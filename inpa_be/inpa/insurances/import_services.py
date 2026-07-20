import copy
import hashlib
import json
import logging
import re
import secrets
import uuid
from dataclasses import asdict, dataclass
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from inpa.analysis.management.commands.seed_normalization import (
    SEED_VERSION,
    STANDARD_TREE,
)
from inpa.analysis.models import AnalysisDetail
from inpa.billing.credit import LimitExceeded, check_and_consume
from inpa.billing.models import UsageMeter
from inpa.customers.consent_texts import has_current_overseas_consent
from inpa.customers.models import Customer

from .date_utils import normalize_insurance_date, parse_insurance_date
from .import_contract import (
    PDFImportError,
    apply_source_review_issue,
    extracted_source_readability,
    safe_confirmation_requirements,
    safe_import_target,
    safe_source_review,
)
from .import_pdf import extract_pdf
from .import_storage import delete_source, save_source
from .import_validation import (
    MANUAL_COVERAGE_FIELDS,
    STANDARD_COVERAGE_PATHS,
    apply_force_manual_review,
    validate_draft,
)
from .models import (
    CustomerInsurance,
    CustomerInsuranceDetail,
    InsuranceDetail,
    InsuranceExtractionJob,
    InsuranceImportCommand,
    InsuranceImportCreateRequest,
)


logger = logging.getLogger(__name__)
CURRENT_NORMALIZATION_VERSION = f'seed-normalization-{SEED_VERSION}'
_DUPLICATE_RESOLUTION_SALT = 'inpa.insurance-import-duplicate.v1'
_DUPLICATE_RESOLUTION_MAX_AGE = 300

_POLICY_FIELDS = (
    'carrier_name', 'company_code', 'insurance_type', 'product_name',
    'contract_date', 'expiry_date', 'monthly_premium',
)
_COVERAGE_FIELDS = (
    'row_id', 'raw_name', 'assurance_amount', 'premium', 'is_renewal',
    'renewal_period', 'payment_period', 'payment_period_unit',
    'warranty_period', 'warranty_period_unit', 'disposition',
    'standard_category', 'standard_subcategory', 'standard_detail_name',
    'exclusion_reason', 'duplicate_of_row_id', 'source_candidate_ids',
    'evidence_line_ids', 'state', 'review_reason_codes',
)
_STANDARD_COVERAGE_ITEMS = tuple(
    {
        'category': category,
        'subcategory': subcategory,
        'detail_name': detail_name,
    }
    for category, _insurance_type, subcategories in STANDARD_TREE
    for subcategory, details in subcategories
    for detail_name, _chart_based_amount in details
)


def standard_coverage_catalog():
    """Return the versioned standard-coverage write catalog."""
    return {
        'version': CURRENT_NORMALIZATION_VERSION,
        'items': [copy.deepcopy(item) for item in _STANDARD_COVERAGE_ITEMS],
    }


@dataclass(frozen=True)
class ImportReceptionResult:
    job: InsuranceExtractionJob | None
    duplicate_kind: str
    response_status: int
    response_body: dict


class ImportReceptionError(Exception):
    def __init__(self, code, *, status_code, detail, extra=None):
        self.code = code
        self.status_code = status_code
        self.detail = detail
        self.extra = extra or {}
        super().__init__(code)


_PDF_ERROR_DETAILS = {
    'FILE_TOO_LARGE': '50MB 이하의 전자 PDF를 선택해 주세요.',
    'INVALID_PDF': '전자 PDF 형식 파일을 선택해 주세요.',
    'ENCRYPTED_PDF': '암호를 해제한 전자 PDF를 선택해 주세요.',
    'IMAGE_PDF': '텍스트를 선택할 수 있는 전자 PDF를 선택해 주세요.',
    'TOO_MANY_PAGES': '300쪽 이하의 전자 PDF를 선택해 주세요.',
    'DOCUMENT_TOO_LONG': '문서 분량을 줄인 전자 PDF를 선택해 주세요.',
    'TOO_MANY_CANDIDATES': '한 번에 확인할 담보가 더 적은 전자 PDF를 선택해 주세요.',
    'PDF_PARSE_TIMEOUT': '증권 원문을 다시 선택해 주세요.',
    'PDF_PARSE_RESOURCE_LIMIT': '증권 원문을 나누어 다시 선택해 주세요.',
    'PDF_PARSE_FAILED': '증권 원문을 다시 선택해 주세요.',
}


def _safe_display_name(name):
    value = str(name or 'policy.pdf').replace('\\', '/').rsplit('/', 1)[-1]
    value = re.sub(
        r'[\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]+', '', value).strip()
    if not value.lower().endswith('.pdf'):
        value = 'policy.pdf'
    if len(value) > 120:
        value = value[:116] + '.pdf'
    return value or 'policy.pdf'


def _same_create_request(job, *, customer_id, extracted, intent, portfolio_type,
                         target_insurance_id, duplicate_resolution_token=None):
    return (
        not duplicate_resolution_token
        and job.customer_id == customer_id
        and job.file_sha256 == extracted.file_sha256
        and job.file_size == extracted.file_size
        and job.intent == intent
        and job.portfolio_type == portfolio_type
        and job.target_insurance_id == target_insurance_id
    )


def _candidate_payload(candidate):
    payload = asdict(candidate)
    payload['evidence_line_ids'] = list(payload['evidence_line_ids'])
    return payload


def _get_scoped_customer(owner, customer_pk):
    try:
        return Customer.objects.get(pk=customer_pk, owner=owner)
    except Customer.DoesNotExist as exc:
        raise ImportReceptionError(
            'NOT_FOUND', status_code=404,
            detail='고객을 찾을 수 없습니다.') from exc


def _get_scoped_target(customer, target_insurance_id):
    if target_insurance_id is None:
        return None
    try:
        return CustomerInsurance.objects.get(
            pk=target_insurance_id,
            customer=customer,
            customer__owner=customer.owner,
        )
    except CustomerInsurance.DoesNotExist as exc:
        raise ImportReceptionError(
            'NOT_FOUND', status_code=404,
            detail='보험을 찾을 수 없습니다.') from exc


def _consent_error(customer):
    reason = 'reconsent' if customer.consent_overseas_at else 'missing'
    return ImportReceptionError(
        'CONSENT_OVERSEAS_REQUIRED', status_code=412,
        detail='고객 동의를 먼저 보내면 바로 분석할 수 있어요.',
        extra={'reason': reason})


def _confirmed_duplicate(owner, customer, extracted, portfolio_type):
    return (
        InsuranceExtractionJob.objects
        .select_for_update()
        .select_related('confirmed_insurance__customer')
        .filter(
            owner=owner,
            customer=customer,
            file_sha256=extracted.file_sha256,
            portfolio_type=portfolio_type,
            status='confirmed',
            confirmed_insurance__isnull=False,
            confirmed_insurance__customer=customer,
            confirmed_insurance__customer__owner=owner,
        )
        .order_by('-confirmed_at', '-created_at')
        .first()
    )


def _duplicate_resolution_error():
    return ImportReceptionError(
        'DUPLICATE_RESOLUTION_INVALID', status_code=409,
        detail='같은 증권의 등록 방식을 다시 선택해 주세요.')


def _duplicate_resolution_used_error():
    return ImportReceptionError(
        'DUPLICATE_RESOLUTION_USED', status_code=409,
        detail='이미 선택한 방식으로 증권 확인을 시작했어요.')


def _duplicate_resolution_superseded_error_body():
    return {
        'code': 'DUPLICATE_RESOLUTION_SUPERSEDED',
        'detail': '먼저 선택한 등록 방식으로 증권 확인을 이어가고 있어요.',
    }


def _consume_duplicate_resolution(request_id, job_id):
    """Consume one server-issued resolution with a single database CAS."""
    return InsuranceImportCreateRequest.objects.filter(
        pk=request_id,
        resolution_job__isnull=True,
    ).update(resolution_job_id=job_id) == 1


