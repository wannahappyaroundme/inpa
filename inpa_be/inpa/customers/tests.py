"""고객 도메인 핵심 게이트 테스트.

★ 필수 2종:
  1) owner 격리 — 설계사 A가 B의 고객을 조회·수정·삭제할 수 없다.
  2) 병력 동의 게이트 — consent_overseas_at 없으면 병력 등록 412 차단, 동의 후 201.
+ 하위 라우트 owner 격리, ConsentLog append-only, 동의 생성 시 스냅샷 동기화 보강.
"""
import datetime
import importlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from unittest import mock, skipUnless

from django.core.management import call_command
from django.core.management.base import CommandError
from django.core import signing
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import (
    IntegrityError, OperationalError, close_old_connections, connection,
    transaction,
)
from django.db.migrations.executor import MigrationExecutor
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from rest_framework.test import APIClient
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext

from inpa.accounts.models import Profile, User
from inpa.analysis.models import AnalysisCategory, AnalysisDetail, AnalysisSubCategory
from inpa.billing.models import Plan, Subscription, UsageMeter
from inpa.insurances.models import CustomerInsurance

from .consent_texts import (
    CONSENT_TEXTS_VERSION,
    CONSULTATION_CONSENT_VERSIONS,
    has_current_consultation_recording_consent,
    has_current_overseas_consent,
)
from .models import (
    ConsentLog, Customer, CustomerMedicalHistory, CustomerMemo, CustomerTag, JobRiskCode,
    PlannerBaseline, PlannerBaselineRevision, compute_insurance_age,
)
from .presets import PRESET_ORIGIN_V0, PRESET_V0, iter_preset_rows
from .serializers import CustomerListSerializer, CustomerSerializer
from .tokens import make_consent_token, read_consent_token


POSTGRES_ONLY = skipUnless(
    connection.vendor == 'postgresql',
    'PostgreSQL row-lock and partial-unique test',
)


class ComputeInsuranceAgeTests(SimpleTestCase):
    def test_calendar_boundaries_match_insurance_age_rule(self):
        cases = (
            ('2000-01-31', datetime.date(2026, 7, 30), 26),
            ('2000-01-31', datetime.date(2026, 7, 31), 27),
            ('2000-08-31', datetime.date(2026, 2, 27), 25),
            ('2000-08-31', datetime.date(2026, 2, 28), 26),
            ('2000-02-29', datetime.date(2025, 8, 28), 25),
            ('2000-02-29', datetime.date(2025, 8, 29), 26),
            ('2000-08-04', datetime.date(2026, 8, 4), 26),
        )
        for birth_day, as_of, expected in cases:
            with self.subTest(birth_day=birth_day, as_of=as_of):
                self.assertEqual(compute_insurance_age(birth_day, as_of), expected)

    def test_invalid_and_future_birth_dates_return_none(self):
        as_of = datetime.date(2026, 8, 4)
        for birth_day in ('', '2000-2-03', '2000-02-30', '2026-08-05', '2027-01-01'):
            with self.subTest(birth_day=birth_day):
                self.assertIsNone(compute_insurance_age(birth_day, as_of))


def _thread_database_call(callback):
    close_old_connections()
    try:
        return callback()
    finally:
        close_old_connections()


def _grant_overseas(customer, version=CONSENT_TEXTS_VERSION):
    """현재 문구 버전으로 받은 고객 본인 국외이전 동의 = Claude 게이트 통과 조건.

    version=''로 부르면 구버전 동의(재동의 필요) 상황을 재현한다.
    """
    customer.consent_overseas_at = timezone.now()
    customer.save(update_fields=['consent_overseas_at'])
    return ConsentLog.objects.create(
        customer=customer, scope=ConsentLog.SCOPE_OVERSEAS_MEDICAL,
        subject=ConsentLog.SUBJECT_CUSTOMER_SELF, doc_version=version)


def _make_planner(email):
    """이메일 인증 완료(is_active=True) + Profile 보유 설계사 + 인증된 APIClient 반환."""
    user = User.objects.create_user(email=email, password='inpaPass123!')
    user.is_active = True
    user.save(update_fields=['is_active'])
    Profile.objects.create(user=user, email_verified_at=timezone.now())
    client = APIClient()
    client.force_authenticate(user=user)
    return user, client


class CustomerMemoModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('memo-owner@example.com', password='pass1234')
        self.customer = Customer.objects.create(owner=self.user, name='메모 고객')

    def test_customer_allows_many_memos_but_only_one_legacy_row(self):
        CustomerMemo.objects.create(
            owner=self.user, customer=self.customer,
            source=CustomerMemo.SOURCE_MANUAL, body='첫 메모', occurred_at=timezone.now())
        CustomerMemo.objects.create(
            owner=self.user, customer=self.customer,
            source=CustomerMemo.SOURCE_MANUAL, body='둘째 메모', occurred_at=timezone.now())
        CustomerMemo.objects.create(
            owner=self.user, customer=self.customer,
            source=CustomerMemo.SOURCE_LEGACY, body='기존 메모')

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CustomerMemo.objects.create(
                    owner=self.user, customer=self.customer,
                    source=CustomerMemo.SOURCE_LEGACY, body='중복 기존 메모')

    def test_customer_memo_derives_owner_from_customer(self):
        other_user = User.objects.create_user('memo-other@example.com', password='pass1234')

        memo = CustomerMemo.objects.create(
            owner=other_user, customer=self.customer,
            source=CustomerMemo.SOURCE_MANUAL, body='소유자 일치')

        memo.refresh_from_db()
        self.assertEqual(memo.owner_id, self.customer.owner_id)

    def test_body_update_corrects_mismatched_in_memory_owner(self):
        other_user = User.objects.create_user('memo-other@example.com', password='pass1234')
        memo = CustomerMemo.objects.create(
            owner=self.user, customer=self.customer,
            source=CustomerMemo.SOURCE_MANUAL, body='첫 메모')
        memo.owner = other_user
        memo.body = '수정 메모'

        memo.save(update_fields=['body'])
        memo.refresh_from_db()

        self.assertEqual(memo.owner_id, self.customer.owner_id)
        self.assertEqual(memo.body, '수정 메모')

    def test_customer_update_persists_derived_owner(self):
        other_user = User.objects.create_user('memo-other@example.com', password='pass1234')
        other_customer = Customer.objects.create(owner=other_user, name='다른 고객')
        memo = CustomerMemo.objects.create(
            owner=self.user, customer=self.customer,
            source=CustomerMemo.SOURCE_MANUAL, body='첫 메모')
        memo.customer = other_customer

        memo.save(update_fields=['customer'])
        memo.refresh_from_db()

        self.assertEqual(memo.customer_id, other_customer.id)
        self.assertEqual(memo.owner_id, other_customer.owner_id)

    def test_existing_memo_empty_update_fields_is_a_noop(self):
        memo = CustomerMemo.objects.create(
            owner=self.user, customer=self.customer,
            source=CustomerMemo.SOURCE_MANUAL, body='첫 메모')
        memo.body = '저장되면 안 되는 메모'

        with self.assertNumQueries(0):
            memo.save(update_fields=[])
        memo.refresh_from_db()

        self.assertEqual(memo.body, '첫 메모')

    def test_unsaved_memo_empty_update_fields_is_a_noop(self):
        memo = CustomerMemo(
            owner=self.user, customer=self.customer,
            source=CustomerMemo.SOURCE_MANUAL, body='저장되면 안 되는 메모')

        with self.assertNumQueries(0):
            memo.save(update_fields=[])

        self.assertIsNone(memo.pk)

    def test_customer_memos_are_newest_first_with_id_tiebreaker(self):
        first = CustomerMemo.objects.create(
            owner=self.user, customer=self.customer,
            source=CustomerMemo.SOURCE_MANUAL, body='첫 메모')
        second = CustomerMemo.objects.create(
            owner=self.user, customer=self.customer,
            source=CustomerMemo.SOURCE_MANUAL, body='둘째 메모')
        CustomerMemo.objects.filter(id__in=[first.id, second.id]).update(
            created_at=timezone.now())

        self.assertEqual(
            list(self.customer.memos.values_list('id', flat=True)),
            [second.id, first.id])


class CustomerMemoCountTests(TestCase):
    """고객 목록/상세의 메모 개수는 출처와 고객 수에 관계없이 정확해야 한다."""

    def setUp(self):
        self.user, self.client = _make_planner('memo-count-owner@test.com')
        self.other_user, self.other_client = _make_planner('memo-count-other@test.com')
        self.customer = Customer.objects.create(owner=self.user, name='메모 개수 고객')
        self.empty_customer = Customer.objects.create(owner=self.user, name='빈 메모 고객')
        self.other_customer = Customer.objects.create(owner=self.other_user, name='다른 설계사 고객')
        CustomerMemo.objects.create(
            owner=self.user, customer=self.customer,
            source=CustomerMemo.SOURCE_MANUAL, body='직접 메모', occurred_at=timezone.now())
        CustomerMemo.objects.create(
            owner=self.user, customer=self.customer,
            source=CustomerMemo.SOURCE_AI_SUMMARY, body='요약 메모', occurred_at=timezone.now())
        CustomerMemo.objects.create(
            owner=self.user, customer=self.customer,
            source=CustomerMemo.SOURCE_LEGACY, body='기존 메모')
        CustomerMemo.objects.create(
            owner=self.other_user, customer=self.other_customer,
            source=CustomerMemo.SOURCE_MANUAL, body='다른 설계사 메모', occurred_at=timezone.now())

    def test_customer_detail_returns_all_memo_sources_and_hides_other_owner(self):
        response = self.client.get(f'/api/v1/customers/{self.customer.id}/')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['memo_count'], 3)
        self.assertEqual(
            self.client.get(f'/api/v1/customers/{self.other_customer.id}/').status_code,
            404,
        )

    def test_customer_list_returns_zero_and_nonzero_counts_with_owner_isolation(self):
        response = self.client.get('/api/v1/customers/')

        self.assertEqual(response.status_code, 200, response.data)
        rows = {row['id']: row for row in response.data['results']}
        self.assertEqual(rows[self.customer.id]['memo_count'], 3)
        self.assertEqual(rows[self.empty_customer.id]['memo_count'], 0)
        self.assertNotIn(self.other_customer.id, rows)

    def test_customer_list_counts_memos_without_per_customer_queries(self):
        for index in range(4):
            customer = Customer.objects.create(owner=self.user, name=f'추가 고객 {index}')
            CustomerMemo.objects.create(
                owner=self.user, customer=customer,
                source=CustomerMemo.SOURCE_MANUAL, body=f'추가 메모 {index}',
                occurred_at=timezone.now())

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get('/api/v1/customers/')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(all('memo_count' in row for row in response.data['results']))
        memo_queries = [
            query['sql'] for query in queries.captured_queries
            if 'customer_memo' in query['sql'].lower()
        ]
        self.assertLessEqual(len(memo_queries), 2, memo_queries)
        self.assertTrue(any('COUNT(DISTINCT' in query.upper() for query in memo_queries), memo_queries)

    def test_customer_serializers_fall_back_to_real_count_without_annotation(self):
        plain_customer = Customer.objects.get(pk=self.customer.pk)

        self.assertEqual(CustomerListSerializer(plain_customer).data['memo_count'], 3)
        self.assertEqual(CustomerSerializer(plain_customer).data['memo_count'], 3)

    def test_legacy_memo_bridge_returns_live_count_after_create_and_clear(self):
        created = self.client.patch(
            f'/api/v1/customers/{self.empty_customer.id}/',
            {'memo': '호환 메모 생성'}, format='json')
        self.assertEqual(created.status_code, 200, created.data)
        self.assertEqual(created.data['memo'], '호환 메모 생성')
        self.assertEqual(created.data['memo_count'], 1)

        cleared = self.client.patch(
            f'/api/v1/customers/{self.empty_customer.id}/',
            {'memo': ''}, format='json')
        self.assertEqual(cleared.status_code, 200, cleared.data)
        self.assertEqual(cleared.data['memo'], '')
        self.assertEqual(cleared.data['memo_count'], 0)


class CustomerMemoMigrationTests(TransactionTestCase):
    migrate_from = [('customers', '0015_alter_consentlog_scope')]
    migrate_to = [('customers', '0016_customermemo')]

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        executor = MigrationExecutor(connection)
        executor.migrate(cls.migrate_from)
        cls.old_apps = executor.loader.project_state(cls.migrate_from).apps

    @classmethod
    def tearDownClass(cls):
        try:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
            if CustomerMemo._meta.db_table not in connection.introspection.table_names():
                raise AssertionError('CustomerMemo schema was not restored')
        finally:
            super().tearDownClass()

    def test_migration_preserves_legacy_memos_and_is_idempotent(self):
        User = self.old_apps.get_model('accounts', 'User')
        Customer = self.old_apps.get_model('customers', 'Customer')
        owner = User.objects.create(email='migration-owner@example.com')
        padded = Customer.objects.create(
            owner_id=owner.pk, name='원문 보존', memo='  앞뒤 공백 보존  ')
        empty = Customer.objects.create(owner_id=owner.pk, name='빈 메모', memo='')
        whitespace = Customer.objects.create(owner_id=owner.pk, name='공백 메모', memo=' \n\t ')

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        new_apps = executor.loader.project_state(self.migrate_to).apps
        CustomerMemo = new_apps.get_model('customers', 'CustomerMemo')

        migrated = CustomerMemo.objects.get(customer_id=padded.pk)
        self.assertEqual(migrated.owner_id, owner.pk)
        self.assertEqual(migrated.customer_id, padded.pk)
        self.assertEqual(migrated.source, 'legacy_migrated')
        self.assertEqual(migrated.body, '  앞뒤 공백 보존  ')
        self.assertIsNone(migrated.occurred_at)
        self.assertFalse(CustomerMemo.objects.filter(customer_id=empty.pk).exists())
        self.assertFalse(CustomerMemo.objects.filter(customer_id=whitespace.pk).exists())

        migration = importlib.import_module('inpa.customers.migrations.0016_customermemo')
        migration.forwards(new_apps, None)
        self.assertEqual(CustomerMemo.objects.filter(customer_id=padded.pk).count(), 1)


