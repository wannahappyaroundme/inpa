"""Team linking and sticky manager-role regressions."""
from datetime import timedelta
import importlib
from io import BytesIO
from pathlib import Path
import tempfile
from unittest import mock

from django.apps import apps as django_apps
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import OperationalError, connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from inpa.billing.models import Plan, Subscription, UsageMeter

from . import views as account_views
from .invite import make_invite_token, resolve_invite_manager
from .models import Profile, User
from .serializers import RegisterSerializer


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

    def test_team_profiles_are_locked_in_one_stable_order(self):
        _, link_agent_to_manager, _ = _team_api()

        with CaptureQueriesContext(connection) as queries:
            link_agent_to_manager(agent=self.agent, manager=self.manager)

        lock_queries = [
            query['sql']
            for query in queries.captured_queries
            if 'FROM "accounts_profile"' in query['sql']
            and '"accounts_profile"."user_id" IN' in query['sql']
        ]
        self.assertEqual(len(lock_queries), 1, lock_queries)
        self.assertIn(
            'ORDER BY "accounts_profile"."user_id" ASC',
            lock_queries[0],
        )

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


class ExistingManagerLinkApiTests(TestCase):
    def setUp(self):
        Plan.objects.create(code='free', display_name='Free', price_krw=0)
        self.first_manager = self._user('first-manager@test.com')
        self.second_manager = self._user('second-manager@test.com')
        self.agent = self._user('existing-agent@test.com')
        self.agent.profile.name = '기존 이름'
        self.agent.profile.affiliation = '기존 소속'
        self.agent.profile.manager = self.first_manager
        self.agent.profile.save(update_fields=['name', 'affiliation', 'manager'])
        self.client = APIClient()
        self.client.force_authenticate(user=self.agent)

    def _user(self, email):
        user = User.objects.create_user(email=email, password='inpaPass123!')
        user.is_active = True
        user.save(update_fields=['is_active'])
        Profile.objects.create(user=user)
        return user

    def _profile_image_upload(self):
        content = BytesIO()
        Image.new('RGB', (2, 2), color='white').save(content, format='PNG')
        return SimpleUploadedFile(
            'profile.png',
            content.getvalue(),
            content_type='image/png',
        )

    def test_profile_switch_requires_confirmation_and_rolls_back_changes(self):
        response = self.client.patch(
            '/api/v1/auth/profile/',
            {
                'name': '바뀌면 안 되는 이름',
                'manager_email': self.second_manager.email,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()['code'], 'team_switch_confirmation_required')
        self.assertIn('확인', response.json()['detail'])
        self.agent.profile.refresh_from_db()
        self.assertEqual(self.agent.profile.name, '기존 이름')
        self.assertEqual(self.agent.profile.manager_id, self.first_manager.pk)

    def test_confirmed_profile_switch_saves_changes(self):
        response = self.client.patch(
            '/api/v1/auth/profile/',
            {
                'name': '변경된 이름',
                'manager_email': self.second_manager.email,
                'confirm_manager_switch': True,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.agent.profile.refresh_from_db()
        self.assertEqual(self.agent.profile.name, '변경된 이름')
        self.assertEqual(self.agent.profile.manager_id, self.second_manager.pk)

    def test_confirmed_profile_switch_links_before_other_profile_writes(self):
        observed_names = []
        real_link_manager = account_views._link_manager

        def observe_then_link(profile, manager_email, **kwargs):
            observed_names.append(Profile.objects.get(pk=profile.pk).name)
            return real_link_manager(profile, manager_email, **kwargs)

        with mock.patch(
            'inpa.accounts.views._link_manager',
            side_effect=observe_then_link,
        ):
            response = self.client.patch(
                '/api/v1/auth/profile/',
                {
                    'name': '연결 뒤 저장할 이름',
                    'manager_email': self.second_manager.email,
                    'confirm_manager_switch': True,
                },
                format='json',
            )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(observed_names, ['기존 이름'])
        self.agent.profile.refresh_from_db()
        self.assertEqual(self.agent.profile.name, '연결 뒤 저장할 이름')
        self.assertEqual(self.agent.profile.manager_id, self.second_manager.pk)

    def test_unconfirmed_profile_switch_does_not_store_uploaded_image(self):
        image_field = Profile._meta.get_field('profile_image')

        with tempfile.TemporaryDirectory() as media_root:
            storage = FileSystemStorage(location=media_root)
            with (
                override_settings(MEDIA_ROOT=media_root),
                mock.patch.object(image_field, 'storage', storage),
                mock.patch.object(storage, 'save', wraps=storage.save) as storage_save,
            ):
                response = self.client.patch(
                    '/api/v1/auth/profile/',
                    {
                        'name': '바뀌면 안 되는 이름',
                        'manager_email': self.second_manager.email,
                        'profile_image': self._profile_image_upload(),
                    },
                    format='multipart',
                )

            stored_files = [
                path for path in Path(media_root).rglob('*') if path.is_file()
            ]

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()['code'], 'team_switch_confirmation_required')
        storage_save.assert_not_called()
        self.assertEqual(stored_files, [])
        self.agent.profile.refresh_from_db()
        self.assertFalse(self.agent.profile.profile_image)

    def test_first_profile_manager_link_keeps_existing_behavior(self):
        self.agent.profile.manager = None
        self.agent.profile.save(update_fields=['manager'])

        response = self.client.patch(
            '/api/v1/auth/profile/',
            {'manager_email': self.second_manager.email},
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.agent.profile.refresh_from_db()
        self.assertEqual(self.agent.profile.manager_id, self.second_manager.pk)

    def test_same_profile_manager_link_keeps_existing_behavior(self):
        response = self.client.patch(
            '/api/v1/auth/profile/',
            {'manager_email': self.first_manager.email},
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.agent.profile.refresh_from_db()
        self.assertEqual(self.agent.profile.manager_id, self.first_manager.pk)

    def test_profile_self_management_is_rejected_without_partial_changes(self):
        response = self.client.patch(
            '/api/v1/auth/profile/',
            {
                'name': '바뀌면 안 되는 이름',
                'manager_email': self.agent.email,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()['code'], 'self_management')
        self.agent.profile.refresh_from_db()
        self.assertEqual(self.agent.profile.name, '기존 이름')
        self.assertEqual(self.agent.profile.manager_id, self.first_manager.pk)

    def test_onboarding_switch_requires_confirmation_and_rolls_back_changes(self):
        response = self.client.post(
            '/api/v1/auth/onboarding/attest/',
            {
                'affiliation': '바뀌면 안 되는 소속',
                'manager_email': self.second_manager.email,
                'license_self_declared': True,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()['code'], 'team_switch_confirmation_required')
        self.agent.profile.refresh_from_db()
        self.assertEqual(self.agent.profile.affiliation, '기존 소속')
        self.assertFalse(self.agent.profile.license_self_declared)
        self.assertIsNone(self.agent.profile.onboarding_completed_at)
        self.assertEqual(self.agent.profile.manager_id, self.first_manager.pk)

    def test_confirmed_onboarding_switch_saves_changes(self):
        response = self.client.post(
            '/api/v1/auth/onboarding/attest/',
            {
                'affiliation': '변경된 소속',
                'manager_email': self.second_manager.email,
                'license_self_declared': True,
                'confirm_manager_switch': True,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.agent.profile.refresh_from_db()
        self.assertEqual(self.agent.profile.affiliation, '변경된 소속')
        self.assertTrue(self.agent.profile.license_self_declared)
        self.assertIsNotNone(self.agent.profile.onboarding_completed_at)
        self.assertEqual(self.agent.profile.manager_id, self.second_manager.pk)

    def test_confirmed_onboarding_switch_links_before_other_profile_writes(self):
        observed_profiles = []
        real_link_manager = account_views._link_manager

        def observe_then_link(profile, manager_email, **kwargs):
            current = Profile.objects.get(pk=profile.pk)
            observed_profiles.append({
                'affiliation': current.affiliation,
                'license_self_declared': current.license_self_declared,
                'onboarding_completed_at': current.onboarding_completed_at,
            })
            return real_link_manager(profile, manager_email, **kwargs)

        with mock.patch(
            'inpa.accounts.views._link_manager',
            side_effect=observe_then_link,
        ):
            response = self.client.post(
                '/api/v1/auth/onboarding/attest/',
                {
                    'affiliation': '연결 뒤 저장할 소속',
                    'manager_email': self.second_manager.email,
                    'license_self_declared': True,
                    'confirm_manager_switch': True,
                },
                format='json',
            )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(observed_profiles, [{
            'affiliation': '기존 소속',
            'license_self_declared': False,
            'onboarding_completed_at': None,
        }])
        self.agent.profile.refresh_from_db()
        self.assertEqual(self.agent.profile.affiliation, '연결 뒤 저장할 소속')
        self.assertTrue(self.agent.profile.license_self_declared)
        self.assertIsNotNone(self.agent.profile.onboarding_completed_at)
        self.assertEqual(self.agent.profile.manager_id, self.second_manager.pk)


class RegisterTeamTransactionTests(TestCase):
    def setUp(self):
        Plan.objects.create(code='free', display_name='Free', price_krw=0)
        self.manager = User.objects.create_user(
            email='rollback-manager@test.com', password='inpaPass123!'
        )
        self.manager.is_active = True
        self.manager.save(update_fields=['is_active'])
        Profile.objects.create(user=self.manager)
        self.payload = {
            'email': 'rollback-agent@test.com',
            'password': 'inpaPass123!',
            'password_confirm': 'inpaPass123!',
            'tos_agreed': True,
            'pp_agreed': True,
            'invite_token': make_invite_token(self.manager),
        }

    def test_link_error_rolls_back_user_profile_and_subscription(self):
        serializer = RegisterSerializer(data=self.payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)

        with mock.patch(
            'inpa.accounts.team.link_agent_to_manager',
            side_effect=OperationalError('lock failed'),
        ):
            with self.assertRaises(OperationalError):
                serializer.save()

        self.assertFalse(User.objects.filter(email=self.payload['email']).exists())
        self.assertFalse(Profile.objects.filter(user__email=self.payload['email']).exists())
        self.assertFalse(
            Subscription.objects.filter(user__email=self.payload['email']).exists()
        )


class ManagerPromotionMigrationTests(TestCase):
    def setUp(self):
        self.free_plan = Plan.objects.create(
            code='free', display_name='Free', price_krw=0
        )
        self.manager_plan = Plan.objects.create(
            code='manager', display_name='Manager', price_krw=19900
        )

    def _user(self, email, *, manager=None):
        user = User.objects.create_user(email=email, password='inpaPass123!')
        Profile.objects.create(user=user, manager=manager)
        return user

    def _manager_subscription(self, user, *, status, started_at, expires_at):
        Subscription.objects.filter(user=user).update(
            plan=self.manager_plan,
            status=status,
            expires_at=expires_at,
        )
        Subscription.objects.filter(user=user).update(started_at=started_at)

    def _run_backfill(self):
        migration = importlib.import_module(
            'inpa.accounts.migrations.0014_profile_manager_promotion'
        )
        migration.backfill_manager_promotion(django_apps, None)

    def test_team_earliest_joined_date_takes_priority_and_is_seen(self):
        manager = self._user('migration-team-manager@test.com')
        first_agent = self._user('migration-first-agent@test.com', manager=manager)
        second_agent = self._user('migration-second-agent@test.com', manager=manager)
        now = timezone.now()
        earliest_joined = now - timedelta(days=20)
        User.objects.filter(pk=first_agent.pk).update(date_joined=earliest_joined)
        User.objects.filter(pk=second_agent.pk).update(
            date_joined=now - timedelta(days=10)
        )
        self._manager_subscription(
            manager,
            status='active',
            started_at=now - timedelta(days=30),
            expires_at=None,
        )

        self._run_backfill()

        manager.profile.refresh_from_db()
        self.assertEqual(manager.profile.manager_promoted_at, earliest_joined)
        self.assertEqual(manager.profile.manager_promotion_seen_at, earliest_joined)

    def test_active_and_trial_manager_subscriptions_use_started_at_and_are_seen(self):
        active_manager = self._user('migration-active-manager@test.com')
        trial_manager = self._user('migration-trial-manager@test.com')
        now = timezone.now()
        active_started = now - timedelta(days=15)
        trial_started = now - timedelta(days=5)
        self._manager_subscription(
            active_manager,
            status='active',
            started_at=active_started,
            expires_at=None,
        )
        self._manager_subscription(
            trial_manager,
            status='trial',
            started_at=trial_started,
            expires_at=now + timedelta(days=5),
        )

        self._run_backfill()

        active_manager.profile.refresh_from_db()
        trial_manager.profile.refresh_from_db()
        self.assertEqual(active_manager.profile.manager_promoted_at, active_started)
        self.assertEqual(active_manager.profile.manager_promotion_seen_at, active_started)
        self.assertEqual(trial_manager.profile.manager_promoted_at, trial_started)
        self.assertEqual(trial_manager.profile.manager_promotion_seen_at, trial_started)

    def test_cancelled_and_expired_manager_subscriptions_are_excluded(self):
        cancelled_manager = self._user('migration-cancelled-manager@test.com')
        expired_manager = self._user('migration-expired-manager@test.com')
        now = timezone.now()
        self._manager_subscription(
            cancelled_manager,
            status='cancelled',
            started_at=now - timedelta(days=20),
            expires_at=now + timedelta(days=10),
        )
        self._manager_subscription(
            expired_manager,
            status='active',
            started_at=now - timedelta(days=20),
            expires_at=now - timedelta(seconds=1),
        )

        self._run_backfill()

        cancelled_manager.profile.refresh_from_db()
        expired_manager.profile.refresh_from_db()
        self.assertIsNone(cancelled_manager.profile.manager_promoted_at)
        self.assertIsNone(cancelled_manager.profile.manager_promotion_seen_at)
        self.assertIsNone(expired_manager.profile.manager_promoted_at)
        self.assertIsNone(expired_manager.profile.manager_promotion_seen_at)


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
