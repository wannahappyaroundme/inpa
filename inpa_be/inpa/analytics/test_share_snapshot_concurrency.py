"""PostgreSQL release gates for concurrent immutable share issuance."""

import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest import mock

from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User
from inpa.analysis.models import (
    AnalysisCategory,
    AnalysisDetail,
    AnalysisSubCategory,
)
from inpa.customers.models import Customer
from inpa.insurances.models import (
    CustomerInsurance,
    CustomerInsuranceDetail,
    InsuranceCategory,
    InsuranceDetail,
    InsuranceSubCategory,
)
from inpa.insurances.test_import_concurrency import _PgBlockingProbe

from .models import ShareSnapshot
from .views import _build_share_payload


THREAD_TIMEOUT = 5
POSTGRES_ONLY = unittest.skipUnless(
    connection.vendor == 'postgresql',
    'PostgreSQL row locks and partial indexes are required.',
)


def _planner(email):
    user = User.objects.create_user(email=email, password='inpaPass123!')
    user.is_active = True
    user.save(update_fields=['is_active'])
    Profile.objects.create(user=user, email_verified_at=timezone.now())
    return user, Token.objects.create(user=user).key


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


def _confirmed_portfolio(customer):
    analysis_category = AnalysisCategory.objects.create(
        insurance_type=2, name='공유합성-상해', order=1)
    analysis_subcategory = AnalysisSubCategory.objects.create(
        insurance_type=2,
        category=analysis_category,
        name='공유합성-사망후유',
        order=1,
    )
    analysis_detail = AnalysisDetail.objects.create(
        sub_category=analysis_subcategory,
        name='공유합성-사망보장',
        order=1,
    )
    insurance_category = InsuranceCategory.objects.create(
        insurance_type=2, name='공유합성-손보상품', order=1)
    insurance_subcategory = InsuranceSubCategory.objects.create(
        insurance_type=2,
        category=insurance_category,
        name='공유합성-보장',
        order=1,
    )
    catalog_detail = InsuranceDetail.objects.create(
        sub_category=insurance_subcategory,
        name='공유합성-사망담보',
        order=1,
    )
    catalog_detail.analysis_detail.add(analysis_detail)
    insurance = CustomerInsurance.objects.create(
        customer=customer,
        insurance_type=2,
        name='공유 합성보험',
        portfolio_type=1,
        payment_period_type=1,
        payment_period=20,
        monthly_premiums=50_000,
        monthly_assurance_premium=50_000,
        review_status='confirmed',
        analysis_included=True,
        confirmed_at=timezone.now(),
    )
    CustomerInsuranceDetail.objects.create(
        insurance=insurance,
        detail=catalog_detail,
        assurance_amount=20_000_000,
        premium=10_000,
        payment_period_type=1,
        payment_period=20,
        warranty_period_type=1,
        warranty_period='100',
        confirmed_at=timezone.now(),
    )
    insurance.set_renewal_month()
    insurance.calculate()
    insurance.save()
    return insurance


@POSTGRES_ONLY
@override_settings(INSURANCE_REVIEW_GATE_ENABLED=True)
class ShareSnapshotPostgresConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.owner, self.token_key = _planner(
            'pg-share-owner@example.invalid')
        self.customer = Customer.objects.create(
            owner=self.owner,
            name='공유 합성고객',
            birth_day='1985.05.05',
            gender=1,
        )
        _confirmed_portfolio(self.customer)

    @property
    def share_url(self):
        return f'/api/v1/customers/{self.customer.pk}/share/'

    def test_two_http_issues_converge_to_one_active_v2_link(self):
        probe = _PgBlockingProbe()

        def build_payload(*args, **kwargs):
            probe.hold_first_after_lock()
            return _build_share_payload(*args, **kwargs)

        def issue():
            probe.register_worker()
            return _client(self.token_key).post(self.share_url)

        with mock.patch(
                'inpa.analytics.views._build_share_payload',
                side_effect=build_payload):
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(_thread_call, issue),
                    executor.submit(_thread_call, issue),
                ]
                try:
                    probe.assert_peer_blocked()
                finally:
                    probe.release()
                responses = [future.result(timeout=THREAD_TIMEOUT)
                             for future in futures]

        self.assertEqual(
            [response.status_code for response in responses], [201, 201])
        response_tokens = {
            response.json()['share_token'] for response in responses}
        self.assertEqual(len(response_tokens), 2)
        snapshots = ShareSnapshot.objects.filter(customer=self.customer)
        self.assertEqual(snapshots.count(), 2)
        active = snapshots.filter(
            share_token__isnull=False,
            revoked_at__isnull=True,
            link_expires_at__gt=timezone.now(),
            payload_version='v2-immutable-analysis',
        )
        self.assertEqual(active.count(), 1)
        current = active.get()
        revoked = snapshots.exclude(pk=current.pk).get()
        self.assertIsNotNone(revoked.revoked_at)
        self.assertEqual(revoked.revoked_reason, 'reissued')
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.share_token, current.share_token)
        self.assertEqual(
            self.customer.share_expires_at, current.link_expires_at)

        public = APIClient()
        self.assertEqual(
            public.get(f'/api/v1/s/{revoked.share_token}/').status_code, 404)
        self.assertEqual(
            public.get(f'/api/v1/s/{current.share_token}/').status_code, 200)

    def test_direct_nonnull_token_collision_is_database_enforced(self):
        shared_token = uuid.uuid4()
        probe = _PgBlockingProbe()

        def insert():
            def operation():
                probe.register_worker()
                try:
                    with transaction.atomic():
                        snapshot = ShareSnapshot.objects.create(
                            owner=self.owner,
                            customer=self.customer,
                            share_token=shared_token,
                            payload={},
                            link_expires_at=(
                                timezone.now() + timedelta(days=90)),
                            retention_expires_at=(
                                timezone.now() + timedelta(days=180)),
                        )
                        probe.hold_first_after_lock()
                    return ('created', snapshot.pk)
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

        self.assertEqual(
            sorted(outcome[0] for outcome in outcomes),
            ['created', 'integrity'],
        )
        self.assertEqual(
            ShareSnapshot.objects.filter(share_token=shared_token).count(), 1)
        for _ in range(2):
            ShareSnapshot.objects.create(
                owner=self.owner,
                customer=self.customer,
                share_token=None,
                payload={},
                retention_expires_at=(
                    timezone.now() + timedelta(days=180)),
            )
        self.assertEqual(
            ShareSnapshot.objects.filter(share_token__isnull=True).count(), 2)

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT pg_get_expr(index.indpred, index.indrelid)
                FROM pg_index AS index
                JOIN pg_class AS relation ON relation.oid = index.indexrelid
                WHERE relation.relname = %s
                """,
                ['uniq_share_snapshot_nonnull_token'],
            )
            predicate = cursor.fetchone()[0]
        self.assertIn('share_token', predicate)
        self.assertIn('IS NOT NULL', predicate)
