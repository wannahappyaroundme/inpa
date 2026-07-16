import logging
import re
import uuid
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from inpa.accounts.team import link_agent_to_manager

from .consent_texts import RECRUITING_CONSENT_VERSION
from .models import (
    RecruitingActivity,
    RecruitingCampaign,
    RecruitingCandidate,
    RecruitingConsentLog,
    RecruitingCopyTemplate,
    RecruitingEvent,
    RecruitingPage,
    SettlementCheck,
)
from .tokens import make_leader_choice_token, read_leader_choice_token


logger = logging.getLogger(__name__)


ALLOWED_STAGE_TRANSITIONS = {
    RecruitingCandidate.Stage.NEW: {
        RecruitingCandidate.Stage.CONTACT,
        RecruitingCandidate.Stage.RECONTACT,
        RecruitingCandidate.Stage.ENDED,
    },
    RecruitingCandidate.Stage.CONTACT: {
        RecruitingCandidate.Stage.CONVERSATION,
        RecruitingCandidate.Stage.RECONTACT,
        RecruitingCandidate.Stage.ENDED,
    },
    RecruitingCandidate.Stage.CONVERSATION: {
        RecruitingCandidate.Stage.PREPARING,
        RecruitingCandidate.Stage.RECONTACT,
        RecruitingCandidate.Stage.ENDED,
    },
    RecruitingCandidate.Stage.PREPARING: {
        RecruitingCandidate.Stage.CONVERSATION,
        RecruitingCandidate.Stage.RECONTACT,
        RecruitingCandidate.Stage.ENDED,
    },
    RecruitingCandidate.Stage.TEAM_JOIN: {RecruitingCandidate.Stage.ENDED},
    RecruitingCandidate.Stage.RECONTACT: {
        RecruitingCandidate.Stage.CONTACT,
        RecruitingCandidate.Stage.ENDED,
    },
    RecruitingCandidate.Stage.ENDED: {RecruitingCandidate.Stage.RECONTACT},
}


STAGE_EVENT_TYPES = {
    RecruitingCandidate.Stage.CONTACT: RecruitingEvent.EventType.FIRST_CONTACT,
    RecruitingCandidate.Stage.CONVERSATION: RecruitingEvent.EventType.CONVERSATION_STARTED,
    RecruitingCandidate.Stage.PREPARING: RecruitingEvent.EventType.PREPARING_STARTED,
}


class TeamAccountManagementRequired(Exception):
    pass


class RecruitingApplicationLimitReached(Exception):
    pass


class RecruitingLinkUnavailable(Exception):
    pass


class PendingSubmissionVerificationRequired(Exception):
    pass


RECRUITING_APPLICATION_DAILY_CAP = 30
SETTLEMENT_DAYS = {1: 7, 4: 28, 8: 56, 13: 91}


@dataclass(frozen=True)
class SubmissionResult:
    candidate: RecruitingCandidate
    created: bool
    choice_required: bool = False
    choice_token: str | None = None
    prior_candidate: RecruitingCandidate | None = None


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("82"):
        digits = "0" + digits[2:]
    if len(digits) not in (10, 11):
        raise ValidationError("연락 가능한 휴대전화 번호를 확인해주세요.")
    return digits


def _schedule_event(*, owner, event_type, campaign=None, candidate=None, metadata=None):
    owner_id = owner.pk
    campaign_id = campaign.pk if campaign else None
    candidate_id = candidate.pk if candidate else None
    channel = campaign.channel if campaign else ""
    safe_metadata = dict(metadata or {})

    def create_event():
        try:
            RecruitingEvent.objects.create(
                owner_id=owner_id,
                campaign_id=campaign_id,
                candidate_id=candidate_id,
                event_type=event_type,
                channel=channel,
                metadata=safe_metadata,
            )
        except Exception as exc:  # 계측 실패는 지원·단계 변경을 깨지 않는다.
            logger.warning("recruiting event write skipped: %s", type(exc).__name__)

    transaction.on_commit(create_event)


