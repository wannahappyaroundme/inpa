"""Team linking and sticky manager-role regressions."""
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from inpa.billing.models import Plan, Subscription, UsageMeter

from .invite import make_invite_token, resolve_invite_manager
from .models import Profile, User


def _team_api():
    try:
        from .team import (
            TeamSwitchConfirmationRequired,
            link_agent_to_manager,
            profile_has_manager_role,
        )
    except ImportError as exc:
        raise AssertionError("accounts.team service is not implemented") from exc
    return TeamSwitchConfirmationRequired, link_agent_to_manager, profile_has_manager_role


def _subscription_snapshot():
    return list(
        Subscription.objects.order_by("pk").values(
            "user_id", "plan_id", "status", "started_at", "expires_at"
        )
    )


def _usage_snapshot():
    return list(UsageMeter.objects.order_by("pk").values())


class TeamLinkServiceTests(TestCase):
    def setUp(self):
        self.free_plan = Plan.objects.create(
            code="free", display_name="Free", price_krw=0
        )
        self.manager_plan = Plan.objects.create(
            code="manager", display_name="Manager", price_krw=19900
        )
        self.manager = self._user("manager@test.com")
        self.other_manager = self._user("other-manager@test.com")
        self.agent = self._user("agent@test.com")

    def _user(self, email):
        user = User.objects.create_user(email=email, password="inpaPass123!")
        user.is_active = True
        user.save(update_fields=["is_active"])
        Profile.objects.create(user=user)
        return user

    def _subscribe_manager(self, user):
        Subscription.objects.filter(user=user).update(
            plan=self.manager_plan, status="active", expires_at=None
        )

    def test_first_real_team_link_stamps_manager_promotion_once(self):
        _, link_agent_to_manager, _ = _team_api()

        first = link_agent_to_manager(agent=self.agent, manager=self.manager)
        self.manager.profile.refresh_from_db()
        promoted_at = self.manager.profile.manager_promoted_at

        second_agent = self._user("second-agent@test.com")
        second = link_agent_to_manager(agent=second_agent, manager=self.manager)
        self.manager.profile.refresh_from_db()

        self.assertTrue(first.promoted_now)
        self.assertFalse(second.promoted_now)
        self.assertIsNotNone(promoted_at)
        self.assertEqual(self.manager.profile.manager_promoted_at, promoted_at)
        self.assertIsNone(self.manager.profile.manager_promotion_seen_at)

    def test_removing_last_agent_does_not_remove_manager_role(self):
        _, link_agent_to_manager, profile_has_manager_role = _team_api()
        link_agent_to_manager(agent=self.agent, manager=self.manager)
        self.agent.profile.refresh_from_db()
        self.agent.profile.manager = None
        self.agent.profile.save(update_fields=["manager"])
        self.manager.profile.refresh_from_db()

        self.assertEqual(self.manager.managed_agents.count(), 0)
        self.assertTrue(profile_has_manager_role(self.manager.profile))

    def test_team_link_never_changes_manager_share_level(self):
        _, link_agent_to_manager, _ = _team_api()
        profile = self.agent.profile
        profile.manager_share_level = Profile.SHARE_FULL
        profile.manager_share_opt_in = True
        profile.save(update_fields=["manager_share_level", "manager_share_opt_in"])

        link_agent_to_manager(agent=self.agent, manager=self.manager)
        profile.refresh_from_db()

        self.assertEqual(profile.manager_share_level, Profile.SHARE_FULL)
        self.assertTrue(profile.manager_share_opt_in)

    def test_team_link_never_updates_subscription_or_usage(self):
        _, link_agent_to_manager, _ = _team_api()
        UsageMeter.objects.create(
            user=self.manager, action="ocr", year_month="2026-07", count=4
        )
        UsageMeter.objects.create(
            user=self.agent, action="analysis", year_month="2026-07", count=2
        )
        subscriptions_before = _subscription_snapshot()
        usage_before = _usage_snapshot()

        link_agent_to_manager(agent=self.agent, manager=self.manager)

        self.assertEqual(_subscription_snapshot(), subscriptions_before)
        self.assertEqual(_usage_snapshot(), usage_before)

    def test_self_management_is_rejected(self):
        _, link_agent_to_manager, _ = _team_api()

        with self.assertRaisesRegex(ValueError, "self_management"):
            link_agent_to_manager(agent=self.manager, manager=self.manager)
        self.manager.profile.refresh_from_db()
        self.assertIsNone(self.manager.profile.manager_id)

    def test_switching_manager_requires_explicit_confirmation(self):
        TeamSwitchConfirmationRequired, link_agent_to_manager, _ = _team_api()
        self.agent.profile.manager = self.manager
        self.agent.profile.save(update_fields=["manager"])

        with self.assertRaises(TeamSwitchConfirmationRequired):
            link_agent_to_manager(agent=self.agent, manager=self.other_manager)

        self.agent.profile.refresh_from_db()
        self.other_manager.profile.refresh_from_db()
        self.assertEqual(self.agent.profile.manager_id, self.manager.pk)
        self.assertIsNone(self.other_manager.profile.manager_promoted_at)

    def test_confirmed_switch_updates_only_profile_manager(self):
        _, link_agent_to_manager, _ = _team_api()
        self.agent.profile.manager = self.manager
        self.agent.profile.save(update_fields=["manager"])
        before = Profile.objects.filter(pk=self.agent.profile.pk).values().get()

        result = link_agent_to_manager(
            agent=self.agent,
            manager=self.other_manager,
            confirm_switch=True,
        )

        after = Profile.objects.filter(pk=self.agent.profile.pk).values().get()
        changed_fields = {key for key in before if before[key] != after[key]}
        self.assertEqual(changed_fields, {"manager_id"})
        self.assertEqual(after["manager_id"], self.other_manager.pk)
        self.assertTrue(result.switched)

    def test_legacy_manager_subscription_counts_as_manager_role(self):
        _, _, profile_has_manager_role = _team_api()
        self._subscribe_manager(self.manager)
        self.manager.profile.refresh_from_db()

        self.assertIsNone(self.manager.profile.manager_promoted_at)
        self.assertTrue(profile_has_manager_role(self.manager.profile))

    def test_legacy_manager_first_team_link_is_marked_seen_without_new_promotion_notice(self):
        _, link_agent_to_manager, _ = _team_api()
        self._subscribe_manager(self.manager)

        result = link_agent_to_manager(agent=self.agent, manager=self.manager)
        self.manager.profile.refresh_from_db()

        self.assertFalse(result.promoted_now)
        self.assertIsNotNone(self.manager.profile.manager_promoted_at)
        self.assertEqual(
            self.manager.profile.manager_promotion_seen_at,
            self.manager.profile.manager_promoted_at,
        )


