import os
from pathlib import Path
import subprocess
import sys
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from inpa.consultations.gates import recording_feature_enabled
from inpa.consultations.models import (
    ConsultationPilotAccess,
    ConsultationRecording,
    ConsultationRuntimeConfig,
)
from inpa.customers.models import Customer


User = get_user_model()


class ConsultationRetentionSettingsTests(SimpleTestCase):
    def _load_production_settings(self, **overrides):
        environment = os.environ.copy()
        environment.update({
            'DJANGO_SETTINGS_MODULE': 'config.settings.prod',
            'SECRET_KEY': 'test-' + 'only-settings-value',
            'DATABASE_URL': 'sqlite:///:memory:',
            **overrides,
        })
        return subprocess.run(
            [
                sys.executable,
                '-c',
                'import django; django.setup()',
            ],
            cwd=Path(settings.BASE_DIR),
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def test_production_recording_gate_rejects_non_720_hour_policy(self):
        result = self._load_production_settings(
            CONSULTATION_RECORDING_ENABLED='True',
            CONSULTATION_RETENTION_HOURS='719',
        )

        self.assertNotEqual(result.returncode, 0)
        output = f'{result.stdout}\n{result.stderr}'
        self.assertIn(
            'CONSULTATION_RETENTION_HOURS must be exactly 720',
            output,
        )
        self.assertNotIn('test-only-settings-value', output)

    def test_openai_summary_gate_requires_every_server_only_setting(self):
        placeholder = 'not-a-secret-test-value'
        result = self._load_production_settings(
            CONSULTATION_AI_SUMMARY_ENABLED='True',
            CONSULTATION_STT_PROVIDER='openai',
            CONSULTATION_SUMMARY_PROVIDER='openai',
            OPENAI_API_KEY=placeholder,
            OPENAI_TRANSCRIPTION_MODEL='transcription-from-environment',
            OPENAI_COMPARISON_MODEL='',
            OPENAI_CONSULTATION_SUMMARY_MODEL='',
        )

        self.assertNotEqual(result.returncode, 0)
        output = f'{result.stdout}\n{result.stderr}'
        self.assertIn(
            'OPENAI_CONSULTATION_SUMMARY_MODEL',
            output,
        )
        self.assertNotIn(placeholder, output)

    def test_openai_summary_gate_accepts_model_fallback_from_comparison(self):
        placeholder = 'not-a-secret-test-value'
        result = self._load_production_settings(
            CONSULTATION_AI_SUMMARY_ENABLED='True',
            CONSULTATION_STT_PROVIDER='openai',
            CONSULTATION_SUMMARY_PROVIDER='openai',
            OPENAI_API_KEY=placeholder,
            OPENAI_TRANSCRIPTION_MODEL='transcription-from-environment',
            OPENAI_COMPARISON_MODEL='summary-from-environment',
        )

        self.assertEqual(
            result.returncode,
            0,
            f'{result.stdout}\n{result.stderr}',
        )


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

    def test_ready_recording_expiry_uses_its_legacy_snapshot_exactly(self):
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
            actual_container='webm',
        )

        self.assertEqual(recording.status, ConsultationRecording.STATUS_READY)
        self.assertEqual(
            recording.expires_at - recording.ready_at,
            timedelta(days=7),
        )
        self.assertEqual(recording.multipart_upload_id, '')
        self.assertEqual(recording.verified_container, 'webm')

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
                actual_container='webm',
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
