import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest import mock, skipUnless

from django.db import close_old_connections, connection
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User
from inpa.consultations.models import (
    ConsultationPilotAccess,
    ConsultationRecording,
    ConsultationRuntimeConfig,
)
from inpa.consultations.storage import MultipartSession
from inpa.customers.consent_texts import CONSULTATION_CONSENT_VERSIONS
from inpa.customers.models import ConsentLog, Customer
from inpa.customers.public_consent import PublicConsentView
from inpa.customers.tokens import make_consent_token


THREAD_TIMEOUT = 8


def _thread_call(callback):
    close_old_connections()
    try:
        return callback()
    finally:
        close_old_connections()


def _wait_for_peer_blocked_by(blocker_pid, *, action_name):
    deadline = time.monotonic() + THREAD_TIMEOUT
    while time.monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT pid, xact_start IS NOT NULL, pg_blocking_pids(pid)
                FROM pg_stat_activity
                WHERE datname = current_database()
                  AND pid <> pg_backend_pid()
                  AND %s = ANY(pg_blocking_pids(pid))
                ORDER BY pid
                """,
                [blocker_pid],
            )
            row = cursor.fetchone()
        if row is not None:
            return {
                'pid': row[0],
                'in_transaction': row[1],
                'blockers': row[2],
            }
        time.sleep(0.02)
    raise AssertionError(
        f'{action_name} did not wait on the withdrawal customer lock.',
    )


@skipUnless(
    connection.vendor == 'postgresql',
    'PostgreSQL row-lock semantics required',
)
@override_settings(
    CONSULTATION_RECORDING_ENABLED=True,
    CONSULTATION_RETENTION_HOURS=720,
)
class ConsultationDownloadConsentPostgresConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.user = User.objects.create_user(
            email='recording-download-race@example.invalid',
            password='inpaPass123!',
        )
        self.user.is_active = True
        self.user.save(update_fields=['is_active'])
        Profile.objects.create(
            user=self.user,
            email_verified_at=timezone.now(),
        )
        runtime = ConsultationRuntimeConfig.solo()
        runtime.recording_enabled = True
        runtime.save(update_fields=['recording_enabled'])
        ConsultationPilotAccess.objects.create(
            user=self.user,
            recording_allowed=True,
        )
        self.customer = Customer.objects.create(
            owner=self.user,
            name='철회 경합 고객',
        )
        for scope, version in CONSULTATION_CONSENT_VERSIONS.items():
            ConsentLog.objects.create(
                customer=self.customer,
                scope=scope,
                subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
                doc_version=version,
            )
        recording_id = uuid.uuid4()
        self.recording = ConsultationRecording.objects.create(
            id=recording_id,
            owner=self.user,
            customer=self.customer,
            status=ConsultationRecording.STATUS_READY,
            storage_key=f'consultation-recordings/{recording_id}/source',
            mime_type='audio/webm',
            verified_container='webm',
            uploaded_at=timezone.now(),
            expires_at=timezone.now() + timedelta(days=1),
        )
        token = make_consent_token(
            self.customer,
            scopes=[ConsentLog.SCOPE_CONSULTATION_RECORDING],
        )
        self.withdraw_url = f'/api/v1/c/{token}/'
        self.download_url = (
            f'/api/v1/customers/{self.customer.id}/recordings/'
            f'{self.recording.id}/download-url/'
        )
        self.play_url = (
            f'/api/v1/customers/{self.customer.id}/recordings/'
            f'{self.recording.id}/play-url/'
        )
        self.upload_url = (
            f'/api/v1/customers/{self.customer.id}/recordings/'
            'upload-sessions/'
        )

    def _withdrawal_first(self, action):
        withdrawal_locked = threading.Event()
        release_withdrawal = threading.Event()
        holder_pid = []
        original_apply = PublicConsentView._apply_revocations

        def hold_after_revocation(view, *args, **kwargs):
            result = original_apply(view, *args, **kwargs)
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_backend_pid()')
                holder_pid.append(cursor.fetchone()[0])
            withdrawal_locked.set()
            if not release_withdrawal.wait(timeout=THREAD_TIMEOUT):
                raise AssertionError('Withdrawal lock release timed out.')
            return result

        def withdraw():
            return APIClient().post(
                self.withdraw_url,
                {'revoked': [ConsentLog.SCOPE_CONSULTATION_RECORDING]},
                format='json',
            )

        with (
            mock.patch.object(
                PublicConsentView,
                '_apply_revocations',
                new=hold_after_revocation,
            ),
            mock.patch(
                'inpa.consultations.tasks.delete_customer_sources.delay',
            ),
            mock.patch(
                'inpa.consultations.tasks.cancel_customer_summaries.delay',
            ),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            withdrawal_future = executor.submit(_thread_call, withdraw)
            self.assertTrue(
                withdrawal_locked.wait(timeout=THREAD_TIMEOUT),
                'Withdrawal did not acquire the customer lock.',
            )
            action_future = executor.submit(_thread_call, action)
            try:
                blocked = _wait_for_peer_blocked_by(
                    holder_pid[0],
                    action_name=action.__name__,
                )
                self.assertTrue(blocked['in_transaction'])
                self.assertIn(holder_pid[0], blocked['blockers'])
            finally:
                release_withdrawal.set()
            return (
                withdrawal_future.result(timeout=THREAD_TIMEOUT),
                action_future.result(timeout=THREAD_TIMEOUT),
            )

    def test_withdrawal_first_blocks_download_then_returns_410_without_signing(self):
        withdrawal_locked = threading.Event()
        release_withdrawal = threading.Event()
        holder_pid = []
        original_apply = PublicConsentView._apply_revocations
        storage = mock.MagicMock()

        def hold_after_revocation(view, *args, **kwargs):
            result = original_apply(view, *args, **kwargs)
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_backend_pid()')
                holder_pid.append(cursor.fetchone()[0])
            withdrawal_locked.set()
            if not release_withdrawal.wait(timeout=THREAD_TIMEOUT):
                raise AssertionError('Withdrawal lock release timed out.')
            return result

        def withdraw():
            return APIClient().post(
                self.withdraw_url,
                {'revoked': [ConsentLog.SCOPE_CONSULTATION_RECORDING]},
                format='json',
            )

        def download():
            user = User.objects.get(pk=self.user.pk)
            client = APIClient()
            client.force_authenticate(user=user)
            return client.post(self.download_url)

        with (
            mock.patch.object(
                PublicConsentView,
                '_apply_revocations',
                new=hold_after_revocation,
            ),
            mock.patch(
                'inpa.consultations.services.get_recording_storage',
                return_value=storage,
            ),
            mock.patch(
                'inpa.consultations.tasks.delete_customer_sources.delay',
            ),
            mock.patch(
                'inpa.consultations.tasks.cancel_customer_summaries.delay',
            ),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            withdrawal_future = executor.submit(_thread_call, withdraw)
            self.assertTrue(
                withdrawal_locked.wait(timeout=THREAD_TIMEOUT),
                'Withdrawal did not acquire the customer lock.',
            )
            download_future = executor.submit(_thread_call, download)
            try:
                blocked = _wait_for_peer_blocked_by(
                    holder_pid[0],
                    action_name='download',
                )
                self.assertTrue(blocked['in_transaction'])
                self.assertIn(holder_pid[0], blocked['blockers'])
            finally:
                release_withdrawal.set()
            withdrawal_response = withdrawal_future.result(
                timeout=THREAD_TIMEOUT,
            )
            download_response = download_future.result(
                timeout=THREAD_TIMEOUT,
            )

        self.assertEqual(withdrawal_response.status_code, 200)
        self.assertEqual(download_response.status_code, 410)
        self.assertEqual(
            download_response.json()['code'],
            'recording_download_unavailable',
        )
        storage.presign_download.assert_not_called()

    def test_withdrawal_first_blocks_play_then_returns_410_without_signing(self):
        storage = mock.MagicMock()

        def play():
            user = User.objects.get(pk=self.user.pk)
            client = APIClient()
            client.force_authenticate(user=user)
            return client.post(self.play_url)

        with mock.patch(
            'inpa.consultations.services.get_recording_storage',
            return_value=storage,
        ):
            withdrawal_response, play_response = self._withdrawal_first(play)

        self.assertEqual(withdrawal_response.status_code, 200)
        self.assertEqual(play_response.status_code, 410)
        self.assertEqual(
            play_response.json()['code'],
            'recording_play_unavailable',
        )
        storage.presign_get.assert_not_called()

    def test_withdrawal_first_blocks_upload_then_returns_412_without_session(self):
        storage = mock.MagicMock()
        storage.create.side_effect = (
            lambda recording_id, _mime, **_retention: MultipartSession(
                key=f'consultation-recordings/{recording_id}/source',
                upload_id='upload-after-withdrawal',
            )
        )

        def upload():
            user = User.objects.get(pk=self.user.pk)
            client = APIClient()
            client.force_authenticate(user=user)
            return client.post(
                self.upload_url,
                {
                    'client_session_id': str(uuid.uuid4()),
                    'mime_type': 'audio/webm',
                    'notice_attested': True,
                    'notice_version':
                        'consultation-notice-v2-2026-07-28',
                },
                format='json',
            )

        with mock.patch(
            'inpa.consultations.services.get_recording_storage',
            return_value=storage,
        ):
            withdrawal_response, upload_response = self._withdrawal_first(
                upload,
            )

        self.assertEqual(withdrawal_response.status_code, 200)
        self.assertEqual(upload_response.status_code, 412)
        self.assertEqual(
            upload_response.json()['code'],
            'CONSULTATION_CONSENT_REQUIRED',
        )
        self.assertFalse(
            ConsultationRecording.objects.filter(
                status=ConsultationRecording.STATUS_UPLOADING,
            ).exists(),
        )
        storage.create.assert_not_called()

    def _create_uploading_recording(self):
        recording_id = uuid.uuid4()
        return ConsultationRecording.objects.create(
            id=recording_id,
            owner=self.user,
            customer=self.customer,
            status=ConsultationRecording.STATUS_UPLOADING,
            storage_key=f'consultation-recordings/{recording_id}/source',
            multipart_upload_id='upload-before-withdrawal',
            mime_type='audio/webm',
            expires_at=timezone.now() + timedelta(days=1),
        )

    def test_withdrawal_first_blocks_part_url_and_retires_upload(self):
        recording = self._create_uploading_recording()
        storage = mock.MagicMock()
        storage.presign_part.return_value = 'https://upload.example/part'
        part_url = (
            f'/api/v1/customers/{self.customer.id}/recordings/'
            f'{recording.id}/parts/1/'
        )

        def issue_part_url():
            user = User.objects.get(pk=self.user.pk)
            client = APIClient()
            client.force_authenticate(user=user)
            return client.post(part_url)

        with mock.patch(
            'inpa.consultations.services.get_recording_storage',
            return_value=storage,
        ):
            withdrawal_response, part_response = self._withdrawal_first(
                issue_part_url,
            )

        self.assertEqual(withdrawal_response.status_code, 200)
        self.assertEqual(part_response.status_code, 410)
        self.assertEqual(
            part_response.json()['code'],
            'recording_upload_unavailable',
        )
        storage.presign_part.assert_not_called()
        storage.abort.assert_called_once_with(
            recording.storage_key,
            recording.multipart_upload_id,
        )
        storage.delete.assert_called_once_with(recording.storage_key)
        recording.refresh_from_db()
        self.assertEqual(
            recording.status,
            ConsultationRecording.STATUS_DELETED,
        )

    def test_withdrawal_first_blocks_complete_and_retires_upload(self):
        recording = self._create_uploading_recording()
        storage = mock.MagicMock()
        complete_url = (
            f'/api/v1/customers/{self.customer.id}/recordings/'
            f'{recording.id}/complete-upload/'
        )

        def complete_upload():
            user = User.objects.get(pk=self.user.pk)
            client = APIClient()
            client.force_authenticate(user=user)
            return client.post(
                complete_url,
                {
                    'parts': [
                        {
                            'part_number': 1,
                            'etag': '"one"',
                            'byte_size': 1024,
                        },
                    ],
                },
                format='json',
            )

        with mock.patch(
            'inpa.consultations.services.get_recording_storage',
            return_value=storage,
        ):
            withdrawal_response, complete_response = self._withdrawal_first(
                complete_upload,
            )

        self.assertEqual(withdrawal_response.status_code, 200)
        self.assertEqual(complete_response.status_code, 410)
        self.assertEqual(
            complete_response.json()['code'],
            'recording_upload_unavailable',
        )
        storage.complete.assert_not_called()
        storage.abort.assert_called_once_with(
            recording.storage_key,
            recording.multipart_upload_id,
        )
        storage.delete.assert_called_once_with(recording.storage_key)
        recording.refresh_from_db()
        self.assertEqual(
            recording.status,
            ConsultationRecording.STATUS_DELETED,
        )
