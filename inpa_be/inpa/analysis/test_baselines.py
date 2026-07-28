from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from inpa.analysis.baselines import (
    grading_eligible_baselines,
    is_grading_eligible_baseline,
    normalize_money,
    select_baseline,
)
from inpa.analysis.models import AnalysisCategory, AnalysisDetail, AnalysisSubCategory
from inpa.analysis.views import _age_band
from inpa.accounts.models import Profile, User
from inpa.customers.models import Customer, PlannerBaseline
from inpa.insurances.models import (
    CustomerInsurance, CustomerInsuranceDetail, InsuranceCategory,
    InsuranceDetail, InsuranceSubCategory,
)


def _baseline(
        product_group, age_band, gender, label, *,
        is_active=True, baseline_source='planner'):
    return SimpleNamespace(
        product_group=product_group,
        age_band=age_band,
        gender=gender,
        label=label,
        is_active=is_active,
        baseline_source=baseline_source,
    )


class BaselineMoneyTests(SimpleTestCase):
    def test_ten_thousand_won_is_converted_to_won(self):
        self.assertEqual(
            normalize_money(Decimal('5000'), PlannerBaseline.UNIT_TEN_THOUSAND_WON),
            Decimal('50000000'),
        )

    def test_won_is_not_scaled(self):
        self.assertEqual(
            normalize_money(Decimal('50000000'), PlannerBaseline.UNIT_WON),
            Decimal('50000000'),
        )

    def test_account_unit_is_not_money(self):
        self.assertIsNone(
            normalize_money(Decimal('3'), PlannerBaseline.UNIT_ACCOUNT)
        )


class BaselineSourceEligibilityTests(SimpleTestCase):
    def test_only_active_planner_source_is_grading_eligible(self):
        planner = _baseline(
            PlannerBaseline.PRODUCT_GROUP_NONLIFE,
            '30s',
            1,
            'planner',
            baseline_source='planner',
        )
        preset = _baseline(
            PlannerBaseline.PRODUCT_GROUP_NONLIFE,
            '30s',
            1,
            'preset',
            baseline_source='preset',
        )
        source_less = _baseline(
            PlannerBaseline.PRODUCT_GROUP_NONLIFE,
            '30s',
            1,
            'source-less',
            baseline_source=None,
        )
        inactive = _baseline(
            PlannerBaseline.PRODUCT_GROUP_NONLIFE,
            '30s',
            1,
            'inactive',
            is_active=False,
            baseline_source='planner',
        )

        self.assertTrue(is_grading_eligible_baseline(planner))
        self.assertFalse(is_grading_eligible_baseline(preset))
        self.assertFalse(is_grading_eligible_baseline(source_less))
        self.assertFalse(is_grading_eligible_baseline(inactive))
        self.assertEqual(
            grading_eligible_baselines(
                [preset, source_less, planner, inactive]),
            [planner],
        )

    def test_select_baseline_rejects_unreviewed_preset_defensively(self):
        preset = _baseline(
            PlannerBaseline.PRODUCT_GROUP_NONLIFE,
            '30s',
            1,
            'preset',
            baseline_source='preset',
        )

        self.assertIsNone(select_baseline(
            [preset],
            insurance_type=PlannerBaseline.PRODUCT_GROUP_NONLIFE,
            age_band='30s',
            gender=1,
        ))


