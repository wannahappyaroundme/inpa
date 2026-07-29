"""미팅 예약 핵심 테스트 — owner 격리 · 토큰 · 공개 예약 · 중복예약 · 플래그 게이트."""
from datetime import timedelta
from unittest import mock

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

    @override_settings(FRONTEND_BASE_URL='https://www.inpa.kr')
    def test_booking_request_default_message_contains_real_identity_and_full_url(self):
        self.profile_a.name = '황예진'
        self.profile_a.title = '팀장'
        self.profile_a.booking_msg_template = ''
        self.profile_a.save(update_fields=['name', 'title', 'booking_msg_template'])

        response = self.client_a.post(
            f'/api/v1/customers/{self.customer.id}/booking-requests/')
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertIn('홍길동 고객님', body['message'])
        self.assertIn('A생명 팀장 황예진 보험설계사입니다.', body['message'])
        self.assertTrue(body['booking_url'].startswith('https://www.inpa.kr/b/'))
        self.assertIn(body['booking_url'], body['message'])

    def test_booking_request_default_message_uses_fallback_name_without_affiliation_duplication(self):
        self.profile_a.name = ''
        self.profile_a.affiliation = 'A생명'
        self.profile_a.title = ''
        self.profile_a.booking_msg_template = ''
        self.profile_a.save(update_fields=[
            'name', 'affiliation', 'title', 'booking_msg_template',
        ])

        body = self.client_a.post(
            f'/api/v1/customers/{self.customer.id}/booking-requests/').json()
        self.assertIn('안녕하세요. A생명 담당 설계사입니다.', body['message'])
        self.assertNotIn('A생명 A생명', body['message'])
        self.assertNotIn('담당 설계사 보험설계사', body['message'])

    def test_booking_request_default_message_has_no_double_space_without_label(self):
        self.profile_a.name = '황예진'
        self.profile_a.affiliation = ''
        self.profile_a.title = ''
        self.profile_a.booking_msg_template = ''
        self.profile_a.save(update_fields=[
            'name', 'affiliation', 'title', 'booking_msg_template',
        ])

        body = self.client_a.post(
            f'/api/v1/customers/{self.customer.id}/booking-requests/').json()
        self.assertIn('안녕하세요. 황예진 보험설계사입니다.', body['message'])
        self.assertNotIn('안녕하세요.  황예진', body['message'])

    def test_booking_request_custom_template_keeps_optional_label_contract(self):
        self.profile_a.name = '황예진'
        self.profile_a.affiliation = ''
        self.profile_a.title = ''
        self.profile_a.booking_msg_template = (
            '{고객명}님, {소속직책} {설계사명}입니다.\n{링크}')
        self.profile_a.save(update_fields=[
            'name', 'affiliation', 'title', 'booking_msg_template',
        ])

        body = self.client_a.post(
            f'/api/v1/customers/{self.customer.id}/booking-requests/').json()
        self.assertIn('홍길동님, 황예진입니다.', body['message'])
        self.assertNotIn('  ', body['message'])

    def test_booking_request_custom_template_keeps_fallback_name(self):
        self.profile_a.name = ''
        self.profile_a.affiliation = 'A생명'
        self.profile_a.booking_msg_template = '{소속직책} {설계사명}님\n{링크}'
        self.profile_a.save(update_fields=[
            'name', 'affiliation', 'booking_msg_template',
        ])

        body = self.client_a.post(
            f'/api/v1/customers/{self.customer.id}/booking-requests/').json()
        self.assertIn('A생명 담당 설계사님', body['message'])

    def test_booking_request_leaves_no_known_placeholder(self):
        body = self.client_a.post(
            f'/api/v1/customers/{self.customer.id}/booking-requests/').json()
        for placeholder in ('{고객명}', '{소속직책}', '{설계사명}', '{링크}'):
            self.assertNotIn(placeholder, body['message'])

    def test_booking_request_owner_isolation(self):
        r = self.client_b.post(f'/api/v1/customers/{self.customer.id}/booking-requests/')
        self.assertEqual(r.status_code, 404)

    def test_booking_request_admin_cannot_issue_link_for_foreign_customer(self):
        self.profile_b.is_admin = True
        self.profile_b.save(update_fields=['is_admin'])

        response = self.client_b.post(
            f'/api/v1/customers/{self.customer.id}/booking-requests/')

        self.assertEqual(response.status_code, 404)

    def test_booking_request_admin_can_issue_link_for_own_customer(self):
        self.profile_b.is_admin = True
        self.profile_b.save(update_fields=['is_admin'])
        own_customer = Customer.objects.create(
            owner=self.user_b,
            name='관리자 본인 고객',
            mobile_phone_number='010-1111-2222',
        )

        response = self.client_b.post(
            f'/api/v1/customers/{own_customer.id}/booking-requests/')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(read_booking_token(response.json()['token']), own_customer.id)

    # ── 예약 고객 검색(설계사 본인 소유만) ──
    def test_booking_customer_list_returns_only_owner_rows_with_minimal_fields(self):
        own_customer = Customer.objects.create(
            owner=self.user_a,
            name='내 고객',
            mobile_phone_number='010-1111-2222',
            sales_stage=Customer.STAGE_CONTACT,
            memo='예약 선택기에 노출되면 안 되는 메모',
        )
        foreign_customer = Customer.objects.create(
            owner=self.user_b,
            name='외부 고객 비밀이름',
            mobile_phone_number='010-9999-8888',
            sales_stage=Customer.STAGE_MEETING,
        )

        response = self.client_a.get('/api/v1/booking-customers/')

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['count'], 2)
        self.assertEqual(set(body), {'count', 'next', 'previous', 'results'})
        row = next(item for item in body['results'] if item['id'] == own_customer.id)
        self.assertEqual(
            row,
            {
                'id': own_customer.id,
                'name': '내 고객',
                'mobile_phone_number': '010-1111-2222',
                'sales_stage': Customer.STAGE_CONTACT,
            },
        )
        payload = response.content.decode()
        self.assertNotIn(
            foreign_customer.id,
            [item['id'] for item in body['results']],
        )
        self.assertNotIn('외부 고객 비밀이름', payload)
        self.assertNotIn('010-9999-8888', payload)
        self.assertNotIn('예약 선택기에 노출되면 안 되는 메모', payload)

    def test_booking_customer_list_keeps_admin_strictly_owner_scoped(self):
        self.profile_b.is_admin = True
        self.profile_b.save(update_fields=['is_admin'])
        own_customer = Customer.objects.create(
            owner=self.user_b,
            name='관리자 본인 고객',
            mobile_phone_number='010-3333-4444',
        )

        response = self.client_b.get('/api/v1/booking-customers/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item['id'] for item in response.json()['results']],
            [own_customer.id],
        )
        payload = response.content.decode()
        self.assertNotIn('홍길동', payload)
        self.assertNotIn('010-0000-0000', payload)

    def test_booking_customer_search_trims_and_matches_name_or_phone(self):
        name_match = Customer.objects.create(
            owner=self.user_a,
            name='검색 대상',
            mobile_phone_number='010-1111-2222',
        )
        phone_match = Customer.objects.create(
            owner=self.user_a,
            name='다른 고객',
            mobile_phone_number='010-5555-6789',
        )
        Customer.objects.create(
            owner=self.user_a,
            name='검색 제외',
            mobile_phone_number='010-0000-0001',
        )

        by_name = self.client_a.get(
            '/api/v1/booking-customers/',
            {'search': '  검색 대상  '},
        )
        by_phone = self.client_a.get(
            '/api/v1/booking-customers/',
            {'search': '  6789  '},
        )

        self.assertEqual(by_name.status_code, 200)
        self.assertEqual(
            [item['id'] for item in by_name.json()['results']],
            [name_match.id],
        )
        self.assertEqual(by_phone.status_code, 200)
        self.assertEqual(
            [item['id'] for item in by_phone.json()['results']],
            [phone_match.id],
        )

    def test_booking_customer_list_requires_authentication_and_verified_email(self):
        anonymous = APIClient().get('/api/v1/booking-customers/')
        unverified_user = User.objects.create_user(
            email='unverified-booking@test.com',
            password='inpaPass123!',
        )
        Profile.objects.create(user=unverified_user)
        unverified_client = APIClient()
        unverified_client.force_authenticate(user=unverified_user)

        unverified = unverified_client.get('/api/v1/booking-customers/')

        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(unverified.status_code, 403)

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

    @override_settings(SHOWCASE_ACCOUNT_EMAIL='agent_a@test.com')
    @mock.patch(
        'inpa.accounts.google_calendar.insert_meeting_event',
        return_value='showcase-event-must-not-exist',
    )
    @mock.patch(
        'inpa.accounts.google.google_calendar_enabled',
        return_value=True,
    )
    def test_showcase_accept_confirms_without_google_call(
        self,
        _google_enabled,
        insert_event,
    ):
        self.profile_a.is_showcase = True
        self.profile_a.google_calendar_refresh_token = 'existing-token'
        self.profile_a.save(update_fields=[
            'is_showcase',
            'google_calendar_refresh_token',
        ])
        meeting = Meeting.objects.create(
            owner=self.user_a,
            customer=self.customer,
            start_at=_future(),
            method=Meeting.METHOD_PHONE,
            status=Meeting.STATUS_PENDING,
        )

        response = self.client_a.post(
            f'/api/v1/meetings/{meeting.id}/accept/')

        self.assertEqual(response.status_code, 200)
        meeting.refresh_from_db()
        self.assertEqual(meeting.status, Meeting.STATUS_CONFIRMED)
        self.assertIsNone(meeting.google_event_id)
        insert_event.assert_not_called()

    @override_settings(SHOWCASE_ACCOUNT_EMAIL='showcase@inpa.example')
    @mock.patch(
        'inpa.accounts.google_calendar.insert_meeting_event',
        return_value='ordinary-google-event',
    )
    @mock.patch(
        'inpa.accounts.google.google_calendar_enabled',
        return_value=True,
    )
    def test_ordinary_accept_pushes_to_google_once(
        self,
        _google_enabled,
        insert_event,
    ):
        self.profile_a.google_calendar_refresh_token = 'existing-token'
        self.profile_a.save(update_fields=[
            'google_calendar_refresh_token',
        ])
        meeting = Meeting.objects.create(
            owner=self.user_a,
            customer=self.customer,
            start_at=_future(),
            method=Meeting.METHOD_PHONE,
            status=Meeting.STATUS_PENDING,
        )

        response = self.client_a.post(
            f'/api/v1/meetings/{meeting.id}/accept/')

        self.assertEqual(response.status_code, 200)
        meeting.refresh_from_db()
        self.assertEqual(
            meeting.google_event_id,
            'ordinary-google-event',
        )
        insert_event.assert_called_once()

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

    def test_short_duration_slot_bookable(self):
        # 소요시간 12분(15분 미만) — GET가 노출한 슬롯이 POST에서도 그대로 예약돼야 함.
        # 예전엔 POST가 15분 grid 로 재확인해 15분 비배수 슬롯이 409였다(grid 불일치).
        self.profile_a.booking_default_duration = 12
        self.profile_a.save(update_fields=['booking_default_duration'])
        _all_week_workhours(self.user_a)
        token = make_booking_token(self.customer)
        slots = [s['start_at'] for s in self.public.get(f'/api/v1/b/{token}/').json()['slots']]
        self.assertTrue(slots)
        off_grid = None
        for s in slots:
            if timezone.datetime.fromisoformat(s).minute % 15 != 0:
                off_grid = s  # 예: 09:12 — 15분 grid 에는 없는 슬롯
                break
        self.assertIsNotNone(off_grid, '12분 소요면 15분 비배수 슬롯이 있어야 함')
        r = self.public.post(f'/api/v1/b/{token}/',
                             {'start_at': off_grid, 'method': 'phone'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)

    def test_double_accept_is_noop(self):
        # 이미 확정된 예약을 다시 수락하면 400(멱등) — 구글 캘린더 중복 생성 방지.
        _all_week_workhours(self.user_a)
        token = make_booking_token(self.customer)
        start_at = _first_slot(self.public, token)
        self.public.post(f'/api/v1/b/{token}/',
                         {'start_at': start_at, 'method': 'phone'}, format='json')
        meeting = Meeting.objects.get(customer=self.customer)
        r1 = self.client_a.post(f'/api/v1/meetings/{meeting.id}/accept/')
        self.assertEqual(r1.status_code, 200)
        r2 = self.client_a.post(f'/api/v1/meetings/{meeting.id}/accept/')
        self.assertEqual(r2.status_code, 400)
        meeting.refresh_from_db()
        self.assertEqual(meeting.status, Meeting.STATUS_CONFIRMED)

    def test_accept_snapshots_location_for_in_person(self):
        # 대면 수락 시 설계사 기본 장소가 미팅에 스냅샷된다(전화 예약은 장소 없음).
        _all_week_workhours(self.user_a)
        token = make_booking_token(self.customer)
        start_at = _first_slot(self.public, token)
        self.public.post(f'/api/v1/b/{token}/',
                         {'start_at': start_at, 'method': 'in_person'}, format='json')
        meeting = Meeting.objects.get(customer=self.customer)
        self.assertEqual(meeting.location_detail, '')  # 신청 시엔 빈 값
        self.client_a.post(f'/api/v1/meetings/{meeting.id}/accept/')
        meeting.refresh_from_db()
        self.assertEqual(meeting.location_detail, '강남역 스타벅스')

    def test_accept_phone_leaves_location_empty(self):
        _all_week_workhours(self.user_a)
        token = make_booking_token(self.customer)
        start_at = _first_slot(self.public, token)
        self.public.post(f'/api/v1/b/{token}/',
                         {'start_at': start_at, 'method': 'phone'}, format='json')
        meeting = Meeting.objects.get(customer=self.customer)
        self.client_a.post(f'/api/v1/meetings/{meeting.id}/accept/')
        meeting.refresh_from_db()
        self.assertEqual(meeting.location_detail, '')

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

    def test_booking_customer_list_403(self):
        response = self.client.get('/api/v1/booking-customers/')
        self.assertEqual(response.status_code, 403)

    def test_public_get_404(self):
        token = make_booking_token(self.customer)
        self.assertEqual(self.public.get(f'/api/v1/b/{token}/').status_code, 404)
