from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from inpa.analysis.baselines import normalize_money, select_baseline
from inpa.analysis.views import _age_band
from inpa.customers.models import PlannerBaseline


def _baseline(product_group, age_band, gender, label):
    return SimpleNamespace(
        product_group=product_group,
        age_band=age_band,
        gender=gender,
        label=label,
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


class BaselineSelectionTests(SimpleTestCase):
    def setUp(self):
        self.candidates = [
            _baseline(PlannerBaseline.PRODUCT_GROUP_LIFE, '30s', 1, 'life-30s-male'),
            _baseline(PlannerBaseline.PRODUCT_GROUP_LIFE, '30s', None, 'life-30s-common'),
            _baseline(PlannerBaseline.PRODUCT_GROUP_NONLIFE, '30s', 1, 'nonlife-30s-male'),
            _baseline(PlannerBaseline.PRODUCT_GROUP_LIFE, '60s+', 2, 'life-60s-female'),
            _baseline(PlannerBaseline.PRODUCT_GROUP_INDEMNITY, '30s', 1, 'indemnity-30s-male'),
        ]

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

    def test_wrong_age_never_falls_back(self):
        self.assertIsNone(select_baseline(
            self.candidates, insurance_type=1, age_band='40s', gender=1))

    def test_life_never_uses_nonlife(self):
        candidates = [
            row for row in self.candidates if row.label == 'nonlife-30s-male'
        ]

        self.assertIsNone(select_baseline(
            candidates, insurance_type=1, age_band='30s', gender=1))

    def test_ambiguous_indemnity_and_annuity_are_neutral(self):
        for insurance_type in (0, PlannerBaseline.PRODUCT_GROUP_INDEMNITY,
                               PlannerBaseline.PRODUCT_GROUP_ANNUITY):
            with self.subTest(insurance_type=insurance_type):
                self.assertIsNone(select_baseline(
                    self.candidates, insurance_type=insurance_type,
                    age_band='30s', gender=1))

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


class HeatmapGradingGateTests(SimpleTestCase):
    @override_settings(HEATMAP_GRADING_ENABLED=False)
    def test_grading_gate_is_closed(self):
        self.assertFalse(settings.HEATMAP_GRADING_ENABLED)
