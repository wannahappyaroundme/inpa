import hashlib
import re
from collections import Counter
from io import StringIO
from urllib.parse import urlparse
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from inpa.accounts.models import Profile
from inpa.analysis.models import (
    AnalysisCategory,
    AnalysisDetail,
    AnalysisSubCategory,
)
from inpa.analysis.showcase_data import (
    ANCHOR_CUSTOMER_KEYS,
    CUSTOMERS,
    INSURANCES,
    STAGE_COUNTS,
    STATUS_COUNTS,
)
from inpa.analytics.models import NorthStarEvent, ShareSnapshot
from inpa.billing.models import Plan, Subscription
from inpa.booking.models import Meeting, WorkHour
from inpa.boards.models import BlogPost, Faq, Notice, Post
from inpa.customers.consent_texts import CONSENT_TEXTS_VERSION
from inpa.customers.models import ConsentLog, Customer
from inpa.dashboard.models import MonthlyGoal
from inpa.insurances.models import (
    CustomerInsurance,
    CustomerInsuranceDetail,
    InsuranceCategory,
    InsuranceDetail,
    InsuranceSubCategory,
)
from inpa.notifications.models import Notification
from inpa.promotion.models import PromotionSample
from inpa.schedule.models import ScheduleItem


User = get_user_model()

_SHOWCASE_EMAIL = 'internal-showcase@test.example'
_ARBITRARY_TEST_VALUE = 'test-only-value-' + '49xq'
_PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
_PUBLIC_MODELS = (
    Post,
    Notice,
    Faq,
    BlogPost,
    Plan,
    PromotionSample,
    AnalysisCategory,
    AnalysisSubCategory,
    AnalysisDetail,
    InsuranceCategory,
    InsuranceSubCategory,
    InsuranceDetail,
    InsuranceDetail.analysis_detail.through,
)


def _model_rows(model):
    field_names = [
        field.attname
        for field in model._meta.concrete_fields
    ]
    order_field = model._meta.pk.attname
    return tuple(
        model._default_manager.order_by(order_field).values_list(*field_names)
    )


def _fingerprint(models):
    payload = tuple(
        (model._meta.label_lower, _model_rows(model))
        for model in models
    )
    return hashlib.sha256(repr(payload).encode('utf-8')).hexdigest()


def _database_fingerprint():
    models = tuple(
        model
        for model in apps.get_models(include_auto_created=True)
        if model._meta.managed and not model._meta.proxy
    )
    return _fingerprint(models)


