import json
import time

import anthropic
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
    comparison_http_timeout,
    elapsed_milliseconds,
    retry_explicit_nonreceipt,
    root_is_connect_error,
)


class AnthropicComparisonSummarizer:
    def __init__(self, client=None, sleep=None, clock=None):
        if not settings.ANTHROPIC_COMPARISON_MODEL:
            raise ImproperlyConfigured(
                'ANTHROPIC_COMPARISON_MODEL is required',
            )
        if client is None and not settings.ANTHROPIC_API_KEY:
            raise ImproperlyConfigured('ANTHROPIC_API_KEY is required')
        self.client = client or anthropic.Anthropic(
            api_key=settings.ANTHROPIC_API_KEY,
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
            return self.client.messages.create(
                model=settings.ANTHROPIC_COMPARISON_MODEL,
                max_tokens=2_500,
                system=SYSTEM_PROMPT,
                messages=[{
                    'role': 'user',
                    'content': masked_transcript,
                }],
                output_config={
                    'format': {
                        'type': 'json_schema',
                        'schema': SUMMARY_JSON_SCHEMA,
                    },
                },
            )
        except anthropic.APITimeoutError:
            raise ComparisonOutcomeUnknown('SUMMARY_TIMEOUT') from None
        except anthropic.APIConnectionError as exc:
            if root_is_connect_error(exc):
                raise ExplicitProviderNonReceipt(
                    'SUMMARY_CONNECT_FAILED',
                ) from None
            raise ComparisonOutcomeUnknown(
                'SUMMARY_OUTCOME_UNKNOWN',
            ) from None
        except anthropic.AnthropicError:
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

        if response.stop_reason in {'refusal', 'max_tokens'}:
            code = (
                'SUMMARY_REFUSED'
                if response.stop_reason == 'refusal'
                else 'SUMMARY_TRUNCATED'
            )
            raise ComparisonProviderFailure(code)
        try:
            text = ''.join(
                block.text
                for block in response.content
                if getattr(block, 'type', None) == 'text'
            )
            payload = json.loads(text)
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
