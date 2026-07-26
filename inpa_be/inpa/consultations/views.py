from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from inpa.core.permissions import IsEmailVerified
from inpa.billing.credit import LimitExceeded
from inpa.customers.consent_texts import (
    has_current_consultation_recording_consent,
    has_current_consultation_summary_consents,
)
from inpa.customers.models import Customer

from .callbacks import read_clova_callback_token
from .gates import recording_feature_enabled, summary_feature_enabled
from .models import (
    ConsultationCustomerBenefit,
    ConsultationRecording,
    ConsultationSummaryRun,
)
from .quota import usage_snapshot
from .serializers import (
    CompleteUploadRequestSerializer,
    ConsultationRecordingSerializer,
    ConsultationSummaryRunSerializer,
    UploadSessionRequestSerializer,
)
from .services import (
    ConsultationServiceError,
    complete_upload,
    create_part_url,
    create_play_url,
    create_upload_session,
    delete_source,
    max_part_number,
)
from .tasks import process_consultation_summary
from .summary_service import SummaryPrecondition, request_summary


def _service_error_response(exc):
    return Response(
        {'code': exc.code, 'detail': exc.detail},
        status=exc.status_code,
    )


class CustomerRecordingMixin:
    permission_classes = [IsAuthenticated, IsEmailVerified]

    def get_customer(self, customer_pk):
        queryset = Customer.objects.all()
        profile = getattr(self.request.user, 'profile', None)
        if not bool(getattr(profile, 'is_admin', False)):
            queryset = queryset.filter(owner=self.request.user)
        return get_object_or_404(queryset, pk=customer_pk)

    def get_recording(self, customer, recording_id):
        queryset = ConsultationRecording.objects.filter(customer=customer)
        profile = getattr(self.request.user, 'profile', None)
        if not bool(getattr(profile, 'is_admin', False)):
            queryset = queryset.filter(owner=self.request.user)
        return get_object_or_404(queryset, pk=recording_id)


class RecordingListView(CustomerRecordingMixin, APIView):
    def get(self, request, customer_pk):
        customer = self.get_customer(customer_pk)
        queryset = ConsultationRecording.objects.filter(
            customer=customer,
            owner=customer.owner,
        ).select_related('summary_run__memo').order_by('-created_at')
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = ConsultationRecordingSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class RecordingCapabilityView(CustomerRecordingMixin, APIView):
    def get(self, request, customer_pk):
        customer = self.get_customer(customer_pk)
        summary_enabled = summary_feature_enabled(request.user)
        summary_usage = usage_snapshot(user=request.user) if summary_enabled else None
        return Response({
            'recording_enabled': recording_feature_enabled(request.user),
            'consent_ready': has_current_consultation_recording_consent(customer),
            'summary_enabled': summary_enabled,
            'summary_consent_ready':
                has_current_consultation_summary_consents(customer),
            'summary_usage': summary_usage,
            'customer_free_summary_used':
                ConsultationCustomerBenefit.objects.filter(
                    owner=request.user,
                    customer=customer,
                    status=ConsultationCustomerBenefit.STATUS_CONSUMED,
                ).exists(),
            'retention_days': 7,
            'max_duration_seconds': min(
                settings.CONSULTATION_MAX_DURATION_SECONDS,
                3600,
            ),
            'max_bytes': settings.CONSULTATION_MAX_BYTES,
            'part_bytes': settings.CONSULTATION_UPLOAD_PART_BYTES,
            'max_part_number': max_part_number(),
        })


