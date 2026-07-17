import uuid

from django.contrib import admin as django_admin
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import RequestFactory, TestCase, override_settings

from inpa.accounts.models import User
from inpa.analysis.models import (
    AnalysisCategory,
    AnalysisDetail,
    AnalysisSubCategory,
)
from inpa.customers.models import Customer

from .admin import (
    InsuranceExtractionJobAdmin,
    InsuranceExtractionResultAdmin,
    InsuranceImportCommandAdmin,
    InsuranceImportCreateRequestAdmin,
    InsuranceImportRuntimeConfigAdmin,
)
from .models import (
    CustomerInsurance,
    CustomerInsuranceDetail,
    InsuranceCategory,
    InsuranceDetail,
    InsuranceExtractionJob,
    InsuranceExtractionResult,
    InsuranceImportCommand,
    InsuranceImportCreateRequest,
    InsuranceImportRuntimeConfig,
    InsuranceSubCategory,
    ManualInsuranceCommand,
)


class InsuranceExtractionModelTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email='owner@example.com', password='inpaPass123!')
        self.other_owner = User.objects.create_user(
            email='other@example.com', password='inpaPass123!')
        self.customer = Customer.objects.create(owner=self.owner, name='첫 고객')
        self.other_customer = Customer.objects.create(
            owner=self.other_owner, name='다른 고객')
        self.file_sha256 = 'f' * 64
        self.command_key = uuid.uuid4()

    def make_job(self, owner=None, customer=None, **overrides):
        values = {
            'owner': owner or self.owner,
            'customer': customer or self.customer,
            'intent': 'add',
            'portfolio_type': 1,
            'file_sha256': self.file_sha256,
            'file_size': 1024,
            'safe_display_name': 'policy.pdf',
        }
        values.update(overrides)
        return InsuranceExtractionJob.objects.create(**values)

    def test_same_active_hash_is_unique_only_within_owner_customer_and_portfolio(self):
        self.make_job()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.make_job()

    def test_same_hash_different_owner_creates_independent_jobs(self):
        first = self.make_job()
        second = self.make_job(
            owner=self.other_owner, customer=self.other_customer)
        self.assertNotEqual(first.id, second.id)

    def test_same_hash_same_owner_different_customer_creates_independent_jobs(self):
        other_customer = Customer.objects.create(
            owner=self.owner, name='같은 설계사의 다른 고객')

        first = self.make_job()
        second = self.make_job(customer=other_customer)

        self.assertNotEqual(first.id, second.id)

    def test_same_hash_different_portfolio_creates_independent_jobs(self):
        first = self.make_job()
        second = self.make_job(portfolio_type=2)

        self.assertNotEqual(first.id, second.id)

    def test_same_hash_is_allowed_after_previous_job_becomes_inactive(self):
        first = self.make_job()
        first.status = 'confirmed'
        first.save(update_fields=['status'])

        second = self.make_job()

        self.assertNotEqual(first.id, second.id)

    def test_same_lineage_cannot_have_two_confirmed_jobs(self):
        self.make_job(status='confirmed')

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.make_job(status='confirmed')

    def test_result_is_unique_per_job_and_provider(self):
        job = self.make_job()
        InsuranceExtractionResult.objects.create(job=job, provider='claude')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                InsuranceExtractionResult.objects.create(
                    job=job, provider='claude')

    def test_idempotency_key_cannot_be_reused_with_different_request_hash(self):
        job = self.make_job()
        InsuranceImportCommand.objects.create(
            job=job, operation='patch', idempotency_key=self.command_key,
            request_sha256='a' * 64)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                InsuranceImportCommand.objects.create(
                    job=job, operation='patch',
                    idempotency_key=self.command_key,
                    request_sha256='b' * 64)

    def test_manual_command_rejects_duplicate_unique_tuple(self):
        insurance = CustomerInsurance.objects.create(
            customer=self.customer, portfolio_type=1)
        ManualInsuranceCommand.objects.create(
            insurance=insurance, operation='confirm',
            idempotency_key=self.command_key, request_sha256='a' * 64)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ManualInsuranceCommand.objects.create(
                    insurance=insurance, operation='confirm',
                    idempotency_key=self.command_key,
                    request_sha256='a' * 64)

    def test_legacy_rows_are_not_claimed_as_confirmed(self):
        insurance = CustomerInsurance.objects.create(
            customer=self.customer, portfolio_type=1)
        self.assertEqual(
            insurance.review_status, 'legacy_review_required')
        self.assertFalse(insurance.analysis_included)

    def test_create_idempotency_key_is_unique_per_owner_only_when_present(self):
        key = uuid.uuid4()
        self.make_job(create_idempotency_key=key)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.make_job(
                    file_sha256='a' * 64,
                    create_idempotency_key=key,
                )
        other_job = self.make_job(
            owner=self.other_owner,
            customer=self.other_customer,
            create_idempotency_key=key,
        )
        self.assertEqual(other_job.create_idempotency_key, key)

    def test_create_request_key_is_unique_per_owner_with_fixed_response(self):
        key = uuid.uuid4()
        first = InsuranceImportCreateRequest.objects.create(
            owner=self.owner,
            idempotency_key=key,
            request_sha256='a' * 64,
            response_status=202,
            response_body={'job_id': str(uuid.uuid4()), 'status': 'queued'},
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                InsuranceImportCreateRequest.objects.create(
                    owner=self.owner,
                    idempotency_key=key,
                    request_sha256='b' * 64,
                )

        other_owner_request = InsuranceImportCreateRequest.objects.create(
            owner=self.other_owner,
            idempotency_key=key,
            request_sha256='b' * 64,
        )
        self.assertEqual(first.response_status, 202)
        self.assertNotEqual(first.owner_id, other_owner_request.owner_id)


class CustomerInsuranceDetailMappingTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email='mapping@example.com', password='inpaPass123!')
        self.customer = Customer.objects.create(owner=self.owner, name='매핑 고객')
        self.insurance = CustomerInsurance.objects.create(
            customer=self.customer, portfolio_type=1)

        category = InsuranceCategory.objects.create(name='진단비')
        sub_category = InsuranceSubCategory.objects.create(
            category=category, name='암')
        self.detail = InsuranceDetail.objects.create(
            sub_category=sub_category, name='일반암')

        analysis_category = AnalysisCategory.objects.create(name='진단비')
        analysis_sub_category = AnalysisSubCategory.objects.create(
            category=analysis_category, name='암')
        self.global_detail = AnalysisDetail.objects.create(
            sub_category=analysis_sub_category, name='일반암')
        self.override_detail = AnalysisDetail.objects.create(
            sub_category=analysis_sub_category, name='소액암')
        self.detail.analysis_detail.add(self.global_detail)

    def test_global_mapping_uses_catalog_mapping(self):
        case = CustomerInsuranceDetail.objects.create(
            insurance=self.insurance, detail=self.detail,
            mapping_source='global')
        case.analysis_detail_override.add(self.override_detail)

        self.assertQuerySetEqual(
            case.effective_analysis_details(),
            [self.global_detail],
            transform=lambda item: item,
        )

    def test_planner_override_and_manual_use_case_mapping(self):
        for mapping_source in ('planner_override', 'manual'):
            with self.subTest(mapping_source=mapping_source):
                case = CustomerInsuranceDetail.objects.create(
                    insurance=self.insurance, detail=self.detail,
                    mapping_source=mapping_source)
                case.analysis_detail_override.add(self.override_detail)

                self.assertQuerySetEqual(
                    case.effective_analysis_details(),
                    [self.override_detail],
                    transform=lambda item: item,
                )


