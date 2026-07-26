from datetime import date, timedelta
from unittest import mock

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from .kicc import ChargeResult, OperationResult
from .models import (
    BillingAgreement,
    PaymentAttempt,
    PaymentMethodToken,
    PaymentOrder,
    Plan,
    Subscription,
)
from .payment_tokens import encrypt_billing_token
from .reconciliation import (
    reconcile_unknown_order,
    revoke_payment_token,
)

User = get_user_model()


@override_settings(
    PAYMENT_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    PAYMENT_TOKEN_KEY_VERSION='v1',
)
class ReconciliationTests(TestCase):
    def setUp(self):
        self.free = Plan.objects.create(
            code='free', display_name='무료', price_krw=0)
        self.plus = Plan.objects.create(
            code='plus', display_name='Plus', price_krw=19900)
        self.user = User.objects.create_user(
            email='reconcile@example.com',
            password='test-password',
        )
        self.agreement = BillingAgreement.objects.create(
            user=self.user,
            plan=self.plus,
            status='past_due_unknown',
            billing_anchor_day=8,
            trial_duration_months=1,
            current_period_starts_on=date(2026, 6, 8),
            current_period_ends_on=date(2026, 7, 7),
            next_charge_date=date(2026, 7, 8),
        )
        encrypted = encrypt_billing_token('provider-key')
        self.token = PaymentMethodToken.objects.create(
            agreement=self.agreement,
            encrypted_token=encrypted.ciphertext,
            key_version=encrypted.key_version,
            card_brand='신한카드',
            card_last4='7890',
        )
        Subscription.objects.filter(user=self.user).update(
            plan=self.plus,
            status='active',
            expires_at=timezone.now() + timedelta(hours=24),
        )
        self.order = PaymentOrder.objects.create(
            agreement=self.agreement,
            cycle_sequence=1,
            merchant_order_id='INPA-P-RECONCILE-1',
            amount_krw=21890,
            due_date=date(2026, 7, 8),
            status='unknown',
            failure_code='TRANSPORT_UNKNOWN',
            unknown_since=timezone.now(),
            temporary_access_until=timezone.now() + timedelta(hours=24),
        )
        self.attempt = PaymentAttempt.objects.create(
            order=self.order,
            attempt_no=1,
            provider_request_id='INPA-PA-RECONCILE-1',
            result_kind='unknown',
            provider_code='TRANSPORT_UNKNOWN',
            started_at=timezone.now(),
            completed_at=timezone.now(),
        )

    def test_unknown_reconciliation_uses_query_and_never_recharges(self):
        provider = mock.Mock()
        provider.query.return_value = ChargeResult(
            kind='unknown', code='VTIM')

        result = reconcile_unknown_order(
            self.order.pk, client=provider)

        self.assertEqual(result.status, 'unknown')
        provider.query.assert_called_once()
        provider.charge.assert_not_called()

    def test_approval_within_twenty_four_hours_settles_original_order(self):
        provider = mock.Mock()
        provider.query.return_value = ChargeResult(
            kind='approved',
            provider_transaction_id='PG-RECONCILED-1',
            code='0000',
            amount_krw=21890,
        )

        result = reconcile_unknown_order(
            self.order.pk, client=provider)

        self.assertEqual(result.status, 'approved')
        provider.cancel.assert_not_called()
        self.agreement.refresh_from_db()
        self.assertEqual(self.agreement.status, 'active')
        self.assertEqual(self.agreement.cycle_sequence, 1)

    def test_approval_found_after_twenty_four_hours_is_canceled(self):
        PaymentOrder.objects.filter(pk=self.order.pk).update(
            unknown_since=timezone.now() - timedelta(hours=25))
        provider = mock.Mock()
        provider.query.return_value = ChargeResult(
            kind='approved',
            provider_transaction_id='PG-LATE-1',
            code='0000',
            amount_krw=21890,
        )
        provider.cancel.return_value = OperationResult(
            kind='approved',
            provider_transaction_id='PG-CANCEL-1',
            code='0000',
        )

        result = reconcile_unknown_order(
            self.order.pk, client=provider)

        self.assertEqual(result.status, 'canceled')
        provider.cancel.assert_called_once()
        self.assertEqual(
            Subscription.objects.get(user=self.user).plan,
            self.free,
        )

    def test_unknown_after_twenty_four_hours_ends_temporary_access(self):
        PaymentOrder.objects.filter(pk=self.order.pk).update(
            unknown_since=timezone.now() - timedelta(hours=25))
        provider = mock.Mock()
        provider.query.return_value = ChargeResult(
            kind='unknown', code='VTIM')

        result = reconcile_unknown_order(
            self.order.pk, client=provider)

        self.assertEqual(result.status, 'unknown')
        self.assertEqual(
            result.failure_code, 'RECONCILIATION_EXPIRED')
        self.assertEqual(
            Subscription.objects.get(user=self.user).plan,
            self.free,
        )

    def test_revoke_clears_ciphertext_only_after_provider_approval(self):
        provider = mock.Mock()
        provider.revoke_key.return_value = OperationResult(
            kind='approved', code='0000')

        result = revoke_payment_token(
            self.token.pk, client=provider)

        self.assertEqual(result.status, 'revoked')
        self.assertEqual(result.encrypted_token, '')
        provider.revoke_key.assert_called_once_with(
            'provider-key',
            request_id=f'INPA-BR-{self.token.pk}',
        )
