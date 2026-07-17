"""지점장 대시보드 — 동의한 소속 설계사의 KPI '집계만'.

★ 프라이버시 (확정 결정):
  - manager_share_opt_in=True 인 소속 설계사(Profile.manager == 매니저)만 포함.
  - 반환은 '집계 수치'뿐 — 개별 고객 객체·이름·병력은 절대 노출하지 않는다(owner 격리 유지).
  - 설계사 식별은 이메일 앞부분 마스킹(별도 표시명 필드 없음).

엔드포인트: GET /api/v1/manager/dashboard/  (config/urls.py 직접 마운트)
"""
import datetime

from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from inpa.accounts.models import Profile
from inpa.analytics.models import NorthStarEvent
from inpa.billing.credit import user_can_use_team
from inpa.core.permissions import IsEmailVerified
from inpa.customers.models import Customer
from inpa.dashboard.aggregation import (
    compute_actuals, compute_deltas, compute_funnel, compute_product_mix,
    compute_retention, compute_team_roi, compute_trend,
)
from inpa.insurances.churn import _assess
from inpa.insurances.models import CustomerInsurance

# 팀 기능 게이트(MANAGER_PLAN_GATE_ENABLED, spec 2026-07-09) 응답 — accounts/invite.py와 동일 shape.
MANAGER_PLAN_REQUIRED_BODY = {
    'detail': 'Plus를 시작하면 팀 관리 기능을 계속 사용할 수 있어요.',
    'code': 'manager_plan_required',
    'plan': 'plus',
}


def _mask(label):
    if not label:
        return '설계사'
    return label[0] + '*' * (len(label) - 1) if len(label) > 1 else label


