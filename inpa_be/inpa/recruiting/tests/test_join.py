"""Explicit recruiting join and settlement-flow regressions."""
from datetime import timedelta
from unittest import mock
import uuid

from django.core import signing
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User
from inpa.billing.models import Plan, Subscription, UsageMeter
from inpa.recruiting.models import (
    RecruitingActivity,
    RecruitingCampaign,
    RecruitingCandidate,
    RecruitingConsentLog,
    RecruitingEvent,
    RecruitingPage,
    SettlementCheck,
)


def _join_api():
    from inpa.recruiting.services import (
        TeamJoinResult,
        accept_team_join,
        complete_settlement_check,
        reopen_settlement_check,
    )
    from inpa.recruiting.tokens import (
        RECRUITING_CHOICE_SALT,
        RECRUITING_JOIN_SALT,
        make_recruiting_join_token,
        read_recruiting_join_token,
    )

    return {
        "accept": accept_team_join,
        "complete": complete_settlement_check,
        "reopen": reopen_settlement_check,
        "result_type": TeamJoinResult,
        "choice_salt": RECRUITING_CHOICE_SALT,
        "join_salt": RECRUITING_JOIN_SALT,
        "make_token": make_recruiting_join_token,
        "read_token": read_recruiting_join_token,
    }


@override_settings(RECRUITING_ENABLED=True)
class RecruitingJoinTests(TestCase):
    def setUp(self):
        self.free_plan = Plan.objects.create(code="free", display_name="Free", price_krw=0)
        self.owner = self._user("join-owner@inpa.local", "김리더", "인파GA", "팀장")
        self.other_owner = self._user("other-owner@inpa.local", "박리더", "다른GA", "본부장")
        self.agent = self._user("joining-agent@inpa.local", "합류 설계사", "기존GA", "FC")
        self.page = RecruitingPage.objects.create(owner=self.owner, is_published=True)
        self.campaign = RecruitingCampaign.objects.create(
            page=self.page,
            name="개인 소개",
            channel=RecruitingCampaign.Channel.RELATIONSHIP,
        )
        self.candidate = self._candidate(self.owner, self.campaign)
        self.client = APIClient()

    def _user(self, email, name="", affiliation="", title=""):
        user = User.objects.create_user(email=email, password="inpaPass123!")
        user.is_active = True
        user.save(update_fields=["is_active"])
        Profile.objects.create(
            user=user,
            name=name,
            affiliation=affiliation,
            title=title,
            manager_share_level=Profile.SHARE_FULL,
            manager_share_opt_in=True,
        )
        return user

    def _candidate(self, owner, campaign, **overrides):
        values = {
            "owner": owner,
            "campaign": campaign,
            "name": "홍길동",
            "phone": "01012345678",
            "career_band": RecruitingCandidate.CareerBand.FIVE_TO_TEN,
            "current_affiliation": "기존 GA",
            "region": "서울",
            "contact_window": RecruitingCandidate.ContactWindow.EVENING,
            "stage": RecruitingCandidate.Stage.PREPARING,
        }
        values.update(overrides)
        return RecruitingCandidate.objects.create(**values)

    def _token(self, candidate=None):
        return _join_api()["make_token"](candidate or self.candidate)

    def _accept(self, token=None, confirm_switch=False, user=None):
        self.client.force_authenticate(user=user or self.agent)
        return self.client.post(
            f"/api/v1/recruiting/join/{token or self._token()}/",
            {"confirm_switch": confirm_switch},
            format="json",
        )

    def _snapshots(self):
        subscriptions = list(
            Subscription.objects.order_by("pk").values(
                "user_id", "plan_id", "status", "started_at", "expires_at"
            )
        )
        usage = list(UsageMeter.objects.order_by("pk").values())
        shares = list(
            Profile.objects.order_by("pk").values(
                "user_id", "manager_share_level", "manager_share_opt_in"
            )
        )
        return subscriptions, usage, shares

    def test_invite_token_has_separate_salt_and_candidate_owner_payload(self):
        api = _join_api()
        token = api["make_token"](self.candidate)

        payload = api["read_token"](token)

        self.assertNotEqual(api["join_salt"], api["choice_salt"])
        self.assertEqual(payload["candidate_id"], self.candidate.pk)
        self.assertEqual(payload["owner_id"], self.owner.pk)
        self.assertEqual(set(payload), {"candidate_id", "owner_id", "v"})
        with self.assertRaises(signing.BadSignature):
            signing.loads(token, salt=api["choice_salt"])
        from inpa.recruiting.tokens import make_leader_choice_token

        choice_token = make_leader_choice_token(
            old_candidate_id=self.candidate.pk,
            new_candidate_id=self.candidate.pk + 1,
        )
        with self.assertRaises(signing.BadSignature):
            api["read_token"](choice_token)

    def test_identity_reference_is_hidden_from_api_event_and_admin(self):
        from inpa.recruiting.admin import RecruitingCandidateAdmin

        self.client.force_authenticate(self.owner)
        response = self.client.get(
            f"/api/v1/recruiting/candidates/{self.candidate.pk}/"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertNotIn("identity_ref", response.json())
        self.assertIn("identity_ref", RecruitingCandidateAdmin.exclude)
        self.assertNotIn(
            "identity_ref", {field.name for field in RecruitingEvent._meta.fields}
        )

    def test_expired_join_token_returns_410_without_identity_details(self):
        token = self._token()
        with mock.patch(
            "inpa.recruiting.tokens.signing.loads",
            side_effect=signing.SignatureExpired("expired"),
        ):
            response = self.client.get(f"/api/v1/recruiting/join/{token}/")

        self.assertEqual(response.status_code, 410)
        body = response.json()
        self.assertEqual(set(body), {"code", "message"})
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertNotIn(self.candidate.name, str(body))
        self.assertNotIn(self.candidate.phone, str(body))
        self.assertNotIn("identity_ref", str(body))

    def test_anonymous_accept_returns_401(self):
        response = self.client.post(
            f"/api/v1/recruiting/join/{self._token()}/",
            {"confirm_switch": False},
            format="json",
        )
        self.assertEqual(response.status_code, 401)

    def test_public_info_contains_only_leader_profile_and_headline(self):
        response = self.client.get(f"/api/v1/recruiting/join/{self._token()}/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            set(response.json()),
            {"display_name", "affiliation", "title", "profile_image", "headline"},
        )
        self.assertNotIn(self.candidate.name, str(response.json()))
        self.assertNotIn(self.candidate.phone, str(response.json()))
        self.assertNotIn("identity_ref", str(response.json()))
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")

    def test_join_view_uses_public_throttle_and_noindexes_post_response(self):
        from rest_framework.throttling import ScopedRateThrottle
        from inpa.recruiting.join_views import RecruitingJoinView

        self.assertEqual(RecruitingJoinView.throttle_classes, [ScopedRateThrottle])
        self.assertEqual(RecruitingJoinView.throttle_scope, "recruiting_public")
        response = self._accept()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertNotIn("manager_id", response.json())
        self.assertEqual(
            set(response.json()),
            {"stage", "joined_now", "manager_promoted_now"},
        )

    def test_accepting_sets_profile_manager_and_candidate_joined(self):
        response = self._accept()
        self.assertEqual(response.status_code, 200, response.content)
        self.agent.profile.refresh_from_db()
        self.candidate.refresh_from_db()
        self.assertEqual(self.agent.profile.manager_id, self.owner.pk)
        self.assertEqual(self.candidate.joined_user_id, self.agent.pk)
        self.assertEqual(self.candidate.stage, RecruitingCandidate.Stage.TEAM_JOIN)
        self.assertEqual(self.candidate.name, "팀 합류 설계사")
        self.assertEqual(self.candidate.phone, "")

    def test_accepting_creates_exactly_four_settlement_checks(self):
        self.assertEqual(self._accept().status_code, 200)
        checks = list(
            self.candidate.settlement_checks.order_by("week").values_list("week", "due_on")
        )
        joined_date = timezone.localdate()
        self.assertEqual(
            checks,
            [
                (1, joined_date + timedelta(days=7)),
                (4, joined_date + timedelta(days=28)),
                (8, joined_date + timedelta(days=56)),
                (13, joined_date + timedelta(days=91)),
            ],
        )

    def test_repeated_accept_is_idempotent(self):
        first = self._accept()
        first_joined_at = RecruitingCandidate.objects.get(pk=self.candidate.pk).joined_at
        second = self._accept()
        self.candidate.refresh_from_db()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(first.json()["joined_now"])
        self.assertTrue(first.json()["manager_promoted_now"])
        self.assertFalse(second.json()["joined_now"])
        self.assertFalse(second.json()["manager_promoted_now"])
        self.assertEqual(self.candidate.joined_at, first_joined_at)
        self.assertEqual(self.candidate.settlement_checks.count(), 4)
        self.assertEqual(
            RecruitingActivity.objects.filter(
                candidate=self.candidate,
                event_type=RecruitingActivity.EventType.TEAM_JOINED,
            ).count(),
            1,
        )

    def test_join_result_distinguishes_legacy_manager_first_join(self):
        manager_plan = Plan.objects.create(
            code="manager", display_name="Manager", price_krw=19900
        )
        Subscription.objects.filter(user=self.owner).update(plan=manager_plan)

        result = _join_api()["accept"](
            candidate=self.candidate,
            agent=self.agent,
            expected_owner_id=self.owner.pk,
        )

        self.assertIsInstance(result, _join_api()["result_type"])
        self.assertEqual(result.candidate.pk, self.candidate.pk)
        self.assertTrue(result.joined_now)
        self.assertFalse(result.manager_promoted_now)

    def test_join_result_first_join_has_both_explicit_booleans(self):
        result = _join_api()["accept"](
            candidate=self.candidate,
            agent=self.agent,
            expected_owner_id=self.owner.pk,
        )

        self.assertTrue(result.joined_now)
        self.assertTrue(result.manager_promoted_now)

    def test_manual_candidate_stage_patch_still_cannot_join(self):
        self.client.force_authenticate(self.owner)
        response = self.client.patch(
            f"/api/v1/recruiting/candidates/{self.candidate.pk}/",
            {"stage": RecruitingCandidate.Stage.TEAM_JOIN},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.candidate.refresh_from_db()
        self.assertEqual(self.candidate.stage, RecruitingCandidate.Stage.PREPARING)

    def test_switch_requires_confirmation_and_confirm_switch_succeeds(self):
        self.agent.profile.manager = self.other_owner
        self.agent.profile.save(update_fields=["manager"])

        rejected = self._accept()
        self.assertEqual(rejected.status_code, 409, rejected.content)
        self.assertEqual(rejected.json()["code"], "team_switch_confirmation_required")
        self.agent.profile.refresh_from_db()
        self.candidate.refresh_from_db()
        self.assertEqual(self.agent.profile.manager_id, self.other_owner.pk)
        self.assertIsNone(self.candidate.joined_user_id)

        accepted = self._accept(confirm_switch=True)
        self.assertEqual(accepted.status_code, 200, accepted.content)
        self.agent.profile.refresh_from_db()
        self.assertEqual(self.agent.profile.manager_id, self.owner.pk)

    def test_accept_never_changes_subscription_or_share_level(self):
        UsageMeter.objects.create(
            user=self.agent, action="analysis", year_month="2026-07", count=3
        )
        before = self._snapshots()
        response = self._accept()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self._snapshots(), before)

    def test_previous_accepted_candidate_record_closes_without_revealing_new_leader(self):
        other_page = RecruitingPage.objects.create(owner=self.other_owner, is_published=True)
        other_campaign = RecruitingCampaign.objects.create(
            page=other_page,
            name="인스타그램",
            channel=RecruitingCampaign.Channel.INSTAGRAM,
        )
        previous = self._candidate(
            self.other_owner,
            other_campaign,
            joined_user=self.agent,
            joined_at=timezone.now() - timedelta(days=3),
            stage=RecruitingCandidate.Stage.TEAM_JOIN,
        )
        self.agent.profile.manager = self.other_owner
        self.agent.profile.save(update_fields=["manager"])

        response = self._accept(confirm_switch=True)
        self.assertEqual(response.status_code, 200, response.content)
        previous.refresh_from_db()
        self.assertEqual(previous.selection_status, RecruitingCandidate.SelectionStatus.REPLACED)
        self.assertEqual(previous.stage, RecruitingCandidate.Stage.ENDED)
        self.assertEqual(previous.name, "담당자 변경")
        self.assertEqual(previous.phone, "")
        activity = previous.activities.get(event_type=RecruitingActivity.EventType.LEADER_CHANGED)
        self.assertIsNone(activity.actor_id)
        self.assertFalse(hasattr(activity, "metadata"))

    def test_previous_leaders_unfinished_settlement_checks_stop_after_switch(self):
        other_page = RecruitingPage.objects.create(owner=self.other_owner, is_published=True)
        other_campaign = RecruitingCampaign.objects.create(
            page=other_page, name="Threads", channel=RecruitingCampaign.Channel.THREADS
        )
        previous = self._candidate(
            self.other_owner,
            other_campaign,
            joined_user=self.agent,
            joined_at=timezone.now(),
            stage=RecruitingCandidate.Stage.TEAM_JOIN,
        )
        check = SettlementCheck.objects.create(
            candidate=previous, week=4, due_on=timezone.localdate() + timedelta(days=28)
        )
        old_updated_at = check.updated_at
        consent = RecruitingConsentLog.objects.create(
            candidate=previous,
            doc_version="recruiting-contact-v1",
        )
        self.agent.profile.manager = self.other_owner
        self.agent.profile.save(update_fields=["manager"])

        self.assertEqual(self._accept(confirm_switch=True).status_code, 200)
        check.refresh_from_db()
        self.assertEqual(check.state, SettlementCheck.State.STOPPED)
        self.assertEqual(check.next_support, SettlementCheck.NextSupport.CLOSE)
        self.assertIsNotNone(check.completed_at)
        self.assertGreater(check.updated_at, old_updated_at)
        consent.refresh_from_db()
        self.assertIsNotNone(consent.revoked_at)

    def test_accept_closes_other_active_rows_only_when_manage_proof_linked_the_identity(self):
        other_page = RecruitingPage.objects.create(owner=self.other_owner, is_published=True)
        other_campaign = RecruitingCampaign.objects.create(
            page=other_page, name="다른 링크", channel=RecruitingCampaign.Channel.INSTAGRAM
        )
        linked = self._candidate(
            self.other_owner,
            other_campaign,
            identity_ref=self.candidate.identity_ref,
        )
        self.assertEqual(self._accept().status_code, 200)
        linked.refresh_from_db()
        self.assertEqual(linked.selection_status, RecruitingCandidate.SelectionStatus.REPLACED)
        self.assertEqual(linked.stage, RecruitingCandidate.Stage.ENDED)

    def test_same_phone_without_manage_proof_is_not_closed_by_another_accounts_accept(self):
        other_page = RecruitingPage.objects.create(owner=self.other_owner, is_published=True)
        other_campaign = RecruitingCampaign.objects.create(
            page=other_page, name="같은 전화", channel=RecruitingCampaign.Channel.TIKTOK
        )
        unrelated = self._candidate(
            self.other_owner,
            other_campaign,
            phone=self.candidate.phone,
        )
        self.assertNotEqual(unrelated.identity_ref, self.candidate.identity_ref)
        self.assertEqual(self._accept().status_code, 200)
        unrelated.refresh_from_db()
        self.assertEqual(unrelated.selection_status, RecruitingCandidate.SelectionStatus.ACTIVE)
        self.assertNotEqual(unrelated.stage, RecruitingCandidate.Stage.ENDED)

    def test_accept_locks_profiles_before_candidate_group_and_rolls_back_on_revalidation(self):
        api = _join_api()
        calls = []
        from inpa.recruiting import services

        real_link = services.link_agent_to_manager
        real_select = RecruitingCandidate.objects.select_for_update

        def observed_link(**kwargs):
            calls.append("profiles")
            return real_link(**kwargs)

        def observed_candidate_lock(*args, **kwargs):
            calls.append("candidates")
            return real_select(*args, **kwargs)

        with mock.patch("inpa.recruiting.services.link_agent_to_manager", side_effect=observed_link), mock.patch(
            "inpa.recruiting.services.RecruitingCandidate.objects.select_for_update",
            side_effect=observed_candidate_lock,
        ):
            with self.assertRaisesRegex(ValueError, "candidate_owner_mismatch"):
                api["accept"](
                    candidate=self.candidate,
                    agent=self.agent,
                    expected_owner_id=self.other_owner.pk,
                )

        self.assertEqual(calls[:2], ["profiles", "candidates"])
        self.agent.profile.refresh_from_db()
        self.assertIsNone(self.agent.profile.manager_id)

    def test_token_owner_is_rechecked_after_candidate_lock(self):
        response = self._accept(token=_join_api()["make_token"](self.candidate))
        self.assertEqual(response.status_code, 200)

        payload = {"candidate_id": self.candidate.pk, "owner_id": self.other_owner.pk, "v": 1}
        forged = signing.dumps(payload, salt=_join_api()["join_salt"], compress=True)
        other_agent = self._user("other-agent@inpa.local")
        rejected = self._accept(token=forged, user=other_agent)
        self.assertEqual(rejected.status_code, 410)
        other_agent.profile.refresh_from_db()
        self.assertIsNone(other_agent.profile.manager_id)

    def test_feature_flag_off_hides_join_and_issue_routes(self):
        with override_settings(RECRUITING_ENABLED=False):
            info = self.client.get(f"/api/v1/recruiting/join/{self._token()}/")
            self.client.force_authenticate(self.owner)
            issued = self.client.post(
                f"/api/v1/recruiting/candidates/{self.candidate.pk}/team-invite/"
            )
        self.assertEqual(info.status_code, 404)
        self.assertEqual(issued.status_code, 404)

    def test_candidate_state_change_after_issue_returns_generic_410_without_team_change(self):
        cases = [
            {"selection_status": RecruitingCandidate.SelectionStatus.REPLACED},
            {"contact_opt_out_at": timezone.now()},
            {"stage": RecruitingCandidate.Stage.ENDED},
        ]
        for index, changes in enumerate(cases):
            candidate = self._candidate(
                self.owner,
                self.campaign,
                phone=f"0101111000{index}",
            )
            token = self._token(candidate)
            RecruitingCandidate.objects.filter(pk=candidate.pk).update(**changes)
            with self.subTest(changes=changes):
                info = self.client.get(f"/api/v1/recruiting/join/{token}/")
                accepted = self._accept(token=token)
                self.assertEqual(info.status_code, 410)
                self.assertEqual(accepted.status_code, 410)
                self.assertNotIn(candidate.name, str(info.json()))
                self.assertNotIn(candidate.phone, str(accepted.json()))
                self.agent.profile.refresh_from_db()
                self.assertIsNone(self.agent.profile.manager_id)

    def test_team_invite_issue_is_owner_only_and_returns_relative_path(self):
        self.client.force_authenticate(self.other_owner)
        hidden = self.client.post(
            f"/api/v1/recruiting/candidates/{self.candidate.pk}/team-invite/"
        )
        self.assertEqual(hidden.status_code, 404)

        self.client.force_authenticate(self.owner)
        issued = self.client.post(
            f"/api/v1/recruiting/candidates/{self.candidate.pk}/team-invite/"
        )
        self.assertEqual(issued.status_code, 200, issued.content)
        self.assertEqual(set(issued.json()), {"join_path", "expires_at"})
        self.assertTrue(issued.json()["join_path"].startswith("/recruiting/join/"))
        self.assertNotIn("http", issued.json()["join_path"])
        self.assertTrue(issued.json()["expires_at"].endswith("+09:00"))
        self.assertNotIn("identity_ref", str(issued.json()))

    def test_team_invite_locks_owner_row_inside_atomic_without_mutating_candidate(self):
        self.client.force_authenticate(self.owner)
        before = RecruitingCandidate.objects.filter(pk=self.candidate.pk).values().get()
        real_lock = RecruitingCandidate.objects.select_for_update
        from inpa.recruiting import views as recruiting_views

        real_make_token = recruiting_views.make_recruiting_join_token
        atomic_observations = []

        def observe_token(candidate):
            atomic_observations.append(connection.in_atomic_block)
            return real_make_token(candidate)

        with mock.patch(
            "inpa.recruiting.views.RecruitingCandidate.objects.select_for_update",
            wraps=real_lock,
        ) as select_for_update, mock.patch(
            "inpa.recruiting.views.make_recruiting_join_token",
            side_effect=observe_token,
        ):
            response = self.client.post(
                f"/api/v1/recruiting/candidates/{self.candidate.pk}/team-invite/"
            )

        self.assertEqual(response.status_code, 200, response.content)
        select_for_update.assert_called_once_with()
        self.assertEqual(atomic_observations, [True])
        self.assertEqual(
            RecruitingCandidate.objects.filter(pk=self.candidate.pk).values().get(),
            before,
        )

    def test_team_invite_issue_blocks_inactive_optout_ended_and_joined_candidates(self):
        self.client.force_authenticate(self.owner)
        cases = [
            {"selection_status": RecruitingCandidate.SelectionStatus.REPLACED},
            {"contact_opt_out_at": timezone.now()},
            {"stage": RecruitingCandidate.Stage.ENDED},
            {"joined_user": self.agent},
        ]
        for index, changes in enumerate(cases):
            candidate = self._candidate(
                self.owner,
                self.campaign,
                phone=f"0100000000{index}",
                **changes,
            )
            with self.subTest(changes=changes):
                response = self.client.post(
                    f"/api/v1/recruiting/candidates/{candidate.pk}/team-invite/"
                )
                self.assertIn(response.status_code, {400, 409})


@override_settings(RECRUITING_ENABLED=True)
class SettlementCheckTests(TestCase):
    def setUp(self):
        Plan.objects.create(code="free", display_name="Free", price_krw=0)
        self.owner = User.objects.create_user(email="settlement-owner@inpa.local", password="pass")
        self.other = User.objects.create_user(email="settlement-other@inpa.local", password="pass")
        Profile.objects.create(user=self.owner)
        Profile.objects.create(user=self.other)
        page = RecruitingPage.objects.create(owner=self.owner, is_published=True)
        campaign = RecruitingCampaign.objects.create(
            page=page, name="개인 소개", channel=RecruitingCampaign.Channel.RELATIONSHIP
        )
        self.candidate = RecruitingCandidate.objects.create(
            owner=self.owner,
            campaign=campaign,
            name="정착 설계사",
            phone="",
            career_band=RecruitingCandidate.CareerBand.ONE_TO_THREE,
            region="",
            contact_window=RecruitingCandidate.ContactWindow.ANYTIME,
            stage=RecruitingCandidate.Stage.TEAM_JOIN,
        )
        self.checks = [
            SettlementCheck.objects.create(
                candidate=self.candidate,
                week=week,
                due_on=timezone.localdate() + timedelta(days=week * 7),
            )
            for week in (1, 4, 8, 13)
        ]
        self.client = APIClient()

    def test_reopen_has_dedicated_activity_and_event_enums(self):
        self.assertIn(
            "settlement_reopened", RecruitingActivity.EventType.values
        )
        self.assertIn(
            "settlement_reopened", RecruitingEvent.EventType.values
        )

    def test_support_needed_requires_blocker_and_next_support(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            f"/api/v1/recruiting/settlement-checks/{self.checks[0].pk}/complete/",
            {"state": "support_needed", "blocker": "none", "next_support": ""},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.checks[0].refresh_from_db()
        self.assertIsNone(self.checks[0].completed_at)

    def test_settlement_complete_is_owner_only_and_records_safe_activity_and_event(self):
        self.client.force_authenticate(self.other)
        hidden = self.client.post(
            f"/api/v1/recruiting/settlement-checks/{self.checks[0].pk}/complete/",
            {"state": "active"},
            format="json",
        )
        self.assertEqual(hidden.status_code, 404)

        self.client.force_authenticate(self.owner)
        with self.captureOnCommitCallbacks(execute=True):
            completed = self.client.post(
                f"/api/v1/recruiting/settlement-checks/{self.checks[0].pk}/complete/",
                {"state": "support_needed", "blocker": "customer_prospecting", "next_support": "activity_plan"},
                format="json",
            )
        self.assertEqual(completed.status_code, 200, completed.content)
        activity = RecruitingActivity.objects.get(
            candidate=self.candidate,
            event_type=RecruitingActivity.EventType.SETTLEMENT_COMPLETED,
        )
        event = RecruitingEvent.objects.get(
            candidate=self.candidate,
            event_type=RecruitingEvent.EventType.SETTLEMENT_COMPLETED,
        )
        self.assertEqual(activity.actor, self.owner)
        self.assertNotIn("identity_ref", str(activity.__dict__))
        self.assertEqual(event.metadata, {"week": 1, "state": "support_needed"})

    def test_stopped_settlement_closes_future_unfinished_checks(self):
        result = _join_api()["complete"](
            check=self.checks[1],
            owner=self.owner,
            state=SettlementCheck.State.STOPPED,
            blocker="",
            next_support="",
        )
        self.assertEqual(result.state, SettlementCheck.State.STOPPED)
        for check in self.checks[1:]:
            check.refresh_from_db()
            self.assertEqual(check.state, SettlementCheck.State.STOPPED)
            self.assertEqual(check.next_support, SettlementCheck.NextSupport.CLOSE)
            self.assertIsNotNone(check.completed_at)
        self.checks[0].refresh_from_db()
        self.assertIsNone(self.checks[0].completed_at)

    def test_active_settlement_normalizes_blocker_and_next_support(self):
        result = _join_api()["complete"](
            check=self.checks[0],
            owner=self.owner,
            state=SettlementCheck.State.ACTIVE,
            blocker=SettlementCheck.Blocker.PERSONAL,
            next_support=SettlementCheck.NextSupport.TRAINING,
        )
        self.assertEqual(result.blocker, SettlementCheck.Blocker.NONE)
        self.assertEqual(result.next_support, SettlementCheck.NextSupport.SCHEDULE_ONLY)

    def test_service_rejects_invalid_state_and_blocker_choices(self):
        with self.assertRaises(ValidationError):
            _join_api()["complete"](
                check=self.checks[0],
                owner=self.owner,
                state="unknown",
                blocker="",
                next_support="",
            )
        with self.assertRaises(ValidationError):
            _join_api()["complete"](
                check=self.checks[0],
                owner=self.owner,
                state=SettlementCheck.State.ACTIVE,
                blocker="unknown",
                next_support=SettlementCheck.NextSupport.TRAINING,
            )

    def test_service_rejects_invalid_next_support_even_when_stopped(self):
        with self.assertRaises(ValidationError):
            _join_api()["complete"](
                check=self.checks[0],
                owner=self.owner,
                state=SettlementCheck.State.STOPPED,
                blocker=SettlementCheck.Blocker.NONE,
                next_support="unknown",
            )

    def test_same_normalized_settlement_update_is_fully_idempotent(self):
        with self.captureOnCommitCallbacks(execute=True):
            first = _join_api()["complete"](
                check=self.checks[0],
                owner=self.owner,
                state=SettlementCheck.State.ACTIVE,
                blocker="",
                next_support="",
            )
        completed_at = first.completed_at
        updated_at = first.updated_at
        activity_count = RecruitingActivity.objects.filter(candidate=self.candidate).count()
        event_count = RecruitingEvent.objects.filter(candidate=self.candidate).count()

        with self.captureOnCommitCallbacks(execute=True):
            repeated = _join_api()["complete"](
                check=self.checks[0],
                owner=self.owner,
                state=SettlementCheck.State.ACTIVE,
                blocker=SettlementCheck.Blocker.PERSONAL,
                next_support=SettlementCheck.NextSupport.TRAINING,
            )

        self.assertEqual(repeated.completed_at, completed_at)
        self.assertEqual(repeated.updated_at, updated_at)
        self.assertEqual(
            RecruitingActivity.objects.filter(candidate=self.candidate).count(),
            activity_count,
        )
        self.assertEqual(
            RecruitingEvent.objects.filter(candidate=self.candidate).count(),
            event_count,
        )

    def test_changed_completed_settlement_preserves_first_date_and_appends_history(self):
        self.checks[0].due_on = timezone.localdate() - timedelta(days=1)
        self.checks[0].save(update_fields=["due_on", "updated_at"])
        with self.captureOnCommitCallbacks(execute=True):
            first = _join_api()["complete"](
                check=self.checks[0],
                owner=self.owner,
                state=SettlementCheck.State.ACTIVE,
                blocker="",
                next_support="",
            )
        completed_at = first.completed_at
        previous_activity_ids = list(
            RecruitingActivity.objects.filter(candidate=self.candidate).values_list("pk", flat=True)
        )

        with self.captureOnCommitCallbacks(execute=True):
            changed = _join_api()["complete"](
                check=self.checks[0],
                owner=self.owner,
                state=SettlementCheck.State.SUPPORT_NEEDED,
                blocker=SettlementCheck.Blocker.CUSTOMER_PROSPECTING,
                next_support=SettlementCheck.NextSupport.ACTIVITY_PLAN,
            )

        self.assertEqual(changed.completed_at, completed_at)
        self.assertTrue(
            RecruitingActivity.objects.filter(pk__in=previous_activity_ids).exists()
        )
        self.assertEqual(
            RecruitingActivity.objects.filter(candidate=self.candidate).count(), 2
        )
        self.assertEqual(RecruitingEvent.objects.filter(candidate=self.candidate).count(), 2)

    def test_future_auto_stopped_check_can_reopen_pending_without_deleting_history(self):
        with self.captureOnCommitCallbacks(execute=True):
            _join_api()["complete"](
                check=self.checks[0],
                owner=self.owner,
                state=SettlementCheck.State.STOPPED,
                blocker="",
                next_support="",
            )
        future = self.checks[1]
        future.refresh_from_db()
        self.assertEqual(future.state, SettlementCheck.State.STOPPED)
        self.assertIsNotNone(future.completed_at)
        previous_activity_ids = list(
            RecruitingActivity.objects.filter(candidate=self.candidate).values_list("pk", flat=True)
        )
        completed_activity_count = RecruitingActivity.objects.filter(
            candidate=self.candidate,
            event_type=RecruitingActivity.EventType.SETTLEMENT_COMPLETED,
        ).count()

        with self.captureOnCommitCallbacks(execute=True):
            reopened = _join_api()["reopen"](
                check=future,
                owner=self.owner,
            )

        self.assertEqual(reopened.state, SettlementCheck.State.ACTIVE)
        self.assertEqual(reopened.blocker, SettlementCheck.Blocker.NONE)
        self.assertEqual(reopened.next_support, SettlementCheck.NextSupport.SCHEDULE_ONLY)
        self.assertIsNone(reopened.completed_at)
        self.assertTrue(
            RecruitingActivity.objects.filter(pk__in=previous_activity_ids).exists()
        )
        self.assertEqual(
            RecruitingActivity.objects.filter(candidate=self.candidate).count(), 2
        )
        self.assertEqual(
            RecruitingActivity.objects.filter(
                candidate=self.candidate,
                event_type=RecruitingActivity.EventType.SETTLEMENT_COMPLETED,
            ).count(),
            completed_activity_count,
        )
        self.assertEqual(
            RecruitingActivity.objects.filter(
                candidate=self.candidate,
                event_type=RecruitingActivity.EventType.SETTLEMENT_REOPENED,
            ).count(),
            1,
        )
        reopen_event = RecruitingEvent.objects.get(
            candidate=self.candidate,
            event_type=RecruitingEvent.EventType.SETTLEMENT_REOPENED,
        )
        self.assertEqual(reopen_event.metadata, {"week": 4, "state": "active"})

        reopened_at = reopened.updated_at
        activity_count = RecruitingActivity.objects.filter(candidate=self.candidate).count()
        event_count = RecruitingEvent.objects.filter(candidate=self.candidate).count()
        with self.captureOnCommitCallbacks(execute=True):
            repeated = _join_api()["reopen"](check=future, owner=self.owner)
        self.assertIsNone(repeated.completed_at)
        self.assertEqual(repeated.updated_at, reopened_at)
        self.assertEqual(
            RecruitingActivity.objects.filter(candidate=self.candidate).count(),
            activity_count,
        )
        self.assertEqual(
            RecruitingEvent.objects.filter(candidate=self.candidate).count(), event_count
        )

    def test_reopened_active_check_can_be_completed_later(self):
        with self.captureOnCommitCallbacks(execute=True):
            _join_api()["complete"](
                check=self.checks[0],
                owner=self.owner,
                state=SettlementCheck.State.STOPPED,
                blocker="",
                next_support="",
            )
        future = SettlementCheck.objects.get(pk=self.checks[1].pk)
        self.client.force_authenticate(self.owner)
        with self.captureOnCommitCallbacks(execute=True):
            reopen_response = self.client.post(
                f"/api/v1/recruiting/settlement-checks/{future.pk}/reopen/",
                {},
                format="json",
            )
        self.assertEqual(reopen_response.status_code, 200, reopen_response.content)
        reopened = SettlementCheck.objects.get(pk=future.pk)
        self.assertIsNone(reopened.completed_at)
        completed_before = RecruitingActivity.objects.filter(
            candidate=self.candidate,
            event_type=RecruitingActivity.EventType.SETTLEMENT_COMPLETED,
        ).count()

        updated_at = reopened.updated_at
        activity_count = RecruitingActivity.objects.filter(candidate=self.candidate).count()
        event_count = RecruitingEvent.objects.filter(candidate=self.candidate).count()
        with self.captureOnCommitCallbacks(execute=True):
            repeated_response = self.client.post(
                f"/api/v1/recruiting/settlement-checks/{future.pk}/reopen/",
                {},
                format="json",
            )
        self.assertEqual(repeated_response.status_code, 200, repeated_response.content)
        reopened.refresh_from_db()
        self.assertIsNone(reopened.completed_at)
        self.assertEqual(reopened.updated_at, updated_at)
        self.assertEqual(
            RecruitingActivity.objects.filter(candidate=self.candidate).count(),
            activity_count,
        )
        self.assertEqual(
            RecruitingEvent.objects.filter(candidate=self.candidate).count(), event_count
        )

        with self.captureOnCommitCallbacks(execute=True):
            completed = _join_api()["complete"](
                check=future,
                owner=self.owner,
                state=SettlementCheck.State.ACTIVE,
                blocker="",
                next_support="",
            )

        self.assertIsNotNone(completed.completed_at)
        self.assertEqual(
            RecruitingActivity.objects.filter(
                candidate=self.candidate,
                event_type=RecruitingActivity.EventType.SETTLEMENT_COMPLETED,
            ).count(),
            completed_before + 1,
        )

        completed_at = completed.completed_at
        activity_count = RecruitingActivity.objects.filter(candidate=self.candidate).count()
        event_count = RecruitingEvent.objects.filter(candidate=self.candidate).count()
        with self.captureOnCommitCallbacks(execute=True):
            retried = _join_api()["complete"](
                check=future,
                owner=self.owner,
                state=SettlementCheck.State.ACTIVE,
                blocker="",
                next_support="",
            )
        self.assertEqual(retried.completed_at, completed_at)
        self.assertEqual(
            RecruitingActivity.objects.filter(candidate=self.candidate).count(),
            activity_count,
        )
        self.assertEqual(
            RecruitingEvent.objects.filter(candidate=self.candidate).count(), event_count
        )

    def test_complete_stopped_to_active_never_reopens_implicitly(self):
        with self.captureOnCommitCallbacks(execute=True):
            _join_api()["complete"](
                check=self.checks[0],
                owner=self.owner,
                state=SettlementCheck.State.STOPPED,
                blocker="",
                next_support="",
            )
        future = SettlementCheck.objects.get(pk=self.checks[1].pk)
        first_completed_at = future.completed_at

        with self.captureOnCommitCallbacks(execute=True):
            changed = _join_api()["complete"](
                check=future,
                owner=self.owner,
                state=SettlementCheck.State.ACTIVE,
                blocker="",
                next_support="",
            )

        self.assertEqual(changed.state, SettlementCheck.State.ACTIVE)
        self.assertEqual(changed.completed_at, first_completed_at)
        self.assertEqual(
            RecruitingActivity.objects.filter(
                candidate=self.candidate,
                event_type=RecruitingActivity.EventType.SETTLEMENT_REOPENED,
            ).count(),
            0,
        )

    def test_reopen_rejects_past_or_nonstopped_completed_checks_with_positive_detail(self):
        now = timezone.now()
        cases = (
            (self.checks[0], SettlementCheck.State.STOPPED, timezone.localdate() - timedelta(days=1)),
            (self.checks[1], SettlementCheck.State.SUPPORT_NEEDED, timezone.localdate() + timedelta(days=1)),
            (self.checks[2], SettlementCheck.State.ACTIVE, timezone.localdate() + timedelta(days=1)),
        )
        for check, state, due_on in cases:
            SettlementCheck.objects.filter(pk=check.pk).update(
                state=state,
                blocker=(
                    SettlementCheck.Blocker.CUSTOMER_PROSPECTING
                    if state == SettlementCheck.State.SUPPORT_NEEDED
                    else SettlementCheck.Blocker.NONE
                ),
                next_support=(
                    SettlementCheck.NextSupport.ACTIVITY_PLAN
                    if state == SettlementCheck.State.SUPPORT_NEEDED
                    else SettlementCheck.NextSupport.SCHEDULE_ONLY
                ),
                due_on=due_on,
                completed_at=now,
            )
            self.client.force_authenticate(self.owner)
            with self.subTest(state=state, due_on=due_on):
                response = self.client.post(
                    f"/api/v1/recruiting/settlement-checks/{check.pk}/reopen/",
                    {},
                    format="json",
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("확인", str(response.json()))

    def test_reopen_is_owner_only(self):
        SettlementCheck.objects.filter(pk=self.checks[1].pk).update(
            state=SettlementCheck.State.STOPPED,
            blocker=SettlementCheck.Blocker.NONE,
            next_support=SettlementCheck.NextSupport.CLOSE,
            completed_at=timezone.now(),
        )
        self.client.force_authenticate(self.other)
        response = self.client.post(
            f"/api/v1/recruiting/settlement-checks/{self.checks[1].pk}/reopen/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 404)

    def test_reopen_analytics_failure_keeps_required_reopen_history(self):
        with self.captureOnCommitCallbacks(execute=True):
            _join_api()["complete"](
                check=self.checks[0],
                owner=self.owner,
                state=SettlementCheck.State.STOPPED,
                blocker="",
                next_support="",
            )
        future = SettlementCheck.objects.get(pk=self.checks[1].pk)

        with mock.patch(
            "inpa.recruiting.services.RecruitingEvent.objects.create",
            side_effect=RuntimeError("analytics down"),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                reopened = _join_api()["reopen"](check=future, owner=self.owner)

        reopened.refresh_from_db()
        self.assertEqual(reopened.state, SettlementCheck.State.ACTIVE)
        self.assertIsNone(reopened.completed_at)
        self.assertTrue(
            RecruitingActivity.objects.filter(
                candidate=self.candidate,
                event_type=RecruitingActivity.EventType.SETTLEMENT_REOPENED,
            ).exists()
        )
        self.assertFalse(
            RecruitingEvent.objects.filter(
                candidate=self.candidate,
                event_type=RecruitingEvent.EventType.SETTLEMENT_REOPENED,
            ).exists()
        )

    def test_analytics_failure_does_not_rollback_required_settlement_history(self):
        with mock.patch(
            "inpa.recruiting.services.RecruitingEvent.objects.create",
            side_effect=RuntimeError("analytics down"),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                updated = _join_api()["complete"](
                    check=self.checks[0],
                    owner=self.owner,
                    state=SettlementCheck.State.ACTIVE,
                    blocker="",
                    next_support="",
                )

        updated.refresh_from_db()
        self.assertIsNotNone(updated.completed_at)
        self.assertTrue(
            RecruitingActivity.objects.filter(
                candidate=self.candidate,
                event_type=RecruitingActivity.EventType.SETTLEMENT_COMPLETED,
            ).exists()
        )
        self.assertFalse(RecruitingEvent.objects.filter(candidate=self.candidate).exists())
