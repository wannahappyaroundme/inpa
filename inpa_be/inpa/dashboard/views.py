"""대시보드 — 월별 목표(저장) + 실적(계산). 단일 GET/PATCH(?month=YYYY-MM)."""
import re

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from inpa.core.permissions import IsEmailVerified

from .aggregation import (
    compute_actuals, compute_funnel, compute_portfolio_breakdown,
    compute_retention, compute_trend,
)
from .models import MonthlyGoal
from .serializers import MonthlyGoalSerializer

_MONTH_RE = re.compile(r'^\d{4}-\d{2}$')


class DashboardView(APIView):
    """GET = 목표+실적 조회(없으면 0목표 자동 생성), PATCH = 목표 갱신. owner 전용."""
    permission_classes = [IsAuthenticated, IsEmailVerified]

    def _month(self, request):
        ym = request.query_params.get('month')
        if not ym:
            return MonthlyGoal.current_month(), None
        if not _MONTH_RE.match(ym):
            return None, Response(
                {'code': 'BAD_MONTH', 'detail': "month는 'YYYY-MM' 형식이어야 합니다."},
                status=status.HTTP_400_BAD_REQUEST)
        return ym, None

    def _payload(self, goal, user):
        a = compute_actuals(user, goal.year_month)
        multiplier = float(goal.income_multiplier)
        # 예상 월급 = 가입 보험료(실적) × 배율. (추후 수수료 연동 시 이 식만 교체)
        expected_income = int(a['premium'] * multiplier)
        return {
            'year_month': goal.year_month,
            'target_meetings': goal.target_meetings,
            'target_premium': goal.target_premium,
            'income_multiplier': multiplier,
            'expected_income': expected_income,
            'actual_meetings': a['meetings'],
            'actual_premium': a['premium'],
            'actual_new_customers': a['new_customers'],
        }

    def get(self, request):
        ym, err = self._month(request)
        if err is not None:
            return err
        goal, _ = MonthlyGoal.objects.get_or_create(owner=request.user, year_month=ym)
        return Response(self._payload(goal, request.user))

    def patch(self, request):
        ym, err = self._month(request)
        if err is not None:
            return err
        goal, _ = MonthlyGoal.objects.get_or_create(owner=request.user, year_month=ym)
        serializer = MonthlyGoalSerializer(goal, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        goal.refresh_from_db()
        return Response(self._payload(goal, request.user))


class InsightsView(APIView):
    """GET /api/v1/dashboard/insights/ — 홈 차트용 집계(저장 없이 on-demand). owner 전용.

    monthly_trend(최근 6개월 막대) · funnel(영업 4단계) · portfolio(보유계약 유지현황 도넛).
    """
    permission_classes = [IsAuthenticated, IsEmailVerified]

    def get(self, request):
        return Response({
            'monthly_trend': compute_trend(request.user, n=6),
            'funnel': compute_funnel(request.user),
            'portfolio': compute_portfolio_breakdown(request.user),
            'retention': compute_retention(request.user),
        })