def _duplicate_resolution_token(resolution_request):
    return signing.dumps({
        'resolution_request_id': resolution_request.pk,
    }, key=settings.SECRET_KEY, salt=_DUPLICATE_RESOLUTION_SALT,
       compress=True)


def _scoped_confirmed_insurance(job, *, owner, customer):
    if (job is None
            or job.status != 'confirmed'
            or job.owner_id != owner.pk
            or job.customer_id != customer.pk):
        raise _duplicate_resolution_error()
    try:
        insurance = (
            CustomerInsurance.objects
            .select_for_update()
            .select_related('customer')
            .get(
                source_job=job,
                customer=customer,
                customer__owner=owner,
            )
        )
    except CustomerInsurance.DoesNotExist:
        raise _duplicate_resolution_error()
    return insurance


def _validate_duplicate_resolution(*, token, owner, customer, extracted,
                                   portfolio_type, intent, target):
    if not token:
        return False
    try:
        payload = signing.loads(
            token, key=settings.SECRET_KEY,
            salt=_DUPLICATE_RESOLUTION_SALT,
            max_age=_DUPLICATE_RESOLUTION_MAX_AGE)
    except (signing.BadSignature, signing.SignatureExpired, TypeError,
            ValueError):
        raise _duplicate_resolution_error()
    if (not isinstance(payload, dict)
            or set(payload) != {'resolution_request_id'}
            or type(payload['resolution_request_id']) is not int
            or payload['resolution_request_id'] <= 0):
        raise _duplicate_resolution_error()
    request_id = payload['resolution_request_id']
    try:
        resolution_request = (
            InsuranceImportCreateRequest.objects
            .select_for_update()
            .get(
                pk=request_id,
                owner=owner,
                response_status=409,
            )
        )
    except (InsuranceImportCreateRequest.DoesNotExist, TypeError, ValueError):
        raise _duplicate_resolution_error()
    if resolution_request.resolution_job_id is not None:
        raise _duplicate_resolution_used_error()
    if resolution_request.job_id is None:
        raise _duplicate_resolution_error()
    try:
        confirmed = (
            InsuranceExtractionJob.objects
            .select_for_update()
            .get(
                pk=resolution_request.job_id,
                owner=owner,
                customer=customer,
                file_sha256=extracted.file_sha256,
                portfolio_type=portfolio_type,
                status='confirmed',
            )
        )
    except InsuranceExtractionJob.DoesNotExist:
        raise _duplicate_resolution_error()
    insurance = _scoped_confirmed_insurance(
        confirmed, owner=owner, customer=customer)
    body = resolution_request.response_body
    if (not isinstance(body, dict)
            or body.get('code') != 'DUPLICATE_CONFIRMED'
            or body.get('insurance_id') != insurance.pk
            or body.get('insurance_version') != insurance.data_version
            or body.get('allowed_intents') != ['replace']):
        raise _duplicate_resolution_error()
    stored_token = resolution_request.response_body.get(
        'duplicate_resolution_token')
    if (not isinstance(stored_token, str)
            or not secrets.compare_digest(stored_token, token)):
        raise _duplicate_resolution_error()
    if (intent != 'replace'
            or target is None
            or target.pk != insurance.pk):
        raise _duplicate_resolution_error()
    return resolution_request


def _duplicate_confirmed_body(owner, customer, job, resolution_request):
    insurance = _scoped_confirmed_insurance(
        job, owner=owner, customer=customer)
    return {
        'code': 'DUPLICATE_CONFIRMED',
        'detail': '이미 확인을 마친 같은 증권이 있어요.',
        'insurance_id': insurance.pk,
        'insurance_version': insurance.data_version,
        'allowed_intents': ['replace'],
        'duplicate_resolution_token': _duplicate_resolution_token(
            resolution_request),
    }


