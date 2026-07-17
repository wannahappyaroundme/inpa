"""Private recruiting notifications and retention cleanup."""
from datetime import datetime, time, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from inpa.notifications.models import Notification, NotifType

from .models import RecruitingActivity, RecruitingCandidate, SettlementCheck


def create_recruiting_notification_once(
    *, owner_id, notif_type, title, body, dedupe_key, target_date=None
):
    """Create one private, PII-free notification and converge races to zero."""
    if Notification.objects.filter(dedupe_key=dedupe_key).exists():
        return 0
    try:
        with transaction.atomic():
            Notification.objects.create(
                owner_id=owner_id,
                notif_type=notif_type,
                title=title,
                body=body,
                target_date=target_date,
                dedupe_key=dedupe_key,
            )
    except IntegrityError:
        if Notification.objects.filter(dedupe_key=dedupe_key).exists():
            return 0
        raise
    return 1


def produce_recruiting_reminders(run_date=None):
    """Create due follow-up and settlement reminders using KST calendar days."""
    if not getattr(settings, "RECRUITING_ENABLED", False):
        return 0

    today = run_date or timezone.localdate()
    tomorrow_start = timezone.make_aware(datetime.combine(today + timedelta(days=1), time.min))
    created = 0

    owner_ids = (
        RecruitingCandidate.objects.filter(
            selection_status=RecruitingCandidate.SelectionStatus.ACTIVE,
            contact_opt_out_at__isnull=True,
            next_action_at__isnull=False,
            next_action_at__lt=tomorrow_start,
        )
        .exclude(
            stage__in=(
                RecruitingCandidate.Stage.ENDED,
                RecruitingCandidate.Stage.TEAM_JOIN,
            )
        )
        .values_list("owner_id", flat=True)
        .distinct()
    )
    for owner_id in owner_ids.iterator():
        created += create_recruiting_notification_once(
            owner_id=owner_id,
            notif_type=NotifType.RECRUITING_FOLLOWUP,
            title="다음 연락 시간이 되었어요",
            body="영입 현황에서 오늘 이어갈 대화를 확인해보세요.",
            target_date=today,
            dedupe_key=f"recruiting:followup:{owner_id}:{today.isoformat()}",
        )

    checks = (
        SettlementCheck.objects.filter(
            due_on__lte=today,
            state=SettlementCheck.State.ACTIVE,
            completed_at__isnull=True,
            candidate__stage=RecruitingCandidate.Stage.TEAM_JOIN,
            candidate__selection_status=RecruitingCandidate.SelectionStatus.ACTIVE,
            candidate__contact_opt_out_at__isnull=True,
            candidate__joined_user__isnull=False,
        )
        .select_related("candidate")
        .order_by("pk")
    )
    for check in checks.iterator():
        created += create_recruiting_notification_once(
            owner_id=check.candidate.owner_id,
            notif_type=NotifType.RECRUITING_SETTLEMENT,
            title="정착 확인 주차가 되었어요",
            body="함께 일하는 설계사의 현재 흐름을 짧게 확인해보세요.",
            target_date=check.due_on,
            dedupe_key=f"recruiting:settlement:{check.pk}",
        )
    return created


def _latest_activity_at(candidate_id):
    return (
        RecruitingActivity.objects.filter(candidate_id=candidate_id)
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )


def cleanup_expired_recruiting_candidates(now=None):
    """Delete only expired opt-out tombstones or ended, unjoined candidates."""
    now = now or timezone.now()
    candidate_ids = list(
        RecruitingCandidate.objects.filter(retention_expires_at__lte=now)
        .filter(
            Q(contact_opt_out_at__isnull=False)
            | Q(
                selection_status=RecruitingCandidate.SelectionStatus.PENDING,
                joined_user__isnull=True,
                joined_at__isnull=True,
            )
            | Q(
                contact_opt_out_at__isnull=True,
                joined_user__isnull=True,
                stage=RecruitingCandidate.Stage.ENDED,
                ended_at__isnull=False,
            )
        )
        .values_list("pk", flat=True)
    )
    deleted_candidates = 0
    retention_days = int(getattr(settings, "RECRUITING_RETENTION_DAYS", 180) or 180)

    for candidate_id in candidate_ids:
        with transaction.atomic():
            candidate = RecruitingCandidate.objects.select_for_update().filter(
                pk=candidate_id
            ).first()
            if candidate is None or candidate.retention_expires_at is None:
                continue
            if candidate.retention_expires_at > now:
                continue
            # joined_user는 현재 합류 계정, joined_at은 계정 삭제 후에도 남는 합류 증거다.
            # 어느 쪽이든 있으면 일반 지원자 개인정보 정리 대상으로 보지 않는다.
            if candidate.joined_user_id is not None or candidate.joined_at is not None:
                continue

            if candidate.contact_opt_out_at is not None:
                is_valid_tombstone = (
                    candidate.stage == RecruitingCandidate.Stage.ENDED
                    and candidate.ended_at is not None
                    and candidate.name == "정리 요청"
                    and candidate.phone == ""
                    and candidate.current_affiliation == ""
                    and candidate.region == ""
                    and not candidate.consents.exists()
                )
                if not is_valid_tombstone:
                    continue
            elif candidate.selection_status == RecruitingCandidate.SelectionStatus.PENDING:
                if candidate.joined_user_id is not None or candidate.joined_at is not None:
                    continue
            else:
                is_ended_unjoined = (
                    candidate.joined_user_id is None
                    and candidate.stage == RecruitingCandidate.Stage.ENDED
                    and candidate.ended_at is not None
                )
                if not is_ended_unjoined:
                    continue

                anchors = [candidate.ended_at]
                if candidate.last_contacted_at is not None:
                    anchors.append(candidate.last_contacted_at)
                latest_activity = _latest_activity_at(candidate.pk)
                if latest_activity is not None:
                    anchors.append(latest_activity)
                expected_expiry = max(anchors) + timedelta(days=retention_days)
                if expected_expiry > candidate.retention_expires_at:
                    candidate.retention_expires_at = expected_expiry
                    candidate.save(update_fields=["retention_expires_at", "updated_at"])
                if expected_expiry > now:
                    continue

            RecruitingActivity.objects.get_or_create(
                candidate_ref=candidate.audit_ref,
                event_type=RecruitingActivity.EventType.CANDIDATE_PURGED,
                defaults={
                    "candidate": candidate,
                    "from_stage": candidate.stage,
                    "to_stage": RecruitingCandidate.Stage.ENDED,
                    "reason_code": RecruitingActivity.ReasonCode.RETENTION,
                },
            )
            candidate.delete()
            deleted_candidates += 1
    return deleted_candidates
