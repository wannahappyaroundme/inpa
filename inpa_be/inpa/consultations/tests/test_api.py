import io
import uuid
import wave
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User
from inpa.consultations.models import (
    ConsultationPilotAccess,
    ConsultationRecording,
    ConsultationRuntimeConfig,
)
from inpa.consultations.cleanup import cleanup_expired_recordings
from inpa.consultations.services import (
    ConsultationServiceError,
    InvalidRecording,
    create_upload_session,
    inspect_audio,
)
from inpa.consultations.storage import MultipartSession
from inpa.customers.consent_texts import CONSULTATION_CONSENT_VERSIONS
from inpa.customers.models import ConsentLog, Customer


def _audio_wav_bytes(duration_seconds=1):
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b'\x00\x00' * 8000 * duration_seconds)
    return output.getvalue()


def _mock_av_container(format_name, codec):
    audio_stream = SimpleNamespace(
        type='audio',
        duration=None,
        time_base=None,
        codec_context=SimpleNamespace(name=codec),
    )
    container = SimpleNamespace(
        duration=1_000_000,
        format=SimpleNamespace(name=format_name),
        streams=[audio_stream],
    )
    context = mock.MagicMock()
    context.__enter__.return_value = container
    context.__exit__.return_value = False
    return context


@override_settings(
    CONSULTATION_RECORDING_ENABLED=True,
    CONSULTATION_MAX_DURATION_SECONDS=3600,
    CONSULTATION_MAX_BYTES=100 * 1024 * 1024,
    CONSULTATION_UPLOAD_PART_BYTES=8 * 1024 * 1024,
)
class ConsultationRecordingApiTests(TestCase):
    NOTICE_VERSION = 'consultation-notice-v2-2026-07-28'
    NOTICE_TEXT = (
        '본 상담은 상담 내용을 정확히 기록하고, 향후 상담 내용과 보험금 청구 관련 안내를 '
        '확인하는 참고자료로 활용하기 위해 녹음합니다. 원본은 인파에 30일 동안 보관된 뒤 '
        '자동 삭제됩니다. 녹음에 동의하시나요?'
    )
    NOTICE_TEXT_HASH = (
        'f316dff62e8c9628babccbcfb8d2ae1ddfc9a1572e72f58ac087d83fc45ec432'
    )

    def setUp(self):
        self.user = User.objects.create_user(
            email='recording-owner@test.com',
            password='inpaPass123!',
        )
        self.user.is_active = True
        self.user.save(update_fields=['is_active'])
        Profile.objects.create(user=self.user)
        self.customer = Customer.objects.create(owner=self.user, name='김보장')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

        runtime = ConsultationRuntimeConfig.solo()
        runtime.recording_enabled = True
        runtime.save(update_fields=['recording_enabled'])
        ConsultationPilotAccess.objects.create(
            user=self.user,
            recording_allowed=True,
        )

        self.storage = mock.MagicMock()
        self.storage.create.side_effect = (
            lambda recording_id, _mime, **_retention: MultipartSession(
                key=f'consultation-recordings/{recording_id}/source',
                upload_id='upload-1',
            )
        )
        self.storage.presign_part.return_value = 'https://upload.example/part'
        self.storage.presign_get.return_value = 'https://play.example/source'
        self.storage.presign_download.return_value = (
            'https://download.example/private-signed-value'
        )
        self.storage.head.return_value = {'ContentLength': 1024}
        self.storage.iter_object.return_value = iter([_audio_wav_bytes()])
        self.storage_patch = mock.patch(
            'inpa.consultations.services.get_recording_storage',
            return_value=self.storage,
        )
        self.storage_patch.start()
        self.addCleanup(self.storage_patch.stop)

    def _grant_recording_consents(self):
        for scope, version in CONSULTATION_CONSENT_VERSIONS.items():
            ConsentLog.objects.create(
                customer=self.customer,
                scope=scope,
                subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
                doc_version=version,
            )

    def _create_upload(self, **overrides):
        self._grant_recording_consents()
        payload = {
            'client_session_id': str(uuid.uuid4()),
            'mime_type': 'audio/webm;codecs=opus',
            'started_at': timezone.now().isoformat(),
            'notice_attested': True,
            'notice_version': self.NOTICE_VERSION,
        }
        payload.update(overrides)
        return self.client.post(
            f'/api/v1/customers/{self.customer.id}/recordings/upload-sessions/',
            payload,
            format='json',
        )

    def _post_expected_error(self, url, data=None, **kwargs):
        with self.assertLogs('django.request', level='WARNING'):
            return self.client.post(url, data, **kwargs)

    def _post_download_failure(self, url, expected_result):
        with (
            self.assertLogs(
                'inpa.consultations.views',
                level='INFO',
            ) as audit_logs,
            self.assertLogs('django.request', level='WARNING'),
        ):
            response = self.client.post(url)
        audit_output = ' '.join(audit_logs.output)
        self.assertIn(f'result={expected_result}', audit_output)
        return response, audit_output

    def test_upload_session_checks_customer_consent_before_planner_notice(self):
        response = self._post_expected_error(
            f'/api/v1/customers/{self.customer.id}/recordings/upload-sessions/',
            {
                'client_session_id': str(uuid.uuid4()),
                'mime_type': 'audio/webm',
                'started_at': timezone.now().isoformat(),
            },
            format='json',
        )

        self.assertEqual(response.status_code, 412)
        self.assertEqual(response.data['code'], 'CONSULTATION_CONSENT_REQUIRED')
        self.assertEqual(ConsultationRecording.objects.count(), 0)

    def test_upload_service_rechecks_latest_consent_before_storage_creation(self):
        self._grant_recording_consents()
        ConsentLog.objects.filter(
            customer=self.customer,
            scope=ConsentLog.SCOPE_CONSULTATION_RECORDING,
        ).update(revoked_at=timezone.now())

        with self.assertRaises(ConsultationServiceError) as captured:
            create_upload_session(
                owner=self.user,
                customer=self.customer,
                client_session_id=uuid.uuid4(),
                mime_type='audio/webm',
                started_at=timezone.now(),
                notice_attested=True,
                notice_version=self.NOTICE_VERSION,
            )

        self.assertEqual(
            captured.exception.code,
            'CONSULTATION_CONSENT_REQUIRED',
        )
        self.assertEqual(captured.exception.status_code, 412)
        self.assertEqual(ConsultationRecording.objects.count(), 0)
        self.storage.create.assert_not_called()

    def test_upload_session_requires_exact_planner_notice_attestation(self):
        self._grant_recording_consents()
        url = (
            f'/api/v1/customers/{self.customer.id}/recordings/upload-sessions/'
        )
        base_payload = {
            'client_session_id': str(uuid.uuid4()),
            'mime_type': 'audio/webm',
        }

        for notice_attested in (None, False):
            with self.subTest(notice_attested=notice_attested):
                payload = dict(base_payload)
                payload['client_session_id'] = str(uuid.uuid4())
                if notice_attested is not None:
                    payload['notice_attested'] = notice_attested
                response = self._post_expected_error(
                    url,
                    payload,
                    format='json',
                )
                self.assertEqual(response.status_code, 400, response.content)
                self.assertEqual(
                    response.data['code'],
                    'recording_notice_required',
                )

        stale = self._post_expected_error(
            url,
            {
                **base_payload,
                'client_session_id': str(uuid.uuid4()),
                'notice_attested': True,
                'notice_version': 'consultation-notice-v1-legacy',
            },
            format='json',
        )
        self.assertEqual(stale.status_code, 409, stale.content)
        self.assertEqual(stale.data['code'], 'recording_notice_changed')
        self.assertEqual(ConsultationRecording.objects.count(), 0)

    def test_capability_exposes_current_notice_and_effective_retention(self):
        response = self.client.get(
            f'/api/v1/customers/{self.customer.id}/recordings/capability/',
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data['retention_days'], 30)
        self.assertEqual(
            response.data['planner_notice_version'],
            self.NOTICE_VERSION,
        )
        self.assertEqual(
            response.data['planner_notice_text'],
            self.NOTICE_TEXT,
        )

    def test_current_v2_policy_rejects_any_retention_other_than_720_hours(self):
        capability_url = (
            f'/api/v1/customers/{self.customer.id}/recordings/capability/'
        )
        for configured_hours in (0, 1, 25, 719, 721, 999):
            with (
                self.subTest(configured_hours=configured_hours),
                self.settings(
                    CONSULTATION_RETENTION_HOURS=configured_hours,
                ),
                self.assertRaisesMessage(
                    ImproperlyConfigured,
                    'CONSULTATION_RETENTION_HOURS must be exactly 720',
                ),
            ):
                self.client.get(capability_url)

    @override_settings(CONSULTATION_RECORDING_ENABLED=False)
    def test_closed_environment_gate_cannot_be_opened_by_runtime_or_pilot(self):
        self._grant_recording_consents()

        response = self.client.post(
            f'/api/v1/customers/{self.customer.id}/recordings/upload-sessions/',
            {'mime_type': 'audio/webm'},
            format='json',
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['code'], 'CONSULTATION_RECORDING_CLOSED')

    def test_upload_session_returns_only_safe_upload_contract(self):
        response = self._create_upload()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], ConsultationRecording.STATUS_UPLOADING)
        self.assertEqual(response.data['part_bytes'], 8 * 1024 * 1024)
        self.assertEqual(response.data['max_part_number'], 13)
        self.assertNotIn('storage_key', response.data)
        self.assertNotIn('multipart_upload_id', response.data)

    def test_lost_response_retry_returns_same_session_across_server_requests(self):
        self._grant_recording_consents()
        client_session_id = str(uuid.uuid4())
        payload = {
            'client_session_id': client_session_id,
            'mime_type': 'audio/webm',
            'started_at': timezone.now().isoformat(),
            'notice_attested': True,
            'notice_version': self.NOTICE_VERSION,
        }

        first = self.client.post(
            f'/api/v1/customers/{self.customer.id}/recordings/upload-sessions/',
            payload,
            format='json',
        )
        second = self.client.post(
            f'/api/v1/customers/{self.customer.id}/recordings/upload-sessions/',
            payload,
            format='json',
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data['id'], first.data['id'])
        self.assertEqual(ConsultationRecording.objects.count(), 1)
        self.assertEqual(self.storage.create.call_count, 1)

    def test_retry_never_reuses_legacy_session_without_current_evidence(self):
        self._grant_recording_consents()
        client_session_id = uuid.uuid4()
        legacy = ConsultationRecording.objects.create(
            owner=self.user,
            customer=self.customer,
            client_session_id=client_session_id,
            status=ConsultationRecording.STATUS_UPLOADING,
            storage_key=f'consultation-recordings/{uuid.uuid4()}/source',
            multipart_upload_id='legacy-upload',
            mime_type='audio/webm',
        )

        response = self._post_expected_error(
            f'/api/v1/customers/{self.customer.id}/recordings/upload-sessions/',
            {
                'client_session_id': str(client_session_id),
                'mime_type': 'audio/webm',
                'notice_attested': True,
                'notice_version': self.NOTICE_VERSION,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(
            response.data['code'],
            'recording_session_policy_mismatch',
        )
        self.assertEqual(response.data.get('id'), None)
        self.assertEqual(ConsultationRecording.objects.get(), legacy)
        self.storage.create.assert_not_called()

    def test_retry_rejects_changed_exact_retention_snapshot(self):
        self._grant_recording_consents()
        client_session_id = str(uuid.uuid4())
        payload = {
            'client_session_id': client_session_id,
            'mime_type': 'audio/webm',
            'notice_attested': True,
            'notice_version': self.NOTICE_VERSION,
        }
        url = (
            f'/api/v1/customers/{self.customer.id}/recordings/upload-sessions/'
        )
        first = self.client.post(url, payload, format='json')

        with (
            self.settings(CONSULTATION_RETENTION_HOURS=719),
            self.assertRaisesMessage(
                ImproperlyConfigured,
                'CONSULTATION_RETENTION_HOURS must be exactly 720',
            ),
        ):
            self.client.post(url, payload, format='json')

        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(ConsultationRecording.objects.count(), 1)
        self.assertEqual(self.storage.create.call_count, 1)

    def test_part_url_rejects_number_above_server_limit(self):
        response = self._create_upload()
        recording_id = response.data['id']

        result = self.client.post(
            f'/api/v1/customers/{self.customer.id}/recordings/'
            f'{recording_id}/parts/14/',
            {},
            format='json',
        )

        self.assertEqual(result.status_code, 400)
        self.storage.presign_part.assert_not_called()

    def test_part_url_with_current_consent_uses_locked_upload_session(self):
        response = self._create_upload()
        recording = ConsultationRecording.objects.get(pk=response.data['id'])

        result = self.client.post(
            f'/api/v1/customers/{self.customer.id}/recordings/'
            f'{recording.id}/parts/1/',
            {},
            format='json',
        )

        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(result.data['url'], 'https://upload.example/part')
        self.assertEqual(result.data['expires_in_seconds'], 600)
        self.storage.presign_part.assert_called_once_with(
            recording.storage_key,
            recording.multipart_upload_id,
            1,
        )

    def test_part_url_rechecks_consent_and_retires_stale_upload(self):
        response = self._create_upload()
        recording_id = response.data['id']
        recording = ConsultationRecording.objects.get(pk=recording_id)
        ConsentLog.objects.filter(
            customer=self.customer,
            scope=ConsentLog.SCOPE_CONSULTATION_RECORDING,
        ).update(revoked_at=timezone.now())

        result = self._post_expected_error(
            f'/api/v1/customers/{self.customer.id}/recordings/'
            f'{recording_id}/parts/1/',
            {},
            format='json',
        )

        self.assertEqual(result.status_code, 410, result.content)
        self.assertEqual(result.data['code'], 'recording_upload_unavailable')
        self.storage.presign_part.assert_not_called()
        self.storage.abort.assert_called_once_with(
            recording.storage_key,
            recording.multipart_upload_id,
        )
        self.storage.delete.assert_called_once_with(recording.storage_key)
        recording.refresh_from_db()
        self.assertEqual(
            recording.status,
            ConsultationRecording.STATUS_DELETED,
        )
        self.assertIsNone(recording.storage_key)
        self.assertEqual(recording.multipart_upload_id, '')

    def test_revoked_part_url_stays_blocked_when_source_retirement_retries(self):
        response = self._create_upload()
        recording = ConsultationRecording.objects.get(pk=response.data['id'])
        ConsentLog.objects.filter(
            customer=self.customer,
            scope=ConsentLog.SCOPE_CONSULTATION_RECORDING,
        ).update(revoked_at=timezone.now())
        self.storage.abort.side_effect = RuntimeError('storage unavailable')

        result = self._post_expected_error(
            f'/api/v1/customers/{self.customer.id}/recordings/'
            f'{recording.id}/parts/1/',
            {},
            format='json',
        )

        self.assertEqual(result.status_code, 410, result.content)
        self.assertEqual(result.data['code'], 'recording_upload_unavailable')
        self.storage.presign_part.assert_not_called()
        self.storage.delete.assert_not_called()
        recording.refresh_from_db()
        self.assertEqual(
            recording.status,
            ConsultationRecording.STATUS_DELETING,
        )
        self.assertEqual(recording.delete_result, 'retry_required')
        self.assertEqual(recording.delete_attempts, 1)

    def test_uploading_source_cannot_issue_play_url(self):
        response = self._create_upload()
        recording_id = response.data['id']

        result = self.client.post(
            f'/api/v1/customers/{self.customer.id}/recordings/'
            f'{recording_id}/play-url/',
        )

        self.assertEqual(result.status_code, 409)
        self.storage.presign_get.assert_not_called()

    def test_play_url_requires_current_customer_consent_without_signing(self):
        self._grant_recording_consents()
        recording = ConsultationRecording.objects.create(
            owner=self.user,
            customer=self.customer,
            status=ConsultationRecording.STATUS_READY,
            storage_key=f'consultation-recordings/{uuid.uuid4()}/source',
            mime_type='audio/webm',
            uploaded_at=timezone.now(),
            expires_at=timezone.now() + timedelta(days=1),
        )
        ConsentLog.objects.filter(
            customer=self.customer,
            scope=ConsentLog.SCOPE_CONSULTATION_RECORDING,
        ).update(revoked_at=timezone.now())

        response = self._post_expected_error(
            f'/api/v1/customers/{self.customer.id}/recordings/'
            f'{recording.id}/play-url/',
        )

        self.assertEqual(response.status_code, 410, response.content)
        self.assertEqual(response.data['code'], 'recording_play_unavailable')
        self.storage.presign_get.assert_not_called()

    def test_play_uses_shared_customer_lock_and_recording_row_lock(self):
        self._grant_recording_consents()
        recording = ConsultationRecording.objects.create(
            owner=self.user,
            customer=self.customer,
            status=ConsultationRecording.STATUS_READY,
            storage_key=f'consultation-recordings/{uuid.uuid4()}/source',
            mime_type='audio/webm',
            uploaded_at=timezone.now(),
            expires_at=timezone.now() + timedelta(days=1),
        )

        with (
            mock.patch(
                'inpa.customers.consent_texts.Customer.objects.select_for_update',
                wraps=Customer.objects.select_for_update,
            ) as customer_lock,
            mock.patch.object(
                ConsultationRecording.objects,
                'select_for_update',
                wraps=ConsultationRecording.objects.select_for_update,
            ) as recording_lock,
        ):
            response = self.client.post(
                f'/api/v1/customers/{self.customer.id}/recordings/'
                f'{recording.id}/play-url/',
            )

        self.assertEqual(response.status_code, 200, response.content)
        customer_lock.assert_called_once_with()
        recording_lock.assert_called_once_with()

    @mock.patch(
        'inpa.consultations.services.inspect_audio',
        return_value=SimpleNamespace(
            byte_size=1024,
            duration_ms=60_000,
            codec='opus',
            checksum='sha256:abc',
            container='webm',
        ),
    )
    def test_complete_is_idempotent_and_validates_server_object(self, inspect_mock):
        response = self._create_upload()
        recording_id = response.data['id']
        complete_url = (
            f'/api/v1/customers/{self.customer.id}/recordings/'
            f'{recording_id}/complete-upload/'
        )
        payload = {
            'ended_at': timezone.now().isoformat(),
            'parts': [
                {'part_number': 1, 'etag': '"one"', 'byte_size': 1024},
            ],
        }

        first = self.client.post(complete_url, payload, format='json')
        second = self.client.post(complete_url, payload, format='json')

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data['id'], first.data['id'])
        self.assertEqual(self.storage.complete.call_count, 1)
        self.storage.head.assert_called_once()
        inspect_mock.assert_called_once()

    def test_complete_rechecks_consent_and_retires_stale_upload(self):
        response = self._create_upload()
        recording_id = response.data['id']
        recording = ConsultationRecording.objects.get(pk=recording_id)
        ConsentLog.objects.filter(
            customer=self.customer,
            scope=ConsentLog.SCOPE_CONSULTATION_RECORDING,
        ).update(revoked_at=timezone.now())

        result = self._post_expected_error(
            f'/api/v1/customers/{self.customer.id}/recordings/'
            f'{recording_id}/complete-upload/',
            {
                'parts': [
                    {'part_number': 1, 'etag': '"one"', 'byte_size': 1024},
                ],
            },
            format='json',
        )

        self.assertEqual(result.status_code, 410, result.content)
        self.assertEqual(result.data['code'], 'recording_upload_unavailable')
        self.storage.complete.assert_not_called()
        self.storage.head.assert_not_called()
        self.storage.abort.assert_called_once_with(
            recording.storage_key,
            recording.multipart_upload_id,
        )
        self.storage.delete.assert_called_once_with(recording.storage_key)
        recording.refresh_from_db()
        self.assertEqual(
            recording.status,
            ConsultationRecording.STATUS_DELETED,
        )
        self.assertIsNone(recording.storage_key)
        self.assertEqual(recording.multipart_upload_id, '')

    @mock.patch(
        'inpa.consultations.services.inspect_audio',
        return_value=SimpleNamespace(
            byte_size=1024,
            duration_ms=60_000,
            codec='opus',
            checksum='sha256:abc',
            container='webm',
        ),
    )
    def test_new_recording_keeps_notice_evidence_and_exact_thirty_day_expiry(
        self,
        _inspect_mock,
    ):
        response = self._create_upload(
            notice_text='클라이언트가 보낸 저장 금지 문구',
        )
        recording_id = response.data['id']

        completed = self.client.post(
            f'/api/v1/customers/{self.customer.id}/recordings/'
            f'{recording_id}/complete-upload/',
            {
                'parts': [
                    {'part_number': 1, 'etag': '"one"', 'byte_size': 1024},
                ],
            },
            format='json',
        )

        self.assertEqual(completed.status_code, 200, completed.content)
        recording = ConsultationRecording.objects.get(pk=recording_id)
        self.assertEqual(recording.notice_version, self.NOTICE_VERSION)
        self.assertIsNotNone(recording.notice_attested_at)
        self.assertEqual(recording.notice_text_hash, self.NOTICE_TEXT_HASH)
        self.assertEqual(recording.retention_hours_snapshot, 720)
        self.assertEqual(recording.retention_days_snapshot, 30)
        self.assertEqual(recording.retention_policy_version, 'v2-30d')
        self.storage.create.assert_called_once_with(
            recording.id,
            'audio/webm;codecs=opus',
            retention_hours=720,
            retention_days=30,
            retention_policy_version='v2-30d',
        )
        self.assertEqual(
            recording.expires_at - recording.ready_at,
            timedelta(days=30),
        )
        self.assertEqual(recording.verified_container, 'webm')

    @mock.patch(
        'inpa.consultations.services.inspect_audio',
        return_value=SimpleNamespace(
            byte_size=1024,
            duration_ms=60_000,
            codec='aac',
            checksum='sha256:mp4',
            container='mp4',
        ),
    )
    def test_complete_rejects_declared_webm_when_actual_container_is_mp4(
        self,
        _inspect_mock,
    ):
        upload = self._create_upload(mime_type='audio/webm')

        completed = self._post_expected_error(
            (
                f'/api/v1/customers/{self.customer.id}/recordings/'
                f'{upload.data["id"]}/complete-upload/'
            ),
            {
                'parts': [
                    {'part_number': 1, 'etag': '"one"', 'byte_size': 1024},
                ],
            },
            format='json',
        )

        self.assertEqual(completed.status_code, 400, completed.content)
        self.assertEqual(
            completed.data['code'],
            'RECORDING_CONTAINER_MISMATCH',
        )
        recording = ConsultationRecording.objects.get(pk=upload.data['id'])
        self.assertEqual(recording.status, ConsultationRecording.STATUS_DELETED)
        self.assertIsNone(recording.storage_key)
        self.assertEqual(recording.verified_container, '')
        self.storage.delete.assert_called_once()

    @mock.patch(
        'inpa.consultations.services.inspect_audio',
        return_value=SimpleNamespace(
            byte_size=1024,
            duration_ms=60_000,
            codec='aac',
            checksum='sha256:mp4',
            container='mp4',
        ),
    )
    def test_complete_accepts_matching_mp4_and_persists_verified_container(
        self,
        _inspect_mock,
    ):
        upload = self._create_upload(mime_type='audio/mp4')

        completed = self.client.post(
            (
                f'/api/v1/customers/{self.customer.id}/recordings/'
                f'{upload.data["id"]}/complete-upload/'
            ),
            {
                'parts': [
                    {'part_number': 1, 'etag': '"one"', 'byte_size': 1024},
                ],
            },
            format='json',
        )

        self.assertEqual(completed.status_code, 200, completed.content)
        recording = ConsultationRecording.objects.get(pk=upload.data['id'])
        self.assertEqual(recording.status, ConsultationRecording.STATUS_READY)
        self.assertEqual(recording.codec, 'aac')
        self.assertEqual(recording.verified_container, 'mp4')

    def test_play_and_delete_foreign_owner_are_hidden_as_404(self):
        recording = ConsultationRecording.objects.create(
            owner=self.user,
            customer=self.customer,
            status=ConsultationRecording.STATUS_READY,
            storage_key=f'consultation-recordings/{uuid.uuid4()}/source',
            mime_type='audio/webm',
            expires_at=timezone.now() + timedelta(days=1),
        )
        other = User.objects.create_user(
            email='recording-other@test.com',
            password='inpaPass123!',
        )
        other.is_active = True
        other.save(update_fields=['is_active'])
        Profile.objects.create(user=other)
        self.client.force_authenticate(other)

        play = self.client.post(
            f'/api/v1/customers/{self.customer.id}/recordings/'
            f'{recording.id}/play-url/',
        )
        delete = self.client.delete(
            f'/api/v1/customers/{self.customer.id}/recordings/'
            f'{recording.id}/source/',
        )

        self.assertEqual(play.status_code, 404)
        self.assertEqual(delete.status_code, 404)

    def test_same_owner_cannot_cross_wire_recording_to_another_customer(self):
        other_customer = Customer.objects.create(
            owner=self.user,
            name='이고객',
        )
        recording = ConsultationRecording.objects.create(
            owner=self.user,
            customer=self.customer,
            status=ConsultationRecording.STATUS_UPLOADING,
            storage_key=f'consultation-recordings/{uuid.uuid4()}/source',
            multipart_upload_id='upload-1',
            mime_type='audio/webm',
        )

        part = self.client.post(
            f'/api/v1/customers/{other_customer.id}/recordings/'
            f'{recording.id}/parts/1/',
        )
        complete = self.client.post(
            f'/api/v1/customers/{other_customer.id}/recordings/'
            f'{recording.id}/complete-upload/',
            {
                'parts': [
                    {'part_number': 1, 'etag': '"one"', 'byte_size': 1024},
                ],
            },
            format='json',
        )

        self.assertEqual(part.status_code, 404)
        self.assertEqual(complete.status_code, 404)
        self.storage.presign_part.assert_not_called()
        self.storage.complete.assert_not_called()

    def test_ordinary_admin_cannot_part_or_complete_foreign_upload(self):
        recording = ConsultationRecording.objects.create(
            owner=self.user,
            customer=self.customer,
            status=ConsultationRecording.STATUS_UPLOADING,
            storage_key=f'consultation-recordings/{uuid.uuid4()}/source',
            multipart_upload_id='upload-1',
            mime_type='audio/webm',
        )
        admin = User.objects.create_user(
            email='recording-upload-admin@test.com',
            password='inpaPass123!',
        )
        admin.is_active = True
        admin.save(update_fields=['is_active'])
        Profile.objects.create(user=admin, is_admin=True)
        self.client.force_authenticate(admin)

        part = self.client.post(
            f'/api/v1/customers/{self.customer.id}/recordings/'
            f'{recording.id}/parts/1/',
        )
        complete = self.client.post(
            f'/api/v1/customers/{self.customer.id}/recordings/'
            f'{recording.id}/complete-upload/',
            {
                'parts': [
                    {'part_number': 1, 'etag': '"one"', 'byte_size': 1024},
                ],
            },
            format='json',
        )

        self.assertEqual(part.status_code, 404)
        self.assertEqual(complete.status_code, 404)
        self.storage.presign_part.assert_not_called()
        self.storage.complete.assert_not_called()

    def test_ordinary_admin_cannot_start_foreign_upload_session(self):
        self._grant_recording_consents()
        admin = User.objects.create_user(
            email='recording-start-admin@test.com',
            password='inpaPass123!',
        )
        admin.is_active = True
        admin.save(update_fields=['is_active'])
        Profile.objects.create(user=admin, is_admin=True)
        self.client.force_authenticate(admin)

        response = self.client.post(
            f'/api/v1/customers/{self.customer.id}/recordings/upload-sessions/',
            {
                'client_session_id': str(uuid.uuid4()),
                'mime_type': 'audio/webm;codecs=opus',
                'started_at': timezone.now().isoformat(),
                'notice_attested': True,
                'notice_version': self.NOTICE_VERSION,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 404)
        self.storage.create.assert_not_called()
        self.assertFalse(ConsultationRecording.objects.exists())

    def test_ordinary_admin_cannot_delete_foreign_source(self):
        recording = ConsultationRecording.objects.create(
            owner=self.user,
            customer=self.customer,
            status=ConsultationRecording.STATUS_READY,
            storage_key=f'consultation-recordings/{uuid.uuid4()}/source',
            mime_type='audio/webm',
            expires_at=timezone.now() + timedelta(days=1),
        )
        admin = User.objects.create_user(
            email='recording-delete-admin@test.com',
            password='inpaPass123!',
        )
        admin.is_active = True
        admin.save(update_fields=['is_active'])
        Profile.objects.create(user=admin, is_admin=True)
        self.client.force_authenticate(admin)

        response = self.client.delete(
            f'/api/v1/customers/{self.customer.id}/recordings/'
            f'{recording.id}/source/',
        )

        self.assertEqual(response.status_code, 404)
        self.storage.abort.assert_not_called()
        self.storage.delete.assert_not_called()
        recording.refresh_from_db()
        self.assertEqual(recording.status, ConsultationRecording.STATUS_READY)

    def test_list_restores_ready_and_deleted_metadata_without_private_fields(self):
        ConsultationRecording.objects.create(
            owner=self.user,
            customer=self.customer,
            status=ConsultationRecording.STATUS_READY,
            storage_key=f'consultation-recordings/{uuid.uuid4()}/source',
            mime_type='audio/webm',
        )
        ConsultationRecording.objects.create(
            owner=self.user,
            customer=self.customer,
            status=ConsultationRecording.STATUS_DELETED,
            mime_type='audio/webm',
            deleted_at=timezone.now(),
            delete_reason='retention_expired',
        )

        response = self.client.get(
            f'/api/v1/customers/{self.customer.id}/recordings/?page=1',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 2)
        for row in response.data['results']:
            self.assertNotIn('storage_key', row)
            self.assertNotIn('checksum', row)
            self.assertNotIn('multipart_upload_id', row)

    def test_source_delete_is_idempotent_and_removes_storage_reference(self):
        recording = ConsultationRecording.objects.create(
            owner=self.user,
            customer=self.customer,
            status=ConsultationRecording.STATUS_READY,
            storage_key=f'consultation-recordings/{uuid.uuid4()}/source',
            mime_type='audio/webm',
            expires_at=timezone.now() + timedelta(days=1),
        )
        url = (
            f'/api/v1/customers/{self.customer.id}/recordings/'
            f'{recording.id}/source/'
        )

        first = self.client.delete(url)
        second = self.client.delete(url)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(self.storage.delete.call_count, 1)
        recording.refresh_from_db()
        self.assertEqual(recording.status, ConsultationRecording.STATUS_DELETED)
        self.assertIsNone(recording.storage_key)
        self.assertIsNotNone(recording.deleted_at)

    def test_failed_upload_delete_retries_abort_before_expiry(self):
        recording = ConsultationRecording.objects.create(
            owner=self.user,
            customer=self.customer,
            status=ConsultationRecording.STATUS_UPLOADING,
            storage_key=f'consultation-recordings/{uuid.uuid4()}/source',
            multipart_upload_id='upload-retry',
            mime_type='audio/webm',
            expires_at=timezone.now() + timedelta(days=1),
        )
        self.storage.abort.side_effect = RuntimeError('storage unavailable')
        url = (
            f'/api/v1/customers/{self.customer.id}/recordings/'
            f'{recording.id}/source/'
        )

        response = self.client.delete(url)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data['code'], 'RECORDING_DELETE_RETRY')
        recording.refresh_from_db()
        self.assertEqual(
            recording.status,
            ConsultationRecording.STATUS_DELETING,
        )
        self.assertEqual(recording.delete_result, 'retry_required')
        self.assertEqual(recording.delete_attempts, 1)

        self.storage.abort.side_effect = None
        result = cleanup_expired_recordings(
            now=timezone.now(),
            limit=100,
            storage=self.storage,
        )

        self.assertEqual(result['selected'], 1)
        self.assertEqual(result['deleted'], 1)
        self.assertEqual(self.storage.abort.call_count, 2)
        self.storage.abort.assert_called_with(
            recording.storage_key,
            'upload-retry',
        )
        self.storage.delete.assert_called_once_with(recording.storage_key)
        recording.refresh_from_db()
        self.assertEqual(recording.status, ConsultationRecording.STATUS_DELETED)
        self.assertEqual(recording.multipart_upload_id, '')
        self.assertEqual(recording.delete_reason, 'user_requested')

    def test_owner_download_uses_verified_container_after_2026_08_27(self):
        self._grant_recording_consents()
        ready_at = timezone.make_aware(datetime(2026, 7, 28, 9, 0))
        future_now = timezone.make_aware(datetime(2027, 1, 15, 9, 0))
        cases = (
            ('webm', 'audio/mp4', '.webm'),
            ('ogg', 'audio/webm', '.ogg'),
            ('mp4', 'audio/ogg', '.m4a'),
        )

        for verified_container, mime_type, expected_extension in cases:
            with self.subTest(verified_container=verified_container):
                recording = ConsultationRecording.objects.create(
                    owner=self.user,
                    customer=self.customer,
                    status=ConsultationRecording.STATUS_READY,
                    storage_key=(
                        f'consultation-recordings/{uuid.uuid4()}/source'
                    ),
                    mime_type=mime_type,
                    codec='client-value-does-not-control-extension',
                    verified_container=verified_container,
                    uploaded_at=ready_at,
                    expires_at=future_now + timedelta(days=30),
                )
                url = (
                    f'/api/v1/customers/{self.customer.id}/recordings/'
                    f'{recording.id}/download-url/'
                )

                with (
                    mock.patch(
                        'inpa.consultations.services.timezone.now',
                        return_value=future_now,
                    ),
                    self.assertLogs(
                        'inpa.consultations.views',
                        level='INFO',
                    ) as captured,
                ):
                    response = self.client.post(url)

                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(
                    response.data,
                    {
                        'url': 'https://download.example/private-signed-value',
                        'expires_in_seconds': 300,
                    },
                )
                filename = self.storage.presign_download.call_args.args[1]
                self.assertEqual(
                    filename,
                    f'consultation-recording-20260728{expected_extension}',
                )
                log_output = ' '.join(captured.output)
                self.assertIn(f'user_id={self.user.id}', log_output)
                self.assertIn(f'recording_id={recording.id}', log_output)
                self.assertIn('result=issued', log_output)
                self.assertNotIn(recording.storage_key, log_output)
                self.assertNotIn('private-signed-value', log_output)
                self.assertNotIn(self.customer.name, log_output)
                self.assertNotIn(self.user.email, log_output)
                self.storage.presign_download.reset_mock()

    def test_download_signing_failure_logs_only_content_safe_audit(self):
        self._grant_recording_consents()
        storage_key = f'consultation-recordings/{uuid.uuid4()}/source'
        recording = ConsultationRecording.objects.create(
            owner=self.user,
            customer=self.customer,
            status=ConsultationRecording.STATUS_READY,
            storage_key=storage_key,
            mime_type='audio/webm',
            verified_container='webm',
            uploaded_at=timezone.now(),
            expires_at=timezone.now() + timedelta(days=1),
        )
        self.storage.presign_download.side_effect = RuntimeError(
            f'{storage_key} https://signed.example/private',
        )

        response, log_output = self._post_download_failure(
            (
                f'/api/v1/customers/{self.customer.id}/recordings/'
                f'{recording.id}/download-url/'
            ),
            'signing_failed',
        )

        self.assertEqual(response.status_code, 503, response.content)
        self.assertNotIn(storage_key, log_output)
        self.assertNotIn('signed.example', log_output)
        self.assertNotIn(self.customer.name, log_output)
        self.assertNotIn(self.user.email, log_output)

    def test_download_uses_shared_customer_lock_and_recording_row_lock(self):
        self._grant_recording_consents()
        recording = ConsultationRecording.objects.create(
            owner=self.user,
            customer=self.customer,
            status=ConsultationRecording.STATUS_READY,
            storage_key=f'consultation-recordings/{uuid.uuid4()}/source',
            mime_type='audio/webm',
            verified_container='webm',
            uploaded_at=timezone.now(),
            expires_at=timezone.now() + timedelta(days=1),
        )

        with (
            mock.patch(
                'inpa.customers.consent_texts.Customer.objects.select_for_update',
                wraps=Customer.objects.select_for_update,
            ) as customer_lock,
            mock.patch.object(
                ConsultationRecording.objects,
                'select_for_update',
                wraps=ConsultationRecording.objects.select_for_update,
            ) as recording_lock,
            self.assertLogs('inpa.consultations.views', level='INFO'),
        ):
            response = self.client.post(
                f'/api/v1/customers/{self.customer.id}/recordings/'
                f'{recording.id}/download-url/',
            )

        self.assertEqual(response.status_code, 200, response.content)
        customer_lock.assert_called_once_with()
        recording_lock.assert_called_once_with()

    def test_truthful_legacy_row_without_verified_container_returns_410(self):
        self._grant_recording_consents()
        recording = ConsultationRecording.objects.create(
            owner=self.user,
            customer=self.customer,
            status=ConsultationRecording.STATUS_READY,
            storage_key=f'consultation-recordings/{uuid.uuid4()}/source',
            mime_type='audio/webm',
            verified_container='',
            uploaded_at=timezone.now(),
            expires_at=timezone.now() + timedelta(days=1),
        )

        response, _audit = self._post_download_failure(
            (
                f'/api/v1/customers/{self.customer.id}/recordings/'
                f'{recording.id}/download-url/'
            ),
            'source_unavailable',
        )

        self.assertEqual(response.status_code, 410, response.content)
        self.storage.presign_download.assert_not_called()

    def test_foreign_owner_and_ordinary_admin_download_are_both_hidden(self):
        self._grant_recording_consents()
        recording = ConsultationRecording.objects.create(
            owner=self.user,
            customer=self.customer,
            status=ConsultationRecording.STATUS_READY,
            storage_key=f'consultation-recordings/{uuid.uuid4()}/source',
            mime_type='audio/webm',
            uploaded_at=timezone.now(),
            expires_at=timezone.now() + timedelta(days=1),
        )
        url = (
            f'/api/v1/customers/{self.customer.id}/recordings/'
            f'{recording.id}/download-url/'
        )
        other = User.objects.create_user(
            email='recording-download-other@test.com',
            password='inpaPass123!',
        )
        other.is_active = True
        other.save(update_fields=['is_active'])
        Profile.objects.create(user=other)
        admin = User.objects.create_user(
            email='recording-download-admin@test.com',
            password='inpaPass123!',
        )
        admin.is_active = True
        admin.save(update_fields=['is_active'])
        Profile.objects.create(user=admin, is_admin=True)

        for actor in (other, admin):
            with self.subTest(actor=actor.email):
                self.client.force_authenticate(actor)
                response, _audit = self._post_download_failure(
                    url,
                    'not_found',
                )
                self.assertEqual(response.status_code, 404, response.content)

        self.storage.presign_download.assert_not_called()

    def test_download_requires_current_consent(self):
        recording = ConsultationRecording.objects.create(
            owner=self.user,
            customer=self.customer,
            status=ConsultationRecording.STATUS_READY,
            storage_key=f'consultation-recordings/{uuid.uuid4()}/source',
            mime_type='audio/webm',
            uploaded_at=timezone.now(),
            expires_at=timezone.now() + timedelta(days=1),
        )
        url = (
            f'/api/v1/customers/{self.customer.id}/recordings/'
            f'{recording.id}/download-url/'
        )

        missing, _missing_audit = self._post_download_failure(
            url,
            'consent_unavailable',
        )
        self.assertEqual(missing.status_code, 410, missing.content)

        self._grant_recording_consents()
        ConsentLog.objects.filter(
            customer=self.customer,
            scope=ConsentLog.SCOPE_CONSULTATION_RECORDING,
        ).update(revoked_at=timezone.now())
        withdrawn, _withdrawn_audit = self._post_download_failure(
            url,
            'consent_unavailable',
        )
        self.assertEqual(withdrawn.status_code, 410, withdrawn.content)
        self.storage.presign_download.assert_not_called()

    def test_download_rejects_expired_deleted_and_unavailable_sources(self):
        self._grant_recording_consents()
        now = timezone.now()
        cases = (
            (
                ConsultationRecording.STATUS_READY,
                f'consultation-recordings/{uuid.uuid4()}/source',
                now - timedelta(microseconds=1),
            ),
            (ConsultationRecording.STATUS_DELETED, None, now + timedelta(days=1)),
            (
                ConsultationRecording.STATUS_DELETING,
                f'consultation-recordings/{uuid.uuid4()}/source',
                now + timedelta(days=1),
            ),
            (
                ConsultationRecording.STATUS_PROCESSING,
                f'consultation-recordings/{uuid.uuid4()}/source',
                now + timedelta(days=1),
            ),
            (ConsultationRecording.STATUS_READY, None, now + timedelta(days=1)),
            (
                ConsultationRecording.STATUS_READY,
                f'consultation-recordings/{uuid.uuid4()}/source',
                None,
            ),
        )

        for index, (recording_status, storage_key, expires_at) in enumerate(cases):
            with self.subTest(recording_status=recording_status, index=index):
                recording = ConsultationRecording.objects.create(
                    owner=self.user,
                    customer=self.customer,
                    status=recording_status,
                    storage_key=storage_key,
                    mime_type='audio/webm',
                    uploaded_at=now,
                    expires_at=expires_at,
                )
                response, _audit = self._post_download_failure(
                    (
                        f'/api/v1/customers/{self.customer.id}/recordings/'
                        f'{recording.id}/download-url/'
                    ),
                    'source_unavailable',
                )
                self.assertEqual(response.status_code, 410, response.content)

        self.storage.presign_download.assert_not_called()

    def test_download_status_table_only_allows_ready_and_completed(self):
        self._grant_recording_consents()
        now = timezone.now()
        expected_by_status = {
            ConsultationRecording.STATUS_UPLOADING: 410,
            ConsultationRecording.STATUS_READY: 200,
            ConsultationRecording.STATUS_PROCESSING: 410,
            ConsultationRecording.STATUS_COMPLETED: 200,
            ConsultationRecording.STATUS_FAILED: 410,
            ConsultationRecording.STATUS_AMBIGUOUS: 410,
            ConsultationRecording.STATUS_DELETING: 410,
            ConsultationRecording.STATUS_DELETED: 410,
        }

        for recording_status, expected_status in expected_by_status.items():
            with self.subTest(recording_status=recording_status):
                recording = ConsultationRecording.objects.create(
                    owner=self.user,
                    customer=self.customer,
                    status=recording_status,
                    storage_key=(
                        f'consultation-recordings/{uuid.uuid4()}/source'
                    ),
                    mime_type='audio/webm',
                    verified_container='webm',
                    uploaded_at=now,
                    expires_at=now + timedelta(days=1),
                )
                url = (
                    f'/api/v1/customers/{self.customer.id}/recordings/'
                    f'{recording.id}/download-url/'
                )
                if expected_status == 200:
                    with self.assertLogs(
                        'inpa.consultations.views',
                        level='INFO',
                    ):
                        response = self.client.post(url)
                    self.assertEqual(response.status_code, 200, response.content)
                else:
                    response, _audit = self._post_download_failure(
                        url,
                        'source_unavailable',
                    )
                    self.assertEqual(response.status_code, 410, response.content)

        self.assertEqual(self.storage.presign_download.call_count, 2)

    @mock.patch('inpa.consultations.services.av.open')
    def test_inspect_audio_normalizes_allowlisted_pyav_container_aliases(
        self,
        av_open,
    ):
        cases = (
            ('matroska,webm', 'opus', 'webm'),
            ('ogg', 'opus', 'ogg'),
            ('mov,mp4,m4a,3gp,3g2,mj2', 'aac', 'mp4'),
        )

        for format_name, codec, expected_container in cases:
            with self.subTest(format_name=format_name):
                av_open.return_value = _mock_av_container(format_name, codec)

                result = inspect_audio([b'server-inspected-audio'])

                self.assertEqual(result.byte_size, 22)
                self.assertEqual(result.duration_ms, 1000)
                self.assertEqual(result.codec, codec)
                self.assertEqual(result.container, expected_container)
                self.assertTrue(result.checksum.startswith('sha256:'))

    @mock.patch('inpa.consultations.services.av.open')
    def test_inspect_audio_rejects_container_outside_allowlist(self, av_open):
        av_open.return_value = _mock_av_container('wav', 'pcm_s16le')

        with self.assertRaises(InvalidRecording) as error:
            inspect_audio([b'wave-container'])

        self.assertEqual(error.exception.code, 'RECORDING_CONTAINER_INVALID')

    def test_inspect_audio_turns_invalid_container_into_safe_domain_error(self):
        with self.assertRaises(InvalidRecording) as error:
            inspect_audio([b'not-an-audio-container'])

        self.assertEqual(error.exception.code, 'RECORDING_FORMAT_INVALID')
