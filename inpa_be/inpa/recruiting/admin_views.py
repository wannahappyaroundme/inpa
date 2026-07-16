"""De-identified recruiting operations API. No rollout-flag dependency."""
import re
from datetime import datetime, time

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from inpa.accounts.models import Profile
from inpa.billing.credit import resolve_effective_plan
from inpa.billing.models import Subscription
from inpa.core.permissions import IsAdmin

from .models import (
    RecruitingActivity,
    RecruitingCandidate,
    RecruitingCopyTemplate,
    RecruitingEvent,
)
from .services import anonymize_candidate_for_tombstone


class _StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {key: "화면에 있는 항목만 입력해주세요." for key in sorted(unknown)}
            )
        return super().to_internal_value(data)


class AdminCandidatePurgeSerializer(_StrictSerializer):
    reason = serializers.ChoiceField(
        choices=("user_request", "retention", "admin_correction"),
        error_messages={"invalid_choice": "정보 정리 사유를 다시 선택해주세요."},
    )


class AdminRecruitingTemplateReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = RecruitingCopyTemplate
        fields = (
            "id",
            "code",
            "kind",
            "title",
            "body",
            "is_active",
            "sort_order",
        )


class _TemplateValidationMixin:
    def validate_code(self, value):
        if not re.fullmatch(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", value or ""):
            raise serializers.ValidationError(
                "영문 소문자와 숫자, 하이픈으로 코드를 입력해주세요."
            )
        if RecruitingCopyTemplate.objects.filter(code=value).exists():
            raise serializers.ValidationError(
                "이미 사용 중인 코드예요. 다른 코드를 입력해주세요."
            )
        return value


class AdminRecruitingTemplateCreateSerializer(_TemplateValidationMixin, _StrictSerializer):
    code = serializers.CharField(max_length=60, trim_whitespace=True)
    kind = serializers.ChoiceField(
        choices=RecruitingCopyTemplate.Kind.choices,
        error_messages={"invalid_choice": "문구 종류를 다시 선택해주세요."},
    )
    title = serializers.CharField(max_length=80, trim_whitespace=True)
    body = serializers.CharField(max_length=300, trim_whitespace=True)
    is_active = serializers.BooleanField(default=True)
    sort_order = serializers.IntegerField(min_value=0, max_value=32767, default=0)

    def create(self, validated_data):
        return RecruitingCopyTemplate.objects.create(**validated_data)


class AdminRecruitingTemplateUpdateSerializer(_StrictSerializer):
    title = serializers.CharField(max_length=80, trim_whitespace=True, required=False)
    body = serializers.CharField(max_length=300, trim_whitespace=True, required=False)
    is_active = serializers.BooleanField(required=False)
    sort_order = serializers.IntegerField(
        min_value=0,
        max_value=32767,
        required=False,
    )

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError(
                "바꿀 문구나 사용 상태를 선택해주세요."
            )
        return attrs

    def update(self, instance, validated_data):
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save(update_fields=[*validated_data, "updated_at"])
        return instance


class AdminRecruitingAuditSerializer(serializers.ModelSerializer):
    class Meta:
        model = RecruitingActivity
        fields = (
            "candidate_ref",
            "event_type",
            "from_stage",
            "to_stage",
            "actor_id",
            "created_at",
        )


def _month_bounds(today):
    zone = timezone.get_current_timezone()
    first = today.replace(day=1)
    if today.month == 12:
        next_first = today.replace(year=today.year + 1, month=1, day=1)
    else:
        next_first = today.replace(month=today.month + 1, day=1)
    return (
        timezone.make_aware(datetime.combine(first, time.min), zone),
        timezone.make_aware(datetime.combine(next_first, time.min), zone),
    )


def _mask_name(value):
    value = (value or "").strip()
    if not value:
        return "-"
    if len(value) == 1:
        return "*"
    if len(value) == 2:
        return f"{value[0]}*"
    return f"{value[0]}{'*' * (len(value) - 2)}{value[-1]}"


def _mask_phone(value):
    raw = (value or "").strip()
    if not raw:
        return "-"
    digits = "".join(character for character in raw if character.isdigit())
    if len(digits) not in (10, 11):
        return "***-****-****"
    return f"***-****-{digits[-4:]}"


def _display_name(profile):
    return (profile.name or profile.affiliation or "설계사").strip()


class AdminRecruitingSummaryView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        month_start, next_month_start = _month_bounds(timezone.localdate())
        events = RecruitingEvent.objects.filter(
            created_at__gte=month_start,
            created_at__lt=next_month_start,
        )
        active_candidate_events = events.filter(
            candidate__selection_status=RecruitingCandidate.SelectionStatus.ACTIVE
        )
        return Response(
            {
                "visits": events.filter(
                    event_type=RecruitingEvent.EventType.PAGE_VIEW
                ).count(),
                "applications": active_candidate_events.filter(
                    event_type=RecruitingEvent.EventType.APPLICATION_SUBMITTED
                ).count(),
                "joins": active_candidate_events.filter(
                    event_type=RecruitingEvent.EventType.TEAM_JOIN
                ).count(),
                "settlements_completed": active_candidate_events.filter(
                    event_type=RecruitingEvent.EventType.SETTLEMENT_COMPLETED
                ).count(),
                "manager_promotions": events.filter(
                    event_type=RecruitingEvent.EventType.MANAGER_PROMOTED
                ).count(),
                "recruiting_enabled": bool(
                    getattr(settings, "RECRUITING_ENABLED", False)
                ),
                "retention_days": int(
                    getattr(settings, "RECRUITING_RETENTION_DAYS", 180)
                ),
                "tombstone_days": int(
                    getattr(settings, "RECRUITING_TOMBSTONE_DAYS", 30)
                ),
            }
        )


class AdminRecruitingCandidateListView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        queryset = RecruitingCandidate.objects.order_by("-created_at", "-pk")
        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(queryset, request)
        results = [
            {
                "id": candidate.pk,
                "name_masked": _mask_name(candidate.name),
                "phone_masked": _mask_phone(candidate.phone),
                "stage": candidate.stage,
                "created_at": candidate.created_at,
                "retention_expires_at": candidate.retention_expires_at,
                "contact_opted_out": candidate.contact_opt_out_at is not None,
            }
            for candidate in page
        ]
        return paginator.get_paginated_response(results)


class AdminRecruitingCandidatePurgeView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request, candidate_id):
        serializer = AdminCandidatePurgeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            candidate = RecruitingCandidate.objects.select_for_update().filter(
                pk=candidate_id
            ).first()
            if candidate is None:
                raise NotFound()
            if candidate.joined_user_id is not None or candidate.joined_at is not None:
                return Response(
                    {
                        "code": "recruiting_join_history_preserved",
                        "message": "합류 기록은 그대로 두고 계정 관리에서 다음 절차를 이어가주세요.",
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            anonymize_candidate_for_tombstone(
                candidate=candidate,
                event_type=RecruitingActivity.EventType.CANDIDATE_PURGED,
                actor=request.user,
            )
        return Response({"purged": True})


class AdminRecruitingTemplateListView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        templates = RecruitingCopyTemplate.objects.order_by("kind", "sort_order", "pk")
        return Response(
            AdminRecruitingTemplateReadSerializer(templates, many=True).data
        )

    def post(self, request):
        serializer = AdminRecruitingTemplateCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            template = serializer.save()
        except IntegrityError as exc:
            raise serializers.ValidationError(
                {"code": "이미 사용 중인 코드예요. 다른 코드를 입력해주세요."}
            ) from exc
        return Response(
            AdminRecruitingTemplateReadSerializer(template).data,
            status=status.HTTP_201_CREATED,
        )


class AdminRecruitingTemplateDetailView(APIView):
    permission_classes = [IsAdmin]

    def _template(self, template_id):
        template = RecruitingCopyTemplate.objects.filter(pk=template_id).first()
        if template is None:
            raise NotFound()
        return template

    def get(self, request, template_id):
        return Response(
            AdminRecruitingTemplateReadSerializer(self._template(template_id)).data
        )

    def patch(self, request, template_id):
        template = self._template(template_id)
        serializer = AdminRecruitingTemplateUpdateSerializer(
            template,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        return Response(
            AdminRecruitingTemplateReadSerializer(serializer.save()).data
        )


class AdminRecruitingPromotionListView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        profiles = Profile.objects.filter(
            manager_promoted_at__isnull=False
        ).select_related("user").order_by("manager_promoted_at", "user_id")
        subscriptions = {
            item.user_id: item
            for item in Subscription.objects.filter(
                user_id__in=[profile.user_id for profile in profiles]
            ).select_related("plan")
        }
        results = []
        for profile in profiles:
            subscription = subscriptions.get(profile.user_id)
            try:
                effective_plan = resolve_effective_plan(profile.user)
                effective_plan_code = effective_plan.code
            except RuntimeError:
                effective_plan_code = None
            results.append(
                {
                    "user_id": profile.user_id,
                    "display_name": _display_name(profile),
                    "manager_promoted_at": profile.manager_promoted_at,
                    "current_team_count": Profile.objects.filter(
                        manager_id=profile.user_id
                    ).count(),
                    "is_manager": profile.manager_promoted_at is not None,
                    "effective_plan_code": effective_plan_code,
                    "subscription_plan_code": (
                        subscription.plan.code if subscription else None
                    ),
                }
            )
        return Response(results)


class AdminRecruitingAuditListView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        queryset = RecruitingActivity.objects.order_by("-created_at", "-pk")
        paginator = PageNumberPagination()
        paginator.page_size = 50
        page = paginator.paginate_queryset(queryset, request)
        return paginator.get_paginated_response(
            AdminRecruitingAuditSerializer(page, many=True).data
        )
