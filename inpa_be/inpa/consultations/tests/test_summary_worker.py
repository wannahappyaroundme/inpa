from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from inpa.accounts.models import User
from inpa.consultations.callbacks import make_clova_callback_url
from inpa.consultations.models import (
    ConsultationPilotAccess,
    ConsultationRecording,
    ConsultationRuntimeConfig,
    ConsultationSummaryRun,
)
from inpa.consultations.providers.anthropic_summary import SummaryProviderResult
from inpa.consultations.providers.base import (
    ExplicitProviderNonReceipt,
    SpeechJobResult,
    SummaryOutcomeUnknown,
)
from inpa.consultations.summary_schema import ConsultationSummary
from inpa.consultations.summary_service import request_summary
from inpa.consultations.summary_worker import run_summary_step
from inpa.customers.consent_texts import (
    CONSULTATION_CONSENT_VERSIONS,
    CONSULTATION_SUMMARY_CONSENT_VERSION,
)
from inpa.customers.models import ConsentLog, Customer, CustomerMemo

TEST_PROVIDER_CREDENTIAL = 'test-only'


@contextmanager
def _prepared_audio():
    from io import BytesIO
    yield BytesIO(b'RIFF-prepared')


@override_settings(
    CONSULTATION_AI_SUMMARY_ENABLED=True,
    CONSULTATION_SUMMARY_PROMPT_VERSION='worker-prompt-v1',
    CONSULTATION_SUMMARY_MODEL='summary-model',
    CONSULTATION_STT_PROVIDER='clova',
    CLOVA_SPEECH_INVOKE_URL='https://clova.example',
    CLOVA_SPEECH_SECRET_KEY=TEST_PROVIDER_CREDENTIAL,
    ANTHROPIC_API_KEY=TEST_PROVIDER_CREDENTIAL,
    BACKEND_BASE_URL='https://api.inpa.example',
    CONSULTATION_SUMMARY_ACTIVE_LIMIT=1,
)
class ConsultationSummaryWorkerTests(TestCase):
    def setUp(self):
        call_command('seed_billing')
        self.user = User.objects.create_user(
            email='summary-worker@example.com',
            password='strong-password',
        )
        self.customer = Customer.objects.create(
            owner=self.user,
            name='김고객',
        )
        self.recording = ConsultationRecording.objects.create(
            owner=self.user,
            customer=self.customer,
            status=ConsultationRecording.STATUS_READY,
            storage_key=(
                'consultation-recordings/'
                '00000000-0000-4000-8000-000000000401/source'
            ),
            mime_type='audio/webm',
            duration_ms=60_000,
            ended_at=timezone.now() - timedelta(minutes=1),
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
        with patch(
            'inpa.consultations.summary_service.enqueue_summary_run',
        ):
            self.run, _ = request_summary(
                recording=self.recording,
                user=self.user,
                idempotency_key='worker-request',
            )

    def _set_stt_job(self):
        self.run.status = ConsultationSummaryRun.STATUS_TRANSCRIBING
        self.run.provider_reserved_at = timezone.now()
        self.run.stt_provider = 'clova'
        self.run.stt_job_id = 'same-provider-token'
        self.run.save(update_fields=[
            'status',
            'provider_reserved_at',
            'stt_provider',
            'stt_job_id',
            'updated_at',
        ])

    def _summary_result(self):
        return SummaryProviderResult(
            summary=ConsultationSummary(
                consultation_core=('상담 내용을 함께 확인함',),
                customer_priorities=('가족 보장을 중요하게 봄',),
                items_to_confirm=('보험료 확인 필요',),
                next_actions=('다음 만남 날짜 확인',),
            ),
            input_tokens=120,
            output_tokens=40,
            model='claude-haiku-test',
        )

    @patch('inpa.consultations.summary_worker.ClovaSpeechProvider')
    def test_redelivery_with_job_token_only_polls_same_job(self, provider_cls):
        self._set_stt_job()
        provider = provider_cls.return_value
        provider.poll.return_value = SpeechJobResult(state='processing')

        result = run_summary_step(self.run.id)

        self.assertEqual(result.outcome, 'processing')
        provider.poll.assert_called_once_with('same-provider-token')
        provider.submit.assert_not_called()

    @patch('inpa.consultations.summary_worker.AnthropicConsultationSummarizer')
    @patch('inpa.consultations.summary_worker.ClovaSpeechProvider')
    def test_unknown_summary_outcome_is_never_called_again(
        self,
        provider_cls,
        summarizer_cls,
    ):
        self._set_stt_job()
        provider_cls.return_value.poll.return_value = SpeechJobResult(
            state='completed',
            transcript='김고객 전화번호는 010-1234-5678입니다',
        )
        summarizer_cls.return_value.summarize.side_effect = (
            SummaryOutcomeUnknown('ReadTimeout')
        )

        first = run_summary_step(self.run.id)
        second = run_summary_step(self.run.id)

        self.assertEqual(first.outcome, 'ambiguous')
        self.assertEqual(second.outcome, 'terminal')
        self.run.refresh_from_db()
        self.assertEqual(
            self.run.status,
            ConsultationSummaryRun.STATUS_AMBIGUOUS,
        )
        self.assertEqual(CustomerMemo.objects.count(), 0)
        summarizer_cls.return_value.summarize.assert_called_once()

    @patch('inpa.consultations.summary_worker.open_clova_wav')
    @patch('inpa.consultations.summary_worker.get_recording_storage')
    @patch('inpa.consultations.summary_worker.ClovaSpeechProvider')
    def test_explicit_nonreceipt_clears_marker_for_same_run_retry(
        self,
        provider_cls,
        _storage,
        open_wav,
    ):
        open_wav.return_value = _prepared_audio()
        provider_cls.return_value.submit.side_effect = (
            ExplicitProviderNonReceipt('ConnectError')
        )

        result = run_summary_step(self.run.id)

        self.assertEqual(result.outcome, 'retry')
        self.run.refresh_from_db()
        self.assertEqual(self.run.status, ConsultationSummaryRun.STATUS_QUEUED)
        self.assertIsNone(self.run.provider_reserved_at)
        self.assertEqual(self.run.stt_job_id, '')
        provider_cls.return_value.submit.assert_called_once()

    @patch('inpa.consultations.summary_worker.ClovaSpeechProvider')
    def test_deleted_source_cancels_late_result_without_poll_or_memo(
        self,
        provider_cls,
    ):
        self._set_stt_job()
        self.recording.status = ConsultationRecording.STATUS_DELETED
        self.recording.storage_key = None
        self.recording.save(update_fields=['status', 'storage_key', 'updated_at'])

        result = run_summary_step(self.run.id)

        self.assertEqual(result.outcome, 'cancelled')
        self.run.refresh_from_db()
        self.assertEqual(
            self.run.status,
            ConsultationSummaryRun.STATUS_CANCELLED,
        )
        provider_cls.return_value.poll.assert_not_called()
        self.assertEqual(CustomerMemo.objects.count(), 0)

    @patch('inpa.consultations.summary_worker.AnthropicConsultationSummarizer')
    @patch('inpa.consultations.summary_worker.ClovaSpeechProvider')
    def test_success_creates_exactly_one_editable_memo_without_transcript(
        self,
        provider_cls,
        summarizer_cls,
    ):
        self._set_stt_job()
        provider_cls.return_value.poll.return_value = SpeechJobResult(
            state='completed',
            transcript='김고객 연락처 010-1234-5678 상담 원문',
        )
        summarizer_cls.return_value.summarize.return_value = (
            self._summary_result()
        )

        first = run_summary_step(self.run.id)
        second = run_summary_step(self.run.id)

        self.assertEqual(first.outcome, 'succeeded')
        self.assertEqual(second.outcome, 'terminal')
        memo = CustomerMemo.objects.get(summary_run=self.run)
        self.assertEqual(memo.customer, self.customer)
        self.assertEqual(memo.owner, self.user)
        self.assertEqual(memo.source, CustomerMemo.SOURCE_AI_SUMMARY)
        self.assertIn('상담 핵심', memo.body)
        self.assertNotIn('010-1234-5678', memo.body)
        self.run.refresh_from_db()
        self.assertFalse(
            any(
                field.name in {'transcript', 'masked_transcript'}
                for field in self.run._meta.fields
            ),
        )
        summarizer_cls.return_value.summarize.assert_called_once()

    @patch('inpa.consultations.views.process_consultation_summary.apply_async')
    def test_signed_callback_ignores_provider_body_and_only_wakes_same_run(
        self,
        enqueue,
    ):
        callback_url = make_clova_callback_url(self.run)
        callback_path = callback_url.replace(
            'https://api.inpa.example',
            '',
            1,
        )

        response = APIClient().post(
            callback_path,
            {
                'token': 'attacker-token',
                'transcript': '저장되면 안 되는 원문',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 202)
        enqueue.assert_called_once_with(
            args=[str(self.run.id)],
            queue='consultation_summaries',
        )
        self.assertEqual(CustomerMemo.objects.count(), 0)