class ManagerDashboardView(APIView):
    """매니저 본인에게 KPI 공유 동의한 소속 설계사들의 집계.

    ★ settings.MANAGER_PLAN_GATE_ENABLED=True(유료 전환 후)면
      billing.Plan.can_use_team=True인 활성 구독자만 접근 가능 — 402 manager_plan_required.
      기본 False(dormant)라 현재는 인증 설계사 누구나 이용 가능(현행 유지).
    """
    permission_classes = [IsAuthenticated, IsEmailVerified]

    def get(self, request):
        if getattr(settings, 'MANAGER_PLAN_GATE_ENABLED', False) and not user_can_use_team(request.user):
            return Response(MANAGER_PLAN_REQUIRED_BODY, status=status.HTTP_402_PAYMENT_REQUIRED)
        me = request.user
        # ★ KST 기준(§7 이번 달 경계 버그): timezone.localdate() 로 서비스 로컬(Asia/Seoul) 날짜.
        #   datetime.date.today()=OS 로컬(운영 서버 UTC)이라 KST/UTC 월경계 날 집계가 어긋남.
        today = timezone.localdate()
        this_ym = today.strftime('%Y-%m')
        # 동의한 소속 설계사만(level != none). activity=활동만 / full=활동+실적.
        profiles = me.managed_agents.filter(
            manager_share_level__in=[Profile.SHARE_ACTIVITY, Profile.SHARE_FULL]
        ).select_related('user')

        agents = []
        tot_customers = tot_risk = tot_share = 0
        tot_premium = tot_new = active_members = perf_agents = 0
        # 팀 집계: 퍼널·유지율·실적은 기존 개별 집계 함수를 팀 루프로 재사용 — PII 비노출(수치만).
        STAGES = (Customer.STAGE_DB, Customer.STAGE_CONTACT,
                  Customer.STAGE_MEETING, Customer.STAGE_CONTRACT)
        team_funnel = {k: 0 for k in STAGES}
        team_mix = {'life': 0, 'nonlife': 0}
        trend_acc = {}  # ym -> 팀 premium 합(월별 추이) — full 동의자만
        ret_acc = {f'y{n}': {'reached': 0, 'survived': 0} for n in (1, 2, 3)}
        team_has_cancel = False
        for profile in profiles:
            agent = profile.user
            shares_perf = (profile.manager_share_level == Profile.SHARE_FULL)  # 실적까지 공유?
            customer_count = Customer.objects.filter(owner=agent).count()
            held = CustomerInsurance.objects.select_related('customer').filter(
                customer__owner=agent, portfolio_type=1)
            risk = sum(1 for ci in held if _assess(ci, today)[0])
            share_view = NorthStarEvent.objects.filter(
                sender=agent, event_type=NorthStarEvent.SHARE_VIEW).count()
            agent_funnel = compute_funnel(agent)
            for k, v in agent_funnel.items():
                team_funnel[k] = team_funnel.get(k, 0) + v
            actuals = compute_actuals(agent, this_ym)
            deltas = compute_deltas(agent, this_ym, cur=actuals)
            mix = compute_product_mix(agent)
            team_mix['life'] += mix['life']
            team_mix['nonlife'] += mix['nonlife']
            is_active = (actuals['new_customers'] + actuals['meetings']) > 0
            if is_active:
                active_members += 1
            ret = compute_retention(agent, today)
            agents.append({
                'name_masked': _mask(agent.email.split('@')[0]),
                # ── 활동 지표(activity·full 모두 공유) ──
                'customer_count': customer_count,
                'churn_risk_count': risk,
                'share_view_count': share_view,
                'new_month': actuals['new_customers'],
                'meetings_month': actuals['meetings'],
                'funnel': agent_funnel,                       # 단계 분포(미니바)
                'product_mix': mix,
                'last_login': agent.last_login.isoformat() if agent.last_login else None,
                'is_active_month': is_active,                 # 이번 달 활동 0 → 회색 강조
                'shares_performance': shares_perf,            # False면 FE에서 실적 '비공개'
                # ── 실적 지표(full 동의만, 아니면 None=비공개) ──
                'premium_month': actuals['premium'] if shares_perf else None,
                'premium_delta': deltas['premium']['pct'] if shares_perf else None,
                'retention_y1': ret['y1']['rate'] if shares_perf else None,
            })
            tot_customers += customer_count
            tot_risk += risk
            tot_share += share_view
            tot_new += actuals['new_customers']
            # 팀 실적 합계·유지율·추이는 full 동의자만 합산(activity는 실적 미공유).
            if shares_perf:
                perf_agents += 1
                tot_premium += actuals['premium']
                for pt in compute_trend(agent, 6):
                    trend_acc[pt['ym']] = trend_acc.get(pt['ym'], 0) + pt['premium']
                team_has_cancel = team_has_cancel or ret['has_cancellation_data']
                for n in (1, 2, 3):
                    ret_acc[f'y{n}']['reached'] += ret[f'y{n}']['reached']
                    ret_acc[f'y{n}']['survived'] += ret[f'y{n}']['survived']

        team_retention = {'has_cancellation_data': team_has_cancel}
        for n in (1, 2, 3):
            r = ret_acc[f'y{n}']
            team_retention[f'y{n}'] = {
                'rate': round(r['survived'] / r['reached'] * 100) if r['reached'] else None,
                'reached': r['reached'],
                'survived': r['survived'],
            }
        team_premium_trend = [{'ym': ym, 'premium': trend_acc[ym]} for ym in sorted(trend_acc)]

        return Response({
            'agent_count': len(agents),
            'agents': agents,
            'totals': {
                'customer_count': tot_customers,
                'churn_risk_count': tot_risk,
                'share_view_count': tot_share,
                'premium_month': tot_premium,
                'new_month': tot_new,
                'active_member_count': active_members,
                'perf_agent_count': perf_agents,   # 실적까지 공유한 팀원 수(팀 보험료 합계 기준)
            },
            'team_funnel': team_funnel,
            'team_retention': team_retention,
            'team_product_mix': team_mix,
            'team_premium_trend': team_premium_trend,
            'roi': compute_team_roi(len(agents)),
        })
