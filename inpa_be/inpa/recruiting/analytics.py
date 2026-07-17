"""Recruiting-only aggregate calculations, isolated from customer analytics."""
from datetime import datetime, time, timedelta

from django.db.models import Count
from django.utils import timezone

from .models import RecruitingCandidate, SettlementCheck


def _calendar_bounds(today):
    zone = timezone.get_current_timezone()
    day_start = timezone.make_aware(datetime.combine(today, time.min), zone)
    next_day_start = day_start + timedelta(days=1)
    month_start_date = today.replace(day=1)
    if today.month == 12:
        next_month_date = today.replace(year=today.year + 1, month=1, day=1)
    else:
        next_month_date = today.replace(month=today.month + 1, day=1)
    month_start = timezone.make_aware(
        datetime.combine(month_start_date, time.min), zone
    )
    next_month_start = timezone.make_aware(
        datetime.combine(next_month_date, time.min), zone
    )
    return day_start, next_day_start, month_start, next_month_start


def candidate_metrics(owner, today=None):
    today = today or timezone.localdate()
    day_start, next_day_start, month_start, next_month_start = _calendar_bounds(today)
    visible = RecruitingCandidate.objects.filter(
        owner=owner,
        contact_opt_out_at__isnull=True,
        selection_status__in=(
            RecruitingCandidate.SelectionStatus.ACTIVE,
            RecruitingCandidate.SelectionStatus.REPLACED,
        ),
    )
    stage_counts = {stage: 0 for stage in RecruitingCandidate.Stage.values}
    for item in visible.values("stage").annotate(total=Count("pk")):
        stage_counts[item["stage"]] = item["total"]

    active = visible.filter(
        selection_status=RecruitingCandidate.SelectionStatus.ACTIVE,
    )

    actionable = active.filter(contact_opt_out_at__isnull=True).exclude(
        stage__in=(RecruitingCandidate.Stage.ENDED, RecruitingCandidate.Stage.TEAM_JOIN)
    )
    settlement_due = SettlementCheck.objects.filter(
        candidate__owner=owner,
        candidate__selection_status=RecruitingCandidate.SelectionStatus.ACTIVE,
        candidate__stage=RecruitingCandidate.Stage.TEAM_JOIN,
        candidate__contact_opt_out_at__isnull=True,
        candidate__joined_user__isnull=False,
        state=SettlementCheck.State.ACTIVE,
        completed_at__isnull=True,
        due_on__lte=today,
    ).count()
    return {
        "stage_counts": stage_counts,
        "due_today": actionable.filter(
            next_action_at__gte=day_start,
            next_action_at__lt=next_day_start,
        ).count(),
        "overdue": actionable.filter(next_action_at__lt=day_start).count(),
        "joined_this_month": active.filter(
            stage=RecruitingCandidate.Stage.TEAM_JOIN,
            joined_at__isnull=False,
            joined_at__gte=month_start,
            joined_at__lt=next_month_start,
        ).count(),
        "settlement_due": settlement_due,
    }
