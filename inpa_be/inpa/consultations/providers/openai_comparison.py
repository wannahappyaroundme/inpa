import json
import time
from pathlib import Path

import openai
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from inpa.consultations.summary_schema import (
    SUMMARY_JSON_SCHEMA,
    ConsultationSummary,
    InvalidSummary,
)

from .anthropic_summary import SYSTEM_PROMPT
from .base import ExplicitProviderNonReceipt
from .comparison_base import (
    ComparisonOutcomeUnknown,
    ComparisonProviderFailure,
    ComparisonSummaryResult,
    ComparisonTranscriptSegment,
    ComparisonTranscription,
    comparison_http_timeout,
    elapsed_milliseconds,
    retry_explicit_nonreceipt,
    root_is_connect_error,
)


class OpenAIComparisonTranscriber:
    def __init__(self, client=None, sleep=None, clock=None):
        if not settings.OPENAI_TRANSCRIPTION_MODEL:
            raise ImproperlyConfigured(
                'OPENAI_TRANSCRIPTION_MODEL is required',
            )
        if client is None and not settings.OPENAI_API_KEY:
            raise ImproperlyConfigured('OPENAI_API_KEY is required')
        self.client = client or openai.OpenAI(
            api_key=settings.OPENAI_API_KEY,
            max_retries=0,
            timeout=comparison_http_timeout(
                read_seconds=(
                    settings
                    .CONSULTATION_COMPARISON_TRANSCRIPTION_READ_TIMEOUT_SECONDS
                ),
            ),
        )
        self.sleep = sleep or time.sleep
        self.clock = clock or time.monotonic

    def _request(self, path: Path):
        try:
            with path.open('rb') as audio_file:
                return self.client.audio.transcriptions.create(
                    file=audio_file,
                    model=settings.OPENAI_TRANSCRIPTION_MODEL,
                    response_format='diarized_json',
                    chunking_strategy='auto',
                    language='ko',
                )
        except openai.APITimeoutError:
            raise ComparisonOutcomeUnknown(
                'TRANSCRIPTION_TIMEOUT',
            ) from None
        except openai.APIConnectionError as exc:
            if root_is_connect_error(exc):
                raise ExplicitProviderNonReceipt(
                    'TRANSCRIPTION_CONNECT_FAILED',
                ) from None
            raise ComparisonOutcomeUnknown(
                'TRANSCRIPTION_OUTCOME_UNKNOWN',
            ) from None
        except openai.OpenAIError:
            raise ComparisonProviderFailure(
                'TRANSCRIPTION_FAILED',
            ) from None
        except OSError:
            raise ComparisonProviderFailure(
                'TRANSCRIPTION_FILE_UNAVAILABLE',
            ) from None
        except Exception:
            raise ComparisonProviderFailure(
                'TRANSCRIPTION_FAILED',
            ) from None

    def transcribe(self, path: Path) -> ComparisonTranscription:
        started = self.clock()
        try:
            response = retry_explicit_nonreceipt(
                lambda: self._request(path),
                sleep=self.sleep,
            )
        except ExplicitProviderNonReceipt:
            raise ComparisonProviderFailure(
                'TRANSCRIPTION_CONNECT_FAILED',
            ) from None

        raw_segments = getattr(response, 'segments', None)
        if not isinstance(raw_segments, (list, tuple)):
            raise ComparisonProviderFailure(
                'TRANSCRIPTION_RESPONSE_INVALID',
            )

        speakers = {}
        segments = []
        try:
            for raw_segment in raw_segments:
                text = raw_segment.text.strip()
                if not text:
                    continue
                raw_speaker = raw_segment.speaker
                if (
                    not isinstance(raw_speaker, str)
                    or not raw_speaker.strip()
                ):
                    raise ValueError
                if raw_speaker not in speakers:
                    speakers[raw_speaker] = f'화자 {len(speakers) + 1}'
                start = raw_segment.start
                end = raw_segment.end
                segments.append(ComparisonTranscriptSegment(
                    speaker=speakers[raw_speaker],
                    text=text,
                    start_seconds=None if start is None else float(start),
                    end_seconds=None if end is None else float(end),
                ))
        except (AttributeError, TypeError, ValueError):
            raise ComparisonProviderFailure(
                'TRANSCRIPTION_RESPONSE_INVALID',
            ) from None

        if not segments:
            raise ComparisonProviderFailure('TRANSCRIPT_EMPTY')
        return ComparisonTranscription(
            segments=tuple(segments),
            model=settings.OPENAI_TRANSCRIPTION_MODEL,
            latency_ms=elapsed_milliseconds(started, self.clock),
        )


class OpenAIComparisonSummarizer:
    def __init__(self, client=None, sleep=None, clock=None):
        if not settings.OPENAI_COMPARISON_MODEL:
            raise ImproperlyConfigured(
                'OPENAI_COMPARISON_MODEL is required',
            )
        if client is None and not settings.OPENAI_API_KEY:
            raise ImproperlyConfigured('OPENAI_API_KEY is required')
        self.client = client or openai.OpenAI(
            api_key=settings.OPENAI_API_KEY,
            max_retries=0,
            timeout=comparison_http_timeout(
                read_seconds=(
                    settings.CONSULTATION_COMPARISON_SUMMARY_READ_TIMEOUT_SECONDS
                ),
            ),
        )
        self.sleep = sleep or time.sleep
        self.clock = clock or time.monotonic

    def _request(self, masked_transcript: str):
        try:
            return self.client.responses.create(
                model=settings.OPENAI_COMPARISON_MODEL,
                instructions=SYSTEM_PROMPT,
                input=masked_transcript,
                text={
                    'format': {
                        'type': 'json_schema',
                        'name': 'consultation_summary',
                        'strict': True,
                        'schema': SUMMARY_JSON_SCHEMA,
                    },
                },
                max_output_tokens=2_500,
                store=False,
            )
        except openai.APITimeoutError:
            raise ComparisonOutcomeUnknown('SUMMARY_TIMEOUT') from None
        except openai.APIConnectionError as exc:
            if root_is_connect_error(exc):
                raise ExplicitProviderNonReceipt(
                    'SUMMARY_CONNECT_FAILED',
                ) from None
            raise ComparisonOutcomeUnknown(
                'SUMMARY_OUTCOME_UNKNOWN',
            ) from None
        except openai.OpenAIError:
            raise ComparisonProviderFailure('SUMMARY_FAILED') from None
        except Exception:
            raise ComparisonProviderFailure('SUMMARY_FAILED') from None

    def summarize(self, masked_transcript: str) -> ComparisonSummaryResult:
        if not isinstance(masked_transcript, str) or not masked_transcript:
            raise ComparisonProviderFailure('MASKED_TRANSCRIPT_EMPTY')
        started = self.clock()
        try:
            response = retry_explicit_nonreceipt(
                lambda: self._request(masked_transcript),
                sleep=self.sleep,
            )
        except ExplicitProviderNonReceipt:
            raise ComparisonProviderFailure(
                'SUMMARY_CONNECT_FAILED',
            ) from None

        try:
            payload = json.loads(response.output_text)
            summary = ConsultationSummary.from_payload(payload)
            input_tokens = max(0, int(response.usage.input_tokens))
            output_tokens = max(0, int(response.usage.output_tokens))
            model = str(response.model)
        except (AttributeError, TypeError, ValueError, InvalidSummary):
            raise ComparisonProviderFailure('SUMMARY_INVALID') from None
        return ComparisonSummaryResult(
            summary=summary,
            model=model,
            latency_ms=elapsed_milliseconds(started, self.clock),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
