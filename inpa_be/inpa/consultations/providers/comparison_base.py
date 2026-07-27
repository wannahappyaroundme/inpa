import time
from dataclasses import dataclass
from typing import Callable, Sequence, TypeVar

import httpx

from inpa.consultations.summary_schema import ConsultationSummary

from .base import ExplicitProviderNonReceipt


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


def retry_explicit_nonreceipt(
    operation: Callable[[], Result],
    sleep: Callable[[float], None] = time.sleep,
) -> Result:
    delays = (1, 2, 4)
    for attempt in range(len(delays) + 1):
        try:
            return operation()
        except ExplicitProviderNonReceipt:
            if attempt == len(delays):
                raise
            sleep(delays[attempt])
    raise AssertionError('unreachable')


def root_is_connect_error(exc: BaseException) -> bool:
    root = exc
    seen = set()
    while root.__cause__ is not None and id(root) not in seen:
        seen.add(id(root))
        root = root.__cause__
    return isinstance(root, httpx.ConnectError)


def elapsed_milliseconds(started: float, clock) -> int:
    return max(0, round((clock() - started) * 1_000))
