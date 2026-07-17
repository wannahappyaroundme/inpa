from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from unittest.mock import patch

from inpa.accounts.models import Profile, User
from inpa.recruiting.models import (
    RecruitingCampaign,
    RecruitingCandidate,
    RecruitingCopyTemplate,
    RecruitingPage,
)


@override_settings(RECRUITING_ENABLED=True)
class RecruitingCandidateApiTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="owner@inpa.local", password="inpaPass123!")
        self.other = User.objects.create_user(email="other@inpa.local", password="inpaPass123!")
        self.admin = User.objects.create_user(email="admin@inpa.local", password="inpaPass123!")
        Profile.objects.create(user=self.owner, name="내 리더")
        Profile.objects.create(user=self.other, name="다른 리더")
        Profile.objects.create(user=self.admin, name="운영자", is_admin=True)
        self.candidate = self.make_candidate(self.owner, "내 지원자", "01011112222")
        self.other_candidate = self.make_candidate(self.other, "다른 지원자", "01099998888")
        self.client = APIClient()

    def make_candidate(self, owner, name, phone):
        page = RecruitingPage.objects.create(owner=owner, is_published=True)
        campaign = RecruitingCampaign.objects.create(
            page=page,
            name="개인 소개",
            channel=RecruitingCampaign.Channel.RELATIONSHIP,
        )
        return RecruitingCandidate.objects.create(
            owner=owner,
            campaign=campaign,
            name=name,
            phone=phone,
            career_band=RecruitingCandidate.CareerBand.ONE_TO_THREE,
            region="서울",
            contact_window=RecruitingCandidate.ContactWindow.ANYTIME,
            next_action=RecruitingCandidate.NextAction.CALL,
        )

    def test_owner_cannot_read_another_owners_candidate(self):
        self.client.force_authenticate(self.owner)

        response = self.client.get(f"/api/v1/recruiting/candidates/{self.other_candidate.pk}/")

        self.assertEqual(response.status_code, 404)

    def test_source_filter_uses_campaign_channel_and_excludes_unlinked_candidates(self):
        owner_page = self.candidate.campaign.page
        threads_campaign = RecruitingCampaign.objects.create(
            page=owner_page,
            name="Threads 소개",
            channel=RecruitingCampaign.Channel.THREADS,
        )
        threads_candidate = RecruitingCandidate.objects.create(
            owner=self.owner,
            campaign=threads_campaign,
            name="다른 경로 지원자",
            phone="01033334444",
            career_band=RecruitingCandidate.CareerBand.ONE_TO_THREE,
            region="서울",
            contact_window=RecruitingCandidate.ContactWindow.ANYTIME,
            next_action=RecruitingCandidate.NextAction.CALL,
        )
        unlinked_candidate = RecruitingCandidate.objects.create(
            owner=self.owner,
            campaign=None,
            name="연결 없는 지원자",
            phone="01055556666",
            career_band=RecruitingCandidate.CareerBand.ONE_TO_THREE,
            region="서울",
            contact_window=RecruitingCandidate.ContactWindow.ANYTIME,
            next_action=RecruitingCandidate.NextAction.CALL,
        )
        self.client.force_authenticate(self.owner)

        response = self.client.get(
            "/api/v1/recruiting/candidates/",
            {"source": RecruitingCampaign.Channel.RELATIONSHIP},
        )

        self.assertEqual(response.status_code, 200)
        listed_ids = [item["id"] for item in response.data["results"]]
        self.assertEqual(listed_ids, [self.candidate.pk])
        self.assertNotIn(threads_candidate.pk, listed_ids)
        self.assertNotIn(unlinked_candidate.pk, listed_ids)
        self.assertNotIn(self.other_candidate.pk, listed_ids)

    def test_source_filter_rejects_unknown_channel(self):
        self.client.force_authenticate(self.owner)

        response = self.client.get(
            "/api/v1/recruiting/candidates/",
            {"source": "unknown-channel"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("source", response.data)

    def test_admin_does_not_bypass_candidate_service_view(self):
        self.client.force_authenticate(self.admin)

        response = self.client.get(f"/api/v1/recruiting/candidates/{self.candidate.pk}/")

        self.assertEqual(response.status_code, 404)

    def test_planner_cannot_create_candidate_without_public_consent_flow(self):
        self.client.force_authenticate(self.owner)

        response = self.client.post(
            "/api/v1/recruiting/candidates/",
            {
                "name": "직접 등록",
                "phone": "010-1234-5678",
                "career_band": "1_3",
                "region": "서울",
                "contact_window": "anytime",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 405)

    def test_manual_patch_cannot_set_team_join(self):
        self.client.force_authenticate(self.owner)

        patch_response = self.client.patch(
            f"/api/v1/recruiting/candidates/{self.candidate.pk}/",
            {"stage": RecruitingCandidate.Stage.TEAM_JOIN},
            format="json",
        )
        transition_response = self.client.post(
            f"/api/v1/recruiting/candidates/{self.candidate.pk}/transition/",
            {"stage": RecruitingCandidate.Stage.TEAM_JOIN},
            format="json",
        )

        self.assertEqual(patch_response.status_code, 400)
        self.assertEqual(transition_response.status_code, 400)
        self.candidate.refresh_from_db()
        self.assertEqual(self.candidate.stage, RecruitingCandidate.Stage.NEW)

    def test_relationship_campaign_reissue_preserves_old_token_as_inactive(self):
        self.client.force_authenticate(self.owner)
        old_campaign = self.candidate.campaign
        old_token = old_campaign.public_token

        page_response = self.client.get("/api/v1/recruiting/page/")
        campaign_response = self.client.patch(
            "/api/v1/recruiting/campaign/",
            {"reissue": True},
            format="json",
        )

        self.assertEqual(page_response.status_code, 200)
        self.assertEqual(page_response.data["planner"]["display_name"], "내 리더")
        self.assertIsNotNone(page_response.data["headline"])
        self.assertEqual(campaign_response.status_code, 200)
        old_campaign.refresh_from_db()
        self.assertFalse(old_campaign.is_active)
        self.assertEqual(old_campaign.public_token, old_token)
        self.assertNotIn(str(old_token), campaign_response.data["public_url"])

    def test_page_patch_locks_page_before_publish_state_change(self):
        self.client.force_authenticate(self.owner)
        original = RecruitingPage.objects.select_for_update
        with patch(
            "inpa.recruiting.models.RecruitingPage.objects.select_for_update",
            wraps=original,
        ) as select_for_update:
            response = self.client.patch(
                "/api/v1/recruiting/page/",
                {"is_published": False},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        select_for_update.assert_called_once_with()
        self.assertFalse(response.data["is_published"])

    def test_page_patch_rejects_more_than_three_support_and_faq_templates(self):
        templates = [
            RecruitingCopyTemplate.objects.create(
                code=f"support-{index}",
                kind=(
                    RecruitingCopyTemplate.Kind.SUPPORT
                    if index < 2
                    else RecruitingCopyTemplate.Kind.FAQ
                ),
                title=f"지원 문구 {index}",
                body=f"지원 내용 {index}",
            )
            for index in range(4)
        ]
        self.client.force_authenticate(self.owner)

        response = self.client.patch(
            "/api/v1/recruiting/page/",
            {"template_ids": [template.pk for template in templates]},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("template_ids", response.data)
        self.assertEqual(self.candidate.campaign.page.templates.count(), 0)

    def test_opted_out_candidate_is_hidden_from_list_detail_and_patch(self):
        self.candidate.contact_opt_out_at = timezone.now()
        self.candidate.stage = RecruitingCandidate.Stage.ENDED
        self.candidate.save(update_fields=["contact_opt_out_at", "stage", "updated_at"])
        self.client.force_authenticate(self.owner)

        listed = self.client.get("/api/v1/recruiting/candidates/")
        detailed = self.client.get(f"/api/v1/recruiting/candidates/{self.candidate.pk}/")
        patched = self.client.patch(
            f"/api/v1/recruiting/candidates/{self.candidate.pk}/",
            {"name": "다시 노출"},
            format="json",
        )

        self.assertNotIn(self.candidate.pk, [item["id"] for item in listed.data["results"]])
        self.assertEqual(detailed.status_code, 404)
        self.assertEqual(patched.status_code, 404)
        self.candidate.refresh_from_db()
        self.assertEqual(self.candidate.name, "내 지원자")

    def test_leader_cannot_replace_applicant_identity_under_existing_consent(self):
        self.client.force_authenticate(self.owner)

        response = self.client.patch(
            f"/api/v1/recruiting/candidates/{self.candidate.pk}/",
            {
                "name": "다른 사람",
                "phone": "010-9999-9999",
                "career_band": RecruitingCandidate.CareerBand.TEN_PLUS,
                "current_affiliation": "다른 소속",
                "region": "부산",
                "contact_window": RecruitingCandidate.ContactWindow.MORNING,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.candidate.refresh_from_db()
        self.assertEqual(self.candidate.name, "내 지원자")
        self.assertEqual(self.candidate.phone, "01011112222")

    def test_replaced_candidate_generic_card_cannot_be_patched(self):
        self.candidate.selection_status = RecruitingCandidate.SelectionStatus.REPLACED
        self.candidate.stage = RecruitingCandidate.Stage.ENDED
        self.candidate.name = "담당 변경"
        self.candidate.phone = ""
        self.candidate.save(
            update_fields=["selection_status", "stage", "name", "phone", "updated_at"]
        )
        self.client.force_authenticate(self.owner)

        detailed = self.client.get(f"/api/v1/recruiting/candidates/{self.candidate.pk}/")
        patched = self.client.patch(
            f"/api/v1/recruiting/candidates/{self.candidate.pk}/",
            {"name": "다시 기록"},
            format="json",
        )

        self.assertEqual(detailed.status_code, 200)
        self.assertEqual(
            detailed.data["closed_message"],
            "후보가 다른 담당자를 선택해 대화가 종료되었어요.",
        )
        self.assertNotIn("phone", detailed.data)
        self.assertEqual(patched.status_code, 400)
        self.candidate.refresh_from_db()
        self.assertEqual(self.candidate.name, "담당 변경")
