from datetime import date, datetime, time, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from inpa.analytics.models import NorthStarEvent

from .agreements import confirm_first_charge
from .kicc import ChargeResult
from .legal_texts import FIRST_CHARGE_CONSENT_VERSION
from .models import (
    BillingAgreement,
    BillingNoticeEvent,
    PaymentAttempt,
    PaymentMethodToken,
    PaymentOrder,
    Plan,
    RuntimeConfig,
    Subscription,
)
from .payment_tokens import encrypt_billing_token
from .recurring import charge_order, create_due_order

User = get_user_model()
KST = ZoneInfo('Asia/Seoul')


def kst_midnight(value):
    return timezone.make_aware(
        datetime.combine(value, time.min),
        timezone=KST,
    )


@override_settings(
    BILLING_CARD_REGISTRATION_ENABLED=True,
    BILLING_RECURRING_CHARGE_ENABLED=True,
    BILLING_WEBHOOK_RECONCILIATION_ENABLED=True,
    FREE_TIER_UNLIMITED=False,
    KICC_MALL_ID='T0000001',
    KICC_CLIENT_SECRET='configured-secret',
    KICC_API_BASE_URL='https://testpgapi.easypay.co.kr',
    PAYMENT_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    PAYMENT_TOKEN_KEY_VERSION='v1',
)
class RecurringChargeTests(TestCase):
    def setUp(self):
        self.free = Plan.objects.create(
            code='free', display_name='무료', price_krw=0)
        self.plus = Plan.objects.create(
            code='plus', display_name='Plus', price_krw=19900)
        self.user = User.objects.create_user(
            email='charge@example.com',
            password='test-password',
        )
        self.due_date = date(2026, 7, 8)
        self.agreement = BillingAgreement.objects.create(
            user=self.user,
            plan=self.plus,
            status='trialing',
            billing_anchor_day=8,
            trial_duration_months=1,
            current_period_starts_on=self.due_date - timedelta(days=31),
            current_period_ends_on=self.due_date - timedelta(days=1),
            next_charge_date=self.due_date,
        )
        encrypted = encrypt_billing_token('provider-key')
        PaymentMethodToken.objects.create(
            agreement=self.agreement,
            encrypted_token=encrypted.ciphertext,
            key_version=encrypted.key_version,
            card_brand='신한카드',
            card_last4='7890',
            status='active',
        )
        Subscription.objects.filter(user=self.user).update(
            plan=self.plus,
            status='trial',
            expires_at=kst_midnight(self.due_date),
            auto_renew=True,
            next_billing_at=kst_midnight(self.due_date),
        )
        RuntimeConfig.objects.update_or_create(
            pk=1,
            defaults={
                'free_tier_unlimited': False,
                'billing_card_registration_enabled': True,
                'billing_recurring_charge_enabled': True,
                'billing_reconciliation_enabled': True,
            },
        )

    def _reconfirm(self):
        accepted_at = kst_midnight(
            self.due_date - timedelta(days=1)) + timedelta(hours=12)
        with mock.patch(
            'inpa.billing.agreements.timezone.now',
            return_value=accepted_at,
        ):
            confirm_first_charge(
                user=self.user,
                consent_version=FIRST_CHARGE_CONSENT_VERSION,
            )

    def test_missing_reconfirmation_never_calls_provider(self):
        order = create_due_order(self.agreement.id, self.due_date)
        provider = mock.Mock()

        with mock.patch(
            'inpa.billing.recurring.enqueue_token_revocation',
        ):
            with self.captureOnCommitCallbacks(execute=True):
                result = charge_order(order.id, client=provider)

        self.assertEqual(result.status, 'declined')
        self.assertEqual(
            result.failure_code, 'RECONFIRMATION_MISSING')
        provider.charge.assert_not_called()
        self.assertEqual(
            Subscription.objects.get(user=self.user).plan.code,
            'free',
        )
        self.assertTrue(BillingNoticeEvent.objects.filter(
            user=self.user,
            reason='reconfirmation_missing',
        ).exists())

    def test_approved_charge_projects_one_calendar_month(self):
        self._reconfirm()
        order = create_due_order(self.agreement.id, self.due_date)
        provider = mock.Mock()
        provider.charge.return_value = ChargeResult(
            kind='approved',
            provider_transaction_id='PG-APPROVED-1',
            code='0000',
            amount_krw=21890,
        )

        with self.captureOnCommitCallbacks(execute=True):
            result = charge_order(order.id, client=provider)

        self.assertEqual(result.status, 'approved')
        self.agreement.refresh_from_db()
        self.assertEqual(self.agreement.status, 'active')
        self.assertEqual(self.agreement.cycle_sequence, 1)
        self.assertEqual(
            self.agreement.current_period_starts_on,
            self.due_date,
        )
        self.assertEqual(
            self.agreement.next_charge_date,
            date(2026, 8, 8),
        )
        self.assertEqual(
            self.agreement.current_period_ends_on,
            date(2026, 8, 7),
        )
        subscription = Subscription.objects.get(user=self.user)
        self.assertEqual(subscription.plan, self.plus)
        self.assertEqual(subscription.status, 'active')
        self.assertEqual(
            subscription.expires_at,
            kst_midnight(date(2026, 8, 8)),
        )
        event = NorthStarEvent.objects.get(
            sender=self.user,
            event_type=NorthStarEvent.BILLING_CHARGE_SUCCEEDED,
        )
        self.assertEqual(event.payload, {
            'cycle_sequence': 1,
            'plan_code': 'plus',
        })

    def test_repeated_charge_call_uses_the_same_attempt(self):
        self._reconfirm()
        order = create_due_order(self.agreement.id, self.due_date)
        provider = mock.Mock()
        provider.charge.return_value = ChargeResult(
            kind='approved',
            provider_transaction_id='PG-APPROVED-2',
            code='0000',
            amount_krw=21890,
        )

        first = charge_order(order.id, client=provider)
        second = charge_order(order.id, client=provider)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(provider.charge.call_count, 1)
        self.assertEqual(PaymentOrder.objects.count(), 1)
        self.assertEqual(PaymentAttempt.objects.count(), 1)

    def test_unknown_charge_grants_only_finite_temporary_access(self):
        self._reconfirm()
        order = create_due_order(self.agreement.id, self.due_date)
        provider = mock.Mock()
        provider.charge.return_value = ChargeResult(
            kind='unknown',
            code='TRANSPORT_UNKNOWN',
        )

        before = timezone.now()
        with mock.patch(
            'inpa.billing.recurring._schedule_unknown_reconciliation',
        ) as schedule_reconciliation:
            with self.captureOnCommitCallbacks(execute=True):
                result = charge_order(order.id, client=provider)

        self.assertEqual(result.status, 'unknown')
        schedule_reconciliation.assert_called_once_with(order.id)
        self.assertGreaterEqual(
            result.temporary_access_until,
            before + timedelta(hours=23, minutes=59),
        )
        self.assertLessEqual(
            result.temporary_access_until,
            before + timedelta(hours=24, minutes=1),
        )
        self.agreement.refresh_from_db()
        self.assertEqual(
            self.agreement.status, 'past_due_unknown')
        self.assertTrue(NorthStarEvent.objects.filter(
            sender=self.user,
            event_type=NorthStarEvent.BILLING_CHARGE_UNKNOWN,
            payload={'age_bucket': 'under_5m'},
        ).exists())
        charge_order(order.id, client=provider)
        self.assertEqual(provider.charge.call_count, 1)

    def test_provider_decline_moves_to_free_and_revocation_queue(self):
        self._reconfirm()
        order = create_due_order(self.agreement.id, self.due_date)
        provider = mock.Mock()
        provider.charge.return_value = ChargeResult(
            kind='declined',
            code='CARD_DECLINED',
        )

        with mock.patch(
            'inpa.billing.recurring.enqueue_token_revocation',
        ):
            with self.captureOnCommitCallbacks(execute=True):
                result = charge_order(order.id, client=provider)

        self.assertEqual(result.status, 'declined')
        self.assertEqual(result.failure_code, 'CARD_DECLINED')
        self.agreement.refresh_from_db()
        self.assertEqual(self.agreement.status, 'free')
        self.assertEqual(
            Subscription.objects.get(user=self.user).plan,
            self.free,
        )
        self.assertEqual(
            PaymentMethodToken.objects.get(
                agreement=self.agreement).status,
            'revocation_pending',
        )
        event = NorthStarEvent.objects.get(
            sender=self.user,
            event_type=NorthStarEvent.BILLING_CHARGE_DECLINED,
        )
        self.assertEqual(event.payload, {
            'cycle_sequence': 1,
            'provider_code_enum': 'CARD_DECLINED',
        })
        self.assertTrue(NorthStarEvent.objects.filter(
            sender=self.user,
            event_type=NorthStarEvent.BILLING_FREE_TRANSITIONED,
            payload={'reason': 'payment_declined'},
        ).exists())
