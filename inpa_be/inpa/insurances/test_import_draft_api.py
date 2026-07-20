import copy
import json
import uuid
from dataclasses import asdict
from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User
from inpa.customers.models import Customer

from .import_contract import CoverageCandidate, MaskedLine
from .import_validation import validate_draft
from .models import (
    InsuranceExtractionJob,
    InsuranceExtractionResult,
    InsuranceImportCommand,
)
from .tasks import NORMALIZATION_VERSION


def _planner(email):
    user = User.objects.create_user(email=email, password='inpaPass123!')
    user.is_active = True
    user.save(update_fields=['is_active'])
    Profile.objects.create(user=user, email_verified_at=timezone.now())
    client = APIClient()
    client.force_authenticate(user=user)
    return user, client


def _draft_material():
    lines = (
        MaskedLine(
            line_id='p01-l001', page=1, line=1,
            text_masked='일반암진단비 가입금액 3,000만원 보험료 30,000원'),
        MaskedLine(
            line_id='p01-l002', page=1, line=2,
            text_masked='유사암진단비 가입금액 1,000만원 보험료 10,000원'),
    )
    candidates = (
        CoverageCandidate(
            candidate_id='c00001', evidence_line_ids=('p01-l001',),
            text_masked=lines[0].text_masked),
        CoverageCandidate(
            candidate_id='c00002', evidence_line_ids=('p01-l002',),
            text_masked=lines[1].text_masked),
    )
    evidence = {'value': None, 'evidence_line_ids': []}
    payload = {
        'schema_version': 'insurance-review-v1',
        'policy': {
            'carrier_name': copy.deepcopy(evidence),
            'company_code': copy.deepcopy(evidence),
            'insurance_type': copy.deepcopy(evidence),
            'product_name': copy.deepcopy(evidence),
            'contract_date': copy.deepcopy(evidence),
            'expiry_date': copy.deepcopy(evidence),
            'monthly_premium': copy.deepcopy(evidence),
        },
        'coverage_rows': [
            {
                'row_id': 'row-1',
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
                'source_candidate_ids': ['c00001'],
                'evidence_line_ids': ['p01-l001'],
            },
            {
                'row_id': 'row-2',
                'raw_name': '유사암진단비',
                'assurance_amount': 10_000_000,
                'premium': 10_000,
                'is_renewal': False,
                'renewal_period': None,
                'payment_period': 20,
                'payment_period_unit': 'years',
                'warranty_period': 100,
                'warranty_period_unit': 'age',
                'disposition': 'assigned',
                'standard_category': '진단-암',
                'standard_subcategory': '유사암/소액암',
                'standard_detail_name': '유사암진단비',
                'exclusion_reason': None,
                'source_candidate_ids': ['c00002'],
                'evidence_line_ids': ['p01-l002'],
            },
        ],
    }
    validated = validate_draft(lines, candidates, payload)
    return lines, candidates, validated.draft, validated.summary


