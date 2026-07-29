import math

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from inpa.billing.credit import resolve_effective_plan
from inpa.billing.models import UsageMeter
from inpa.core.internal_accounts import internal_user_q
from inpa.customers.consent_texts import (
    CONSULTATION_CONSENT_VERSIONS,
    CONSULTATION_SUMMARY_CONSENT_VERSION,
    has_current_consultation_summary_consents,
)

from .gates import summary_feature_enabled
from .models import (
    ConsultationCustomerBenefit,
    ConsultationRecording,
    ConsultationSummaryRun,
)
from .quota import (
    ai_cost_budget_available,
    assert_success_slot_available,
    consume_success_meter,
    release_meter,
    reserve_minute_meter,
)


class SummaryPrecondition(RuntimeError):
    def __init__(self, code, detail, status_code=409):
        super().__init__(code)
        self.code = code
        self.detail = detail
        self.status_code = status_code


def enqueue_summary_run(run_id):
    from .tasks import process_consultation_summary
    if not ConsultationSummaryRun.objects.filter(pk=run_id).exclude(
        internal_user_q('recording__owner'),
    ).exists():
        return
    process_consultation_summary.delay(str(run_id))


def validate_summary_request(recording, user):
    if recording.owner_id != user.pk:
        raise SummaryPrecondition(
            'RECORDING_NOT_FOUND',
            '이 고객의 녹음 목록을 다시 확인해 주세요.',
            404,
        )
    if not summary_feature_enabled(user):
        raise SummaryPrecondition(
            'SUMMARY_FEATURE_CLOSED',
            '요약 사용 설정을 마치면 바로 정리할 수 있어요.',
            403,
        )
    if (
        recording.status != ConsultationRecording.STATUS_READY
        or not recording.storage_key
        or recording.duration_ms <= 0
    ):
        raise SummaryPrecondition(
            'RECORDING_SOURCE_UNAVAILABLE',
            '원본이 보관 중인 녹음에서 요약을 만들 수 있어요.',
        )
    if not has_current_consultation_summary_consents(recording.customer):
        raise SummaryPrecondition(
            'CONSULTATION_SUMMARY_CONSENT_REQUIRED',
            '고객 동의를 다시 확인하면 바로 요약할 수 있어요.',
            412,
        )
    if not ai_cost_budget_available():
        raise SummaryPrecondition(
            'SUMMARY_COST_LIMIT_REACHED',
            '운영 한도를 확인하고 있어요. 잠시 후 다시 요약해 주세요.',
            503,
        )


def _reserve_customer_benefit_if_free(*, run, user, customer):
    plan = resolve_effective_plan(user)
    if plan.code != 'free':
        return None
    benefit = ConsultationCustomerBenefit.objects.select_for_update().filter(
        owner=user,
        customer=customer,
    ).first()
    if benefit is not None:
        if benefit.status == ConsultationCustomerBenefit.STATUS_CONSUMED:
            raise SummaryPrecondition(
                'CUSTOMER_FREE_SUMMARY_USED',
                '이 고객의 무료 요약을 사용했어요. 요금제를 바꾸면 새 녹음도 요약할 수 있어요.',
                402,
            )
        if benefit.reserved_run_id != run.id:
            raise SummaryPrecondition(
                'CUSTOMER_FREE_SUMMARY_RESERVED',
                '이 고객의 요약을 정리하고 있어요. 완료 상태를 확인해 주세요.',
            )
        return benefit
    return ConsultationCustomerBenefit.objects.create(
        owner=user,
        customer=customer,
        status=ConsultationCustomerBenefit.STATUS_RESERVED,
        reserved_run=run,
        reserved_at=timezone.now(),
    )


def request_summary(*, recording, user, idempotency_key):
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise SummaryPrecondition(
            'IDEMPOTENCY_KEY_REQUIRED',
            '요약 요청을 다시 확인해 주세요.',
            400,
        )
    if len(idempotency_key) > 80:
        raise SummaryPrecondition(
            'IDEMPOTENCY_KEY_INVALID',
            '요약 요청을 다시 확인해 주세요.',
            400,
        )
    with transaction.atomic():
        locked = (
            ConsultationRecording.objects.select_for_update()
            .select_related('customer')
            .get(pk=recording.pk, owner=user)
        )
        existing = ConsultationSummaryRun.objects.filter(
            recording=locked,
        ).first()
        if existing is not None:
            return existing, False

        validate_summary_request(locked, user)
        year_month = UsageMeter.current_month()
        minutes = max(1, math.ceil(locked.duration_ms / 60_000))
        assert_success_slot_available(user=user, year_month=year_month)
        run = ConsultationSummaryRun.objects.create(
            recording=locked,
            status=ConsultationSummaryRun.STATUS_QUEUED,
            idempotency_key=idempotency_key.strip(),
            prompt_version=settings.CONSULTATION_SUMMARY_PROMPT_VERSION,
            recording_consent_version=CONSULTATION_CONSENT_VERSIONS[
                'consultation_recording'
            ],
            sensitive_consent_version=CONSULTATION_CONSENT_VERSIONS[
                'consultation_sensitive'
            ],
            overseas_consent_version=CONSULTATION_SUMMARY_CONSENT_VERSION,
            usage_year_month=year_month,
            success_count_reserved=1,
            processing_minutes_reserved=minutes,
        )
        reserve_minute_meter(
            user=user,
            amount=minutes,
            year_month=year_month,
        )
        _reserve_customer_benefit_if_free(
            run=run,
            user=user,
            customer=locked.customer,
        )
        transaction.on_commit(
            lambda run_id=run.id: enqueue_summary_run(run_id),
        )
        return run, True


def settle_summary_success(run_id):
    with transaction.atomic():
        run = (
            ConsultationSummaryRun.objects.select_for_update()
            .select_related('recording__owner')
            .get(pk=run_id)
        )
        if run.success_count_reserved != 1:
            return run
        consume_success_meter(
            user=run.recording.owner,
            year_month=run.usage_year_month,
        )
        benefit = ConsultationCustomerBenefit.objects.select_for_update().filter(
            reserved_run=run,
        ).first()
        if benefit is not None:
            benefit.status = ConsultationCustomerBenefit.STATUS_CONSUMED
            benefit.consumed_at = timezone.now()
            benefit.save(update_fields=['status', 'consumed_at'])
        run.success_count_reserved = 0
        run.success_reservation_released_at = timezone.now()
        run.save(update_fields=[
            'success_count_reserved',
            'success_reservation_released_at',
            'updated_at',
        ])
        return run


def settle_summary_failure(run_id, *, provider_started):
    with transaction.atomic():
        run = (
            ConsultationSummaryRun.objects.select_for_update()
            .select_related('recording__owner')
            .get(pk=run_id)
        )
        now = timezone.now()
        if run.success_count_reserved == 1:
            run.success_count_reserved = 0
            run.success_reservation_released_at = now
            ConsultationCustomerBenefit.objects.filter(
                reserved_run=run,
                status=ConsultationCustomerBenefit.STATUS_RESERVED,
            ).delete()
        if (
            not provider_started
            and run.processing_minutes_reserved > 0
            and run.minute_reservation_released_at is None
        ):
            release_meter(
                user=run.recording.owner,
                action='consultation_minute',
                amount=run.processing_minutes_reserved,
                year_month=run.usage_year_month,
            )
            run.minute_reservation_released_at = now
        run.save(update_fields=[
            'success_count_reserved',
            'success_reservation_released_at',
            'minute_reservation_released_at',
            'updated_at',
        ])
        return run
