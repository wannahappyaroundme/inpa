import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from inpa.consultations.gates import recording_feature_enabled
from inpa.consultations.models import (
    ConsultationPilotAccess,
    ConsultationRecording,
    ConsultationRuntimeConfig,
)
from inpa.customers.models import Customer


User = get_user_model()


class ConsultationRecordingModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='recording-owner@example.com',
            password='strong-password',
        )
        self.customer = Customer.objects.create(
            owner=self.user,
            name='상담 고객',
        )

    def test_ready_recording_expiry_is_server_stamped_inside_seven_days(self):
        ended_at = timezone.now()
        recording = ConsultationRecording.objects.create(
            owner=self.user,
            customer=self.customer,
            status=ConsultationRecording.STATUS_UPLOADING,
            storage_key=f'consultation-recordings/{uuid.uuid4()}/source',
            multipart_upload_id='upload-1',
            mime_type='audio/webm',
        )

        recording.mark_ready(
            ended_at=ended_at,
            byte_size=8_000_000,
            duration_ms=3_600_000,
            checksum='sha256:abc',
        )

        self.assertEqual(recording.status, ConsultationRecording.STATUS_READY)
        self.assertLessEqual(recording.expires_at, ended_at + timedelta(days=7))
        self.assertGreater(
            recording.expires_at,
            ended_at + timedelta(days=6, hours=23),
        )
        self.assertEqual(recording.multipart_upload_id, '')

    def test_mark_ready_rejects_a_second_transition(self):
        recording = ConsultationRecording.objects.create(
            owner=self.user,
            customer=self.customer,
            status=ConsultationRecording.STATUS_READY,
            storage_key=f'consultation-recordings/{uuid.uuid4()}/source',
            mime_type='audio/webm',
        )

        with self.assertRaisesMessage(ValueError, 'INVALID_RECORDING_TRANSITION'):
            recording.mark_ready(
                ended_at=timezone.now(),
                byte_size=1,
                duration_ms=1,
                checksum='sha256:x',
            )

    @override_settings(CONSULTATION_RECORDING_ENABLED=False)
    def test_runtime_switch_cannot_open_closed_environment_gate(self):
        config = ConsultationRuntimeConfig.solo()
        config.recording_enabled = True
        config.save(update_fields=['recording_enabled', 'updated_at'])

        self.assertFalse(recording_feature_enabled(self.user))

    @override_settings(CONSULTATION_RECORDING_ENABLED=True)
    def test_pilot_user_requires_both_environment_and_runtime_gates(self):
        config = ConsultationRuntimeConfig.solo()
        config.recording_enabled = True
        config.save(update_fields=['recording_enabled', 'updated_at'])
        ConsultationPilotAccess.objects.create(
            user=self.user,
            recording_allowed=True,
        )

        self.assertTrue(recording_feature_enabled(self.user))
