from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User
from inpa.consultations.models import (
    ConsultationPilotAccess,
    ConsultationRecording,
    ConsultationRuntimeConfig,
    ConsultationSummaryRun,
)
from inpa.customers.consent_texts import (
    CONSULTATION_CONSENT_VERSIONS,
    CONSULTATION_SUMMARY_CONSENT_VERSION,
)
from inpa.customers.models import ConsentLog, Customer


@override_settings(
    CONSULTATION_AI_SUMMARY_ENABLED=True,
    CONSULTATION_SUMMARY_PROMPT_VERSION='api-prompt-v1',
)
class ConsultationSummaryApiTests(TestCase):
    def setUp(self):
        call_command('seed_billing')
        self.user = User.objects.create_user(
            email='summary-api@example.com',
            password='strong-password',
        )
        self.user.is_active = True
        self.user.save(update_fields=['is_active'])
        Profile.objects.create(user=self.user)
        self.customer = Customer.objects.create(
            owner=self.user,
            name='요약 고객',
        )
        self.other_customer = Customer.objects.create(
            owner=self.user,
            name='다른 고객',
        )
        self.recording = ConsultationRecording.objects.create(
            owner=self.user,
            customer=self.customer,
            status=ConsultationRecording.STATUS_READY,
            storage_key=(
                'consultation-recordings/'
                '00000000-0000-4000-8000-000000000501/source'
            ),
            mime_type='audio/webm',
            duration_ms=120_000,
            ended_at=timezone.now(),
            expires_at=timezone.now() + timedelta(days=6),
        )
        runtime = ConsultationRuntimeConfig.solo()
        runtime.ai_summary_enabled = True
        runtime.save(update_fields=['ai_summary_enabled', 'updated_at'])
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
                doc_version=version,
            )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = (
            f'/api/v1/customers/{self.customer.id}/recordings/'
            f'{self.recording.id}/summarize/'
        )

    @patch('inpa.consultations.summary_service.enqueue_summary_run')
    def test_double_click_returns_same_single_run_without_provider_fields(
        self,
        enqueue,
    ):
        with self.captureOnCommitCallbacks(execute=True):
            first = self.client.post(
                self.url,
                {},
                format='json',
                HTTP_IDEMPOTENCY_KEY='first-click',
            )
        second = self.client.post(
            self.url,
            {},
            format='json',
            HTTP_IDEMPOTENCY_KEY='second-click',
        )

        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data['id'], second.data['id'])
        self.assertEqual(ConsultationSummaryRun.objects.count(), 1)
        self.assertEqual(enqueue.call_count, 1)
        for private_field in (
            'stt_provider',
            'stt_job_id',
            'summary_provider',
            'summary_model',
            'input_tokens',
            'estimated_cost_krw',
        ):
            self.assertNotIn(private_field, first.data)

    @patch('inpa.consultations.summary_service.enqueue_summary_run')
    def test_existing_failed_run_cannot_be_regenerated(self, enqueue):
        with self.captureOnCommitCallbacks(execute=True):
            first = self.client.post(
                self.url,
                {},
                format='json',
                HTTP_IDEMPOTENCY_KEY='only-run',
            )
        run = ConsultationSummaryRun.objects.get(pk=first.data['id'])
        run.status = ConsultationSummaryRun.STATUS_FAILED
        run.save(update_fields=['status', 'updated_at'])

        again = self.client.post(
            self.url,
            {},
            format='json',
            HTTP_IDEMPOTENCY_KEY='new-key-cannot-regenerate',
        )

        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.data['id'], first.data['id'])
        self.assertEqual(again.data['status'], 'failed')
        self.assertEqual(ConsultationSummaryRun.objects.count(), 1)
        self.assertEqual(enqueue.call_count, 1)

    def test_summary_requires_idempotency_key(self):
        response = self.client.post(self.url, {}, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'IDEMPOTENCY_KEY_REQUIRED')

    def test_same_owner_wrong_customer_route_is_404(self):
        response = self.client.post(
            (
                f'/api/v1/customers/{self.other_customer.id}/recordings/'
                f'{self.recording.id}/summarize/'
            ),
            {},
            format='json',
            HTTP_IDEMPOTENCY_KEY='wrong-customer',
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(ConsultationSummaryRun.objects.count(), 0)

    def test_other_owner_cannot_access_recording_or_summary(self):
        other = User.objects.create_user(
            email='other-summary-owner@example.com',
            password='strong-password',
        )
        other.is_active = True
        other.save(update_fields=['is_active'])
        Profile.objects.create(user=other)
        client = APIClient()
        client.force_authenticate(other)

        response = client.post(
            self.url,
            {},
            format='json',
            HTTP_IDEMPOTENCY_KEY='cross-owner',
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(ConsultationSummaryRun.objects.count(), 0)
