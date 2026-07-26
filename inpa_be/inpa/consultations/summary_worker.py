import math
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone

from inpa.billing.pricing import estimate_cost_krw
from inpa.customers.consent_texts import (
    has_current_consultation_summary_consents,
)
from inpa.customers.models import CustomerMemo

from .audio import AudioTranscodeError, open_clova_wav
from .callbacks import make_clova_callback_url
from .gates import summary_feature_enabled
from .models import (
    ConsultationRecording,
    ConsultationRuntimeConfig,
    ConsultationSummaryRun,
)
from .quota import ai_cost_budget_available
from .providers.anthropic_summary import AnthropicConsultationSummarizer
from .providers.base import (
    ExplicitProviderNonReceipt,
    SpeechProviderProtocolError,
    SpeechProviderTemporaryError,
    SpeechSubmitOutcomeUnknown,
    SummaryOutcomeUnknown,
)
from .providers.clova import ClovaSpeechProvider
from .services import get_recording_storage
from .summary_schema import InvalidSummary, render_summary_memo
from .summary_service import settle_summary_failure, settle_summary_success
from .transcript_mask import UnsafeTranscript, mask_transcript


TERMINAL_STATUSES = {
    ConsultationSummaryRun.STATUS_SUCCEEDED,
    ConsultationSummaryRun.STATUS_FAILED,
    ConsultationSummaryRun.STATUS_AMBIGUOUS,
    ConsultationSummaryRun.STATUS_CANCELLED,
}
ACTIVE_STATUSES = {
    ConsultationSummaryRun.STATUS_TRANSCRIBING,
    ConsultationSummaryRun.STATUS_SUMMARIZING,
}


@dataclass(frozen=True)
class StepResult:
    outcome: str
    retry_after: int = 0


def _safe_code(value, fallback):
    if not isinstance(value, str):
        return fallback
    cleaned = ''.join(
        character
        for character in value.upper()
        if character.isalnum() or character == '_'
    )
    return (cleaned or fallback)[:80]


def _source_is_current(run):
    recording = run.recording
    return (
        recording.status in {
            ConsultationRecording.STATUS_READY,
            ConsultationRecording.STATUS_PROCESSING,
            ConsultationRecording.STATUS_COMPLETED,
        }
        and bool(recording.storage_key)
        and (
            recording.expires_at is None
            or recording.expires_at > timezone.now()
        )
        and has_current_consultation_summary_consents(recording.customer)
        and summary_feature_enabled(recording.owner)
    )


def _mark_recording_status(recording, status):
    if recording.status in {
        ConsultationRecording.STATUS_DELETING,
        ConsultationRecording.STATUS_DELETED,
    }:
        return
    if recording.status == status:
        return
    recording.status = status
    recording.version += 1
    recording.save(update_fields=['status', 'version', 'updated_at'])


def _terminal_failure(
    run_id,
    *,
    status,
    outcome,
    error_code,
    error_type='',
    provider_started,
):
    with transaction.atomic():
        recording_id = ConsultationSummaryRun.objects.filter(
            pk=run_id,
        ).values_list('recording_id', flat=True).first()
        if recording_id is None:
            return None
        ConsultationRecording.objects.select_for_update().get(
            pk=recording_id,
        )
        run = (
            ConsultationSummaryRun.objects.select_for_update()
            .select_related('recording__owner')
            .get(pk=run_id)
        )
        if run.status in TERMINAL_STATUSES:
            return run
        now = timezone.now()
        run.status = status
        run.outcome = _safe_code(outcome, 'FAILED').lower()
        run.error_code = _safe_code(error_code, 'SUMMARY_FAILED')
        run.error_type = _safe_code(error_type, '') if error_type else ''
        run.completed_at = now
        run.lease_expires_at = None
        run.save(update_fields=[
            'status',
            'outcome',
            'error_code',
            'error_type',
            'completed_at',
            'lease_expires_at',
            'updated_at',
        ])
        if status == ConsultationSummaryRun.STATUS_FAILED:
            _mark_recording_status(
                run.recording,
                ConsultationRecording.STATUS_FAILED,
            )
        elif status == ConsultationSummaryRun.STATUS_AMBIGUOUS:
            _mark_recording_status(
                run.recording,
                ConsultationRecording.STATUS_AMBIGUOUS,
            )
        settle_summary_failure(
            run.id,
            provider_started=provider_started,
        )
        return run


