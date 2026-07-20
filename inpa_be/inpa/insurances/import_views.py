import hashlib
import logging
import re
import secrets
import uuid

from django.conf import settings
from django.core import signing
from django.core.files.storage import storages
from django.http import FileResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.clickjacking import xframe_options_exempt
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from inpa.billing.credit import LimitExceeded
from inpa.core.permissions import IsEmailVerified

from . import import_services
from .import_pdf import MAX_FILE_BYTES
from .import_serializers import (
    InsuranceImportCancelSerializer,
    InsuranceImportConfirmSerializer,
    InsuranceImportCreateSerializer,
    InsuranceImportDraftPatchSerializer,
    InsuranceImportJobSerializer,
)
from .import_storage import assert_source_namespace
from .models import InsuranceExtractionJob


logger = logging.getLogger(__name__)
_SOURCE_TOKEN_SALT = 'inpa.insurance-import-source.v1'
_SOURCE_TOKEN_MAX_AGE = 300


class _ReviewGateMixin:
    def initial(self, request, *args, **kwargs):
        if not settings.INSURANCE_REVIEW_GATE_ENABLED:
            raise NotFound()
        return super().initial(request, *args, **kwargs)


def _owned_job(user, job_id):
    try:
        return InsuranceExtractionJob.objects.select_related(
            'target_insurance').get(
            id=job_id,
            owner=user,
            customer__owner=user,
        )
    except (InsuranceExtractionJob.DoesNotExist, ValueError) as exc:
        raise NotFound() from exc


def _private_response(data, *, status_code=status.HTTP_200_OK):
    response = Response(data, status=status_code)
    response['Cache-Control'] = 'private, no-store'
    return response


def _error_response(exc):
    body = {'code': exc.code, 'detail': exc.detail, **exc.extra}
    return _private_response(body, status_code=exc.status_code)


def _credit_error_response(exc, user):
    from inpa.billing.models import Subscription

    subscription = (
        Subscription.objects.select_related('plan').filter(user=user).first())
    return _private_response({
        'detail': f'이번 달 한도({exc.limit}건)를 모두 사용했어요.',
        'code': 'credit_exhausted',
        'kind': exc.action,
        'membership': subscription.plan.code if subscription else 'free',
        'limit': exc.limit,
        'used': exc.current,
    }, status_code=status.HTTP_402_PAYMENT_REQUIRED)


def _parse_idempotency_key(request, *, required):
    raw_value = request.headers.get('Idempotency-Key')
    if not raw_value:
        if required:
            raise import_services.ImportReceptionError(
                'IDEMPOTENCY_KEY_REQUIRED', status_code=400,
                detail='요청을 안전하게 이어갈 수 있도록 다시 시도해 주세요.')
        return uuid.uuid4()
    try:
        return uuid.UUID(raw_value)
    except (TypeError, ValueError, AttributeError) as exc:
        raise import_services.ImportReceptionError(
            'INVALID_IDEMPOTENCY_KEY', status_code=400,
            detail='요청 정보를 새로 고친 뒤 다시 시도해 주세요.') from exc


