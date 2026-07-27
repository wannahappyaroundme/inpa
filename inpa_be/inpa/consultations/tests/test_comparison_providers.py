import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import anthropic
import httpcore
import httpx
import openai
from django.test import SimpleTestCase, override_settings

from inpa.consultations.providers.anthropic_comparison import (
    AnthropicComparisonSummarizer,
)
from inpa.consultations.providers.anthropic_summary import SYSTEM_PROMPT
from inpa.consultations.providers.base import ExplicitProviderNonReceipt
from inpa.consultations.providers.comparison_base import (
    COMPARISON_WORKER_CEILING_SECONDS,
    ComparisonOutcomeUnknown,
    ComparisonProviderFailure,
    comparison_request_budget_seconds,
    retry_explicit_nonreceipt,
)
from inpa.consultations.providers.openai_comparison import (
    OpenAIComparisonSummarizer,
    OpenAIComparisonTranscriber,
)
from inpa.consultations.summary_schema import SUMMARY_JSON_SCHEMA


def valid_payload():
    return {
        'consultation_core': ['월 납입액을 함께 확인함'],
        'customer_priorities': ['가족 보장을 중요하게 봄'],
        'items_to_confirm': ['보험료 금액 확인 필요'],
        'next_actions': ['다음 상담 날짜 확인'],
    }


class FakeSegment:
    def __init__(self, speaker, start, end, text):
        self.speaker = speaker
        self.start = start
        self.end = end
        self.text = text


class FakeDiarizedTranscript:
    def __init__(self, text, segments):
        self.text = text
        self.segments = segments


class FakeTranscriptions:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0
        self.kwargs = None

    def create(self, **kwargs):
        self.calls += 1
        self.kwargs = kwargs
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeResponses:
    def __init__(self, outcome):
        self.outcomes = (
            list(outcome)
            if isinstance(outcome, list)
            else [outcome]
        )
        self.calls = 0
        self.kwargs = None

    def create(self, **kwargs):
        self.calls += 1
        self.kwargs = kwargs
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeOpenAIClient:
    def __init__(self, *, transcription=None, transcription_outcomes=None):
        outcomes = (
            transcription_outcomes
            if transcription_outcomes is not None
            else [transcription]
        )
        self._transcriptions = FakeTranscriptions(outcomes)
        self.audio = SimpleNamespace(transcriptions=self._transcriptions)

    @property
    def transcription_kwargs(self):
        return self._transcriptions.kwargs


class FakeOpenAISummaryClient:
    last_format = None

    def __init__(self, payload=None, *, outcome=None):
        response = outcome or SimpleNamespace(
            output_text=json.dumps(
                payload if payload is not None else valid_payload(),
                ensure_ascii=False,
            ),
            model='openai-response-model',
            usage=SimpleNamespace(input_tokens=101, output_tokens=41),
        )
        self.responses = FakeResponses(response)

    def capture_format(self):
        type(self).last_format = self.responses.kwargs['text']['format']


class FakeMessages:
    def __init__(self, outcome):
        self.outcomes = (
            list(outcome)
            if isinstance(outcome, list)
            else [outcome]
        )
        self.calls = 0
        self.kwargs = None

    def create(self, **kwargs):
        self.calls += 1
        self.kwargs = kwargs
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeAnthropicClient:
    last_format = None

    def __init__(self, payload=None, *, outcome=None, stop_reason='end_turn'):
        response = outcome or SimpleNamespace(
            content=[
                SimpleNamespace(
                    type='text',
                    text=json.dumps(
                        payload if payload is not None else valid_payload(),
                        ensure_ascii=False,
                    ),
                ),
            ],
            stop_reason=stop_reason,
            model='anthropic-response-model',
            usage=SimpleNamespace(input_tokens=103, output_tokens=43),
        )
        self.messages = FakeMessages(response)

    def capture_format(self):
        type(self).last_format = self.messages.kwargs[
            'output_config'
        ]['format']


