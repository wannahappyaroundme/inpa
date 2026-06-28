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
        """계약 키 전부 존재 + publishable 항상 false + 면책 고정."""
        _make_portfolio_typed(self.customer, self.idet, 50000000, portfolio_type=1)
        body = self._get().json()
        for key in ('mode', 'current', 'proposed', 'rows', 'guide_draft',
                    'guide_enabled', 'publishable', 'publish_blocked_reason',
                    'disclaimer'):
            self.assertIn(key, body)
        self.assertFalse(body['publishable'])
        self.assertEqual(body['publish_blocked_reason'], '법무 검토 완료 전 발행 금지')
        self.assertIn('AI', body['disclaimer'])

    @override_settings(COMPARE_AI_ENABLED=False)
    def test_ai_disabled_guide_null(self):
        """★ COMPARE_AI_ENABLED=False → guide_draft=null, guide_enabled=false."""
        _make_portfolio_typed(self.customer, self.idet, 50000000, portfolio_type=1)
        _make_portfolio_typed(self.customer, self.idet, 100000000, portfolio_type=2)
        body = self._get().json()
        self.assertIsNone(body['guide_draft'])
        self.assertFalse(body['guide_enabled'])

    # ── 갈아타기 KEEP/SWITCH 판정 (설계사 내부면 전용, 결정론) ──
    def test_verdict_keys_present(self):
        """verdict + switch_warnings 키 존재 + decision 은 3값 중 하나."""
        _make_portfolio_typed(self.customer, self.idet, 50000000, portfolio_type=1, monthly=40000)
        _make_portfolio_typed(self.customer, self.idet, 100000000, portfolio_type=2, monthly=60000)
        body = self._get().json()
        self.assertIn('verdict', body)
        self.assertIn('switch_warnings', body)
        for k in ('decision', 'reason', 'customer_net_benefit_estimate', 'disclaimer'):
            self.assertIn(k, body['verdict'])
        self.assertIn(body['verdict']['decision'], ('KEEP', 'SWITCH', 'NEUTRAL'))

    def test_verdict_neutral_when_no_proposed(self):
        """제안(갈아타기 대상) 없음 → NEUTRAL."""
        _make_portfolio_typed(self.customer, self.idet, 50000000, portfolio_type=1)
        body = self._get().json()
        self.assertEqual(body['verdict']['decision'], 'NEUTRAL')

    def test_verdict_switch_when_cheaper_and_improved(self):
        """더 싸고(월6만→4만) 보장 개선(5천만→1억) → SWITCH 검토."""
        _make_portfolio_typed(self.customer, self.idet, 50000000, portfolio_type=1, monthly=60000)
        _make_portfolio_typed(self.customer, self.idet, 100000000, portfolio_type=2, monthly=40000)
        body = self._get().json()
        self.assertEqual(body['verdict']['decision'], 'SWITCH')

    def test_verdict_keep_when_pricier_no_improvement(self):
        """더 비싸고(월4만→8만) 보장 동일 → KEEP(유지 유리)."""
        _make_portfolio_typed(self.customer, self.idet, 50000000, portfolio_type=1, monthly=40000)
        _make_portfolio_typed(self.customer, self.idet, 50000000, portfolio_type=2, monthly=80000)
        body = self._get().json()
        self.assertEqual(body['verdict']['decision'], 'KEEP')


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
