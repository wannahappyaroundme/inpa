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

    @override_settings(CLAUDE_API_KEY='test-key')
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
