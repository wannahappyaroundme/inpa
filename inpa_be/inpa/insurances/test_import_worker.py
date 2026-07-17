import copy
import json
import uuid
from dataclasses import asdict, replace
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from inpa.billing.models import ClaudeApiLog, UsageMeter
from inpa.customers.consent_texts import CONSENT_TEXTS_VERSION
from inpa.customers.models import ConsentLog, Customer

from .import_claude import ExtractionFailure, ExtractionResult
from .import_contract import (
    CoverageCandidate,
    ExtractedPDF,
    MaskedLine,
    PDFImportError,
    extracted_source_readability,
)
from .models import (
    InsuranceExtractionJob,
    InsuranceExtractionResult,
    InsuranceImportRuntimeConfig,
)


def _owner(email):
    return get_user_model().objects.create_user(
        email=email, password='worker-test-password')


def _consent(customer):
    customer.consent_overseas_at = timezone.now()
    customer.save(update_fields=['consent_overseas_at'])
    return ConsentLog.objects.create(
        customer=customer,
        scope=ConsentLog.SCOPE_OVERSEAS_MEDICAL,
        subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
        doc_version=CONSENT_TEXTS_VERSION,
    )


def _extracted():
    line = MaskedLine(
        line_id='p01-l001', page=1, line=1,
        text_masked='일반암진단비 가입금액 3,000만원')
    candidate = CoverageCandidate(
        candidate_id='c00001', evidence_line_ids=(line.line_id,),
        text_masked=line.text_masked)
    return ExtractedPDF(
        file_sha256='a' * 64, file_size=123, page_count=1,
        masked_lines=(line,), candidates=(candidate,),
        residual_scan_passed=True)


def _mixed_extracted():
    lines = tuple(
        MaskedLine(
            line_id=f'p{page:02d}-l001', page=page, line=1,
            text_masked=f'담보 {page} 가입금액 1,000만원')
        for page in range(3, 11)
    )
    candidates = tuple(
        CoverageCandidate(
            candidate_id=f'c{number:05d}',
            evidence_line_ids=(line.line_id,),
            text_masked=line.text_masked)
        for number, line in enumerate(lines, start=1)
    )
    return ExtractedPDF(
        file_sha256='a' * 64, file_size=123, page_count=10,
        masked_lines=lines, candidates=candidates,
        residual_scan_passed=True,
        image_only_page_count=2, image_only_pages=(1, 2))


def _provider_payload(*, company_code=None, rows=True):
    evidence = []
    return {
        'schema_version': 'insurance-review-v1',
        'policy': {
            'carrier_name': {'value': None, 'evidence_line_ids': evidence},
            'company_code': {
                'value': company_code, 'evidence_line_ids': evidence},
            'insurance_type': {'value': None, 'evidence_line_ids': evidence},
            'product_name': {'value': None, 'evidence_line_ids': evidence},
            'contract_date': {'value': None, 'evidence_line_ids': evidence},
            'expiry_date': {'value': None, 'evidence_line_ids': evidence},
            'monthly_premium': {'value': None, 'evidence_line_ids': evidence},
        },
        'coverage_rows': ([{
            'row_id': 'row-1',
            'raw_name': '일반암진단비',
            'assurance_amount': 30_000_000,
            'premium': None,
            'is_renewal': None,
            'renewal_period': None,
            'payment_period': None,
            'payment_period_unit': None,
            'warranty_period': None,
            'warranty_period_unit': None,
            'disposition': 'unmatched',
            'standard_category': None,
            'standard_subcategory': None,
            'standard_detail_name': None,
            'exclusion_reason': None,
            'source_candidate_ids': ['c00001'],
            'evidence_line_ids': ['p01-l001'],
        }] if rows else []),
    }


