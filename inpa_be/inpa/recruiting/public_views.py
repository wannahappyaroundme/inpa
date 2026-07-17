import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .models import RecruitingCampaign, RecruitingCandidate, RecruitingCopyTemplate, RecruitingEvent
from .consent_texts import RECRUITING_CONSENT_VERSION, RECRUITING_CONTACT_CONSENT
from .serializers import (
    LeaderChoiceSerializer,
    ManageCandidateActionSerializer,
    PublicRecruitingApplicationSerializer,
    RecruitingCopyTemplateSerializer,
)
from .services import (
    PendingSubmissionVerificationRequired,
    RecruitingApplicationLimitReached,
    RecruitingLinkUnavailable,
    TeamAccountManagementRequired,
    _schedule_event,
    apply_leader_choice,
    create_candidate_submission,
    stop_candidate_contact,
)
from .views import RecruitingEnabledMixin


logger = logging.getLogger(__name__)
SUBMITTED_MESSAGE = "지원 내용을 잘 받았어요. 담당 설계사가 선택한 시간대에 연락드릴게요."
STOPPED_MESSAGE = "연락을 멈췄어요. 남은 정보도 정리 절차에 따라 처리됩니다."
RENEWED_MESSAGE = "담당 설계사에게 새 링크를 받아 지원을 이어가세요."


def _profile_payload(user):
    profile = getattr(user, "profile", None)
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


def _manage_url(candidate):
    return f"/r/manage/{candidate.manage_token}"


def _leader_choice_payload(user):
    public_profile = _profile_payload(user)
    return {
        "display_name": public_profile["display_name"],
        "affiliation": public_profile["affiliation"],
    }


def _renewed_response():
    return Response(
        {"code": "recruiting_link_renewed", "message": RENEWED_MESSAGE},
        status=status.HTTP_410_GONE,
    )


def _safe_validation_detail(exc):
    if hasattr(exc, "message_dict"):
        return exc.message_dict
    return exc.messages


