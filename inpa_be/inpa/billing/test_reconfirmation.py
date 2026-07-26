from datetime import date, datetime, time, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from .agreements import (
    confirm_first_charge,
    has_current_reconfirmation,
    reconfirmation_window,
    vat_inclusive_amount,
)
from .legal_texts import FIRST_CHARGE_CONSENT_VERSION
from .models import (
    BillingAgreement,
    PaymentMethodToken,
    Plan,
    RecurringPaymentConsent,
)
from .payment_tokens import encrypt_billing_token

User = get_user_model()
KST = ZoneInfo('Asia/Seoul')


def kst_midnight(value):
    return timezone.make_aware(
        datetime.combine(value, time.min),
        timezone=KST,
    )


@override_settings(
    PAYMENT_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    PAYMENT_TOKEN_KEY_VERSION='v1',
)
class ReconfirmationTests(APITestCase):
    def setUp(self):
        self.free = Plan.objects.create(
            code='free', display_name='무료', price_krw=0)
        self.plus = Plan.objects.create(
            code='plus', display_name='Plus', price_krw=19900)
        self.user = User.objects.create_user(
            email='reconfirm@example.com',
            password='test-password',
        )
        self.other = User.objects.create_user(
            email='reconfirm-other@example.com',
            password='test-password',
        )

    def _agreement(self, *, months=1, charge_date=None):
        charge_date = charge_date or timezone.localdate() + timedelta(days=3)
        agreement = BillingAgreement.objects.create(
            user=self.user,
            plan=self.plus,
            status='trialing',
            billing_anchor_day=charge_date.day,
            trial_duration_months=months,
            current_period_starts_on=charge_date - timedelta(days=30),
            current_period_ends_on=charge_date - timedelta(days=1),
            next_charge_date=charge_date,
        )
        encrypted = encrypt_billing_token('provider-key')
        PaymentMethodToken.objects.create(
            agreement=agreement,
            encrypted_token=encrypted.ciphertext,
            key_version=encrypted.key_version,
            card_brand='신한카드',
            card_last4='7890',
            status='active',
        )
        return agreement

    def test_one_month_window_opens_seven_days_before(self):
        agreement = self._agreement(
            months=1,
            charge_date=date(2027, 2, 5),
        )
        window = reconfirmation_window(agreement)
        self.assertEqual(
            window.opens_at,
            kst_midnight(date(2027, 1, 29)),
        )
        self.assertEqual(
            window.closes_at,
            kst_midnight(date(2027, 2, 5)),
        )

    def test_two_and_three_month_windows_open_thirty_days_before(self):
        for index, months in enumerate((2, 3), start=1):
            user = User.objects.create_user(
                email=f'reconfirm-{months}@example.com',
                password='test-password',
            )
            agreement = BillingAgreement.objects.create(
                user=user,
                plan=self.plus,
                status='trialing',
                billing_anchor_day=5,
                trial_duration_months=months,
                current_period_starts_on=date(2026, 12, 5),
                current_period_ends_on=date(2027, 2 + index, 4),
                next_charge_date=date(2027, 2 + index, 5),
            )
            self.assertEqual(
                reconfirmation_window(agreement).opens_at.date(),
                agreement.next_charge_date - timedelta(days=30),
            )

    def test_amount_change_invalidates_old_reconfirmation(self):
        agreement = self._agreement()
        now = kst_midnight(agreement.next_charge_date - timedelta(days=3))
        with mock.patch(
            'inpa.billing.agreements.timezone.now',
            return_value=now,
        ):
            confirm_first_charge(
                user=self.user,
                consent_version=FIRST_CHARGE_CONSENT_VERSION,
            )
        self.assertTrue(has_current_reconfirmation(
            agreement,
            agreement.next_charge_date,
            amount_krw=vat_inclusive_amount(self.plus.price_krw),
        ))
        self.assertFalse(has_current_reconfirmation(
            agreement,
            agreement.next_charge_date,
            amount_krw=43890,
        ))

    def test_reconfirm_endpoint_is_idempotent_and_owner_scoped(self):
        agreement = self._agreement()
        now = kst_midnight(agreement.next_charge_date - timedelta(days=2))
        self.client.force_authenticate(self.user)
        payload = {
            'first_charge_consent_version':
                FIRST_CHARGE_CONSENT_VERSION,
        }
        with mock.patch(
            'inpa.billing.agreements.timezone.now',
            return_value=now,
        ):
            first = self.client.post(
                '/api/v1/billing/reconfirm/',
                payload,
                format='json',
            )
            second = self.client.post(
                '/api/v1/billing/reconfirm/',
                payload,
                format='json',
            )
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(first.data['consent_id'], second.data['consent_id'])
        self.assertEqual(
            RecurringPaymentConsent.objects.filter(
                agreement=agreement,
                kind='first_charge',
            ).count(),
            1,
        )

        self.client.force_authenticate(self.other)
        response = self.client.post(
            '/api/v1/billing/reconfirm/',
            payload,
            format='json',
        )
        self.assertEqual(response.status_code, 404)

    def test_reconfirmation_waits_until_the_window_opens(self):
        agreement = self._agreement(
            charge_date=timezone.localdate() + timedelta(days=10))
        self.client.force_authenticate(self.user)
        response = self.client.post(
            '/api/v1/billing/reconfirm/',
            {
                'first_charge_consent_version':
                    FIRST_CHARGE_CONSENT_VERSION,
            },
            format='json',
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'reconfirmation_not_open')
