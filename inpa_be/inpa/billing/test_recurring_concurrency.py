from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import threading
import unittest

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from .agreements import confirm_first_charge
from .kicc import ChargeResult
from .legal_texts import FIRST_CHARGE_CONSENT_VERSION
from .models import (
    BillingAgreement,
    PaymentAttempt,
    PaymentMethodToken,
    PaymentOrder,
    Plan,
    RuntimeConfig,
)
from .payment_tokens import encrypt_billing_token
from .recurring import create_and_charge_due_agreement

User = get_user_model()
POSTGRES_ONLY = unittest.skipUnless(
    connection.vendor == 'postgresql',
    'PostgreSQL row-lock test',
)


def _thread_call(callback):
    close_old_connections()
    try:
        return callback()
    finally:
        close_old_connections()


class CountingProvider:
    def __init__(self):
        self.calls = 0
        self._lock = threading.Lock()

    def charge(self, order, billing_key, *, request_id):
        with self._lock:
            self.calls += 1
        return ChargeResult(
            kind='approved',
            provider_transaction_id='PG-CONCURRENT-1',
            code='0000',
            amount_krw=order.amount_krw,
        )


@POSTGRES_ONLY
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
class RecurringChargePostgresConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        Plan.objects.create(
            code='free', display_name='무료', price_krw=0)
        plus = Plan.objects.create(
            code='plus', display_name='Plus', price_krw=19900)
        user = User.objects.create_user(
            email='charge-concurrent@example.com',
            password='test-password',
        )
        self.due_date = timezone.localdate() + timedelta(days=1)
        self.agreement = BillingAgreement.objects.create(
            user=user,
            plan=plus,
            status='trialing',
            billing_anchor_day=self.due_date.day,
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
        )
        confirm_first_charge(
            user=user,
            consent_version=FIRST_CHARGE_CONSENT_VERSION,
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

    def test_two_workers_create_one_order_and_one_provider_attempt(self):
        provider = CountingProvider()
        barrier = threading.Barrier(2)

        def run():
            barrier.wait(timeout=5)
            return create_and_charge_due_agreement(
                self.agreement.pk,
                self.due_date,
                client=provider,
            ).pk

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(
                _thread_call,
                (run, run),
            ))

        self.assertEqual(len(set(results)), 1)
        self.assertEqual(PaymentOrder.objects.count(), 1)
        self.assertEqual(PaymentAttempt.objects.count(), 1)
        self.assertEqual(provider.calls, 1)
