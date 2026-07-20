import copy
import logging
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.storage import storages
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from sentry_sdk import capture_event

from inpa.analysis.management.commands.seed_normalization import SEED_VERSION
from inpa.billing.credit import log_claude_usage
from inpa.billing.models import ClaudeApiLog, UsageMeter
from inpa.billing.pricing import estimate_cost_krw
from inpa.customers.consent_texts import has_current_overseas_consent
from inpa.customers.models import Customer

from .import_claude import (
    ExtractionFailure,
    assert_provider_payload_pii_safe,
    extract as claude_extract,
    provider_grounding_texts,
)
from .import_contract import (
    PDFImportError,
    apply_source_review_issue,
    extracted_source_readability,
    normalize_source_readability,
    safe_source_review,
)
from .import_pdf import extract_pdf
from .import_storage import (
    SourceNamespaceMismatch,
    assert_source_namespace,
    delete_source,
)
from .import_validation import apply_force_manual_review, validate_draft
from .models import (
    InsuranceExtractionJob,
    InsuranceExtractionResult,
    InsuranceImportCreateRequest,
    InsuranceImportRuntimeConfig,
)


logger = logging.getLogger(__name__)

SCHEMA_VERSION = 'insurance-review-v1'
PROMPT_VERSION = 'claude-extraction-v1'
NORMALIZATION_VERSION = f'seed-normalization-{SEED_VERSION}'
LEASE_SECONDS = 600
CAPACITY_RETRY_SECONDS = 15
MAX_LEASE_ATTEMPTS = 3
INITIAL_METRICS_SCHEMA = 'insurance-extraction-initial-metrics-v1'
INITIAL_METRIC_STATES = (
    'review_ready', 'needs_review', 'no_evidence',
    'unmatched', 'invalid', 'manual',
)


class CapacityUnavailable(Exception):
    """A PII-free signal that Celery should retry after a short delay."""


class StaleAttempt(Exception):
    """The database has already assigned this job to a newer attempt."""


class WorkerFailure(Exception):
    def __init__(self, code, *, error_type='worker'):
        self.code = code
        self.error_type = error_type
        super().__init__(code)


@dataclass(frozen=True)
class ClaimedImport:
    job_id: uuid.UUID
    attempt_uuid: uuid.UUID
    force_manual_carrier_codes: tuple[int, ...]


def _lock_owner_row(owner_id):
    return get_user_model().objects.select_for_update().get(pk=owner_id)


def _read_job_owner_id(job_id):
    """Non-locking routing read; every caller must revalidate after locks."""
    return (
        InsuranceExtractionJob.objects
        .filter(pk=job_id)
        .values_list('owner_id', flat=True)
        .first()
    )


def _lock_job_row(job_id):
    return (
        InsuranceExtractionJob.objects
        .select_for_update()
        .filter(pk=job_id)
        .first()
    )


def _locked_runtime_config():
    defaults = {
        'per_owner_concurrency': getattr(
            settings, 'INSURANCE_IMPORT_PER_OWNER_LIMIT', 2),
        'global_concurrency': getattr(
            settings, 'INSURANCE_IMPORT_GLOBAL_LIMIT', 4),
    }
    config, _created = (
        InsuranceImportRuntimeConfig.objects
        .select_for_update()
        .get_or_create(pk=1, defaults=defaults)
    )
    return config


