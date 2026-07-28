import uuid
from datetime import datetime

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class RecordingNoticeRetentionMigrationTests(TransactionTestCase):
    migrate_from = [('consultations', '0006_consultationruntimeconfig_cost_limits')]
    migrate_to = [('consultations', '0007_recording_notice_retention')]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        User = old_apps.get_model('accounts', 'User')
        Customer = old_apps.get_model('customers', 'Customer')
        Recording = old_apps.get_model(
            'consultations',
            'ConsultationRecording',
        )

        owner = User.objects.create(
            email='recording-retention-migration@test.com',
            password='!',
        )
        customer = Customer.objects.create(owner_id=owner.pk, name='이전 고객')
        self.owner_id = owner.pk
        self.customer_id = customer.pk
        self.legacy_expiry = timezone.make_aware(
            datetime(2026, 7, 29, 10, 11, 12),
        )
        legacy = Recording.objects.create(
            owner_id=owner.pk,
            customer_id=customer.pk,
            status='ready',
            storage_key=f'consultation-recordings/{uuid.uuid4()}/source',
            mime_type='audio/webm',
            uploaded_at=timezone.make_aware(
                datetime(2026, 7, 22, 10, 11, 12),
            ),
            expires_at=self.legacy_expiry,
        )
        self.legacy_id = legacy.pk

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        self.apps = executor.loader.project_state(self.migrate_to).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_legacy_expiry_is_unchanged_and_no_attestation_is_fabricated(self):
        Recording = self.apps.get_model(
            'consultations',
            'ConsultationRecording',
        )

        legacy = Recording.objects.get(pk=self.legacy_id)

        self.assertEqual(legacy.expires_at, self.legacy_expiry)
        self.assertEqual(legacy.notice_version, '')
        self.assertIsNone(legacy.notice_attested_at)
        self.assertEqual(legacy.notice_text_hash, '')
        self.assertEqual(legacy.retention_hours_snapshot, 168)
        self.assertEqual(legacy.retention_days_snapshot, 7)
        self.assertEqual(legacy.retention_policy_version, 'v1-7d')
        self.assertEqual(legacy.verified_container, '')

    def test_v2_rows_require_exact_server_notice_evidence(self):
        Recording = self.apps.get_model(
            'consultations',
            'ConsultationRecording',
        )
        values = {
            'owner_id': self.owner_id,
            'customer_id': self.customer_id,
            'status': 'ready',
            'mime_type': 'audio/webm',
            'retention_hours_snapshot': 720,
            'retention_days_snapshot': 30,
            'retention_policy_version': 'v2-30d',
        }

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Recording.objects.create(**values)

        exact_evidence = {
            'notice_version': 'consultation-notice-v2-2026-07-28',
            'notice_attested_at': timezone.now(),
            'notice_text_hash': (
                'f316dff62e8c9628babccbcfb8d2ae1ddfc9a1572e72f58a'
                'c087d83fc45ec432'
            ),
        }
        for hours, days in ((1, 1), (25, 2), (719, 30), (720, 29)):
            with self.subTest(hours=hours, days=days):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        Recording.objects.create(
                            **{
                                **values,
                                'retention_hours_snapshot': hours,
                                'retention_days_snapshot': days,
                            },
                            **exact_evidence,
                        )

        current = Recording.objects.create(
            **values,
            **exact_evidence,
        )
        self.assertEqual(current.retention_policy_version, 'v2-30d')
