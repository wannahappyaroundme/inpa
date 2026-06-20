"""지점장 대시보드 — 동의한 소속 설계사의 KPI '집계만'.

★ 프라이버시 (확정 결정):
  - manager_share_opt_in=True 인 소속 설계사(Profile.manager == 매니저)만 포함.
  - 반환은 '집계 수치'뿐 — 개별 고객 객체·이름·병력은 절대 노출하지 않는다(owner 격리 유지).
  - 설계사 식별은 이메일 앞부분 마스킹(별도 표시명 필드 없음).

엔드포인트: GET /api/v1/manager/dashboard/  (config/urls.py 직접 마운트)
"""
import datetime

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from inpa.analytics.models import NorthStarEvent
from inpa.core.permissions import IsEmailVerified
from inpa.customers.models import Customer
from inpa.insurances.churn import _assess
from inpa.insurances.models import CustomerInsurance


def _mask(label):
    if not label:
        return '설계사'
    return label[0] + '*' * (len(label) - 1) if len(label) > 1 else label


class ManagerDashboardView(APIView):
    """매니저 본인에게 KPI 공유 동의한 소속 설계사들의 집계."""
    permission_classes = [IsAuthenticated, IsEmailVerified]

    def get(self, request):
        me = request.user
        today = datetime.date.today()
        # 동의한 소속 설계사만(Profile.manager == me AND manager_share_opt_in=True)
        profiles = me.managed_agents.filter(manager_share_opt_in=True).select_related('user')

        agents = []
        tot_customers = tot_risk = tot_share = 0
        for profile in profiles:
            agent = profile.user
            customer_count = Customer.objects.filter(owner=agent).count()
            held = CustomerInsurance.objects.select_related('customer').filter(
                customer__owner=agent, portfolio_type=1)
            risk = sum(1 for ci in held if _assess(ci, today)[0])
            share_view = NorthStarEvent.objects.filter(
                sender=agent, event_type=NorthStarEvent.SHARE_VIEW).count()
            agents.append({
                'name_masked': _mask(agent.email.split('@')[0]),
                'customer_count': customer_count,
                'churn_risk_count': risk,
                'share_view_count': share_view,
            })
            tot_customers += customer_count
            tot_risk += risk
            tot_share += share_view

        return Response({
            'agent_count': len(agents),
            'agents': agents,
            'totals': {
                'customer_count': tot_customers,
                'churn_risk_count': tot_risk,
                'share_view_count': tot_share,
            },
        })
