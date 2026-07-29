import io
import json
from types import SimpleNamespace

import httpx
import openai
from django.test import SimpleTestCase, override_settings

from inpa.consultations.providers.base import (
    SpeechProviderProtocolError,
    SpeechSubmitOutcomeUnknown,
    SummaryOutcomeUnknown,
)
from inpa.consultations.providers.openai_summary import (
    OpenAIConsultationSummarizer,
    OpenAIConsultationTranscriber,
)
from inpa.consultations.summary_schema import (
    InvalidSummary,
    OPENAI_SUMMARY_JSON_SCHEMA,
)


TEST_PROVIDER_CREDENTIAL = 'unit-test-provider-credential'


def _valid_payload():
    return {
        'consultation_core': ['보장 내용을 함께 확인함'],
        'customer_priorities': ['가족 보장을 중요하게 봄'],
        'items_to_confirm': ['월 보험료 확인 필요'],
        'next_actions': ['다음 상담 날짜 확인'],
    }


class _Call:
    def __init__(self, outcome):
        self.outcome = outcome
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


class _Client:
    def __init__(self, *, transcription=None, summary=None):
        self.transcriptions = _Call(transcription)
        self.responses = _Call(summary)
        self.audio = SimpleNamespace(transcriptions=self.transcriptions)


@override_settings(
    OPENAI_API_KEY=TEST_PROVIDER_CREDENTIAL,
    OPENAI_TRANSCRIPTION_MODEL='transcription-model-from-env',
    OPENAI_CONSULTATION_TRANSCRIPTION_MODEL=(
        'consultation-transcription-model-from-env'
    ),
    OPENAI_CONSULTATION_SUMMARY_MODEL='summary-model-from-env',
    CONSULTATION_AI_REQUEST_TIMEOUT_SECONDS=180,
)
class OpenAIConsultationProviderTests(SimpleTestCase):
    def test_transcription_requests_diarized_korean_and_stable_speakers(self):
        response = SimpleNamespace(segments=[
            SimpleNamespace(
                speaker='speaker_0',
                start=0.0,
                end=1.2,
                text=' 안녕하세요 ',
            ),
            SimpleNamespace(
                speaker='speaker_1',
                start=1.3,
                end=2.2,
                text='보장 내용을 볼게요',
            ),
            SimpleNamespace(
                speaker='speaker_0',
                start=2.3,
                end=3.0,
                text='  네  ',
            ),
        ])
        client = _Client(transcription=response)
        clock = iter((10.0, 10.321))

        result = OpenAIConsultationTranscriber(
            client=client,
            clock=lambda: next(clock),
        ).transcribe(io.BytesIO(b'RIFF-synthetic'))

        self.assertEqual(
            result.transcript,
            '[화자 1] 안녕하세요\n'
            '[화자 2] 보장 내용을 볼게요\n'
            '[화자 1] 네',
        )
        self.assertEqual(
            result.model,
            'consultation-transcription-model-from-env',
        )
        self.assertEqual(result.latency_ms, 321)
        kwargs = client.transcriptions.kwargs
        self.assertEqual(
            kwargs['model'],
            'consultation-transcription-model-from-env',
        )
        self.assertEqual(kwargs['response_format'], 'diarized_json')
        self.assertEqual(kwargs['chunking_strategy'], 'auto')
        self.assertEqual(kwargs['language'], 'ko')

    def test_empty_or_malformed_diarization_is_rejected(self):
        for segments in (
            [],
            [SimpleNamespace(speaker='', start=0, end=1, text='내용')],
            [SimpleNamespace(speaker='speaker_0', start=0, end=1, text=' ')],
        ):
            with self.subTest(segments=segments):
                client = _Client(
                    transcription=SimpleNamespace(segments=segments),
                )
                with self.assertRaises(SpeechProviderProtocolError):
                    OpenAIConsultationTranscriber(
                        client=client,
                    ).transcribe(io.BytesIO(b'RIFF-synthetic'))

    def test_transcription_timeout_is_ambiguous_and_not_retried(self):
        timeout = openai.APITimeoutError(
            request=httpx.Request('POST', 'https://api.openai.com'),
        )
        client = _Client(transcription=timeout)

        with self.assertRaises(SpeechSubmitOutcomeUnknown):
            OpenAIConsultationTranscriber(
                client=client,
            ).transcribe(io.BytesIO(b'RIFF-synthetic'))

    def test_summary_uses_strict_schema_store_false_and_returns_usage(self):
        client = _Client(summary=SimpleNamespace(
            output_text=json.dumps(_valid_payload(), ensure_ascii=False),
            model='actual-openai-summary-model',
            usage=SimpleNamespace(input_tokens=120, output_tokens=45),
        ))
        clock = iter((20.0, 20.456))

        result = OpenAIConsultationSummarizer(
            client=client,
            clock=lambda: next(clock),
        ).summarize('[화자 1] [이름_1] 상담 내용')

        self.assertEqual(result.model, 'actual-openai-summary-model')
        self.assertEqual(result.input_tokens, 120)
        self.assertEqual(result.output_tokens, 45)
        self.assertEqual(result.latency_ms, 456)
        kwargs = client.responses.kwargs
        self.assertEqual(kwargs['model'], 'summary-model-from-env')
        self.assertFalse(kwargs['store'])
        self.assertEqual(kwargs['text']['format']['type'], 'json_schema')
        self.assertTrue(kwargs['text']['format']['strict'])
        self.assertEqual(
            kwargs['text']['format']['schema'],
            OPENAI_SUMMARY_JSON_SCHEMA,
        )
        item_schema = (
            kwargs['text']['format']['schema']['properties']
            ['consultation_core']['items']
        )
        self.assertNotIn('maxLength', item_schema)

    def test_summary_rejects_empty_input_and_invalid_output(self):
        client = _Client(summary=SimpleNamespace(
            output_text='not-json',
            model='actual-openai-summary-model',
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        ))
        summarizer = OpenAIConsultationSummarizer(client=client)

        with self.assertRaises(InvalidSummary):
            summarizer.summarize('')
        with self.assertRaises(InvalidSummary):
            summarizer.summarize('[화자 1] 상담 내용')

    def test_summary_timeout_is_ambiguous_and_not_retried(self):
        timeout = openai.APITimeoutError(
            request=httpx.Request('POST', 'https://api.openai.com'),
        )
        client = _Client(summary=timeout)

        with self.assertRaises(SummaryOutcomeUnknown):
            OpenAIConsultationSummarizer(
                client=client,
            ).summarize('[화자 1] 상담 내용')
