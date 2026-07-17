import uuid

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class ShareSnapshotTokenAuthorityMigrationTests(TransactionTestCase):
    migrate_from = [('analytics', '0003_alter_northstarevent_event_type')]
    migrate_to = [('analytics', '0004_share_snapshot_token_authority')]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        User = old_apps.get_model('accounts', 'User')
        Customer = old_apps.get_model('customers', 'Customer')
        ShareSnapshot = old_apps.get_model('analytics', 'ShareSnapshot')

        owner = User.objects.create(email='migration-owner@test.com', password='!')
        customer = Customer.objects.create(owner_id=owner.pk, name='이전고객')
        self.owner_id = owner.pk
        self.customer_id = customer.pk
        self.token = uuid.uuid4()
        retention = timezone.now() + timezone.timedelta(days=180)
        older = ShareSnapshot.objects.create(
            owner_id=owner.pk, customer_id=customer.pk,
            share_token=self.token, payload={'version': 'older'},
            retention_expires_at=retention)
        newer = ShareSnapshot.objects.create(
            owner_id=owner.pk, customer_id=customer.pk,
            share_token=self.token, payload={'version': 'newer'},
            retention_expires_at=retention)
        ShareSnapshot.objects.filter(pk=older.pk).update(
            captured_at=timezone.now() - timezone.timedelta(days=2))
        ShareSnapshot.objects.filter(pk=newer.pk).update(
            captured_at=timezone.now() - timezone.timedelta(days=1))
        self.older_id = older.pk
        self.newer_id = newer.pk

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        self.apps = executor.loader.project_state(self.migrate_to).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        super().tearDown()

    def test_latest_duplicate_survives_unique_constraint_and_reverse_is_safe(self):
        ShareSnapshot = self.apps.get_model('analytics', 'ShareSnapshot')
        older = ShareSnapshot.objects.get(pk=self.older_id)
        newer = ShareSnapshot.objects.get(pk=self.newer_id)
        self.assertIsNone(older.share_token)
        self.assertEqual(newer.share_token, self.token)
        self.assertEqual(older.payload_version, 'v1-legacy-actions')
        self.assertEqual(newer.payload_version, 'v1-legacy-actions')

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ShareSnapshot.objects.create(
                    owner_id=self.owner_id,
                    customer_id=self.customer_id,
                    share_token=self.token,
                    retention_expires_at=(
                        timezone.now() + timezone.timedelta(days=180)),
                )
        for marker in ('null-one', 'null-two'):
            ShareSnapshot.objects.create(
                owner_id=self.owner_id,
                customer_id=self.customer_id,
                share_token=None,
                payload={'marker': marker},
                retention_expires_at=(
                    timezone.now() + timezone.timedelta(days=180)),
            )

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        OldShareSnapshot = old_apps.get_model('analytics', 'ShareSnapshot')
        self.assertEqual(OldShareSnapshot.objects.filter(
            pk__in=(self.older_id, self.newer_id)).count(), 2)
        OldShareSnapshot.objects.filter(pk=self.older_id).update(
            share_token=self.token)
        self.assertEqual(OldShareSnapshot.objects.filter(
            share_token=self.token).count(), 2)
