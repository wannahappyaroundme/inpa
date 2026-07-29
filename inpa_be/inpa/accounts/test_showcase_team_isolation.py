"""Showcase accounts never participate in public team relationships."""
from django.core import signing
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from inpa.billing.models import Plan
from inpa.core.internal_accounts import ShowcaseActionRestricted
from inpa.notifications.models import Notification

from .invite import (
    TEAM_INVITE_SALT,
    make_invite_token,
    resolve_invite_manager,
)
from .models import Profile, User
from .team import link_agent_to_manager


SHOWCASE_EMAIL = 'showcase-team-guard@inpa.invalid'


@override_settings(SHOWCASE_ACCOUNT_EMAIL=SHOWCASE_EMAIL)
class ShowcaseTeamServiceIsolationTests(TestCase):
    def setUp(self):
        Plan.objects.create(code='free', display_name='Free', price_krw=0)
        self.showcase = self._user(SHOWCASE_EMAIL, is_showcase=True)
        self.manager = self._user('real-manager@inpa.invalid')
        self.agent = self._user('real-agent@inpa.invalid')

    def _user(self, email, *, is_showcase=False):
        user = User.objects.create_user(email=email)
        user.is_active = True
        user.save(update_fields=['is_active'])
        Profile.objects.create(user=user, is_showcase=is_showcase)
        return user

    def _state(self):
        return {
            'profiles': list(
                Profile.objects.order_by('user_id').values(
                    'user_id',
                    'manager_id',
                    'manager_promoted_at',
                    'manager_promotion_seen_at',
                )
            ),
            'notifications': list(Notification.objects.order_by('pk').values()),
        }

    def test_team_service_rejects_showcase_agent_without_mutating_real_manager(self):
        before = self._state()

        with self.assertRaises(ShowcaseActionRestricted):
            link_agent_to_manager(agent=self.showcase, manager=self.manager)

        self.assertEqual(self._state(), before)

    def test_team_service_rejects_showcase_manager_without_mutating_real_agent(self):
        before = self._state()

        with self.assertRaises(ShowcaseActionRestricted):
            link_agent_to_manager(agent=self.agent, manager=self.showcase)

        self.assertEqual(self._state(), before)

    def test_showcase_manager_cannot_issue_an_invite_token(self):
        with self.assertRaises(ShowcaseActionRestricted):
            make_invite_token(self.showcase)

    def test_preexisting_showcase_invite_token_no_longer_resolves(self):
        legacy_token = signing.dumps(self.showcase.pk, salt=TEAM_INVITE_SALT)

        self.assertIsNone(resolve_invite_manager(legacy_token))


@override_settings(SHOWCASE_ACCOUNT_EMAIL=SHOWCASE_EMAIL)
class ShowcaseTeamApiIsolationTests(TestCase):
    def setUp(self):
        Plan.objects.create(code='free', display_name='Free', price_krw=0)
        self.showcase = self._user(
            SHOWCASE_EMAIL,
            is_showcase=True,
            name='시연 설계사',
            affiliation='시연 지점',
        )
        self.manager = self._user(
            'real-manager-api@inpa.invalid',
            name='운영 관리자',
            affiliation='운영 지점',
        )
        self.agent = self._user(
            'real-agent-api@inpa.invalid',
            name='운영 설계사',
            affiliation='운영 지점',
        )
        self.client = APIClient()

    def _user(self, email, *, is_showcase=False, name='', affiliation=''):
        user = User.objects.create_user(email=email)
        user.is_active = True
        user.save(update_fields=['is_active'])
        Profile.objects.create(
            user=user,
            is_showcase=is_showcase,
            name=name,
            affiliation=affiliation,
        )
        return user

    def _state(self):
        return {
            'profiles': list(
                Profile.objects.order_by('user_id').values(
                    'user_id',
                    'name',
                    'affiliation',
                    'manager_id',
                    'manager_promoted_at',
                    'manager_promotion_seen_at',
                    'license_self_declared',
                    'onboarding_completed_at',
                )
            ),
            'notifications': list(Notification.objects.order_by('pk').values()),
        }

    def _assert_request_is_blocked_without_mutation(
        self,
        *,
        actor,
        method,
        path,
        payload,
    ):
        self.client.force_authenticate(user=actor)
        before = self._state()

        with self.captureOnCommitCallbacks(execute=True):
            response = getattr(self.client, method)(path, payload, format='json')

        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(response.json()['code'], 'SHOWCASE_ACTION_RESTRICTED')
        self.assertEqual(self._state(), before)

    def test_showcase_profile_patch_cannot_link_to_real_manager(self):
        self._assert_request_is_blocked_without_mutation(
            actor=self.showcase,
            method='patch',
            path='/api/v1/auth/profile/',
            payload={
                'name': '저장되면 안 되는 이름',
                'manager_email': self.manager.email,
            },
        )

    def test_real_profile_patch_cannot_link_to_showcase_manager(self):
        self._assert_request_is_blocked_without_mutation(
            actor=self.agent,
            method='patch',
            path='/api/v1/auth/profile/',
            payload={
                'name': '저장되면 안 되는 이름',
                'manager_email': self.showcase.email,
            },
        )

    def test_showcase_onboarding_cannot_link_to_real_manager(self):
        self._assert_request_is_blocked_without_mutation(
            actor=self.showcase,
            method='post',
            path='/api/v1/auth/onboarding/attest/',
            payload={
                'affiliation': '저장되면 안 되는 소속',
                'manager_email': self.manager.email,
                'license_self_declared': True,
            },
        )

    def test_real_onboarding_cannot_link_to_showcase_manager(self):
        self._assert_request_is_blocked_without_mutation(
            actor=self.agent,
            method='post',
            path='/api/v1/auth/onboarding/attest/',
            payload={
                'affiliation': '저장되면 안 되는 소속',
                'manager_email': self.showcase.email,
                'license_self_declared': True,
            },
        )

    def test_showcase_invite_endpoint_returns_no_public_url(self):
        self.client.force_authenticate(user=self.showcase)
        before = self._state()

        response = self.client.post('/api/v1/manager/invite-link/')

        self.assertEqual(response.status_code, 403, response.content)
        self.assertNotIn('url', response.json())
        self.assertEqual(response.json()['code'], 'SHOWCASE_ACTION_RESTRICTED')
        self.assertEqual(self._state(), before)

    def test_preexisting_showcase_invite_is_hidden_from_public_info(self):
        legacy_token = signing.dumps(self.showcase.pk, salt=TEAM_INVITE_SALT)
        self.client.force_authenticate(user=None)

        response = self.client.get(
            '/api/v1/manager/invite-info/',
            {'token': legacy_token},
        )

        self.assertEqual(response.status_code, 404, response.content)
        self.assertEqual(response.json()['code'], 'INVITE_INVALID')