def get_or_create_recruiting_page(user):
    page, created = RecruitingPage.objects.get_or_create(owner=user)
    update_fields = []
    if created or page.headline_template_id is None:
        headline = RecruitingCopyTemplate.objects.filter(
            kind=RecruitingCopyTemplate.Kind.HEADLINE,
            is_active=True,
        ).order_by("sort_order", "pk").first()
        if headline is not None and page.headline_template_id != headline.pk:
            page.headline_template = headline
            update_fields.append("headline_template")
    if update_fields:
        update_fields.append("updated_at")
        page.save(update_fields=update_fields)
    campaign, _ = RecruitingCampaign.objects.get_or_create(
        page=page,
        channel=RecruitingCampaign.Channel.RELATIONSHIP,
        is_active=True,
        defaults={"name": "개인 소개"},
    )
    return page, campaign


def _coerce_submission_key(value):
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValidationError("지원 내용을 다시 확인해주세요.") from exc


def _valid_prior_candidate(*, manage_token, phone):
    if not manage_token:
        return None
    try:
        token = uuid.UUID(str(manage_token))
    except (TypeError, ValueError, AttributeError):
        return None
    return RecruitingCandidate.objects.select_related("owner__profile").filter(
        manage_token=token,
        phone=phone,
        selection_status=RecruitingCandidate.SelectionStatus.ACTIVE,
        contact_opt_out_at__isnull=True,
    ).first()


def _existing_submission_result(*, existing, data, phone):
    prior = _valid_prior_candidate(
        manage_token=data.get("prior_manage_token"),
        phone=phone,
    )
    if existing.selection_status == RecruitingCandidate.SelectionStatus.PENDING:
        if (
            prior is not None
            and prior.identity_ref == existing.identity_ref
            and prior.owner_id != existing.owner_id
        ):
            return SubmissionResult(
                candidate=existing,
                created=False,
                choice_required=True,
                choice_token=make_leader_choice_token(
                    old_candidate_id=prior.pk,
                    new_candidate_id=existing.pk,
                ),
                prior_candidate=prior,
            )
        raise PendingSubmissionVerificationRequired
    if existing.selection_status != RecruitingCandidate.SelectionStatus.ACTIVE:
        raise PendingSubmissionVerificationRequired
    return SubmissionResult(candidate=existing, created=False)


@transaction.atomic
def create_candidate_submission(*, campaign, data, ip_address=None):
    if not data.get("agreed"):
        raise ValidationError("개인정보 수집과 영입 상담 연락에 동의하면 바로 지원할 수 있어요.")
    phone = normalize_phone(data.get("phone", ""))
    submission_key = _coerce_submission_key(data.get("submission_key"))
    # PostgreSQL은 nullable OUTER JOIN이 붙은 FOR UPDATE를 거부하므로 본체 행만 잠근다.
    campaign = RecruitingCampaign.objects.select_for_update().get(pk=campaign.pk)
    page = RecruitingPage.objects.select_for_update().get(pk=campaign.page_id)
    if not campaign.is_active or not page.is_published:
        raise RecruitingLinkUnavailable

    existing = RecruitingCandidate.objects.select_related("owner__profile").filter(
        campaign=campaign,
        submission_key=submission_key,
    ).first()
    if existing is not None:
        return _existing_submission_result(existing=existing, data=data, phone=phone)

    prior = _valid_prior_candidate(
        manage_token=data.get("prior_manage_token"),
        phone=phone,
    )
    owner = page.owner
    if prior is not None and prior.owner_id == owner.pk:
        return SubmissionResult(candidate=prior, created=False)

    is_pending = prior is not None and prior.owner_id != owner.pk
    todays_submissions = RecruitingCandidate.objects.filter(
        campaign=campaign,
        created_at__date=timezone.localdate(),
    ).count()
    if todays_submissions >= RECRUITING_APPLICATION_DAILY_CAP:
        raise RecruitingApplicationLimitReached
    try:
        with transaction.atomic():
            candidate = RecruitingCandidate.objects.create(
                owner=owner,
                campaign=campaign,
                name=str(data.get("name", "")).strip()[:30],
                phone=phone,
                career_band=data.get("career_band"),
                current_affiliation=str(data.get("current_affiliation", "")).strip()[:100],
                region=str(data.get("region", "")).strip()[:60],
                contact_window=data.get("contact_window"),
                submission_key=submission_key,
                identity_ref=prior.identity_ref if is_pending else uuid.uuid4(),
                selection_status=(
                    RecruitingCandidate.SelectionStatus.PENDING
                    if is_pending
                    else RecruitingCandidate.SelectionStatus.ACTIVE
                ),
                next_action="" if is_pending else RecruitingCandidate.NextAction.CALL,
                next_action_at=None if is_pending else timezone.now() + timedelta(hours=24),
            )
    except IntegrityError:
        existing = RecruitingCandidate.objects.select_related("owner__profile").filter(
            campaign=campaign,
            submission_key=submission_key,
        ).first()
        if existing is None:
            raise
        return _existing_submission_result(existing=existing, data=data, phone=phone)
    RecruitingConsentLog.objects.create(
        candidate=candidate,
        doc_version=RECRUITING_CONSENT_VERSION,
        ip_address=ip_address,
    )
    if is_pending:
        return SubmissionResult(
            candidate=candidate,
            created=True,
            choice_required=True,
            choice_token=make_leader_choice_token(
                old_candidate_id=prior.pk,
                new_candidate_id=candidate.pk,
            ),
            prior_candidate=prior,
        )

    _schedule_event(
        owner=owner,
        campaign=campaign,
        candidate=candidate,
        event_type=RecruitingEvent.EventType.APPLICATION_SUBMITTED,
        metadata={"source": campaign.channel},
    )
    return SubmissionResult(candidate=candidate, created=True)