def cancel_summary_run(run_id, *, reason):
    try:
        run = ConsultationSummaryRun.objects.select_related(
            'recording',
        ).get(pk=run_id)
    except ConsultationSummaryRun.DoesNotExist:
        return None
    if run.status in TERMINAL_STATUSES:
        return run
    return _terminal_failure(
        run.id,
        status=ConsultationSummaryRun.STATUS_CANCELLED,
        outcome='cancelled',
        error_code=reason,
        provider_started=bool(run.provider_reserved_at),
    )


def cancel_recording_summary(recording_id, *, reason):
    run_id = ConsultationSummaryRun.objects.filter(
        recording_id=recording_id,
    ).values_list('id', flat=True).first()
    if run_id is None:
        return None
    return cancel_summary_run(run_id, reason=reason)


def _claim(run_id):
    now = timezone.now()
    with transaction.atomic():
        ConsultationRuntimeConfig.objects.select_for_update().get_or_create(
            pk=1,
        )
        run = (
            ConsultationSummaryRun.objects.select_for_update()
            .select_related('recording__customer', 'recording__owner__profile')
            .get(pk=run_id)
        )
        if run.status in TERMINAL_STATUSES:
            return None, StepResult('terminal')
        if run.lease_expires_at and run.lease_expires_at > now:
            return None, StepResult(
                'leased',
                settings.CONSULTATION_SUMMARY_POLL_SECONDS,
            )
        active_count = (
            ConsultationSummaryRun.objects.filter(
                status__in=ACTIVE_STATUSES,
                lease_expires_at__gt=now,
            )
            .exclude(pk=run.pk)
            .count()
        )
        if active_count >= max(
            1,
            settings.CONSULTATION_SUMMARY_ACTIVE_LIMIT,
        ):
            return None, StepResult(
                'capacity',
                settings.CONSULTATION_SUMMARY_POLL_SECONDS,
            )
        run.lease_expires_at = now + timedelta(
            seconds=max(30, settings.CONSULTATION_SUMMARY_LEASE_SECONDS),
        )
        run.attempt_count += 1
        if run.status == ConsultationSummaryRun.STATUS_QUEUED:
            run.status = ConsultationSummaryRun.STATUS_TRANSCRIBING
        if run.started_at is None:
            run.started_at = now
        run.save(update_fields=[
            'lease_expires_at',
            'attempt_count',
            'status',
            'started_at',
            'updated_at',
        ])
        return run, None


def _release_for_retry(run_id, *, status=None):
    with transaction.atomic():
        run = ConsultationSummaryRun.objects.select_for_update().get(pk=run_id)
        if run.status in TERMINAL_STATUSES:
            return
        run.lease_expires_at = None
        update_fields = ['lease_expires_at', 'updated_at']
        if status is not None:
            run.status = status
            update_fields.append('status')
        run.save(update_fields=update_fields)


def _reserve_stt(run_id):
    with transaction.atomic():
        recording_id = ConsultationSummaryRun.objects.filter(
            pk=run_id,
        ).values_list('recording_id', flat=True).first()
        if recording_id is None:
            return None
        ConsultationRecording.objects.select_for_update().get(
            pk=recording_id,
        )
        run = (
            ConsultationSummaryRun.objects.select_for_update()
            .select_related('recording')
            .get(pk=run_id)
        )
        if run.status in TERMINAL_STATUSES:
            return None
        if run.stt_job_id:
            return run
        if run.provider_reserved_at is not None:
            return None
        run.provider_reserved_at = timezone.now()
        run.status = ConsultationSummaryRun.STATUS_TRANSCRIBING
        run.stt_provider = settings.CONSULTATION_STT_PROVIDER
        run.save(update_fields=[
            'provider_reserved_at',
            'status',
            'stt_provider',
            'updated_at',
        ])
        _mark_recording_status(
            run.recording,
            ConsultationRecording.STATUS_PROCESSING,
        )
        return run


