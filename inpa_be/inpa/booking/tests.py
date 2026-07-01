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

from .models import Meeting, MeetingSlot, WorkHour
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


def _all_week_workhours(owner):
    """월~일 09:00~18:00 업무시간 — 향후 14일 내 빈 슬롯이 항상 생기게."""
    from datetime import time
    for wd in range(7):
        WorkHour.objects.create(owner=owner, weekday=wd,
                                start_time=time(9, 0), end_time=time(18, 0))


def _first_slot(client, token):
    body = client.get(f'/api/v1/b/{token}/').json()
    slots = body.get('slots') or []
    return slots[0]['start_at'] if slots else None


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

    # ── 공개 GET (업무시간 기준 빈 슬롯 자동 생성) ──
    def test_public_get_masked_and_workhour_slots(self):
        _all_week_workhours(self.user_a)
        token = make_booking_token(self.customer)
        r = self.public.get(f'/api/v1/b/{token}/')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body['customer']['name_masked'], '홍**')
        self.assertNotIn('010-0000-0000', r.content.decode())  # PII 미노출
        self.assertTrue(len(body['slots']) > 0)  # 업무시간 안의 빈 시간 자동 노출
        self.assertIn('start_at', body['slots'][0])

    def test_public_get_no_workhours_empty(self):
        # 업무시간 미설정이면 빈 슬롯(설계사가 아직 설정 전)
        token = make_booking_token(self.customer)
        body = self.public.get(f'/api/v1/b/{token}/').json()
        self.assertEqual(body['slots'], [])

    def test_public_get_expired_410(self):
        token = make_booking_token(self.customer)
        with override_settings(BOOKING_TOKEN_TTL_HOURS=0):
            r = self.public.get(f'/api/v1/b/{token}/')
        self.assertEqual(r.status_code, 410)

    def test_public_get_invalid_404(self):
        r = self.public.get('/api/v1/b/bad-token/')
        self.assertEqual(r.status_code, 404)

    # ── 공개 POST(예약 신청 → 대기) ──
    def test_public_post_requests_pending_and_notifies(self):
        _all_week_workhours(self.user_a)
        token = make_booking_token(self.customer)
        start_at = _first_slot(self.public, token)
        r = self.public.post(f'/api/v1/b/{token}/',
                             {'start_at': start_at, 'method': 'in_person', 'note': '상담 희망'},
                             format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()['status'], Meeting.STATUS_PENDING)
        meeting = Meeting.objects.get(customer=self.customer)
        self.assertEqual(meeting.status, Meeting.STATUS_PENDING)
        notif = Notification.objects.filter(
            owner=self.user_a, notif_type=NotifType.MEETING_BOOKED).first()
        self.assertIsNotNone(notif)
        self.assertEqual(notif.meeting_id, meeting.id)  # 알림에 미팅 연결(수락/거절용)

    def test_public_post_method_invalid(self):
        _all_week_workhours(self.user_a)
        token = make_booking_token(self.customer)
        start_at = _first_slot(self.public, token)
        r = self.public.post(f'/api/v1/b/{token}/',
                             {'start_at': start_at, 'method': 'telepathy'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_public_post_double_booking_409(self):
        _all_week_workhours(self.user_a)
        token = make_booking_token(self.customer)
        start_at = _first_slot(self.public, token)
        r1 = self.public.post(f'/api/v1/b/{token}/',
                              {'start_at': start_at, 'method': 'phone'}, format='json')
        r2 = self.public.post(f'/api/v1/b/{token}/',
                              {'start_at': start_at, 'method': 'phone'}, format='json')
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 409)
        self.assertEqual(
            Meeting.objects.filter(customer=self.customer,
                                   status=Meeting.STATUS_PENDING).count(), 1)

    # ── 수락/거절 + 버퍼 + 업무시간 격리 ──
    def test_accept_confirms(self):
        _all_week_workhours(self.user_a)
        token = make_booking_token(self.customer)
        start_at = _first_slot(self.public, token)
        self.public.post(f'/api/v1/b/{token}/',
                         {'start_at': start_at, 'method': 'phone'}, format='json')
        meeting = Meeting.objects.get(customer=self.customer)
        r = self.client_a.post(f'/api/v1/meetings/{meeting.id}/accept/')
        self.assertEqual(r.status_code, 200)
        meeting.refresh_from_db()
        self.assertEqual(meeting.status, Meeting.STATUS_CONFIRMED)

    def test_accept_promotes_customer_to_fa(self):
        # 수락 = 만나기로 확정 → db/contact 고객이 FA(meeting)로 자동 승급 + fa_reached_at 스탬프.
        _all_week_workhours(self.user_a)
        self.customer.sales_stage = Customer.STAGE_CONTACT
        self.customer.save(update_fields=['sales_stage'])
        token = make_booking_token(self.customer)
        start_at = _first_slot(self.public, token)
        self.public.post(f'/api/v1/b/{token}/',
                         {'start_at': start_at, 'method': 'phone'}, format='json')
        meeting = Meeting.objects.get(customer=self.customer)
        self.client_a.post(f'/api/v1/meetings/{meeting.id}/accept/')
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.sales_stage, Customer.STAGE_MEETING)
        self.assertIsNotNone(self.customer.fa_reached_at)

    def test_accept_does_not_demote_contract(self):
        # 이미 청약(contract) 단계면 수락해도 끌어내리지 않는다(승급은 db/contact만).
        _all_week_workhours(self.user_a)
        self.customer.sales_stage = Customer.STAGE_CONTRACT
        self.customer.save(update_fields=['sales_stage'])
        token = make_booking_token(self.customer)
        start_at = _first_slot(self.public, token)
        self.public.post(f'/api/v1/b/{token}/',
                         {'start_at': start_at, 'method': 'phone'}, format='json')
        meeting = Meeting.objects.get(customer=self.customer)
        self.client_a.post(f'/api/v1/meetings/{meeting.id}/accept/')
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.sales_stage, Customer.STAGE_CONTRACT)

    def test_decline_frees_time(self):
        _all_week_workhours(self.user_a)
        token = make_booking_token(self.customer)
        start_at = _first_slot(self.public, token)
        self.public.post(f'/api/v1/b/{token}/',
                         {'start_at': start_at, 'method': 'phone'}, format='json')
        meeting = Meeting.objects.get(customer=self.customer)
        r = self.client_a.post(f'/api/v1/meetings/{meeting.id}/decline/')
        self.assertEqual(r.status_code, 200)
        meeting.refresh_from_db()
        self.assertEqual(meeting.status, Meeting.STATUS_DECLINED)
        cache.clear()
        slots = [s['start_at'] for s in self.public.get(f'/api/v1/b/{token}/').json()['slots']]
        self.assertIn(start_at, slots)  # 거절되면 그 시간이 다시 비워진다

    def test_buffer_blocks_adjacent(self):
        _all_week_workhours(self.user_a)
        token = make_booking_token(self.customer)
        start_at = _first_slot(self.public, token)
        self.public.post(f'/api/v1/b/{token}/',
                         {'start_at': start_at, 'method': 'phone'}, format='json')
        cache.clear()
        slots = [s['start_at'] for s in self.public.get(f'/api/v1/b/{token}/').json()['slots']]
        self.assertNotIn(start_at, slots)  # 신청된 시간 제외(점유)
        booked = timezone.datetime.fromisoformat(start_at)
        near = (booked + timedelta(minutes=30)).isoformat()
        self.assertNotIn(near, slots)  # 앞뒤 60분 버퍼 안(30분 뒤)도 제외

    def test_workhour_owner_isolation(self):
        from datetime import time
        wh = WorkHour.objects.create(owner=self.user_a, weekday=0,
                                     start_time=time(9, 0), end_time=time(10, 0))
        r = self.client_b.get('/api/v1/work-hours/')
        ids = [w['id'] for w in r.json()['results']] if isinstance(r.json(), dict) else []
        self.assertNotIn(wh.id, ids)

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

    def test_booking_request_403(self):
        r = self.client.post(f'/api/v1/customers/{self.customer.id}/booking-requests/')
        self.assertEqual(r.status_code, 403)

    def test_public_get_404(self):
        token = make_booking_token(self.customer)
        self.assertEqual(self.public.get(f'/api/v1/b/{token}/').status_code, 404)
