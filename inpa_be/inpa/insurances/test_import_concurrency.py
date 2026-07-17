"""PostgreSQL release gates for insurance import transaction authority.

The HTTP cases prove service-level convergence.  Direct inserts separately
exercise PostgreSQL's partial unique index, which the owner row lock normally
prevents the HTTP path from reaching.
"""

import copy
import hashlib
import threading
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import timedelta
from tempfile import TemporaryDirectory
from unittest import mock

from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User
from inpa.analysis.models import AnalysisCategory, AnalysisDetail, AnalysisSubCategory
from inpa.billing.models import RuntimeConfig, UsageMeter
from inpa.customers.consent_texts import CONSENT_TEXTS_VERSION
from inpa.customers.models import ConsentLog, Customer

from . import import_services
from . import tasks as import_tasks
from . import views as insurance_views
from .import_contract import CoverageCandidate, ExtractedPDF, MaskedLine
from .import_storage import delete_source, source_key
from .management.commands.cleanup_insurance_imports import cleanup_imports
from .models import (
    CustomerInsurance,
    InsuranceCategory,
    InsuranceDetail,
    InsuranceExtractionJob,
    InsuranceImportCommand,
    InsuranceImportCreateRequest,
    InsuranceSubCategory,
    ManualInsuranceCommand,
)
from .serializers import CustomerInsuranceManualSerializer
from .tasks import NORMALIZATION_VERSION
from .test_import_confirm import _valid_material


PDF_BYTES = b'%PDF-1.7\nsynthetic-policy-body'
PDF_SHA = hashlib.sha256(PDF_BYTES).hexdigest()
THREAD_TIMEOUT = 5
PG_STATE_TIMEOUT = 3
POSTGRES_ONLY = unittest.skipUnless(
    connection.vendor == 'postgresql',
    'PostgreSQL row locks and partial indexes are required.',
)


def _planner(email):
    user = User.objects.create_user(email=email, password='inpaPass123!')
    user.is_active = True
    user.save(update_fields=['is_active'])
    Profile.objects.create(user=user, email_verified_at=timezone.now())
    token = Token.objects.create(user=user)
    return user, token.key


def _client(token_key):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Token {token_key}')
    return client


def _thread_call(callback):
    close_old_connections()
    try:
        return callback()
    finally:
        close_old_connections()


def _consent(customer):
    customer.consent_overseas_at = timezone.now()
    customer.save(update_fields=['consent_overseas_at'])
    ConsentLog.objects.create(
        customer=customer,
        scope=ConsentLog.SCOPE_OVERSEAS_MEDICAL,
        subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
        doc_version=CONSENT_TEXTS_VERSION,
    )


def _pdf():
    return SimpleUploadedFile(
        'synthetic-policy.pdf', PDF_BYTES, content_type='application/pdf')


def _extracted():
    line = MaskedLine(
        line_id='p01-l001', page=1, line=1,
        text_masked='일반암진단비 가입금액 3,000만원')
    candidate = CoverageCandidate(
        candidate_id='c00001', evidence_line_ids=(line.line_id,),
        text_masked=line.text_masked)
    return ExtractedPDF(
        file_sha256=PDF_SHA,
        file_size=len(PDF_BYTES),
        page_count=1,
        masked_lines=(line,),
        candidates=(candidate,),
        residual_scan_passed=True,
    )


def _post_import(token_key, customer_id, *, key=None):
    return _client(token_key).post(
        f'/api/v1/customers/{customer_id}/insurance-imports/',
        {'file': _pdf(), 'intent': 'add', 'portfolio_type': 1},
        format='multipart',
        HTTP_IDEMPOTENCY_KEY=str(key or uuid.uuid4()),
    )


def _catalog():
    analysis_category = AnalysisCategory.objects.create(name='[표준]진단-암')
    analysis_subcategory = AnalysisSubCategory.objects.create(
        category=analysis_category, name='일반암')
    analysis_detail = AnalysisDetail.objects.create(
        sub_category=analysis_subcategory, name='일반암진단비')
    category = InsuranceCategory.objects.create(name='진단-암')
    subcategory = InsuranceSubCategory.objects.create(
        category=category, name='일반암')
    catalog_detail = InsuranceDetail.objects.create(
        sub_category=subcategory, name='일반암진단비')
    catalog_detail.analysis_detail.add(analysis_detail)


