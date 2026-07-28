import json
import uuid
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User
from inpa.consultations.cleanup import (
    cleanup_expired_recordings,
    delete_recording_source,
    mark_source_deleted,
)
from inpa.consultations.models import (
    ConsultationRecording,
    ConsultationRuntimeConfig,
)
from inpa.consultations.storage import RecordingDeleteVerificationFailed
from inpa.customers.consent_texts import CONSULTATION_CONSENT_VERSIONS
from inpa.customers.models import ConsentLog, Customer
from inpa.customers.tokens import make_consent_token


class ConsultationRecordingCleanupTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='recording-cleanup@test.com',
            password='inpaPass123!',
        )
        self.user.is_active = True
        self.user.save(update_fields=['is_active'])
        Profile.objects.create(user=self.user)
        self.customer = Customer.objects.create(owner=self.user, name='김보장')
        self.expires_at = timezone.now()
        self.recording = ConsultationRecording.objects.create(
            owner=self.user,
            customer=self.customer,
            status=ConsultationRecording.STATUS_READY,
            storage_key=f'consultation-recordings/{uuid.uuid4()}/source',
            mime_type='audio/webm',
            expires_at=self.expires_at,
            checksum='sha256:secret-hash',
        )
        self.storage = mock.MagicMock()

    def test_cleanup_never_deletes_before_expiry_and_verifies_at_expiry(self):
        result_before = cleanup_expired_recordings(
            now=self.expires_at - timedelta(microseconds=1),
            limit=100,
            storage=self.storage,
        )
        self.storage.delete.assert_not_called()
        self.assertEqual(result_before['selected'], 0)

        result_at = cleanup_expired_recordings(
            now=self.expires_at,
            limit=100,
            storage=self.storage,
        )

        self.storage.delete.assert_called_once_with(self.recording.storage_key)
        self.recording.refresh_from_db()
        self.assertEqual(self.recording.status, ConsultationRecording.STATUS_DELETED)
        self.assertIsNone(self.recording.storage_key)
        self.assertEqual(self.recording.checksum, '')
        self.assertEqual(result_at['deleted'], 1)

    def test_three_repeated_verified_delete_failures_close_runtime_uploads(self):
        config = ConsultationRuntimeConfig.solo()
        config.recording_enabled = True
        config.save(update_fields=['recording_enabled'])
        self.storage.delete.side_effect = RecordingDeleteVerificationFailed(
            'still exists',
        )

        for index in range(3):
            result = cleanup_expired_recordings(
                now=self.expires_at + timedelta(hours=1, minutes=index),
                limit=100,
                storage=self.storage,
            )
            self.assertEqual(result['failed'], 1)

        config.refresh_from_db()
        self.recording.refresh_from_db()
        self.assertFalse(config.recording_enabled)
        self.assertEqual(self.recording.delete_attempts, 3)
        self.assertEqual(
            self.recording.last_delete_error_type,
            'RecordingDeleteVerificationFailed',
        )

    def test_late_failure_cannot_resurrect_concurrently_deleted_source(self):
        deleted_at = timezone.now()

        def delete_after_parallel_success(_key):
            mark_source_deleted(
                self.recording.id,
                reason='user_requested',
                now=deleted_at,
            )
            raise RuntimeError('slower overlapping delete failed')

        self.storage.delete.side_effect = delete_after_parallel_success

        outcome = delete_recording_source(
            self.recording.id,
            reason='user_requested',
            storage=self.storage,
            now=deleted_at,
        )

        self.assertEqual(outcome, 'deleted')
        self.recording.refresh_from_db()
        self.assertEqual(
            self.recording.status,
            ConsultationRecording.STATUS_DELETED,
        )
        self.assertIsNone(self.recording.storage_key)
        self.assertEqual(self.recording.delete_result, 'verified_absent')
        self.assertEqual(self.recording.delete_attempts, 0)

    @mock.patch('inpa.consultations.cleanup.get_recording_storage')
    def test_no_candidates_do_not_require_storage_credentials(self, storage_factory):
        ConsultationRecording.objects.all().delete()

        result = cleanup_expired_recordings(now=timezone.now(), limit=100)

        self.assertEqual(result['selected'], 0)
        storage_factory.assert_not_called()

    @mock.patch('inpa.consultations.tasks.delete_exact_sources.delay')
    def test_customer_delete_schedules_exact_random_keys_after_commit(self, delay):
        key = self.recording.storage_key
        upload_id = self.recording.multipart_upload_id

        with self.captureOnCommitCallbacks(execute=True):
            self.customer.delete()

        delay.assert_called_once_with(
            [{'storage_key': key, 'multipart_upload_id': upload_id}],
            reason='customer_deleted',
        )

    @mock.patch('inpa.consultations.tasks.delete_customer_sources.delay')
    def test_public_revocation_schedules_immediate_source_deletion(self, delay):
        for scope, version in CONSULTATION_CONSENT_VERSIONS.items():
            ConsentLog.objects.create(
                customer=self.customer,
                scope=scope,
                subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
                doc_version=version,
            )
        token = make_consent_token(
            self.customer,
            scopes=list(CONSULTATION_CONSENT_VERSIONS),
        )

        with self.captureOnCommitCallbacks(execute=True):
            response = APIClient().post(
                f'/api/v1/c/{token}/',
                {'revoked': [ConsentLog.SCOPE_CONSULTATION_RECORDING]},
                format='json',
            )

        self.assertEqual(response.status_code, 200)
        delay.assert_called_once_with(
            self.customer.id,
            reason='consent_revoked',
        )

    def test_cleanup_command_outputs_content_safe_counts(self):
        output = StringIO()

        with mock.patch(
            'inpa.consultations.cleanup.get_recording_storage',
            return_value=self.storage,
        ):
            call_command(
                'cleanup_consultation_recordings',
                now=self.expires_at.isoformat(),
                stdout=output,
            )

        result = json.loads(output.getvalue())
        self.assertEqual(result['deleted'], 1)
        self.assertNotIn(self.customer.name, output.getvalue())
        self.assertNotIn(self.user.email, output.getvalue())
