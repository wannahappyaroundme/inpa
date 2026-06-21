"""구글 연동 테스트 — 모든 구글 네트워크는 mock. 게이트·링크·보안 검증."""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.core.cache import cache
from django.utils import timezone
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
    def test_meeting_confirm_inserts_event_when_connected(self, mock_insert):
        mock_insert.return_value = 'evt-1'
        self.profile.google_calendar_refresh_token = 'rt'
        self.profile.save(update_fields=['google_calendar_refresh_token'])
        cust = Customer.objects.create(owner=self.user, name='홍길동')
        slot = MeetingSlot.objects.create(owner=self.user, start_at=timezone.now() + timedelta(days=1))
        token = make_booking_token(cust)
        r = self.public.post(f'/api/v1/b/{token}/', {'slot_id': slot.id, 'method': 'phone'}, format='json')
        self.assertEqual(r.status_code, 201)
        meeting = Meeting.objects.get(slot=slot)
        self.assertEqual(meeting.google_event_id, 'evt-1')
        mock_insert.assert_called_once()

    @patch('inpa.accounts.google_calendar.insert_meeting_event', side_effect=Exception('google down'))
    def test_meeting_confirm_survives_calendar_failure(self, mock_insert):
        self.profile.google_calendar_refresh_token = 'rt'
        self.profile.save(update_fields=['google_calendar_refresh_token'])
        cust = Customer.objects.create(owner=self.user, name='김철수')
        slot = MeetingSlot.objects.create(owner=self.user, start_at=timezone.now() + timedelta(days=2))
        token = make_booking_token(cust)
        r = self.public.post(f'/api/v1/b/{token}/', {'slot_id': slot.id, 'method': 'phone'}, format='json')
        self.assertEqual(r.status_code, 201)  # 캘린더 실패해도 예약 확정
        self.assertIsNone(Meeting.objects.get(slot=slot).google_event_id)
