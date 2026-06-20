"""담보 한눈표 / 히트맵 API — 소유자 격리 + 준법 neutral 게이트.

핵심 엔드포인트:
  GET /api/v1/customers/<customer_pk>/heatmap/
    해당 고객(★ owner 격리)의 보험·담보를 표준 담보 트리(AnalysisDetail)에 매핑해
    '한눈표'를 만들고, 보유 보장금액을 집계(♻ calculate_total_analysis)한다.

★ 준법 통제점 (dev/02 §0, planner_baseline neutral 강제):
  - 설계사가 해당 고객 상품군에 대한 PlannerBaseline(baseline_source != null) 을 보유하지 않으면
    mode='neutral' — 각 담보 status='neutral'(부족/충분 단정 금지).
  - baseline_source 가 살아있는 baseline 이 하나라도 있으면 mode='graded' — 해당 담보만
    baseline 과 비교해 'shortage'|'adequate'|'over' 판정. baseline 없는 담보는 여전히 neutral.
  → "부족/충분" 판정 권위는 인파가 아니라 설계사(planner_baseline)에게 있다.

격리: 부모 Customer 를 owner 스코프 쿼리로 잡는다(없으면 404 = 존재 자체 은폐).
  보험(CustomerInsurance)은 customer__owner 경유 소유자 전용이므로 customer 필터만으로 충분.

순수 계산 — Claude API 불필요.
"""
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from inpa.analysis.models import AnalysisCategory, AnalysisDetail, ChartDetail
from inpa.billing.credit import LimitExceeded, check_and_consume
from inpa.core.permissions import IsEmailVerified
from inpa.customers.models import Customer, PlannerBaseline

from .calculate import calculate_total_analysis

# 상품군(PlannerBaseline.product_group) ↔ 보험종류(AnalysisDetail.insurance_type) 매핑.
# 생명(1)=생명보험(1), 손해/실손/연금(2·3·4)=손해보험(2). neutral 게이트는 상품군 무관하게
# "살아있는 baseline 존재 여부"로 결정하므로 이 매핑은 grading 단계 보조용이다.
_PRODUCT_GROUP_TO_INSURANCE_TYPE = {
    PlannerBaseline.PRODUCT_GROUP_LIFE: 1,
    PlannerBaseline.PRODUCT_GROUP_NONLIFE: 2,
    PlannerBaseline.PRODUCT_GROUP_INDEMNITY: 2,
    PlannerBaseline.PRODUCT_GROUP_ANNUITY: 2,
}


def _credit_exhausted_response(exc: LimitExceeded, user) -> Response:
    """LimitExceeded → 402 Payment Required (dev/02 §16 shape).

    FE는 402 + code='credit_exhausted' 수신 시 UpgradeGuideModal 표시.
    """
    from inpa.billing.models import Subscription
    sub = Subscription.objects.select_related('plan').filter(user=user).first()
    membership = sub.plan.code if sub else 'free'
    return Response(
        {
            'detail': f'이번 달 한도({exc.limit}건)를 모두 사용했어요.',
            'code': 'credit_exhausted',
            'kind': exc.action,
            'membership': membership,
            'limit': exc.limit,
            'used': exc.current,
        },
        status=status.HTTP_402_PAYMENT_REQUIRED,
    )


def _age_band(birth_day):
    """'YYYY.MM.DD' / 'YYYY-MM-DD' → '20s'|'30s'|...|'60s+'. 파싱 실패 시 None."""
    if not birth_day:
        return None
    import datetime
    raw = str(birth_day).replace('-', '.').strip()
    for fmt in ('%Y.%m.%d', '%Y.%m', '%Y'):
        try:
            dt = datetime.datetime.strptime(raw, fmt)
            break
        except ValueError:
            dt = None
    if dt is None:
        return None
    age = datetime.datetime.now().year - dt.year
    if age < 20:
        return '20s'  # 20대 미만도 가장 낮은 밴드로 귀속(보수적)
    if age >= 60:
        return '60s+'
    return f'{(age // 10) * 10}s'


