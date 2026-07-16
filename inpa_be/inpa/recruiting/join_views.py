from django.core import signing
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from inpa.accounts.team import TeamSwitchConfirmationRequired

from .models import RecruitingCandidate, SettlementCheck
from .serializers import SettlementCheckCompleteSerializer, TeamJoinAcceptSerializer
from .services import accept_team_join, complete_settlement_check
from .tokens import read_recruiting_join_token
from .views import RecruitingEnabledMixin


def _gone_response():
    return Response(
        {
            "code": "recruiting_join_link_expired",
            "message": "리더에게 새 합류 링크를 받으면 바로 이어갈 수 있어요.",
        },
        status=status.HTTP_410_GONE,
    )


def _read_candidate(token):
    payload = read_recruiting_join_token(token)
    candidate = (
        RecruitingCandidate.objects.select_related(
            "owner__profile", "owner__recruiting_page__headline_template"
        )
        .filter(pk=payload["candidate_id"], owner_id=payload["owner_id"])
        .first()
    )
    if (
        candidate is None
        or candidate.selection_status != RecruitingCandidate.SelectionStatus.ACTIVE
        or candidate.contact_opt_out_at is not None
        or candidate.stage == RecruitingCandidate.Stage.ENDED
    ):
        raise RecruitingCandidate.DoesNotExist
    return candidate, payload


class RecruitingJoinView(RecruitingEnabledMixin, APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "recruiting_public"

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["X-Robots-Tag"] = "noindex, nofollow"
        return response

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated()]
        return [AllowAny()]

    def get(self, request, token):
        try:
            candidate, _ = _read_candidate(token)
        except (signing.BadSignature, RecruitingCandidate.DoesNotExist):
            return _gone_response()
        profile = candidate.owner.profile
        page = getattr(candidate.owner, "recruiting_page", None)
        headline_template = getattr(page, "headline_template", None)
        image_url = None
        if profile.profile_image:
            try:
                image_url = profile.profile_image.url
            except Exception:
                image_url = None
        return Response(
            {
                "display_name": (profile.name or profile.affiliation or "담당 리더").strip(),
                "affiliation": (profile.affiliation or "").strip(),
                "title": (profile.title or "").strip(),
                "profile_image": image_url,
                "headline": headline_template.body if headline_template else "",
            }
        )

    def post(self, request, token):
        serializer = TeamJoinAcceptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            candidate, payload = _read_candidate(token)
            joined, joined_now = accept_team_join(
                candidate=candidate,
                agent=request.user,
                expected_owner_id=payload["owner_id"],
                confirm_switch=serializer.validated_data["confirm_switch"],
            )
        except TeamSwitchConfirmationRequired:
            return Response(
                {
                    "code": "team_switch_confirmation_required",
                    "message": "현재 연결된 리더가 있어요. 이 리더로 변경할지 한 번 더 확인해주세요.",
                },
                status=status.HTTP_409_CONFLICT,
            )
        except (signing.BadSignature, RecruitingCandidate.DoesNotExist):
            return _gone_response()
        except ValueError as exc:
            if str(exc) in {"candidate_owner_mismatch", "inactive_candidate_selection"}:
                return _gone_response()
            if str(exc) == "candidate_joined_to_another_account":
                return Response(
                    {
                        "code": "recruiting_join_account_mismatch",
                        "message": "처음 합류한 계정으로 로그인하면 정착 일정을 이어갈 수 있어요.",
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            return Response(
                {"code": "recruiting_join_unavailable", "message": "리더와 합류 계정을 확인해주세요."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {
                "joined_now": joined_now,
                "stage": joined.stage,
            }
        )


class SettlementCheckCompleteView(RecruitingEnabledMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        check = SettlementCheck.objects.filter(
            pk=pk,
            candidate__owner=request.user,
        ).first()
        if check is None:
            raise NotFound()
        serializer = SettlementCheckCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            updated = complete_settlement_check(
                check=check,
                owner=request.user,
                **serializer.validated_data,
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "id": updated.pk,
                "week": updated.week,
                "state": updated.state,
                "blocker": updated.blocker,
                "next_support": updated.next_support,
                "completed_at": updated.completed_at,
            }
        )
