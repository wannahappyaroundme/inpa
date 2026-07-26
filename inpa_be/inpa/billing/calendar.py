"""KST 결제 기준일을 위한 순수 달력 계산."""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class BillingPeriod:
    starts_on: date
    access_through: date
    next_charge_date: date


def add_calendar_months(
        start_date: date, months: int, *, anchor_day: int) -> date:
    """원래 결제일을 보존하고 없는 날짜만 해당 월 말일로 맞춘다."""
    if months < 1 or anchor_day not in range(1, 32):
        raise ValueError('INVALID_CALENDAR_PERIOD')
    month_index = start_date.year * 12 + start_date.month - 1 + months
    year, zero_month = divmod(month_index, 12)
    month = zero_month + 1
    day = min(anchor_day, monthrange(year, month)[1])
    return date(year, month, day)


def period_for(
        start_date: date, months: int, *, anchor_day: int) -> BillingPeriod:
    next_date = add_calendar_months(
        start_date, months, anchor_day=anchor_day)
    return BillingPeriod(
        starts_on=start_date,
        access_through=next_date - timedelta(days=1),
        next_charge_date=next_date,
    )


def new_anchor(local_date: date) -> int:
    return local_date.day