class PublicRecruitingCampaignView(RecruitingEnabledMixin, APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "recruiting_public"

    def get_throttles(self):
        self.throttle_scope = "recruiting_apply" if self.request.method == "POST" else "recruiting_public"
        return super().get_throttles()

    def _campaign(self, token):
        try:
            return (
                RecruitingCampaign.objects.select_related("page__owner__profile", "page__headline_template")
                .prefetch_related("page__templates")
                .get(public_token=token)
            )
        except RecruitingCampaign.DoesNotExist as exc:
            raise NotFound() from exc

    def _is_unavailable(self, campaign):
        return not campaign.is_active or not campaign.page.is_published

    def get(self, request, token):
        campaign = self._campaign(token)
        if self._is_unavailable(campaign):
            return _renewed_response()
        page = campaign.page
        templates = list(page.templates.filter(is_active=True).order_by("kind", "sort_order", "pk"))
        support = [item for item in templates if item.kind == RecruitingCopyTemplate.Kind.SUPPORT]
        faq = [item for item in templates if item.kind == RecruitingCopyTemplate.Kind.FAQ]
        _schedule_event(
            owner=page.owner,
            campaign=campaign,
            event_type=RecruitingEvent.EventType.PAGE_VIEW,
            metadata={"source": campaign.channel},
        )
        return Response(
            {
                "planner": _profile_payload(page.owner),
                "headline": (
                    RecruitingCopyTemplateSerializer(page.headline_template).data
                    if page.headline_template and page.headline_template.is_active
                    else None
                ),
                "support": RecruitingCopyTemplateSerializer(support, many=True).data,
                "faq": RecruitingCopyTemplateSerializer(faq, many=True).data,
                "activity_region": page.activity_region,
                "consent_version": RECRUITING_CONSENT_VERSION,
                "consent_text": RECRUITING_CONTACT_CONSENT,
            }
        )

    def post(self, request, token):
        campaign = self._campaign(token)
        if self._is_unavailable(campaign):
            return _renewed_response()
        if request.data.get("consent_version") != RECRUITING_CONSENT_VERSION:
            return Response(
                {
                    "code": "recruiting_consent_refresh_required",
                    "message": "최신 개인정보 안내를 다시 불러왔어요. 내용을 확인한 뒤 지원을 이어가주세요.",
                },
                status=status.HTTP_409_CONFLICT,
            )
        serializer = PublicRecruitingApplicationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = create_candidate_submission(
                campaign=campaign,
                data=serializer.validated_data,
            )
        except RecruitingLinkUnavailable:
            return _renewed_response()
        except RecruitingApplicationLimitReached:
            return Response(
                {
                    "code": "recruiting_apply_daily_limit",
                    "message": "담당 설계사에게 연락 가능한 시간을 확인한 뒤 다시 지원해주세요.",
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        except PendingSubmissionVerificationRequired:
            return Response(
                {
                    "submitted": False,
                    "verification_required": True,
                    "message": "이전 신청 관리 링크를 확인하면 담당자 선택을 이어갈 수 있어요.",
                },
                status=status.HTTP_200_OK,
            )
        except DjangoValidationError as exc:
            raise ValidationError(_safe_validation_detail(exc)) from exc
        if result.choice_required:
            return Response(
                {
                    "submitted": False,
                    "choice_required": True,
                    "current_leader": _leader_choice_payload(result.prior_candidate.owner),
                    "new_leader": _leader_choice_payload(result.candidate.owner),
                    "choice_token": result.choice_token,
                },
                status=status.HTTP_200_OK,
            )
        response_body = {
            "submitted": True,
            "message": SUBMITTED_MESSAGE,
            "manage_url": _manage_url(result.candidate),
        }
        return Response(
            response_body,
            status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK,
        )


class PublicRecruitingLeaderChoiceView(RecruitingEnabledMixin, APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "recruiting_apply"

    def post(self, request, token):
        serializer = LeaderChoiceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            candidate = apply_leader_choice(
                token=token,
                choice=serializer.validated_data["choice"],
            )
        except DjangoValidationError as exc:
            raise ValidationError(_safe_validation_detail(exc)) from exc
        return Response(
            {
                "submitted": True,
                "message": "선택한 담당자와 지원 상담을 이어갈 수 있어요.",
                "manage_url": _manage_url(candidate),
            }
        )


class PublicRecruitingManageView(RecruitingEnabledMixin, APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "recruiting_public"

    def _candidate(self, token):
        try:
            return RecruitingCandidate.objects.select_related("owner__profile").get(manage_token=token)
        except RecruitingCandidate.DoesNotExist as exc:
            raise NotFound() from exc

    def get(self, request, token):
        candidate = self._candidate(token)
        if candidate.contact_opt_out_at:
            return Response(
                {
                    "contact_stopped": True,
                    "submitted_at": candidate.created_at,
                    "support_reference": str(candidate.audit_ref),
                    "message": STOPPED_MESSAGE,
                }
            )
        return Response(
            {
                "contact_stopped": False,
                "stage": candidate.stage,
                "submitted_at": candidate.created_at,
                "support_reference": str(candidate.audit_ref),
                "leader": _profile_payload(candidate.owner),
            }
        )

    def post(self, request, token):
        serializer = ManageCandidateActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        candidate = self._candidate(token)
        try:
            stop_candidate_contact(candidate=candidate)
        except TeamAccountManagementRequired:
            return Response(
                {
                    "code": "team_account_management_required",
                    "message": "인파 계정에서 연결 상태를 확인하고, 정보 정리는 문의함에서 요청할 수 있어요",
                },
                status=status.HTTP_409_CONFLICT,
            )
        except DjangoValidationError as exc:
            raise ValidationError(_safe_validation_detail(exc)) from exc
        return Response({"contact_stopped": True, "message": STOPPED_MESSAGE})
