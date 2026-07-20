import copy
import uuid
from dataclasses import asdict
from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User
from inpa.analysis.models import (
    AnalysisCategory, AnalysisDetail, AnalysisSubCategory,
)
from inpa.customers.models import Customer

from .import_contract import CoverageCandidate, MaskedLine
from .import_validation import validate_draft
from .models import (
    CustomerInsurance, InsuranceCategory, InsuranceDetail,
    InsuranceExtractionJob, InsuranceImportCommand, InsuranceSubCategory,
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


def _valid_material():
    line = MaskedLine(
        line_id='p01-l001', page=1, line=1,
        text_masked='일반암진단비 가입금액 3,000만원 보험료 30,000원')
    candidate = CoverageCandidate(
        candidate_id='c00001', evidence_line_ids=(line.line_id,),
        text_masked=line.text_masked)
    none = {'value': None, 'evidence_line_ids': []}
    payload = {
        'schema_version': 'insurance-review-v1',
        'policy': {
            'carrier_name': copy.deepcopy(none),
            'company_code': copy.deepcopy(none),
            'insurance_type': {
                'value': 'loss', 'evidence_line_ids': [], 'state': 'manual'},
            'product_name': {
                'value': '직접 확인한 건강보험',
                'evidence_line_ids': [], 'state': 'manual'},
            'contract_date': copy.deepcopy(none),
            'expiry_date': copy.deepcopy(none),
            'monthly_premium': copy.deepcopy(none),
        },
        'coverage_rows': [{
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
            'duplicate_of_row_id': None,
            'source_candidate_ids': ['c00001'],
            'evidence_line_ids': ['p01-l001'],
        }],
    }
    validated = validate_draft(
        (line,), (candidate,), payload, allow_manual=True)
    return line, candidate, validated.draft, validated.summary


@override_settings(INSURANCE_REVIEW_GATE_ENABLED=True)
class InsuranceImportConfirmTests(TestCase):
    def setUp(self):
        self.owner, self.client = _planner('confirm-owner@test.com')
        self.foreign, self.foreign_client = _planner(
            'confirm-foreign@test.com')
        self.customer = Customer.objects.create(
            owner=self.owner, name='내 고객', birth_day='1990.01.01')
        self.line, self.candidate, draft, summary = _valid_material()
        self.analysis_category = AnalysisCategory.objects.create(
            name='[표준]진단-암')
        self.analysis_subcategory = AnalysisSubCategory.objects.create(
            category=self.analysis_category, name='일반암')
        self.analysis_detail = AnalysisDetail.objects.create(
            sub_category=self.analysis_subcategory, name='일반암진단비')
        category = InsuranceCategory.objects.create(name='진단-암')
        subcategory = InsuranceSubCategory.objects.create(
            category=category, name='일반암')
        self.catalog_detail = InsuranceDetail.objects.create(
            sub_category=subcategory, name='일반암진단비')
        self.global_mapping = AnalysisDetail.objects.create(
            sub_category=self.analysis_subcategory, name='기존전역담보')
        self.catalog_detail.analysis_detail.add(self.global_mapping)
        self.job = InsuranceExtractionJob.objects.create(
            owner=self.owner, customer=self.customer, intent='add',
            portfolio_type=1, status='review_required',
            file_sha256='a' * 64, file_size=100, page_count=1,
            safe_display_name='policy.pdf',
            source_expires_at=timezone.now() + timedelta(hours=1),
            masked_lines=[asdict(self.line)], draft_payload=draft,
            validation_summary={
                **summary,
                'intake_candidates': [{
                    **asdict(self.candidate),
                    'evidence_line_ids': list(
                        self.candidate.evidence_line_ids),
                }],
                '_system': {'source_readability': {
                    'page_count': 1,
                    'image_only_page_count': 0,
                    'image_only_pages': [],
                    'quarantined_line_count': 0,
                    'quarantined_pages': [],
                    'analysis_signal_quarantined_line_count': 0,
                    'analysis_signal_quarantined_pages': [],
                    'pages_requiring_manual_source_review': [],
                }},
            },
            normalization_version=NORMALIZATION_VERSION,
        )
        self.job.source_storage_key = (
            f'insurance-imports/{self.owner.pk}/{self.customer.pk}/'
            f'{self.job.pk}/source.pdf')
        self.job.save(update_fields=['source_storage_key'])

    @property
    def url(self):
        return f'/api/v1/insurance-imports/{self.job.pk}/confirm/'

    def confirm(self, *, body=None, key=None, client=None):
        payload = {
            'draft_version': self.job.draft_version,
            'target_insurance_version': None,
            'planner_confirmed_source_match': True,
        }
        if body:
            payload.update(body)
        return (client or self.client).post(
            self.url, payload, format='json',
            HTTP_IDEMPOTENCY_KEY=str(key or uuid.uuid4()))

    def save_draft(self, draft):
        self.job.draft_payload = draft
        self.job.save(update_fields=['draft_payload'])

    @staticmethod
    def set_policy_value(draft, field, value):
        draft['policy'][field] = {
            'value': value,
            'evidence_line_ids': [],
            'state': 'manual',
        }

    def renewal_draft(self, *, insurance_type='loss',
                      contract_date='2024.01.01',
                      expiry_date='2044.01.01',
                      payment_period=20,
                      payment_period_unit='years'):
        draft = copy.deepcopy(self.job.draft_payload)
        self.set_policy_value(
            draft, 'insurance_type', insurance_type)
        self.set_policy_value(draft, 'contract_date', contract_date)
        self.set_policy_value(draft, 'expiry_date', expiry_date)
        draft['coverage_rows'][0].update({
            'is_renewal': True,
            'renewal_period': 10,
            'payment_period': payment_period,
            'payment_period_unit': payment_period_unit,
        })
        return draft

    def test_confirmation_requires_planner_source_checkbox(self):
        response = self.confirm(body={
            'planner_confirmed_source_match': False})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'SOURCE_CONFIRMATION_REQUIRED')
        self.assertFalse(CustomerInsurance.objects.exists())

    def test_same_lineage_add_cannot_create_second_analysis_insurance(self):
        confirmed_job = InsuranceExtractionJob.objects.create(
            owner=self.owner, customer=self.customer, intent='add',
            portfolio_type=self.job.portfolio_type, status='confirmed',
            file_sha256=self.job.file_sha256, file_size=100, page_count=1,
            safe_display_name='already-confirmed.pdf',
        )
        existing = CustomerInsurance.objects.create(
            customer=self.customer, portfolio_type=self.job.portfolio_type,
            insurance_type=2, name='기존 확인 보험',
            source_job=confirmed_job, review_status='confirmed',
            analysis_included=True,
        )

        response = self.confirm()

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()['code'], 'DUPLICATE_CONFIRMED')
        self.assertEqual(response.json()['insurance_id'], existing.pk)
        self.assertEqual(
            CustomerInsurance.objects.analysis_ready().count(), 1)
        self.assertEqual(
            InsuranceExtractionJob.objects.filter(status='confirmed').count(),
            1,
        )

    def test_confirmation_preserves_frozen_initial_metrics(self):
        initial_metrics = {
            'schema_version': 'insurance-extraction-initial-metrics-v1',
            'carrier_code': 1,
            'detected_candidates': 1,
            'assigned': 1,
            'unmatched': 0,
            'intentionally_excluded': 0,
            'coverage_row_count': 1,
            'coverage_state_counts': {
                'review_ready': 1, 'needs_review': 0, 'no_evidence': 0,
                'unmatched': 0, 'invalid': 0, 'manual': 0,
            },
            'policy_field_count': 7,
            'policy_state_counts': {
                'review_ready': 7, 'needs_review': 0, 'no_evidence': 0,
                'unmatched': 0, 'invalid': 0, 'manual': 0,
            },
        }
        self.job.validation_summary['_system']['initial_metrics'] = initial_metrics
        self.job.save(update_fields=['validation_summary'])

        response = self.confirm()

        self.assertEqual(response.status_code, 200, response.content)
        self.job.refresh_from_db()
        self.assertEqual(
            self.job.validation_summary['_system']['initial_metrics'],
            initial_metrics,
        )

    def test_unread_source_pages_need_separate_explicit_confirmation(self):
        summary = copy.deepcopy(self.job.validation_summary)
        summary['_system']['source_readability'] = {
            'page_count': 10,
            'image_only_page_count': 2,
            'image_only_pages': [1, 2],
            'quarantined_line_count': 0,
            'quarantined_pages': [],
            'analysis_signal_quarantined_line_count': 0,
            'analysis_signal_quarantined_pages': [],
            'pages_requiring_manual_source_review': [1, 2],
        }
        self.job.page_count = 10
        self.job.validation_summary = summary
        self.job.save(update_fields=['page_count', 'validation_summary'])

        blocked = self.confirm()
        self.assertEqual(blocked.status_code, 409, blocked.content)
        self.assertEqual(
            blocked.json()['code'],
            'UNREAD_SOURCE_PAGES_CONFIRMATION_REQUIRED')
        self.assertFalse(CustomerInsurance.objects.exists())

        confirmed = self.confirm(body={
            'planner_confirmed_unread_pages': True})
        self.assertEqual(confirmed.status_code, 200, confirmed.content)
        self.assertEqual(CustomerInsurance.objects.count(), 1)

    def test_analysis_quarantine_pages_need_explicit_source_confirmation(self):
        summary = copy.deepcopy(self.job.validation_summary)
        summary['_system']['source_readability'] = {
            'page_count': 2,
            'image_only_page_count': 0,
            'image_only_pages': [],
            'quarantined_line_count': 2,
            'quarantined_pages': [1],
            'analysis_signal_quarantined_line_count': 1,
            'analysis_signal_quarantined_pages': [1],
            'pages_requiring_manual_source_review': [1],
        }
        self.job.page_count = 2
        self.job.validation_summary = summary
        self.job.save(update_fields=['page_count', 'validation_summary'])

        blocked = self.confirm()

        self.assertEqual(blocked.status_code, 409, blocked.content)
        self.assertEqual(
            blocked.json()['code'],
            'UNREAD_SOURCE_PAGES_CONFIRMATION_REQUIRED',
        )
        self.assertFalse(CustomerInsurance.objects.exists())

        confirmed = self.confirm(body={
            'planner_confirmed_unread_pages': True,
        })
        self.assertEqual(confirmed.status_code, 200, confirmed.content)
        self.assertEqual(CustomerInsurance.objects.count(), 1)

    def test_unresolved_candidate_blocks_confirmation(self):
        draft = copy.deepcopy(self.job.draft_payload)
        draft['coverage_rows'][0].update({
            'disposition': 'unmatched',
            'standard_category': None,
            'standard_subcategory': None,
            'standard_detail_name': None,
        })
        validation = validate_draft(
            (self.line,), (self.candidate,), draft, allow_manual=True)
        self.job.draft_payload = validation.draft
        self.job.save(update_fields=['draft_payload'])

        response = self.confirm()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'DRAFT_UNRESOLVED')

    def test_no_evidence_amount_blocks_confirmation(self):
        draft = copy.deepcopy(self.job.draft_payload)
        draft['coverage_rows'][0]['assurance_amount'] = 99_000_000
        validation = validate_draft(
            (self.line,), (self.candidate,), draft, allow_manual=True)
        self.job.draft_payload = validation.draft
        self.job.save(update_fields=['draft_payload'])

        response = self.confirm()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'DRAFT_UNRESOLVED')

    def test_unknown_insurance_type_blocks_confirmation(self):
        draft = copy.deepcopy(self.job.draft_payload)
        draft['policy']['insurance_type']['value'] = None
        self.job.draft_payload = draft
        self.job.save(update_fields=['draft_payload'])

        response = self.confirm()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'DRAFT_UNRESOLVED')
        self.assertFalse(CustomerInsurance.objects.exists())

    def test_unknown_renewal_flag_blocks_confirmation(self):
        draft = copy.deepcopy(self.job.draft_payload)
        draft['coverage_rows'][0].update({
            'is_renewal': None,
            'renewal_period': None,
        })
        self.job.draft_payload = draft
        self.job.save(update_fields=['draft_payload'])

        response = self.confirm()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'DRAFT_UNRESOLVED')
        self.assertFalse(CustomerInsurance.objects.exists())

    def test_premium_without_payment_period_blocks_before_calculation(self):
        draft = copy.deepcopy(self.job.draft_payload)
        draft['coverage_rows'][0].update({
            'payment_period': None,
            'payment_period_unit': None,
        })
        self.job.draft_payload = draft
        self.job.save(update_fields=['draft_payload'])

        response = self.confirm()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'DRAFT_UNRESOLVED')
        self.assertFalse(CustomerInsurance.objects.exists())

    def test_renewal_age_payment_unit_blocks_when_storage_cannot_preserve_it(self):
        draft = copy.deepcopy(self.job.draft_payload)
        draft['coverage_rows'][0].update({
            'is_renewal': True,
            'renewal_period': 10,
            'payment_period': 100,
            'payment_period_unit': 'age',
        })
        self.job.draft_payload = draft
        self.job.save(update_fields=['draft_payload'])

        response = self.confirm()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'DRAFT_UNRESOLVED')
        self.assertFalse(CustomerInsurance.objects.exists())

    def test_manually_confirmed_total_premium_allows_missing_case_premium(self):
        draft = copy.deepcopy(self.job.draft_payload)
        draft['policy']['monthly_premium'] = {
            'value': 30_000,
            'evidence_line_ids': [],
            'state': 'manual',
            'planner_confirmed': True,
        }
        draft['coverage_rows'][0]['premium'] = None
        self.job.draft_payload = draft
        self.job.save(update_fields=['draft_payload'])

        response = self.confirm()

        self.assertEqual(response.status_code, 200, response.content)
        insurance = CustomerInsurance.objects.get()
        self.assertEqual(insurance.monthly_premiums, 30_000)
        self.assertIsNone(insurance.case_list.get().premium)

    def test_assigned_coverage_without_assurance_amount_blocks_confirmation(self):
        draft = copy.deepcopy(self.job.draft_payload)
        draft['coverage_rows'][0]['assurance_amount'] = None
        self.job.draft_payload = draft
        self.job.save(update_fields=['draft_payload'])

        response = self.confirm()

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()['code'], 'DRAFT_UNRESOLVED')
        self.assertFalse(CustomerInsurance.objects.exists())

    def test_mixed_known_and_unknown_case_premiums_block_confirmation(self):
        second_line = MaskedLine(
            line_id='p01-l002', page=1, line=2,
            text_masked='일반암진단비 가입금액 3,000만원')
        second_candidate = CoverageCandidate(
            candidate_id='c00002',
            evidence_line_ids=(second_line.line_id,),
            text_masked=second_line.text_masked,
        )
        draft = copy.deepcopy(self.job.draft_payload)
        second_row = copy.deepcopy(draft['coverage_rows'][0])
        second_row.update({
            'row_id': 'row-2',
            'premium': None,
            'source_candidate_ids': ['c00002'],
            'evidence_line_ids': ['p01-l002'],
        })
        draft['coverage_rows'].append(second_row)
        self.job.masked_lines = [asdict(self.line), asdict(second_line)]
        summary = copy.deepcopy(self.job.validation_summary)
        summary['intake_candidates'].append({
            **asdict(second_candidate),
            'evidence_line_ids': list(second_candidate.evidence_line_ids),
        })
        self.job.validation_summary = summary
        self.job.draft_payload = draft
        self.job.save(update_fields=(
            'masked_lines', 'validation_summary', 'draft_payload'))

        response = self.confirm()

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()['code'], 'DRAFT_UNRESOLVED')
        self.assertFalse(CustomerInsurance.objects.exists())

    def test_age_payment_with_missing_contract_date_blocks_before_calculation(self):
        draft = copy.deepcopy(self.job.draft_payload)
        draft['coverage_rows'][0].update({
            'payment_period': 100,
            'payment_period_unit': 'age',
        })
        self.job.draft_payload = draft
        self.job.save(update_fields=['draft_payload'])

        response = self.confirm()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'DRAFT_UNRESOLVED')
        self.assertFalse(CustomerInsurance.objects.exists())

    def test_age_payment_with_missing_birth_date_blocks_before_calculation(self):
        draft = copy.deepcopy(self.job.draft_payload)
        draft['policy']['contract_date'] = {
            'value': '2024.01.01',
            'evidence_line_ids': [],
            'state': 'manual',
        }
        draft['coverage_rows'][0].update({
            'payment_period': 100,
            'payment_period_unit': 'age',
        })
        self.job.draft_payload = draft
        self.job.save(update_fields=['draft_payload'])
        self.customer.birth_day = ''
        self.customer.save(update_fields=['birth_day'])

        response = self.confirm()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'DRAFT_UNRESOLVED')
        self.assertFalse(CustomerInsurance.objects.exists())

    def test_life_renewal_accepts_iso_birth_and_policy_dates(self):
        self.customer.birth_day = '1990-01-01'
        self.customer.save(update_fields=['birth_day'])
        self.save_draft(self.renewal_draft(
            insurance_type='life',
            contract_date='2024-01-01',
            expiry_date='2044-01-01'))

        response = self.confirm()

        self.assertEqual(response.status_code, 200, response.content)
        insurance = CustomerInsurance.objects.get()
        case = insurance.case_list.get()
        self.assertEqual(insurance.renewal_month, 240)
        self.assertEqual(case.total_renewal_premium, 7_200_000)

    def test_life_renewal_missing_expiry_never_uses_due_year_or_age_guess(self):
        insurance = CustomerInsurance.objects.create(
            customer=self.customer,
            insurance_type=1,
            name='생명보험',
            contract_date='2024-01-01',
            expiry_date=None,
            expected_due_year=20,
            renewal_special_expiry=100,
        )

        insurance.set_renewal_month()

        self.assertIsNone(insurance.renewal_month)

    def test_loss_renewal_accepts_legacy_dotted_policy_dates(self):
        self.save_draft(self.renewal_draft())

        response = self.confirm()

        self.assertEqual(response.status_code, 200, response.content)
        insurance = CustomerInsurance.objects.get()
        self.assertEqual(insurance.renewal_month, 240)
        self.assertEqual(
            insurance.case_list.get().total_renewal_premium,
            7_200_000)

    def test_loss_renewal_missing_expiry_blocks_instead_of_zero_total(self):
        self.save_draft(self.renewal_draft(expiry_date=None))

        response = self.confirm()

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()['code'], 'DRAFT_UNRESOLVED')
        self.assertFalse(CustomerInsurance.objects.exists())

    def test_invalid_policy_calendar_date_blocks_before_materialization(self):
        draft = self.renewal_draft(contract_date='2024-02-30')
        self.save_draft(draft)

        response = self.confirm()

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()['code'], 'DRAFT_UNRESOLVED')
        self.assertFalse(CustomerInsurance.objects.exists())

    def test_life_renewal_invalid_customer_birth_returns_409_not_503(self):
        self.customer.birth_day = '1990-02-30'
        self.customer.save(update_fields=['birth_day'])
        self.save_draft(self.renewal_draft(insurance_type='life'))

        response = self.confirm()

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()['code'], 'DRAFT_UNRESOLVED')
        self.assertFalse(CustomerInsurance.objects.exists())

    def test_lifetime_nonrenewal_preserves_unit_and_unknown_totals(self):
        draft = copy.deepcopy(self.job.draft_payload)
        self.set_policy_value(draft, 'contract_date', '2024.01.01')
        draft['coverage_rows'][0].update({
            'is_renewal': False,
            'renewal_period': None,
            'payment_period': None,
            'payment_period_unit': 'lifetime',
            'warranty_period': 100,
            'warranty_period_unit': 'age',
        })
        self.save_draft(draft)

        response = self.confirm()

        self.assertEqual(response.status_code, 200, response.content)
        insurance = CustomerInsurance.objects.get()
        case = insurance.case_list.get()
        self.assertEqual(case.payment_period_type, 4)
        self.assertIsNone(case.payment_period)
        self.assertIsNone(case.renewal_period)
        self.assertIsNone(case.total_renewal_premium)
        self.assertIsNone(case.total_non_renewal_premium)
        self.assertEqual(insurance.monthly_non_renewal_premium, 30_000)
        self.assertEqual(insurance.monthly_renewal_premium, 0)
        self.assertIsNone(insurance.total_premiums)
        self.assertIsNone(insurance.total_non_renewal_premium)

    def test_lifetime_renewal_uses_monthly_renewal_bucket_but_unknown_totals(self):
        self.save_draft(self.renewal_draft(
            payment_period=None,
            payment_period_unit='lifetime'))

        response = self.confirm()

        self.assertEqual(response.status_code, 200, response.content)
        insurance = CustomerInsurance.objects.get()
        case = insurance.case_list.get()
        self.assertEqual(case.payment_period_type, 4)
        self.assertEqual(case.renewal_period, 10)
        self.assertIsNone(case.payment_period)
        self.assertIsNone(case.total_renewal_premium)
        self.assertIsNone(case.total_non_renewal_premium)
        self.assertEqual(insurance.monthly_renewal_premium, 30_000)
        self.assertEqual(insurance.monthly_non_renewal_premium, 0)
        self.assertIsNone(insurance.total_premiums)
        self.assertIsNone(insurance.total_renewal_premium)

    def test_stale_draft_version_returns_409(self):
        response = self.confirm(body={'draft_version': 999})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'DRAFT_VERSION_CHANGED')

    @mock.patch(
        'inpa.insurances.import_services._calculate_materialized_insurance',
        side_effect=RuntimeError('injected'))
    def test_confirm_rollback_leaves_no_partial_insurance(self, _calculate):
        response = self.confirm()
        self.assertEqual(response.status_code, 503)
        self.assertFalse(CustomerInsurance.objects.exists())
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'review_required')
        self.assertFalse(InsuranceImportCommand.objects.exists())

    def test_confirm_is_idempotent_for_same_command_key(self):
        key = uuid.uuid4()
        first = self.confirm(key=key)
        second = self.confirm(key=key)
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(second.json(), first.json())
        self.assertEqual(CustomerInsurance.objects.count(), 1)

    def test_different_request_with_same_command_key_returns_409(self):
        key = uuid.uuid4()
        first = self.confirm(key=key)
        second = self.confirm(
            body={'draft_version': self.job.draft_version + 1}, key=key)
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()['code'], 'IDEMPOTENCY_KEY_REUSED')

    def test_confirmed_insurance_preserves_source_evidence(self):
        response = self.confirm()
        self.assertEqual(response.status_code, 200, response.content)
        case = CustomerInsurance.objects.get().case_list.get()
        self.assertEqual(case.raw_name, '일반암진단비')
        self.assertEqual(case.source_candidate_ids, ['c00001'])
        self.assertEqual(case.evidence_line_ids, ['p01-l001'])
        self.assertEqual(case.source_page, 1)
        self.assertEqual(case.source_line_start, 1)
        self.assertEqual(case.source_line_end, 1)
        self.assertIn('3,000만원', case.source_text_masked)

    def test_confirm_does_not_mutate_global_mapping(self):
        before = list(
            self.catalog_detail.analysis_detail.values_list('pk', flat=True))
        response = self.confirm()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            list(self.catalog_detail.analysis_detail.values_list(
                'pk', flat=True)), before)
        case = CustomerInsurance.objects.get().case_list.get()
        self.assertEqual(case.mapping_source, 'planner_override')
        self.assertEqual(
            list(case.analysis_detail_override.all()), [self.analysis_detail])

    def test_manual_added_coverage_confirms_without_source_evidence(self):
        analysis_category = AnalysisCategory.objects.create(
            name='[표준]수술비')
        analysis_subcategory = AnalysisSubCategory.objects.create(
            category=analysis_category, name='특수수술')
        analysis_detail = AnalysisDetail.objects.create(
            sub_category=analysis_subcategory, name='골절수술비')
        catalog_category = InsuranceCategory.objects.create(
            name='[표준]수술비')
        catalog_subcategory = InsuranceSubCategory.objects.create(
            category=catalog_category, name='특수수술')
        catalog_detail = InsuranceDetail.objects.create(
            sub_category=catalog_subcategory, name='골절수술비')

        patch_response = self.client.patch(
            f'/api/v1/insurance-imports/{self.job.pk}/draft/',
            {
                'draft_version': self.job.draft_version,
                'policy_changes': [{
                    'field': 'monthly_premium',
                    'value': 30_000,
                }],
                'coverage_actions': [{
                    'action': 'add',
                    'raw_name': '골절수술비',
                    'assurance_amount': 1_000_000,
                    'premium': None,
                    'is_renewal': False,
                    'payment_period': 20,
                    'payment_period_unit': 'years',
                    'warranty_period': 20,
                    'warranty_period_unit': 'years',
                    'standard_category': '수술비',
                    'standard_subcategory': '특수수술',
                    'standard_detail_name': '골절수술비',
                }],
            },
            format='json',
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        self.assertEqual(patch_response.status_code, 200, patch_response.content)
        self.job.refresh_from_db()

        response = self.confirm(body={
            'draft_version': self.job.draft_version,
        })

        self.assertEqual(response.status_code, 200, response.content)
        insurance = CustomerInsurance.objects.get()
        added = insurance.case_list.get(raw_name='골절수술비')
        self.assertEqual(added.detail_id, catalog_detail.pk)
        self.assertIsNone(added.premium)
        self.assertEqual(added.evidence_line_ids, [])
        self.assertEqual(added.source_candidate_ids, [])
        self.assertEqual(added.mapping_source, 'planner_override')
        self.assertEqual(
            list(added.analysis_detail_override.all()), [analysis_detail])
        self.assertFalse(catalog_detail.analysis_detail.exists())

    def test_missing_catalog_mapping_blocks_without_creating_global_rows(self):
        self.catalog_detail.delete()
        before = (
            InsuranceCategory.objects.count(),
            InsuranceSubCategory.objects.count(),
            InsuranceDetail.objects.count(),
        )

        response = self.confirm()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()['code'], 'STANDARD_COVERAGE_NOT_READY')
        self.assertEqual((
            InsuranceCategory.objects.count(),
            InsuranceSubCategory.objects.count(),
            InsuranceDetail.objects.count(),
        ), before)
        self.assertFalse(CustomerInsurance.objects.exists())

    def test_duplicate_catalog_mapping_blocks_without_global_mutation(self):
        duplicate = InsuranceDetail.objects.create(
            sub_category=self.catalog_detail.sub_category,
            name=self.catalog_detail.name,
        )
        before_rows = InsuranceDetail.objects.count()
        before_links = {
            detail.pk: list(detail.analysis_detail.values_list('pk', flat=True))
            for detail in (self.catalog_detail, duplicate)
        }

        response = self.confirm()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()['code'], 'STANDARD_COVERAGE_NOT_READY')
        self.assertEqual(InsuranceDetail.objects.count(), before_rows)
        for detail in (self.catalog_detail, duplicate):
            self.assertEqual(
                list(detail.analysis_detail.values_list('pk', flat=True)),
                before_links[detail.pk],
            )
        self.assertFalse(CustomerInsurance.objects.exists())

    def test_two_owners_confirm_same_mapping_without_global_mutation(self):
        before_rows = (
            InsuranceCategory.objects.count(),
            InsuranceSubCategory.objects.count(),
            InsuranceDetail.objects.count(),
        )
        before_links = list(
            self.catalog_detail.analysis_detail.values_list('pk', flat=True))
        first = self.confirm()
        self.assertEqual(first.status_code, 200, first.content)

        foreign_customer = Customer.objects.create(
            owner=self.foreign, name='다른 고객', birth_day='1991.01.01')
        foreign_job = InsuranceExtractionJob.objects.create(
            owner=self.foreign,
            customer=foreign_customer,
            intent='add',
            portfolio_type=1,
            status='review_required',
            file_sha256='b' * 64,
            file_size=100,
            page_count=1,
            safe_display_name='policy.pdf',
            source_expires_at=timezone.now() + timedelta(hours=1),
            masked_lines=[asdict(self.line)],
            draft_payload=copy.deepcopy(self.job.draft_payload),
            validation_summary=copy.deepcopy(self.job.validation_summary),
            normalization_version=NORMALIZATION_VERSION,
        )
        response = self.foreign_client.post(
            f'/api/v1/insurance-imports/{foreign_job.pk}/confirm/',
            {
                'draft_version': foreign_job.draft_version,
                'target_insurance_version': None,
                'planner_confirmed_source_match': True,
            },
            format='json',
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual((
            InsuranceCategory.objects.count(),
            InsuranceSubCategory.objects.count(),
            InsuranceDetail.objects.count(),
        ), before_rows)
        self.assertEqual(
            list(self.catalog_detail.analysis_detail.values_list(
                'pk', flat=True)), before_links)

    def test_golden_unlabeled_money_roles_remain_unresolved(self):
        text = (
            '뇌혈관질환진단비 1,000만원 14,290원 '
            '100세만기/20년납')
        line = MaskedLine(
            line_id='p01-l010', page=1, line=10, text_masked=text)
        candidate = CoverageCandidate(
            candidate_id='c00010',
            evidence_line_ids=(line.line_id,),
            text_masked=text,
        )
        draft = copy.deepcopy(self.job.draft_payload)
        draft['coverage_rows'][0].update({
            'raw_name': '뇌혈관질환진단비',
            'assurance_amount': 10_000_000,
            'premium': 14_290,
            'source_candidate_ids': ['c00010'],
            'evidence_line_ids': ['p01-l010'],
        })
        validation = validate_draft(
            (line,), (candidate,), draft, allow_manual=True)
        self.job.masked_lines = [asdict(line)]
        self.job.draft_payload = validation.draft
        system = copy.deepcopy(
            self.job.validation_summary.get('_system', {}))
        self.job.validation_summary = {
            **validation.summary,
            'intake_candidates': [{
                **asdict(candidate),
                'evidence_line_ids': list(candidate.evidence_line_ids),
            }],
            '_system': system,
        }
        self.job.save(update_fields=(
            'masked_lines', 'draft_payload', 'validation_summary'))

        response = self.confirm()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'DRAFT_UNRESOLVED')

    def test_replace_marks_old_insurance_superseded_after_new_is_complete(self):
        source_job = InsuranceExtractionJob.objects.create(
            owner=self.owner, customer=self.customer, intent='add',
            portfolio_type=self.job.portfolio_type, status='confirmed',
            file_sha256=self.job.file_sha256, file_size=100, page_count=1,
            safe_display_name='previous.pdf',
        )
        target = CustomerInsurance.objects.create(
            customer=self.customer, portfolio_type=1,
            review_status='confirmed', analysis_included=True,
            data_version=7, source_job=source_job)
        self.job.intent = 'replace'
        self.job.target_insurance = target
        self.job.target_insurance_version = 7
        self.job.save(update_fields=(
            'intent', 'target_insurance', 'target_insurance_version'))

        response = self.confirm(body={'target_insurance_version': 7})

        self.assertEqual(response.status_code, 200, response.content)
        target.refresh_from_db()
        replacement = CustomerInsurance.objects.exclude(pk=target.pk).get()
        self.assertEqual(replacement.review_status, 'confirmed')
        self.assertEqual(replacement.case_list.count(), 1)
        self.assertEqual(target.review_status, 'superseded')
        self.assertFalse(target.analysis_included)
        self.assertEqual(target.data_version, 8)
        source_job.refresh_from_db()
        self.assertEqual(source_job.status, 'superseded')
        self.assertEqual(
            InsuranceExtractionJob.objects.filter(status='confirmed').count(),
            1,
        )
        self.assertEqual(
            CustomerInsurance.objects.analysis_ready().count(), 1)

    def test_refreshed_replace_draft_exposes_bound_target_and_confirms(self):
        target = CustomerInsurance.objects.create(
            customer=self.customer, portfolio_type=1,
            review_status='confirmed', analysis_included=True,
            data_version=7)
        self.job.intent = 'replace'
        self.job.target_insurance = target
        self.job.target_insurance_version = 7
        self.job.save(update_fields=(
            'intent', 'target_insurance', 'target_insurance_version'))

        refreshed_job = self.client.get(
            f'/api/v1/insurance-imports/{self.job.pk}/')
        refreshed_draft = self.client.get(
            f'/api/v1/insurance-imports/{self.job.pk}/draft/')

        self.assertEqual(refreshed_job.status_code, 200, refreshed_job.content)
        self.assertEqual(
            refreshed_job.json()['target_insurance_id'], target.pk)
        self.assertEqual(
            refreshed_job.json()['target_insurance_version'], 7)
        self.assertEqual(refreshed_draft.status_code, 200,
                         refreshed_draft.content)
        self.assertEqual(
            refreshed_draft.json()['target_insurance_id'], target.pk)
        self.assertEqual(
            refreshed_draft.json()['target_insurance_version'], 7)

        response = self.confirm(body={
            'target_insurance_version': refreshed_draft.json()[
                'target_insurance_version'],
        })

        self.assertEqual(response.status_code, 200, response.content)
        target.refresh_from_db()
        self.assertEqual(target.review_status, 'superseded')

    def test_target_data_version_change_returns_import_target_changed(self):
        target = CustomerInsurance.objects.create(
            customer=self.customer, portfolio_type=1,
            review_status='confirmed', analysis_included=True,
            data_version=2)
        self.job.intent = 'replace'
        self.job.target_insurance = target
        self.job.target_insurance_version = 1
        self.job.save(update_fields=(
            'intent', 'target_insurance', 'target_insurance_version'))

        response = self.confirm(body={'target_insurance_version': 1})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'IMPORT_TARGET_CHANGED')
        self.assertEqual(CustomerInsurance.objects.count(), 1)

    def test_invalid_disposition_cannot_bypass_unresolved_gate(self):
        draft = copy.deepcopy(self.job.draft_payload)
        draft['coverage_rows'][0]['disposition'] = 'provider-invented'
        self.job.draft_payload = draft
        self.job.save(update_fields=['draft_payload'])

        response = self.confirm()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'DRAFT_UNRESOLVED')

    @mock.patch('inpa.insurances.import_services.delete_source')
    def test_confirm_deletes_only_exact_source_after_commit(self, delete_source):
        source_key = self.job.source_storage_key
        with self.captureOnCommitCallbacks(execute=True):
            response = self.confirm()
        self.assertEqual(response.status_code, 200, response.content)
        called_job, = delete_source.call_args.args
        self.assertEqual(called_job.pk, self.job.pk)
        self.assertEqual(delete_source.call_args.kwargs, {'key': source_key})
        self.job.refresh_from_db()
        self.assertIsNotNone(self.job.source_deleted_at)

    @mock.patch('inpa.insurances.import_services.delete_source')
    def test_failed_source_delete_remains_retryable(self, delete_source):
        delete_source.side_effect = OSError('storage unavailable')
        with self.captureOnCommitCallbacks(execute=True):
            response = self.confirm()
        self.assertEqual(response.status_code, 200, response.content)
        self.job.refresh_from_db()
        self.assertIsNone(self.job.source_deleted_at)
        self.assertLessEqual(self.job.source_expires_at, timezone.now())

        delete_source.side_effect = None
        from .import_services import _delete_confirmed_source
        _delete_confirmed_source(self.job.pk, self.job.source_storage_key)
        self.job.refresh_from_db()
        self.assertIsNotNone(self.job.source_deleted_at)

    def test_foreign_job_is_hidden_before_payload_validation(self):
        response = self.foreign_client.post(
            self.url, {}, format='json')
        self.assertEqual(response.status_code, 404)