class CustomerMemoMirrorMarkerMigrationTests(TransactionTestCase):
    migrate_from = [('customers', '0016_customermemo')]
    migrate_to = [('customers', '0018_customermemo_mirror_constraint')]

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        executor = MigrationExecutor(connection)
        executor.migrate(cls.migrate_from)
        cls.old_apps = executor.loader.project_state(cls.migrate_from).apps

    @classmethod
    def tearDownClass(cls):
        try:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
        finally:
            super().tearDownClass()

    def test_migration_recovers_every_rolling_deploy_mirror_without_marking_ordinary_rows(self):
        User = self.old_apps.get_model('accounts', 'User')
        Customer = self.old_apps.get_model('customers', 'Customer')
        CustomerMemo = self.old_apps.get_model('customers', 'CustomerMemo')
        owner = User.objects.create(email='marker-migration@example.com')
        legacy_customer = Customer.objects.create(
            owner_id=owner.pk, name='기존 고객', memo='기존 메모')
        manual_customer = Customer.objects.create(
            owner_id=owner.pk, name='직접 고객', memo='직접 메모')
        multi_customer = Customer.objects.create(
            owner_id=owner.pk, name='여러 메모 고객', memo='같은 직접 메모')
        missing_customer = Customer.objects.create(
            owner_id=owner.pk, name='누락 고객', memo='  누락 원문 보존  ')
        mismatch_customer = Customer.objects.create(
            owner_id=owner.pk, name='불일치 고객', memo='호환 기준')
        blank_customer = Customer.objects.create(
            owner_id=owner.pk, name='빈 고객', memo=' \n\t ')
        rolling_customer = Customer.objects.create(
            owner_id=owner.pk, name='롤링 고객', memo='')
        CustomerMemo.objects.create(
            owner_id=owner.pk, customer_id=legacy_customer.pk,
            source='legacy_migrated', body='기존 메모')
        manual = CustomerMemo.objects.create(
            owner_id=owner.pk, customer_id=manual_customer.pk,
            source='manual', body='직접 메모')
        first_matching = CustomerMemo.objects.create(
            owner_id=owner.pk, customer_id=multi_customer.pk,
            source='manual', body='같은 직접 메모')
        later_matching = CustomerMemo.objects.create(
            owner_id=owner.pk, customer_id=multi_customer.pk,
            source='manual', body='같은 직접 메모')
        mismatched = CustomerMemo.objects.create(
            owner_id=owner.pk, customer_id=mismatch_customer.pk,
            source='manual', body='일반 메모')

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        new_apps = executor.loader.project_state(self.migrate_to).apps
        MigratedMemo = new_apps.get_model('customers', 'CustomerMemo')

        self.assertTrue(MigratedMemo.objects.get(customer_id=legacy_customer.pk).is_legacy_mirror)
        self.assertTrue(MigratedMemo.objects.get(pk=manual.pk).is_legacy_mirror)
        self.assertTrue(MigratedMemo.objects.get(pk=first_matching.pk).is_legacy_mirror)
        self.assertFalse(MigratedMemo.objects.get(pk=later_matching.pk).is_legacy_mirror)

        recovered = MigratedMemo.objects.get(customer_id=missing_customer.pk)
        self.assertEqual(recovered.source, 'legacy_migrated')
        self.assertEqual(recovered.body, '  누락 원문 보존  ')
        self.assertTrue(recovered.is_legacy_mirror)
        self.assertFalse(MigratedMemo.objects.filter(customer_id=blank_customer.pk).exists())

        self.assertFalse(MigratedMemo.objects.get(pk=mismatched.pk).is_legacy_mirror)
        mismatch_mirror = MigratedMemo.objects.get(
            customer_id=mismatch_customer.pk, is_legacy_mirror=True)
        self.assertEqual(mismatch_mirror.source, 'legacy_migrated')
        self.assertEqual(mismatch_mirror.body, '호환 기준')

        migration = importlib.import_module(
            'inpa.customers.migrations.0017_customermemo_is_legacy_mirror')
        migration.mark_legacy_mirrors(new_apps, None)
        self.assertEqual(
            MigratedMemo.objects.filter(is_legacy_mirror=True).count(), 5)
        self.assertEqual(MigratedMemo.objects.filter(customer_id=missing_customer.pk).count(), 1)

        old_writer_row = CustomerMemo.objects.create(
            owner_id=owner.pk, customer_id=rolling_customer.pk,
            source='manual', body='구버전 프로세스 메모')
        self.assertFalse(
            MigratedMemo.objects.get(pk=old_writer_row.pk).is_legacy_mirror)
        self.assertIs(MigratedMemo._meta.get_field('is_legacy_mirror').db_default, False)
        if connection.vendor == 'postgresql':
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT column_default
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'customer_memo'
                      AND column_name = 'is_legacy_mirror'
                """)
                db_default = cursor.fetchone()[0]
            self.assertEqual(db_default.lower(), 'false')

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MigratedMemo.objects.create(
                    owner_id=owner.pk, customer_id=legacy_customer.pk,
                    source='manual', body='중복 호환 메모', is_legacy_mirror=True)


@skipUnless(connection.vendor == 'postgresql', 'PostgreSQL cutover test')
class CustomerMemoRollingBridgeMigrationTests(TransactionTestCase):
    migrate_from = [('customers', '0018_customermemo_mirror_constraint')]
    migrate_to = [('customers', '0019_customer_memo_rolling_bridge')]

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        executor = MigrationExecutor(connection)
        executor.migrate(cls.migrate_from)
        cls.old_apps = executor.loader.project_state(cls.migrate_from).apps

    @classmethod
    def tearDownClass(cls):
        try:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
        finally:
            super().tearDownClass()

    def test_install_reconciles_writes_that_landed_after_0017_backfill(self):
        User = self.old_apps.get_model('accounts', 'User')
        Customer = self.old_apps.get_model('customers', 'Customer')
        OldMemo = self.old_apps.get_model('customers', 'CustomerMemo')
        owner = User.objects.create(email='memo-cutover@example.com')
        missing = Customer.objects.create(
            owner_id=owner.pk, name='설치 전 누락', memo='설치 전 단일 메모')
        matching = Customer.objects.create(
            owner_id=owner.pk, name='설치 전 직접 메모', memo='설치 전 같은 메모')
        blank = Customer.objects.create(
            owner_id=owner.pk, name='설치 전 공백 메모', memo=' \n\t ')
        manual = OldMemo.objects.create(
            owner_id=owner.pk,
            customer_id=matching.pk,
            source='manual',
            body='설치 전 같은 메모',
            occurred_at=timezone.now(),
        )
        stale = OldMemo.objects.create(
            owner_id=owner.pk,
            customer_id=blank.pk,
            source='manual',
            body='지워질 이전 호환 행',
            is_legacy_mirror=True,
            occurred_at=timezone.now(),
        )

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)

        recovered = CustomerMemo.objects.get(
            customer_id=missing.pk, is_legacy_mirror=True)
        self.assertEqual(recovered.source, CustomerMemo.SOURCE_LEGACY)
        self.assertEqual(recovered.body, '설치 전 단일 메모')
        self.assertTrue(CustomerMemo.objects.get(pk=manual.pk).is_legacy_mirror)
        self.assertEqual(CustomerMemo.objects.filter(customer_id=matching.pk).count(), 1)
        self.assertFalse(CustomerMemo.objects.filter(pk=stale.pk).exists())

        output = StringIO()
        call_command('audit_customer_memos', stdout=output)
        result = json.loads(output.getvalue())
        self.assertEqual(result['missing_count'], 0)
        self.assertEqual(result['mismatched_count'], 0)
        self.assertEqual(result['duplicate_count'], 0)
        self.assertEqual(result['owner_mismatch_count'], 0)


@skipUnless(connection.vendor == 'postgresql', 'PostgreSQL deferred trigger test')
class CustomerMemoRollingBridgeTriggerTests(TransactionTestCase):
    """구버전 쓰기가 0017 이관 뒤 도착해도 커밋 시 호환 행을 복구한다."""

    def setUp(self):
        self.user = User.objects.create_user(
            'memo-rolling-trigger@example.com', password='pass1234')
        executor = MigrationExecutor(connection)
        old_apps = executor.loader.project_state(
            [('customers', '0016_customermemo')]).apps
        self.OldCustomer = old_apps.get_model('customers', 'Customer')
        self.OldCustomerMemo = old_apps.get_model('customers', 'CustomerMemo')

    def test_customer_only_old_writer_create_update_and_clear_stay_in_sync(self):
        with transaction.atomic():
            customer = self.OldCustomer.objects.create(
                owner_id=self.user.pk, name='구버전 단일 필드', memo='처음 메모')

        mirror = CustomerMemo.objects.get(
            customer_id=customer.pk, is_legacy_mirror=True)
        self.assertEqual(mirror.source, CustomerMemo.SOURCE_LEGACY)
        self.assertEqual(mirror.body, '처음 메모')
        self.assertEqual(mirror.owner_id, self.user.pk)
        self.assertEqual(mirror.revision, 1)

        other_owner = User.objects.create(email='memo-rolling-other@example.com')
        CustomerMemo.objects.filter(pk=mirror.pk).update(owner=other_owner)
        with transaction.atomic():
            self.OldCustomer.objects.filter(pk=customer.pk).update(memo='수정 메모')

        mirror.refresh_from_db()
        self.assertEqual(mirror.body, '수정 메모')
        self.assertEqual(mirror.owner_id, self.user.pk)
        self.assertEqual(mirror.revision, 2)
        self.assertIsNotNone(mirror.edited_at)

        with transaction.atomic():
            self.OldCustomer.objects.filter(pk=customer.pk).update(memo='잠시 메모')
            self.OldCustomer.objects.filter(pk=customer.pk).update(memo=' \n\t ')

        self.assertFalse(CustomerMemo.objects.filter(
            customer_id=customer.pk, is_legacy_mirror=True).exists())

        with transaction.atomic():
            unicode_blank = self.OldCustomer.objects.create(
                owner_id=self.user.pk, name='유니코드 공백', memo='\u00a0\u3000')
        self.assertFalse(CustomerMemo.objects.filter(
            customer_id=unicode_blank.pk, is_legacy_mirror=True).exists())

    def test_d008_writer_marks_matching_manual_and_leaves_later_manual_unmarked(self):
        with transaction.atomic():
            customer = self.OldCustomer.objects.create(
                owner_id=self.user.pk,
                name='구버전 복수 메모',
                memo='\u00a0같은 트랜잭션 메모\u3000',
            )
            matching = self.OldCustomerMemo.objects.create(
                owner_id=self.user.pk,
                customer_id=customer.pk,
                source=CustomerMemo.SOURCE_MANUAL,
                body='같은 트랜잭션 메모',
                occurred_at=timezone.now(),
            )

        marked = CustomerMemo.objects.get(pk=matching.pk)
        self.assertTrue(marked.is_legacy_mirror)
        self.assertEqual(marked.body, '\u00a0같은 트랜잭션 메모\u3000')
        self.assertEqual(marked.revision, 2)
        self.assertEqual(CustomerMemo.objects.filter(customer_id=customer.pk).count(), 1)

        ordinary = self.OldCustomerMemo.objects.create(
            owner_id=self.user.pk,
            customer_id=customer.pk,
            source=CustomerMemo.SOURCE_MANUAL,
            body='추가 일반 메모',
            occurred_at=timezone.now(),
        )
        self.assertFalse(CustomerMemo.objects.get(pk=ordinary.pk).is_legacy_mirror)
        self.assertEqual(CustomerMemo.objects.filter(
            customer_id=customer.pk, is_legacy_mirror=True).count(), 1)

        output = StringIO()
        call_command('audit_customer_memos', stdout=output)
        result = json.loads(output.getvalue())
        self.assertEqual(result['missing_count'], 0)
        self.assertEqual(result['mismatched_count'], 0)
        self.assertEqual(result['duplicate_count'], 0)
        self.assertEqual(result['owner_mismatch_count'], 0)

    def test_blank_insert_then_multiple_updates_preserve_matching_manual_identity(self):
        with transaction.atomic():
            customer = self.OldCustomer.objects.create(
                owner_id=self.user.pk, name='여러 번 수정', memo='')
            self.OldCustomer.objects.filter(pk=customer.pk).update(memo='중간 메모')
            self.OldCustomer.objects.filter(pk=customer.pk).update(memo='최종 메모')
            matching = self.OldCustomerMemo.objects.create(
                owner_id=self.user.pk,
                customer_id=customer.pk,
                source=CustomerMemo.SOURCE_MANUAL,
                body='최종 메모',
                occurred_at=timezone.now(),
            )

        marked = CustomerMemo.objects.get(pk=matching.pk)
        self.assertTrue(marked.is_legacy_mirror)
        self.assertEqual(marked.source, CustomerMemo.SOURCE_MANUAL)
        self.assertEqual(marked.body, '최종 메모')
        self.assertEqual(marked.revision, 1)
        self.assertEqual(CustomerMemo.objects.filter(customer_id=customer.pk).count(), 1)

    def test_deferred_event_is_noop_when_customer_was_deleted(self):
        customer = self.OldCustomer.objects.create(
            owner_id=self.user.pk, name='커밋 전 삭제', memo='')

        with transaction.atomic():
            self.OldCustomer.objects.filter(pk=customer.pk).update(memo='삭제 전 메모')
            self.OldCustomer.objects.filter(pk=customer.pk).delete()

        self.assertFalse(Customer.objects.filter(pk=customer.pk).exists())
        self.assertFalse(CustomerMemo.objects.filter(customer_id=customer.pk).exists())

    def test_serializer_create_preserves_manual_source(self):
        serializer = CustomerSerializer(data={
            'name': '실제 신규 등록',
            'memo': '직접 작성 원문',
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)

        customer = serializer.save(owner=self.user)

        memo = CustomerMemo.objects.get(customer=customer)
        self.assertTrue(memo.is_legacy_mirror)
        self.assertEqual(memo.source, CustomerMemo.SOURCE_MANUAL)
        self.assertEqual(memo.body, '직접 작성 원문')
        self.assertIsNotNone(memo.occurred_at)
        self.assertEqual(memo.revision, 1)

    def test_current_service_and_deferred_bridge_do_not_create_duplicates(self):
        from inpa.customers.memos import sync_legacy_memo

        with transaction.atomic():
            customer = Customer.objects.create(owner=self.user, name='신규 서비스 고객')
            memo, result = sync_legacy_memo(
                customer=customer,
                owner=self.user,
                body='신규 서비스 메모',
                source=CustomerMemo.SOURCE_MANUAL,
            )
            original_memo_id = memo.pk

        self.assertEqual(result, 'created')
        memo = CustomerMemo.objects.get(pk=original_memo_id)
        self.assertTrue(memo.is_legacy_mirror)
        self.assertEqual(memo.source, CustomerMemo.SOURCE_MANUAL)
        self.assertEqual(CustomerMemo.objects.filter(customer=customer).count(), 1)

        memo, result = sync_legacy_memo(
            customer=customer,
            owner=self.user,
            body='신규 서비스 수정',
            source=CustomerMemo.SOURCE_LEGACY,
        )

        self.assertEqual(result, 'edited')
        self.assertEqual(CustomerMemo.objects.filter(customer=customer).count(), 1)
        memo.refresh_from_db()
        self.assertEqual(memo.body, '신규 서비스 수정')
        self.assertEqual(memo.revision, 2)


class OwnerIsolationTests(TestCase):
    """★ 멀티테넌시 격리 — 설계사 A는 B의 데이터에 절대 접근 불가."""

    def setUp(self):
        self.user_a, self.client_a = _make_planner('a@test.com')
        self.user_b, self.client_b = _make_planner('b@test.com')
        # B 소유 고객
        self.cust_b = Customer.objects.create(owner=self.user_b, name='B의고객',
                                              mobile_phone_number='010-1111-2222')

    def test_a_cannot_list_b_customer(self):
        """A의 목록에 B의 고객이 보이지 않는다."""
        r = self.client_a.get('/api/v1/customers/')
        self.assertEqual(r.status_code, 200)
        ids = [c['id'] for c in r.json()['results']]
        self.assertNotIn(self.cust_b.id, ids)

    def test_a_cannot_retrieve_b_customer(self):
        """A가 B의 고객 상세를 직접 조회하면 404(존재 자체를 숨김)."""
        r = self.client_a.get(f'/api/v1/customers/{self.cust_b.id}/')
        self.assertEqual(r.status_code, 404)

    def test_a_cannot_update_b_customer(self):
        r = self.client_a.patch(f'/api/v1/customers/{self.cust_b.id}/',
                                {'name': '탈취시도'}, format='json')
        self.assertEqual(r.status_code, 404)
        self.cust_b.refresh_from_db()
        self.assertEqual(self.cust_b.name, 'B의고객')

    def test_a_cannot_delete_b_customer(self):
        r = self.client_a.delete(f'/api/v1/customers/{self.cust_b.id}/')
        self.assertEqual(r.status_code, 404)
        self.assertTrue(Customer.objects.filter(id=self.cust_b.id).exists())

    def test_create_injects_owner(self):
        """생성 시 owner는 클라이언트 입력이 아니라 request.user로 주입된다."""
        r = self.client_a.post('/api/v1/customers/',
                               {'name': 'A의고객', 'mobile_phone_number': '010-3333-4444'},
                               format='json')
        self.assertEqual(r.status_code, 201)
        cust = Customer.objects.get(id=r.json()['id'])
        self.assertEqual(cust.owner_id, self.user_a.id)

    def test_a_cannot_access_b_family_subroute(self):
        """하위 라우트(가족)도 부모 고객 owner 격리 — A가 B 고객의 가족 라우트 접근 시 404."""
        r = self.client_a.get(f'/api/v1/customers/{self.cust_b.id}/family/')
        self.assertEqual(r.status_code, 404)

    def test_a_cannot_attach_b_tag(self):
        """A가 B의 태그를 본인 고객에 붙이려 하면 검증 거부(400)."""
        tag_b = CustomerTag.objects.create(owner=self.user_b, label='B태그')
        r = self.client_a.post('/api/v1/customers/',
                               {'name': 'A고객', 'tag_ids': [tag_b.id]}, format='json')
        self.assertEqual(r.status_code, 400)


@override_settings(ANALYZE_MEDICAL_ENABLED=True)
class MedicalConsentGateTests(TestCase):
    """★ 병력 동의 게이트 — consent_overseas_at 없으면 병력 등록 412 차단.

    (베타 게이트 ANALYZE_MEDICAL_ENABLED는 True로 켜고 동의게이트 자체를 검증.)
    """

    def setUp(self):
        self.user, self.client = _make_planner('planner@test.com')
        self.customer = Customer.objects.create(owner=self.user, name='홍길동',
                                                mobile_phone_number='010-0000-0000')

    def _post_medical(self):
        return self.client.post(
            f'/api/v1/customers/{self.customer.id}/medical/',
            {'disease_name': '고혈압', 'is_inpatient': False}, format='json')

    def test_medical_blocked_without_consent(self):
        """미동의(consent_overseas_at=null) → 412 + CONSENT_OVERSEAS_REQUIRED."""
        self.assertIsNone(self.customer.consent_overseas_at)
        r = self._post_medical()
        self.assertEqual(r.status_code, 412)
        self.assertEqual(r.json()['code'], 'CONSENT_OVERSEAS_REQUIRED')
        self.assertEqual(r.json()['reason'], 'missing')
        self.assertEqual(CustomerMedicalHistory.objects.count(), 0)

    def test_medical_allowed_after_consent(self):
        """현재 버전 고객 본인 동의 후 → 201 등록 성공."""
        _grant_overseas(self.customer)
        r = self._post_medical()
        self.assertEqual(r.status_code, 201)
        self.assertEqual(CustomerMedicalHistory.objects.count(), 1)

    def test_medical_old_version_consent_requires_reconsent(self):
        """구버전 문구로 받은 동의만 있으면 재동의 필요 → 412 reason=reconsent."""
        _grant_overseas(self.customer, version='')
        r = self._post_medical()
        self.assertEqual(r.status_code, 412)
        self.assertEqual(r.json()['code'], 'CONSENT_OVERSEAS_REQUIRED')
        self.assertEqual(r.json()['reason'], 'reconsent')
        self.assertEqual(CustomerMedicalHistory.objects.count(), 0)

    def test_planner_consent_does_not_unlock_gate(self):
        """★ P3c 카나리아: 설계사 동의 기록은 planner_attested(대리)로 남고 국외이전 게이트를
        열지 못한다. consent_overseas_at은 여전히 None, 병력 게이트도 412 유지."""
        r = self.client.post(
            f'/api/v1/customers/{self.customer.id}/consents/',
            {'scope': ConsentLog.SCOPE_OVERSEAS_MEDICAL, 'doc_version': 'OVERSEAS-v1.0'},
            format='json')
        self.assertEqual(r.status_code, 201)
        log = ConsentLog.objects.get(id=r.json()['id'])
        self.assertEqual(log.subject, ConsentLog.SUBJECT_PLANNER_ATTESTED)
        self.customer.refresh_from_db()
        self.assertIsNone(self.customer.consent_overseas_at)  # 게이트 안 열림
        r2 = self._post_medical()
        self.assertEqual(r2.status_code, 412)
        self.assertEqual(r2.json()['code'], 'CONSENT_OVERSEAS_REQUIRED')

    def test_planner_attested_stamps_current_version(self):
        """설계사 대리 동의도 현재 문구 버전으로 스탬프된다(서버 강제)."""
        r = self.client.post(
            f'/api/v1/customers/{self.customer.id}/consents/',
            {'scope': ConsentLog.SCOPE_MARKETING, 'doc_version': 'legacy-v1'},
            format='json')
        self.assertEqual(r.status_code, 201)
        log = ConsentLog.objects.get(id=r.json()['id'])
        self.assertEqual(log.doc_version, CONSENT_TEXTS_VERSION)

    def test_planner_cannot_forge_customer_self_subject(self):
        """설계사가 subject=customer_self로 위조해도 서버가 planner_attested로 강제(read_only)."""
        r = self.client.post(
            f'/api/v1/customers/{self.customer.id}/consents/',
            {'scope': ConsentLog.SCOPE_OVERSEAS_MEDICAL, 'subject': 'customer_self'},
            format='json')
        self.assertEqual(r.status_code, 201)
        log = ConsentLog.objects.get(id=r.json()['id'])
        self.assertEqual(log.subject, ConsentLog.SUBJECT_PLANNER_ATTESTED)

    def test_consent_log_is_append_only(self):
        """ConsentLog는 append-only — PATCH/DELETE 차단(405)."""
        r = self.client.post(
            f'/api/v1/customers/{self.customer.id}/consents/',
            {'scope': ConsentLog.SCOPE_MARKETING, 'doc_version': 'MKT-v1'}, format='json')
        self.assertEqual(r.status_code, 201)
        log_id = r.json()['id']
        r_patch = self.client.patch(
            f'/api/v1/customers/{self.customer.id}/consents/{log_id}/',
            {'purpose': '변조'}, format='json')
        self.assertEqual(r_patch.status_code, 405)
        r_del = self.client.delete(
            f'/api/v1/customers/{self.customer.id}/consents/{log_id}/')
        self.assertEqual(r_del.status_code, 405)


@override_settings(ANALYZE_MEDICAL_ENABLED=False)
class BetaMedicalDisabledTests(TestCase):
    """★ 베타 게이트(council 2026-06-21 P0-3) — ANALYZE_MEDICAL_ENABLED=False면
    국외이전 동의가 있어도 병력 등록을 403으로 차단(베타 미수집)."""

    def setUp(self):
        self.user, self.client = _make_planner('beta@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='홍길동', mobile_phone_number='010-0000-0000',
            consent_overseas_at=timezone.now())  # 동의가 있어도 차단되어야 함

    def test_medical_blocked_in_beta(self):
        r = self.client.post(
            f'/api/v1/customers/{self.customer.id}/medical/',
            {'disease_name': '고혈압', 'is_inpatient': False}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()['code'], 'MEDICAL_DISABLED_BETA')
        self.assertEqual(CustomerMedicalHistory.objects.count(), 0)


class ConsentLogRetentionTests(TestCase):
    """★ 동의기록 보존(council 2026-06-21 P0-5) — 고객 삭제(파기) 후에도
    ConsentLog는 SET_NULL로 남는다(처리방침상 동의기록 5년 보관)."""

    def test_consent_log_survives_customer_delete(self):
        user, _ = _make_planner('retain@test.com')
        customer = Customer.objects.create(owner=user, name='파기대상',
                                           mobile_phone_number='010-9999-8888')
        log = ConsentLog.objects.create(
            customer=customer, scope=ConsentLog.SCOPE_OVERSEAS_MEDICAL,
            doc_version='OVERSEAS-v1.0')
        log_id = log.id
        customer.delete()  # 고객 파기
        # 동의기록은 남고, customer 링크만 null
        self.assertTrue(ConsentLog.objects.filter(id=log_id).exists())
        log.refresh_from_db()
        self.assertIsNone(log.customer_id)


class CustomerSelfConsentTests(TestCase):
    """★ P3c: 고객 본인 국외이전 동의 — 토큰·동의요청(설계사)·공개 동의(고객)."""

    def setUp(self):
        cache.clear()  # ScopedRateThrottle(consent_public) 카운터 초기화
        self.user_a, self.client_a = _make_planner('agent_a@test.com')
        self.user_b, self.client_b = _make_planner('agent_b@test.com')
        self.customer = Customer.objects.create(
            owner=self.user_a, name='홍길동', mobile_phone_number='010-0000-0000')
        self.public = APIClient()  # 비인증 공개 클라이언트

    # ── 토큰 ──
    def test_token_roundtrip(self):
        token = make_consent_token(self.customer)
        self.assertEqual(read_consent_token(token)['pk'], self.customer.id)

    def test_token_expired(self):
        token = make_consent_token(self.customer)
        with override_settings(CONSENT_TOKEN_TTL_HOURS=0):
            with self.assertRaises(signing.SignatureExpired):
                read_consent_token(token)

    def test_token_tampered(self):
        with self.assertRaises(signing.BadSignature):
            read_consent_token('not.a.valid-token')

    # ── 설계사: 동의 요청 링크 생성 ──
    def test_consent_request_owner_ok(self):
        r = self.client_a.post(f'/api/v1/customers/{self.customer.id}/consent-requests/')
        self.assertEqual(r.status_code, 201)
        body = r.json()
        self.assertIn('token', body)
        self.assertIn('/c/', body['consent_url'])
        self.assertFalse(body['already_consented'])
        self.assertEqual(read_consent_token(body['token'])['pk'], self.customer.id)

    def test_consent_request_owner_isolation(self):
        """타 설계사(B)는 A의 고객으로 링크를 만들 수 없다(404)."""
        r = self.client_b.post(f'/api/v1/customers/{self.customer.id}/consent-requests/')
        self.assertEqual(r.status_code, 404)

    # ── 공개: 고지 GET ──
    def test_public_get_discloses_masked(self):
        token = make_consent_token(self.customer)
        r = self.public.get(f'/api/v1/c/{token}/')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body['customer']['name_masked'], '홍**')
        # 다항목화: 구 overseas_medical 단일 토큰 → items[0]['already'] 확인
        self.assertIn('items', body)
        overseas_item = next(it for it in body['items'] if it['scope'] == 'overseas_medical')
        self.assertFalse(overseas_item['already'])
        # PII 누출 금지 — 전화/생년/병력 미포함
        self.assertNotIn('010-0000-0000', r.content.decode())

    def test_public_get_expired_410(self):
        token = make_consent_token(self.customer)
        with override_settings(CONSENT_TOKEN_TTL_HOURS=0):
            r = self.public.get(f'/api/v1/c/{token}/')
        self.assertEqual(r.status_code, 410)

    def test_public_get_invalid_404(self):
        r = self.public.get('/api/v1/c/bad-token/')
        self.assertEqual(r.status_code, 404)

    # ── 공개: 동의 제출 POST ──
    def test_public_post_consent_unlocks_gate(self):
        token = make_consent_token(self.customer)
        r = self.public.post(f'/api/v1/c/{token}/',
                             {'agreed': ['overseas_medical']}, format='json')
        self.assertEqual(r.status_code, 201)
        self.customer.refresh_from_db()
        self.assertIsNotNone(self.customer.consent_overseas_at)  # OCR 게이트 해제
        log = ConsentLog.objects.filter(customer=self.customer).latest('agreed_at')
        self.assertEqual(log.subject, ConsentLog.SUBJECT_CUSTOMER_SELF)
        self.assertEqual(log.doc_version, CONSENT_TEXTS_VERSION)  # 버전 스탬프

    def test_public_post_without_consent_412(self):
        token = make_consent_token(self.customer)
        r = self.public.post(f'/api/v1/c/{token}/', {}, format='json')
        self.assertEqual(r.status_code, 412)
        self.customer.refresh_from_db()
        self.assertIsNone(self.customer.consent_overseas_at)

    def test_public_post_idempotent(self):
        """재동의가 기존 스냅샷 시각을 덮지 않는다(append-only 정신)."""
        token = make_consent_token(self.customer)
        self.public.post(f'/api/v1/c/{token}/',
                         {'agreed': ['overseas_medical']}, format='json')
        self.customer.refresh_from_db()
        first = self.customer.consent_overseas_at
        self.public.post(f'/api/v1/c/{token}/',
                         {'agreed': ['overseas_medical']}, format='json')
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.consent_overseas_at, first)

    def test_old_version_consent_is_reagreeable_via_c(self):
        """구버전 문구로 동의한 고객(consent_overseas_at 세팅됨)이 /c 로 재동의해 게이트를 다시 연다.

        LB-2 회복 경로: GET에서 overseas already=False(체크박스 재활성) → POST가 새 v2 로그 생성
        → has_current_overseas_consent 통과. 구버전 로그만 있으면 게이트가 막혀 있어야 한다.
        """
        # 구버전 동의 재현: consent_overseas_at 세팅 + doc_version='' 로그
        _grant_overseas(self.customer, version='')
        self.assertFalse(has_current_overseas_consent(self.customer))  # 게이트 아직 닫힘

        token = make_consent_token(self.customer)
        # GET: 구버전 고객도 overseas 항목이 재동의 가능(already=False)해야 함
        g = self.public.get(f'/api/v1/c/{token}/')
        self.assertEqual(g.status_code, 200)
        overseas_item = next(it for it in g.json()['items']
                             if it['scope'] == 'overseas_medical')
        self.assertFalse(overseas_item['already'])

        # POST: 새 v2 로그가 생성되어 게이트가 열림
        r = self.public.post(f'/api/v1/c/{token}/',
                             {'agreed': ['overseas_medical']}, format='json')
        self.assertEqual(r.status_code, 201)
        self.customer.refresh_from_db()
        self.assertTrue(has_current_overseas_consent(self.customer))
        # 새 로그는 현재 버전으로 스탬프됨
        latest = ConsentLog.objects.filter(
            customer=self.customer, scope=ConsentLog.SCOPE_OVERSEAS_MEDICAL,
        ).latest('agreed_at')
        self.assertEqual(latest.doc_version, CONSENT_TEXTS_VERSION)

    @override_settings(REQUIRE_CUSTOMER_SELF_CONSENT=True)
    def test_customer_self_unlocks_in_strict_mode(self):
        """전방검증: strict 모드여도 고객 본인 동의는 정상적으로 게이트를 연다."""
        token = make_consent_token(self.customer)
        r = self.public.post(f'/api/v1/c/{token}/',
                             {'agreed': ['overseas_medical']}, format='json')
        self.assertEqual(r.status_code, 201)
        self.customer.refresh_from_db()
        self.assertIsNotNone(self.customer.consent_overseas_at)


class AuthGateTests(TestCase):
    """인증/이메일 인증 게이트."""

    def test_unauthenticated_blocked(self):
        c = APIClient()
        self.assertEqual(c.get('/api/v1/customers/').status_code, 401)

    def test_unverified_email_blocked(self):
        """이메일 미인증(is_active=False) → IsEmailVerified 403."""
        user = User.objects.create_user(email='unverified@test.com', password='inpaPass123!')
        Profile.objects.create(user=user)
        c = APIClient()
        c.force_authenticate(user=user)
        r = c.get('/api/v1/customers/')
        self.assertEqual(r.status_code, 403)


class ApplyPresetTests(TestCase):
    """★ PRESET_DISABLED — apply-preset 은 §97/무등록중개 레드라인으로 비활성.
       모든 호출(인증 성공 포함)이 400 PRESET_DISABLED 를 반환하고 PlannerBaseline 행을 만들지 않음."""

    URL = '/api/v1/planner-baselines/apply-preset/'
    NONLIFE = PlannerBaseline.PRODUCT_GROUP_NONLIFE   # 2

    def setUp(self):
        self.user_a, self.client_a = _make_planner('preset-a@test.com')

    def test_apply_preset_returns_400_and_creates_nothing(self):
        """프리셋 적용 → 400 PRESET_DISABLED, PlannerBaseline 행 0개."""
        r = self.client_a.post(self.URL, {'product_group': self.NONLIFE}, format='json')
        self.assertEqual(r.status_code, 400)
        body = r.json()
        self.assertEqual(body.get('code'), 'PRESET_DISABLED')
        self.assertEqual(
            PlannerBaseline.objects.filter(owner=self.user_a).count(), 0)

    def test_apply_preset_any_group_returns_400(self):
        """상품군 값과 무관하게 400 반환."""
        for pg in [1, 2, 3, 4]:
            r = self.client_a.post(self.URL, {'product_group': pg}, format='json')
            self.assertEqual(r.status_code, 400,
                             msg=f'product_group={pg} 는 400 이어야 함')

    def test_unauthenticated_blocked(self):
        c = APIClient()
        r = c.post(self.URL, {'product_group': self.NONLIFE}, format='json')
        self.assertEqual(r.status_code, 401)

    def test_unverified_email_blocked(self):
        user = User.objects.create_user(email='preset-unverified@test.com',
                                        password='inpaPass123!')
        Profile.objects.create(user=user)
        c = APIClient()
        c.force_authenticate(user=user)
        r = c.post(self.URL, {'product_group': self.NONLIFE}, format='json')
        self.assertEqual(r.status_code, 403)


class PlannerBaselineValidationTests(TestCase):
    URL = '/api/v1/planner-baselines/'
    BATCH_URL = '/api/v1/planner-baselines/batch/'
    CATALOG_URL = '/api/v1/baseline-catalog/'

    def setUp(self):
        self.user, self.client = _make_planner('baseline-validation@test.com')
        category = AnalysisCategory.objects.create(
            insurance_type=0, name='[표준]직접 저장', order=1)
        sub_category = AnalysisSubCategory.objects.create(
            insurance_type=0, category=category, name='저장', order=1)
        self.detail = AnalysisDetail.objects.create(
            sub_category=sub_category, name='일반사망', order=1)
        nonstandard_category = AnalysisCategory.objects.create(
            insurance_type=0, name='촬영용', order=2)
        nonstandard_sub = AnalysisSubCategory.objects.create(
            insurance_type=0, category=nonstandard_category, name='저장', order=1)
        self.nonstandard_detail = AnalysisDetail.objects.create(
            sub_category=nonstandard_sub, name='촬영 담보', order=1)
        self.valid = {
            'analysis_detail': self.detail.id,
            'coverage_key': '클라이언트가 바꾼 이름',
            'product_group': PlannerBaseline.PRODUCT_GROUP_NONLIFE,
            'age_band': '30s',
            'gender': 1,
            'recommend_min': '10000000',
            'recommend_max': '30000000',
            'unit': PlannerBaseline.UNIT_WON,
            'baseline_source': 'preset:forged',
            'preset_origin': 'forged',
            'is_active': True,
        }

    def _batch_change(self, **overrides):
        change = {
            'analysis_detail_id': self.detail.id,
            'product_group': PlannerBaseline.PRODUCT_GROUP_ALL,
            'age_band': PlannerBaseline.AGE_ALL,
            'gender': 2,
            'recommend_min': '5000',
            'recommend_max': None,
            'unit': PlannerBaseline.UNIT_TEN_THOUSAND_WON,
        }
        change.update(overrides)
        return change

    def _assert_revision_and_stale_batch(self):
        self.assertEqual(
            PlannerBaselineRevision.objects.get(owner=self.user).revision, 1)
        response = self.client.post(
            self.BATCH_URL,
            {'revision': 0, 'changes': [self._batch_change()]},
            format='json',
        )
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(
            response.json()['code'], 'baseline_revision_conflict')

    def test_negative_recommendation_bounds_are_rejected(self):
        for field in ('recommend_min', 'recommend_max'):
            with self.subTest(field=field):
                payload = {**self.valid, field: '-1'}
                response = self.client.post(self.URL, payload, format='json')

                self.assertEqual(response.status_code, 400, response.content)
                self.assertIn(field, response.json())
        self.assertFalse(PlannerBaseline.objects.filter(owner=self.user).exists())

    def test_recommendation_minimum_above_maximum_is_rejected(self):
        response = self.client.post(
            self.URL,
            {**self.valid, 'recommend_min': '30000001'},
            format='json',
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn('recommend_max', response.json())
        self.assertFalse(PlannerBaseline.objects.filter(owner=self.user).exists())

    def test_create_requires_a_standard_detail_and_forces_server_fields(self):
        response = self.client.post(self.URL, self.valid, format='json')

        self.assertEqual(response.status_code, 201, response.content)
        baseline = PlannerBaseline.objects.get()
        self.assertEqual(baseline.owner_id, self.user.id)
        self.assertEqual(baseline.analysis_detail_id, self.detail.id)
        self.assertEqual(baseline.coverage_key, self.detail.name)
        self.assertEqual(baseline.baseline_source, 'planner')
        self.assertIsNone(baseline.preset_origin)

        for detail_value in (None, self.nonstandard_detail.id, 999999):
            with self.subTest(detail_value=detail_value):
                payload = {**self.valid, 'gender': 2}
                if detail_value is None:
                    payload.pop('analysis_detail')
                else:
                    payload['analysis_detail'] = detail_value
                rejected = self.client.post(self.URL, payload, format='json')
                self.assertEqual(rejected.status_code, 400, rejected.content)

    def test_direct_create_accepts_every_product_group(self):
        for product_group in (
                PlannerBaseline.PRODUCT_GROUP_ALL,
                PlannerBaseline.PRODUCT_GROUP_LIFE,
                PlannerBaseline.PRODUCT_GROUP_NONLIFE,
                PlannerBaseline.PRODUCT_GROUP_INDEMNITY,
                PlannerBaseline.PRODUCT_GROUP_ANNUITY):
            with self.subTest(product_group=product_group):
                response = self.client.post(
                    self.URL,
                    {**self.valid, 'product_group': product_group},
                    format='json',
                )
                self.assertEqual(response.status_code, 201, response.content)
                self.assertEqual(response.json()['product_group'], product_group)

    def test_direct_create_increments_revision_and_invalidates_stale_batch(self):
        self.assertEqual(
            self.client.get(self.CATALOG_URL).json()['revision'], 0)

        response = self.client.post(self.URL, self.valid, format='json')

        self.assertEqual(response.status_code, 201, response.content)
        self._assert_revision_and_stale_batch()

    def test_direct_patch_increments_revision_and_invalidates_stale_batch(self):
        baseline = PlannerBaseline.objects.create(
            owner=self.user,
            analysis_detail=self.detail,
            coverage_key=self.detail.name,
            product_group=PlannerBaseline.PRODUCT_GROUP_NONLIFE,
            age_band='30s',
            gender=1,
            recommend_min=1000,
            unit=PlannerBaseline.UNIT_WON,
            baseline_source='planner',
        )
        self.assertEqual(
            self.client.get(self.CATALOG_URL).json()['revision'], 0)

        response = self.client.patch(
            f'{self.URL}{baseline.id}/',
            {'recommend_min': '2000'},
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.content)
        self._assert_revision_and_stale_batch()

    def test_direct_delete_increments_revision_and_invalidates_stale_batch(self):
        baseline = PlannerBaseline.objects.create(
            owner=self.user,
            analysis_detail=self.detail,
            coverage_key=self.detail.name,
            product_group=PlannerBaseline.PRODUCT_GROUP_NONLIFE,
            age_band='30s',
            gender=1,
            recommend_min=1000,
            unit=PlannerBaseline.UNIT_WON,
            baseline_source='planner',
        )
        self.assertEqual(
            self.client.get(self.CATALOG_URL).json()['revision'], 0)

        response = self.client.delete(f'{self.URL}{baseline.id}/')

        self.assertEqual(response.status_code, 204, response.content)
        self._assert_revision_and_stale_batch()

    def test_direct_write_rejects_empty_amounts_and_unsupported_scopes(self):
        invalid_payloads = (
            {**self.valid, 'recommend_min': None, 'recommend_max': None},
            {**self.valid, 'product_group': 5},
            {**self.valid, 'age_band': 'bogus'},
            {**self.valid, 'gender': 3},
        )

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                response = self.client.post(
                    self.URL, payload, format='json')
                self.assertEqual(response.status_code, 400, response.content)

        self.assertFalse(
            PlannerBaseline.objects.filter(owner=self.user).exists())

    def test_direct_patch_rejects_clearing_both_amounts(self):
        baseline = PlannerBaseline.objects.create(
            owner=self.user,
            analysis_detail=self.detail,
            coverage_key=self.detail.name,
            product_group=PlannerBaseline.PRODUCT_GROUP_ALL,
            age_band=PlannerBaseline.AGE_ALL,
            gender=None,
            recommend_min=1000,
            baseline_source='planner',
        )

        response = self.client.patch(
            f'{self.URL}{baseline.id}/',
            {'recommend_min': None, 'recommend_max': None},
            format='json',
        )

        self.assertEqual(response.status_code, 400, response.content)
        baseline.refresh_from_db()
        self.assertEqual(baseline.recommend_min, 1000)

    def test_direct_create_and_patch_cannot_override_server_owned_active_state(self):
        payload = {**self.valid, 'is_active': False}

        created = self.client.post(self.URL, payload, format='json')

        self.assertEqual(created.status_code, 201, created.content)
        baseline = PlannerBaseline.objects.get(pk=created.json()['id'])
        self.assertTrue(baseline.is_active)

        updated = self.client.patch(
            f'{self.URL}{baseline.id}/',
            {'is_active': False},
            format='json',
        )

        self.assertEqual(updated.status_code, 200, updated.content)
        baseline.refresh_from_db()
        self.assertTrue(baseline.is_active)

        baseline.is_active = False
        baseline.save(update_fields=['is_active'])
        reactivation_attempt = self.client.patch(
            f'{self.URL}{baseline.id}/',
            {'is_active': True},
            format='json',
        )

        self.assertEqual(
            reactivation_attempt.status_code, 200, reactivation_attempt.content)
        baseline.refresh_from_db()
        self.assertFalse(baseline.is_active)

    def test_direct_duplicate_scope_returns_400_instead_of_integrity_error(self):
        first = self.client.post(self.URL, self.valid, format='json')
        self.assertEqual(first.status_code, 201, first.content)

        duplicate = self.client.post(self.URL, self.valid, format='json')

        self.assertEqual(duplicate.status_code, 400, duplicate.content)
        self.assertEqual(
            PlannerBaseline.objects.filter(owner=self.user).count(), 1)

    def test_direct_integrity_race_returns_stable_conflict(self):
        with mock.patch(
                'inpa.customers.serializers.PlannerBaselineSerializer.create',
                side_effect=IntegrityError('simulated final unique race')):
            response = self.client.post(self.URL, self.valid, format='json')

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()['code'], 'baseline_scope_conflict')
        self.assertFalse(
            PlannerBaseline.objects.filter(owner=self.user).exists())
        self.assertFalse(
            PlannerBaselineRevision.objects.filter(owner=self.user).exists())

    def test_direct_create_preserves_legacy_rows_until_explicit_resolution(self):
        exact = PlannerBaseline.objects.create(
            owner=self.user,
            analysis_detail=None,
            coverage_key=self.detail.name,
            product_group=PlannerBaseline.PRODUCT_GROUP_NONLIFE,
            age_band='30s',
            gender=1,
            recommend_min=800,
            baseline_source='planner',
        )
        unrelated = PlannerBaseline.objects.create(
            owner=self.user,
            analysis_detail=None,
            coverage_key=self.detail.name,
            product_group=PlannerBaseline.PRODUCT_GROUP_NONLIFE,
            age_band='40s',
            gender=1,
            recommend_min=900,
            baseline_source='planner',
        )

        response = self.client.post(self.URL, self.valid, format='json')

        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(
            PlannerBaseline.objects.filter(pk=exact.pk).exists())
        self.assertTrue(
            PlannerBaseline.objects.filter(pk=unrelated.pk).exists())

    def test_direct_patch_preserves_legacy_rows_until_explicit_resolution(self):
        baseline = PlannerBaseline.objects.create(
            owner=self.user,
            analysis_detail=self.detail,
            coverage_key=self.detail.name,
            product_group=PlannerBaseline.PRODUCT_GROUP_NONLIFE,
            age_band='30s',
            gender=1,
            recommend_min=1000,
            baseline_source='planner',
        )
        old_legacy = PlannerBaseline.objects.create(
            owner=self.user,
            analysis_detail=None,
            coverage_key=self.detail.name,
            product_group=PlannerBaseline.PRODUCT_GROUP_NONLIFE,
            age_band='30s',
            gender=1,
            recommend_min=800,
            baseline_source='planner',
        )
        new_legacy = PlannerBaseline.objects.create(
            owner=self.user,
            analysis_detail=None,
            coverage_key=self.detail.name,
            product_group=PlannerBaseline.PRODUCT_GROUP_NONLIFE,
            age_band='40s',
            gender=1,
            recommend_min=900,
            baseline_source='planner',
        )
        unrelated = PlannerBaseline.objects.create(
            owner=self.user,
            analysis_detail=None,
            coverage_key=self.detail.name,
            product_group=PlannerBaseline.PRODUCT_GROUP_NONLIFE,
            age_band='50s',
            gender=1,
            recommend_min=700,
            baseline_source='planner',
        )

        response = self.client.patch(
            f'{self.URL}{baseline.id}/',
            {'age_band': '40s'},
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            PlannerBaseline.objects.filter(
                pk__in=[old_legacy.pk, new_legacy.pk]).count(),
            2,
        )
        self.assertTrue(
            PlannerBaseline.objects.filter(pk=unrelated.pk).exists())

    def test_direct_delete_preserves_legacy_rows_until_explicit_resolution(self):
        baseline = PlannerBaseline.objects.create(
            owner=self.user,
            analysis_detail=self.detail,
            coverage_key=self.detail.name,
            product_group=PlannerBaseline.PRODUCT_GROUP_NONLIFE,
            age_band='30s',
            gender=1,
            recommend_min=1000,
            baseline_source='planner',
        )
        exact = PlannerBaseline.objects.create(
            owner=self.user,
            analysis_detail=None,
            coverage_key=self.detail.name,
            product_group=PlannerBaseline.PRODUCT_GROUP_NONLIFE,
            age_band='30s',
            gender=1,
            recommend_min=800,
            baseline_source='planner',
        )
        unrelated = PlannerBaseline.objects.create(
            owner=self.user,
            analysis_detail=None,
            coverage_key=self.detail.name,
            product_group=PlannerBaseline.PRODUCT_GROUP_NONLIFE,
            age_band='30s',
            gender=2,
            recommend_min=900,
            baseline_source='planner',
        )

        response = self.client.delete(f'{self.URL}{baseline.id}/')

        self.assertEqual(response.status_code, 204, response.content)
        self.assertTrue(
            PlannerBaseline.objects.filter(pk=exact.pk).exists())
        self.assertTrue(
            PlannerBaseline.objects.filter(pk=unrelated.pk).exists())


class PlannerBaselineDisappearanceConcurrencyTests(TransactionTestCase):
    reset_sequences = True
    URL = '/api/v1/planner-baselines/'

    def setUp(self):
        self.user, self.client = _make_planner(
            'baseline-disappearance@test.com')
        category = AnalysisCategory.objects.create(
            insurance_type=0, name='[표준]삭제 경합', order=1)
        sub_category = AnalysisSubCategory.objects.create(
            insurance_type=0, category=category, name='삭제 경합', order=1)
        self.detail = AnalysisDetail.objects.create(
            sub_category=sub_category, name='삭제 경합 담보', order=1)
        self.baseline = PlannerBaseline.objects.create(
            owner=self.user,
            analysis_detail=self.detail,
            coverage_key=self.detail.name,
            product_group=PlannerBaseline.PRODUCT_GROUP_ALL,
            age_band=PlannerBaseline.AGE_ALL,
            gender=None,
            recommend_min=1000,
            baseline_source='planner',
        )
        self.client.raise_request_exception = False

    def _request_after_competing_delete(self, method):
        from .views import PlannerBaselineViewSet

        original_lock_revision = PlannerBaselineViewSet._lock_revision
        requesting_thread = threading.get_ident()
        winner_responses = []

        def lock_after_competing_delete(owner_id):
            if threading.get_ident() == requesting_thread:
                def competing_delete():
                    client = APIClient()
                    client.force_authenticate(user=self.user)
                    return client.delete(f'{self.URL}{self.baseline.pk}/')

                with ThreadPoolExecutor(max_workers=1) as executor:
                    winner_responses.append(
                        executor.submit(
                            _thread_database_call,
                            competing_delete,
                        ).result(timeout=10)
                    )
            return original_lock_revision(owner_id)

        with mock.patch.object(
                PlannerBaselineViewSet,
                '_lock_revision',
                side_effect=lock_after_competing_delete):
            if method == 'patch':
                loser = self.client.patch(
                    f'{self.URL}{self.baseline.pk}/',
                    {'recommend_min': '2000'},
                    format='json',
                )
            else:
                loser = self.client.delete(
                    f'{self.URL}{self.baseline.pk}/')

        self.assertEqual(winner_responses[0].status_code, 204)
        return loser

    def test_patch_returns_404_when_delete_wins_before_locked_refetch(self):
        response = self._request_after_competing_delete('patch')

        self.assertEqual(response.status_code, 404, response.content)
        self.assertFalse(
            PlannerBaseline.objects.filter(pk=self.baseline.pk).exists())
        self.assertEqual(
            PlannerBaselineRevision.objects.get(owner=self.user).revision, 1)

    def test_delete_returns_404_when_another_delete_wins_before_locked_refetch(self):
        response = self._request_after_competing_delete('delete')

        self.assertEqual(response.status_code, 404, response.content)
        self.assertFalse(
            PlannerBaseline.objects.filter(pk=self.baseline.pk).exists())
        self.assertEqual(
            PlannerBaselineRevision.objects.get(owner=self.user).revision, 1)


class PlannerBaselineCatalogTests(TestCase):
    CATALOG_URL = '/api/v1/baseline-catalog/'
    BATCH_URL = '/api/v1/planner-baselines/batch/'

    def setUp(self):
        self.user, self.client = _make_planner('baseline-catalog@test.com')
        self.other_user, self.other_client = _make_planner(
            'baseline-catalog-other@test.com')

        category_later = AnalysisCategory.objects.create(
            insurance_type=2, name='[표준]수술비', order=2)
        category_first = AnalysisCategory.objects.create(
            insurance_type=0, name='[표준]진단비', order=1)
        sub_later = AnalysisSubCategory.objects.create(
            insurance_type=2, category=category_later, name='상해', order=1)
        sub_later_in_first = AnalysisSubCategory.objects.create(
            insurance_type=0, category=category_first, name='뇌', order=2)
        sub_first = AnalysisSubCategory.objects.create(
            insurance_type=0, category=category_first, name='암', order=1)
        self.detail_later_category = AnalysisDetail.objects.create(
            sub_category=sub_later, name='골절 수술비', order=1)
        self.detail_later = AnalysisDetail.objects.create(
            sub_category=sub_later_in_first, name='뇌혈관 진단비', order=1)
        self.detail_first = AnalysisDetail.objects.create(
            sub_category=sub_first, name='일반암 진단비', order=1,
            chart_based_amount=9999)

        nonstandard_category = AnalysisCategory.objects.create(
            insurance_type=0, name='[촬영]진단비', order=0)
        nonstandard_sub = AnalysisSubCategory.objects.create(
            insurance_type=0, category=nonstandard_category, name='암', order=1)
        self.nonstandard_detail = AnalysisDetail.objects.create(
            sub_category=nonstandard_sub, name='촬영용 담보', order=1)

        self.owner_baseline = PlannerBaseline.objects.create(
            owner=self.user,
            analysis_detail=self.detail_first,
            coverage_key=self.detail_first.name,
            product_group=PlannerBaseline.PRODUCT_GROUP_ALL,
            age_band=PlannerBaseline.AGE_ALL,
            gender=None,
            recommend_min=5000,
            recommend_max=None,
            unit=PlannerBaseline.UNIT_TEN_THOUSAND_WON,
            baseline_source='planner',
        )
        PlannerBaseline.objects.create(
            owner=self.other_user,
            analysis_detail=self.detail_first,
            coverage_key=self.detail_first.name,
            product_group=PlannerBaseline.PRODUCT_GROUP_ALL,
            age_band=PlannerBaseline.AGE_ALL,
            gender=1,
            recommend_min=9000,
            unit=PlannerBaseline.UNIT_TEN_THOUSAND_WON,
            baseline_source='planner',
        )

    @staticmethod
    def _change(detail, **overrides):
        values = {
            'analysis_detail_id': detail.id,
            'product_group': PlannerBaseline.PRODUCT_GROUP_ALL,
            'age_band': PlannerBaseline.AGE_ALL,
            'gender': None,
            'recommend_min': '5000',
            'recommend_max': None,
            'unit': PlannerBaseline.UNIT_TEN_THOUSAND_WON,
        }
        values.update(overrides)
        return values

    def test_catalog_is_ordered_owner_scoped_and_contains_no_guessed_amounts(self):
        response = self.client.get(self.CATALOG_URL)

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body['revision'], 0)
        self.assertEqual(
            [category['name'] for category in body['categories']],
            ['진단비', '수술비'],
        )
        self.assertEqual(
            [sub['name'] for sub in body['categories'][0]['subcategories']],
            ['암', '뇌'],
        )
        detail = body['categories'][0]['subcategories'][0]['details'][0]
        self.assertEqual(detail['id'], self.detail_first.id)
        self.assertEqual(detail['name'], self.detail_first.name)
        self.assertEqual(detail['unit'], PlannerBaseline.UNIT_TEN_THOUSAND_WON)
        self.assertEqual(len(detail['baselines']), 1)
        self.assertEqual(detail['baselines'][0]['id'], self.owner_baseline.id)
        self.assertEqual(detail['baselines'][0]['recommend_min'], '5000.00')
        serialized = json.dumps(body, ensure_ascii=False)
        self.assertNotIn('chart_based_amount', serialized)
        self.assertNotIn('9999', serialized)
        self.assertNotIn('9000', serialized)
        self.assertNotIn('촬영용 담보', serialized)
        self.assertTrue(
            PlannerBaselineRevision.objects.filter(owner=self.user).exists())

    def test_ambiguous_legacy_row_is_visible_with_applied_status_and_reason(self):
        duplicate = AnalysisDetail.objects.create(
            sub_category=self.detail_first.sub_category,
            name=self.detail_later.name,
            order=9,
        )
        legacy = PlannerBaseline.objects.create(
            owner=self.user,
            analysis_detail=None,
            coverage_key=self.detail_later.name,
            product_group=PlannerBaseline.PRODUCT_GROUP_ALL,
            age_band=PlannerBaseline.AGE_ALL,
            gender=None,
            recommend_min=2500,
            recommend_max=5000,
            unit=PlannerBaseline.UNIT_TEN_THOUSAND_WON,
            baseline_source='planner',
            is_active=True,
        )
        other_legacy = PlannerBaseline.objects.create(
            owner=self.other_user,
            analysis_detail=None,
            coverage_key=self.detail_later.name,
            product_group=PlannerBaseline.PRODUCT_GROUP_ALL,
            age_band=PlannerBaseline.AGE_ALL,
            gender=None,
            recommend_min=9000,
            baseline_source='planner',
        )

        response = self.client.get(self.CATALOG_URL)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['legacy_baselines'], [{
            'id': legacy.id,
            'coverage_key': self.detail_later.name,
            'product_group': PlannerBaseline.PRODUCT_GROUP_ALL,
            'age_band': PlannerBaseline.AGE_ALL,
            'gender': None,
            'recommend_min': '2500.00',
            'recommend_max': '5000.00',
            'unit': PlannerBaseline.UNIT_TEN_THOUSAND_WON,
            'is_active': True,
            'is_applied': True,
            'requires_adoption': False,
            'conflict_code': 'multiple_standard_matches',
            'conflict_reason': (
                '같은 이름의 표준 담보가 여러 곳에 있어 연결할 항목을 확인해 주세요.'
            ),
            'matching_analysis_detail_ids': sorted([
                self.detail_later.id,
                duplicate.id,
            ]),
        }])
        self.assertNotIn(
            other_legacy.id,
            [
                row['id']
                for row in response.json()['legacy_baselines']
            ],
        )

    def test_legacy_preset_and_source_less_rows_require_adoption_until_saved(self):
        preset = PlannerBaseline.objects.create(
            owner=self.user,
            analysis_detail=None,
            coverage_key=self.detail_later.name,
            product_group=PlannerBaseline.PRODUCT_GROUP_ALL,
            age_band=PlannerBaseline.AGE_ALL,
            gender=None,
            recommend_min=2500,
            unit=PlannerBaseline.UNIT_TEN_THOUSAND_WON,
            baseline_source=PlannerBaseline.SOURCE_PRESET,
            preset_origin='v0_starter',
            is_active=True,
        )
        source_less = PlannerBaseline.objects.create(
            owner=self.user,
            analysis_detail=None,
            coverage_key=self.detail_later_category.name,
            product_group=PlannerBaseline.PRODUCT_GROUP_ALL,
            age_band=PlannerBaseline.AGE_ALL,
            gender=None,
            recommend_min=1500,
            unit=PlannerBaseline.UNIT_TEN_THOUSAND_WON,
            baseline_source=None,
            is_active=True,
        )

        before_link = self.client.get(self.CATALOG_URL).json()['legacy_baselines']
        before_link_by_id = {row['id']: row for row in before_link}
        self.assertFalse(before_link_by_id[preset.id]['is_applied'])
        self.assertTrue(before_link_by_id[preset.id]['requires_adoption'])
        self.assertFalse(before_link_by_id[source_less.id]['is_applied'])
        self.assertTrue(before_link_by_id[source_less.id]['requires_adoption'])

        self.assertEqual(
            self.client.post(
                f'/api/v1/planner-baselines/{preset.id}/link/',
                {'analysis_detail_id': self.detail_later.id},
                format='json',
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                f'/api/v1/planner-baselines/{source_less.id}/link/',
                {'analysis_detail_id': self.detail_later_category.id},
                format='json',
            ).status_code,
            200,
        )

        after_link = self.client.get(self.CATALOG_URL).json()
        linked_sources = {
            detail['id']: detail['baselines'][0]['baseline_source']
            for category in after_link['categories']
            for subcategory in category['subcategories']
            for detail in subcategory['details']
            if detail['id'] in {
                self.detail_later.id,
                self.detail_later_category.id,
            }
        }
        self.assertEqual(linked_sources, {
            self.detail_later.id: PlannerBaseline.SOURCE_PRESET,
            self.detail_later_category.id: None,
        })

        response = self.client.post(
            self.BATCH_URL,
            {
                'revision': after_link['revision'],
                'changes': [self._change(
                    self.detail_later,
                    recommend_min='2500',
                )],
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.content)
        preset.refresh_from_db()
        source_less.refresh_from_db()
        self.assertEqual(preset.baseline_source, PlannerBaseline.SOURCE_PLANNER)
        self.assertIsNone(preset.preset_origin)
        self.assertTrue(preset.is_active)
        self.assertIsNone(source_less.baseline_source)
        self.assertTrue(source_less.is_active)

        response = self.client.post(
            self.BATCH_URL,
            {
                'revision': response.json()['revision'],
                'changes': [self._change(
                    self.detail_later_category,
                    recommend_min='1500',
                )],
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.content)
        source_less.refresh_from_db()
        self.assertEqual(
            source_less.baseline_source,
            PlannerBaseline.SOURCE_PLANNER,
        )
        self.assertIsNone(source_less.preset_origin)
        self.assertTrue(source_less.is_active)

    def test_inactive_legacy_planner_row_requires_explicit_reuse_not_adoption(self):
        inactive = PlannerBaseline.objects.create(
            owner=self.user,
            analysis_detail=None,
            coverage_key=self.detail_later.name,
            product_group=PlannerBaseline.PRODUCT_GROUP_ALL,
            age_band=PlannerBaseline.AGE_ALL,
            gender=None,
            recommend_min=2500,
            unit=PlannerBaseline.UNIT_TEN_THOUSAND_WON,
            baseline_source=PlannerBaseline.SOURCE_PLANNER,
            preset_origin='historic_planner',
            is_active=False,
        )
        untouched = PlannerBaseline.objects.create(
            owner=self.user,
            analysis_detail=self.detail_later_category,
            coverage_key=self.detail_later_category.name,
            product_group=PlannerBaseline.PRODUCT_GROUP_ALL,
            age_band=PlannerBaseline.AGE_ALL,
            gender=None,
            recommend_min=1500,
            unit=PlannerBaseline.UNIT_TEN_THOUSAND_WON,
            baseline_source=PlannerBaseline.SOURCE_PLANNER,
            preset_origin='leave-as-is',
            is_active=False,
        )

        legacy = self.client.get(self.CATALOG_URL).json()['legacy_baselines']
        row = next(item for item in legacy if item['id'] == inactive.id)
        self.assertFalse(row['is_applied'])
        self.assertFalse(row['requires_adoption'])
        self.assertFalse(row['is_active'])

        self.assertEqual(
            self.client.post(
                f'/api/v1/planner-baselines/{inactive.id}/link/',
                {'analysis_detail_id': self.detail_later.id},
                format='json',
            ).status_code,
            200,
        )

        self.assertEqual(
            self.client.post(
                self.BATCH_URL,
                {
                    'revision': self.client.get(self.CATALOG_URL).json()['revision'],
                    'changes': [self._change(
                        self.detail_later,
                        recommend_min='2500',
                    )],
                },
                format='json',
            ).status_code,
            200,
        )
        inactive.refresh_from_db()
        untouched.refresh_from_db()
        self.assertTrue(inactive.is_active)
        self.assertEqual(
            inactive.baseline_source,
            PlannerBaseline.SOURCE_PLANNER,
        )
        self.assertIsNone(inactive.preset_origin)
        self.assertFalse(untouched.is_active)
        self.assertEqual(untouched.baseline_source, PlannerBaseline.SOURCE_PLANNER)
        self.assertEqual(untouched.preset_origin, 'leave-as-is')

    def test_ambiguous_legacy_row_can_be_explicitly_linked_or_deleted(self):
        duplicate = AnalysisDetail.objects.create(
            sub_category=self.detail_first.sub_category,
            name=self.detail_later.name,
            order=9,
        )
        linked = PlannerBaseline.objects.create(
            owner=self.user,
            analysis_detail=None,
            coverage_key=self.detail_later.name,
            product_group=PlannerBaseline.PRODUCT_GROUP_ALL,
            age_band=PlannerBaseline.AGE_ALL,
            gender=None,
            recommend_min=2500,
            baseline_source='planner',
        )
        deleted = PlannerBaseline.objects.create(
            owner=self.user,
            analysis_detail=None,
            coverage_key='연결하지 않을 기존 값',
            product_group=PlannerBaseline.PRODUCT_GROUP_ALL,
            age_band=PlannerBaseline.AGE_ALL,
            gender=None,
            recommend_min=1500,
            baseline_source='planner',
        )

        foreign_response = self.other_client.post(
            f'/api/v1/planner-baselines/{linked.id}/link/',
            {'analysis_detail_id': duplicate.id},
            format='json',
        )
        self.assertEqual(foreign_response.status_code, 404)
        linked.refresh_from_db()
        self.assertIsNone(linked.analysis_detail_id)

        link_response = self.client.post(
            f'/api/v1/planner-baselines/{linked.id}/link/',
            {'analysis_detail_id': duplicate.id},
            format='json',
        )
        self.assertEqual(link_response.status_code, 200, link_response.content)
        self.assertEqual(link_response.json()['revision'], 1)
        linked.refresh_from_db()
        self.assertEqual(linked.analysis_detail_id, duplicate.id)
        self.assertEqual(linked.coverage_key, duplicate.name)

        delete_response = self.client.delete(
            f'/api/v1/planner-baselines/{deleted.id}/')
        self.assertEqual(delete_response.status_code, 204)
        self.assertFalse(
            PlannerBaseline.objects.filter(pk=deleted.pk).exists())
        self.assertEqual(
            PlannerBaselineRevision.objects.get(owner=self.user).revision,
            2,
        )

    def test_batch_saves_multiple_changes_and_increments_revision_once(self):
        response = self.client.post(
            self.BATCH_URL,
            {
                'revision': 0,
                'changes': [
                    self._change(
                        self.detail_first,
                        recommend_min='7000',
                        recommend_max='10000',
                        owner_id=self.other_user.id,
                    ),
                    self._change(
                        self.detail_later,
                        age_band='30s',
                        gender=1,
                        recommend_min='3000',
                        unit=PlannerBaseline.UNIT_WON,
                    ),
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['revision'], 1)
        rows = list(
            PlannerBaseline.objects.filter(owner=self.user)
            .order_by('analysis_detail_id'))
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row.baseline_source == 'planner' for row in rows))
        self.assertTrue(all(row.owner_id == self.user.id for row in rows))
        self.assertEqual(
            {row.coverage_key for row in rows},
            {self.detail_first.name, self.detail_later.name},
        )
        self.assertEqual(
            PlannerBaselineRevision.objects.get(owner=self.user).revision, 1)
        self.assertEqual(
            PlannerBaseline.objects.filter(owner=self.other_user).count(), 1)

    def test_batch_creates_updates_and_deletes_indemnity_and_annuity_scopes(self):
        annuity = PlannerBaseline.objects.create(
            owner=self.user,
            analysis_detail=self.detail_later,
            coverage_key=self.detail_later.name,
            product_group=PlannerBaseline.PRODUCT_GROUP_ANNUITY,
            age_band='40s',
            gender=2,
            recommend_min=9000,
            unit=PlannerBaseline.UNIT_TEN_THOUSAND_WON,
            baseline_source='planner',
        )

        response = self.client.post(
            self.BATCH_URL,
            {
                'revision': 0,
                'changes': [
                    self._change(
                        self.detail_first,
                        product_group=PlannerBaseline.PRODUCT_GROUP_INDEMNITY,
                        age_band='30s',
                        gender=1,
                        recommend_min='7000',
                    ),
                    self._change(
                        self.detail_later,
                        product_group=PlannerBaseline.PRODUCT_GROUP_ANNUITY,
                        age_band='40s',
                        gender=2,
                        recommend_min=None,
                        recommend_max=None,
                    ),
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(PlannerBaseline.objects.filter(
            owner=self.user,
            analysis_detail=self.detail_first,
            product_group=PlannerBaseline.PRODUCT_GROUP_INDEMNITY,
            recommend_min=7000,
        ).exists())
        self.assertFalse(
            PlannerBaseline.objects.filter(pk=annuity.pk).exists())

    def test_both_null_amounts_delete_linked_scope_and_preserve_legacy_row(self):
        exact_legacy = PlannerBaseline.objects.create(
            owner=self.user,
            analysis_detail=None,
            coverage_key=self.detail_first.name,
            product_group=PlannerBaseline.PRODUCT_GROUP_ALL,
            age_band=PlannerBaseline.AGE_ALL,
            gender=None,
            recommend_min=4000,
            baseline_source='planner',
        )
        unrelated_legacy = PlannerBaseline.objects.create(
            owner=self.user,
            analysis_detail=None,
            coverage_key=self.detail_first.name,
            product_group=PlannerBaseline.PRODUCT_GROUP_ALL,
            age_band='30s',
            gender=None,
            recommend_min=4000,
            baseline_source='planner',
        )
        response = self.client.post(
            self.BATCH_URL,
            {
                'revision': 0,
                'changes': [
                    self._change(
                        self.detail_first,
                        recommend_min=None,
                        recommend_max=None,
                    ),
                    self._change(
                        self.detail_later,
                        recommend_min=None,
                        recommend_max=None,
                    ),
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['revision'], 1)
        self.assertFalse(
            PlannerBaseline.objects.filter(pk=self.owner_baseline.pk).exists())
        self.assertTrue(
            PlannerBaseline.objects.filter(pk=exact_legacy.pk).exists())
        self.assertTrue(
            PlannerBaseline.objects.filter(pk=unrelated_legacy.pk).exists())

    def test_batch_create_preserves_same_scope_legacy_rows(self):
        exact_legacy = PlannerBaseline.objects.create(
            owner=self.user,
            analysis_detail=None,
            coverage_key=self.detail_later.name,
            product_group=PlannerBaseline.PRODUCT_GROUP_ALL,
            age_band='30s',
            gender=1,
            recommend_min=2000,
            baseline_source='planner',
        )
        unrelated_legacy = PlannerBaseline.objects.create(
            owner=self.user,
            analysis_detail=None,
            coverage_key=self.detail_later.name,
            product_group=PlannerBaseline.PRODUCT_GROUP_ALL,
            age_band='40s',
            gender=1,
            recommend_min=2000,
            baseline_source='planner',
        )

        response = self.client.post(
            self.BATCH_URL,
            {
                'revision': 0,
                'changes': [self._change(
                    self.detail_later,
                    age_band='30s',
                    gender=1,
                    recommend_min='3000',
                )],
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(
            PlannerBaseline.objects.filter(pk=exact_legacy.pk).exists())
        self.assertTrue(
            PlannerBaseline.objects.filter(pk=unrelated_legacy.pk).exists())
        self.assertTrue(PlannerBaseline.objects.filter(
            owner=self.user,
            analysis_detail=self.detail_later,
            product_group=PlannerBaseline.PRODUCT_GROUP_ALL,
            age_band='30s',
            gender=1,
        ).exists())

    def test_batch_update_preserves_same_scope_legacy_rows(self):
        exact_legacy = PlannerBaseline.objects.create(
            owner=self.user,
            analysis_detail=None,
            coverage_key=self.detail_first.name,
            product_group=PlannerBaseline.PRODUCT_GROUP_ALL,
            age_band=PlannerBaseline.AGE_ALL,
            gender=None,
            recommend_min=4000,
            baseline_source='planner',
        )

        response = self.client.post(
            self.BATCH_URL,
            {
                'revision': 0,
                'changes': [self._change(
                    self.detail_first,
                    recommend_min='7000',
                )],
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(
            PlannerBaseline.objects.filter(pk=exact_legacy.pk).exists())
        self.owner_baseline.refresh_from_db()
        self.assertEqual(self.owner_baseline.recommend_min, 7000)

    def test_ten_change_batch_stays_within_query_ceiling(self):
        details = [
            AnalysisDetail.objects.create(
                sub_category=self.detail_first.sub_category,
                name=f'대량 저장 담보 {index}',
                order=10 + index,
            )
            for index in range(10)
        ]
        PlannerBaselineRevision.objects.create(owner=self.user, revision=0)

        with CaptureQueriesContext(connection) as queries:
            response = self.client.post(
                self.BATCH_URL,
                {
                    'revision': 0,
                    'changes': [
                        self._change(detail, recommend_min=str(1000 + index))
                        for index, detail in enumerate(details)
                    ],
                },
                format='json',
            )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertLessEqual(
            len(queries),
            12,
            '\n'.join(query['sql'] for query in queries.captured_queries),
        )
        self.assertEqual(
            PlannerBaseline.objects.filter(
                owner=self.user,
                analysis_detail__in=details,
            ).count(),
            10,
        )

    def test_stale_revision_returns_conflict_without_writing(self):
        PlannerBaselineRevision.objects.create(owner=self.user, revision=3)

        response = self.client.post(
            self.BATCH_URL,
            {
                'revision': 2,
                'changes': [
                    self._change(self.detail_later, recommend_min='3000'),
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(
            response.json()['code'], 'baseline_revision_conflict')
        self.assertEqual(
            PlannerBaselineRevision.objects.get(owner=self.user).revision, 3)
        self.assertFalse(
            PlannerBaseline.objects.filter(
                owner=self.user, analysis_detail=self.detail_later).exists())

    def test_missing_or_nonstandard_detail_rejects_the_whole_batch(self):
        for detail_id in (999999, self.nonstandard_detail.id):
            with self.subTest(detail_id=detail_id):
                response = self.client.post(
                    self.BATCH_URL,
                    {
                        'revision': 0,
                        'changes': [
                            self._change(
                                self.detail_later,
                                recommend_min='3000',
                            ),
                            {
                                **self._change(
                                    self.detail_first,
                                    recommend_min='4000',
                                ),
                                'analysis_detail_id': detail_id,
                            },
                        ],
                    },
                    format='json',
                )

                self.assertEqual(response.status_code, 400, response.content)
                self.assertFalse(
                    PlannerBaseline.objects.filter(
                        owner=self.user,
                        analysis_detail=self.detail_later,
                    ).exists())
                revision = PlannerBaselineRevision.objects.filter(
                    owner=self.user).first()
                self.assertTrue(revision is None or revision.revision == 0)

    def test_invalid_later_change_rolls_back_all_rows(self):
        response = self.client.post(
            self.BATCH_URL,
            {
                'revision': 0,
                'changes': [
                    self._change(self.detail_later, recommend_min='3000'),
                    self._change(
                        self.detail_later_category,
                        recommend_min='9000',
                        recommend_max='8000',
                    ),
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(
            PlannerBaseline.objects.filter(
                owner=self.user,
                analysis_detail__in=[
                    self.detail_later,
                    self.detail_later_category,
                ],
            ).exists())

    def test_unauthenticated_requests_are_blocked(self):
        client = APIClient()

        self.assertEqual(client.get(self.CATALOG_URL).status_code, 401)
        self.assertEqual(
            client.post(
                self.BATCH_URL,
                {'revision': 0, 'changes': []},
                format='json',
            ).status_code,
            401,
        )


class PlannerBaselineCatalogModelTests(TestCase):
    def setUp(self):
        self.user, _client = _make_planner('baseline-model@test.com')
        category = AnalysisCategory.objects.create(
            insurance_type=0, name='기준 대분류', order=1)
        sub_category = AnalysisSubCategory.objects.create(
            insurance_type=0, category=category, name='기준 중분류', order=1)
        self.detail = AnalysisDetail.objects.create(
            sub_category=sub_category, name='기준 담보', order=1)

    def _create(self, **overrides):
        values = {
            'owner': self.user,
            'analysis_detail': self.detail,
            'coverage_key': self.detail.name,
            'product_group': PlannerBaseline.PRODUCT_GROUP_ALL,
            'age_band': PlannerBaseline.AGE_ALL,
            'gender': None,
            'recommend_min': 5000,
            'unit': PlannerBaseline.UNIT_TEN_THOUSAND_WON,
            'baseline_source': 'planner',
        }
        values.update(overrides)
        return PlannerBaseline.objects.create(**values)

    def test_linked_detail_is_protected_from_deletion(self):
        self._create()

        with self.assertRaises(ProtectedError):
            self.detail.delete()

    def test_common_and_specific_gender_scopes_are_each_unique(self):
        self._create()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._create()

        self._create(gender=1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._create(gender=1)

    def test_unlinked_legacy_rows_remain_compatible(self):
        values = {
            'owner': self.user,
            'analysis_detail': None,
            'coverage_key': '기존 직접 입력',
            'product_group': PlannerBaseline.PRODUCT_GROUP_NONLIFE,
            'age_band': '30s',
            'gender': None,
            'recommend_min': 1000,
            'baseline_source': 'planner',
        }

        PlannerBaseline.objects.create(**values)
        PlannerBaseline.objects.create(**values)

        self.assertEqual(
            PlannerBaseline.objects.filter(
                owner=self.user, analysis_detail__isnull=True).count(),
            2,
        )

    def test_revision_is_one_per_owner_and_starts_at_zero(self):
        from inpa.customers.models import PlannerBaselineRevision

        revision = PlannerBaselineRevision.objects.create(owner=self.user)

        self.assertEqual(revision.revision, 0)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PlannerBaselineRevision.objects.create(owner=self.user)


class PlannerBaselineBackfillTests(TestCase):
    def setUp(self):
        self.user, _client = _make_planner('baseline-backfill@test.com')
        category = AnalysisCategory.objects.create(
            insurance_type=0, name='[표준]이관 대분류', order=1)
        sub_category = AnalysisSubCategory.objects.create(
            insurance_type=0, category=category, name='이관 중분류', order=1)
        self.unique_detail = AnalysisDetail.objects.create(
            sub_category=sub_category, name='유일 담보', order=1)
        self.ambiguous_details = [
            AnalysisDetail.objects.create(
                sub_category=sub_category, name='동명 담보', order=order)
            for order in (2, 3)
        ]
        nonstandard_category = AnalysisCategory.objects.create(
            insurance_type=0, name='[촬영]이관 대분류', order=2)
        self.nonstandard_sub_category = AnalysisSubCategory.objects.create(
            insurance_type=0,
            category=nonstandard_category,
            name='이관 중분류',
            order=1,
        )

    def _legacy_row(self, coverage_key, **overrides):
        values = {
            'owner': self.user,
            'analysis_detail': None,
            'coverage_key': coverage_key,
            'product_group': PlannerBaseline.PRODUCT_GROUP_ALL,
            'age_band': PlannerBaseline.AGE_ALL,
            'gender': None,
            'recommend_min': 5000,
            'recommend_max': None,
            'unit': PlannerBaseline.UNIT_TEN_THOUSAND_WON,
            'baseline_source': 'planner',
            'preset_origin': None,
            'is_active': True,
        }
        values.update(overrides)
        return PlannerBaseline.objects.create(**values)

    def _run_backfill(self):
        migration = importlib.import_module(
            'inpa.customers.migrations.0023_baseline_catalog_scope')
        from django.apps import apps

        migration.backfill_baseline_details(apps, None)

    def test_unique_names_link_ambiguous_names_stay_null_and_identical_duplicates_collapse(self):
        oldest = self._legacy_row('유일 담보')
        duplicate = self._legacy_row('유일 담보')
        ambiguous = self._legacy_row('동명 담보')
        unmatched = self._legacy_row('매칭 없는 담보')

        self._run_backfill()

        oldest.refresh_from_db()
        ambiguous.refresh_from_db()
        unmatched.refresh_from_db()
        self.assertEqual(oldest.analysis_detail_id, self.unique_detail.id)
        self.assertFalse(PlannerBaseline.objects.filter(pk=duplicate.pk).exists())
        self.assertIsNone(ambiguous.analysis_detail_id)
        self.assertIsNone(unmatched.analysis_detail_id)

    def test_conflicting_common_duplicates_fail_without_partial_backfill(self):
        first = self._legacy_row('유일 담보', recommend_min=5000)
        second = self._legacy_row('유일 담보', recommend_min=7000)

        with self.assertRaises(RuntimeError), transaction.atomic():
            self._run_backfill()

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertIsNone(first.analysis_detail_id)
        self.assertIsNone(second.analysis_detail_id)

    def test_nonstandard_only_exact_name_stays_unlinked(self):
        AnalysisDetail.objects.create(
            sub_category=self.nonstandard_sub_category,
            name='촬영 전용 담보',
            order=1,
        )
        legacy = self._legacy_row('촬영 전용 담보')

        self._run_backfill()

        legacy.refresh_from_db()
        self.assertIsNone(legacy.analysis_detail_id)

    def test_one_standard_and_one_nonstandard_name_links_standard_detail(self):
        AnalysisDetail.objects.create(
            sub_category=self.nonstandard_sub_category,
            name=self.unique_detail.name,
            order=1,
        )
        legacy = self._legacy_row(self.unique_detail.name)

        self._run_backfill()

        legacy.refresh_from_db()
        self.assertEqual(legacy.analysis_detail_id, self.unique_detail.id)

    def test_duplicate_name_within_standard_tree_stays_unlinked(self):
        legacy = self._legacy_row('동명 담보')

        self._run_backfill()

        legacy.refresh_from_db()
        self.assertIsNone(legacy.analysis_detail_id)


@POSTGRES_ONLY
class PlannerBaselinePostgresConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.user, _client = _make_planner('baseline-pg-race@test.com')
        category = AnalysisCategory.objects.create(
            insurance_type=0, name='[표준]경합', order=1)
        sub_category = AnalysisSubCategory.objects.create(
            insurance_type=0, category=category, name='경합', order=1)
        self.details = [
            AnalysisDetail.objects.create(
                sub_category=sub_category,
                name=f'경합 담보 {index}',
                order=index,
            )
            for index in (1, 2)
        ]

    @staticmethod
    def _change(detail_id):
        return {
            'analysis_detail_id': detail_id,
            'product_group': PlannerBaseline.PRODUCT_GROUP_ALL,
            'age_band': PlannerBaseline.AGE_ALL,
            'gender': None,
            'recommend_min': '5000',
            'recommend_max': None,
            'unit': PlannerBaseline.UNIT_TEN_THOUSAND_WON,
        }

    def test_two_first_batch_requests_serialize_to_success_and_stale_conflict(self):
        barrier = threading.Barrier(2)

        def post(detail_id):
            def request():
                barrier.wait(timeout=5)
                client = APIClient()
                client.force_authenticate(user=self.user)
                return client.post(
                    '/api/v1/planner-baselines/batch/',
                    {
                        'revision': 0,
                        'changes': [self._change(detail_id)],
                    },
                    format='json',
                )

            return _thread_database_call(request)

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(
                post,
                [detail.id for detail in self.details],
            ))

        self.assertEqual(
            sorted(response.status_code for response in responses),
            [200, 409],
        )
        conflict = next(
            response for response in responses
            if response.status_code == 409)
        self.assertEqual(
            conflict.json()['code'], 'baseline_revision_conflict')
        self.assertEqual(
            PlannerBaselineRevision.objects.get(owner=self.user).revision, 1)
        self.assertEqual(
            PlannerBaseline.objects.filter(owner=self.user).count(), 1)

    def _assert_partial_unique_allows_only_one_concurrent_insert(self, gender):
        barrier = threading.Barrier(2)

        def insert(amount):
            def write():
                barrier.wait(timeout=5)
                try:
                    with transaction.atomic():
                        PlannerBaseline.objects.create(
                            owner_id=self.user.id,
                            analysis_detail_id=self.details[0].id,
                            coverage_key=self.details[0].name,
                            product_group=PlannerBaseline.PRODUCT_GROUP_ALL,
                            age_band=PlannerBaseline.AGE_ALL,
                            gender=gender,
                            recommend_min=amount,
                            baseline_source='planner',
                        )
                    return 'created'
                except IntegrityError:
                    return 'conflict'

            return _thread_database_call(write)

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(insert, (5000, 7000)))

        self.assertEqual(sorted(outcomes), ['conflict', 'created'])
        self.assertEqual(
            PlannerBaseline.objects.filter(
                owner=self.user,
                analysis_detail=self.details[0],
                product_group=PlannerBaseline.PRODUCT_GROUP_ALL,
                age_band=PlannerBaseline.AGE_ALL,
                gender=gender,
            ).count(),
            1,
        )

    def test_common_gender_partial_unique_allows_only_one_concurrent_insert(self):
        self._assert_partial_unique_allows_only_one_concurrent_insert(None)

    def test_specific_gender_partial_unique_allows_only_one_concurrent_insert(self):
        self._assert_partial_unique_allows_only_one_concurrent_insert(1)


class SalesStageTests(TestCase):
    """영업 단계(칸반/퍼널) — 기본값·PATCH 단계이동·목록 노출·owner 격리."""

    def setUp(self):
        self.user_a, self.client_a = _make_planner('sa@test.com')
        self.user_b, self.client_b = _make_planner('sb@test.com')

    def test_default_stage_is_db(self):
        r = self.client_a.post('/api/v1/customers/', {'name': '신규리드'}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()['sales_stage'], Customer.STAGE_DB)

    def test_patch_moves_stage(self):
        cust = Customer.objects.create(owner=self.user_a, name='이동대상')
        r = self.client_a.patch(f'/api/v1/customers/{cust.id}/',
                                {'sales_stage': Customer.STAGE_MEETING}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['sales_stage'], Customer.STAGE_MEETING)
        cust.refresh_from_db()
        self.assertEqual(cust.sales_stage, Customer.STAGE_MEETING)

    def test_invalid_stage_rejected(self):
        cust = Customer.objects.create(owner=self.user_a, name='검증')
        r = self.client_a.patch(f'/api/v1/customers/{cust.id}/',
                                {'sales_stage': 'bogus'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_stage_in_list_serializer(self):
        Customer.objects.create(owner=self.user_a, name='목록', sales_stage=Customer.STAGE_CONTACT)
        r = self.client_a.get('/api/v1/customers/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['results'][0]['sales_stage'], Customer.STAGE_CONTACT)

    def test_cannot_move_others_customer(self):
        cust_b = Customer.objects.create(owner=self.user_b, name='B고객')
        r = self.client_a.patch(f'/api/v1/customers/{cust_b.id}/',
                                {'sales_stage': Customer.STAGE_CONTRACT}, format='json')
        self.assertEqual(r.status_code, 404)
        cust_b.refresh_from_db()
        self.assertEqual(cust_b.sales_stage, Customer.STAGE_DB)


class ConsentTokenScopeTests(TestCase):
    """토큰 다목적화 + 하위호환 + personal_info scope."""

    def setUp(self):
        self.user, self.client = _make_planner('tok@test.com')
        self.customer = Customer.objects.create(owner=self.user, name='김보장')

    def test_personal_info_scope_exists(self):
        self.assertEqual(ConsentLog.SCOPE_PERSONAL_INFO, 'personal_info')
        self.assertIn('personal_info', dict(ConsentLog.SCOPE_CHOICES))

    def test_token_roundtrip_with_scopes(self):
        tok = make_consent_token(self.customer, scopes=['personal_info', 'marketing'])
        data = read_consent_token(tok)
        self.assertEqual(data['pk'], self.customer.pk)
        self.assertEqual(set(data['scopes']), {'personal_info', 'marketing'})

    def test_token_default_scope_is_overseas(self):
        data = read_consent_token(make_consent_token(self.customer))
        self.assertEqual(data['scopes'], ['overseas_medical'])

    def test_legacy_int_token_backward_compat(self):
        from .tokens import CONSENT_SALT
        legacy = signing.dumps(self.customer.pk, salt=CONSENT_SALT)  # 구 형식: pk(int) 직접
        data = read_consent_token(legacy)
        self.assertEqual(data['pk'], self.customer.pk)
        self.assertEqual(data['scopes'], ['overseas_medical'])


class PublicConsentMultiScopeTests(TestCase):
    """공개 /c 다항목 동의 — 개인정보(필수)+마케팅(선택)."""

    def setUp(self):
        cache.clear()  # throttle 격리
        self.user, _ = _make_planner('pc@test.com')
        self.customer = Customer.objects.create(owner=self.user, name='김보장')
        self.anon = APIClient()  # 비인증(공개 경로)

    def _token(self, scopes):
        return make_consent_token(self.customer, scopes=scopes)

    def test_get_returns_requested_items(self):
        tok = self._token(['personal_info', 'marketing'])
        r = self.anon.get(f'/api/v1/c/{tok}/')
        self.assertEqual(r.status_code, 200)
        scopes = [it['scope'] for it in r.json()['items']]
        self.assertEqual(scopes, ['personal_info', 'marketing'])
        pi = next(it for it in r.json()['items'] if it['scope'] == 'personal_info')
        self.assertTrue(pi['required'])

    def test_post_agreed_creates_customer_self_logs(self):
        tok = self._token(['personal_info', 'marketing'])
        r = self.anon.post(f'/api/v1/c/{tok}/',
                           {'agreed': ['personal_info', 'marketing']}, format='json')
        self.assertEqual(r.status_code, 201)
        logs = ConsentLog.objects.filter(customer=self.customer)
        self.assertEqual(logs.count(), 2)
        self.assertTrue(all(l.subject == ConsentLog.SUBJECT_CUSTOMER_SELF for l in logs))

    def test_post_missing_required_returns_412(self):
        tok = self._token(['personal_info', 'marketing'])
        r = self.anon.post(f'/api/v1/c/{tok}/',
                           {'agreed': ['marketing']}, format='json')  # 필수 누락
        self.assertEqual(r.status_code, 412)
        self.assertEqual(ConsentLog.objects.filter(customer=self.customer).count(), 0)

    def test_overseas_token_sets_snapshot(self):
        tok = self._token(['overseas_medical'])
        r = self.anon.post(f'/api/v1/c/{tok}/',
                           {'agreed': ['overseas_medical']}, format='json')
        self.assertEqual(r.status_code, 201)
        self.customer.refresh_from_db()
        self.assertIsNotNone(self.customer.consent_overseas_at)

    def test_post_ignores_scope_not_in_token(self):
        """위조 방지 — 토큰에 없는 scope를 agreed에 넣어도 무시된다."""
        tok = self._token(['overseas_medical'])
        r = self.anon.post(f'/api/v1/c/{tok}/',
                           {'agreed': ['overseas_medical', 'personal_info']}, format='json')
        self.assertEqual(r.status_code, 201)
        scopes = set(ConsentLog.objects.filter(customer=self.customer)
                     .values_list('scope', flat=True))
        self.assertEqual(scopes, {'overseas_medical'})  # 토큰 밖 personal_info는 무시됨


class ConsultationRecordingConsentTests(TestCase):
    """상담 녹음은 고객 본인의 최신 필수 동의 2종이 모두 있어야 한다."""

    def setUp(self):
        cache.clear()
        self.user, self.client = _make_planner('recording-consent@test.com')
        self.customer = Customer.objects.create(owner=self.user, name='김보장')
        self.anon = APIClient()
        self.scopes = [
            ConsentLog.SCOPE_CONSULTATION_RECORDING,
            ConsentLog.SCOPE_CONSULTATION_SENSITIVE,
        ]

    def test_public_disclosure_marks_both_required_and_explains_thirty_day_retention(self):
        token = make_consent_token(self.customer, scopes=self.scopes)

        response = self.anon.get(f'/api/v1/c/{token}/')

        self.assertEqual(response.status_code, 200)
        items = response.json()['items']
        self.assertEqual([item['scope'] for item in items], self.scopes)
        self.assertTrue(all(item['required'] for item in items))
        recording = items[0]
        self.assertIn('30일', ' '.join(recording['lines']))

    def test_openai_summary_disclosure_explains_raw_audio_transfer_and_masking(self):
        token = make_consent_token(
            self.customer,
            scopes=[ConsentLog.SCOPE_CONSULTATION_OVERSEAS_SUMMARY],
        )

        response = self.anon.get(f'/api/v1/c/{token}/')

        self.assertEqual(response.status_code, 200)
        item = response.json()['items'][0]
        disclosure = ' '.join(item['lines'])
        self.assertIn('상담 음성', disclosure)
        self.assertIn('OpenAI', disclosure)
        self.assertIn('이름과 연락처를 가리고', disclosure)
        self.assertIn('최대 30일', disclosure)

    def test_old_recording_consent_is_immutable_and_cannot_open_new_gate(self):
        old_recording = ConsentLog.objects.create(
            customer=self.customer,
            scope=ConsentLog.SCOPE_CONSULTATION_RECORDING,
            subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
            doc_version='v1-2026-07-22',
        )
        ConsentLog.objects.create(
            customer=self.customer,
            scope=ConsentLog.SCOPE_CONSULTATION_SENSITIVE,
            subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
            doc_version=CONSULTATION_CONSENT_VERSIONS[
                ConsentLog.SCOPE_CONSULTATION_SENSITIVE
            ],
        )

        self.assertFalse(has_current_consultation_recording_consent(self.customer))
        token = make_consent_token(
            self.customer,
            scopes=[ConsentLog.SCOPE_CONSULTATION_RECORDING],
        )
        response = self.anon.post(
            f'/api/v1/c/{token}/',
            {'agreed': [ConsentLog.SCOPE_CONSULTATION_RECORDING]},
            format='json',
        )

        self.assertEqual(response.status_code, 201, response.content)
        old_recording.refresh_from_db()
        self.assertEqual(old_recording.doc_version, 'v1-2026-07-22')
        self.assertIsNone(old_recording.revoked_at)
        self.assertTrue(has_current_consultation_recording_consent(self.customer))
        self.assertEqual(
            ConsentLog.objects.filter(
                customer=self.customer,
                scope=ConsentLog.SCOPE_CONSULTATION_RECORDING,
            ).count(),
            2,
        )

    def test_public_revocation_locks_customer_before_mutating_consents(self):
        for scope in self.scopes:
            ConsentLog.objects.create(
                customer=self.customer,
                scope=scope,
                subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
                doc_version=CONSULTATION_CONSENT_VERSIONS[scope],
            )
        token = make_consent_token(
            self.customer,
            scopes=[ConsentLog.SCOPE_CONSULTATION_RECORDING],
        )
        order = []

        select_for_update = Customer.objects.select_for_update

        def lock_customer():
            order.append('customer_lock_requested')
            return select_for_update()

        from .public_consent import PublicConsentView
        apply_revocations = PublicConsentView._apply_revocations

        def apply_after_lock(view, *args, **kwargs):
            order.append('consents_mutated')
            return apply_revocations(view, *args, **kwargs)

        with (
            mock.patch(
                'inpa.customers.consent_texts.Customer.objects.select_for_update',
                side_effect=lock_customer,
            ) as customer_lock,
            mock.patch.object(
                PublicConsentView,
                '_apply_revocations',
                new=apply_after_lock,
            ),
        ):
            response = self.anon.post(
                f'/api/v1/c/{token}/',
                {'revoked': [ConsentLog.SCOPE_CONSULTATION_RECORDING]},
                format='json',
            )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(order, ['customer_lock_requested', 'consents_mutated'])
        customer_lock.assert_called_once_with()
        self.assertFalse(
            has_current_consultation_recording_consent(self.customer),
        )

    def test_customer_self_consent_to_both_scopes_opens_gate_with_current_version(self):
        token = make_consent_token(self.customer, scopes=self.scopes)

        response = self.anon.post(
            f'/api/v1/c/{token}/',
            {'agreed': self.scopes},
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(has_current_consultation_recording_consent(self.customer))
        versions = set(
            ConsentLog.objects.filter(customer=self.customer, scope__in=self.scopes)
            .values_list('doc_version', flat=True)
        )
        self.assertEqual(versions, set(CONSULTATION_CONSENT_VERSIONS.values()))

    def test_planner_attestation_or_one_scope_cannot_open_gate(self):
        ConsentLog.objects.create(
            customer=self.customer,
            scope=ConsentLog.SCOPE_CONSULTATION_RECORDING,
            subject=ConsentLog.SUBJECT_PLANNER_ATTESTED,
            doc_version=CONSULTATION_CONSENT_VERSIONS[
                ConsentLog.SCOPE_CONSULTATION_RECORDING
            ],
        )
        ConsentLog.objects.create(
            customer=self.customer,
            scope=ConsentLog.SCOPE_CONSULTATION_SENSITIVE,
            subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
            doc_version=CONSULTATION_CONSENT_VERSIONS[
                ConsentLog.SCOPE_CONSULTATION_SENSITIVE
            ],
        )

        self.assertFalse(has_current_consultation_recording_consent(self.customer))

    def test_revoking_either_scope_closes_gate(self):
        for scope in self.scopes:
            ConsentLog.objects.create(
                customer=self.customer,
                scope=scope,
                subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
                doc_version=CONSULTATION_CONSENT_VERSIONS[scope],
            )
        self.assertTrue(has_current_consultation_recording_consent(self.customer))
        ConsentLog.objects.filter(
            customer=self.customer,
            scope=ConsentLog.SCOPE_CONSULTATION_SENSITIVE,
        ).update(revoked_at=timezone.now())

        self.assertFalse(has_current_consultation_recording_consent(self.customer))

    def test_planner_can_create_request_for_both_recording_scopes(self):
        response = self.client.post(
            f'/api/v1/customers/{self.customer.id}/consent-requests/',
            {'scopes': self.scopes},
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(read_consent_token(response.json()['token'])['scopes'], self.scopes)


class ConsentRequestScopeTests(TestCase):
    def setUp(self):
        self.user, self.client = _make_planner('cr@test.com')
        self.customer = Customer.objects.create(owner=self.user, name='김보장')

    def test_default_scope_overseas(self):
        r = self.client.post(f'/api/v1/customers/{self.customer.id}/consent-requests/',
                             {}, format='json')
        self.assertEqual(r.status_code, 201)
        data = read_consent_token(r.json()['token'])
        self.assertEqual(data['scopes'], ['overseas_medical'])

    def test_custom_scopes_encoded(self):
        r = self.client.post(f'/api/v1/customers/{self.customer.id}/consent-requests/',
                             {'scopes': ['personal_info', 'marketing']}, format='json')
        self.assertEqual(r.status_code, 201)
        data = read_consent_token(r.json()['token'])
        self.assertEqual(set(data['scopes']), {'personal_info', 'marketing'})

    def test_unknown_scope_rejected(self):
        r = self.client.post(f'/api/v1/customers/{self.customer.id}/consent-requests/',
                             {'scopes': ['hacker']}, format='json')
        self.assertEqual(r.status_code, 400)


class ConsentSerializerTests(TestCase):
    def setUp(self):
        self.user, self.client = _make_planner('ser@test.com')
        self.customer = Customer.objects.create(owner=self.user, name='김보장')

    def test_list_has_personal_info_consent_none(self):
        r = self.client.get('/api/v1/customers/')
        row = next(c for c in r.json()['results'] if c['id'] == self.customer.id)
        self.assertEqual(row['personal_info_consent'], 'none')

    def test_detail_consents_reflect_logs(self):
        ConsentLog.objects.create(customer=self.customer,
                                  scope=ConsentLog.SCOPE_PERSONAL_INFO,
                                  subject=ConsentLog.SUBJECT_CUSTOMER_SELF)
        ConsentLog.objects.create(customer=self.customer,
                                  scope=ConsentLog.SCOPE_MARKETING,
                                  subject=ConsentLog.SUBJECT_PLANNER_ATTESTED)
        r = self.client.get(f'/api/v1/customers/{self.customer.id}/')
        consents = r.json()['consents']
        self.assertEqual(consents['personal_info']['status'], 'agreed')
        self.assertEqual(consents['personal_info']['subject'], 'customer_self')
        self.assertEqual(consents['marketing']['subject'], 'planner_attested')


class DdayAutoUpdateTests(TestCase):
    """D-Day 자동갱신: substantive 필드 PATCH → last_contacted_at 갱신. is_favorite/is_pinned만 → 불변."""

    def setUp(self):
        self.user, self.client = _make_planner('dday@test.com')
        self.cust = Customer.objects.create(
            owner=self.user,
            name='테스트고객',
            mobile_phone_number='010-0000-0000',
            last_contacted_at=None,
        )

    def test_substantive_patch_updates_last_contacted_at(self):
        """이름 수정 → last_contacted_at이 ~now로 갱신된다."""
        before = timezone.now()
        r = self.client.patch(
            f'/api/v1/customers/{self.cust.id}/',
            {'name': '수정 고객'},
            format='json',
        )
        self.assertEqual(r.status_code, 200)
        self.cust.refresh_from_db()
        self.assertIsNotNone(self.cust.last_contacted_at)
        self.assertGreaterEqual(self.cust.last_contacted_at, before)

    def test_non_substantive_patch_does_not_update_last_contacted_at(self):
        """is_favorite만 PATCH → last_contacted_at 불변."""
        original_ts = self.cust.last_contacted_at  # None
        r = self.client.patch(
            f'/api/v1/customers/{self.cust.id}/',
            {'is_favorite': True},
            format='json',
        )
        self.assertEqual(r.status_code, 200)
        self.cust.refresh_from_db()
        self.assertEqual(self.cust.last_contacted_at, original_ts)

    def test_patch_sales_stage_meeting_sets_fa_reached_at_once(self):
        """칸반 FA 이동(PATCH sales_stage=meeting) → fa_reached_at 기록, 재이동엔 불변."""
        self.assertIsNone(self.cust.fa_reached_at)
        r = self.client.patch(f'/api/v1/customers/{self.cust.id}/',
                             {'sales_stage': 'meeting'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.cust.refresh_from_db()
        self.assertIsNotNone(self.cust.fa_reached_at)
        first = self.cust.fa_reached_at
        # 청약 → 다시 FA: 최초 시각 보존(중복 카운트 방지)
        self.client.patch(f'/api/v1/customers/{self.cust.id}/', {'sales_stage': 'contract'}, format='json')
        self.client.patch(f'/api/v1/customers/{self.cust.id}/', {'sales_stage': 'meeting'}, format='json')
        self.cust.refresh_from_db()
        self.assertEqual(self.cust.fa_reached_at, first)


class JobSearchTests(TestCase):
    """직업급수 검색(전역 마스터) + 고객 job_code 적용."""

    def setUp(self):
        self.user, self.client = _make_planner('job@test.com')
        self.doctor = JobRiskCode.objects.create(
            sctg_cd='1110', name='의사', risk_grade=1, kidi_cd='011')
        self.council = JobRiskCode.objects.create(
            sctg_cd='1501', name='의회의원/공공단체임원', risk_grade=1,
            synonym='지방의회의원|시의원|도의원|구의원')

    def test_name_match_ranked_first(self):
        r = self.client.get('/api/v1/jobs/search/?q=의사')
        self.assertEqual(r.status_code, 200)
        results = r.data['results']
        self.assertTrue(results)
        self.assertEqual(results[0]['name'], '의사')
        self.assertEqual(results[0]['risk_grade'], 1)
        self.assertEqual(results[0]['risk_grade_label'], '1급')

    def test_synonym_match(self):
        """검색어(synonym)에만 있는 '시의원' 으로 의회의원 매칭."""
        r = self.client.get('/api/v1/jobs/search/?q=시의원')
        self.assertEqual(r.status_code, 200)
        names = [j['name'] for j in r.data['results']]
        self.assertIn('의회의원/공공단체임원', names)

    def test_empty_query_empty_results(self):
        r = self.client.get('/api/v1/jobs/search/?q=')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['results'], [])

    def test_requires_auth(self):
        anon = APIClient()
        r = anon.get('/api/v1/jobs/search/?q=의사')
        self.assertIn(r.status_code, (401, 403))

    def test_customer_job_code_apply(self):
        """검색 결과 id 를 job_code 로 고객 생성 → 직렬화에 job_risk_grade 반영."""
        r = self.client.post('/api/v1/customers/',
                             {'name': '김보장', 'job_code': self.doctor.id}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        cust = Customer.objects.get(pk=r.data['id'])
        self.assertEqual(cust.job_code_id, self.doctor.id)
        detail = self.client.get(f'/api/v1/customers/{cust.id}/')
        self.assertEqual(detail.data['job_risk_grade'], 1)
        self.assertEqual(detail.data['job_name'], '의사')


class ContactLogTests(TestCase):
    """접촉 결과 로그 — 생성 시 last_contacted_at 갱신, owner 격리, append-only."""

    def setUp(self):
        self.user_a, self.client_a = _make_planner('contact_a@test.com')
        self.user_b, self.client_b = _make_planner('contact_b@test.com')
        self.customer = Customer.objects.create(owner=self.user_a, name='접촉고객')

    def _url(self, cid=None):
        return f'/api/v1/customers/{cid or self.customer.id}/contact-logs/'

    def test_create_bumps_last_contacted(self):
        self.assertIsNone(self.customer.last_contacted_at)
        r = self.client_a.post(self._url(), {'result': 'no_answer', 'memo': '부재중'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.json()['result'], 'no_answer')
        self.assertEqual(r.json()['result_display'], '부재중')
        self.customer.refresh_from_db()
        self.assertIsNotNone(self.customer.last_contacted_at)  # 방치 경보 리셋

    def test_list_returns_own_logs(self):
        self.client_a.post(self._url(), {'result': 'connected'}, format='json')
        self.client_a.post(self._url(), {'result': 'appointment', 'memo': '내일 2시'}, format='json')
        body = self.client_a.get(self._url()).json()
        results = body['results'] if isinstance(body, dict) and 'results' in body else body
        self.assertEqual(len(results), 2)

    def test_owner_isolation(self):
        # B가 A의 고객에 접촉로그 시도 → 404(존재 은폐)
        r = self.client_b.post(self._url(), {'result': 'connected'}, format='json')
        self.assertEqual(r.status_code, 404)

    def test_append_only_no_delete(self):
        r = self.client_a.post(self._url(), {'result': 'hold'}, format='json')
        log_id = r.json()['id']
        rd = self.client_a.delete(f'{self._url()}{log_id}/')
        self.assertIn(rd.status_code, (404, 405))  # detail 라우트 미등록 + append-only


class CustomerBulkCreateTests(TestCase):
    """고객 일괄 등록 — 중복(이름+연락처) 건너뛰기, 이름 없는 행 무시, db 단계."""

    def setUp(self):
        self.user, self.client = _make_planner('bulk@test.com')

    def test_bulk_create_with_dedup(self):
        Customer.objects.create(owner=self.user, name='기존', mobile_phone_number='010-1')
        body = {'customers': [
            {'name': '김민수', 'mobile_phone_number': '010-1234-5678'},
            {'name': '기존', 'mobile_phone_number': '010-1'},                  # 기존 중복 → skip
            {'name': '김민수', 'mobile_phone_number': '010-1234-5678'},        # 배치 내 중복 → skip
            {'name': '', 'mobile_phone_number': '010-9'},                      # 이름 없음 → skip
            {'name': '이영희'},
        ]}
        r = self.client.post('/api/v1/customers/bulk/', body, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.json()['created'], 2)   # 김민수, 이영희
        self.assertEqual(r.json()['skipped'], 3)
        self.assertEqual(Customer.objects.filter(owner=self.user).count(), 3)  # 기존1 + 신규2
        new = Customer.objects.get(name='이영희')
        self.assertEqual(new.sales_stage, 'db')
        self.assertEqual(new.lead_source, 'direct')

    def test_bulk_empty_rejected(self):
        r = self.client.post('/api/v1/customers/bulk/', {'customers': []}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_bulk_create_full_fields(self):
        """일괄 등록도 성별·생년월일·직업급수·유입경로·메모·아바타를 행별로 반영."""
        job = JobRiskCode.objects.create(sctg_cd='D01', name='의사', risk_grade=1)
        body = {'customers': [
            {
                'name': '김보장', 'mobile_phone_number': '010-1111-2222',
                'gender': '1', 'birth_day': '1990-05-15',
                'job_code': str(job.id), 'lead_source': 'introduction',
                'memo': '지인 소개', 'avatar_label': 'KB', 'color': '#F8D7DD',
            },
            {
                'name': '이영희',
                'gender': '2',
                'job_code': '99999',          # 존재하지 않는 직업 id → 무시(None)
                'lead_source': 'weird',        # 잘못된 유입 → direct 폴백
            },
        ]}
        r = self.client.post('/api/v1/customers/bulk/', body, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.json()['created'], 2)

        a = Customer.objects.get(name='김보장')
        self.assertEqual(a.gender, 1)
        self.assertEqual(a.birth_day, '1990-05-15')
        self.assertEqual(a.job_code_id, job.id)
        self.assertEqual(a.lead_source, 'introduction')
        self.assertEqual(a.memo, '지인 소개')
        self.assertEqual(a.avatar_label, 'KB')
        self.assertEqual(a.color, '#F8D7DD')

        b = Customer.objects.get(name='이영희')
        self.assertEqual(b.gender, 2)
        self.assertIsNone(b.job_code_id)          # 없는 id → None
        self.assertEqual(b.lead_source, 'direct')  # 잘못된 값 → 폴백


class ConsentTextsEndpointTests(TestCase):
    """★ LB-2: 공개 동의 고지문 단일 소스 GET /consent-texts/."""

    def setUp(self):
        cache.clear()  # share_public ScopedRateThrottle 카운터 격리
        self.public = APIClient()

    def test_returns_version_and_all_scopes(self):
        r = self.public.get('/api/v1/consent-texts/')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body['version'], CONSENT_TEXTS_VERSION)
        texts = body['texts']
        for scope in ('overseas_medical', 'personal_info', 'third_party', 'marketing'):
            self.assertIn(scope, texts)
            self.assertIn('title', texts[scope])
            self.assertIn('body', texts[scope])
            self.assertIn('retention', texts[scope])

    def test_overseas_retention_wording_corrected(self):
        """옛 '즉시 삭제' 문구는 사라지고 Anthropic 정책 문구가 들어간다."""
        r = self.public.get('/api/v1/consent-texts/')
        overseas = r.json()['texts']['overseas_medical']['retention']
        self.assertNotIn('즉시 삭제', overseas)
        self.assertIn('Anthropic', overseas)
        # 전체 응답에도 옛 문구가 없어야 함
        self.assertNotIn('즉시 삭제', r.content.decode())


class SeedJobsMarkerTests(TestCase):
    """LB-1 시드 안전화: seed_jobs 버전 마커 — 2회차 no-op, --force 우회."""

    def _tiny_file(self):
        import json
        import tempfile
        rows = [{'sctg_cd': 'S01', 'name': '테스트직업', 'risk_grade': 1}]
        f = tempfile.NamedTemporaryFile(
            'w', suffix='.json', delete=False, encoding='utf-8')
        json.dump(rows, f)
        f.close()
        return f.name

    def test_marker_skips_second_run_force_bypasses(self):
        from io import StringIO

        from django.core.management import call_command

        from inpa.analysis.models import SeedMarker
        from inpa.customers.management.commands import seed_jobs as seed_jobs_mod
        from inpa.customers.models import JobRiskCode

        path = self._tiny_file()
        call_command('seed_jobs', '--file', path, stdout=StringIO())
        self.assertEqual(JobRiskCode.objects.count(), 1)
        self.assertEqual(
            SeedMarker.objects.get(key=seed_jobs_mod.MARKER_KEY).version,
            seed_jobs_mod.SEED_VERSION)

        # 2회차: 마커 최신 → no-op (파일 SSOT prune 로직도 실행 안 됨)
        out = StringIO()
        call_command('seed_jobs', '--file', path, stdout=out)
        self.assertIn('이미 최신', out.getvalue())

        # --force: 실제 실행 (upsert + 파일 SSOT 동기화 의미 유지)
        out2 = StringIO()
        call_command('seed_jobs', '--file', path, '--force', stdout=out2)
        self.assertIn('직업급수 시드 완료', out2.getvalue())
        self.assertEqual(JobRiskCode.objects.count(), 1)


class PublicConsentRevocationTests(TestCase):
    """공개 /c 동의 철회(LB#10) — revocable 노출, revoked[] 스탬프, 게이트·스냅샷 정합."""

    def setUp(self):
        cache.clear()  # throttle 격리
        self.user, _ = _make_planner('rv@test.com')
        self.customer = Customer.objects.create(owner=self.user, name='김철회')
        self.anon = APIClient()

    def _token(self, scopes):
        return make_consent_token(self.customer, scopes=scopes)

    def test_get_marks_agreed_scope_revocable(self):
        """동의된 scope는 revocable=true, 기록 없는 scope는 false."""
        ConsentLog.objects.create(
            customer=self.customer, scope=ConsentLog.SCOPE_MARKETING,
            subject=ConsentLog.SUBJECT_CUSTOMER_SELF, doc_version=CONSENT_TEXTS_VERSION)
        tok = self._token(['marketing', 'personal_info'])
        r = self.anon.get(f'/api/v1/c/{tok}/')
        self.assertEqual(r.status_code, 200)
        items = {it['scope']: it for it in r.json()['items']}
        self.assertTrue(items['marketing']['revocable'])
        self.assertFalse(items['personal_info']['revocable'])

    def test_post_revoked_stamps_all_unrevoked_logs_incl_planner_attested(self):
        """철회 = 해당 scope의 모든 unrevoked 로그(subject 불문) revoked_at 스탬프."""
        ConsentLog.objects.create(
            customer=self.customer, scope=ConsentLog.SCOPE_MARKETING,
            subject=ConsentLog.SUBJECT_CUSTOMER_SELF)
        ConsentLog.objects.create(
            customer=self.customer, scope=ConsentLog.SCOPE_MARKETING,
            subject=ConsentLog.SUBJECT_PLANNER_ATTESTED)
        tok = self._token(['marketing'])
        r = self.anon.post(f'/api/v1/c/{tok}/', {'revoked': ['marketing']}, format='json')
        self.assertEqual(r.status_code, 200)
        logs = ConsentLog.objects.filter(customer=self.customer,
                                         scope=ConsentLog.SCOPE_MARKETING)
        self.assertEqual(logs.count(), 2)
        self.assertTrue(all(l.revoked_at is not None for l in logs))
        # 재철회 멱등 — 추가 스탬프 없음, 응답 정상
        r2 = self.anon.post(f'/api/v1/c/{tok}/', {'revoked': ['marketing']}, format='json')
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()['revoked'][0]['updated_logs'], 0)

    @override_settings(ANTHROPIC_API_KEY='test-key')
    def test_overseas_revoke_closes_ocr_gate_with_missing_reason(self):
        """국외이전 철회 → 스냅샷(consent_overseas_at)도 비워져 OCR 게이트 412 reason=missing."""
        _grant_overseas(self.customer)
        self.assertTrue(has_current_overseas_consent(self.customer))
        tok = self._token(['overseas_medical'])
        r = self.anon.post(f'/api/v1/c/{tok}/', {'revoked': ['overseas_medical']},
                           format='json')
        self.assertEqual(r.status_code, 200)
        self.customer.refresh_from_db()
        self.assertIsNone(self.customer.consent_overseas_at)
        self.assertFalse(has_current_overseas_consent(self.customer))
        # OCR 업로드 게이트 — 철회 후 새 분석은 412(스냅샷까지 비웠으니 reason=missing)
        client = APIClient()
        client.force_authenticate(user=self.user)
        ocr = client.post(f'/api/v1/customers/{self.customer.id}/insurances/ocr/', {})
        self.assertEqual(ocr.status_code, 412)
        self.assertEqual(ocr.json()['code'], 'CONSENT_OVERSEAS_REQUIRED')
        self.assertEqual(ocr.json()['reason'], 'missing')

    def test_revoke_outside_token_scope_ignored(self):
        """토큰 밖 scope 철회는 무시(위조 가드) — 로그 불변."""
        ConsentLog.objects.create(
            customer=self.customer, scope=ConsentLog.SCOPE_MARKETING,
            subject=ConsentLog.SUBJECT_CUSTOMER_SELF)
        tok = self._token(['personal_info'])  # marketing 미포함 토큰
        r = self.anon.post(f'/api/v1/c/{tok}/',
                           {'agreed': ['personal_info'], 'revoked': ['marketing']},
                           format='json')
        self.assertEqual(r.status_code, 201)
        log = ConsentLog.objects.get(customer=self.customer,
                                     scope=ConsentLog.SCOPE_MARKETING)
        self.assertIsNone(log.revoked_at)

    def test_pure_revoke_of_required_scope_passes_412_check(self):
        """철회 전용 요청은 필수 미동의 412를 타지 않는다(철회권 보장)."""
        ConsentLog.objects.create(
            customer=self.customer, scope=ConsentLog.SCOPE_PERSONAL_INFO,
            subject=ConsentLog.SUBJECT_CUSTOMER_SELF)
        tok = self._token(['personal_info'])
        r = self.anon.post(f'/api/v1/c/{tok}/', {'revoked': ['personal_info']},
                           format='json')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()['all_required_done'])

    def test_revoke_then_reagree_reopens_gate(self):
        """왕복 — 철회 후 재동의(v2) → 새 로그 생성 + 게이트 다시 열림."""
        _grant_overseas(self.customer)
        tok = self._token(['overseas_medical'])
        self.anon.post(f'/api/v1/c/{tok}/', {'revoked': ['overseas_medical']},
                       format='json')
        self.assertFalse(has_current_overseas_consent(self.customer))
        r = self.anon.post(f'/api/v1/c/{tok}/', {'agreed': ['overseas_medical']},
                           format='json')
        self.assertEqual(r.status_code, 201)
        self.customer.refresh_from_db()
        self.assertIsNotNone(self.customer.consent_overseas_at)
        self.assertTrue(has_current_overseas_consent(self.customer))
        # 로그: 철회된 1건 + 살아있는 새 1건
        logs = ConsentLog.objects.filter(customer=self.customer,
                                         scope=ConsentLog.SCOPE_OVERSEAS_MEDICAL)
        self.assertEqual(logs.count(), 2)
        self.assertEqual(logs.filter(revoked_at__isnull=True).count(), 1)

    def test_revoke_updates_detail_serializer_state(self):
        """철회 후 고객 상세 consents 상태가 'revoked'로 일관 반영(표시 정합)."""
        ConsentLog.objects.create(
            customer=self.customer, scope=ConsentLog.SCOPE_MARKETING,
            subject=ConsentLog.SUBJECT_CUSTOMER_SELF)
        tok = self._token(['marketing'])
        self.anon.post(f'/api/v1/c/{tok}/', {'revoked': ['marketing']}, format='json')
        client = APIClient()
        client.force_authenticate(user=self.user)
        r = client.get(f'/api/v1/customers/{self.customer.id}/')
        self.assertEqual(r.json()['consents']['marketing']['status'], 'revoked')
        self.assertEqual(r.json()['marketing_consent'], 'revoked')

    def _make_snapshot(self, customer):
        from inpa.analytics.models import ShareSnapshot
        return ShareSnapshot.objects.create(
            owner=self.user, customer=customer,
            payload={'tree': [], 'summary': {}, 'disclaimer': 'x',
                     'customer': {'name_masked': '김**'}, 'mode': 'neutral'},
            retention_expires_at=timezone.now() + datetime.timedelta(days=180))

    def test_personal_info_revoke_purges_this_customers_share_snapshots(self):
        """개인정보(personal_info) 철회 = 그 고객의 공유(/s) 기록 전량 즉시 파기(spec 2026-07-08)."""
        from inpa.analytics.models import ShareSnapshot
        ConsentLog.objects.create(
            customer=self.customer, scope=ConsentLog.SCOPE_PERSONAL_INFO,
            subject=ConsentLog.SUBJECT_CUSTOMER_SELF)
        self._make_snapshot(self.customer)
        other_customer = Customer.objects.create(owner=self.user, name='다른고객')
        other_snap = self._make_snapshot(other_customer)

        tok = self._token(['personal_info'])
        r = self.anon.post(f'/api/v1/c/{tok}/', {'revoked': ['personal_info']},
                           format='json')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(ShareSnapshot.objects.filter(customer=self.customer).exists())
        # 다른 고객의 스냅샷은 무관 — 보존
        self.assertTrue(ShareSnapshot.objects.filter(pk=other_snap.pk).exists())

    @override_settings(INSURANCE_REVIEW_GATE_ENABLED=True)
    def test_personal_info_revoke_closes_active_public_snapshot_link(self):
        """개인정보 동의 철회 뒤 공개 링크는 즉시 404이고 본문은 남지 않는다."""
        from inpa.analytics.models import ShareSnapshot
        ConsentLog.objects.create(
            customer=self.customer, scope=ConsentLog.SCOPE_PERSONAL_INFO,
            subject=ConsentLog.SUBJECT_CUSTOMER_SELF)
        snap = ShareSnapshot.objects.create(
            owner=self.user, customer=self.customer,
            share_token=self.customer.share_token,
            payload={'customer': {'name_masked': '김**'}, 'tree': []},
            payload_version='v2-immutable-analysis',
            link_expires_at=timezone.now() + datetime.timedelta(days=90),
            retention_expires_at=timezone.now() + datetime.timedelta(days=180))
        tok = self._token(['personal_info'])

        response = self.anon.post(
            f'/api/v1/c/{tok}/', {'revoked': ['personal_info']}, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ShareSnapshot.objects.filter(pk=snap.pk).exists())
        self.assertEqual(self.anon.get(
            f'/api/v1/s/{self.customer.share_token}/').status_code, 404)

    def test_marketing_revoke_does_not_touch_share_snapshots(self):
        """personal_info 이외 scope 철회는 공유 기록과 무관(보존)."""
        from inpa.analytics.models import ShareSnapshot
        ConsentLog.objects.create(
            customer=self.customer, scope=ConsentLog.SCOPE_MARKETING,
            subject=ConsentLog.SUBJECT_CUSTOMER_SELF)
        snap = self._make_snapshot(self.customer)
        tok = self._token(['marketing'])
        r = self.anon.post(f'/api/v1/c/{tok}/', {'revoked': ['marketing']}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(ShareSnapshot.objects.filter(pk=snap.pk).exists())


class DailyCallListTests(TestCase):
    """오늘 전화 리스트(call-list) — 랭킹·격리·캡·안전성 (spec 2026-07-05)."""

    URL = '/api/v1/customers/call-list/'

    def setUp(self):
        self.user, self.client = _make_planner('caller@test.com')
        self.other, self.other_client = _make_planner('other@test.com')
        self.today = timezone.localdate()

    def _customer(self, name, owner=None, **kw):
        return Customer.objects.create(owner=owner or self.user, name=name, **kw)

    def _birth_str(self, days_ahead):
        """오늘+N일의 월·일을 가진 생일 문자열(1992 = 윤년이라 2/29도 유효)."""
        d = self.today + datetime.timedelta(days=days_ahead)
        return f'1992-{d.month:02d}-{d.day:02d}'

    def _expiry(self, customer, days_ahead, **kw):
        exp = self.today + datetime.timedelta(days=days_ahead)
        return CustomerInsurance.objects.create(
            customer=customer, name='테스트보험', portfolio_type=1,
            expiry_date=exp.strftime('%Y-%m-%d'), **kw)

    def test_ranking_birthday_over_expiry_over_idle(self):
        """생일 D-1(90) > 만기 D-5(70) > 무접촉 30일(30) 순서 + reasons 칩."""
        c_birth = self._customer('생일고객', birth_day=self._birth_str(1))
        c_exp = self._customer('만기고객')
        self._expiry(c_exp, 5)
        c_idle = self._customer(
            '무접촉고객',
            last_contacted_at=timezone.now() - datetime.timedelta(days=30))
        r = self.client.get(self.URL)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        names = [row['name'] for row in body['results']]
        self.assertEqual(names, ['생일고객', '만기고객', '무접촉고객'])
        self.assertEqual(body['total_candidates'], 3)
        by_name = {row['name']: row for row in body['results']}
        self.assertEqual(by_name['생일고객']['score'], 90)
        self.assertIn('생일 D-1', by_name['생일고객']['reasons'])
        self.assertEqual(by_name['만기고객']['score'], 70)
        self.assertIn('만기 D-5', by_name['만기고객']['reasons'])
        self.assertIn('무접촉', by_name['무접촉고객']['reasons'][0])
        self.assertEqual(by_name['무접촉고객']['id'], c_idle.id)
        self.assertEqual(by_name['생일고객']['id'], c_birth.id)

    def test_only_active_status(self):
        """보류·휴면·종료 고객은 사유가 강해도 제외."""
        for st in (Customer.STATUS_HOLD, Customer.STATUS_DORMANT,
                   Customer.STATUS_CLOSED):
            self._customer(
                f'파킹-{st}', status=st,
                last_contacted_at=timezone.now() - datetime.timedelta(days=40))
        active = self._customer(
            '진행중고객',
            last_contacted_at=timezone.now() - datetime.timedelta(days=10))
        r = self.client.get(self.URL)
        body = r.json()
        self.assertEqual([row['id'] for row in body['results']], [active.id])
        self.assertEqual(body['total_candidates'], 1)

    def test_owner_isolation(self):
        """타 설계사 고객은 사유가 있어도 절대 미노출."""
        self._customer(
            '남의고객', owner=self.other,
            birth_day=self._birth_str(0),
            last_contacted_at=timezone.now() - datetime.timedelta(days=50))
        mine = self._customer(
            '내고객', last_contacted_at=timezone.now() - datetime.timedelta(days=5))
        r = self.client.get(self.URL)
        body = r.json()
        self.assertEqual([row['id'] for row in body['results']], [mine.id])
        self.assertEqual(body['total_candidates'], 1)

    def test_zero_score_excluded_and_cap_10(self):
        """사유 없는(score 0) 고객 제외 + 10명 캡 + total_candidates."""
        fresh = self._customer('오늘등록')  # created 오늘 → 무접촉 0 → score 0
        # 단계 보정만으로는 리스트에 오르지 않음(사유 없음).
        momentum = self._customer('모멘텀만', sales_stage=Customer.STAGE_CONTACT)
        for i in range(12):
            self._customer(
                f'무접촉{i}',
                last_contacted_at=timezone.now() - datetime.timedelta(days=5 + i))
        r = self.client.get(self.URL)
        body = r.json()
        self.assertEqual(len(body['results']), 10)
        self.assertEqual(body['total_candidates'], 12)
        ids = {row['id'] for row in body['results']}
        self.assertNotIn(fresh.id, ids)
        self.assertNotIn(momentum.id, ids)

    def test_stage_bonus_applied_when_reason_exists(self):
        """같은 사유(무접촉 20일)면 TA/FA 단계가 +10으로 앞선다."""
        anchor = timezone.now() - datetime.timedelta(days=20)
        db_cust = self._customer('디비단계', last_contacted_at=anchor)
        ta_cust = self._customer('티에이단계', sales_stage=Customer.STAGE_CONTACT,
                                 last_contacted_at=anchor)
        r = self.client.get(self.URL)
        by_name = {row['name']: row for row in r.json()['results']}
        self.assertEqual(by_name['티에이단계']['score'],
                         by_name['디비단계']['score'] + 10)
        self.assertEqual([row['id'] for row in r.json()['results']],
                         [ta_cust.id, db_cust.id])

    def test_limit_param_default_cap_and_invalid(self):
        """?limit= 동작 — 기본 10 · 상한 50 클램프 · 비정상 값은 기본값."""
        for i in range(55):
            self._customer(
                f'무접촉{i}',
                last_contacted_at=timezone.now() - datetime.timedelta(days=3 + i))
        # 기본(파라미터 없음) = 10
        body = self.client.get(self.URL).json()
        self.assertEqual(len(body['results']), 10)
        self.assertEqual(body['total_candidates'], 55)
        # 명시 limit 반영
        body = self.client.get(self.URL, {'limit': '5'}).json()
        self.assertEqual(len(body['results']), 5)
        self.assertEqual(body['total_candidates'], 55)
        # 전용 화면 요청값(50) + 상한 초과는 50으로 클램프
        body = self.client.get(self.URL, {'limit': '50'}).json()
        self.assertEqual(len(body['results']), 50)
        body = self.client.get(self.URL, {'limit': '999'}).json()
        self.assertEqual(len(body['results']), 50)
        # 비정상 값(숫자 아님·0 이하)은 기본 10
        for bad in ('abc', '0', '-3'):
            body = self.client.get(self.URL, {'limit': bad}).json()
            self.assertEqual(len(body['results']), 10, msg=f'limit={bad}')

    def test_malformed_dates_are_safe(self):
        """생일·만기 문자열이 깨져도 200 + 그 사유만 조용히 무시."""
        self._customer('깨진생일', birth_day='19-XX')  # 파싱 불가 + 무접촉 0 → 제외
        broken_exp = self._customer(
            '깨진만기', last_contacted_at=timezone.now() - datetime.timedelta(days=3))
        self._expiry(broken_exp, 5)
        broken_exp.customer_insurance_list.update(expiry_date='2026.13.99')
        r = self.client.get(self.URL)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual([row['id'] for row in body['results']], [broken_exp.id])
        reasons = body['results'][0]['reasons']
        self.assertTrue(all('만기' not in x and '생일' not in x for x in reasons))
        self.assertEqual(body['total_candidates'], 1)


# ─── 신규 고객 추가 한도 (spec 2026-07-09 pricing-limits-align) ───────────────


def _consume_customer_quota(user, n):
    """billing UsageMeter('customer') 카운터를 n으로 직접 세팅(billing/tests.py::_consume_n과 동일 패턴)."""
    ym = UsageMeter.current_month()
    meter, _ = UsageMeter.objects.get_or_create(
        user=user, action='customer', year_month=ym, defaults={'count': 0})
    meter.count = n
    meter.save(update_fields=['count', 'updated_at'])


def _subscribe_free(user, limit_customer=5):
    """테스트 전용 free Plan(원하는 limit_customer)에 구독시킨다."""
    free_plan, created = Plan.objects.get_or_create(
        code='free',
        defaults={'display_name': '무료', 'price_krw': 0, 'limit_customer': limit_customer},
    )
    if not created and free_plan.limit_customer != limit_customer:
        free_plan.limit_customer = limit_customer
        free_plan.save(update_fields=['limit_customer'])
    Subscription.objects.update_or_create(
        user=user, defaults={'plan': free_plan, 'status': 'active'})
    return free_plan


@override_settings(FREE_TIER_UNLIMITED=False)
class CustomerQuotaEnforcementTests(TestCase):
    """CustomerViewSet 단건·일괄 등록 — 신규 고객 추가 한도(kind='customer') 강제.

    ★ FREE_TIER_UNLIMITED=False(유료 전환 후)에서만 발동 — 베타 dormant는
    CustomerQuotaBetaDormantTests 로 별도 검증한다.
    """

    def setUp(self):
        self.user, self.client = _make_planner('quota@test.com')
        _subscribe_free(self.user, limit_customer=5)

    def test_sixth_single_create_returns_402_credit_exhausted(self):
        _consume_customer_quota(self.user, 5)
        r = self.client.post('/api/v1/customers/', {'name': '고객6'}, format='json')
        self.assertEqual(r.status_code, 402, r.data)
        self.assertEqual(r.json()['code'], 'credit_exhausted')
        self.assertEqual(r.json()['kind'], 'customer')
        self.assertFalse(Customer.objects.filter(owner=self.user, name='고객6').exists())

    def test_fifth_single_create_passes(self):
        _consume_customer_quota(self.user, 4)
        r = self.client.post('/api/v1/customers/', {'name': '고객5'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(Customer.objects.filter(owner=self.user, name='고객5').exists())

    def test_bulk_batch_larger_than_remaining_returns_402_no_partial_create(self):
        """잔여 0(5/5 소진)인데 2건 일괄 등록 시도 → 402, 아무도 생성되지 않는다."""
        _consume_customer_quota(self.user, 5)
        body = {'customers': [{'name': '벌크1'}, {'name': '벌크2'}]}
        r = self.client.post('/api/v1/customers/bulk/', body, format='json')
        self.assertEqual(r.status_code, 402, r.data)
        self.assertEqual(r.json()['kind'], 'customer')
        self.assertEqual(
            Customer.objects.filter(owner=self.user, name__startswith='벌크').count(), 0)

    def test_bulk_partial_remaining_rejects_whole_batch_not_partial(self):
        """잔여 2(5-3)인데 3건 요청 → 전량 402(부분 생성 없음 — 2건만 만들고 끝내지 않는다)."""
        _consume_customer_quota(self.user, 3)
        body = {'customers': [{'name': 'A'}, {'name': 'B'}, {'name': 'C'}]}
        r = self.client.post('/api/v1/customers/bulk/', body, format='json')
        self.assertEqual(r.status_code, 402, r.data)
        self.assertEqual(
            Customer.objects.filter(owner=self.user, name__in=['A', 'B', 'C']).count(), 0)

    def test_bulk_within_remaining_creates_all(self):
        """잔여 2인데 2건 요청 → 통과, 2건 모두 생성."""
        _consume_customer_quota(self.user, 3)
        body = {'customers': [{'name': 'D'}, {'name': 'E'}]}
        r = self.client.post('/api/v1/customers/bulk/', body, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.json()['created'], 2)
        self.assertEqual(
            Customer.objects.filter(owner=self.user, name__in=['D', 'E']).count(), 2)


class CustomerQuotaBetaDormantTests(TestCase):
    """★ FREE_TIER_UNLIMITED=True(기본, 베타) → 고객 추가 한도는 dormant.

    지금 베타 사용자에게는 어떤 영향도 없어야 한다 — Free 한도(5)를 넘겨도 계속 생성된다.
    (default_settings에서 FREE_TIER_UNLIMITED 를 override 하지 않음 = 실제 배포 기본값과 동일)
    """

    def setUp(self):
        self.user, self.client = _make_planner('betaquota@test.com')
        _subscribe_free(self.user, limit_customer=5)

    def test_single_create_beyond_free_limit_still_succeeds(self):
        _consume_customer_quota(self.user, 999)
        r = self.client.post('/api/v1/customers/', {'name': '베타무제한'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)

    def test_bulk_beyond_free_limit_still_succeeds(self):
        body = {'customers': [{'name': f'베타{i}'} for i in range(10)]}
        r = self.client.post('/api/v1/customers/bulk/', body, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.json()['created'], 10)


class InboundLeadQuotaExclusionTests(TestCase):
    """★ 회귀(spec 2026-07-09): 인바운드 자동 리드(셀프진단 /d, 소개카드 /p)는 설계사의
    '신규 고객 추가' 한도를 소비하지 않는다 — 두 뷰 모두 Customer.objects.create()를 직접
    호출해 CustomerViewSet(perform_create/bulk_create)를 거치지 않기 때문이다. 한도가 이미
    완전히 소진된 설계사라도 잠재고객의 셀프진단·상담신청은 계속 성공해야 한다(그렇지 않으면
    고객이 셀프진단했다는 이유로 설계사의 한도가 깎이는 불합리가 생긴다).
    """

    def setUp(self):
        from django.core.cache import cache
        cache.clear()  # ScopedRateThrottle('self_diagnosis') 카운터 격리

    @override_settings(FREE_TIER_UNLIMITED=False)
    def test_self_diagnosis_lead_does_not_consume_customer_quota(self):
        planner, _ = _make_planner('inbound-diag@test.com')
        _subscribe_free(planner, limit_customer=5)
        _consume_customer_quota(planner, 5)  # 설계사 능동 한도 완전 소진

        public = APIClient()
        ref = planner.profile.ref_code
        r = public.post(f'/api/v1/d/{ref}/', {
            'name': '셀프진단고객', 'phone': '01099998888',
            'birth': '1990-01-01', 'gender': '1', 'consent_share': 'true',
        }, format='multipart')
        self.assertEqual(r.status_code, 201, r.data)  # 한도 소진과 무관하게 리드는 성공
        self.assertTrue(Customer.objects.filter(
            owner=planner, lead_source='self_diagnosis', name='셀프진단고객').exists())
        # UsageMeter('customer')는 여전히 5 — 인바운드 리드로 증가하지 않는다.
        ym = UsageMeter.current_month()
        meter = UsageMeter.objects.get(user=planner, action='customer', year_month=ym)
        self.assertEqual(meter.count, 5)

    @override_settings(FREE_TIER_UNLIMITED=False)
    def test_introduction_card_lead_does_not_consume_customer_quota(self):
        planner, _ = _make_planner('inbound-intro@test.com')
        _subscribe_free(planner, limit_customer=5)
        _consume_customer_quota(planner, 5)

        public = APIClient()
        ref = planner.profile.ref_code
        r = public.post(f'/api/v1/p/{ref}/',
                        {'name': '소개고객', 'phone': '010-2222-3333', 'agreed': True},
                        format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(Customer.objects.filter(
            owner=planner, lead_source='introduction', name='소개고객').exists())
        ym = UsageMeter.current_month()
        meter = UsageMeter.objects.get(user=planner, action='customer', year_month=ym)
        self.assertEqual(meter.count, 5)


class CustomerMemoApiTests(TestCase):
    """상담 메모 CRUD는 고객 소유자 범위 안에서만 동작한다."""

    def setUp(self):
        self.user, self.client = _make_planner('memo-api-owner@test.com')
        self.other_user, self.other_client = _make_planner('memo-api-other@test.com')
        self.customer = Customer.objects.create(owner=self.user, name='메모 고객')
        self.other_customer = Customer.objects.create(owner=self.other_user, name='다른 고객')

    def _url(self, customer_id=None):
        return f'/api/v1/customers/{customer_id or self.customer.id}/memos/'

    def _detail_url(self, memo_id, customer_id=None):
        return f'{self._url(customer_id)}{memo_id}/'

    def test_create_keeps_server_source_and_occurred_time_authoritative(self):
        from inpa.analytics.models import NorthStarEvent

        self.assertIsNone(self.customer.last_contacted_at)
        before = timezone.now()
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self._url(), {
                'body': '  첫 상담 메모  ',
                'source': CustomerMemo.SOURCE_AI_SUMMARY,
                'is_legacy_mirror': True,
                'occurred_at': '2000-01-01T00:00:00Z',
            }, format='json')

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['body'], '첫 상담 메모')
        self.assertEqual(response.data['source'], CustomerMemo.SOURCE_MANUAL)
        self.assertEqual(response.data['revision'], 1)
        memo = CustomerMemo.objects.get(pk=response.data['id'])
        self.assertGreaterEqual(memo.occurred_at, before)
        self.assertFalse(memo.is_legacy_mirror)
        self.assertNotIn('is_legacy_mirror', response.data)
        retrieved = self.client.get(self._detail_url(response.data['id']))
        self.assertEqual(retrieved.status_code, 200, retrieved.data)
        self.assertEqual(retrieved.data['body'], '첫 상담 메모')
        self.customer.refresh_from_db()
        self.assertIsNotNone(self.customer.last_contacted_at)
        event = NorthStarEvent.objects.get(event_type=NorthStarEvent.CONSULTATION_MEMO_CREATED)
        self.assertEqual(event.customer_id, self.customer.id)
        self.assertEqual(event.sender_id, self.user.id)
        self.assertEqual(event.payload, {'source': 'manual'})

    def test_task2_memo_events_wait_for_commit_and_run_once(self):
        from inpa.analytics.models import NorthStarEvent

        with self.captureOnCommitCallbacks(execute=False) as create_callbacks:
            created = self.client.post(self._url(), {'body': '커밋 뒤 생성'}, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(len(create_callbacks), 1)
        self.assertFalse(NorthStarEvent.objects.filter(customer=self.customer).exists())
        create_callbacks[0]()
        self.assertEqual(NorthStarEvent.objects.filter(
            event_type=NorthStarEvent.CONSULTATION_MEMO_CREATED,
            customer=self.customer, payload={'source': CustomerMemo.SOURCE_MANUAL}).count(), 1)

        with self.captureOnCommitCallbacks(execute=False) as edit_callbacks:
            changed = self.client.patch(
                self._detail_url(created.data['id']),
                {'body': '커밋 뒤 수정', 'revision': 1}, format='json')
        self.assertEqual(changed.status_code, 200, changed.data)
        self.assertEqual(len(edit_callbacks), 1)
        self.assertEqual(NorthStarEvent.objects.filter(customer=self.customer).count(), 1)
        edit_callbacks[0]()
        self.assertEqual(NorthStarEvent.objects.filter(
            event_type=NorthStarEvent.CONSULTATION_MEMO_EDITED,
            customer=self.customer, payload={'source': CustomerMemo.SOURCE_MANUAL}).count(), 1)

    def test_edit_noop_and_delete_do_not_bump_contact_time(self):
        created = self.client.post(self._url(), {'body': '첫 상담 메모'}, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        memo_id = created.data['id']
        self.customer.refresh_from_db()
        contacted_at = self.customer.last_contacted_at

        changed = self.client.patch(
            self._detail_url(memo_id),
            {'body': '첫 상담 메모 수정', 'revision': 1}, format='json')
        self.assertEqual(changed.status_code, 200, changed.data)
        self.assertEqual(changed.data['revision'], 2)
        self.assertIsNotNone(changed.data['edited_at'])
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.last_contacted_at, contacted_at)

        noop = self.client.patch(
            self._detail_url(memo_id),
            {'body': '첫 상담 메모 수정', 'revision': 2}, format='json')
        self.assertEqual(noop.status_code, 200, noop.data)
        self.assertEqual(noop.data['revision'], 2)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.last_contacted_at, contacted_at)

        deleted = self.client.delete(self._detail_url(memo_id))
        self.assertEqual(deleted.status_code, 204)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.last_contacted_at, contacted_at)

    def test_edit_and_delete_legacy_mirror_keep_customer_field_in_sync(self):
        self.customer.memo = '이전 내용'
        self.customer.save(update_fields=['memo'])
        mirror = CustomerMemo.objects.create(
            owner=self.user, customer=self.customer,
            source=CustomerMemo.SOURCE_LEGACY, body='이전 내용',
            is_legacy_mirror=True)

        changed = self.client.patch(
            self._detail_url(mirror.id),
            {'body': '새 내용', 'revision': 1}, format='json')

        self.assertEqual(changed.status_code, 200, changed.data)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.memo, '새 내용')

        deleted = self.client.delete(self._detail_url(mirror.id))

        self.assertEqual(deleted.status_code, 204)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.memo, '')

    def test_legacy_mirror_noop_edit_repairs_drift_without_revision_change(self):
        self.customer.memo = '오래된 내용'
        self.customer.save(update_fields=['memo'])
        mirror = CustomerMemo.objects.create(
            owner=self.user, customer=self.customer,
            source=CustomerMemo.SOURCE_LEGACY, body='최신 내용',
            is_legacy_mirror=True)

        response = self.client.patch(
            self._detail_url(mirror.id),
            {'body': '최신 내용', 'revision': 1}, format='json')

        self.assertEqual(response.status_code, 200, response.data)
        self.customer.refresh_from_db()
        mirror.refresh_from_db()
        self.assertEqual(self.customer.memo, '최신 내용')
        self.assertEqual(mirror.revision, 1)
        self.assertIsNone(mirror.edited_at)

    def test_edit_and_delete_ordinary_memo_never_change_customer_field(self):
        self.customer.memo = '호환 기준'
        self.customer.save(update_fields=['memo'])
        CustomerMemo.objects.create(
            owner=self.user, customer=self.customer,
            source=CustomerMemo.SOURCE_LEGACY, body='호환 기준',
            is_legacy_mirror=True)
        ordinary = CustomerMemo.objects.create(
            owner=self.user, customer=self.customer,
            source=CustomerMemo.SOURCE_MANUAL, body='일반 메모',
            occurred_at=timezone.now())

        changed = self.client.patch(
            self._detail_url(ordinary.id),
            {'body': '일반 메모 수정', 'revision': 1}, format='json')
        self.assertEqual(changed.status_code, 200, changed.data)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.memo, '호환 기준')

        deleted = self.client.delete(self._detail_url(ordinary.id))
        self.assertEqual(deleted.status_code, 204)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.memo, '호환 기준')

    def test_list_uses_tie_breakers_across_pagination_boundary(self):
        base = timezone.now()
        memos = [CustomerMemo.objects.create(
            owner=self.user, customer=self.customer, source=CustomerMemo.SOURCE_MANUAL,
            body=f'동률 메모 {number}', occurred_at=base)
            for number in range(21)]
        CustomerMemo.objects.filter(pk__in=[memo.pk for memo in memos]).update(created_at=base)

        first_page = self.client.get(self._url())
        second_page = self.client.get(f'{self._url()}?page=2')

        self.assertEqual(first_page.status_code, 200, first_page.data)
        self.assertEqual(second_page.status_code, 200, second_page.data)
        first_rows = first_page.data['results']
        second_rows = second_page.data['results']
        ids = [row['id'] for row in first_rows + second_rows]
        self.assertEqual(len(first_rows), 20)
        self.assertEqual(len(ids), 21)
        self.assertEqual(len(set(ids)), 21)
        self.assertEqual(ids, sorted(ids, reverse=True))
        self.assertEqual(ids, sorted((memo.id for memo in memos), reverse=True))

    def test_list_orders_coalesced_time_then_created_time_before_id(self):
        base = timezone.now()
        latest_occurred = CustomerMemo.objects.create(
            owner=self.user, customer=self.customer, source=CustomerMemo.SOURCE_MANUAL,
            body='발생 시각 최신', occurred_at=base)
        legacy_between = CustomerMemo.objects.create(
            owner=self.user, customer=self.customer, source=CustomerMemo.SOURCE_LEGACY,
            body='기존 메모', occurred_at=None)
        same_display_newer_created = CustomerMemo.objects.create(
            owner=self.user, customer=self.customer, source=CustomerMemo.SOURCE_MANUAL,
            body='같은 발생 시각, 생성 최신', occurred_at=base)
        same_display_older_created = CustomerMemo.objects.create(
            owner=self.user, customer=self.customer, source=CustomerMemo.SOURCE_MANUAL,
            body='같은 발생 시각, 생성 이전', occurred_at=base)
        earliest_occurred = CustomerMemo.objects.create(
            owner=self.user, customer=self.customer, source=CustomerMemo.SOURCE_MANUAL,
            body='발생 시각 이전', occurred_at=base)
        CustomerMemo.objects.filter(pk=latest_occurred.pk).update(
            occurred_at=base + datetime.timedelta(minutes=4), created_at=base)
        CustomerMemo.objects.filter(pk=legacy_between.pk).update(
            created_at=base + datetime.timedelta(minutes=3))
        CustomerMemo.objects.filter(pk=same_display_newer_created.pk).update(
            occurred_at=base + datetime.timedelta(minutes=1),
            created_at=base + datetime.timedelta(minutes=6))
        CustomerMemo.objects.filter(pk=same_display_older_created.pk).update(
            occurred_at=base + datetime.timedelta(minutes=1),
            created_at=base + datetime.timedelta(minutes=5))
        CustomerMemo.objects.filter(pk=earliest_occurred.pk).update(
            occurred_at=base, created_at=base + datetime.timedelta(minutes=9))

        response = self.client.get(self._url())

        self.assertEqual(response.status_code, 200, response.data)
        rows = response.data['results'] if isinstance(response.data, dict) else response.data
        self.assertEqual(
            [row['id'] for row in rows],
            [
                latest_occurred.id,
                legacy_between.id,
                same_display_newer_created.id,
                same_display_older_created.id,
                earliest_occurred.id,
            ],
        )

    def test_blank_and_too_long_body_are_rejected(self):
        for body in ('   ', '가' * 10_001):
            response = self.client.post(self._url(), {'body': body}, format='json')
            self.assertEqual(response.status_code, 400, response.data)
            self.assertIn('body', response.data)

    def test_revision_is_required_integer_and_stale_revision_conflicts(self):
        memo = CustomerMemo.objects.create(
            owner=self.user, customer=self.customer, source=CustomerMemo.SOURCE_MANUAL,
            body='기존 메모', occurred_at=timezone.now())
        for revision in (None, True, '1', 1.0):
            payload = {'body': '수정 메모'}
            if revision is not None:
                payload['revision'] = revision
            response = self.client.patch(self._detail_url(memo.id), payload, format='json')
            self.assertEqual(response.status_code, 400, response.data)
            self.assertEqual(response.data['code'], 'MEMO_REVISION_REQUIRED')

        response = self.client.patch(
            self._detail_url(memo.id), {'body': '충돌 메모', 'revision': 999}, format='json')
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data['code'], 'MEMO_EDIT_CONFLICT')

    def test_other_owner_gets_404_for_every_customer_and_memo_path(self):
        memo = CustomerMemo.objects.create(
            owner=self.user, customer=self.customer, source=CustomerMemo.SOURCE_MANUAL,
            body='비공개 메모', occurred_at=timezone.now())
        self.assertEqual(self.other_client.get(self._url()).status_code, 404)
        self.assertEqual(
            self.other_client.post(self._url(), {'body': '침입 시도'}, format='json').status_code, 404)
        self.assertEqual(self.other_client.get(self._detail_url(memo.id)).status_code, 404)
        for payload in (
            {'body': '침입 수정', 'revision': 1},
            {},
            {'body': '침입 수정', 'revision': True},
            {'body': '침입 수정', 'revision': '1'},
            {'body': '   ', 'revision': 1},
            {'body': '가' * 10_001, 'revision': 1},
        ):
            self.assertEqual(
                self.other_client.patch(self._detail_url(memo.id), payload, format='json').status_code,
                404)
        self.assertEqual(self.other_client.delete(self._detail_url(memo.id)).status_code, 404)
        self.assertEqual(
            self.other_client.post(self._url(), {'body': '   '}, format='json').status_code, 404)

    def test_put_is_not_a_memo_edit_endpoint(self):
        memo = CustomerMemo.objects.create(
            owner=self.user, customer=self.customer, source=CustomerMemo.SOURCE_MANUAL,
            body='기존 메모', occurred_at=timezone.now())

        response = self.client.put(
            self._detail_url(memo.id), {'body': 'PUT 수정', 'revision': 1}, format='json')

        self.assertEqual(response.status_code, 405)

    def test_analytics_failure_never_blocks_creation_and_edit_only_logs_real_change(self):
        from inpa.analytics.models import NorthStarEvent

        with mock.patch('inpa.analytics.models.NorthStarEvent.objects.create',
                        side_effect=RuntimeError('analytics unavailable')):
            with self.captureOnCommitCallbacks(execute=True):
                failed_analytics = self.client.post(self._url(), {'body': '저장되는 메모'}, format='json')
        self.assertEqual(failed_analytics.status_code, 201, failed_analytics.data)

        with self.captureOnCommitCallbacks(execute=True):
            created = self.client.post(self._url(), {'body': '이벤트 확인 메모'}, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        memo_id = created.data['id']
        with self.captureOnCommitCallbacks(execute=True):
            changed = self.client.patch(
                self._detail_url(memo_id), {'body': '이벤트 수정 메모', 'revision': 1}, format='json')
        self.assertEqual(changed.status_code, 200, changed.data)
        noop = self.client.patch(
            self._detail_url(memo_id), {'body': '이벤트 수정 메모', 'revision': 2}, format='json')
        self.assertEqual(noop.status_code, 200, noop.data)
        self.assertEqual(NorthStarEvent.objects.filter(
            event_type=NorthStarEvent.CONSULTATION_MEMO_CREATED,
            customer=self.customer).count(), 1)
        self.assertEqual(NorthStarEvent.objects.filter(
            event_type=NorthStarEvent.CONSULTATION_MEMO_EDITED,
            customer=self.customer).count(), 1)

    def test_edit_analytics_failure_persists_change_and_noop_emits_nothing(self):
        from inpa.analytics.models import NorthStarEvent

        memo = CustomerMemo.objects.create(
            owner=self.user, customer=self.customer, source=CustomerMemo.SOURCE_MANUAL,
            body='수정 전 메모', occurred_at=timezone.now())
        with mock.patch('inpa.analytics.models.NorthStarEvent.objects.create',
                        side_effect=RuntimeError('analytics unavailable')):
            with self.captureOnCommitCallbacks(execute=True):
                changed = self.client.patch(
                    self._detail_url(memo.id), {'body': '수정 후 메모', 'revision': 1}, format='json')

        self.assertEqual(changed.status_code, 200, changed.data)
        memo.refresh_from_db()
        self.assertEqual(memo.body, '수정 후 메모')
        self.assertEqual(memo.revision, 2)
        noop = self.client.patch(
            self._detail_url(memo.id), {'body': '수정 후 메모', 'revision': 2}, format='json')
        self.assertEqual(noop.status_code, 200, noop.data)
        self.assertFalse(NorthStarEvent.objects.filter(
            event_type=NorthStarEvent.CONSULTATION_MEMO_EDITED,
            customer=self.customer).exists())


class CustomerMemoServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('memo-service@test.com', password='pass1234')
        self.customer = Customer.objects.create(owner=self.user, name='서비스 고객')

    def test_service_rejects_whitespace_only_and_too_long_bodies(self):
        from .memos import create_manual_memo, update_memo

        with self.assertRaisesRegex(ValueError, 'EMPTY_MEMO'):
            create_manual_memo(customer=self.customer, owner=self.user, body='   ')
        with self.assertRaisesRegex(ValueError, 'MEMO_BODY_TOO_LONG'):
            create_manual_memo(customer=self.customer, owner=self.user, body='가' * 10_001)

        memo = CustomerMemo.objects.create(
            owner=self.user, customer=self.customer, source=CustomerMemo.SOURCE_MANUAL,
            body='기존 메모')
        with self.assertRaisesRegex(ValueError, 'MEMO_BODY_TOO_LONG'):
            update_memo(memo=memo, body='가' * 10_001, expected_revision=1)


class CustomerMemoCompatibilityTests(TestCase):
    """구버전 Customer.memo 요청도 다중 상담 메모와 함께 안전하게 유지한다."""

    def setUp(self):
        self.user, self.client = _make_planner('memo-bridge-owner@test.com')
        self.other_user, self.other_client = _make_planner('memo-bridge-other@test.com')
        self.customer = Customer.objects.create(owner=self.user, name='호환 고객')
        self.other_customer = Customer.objects.create(owner=self.other_user, name='다른 고객')

    def _url(self, customer=None):
        return f'/api/v1/customers/{(customer or self.customer).id}/'

    def test_legacy_patch_updates_only_legacy_mirror_and_preserves_other_rows(self):
        manual = CustomerMemo.objects.create(
            owner=self.user, customer=self.customer, source=CustomerMemo.SOURCE_MANUAL,
            body='직접 작성 메모', occurred_at=timezone.now())
        ai_summary = CustomerMemo.objects.create(
            owner=self.user, customer=self.customer, source=CustomerMemo.SOURCE_AI_SUMMARY,
            body='요약 메모')

        response = self.client.patch(self._url(), {'memo': '  구버전 저장  '}, format='json')

        self.assertEqual(response.status_code, 200, response.data)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.memo, '구버전 저장')
        legacy = self.customer.memos.get(source=CustomerMemo.SOURCE_LEGACY)
        self.assertEqual(legacy.body, '구버전 저장')
        self.assertEqual(legacy.revision, 1)
        self.assertIsNone(legacy.edited_at)
        self.assertTrue(CustomerMemo.objects.filter(pk=manual.pk).exists())
        self.assertTrue(CustomerMemo.objects.filter(pk=ai_summary.pk).exists())

    def test_legacy_patch_change_noop_and_clear_follow_revision_rules_without_contact_bump(self):
        self.customer.memo = '처음'
        self.customer.save(update_fields=['memo'])
        legacy = CustomerMemo.objects.create(
            owner=self.user, customer=self.customer, source=CustomerMemo.SOURCE_LEGACY,
            body='처음', is_legacy_mirror=True)
        original_contacted_at = self.customer.last_contacted_at

        changed = self.client.patch(self._url(), {'memo': '바뀐 메모'}, format='json')
        self.assertEqual(changed.status_code, 200, changed.data)
        legacy.refresh_from_db()
        self.assertEqual(legacy.body, '바뀐 메모')
        self.assertEqual(legacy.revision, 2)
        self.assertIsNotNone(legacy.edited_at)
        edited_at = legacy.edited_at

        noop = self.client.patch(self._url(), {'memo': '  바뀐 메모  '}, format='json')
        self.assertEqual(noop.status_code, 200, noop.data)
        legacy.refresh_from_db()
        self.assertEqual(legacy.revision, 2)
        self.assertEqual(legacy.edited_at, edited_at)

        cleared = self.client.patch(self._url(), {'memo': ' \n\t '}, format='json')
        self.assertEqual(cleared.status_code, 200, cleared.data)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.memo, '')
        self.assertFalse(self.customer.memos.filter(source=CustomerMemo.SOURCE_LEGACY).exists())
        self.assertEqual(self.customer.last_contacted_at, original_contacted_at)

    def test_migration_padded_legacy_body_is_a_normalized_noop(self):
        from inpa.analytics.models import NorthStarEvent

        self.customer.memo = '  이관된 메모  '
        self.customer.save(update_fields=['memo'])
        legacy = CustomerMemo.objects.create(
            owner=self.user, customer=self.customer, source=CustomerMemo.SOURCE_LEGACY,
            body='  이관된 메모  ', is_legacy_mirror=True)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.patch(self._url(), {'memo': '이관된 메모'}, format='json')

        self.assertEqual(response.status_code, 200, response.data)
        legacy.refresh_from_db()
        self.customer.refresh_from_db()
        self.assertEqual(legacy.body, '  이관된 메모  ')
        self.assertEqual(legacy.revision, 1)
        self.assertIsNone(legacy.edited_at)
        self.assertEqual(self.customer.memo, '  이관된 메모  ')
        self.assertFalse(NorthStarEvent.objects.filter(customer=self.customer).exists())

    def test_new_customer_memo_creates_manual_mirror_and_bumps_contact_time(self):
        from inpa.analytics.models import NorthStarEvent

        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            response = self.client.post(
                '/api/v1/customers/', {'name': '단건 고객', 'memo': '  단건 메모  '}, format='json')

        self.assertEqual(response.status_code, 201, response.data)
        customer = Customer.objects.get(pk=response.data['id'])
        self.assertEqual(customer.memo, '단건 메모')
        memo = customer.memos.get()
        self.assertEqual(memo.source, CustomerMemo.SOURCE_MANUAL)
        self.assertEqual(memo.body, '단건 메모')
        self.assertTrue(getattr(memo, 'is_legacy_mirror', False))
        self.assertIsNotNone(memo.occurred_at)
        self.assertIsNotNone(customer.last_contacted_at)
        self.assertEqual(len(callbacks), 1)
        self.assertFalse(NorthStarEvent.objects.filter(customer=customer).exists())
        callbacks[0]()
        self.assertEqual(NorthStarEvent.objects.filter(
            customer=customer,
            event_type=NorthStarEvent.CONSULTATION_MEMO_CREATED,
            payload={'source': CustomerMemo.SOURCE_MANUAL}).count(), 1)

        changed = self.client.patch(
            f'/api/v1/customers/{customer.id}/memos/{memo.id}/',
            {'body': '단건 수정', 'revision': 1}, format='json')
        self.assertEqual(changed.status_code, 200, changed.data)
        customer.refresh_from_db()
        self.assertEqual(customer.memo, '단건 수정')

        deleted = self.client.delete(
            f'/api/v1/customers/{customer.id}/memos/{memo.id}/')
        self.assertEqual(deleted.status_code, 204)
        customer.refresh_from_db()
        self.assertEqual(customer.memo, '')

    def test_bulk_customer_memo_creates_manual_mirror_and_skips_blank(self):
        from inpa.analytics.models import NorthStarEvent

        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            response = self.client.post('/api/v1/customers/bulk/', {'customers': [
                {'name': '일괄 메모 고객', 'memo': '  일괄 메모  '},
                {'name': '빈 메모 고객', 'memo': ' \t '},
            ]}, format='json')

        self.assertEqual(response.status_code, 201, response.data)
        mirrored = Customer.objects.get(owner=self.user, name='일괄 메모 고객')
        blank = Customer.objects.get(owner=self.user, name='빈 메모 고객')
        self.assertEqual(mirrored.memo, '일괄 메모')
        self.assertEqual(mirrored.memos.get().source, CustomerMemo.SOURCE_MANUAL)
        self.assertEqual(mirrored.memos.get().body, '일괄 메모')
        self.assertTrue(getattr(mirrored.memos.get(), 'is_legacy_mirror', False))
        self.assertIsNotNone(mirrored.last_contacted_at)
        self.assertEqual(blank.memo, '')
        self.assertFalse(blank.memos.exists())
        self.assertIsNone(blank.last_contacted_at)
        self.assertEqual(len(callbacks), 1)
        self.assertFalse(NorthStarEvent.objects.filter(customer=mirrored).exists())
        callbacks[0]()
        self.assertEqual(NorthStarEvent.objects.filter(
            customer=mirrored,
            event_type=NorthStarEvent.CONSULTATION_MEMO_CREATED,
            payload={'source': CustomerMemo.SOURCE_MANUAL}).count(), 1)

        memo = mirrored.memos.get()
        changed = self.client.patch(
            f'/api/v1/customers/{mirrored.id}/memos/{memo.id}/',
            {'body': '일괄 수정', 'revision': 1}, format='json')
        self.assertEqual(changed.status_code, 200, changed.data)
        mirrored.refresh_from_db()
        self.assertEqual(mirrored.memo, '일괄 수정')

        deleted = self.client.delete(
            f'/api/v1/customers/{mirrored.id}/memos/{memo.id}/')
        self.assertEqual(deleted.status_code, 204)
        mirrored.refresh_from_db()
        self.assertEqual(mirrored.memo, '')

    def test_legacy_memo_length_validation_is_400_for_single_bulk_and_patch(self):
        too_long = '가' * 10_001

        single = self.client.post(
            '/api/v1/customers/', {'name': '긴 단건', 'memo': too_long}, format='json')
        self.assertEqual(single.status_code, 400, single.data)
        self.assertFalse(Customer.objects.filter(owner=self.user, name='긴 단건').exists())

        bulk = self.client.post('/api/v1/customers/bulk/', {'customers': [
            {'name': '긴 일괄', 'memo': too_long},
        ]}, format='json')
        self.assertEqual(bulk.status_code, 400, bulk.data)
        self.assertFalse(Customer.objects.filter(owner=self.user, name='긴 일괄').exists())

        patched = self.client.patch(self._url(), {'memo': too_long}, format='json')
        self.assertEqual(patched.status_code, 400, patched.data)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.memo, '')
        self.assertFalse(self.customer.memos.exists())

    def test_preexisting_over_limit_memo_normalized_noop_preserves_exact_source(self):
        raw = f"  {'가' * 10_001}  "
        self.customer.memo = raw
        self.customer.save(update_fields=['memo'])
        mirror = CustomerMemo.objects.create(
            owner=self.user, customer=self.customer,
            source=CustomerMemo.SOURCE_LEGACY, body=raw,
            is_legacy_mirror=True)

        response = self.client.patch(
            self._url(), {'memo': raw.strip()}, format='json')

        self.assertEqual(response.status_code, 200, response.data)
        self.customer.refresh_from_db()
        mirror.refresh_from_db()
        self.assertEqual(self.customer.memo, raw)
        self.assertEqual(mirror.body, raw)
        self.assertEqual(mirror.revision, 1)
        self.assertIsNone(mirror.edited_at)

    def test_bulk_analytics_integrity_error_does_not_rollback_primary_writes(self):
        from inpa.analytics.models import NorthStarEvent

        with mock.patch('inpa.analytics.models.NorthStarEvent.objects.create',
                        side_effect=IntegrityError('analytics unavailable')):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post('/api/v1/customers/bulk/', {'customers': [
                    {'name': '계측 오류 일괄 고객', 'memo': '일괄 메모'},
                ]}, format='json')

        self.assertEqual(response.status_code, 201, response.data)
        customer = Customer.objects.get(owner=self.user, name='계측 오류 일괄 고객')
        self.assertEqual(customer.memo, '일괄 메모')
        self.assertTrue(customer.memos.filter(
            source=CustomerMemo.SOURCE_MANUAL, body='일괄 메모').exists())
        self.assertIsNotNone(customer.last_contacted_at)

    def test_legacy_patch_does_not_bump_contact_but_other_substantive_change_does(self):
        self.assertIsNone(self.customer.last_contacted_at)

        legacy = self.client.patch(self._url(), {'memo': '호환 메모'}, format='json')
        self.assertEqual(legacy.status_code, 200, legacy.data)
        self.customer.refresh_from_db()
        self.assertIsNone(self.customer.last_contacted_at)

        before = timezone.now()
        substantive = self.client.patch(
            self._url(), {'memo': '새 호환 메모', 'name': '이름 변경'}, format='json')
        self.assertEqual(substantive.status_code, 200, substantive.data)
        self.customer.refresh_from_db()
        self.assertGreaterEqual(self.customer.last_contacted_at, before)

    def test_bridge_owner_isolation_is_non_enumerating_404(self):
        response = self.other_client.patch(self._url(), {'memo': '침입'}, format='json')

        self.assertEqual(response.status_code, 404)
        self.assertFalse(self.customer.memos.exists())

    def test_bridge_telemetry_is_content_safe_and_only_records_real_row_changes(self):
        from inpa.analytics.models import NorthStarEvent

        with self.captureOnCommitCallbacks(execute=True):
            created = self.client.patch(self._url(), {'memo': '첫 호환 메모'}, format='json')
            self.assertEqual(created.status_code, 200, created.data)
            edited = self.client.patch(self._url(), {'memo': '수정 호환 메모'}, format='json')
            self.assertEqual(edited.status_code, 200, edited.data)
            noop = self.client.patch(self._url(), {'memo': ' 수정 호환 메모 '}, format='json')
            self.assertEqual(noop.status_code, 200, noop.data)
            cleared = self.client.patch(self._url(), {'memo': ''}, format='json')
            self.assertEqual(cleared.status_code, 200, cleared.data)

        events = list(NorthStarEvent.objects.filter(customer=self.customer).order_by('id'))
        self.assertEqual(
            [event.event_type for event in events],
            [NorthStarEvent.CONSULTATION_MEMO_CREATED, NorthStarEvent.CONSULTATION_MEMO_EDITED])
        self.assertEqual([event.payload for event in events], [
            {'source': CustomerMemo.SOURCE_LEGACY},
            {'source': CustomerMemo.SOURCE_LEGACY},
        ])
        self.assertNotIn('첫 호환 메모', json.dumps([event.payload for event in events]))
        self.assertNotIn('수정 호환 메모', json.dumps([event.payload for event in events]))

    def test_bridge_analytics_failure_does_not_block_successful_write(self):
        with mock.patch('inpa.analytics.models.NorthStarEvent.objects.create',
                        side_effect=RuntimeError('analytics unavailable')):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.patch(self._url(), {'memo': '계측 실패에도 저장'}, format='json')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            self.customer.memos.get(source=CustomerMemo.SOURCE_LEGACY).body,
            '계측 실패에도 저장')

    def test_single_create_rolls_back_customer_when_manual_mirror_fails(self):
        with override_settings(FREE_TIER_UNLIMITED=False):
            _subscribe_free(self.user, limit_customer=5)
            with mock.patch('inpa.customers.serializers.sync_legacy_memo',
                            side_effect=RuntimeError('mirror failed')):
                with self.assertRaises(RuntimeError):
                    self.client.post('/api/v1/customers/', {'name': '롤백 단건', 'memo': '메모'}, format='json')

        self.assertFalse(Customer.objects.filter(owner=self.user, name='롤백 단건').exists())
        self.assertFalse(CustomerMemo.objects.filter(owner=self.user).exists())
        self.assertFalse(UsageMeter.objects.filter(user=self.user, action='customer').exists())

    def test_bulk_create_rolls_back_every_customer_when_manual_mirror_fails(self):
        from inpa.customers.memos import sync_legacy_memo

        calls = 0

        def fail_after_first(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError('mirror failed')
            return sync_legacy_memo(**kwargs)

        with mock.patch('inpa.customers.views.sync_legacy_memo', side_effect=fail_after_first):
            with self.assertRaises(RuntimeError):
                self.client.post('/api/v1/customers/bulk/', {'customers': [
                    {'name': '롤백 일괄 하나', 'memo': '메모 하나'},
                    {'name': '롤백 일괄 둘', 'memo': '메모 둘'},
                ]}, format='json')

        self.assertFalse(Customer.objects.filter(owner=self.user, name__startswith='롤백 일괄').exists())


class CustomerMemoAuditCommandTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('memo-audit@test.com', password='pass1234')

    def _audit(self):
        output = StringIO()
        call_command('audit_customer_memos', stdout=output)
        return json.loads(output.getvalue())

    def test_audit_accepts_legacy_and_post_release_manual_mirrors_and_skips_whitespace(self):
        legacy = Customer.objects.create(owner=self.user, name='이관 고객', memo='  기존 메모  ')
        CustomerMemo.objects.create(
            owner=self.user, customer=legacy, source=CustomerMemo.SOURCE_LEGACY,
            body='기존 메모', is_legacy_mirror=True)
        post_release = Customer.objects.create(owner=self.user, name='신규 고객', memo='새 메모')
        CustomerMemo.objects.create(
            owner=self.user, customer=post_release, source=CustomerMemo.SOURCE_MANUAL,
            body='새 메모', occurred_at=timezone.now(), is_legacy_mirror=True)
        Customer.objects.create(owner=self.user, name='공백 고객', memo=' \n\t ')

        result = self._audit()

        self.assertEqual(result['old_count'], 2)
        self.assertEqual(result['mirror_count'], 2)
        self.assertEqual(result['missing_count'], 0)
        self.assertEqual(result['mismatched_count'], 0)
        self.assertEqual(result['duplicate_count'], 0)
        self.assertEqual(result['owner_mismatch_count'], 0)
        self.assertEqual(result['old_hash'], result['mirror_hash'])
        self.assertEqual(result['sources'], [
            CustomerMemo.SOURCE_LEGACY, CustomerMemo.SOURCE_MANUAL])

    def test_audit_ignores_additional_ordinary_manual_memos(self):
        customer = Customer.objects.create(
            owner=self.user, name='여러 메모 고객', memo='호환 메모')
        CustomerMemo.objects.create(
            owner=self.user, customer=customer,
            source=CustomerMemo.SOURCE_LEGACY, body='호환 메모',
            is_legacy_mirror=True)
        CustomerMemo.objects.create(
            owner=self.user, customer=customer,
            source=CustomerMemo.SOURCE_MANUAL, body='추가 일반 메모',
            occurred_at=timezone.now())

        result = self._audit()

        self.assertEqual(result['old_count'], 1)
        self.assertEqual(result['mirror_count'], 1)
        self.assertEqual(result['mismatched_count'], 0)
        self.assertEqual(result['duplicate_count'], 0)
        self.assertEqual(result['old_hash'], result['mirror_hash'])

    def test_audit_fails_for_missing_and_mismatched_mirrors_without_content(self):
        missing = Customer.objects.create(owner=self.user, name='누락 고객', memo='누락 메모')
        mismatch = Customer.objects.create(owner=self.user, name='불일치 고객', memo='기준 메모')
        CustomerMemo.objects.create(
            owner=self.user, customer=mismatch, source=CustomerMemo.SOURCE_LEGACY,
            body='다른 내용', is_legacy_mirror=True)
        duplicate = Customer.objects.create(owner=self.user, name='중복 고객', memo='같은 내용')
        CustomerMemo.objects.create(
            owner=self.user, customer=duplicate, source=CustomerMemo.SOURCE_LEGACY,
            body='같은 내용', is_legacy_mirror=True)
        CustomerMemo.objects.create(
            owner=self.user, customer=duplicate, source=CustomerMemo.SOURCE_MANUAL,
            body='같은 내용', occurred_at=timezone.now())

        output = StringIO()
        with self.assertRaisesRegex(CommandError, '기존 메모 이관 대조가 일치하지 않습니다'):
            call_command('audit_customer_memos', stdout=output)

        result = json.loads(output.getvalue())
        self.assertEqual(result['missing_count'], 1)
        self.assertEqual(result['mismatched_count'], 1)
        self.assertEqual(result['duplicate_count'], 0)
        rendered = output.getvalue()
        for body in ('누락 메모', '기준 메모', '다른 내용', '같은 내용'):
            self.assertNotIn(body, rendered)

    def test_audit_fails_for_owner_drift_without_outputting_identity(self):
        other_owner = User.objects.create_user('memo-audit-other@test.com', password='pass1234')
        customer = Customer.objects.create(owner=self.user, name='소유자 대조', memo='대조 메모')
        memo = CustomerMemo.objects.create(
            owner=self.user, customer=customer, source=CustomerMemo.SOURCE_LEGACY,
            body='대조 메모', is_legacy_mirror=True)
        CustomerMemo.objects.filter(pk=memo.pk).update(owner=other_owner)

        output = StringIO()
        with self.assertRaisesRegex(CommandError, '기존 메모 이관 대조가 일치하지 않습니다'):
            call_command('audit_customer_memos', stdout=output)

        result = json.loads(output.getvalue())
        self.assertEqual(result['owner_mismatch_count'], 1)
        self.assertNotIn(other_owner.email, output.getvalue())


@override_settings(FREE_TIER_UNLIMITED=False)
class CustomerMemoCommitCallbackTests(TransactionTestCase):
    """실제 커밋 뒤 메모 계측 실패가 고객 저장 결과를 바꾸지 않는다."""

    def setUp(self):
        self.user, self.client = _make_planner('memo-commit-owner@test.com')
        _subscribe_free(self.user, limit_customer=5)

    def _bulk(self):
        return self.client.post('/api/v1/customers/bulk/', {'customers': [
            {'name': '커밋 고객 하나', 'memo': '메모 하나'},
            {'name': '커밋 고객 둘', 'memo': '메모 둘'},
        ]}, format='json')

    def _assert_primary_rows_committed(self):
        customers = Customer.objects.filter(
            owner=self.user, name__in=['커밋 고객 하나', '커밋 고객 둘']).order_by('name')
        self.assertEqual(customers.count(), 2)
        self.assertEqual(CustomerMemo.objects.filter(customer__in=customers).count(), 2)
        self.assertTrue(all(customer.last_contacted_at is not None for customer in customers))
        meter = UsageMeter.objects.get(
            user=self.user, action='customer', year_month=UsageMeter.current_month())
        self.assertEqual(meter.count, 2)

    def test_callback_query_operational_error_cannot_change_committed_bulk_response(self):
        from inpa.analytics.models import NorthStarEvent

        with mock.patch('inpa.customers.memos.Customer.objects.select_related',
                        side_effect=OperationalError('callback query unavailable')):
            response = self._bulk()

        self.assertEqual(response.status_code, 201, response.data)
        self._assert_primary_rows_committed()
        self.assertEqual(NorthStarEvent.objects.filter(sender=self.user).count(), 2)

    def test_unexpected_first_callback_error_does_not_block_later_bulk_callback(self):
        from inpa.analytics.events import log_event as real_log_event
        from inpa.analytics.models import NorthStarEvent

        calls = []

        def fail_first(*args, **kwargs):
            calls.append((args, kwargs))
            if len(calls) == 1:
                raise OperationalError('unexpected callback failure')
            return real_log_event(*args, **kwargs)

        with mock.patch('inpa.analytics.events.log_event', side_effect=fail_first):
            response = self._bulk()

        self.assertEqual(response.status_code, 201, response.data)
        self._assert_primary_rows_committed()
        self.assertEqual(len(calls), 2)
        second = Customer.objects.get(owner=self.user, name='커밋 고객 둘')
        self.assertEqual(NorthStarEvent.objects.filter(
            customer=second,
            event_type=NorthStarEvent.CONSULTATION_MEMO_CREATED,
            payload={'source': CustomerMemo.SOURCE_MANUAL}).count(), 1)


@override_settings(
    SHOWCASE_ACCOUNT_EMAIL='showcase@inpa.example',
    ANTHROPIC_API_KEY='test-provider-key',
    CLAUDE_MODEL_PARSE='test-model',
    INSURANCE_REVIEW_GATE_ENABLED=False,
)
class ShowcaseUploadTests(TestCase):
    """고객 내부 CRUD는 유지하고 파일·공개 인바운드 확산만 차단한다."""

    def setUp(self):
        cache.clear()
        self.user, self.client = _make_planner('showcase@inpa.example')
        Profile.objects.filter(user=self.user).update(is_showcase=True)
        self.user.profile.refresh_from_db()
        self.customer = Customer.objects.create(
            owner=self.user,
            name='준비된 고객',
            mobile_phone_number='010-1000-1000',
        )
        self.public = APIClient()

    def assert_showcase_restricted(self, response):
        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(response.json()['code'], 'SHOWCASE_ACTION_RESTRICTED')

    @staticmethod
    def image_upload(name='card.gif'):
        return SimpleUploadedFile(
            name,
            (
                b'GIF89a\x01\x00\x01\x00\x80\x00\x00'
                b'\x00\x00\x00\xff\xff\xff!\xf9\x04\x01'
                b'\x00\x00\x00\x00,\x00\x00\x00\x00\x01'
                b'\x00\x01\x00\x00\x02\x02D\x01\x00;'
            ),
            content_type='image/gif',
        )

    def test_business_card_upload_blocks_before_storage_save(self):
        storage = Customer._meta.get_field('business_card').storage
        with mock.patch.object(
            storage,
            'save',
            return_value='business_cards/showcase.gif',
        ) as save:
            response = self.client.patch(
                f'/api/v1/customers/{self.customer.pk}/',
                {'business_card': self.image_upload()},
                format='multipart',
            )

        self.assert_showcase_restricted(response)
        save.assert_not_called()

    def test_ordinary_business_card_upload_still_saves_once(self):
        ordinary, client = _make_planner('ordinary-card@test.com')
        customer = Customer.objects.create(owner=ordinary, name='일반 고객')
        storage = Customer._meta.get_field('business_card').storage
        with mock.patch.object(
            storage,
            'save',
            return_value='business_cards/ordinary.gif',
        ) as save:
            response = client.patch(
                f'/api/v1/customers/{customer.pk}/',
                {'business_card': self.image_upload('ordinary.gif')},
                format='multipart',
            )

        self.assertEqual(response.status_code, 200, response.content)
        save.assert_called_once()
        customer.refresh_from_db()
        self.assertEqual(
            customer.business_card.name,
            'business_cards/ordinary.gif',
        )

    def test_customer_memo_and_status_internal_update_remains_available(self):
        response = self.client.patch(
            f'/api/v1/customers/{self.customer.pk}/',
            {'memo': '시연 중 수정한 메모', 'status': 'hold'},
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.memo, '시연 중 수정한 메모')
        self.assertEqual(self.customer.status, 'hold')

    def test_public_self_diagnosis_blocks_before_customer_and_provider_work(self):
        payload = {
            'name': '시연 공개 고객',
            'phone': '010-2222-3333',
            'birth': '1990-01-01',
            'gender': '1',
            'consent_share': 'true',
            'consent_overseas': 'true',
            'file': SimpleUploadedFile(
                'policy.pdf',
                b'%PDF-1.7\nshowcase-policy',
                content_type='application/pdf',
            ),
        }
        with mock.patch(
            'inpa.insurances.self_diagnosis._extract_pdf_lines',
            return_value=(['시연 증권'], None),
        ) as extract, mock.patch(
            'inpa.insurances.self_diagnosis.claude_parse',
            return_value=None,
        ) as parse:
            response = self.public.post(
                f'/api/v1/d/{self.user.profile.ref_code}/',
                payload,
                format='multipart',
            )

        self.assert_showcase_restricted(response)
        extract.assert_not_called()
        parse.assert_not_called()
        self.assertFalse(
            Customer.objects.filter(
                owner=self.user,
                lead_source='self_diagnosis',
            ).exists()
        )

    def test_ordinary_public_self_diagnosis_still_calls_parser_once(self):
        ordinary, _client = _make_planner('ordinary-selfdiag@test.com')
        payload = {
            'name': '일반 공개 고객',
            'phone': '010-4444-5555',
            'birth': '1990-01-01',
            'gender': '2',
            'consent_share': 'true',
            'consent_overseas': 'true',
            'file': SimpleUploadedFile(
                'policy.pdf',
                b'%PDF-1.7\nordinary-policy',
                content_type='application/pdf',
            ),
        }
        with mock.patch(
            'inpa.insurances.self_diagnosis._extract_pdf_lines',
            return_value=(['일반 증권'], None),
        ) as extract, mock.patch(
            'inpa.insurances.self_diagnosis.claude_parse',
            return_value=None,
        ) as parse:
            response = self.public.post(
                f'/api/v1/d/{ordinary.profile.ref_code}/',
                payload,
                format='multipart',
            )

        self.assertEqual(response.status_code, 201, response.content)
        extract.assert_called_once()
        parse.assert_called_once()
        self.assertTrue(
            Customer.objects.filter(
                owner=ordinary,
                lead_source='self_diagnosis',
            ).exists()
        )

    def test_public_introduction_post_blocks_before_customer_or_notification(self):
        with mock.patch(
            'inpa.accounts.public.Notification.objects.create',
        ) as create_notification:
            response = self.public.post(
                f'/api/v1/p/{self.user.profile.ref_code}/',
                {
                    'name': '시연 상담 고객',
                    'phone': '010-7777-8888',
                    'agreed': 'true',
                },
                format='json',
            )

        self.assert_showcase_restricted(response)
        create_notification.assert_not_called()
        self.assertFalse(
            Customer.objects.filter(
                owner=self.user,
                lead_source='introduction',
            ).exists()
        )

    def test_ordinary_public_introduction_post_still_notifies_once(self):
        ordinary, _client = _make_planner('ordinary-intro@test.com')
        with mock.patch(
            'inpa.accounts.public.Notification.objects.create',
        ) as create_notification:
            response = self.public.post(
                f'/api/v1/p/{ordinary.profile.ref_code}/',
                {
                    'name': '일반 상담 고객',
                    'phone': '010-9999-0000',
                    'agreed': 'true',
                },
                format='json',
            )

        self.assertEqual(response.status_code, 201, response.content)
        create_notification.assert_called_once()
        self.assertTrue(
            Customer.objects.filter(
                owner=ordinary,
                lead_source='introduction',
            ).exists()
        )

    def test_public_read_surfaces_remain_available(self):
        self.assertEqual(
            self.public.get(
                f'/api/v1/p/{self.user.profile.ref_code}/',
            ).status_code,
            200,
        )
