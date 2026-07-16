import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class RecruitingCopyTemplate(models.Model):
    class Kind(models.TextChoices):
        HEADLINE = "headline", "첫 문장"
        SUPPORT = "support", "정착 지원"
        FAQ = "faq", "자주 묻는 질문"
        SHARE = "share", "공유 문구"

    code = models.SlugField(max_length=60, unique=True)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    title = models.CharField(max_length=80)
    body = models.CharField(max_length=300)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"recruiting-copy-template:{self.pk}"


class RecruitingPage(models.Model):
    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="recruiting_page",
    )
    headline_template = models.ForeignKey(
        RecruitingCopyTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="headline_pages",
    )
    activity_region = models.CharField(max_length=60, blank=True)
    is_published = models.BooleanField(default=False)
    templates = models.ManyToManyField(RecruitingCopyTemplate, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"recruiting-page:{self.pk}"


class RecruitingCampaign(models.Model):
    class Channel(models.TextChoices):
        RELATIONSHIP = "relationship", "개인 소개"
        THREADS = "threads", "Threads"
        TIKTOK = "tiktok", "TikTok"
        INSTAGRAM = "instagram", "Instagram"
        SARAMIN = "saramin", "사람인"
        JOBKOREA = "jobkorea", "잡코리아"
        INPA_CONTENT = "inpa_content", "인파 콘텐츠"

    page = models.ForeignKey(
        RecruitingPage,
        on_delete=models.CASCADE,
        related_name="campaigns",
    )
    name = models.CharField(max_length=60)
    channel = models.CharField(max_length=20, choices=Channel.choices)
    public_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("page", "channel"),
                condition=models.Q(channel="relationship", is_active=True),
                name="uniq_recruiting_relationship_campaign",
            )
        ]

    def __str__(self):
        return f"recruiting-campaign:{self.pk}"


class RecruitingCandidate(models.Model):
    class CareerBand(models.TextChoices):
        UNDER_ONE = "under_1", "1년 미만"
        ONE_TO_THREE = "1_3", "1~3년"
        THREE_TO_FIVE = "3_5", "3~5년"
        FIVE_TO_TEN = "5_10", "5~10년"
        TEN_PLUS = "10_plus", "10년 이상"

    class ContactWindow(models.TextChoices):
        MORNING = "morning", "오전"
        AFTERNOON = "afternoon", "오후"
        EVENING = "evening", "저녁"
        ANYTIME = "anytime", "언제든"

    class SelectionStatus(models.TextChoices):
        PENDING = "pending", "선택 대기"
        ACTIVE = "active", "진행 중"
        REPLACED = "replaced", "다른 담당자 연결"
        DECLINED = "declined", "진행 종료"

    class Stage(models.TextChoices):
        NEW = "new", "새 지원"
        CONTACT = "contact", "연락"
        CONVERSATION = "conversation", "대화·면담"
        PREPARING = "preparing", "위촉 준비"
        TEAM_JOIN = "team_join", "팀 합류"
        RECONTACT = "recontact", "다시 연락"
        ENDED = "ended", "종료"

    class NextAction(models.TextChoices):
        CALL = "call", "전화"
        MESSAGE = "message", "메시지"
        MEETING = "meeting", "미팅"
        FOLLOW_UP = "follow_up", "다시 확인"
        NONE = "none", "없음"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="recruiting_candidates",
    )
    campaign = models.ForeignKey(
        RecruitingCampaign,
        on_delete=models.SET_NULL,
        null=True,
        related_name="candidates",
    )
    name = models.CharField(max_length=30)
    phone = models.CharField(max_length=20, db_index=True)
    career_band = models.CharField(max_length=20, choices=CareerBand.choices)
    current_affiliation = models.CharField(max_length=100, blank=True)
    region = models.CharField(max_length=60)
    contact_window = models.CharField(max_length=20, choices=ContactWindow.choices)
    submission_key = models.UUIDField(default=uuid.uuid4, db_index=True, editable=False)
    audit_ref = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    identity_ref = models.UUIDField(default=uuid.uuid4, db_index=True, editable=False)
    selection_status = models.CharField(
        max_length=20,
        choices=SelectionStatus.choices,
        default=SelectionStatus.ACTIVE,
    )
    stage = models.CharField(max_length=20, choices=Stage.choices, default=Stage.NEW)
    next_action = models.CharField(max_length=30, choices=NextAction.choices, blank=True)
    next_action_at = models.DateTimeField(null=True, blank=True)
    last_contacted_at = models.DateTimeField(null=True, blank=True)
    joined_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="accepted_recruiting_candidates",
    )
    joined_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    retention_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    contact_opt_out_at = models.DateTimeField(null=True, blank=True)
    manage_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=("owner", "stage", "next_action_at")),
            models.Index(fields=("owner", "phone")),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("campaign", "submission_key"),
                name="uniq_recruiting_campaign_submission",
            )
        ]

    def save(self, *args, **kwargs):
        self.phone = "".join(character for character in self.phone if character.isdigit())
        super().save(*args, **kwargs)

    def __str__(self):
        return f"candidate:{self.pk}"


