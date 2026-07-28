"""구글 연동 테스트 — 모든 구글 네트워크는 mock. 게이트·링크·보안 검증."""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.core.cache import cache
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from inpa.accounts.google import GoogleTokenError
from inpa.accounts.models import Profile, User
from inpa.booking.models import Meeting, MeetingSlot
from inpa.booking.tokens import make_booking_token
from inpa.customers.models import Customer
from inpa.notifications.models import ReminderRule


@override_settings(GOOGLE_OAUTH_ENABLED=True, GOOGLE_OAUTH_CLIENT_ID='cid')
class GoogleLoginTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch('inpa.accounts.views.verify_google_id_token')
    def test_new_user_created_onboarding_false(self, mock_verify):
        mock_verify.return_value = {'sub': 'g1', 'email': 'New@test.com',
                                    'email_verified': True, 'given_name': '홍길동'}
        r = self.client.post('/api/v1/auth/google/', {'id_token': 'x'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()['onboarding_completed'])
        u = User.objects.get(email='new@test.com')
        self.assertTrue(u.is_active)
        self.assertFalse(u.has_usable_password())  # 비번 미설정
        self.assertEqual(u.profile.google_sub, 'g1')
        self.assertTrue(ReminderRule.objects.filter(owner=u).exists())

    @patch('inpa.accounts.views.verify_google_id_token')
    def test_existing_email_links_and_password_still_works(self, mock_verify):
        user = User.objects.create_user(email='e@test.com', password='inpaPass123!')
        user.is_active = True
        user.save(update_fields=['is_active'])
        Profile.objects.create(user=user, email_verified_at=timezone.now())
        mock_verify.return_value = {'sub': 'g2', 'email': 'e@test.com', 'email_verified': True}
        r = self.client.post('/api/v1/auth/google/', {'id_token': 'x'}, format='json')
        self.assertEqual(r.status_code, 200)
        user.profile.refresh_from_db()
        self.assertEqual(user.profile.google_sub, 'g2')
        # 병행: 비번 로그인 여전히 동작
        r2 = self.client.post('/api/v1/auth/login/',
                              {'email': 'e@test.com', 'password': 'inpaPass123!'}, format='json')
        self.assertEqual(r2.status_code, 200)

    @patch('inpa.accounts.views.verify_google_id_token')
    def test_email_not_verified_401(self, mock_verify):
        mock_verify.side_effect = GoogleTokenError('email not verified')
        r = self.client.post('/api/v1/auth/google/', {'id_token': 'x'}, format='json')
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()['code'], 'GOOGLE_TOKEN_INVALID')

    @patch('inpa.accounts.views.verify_google_id_token')
    def test_sub_collision_409(self, mock_verify):
        b = User.objects.create_user(email='b@test.com', is_active=True)
        Profile.objects.create(user=b, google_sub='gY')
        mock_verify.return_value = {'sub': 'gZ', 'email': 'b@test.com', 'email_verified': True}
        r = self.client.post('/api/v1/auth/google/', {'id_token': 'x'}, format='json')
        self.assertEqual(r.status_code, 409)

    @override_settings(GOOGLE_OAUTH_ENABLED=False)
    def test_gate_off_404(self):
        r = self.client.post('/api/v1/auth/google/', {'id_token': 'x'}, format='json')
        self.assertEqual(r.status_code, 404)


@override_settings(GOOGLE_OAUTH_ENABLED=True, GOOGLE_OAUTH_CLIENT_ID='cid',
                   GOOGLE_OAUTH_CLIENT_SECRET='sec',
                   GOOGLE_OAUTH_REDIRECT_URI='https://be.test/api/v1/auth/google/calendar/callback/')
class GoogleCalendarTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(email='p@test.com', is_active=True)
        self.profile = Profile.objects.create(user=self.user, email_verified_at=timezone.now())
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.public = APIClient()

    @patch('inpa.accounts.google_calendar.build_auth_url')
    def test_connect_returns_auth_url(self, mock_url):
        mock_url.return_value = 'https://accounts.google.com/o/oauth2/auth?x=1'
        r = self.client.get('/api/v1/auth/google/calendar/connect/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('auth_url', r.json())

    @override_settings(GOOGLE_OAUTH_ENABLED=False)
    def test_connect_gate_off_403(self):
        r = self.client.get('/api/v1/auth/google/calendar/connect/')
        self.assertEqual(r.status_code, 403)

    @patch('inpa.accounts.google_calendar.exchange_code')
    def test_callback_happy_stores_refresh(self, mock_ex):
        mock_ex.return_value = 'refresh-xyz'
        from inpa.accounts.google_calendar import make_calendar_state
        state = make_calendar_state(self.user.pk)
        r = self.public.get(f'/api/v1/auth/google/calendar/callback/?code=abc&state={state}')
        self.assertEqual(r.status_code, 302)
        self.assertIn('gcal=connected', r['Location'])
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.google_calendar_refresh_token, 'refresh-xyz')

    def test_callback_bad_state_redirects_error(self):
        r = self.public.get('/api/v1/auth/google/calendar/callback/?code=abc&state=bad')
        self.assertEqual(r.status_code, 302)
        self.assertIn('gcal=error', r['Location'])

    def test_profile_never_exposes_refresh_token(self):
        self.profile.google_calendar_refresh_token = 'secret-rt-123'
        self.profile.save(update_fields=['google_calendar_refresh_token'])
        r = self.client.get('/api/v1/auth/profile/')
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('secret-rt-123', r.content.decode())
        self.assertTrue(r.json()['google_calendar_connected'])

    @patch('inpa.accounts.google_calendar.insert_meeting_event')
    def test_meeting_event_inserted_on_accept(self, mock_insert):
        # 구글 이벤트는 '수락'(대기→확정) 시점에 등록된다(공개 신청 시점이 아님).
        mock_insert.return_value = 'evt-1'
        self.profile.google_calendar_refresh_token = 'rt'
        self.profile.save(update_fields=['google_calendar_refresh_token'])
        cust = Customer.objects.create(owner=self.user, name='홍길동')
        meeting = Meeting.objects.create(
            owner=self.user, customer=cust, start_at=timezone.now() + timedelta(days=1),
            method='phone', status=Meeting.STATUS_PENDING)
        r = self.client.post(f'/api/v1/meetings/{meeting.id}/accept/')
        self.assertEqual(r.status_code, 200)
        meeting.refresh_from_db()
        self.assertEqual(meeting.status, Meeting.STATUS_CONFIRMED)
        self.assertEqual(meeting.google_event_id, 'evt-1')
        mock_insert.assert_called_once()

    @patch('inpa.accounts.google_calendar.insert_meeting_event', side_effect=Exception('google down'))
    def test_meeting_accept_survives_calendar_failure(self, mock_insert):
        self.profile.google_calendar_refresh_token = 'rt'
        self.profile.save(update_fields=['google_calendar_refresh_token'])
        cust = Customer.objects.create(owner=self.user, name='김철수')
        meeting = Meeting.objects.create(
            owner=self.user, customer=cust, start_at=timezone.now() + timedelta(days=2),
            method='phone', status=Meeting.STATUS_PENDING)
        r = self.client.post(f'/api/v1/meetings/{meeting.id}/accept/')
        self.assertEqual(r.status_code, 200)  # 캘린더 실패해도 수락(확정)은 성공
        meeting.refresh_from_db()
        self.assertEqual(meeting.status, Meeting.STATUS_CONFIRMED)
        self.assertIsNone(meeting.google_event_id)


