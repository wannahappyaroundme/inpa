import re
import unicodedata
from collections import Counter
from dataclasses import dataclass


class UnsafeTranscript(ValueError):
    pass


PATTERNS = (
    (
        '전화',
        re.compile(r'(?<!\d)(?:01[016789][ -]?\d{3,4}[ -]?\d{4})(?!\d)'),
    ),
    (
        '이메일',
        re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'),
    ),
    (
        '주민번호',
        re.compile(r'(?<!\d)\d{6}[ -]?[1-8]\d{6}(?!\d)'),
    ),
    (
        '계좌',
        re.compile(r'(?<!\d)\d{2,4}[ -]\d{2,6}[ -]\d{3,8}(?!\d)'),
    ),
)


@dataclass(frozen=True)
class MaskedTranscript:
    text: str
    counts: tuple[tuple[str, int], ...]
    residual_scan_passed: bool


def mask_transcript(transcript, known_names):
    if not isinstance(transcript, str):
        raise UnsafeTranscript('TRANSCRIPT_TYPE_INVALID')
    text = unicodedata.normalize('NFKC', transcript).strip()
    if not text:
        raise UnsafeTranscript('TRANSCRIPT_EMPTY')
    if len(text) > 120_000:
        raise UnsafeTranscript('TRANSCRIPT_TOO_LONG')

    counts = Counter()
    names = {
        unicodedata.normalize('NFKC', value).strip()
        for value in known_names
        if isinstance(value, str) and value.strip()
    }
    for index, name in enumerate(
        sorted(names, key=len, reverse=True),
        start=1,
    ):
        text, count = re.subn(re.escape(name), f'[이름_{index}]', text)
        counts['known_name'] += count

    for label, pattern in PATTERNS:
        index = 0

        def replace(_match):
            nonlocal index
            index += 1
            return f'[{label}_{index}]'

        text, count = pattern.subn(replace, text)
        counts[label] += count

    if any(pattern.search(text) for _, pattern in PATTERNS):
        raise UnsafeTranscript('RESIDUAL_IDENTIFIER')
    return MaskedTranscript(
        text=text,
        counts=tuple(sorted(counts.items())),
        residual_scan_passed=True,
    )