def _create_request_sha256(*, customer_id, extracted, intent,
                           portfolio_type, target_insurance_id,
                           duplicate_resolution_token=None):
    payload = {
        'customer_id': customer_id,
        'file_sha256': extracted.file_sha256,
        'file_size': extracted.file_size,
        'intent': intent,
        'portfolio_type': portfolio_type,
        'target_insurance_id': target_insurance_id,
        'duplicate_resolution_token_sha256': (
            hashlib.sha256(duplicate_resolution_token.encode('utf-8')).hexdigest()
            if duplicate_resolution_token else None),
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _success_body(job, *, status_value=None):
    return {
        'job_id': str(job.id),
        'status': status_value or job.status,
    }


def _complete_create_request(record, *, job, status_code, body,
                             duplicate_kind):
    record.job = job
    record.response_status = status_code
    record.response_body = body
    record.completed_at = timezone.now()
    record.save(update_fields=(
        'job', 'response_status', 'response_body', 'completed_at'))
    return ImportReceptionResult(
        job=job,
        duplicate_kind=duplicate_kind,
        response_status=status_code,
        response_body=body,
    )


def _replay_create_request(record, request_sha256):
    if not secrets.compare_digest(record.request_sha256, request_sha256):
        raise ImportReceptionError(
            'IDEMPOTENCY_KEY_REUSED', status_code=409,
            detail='같은 요청 키에는 같은 증권만 사용할 수 있어요.')
    if record.response_status is None or not record.response_body:
        raise ImportReceptionError(
            'IDEMPOTENCY_REQUEST_IN_PROGRESS', status_code=409,
            detail='앞선 접수를 확인하고 있어요. 잠시 후 다시 시도해 주세요.')
    return ImportReceptionResult(
        job=record.job,
        duplicate_kind='idempotent_replay',
        response_status=record.response_status,
        response_body=dict(record.response_body),
    )


def _source_is_available(job, now):
    return bool(
        job.source_storage_key
        and job.source_deleted_at is None
        and job.source_expires_at is not None
        and job.source_expires_at > now
    )


def _reattach_review_source(job, uploaded_file, now):
    old_key = job.source_storage_key
    if old_key and job.source_deleted_at is None:
        # The system retention deadline has passed. Delete only the exact,
        # namespace-verified key before recreating that same deterministic key.
        delete_source(job, key=old_key)
    stored_key = save_source(job, uploaded_file)
    job.source_storage_key = stored_key
    job.source_expires_at = now + timedelta(
        hours=settings.INSURANCE_SOURCE_RETENTION_HOURS)
    job.source_deleted_at = None
    job.save(update_fields=(
        'source_storage_key', 'source_expires_at', 'source_deleted_at'))


def _enqueue_job(job_id):
    # Task 6 supplies the worker. Keeping this import lazy lets the dormant
    # gate and all non-import processes start before that module exists.
    from .tasks import process_insurance_import
    process_insurance_import.delay(job_id)


def _refund_queue_failure_once(job_id, *, refund_credit=True):
    # Keep queue-publish compensation on the same owner -> job -> meter CAS
    # boundary used by worker and retention failures.
    from .tasks import _fail_queued_job
    return _fail_queued_job(
        job_id,
        code='QUEUE_UNAVAILABLE',
        error_type='queue_publish',
        refund_credit=refund_credit,
    )


def _publish_job(job_id, *, refund_credit):
    try:
        _enqueue_job(job_id)
    except Exception as exc:
        logger.warning(
            '[insurance-import] queue publish failed job=%s type=%s',
            job_id, type(exc).__name__)
        try:
            _refund_queue_failure_once(
                job_id, refund_credit=refund_credit)
        except Exception as refund_exc:
            logger.warning(
                '[insurance-import] queue failure recovery failed '
                'job=%s type=%s',
                job_id, type(refund_exc).__name__)


def receive_import(*, owner, customer_pk, uploaded_file, intent='add',
                   portfolio_type=1, target_insurance_id=None,
                   duplicate_resolution_token=None,
                   idempotency_key):
    """Receive one digital policy and converge all duplicates to one job."""
    customer = _get_scoped_customer(owner, customer_pk)
    target = _get_scoped_target(customer, target_insurance_id)
    if not has_current_overseas_consent(customer):
        raise _consent_error(customer)

    try:
        extracted = extract_pdf(uploaded_file)
    except PDFImportError as exc:
        raise ImportReceptionError(
            exc.code, status_code=400,
            detail=_PDF_ERROR_DETAILS.get(
                exc.code, '증권 원문을 다시 선택해 주세요.')) from exc

    request_sha256 = _create_request_sha256(
        customer_id=customer.pk,
        extracted=extracted,
        intent=intent,
        portfolio_type=portfolio_type,
        target_insurance_id=target.pk if target else None,
        duplicate_resolution_token=duplicate_resolution_token,
    )
    source_written_job = None
    try:
        with transaction.atomic():
            type(owner).objects.select_for_update().get(pk=owner.pk)
            replay_record = (
                InsuranceImportCreateRequest.objects
                .select_for_update()
                .filter(owner=owner, idempotency_key=idempotency_key)
                .first()
            )
            if replay_record is not None:
                return _replay_create_request(
                    replay_record, request_sha256)

            # Compatibility for jobs accepted before the dedicated immutable
            # request ledger existed. The first post-upgrade replay freezes the
            # safest response still available from that job.
            legacy_replay = (
                InsuranceExtractionJob.objects
                .select_for_update()
                .filter(owner=owner, create_idempotency_key=idempotency_key)
                .first()
            )
            if legacy_replay is not None:
                if not _same_create_request(
                        legacy_replay, customer_id=customer.pk,
                        extracted=extracted, intent=intent,
                        portfolio_type=portfolio_type,
                        target_insurance_id=target.pk if target else None,
                        duplicate_resolution_token=(
                            duplicate_resolution_token)):
                    raise ImportReceptionError(
                        'IDEMPOTENCY_KEY_REUSED', status_code=409,
                        detail='같은 요청 키에는 같은 증권만 사용할 수 있어요.')
                legacy_record = InsuranceImportCreateRequest.objects.create(
                    owner=owner,
                    job=legacy_replay,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                )
                return _complete_create_request(
                    legacy_record,
                    job=legacy_replay,
                    status_code=202,
                    body=_success_body(legacy_replay),
                    duplicate_kind='legacy_idempotent_replay',
                )

            create_request = InsuranceImportCreateRequest.objects.create(
                owner=owner,
                idempotency_key=idempotency_key,
                request_sha256=request_sha256,
            )
            now = timezone.now()
            # PDF preflight can take time. Re-lock and revalidate the scope and
            # current consent immediately before any permanent source write or
            # queue publish so an owner transfer/revocation cannot race intake.
            try:
                customer = Customer.objects.select_for_update().get(
                    pk=customer.pk, owner=owner)
            except Customer.DoesNotExist as exc:
                raise ImportReceptionError(
                    'NOT_FOUND', status_code=404,
                    detail='고객을 찾을 수 없습니다.') from exc
            if not has_current_overseas_consent(customer):
                raise _consent_error(customer)
            if target is not None:
                try:
                    target = CustomerInsurance.objects.select_for_update().get(
                        pk=target.pk,
                        customer=customer,
                        customer__owner=owner,
                    )
                except CustomerInsurance.DoesNotExist as exc:
                    raise ImportReceptionError(
                        'NOT_FOUND', status_code=404,
                        detail='보험을 찾을 수 없습니다.') from exc

            active = (
                InsuranceExtractionJob.objects
                .select_for_update()
                .filter(
                    owner=owner,
                    customer=customer,
                    file_sha256=extracted.file_sha256,
                    portfolio_type=portfolio_type,
                    status__in=InsuranceExtractionJob.ACTIVE_STATUSES,
                )
                .order_by('-created_at')
                .first()
            )
            if active is not None and not duplicate_resolution_token:
                if (active.status == 'review_required'
                        and not _source_is_available(active, now)):
                    try:
                        _reattach_review_source(active, uploaded_file, now)
                        source_written_job = active
                    except Exception:
                        # A source save has no DB transaction semantics. Remove
                        # only this job's exact key if a partial write occurred.
                        try:
                            delete_source(active)
                        except Exception:
                            pass
                        raise
                    return _complete_create_request(
                        create_request,
                        job=active,
                        status_code=202,
                        body=_success_body(
                            active, status_value='review_required'),
                        duplicate_kind='source_reattached',
                    )
                return _complete_create_request(
                    create_request,
                    job=active,
                    status_code=202,
                    body=_success_body(active),
                    duplicate_kind='active_duplicate',
                )

            resolution_request = None
            if duplicate_resolution_token:
                resolution_request = _validate_duplicate_resolution(
                    token=duplicate_resolution_token,
                    owner=owner,
                    customer=customer,
                    extracted=extracted,
                    portfolio_type=portfolio_type,
                    intent=intent,
                    target=target,
                )
            else:
                confirmed = _confirmed_duplicate(
                    owner, customer, extracted, portfolio_type)
                if confirmed is not None:
                    return _complete_create_request(
                        create_request,
                        job=confirmed,
                        status_code=409,
                        body=_duplicate_confirmed_body(
                            owner, customer, confirmed, create_request),
                        duplicate_kind='confirmed_duplicate',
                    )

            if active is not None:
                if (resolution_request is None
                        or not _consume_duplicate_resolution(
                            resolution_request.pk, active.pk)):
                    raise _duplicate_resolution_used_error()
                same_resolution = (
                    active.intent == intent
                    and active.target_insurance_id == (
                        target.pk if target is not None else None)
                )
                if not same_resolution:
                    return _complete_create_request(
                        create_request,
                        job=active,
                        status_code=409,
                        body=_duplicate_resolution_superseded_error_body(),
                        duplicate_kind='resolution_superseded',
                    )
                return _complete_create_request(
                    create_request,
                    job=active,
                    status_code=202,
                    body=_success_body(active),
                    duplicate_kind='resolution_converged',
                )

            queued_count = InsuranceExtractionJob.objects.filter(
                owner=owner, status='queued').count()
            if queued_count >= settings.INSURANCE_MAX_QUEUED_PER_OWNER:
                raise ImportReceptionError(
                    'TOO_MANY_QUEUED_IMPORTS', status_code=429,
                    detail='진행 중인 증권이 끝나면 다음 증권을 바로 등록할 수 있어요.')

            credit_result = check_and_consume(owner, 'ocr')
            credit_count = credit_result.get('count')
            credit_consumed = (
                type(credit_count) is int and credit_count > 0)
            credit_year_month = credit_result.get('year_month')
            stored_job = InsuranceExtractionJob.objects.create(
                owner=owner,
                customer=customer,
                target_insurance=target,
                target_insurance_version=(
                    target.data_version if target is not None else None),
                intent=intent,
                portfolio_type=portfolio_type,
                status='queued',
                file_sha256=extracted.file_sha256,
                file_size=extracted.file_size,
                page_count=extracted.page_count,
                safe_display_name=_safe_display_name(uploaded_file.name),
                source_expires_at=now + timedelta(
                    hours=settings.INSURANCE_SOURCE_RETENTION_HOURS),
                masked_lines=[asdict(line) for line in extracted.masked_lines],
                validation_summary={
                    'intake_candidates': [
                        _candidate_payload(candidate)
                        for candidate in extracted.candidates
                    ],
                    # Reserved server-only accounting metadata. Job serializers
                    # intentionally do not expose validation_summary.
                    '_system': {
                        'credit_consumed': credit_consumed,
                        'credit_refunded': False,
                        'credit_year_month': credit_year_month,
                        'source_readability': extracted_source_readability(
                            extracted),
                    },
                },
                create_idempotency_key=idempotency_key,
            )
            if (resolution_request is not None
                    and not _consume_duplicate_resolution(
                        resolution_request.pk, stored_job.pk)):
                raise _duplicate_resolution_used_error()
            stored_key = save_source(stored_job, uploaded_file)
            source_written_job = stored_job
            stored_job.source_storage_key = stored_key
            stored_job.save(update_fields=['source_storage_key'])
            result = _complete_create_request(
                create_request,
                job=stored_job,
                status_code=202,
                body=_success_body(stored_job, status_value='queued'),
                duplicate_kind='created',
            )
            queued_job_id = str(stored_job.id)
            transaction.on_commit(
                lambda: _publish_job(
                    queued_job_id, refund_credit=credit_consumed))
    except (ImportReceptionError, LimitExceeded):
        raise
    except Exception:
        if source_written_job is not None:
            try:
                delete_source(source_written_job)
            except Exception:
                pass
        raise

    return result


def _owned_import_job(owner, job_id, *, for_update=False):
    queryset = InsuranceExtractionJob.objects
    if for_update:
        queryset = queryset.select_for_update()
    try:
        return queryset.get(
            pk=job_id,
            owner=owner,
            customer__owner=owner,
        )
    except (InsuranceExtractionJob.DoesNotExist, ValueError) as exc:
        raise ImportReceptionError(
            'NOT_FOUND', status_code=404,
            detail='증권 작업을 찾을 수 없습니다.') from exc


def _assert_review_ready(job):
    if job.status == 'canceled':
        raise ImportReceptionError(
            'IMPORT_CANCELED', status_code=409,
            detail='취소한 증권은 새로 등록하면 다시 확인할 수 있어요.')
    if job.status != 'review_required':
        raise ImportReceptionError(
            'DRAFT_NOT_READY', status_code=409,
            detail='자동 정리가 끝나면 바로 확인할 수 있어요.')


def _assert_normalization_version(job):
    if (not job.normalization_version
            or job.normalization_version != CURRENT_NORMALIZATION_VERSION):
        raise ImportReceptionError(
            'NORMALIZATION_VERSION_UNAVAILABLE', status_code=409,
            detail='담보 기준을 새로 맞춘 뒤 다시 확인해 주세요.',
            extra={
                'draft_normalization_version': job.normalization_version,
            })


def _safe_evidence(value):
    if not isinstance(value, dict):
        return {
            'value': None,
            'state': 'invalid',
            'evidence_line_ids': [],
            'review_reason_codes': ['INVALID_DRAFT_FIELD'],
        }
    return {
        'value': copy.deepcopy(value.get('value')),
        'state': str(value.get('state') or 'needs_review'),
        'evidence_line_ids': [
            line_id for line_id in value.get('evidence_line_ids', [])
            if isinstance(line_id, str)
        ],
        'review_reason_codes': [
            code for code in value.get('review_reason_codes', [])
            if isinstance(code, str)
        ],
    }


def _safe_review_response(job):
    _assert_normalization_version(job)
    draft = job.draft_payload if isinstance(job.draft_payload, dict) else {}
    raw_policy = draft.get('policy')
    policy = raw_policy if isinstance(raw_policy, dict) else {}
    safe_policy = {
        field: _safe_evidence(policy.get(field))
        for field in _POLICY_FIELDS
        if field != 'company_code'
    }
    company_code = policy.get('company_code')
    safe_policy['company_code'] = (
        company_code.get('value')
        if isinstance(company_code, dict) else None
    )

    raw_rows = draft.get('coverage_rows')
    rows = raw_rows if isinstance(raw_rows, list) else []
    safe_rows = []
    for raw_row in rows:
        if not isinstance(raw_row, dict):
            continue
        safe_rows.append({
            field: copy.deepcopy(raw_row.get(field))
            for field in _COVERAGE_FIELDS
        })
    validation = draft.get('validation')
    validation = validation if isinstance(validation, dict) else {}
    raw_issues = validation.get('issues')
    raw_issues = raw_issues if isinstance(raw_issues, list) else []
    safe_issues = []
    for raw_issue in raw_issues:
        if not isinstance(raw_issue, dict):
            continue
        safe_issues.append({
            field: copy.deepcopy(raw_issue.get(field))
            for field in ('code', 'state', 'scope', 'row_id', 'field')
        })
    unresolved = validation.get('unresolved_count')
    if type(unresolved) is not int or unresolved < 0:
        unresolved = len(safe_rows) + len(safe_policy)
    source_review = safe_source_review(
        job.validation_summary,
        expected_page_count=job.page_count,
    )
    return {
        'job_id': str(job.id),
        'customer_id': job.customer_id,
        'status': job.status,
        'draft_version': job.draft_version,
        **safe_import_target(job),
        'policy': safe_policy,
        'coverages': safe_rows,
        'validation': {
            'unresolved_count': unresolved,
            'issues': safe_issues,
        },
        'source_review': source_review,
        'confirmation_requirements': safe_confirmation_requirements(
            source_review),
        'standard_coverages': standard_coverage_catalog(),
    }


def get_import_draft(*, owner, job_id):
    job = _owned_import_job(owner, job_id)
    _assert_review_ready(job)
    return _safe_review_response(job)


def _command_request_sha256(payload):
    encoded = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(',', ':'),
    ).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _replay_command(command, request_sha256):
    if not secrets.compare_digest(command.request_sha256, request_sha256):
        raise ImportReceptionError(
            'IDEMPOTENCY_KEY_REUSED', status_code=409,
            detail='같은 요청 키에는 같은 수정 내용만 사용할 수 있어요.')
    if command.completed_at is None or command.response_status is None:
        raise ImportReceptionError(
            'COMMAND_IN_PROGRESS', status_code=409,
            detail='먼저 시작한 저장이 끝나면 결과를 바로 확인할 수 있어요.')
    return command.response_status, copy.deepcopy(command.response_body)