@override_settings(FREE_TIER_UNLIMITED=False)
class InsuranceImportWorkerTests(TestCase):
    def setUp(self):
        self.owner = _owner('worker-owner@test.com')
        self.customer = Customer.objects.create(
            owner=self.owner, name='고객', mobile_phone_number='010')
        _consent(self.customer)
        self.extracted = _extracted()
        self.source_key = None
        InsuranceImportRuntimeConfig.objects.update_or_create(
            pk=1,
            defaults={
                'per_owner_concurrency': 2,
                'global_concurrency': 4,
                'force_manual_carrier_codes': [],
            },
        )

    def make_job(self, *, owner=None, customer=None, status='queued',
                 credit_consumed=True, source_expires_at=None,
                 file_sha256=None, credit_year_month=None):
        owner = owner or self.owner
        customer = customer or self.customer
        job = InsuranceExtractionJob.objects.create(
            owner=owner,
            customer=customer,
            intent='add',
            portfolio_type=1,
            status=status,
            file_sha256=file_sha256 or self.extracted.file_sha256,
            file_size=self.extracted.file_size,
            page_count=self.extracted.page_count,
            safe_display_name='policy.pdf',
            source_expires_at=(
                source_expires_at
                or timezone.now() + timedelta(hours=24)),
            validation_summary={
                'intake_candidates': [
                    {**asdict(candidate),
                     'evidence_line_ids': list(candidate.evidence_line_ids)}
                    for candidate in self.extracted.candidates
                ],
                '_system': {
                    'credit_consumed': credit_consumed,
                    'credit_refunded': False,
                    'credit_year_month': (
                        credit_year_month or UsageMeter.current_month()),
                    'source_readability': extracted_source_readability(
                        self.extracted),
                },
            },
        )
        job.source_storage_key = (
            f'insurance-imports/{owner.pk}/{customer.pk}/{job.id}/source.pdf')
        job.save(update_fields=['source_storage_key'])
        self.source_key = job.source_storage_key
        if credit_consumed:
            UsageMeter.objects.get_or_create(
                user=owner,
                action='ocr',
                year_month=(credit_year_month or UsageMeter.current_month()),
                defaults={'count': 1},
            )
        return job

    def run_worker(self, job, *, extraction_result=None):
        from .tasks import run_insurance_import

        provider = extraction_result or ExtractionResult(
            payload=_provider_payload(), model_id='env-model',
            input_tokens=10, output_tokens=5)
        with mock.patch(
                'inpa.insurances.tasks._extract_job_pdf',
                return_value=self.extracted), \
                mock.patch(
                    'inpa.insurances.tasks.claude_extract',
                    return_value=provider), \
                mock.patch(
                    'inpa.insurances.tasks.delete_source'):
            return run_insurance_import(str(job.id))

    def test_worker_refetches_owner_customer_and_key_from_database(self):
        job = self.make_job()
        seen = {}

        def inspect_database_job(database_job):
            seen.update({
                'owner': database_job.owner_id,
                'customer': database_job.customer_id,
                'key': database_job.source_storage_key,
            })
            return self.extracted

        from .tasks import run_insurance_import
        with mock.patch(
                'inpa.insurances.tasks._extract_job_pdf',
                side_effect=inspect_database_job), \
                mock.patch(
                    'inpa.insurances.tasks.claude_extract',
                    return_value=ExtractionResult(
                        payload=_provider_payload(), model_id='env-model',
                        input_tokens=1, output_tokens=1)):
            run_insurance_import(str(job.id))

        self.assertEqual(seen, {
            'owner': self.owner.pk,
            'customer': self.customer.pk,
            'key': self.source_key,
        })

    def test_claim_uses_canonical_owner_config_job_lock_order(self):
        from . import tasks

        job = self.make_job()
        events = []
        owner_lock = tasks._lock_owner_row
        config_lock = tasks._locked_runtime_config
        job_lock = tasks._lock_job_row

        with mock.patch(
                'inpa.insurances.tasks._lock_owner_row',
                side_effect=lambda owner_id: (
                    events.append('owner') or owner_lock(owner_id))), \
                mock.patch(
                    'inpa.insurances.tasks._locked_runtime_config',
                    side_effect=lambda: (
                        events.append('config') or config_lock())), \
                mock.patch(
                    'inpa.insurances.tasks._lock_job_row',
                    side_effect=lambda job_id: (
                        events.append('job') or job_lock(job_id))):
            tasks.claim_import(job.id)

        self.assertEqual(events, ['owner', 'config', 'job'])

    def test_queued_failure_uses_canonical_owner_then_job_lock_order(self):
        from . import tasks

        job = self.make_job(credit_consumed=False)
        events = []
        owner_lock = tasks._lock_owner_row
        job_lock = tasks._lock_job_row
        with mock.patch(
                'inpa.insurances.tasks._lock_owner_row',
                side_effect=lambda owner_id: (
                    events.append('owner') or owner_lock(owner_id))), \
                mock.patch(
                    'inpa.insurances.tasks._lock_job_row',
                    side_effect=lambda job_id: (
                        events.append('job') or job_lock(job_id))), \
                mock.patch('inpa.insurances.tasks.delete_source'):
            failed = tasks._fail_queued_job(
                job.id,
                code='SOURCE_EXPIRED',
                error_type='source_expired',
                refund_credit=False,
            )

        self.assertTrue(failed)
        self.assertEqual(events, ['owner', 'job'])

    def test_owner_customer_scope_drift_fails_before_pdf_or_claude(self):
        job = self.make_job()
        other = _owner('scope-drift@test.com')
        Customer.objects.filter(pk=self.customer.pk).update(owner=other)
        from .tasks import run_insurance_import

        with mock.patch(
                'inpa.insurances.tasks._extract_job_pdf') as pdf, \
                mock.patch('inpa.insurances.tasks.claude_extract') as claude, \
                mock.patch('inpa.insurances.tasks.delete_source'):
            result = run_insurance_import(str(job.id))

        pdf.assert_not_called()
        claude.assert_not_called()
        job.refresh_from_db()
        self.assertEqual(result, 'failed')
        self.assertEqual(job.status, 'failed')
        self.assertEqual(job.error_code, 'SOURCE_NAMESPACE_MISMATCH')

    def test_late_attempt_cas_cannot_overwrite_new_attempt(self):
        from .tasks import StaleAttempt, _cas_transition, claim_import

        job = self.make_job()
        old_attempt = claim_import(job.id).attempt_uuid
        new_attempt = uuid.uuid4()
        InsuranceExtractionJob.objects.filter(pk=job.id).update(
            attempt_uuid=new_attempt, status='extracting')

        with self.assertRaises(StaleAttempt):
            _cas_transition(
                job.id, old_attempt, expected_status='extracting',
                next_status='validating')
        job.refresh_from_db()
        self.assertEqual(job.attempt_uuid, new_attempt)
        self.assertEqual(job.status, 'extracting')

    def test_late_provider_call_keeps_both_logs_but_cannot_overwrite_new_result(self):
        from .management.commands.cleanup_insurance_imports import cleanup_imports
        from .tasks import run_insurance_import

        job = self.make_job()
        old_provider = ExtractionResult(
            payload=_provider_payload(rows=False),
            model_id='old-attempt-model',
            input_tokens=20,
            output_tokens=2,
            latency_ms=220,
        )
        new_provider = ExtractionResult(
            payload=_provider_payload(company_code=7),
            model_id='new-attempt-model',
            input_tokens=10,
            output_tokens=1,
            latency_ms=110,
        )
        provider_call_count = 0
        nested_outcomes = []

        def provider_side_effect(*_args):
            nonlocal provider_call_count
            provider_call_count += 1
            if provider_call_count == 1:
                recovery_time = timezone.now()
                InsuranceExtractionJob.objects.filter(pk=job.pk).update(
                    lease_expires_at=recovery_time - timedelta(seconds=1))
                self.assertEqual(
                    cleanup_imports(now=recovery_time)['recovered'], 1)
                nested_outcomes.append(run_insurance_import(str(job.pk)))
                return old_provider
            return new_provider

        with mock.patch(
                'inpa.insurances.tasks._extract_job_pdf',
                return_value=self.extracted), mock.patch(
                    'inpa.insurances.tasks.claude_extract',
                    side_effect=provider_side_effect), mock.patch(
                        'inpa.insurances.tasks.delete_source'):
            old_outcome = run_insurance_import(str(job.pk))

        self.assertEqual(nested_outcomes, ['review_required'])
        self.assertEqual(old_outcome, 'stale')
        self.assertEqual(
            ClaudeApiLog.objects.filter(
                action='insurance_extraction').count(), 2)
        self.assertEqual(
            set(ClaudeApiLog.objects.filter(
                action='insurance_extraction').values_list(
                    'input_tokens', flat=True)),
            {10, 20},
        )
        result = InsuranceExtractionResult.objects.get(
            job=job, provider='claude')
        self.assertEqual(result.model_id, 'new-attempt-model')
        self.assertEqual(result.outcome, 'review_required')
        self.assertEqual(result.input_tokens, 10)
        self.assertEqual(result.latency_ms, 110)
        job.refresh_from_db()
        self.assertEqual(job.status, 'review_required')
        self.assertEqual(
            job.validation_summary['_system']['initial_metrics']
            ['carrier_code'],
            7,
        )

    def test_old_provider_return_after_new_claim_creates_no_result_snapshot(self):
        from .management.commands.cleanup_insurance_imports import cleanup_imports
        from .tasks import claim_import, run_insurance_import

        job = self.make_job()
        latest_claim = None

        def provider_side_effect(*_args):
            nonlocal latest_claim
            recovery_time = timezone.now()
            InsuranceExtractionJob.objects.filter(pk=job.pk).update(
                lease_expires_at=recovery_time - timedelta(seconds=1))
            self.assertEqual(cleanup_imports(now=recovery_time)['recovered'], 1)
            latest_claim = claim_import(job.pk)
            return ExtractionResult(
                payload=_provider_payload(company_code=7),
                model_id='stale-attempt-model',
                input_tokens=30,
                output_tokens=3,
                latency_ms=330,
            )

        with mock.patch(
                'inpa.insurances.tasks._extract_job_pdf',
                return_value=self.extracted), mock.patch(
                    'inpa.insurances.tasks.claude_extract',
                    side_effect=provider_side_effect), mock.patch(
                        'inpa.insurances.tasks.delete_source'):
            outcome = run_insurance_import(str(job.pk))

        self.assertEqual(outcome, 'stale')
        self.assertIsNotNone(latest_claim)
        self.assertEqual(
            ClaudeApiLog.objects.filter(
                action='insurance_extraction').count(), 1)
        self.assertFalse(
            InsuranceExtractionResult.objects.filter(job=job).exists())
        job.refresh_from_db()
        self.assertEqual(job.status, 'extracting')
        self.assertEqual(job.attempt_uuid, latest_claim.attempt_uuid)

    def test_per_owner_limit_is_checked_under_owner_row_lock(self):
        from .tasks import CapacityUnavailable, claim_import

        InsuranceImportRuntimeConfig.objects.filter(pk=1).update(
            per_owner_concurrency=1, global_concurrency=4)
        first = self.make_job()
        second = self.make_job(file_sha256='b' * 64)
        claim_import(first.id)
        with mock.patch(
                'inpa.insurances.tasks._lock_owner_row',
                wraps=__import__(
                    'inpa.insurances.tasks', fromlist=['_lock_owner_row']
                )._lock_owner_row) as owner_lock:
            with self.assertRaises(CapacityUnavailable):
                claim_import(second.id)
        owner_lock.assert_called_once_with(self.owner.pk)

    def test_different_owners_can_run_in_parallel(self):
        from .tasks import claim_import

        InsuranceImportRuntimeConfig.objects.filter(pk=1).update(
            per_owner_concurrency=1, global_concurrency=2)
        other = _owner('worker-other@test.com')
        other_customer = Customer.objects.create(
            owner=other, name='다른 고객', mobile_phone_number='011')
        _consent(other_customer)
        first = self.make_job()
        second = self.make_job(owner=other, customer=other_customer,
                               credit_consumed=False)

        self.assertNotEqual(
            claim_import(first.id).attempt_uuid,
            claim_import(second.id).attempt_uuid,
        )

        # SQLite proves separate-owner lease accounting, not simultaneous row
        # lock progress. Real PostgreSQL overlap remains a Task 15 staging gate.

    def test_transport_retry_does_not_consume_credit_twice(self):
        job = self.make_job()
        meter = UsageMeter.objects.get(user=self.owner, action='ocr')
        self.assertEqual(meter.count, 1)

        first = self.run_worker(job)
        redelivery = self.run_worker(job)

        meter.refresh_from_db()
        self.assertEqual(meter.count, 1)
        job.refresh_from_db()
        self.assertEqual(first, 'review_required')
        self.assertEqual(redelivery, 'stale')
        self.assertEqual(job.status, 'review_required')
        self.assertEqual(
            InsuranceExtractionResult.objects.filter(job=job).count(), 1)
        self.assertEqual(
            ClaudeApiLog.objects.filter(
                action='insurance_extraction').count(), 1)

    def test_provider_success_has_one_cost_ledger_row_and_frozen_initial_metrics(self):
        job = self.make_job()
        provider = ExtractionResult(
            payload=_provider_payload(company_code=7),
            model_id='claude-opus-4-8',
            input_tokens=100,
            output_tokens=20,
            cache_read_input_tokens=30,
            cache_creation_input_tokens=40,
            latency_ms=125,
        )

        outcome = self.run_worker(job, extraction_result=provider)

        self.assertEqual(outcome, 'review_required')
        log = ClaudeApiLog.objects.get(action='insurance_extraction')
        self.assertEqual(log.user_id, self.owner.pk)
        self.assertEqual(log.model, 'claude-opus-4-8')
        self.assertEqual(log.parse_outcome, ClaudeApiLog.OUTCOME_SUCCESS)
        self.assertEqual(
            (log.input_tokens, log.output_tokens,
             log.cache_read_input_tokens,
             log.cache_creation_input_tokens),
            (100, 20, 30, 40),
        )
        self.assertEqual(
            (log.carrier_code, log.matched_count, log.unmatched_count),
            (7, 0, 1),
        )

        result = InsuranceExtractionResult.objects.get(
            job=job, provider='claude')
        self.assertEqual(result.latency_ms, 125)
        self.assertEqual(result.input_tokens, 100)
        self.assertEqual(result.output_tokens, 20)
        self.assertEqual(result.outcome, 'review_required')
        self.assertGreater(result.estimated_cost_krw, 0)

        job.refresh_from_db()
        metrics = job.validation_summary['_system']['initial_metrics']
        self.assertEqual(set(metrics), {
            'schema_version', 'carrier_code', 'detected_candidates',
            'assigned', 'unmatched', 'intentionally_excluded',
            'coverage_row_count', 'coverage_state_counts',
            'policy_field_count', 'policy_state_counts',
            'provider_rows', 'zero_provider_rows',
        })
        self.assertEqual(
            metrics['schema_version'],
            'insurance-extraction-initial-metrics-v1')
        self.assertEqual(metrics['carrier_code'], 7)
        self.assertEqual(metrics['provider_rows'], 1)
        self.assertEqual(metrics['zero_provider_rows'], 0)
        self.assertEqual(
            metrics['detected_candidates'],
            metrics['assigned'] + metrics['unmatched']
            + metrics['intentionally_excluded'],
        )
        allowed_states = {
            'review_ready', 'needs_review', 'no_evidence',
            'unmatched', 'invalid', 'manual',
        }
        self.assertEqual(set(metrics['coverage_state_counts']), allowed_states)
        self.assertEqual(set(metrics['policy_state_counts']), allowed_states)
        self.assertEqual(
            sum(metrics['coverage_state_counts'].values()),
            metrics['coverage_row_count'])
        self.assertEqual(
            sum(metrics['policy_state_counts'].values()),
            metrics['policy_field_count'])

    def test_post_provider_persistence_failure_keeps_success_log_and_safe_snapshot(self):
        job = self.make_job()
        provider = ExtractionResult(
            payload=_provider_payload(company_code=7),
            model_id='claude-opus-4-8',
            input_tokens=41,
            output_tokens=9,
            latency_ms=246,
        )
        from .tasks import run_insurance_import

        with mock.patch(
                'inpa.insurances.tasks._extract_job_pdf',
                return_value=self.extracted), mock.patch(
                    'inpa.insurances.tasks.claude_extract',
                    return_value=provider), mock.patch(
                        'inpa.insurances.tasks._save_review_draft',
                        side_effect=RuntimeError('persistence failed')), \
                mock.patch('inpa.insurances.tasks.delete_source') as delete:
            outcome = run_insurance_import(str(job.pk))

        self.assertEqual(outcome, 'failed')
        log = ClaudeApiLog.objects.get(action='insurance_extraction')
        self.assertEqual(log.parse_outcome, ClaudeApiLog.OUTCOME_SUCCESS)
        self.assertEqual((log.input_tokens, log.output_tokens), (41, 9))
        result = InsuranceExtractionResult.objects.get(
            job=job, provider='claude')
        self.assertEqual(
            result.outcome, 'post_provider_persistence_failure')
        self.assertEqual(result.structured_payload, {})
        self.assertEqual(
            (result.model_id, result.input_tokens, result.output_tokens,
             result.latency_ms),
            ('claude-opus-4-8', 41, 9, 246),
        )
        job.refresh_from_db()
        self.assertEqual(
            (job.status, job.error_code, job.error_type),
            ('failed', 'WORKER_FAILED', 'RuntimeError'),
        )
        self.assertEqual(job.draft_payload, {})
        metrics = job.validation_summary['_system']['initial_metrics']
        self.assertEqual(metrics['provider_rows'], 1)
        self.assertEqual(metrics['zero_provider_rows'], 0)
        self.assertEqual(metrics['coverage_row_count'], 1)
        self.assertEqual(sum(metrics['coverage_state_counts'].values()), 1)
        serialized = json.dumps({
            'result': result.structured_payload,
            'draft': job.draft_payload,
            'metrics': metrics,
        }, ensure_ascii=False)
        self.assertNotIn('일반암진단비', serialized)
        self.assertEqual(
            UsageMeter.objects.get(user=self.owner, action='ocr').count, 0)
        delete.assert_called_once_with(job, key=self.source_key)

    def test_stale_post_provider_persistence_failure_cannot_overwrite_new_attempt(self):
        from .management.commands.cleanup_insurance_imports import cleanup_imports
        from .tasks import claim_import, run_insurance_import

        job = self.make_job()
        latest_claim = None

        def fail_after_new_claim(*_args, **_kwargs):
            nonlocal latest_claim
            recovery_time = timezone.now()
            InsuranceExtractionJob.objects.filter(pk=job.pk).update(
                lease_expires_at=recovery_time - timedelta(seconds=1))
            self.assertEqual(cleanup_imports(now=recovery_time)['recovered'], 1)
            latest_claim = claim_import(job.pk)
            InsuranceExtractionResult.objects.create(
                job=job,
                provider='claude',
                model_id='new-attempt-model',
                outcome='review_required',
                input_tokens=99,
                output_tokens=8,
                latency_ms=700,
            )
            raise RuntimeError('old persistence failed')

        provider = ExtractionResult(
            payload=_provider_payload(company_code=7),
            model_id='old-attempt-model',
            input_tokens=20,
            output_tokens=2,
            latency_ms=220,
        )
        with mock.patch(
                'inpa.insurances.tasks._extract_job_pdf',
                return_value=self.extracted), mock.patch(
                    'inpa.insurances.tasks.claude_extract',
                    return_value=provider), mock.patch(
                        'inpa.insurances.tasks._save_review_draft',
                        side_effect=fail_after_new_claim), mock.patch(
                            'inpa.insurances.tasks.delete_source') as delete:
            outcome = run_insurance_import(str(job.pk))

        self.assertEqual(outcome, 'stale')
        self.assertIsNotNone(latest_claim)
        self.assertEqual(
            ClaudeApiLog.objects.filter(
                action='insurance_extraction',
                parse_outcome=ClaudeApiLog.OUTCOME_SUCCESS,
            ).count(),
            1,
        )
        result = InsuranceExtractionResult.objects.get(
            job=job, provider='claude')
        self.assertEqual(
            (result.model_id, result.outcome, result.input_tokens),
            ('new-attempt-model', 'review_required', 99),
        )
        job.refresh_from_db()
        self.assertEqual(job.status, 'extracting')
        self.assertEqual(job.attempt_uuid, latest_claim.attempt_uuid)
        self.assertNotIn(
            'initial_metrics', job.validation_summary.get('_system', {}))
        delete.assert_not_called()

    def test_worker_rechecks_current_consent_immediately_before_claude(self):
        job = self.make_job()
        events = []
        from . import tasks
        provider_payload = _provider_payload()
        provider_payload['_system'] = {'provider_started': False}

        def inspect_reserved_provider_call(*_args):
            events.append('claude')
            job.refresh_from_db()
            self.assertEqual(job.status, 'validating')
            self.assertTrue(
                job.validation_summary['_system']['provider_started'])
            return ExtractionResult(
                payload=provider_payload, model_id='env-model',
                input_tokens=1, output_tokens=1)

        with mock.patch(
                'inpa.insurances.tasks._extract_job_pdf',
                side_effect=lambda _job: (events.append('pdf') or self.extracted)), \
                mock.patch(
                    'inpa.insurances.tasks.has_current_overseas_consent',
                    side_effect=lambda _customer: (events.append('consent') or True)), \
                mock.patch(
                    'inpa.insurances.tasks.claude_extract',
                    side_effect=inspect_reserved_provider_call):
            outcome = tasks.run_insurance_import(str(job.id))

        self.assertEqual(outcome, 'review_required')
        self.assertEqual(events, ['pdf', 'consent', 'claude'])
        job.refresh_from_db()
        self.assertTrue(
            job.validation_summary['_system']['provider_started'])
        self.assertNotIn('_system', job.draft_payload)

    def test_worker_requires_true_residual_proof_before_provider(self):
        job = self.make_job(credit_year_month='2026-06')
        unsafe = replace(self.extracted, residual_scan_passed=False)
        from .tasks import run_insurance_import

        with mock.patch(
                'inpa.insurances.tasks._extract_job_pdf',
                return_value=unsafe), mock.patch(
                    'inpa.insurances.tasks.claude_extract') as claude, \
                mock.patch(
                    'inpa.insurances.tasks.delete_source') as delete:
            outcome = run_insurance_import(str(job.id))

        self.assertEqual(outcome, 'failed')
        claude.assert_not_called()
        self.assertFalse(
            InsuranceExtractionResult.objects.filter(job=job).exists())
        job.refresh_from_db()
        self.assertEqual(job.error_code, 'PII_REDACTION_UNCERTAIN')
        self.assertTrue(
            job.validation_summary['_system']['credit_refunded'])
        self.assertEqual(
            UsageMeter.objects.get(
                user=self.owner, action='ocr', year_month='2026-06').count,
            0,
        )
        delete.assert_called_once_with(job, key=self.source_key)

    def test_ambiguous_unlabeled_identity_is_absent_from_provider_payload(self):
        extracted = replace(
            self.extracted,
            quarantined_line_count=1,
            quarantined_line_ids=('p01-l002',),
        )
        self.extracted = extracted
        job = self.make_job(credit_year_month='2026-06')
        from .tasks import run_insurance_import

        def inspect_provider_payload(masked_lines, _candidates, _schema):
            self.assertNotIn('김가온 부가표기', repr(masked_lines))
            return ExtractionResult(
                payload=_provider_payload(), model_id='env-model',
                input_tokens=1, output_tokens=1)

        with mock.patch(
                'inpa.insurances.tasks._extract_job_pdf',
                return_value=extracted), mock.patch(
                    'inpa.insurances.tasks.claude_extract',
                    side_effect=inspect_provider_payload) as provider:
            outcome = run_insurance_import(str(job.id))

        self.assertEqual(outcome, 'review_required')
        provider.assert_called_once()
        job.refresh_from_db()
        self.assertNotIn('김가온 부가표기', repr(job.masked_lines))

    def test_standalone_privacy_variants_are_removed_before_worker_payload(self):
        variants = (
            '김솔',
            '남궁가온',
            '가온동 123-4',
            '테스트광역시 가림구 보호로',
            '테스트광역시 가림구 보호리',
        )
        from .import_pdf_mask import pseudonymize_page_lines

        for synthetic_value in variants:
            with self.subTest(shape=len(synthetic_value)):
                result = pseudonymize_page_lines(((
                    synthetic_value,
                    '일반암진단비 3,000만원',
                ),))

                self.assertEqual(result.pages[0][0], '')
                self.assertGreaterEqual(result.quarantined_line_count, 1)
                self.assertNotIn(synthetic_value, repr(result.pages))

    def test_mixed_privacy_analysis_is_removed_before_worker_payload(self):
        variants = (
            '김솔 3,000만원',
            '남궁가온 일반암진단비 3,000만원',
            '테스트광역시 가림구 보호로 123 '
            '보험료 30,000원',
        )
        from .import_pdf_mask import pseudonymize_page_lines

        for synthetic_line in variants:
            with self.subTest(shape=len(synthetic_line)):
                result = pseudonymize_page_lines(((synthetic_line,),))

                self.assertEqual(result.pages, (('',),))
                self.assertEqual(result.quarantined_line_count, 1)
                self.assertEqual(
                    result.analysis_signal_quarantined_line_count, 1)
                self.assertNotIn(synthetic_line, repr(result.pages))

    def test_additional_name_variants_are_removed_before_worker_payload(self):
        variants = (
            '김 가온',
            '김가온별',
            '김가온별빛',
            'ALEX MORGAN KIM',
            '김 가온 보험료 30,000원',
        )
        from .import_pdf_mask import pseudonymize_page_lines

        for synthetic_value in variants:
            with self.subTest(shape=len(synthetic_value)):
                result = pseudonymize_page_lines(((synthetic_value,),))

                self.assertEqual(result.pages, (('',),))
                self.assertEqual(result.quarantined_line_count, 1)
                self.assertNotIn(synthetic_value, repr(result.pages))

    def test_analysis_quarantine_adds_manual_source_review_issue(self):
        self.extracted = replace(
            self.extracted,
            quarantined_line_count=1,
            quarantined_line_ids=('p01-l002',),
            analysis_signal_quarantined_line_count=1,
            analysis_signal_quarantined_line_ids=('p01-l002',),
        )
        job = self.make_job()

        outcome = self.run_worker(job)

        self.assertEqual(outcome, 'review_required')
        job.refresh_from_db()
        self.assertIn({
            'code': 'SOURCE_PAGE_MANUAL_REVIEW_REQUIRED',
            'state': 'needs_review',
            'scope': 'document',
            'row_id': None,
            'field': 'source_page',
        }, job.draft_payload['validation']['issues'])
        self.assertEqual(
            job.validation_summary['pages_requiring_manual_source_review'],
            [1],
        )
        self.assertEqual(
            job.validation_summary['analysis_signal_quarantined_line_count'],
            1,
        )

    def test_mixed_source_readability_survives_worker_and_images_never_reach_ai(self):
        self.extracted = _mixed_extracted()
        job = self.make_job()
        provider_payload = _provider_payload()
        provider_payload['coverage_rows'][0].update({
            'source_candidate_ids': ['c00001'],
            'evidence_line_ids': ['p03-l001'],
        })
        provider = ExtractionResult(
            payload=provider_payload, model_id='env-model',
            input_tokens=1, output_tokens=1)
        from .tasks import run_insurance_import
        with mock.patch(
                'inpa.insurances.tasks._extract_job_pdf',
                return_value=self.extracted), mock.patch(
                    'inpa.insurances.tasks.claude_extract',
                    return_value=provider) as claude:
            outcome = run_insurance_import(str(job.id))

        self.assertEqual(outcome, 'review_required')
        sent_lines, sent_candidates, _schema = claude.call_args.args
        self.assertEqual(sent_lines, self.extracted.masked_lines)
        self.assertEqual(sent_candidates, self.extracted.candidates)
        self.assertTrue(all(line.page >= 3 for line in sent_lines))
        job.refresh_from_db()
        system = job.validation_summary['_system']
        self.assertEqual(
            system['source_readability'],
            extracted_source_readability(self.extracted),
        )
        self.assertTrue(system['credit_consumed'])
        self.assertTrue(system['provider_started'])

    def test_worker_fails_closed_when_reextract_readability_differs_from_intake(self):
        job = self.make_job()
        changed = ExtractedPDF(
            file_sha256=self.extracted.file_sha256,
            file_size=self.extracted.file_size,
            page_count=2,
            masked_lines=self.extracted.masked_lines,
            candidates=self.extracted.candidates,
            image_only_page_count=1,
            image_only_pages=(2,),
        )
        from .tasks import run_insurance_import
        with mock.patch(
                'inpa.insurances.tasks._extract_job_pdf',
                return_value=changed), mock.patch(
                    'inpa.insurances.tasks.claude_extract') as claude, \
                mock.patch('inpa.insurances.tasks.delete_source'):
            outcome = run_insurance_import(str(job.id))

        self.assertEqual(outcome, 'failed')
        claude.assert_not_called()
        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        self.assertEqual(job.error_code, 'SOURCE_READABILITY_MISMATCH')
        self.assertEqual(
            job.validation_summary['_system']['source_readability'],
            extracted_source_readability(self.extracted),
        )

    def test_cancel_at_provider_entry_is_conflict_and_provider_completes(self):
        job = self.make_job(credit_year_month='2026-06')
        from .import_services import ImportReceptionError, cancel_import
        from .tasks import run_insurance_import
        observed = {}
        provider = ExtractionResult(
            payload=_provider_payload(), model_id='env-model',
            input_tokens=1, output_tokens=1)

        def cancel_at_provider_entry(*_args):
            try:
                cancel_import(
                    owner=self.owner,
                    job_id=job.id,
                    idempotency_key=uuid.uuid4(),
                )
            except ImportReceptionError as exc:
                observed.update(code=exc.code, status=exc.status_code)
            else:
                observed.update(code='canceled', status=200)
            return provider

        with mock.patch(
                'inpa.insurances.tasks._extract_job_pdf',
                return_value=self.extracted), \
                mock.patch(
                    'inpa.insurances.tasks.claude_extract',
                    side_effect=cancel_at_provider_entry) as claude, \
                mock.patch(
                    'inpa.insurances.import_services.delete_source') as delete:
            with self.captureOnCommitCallbacks(execute=True):
                outcome = run_insurance_import(str(job.id))

        self.assertEqual(observed, {
            'code': 'CANCEL_IN_PROGRESS', 'status': 409})
        self.assertEqual(outcome, 'review_required')
        claude.assert_called_once()
        job.refresh_from_db()
        self.assertEqual(job.status, 'review_required')
        self.assertTrue(
            job.validation_summary['_system']['provider_started'])
        self.assertEqual(
            UsageMeter.objects.get(
                user=self.owner, action='ocr', year_month='2026-06').count,
            1,
        )
        delete.assert_not_called()

    def test_cancel_during_pdf_extract_blocks_provider_and_refunds_once(self):
        job = self.make_job(credit_year_month='2026-06')
        from .import_services import cancel_import
        from .tasks import run_insurance_import

        def cancel_then_finish_pdf(_job):
            status, body = cancel_import(
                owner=self.owner,
                job_id=job.id,
                idempotency_key=uuid.uuid4(),
            )
            self.assertEqual(status, 200)
            self.assertEqual(body['status'], 'canceled')
            return self.extracted

        with mock.patch(
                'inpa.insurances.tasks._extract_job_pdf',
                side_effect=cancel_then_finish_pdf), \
                mock.patch(
                    'inpa.insurances.tasks.claude_extract') as claude, \
                mock.patch(
                    'inpa.insurances.import_services.delete_source') as delete:
            with self.captureOnCommitCallbacks(execute=True):
                outcome = run_insurance_import(str(job.id))

        self.assertEqual(outcome, 'stale')
        claude.assert_not_called()
        self.assertFalse(
            InsuranceExtractionResult.objects.filter(job=job).exists())
        job.refresh_from_db()
        self.assertEqual(job.status, 'canceled')
        self.assertEqual(job.draft_payload, {})
        self.assertTrue(
            job.validation_summary['_system']['credit_refunded'])
        self.assertFalse(
            job.validation_summary['_system'].get(
                'provider_started', False))
        self.assertEqual(
            UsageMeter.objects.get(
                user=self.owner,
                action='ocr',
                year_month='2026-06',
            ).count,
            0,
        )
        delete.assert_called_once_with(job, key=self.source_key)

    def test_cancel_refunds_only_before_provider_start(self):
        from .import_services import cancel_import

        cases = (
            ('queued', True),
            ('review_required', False),
        )
        with mock.patch(
                'inpa.insurances.import_services.delete_source') as delete:
            for status_value, provider_started in cases:
                with self.subTest(
                        status=status_value,
                        provider_started=provider_started):
                    job = self.make_job(
                        status=status_value,
                        file_sha256=uuid.uuid4().hex * 2,
                        credit_year_month='2026-06',
                    )
                    summary = copy.deepcopy(job.validation_summary)
                    summary['_system']['provider_started'] = provider_started
                    job.validation_summary = summary
                    job.save(update_fields=['validation_summary'])
                    before = UsageMeter.objects.get(
                        user=self.owner, action='ocr',
                        year_month='2026-06').count

                    with self.captureOnCommitCallbacks(execute=True):
                        response_status, body = cancel_import(
                            owner=self.owner,
                            job_id=job.id,
                            idempotency_key=uuid.uuid4(),
                        )

                    job.refresh_from_db()
                    self.assertEqual(response_status, 200)
                    self.assertEqual(body['status'], 'canceled')
                    self.assertEqual(job.status, 'canceled')
                    self.assertFalse(
                        job.validation_summary['_system'][
                            'credit_refunded'])
                    self.assertEqual(
                        UsageMeter.objects.get(
                            user=self.owner, action='ocr',
                            year_month='2026-06').count,
                        before,
                    )
        self.assertEqual(delete.call_count, len(cases))

    def test_consent_revoked_while_queued_never_calls_claude(self):
        job = self.make_job()
        ConsentLog.objects.filter(customer=self.customer).update(
            revoked_at=timezone.now())
        from .tasks import run_insurance_import

        with mock.patch(
                'inpa.insurances.tasks._extract_job_pdf',
                return_value=self.extracted), \
                mock.patch('inpa.insurances.tasks.claude_extract') as claude, \
                mock.patch(
                    'inpa.insurances.tasks.delete_source') as delete:
            run_insurance_import(str(job.id))

        claude.assert_not_called()
        self.assertFalse(InsuranceExtractionResult.objects.filter(job=job).exists())
        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        self.assertEqual(job.error_code, 'CONSENT_REVOKED_BEFORE_TRANSFER')
        self.assertEqual(job.draft_payload, {})
        self.assertTrue(
            job.validation_summary['_system']['credit_refunded'])
        self.assertEqual(
            UsageMeter.objects.get(user=self.owner, action='ocr').count, 0)
        delete.assert_called_once_with(job, key=self.source_key)

    def test_resource_limit_failure_refunds_credit_once(self):
        job = self.make_job()
        from .tasks import run_insurance_import

        with mock.patch(
                'inpa.insurances.tasks._extract_job_pdf',
                side_effect=PDFImportError('PDF_PARSE_RESOURCE_LIMIT')), \
                mock.patch('inpa.insurances.tasks.claude_extract') as claude, \
                mock.patch('inpa.insurances.tasks.delete_source') as delete:
            run_insurance_import(str(job.id))
            run_insurance_import(str(job.id))

        claude.assert_not_called()
        self.assertEqual(
            UsageMeter.objects.get(user=self.owner, action='ocr').count, 0)
        job.refresh_from_db()
        self.assertTrue(
            job.validation_summary['_system']['credit_refunded'])
        delete.assert_called_once_with(job, key=self.source_key)

    def test_failure_refunds_the_original_billing_month(self):
        job = self.make_job(credit_year_month='2026-06')
        from .tasks import run_insurance_import

        with mock.patch(
                'inpa.insurances.tasks._extract_job_pdf',
                side_effect=PDFImportError('PDF_PARSE_RESOURCE_LIMIT')), \
                mock.patch('inpa.insurances.tasks.delete_source'), \
                mock.patch.object(
                    UsageMeter, 'current_month', return_value='2026-07'):
            run_insurance_import(str(job.id))

        self.assertEqual(
            UsageMeter.objects.get(
                user=self.owner, action='ocr', year_month='2026-06').count,
            0,
        )

    def test_empty_coverage_result_is_failed_not_review_required(self):
        job = self.make_job()
        self.run_worker(job, extraction_result=ExtractionResult(
            payload=_provider_payload(rows=False), model_id='env-model',
            input_tokens=1, output_tokens=1, latency_ms=12))

        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        self.assertEqual(job.error_code, 'EMPTY_COVERAGE_RESULT')
        result = InsuranceExtractionResult.objects.get(job=job, provider='claude')
        self.assertEqual(result.outcome, 'empty')
        self.assertEqual(result.structured_payload, {})
        self.assertEqual(result.latency_ms, 12)
        log = ClaudeApiLog.objects.get(action='insurance_extraction')
        self.assertEqual(log.parse_outcome, ClaudeApiLog.OUTCOME_EMPTY)
        job.refresh_from_db()
        metrics = job.validation_summary['_system']['initial_metrics']
        self.assertEqual(metrics['provider_rows'], 0)
        self.assertEqual(metrics['zero_provider_rows'], 1)
        self.assertEqual(metrics['coverage_row_count'], 0)

    def test_force_manual_carrier_codes_marks_every_row_without_changing_values(self):
        job = self.make_job()
        InsuranceImportRuntimeConfig.objects.filter(pk=1).update(
            force_manual_carrier_codes=[7])
        original = _provider_payload(company_code=7)
        original['coverage_rows'][0]['confirmed_review_codes'] = [
            'CARRIER_MANUAL_REVIEW']
        self.run_worker(job, extraction_result=ExtractionResult(
            payload=original, model_id='env-model',
            input_tokens=1, output_tokens=1))

        job.refresh_from_db()
        row = job.draft_payload['coverage_rows'][0]
        self.assertEqual(row['raw_name'], original['coverage_rows'][0]['raw_name'])
        self.assertEqual(row['assurance_amount'], 30_000_000)
        self.assertEqual(row['state'], 'needs_review')
        self.assertIn('CARRIER_MANUAL_REVIEW', row['review_reason_codes'])
        self.assertNotIn('confirmed_review_codes', row)
        self.assertTrue(
            job.validation_summary['_system']['force_manual_review'])

    def test_provider_failure_is_safe_and_refunds_only_the_consumed_job(self):
        job = self.make_job()
        from .tasks import run_insurance_import
        with mock.patch(
                'inpa.insurances.tasks._extract_job_pdf',
                return_value=self.extracted), \
                mock.patch(
                'inpa.insurances.tasks.claude_extract',
                    side_effect=ExtractionFailure(
                        'PROVIDER_UNAVAILABLE',
                        model_id='claude-opus-4-8',
                        usage={
                            'input_tokens': 9,
                            'output_tokens': 2,
                            'cache_read_input_tokens': 1,
                            'cache_creation_input_tokens': 3,
                        },
                        latency_ms=321,
                    )), \
                mock.patch('inpa.insurances.tasks.delete_source'):
            run_insurance_import(str(job.id))

        job.refresh_from_db()
        self.assertEqual(job.error_code, 'PROVIDER_UNAVAILABLE')
        self.assertEqual(
            UsageMeter.objects.get(user=self.owner, action='ocr').count, 0)
        result = InsuranceExtractionResult.objects.get(job=job, provider='claude')
        self.assertEqual(result.outcome, 'transport_failure')
        self.assertEqual(result.structured_payload, {})
        self.assertEqual(
            (result.input_tokens, result.output_tokens, result.latency_ms),
            (9, 2, 321),
        )
        log = ClaudeApiLog.objects.get(action='insurance_extraction')
        self.assertEqual(log.parse_outcome, 'transport_failure')
        self.assertEqual(log.cache_read_input_tokens, 1)
        self.assertEqual(log.cache_creation_input_tokens, 3)
        metrics = job.validation_summary['_system']['initial_metrics']
        self.assertEqual(metrics['provider_rows'], 0)
        self.assertEqual(metrics['zero_provider_rows'], 0)

    def test_schema_failure_has_one_safe_ledger_and_empty_result_snapshot(self):
        job = self.make_job()
        failure = ExtractionFailure(
            'SCHEMA_INVALID',
            model_id='claude-opus-4-8',
            usage={'input_tokens': 8, 'output_tokens': 1},
            latency_ms=44,
        )
        from .tasks import run_insurance_import

        with mock.patch(
                'inpa.insurances.tasks._extract_job_pdf',
                return_value=self.extracted), mock.patch(
                    'inpa.insurances.tasks.claude_extract',
                    side_effect=failure), mock.patch(
                        'inpa.insurances.tasks.delete_source'):
            outcome = run_insurance_import(str(job.id))

        self.assertEqual(outcome, 'failed')
        result = InsuranceExtractionResult.objects.get(job=job, provider='claude')
        self.assertEqual(result.outcome, 'schema_invalid')
        self.assertEqual(result.structured_payload, {})
        self.assertEqual(result.latency_ms, 44)
        log = ClaudeApiLog.objects.get(action='insurance_extraction')
        self.assertEqual(log.parse_outcome, 'schema_invalid')
        self.assertEqual((log.input_tokens, log.output_tokens), (8, 1))
        job.refresh_from_db()
        metrics = job.validation_summary['_system']['initial_metrics']
        self.assertEqual(metrics['provider_rows'], 0)
        self.assertEqual(metrics['zero_provider_rows'], 0)

    def test_provider_pii_output_creates_no_draft_or_result_and_refunds_once(self):
        sentinel = '계약자: 홍길동 010-1234-5678'
        job = self.make_job(credit_year_month='2026-06')
        payload = _provider_payload()
        payload['coverage_rows'][0]['raw_name'] = sentinel
        provider = ExtractionResult(
            payload=payload,
            model_id='env-model',
            input_tokens=10,
            output_tokens=5,
        )
        from .tasks import run_insurance_import

        with mock.patch(
                'inpa.insurances.tasks._extract_job_pdf',
                return_value=self.extracted), \
                mock.patch(
                    'inpa.insurances.tasks.claude_extract',
                    return_value=provider), \
                mock.patch(
                    'inpa.insurances.tasks.capture_event') as capture, \
                mock.patch(
                    'inpa.insurances.tasks.logger') as safe_logger, \
                mock.patch(
                    'inpa.insurances.tasks.delete_source') as delete, \
                mock.patch.object(
                    UsageMeter, 'current_month', return_value='2026-07'):
            first = run_insurance_import(str(job.id))
            second = run_insurance_import(str(job.id))

        job.refresh_from_db()
        self.assertEqual((first, second), ('failed', 'stale'))
        self.assertEqual(job.status, 'failed')
        self.assertEqual(job.error_code, 'PROVIDER_PII_OUTPUT')
        self.assertEqual(job.error_type, 'provider_privacy')
        self.assertEqual(job.draft_payload, {})
        self.assertFalse(
            InsuranceExtractionResult.objects.filter(
                job=job,
                structured_payload__has_key='coverage_rows',
            ).exists())
        result = InsuranceExtractionResult.objects.get(job=job, provider='claude')
        self.assertEqual(result.outcome, 'privacy_rejected')
        self.assertEqual(result.structured_payload, {})
        log = ClaudeApiLog.objects.get(action='insurance_extraction')
        self.assertEqual(log.parse_outcome, 'privacy_rejected')
        metrics = job.validation_summary['_system']['initial_metrics']
        self.assertEqual(metrics['provider_rows'], 1)
        self.assertEqual(metrics['zero_provider_rows'], 0)
        self.assertEqual(
            UsageMeter.objects.get(
                user=self.owner, action='ocr', year_month='2026-06').count,
            0,
        )
        self.assertTrue(
            job.validation_summary['_system']['credit_refunded'])
        delete.assert_called_once_with(job, key=self.source_key)
        capture.assert_not_called()
        rendered_logs = repr(safe_logger.mock_calls)
        self.assertNotIn(sentinel, rendered_logs)
        self.assertNotIn('홍길동', rendered_logs)
        self.assertNotIn('010-1234-5678', rendered_logs)

    def test_configuration_failures_have_distinct_single_ledger_and_safe_snapshot(self):
        from .tasks import run_insurance_import

        for index, code in enumerate((
                'API_KEY_NOT_CONFIGURED',
                'MODEL_NOT_CONFIGURED',
                'PROVIDER_PACKAGE_MISSING'), start=1):
            with self.subTest(code=code):
                job = self.make_job(
                    credit_consumed=False,
                    file_sha256=f'{index + 20:064x}',
                )
                before = ClaudeApiLog.objects.filter(
                    action='insurance_extraction').count()
                with mock.patch(
                        'inpa.insurances.tasks._extract_job_pdf',
                        return_value=self.extracted), mock.patch(
                            'inpa.insurances.tasks.claude_extract',
                            side_effect=ExtractionFailure(
                                code,
                                model_id='configured-model',
                                usage={
                                    'input_tokens': index,
                                    'output_tokens': 0,
                                },
                                latency_ms=index * 10,
                            )), mock.patch(
                                'inpa.insurances.tasks.delete_source'):
                    outcome = run_insurance_import(str(job.pk))

                self.assertEqual(outcome, 'failed')
                logs = ClaudeApiLog.objects.filter(
                    action='insurance_extraction').order_by('pk')
                self.assertEqual(logs.count(), before + 1)
                self.assertEqual(logs.last().parse_outcome, 'config_failure')
                result = InsuranceExtractionResult.objects.get(
                    job=job, provider='claude')
                self.assertEqual(result.outcome, 'config_failure')
                self.assertEqual(result.structured_payload, {})
                job.refresh_from_db()
                metrics = job.validation_summary['_system']['initial_metrics']
                self.assertEqual(metrics['provider_rows'], 0)
                self.assertEqual(metrics['zero_provider_rows'], 0)

    def test_pre_provider_failure_has_no_provider_snapshot_or_ledger(self):
        job = self.make_job()
        from .tasks import run_insurance_import

        with mock.patch(
                'inpa.insurances.tasks._extract_job_pdf',
                side_effect=PDFImportError('PDF_PARSE_RESOURCE_LIMIT')), \
                mock.patch('inpa.insurances.tasks.delete_source'):
            outcome = run_insurance_import(str(job.pk))

        self.assertEqual(outcome, 'failed')
        job.refresh_from_db()
        self.assertNotIn(
            'initial_metrics', job.validation_summary.get('_system', {}))
        self.assertFalse(
            ClaudeApiLog.objects.filter(
                action='insurance_extraction').exists())
        self.assertFalse(
            InsuranceExtractionResult.objects.filter(job=job).exists())

    def test_system_credit_metadata_is_not_exposed_by_job_serializer(self):
        from .import_serializers import InsuranceImportJobSerializer

        job = self.make_job()
        payload = InsuranceImportJobSerializer(job).data

        self.assertNotIn('validation_summary', payload)
        self.assertNotIn('_system', json.dumps(payload))

    def test_worker_exception_sentry_event_contains_no_lines_or_payload(self):
        sentinel_name = '홍길동-900101'
        sentinel_line = '휴대폰 010-1234-5678'
        sentinel_payload = {'secret': '암진단비 3억원'}
        job = self.make_job()
        from .tasks import run_insurance_import

        def explode(_job):
            local_lines = [sentinel_line]
            structured_payload = sentinel_payload
            raise RuntimeError(
                f'{sentinel_name}:{local_lines}:{structured_payload}')

        with mock.patch(
                'inpa.insurances.tasks._extract_job_pdf',
                side_effect=explode), \
                mock.patch('inpa.insurances.tasks.capture_event') as capture, \
                mock.patch('inpa.insurances.tasks.delete_source'):
            run_insurance_import(str(job.id))

        capture.assert_called_once()
        serialized = json.dumps(
            capture.call_args.args[0], ensure_ascii=False, sort_keys=True)
        for sentinel in (sentinel_name, sentinel_line, '암진단비'):
            self.assertNotIn(sentinel, serialized)
        self.assertIn(str(job.id), serialized)
        self.assertIn('RuntimeError', serialized)

    def test_sentry_failure_does_not_block_terminal_refund_and_cleanup(self):
        job = self.make_job()
        from .tasks import run_insurance_import

        with mock.patch(
                'inpa.insurances.tasks._extract_job_pdf',
                side_effect=RuntimeError('worker failed')), \
                mock.patch(
                    'inpa.insurances.tasks.capture_event',
                    side_effect=RuntimeError('telemetry failed')), \
                mock.patch('inpa.insurances.tasks.delete_source') as delete:
            result = run_insurance_import(str(job.id))

        job.refresh_from_db()
        self.assertEqual(result, 'failed')
        self.assertEqual(job.status, 'failed')
        self.assertEqual(job.error_code, 'WORKER_FAILED')
        self.assertEqual(
            UsageMeter.objects.get(user=self.owner, action='ocr').count, 0)
        delete.assert_called_once_with(job, key=self.source_key)


