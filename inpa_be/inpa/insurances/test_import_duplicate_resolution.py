import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from django.db import close_old_connections
from django.test import TransactionTestCase

from inpa.accounts.models import User
from inpa.customers.models import Customer

from .import_services import _consume_duplicate_resolution
from .models import InsuranceExtractionJob, InsuranceImportCreateRequest


class DuplicateResolutionConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.owner = User.objects.create_user(
            email='resolution-race@test.com', password='inpaPass123!')
        self.customer = Customer.objects.create(
            owner=self.owner, name='고객')
        self.source_job = self.make_job(status='confirmed')
        self.candidates = [self.make_job(), self.make_job()]
        request = InsuranceImportCreateRequest.objects.create(
            owner=self.owner,
            job=self.source_job,
            idempotency_key=uuid.uuid4(),
            request_sha256='a' * 64,
            response_status=409,
            response_body={'code': 'DUPLICATE_CONFIRMED'},
        )
        self.request_id = request.pk

    def make_job(self, *, status='queued'):
        return InsuranceExtractionJob.objects.create(
            owner=self.owner,
            customer=self.customer,
            intent='add',
            portfolio_type=1,
            status=status,
            file_sha256=uuid.uuid4().hex * 2,
            file_size=10,
            safe_display_name='policy.pdf',
        )

    def test_two_concurrent_consumers_allow_exactly_one_job(self):
        barrier = threading.Barrier(2)

        def consume(job_id):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                return _consume_duplicate_resolution(
                    self.request_id, job_id)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(
                consume, [job.pk for job in self.candidates]))

        self.assertEqual(sorted(results), [False, True])
        request = InsuranceImportCreateRequest.objects.get(
            pk=self.request_id)
        self.assertIn(
            request.resolution_job_id,
            {job.pk for job in self.candidates})

    def test_two_independent_requests_can_concurrently_converge_to_one_job(self):
        target_job = self.candidates[0]
        request_ids = list(InsuranceImportCreateRequest.objects.bulk_create([
            InsuranceImportCreateRequest(
                owner=self.owner,
                job=self.source_job,
                idempotency_key=uuid.uuid4(),
                request_sha256=value * 64,
                response_status=409,
                response_body={'code': 'DUPLICATE_CONFIRMED'},
            )
            for value in ('b', 'c')
        ]))
        request_ids = [request.pk for request in request_ids]
        barrier = threading.Barrier(2)

        def consume(request_id):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                return _consume_duplicate_resolution(
                    request_id, target_job.pk)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(consume, request_ids))

        self.assertEqual(results, [True, True])
        self.assertEqual(
            set(InsuranceImportCreateRequest.objects.filter(
                pk__in=request_ids,
            ).values_list('resolution_job_id', flat=True)),
            {target_job.pk},
        )
        self.assertEqual(
            InsuranceExtractionJob.objects.filter(pk=target_job.pk).count(),
            1,
        )
