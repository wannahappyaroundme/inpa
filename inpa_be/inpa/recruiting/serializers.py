from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import (
    RecruitingCampaign,
    RecruitingCandidate,
    RecruitingCopyTemplate,
    RecruitingPage,
    SettlementCheck,
)
from .services import normalize_phone


class RecruitingCopyTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = RecruitingCopyTemplate
        fields = ("id", "code", "kind", "title", "body", "sort_order")


class RecruitingPageSerializer(serializers.ModelSerializer):
    headline_template_id = serializers.IntegerField(required=False, allow_null=True)
    template_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        write_only=True,
    )
    headline = RecruitingCopyTemplateSerializer(source="headline_template", read_only=True)
    templates = RecruitingCopyTemplateSerializer(many=True, read_only=True)
    planner = serializers.SerializerMethodField()

    class Meta:
        model = RecruitingPage
        fields = (
            "headline_template_id",
            "template_ids",
            "headline",
            "templates",
            "activity_region",
            "is_published",
            "planner",
        )

    def get_planner(self, obj):
        profile = getattr(obj.owner, "profile", None)
        if profile is None:
            return {"display_name": "담당 설계사", "affiliation": "", "title": "", "profile_image": None}
        image_url = None
        if profile.profile_image:
            try:
                image_url = profile.profile_image.url
            except Exception:
                image_url = None
        return {
            "display_name": (profile.name or profile.affiliation or "담당 설계사").strip(),
            "affiliation": (profile.affiliation or "").strip(),
            "title": (profile.title or "").strip(),
            "profile_image": image_url,
        }

    def validate(self, attrs):
        headline_id = attrs.get("headline_template_id", serializers.empty)
        if headline_id is not serializers.empty and headline_id is not None:
            headline = RecruitingCopyTemplate.objects.filter(
                pk=headline_id,
                kind=RecruitingCopyTemplate.Kind.HEADLINE,
                is_active=True,
            ).first()
            if headline is None:
                raise serializers.ValidationError({"headline_template_id": "사용할 첫 문장을 선택해주세요."})
            attrs["headline_template"] = headline
        template_ids = attrs.get("template_ids")
        if template_ids is not None:
            templates = list(
                RecruitingCopyTemplate.objects.filter(
                    pk__in=template_ids,
                    kind__in=(
                        RecruitingCopyTemplate.Kind.SUPPORT,
                        RecruitingCopyTemplate.Kind.FAQ,
                    ),
                    is_active=True,
                )
            )
            if len(templates) != len(set(template_ids)):
                raise serializers.ValidationError({"template_ids": "사용할 지원 문구를 다시 선택해주세요."})
            attrs["selected_templates"] = templates
        return attrs

    def update(self, instance, validated_data):
        templates = validated_data.pop("selected_templates", None)
        validated_data.pop("template_ids", None)
        validated_data.pop("headline_template_id", None)
        instance = super().update(instance, validated_data)
        if templates is not None:
            instance.templates.set(templates)
        return instance


class RecruitingCampaignSerializer(serializers.ModelSerializer):
    public_url = serializers.SerializerMethodField()

    class Meta:
        model = RecruitingCampaign
        fields = ("id", "name", "channel", "is_active", "public_url", "created_at")
        read_only_fields = fields

    def get_public_url(self, obj):
        return f"/r/{obj.public_token}"


