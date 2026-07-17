"""Evaluator-only OpenAI structured extraction.

The production import path remains Claude-only. This module is loaded by the
private evaluation adapter and imports the OpenAI SDK only at call time.
"""

from __future__ import annotations

import importlib
import logging
import os
import time
from contextlib import contextmanager

from pydantic import ValidationError

from .import_claude import (
    SYSTEM_PROMPT,
    ClaudeExtractionPayload,
    ExtractionFailure,
    ExtractionResult,
    _numeric_usage,
    _request_content,
    assert_provider_payload_pii_safe,
    provider_grounding_texts,
)


_RETRY_DELAYS_SECONDS = (1, 2, 4)
_MAX_OUTPUT_TOKENS = 8192


@contextmanager
def _private_provider_logging_guard():
    """Suppress SDK/HTTP request logs and restore the global threshold."""
    previous_disable = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        yield
    finally:
        logging.disable(previous_disable)


def _status_code(exc):
    value = getattr(exc, 'status_code', None)
    return value if type(value) is int else None


def _is_retryable(exc, openai):
    retryable_types = tuple(
        error_type
        for error_type in (
            getattr(openai, 'APITimeoutError', None),
            getattr(openai, 'APIConnectionError', None),
            getattr(openai, 'RateLimitError', None),
            getattr(openai, 'InternalServerError', None),
        )
        if isinstance(error_type, type)
    )
    status_code = _status_code(exc)
    return (
        (retryable_types and isinstance(exc, retryable_types))
        or status_code == 429
        or (status_code is not None and 500 <= status_code <= 599)
    )


def _failure_code(exc, openai):
    status_code = _status_code(exc)
    timeout_types = tuple(
        error_type
        for error_type in (
            getattr(openai, 'APITimeoutError', None),
            getattr(openai, 'APIConnectionError', None),
        )
        if isinstance(error_type, type)
    )
    if status_code == 429:
        return 'PROVIDER_RATE_LIMITED'
    if (
        (timeout_types and isinstance(exc, timeout_types))
        or (status_code is not None and status_code >= 500)
    ):
        return 'PROVIDER_UNAVAILABLE'
    return 'PROVIDER_REQUEST_REJECTED'


def _call_with_retry(*, client, openai, model, masked_lines, candidates,
                     schema_version):
    request_content = _request_content(
        masked_lines, candidates, schema_version)
    for attempt in range(len(_RETRY_DELAYS_SECONDS) + 1):
        usage = None
        try:
            with _private_provider_logging_guard():
                response = client.responses.parse(
                    model=model,
                    input=[
                        {'role': 'system', 'content': SYSTEM_PROMPT},
                        {'role': 'user', 'content': request_content},
                    ],
                    max_output_tokens=_MAX_OUTPUT_TOKENS,
                    text_format=ClaudeExtractionPayload,
                    store=False,
                )
            usage = getattr(response, 'usage', None)
            parsed = getattr(response, 'output_parsed', None)
            if parsed is None:
                raise ExtractionFailure('SCHEMA_INVALID', usage=usage)
            if not isinstance(parsed, ClaudeExtractionPayload):
                parsed = ClaudeExtractionPayload.model_validate(parsed)
            if parsed.schema_version != schema_version:
                raise ExtractionFailure(
                    'SCHEMA_VERSION_MISMATCH', usage=usage)
            return parsed, usage
        except ExtractionFailure:
            raise
        except ValidationError:
            raise ExtractionFailure('SCHEMA_INVALID', usage=usage) from None
        except Exception as exc:
            if (_is_retryable(exc, openai)
                    and attempt < len(_RETRY_DELAYS_SECONDS)):
                time.sleep(_RETRY_DELAYS_SECONDS[attempt])
                continue
            raise ExtractionFailure(
                _failure_code(exc, openai),
                error_type=type(exc).__name__,
            ) from None
    raise ExtractionFailure('PROVIDER_UNAVAILABLE')


def extract(masked_lines, candidates, schema_version):
    """Extract one non-persisted draft for private comparison only."""
    started_at = time.monotonic()
    model = os.environ.get('OPENAI_EVAL_MODEL', '').strip()
    usage_values = _numeric_usage(None)
    try:
        api_key = os.environ.get('OPENAI_EVAL_API_KEY', '').strip()
        if not api_key:
            raise ExtractionFailure('API_KEY_NOT_CONFIGURED')
        if not model:
            raise ExtractionFailure('MODEL_NOT_CONFIGURED')
        try:
            openai = importlib.import_module('openai')
        except ImportError:
            raise ExtractionFailure('PROVIDER_PACKAGE_MISSING') from None

        client = openai.OpenAI(api_key=api_key, max_retries=0)
        parsed, usage = _call_with_retry(
            client=client,
            openai=openai,
            model=model,
            masked_lines=masked_lines,
            candidates=candidates,
            schema_version=schema_version,
        )
        usage_values = _numeric_usage(usage)
        payload = parsed.model_dump(mode='json')
        assert_provider_payload_pii_safe(
            payload,
            provider_grounding_texts(masked_lines, candidates),
        )
    except ExtractionFailure as exc:
        exc.attach_observation(
            model_id=model,
            usage=usage_values,
            latency_ms=max(0, int((time.monotonic() - started_at) * 1000)),
        )
        raise

    return ExtractionResult(
        payload=payload,
        model_id=model,
        input_tokens=usage_values['input_tokens'],
        output_tokens=usage_values['output_tokens'],
        cache_read_input_tokens=usage_values['cache_read_input_tokens'],
        cache_creation_input_tokens=(
            usage_values['cache_creation_input_tokens']),
        latency_ms=max(0, int((time.monotonic() - started_at) * 1000)),
    )