def _submit_stt(run):
    try:
        callback_url = make_clova_callback_url(run)
    except ImproperlyConfigured as exc:
        return _terminal_failure(
            run.id,
            status=ConsultationSummaryRun.STATUS_FAILED,
            outcome='failed',
            error_code='SUMMARY_CONFIGURATION_INVALID',
            error_type=type(exc).__name__,
            provider_started=False,
        ), StepResult('failed')
    reserved = _reserve_stt(run.id)
    if reserved is None:
        return _terminal_failure(
            run.id,
            status=ConsultationSummaryRun.STATUS_AMBIGUOUS,
            outcome='ambiguous',
            error_code='STT_SUBMISSION_OUTCOME_UNKNOWN',
            provider_started=True,
        ), StepResult('ambiguous')
    try:
        provider = ClovaSpeechProvider()
        storage = get_recording_storage()
        with open_clova_wav(
            storage,
            reserved.recording.storage_key,
        ) as prepared:
            submitted = provider.submit(prepared, callback_url)
    except ExplicitProviderNonReceipt as exc:
        with transaction.atomic():
            locked = ConsultationSummaryRun.objects.select_for_update().get(
                pk=run.id,
            )
            if locked.status in TERMINAL_STATUSES:
                return locked, StepResult('terminal')
            locked.provider_reserved_at = None
            locked.stt_provider = ''
            locked.status = ConsultationSummaryRun.STATUS_QUEUED
            locked.lease_expires_at = None
            locked.error_code = 'STT_EXPLICIT_NON_RECEIPT'
            locked.error_type = type(exc).__name__
            locked.save(update_fields=[
                'provider_reserved_at',
                'stt_provider',
                'status',
                'lease_expires_at',
                'error_code',
                'error_type',
                'updated_at',
            ])
            attempts = locked.attempt_count
        if attempts >= 3:
            return _terminal_failure(
                run.id,
                status=ConsultationSummaryRun.STATUS_FAILED,
                outcome='failed',
                error_code='STT_CONNECT_RETRY_EXHAUSTED',
                error_type=type(exc).__name__,
                provider_started=False,
            ), StepResult('failed')
        return locked, StepResult('retry', min(4, 2 ** (attempts - 1)))
    except SpeechSubmitOutcomeUnknown as exc:
        return _terminal_failure(
            run.id,
            status=ConsultationSummaryRun.STATUS_AMBIGUOUS,
            outcome='ambiguous',
            error_code='STT_SUBMISSION_OUTCOME_UNKNOWN',
            error_type=type(exc).__name__,
            provider_started=True,
        ), StepResult('ambiguous')
    except (
        AudioTranscodeError,
        ImproperlyConfigured,
        OSError,
        ValueError,
    ) as exc:
        return _terminal_failure(
            run.id,
            status=ConsultationSummaryRun.STATUS_FAILED,
            outcome='failed',
            error_code='AUDIO_PREPARATION_FAILED',
            error_type=type(exc).__name__,
            provider_started=False,
        ), StepResult('failed')
    except Exception as exc:
        return _terminal_failure(
            run.id,
            status=ConsultationSummaryRun.STATUS_AMBIGUOUS,
            outcome='ambiguous',
            error_code='STT_SUBMISSION_OUTCOME_UNKNOWN',
            error_type=type(exc).__name__,
            provider_started=True,
        ), StepResult('ambiguous')
    with transaction.atomic():
        locked = ConsultationSummaryRun.objects.select_for_update().get(
            pk=run.id,
        )
        if locked.status in TERMINAL_STATUSES:
            return locked, StepResult('terminal')
        locked.stt_job_id = submitted.job_id
        locked.lease_expires_at = None
        locked.error_code = ''
        locked.error_type = ''
        locked.save(update_fields=[
            'stt_job_id',
            'lease_expires_at',
            'error_code',
            'error_type',
            'updated_at',
        ])
    return locked, StepResult(
        'submitted',
        settings.CONSULTATION_SUMMARY_POLL_SECONDS,
    )


