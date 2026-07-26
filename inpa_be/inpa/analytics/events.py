"""북극성 이벤트 적재 헬퍼 (dev/13 §3.3 viewer_fp · §4 트리거 매핑).

- log_event: NorthStarEvent 1건 적재. 적재 실패가 본 기능을 깨뜨리지 않도록 예외 격리
  (계측은 부가기능 — 본 응답을 막으면 안 된다).
- viewer_fingerprint: 비식별 지문(개인정보 아님). hash(IP대역+UA+Accept-Language+일별 솔트).
- is_dedup_view: 동일 (share_token, viewer_fp) 24h 내 재열람 → 중복(분모 오염 방지).
- is_bot_ua: 카톡 인앱 프리뷰 봇·크롤러 UA → share_view 제외(별도 raw 로그만, dev/13 §3.3).
"""
import hashlib
import logging
import re
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

_SAFE_CODE_RE = re.compile(r'^[A-Za-z0-9_:-]+$')
_BILLING_EVENT_PAYLOAD_FIELDS = {
    'billing_coupon_preflighted': frozenset({
        'duration_months', 'plan_code'}),
    'billing_card_registration_started': frozenset({'plan_code'}),
    'billing_trial_started': frozenset({
        'duration_months', 'plan_code'}),
    'billing_reconfirmation_viewed': frozenset({'days_before'}),
    'billing_reconfirmation_accepted': frozenset({'days_before'}),
    'billing_charge_succeeded': frozenset({
        'plan_code', 'cycle_sequence'}),
    'billing_charge_declined': frozenset({
        'provider_code_enum', 'cycle_sequence'}),
    'billing_charge_unknown': frozenset({'age_bucket'}),
    'billing_free_transitioned': frozenset({'reason'}),
    'billing_restart_started': frozenset({'source'}),
}
_BILLING_ENUM_VALUES = {
    'age_bucket': frozenset({
        'under_5m', '5m_to_30m', '30m_to_24h', 'over_24h'}),
    'reason': frozenset({
        'reconfirmation_missing',
        'payment_method_missing',
        'payment_declined',
        'payment_unknown',
        'late_approval_canceled',
        'cancellation_expired',
    }),
    'source': frozenset({'notice', 'settings'}),
}
_BILLING_TERMINAL_EVENTS = (
    'billing_charge_succeeded',
    'billing_charge_declined',
    'billing_charge_unknown',
)

# 카톡 OG 프리뷰·크롤러 봇 UA 토큰 (소문자 비교). dev/13 §3.3 ②③.
# 카톡으로 링크 보내면 카톡 서버가 OG 프리뷰용으로 먼저 1회 긁는다 → share_view 오염.
_BOT_UA_TOKENS = (
    'kakaotalk-scrap', 'facebookexternalhit', 'twitterbot', 'slackbot',
    'telegrambot', 'whatsapp', 'discordbot', 'linkedinbot', 'embedly',
    'googlebot', 'bingbot', 'yeti', 'daumoa', 'bot', 'crawler', 'spider',
)


def is_bot_ua(user_agent: str) -> bool:
    """알려진 봇/카톡 프리뷰 UA 여부. share_view 신뢰 KPI 분자에서 제외 대상."""
    if not user_agent:
        return False
    ua = user_agent.lower()
    return any(tok in ua for tok in _BOT_UA_TOKENS)


def viewer_fingerprint(request) -> str:
    """비식별 열람자 지문(개인정보 아님). 일별 솔트로 추적 영구화 방지.

    구성(dev/13 §3.3): hash(IP대역 /24 + User-Agent + Accept-Language + 일자).
    """
    ip = request.META.get('REMOTE_ADDR', '') or ''
    # IPv4 /24 대역만 사용(개별 식별 회피). IPv6/파싱 실패는 원문 사용.
    ip_band = ip
    parts = ip.split('.')
    if len(parts) == 4:
        ip_band = '.'.join(parts[:3])
    ua = request.META.get('HTTP_USER_AGENT', '') or ''
    lang = request.META.get('HTTP_ACCEPT_LANGUAGE', '') or ''
    day_salt = timezone.now().strftime('%Y%m%d')
    raw = f'{ip_band}|{ua}|{lang}|{day_salt}'
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]


def is_dedup_view(share_token, viewer_fp, window_hours: int = 24) -> bool:
    """동일 (share_token, viewer_fp)가 window 내 이미 share_view로 적재됐는가.

    True 면 중복 → share_view 재적재 생략(dev/13 §3.3 ① 분모 오염 방지).
    """
    from .models import NorthStarEvent  # 순환 import 방지
    if not viewer_fp:
        return False
    since = timezone.now() - timedelta(hours=window_hours)
    return NorthStarEvent.objects.filter(
        event_type=NorthStarEvent.SHARE_VIEW,
        share_token=share_token,
        viewer_fp=viewer_fp,
        created_at__gte=since,
    ).exists()