class InsuranceImportRuntimeConfigTests(TestCase):
    def test_first_row_defaults_to_pk_one(self):
        config = InsuranceImportRuntimeConfig.objects.create()

        self.assertEqual(config.pk, 1)

    def test_database_rejects_second_singleton_row(self):
        InsuranceImportRuntimeConfig.objects.create()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                InsuranceImportRuntimeConfig.objects.create(pk=2)

    def test_full_clean_rejects_invalid_limits_relationship_and_codes(self):
        invalid_values = (
            {'per_owner_concurrency': True},
            {'per_owner_concurrency': 0},
            {'global_concurrency': 101},
            {'per_owner_concurrency': 5, 'global_concurrency': 4},
            {'force_manual_carrier_codes': '0'},
            {'force_manual_carrier_codes': [True]},
            {'force_manual_carrier_codes': [9999]},
            {'force_manual_carrier_codes': [1, 0, 1]},
        )

        for values in invalid_values:
            with self.subTest(values=values):
                fields = {
                    'pk': 1,
                    'per_owner_concurrency': 2,
                    'global_concurrency': 4,
                    'force_manual_carrier_codes': [],
                }
                fields.update(values)
                config = InsuranceImportRuntimeConfig(**fields)
                with self.assertRaises(ValidationError):
                    config.clean()

    def test_full_clean_accepts_canonical_runtime_config(self):
        config = InsuranceImportRuntimeConfig(
            pk=1,
            per_owner_concurrency=3,
            global_concurrency=6,
            force_manual_carrier_codes=[0, 1],
        )

        config.clean()

    @override_settings(
        INSURANCE_IMPORT_PER_OWNER_LIMIT=3,
        INSURANCE_IMPORT_GLOBAL_LIMIT=11,
    )
    def test_solo_uses_safe_settings_defaults_only_on_create(self):
        config = InsuranceImportRuntimeConfig.solo()
        self.assertEqual(config.pk, 1)
        self.assertEqual(config.per_owner_concurrency, 3)
        self.assertEqual(config.global_concurrency, 11)
        self.assertEqual(config.force_manual_carrier_codes, [])

        config.per_owner_concurrency = 7
        config.global_concurrency = 19
        config.force_manual_carrier_codes = [2]
        config.save()

        with self.settings(
                INSURANCE_IMPORT_PER_OWNER_LIMIT=4,
                INSURANCE_IMPORT_GLOBAL_LIMIT=20):
            preserved = InsuranceImportRuntimeConfig.solo()

        self.assertEqual(preserved.per_owner_concurrency, 7)
        self.assertEqual(preserved.global_concurrency, 19)
        self.assertEqual(preserved.force_manual_carrier_codes, [2])


class InsuranceImportAdminPermissionTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            email='admin@example.com', password='inpaPass123!')
        self.request = RequestFactory().get('/admin/insurances/')
        self.request.user = self.superuser

    def test_system_record_admins_deny_add_change_delete_and_bulk_delete(self):
        admin_classes = (
            (InsuranceExtractionJobAdmin, InsuranceExtractionJob),
            (InsuranceExtractionResultAdmin, InsuranceExtractionResult),
            (InsuranceImportCommandAdmin, InsuranceImportCommand),
            (InsuranceImportCreateRequestAdmin,
             InsuranceImportCreateRequest),
        )

        for admin_class, model in admin_classes:
            with self.subTest(model=model.__name__):
                model_admin = admin_class(model, django_admin.site)
                self.assertFalse(model_admin.has_add_permission(self.request))
                self.assertFalse(model_admin.has_change_permission(self.request))
                self.assertFalse(model_admin.has_delete_permission(self.request))
                self.assertNotIn('delete_selected', model_admin.get_actions(self.request))

    def test_manual_command_admin_is_registered_read_only(self):
        self.assertIn(ManualInsuranceCommand, django_admin.site._registry)
        model_admin = django_admin.site._registry[ManualInsuranceCommand]

        self.assertFalse(model_admin.has_add_permission(self.request))
        self.assertFalse(model_admin.has_change_permission(self.request))
        self.assertFalse(model_admin.has_delete_permission(self.request))
        self.assertNotIn('delete_selected', model_admin.get_actions(self.request))

    def test_manual_command_admin_hides_replay_secrets(self):
        model_admin = django_admin.site._registry[ManualInsuranceCommand]
        hidden_fields = {
            'idempotency_key', 'request_sha256', 'response_body',
        }

        self.assertTrue(hidden_fields.isdisjoint(model_admin.list_display))
        self.assertTrue(hidden_fields.issubset(set(model_admin.exclude)))
        form = model_admin.get_form(self.request)
        self.assertTrue(hidden_fields.isdisjoint(form.base_fields))

    def test_extraction_job_admin_hides_uploaded_display_name(self):
        model_admin = django_admin.site._registry[InsuranceExtractionJob]

        self.assertNotIn('safe_display_name', model_admin.list_display)
        self.assertIn('safe_display_name', model_admin.exclude)
        form = model_admin.get_form(self.request)
        self.assertNotIn('safe_display_name', form.base_fields)

    def test_runtime_config_admin_cannot_add_when_any_row_exists(self):
        model_admin = InsuranceImportRuntimeConfigAdmin(
            InsuranceImportRuntimeConfig, django_admin.site)
        self.assertTrue(model_admin.has_add_permission(self.request))
        InsuranceImportRuntimeConfig.objects.create()

        self.assertFalse(model_admin.has_add_permission(self.request))
