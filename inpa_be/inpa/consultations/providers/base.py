from dataclasses import dataclass
from typing import Literal


class SpeechProviderError(RuntimeError):
    pass


class SpeechProviderProtocolError(SpeechProviderError):
    pass


class SpeechProviderTemporaryError(SpeechProviderError):
    pass


class ExplicitProviderNonReceipt(SpeechProviderError):
    pass


class SpeechSubmitOutcomeUnknown(SpeechProviderError):
    pass


class SummaryOutcomeUnknown(RuntimeError):
    pass


@dataclass(frozen=True)
class SubmittedSpeechJob:
    job_id: str


@dataclass(frozen=True)
class SpeechJobResult:
    state: Literal[
        'waiting',
        'processing',
        'completed',
        'failed',
        'timeout',
    ]
    transcript: str = ''
    processing_seconds: int = 0
    error_code: str = ''