@transaction.atomic
def apply_leader_choice(*, token, choice):
    if choice not in {"keep_current", "switch_to_new"}:
        raise ValidationError("이어갈 담당자를 선택해주세요.")
    old_id, new_id = read_leader_choice_token(token)
    locked = {
        item.pk: item
        for item in RecruitingCandidate.objects.select_for_update().filter(
            pk__in=(old_id, new_id)
        )
    }
    old = locked.get(old_id)
    new = locked.get(new_id)
    if (
        old is None
        or new is None
        or old.pk == new.pk
        or old.phone != new.phone
        or not old.phone
        or old.identity_ref != new.identity_ref
        or old.selection_status != RecruitingCandidate.SelectionStatus.ACTIVE
        or old.contact_opt_out_at is not None
        or new.selection_status != RecruitingCandidate.SelectionStatus.PENDING
    ):
        raise ValidationError("현재 지원 상태를 새 링크에서 다시 확인해주세요.")

    now = timezone.now()
    if choice == "keep_current":
        new.selection_status = RecruitingCandidate.SelectionStatus.DECLINED
        new.stage = RecruitingCandidate.Stage.ENDED
        new.ended_at = now
        new.next_action = ""
        new.next_action_at = None
        new.retention_expires_at = now + timedelta(days=settings.RECRUITING_RETENTION_DAYS)
        new.save(
            update_fields=[
                "selection_status",
                "stage",
                "ended_at",
                "next_action",
                "next_action_at",
                "retention_expires_at",
                "updated_at",
            ]
        )
        RecruitingActivity.objects.create(
            candidate=new,
            candidate_ref=new.audit_ref,
            event_type=RecruitingActivity.EventType.LEADER_CHANGED,
            from_stage=RecruitingCandidate.Stage.NEW,
            to_stage=RecruitingCandidate.Stage.ENDED,
        )
        return old

    previous_old_stage = old.stage
    old.selection_status = RecruitingCandidate.SelectionStatus.REPLACED
    old.stage = RecruitingCandidate.Stage.ENDED
    old.ended_at = now
    old.next_action = ""
    old.next_action_at = None
    old.retention_expires_at = now + timedelta(days=settings.RECRUITING_RETENTION_DAYS)
    old.name = "담당 변경"
    old.phone = ""
    old.current_affiliation = ""
    old.region = ""
    old.save(
        update_fields=[
            "selection_status",
            "stage",
            "ended_at",
            "next_action",
            "next_action_at",
            "retention_expires_at",
            "name",
            "phone",
            "current_affiliation",
            "region",
            "updated_at",
        ]
    )
    new.selection_status = RecruitingCandidate.SelectionStatus.ACTIVE
    new.next_action = RecruitingCandidate.NextAction.CALL
    new.next_action_at = now + timedelta(hours=24)
    new.save(update_fields=["selection_status", "next_action", "next_action_at", "updated_at"])
    RecruitingActivity.objects.bulk_create(
        [
            RecruitingActivity(
                candidate=old,
                candidate_ref=old.audit_ref,
                event_type=RecruitingActivity.EventType.LEADER_CHANGED,
                from_stage=previous_old_stage,
                to_stage=RecruitingCandidate.Stage.ENDED,
            ),
            RecruitingActivity(
                candidate=new,
                candidate_ref=new.audit_ref,
                event_type=RecruitingActivity.EventType.LEADER_CHANGED,
                from_stage=RecruitingCandidate.Stage.NEW,
                to_stage=RecruitingCandidate.Stage.NEW,
            ),
        ]
    )
    _schedule_event(
        owner=new.owner,
        campaign=new.campaign,
        candidate=new,
        event_type=RecruitingEvent.EventType.APPLICATION_SUBMITTED,
        metadata={"source": new.campaign.channel if new.campaign else ""},
    )
    return new


