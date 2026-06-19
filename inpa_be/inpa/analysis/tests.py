"""담보 한눈표/히트맵 + 계산 엔진 핵심 게이트 테스트.

★ 필수 3종 (작업 지시):
  (a) calculate — 샘플 입력으로 계산 엔진(calculate_total_analysis) 동작 검증.
  (b) neutral 게이트 — PlannerBaseline 없으면 heatmap mode='neutral'(부족/충분 단정 금지).
  (c) owner 격리 — 설계사 A가 B 고객의 heatmap에 접근하면 404.
+ graded 모드(살아있는 baseline 있을 때 shortage/adequate/over 판정) 보강.
"""
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User
from inpa.analysis.calculate import calculate_total_analysis
from inpa.analysis.models import (
    AnalysisCategory, AnalysisDetail, AnalysisSubCategory, ChartDetail,
)
from inpa.customers.models import Customer, PlannerBaseline
from inpa.insurances.models import (
    CustomerInsurance, CustomerInsuranceDetail, InsuranceCategory,
    InsuranceDetail, InsuranceSubCategory,
)


def _make_planner(email):
    """이메일 인증 완료 설계사 + 인증된 APIClient."""
    user = User.objects.create_user(email=email, password='inpaPass123!')
    user.is_active = True
    user.save(update_fields=['is_active'])
    Profile.objects.create(user=user, email_verified_at=timezone.now())
    client = APIClient()
    client.force_authenticate(user=user)
    return user, client


def _build_std_tree():
    """표준 담보 트리: 카테고리1 > 서브1 > 디테일 '사망보장' 1개. 반환 = AnalysisDetail."""
    cat = AnalysisCategory.objects.create(insurance_type=2, name='상해', order=1)
    sub = AnalysisSubCategory.objects.create(insurance_type=2, category=cat,
                                             name='사망/후유', order=1)
    det = AnalysisDetail.objects.create(sub_category=sub, name='사망보장', order=1)
    return det


def _catalog_detail_linked_to(analysis_detail):
    """카탈로그 InsuranceDetail 1개를 만들고 표준 담보(analysis_detail)에 M2M 연결."""
    icat = InsuranceCategory.objects.create(insurance_type=2, name='손보상품', order=1)
    isub = InsuranceSubCategory.objects.create(insurance_type=2, category=icat,
                                               name='보장', order=1)
    idet = InsuranceDetail.objects.create(sub_category=isub, name='사망담보', order=1)
    idet.analysis_detail.add(analysis_detail)
    return idet


def _make_portfolio(customer, catalog_detail, assurance_amount):
    """고객 보유 포트폴리오 1건 + 담보 케이스 1건(비갱신, 보장금액 지정)."""
    ci = CustomerInsurance.objects.create(
        customer=customer, insurance_type=2, name='테스트보험',
        portfolio_type=1, payment_period_type=1, payment_period=20,
        monthly_premiums=50000, monthly_assurance_premium=50000,
    )
    CustomerInsuranceDetail.objects.create(
        insurance=ci, detail=catalog_detail,
        assurance_amount=assurance_amount, premium=10000,
        payment_period_type=1, payment_period=20,
        warranty_period_type=1, warranty_period='100',
    )
    return ci


