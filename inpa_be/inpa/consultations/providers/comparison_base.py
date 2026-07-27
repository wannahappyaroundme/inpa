import time
from dataclasses import dataclass
from typing import Callable, Sequence, TypeVar

import httpx
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from inpa.consultations.summary_schema import ConsultationSummary

from .base import ExplicitProviderNonReceipt


COMPARISON_CONNECT_BACKOFF_SECONDS = (1, 2, 4)
COMPARISON_PROVIDER_ATTEMPTS = len(COMPARISON_CONNECT_BACKOFF_SECONDS) + 1
COMPARISON_WORKER_CEILING_SECONDS = 120.0


class ComparisonProviderFailure(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class ComparisonOutcomeUnknown(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ComparisonTranscriptSegment:
    speaker: str
    text: str
    start_seconds: float | None
    end_seconds: float | None


@dataclass(frozen=True)
class ComparisonTranscription:
    segments: Sequence[ComparisonTranscriptSegment]
    model: str
    latency_ms: int


@dataclass(frozen=True)
class ComparisonSummaryResult:
    summary: ConsultationSummary
    model: str
    latency_ms: int
    input_tokens: int
    output_tokens: int


Result = TypeVar('Result')


def comparison_request_budget_seconds() -> float:
    connect_and_pool = (
        settings.CONSULTATION_COMPARISON_CONNECT_TIMEOUT_SECONDS
        + settings.CONSULTATION_COMPARISON_POOL_TIMEOUT_SECONDS
    )
    stage_before_read = (
        COMPARISON_PROVIDER_ATTEMPTS * connect_and_pool
        + settings.CONSULTATION_COMPARISON_WRITE_TIMEOUT_SECONDS
        + sum(COMPARISON_CONNECT_BACKOFF_SECONDS)
    )
    return (
        stage_before_read
        + settings.CONSULTATION_COMPARISON_TRANSCRIPTION_READ_TIMEOUT_SECONDS
        + stage_before_read
        + settings.CONSULTATION_COMPARISON_SUMMARY_READ_TIMEOUT_SECONDS
    )


def comparison_http_timeout(*, read_seconds: float) -> httpx.Timeout:
    values = (
        settings.CONSULTATION_COMPARISON_CONNECT_TIMEOUT_SECONDS,
        read_seconds,
        settings.CONSULTATION_COMPARISON_WRITE_TIMEOUT_SECONDS,
        settings.CONSULTATION_COMPARISON_POOL_TIMEOUT_SECONDS,
    )
    if any(value <= 0 for value in values):
        raise ImproperlyConfigured(
            'Consultation comparison timeouts must be positive',
        )
    if comparison_request_budget_seconds() >= COMPARISON_WORKER_CEILING_SECONDS:
        raise ImproperlyConfigured(
            'Consultation comparison request budget must stay below 120 seconds',
        )
    return httpx.Timeout(
        connect=values[0],
        read=values[1],
        write=values[2],
        pool=values[3],
    )


def retry_explicit_nonreceipt(
    operation: Callable[[], Result],
    sleep: Callable[[float], None] = time.sleep,
) -> Result:
    delays = COMPARISON_CONNECT_BACKOFF_SECONDS
    for attempt in range(len(delays) + 1):
        try:
            return operation()
        except ExplicitProviderNonReceipt:
            if attempt == len(delays):
                raise
            sleep(delays[attempt])
    raise AssertionError('unreachable')


def root_is_connect_error(exc: BaseException) -> bool:
    current = exc
    seen = set()
    while current is not None and id(current) not in seen:
        if isinstance(current, httpx.TransportError):
            return isinstance(current, httpx.ConnectError)
        seen.add(id(current))
        current = current.__cause__
    return False


def elapsed_milliseconds(started: float, clock) -> int:
    return max(0, round((clock() - started) * 1_000))