def log_event(event_type, *, customer=None, sender=None, customer_id=None,
              sender_id=None, share_token=None, ref_code=None, viewer_fp=None,
              channel='', payload=None):
    """NorthStarEvent 1건 적재. 적재 실패는 본 기능을 막지 않는다(예외 격리).

    반환: 생성된 NorthStarEvent 또는 None(실패 시).
    """
    from .models import NorthStarEvent  # 순환 import 방지
    try:
        values = {
            'event_type': event_type,
            'share_token': share_token,
            'ref_code': ref_code or None,
            'viewer_fp': viewer_fp,
            'channel': channel or '',
            'payload': payload or {},
        }
        if customer_id is not None:
            values['customer_id'] = customer_id
        else:
            values['customer'] = customer
        if sender_id is not None:
            values['sender_id'] = sender_id
        else:
            values['sender'] = sender
        return NorthStarEvent.objects.create(**values)
    except Exception as exc:  # 계측 실패가 응답을 깨뜨리지 않도록 격리
        logger.warning('[analytics] log_event failed: %s', type(exc).__name__)
        return None


def _safe_billing_payload(event_type, payload):
    """결제 이벤트에서 허용한 열거값·숫자만 남긴다.

    이메일, 카드 표기, 고객·메모·상담 내용은 키 이름과 무관하게 저장하지 않는다.
    """
    allowed = _BILLING_EVENT_PAYLOAD_FIELDS[event_type]
    raw = payload or {}
    safe = {}
    # JSON exact-query dedupe가 프로세스 해시 시드와 무관하도록 키 순서를 고정한다.
    for key in sorted(allowed):
        value = raw.get(key)
        if key == 'duration_months':
            if isinstance(value, int) and not isinstance(value, bool):
                safe[key] = min(max(value, 1), 3)
        elif key in ('days_before', 'cycle_sequence'):
            if isinstance(value, int) and not isinstance(value, bool):
                safe[key] = min(max(value, 0), 100000)
        elif key == 'plan_code':
            if (
                isinstance(value, str)
                and 0 < len(value) <= 30
                and _SAFE_CODE_RE.fullmatch(value)
            ):
                safe[key] = value.lower()
        elif key == 'provider_code_enum':
            if (
                isinstance(value, str)
                and 0 < len(value) <= 40
                and _SAFE_CODE_RE.fullmatch(value)
            ):
                safe[key] = value.upper()
            else:
                safe[key] = 'OTHER'
        elif value in _BILLING_ENUM_VALUES.get(key, ()):
            safe[key] = value
    return safe


def log_billing_event(
    event_type,
    *,
    sender,
    payload=None,
    dedupe_hours=0,
):
    """개인정보 없는 결제 운영 이벤트만 append-only 로그에 적재한다."""
    if event_type not in _BILLING_EVENT_PAYLOAD_FIELDS:
        logger.warning('[analytics] rejected billing event type')
        return None
    safe_payload = _safe_billing_payload(event_type, payload)
    if dedupe_hours:
        from .models import NorthStarEvent
        existing = NorthStarEvent.objects.filter(
            event_type=event_type,
            sender=sender,
            channel='billing',
            payload=safe_payload,
            created_at__gte=(
                timezone.now() - timedelta(hours=dedupe_hours)),
        ).first()
        if existing:
            return existing
    return log_event(
        event_type,
        sender=sender,
        channel='billing',
        payload=safe_payload,
    )


def billing_terminal_event_gap(*, now=None, lookback_hours=24):
    """10분 넘은 결제 시도 중 이후 종결 이벤트가 없는 건수.

    관리자 운영 경보용 집계다. 주문·카드·사용자 식별값을 payload에 넣지 않고도
    "승인 시도는 있는데 종결 신호가 멈춤"을 감지한다.
    """
    from inpa.billing.models import PaymentAttempt
    from .models import NorthStarEvent
    from django.db.models import Exists, OuterRef

    current = now or timezone.now()
    started_after = current - timedelta(hours=lookback_hours)
    due_before = current - timedelta(minutes=10)
    terminal_for_attempt = NorthStarEvent.objects.filter(
        event_type__in=_BILLING_TERMINAL_EVENTS,
        sender_id=OuterRef('order__agreement__user_id'),
        created_at__gte=OuterRef('started_at'),
        created_at__lte=current,
    )
    return PaymentAttempt.objects.filter(
        started_at__gte=started_after,
        started_at__lte=due_before,
    ).annotate(
        has_terminal_event=Exists(terminal_for_attempt),
    ).filter(
        has_terminal_event=False,
    ).count()
