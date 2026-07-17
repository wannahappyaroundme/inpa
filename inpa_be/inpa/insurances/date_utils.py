import datetime
import re


_INSURANCE_DATE_PATTERNS = (
    re.compile(
        r'\s*(\d{4})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*'
        r'(\d{1,2})\s*'),
    re.compile(
        r'\s*(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일\s*'),
)


def parse_insurance_date(value):
    """Return one validated calendar date from supported policy formats."""
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if not isinstance(value, str):
        return None
    for pattern in _INSURANCE_DATE_PATTERNS:
        match = pattern.fullmatch(value)
        if match is None:
            continue
        try:
            return datetime.date(*(int(part) for part in match.groups()))
        except ValueError:
            return None
    return None


def normalize_insurance_date(value):
    """Normalize a valid policy date to the legacy model's dotted form."""
    parsed = parse_insurance_date(value)
    return parsed.strftime('%Y.%m.%d') if parsed is not None else None