class InsuranceImportCleanupTests(TestCase):
    def setUp(self):
        self.owner = _owner('cleanup-owner@test.com')
        self.customer = Customer.objects.create(
            owner=self.owner, name='고객', mobile_phone_number='010')

    def make_job(self, *, status, source_expires_at, lease_expires_at=None,
                 attempt_count=1, draft_payload=None):
        job = InsuranceExtractionJob.objects.create(
            owner=self.owner, customer=self.customer, intent='add',
            portfolio_type=1, status=status, file_sha256=uuid.uuid4().hex * 2,
            file_size=10, safe_display_name='policy.pdf',
            source_expires_at=source_expires_at,
            lease_expires_at=lease_expires_at,
            attempt_uuid=(uuid.uuid4() if lease_expires_at else None),
            attempt_count=attempt_count,
            draft_payload=draft_payload or {},
        )
        job.source_storage_key = (
            f'insurance-imports/{self.owner.pk}/{self.customer.pk}/'
            f'{job.id}/source.pdf')
        job.save(update_fields=['source_storage_key'])
        return job

    def test_cleanup_recovers_expired_lease(self):
        now = timezone.now()
        job = self.make_job(
            status='extracting',
            source_expires_at=now + timedelta(hours=1),
            lease_expires_at=now - timedelta(minutes=1))
        with mock.patch(
                'inpa.insurances.management.commands.cleanup_insurance_imports.delete_source') as delete:
            call_command('cleanup_insurance_imports', now=now.isoformat())

        job.refresh_from_db()
        self.assertEqual(job.status, 'queued')
        self.assertIsNone(job.attempt_uuid)
        self.assertIsNone(job.lease_expires_at)
        self.assertEqual(job.lease_expired_count, 1)
        delete.assert_not_called()

    def test_cleanup_republishes_recovered_job_once_after_commit(self):
        now = timezone.now()
        job = self.make_job(
            status='extracting',
            source_expires_at=now + timedelta(hours=1),
            lease_expires_at=now - timedelta(minutes=1))

        with mock.patch(
                'inpa.insurances.management.commands.'
                'cleanup_insurance_imports._publish_job') as publish:
            with self.captureOnCommitCallbacks(execute=True):
                call_command(
                    'cleanup_insurance_imports', now=now.isoformat())
            with self.captureOnCommitCallbacks(execute=True):
                call_command(
                    'cleanup_insurance_imports', now=now.isoformat())

        publish.assert_called_once_with(str(job.id), refund_credit=False)

    def test_worker_loss_recovery_invalidates_old_attempt_before_republish(self):
        now = timezone.now()
        job = self.make_job(
            status='validating',
            source_expires_at=now + timedelta(hours=1),
            lease_expires_at=now - timedelta(minutes=1))
        old_attempt = job.attempt_uuid
        job.page_count = 1
        job.validation_summary = {
            '_system': {
                'provider_started': True,
                'source_readability': {
                    'page_count': 1,
                    'image_only_page_count': 0,
                    'image_only_pages': [],
                    'quarantined_line_count': 0,
                    'quarantined_pages': [],
                    'analysis_signal_quarantined_line_count': 0,
                    'analysis_signal_quarantined_pages': [],
                    'pages_requiring_manual_source_review': [],
                },
            },
        }
        job.save(update_fields=['page_count', 'validation_summary'])

        with mock.patch(
                'inpa.insurances.management.commands.'
                'cleanup_insurance_imports._publish_job'):
            with self.captureOnCommitCallbacks(execute=True):
                call_command(
                    'cleanup_insurance_imports', now=now.isoformat())

        from .tasks import StaleAttempt, _cas_transition
        with self.assertRaises(StaleAttempt):
            _cas_transition(
                job.id, old_attempt,
                expected_status='validating', next_status='review_required')
        job.refresh_from_db()
        self.assertEqual(job.status, 'queued')
        self.assertIsNone(job.attempt_uuid)
        self.assertTrue(
            job.validation_summary['_system']['provider_started'])

        from .tasks import run_insurance_import
        provider = ExtractionResult(
            payload=_provider_payload(), model_id='env-model',
            input_tokens=1, output_tokens=1)
        with mock.patch(
                'inpa.insurances.tasks._extract_job_pdf',
                return_value=_extracted()), \
                mock.patch(
                    'inpa.insurances.tasks.has_current_overseas_consent',
                    return_value=True), \
                mock.patch(
                    'inpa.insurances.tasks.claude_extract',
                    return_value=provider), \
                mock.patch('inpa.insurances.tasks.delete_source'):
            old_redelivery = run_insurance_import(str(job.id))
            republished_delivery = run_insurance_import(str(job.id))

        self.assertEqual(old_redelivery, 'review_required')
        self.assertEqual(republished_delivery, 'stale')

    def test_recovery_broker_failure_reuses_terminal_refund_and_cleanup(self):
        now = timezone.now()
        job = self.make_job(
            status='extracting',
            source_expires_at=now + timedelta(hours=1),
            lease_expires_at=now - timedelta(minutes=1))
        job.validation_summary = {
            '_system': {
                'credit_consumed': True,
                'credit_refunded': False,
                'credit_year_month': '2026-06',
            },
        }
        job.save(update_fields=['validation_summary'])
        meter = UsageMeter.objects.create(
            user=self.owner, action='ocr',
            year_month='2026-06', count=1)

        with mock.patch(
                'inpa.insurances.import_services._enqueue_job',
                side_effect=ConnectionError('broker unavailable')), \
                mock.patch('inpa.insurances.tasks.delete_source') as delete:
            with self.captureOnCommitCallbacks(execute=True):
                call_command(
                    'cleanup_insurance_imports', now=now.isoformat())

        job.refresh_from_db()
        meter.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        self.assertEqual(job.error_code, 'QUEUE_UNAVAILABLE')
        self.assertTrue(
            job.validation_summary['_system']['credit_refunded'])
        self.assertEqual(meter.count, 0)
        delete.assert_called_once_with(job, key=job.source_storage_key)

    def test_cleanup_fails_after_max_lease_attempts_and_invalidates_attempt(self):
        now = timezone.now()
        job = self.make_job(
            status='validating',
            source_expires_at=now + timedelta(hours=1),
            lease_expires_at=now - timedelta(minutes=1),
            attempt_count=3)
        with mock.patch(
                'inpa.insurances.tasks.delete_source') as delete:
            call_command('cleanup_insurance_imports', now=now.isoformat())

        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        self.assertEqual(job.error_code, 'LEASE_RETRY_EXHAUSTED')
        self.assertIsNone(job.attempt_uuid)
        self.assertIsNone(job.lease_expires_at)
        self.assertEqual(job.lease_expired_count, 1)
        delete.assert_called_once_with(job, key=job.source_storage_key)

    def test_cleanup_terminalizes_before_late_save_barrier(self):
        from .import_validation import validate_draft
        from .management.commands.cleanup_insurance_imports import cleanup_imports
        from .tasks import ClaimedImport, StaleAttempt, _save_review_draft

        now = timezone.now()
        job = self.make_job(
            status='validating',
            source_expires_at=now + timedelta(hours=1),
            lease_expires_at=now - timedelta(minutes=1),
            attempt_count=3)
        old_claim = ClaimedImport(
            job_id=job.id,
            attempt_uuid=job.attempt_uuid,
            force_manual_carrier_codes=(),
        )
        job.validation_summary = {
            '_system': {
                'credit_consumed': True,
                'credit_refunded': False,
                'credit_year_month': '2026-06',
            },
        }
        job.save(update_fields=['validation_summary'])
        meter = UsageMeter.objects.create(
            user=self.owner, action='ocr',
            year_month='2026-06', count=1)
        extracted = _extracted()
        provider = ExtractionResult(
            payload=_provider_payload(), model_id='env-model',
            input_tokens=1, output_tokens=1)
        validation = validate_draft(
            extracted.masked_lines,
            extracted.candidates,
            provider.payload,
        )
        barrier_events = []

        def late_save_barrier(_job_id, _attempt_uuid):
            try:
                _save_review_draft(old_claim, provider, validation)
            except StaleAttempt:
                barrier_events.append('stale')
            else:
                barrier_events.append('saved')

        with mock.patch('inpa.insurances.tasks.delete_source'):
            cleanup_imports(
                now=now,
                _terminal_barrier=late_save_barrier,
            )

        job.refresh_from_db()
        meter.refresh_from_db()
        self.assertEqual(barrier_events, ['stale'])
        self.assertEqual(job.status, 'failed')
        self.assertEqual(job.error_code, 'LEASE_RETRY_EXHAUSTED')
        self.assertIsNone(job.attempt_uuid)
        self.assertIsNone(job.lease_expires_at)
        self.assertEqual(job.draft_payload, {})
        self.assertFalse(
            InsuranceExtractionResult.objects.filter(job=job).exists())
        self.assertTrue(
            job.validation_summary['_system']['credit_refunded'])
        self.assertEqual(meter.count, 0)

    def test_cleanup_deletes_expired_review_required_source_but_keeps_draft(self):
        now = timezone.now()
        draft = {'coverage_rows': [{'row_id': 'keep-me'}]}
        job = self.make_job(
            status='review_required',
            source_expires_at=now - timedelta(minutes=1),
            draft_payload=draft)
        with mock.patch(
                'inpa.insurances.management.commands.cleanup_insurance_imports.delete_source') as delete:
            call_command('cleanup_insurance_imports', now=now.isoformat())

        job.refresh_from_db()
        self.assertEqual(job.status, 'review_required')
        self.assertEqual(job.draft_payload, draft)
        self.assertIsNotNone(job.source_deleted_at)
        delete.assert_called_once_with(job, key=job.source_storage_key)

    def test_cleanup_fails_expired_queued_source_and_refunds_once(self):
        now = timezone.now()
        job = self.make_job(
            status='queued',
            source_expires_at=now - timedelta(minutes=1))
        job.validation_summary = {
            '_system': {
                'credit_consumed': True,
                'credit_refunded': False,
                'credit_year_month': '2026-06',
            },
        }
        job.save(update_fields=['validation_summary'])
        meter = UsageMeter.objects.create(
            user=self.owner, action='ocr',
            year_month='2026-06', count=1)

        with mock.patch('inpa.insurances.tasks.delete_source') as delete:
            call_command('cleanup_insurance_imports', now=now.isoformat())
            call_command('cleanup_insurance_imports', now=now.isoformat())

        job.refresh_from_db()
        meter.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        self.assertEqual(job.error_code, 'SOURCE_EXPIRED')
        self.assertTrue(
            job.validation_summary['_system']['credit_refunded'])
        self.assertEqual(meter.count, 0)
        delete.assert_called_once_with(job, key=job.source_storage_key)

    def test_cleanup_counts_only_successful_source_delete_and_retries(self):
        from .management.commands.cleanup_insurance_imports import cleanup_imports

        now = timezone.now()
        job = self.make_job(
            status='queued',
            source_expires_at=now - timedelta(minutes=1))

        with mock.patch(
                'inpa.insurances.tasks.delete_source',
                side_effect=OSError('storage unavailable')):
            first = cleanup_imports(now=now)

        job.refresh_from_db()
        self.assertEqual(first['deleted'], 0)
        self.assertEqual(job.status, 'failed')
        self.assertIsNone(job.source_deleted_at)

        with mock.patch(
                'inpa.insurances.management.commands.'
                'cleanup_insurance_imports.delete_source') as delete:
            second = cleanup_imports(now=now)

        job.refresh_from_db()
        self.assertEqual(second['deleted'], 1)
        self.assertIsNotNone(job.source_deleted_at)
        delete.assert_called_once_with(job, key=job.source_storage_key)

    def test_cleanup_counts_zero_when_candidate_becomes_queued_and_delete_fails(self):
        from .management.commands import cleanup_insurance_imports as cleanup

        now = timezone.now()
        job = self.make_job(
            status='review_required',
            source_expires_at=now - timedelta(minutes=1))
        lock_cleanup_job = cleanup._lock_cleanup_job

        def become_queued_before_lock(job_id, owner_id):
            InsuranceExtractionJob.objects.filter(pk=job_id).update(
                status='queued')
            return lock_cleanup_job(job_id, owner_id)

        with mock.patch.object(
                cleanup, '_lock_cleanup_job',
                side_effect=become_queued_before_lock), \
                mock.patch(
                    'inpa.insurances.tasks.delete_source',
                    side_effect=OSError('storage unavailable')):
            result = cleanup.cleanup_imports(now=now)

        job.refresh_from_db()
        self.assertEqual(result['deleted'], 0)
        self.assertEqual(job.status, 'failed')
        self.assertIsNone(job.source_deleted_at)

    def test_cleanup_deletes_only_exact_expired_source_key(self):
        now = timezone.now()
        expired = self.make_job(
            status='failed', source_expires_at=now - timedelta(minutes=1))
        live = self.make_job(
            status='queued', source_expires_at=now + timedelta(hours=1))
        with mock.patch(
                'inpa.insurances.management.commands.cleanup_insurance_imports.delete_source') as delete:
            call_command('cleanup_insurance_imports', now=now.isoformat())

        delete.assert_called_once_with(expired, key=expired.source_storage_key)
        live.refresh_from_db()
        self.assertIsNone(live.source_deleted_at)

    def test_cleanup_does_not_delete_source_with_live_lease(self):
        now = timezone.now()
        job = self.make_job(
            status='extracting',
            source_expires_at=now - timedelta(minutes=1),
            lease_expires_at=now + timedelta(minutes=1))
        with mock.patch(
                'inpa.insurances.management.commands.cleanup_insurance_imports.delete_source') as delete:
            call_command('cleanup_insurance_imports', now=now.isoformat())

        job.refresh_from_db()
        self.assertIsNone(job.source_deleted_at)
        delete.assert_not_called()

    def test_cleanup_holds_transaction_through_exact_source_delete(self):
        from django.db import connection

        now = timezone.now()
        self.make_job(
            status='review_required',
            source_expires_at=now - timedelta(minutes=1))
        atomic_states = []
        baseline_depth = len(connection.atomic_blocks)

        def inspect_lock(_job, *, key):
            atomic_states.append(len(connection.atomic_blocks) > baseline_depth)

        with mock.patch(
                'inpa.insurances.management.commands.cleanup_insurance_imports.delete_source',
                side_effect=inspect_lock):
            call_command('cleanup_insurance_imports', now=now.isoformat())

        self.assertEqual(atomic_states, [True])

    def test_cleanup_uses_canonical_owner_then_job_lock_order(self):
        from .management.commands import cleanup_insurance_imports as cleanup

        now = timezone.now()
        self.make_job(
            status='review_required',
            source_expires_at=now - timedelta(minutes=1))
        events = []
        owner_lock = cleanup._lock_owner_row
        job_lock = cleanup._lock_job_row
        with mock.patch.object(
                cleanup, '_lock_owner_row',
                side_effect=lambda owner_id: (
                    events.append('owner') or owner_lock(owner_id))), \
                mock.patch.object(
                    cleanup, '_lock_job_row',
                    side_effect=lambda job_id: (
                        events.append('job') or job_lock(job_id))), \
                mock.patch.object(cleanup, 'delete_source'):
            call_command('cleanup_insurance_imports', now=now.isoformat())

        self.assertEqual(events, ['owner', 'job'])
