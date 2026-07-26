from datetime import timedelta
from unittest import mock

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from .kicc import IssueKeyResult, RegistrationResult
from .legal_texts import INITIAL_BILLING_CONSENT_VERSION
from .models import (
    BillingAgreement,
    Coupon,
    CouponClaim,
    CouponRedemption,
    PaymentMethodToken,
    Plan,
    RuntimeConfig,
)

User = get_user_model()


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
    BACKEND_BASE_URL='https://api.example.com',
    FRONTEND_BASE_URL='https://app.example.com',
)
class CardRegistrationApiTests(APITestCase):
    def setUp(self):
        self.free = Plan.objects.create(
            code='free', display_name='무료', price_krw=0)
        self.plus = Plan.objects.create(
            code='plus', display_name='Plus', price_krw=19900)
        self.user = User.objects.create_user(
            email='register-card@example.com',
            password='test-password',
        )
        self.other = User.objects.create_user(
            email='other-card@example.com',
            password='test-password',
        )
        self.coupon = Coupon.objects.create(
            code='CARD-MONTH-1',
            plan=self.plus,
            coupon_kind='recurring_trial',
            duration_months=1,
            redeem_by=timezone.now() + timedelta(days=30),
            max_redemptions=10,
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
        self.client.force_authenticate(self.user)

    def _preflight(self):
        response = self.client.post(
            '/api/v1/billing/coupons/preflight/',
            {'code': self.coupon.code},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def test_preflight_holds_coupon_and_returns_exact_months(self):
        data = self._preflight()
        self.assertEqual(data['duration_months'], 1)
        self.assertEqual(data['plan_code'], 'plus')
        self.assertIn('claim_id', data)
        claim = CouponClaim.objects.get(pk=data['claim_id'])
        self.assertEqual(claim.user, self.user)
        self.assertEqual(claim.status, 'held')

    @mock.patch('inpa.billing.agreements.KiccBillingClient')
    def test_card_registration_requires_users_own_live_claim(
        self,
        kicc_class,
    ):
        claim_id = self._preflight()['claim_id']
        self.client.force_authenticate(self.other)
        response = self.client.post(
            '/api/v1/billing/card-registration/start/',
            {
                'claim_id': claim_id,
                'initial_consent_version':
                    INITIAL_BILLING_CONSENT_VERSION,
            },
            format='json',
        )
        self.assertEqual(response.status_code, 404)
        kicc_class.assert_not_called()

    @mock.patch('inpa.billing.agreements.KiccBillingClient')
    def test_complete_encrypts_key_and_redeems_coupon_once(
        self,
        kicc_class,
    ):
        claim_id = self._preflight()['claim_id']
        kicc = kicc_class.return_value
        kicc.start_registration.return_value = RegistrationResult(
            auth_page_url='https://testsp.easypay.co.kr/register')
        start = self.client.post(
            '/api/v1/billing/card-registration/start/',
            {
                'claim_id': claim_id,
                'initial_consent_version':
                    INITIAL_BILLING_CONSENT_VERSION,
            },
            format='json',
        ).data
        kicc.issue_key.return_value = IssueKeyResult(
            billing_key='plain-provider-billing-key',
            card_brand='신한카드',
            card_last4='7890',
        )

        response = self.client.post(
            '/api/v1/billing/card-registration/complete/',
            {
                'state': start['state'],
                'authorization_id': 'AUTH-1',
                'shop_order_no': start['shop_order_no'],
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['state'], 'trial')
        self.assertEqual(response.data['amount_krw'], 21890)
        self.assertEqual(response.data['card_label'], '신한카드 끝 7890')
        token = PaymentMethodToken.objects.get(status='active')
        self.assertNotIn(
            'plain-provider-billing-key', token.encrypted_token)
        self.assertTrue(CouponRedemption.objects.filter(
            coupon=self.coupon, user=self.user).exists())
        self.assertEqual(
            CouponClaim.objects.get(pk=claim_id).status, 'redeemed')

        repeated = self.client.post(
            '/api/v1/billing/card-registration/complete/',
            {
                'state': start['state'],
                'authorization_id': 'AUTH-1',
                'shop_order_no': start['shop_order_no'],
            },
            format='json',
        )
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(kicc.issue_key.call_count, 1)
        self.assertEqual(PaymentMethodToken.objects.count(), 1)

    @mock.patch('inpa.billing.agreements.KiccBillingClient')
    def test_expired_claim_never_issues_a_billing_key(
        self,
        kicc_class,
    ):
        claim_id = self._preflight()['claim_id']
        kicc_class.return_value.start_registration.return_value = (
            RegistrationResult(
                auth_page_url='https://testsp.easypay.co.kr/register')
        )
        start = self.client.post(
            '/api/v1/billing/card-registration/start/',
            {
                'claim_id': claim_id,
                'initial_consent_version':
                    INITIAL_BILLING_CONSENT_VERSION,
            },
            format='json',
        ).data
        CouponClaim.objects.filter(pk=claim_id).update(
            expires_at=timezone.now() - timedelta(seconds=1))

        response = self.client.post(
            '/api/v1/billing/card-registration/complete/',
            {
                'state': start['state'],
                'authorization_id': 'AUTH-LATE',
                'shop_order_no': start['shop_order_no'],
            },
            format='json',
        )
        self.assertEqual(response.status_code, 410)
        kicc_class.return_value.issue_key.assert_not_called()
        self.assertFalse(CouponRedemption.objects.exists())

    def test_status_never_exposes_token_or_provider_ids(self):
        response = self.client.get('/api/v1/billing/status/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['state'], 'free')
        self.assertTrue(response.data['existing_data_available'])
        encoded = str(response.data)
        self.assertNotIn('encrypted_token', encoded)
        self.assertNotIn('billing_key', encoded)

    @override_settings(BILLING_CARD_REGISTRATION_ENABLED=False)
    def test_preflight_stays_closed_until_environment_gate_is_open(self):
        response = self.client.post(
            '/api/v1/billing/coupons/preflight/',
            {'code': self.coupon.code},
            format='json',
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data['code'], 'billing_setup_required')
        self.assertIn('설정을 마치면', response.data['detail'])
