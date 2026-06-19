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

    # 베타 무차감 스위치 — 환경변수 FREE_TIER_UNLIMITED=True (dev/23 §3 §G4)
    if getattr(settings, 'FREE_TIER_UNLIMITED', False):
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
    if sub is not None:
        plan = sub.plan
    else:
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