def _draft_candidates(job):
    summary = job.validation_summary
    if not isinstance(summary, dict):
        return []
    candidates = summary.get('intake_candidates')
    if not isinstance(candidates, list):
        return []
    return copy.deepcopy(candidates)


def _draft_rows(draft):
    rows = draft.get('coverage_rows')
    if not isinstance(rows, list) or any(
            not isinstance(row, dict) for row in rows):
        raise ImportReceptionError(
            'DRAFT_INVALID', status_code=409,
            detail='증권을 다시 자동 정리한 뒤 확인해 주세요.')
    return rows


def _row_by_id(rows):
    rows_by_id = {}
    for row in rows:
        row_id = row.get('row_id')
        if (not isinstance(row_id, str)
                or not row_id
                or row_id in rows_by_id):
            raise ImportReceptionError(
                'DRAFT_INVALID', status_code=409,
                detail='증권을 다시 자동 정리한 뒤 확인해 주세요.')
        rows_by_id[row_id] = row
    return rows_by_id


def _previous_disposition(row):
    previous = {
        'disposition': row.get('disposition'),
        'standard_category': row.get('standard_category'),
        'standard_subcategory': row.get('standard_subcategory'),
        'standard_detail_name': row.get('standard_detail_name'),
    }
    manual_fields = row.get('manual_fields')
    if isinstance(manual_fields, list):
        previous['manual_fields'] = copy.deepcopy(manual_fields)
    return previous


def _set_manual_fields(row, fields):
    current = row.get('manual_fields')
    if not isinstance(current, list):
        current = []
    trusted = set(current)
    trusted.update(fields)
    ordered = [
        field for field in MANUAL_COVERAGE_FIELDS
        if field in trusted
    ]
    if ordered:
        row['manual_fields'] = ordered
    else:
        row.pop('manual_fields', None)


def _remove_manual_fields(row, fields):
    current = row.get('manual_fields')
    if not isinstance(current, list):
        return
    blocked = set(fields)
    remaining = [field for field in current if field not in blocked]
    if remaining:
        row['manual_fields'] = remaining
    else:
        row.pop('manual_fields', None)


def _apply_policy_changes(draft, changes):
    policy = draft.get('policy')
    if not isinstance(policy, dict):
        raise ImportReceptionError(
            'DRAFT_INVALID', status_code=409,
            detail='증권을 다시 자동 정리한 뒤 확인해 주세요.')
    for change in changes:
        field = change['field']
        existing = policy.get(field)
        if not isinstance(existing, dict):
            existing = {'evidence_line_ids': []}
            policy[field] = existing
        evidence_ids = existing.get('evidence_line_ids')
        existing['evidence_line_ids'] = (
            copy.deepcopy(evidence_ids)
            if isinstance(evidence_ids, list) else []
        )
        existing['value'] = copy.deepcopy(change['value'])
        existing['state'] = 'manual'
        existing['review_reason_codes'] = []