def _review_job(owner, customer, *, digest, intent='add', target=None):
    line, candidate, draft, summary = _valid_material()
    return InsuranceExtractionJob.objects.create(
        owner=owner,
        customer=customer,
        target_insurance=target,
        target_insurance_version=(target.data_version if target else None),
        intent=intent,
        portfolio_type=1,
        status='review_required',
        file_sha256=digest,
        file_size=100,
        page_count=1,
        safe_display_name='synthetic-policy.pdf',
        source_expires_at=timezone.now() + timedelta(hours=1),
        masked_lines=[asdict(line)],
        draft_payload=draft,
        validation_summary={
            **summary,
            'intake_candidates': [{
                **asdict(candidate),
                'evidence_line_ids': list(candidate.evidence_line_ids),
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


def _confirm(token_key, job):
    return _client(token_key).post(
        f'/api/v1/insurance-imports/{job.pk}/confirm/',
        {
            'draft_version': job.draft_version,
            'target_insurance_version': job.target_insurance_version,
            'planner_confirmed_source_match': True,
        },
        format='json',
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )


def _backend_pid():
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_backend_pid()')
        return cursor.fetchone()[0]


def _backend_activity(pid):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT state, xact_start IS NOT NULL, wait_event_type,
                   wait_event, pg_blocking_pids(pid)
            FROM pg_stat_activity
            WHERE pid = %s
            """,
            [pid],
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return {
        'state': row[0],
        'in_transaction': row[1],
        'wait_event_type': row[2],
        'wait_event': row[3],
        'blockers': row[4],
    }


def _wait_for_blocked_backend(pid, *, blocker_pid=None):
    deadline = time.monotonic() + PG_STATE_TIMEOUT
    while time.monotonic() < deadline:
        activity = _backend_activity(pid)
        if activity is not None and activity['blockers']:
            if (blocker_pid is None
                    or blocker_pid in activity['blockers']):
                return activity
        time.sleep(0.02)
    raise AssertionError('Expected PostgreSQL backend did not enter lock wait.')


def _wait_for_peer_blocked_by(blocker_pid):
    deadline = time.monotonic() + PG_STATE_TIMEOUT
    while time.monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT pid, state, xact_start IS NOT NULL, wait_event_type,
                       wait_event, pg_blocking_pids(pid)
                FROM pg_stat_activity
                WHERE datname = current_database()
                  AND pid <> pg_backend_pid()
                  AND %s = ANY(pg_blocking_pids(pid))
                ORDER BY pid
                """,
                [blocker_pid],
            )
            row = cursor.fetchone()
        if row is not None:
            return {
                'pid': row[0],
                'state': row[1],
                'in_transaction': row[2],
                'wait_event_type': row[3],
                'wait_event': row[4],
                'blockers': row[5],
            }
        time.sleep(0.02)
    raise AssertionError('No PostgreSQL peer blocked behind the lock holder.')


class _PgBlockingProbe:
    """Prove one worker holds a transaction lock while its peer waits."""

    def __init__(self):
        self._start = threading.Barrier(2)
        self._mutex = threading.Lock()
        self._holder_pid = None
        self._holder_ready = threading.Event()
        self._release = threading.Event()

    def register_worker(self):
        self._start.wait(timeout=THREAD_TIMEOUT)

    def hold_first_after_lock(self):
        if not connection.in_atomic_block:
            raise AssertionError('Lock probe must run inside transaction.atomic().')
        pid = _backend_pid()
        with self._mutex:
            first = self._holder_pid is None
            if first:
                self._holder_pid = pid
        if first:
            self._holder_ready.set()
            if not self._release.wait(timeout=THREAD_TIMEOUT):
                raise AssertionError('PostgreSQL lock holder release timed out.')

    def assert_peer_blocked(self):
        if not self._holder_ready.wait(timeout=THREAD_TIMEOUT):
            raise AssertionError('PostgreSQL lock holder was not reached.')
        with self._mutex:
            holder_pid = self._holder_pid
        activity = _wait_for_peer_blocked_by(holder_pid)
        if activity['pid'] == holder_pid:
            raise AssertionError('Lock holder and blocked peer must be distinct.')
        if not activity['in_transaction']:
            raise AssertionError('Blocked backend has no open transaction.')
        return activity

    def release(self):
        self._release.set()


class _PgConcurrentTransactionsProbe:
    """Prove two independent workers are concurrently inside transactions."""

    def __init__(self):
        self._mutex = threading.Lock()
        self._inside_pids = []
        self._both_inside = threading.Event()
        self._release = threading.Event()

    def hold_both_inside_transaction(self):
        if not connection.in_atomic_block:
            raise AssertionError(
                'Concurrency probe must run inside transaction.atomic().')
        pid = _backend_pid()
        with self._mutex:
            self._inside_pids.append(pid)
            if len(self._inside_pids) == 2:
                self._both_inside.set()
        if not self._release.wait(timeout=THREAD_TIMEOUT):
            raise AssertionError('Concurrent transaction release timed out.')

    def assert_two_unblocked_transactions(self):
        if not self._both_inside.wait(timeout=THREAD_TIMEOUT):
            raise AssertionError(
                'Both independent transactions did not reach the safe seam.')
        with self._mutex:
            pids = tuple(self._inside_pids)
        if len(set(pids)) != 2:
            raise AssertionError('Workers must use two distinct PostgreSQL backends.')
        activities = [_backend_activity(pid) for pid in pids]
        if any(activity is None for activity in activities):
            raise AssertionError('A PostgreSQL worker disappeared before inspection.')
        if not all(activity['in_transaction'] for activity in activities):
            raise AssertionError('Both workers must have open transactions.')
        if any(activity['blockers'] for activity in activities):
            raise AssertionError('Independent owner transactions must not block.')
        return activities

    def release(self):
        self._release.set()


@POSTGRES_ONLY
@override_settings(
    INSURANCE_REVIEW_GATE_ENABLED=True,
    FREE_TIER_UNLIMITED=True,
)
class ImportReceptionPostgresConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def test_same_owner_customer_hash_converges_to_one_http_job(self):
        owner, token_key = _planner('pg-import-owner@example.invalid')
        customer = Customer.objects.create(owner=owner, name='합성고객')
        _consent(customer)
        extract_barrier = threading.Barrier(2)
        probe = _PgBlockingProbe()
        save_calls = []
        enqueue_calls = []

        def extract(_upload):
            extract_barrier.wait(timeout=THREAD_TIMEOUT)
            return _extracted()

        def save(job, _upload):
            save_calls.append(job.pk)
            probe.hold_first_after_lock()
            return source_key(job)

        def enqueue(job_id):
            enqueue_calls.append(job_id)

        def request(key):
            probe.register_worker()
            return _post_import(token_key, customer.pk, key=key)

        with mock.patch(
                'inpa.insurances.import_services.extract_pdf',
                side_effect=extract), mock.patch(
                'inpa.insurances.import_services.save_source',
                side_effect=save), mock.patch(
                'inpa.insurances.import_services._enqueue_job',
                side_effect=enqueue), mock.patch(
                'inpa.insurances.import_services.check_and_consume',
                wraps=import_services.check_and_consume) as credit:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(
                    _thread_call,
                    lambda key=uuid.uuid4(): request(key),
                ) for _ in range(2)]
                try:
                    probe.assert_peer_blocked()
                finally:
                    probe.release()
                responses = [
                    future.result(timeout=THREAD_TIMEOUT) for future in futures]

        self.assertEqual([response.status_code for response in responses],
                         [202, 202])
        self.assertEqual(
            {response.json()['job_id'] for response in responses},
            {str(InsuranceExtractionJob.objects.get().pk)},
        )
        self.assertEqual(InsuranceExtractionJob.objects.count(), 1)
        self.assertEqual(len(save_calls), 1)
        self.assertEqual(len(enqueue_calls), 1)
        self.assertLessEqual(credit.call_count, 1)
        self.assertEqual(
            InsuranceImportCreateRequest.objects.filter(owner=owner).count(),
            2,
        )

    def test_same_hash_different_owners_progress_independently(self):
        owner_a, token_a = _planner('pg-owner-a@example.invalid')
        owner_b, token_b = _planner('pg-owner-b@example.invalid')
        customer_a = Customer.objects.create(owner=owner_a, name='합성A')
        customer_b = Customer.objects.create(owner=owner_b, name='합성B')
        _consent(customer_a)
        _consent(customer_b)
        RuntimeConfig.objects.create(pk=1, free_tier_unlimited=True)
        extract_barrier = threading.Barrier(2)
        probe = _PgConcurrentTransactionsProbe()
        enqueue_calls = []

        def extract(_upload):
            extract_barrier.wait(timeout=THREAD_TIMEOUT)
            return _extracted()

        def save(job, _upload):
            probe.hold_both_inside_transaction()
            return source_key(job)

        with mock.patch(
                'inpa.insurances.import_services.extract_pdf',
                side_effect=extract), mock.patch(
                'inpa.insurances.import_services.save_source',
                side_effect=save), mock.patch(
                'inpa.insurances.import_services._enqueue_job',
                side_effect=enqueue_calls.append):
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(
                        _thread_call,
                        lambda: _post_import(token_a, customer_a.pk)),
                    executor.submit(
                        _thread_call,
                        lambda: _post_import(token_b, customer_b.pk)),
                ]
                try:
                    probe.assert_two_unblocked_transactions()
                finally:
                    probe.release()
                responses = [
                    future.result(timeout=THREAD_TIMEOUT) for future in futures]

        self.assertEqual([response.status_code for response in responses],
                         [202, 202])
        self.assertEqual(len({response.json()['job_id']
                              for response in responses}), 2)
        jobs = list(InsuranceExtractionJob.objects.order_by('owner_id'))
        self.assertEqual(len(jobs), 2)
        self.assertEqual({job.owner_id for job in jobs}, {owner_a.pk, owner_b.pk})
        self.assertEqual({job.customer_id for job in jobs},
                         {customer_a.pk, customer_b.pk})
        self.assertEqual({job.file_sha256 for job in jobs}, {PDF_SHA})
        self.assertEqual(len(enqueue_calls), 2)


@POSTGRES_ONLY
class ImportDatabaseAuthorityPostgresTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.owner, _ = _planner('pg-db-owner@example.invalid')
        self.customer = Customer.objects.create(owner=self.owner, name='합성고객')

    def _job_values(self):
        return {
            'owner': self.owner,
            'customer': self.customer,
            'intent': 'add',
            'portfolio_type': 1,
            'status': 'queued',
            'file_sha256': 'c' * 64,
            'file_size': 100,
            'safe_display_name': 'synthetic-policy.pdf',
        }

    def test_partial_unique_collision_terminal_reuse_and_predicate(self):
        probe = _PgBlockingProbe()

        def insert():
            def operation():
                probe.register_worker()
                try:
                    with transaction.atomic():
                        job = InsuranceExtractionJob.objects.create(
                            **self._job_values())
                        probe.hold_first_after_lock()
                        return ('created', str(job.pk))
                except IntegrityError:
                    return ('integrity', None)
            return _thread_call(operation)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = (executor.submit(insert), executor.submit(insert))
            try:
                probe.assert_peer_blocked()
            finally:
                probe.release()
            outcomes = [
                future.result(timeout=THREAD_TIMEOUT) for future in futures]

        self.assertEqual(sorted(outcome[0] for outcome in outcomes),
                         ['created', 'integrity'])
        self.assertEqual(InsuranceExtractionJob.objects.count(), 1)
        first = InsuranceExtractionJob.objects.get()
        first.status = 'failed'
        first.save(update_fields=['status'])
        replacement = InsuranceExtractionJob.objects.create(**self._job_values())
        self.assertNotEqual(first.pk, replacement.pk)

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT pg_get_expr(index.indpred, index.indrelid)
                FROM pg_index AS index
                JOIN pg_class AS relation ON relation.oid = index.indexrelid
                WHERE relation.relname = %s
                """,
                ['uniq_active_ins_import_hash'],
            )
            predicate = cursor.fetchone()[0]
        self.assertIsNotNone(predicate)
        for value in InsuranceExtractionJob.ACTIVE_STATUSES:
            self.assertIn(value, predicate)
        self.assertIn('status', predicate)

    def test_late_attempt_cas_waits_then_updates_zero_rows(self):
        old_attempt = uuid.uuid4()
        new_attempt = uuid.uuid4()
        job = InsuranceExtractionJob.objects.create(
            **{**self._job_values(), 'status': 'extracting'},
            attempt_uuid=old_attempt,
            draft_payload={'marker': 'new-attempt-only'},
        )
        owner_locked = threading.Event()
        release_owner = threading.Event()
        waiter_pid = []
        waiter_ready = threading.Event()

        def replace_attempt():
            def operation():
                with transaction.atomic():
                    locked = InsuranceExtractionJob.objects.select_for_update().get(
                        pk=job.pk)
                    locked.attempt_uuid = new_attempt
                    locked.status = 'validating'
                    locked.error_code = ''
                    locked.save(update_fields=['attempt_uuid', 'status', 'error_code'])
                    owner_locked.set()
                    if not release_owner.wait(timeout=THREAD_TIMEOUT):
                        raise AssertionError('attempt release timed out')
            return _thread_call(operation)

        def stale_update():
            def operation():
                with connection.cursor() as cursor:
                    cursor.execute('SELECT pg_backend_pid()')
                    waiter_pid.append(cursor.fetchone()[0])
                waiter_ready.set()
                return InsuranceExtractionJob.objects.filter(
                    pk=job.pk,
                    attempt_uuid=old_attempt,
                    status='extracting',
                ).update(
                    status='failed',
                    error_code='STALE_WORKER',
                    draft_payload={'marker': 'stale-overwrite'},
                )
            return _thread_call(operation)

        with ThreadPoolExecutor(max_workers=2) as executor:
            winner = executor.submit(replace_attempt)
            self.assertTrue(owner_locked.wait(timeout=THREAD_TIMEOUT))
            loser = executor.submit(stale_update)
            self.assertTrue(waiter_ready.wait(timeout=THREAD_TIMEOUT))
            self.assertTrue(_wait_for_blocked_backend(waiter_pid[0]))
            release_owner.set()
            winner.result(timeout=THREAD_TIMEOUT)
            updated = loser.result(timeout=THREAD_TIMEOUT)

        self.assertEqual(updated, 0)
        job.refresh_from_db()
        self.assertEqual(job.attempt_uuid, new_attempt)
        self.assertEqual(job.status, 'validating')
        self.assertEqual(job.error_code, '')
        self.assertEqual(job.draft_payload, {'marker': 'new-attempt-only'})

    def test_expired_source_cleanup_and_worker_claim_have_no_hybrid_state(self):
        now = timezone.now()
        job = InsuranceExtractionJob.objects.create(
            **self._job_values(),
            source_storage_key=(
                f'insurance-imports/{self.owner.pk}/{self.customer.pk}/'
                f'{uuid.uuid4()}/source.pdf'),
            source_expires_at=now - timedelta(seconds=1),
            validation_summary={
                '_system': {
                    'credit_consumed': True,
                    'credit_refunded': False,
                    'credit_year_month': '2026-07',
                },
            },
        )
        meter = UsageMeter.objects.create(
            user=self.owner, action='ocr', year_month='2026-07', count=1)
        probe = _PgBlockingProbe()
        original_lock_owner = import_tasks._lock_owner_row

        def race_owner_lock(owner_id):
            locked = original_lock_owner(owner_id)
            probe.hold_first_after_lock()
            return locked

        def claim():
            probe.register_worker()
            try:
                return ('claimed', import_tasks.claim_import(job.pk, now=now))
            except import_tasks.StaleAttempt:
                return ('stale', None)

        def cleanup():
            probe.register_worker()
            return cleanup_imports(now=now)

        with mock.patch(
                'inpa.insurances.tasks._lock_owner_row',
                side_effect=race_owner_lock), mock.patch(
                'inpa.insurances.tasks.delete_source'):
            with ThreadPoolExecutor(max_workers=2) as executor:
                claim_future = executor.submit(_thread_call, claim)
                cleanup_future = executor.submit(
                    _thread_call, cleanup)
                try:
                    probe.assert_peer_blocked()
                finally:
                    probe.release()
                claim_result = claim_future.result(timeout=THREAD_TIMEOUT)
                cleanup_result = cleanup_future.result(timeout=THREAD_TIMEOUT)

        job.refresh_from_db()
        meter.refresh_from_db()
        system = job.validation_summary['_system']
        if claim_result[0] == 'claimed':
            self.assertEqual(job.status, 'extracting')
            self.assertIsNotNone(job.attempt_uuid)
            self.assertGreater(job.lease_expires_at, now)
            self.assertEqual(meter.count, 1)
            self.assertFalse(system['credit_refunded'])
            self.assertEqual(cleanup_result['deleted'], 0)
        else:
            self.assertEqual(job.status, 'failed')
            self.assertEqual(job.error_code, 'SOURCE_EXPIRED')
            self.assertIsNone(job.attempt_uuid)
            self.assertIsNone(job.lease_expires_at)
            self.assertEqual(meter.count, 0)
            self.assertTrue(system['credit_refunded'])
            self.assertEqual(cleanup_result['deleted'], 1)


@POSTGRES_ONLY
@override_settings(INSURANCE_REVIEW_GATE_ENABLED=True)
class ImportCommandPostgresConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.owner, self.token_key = _planner(
            'pg-command-owner@example.invalid')
        self.customer = Customer.objects.create(
            owner=self.owner, name='합성고객', birth_day='1990.01.01')
        _catalog()

    def _race_confirm(self, jobs):
        probe = _PgBlockingProbe()
        original = import_services._materialize_confirmed_insurance

        def materialize(*args, **kwargs):
            probe.hold_first_after_lock()
            return original(*args, **kwargs)

        def request(job):
            probe.register_worker()
            return _confirm(self.token_key, job)

        with mock.patch(
                'inpa.insurances.import_services._materialize_confirmed_insurance',
                side_effect=materialize):
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(
                    _thread_call, lambda job=job: request(job)) for job in jobs]
                try:
                    probe.assert_peer_blocked()
                finally:
                    probe.release()
                return [future.result(timeout=THREAD_TIMEOUT)
                        for future in futures]

    def test_two_add_confirmations_preserve_both_policies(self):
        jobs = [
            _review_job(self.owner, self.customer, digest=value * 64)
            for value in ('d', 'e')
        ]
        responses = self._race_confirm(jobs)

        self.assertEqual(sorted(response.status_code for response in responses),
                         [200, 200])
        policies = CustomerInsurance.objects.filter(customer=self.customer)
        self.assertEqual(policies.count(), 2)
        self.assertEqual(
            set(policies.values_list('source_job_id', flat=True)),
            {job.pk for job in jobs},
        )
        self.assertEqual(policies.filter(review_status='confirmed').count(), 2)
        for job in jobs:
            job.refresh_from_db()
            self.assertEqual(job.status, 'confirmed')
            policy = CustomerInsurance.objects.get(source_job=job)
            self.assertEqual(policy.case_list.count(), 1)
            self.assertEqual(
                policy.case_list.get().assurance_amount, 30_000_000)

    def test_same_target_replace_has_one_winner_and_one_exact_rollback(self):
        target = CustomerInsurance.objects.create(
            customer=self.customer,
            insurance_type=2,
            portfolio_type=1,
            name='교체 대상',
            review_status='confirmed',
            analysis_included=True,
        )
        jobs = [
            _review_job(
                self.owner, self.customer, digest=value * 64,
                intent='replace', target=target)
            for value in ('f', '9')
        ]
        responses = self._race_confirm(jobs)

        self.assertEqual(sorted(response.status_code for response in responses),
                         [200, 409])
        conflict = next(response for response in responses
                        if response.status_code == 409)
        self.assertEqual(conflict.json()['code'], 'IMPORT_TARGET_CHANGED')
        target.refresh_from_db()
        self.assertEqual(target.review_status, 'superseded')
        self.assertFalse(target.analysis_included)
        self.assertEqual(target.data_version, 2)
        replacements = CustomerInsurance.objects.exclude(pk=target.pk)
        self.assertEqual(replacements.count(), 1)
        replacement = replacements.get()
        self.assertEqual(replacement.case_list.count(), 1)
        self.assertEqual(
            replacement.case_list.get().assurance_amount, 30_000_000)
        winner_job_id = replacement.source_job_id
        winner = next(job for job in jobs if job.pk == winner_job_id)
        winner.refresh_from_db()
        self.assertEqual(winner.status, 'confirmed')
        loser = next(job for job in jobs if job.pk != winner_job_id)
        loser.refresh_from_db()
        self.assertEqual(loser.status, 'review_required')
        self.assertEqual(
            InsuranceImportCommand.objects.filter(operation='confirm').count(),
            1,
        )

    def test_foreign_five_surfaces_are_404_and_mutate_nothing(self):
        job = _review_job(self.owner, self.customer, digest='1' * 64)
        foreign, foreign_token = _planner('pg-foreign@example.invalid')
        Customer.objects.create(owner=foreign, name='다른합성고객')
        client = _client(foreign_token)
        original = {
            'status': job.status,
            'draft_version': job.draft_version,
            'source_deleted_at': job.source_deleted_at,
            'commands': InsuranceImportCommand.objects.count(),
            'policies': CustomerInsurance.objects.count(),
        }
        urls = {
            'detail': f'/api/v1/insurance-imports/{job.pk}/',
            'draft': f'/api/v1/insurance-imports/{job.pk}/draft/',
            'source': f'/api/v1/insurance-imports/{job.pk}/source-url/',
            'confirm': f'/api/v1/insurance-imports/{job.pk}/confirm/',
            'cancel': f'/api/v1/insurance-imports/{job.pk}/cancel/',
        }
        responses = [
            client.get(urls['detail']),
            client.get(urls['draft']),
            client.get(urls['source']),
            client.post(urls['confirm'], {}, format='json'),
            client.post(urls['cancel'], {}, format='json'),
        ]
        self.assertEqual([response.status_code for response in responses],
                         [404, 404, 404, 404, 404])
        job.refresh_from_db()
        self.assertEqual(job.status, original['status'])
        self.assertEqual(job.draft_version, original['draft_version'])
        self.assertEqual(job.source_deleted_at, original['source_deleted_at'])
        self.assertEqual(InsuranceImportCommand.objects.count(),
                         original['commands'])
        self.assertEqual(CustomerInsurance.objects.count(),
                         original['policies'])

    def test_patch_cancel_race_has_only_ordered_contract_outcomes(self):
        job = _review_job(self.owner, self.customer, digest='2' * 64)
        original_draft = copy.deepcopy(job.draft_payload)
        patched_draft = copy.deepcopy(original_draft)
        patched_product = patched_draft['policy']['product_name']
        patched_product['value'] = '경합 뒤 상품'
        patched_product['state'] = 'manual'
        patched_product['review_reason_codes'] = []
        probe = _PgBlockingProbe()
        original_owned_job = import_services._owned_import_job

        def owned_job(*args, **kwargs):
            locked = original_owned_job(*args, **kwargs)
            if kwargs.get('for_update'):
                probe.hold_first_after_lock()
            return locked

        def patch():
            probe.register_worker()
            return _client(self.token_key).patch(
                f'/api/v1/insurance-imports/{job.pk}/draft/',
                {
                    'draft_version': 1,
                    'policy_changes': [{
                        'field': 'product_name', 'value': '경합 뒤 상품',
                    }],
                },
                format='json',
                HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
            )

        def cancel():
            probe.register_worker()
            return _client(self.token_key).post(
                f'/api/v1/insurance-imports/{job.pk}/cancel/',
                {}, format='json',
                HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
            )

        with mock.patch(
                'inpa.insurances.import_services._owned_import_job',
                side_effect=owned_job):
            with ThreadPoolExecutor(max_workers=2) as executor:
                patch_future = executor.submit(_thread_call, patch)
                cancel_future = executor.submit(_thread_call, cancel)
                try:
                    probe.assert_peer_blocked()
                finally:
                    probe.release()
                patch_response = patch_future.result(timeout=THREAD_TIMEOUT)
                cancel_response = cancel_future.result(timeout=THREAD_TIMEOUT)

        self.assertEqual(cancel_response.status_code, 200)
        self.assertIn(patch_response.status_code, {200, 409})
        job.refresh_from_db()
        self.assertEqual(job.status, 'canceled')
        cancel_commands = InsuranceImportCommand.objects.filter(
            job=job, operation='cancel')
        patch_commands = InsuranceImportCommand.objects.filter(
            job=job, operation='patch')
        self.assertEqual(cancel_commands.count(), 1)
        self.assertIsNotNone(cancel_commands.get().completed_at)
        if patch_response.status_code == 200:
            self.assertEqual(job.draft_version, 2)
            self.assertEqual(
                job.draft_payload['policy']['product_name']['value'],
                '경합 뒤 상품')
            self.assertEqual(job.draft_payload, patched_draft)
            self.assertEqual(patch_commands.count(), 1)
            self.assertIsNotNone(patch_commands.get().completed_at)
        else:
            self.assertEqual(patch_response.json()['code'], 'IMPORT_CANCELED')
            self.assertEqual(job.draft_version, 1)
            self.assertEqual(job.draft_payload, original_draft)
            self.assertEqual(patch_commands.count(), 0)
        self.assertEqual(
            InsuranceImportCommand.objects.filter(job=job).count(),
            cancel_commands.count() + patch_commands.count())

    def test_cleanup_deletes_only_expired_exact_storage_key(self):
        expired = _review_job(self.owner, self.customer, digest='3' * 64)
        sibling = _review_job(self.owner, self.customer, digest='4' * 64)
        now = timezone.now()
        expired.source_expires_at = now - timedelta(seconds=1)
        sibling.source_expires_at = now + timedelta(hours=1)
        expired.source_storage_key = source_key(expired)
        sibling.source_storage_key = source_key(sibling)
        expired.save(update_fields=['source_expires_at', 'source_storage_key'])
        sibling.save(update_fields=['source_expires_at', 'source_storage_key'])

        with TemporaryDirectory() as directory:
            storage = FileSystemStorage(location=directory)
            storage.save(expired.source_storage_key, ContentFile(b'expired'))
            storage.save(sibling.source_storage_key, ContentFile(b'sibling'))

            def exact_delete(job, *, key=None):
                return delete_source(job, key=key, storage=storage)

            with mock.patch(
                    'inpa.insurances.management.commands.cleanup_insurance_imports.delete_source',
                    side_effect=exact_delete):
                result = cleanup_imports(now=now)

            self.assertFalse(storage.exists(expired.source_storage_key))
            self.assertTrue(storage.exists(sibling.source_storage_key))
        self.assertEqual(result['deleted'], 1)
        expired.refresh_from_db()
        sibling.refresh_from_db()
        self.assertEqual(expired.source_deleted_at, now)
        self.assertIsNone(sibling.source_deleted_at)


class _ManualConcurrencyFixture:
    def setUp(self):
        super().setUp()
        self.owner, self.token_key = _planner(
            f'manual-concurrency-{uuid.uuid4()}@example.invalid')
        self.customer = Customer.objects.create(
            owner=self.owner, name='직접 입력 합성고객',
            birth_day='1990.01.01')
        _catalog()
        self.insurance = CustomerInsurance.objects.create(
            customer=self.customer,
            insurance_type=2,
            portfolio_type=1,
            name='직접 입력 합성보험',
            monthly_premiums=30_000,
            contractor_name='기존계약자',
            insured_name='기존피보험자',
            review_status='draft',
            analysis_included=False,
        )

    @property
    def basic_url(self):
        return (
            f'/api/v1/customers/{self.customer.pk}/insurances/manual/'
            f'{self.insurance.pk}/')

    @property
    def coverage_url(self):
        return (
            f'/api/v1/customers/{self.customer.pk}/insurances/manual/'
            f'{self.insurance.pk}/coverages/')

    def coverage_detail_url(self, case_id):
        return f'{self.coverage_url}{case_id}/'

    @property
    def confirm_url(self):
        return (
            f'/api/v1/customers/{self.customer.pk}/insurances/manual/'
            f'{self.insurance.pk}/confirm/')

    @property
    def exclude_url(self):
        return (
            f'/api/v1/customers/{self.customer.pk}/insurances/manual/'
            f'{self.insurance.pk}/exclude/')

    def coverage_payload(self, *, data_version, suffix=''):
        return {
            'data_version': data_version,
            'raw_name': f'직접 확인한 일반암진단비{suffix}',
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

    def post_coverage(self, *, data_version, suffix=''):
        return _client(self.token_key).post(
            self.coverage_url,
            self.coverage_payload(
                data_version=data_version, suffix=suffix),
            format='json',
        )


@POSTGRES_ONLY
class ManualReviewPostgresConcurrencyTests(
        _ManualConcurrencyFixture, TransactionTestCase):
    reset_sequences = True

    def _race_manual_insurance_lock(self, *callbacks):
        probe = _PgBlockingProbe()
        original_owned = insurance_views._owned_manual_insurance

        def owned(*args, **kwargs):
            insurance = original_owned(*args, **kwargs)
            if kwargs.get('lock'):
                probe.hold_first_after_lock()
            return insurance

        def request(callback):
            probe.register_worker()
            return callback()

        with mock.patch(
                'inpa.insurances.views._owned_manual_insurance',
                side_effect=owned):
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(
                    _thread_call,
                    lambda callback=callback: request(callback),
                ) for callback in callbacks]
                try:
                    probe.assert_peer_blocked()
                finally:
                    probe.release()
                return [future.result(timeout=THREAD_TIMEOUT)
                        for future in futures]

    def test_same_version_coverage_posts_have_one_winner(self):
        responses = self._race_manual_insurance_lock(
            lambda: self.post_coverage(data_version=1, suffix='A'),
            lambda: self.post_coverage(data_version=1, suffix='B'),
        )

        self.assertEqual(
            sorted(response.status_code for response in responses),
            [201, 409],
        )
        conflict = next(response for response in responses
                        if response.status_code == 409)
        self.assertEqual(conflict.json()['code'], 'INSURANCE_VERSION_CHANGED')
        self.insurance.refresh_from_db()
        self.assertEqual(self.insurance.data_version, 2)
        self.assertEqual(self.insurance.case_list.count(), 1)
        self.assertIn(
            self.insurance.case_list.get().raw_name,
            {'직접 확인한 일반암진단비A', '직접 확인한 일반암진단비B'},
        )

    def test_confirm_and_exclude_same_version_have_one_terminal_winner(self):
        created = self.post_coverage(data_version=1)
        self.assertEqual(created.status_code, 201, created.content)
        contested_version = created.json()['data_version']

        def confirm():
            return _client(self.token_key).post(
                self.confirm_url,
                {
                    'data_version': contested_version,
                    'planner_confirmed_contents': True,
                },
                format='json',
                HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
            )

        def exclude():
            return _client(self.token_key).post(
                self.exclude_url,
                {
                    'data_version': contested_version,
                    'reason': '설계사가 직접 분석에서 제외함',
                },
                format='json',
            )

        responses = self._race_manual_insurance_lock(confirm, exclude)

        self.assertEqual(
            sorted(response.status_code for response in responses),
            [200, 409],
        )
        conflict = next(response for response in responses
                        if response.status_code == 409)
        self.assertEqual(conflict.json()['code'], 'INSURANCE_VERSION_CHANGED')
        self.insurance.refresh_from_db()
        self.assertEqual(self.insurance.data_version, contested_version + 1)
        self.assertIn(self.insurance.review_status, {'confirmed', 'excluded'})
        if self.insurance.review_status == 'confirmed':
            self.assertTrue(self.insurance.analysis_included)
            self.assertEqual(self.insurance.confirmation_source, 'manual_entry')
            self.assertEqual(ManualInsuranceCommand.objects.count(), 1)
        else:
            self.assertFalse(self.insurance.analysis_included)
            self.assertEqual(
                self.insurance.review_exclusion_reason,
                '설계사가 직접 분석에서 제외함',
            )
            self.assertEqual(ManualInsuranceCommand.objects.count(), 0)

    def test_confirm_idempotency_replays_exact_completed_response(self):
        created = self.post_coverage(data_version=1)
        self.assertEqual(created.status_code, 201, created.content)
        key = str(uuid.uuid4())
        payload = {
            'data_version': created.json()['data_version'],
            'planner_confirmed_contents': True,
        }

        first = _client(self.token_key).post(
            self.confirm_url, payload, format='json',
            HTTP_IDEMPOTENCY_KEY=key)
        replay = _client(self.token_key).post(
            self.confirm_url, payload, format='json',
            HTTP_IDEMPOTENCY_KEY=key)

        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(replay.status_code, 200, replay.content)
        self.assertEqual(replay.json(), first.json())
        self.assertEqual(
            ManualInsuranceCommand.objects.filter(
                insurance=self.insurance,
                operation='confirm',
                idempotency_key=key,
            ).count(),
            1,
        )

    def test_same_idempotency_key_concurrent_confirm_replays_one_mutation(self):
        created = self.post_coverage(data_version=1)
        self.assertEqual(created.status_code, 201, created.content)
        contested_version = created.json()['data_version']
        key = str(uuid.uuid4())
        payload = {
            'data_version': contested_version,
            'planner_confirmed_contents': True,
        }

        def confirm():
            return _client(self.token_key).post(
                self.confirm_url,
                payload,
                format='json',
                HTTP_IDEMPOTENCY_KEY=key,
            )

        responses = self._race_manual_insurance_lock(confirm, confirm)

        self.assertEqual(
            [response.status_code for response in responses], [200, 200])
        self.assertEqual(responses[0].json(), responses[1].json())
        self.insurance.refresh_from_db()
        self.assertEqual(self.insurance.review_status, 'confirmed')
        self.assertTrue(self.insurance.analysis_included)
        self.assertEqual(self.insurance.data_version, contested_version + 1)
        self.assertEqual(
            ManualInsuranceCommand.objects.filter(
                insurance=self.insurance,
                operation='confirm',
                idempotency_key=key,
                completed_at__isnull=False,
            ).count(),
            1,
        )
        case = self.insurance.case_list.get()
        self.assertIsNotNone(case.confirmed_at)

    def test_same_version_basic_patches_have_one_whole_winner(self):
        probe = _PgBlockingProbe()
        original_is_valid = CustomerInsuranceManualSerializer.is_valid
        payloads = {
            'policy': {
                'data_version': 1,
                'name': '기본정보 A',
                'monthly_premiums': 11_111,
            },
            'people': {
                'data_version': 1,
                'contractor_name': '변경계약자 B',
                'insured_name': '변경피보험자 B',
            },
        }

        def gated_is_valid(serializer, *args, **kwargs):
            result = original_is_valid(serializer, *args, **kwargs)
            probe.hold_first_after_lock()
            return result

        def patch(label):
            probe.register_worker()
            response = _client(self.token_key).patch(
                self.basic_url, payloads[label], format='json')
            return label, response

        with mock.patch.object(
                CustomerInsuranceManualSerializer,
                'is_valid',
                new=gated_is_valid):
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(_thread_call, lambda: patch('policy')),
                    executor.submit(_thread_call, lambda: patch('people')),
                ]
                try:
                    probe.assert_peer_blocked()
                finally:
                    probe.release()
                outcomes = [
                    future.result(timeout=THREAD_TIMEOUT) for future in futures]

        self.assertEqual(
            sorted(response.status_code for _, response in outcomes),
            [200, 409],
        )
        winner = next(label for label, response in outcomes
                      if response.status_code == 200)
        conflict = next(response for _, response in outcomes
                        if response.status_code == 409)
        self.assertEqual(conflict.json()['code'], 'INSURANCE_VERSION_CHANGED')
        self.insurance.refresh_from_db()
        self.assertEqual(self.insurance.data_version, 2)
        if winner == 'policy':
            self.assertEqual(self.insurance.name, '기본정보 A')
            self.assertEqual(self.insurance.monthly_premiums, 11_111)
            self.assertEqual(self.insurance.contractor_name, '기존계약자')
            self.assertEqual(self.insurance.insured_name, '기존피보험자')
        else:
            self.assertEqual(self.insurance.name, '직접 입력 합성보험')
            self.assertEqual(self.insurance.monthly_premiums, 30_000)
            self.assertEqual(self.insurance.contractor_name, '변경계약자 B')
            self.assertEqual(self.insurance.insured_name, '변경피보험자 B')


class ManualResponseVersionAuthorityTests(
        _ManualConcurrencyFixture, TransactionTestCase):
    """A response owns its committed version even if the next write wins fast."""

    reset_sequences = True

    def _pause_first_request_after_outer_commit(
            self, first_request, second_request):
        first_committed = threading.Event()
        release_first = threading.Event()
        gate_state = threading.local()
        original_exit = transaction.Atomic.__exit__

        def gated_exit(atomic, exc_type, exc_value, traceback):
            result = original_exit(
                atomic, exc_type, exc_value, traceback)
            if (getattr(gate_state, 'pause_after_commit', False)
                    and exc_type is None
                    and not connection.in_atomic_block):
                gate_state.pause_after_commit = False
                first_committed.set()
                if not release_first.wait(timeout=THREAD_TIMEOUT):
                    raise AssertionError('first response release timed out')
            return result

        def gated_first():
            gate_state.pause_after_commit = True
            return first_request()

        with mock.patch.object(
                transaction.Atomic, '__exit__', new=gated_exit):
            with ThreadPoolExecutor(max_workers=2) as executor:
                first_future = executor.submit(_thread_call, gated_first)
                self.assertTrue(
                    first_committed.wait(timeout=THREAD_TIMEOUT),
                    'first mutation did not commit before its response',
                )
                second_response = _thread_call(second_request)
                release_first.set()
                first_response = first_future.result(timeout=THREAD_TIMEOUT)
        return first_response, second_response

    def test_post_response_keeps_its_own_committed_version(self):
        first, second = self._pause_first_request_after_outer_commit(
            lambda: self.post_coverage(data_version=1, suffix='첫번째'),
            lambda: self.post_coverage(data_version=2, suffix='두번째'),
        )

        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(second.status_code, 201, second.content)
        self.assertEqual(first.json()['data_version'], 2)
        self.assertEqual(second.json()['data_version'], 3)

    def test_patch_response_keeps_its_own_committed_version(self):
        created = self.post_coverage(data_version=1)
        self.assertEqual(created.status_code, 201, created.content)
        case_id = created.json()['id']
        first, second = self._pause_first_request_after_outer_commit(
            lambda: _client(self.token_key).patch(
                self.coverage_detail_url(case_id),
                {'data_version': 2, 'premium': 11_000},
                format='json'),
            lambda: _client(self.token_key).patch(
                self.coverage_detail_url(case_id),
                {'data_version': 3, 'premium': 22_000},
                format='json'),
        )

        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(first.json()['data_version'], 3)
        self.assertEqual(second.json()['data_version'], 4)

    def test_delete_response_keeps_its_own_committed_version(self):
        created = self.post_coverage(data_version=1)
        self.assertEqual(created.status_code, 201, created.content)
        case_id = created.json()['id']
        first, second = self._pause_first_request_after_outer_commit(
            lambda: _client(self.token_key).delete(
                self.coverage_detail_url(case_id),
                {'data_version': 2}, format='json'),
            lambda: self.post_coverage(data_version=3, suffix='다음담보'),
        )

        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(second.status_code, 201, second.content)
        self.assertEqual(first.json()['data_version'], 3)
        self.assertEqual(second.json()['data_version'], 4)