def _run_create(request, customer_pk, *, legacy=False):
    serializer = InsuranceImportCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        idempotency_key = _parse_idempotency_key(
            request, required=not legacy)
        result = import_services.receive_import(
            owner=request.user,
            customer_pk=customer_pk,
            uploaded_file=serializer.validated_data['file'],
            intent=serializer.validated_data.get('intent', 'add'),
            portfolio_type=serializer.validated_data.get('portfolio_type', 1),
            target_insurance_id=serializer.validated_data.get(
                'target_insurance_id'),
            duplicate_resolution_token=serializer.validated_data.get(
                'duplicate_resolution_token'),
            idempotency_key=idempotency_key,
        )
    except import_services.ImportReceptionError as exc:
        return _error_response(exc)
    except LimitExceeded as exc:
        return _credit_error_response(exc, request.user)
    except Exception as exc:
        logger.warning(
            '[insurance-import] reception failed type=%s',
            type(exc).__name__)
        return _private_response({
            'code': 'IMPORT_UNAVAILABLE',
            'detail': '증권 원문을 다시 선택해 주세요.',
        }, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    return _private_response(
        result.response_body,
        status_code=result.response_status,
    )


def delegate_legacy_import(request, customer):
    """Keep /ocr as an alias only; gate ON never reaches immediate saving."""
    return _run_create(request, customer.pk, legacy=True)


class InsuranceImportCollectionView(_ReviewGateMixin, APIView):
    permission_classes = [IsAuthenticated, IsEmailVerified]
    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [ScopedRateThrottle]
    create_throttle_scope = 'ocr'
    read_throttle_scope = 'insurance_import'

    def get_throttles(self):
        self.throttle_scope = (
            self.create_throttle_scope
            if self.request.method == 'POST'
            else self.read_throttle_scope
        )
        return super().get_throttles()

    def post(self, request, customer_pk):
        return _run_create(request, customer_pk)

    def get(self, request, customer_pk):
        # Both dimensions are explicit even though Customer.owner already
        # implies the job owner. This prevents drift if either relation changes.
        queryset = (
            InsuranceExtractionJob.objects
            .select_related('target_insurance')
            .filter(
                owner=request.user,
                customer_id=customer_pk,
                customer__owner=request.user,
            )
            .order_by('-created_at')
        )
        if not queryset.exists():
            from inpa.customers.models import Customer
            if not Customer.objects.filter(
                    pk=customer_pk, owner=request.user).exists():
                raise NotFound()
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = InsuranceImportJobSerializer(page, many=True)
        response = paginator.get_paginated_response(serializer.data)
        response['Cache-Control'] = 'private, no-store'
        return response


class InsuranceImportDetailView(_ReviewGateMixin, APIView):
    permission_classes = [IsAuthenticated, IsEmailVerified]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'insurance_import'

    def get(self, request, job_id):
        job = _owned_job(request.user, job_id)
        return _private_response(InsuranceImportJobSerializer(job).data)


class InsuranceImportDraftView(_ReviewGateMixin, APIView):
    permission_classes = [IsAuthenticated, IsEmailVerified]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'insurance_import'

    def get(self, request, job_id):
        try:
            body = import_services.get_import_draft(
                owner=request.user, job_id=job_id)
        except import_services.ImportReceptionError as exc:
            return _error_response(exc)
        return _private_response(body)

    def patch(self, request, job_id):
        # Hide foreign UUID existence before header/body validation. The
        # service repeats the same two-dimensional authority check under lock.
        _owned_job(request.user, job_id)
        try:
            idempotency_key = _parse_idempotency_key(
                request, required=True)
        except import_services.ImportReceptionError as exc:
            return _error_response(exc)
        serializer = InsuranceImportDraftPatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            response_status, body = import_services.patch_import_draft(
                owner=request.user,
                job_id=job_id,
                payload=serializer.validated_data,
                idempotency_key=idempotency_key,
            )
        except import_services.ImportReceptionError as exc:
            return _error_response(exc)
        return _private_response(body, status_code=response_status)


class InsuranceImportCancelView(_ReviewGateMixin, APIView):
    permission_classes = [IsAuthenticated, IsEmailVerified]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'insurance_import'

    def post(self, request, job_id):
        _owned_job(request.user, job_id)
        try:
            idempotency_key = _parse_idempotency_key(
                request, required=True)
        except import_services.ImportReceptionError as exc:
            return _error_response(exc)
        serializer = InsuranceImportCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            response_status, body = import_services.cancel_import(
                owner=request.user,
                job_id=job_id,
                idempotency_key=idempotency_key,
            )
        except import_services.ImportReceptionError as exc:
            return _error_response(exc)
        return _private_response(body, status_code=response_status)


class InsuranceImportConfirmView(_ReviewGateMixin, APIView):
    permission_classes = [IsAuthenticated, IsEmailVerified]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'insurance_import'

    def post(self, request, job_id):
        # Scope first so foreign UUIDs stay hidden even with malformed input.
        _owned_job(request.user, job_id)
        try:
            idempotency_key = _parse_idempotency_key(
                request, required=True)
        except import_services.ImportReceptionError as exc:
            return _error_response(exc)
        serializer = InsuranceImportConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            response_status, body = import_services.confirm_import(
                owner=request.user,
                job_id=job_id,
                payload=serializer.validated_data,
                idempotency_key=idempotency_key,
            )
        except import_services.ImportReceptionError as exc:
            return _error_response(exc)
        except Exception as exc:
            logger.warning(
                '[insurance-import] confirmation failed job=%s type=%s',
                job_id, type(exc).__name__)
            return _private_response({
                'code': 'IMPORT_CONFIRM_UNAVAILABLE',
                'detail': '저장 내용을 그대로 두었어요. 다시 확인해 주세요.',
            }, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        return _private_response(body, status_code=response_status)


def _source_ready(job):
    return bool(
        job.source_storage_key
        and job.source_deleted_at is None
        and job.source_expires_at is not None
        and job.source_expires_at > timezone.now()
    )


def _source_digest(key):
    return hashlib.sha256(key.encode('utf-8')).hexdigest()


def _source_token(job):
    return signing.dumps(
        {'job_id': str(job.id), 'source_digest': _source_digest(
            job.source_storage_key)},
        key=settings.SECRET_KEY,
        salt=_SOURCE_TOKEN_SALT,
        compress=True,
    )


def _is_s3_storage(storage):
    return storage.__class__.__module__.startswith('storages.backends.s3')


def _signed_s3_url(storage, job):
    return storage.url(
        job.source_storage_key,
        parameters={
            'ResponseContentDisposition': 'inline',
            'ResponseCacheControl': 'private,no-store',
        },
        expire=_SOURCE_TOKEN_MAX_AGE,
    )


class InsuranceImportSourceURLView(_ReviewGateMixin, APIView):
    permission_classes = [IsAuthenticated, IsEmailVerified]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'insurance_import_source'

    def get(self, request, job_id):
        job = _owned_job(request.user, job_id)
        if not _source_ready(job):
            raise NotFound()
        try:
            assert_source_namespace(job, job.source_storage_key)
            storage = storages['insurance_sources']
            if not storage.exists(job.source_storage_key):
                raise NotFound()
            if _is_s3_storage(storage):
                url = _signed_s3_url(storage, job)
            else:
                token = _source_token(job)
                url = request.build_absolute_uri(reverse(
                    'insurances:insurance-import-source-preview',
                    kwargs={'token': token},
                ))
        except NotFound:
            raise
        except Exception as exc:
            logger.warning(
                '[insurance-import] source url failed job=%s type=%s',
                job.id, type(exc).__name__)
            raise NotFound() from exc
        return _private_response({
            'url': url,
            'expires_in': _SOURCE_TOKEN_MAX_AGE,
        })


def _frame_ancestors():
    allowed = ["'self'"]
    for origin in getattr(settings, 'CORS_ALLOWED_ORIGINS', ()):
        if re.fullmatch(r'https?://[A-Za-z0-9.:-]+', origin):
            allowed.append(origin)
    return ' '.join(dict.fromkeys(allowed))


@method_decorator(xframe_options_exempt, name='dispatch')
class InsuranceImportSourcePreviewView(_ReviewGateMixin, APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'insurance_import_source'

    def get(self, request, token):
        try:
            payload = signing.loads(
                token,
                key=settings.SECRET_KEY,
                salt=_SOURCE_TOKEN_SALT,
                max_age=_SOURCE_TOKEN_MAX_AGE,
            )
            if not isinstance(payload, dict) or set(payload) != {
                    'job_id', 'source_digest'}:
                raise NotFound()
            job = InsuranceExtractionJob.objects.get(id=payload['job_id'])
            if (not _source_ready(job)
                    or not secrets.compare_digest(
                        payload['source_digest'],
                        _source_digest(job.source_storage_key))):
                raise NotFound()
            assert_source_namespace(job, job.source_storage_key)
            storage = storages['insurance_sources']
            if _is_s3_storage(storage) or not storage.exists(
                    job.source_storage_key):
                raise NotFound()
            source = storage.open(job.source_storage_key, 'rb')
        except NotFound:
            raise
        except Exception as exc:
            raise NotFound() from exc

        response = FileResponse(
            source, content_type='application/pdf', as_attachment=False,
            filename='source.pdf')
        response['Cache-Control'] = 'private, no-store'
        response['Content-Disposition'] = 'inline; filename="source.pdf"'
        response['Content-Security-Policy'] = (
            "default-src 'none'; frame-ancestors " + _frame_ancestors())
        response['X-Content-Type-Options'] = 'nosniff'
        response['Referrer-Policy'] = 'no-referrer'
        return response


class InsuranceImportConfigView(APIView):
    permission_classes = [IsAuthenticated, IsEmailVerified]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'insurance_import'

    def get(self, request):
        return _private_response({
            'review_workflow_enabled': bool(
                settings.INSURANCE_REVIEW_GATE_ENABLED),
            'accepted_input': 'digital_pdf',
            'max_file_bytes': MAX_FILE_BYTES,
        })