class UploadSessionView(CustomerRecordingMixin, APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'consultation_upload'

    def post(self, request, customer_pk):
        customer = self.get_customer(customer_pk)
        if not recording_feature_enabled(request.user):
            return Response(
                {
                    'code': 'CONSULTATION_RECORDING_CLOSED',
                    'detail': '메모 작성으로 상담 내용을 바로 남길 수 있어요.',
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        if not has_current_consultation_recording_consent(customer):
            return Response(
                {
                    'code': 'CONSULTATION_CONSENT_REQUIRED',
                    'detail': '고객 동의를 먼저 받으면 상담 녹음을 시작할 수 있어요.',
                },
                status=status.HTTP_412_PRECONDITION_FAILED,
            )
        serializer = UploadSessionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            recording, created = create_upload_session(
                owner=customer.owner,
                customer=customer,
                client_session_id=serializer.validated_data['client_session_id'],
                mime_type=serializer.validated_data['mime_type'],
                started_at=serializer.validated_data.get('started_at'),
            )
        except ConsultationServiceError as exc:
            return _service_error_response(exc)
        data = ConsultationRecordingSerializer(recording).data
        data.update({
            'part_bytes': settings.CONSULTATION_UPLOAD_PART_BYTES,
            'max_part_number': max_part_number(),
        })
        return Response(
            data,
            status=(
                status.HTTP_201_CREATED
                if created
                else status.HTTP_200_OK
            ),
        )


class RecordingDetailView(CustomerRecordingMixin, APIView):
    def get(self, request, customer_pk, recording_id):
        customer = self.get_customer(customer_pk)
        recording = self.get_recording(customer, recording_id)
        return Response(ConsultationRecordingSerializer(recording).data)


class RecordingSummarizeView(CustomerRecordingMixin, APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'consultation_summary'

    def post(self, request, customer_pk, recording_id):
        customer = self.get_customer(customer_pk)
        recording = self.get_recording(customer, recording_id)
        try:
            run, created = request_summary(
                recording=recording,
                user=request.user,
                idempotency_key=request.headers.get('Idempotency-Key', ''),
            )
        except SummaryPrecondition as exc:
            return Response(
                {'code': exc.code, 'detail': exc.detail},
                status=exc.status_code,
            )
        except LimitExceeded as exc:
            unit = '분' if exc.action == 'consultation_minute' else '회'
            return Response(
                {
                    'code': 'credit_exhausted',
                    'action': exc.action,
                    'current': exc.current,
                    'limit': exc.limit,
                    'detail': (
                        f'이번 달 상담 요약 한도 {exc.limit}{unit}를 사용했어요. '
                        '요금제를 확인하면 계속 정리할 수 있어요.'
                    ),
                },
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )
        return Response(
            ConsultationSummaryRunSerializer(run).data,
            status=(
                status.HTTP_202_ACCEPTED
                if created
                else status.HTTP_200_OK
            ),
        )


class RecordingPartURLView(CustomerRecordingMixin, APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'consultation_upload'

    def post(self, request, customer_pk, recording_id, part_number):
        customer = self.get_customer(customer_pk)
        recording = self.get_recording(customer, recording_id)
        try:
            url = create_part_url(
                recording=recording,
                part_number=part_number,
            )
        except ConsultationServiceError as exc:
            return _service_error_response(exc)
        return Response({
            'url': url,
            'part_number': part_number,
            'expires_in_seconds': settings.CONSULTATION_PRESIGN_TTL_SECONDS,
        })


class CompleteUploadView(CustomerRecordingMixin, APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'consultation_upload'

    def post(self, request, customer_pk, recording_id):
        customer = self.get_customer(customer_pk)
        self.get_recording(customer, recording_id)
        serializer = CompleteUploadRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            recording = complete_upload(
                recording_id=recording_id,
                owner=customer.owner,
                customer=customer,
                parts=serializer.validated_data['parts'],
                ended_at=serializer.validated_data.get('ended_at'),
            )
        except ConsultationRecording.DoesNotExist as exc:
            raise NotFound('녹음 기록을 찾을 수 없어요.') from exc
        except ConsultationServiceError as exc:
            return _service_error_response(exc)
        return Response(ConsultationRecordingSerializer(recording).data)


class RecordingPlayURLView(CustomerRecordingMixin, APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'consultation_play'

    def post(self, request, customer_pk, recording_id):
        customer = self.get_customer(customer_pk)
        recording = self.get_recording(customer, recording_id)
        try:
            url = create_play_url(recording=recording)
        except ConsultationServiceError as exc:
            return _service_error_response(exc)
        return Response({'url': url, 'expires_in_seconds': 300})


class RecordingSourceDeleteView(CustomerRecordingMixin, APIView):
    def delete(self, request, customer_pk, recording_id):
        customer = self.get_customer(customer_pk)
        self.get_recording(customer, recording_id)
        try:
            recording = delete_source(
                recording_id=recording_id,
                owner=customer.owner,
                customer=customer,
                reason='user_requested',
            )
        except ConsultationRecording.DoesNotExist as exc:
            raise NotFound('녹음 기록을 찾을 수 없어요.') from exc
        except ConsultationServiceError as exc:
            return _service_error_response(exc)
        return Response(ConsultationRecordingSerializer(recording).data)


class ClovaCallbackView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'consultation_callback'

    def post(self, request, token):
        try:
            run_id, attempt_uuid = read_clova_callback_token(token)
        except Exception:
            raise NotFound('요청 정보를 찾을 수 없어요.')
        exists = ConsultationSummaryRun.objects.filter(
            pk=run_id,
            attempt_uuid=attempt_uuid,
        ).exists()
        if not exists:
            raise NotFound('요청 정보를 찾을 수 없어요.')
        process_consultation_summary.apply_async(
            args=[str(run_id)],
            queue='consultation_summaries',
        )
        return Response({'accepted': True}, status=status.HTTP_202_ACCEPTED)
