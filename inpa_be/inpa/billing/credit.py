"""사용량 계측 훅 — foliio credit.py 확장판 (dev/23 §3).

공개 인터페이스:
  check_and_consume(user, kind)  → 성공 dict 반환 or LimitExceeded raise
  LimitExceeded                  → 한도 초과 예외 (뷰에서 402 로 변환)

kind ∈ {'ocr', 'ai_compare', 'analysis', 'promotion', 'customer'} (정본 5종 — 'customer'는
  spec 2026-07-09 pricing-limits-align으로 신설. 신규 고객 추가는 설계사 능동 등록만 집계
  — 셀프진단(/d)·소개카드(/p) 인바운드 리드는 Customer.objects.create() 직접 호출이라 미집계)

베타 스위치:
  settings.FREE_TIER_UNLIMITED=True → 한도 체크 전부 우회(무차감 통과)
  settings.FREE_TIER_UNLIMITED=False → 정상 집계

share_link = 이 함수 호출 대상이 아님(북극성 차단 금지 — dev/23 §1.2).
"""
import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


def add_months(dt, n: int):
    """dt 로부터 n개월 뒤 시각. python-dateutil relativedelta 사용(월말 clamp 처리).

    relativedelta 는 1/31 + 1개월 = 2/28 처럼 존재하지 않는 날짜를 자동으로 그 달의
    마지막 날로 clamp 한다(구독 만료일 계산에 안전). requirements.txt 에 이미 존재.
    """
    from dateutil.relativedelta import relativedelta
    return dt + relativedelta(months=n)


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
        return bool(getattr(settings, 'FREE_TIER_UNLIMITED', True))


# 허용된 kind 목록 (정본 5종 — dev/02 §16 + spec 2026-07-09 'customer')
_ALLOWED_KINDS = frozenset({'ocr', 'ai_compare', 'analysis', 'promotion', 'customer'})

# 한도 계산에서 '유효'하다고 볼 상태. 팀 capability는 별도 계약으로 active만 허용한다.
_EFFECTIVE_STATUSES = frozenset({'active', 'trial'})


