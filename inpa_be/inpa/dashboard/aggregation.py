"""월별 실적(actual) 계산 — 저장 없이 on-demand. 추후 연동 시 이 계산식만 교체.

meetings   = 이번달 확정 미팅 수(booking.Meeting)
premium    = 이번달 등록 증권의 월보험료 합(CustomerInsurance) — '등록 기준' 프록시(신규계약 한정 아님)
new_customers = 이번달 신규 고객 수(Customer)
※ 예상 월급(income)은 산출 소스가 없어 수동값만(MonthlyGoal.target_income).
"""
from django.db.models import Sum

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
