import dataclasses
import importlib
import re
from collections import Counter
from dataclasses import FrozenInstanceError, replace

from django.core.management.base import CommandError
from django.test import SimpleTestCase
from unittest.mock import patch

try:
    specs = importlib.import_module('inpa.analysis.showcase_data')
except ModuleNotFoundError as exc:
    if exc.name != 'inpa.analysis.showcase_data':
        raise
    specs = None


def _renderable_strings(value):
    if isinstance(value, str):
        yield value
    elif dataclasses.is_dataclass(value):
        for field in dataclasses.fields(value):
            yield from _renderable_strings(getattr(value, field.name))
    elif isinstance(value, (tuple, list, set, frozenset)):
        for item in value:
            yield from _renderable_strings(item)


class ShowcaseSpecTestCase(SimpleTestCase):
    def setUp(self):
        self.assertIsNotNone(
            specs,
            'inpa.analysis.showcase_data 합성 자료 명세가 아직 없습니다.',
        )


class ShowcaseCustomerSpecsTests(ShowcaseSpecTestCase):
    def test_customer_counts_and_required_combinations_are_fixed(self):
        self.assertEqual(specs.CUSTOMER_COUNT, 50)
        self.assertIsInstance(specs.CUSTOMERS, tuple)
        self.assertEqual(len(specs.CUSTOMERS), 50)

        required_fields = {
            'key',
            'name',
            'birth_date',
            'gender',
            'occupation',
            'phone',
            'source',
            'stage',
            'status',
            'tags',
            'memo',
        }
        self.assertTrue(required_fields.issubset({
            field.name for field in dataclasses.fields(specs.CustomerSpec)
        }))
        self.assertEqual(len({customer.key for customer in specs.CUSTOMERS}), 50)
        self.assertEqual(len({customer.name for customer in specs.CUSTOMERS}), 50)
        for customer in specs.CUSTOMERS:
            self.assertTrue(all((
                customer.key,
                customer.name,
                customer.birth_date,
                customer.gender,
                customer.occupation,
                customer.phone,
                customer.source,
                customer.stage,
                customer.status,
                customer.tags,
                customer.memo,
            )))

    def test_customer_specs_are_immutable(self):
        self.assertTrue(dataclasses.is_dataclass(specs.CustomerSpec))
        self.assertIsInstance(specs.CUSTOMERS, tuple)
        with self.assertRaises(FrozenInstanceError):
            specs.CUSTOMERS[0].name = '변경된 이름'

    def test_stage_and_status_distributions_match_the_showcase_contract(self):
        self.assertEqual(
            specs.STAGE_COUNTS,
            {'db': 14, 'contact': 12, 'meeting': 12, 'contract': 12},
        )
        self.assertEqual(
            Counter(customer.stage for customer in specs.CUSTOMERS),
            specs.STAGE_COUNTS,
        )
        self.assertEqual(
            specs.STATUS_COUNTS,
            {'active': 42, 'hold': 4, 'dormant': 3, 'closed': 1},
        )
        self.assertEqual(
            Counter(customer.status for customer in specs.CUSTOMERS),
            specs.STATUS_COUNTS,
        )

    def test_phones_use_reserved_showcase_range_and_are_unique(self):
        phones = [customer.phone for customer in specs.CUSTOMERS]
        self.assertEqual(len(phones), len(set(phones)))
        for phone in phones:
            self.assertRegex(phone, r'^010-1\d{3}-\d{4}$')

    def test_customer_records_have_no_email_address_or_resident_id_fields(self):
        field_names = {
            field.name.lower()
            for field in dataclasses.fields(specs.CustomerSpec)
        }
        self.assertTrue(
            field_names.isdisjoint({
                'email',
                'address',
                'resident_id',
                'resident_registration_number',
                'social_security_number',
            })
        )
        rendered = tuple(_renderable_strings(specs.CUSTOMERS))
        self.assertFalse(any(
            re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', text)
            for text in rendered
        ))
        self.assertFalse(any(
            re.search(r'\b\d{6}-[1-4]\d{6}\b', text)
            for text in rendered
        ))

    def test_eight_anchor_customers_have_distinct_realistic_contexts(self):
        self.assertEqual(specs.ANCHOR_CUSTOMER_COUNT, 8)
        self.assertEqual(len(specs.ANCHOR_CUSTOMER_KEYS), 8)
        anchors = [
            customer
            for customer in specs.CUSTOMERS
            if customer.key in specs.ANCHOR_CUSTOMER_KEYS
        ]
        self.assertEqual(len(anchors), 8)
        self.assertEqual(len({customer.birth_date.year for customer in anchors}), 8)
        self.assertGreaterEqual(
            max(customer.birth_date.year for customer in anchors)
            - min(customer.birth_date.year for customer in anchors),
            30,
        )
        self.assertEqual({customer.gender for customer in anchors}, {1, 2})
        self.assertEqual(len({customer.family_context for customer in anchors}), 8)
        self.assertEqual(len({customer.coverage_focus for customer in anchors}), 8)