@transaction.atomic
def transition_candidate(*, candidate, actor, to_stage, next_action="", next_action_at=None):
    locked = type(candidate).objects.select_for_update().get(pk=candidate.pk)
    if (
        locked.selection_status != locked.SelectionStatus.ACTIVE
        or locked.contact_opt_out_at
    ):
        raise ValidationError("현재 담당 중인 지원자만 다음 단계를 이어갈 수 있어요.")
    if to_stage == locked.Stage.TEAM_JOIN:
        raise ValidationError("팀 합류는 합류 링크를 수락하면 자동으로 기록돼요.")
    if to_stage not in ALLOWED_STAGE_TRANSITIONS.get(locked.stage, set()):
        raise ValidationError("현재 단계에서 선택할 수 있는 다음 흐름을 확인해주세요.")
    previous = locked.stage
    locked.stage = to_stage
    locked.next_action = next_action
    locked.next_action_at = next_action_at
    if to_stage == locked.Stage.CONTACT:
        locked.last_contacted_at = timezone.now()
    if to_stage == locked.Stage.RECONTACT:
        locked.ended_at = None
        locked.retention_expires_at = None
    if to_stage == locked.Stage.ENDED:
        locked.ended_at = timezone.now()
        anchor = max(locked.ended_at, locked.last_contacted_at or locked.ended_at)
        locked.retention_expires_at = anchor + timedelta(days=settings.RECRUITING_RETENTION_DAYS)
    locked.save(
        update_fields=[
            "stage",
            "next_action",
            "next_action_at",
            "last_contacted_at",
            "ended_at",
            "retention_expires_at",
            "updated_at",
        ]
    )
    RecruitingActivity.objects.create(
        candidate=locked,
        candidate_ref=locked.audit_ref,
        actor=actor,
        event_type=RecruitingActivity.EventType.STAGE_CHANGED,
        from_stage=previous,
        to_stage=to_stage,
    )
    event_type = STAGE_EVENT_TYPES.get(to_stage)
    if event_type:
        _schedule_event(
            owner=locked.owner,
            campaign=locked.campaign,
            candidate=locked,
            event_type=event_type,
            metadata={"previous_stage": previous},
        )
    return locked


@transaction.atomic
def stop_candidate_contact(*, candidate):
    locked = type(candidate).objects.select_for_update().get(pk=candidate.pk)
    if locked.joined_user_id is not None or locked.stage == locked.Stage.TEAM_JOIN:
        raise TeamAccountManagementRequired
    if locked.contact_opt_out_at is not None:
        return locked
    if locked.selection_status != locked.SelectionStatus.ACTIVE:
        raise ValidationError("신청 관리 링크에서 현재 연락 상태를 확인해주세요.")
    previous_stage = locked.stage
    now = timezone.now()
    locked.contact_opt_out_at = now
    locked.stage = locked.Stage.ENDED
    locked.ended_at = now
    locked.retention_expires_at = now + timedelta(days=settings.RECRUITING_TOMBSTONE_DAYS)
    locked.next_action = ""
    locked.next_action_at = None
    locked.name = "정리 요청"
    locked.phone = ""
    locked.current_affiliation = ""
    locked.region = ""
    locked.save(
        update_fields=[
            "contact_opt_out_at",
            "stage",
            "ended_at",
            "retention_expires_at",
            "next_action",
            "next_action_at",
            "name",
            "phone",
            "current_affiliation",
            "region",
            "updated_at",
        ]
    )
    locked.consents.all().delete()
    RecruitingActivity.objects.create(
        candidate=locked,
        candidate_ref=locked.audit_ref,
        event_type=RecruitingActivity.EventType.CONTACT_STOPPED,
        from_stage=previous_stage,
        to_stage=RecruitingCandidate.Stage.ENDED,
    )
    return locked


