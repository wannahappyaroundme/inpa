"""담보 한눈표/히트맵 + 계산 엔진 핵심 게이트 테스트.

★ 필수 3종 (작업 지시):
  (a) calculate — 샘플 입력으로 계산 엔진(calculate_total_analysis) 동작 검증.
  (b) neutral 게이트 — PlannerBaseline 없으면 heatmap mode='neutral'(부족/충분 단정 금지).
  (c) owner 격리 — 설계사 A가 B 고객의 heatmap에 접근하면 404.
+ graded 모드(살아있는 baseline 있을 때 shortage/adequate/over 판정) 보강.
"""
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User
from inpa.analysis.calculate import calculate_analysis, calculate_total_analysis
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

    def test_lifetime_nonrenewal_stays_in_nonrenewal_coverage_bucket(self):
        case = self.ci.case_list.get()
        case.payment_period_type = 4
        case.payment_period = None
        case.renewal_period = None
        case.save(update_fields=(
            'payment_period_type', 'payment_period', 'renewal_period'))
        case_list = [dict(d) for d in AnalysisDetail.objects.all().values(
            'id', 'name', 'order', 'chart_based_amount', 'sub_category_id')]

        result = calculate_total_analysis(
            self.customer.birth_day, case_list, [], [self.ci])

        target = next(
            row for row in result['case_list'] if row['id'] == self.det.id)
        self.assertEqual(target['total_non_renewal_premium'], 100000000)
        self.assertEqual(target['total_renewal_premium'], 0)

    def test_lifetime_renewal_stays_in_renewal_coverage_bucket(self):
        case = self.ci.case_list.get()
        case.payment_period_type = 4
        case.payment_period = None
        case.renewal_period = 10
        case.save(update_fields=(
            'payment_period_type', 'payment_period', 'renewal_period'))
        case_list = [dict(d) for d in AnalysisDetail.objects.all().values(
            'id', 'name', 'order', 'chart_based_amount', 'sub_category_id')]

        result = calculate_total_analysis(
            self.customer.birth_day, case_list, [], [self.ci])

        target = next(
            row for row in result['case_list'] if row['id'] == self.det.id)
        self.assertEqual(target['total_renewal_premium'], 100000000)
        self.assertEqual(target['total_non_renewal_premium'], 0)

    def _run_both_aggregators(self, insurances):
        return [
            (
                calculate.__name__,
                calculate(
                    self.customer.birth_day, [], [], list(insurances)),
            )
            for calculate in (calculate_analysis, calculate_total_analysis)
        ]

    def _insurance_with_totals(self, name, *, monthly, renewal_monthly,
                               nonrenewal_monthly, total, renewal_total,
                               nonrenewal_total, earned_total):
        return CustomerInsurance.objects.create(
            customer=self.customer,
            insurance_type=2,
            name=name,
            portfolio_type=1,
            payment_period_type=1,
            payment_period=20,
            non_renewal_month=240,
            contract_date=timezone.localdate().strftime('%Y.%m.%d'),
            monthly_premiums=monthly,
            monthly_renewal_premium=renewal_monthly,
            monthly_non_renewal_premium=nonrenewal_monthly,
            total_premiums=total,
            total_renewal_premium=renewal_total,
            total_non_renewal_premium=nonrenewal_total,
            total_earned_premium=earned_total,
        )

    def test_both_aggregators_preserve_unknown_absolute_totals(self):
        known = self._insurance_with_totals(
            '확정값보험', monthly=200, renewal_monthly=50,
            nonrenewal_monthly=150, total=1000, renewal_total=400,
            nonrenewal_total=600, earned_total=0)
        unknown = self._insurance_with_totals(
            '종신납보험', monthly=300, renewal_monthly=100,
            nonrenewal_monthly=200, total=None, renewal_total=None,
            nonrenewal_total=None, earned_total=None)

        for name, result in self._run_both_aggregators([known, unknown]):
            with self.subTest(calculate=name):
                self.assertEqual(result['monthly_premiums'], 500)
                self.assertEqual(result['monthly_renewal_premium'], 150)
                self.assertEqual(result['monthly_non_renewal_premium'], 350)
                self.assertIsNone(result['total_premiums'])
                self.assertIsNone(result['total_renewal_premium'])
                self.assertIsNone(result['total_non_renewal_premium'])
                self.assertIsNone(result['total_earned_premium'])
                self.assertIsNone(result['total_pay_insurance_premium'])

    def test_both_aggregators_do_not_expose_partial_monthly_totals(self):
        known = self._insurance_with_totals(
            '월보험료확정', monthly=200, renewal_monthly=50,
            nonrenewal_monthly=150, total=1000, renewal_total=400,
            nonrenewal_total=600, earned_total=0)
        unknown = self._insurance_with_totals(
            '월보험료미확정', monthly=None, renewal_monthly=None,
            nonrenewal_monthly=None, total=None, renewal_total=None,
            nonrenewal_total=None, earned_total=None)

        for name, result in self._run_both_aggregators([known, unknown]):
            with self.subTest(calculate=name):
                self.assertIsNone(result['monthly_premiums'])
                self.assertIsNone(result['monthly_renewal_premium'])
                self.assertIsNone(result['monthly_non_renewal_premium'])
                self.assertIsNone(result['monthly_earned_premium'])

    def test_both_aggregators_sum_known_absolute_totals_exactly(self):
        first = self._insurance_with_totals(
            '확정값보험1', monthly=100, renewal_monthly=40,
            nonrenewal_monthly=60, total=1000, renewal_total=400,
            nonrenewal_total=600, earned_total=0)
        second = self._insurance_with_totals(
            '확정값보험2', monthly=200, renewal_monthly=50,
            nonrenewal_monthly=150, total=2000, renewal_total=500,
            nonrenewal_total=1500, earned_total=0)

        for name, result in self._run_both_aggregators([first, second]):
            with self.subTest(calculate=name):
                self.assertEqual(result['monthly_premiums'], 300)
                self.assertEqual(result['monthly_renewal_premium'], 90)
                self.assertEqual(result['monthly_non_renewal_premium'], 210)
                self.assertEqual(result['total_premiums'], 3000)
                self.assertEqual(result['total_renewal_premium'], 900)
                self.assertEqual(result['total_non_renewal_premium'], 2100)
                self.assertEqual(result['total_earned_premium'], 0)
                self.assertEqual(result['total_pay_insurance_premium'], 3000)


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

    @override_settings(INSURANCE_REVIEW_GATE_ENABLED=True)
    def test_heatmap_skips_legacy_confirmed_policy_with_unknown_assurance(self):
        self.ci.review_status = 'confirmed'
        self.ci.analysis_included = True
        self.ci.save(update_fields=('review_status', 'analysis_included'))
        self.ci.case_list.update(assurance_amount=None)

        response = self._get()

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['insurance_count'], 0)
        held = response.json()['tree'][0]['sub_categories'][0]['details'][0][
            'held_amount']
        self.assertEqual(held, 0)


