import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest import skipUnless
from unittest.mock import patch

from django.core.management import call_command
from django.db import close_old_connections, connection
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from inpa.accounts.models import User
from inpa.consultations.models import (
    ConsultationPilotAccess,
    ConsultationRecording,
    ConsultationRuntimeConfig,
    ConsultationSummaryRun,
)
from inpa.consultations.summary_service import request_summary
from inpa.consultations.summary_worker import _claim
from inpa.customers.consent_texts import (
    CONSULTATION_CONSENT_VERSIONS,
    CONSULTATION_SUMMARY_CONSENT_VERSION,
)
from inpa.customers.models import ConsentLog, Customer


@skipUnless(
    connection.vendor == 'postgresql',
    'PostgreSQL row-lock semantics required',
)
@override_settings(
    CONSULTATION_AI_SUMMARY_ENABLED=True,
    CONSULTATION_SUMMARY_PROMPT_VERSION='concurrency-v1',
    CONSULTATION_SUMMARY_ACTIVE_LIMIT=1,
)
class ConsultationSummaryConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        call_command('seed_billing')
        self.user = User.objects.create_user(
            email='summary-concurrency@example.com',
            password='strong-password',
        )
        self.customer = Customer.objects.create(
            owner=self.user,
            name='동시 요청 고객',
        )
        self.recording = self._recording(self.customer)
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
                doc_version=version,
            )

    def _recording(self, customer):
        recording_id = uuid.uuid4()
        return ConsultationRecording.objects.create(
            id=recording_id,
            owner=self.user,
            customer=customer,
            status=ConsultationRecording.STATUS_READY,
            storage_key=(
                f'consultation-recordings/{recording_id}/source'
            ),
            mime_type='audio/webm',
            duration_ms=60_000,
            ended_at=timezone.now(),
            expires_at=timezone.now() + timedelta(days=6),
        )

    @patch('inpa.consultations.summary_service.enqueue_summary_run')
    def test_two_servers_create_one_run_for_same_owner_customer_recording(
        self,
        _enqueue,
    ):
        barrier = threading.Barrier(2)

        def submit(index):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                recording = ConsultationRecording.objects.get(
                    pk=self.recording.pk,
                )
                user = User.objects.get(pk=self.user.pk)
                run, _ = request_summary(
                    recording=recording,
                    user=user,
                    idempotency_key=f'server-{index}',
                )
                return run.id
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            run_ids = list(pool.map(submit, (1, 2)))

        self.assertEqual(run_ids[0], run_ids[1])
        self.assertEqual(
            ConsultationSummaryRun.objects.filter(
                recording=self.recording,
            ).count(),
            1,
        )

    def test_shared_database_allows_one_active_summary_across_servers(self):
        other_customer = Customer.objects.create(
            owner=self.user,
            name='다른 동시 요청 고객',
        )
        other_recording = self._recording(other_customer)
        runs = [
            ConsultationSummaryRun.objects.create(
                recording=recording,
                idempotency_key=f'run-{index}',
                prompt_version='concurrency-v1',
                recording_consent_version='recording-v1',
                sensitive_consent_version='sensitive-v1',
                overseas_consent_version='overseas-v1',
            )
            for index, recording in enumerate(
                (self.recording, other_recording),
                start=1,
            )
        ]
        barrier = threading.Barrier(2)

        def claim(run_id):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                claimed, early = _claim(run_id)
                return bool(claimed), early.outcome if early else ''
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(claim, [run.id for run in runs]))

        self.assertEqual(sum(1 for claimed, _ in outcomes if claimed), 1)
        self.assertEqual(
            sum(1 for _, outcome in outcomes if outcome == 'capacity'),
            1,
        )
