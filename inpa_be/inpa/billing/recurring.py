"""중복 승인 없이 월 정기결제를 처리하는 주문 원장."""

from datetime import datetime, time, timedelta
import hashlib
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from .agreements import (
    BillingFlowError,
    enqueue_token_revocation,
    has_current_reconfirmation,
    vat_inclusive_amount,
)
from .calendar import period_for
from .gates import recurring_charge_enabled
from .kicc import ChargeResult, KiccBillingClient, KiccIntegrityError
from .models import (
    BillingAgreement,
    BillingNoticeEvent,
    PaymentAttempt,
    PaymentMethodToken,
    PaymentOrder,
    Plan,
    Subscription,
)
from .payment_tokens import decrypt_billing_token

_KST = ZoneInfo('Asia/Seoul')


def _kst_midnight(local_date):
    return timezone.make_aware(
        datetime.combine(local_date, time.min),
        timezone=_KST,
    )


def _merchant_order_id(agreement, sequence):
    return f'INPA-P-{agreement.id.hex}-{sequence:06d}'


def _provider_request_id(order):
    digest = hashlib.sha256(
        f'{order.merchant_order_id}|{order.amount_krw}'.encode(),
    ).hexdigest()[:24]
    return f'INPA-PA-{digest}'


def create_due_order(agreement_id, due_date):
    with transaction.atomic():
        agreement = (
            BillingAgreement.objects.select_for_update()
            .select_related('plan')
            .get(pk=agreement_id)
        )
        if (
            agreement.next_charge_date != due_date
            or agreement.status not in (
                'trialing', 'active', 'renewal_processing')
        ):
            raise BillingFlowError(
                'agreement_not_due',
                '현재 결제 일정을 다시 확인해 주세요.',
                status_code=409,
            )
        sequence = agreement.cycle_sequence + 1
        order, _ = PaymentOrder.objects.get_or_create(
            agreement=agreement,
            cycle_sequence=sequence,
            defaults={
                'merchant_order_id':
                    _merchant_order_id(agreement, sequence),
                'amount_krw':
                    vat_inclusive_amount(agreement.plan.price_krw),
                'due_date': due_date,
                'status': 'created',
            },
        )
        return order


def _active_token(agreement, *, lock=False):
    queryset = PaymentMethodToken.objects.filter(
        agreement=agreement,
        status='active',
    )
    if lock:
        queryset = queryset.select_for_update()
    return queryset.first()


def _notice(user, *, reason, event_key):
    return BillingNoticeEvent.objects.get_or_create(
        user=user,
        event_key=event_key,
        notice_type='free_transition',
        defaults={'reason': reason},
    )[0]


def _queue_token_revocation(token):
    if not token or token.status != 'active':
        return
    token.status = 'revocation_pending'
    token.save(update_fields=['status', 'updated_at'])
    transaction.on_commit(
        lambda token_id=token.pk:
            enqueue_token_revocation(token_id)
    )


def project_free_entitlement(
    agreement,
    *,
    reason,
    event_key,
):
    free = Plan.objects.get(code='free')
    subscription, _ = Subscription.objects.select_for_update().get_or_create(
        user=agreement.user,
        defaults={'plan': free, 'status': 'active'},
    )
    subscription.plan = free
    subscription.status = 'active'
    subscription.expires_at = None
    subscription.cancelled_at = None
    subscription.auto_renew = False
    subscription.next_billing_at = None
    subscription.save(update_fields=[
        'plan',
        'status',
        'expires_at',
        'cancelled_at',
        'auto_renew',
        'next_billing_at',
    ])
    agreement.status = 'free'
    agreement.next_charge_date = None
    agreement.save(update_fields=[
        'status', 'next_charge_date', 'updated_at'])
    _notice(agreement.user, reason=reason, event_key=event_key)
    return subscription


def project_subscription(agreement):
    period = period_for(
        agreement.next_charge_date,
        1,
        anchor_day=agreement.billing_anchor_day,
    )
    agreement.status = 'active'
    agreement.cycle_sequence += 1
    agreement.current_period_starts_on = period.starts_on
    agreement.current_period_ends_on = period.access_through
    agreement.next_charge_date = period.next_charge_date
    agreement.save(update_fields=[
        'status',
        'cycle_sequence',
        'current_period_starts_on',
        'current_period_ends_on',
        'next_charge_date',
        'updated_at',
    ])
    subscription, _ = Subscription.objects.select_for_update().get_or_create(
        user=agreement.user,
        defaults={'plan': agreement.plan, 'status': 'active'},
    )
    subscription.plan = agreement.plan
    subscription.status = 'active'
    subscription.expires_at = _kst_midnight(period.next_charge_date)
    subscription.cancelled_at = None
    subscription.auto_renew = True
    subscription.next_billing_at = _kst_midnight(
        period.next_charge_date)
    subscription.save(update_fields=[
        'plan',
        'status',
        'expires_at',
        'cancelled_at',
        'auto_renew',
        'next_billing_at',
    ])
    return subscription


def _project_temporary_access(agreement, until):
    agreement.status = 'past_due_unknown'
    agreement.save(update_fields=['status', 'updated_at'])
    subscription, _ = Subscription.objects.select_for_update().get_or_create(
        user=agreement.user,
        defaults={'plan': agreement.plan, 'status': 'active'},
    )
    subscription.plan = agreement.plan
    subscription.status = 'active'
    subscription.expires_at = until
    subscription.auto_renew = False
    subscription.next_billing_at = None
    subscription.save(update_fields=[
        'plan',
        'status',
        'expires_at',
        'auto_renew',
        'next_billing_at',
    ])