class CalculateEngineTests(TestCase):
    """(a) 계산 엔진 — 샘플 입력으로 calculate_total_analysis 동작 검증."""

    def setUp(self):
        self.user, _ = _make_planner('calc@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='계산고객', birth_day='1985.05.05')
        self.det = _build_std_tree()
        self.idet = _catalog_detail_linked_to(self.det)
        self.ci = _make_portfolio(self.customer, self.idet, assurance_amount=100000000)

    def test_calculate_total_analysis_aggregates_amount(self):
        """표준 담보 트리에 보장금액(1억)이 집계되고 합계 필드가 채워진다."""
        # CustomerInsurance.calculate() 로 월/총 보험료 산출(엔진 무변경 호출)
        self.ci.set_renewal_month()
        self.ci.calculate()
        self.ci.save()

        case_list = [dict(d) for d in AnalysisDetail.objects.all().values(
            'id', 'name', 'order', 'chart_based_amount', 'sub_category_id')]
        chart_list = [dict(c) for c in ChartDetail.objects.all().values(
            'id', 'name', 'order', 'chart_based_amount', 'insurance_type', 'chart_type')]
        insurance_list = list(self.customer.customer_insurance_list.all())

        result = calculate_total_analysis(
            self.customer.birth_day, case_list, chart_list, insurance_list)

        # 표준 담보 '사망보장' 칸에 1억 집계
        target = next(c for c in result['case_list'] if c['id'] == self.det.id)
        self.assertEqual(target['total_premium'], 100000000)
        self.assertEqual(target['total_non_renewal_premium'], 100000000)
        # 합계 키 존재 + 월보험료 누적
        self.assertIn('total_premiums', result)
        self.assertEqual(result['monthly_premiums'], 50000)

    def test_calculate_handles_empty_insurance_list(self):
        """보험 0건이어도 예외 없이 0 집계."""
        case_list = [dict(d) for d in AnalysisDetail.objects.all().values(
            'id', 'name', 'order', 'chart_based_amount', 'sub_category_id')]
        result = calculate_total_analysis('1985.05.05', case_list, [], [])
        self.assertEqual(result['total_premiums'], 0)
        self.assertEqual(result['case_list'][0]['total_premium'], 0)


class HeatmapNeutralGateTests(TestCase):
    """(b) ★ 준법 neutral 게이트 — PlannerBaseline 없으면 mode='neutral'."""

    def setUp(self):
        self.user, self.client = _make_planner('neutral@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='무기준고객', birth_day='1990.01.01', gender=1)
        self.det = _build_std_tree()
        self.idet = _catalog_detail_linked_to(self.det)
        self.ci = _make_portfolio(self.customer, self.idet, assurance_amount=50000000)
        self.ci.set_renewal_month()
        self.ci.calculate()
        self.ci.save()

    def _get(self):
        return self.client.get(f'/api/v1/customers/{self.customer.id}/heatmap/')

    def test_no_baseline_forces_neutral(self):
        """baseline 0건 → mode='neutral', 모든 담보 status='neutral'(부족/충분 단정 금지)."""
        r = self._get()
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body['mode'], 'neutral')
        self.assertFalse(body['baseline_present'])
        for cat in body['tree']:
            for sub in cat['sub_categories']:
                for det in sub['details']:
                    self.assertEqual(det['status'], 'neutral')
                    self.assertIsNone(det['baseline'])

    def test_baseline_with_null_source_still_neutral(self):
        """baseline 있으나 baseline_source=null → 여전히 neutral 강제(준법 통제점)."""
        PlannerBaseline.objects.create(
            owner=self.user, coverage_key='사망보장',
            product_group=PlannerBaseline.PRODUCT_GROUP_NONLIFE,
            age_band='30s', gender=1,
            recommend_min=100000000, recommend_max=300000000,
            baseline_source=None,  # ★ source 없음 → 판정 권위 미확립
        )
        r = self._get()
        body = r.json()
        self.assertEqual(body['mode'], 'neutral')

    def test_heatmap_includes_held_amount(self):
        """neutral 이어도 보유 보장금액(held_amount)은 표시(중립 사실 표시는 허용)."""
        r = self._get()
        body = r.json()
        held = body['tree'][0]['sub_categories'][0]['details'][0]['held_amount']
        self.assertEqual(held, 50000000)


class HeatmapGradedTests(TestCase):
    """살아있는 baseline(source!=null)이 있으면 mode='graded' + 담보별 판정."""

    def setUp(self):
        self.user, self.client = _make_planner('graded@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='기준고객', birth_day='1990.01.01', gender=1)
        self.det = _build_std_tree()
        self.idet = _catalog_detail_linked_to(self.det)

    def _baseline(self, lo, hi):
        return PlannerBaseline.objects.create(
            owner=self.user, coverage_key='사망보장',
            product_group=PlannerBaseline.PRODUCT_GROUP_NONLIFE,
            age_band='30s', gender=1,
            recommend_min=lo, recommend_max=hi,
            baseline_source='planner',  # ★ 살아있는 출처
        )

    def _heatmap_detail_status(self):
        r = self.client.get(f'/api/v1/customers/{self.customer.id}/heatmap/')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body['mode'], 'graded')
        return body['tree'][0]['sub_categories'][0]['details'][0]

    def test_shortage_when_held_below_min(self):
        self._baseline(lo=100000000, hi=300000000)
        ci = _make_portfolio(self.customer, self.idet, assurance_amount=50000000)
        ci.calculate(); ci.save()
        det = self._heatmap_detail_status()
        self.assertEqual(det['status'], 'shortage')

    def test_adequate_when_within_range(self):
        self._baseline(lo=100000000, hi=300000000)
        ci = _make_portfolio(self.customer, self.idet, assurance_amount=200000000)
        ci.calculate(); ci.save()
        det = self._heatmap_detail_status()
        self.assertEqual(det['status'], 'adequate')

    def test_over_when_held_above_max(self):
        self._baseline(lo=100000000, hi=300000000)
        ci = _make_portfolio(self.customer, self.idet, assurance_amount=500000000)
        ci.calculate(); ci.save()
        det = self._heatmap_detail_status()
        self.assertEqual(det['status'], 'over')

    def test_unmatched_detail_stays_neutral_even_in_graded(self):
        """graded 모드라도 baseline 매칭 없는 담보는 neutral(단정 금지)."""
        # coverage_key 가 트리 담보명과 다른 baseline → '사망보장'엔 매칭 없음
        PlannerBaseline.objects.create(
            owner=self.user, coverage_key='암진단비',
            product_group=PlannerBaseline.PRODUCT_GROUP_NONLIFE,
            age_band='30s', gender=1, recommend_min=10000000,
            baseline_source='planner')
        ci = _make_portfolio(self.customer, self.idet, assurance_amount=50000000)
        ci.calculate(); ci.save()
        det = self._heatmap_detail_status()
        self.assertEqual(det['status'], 'neutral')


class HeatmapOwnerIsolationTests(TestCase):
    """(c) ★ owner 격리 — A는 B 고객의 heatmap에 접근 불가."""

    def setUp(self):
        self.user_a, self.client_a = _make_planner('a@heatmap.com')
        self.user_b, self.client_b = _make_planner('b@heatmap.com')
        self.cust_b = Customer.objects.create(
            owner=self.user_b, name='B고객', birth_day='1988.08.08')
        det = _build_std_tree()
        idet = _catalog_detail_linked_to(det)
        _make_portfolio(self.cust_b, idet, assurance_amount=70000000)

    def test_a_cannot_get_b_heatmap(self):
        """A가 B 고객 heatmap 조회 → 404(존재 자체 은폐)."""
        r = self.client_a.get(f'/api/v1/customers/{self.cust_b.id}/heatmap/')
        self.assertEqual(r.status_code, 404)

    def test_owner_can_get_own_heatmap(self):
        """소유자 B는 본인 고객 heatmap 정상 조회."""
        r = self.client_b.get(f'/api/v1/customers/{self.cust_b.id}/heatmap/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['customer_id'], self.cust_b.id)

    def test_unauthenticated_blocked(self):
        c = APIClient()
        r = c.get(f'/api/v1/customers/{self.cust_b.id}/heatmap/')
        self.assertEqual(r.status_code, 401)
