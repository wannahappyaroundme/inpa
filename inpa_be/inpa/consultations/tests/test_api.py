import io
import uuid
import wave
from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User
from inpa.consultations.models import (
    ConsultationPilotAccess,
    ConsultationRecording,
    ConsultationRuntimeConfig,
)
from inpa.consultations.services import (
    AudioInspection,
    InvalidRecording,
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


@override_settings(
    CONSULTATION_RECORDING_ENABLED=True,
    CONSULTATION_MAX_DURATION_SECONDS=3600,
    CONSULTATION_MAX_BYTES=100 * 1024 * 1024,
    CONSULTATION_UPLOAD_PART_BYTES=8 * 1024 * 1024,
)
class ConsultationRecordingApiTests(TestCase):
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
        self.storage.create.side_effect = lambda recording_id, _mime: MultipartSession(
            key=f'consultation-recordings/{recording_id}/source',
            upload_id='upload-1',
        )
        self.storage.presign_part.return_value = 'https://upload.example/part'
        self.storage.presign_get.return_value = 'https://play.example/source'
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

    def _create_upload(self):
        self._grant_recording_consents()
        return self.client.post(
            f'/api/v1/customers/{self.customer.id}/recordings/upload-sessions/',
            {
                'client_session_id': str(uuid.uuid4()),
                'mime_type': 'audio/webm;codecs=opus',
                'started_at': timezone.now().isoformat(),
            },
            format='json',
        )

    def test_upload_session_requires_both_current_customer_consents(self):
        response = self.client.post(
            f'/api/v1/customers/{self.customer.id}/recordings/upload-sessions/',
            {
                'mime_type': 'audio/webm',
                'started_at': timezone.now().isoformat(),
            },
            format='json',
        )

        self.assertEqual(response.status_code, 412)
        self.assertEqual(response.data['code'], 'CONSULTATION_CONSENT_REQUIRED')
        self.assertEqual(ConsultationRecording.objects.count(), 0)

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

    def test_uploading_source_cannot_issue_play_url(self):
        response = self._create_upload()
        recording_id = response.data['id']

        result = self.client.post(
            f'/api/v1/customers/{self.customer.id}/recordings/'
            f'{recording_id}/play-url/',
        )

        self.assertEqual(result.status_code, 409)
        self.storage.presign_get.assert_not_called()

    @mock.patch(
        'inpa.consultations.services.inspect_audio',
        return_value=AudioInspection(
            byte_size=1024,
            duration_ms=60_000,
            codec='opus',
            checksum='sha256:abc',
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

    def test_inspect_audio_reads_actual_audio_duration_and_checksum(self):
        result = inspect_audio([_audio_wav_bytes(duration_seconds=1)])

        self.assertEqual(result.byte_size, len(_audio_wav_bytes(duration_seconds=1)))
        self.assertGreaterEqual(result.duration_ms, 990)
        self.assertLessEqual(result.duration_ms, 1010)
        self.assertEqual(result.codec, 'pcm_s16le')
        self.assertTrue(result.checksum.startswith('sha256:'))

    def test_inspect_audio_turns_invalid_container_into_safe_domain_error(self):
        with self.assertRaises(InvalidRecording) as error:
            inspect_audio([b'not-an-audio-container'])

        self.assertEqual(error.exception.code, 'RECORDING_FORMAT_INVALID')