def _decline_without_provider(order_id, failure_code, reason):
    with transaction.atomic():
        order = (
            PaymentOrder.objects.select_for_update()
            .select_related('agreement__user')
            .get(pk=order_id)
        )
        if order.status != 'created':
            return order
        agreement = BillingAgreement.objects.select_for_update().get(
            pk=order.agreement_id)
        token = _active_token(agreement, lock=True)
        order.status = 'declined'
        order.failure_code = failure_code
        order.save(update_fields=[
            'status', 'failure_code', 'updated_at'])
        project_free_entitlement(
            agreement,
            reason=reason,
            event_key=f'payment:{order.pk}:{failure_code}',
        )
        _queue_token_revocation(token)
        return order


def charge_order(order_id, *, client=None):
    if not recurring_charge_enabled():
        raise BillingFlowError(
            'recurring_charge_closed',
            '결제 설정을 확인한 뒤 다시 진행해 주세요.',
            status_code=503,
        )

    with transaction.atomic():
        order = (
            PaymentOrder.objects.select_for_update()
            .select_related('agreement__plan')
            .get(pk=order_id)
        )
        if order.status != 'created':
            return order
        agreement = order.agreement
        if order.cycle_sequence == 1 and not has_current_reconfirmation(
            agreement,
            order.due_date,
            order.amount_krw,
        ):
            missing_confirmation = True
        else:
            missing_confirmation = False
        if not missing_confirmation:
            token = _active_token(agreement, lock=True)
            if not token:
                missing_card = True
            else:
                missing_card = False
                billing_key = decrypt_billing_token(token)
                request_id = _provider_request_id(order)
                attempt = PaymentAttempt.objects.create(
                    order=order,
                    attempt_no=1,
                    provider_request_id=request_id,
                    started_at=timezone.now(),
                )
                order.status = 'submitted'
                order.save(update_fields=['status', 'updated_at'])

    if missing_confirmation:
        return _decline_without_provider(
            order_id,
            'RECONFIRMATION_MISSING',
            'reconfirmation_missing',
        )
    if missing_card:
        return _decline_without_provider(
            order_id,
            'PAYMENT_METHOD_MISSING',
            'payment_method_missing',
        )

    provider = client or KiccBillingClient()
    try:
        result = provider.charge(
            order,
            billing_key,
            request_id=request_id,
        )
    except (KiccIntegrityError, OSError):
        result = ChargeResult(
            kind='unknown',
            code='INTEGRITY_UNKNOWN',
        )

    with transaction.atomic():
        order = (
            PaymentOrder.objects.select_for_update()
            .select_related('agreement__plan', 'agreement__user')
            .get(pk=order_id)
        )
        if order.status != 'submitted':
            return order
        agreement = BillingAgreement.objects.select_for_update().get(
            pk=order.agreement_id)
        attempt = PaymentAttempt.objects.select_for_update().get(
            pk=attempt.pk)
        now = timezone.now()
        attempt.result_kind = result.kind
        attempt.provider_code = result.code
        attempt.response_hash = hashlib.sha256(
            (
                f'{result.kind}|{result.code}|'
                f'{result.provider_transaction_id}|{result.amount_krw}'
            ).encode(),
        ).hexdigest()
        attempt.completed_at = now

        approved = (
            result.kind == 'approved'
            and result.amount_krw == order.amount_krw
            and bool(result.provider_transaction_id)
        )
        if approved:
            attempt.provider_transaction_id = (
                result.provider_transaction_id)
            attempt.save(update_fields=[
                'result_kind',
                'provider_code',
                'provider_transaction_id',
                'response_hash',
                'completed_at',
            ])
            order.status = 'approved'
            order.failure_code = ''
            order.save(update_fields=[
                'status', 'failure_code', 'updated_at'])
            project_subscription(agreement)
            return order

        if result.kind == 'declined':
            attempt.save(update_fields=[
                'result_kind',
                'provider_code',
                'response_hash',
                'completed_at',
            ])
            order.status = 'declined'
            order.failure_code = result.code
            order.save(update_fields=[
                'status', 'failure_code', 'updated_at'])
            token = _active_token(agreement, lock=True)
            project_free_entitlement(
                agreement,
                reason='payment_declined',
                event_key=f'payment:{order.pk}:declined',
            )
            _queue_token_revocation(token)
            return order

        attempt.result_kind = 'unknown'
        attempt.save(update_fields=[
            'result_kind',
            'provider_code',
            'response_hash',
            'completed_at',
        ])
        order.status = 'unknown'
        order.failure_code = result.code or 'PAYMENT_UNKNOWN'
        order.unknown_since = now
        order.temporary_access_until = now + timedelta(hours=24)
        order.save(update_fields=[
            'status',
            'failure_code',
            'unknown_since',
            'temporary_access_until',
            'updated_at',
        ])
        _project_temporary_access(
            agreement, order.temporary_access_until)
        return order


def create_and_charge_due_agreement(
    agreement_id,
    due_date,
    *,
    client=None,
):
    order = create_due_order(agreement_id, due_date)
    return charge_order(order.pk, client=client)
