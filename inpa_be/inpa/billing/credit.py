"""사용량 계측 훅 — foliio credit.py 확장판 (dev/23 §3).

공개 인터페이스:
  check_and_consume(user, kind)  → 성공 dict 반환 or LimitExceeded raise
  LimitExceeded                  → 한도 초과 예외 (뷰에서 402 로 변환)

kind ∈ {'ocr', 'ai_compare', 'analysis', 'promotion'} (정본 4종, dev/02 §16)

베타 스위치:
  settings.FREE_TIER_UNLIMITED=True → 한도 체크 전부 우회(무차감 통과)
  settings.FREE_TIER_UNLIMITED=False → 정상 집계

share_link / customer_add = 이 함수 호출 대상이 아님(북극성 차단 금지 — dev/23 §1.2).
"""
from django.conf import settings
from django.db import transaction
from django.utils import timezone


class LimitExceeded(Exception):
    """한도 초과. API 뷰는 402 Payment Required 로 변환.

    FE는 402 + code='credit_exhausted' 수신 시 UpgradeGuideModal 표시.
    기능 자체를 차단하는 UI는 사용하지 않는다 (dev/23 §2 레드라인).
    """

    def __init__(self, action: str, current: int, limit: int):
        self.action = action
        self.current = current
        self.limit = limit
        super().__init__(
            f'[{action}] 이번 달 한도({limit}건)를 모두 사용했어요. (현재 {current}건)'
        )


def free_tier_unlimited() -> bool:
    """DB RuntimeConfig 행 우선, 실패 시 settings fallback."""
    try:
        from .models import RuntimeConfig
        return RuntimeConfig.solo().free_tier_unlimited
    except Exception:
        return bool(getattr(settings, 'FREE_TIER_UNLIMITED', False))


# 허용된 kind 목록 (정본 4종 — dev/02 §16)
_ALLOWED_KINDS = frozenset({'ocr', 'ai_compare', 'analysis', 'promotion'})


def check_and_consume(user, kind: str) -> dict:
    """사용 전 호출. 한도 이내이면 count+1 후 반환, 초과이면 LimitExceeded raise.

    베타 스위치(FREE_TIER_UNLIMITED=True)이면 모든 체크를 우회한다 (무차감).

    반환값:
      {
        "action":    str,
        "count":     int,        # 증가 후 현재 값 (베타 우회 시 0)
        "limit":     int | None, # None = 무제한 sentinel (베타 우회 시 None)
        "remaining": int | None, # None = 무제한 (베타 우회 시 None)
      }

    Args:
        user: django.contrib.auth User 인스턴스 (request.user)
        kind: 정본 4종 중 하나. 그 외는 ValueError raise.
    """
    if kind not in _ALLOWED_KINDS:
        raise ValueError(
            f'kind는 {sorted(_ALLOWED_KINDS)} 중 하나여야 합니다. 받은 값: {kind!r}'
        )

    # 베타 무차감 스위치 — DB RuntimeConfig 우선, env fallback (dev/23 §3 §G4)
    if free_tier_unlimited():
        return {'action': kind, 'count': 0, 'limit': None, 'remaining': None}

    from .models import Plan, UsageMeter, Subscription  # 순환 import 방지

    # select_related로 plan까지 단일 쿼리. getattr 역방향 캐시를 우회해
    # 관리자 Subscription 변경 직후에도 최신 plan을 반영한다 (AC-B7).
    sub = (
        Subscription.objects
        .select_related('plan')
        .filter(user=user)
        .first()
    )
    if sub is not None and (sub.expires_at is None or sub.expires_at > timezone.now()):
        plan = sub.plan
    else:
        # 구독이 없거나, 기간제 구독(쿠폰·체험)이 만료됐으면 Free 한도로 폴백.
        # expires_at=null = 무기한(Free 또는 무기한 Plus) → 만료 판정 없음.
        plan = _get_free_plan()

    ym = UsageMeter.current_month()
    lim = plan.get_limit(kind)  # None = 무제한 sentinel

    with transaction.atomic():
        meter, _ = UsageMeter.objects.select_for_update().get_or_create(
            user=user,
            action=kind,
            year_month=ym,
            defaults={'count': 0},
        )

        if lim is not None and meter.count >= lim:
            raise LimitExceeded(action=kind, current=meter.count, limit=lim)

        meter.count += 1
        meter.save(update_fields=['count', 'updated_at'])

    remaining = (lim - meter.count) if lim is not None else None
    return {
        'action': kind,
        'count': meter.count,
        'limit': lim,
        'remaining': remaining,
    }


def _get_free_plan():
    """Free Plan 조회. 시드 데이터가 없으면 RuntimeError."""
    from .models import Plan  # 순환 import 방지
    try:
        return Plan.objects.get(code='free')
    except Plan.DoesNotExist:
        raise RuntimeError(
            'billing.Plan(code="free") 시드 데이터가 없습니다. '
            'python manage.py loaddata billing_initial_data 를 실행하세요.'
        )


def log_claude_usage(action: str, model: str, usage) -> None:
    """Claude 호출 후 usage 를 ClaudeApiLog 에 1건 기록 (관리자 전용 비용 로깅).

    Anthropic SDK message.usage 객체(또는 dict)를 받아 토큰 필드를 안전 추출한다.
    로깅 실패가 본 기능(OCR/비교/메시지)을 깨뜨리지 않도록 모든 예외를 격리한다.

    Args:
        action: 'ocr_parse' | 'compare_guide' | 'message_gen' 등.
        model:  실제 호출된 모델 ID (settings 정본).
        usage:  message.usage (input_tokens/output_tokens/
                cache_read_input_tokens/cache_creation_input_tokens).
    """
    try:
        from .models import ClaudeApiLog  # 순환 import 방지

        def _g(name):
            if usage is None:
                return 0
            if isinstance(usage, dict):
                val = usage.get(name, 0)
            else:
                val = getattr(usage, name, 0)
            # 실제 usage 는 int. mock/None/비숫자는 0 으로 안전 처리.
            if not isinstance(val, (int, float)):
                return 0
            return int(val)

        ClaudeApiLog.objects.create(
            action=action,
            model=model,
            input_tokens=_g('input_tokens'),
            output_tokens=_g('output_tokens'),
            cache_read_input_tokens=_g('cache_read_input_tokens'),
            cache_creation_input_tokens=_g('cache_creation_input_tokens'),
        )
    except Exception as exc:  # 로깅 실패는 본 기능을 막지 않는다
        print(f'[billing] log_claude_usage failed: {exc}')
