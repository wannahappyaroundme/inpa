from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from inpa.accounts.models import User
from inpa.billing.models import UsageMeter
from inpa.consultations.models import (
    ConsultationCustomerBenefit,
    ConsultationPilotAccess,
    ConsultationRecording,
    ConsultationRuntimeConfig,
    ConsultationSummaryRun,
)
from inpa.consultations.quota import ai_cost_budget_available
from inpa.consultations.summary_service import (
    request_summary,
    settle_summary_failure,
    settle_summary_success,
)
from inpa.customers.consent_texts import (
    CONSULTATION_CONSENT_VERSIONS,
    CONSULTATION_SUMMARY_CONSENT_VERSION,
)
from inpa.customers.models import ConsentLog, Customer


@override_settings(
    CONSULTATION_AI_SUMMARY_ENABLED=True,
    CONSULTATION_SUMMARY_PROMPT_VERSION='prompt-test-v1',
)
class ConsultationQuotaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='quota-summary@example.com',
            password='strong-password',
        )
        call_command('seed_billing')
        self.customer = Customer.objects.create(
            owner=self.user,
            name='사용량 고객',
        )
        self.recording = ConsultationRecording.objects.create(
            owner=self.user,
            customer=self.customer,
            status=ConsultationRecording.STATUS_READY,
            storage_key=(
                'consultation-recordings/'
                '00000000-0000-4000-8000-000000000121/source'
            ),
            mime_type='audio/webm',
            duration_ms=3_600_000,
            ended_at=timezone.now(),
        )
        config = ConsultationRuntimeConfig.solo()
        config.ai_summary_enabled = True
        config.save(update_fields=['ai_summary_enabled', 'updated_at'])
        ConsultationPilotAccess.objects.create(
            user=self.user,
            recording_allowed=True,
            summary_allowed=True,
        )
        for scope, version in {
            **CONSULTATION_CONSENT_VERSIONS,
            ConsentLog.SCOPE_CONSULTATION_OVERSEAS_SUMMARY:
                CONSULTATION_SUMMARY_CONSENT_VERSION,
        }.items():
            ConsentLog.objects.create(
                customer=self.customer,
                scope=scope,
                subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
                purpose='상담 요약 테스트',
                doc_version=version,
            )

    def _usage(self, action):
        return UsageMeter.objects.get(
            user=self.user,
            action=action,
            year_month=UsageMeter.current_month(),
        ).count

    @patch('inpa.consultations.summary_service.enqueue_summary_run')
    def test_free_customer_benefit_and_usage_settle_only_on_success(
        self,
        enqueue,
    ):
        run, created = request_summary(
            recording=self.recording,
            user=self.user,
            idempotency_key='once',
        )
        self.assertTrue(created)
        self.assertEqual(run.success_count_reserved, 1)
        self.assertEqual(run.processing_minutes_reserved, 60)
        self.assertEqual(self._usage('consultation_summary'), 0)
        self.assertEqual(self._usage('consultation_minute'), 60)

        settle_summary_failure(run.id, provider_started=True)

        self.assertFalse(
            ConsultationCustomerBenefit.objects.filter(
                owner=self.user,
                customer=self.customer,
                status=ConsultationCustomerBenefit.STATUS_CONSUMED,
            ).exists(),
        )
        self.assertEqual(self._usage('consultation_summary'), 0)
        self.assertEqual(self._usage('consultation_minute'), 60)

    @patch('inpa.consultations.summary_service.enqueue_summary_run')
    def test_success_consumes_count_and_customer_benefit_once(self, enqueue):
        run, _ = request_summary(
            recording=self.recording,
            user=self.user,
            idempotency_key='success',
        )

        settle_summary_success(run.id)
        settle_summary_success(run.id)

        self.assertEqual(self._usage('consultation_summary'), 1)
        benefit = ConsultationCustomerBenefit.objects.get(
            owner=self.user,
            customer=self.customer,
        )
        self.assertEqual(
            benefit.status,
            ConsultationCustomerBenefit.STATUS_CONSUMED,
        )

    @patch('inpa.consultations.summary_service.enqueue_summary_run')
    def test_provider_not_started_releases_minute_reservation(self, enqueue):
        run, _ = request_summary(
            recording=self.recording,
            user=self.user,
            idempotency_key='not-started',
        )

        settle_summary_failure(run.id, provider_started=False)

        self.assertEqual(self._usage('consultation_minute'), 0)

    def test_daily_cost_limit_closes_new_ai_budget(self):
        config = ConsultationRuntimeConfig.solo()
        config.daily_ai_cost_limit_krw = 50_000
        config.monthly_ai_cost_limit_krw = 500_000
        config.save(update_fields=[
            'daily_ai_cost_limit_krw',
            'monthly_ai_cost_limit_krw',
            'updated_at',
        ])
        ConsultationSummaryRun.objects.create(
            recording=self.recording,
            status=ConsultationSummaryRun.STATUS_SUCCEEDED,
            idempotency_key='cost-cap',
            prompt_version='prompt-v1',
            recording_consent_version='recording-v1',
            sensitive_consent_version='sensitive-v1',
            overseas_consent_version='overseas-v1',
            estimated_cost_krw=50_000,
            completed_at=timezone.now(),
        )

        self.assertFalse(ai_cost_budget_available())
