from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from inpa.analytics.events import (
    billing_terminal_event_gap,
    log_billing_event,
)
from inpa.analytics.models import NorthStarEvent

from .models import (
    BillingAgreement,
    PaymentAttempt,
    PaymentOrder,
    Plan,
)

User = get_user_model()


class BillingObservabilityTests(TestCase):
    def setUp(self):
        self.plus = Plan.objects.create(
            code='plus',
            display_name='Plus',
            price_krw=19900,
        )
        self.user = User.objects.create_user(
            email='billing-observability@example.com',
            password='test-password',
        )

    def test_billing_event_keeps_only_content_free_allowlisted_fields(self):
        event = log_billing_event(
            NorthStarEvent.BILLING_CHARGE_DECLINED,
            sender=self.user,
            payload={
                'provider_code_enum': 'CARD_DECLINED',
                'cycle_sequence': 2,
                'email': self.user.email,
                'card_label': '신한카드 끝 7890',
                'memo': '고객과 나눈 상담 내용',
            },
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.payload, {
            'provider_code_enum': 'CARD_DECLINED',
            'cycle_sequence': 2,
        })
        encoded = str(event.payload)
        self.assertNotIn(self.user.email, encoded)
        self.assertNotIn('7890', encoded)
        self.assertNotIn('상담', encoded)

    def test_unknown_billing_event_is_not_stored(self):
        event = log_billing_event(
            'billing_unreviewed_event',
            sender=self.user,
            payload={'plan_code': 'plus'},
        )

        self.assertIsNone(event)
        self.assertFalse(NorthStarEvent.objects.exists())

    def test_terminal_event_gap_alerts_after_ten_minutes(self):
        agreement = BillingAgreement.objects.create(
            user=self.user,
            plan=self.plus,
            status='active',
            billing_anchor_day=5,
            trial_duration_months=1,
            current_period_starts_on=timezone.localdate(),
            current_period_ends_on=timezone.localdate(),
            next_charge_date=timezone.localdate(),
        )
        order = PaymentOrder.objects.create(
            agreement=agreement,
            cycle_sequence=1,
            merchant_order_id='INPA-OBSERVABILITY-1',
            amount_krw=21890,
            due_date=timezone.localdate(),
            status='submitted',
        )
        started_at = timezone.now() - timedelta(minutes=11)
        PaymentAttempt.objects.create(
            order=order,
            attempt_no=1,
            provider_request_id='INPA-OBSERVABILITY-ATTEMPT-1',
            started_at=started_at,
        )

        self.assertEqual(billing_terminal_event_gap(), 1)

        log_billing_event(
            NorthStarEvent.BILLING_CHARGE_UNKNOWN,
            sender=self.user,
            payload={'age_bucket': 'under_5m'},
        )
        self.assertEqual(billing_terminal_event_gap(), 0)
