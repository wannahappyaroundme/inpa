import hashlib
import logging
import tempfile
import uuid
from dataclasses import asdict
from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.core.cache.backends.locmem import LocMemCache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core import signing
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User
from inpa.billing.models import Plan, Subscription, UsageMeter
from inpa.customers.consent_texts import CONSENT_TEXTS_VERSION
from inpa.customers.models import ConsentLog, Customer

from .import_claude import ExtractionResult
from .import_contract import CoverageCandidate, ExtractedPDF, MaskedLine
from .models import (
    CustomerInsurance,
    InsuranceExtractionJob,
    InsuranceImportCreateRequest,
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


def _consent(customer):
    customer.consent_overseas_at = timezone.now()
    customer.save(update_fields=['consent_overseas_at'])
    ConsentLog.objects.create(
        customer=customer,
        scope=ConsentLog.SCOPE_OVERSEAS_MEDICAL,
        subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
        doc_version=CONSENT_TEXTS_VERSION,
    )


PDF_BYTES = b'%PDF-1.7\npolicy-body'
PDF_SHA = hashlib.sha256(PDF_BYTES).hexdigest()


def _pdf(name='policy.pdf', body=PDF_BYTES):
    return SimpleUploadedFile(name, body, content_type='application/pdf')


def _extracted(body=PDF_BYTES, *, page_count=1, image_only_pages=()):
    text_page = next(
        page for page in range(1, page_count + 1)
        if page not in image_only_pages)
    line = MaskedLine(
        line_id=f'p{text_page:02d}-l001', page=text_page, line=1,
        text_masked='일반암진단비 가입금액 3,000만원')
    candidate = CoverageCandidate(
        candidate_id='c00001', evidence_line_ids=(line.line_id,),
        text_masked=line.text_masked)
    return ExtractedPDF(
        file_sha256=hashlib.sha256(body).hexdigest(),
        file_size=len(body), page_count=page_count,
        masked_lines=(line,), candidates=(candidate,),
        residual_scan_passed=True,
        image_only_page_count=len(image_only_pages),
        image_only_pages=tuple(image_only_pages))


def _url(customer):
    return f'/api/v1/customers/{customer.pk}/insurance-imports/'


def _headers(key=None):
    return {'HTTP_IDEMPOTENCY_KEY': str(key or uuid.uuid4())}


def _provider_payload(line_id):
    no_evidence = {'value': None, 'evidence_line_ids': []}
    return {
        'schema_version': 'insurance-review-v1',
        'policy': {
            'carrier_name': dict(no_evidence),
            'company_code': dict(no_evidence),
            'insurance_type': dict(no_evidence),
            'product_name': dict(no_evidence),
            'contract_date': dict(no_evidence),
            'expiry_date': dict(no_evidence),
            'monthly_premium': dict(no_evidence),
        },
        'coverage_rows': [{
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
            'evidence_line_ids': [line_id],
        }],
    }


@override_settings(
    INSURANCE_REVIEW_GATE_ENABLED=True,
    FREE_TIER_UNLIMITED=True,
)
class InsuranceImportReceptionTests(TestCase):
    def setUp(self):
        self.user, self.client = _planner('owner-import@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='고객',
            mobile_phone_number='010-0000-0000')

    def post(self, *, key=None, body=PDF_BYTES, **data):
        payload = {
            'file': _pdf(body=body), 'intent': 'add',
            'portfolio_type': 1, **data,
        }
        return self.client.post(
            _url(self.customer), payload, format='multipart',
            **_headers(key))

    def test_current_customer_self_consent_is_required_before_pdf_or_storage(self):
        with mock.patch(
                'inpa.insurances.import_services.extract_pdf') as extract, \
                mock.patch(
                    'inpa.insurances.import_services.save_source') as save, \
                mock.patch(
                    'inpa.insurances.import_services._enqueue_job') as enqueue:
            response = self.post()

        self.assertEqual(response.status_code, 412)
        self.assertEqual(response.json()['code'],
                         'CONSENT_OVERSEAS_REQUIRED')
        extract.assert_not_called()
        save.assert_not_called()
        enqueue.assert_not_called()

    def test_replace_target_must_belong_to_same_owner_and_customer_before_pdf(self):
        _consent(self.customer)
        foreign, _foreign_client = _planner('target-foreign@test.com')
        foreign_customer = Customer.objects.create(
            owner=foreign, name='다른 고객', mobile_phone_number='011')
        target = CustomerInsurance.objects.create(
            customer=foreign_customer, portfolio_type=1, insurance_type=2,
            name='다른 보험')

        with mock.patch(
                'inpa.insurances.import_services.extract_pdf') as extract:
            response = self.post(
                intent='replace', target_insurance_id=target.id,
                duplicate_resolution_token='server-issued-token')

        self.assertEqual(response.status_code, 404)
        extract.assert_not_called()

    def test_valid_pdf_magic_with_wrong_mime_is_rejected_before_service(self):
        _consent(self.customer)
        upload = SimpleUploadedFile(
            'policy.pdf', PDF_BYTES, content_type='image/jpeg')

        with mock.patch(
                'inpa.insurances.import_services.receive_import',
                return_value=mock.Mock(
                    response_status=202,
                    response_body={'job_id': str(uuid.uuid4()),
                                   'status': 'queued'})) as receive:
            response = self.client.post(
                _url(self.customer), {
                    'file': upload, 'intent': 'add', 'portfolio_type': 1,
                }, format='multipart', **_headers())

        self.assertEqual(response.status_code, 400)
        receive.assert_not_called()

    def test_valid_pdf_mime_with_wrong_magic_is_rejected_before_service(self):
        _consent(self.customer)
        upload = SimpleUploadedFile(
            'policy.pdf', b'not-a-pdf', content_type='application/pdf')

        with mock.patch(
                'inpa.insurances.import_services.receive_import',
                return_value=mock.Mock(
                    response_status=202,
                    response_body={'job_id': str(uuid.uuid4()),
                                   'status': 'queued'})) as receive:
            response = self.client.post(
                _url(self.customer), {
                    'file': upload, 'intent': 'add', 'portfolio_type': 1,
                }, format='multipart', **_headers())

        self.assertEqual(response.status_code, 400)
        receive.assert_not_called()

    def test_pdf_and_browser_generic_mime_values_are_allowed_with_valid_magic(self):
        from .import_serializers import InsuranceImportCreateSerializer

        for content_type in ('application/pdf', 'application/octet-stream', ''):
            with self.subTest(content_type=content_type):
                serializer = InsuranceImportCreateSerializer(data={
                    'file': SimpleUploadedFile(
                        'policy.pdf', PDF_BYTES, content_type=content_type),
                    'intent': 'add',
                    'portfolio_type': 1,
                })
                self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_consent_revoked_during_preflight_is_rechecked_before_storage(self):
        _consent(self.customer)

        def revoke_during_extract(_uploaded_file):
            ConsentLog.objects.filter(customer=self.customer).update(
                revoked_at=timezone.now())
            return _extracted()

        with mock.patch(
                'inpa.insurances.import_services.extract_pdf',
                side_effect=revoke_during_extract), \
                mock.patch(
                    'inpa.insurances.import_services.save_source') as save, \
                mock.patch(
                    'inpa.insurances.import_services.check_and_consume') as credit:
            response = self.post()

        self.assertEqual(response.status_code, 412)
        save.assert_not_called()
        credit.assert_not_called()

    def test_valid_pdf_returns_queued_job_202(self):
        _consent(self.customer)
        with mock.patch(
                'inpa.insurances.import_services.extract_pdf',
                return_value=_extracted()), \
                mock.patch(
                    'inpa.insurances.import_services.save_source',
                    side_effect=lambda job, _upload: (
                        f'insurance-imports/{job.owner_id}/{job.customer_id}/'
                        f'{job.id}/source.pdf')) as save, \
                mock.patch(
                    'inpa.insurances.import_services._enqueue_job') as enqueue:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.post()

        self.assertEqual(response.status_code, 202, response.content)
        self.assertEqual(response.json()['status'], 'queued')
        job = InsuranceExtractionJob.objects.get(id=response.json()['job_id'])
        self.assertEqual(job.owner, self.user)
        self.assertEqual(job.customer, self.customer)
        self.assertEqual(job.file_sha256, PDF_SHA)
        self.assertEqual(job.masked_lines,
                         [asdict(line) for line in _extracted().masked_lines])
        self.assertEqual(
            job.validation_summary['intake_candidates'],
            [{**asdict(candidate),
              'evidence_line_ids': list(candidate.evidence_line_ids)}
             for candidate in _extracted().candidates])
        save.assert_called_once()
        enqueue.assert_called_once_with(str(job.id))

    def test_intake_persists_exact_unread_page_metadata_under_system(self):
        _consent(self.customer)
        mixed = _extracted(page_count=10, image_only_pages=(1, 2))
        with mock.patch(
                'inpa.insurances.import_services.extract_pdf',
                return_value=mixed), mock.patch(
                    'inpa.insurances.import_services.save_source',
                    side_effect=lambda job, _upload: (
                        f'insurance-imports/{job.owner_id}/'
                        f'{job.customer_id}/{job.id}/source.pdf')), mock.patch(
                    'inpa.insurances.import_services._enqueue_job'):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.post()

        self.assertEqual(response.status_code, 202, response.content)
        job = InsuranceExtractionJob.objects.get(pk=response.json()['job_id'])
        self.assertEqual(job.page_count, 10)
        self.assertEqual(
            job.validation_summary['_system']['source_readability'], {
                'page_count': 10,
                'image_only_page_count': 2,
                'image_only_pages': [1, 2],
                'quarantined_line_count': 0,
                'quarantined_pages': [],
                'analysis_signal_quarantined_line_count': 0,
                'analysis_signal_quarantined_pages': [],
                'pages_requiring_manual_source_review': [1, 2],
            })

    def test_ten_page_mixed_pdf_keeps_pages_one_two_unread_through_worker(self):
        _consent(self.customer)
        mixed = _extracted(page_count=10, image_only_pages=(1, 2))
        with mock.patch(
                'inpa.insurances.import_services.extract_pdf',
                return_value=mixed), mock.patch(
                    'inpa.insurances.import_services.save_source',
                    side_effect=lambda job, _upload: (
                        f'insurance-imports/{job.owner_id}/'
                        f'{job.customer_id}/{job.id}/source.pdf')), mock.patch(
                    'inpa.insurances.import_services._enqueue_job'):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.post()
        self.assertEqual(response.status_code, 202, response.content)
        job = InsuranceExtractionJob.objects.get(pk=response.json()['job_id'])

        provider = ExtractionResult(
            payload=_provider_payload(mixed.masked_lines[0].line_id),
            model_id='env-model', input_tokens=1, output_tokens=1)
        from .tasks import run_insurance_import
        with mock.patch(
                'inpa.insurances.tasks._extract_job_pdf',
                return_value=mixed), mock.patch(
                    'inpa.insurances.tasks.claude_extract',
                    return_value=provider) as claude:
            outcome = run_insurance_import(str(job.id))

        self.assertEqual(outcome, 'review_required')
        sent_lines, sent_candidates, _schema = claude.call_args.args
        self.assertEqual(sent_lines, mixed.masked_lines)
        self.assertEqual(sent_candidates, mixed.candidates)
        self.assertTrue(all(line.page >= 3 for line in sent_lines))
        job.refresh_from_db()
        self.assertEqual(job.validation_summary['_system'][
            'source_readability'], {
                'page_count': 10,
                'image_only_page_count': 2,
                'image_only_pages': [1, 2],
                'quarantined_line_count': 0,
                'quarantined_pages': [],
                'analysis_signal_quarantined_line_count': 0,
                'analysis_signal_quarantined_pages': [],
                'pages_requiring_manual_source_review': [1, 2],
            })
        expected_review = {
            'required': True,
            'image_only_page_count': 2,
            'image_only_pages': [1, 2],
            'quarantined_line_count': 0,
            'quarantined_pages': [],
            'analysis_signal_quarantined_line_count': 0,
            'analysis_signal_quarantined_pages': [],
            'pages_requiring_manual_source_review': [1, 2],
            'requires_manual_coverage_entry': True,
            'guidance': (
                '해당 페이지의 원문을 확인한 뒤, 필요한 담보를 '
                '직접 추가하거나 수정해 주세요.'),
        }
        detail = self.client.get(
            f'/api/v1/insurance-imports/{job.id}/')
        draft = self.client.get(
            f'/api/v1/insurance-imports/{job.id}/draft/')
        self.assertEqual(detail.status_code, 200, detail.content)
        self.assertEqual(draft.status_code, 200, draft.content)
        self.assertEqual(detail.json()['source_review'], expected_review)
        self.assertEqual(draft.json()['source_review'], expected_review)
        self.assertIn({
            'code': 'SOURCE_PAGE_MANUAL_REVIEW_REQUIRED',
            'state': 'needs_review',
            'scope': 'document',
            'row_id': None,
            'field': 'source_page',
        }, draft.json()['validation']['issues'])

    def test_queue_publish_failure_marks_failed_deletes_exact_source_and_refunds_once(self):
        _consent(self.customer)
        UsageMeter.objects.create(
            user=self.user, action='ocr',
            year_month=UsageMeter.current_month(), count=1)
        stored_keys = []

        def fake_save(job, _upload):
            key = (
                f'insurance-imports/{job.owner_id}/{job.customer_id}/'
                f'{job.id}/source.pdf')
            stored_keys.append(key)
            return key

        with mock.patch(
                'inpa.insurances.import_services.extract_pdf',
                return_value=_extracted()), \
                mock.patch(
                    'inpa.insurances.import_services.check_and_consume',
                    return_value={
                        'count': 1,
                        'year_month': UsageMeter.current_month(),
                    }), \
                mock.patch(
                    'inpa.insurances.import_services.save_source',
                    side_effect=fake_save), \
                mock.patch(
                    'inpa.insurances.tasks.delete_source') as delete, \
                mock.patch(
                    'inpa.insurances.import_services._enqueue_job',
                    side_effect=ConnectionError('broker unavailable')):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.post()

            # TestCase keeps an outer transaction, so the HTTP response is
            # built before the captured on_commit callback executes. The
            # authoritative job state still records the publish failure.
            self.assertEqual(response.status_code, 202)
            job = InsuranceExtractionJob.objects.get(
                id=response.json()['job_id'])
            self.assertEqual(job.status, 'failed')
            self.assertEqual(job.error_code, 'QUEUE_UNAVAILABLE')
            delete.assert_called_once_with(job, key=stored_keys[0])

            from .import_services import _refund_queue_failure_once
            _refund_queue_failure_once(job.id, refund_credit=True)

        meter = UsageMeter.objects.get(user=self.user, action='ocr')
        self.assertEqual(meter.count, 0)

    def test_queue_failure_does_not_refund_when_beta_bypassed_credit(self):
        meter = UsageMeter.objects.create(
            user=self.user, action='ocr',
            year_month=UsageMeter.current_month(), count=3)
        job = InsuranceExtractionJob.objects.create(
            owner=self.user, customer=self.customer, intent='add',
            portfolio_type=1, status='queued', file_sha256='b' * 64,
            file_size=10, safe_display_name='policy.pdf')

        with mock.patch(
                'inpa.insurances.import_services._enqueue_job',
                side_effect=ConnectionError('broker unavailable')):
            from .import_services import _publish_job
            _publish_job(str(job.id), refund_credit=False)

        meter.refresh_from_db()
        job.refresh_from_db()
        self.assertEqual(meter.count, 3)
        self.assertEqual(job.error_code, 'QUEUE_UNAVAILABLE')

    @override_settings(FREE_TIER_UNLIMITED=False)
    def test_credit_receipt_month_is_the_refund_month_across_boundary(self):
        _consent(self.customer)
        plan = Plan.objects.create(
            code='free', display_name='Free', limit_ocr=10)
        Subscription.objects.create(user=self.user, plan=plan)

        with mock.patch.object(
                UsageMeter, 'current_month',
                side_effect=['2026-06', '2026-07']) as month_clock, \
                mock.patch(
                    'inpa.insurances.import_services.extract_pdf',
                    return_value=_extracted()), \
                mock.patch(
                    'inpa.insurances.import_services.save_source',
                    side_effect=lambda job, _upload: (
                        f'insurance-imports/{job.owner_id}/'
                        f'{job.customer_id}/{job.id}/source.pdf')), \
                mock.patch(
                    'inpa.insurances.import_services._enqueue_job'):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.post()

        self.assertEqual(month_clock.call_count, 1)
        job = InsuranceExtractionJob.objects.get(
            pk=response.json()['job_id'])
        self.assertEqual(
            job.validation_summary['_system']['credit_year_month'],
            '2026-06')
        self.assertEqual(
            UsageMeter.objects.get(
                user=self.user, action='ocr',
                year_month='2026-06').count,
            1,
        )

        from .tasks import run_insurance_import
        with mock.patch.object(
                UsageMeter, 'current_month', return_value='2026-07'), \
                mock.patch(
                    'inpa.insurances.tasks._extract_job_pdf',
                    side_effect=Exception('worker boundary')), \
                mock.patch('inpa.insurances.tasks.capture_event'), \
                mock.patch('inpa.insurances.tasks.delete_source'):
            run_insurance_import(str(job.id))

        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        self.assertTrue(
            job.validation_summary['_system']['credit_refunded'])
        self.assertEqual(
            UsageMeter.objects.get(
                user=self.user, action='ocr',
                year_month='2026-06').count,
            0,
        )
        self.assertFalse(UsageMeter.objects.filter(
            user=self.user, action='ocr', year_month='2026-07').exists())

    @override_settings(FREE_TIER_UNLIMITED=False)
    def test_canceled_pdf_reception_creates_a_new_charged_job(self):
        _consent(self.customer)
        plan = Plan.objects.create(
            code='free', display_name='Free', limit_ocr=10)
        Subscription.objects.create(user=self.user, plan=plan)

        with mock.patch(
                'inpa.insurances.import_services.extract_pdf',
                return_value=_extracted()), \
                mock.patch(
                    'inpa.insurances.import_services.save_source',
                    side_effect=lambda job, _upload: (
                        f'insurance-imports/{job.owner_id}/'
                        f'{job.customer_id}/{job.id}/source.pdf')), \
                mock.patch(
                    'inpa.insurances.import_services._enqueue_job'), \
                mock.patch(
                    'inpa.insurances.import_services.delete_source'):
            with self.captureOnCommitCallbacks(execute=True):
                first = self.post()
            first_job = InsuranceExtractionJob.objects.get(
                pk=first.json()['job_id'])
            self.assertEqual(
                UsageMeter.objects.get(
                    user=self.user, action='ocr').count,
                1,
            )

            with self.captureOnCommitCallbacks(execute=True):
                canceled = self.client.post(
                    f'/api/v1/insurance-imports/{first_job.id}/cancel/',
                    {}, format='json', **_headers())
            self.assertEqual(canceled.status_code, 200, canceled.content)
            self.assertEqual(
                UsageMeter.objects.get(
                    user=self.user, action='ocr').count,
                0,
            )

            with self.captureOnCommitCallbacks(execute=True):
                second = self.post()

        self.assertEqual(second.status_code, 202, second.content)
        self.assertNotEqual(second.json()['job_id'], str(first_job.id))
        first_job.refresh_from_db()
        self.assertEqual(first_job.status, 'canceled')
        self.assertEqual(
            UsageMeter.objects.get(user=self.user, action='ocr').count,
            1,
        )

    def test_same_active_hash_converges_without_recharge_restore_or_reenqueue(self):
        _consent(self.customer)
        existing = InsuranceExtractionJob.objects.create(
            owner=self.user, customer=self.customer, intent='add',
            portfolio_type=1, status='queued', file_sha256=PDF_SHA,
            file_size=len(PDF_BYTES), page_count=1,
            safe_display_name='policy.pdf',
            source_storage_key=(
                f'insurance-imports/{self.user.email}/{self.customer.id}/'
                f'{uuid.uuid4()}/source.pdf'),
            source_expires_at=timezone.now() + timedelta(hours=24),
        )
        with mock.patch(
                'inpa.insurances.import_services.extract_pdf',
                return_value=_extracted()), \
                mock.patch(
                    'inpa.insurances.import_services.check_and_consume') as credit, \
                mock.patch(
                    'inpa.insurances.import_services.save_source') as save, \
                mock.patch(
                    'inpa.insurances.import_services._enqueue_job') as enqueue:
            response = self.post()

        self.assertEqual(response.status_code, 202, response.content)
        self.assertEqual(response.json()['job_id'], str(existing.id))
        credit.assert_not_called()
        save.assert_not_called()
        enqueue.assert_not_called()

    def test_expired_queued_source_cleanup_allows_same_hash_new_job(self):
        _consent(self.customer)
        now = timezone.now()
        expired = InsuranceExtractionJob.objects.create(
            owner=self.user, customer=self.customer, intent='add',
            portfolio_type=1, status='queued', file_sha256=PDF_SHA,
            file_size=len(PDF_BYTES), page_count=1,
            safe_display_name='policy.pdf',
            source_expires_at=now - timedelta(minutes=1),
        )
        expired.source_storage_key = (
            f'insurance-imports/{self.user.id}/{self.customer.id}/'
            f'{expired.id}/source.pdf')
        expired.save(update_fields=['source_storage_key'])

        with mock.patch('inpa.insurances.tasks.delete_source'):
            call_command(
                'cleanup_insurance_imports', now=now.isoformat())

        expired.refresh_from_db()
        self.assertEqual(expired.status, 'failed')
        self.assertEqual(expired.error_code, 'SOURCE_EXPIRED')

        with mock.patch(
                'inpa.insurances.import_services.extract_pdf',
                return_value=_extracted()), \
                mock.patch(
                    'inpa.insurances.import_services.save_source',
                    side_effect=lambda job, _upload: (
                        f'insurance-imports/{job.owner_id}/'
                        f'{job.customer_id}/{job.id}/source.pdf')), \
                mock.patch(
                    'inpa.insurances.import_services._enqueue_job'):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.post()

        self.assertEqual(response.status_code, 202)
        self.assertNotEqual(response.json()['job_id'], str(expired.id))
        self.assertEqual(
            InsuranceExtractionJob.objects.get(
                pk=response.json()['job_id']).status,
            'queued',
        )

    def test_active_duplicate_idempotency_replays_first_response_after_job_changes(self):
        _consent(self.customer)
        key = uuid.uuid4()
        existing = InsuranceExtractionJob.objects.create(
            owner=self.user, customer=self.customer, intent='add',
            portfolio_type=1, status='queued', file_sha256=PDF_SHA,
            file_size=len(PDF_BYTES), page_count=1,
            safe_display_name='policy.pdf')
        other_body = b'%PDF-1.7\nother-policy'

        with mock.patch(
                'inpa.insurances.import_services.extract_pdf',
                side_effect=[_extracted(), _extracted(),
                             _extracted(other_body)]), \
                mock.patch(
                    'inpa.insurances.import_services.check_and_consume') as credit, \
                mock.patch(
                    'inpa.insurances.import_services.save_source') as save, \
                mock.patch(
                    'inpa.insurances.import_services._enqueue_job') as enqueue:
            first = self.post(key=key)
            existing.status = 'failed'
            existing.save(update_fields=['status'])
            replay = self.post(key=key)
            conflict = self.post(key=key, body=other_body)

        expected = {'job_id': str(existing.id), 'status': 'queued'}
        self.assertEqual(first.status_code, 202)
        self.assertEqual(first.json(), expected)
        self.assertEqual(replay.status_code, 202)
        self.assertEqual(replay.json(), expected)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()['code'], 'IDEMPOTENCY_KEY_REUSED')
        self.assertEqual(InsuranceExtractionJob.objects.count(), 1)
        request_record = InsuranceImportCreateRequest.objects.get(
            owner=self.user, idempotency_key=key)
        self.assertEqual(request_record.response_status, 202)
        self.assertEqual(request_record.response_body, expected)
        self.assertNotIn(PDF_SHA, str(request_record.response_body))
        self.assertNotIn('source_storage_key', request_record.response_body)
        credit.assert_not_called()
        save.assert_not_called()
        enqueue.assert_not_called()

    def test_review_required_expired_source_is_reattached_without_claude_or_credit(self):
        _consent(self.customer)
        existing = InsuranceExtractionJob.objects.create(
            owner=self.user, customer=self.customer, intent='add',
            portfolio_type=1, status='review_required', file_sha256=PDF_SHA,
            file_size=len(PDF_BYTES), page_count=1,
            safe_display_name='policy.pdf', draft_payload={'coverages': [1]},
            source_storage_key='', source_deleted_at=timezone.now(),
            source_expires_at=timezone.now() - timedelta(minutes=1),
        )
        exact_key = (
            f'insurance-imports/{self.user.email}/{self.customer.id}/'
            f'{existing.id}/source.pdf')
        with mock.patch(
                'inpa.insurances.import_services.extract_pdf',
                return_value=_extracted()), \
                mock.patch(
                    'inpa.insurances.import_services.check_and_consume') as credit, \
                mock.patch(
                    'inpa.insurances.import_services.save_source',
                    return_value=exact_key) as save, \
                mock.patch(
                    'inpa.insurances.import_services._enqueue_job') as enqueue:
            response = self.post()

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json(), {
            'job_id': str(existing.id), 'status': 'review_required'})
        existing.refresh_from_db()
        self.assertEqual(existing.source_storage_key, exact_key)
        self.assertIsNone(existing.source_deleted_at)
        self.assertGreater(existing.source_expires_at, timezone.now())
        self.assertEqual(existing.draft_payload, {'coverages': [1]})
        save.assert_called_once()
        credit.assert_not_called()
        enqueue.assert_not_called()

    def test_reattach_idempotency_replays_without_second_source_write(self):
        _consent(self.customer)
        key = uuid.uuid4()
        existing = InsuranceExtractionJob.objects.create(
            owner=self.user, customer=self.customer, intent='add',
            portfolio_type=1, status='review_required', file_sha256=PDF_SHA,
            file_size=len(PDF_BYTES), page_count=1,
            safe_display_name='policy.pdf', draft_payload={'coverages': [1]},
            source_storage_key='', source_deleted_at=timezone.now(),
            source_expires_at=timezone.now() - timedelta(minutes=1))
        exact_key = (
            f'insurance-imports/{self.user.id}/{self.customer.id}/'
            f'{existing.id}/source.pdf')

        with mock.patch(
                'inpa.insurances.import_services.extract_pdf',
                return_value=_extracted()), \
                mock.patch(
                    'inpa.insurances.import_services.save_source',
                    return_value=exact_key) as save:
            first = self.post(key=key)
            existing.status = 'superseded'
            existing.source_deleted_at = timezone.now()
            existing.save(update_fields=['status', 'source_deleted_at'])
            replay = self.post(key=key)

        expected = {
            'job_id': str(existing.id), 'status': 'review_required'}
        self.assertEqual(first.status_code, 202)
        self.assertEqual(first.json(), expected)
        self.assertEqual(replay.status_code, 202)
        self.assertEqual(replay.json(), expected)
        save.assert_called_once()

    def test_confirmed_hash_returns_duplicate_conflict_with_existing_version(self):
        _consent(self.customer)
        job = InsuranceExtractionJob.objects.create(
            owner=self.user, customer=self.customer, intent='add',
            portfolio_type=1, status='confirmed', file_sha256=PDF_SHA,
            file_size=len(PDF_BYTES), page_count=1,
            safe_display_name='policy.pdf')
        insurance = CustomerInsurance.objects.create(
            customer=self.customer, portfolio_type=1, insurance_type=2,
            name='확인한 보험', source_job=job, review_status='confirmed',
            analysis_included=True, data_version=7)

        with mock.patch(
                'inpa.insurances.import_services.extract_pdf',
                return_value=_extracted()), \
                mock.patch(
                    'inpa.insurances.import_services.check_and_consume') as credit, \
                mock.patch(
                    'inpa.insurances.import_services.save_source') as save:
            response = self.post()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'DUPLICATE_CONFIRMED')
        self.assertEqual(response.json()['insurance_id'], insurance.id)
        self.assertEqual(response.json()['insurance_version'], 7)
        self.assertEqual(response.json()['allowed_intents'], ['replace'])
        self.assertIsInstance(response.json()['duplicate_resolution_token'], str)
        self.assertGreater(len(response.json()['duplicate_resolution_token']), 40)
        token_payload = signing.loads(
            response.json()['duplicate_resolution_token'],
            key=settings.SECRET_KEY,
            salt='inpa.insurance-import-duplicate.v1',
        )
        self.assertEqual(
            set(token_payload), {'resolution_request_id'})
        self.assertIsInstance(token_payload['resolution_request_id'], int)
        credit.assert_not_called()
        save.assert_not_called()

    def test_confirmed_duplicate_allows_replace_only(self):
        _consent(self.customer)
        confirmed_job = InsuranceExtractionJob.objects.create(
            owner=self.user, customer=self.customer, intent='add',
            portfolio_type=1, status='confirmed', file_sha256=PDF_SHA,
            file_size=len(PDF_BYTES), page_count=1,
            safe_display_name='policy.pdf')
        insurance = CustomerInsurance.objects.create(
            customer=self.customer, portfolio_type=1, insurance_type=2,
            name='확인한 보험', source_job=confirmed_job,
            review_status='confirmed', analysis_included=True,
            data_version=7)
        first_key = uuid.uuid4()
        with mock.patch(
                'inpa.insurances.import_services.extract_pdf',
                return_value=_extracted()), mock.patch(
                    'inpa.insurances.import_services.save_source',
                    side_effect=lambda job, _upload: (
                        f'insurance-imports/{job.owner_id}/'
                        f'{job.customer_id}/{job.id}/source.pdf')), mock.patch(
                    'inpa.insurances.import_services.check_and_consume',
                    return_value={'count': 0, 'year_month': None}) as credit, \
                mock.patch(
                    'inpa.insurances.import_services._enqueue_job') as enqueue:
            conflict = self.post(key=first_key)
            token = conflict.json()['duplicate_resolution_token']
            reused_key = self.post(
                key=first_key, duplicate_resolution_token=token)
            rejected_add = self.post(
                key=uuid.uuid4(), duplicate_resolution_token=token)
            with self.captureOnCommitCallbacks(execute=True):
                accepted = self.post(
                    key=uuid.uuid4(), intent='replace',
                    target_insurance_id=insurance.pk,
                    duplicate_resolution_token=token)
            reused_token = self.post(
                key=uuid.uuid4(), intent='replace',
                target_insurance_id=insurance.pk,
                duplicate_resolution_token=token)

        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(reused_key.status_code, 409)
        self.assertEqual(
            reused_key.json()['code'], 'IDEMPOTENCY_KEY_REUSED')
        self.assertEqual(rejected_add.status_code, 409, rejected_add.content)
        self.assertEqual(
            rejected_add.json()['code'], 'DUPLICATE_RESOLUTION_INVALID')
        self.assertEqual(accepted.status_code, 202, accepted.content)
        created = InsuranceExtractionJob.objects.get(
            pk=accepted.json()['job_id'])
        self.assertNotEqual(created.pk, confirmed_job.pk)
        self.assertEqual(created.intent, 'replace')
        self.assertEqual(created.target_insurance_id, insurance.pk)
        self.assertEqual(reused_token.status_code, 409)
        self.assertEqual(
            reused_token.json()['code'], 'DUPLICATE_RESOLUTION_USED')
        self.assertEqual(InsuranceExtractionJob.objects.filter(
            file_sha256=PDF_SHA).count(), 2)
        credit.assert_called_once()
        enqueue.assert_called_once_with(str(created.pk))

    def test_duplicate_resolution_never_rebinds_to_a_later_match(self):
        _consent(self.customer)
        issued_job = InsuranceExtractionJob.objects.create(
            owner=self.user, customer=self.customer, intent='add',
            portfolio_type=1, status='confirmed', file_sha256=PDF_SHA,
            file_size=len(PDF_BYTES), page_count=1,
            safe_display_name='issued.pdf')
        issued_insurance = CustomerInsurance.objects.create(
            customer=self.customer, portfolio_type=1, insurance_type=2,
            name='선택 권한을 발급한 보험', source_job=issued_job,
            review_status='confirmed', analysis_included=True,
            data_version=7)
        conflict_key = uuid.uuid4()
        with mock.patch(
                'inpa.insurances.import_services.extract_pdf',
                return_value=_extracted()):
            conflict = self.post(key=conflict_key)
        token = conflict.json()['duplicate_resolution_token']

        issued_job.status = 'superseded'
        issued_job.save(update_fields=['status'])
        issued_insurance.review_status = 'superseded'
        issued_insurance.analysis_included = False
        issued_insurance.save(update_fields=(
            'review_status', 'analysis_included'))

        latest_job = InsuranceExtractionJob.objects.create(
            owner=self.user, customer=self.customer, intent='add',
            portfolio_type=1, status='confirmed', file_sha256=PDF_SHA,
            file_size=len(PDF_BYTES), page_count=1,
            safe_display_name='latest.pdf')
        CustomerInsurance.objects.create(
            customer=self.customer, portfolio_type=1, insurance_type=2,
            name='나중에 확인된 보험', source_job=latest_job,
            review_status='confirmed', analysis_included=True,
            data_version=3)

        with mock.patch(
                'inpa.insurances.import_services.extract_pdf',
                return_value=_extracted()), mock.patch(
                    'inpa.insurances.import_services.save_source',
                    side_effect=lambda job, _upload: (
                        f'insurance-imports/{job.owner_id}/'
                        f'{job.customer_id}/{job.id}/source.pdf')), mock.patch(
                    'inpa.insurances.import_services.check_and_consume',
                    return_value={'count': 0, 'year_month': None}), mock.patch(
                    'inpa.insurances.import_services._enqueue_job'):
            response = self.post(
                key=uuid.uuid4(), intent='replace',
                target_insurance_id=issued_insurance.pk,
                duplicate_resolution_token=token)

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(
            response.json()['code'], 'DUPLICATE_RESOLUTION_INVALID')
        issued_request = InsuranceImportCreateRequest.objects.get(
            owner=self.user,
            idempotency_key=conflict_key,
        )
        self.assertEqual(issued_request.job_id, issued_job.pk)
        self.assertIsNone(issued_request.resolution_job_id)
        self.assertEqual(
            InsuranceExtractionJob.objects.filter(
                file_sha256=PDF_SHA).count(), 2)

    def test_two_independent_replace_capabilities_converge_to_one_active_job(self):
        _consent(self.customer)
        confirmed_job = InsuranceExtractionJob.objects.create(
            owner=self.user, customer=self.customer, intent='add',
            portfolio_type=1, status='confirmed', file_sha256=PDF_SHA,
            file_size=len(PDF_BYTES), page_count=1,
            safe_display_name='policy.pdf')
        insurance = CustomerInsurance.objects.create(
            customer=self.customer, portfolio_type=1, insurance_type=2,
            name='확인한 보험', source_job=confirmed_job,
            review_status='confirmed', analysis_included=True,
            data_version=7)
        conflict_keys = [uuid.uuid4(), uuid.uuid4()]
        with mock.patch(
                'inpa.insurances.import_services.extract_pdf',
                return_value=_extracted()), mock.patch(
                    'inpa.insurances.import_services.save_source',
                    side_effect=lambda job, _upload: (
                        f'insurance-imports/{job.owner_id}/'
                        f'{job.customer_id}/{job.id}/source.pdf')) as save, \
                mock.patch(
                    'inpa.insurances.import_services.check_and_consume',
                    return_value={'count': 0, 'year_month': None}) as credit, \
                mock.patch(
                    'inpa.insurances.import_services._enqueue_job') as enqueue:
            conflicts = [self.post(key=key) for key in conflict_keys]
            tokens = [
                response.json()['duplicate_resolution_token']
                for response in conflicts
            ]
            with self.captureOnCommitCallbacks(execute=True):
                first = self.post(
                    key=uuid.uuid4(), intent='replace',
                    target_insurance_id=insurance.pk,
                    duplicate_resolution_token=tokens[0])
            second = self.post(
                key=uuid.uuid4(), intent='replace',
                target_insurance_id=insurance.pk,
                duplicate_resolution_token=tokens[1])
            replay = self.post(
                key=uuid.uuid4(), intent='replace',
                target_insurance_id=insurance.pk,
                duplicate_resolution_token=tokens[1])

        self.assertNotEqual(tokens[0], tokens[1])
        self.assertEqual(first.status_code, 202, first.content)
        self.assertEqual(second.status_code, 202, second.content)
        self.assertEqual(second.json()['job_id'], first.json()['job_id'])
        active_id = first.json()['job_id']
        self.assertEqual(
            InsuranceExtractionJob.objects.filter(
                file_sha256=PDF_SHA,
                status__in=InsuranceExtractionJob.ACTIVE_STATUSES,
            ).count(),
            1,
        )
        resolution_rows = InsuranceImportCreateRequest.objects.filter(
            owner=self.user,
            idempotency_key__in=conflict_keys,
        )
        self.assertEqual(resolution_rows.count(), 2)
        self.assertEqual(
            set(resolution_rows.values_list(
                'resolution_job_id', flat=True)),
            {uuid.UUID(active_id)},
        )
        self.assertEqual(replay.status_code, 409, replay.content)
        self.assertEqual(
            replay.json()['code'], 'DUPLICATE_RESOLUTION_USED')
        save.assert_called_once()
        credit.assert_called_once()
        enqueue.assert_called_once_with(active_id)

    def test_add_intent_cannot_consume_a_replace_capability(self):
        _consent(self.customer)
        confirmed_job = InsuranceExtractionJob.objects.create(
            owner=self.user, customer=self.customer, intent='add',
            portfolio_type=1, status='confirmed', file_sha256=PDF_SHA,
            file_size=len(PDF_BYTES), page_count=1,
            safe_display_name='policy.pdf')
        insurance = CustomerInsurance.objects.create(
            customer=self.customer, portfolio_type=1, insurance_type=2,
            name='확인한 보험', source_job=confirmed_job,
            review_status='confirmed', analysis_included=True,
            data_version=7)
        conflict_keys = [uuid.uuid4(), uuid.uuid4()]
        with mock.patch(
                'inpa.insurances.import_services.extract_pdf',
                return_value=_extracted()), mock.patch(
                    'inpa.insurances.import_services.save_source',
                    side_effect=lambda job, _upload: (
                        f'insurance-imports/{job.owner_id}/'
                        f'{job.customer_id}/{job.id}/source.pdf')), \
                mock.patch(
                    'inpa.insurances.import_services.check_and_consume',
                    return_value={'count': 0, 'year_month': None}), \
                mock.patch('inpa.insurances.import_services._enqueue_job'):
            conflicts = [self.post(key=key) for key in conflict_keys]
            tokens = [
                response.json()['duplicate_resolution_token']
                for response in conflicts
            ]
            rejected = self.post(
                key=uuid.uuid4(), duplicate_resolution_token=tokens[0])
            accepted = self.post(
                key=uuid.uuid4(), intent='replace',
                target_insurance_id=insurance.pk,
                duplicate_resolution_token=tokens[0])

        self.assertEqual(rejected.status_code, 409, rejected.content)
        self.assertEqual(
            rejected.json()['code'], 'DUPLICATE_RESOLUTION_INVALID')
        self.assertEqual(accepted.status_code, 202, accepted.content)
        self.assertEqual(
            InsuranceExtractionJob.objects.filter(
                file_sha256=PDF_SHA,
                status__in=InsuranceExtractionJob.ACTIVE_STATUSES,
            ).count(),
            1,
        )

    def test_publish_failure_releases_duplicate_resolution_for_retry(self):
        _consent(self.customer)
        confirmed_job = InsuranceExtractionJob.objects.create(
            owner=self.user, customer=self.customer, intent='add',
            portfolio_type=1, status='confirmed', file_sha256=PDF_SHA,
            file_size=len(PDF_BYTES), page_count=1,
            safe_display_name='policy.pdf')
        CustomerInsurance.objects.create(
            customer=self.customer, portfolio_type=1, insurance_type=2,
            name='확인한 보험', source_job=confirmed_job,
            review_status='confirmed', analysis_included=True,
            data_version=7)
        stored_keys = []

        def fake_save(job, _upload):
            key = (
                f'insurance-imports/{job.owner_id}/{job.customer_id}/'
                f'{job.id}/source.pdf')
            stored_keys.append(key)
            return key

        with mock.patch(
                'inpa.insurances.import_services.extract_pdf',
                return_value=_extracted()), mock.patch(
                    'inpa.insurances.import_services.save_source',
                    side_effect=fake_save), mock.patch(
                    'inpa.insurances.import_services.check_and_consume',
                    return_value={'count': 0, 'year_month': None}), mock.patch(
                    'inpa.insurances.tasks.delete_source'), mock.patch(
                    'inpa.insurances.import_services._enqueue_job',
                    side_effect=[ConnectionError('broker unavailable'), None]):
            conflict = self.post()
            token = conflict.json()['duplicate_resolution_token']
            with self.captureOnCommitCallbacks(execute=True):
                failed_accept = self.post(
                    key=uuid.uuid4(), intent='replace',
                    target_insurance_id=confirmed_job.confirmed_insurance.pk,
                    duplicate_resolution_token=token)
            failed_job = InsuranceExtractionJob.objects.get(
                pk=failed_accept.json()['job_id'])
            with self.captureOnCommitCallbacks(execute=True):
                retried = self.post(
                    key=uuid.uuid4(), intent='replace',
                    target_insurance_id=confirmed_job.confirmed_insurance.pk,
                    duplicate_resolution_token=token)

        failed_job.refresh_from_db()
        self.assertEqual(failed_job.status, 'failed')
        self.assertEqual(failed_job.error_code, 'QUEUE_UNAVAILABLE')
        self.assertEqual(retried.status_code, 202, retried.content)
        self.assertNotEqual(retried.json()['job_id'], str(failed_job.pk))

    def test_confirmed_duplicate_replace_token_is_bound_to_its_target(self):
        _consent(self.customer)
        confirmed_job = InsuranceExtractionJob.objects.create(
            owner=self.user, customer=self.customer, intent='add',
            portfolio_type=1, status='confirmed', file_sha256=PDF_SHA,
            file_size=len(PDF_BYTES), page_count=1,
            safe_display_name='policy.pdf')
        insurance = CustomerInsurance.objects.create(
            customer=self.customer, portfolio_type=1, insurance_type=2,
            name='확인한 보험', source_job=confirmed_job,
            review_status='confirmed', analysis_included=True,
            data_version=7)
        other = CustomerInsurance.objects.create(
            customer=self.customer, portfolio_type=1, insurance_type=2,
            name='다른 보험', review_status='confirmed',
            analysis_included=True, data_version=3)
        with mock.patch(
                'inpa.insurances.import_services.extract_pdf',
                return_value=_extracted()), mock.patch(
                    'inpa.insurances.import_services.save_source',
                    side_effect=lambda job, _upload: (
                        f'insurance-imports/{job.owner_id}/'
                        f'{job.customer_id}/{job.id}/source.pdf')), mock.patch(
                    'inpa.insurances.import_services.check_and_consume',
                    return_value={'count': 0, 'year_month': None}), mock.patch(
                    'inpa.insurances.import_services._enqueue_job'):
            conflict = self.post()
            token = conflict.json()['duplicate_resolution_token']
            wrong_target = self.post(
                intent='replace', target_insurance_id=other.pk,
                duplicate_resolution_token=token)
            with self.captureOnCommitCallbacks(execute=True):
                accepted = self.post(
                    intent='replace', target_insurance_id=insurance.pk,
                    duplicate_resolution_token=token)

        self.assertEqual(wrong_target.status_code, 409)
        self.assertEqual(
            wrong_target.json()['code'], 'DUPLICATE_RESOLUTION_INVALID')
        self.assertEqual(accepted.status_code, 202, accepted.content)
        created = InsuranceExtractionJob.objects.get(
            pk=accepted.json()['job_id'])
        self.assertEqual(created.intent, 'replace')
        self.assertEqual(created.target_insurance_id, insurance.pk)
        self.assertEqual(created.target_insurance_version, 7)

    def test_forged_duplicate_resolution_cannot_bypass_normal_intake(self):
        _consent(self.customer)
        with mock.patch(
                'inpa.insurances.import_services.extract_pdf',
                return_value=_extracted()), mock.patch(
                    'inpa.insurances.import_services.check_and_consume') as credit, \
                mock.patch(
                    'inpa.insurances.import_services.save_source') as save:
            response = self.post(
                duplicate_resolution_token='forged-token')

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()['code'], 'DUPLICATE_RESOLUTION_INVALID')
        credit.assert_not_called()
        save.assert_not_called()

    def test_expired_duplicate_resolution_cannot_be_used(self):
        _consent(self.customer)
        confirmed_job = InsuranceExtractionJob.objects.create(
            owner=self.user, customer=self.customer, intent='add',
            portfolio_type=1, status='confirmed', file_sha256=PDF_SHA,
            file_size=len(PDF_BYTES), page_count=1,
            safe_display_name='policy.pdf')
        CustomerInsurance.objects.create(
            customer=self.customer, portfolio_type=1, insurance_type=2,
            name='확인한 보험', source_job=confirmed_job,
            review_status='confirmed', analysis_included=True,
            data_version=7)
        issued_at = 1_700_000_000
        with mock.patch(
                'inpa.insurances.import_services.extract_pdf',
                return_value=_extracted()), mock.patch(
                    'inpa.insurances.import_services.check_and_consume') as credit, \
                mock.patch(
                    'inpa.insurances.import_services.save_source') as save, \
                mock.patch(
                    'django.core.signing.time.time', return_value=issued_at):
            conflict = self.post()
        token = conflict.json()['duplicate_resolution_token']

        with mock.patch(
                'inpa.insurances.import_services.extract_pdf',
                return_value=_extracted()), mock.patch(
                    'inpa.insurances.import_services.check_and_consume') as credit, \
                mock.patch(
                    'inpa.insurances.import_services.save_source') as save, \
                mock.patch(
                    'django.core.signing.time.time',
                    return_value=issued_at + 301):
            response = self.post(
                key=uuid.uuid4(), duplicate_resolution_token=token)

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(
            response.json()['code'], 'DUPLICATE_RESOLUTION_INVALID')
        credit.assert_not_called()
        save.assert_not_called()

    def test_duplicate_resolution_cannot_cross_customer_or_owner(self):
        _consent(self.customer)
        source_job = InsuranceExtractionJob.objects.create(
            owner=self.user, customer=self.customer, intent='add',
            portfolio_type=1, status='confirmed', file_sha256=PDF_SHA,
            file_size=len(PDF_BYTES), page_count=1,
            safe_display_name='policy.pdf')
        CustomerInsurance.objects.create(
            customer=self.customer, portfolio_type=1, insurance_type=2,
            name='확인한 보험', source_job=source_job,
            review_status='confirmed', analysis_included=True,
            data_version=7)
        other_customer = Customer.objects.create(
            owner=self.user, name='두 번째 고객', mobile_phone_number='012')
        _consent(other_customer)
        other_job = InsuranceExtractionJob.objects.create(
            owner=self.user, customer=other_customer, intent='add',
            portfolio_type=1, status='confirmed', file_sha256=PDF_SHA,
            file_size=len(PDF_BYTES), page_count=1,
            safe_display_name='policy.pdf')
        CustomerInsurance.objects.create(
            customer=other_customer, portfolio_type=1, insurance_type=2,
            name='두 번째 고객 보험', source_job=other_job,
            review_status='confirmed', analysis_included=True,
            data_version=3)
        foreign, foreign_client = _planner('resolution-cross@test.com')
        foreign_customer = Customer.objects.create(
            owner=foreign, name='다른 설계사 고객', mobile_phone_number='013')
        _consent(foreign_customer)
        foreign_job = InsuranceExtractionJob.objects.create(
            owner=foreign, customer=foreign_customer, intent='add',
            portfolio_type=1, status='confirmed', file_sha256=PDF_SHA,
            file_size=len(PDF_BYTES), page_count=1,
            safe_display_name='policy.pdf')
        CustomerInsurance.objects.create(
            customer=foreign_customer, portfolio_type=1, insurance_type=2,
            name='다른 설계사 보험', source_job=foreign_job,
            review_status='confirmed', analysis_included=True,
            data_version=5)

        with mock.patch(
                'inpa.insurances.import_services.extract_pdf',
                return_value=_extracted()), mock.patch(
                    'inpa.insurances.import_services.check_and_consume') as credit, \
                mock.patch(
                    'inpa.insurances.import_services.save_source') as save:
            conflict = self.post()
            token = conflict.json()['duplicate_resolution_token']
            cross_customer = self.client.post(
                _url(other_customer), {
                    'file': _pdf(), 'intent': 'add', 'portfolio_type': 1,
                    'duplicate_resolution_token': token,
                }, format='multipart', **_headers())
            cross_owner = foreign_client.post(
                _url(foreign_customer), {
                    'file': _pdf(), 'intent': 'add', 'portfolio_type': 1,
                    'duplicate_resolution_token': token,
                }, format='multipart', **_headers())

        for response in (cross_customer, cross_owner):
            self.assertEqual(response.status_code, 409, response.content)
            self.assertEqual(
                response.json()['code'], 'DUPLICATE_RESOLUTION_INVALID')
            self.assertNotIn('insurance_id', response.json())
            self.assertNotIn('insurance_version', response.json())
        credit.assert_not_called()
        save.assert_not_called()

    def test_token_is_rejected_after_confirmed_relation_changes_customer(self):
        _consent(self.customer)
        other_customer = Customer.objects.create(
            owner=self.user, name='다른 내 고객', mobile_phone_number='012')
        confirmed_job = InsuranceExtractionJob.objects.create(
            owner=self.user, customer=self.customer, intent='add',
            portfolio_type=1, status='confirmed', file_sha256=PDF_SHA,
            file_size=len(PDF_BYTES), page_count=1,
            safe_display_name='policy.pdf')
        insurance = CustomerInsurance.objects.create(
            customer=self.customer, portfolio_type=1, insurance_type=2,
            name='확인한 보험', source_job=confirmed_job,
            review_status='confirmed', analysis_included=True,
            data_version=7)
        with mock.patch(
                'inpa.insurances.import_services.extract_pdf',
                return_value=_extracted()):
            conflict = self.post()
        token = conflict.json()['duplicate_resolution_token']
        insurance.customer = other_customer
        insurance.save(update_fields=['customer'])

        with mock.patch(
                'inpa.insurances.import_services.extract_pdf',
                return_value=_extracted()), mock.patch(
                    'inpa.insurances.import_services.check_and_consume') as credit, \
                mock.patch(
                    'inpa.insurances.import_services.save_source') as save:
            response = self.post(
                key=uuid.uuid4(), duplicate_resolution_token=token)

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(
            response.json()['code'], 'DUPLICATE_RESOLUTION_INVALID')
        self.assertNotIn('insurance_id', response.json())
        self.assertNotIn('insurance_version', response.json())
        self.assertNotIn('duplicate_resolution_token', response.json())
        credit.assert_not_called()
        save.assert_not_called()

    def test_damaged_confirmed_relation_to_other_customer_never_leaks(self):
        _consent(self.customer)
        other_customer = Customer.objects.create(
            owner=self.user, name='다른 내 고객', mobile_phone_number='012')
        confirmed_job = InsuranceExtractionJob.objects.create(
            owner=self.user, customer=self.customer, intent='add',
            portfolio_type=1, status='confirmed', file_sha256=PDF_SHA,
            file_size=len(PDF_BYTES), page_count=1,
            safe_display_name='policy.pdf')
        foreign_insurance = CustomerInsurance.objects.create(
            customer=other_customer, portfolio_type=1, insurance_type=2,
            name='다른 고객 보험', source_job=confirmed_job,
            review_status='confirmed', analysis_included=True,
            data_version=9)
        with mock.patch(
                'inpa.insurances.import_services.extract_pdf',
                return_value=_extracted()), mock.patch(
                    'inpa.insurances.import_services.save_source',
                    side_effect=lambda job, _upload: (
                        f'insurance-imports/{job.owner_id}/'
                        f'{job.customer_id}/{job.id}/source.pdf')), \
                mock.patch(
                    'inpa.insurances.import_services.check_and_consume',
                    return_value={'count': 0, 'year_month': None}), \
                mock.patch('inpa.insurances.import_services._enqueue_job'):
            response = self.post()

        self.assertEqual(response.status_code, 202, response.content)
        self.assertNotIn('insurance_id', response.json())
        self.assertNotIn('insurance_version', response.json())
        self.assertNotIn('duplicate_resolution_token', response.json())
        foreign_insurance.refresh_from_db()
        self.assertEqual(foreign_insurance.source_job_id, confirmed_job.pk)

    def test_damaged_confirmed_relation_to_foreign_owner_never_leaks(self):
        _consent(self.customer)
        foreign, _foreign_client = _planner('damaged-relation@test.com')
        foreign_customer = Customer.objects.create(
            owner=foreign, name='다른 설계사 고객', mobile_phone_number='013')
        confirmed_job = InsuranceExtractionJob.objects.create(
            owner=self.user, customer=self.customer, intent='add',
            portfolio_type=1, status='confirmed', file_sha256=PDF_SHA,
            file_size=len(PDF_BYTES), page_count=1,
            safe_display_name='policy.pdf')
        foreign_insurance = CustomerInsurance.objects.create(
            customer=foreign_customer, portfolio_type=1, insurance_type=2,
            name='다른 설계사 보험', source_job=confirmed_job,
            review_status='confirmed', analysis_included=True,
            data_version=11)
        with mock.patch(
                'inpa.insurances.import_services.extract_pdf',
                return_value=_extracted()), mock.patch(
                    'inpa.insurances.import_services.save_source',
                    side_effect=lambda job, _upload: (
                        f'insurance-imports/{job.owner_id}/'
                        f'{job.customer_id}/{job.id}/source.pdf')), \
                mock.patch(
                    'inpa.insurances.import_services.check_and_consume',
                    return_value={'count': 0, 'year_month': None}), \
                mock.patch('inpa.insurances.import_services._enqueue_job'):
            response = self.post()

        self.assertEqual(response.status_code, 202, response.content)
        self.assertNotIn('insurance_id', response.json())
        self.assertNotIn('insurance_version', response.json())
        self.assertNotIn('duplicate_resolution_token', response.json())
        foreign_insurance.refresh_from_db()
        self.assertEqual(foreign_insurance.source_job_id, confirmed_job.pk)

    def test_active_duplicate_wins_over_older_confirmed_hash(self):
        _consent(self.customer)
        confirmed_job = InsuranceExtractionJob.objects.create(
            owner=self.user, customer=self.customer, intent='add',
            portfolio_type=1, status='confirmed', file_sha256=PDF_SHA,
            file_size=len(PDF_BYTES), page_count=1,
            safe_display_name='old.pdf')
        CustomerInsurance.objects.create(
            customer=self.customer, portfolio_type=1, insurance_type=2,
            name='확인한 보험', source_job=confirmed_job,
            review_status='confirmed', analysis_included=True)
        active = InsuranceExtractionJob.objects.create(
            owner=self.user, customer=self.customer, intent='add',
            portfolio_type=1, status='queued', file_sha256=PDF_SHA,
            file_size=len(PDF_BYTES), page_count=1,
            safe_display_name='new.pdf')

        with mock.patch(
                'inpa.insurances.import_services.extract_pdf',
                return_value=_extracted()), mock.patch(
                    'inpa.insurances.import_services.check_and_consume') as credit, \
                mock.patch(
                    'inpa.insurances.import_services.save_source') as save:
            response = self.post()

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json(), {
            'job_id': str(active.pk), 'status': 'queued'})
        credit.assert_not_called()
        save.assert_not_called()

    def test_confirmed_conflict_idempotency_replays_fixed_conflict(self):
        _consent(self.customer)
        key = uuid.uuid4()
        job = InsuranceExtractionJob.objects.create(
            owner=self.user, customer=self.customer, intent='add',
            portfolio_type=1, status='confirmed', file_sha256=PDF_SHA,
            file_size=len(PDF_BYTES), page_count=1,
            safe_display_name='policy.pdf')
        insurance = CustomerInsurance.objects.create(
            customer=self.customer, portfolio_type=1, insurance_type=2,
            name='확인한 보험', source_job=job, review_status='confirmed',
            analysis_included=True, data_version=7)

        with mock.patch(
                'inpa.insurances.import_services.extract_pdf',
                return_value=_extracted()), \
                mock.patch(
                    'inpa.insurances.import_services.save_source') as save:
            first = self.post(key=key)
            job.status = 'superseded'
            job.save(update_fields=['status'])
            insurance.data_version = 8
            insurance.save(update_fields=['data_version'])
            replay = self.post(key=key)

        self.assertEqual(first.status_code, 409)
        self.assertEqual(replay.status_code, 409)
        self.assertEqual(replay.json(), first.json())
        self.assertEqual(replay.json()['insurance_version'], 7)
        self.assertEqual(InsuranceExtractionJob.objects.count(), 1)
        record = InsuranceImportCreateRequest.objects.get(
            owner=self.user, idempotency_key=key)
        self.assertEqual(record.response_status, 409)
        self.assertEqual(record.response_body, first.json())
        save.assert_not_called()

    def test_idempotency_key_replays_same_body_and_rejects_different_body(self):
        _consent(self.customer)
        key = uuid.uuid4()
        extracted_other = _extracted(b'%PDF-1.7\nother-policy')
        with mock.patch(
                'inpa.insurances.import_services.extract_pdf',
                side_effect=[_extracted(), _extracted(), extracted_other]), \
                mock.patch(
                    'inpa.insurances.import_services.save_source',
                    side_effect=lambda job, _upload: (
                        f'insurance-imports/{job.owner_id}/{job.customer_id}/'
                        f'{job.id}/source.pdf')) as save, \
                mock.patch(
                    'inpa.insurances.import_services.check_and_consume',
                    return_value={
                        'count': 0,
                        'year_month': None,
                    }) as credit:
            first = self.post(key=key)
            job = InsuranceExtractionJob.objects.get(
                id=first.json()['job_id'])
            job.status = 'failed'
            job.save(update_fields=['status'])
            replay = self.post(key=key)
            conflict = self.post(
                key=key, body=b'%PDF-1.7\nother-policy')

        self.assertEqual(first.status_code, 202)
        self.assertEqual(replay.status_code, 202)
        self.assertEqual(replay.json(), first.json())
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()['code'], 'IDEMPOTENCY_KEY_REUSED')
        save.assert_called_once()
        credit.assert_called_once()

    def test_idempotency_key_cannot_cross_customer_route(self):
        _consent(self.customer)
        other_customer = Customer.objects.create(
            owner=self.user, name='두 번째 고객', mobile_phone_number='012')
        _consent(other_customer)
        key = uuid.uuid4()
        with mock.patch(
                'inpa.insurances.import_services.extract_pdf',
                return_value=_extracted()), \
                mock.patch(
                    'inpa.insurances.import_services.save_source',
                    side_effect=lambda job, _upload: (
                        f'insurance-imports/{job.owner_id}/{job.customer_id}/'
                        f'{job.id}/source.pdf')):
            first = self.post(key=key)
            second = self.client.post(
                _url(other_customer), {
                    'file': _pdf(), 'intent': 'add', 'portfolio_type': 1,
                }, format='multipart', **_headers(key))

        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()['code'], 'IDEMPOTENCY_KEY_REUSED')

    @override_settings(INSURANCE_MAX_QUEUED_PER_OWNER=1)
    def test_active_duplicate_converges_before_queued_cap_but_new_hash_is_429(self):
        _consent(self.customer)
        existing = InsuranceExtractionJob.objects.create(
            owner=self.user, customer=self.customer, intent='add',
            portfolio_type=1, status='queued', file_sha256=PDF_SHA,
            file_size=len(PDF_BYTES), page_count=1,
            safe_display_name='policy.pdf')
        other_body = b'%PDF-1.7\nother-policy'
        with mock.patch(
                'inpa.insurances.import_services.extract_pdf',
                side_effect=[_extracted(), _extracted(other_body)]), \
                mock.patch(
                    'inpa.insurances.import_services.check_and_consume') as credit, \
                mock.patch(
                    'inpa.insurances.import_services.save_source') as save:
            duplicate = self.post()
            capped = self.post(body=other_body)

        self.assertEqual(duplicate.status_code, 202)
        self.assertEqual(duplicate.json()['job_id'], str(existing.id))
        self.assertEqual(capped.status_code, 429)
        self.assertEqual(capped.json()['code'], 'TOO_MANY_QUEUED_IMPORTS')
        credit.assert_not_called()
        save.assert_not_called()