@override_settings(INSURANCE_REVIEW_GATE_ENABLED=True)
class InsuranceImportDraftAPITests(TestCase):
    def setUp(self):
        self.owner, self.client = _planner('draft-owner@test.com')
        self.foreign, self.foreign_client = _planner(
            'draft-foreign@test.com')
        self.customer = Customer.objects.create(
            owner=self.owner, name='내 고객', mobile_phone_number='010')
        self.lines, self.candidates, draft, summary = _draft_material()
        self.job = InsuranceExtractionJob.objects.create(
            owner=self.owner,
            customer=self.customer,
            intent='add',
            portfolio_type=1,
            status='review_required',
            file_sha256='a' * 64,
            file_size=100,
            page_count=1,
            safe_display_name='policy.pdf',
            source_expires_at=timezone.now() + timedelta(hours=1),
            masked_lines=[asdict(line) for line in self.lines],
            draft_payload=draft,
            validation_summary={
                **summary,
                'intake_candidates': [
                    {**asdict(candidate),
                     'evidence_line_ids': list(candidate.evidence_line_ids)}
                    for candidate in self.candidates
                ],
                '_system': {'credit_consumed': True},
            },
            normalization_version=NORMALIZATION_VERSION,
        )
        self.job.source_storage_key = (
            f'insurance-imports/{self.owner.pk}/{self.customer.pk}/'
            f'{self.job.id}/source.pdf')
        self.job.save(update_fields=['source_storage_key'])
        summary = copy.deepcopy(self.job.validation_summary)
        summary['_system']['source_readability'] = {
            'page_count': 1,
            'image_only_page_count': 0,
            'image_only_pages': [],
            'quarantined_line_count': 0,
            'quarantined_pages': [],
            'analysis_signal_quarantined_line_count': 0,
            'analysis_signal_quarantined_pages': [],
            'pages_requiring_manual_source_review': [],
        }
        self.job.validation_summary = summary
        self.job.save(update_fields=['validation_summary'])
        InsuranceExtractionResult.objects.create(
            job=self.job,
            provider='claude',
            model_id='env-model',
            outcome='review_required',
            structured_payload={'raw_provider_secret': 'do-not-return'},
        )

    @property
    def draft_url(self):
        return f'/api/v1/insurance-imports/{self.job.id}/draft/'

    @property
    def cancel_url(self):
        return f'/api/v1/insurance-imports/{self.job.id}/cancel/'

    def patch(self, body, *, key=None, client=None):
        return (client or self.client).patch(
            self.draft_url,
            body,
            format='json',
            HTTP_IDEMPOTENCY_KEY=str(key or uuid.uuid4()),
        )

    def add_coverage_action(self, **overrides):
        action = {
            'action': 'add',
            'raw_name': '골절수술비',
            'assurance_amount': 1_000_000,
            'premium': 1_000,
            'is_renewal': False,
            'payment_period': 20,
            'payment_period_unit': 'years',
            'warranty_period': 20,
            'warranty_period_unit': 'years',
            'standard_category': '수술비',
            'standard_subcategory': '특수수술',
            'standard_detail_name': '골절수술비',
        }
        action.update(overrides)
        return action

    def set_amount_evidence_mismatch(self):
        draft = copy.deepcopy(self.job.draft_payload)
        draft['coverage_rows'][0]['assurance_amount'] = 99_000_000
        validation = validate_draft(self.lines, self.candidates, draft)
        summary = copy.deepcopy(self.job.validation_summary)
        summary.update(validation.summary)
        self.job.draft_payload = validation.draft
        self.job.validation_summary = summary
        self.job.save(update_fields=['draft_payload', 'validation_summary'])

    def set_force_manual_review(self):
        draft = copy.deepcopy(self.job.draft_payload)
        issues = draft['validation']['issues']
        for row in draft['coverage_rows']:
            row['state'] = 'needs_review'
            row['review_reason_codes'] = ['CARRIER_MANUAL_REVIEW']
            issues.append({
                'code': 'CARRIER_MANUAL_REVIEW',
                'state': 'needs_review',
                'scope': 'coverage',
                'row_id': row['row_id'],
                'field': 'company_code',
            })
        draft['validation']['unresolved_count'] = len(
            draft['coverage_rows'])
        summary = copy.deepcopy(self.job.validation_summary)
        summary.update({
            'unresolved_count': len(draft['coverage_rows']),
            'issue_count': len(issues),
        })
        summary.setdefault('_system', {})['force_manual_review'] = True
        self.job.draft_payload = draft
        self.job.validation_summary = summary
        self.job.save(update_fields=['draft_payload', 'validation_summary'])

    def set_duplicate_source_rows(self):
        draft = copy.deepcopy(self.job.draft_payload)
        first = draft['coverage_rows'][0]
        second = draft['coverage_rows'][1]
        second['raw_name'] = first['raw_name']
        second['assurance_amount'] = first['assurance_amount']
        second['premium'] = first['premium']
        second['source_candidate_ids'] = ['c00001']
        second['evidence_line_ids'] = ['p01-l001']
        validation = validate_draft(
            self.lines, (self.candidates[0],), draft)
        summary = copy.deepcopy(self.job.validation_summary)
        summary.update(validation.summary)
        summary['intake_candidates'] = [
            {**asdict(self.candidates[0]),
             'evidence_line_ids': list(
                 self.candidates[0].evidence_line_ids)}
        ]
        self.job.draft_payload = validation.draft
        self.job.validation_summary = summary
        self.job.save(update_fields=['draft_payload', 'validation_summary'])

    def test_draft_get_before_review_required_is_conflict(self):
        self.job.status = 'validating'
        self.job.save(update_fields=['status'])

        response = self.client.get(self.draft_url)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'DRAFT_NOT_READY')

    def test_draft_get_has_safe_fixed_schema_and_every_row(self):
        response = self.client.get(self.draft_url)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        body = response.json()
        self.assertEqual(body['job_id'], str(self.job.id))
        self.assertEqual(body['customer_id'], self.customer.pk)
        self.assertEqual(body['status'], 'review_required')
        self.assertEqual(body['draft_version'], 1)
        self.assertEqual(len(body['coverages']), 2)
        self.assertIn('policy', body)
        self.assertIn('validation', body)
        self.assertIn('unresolved_count', body['validation'])
        self.assertIn('issues', body['validation'])
        self.assertEqual(
            body['standard_coverages']['version'], NORMALIZATION_VERSION)
        self.assertTrue(body['standard_coverages']['items'])
        self.assertEqual(body['source_review'], {
            'required': False,
            'image_only_page_count': 0,
            'image_only_pages': [],
            'quarantined_line_count': 0,
            'quarantined_pages': [],
            'analysis_signal_quarantined_line_count': 0,
            'analysis_signal_quarantined_pages': [],
            'pages_requiring_manual_source_review': [],
            'requires_manual_coverage_entry': False,
            'guidance': '',
        })
        serialized = json.dumps(body, ensure_ascii=False)
        for secret in (
                'source_storage_key', self.job.source_storage_key,
                'raw_provider_secret', 'do-not-return', 'masked_lines',
                'validation_summary', '_system'):
            self.assertNotIn(secret, serialized)

    def test_provider_started_metadata_is_never_exposed(self):
        summary = copy.deepcopy(self.job.validation_summary)
        summary['_system']['provider_started'] = True
        self.job.validation_summary = summary
        self.job.save(update_fields=['validation_summary'])

        response = self.client.get(self.draft_url)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('provider_started', json.dumps(response.json()))

    def test_analysis_quarantine_exposes_only_manual_review_pages_and_counts(self):
        summary = copy.deepcopy(self.job.validation_summary)
        summary['_system']['source_readability'] = {
            'page_count': 3,
            'image_only_page_count': 1,
            'image_only_pages': [1],
            'quarantined_line_count': 4,
            'quarantined_pages': [2, 3],
            'analysis_signal_quarantined_line_count': 2,
            'analysis_signal_quarantined_pages': [2],
            'pages_requiring_manual_source_review': [1, 2],
        }
        self.job.page_count = 3
        self.job.validation_summary = summary
        self.job.save(update_fields=['page_count', 'validation_summary'])

        response = self.client.get(self.draft_url)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['source_review'], {
            'required': True,
            'image_only_page_count': 1,
            'image_only_pages': [1],
            'quarantined_line_count': 4,
            'quarantined_pages': [2, 3],
            'analysis_signal_quarantined_line_count': 2,
            'analysis_signal_quarantined_pages': [2],
            'pages_requiring_manual_source_review': [1, 2],
            'requires_manual_coverage_entry': True,
            'guidance': (
                '해당 페이지의 원문을 확인한 뒤, 필요한 담보를 '
                '직접 추가하거나 수정해 주세요.'),
        })

    def test_normalization_version_mismatch_never_uses_latest_choices(self):
        self.job.normalization_version = 'seed-normalization-historical'
        self.job.save(update_fields=['normalization_version'])

        response = self.client.get(self.draft_url)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()['code'], 'NORMALIZATION_VERSION_UNAVAILABLE')

    def test_patch_requires_draft_version_and_idempotency_key(self):
        missing_version = self.client.patch(
            self.draft_url,
            {'policy_changes': [{'field': 'product_name', 'value': '새 상품'}]},
            format='json',
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        missing_key = self.client.patch(
            self.draft_url,
            {'draft_version': 1,
             'policy_changes': [
                 {'field': 'product_name', 'value': '새 상품'}]},
            format='json',
        )

        self.assertEqual(missing_version.status_code, 400)
        self.assertEqual(missing_key.status_code, 400)
        self.assertEqual(
            missing_key.json()['code'], 'IDEMPOTENCY_KEY_REQUIRED')

    def test_patch_rejects_whole_draft_and_evidence_overwrite(self):
        whole_draft = self.patch({
            'draft_version': 1,
            'draft_payload': {'policy': {}},
        })
        evidence = self.patch({
            'draft_version': 1,
            'policy_changes': [{
                'field': 'product_name',
                'value': '새 상품',
                'evidence_line_ids': ['forged'],
            }],
        })

        self.assertEqual(whole_draft.status_code, 400)
        self.assertEqual(evidence.status_code, 400)

    def test_policy_edit_is_manual_and_preserves_evidence_and_candidates(self):
        before_rows = copy.deepcopy(self.job.draft_payload['coverage_rows'])

        response = self.patch({
            'draft_version': 1,
            'policy_changes': [
                {'field': 'product_name', 'value': '직접 확인한 건강보험'},
            ],
        })

        self.assertEqual(response.status_code, 200, response.content)
        self.job.refresh_from_db()
        field = self.job.draft_payload['policy']['product_name']
        self.assertEqual(field['value'], '직접 확인한 건강보험')
        self.assertEqual(field['state'], 'manual')
        self.assertEqual(field['evidence_line_ids'], [])
        self.assertEqual(self.job.draft_payload['coverage_rows'], before_rows)
        self.assertEqual(self.job.draft_version, 2)
        self.assertEqual(self.job.planner_edit_count, 1)
        self.assertEqual(response.json()['draft_version'], 2)

    def test_same_value_policy_premium_edit_resolves_sum_review_codes(self):
        draft = copy.deepcopy(self.job.draft_payload)
        draft['policy']['monthly_premium'] = {
            'value': 50_000,
            'evidence_line_ids': ['p01-l001'],
        }
        validation = validate_draft(self.lines, self.candidates, draft)
        self.assertIn(
            'PREMIUM_SUM_MISMATCH',
            validation.draft['policy']['monthly_premium'][
                'review_reason_codes'])
        summary = copy.deepcopy(self.job.validation_summary)
        summary.update(validation.summary)
        self.job.draft_payload = validation.draft
        self.job.validation_summary = summary
        self.job.save(update_fields=['draft_payload', 'validation_summary'])

        response = self.patch({
            'draft_version': 1,
            'policy_changes': [
                {'field': 'monthly_premium', 'value': 50_000},
            ],
        })

        self.assertEqual(response.status_code, 200, response.content)
        premium = response.json()['policy']['monthly_premium']
        self.assertEqual(premium['state'], 'manual')
        self.assertNotIn(
            'PREMIUM_SUM_MISMATCH', premium['review_reason_codes'])
        self.assertNotIn(
            'PREMIUM_SUM_INCOMPLETE', premium['review_reason_codes'])

    def test_same_value_policy_premium_edit_resolves_incomplete_sum(self):
        draft = copy.deepcopy(self.job.draft_payload)
        draft['policy']['monthly_premium'] = {
            'value': 30_000,
            'evidence_line_ids': ['p01-l001'],
        }
        draft['coverage_rows'][1]['premium'] = None
        validation = validate_draft(self.lines, self.candidates, draft)
        self.assertIn(
            'PREMIUM_SUM_INCOMPLETE',
            validation.draft['policy']['monthly_premium'][
                'review_reason_codes'])
        summary = copy.deepcopy(self.job.validation_summary)
        summary.update(validation.summary)
        self.job.draft_payload = validation.draft
        self.job.validation_summary = summary
        self.job.save(update_fields=['draft_payload', 'validation_summary'])

        response = self.patch({
            'draft_version': 1,
            'policy_changes': [
                {'field': 'monthly_premium', 'value': 30_000},
            ],
        })

        self.assertEqual(response.status_code, 200, response.content)
        premium = response.json()['policy']['monthly_premium']
        self.assertEqual(premium['state'], 'manual')
        self.assertNotIn(
            'PREMIUM_SUM_MISMATCH', premium['review_reason_codes'])
        self.assertNotIn(
            'PREMIUM_SUM_INCOMPLETE', premium['review_reason_codes'])

    def test_assign_action_uses_same_version_standard_choice(self):
        response = self.patch({
            'draft_version': 1,
            'coverage_actions': [{
                'row_id': 'row-1',
                'action': 'assign',
                'standard_category': '진단-뇌혈관',
                'standard_subcategory': '뇌혈관',
                'standard_detail_name': '뇌혈관질환진단비',
            }],
        })

        self.assertEqual(response.status_code, 200, response.content)
        self.job.refresh_from_db()
        row = self.job.draft_payload['coverage_rows'][0]
        self.assertEqual(row['standard_detail_name'], '뇌혈관질환진단비')
        self.assertEqual(row['state'], 'manual')
        self.assertEqual(row['source_candidate_ids'], ['c00001'])
        self.assertEqual(row['evidence_line_ids'], ['p01-l001'])
        self.assertEqual(set(row['manual_fields']), {
            'standard_category', 'standard_subcategory',
            'standard_detail_name',
        })
        self.assertNotIn('manual_fields', response.json()['coverages'][0])

    def test_add_action_creates_server_owned_manual_coverage_row(self):
        response = self.patch({
            'draft_version': 1,
            'coverage_actions': [self.add_coverage_action()],
        })

        self.assertEqual(response.status_code, 200, response.content)
        self.job.refresh_from_db()
        rows = self.job.draft_payload['coverage_rows']
        self.assertEqual(len(rows), 3)
        added = rows[-1]
        self.assertTrue(added['row_id'].startswith('manual-'))
        self.assertNotIn(added['row_id'], {'row-1', 'row-2'})
        self.assertEqual(added['raw_name'], '골절수술비')
        self.assertEqual(added['assurance_amount'], 1_000_000)
        self.assertEqual(added['premium'], 1_000)
        self.assertEqual(added['standard_detail_name'], '골절수술비')
        self.assertEqual(added['source_candidate_ids'], [])
        self.assertEqual(added['evidence_line_ids'], [])
        self.assertEqual(added['state'], 'manual')
        self.assertEqual(set(added['manual_fields']), {
            'raw_name', 'assurance_amount', 'premium', 'is_renewal',
            'renewal_period', 'payment_period', 'payment_period_unit',
            'warranty_period', 'warranty_period_unit', 'standard_category',
            'standard_subcategory', 'standard_detail_name', 'disposition',
            'exclusion_reason', 'duplicate_of_row_id',
        })
        safe_added = response.json()['coverages'][-1]
        self.assertEqual(safe_added['row_id'], added['row_id'])
        self.assertNotIn('manual_fields', safe_added)
        self.assertEqual(self.job.draft_version, 2)
        self.assertEqual(self.job.planner_edit_count, 1)

    def test_add_action_rejects_client_row_id_and_invalid_manual_values(self):
        client_row_id = self.patch({
            'draft_version': 1,
            'coverage_actions': [self.add_coverage_action(
                row_id='client-chosen')],
        })
        invalid_period = self.patch({
            'draft_version': 1,
            'coverage_actions': [self.add_coverage_action(
                payment_period=0)],
        })
        invalid_path = self.patch({
            'draft_version': 1,
            'coverage_actions': [self.add_coverage_action(
                standard_detail_name='존재하지 않는 담보')],
        })
        unrelated_field = self.patch({
            'draft_version': 1,
            'coverage_actions': [self.add_coverage_action(
                reason='추가 동작에는 쓰지 않는 값')],
        })

        self.assertEqual(client_row_id.status_code, 400)
        self.assertEqual(invalid_period.status_code, 400)
        self.assertEqual(invalid_path.status_code, 400)
        self.assertEqual(unrelated_field.status_code, 400)
        self.job.refresh_from_db()
        self.assertEqual(len(self.job.draft_payload['coverage_rows']), 2)
        self.assertEqual(self.job.draft_version, 1)

    def test_add_action_replays_once_with_same_idempotency_key(self):
        key = uuid.uuid4()
        body = {
            'draft_version': 1,
            'coverage_actions': [self.add_coverage_action()],
        }

        first = self.patch(body, key=key)
        second = self.patch(body, key=key)

        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(first.json(), second.json())
        self.job.refresh_from_db()
        self.assertEqual(len(self.job.draft_payload['coverage_rows']), 3)
        self.assertEqual(self.job.draft_version, 2)
        self.assertEqual(self.job.planner_edit_count, 1)

    @override_settings(INSURANCE_MAX_CANDIDATES=3)
    def test_repeated_add_action_cannot_exceed_total_coverage_limit(self):
        first = self.patch({
            'draft_version': 1,
            'coverage_actions': [self.add_coverage_action()],
        })
        second = self.patch({
            'draft_version': 2,
            'coverage_actions': [self.add_coverage_action(
                raw_name='두 번째 직접 추가 담보')],
        })

        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(second.status_code, 400, second.content)
        self.assertEqual(
            second.json()['code'], 'COVERAGE_ROW_LIMIT_EXCEEDED')
        self.job.refresh_from_db()
        self.assertEqual(len(self.job.draft_payload['coverage_rows']), 3)
        self.assertEqual(self.job.draft_version, 2)
        self.assertEqual(self.job.planner_edit_count, 1)

    def test_assigning_same_mapping_marks_ambiguous_row_as_reviewed(self):
        draft = copy.deepcopy(self.job.draft_payload)
        draft['coverage_rows'][0]['raw_name'] = '암진단비(유사암포함)'
        ambiguous_text = (
            '암진단비(유사암포함) 가입금액 3,000만원 보험료 30,000원')
        lines = (
            MaskedLine(
                line_id='p01-l001', page=1, line=1,
                text_masked=ambiguous_text),
            self.lines[1],
        )
        candidates = (
            CoverageCandidate(
                candidate_id='c00001',
                evidence_line_ids=('p01-l001',),
                text_masked=ambiguous_text),
            self.candidates[1],
        )
        validation = validate_draft(lines, candidates, draft)
        self.assertIn(
            'STANDARD_MAPPING_AMBIGUOUS',
            validation.draft['coverage_rows'][0]['review_reason_codes'],
        )
        summary = copy.deepcopy(self.job.validation_summary)
        summary.update(validation.summary)
        summary['intake_candidates'] = [
            {**asdict(candidate),
             'evidence_line_ids': list(candidate.evidence_line_ids)}
            for candidate in candidates
        ]
        self.job.masked_lines = [asdict(line) for line in lines]
        self.job.draft_payload = validation.draft
        self.job.validation_summary = summary
        self.job.save(update_fields=[
            'masked_lines', 'draft_payload', 'validation_summary'])

        response = self.patch({
            'draft_version': 1,
            'coverage_actions': [{
                'row_id': 'row-1',
                'action': 'assign',
                'standard_category': '진단-암',
                'standard_subcategory': '일반암',
                'standard_detail_name': '일반암진단비',
            }],
        })

        self.assertEqual(response.status_code, 200, response.content)
        row = response.json()['coverages'][0]
        self.assertEqual(row['state'], 'manual')
        self.assertNotIn(
            'STANDARD_MAPPING_AMBIGUOUS', row['review_reason_codes'])
        self.job.refresh_from_db()
        self.assertEqual(set(
            self.job.draft_payload['coverage_rows'][0]['manual_fields']), {
                'standard_category',
                'standard_subcategory',
                'standard_detail_name',
            })

    def test_assign_does_not_authorize_unchanged_amount_mismatch(self):
        self.set_amount_evidence_mismatch()

        response = self.patch({
            'draft_version': 1,
            'coverage_actions': [{
                'row_id': 'row-1',
                'action': 'assign',
                'standard_category': '진단-뇌혈관',
                'standard_subcategory': '뇌혈관',
                'standard_detail_name': '뇌혈관질환진단비',
            }],
        })

        self.assertEqual(response.status_code, 200, response.content)
        row = response.json()['coverages'][0]
        self.assertEqual(row['state'], 'no_evidence')
        self.assertIn('AMOUNT_EVIDENCE_MISMATCH', row['review_reason_codes'])
        self.assertGreater(response.json()['validation']['unresolved_count'], 0)

    def test_other_field_edit_does_not_authorize_unchanged_amount_mismatch(self):
        self.set_amount_evidence_mismatch()

        response = self.patch({
            'draft_version': 1,
            'coverage_actions': [{
                'row_id': 'row-1',
                'action': 'edit',
                'field': 'warranty_period',
                'value': 99,
            }],
        })

        self.assertEqual(response.status_code, 200, response.content)
        row = response.json()['coverages'][0]
        self.assertEqual(row['state'], 'no_evidence')
        self.assertIn('AMOUNT_EVIDENCE_MISMATCH', row['review_reason_codes'])
        self.job.refresh_from_db()
        self.assertEqual(
            self.job.draft_payload['coverage_rows'][0]['manual_fields'],
            ['warranty_period'],
        )

    def test_same_value_amount_edit_records_manual_source_confirmation(self):
        self.set_amount_evidence_mismatch()

        response = self.patch({
            'draft_version': 1,
            'coverage_actions': [{
                'row_id': 'row-1',
                'action': 'edit',
                'field': 'assurance_amount',
                'value': 99_000_000,
            }],
        })

        self.assertEqual(response.status_code, 200, response.content)
        row = response.json()['coverages'][0]
        self.assertEqual(row['state'], 'manual')
        self.assertNotIn(
            'AMOUNT_EVIDENCE_MISMATCH', row['review_reason_codes'])
        self.assertNotIn(
            'AMOUNT_ROLE_AMBIGUOUS', row['review_reason_codes'])
        self.job.refresh_from_db()
        self.assertIn(
            'assurance_amount',
            self.job.draft_payload['coverage_rows'][0]['manual_fields'])

    def test_same_value_premium_edit_records_manual_source_confirmation(self):
        draft = copy.deepcopy(self.job.draft_payload)
        draft['coverage_rows'][0]['premium'] = 99_000
        validation = validate_draft(self.lines, self.candidates, draft)
        self.assertIn(
            'PREMIUM_EVIDENCE_MISMATCH',
            validation.draft['coverage_rows'][0]['review_reason_codes'])
        summary = copy.deepcopy(self.job.validation_summary)
        summary.update(validation.summary)
        self.job.draft_payload = validation.draft
        self.job.validation_summary = summary
        self.job.save(update_fields=['draft_payload', 'validation_summary'])

        response = self.patch({
            'draft_version': 1,
            'coverage_actions': [{
                'row_id': 'row-1',
                'action': 'edit',
                'field': 'premium',
                'value': 99_000,
            }],
        })

        self.assertEqual(response.status_code, 200, response.content)
        row = response.json()['coverages'][0]
        self.assertNotIn(
            'PREMIUM_EVIDENCE_MISMATCH', row['review_reason_codes'])
        self.job.refresh_from_db()
        self.assertIn(
            'premium',
            self.job.draft_payload['coverage_rows'][0]['manual_fields'])

    def test_same_invalid_value_edit_does_not_bypass_value_validation(self):
        response = self.patch({
            'draft_version': 1,
            'coverage_actions': [{
                'row_id': 'row-1',
                'action': 'edit',
                'field': 'is_renewal',
                'value': None,
            }],
        })

        self.assertEqual(response.status_code, 200, response.content)
        row = response.json()['coverages'][0]
        self.assertEqual(row['state'], 'invalid')
        self.assertIn('RENEWAL_FLAG_REQUIRED', row['review_reason_codes'])

    def test_undo_exclude_fully_revalidates_unchanged_amount(self):
        self.set_amount_evidence_mismatch()
        excluded = self.patch({
            'draft_version': 1,
            'coverage_actions': [{
                'row_id': 'row-1',
                'action': 'exclude',
                'reason': '분석 대상이 아닌 안내 행',
            }],
        })
        self.assertEqual(excluded.status_code, 200, excluded.content)
        excluded_row = excluded.json()['coverages'][0]
        self.assertEqual(excluded_row['state'], 'manual')
        self.assertNotIn(
            'AMOUNT_EVIDENCE_MISMATCH',
            excluded_row['review_reason_codes'])
        self.assertEqual(excluded.json()['validation']['unresolved_count'], 1)
        self.assertIn(
            'INSURANCE_TYPE_REQUIRED',
            excluded.json()['policy']['insurance_type'][
                'review_reason_codes'])

        restored = self.patch({
            'draft_version': 2,
            'coverage_actions': [{
                'row_id': 'row-1',
                'action': 'undo_exclude',
            }],
        })

        self.assertEqual(restored.status_code, 200, restored.content)
        row = restored.json()['coverages'][0]
        self.assertEqual(row['state'], 'no_evidence')
        self.assertIn('AMOUNT_EVIDENCE_MISMATCH', row['review_reason_codes'])
        self.job.refresh_from_db()
        self.assertNotIn(
            'manual_fields', self.job.draft_payload['coverage_rows'][0])

    def test_force_manual_review_requires_each_row_confirmation(self):
        self.set_force_manual_review()

        assigned = self.patch({
            'draft_version': 1,
            'coverage_actions': [{
                'row_id': 'row-1',
                'action': 'assign',
                'standard_category': '진단-뇌혈관',
                'standard_subcategory': '뇌혈관',
                'standard_detail_name': '뇌혈관질환진단비',
            }],
        })
        self.assertEqual(assigned.status_code, 200, assigned.content)
        self.assertEqual(assigned.json()['validation']['unresolved_count'], 3)
        for row in assigned.json()['coverages']:
            self.assertIn(
                'CARRIER_MANUAL_REVIEW', row['review_reason_codes'])

        before = {
            row['row_id']: (
                copy.deepcopy(row['source_candidate_ids']),
                copy.deepcopy(row['evidence_line_ids']),
            )
            for row in self.job.draft_payload['coverage_rows']
        }
        first = self.patch({
            'draft_version': 2,
            'coverage_actions': [{
                'row_id': 'row-1',
                'action': 'confirm',
            }],
        })
        self.assertEqual(first.status_code, 200, first.content)
        first_rows = {row['row_id']: row for row in first.json()['coverages']}
        self.assertNotIn(
            'CARRIER_MANUAL_REVIEW',
            first_rows['row-1']['review_reason_codes'])
        self.assertIn(
            'CARRIER_MANUAL_REVIEW',
            first_rows['row-2']['review_reason_codes'])
        self.assertEqual(first.json()['validation']['unresolved_count'], 2)

        second = self.patch({
            'draft_version': 3,
            'coverage_actions': [{
                'row_id': 'row-2',
                'action': 'confirm',
            }],
        })
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(second.json()['validation']['unresolved_count'], 1)
        self.assertIn(
            'INSURANCE_TYPE_REQUIRED',
            second.json()['policy']['insurance_type'][
                'review_reason_codes'])
        self.job.refresh_from_db()
        self.assertEqual(self.job.planner_edit_count, 3)
        for row in self.job.draft_payload['coverage_rows']:
            self.assertEqual(
                (row['source_candidate_ids'], row['evidence_line_ids']),
                before[row['row_id']],
            )
            self.assertEqual(
                row['confirmed_review_codes'], ['CARRIER_MANUAL_REVIEW'])
        for row in second.json()['coverages']:
            self.assertNotIn('manual_fields', row)
            self.assertNotIn('confirmed_review_codes', row)

    def test_confirm_is_rejected_without_force_manual_requirement(self):
        response = self.patch({
            'draft_version': 1,
            'coverage_actions': [{
                'row_id': 'row-1',
                'action': 'confirm',
            }],
        })

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()['code'], 'COVERAGE_CONFIRM_NOT_REQUIRED')

    def test_exclude_requires_reason_and_duplicate_requires_target(self):
        missing_reason = self.patch({
            'draft_version': 1,
            'coverage_actions': [{
                'row_id': 'row-1', 'action': 'exclude'}],
        })
        missing_target = self.patch({
            'draft_version': 1,
            'coverage_actions': [{
                'row_id': 'row-1', 'action': 'duplicate',
                'reason': '같은 담보가 두 번 표시됨'}],
        })

        self.assertEqual(missing_reason.status_code, 400)
        self.assertEqual(missing_target.status_code, 400)

    def test_duplicate_cannot_target_itself_or_an_excluded_row(self):
        self_target = self.patch({
            'draft_version': 1,
            'coverage_actions': [{
                'row_id': 'row-1', 'action': 'duplicate',
                'reason': '중복', 'target_row_id': 'row-1'}],
        })
        self.assertEqual(self_target.status_code, 400)
        self.assertEqual(
            self_target.json()['code'], 'INVALID_DUPLICATE_TARGET')

        excluded = self.patch({
            'draft_version': 1,
            'coverage_actions': [{
                'row_id': 'row-2', 'action': 'exclude',
                'reason': '문서 안내 행'}],
        })
        self.assertEqual(excluded.status_code, 200, excluded.content)
        excluded_target = self.patch({
            'draft_version': 2,
            'coverage_actions': [{
                'row_id': 'row-1', 'action': 'duplicate',
                'reason': '중복', 'target_row_id': 'row-2'}],
        })
        self.assertEqual(excluded_target.status_code, 400)
        self.assertEqual(
            excluded_target.json()['code'], 'INVALID_DUPLICATE_TARGET')

    def test_duplicate_requires_the_same_source_candidate_group(self):
        response = self.patch({
            'draft_version': 1,
            'coverage_actions': [{
                'row_id': 'row-2', 'action': 'duplicate',
                'reason': '중복', 'target_row_id': 'row-1'}],
        })

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(
            response.json()['code'], 'INVALID_DUPLICATE_TARGET')

    def test_exclude_duplicate_and_undo_are_deterministically_revalidated(self):
        self.set_duplicate_source_rows()
        duplicate = self.patch({
            'draft_version': 1,
            'coverage_actions': [{
                'row_id': 'row-2', 'action': 'duplicate',
                'reason': '같은 담보가 두 번 표시됨',
                'target_row_id': 'row-1',
            }],
        })
        self.assertEqual(duplicate.status_code, 200, duplicate.content)
        duplicate_row = next(
            row for row in duplicate.json()['coverages']
            if row['row_id'] == 'row-2')
        self.assertEqual(duplicate_row['disposition'], 'intentionally_excluded')
        self.assertEqual(duplicate_row['duplicate_of_row_id'], 'row-1')
        self.assertEqual(duplicate_row['state'], 'manual')
        self.assertNotIn(
            'DUPLICATE_SOURCE_ROW', duplicate_row['review_reason_codes'])
        self.assertEqual(duplicate.json()['validation']['unresolved_count'], 1)
        self.assertIn(
            'INSURANCE_TYPE_REQUIRED',
            duplicate.json()['policy']['insurance_type'][
                'review_reason_codes'])

        undo = self.patch({
            'draft_version': 2,
            'coverage_actions': [{
                'row_id': 'row-2', 'action': 'undo_exclude'}],
        })
        self.assertEqual(undo.status_code, 200, undo.content)
        restored = next(
            row for row in undo.json()['coverages']
            if row['row_id'] == 'row-2')
        self.assertEqual(restored['disposition'], 'assigned')
        self.assertEqual(restored['standard_detail_name'], '유사암진단비')
        self.assertIsNone(restored.get('duplicate_of_row_id'))
        self.assertEqual(restored['state'], 'needs_review')
        self.assertIn(
            'DUPLICATE_SOURCE_ROW', restored['review_reason_codes'])

    def test_same_key_same_body_replays_fixed_response_once(self):
        key = uuid.uuid4()
        body = {
            'draft_version': 1,
            'policy_changes': [
                {'field': 'product_name', 'value': '재생 상품'}],
        }

        first = self.patch(body, key=key)
        second = self.patch(body, key=key)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json(), second.json())
        self.job.refresh_from_db()
        self.assertEqual(self.job.draft_version, 2)
        self.assertEqual(self.job.planner_edit_count, 1)
        self.assertEqual(
            InsuranceImportCommand.objects.filter(
                job=self.job, operation='patch').count(), 1)

    def test_same_key_different_body_is_conflict(self):
        key = uuid.uuid4()
        first = self.patch({
            'draft_version': 1,
            'policy_changes': [
                {'field': 'product_name', 'value': '첫 상품'}],
        }, key=key)
        reused = self.patch({
            'draft_version': 1,
            'policy_changes': [
                {'field': 'product_name', 'value': '다른 상품'}],
        }, key=key)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(reused.status_code, 409)
        self.assertEqual(reused.json()['code'], 'IDEMPOTENCY_KEY_REUSED')

    def test_stale_version_has_current_version_and_only_one_writer_wins(self):
        first = self.patch({
            'draft_version': 1,
            'policy_changes': [
                {'field': 'product_name', 'value': '첫 저장'}],
        })
        stale = self.patch({
            'draft_version': 1,
            'policy_changes': [
                {'field': 'product_name', 'value': '늦은 저장'}],
        })

        self.assertEqual(first.status_code, 200)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()['code'], 'DRAFT_VERSION_CHANGED')
        self.assertEqual(stale.json()['current_version'], 2)
        self.job.refresh_from_db()
        self.assertEqual(
            self.job.draft_payload['policy']['product_name']['value'],
            '첫 저장')

    def test_foreign_get_patch_and_cancel_are_all_hidden(self):
        get_response = self.foreign_client.get(self.draft_url)
        patch_response = self.patch({
            'draft_version': 1,
            'policy_changes': [
                {'field': 'product_name', 'value': '침범'}],
        }, client=self.foreign_client)
        cancel_response = self.foreign_client.post(
            self.cancel_url, {}, format='json',
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))

        self.assertEqual(get_response.status_code, 404)
        self.assertEqual(patch_response.status_code, 404)
        self.assertEqual(cancel_response.status_code, 404)

    def test_cancel_is_durable_and_deletes_only_exact_source_after_commit(self):
        key = uuid.uuid4()
        with mock.patch(
                'inpa.insurances.import_services.delete_source') as delete:
            with self.captureOnCommitCallbacks(execute=True):
                first = self.client.post(
                    self.cancel_url, {}, format='json',
                    HTTP_IDEMPOTENCY_KEY=str(key))
            second = self.client.post(
                self.cancel_url, {}, format='json',
                HTTP_IDEMPOTENCY_KEY=str(key))

        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(first.json(), second.json())
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'canceled')
        self.assertIsNotNone(self.job.canceled_at)
        self.assertIsNotNone(self.job.source_deleted_at)
        delete.assert_called_once_with(
            mock.ANY, key=self.job.source_storage_key)
        canceled_patch = self.patch({
            'draft_version': self.job.draft_version,
            'policy_changes': [
                {'field': 'product_name', 'value': '취소 뒤 수정'}],
        })
        self.assertEqual(canceled_patch.status_code, 409)
        self.assertEqual(canceled_patch.json()['code'], 'IMPORT_CANCELED')

    def test_cancel_cleanup_failure_leaves_expired_retry_marker(self):
        with mock.patch(
                'inpa.insurances.import_services.delete_source',
                side_effect=OSError('storage unavailable')):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    self.cancel_url, {}, format='json',
                    HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))

        self.assertEqual(response.status_code, 200)
        self.job.refresh_from_db()
        self.assertIsNone(self.job.source_deleted_at)
        self.assertLessEqual(self.job.source_expires_at, timezone.now())

    def test_provider_reserved_job_cancel_returns_conflict_without_command(self):
        summary = copy.deepcopy(self.job.validation_summary)
        summary['_system']['provider_started'] = True
        self.job.status = 'validating'
        self.job.attempt_uuid = uuid.uuid4()
        self.job.lease_expires_at = timezone.now() + timedelta(minutes=5)
        self.job.validation_summary = summary
        self.job.save(update_fields=(
            'status', 'attempt_uuid', 'lease_expires_at',
            'validation_summary'))

        with mock.patch(
                'inpa.insurances.import_services.delete_source') as delete:
            response = self.client.post(
                self.cancel_url, {}, format='json',
                HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'CANCEL_IN_PROGRESS')
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'validating')
        self.assertFalse(InsuranceImportCommand.objects.filter(
            job=self.job, operation='cancel').exists())
        delete.assert_not_called()
