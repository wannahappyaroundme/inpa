from django.test import SimpleTestCase

from .import_contract import CoverageCandidate, MaskedLine
from .import_validation import validate_draft


def _evidence(value, line_id):
    return {'value': value, 'evidence_line_ids': [line_id]}


def _policy(**overrides):
    policy = {
        'carrier_name': _evidence('한빛생명', 'p01-l001'),
        'company_code': _evidence(1, 'p01-l001'),
        'insurance_type': _evidence('life', 'p01-l001'),
        'product_name': _evidence('건강보험', 'p01-l001'),
        'contract_date': _evidence('2024.01.01', 'p01-l002'),
        'expiry_date': _evidence('2044.01.01', 'p01-l002'),
        'monthly_premium': _evidence(30_000, 'p01-l003'),
    }
    policy.update(overrides)
    return policy


def _row(row_id, candidate_id, line_id, **overrides):
    row = {
        'row_id': row_id,
        'raw_name': '일반암진단비',
        'assurance_amount': 30_000_000,
        'premium': 30_000,
        'is_renewal': False,
        'renewal_period': None,
        'payment_period': 20,
        'payment_period_unit': 'years',
        'warranty_period': 100,
        'warranty_period_unit': 'age',
        'disposition': 'assigned',
        'standard_category': '진단-암',
        'standard_subcategory': '일반암',
        'standard_detail_name': '일반암진단비',
        'exclusion_reason': None,
        'source_candidate_ids': [candidate_id],
        'evidence_line_ids': [line_id],
    }
    row.update(overrides)
    return row


def _line(line_id, text, *, page=1, line=1):
    return MaskedLine(
        line_id=line_id, page=page, line=line, text_masked=text)


def _candidate(candidate_id, line_id, text):
    return CoverageCandidate(
        candidate_id=candidate_id,
        evidence_line_ids=(line_id,),
        text_masked=text,
    )


