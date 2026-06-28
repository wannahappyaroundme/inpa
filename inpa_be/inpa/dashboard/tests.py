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
                              {'target_meetings': 10, 'target_premium': 5000000, 'income_multiplier': 12},
                              format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['target_meetings'], 10)
        self.assertEqual(r.json()['income_multiplier'], 12)
        g = MonthlyGoal.objects.get(owner=self.user)
        self.assertEqual(g.target_premium, 5000000)
        self.assertEqual(float(g.income_multiplier), 12)

    def test_expected_income_from_premium(self):
        """예상 월급 = 가입 보험료(실적) × 배율."""
        from inpa.customers.models import Customer
        from inpa.insurances.models import CustomerInsurance
        cust = Customer.objects.create(owner=self.user, name='홍')
        CustomerInsurance.objects.create(customer=cust, monthly_premiums=200000)
        self.client.patch('/api/v1/dashboard/', {'income_multiplier': 10}, format='json')
        r = self.client.get('/api/v1/dashboard/')
        self.assertEqual(r.json()['actual_premium'], 200000)
        self.assertEqual(r.json()['expected_income'], 2000000)

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


class InsightsTests(TestCase):
    """홈 차트 집계 — trend 6개월·funnel 4단계·portfolio 도넛·owner 격리."""

    def setUp(self):
        self.user, self.client = _make_planner('ins@test.com')
        self.user_b, self.client_b = _make_planner('insb@test.com')

    def test_shape(self):
        r = self.client.get('/api/v1/dashboard/insights/')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        # 기본 n=12
        self.assertEqual(len(body['monthly_trend']), 12)
        self.assertEqual(set(body['funnel']), {'db', 'contact', 'meeting', 'contract'})
        self.assertEqual(set(body['portfolio']), {'at_risk', 'watch', 'stable', 'unknown'})

    def test_shape_months_6(self):
        """?months=6 명시 시 6개 반환."""
        body = self.client.get('/api/v1/dashboard/insights/?months=6').json()
        self.assertEqual(len(body['monthly_trend']), 6)

    def test_funnel_counts_by_stage_owner_scoped(self):
        Customer.objects.create(owner=self.user, name='가', sales_stage=Customer.STAGE_DB)
        Customer.objects.create(owner=self.user, name='나', sales_stage=Customer.STAGE_CONTRACT)
        Customer.objects.create(owner=self.user_b, name='타인', sales_stage=Customer.STAGE_DB)
        funnel = self.client.get('/api/v1/dashboard/insights/').json()['funnel']
        self.assertEqual(funnel['db'], 1)       # 타인(B) 미포함
        self.assertEqual(funnel['contract'], 1)
        self.assertEqual(funnel['meeting'], 0)

    def test_months_12_returns_12_points_with_target_premium(self):
        """?months=12 → monthly_trend 12건, 각 포인트에 target_premium 키 포함."""
        r = self.client.get('/api/v1/dashboard/insights/?months=12')
        self.assertEqual(r.status_code, 200)
        trend = r.json()['monthly_trend']
        self.assertEqual(len(trend), 12)
        for point in trend:
            self.assertIn('target_premium', point)

    def test_months_with_goal_returns_target_premium_value(self):
        """해당 월 MonthlyGoal이 있으면 target_premium이 그 값으로 반환된다."""
        from .models import MonthlyGoal
        from django.utils import timezone
        ym = timezone.now().strftime('%Y-%m')
        MonthlyGoal.objects.create(owner=self.user, year_month=ym, target_premium=3000000)
        r = self.client.get('/api/v1/dashboard/insights/?months=3')
        trend = r.json()['monthly_trend']
        # 마지막 항목(이번 달)의 target_premium이 설정값과 일치
        last = trend[-1]
        self.assertEqual(last['ym'], ym)
        self.assertEqual(last['target_premium'], 3000000)

    def test_months_param_invalid_400(self):
        """months가 허용 집합 밖이면 400."""
        self.assertEqual(
            self.client.get('/api/v1/dashboard/insights/?months=7').status_code, 400)
        self.assertEqual(
            self.client.get('/api/v1/dashboard/insights/?months=abc').status_code, 400)

    def test_default_months_is_12(self):
        """기본 n=12 — ?months 미설정 시 12개 반환."""
        trend = self.client.get('/api/v1/dashboard/insights/').json()['monthly_trend']
        self.assertEqual(len(trend), 12)
