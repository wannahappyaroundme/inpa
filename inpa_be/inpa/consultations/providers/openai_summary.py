import json
import time
from dataclasses import dataclass

import openai
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from inpa.consultations.summary_schema import (
    ConsultationSummary,
    InvalidSummary,
    OPENAI_SUMMARY_JSON_SCHEMA,
)

from .anthropic_summary import SYSTEM_PROMPT, SummaryProviderResult
from .base import (
    ExplicitProviderNonReceipt,
    SpeechProviderProtocolError,
    SpeechSubmitOutcomeUnknown,
    SummaryOutcomeUnknown,
)
from .comparison_base import root_is_connect_error


@dataclass(frozen=True)
class OpenAITranscriptionResult:
    transcript: str
    model: str
    latency_ms: int


def _elapsed_ms(started, clock):
    return max(0, int(round((clock() - started) * 1_000)))


class OpenAIConsultationTranscriber:
    def __init__(self, client=None, clock=None):
        if not settings.OPENAI_CONSULTATION_TRANSCRIPTION_MODEL:
            raise ImproperlyConfigured(
                'OPENAI_CONSULTATION_TRANSCRIPTION_MODEL is required',
            )
        if client is None and not settings.OPENAI_API_KEY:
            raise ImproperlyConfigured('OPENAI_API_KEY is required')
        self.client = client or openai.OpenAI(
            api_key=settings.OPENAI_API_KEY,
            max_retries=0,
            timeout=settings.CONSULTATION_AI_REQUEST_TIMEOUT_SECONDS,
        )
        self.clock = clock or time.monotonic

    def transcribe(self, audio_file):
        if not hasattr(audio_file, 'read'):
            raise SpeechProviderProtocolError(
                'TRANSCRIPTION_FILE_UNAVAILABLE',
            )
        try:
            audio_file.seek(0)
        except (AttributeError, OSError):
            pass
        started = self.clock()
        try:
            response = self.client.audio.transcriptions.create(
                file=audio_file,
                model=settings.OPENAI_CONSULTATION_TRANSCRIPTION_MODEL,
                response_format='diarized_json',
                chunking_strategy='auto',
                language='ko',
            )
        except openai.APITimeoutError:
            raise SpeechSubmitOutcomeUnknown(
                'TRANSCRIPTION_TIMEOUT',
            ) from None
        except openai.APIConnectionError as exc:
            if root_is_connect_error(exc):
                raise ExplicitProviderNonReceipt(
                    'TRANSCRIPTION_CONNECT_FAILED',
                ) from None
            raise SpeechSubmitOutcomeUnknown(
                'TRANSCRIPTION_OUTCOME_UNKNOWN',
            ) from None
        except openai.OpenAIError:
            raise SpeechProviderProtocolError(
                'TRANSCRIPTION_FAILED',
            ) from None
        except OSError:
            raise SpeechProviderProtocolError(
                'TRANSCRIPTION_FILE_UNAVAILABLE',
            ) from None
        except Exception:
            raise SpeechProviderProtocolError(
                'TRANSCRIPTION_FAILED',
            ) from None

        raw_segments = getattr(response, 'segments', None)
        if not isinstance(raw_segments, (list, tuple)):
            raise SpeechProviderProtocolError(
                'TRANSCRIPTION_RESPONSE_INVALID',
            )
        speakers = {}
        lines = []
        try:
            for segment in raw_segments:
                text = segment.text.strip()
                if not text:
                    continue
                speaker = segment.speaker
                if not isinstance(speaker, str) or not speaker.strip():
                    raise ValueError
                if speaker not in speakers:
                    speakers[speaker] = f'화자 {len(speakers) + 1}'
                lines.append(f'[{speakers[speaker]}] {text}')
        except (AttributeError, TypeError, ValueError):
            raise SpeechProviderProtocolError(
                'TRANSCRIPTION_RESPONSE_INVALID',
            ) from None
        if not lines:
            raise SpeechProviderProtocolError('TRANSCRIPT_EMPTY')
        return OpenAITranscriptionResult(
            transcript='\n'.join(lines),
            model=settings.OPENAI_CONSULTATION_TRANSCRIPTION_MODEL,
            latency_ms=_elapsed_ms(started, self.clock),
        )


class OpenAIConsultationSummarizer:
    def __init__(self, client=None, clock=None):
        if not settings.OPENAI_CONSULTATION_SUMMARY_MODEL:
            raise ImproperlyConfigured(
                'OPENAI_CONSULTATION_SUMMARY_MODEL is required',
            )
        if client is None and not settings.OPENAI_API_KEY:
            raise ImproperlyConfigured('OPENAI_API_KEY is required')
        self.client = client or openai.OpenAI(
            api_key=settings.OPENAI_API_KEY,
            max_retries=0,
            timeout=settings.CONSULTATION_AI_REQUEST_TIMEOUT_SECONDS,
        )
        self.clock = clock or time.monotonic

    def summarize(self, masked_transcript):
        if not isinstance(masked_transcript, str) or not masked_transcript:
            raise InvalidSummary('MASKED_TRANSCRIPT_EMPTY')
        started = self.clock()
        try:
            response = self.client.responses.create(
                model=settings.OPENAI_CONSULTATION_SUMMARY_MODEL,
                instructions=SYSTEM_PROMPT,
                input=masked_transcript,
                text={
                    'format': {
                        'type': 'json_schema',
                        'name': 'consultation_summary',
                        'strict': True,
                        'schema': OPENAI_SUMMARY_JSON_SCHEMA,
                    },
                },
                max_output_tokens=2_500,
                store=False,
            )
        except openai.APITimeoutError:
            raise SummaryOutcomeUnknown('SUMMARY_TIMEOUT') from None
        except openai.APIConnectionError as exc:
            if root_is_connect_error(exc):
                raise ExplicitProviderNonReceipt(
                    'SUMMARY_CONNECT_FAILED',
                ) from None
            raise SummaryOutcomeUnknown('SUMMARY_OUTCOME_UNKNOWN') from None
        except openai.OpenAIError:
            raise InvalidSummary('SUMMARY_PROVIDER_FAILED') from None
        except Exception:
            raise InvalidSummary('SUMMARY_PROVIDER_FAILED') from None

        try:
            payload = json.loads(response.output_text)
            summary = ConsultationSummary.from_payload(payload)
            input_tokens = max(0, int(response.usage.input_tokens))
            output_tokens = max(0, int(response.usage.output_tokens))
            model = str(response.model)
        except (AttributeError, TypeError, ValueError, InvalidSummary):
            raise InvalidSummary('SUMMARY_RESPONSE_INVALID') from None
        return SummaryProviderResult(
            summary=summary,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
            latency_ms=_elapsed_ms(started, self.clock),
        )
