from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import RecruitingCampaign, RecruitingCandidate, RecruitingCopyTemplate, RecruitingEvent
from .serializers import (
    CandidateTransitionSerializer,
    RecruitingCampaignSerializer,
    RecruitingCandidateSerializer,
    RecruitingCopyTemplateSerializer,
    RecruitingPageSerializer,
)
from .services import _schedule_event, get_or_create_recruiting_page, transition_candidate


class RecruitingEnabledMixin:
    def initial(self, request, *args, **kwargs):
        if not settings.RECRUITING_ENABLED:
            raise NotFound()
        return super().initial(request, *args, **kwargs)


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
            )
            .select_related("campaign", "joined_user")
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


class RecruitingPageView(RecruitingEnabledMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        page, _ = get_or_create_recruiting_page(request.user)
        page = type(page).objects.select_related("owner__profile", "headline_template").prefetch_related("templates").get(pk=page.pk)
        return Response(RecruitingPageSerializer(page).data)

    def patch(self, request):
        page, _ = get_or_create_recruiting_page(request.user)
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
        if request.data.get("reissue") is not True:
            raise ValidationError({"reissue": "새 개인 링크를 발급하려면 다시 확인해주세요."})
        with transaction.atomic():
            page, campaign = get_or_create_recruiting_page(request.user)
            campaign = RecruitingCampaign.objects.select_for_update().get(pk=campaign.pk)
            campaign.is_active = False
            campaign.save(update_fields=["is_active", "updated_at"])
            replacement = RecruitingCampaign.objects.create(
                page=page,
                name="개인 소개",
                channel=RecruitingCampaign.Channel.RELATIONSHIP,
            )
        return Response(RecruitingCampaignSerializer(replacement).data)


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