def wrapped_provider_connection_error(provider_error_type):
    request = httpx.Request('POST', 'https://provider.invalid')
    try:
        raise httpcore.ConnectError('dns or tcp connect failed')
    except httpcore.ConnectError as core_error:
        try:
            raise httpx.ConnectError(
                'httpx connect failed',
                request=request,
            ) from core_error
        except httpx.ConnectError as httpx_error:
            try:
                raise provider_error_type(request=request) from httpx_error
            except provider_error_type as wrapped:
                return wrapped


def wrapped_openai_read_error():
    request = httpx.Request('POST', 'https://provider.invalid')
    try:
        raise httpx.ReadError('ambiguous receipt', request=request)
    except httpx.ReadError as exc:
        try:
            raise openai.APIConnectionError(request=request) from exc
        except openai.APIConnectionError as wrapped:
            return wrapped


@override_settings(
    OPENAI_API_KEY='openai-test-key',
    OPENAI_TRANSCRIPTION_MODEL='transcription-model-from-env',
    OPENAI_COMPARISON_MODEL='openai-summary-model-from-env',
    ANTHROPIC_API_KEY='anthropic-test-key',
    ANTHROPIC_COMPARISON_MODEL='anthropic-summary-model-from-env',
    CONSULTATION_COMPARISON_CONNECT_TIMEOUT_SECONDS=2.0,
    CONSULTATION_COMPARISON_TRANSCRIPTION_READ_TIMEOUT_SECONDS=35.0,
    CONSULTATION_COMPARISON_SUMMARY_READ_TIMEOUT_SECONDS=25.0,
    CONSULTATION_COMPARISON_WRITE_TIMEOUT_SECONDS=5.0,
    CONSULTATION_COMPARISON_POOL_TIMEOUT_SECONDS=1.0,
)
class ComparisonProviderTests(SimpleTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.audio_path = Path(self.temp_dir.name) / 'synthetic.wav'
        self.audio_path.write_bytes(b'RIFF-synthetic-audio')

    def test_openai_transcriber_requests_diarized_korean_transcript(self):
        client = FakeOpenAIClient(
            transcription=FakeDiarizedTranscript(
                text='전체 대화',
                segments=[
                    FakeSegment('speaker_0', 0.0, 1.2, ' 안녕하세요 '),
                    FakeSegment('speaker_1', 1.3, 2.1, '반갑습니다'),
                    FakeSegment('speaker_0', 2.2, 3.0, '  다시 만났어요  '),
                    FakeSegment('speaker_1', 3.1, 3.2, '   '),
                ],
            ),
        )

        with patch(
            'inpa.consultations.providers.openai_comparison.time.monotonic',
            side_effect=(10.0, 10.123),
        ):
            result = OpenAIComparisonTranscriber(
                client=client,
            ).transcribe(self.audio_path)

        self.assertEqual(
            [row.speaker for row in result.segments],
            ['화자 1', '화자 2', '화자 1'],
        )
        self.assertEqual(
            [row.text for row in result.segments],
            ['안녕하세요', '반갑습니다', '다시 만났어요'],
        )
        self.assertEqual(result.segments[0].start_seconds, 0.0)
        self.assertEqual(result.segments[0].end_seconds, 1.2)
        self.assertEqual(result.model, 'transcription-model-from-env')
        self.assertEqual(result.latency_ms, 123)
        self.assertEqual(
            client.transcription_kwargs['response_format'],
            'diarized_json',
        )
        self.assertEqual(
            client.transcription_kwargs['chunking_strategy'],
            'auto',
        )
        self.assertEqual(client.transcription_kwargs['language'], 'ko')
        self.assertEqual(
            client.transcription_kwargs['model'],
            'transcription-model-from-env',
        )
        self.assertNotIn('prompt', client.transcription_kwargs)
        self.assertNotIn('logprobs', client.transcription_kwargs)
        self.assertNotIn(
            'timestamp_granularities',
            client.transcription_kwargs,
        )

    def test_openai_transcriber_rejects_empty_segments_with_safe_code(self):
        client = FakeOpenAIClient(
            transcription=FakeDiarizedTranscript(
                text='ignored aggregate text',
                segments=[FakeSegment('speaker_0', None, None, '   ')],
            ),
        )

        with self.assertRaises(ComparisonProviderFailure) as raised:
            OpenAIComparisonTranscriber(
                client=client,
            ).transcribe(self.audio_path)

        self.assertEqual(raised.exception.code, 'TRANSCRIPT_EMPTY')
        self.assertEqual(str(raised.exception), 'TRANSCRIPT_EMPTY')

    def test_both_summarizers_enforce_the_same_existing_schema(self):
        openai_client = FakeOpenAISummaryClient(valid_payload())
        anthropic_client = FakeAnthropicClient(valid_payload())

        openai_result = OpenAIComparisonSummarizer(
            client=openai_client,
        ).summarize('화자 1: 가림 전사문')
        anthropic_result = AnthropicComparisonSummarizer(
            client=anthropic_client,
        ).summarize('화자 1: 가림 전사문')
        openai_client.capture_format()
        anthropic_client.capture_format()

        self.assertEqual(openai_result.summary, anthropic_result.summary)
        self.assertEqual(
            FakeOpenAISummaryClient.last_format['schema'],
            SUMMARY_JSON_SCHEMA,
        )
        self.assertEqual(
            FakeAnthropicClient.last_format['schema'],
            SUMMARY_JSON_SCHEMA,
        )
        self.assertEqual(
            openai_client.responses.kwargs['instructions'],
            SYSTEM_PROMPT,
        )
        self.assertEqual(
            anthropic_client.messages.kwargs['system'],
            SYSTEM_PROMPT,
        )
        self.assertEqual(
            openai_client.responses.kwargs['input'],
            '화자 1: 가림 전사문',
        )
        self.assertEqual(
            anthropic_client.messages.kwargs['messages'],
            [{'role': 'user', 'content': '화자 1: 가림 전사문'}],
        )
        self.assertEqual(
            openai_client.responses.kwargs['max_output_tokens'],
            2_500,
        )
        self.assertEqual(
            anthropic_client.messages.kwargs['max_tokens'],
            2_500,
        )
        self.assertFalse(openai_client.responses.kwargs['store'])
        self.assertEqual(openai_result.input_tokens, 101)
        self.assertEqual(openai_result.output_tokens, 41)
        self.assertEqual(openai_result.model, 'openai-response-model')
        self.assertEqual(anthropic_result.input_tokens, 103)
        self.assertEqual(anthropic_result.output_tokens, 43)
        self.assertEqual(
            anthropic_result.model,
            'anthropic-response-model',
        )

    def test_retry_boundary_retries_only_explicit_nonreceipt(self):
        attempts = []
        sleeps = []

        def eventually_succeeds():
            attempts.append(len(attempts) + 1)
            if len(attempts) < 4:
                raise ExplicitProviderNonReceipt('CONNECT_FAILED')
            return 'received'

        result = retry_explicit_nonreceipt(
            eventually_succeeds,
            sleep=sleeps.append,
        )

        self.assertEqual(result, 'received')
        self.assertEqual(attempts, [1, 2, 3, 4])
        self.assertEqual(sleeps, [1, 2, 4])

        non_retry_attempts = []

        def unknown_outcome():
            non_retry_attempts.append(1)
            raise ComparisonOutcomeUnknown('OUTCOME_UNKNOWN')

        with self.assertRaises(ComparisonOutcomeUnknown):
            retry_explicit_nonreceipt(
                unknown_outcome,
                sleep=sleeps.append,
            )
        self.assertEqual(non_retry_attempts, [1])
        self.assertEqual(sleeps, [1, 2, 4])

    def test_openai_retries_only_root_connect_error(self):
        connection_error = wrapped_provider_connection_error(
            openai.APIConnectionError,
        )
        client = FakeOpenAIClient(
            transcription_outcomes=[
                connection_error,
                FakeDiarizedTranscript(
                    text='전체 대화',
                    segments=[
                        FakeSegment('speaker_0', 0.0, 1.0, '안녕하세요'),
                    ],
                ),
            ],
        )
        sleeps = []

        result = OpenAIComparisonTranscriber(
            client=client,
            sleep=sleeps.append,
        ).transcribe(self.audio_path)

        self.assertEqual(client._transcriptions.calls, 2)
        self.assertEqual(sleeps, [1])
        self.assertEqual(result.segments[0].text, '안녕하세요')

        read_error = wrapped_openai_read_error()
        no_retry_client = FakeOpenAIClient(
            transcription_outcomes=[read_error],
        )
        with self.assertRaises(ComparisonOutcomeUnknown) as raised:
            OpenAIComparisonTranscriber(
                client=no_retry_client,
                sleep=sleeps.append,
            ).transcribe(self.audio_path)
        self.assertEqual(
            raised.exception.code,
            'TRANSCRIPTION_OUTCOME_UNKNOWN',
        )
        self.assertEqual(no_retry_client._transcriptions.calls, 1)
        self.assertEqual(sleeps, [1])

    def test_openai_summary_retries_real_three_level_connect_chain(self):
        client = FakeOpenAISummaryClient()
        client.responses.outcomes.insert(
            0,
            wrapped_provider_connection_error(openai.APIConnectionError),
        )
        sleeps = []

        result = OpenAIComparisonSummarizer(
            client=client,
            sleep=sleeps.append,
        ).summarize('화자 1: 가림 전사문')

        self.assertEqual(result.model, 'openai-response-model')
        self.assertEqual(client.responses.calls, 2)
        self.assertEqual(sleeps, [1])

    def test_anthropic_summary_retries_real_three_level_connect_chain(self):
        client = FakeAnthropicClient()
        client.messages.outcomes.insert(
            0,
            wrapped_provider_connection_error(
                anthropic.APIConnectionError,
            ),
        )
        sleeps = []

        result = AnthropicComparisonSummarizer(
            client=client,
            sleep=sleeps.append,
        ).summarize('화자 1: 가림 전사문')

        self.assertEqual(result.model, 'anthropic-response-model')
        self.assertEqual(client.messages.calls, 2)
        self.assertEqual(sleeps, [1])

    def test_openai_timeout_is_unknown_and_never_retried(self):
        timeout = openai.APITimeoutError(
            request=httpx.Request('POST', 'https://provider.invalid'),
        )
        client = FakeOpenAIClient(transcription_outcomes=[timeout])

        with self.assertRaises(ComparisonOutcomeUnknown) as raised:
            OpenAIComparisonTranscriber(
                client=client,
                sleep=lambda delay: self.fail(f'unexpected sleep {delay}'),
            ).transcribe(self.audio_path)

        self.assertEqual(raised.exception.code, 'TRANSCRIPTION_TIMEOUT')
        self.assertEqual(client._transcriptions.calls, 1)

    def test_malformed_or_refused_summaries_are_final_safe_failures(self):
        openai_client = FakeOpenAISummaryClient(
            outcome=SimpleNamespace(
                output_text='{invalid',
                model='openai-response-model',
                usage=SimpleNamespace(input_tokens=1, output_tokens=1),
            ),
        )
        with self.assertRaises(ComparisonProviderFailure) as openai_raised:
            OpenAIComparisonSummarizer(
                client=openai_client,
            ).summarize('화자 1: 민감한 원문')
        self.assertEqual(openai_raised.exception.code, 'SUMMARY_INVALID')
        self.assertEqual(openai_client.responses.calls, 1)
        self.assertNotIn('민감한 원문', str(openai_raised.exception))

        anthropic_client = FakeAnthropicClient(
            valid_payload(),
            stop_reason='refusal',
        )
        with self.assertRaises(ComparisonProviderFailure) as anthropic_raised:
            AnthropicComparisonSummarizer(
                client=anthropic_client,
            ).summarize('화자 1: 민감한 원문')
        self.assertEqual(
            anthropic_raised.exception.code,
            'SUMMARY_REFUSED',
        )
        self.assertEqual(anthropic_client.messages.calls, 1)
        self.assertNotIn('민감한 원문', str(anthropic_raised.exception))

    def test_summary_timeouts_are_unknown_and_never_retried(self):
        openai_timeout = openai.APITimeoutError(
            request=httpx.Request('POST', 'https://provider.invalid'),
        )
        openai_client = FakeOpenAISummaryClient(outcome=openai_timeout)
        with self.assertRaises(ComparisonOutcomeUnknown) as openai_raised:
            OpenAIComparisonSummarizer(
                client=openai_client,
                sleep=lambda delay: self.fail(f'unexpected sleep {delay}'),
            ).summarize('화자 1: 가림 전사문')
        self.assertEqual(openai_raised.exception.code, 'SUMMARY_TIMEOUT')
        self.assertEqual(openai_client.responses.calls, 1)

        anthropic_timeout = anthropic.APITimeoutError(
            request=httpx.Request('POST', 'https://provider.invalid'),
        )
        anthropic_client = FakeAnthropicClient(outcome=anthropic_timeout)
        with self.assertRaises(ComparisonOutcomeUnknown) as anthropic_raised:
            AnthropicComparisonSummarizer(
                client=anthropic_client,
                sleep=lambda delay: self.fail(f'unexpected sleep {delay}'),
            ).summarize('화자 1: 가림 전사문')
        self.assertEqual(anthropic_raised.exception.code, 'SUMMARY_TIMEOUT')
        self.assertEqual(anthropic_client.messages.calls, 1)

    def test_request_budget_stays_below_worker_timeout_with_retry_backoff(self):
        self.assertEqual(comparison_request_budget_seconds(), 108.0)
        self.assertLess(
            comparison_request_budget_seconds(),
            COMPARISON_WORKER_CEILING_SECONDS,
        )

    def test_sdk_clients_receive_explicit_timeouts_and_disable_retries(self):
        with patch(
            'inpa.consultations.providers.openai_comparison.openai.OpenAI',
        ) as openai_factory:
            OpenAIComparisonTranscriber()
            OpenAIComparisonSummarizer()

        self.assertEqual(openai_factory.call_count, 2)
        expected_read_timeouts = (35.0, 25.0)
        for call, expected_read_timeout in zip(
            openai_factory.call_args_list,
            expected_read_timeouts,
        ):
            self.assertEqual(call.kwargs['max_retries'], 0)
            self.assertEqual(call.kwargs['api_key'], 'openai-test-key')
            timeout = call.kwargs['timeout']
            self.assertIsInstance(timeout, httpx.Timeout)
            self.assertEqual(timeout.connect, 2.0)
            self.assertEqual(timeout.read, expected_read_timeout)
            self.assertEqual(timeout.write, 5.0)
            self.assertEqual(timeout.pool, 1.0)

        with patch(
            'inpa.consultations.providers.anthropic_comparison.'
            'anthropic.Anthropic',
        ) as anthropic_factory:
            AnthropicComparisonSummarizer()

        anthropic_factory.assert_called_once()
        anthropic_kwargs = anthropic_factory.call_args.kwargs
        self.assertEqual(anthropic_kwargs['api_key'], 'anthropic-test-key')
        self.assertEqual(anthropic_kwargs['max_retries'], 0)
        timeout = anthropic_kwargs['timeout']
        self.assertIsInstance(timeout, httpx.Timeout)
        self.assertEqual(timeout.connect, 2.0)
        self.assertEqual(timeout.read, 25.0)
        self.assertEqual(timeout.write, 5.0)
        self.assertEqual(timeout.pool, 1.0)
