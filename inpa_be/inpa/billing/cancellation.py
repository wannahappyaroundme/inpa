"""다음 결제를 멈추고 현재 이용 기간을 보존한다."""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .agreements import BillingFlowError
from .models import (
    BillingAgreement,
    PaymentMethodToken,
    Subscription,
)
from .recurring import (
    _kst_midnight,
    _queue_token_revocation,
    project_free_entitlement,
)


def _cancel_response(agreement):
    return {
        'state': 'canceled',
        'access_through':
            agreement.current_period_ends_on.isoformat(),
        'next_charge_date': None,
        'existing_data_available': True,
    }


def cancel_billing(user):
    with transaction.atomic():
        agreement = (
            BillingAgreement.objects.select_for_update()
            .select_related('user')
            .filter(user=user)
            .first()
        )
        if not agreement:
            raise BillingFlowError(
                'agreement_not_found',
                '현재 결제 정보를 확인해 주세요.',
                status_code=404,
            )
        if agreement.status == 'canceled':
            return _cancel_response(agreement)
        if agreement.status == 'free':
            raise BillingFlowError(
                'already_free',
                '현재 무료 요금제로 이용하고 있어요.',
                status_code=409,
            )

        now = timezone.now()
        token = (
            PaymentMethodToken.objects.select_for_update()
            .filter(agreement=agreement, status='active')
            .first()
        )
        agreement.status = 'canceled'
        agreement.canceled_at = now
        agreement.next_charge_date = None
        agreement.save(update_fields=[
            'status',
            'canceled_at',
            'next_charge_date',
            'updated_at',
        ])
        subscription, _ = (
            Subscription.objects.select_for_update().get_or_create(
                user=user,
                defaults={
                    'plan': agreement.plan,
                    'status': 'active',
                },
            )
        )
        subscription.plan = agreement.plan
        subscription.status = 'active'
        subscription.expires_at = _kst_midnight(
            agreement.current_period_ends_on + timedelta(days=1))
        subscription.cancelled_at = now
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
        _queue_token_revocation(token)
        return _cancel_response(agreement)


def finalize_canceled_agreement(agreement_id):
    with transaction.atomic():
        agreement = (
            BillingAgreement.objects.select_for_update()
            .select_related('user')
            .get(pk=agreement_id)
        )
        if agreement.status != 'canceled':
            return agreement
        if agreement.current_period_ends_on >= timezone.localdate():
            return agreement
        project_free_entitlement(
            agreement,
            reason='cancellation_expired',
            event_key=f'agreement:{agreement.pk}:cancellation-expired',
        )
        return agreement