@override_settings(HEATMAP_GRADING_ENABLED=True)
class HeatmapGradedTests(TestCase):
    """살아있는 baseline(source!=null)이 있으면 mode='graded' + 담보별 판정."""

    def setUp(self):
        self.user, self.client = _make_planner('graded@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='기준고객', birth_day='1990.01.01', gender=1)
        self.det = _build_std_tree()
        self.idet = _catalog_detail_linked_to(self.det)

    def _baseline(
        self,
        lo,
        hi,
        *,
        unit=PlannerBaseline.UNIT_WON,
        product_group=PlannerBaseline.PRODUCT_GROUP_NONLIFE,
        age_band='30s',
        gender=1,
    ):
        return PlannerBaseline.objects.create(
            owner=self.user, coverage_key='사망보장',
            product_group=product_group,
            age_band=age_band, gender=gender,
            recommend_min=lo, recommend_max=hi,
            unit=unit,
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

    def test_invalid_persisted_bounds_fail_closed_to_neutral(self):
        ci = _make_portfolio(self.customer, self.idet, assurance_amount=200000000)
        ci.calculate(); ci.save()

        for lo, hi in ((-1, 300000000), (300000001, 300000000)):
            with self.subTest(lo=lo, hi=hi):
                PlannerBaseline.objects.filter(owner=self.user).delete()
                self._baseline(lo=lo, hi=hi)
                det = self._heatmap_detail_status()
                self.assertEqual(det['status'], 'neutral')
                self.assertIsNone(det['baseline'])

    def test_unmatched_detail_stays_neutral_even_in_graded(self):
        """graded 모드라도 baseline 매칭 없는 담보는 neutral(단정 금지)."""
        # coverage_key 가 트리 담보명과 다른 baseline → '사망보장'엔 매칭 없음
        PlannerBaseline.objects.create(
            owner=self.user, coverage_key='암진단비',
            product_group=PlannerBaseline.PRODUCT_GROUP_NONLIFE,
            age_band='30s', gender=1, recommend_min=10000000,
            unit=PlannerBaseline.UNIT_WON,
            baseline_source='planner')
        ci = _make_portfolio(self.customer, self.idet, assurance_amount=50000000)
        ci.calculate(); ci.save()
        det = self._heatmap_detail_status()
        self.assertEqual(det['status'], 'neutral')

    @override_settings(HEATMAP_GRADING_ENABLED=False)
    def test_gate_closed_keeps_every_cell_neutral_even_with_baselines(self):
        self._baseline(lo=30000000, hi=50000000)
        ci = _make_portfolio(self.customer, self.idet, assurance_amount=50000000)
        ci.calculate(); ci.save()

        response = self.client.get(f'/api/v1/customers/{self.customer.id}/heatmap/')

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['mode'], 'neutral')
        self.assertTrue(body['baseline_present'])
        self.assertFalse(body['grading_enabled'])
        for category in body['tree']:
            for sub_category in category['sub_categories']:
                for detail in sub_category['details']:
                    self.assertEqual(detail['status'], 'neutral')
                    self.assertIsNone(detail['baseline'])

    def test_fifty_million_won_equals_five_thousand_ten_thousand_won(self):
        self._baseline(
            lo=5000,
            hi=6000,
            unit=PlannerBaseline.UNIT_TEN_THOUSAND_WON,
        )
        ci = _make_portfolio(self.customer, self.idet, assurance_amount=50000000)
        ci.calculate(); ci.save()

        detail = self._heatmap_detail_status()

        self.assertEqual(detail['status'], 'adequate')
        self.assertEqual(detail['baseline'], {
            'min': 50000000,
            'max': 60000000,
            'display_unit': PlannerBaseline.UNIT_TEN_THOUSAND_WON,
            'baseline_source': 'planner',
        })

    def test_twenty_million_is_shortage_against_thirty_million(self):
        self._baseline(lo=30000000, hi=50000000)
        ci = _make_portfolio(self.customer, self.idet, assurance_amount=20000000)
        ci.calculate(); ci.save()

        detail = self._heatmap_detail_status()

        self.assertEqual(detail['status'], 'shortage')

    def test_account_unit_and_wrong_scope_stay_neutral(self):
        ci = _make_portfolio(self.customer, self.idet, assurance_amount=50000000)
        ci.calculate(); ci.save()
        self._baseline(
            lo=3,
            hi=5,
            unit=PlannerBaseline.UNIT_ACCOUNT,
        )

        self.assertEqual(self._heatmap_detail_status()['status'], 'neutral')

        PlannerBaseline.objects.filter(owner=self.user).delete()
        self._baseline(
            lo=30000000,
            hi=50000000,
            product_group=PlannerBaseline.PRODUCT_GROUP_LIFE,
        )

        self.assertEqual(self._heatmap_detail_status()['status'], 'neutral')

    def test_category_type_wins_over_mismatched_subcategory_type(self):
        category = self.det.sub_category.category
        category.insurance_type = 1
        category.save(update_fields=['insurance_type'])
        self._baseline(lo=30000000, hi=50000000)
        ci = _make_portfolio(self.customer, self.idet, assurance_amount=50000000)
        ci.calculate(); ci.save()

        detail = self._heatmap_detail_status()

        self.assertEqual(detail['status'], 'neutral')
        self.assertIsNone(detail['baseline'])

    def test_wrong_age_baseline_stays_neutral(self):
        self._baseline(lo=30000000, hi=50000000, age_band='40s')
        ci = _make_portfolio(self.customer, self.idet, assurance_amount=50000000)
        ci.calculate(); ci.save()

        detail = self._heatmap_detail_status()

        self.assertEqual(detail['status'], 'neutral')
        self.assertIsNone(detail['baseline'])

    def test_wrong_gender_baseline_stays_neutral(self):
        self._baseline(lo=30000000, hi=50000000, gender=2)
        ci = _make_portfolio(self.customer, self.idet, assurance_amount=50000000)
        ci.calculate(); ci.save()

        detail = self._heatmap_detail_status()

        self.assertEqual(detail['status'], 'neutral')
        self.assertIsNone(detail['baseline'])

    def test_common_category_stays_neutral_even_with_nonlife_baseline(self):
        category = self.det.sub_category.category
        category.insurance_type = 0
        category.save(update_fields=['insurance_type'])
        self._baseline(lo=30000000, hi=50000000)
        ci = _make_portfolio(self.customer, self.idet, assurance_amount=50000000)
        ci.calculate(); ci.save()

        detail = self._heatmap_detail_status()

        self.assertEqual(detail['status'], 'neutral')
        self.assertIsNone(detail['baseline'])


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


class HeatmapProposalExclusionTests(TestCase):
    """★ 제안(portfolio_type=2)이 히트맵 '보유 보장금액'에 섞이지 않는다."""

    def setUp(self):
        self.user, self.client = _make_planner('proposal@heatmap.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='제안고객', birth_day='1990.01.01', gender=1)
        self.det = _build_std_tree()
        self.idet = _catalog_detail_linked_to(self.det)
        # 보유(pt=1) 1억
        held = _make_portfolio(self.customer, self.idet, assurance_amount=100000000)
        held.set_renewal_month(); held.calculate(); held.save()

    def _make_proposal(self, amount):
        ci = CustomerInsurance.objects.create(
            customer=self.customer, insurance_type=2, name='제안보험',
            portfolio_type=2, payment_period_type=1, payment_period=20,
            monthly_premiums=70000, monthly_assurance_premium=70000)
        CustomerInsuranceDetail.objects.create(
            insurance=ci, detail=self.idet, assurance_amount=amount, premium=20000,
            payment_period_type=1, payment_period=20,
            warranty_period_type=1, warranty_period='100')
        ci.set_renewal_month(); ci.calculate(); ci.save()
        return ci

    def test_proposal_excluded_from_held_amount(self):
        self._make_proposal(amount=500000000)  # 제안 5억 — 보유로 잡히면 안 됨
        body = self.client.get(
            f'/api/v1/customers/{self.customer.id}/heatmap/').json()
        held = body['tree'][0]['sub_categories'][0]['details'][0]['held_amount']
        self.assertEqual(held, 100000000)   # 보유 1억만(제안 5억 제외)
        self.assertEqual(body['insurance_count'], 1)  # 보유 1건만 집계


class HeatmapAnalysisViewEventTests(TestCase):
    """★ 히트맵 조회 → 북극성 ANALYSIS_VIEW 1건 적재(관리자 '분석 조회' 집계)."""

    def setUp(self):
        self.user, self.client = _make_planner('anview@heatmap.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='조회고객', birth_day='1990.01.01', gender=1)
        det = _build_std_tree()
        idet = _catalog_detail_linked_to(det)
        _make_portfolio(self.customer, idet, assurance_amount=50000000)

    def test_viewing_heatmap_logs_one_analysis_view(self):
        from inpa.analytics.models import NorthStarEvent
        r = self.client.get(f'/api/v1/customers/{self.customer.id}/heatmap/')
        self.assertEqual(r.status_code, 200)
        evs = NorthStarEvent.objects.filter(
            event_type=NorthStarEvent.ANALYSIS_VIEW,
            customer=self.customer, sender=self.user)
        self.assertEqual(evs.count(), 1)   # 요청당 정확히 1건(중복 계측 없음)


# ──────────────────────────────────────────────────────────────────────
# 갈아타기(승환) 비교 — 보유(portfolio_type=1) vs 제안(portfolio_type=2)
# ★ 준법 게이트: AI 비활성 시 guide null / 발행 403 하드블록 / owner 격리.
# ──────────────────────────────────────────────────────────────────────
def _make_portfolio_typed(customer, catalog_detail, assurance_amount,
                          portfolio_type, monthly=50000):
    """portfolio_type 지정 포트폴리오 1건 + 담보 케이스 1건(비갱신)."""
    ci = CustomerInsurance.objects.create(
        customer=customer, insurance_type=2, name='비교보험',
        portfolio_type=portfolio_type, payment_period_type=1, payment_period=20,
        monthly_premiums=monthly, monthly_assurance_premium=monthly,
    )
    CustomerInsuranceDetail.objects.create(
        insurance=ci, detail=catalog_detail,
        assurance_amount=assurance_amount, premium=10000,
        payment_period_type=1, payment_period=20,
        warranty_period_type=1, warranty_period='100',
    )
    ci.set_renewal_month()
    ci.calculate()
    ci.save()
    return ci


class CompareFactsTests(TestCase):
    """비교표(사실)는 ★AI 없이 지금 완전 동작 — 보유/제안 담보별 금액 + delta + summary."""

    def setUp(self):
        self.user, self.client = _make_planner('compare-facts@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='비교고객', birth_day='1990.01.01', gender=1)
        self.det = _build_std_tree()  # 표준 담보 '사망보장'
        self.idet = _catalog_detail_linked_to(self.det)

    def _get(self):
        return self.client.get(f'/api/v1/customers/{self.customer.id}/compare/')

    def test_rows_and_delta_pure_data(self):
        """보유 5천만 vs 제안 1억 → row delta=+5천만, AI 비활성이어도 동작."""
        _make_portfolio_typed(self.customer, self.idet, 50000000, portfolio_type=1,
                              monthly=40000)
        _make_portfolio_typed(self.customer, self.idet, 100000000, portfolio_type=2,
                              monthly=60000)
        r = self._get()
        self.assertEqual(r.status_code, 200)
        body = r.json()
        row = next(x for x in body['rows'] if x['coverage'] == '사망보장')
        self.assertEqual(row['current_amount'], 50000000)
        self.assertEqual(row['proposed_amount'], 100000000)
        self.assertEqual(row['delta'], 50000000)
        # summary 사실 집계
        self.assertEqual(body['current']['monthly_premiums'], 40000)
        self.assertEqual(body['proposed']['monthly_premiums'], 60000)

    def test_summary_null_when_side_empty(self):
        """제안 보험이 0건이면 proposed.monthly_premiums=null (미보유 구분)."""
        _make_portfolio_typed(self.customer, self.idet, 50000000, portfolio_type=1)
        r = self._get()
        body = r.json()
        self.assertIsNone(body['proposed']['monthly_premiums'])
        self.assertIsNone(body['proposed']['total_premiums'])
        # 보유 한쪽만 있는 담보 → proposed_amount null, delta null
        row = next(x for x in body['rows'] if x['coverage'] == '사망보장')
        self.assertEqual(row['current_amount'], 50000000)
        self.assertIsNone(row['proposed_amount'])
        self.assertIsNone(row['delta'])

    def test_selection_compares_only_selected(self):
        """보험 선택 비교(PM 06.29): current_ids/proposed_ids 로 고른 보험만 집계."""
        h1 = _make_portfolio_typed(self.customer, self.idet, 50000000, portfolio_type=1, monthly=40000)
        h2 = _make_portfolio_typed(self.customer, self.idet, 30000000, portfolio_type=1, monthly=20000)
        p1 = _make_portfolio_typed(self.customer, self.idet, 100000000, portfolio_type=2, monthly=60000)
        # 전체(GET, 하위호환): 보유 2건 합산 월 60000
        self.assertEqual(self._get().json()['current']['monthly_premiums'], 60000)
        # h1만 선택(POST) → 보유 월 40000
        r = self.client.post(
            f'/api/v1/customers/{self.customer.id}/compare/',
            {'current_ids': [h1.id], 'proposed_ids': [p1.id]}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['current']['monthly_premiums'], 40000)
        # 제안 0개 선택 → proposed null (전체로 되돌아가지 않음)
        r2 = self.client.post(
            f'/api/v1/customers/{self.customer.id}/compare/',
            {'current_ids': [h1.id, h2.id], 'proposed_ids': []}, format='json')
        self.assertIsNone(r2.json()['proposed']['monthly_premiums'])

    def test_contract_shape_and_disclaimer(self):
        """계약 키 전부 존재 + publishable 항상 false + 면책 고정 + verdict 키 없음(판정 제거)."""
        _make_portfolio_typed(self.customer, self.idet, 50000000, portfolio_type=1)
        body = self._get().json()
        for key in ('mode', 'current', 'proposed', 'rows', 'comparison_source',
                    'guide_draft', 'guide_enabled', 'guide_source', 'switch_warnings', 'publishable',
                    'publish_blocked_reason', 'disclaimer'):
            self.assertIn(key, body)
        self.assertFalse(body['publishable'])
        self.assertEqual(body['comparison_source'], 'deterministic')
        self.assertIsNone(body['guide_source'])
        self.assertEqual(body['publish_blocked_reason'], '법무 검토 완료 전 발행 금지')
        self.assertIn('AI', body['disclaimer'])
        # ★ 2026-07-09 재정의: 인파는 KEEP/SWITCH 판정을 산출하지 않는다 → verdict 키 부재.
        self.assertNotIn('verdict', body)

    @override_settings(HEATMAP_GRADING_ENABLED=False)
    def test_mode_stays_neutral_while_heatmap_grading_gate_is_closed(self):
        PlannerBaseline.objects.create(
            owner=self.user,
            coverage_key='사망보장',
            product_group=PlannerBaseline.PRODUCT_GROUP_NONLIFE,
            age_band='30s',
            gender=1,
            recommend_min=100000000,
            recommend_max=300000000,
            unit=PlannerBaseline.UNIT_WON,
            baseline_source='planner',
        )

        self.assertEqual(self._get().json()['mode'], 'neutral')

    @override_settings(COMPARE_AI_ENABLED=False)
    def test_ai_disabled_guide_null(self):
        """★ COMPARE_AI_ENABLED=False → guide_draft=null, guide_enabled=false."""
        _make_portfolio_typed(self.customer, self.idet, 50000000, portfolio_type=1)
        _make_portfolio_typed(self.customer, self.idet, 100000000, portfolio_type=2)
        body = self._get().json()
        self.assertIsNone(body['guide_draft'])
        self.assertFalse(body['guide_enabled'])
        self.assertEqual(body['comparison_source'], 'deterministic')
        self.assertIsNone(body['guide_source'])

    # ── 확인해야 할 사항(switch_warnings, 중립 사실 — 판정 아님) ──────────────
    # ★ 2026-07-09 재정의(PM 지시, §97 리스크 축소): 인파는 KEEP/SWITCH/NEUTRAL 판정을
    #   산출하지 않는다. 응답에는 verdict 키가 없고, switch_warnings 만 남는다.
    def test_verdict_key_removed_switch_warnings_present(self):
        """verdict 키는 응답에 없고, switch_warnings(중립 사실) 키는 존재."""
        _make_portfolio_typed(self.customer, self.idet, 50000000, portfolio_type=1, monthly=40000)
        _make_portfolio_typed(self.customer, self.idet, 100000000, portfolio_type=2, monthly=60000)
        body = self._get().json()
        self.assertNotIn('verdict', body)
        self.assertIn('switch_warnings', body)
        self.assertIsInstance(body['switch_warnings'], list)

    def test_switch_warnings_empty_when_no_proposed(self):
        """비교 대상(B측)이 없으면 면책/이율 유의사항이 생기지 않는다(정성 항목은 has_proposed 조건)."""
        _make_portfolio_typed(self.customer, self.idet, 50000000, portfolio_type=1)
        body = self._get().json()
        types = {w['type'] for w in body['switch_warnings']}
        self.assertNotIn('exemption_reset', types)
        self.assertNotIn('rate_change', types)

    def test_switch_warnings_present_when_both_sides(self):
        """양측 다 있으면 면책 리셋·이율 변동 유의사항이 뜬다(사실 나열, 판정 아님)."""
        _make_portfolio_typed(self.customer, self.idet, 50000000, portfolio_type=1, monthly=40000)
        _make_portfolio_typed(self.customer, self.idet, 100000000, portfolio_type=2, monthly=60000)
        body = self._get().json()
        types = {w['type'] for w in body['switch_warnings']}
        self.assertIn('exemption_reset', types)
        self.assertIn('rate_change', types)
        for w in body['switch_warnings']:
            for k in ('type', 'label', 'detail', 'amount'):
                self.assertIn(k, w)

    # ── A/B 자유 비교(side_a_ids/side_b_ids) — portfolio_type 무관 ─────────────
    def test_side_ab_ids_compare_two_proposals(self):
        """제안 vs 제안(둘 다 portfolio_type=2)도 side_a_ids/side_b_ids 로 비교 가능."""
        p1 = _make_portfolio_typed(self.customer, self.idet, 40000000, portfolio_type=2, monthly=30000)
        p2 = _make_portfolio_typed(self.customer, self.idet, 90000000, portfolio_type=2, monthly=55000)
        r = self.client.post(
            f'/api/v1/customers/{self.customer.id}/compare/',
            {'side_a_ids': [p1.id], 'side_b_ids': [p2.id]}, format='json')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body['current']['monthly_premiums'], 30000)
        self.assertEqual(body['proposed']['monthly_premiums'], 55000)
        row = next(x for x in body['rows'] if x['coverage'] == '사망보장')
        self.assertEqual(row['current_amount'], 40000000)
        self.assertEqual(row['proposed_amount'], 90000000)
        self.assertEqual(row['delta'], 50000000)

    def test_side_ab_selection_requires_nonempty_integer_arrays(self):
        """A/B 선택은 양쪽의 정수 배열이어야 하며 빈 선택을 사실 표로 처리하지 않는다."""
        policy_a = _make_portfolio_typed(
            self.customer, self.idet, 40000000, portfolio_type=2, monthly=30000)
        policy_b = _make_portfolio_typed(
            self.customer, self.idet, 90000000, portfolio_type=2, monthly=55000)
        unavailable_policy = _make_portfolio_typed(
            self.customer, self.idet, 70000000, portfolio_type=2, monthly=45000)
        unavailable_policy.is_cancelled = True
        unavailable_policy.save(update_fields=['is_cancelled'])

        for selection in (
            {'side_a_ids': [policy_a.id], 'side_b_ids': []},
            {'side_a_ids': [], 'side_b_ids': [policy_b.id]},
            {'side_a_ids': [str(policy_a.id)], 'side_b_ids': [policy_b.id]},
            {'side_a_ids': [policy_a.id, 1.5], 'side_b_ids': [policy_b.id]},
            {'side_a_ids': [policy_a.id, True], 'side_b_ids': [policy_b.id]},
            {'side_a_ids': policy_a.id, 'side_b_ids': [policy_b.id]},
            {'side_a_ids': [policy_a.id]},
            {'side_a_ids': [unavailable_policy.id], 'side_b_ids': [policy_b.id]},
        ):
            response = self.client.post(
                f'/api/v1/customers/{self.customer.id}/compare/',
                selection,
                format='json',
            )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()['code'], 'INVALID_COMPARISON_SELECTION')

    def test_side_ab_selection_rejects_mixed_ineligible_policy_ids(self):
        """한 쪽에 취소 보험이 섞여도 일부만 골라 사실표를 만들지 않는다."""
        policy_a = _make_portfolio_typed(
            self.customer, self.idet, 40000000, portfolio_type=2, monthly=30000)
        policy_b = _make_portfolio_typed(
            self.customer, self.idet, 90000000, portfolio_type=2, monthly=55000)
        canceled = _make_portfolio_typed(
            self.customer, self.idet, 70000000, portfolio_type=2, monthly=45000)
        canceled.is_cancelled = True
        canceled.save(update_fields=['is_cancelled'])

        response = self.client.post(
            f'/api/v1/customers/{self.customer.id}/compare/',
            {'side_a_ids': [policy_a.id, canceled.id], 'side_b_ids': [policy_b.id]},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'INVALID_COMPARISON_SELECTION')

    def test_get_side_ab_selection_accepts_comma_and_repeated_integer_params(self):
        """GET도 문서화된 콤마·반복 A/B 선택을 같은 계약으로 처리한다."""
        policy_a = _make_portfolio_typed(
            self.customer, self.idet, 40000000, portfolio_type=2, monthly=30000)
        policy_b = _make_portfolio_typed(
            self.customer, self.idet, 90000000, portfolio_type=2, monthly=55000)

        response = self.client.get(
            f'/api/v1/customers/{self.customer.id}/compare/'
            f'?side_a_ids={policy_a.id},{policy_a.id}&side_b_ids={policy_b.id}',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['current']['monthly_premiums'], 30000)

        repeated = self.client.get(
            f'/api/v1/customers/{self.customer.id}/compare/'
            f'?side_a_ids={policy_a.id}&side_a_ids={policy_a.id}&side_b_ids={policy_b.id}',
        )
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.json()['current']['monthly_premiums'], 30000)

    def test_get_side_ab_selection_rejects_malformed_or_empty_params(self):
        """GET side 선택도 누락·빈값·문자열 오염 시 legacy 비교로 빠지지 않는다."""
        policy_a = _make_portfolio_typed(
            self.customer, self.idet, 40000000, portfolio_type=2, monthly=30000)
        policy_b = _make_portfolio_typed(
            self.customer, self.idet, 90000000, portfolio_type=2, monthly=55000)

        for query in (
            f'?side_a_ids={policy_a.id}',
            f'?side_a_ids=&side_b_ids={policy_b.id}',
            f'?side_a_ids={policy_a.id},oops&side_b_ids={policy_b.id}',
        ):
            response = self.client.get(
                f'/api/v1/customers/{self.customer.id}/compare/{query}')
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()['code'], 'INVALID_COMPARISON_SELECTION')

    def test_side_ab_selection_deduplicates_each_side(self):
        """같은 보험을 여러 번 보내도 한 번만 집계한다."""
        policy_a = _make_portfolio_typed(
            self.customer, self.idet, 40000000, portfolio_type=2, monthly=30000)
        policy_b = _make_portfolio_typed(
            self.customer, self.idet, 90000000, portfolio_type=2, monthly=55000)

        response = self.client.post(
            f'/api/v1/customers/{self.customer.id}/compare/',
            {'side_a_ids': [policy_a.id, policy_a.id],
             'side_b_ids': [policy_b.id, policy_b.id]},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['current']['monthly_premiums'], 30000)
        self.assertEqual(response.json()['proposed']['monthly_premiums'], 55000)

    def test_side_ab_selection_hides_non_customer_or_unknown_policy_ids(self):
        """다른 고객·다른 소유자·없는 보험 ID는 모두 존재를 알리지 않는 404다."""
        policy_a = _make_portfolio_typed(
            self.customer, self.idet, 40000000, portfolio_type=2, monthly=30000)
        policy_b = _make_portfolio_typed(
            self.customer, self.idet, 90000000, portfolio_type=2, monthly=55000)
        another_customer = Customer.objects.create(owner=self.user, name='다른고객')
        other_customer_policy = _make_portfolio_typed(
            another_customer, self.idet, 70000000, portfolio_type=2, monthly=70000)
        other_user, _ = _make_planner('other-cmp-selection@test.com')
        foreign_customer = Customer.objects.create(owner=other_user, name='남의고객')
        foreign_policy = _make_portfolio_typed(
            foreign_customer, self.idet, 80000000, portfolio_type=2, monthly=80000)

        for invalid_id in (other_customer_policy.id, foreign_policy.id, 999999):
            response = self.client.post(
                f'/api/v1/customers/{self.customer.id}/compare/',
                {'side_a_ids': [policy_a.id], 'side_b_ids': [policy_b.id, invalid_id]},
                format='json',
            )
            self.assertEqual(response.status_code, 404)

    def test_proposal_vs_proposal_no_replacement_warnings(self):
        """제안 vs 제안(교체 아님)엔 면책 리셋·이율 변동 유의사항이 뜨지 않는다(리뷰 major).

        '기존 계약 → 신규 계약 교체'가 아닌데 '면책 다시 시작' 안내가 뜨면 오해를 준다.
        """
        p1 = _make_portfolio_typed(self.customer, self.idet, 40000000, portfolio_type=2, monthly=30000)
        p2 = _make_portfolio_typed(self.customer, self.idet, 90000000, portfolio_type=2, monthly=55000)
        r = self.client.post(
            f'/api/v1/customers/{self.customer.id}/compare/',
            {'side_a_ids': [p1.id], 'side_b_ids': [p2.id]}, format='json')
        types = {w['type'] for w in r.json()['switch_warnings']}
        self.assertNotIn('exemption_reset', types)
        self.assertNotIn('rate_change', types)

    def test_side_ab_ids_owner_isolation(self):
        """다른 설계사 고객의 보험 id는 존재를 알리지 않는 404다."""
        from inpa.accounts.models import Profile, User
        other = User.objects.create_user(email='other-cmp@test.com', password='inpaPass123!')
        other.is_active = True
        other.save(update_fields=['is_active'])
        Profile.objects.get_or_create(user=other)
        other_cust = Customer.objects.create(owner=other, name='남의고객')
        foreign = _make_portfolio_typed(other_cust, self.idet, 77000000, portfolio_type=2, monthly=99000)
        mine = _make_portfolio_typed(self.customer, self.idet, 40000000, portfolio_type=2, monthly=30000)
        r = self.client.post(
            f'/api/v1/customers/{self.customer.id}/compare/',
            {'side_a_ids': [mine.id], 'side_b_ids': [foreign.id]}, format='json')
        self.assertEqual(r.status_code, 404)

    def test_side_ab_ids_take_priority_over_legacy_params(self):
        """side_a_ids/side_b_ids 가 오면 current_ids/proposed_ids 는 무시된다(신규 우선)."""
        h1 = _make_portfolio_typed(self.customer, self.idet, 50000000, portfolio_type=1, monthly=40000)
        p1 = _make_portfolio_typed(self.customer, self.idet, 100000000, portfolio_type=2, monthly=60000)
        p2 = _make_portfolio_typed(self.customer, self.idet, 80000000, portfolio_type=2, monthly=50000)
        r = self.client.post(
            f'/api/v1/customers/{self.customer.id}/compare/',
            {'side_a_ids': [p1.id], 'side_b_ids': [p2.id], 'current_ids': [h1.id]}, format='json')
        body = r.json()
        # side_a=p1(제안, 월 6만) → current 자리에 실린다. current_ids(h1)는 무시.
        self.assertEqual(body['current']['monthly_premiums'], 60000)
        self.assertEqual(body['proposed']['monthly_premiums'], 50000)

    def test_no_side_params_backward_compat_portfolio_split(self):
        """side_a_ids/side_b_ids 도, current_ids/proposed_ids 도 없으면 기존 동작(보유/제안 분리)."""
        _make_portfolio_typed(self.customer, self.idet, 50000000, portfolio_type=1, monthly=40000)
        _make_portfolio_typed(self.customer, self.idet, 100000000, portfolio_type=2, monthly=60000)
        body = self._get().json()
        self.assertEqual(body['current']['monthly_premiums'], 40000)
        self.assertEqual(body['proposed']['monthly_premiums'], 60000)