class CustomerHeatmapView(APIView):
    """담보 한눈표/히트맵 — GET /api/v1/customers/<customer_pk>/heatmap/

    응답 형태:
      {
        "customer_id": int,
        "mode": "neutral" | "graded",
        "baseline_present": bool,
        "summary": { calculate_total_analysis 의 합계 필드들 },
        "tree": [ {category, sub_categories:[ {sub, details:[ {detail, held_amount,
                   status, baseline:{min,max} } ] } ] } ],
      }

    ★ status 규칙:
      - mode=neutral 이거나 해당 담보에 살아있는 baseline 이 없으면 → 'neutral'
      - graded + baseline 있음 →
          held < min            → 'shortage'
          held > max(>0)        → 'over'
          그 외(min..max 사이)   → 'adequate'
    """
    permission_classes = [IsAuthenticated, IsEmailVerified]

    def _is_admin(self):
        profile = getattr(self.request.user, 'profile', None)
        return bool(getattr(profile, 'is_admin', False))

    def _get_customer(self, customer_pk):
        qs = Customer.objects.all()
        if not self._is_admin():
            qs = qs.filter(owner=self.request.user)
        try:
            return qs.get(pk=customer_pk)
        except Customer.DoesNotExist:
            raise NotFound('고객을 찾을 수 없습니다.')

    def get(self, request, customer_pk):
        customer = self._get_customer(customer_pk)

        # ── 0) 크레딧 차감 (kind='analysis') — 한눈표/히트맵 진입. 한도 초과 시 402 ──
        #    베타 FREE_TIER_UNLIMITED=True 면 통과(무차감).
        try:
            check_and_consume(request.user, 'analysis')
        except LimitExceeded as exc:
            return _credit_exhausted_response(exc, request.user)

        # ── 1) 보험 목록 (customer__owner 경유 소유자 전용 → customer 필터로 격리 완결) ──
        insurance_list = list(
            customer.customer_insurance_list
            .prefetch_related('case_list__detail__analysis_detail',
                              'case_list__detail__chart_detail')
            .all()
        )

        # ── 2) 표준 담보 트리(AnalysisDetail) · 차트단위(ChartDetail) → calculate 입력 ──
        #    calculate_total_analysis 는 case['id']/chart['id'] 로 인덱싱하므로 dict 화 필수.
        analysis_details = list(AnalysisDetail.objects.all().values(
            'id', 'name', 'order', 'chart_based_amount', 'sub_category_id'))
        case_list = [dict(d) for d in analysis_details]
        chart_list = [dict(c) for c in ChartDetail.objects.all().values(
            'id', 'name', 'order', 'chart_based_amount', 'insurance_type', 'chart_type')]

        result = calculate_total_analysis(
            customer.birth_day, case_list, chart_list, insurance_list)

        # ── 3) 준법 게이트: 살아있는 baseline(baseline_source != null, is_active) 존재? ──
        baselines = list(
            PlannerBaseline.objects
            .filter(owner=customer.owner, is_active=True)
            .exclude(baseline_source__isnull=True)
        )
        mode = 'graded' if baselines else 'neutral'
        band = _age_band(customer.birth_day)

        # coverage_key 별 baseline 조회 인덱스 (성별/연령 우선, 없으면 공통으로 완화)
        baseline_index = {}
        for b in baselines:
            baseline_index.setdefault(b.coverage_key, []).append(b)

        def _grade(detail_name, held_amount):
            """담보 한 칸의 status 판정. graded 모드 + 매칭 baseline 있을 때만 비교."""
            if mode != 'graded':
                return 'neutral', None
            candidates = baseline_index.get(detail_name)
            if not candidates:
                return 'neutral', None  # ★ baseline 없는 담보는 단정 금지
            chosen = self._pick_baseline(candidates, customer.gender, band)
            if chosen is None:
                return 'neutral', None
            lo = float(chosen.recommend_min) if chosen.recommend_min is not None else None
            hi = float(chosen.recommend_max) if chosen.recommend_max is not None else None
            held = held_amount or 0
            if lo is not None and held < lo:
                status = 'shortage'
            elif hi is not None and hi > 0 and held > hi:
                status = 'over'
            else:
                status = 'adequate'
            return status, {'min': lo, 'max': hi, 'unit': chosen.unit,
                            'baseline_source': chosen.baseline_source}

        # ── 4) 집계 결과(case_list)를 표준 트리(category→sub→detail)로 재구성 ──
        held_by_detail_id = {c['id']: c.get('total_premium', 0) for c in result['case_list']}

        tree = []
        categories = (AnalysisCategory.objects
                      .prefetch_related('sub_categories__details')
                      .order_by('order', 'id'))
        for cat in categories:
            sub_nodes = []
            for sub in cat.sub_categories.all().order_by('order', 'id'):
                detail_nodes = []
                for det in sub.details.all().order_by('order', 'id'):
                    held = held_by_detail_id.get(det.id, 0)
                    status, baseline = _grade(det.name, held)
                    detail_nodes.append({
                        'detail_id': det.id,
                        'name': det.name,
                        'held_amount': held,
                        'status': status,
                        'baseline': baseline,
                    })
                sub_nodes.append({
                    'sub_category_id': sub.id,
                    'name': sub.name,
                    'details': detail_nodes,
                })
            tree.append({
                'category_id': cat.id,
                'name': cat.name,
                'insurance_type': cat.insurance_type,
                'sub_categories': sub_nodes,
            })

        # summary 는 calculate 결과의 합계 필드만 추려 노출(case_list/chart_list 원본은 제외 — 트리로 대체)
        summary_keys = (
            'monthly_premiums', 'monthly_renewal_premium', 'monthly_non_renewal_premium',
            'monthly_earned_premium', 'total_premiums', 'total_renewal_premium',
            'total_non_renewal_premium', 'total_earned_premium',
            'total_cancellation_refund', 'total_cancellation_loss',
            'total_prepaid_insurance_premium', 'total_pay_insurance_premium',
        )
        summary = {k: result[k] for k in summary_keys}

        return Response({
            'customer_id': customer.id,
            'mode': mode,
            'baseline_present': bool(baselines),
            'insurance_count': len(insurance_list),
            'summary': summary,
            'chart_list': result['chart_list'],
            'tree': tree,
        })

    @staticmethod
    def _pick_baseline(candidates, gender, band):
        """coverage_key 매칭 후보 중 (성별·연령) 가장 구체적인 것을 고른다.

        우선순위: (gender 일치 + band 일치) > (gender 공통 + band 일치)
                > (gender 일치) > (gender 공통) > 첫 후보.
        """
        def score(b):
            s = 0
            if b.gender is not None and b.gender == gender:
                s += 2
            elif b.gender is None:
                s += 1
            if band and b.age_band == band:
                s += 4
            return s
        return max(candidates, key=score) if candidates else None