class DraftValidationTests(SimpleTestCase):
    def _validate_single_mapping(self, raw_name, **mapping):
        coverage_text = (
            f'{raw_name} 가입금액 3,000만원 보험료 30,000원')
        lines = (
            _line('p01-l001', '한빛생명 건강보험'),
            _line('p01-l002', '계약일 2024.01.01 만기일 2044.01.01', line=2),
            _line('p01-l003', '월 보험료 30,000원', line=3),
            _line('p01-l004', coverage_text, line=4),
        )
        candidates = (_candidate('c00001', 'p01-l004', coverage_text),)
        return validate_draft(lines, candidates, {
            'policy': _policy(),
            'coverage_rows': [
                _row(
                    'r00001', 'c00001', 'p01-l004',
                    raw_name=raw_name,
                    **mapping,
                ),
            ],
        })

    def test_ambiguous_cancer_mapping_requires_planner_review(self):
        cases = (
            (
                '특정(소액)암진단비',
                {
                    'standard_category': '진단-암',
                    'standard_subcategory': '유사암/소액암',
                    'standard_detail_name': '소액암진단비',
                },
            ),
            (
                '특정(소액)암진단금',
                {
                    'standard_category': '진단-암',
                    'standard_subcategory': '유사암/소액암',
                    'standard_detail_name': '소액암진단비',
                },
            ),
            (
                '암진단비(유사암포함)',
                {
                    'standard_category': '진단-암',
                    'standard_subcategory': '일반암',
                    'standard_detail_name': '일반암진단비',
                },
            ),
        )

        for raw_name, mapping in cases:
            with self.subTest(raw_name=raw_name):
                result = self._validate_single_mapping(raw_name, **mapping)
                row = result.draft['coverage_rows'][0]

                self.assertEqual(row['state'], 'needs_review')
                self.assertIn(
                    'STANDARD_MAPPING_AMBIGUOUS',
                    row['review_reason_codes'],
                )
                self.assertGreater(result.summary['unresolved_count'], 0)

    def test_planner_mapping_edit_resolves_ambiguous_cancer_review(self):
        raw_name = '특정(소액)암진단비'
        coverage_text = (
            f'{raw_name} 가입금액 3,000만원 보험료 30,000원')
        lines = (
            _line('p01-l001', '한빛생명 건강보험'),
            _line('p01-l002', '계약일 2024.01.01 만기일 2044.01.01', line=2),
            _line('p01-l003', '월 보험료 30,000원', line=3),
            _line('p01-l004', coverage_text, line=4),
        )
        candidates = (_candidate('c00001', 'p01-l004', coverage_text),)
        row = _row(
            'r00001', 'c00001', 'p01-l004',
            raw_name=raw_name,
            standard_category='진단-암',
            standard_subcategory='유사암/소액암',
            standard_detail_name='소액암진단비',
        )
        row['manual_fields'] = ['standard_detail_name']

        result = validate_draft(
            lines,
            candidates,
            {'policy': _policy(), 'coverage_rows': [row]},
            allow_manual=True,
        )

        reviewed = result.draft['coverage_rows'][0]
        self.assertEqual(reviewed['state'], 'manual')
        self.assertNotIn(
            'STANDARD_MAPPING_AMBIGUOUS',
            reviewed['review_reason_codes'],
        )
        self.assertEqual(result.summary['unresolved_count'], 0)

    def test_dosu_mapping_to_mri_is_a_review_block(self):
        result = self._validate_single_mapping(
            '비급여도수치료실손',
            standard_category='실손의료비',
            standard_subcategory='비급여',
            standard_detail_name='실손비급여MRI',
        )
        row = result.draft['coverage_rows'][0]

        self.assertEqual(row['state'], 'needs_review')
        self.assertIn(
            'STANDARD_MAPPING_CONTRADICTION',
            row['review_reason_codes'],
        )
        self.assertGreater(result.summary['unresolved_count'], 0)

    def test_dosu_mapping_to_dosu_remains_review_ready(self):
        result = self._validate_single_mapping(
            '비급여도수치료실손',
            standard_category='실손의료비',
            standard_subcategory='비급여',
            standard_detail_name='실손비급여도수치료',
        )
        row = result.draft['coverage_rows'][0]

        self.assertEqual(row['state'], 'review_ready')
        self.assertNotIn(
            'STANDARD_MAPPING_CONTRADICTION',
            row['review_reason_codes'],
        )

    def test_mri_mapping_to_dosu_is_a_review_block(self):
        result = self._validate_single_mapping(
            '비급여MRI촬영료(실손)',
            standard_category='실손의료비',
            standard_subcategory='비급여',
            standard_detail_name='실손비급여도수치료',
        )
        row = result.draft['coverage_rows'][0]

        self.assertEqual(row['state'], 'needs_review')
        self.assertIn(
            'STANDARD_MAPPING_CONTRADICTION',
            row['review_reason_codes'],
        )

    def test_assigned_coverage_requires_assurance_amount(self):
        coverage_text = '일반암진단비 보험료 30,000원'
        lines = (
            _line('p01-l001', '한빛생명 건강보험'),
            _line('p01-l002', '계약일 2024.01.01 만기일 2044.01.01', line=2),
            _line('p01-l003', '월 보험료 30,000원', line=3),
            _line('p01-l004', coverage_text, line=4),
        )
        candidates = (_candidate('c00001', 'p01-l004', coverage_text),)

        result = validate_draft(lines, candidates, {
            'policy': _policy(),
            'coverage_rows': [
                _row(
                    'r00001', 'c00001', 'p01-l004',
                    assurance_amount=None,
                ),
            ],
        })

        issue = next(
            issue for issue in result.issues
            if issue.code == 'ASSURANCE_AMOUNT_REQUIRED'
        )
        self.assertEqual(issue.state, 'invalid')
        self.assertEqual(issue.field, 'assurance_amount')
        self.assertGreater(result.summary['unresolved_count'], 0)

    def test_mixed_known_and_unknown_coverage_premiums_are_incomplete(self):
        first_text = '일반암진단비 3,000만원 보험료 20,000원'
        second_text = '일반암진단비 3,000만원'
        lines = (
            _line('p01-l001', '한빛생명 건강보험'),
            _line('p01-l002', '계약일 2024.01.01 만기일 2044.01.01', line=2),
            _line('p01-l003', '월 보험료 미표기', line=3),
            _line('p01-l004', first_text, line=4),
            _line('p01-l005', second_text, line=5),
        )
        candidates = (
            _candidate('c00001', 'p01-l004', first_text),
            _candidate('c00002', 'p01-l005', second_text),
        )

        result = validate_draft(lines, candidates, {
            'policy': _policy(
                monthly_premium=_evidence(None, 'p01-l003'),
            ),
            'coverage_rows': [
                _row(
                    'r00001', 'c00001', 'p01-l004',
                    premium=20_000,
                ),
                _row(
                    'r00002', 'c00002', 'p01-l005',
                    premium=None,
                ),
            ],
        })

        self.assertIn('PREMIUM_SUM_INCOMPLETE', {
            issue.code for issue in result.issues
        })
        self.assertGreater(result.summary['unresolved_count'], 0)

    def test_provider_cannot_self_declare_manual_to_bypass_evidence(self):
        coverage_text = (
            '일반암진단비 가입금액 3,000만원 보험료 30,000원')
        lines = (
            _line('p01-l001', '한빛생명 건강보험'),
            _line('p01-l002', '계약일 2024.01.01 만기일 2044.01.01', line=2),
            _line('p01-l003', '월 보험료 30,000원', line=3),
            _line('p01-l004', coverage_text, line=4),
        )
        candidates = (_candidate('c00001', 'p01-l004', coverage_text),)
        row = _row(
            'r00001', 'c00001', 'p01-l004',
            assurance_amount=50_000_000,
            state='manual',
        )
        row['manual_fields'] = ['assurance_amount']
        row['confirmed_review_codes'] = ['CARRIER_MANUAL_REVIEW']

        result = validate_draft(lines, candidates, {
            'policy': _policy(),
            'coverage_rows': [row],
        })

        self.assertIn('AMOUNT_EVIDENCE_MISMATCH', {
            issue.code for issue in result.issues
        })
        self.assertEqual(
            result.draft['coverage_rows'][0]['state'], 'no_evidence')
        self.assertNotIn(
            'manual_fields', result.draft['coverage_rows'][0])
        self.assertNotIn(
            'confirmed_review_codes', result.draft['coverage_rows'][0])

    def test_candidate_conservation_assigned_unmatched_excluded_equals_detected(self):
        lines = (
            _line('p01-l001', '한빛생명 건강보험'),
            _line('p01-l002', '계약일 2024.01.01 만기일 2044.01.01', line=2),
            _line('p01-l003', '월 보험료 30,000원', line=3),
            _line('p01-l004', '일반암진단비 3,000만원 보험료 30,000원', line=4),
            _line('p01-l005', '문서 안내 행', line=5),
            _line('p01-l006', '표준 위치를 찾지 못한 담보 100만원', line=6),
        )
        candidates = (
            _candidate('c00001', 'p01-l004', lines[3].text_masked),
            _candidate('c00002', 'p01-l005', lines[4].text_masked),
            _candidate('c00003', 'p01-l006', lines[5].text_masked),
        )
        payload = {
            'policy': _policy(),
            'coverage_rows': [
                _row('r00001', 'c00001', 'p01-l004'),
                _row(
                    'r00002', 'c00002', 'p01-l005',
                    raw_name='문서 안내 행', assurance_amount=None,
                    premium=None, disposition='intentionally_excluded',
                    standard_category=None, standard_subcategory=None,
                    standard_detail_name=None, exclusion_reason='header'),
            ],
        }

        result = validate_draft(lines, candidates, payload)

        self.assertEqual(
            result.summary['detected_candidates'],
            result.summary['assigned']
            + result.summary['unmatched']
            + result.summary['intentionally_excluded'],
        )
        self.assertEqual(result.summary['detected_candidates'], 3)
        self.assertEqual((result.summary['assigned'],
                          result.summary['unmatched'],
                          result.summary['intentionally_excluded']),
                         (1, 1, 1))
        resurrected = next(
            row for row in result.draft['coverage_rows']
            if row['source_candidate_ids'] == ['c00003'])
        self.assertEqual(resurrected['state'], 'unmatched')
        self.assertIn('CLAUDE_OMITTED_CANDIDATE',
                      resurrected['review_reason_codes'])

    def test_server_excluded_row_ignores_content_errors_but_keeps_disposition(self):
        coverage_text = (
            '일반암진단비 가입금액 3,000만원 보험료 30,000원')
        lines = (
            _line('p01-l001', '한빛생명 건강보험'),
            _line('p01-l002', '계약일 2024.01.01 만기일 2044.01.01', line=2),
            _line('p01-l003', '월 보험료 30,000원', line=3),
            _line('p01-l004', coverage_text, line=4),
        )
        candidates = (_candidate('c00001', 'p01-l004', coverage_text),)
        excluded = _row(
            'r00001', 'c00001', 'missing-line',
            raw_name='', assurance_amount=-1, premium=-1,
            is_renewal=True, renewal_period=None,
            payment_period=-1, payment_period_unit='lifetime',
            warranty_period=-1, warranty_period_unit='years',
            disposition='intentionally_excluded',
            standard_category=None, standard_subcategory=None,
            standard_detail_name=None,
            exclusion_reason='분석 대상이 아닌 문서 안내 행',
            duplicate_of_row_id=None,
        )
        excluded['manual_fields'] = ['disposition', 'exclusion_reason']

        result = validate_draft(lines, candidates, {
            'policy': _policy(),
            'coverage_rows': [excluded],
        }, allow_manual=True)

        row = result.draft['coverage_rows'][0]
        self.assertEqual(row['state'], 'manual')
        self.assertEqual(row['review_reason_codes'], [])
        self.assertEqual(result.summary['unresolved_count'], 0)
        self.assertEqual(result.summary['intentionally_excluded'], 1)

    def test_value_without_matching_evidence_is_no_evidence(self):
        line_text = '일반암진단비 3,000만원 보험료 30,000원'
        lines = (
            _line('p01-l001', '한빛생명 건강보험'),
            _line('p01-l002', '계약일 2024.01.01 만기일 2044.01.01', line=2),
            _line('p01-l003', '월 보험료 30,000원', line=3),
            _line('p01-l004', line_text, line=4),
        )
        candidates = (_candidate('c00001', 'p01-l004', line_text),)
        payload = {
            'policy': _policy(),
            'coverage_rows': [
                _row('r00001', 'c00001', 'p01-l004',
                     assurance_amount=50_000_000),
            ],
        }

        result = validate_draft(lines, candidates, payload)

        issue = next(
            issue for issue in result.issues
            if issue.code == 'AMOUNT_EVIDENCE_MISMATCH')
        self.assertEqual(issue.state, 'no_evidence')
        self.assertEqual(result.draft['coverage_rows'][0]['state'],
                         'no_evidence')
        self.assertEqual(
            result.draft['coverage_rows'][0]['assurance_amount'],
            50_000_000,
        )

    def test_validator_flags_date_order_duplicate_and_premium_mismatch(self):
        coverage_text = '일반암진단비 3,000만원 보험료 30,000원'
        lines = (
            _line('p01-l001', '한빛생명 건강보험'),
            _line('p01-l002', '계약일 2044.01.01 만기일 2024.01.01', line=2),
            _line('p01-l003', '월 보험료 50,000원', line=3),
            _line('p01-l004', coverage_text, line=4),
        )
        candidates = (_candidate('c00001', 'p01-l004', coverage_text),)
        payload = {
            'policy': _policy(
                contract_date=_evidence('2044.01.01', 'p01-l002'),
                expiry_date=_evidence('2024.01.01', 'p01-l002'),
                monthly_premium=_evidence(50_000, 'p01-l003')),
            'coverage_rows': [
                _row('r00001', 'c00001', 'p01-l004'),
                _row('r00002', 'c00001', 'p01-l004'),
            ],
        }

        result = validate_draft(lines, candidates, payload)

        self.assertEqual(
            {item.code for item in result.issues},
            {
                'CONTRACT_AFTER_EXPIRY',
                'DUPLICATE_SOURCE_ROW',
                'PREMIUM_SUM_MISMATCH',
            },
        )

    def test_won_manwon_and_korean_large_units_match_without_mutating_value(self):
        cases = (
            ('가입금액 50,000,000원', 50_000_000),
            ('가입금액 5천만원', 50_000_000),
            ('가입금액 3,000만원', 30_000_000),
            ('가입금액 1억원', 100_000_000),
        )

        for text, amount in cases:
            with self.subTest(text=text):
                lines = (
                    _line('p01-l001', '한빛생명 건강보험'),
                    _line('p01-l002', '계약일 2024.01.01 만기일 2044.01.01', line=2),
                    _line('p01-l003', '월 보험료 0원', line=3),
                    _line('p01-l004', text, line=4),
                )
                candidates = (_candidate('c00001', 'p01-l004', text),)
                payload = {
                    'policy': _policy(monthly_premium=_evidence(0, 'p01-l003')),
                    'coverage_rows': [
                        _row('r00001', 'c00001', 'p01-l004',
                             assurance_amount=amount, premium=None),
                    ],
                }

                result = validate_draft(lines, candidates, payload)

                self.assertNotIn(
                    'AMOUNT_EVIDENCE_MISMATCH',
                    {issue.code for issue in result.issues},
                )
                self.assertEqual(
                    result.draft['coverage_rows'][0]['assurance_amount'],
                    amount,
                )

    def test_negative_and_invalid_renewal_combinations_are_invalid(self):
        text = '갱신형 일반암진단비 -1원 보험료 30,000원'
        lines = (
            _line('p01-l001', '한빛생명 건강보험'),
            _line('p01-l002', '계약일 2024.01.01 만기일 2044.01.01', line=2),
            _line('p01-l003', '월 보험료 30,000원', line=3),
            _line('p01-l004', text, line=4),
        )
        candidates = (_candidate('c00001', 'p01-l004', text),)
        payload = {
            'policy': _policy(),
            'coverage_rows': [
                _row(
                    'r00001', 'c00001', 'p01-l004',
                    assurance_amount=-1, is_renewal=True,
                    renewal_period=None, payment_period_unit='lifetime'),
            ],
        }

        result = validate_draft(lines, candidates, payload)

        self.assertTrue({
            'NEGATIVE_AMOUNT', 'INVALID_RENEWAL_PAYMENT_COMBINATION',
        }.issubset({issue.code for issue in result.issues}))
        self.assertEqual(result.draft['coverage_rows'][0]['state'], 'invalid')
        self.assertEqual(result.draft['coverage_rows'][0]['assurance_amount'],
                         -1)

    def test_carrier_and_insurance_type_contradiction_is_needs_review(self):
        text = '일반암진단비 3,000만원 보험료 30,000원'
        lines = (
            _line('p01-l001', '한빛생명 건강보험'),
            _line('p01-l002', '계약일 2024.01.01 만기일 2044.01.01', line=2),
            _line('p01-l003', '월 보험료 30,000원', line=3),
            _line('p01-l004', text, line=4),
        )
        candidates = (_candidate('c00001', 'p01-l004', text),)
        payload = {
            'policy': _policy(
                insurance_type=_evidence('loss', 'p01-l001')),
            'coverage_rows': [
                _row('r00001', 'c00001', 'p01-l004'),
            ],
        }

        result = validate_draft(lines, candidates, payload)

        issue = next(
            issue for issue in result.issues
            if issue.code == 'CARRIER_TYPE_CONTRADICTION')
        self.assertEqual(issue.state, 'needs_review')
        self.assertEqual(result.draft['policy']['insurance_type']['value'],
                         'loss')

    def test_invalid_standard_path_and_carrier_code_are_never_review_ready(self):
        coverage_text = '일반암진단비 3,000만원 보험료 30,000원'
        lines = (
            _line('p01-l001', '삼성생명 건강보험'),
            _line('p01-l002', '계약일 2024.01.01 만기일 2044.01.01', line=2),
            _line('p01-l003', '월 보험료 30,000원', line=3),
            _line('p01-l004', coverage_text, line=4),
        )
        candidates = (_candidate('c00001', 'p01-l004', coverage_text),)
        payload = {
            'policy': _policy(
                carrier_name=_evidence('삼성생명', 'p01-l001'),
                company_code=_evidence(2, 'p01-l001')),
            'coverage_rows': [
                _row(
                    'r00001', 'c00001', 'p01-l004',
                    standard_category='지어낸 분류',
                    standard_subcategory='암',
                    standard_detail_name='임의 담보'),
            ],
        }

        result = validate_draft(lines, candidates, payload)

        self.assertTrue({
            'CARRIER_CODE_CONTRADICTION', 'STANDARD_MAPPING_INVALID',
        }.issubset({issue.code for issue in result.issues}))
        self.assertEqual(
            result.draft['policy']['company_code']['state'], 'needs_review')
        self.assertEqual(
            result.draft['coverage_rows'][0]['state'], 'unmatched')

    def test_labeled_amount_roles_reject_wrong_or_swapped_values(self):
        coverage_text = (
            '일반암진단비 가입금액 3,000만원 보험료 30,000원')
        lines = (
            _line('p01-l001', '한빛생명 건강보험'),
            _line('p01-l002', '계약일 2024.01.01 만기일 2044.01.01', line=2),
            _line('p01-l003', '월 보험료 30,000원', line=3),
            _line('p01-l004', coverage_text, line=4),
        )
        candidates = (_candidate('c00001', 'p01-l004', coverage_text),)
        cases = (
            (30_000, 30_000, {'AMOUNT_EVIDENCE_MISMATCH'}),
            (30_000_000, 30_000_000, {'PREMIUM_EVIDENCE_MISMATCH'}),
            (
                30_000, 30_000_000,
                {'AMOUNT_EVIDENCE_MISMATCH', 'PREMIUM_EVIDENCE_MISMATCH'},
            ),
        )

        for assurance_amount, premium, expected_codes in cases:
            with self.subTest(
                    assurance_amount=assurance_amount, premium=premium):
                result = validate_draft(lines, candidates, {
                    'policy': _policy(),
                    'coverage_rows': [
                        _row(
                            'r00001', 'c00001', 'p01-l004',
                            assurance_amount=assurance_amount,
                            premium=premium),
                    ],
                })

                row = result.draft['coverage_rows'][0]
                self.assertTrue(
                    expected_codes.issubset(row['review_reason_codes']))
                self.assertNotEqual(row['state'], 'review_ready')

    def test_multiple_unlabeled_amounts_have_no_field_role_evidence(self):
        coverage_text = '일반암진단비 3,000만원 30,000원'
        lines = (
            _line('p01-l001', '한빛생명 건강보험'),
            _line('p01-l002', '계약일 2024.01.01 만기일 2044.01.01', line=2),
            _line('p01-l003', '월 보험료 30,000원', line=3),
            _line('p01-l004', coverage_text, line=4),
        )
        candidates = (_candidate('c00001', 'p01-l004', coverage_text),)

        result = validate_draft(lines, candidates, {
            'policy': _policy(),
            'coverage_rows': [
                _row('r00001', 'c00001', 'p01-l004'),
            ],
        })

        row = result.draft['coverage_rows'][0]
        self.assertTrue({
            'AMOUNT_EVIDENCE_MISMATCH', 'PREMIUM_EVIDENCE_MISMATCH',
        }.issubset(row['review_reason_codes']))
        self.assertEqual(row['state'], 'no_evidence')

    def test_composite_korean_money_and_date_formats_normalize(self):
        amount_cases = (
            '일반암진단비 가입금액 1억5천만원 보험료 30,000원',
            '일반암진단비 가입금액 1억 5,000만원 보험료 30,000원',
        )

        for coverage_text in amount_cases:
            with self.subTest(coverage_text=coverage_text):
                lines = (
                    _line('p01-l001', '한빛생명 건강보험'),
                    _line(
                        'p01-l002',
                        '계약일 2024년 1월 2일 만기일 2044/01/02',
                        line=2),
                    _line('p01-l003', '월 보험료 30,000원', line=3),
                    _line('p01-l004', coverage_text, line=4),
                )
                candidates = (
                    _candidate('c00001', 'p01-l004', coverage_text),)
                result = validate_draft(lines, candidates, {
                    'policy': _policy(
                        contract_date=_evidence('2024-01-02', 'p01-l002'),
                        expiry_date=_evidence('2044.01.02', 'p01-l002')),
                    'coverage_rows': [
                        _row(
                            'r00001', 'c00001', 'p01-l004',
                            assurance_amount=150_000_000),
                    ],
                })

                issue_codes = {issue.code for issue in result.issues}
                self.assertNotIn('AMOUNT_EVIDENCE_MISMATCH', issue_codes)
                self.assertNotIn('DATE_EVIDENCE_MISMATCH', issue_codes)
                self.assertNotIn('INVALID_DATE', issue_codes)
                self.assertEqual(
                    result.draft['coverage_rows'][0]['state'],
                    'review_ready',
                )

    def test_malformed_dates_are_invalid_or_have_no_evidence(self):
        coverage_text = (
            '일반암진단비 가입금액 3,000만원 보험료 30,000원')
        lines = (
            _line('p01-l001', '한빛생명 건강보험'),
            _line(
                'p01-l002',
                '계약일 2024년 13월 40일 만기일 2044/01/02',
                line=2),
            _line('p01-l003', '월 보험료 30,000원', line=3),
            _line('p01-l004', coverage_text, line=4),
        )
        candidates = (_candidate('c00001', 'p01-l004', coverage_text),)

        result = validate_draft(lines, candidates, {
            'policy': _policy(
                contract_date=_evidence('2024-13-40', 'p01-l002'),
                expiry_date=_evidence('2044-01-02', 'p01-l002')),
            'coverage_rows': [
                _row('r00001', 'c00001', 'p01-l004'),
            ],
        })

        self.assertIn('INVALID_DATE', {
            issue.code for issue in result.issues
            if issue.field == 'contract_date'
        })
        self.assertEqual(
            result.draft['policy']['contract_date']['state'], 'invalid')

    def test_duplicate_candidate_marks_every_row_and_uses_safe_bucket(self):
        coverage_text = (
            '일반암진단비 가입금액 3,000만원 보험료 30,000원')
        lines = (
            _line('p01-l001', '한빛생명 건강보험'),
            _line('p01-l002', '계약일 2024.01.01 만기일 2044.01.01', line=2),
            _line('p01-l003', '월 보험료 30,000원', line=3),
            _line('p01-l004', coverage_text, line=4),
        )
        candidates = (_candidate('c00001', 'p01-l004', coverage_text),)
        assigned = _row('r00001', 'c00001', 'p01-l004')
        excluded = _row(
            'r00002', 'c00001', 'p01-l004',
            disposition='intentionally_excluded',
            standard_category=None,
            standard_subcategory=None,
            standard_detail_name=None,
            exclusion_reason='문서 안내 행',
        )

        for coverage_rows in ([assigned, excluded], [excluded, assigned]):
            with self.subTest(order=[row['row_id'] for row in coverage_rows]):
                result = validate_draft(lines, candidates, {
                    'policy': _policy(),
                    'coverage_rows': coverage_rows,
                })

                for row in result.draft['coverage_rows']:
                    self.assertIn(
                        'DUPLICATE_SOURCE_ROW', row['review_reason_codes'])
                    self.assertNotEqual(row['state'], 'review_ready')
                self.assertEqual(result.summary['detected_candidates'], 1)
                self.assertEqual(result.summary['assigned'], 0)
                self.assertEqual(result.summary['unmatched'], 1)
                self.assertEqual(result.summary['intentionally_excluded'], 0)
                self.assertEqual(
                    result.summary['assigned']
                    + result.summary['unmatched']
                    + result.summary['intentionally_excluded'],
                    result.summary['detected_candidates'],
                )

    def test_valid_duplicate_disposition_converges_to_one_keeper(self):
        coverage_text = (
            '일반암진단비 가입금액 3,000만원 보험료 30,000원')
        lines = (
            _line('p01-l001', '한빛생명 건강보험'),
            _line('p01-l002', '계약일 2024.01.01 만기일 2044.01.01', line=2),
            _line('p01-l003', '월 보험료 30,000원', line=3),
            _line('p01-l004', coverage_text, line=4),
        )
        candidates = (_candidate('c00001', 'p01-l004', coverage_text),)
        duplicate = _row(
            'r00002', 'c00001', 'p01-l004',
            disposition='intentionally_excluded',
            standard_category=None, standard_subcategory=None,
            standard_detail_name=None,
            exclusion_reason='같은 담보가 두 번 표시됨',
            duplicate_of_row_id='r00001',
        )
        duplicate['manual_fields'] = [
            'disposition', 'exclusion_reason', 'duplicate_of_row_id']

        result = validate_draft(lines, candidates, {
            'policy': _policy(),
            'coverage_rows': [
                _row('r00001', 'c00001', 'p01-l004'),
                duplicate,
            ],
        }, allow_manual=True)

        rows = {row['row_id']: row for row in result.draft['coverage_rows']}
        self.assertNotIn('DUPLICATE_SOURCE_ROW', {
            issue.code for issue in result.issues
        })
        self.assertEqual(rows['r00001']['state'], 'review_ready')
        self.assertEqual(rows['r00002']['state'], 'manual')
        self.assertEqual(result.summary['unresolved_count'], 0)
        self.assertEqual(
            (result.summary['assigned'], result.summary['unmatched'],
             result.summary['intentionally_excluded']),
            (1, 0, 0),
        )

    def test_invalid_duplicate_graphs_stay_blocking(self):
        coverage_text = (
            '일반암진단비 가입금액 3,000만원 보험료 30,000원')
        other_text = '유사암진단비 가입금액 1,000만원 보험료 10,000원'
        lines = (
            _line('p01-l001', '한빛생명 건강보험'),
            _line('p01-l002', '계약일 2024.01.01 만기일 2044.01.01', line=2),
            _line('p01-l003', '월 보험료 30,000원', line=3),
            _line('p01-l004', coverage_text, line=4),
            _line('p01-l005', other_text, line=5),
        )
        candidates = (
            _candidate('c00001', 'p01-l004', coverage_text),
            _candidate('c00002', 'p01-l005', other_text),
        )

        def excluded(row_id, candidate_id, line_id, target_id):
            row = _row(
                row_id, candidate_id, line_id,
                disposition='intentionally_excluded',
                standard_category=None, standard_subcategory=None,
                standard_detail_name=None, exclusion_reason='중복',
                duplicate_of_row_id=target_id,
            )
            row['manual_fields'] = [
                'disposition', 'exclusion_reason', 'duplicate_of_row_id']
            return row

        cases = {
            'missing_target': [
                _row('r00001', 'c00001', 'p01-l004'),
                excluded('r00002', 'c00001', 'p01-l004', 'missing'),
            ],
            'self_target': [
                _row('r00001', 'c00001', 'p01-l004'),
                excluded('r00002', 'c00001', 'p01-l004', 'r00002'),
            ],
            'different_candidate': [
                _row('r00001', 'c00001', 'p01-l004'),
                excluded('r00002', 'c00002', 'p01-l005', 'r00001'),
            ],
            'multiple_keepers': [
                _row('r00001', 'c00001', 'p01-l004'),
                _row('r00002', 'c00001', 'p01-l004'),
            ],
            'cycle': [
                excluded('r00001', 'c00001', 'p01-l004', 'r00002'),
                excluded('r00002', 'c00001', 'p01-l004', 'r00001'),
            ],
        }

        for case, coverage_rows in cases.items():
            with self.subTest(case=case):
                result = validate_draft(lines, candidates, {
                    'policy': _policy(),
                    'coverage_rows': coverage_rows,
                }, allow_manual=True)

                self.assertIn('DUPLICATE_SOURCE_ROW', {
                    issue.code for issue in result.issues
                })
                self.assertGreater(result.summary['unresolved_count'], 0)
                self.assertEqual(
                    result.summary['assigned']
                    + result.summary['unmatched']
                    + result.summary['intentionally_excluded'],
                    result.summary['detected_candidates'],
                )

    def test_candidate_evidence_requires_intersection_and_allows_extra_lines(self):
        coverage_text = (
            '일반암진단비 가입금액 3,000만원 보험료 30,000원')
        lines = (
            _line('p01-l001', '한빛생명 건강보험'),
            _line('p01-l002', '계약일 2024.01.01 만기일 2044.01.01', line=2),
            _line('p01-l003', '월 보험료 30,000원', line=3),
            _line('p01-l004', coverage_text, line=4),
            _line('p01-l005', coverage_text, line=5),
        )
        candidates = (_candidate('c00001', 'p01-l004', coverage_text),)

        missing_link = validate_draft(lines, candidates, {
            'policy': _policy(),
            'coverage_rows': [
                _row('r00001', 'c00001', 'p01-l005'),
            ],
        })
        linked_with_context = validate_draft(lines, candidates, {
            'policy': _policy(),
            'coverage_rows': [
                _row(
                    'r00001', 'c00001', 'p01-l004',
                    evidence_line_ids=['p01-l004', 'p01-l005']),
            ],
        })

        missing_row = missing_link.draft['coverage_rows'][0]
        self.assertIn(
            'EVIDENCE_CANDIDATE_MISMATCH',
            missing_row['review_reason_codes'],
        )
        self.assertNotEqual(missing_row['state'], 'review_ready')
        linked_row = linked_with_context.draft['coverage_rows'][0]
        self.assertNotIn(
            'EVIDENCE_CANDIDATE_MISMATCH',
            linked_row['review_reason_codes'],
        )
        self.assertEqual(linked_row['state'], 'review_ready')

    def test_bypassed_blank_row_identity_is_invalid_and_never_rewritten(self):
        coverage_text = (
            '일반암진단비 가입금액 3,000만원 보험료 30,000원')
        lines = (
            _line('p01-l001', '한빛생명 건강보험'),
            _line('p01-l002', '계약일 2024.01.01 만기일 2044.01.01', line=2),
            _line('p01-l003', '월 보험료 30,000원', line=3),
            _line('p01-l004', coverage_text, line=4),
        )
        candidates = (_candidate('c00001', 'p01-l004', coverage_text),)

        result = validate_draft(lines, candidates, {
            'policy': _policy(),
            'coverage_rows': [
                _row('', 'c00001', 'p01-l004', raw_name='   '),
            ],
        })

        row = result.draft['coverage_rows'][0]
        self.assertEqual(row['row_id'], '')
        self.assertEqual(row['raw_name'], '   ')
        self.assertTrue({
            'INVALID_ROW_ID', 'RAW_NAME_REQUIRED',
        }.issubset(row['review_reason_codes']))
        self.assertEqual(row['state'], 'invalid')

    def test_negative_policy_monthly_premium_is_invalid(self):
        coverage_text = '일반암진단비 가입금액 3,000만원'
        lines = (
            _line('p01-l001', '한빛생명 건강보험'),
            _line('p01-l002', '계약일 2024.01.01 만기일 2044.01.01', line=2),
            _line('p01-l003', '월 보험료 -30,000원', line=3),
            _line('p01-l004', coverage_text, line=4),
        )
        candidates = (_candidate('c00001', 'p01-l004', coverage_text),)

        result = validate_draft(lines, candidates, {
            'policy': _policy(
                monthly_premium=_evidence(-30_000, 'p01-l003')),
            'coverage_rows': [
                _row(
                    'r00001', 'c00001', 'p01-l004', premium=None),
            ],
        })

        premium = result.draft['policy']['monthly_premium']
        self.assertIn('NEGATIVE_PREMIUM', premium['review_reason_codes'])
        self.assertEqual(premium['value'], -30_000)
        self.assertEqual(premium['state'], 'invalid')

    def test_period_value_unit_and_lifetime_consistency(self):
        coverage_text = (
            '일반암진단비 가입금액 3,000만원 보험료 30,000원')
        lines = (
            _line('p01-l001', '한빛생명 건강보험'),
            _line('p01-l002', '계약일 2024.01.01 만기일 2044.01.01', line=2),
            _line('p01-l003', '월 보험료 30,000원', line=3),
            _line('p01-l004', coverage_text, line=4),
        )
        candidates = (_candidate('c00001', 'p01-l004', coverage_text),)
        cases = (
            (
                {'payment_period': 20, 'payment_period_unit': None},
                'PERIOD_UNIT_REQUIRED',
            ),
            (
                {'warranty_period': None, 'warranty_period_unit': 'years'},
                'PERIOD_VALUE_REQUIRED',
            ),
            (
                {'payment_period': 20, 'payment_period_unit': 'lifetime'},
                'LIFETIME_PERIOD_HAS_VALUE',
            ),
            (
                {'is_renewal': None, 'renewal_period': 10},
                'RENEWAL_FLAG_REQUIRED',
            ),
        )

        for overrides, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                result = validate_draft(lines, candidates, {
                    'policy': _policy(),
                    'coverage_rows': [
                        _row(
                            'r00001', 'c00001', 'p01-l004', **overrides),
                    ],
                })

                row = result.draft['coverage_rows'][0]
                self.assertIn(expected_code, row['review_reason_codes'])
                self.assertNotEqual(row['state'], 'review_ready')

    def test_payment_period_cannot_exceed_same_unit_warranty_period(self):
        coverage_text = (
            '일반암진단비 가입금액 3,000만원 보험료 30,000원')
        lines = (
            _line('p01-l001', '한빛생명 건강보험'),
            _line('p01-l002', '계약일 2024.01.01 만기일 2044.01.01', line=2),
            _line('p01-l003', '월 보험료 30,000원', line=3),
            _line('p01-l004', coverage_text, line=4),
        )
        candidates = (_candidate('c00001', 'p01-l004', coverage_text),)

        result = validate_draft(lines, candidates, {
            'policy': _policy(),
            'coverage_rows': [
                _row(
                    'r00001', 'c00001', 'p01-l004',
                    payment_period=30,
                    payment_period_unit='years',
                    warranty_period=20,
                    warranty_period_unit='years'),
            ],
        })

        row = result.draft['coverage_rows'][0]
        self.assertIn(
            'PAYMENT_PERIOD_EXCEEDS_WARRANTY',
            row['review_reason_codes'],
        )
        self.assertEqual(row['state'], 'invalid')

    def test_one_unlabeled_occurrence_cannot_prove_both_money_fields(self):
        coverage_text = '일반암진단비 3,000만원'
        lines = (
            _line('p01-l001', '한빛생명 건강보험'),
            _line('p01-l002', '계약일 2024.01.01 만기일 2044.01.01', line=2),
            _line('p01-l003', '월 보험료 3,000만원', line=3),
            _line('p01-l004', coverage_text, line=4),
        )
        candidates = (_candidate('c00001', 'p01-l004', coverage_text),)

        result = validate_draft(lines, candidates, {
            'policy': _policy(
                monthly_premium=_evidence(30_000_000, 'p01-l003')),
            'coverage_rows': [
                _row(
                    'r00001', 'c00001', 'p01-l004',
                    assurance_amount=30_000_000,
                    premium=30_000_000),
            ],
        })

        row = result.draft['coverage_rows'][0]
        self.assertTrue({
            'AMOUNT_EVIDENCE_MISMATCH',
            'PREMIUM_EVIDENCE_MISMATCH',
            'AMOUNT_ROLE_AMBIGUOUS',
        }.issubset(row['review_reason_codes']))
        self.assertEqual(row['state'], 'no_evidence')
        self.assertEqual(row['assurance_amount'], 30_000_000)
        self.assertEqual(row['premium'], 30_000_000)

    def test_distinct_labeled_money_fields_are_review_ready(self):
        coverage_text = (
            '일반암진단비 가입금액 3,000만원 보험료 30,000원')
        lines = (
            _line('p01-l001', '한빛생명 건강보험'),
            _line('p01-l002', '계약일 2024.01.01 만기일 2044.01.01', line=2),
            _line('p01-l003', '월 보험료 30,000원', line=3),
            _line('p01-l004', coverage_text, line=4),
        )
        candidates = (_candidate('c00001', 'p01-l004', coverage_text),)

        result = validate_draft(lines, candidates, {
            'policy': _policy(),
            'coverage_rows': [
                _row('r00001', 'c00001', 'p01-l004'),
            ],
        })

        self.assertEqual(
            result.draft['coverage_rows'][0]['state'], 'review_ready')

    def test_single_populated_money_field_accepts_one_unlabeled_occurrence(self):
        coverage_text = '일반암진단비 3,000만원'
        lines = (
            _line('p01-l001', '한빛생명 건강보험'),
            _line('p01-l002', '계약일 2024.01.01 만기일 2044.01.01', line=2),
            _line('p01-l003', '월 보험료 30,000원', line=3),
            _line('p01-l004', coverage_text, line=4),
        )
        candidates = (_candidate('c00001', 'p01-l004', coverage_text),)

        result = validate_draft(lines, candidates, {
            'policy': _policy(),
            'coverage_rows': [
                _row(
                    'r00001', 'c00001', 'p01-l004', premium=None),
            ],
        })

        self.assertEqual(
            result.draft['coverage_rows'][0]['state'], 'review_ready')
