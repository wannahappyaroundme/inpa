"""One-shot, in-memory orchestration for synthetic consultation comparison."""

import random
from concurrent.futures import ThreadPoolExecutor

from inpa.consultations.comparison_audio import prepare_comparison_audio
from inpa.consultations.providers.anthropic_comparison import (
    AnthropicComparisonSummarizer,
)
from inpa.consultations.providers.comparison_base import (
    ComparisonOutcomeUnknown,
    ComparisonProviderFailure,
)
from inpa.consultations.providers.openai_comparison import (
    OpenAIComparisonSummarizer,
    OpenAIComparisonTranscriber,
)
from inpa.consultations.summary_schema import SECTION_KEYS
from inpa.consultations.transcript_mask import mask_transcript


SUMMARY_FAILURE_CODES = frozenset({
    'MASKED_TRANSCRIPT_EMPTY',
    'SUMMARY_CONNECT_FAILED',
    'SUMMARY_FAILED',
    'SUMMARY_INVALID',
    'SUMMARY_REFUSED',
    'SUMMARY_TRUNCATED',
})
SUMMARY_UNKNOWN_CODES = frozenset({
    'SUMMARY_OUTCOME_UNKNOWN',
    'SUMMARY_TIMEOUT',
})


def _safe_code(value, *, allowed, fallback):
    if not isinstance(value, str):
        return fallback
    normalized = value.upper()
    if (
        len(normalized) > 80
        or any(
            character not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_'
            for character in normalized
        )
        or normalized not in allowed
    ):
        return fallback
    return normalized


class ConsultationComparisonService:
    def __init__(self, transcriber=None, summarizers=None, shuffle=None):
        self.transcriber = transcriber or OpenAIComparisonTranscriber()
        if summarizers is None:
            summarizers = (
                OpenAIComparisonSummarizer(),
                AnthropicComparisonSummarizer(),
            )
        if len(summarizers) != 2:
            raise ValueError('COMPARISON_SUMMARIZER_COUNT_INVALID')
        self.summarizers = tuple(summarizers)
        self.shuffle = shuffle or random.shuffle

    def compare(self, uploaded_file):
        with prepare_comparison_audio(uploaded_file) as prepared_audio:
            transcription = self.transcriber.transcribe(prepared_audio.path)

            masked_segments = [
                {
                    'speaker': segment.speaker,
                    'text': mask_transcript(
                        segment.text,
                        known_names=(),
                    ).text,
                    'start_seconds': segment.start_seconds,
                    'end_seconds': segment.end_seconds,
                }
                for segment in transcription.segments
            ]
            masked_transcript = '\n'.join(
                f"{segment['speaker']}: {segment['text']}"
                for segment in masked_segments
            )
            results = self._summarize(masked_transcript)

        self.shuffle(results)
        for slot, result in zip(('A', 'B'), results):
            result['slot'] = slot
        return {
            'transcript': {'segments': masked_segments},
            'results': results,
        }

    def _summarize(self, masked_transcript):
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                (summarizer, executor.submit(
                    summarizer.summarize,
                    masked_transcript,
                ))
                for summarizer in self.summarizers
            ]
        return [
            self._summary_result(summarizer, future)
            for summarizer, future in futures
        ]

    @staticmethod
    def _provider_name(summarizer):
        provider = getattr(summarizer, 'provider', '')
        if provider in {'openai', 'anthropic'}:
            return provider
        if isinstance(summarizer, OpenAIComparisonSummarizer):
            return 'openai'
        if isinstance(summarizer, AnthropicComparisonSummarizer):
            return 'anthropic'
        raise ValueError('COMPARISON_PROVIDER_INVALID')

    def _summary_result(self, summarizer, future):
        provider = self._provider_name(summarizer)
        try:
            result = future.result()
        except ComparisonOutcomeUnknown as exc:
            return self._failure_result(
                provider,
                status='outcome_unknown',
                error_code=_safe_code(
                    exc.code,
                    allowed=SUMMARY_UNKNOWN_CODES,
                    fallback='SUMMARY_OUTCOME_UNKNOWN',
                ),
            )
        except ComparisonProviderFailure as exc:
            return self._failure_result(
                provider,
                status='failed',
                error_code=_safe_code(
                    exc.code,
                    allowed=SUMMARY_FAILURE_CODES,
                    fallback='SUMMARY_FAILED',
                ),
            )
        except Exception:
            return self._failure_result(
                provider,
                status='failed',
                error_code='SUMMARY_FAILED',
            )
        return {
            'slot': '',
            'provider': provider,
            'model': result.model,
            'status': 'success',
            'summary': {
                key: list(getattr(result.summary, key))
                for key in SECTION_KEYS
            },
            'latency_ms': result.latency_ms,
            'input_tokens': result.input_tokens,
            'output_tokens': result.output_tokens,
            'error_code': '',
        }

    @staticmethod
    def _failure_result(provider, *, status, error_code):
        return {
            'slot': '',
            'provider': provider,
            'model': '',
            'status': status,
            'summary': None,
            'latency_ms': 0,
            'input_tokens': 0,
            'output_tokens': 0,
            'error_code': error_code,
        }