class ShowcaseInsuranceSpecsTests(ShowcaseSpecTestCase):
    def test_eighty_policies_are_assigned_to_all_fifty_customers(self):
        self.assertEqual(specs.INSURANCE_COUNT, 80)
        self.assertIsInstance(specs.INSURANCES, tuple)
        self.assertEqual(len(specs.INSURANCES), 80)
        customer_keys = {customer.key for customer in specs.CUSTOMERS}
        assigned_keys = {policy.customer_key for policy in specs.INSURANCES}
        self.assertEqual(assigned_keys, customer_keys)
        self.assertTrue(all(
            policy.customer_key in customer_keys
            for policy in specs.INSURANCES
        ))

    def test_policy_and_coverage_specs_are_immutable(self):
        self.assertTrue(dataclasses.is_dataclass(specs.InsuranceSpec))
        self.assertTrue(dataclasses.is_dataclass(specs.CoverageSpec))
        self.assertIsInstance(specs.INSURANCES, tuple)
        self.assertIsInstance(specs.INSURANCES[0].coverages, tuple)
        with self.assertRaises(FrozenInstanceError):
            specs.INSURANCES[0].monthly_premium = 0

    def test_anchor_customers_have_rich_policy_and_coverage_sets(self):
        self.assertEqual(specs.MIN_COVERAGE_COUNT, 160)
        policies_by_customer = Counter(
            policy.customer_key for policy in specs.INSURANCES
        )
        coverage_by_customer = Counter()
        for policy in specs.INSURANCES:
            coverage_by_customer[policy.customer_key] += len(policy.coverages)

        for customer_key in specs.ANCHOR_CUSTOMER_KEYS:
            self.assertGreaterEqual(policies_by_customer[customer_key], 2)
            self.assertLessEqual(policies_by_customer[customer_key], 4)
            self.assertGreaterEqual(coverage_by_customer[customer_key], 12)
            self.assertLessEqual(coverage_by_customer[customer_key], 25)
        self.assertGreaterEqual(
            sum(coverage_by_customer[key] for key in specs.ANCHOR_CUSTOMER_KEYS),
            160,
        )

    def test_recent_six_month_policy_flow_never_decreases(self):
        month_counts = Counter(
            policy.registered_month_offset for policy in specs.INSURANCES
        )
        self.assertEqual(set(month_counts), {0, 1, 2, 3, 4, 5})
        oldest_to_newest = [month_counts[offset] for offset in range(5, -1, -1)]
        self.assertEqual(sum(oldest_to_newest), 80)
        self.assertTrue(all(
            earlier <= later
            for earlier, later in zip(
                oldest_to_newest,
                oldest_to_newest[1:],
            )
        ))

    def test_only_synthetic_companies_and_general_product_types_are_used(self):
        allowed_companies = {
            '생활보장사 A',
            '생활보장사 B',
            '생활보장사 C',
            '생활보장사 D',
        }
        allowed_products = {
            '종합보장형',
            '건강보장형',
            '질병보장형',
            '상해보장형',
            '간병보장형',
            '어린이보장형',
            '운전자보장형',
            '의료비보장형',
        }
        self.assertEqual(
            {policy.company_name for policy in specs.INSURANCES},
            allowed_companies,
        )
        self.assertTrue(all(
            policy.product_type in allowed_products
            for policy in specs.INSURANCES
        ))