@override_settings(INSURANCE_REVIEW_GATE_ENABLED=True)
class InsuranceImportReadAndSourceTests(TestCase):
    def setUp(self):
        self.owner, self.client = _planner('read-owner@test.com')
        self.foreign, self.foreign_client = _planner('read-foreign@test.com')
        self.customer = Customer.objects.create(
            owner=self.owner, name='내 고객', mobile_phone_number='010')
        self.foreign_customer = Customer.objects.create(
            owner=self.foreign, name='다른 고객', mobile_phone_number='011')
        self.job = InsuranceExtractionJob.objects.create(
            owner=self.owner, customer=self.customer, intent='add',
            portfolio_type=1, status='review_required', file_sha256=PDF_SHA,
            file_size=len(PDF_BYTES), page_count=1,
            safe_display_name='policy.pdf',
            normalization_version=NORMALIZATION_VERSION,
            source_expires_at=timezone.now() + timedelta(hours=1),
            validation_summary={'_system': {'source_readability': {
                'page_count': 1,
                'image_only_page_count': 0,
                'image_only_pages': [],
                'quarantined_line_count': 0,
                'quarantined_pages': [],
                'analysis_signal_quarantined_line_count': 0,
                'analysis_signal_quarantined_pages': [],
                'pages_requiring_manual_source_review': [],
            }}})

    def test_customer_list_is_scoped_by_both_owner_and_customer(self):
        InsuranceExtractionJob.objects.create(
            owner=self.owner, customer=Customer.objects.create(
                owner=self.owner, name='다른 내 고객', mobile_phone_number='012'),
            intent='add', portfolio_type=1, status='failed',
            file_sha256='1' * 64, file_size=1,
            safe_display_name='other.pdf')
        InsuranceExtractionJob.objects.create(
            owner=self.foreign, customer=self.foreign_customer,
            intent='add', portfolio_type=1, status='failed',
            file_sha256='2' * 64, file_size=1,
            safe_display_name='foreign.pdf')

        response = self.client.get(_url(self.customer))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], 1)
        item = response.json()['results'][0]
        self.assertEqual(item['job_id'], str(self.job.id))
        self.assertIsNone(item['target_insurance_id'])
        self.assertIsNone(item['target_insurance_version'])
        self.assertEqual(item['confirmation_requirements'], {
            'planner_confirmed_source_match': {'required': True},
            'planner_confirmed_unread_pages': {'required': False},
        })
        self.assertNotIn('source_storage_key', item)
        self.assertNotIn('file_sha256', item)
        self.assertNotIn('draft_payload', item)
        self.assertEqual(item['source_review'], {
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

        detail = self.client.get(
            f'/api/v1/insurance-imports/{self.job.id}/')
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()['source_review'], item['source_review'])
        self.assertEqual(
            detail.json()['confirmation_requirements'],
            item['confirmation_requirements'])

        draft = self.client.get(
            f'/api/v1/insurance-imports/{self.job.id}/draft/')
        self.assertEqual(draft.status_code, 200, draft.content)
        self.assertIsNone(draft.json()['target_insurance_id'])
        self.assertIsNone(draft.json()['target_insurance_version'])
        self.assertEqual(
            draft.json()['confirmation_requirements'],
            item['confirmation_requirements'])

    def test_foreign_status_and_source_url_are_both_404(self):
        status_response = self.foreign_client.get(
            f'/api/v1/insurance-imports/{self.job.id}/')
        source_response = self.foreign_client.get(
            f'/api/v1/insurance-imports/{self.job.id}/source-url/')

        self.assertEqual(status_response.status_code, 404)
        self.assertEqual(source_response.status_code, 404)

    def test_owned_job_never_exposes_a_foreign_target_reference(self):
        foreign_target = CustomerInsurance.objects.create(
            customer=self.foreign_customer, portfolio_type=1,
            insurance_type=2, name='다른 설계사의 보험', data_version=9)
        self.job.intent = 'replace'
        self.job.target_insurance = foreign_target
        self.job.target_insurance_version = 9
        self.job.save(update_fields=(
            'intent', 'target_insurance', 'target_insurance_version'))

        detail = self.client.get(
            f'/api/v1/insurance-imports/{self.job.id}/')
        draft = self.client.get(
            f'/api/v1/insurance-imports/{self.job.id}/draft/')

        self.assertEqual(detail.status_code, 200, detail.content)
        self.assertEqual(draft.status_code, 200, draft.content)
        for body in (detail.json(), draft.json()):
            self.assertIsNone(body['target_insurance_id'])
            self.assertIsNone(body['target_insurance_version'])

    def test_invalid_internal_page_metadata_never_leaks_untrusted_page_numbers(self):
        self.job.page_count = 3
        self.job.validation_summary = {
            '_system': {'source_readability': {
                'page_count': 3,
                'image_only_page_count': 2,
                'image_only_pages': [1, 999],
            }}}
        self.job.save(update_fields=['page_count', 'validation_summary'])

        response = self.client.get(
            f'/api/v1/insurance-imports/{self.job.id}/')

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['confirmation_requirements'], {
            'planner_confirmed_source_match': {'required': True},
            'planner_confirmed_unread_pages': {'required': True},
        })
        self.assertEqual(response.json()['source_review'], {
            'required': True,
            'image_only_page_count': 3,
            'image_only_pages': [1, 2, 3],
            'quarantined_line_count': 0,
            'quarantined_pages': [],
            'analysis_signal_quarantined_line_count': 0,
            'analysis_signal_quarantined_pages': [],
            'pages_requiring_manual_source_review': [1, 2, 3],
            'requires_manual_coverage_entry': True,
            'guidance': (
                '해당 페이지의 원문을 확인한 뒤, 필요한 담보를 '
                '직접 추가하거나 수정해 주세요.'),
        })

    def test_local_source_uses_five_minute_signed_token_and_rejects_tamper_or_delete(self):
        with tempfile.TemporaryDirectory() as directory, self.settings(
            STORAGES={
                'default': {
                    'BACKEND': 'django.core.files.storage.FileSystemStorage',
                    'OPTIONS': {'location': directory},
                },
                'insurance_sources': {
                    'BACKEND': 'django.core.files.storage.FileSystemStorage',
                    'OPTIONS': {'location': directory, 'base_url': None},
                },
                'staticfiles': {
                    'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
            },
        ):
            from django.core.files.storage import storages
            from .import_storage import save_source

            storages._storages.clear()
            self.addCleanup(storages._storages.clear)
            key = save_source(self.job, _pdf())
            self.job.source_storage_key = key
            self.job.save(update_fields=['source_storage_key'])

            issued = self.client.get(
                f'/api/v1/insurance-imports/{self.job.id}/source-url/')
            self.assertEqual(issued.status_code, 200, issued.content)
            self.assertEqual(issued['Cache-Control'], 'private, no-store')
            self.assertEqual(issued.json()['expires_in'], 300)
            self.assertNotIn(key, issued.content.decode())

            preview_path = issued.json()['url'].split('testserver')[-1]
            preview = self.client.get(preview_path)
            self.assertEqual(preview.status_code, 200)
            self.assertEqual(preview['Cache-Control'], 'private, no-store')
            self.assertTrue(preview['Content-Disposition'].startswith('inline'))
            self.assertEqual(preview['Referrer-Policy'], 'no-referrer')
            self.assertIsNone(preview.get('X-Frame-Options'))
            self.assertIn(
                "frame-ancestors 'self'",
                preview['Content-Security-Policy'])

            tampered = self.client.get(preview_path + 'x')
            self.assertEqual(tampered.status_code, 404)

            self.job.source_deleted_at = timezone.now()
            self.job.save(update_fields=['source_deleted_at'])
            deleted = self.client.get(preview_path)
            self.assertEqual(deleted.status_code, 404)

    def test_expired_source_is_not_issued(self):
        self.job.source_storage_key = (
            f'insurance-imports/{self.owner.id}/{self.customer.id}/'
            f'{self.job.id}/source.pdf')
        self.job.source_expires_at = timezone.now() - timedelta(seconds=1)
        self.job.save(update_fields=(
            'source_storage_key', 'source_expires_at'))

        response = self.client.get(
            f'/api/v1/insurance-imports/{self.job.id}/source-url/')

        self.assertEqual(response.status_code, 404)

    def test_local_source_capability_expires_after_301_seconds(self):
        with tempfile.TemporaryDirectory() as directory, self.settings(
            STORAGES={
                'default': {
                    'BACKEND': 'django.core.files.storage.FileSystemStorage',
                    'OPTIONS': {'location': directory},
                },
                'insurance_sources': {
                    'BACKEND': 'django.core.files.storage.FileSystemStorage',
                    'OPTIONS': {'location': directory, 'base_url': None},
                },
                'staticfiles': {
                    'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
            },
        ):
            from django.core.files.storage import storages
            from .import_storage import save_source

            storages._storages.clear()
            self.addCleanup(storages._storages.clear)
            key = save_source(self.job, _pdf())
            self.job.source_storage_key = key
            self.job.save(update_fields=['source_storage_key'])
            issued_at = 1_800_000_000
            with mock.patch(
                    'django.core.signing.time.time', return_value=issued_at):
                issued = self.client.get(
                    f'/api/v1/insurance-imports/{self.job.id}/source-url/')

            preview_path = issued.json()['url'].split('testserver')[-1]
            with mock.patch(
                    'django.core.signing.time.time',
                    return_value=issued_at + 301):
                expired = self.client.get(preview_path)

        self.assertEqual(issued.status_code, 200)
        self.assertEqual(expired.status_code, 404)


@override_settings(INSURANCE_REVIEW_GATE_ENABLED=True)
class InsuranceImportThrottleBoundaryTests(TestCase):
    def setUp(self):
        self.owner, self.client = _planner('throttle-owner@test.com')
        self.customer = Customer.objects.create(
            owner=self.owner, name='제한 고객', mobile_phone_number='010')
        _consent(self.customer)

    def throttle_context(self, location):
        rates = settings.INSURANCE_IMPORT_THROTTLE_RATES
        return (
            mock.patch.object(ScopedRateThrottle, 'THROTTLE_RATES', rates),
            mock.patch.object(
                ScopedRateThrottle, 'cache', LocMemCache(location, {})),
        )

    def test_twenty_first_create_is_throttled_before_service_or_storage(self):
        result = mock.Mock(
            response_status=202,
            response_body={'job_id': str(uuid.uuid4()), 'status': 'queued'},
        )
        rate_patch, cache_patch = self.throttle_context(
            'insurance-import-create-boundary')
        with rate_patch, cache_patch, mock.patch(
                'inpa.insurances.import_services.receive_import',
                return_value=result) as receive, mock.patch(
                    'inpa.insurances.import_services.save_source') as save:
            accepted = [self.client.post(
                _url(self.customer), {
                    'file': _pdf(), 'intent': 'add', 'portfolio_type': 1,
                }, format='multipart', **_headers()) for _ in range(20)]
            receive.reset_mock()
            throttled = self.client.post(
                _url(self.customer), {
                    'file': _pdf(), 'intent': 'add', 'portfolio_type': 1,
                }, format='multipart', **_headers())

        self.assertTrue(all(response.status_code == 202
                            for response in accepted))
        self.assertEqual(throttled.status_code, 429)
        receive.assert_not_called()
        save.assert_not_called()

    def test_one_hundred_twenty_first_source_request_is_throttled(self):
        job = InsuranceExtractionJob.objects.create(
            owner=self.owner, customer=self.customer, intent='add',
            portfolio_type=1, status='review_required', file_sha256=PDF_SHA,
            file_size=len(PDF_BYTES), page_count=1,
            safe_display_name='policy.pdf',
            source_storage_key='',
            source_expires_at=timezone.now() + timedelta(hours=1))
        job.source_storage_key = (
            f'insurance-imports/{self.owner.id}/{self.customer.id}/'
            f'{job.id}/source.pdf')
        job.save(update_fields=['source_storage_key'])
        storage = mock.Mock()
        storage.exists.return_value = True
        rate_patch, cache_patch = self.throttle_context(
            'insurance-import-source-boundary')

        with rate_patch, cache_patch, mock.patch(
                'inpa.insurances.import_views.storages',
                {'insurance_sources': storage}):
            accepted = [self.client.get(
                f'/api/v1/insurance-imports/{job.id}/source-url/')
                for _ in range(120)]
            throttled = self.client.get(
                f'/api/v1/insurance-imports/{job.id}/source-url/')

        self.assertTrue(all(response.status_code == 200
                            for response in accepted))
        self.assertEqual(throttled.status_code, 429)


class InsuranceImportGateAndConfigTests(TestCase):
    def setUp(self):
        self.user, self.client = _planner('gate@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='고객', mobile_phone_number='010')

    @override_settings(INSURANCE_REVIEW_GATE_ENABLED=False)
    def test_config_has_only_public_runtime_contract_while_new_reception_is_404(self):
        config = self.client.get('/api/v1/insurance-imports/config/')
        create = self.client.post(
            _url(self.customer),
            {'file': _pdf(), 'intent': 'add', 'portfolio_type': 1},
            format='multipart', **_headers())

        self.assertEqual(config.status_code, 200)
        self.assertEqual(config.json(), {
            'review_workflow_enabled': False,
            'accepted_input': 'digital_pdf',
            'max_file_bytes': 52_428_800,
        })
        self.assertEqual(create.status_code, 404)

    @override_settings(INSURANCE_REVIEW_GATE_ENABLED=False)
    def test_gate_off_keeps_legacy_ocr_path_unchanged(self):
        legacy = self.client.post(
            f'/api/v1/customers/{self.customer.id}/insurances/ocr/',
            {'file': _pdf()}, format='multipart')

        self.assertEqual(legacy.status_code, 412)
        self.assertEqual(legacy.json()['code'], 'CONSENT_OVERSEAS_REQUIRED')

    @override_settings(INSURANCE_REVIEW_GATE_ENABLED=True)
    def test_gate_on_legacy_ocr_delegates_to_import_reception(self):
        _consent(self.customer)
        with mock.patch(
                'inpa.insurances.import_services.receive_import') as receive:
            receive.return_value = mock.Mock(
                job=mock.Mock(id=uuid.uuid4(), status='queued'),
                duplicate_kind='created',
                response_status=202,
                response_body={
                    'job_id': str(uuid.uuid4()), 'status': 'queued'},
            )
            response = self.client.post(
                f'/api/v1/customers/{self.customer.id}/insurances/ocr/',
                {'file': _pdf(), 'portfolio_type': 1}, format='multipart',
                **_headers())

        self.assertEqual(response.status_code, 202, response.content)
        receive.assert_called_once()

    def test_import_views_use_the_required_throttle_scopes(self):
        from .import_views import (
            InsuranceImportCollectionView, InsuranceImportDetailView,
            InsuranceImportSourceURLView,
        )

        self.assertEqual(InsuranceImportCollectionView.create_throttle_scope,
                         'ocr')
        self.assertEqual(InsuranceImportCollectionView.read_throttle_scope,
                         'insurance_import')
        self.assertEqual(InsuranceImportDetailView.throttle_scope,
                         'insurance_import')
        self.assertEqual(InsuranceImportSourceURLView.throttle_scope,
                         'insurance_import_source')

    def test_settings_keep_ocr_rate_and_add_import_rates(self):
        rates = settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']
        # Test settings replace rates with None, so verify the keys here. The
        # production values are asserted without test argv in settings tests.
        self.assertEqual(
            set(('ocr', 'insurance_import', 'insurance_import_source'))
            - set(rates), set())
        self.assertEqual(settings.INSURANCE_IMPORT_THROTTLE_RATES, {
            'ocr': '20/hour',
            'insurance_import': '600/hour',
            'insurance_import_source': '120/hour',
        })

    def test_r2_url_uses_inline_private_five_minute_signature(self):
        from .import_views import _signed_s3_url

        storage = mock.Mock()
        job = mock.Mock(source_storage_key='private/exact/source.pdf')

        _signed_s3_url(storage, job)

        storage.url.assert_called_once_with(
            'private/exact/source.pdf',
            parameters={
                'ResponseContentDisposition': 'inline',
                'ResponseCacheControl': 'private,no-store',
            },
            expire=300,
        )

    def test_console_logging_redacts_local_source_capability_token(self):
        from inpa.core.logging_filters import (
            RedactInsuranceSourceTokenFilter,
        )

        token = 'signed.secret.capability'
        record = logging.LogRecord(
            name='django.request', level=logging.WARNING, pathname=__file__,
            lineno=1, msg='Not Found: %s',
            args=(f'/api/v1/insurance-imports/source/{token}/',),
            exc_info=None,
        )

        RedactInsuranceSourceTokenFilter().filter(record)
        rendered = record.getMessage()

        self.assertNotIn(token, rendered)
        self.assertIn('<redacted>', rendered)
