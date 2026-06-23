"""개인 일정(ScheduleItem) 테스트 — 소유자 격리·과거허용·완료토글·TimeField 벽시계·고객격리."""
import datetime

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User
from inpa.customers.models import Customer

from .models import ScheduleItem


def _planner(email, verified=True):
    # 이메일 인증 = User.is_active (IsEmailVerified 가 is_active 를 검사).
    u = User.objects.create_user(email=email, password='inpaPass123!')
    u.is_active = verified
    u.save(update_fields=['is_active'])
    Profile.objects.create(
        user=u, email_verified_at=timezone.now() if verified else None)
    c = APIClient()
    c.force_authenticate(user=u)
    return u, c


class ScheduleCrudTests(TestCase):
    def setUp(self):
        self.user, self.client = _planner('sched@test.com')

    def test_create_event(self):
        r = self.client.post('/api/v1/schedule-items/', {
            'kind': 'event', 'title': '보장분석 미팅',
            'start_at': '2026-06-25T05:00:00Z'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['kind'], 'event')

    def test_past_datetime_allowed(self):
        """★ 슬롯과 달리 과거시각 일정 생성 허용(지난 일정 기록)."""
        past = (timezone.now() - datetime.timedelta(days=3)).isoformat()
        r = self.client.post('/api/v1/schedule-items/', {
            'kind': 'event', 'title': '지난 미팅', 'start_at': past}, format='json')
        self.assertEqual(r.status_code, 201, r.content)

    def test_toggle_done(self):
        it = ScheduleItem.objects.create(owner=self.user, kind='todo', title='전화 3건')
        url = f'/api/v1/schedule-items/{it.id}/toggle_done/'
        r1 = self.client.post(url)
        self.assertEqual(r1.status_code, 200)
        self.assertTrue(r1.json()['is_done'])
        self.assertIsNotNone(r1.json()['done_at'])
        r2 = self.client.post(url)
        self.assertFalse(r2.json()['is_done'])
        self.assertIsNone(r2.json()['done_at'])

    def test_recurring_block_timefield_wallclock_preserved(self):
        """★ 반복 차단 TimeField 는 KST 벽시계 그대로(12:00 입력 → 12:00 반환, UTC 변환 안 됨)."""
        r = self.client.post('/api/v1/schedule-items/', {
            'kind': 'block', 'title': '점심', 'recur_weekday': 0,
            'recur_start_time': '12:00', 'recur_end_time': '13:00'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual(body['recur_start_time'][:5], '12:00')
        self.assertEqual(body['recur_end_time'][:5], '13:00')
        self.assertEqual(ScheduleItem.objects.get(id=body['id']).recur_start_time,
                         datetime.time(12, 0))

    def test_recurring_block_requires_times(self):
        r = self.client.post('/api/v1/schedule-items/', {
            'kind': 'block', 'title': '미정', 'recur_weekday': 2}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_month_filter_includes_recurring(self):
        ScheduleItem.objects.create(owner=self.user, kind='event', title='6월 일정',
                                    start_at='2026-06-10T01:00:00Z')
        ScheduleItem.objects.create(owner=self.user, kind='event', title='7월 일정',
                                    start_at='2026-07-10T01:00:00Z')
        ScheduleItem.objects.create(owner=self.user, kind='block', title='반복차단',
                                    recur_weekday=0, recur_start_time='12:00',
                                    recur_end_time='13:00')
        r = self.client.get('/api/v1/schedule-items/?month=2026-06')
        titles = {x['title'] for x in r.json()['results']} if isinstance(r.json(), dict) else {x['title'] for x in r.json()}
        self.assertIn('6월 일정', titles)
        self.assertIn('반복차단', titles)        # 반복은 항상 포함
        self.assertNotIn('7월 일정', titles)     # 다른 달 단건 제외


class ScheduleOwnerIsolationTests(TestCase):
    def setUp(self):
        self.a, self.ca = _planner('a@test.com')
        self.b, self.cb = _planner('b@test.com')
        self.item = ScheduleItem.objects.create(owner=self.a, kind='event', title='A의 일정')

    def test_b_cannot_read_a_item(self):
        r = self.cb.get(f'/api/v1/schedule-items/{self.item.id}/')
        self.assertIn(r.status_code, (403, 404))

    def test_b_cannot_toggle_a_item(self):
        r = self.cb.post(f'/api/v1/schedule-items/{self.item.id}/toggle_done/')
        self.assertIn(r.status_code, (403, 404))

    def test_list_only_own(self):
        ScheduleItem.objects.create(owner=self.b, kind='event', title='B의 일정')
        r = self.cb.get('/api/v1/schedule-items/')
        data = r.json()
        results = data['results'] if isinstance(data, dict) else data
        self.assertTrue(all(x['title'] != 'A의 일정' for x in results))

    def test_cannot_link_other_customer(self):
        c = Customer.objects.create(owner=self.a, name='A고객')
        r = self.cb.post('/api/v1/schedule-items/', {
            'kind': 'event', 'title': '훔친고객', 'customer': c.id}, format='json')
        self.assertEqual(r.status_code, 400)


class ScheduleAuthTests(TestCase):
    def test_unverified_blocked(self):
        _, c = _planner('unverified@test.com', verified=False)
        r = c.post('/api/v1/schedule-items/', {'kind': 'event', 'title': 'x'}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_customer_set_null_keeps_item(self):
        u, c = _planner('setnull@test.com')
        cust = Customer.objects.create(owner=u, name='연결고객')
        it = ScheduleItem.objects.create(owner=u, kind='event', title='연결일정', customer=cust)
        cust.delete()
        it.refresh_from_db()
        self.assertIsNone(it.customer_id)