class TeamProfileApiTests(TestCase):
    def setUp(self):
        Plan.objects.create(code="free", display_name="Free", price_krw=0)
        self.manager = User.objects.create_user(
            email="profile-manager@test.com", password="inpaPass123!"
        )
        self.manager.is_active = True
        self.manager.save(update_fields=["is_active"])
        Profile.objects.create(user=self.manager)
        self.agent = User.objects.create_user(
            email="profile-agent@test.com", password="inpaPass123!"
        )
        self.agent.is_active = True
        self.agent.save(update_fields=["is_active"])
        Profile.objects.create(user=self.agent)
        self.client = APIClient()
        self.client.force_authenticate(user=self.manager)

    @override_settings(RECRUITING_ENABLED=True)
    def test_profile_exposes_recruiting_feature_flag_read_only(self):
        _, link_agent_to_manager, _ = _team_api()
        link_agent_to_manager(agent=self.agent, manager=self.manager)

        response = self.client.get("/api/v1/auth/profile/")
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertTrue(body["recruiting_enabled"])
        self.assertTrue(body["is_manager"])
        self.assertIsNotNone(body["manager_promoted_at"])
        self.assertIsNone(body["manager_promotion_seen_at"])
        self.assertEqual(body["managed_agents_count"], 1)

        patched = self.client.patch(
            "/api/v1/auth/profile/",
            {
                "recruiting_enabled": False,
                "is_manager": False,
                "manager_promoted_at": None,
                "manager_promotion_seen_at": "2020-01-01T00:00:00Z",
            },
            format="json",
        )
        self.assertEqual(patched.status_code, 200, patched.content)
        self.assertTrue(patched.json()["recruiting_enabled"])
        self.assertTrue(patched.json()["is_manager"])
        self.manager.profile.refresh_from_db()
        self.assertIsNotNone(self.manager.profile.manager_promoted_at)
        self.assertIsNone(self.manager.profile.manager_promotion_seen_at)

    def test_manager_promotion_ack_records_seen_once(self):
        _, link_agent_to_manager, _ = _team_api()
        link_agent_to_manager(agent=self.agent, manager=self.manager)

        first = self.client.post("/api/v1/auth/manager-promotion/ack/")
        self.assertEqual(first.status_code, 200, first.content)
        self.manager.profile.refresh_from_db()
        seen_at = self.manager.profile.manager_promotion_seen_at
        self.assertIsNotNone(seen_at)

        second = self.client.post("/api/v1/auth/manager-promotion/ack/")
        self.assertEqual(second.status_code, 200, second.content)
        self.manager.profile.refresh_from_db()
        self.assertEqual(self.manager.profile.manager_promotion_seen_at, seen_at)
        self.assertIsNotNone(self.manager.profile.manager_promoted_at)


