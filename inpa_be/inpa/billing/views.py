"""billing 도메인 뷰 (dev/23 §4 API 계약).

엔드포인트:
  GET  /api/v1/billing/plans/                     — 요금제 목록 (공개 AllowAny)
  GET  /api/v1/billing/usage/                     — 내 사용량 조회 (IsAuthenticated)
  GET  /api/v1/admin/billing/usage/               — 관리자 전체 사용량 (IsAdmin)
  PATCH /api/v1/admin/billing/subscription/<uid>/ — 관리자 구독 수동 변경 (IsAdmin)

★ 가시성 강제:
  - /billing/usage/ : request.user로 자동 스코프. user_id 파라미터 주입 차단.
  - /admin/* : IsAdmin 권한만.

★ 한도 초과 응답 shape (dev/23 §4.4, AC-B3):
  {detail, code, kind, membership, limit, used, upgrade_url}  HTTP 402
  → credit.py의 LimitExceeded를 뷰에서 잡아 변환. 이 파일에 예시 포함.
"""
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from inpa.core.permissions import IsAdmin

from .coupons import CouponError, redeem_coupon
from .credit import LimitExceeded  # noqa: F401 — 뷰 사용 예시용 (실제 뷰에서 직접 catch)
from .models import Plan, Subscription, UsageMeter
from .serializers import (
    AdminSubscriptionPatchSerializer,
    CouponRedeemSerializer,
    PlanSerializer,
)

User = get_user_model()

# action별 한국어 label (dev/23 §5.1 화면 구성 일치)
_ACTION_LABELS = {
    'ocr': '증권 OCR 분析',
    'ai_compare': '증권 비교',
    'analysis': 'AI 분析·메시지',
    'promotion': '판촉물 주문',
    'customer': '고객 추가',
}
_ACTION_ORDER = ['ocr', 'ai_compare', 'analysis', 'promotion', 'customer']


def _build_usage_response(user) -> dict:
    """설계사 1인의 사용량 응답 dict 구성 (내부 헬퍼).

    sub가 없으면 Free Plan으로 폴백 (비정상 상태 방어).
    Django OneToOneField 역방향 캐시를 우회해 항상 최신 DB 상태를 조회한다.
    """
    from .credit import resolve_effective_plan

    # ★ 표시 한도 = 실제 강제 한도. resolve_effective_plan 이 만료·해지 구독을 Free 로
    #   폴백하므로 화면에 보이는 한도가 402 로 실제 막히는 한도와 일치한다.
    plan = resolve_effective_plan(user)

    # select_related로 plan까지 단일 쿼리, 캐시 우회 — 폴백 여부 판정용.
    sub = (
        Subscription.objects
        .select_related('plan')
        .filter(user=user)
        .first()
    )
    if sub is not None:
        effective = (
            sub.status in ('active', 'trial')
            and (sub.expires_at is None or sub.expires_at > timezone.now())
        )
        # 폴백이 발동하면(만료·해지) 상태를 '만료'로 표기해 Free 한도 표시와 맞춘다.
        sub_data = {
            'status': sub.status if effective else 'expired',
            'billing_cycle': sub.billing_cycle,
            'expires_at': sub.expires_at.isoformat() if sub.expires_at else None,
        }
    else:
        # 가입 시그널 누락 방어 — Free Plan 폴백
        sub_data = {'status': 'active', 'billing_cycle': 'monthly', 'expires_at': None}

    ym = UsageMeter.current_month()

    # 현재 월 meters (없으면 count=0으로 처리)
    meters = {
        m.action: m.count
        for m in UsageMeter.objects.filter(user=user, year_month=ym)
    }

    usage_list = []
    for action in _ACTION_ORDER:
        lim = plan.get_limit(action) if plan else None
        cnt = meters.get(action, 0)
        remaining = (lim - cnt) if lim is not None else None
        usage_list.append({
            'action': action,
            'label': _ACTION_LABELS[action],
            'count': cnt,
            'limit': lim,
            'remaining': remaining,
        })

    return {
        'plan': {
            'code': plan.code if plan else 'free',
            'display_name': plan.display_name if plan else '무료',
            'price_krw': plan.price_krw if plan else 0,
        },
        'subscription': sub_data,
        'year_month': ym,
        'usage': usage_list,
    }


