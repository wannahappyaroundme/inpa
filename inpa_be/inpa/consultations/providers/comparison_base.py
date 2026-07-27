import math
import time
from dataclasses import dataclass, field
from typing import Callable, Sequence, TypeVar

import httpx
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from inpa.consultations.summary_schema import ConsultationSummary

from .base import ExplicitProviderNonReceipt


COMPARISON_CONNECT_BACKOFF_SECONDS = (1, 2, 4)
COMPARISON_RESPONSE_RESERVE_SECONDS = 5.0
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
class ComparisonDeadline:
    expires_at: float
    response_reserve_seconds: float
    clock: Callable[[], float] = field(repr=False, compare=False)

    @classmethod
    def for_request(cls, *, clock=time.monotonic):
        total_seconds = float(
            settings.CONSULTATION_COMPARISON_REQUEST_DEADLINE_SECONDS
        )
        if (
            not math.isfinite(total_seconds)
            or total_seconds <= COMPARISON_RESPONSE_RESERVE_SECONDS
            or total_seconds >= COMPARISON_WORKER_CEILING_SECONDS
        ):
            raise ImproperlyConfigured(
                'Consultation comparison request deadline must be above '
                'the response reserve and below 120 seconds',
            )
        return cls.after(
            total_seconds,
            response_reserve_seconds=COMPARISON_RESPONSE_RESERVE_SECONDS,
            clock=clock,
        )

    @classmethod
    def after(
        cls,
        seconds: float,
        *,
        response_reserve_seconds: float = 0.0,
        clock=time.monotonic,
    ):
        seconds = float(seconds)
        response_reserve_seconds = float(response_reserve_seconds)
        if (
            not math.isfinite(seconds)
            or not math.isfinite(response_reserve_seconds)
            or seconds <= 0
            or response_reserve_seconds < 0
            or response_reserve_seconds >= seconds
        ):
            raise ValueError('COMPARISON_DEADLINE_INVALID')
        return cls(
            expires_at=clock() + seconds,
            response_reserve_seconds=response_reserve_seconds,
            clock=clock,
        )

    def remaining_request_seconds(self) -> float:
        return max(0.0, self.expires_at - self.clock())

    def remaining_work_seconds(
        self,
        *,
        extra_reserve_seconds: float = 0.0,
    ) -> float:
        extra_reserve_seconds = float(extra_reserve_seconds)
        if (
            not math.isfinite(extra_reserve_seconds)
            or extra_reserve_seconds < 0
        ):
            raise ValueError('COMPARISON_DEADLINE_RESERVE_INVALID')
        return max(
            0.0,
            self.expires_at
            - self.clock()
            - self.response_reserve_seconds
            - extra_reserve_seconds,
        )

    def require_work_time(self, *, code: str) -> float:
        remaining = self.remaining_work_seconds()
        if remaining <= 0:
            raise ComparisonOutcomeUnknown(code)
        return remaining


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


def comparison_http_timeout(*, read_seconds: float) -> httpx.Timeout:
    values = (
        settings.CONSULTATION_COMPARISON_CONNECT_TIMEOUT_SECONDS,
        read_seconds,
        settings.CONSULTATION_COMPARISON_WRITE_TIMEOUT_SECONDS,
        settings.CONSULTATION_COMPARISON_POOL_TIMEOUT_SECONDS,
    )
    if any(not math.isfinite(float(value)) or value <= 0 for value in values):
        raise ImproperlyConfigured(
            'Consultation comparison timeouts must be positive',
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