def _apply_coverage_actions(draft, actions, *, force_manual_review):
    rows = _draft_rows(draft)
    add_count = sum(action['action'] == 'add' for action in actions)
    if (add_count
            and len(rows) + add_count > settings.INSURANCE_MAX_CANDIDATES):
        raise ImportReceptionError(
            'COVERAGE_ROW_LIMIT_EXCEEDED', status_code=400,
            detail='담보 수가 많아요. 현재 담보를 먼저 확인해 주세요.')
    rows_by_id = _row_by_id(rows)
    for action in actions:
        operation = action['action']
        if operation == 'add':
            while True:
                row_id = f'manual-{uuid.uuid4()}'
                if row_id not in rows_by_id:
                    break
            row = {
                'row_id': row_id,
                **{
                    field: copy.deepcopy(action.get(field))
                    for field in (
                        'raw_name', 'assurance_amount', 'premium',
                        'is_renewal', 'renewal_period', 'payment_period',
                        'payment_period_unit', 'warranty_period',
                        'warranty_period_unit', 'standard_category',
                        'standard_subcategory', 'standard_detail_name',
                    )
                },
                'disposition': 'assigned',
                'exclusion_reason': None,
                'duplicate_of_row_id': None,
                'source_candidate_ids': [],
                'evidence_line_ids': [],
                'manual_fields': list(MANUAL_COVERAGE_FIELDS),
            }
            rows.append(row)
            rows_by_id[row_id] = row
            continue
        row = rows_by_id.get(action['row_id'])
        if row is None:
            raise ImportReceptionError(
                'COVERAGE_ROW_NOT_FOUND', status_code=400,
                detail='담보 목록을 새로 읽은 뒤 다시 수정해 주세요.')
        if operation == 'edit':
            field = action['field']
            value = copy.deepcopy(action['value'])
            row[field] = value
            _set_manual_fields(row, (field,))
        elif operation == 'assign':
            path = (
                action['standard_category'],
                action['standard_subcategory'],
                action['standard_detail_name'],
            )
            if path not in STANDARD_COVERAGE_PATHS:
                raise ImportReceptionError(
                    'STANDARD_COVERAGE_NOT_FOUND', status_code=400,
                    detail='표준 담보 위치를 다시 선택해 주세요.')
            mapping = {
                'disposition': 'assigned',
                'standard_category': path[0],
                'standard_subcategory': path[1],
                'standard_detail_name': path[2],
                'exclusion_reason': None,
                'duplicate_of_row_id': None,
            }
            row.update(mapping)
            _remove_manual_fields(row, (
                'disposition', 'exclusion_reason', 'duplicate_of_row_id'))
            # 같은 위치를 다시 선택한 경우도 설계사가 원문과 위치를 직접 확인한 것이다.
            _set_manual_fields(row, (
                'standard_category', 'standard_subcategory',
                'standard_detail_name'))
            row.pop('_review_previous', None)
        elif operation in {'exclude', 'duplicate'}:
            if (row.get('disposition') != 'intentionally_excluded'
                    or not isinstance(row.get('_review_previous'), dict)):
                row['_review_previous'] = _previous_disposition(row)
            exclusion = {
                'disposition': 'intentionally_excluded',
                'standard_category': None,
                'standard_subcategory': None,
                'standard_detail_name': None,
                'exclusion_reason': action['reason'],
                'duplicate_of_row_id': (
                    action.get('target_row_id')
                    if operation == 'duplicate' else None),
            }
            row.update(exclusion)
            approved_fields = ['disposition', 'exclusion_reason']
            if operation == 'duplicate':
                approved_fields.append('duplicate_of_row_id')
            _set_manual_fields(row, approved_fields)
        elif operation == 'confirm':
            if not force_manual_review:
                raise ImportReceptionError(
                    'COVERAGE_CONFIRM_NOT_REQUIRED', status_code=400,
                    detail='직접 확인이 필요한 담보만 확인해 주세요.')
            confirmed_codes = row.get('confirmed_review_codes')
            if not isinstance(confirmed_codes, list):
                confirmed_codes = []
            if 'CARRIER_MANUAL_REVIEW' not in confirmed_codes:
                confirmed_codes.append('CARRIER_MANUAL_REVIEW')
            row['confirmed_review_codes'] = confirmed_codes
        else:
            if row.get('disposition') != 'intentionally_excluded':
                raise ImportReceptionError(
                    'COVERAGE_NOT_EXCLUDED', status_code=400,
                    detail='현재 제외된 담보만 되돌릴 수 있어요.')
            previous = row.get('_review_previous')
            if not isinstance(previous, dict):
                previous = {
                    'disposition': 'unmatched',
                    'standard_category': None,
                    'standard_subcategory': None,
                    'standard_detail_name': None,
                }
            row.update({
                'disposition': previous.get('disposition') or 'unmatched',
                'standard_category': previous.get('standard_category'),
                'standard_subcategory': previous.get('standard_subcategory'),
                'standard_detail_name': previous.get('standard_detail_name'),
                'exclusion_reason': None,
                'duplicate_of_row_id': None,
            })
            previous_manual_fields = previous.get('manual_fields')
            if isinstance(previous_manual_fields, list):
                row['manual_fields'] = copy.deepcopy(previous_manual_fields)
            else:
                row.pop('manual_fields', None)
            row.pop('_review_previous', None)

    rows_by_id = _row_by_id(rows)
    for row in rows:
        target_id = row.get('duplicate_of_row_id')
        if target_id is None:
            continue
        target = rows_by_id.get(target_id)
        source_ids = set(row.get('source_candidate_ids') or [])
        target_source_ids = set(
            target.get('source_candidate_ids') or []) if target else set()
        if (target is None
                or target is row
                or target.get('disposition') == 'intentionally_excluded'
                or target.get('duplicate_of_row_id') is not None
                or not source_ids
                or source_ids != target_source_ids):
            raise ImportReceptionError(
                'INVALID_DUPLICATE_TARGET', status_code=400,
                detail='중복이 아닌 기준 담보를 다시 선택해 주세요.')


def _validation_summary(job, new_summary):
    old_summary = (
        copy.deepcopy(job.validation_summary)
        if isinstance(job.validation_summary, dict) else {}
    )
    old_summary.update(new_summary)
    return old_summary


def _force_manual_review_required(job):
    summary = job.validation_summary
    if not isinstance(summary, dict):
        return False
    system = summary.get('_system')
    return bool(
        isinstance(system, dict)
        and system.get('force_manual_review') is True
    )


