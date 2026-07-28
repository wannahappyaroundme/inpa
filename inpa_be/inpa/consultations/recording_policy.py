import hashlib

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


PLANNER_NOTICE_VERSION = 'consultation-notice-v2-2026-07-28'
PLANNER_NOTICE_TEXT = (
    '본 상담은 상담 내용을 정확히 기록하고, 향후 상담 내용과 보험금 청구 관련 안내를 '
    '확인하는 참고자료로 활용하기 위해 녹음합니다. 원본은 인파에 30일 동안 보관된 뒤 '
    '자동 삭제됩니다. 녹음에 동의하시나요?'
)
PLANNER_NOTICE_TEXT_HASH = hashlib.sha256(
    PLANNER_NOTICE_TEXT.encode('utf-8'),
).hexdigest()

LEGACY_RETENTION_HOURS = 168
LEGACY_RETENTION_DAYS = 7
LEGACY_RETENTION_POLICY_VERSION = 'v1-7d'
CURRENT_RETENTION_POLICY_VERSION = 'v2-30d'
CURRENT_RETENTION_HOURS = 720
CURRENT_RETENTION_DAYS = 30


def effective_retention_hours():
    configured = int(settings.CONSULTATION_RETENTION_HOURS)
    if configured != CURRENT_RETENTION_HOURS:
        raise ImproperlyConfigured(
            'CONSULTATION_RETENTION_HOURS must be exactly 720 '
            'for retention policy v2-30d.',
        )
    return CURRENT_RETENTION_HOURS


def current_retention_snapshot():
    hours = effective_retention_hours()
    return {
        'hours': hours,
        'days': CURRENT_RETENTION_DAYS,
        'policy_version': CURRENT_RETENTION_POLICY_VERSION,
    }