def resolve_effective_plan(user):
    """실제 한도 계산에 적용할 Plan 을 반환한다 (단일 진실 소스).

    구독의 plan 을 돌려주는 것은 **모든 조건이 참일 때만**이다:
      1) 구독이 존재하고,
      2) status ∈ {active, trial} 이고 (관리자가 cancelled/expired 로 바꾸면 제외),
      3) expires_at 이 없거나(=무기한) 아직 지나지 않았다.
    그 밖(구독 없음·비활성·해지·만료)은 Free 한도로 폴백한다.

    ★ 이 함수는 사용량 화면과 실제 강제(_consume)의 단일 진실 소스다.
      팀 capability는 user_can_use_team이 active만 허용하므로 trial 처리만 의도적으로 다르다.
    """
    from .models import Subscription  # 순환 import 방지

    sub = (
        Subscription.objects
        .select_related('plan')
        .filter(user=user)
        .first()
    )
    if sub is None:
        return _get_free_plan()
    if sub.status not in _EFFECTIVE_STATUSES:
        return _get_free_plan()
    if sub.expires_at is not None and sub.expires_at <= timezone.now():
        return _get_free_plan()
    return sub.plan


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
        kind: 정본 5종 중 하나. 그 외는 ValueError raise.
    """
    return _consume(user, kind, 1)


def check_and_consume_n(user, kind: str, n: int) -> dict:
    """N건을 한 번에 소비 — 일괄 등록(bulk) 전용 (spec 2026-07-09 pricing-limits-align).

    잔여 한도가 n보다 적으면 LimitExceeded를 raise한다 — **부분 소비 없음**(전량 거부,
    호출부가 실제로 만들 행을 하나도 만들지 않도록 트랜잭션 밖에서 먼저 체크해야 한다).
    n<=0 이면 아무 것도 하지 않고 무제한 sentinel 모양의 dict 를 반환한다(호출부 방어).

    Args:
        user: django.contrib.auth User 인스턴스 (request.user)
        kind: 정본 5종 중 하나. 그 외는 ValueError raise.
        n: 이번에 한 번에 소비할 건수(예: 일괄 등록 행 수).
    """
    if n <= 0:
        return {'action': kind, 'count': 0, 'limit': None, 'remaining': None}
    return _consume(user, kind, n)


def _consume(user, kind: str, n: int) -> dict:
    """check_and_consume / check_and_consume_n 공용 내부 구현. n건을 한 번에 소비."""
    if kind not in _ALLOWED_KINDS:
        raise ValueError(
            f'kind는 {sorted(_ALLOWED_KINDS)} 중 하나여야 합니다. 받은 값: {kind!r}'
        )

    # 베타 무차감 스위치 — DB RuntimeConfig 우선, env fallback (dev/23 §3 §G4)
    if free_tier_unlimited():
        return {'action': kind, 'count': 0, 'limit': None, 'remaining': None}

    from .models import UsageMeter  # 순환 import 방지

    # 유효 구독일 때만 그 plan, 아니면 Free 폴백(status·expires_at 동시 판정).
    # resolve_effective_plan 이 매번 DB 조회 → 관리자 변경 직후에도 최신 반영(AC-B7),
    # 역방향 OneToOne 캐시도 우회한다.
    plan = resolve_effective_plan(user)

    ym = UsageMeter.current_month()
    lim = plan.get_limit(kind)  # None = 무제한 sentinel

    with transaction.atomic():
        meter, _ = UsageMeter.objects.select_for_update().get_or_create(
            user=user,
            action=kind,
            year_month=ym,
            defaults={'count': 0},
        )

        if lim is not None and meter.count + n > lim:
            # current = 소비 시도 이전 값 — 부분 반영 없이 전량 거부.
            raise LimitExceeded(action=kind, current=meter.count, limit=lim)

        meter.count += n
        meter.save(update_fields=['count', 'updated_at'])

    remaining = (lim - meter.count) if lim is not None else None
    return {
        'action': kind,
        'count': meter.count,
        'limit': lim,
        'remaining': remaining,
    }


def user_can_use_team(user) -> bool:
    """팀 기능 capability 게이트.

    활성(status='active')·미만료(expires_at) 구독이면서 그 plan.can_use_team=True 일 때만 True.
    구독이 없거나, 비활성/만료 구독이거나, plan.can_use_team=False(예: free)면 False.
    플랜 코드를 직접 판단하지 않으므로 Plus와 legacy Manager/Super도 같은 계약을 따른다.

    ★ 이 함수는 순수 판별만 한다 — 실제로 막을지는 호출부(뷰)가
      settings.MANAGER_PLAN_GATE_ENABLED 를 함께 확인해서 결정한다(기본 False=게이트 미적용).
    """
    from .models import Subscription

    sub = Subscription.objects.select_related('plan').filter(user=user).first()
    if sub is None or sub.status != 'active':
        return False
    if sub.expires_at is not None and sub.expires_at <= timezone.now():
        return False
    return bool(sub.plan.can_use_team)


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


def log_claude_usage(action: str, model: str, usage, *, user=None, outcome='success',
                      carrier_code=None, matched=None, unmatched=None) -> None:
    """Claude 호출 후 1건을 ClaudeApiLog 에 기록 (관리자 전용 비용·결과 로깅, 프리런치 #17).

    ★ 성공·실패 모두 기록한다 — outcome 이 신호다(usage=None 이면 토큰 0, 그래도 1건).
    ★ PII-safe: user 는 FK(id)만, model/action/토큰수/outcome enum/carrier_code(int)/
      matched·unmatched 건수만 저장한다. 증권 원문·응답 본문·상품/고객명은 절대 넣지 않는다
      (claude_parser.py:29 레드라인과 동일 원칙).

    Anthropic SDK message.usage 객체(또는 dict)를 받아 토큰 필드를 안전 추출한다.
    로깅 실패가 본 기능(OCR/비교/메시지)을 깨뜨리지 않도록 모든 예외를 격리한다.

    Args:
        action: 'ocr_parse' | 'ocr_verify' | 'compare_guide' | 'self_diagnosis' 등.
        model:  실제 호출된 모델 ID (settings 정본, 하드코딩 금지).
        usage:  message.usage (input_tokens/output_tokens/
                cache_read_input_tokens/cache_creation_input_tokens) 또는 None(실패).
        user:   호출을 발생시킨 설계사(request.user) 또는 None(/d 공개 경로).
        outcome: ClaudeApiLog.OUTCOME_CHOICES 중 하나(기본 'success').
        carrier_code: 보험사 코드(int, UnmatchedLog 규약) 또는 None(미상).
        matched / unmatched: 이 호출에서 매칭/미매칭된 담보 건수(정수, 원문 미포함).
    """
    try:
        from .models import ClaudeApiLog  # 순환 import 방지
        from .pricing import estimate_cost_krw

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
            user=user,
            cost_krw=estimate_cost_krw(model, usage),
            parse_outcome=outcome,
            carrier_code=carrier_code,
            matched_count=matched or 0,
            unmatched_count=unmatched or 0,
        )
    except Exception as exc:  # 로깅 실패는 본 기능을 막지 않는다. 예외 타입만(내용 미포함).
        logger.warning('[billing] log_claude_usage failed: %s', type(exc).__name__)