def patch_import_draft(*, owner, job_id, payload, idempotency_key):
    request_sha256 = _command_request_sha256(payload)
    requested_version = payload['draft_version']
    with transaction.atomic():
        type(owner).objects.select_for_update().get(pk=owner.pk)
        job = _owned_import_job(owner, job_id, for_update=True)
        command = (
            InsuranceImportCommand.objects
            .select_for_update()
            .filter(
                job=job,
                operation='patch',
                idempotency_key=idempotency_key,
            )
            .first()
        )
        if command is not None:
            return _replay_command(command, request_sha256)
        _assert_review_ready(job)
        _assert_normalization_version(job)
        if requested_version != job.draft_version:
            raise ImportReceptionError(
                'DRAFT_VERSION_CHANGED', status_code=409,
                detail='다른 화면에서 내용이 바뀌었어요. 최신 내용을 확인해 주세요.',
                extra={'current_version': job.draft_version})

        command = InsuranceImportCommand.objects.create(
            job=job,
            operation='patch',
            idempotency_key=idempotency_key,
            request_sha256=request_sha256,
        )
        draft = copy.deepcopy(job.draft_payload)
        force_manual_review = _force_manual_review_required(job)
        _apply_policy_changes(draft, payload.get('policy_changes') or [])
        _apply_coverage_actions(
            draft,
            payload.get('coverage_actions') or [],
            force_manual_review=force_manual_review,
        )
        validation = validate_draft(
            job.masked_lines,
            _draft_candidates(job),
            draft,
            allow_manual=True,
            allow_manual_without_evidence=True,
        )
        validated_draft, validation_summary = apply_force_manual_review(
            validation,
            required=force_manual_review,
        )
        validated_draft, validation_summary = apply_source_review_issue(
            validated_draft,
            validation_summary,
            safe_source_review(
                job.validation_summary,
                expected_page_count=job.page_count,
            ),
        )
        edit_count = (
            len(payload.get('policy_changes') or [])
            + len(payload.get('coverage_actions') or [])
        )
        updated = InsuranceExtractionJob.objects.filter(
            pk=job.pk,
            owner=owner,
            customer__owner=owner,
            status='review_required',
            draft_version=requested_version,
        ).update(
            draft_payload=validated_draft,
            validation_summary=_validation_summary(job, validation_summary),
            draft_version=F('draft_version') + 1,
            planner_edit_count=F('planner_edit_count') + edit_count,
        )
        if updated != 1:
            current_version = (
                InsuranceExtractionJob.objects
                .filter(pk=job.pk, owner=owner, customer__owner=owner)
                .values_list('draft_version', flat=True)
                .first()
            )
            raise ImportReceptionError(
                'DRAFT_VERSION_CHANGED', status_code=409,
                detail='다른 화면에서 내용이 바뀌었어요. 최신 내용을 확인해 주세요.',
                extra={'current_version': current_version})
        job.refresh_from_db()
        response_body = _safe_review_response(job)
        command.response_status = 200
        command.response_body = response_body
        command.completed_at = timezone.now()
        command.save(update_fields=(
            'response_status', 'response_body', 'completed_at'))
    return 200, response_body


def _delete_canceled_source(job_id, source_key):
    if not source_key:
        return
    job = InsuranceExtractionJob.objects.filter(
        pk=job_id,
        status='canceled',
        source_storage_key=source_key,
        source_deleted_at__isnull=True,
    ).first()
    if job is None:
        return
    try:
        delete_source(job, key=source_key)
    except Exception as exc:
        logger.warning(
            '[insurance-import] canceled source cleanup failed '
            'job=%s type=%s', job_id, type(exc).__name__)
        return
    InsuranceExtractionJob.objects.filter(
        pk=job_id,
        status='canceled',
        source_storage_key=source_key,
        source_deleted_at__isnull=True,
    ).update(source_deleted_at=timezone.now())


def _refund_canceled_credit(job):
    summary = (
        copy.deepcopy(job.validation_summary)
        if isinstance(job.validation_summary, dict) else {}
    )
    system = summary.get('_system')
    if not isinstance(system, dict):
        return summary
    if (job.status not in {'queued', 'extracting'}
            or system.get('provider_started') is True):
        return summary
    year_month = system.get('credit_year_month')
    if (not system.get('credit_consumed')
            or system.get('credit_refunded')
            or not isinstance(year_month, str)
            or len(year_month) != 7
            or year_month[4] != '-'):
        return summary
    meter = (
        UsageMeter.objects
        .select_for_update()
        .filter(
            user=job.owner,
            action='ocr',
            year_month=year_month,
        )
        .first()
    )
    if meter is None or meter.count <= 0:
        return summary
    updated = UsageMeter.objects.filter(
        pk=meter.pk, count__gt=0).update(count=F('count') - 1)
    if updated == 1:
        system['credit_refunded'] = True
    return summary


def cancel_import(*, owner, job_id, idempotency_key):
    request_sha256 = _command_request_sha256({})
    cleanup = None
    with transaction.atomic():
        type(owner).objects.select_for_update().get(pk=owner.pk)
        job = _owned_import_job(owner, job_id, for_update=True)
        command = (
            InsuranceImportCommand.objects
            .select_for_update()
            .filter(
                job=job,
                operation='cancel',
                idempotency_key=idempotency_key,
            )
            .first()
        )
        if command is not None:
            return _replay_command(command, request_sha256)
        if job.status in {'confirmed', 'failed', 'superseded'}:
            raise ImportReceptionError(
                'IMPORT_NOT_CANCELABLE', status_code=409,
                detail='현재 증권 상태를 새로 확인해 주세요.')
        if job.status == 'validating':
            raise ImportReceptionError(
                'CANCEL_IN_PROGRESS', status_code=409,
                detail='자동 정리가 끝난 뒤 취소할 수 있어요.')

        command = InsuranceImportCommand.objects.create(
            job=job,
            operation='cancel',
            idempotency_key=idempotency_key,
            request_sha256=request_sha256,
        )
        now = timezone.now()
        validation_summary = _refund_canceled_credit(job)
        if job.status != 'canceled':
            updated = InsuranceExtractionJob.objects.filter(
                pk=job.pk,
                owner=owner,
                customer__owner=owner,
                status=job.status,
                attempt_uuid=job.attempt_uuid,
            ).update(
                status='canceled',
                canceled_at=now,
                source_expires_at=now,
                attempt_uuid=None,
                lease_expires_at=None,
                validation_summary=validation_summary,
            )
            if updated != 1:
                raise ImportReceptionError(
                    'IMPORT_STATE_CHANGED', status_code=409,
                    detail='현재 증권 상태를 새로 확인해 주세요.')
            job.refresh_from_db()
        elif validation_summary != job.validation_summary:
            InsuranceExtractionJob.objects.filter(
                pk=job.pk,
                owner=owner,
                customer__owner=owner,
                status='canceled',
            ).update(validation_summary=validation_summary)
            job.validation_summary = validation_summary
        if job.source_storage_key and job.source_deleted_at is None:
            cleanup = (job.pk, job.source_storage_key)
        elif job.source_deleted_at is None:
            InsuranceExtractionJob.objects.filter(
                pk=job.pk,
                status='canceled',
                source_deleted_at__isnull=True,
            ).update(source_deleted_at=now)
        response_body = {'job_id': str(job.pk), 'status': 'canceled'}
        command.response_status = 200
        command.response_body = response_body
        command.completed_at = now
        command.save(update_fields=(
            'response_status', 'response_body', 'completed_at'))
        if cleanup is not None:
            transaction.on_commit(
                lambda args=cleanup: _delete_canceled_source(*args))
    return 200, response_body


def _policy_value(draft, field):
    policy = draft.get('policy') if isinstance(draft, dict) else None
    evidence = policy.get(field) if isinstance(policy, dict) else None
    return evidence.get('value') if isinstance(evidence, dict) else None


def _model_date(value):
    return normalize_insurance_date(value)


def _standard_analysis_detail(row):
    category = row.get('standard_category')
    subcategory = row.get('standard_subcategory')
    detail_name = row.get('standard_detail_name')
    details = list(
        AnalysisDetail.objects
        .select_related('sub_category__category')
        .filter(
            name=detail_name,
            sub_category__name=subcategory,
            sub_category__category__name__in=(
                category, f'[표준]{category}'),
        )
        .order_by('pk')
        [:2]
    )
    if len(details) != 1:
        raise ImportReceptionError(
            'STANDARD_COVERAGE_NOT_READY', status_code=409,
            detail='담보 기준을 새로 맞춘 뒤 다시 확인해 주세요.')
    return details[0]


def _catalog_detail_for_override(row, insurance_type):
    """Resolve one seeded compatibility FK without changing global rows."""
    category_names = (
        f'[표준]{row["standard_category"]}',
        row['standard_category'],
    )
    for category_name in category_names:
        details = list(
            InsuranceDetail.objects
            .select_related('sub_category__category')
            .filter(
                sub_category__category__name=category_name,
                sub_category__name=row['standard_subcategory'],
                name=row['standard_detail_name'],
            )
            .order_by('pk')
            [:2]
        )
        if len(details) == 1:
            # The selected AnalysisDetail is stored only on the customer case.
            # Never add/set/remove InsuranceDetail.analysis_detail here.
            return details[0]
        if len(details) > 1:
            break
    raise ImportReceptionError(
        'STANDARD_COVERAGE_NOT_READY', status_code=409,
        detail='담보 기준을 새로 맞춘 뒤 다시 확인해 주세요.')


