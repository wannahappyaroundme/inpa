"""북극성 이벤트 적재 헬퍼 (dev/13 §3.3 viewer_fp · §4 트리거 매핑).

- log_event: NorthStarEvent 1건 적재. 적재 실패가 본 기능을 깨뜨리지 않도록 예외 격리
  (계측은 부가기능 — 본 응답을 막으면 안 된다).
- viewer_fingerprint: 비식별 지문(개인정보 아님). hash(IP대역+UA+Accept-Language+일별 솔트).
- is_dedup_view: 동일 (share_token, viewer_fp) 24h 내 재열람 → 중복(분모 오염 방지).
- is_bot_ua: 카톡 인앱 프리뷰 봇·크롤러 UA → share_view 제외(별도 raw 로그만, dev/13 §3.3).
"""
import hashlib
import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

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
