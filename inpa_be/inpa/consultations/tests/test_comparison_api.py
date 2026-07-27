import io
import wave
from unittest.mock import Mock, patch

from django.conf import settings
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase
from rest_framework.throttling import ScopedRateThrottle

from inpa.accounts.models import Profile, User
from inpa.billing.models import PaymentOrder, UsageMeter
from inpa.consultations.comparison import ConsultationComparisonService
from inpa.consultations.comparison_audio import ComparisonAudioError
from inpa.consultations.models import ConsultationRecording
from inpa.consultations.providers.comparison_base import (
    ComparisonDeadline,
    ComparisonOutcomeUnknown,
    ComparisonProviderFailure,
    ComparisonSummaryResult,
    ComparisonTranscriptSegment,
    ComparisonTranscription,
)
from inpa.consultations.summary_schema import ConsultationSummary
from inpa.customers.models import CustomerMemo


def make_wav(seconds=1, sample_rate=16_000):
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b'\x00\x00' * sample_rate * seconds)
    return output.getvalue()


@override_settings(
    CONSULTATION_AI_COMPARISON_ENABLED=True,
    OPENAI_API_KEY='test-value',
    OPENAI_TRANSCRIPTION_MODEL='env-transcriber',
    OPENAI_COMPARISON_MODEL='env-openai-summary',
    ANTHROPIC_API_KEY='test-value',
    ANTHROPIC_COMPARISON_MODEL='env-anthropic-summary',
)
class AdminConsultationComparisonApiTests(APITestCase):
    url = '/api/v1/admin/consultations/comparison/'

    def setUp(self):
        cache.clear()
        self.admin = self._make_user(
            'comparison-admin@inpa.kr',
            is_admin=True,
        )
        self.user = self._make_user('comparison-user@inpa.kr')
        self.admin_token = Token.objects.create(user=self.admin)
        self.user_token = Token.objects.create(user=self.user)
        self.service = Mock()
        self.service.compare.return_value = self.success_payload()
        self.service_class_patcher = patch(
            'inpa.admin_console.views.ConsultationComparisonService',
            return_value=self.service,
            create=True,
        )
        self.service_class = self.service_class_patcher.start()
        self.addCleanup(self.service_class_patcher.stop)

    @staticmethod
    def _make_user(email, *, is_admin=False):
        user = User.objects.create_user(
            email=email,
            password='inpaPass123!',
        )
        user.is_active = True
        user.save(update_fields=['is_active'])
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.is_admin = is_admin
        profile.save(update_fields=['is_admin'])
        return user

    @staticmethod
    def success_payload():
        return {
            'transcript': {
                'segments': [{
                    'speaker': '화자 1',
                    'text': '가상 상담 내용입니다.',
                    'start_seconds': 0.0,
                    'end_seconds': 1.0,
                }],
            },
            'results': [{
                'slot': 'A',
                'provider': 'openai',
                'model': 'env-openai-summary',
                'status': 'success',
                'summary': {
                    'consultation_core': ['상담 핵심'],
                    'customer_priorities': ['고객 우선순위'],
                    'items_to_confirm': ['확인할 내용'],
                    'next_actions': ['다음 할 일'],
                },
                'latency_ms': 10,
                'input_tokens': 20,
                'output_tokens': 5,
                'error_code': '',
            }],
        }

    @staticmethod
    def valid_payload():
        return {
            'audio': SimpleUploadedFile(
                'synthetic.wav',
                b'synthetic audio fixture',
                content_type='audio/wav',
            ),
            'synthetic_confirmed': True,
        }

    def post_as_admin(self, payload):
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Token {self.admin_token.key}',
        )
        return self.client.post(self.url, payload, format='multipart')

    def assert_product_rows_unchanged(self, before):
        self.assertEqual(before, {
            'recordings': ConsultationRecording.objects.count(),
            'memos': CustomerMemo.objects.count(),
            'usage': UsageMeter.objects.count(),
            'orders': PaymentOrder.objects.count(),
        })

    def test_anonymous_and_non_admin_cannot_spend_provider_cost(self):
        anonymous = self.client.post(self.url, {}, format='multipart')
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Token {self.user_token.key}',
        )
        regular = self.client.post(self.url, {}, format='multipart')

        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(regular.status_code, 403)
        self.service_class.assert_not_called()
        self.service.compare.assert_not_called()

    @override_settings(
        CONSULTATION_AI_COMPARISON_ENABLED=False,
        OPENAI_API_KEY='',
        OPENAI_TRANSCRIPTION_MODEL='',
        OPENAI_COMPARISON_MODEL='',
        ANTHROPIC_API_KEY='',
        ANTHROPIC_COMPARISON_MODEL='',
    )
    def test_closed_environment_gate_returns_before_readiness_and_input(self):
        response = self.post_as_admin({})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.data,
            {
                'code': 'CONSULTATION_COMPARISON_CLOSED',
                'detail': '내부 비교 설정을 켜면 바로 확인할 수 있어요.',
            },
        )
        self.service_class.assert_not_called()
        self.service.compare.assert_not_called()

    def test_every_provider_setting_is_required_before_input_validation(self):
        required_settings = (
            'OPENAI_API_KEY',
            'OPENAI_TRANSCRIPTION_MODEL',
            'OPENAI_COMPARISON_MODEL',
            'ANTHROPIC_API_KEY',
            'ANTHROPIC_COMPARISON_MODEL',
        )

        for setting_name in required_settings:
            with self.subTest(setting=setting_name), self.settings(
                **{setting_name: ''},
            ):
                response = self.post_as_admin({})

                self.assertEqual(response.status_code, 503)
                self.assertEqual(
                    response.data,
                    {
                        'code': 'CONSULTATION_COMPARISON_NOT_READY',
                        'detail': (
                            '두 AI 연결 설정을 마치면 비교를 시작할 수 있어요.'
                        ),
                    },
                )
        self.service_class.assert_not_called()
        self.service.compare.assert_not_called()

    def test_audio_is_required_before_service_construction(self):
        response = self.post_as_admin({
            'synthetic_confirmed': True,
        })

        self.assertEqual(response.status_code, 400)
        self.assertIn('audio', response.data)
        self.service_class.assert_not_called()
        self.service.compare.assert_not_called()

    def test_requires_explicit_synthetic_confirmation(self):
        payload = self.valid_payload()
        payload['synthetic_confirmed'] = False

        response = self.post_as_admin(payload)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data,
            {
                'code': 'SYNTHETIC_CONFIRMATION_REQUIRED',
                'detail': '가상 녹음 확인을 선택해 주세요.',
            },
        )
        self.service_class.assert_not_called()
        self.service.compare.assert_not_called()

    def test_success_returns_comparison_without_creating_product_rows(self):
        before = {
            'recordings': ConsultationRecording.objects.count(),
            'memos': CustomerMemo.objects.count(),
            'usage': UsageMeter.objects.count(),
            'orders': PaymentOrder.objects.count(),
        }
        payload = self.valid_payload()

        response = self.post_as_admin(payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, self.success_payload())
        self.service_class.assert_called_once_with()
        self.service.compare.assert_called_once()
        uploaded_audio = self.service.compare.call_args.args[0]
        deadline = self.service.compare.call_args.kwargs['deadline']
        self.assertEqual(uploaded_audio.name, 'synthetic.wav')
        self.assertEqual(uploaded_audio.content_type, 'audio/wav')
        self.assertIsInstance(deadline, ComparisonDeadline)
        self.assertGreater(deadline.remaining_work_seconds(), 0)
        self.assert_product_rows_unchanged(before)

    @override_settings(
        REST_FRAMEWORK={
            **settings.REST_FRAMEWORK,
            'DEFAULT_THROTTLE_RATES': {
                **settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'],
                'consultation_comparison': '10/hour',
            },
        },
    )
    def test_eleventh_request_is_throttled_before_service_cost(self):
        with patch.object(
            ScopedRateThrottle,
            'THROTTLE_RATES',
            {'consultation_comparison': '10/hour'},
        ):
            responses = [
                self.post_as_admin(self.valid_payload())
                for _index in range(11)
            ]

        self.assertEqual(
            [response.status_code for response in responses[:10]],
            [200] * 10,
        )
        self.assertEqual(responses[10].status_code, 429)
        self.assertEqual(self.service_class.call_count, 10)
        self.assertEqual(self.service.compare.call_count, 10)

    def test_real_comparison_service_with_fake_providers_writes_nothing(self):
        self.service_class_patcher.stop()
        transcriber = Mock()
        transcriber.transcribe.return_value = ComparisonTranscription(
            segments=(
                ComparisonTranscriptSegment(
                    speaker='화자 1',
                    text='가상 상담 연락처는 010-1234-5678입니다.',
                    start_seconds=None,
                    end_seconds=None,
                ),
            ),
            model='fake-transcriber',
            latency_ms=1,
        )
        summary = ConsultationSummary(
            consultation_core=('가상 상담 핵심',),
            customer_priorities=(),
            items_to_confirm=(),
            next_actions=('다음 가상 상담 일정 확인',),
        )
        summarizers = []
        for provider in ('openai', 'anthropic'):
            summarizer = Mock()
            summarizer.provider = provider
            summarizer.summarize.return_value = ComparisonSummaryResult(
                summary=summary,
                model=f'fake-{provider}',
                latency_ms=2,
                input_tokens=3,
                output_tokens=4,
            )
            summarizers.append(summarizer)
        service = ConsultationComparisonService(
            transcriber=transcriber,
            summarizers=tuple(summarizers),
            shuffle=lambda rows: None,
        )
        before = {
            'recordings': ConsultationRecording.objects.count(),
            'memos': CustomerMemo.objects.count(),
            'usage': UsageMeter.objects.count(),
            'orders': PaymentOrder.objects.count(),
        }
        payload = {
            'audio': SimpleUploadedFile(
                'synthetic.wav',
                make_wav(),
                content_type='audio/wav',
            ),
            'synthetic_confirmed': True,
        }

        with patch(
            'inpa.admin_console.views.ConsultationComparisonService',
            return_value=service,
        ), patch(
            'inpa.consultations.services.get_recording_storage',
        ) as storage_factory:
            response = self.post_as_admin(payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data['transcript']['segments'][0],
            {
                'speaker': '화자 1',
                'text': '가상 상담 연락처는 [전화_1]입니다.',
                'start_seconds': None,
                'end_seconds': None,
            },
        )
        self.assertEqual(
            [result['status'] for result in response.data['results']],
            ['success', 'success'],
        )
        transcriber.transcribe.assert_called_once()
        for summarizer in summarizers:
            summarizer.summarize.assert_called_once_with(
                '화자 1: 가상 상담 연락처는 [전화_1]입니다.',
            )
        storage_factory.assert_not_called()
        self.assert_product_rows_unchanged(before)

    def test_audio_error_returns_only_safe_code(self):
        self.service.compare.side_effect = ComparisonAudioError(
            'AUDIO_TOO_LARGE',
        )

        response = self.post_as_admin(self.valid_payload())

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'AUDIO_TOO_LARGE')
        self.assertNotIn('AUDIO_TOO_LARGE', response.data.get('detail', ''))

    def test_unknown_audio_error_code_uses_safe_fallback(self):
        unsafe_code = 'customer filename and content'
        self.service.compare.side_effect = ComparisonAudioError(unsafe_code)

        response = self.post_as_admin(self.valid_payload())

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'AUDIO_INVALID')
        self.assertNotIn(unsafe_code, str(response.data))

    def test_transcription_failure_is_mapped_to_safe_retry_response(self):
        unsafe_code = 'TRANSCRIPT: customer phone 010-1234-5678'
        self.service.compare.side_effect = ComparisonProviderFailure(
            unsafe_code,
        )

        response = self.post_as_admin(self.valid_payload())

        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.data,
            {
                'code': 'TRANSCRIPTION_FAILED',
                'detail': (
                    '음성을 글로 바꾸는 단계를 다시 시작해 주세요.'
                ),
            },
        )
        self.assertNotIn(unsafe_code, str(response.data))

    def test_unknown_transcription_outcome_is_mapped_to_safe_response(self):
        unsafe_code = 'timeout included customer content'
        self.service.compare.side_effect = ComparisonOutcomeUnknown(
            unsafe_code,
        )

        response = self.post_as_admin(self.valid_payload())

        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.data,
            {
                'code': 'TRANSCRIPTION_OUTCOME_UNKNOWN',
                'detail': (
                    '처리 상태를 확인한 뒤 새 비교를 시작해 주세요.'
                ),
            },
        )
        self.assertNotIn(unsafe_code, str(response.data))

    def test_summary_side_failure_stays_inside_success_payload(self):
        payload = self.success_payload()
        payload['results'][0] = {
            'slot': 'A',
            'provider': 'openai',
            'model': '',
            'status': 'failed',
            'summary': None,
            'latency_ms': 0,
            'input_tokens': 0,
            'output_tokens': 0,
            'error_code': 'SUMMARY_FAILED',
        }
        self.service.compare.return_value = payload

        response = self.post_as_admin(self.valid_payload())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, payload)