def _reserve_summary(run_id):
    with transaction.atomic():
        run = ConsultationSummaryRun.objects.select_for_update().get(pk=run_id)
        if run.status in TERMINAL_STATUSES:
            return None
        if run.summary_reserved_at is not None:
            return None
        run.summary_reserved_at = timezone.now()
        run.status = ConsultationSummaryRun.STATUS_SUMMARIZING
        run.summary_provider = 'anthropic'
        run.save(update_fields=[
            'summary_reserved_at',
            'status',
            'summary_provider',
            'updated_at',
        ])
        return run


def _known_names(recording):
    profile = getattr(recording.owner, 'profile', None)
    return [
        recording.customer.name,
        getattr(profile, 'name', ''),
    ]


def _complete_success(run_id, provider_result):
    body = render_summary_memo(provider_result.summary)
    now = timezone.now()
    with transaction.atomic():
        recording_id = ConsultationSummaryRun.objects.filter(
            pk=run_id,
        ).values_list('recording_id', flat=True).first()
        if recording_id is None:
            return None
        ConsultationRecording.objects.select_for_update().get(
            pk=recording_id,
        )
        run = (
            ConsultationSummaryRun.objects.select_for_update()
            .select_related('recording__customer', 'recording__owner')
            .get(pk=run_id)
        )
        if run.status in TERMINAL_STATUSES:
            return run
        if not _source_is_current(run):
            return cancel_summary_run(
                run.id,
                reason='SUMMARY_PRECONDITION_CHANGED',
            )
        recording = run.recording
        memo, _ = CustomerMemo.objects.get_or_create(
            summary_run=run,
            defaults={
                'owner': recording.owner,
                'customer': recording.customer,
                'source': CustomerMemo.SOURCE_AI_SUMMARY,
                'body': body,
                'occurred_at': recording.ended_at,
            },
        )
        customer = recording.customer
        if (
            recording.ended_at
            and (
                customer.last_contacted_at is None
                or customer.last_contacted_at < recording.ended_at
            )
        ):
            customer.last_contacted_at = recording.ended_at
            customer.save(update_fields=['last_contacted_at'])
        run.status = ConsultationSummaryRun.STATUS_SUCCEEDED
        run.outcome = 'succeeded'
        run.summary_model = provider_result.model[:100]
        run.input_tokens = provider_result.input_tokens
        run.output_tokens = provider_result.output_tokens
        run.estimated_cost_krw = int(math.ceil(estimate_cost_krw(
            provider_result.model,
            {
                'input_tokens': provider_result.input_tokens,
                'output_tokens': provider_result.output_tokens,
            },
        )))
        run.processing_seconds = max(
            0,
            int((now - (run.started_at or now)).total_seconds()),
        )
        run.completed_at = now
        run.lease_expires_at = None
        run.error_code = ''
        run.error_type = ''
        run.save(update_fields=[
            'status',
            'outcome',
            'summary_model',
            'input_tokens',
            'output_tokens',
            'estimated_cost_krw',
            'processing_seconds',
            'completed_at',
            'lease_expires_at',
            'error_code',
            'error_type',
            'updated_at',
        ])
        _mark_recording_status(
            recording,
            ConsultationRecording.STATUS_COMPLETED,
        )
        settle_summary_success(run.id)
        return run