def claim_import(job_id, *, now=None):
    """Claim with the canonical owner -> config -> job lock order."""
    now = now or timezone.now()
    try:
        parsed_job_id = uuid.UUID(str(job_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise WorkerFailure('JOB_NOT_FOUND', error_type='invalid_job_id') from exc

    owner_id = _read_job_owner_id(parsed_job_id)
    if owner_id is None:
        raise WorkerFailure('JOB_NOT_FOUND', error_type='missing_job')

    with transaction.atomic():
        try:
            _lock_owner_row(owner_id)
        except get_user_model().DoesNotExist as exc:
            raise StaleAttempt from exc
        config = _locked_runtime_config()
        job = _lock_job_row(parsed_job_id)
        if job is None or job.owner_id != owner_id:
            raise StaleAttempt
        if job.status != 'queued':
            raise StaleAttempt
        if not Customer.objects.filter(
                pk=job.customer_id, owner_id=owner_id).exists():
            raise SourceNamespaceMismatch

        live = InsuranceExtractionJob.objects.filter(
            status__in=('extracting', 'validating'),
            lease_expires_at__gt=now,
        )
        if live.count() >= config.global_concurrency:
            raise CapacityUnavailable
        if live.filter(owner_id=job.owner_id).count() >= config.per_owner_concurrency:
            raise CapacityUnavailable

        attempt_id = uuid.uuid4()
        updated = InsuranceExtractionJob.objects.filter(
            pk=job.id,
            status='queued',
            attempt_uuid=job.attempt_uuid,
        ).update(
            status='extracting',
            attempt_uuid=attempt_id,
            lease_expires_at=now + timedelta(seconds=LEASE_SECONDS),
            attempt_count=F('attempt_count') + 1,
            started_at=job.started_at or now,
            error_code='',
            error_type='',
        )
        if updated != 1:
            raise StaleAttempt
        from .import_validation import sanitize_force_manual_carrier_codes

        force_manual_codes = tuple(sanitize_force_manual_carrier_codes(
            config.force_manual_carrier_codes))
        return ClaimedImport(
            job_id=job.id,
            attempt_uuid=attempt_id,
            force_manual_carrier_codes=force_manual_codes,
        )


def _cas_transition(job_id, attempt_id, *, expected_status, next_status,
                    **safe_fields):
    updated = InsuranceExtractionJob.objects.filter(
        id=job_id,
        attempt_uuid=attempt_id,
        status=expected_status,
    ).update(status=next_status, **safe_fields)
    if updated != 1:
        raise StaleAttempt


def _current_job(claim, *, expected_status):
    try:
        job = (
            InsuranceExtractionJob.objects
            .select_related('owner', 'customer')
            .get(
                pk=claim.job_id,
                attempt_uuid=claim.attempt_uuid,
                status=expected_status,
            )
        )
    except InsuranceExtractionJob.DoesNotExist as exc:
        raise StaleAttempt from exc
    if job.customer.owner_id != job.owner_id:
        raise SourceNamespaceMismatch
    return job


def _extract_job_pdf(job):
    if (not job.source_storage_key
            or job.source_deleted_at is not None
            or job.source_expires_at is None
            or job.source_expires_at <= timezone.now()):
        raise WorkerFailure('SOURCE_EXPIRED', error_type='source_unavailable')
    assert_source_namespace(job, job.source_storage_key)
    storage = storages['insurance_sources']
    if not storage.exists(job.source_storage_key):
        raise WorkerFailure('SOURCE_NOT_FOUND', error_type='source_unavailable')
    try:
        with storage.open(job.source_storage_key, 'rb') as source:
            extracted = extract_pdf(source)
    except PDFImportError:
        raise
    except Exception as exc:
        raise WorkerFailure(
            'SOURCE_READ_FAILED', error_type=type(exc).__name__) from None
    if (not secrets.compare_digest(extracted.file_sha256, job.file_sha256)
            or extracted.file_size != job.file_size):
        raise WorkerFailure(
            'SOURCE_INTEGRITY_MISMATCH', error_type='source_integrity')
    return extracted


def _system_summary(summary):
    safe_summary = copy.deepcopy(summary) if isinstance(summary, dict) else {}
    system = safe_summary.get('_system')
    if not isinstance(system, dict):
        system = {}
        safe_summary['_system'] = system
    return safe_summary, system


def _assert_source_readability_matches(job, extracted):
    summary = job.validation_summary
    system = summary.get('_system') if isinstance(summary, dict) else None
    expected = normalize_source_readability(
        system.get('source_readability') if isinstance(system, dict) else None,
        expected_page_count=job.page_count,
    )
    if (expected is None
            or extracted_source_readability(extracted) != expected):
        raise WorkerFailure(
            'SOURCE_READABILITY_MISMATCH',
            error_type='source_readability',
        )


def _reserve_provider_call(claim):
    """Atomically reserve the provider boundary under owner -> job locks."""
    owner_id = _read_job_owner_id(claim.job_id)
    if owner_id is None:
        raise StaleAttempt
    with transaction.atomic():
        try:
            _lock_owner_row(owner_id)
        except get_user_model().DoesNotExist as exc:
            raise StaleAttempt from exc
        job = _lock_job_row(claim.job_id)
        if (job is None
                or job.owner_id != owner_id
                or job.attempt_uuid != claim.attempt_uuid
                or job.status != 'extracting'):
            raise StaleAttempt
        summary, system = _system_summary(job.validation_summary)
        system['provider_started'] = True
        updated = InsuranceExtractionJob.objects.filter(
            pk=job.id,
            owner_id=owner_id,
            attempt_uuid=claim.attempt_uuid,
            status='extracting',
        ).update(
            status='validating',
            validation_summary=summary,
            lease_expires_at=timezone.now() + timedelta(seconds=LEASE_SECONDS),
        )
        if updated != 1:
            raise StaleAttempt


def _refund_metadata(job, *, refund_credit=True):
    summary, system = _system_summary(job.validation_summary)
    should_refund = bool(
        refund_credit
        and system.get('credit_consumed')
        and not system.get('credit_refunded')
    )
    credit_year_month = system.get('credit_year_month')
    if (not isinstance(credit_year_month, str)
            or len(credit_year_month) != 7
            or credit_year_month[4] != '-'):
        should_refund = False
    if should_refund:
        system['credit_refunded'] = True
    return summary, should_refund, credit_year_month


def _decrement_credit(job, credit_year_month):
    meter = UsageMeter.objects.select_for_update().filter(
        user_id=job.owner_id,
        action='ocr',
        year_month=credit_year_month,
        count__gt=0,
    ).first()
    if meter is not None:
        meter.count -= 1
        meter.save(update_fields=['count', 'updated_at'])


def _fail_queued_job(job_id, *, code, error_type, refund_credit=True):
    """Fail one queued job using owner -> job -> meter lock order."""
    owner_id = _read_job_owner_id(job_id)
    if owner_id is None:
        return False
    with transaction.atomic():
        try:
            _lock_owner_row(owner_id)
        except get_user_model().DoesNotExist:
            return False
        job = _lock_job_row(job_id)
        if (job is None
                or job.owner_id != owner_id
                or job.status != 'queued'):
            return False
        summary, should_refund, credit_year_month = _refund_metadata(
            job, refund_credit=refund_credit)
        source_key = job.source_storage_key or ''
        updated = InsuranceExtractionJob.objects.filter(
            pk=job.id,
            owner_id=owner_id,
            status='queued',
            attempt_uuid=job.attempt_uuid,
        ).update(
            status='failed',
            error_code=code,
            error_type=error_type[:40],
            validation_summary=summary,
            completed_at=timezone.now(),
            lease_expires_at=None,
            attempt_uuid=None,
        )
        if updated != 1:
            return False
        if code == 'QUEUE_UNAVAILABLE':
            InsuranceImportCreateRequest.objects.filter(
                resolution_job_id=job.id,
            ).update(resolution_job=None)
        if should_refund:
            _decrement_credit(job, credit_year_month)
    _delete_terminal_source(job.id, source_key)
    return True


def _terminalize_locked_attempt(
        job, attempt_uuid, *, code, error_type,
        increment_lease_expired=False):
    """Invalidate an already owner->job locked attempt before releasing it."""
    if (job.attempt_uuid != attempt_uuid
            or job.status not in ('extracting', 'validating')):
        raise StaleAttempt
    expected_status = job.status
    summary, should_refund, credit_year_month = _refund_metadata(job)
    safe_fields = {
        'status': 'failed',
        'error_code': code,
        'error_type': error_type[:40],
        'validation_summary': summary,
        'completed_at': timezone.now(),
        'lease_expires_at': None,
        'attempt_uuid': None,
    }
    if increment_lease_expired:
        safe_fields['lease_expired_count'] = F('lease_expired_count') + 1
    updated = InsuranceExtractionJob.objects.filter(
        pk=job.id,
        owner_id=job.owner_id,
        attempt_uuid=attempt_uuid,
        status=expected_status,
    ).update(**safe_fields)
    if updated != 1:
        raise StaleAttempt
    if should_refund:
        _decrement_credit(job, credit_year_month)
    return job.source_storage_key or ''


def _fail_current_attempt(claim, *, code, error_type):
    """CAS a terminal failure and refund a consumed credit in one DB tx."""
    owner_id = _read_job_owner_id(claim.job_id)
    if owner_id is None:
        raise StaleAttempt
    with transaction.atomic():
        try:
            _lock_owner_row(owner_id)
        except get_user_model().DoesNotExist as exc:
            raise StaleAttempt from exc
        job = _lock_job_row(claim.job_id)
        if (job is None
                or job.owner_id != owner_id
                or job.attempt_uuid != claim.attempt_uuid
                or job.status not in ('extracting', 'validating')):
            raise StaleAttempt
        source_key = _terminalize_locked_attempt(
            job,
            claim.attempt_uuid,
            code=code,
            error_type=error_type,
        )
    _delete_terminal_source(job.id, source_key)


def _delete_terminal_source(job_id, source_key):
    if not source_key:
        return
    job = InsuranceExtractionJob.objects.filter(pk=job_id).first()
    if job is None or job.source_deleted_at is not None:
        return
    try:
        delete_source(job, key=source_key)
    except Exception as exc:
        logger.warning(
            'insurance import source cleanup failed job=%s type=%s',
            job_id, type(exc).__name__)
        return
    InsuranceExtractionJob.objects.filter(
        pk=job_id,
        source_storage_key=source_key,
        source_deleted_at__isnull=True,
        status='failed',
    ).update(source_deleted_at=timezone.now())


def _apply_force_manual_review(validation, force_manual_codes):
    draft = validation.draft
    company_code = (
        ((draft.get('policy') or {}).get('company_code') or {}).get('value'))
    required = company_code in force_manual_codes
    reviewed_draft, summary = apply_force_manual_review(
        validation, required=required)
    return reviewed_draft, summary, required


def _state_counts(values):
    counts = {state: 0 for state in INITIAL_METRIC_STATES}
    for value in values:
        state = value if value in counts else 'invalid'
        counts[state] += 1
    return counts


def _initial_metrics(
        draft, summary, *, provider_rows, zero_provider_rows,
        carrier_code=None):
    policy = draft.get('policy') if isinstance(draft, dict) else {}
    rows = draft.get('coverage_rows') if isinstance(draft, dict) else []
    if not isinstance(policy, dict):
        policy = {}
    if not isinstance(rows, list):
        rows = []
    if carrier_code is None:
        carrier_code = ((policy.get('company_code') or {}).get('value'))
    if type(carrier_code) is not int:
        carrier_code = None
    if type(provider_rows) is not int or provider_rows < 0:
        provider_rows = 0
    zero_provider_rows = int(zero_provider_rows is True)

    safe_counts = {}
    for field in (
            'detected_candidates', 'assigned', 'unmatched',
            'intentionally_excluded'):
        value = summary.get(field, 0) if isinstance(summary, dict) else 0
        safe_counts[field] = value if type(value) is int and value >= 0 else 0
    coverage_states = _state_counts(
        row.get('state') if isinstance(row, dict) else None
        for row in rows
    )
    policy_states = _state_counts(
        evidence.get('state') if isinstance(evidence, dict) else None
        for evidence in policy.values()
    )
    return {
        'schema_version': INITIAL_METRICS_SCHEMA,
        'carrier_code': carrier_code,
        **safe_counts,
        'coverage_row_count': len(rows),
        'coverage_state_counts': coverage_states,
        'policy_field_count': len(policy),
        'policy_state_counts': policy_states,
        'provider_rows': provider_rows,
        'zero_provider_rows': zero_provider_rows,
    }


def _provider_usage(observation):
    usage = getattr(observation, 'usage', None)
    if isinstance(usage, dict):
        return {
            field: value if type(value) is int and value >= 0 else 0
            for field, value in {
                'input_tokens': usage.get('input_tokens', 0),
                'output_tokens': usage.get('output_tokens', 0),
                'cache_read_input_tokens': usage.get(
                    'cache_read_input_tokens', 0),
                'cache_creation_input_tokens': usage.get(
                    'cache_creation_input_tokens', 0),
            }.items()
        }
    return {
        field: value if type(value) is int and value >= 0 else 0
        for field, value in {
            'input_tokens': getattr(observation, 'input_tokens', 0),
            'output_tokens': getattr(observation, 'output_tokens', 0),
            'cache_read_input_tokens': getattr(
                observation, 'cache_read_input_tokens', 0),
            'cache_creation_input_tokens': getattr(
                observation, 'cache_creation_input_tokens', 0),
        }.items()
    }


def _provider_latency(observation, started_at):
    latency_ms = getattr(observation, 'latency_ms', 0)
    if type(latency_ms) is int and latency_ms > 0:
        return latency_ms
    return max(0, int((time.monotonic() - started_at) * 1000))


def _failure_outcomes(code):
    if code == 'PROVIDER_PII_OUTPUT':
        return (
            'privacy_rejected',
            ClaudeApiLog.EXTRACTION_OUTCOME_PRIVACY_REJECTED,
        )
    if code in {'SCHEMA_INVALID', 'SCHEMA_VERSION_MISMATCH'}:
        return (
            'schema_invalid',
            ClaudeApiLog.EXTRACTION_OUTCOME_SCHEMA_INVALID,
        )
    if code in {
            'API_KEY_NOT_CONFIGURED', 'MODEL_NOT_CONFIGURED',
            'PROVIDER_PACKAGE_MISSING'}:
        return (
            'config_failure',
            ClaudeApiLog.EXTRACTION_OUTCOME_CONFIG_FAILURE,
        )
    return (
        'transport_failure',
        ClaudeApiLog.EXTRACTION_OUTCOME_TRANSPORT_FAILURE,
    )


def _record_provider_observation(
        job, observation, *, result_outcome, log_outcome,
        latency_ms, carrier_code=None, matched=0, unmatched=0,
        structured_payload=None):
    """Append the real-call ledger only; job Result persistence is CAS-fenced."""
    usage = _provider_usage(observation)
    model_id = getattr(observation, 'model_id', '')
    if not isinstance(model_id, str) or not model_id:
        model_id = getattr(settings, 'CLAUDE_MODEL_PARSE', '') or ''
    log_claude_usage(
        'insurance_extraction',
        model_id,
        usage,
        user=job.owner,
        outcome=log_outcome,
        carrier_code=carrier_code if type(carrier_code) is int else None,
        matched=matched if type(matched) is int and matched >= 0 else 0,
        unmatched=(
            unmatched if type(unmatched) is int and unmatched >= 0 else 0),
    )
    return {
        'model_id': model_id,
        'outcome': result_outcome,
        'structured_payload': (
            structured_payload
            if isinstance(structured_payload, dict) else {}),
        'input_tokens': usage['input_tokens'],
        'output_tokens': usage['output_tokens'],
        'estimated_cost_krw': estimate_cost_krw(model_id, usage),
        'latency_ms': latency_ms if type(latency_ms) is int and latency_ms >= 0 else 0,
    }


def _safe_provider_shape(observation):
    payload = getattr(observation, 'payload', None)
    if not isinstance(payload, dict):
        return 0, None
    rows = payload.get('coverage_rows')
    provider_rows = len(rows) if isinstance(rows, list) else 0
    policy = payload.get('policy')
    carrier_code = (
        ((policy.get('company_code') or {}).get('value'))
        if isinstance(policy, dict) else None)
    if type(carrier_code) is not int:
        carrier_code = None
    return provider_rows, carrier_code


def _safe_failure_result(result_defaults, outcome):
    """Keep only PII-free provider metadata for a failed job snapshot."""
    return {
        **result_defaults,
        'outcome': outcome,
        'structured_payload': {},
    }


def _fail_provider_attempt(
        claim, *, code, error_type, result_defaults, initial_metrics):
    """Persist one current-attempt provider snapshot and terminal state atomically."""
    owner_id = _read_job_owner_id(claim.job_id)
    if owner_id is None:
        raise StaleAttempt
    with transaction.atomic():
        try:
            _lock_owner_row(owner_id)
        except get_user_model().DoesNotExist as exc:
            raise StaleAttempt from exc
        job = _lock_job_row(claim.job_id)
        if (job is None
                or job.owner_id != owner_id
                or job.attempt_uuid != claim.attempt_uuid
                or job.status != 'validating'):
            raise StaleAttempt
        summary, system = _system_summary(job.validation_summary)
        if 'initial_metrics' not in system:
            system['initial_metrics'] = initial_metrics
        job.validation_summary = summary
        InsuranceExtractionResult.objects.update_or_create(
            job=job,
            provider='claude',
            defaults=result_defaults,
        )
        source_key = _terminalize_locked_attempt(
            job,
            claim.attempt_uuid,
            code=code,
            error_type=error_type,
        )
    _delete_terminal_source(job.id, source_key)


def _prepare_review_snapshot(job, validation, force_manual_codes, provider_rows):
    draft, validation_summary, force_manual_review = _apply_force_manual_review(
        validation, force_manual_codes)
    prior_summary, _system = _system_summary(job.validation_summary)
    source_review = safe_source_review(
        prior_summary, expected_page_count=job.page_count)
    draft, validation_summary = apply_source_review_issue(
        draft, validation_summary, source_review)
    initial_metrics = _initial_metrics(
        draft,
        validation_summary,
        provider_rows=provider_rows,
        zero_provider_rows=False,
    )
    return (
        draft,
        validation_summary,
        force_manual_review,
        initial_metrics,
    )


def _save_review_draft(
        claim, extraction_result, validation, *, provider_latency_ms=None,
        result_defaults=None, provider_rows=None, prepared_review=None):
    with transaction.atomic():
        try:
            job = (
                InsuranceExtractionJob.objects
                .select_for_update()
                .get(
                    pk=claim.job_id,
                    attempt_uuid=claim.attempt_uuid,
                    status='validating',
                )
            )
        except InsuranceExtractionJob.DoesNotExist as exc:
            raise StaleAttempt from exc
        if prepared_review is None:
            prepared_review = _prepare_review_snapshot(
                job,
                validation,
                claim.force_manual_carrier_codes,
                provider_rows=(
                    provider_rows
                    if type(provider_rows) is int
                    else len(extraction_result.payload.get(
                        'coverage_rows', []))),
            )
        (
            draft,
            validation_summary,
            force_manual_review,
            initial_metrics,
        ) = prepared_review
        prior_summary, system = _system_summary(job.validation_summary)
        prior_summary.pop('_system', None)
        system['force_manual_review'] = force_manual_review
        if 'initial_metrics' not in system:
            system['initial_metrics'] = initial_metrics
        validation_summary = {
            **prior_summary,
            **validation_summary,
            '_system': system,
        }
        updated = InsuranceExtractionJob.objects.filter(
            pk=job.id,
            attempt_uuid=claim.attempt_uuid,
            status='validating',
        ).update(
            status='review_required',
            draft_payload=draft,
            validation_summary=validation_summary,
            schema_version=SCHEMA_VERSION,
            prompt_version=PROMPT_VERSION,
            normalization_version=NORMALIZATION_VERSION,
            completed_at=timezone.now(),
            lease_expires_at=None,
            attempt_uuid=None,
        )
        if updated != 1:
            raise StaleAttempt
        if result_defaults is None:
            result_defaults = {
                'model_id': extraction_result.model_id,
                'outcome': 'review_required',
                'structured_payload': extraction_result.payload,
                'input_tokens': extraction_result.input_tokens,
                'output_tokens': extraction_result.output_tokens,
                'estimated_cost_krw': estimate_cost_krw(
                    extraction_result.model_id,
                    _provider_usage(extraction_result),
                ),
                'latency_ms': (
                    provider_latency_ms
                    if type(provider_latency_ms) is int
                    and provider_latency_ms >= 0
                    else extraction_result.latency_ms),
            }
        InsuranceExtractionResult.objects.update_or_create(
            job=job,
            provider='claude',
            defaults=result_defaults,
        )


def _capture_safe_worker_exception(job_id, exc):
    try:
        capture_event({
            'level': 'error',
            'exception': {
                'values': [{'type': type(exc).__name__}],
            },
            'extra': {
                'job_uuid': str(job_id),
                'exception_type': type(exc).__name__,
                'outcome': 'worker_failed',
            },
        })
    except Exception as telemetry_exc:
        logger.warning(
            'insurance import telemetry failed job=%s type=%s',
            job_id, type(telemetry_exc).__name__)


def run_insurance_import(job_id):
    """Run one UUID-only import attempt; never accepts owner/customer/key."""
    provider_started_at = None
    provider_recorded = False
    provider_snapshot = None
    provider_initial_metrics = None
    extraction_result = None
    try:
        claim = claim_import(job_id)
    except StaleAttempt:
        return 'stale'
    except SourceNamespaceMismatch:
        _fail_queued_job(
            job_id,
            code='SOURCE_NAMESPACE_MISMATCH',
            error_type='source_namespace',
        )
        return 'failed'
    except WorkerFailure:
        # A missing or malformed UUID-only queue message has no job row to
        # mutate and must not be retried with any user-supplied metadata.
        return 'missing'

    try:
        job = _current_job(claim, expected_status='extracting')
        extracted = _extract_job_pdf(job)
        _assert_source_readability_matches(job, extracted)
        if extracted.residual_scan_passed is not True:
            raise WorkerFailure(
                'PII_REDACTION_UNCERTAIN',
                error_type='residual_scan',
            )

        # Consent is deliberately fetched again after local PDF work and
        # immediately before the only overseas/provider boundary.
        customer = Customer.objects.get(
            pk=job.customer_id, owner_id=job.owner_id)
        if not has_current_overseas_consent(customer):
            raise WorkerFailure(
                'CONSENT_REVOKED_BEFORE_TRANSFER',
                error_type='consent_revoked')

        # The validating state is the committed provider reservation. A
        # concurrent cancel either wins before this transaction (provider 0)
        # or observes validating and returns CANCEL_IN_PROGRESS.
        _reserve_provider_call(claim)

        provider_started_at = time.monotonic()
        extraction_result = claude_extract(
            extracted.masked_lines,
            extracted.candidates,
            SCHEMA_VERSION,
        )
        # The adapter applies the same gate. Keep this worker boundary as
        # defense in depth so no alternate/mock provider result can persist.
        assert_provider_payload_pii_safe(
            extraction_result.payload,
            provider_grounding_texts(
                extracted.masked_lines, extracted.candidates),
        )
        coverage_rows = extraction_result.payload.get('coverage_rows')
        if not isinstance(coverage_rows, list) or not coverage_rows:
            policy = extraction_result.payload.get('policy') or {}
            carrier_code = ((policy.get('company_code') or {}).get('value'))
            provider_snapshot = _record_provider_observation(
                job,
                extraction_result,
                result_outcome='empty',
                log_outcome=ClaudeApiLog.OUTCOME_EMPTY,
                latency_ms=_provider_latency(
                    extraction_result, provider_started_at),
                carrier_code=carrier_code,
            )
            provider_initial_metrics = _initial_metrics(
                {},
                {},
                provider_rows=0,
                zero_provider_rows=True,
                carrier_code=carrier_code,
            )
            provider_recorded = True
            raise WorkerFailure(
                'EMPTY_COVERAGE_RESULT', error_type='empty_result')

        try:
            validation = validate_draft(
                extracted.masked_lines,
                extracted.candidates,
                extraction_result.payload,
            )
        except Exception:
            provider_rows, carrier_code = _safe_provider_shape(
                extraction_result)
            provider_snapshot = _record_provider_observation(
                job,
                extraction_result,
                result_outcome='schema_invalid',
                log_outcome=(
                    ClaudeApiLog.EXTRACTION_OUTCOME_SCHEMA_INVALID),
                latency_ms=_provider_latency(
                    extraction_result, provider_started_at),
            )
            provider_initial_metrics = _initial_metrics(
                {},
                {},
                provider_rows=provider_rows,
                zero_provider_rows=False,
                carrier_code=carrier_code,
            )
            provider_recorded = True
            try:
                _fail_provider_attempt(
                    claim,
                    code='SCHEMA_INVALID',
                    error_type='provider_schema',
                    result_defaults=provider_snapshot,
                    initial_metrics=provider_initial_metrics,
                )
            except StaleAttempt:
                return 'stale'
            return 'failed'
        policy = validation.draft.get('policy') or {}
        carrier_code = ((policy.get('company_code') or {}).get('value'))
        provider_latency_ms = _provider_latency(
            extraction_result, provider_started_at)
        provider_snapshot = _record_provider_observation(
            job,
            extraction_result,
            result_outcome='review_required',
            log_outcome=ClaudeApiLog.OUTCOME_SUCCESS,
            latency_ms=provider_latency_ms,
            carrier_code=carrier_code,
            matched=validation.summary.get('assigned', 0),
            unmatched=validation.summary.get('unmatched', 0),
            structured_payload=extraction_result.payload,
        )
        provider_recorded = True
        prepared_review = _prepare_review_snapshot(
            job,
            validation,
            claim.force_manual_carrier_codes,
            provider_rows=len(coverage_rows),
        )
        provider_initial_metrics = prepared_review[3]
        _save_review_draft(
            claim,
            extraction_result,
            validation,
            provider_latency_ms=provider_latency_ms,
            result_defaults=provider_snapshot,
            provider_rows=len(coverage_rows),
            prepared_review=prepared_review,
        )
        return 'review_required'
    except StaleAttempt:
        return 'stale'
    except SourceNamespaceMismatch:
        try:
            _fail_current_attempt(
                claim, code='SOURCE_NAMESPACE_MISMATCH',
                error_type='source_namespace')
        except StaleAttempt:
            return 'stale'
        return 'failed'
    except PDFImportError as exc:
        try:
            _fail_current_attempt(
                claim, code=exc.code, error_type='pdf_resource')
        except StaleAttempt:
            return 'stale'
        return 'failed'
    except ExtractionFailure as exc:
        if provider_started_at is not None and not provider_recorded:
            result_outcome, log_outcome = _failure_outcomes(exc.code)
            source = extraction_result or exc
            provider_rows, carrier_code = _safe_provider_shape(source)
            provider_snapshot = _record_provider_observation(
                job,
                source,
                result_outcome=result_outcome,
                log_outcome=log_outcome,
                latency_ms=_provider_latency(source, provider_started_at),
                carrier_code=carrier_code,
            )
            provider_initial_metrics = _initial_metrics(
                {},
                {},
                provider_rows=provider_rows,
                zero_provider_rows=False,
                carrier_code=carrier_code,
            )
            provider_recorded = True
        try:
            if provider_snapshot is not None:
                _fail_provider_attempt(
                    claim,
                    code=exc.code,
                    error_type=exc.error_type or 'provider',
                    result_defaults=provider_snapshot,
                    initial_metrics=provider_initial_metrics,
                )
            else:
                _fail_current_attempt(
                    claim, code=exc.code,
                    error_type=exc.error_type or 'provider')
        except StaleAttempt:
            return 'stale'
        return 'failed'
    except WorkerFailure as exc:
        try:
            if provider_snapshot is not None:
                _fail_provider_attempt(
                    claim,
                    code=exc.code,
                    error_type=exc.error_type,
                    result_defaults=provider_snapshot,
                    initial_metrics=provider_initial_metrics,
                )
            else:
                _fail_current_attempt(
                    claim, code=exc.code, error_type=exc.error_type)
        except StaleAttempt:
            return 'stale'
        return 'failed'
    except Exception as exc:
        _capture_safe_worker_exception(claim.job_id, exc)
        try:
            if (provider_snapshot is not None
                    and provider_initial_metrics is not None):
                _fail_provider_attempt(
                    claim,
                    code='WORKER_FAILED',
                    error_type=type(exc).__name__,
                    result_defaults=_safe_failure_result(
                        provider_snapshot,
                        'post_provider_persistence_failure',
                    ),
                    initial_metrics=provider_initial_metrics,
                )
            else:
                _fail_current_attempt(
                    claim, code='WORKER_FAILED',
                    error_type=type(exc).__name__)
        except StaleAttempt:
            return 'stale'
        return 'failed'


@shared_task(
    bind=True,
    name='inpa.insurances.process_insurance_import',
    max_retries=None,
)
def process_insurance_import(self, job_id):
    """Celery envelope. The serialized message contains only one job UUID."""
    try:
        return run_insurance_import(job_id)
    except CapacityUnavailable as exc:
        raise self.retry(
            exc=exc,
            countdown=CAPACITY_RETRY_SECONDS,
            max_retries=None,
        )
