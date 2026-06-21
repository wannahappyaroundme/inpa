"""대시보드 월별 목표 테스트 — 기본 생성·목표 갱신·실적 계산·owner 격리·month 검증."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User
from inpa.booking.models import Meeting, MeetingSlot
from inpa.customers.models import Customer

from .models import MonthlyGoal


def _make_planner(email):
    user = User.objects.create_user(email=email, password='inpaPass123!')
    user.is_active = True
    user.save(update_fields=['is_active'])
    Profile.objects.create(user=user, email_verified_at=timezone.now())
    client = APIClient()
    client.force_authenticate(user=user)
    return user, client


class DashboardTests(TestCase):
    def setUp(self):
        self.user, self.client = _make_planner('a@test.com')
        self.user_b, self.client_b = _make_planner('b@test.com')

    def test_get_creates_current_month(self):
        r = self.client.get('/api/v1/dashboard/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['year_month'], MonthlyGoal.current_month())
        self.assertTrue(MonthlyGoal.objects.filter(owner=self.user).exists())
        # 초기 목표는 0
        self.assertEqual(r.json()['target_meetings'], 0)

    def test_patch_updates_targets(self):
        r = self.client.patch('/api/v1/dashboard/',
                              {'target_meetings': 10, 'target_premium': 5000000, 'target_income': 3000000},
                              format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['target_meetings'], 10)
        g = MonthlyGoal.objects.get(owner=self.user)
        self.assertEqual(g.target_premium, 5000000)
        self.assertEqual(g.target_income, 3000000)

    def test_patch_negative_rejected(self):
        r = self.client.patch('/api/v1/dashboard/', {'target_meetings': -1}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_bad_month_400(self):
        self.assertEqual(self.client.get('/api/v1/dashboard/?month=2026/06').status_code, 400)

    def test_actuals_count_this_month(self):
        cust = Customer.objects.create(owner=self.user, name='홍길동')
        slot = MeetingSlot.objects.create(owner=self.user, start_at=timezone.now() + timedelta(days=1))
        Meeting.objects.create(owner=self.user, customer=cust, slot=slot,
                               start_at=timezone.now() + timedelta(days=1), method='phone',
                               status=Meeting.STATUS_CONFIRMED)
        r = self.client.get('/api/v1/dashboard/')
        self.assertEqual(r.json()['actual_meetings'], 1)
        self.assertEqual(r.json()['actual_new_customers'], 1)

    def test_owner_isolation(self):
        """B가 목표를 바꿔도 A의 목표는 영향 없음(각자 own row)."""
        self.client_b.patch('/api/v1/dashboard/', {'target_meetings': 99}, format='json')
        r = self.client.get('/api/v1/dashboard/')
        self.assertEqual(r.json()['target_meetings'], 0)