class ShowcaseCopySafetyTests(ShowcaseSpecTestCase):
    def test_renderable_strings_contain_no_showcase_markers(self):
        rendered = tuple(_renderable_strings((
            specs.CUSTOMERS,
            specs.INSURANCES,
        )))
        forbidden = (
            '[demo]',
            '[촬영]',
            '데모',
            '테스트',
            '촬영용',
            'sample',
            'dummy',
        )
        findings = [
            (word, text)
            for text in rendered
            for word in forbidden
            if word in text.lower()
        ]
        self.assertEqual(findings, [])

    def test_renderable_strings_do_not_name_real_insurers_or_claim_results(self):
        rendered = tuple(_renderable_strings((
            specs.CUSTOMERS,
            specs.INSURANCES,
        )))
        forbidden = (
            '삼성생명',
            '삼성화재',
            '교보생명',
            '한화생명',
            '현대해상',
            'db손해보험',
            'kb손해보험',
            '메리츠화재',
            '흥국생명',
            '신한라이프',
            '동양생명',
            '미래에셋생명',
            '라이나생명',
            'aia생명',
            'nh농협생명',
            '롯데손해보험',
            '하나손해보험',
            'aig손해보험',
            '업계 1위',
            '최고 실적',
            '수상 실적',
            '계약 달성',
            '매출 달성',
            'mdrt',
        )
        findings = [
            (word, text)
            for text in rendered
            for word in forbidden
            if word in text.lower()
        ]
        self.assertEqual(findings, [])


class ShowcaseValidationTests(ShowcaseSpecTestCase):
    def test_checked_in_specs_pass_validation(self):
        self.assertIsNone(specs.validate_showcase_specs())

    def test_validation_rejects_customer_count_drift(self):
        with patch.object(specs, 'CUSTOMERS', specs.CUSTOMERS[:-1]):
            with self.assertRaises(CommandError):
                specs.validate_showcase_specs()

    def test_validation_rejects_duplicate_phone(self):
        duplicate = replace(
            specs.CUSTOMERS[-1],
            phone=specs.CUSTOMERS[0].phone,
        )
        with patch.object(
            specs,
            'CUSTOMERS',
            specs.CUSTOMERS[:-1] + (duplicate,),
        ):
            with self.assertRaises(CommandError):
                specs.validate_showcase_specs()

    def test_validation_rejects_unknown_policy_customer(self):
        orphan = replace(
            specs.INSURANCES[0],
            customer_key='unknown-customer',
        )
        with patch.object(
            specs,
            'INSURANCES',
            (orphan,) + specs.INSURANCES[1:],
        ):
            with self.assertRaises(CommandError):
                specs.validate_showcase_specs()

    def test_validation_rejects_policy_outside_recent_six_months(self):
        stale = replace(
            specs.INSURANCES[0],
            registered_month_offset=6,
        )
        with patch.object(
            specs,
            'INSURANCES',
            (stale,) + specs.INSURANCES[1:],
        ):
            with self.assertRaises(CommandError):
                specs.validate_showcase_specs()

    def test_validation_rejects_forbidden_rendered_copy(self):
        marked = replace(
            specs.CUSTOMERS[0],
            memo='촬영용 고객 자료',
        )
        with patch.object(
            specs,
            'CUSTOMERS',
            (marked,) + specs.CUSTOMERS[1:],
        ):
            with self.assertRaises(CommandError):
                specs.validate_showcase_specs()
