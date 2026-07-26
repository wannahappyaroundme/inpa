from dataclasses import dataclass


class InvalidSummary(ValueError):
    pass


SECTION_KEYS = (
    'consultation_core',
    'customer_priorities',
    'items_to_confirm',
    'next_actions',
)

SUMMARY_JSON_SCHEMA = {
    'type': 'object',
    'properties': {
        key: {
            'type': 'array',
            'items': {'type': 'string', 'maxLength': 300},
            'maxItems': 12,
        }
        for key in SECTION_KEYS
    },
    'required': list(SECTION_KEYS),
    'additionalProperties': False,
}


def _validated_items(payload, key):
    values = payload.get(key)
    if not isinstance(values, list) or len(values) > 12:
        raise InvalidSummary(f'INVALID_{key.upper()}')
    cleaned = []
    for value in values:
        if not isinstance(value, str):
            raise InvalidSummary(f'INVALID_{key.upper()}')
        item = value.strip()
        if not item or len(item) > 300:
            raise InvalidSummary(f'INVALID_{key.upper()}')
        cleaned.append(item)
    return tuple(cleaned)


@dataclass(frozen=True)
class ConsultationSummary:
    consultation_core: tuple[str, ...]
    customer_priorities: tuple[str, ...]
    items_to_confirm: tuple[str, ...]
    next_actions: tuple[str, ...]

    @classmethod
    def from_payload(cls, payload):
        if not isinstance(payload, dict) or set(payload) != set(SECTION_KEYS):
            raise InvalidSummary('SUMMARY_SCHEMA_INVALID')
        return cls(**{
            key: _validated_items(payload, key)
            for key in SECTION_KEYS
        })


def render_summary_memo(summary):
    if not isinstance(summary, ConsultationSummary):
        raise InvalidSummary('SUMMARY_TYPE_INVALID')
    sections = (
        ('상담 핵심', summary.consultation_core),
        ('고객이 중요하게 본 내용', summary.customer_priorities),
        ('확인할 내용', summary.items_to_confirm),
        ('다음 할 일', summary.next_actions),
    )
    body = '\n\n'.join(
        f"{title}\n" + (
            '\n'.join(f'- {item}' for item in items)
            if items
            else '- 확인된 내용 없음'
        )
        for title, items in sections
    )
    if len(body) > 5_000:
        raise InvalidSummary('SUMMARY_TOO_LONG')
    return body