@override_settings(
    SHOWCASE_ACCOUNT_EMAIL='showcase@inpa.example',
    GOOGLE_OAUTH_ENABLED=True,
    GOOGLE_OAUTH_CLIENT_ID='cid',
    GOOGLE_OAUTH_CLIENT_SECRET='sec',
    GOOGLE_OAUTH_REDIRECT_URI=(
        'https://be.test/api/v1/auth/google/calendar/callback/'
    ),
)
class ShowcaseGoogleActionTests(TestCase):
    """검증된 시연 계정은 Google 연결·토큰 갱신 전에 멈춘다."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email='showcase@inpa.example',
            password='showcaseTestPass123!',
            is_active=True,
        )
        self.profile = Profile.objects.create(
            user=self.user,
            email_verified_at=timezone.now(),
            is_showcase=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.public = APIClient()

    def assert_showcase_restricted(self, response):
        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(response.json()['code'], 'SHOWCASE_ACTION_RESTRICTED')

    @patch('inpa.accounts.views.verify_google_id_token')
    def test_google_login_stops_after_verified_email_before_link_or_token(
            self, verify):
        verify.return_value = {
            'sub': 'showcase-google-sub',
            'email': self.user.email,
            'email_verified': True,
        }

        response = self.public.post(
            '/api/v1/auth/google/',
            {'id_token': 'verified-google-token'},
            format='json',
        )

        self.assert_showcase_restricted(response)
        verify.assert_called_once_with('verified-google-token')
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.google_sub)
        self.assertFalse(Token.objects.filter(user=self.user).exists())

    @patch('inpa.accounts.views.verify_google_id_token')
    def test_verified_showcase_email_blocks_even_if_sub_points_elsewhere(
            self, verify):
        ordinary = User.objects.create_user(
            email='linked-ordinary@test.com',
            is_active=True,
        )
        Profile.objects.create(
            user=ordinary,
            email_verified_at=timezone.now(),
            google_sub='shared-google-sub',
        )
        verify.return_value = {
            'sub': 'shared-google-sub',
            'email': self.user.email,
            'email_verified': True,
        }

        response = self.public.post(
            '/api/v1/auth/google/',
            {'id_token': 'verified-google-token'},
            format='json',
        )

        self.assert_showcase_restricted(response)
        self.assertFalse(Token.objects.filter(user=ordinary).exists())

    @patch('inpa.accounts.views.verify_google_id_token')
    def test_ordinary_google_login_still_links_once(self, verify):
        ordinary = User.objects.create_user(
            email='ordinary-google@test.com',
            password='ordinaryTestPass123!',
            is_active=True,
        )
        profile = Profile.objects.create(
            user=ordinary,
            email_verified_at=timezone.now(),
        )
        verify.return_value = {
            'sub': 'ordinary-google-sub',
            'email': ordinary.email,
            'email_verified': True,
        }

        response = self.public.post(
            '/api/v1/auth/google/',
            {'id_token': 'ordinary-google-token'},
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.content)
        verify.assert_called_once_with('ordinary-google-token')
        profile.refresh_from_db()
        self.assertEqual(profile.google_sub, 'ordinary-google-sub')

    @patch('inpa.accounts.google_calendar.build_auth_url')
    def test_calendar_connect_blocks_before_auth_url_creation(self, build_url):
        build_url.return_value = (
            'https://accounts.google.com/o/oauth2/auth?showcase=1'
        )
        response = self.client.get(
            '/api/v1/auth/google/calendar/connect/',
        )

        self.assert_showcase_restricted(response)
        build_url.assert_not_called()

    @patch('inpa.accounts.google_calendar.build_auth_url')
    def test_ordinary_calendar_connect_still_builds_url_once(self, build_url):
        ordinary = User.objects.create_user(
            email='ordinary-calendar@test.com',
            is_active=True,
        )
        Profile.objects.create(
            user=ordinary,
            email_verified_at=timezone.now(),
        )
        client = APIClient()
        client.force_authenticate(user=ordinary)
        build_url.return_value = (
            'https://accounts.google.com/o/oauth2/auth?ordinary=1'
        )

        response = client.get('/api/v1/auth/google/calendar/connect/')

        self.assertEqual(response.status_code, 200, response.content)
        build_url.assert_called_once_with(ordinary.pk)

    @patch('inpa.accounts.google_calendar.exchange_code')
    def test_calendar_callback_blocks_before_code_exchange(self, exchange):
        from inpa.accounts.google_calendar import make_calendar_state

        state = make_calendar_state(self.user.pk)
        response = self.public.get(
            '/api/v1/auth/google/calendar/callback/',
            {'code': 'authorization-code', 'state': state},
        )

        self.assert_showcase_restricted(response)
        exchange.assert_not_called()
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.google_calendar_refresh_token)

    @patch('inpa.accounts.google_calendar.exchange_code')
    def test_ordinary_calendar_callback_still_exchanges_once(self, exchange):
        from inpa.accounts.google_calendar import make_calendar_state

        ordinary = User.objects.create_user(
            email='ordinary-callback@test.com',
            is_active=True,
        )
        profile = Profile.objects.create(
            user=ordinary,
            email_verified_at=timezone.now(),
        )
        exchange.return_value = 'ordinary-refresh-token'
        state = make_calendar_state(ordinary.pk)

        response = self.public.get(
            '/api/v1/auth/google/calendar/callback/',
            {'code': 'authorization-code', 'state': state},
        )

        self.assertEqual(response.status_code, 302)
        exchange.assert_called_once_with('authorization-code')
        profile.refresh_from_db()
        self.assertEqual(
            profile.google_calendar_refresh_token,
            'ordinary-refresh-token',
        )

    @patch('inpa.accounts.google_calendar.revoke_refresh_token')
    def test_calendar_disconnect_blocks_before_token_revoke(self, revoke):
        self.profile.google_calendar_refresh_token = 'showcase-refresh-token'
        self.profile.save(update_fields=['google_calendar_refresh_token'])

        response = self.client.post(
            '/api/v1/auth/google/calendar/disconnect/',
        )

        self.assert_showcase_restricted(response)
        revoke.assert_not_called()
        self.profile.refresh_from_db()
        self.assertEqual(
            self.profile.google_calendar_refresh_token,
            'showcase-refresh-token',
        )

    @patch('inpa.accounts.google_calendar.revoke_refresh_token')
    def test_ordinary_calendar_disconnect_still_revokes_once(self, revoke):
        ordinary = User.objects.create_user(
            email='ordinary-disconnect@test.com',
            is_active=True,
        )
        profile = Profile.objects.create(
            user=ordinary,
            email_verified_at=timezone.now(),
            google_calendar_refresh_token='ordinary-refresh-token',
        )
        client = APIClient()
        client.force_authenticate(user=ordinary)

        response = client.post(
            '/api/v1/auth/google/calendar/disconnect/',
        )

        self.assertEqual(response.status_code, 200, response.content)
        revoke.assert_called_once_with('ordinary-refresh-token')
        profile.refresh_from_db()
        self.assertIsNone(profile.google_calendar_refresh_token)