@override_settings(
    SHOWCASE_ACCOUNT_EMAIL=_SHOWCASE_EMAIL,
    SHOWCASE_ACCOUNT_PASSWORD=_ARBITRARY_TEST_VALUE,
    PASSWORD_HASHERS=_PASSWORD_HASHERS,
    BOOKING_ENABLED=True,
    BOOKING_TOKEN_TTL_HOURS=72,
    FRONTEND_BASE_URL='https://showcase.example.invalid',
    INSURANCE_REVIEW_GATE_ENABLED=True,
    LEGACY_SHARE_FALLBACK_ENABLED=False,
)
class ShowcaseSeedCommandTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_normalization', '--force', stdout=StringIO())
        Plan.objects.get_or_create(
            code='free',
            defaults={
                'display_name': 'Free',
                'price_krw': 0,
                'is_active': True,
            },
        )
        Plan.objects.get_or_create(
            code='super',
            defaults={
                'display_name': 'Super',
                'price_krw': 0,
                'is_active': True,
            },
        )

    def _call(self, *args):
        output = StringIO()
        call_command('seed_showcase', *args, stdout=output)
        return output.getvalue()

    def _assert_error_without_changes(self, expected, *args):
        before = _database_fingerprint()
        with self.assertRaises(CommandError) as raised:
            self._call(*args)
        self.assertIn(expected, str(raised.exception))
        self.assertEqual(_database_fingerprint(), before)

    def _seed(self):
        return self._call('--apply')

    def _showcase_user(self):
        return User.objects.select_related('profile').get(
            email=_SHOWCASE_EMAIL,
        )

    def _owned_counts(self):
        user = self._showcase_user()
        return {
            'customers': Customer.objects.filter(owner=user).count(),
            'insurances': CustomerInsurance.objects.filter(
                customer__owner=user,
            ).count(),
            'coverages': CustomerInsuranceDetail.objects.filter(
                insurance__customer__owner=user,
            ).count(),
            'goals': MonthlyGoal.objects.filter(owner=user).count(),
            'schedule': ScheduleItem.objects.filter(owner=user).count(),
            'work_hours': WorkHour.objects.filter(owner=user).count(),
            'meetings': Meeting.objects.filter(owner=user).count(),
            'notifications': Notification.objects.filter(owner=user).count(),
            'shares': ShareSnapshot.objects.filter(owner=user).count(),
        }

    def _relative_natural_state(self):
        user = self._showcase_user()
        customer_rows = tuple(
            (
                row.name,
                row.birth_day,
                row.sales_stage,
                row.status,
                timezone.localtime(row.created_at).date(),
            )
            for row in Customer.objects.filter(owner=user).order_by('name')
        )
        insurance_rows = tuple(
            (
                row.customer.name,
                row.name,
                row.contract_date,
                timezone.localtime(row.created_at).date(),
            )
            for row in CustomerInsurance.objects.filter(
                customer__owner=user,
            ).select_related('customer').order_by(
                'customer__name',
                'name',
                'contract_date',
            )
        )
        schedule_rows = tuple(
            (
                row.title,
                timezone.localtime(row.start_at).date(),
                timezone.localtime(row.start_at).time(),
            )
            for row in ScheduleItem.objects.filter(
                owner=user,
            ).order_by('title')
        )
        return {
            'customers': customer_rows,
            'insurances': insurance_rows,
            'goals': tuple(
                MonthlyGoal.objects.filter(owner=user)
                .order_by('year_month')
                .values_list('year_month', flat=True)
            ),
            'schedule': schedule_rows,
        }

    def test_apply_is_required_before_any_database_change(self):
        self._assert_error_without_changes('--apply',)

    def test_missing_email_setting_fails_without_database_change(self):
        with override_settings(SHOWCASE_ACCOUNT_EMAIL=''):
            self._assert_error_without_changes(
                'SHOWCASE_ACCOUNT_EMAIL',
                '--apply',
            )

    def test_missing_password_setting_fails_without_database_change(self):
        with override_settings(SHOWCASE_ACCOUNT_PASSWORD=''):
            self._assert_error_without_changes(
                'SHOWCASE_ACCOUNT_PASSWORD',
                '--apply',
            )

    def test_ordinary_account_with_configured_email_is_never_reset(self):
        ordinary = User.objects.create_user(
            email=_SHOWCASE_EMAIL,
            password=_ARBITRARY_TEST_VALUE,
        )
        Profile.objects.create(user=ordinary, is_showcase=False)
        self._assert_error_without_changes('시연 계정 표식', '--apply')

    def test_staff_collision_is_never_reset(self):
        user = User.objects.create_user(
            email=_SHOWCASE_EMAIL,
            password=_ARBITRARY_TEST_VALUE,
            is_staff=True,
        )
        Profile.objects.create(user=user, is_showcase=True)
        self._assert_error_without_changes('관리자 권한', '--apply')

    def test_superuser_collision_is_never_reset(self):
        user = User.objects.create_user(
            email=_SHOWCASE_EMAIL,
            password=_ARBITRARY_TEST_VALUE,
            is_superuser=True,
        )
        Profile.objects.create(user=user, is_showcase=True)
        self._assert_error_without_changes('관리자 권한', '--apply')

    def test_profile_admin_collision_is_never_reset(self):
        user = User.objects.create_user(
            email=_SHOWCASE_EMAIL,
            password=_ARBITRARY_TEST_VALUE,
        )
        Profile.objects.create(
            user=user,
            is_showcase=True,
            is_admin=True,
        )
        self._assert_error_without_changes('관리자 권한', '--apply')

    def test_missing_super_plan_fails_without_creating_it(self):
        Plan.objects.filter(code='super').delete()
        self._assert_error_without_changes('Super 요금제', '--apply')
        self.assertFalse(Plan.objects.filter(code='super').exists())

    def test_all_missing_standard_prerequisites_are_reported_before_writes(self):
        AnalysisDetail.objects.filter(
            name='일반사망',
            sub_category__category__name__startswith='[표준]',
        ).delete()
        InsuranceDetail.objects.filter(
            name='유사암진단비',
            sub_category__category__name__startswith='[표준]',
        ).delete()

        self._assert_error_without_changes(
            '일반사망',
            '--apply',
        )
        with self.assertRaises(CommandError) as raised:
            self._call('--apply')
        self.assertIn('유사암진단비', str(raised.exception))
        self.assertFalse(User.objects.filter(email=_SHOWCASE_EMAIL).exists())

    def test_empty_database_materializes_exact_showcase_contract(self):
        self._seed()
        user = self._showcase_user()
        profile = user.profile
        subscription = Subscription.objects.select_related('plan').get(
            user=user,
        )

        self.assertEqual(profile.name, '박도윤')
        self.assertEqual(profile.affiliation, '한빛금융서비스')
        self.assertEqual(profile.title, '팀장')
        self.assertTrue(profile.is_showcase)
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertFalse(profile.is_admin)
        self.assertIsNotNone(profile.email_verified_at)
        self.assertIsNotNone(profile.onboarding_completed_at)
        self.assertIsNotNone(profile.tour_completed_at)
        self.assertTrue(user.check_password(_ARBITRARY_TEST_VALUE))

        self.assertEqual(subscription.plan.code, 'super')
        self.assertEqual(subscription.status, 'active')
        self.assertFalse(subscription.auto_renew)
        self.assertIsNone(subscription.next_billing_at)
        self.assertIsNone(subscription.expires_at)
        self.assertEqual(subscription.pg_subscription_id, '')

        customers = Customer.objects.filter(owner=user)
        self.assertEqual(customers.count(), 50)
        self.assertEqual(customers.filter(is_favorite=True).count(), 8)
        self.assertEqual(
            Counter(customers.values_list('sales_stage', flat=True)),
            STAGE_COUNTS,
        )
        self.assertEqual(
            Counter(customers.values_list('status', flat=True)),
            STATUS_COUNTS,
        )
        self.assertEqual(
            CustomerInsurance.objects.filter(customer__owner=user).count(),
            80,
        )
        actual_coverage_count = sum(
            len(policy.coverages)
            for policy in INSURANCES
        )
        self.assertGreaterEqual(actual_coverage_count, 160)
        self.assertEqual(
            CustomerInsuranceDetail.objects.filter(
                insurance__customer__owner=user,
            ).count(),
            actual_coverage_count,
        )
        self.assertFalse(
            CustomerInsuranceDetail.objects.filter(
                insurance__customer__owner=user,
                mapping_source='planner_override',
                analysis_detail_override__isnull=True,
            ).exists()
        )
        self.assertEqual(MonthlyGoal.objects.filter(owner=user).count(), 6)
        schedule = ScheduleItem.objects.filter(owner=user)
        self.assertEqual(schedule.count(), 30)
        today = timezone.localdate()
        self.assertEqual(
            sum(
                timezone.localtime(item.start_at).date() == today
                for item in schedule
            ),
            3,
        )
        self.assertEqual(WorkHour.objects.filter(owner=user).count(), 5)
        self.assertEqual(
            Counter(
                Meeting.objects.filter(owner=user)
                .values_list('status', flat=True)
            ),
            {'pending': 2, 'confirmed': 3},
        )
        notifications = Notification.objects.filter(owner=user)
        self.assertEqual(notifications.count(), 12)
        self.assertTrue(notifications.filter(is_read=True).exists())
        self.assertTrue(notifications.filter(is_read=False).exists())

        anchor_names = {
            customer.name
            for customer in CUSTOMERS
            if customer.key in ANCHOR_CUSTOMER_KEYS
        }
        active_shares = ShareSnapshot.objects.filter(
            owner=user,
            customer__name__in=anchor_names,
            revoked_at__isnull=True,
            link_expires_at__gt=timezone.now(),
        )
        self.assertEqual(active_shares.count(), 2)

    def test_public_tables_and_global_catalog_links_never_change(self):
        before = _fingerprint(_PUBLIC_MODELS)
        self._seed()
        self.assertEqual(_fingerprint(_PUBLIC_MODELS), before)

    def test_second_apply_resets_only_safe_target_and_rebuilds_same_state(self):
        self._seed()
        first_user_id = self._showcase_user().pk
        first_counts = self._owned_counts()
        first_state = self._relative_natural_state()
        first_public = _fingerprint(_PUBLIC_MODELS)

        self._seed()

        self.assertEqual(
            User.objects.filter(email=_SHOWCASE_EMAIL).count(),
            1,
        )
        self.assertNotEqual(self._showcase_user().pk, first_user_id)
        self.assertEqual(self._owned_counts(), first_counts)
        self.assertEqual(self._relative_natural_state(), first_state)
        self.assertEqual(_fingerprint(_PUBLIC_MODELS), first_public)

    def test_forced_exception_rolls_back_user_and_every_owned_row(self):
        public_before = _fingerprint(_PUBLIC_MODELS)
        with patch(
            'inpa.analysis.management.commands.seed_showcase.'
            'Command._create_schedule_items',
            side_effect=RuntimeError('forced rollback'),
        ):
            with self.assertRaisesRegex(RuntimeError, 'forced rollback'):
                self._seed()

        self.assertFalse(User.objects.filter(email=_SHOWCASE_EMAIL).exists())
        self.assertEqual(_fingerprint(_PUBLIC_MODELS), public_before)
        self.assertFalse(ConsentLog.objects.filter(
            customer__owner__email=_SHOWCASE_EMAIL,
        ).exists())
        self.assertFalse(NorthStarEvent.objects.filter(
            sender__email=_SHOWCASE_EMAIL,
        ).exists())

    def test_guarded_purge_removes_only_showcase_rows_and_preserves_globals(self):
        self._seed()
        user = self._showcase_user()
        consent_ids = tuple(
            ConsentLog.objects.filter(
                customer__owner=user,
            ).values_list('pk', flat=True)
        )
        event_ids = tuple(
            NorthStarEvent.objects.filter(
                sender=user,
            ).values_list('pk', flat=True)
        )
        public_before = _fingerprint(_PUBLIC_MODELS)

        self._call('--purge', '--apply')

        self.assertFalse(User.objects.filter(email=_SHOWCASE_EMAIL).exists())
        self.assertFalse(ConsentLog.objects.filter(pk__in=consent_ids).exists())
        self.assertFalse(
            NorthStarEvent.objects.filter(pk__in=event_ids).exists()
        )
        self.assertEqual(_fingerprint(_PUBLIC_MODELS), public_before)

    def test_purge_refuses_target_after_showcase_flag_is_disabled(self):
        self._seed()
        user = self._showcase_user()
        Profile.objects.filter(user=user).update(is_showcase=False)

        self._assert_error_without_changes(
            '시연 계정 표식',
            '--purge',
            '--apply',
        )
        self.assertTrue(User.objects.filter(pk=user.pk).exists())

    def test_share_and_booking_public_prerequisites_are_live(self):
        self._seed()
        user = self._showcase_user()
        snapshots = list(
            ShareSnapshot.objects.filter(owner=user).select_related('customer')
        )
        self.assertEqual(len(snapshots), 2)
        public = APIClient()

        for snapshot in snapshots:
            self.assertEqual(
                snapshot.consent_doc_version,
                CONSENT_TEXTS_VERSION,
            )
            self.assertGreater(snapshot.link_expires_at, timezone.now())
            self.assertGreater(
                snapshot.retention_expires_at,
                snapshot.link_expires_at,
            )
            response = public.get(f'/api/v1/s/{snapshot.share_token}/')
            self.assertEqual(response.status_code, 200, response.content)
            booking_url = response.json()['actions']['booking_url']
            self.assertRegex(
                booking_url,
                r'^https://showcase\.example\.invalid/b/',
            )
            booking_token = urlparse(booking_url).path.removeprefix('/b/')
            booking_response = public.get(f'/api/v1/b/{booking_token}/')
            self.assertEqual(
                booking_response.status_code,
                200,
                booking_response.content,
            )

    def test_command_output_contains_counts_but_no_secret_phone_or_raw_token(self):
        output = self._seed()
        user = self._showcase_user()

        self.assertIn('고객 50', output)
        self.assertIn('증권 80', output)
        self.assertIn('대표 고객 ID', output)
        self.assertIn('/s/<보호된 토큰>', output)
        self.assertIn('/b/<보호된 토큰>', output)
        self.assertNotIn(_ARBITRARY_TEST_VALUE, output)
        self.assertNotIn(_SHOWCASE_EMAIL, output)
        for phone in Customer.objects.filter(
            owner=user,
        ).values_list('mobile_phone_number', flat=True):
            self.assertNotIn(phone, output)
        self.assertIsNone(re.search(
            r'[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-'
            r'[89ab][0-9a-f]{3}-[0-9a-f]{12}',
            output,
            re.IGNORECASE,
        ))
