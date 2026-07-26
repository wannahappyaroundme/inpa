from datetime import date, timedelta
import hashlib
import uuid

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from inpa.customers.models import Customer, CustomerMemo

from .models import (
    BillingAgreement,
    BillingNoticeEvent,
    PaymentMethodToken,
    Plan,
    Subscription,
)
from .payment_tokens import encrypt_billing_token

User = get_user_model()


@override_settings(
    PAYMENT_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    PAYMENT_TOKEN_KEY_VERSION='v1',
)
class CancellationAndNoticeApiTests(APITestCase):
    def setUp(self):
        self.free = Plan.objects.create(
            code='free', display_name='무료', price_krw=0)
        self.plus = Plan.objects.create(
            code='plus', display_name='Plus', price_krw=19900)
        self.user = User.objects.create_user(
            email='cancel@example.com',
            password='test-password',
        )
        self.other = User.objects.create_user(
            email='cancel-other@example.com',
            password='test-password',
        )
        self.agreement = BillingAgreement.objects.create(
            user=self.user,
            plan=self.plus,
            status='active',
            billing_anchor_day=8,
            trial_duration_months=1,
            cycle_sequence=1,
            current_period_starts_on=date(2026, 7, 8),
            current_period_ends_on=date(2026, 8, 7),
            next_charge_date=date(2026, 8, 8),
        )
        encrypted = encrypt_billing_token('provider-key')
        PaymentMethodToken.objects.create(
            agreement=self.agreement,
            encrypted_token=encrypted.ciphertext,
            key_version=encrypted.key_version,
            card_brand='신한카드',
            card_last4='7890',
        )
        Subscription.objects.filter(user=self.user).update(
            plan=self.plus,
            status='active',
            expires_at=timezone.now() + timedelta(days=12),
            auto_renew=True,
            next_billing_at=timezone.now() + timedelta(days=12),
        )
        self.customer = Customer.objects.create(
            owner=self.user,
            name='김인파',
            mobile_phone_number='010-1000-2000',
        )
        CustomerMemo.objects.create(
            customer=self.customer,
            owner=self.user,
            source=CustomerMemo.SOURCE_MANUAL,
            body='기존 상담 메모',
        )
        CustomerMemo.objects.create(
            customer=self.customer,
            owner=self.user,
            source=CustomerMemo.SOURCE_AI_SUMMARY,
            body='기존 AI 요약 메모',
        )
        self.client.force_authenticate(self.user)

    def test_cancel_stops_future_charge_and_keeps_data_and_period(self):
        customer_hash_before = hashlib.sha256(
            (
                f'{self.customer.pk}|{self.customer.name}|'
                f'{self.customer.mobile_phone_number}'
            ).encode(),
        ).hexdigest()
        memo_hash_before = hashlib.sha256(
            '|'.join(
                CustomerMemo.objects.filter(
                    customer=self.customer,
                    owner=self.user,
                ).order_by('pk').values_list('body', flat=True)
            ).encode(),
        ).hexdigest()

        response = self.client.post('/api/v1/billing/cancel/')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['state'], 'canceled')
        self.assertEqual(response.data['access_through'], '2026-08-07')
        self.agreement.refresh_from_db()
        self.assertEqual(self.agreement.status, 'canceled')
        self.assertIsNone(self.agreement.next_charge_date)
        subscription = Subscription.objects.get(user=self.user)
        self.assertFalse(subscription.auto_renew)
        self.assertEqual(
            timezone.localdate(subscription.expires_at),
            date(2026, 8, 8),
        )
        self.assertTrue(Customer.objects.filter(
            pk=self.customer.pk,
            owner=self.user,
        ).exists())
        self.assertEqual(
            CustomerMemo.objects.filter(
                customer=self.customer,
                owner=self.user,
            ).count(),
            2,
        )
        self.customer.refresh_from_db()
        customer_hash_after = hashlib.sha256(
            (
                f'{self.customer.pk}|{self.customer.name}|'
                f'{self.customer.mobile_phone_number}'
            ).encode(),
        ).hexdigest()
        memo_hash_after = hashlib.sha256(
            '|'.join(
                CustomerMemo.objects.filter(
                    customer=self.customer,
                    owner=self.user,
                ).order_by('pk').values_list('body', flat=True)
            ).encode(),
        ).hexdigest()
        self.assertEqual(customer_hash_after, customer_hash_before)
        self.assertEqual(memo_hash_after, memo_hash_before)
        status_response = self.client.get('/api/v1/billing/status/')
        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(status_response.data['state'], 'canceled')
        self.assertEqual(
            status_response.data['access_through'],
            '2026-08-07',
        )

        repeated = self.client.post('/api/v1/billing/cancel/')
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.data, response.data)

    def test_other_user_cannot_cancel_the_agreement(self):
        self.client.force_authenticate(self.other)
        response = self.client.post('/api/v1/billing/cancel/')
        self.assertEqual(response.status_code, 404)
        self.agreement.refresh_from_db()
        self.assertEqual(self.agreement.status, 'active')

    def test_notice_is_rendered_once_across_devices(self):
        notice = BillingNoticeEvent.objects.create(
            user=self.user,
            event_key='payment:1:declined',
            notice_type='free_transition',
            reason='payment_declined',
        )
        first_device = str(uuid.uuid4())
        second_device = str(uuid.uuid4())

        first = self.client.post(
            '/api/v1/billing/notices/lease/',
            {'device_id': first_device},
            format='json',
        )
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(first.data['notice']['id'], notice.pk)
        self.assertTrue(first.data['notice']['existing_data_available'])

        second = self.client.post(
            '/api/v1/billing/notices/lease/',
            {'device_id': second_device},
            format='json',
        )
        self.assertEqual(second.status_code, 200)
        self.assertIsNone(second.data['notice'])

        wrong = self.client.post(
            f'/api/v1/billing/notices/{notice.pk}/rendered/',
            {'device_id': second_device},
            format='json',
        )
        self.assertEqual(wrong.status_code, 404)

        rendered = self.client.post(
            f'/api/v1/billing/notices/{notice.pk}/rendered/',
            {'device_id': first_device},
            format='json',
        )
        self.assertEqual(rendered.status_code, 200)

        after_render = self.client.post(
            '/api/v1/billing/notices/lease/',
            {'device_id': second_device},
            format='json',
        )
        self.assertIsNone(after_render.data['notice'])

        dismissed = self.client.post(
            f'/api/v1/billing/notices/{notice.pk}/dismiss/',
        )
        self.assertEqual(dismissed.status_code, 200)

    def test_expired_cancellation_creates_one_free_transition_notice(self):
        self.client.post('/api/v1/billing/cancel/')
        BillingAgreement.objects.filter(pk=self.agreement.pk).update(
            current_period_ends_on=timezone.localdate() - timedelta(days=1))

        call_command('run_billing_reconciliation')
        call_command('run_billing_reconciliation')

        self.agreement.refresh_from_db()
        self.assertEqual(self.agreement.status, 'free')
        self.assertEqual(
            BillingNoticeEvent.objects.filter(
                user=self.user,
                reason='cancellation_expired',
            ).count(),
            1,
        )