def _period_types(row):
    payment_unit = row.get('payment_period_unit')
    payment_period = row.get('payment_period')
    if payment_unit not in {'years', 'age', 'lifetime'}:
        raise ImportReceptionError(
            'DRAFT_UNRESOLVED', status_code=409,
            detail='납입 기간을 확인하면 바로 반영할 수 있어요.')
    if payment_unit == 'lifetime':
        payment_type = 4
        payment_period = None
    elif row.get('is_renewal') is True:
        payment_type = 3
    elif row.get('is_renewal') is False and payment_unit in {'years', 'age'}:
        payment_type = {'years': 1, 'age': 2}[payment_unit]
    else:
        raise ImportReceptionError(
            'DRAFT_UNRESOLVED', status_code=409,
            detail='갱신 여부와 납입 기간을 확인하면 바로 반영할 수 있어요.')
    warranty_types = {
        'age': 1,
        'years': 2,
        'lifetime': 4,
    }
    warranty_unit = row.get('warranty_period_unit')
    if warranty_unit not in warranty_types:
        raise ImportReceptionError(
            'DRAFT_UNRESOLVED', status_code=409,
            detail='보장 기간을 확인하면 바로 반영할 수 있어요.')
    warranty_type = warranty_types[warranty_unit]
    warranty_period = (
        None if warranty_type == 4 else row.get('warranty_period'))
    return payment_type, payment_period, warranty_type, warranty_period


_LINE_ID_RE = re.compile(r'^p(?P<page>\d+)-l(?P<line>\d+)$')


def _evidence_projection(job, row):
    line_map = {
        line.get('line_id'): line
        for line in job.masked_lines
        if isinstance(line, dict) and isinstance(line.get('line_id'), str)
    }
    ids = [
        line_id for line_id in row.get('evidence_line_ids') or []
        if isinstance(line_id, str) and line_id in line_map
    ]
    positions = []
    texts = []
    for line_id in ids:
        match = _LINE_ID_RE.fullmatch(line_id)
        if match:
            positions.append((
                int(match.group('page')), int(match.group('line'))))
        text = line_map[line_id].get('text_masked')
        if isinstance(text, str) and text:
            texts.append(text)
    pages = {page for page, _line in positions}
    source_page = next(iter(pages)) if len(pages) == 1 else None
    line_numbers = [line for page, line in positions if page == source_page]
    return {
        'source_page': source_page,
        'source_line_start': min(line_numbers) if line_numbers else None,
        'source_line_end': max(line_numbers) if line_numbers else None,
        'source_text_masked': '\n'.join(texts),
        'source_candidate_ids': copy.deepcopy(
            row.get('source_candidate_ids') or []),
        'evidence_line_ids': ids,
    }


def _calculate_materialized_insurance(insurance):
    cases = list(insurance.case_list.all())
    if not any(type(case.premium) is int and case.premium > 0
               for case in cases):
        # Coverage amounts can still be analyzed when a document has no
        # per-coverage premium. Do not invent a payment term just to run the
        # legacy cost engine; leave cost totals unknown.
        return
    insurance.set_renewal_month()
    for case in cases:
        case.calculate(insurance)
        case.save(update_fields=(
            'total_renewal_premium', 'total_non_renewal_premium',
            'updated_at'))
    insurance.calculate()
    insurance.save(update_fields=(
        'total_premiums', 'monthly_non_renewal_premium',
        'monthly_renewal_premium', 'total_renewal_premium',
        'total_non_renewal_premium', 'total_earned_premium',
        'monthly_earned_premium', 'updated_at'))


def _assert_calculation_prerequisites(customer, draft):
    rows = draft.get('coverage_rows') or []
    positive_rows = [
        row for row in rows
        if row.get('disposition') == 'assigned'
        and type(row.get('premium')) is int
        and row.get('premium') > 0
    ]
    renewal_rows = [
        row for row in positive_rows if row.get('is_renewal') is True
    ]
    contract_date = parse_insurance_date(
        _policy_value(draft, 'contract_date'))
    expiry_date = parse_insurance_date(
        _policy_value(draft, 'expiry_date'))
    if renewal_rows and (
            contract_date is None
            or expiry_date is None
            or contract_date > expiry_date):
        raise ImportReceptionError(
            'DRAFT_UNRESOLVED', status_code=409,
            detail='계약일과 만기일을 확인하면 바로 반영할 수 있어요.')

    needs_birth_date = any(
        row.get('is_renewal') is False
        and row.get('payment_period_unit') == 'age'
        for row in positive_rows
    )
    if (renewal_rows and _policy_value(draft, 'insurance_type') == 'life'):
        needs_birth_date = True
    if needs_birth_date and parse_insurance_date(customer.birth_day) is None:
        raise ImportReceptionError(
            'DRAFT_UNRESOLVED', status_code=409,
            detail='고객 생년월일을 확인하면 바로 반영할 수 있어요.')
    if any(row.get('payment_period_unit') == 'age'
           for row in positive_rows) and contract_date is None:
        raise ImportReceptionError(
            'DRAFT_UNRESOLVED', status_code=409,
            detail='계약일을 확인하면 바로 반영할 수 있어요.')


def _materialize_confirmed_insurance(job, owner, draft, now):
    insurance_type_value = _policy_value(draft, 'insurance_type')
    try:
        insurance_type = {'life': 1, 'loss': 2}[insurance_type_value]
    except (KeyError, TypeError) as exc:
        raise ImportReceptionError(
            'DRAFT_UNRESOLVED', status_code=409,
            detail='보험 종류를 확인하면 바로 반영할 수 있어요.') from exc
    insurance = CustomerInsurance.objects.create(
        customer=job.customer,
        company=_policy_value(draft, 'company_code'),
        insurance_type=insurance_type,
        name=_policy_value(draft, 'product_name'),
        portfolio_type=job.portfolio_type,
        contract_date=_model_date(_policy_value(draft, 'contract_date')),
        expiry_date=_model_date(_policy_value(draft, 'expiry_date')),
        monthly_premiums=_policy_value(draft, 'monthly_premium'),
        review_status='confirmed',
        source_job=job,
        confirmed_at=now,
        confirmed_by=owner,
        analysis_included=True,
        confirmation_source='planner_review',
    )
    for row in draft.get('coverage_rows') or []:
        if row.get('disposition') == 'intentionally_excluded':
            continue
        analysis_detail = _standard_analysis_detail(row)
        catalog_detail = _catalog_detail_for_override(row, insurance_type)
        (payment_type, payment_period, warranty_type,
         warranty_period) = _period_types(row)
        case = CustomerInsuranceDetail.objects.create(
            insurance=insurance,
            detail=catalog_detail,
            raw_name=str(row.get('raw_name') or '')[:200],
            assurance_amount=row.get('assurance_amount'),
            premium=row.get('premium'),
            renewal_period=row.get('renewal_period'),
            payment_period=payment_period,
            payment_period_type=payment_type,
            warranty_period=(
                str(warranty_period) if warranty_period is not None else None),
            warranty_period_type=warranty_type,
            mapping_source='planner_override',
            confirmed_at=now,
            review_reason=copy.deepcopy(
                row.get('review_reason_codes') or []),
            **_evidence_projection(job, row),
        )
        case.analysis_detail_override.add(analysis_detail)
    _calculate_materialized_insurance(insurance)
    return insurance


