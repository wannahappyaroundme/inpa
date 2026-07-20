import logging
import re


_SOURCE_TOKEN_PATH = re.compile(
    r'(/api/v1/insurance-imports/source/)[^/?\s]+',
)


def _redact(value):
    if not isinstance(value, str):
        return value
    return _SOURCE_TOKEN_PATH.sub(r'\1<redacted>', value)


class RedactInsuranceSourceTokenFilter(logging.Filter):
    """Keep signed source capabilities out of Django console logs."""

    def filter(self, record):
        record.msg = _redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(_redact(value) for value in record.args)
        elif isinstance(record.args, dict):
            record.args = {
                key: _redact(value) for key, value in record.args.items()
            }
        return True