class CompareAiGateTests(TestCase):
    """AI 비교안내서 초안 — COMPARE_AI_ENABLED=True 일 때만 생성(Claude mock)."""

    def setUp(self):
        self.user, self.client = _make_planner('compare-ai@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='AI고객', birth_day='1990.01.01', gender=1)
        self.det = _build_std_tree()
        self.idet = _catalog_detail_linked_to(self.det)
        _make_portfolio_typed(self.customer, self.idet, 50000000, portfolio_type=1)
        _make_portfolio_typed(self.customer, self.idet, 100000000, portfolio_type=2)

    @override_settings(COMPARE_AI_ENABLED=True)
    @mock.patch('inpa.analysis.compare._generate_guide_draft')
    def test_ai_enabled_returns_guide(self, mock_gen):
        """게이트 ON + Claude 성공(mock) → guide_draft 채워지고 guide_enabled=true."""
        mock_gen.return_value = ('§97 6요건 초안 본문', {'input_tokens': 10,
                                                       'output_tokens': 20})
        body = self.client.get(
            f'/api/v1/customers/{self.customer.id}/compare/').json()
        self.assertEqual(body['guide_draft'], '§97 6요건 초안 본문')
        self.assertTrue(body['guide_enabled'])
        self.assertEqual(body['comparison_source'], 'deterministic')
        self.assertEqual(body['guide_source'], 'ai')
        mock_gen.assert_called_once()

    @override_settings(COMPARE_AI_ENABLED=True)
    @mock.patch('inpa.analysis.compare._generate_guide_draft')
    def test_ai_enabled_but_claude_fails_guide_null(self, mock_gen):
        """게이트 ON 이어도 Claude 실패(None) → guide null (비교표는 그대로 동작)."""
        mock_gen.return_value = (None, None)
        body = self.client.get(
            f'/api/v1/customers/{self.customer.id}/compare/').json()
        self.assertIsNone(body['guide_draft'])
        self.assertFalse(body['guide_enabled'])
        self.assertEqual(body['comparison_source'], 'deterministic')
        self.assertIsNone(body['guide_source'])
        # 비교표(사실)는 여전히 존재
        self.assertTrue(any(x['coverage'] == '사망보장' for x in body['rows']))


class ComparePublishHardblockTests(TestCase):
    """★ 발행 하드블록 — COMPARE_PUBLISH_ENABLED=False → 403, publishable 항상 false."""

    def setUp(self):
        self.user, self.client = _make_planner('compare-pub@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='발행고객', birth_day='1990.01.01')

    @override_settings(COMPARE_PUBLISH_ENABLED=False)
    def test_publish_blocked_403(self):
        r = self.client.post(
            f'/api/v1/customers/{self.customer.id}/compare/publish/')
        self.assertEqual(r.status_code, 403)
        body = r.json()
        self.assertFalse(body['publishable'])
        self.assertEqual(body['publish_blocked_reason'], '법무 검토 완료 전 발행 금지')


class CompareOwnerIsolationTests(TestCase):
    """★ owner 격리 — A는 B 고객의 compare/publish 에 접근 불가(404)."""

    def setUp(self):
        self.user_a, self.client_a = _make_planner('a@compare.com')
        self.user_b, self.client_b = _make_planner('b@compare.com')
        self.cust_b = Customer.objects.create(
            owner=self.user_b, name='B고객', birth_day='1988.08.08')
        det = _build_std_tree()
        idet = _catalog_detail_linked_to(det)
        _make_portfolio_typed(self.cust_b, idet, 70000000, portfolio_type=1)

    def test_a_cannot_get_b_compare(self):
        r = self.client_a.get(f'/api/v1/customers/{self.cust_b.id}/compare/')
        self.assertEqual(r.status_code, 404)

    def test_a_cannot_publish_b_compare(self):
        r = self.client_a.post(
            f'/api/v1/customers/{self.cust_b.id}/compare/publish/')
        self.assertEqual(r.status_code, 404)

    def test_owner_can_get_own_compare(self):
        r = self.client_b.get(f'/api/v1/customers/{self.cust_b.id}/compare/')
        self.assertEqual(r.status_code, 200)

    def test_unauthenticated_blocked(self):
        c = APIClient()
        r = c.get(f'/api/v1/customers/{self.cust_b.id}/compare/')
        self.assertEqual(r.status_code, 401)


class CompareRenewalSplitTests(TestCase):
    """비교분석 응답에 갱신/비갱신 분리 + 보험별 요금 포함."""

    def setUp(self):
        self.user, self.client = _make_planner('cmp@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='김보장', birth_day='1990.01.01', gender=1)
        self.det = _build_std_tree()
        self.idet = _catalog_detail_linked_to(self.det)

        # 보유 보험A: 담보 케이스 비갱신(1) + 갱신(3)
        # 비갱신 케이스: premium=10000, 갱신 케이스: premium=20000
        self.ci_cur = CustomerInsurance.objects.create(
            customer=self.customer, name='보유A', insurance_type=2, portfolio_type=1,
            payment_period_type=1, payment_period=20,
            monthly_premiums=30000, monthly_assurance_premium=30000,
            monthly_earned_premium=0)
        # 비갱신 케이스
        CustomerInsuranceDetail.objects.create(
            insurance=self.ci_cur, detail=self.idet,
            assurance_amount=30000000, premium=10000,
            payment_period_type=1, payment_period=20,
            warranty_period_type=1, warranty_period='100',
        )
        # 갱신 케이스
        CustomerInsuranceDetail.objects.create(
            insurance=self.ci_cur, detail=self.idet,
            assurance_amount=20000000, premium=20000,
            payment_period_type=3, payment_period=20,
            warranty_period_type=1, warranty_period='100',
        )
        self.ci_cur.set_renewal_month()
        self.ci_cur.calculate()
        self.ci_cur.save()

        # 제안 보험B: 비갱신(1) 케이스만
        self.ci_prop = CustomerInsurance.objects.create(
            customer=self.customer, name='제안B', insurance_type=2, portfolio_type=2,
            payment_period_type=1, payment_period=20,
            monthly_premiums=30000, monthly_assurance_premium=30000,
            monthly_earned_premium=0)
        # 비갱신 케이스
        CustomerInsuranceDetail.objects.create(
            insurance=self.ci_prop, detail=self.idet,
            assurance_amount=30000000, premium=30000,
            payment_period_type=1, payment_period=20,
            warranty_period_type=1, warranty_period='100',
        )
        self.ci_prop.set_renewal_month()
        self.ci_prop.calculate()
        self.ci_prop.save()

    def test_compare_sides_carry_renewal_split_and_insurances(self):
        """비교분석 응답의 current/proposed 에 갱신/비갱신/적립 분리 + insurances 배열 포함."""
        r = self.client.post(f'/api/v1/customers/{self.customer.id}/compare/', {}, format='json')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        cur = body['current']
        prop = body['proposed']

        # 갱신/비갱신 분리 검증 (calculate()에 의해 자동 계산됨)
        self.assertIn('monthly_renewal_premium', cur)
        self.assertIn('monthly_non_renewal_premium', cur)
        self.assertIn('monthly_earned_premium', cur)
        self.assertIn('total_renewal_premium', cur)
        self.assertIn('total_non_renewal_premium', cur)
        self.assertIn('total_earned_premium', cur)

        # insurances 배열 검증
        self.assertIn('insurances', cur)
        self.assertIn('insurances', prop)
        self.assertEqual(len(cur['insurances']), 1)
        self.assertEqual(len(prop['insurances']), 1)

        # 첫 번째 insurances 요소 검증
        cur_ins = cur['insurances'][0]
        self.assertEqual(cur_ins['name'], '보유A')
        self.assertIn('case_fees', cur_ins)
        self.assertIn('monthly_renewal_premium', cur_ins)
        self.assertEqual(cur_ins['monthly_renewal_premium'], 20000)

        prop_ins = prop['insurances'][0]
        self.assertEqual(prop_ins['name'], '제안B')
        self.assertIn('case_fees', prop_ins)
        # 제안B는 비갱신만 있으므로
        self.assertEqual(prop_ins['monthly_non_renewal_premium'], 30000)

    def test_manual_insurance_renewal_fields_become_none(self):
        """수기 입력 보험(케이스 없음): monthly_premiums=50000 있으나,
        월갱신보험료=None 인 경우, 집계 후 응답의 monthly_renewal_premium=None (0 아님).
        ★ "알려지지 않음"(None) vs "0"(알려진 영)을 구분 → 거짓 방지."""
        # 별도 고객 생성 (setUp의 ci_cur/ci_prop와 격리)
        manual_cust = Customer.objects.create(
            owner=self.user, name='수기고객', birth_day='1990.01.01', gender=1)

        # 수기 입력 보험 1건: monthly_premiums=50000 설정, 갱신 분리 필드는 None 유지
        ci = CustomerInsurance.objects.create(
            customer=manual_cust, name='수기입력', insurance_type=2, portfolio_type=1,
            payment_period_type=1, payment_period=20,
            monthly_premiums=50000, monthly_assurance_premium=50000,
            # ★ 아래 필드들은 명시적으로 None (calculate() 안 함)
            monthly_renewal_premium=None,
            monthly_non_renewal_premium=None,
            monthly_earned_premium=None,
            total_premiums=50000,
            total_renewal_premium=None,
            total_non_renewal_premium=None,
            total_earned_premium=None,
        )
        # ★ 케이스 추가 안 함 (case_list 빔)

        # 비교 요청
        r = self.client.post(f'/api/v1/customers/{manual_cust.id}/compare/', {}, format='json')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        current = body['current']

        # ★ 핵심: monthly_premiums=50000 (알려진 값), 하지만 갱신 필드는 None (미상)
        self.assertEqual(current['monthly_premiums'], 50000)
        self.assertIsNone(current['monthly_renewal_premium'],
                         msg='갱신분리 미상이면 0 아닌 None')
        self.assertIsNone(current['monthly_non_renewal_premium'])
        self.assertIsNone(current['monthly_earned_premium'])
        self.assertEqual(current['total_premiums'], 50000)
        self.assertIsNone(current['total_renewal_premium'])
        self.assertIsNone(current['total_non_renewal_premium'])
        self.assertIsNone(current['total_earned_premium'])


class HeatmapInsurancesTests(TestCase):
    """히트맵 응답이 보험별 요금(insurances)을 담아 보낸다."""

    def setUp(self):
        self.user, self.client = _make_planner('hm@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='김보장', birth_day='1990.01.01')
        self.ci = CustomerInsurance.objects.create(
            customer=self.customer, name='보험A', insurance_type=2, portfolio_type=1,
            payment_period_type=1, payment_period=20,
            monthly_premiums=30000, monthly_assurance_premium=30000)
        # 담보 케이스 추가 (InsuranceFeeSerializer 가 case_list 에서 case_fees 추출)
        det = _build_std_tree()
        idet = _catalog_detail_linked_to(det)
        CustomerInsuranceDetail.objects.create(
            insurance=self.ci, detail=idet,
            assurance_amount=100000000, premium=30000,
            payment_period_type=1, payment_period=20,
            warranty_period_type=1, warranty_period='100',
        )
        self.ci.set_renewal_month()
        self.ci.calculate()
        self.ci.save()

    def test_heatmap_includes_insurances_with_split(self):
        """히트맵 응답에 insurances 배열이 있고, 각 보험이 monthly_renewal_premium 및 case_fees 포함."""
        r = self.client.get(f'/api/v1/customers/{self.customer.id}/heatmap/')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn('insurances', body)
        self.assertEqual(len(body['insurances']), 1)
        # 보험 요금 필드 검증
        insurance = body['insurances'][0]
        self.assertEqual(insurance['id'], self.ci.id)
        self.assertEqual(insurance['name'], '보험A')
        self.assertIn('monthly_renewal_premium', insurance)
        self.assertIn('case_fees', insurance)
        self.assertEqual(insurance['review_status'], 'legacy_review_required')
        self.assertFalse(insurance['analysis_included'])
        self.assertIsNone(insurance['confirmed_at'])
        # case_fees 는 배열 (담보별 요금)
        self.assertIsInstance(insurance['case_fees'], list)
        self.assertEqual(len(insurance['case_fees']), 1)


class HeatmapInsuranceFilterTests(TestCase):
    """?insurance_id= 보험별 필터 — 해당 보험 case_list 만 집계 + owner 격리(404).

    스펙(2026-07-07 analysis-insurance-cards): 파라미터 없으면 기존 전체 합산 그대로,
    주어지면 그 보험의 트리/summary 만. 남의/다른 고객/없는/형식 오류 id 전부 404.
    """

    def setUp(self):
        self.user, self.client = _make_planner('filter@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='필터고객', birth_day='1990.01.01')
        # 표준 담보 2종: 사망보장 / 암진단 (같은 서브카테고리)
        self.det_death = _build_std_tree()
        sub = self.det_death.sub_category
        self.det_cancer = AnalysisDetail.objects.create(
            sub_category=sub, name='암진단', order=2)
        # 카탈로그 담보 2종 → 각각 표준 담보 1개에 연결
        self.idet_death = _catalog_detail_linked_to(self.det_death)
        icat = InsuranceCategory.objects.create(insurance_type=2, name='손보상품2', order=2)
        isub = InsuranceSubCategory.objects.create(
            insurance_type=2, category=icat, name='보장2', order=1)
        self.idet_cancer = InsuranceDetail.objects.create(
            sub_category=isub, name='암담보', order=1)
        self.idet_cancer.analysis_detail.add(self.det_cancer)
        # 보험 A(사망보장 1억, 월 3만) / 보험 B(암진단 3천만, 월 5만)
        self.ci_a = self._make_ins('보험A', 30000, self.idet_death, 100000000)
        self.ci_b = self._make_ins('보험B', 50000, self.idet_cancer, 30000000)

    def _make_ins(self, name, monthly, catalog_detail, amount):
        ci = CustomerInsurance.objects.create(
            customer=self.customer, insurance_type=2, name=name,
            portfolio_type=1, payment_period_type=1, payment_period=20,
            monthly_premiums=monthly, monthly_assurance_premium=monthly)
        CustomerInsuranceDetail.objects.create(
            insurance=ci, detail=catalog_detail,
            assurance_amount=amount, premium=10000,
            payment_period_type=1, payment_period=20,
            warranty_period_type=1, warranty_period='100')
        ci.set_renewal_month()
        ci.calculate()
        ci.save()
        return ci

    def _get(self, insurance_id=None):
        url = f'/api/v1/customers/{self.customer.id}/heatmap/'
        if insurance_id is not None:
            url += f'?insurance_id={insurance_id}'
        return self.client.get(url)

    def _held(self, body):
        """트리에서 담보명 → held_amount 맵."""
        held = {}
        for cat in body['tree']:
            for sub in cat['sub_categories']:
                for det in sub['details']:
                    held[det['name']] = det['held_amount']
        return held

    def test_filter_by_each_insurance_splits_tree_and_summary(self):
        """각 id 로 조회하면 트리는 해당 보험 담보만, summary 도 해당 보험 수치만."""
        r = self._get(self.ci_a.id)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        held = self._held(body)
        self.assertEqual(held['사망보장'], 100000000)
        self.assertEqual(held['암진단'], 0)
        self.assertEqual(body['summary']['monthly_premiums'], 30000)
        self.assertEqual(body['insurance_count'], 1)
        self.assertEqual([i['id'] for i in body['insurances']], [self.ci_a.id])

        r = self._get(self.ci_b.id)
        body = r.json()
        held = self._held(body)
        self.assertEqual(held['사망보장'], 0)
        self.assertEqual(held['암진단'], 30000000)
        self.assertEqual(body['summary']['monthly_premiums'], 50000)
        self.assertEqual([i['id'] for i in body['insurances']], [self.ci_b.id])

    def test_no_param_keeps_full_aggregation(self):
        """파라미터 없음 = 기존 전체 합산 그대로(하위호환)."""
        r = self._get()
        self.assertEqual(r.status_code, 200)
        body = r.json()
        held = self._held(body)
        self.assertEqual(held['사망보장'], 100000000)
        self.assertEqual(held['암진단'], 30000000)
        self.assertEqual(body['summary']['monthly_premiums'], 80000)
        self.assertEqual(body['insurance_count'], 2)

    def test_other_owners_insurance_id_404(self):
        """남의 보험 id 를 내 고객 heatmap 에 붙여도 404(존재 은폐)."""
        other, _ = _make_planner('other@filter.com')
        other_cust = Customer.objects.create(
            owner=other, name='남의고객', birth_day='1980.01.01')
        other_ci = CustomerInsurance.objects.create(
            customer=other_cust, insurance_type=2, name='남의보험',
            portfolio_type=1, payment_period_type=1, payment_period=20,
            monthly_premiums=10000, monthly_assurance_premium=10000)
        r = self._get(other_ci.id)
        self.assertEqual(r.status_code, 404)

    def test_same_owner_other_customer_insurance_404(self):
        """같은 설계사의 다른 고객 보험 id 도 이 고객 heatmap 에선 404."""
        cust2 = Customer.objects.create(
            owner=self.user, name='둘째고객', birth_day='1992.02.02')
        ci2 = CustomerInsurance.objects.create(
            customer=cust2, insurance_type=2, name='둘째보험',
            portfolio_type=1, payment_period_type=1, payment_period=20,
            monthly_premiums=10000, monthly_assurance_premium=10000)
        r = self._get(ci2.id)
        self.assertEqual(r.status_code, 404)

    def test_unknown_or_malformed_id_404(self):
        self.assertEqual(self._get(9999999).status_code, 404)
        self.assertEqual(self._get('abc').status_code, 404)


@override_settings(INSURANCE_REVIEW_GATE_ENABLED=True)
class AnalysisEligibilityGateTests(TestCase):
    """검토 게이트가 열리면 확인·포함·정상 보험만 서버 집계에 들어간다."""

    def setUp(self):
        self.user, self.client = _make_planner('eligibility@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='검토고객', birth_day='1990.01.01')
        self.standard = _build_std_tree()
        self.catalog = _catalog_detail_linked_to(self.standard)
        self.confirmed_at = timezone.now() - timezone.timedelta(hours=1)
        self.included = self._make(
            '확인보험', 10000000, review_status='confirmed',
            analysis_included=True, confirmed_at=self.confirmed_at)
        self._make('기존보험', 20000000, review_status='legacy_review_required')
        self._make('제외보험', 30000000, review_status='excluded')
        self._make(
            '포함해제보험', 40000000, review_status='confirmed',
            analysis_included=False, confirmed_at=timezone.now())
        self._make(
            '교체보험', 50000000, review_status='superseded',
            analysis_included=True, confirmed_at=timezone.now())
        self._make(
            '해지보험', 60000000, review_status='confirmed',
            analysis_included=True, confirmed_at=timezone.now(),
            is_cancelled=True)

    def _make(self, name, amount, **fields):
        ci = CustomerInsurance.objects.create(
            customer=self.customer, insurance_type=2, name=name,
            portfolio_type=1, payment_period_type=1, payment_period=20,
            monthly_premiums=amount // 1000,
            monthly_assurance_premium=amount // 1000,
            **fields)
        CustomerInsuranceDetail.objects.create(
            insurance=ci, detail=self.catalog, assurance_amount=amount,
            premium=1000, payment_period_type=1, payment_period=20,
            warranty_period_type=1, warranty_period='100')
        ci.set_renewal_month()
        ci.calculate()
        ci.save()
        return ci

    def _get(self, suffix=''):
        return self.client.get(
            f'/api/v1/customers/{self.customer.id}/heatmap/{suffix}')

    def test_gate_on_includes_only_confirmed_included_active_insurance(self):
        response = self._get()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        held = body['tree'][0]['sub_categories'][0]['details'][0]['held_amount']
        self.assertEqual(held, 10000000)
        self.assertEqual(body['insurance_count'], 1)
        self.assertEqual(body['included_insurance_count'], 1)
        self.assertEqual(body['excluded_insurance_count'], 5)
        self.assertEqual(body['pending_review_count'], 1)
        self.assertEqual(body['last_confirmed_at'], self.confirmed_at.isoformat())
        self.assertFalse(body['can_share'])
        self.assertEqual(
            body['share_block_reason'],
            '확인할 보험 내용을 마치면 바로 공유할 수 있어요.')

    def test_mixed_coverage_premiums_hide_partial_composition_not_coverage(self):
        CustomerInsuranceDetail.objects.create(
            insurance=self.included,
            detail=self.catalog,
            assurance_amount=5_000_000,
            premium=None,
            payment_period_type=1,
            payment_period=20,
            warranty_period_type=1,
            warranty_period='100',
        )

        response = self._get()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        detail = body['tree'][0]['sub_categories'][0]['details'][0]
        self.assertEqual(detail['held_amount'], 15_000_000)
        self.assertEqual(body['insurance_count'], 1)
        self.assertEqual(body['summary']['monthly_premiums'], 10_000)
        for field in (
                'monthly_renewal_premium',
                'monthly_non_renewal_premium',
                'total_premiums',
                'total_renewal_premium',
                'total_non_renewal_premium'):
            self.assertIsNone(body['summary'][field], field)
            self.assertIsNone(body['insurances'][0][field], field)
        self.assertIsNone(body['summary']['total_pay_insurance_premium'])
        self.assertEqual(
            sorted(
                fee['premium']
                for fee in body['insurances'][0]['case_fees']
                if fee['premium'] is not None),
            [1_000],
        )
        self.assertEqual(
            sum(
                fee['premium'] is None
                for fee in body['insurances'][0]['case_fees']),
            1,
        )

        compare = self.client.post(
            f'/api/v1/customers/{self.customer.id}/compare/',
            {},
            format='json',
        )
        self.assertEqual(compare.status_code, 200)
        current = compare.json()['current']
        self.assertEqual(current['monthly_premiums'], 10_000)
        for field in (
                'monthly_renewal_premium',
                'monthly_non_renewal_premium',
                'total_premiums',
                'total_renewal_premium',
                'total_non_renewal_premium'):
            self.assertIsNone(current[field], field)

    def test_contributions_use_only_exact_ready_held_portfolio(self):
        included_case = self.included.case_list.get()
        included_case.raw_name = '확인한 원문 담보'
        included_case.source_page = 4
        included_case.source_text_masked = '응답에 포함하지 않을 합성 근거'
        included_case.evidence_line_ids = ['synthetic-evidence']
        included_case.source_candidate_ids = ['synthetic-candidate']
        included_case.save(update_fields=(
            'raw_name', 'source_page', 'source_text_masked',
            'evidence_line_ids', 'source_candidate_ids'))
        proposal = self._make(
            '확인제안', 70000000, review_status='confirmed',
            analysis_included=True, confirmed_at=timezone.now())
        proposal.portfolio_type = 2
        proposal.save(update_fields=['portfolio_type'])
        foreign_user, _ = _make_planner('contribution-foreign@test.com')
        foreign_customer = Customer.objects.create(
            owner=foreign_user, name='다른 고객', birth_day='1980.01.01')
        foreign_insurance = CustomerInsurance.objects.create(
            customer=foreign_customer, insurance_type=2, name='다른 보험',
            portfolio_type=1, review_status='confirmed',
            analysis_included=True, confirmed_at=timezone.now())
        CustomerInsuranceDetail.objects.create(
            insurance=foreign_insurance, detail=self.catalog,
            raw_name='다른 고객 담보', assurance_amount=80_000_000,
            payment_period_type=1, payment_period=20,
            warranty_period_type=1, warranty_period='100')

        body = self._get().json()
        detail = body['tree'][0]['sub_categories'][0]['details'][0]

        self.assertEqual(detail['held_amount'], 10_000_000)
        self.assertEqual(len(detail['contributions']), 1)
        contribution = detail['contributions'][0]
        self.assertEqual(set(contribution), {
            'case_id', 'insurance_id', 'insurance_name', 'raw_name',
            'assurance_amount', 'source_page', 'mapping_source',
        })
        self.assertEqual(contribution, {
            'case_id': included_case.pk,
            'insurance_id': self.included.pk,
            'insurance_name': '확인보험',
            'raw_name': '확인한 원문 담보',
            'assurance_amount': 10_000_000,
            'source_page': 4,
            'mapping_source': 'global',
        })
        self.assertEqual(
            sum(row['assurance_amount']
                for row in detail['contributions']),
            detail['held_amount'])
        serialized = str(detail['contributions'])
        for forbidden in (
                'source_text_masked', 'evidence_line_ids',
                'source_candidate_ids', 'file_name', 'capability',
                '다른 고객 담보'):
            self.assertNotIn(forbidden, serialized)

    def test_excluded_canceled_and_superseded_do_not_block_after_pending_is_resolved(self):
        legacy = self.customer.customer_insurance_list.get(name='기존보험')
        legacy.review_status = 'excluded'
        legacy.analysis_included = False
        legacy.save(update_fields=('review_status', 'analysis_included'))
        body = self._get().json()
        self.assertEqual(body['pending_review_count'], 0)
        self.assertTrue(body['can_share'])
        self.assertIsNone(body['share_block_reason'])

    def test_unconfirmed_insurance_id_is_hidden(self):
        legacy = self.customer.customer_insurance_list.get(name='기존보험')
        response = self._get(f'?insurance_id={legacy.id}')
        self.assertEqual(response.status_code, 404)

    def test_share_status_guides_next_confirmation_when_nothing_is_included(self):
        self.included.analysis_included = False
        self.included.save(update_fields=['analysis_included'])
        body = self._get().json()
        self.assertFalse(body['can_share'])
        self.assertEqual(
            body['share_block_reason'],
            '확인할 보험 내용을 마치면 바로 공유할 수 있어요.')

    @override_settings(INSURANCE_REVIEW_GATE_ENABLED=False)
    def test_gate_off_preserves_legacy_but_never_includes_explicit_exclusions(self):
        response = self._get()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        held = body['tree'][0]['sub_categories'][0]['details'][0]['held_amount']
        # Gate OFF는 기존 자료만 보존한다. 명시적 제외와 포함 해제는
        # 검토 기능 활성화 여부와 관계없이 분석에 들어가지 않는다.
        self.assertEqual(held, 10000000 + 20000000)

    def test_compare_uses_same_analysis_ready_authority(self):
        proposed = self._make(
            '확인제안', 70000000, review_status='confirmed',
            analysis_included=True, confirmed_at=timezone.now())
        proposed.portfolio_type = 2
        proposed.save(update_fields=['portfolio_type'])
        response = self.client.post(
            f'/api/v1/customers/{self.customer.id}/compare/',
            {'side_a_ids': [self.included.id],
             'side_b_ids': [proposed.id]},
            format='json')
        self.assertEqual(response.status_code, 200)
        row = next(item for item in response.json()['rows']
                   if item['coverage'] == '사망보장')
        self.assertEqual(row['current_amount'], 10000000)
        self.assertEqual(row['proposed_amount'], 70000000)


@override_settings(INSURANCE_REVIEW_GATE_ENABLED=True)
class CaseMappingOverrideTests(TestCase):
    """한 고객의 개별 매핑 변경은 다른 고객과 전역 담보 사전에 전파되지 않는다."""

    def setUp(self):
        self.user, self.client = _make_planner('override@test.com')
        self.customer_a = Customer.objects.create(
            owner=self.user, name='A고객', birth_day='1990.01.01')
        self.customer_b = Customer.objects.create(
            owner=self.user, name='B고객', birth_day='1990.01.01')
        self.global_detail = _build_std_tree()
        self.override_detail = AnalysisDetail.objects.create(
            sub_category=self.global_detail.sub_category, name='개별담보', order=2)
        self.catalog = _catalog_detail_linked_to(self.global_detail)
        self.insurance_a, self.case_a = self._make(self.customer_a)
        self.insurance_b, self.case_b = self._make(self.customer_b)
        self.case_a.mapping_source = 'planner_override'
        self.case_a.save(update_fields=['mapping_source'])
        self.case_a.analysis_detail_override.add(self.override_detail)

    def _make(self, customer):
        ci = CustomerInsurance.objects.create(
            customer=customer, insurance_type=2, name='공유담보보험',
            portfolio_type=1, payment_period_type=1, payment_period=20,
            monthly_premiums=30000, monthly_assurance_premium=30000,
            review_status='confirmed', analysis_included=True,
            confirmed_at=timezone.now())
        case = CustomerInsuranceDetail.objects.create(
            insurance=ci, detail=self.catalog, assurance_amount=50000000,
            premium=1000, payment_period_type=1, payment_period=20,
            warranty_period_type=1, warranty_period='100')
        ci.set_renewal_month()
        ci.calculate()
        ci.save()
        return ci, case

    @staticmethod
    def _held(body):
        return {
            detail['name']: detail['held_amount']
            for category in body['tree']
            for sub in category['sub_categories']
            for detail in sub['details']
        }

    def test_heatmap_uses_case_override_without_mutating_global_mapping(self):
        a = self.client.get(
            f'/api/v1/customers/{self.customer_a.id}/heatmap/').json()
        b = self.client.get(
            f'/api/v1/customers/{self.customer_b.id}/heatmap/').json()
        self.assertEqual(self._held(a)['개별담보'], 50000000)
        self.assertEqual(self._held(a)['사망보장'], 0)
        self.assertEqual(self._held(b)['개별담보'], 0)
        self.assertEqual(self._held(b)['사망보장'], 50000000)
        self.assertEqual(
            list(self.catalog.analysis_detail.values_list('id', flat=True)),
            [self.global_detail.id])

    def test_contribution_uses_effective_case_local_override(self):
        self.case_a.raw_name = '설계사가 바꾼 담보'
        self.case_a.source_page = 2
        self.case_a.save(update_fields=['raw_name', 'source_page'])

        body = self.client.get(
            f'/api/v1/customers/{self.customer_a.id}/heatmap/').json()
        details = {
            detail['name']: detail
            for category in body['tree']
            for sub in category['sub_categories']
            for detail in sub['details']
        }

        self.assertEqual(details['사망보장']['contributions'], [])
        self.assertEqual(details['개별담보']['contributions'], [{
            'case_id': self.case_a.pk,
            'insurance_id': self.insurance_a.pk,
            'insurance_name': '공유담보보험',
            'raw_name': '설계사가 바꾼 담보',
            'assurance_amount': 50_000_000,
            'source_page': 2,
            'mapping_source': 'planner_override',
        }])

    def test_contribution_preserves_manual_mapping_source(self):
        self.case_a.mapping_source = 'manual'
        self.case_a.save(update_fields=['mapping_source'])

        body = self.client.get(
            f'/api/v1/customers/{self.customer_a.id}/heatmap/').json()
        details = {
            detail['name']: detail
            for category in body['tree']
            for sub in category['sub_categories']
            for detail in sub['details']
        }

        contribution = details['개별담보']['contributions'][0]
        self.assertEqual(contribution['mapping_source'], 'manual')
        self.assertEqual(
            sum(row['assurance_amount']
                for row in details['개별담보']['contributions']),
            details['개별담보']['held_amount'])

    def test_compare_and_share_use_same_effective_mapping(self):
        compare = self.client.post(
            f'/api/v1/customers/{self.customer_a.id}/compare/',
            {'side_a_ids': [self.insurance_a.id], 'side_b_ids': [self.insurance_a.id]},
            format='json').json()
        self.assertEqual(
            [(row['coverage'], row['current_amount']) for row in compare['rows']],
            [('개별담보', 50000000)])

        from inpa.analytics.views import _build_share_payload
        share = _build_share_payload(self.customer_a)
        self.assertEqual(self._held(share)['개별담보'], 50000000)
        self.assertEqual(self._held(share)['사망보장'], 0)

    def test_empty_override_does_not_fall_back_to_global_catalog_name(self):
        self.case_a.analysis_detail_override.clear()
        compare = self.client.post(
            f'/api/v1/customers/{self.customer_a.id}/compare/',
            {'side_a_ids': [self.insurance_a.id], 'side_b_ids': [self.insurance_a.id]},
            format='json').json()
        self.assertEqual(compare['rows'], [])


# ══════════════════════════════════════════════════════════════════════
# LB-1 시드 안전화 — identity-true upsert + 버전 마커 + 고아/prune + 손상 복구
# ══════════════════════════════════════════════════════════════════════
import copy
from io import StringIO

from django.core.management import call_command

from inpa.analysis.management.commands import seed_normalization as seed_norm_mod
from inpa.analysis.models import NormalizationDict, SeedMarker


def _std_leaf(name):
    return AnalysisDetail.objects.get(
        name=name, sub_category__category__name__startswith='[표준]')


class SeedNormalizationUpsertTests(TestCase):
    """재실행 안전: PK 보존 → M2M 링크·admin_verified 행 생존, 카운트 불변."""

    def test_seed_creates_idempotent_standard_compatibility_catalog(self):
        legacy_category = InsuranceCategory.objects.create(
            insurance_type=2, name='진단-암', order=99)
        legacy_subcategory = InsuranceSubCategory.objects.create(
            insurance_type=2, category=legacy_category,
            name='일반암', order=99)
        legacy_detail = InsuranceDetail.objects.create(
            sub_category=legacy_subcategory,
            name='일반암진단비', order=99)

        call_command('seed_normalization', stdout=StringIO())

        category = InsuranceCategory.objects.get(name='[표준]진단-암')
        subcategory = InsuranceSubCategory.objects.get(
            category=category, name='일반암')
        detail = InsuranceDetail.objects.get(
            sub_category=subcategory, name='일반암진단비')
        self.assertFalse(detail.analysis_detail.exists())

        from inpa.insurances.import_services import (
            _catalog_detail_for_override,
        )
        resolved = _catalog_detail_for_override({
            'standard_category': '진단-암',
            'standard_subcategory': '일반암',
            'standard_detail_name': '일반암진단비',
        }, insurance_type=2)
        self.assertEqual(resolved.pk, detail.pk)

        category_pk = category.pk
        subcategory_pk = subcategory.pk
        detail_pk = detail.pk
        call_command('seed_normalization', '--force', stdout=StringIO())
        self.assertEqual(
            InsuranceCategory.objects.get(name='[표준]진단-암').pk,
            category_pk)
        self.assertEqual(
            InsuranceSubCategory.objects.get(
                category_id=category_pk, name='일반암').pk,
            subcategory_pk)
        self.assertEqual(
            InsuranceDetail.objects.get(
                sub_category_id=subcategory_pk, name='일반암진단비').pk,
            detail_pk)
        legacy_detail.refresh_from_db()
        self.assertEqual(legacy_detail.order, 99)

    def test_standard_compatibility_catalog_matches_all_standard_paths(self):
        call_command('seed_normalization', stdout=StringIO())

        expected_paths = {
            (f'[표준]{category}', subcategory, detail)
            for category, _insurance_type, subcategories
            in seed_norm_mod.STANDARD_TREE
            for subcategory, details in subcategories
            for detail, _amount in details
        }
        actual_paths = {
            (
                detail.sub_category.category.name,
                detail.sub_category.name,
                detail.name,
            )
            for detail in InsuranceDetail.objects.filter(
                sub_category__category__name__startswith='[표준]'
            ).select_related('sub_category__category')
        }

        self.assertEqual(len(expected_paths), 57)
        self.assertEqual(actual_paths, expected_paths)
        self.assertFalse(
            InsuranceDetail.objects.filter(
                sub_category__category__name__startswith='[표준]',
                analysis_detail__isnull=False,
            ).exists()
        )

    def test_reseed_preserves_pk_m2m_and_admin_rows(self):
        call_command('seed_normalization', stdout=StringIO())
        leaf = _std_leaf('일반암진단비')

        # 스캔 저장 상태 재현: 카탈로그 담보 → 표준 leaf M2M + 고객 케이스
        user, _ = _make_planner('reseed@test.com')
        customer = Customer.objects.create(
            owner=user, name='재시드고객', birth_day='1990.01.01')
        icat = InsuranceCategory.objects.create(
            insurance_type=2, name='진단비', order=1)
        isub = InsuranceSubCategory.objects.create(
            insurance_type=2, category=icat, name='암', order=1)
        idet = InsuranceDetail.objects.create(
            sub_category=isub, name='일반암', order=1)
        idet.analysis_detail.add(leaf)
        _make_portfolio(customer, idet, assurance_amount=50000000)

        # 관리자 검수 정규화 행 (어떤 코드 경로에서도 불변이어야 함)
        admin_row = NormalizationDict.objects.create(
            std_detail=leaf, company=1, raw_name='검수된커스텀암진단',
            source=NormalizationDict.SOURCE_ADMIN_VERIFIED, confidence=100)

        det_before = AnalysisDetail.objects.filter(
            sub_category__category__name__startswith='[표준]').count()
        dict_before = NormalizationDict.objects.count()

        call_command('seed_normalization', '--force', stdout=StringIO())

        # leaf PK 불변 → M2M 링크 생존 (집계 보유금액 유지의 물리 조건)
        self.assertEqual(_std_leaf('일반암진단비').pk, leaf.pk)
        self.assertTrue(idet.analysis_detail.filter(pk=leaf.pk).exists())
        # admin_verified 행 불변
        row = NormalizationDict.objects.get(pk=admin_row.pk)
        self.assertEqual(row.source, NormalizationDict.SOURCE_ADMIN_VERIFIED)
        self.assertEqual(row.confidence, 100)
        # 카운트 불변 (중복 생성 없음)
        self.assertEqual(AnalysisDetail.objects.filter(
            sub_category__category__name__startswith='[표준]').count(), det_before)
        self.assertEqual(NormalizationDict.objects.count(), dict_before)

    def test_seed_row_updated_not_duplicated_and_hit_count_kept(self):
        call_command('seed_normalization', stdout=StringIO())
        row = NormalizationDict.objects.get(company=1, raw_name='일반사망보험금')
        NormalizationDict.objects.filter(pk=row.pk).update(hit_count=7)
        before = NormalizationDict.objects.filter(
            company=1, raw_name='일반사망보험금').count()

        call_command('seed_normalization', '--force', stdout=StringIO())

        rows = NormalizationDict.objects.filter(
            company=1, raw_name='일반사망보험금')
        self.assertEqual(rows.count(), before)          # 중복 없음
        self.assertEqual(rows.first().pk, row.pk)       # 동일 행 유지
        self.assertEqual(rows.first().hit_count, 7)     # 데이터 복리 자산 보존


class SeedNormalizationMarkerTests(TestCase):
    """버전 마커: 2회차 no-op / --force 우회 / 버전 bump 시 재실행."""

    def test_missing_catalog_marker_backfills_without_reseeding_tree(self):
        call_command('seed_normalization', stdout=StringIO())
        leaf = _std_leaf('일반암진단비')
        AnalysisDetail.objects.filter(pk=leaf.pk).update(
            chart_based_amount=9999)
        InsuranceCategory.objects.filter(
            name__startswith='[표준]').delete()
        SeedMarker.objects.filter(
            key=seed_norm_mod.CATALOG_MARKER_KEY).delete()

        call_command('seed_normalization', stdout=StringIO())

        leaf.refresh_from_db()
        self.assertEqual(leaf.chart_based_amount, 9999)
        self.assertTrue(InsuranceDetail.objects.filter(
            sub_category__category__name='[표준]진단-암',
            sub_category__name='일반암',
            name='일반암진단비',
        ).exists())
        self.assertEqual(
            SeedMarker.objects.get(
                key=seed_norm_mod.MARKER_KEY).version,
            seed_norm_mod.SEED_VERSION)
        self.assertEqual(
            SeedMarker.objects.get(
                key=seed_norm_mod.CATALOG_MARKER_KEY).version,
            seed_norm_mod.CATALOG_SEED_VERSION)

    def test_second_run_is_noop_force_and_bump_rerun(self):
        call_command('seed_normalization', stdout=StringIO())
        marker = SeedMarker.objects.get(key=seed_norm_mod.MARKER_KEY)
        self.assertEqual(marker.version, seed_norm_mod.SEED_VERSION)

        # DB를 수동 변조 → 마커 최신이면 재실행해도 복원되지 않아야(no-op 증명)
        leaf = _std_leaf('일반암진단비')
        AnalysisDetail.objects.filter(pk=leaf.pk).update(chart_based_amount=9999)
        out = StringIO()
        call_command('seed_normalization', stdout=out)
        self.assertIn('이미 최신', out.getvalue())
        leaf.refresh_from_db()
        self.assertEqual(leaf.chart_based_amount, 9999)

        # --force → 실제 실행되어 시드 값으로 복원
        call_command('seed_normalization', '--force', stdout=StringIO())
        leaf.refresh_from_db()
        self.assertEqual(leaf.chart_based_amount, 5000)

        # 버전 bump(마커 구버전) → --force 없이도 실행
        AnalysisDetail.objects.filter(pk=leaf.pk).update(chart_based_amount=9999)
        SeedMarker.objects.filter(key=seed_norm_mod.MARKER_KEY).update(version='v0')
        call_command('seed_normalization', stdout=StringIO())
        leaf.refresh_from_db()
        self.assertEqual(leaf.chart_based_amount, 5000)
        self.assertEqual(
            SeedMarker.objects.get(key=seed_norm_mod.MARKER_KEY).version,
            seed_norm_mod.SEED_VERSION)


class SeedNormalizationOrphanPruneTests(TestCase):
    """고아: 기본은 로그만(삭제 없음), --prune 은 seed 출처 한정 + 보호 가드."""

    def _mini_constants(self):
        """표적항암 leaf 2개를 코드에서 제거한 미니 상수(고아 유발)."""
        removed = {'표적항암약물치료비', '표적항암방사선치료비'}
        tree = copy.deepcopy(seed_norm_mod.STANDARD_TREE)
        tree = [
            (cat, t, [(sub, [d for d in dets if d[0] not in removed])
                      for sub, dets in subs])
            for cat, t, subs in tree
        ]
        norm = [r for r in seed_norm_mod.NORMALIZATION_V0 if r[2] not in removed]
        return tree, norm

    def test_orphan_logged_not_deleted_then_prune_with_protection(self):
        call_command('seed_normalization', stdout=StringIO())
        chemo = _std_leaf('표적항암약물치료비')
        radiation = _std_leaf('표적항암방사선치료비')
        # chemo leaf 에 admin_verified alias → prune 에서도 leaf 보호되어야 함
        admin_row = NormalizationDict.objects.create(
            std_detail=chemo, company=1, raw_name='검수된표적항암특약',
            source=NormalizationDict.SOURCE_ADMIN_VERIFIED, confidence=100)

        tree, norm = self._mini_constants()
        with mock.patch.object(seed_norm_mod, 'STANDARD_TREE', tree), \
                mock.patch.object(seed_norm_mod, 'NORMALIZATION_V0', norm):
            # 1) 고아 로그만 — 삭제 없음
            out = StringIO()
            call_command('seed_normalization', '--force', stdout=out)
            self.assertIn('[고아]', out.getvalue())
            self.assertTrue(AnalysisDetail.objects.filter(pk=chemo.pk).exists())
            self.assertTrue(AnalysisDetail.objects.filter(pk=radiation.pk).exists())
            self.assertTrue(NormalizationDict.objects.filter(
                company=1, raw_name='표적항암약물치료비',
                source=NormalizationDict.SOURCE_SEED).exists())

            # 2) --prune: seed 출처 고아만 삭제, admin_verified leaf/행은 보호
            out2 = StringIO()
            call_command('seed_normalization', '--force', '--prune', stdout=out2)
            # 비보호 leaf(radiation) 삭제 + 그 seed alias 제거
            self.assertFalse(AnalysisDetail.objects.filter(pk=radiation.pk).exists())
            self.assertFalse(NormalizationDict.objects.filter(
                raw_name='표적항암방사선치료비',
                source=NormalizationDict.SOURCE_SEED).exists())
            # 보호 leaf(chemo — admin alias)와 admin_verified 행 생존
            self.assertIn('[보호]', out2.getvalue())
            self.assertTrue(AnalysisDetail.objects.filter(pk=chemo.pk).exists())
            self.assertTrue(NormalizationDict.objects.filter(
                pk=admin_row.pk,
                source=NormalizationDict.SOURCE_ADMIN_VERIFIED).exists())

    def test_prune_preserves_leaf_used_by_customer_case_override(self):
        call_command('seed_normalization', stdout=StringIO())
        radiation = _std_leaf('표적항암방사선치료비')
        catalog_detail = InsuranceDetail.objects.get(
            sub_category__category__name='[표준]처치',
            sub_category__name='표적항암',
            name='표적항암방사선치료비',
        )
        user, _ = _make_planner('override-prune@test.com')
        customer = Customer.objects.create(
            owner=user, name='직접확인고객', birth_day='1990.01.01')
        insurance = CustomerInsurance.objects.create(
            customer=customer,
            company=1,
            insurance_type=2,
            name='직접 확인 증권',
            monthly_premiums=10000,
        )
        case = CustomerInsuranceDetail.objects.create(
            insurance=insurance,
            detail=catalog_detail,
            raw_name='표적항암방사선치료비',
            assurance_amount=10000000,
            mapping_source='planner_override',
        )
        case.analysis_detail_override.add(radiation)

        tree, norm = self._mini_constants()
        with mock.patch.object(seed_norm_mod, 'STANDARD_TREE', tree), \
                mock.patch.object(seed_norm_mod, 'NORMALIZATION_V0', norm):
            out = StringIO()
            call_command(
                'seed_normalization', '--force', '--prune', stdout=out)

        self.assertIn('고객 직접 확인 연결', out.getvalue())
        self.assertTrue(AnalysisDetail.objects.filter(pk=radiation.pk).exists())
        self.assertTrue(
            case.analysis_detail_override.filter(pk=radiation.pk).exists())


class RepairAnalysisLinksTests(TestCase):
    """손상 복구: dry-run 보고 → --apply 재연결 → 2회차 no-op (멱등)."""

    def setUp(self):
        call_command('seed_normalization', stdout=StringIO())
        self.user, _ = _make_planner('repair@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='복구고객', birth_day='1988.08.08')
        # OCR persist 와 동일한 카탈로그 경로(파서 taxonomy): 진단비/암/일반암
        icat = InsuranceCategory.objects.create(
            insurance_type=2, name='진단비', order=1)
        isub = InsuranceSubCategory.objects.create(
            insurance_type=2, category=icat, name='암', order=1)
        self.idet = InsuranceDetail.objects.create(
            sub_category=isub, name='일반암', order=1)
        self.std = _std_leaf('일반암진단비')
        self.idet.analysis_detail.add(self.std)
        _make_portfolio(self.customer, self.idet, assurance_amount=30000000)

    def test_dry_run_reports_but_does_not_link(self):
        self.idet.analysis_detail.clear()  # 과거 시드 CASCADE 손상 재현
        out = StringIO()
        call_command('repair_analysis_links', stdout=out)
        self.assertIn('연결예정 1건', out.getvalue())
        self.assertEqual(self.idet.analysis_detail.count(), 0)  # dry-run 은 미변경

    def test_apply_relinks_and_second_apply_is_noop(self):
        self.idet.analysis_detail.clear()
        out = StringIO()
        call_command('repair_analysis_links', '--apply', stdout=out)
        self.assertIn('재연결 1건', out.getvalue())
        self.assertTrue(self.idet.analysis_detail.filter(pk=self.std.pk).exists())

        out2 = StringIO()
        call_command('repair_analysis_links', '--apply', stdout=out2)
        self.assertIn('후보 0건', out2.getvalue())  # 멱등 — 재실행 무해

    def test_unmapped_catalog_detail_counted_unresolved(self):
        """브리지 맵에 없는 경로는 미해석으로 보고만 하고 건드리지 않는다."""
        icat = InsuranceCategory.objects.create(
            insurance_type=2, name='실손 의료비', order=2)
        isub = InsuranceSubCategory.objects.create(
            insurance_type=2, category=icat, name='질병/상해', order=1)
        orphan_det = InsuranceDetail.objects.create(
            sub_category=isub, name='처방조제비', order=1)
        _make_portfolio(self.customer, orphan_det, assurance_amount=1000000)

        out = StringIO()
        call_command('repair_analysis_links', '--apply', stdout=out)
        self.assertIn('미해석 1건', out.getvalue())
        self.assertEqual(orphan_det.analysis_detail.count(), 0)


# ════════════════════════════════════════════════════════════════════════
# cleanup_demo — 프로드 [DEMO] 잔재 정리 명령 (LB#7)
#   가드 검증: @inpa.local 도메인 + demo_ 코드 프리픽스 밖 데이터는 절대 무손상,
#   is_admin 프로필은 이메일이 @inpa.local 이어도 보호.
# ════════════════════════════════════════════════════════════════════════
from inpa.billing.models import Plan, Subscription  # noqa: E402


class CleanupDemoCommandTests(TestCase):
    def setUp(self):
        # ★ 사용자 먼저 생성 — free Plan 이 없을 때 billing 시그널이 구독 자동생성을
        #   건너뛰므로(경고만), 구독 상태를 테스트가 직접 통제할 수 있다.
        self.demo_user = User.objects.create_user(
            email='demo@inpa.local', password='demoPass123!')
        Profile.objects.create(user=self.demo_user, email_verified_at=timezone.now())
        self.demo_admin = User.objects.create_user(
            email='demo-admin@inpa.local', password='demoPass123!')
        Profile.objects.create(user=self.demo_admin,
                               email_verified_at=timezone.now(), is_admin=True)
        self.real_user = User.objects.create_user(
            email='real@example.com', password='realPass123!')
        Profile.objects.create(user=self.real_user, email_verified_at=timezone.now())

        # 소유 데이터(CASCADE 확인용)
        self.demo_customer = Customer.objects.create(
            owner=self.demo_user, name='데모고객', mobile_phone_number='010-0000-0000',
            is_agree_term=True)
        self.real_customer = Customer.objects.create(
            owner=self.real_user, name='실고객', mobile_phone_number='010-1111-2222',
            is_agree_term=True)

        # 요금제: 실서비스 free + 데모 2종
        self.free_plan = Plan.objects.create(code='free', display_name='Free')
        self.demo_plan_orphan = Plan.objects.create(
            code='demo_free', display_name='[DEMO] Free')
        self.demo_plan_referenced = Plan.objects.create(
            code='demo_plus', display_name='[DEMO] Plus')
        # demo_free ← 데모 사용자 구독(사용자 삭제 시 CASCADE → 참조 0 → 플랜 삭제 가능)
        Subscription.objects.create(user=self.demo_user, plan=self.demo_plan_orphan)
        # demo_plus ← 실사용자 구독(참조 잔존 → 삭제 대신 비활성)
        Subscription.objects.create(user=self.real_user, plan=self.demo_plan_referenced)

    def _run(self):
        out = StringIO()
        call_command('cleanup_demo', stdout=out)
        return out.getvalue()

    def test_deletes_demo_users_and_cascade_keeps_real_data(self):
        self._run()
        self.assertFalse(User.objects.filter(email='demo@inpa.local').exists())
        self.assertFalse(Customer.objects.filter(pk=self.demo_customer.pk).exists())
        # 데모 패턴 밖 데이터 무손상
        self.assertTrue(User.objects.filter(email='real@example.com').exists())
        self.assertTrue(Customer.objects.filter(pk=self.real_customer.pk).exists())

    def test_admin_inpa_local_user_is_protected(self):
        out = self._run()
        self.assertTrue(User.objects.filter(email='demo-admin@inpa.local').exists())
        self.assertIn('demo-admin@inpa.local', out)
        self.assertIn('보호', out)

    def test_demo_plans_deleted_or_deactivated_free_intact(self):
        self._run()
        # 참조 0 → 삭제
        self.assertFalse(Plan.objects.filter(code='demo_free').exists())
        # 실사용자 구독 참조 잔존 → 비활성 (공개 /billing/plans/ 노출 차단)
        plus = Plan.objects.get(code='demo_plus')
        self.assertFalse(plus.is_active)
        self.assertTrue(Subscription.objects.filter(
            user=self.real_user, plan=plus).exists())
        # 실서비스 free 플랜 무손상
        free = Plan.objects.get(code='free')
        self.assertTrue(free.is_active)

    def test_rerun_is_idempotent(self):
        self._run()
        out = self._run()  # 재실행 — 예외 없이 0건 처리
        self.assertIn('삭제 사용자      : 0명', out)
        self.assertTrue(User.objects.filter(email='real@example.com').exists())
        self.assertTrue(User.objects.filter(email='demo-admin@inpa.local').exists())

    def test_shared_demo_marker_rows_cleaned_real_kept(self):
        # 프로드가 과거 seed_demo 를 돌린 흔적(공유 테이블 [DEMO] 행) 정리 + 실데이터 보존
        from inpa.boards.models import Faq, Notice
        from inpa.promotion.models import PromotionSample
        demo_notice = Notice.objects.create(
            author=self.real_user, title='[DEMO] 데모 공지', body='x')
        real_notice = Notice.objects.create(
            author=self.real_user, title='정식 공지', body='y')
        demo_faq = Faq.objects.create(question='[DEMO] 데모 질문', answer='a')
        real_faq = Faq.objects.create(question='정식 질문', answer='b')
        demo_sample = PromotionSample.objects.create(
            name='[DEMO] 명함 A', category='명함')
        real_sample = PromotionSample.objects.create(name='고급 명함', category='명함')
        out = self._run()
        self.assertFalse(Notice.objects.filter(pk=demo_notice.pk).exists())
        self.assertFalse(Faq.objects.filter(pk=demo_faq.pk).exists())
        self.assertFalse(PromotionSample.objects.filter(pk=demo_sample.pk).exists())
        self.assertTrue(Notice.objects.filter(pk=real_notice.pk).exists())
        self.assertTrue(Faq.objects.filter(pk=real_faq.pk).exists())
        self.assertTrue(PromotionSample.objects.filter(pk=real_sample.pk).exists())
        self.assertIn('공유 [DEMO] 정리', out)


# ════════════════════════════════════════════════════════════════════════
# claude_parser 로깅 — PII 로그 레드라인(LB#9): 로그 문자열에 증권/담보 내용 미포함
# ════════════════════════════════════════════════════════════════════════
from inpa.core.ocr.claude_parser import _add_coverage  # noqa: E402
from inpa.core.ocr.ocrdata import Ocr_Data  # noqa: E402


class DeathCoverageRoutingTests(TestCase):
    """사망 세분류 오분류 수정(2026-07-09) — _match_by_keywords 직접 호출(§7 회귀 관례).

    버그: 범용 '사망보험금'(5자)이 구체 '재해사망/질병사망'(4자)보다 길어 longest-first 로
    먼저 매칭되어 전부 일반사망으로 샜다. 구체 복합어 추가로 교정.
    """

    def _path(self, name):
        from inpa.core.ocr.claude_parser import _match_by_keywords
        return _match_by_keywords(name)

    def test_specific_death_routes_to_own_leaf(self):
        self.assertEqual(self._path('재해사망보험금'), ('사망', '재해', '재해사망'))
        self.assertEqual(self._path('질병사망보험금'), ('사망', '질병', '질병사망'))
        self.assertEqual(self._path('상해사망보험금'), ('사망', '상해', '상해사망'))
        self.assertEqual(self._path('재해사망보장'), ('사망', '재해', '재해사망'))
        self.assertEqual(self._path('질병사망보장'), ('사망', '질병', '질병사망'))

    def test_general_death_unchanged_no_regression(self):
        # 기본 사망·정책상 일반사망 취급 항목은 그대로 일반사망 유지.
        self.assertEqual(self._path('일반사망보험금'), ('사망', '일반', '일반사망'))
        self.assertEqual(self._path('일반사망'), ('사망', '일반', '일반사망'))
        self.assertEqual(self._path('보통약관(상해사망)'), ('사망', '일반', '일반사망'))
        self.assertEqual(self._path('사망후유장해'), ('사망', '일반', '일반사망'))


class CancerSubtypeRoutingTests(TestCase):
    """암 담보 세분류 개별 인식(2026-07-09, PM 확정) — _match_by_keywords 직접 호출(§7 회귀 관례).

    설계: 유사암 경로에 뭉쳐 있던 '소액암'·'갑상선암', 일반암 경로에 뭉쳐 있던 '특정암'을
    표준 트리에 이미 존재하는 전용 leaf(소액암진단비/갑상선암진단비/특정암진단비)로 분리.
    §8 무관(leaf 기존 존재, 순수 라우팅) — 사망 세분류 수정(DeathCoverageRoutingTests)과 동형.
    """

    def _path(self, name):
        from inpa.core.ocr.claude_parser import _match_by_keywords
        return _match_by_keywords(name)

    def test_small_amount_cancer_routes_to_own_leaf(self):
        self.assertEqual(self._path('소액암진단급여금'), ('진단비', '암', '소액암'))
        self.assertEqual(self._path('소액암진단비'), ('진단비', '암', '소액암'))
        self.assertEqual(self._path('소액암진단비(갑상선 등)'), ('진단비', '암', '소액암'))
        # tie-break 트랩: 괄호로 '유사암'이 동반 표기돼도 더 긴 복합어로 소액암이 이겨야 함.
        self.assertEqual(self._path('소액암(유사암)진단보험금'), ('진단비', '암', '소액암'))

    def test_thyroid_cancer_routes_to_own_leaf(self):
        self.assertEqual(self._path('갑상선암진단급여금'), ('진단비', '암', '갑상선암'))
        self.assertEqual(self._path('갑상선암진단비'), ('진단비', '암', '갑상선암'))
        self.assertEqual(self._path('갑상선암진단금'), ('진단비', '암', '갑상선암'))

    def test_specific_cancer_routes_to_own_leaf(self):
        self.assertEqual(self._path('특정암진단비'), ('진단비', '암', '특정암'))

    def test_similar_and_general_cancer_unchanged_no_regression(self):
        # 유사암(부모) 자체·나머지 유사암군은 그대로 유사암 유지.
        self.assertEqual(self._path('유사암진단급여금'), ('진단비', '암', '유사암'))
        self.assertEqual(self._path('상피내암진단비'), ('진단비', '암', '유사암'))
        self.assertEqual(self._path('제자리암진단비'), ('진단비', '암', '유사암'))
        # 회귀 가드: '갑상선'만 있고 '암'이 바로 붙지 않으면 갑상선암으로 오분류되지 않는다.
        self.assertEqual(self._path('유사암진단비(갑상선·경계성)'), ('진단비', '암', '유사암'))
        # 일반암(부모)도 그대로 유지.
        self.assertEqual(self._path('일반암진단급여금'), ('진단비', '암', '일반암'))
        self.assertEqual(self._path('일반암진단비'), ('진단비', '암', '일반암'))
        self.assertEqual(self._path('16대특정암진단비'), ('진단비', '암', '일반암'))

    def test_ambiguous_cancer_is_not_saved_through_category_map(self):
        """Claude 분류가 일반암이어도 복합 표기는 사람 확인 전 저장하지 않는다."""
        ocr = Ocr_Data()
        _add_coverage(ocr, {
            'category': '진단비',
            'subcategory': '암',
            'detail_name': '일반암',
            'name': '암진단비(유사암포함)',
            'amount': 30_000_000,
        }, 20, 100)

        self.assertEqual(
            ocr.dict_detail_data['진단비']['암']['일반암'],
            [],
        )
        self.assertEqual(ocr._manual_review_coverage_count, 1)


class DisabilitySubtypeRoutingTests(TestCase):
    """후유장해 담보 세분류 개별 인식(2026-07-09, PM 확정) — _match_by_keywords 직접 호출.

    설계: 상해후유장애(=상해후유장해) 경로에 뭉쳐 있던 '질병후유장해'(원인=질병)·
    '고도/80%이상후유장해'(중증도=고도)를 표준 트리 전용 leaf로 분리. 일반 상해후유장해는
    그대로 유지(§7 substring 트랩 회피 — 복합어 추가로 longest-first 보정).
    """

    def _path(self, name):
        from inpa.core.ocr.claude_parser import _match_by_keywords
        return _match_by_keywords(name)

    def test_disease_disability_routes_to_own_leaf(self):
        self.assertEqual(self._path('질병후유장해'), ('상해', '질병', '질병후유장해'))
        self.assertEqual(self._path('질병후유장해(3~100%)'), ('상해', '질병', '질병후유장해'))
        self.assertEqual(self._path('질병후유장해급여(3~100%)'), ('상해', '질병', '질병후유장해'))

    def test_severe_disability_routes_to_own_leaf(self):
        self.assertEqual(self._path('고도후유장해'), ('상해', '상해', '고도후유장해'))
        self.assertEqual(self._path('상해80%이상후유장해'), ('상해', '상해', '고도후유장해'))
        self.assertEqual(self._path('고도후유장해(80%이상)'), ('상해', '상해', '고도후유장해'))

    def test_general_disability_unchanged_no_regression(self):
        self.assertEqual(self._path('상해후유장해급여금'), ('상해', '상해', '상해후유장애'))
        self.assertEqual(self._path('상해후유장해(3~100%)'), ('상해', '상해', '상해후유장애'))
        self.assertEqual(self._path('상해후유장해(3%~100%)'), ('상해', '상해', '상해후유장애'))
        self.assertEqual(self._path('상해후유장해보험금(3~100%)'), ('상해', '상해', '상해후유장애'))
        self.assertEqual(self._path('재해후유장해급여금(3~100%)'), ('상해', '상해', '상해후유장애'))


class ClaudeParserLogRedactionTests(TestCase):
    def test_normalizer_error_log_excludes_coverage_content(self):
        """normalizer 훅 예외 로그에 담보 원문명·예외 메시지 내용이 새지 않는다."""
        ocr = Ocr_Data()

        def bad_normalizer(original_name, company_idx):
            raise RuntimeError('민감담보원문-유출금지-XYZ')

        cov = {'category': '', 'subcategory': '', 'detail_name': '',
               'name': '질병입원일당(비밀상품)', 'amount': 1000000}
        with self.assertLogs('inpa.core.ocr.claude_parser', level='WARNING') as cm:
            _add_coverage(ocr, cov, 20, 100,
                          normalizer=bad_normalizer, company_idx=1)
        joined = '\n'.join(cm.output)
        self.assertIn('normalizer hook error', joined)
        self.assertIn('RuntimeError', joined)          # 예외 타입은 허용
        self.assertNotIn('민감담보원문-유출금지-XYZ', joined)  # 메시지 내용 미포함
        self.assertNotIn('비밀상품', joined)             # 담보 원문명 미포함

    @override_settings(CLAUDE_API_KEY='test-key', CLAUDE_MODEL_PARSE='test-model')
    def test_json_failure_log_excludes_response_text(self):
        """JSON 파싱 실패 로그에 Claude 응답 본문(증권 내용 파생)이 새지 않는다."""
        from inpa.core.ocr.claude_parser import claude_parse

        fake_msg = mock.MagicMock()
        fake_msg.content = [mock.MagicMock(text='JSON아님: 고객이름 홍길동 / 증권원문내용')]
        fake_client = mock.MagicMock()
        fake_client.messages.create.return_value = fake_msg

        with mock.patch('anthropic.Anthropic', return_value=fake_client):
            with self.assertLogs('inpa.core.ocr.claude_parser', level='WARNING') as cm:
                result = claude_parse(['텍스트 줄'])
        self.assertIsNone(result)
        joined = '\n'.join(cm.output)
        self.assertIn('failed to parse JSON', joined)
        self.assertIn('length=', joined)               # 길이 수준만 기록
        self.assertNotIn('홍길동', joined)              # 응답 본문 미포함
        self.assertNotIn('증권원문내용', joined)


# ════════════════════════════════════════════════════════════════════════
# Claude 호출당 비용·파싱 결과 계측 (프리런치 리뷰 #17)
# claude_parse(meta=...) out-param — 성공·실패 모든 경로 outcome 스탬프 + PII 레드라인
# ════════════════════════════════════════════════════════════════════════
class ClaudeParseMetaOutcomeTests(TestCase):
    """claude_parse 의 meta out-param — 호출자가 성공·실패 모두 단일 지점에서 로깅할 수 있게
    outcome/usage/carrier_code/matched·unmatched_count 를 스탬프한다."""

    @override_settings(CLAUDE_API_KEY='')
    def test_no_key_outcome(self):
        from inpa.core.ocr.claude_parser import claude_parse
        meta = {}
        result = claude_parse(['텍스트'], meta=meta)
        self.assertIsNone(result)
        self.assertEqual(meta['outcome'], 'no_key')
        self.assertIsNone(meta['usage'])
        self.assertIn('model', meta)  # no_key 여도 model 은 알 수 있음

    @override_settings(CLAUDE_API_KEY='test-key', CLAUDE_MODEL_PARSE='test-model')
    def test_json_invalid_outcome_still_carries_usage(self):
        """JSON 파싱 실패해도 호출 자체는 성공했으므로 usage 는 채워진다(토큰 낭비 관측용)."""
        from inpa.core.ocr.claude_parser import claude_parse

        fake_msg = mock.MagicMock()
        fake_msg.content = [mock.MagicMock(text='이건 JSON이 아님')]
        fake_msg.usage = mock.Mock(input_tokens=50, output_tokens=5,
                                   cache_read_input_tokens=0, cache_creation_input_tokens=0)
        fake_client = mock.MagicMock()
        fake_client.messages.create.return_value = fake_msg

        meta = {}
        with mock.patch('anthropic.Anthropic', return_value=fake_client):
            result = claude_parse(['텍스트'], meta=meta)
        self.assertIsNone(result)
        self.assertEqual(meta['outcome'], 'json_invalid')
        self.assertIsNotNone(meta['usage'])
        self.assertEqual(meta['usage'].input_tokens, 50)

    @override_settings(CLAUDE_API_KEY='test-key', CLAUDE_MODEL_PARSE='test-model')
    def test_timeout_outcome(self):
        import anthropic

        from inpa.core.ocr.claude_parser import claude_parse

        fake_client = mock.MagicMock()
        fake_client.messages.create.side_effect = anthropic.APITimeoutError(request=mock.Mock())

        meta = {}
        with mock.patch('anthropic.Anthropic', return_value=fake_client):
            result = claude_parse(['텍스트'], meta=meta)
        self.assertIsNone(result)
        self.assertEqual(meta['outcome'], 'timeout')
        self.assertIsNone(meta['usage'])

    @override_settings(CLAUDE_API_KEY='test-key', CLAUDE_MODEL_PARSE='test-model')
    def test_api_error_outcome(self):
        from inpa.core.ocr.claude_parser import claude_parse

        fake_client = mock.MagicMock()
        fake_client.messages.create.side_effect = RuntimeError('boom')

        meta = {}
        with mock.patch('anthropic.Anthropic', return_value=fake_client):
            result = claude_parse(['텍스트'], meta=meta)
        self.assertIsNone(result)
        self.assertEqual(meta['outcome'], 'api_error')
        self.assertIsNone(meta['usage'])

    @override_settings(CLAUDE_API_KEY='test-key', CLAUDE_MODEL_PARSE='test-model')
    def test_meta_none_has_no_side_effect(self):
        """meta 미전달 시 기존 동작과 완전히 동일 — 기존 호출부/테스트 하위호환 회귀."""
        from inpa.core.ocr.claude_parser import claude_parse

        fake_msg = mock.MagicMock()
        fake_msg.content = [mock.MagicMock(text='이것도 JSON 아님')]
        fake_client = mock.MagicMock()
        fake_client.messages.create.return_value = fake_msg

        with mock.patch('anthropic.Anthropic', return_value=fake_client):
            result = claude_parse(['텍스트'])  # meta 없음 — 에러 없이 그대로 동작해야 함
        self.assertIsNone(result)

    @override_settings(CLAUDE_API_KEY='test-key', CLAUDE_MODEL_PARSE='test-model')
    def test_success_meta_carries_only_counts_no_raw_names(self):
        """★ PII 레드라인 회귀 — meta 에 담기는 값은 정수/enum 뿐, 담보 원문명이 새지 않는다."""
        import json as _json

        from inpa.core.ocr.claude_parser import claude_parse

        fake_json = _json.dumps({
            'insurance_type': 'loss', 'company_name': '삼성화재',
            'coverages': [{
                'name': '민감정보-홍길동-유출금지-XYZ', 'category': '진단비',
                'subcategory': '암', 'detail_name': '일반암',
                'amount': 10000000, 'premium': 1000,
            }],
            'unmatched_coverages': ['비밀상품명-ABC'],
        })
        fake_block = mock.MagicMock(text=fake_json)
        fake_msg = mock.MagicMock(content=[fake_block], usage=mock.Mock(
            input_tokens=10, output_tokens=5,
            cache_read_input_tokens=0, cache_creation_input_tokens=0))
        fake_client = mock.MagicMock()
        fake_client.messages.create.return_value = fake_msg

        meta = {}
        with mock.patch('anthropic.Anthropic', return_value=fake_client):
            claude_parse(['텍스트'], meta=meta)

        self.assertEqual(meta['outcome'], 'success')
        self.assertIsInstance(meta['carrier_code'], int)
        self.assertIsInstance(meta['matched_count'], int)
        self.assertIsInstance(meta['unmatched_count'], int)
        for value in meta.values():
            self.assertNotIn('민감정보', str(value))
            self.assertNotIn('비밀상품명', str(value))


class ClaudeApiLogPIISafetyTests(TestCase):
    """★ 프리런치 #17 PII 레드라인 — ClaudeApiLog 는 증권 원문·응답 본문·상품/고객명을
    담을 수 있는 자유 텍스트 필드를 가지면 안 된다. 스키마 자체가 방어선(회귀 시 즉시 실패)."""

    def test_schema_has_only_pii_safe_fields(self):
        from inpa.billing.models import ClaudeApiLog
        allowed = {
            'id', 'action', 'model', 'input_tokens', 'output_tokens',
            'cache_read_input_tokens', 'cache_creation_input_tokens',
            'user', 'cost_krw', 'parse_outcome', 'carrier_code',
            'matched_count', 'unmatched_count', 'created_at',
        }
        actual = {f.name for f in ClaudeApiLog._meta.get_fields()}
        self.assertEqual(actual, allowed)


# ═══ 담보 사전 피드백 루프 — 설계사 플래그 API (2026-07-09) ═══════════════════

class CoverageCasesTests(TestCase):
    """GET /customers/<id>/coverage-cases/?detail_id= — 소유 격리 + 응답 형태."""

    def setUp(self):
        self.user, self.client = _make_planner('cases@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='케이스고객', birth_day='1985.03.10')
        self.det = _build_std_tree()
        self.idet = _catalog_detail_linked_to(self.det)
        self.ci = _make_portfolio(self.customer, self.idet, 50_000_000)
        self.case = self.ci.case_list.get()

    def _url(self, cid, detail_id=None):
        qs = f'?detail_id={detail_id}' if detail_id is not None else ''
        return f'/api/v1/customers/{cid}/coverage-cases/{qs}'

    def test_lists_cases_for_leaf(self):
        self.case.raw_name = '삼성 사망담보 특약'
        self.case.save(update_fields=['raw_name'])
        r = self.client.get(self._url(self.customer.id, self.det.id))
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(len(body), 1)
        row = body[0]
        self.assertEqual(row['case_id'], self.case.id)
        self.assertEqual(row['insurance_id'], self.ci.id)
        self.assertEqual(row['insurance_title'], '테스트보험')
        self.assertEqual(row['name'], '사망담보')
        self.assertEqual(row['raw_name'], '삼성 사망담보 특약')
        self.assertEqual(row['assurance_amount'], 50_000_000)

    def test_raw_name_empty_when_not_stored(self):
        """레거시/직접 입력 케이스는 raw_name 빈 값(FE가 name 으로 폴백)."""
        r = self.client.get(self._url(self.customer.id, self.det.id))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()[0]['raw_name'], '')

    def test_requires_detail_id(self):
        r = self.client.get(self._url(self.customer.id))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['code'], 'DETAIL_ID_REQUIRED')

    def test_owner_isolation_404(self):
        _, client_b = _make_planner('cases-b@test.com')
        r = client_b.get(self._url(self.customer.id, self.det.id))
        self.assertEqual(r.status_code, 404)


class CoverageFlagCreateTests(TestCase):
    """POST /customers/<id>/coverage-flags/ — 스냅샷 + 격리 + 어드민 fan-out."""

    def setUp(self):
        from inpa.analysis.models import CoverageFlag  # noqa: F401 (아래 참조용)
        self.user, self.client = _make_planner('flag@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='플래그고객', birth_day='1985.03.10')
        self.det = _build_std_tree()
        self.idet = _catalog_detail_linked_to(self.det)
        self.ci = _make_portfolio(self.customer, self.idet, 50_000_000)
        self.ci.company = 2  # 삼성화재
        self.ci.save(update_fields=['company'])
        self.case = self.ci.case_list.get()
        # 어드민 1명 (fan-out 수신자)
        self.admin = User.objects.create_user(email='admin@test.com', password='inpaPass123!')
        self.admin.is_active = True
        self.admin.save(update_fields=['is_active'])
        Profile.objects.create(user=self.admin, email_verified_at=timezone.now(), is_admin=True)

    def _url(self, cid):
        return f'/api/v1/customers/{cid}/coverage-flags/'

    def test_create_snapshots_from_case_and_notifies_admin(self):
        from inpa.analysis.models import CoverageFlag
        from inpa.notifications.models import Notification, NotifType
        self.case.raw_name = '삼성 사망담보 특약'
        self.case.save(update_fields=['raw_name'])
        r = self.client.post(self._url(self.customer.id), {
            'analysis_detail_id': self.det.id,
            'case_id': self.case.id,
            'note': '위치가 이상해요',
        }, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        flag = CoverageFlag.objects.get(pk=r.json()['id'])
        self.assertEqual(flag.owner_id, self.user.id)
        self.assertEqual(flag.customer_id, self.customer.id)
        self.assertEqual(flag.analysis_detail_id, self.det.id)
        self.assertEqual(flag.case_id, self.case.id)
        self.assertEqual(flag.raw_name_snapshot, '삼성 사망담보 특약')
        self.assertEqual(flag.company, 2)
        self.assertEqual(flag.note, '위치가 이상해요')
        self.assertEqual(flag.status, CoverageFlag.STATUS_OPEN)
        # 어드민 fan-out 알림 (ADMIN_NOTIF_TYPES 파티션에 포함)
        notif = Notification.objects.filter(
            owner=self.admin, notif_type=NotifType.COVERAGE_FLAG_REQUESTED)
        self.assertEqual(notif.count(), 1)
        from inpa.notifications.models import ADMIN_NOTIF_TYPES
        self.assertIn(NotifType.COVERAGE_FLAG_REQUESTED.value, ADMIN_NOTIF_TYPES)

    def test_raw_name_snapshot_falls_back_to_detail_name(self):
        """case.raw_name 이 빈 값(레거시)이면 카탈로그 담보명으로 폴백."""
        from inpa.analysis.models import CoverageFlag
        r = self.client.post(self._url(self.customer.id), {
            'analysis_detail_id': self.det.id, 'case_id': self.case.id,
        }, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        flag = CoverageFlag.objects.get(pk=r.json()['id'])
        self.assertEqual(flag.raw_name_snapshot, '사망담보')

    def test_flag_without_case_allowed(self):
        """케이스 미선택 플래그(빈 leaf 신고)도 생성 — 스냅샷은 빈 값."""
        from inpa.analysis.models import CoverageFlag
        r = self.client.post(self._url(self.customer.id), {
            'analysis_detail_id': self.det.id, 'note': '여기 담보가 안 잡혀요',
        }, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        flag = CoverageFlag.objects.get(pk=r.json()['id'])
        self.assertEqual(flag.raw_name_snapshot, '')
        self.assertIsNone(flag.company)
        self.assertIsNone(flag.case_id)

    def test_owner_isolation_404(self):
        from inpa.analysis.models import CoverageFlag
        _, client_b = _make_planner('flag-b@test.com')
        r = client_b.post(self._url(self.customer.id), {
            'analysis_detail_id': self.det.id, 'case_id': self.case.id,
        }, format='json')
        self.assertEqual(r.status_code, 404)
        self.assertEqual(CoverageFlag.objects.count(), 0)

    def test_case_of_other_customer_404(self):
        """같은 소유자라도 다른 고객의 케이스 id 는 404(케이스-고객 정합)."""
        other = Customer.objects.create(owner=self.user, name='다른고객')
        r = self.client.post(self._url(other.id), {
            'analysis_detail_id': self.det.id, 'case_id': self.case.id,
        }, format='json')
        self.assertEqual(r.status_code, 404)

    def test_invalid_detail_400(self):
        r = self.client.post(self._url(self.customer.id), {
            'analysis_detail_id': 999999,
        }, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['code'], 'ANALYSIS_DETAIL_NOT_FOUND')

    def test_duplicate_flags_allowed(self):
        """동일 leaf 재신고는 새 행(중복 허용 — spec)."""
        from inpa.analysis.models import CoverageFlag
        for _ in range(2):
            r = self.client.post(self._url(self.customer.id), {
                'analysis_detail_id': self.det.id, 'case_id': self.case.id,
            }, format='json')
            self.assertEqual(r.status_code, 201)
        self.assertEqual(CoverageFlag.objects.count(), 2)


# ═══════════════════════════════════════════════════════════════════════
# 골든셋 정규화 정확도 기준선 (프리런치 리뷰 #18, 2026-07-09)
# ═══════════════════════════════════════════════════════════════════════
from inpa.analysis.golden_eval import (  # noqa: E402
    GOLDEN_SET_MIN_ACCURACY, GOLDEN_SET_MIN_EXACT_AUTO_MAPPED,
    evaluate_golden_set, find_golden_expected, load_golden_set,
)


class GoldenEvalUnitTests(TestCase):
    """evaluate_golden_set 유닛: 앵커 통과, 주입한 오답 포착, accuracy 계산 정확."""

    def setUp(self):
        call_command('seed_normalization', stdout=StringIO())

    def test_anchors_all_pass_on_seeded_db(self):
        result = evaluate_golden_set()
        self.assertEqual(result['anchor_failures'], [])
        self.assertEqual(result['anchor_passed'], result['anchor_total'])
        self.assertGreater(result['anchor_total'], 0)

    def test_injected_wrong_entry_is_captured_as_failure(self):
        """정답이 명백히 틀린 엔트리를 주입하면 failures 에 잡혀야 한다."""
        entries = [
            {'company': 1, 'raw_name': '일반사망보험금',
             'expected_std_leaf': '존재하지않는담보', 'source': 'anchor'},
        ]
        result = evaluate_golden_set(entries=entries)
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['passed'], 0)
        self.assertEqual(result['accuracy'], 0.0)
        self.assertEqual(len(result['failures']), 1)
        self.assertEqual(result['failures'][0]['expected'], '존재하지않는담보')
        self.assertEqual(result['failures'][0]['got'], '일반사망')

    def test_accuracy_matches_passed_over_total(self):
        result = evaluate_golden_set()
        self.assertAlmostEqual(
            result['accuracy'], result['passed'] / result['total'], places=6)
        self.assertEqual(result['failed'], result['total'] - result['passed'])

    def test_decision_metrics_separate_exact_review_and_unsafe_results(self):
        result = evaluate_golden_set()

        self.assertEqual(result['exact_auto_mapped'], 174)
        self.assertEqual(result['safe_human_review'], 66)
        self.assertEqual(result['unsafe_auto_mapped'], 0)
        self.assertEqual(
            result['exact_auto_mapped']
            + result['safe_human_review']
            + result['unsafe_auto_mapped'],
            result['total'],
        )
        self.assertEqual(result['safe_decision_rate'], 1.0)

    def test_unknown_mapping_is_counted_as_safe_human_review(self):
        result = evaluate_golden_set(entries=[{
            'company': 1,
            'raw_name': '표준위치를확정할수없는담보',
            'expected_std_leaf': '일반암진단비',
            'source': 'seed_dict',
        }])

        self.assertEqual(result['exact_auto_mapped'], 0)
        self.assertEqual(result['safe_human_review'], 1)
        self.assertEqual(result['unsafe_auto_mapped'], 0)

    def test_wrong_non_blocked_mapping_is_counted_as_unsafe(self):
        result = evaluate_golden_set(entries=[{
            'company': 1,
            'raw_name': '일반사망보험금',
            'expected_std_leaf': '일반암진단비',
            'source': 'seed_dict',
        }])

        self.assertEqual(result['exact_auto_mapped'], 0)
        self.assertEqual(result['safe_human_review'], 0)
        self.assertEqual(result['unsafe_auto_mapped'], 1)
        self.assertEqual(result['safe_decision_rate'], 0.0)

    def test_dosu_keywords_route_to_dosu_and_keep_mri_separate(self):
        from inpa.core.ocr.claude_parser import _match_by_keywords

        for raw_name in (
            '비급여도수치료실손',
            '비급여도수치료(실손)',
            '비급여도수·체외충격파·증식치료',
        ):
            with self.subTest(raw_name=raw_name):
                self.assertEqual(
                    _match_by_keywords(raw_name),
                    ('실손 의료비', '비급여', '비급여 도수치료'),
                )

        for raw_name in ('비급여MRI촬영료(실손)', '비급여MRA촬영료'):
            with self.subTest(raw_name=raw_name):
                self.assertEqual(
                    _match_by_keywords(raw_name),
                    ('실손 의료비', '비급여', '비급여 MR/MRA'),
                )

    def test_ambiguous_cancer_names_are_not_auto_mapped(self):
        from inpa.core.ocr.claude_parser import _match_by_keywords
        from inpa.core.ocr.ocrparsing import _match_coverage

        for raw_name in (
            '특정(소액)암진단비',
            '특정(소액)암진단금',
            '암진단비(유사암포함)',
        ):
            with self.subTest(raw_name=raw_name):
                self.assertIsNone(_match_by_keywords(raw_name))
                self.assertIsNone(_match_coverage(raw_name))

        self.assertEqual(
            _match_by_keywords('특정암진단비'),
            ('진단비', '암', '특정암'),
        )
        self.assertEqual(
            _match_by_keywords('소액암(유사암)진단보험금'),
            ('진단비', '암', '소액암'),
        )

    def test_load_golden_set_tags_seed_dict_and_anchor(self):
        entries = load_golden_set()
        sources = {e['source'] for e in entries}
        self.assertEqual(sources, {'seed_dict', 'anchor'})
        self.assertTrue(any(e['source'] == 'anchor' for e in entries))

    def test_find_golden_expected_lookup(self):
        expected = find_golden_expected(2, '상피내암진단비')
        self.assertEqual(expected, '유사암진단비')
        self.assertIsNone(find_golden_expected(999, '존재하지않는원문'))

    def test_no_duplicate_company_rawname_keys(self):
        """dedup: 앵커가 시드와 겹쳐도 (company, raw_name)은 코퍼스에 한 번만 — 중복 카운트 방지."""
        entries = load_golden_set()
        keys = [(e['company'], e['raw_name']) for e in entries]
        self.assertEqual(len(keys), len(set(keys)))
        # 시드에도 있는 원문을 앵커로 승격한 경우 source 는 anchor 로 덮여야 함
        by_key = {(e['company'], e['raw_name']): e for e in entries}
        promoted = by_key.get((1, '일반암진단급여금'))
        self.assertIsNotNone(promoted)
        self.assertEqual(promoted['source'], 'anchor')

    def test_eval_normalization_command_runs(self):
        """리포트가 폴백 범위를 밝히고 운영 OCR 정확도로 표현하지 않는다."""
        out = StringIO()
        call_command('eval_normalization', stdout=out)
        report = out.getvalue()
        self.assertIn('폴백 골든셋 자동매칭 재현율', report)
        self.assertIn('운영 OCR 정확도 아님', report)


class GoldenSetGateTests(TestCase):
    """CI 게이트 — 정확도 회귀 방지선 + 앵커 100% 통과 (스펙 §3)."""

    def setUp(self):
        call_command('seed_normalization', stdout=StringIO())

    def test_accuracy_above_ratchet(self):
        result = evaluate_golden_set()
        self.assertGreaterEqual(
            result['accuracy'], GOLDEN_SET_MIN_ACCURACY,
            f"정확도 {result['accuracy']:.4f} 가 기준선 {GOLDEN_SET_MIN_ACCURACY} 미만 — "
            f"회귀 확인 필요 (실패 {result['failed']}/{result['total']}건).")

    def test_all_anchors_pass(self):
        result = evaluate_golden_set()
        self.assertEqual(
            result['anchor_failures'], [],
            f"함정 앵커 실패: {result['anchor_failures']} — 반드시 100% 통과해야 함.")

    def test_exact_auto_mapping_ratchet_is_at_least_174_of_240(self):
        result = evaluate_golden_set()
        self.assertGreaterEqual(
            result['exact_auto_mapped'], GOLDEN_SET_MIN_EXACT_AUTO_MAPPED)
        self.assertEqual(result['total'], 240)

    def test_unsafe_auto_mapping_is_zero(self):
        result = evaluate_golden_set()
        self.assertEqual(
            result['unsafe_auto_mapped'], 0,
            f"위험 자동 오매핑: {result['unsafe_failures']}")