@transaction.atomic
def accept_team_join(*, candidate, agent, expected_owner_id=None, confirm_switch=False):
    """Link profiles first, then serialize every candidate identity row.

    Profile locks are the global order for two competing join links. Any candidate
    revalidation failure rolls the profile change back with this outer transaction.
    """
    expected_owner_id = expected_owner_id or candidate.owner_id
    team_result = link_agent_to_manager(
        agent=agent,
        manager=candidate.owner,
        confirm_switch=confirm_switch,
    )

    locked_group = list(
        RecruitingCandidate.objects.select_for_update()
        .filter(Q(identity_ref=candidate.identity_ref) | Q(joined_user=agent))
        .order_by("pk")
    )
    locked = next((row for row in locked_group if row.pk == candidate.pk), None)
    if locked is None or locked.owner_id != expected_owner_id:
        raise ValueError("candidate_owner_mismatch")
    if locked.joined_user_id == agent.pk and locked.stage == locked.Stage.TEAM_JOIN:
        return locked, False
    if locked.joined_user_id is not None and locked.joined_user_id != agent.pk:
        raise ValueError("candidate_joined_to_another_account")
    if (
        locked.selection_status != locked.SelectionStatus.ACTIVE
        or locked.contact_opt_out_at is not None
        or locked.stage == locked.Stage.ENDED
    ):
        raise ValueError("inactive_candidate_selection")

    now = timezone.now()
    joined_date = timezone.localdate()
    previous_stage = locked.stage
    locked.joined_user = agent
    locked.joined_at = now
    locked.stage = locked.Stage.TEAM_JOIN
    locked.name = "팀 합류 설계사"
    locked.phone = ""
    locked.current_affiliation = ""
    locked.region = ""
    locked.next_action = ""
    locked.next_action_at = None
    locked.save(
        update_fields=[
            "joined_user",
            "joined_at",
            "stage",
            "name",
            "phone",
            "current_affiliation",
            "region",
            "next_action",
            "next_action_at",
            "updated_at",
        ]
    )
    locked.consents.filter(revoked_at__isnull=True).update(revoked_at=now)
    for week, days in SETTLEMENT_DAYS.items():
        SettlementCheck.objects.get_or_create(
            candidate=locked,
            week=week,
            defaults={"due_on": joined_date + timedelta(days=days)},
        )

    activities = [
        RecruitingActivity(
            candidate=locked,
            candidate_ref=locked.audit_ref,
            actor=agent,
            event_type=RecruitingActivity.EventType.TEAM_JOINED,
            from_stage=previous_stage,
            to_stage=RecruitingCandidate.Stage.TEAM_JOIN,
        )
    ]
    previous_rows = [
        row
        for row in locked_group
        if row.pk != locked.pk and row.stage != RecruitingCandidate.Stage.ENDED
    ]
    for previous in previous_rows:
        previous_stage = previous.stage
        previous.selection_status = RecruitingCandidate.SelectionStatus.REPLACED
        previous.stage = RecruitingCandidate.Stage.ENDED
        previous.ended_at = now
        previous.retention_expires_at = now + timedelta(days=settings.RECRUITING_RETENTION_DAYS)
        previous.name = "담당자 변경"
        previous.phone = ""
        previous.current_affiliation = ""
        previous.region = ""
        previous.next_action = ""
        previous.next_action_at = None
        previous.save(
            update_fields=[
                "selection_status",
                "stage",
                "ended_at",
                "retention_expires_at",
                "name",
                "phone",
                "current_affiliation",
                "region",
                "next_action",
                "next_action_at",
                "updated_at",
            ]
        )
        previous.consents.filter(revoked_at__isnull=True).update(revoked_at=now)
        previous.settlement_checks.filter(completed_at__isnull=True).update(
            state=SettlementCheck.State.STOPPED,
            blocker=SettlementCheck.Blocker.NONE,
            next_support=SettlementCheck.NextSupport.CLOSE,
            completed_at=now,
            updated_at=now,
        )
        activities.append(
            RecruitingActivity(
                candidate=previous,
                candidate_ref=previous.audit_ref,
                event_type=RecruitingActivity.EventType.LEADER_CHANGED,
                from_stage=previous_stage,
                to_stage=RecruitingCandidate.Stage.ENDED,
            )
        )
    RecruitingActivity.objects.bulk_create(activities)
    _schedule_event(
        owner=locked.owner,
        campaign=locked.campaign,
        candidate=locked,
        event_type=RecruitingEvent.EventType.TEAM_JOIN,
        metadata={},
    )
    if team_result.promoted_now:
        _schedule_event(
            owner=locked.owner,
            event_type=RecruitingEvent.EventType.MANAGER_PROMOTED,
            metadata={},
        )
    return locked, True