class RecruitingConsentLog(models.Model):
    candidate = models.ForeignKey(
        RecruitingCandidate,
        on_delete=models.CASCADE,
        related_name="consents",
    )
    scope = models.CharField(max_length=30, default="recruiting_contact")
    doc_version = models.CharField(max_length=30)
    agreed_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    def __str__(self):
        return f"recruiting-consent:{self.pk}"


class RecruitingActivity(models.Model):
    class EventType(models.TextChoices):
        STAGE_CHANGED = "stage_changed", "단계 변경"
        CONTACT_STOPPED = "contact_stopped", "연락 중단"
        LEADER_CHANGED = "leader_changed", "담당 변경"
        TEAM_JOINED = "team_joined", "팀 합류"
        SETTLEMENT_COMPLETED = "settlement_completed", "정착 확인"
        CANDIDATE_PURGED = "candidate_purged", "정보 정리"

    candidate = models.ForeignKey(
        RecruitingCandidate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activities",
    )
    candidate_ref = models.UUIDField(db_index=True, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    event_type = models.CharField(max_length=30, choices=EventType.choices)
    from_stage = models.CharField(max_length=20, blank=True)
    to_stage = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"recruiting-activity:{self.pk}"


class SettlementCheck(models.Model):
    class State(models.TextChoices):
        ACTIVE = "active", "활동 중"
        SUPPORT_NEEDED = "support_needed", "지원 필요"
        STOPPED = "stopped", "중단"

    class Blocker(models.TextChoices):
        CUSTOMER_PROSPECTING = "customer_prospecting", "고객 발굴"
        CONSULTATION_PREP = "consultation_prep", "상담 준비"
        PRODUCT_UNDERSTANDING = "product_understanding", "상품 이해"
        WORK_TOOLS = "work_tools", "업무 도구"
        TIME_MANAGEMENT = "time_management", "시간 관리"
        ORGANIZATION_ADJUSTMENT = "organization_adjustment", "조직 적응"
        PERSONAL = "personal", "개인 사정"
        NONE = "none", "해당 없음"

    class NextSupport(models.TextChoices):
        CONSULTATION_PREP = "consultation_prep", "상담 준비"
        TRAINING = "training", "교육"
        ACTIVITY_PLAN = "activity_plan", "활동 계획"
        TOOL_HELP = "tool_help", "도구 도움"
        LEADER_MEETING = "leader_meeting", "리더 미팅"
        SCHEDULE_ONLY = "schedule_only", "일정만 잡기"
        CLOSE = "close", "마무리"

    candidate = models.ForeignKey(
        RecruitingCandidate,
        on_delete=models.CASCADE,
        related_name="settlement_checks",
    )
    week = models.PositiveSmallIntegerField(
        choices=((1, "1주"), (4, "4주"), (8, "8주"), (13, "13주"))
    )
    due_on = models.DateField(db_index=True)
    state = models.CharField(max_length=20, choices=State.choices, default=State.ACTIVE)
    blocker = models.CharField(max_length=30, choices=Blocker.choices, blank=True)
    next_support = models.CharField(max_length=30, choices=NextSupport.choices, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("candidate", "week"),
                name="uniq_candidate_settlement_week",
            )
        ]

    def __str__(self):
        return f"settlement-check:{self.pk}"


RECRUITING_EVENT_METADATA_KEYS = frozenset(
    {"source", "week", "state", "previous_stage"}
)


def validate_recruiting_event_metadata(value):
    if not isinstance(value, dict):
        raise ValidationError("metadata must be an object")
    if set(value) - RECRUITING_EVENT_METADATA_KEYS:
        raise ValidationError("metadata contains an unsupported key")

    allowed_values = {
        "source": set(RecruitingCampaign.Channel.values),
        "week": {1, 4, 8, 13},
        "state": set(SettlementCheck.State.values),
        "previous_stage": set(RecruitingCandidate.Stage.values),
    }
    for key, item in value.items():
        valid_type = type(item) is int if key == "week" else isinstance(item, str)
        if not valid_type or item not in allowed_values[key]:
            raise ValidationError(f"metadata contains an unsupported {key} value")


class RecruitingEvent(models.Model):
    class EventType(models.TextChoices):
        PAGE_PUBLISHED = "page_published", "페이지 공개"
        LINK_COPIED = "link_copied", "링크 복사"
        PAGE_VIEW = "page_view", "페이지 방문"
        APPLICATION_SUBMITTED = "application_submitted", "지원 제출"
        FIRST_CONTACT = "first_contact", "첫 연락"
        CONVERSATION_STARTED = "conversation_started", "대화 시작"
        PREPARING_STARTED = "preparing_started", "위촉 준비 시작"
        TEAM_JOIN = "team_join", "팀 합류"
        SETTLEMENT_COMPLETED = "settlement_completed", "정착 확인"
        MANAGER_PROMOTED = "manager_promoted", "관리자 성장"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="recruiting_events",
    )
    campaign = models.ForeignKey(
        RecruitingCampaign,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    candidate = models.ForeignKey(
        RecruitingCandidate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    event_type = models.CharField(max_length=40, choices=EventType.choices, db_index=True)
    channel = models.CharField(
        max_length=20,
        choices=RecruitingCampaign.Channel.choices,
        blank=True,
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        validators=[validate_recruiting_event_metadata],
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self):
        return f"recruiting-event:{self.pk}"
