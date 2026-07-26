from datetime import datetime, time

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from inpa.billing.credit import LimitExceeded, resolve_effective_plan
from inpa.billing.models import UsageMeter

from .models import ConsultationRuntimeConfig, ConsultationSummaryRun


ACTIVE_SUMMARY_STATUSES = (
    ConsultationSummaryRun.STATUS_QUEUED,
    ConsultationSummaryRun.STATUS_TRANSCRIBING,
    ConsultationSummaryRun.STATUS_SUMMARIZING,
)


def ai_cost_budget_available(*, now=None):
    now = now or timezone.now()
    local_date = timezone.localtime(now).date()
    current_tz = timezone.get_current_timezone()
    day_start = timezone.make_aware(
        datetime.combine(local_date, time.min),
        current_tz,
    )
    month_start = timezone.make_aware(
        datetime.combine(local_date.replace(day=1), time.min),
        current_tz,
    )
    config = ConsultationRuntimeConfig.solo()
    completed = ConsultationSummaryRun.objects.filter(
        status=ConsultationSummaryRun.STATUS_SUCCEEDED,
    )
    daily_cost = completed.filter(
        completed_at__gte=day_start,
    ).aggregate(total=Sum('estimated_cost_krw'))['total'] or 0
    monthly_cost = completed.filter(
        completed_at__gte=month_start,
    ).aggregate(total=Sum('estimated_cost_krw'))['total'] or 0
    return (
        daily_cost < config.daily_ai_cost_limit_krw
        and monthly_cost < config.monthly_ai_cost_limit_krw
    )


def _locked_meter(*, user, action, year_month):
    meter, _ = UsageMeter.objects.select_for_update().get_or_create(
        user=user,
        action=action,
        year_month=year_month,
        defaults={'count': 0},
    )
    return meter


def reserve_minute_meter(*, user, amount, year_month):
    if type(amount) is not int or amount <= 0:
        raise ValueError('INVALID_CONSULTATION_MINUTE')
    plan = resolve_effective_plan(user)
    meter = _locked_meter(
        user=user,
        action='consultation_minute',
        year_month=year_month,
    )
    limit = plan.get_limit('consultation_minute')
    if limit is not None and meter.count + amount > limit:
        raise LimitExceeded('consultation_minute', meter.count, limit)
    meter.count += amount
    meter.save(update_fields=['count', 'updated_at'])
    return meter


def release_meter(*, user, action, amount, year_month):
    if action not in {'consultation_summary', 'consultation_minute'}:
        raise ValueError('INVALID_CONSULTATION_ACTION')
    if type(amount) is not int or amount <= 0:
        raise ValueError('INVALID_CONSULTATION_AMOUNT')
    meter = _locked_meter(
        user=user,
        action=action,
        year_month=year_month,
    )
    meter.count = max(0, meter.count - amount)
    meter.save(update_fields=['count', 'updated_at'])
    return meter


def assert_success_slot_available(*, user, year_month):
    plan = resolve_effective_plan(user)
    meter = _locked_meter(
        user=user,
        action='consultation_summary',
        year_month=year_month,
    )
    limit = plan.get_limit('consultation_summary')
    reserved = ConsultationSummaryRun.objects.filter(
        recording__owner=user,
        usage_year_month=year_month,
        success_count_reserved=1,
        status__in=ACTIVE_SUMMARY_STATUSES,
    ).count()
    if limit is not None and meter.count + reserved + 1 > limit:
        raise LimitExceeded('consultation_summary', meter.count, limit)
    return meter


def consume_success_meter(*, user, year_month):
    meter = _locked_meter(
        user=user,
        action='consultation_summary',
        year_month=year_month,
    )
    meter.count += 1
    meter.save(update_fields=['count', 'updated_at'])
    return meter


def usage_snapshot(*, user):
    year_month = UsageMeter.current_month()
    plan = resolve_effective_plan(user)
    meter = UsageMeter.objects.filter(
        user=user,
        action='consultation_summary',
        year_month=year_month,
    ).first()
    return {
        'year_month': year_month,
        'monthly_success_used': meter.count if meter else 0,
        'monthly_success_limit': plan.get_limit('consultation_summary'),
    }
