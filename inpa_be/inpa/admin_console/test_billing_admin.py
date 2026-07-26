import json
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from inpa.accounts.models import Profile
from inpa.billing.models import (
    BillingAdminAction,
    Coupon,
    Plan,
    RuntimeConfig,
)

User = get_user_model()


class AdminBillingApiTests(APITestCase):
    def setUp(self):
        self.free = Plan.objects.create(
            code='free', display_name='무료', price_krw=0)
        self.plus = Plan.objects.create(
            code='plus', display_name='Plus', price_krw=19900)
        self.admin = User.objects.create_user(
            email='billing-admin@example.com',
            password='test-password',
        )
        Profile.objects.create(user=self.admin, is_admin=True)
        self.normal = User.objects.create_user(
            email='billing-user@example.com',
            password='test-password',
        )
        Profile.objects.create(user=self.normal, is_admin=False)
        self.client.force_authenticate(self.admin)

    def test_overview_contains_operations_without_secrets(self):
        response = self.client.get('/api/v1/admin/billing/overview/')
        self.assertEqual(response.status_code, 200, response.data)
        encoded = json.dumps(response.data, ensure_ascii=False)
        for forbidden in (
            'encrypted_token',
            'billing_key',
            'card_number',
            'memo_body',
            'provider_transaction_id',
        ):
            self.assertNotIn(forbidden, encoded)
        self.assertIn('unknown_order_count', response.data['status'])
        self.assertEqual(
            response.data['status']['terminal_event_gap_count'],
            0,
        )
        self.assertIn('environment', response.data)

    def test_admin_can_create_one_to_three_month_coupon(self):
        response = self.client.post(
            '/api/v1/admin/billing/coupons/',
            {
                'plan_code': 'plus',
                'duration_months': 2,
                'redeem_by': (
                    timezone.now() + timedelta(days=90)
                ).isoformat(),
                'max_redemptions': 100,
                'note': '8월 설명회',
            },
            format='json',
            HTTP_IDEMPOTENCY_KEY='coupon-create-20260727-1',
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['duration_months'], 2)
        self.assertEqual(response.data['plan_code'], 'plus')
        coupon = Coupon.objects.get(pk=response.data['id'])
        self.assertEqual(coupon.coupon_kind, 'recurring_trial')
        self.assertEqual(
            BillingAdminAction.objects.filter(
                action='coupon_created',
                target_id=str(coupon.pk),
            ).count(),
            1,
        )

        repeated = self.client.post(
            '/api/v1/admin/billing/coupons/',
            {
                'plan_code': 'plus',
                'duration_months': 2,
                'redeem_by': (
                    timezone.now() + timedelta(days=90)
                ).isoformat(),
                'max_redemptions': 100,
            },
            format='json',
            HTTP_IDEMPOTENCY_KEY='coupon-create-20260727-1',
        )
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.data['id'], coupon.pk)
        self.assertEqual(Coupon.objects.count(), 1)

    def test_coupon_months_are_limited_to_one_through_three(self):
        response = self.client.post(
            '/api/v1/admin/billing/coupons/',
            {
                'plan_code': 'plus',
                'duration_months': 4,
                'redeem_by': (
                    timezone.now() + timedelta(days=90)
                ).isoformat(),
                'max_redemptions': 1,
            },
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    @override_settings(BILLING_CARD_REGISTRATION_ENABLED=False)
    def test_runtime_switch_cannot_open_past_environment_gate(self):
        RuntimeConfig.solo()
        response = self.client.patch(
            '/api/v1/admin/billing/settings/',
            {'billing_card_registration_enabled': True},
            format='json',
        )
        self.assertEqual(response.status_code, 409)
        self.assertFalse(
            RuntimeConfig.solo().billing_card_registration_enabled)

    @mock.patch(
        'inpa.admin_console.views.reconcile_unknown_order_task.delay')
    def test_reconcile_action_only_queues_the_existing_order(
        self,
        enqueue,
    ):
        from datetime import date
        from inpa.billing.models import (
            BillingAgreement,
            PaymentOrder,
        )
        agreement = BillingAgreement.objects.create(
            user=self.normal,
            plan=self.plus,
            status='past_due_unknown',
            billing_anchor_day=8,
            current_period_starts_on=date(2026, 6, 8),
            current_period_ends_on=date(2026, 7, 7),
            next_charge_date=date(2026, 7, 8),
        )
        order = PaymentOrder.objects.create(
            agreement=agreement,
            cycle_sequence=1,
            merchant_order_id='INPA-ADMIN-ORDER-1',
            amount_krw=21890,
            due_date=date(2026, 7, 8),
            status='unknown',
        )
        response = self.client.post(
            f'/api/v1/admin/billing/orders/{order.pk}/reconcile/',
            {},
            format='json',
            HTTP_IDEMPOTENCY_KEY='reconcile-1',
        )
        self.assertEqual(response.status_code, 202, response.data)
        enqueue.assert_called_once_with(order.pk)

    def test_non_admin_cannot_read_billing_operations(self):
        self.client.force_authenticate(self.normal)
        response = self.client.get('/api/v1/admin/billing/overview/')
        self.assertEqual(response.status_code, 403)