class PlanListView(APIView):
    """요금제 목록 (공개 AllowAny — 비로그인 GET 허용, dev/23 §7).

    GET /api/v1/billing/plans/
    """
    permission_classes = [AllowAny]
    authentication_classes = []  # Token 없이도 접근 가능

    def get(self, request):
        plans = Plan.objects.filter(is_active=True).order_by('price_krw')
        serializer = PlanSerializer(plans, many=True)
        return Response(serializer.data)


class BillingEventView(APIView):
    """진행 중인 결제 이벤트 플래그 (공개 AllowAny — 비로그인 GET 허용).

    GET /api/v1/billing/event/  → {"first_paid_bonus_enabled": bool}

    첫 유료 결제 +1개월 보너스 이벤트가 실제로 켜져 있는지(RuntimeConfig 런타임 토글).
    랜딩·업그레이드 모달의 이벤트 문구는 이 값이 True일 때만 노출해, 꺼져 있는
    이벤트를 약속하지 않도록 한다(§6 정직성). 연 결제 할인(2개월 무료 = 실제 가격)은
    이 플래그와 무관하게 항상 노출한다.
    """
    permission_classes = [AllowAny]
    authentication_classes = []  # Token 없이도 접근 가능

    def get(self, request):
        from .models import RuntimeConfig
        cfg = RuntimeConfig.solo()
        return Response({'first_paid_bonus_enabled': cfg.first_paid_bonus_enabled})


class BillingUsageView(APIView):
    """내 사용량 조회 (IsAuthenticated — 본인 데이터만).

    GET /api/v1/billing/usage/
    user_id 쿼리 파라미터 주입 차단: 서버가 request.user로만 스코프.
    AC-B4 검증 포인트.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        data = _build_usage_response(request.user)
        return Response(data)


class CouponRedeemView(APIView):
    """무료 쿠폰 사용 — 설계사가 발급받은 코드를 입력해 Plus를 한시적으로 부여받는다.

    POST /api/v1/billing/coupons/redeem/  body {code}
      성공 200 {plan_code, plan_display_name, expires_at, duration_days}
      실패 404(없음)/409(이미 사용)/410(만료·소진·비활성) + {code, detail}
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CouponRedeemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = redeem_coupon(request.user, serializer.validated_data['code'])
        except CouponError as exc:
            status_map = {
                'not_found': status.HTTP_404_NOT_FOUND,
                'already': status.HTTP_409_CONFLICT,
                'active_plan': status.HTTP_409_CONFLICT,
            }
            code = status_map.get(exc.code, status.HTTP_410_GONE)
            return Response({'code': exc.code, 'detail': str(exc)}, status=code)
        return Response(result, status=status.HTTP_200_OK)


# ─── 관리자 전용 ──────────────────────────────────────────────────