class GenericInviteTeamServiceTests(TestCase):
    def setUp(self):
        self.free_plan = Plan.objects.create(
            code="free", display_name="Free", price_krw=0
        )
        self.manager = User.objects.create_user(
            email="invite-manager@test.com", password="inpaPass123!"
        )
        self.manager.is_active = True
        self.manager.save(update_fields=["is_active"])
        Profile.objects.create(user=self.manager, affiliation="인파 강남")
        self.client = APIClient()
        self.payload = {
            "email": "invite-agent@test.com",
            "password": "inpaPass123!",
            "password_confirm": "inpaPass123!",
            "tos_agreed": True,
            "pp_agreed": True,
        }

    def test_existing_generic_invite_token_still_resolves(self):
        token = make_invite_token(self.manager)

        self.assertEqual(resolve_invite_manager(token), self.manager)
        response = self.client.get(
            "/api/v1/manager/invite-info/", {"token": token}
        )
        self.assertEqual(response.status_code, 200, response.content)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_generic_invite_registration_uses_team_service(self):
        token = make_invite_token(self.manager)

        response = self.client.post(
            "/api/v1/auth/register/",
            {**self.payload, "invite_token": token},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        agent = User.objects.get(email=self.payload["email"])
        self.assertEqual(agent.profile.manager_id, self.manager.pk)
        self.manager.profile.refresh_from_db()
        self.assertIsNotNone(
            getattr(self.manager.profile, "manager_promoted_at", None)
        )

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_generic_invite_signup_succeeds_when_free_plan_seed_is_temporarily_missing(self):
        Subscription.objects.all().delete()
        self.free_plan.delete()
        token = make_invite_token(self.manager)

        response = self.client.post(
            "/api/v1/auth/register/",
            {**self.payload, "invite_token": token},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        agent = User.objects.get(email=self.payload["email"])
        self.assertEqual(agent.profile.manager_id, self.manager.pk)
        self.manager.profile.refresh_from_db()
        self.assertIsNotNone(
            getattr(self.manager.profile, "manager_promoted_at", None)
        )
        self.assertFalse(Subscription.objects.exists())