class BaselineSelectionTests(SimpleTestCase):
    def setUp(self):
        self.candidates = [
            _baseline(PlannerBaseline.PRODUCT_GROUP_LIFE, '30s', 1, 'life-30s-male'),
            _baseline(PlannerBaseline.PRODUCT_GROUP_LIFE, '30s', None, 'life-30s-common'),
            _baseline(PlannerBaseline.PRODUCT_GROUP_NONLIFE, '30s', 1, 'nonlife-30s-male'),
            _baseline(PlannerBaseline.PRODUCT_GROUP_LIFE, '60s+', 2, 'life-60s-female'),
            _baseline(PlannerBaseline.PRODUCT_GROUP_INDEMNITY, '30s', 1, 'indemnity-30s-male'),
        ]

    def test_select_baseline_falls_back_by_product_age_and_gender(self):
        candidates = [
            _baseline(
                PlannerBaseline.PRODUCT_GROUP_ALL,
                PlannerBaseline.AGE_ALL,
                None,
                'all-default',
            ),
            _baseline(
                PlannerBaseline.PRODUCT_GROUP_ALL,
                '30s',
                None,
                'all-30-common',
            ),
            _baseline(
                PlannerBaseline.PRODUCT_GROUP_NONLIFE,
                PlannerBaseline.AGE_ALL,
                1,
                'nonlife-all-male',
            ),
            _baseline(
                PlannerBaseline.PRODUCT_GROUP_NONLIFE,
                '30s',
                1,
                'nonlife-30-male',
            ),
        ]

        expected_fallbacks = (
            'nonlife-30-male',
            'nonlife-all-male',
            'all-30-common',
            'all-default',
        )
        remaining = list(candidates)
        for expected in expected_fallbacks:
            with self.subTest(expected=expected):
                chosen = select_baseline(
                    remaining,
                    insurance_type=PlannerBaseline.PRODUCT_GROUP_NONLIFE,
                    age_band='30s',
                    gender=1,
                )
                self.assertEqual(chosen.label, expected)
            remaining = [row for row in remaining if row.label != expected]

    def test_exact_age_and_gender_win(self):
        chosen = select_baseline(
            self.candidates, insurance_type=1, age_band='30s', gender=1)

        self.assertEqual(chosen.label, 'life-30s-male')

    def test_common_gender_is_the_only_gender_fallback(self):
        candidates = [
            row for row in self.candidates if row.label != 'life-30s-male'
        ]

        chosen = select_baseline(
            candidates, insurance_type=1, age_band='30s', gender=1)

        self.assertEqual(chosen.label, 'life-30s-common')

    def test_common_coverage_uses_all_product_default(self):
        candidates = [
            _baseline(
                PlannerBaseline.PRODUCT_GROUP_ALL,
                PlannerBaseline.AGE_ALL,
                None,
                'all-default',
            ),
            _baseline(
                PlannerBaseline.PRODUCT_GROUP_NONLIFE,
                PlannerBaseline.AGE_ALL,
                None,
                'nonlife-default',
            ),
        ]

        chosen = select_baseline(
            candidates,
            insurance_type=PlannerBaseline.PRODUCT_GROUP_ALL,
            age_band='40s',
            gender=2,
        )

        self.assertEqual(chosen.label, 'all-default')

    def test_life_never_uses_nonlife(self):
        candidates = [
            row for row in self.candidates if row.label == 'nonlife-30s-male'
        ]

        self.assertIsNone(select_baseline(
            candidates, insurance_type=1, age_band='30s', gender=1))

    def test_inactive_and_source_less_rows_are_excluded(self):
        candidates = [
            _baseline(
                PlannerBaseline.PRODUCT_GROUP_LIFE,
                '30s',
                1,
                'inactive',
                is_active=False,
            ),
            _baseline(
                PlannerBaseline.PRODUCT_GROUP_LIFE,
                '30s',
                1,
                'source-less',
                baseline_source=None,
            ),
            _baseline(
                PlannerBaseline.PRODUCT_GROUP_ALL,
                PlannerBaseline.AGE_ALL,
                None,
                'live-default',
            ),
        ]

        chosen = select_baseline(
            candidates, insurance_type=1, age_band='30s', gender=1)

        self.assertEqual(chosen.label, 'live-default')

    def test_multiple_equally_specific_rows_are_neutral(self):
        candidates = self.candidates + [
            _baseline(PlannerBaseline.PRODUCT_GROUP_LIFE, '30s', 1, 'duplicate'),
        ]

        self.assertIsNone(select_baseline(
            candidates, insurance_type=1, age_band='30s', gender=1))


class BaselineAgeBandTests(SimpleTestCase):
    @patch('inpa.analysis.views.timezone.localdate', return_value=date(2026, 7, 21))
    def test_complete_real_dates_are_banded_from_kst_local_date(self, _localdate):
        self.assertEqual(_age_band('1996-07-21'), '30s')
        self.assertEqual(_age_band('1996.07.22'), '20s')
        self.assertEqual(_age_band('1966-07-21'), '60s+')

    def test_partial_or_invalid_birth_dates_are_neutral(self):
        for birth_day in ('', '1996', '1996-07', '2026-02-31', '1996/07/21'):
            with self.subTest(birth_day=birth_day):
                self.assertIsNone(_age_band(birth_day))


class HeatmapGradingGateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='closed-gate@test.com', password='inpaPass123!')
        self.user.is_active = True
        self.user.save(update_fields=['is_active'])
        Profile.objects.create(user=self.user, email_verified_at=timezone.now())
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.customer = Customer.objects.create(
            owner=self.user, name='게이트고객', birth_day='1990-01-01', gender=1)

        category = AnalysisCategory.objects.create(
            insurance_type=2, name='상해', order=1)
        sub_category = AnalysisSubCategory.objects.create(
            insurance_type=2, category=category, name='사망/후유', order=1)
        analysis_detail = AnalysisDetail.objects.create(
            sub_category=sub_category, name='사망보장', order=1)
        insurance_category = InsuranceCategory.objects.create(
            insurance_type=2, name='손보상품', order=1)
        insurance_sub_category = InsuranceSubCategory.objects.create(
            insurance_type=2, category=insurance_category, name='보장', order=1)
        insurance_detail = InsuranceDetail.objects.create(
            sub_category=insurance_sub_category, name='사망담보', order=1)
        insurance_detail.analysis_detail.add(analysis_detail)
        insurance = CustomerInsurance.objects.create(
            customer=self.customer, insurance_type=2, name='테스트보험',
            portfolio_type=1, payment_period_type=1, payment_period=20,
            monthly_premiums=50000, monthly_assurance_premium=50000,
        )
        CustomerInsuranceDetail.objects.create(
            insurance=insurance, detail=insurance_detail,
            assurance_amount=50000000, premium=10000,
            payment_period_type=1, payment_period=20,
            warranty_period_type=1, warranty_period='100',
        )
        insurance.set_renewal_month()
        insurance.calculate()
        insurance.save()
        PlannerBaseline.objects.create(
            owner=self.user, coverage_key='사망보장',
            product_group=PlannerBaseline.PRODUCT_GROUP_NONLIFE,
            age_band='30s', gender=1,
            recommend_min=100000000, recommend_max=300000000,
            unit=PlannerBaseline.UNIT_WON, baseline_source='planner',
        )

    @override_settings(HEATMAP_GRADING_ENABLED=False)
    def test_grading_gate_is_closed(self):
        response = self.client.get(
            f'/api/v1/customers/{self.customer.id}/heatmap/')

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body['mode'], 'neutral')
        self.assertTrue(body['baseline_present'])
        self.assertFalse(body['grading_enabled'])
        details = [
            detail
            for category in body['tree']
            for sub_category in category['sub_categories']
            for detail in sub_category['details']
        ]
        self.assertTrue(details)
        for detail in details:
            self.assertEqual(detail['status'], 'neutral')
            self.assertIsNone(detail['baseline'])

    @override_settings(HEATMAP_GRADING_ENABLED=True)
    def test_preset_is_stored_but_not_applied(self):
        baseline = PlannerBaseline.objects.get(owner=self.user)
        baseline.baseline_source = PlannerBaseline.SOURCE_PRESET
        baseline.preset_origin = 'v0_starter'
        baseline.save(update_fields=['baseline_source', 'preset_origin'])

        body = self.client.get(
            f'/api/v1/customers/{self.customer.id}/heatmap/').json()

        self.assertEqual(body['mode'], 'neutral')
        self.assertTrue(body['baseline_present'])
        self.assertEqual(body['baseline_count'], 1)
        self.assertEqual(body['applied_baseline_count'], 0)
        self.assertEqual(body['unapplied_baseline_count'], 1)

    @override_settings(HEATMAP_GRADING_ENABLED=True)
    def test_planner_baseline_is_applied(self):
        body = self.client.get(
            f'/api/v1/customers/{self.customer.id}/heatmap/').json()

        self.assertEqual(body['mode'], 'graded')
        self.assertEqual(body['baseline_count'], 1)
        self.assertEqual(body['applied_baseline_count'], 1)
        self.assertEqual(body['unapplied_baseline_count'], 0)