class AdminBillingUsageView(APIView):
    """관리자 — 전체 설계사 사용량 조회 (IsAdmin).

    GET /api/v1/admin/billing/usage/?user_id=<id>&year_month=2026-06
    필터 없으면 전체 UsageMeter 반환(페이지네이션 간소화 — 관리자 전용).
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        user_id = request.query_params.get('user_id')
        year_month = request.query_params.get('year_month', UsageMeter.current_month())

        if user_id:
            target_user = get_object_or_404(User, pk=user_id)
            data = _build_usage_response(target_user)
            data['user'] = {
                'id': target_user.pk,
                'email': target_user.email,
            }
            return Response(data)

        # 전체 설계사 목록 — 해당 월 meter가 있는 user만 (없는 user는 all-zero 처리)
        meters = (
            UsageMeter.objects
            .filter(year_month=year_month)
            .select_related('user')
            .order_by('user__email', 'action')
        )

        # user별 그룹핑
        from collections import defaultdict
        from .credit import resolve_effective_plan
        user_meters: dict = defaultdict(dict)
        user_objs = {}
        for m in meters:
            user_meters[m.user_id][m.action] = m.count
            user_objs[m.user_id] = m.user

        results = []
        for uid, cnt_map in user_meters.items():
            u = user_objs[uid]
            # 표시 한도 = 실제 강제 한도(취소·만료 구독은 무료로 폴백). 단일유저 브랜치·_consume와 동일.
            plan = resolve_effective_plan(u)
            usage_list = []
            for action in _ACTION_ORDER:
                lim = plan.get_limit(action) if plan else None
                cnt = cnt_map.get(action, 0)
                remaining = (lim - cnt) if lim is not None else None
                usage_list.append({
                    'action': action,
                    'label': _ACTION_LABELS[action],
                    'count': cnt,
                    'limit': lim,
                    'remaining': remaining,
                })
            results.append({
                'user': {'id': uid, 'email': u.email},
                'year_month': year_month,
                'usage': usage_list,
            })

        return Response({'count': len(results), 'results': results})


class AdminBillingModeView(APIView):
    """운영 토글 — 관리자. GET 현재값 / PATCH 부분 전송.

    토글:
      free_tier_unlimited      — 베타 무제한(True=한도 무시).
      first_paid_bonus_enabled — 첫 유료 결제 +1개월 이벤트(사용자당 1회, 기본 OFF).
    각 키는 선택 전송이며, 있으면 bool 이어야 한다(아니면 400).
    """
    permission_classes = [IsAdmin]

    _TOGGLE_KEYS = ('free_tier_unlimited', 'first_paid_bonus_enabled')

    def _snapshot(self, cfg):
        return {k: getattr(cfg, k) for k in self._TOGGLE_KEYS}

    def get(self, request):
        from .models import RuntimeConfig
        return Response(self._snapshot(RuntimeConfig.solo()))

    def patch(self, request):
        from rest_framework.exceptions import ValidationError
        from .models import RuntimeConfig
        cfg = RuntimeConfig.solo()
        update_fields = []
        for key in self._TOGGLE_KEYS:
            if key in request.data:
                val = request.data.get(key)
                if not isinstance(val, bool):
                    raise ValidationError({key: 'true/false 값이 필요합니다.'})
                setattr(cfg, key, val)
                update_fields.append(key)
        if update_fields:
            cfg.save(update_fields=update_fields + ['updated_at'])
        return Response(self._snapshot(cfg))


class AdminSubscriptionPatchView(APIView):
    """관리자 — 구독 수동 변경 (MVP 결제 확인 후 수동 활성화, dev/23 §4.3).

    PATCH /api/v1/admin/billing/subscription/<user_id>/
    plan_code / status / expires_at 부분 전송 허용.
    """
    permission_classes = [IsAdmin]

    def patch(self, request, user_id):
        target_user = get_object_or_404(User, pk=user_id)
        sub = get_object_or_404(Subscription, user=target_user)

        serializer = AdminSubscriptionPatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        update_fields = []

        if 'plan_code' in data:
            plan = get_object_or_404(Plan, code=data['plan_code'])
            sub.plan = plan
            update_fields.append('plan')

        if 'status' in data:
            sub.status = data['status']
            update_fields.append('status')

        if 'expires_at' in data:
            sub.expires_at = data['expires_at']
            update_fields.append('expires_at')

        if update_fields:
            sub.save(update_fields=update_fields)

        # 변경 후 사용량 응답 반환 (AC-B7 즉시 반영 확인)
        resp_data = _build_usage_response(target_user)
        resp_data['user'] = {'id': target_user.pk, 'email': target_user.email}
        return Response(resp_data)
