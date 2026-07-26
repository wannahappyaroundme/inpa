from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from inpa.accounts.models import User
from inpa.billing.models import Plan
from inpa.consultations.models import (
    ConsultationRecording,
    ConsultationSummaryRun,
)
from inpa.customers.models import Customer, CustomerMemo


class ConsultationSummaryModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='summary-model@example.com',
            password='strong-password',
        )
        self.customer = Customer.objects.create(
            owner=self.user,
            name='요약 모델 고객',
        )
        self.recording = ConsultationRecording.objects.create(
            owner=self.user,
            customer=self.customer,
            status=ConsultationRecording.STATUS_READY,
            storage_key=(
                'consultation-recordings/'
                '00000000-0000-4000-8000-000000000111/source'
            ),
            mime_type='audio/webm',
            duration_ms=60_000,
            ended_at=timezone.now(),
        )

    def test_recording_has_only_one_summary_run_and_one_success_memo(self):
        first = ConsultationSummaryRun.objects.create(
            recording=self.recording,
            idempotency_key='key-a',
            status=ConsultationSummaryRun.STATUS_QUEUED,
            prompt_version='v1',
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ConsultationSummaryRun.objects.create(
                    recording=self.recording,
                    idempotency_key='key-b',
                    status=ConsultationSummaryRun.STATUS_QUEUED,
                    prompt_version='v1',
                )

        CustomerMemo.objects.create(
            owner=self.user,
            customer=self.customer,
            source=CustomerMemo.SOURCE_AI_SUMMARY,
            body='상담 핵심\n- 내용',
            occurred_at=self.recording.ended_at,
            summary_run=first,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CustomerMemo.objects.create(
                    owner=self.user,
                    customer=self.customer,
                    source=CustomerMemo.SOURCE_AI_SUMMARY,
                    body='중복',
                    occurred_at=self.recording.ended_at,
                    summary_run=first,
                )

    def test_seeded_limits_match_approved_safety_values(self):
        call_command('seed_billing')

        free = Plan.objects.get(code='free')
        plus = Plan.objects.get(code='plus')
        manager = Plan.objects.get(code='manager')
        super_plan = Plan.objects.get(code='super')
        self.assertEqual(free.limit_consultation_summary, 5)
        self.assertEqual(free.limit_consultation_minute, 150)
        self.assertEqual(plus.limit_consultation_summary, 30)
        self.assertEqual(manager.limit_consultation_minute, 900)
        self.assertEqual(super_plan.limit_consultation_summary, 100)
        self.assertEqual(super_plan.limit_consultation_minute, 3000)

    def test_seed_keeps_existing_admin_consultation_limits(self):
        plan = Plan.objects.create(
            code='free',
            display_name='운영 무료',
            limit_consultation_summary=7,
            limit_consultation_minute=210,
        )

        call_command('seed_billing')

        plan.refresh_from_db()
        self.assertEqual(plan.limit_consultation_summary, 7)
        self.assertEqual(plan.limit_consultation_minute, 210)
