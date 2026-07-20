import uuid

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User
from inpa.analysis.models import (
    AnalysisCategory, AnalysisDetail, AnalysisSubCategory,
)
from inpa.customers.models import Customer
from inpa.analytics.sharing import ShareNotReady, assert_shareable

from . import import_services
from .models import CustomerInsurance, ManualInsuranceCommand
from .models import InsuranceCategory, InsuranceDetail, InsuranceSubCategory


def _planner(email):
    user = User.objects.create_user(email=email, password='inpaPass123!')
    user.is_active = True
    user.save(update_fields=['is_active'])
    Profile.objects.create(user=user, email_verified_at=timezone.now())
    client = APIClient()
    client.force_authenticate(user=user)
    return user, client


class ManualInsuranceReviewTests(TestCase):
    def setUp(self):
        self.owner, self.client = _planner('manual-review@test.com')
        self.foreign, self.foreign_client = _planner(
            'manual-foreign@test.com')
        self.customer = Customer.objects.create(
            owner=self.owner, name='직접 입력 고객', birth_day='1990.01.01')
        category = AnalysisCategory.objects.create(name='[표준]진단-암')
        subcategory = AnalysisSubCategory.objects.create(
            category=category, name='일반암')
        self.analysis_detail = AnalysisDetail.objects.create(
            sub_category=subcategory, name='일반암진단비')
        catalog_category = InsuranceCategory.objects.create(name='진단-암')
        catalog_subcategory = InsuranceSubCategory.objects.create(
            category=catalog_category, name='일반암')
        self.catalog_detail = InsuranceDetail.objects.create(
            sub_category=catalog_subcategory, name='일반암진단비')
        self.catalog_detail.analysis_detail.add(self.analysis_detail)

    @property
    def collection_url(self):
        return (
            f'/api/v1/customers/{self.customer.pk}/insurances/manual/')

    def create_insurance(self):
        response = self.client.post(self.collection_url, {
            'name': '직접 입력 보험', 'insurance_type': 2,
            'portfolio_type': 1, 'monthly_premiums': 30000,
        }, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        return CustomerInsurance.objects.get(pk=response.json()['id'])

    def create_insurance_with(self, **overrides):
        payload = {
            'name': '직접 입력 보험',
            'insurance_type': 2,
            'portfolio_type': 1,
            'monthly_premiums': 30_000,
        }
        payload.update(overrides)
        response = self.client.post(
            self.collection_url, payload, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        return CustomerInsurance.objects.get(pk=response.json()['id'])

    def confirm_url(self, insurance):
        return (
            f'/api/v1/customers/{self.customer.pk}/insurances/manual/'
            f'{insurance.pk}/confirm/')

    def coverage_url(self, insurance, case_id=None):
        url = (
            f'/api/v1/customers/{self.customer.pk}/insurances/manual/'
            f'{insurance.pk}/coverages/')
        return f'{url}{case_id}/' if case_id is not None else url

    def exclude_url(self, insurance):
        return (
            f'/api/v1/customers/{self.customer.pk}/insurances/manual/'
            f'{insurance.pk}/exclude/')

    def coverage_payload(self, *, data_version=1, **overrides):
        payload = {
            'data_version': data_version,
            'raw_name': '직접 확인한 일반암진단비',
            'assurance_amount': 30_000_000,
            'premium': 30_000,
            'is_renewal': False,
            'renewal_period': None,
            'payment_period': 20,
            'payment_period_unit': 'years',
            'warranty_period': 100,
            'warranty_period_unit': 'age',
            'standard_category': '진단-암',
            'standard_subcategory': '일반암',
            'standard_detail_name': '일반암진단비',
        }
        payload.update(overrides)
        return payload

    @override_settings(INSURANCE_REVIEW_GATE_ENABLED=False)
    def test_manual_create_starts_as_draft_and_excluded_from_analysis(self):
        insurance = self.create_insurance()
        self.assertEqual(insurance.review_status, 'draft')
        self.assertFalse(insurance.analysis_included)
        self.assertEqual(insurance.confirmation_source, '')
        self.assertFalse(CustomerInsurance.objects.filter(
            pk=insurance.pk).analysis_ready().exists())
        with self.assertRaises(ShareNotReady):
            assert_shareable(self.customer)

    def test_owner_can_create_patch_delete_manual_coverage(self):
        insurance = self.create_insurance()
        created = self.client.post(
            self.coverage_url(insurance), self.coverage_payload(),
            format='json')
        self.assertEqual(created.status_code, 201, created.content)
        case = insurance.case_list.get()
        self.assertEqual(case.mapping_source, 'manual')
        self.assertEqual(case.source_candidate_ids, [])
        self.assertEqual(case.evidence_line_ids, [])
        self.assertEqual(case.source_text_masked, '')
        self.assertEqual(
            list(case.analysis_detail_override.all()), [self.analysis_detail])

        patched = self.client.patch(
            self.coverage_url(insurance, case.pk),
            {'premium': 25_000, 'data_version': insurance.data_version + 1},
            format='json')
        self.assertEqual(patched.status_code, 200, patched.content)
        case.refresh_from_db()
        self.assertEqual(case.premium, 25_000)

        insurance.refresh_from_db()
        deleted = self.client.delete(
            self.coverage_url(insurance, case.pk),
            {'data_version': insurance.data_version}, format='json')
        self.assertEqual(deleted.status_code, 200, deleted.content)
        self.assertFalse(insurance.case_list.exists())

    def test_manual_coverage_mutations_return_authoritative_version(self):
        insurance = self.create_insurance()

        created = self.client.post(
            self.coverage_url(insurance), self.coverage_payload(),
            format='json')

        self.assertEqual(created.status_code, 201, created.content)
        created_body = created.json()
        self.assertEqual(created_body['data_version'], 2)
        case_id = created_body['id']

        patched = self.client.patch(
            self.coverage_url(insurance, case_id), {
                'premium': 25_000,
                'data_version': created_body['data_version'],
            }, format='json')

        self.assertEqual(patched.status_code, 200, patched.content)
        patched_body = patched.json()
        self.assertEqual(patched_body['data_version'], 3)
        self.assertEqual(patched_body['premium'], 25_000)

        deleted = self.client.delete(
            self.coverage_url(insurance, case_id), {
                'data_version': patched_body['data_version'],
            }, format='json')

        self.assertEqual(deleted.status_code, 200, deleted.content)
        self.assertEqual(deleted.json(), {
            'insurance_id': insurance.pk,
            'deleted_coverage_id': case_id,
            'data_version': 4,
        })
        insurance.refresh_from_db()
        self.assertEqual(insurance.data_version, 4)

    def test_manual_coverage_rejects_mass_assignment_and_invalid_periods(self):
        insurance = self.create_insurance()
        forged = self.client.post(
            self.coverage_url(insurance),
            self.coverage_payload(
                insurance=999, mapping_source='global', confirmed_at='now'),
            format='json')
        invalid = self.client.post(
            self.coverage_url(insurance),
            self.coverage_payload(
                payment_period=101, warranty_period=100,
                warranty_period_unit='years'),
            format='json')
        self.assertEqual(forged.status_code, 400)
        self.assertEqual(invalid.status_code, 400)
        self.assertFalse(insurance.case_list.exists())

    def test_manual_create_rejects_invalid_policy_values_early(self):
        cases = (
            {'insurance_type': None},
            {'monthly_premiums': -1},
            {'contract_date': '2024-99-01'},
            {
                'contract_date': '2025-01-01',
                'expiry_date': '2024-01-01',
            },
        )
        for override in cases:
            with self.subTest(override=override):
                payload = {
                    'name': '기본정보 오류',
                    'insurance_type': 2,
                    'portfolio_type': 1,
                    **override,
                }
                response = self.client.post(
                    self.collection_url, payload, format='json')
                self.assertEqual(response.status_code, 400, response.content)

    def test_manual_confirm_revalidates_actual_policy_fields(self):
        insurance = self.create_insurance()
        created = self.client.post(
            self.coverage_url(insurance), self.coverage_payload(),
            format='json')
        self.assertEqual(created.status_code, 201, created.content)
        insurance.refresh_from_db()
        CustomerInsurance.objects.filter(pk=insurance.pk).update(
            monthly_premiums=-1)

        response = self.client.post(
            f'/api/v1/customers/{self.customer.pk}/insurances/manual/'
            f'{insurance.pk}/confirm/',
            {
                'data_version': insurance.data_version,
                'planner_confirmed_contents': True,
            }, format='json', HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'MANUAL_POLICY_INVALID')
        insurance.refresh_from_db()
        self.assertEqual(insurance.review_status, 'draft')
        self.assertFalse(insurance.analysis_included)

    def test_manual_confirm_blocks_assigned_coverage_without_assurance_amount(self):
        insurance = self.create_insurance()
        created = self.client.post(
            self.coverage_url(insurance),
            self.coverage_payload(),
            format='json')
        self.assertEqual(created.status_code, 201, created.content)
        insurance.case_list.update(assurance_amount=None)
        insurance.refresh_from_db()

        response = self.client.post(
            self.confirm_url(insurance), {
                'data_version': insurance.data_version,
                'planner_confirmed_contents': True,
            }, format='json', HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()['code'], 'MANUAL_DRAFT_INVALID')
        self.assertIn('ASSURANCE_AMOUNT_REQUIRED', {
            issue['code'] for issue in response.json()['issues']
        })
        insurance.refresh_from_db()
        self.assertEqual(insurance.review_status, 'draft')
        self.assertFalse(insurance.analysis_included)

    def test_manual_confirm_blocks_partial_premium_sum(self):
        insurance = self.create_insurance_with(monthly_premiums=None)
        first = self.client.post(
            self.coverage_url(insurance),
            self.coverage_payload(premium=20_000),
            format='json')
        self.assertEqual(first.status_code, 201, first.content)
        insurance.refresh_from_db()
        second = self.client.post(
            self.coverage_url(insurance),
            self.coverage_payload(
                data_version=insurance.data_version,
                raw_name='직접 확인한 두 번째 일반암진단비',
                premium=None,
            ), format='json')
        self.assertEqual(second.status_code, 201, second.content)
        insurance.refresh_from_db()

        response = self.client.post(
            self.confirm_url(insurance), {
                'data_version': insurance.data_version,
                'planner_confirmed_contents': True,
            }, format='json', HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()['code'], 'MANUAL_POLICY_INVALID')
        self.assertIn('PREMIUM_SUM_INCOMPLETE', {
            issue['code'] for issue in response.json()['issues']
        })
        insurance.refresh_from_db()
        self.assertEqual(insurance.review_status, 'draft')
        self.assertFalse(insurance.analysis_included)

    def test_manual_confirm_uses_shared_validation_and_marks_all_confirmed(self):
        insurance = self.create_insurance()
        created = self.client.post(
            self.coverage_url(insurance), self.coverage_payload(),
            format='json')
        self.assertEqual(created.status_code, 201, created.content)
        insurance.refresh_from_db()
        response = self.client.post(
            f'/api/v1/customers/{self.customer.pk}/insurances/manual/'
            f'{insurance.pk}/confirm/',
            {
                'data_version': insurance.data_version,
                'planner_confirmed_contents': True,
            }, format='json',
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
        self.assertEqual(response.status_code, 200, response.content)
        insurance.refresh_from_db()
        self.assertEqual(insurance.review_status, 'confirmed')
        self.assertTrue(insurance.analysis_included)
        self.assertEqual(insurance.confirmation_source, 'manual_entry')
        self.assertEqual(insurance.confirmed_by, self.owner)
        self.assertIsNotNone(insurance.confirmed_at)
        self.assertIsNotNone(insurance.case_list.get().confirmed_at)

    def test_manual_loss_renewal_missing_expiry_blocks_unknown_months(self):
        insurance = self.create_insurance_with(
            contract_date='2024-01-01')
        created = self.client.post(
            self.coverage_url(insurance),
            self.coverage_payload(
                is_renewal=True,
                renewal_period=10),
            format='json')
        self.assertEqual(created.status_code, 201, created.content)
        insurance.refresh_from_db()

        response = self.client.post(
            self.confirm_url(insurance),
            {
                'data_version': insurance.data_version,
                'planner_confirmed_contents': True,
            }, format='json', HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()['code'], 'DRAFT_UNRESOLVED')
        insurance.refresh_from_db()
        self.assertEqual(insurance.review_status, 'draft')

    def test_manual_life_renewal_accepts_iso_dates_and_birth(self):
        self.customer.birth_day = '1990-01-01'
        self.customer.save(update_fields=['birth_day'])
        insurance = self.create_insurance_with(
            insurance_type=1,
            contract_date='2024-01-01',
            expiry_date='2044-01-01')
        created = self.client.post(
            self.coverage_url(insurance),
            self.coverage_payload(
                is_renewal=True,
                renewal_period=10),
            format='json')
        self.assertEqual(created.status_code, 201, created.content)
        insurance.refresh_from_db()

        response = self.client.post(
            self.confirm_url(insurance),
            {
                'data_version': insurance.data_version,
                'planner_confirmed_contents': True,
            }, format='json', HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))

        self.assertEqual(response.status_code, 200, response.content)
        insurance.refresh_from_db()
        self.assertGreater(insurance.renewal_month, 0)
        self.assertGreater(
            insurance.case_list.get().total_renewal_premium, 0)

    def test_manual_life_renewal_invalid_birth_returns_409(self):
        self.customer.birth_day = '1990-02-30'
        self.customer.save(update_fields=['birth_day'])
        insurance = self.create_insurance_with(
            insurance_type=1,
            contract_date='2024.01.01',
            expiry_date='2044.01.01')
        created = self.client.post(
            self.coverage_url(insurance),
            self.coverage_payload(
                is_renewal=True,
                renewal_period=10),
            format='json')
        self.assertEqual(created.status_code, 201, created.content)
        insurance.refresh_from_db()
        self.client.raise_request_exception = False

        response = self.client.post(
            self.confirm_url(insurance),
            {
                'data_version': insurance.data_version,
                'planner_confirmed_contents': True,
            }, format='json', HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()['code'], 'DRAFT_UNRESOLVED')

    def test_manual_lifetime_roundtrip_keeps_monthly_fact_and_unknown_total(self):
        insurance = self.create_insurance_with(
            contract_date='2024.01.01')
        created = self.client.post(
            self.coverage_url(insurance),
            self.coverage_payload(
                payment_period=None,
                payment_period_unit='lifetime'),
            format='json')

        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(created.json()['payment_period_unit'], 'lifetime')
        case = insurance.case_list.get()
        self.assertEqual(case.payment_period_type, 4)
        self.assertIsNone(case.payment_period)
        insurance.refresh_from_db()
        confirmed = self.client.post(
            self.confirm_url(insurance),
            {
                'data_version': insurance.data_version,
                'planner_confirmed_contents': True,
            }, format='json', HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
        self.assertEqual(confirmed.status_code, 200, confirmed.content)
        insurance.refresh_from_db()
        case.refresh_from_db()
        self.assertEqual(insurance.monthly_non_renewal_premium, 30_000)
        self.assertIsNone(insurance.total_premiums)
        self.assertIsNone(case.total_non_renewal_premium)

    def test_manual_lifetime_rejects_contradictory_numeric_period(self):
        insurance = self.create_insurance()

        response = self.client.post(
            self.coverage_url(insurance),
            self.coverage_payload(
                payment_period=20,
                payment_period_unit='lifetime'),
            format='json')

        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(insurance.case_list.exists())

    def test_manual_confirm_rejects_empty_and_stale_version(self):
        insurance = self.create_insurance()
        url = (
            f'/api/v1/customers/{self.customer.pk}/insurances/manual/'
            f'{insurance.pk}/confirm/')
        empty = self.client.post(
            url, {
                'data_version': insurance.data_version,
                'planner_confirmed_contents': True,
            }, format='json', HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
        stale = self.client.post(
            url, {
                'data_version': 999,
                'planner_confirmed_contents': True,
            }, format='json', HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
        self.assertEqual(empty.status_code, 409)
        self.assertEqual(empty.json()['code'], 'MANUAL_COVERAGE_REQUIRED')
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()['code'], 'INSURANCE_VERSION_CHANGED')

    def test_manual_delete_requires_current_version_and_deletes_draft(self):
        insurance = self.create_insurance()
        url = f'{self.collection_url}{insurance.pk}/'

        missing = self.client.delete(url, {}, format='json')
        stale = self.client.delete(
            url, {'data_version': insurance.data_version + 1}, format='json')

        self.assertEqual(missing.status_code, 400, missing.content)
        self.assertEqual(stale.status_code, 409, stale.content)
        self.assertEqual(stale.json()['code'], 'INSURANCE_VERSION_CHANGED')
        self.assertTrue(CustomerInsurance.objects.filter(pk=insurance.pk).exists())

        deleted = self.client.delete(
            url, {'data_version': insurance.data_version}, format='json')

        self.assertEqual(deleted.status_code, 204, deleted.content)
        self.assertFalse(CustomerInsurance.objects.filter(pk=insurance.pk).exists())

    def test_manual_delete_preserves_reviewed_records(self):
        reviewed_states = ('confirmed', 'excluded', 'superseded')
        for review_status in reviewed_states:
            with self.subTest(review_status=review_status):
                insurance = self.create_insurance()
                CustomerInsurance.objects.filter(pk=insurance.pk).update(
                    review_status=review_status,
                    analysis_included=review_status == 'confirmed',
                )
                insurance.refresh_from_db()

                response = self.client.delete(
                    f'{self.collection_url}{insurance.pk}/',
                    {'data_version': insurance.data_version}, format='json')

                self.assertEqual(response.status_code, 409, response.content)
                self.assertTrue(CustomerInsurance.objects.filter(
                    pk=insurance.pk).exists())

    def test_foreign_manual_insurance_and_coverage_are_always_404(self):
        insurance = self.create_insurance()
        created = self.client.post(
            self.coverage_url(insurance), self.coverage_payload(),
            format='json')
        case_id = created.json()['id']
        for method, url, body in (
            ('post', self.coverage_url(insurance), self.coverage_payload()),
            ('patch', self.coverage_url(insurance, case_id), {'premium': 1}),
            ('delete', self.coverage_url(insurance, case_id), {}),
            ('post', (
                f'/api/v1/customers/{self.customer.pk}/insurances/manual/'
                f'{insurance.pk}/confirm/'), {'data_version': 1}),
        ):
            response = getattr(self.foreign_client, method)(
                url, body, format='json')
            self.assertEqual(response.status_code, 404, (method, response.content))
        response = self.foreign_client.get(self.coverage_url(insurance))
        self.assertEqual(response.status_code, 404)

    def test_admin_can_read_but_cannot_mutate_foreign_manual_insurance(self):
        insurance = self.create_insurance()
        admin, admin_client = _planner('manual-admin@test.com')
        admin.profile.is_admin = True
        admin.profile.save(update_fields=['is_admin'])
        detail_url = f'{self.collection_url}{insurance.pk}/'

        readable = admin_client.get(detail_url)
        self.assertEqual(readable.status_code, 200, readable.content)

        create = admin_client.post(self.collection_url, {
            'name': '관리자가 만든 보험',
            'insurance_type': 2,
            'portfolio_type': 1,
            'monthly_premiums': 30_000,
        }, format='json')
        patch = admin_client.patch(detail_url, {
            'name': '관리자가 바꾼 보험',
            'data_version': insurance.data_version,
        }, format='json')
        delete = admin_client.delete(detail_url, {
            'data_version': insurance.data_version,
        }, format='json')

        self.assertEqual(create.status_code, 404, create.content)
        self.assertEqual(patch.status_code, 404, patch.content)
        self.assertEqual(delete.status_code, 404, delete.content)
        insurance.refresh_from_db()
        self.assertEqual(insurance.name, '직접 입력 보험')

    def test_existing_manual_list_and_create_contract_remains_compatible(self):
        insurance = self.create_insurance()
        listed = self.client.get(self.collection_url)
        self.assertEqual(listed.status_code, 200)
        rows = listed.json().get('results', listed.json())
        self.assertEqual(rows[0]['id'], insurance.pk)
        self.assertEqual(rows[0]['name'], '직접 입력 보험')

    def test_manual_mapping_does_not_mutate_global_catalog_mapping(self):
        unrelated = AnalysisDetail.objects.create(
            sub_category=self.analysis_detail.sub_category, name='기존전역위치')
        self.catalog_detail.analysis_detail.add(unrelated)
        before = list(
            self.catalog_detail.analysis_detail.values_list('pk', flat=True))
        insurance = self.create_insurance()

        created = self.client.post(
            self.coverage_url(insurance), self.coverage_payload(),
            format='json')

        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(
            list(self.catalog_detail.analysis_detail.values_list(
                'pk', flat=True)), before)
        case = insurance.case_list.get()
        self.assertEqual(
            list(case.analysis_detail_override.all()), [self.analysis_detail])

    def test_manual_coverage_requires_one_seeded_catalog_mapping(self):
        self.catalog_detail.delete()
        before = (
            InsuranceCategory.objects.count(),
            InsuranceSubCategory.objects.count(),
            InsuranceDetail.objects.count(),
        )
        insurance = self.create_insurance()

        response = self.client.post(
            self.coverage_url(insurance), self.coverage_payload(),
            format='json')

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()['code'], 'STANDARD_COVERAGE_NOT_READY')
        self.assertEqual((
            InsuranceCategory.objects.count(),
            InsuranceSubCategory.objects.count(),
            InsuranceDetail.objects.count(),
        ), before)
        self.assertFalse(insurance.case_list.exists())

    def test_manual_coverage_collection_get_returns_safe_review_contract(self):
        insurance = self.create_insurance()
        created = self.client.post(
            self.coverage_url(insurance), self.coverage_payload(),
            format='json')
        self.assertEqual(created.status_code, 201, created.content)
        insurance.refresh_from_db()

        response = self.client.get(self.coverage_url(insurance))

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body['insurance_id'], insurance.pk)
        self.assertEqual(body['data_version'], insurance.data_version)
        self.assertEqual(body['review_status'], 'draft')
        self.assertFalse(body['analysis_included'])
        self.assertEqual(len(body['coverages']), 1)
        coverage = body['coverages'][0]
        self.assertEqual(coverage['standard_detail_id'], self.analysis_detail.pk)
        self.assertEqual(coverage['standard_category'], '진단-암')
        self.assertEqual(coverage['standard_subcategory'], '일반암')
        self.assertEqual(coverage['standard_detail_name'], '일반암진단비')
        self.assertEqual(coverage['mapping_source'], 'manual')
        self.assertEqual(coverage['source_candidate_ids'], [])
        self.assertEqual(coverage['evidence_line_ids'], [])
        self.assertNotIn('source_text_masked', coverage)

    def test_manual_review_bundle_uses_versioned_import_catalog_authority(self):
        insurance = self.create_insurance()

        response = self.client.get(self.coverage_url(insurance))

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body['insurance']['id'], insurance.pk)
        self.assertEqual(
            body['insurance']['data_version'], insurance.data_version)
        self.assertEqual(body['insurance']['review_status'], 'draft')
        self.assertEqual(body['confirmation_requirements'], {
            'planner_confirmed_contents': {'required': True},
        })
        self.assertEqual(
            body['standard_coverages']['version'],
            import_services.CURRENT_NORMALIZATION_VERSION,
        )
        self.assertEqual(
            body['standard_coverages']['items'],
            list(import_services._STANDARD_COVERAGE_ITEMS),
        )

    def test_manual_confirm_requires_literal_true(self):
        invalid_values = (
            ('missing', None),
            ('false', False),
            ('string', 'true'),
        )
        for label, value in invalid_values:
            with self.subTest(value=label):
                insurance = self.create_insurance()
                created = self.client.post(
                    self.coverage_url(insurance), self.coverage_payload(),
                    format='json')
                self.assertEqual(created.status_code, 201, created.content)
                insurance.refresh_from_db()
                payload = {'data_version': insurance.data_version}
                if value is not None:
                    payload['planner_confirmed_contents'] = value

                response = self.client.post(
                    self.confirm_url(insurance), payload, format='json',
                    HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))

                self.assertEqual(response.status_code, 400, response.content)
                insurance.refresh_from_db()
                self.assertEqual(insurance.review_status, 'draft')
                self.assertFalse(insurance.analysis_included)

    def test_manual_confirm_returns_server_confirmation_authority(self):
        insurance = self.create_insurance()
        created = self.client.post(
            self.coverage_url(insurance), self.coverage_payload(),
            format='json')
        self.assertEqual(created.status_code, 201, created.content)
        insurance.refresh_from_db()

        response = self.client.post(
            self.confirm_url(insurance), {
                'data_version': insurance.data_version,
                'planner_confirmed_contents': True,
            }, format='json', HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body['insurance_id'], insurance.pk)
        self.assertEqual(body['review_status'], 'confirmed')
        self.assertTrue(body['analysis_included'])
        self.assertEqual(body['confirmation_source'], 'manual_entry')
        self.assertIsNotNone(body['confirmed_at'])
        self.assertEqual(body['data_version'], insurance.data_version + 1)

    def test_manual_confirm_replays_same_key_and_body_after_lost_response(self):
        insurance = self.create_insurance()
        created = self.client.post(
            self.coverage_url(insurance), self.coverage_payload(),
            format='json')
        self.assertEqual(created.status_code, 201, created.content)
        insurance.refresh_from_db()
        payload = {
            'data_version': insurance.data_version,
            'planner_confirmed_contents': True,
        }
        key = str(uuid.uuid4())

        first = self.client.post(
            self.confirm_url(insurance), payload, format='json',
            HTTP_IDEMPOTENCY_KEY=key)
        replay = self.client.post(
            self.confirm_url(insurance), payload, format='json',
            HTTP_IDEMPOTENCY_KEY=key)

        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(replay.status_code, 200, replay.content)
        self.assertEqual(replay.json(), first.json())
        insurance.refresh_from_db()
        self.assertEqual(insurance.data_version, payload['data_version'] + 1)

    def test_manual_confirm_rejects_same_key_with_different_body(self):
        insurance = self.create_insurance()
        created = self.client.post(
            self.coverage_url(insurance), self.coverage_payload(),
            format='json')
        self.assertEqual(created.status_code, 201, created.content)
        insurance.refresh_from_db()
        payload = {
            'data_version': insurance.data_version,
            'planner_confirmed_contents': True,
        }
        key = str(uuid.uuid4())
        first = self.client.post(
            self.confirm_url(insurance), payload, format='json',
            HTTP_IDEMPOTENCY_KEY=key)
        self.assertEqual(first.status_code, 200, first.content)

        reused = self.client.post(
            self.confirm_url(insurance), {
                **payload,
                'data_version': payload['data_version'] + 1,
            }, format='json', HTTP_IDEMPOTENCY_KEY=key)

        self.assertEqual(reused.status_code, 409, reused.content)
        self.assertEqual(reused.json()['code'], 'IDEMPOTENCY_KEY_REUSED')

    def test_manual_confirm_reports_same_request_command_in_progress(self):
        insurance = self.create_insurance()
        created = self.client.post(
            self.coverage_url(insurance), self.coverage_payload(),
            format='json')
        self.assertEqual(created.status_code, 201, created.content)
        payload = {
            'data_version': created.json()['data_version'],
            'planner_confirmed_contents': True,
        }
        key = uuid.uuid4()
        ManualInsuranceCommand.objects.create(
            insurance=insurance,
            operation='confirm',
            idempotency_key=key,
            request_sha256=import_services._command_request_sha256(payload),
        )

        response = self.client.post(
            self.confirm_url(insurance), payload, format='json',
            HTTP_IDEMPOTENCY_KEY=str(key))

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()['code'], 'COMMAND_IN_PROGRESS')
        insurance.refresh_from_db()
        self.assertEqual(insurance.review_status, 'draft')

    def test_confirm_and_exclude_same_version_allow_only_first_command(self):
        excluded_first = self.create_insurance()
        created = self.client.post(
            self.coverage_url(excluded_first), self.coverage_payload(),
            format='json')
        self.assertEqual(created.status_code, 201, created.content)
        contested_version = created.json()['data_version']

        excluded = self.client.post(self.exclude_url(excluded_first), {
            'data_version': contested_version,
            'reason': '중복 기록',
        }, format='json')
        late_confirm = self.client.post(
            self.confirm_url(excluded_first), {
                'data_version': contested_version,
                'planner_confirmed_contents': True,
            }, format='json', HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
        self.assertEqual((excluded.status_code, late_confirm.status_code),
                         (200, 409))
        excluded_first.refresh_from_db()
        self.assertEqual(excluded_first.review_status, 'excluded')

        confirmed_first = self.create_insurance()
        created = self.client.post(
            self.coverage_url(confirmed_first), self.coverage_payload(),
            format='json')
        self.assertEqual(created.status_code, 201, created.content)
        contested_version = created.json()['data_version']

        confirmed = self.client.post(
            self.confirm_url(confirmed_first), {
                'data_version': contested_version,
                'planner_confirmed_contents': True,
            }, format='json', HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
        late_exclude = self.client.post(self.exclude_url(confirmed_first), {
            'data_version': contested_version,
            'reason': '뒤늦은 제외',
        }, format='json')
        self.assertEqual((confirmed.status_code, late_exclude.status_code),
                         (200, 409))
        confirmed_first.refresh_from_db()
        self.assertEqual(confirmed_first.review_status, 'confirmed')

    def test_manual_confirm_requires_valid_idempotency_key(self):
        insurance = self.create_insurance()
        created = self.client.post(
            self.coverage_url(insurance), self.coverage_payload(),
            format='json')
        self.assertEqual(created.status_code, 201, created.content)
        payload = {
            'data_version': created.json()['data_version'],
            'planner_confirmed_contents': True,
        }

        missing = self.client.post(
            self.confirm_url(insurance), payload, format='json')
        malformed = self.client.post(
            self.confirm_url(insurance), payload, format='json',
            HTTP_IDEMPOTENCY_KEY='not-a-uuid')

        self.assertEqual(missing.status_code, 400, missing.content)
        self.assertEqual(malformed.status_code, 400, malformed.content)
        insurance.refresh_from_db()
        self.assertEqual(insurance.review_status, 'draft')

    @override_settings(INSURANCE_REVIEW_GATE_ENABLED=False)
    def test_manual_exclude_preserves_insurance_and_increments_version(self):
        insurance = self.create_insurance()

        response = self.client.post(self.exclude_url(insurance), {
            'data_version': insurance.data_version,
            'reason': '  분석 대상이 아닌 중복 기록  ',
        }, format='json')

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), {
            'insurance_id': insurance.pk,
            'review_status': 'excluded',
            'analysis_included': False,
            'data_version': insurance.data_version + 1,
            'exclusion_reason': '분석 대상이 아닌 중복 기록',
        })
        insurance.refresh_from_db()
        self.assertEqual(insurance.review_status, 'excluded')
        self.assertFalse(insurance.analysis_included)
        self.assertEqual(
            insurance.review_exclusion_reason, '분석 대상이 아닌 중복 기록')
        self.assertTrue(CustomerInsurance.objects.filter(pk=insurance.pk).exists())
        self.assertFalse(CustomerInsurance.objects.filter(
            pk=insurance.pk).analysis_ready().exists())
        with self.assertRaises(ShareNotReady):
            assert_shareable(self.customer)

    def test_manual_exclude_requires_current_version_and_bounded_reason(self):
        invalid_reasons = ('', '   ', '가' * 501)
        for reason in invalid_reasons:
            with self.subTest(reason_length=len(reason)):
                insurance = self.create_insurance()
                response = self.client.post(self.exclude_url(insurance), {
                    'data_version': insurance.data_version,
                    'reason': reason,
                }, format='json')
                self.assertEqual(response.status_code, 400, response.content)
                insurance.refresh_from_db()
                self.assertEqual(insurance.review_status, 'draft')

        insurance = self.create_insurance()
        stale = self.client.post(self.exclude_url(insurance), {
            'data_version': insurance.data_version + 1,
            'reason': '중복 기록',
        }, format='json')
        self.assertEqual(stale.status_code, 409, stale.content)
        self.assertEqual(stale.json()['code'], 'INSURANCE_VERSION_CHANGED')

    def test_manual_exclude_hides_foreign_and_rejects_terminal_states(self):
        insurance = self.create_insurance()
        foreign = self.foreign_client.post(self.exclude_url(insurance), {
            'data_version': insurance.data_version,
            'reason': '다른 소유자 요청',
        }, format='json')
        self.assertEqual(foreign.status_code, 404, foreign.content)

        terminal_states = (
            ('confirmed', False),
            ('superseded', False),
            ('draft', True),
        )
        for review_status, is_cancelled in terminal_states:
            with self.subTest(
                    review_status=review_status, is_cancelled=is_cancelled):
                insurance = self.create_insurance()
                CustomerInsurance.objects.filter(pk=insurance.pk).update(
                    review_status=review_status,
                    analysis_included=(review_status == 'confirmed'),
                    is_cancelled=is_cancelled,
                )
                insurance.refresh_from_db()

                response = self.client.post(self.exclude_url(insurance), {
                    'data_version': insurance.data_version,
                    'reason': '분석 대상 아님',
                }, format='json')

                self.assertEqual(response.status_code, 409, response.content)
                insurance.refresh_from_db()
                self.assertEqual(insurance.review_status, review_status)
                self.assertEqual(insurance.is_cancelled, is_cancelled)

    def test_legacy_review_can_patch_and_confirm_without_overwriting_provenance(self):
        legacy = CustomerInsurance.objects.create(
            customer=self.customer,
            name='기존 보험',
            insurance_type=2,
            portfolio_type=1,
            monthly_premiums=30_000,
            contract_date='2024.01.01',
            expiry_date='2044.01.01',
            review_status='legacy_review_required',
            analysis_included=False,
        )
        case = legacy.case_list.create(
            detail=self.catalog_detail,
            raw_name='기존 일반암진단비',
            assurance_amount=30_000_000,
            premium=30_000,
            payment_period=20,
            payment_period_type=1,
            warranty_period='100',
            warranty_period_type=1,
            mapping_source='global',
            source_page=7,
            source_line_start=10,
            source_line_end=10,
            source_text_masked='가명 처리된 근거',
            source_candidate_ids=['legacy-c1'],
            evidence_line_ids=['p07-l010'],
            review_reason=['LEGACY_REVIEW'],
        )
        detail_id = case.detail_id
        before_override = list(
            case.analysis_detail_override.values_list('pk', flat=True))

        listed = self.client.get(self.coverage_url(legacy))
        self.assertEqual(listed.status_code, 200, listed.content)
        self.assertEqual(listed.json()['review_status'], 'legacy_review_required')
        patched_policy = self.client.patch(
            f'{self.collection_url}{legacy.pk}/',
            {'name': '확인한 기존 보험', 'data_version': legacy.data_version},
            format='json')
        self.assertEqual(patched_policy.status_code, 200, patched_policy.content)
        legacy.refresh_from_db()
        patched_case = self.client.patch(
            self.coverage_url(legacy, case.pk),
            {'premium': 30_000, 'data_version': legacy.data_version},
            format='json')
        self.assertEqual(patched_case.status_code, 200, patched_case.content)

        case.refresh_from_db()
        self.assertEqual(case.detail_id, detail_id)
        self.assertEqual(case.mapping_source, 'global')
        self.assertEqual(
            list(case.analysis_detail_override.values_list('pk', flat=True)),
            before_override)
        self.assertEqual(case.source_page, 7)
        self.assertEqual(case.source_line_start, 10)
        self.assertEqual(case.source_line_end, 10)
        self.assertEqual(case.source_text_masked, '가명 처리된 근거')
        self.assertEqual(case.source_candidate_ids, ['legacy-c1'])
        self.assertEqual(case.evidence_line_ids, ['p07-l010'])
        self.assertEqual(case.review_reason, ['LEGACY_REVIEW'])

        legacy.refresh_from_db()
        confirmed = self.client.post(
            f'{self.collection_url}{legacy.pk}/confirm/',
            {
                'data_version': legacy.data_version,
                'planner_confirmed_contents': True,
            }, format='json', HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
        self.assertEqual(confirmed.status_code, 200, confirmed.content)
        legacy.refresh_from_db()
        self.assertEqual(legacy.review_status, 'confirmed')
        self.assertTrue(legacy.analysis_included)
        self.assertEqual(legacy.confirmation_source, 'legacy_review')

    def test_legacy_review_stale_version_returns_409(self):
        legacy = CustomerInsurance.objects.create(
            customer=self.customer,
            name='기존 보험',
            insurance_type=2,
            portfolio_type=1,
            review_status='legacy_review_required',
        )
        response = self.client.patch(
            f'{self.collection_url}{legacy.pk}/',
            {'name': '오래된 수정', 'data_version': 999},
            format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'INSURANCE_VERSION_CHANGED')

    def test_legacy_non_numeric_warranty_requires_manual_correction(self):
        legacy = CustomerInsurance.objects.create(
            customer=self.customer,
            name='기존 기간 확인 보험',
            insurance_type=2,
            portfolio_type=1,
            review_status='legacy_review_required',
        )
        legacy.case_list.create(
            detail=self.catalog_detail,
            raw_name='기존 일반암진단비',
            assurance_amount=30_000_000,
            premium=30_000,
            payment_period=20,
            payment_period_type=1,
            warranty_period='확인필요',
            warranty_period_type=2,
            mapping_source='global',
        )

        response = self.client.post(
            f'{self.collection_url}{legacy.pk}/confirm/',
            {
                'data_version': legacy.data_version,
                'planner_confirmed_contents': True,
            }, format='json', HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'MANUAL_DRAFT_INVALID')
        legacy.refresh_from_db()
        self.assertEqual(legacy.review_status, 'legacy_review_required')

    def test_manual_coverage_stale_data_version_returns_409(self):
        insurance = self.create_insurance()
        created = self.client.post(
            self.coverage_url(insurance), self.coverage_payload(),
            format='json')
        self.assertEqual(created.status_code, 201, created.content)
        case_id = created.json()['id']

        response = self.client.patch(
            self.coverage_url(insurance, case_id),
            {'premium': 1, 'data_version': 1}, format='json')

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'INSURANCE_VERSION_CHANGED')

    def test_manual_insurance_rejects_server_owned_fields(self):
        response = self.client.post(self.collection_url, {
            'name': '위조 시도', 'portfolio_type': 1,
            'review_status': 'confirmed', 'analysis_included': True,
            'confirmation_source': 'planner_review',
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(CustomerInsurance.objects.exists())

    def test_existing_rows_keep_legacy_and_empty_provenance_defaults(self):
        insurance = CustomerInsurance.objects.create(
            customer=self.customer, portfolio_type=1)
        self.assertEqual(insurance.review_status, 'legacy_review_required')
        self.assertFalse(insurance.analysis_included)
        category = InsuranceCategory.objects.create(name='기존')
        subcategory = InsuranceSubCategory.objects.create(
            category=category, name='기존')
        catalog = InsuranceDetail.objects.create(
            sub_category=subcategory, name='기존')
        case = insurance.case_list.create(detail=catalog)
        self.assertEqual(case.source_candidate_ids, [])
        self.assertEqual(case.evidence_line_ids, [])
        self.assertIsNone(case.renewal_period)