def _poll_and_summarize(run):
    try:
        provider = ClovaSpeechProvider()
        result = provider.poll(run.stt_job_id)
    except SpeechProviderTemporaryError:
        _release_for_retry(run.id)
        return StepResult(
            'poll_retry',
            settings.CONSULTATION_SUMMARY_POLL_SECONDS,
        )
    except SpeechProviderProtocolError as exc:
        _terminal_failure(
            run.id,
            status=ConsultationSummaryRun.STATUS_FAILED,
            outcome='failed',
            error_code='STT_RESPONSE_INVALID',
            error_type=type(exc).__name__,
            provider_started=True,
        )
        return StepResult('failed')
    except ImproperlyConfigured as exc:
        _terminal_failure(
            run.id,
            status=ConsultationSummaryRun.STATUS_FAILED,
            outcome='failed',
            error_code='SUMMARY_CONFIGURATION_INVALID',
            error_type=type(exc).__name__,
            provider_started=True,
        )
        return StepResult('failed')
    except Exception as exc:
        _terminal_failure(
            run.id,
            status=ConsultationSummaryRun.STATUS_FAILED,
            outcome='failed',
            error_code='STT_RESPONSE_INVALID',
            error_type=type(exc).__name__,
            provider_started=True,
        )
        return StepResult('failed')
    if result.state in {'waiting', 'processing'}:
        _release_for_retry(run.id)
        return StepResult(
            result.state,
            settings.CONSULTATION_SUMMARY_POLL_SECONDS,
        )
    if result.state in {'failed', 'timeout'}:
        _terminal_failure(
            run.id,
            status=ConsultationSummaryRun.STATUS_FAILED,
            outcome='failed',
            error_code=result.error_code or f'STT_{result.state.upper()}',
            provider_started=True,
        )
        return StepResult('failed')

    run = (
        ConsultationSummaryRun.objects
        .select_related('recording__customer', 'recording__owner__profile')
        .get(pk=run.id)
    )
    if not _source_is_current(run):
        cancel_summary_run(
            run.id,
            reason='SUMMARY_PRECONDITION_CHANGED',
        )
        return StepResult('cancelled')
    try:
        masked = mask_transcript(
            result.transcript,
            _known_names(run.recording),
        )
    except UnsafeTranscript as exc:
        _terminal_failure(
            run.id,
            status=ConsultationSummaryRun.STATUS_FAILED,
            outcome='failed',
            error_code='TRANSCRIPT_MASKING_FAILED',
            error_type=type(exc).__name__,
            provider_started=True,
        )
        return StepResult('failed')
    if _reserve_summary(run.id) is None:
        _terminal_failure(
            run.id,
            status=ConsultationSummaryRun.STATUS_AMBIGUOUS,
            outcome='ambiguous',
            error_code='SUMMARY_OUTCOME_UNKNOWN',
            provider_started=True,
        )
        return StepResult('ambiguous')
    try:
        summary_result = AnthropicConsultationSummarizer().summarize(
            masked.text,
        )
    except SummaryOutcomeUnknown as exc:
        _terminal_failure(
            run.id,
            status=ConsultationSummaryRun.STATUS_AMBIGUOUS,
            outcome='ambiguous',
            error_code='SUMMARY_OUTCOME_UNKNOWN',
            error_type=type(exc).__name__,
            provider_started=True,
        )
        return StepResult('ambiguous')
    except InvalidSummary as exc:
        _terminal_failure(
            run.id,
            status=ConsultationSummaryRun.STATUS_FAILED,
            outcome='failed',
            error_code='SUMMARY_RESPONSE_INVALID',
            error_type=type(exc).__name__,
            provider_started=True,
        )
        return StepResult('failed')
    except ImproperlyConfigured as exc:
        _terminal_failure(
            run.id,
            status=ConsultationSummaryRun.STATUS_FAILED,
            outcome='failed',
            error_code='SUMMARY_CONFIGURATION_INVALID',
            error_type=type(exc).__name__,
            provider_started=True,
        )
        return StepResult('failed')
    _complete_success(run.id, summary_result)
    return StepResult('succeeded')


def run_summary_step(run_id):
    try:
        run, early = _claim(run_id)
    except ConsultationSummaryRun.DoesNotExist:
        return StepResult('missing')
    if early is not None:
        return early
    if not _source_is_current(run):
        cancel_summary_run(
            run.id,
            reason='SUMMARY_PRECONDITION_CHANGED',
        )
        return StepResult('cancelled')
    if not run.stt_job_id:
        if not ai_cost_budget_available():
            _terminal_failure(
                run.id,
                status=ConsultationSummaryRun.STATUS_FAILED,
                outcome='failed',
                error_code='SUMMARY_COST_LIMIT_REACHED',
                provider_started=False,
            )
            return StepResult('failed')
        if run.provider_reserved_at is not None:
            _terminal_failure(
                run.id,
                status=ConsultationSummaryRun.STATUS_AMBIGUOUS,
                outcome='ambiguous',
                error_code='STT_SUBMISSION_OUTCOME_UNKNOWN',
                provider_started=True,
            )
            return StepResult('ambiguous')
        _, result = _submit_stt(run)
        return result
    return _poll_and_summarize(run)