class RecruitingCandidateSerializer(serializers.ModelSerializer):
    duplicate_contact = serializers.SerializerMethodField()
    closed_message = serializers.SerializerMethodField()
    campaign_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = RecruitingCandidate
        fields = (
            "id",
            "campaign_id",
            "name",
            "phone",
            "career_band",
            "current_affiliation",
            "region",
            "contact_window",
            "stage",
            "next_action",
            "next_action_at",
            "last_contacted_at",
            "ended_at",
            "created_at",
            "updated_at",
            "duplicate_contact",
            "closed_message",
        )
        read_only_fields = (
            "id",
            "campaign_id",
            "stage",
            "last_contacted_at",
            "ended_at",
            "created_at",
            "updated_at",
            "duplicate_contact",
            "closed_message",
        )

    def to_internal_value(self, data):
        forbidden = {
            "stage",
            "team_join",
            "selection_status",
            "joined_user",
            "joined_at",
            "retention_expires_at",
            "manage_token",
        }
        supplied = forbidden.intersection(data.keys())
        if supplied:
            raise serializers.ValidationError(
                {field: "이 항목은 지원 흐름에서 자동으로 기록돼요." for field in sorted(supplied)}
            )
        return super().to_internal_value(data)

    def validate_phone(self, value):
        try:
            return normalize_phone(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages[0]) from exc

    def get_duplicate_contact(self, obj):
        if not obj.phone or obj.selection_status != RecruitingCandidate.SelectionStatus.ACTIVE:
            return False
        return RecruitingCandidate.objects.filter(
            owner=obj.owner,
            phone=obj.phone,
            selection_status=RecruitingCandidate.SelectionStatus.ACTIVE,
            contact_opt_out_at__isnull=True,
        ).exclude(pk=obj.pk).exists()

    def get_closed_message(self, obj):
        if obj.selection_status == RecruitingCandidate.SelectionStatus.REPLACED:
            return "후보가 다른 담당자를 선택해 대화가 종료되었어요."
        return ""

    def to_representation(self, instance):
        if instance.selection_status == RecruitingCandidate.SelectionStatus.REPLACED:
            return {
                "id": instance.pk,
                "stage": RecruitingCandidate.Stage.ENDED,
                "closed_message": "후보가 다른 담당자를 선택해 대화가 종료되었어요.",
                "created_at": instance.created_at,
                "updated_at": instance.updated_at,
            }
        return super().to_representation(instance)


class CandidateTransitionSerializer(serializers.Serializer):
    stage = serializers.ChoiceField(choices=RecruitingCandidate.Stage.choices)
    next_action = serializers.ChoiceField(
        choices=RecruitingCandidate.NextAction.choices,
        required=False,
        allow_blank=True,
    )
    next_action_at = serializers.DateTimeField(required=False, allow_null=True)


class PublicRecruitingApplicationSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=30, trim_whitespace=True)
    phone = serializers.CharField(max_length=30)
    career_band = serializers.ChoiceField(choices=RecruitingCandidate.CareerBand.choices)
    current_affiliation = serializers.CharField(max_length=100, required=False, allow_blank=True)
    region = serializers.CharField(max_length=60, trim_whitespace=True)
    contact_window = serializers.ChoiceField(choices=RecruitingCandidate.ContactWindow.choices)
    submission_key = serializers.UUIDField()
    prior_manage_token = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=100)
    agreed = serializers.BooleanField()

    def validate_phone(self, value):
        try:
            return normalize_phone(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages[0]) from exc

    def validate_agreed(self, value):
        if not value:
            raise serializers.ValidationError("동의하면 바로 지원 내용을 보낼 수 있어요.")
        return value


class LeaderChoiceSerializer(serializers.Serializer):
    choice = serializers.ChoiceField(choices=("keep_current", "switch_to_new"))


class ManageCandidateActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=("stop_contact",))


class TeamJoinAcceptSerializer(serializers.Serializer):
    confirm_switch = serializers.BooleanField(required=False, default=False)


class SettlementCheckCompleteSerializer(serializers.Serializer):
    state = serializers.ChoiceField(choices=SettlementCheck.State.choices)
    blocker = serializers.ChoiceField(
        choices=SettlementCheck.Blocker.choices,
        required=False,
        allow_blank=True,
        default="",
    )
    next_support = serializers.ChoiceField(
        choices=SettlementCheck.NextSupport.choices,
        required=False,
        allow_blank=True,
        default="",
    )

    def validate(self, attrs):
        if attrs["state"] == SettlementCheck.State.SUPPORT_NEEDED:
            if attrs.get("blocker") in {"", SettlementCheck.Blocker.NONE}:
                raise serializers.ValidationError(
                    {"blocker": "도움이 필요한 부분을 선택해주세요."}
                )
            if not attrs.get("next_support"):
                raise serializers.ValidationError(
                    {"next_support": "다음 지원 방법을 선택해주세요."}
                )
        return attrs
