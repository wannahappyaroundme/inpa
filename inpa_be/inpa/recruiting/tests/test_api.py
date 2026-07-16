from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User
from inpa.recruiting.models import RecruitingCampaign, RecruitingCandidate, RecruitingPage


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
