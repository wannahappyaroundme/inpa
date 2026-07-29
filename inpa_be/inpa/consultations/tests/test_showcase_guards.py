import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User
from inpa.billing.models import Plan
from inpa.consultations.callbacks import make_clova_callback_url
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
    SHOWCASE_ACCOUNT_EMAIL='showcase-consultation@inpa.example',
    CONSULTATION_RECORDING_ENABLED=True,
    CONSULTATION_AI_SUMMARY_ENABLED=True,
    CONSULTATION_SHOWCASE_PILOT_ENABLED=True,
    CONSULTATION_SUMMARY_PROMPT_VERSION='showcase-guard-v1',
    BACKEND_BASE_URL='https://api.inpa.example',
)
class ShowcaseConsultationGuardTests(TestCase):
    def setUp(self):
        Plan.objects.create(
            code='free',
            display_name='Free',
            price_krw=0,
        )
        self.user = User.objects.create_user(
            email='showcase-consultation@inpa.example',
            password='local-only-password',
        )
        self.user.is_active = True
        self.user.save(update_fields=['is_active'])
        Profile.objects.create(user=self.user, is_showcase=True)
        self.customer = Customer.objects.create(
            owner=self.user,
            name='내부 시연 고객',
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
        runtime = ConsultationRuntimeConfig.solo()
        runtime.recording_enabled = True
        runtime.ai_summary_enabled = True
        runtime.save(update_fields=[
            'recording_enabled',
            'ai_summary_enabled',
            'updated_at',
        ])
        ConsultationPilotAccess.objects.create(
            user=self.user,
            recording_allowed=True,
            summary_allowed=True,
        )
        self.uploading = ConsultationRecording.objects.create(
            owner=self.user,
            customer=self.customer,
            client_session_id=uuid.uuid4(),
            status=ConsultationRecording.STATUS_UPLOADING,
            storage_key=f'consultation-recordings/{uuid.uuid4()}/source',
            multipart_upload_id='showcase-upload',
            mime_type='audio/webm',
        )
        self.ready = ConsultationRecording.objects.create(
            owner=self.user,
            customer=self.customer,
            status=ConsultationRecording.STATUS_READY,
            storage_key=f'consultation-recordings/{uuid.uuid4()}/source',
            mime_type='audio/webm',
            verified_container='webm',
            byte_size=1024,
            duration_ms=120_000,
            uploaded_at=timezone.now(),
            ended_at=timezone.now(),
            expires_at=timezone.now() + timedelta(days=1),
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _recording_snapshot(self):
        return list(
            ConsultationRecording.objects.order_by('id').values(
                'id',
                'status',
                'storage_key',
                'multipart_upload_id',
                'byte_size',
                'duration_ms',
                'deleted_at',
                'delete_reason',
                'delete_result',
                'version',
            )
        )

    @override_settings(CONSULTATION_SHOWCASE_PILOT_ENABLED=False)
    @patch('inpa.consultations.services.get_recording_storage')
    @patch('inpa.consultations.summary_service.enqueue_summary_run')
    def test_every_recording_mutation_is_blocked_before_storage_or_ai_queue(
        self,
        enqueue_summary,
        get_storage,
    ):
        storage = get_storage.return_value
        storage.presign_part.return_value = 'https://upload.example/part'
        storage.presign_get.return_value = 'https://play.example/source'
        storage.presign_download.return_value = 'https://download.example/source'
        storage.head.return_value = {'ContentLength': 1024}
        storage.iter_object.return_value = iter([b'not-an-audio-file'])
        before = self._recording_snapshot()
        routes = (
            (
                'post',
                f'/api/v1/customers/{self.customer.id}/recordings/'
                'upload-sessions/',
                {
                    'client_session_id': str(uuid.uuid4()),
                    'mime_type': 'audio/webm',
                    'notice_attested': True,
                    'notice_version':
                        'consultation-notice-v2-2026-07-28',
                },
            ),
            (
                'post',
                f'/api/v1/customers/{self.customer.id}/recordings/'
                f'{self.uploading.id}/parts/1/',
                {},
            ),
            (
                'post',
                f'/api/v1/customers/{self.customer.id}/recordings/'
                f'{self.uploading.id}/complete-upload/',
                {
                    'parts': [{
                        'part_number': 1,
                        'etag': 'etag-1',
                        'byte_size': 1024,
                    }],
                },
            ),
            (
                'post',
                f'/api/v1/customers/{self.customer.id}/recordings/'
                f'{self.ready.id}/play-url/',
                {},
            ),
            (
                'post',
                f'/api/v1/customers/{self.customer.id}/recordings/'
                f'{self.ready.id}/download-url/',
                {},
            ),
            (
                'delete',
                f'/api/v1/customers/{self.customer.id}/recordings/'
                f'{self.ready.id}/source/',
                {},
            ),
            (
                'post',
                f'/api/v1/customers/{self.customer.id}/recordings/'
                f'{self.ready.id}/summarize/',
                {},
            ),
        )

        for method, url, payload in routes:
            with self.subTest(url=url):
                kwargs = {'format': 'json'}
                if url.endswith('/summarize/'):
                    kwargs['HTTP_IDEMPOTENCY_KEY'] = 'showcase-summary'
                response = getattr(self.client, method)(url, payload, **kwargs)
                self.assertEqual(response.status_code, 403, response.content)
                self.assertEqual(
                    response.data['code'],
                    'SHOWCASE_ACTION_RESTRICTED',
                )

        self.assertEqual(self._recording_snapshot(), before)
        self.assertEqual(ConsultationRecording.objects.count(), 2)
        self.assertEqual(ConsultationSummaryRun.objects.count(), 0)
        get_storage.assert_not_called()
        enqueue_summary.assert_not_called()

    def test_capability_opens_only_with_the_extra_showcase_pilot_gate(self):
        response = self.client.get(
            f'/api/v1/customers/{self.customer.id}/recordings/capability/',
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.data['recording_enabled'])
        self.assertTrue(response.data['summary_enabled'])

    @patch('inpa.consultations.services.get_recording_storage')
    def test_external_storage_actions_close_when_pilot_access_is_removed(
        self,
        get_storage,
    ):
        access = ConsultationPilotAccess.objects.get(user=self.user)
        access.recording_allowed = False
        access.save(update_fields=['recording_allowed', 'updated_at'])

        response = self.client.post(
            f'/api/v1/customers/{self.customer.id}/recordings/'
            f'{self.ready.id}/play-url/',
            {},
            format='json',
        )

        self.assertEqual(response.status_code, 403, response.content)
        get_storage.assert_not_called()

    @patch('inpa.consultations.tasks.process_consultation_summary.delay')
    def test_direct_summary_enqueue_accepts_exact_showcase_pilot_run(self, enqueue):
        from inpa.consultations.summary_service import enqueue_summary_run

        run = ConsultationSummaryRun.objects.create(
            recording=self.ready,
            status=ConsultationSummaryRun.STATUS_QUEUED,
            idempotency_key='direct-showcase-run',
            prompt_version='showcase-guard-v1',
            recording_consent_version='recording-v1',
            sensitive_consent_version='sensitive-v1',
            overseas_consent_version='overseas-v1',
        )

        enqueue_summary_run(run.id)

        run.refresh_from_db()
        self.assertEqual(run.status, ConsultationSummaryRun.STATUS_QUEUED)
        enqueue.assert_called_once_with(str(run.id))

    def test_render_worker_receives_showcase_identity_from_web_service(self):
        repo_root = Path(__file__).resolve().parents[4]
        blueprint = (repo_root / 'render.yaml').read_text(encoding='utf-8')
        worker = blueprint.split(
            '  - type: worker\n    name: inpa-insurance-worker',
            1,
        )[1].split('\n  - type: cron', 1)[0]

        self.assertRegex(
            worker,
            r'- key: SHOWCASE_ACCOUNT_EMAIL\s+fromService:\s+type: web\s+'
            r'name: inpa-be\s+envVarKey: SHOWCASE_ACCOUNT_EMAIL',
        )

    @patch('inpa.consultations.views.process_consultation_summary.apply_async')
    def test_signed_callback_for_showcase_pilot_wakes_only_the_signed_run(
        self,
        enqueue,
    ):
        run = ConsultationSummaryRun.objects.create(
            recording=self.ready,
            status=ConsultationSummaryRun.STATUS_QUEUED,
            idempotency_key='existing-showcase-run',
            prompt_version='showcase-guard-v1',
            recording_consent_version='recording-v1',
            sensitive_consent_version='sensitive-v1',
            overseas_consent_version='overseas-v1',
        )
        callback_path = make_clova_callback_url(run).replace(
            'https://api.inpa.example',
            '',
            1,
        )

        response = APIClient().post(callback_path, {}, format='json')

        self.assertEqual(response.status_code, 202, response.content)
        run.refresh_from_db()
        self.assertEqual(run.status, ConsultationSummaryRun.STATUS_QUEUED)
        enqueue.assert_called_once_with(
            args=[str(run.id)],
            queue='consultation_summaries',
        )

    def test_email_match_without_showcase_profile_marker_stays_closed(self):
        self.user.profile.is_showcase = False
        self.user.profile.save(update_fields=['is_showcase'])
        ConsultationPilotAccess.objects.filter(user=self.user).delete()

        response = self.client.get(
            f'/api/v1/customers/{self.customer.id}/recordings/capability/',
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(response.data['recording_enabled'])
        self.assertFalse(response.data['summary_enabled'])

    @override_settings(CONSULTATION_SHOWCASE_PILOT_ENABLED=False)
    def test_extra_showcase_pilot_environment_gate_defaults_closed(self):
        response = self.client.get(
            f'/api/v1/customers/{self.customer.id}/recordings/capability/',
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(response.data['recording_enabled'])
        self.assertFalse(response.data['summary_enabled'])
