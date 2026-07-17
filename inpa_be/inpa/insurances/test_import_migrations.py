import uuid

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class DuplicateResolutionRollbackMigrationTests(TransactionTestCase):
    migrate_from = [(
        'insurances', '0010_insuranceimportcreaterequest_resolution_job')]
    migrate_to = [(
        'insurances', '0011_alter_insuranceimportcreaterequest_resolution_job')]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        User = old_apps.get_model('accounts', 'User')
        Customer = old_apps.get_model('customers', 'Customer')
        Job = old_apps.get_model('insurances', 'InsuranceExtractionJob')
        Request = old_apps.get_model(
            'insurances', 'InsuranceImportCreateRequest')

        owner = User.objects.create(
            email='resolution-rollback@test.com', password='!')
        customer = Customer.objects.create(owner_id=owner.pk, name='고객')

        def make_job(marker):
            return Job.objects.create(
                owner_id=owner.pk,
                customer_id=customer.pk,
                intent='add',
                portfolio_type=1,
                status='failed',
                file_sha256=marker * 64,
                file_size=10,
                safe_display_name=f'{marker}.pdf',
            )

        shared_job = make_job('a')
        untouched_job = make_job('b')
        primary = Request.objects.create(
            owner_id=owner.pk,
            resolution_job_id=shared_job.pk,
            idempotency_key=uuid.uuid4(),
            request_sha256='1' * 64,
            response_status=409,
            response_body={'duplicate_resolution_token': 'oldest-token'},
        )
        secondary = Request.objects.create(
            owner_id=owner.pk,
            idempotency_key=uuid.uuid4(),
            request_sha256='2' * 64,
            response_status=409,
            response_body={'duplicate_resolution_token': 'secondary-token'},
        )
        untouched = Request.objects.create(
            owner_id=owner.pk,
            resolution_job_id=untouched_job.pk,
            idempotency_key=uuid.uuid4(),
            request_sha256='3' * 64,
            response_status=202,
            response_body={'marker': 'untouched'},
        )
        self.shared_job_id = shared_job.pk
        self.primary_id = primary.pk
        self.secondary_id = secondary.pk
        self.untouched_id = untouched.pk
        self.untouched_job_id = untouched_job.pk

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        new_apps = executor.loader.project_state(self.migrate_to).apps
        NewRequest = new_apps.get_model(
            'insurances', 'InsuranceImportCreateRequest')
        NewRequest.objects.filter(pk=self.secondary_id).update(
            resolution_job_id=self.shared_job_id)

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        super().tearDown()

    def test_reverse_deduplicates_only_unrepresentable_resolution_ledgers(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        OldRequest = old_apps.get_model(
            'insurances', 'InsuranceImportCreateRequest')
        OldJob = old_apps.get_model('insurances', 'InsuranceExtractionJob')

        survivors = OldRequest.objects.filter(
            resolution_job_id=self.shared_job_id)
        self.assertEqual(list(survivors.values_list('pk', flat=True)), [
            self.primary_id,
        ])
        self.assertFalse(OldRequest.objects.filter(
            pk=self.secondary_id).exists())
        untouched = OldRequest.objects.get(pk=self.untouched_id)
        self.assertEqual(untouched.resolution_job_id, self.untouched_job_id)
        self.assertEqual(untouched.response_body, {'marker': 'untouched'})
        self.assertEqual(OldJob.objects.filter(pk__in=(
            self.shared_job_id, self.untouched_job_id,
        )).count(), 2)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OldRequest.objects.create(
                    owner_id=untouched.owner_id,
                    resolution_job_id=self.shared_job_id,
                    idempotency_key=uuid.uuid4(),
                    request_sha256='4' * 64,
                )

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        new_apps = executor.loader.project_state(self.migrate_to).apps
        NewRequest = new_apps.get_model(
            'insurances', 'InsuranceImportCreateRequest')
        self.assertEqual(NewRequest.objects.filter(
            resolution_job_id=self.shared_job_id).count(), 1)
        self.assertEqual(NewRequest.objects.get(
            pk=self.untouched_id).resolution_job_id, self.untouched_job_id)


class ConfirmedLineageSurvivorMigrationTests(TransactionTestCase):
    migrate_from = [('insurances', '0012_manualinsurancecommand')]
    migrate_to = [('insurances', '0013_confirmed_import_lineage_unique')]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        User = old_apps.get_model('accounts', 'User')
        Customer = old_apps.get_model('customers', 'Customer')
        Job = old_apps.get_model('insurances', 'InsuranceExtractionJob')
        CustomerInsurance = old_apps.get_model(
            'insurances', 'CustomerInsurance')

        owner = User.objects.create(
            email='confirmed-lineage@test.com', password='!')
        customer = Customer.objects.create(owner_id=owner.pk, name='고객')
        lineage = {
            'owner_id': owner.pk,
            'customer_id': customer.pk,
            'intent': 'add',
            'portfolio_type': 1,
            'status': 'confirmed',
            'file_sha256': 'a' * 64,
            'file_size': 10,
        }
        older_valid = Job.objects.create(
            **lineage, safe_display_name='older-valid.pdf')
        newer_orphan = Job.objects.create(
            **lineage, safe_display_name='newer-orphan.pdf')
        now = timezone.now()
        Job.objects.filter(pk=older_valid.pk).update(
            confirmed_at=now - timezone.timedelta(hours=1),
            created_at=now - timezone.timedelta(hours=2),
        )
        Job.objects.filter(pk=newer_orphan.pk).update(
            confirmed_at=now,
            created_at=now - timezone.timedelta(minutes=1),
        )
        insurance = CustomerInsurance.objects.create(
            customer_id=customer.pk,
            name='유효 확정 보험',
            portfolio_type=1,
            review_status='confirmed',
            analysis_included=True,
            source_job_id=older_valid.pk,
        )
        self.older_valid_id = older_valid.pk
        self.newer_orphan_id = newer_orphan.pk
        self.insurance_id = insurance.pk

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        super().tearDown()

    def test_valid_confirmed_insurance_survives_newer_orphan_job(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        new_apps = executor.loader.project_state(self.migrate_to).apps
        Job = new_apps.get_model('insurances', 'InsuranceExtractionJob')
        CustomerInsurance = new_apps.get_model(
            'insurances', 'CustomerInsurance')

        self.assertEqual(
            Job.objects.get(pk=self.older_valid_id).status,
            'confirmed',
        )
        self.assertEqual(
            Job.objects.get(pk=self.newer_orphan_id).status,
            'superseded',
        )
        insurance = CustomerInsurance.objects.get(pk=self.insurance_id)
        self.assertEqual(insurance.review_status, 'confirmed')
        self.assertTrue(insurance.analysis_included)
