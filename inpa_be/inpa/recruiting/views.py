from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from inpa.accounts.models import Profile
from inpa.billing.credit import user_can_use_team

from .analytics import candidate_metrics
from .models import (
    RecruitingCampaign,
    RecruitingCandidate,
    RecruitingCopyTemplate,
    RecruitingEvent,
    SettlementCheck,
)
from .serializers import (
    CandidateTransitionSerializer,
    RecruitingCampaignActionSerializer,
    RecruitingCampaignSerializer,
    RecruitingCandidateSerializer,
    RecruitingCopyTemplateSerializer,
    RecruitingPageSerializer,
)
from .services import _schedule_event, get_or_create_recruiting_page, transition_candidate
from .tokens import RECRUITING_JOIN_MAX_AGE_SECONDS, make_recruiting_join_token


class RecruitingEnabledMixin:
    def initial(self, request, *args, **kwargs):
        if not settings.RECRUITING_ENABLED:
            raise NotFound()
        return super().initial(request, *args, **kwargs)


MANAGER_PLAN_REQUIRED_BODY = {
    "detail": "Plus를 시작하면 팀 관리 기능을 계속 사용할 수 있어요.",
    "code": "manager_plan_required",
    "plan": "manager",
}


class RecruitingSummaryView(RecruitingEnabledMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(candidate_metrics(request.user, timezone.localdate()))


class RecruitingTeamSummaryView(RecruitingEnabledMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if (
            getattr(settings, "MANAGER_PLAN_GATE_ENABLED", False)
            and not user_can_use_team(request.user)
        ):
            return Response(
                MANAGER_PLAN_REQUIRED_BODY,
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )
        today = timezone.localdate()
        profiles = Profile.objects.filter(manager=request.user).select_related("user")
        shared_profiles = profiles.filter(
            manager_share_level__in=(Profile.SHARE_ACTIVITY, Profile.SHARE_FULL)
        )
        members = []
        totals = {
            "active_recruiting": 0,
            "joined_this_month": 0,
            "settlement_due": 0,
        }
        for profile in shared_profiles.order_by("user_id"):
            metrics = candidate_metrics(profile.user, today)
            active_recruiting = sum(
                count
                for stage, count in metrics["stage_counts"].items()
                if stage not in (
                    RecruitingCandidate.Stage.ENDED,
                    RecruitingCandidate.Stage.TEAM_JOIN,
                )
            )
            item = {
                "user_id": profile.user_id,
                "display_name": (
                    profile.name or profile.affiliation or "소속 설계사"
                ).strip(),
                "active_recruiting": active_recruiting,
                "joined_this_month": metrics["joined_this_month"],
                "settlement_due": metrics["settlement_due"],
            }
            members.append(item)
            for key in totals:
                totals[key] += item[key]
        return Response(
            {
                "members": members,
                "not_shared_count": profiles.filter(
                    manager_share_level=Profile.SHARE_NONE
                ).count(),
                "team_totals": totals,
            }
        )


class RecruitingSettlementListView(RecruitingEnabledMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        checks = SettlementCheck.objects.filter(
            candidate__owner=request.user
        ).select_related("candidate__joined_user__profile").order_by("due_on", "week", "pk")
        payload = []
        for check in checks:
            joined_user = check.candidate.joined_user
            profile = getattr(joined_user, "profile", None) if joined_user else None
            payload.append(
                {
                    "id": check.pk,
                    "candidate_id": check.candidate_id,
                    "joined_agent_name": (
                        (profile.name or profile.affiliation or "합류 설계사").strip()
                        if profile
                        else "-"
                    ),
                    "week": check.week,
                    "due_on": check.due_on,
                    "state": check.state,
                    "blocker": check.blocker,
                    "next_support": check.next_support,
                    "completed_at": check.completed_at,
                }
            )
        return Response(payload)


class RecruitingCandidateViewSet(RecruitingEnabledMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = RecruitingCandidateSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        queryset = (
            RecruitingCandidate.objects.filter(
                owner=self.request.user,
                selection_status__in=(
                    RecruitingCandidate.SelectionStatus.ACTIVE,
                    RecruitingCandidate.SelectionStatus.REPLACED,
                ),
                contact_opt_out_at__isnull=True,
            )
            .select_related("campaign", "joined_user__profile")
            .prefetch_related("settlement_checks")
            .order_by("stage", "next_action_at", "-created_at")
        )
        params = self.request.query_params
        if params.get("q"):
            query = params["q"].strip()
            queryset = queryset.filter(Q(name__icontains=query) | Q(phone__icontains=query))
        if params.get("stage"):
            queryset = queryset.filter(stage=params["stage"])
        if params.get("campaign"):
            queryset = queryset.filter(campaign_id=params["campaign"])
        if params.get("career_band"):
            queryset = queryset.filter(career_band=params["career_band"])
        if params.get("due") in {"1", "true", "overdue"}:
            from django.utils import timezone

            queryset = queryset.filter(next_action_at__lte=timezone.now())
        return queryset

    def create(self, request, *args, **kwargs):
        raise MethodNotAllowed("POST")

    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        candidate = (
            RecruitingCandidate.objects.select_for_update()
            .filter(
                pk=kwargs.get("pk"),
                owner=request.user,
                selection_status__in=(
                    RecruitingCandidate.SelectionStatus.ACTIVE,
                    RecruitingCandidate.SelectionStatus.REPLACED,
                ),
                contact_opt_out_at__isnull=True,
            )
            .first()
        )
        if candidate is None:
            raise NotFound()
        if candidate.selection_status != RecruitingCandidate.SelectionStatus.ACTIVE:
            raise ValidationError("진행이 종료된 지원자 정보는 수정하지 않고 기록으로 확인할 수 있어요.")
        serializer = self.get_serializer(candidate, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def transition(self, request, pk=None):
        candidate = self.get_object()
        serializer = CandidateTransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            updated = transition_candidate(
                candidate=candidate,
                actor=request.user,
                to_stage=serializer.validated_data["stage"],
                next_action=serializer.validated_data.get("next_action", ""),
                next_action_at=serializer.validated_data.get("next_action_at"),
            )
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages) from exc
        return Response(self.get_serializer(updated).data)

    @action(detail=True, methods=["post"], url_path="team-invite")
    @transaction.atomic
    def team_invite(self, request, pk=None):
        candidate = (
            RecruitingCandidate.objects.select_for_update()
            .filter(pk=pk, owner=request.user)
            .first()
        )
        if candidate is None:
            raise NotFound()
        if (
            candidate.selection_status != RecruitingCandidate.SelectionStatus.ACTIVE
            or candidate.contact_opt_out_at is not None
            or candidate.stage == RecruitingCandidate.Stage.ENDED
            or candidate.joined_user_id is not None
        ):
            return Response(
                {
                    "code": "recruiting_join_link_unavailable",
                    "message": "현재 지원 흐름을 확인하면 다음 합류 안내를 이어갈 수 있어요.",
                },
                status=status.HTTP_409_CONFLICT,
            )
        token = make_recruiting_join_token(candidate)
        expires_at = timezone.localtime(
            timezone.now() + timedelta(seconds=RECRUITING_JOIN_MAX_AGE_SECONDS)
        ).isoformat()
        return Response(
            {
                "join_path": f"/recruiting/join/{token}",
                "expires_at": expires_at,
            }
        )


class RecruitingPageView(RecruitingEnabledMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        page, _ = get_or_create_recruiting_page(request.user)
        page = type(page).objects.select_related("owner__profile", "headline_template").prefetch_related("templates").get(pk=page.pk)
        return Response(RecruitingPageSerializer(page).data)

    def patch(self, request):
        with transaction.atomic():
            page, _ = get_or_create_recruiting_page(request.user, lock=True)
            serializer = RecruitingPageSerializer(page, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            was_published = page.is_published
            page = serializer.save()
            if not was_published and page.is_published:
                _schedule_event(owner=request.user, event_type=RecruitingEvent.EventType.PAGE_PUBLISHED)
        page = type(page).objects.select_related("owner__profile", "headline_template").prefetch_related("templates").get(pk=page.pk)
        return Response(RecruitingPageSerializer(page).data)


class RecruitingTemplateListView(RecruitingEnabledMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        templates = RecruitingCopyTemplate.objects.filter(is_active=True).order_by("kind", "sort_order", "pk")
        return Response(RecruitingCopyTemplateSerializer(templates, many=True).data)


class RecruitingCampaignView(RecruitingEnabledMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        _, campaign = get_or_create_recruiting_page(request.user)
        return Response(RecruitingCampaignSerializer(campaign).data)

    def patch(self, request):
        action_serializer = RecruitingCampaignActionSerializer(data=request.data)
        action_serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            page, campaign = get_or_create_recruiting_page(request.user, lock=True)
            campaign = RecruitingCampaign.objects.select_for_update().get(
                pk=campaign.pk,
                page_id=page.pk,
            )
            relationship_campaigns = page.campaigns.filter(
                channel=RecruitingCampaign.Channel.RELATIONSHIP
            )
            if action_serializer.validated_data.get("reissue"):
                relationship_campaigns.filter(is_active=True).update(
                    is_active=False, updated_at=timezone.now()
                )
                campaign = RecruitingCampaign.objects.create(
                    page=page,
                    name="개인 소개",
                    channel=RecruitingCampaign.Channel.RELATIONSHIP,
                )
            else:
                is_active = action_serializer.validated_data["is_active"]
                if is_active:
                    relationship_campaigns.filter(is_active=True).exclude(
                        pk=campaign.pk
                    ).update(is_active=False, updated_at=timezone.now())
                else:
                    relationship_campaigns.filter(is_active=True).update(
                        is_active=False, updated_at=timezone.now()
                    )
                campaign.refresh_from_db()
                if campaign.is_active != is_active:
                    campaign.is_active = is_active
                    campaign.save(update_fields=["is_active", "updated_at"])
        return Response(RecruitingCampaignSerializer(campaign).data)


class RecruitingCampaignCopiedView(RecruitingEnabledMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        _, campaign = get_or_create_recruiting_page(request.user)
        _schedule_event(
            owner=request.user,
            campaign=campaign,
            event_type=RecruitingEvent.EventType.LINK_COPIED,
            metadata={"source": campaign.channel},
        )
        return Response({"recorded": True}, status=status.HTTP_200_OK)
