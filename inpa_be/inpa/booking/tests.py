"""미팅 예약 핵심 테스트 — owner 격리 · 토큰 · 공개 예약 · 중복예약 · 플래그 게이트."""
from datetime import timedelta

from django.core import signing
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User
from inpa.customers.models import Customer
from inpa.notifications.models import NotifType, Notification

from .models import Meeting, MeetingSlot
from .tokens import make_booking_token, read_booking_token


def _make_planner(email):
    user = User.objects.create_user(email=email, password='inpaPass123!')
    user.is_active = True
    user.save(update_fields=['is_active'])
    profile = Profile.objects.create(user=user, email_verified_at=timezone.now())
    client = APIClient()
    client.force_authenticate(user=user)
    return user, client, profile


def _future(hours=24):
    return timezone.now() + timedelta(hours=hours)


@override_settings(BOOKING_ENABLED=True)
class BookingCoreTests(TestCase):
    def setUp(self):
        cache.clear()  # ScopedRateThrottle(booking_public) 초기화
        self.user_a, self.client_a, self.profile_a = _make_planner('agent_a@test.com')
        self.user_b, self.client_b, self.profile_b = _make_planner('agent_b@test.com')
        self.profile_a.affiliation = 'A생명'
        self.profile_a.booking_location = '강남역 스타벅스'
        self.profile_a.save(update_fields=['affiliation', 'booking_location'])
        self.customer = Customer.objects.create(
            owner=self.user_a, name='홍길동', mobile_phone_number='010-0000-0000')
        self.public = APIClient()

    # ── 토큰 ──
    def test_token_roundtrip(self):
        token = make_booking_token(self.customer)
        self.assertEqual(read_booking_token(token), self.customer.id)

    def test_token_expired(self):
        token = make_booking_token(self.customer)
        with override_settings(BOOKING_TOKEN_TTL_HOURS=0):
            with self.assertRaises(signing.SignatureExpired):
                read_booking_token(token)

    def test_token_tampered(self):
        with self.assertRaises(signing.BadSignature):
            read_booking_token('nope.bad.token')

    # ── 슬롯 CRUD + owner 격리 ──
    def test_slot_create_owner_injected(self):
        r = self.client_a.post('/api/v1/meeting-slots/',
                               {'start_at': _future().isoformat()}, format='json')
        self.assertEqual(r.status_code, 201)
        slot = MeetingSlot.objects.get(id=r.json()['id'])
        self.assertEqual(slot.owner_id, self.user_a.id)
        self.assertEqual(slot.duration_min, 30)  # profile 기본값

    def test_slot_past_rejected(self):
        r = self.client_a.post('/api/v1/meeting-slots/',
                               {'start_at': (timezone.now() - timedelta(hours=1)).isoformat()},
                               format='json')
        self.assertEqual(r.status_code, 400)

    def test_slot_owner_isolation(self):
        slot = MeetingSlot.objects.create(owner=self.user_a, start_at=_future())
        r = self.client_b.get('/api/v1/meeting-slots/')
        ids = [s['id'] for s in r.json()['results']] if isinstance(r.json(), dict) else []
        self.assertNotIn(slot.id, ids)

    # ── 예약 링크 생성(설계사) ──
    def test_booking_request_owner_ok(self):
        r = self.client_a.post(f'/api/v1/customers/{self.customer.id}/booking-requests/')
        self.assertEqual(r.status_code, 201)
        body = r.json()
        self.assertIn('/b/', body['booking_url'])
        self.assertEqual(read_booking_token(body['token']), self.customer.id)
        # 메시지 렌더: 고객명 포함, 플레이스홀더 치환 완료
        self.assertIn('홍길동', body['message'])
        self.assertNotIn('{링크}', body['message'])

    def test_booking_request_owner_isolation(self):
        r = self.client_b.post(f'/api/v1/customers/{self.customer.id}/booking-requests/')
        self.assertEqual(r.status_code, 404)

    # ── 공개 GET ──
    def test_public_get_masked_and_open_future_only(self):
        open_slot = MeetingSlot.objects.create(owner=self.user_a, start_at=_future(24))
        MeetingSlot.objects.create(owner=self.user_a, start_at=_future(48),
                                   status=MeetingSlot.STATUS_BOOKED)  # booked 제외
        MeetingSlot.objects.create(owner=self.user_b, start_at=_future(24))  # 타 owner 제외
        token = make_booking_token(self.customer)
        r = self.public.get(f'/api/v1/b/{token}/')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body['customer']['name_masked'], '홍**')
        self.assertNotIn('010-0000-0000', r.content.decode())  # PII 미노출
        slot_ids = [s['id'] for s in body['slots']]
        self.assertEqual(slot_ids, [open_slot.id])  # 열린 미래 슬롯만

    def test_public_get_expired_410(self):
        token = make_booking_token(self.customer)
        with override_settings(BOOKING_TOKEN_TTL_HOURS=0):
            r = self.public.get(f'/api/v1/b/{token}/')
        self.assertEqual(r.status_code, 410)

    def test_public_get_invalid_404(self):
        r = self.public.get('/api/v1/b/bad-token/')
        self.assertEqual(r.status_code, 404)

    # ── 공개 POST(예약 확정) ──
    def test_public_post_books_and_notifies(self):
        slot = MeetingSlot.objects.create(owner=self.user_a, start_at=_future())
        token = make_booking_token(self.customer)
        r = self.public.post(f'/api/v1/b/{token}/',
                             {'slot_id': slot.id, 'method': 'in_person', 'note': '상담 희망'},
                             format='json')
        self.assertEqual(r.status_code, 201)
        slot.refresh_from_db()
        self.assertEqual(slot.status, MeetingSlot.STATUS_BOOKED)
        meeting = Meeting.objects.get(slot=slot)
        self.assertEqual(meeting.customer_id, self.customer.id)
        self.assertEqual(meeting.location_detail, '강남역 스타벅스')  # 대면 location 스냅샷
        self.assertTrue(Notification.objects.filter(
            owner=self.user_a, notif_type=NotifType.MEETING_BOOKED).exists())

    def test_public_post_method_invalid(self):
        slot = MeetingSlot.objects.create(owner=self.user_a, start_at=_future())
        token = make_booking_token(self.customer)
        r = self.public.post(f'/api/v1/b/{token}/',
                             {'slot_id': slot.id, 'method': 'telepathy'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_public_post_double_booking_409(self):
        slot = MeetingSlot.objects.create(owner=self.user_a, start_at=_future())
        token = make_booking_token(self.customer)
        r1 = self.public.post(f'/api/v1/b/{token}/',
                              {'slot_id': slot.id, 'method': 'phone'}, format='json')
        r2 = self.public.post(f'/api/v1/b/{token}/',
                              {'slot_id': slot.id, 'method': 'phone'}, format='json')
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 409)
        self.assertEqual(Meeting.objects.filter(slot=slot).count(), 1)

    # ── 미팅 취소(슬롯 재오픈 X) ──
    def test_cancel_keeps_slot_booked(self):
        slot = MeetingSlot.objects.create(owner=self.user_a, start_at=_future(),
                                          status=MeetingSlot.STATUS_BOOKED)
        meeting = Meeting.objects.create(owner=self.user_a, customer=self.customer, slot=slot,
                                         start_at=slot.start_at, method='phone')
        r = self.client_a.post(f'/api/v1/meetings/{meeting.id}/cancel/')
        self.assertEqual(r.status_code, 200)
        meeting.refresh_from_db(); slot.refresh_from_db()
        self.assertEqual(meeting.status, Meeting.STATUS_CANCELED)
        self.assertEqual(slot.status, MeetingSlot.STATUS_BOOKED)  # 재오픈 안 함


@override_settings(BOOKING_ENABLED=False)
class BookingDisabledGateTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user, self.client, _ = _make_planner('agent@test.com')
        self.customer = Customer.objects.create(owner=self.user, name='홍길동')
        self.public = APIClient()

    def test_authed_slots_403(self):
        self.assertEqual(self.client.get('/api/v1/meeting-slots/').status_code, 403)

    def test_booking_request_403(self):
        r = self.client.post(f'/api/v1/customers/{self.customer.id}/booking-requests/')
        self.assertEqual(r.status_code, 403)

    def test_public_get_404(self):
        token = make_booking_token(self.customer)
        self.assertEqual(self.public.get(f'/api/v1/b/{token}/').status_code, 404)