@transaction.atomic
def complete_settlement_check(*, check, owner, state, blocker="", next_support=""):
    locked = SettlementCheck.objects.select_for_update().get(pk=check.pk)
    candidate = RecruitingCandidate.objects.get(pk=locked.candidate_id)
    if candidate.owner_id != owner.pk:
        raise ValueError("settlement_owner_mismatch")
    if locked.completed_at is not None:
        return locked

    valid_states = set(SettlementCheck.State.values)
    if state not in valid_states:
        raise ValidationError("정착 상태를 다시 선택해주세요.")
    if state == SettlementCheck.State.SUPPORT_NEEDED:
        if blocker in {"", SettlementCheck.Blocker.NONE} or not next_support:
            raise ValidationError("필요한 도움과 다음 지원을 함께 선택해주세요.")
    elif state == SettlementCheck.State.STOPPED:
        blocker = SettlementCheck.Blocker.NONE
        next_support = SettlementCheck.NextSupport.CLOSE
    else:
        blocker = SettlementCheck.Blocker.NONE
        next_support = SettlementCheck.NextSupport.SCHEDULE_ONLY

    now = timezone.now()
    locked.state = state
    locked.blocker = blocker
    locked.next_support = next_support
    locked.completed_at = now
    locked.save(
        update_fields=["state", "blocker", "next_support", "completed_at", "updated_at"]
    )
    if state == SettlementCheck.State.STOPPED:
        future = list(
            SettlementCheck.objects.select_for_update()
            .filter(
                candidate_id=candidate.pk,
                week__gt=locked.week,
                completed_at__isnull=True,
            )
            .order_by("pk")
        )
        for item in future:
            item.state = SettlementCheck.State.STOPPED
            item.blocker = SettlementCheck.Blocker.NONE
            item.next_support = SettlementCheck.NextSupport.CLOSE
            item.completed_at = now
            item.updated_at = now
        if future:
            SettlementCheck.objects.bulk_update(
                future,
                ["state", "blocker", "next_support", "completed_at", "updated_at"],
            )

    RecruitingActivity.objects.create(
        candidate=candidate,
        candidate_ref=candidate.audit_ref,
        actor=owner,
        event_type=RecruitingActivity.EventType.SETTLEMENT_COMPLETED,
        from_stage=RecruitingCandidate.Stage.TEAM_JOIN,
        to_stage=RecruitingCandidate.Stage.TEAM_JOIN,
    )
    RecruitingEvent.objects.create(
        owner=owner,
        campaign=candidate.campaign,
        candidate=candidate,
        event_type=RecruitingEvent.EventType.SETTLEMENT_COMPLETED,
        channel=candidate.campaign.channel if candidate.campaign else "",
        metadata={"week": locked.week, "state": locked.state},
    )
    return locked