def _delete_confirmed_source(job_id, source_key):
    if not source_key:
        return
    job = InsuranceExtractionJob.objects.filter(
        pk=job_id,
        status='confirmed',
        source_storage_key=source_key,
        source_deleted_at__isnull=True,
    ).first()
    if job is None:
        return
    try:
        delete_source(job, key=source_key)
    except Exception as exc:
        # source_expires_at is stamped at confirmation, so the retention job
        # retries the same exact key without reopening the confirmed data.
        logger.warning(
            '[insurance-import] confirmed source cleanup failed '
            'job=%s type=%s', job_id, type(exc).__name__)
        return
    InsuranceExtractionJob.objects.filter(
        pk=job_id,
        status='confirmed',
        source_storage_key=source_key,
        source_deleted_at__isnull=True,
    ).update(source_deleted_at=timezone.now())


def confirm_import(*, owner, job_id, payload, idempotency_key):
    request_sha256 = _command_request_sha256(payload)
    requested_version = payload['draft_version']
    cleanup = None
    with transaction.atomic():
        type(owner).objects.select_for_update().get(pk=owner.pk)
        job = _owned_import_job(owner, job_id, for_update=True)
        command = (
            InsuranceImportCommand.objects
            .select_for_update()
            .filter(
                job=job, operation='confirm',
                idempotency_key=idempotency_key)
            .first()
        )
        if command is not None:
            return _replay_command(command, request_sha256)
        _assert_review_ready(job)
        _assert_normalization_version(job)
        if payload['planner_confirmed_source_match'] is not True:
            raise ImportReceptionError(
                'SOURCE_CONFIRMATION_REQUIRED', status_code=409,
                detail='증권 원문과 같은지 확인하면 바로 반영할 수 있어요.')
        if requested_version != job.draft_version:
            raise ImportReceptionError(
                'DRAFT_VERSION_CHANGED', status_code=409,
                detail='다른 화면에서 내용이 바뀌었어요. 최신 내용을 확인해 주세요.',
                extra={'current_version': job.draft_version})
        if (safe_source_review(
                job.validation_summary,
                expected_page_count=job.page_count)['required']
                and payload.get('planner_confirmed_unread_pages') is not True):
            raise ImportReceptionError(
                'UNREAD_SOURCE_PAGES_CONFIRMATION_REQUIRED',
                status_code=409,
                detail=(
                    '텍스트 확인이 필요한 원본 페이지를 확인하면 '
                    '바로 반영할 수 있어요.'))

        requested_target_version = payload.get('target_insurance_version')
        target = None
        # Keep the shared lock order owner -> job -> customer -> target. Intake
        # and confirmation can otherwise deadlock when a replacement upload
        # races a final confirmation for the same customer.
        job.customer = Customer.objects.select_for_update().get(
            pk=job.customer_id, owner=owner)
        if job.intent == 'replace':
            if job.target_insurance_id is None:
                raise ImportReceptionError(
                    'IMPORT_TARGET_CHANGED', status_code=409,
                    detail='교체할 보험을 새로 선택해 주세요.')
            target = (
                CustomerInsurance.objects.select_for_update()
                .filter(
                    pk=job.target_insurance_id,
                    customer=job.customer,
                    customer__owner=owner)
                .first()
            )
            if (target is None
                    or requested_target_version != job.target_insurance_version
                    or target.data_version != job.target_insurance_version):
                raise ImportReceptionError(
                    'IMPORT_TARGET_CHANGED', status_code=409,
                    detail='교체할 보험 내용이 바뀌었어요. 최신 내용을 확인해 주세요.')
        elif requested_target_version is not None:
            raise ImportReceptionError(
                'IMPORT_TARGET_CHANGED', status_code=409,
                detail='추가할 증권 정보를 새로 확인해 주세요.')

        lineage_job = (
            InsuranceExtractionJob.objects.select_for_update()
            .filter(
                owner=owner,
                customer=job.customer,
                file_sha256=job.file_sha256,
                portfolio_type=job.portfolio_type,
                status='confirmed',
            )
            .exclude(pk=job.pk)
            .order_by('-confirmed_at', '-created_at')
            .first()
        )
        lineage_insurance = None
        if lineage_job is not None:
            lineage_insurance = (
                CustomerInsurance.objects.select_for_update()
                .filter(
                    source_job=lineage_job,
                    customer=job.customer,
                    customer__owner=owner,
                )
                .first()
            )
            replaces_lineage = bool(
                job.intent == 'replace'
                and target is not None
                and lineage_insurance is not None
                and target.pk == lineage_insurance.pk
            )
            if not replaces_lineage:
                extra = {}
                if lineage_insurance is not None:
                    extra = {
                        'insurance_id': lineage_insurance.pk,
                        'insurance_version': lineage_insurance.data_version,
                    }
                raise ImportReceptionError(
                    'DUPLICATE_CONFIRMED', status_code=409,
                    detail='이미 확인을 마친 같은 증권이 있어요.',
                    extra=extra,
                )

        validation = validate_draft(
            job.masked_lines,
            _draft_candidates(job),
            copy.deepcopy(job.draft_payload),
            allow_manual=True,
            allow_manual_without_evidence=True,
        )
        final_draft, validation_summary = apply_force_manual_review(
            validation, required=_force_manual_review_required(job))
        final_rows = final_draft.get('coverage_rows') or []
        invalid_disposition = any(
            not isinstance(row, dict)
            or row.get('disposition') not in {
                'assigned', 'intentionally_excluded'}
            for row in final_rows
        )
        detected = validation_summary.get('detected_candidates')
        conserved = sum(
            validation_summary.get(key, 0)
            for key in ('assigned', 'unmatched', 'intentionally_excluded'))
        if (validation_summary.get('unresolved_count') != 0
                or invalid_disposition
                or type(detected) is not int
                or detected != conserved):
            raise ImportReceptionError(
                'DRAFT_UNRESOLVED', status_code=409,
                detail='확인이 필요한 항목을 모두 정리하면 바로 반영할 수 있어요.',
                extra={
                    'unresolved_count': validation_summary.get(
                        'unresolved_count', 1),
                })
        _assert_calculation_prerequisites(job.customer, final_draft)

        command = InsuranceImportCommand.objects.create(
            job=job, operation='confirm', idempotency_key=idempotency_key,
            request_sha256=request_sha256)
        now = timezone.now()
        insurance = _materialize_confirmed_insurance(
            job, owner, final_draft, now)
        if target is not None:
            if target.source_job_id is not None:
                InsuranceExtractionJob.objects.filter(
                    pk=target.source_job_id,
                    owner=owner,
                    customer=job.customer,
                    status='confirmed',
                ).update(
                    status='superseded',
                    completed_at=now,
                )
            target.review_status = 'superseded'
            target.analysis_included = False
            target.data_version = F('data_version') + 1
            target.save(update_fields=(
                'review_status', 'analysis_included', 'data_version',
                'updated_at'))

        confirmed_count = insurance.case_list.count()
        source_key = job.source_storage_key
        updated = InsuranceExtractionJob.objects.filter(
            pk=job.pk, owner=owner, customer__owner=owner,
            status='review_required', draft_version=requested_version,
        ).update(
            status='confirmed', confirmed_at=now, completed_at=now,
            confirmed_coverage_count=confirmed_count,
            source_expires_at=now,
            draft_payload=final_draft,
            validation_summary=_validation_summary(job, validation_summary),
        )
        if updated != 1:
            raise ImportReceptionError(
                'IMPORT_STATE_CHANGED', status_code=409,
                detail='현재 증권 상태를 새로 확인해 주세요.')
        response_body = {
            'job_id': str(job.pk),
            'status': 'confirmed',
            'insurance_id': insurance.pk,
            'insurance_version': insurance.data_version,
            'confirmed_coverage_count': confirmed_count,
        }
        command.response_status = 200
        command.response_body = response_body
        command.completed_at = now
        command.save(update_fields=(
            'response_status', 'response_body', 'completed_at'))
        if source_key:
            cleanup = (job.pk, source_key)
            transaction.on_commit(
                lambda args=cleanup: _delete_confirmed_source(*args))
    return 200, response_body
