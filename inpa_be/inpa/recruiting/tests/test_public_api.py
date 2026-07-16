import uuid
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User
from inpa.recruiting.models import (
    RecruitingCampaign,
    RecruitingCandidate,
    RecruitingConsentLog,
    RecruitingPage,
)


@override_settings(RECRUITING_ENABLED=True)
class RecruitingPublicApiTests(TestCase):
    def setUp(self):
        self.owner = self.make_owner("leader@inpa.local", "김리더", "인파 GA")
        self.other_owner = self.make_owner("other-leader@inpa.local", "이리더", "인파금융")
        self.campaign = self.make_campaign(self.owner)
        self.other_campaign = self.make_campaign(self.other_owner)
        self.client = APIClient()

    def make_owner(self, email, name, affiliation):
        user = User.objects.create_user(email=email, password="inpaPass123!")
        Profile.objects.create(
            user=user,
            name=name,
            affiliation=affiliation,
            title="팀장",
            phone="010-0000-0000",
        )
        return user

    def make_campaign(self, owner):
        page = RecruitingPage.objects.create(
            owner=owner,
            activity_region="서울",
            is_published=True,
        )
        return RecruitingCampaign.objects.create(
            page=page,
            name="개인 소개",
            channel=RecruitingCampaign.Channel.RELATIONSHIP,
        )

    def payload(self, **overrides):
        values = {
            "name": "홍길동",
            "phone": "010-1234-5678",
            "career_band": RecruitingCandidate.CareerBand.FIVE_TO_TEN,
            "current_affiliation": "기존 GA",
            "region": "서울",
            "contact_window": RecruitingCandidate.ContactWindow.EVENING,
            "submission_key": str(uuid.uuid4()),
            "agreed": True,
        }
        values.update(overrides)
        return values

    def apply(self, campaign=None, **overrides):
        campaign = campaign or self.campaign
        return self.client.post(
            f"/api/v1/r/{campaign.public_token}/",
            self.payload(**overrides),
            format="json",
        )

    def test_public_duplicate_submit_returns_same_success_shape(self):
        submission_key = str(uuid.uuid4())

        first = self.apply(submission_key=submission_key)
        second = self.apply(submission_key=submission_key)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data, second.data)
        self.assertEqual(RecruitingCandidate.objects.count(), 1)

    def test_choice_endpoint_keeps_pending_hidden_until_switch_is_confirmed(self):
        old_response = self.apply()
        prior_manage_token = old_response.data["manage_url"].rsplit("/", 1)[-1]
        choice_response = self.apply(
            campaign=self.other_campaign,
            prior_manage_token=prior_manage_token,
        )
        pending = RecruitingCandidate.objects.get(owner=self.other_owner)

        self.client.force_authenticate(self.other_owner)
        before_choice = self.client.get("/api/v1/recruiting/candidates/")
        self.client.force_authenticate(user=None)
        selected = self.client.post(
            f"/api/v1/r/choice/{choice_response.data['choice_token']}/",
            {"choice": "switch_to_new"},
            format="json",
        )

        self.assertEqual(choice_response.status_code, 200)
        self.assertTrue(choice_response.data["choice_required"])
        self.assertEqual(
            set(choice_response.data["current_leader"]),
            {"display_name", "affiliation"},
        )
        self.assertEqual(
            set(choice_response.data["new_leader"]),
            {"display_name", "affiliation"},
        )
        self.assertEqual(before_choice.status_code, 200)
        self.assertEqual(before_choice.data["count"], 0)
        self.assertEqual(selected.status_code, 200)
        self.assertIn(str(pending.manage_token), selected.data["manage_url"])
        pending.refresh_from_db()
        self.assertEqual(pending.selection_status, RecruitingCandidate.SelectionStatus.ACTIVE)

    def test_public_response_never_reveals_existing_owner_or_candidate(self):
        old = self.apply()
        self.assertEqual(old.status_code, 201)

        response = self.apply(
            campaign=self.other_campaign,
            prior_manage_token="broken-browser-value",
        )
        rendered = str(response.data)

        self.assertEqual(response.status_code, 201)
        self.assertNotIn("김리더", rendered)
        self.assertNotIn("leader@inpa.local", rendered)
        self.assertNotIn(str(old.data["manage_url"]), rendered)

        public = self.client.get(f"/api/v1/r/{self.campaign.public_token}/")
        public_text = str(public.data)
        self.assertNotIn("leader@inpa.local", public_text)
        self.assertNotIn("010-0000-0000", public_text)
        self.assertNotIn("team", public_text.lower())
        self.assertNotIn("commission", public_text.lower())

    def test_public_failures_and_duplicate_paths_do_not_log_name_or_phone(self):
        submission_key = str(uuid.uuid4())
        self.apply(submission_key=submission_key)

        with patch("inpa.recruiting.public_views.logger") as logger:
            self.apply(submission_key=submission_key)
            self.apply(name="로그금지이름", phone="010-7777-8888", agreed=False)

        logged = repr(logger.method_calls)
        self.assertNotIn("로그금지이름", logged)
        self.assertNotIn("010-7777-8888", logged)
        self.assertNotIn("01077778888", logged)

    def test_manage_token_can_stop_contact_and_scrub_pii(self):
        application = self.apply()
        candidate = RecruitingCandidate.objects.get(owner=self.owner)
        RecruitingConsentLog.objects.create(candidate=candidate, doc_version="2026-07-16-v1")

        response = self.client.post(
            f"/api/v1/r/manage/{candidate.manage_token}/",
            {"action": "stop_contact"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["contact_stopped"])
        self.assertIn(str(candidate.manage_token), application.data["manage_url"])
        candidate.refresh_from_db()
        self.assertEqual(candidate.name, "정리 요청")
        self.assertEqual(candidate.phone, "")
        self.assertEqual(candidate.current_affiliation, "")
        self.assertEqual(candidate.region, "")
        self.assertEqual(candidate.stage, RecruitingCandidate.Stage.ENDED)
        self.assertIsNotNone(candidate.contact_opt_out_at)
        self.assertFalse(candidate.consents.exists())

        repeated = self.client.post(
            f"/api/v1/r/manage/{candidate.manage_token}/",
            {"action": "stop_contact"},
            format="json",
        )
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.data, response.data)

    def test_joined_candidate_manage_token_cannot_unlink_authenticated_team_relation(self):
        joined = User.objects.create_user(email="joined@inpa.local", password="inpaPass123!")
        candidate = RecruitingCandidate.objects.create(
            owner=self.owner,
            campaign=self.campaign,
            name="합류자",
            phone="010-5555-6666",
            career_band=RecruitingCandidate.CareerBand.THREE_TO_FIVE,
            region="서울",
            contact_window=RecruitingCandidate.ContactWindow.ANYTIME,
            stage=RecruitingCandidate.Stage.TEAM_JOIN,
            joined_user=joined,
        )

        response = self.client.post(
            f"/api/v1/r/manage/{candidate.manage_token}/",
            {"action": "stop_contact"},
            format="json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "team_account_management_required")
        candidate.refresh_from_db()
        self.assertEqual(candidate.joined_user, joined)
        self.assertEqual(candidate.stage, RecruitingCandidate.Stage.TEAM_JOIN)

    def test_expired_or_disabled_campaign_has_positive_next_action_copy(self):
        self.campaign.is_active = False
        self.campaign.save(update_fields=["is_active", "updated_at"])

        get_response = self.client.get(f"/api/v1/r/{self.campaign.public_token}/")
        post_response = self.apply()

        for response in (get_response, post_response):
            self.assertEqual(response.status_code, 410)
            self.assertEqual(response.data["code"], "recruiting_link_renewed")
            self.assertIn("새 링크", response.data["message"])
            self.assertNotIn("불가", response.data["message"])
            self.assertNotIn("안 됩니다", response.data["message"])

    @override_settings(RECRUITING_ENABLED=False)
    def test_recruiting_endpoints_return_404_when_feature_is_disabled(self):
        public = self.client.get(f"/api/v1/r/{self.campaign.public_token}/")
        self.client.force_authenticate(self.owner)
        private = self.client.get("/api/v1/recruiting/candidates/")

        self.assertEqual(public.status_code, 404)
        self.assertEqual(private.status_code, 404)
