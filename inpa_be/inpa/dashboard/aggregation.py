"""월별 실적(actual) 계산 — 저장 없이 on-demand. 추후 연동 시 이 계산식만 교체.

meetings   = 이번달 확정 미팅 수(booking.Meeting)
premium    = 이번달 등록 증권의 월보험료 합(CustomerInsurance) — '등록 기준' 프록시(신규계약 한정 아님)
new_customers = 이번달 신규 고객 수(Customer)
※ 예상 월급(income)은 산출 소스가 없어 수동값만(MonthlyGoal.target_income).
"""
import datetime

from django.db.models import Count, Sum

from inpa.booking.models import Meeting
from inpa.customers.models import Customer
from inpa.insurances.models import CustomerInsurance


def compute_actuals(user, year_month):
    """year_month='YYYY-MM' → {meetings, premium, new_customers}."""
    y, m = int(year_month[:4]), int(year_month[5:7])
    meetings = Meeting.objects.filter(
        owner=user, status=Meeting.STATUS_CONFIRMED,
        start_at__year=y, start_at__month=m).count()
    premium = CustomerInsurance.objects.filter(
        customer__owner=user, created_at__year=y, created_at__month=m
    ).aggregate(s=Sum('monthly_premiums'))['s'] or 0
    new_customers = Customer.objects.filter(
        owner=user, created_at__year=y, created_at__month=m).count()
    return {'meetings': meetings, 'premium': int(premium), 'new_customers': new_customers}


def recent_months(n=6, today=None):
    """오래된→최근 순 'YYYY-MM' n개 (막대 추이용)."""
    today = today or datetime.date.today()
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append(f'{y:04d}-{m:02d}')
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return list(reversed(out))


def compute_trend(user, n=6):
    """최근 n개월 막대 추이 — [{ym, premium, new_customers, meetings}]."""
    return [{'ym': ym, **compute_actuals(user, ym)} for ym in recent_months(n)]


def compute_funnel(user):
    """영업 4단계 퍼널(011) — sales_stage별 고객 카운트. 4키 항상 포함."""
    counts = dict(
        Customer.objects.filter(owner=user)
        .values_list('sales_stage')
        .annotate(c=Count('id'))
    )
    return {k: counts.get(k, 0) for k in (
        Customer.STAGE_DB, Customer.STAGE_CONTACT,
        Customer.STAGE_MEETING, Customer.STAGE_CONTRACT,
    )}


def compute_portfolio_breakdown(user, today=None):
    """보유계약 유지현황 도넛(sample_1) — at_risk/watch/stable/unknown 카운트.

    churn 레이더와 같은 판정(_assess)을 재사용해 일관성 보장. 보유(portfolio_type=1)만 대상.
    """
    from inpa.insurances.churn import _assess  # 순환 import 회피 — 함수 내부 lazy
    today = today or datetime.date.today()
    qs = CustomerInsurance.objects.select_related('customer').filter(
        customer__owner=user, portfolio_type=1)
    buckets = {'at_risk': 0, 'watch': 0, 'stable': 0, 'unknown': 0}
    for ci in qs:
        is_at_risk, _, stage = _assess(ci, today)
        if is_at_risk:
            buckets['at_risk'] += 1
        elif stage == 'safe':
            buckets['stable'] += 1
        elif stage == 'unknown':
            buckets['unknown'] += 1
        else:  # pre_13 / pre_25 (위험 아님) = 주의 관찰
            buckets['watch'] += 1
    return buckets
