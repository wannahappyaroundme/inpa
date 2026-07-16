from unittest.mock import patch

from django.test import TestCase, override_settings
from django.db.models.query import QuerySet
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User
from inpa.recruiting.consent_texts import (
    RECRUITING_CONSENT_VERSION,
    RECRUITING_CONTACT_CONSENT,
)
from inpa.recruiting.models import (
    RecruitingCampaign,
    RecruitingCandidate,
    RecruitingCopyTemplate,
    RecruitingEvent,
    RecruitingPage,
)
from inpa.recruiting.services import get_or_create_recruiting_page


@override_settings(RECRUITING_ENABLED=True)
class RecruitingFrontendCandidateContractTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="contract-owner@inpa.local", password="inpaPass123!"
        )
        Profile.objects.create(user=self.owner, name="리더")
        self.page = RecruitingPage.objects.create(owner=self.owner, is_published=True)
        self.campaign = RecruitingCampaign.objects.create(
            page=self.page,
            name="개인 소개",
            channel=RecruitingCampaign.Channel.RELATIONSHIP,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def candidate(self, **overrides):
        values = {
            "owner": self.owner,
            "campaign": self.campaign,
            "name": "지원자",
            "phone": "010-1234-5678",
            "career_band": RecruitingCandidate.CareerBand.ONE_TO_THREE,
            "current_affiliation": "현재 소속",
            "region": "서울",
            "contact_window": RecruitingCandidate.ContactWindow.ANYTIME,
        }
        values.update(overrides)
        return RecruitingCandidate.objects.create(**values)

    def assert_no_internal_candidate_keys(self, payload):
        forbidden = {
            "identity_ref",
            "audit_ref",
            "submission_key",
            "manage_token",
            "retention_expires_at",
            "contact_opt_out_at",
            "consent",
            "consents",
        }
        self.assertFalse(forbidden.intersection(payload))

    def test_active_candidate_has_additive_campaign_and_selection_contract(self):
        candidate = self.candidate()

        response = self.client.get(f"/api/v1/recruiting/candidates/{candidate.pk}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["selection_status"], "active")
        self.assertIsNone(response.data["joined_at"])
        self.assertIsNone(response.data["joined_agent"])
        self.assertEqual(response.data["campaign_id"], self.campaign.pk)
        self.assertEqual(
            response.data["campaign"],
            {
                "id": self.campaign.pk,
                "name": "개인 소개",
                "channel": RecruitingCampaign.Channel.RELATIONSHIP,
            },
        )
        self.assert_no_internal_candidate_keys(response.data)

    def test_joined_agent_uses_only_linked_authenticated_profile(self):
        joined_user = User.objects.create_user(
            email="joined-private@inpa.local", password="inpaPass123!"
        )
        joined_profile = Profile.objects.create(
            user=joined_user,
            name="합류 설계사",
            phone="010-9999-8888",
            manager=self.owner,
        )
        joined_at = timezone.now()
        candidate = self.candidate(
            name="후보 이름과 다름",
            stage=RecruitingCandidate.Stage.TEAM_JOIN,
            joined_user=joined_user,
            joined_at=joined_at,
        )

        response = self.client.get(f"/api/v1/recruiting/candidates/{candidate.pk}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["selection_status"], "active")
        self.assertEqual(parse_datetime(response.data["joined_at"]), joined_at)
        self.assertEqual(
            response.data["joined_agent"],
            {
                "id": joined_user.pk,
                "display_name": joined_profile.name,
                "profile_image": None,
            },
        )
        self.assertNotIn("email", response.data["joined_agent"])
        self.assertNotIn("phone", response.data["joined_agent"])
        self.assertNotIn("manager", response.data["joined_agent"])
        self.assertNotEqual(response.data["joined_agent"]["display_name"], candidate.name)
        self.assert_no_internal_candidate_keys(response.data)

    def test_replaced_candidate_stays_minimal_and_marks_selection_status(self):
        candidate = self.candidate(
            selection_status=RecruitingCandidate.SelectionStatus.REPLACED,
            stage=RecruitingCandidate.Stage.ENDED,
        )

        response = self.client.get(f"/api/v1/recruiting/candidates/{candidate.pk}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.data),
            {"id", "stage", "selection_status", "closed_message", "created_at", "updated_at"},
        )
        self.assertEqual(response.data["selection_status"], "replaced")
        for pii_key in ("name", "phone", "current_affiliation", "region", "joined_agent"):
            self.assertNotIn(pii_key, response.data)
        self.assert_no_internal_candidate_keys(response.data)


@override_settings(RECRUITING_ENABLED=True)
class RecruitingFrontendCampaignContractTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="campaign-owner@inpa.local", password="inpaPass123!"
        )
        Profile.objects.create(user=self.owner, name="리더")
        self.page = RecruitingPage.objects.create(owner=self.owner, is_published=True)
        self.campaign = RecruitingCampaign.objects.create(
            page=self.page,
            name="개인 소개",
            channel=RecruitingCampaign.Channel.RELATIONSHIP,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def candidate(self, *, status=RecruitingCandidate.SelectionStatus.ACTIVE):
        return RecruitingCandidate.objects.create(
            owner=self.owner,
            campaign=self.campaign,
            name="지원자",
            phone="01012345678",
            career_band=RecruitingCandidate.CareerBand.ONE_TO_THREE,
            region="서울",
            contact_window=RecruitingCandidate.ContactWindow.ANYTIME,
            selection_status=status,
        )

    def event(self, event_type, candidate=None):
        return RecruitingEvent.objects.create(
            owner=self.owner,
            campaign=self.campaign,
            candidate=candidate,
            event_type=event_type,
            channel=self.campaign.channel,
            metadata={"source": self.campaign.channel},
        )

    def test_campaign_metrics_count_real_events_for_current_active_selections(self):
        active = self.candidate()
        replaced = self.candidate(status=RecruitingCandidate.SelectionStatus.REPLACED)
        self.event(RecruitingEvent.EventType.PAGE_VIEW)
        self.event(RecruitingEvent.EventType.PAGE_VIEW)
        self.event(RecruitingEvent.EventType.APPLICATION_SUBMITTED, active)
        self.event(RecruitingEvent.EventType.APPLICATION_SUBMITTED, replaced)
        self.event(RecruitingEvent.EventType.TEAM_JOIN, active)
        self.event(RecruitingEvent.EventType.TEAM_JOIN, replaced)

        response = self.client.get("/api/v1/recruiting/campaign/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["public_path"], f"/r/{self.campaign.public_token}")
        self.assertEqual(response.data["public_url"], response.data["public_path"])
        self.assertEqual(response.data["visits"], 2)
        self.assertEqual(response.data["applications"], 1)
        self.assertEqual(response.data["joins"], 1)
        self.assertFalse({"candidate", "candidates", "phone"}.intersection(response.data))

    def test_first_campaign_bootstrap_rechecks_relation_under_page_lock(self):
        self.campaign.delete()
        headline = RecruitingCopyTemplate.objects.create(
            code="bootstrap-headline",
            kind=RecruitingCopyTemplate.Kind.HEADLINE,
            title="첫 문장",
            body="함께 시작해요.",
        )
        self.page.headline_template = headline
        self.page.save(update_fields=["headline_template", "updated_at"])
        original_first = QuerySet.first
        concurrent = {"campaign": None}

        def first_with_concurrent_insert(queryset):
            if queryset.model is RecruitingCampaign and concurrent["campaign"] is None:
                concurrent["campaign"] = RecruitingCampaign.objects.create(
                    page=self.page,
                    name="동시 생성 개인 소개",
                    channel=RecruitingCampaign.Channel.RELATIONSHIP,
                )
                return None
            return original_first(queryset)

        original_lock = RecruitingPage.objects.select_for_update
        with patch.object(QuerySet, "first", autospec=True, side_effect=first_with_concurrent_insert), patch(
            "inpa.recruiting.models.RecruitingPage.objects.select_for_update",
            wraps=original_lock,
        ) as select_for_update:
            page, campaign = get_or_create_recruiting_page(self.owner)

        self.assertEqual(page.pk, self.page.pk)
        self.assertEqual(campaign.pk, concurrent["campaign"].pk)
        self.assertEqual(
            RecruitingCampaign.objects.filter(
                page=self.page,
                channel=RecruitingCampaign.Channel.RELATIONSHIP,
            ).count(),
            1,
        )
        select_for_update.assert_called_once_with()

    def test_stop_get_page_and_copy_do_not_create_replacement_then_resume_same_token(self):
        original_path = f"/r/{self.campaign.public_token}"

        stopped = self.client.patch(
            "/api/v1/recruiting/campaign/", {"is_active": False}, format="json"
        )
        stopped_again = self.client.patch(
            "/api/v1/recruiting/campaign/", {"is_active": False}, format="json"
        )
        fetched = self.client.get("/api/v1/recruiting/campaign/")
        page = self.client.get("/api/v1/recruiting/page/")
        page_patch = self.client.patch(
            "/api/v1/recruiting/page/", {"activity_region": "서울"}, format="json"
        )
        with self.captureOnCommitCallbacks(execute=True):
            copied = self.client.post(
                "/api/v1/recruiting/campaign/copied/", {}, format="json"
            )
        old_public = APIClient().get(f"/api/v1/r/{self.campaign.public_token}/")

        self.assertEqual(stopped.status_code, 200)
        self.assertEqual(stopped_again.status_code, 200)
        self.assertFalse(stopped.data["is_active"])
        self.assertEqual(stopped.data["public_path"], original_path)
        self.assertEqual(stopped_again.data["public_path"], original_path)
        self.assertEqual(fetched.data["public_path"], original_path)
        self.assertFalse(fetched.data["is_active"])
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page_patch.status_code, 200)
        self.assertEqual(copied.status_code, 200)
        self.assertEqual(RecruitingCampaign.objects.filter(page=self.page).count(), 1)
        self.assertEqual(
            RecruitingEvent.objects.get(event_type=RecruitingEvent.EventType.LINK_COPIED).campaign_id,
            self.campaign.pk,
        )
        self.assertEqual(old_public.status_code, 410)

        resumed = self.client.patch(
            "/api/v1/recruiting/campaign/", {"is_active": True}, format="json"
        )
        resumed_again = self.client.patch(
            "/api/v1/recruiting/campaign/", {"is_active": True}, format="json"
        )
        self.assertEqual(resumed.data["public_path"], original_path)
        self.assertEqual(resumed_again.data["public_path"], original_path)
        self.assertTrue(resumed.data["is_active"])
        self.assertEqual(RecruitingCampaign.objects.filter(page=self.page).count(), 1)

    def test_reissue_changes_token_and_old_public_link_stays_gone(self):
        old_path = f"/r/{self.campaign.public_token}"

        response = self.client.patch(
            "/api/v1/recruiting/campaign/", {"reissue": True}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.data["public_path"], old_path)
        self.campaign.refresh_from_db()
        self.assertFalse(self.campaign.is_active)
        self.assertEqual(
            APIClient().get(f"/api/v1/r/{self.campaign.public_token}/").status_code,
            410,
        )
        self.assertEqual(RecruitingCampaign.objects.filter(page=self.page, is_active=True).count(), 1)

    def test_campaign_patch_is_strict_and_locks_page(self):
        invalid_bodies = (
            {},
            {"unknown": True},
            {"is_active": False, "reissue": True},
            {"is_active": "false"},
            {"reissue": 1},
            {"reissue": False},
        )
        for body in invalid_bodies:
            with self.subTest(body=body):
                response = self.client.patch(
                    "/api/v1/recruiting/campaign/", body, format="json"
                )
                self.assertEqual(response.status_code, 400)
                self.assertTrue(str(response.data))

        original = RecruitingPage.objects.select_for_update
        with patch(
            "inpa.recruiting.models.RecruitingPage.objects.select_for_update",
            wraps=original,
        ) as select_for_update:
            response = self.client.patch(
                "/api/v1/recruiting/campaign/", {"is_active": False}, format="json"
            )

        self.assertEqual(response.status_code, 200)
        select_for_update.assert_called_once_with()

    def test_campaign_patch_uses_page_then_campaign_lock_order(self):
        lock_order = []
        original_page_lock = RecruitingPage.objects.select_for_update
        original_campaign_lock = RecruitingCampaign.objects.select_for_update

        def page_lock():
            lock_order.append("page")
            return original_page_lock()

        def campaign_lock():
            lock_order.append("campaign")
            return original_campaign_lock()

        with patch(
            "inpa.recruiting.models.RecruitingPage.objects.select_for_update",
            side_effect=page_lock,
        ), patch(
            "inpa.recruiting.models.RecruitingCampaign.objects.select_for_update",
            side_effect=campaign_lock,
        ):
            response = self.client.patch(
                "/api/v1/recruiting/campaign/", {"is_active": False}, format="json"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(lock_order, ["page", "campaign"])


@override_settings(RECRUITING_ENABLED=True)
class RecruitingFrontendPublicContractTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="public-owner@inpa.local", password="inpaPass123!"
        )
        Profile.objects.create(user=self.owner, name="리더")
        self.page = RecruitingPage.objects.create(
            owner=self.owner, activity_region="서울", is_published=True
        )
        self.campaign = RecruitingCampaign.objects.create(
            page=self.page,
            name="개인 소개",
            channel=RecruitingCampaign.Channel.RELATIONSHIP,
        )
        self.candidate = RecruitingCandidate.objects.create(
            owner=self.owner,
            campaign=self.campaign,
            name="외부 지원자",
            phone="010-3333-4444",
            career_band=RecruitingCandidate.CareerBand.ONE_TO_THREE,
            current_affiliation="외부 소속",
            region="부산",
            contact_window=RecruitingCandidate.ContactWindow.ANYTIME,
        )
        self.client = APIClient()

    def test_public_campaign_uses_exact_recruiting_consent_ssot(self):
        response = self.client.get(f"/api/v1/r/{self.campaign.public_token}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["consent_version"], RECRUITING_CONSENT_VERSION)
        self.assertEqual(response.data["consent_text"], RECRUITING_CONTACT_CONSENT)

    def test_public_manage_adds_submitted_at_without_applicant_pii(self):
        response = self.client.get(f"/api/v1/r/manage/{self.candidate.manage_token}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["submitted_at"], self.candidate.created_at)
        rendered = str(response.data)
        self.assertNotIn(self.candidate.phone, rendered)
        self.assertNotIn(self.candidate.current_affiliation, rendered)
        self.assertNotIn(self.candidate.region, rendered)
        self.assertFalse({"phone", "current_affiliation", "region"}.intersection(response.data))

    def test_stopped_public_manage_keeps_submitted_at_without_applicant_pii(self):
        self.candidate.contact_opt_out_at = timezone.now()
        self.candidate.save(update_fields=["contact_opt_out_at", "updated_at"])

        response = self.client.get(f"/api/v1/r/manage/{self.candidate.manage_token}/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["contact_stopped"])
        self.assertEqual(response.data["submitted_at"], self.candidate.created_at)
        rendered = str(response.data)
        self.assertNotIn(self.candidate.phone, rendered)
        self.assertNotIn(self.candidate.current_affiliation, rendered)
        self.assertNotIn(self.candidate.region, rendered)
