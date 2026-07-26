from datetime import date

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from .gates import (
    card_registration_enabled,
    reconciliation_enabled,
    recurring_charge_enabled,
)
from .models import (
    BillingAgreement,
    PaymentMethodToken,
    PaymentOrder,
    Plan,
    RuntimeConfig,
)

User = get_user_model()


class PaymentLedgerModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='ledger@example.com', password='test-password')
        self.plan = Plan.objects.create(
            code='plus', display_name='Plus', price_krw=19900)
        self.agreement = BillingAgreement.objects.create(
            user=self.user,
            plan=self.plan,
            status='trialing',
            billing_anchor_day=5,
            trial_duration_months=1,
            current_period_starts_on=date(2027, 1, 5),
            current_period_ends_on=date(2027, 2, 4),
            next_charge_date=date(2027, 2, 5),
        )

    def test_cycle_is_permanently_unique_inside_agreement(self):
        PaymentOrder.objects.create(
            agreement=self.agreement,
            cycle_sequence=1,
            merchant_order_id='INPA-1',
            amount_krw=21890,
            due_date=date(2027, 2, 5),
            status='created',
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PaymentOrder.objects.create(
                    agreement=self.agreement,
                    cycle_sequence=1,
                    merchant_order_id='INPA-2',
                    amount_krw=21890,
                    due_date=date(2027, 2, 5),
                    status='created',
                )

    def test_agreement_has_only_one_active_payment_token(self):
        PaymentMethodToken.objects.create(
            agreement=self.agreement,
            encrypted_token='ciphertext-1',
            key_version='v1',
            card_brand='신한',
            card_last4='1234',
            status='active',
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PaymentMethodToken.objects.create(
                    agreement=self.agreement,
                    encrypted_token='ciphertext-2',
                    key_version='v1',
                    status='active',
                )


@override_settings(
    BILLING_CARD_REGISTRATION_ENABLED=True,
    BILLING_RECURRING_CHARGE_ENABLED=True,
    BILLING_WEBHOOK_RECONCILIATION_ENABLED=True,
    FREE_TIER_UNLIMITED=False,
    KICC_MALL_ID='T0000001',
    KICC_CLIENT_SECRET='configured-secret',
    KICC_API_BASE_URL='https://testpgapi.easypay.co.kr',
    PAYMENT_TOKEN_ENCRYPTION_KEY='configured-key',
)
class PaymentGateTests(TestCase):
    def setUp(self):
        RuntimeConfig.objects.update_or_create(
            pk=1,
            defaults={
                'free_tier_unlimited': False,
                'billing_card_registration_enabled': True,
                'billing_recurring_charge_enabled': True,
                'billing_reconciliation_enabled': True,
            },
        )

    def test_all_dependencies_open_each_gate(self):
        self.assertTrue(card_registration_enabled())
        self.assertTrue(reconciliation_enabled())
        self.assertTrue(recurring_charge_enabled())

    @override_settings(
        BILLING_WEBHOOK_RECONCILIATION_ENABLED=False,
    )
    def test_charge_stays_closed_without_reconciliation(self):
        self.assertFalse(reconciliation_enabled())
        self.assertFalse(recurring_charge_enabled())

    @override_settings(FREE_TIER_UNLIMITED=True)
    def test_charge_stays_closed_while_beta_is_unlimited(self):
        self.assertFalse(recurring_charge_enabled())

    @override_settings(PAYMENT_TOKEN_ENCRYPTION_KEY='')
    def test_card_registration_stays_closed_without_token_key(self):
        self.assertFalse(card_registration_enabled())
        self.assertFalse(recurring_charge_enabled())

    def test_runtime_switch_can_close_each_gate(self):
        config = RuntimeConfig.solo()
        config.billing_recurring_charge_enabled = False
        config.save(update_fields=[
            'billing_recurring_charge_enabled', 'updated_at'])
        self.assertTrue(card_registration_enabled())
        self.assertFalse(recurring_charge_enabled())
