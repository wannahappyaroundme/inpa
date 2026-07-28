import hashlib
import re
from collections import Counter
from datetime import datetime
from io import StringIO
from urllib.parse import urlparse
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from inpa.accounts.models import Profile
from inpa.analysis.management.commands.seed_showcase import (
    Command,
    _COVERAGE_TO_STANDARD,
)
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
from inpa.consultations.models import ConsultationRecording
from inpa.core.internal_accounts import is_showcase_user
from inpa.customers.consent_texts import CONSENT_TEXTS_VERSION
from inpa.customers.models import (
    ConsentLog,
    Customer,
    CustomerTag,
    JobRiskCode,
    PlannerBaseline,
)
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
_ROTATED_TEST_VALUE = 'test-only-rotated-' + '83ks'
_PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
_OVERMAPPING_DENYLIST = (
    '뇌혈관수술',
    '심혈관수술',
    '여성특정질환수술',
    '교통상해입원일당',
    '교통상해후유장해',
)
_SEMANTIC_EQUIVALENCE_ALLOWLIST = {
    '갑상선암진단': '갑상선암진단비',
    '골절수술': '골절수술비',
    '급성심근경색진단': '급성심근경색진단비',
    '뇌졸중진단': '뇌졸중진단비',
    '뇌혈관질환진단': '뇌혈관질환진단비',
    '변호사비용': '변호사선임비',
    '비급여도수치료': '실손비급여도수치료',
    '비급여주사': '실손비급여주사',
    '상해수술': '상해수술비',
    '상해입원일당': '상해입원일당',
    '상해종수술': '상해수술비',
    '상해후유장해': '상해후유장해',
    '암수술': '암수술비',
    '어린이상해수술': '상해수술비',
    '어린이질병수술': '질병수술비',
    '유사암진단': '유사암진단비',
    '일반사망': '일반사망',
    '일반암진단': '일반암진단비',
    '일상생활배상': '일상생활배상책임',
    '질병수술': '질병수술비',
    '질병입원일당': '질병입원일당',
    '질병종수술': '질병수술비',
    '질병후유장해': '질병후유장해',
    '항암약물치료': '항암약물치료비',
    '허혈성심장질환진단': '허혈성심장질환진단비',
    '화상수술': '화상수술비',
}
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
        call_command('seed_jobs', stdout=StringIO())
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

    def _complete_business_state(self):
        user = self._showcase_user()
        profile = user.profile
        profile_fields = (
            'name',
            'affiliation',
            'title',
            'phone',
            'intro_text',
            'booking_msg_template',
            'booking_location',
            'booking_default_duration',
            'booking_buffer_min',
            'license_no',
            'career_years',
            'is_admin',
            'is_showcase',
            'is_dormant',
            'manager_id',
            'manager_promoted_at',
            'manager_promotion_seen_at',
            'cohort_opt_in',
            'manager_share_opt_in',
            'manager_share_level',
            'utm_source',
            'utm_medium',
            'utm_campaign',
            'google_sub',
            'google_calendar_refresh_token',
            'google_calendar_connected_at',
            'google_calendar_mask_name',
            'profile_image',
        )
        customer_rows = tuple(
            Customer.objects.filter(owner=user).order_by('name').values_list(
                'name',
                'job_code__sctg_cd',
                'job_code__name',
                'lead_source',
                'lead_created_at',
                'sales_stage',
                'status',
                'is_favorite',
                'is_pinned',
            )
        )
        insurance_rows = tuple(
            CustomerInsurance.objects.filter(
                customer__owner=user,
            ).select_related('customer').order_by(
                'customer__name',
                'name',
                'contract_date',
            ).values_list(
                'customer__name',
                'name',
                'portfolio_type',
                'payment_status',
                'monthly_premiums',
                'monthly_renewal_premium',
                'monthly_non_renewal_premium',
                'monthly_earned_premium',
                'total_renewal_premium',
                'total_non_renewal_premium',
                'total_earned_premium',
            )
        )
        coverage_rows = tuple(
            CustomerInsuranceDetail.objects.filter(
                insurance__customer__owner=user,
            ).select_related(
                'insurance__customer',
            ).order_by(
                'insurance__customer__name',
                'insurance__name',
                'raw_name',
                'assurance_amount',
            ).values_list(
                'insurance__customer__name',
                'insurance__name',
                'raw_name',
                'assurance_amount',
                'premium',
                'renewal_period',
                'payment_period_type',
            )
        )
        baseline_rows = tuple(
            PlannerBaseline.objects.filter(owner=user).order_by(
                'analysis_detail__name',
            ).values_list(
                'analysis_detail__name',
                'coverage_key',
                'product_group',
                'age_band',
                'gender',
                'recommend_min',
                'recommend_max',
                'unit',
                'baseline_source',
                'is_active',
            )
        )
        return {
            'profile': tuple(
                profile.profile_image.name
                if name == 'profile_image'
                else getattr(profile, name)
                for name in profile_fields
            ),
            'customers': customer_rows,
            'insurances': insurance_rows,
            'coverages': coverage_rows,
            'baselines': baseline_rows,
            'counts': self._owned_counts(),
        }

    def test_apply_is_required_before_any_database_change(self):
        self._assert_error_without_changes('--apply',)

    def test_postgresql_target_lock_query_has_no_nullable_profile_join(self):
        queryset = Command._target_user_lock_queryset(_SHOWCASE_EMAIL)
        with (
            patch.object(connection, 'vendor', 'postgresql'),
            patch.object(
                connection.features,
                'has_select_for_update',
                True,
            ),
        ):
            sql = str(queryset.query)

        self.assertIn('FOR UPDATE', sql.upper())
        self.assertNotIn('accounts_profile', sql)
        self.assertFalse(queryset.query.select_related)

    def test_missing_email_setting_fails_without_database_change(self):
        with override_settings(SHOWCASE_ACCOUNT_EMAIL=''):
            self._assert_error_without_changes(
                'SHOWCASE_ACCOUNT_EMAIL',
                '--apply',
            )

    def test_noncanonical_showcase_email_is_rejected_before_writes(self):
        invalid_values = (
            f' {_SHOWCASE_EMAIL}',
            f'{_SHOWCASE_EMAIL} ',
            'Internal-Showcase@test.example',
            'internal-showcase@Test.Example',
        )
        for value in invalid_values:
            with self.subTest(value=value), override_settings(
                SHOWCASE_ACCOUNT_EMAIL=value,
            ):
                self._assert_error_without_changes(
                    '소문자 표준 형식',
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

    def test_inactive_super_plan_fails_without_database_change(self):
        Plan.objects.filter(code='super').update(is_active=False)
        self._assert_error_without_changes('활성 Super 요금제', '--apply')

    def test_missing_job_catalog_fails_without_database_change(self):
        JobRiskCode.objects.all().delete()
        self._assert_error_without_changes('직업급수', '--apply')

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
        self.assertTrue(is_showcase_user(user))
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertFalse(profile.is_admin)
        self.assertEqual(profile.phone, '010-1986-4270')
        self.assertEqual(
            profile.intro_text,
            '가족의 현재 보장을 한눈에 정리해 드립니다.',
        )
        self.assertIn('{고객명}', profile.booking_msg_template)
        self.assertFalse(profile.cohort_opt_in)
        self.assertFalse(profile.manager_share_opt_in)
        self.assertEqual(profile.manager_share_level, Profile.SHARE_NONE)
        self.assertIsNone(profile.manager_id)
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
        self.assertFalse(customers.filter(job_code__isnull=True).exists())
        self.assertFalse(customers.filter(lead_created_at__isnull=False).exists())
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
                raw_name__in=_SEMANTIC_EQUIVALENCE_ALLOWLIST,
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

        policies = CustomerInsurance.objects.filter(customer__owner=user)
        self.assertEqual(
            set(policies.values_list('portfolio_type', flat=True)),
            {1, 2},
        )
        self.assertEqual(
            set(policies.values_list('payment_status', flat=True)),
            {1, 2, 3},
        )
        self.assertTrue(policies.filter(
            monthly_renewal_premium__gt=0,
        ).exists())
        self.assertTrue(policies.filter(
            monthly_non_renewal_premium__gt=0,
        ).exists())
        self.assertTrue(policies.filter(
            monthly_earned_premium__gt=0,
        ).exists())
        self.assertTrue(policies.filter(
            total_renewal_premium__gt=0,
        ).exists())
        self.assertTrue(policies.filter(
            total_non_renewal_premium__gt=0,
        ).exists())
        self.assertTrue(policies.filter(
            total_earned_premium__gt=0,
        ).exists())

    @override_settings(HEATMAP_GRADING_ENABLED=True)
    def test_anchor_heatmaps_include_meaningful_three_colour_results(self):
        self._seed()
        user = self._showcase_user()
        client = APIClient()
        client.force_authenticate(user=user)
        anchor_names = {
            spec.name
            for spec in CUSTOMERS
            if spec.key in ANCHOR_CUSTOMER_KEYS
        }
        statuses = set()
        for customer in Customer.objects.filter(
            owner=user,
            name__in=anchor_names,
        ):
            response = client.get(
                f'/api/v1/customers/{customer.pk}/heatmap/',
            )
            self.assertEqual(response.status_code, 200, response.content)
            body = response.json()
            self.assertEqual(body['mode'], 'graded')
            statuses.update(
                detail['status']
                for category in body['tree']
                for subcategory in category['sub_categories']
                for detail in subcategory['details']
            )
        self.assertTrue({'shortage', 'adequate', 'over'}.issubset(statuses))

    def test_anchor_default_comparisons_have_distinct_nonempty_sides(self):
        self._seed()
        user = self._showcase_user()
        client = APIClient()
        client.force_authenticate(user=user)
        anchors = Customer.objects.filter(
            owner=user,
            name__in={
                spec.name
                for spec in CUSTOMERS
                if spec.key in ANCHOR_CUSTOMER_KEYS
            },
        )
        for customer in anchors:
            response = client.get(
                f'/api/v1/customers/{customer.pk}/compare/',
            )
            self.assertEqual(response.status_code, 200, response.content)
            body = response.json()
            left_ids = {
                row['id'] for row in body['current']['insurances']
            }
            right_ids = {
                row['id'] for row in body['proposed']['insurances']
            }
            self.assertTrue(left_ids)
            self.assertTrue(right_ids)
            self.assertNotEqual(left_ids, right_ids)
            self.assertTrue(left_ids.isdisjoint(right_ids))

    def test_public_tables_and_global_catalog_links_never_change(self):
        before = _fingerprint(_PUBLIC_MODELS)
        self._seed()
        self.assertEqual(_fingerprint(_PUBLIC_MODELS), before)

    def test_only_semantically_equivalent_coverages_receive_overrides(self):
        self.assertEqual(
            _COVERAGE_TO_STANDARD,
            _SEMANTIC_EQUIVALENCE_ALLOWLIST,
        )
        self._seed()
        user = self._showcase_user()
        cases = (
            CustomerInsuranceDetail.objects.filter(
                insurance__customer__owner=user,
            )
            .select_related('insurance__customer')
            .prefetch_related('analysis_detail_override')
        )

        mapped_by_anchor = Counter()
        anchor_names = {
            spec.name
            for spec in CUSTOMERS
            if spec.key in ANCHOR_CUSTOMER_KEYS
        }
        for case in cases:
            override_names = list(
                case.analysis_detail_override.values_list(
                    'name',
                    flat=True,
                )
            )
            expected_name = _SEMANTIC_EQUIVALENCE_ALLOWLIST.get(
                case.raw_name,
            )
            if expected_name is None:
                self.assertEqual(
                    override_names,
                    [],
                    f'{case.raw_name} must remain raw-only',
                )
            else:
                self.assertEqual(override_names, [expected_name])
                if case.insurance.customer.name in anchor_names:
                    mapped_by_anchor[case.insurance.customer.name] += 1

        self.assertGreaterEqual(sum(mapped_by_anchor.values()), 80)
        self.assertEqual(len(mapped_by_anchor), len(ANCHOR_CUSTOMER_KEYS))
        self.assertTrue(all(count >= 10 for count in mapped_by_anchor.values()))
        for unsafe_name in (
            '치아임플란트',
            '골절진단',
            '화상진단',
            '간병인지원',
            '응급실내원',
        ):
            self.assertFalse(cases.filter(
                raw_name=unsafe_name,
                analysis_detail_override__isnull=False,
            ).exists())

    def test_broad_synthetic_coverages_stay_raw_only_across_all_outputs(self):
        self._seed()
        user = self._showcase_user()
        cases = list(
            CustomerInsuranceDetail.objects.filter(
                insurance__customer__owner=user,
                raw_name__in=_OVERMAPPING_DENYLIST,
            )
            .select_related('insurance__customer')
            .prefetch_related('analysis_detail_override')
        )
        self.assertEqual(
            {case.raw_name for case in cases},
            set(_OVERMAPPING_DENYLIST),
        )

        denied_ids_by_customer = {}
        for case in cases:
            self.assertEqual(
                list(case.analysis_detail_override.all()),
                [],
                f'{case.raw_name} must have no materialized override',
            )
            self.assertEqual(
                list(case.effective_analysis_details()),
                [],
                f'{case.raw_name} must not enter an effective set',
            )
            denied_ids_by_customer.setdefault(
                case.insurance.customer_id,
                set(),
            ).add(case.pk)

        def held_amounts(body):
            return {
                detail['name']: detail['held_amount']
                for category in body['tree']
                for subcategory in category['sub_categories']
                for detail in subcategory['details']
            }

        client = APIClient()
        client.force_authenticate(user=user)
        from inpa.analytics.views import _build_share_payload

        for customer_id, denied_case_ids in denied_ids_by_customer.items():
            heatmap_response = client.get(
                f'/api/v1/customers/{customer_id}/heatmap/',
            )
            self.assertEqual(
                heatmap_response.status_code,
                200,
                heatmap_response.content,
            )
            heatmap = heatmap_response.json()
            contribution_case_ids = {
                contribution['case_id']
                for category in heatmap['tree']
                for subcategory in category['sub_categories']
                for detail in subcategory['details']
                for contribution in detail['contributions']
            }
            self.assertTrue(
                denied_case_ids.isdisjoint(contribution_case_ids),
            )

            compare_response = client.get(
                f'/api/v1/customers/{customer_id}/compare/',
            )
            self.assertEqual(
                compare_response.status_code,
                200,
                compare_response.content,
            )
            compare_amounts = {
                row['coverage']: row['current_amount']
                for row in compare_response.json()['rows']
                if row['current_amount']
            }
            heatmap_amounts = {
                name: amount
                for name, amount in held_amounts(heatmap).items()
                if amount
            }
            self.assertEqual(compare_amounts, heatmap_amounts)

            customer = Customer.objects.get(pk=customer_id)
            share = _build_share_payload(customer)
            self.assertEqual(held_amounts(share), held_amounts(heatmap))

    def test_second_apply_resets_only_safe_target_and_rebuilds_same_state(self):
        self._seed()
        first_user_id = self._showcase_user().pk
        first_counts = self._owned_counts()
        first_state = self._relative_natural_state()
        first_complete_state = self._complete_business_state()
        first_public = _fingerprint(_PUBLIC_MODELS)

        profile = self._showcase_user().profile
        Profile.objects.filter(pk=profile.pk).update(
            phone='010-1999-9999',
            intro_text='바뀐 소개',
            booking_msg_template='바뀐 예약 문구',
            cohort_opt_in=True,
            manager_share_opt_in=True,
            manager_share_level=Profile.SHARE_FULL,
            marketing_agreed_at=timezone.now(),
            is_dormant=True,
            google_calendar_refresh_token='changed-local-value',
        )
        self._seed()

        self.assertEqual(
            User.objects.filter(email=_SHOWCASE_EMAIL).count(),
            1,
        )
        self.assertEqual(self._showcase_user().pk, first_user_id)
        self.assertEqual(self._owned_counts(), first_counts)
        self.assertEqual(self._relative_natural_state(), first_state)
        rebuilt_complete_state = self._complete_business_state()
        for key, expected in first_complete_state.items():
            with self.subTest(complete_state=key):
                self.assertEqual(rebuilt_complete_state[key], expected)
        self.assertEqual(_fingerprint(_PUBLIC_MODELS), first_public)

    def test_reset_revokes_existing_token_and_accepts_configured_password(self):
        self._seed()
        login = APIClient().post(
            '/api/v1/auth/login/',
            {
                'email': _SHOWCASE_EMAIL,
                'password': _ARBITRARY_TEST_VALUE,
            },
            format='json',
        )
        self.assertEqual(login.status_code, 200, login.content)
        old_token = login.json()['token']
        authenticated = APIClient()
        authenticated.credentials(
            HTTP_AUTHORIZATION=f'Token {old_token}',
        )
        self.assertEqual(
            authenticated.get('/api/v1/auth/profile/').status_code,
            200,
        )

        with override_settings(
            SHOWCASE_ACCOUNT_PASSWORD=_ROTATED_TEST_VALUE,
        ):
            self._call('--apply')

        self.assertFalse(Token.objects.filter(key=old_token).exists())
        self.assertEqual(
            authenticated.get('/api/v1/auth/profile/').status_code,
            401,
        )
        relogin = APIClient().post(
            '/api/v1/auth/login/',
            {
                'email': _SHOWCASE_EMAIL,
                'password': _ROTATED_TEST_VALUE,
            },
            format='json',
        )
        self.assertEqual(relogin.status_code, 200, relogin.content)
        self.assertNotEqual(relogin.json()['token'], old_token)

    def test_reset_preserves_foreign_manager_link_and_purge_refuses_it(self):
        self._seed()
        showcase = self._showcase_user()
        foreign_user = User.objects.create_user(
            email='foreign-manager-link@test.example',
            password=_ARBITRARY_TEST_VALUE,
        )
        foreign_profile = Profile.objects.create(
            user=foreign_user,
            manager=showcase,
        )
        profile_fields = [
            field.attname
            for field in Profile._meta.concrete_fields
        ]
        foreign_row = tuple(
            Profile.objects.filter(pk=foreign_profile.pk).values_list(
                *profile_fields
            )
        )

        self._seed()

        showcase.refresh_from_db()
        foreign_profile.refresh_from_db()
        self.assertEqual(foreign_profile.manager_id, showcase.pk)
        self.assertEqual(
            tuple(
                Profile.objects.filter(pk=foreign_profile.pk).values_list(
                    *profile_fields
                )
            ),
            foreign_row,
        )

        before_purge = _database_fingerprint()
        self._assert_error_without_changes(
            '외부 참조',
            '--purge',
            '--apply',
        )
        self.assertEqual(_database_fingerprint(), before_purge)
        foreign_profile.refresh_from_db()
        self.assertEqual(foreign_profile.manager_id, showcase.pk)

    def test_recording_blocks_reset_and_purge_without_queue_or_storage_work(self):
        self._seed()
        user = self._showcase_user()
        customer = Customer.objects.filter(owner=user).first()
        ConsultationRecording.objects.create(
            owner=user,
            customer=customer,
            status=ConsultationRecording.STATUS_READY,
            storage_key='consultation-recordings/showcase/source',
            mime_type='audio/webm',
        )

        with (
            patch(
                'inpa.consultations.signals.transaction.on_commit',
            ) as on_commit,
            patch(
                'inpa.consultations.signals.delete_exact_sources.delay',
            ) as queue_delete,
        ):
            for args in (('--apply',), ('--purge', '--apply')):
                with self.subTest(args=args):
                    self._assert_error_without_changes('녹음', *args)

        on_commit.assert_not_called()
        queue_delete.assert_not_called()

    def test_month_start_seed_chronology_never_enters_the_future(self):
        seoul = ZoneInfo('Asia/Seoul')
        for day in (1, 2):
            reference = datetime(2026, 8, day, 8, 15, tzinfo=seoul)
            with (
                self.subTest(day=day),
                patch(
                    'inpa.analysis.management.commands.seed_showcase.'
                    'timezone.now',
                    return_value=reference,
                ),
                patch(
                    'inpa.analysis.management.commands.seed_showcase.'
                    'timezone.localdate',
                    return_value=reference.date(),
                ),
            ):
                self._seed()

            user = self._showcase_user()
            for customer in Customer.objects.filter(owner=user):
                self.assertLessEqual(customer.created_at, reference)
                self.assertGreaterEqual(
                    customer.last_contacted_at,
                    customer.created_at,
                )
                self.assertLessEqual(customer.last_contacted_at, reference)
                if customer.fa_reached_at is not None:
                    self.assertGreaterEqual(
                        customer.fa_reached_at,
                        customer.created_at,
                    )
                    self.assertLessEqual(customer.fa_reached_at, reference)
            for insurance in CustomerInsurance.objects.filter(
                customer__owner=user,
            ):
                self.assertLessEqual(insurance.created_at, reference)
                self.assertEqual(
                    insurance.confirmed_at,
                    insurance.created_at,
                )
                self.assertLessEqual(insurance.confirmed_at, reference)
                self.assertLessEqual(
                    datetime.fromisoformat(insurance.contract_date).date(),
                    timezone.localtime(
                        insurance.created_at,
                        seoul,
                    ).date(),
                )

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

    def test_late_reset_failure_restores_original_complete_snapshot(self):
        self._seed()
        original_user_id = self._showcase_user().pk
        before_database = _database_fingerprint()
        before_public = _fingerprint(_PUBLIC_MODELS)
        original_create_shares = Command._create_public_shares

        def create_shares_then_fail(user, customers, now):
            original_create_shares(user, customers, now)
            self.assertEqual(
                User.objects.get(email=_SHOWCASE_EMAIL).pk,
                original_user_id,
            )
            raise RuntimeError('forced pre-commit rollback')

        with patch.object(
            Command,
            '_create_public_shares',
            side_effect=create_shares_then_fail,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                'forced pre-commit rollback',
            ):
                self._seed()

        self.assertEqual(self._showcase_user().pk, original_user_id)
        self.assertEqual(_database_fingerprint(), before_database)
        self.assertEqual(_fingerprint(_PUBLIC_MODELS), before_public)

    def test_late_reset_failure_restores_existing_auth_token(self):
        self._seed()
        user = self._showcase_user()
        token, _created = Token.objects.get_or_create(user=user)
        original_token_key = token.key
        authenticated = APIClient()
        authenticated.credentials(
            HTTP_AUTHORIZATION=f'Token {original_token_key}',
        )
        self.assertEqual(
            authenticated.get('/api/v1/auth/profile/').status_code,
            200,
        )
        before_database = _database_fingerprint()
        original_create_shares = Command._create_public_shares

        def create_shares_then_fail(reset_user, customers, now):
            original_create_shares(reset_user, customers, now)
            self.assertFalse(Token.objects.filter(
                user=reset_user,
                key=original_token_key,
            ).exists())
            raise RuntimeError('forced rollback after token deletion')

        with patch.object(
            Command,
            '_create_public_shares',
            side_effect=create_shares_then_fail,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                'forced rollback after token deletion',
            ):
                self._seed()

        self.assertTrue(Token.objects.filter(
            user_id=user.pk,
            key=original_token_key,
        ).exists())
        restored = Token.objects.get(user_id=user.pk)
        self.assertEqual(restored.key, original_token_key)
        self.assertEqual(_database_fingerprint(), before_database)
        self.assertEqual(
            authenticated.get('/api/v1/auth/profile/').status_code,
            200,
        )

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

    def test_purge_needs_no_password_catalog_or_active_super_plan(self):
        self._seed()
        JobRiskCode.objects.all().delete()
        AnalysisCategory.objects.filter(
            name__startswith='[표준]',
        ).update(name='표준 경로 없음')
        InsuranceCategory.objects.filter(
            name__startswith='[표준]',
        ).update(name='표준 경로 없음')
        Plan.objects.filter(code='super').update(is_active=False)

        with override_settings(SHOWCASE_ACCOUNT_PASSWORD=''):
            self._call('--purge', '--apply')

        self.assertFalse(User.objects.filter(email=_SHOWCASE_EMAIL).exists())

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
        owner = APIClient()
        owner.force_authenticate(user=user)
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
            self.assertTrue(booking_response.json()['slots'])

            direct_link = owner.post(
                f'/api/v1/customers/{snapshot.customer_id}/'
                'booking-requests/',
            )
            self.assertEqual(direct_link.status_code, 201, direct_link.content)
            self.assertIn(
                direct_link.json()['booking_url'],
                direct_link.json()['message'],
            )
            direct_token = urlparse(
                direct_link.json()['booking_url'],
            ).path.removeprefix('/b/')
            direct_public = public.get(f'/api/v1/b/{direct_token}/')
            self.assertEqual(
                direct_public.status_code,
                200,
                direct_public.content,
            )
            self.assertTrue(direct_public.json()['slots'])

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


@override_settings(
    SHOWCASE_ACCOUNT_EMAIL=_SHOWCASE_EMAIL,
    SHOWCASE_ACCOUNT_PASSWORD=_ARBITRARY_TEST_VALUE,
    PASSWORD_HASHERS=_PASSWORD_HASHERS,
    BOOKING_ENABLED=True,
    BOOKING_TOKEN_TTL_HOURS=72,
    FRONTEND_BASE_URL='https://app.example.invalid',
    INSURANCE_REVIEW_GATE_ENABLED=True,
    LEGACY_SHARE_FALLBACK_ENABLED=False,
    FREE_TIER_UNLIMITED=True,
)
class ShowcaseApiIntegrationTests(TestCase):
    """Exercise the seeded account through the same API contracts as the UI."""

    ANCHOR_NAMES = (
        '김도윤',
        '이서현',
        '박지훈',
        '최유진',
        '정현우',
        '한소연',
        '조민재',
        '윤하늘',
    )

    @classmethod
    def setUpTestData(cls):
        call_command('seed_normalization', '--force', stdout=StringIO())
        call_command('seed_jobs', stdout=StringIO())
        free_plan, _created = Plan.objects.get_or_create(
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
        call_command('seed_showcase', '--apply', stdout=StringIO())
        cls.showcase_user = User.objects.get(email=_SHOWCASE_EMAIL)

        cls.ordinary_password = 'ordinary-only-value-72mq'
        cls.ordinary_user = User.objects.create_user(
            email='ordinary-api-user@test.example',
            password=cls.ordinary_password,
            is_active=True,
        )
        Profile.objects.create(
            user=cls.ordinary_user,
            email_verified_at=timezone.now(),
        )
        Subscription.objects.update_or_create(
            user=cls.ordinary_user,
            defaults={'plan': free_plan, 'status': 'active'},
        )
        cls.ordinary_customer = Customer.objects.create(
            owner=cls.ordinary_user,
            name='일반계정고객',
            mobile_phone_number='010-1888-7777',
            birth_day='1989-04-03',
            gender=1,
            sales_stage=Customer.STAGE_CONTACT,
            memo='일반 계정 소유 격리 확인 자료',
        )
        cls.ordinary_insurance = CustomerInsurance.objects.create(
            customer=cls.ordinary_customer,
            insurance_type=1,
            portfolio_type=1,
            name='일반 계정 보장형',
            monthly_premiums=70_000,
            review_status='draft',
            analysis_included=False,
        )
        cls.ordinary_schedule = ScheduleItem.objects.create(
            owner=cls.ordinary_user,
            customer=cls.ordinary_customer,
            kind=ScheduleItem.KIND_EVENT,
            category=ScheduleItem.CAT_TASK,
            title='일반 계정 일정',
            start_at=timezone.now(),
        )
        cls.ordinary_notification = Notification.objects.create(
            owner=cls.ordinary_user,
            customer=cls.ordinary_customer,
            notif_type='task_due',
            title='일반 계정 알림',
            body='일반 계정만 볼 수 있는 알림',
        )

        cls.admin_password = 'admin-only-value-39zr'
        cls.admin_user = User.objects.create_user(
            email='showcase-api-admin@test.example',
            password=cls.admin_password,
            is_active=True,
        )
        Profile.objects.create(
            user=cls.admin_user,
            email_verified_at=timezone.now(),
            is_admin=True,
        )
        Subscription.objects.update_or_create(
            user=cls.admin_user,
            defaults={'plan': free_plan, 'status': 'active'},
        )

    def _authenticated_client(self, email, password):
        login = APIClient().post(
            '/api/v1/auth/login/',
            {'email': email, 'password': password},
            format='json',
        )
        self.assertEqual(login.status_code, 200, login.content)
        self.assertEqual(login.json()['email'], email)
        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=f"Token {login.json()['token']}",
        )
        return client

    def _showcase_client(self):
        return self._authenticated_client(
            _SHOWCASE_EMAIL,
            _ARBITRARY_TEST_VALUE,
        )

    def _ordinary_client(self):
        return self._authenticated_client(
            self.ordinary_user.email,
            self.ordinary_password,
        )

    def _admin_client(self):
        return self._authenticated_client(
            self.admin_user.email,
            self.admin_password,
        )

    def _paginated_results(self, client, path):
        first = client.get(path)
        self.assertEqual(first.status_code, 200, first.content)
        body = first.json()
        if isinstance(body, list):
            return len(body), body

        results = list(body['results'])
        next_url = body.get('next')
        while next_url:
            parsed = urlparse(next_url)
            next_path = parsed.path
            if parsed.query:
                next_path += f'?{parsed.query}'
            page = client.get(next_path)
            self.assertEqual(page.status_code, 200, page.content)
            page_body = page.json()
            results.extend(page_body['results'])
            next_url = page_body.get('next')
        return body['count'], results

    def _assert_foreign_row_hidden(
        self,
        *,
        client,
        get_path,
        patch_path,
        patch_body,
        delete_path,
        delete_body=None,
    ):
        self.assertEqual(client.get(get_path).status_code, 404)
        self.assertEqual(
            client.patch(patch_path, patch_body, format='json').status_code,
            404,
        )
        self.assertEqual(
            client.delete(
                delete_path,
                delete_body or {},
                format='json',
            ).status_code,
            404,
        )

    @staticmethod
    def _isolation_state(customer, insurance, schedule, notification):
        return {
            'customer': (
                customer.memo,
                customer.sales_stage,
                customer.updated_at,
            ),
            'insurance': (
                insurance.name,
                insurance.data_version,
                insurance.updated_at,
            ),
            'schedule': (
                schedule.title,
                schedule.updated_at,
            ),
            'notification': notification.is_read,
        }

    def test_showcase_and_ordinary_users_authenticate_and_admin_policy_holds(self):
        showcase = self._showcase_client()
        ordinary = self._ordinary_client()
        admin = self._admin_client()

        self.assertEqual(
            showcase.get('/api/v1/auth/profile/').status_code,
            200,
        )
        self.assertEqual(
            ordinary.get('/api/v1/auth/profile/').status_code,
            200,
        )

        anchor = Customer.objects.get(
            owner=self.showcase_user,
            name=self.ANCHOR_NAMES[0],
        )
        admin_customer = admin.get(f'/api/v1/customers/{anchor.pk}/')
        self.assertEqual(admin_customer.status_code, 200, admin_customer.content)
        ops_customers = admin.get(
            f'/api/v1/admin/users/{self.showcase_user.pk}/customers/',
        )
        self.assertEqual(ops_customers.status_code, 200, ops_customers.content)
        self.assertEqual(ops_customers.json()['count'], 50)

        self.assertEqual(
            showcase.get('/api/v1/admin/users/').status_code,
            403,
        )
        self.assertEqual(
            showcase.get(
                f'/api/v1/admin/users/{self.showcase_user.pk}/customers/',
            ).status_code,
            403,
        )

    def test_bidirectional_customer_insurance_schedule_notification_isolation(self):
        showcase = self._showcase_client()
        ordinary = self._ordinary_client()
        anchor = Customer.objects.get(
            owner=self.showcase_user,
            name=self.ANCHOR_NAMES[0],
        )
        showcase_insurance = CustomerInsurance.objects.filter(
            customer=anchor,
        ).order_by('pk').first()
        showcase_schedule = ScheduleItem.objects.filter(
            owner=self.showcase_user,
        ).order_by('pk').first()
        showcase_notification = Notification.objects.filter(
            owner=self.showcase_user,
        ).order_by('pk').first()
        showcase_before = self._isolation_state(
            anchor,
            showcase_insurance,
            showcase_schedule,
            showcase_notification,
        )
        ordinary_before = self._isolation_state(
            self.ordinary_customer,
            self.ordinary_insurance,
            self.ordinary_schedule,
            self.ordinary_notification,
        )

        pairs = (
            (
                ordinary,
                self.ordinary_customer,
                anchor,
                showcase_insurance,
                showcase_schedule,
                showcase_notification,
            ),
            (
                showcase,
                anchor,
                self.ordinary_customer,
                self.ordinary_insurance,
                self.ordinary_schedule,
                self.ordinary_notification,
            ),
        )
        for (
            actor,
            actor_owned_customer,
            foreign_customer,
            foreign_insurance,
            foreign_schedule,
            foreign_notification,
        ) in pairs:
            with self.subTest(
                actor=actor,
                foreign_customer=foreign_customer.pk,
            ):
                self._assert_foreign_row_hidden(
                    client=actor,
                    get_path=f'/api/v1/customers/{foreign_customer.pk}/',
                    patch_path=f'/api/v1/customers/{foreign_customer.pk}/',
                    patch_body={'memo': '경계를 넘는 수정'},
                    delete_path=f'/api/v1/customers/{foreign_customer.pk}/',
                )
                insurance_path = (
                    f'/api/v1/customers/{foreign_customer.pk}/insurances/'
                    f'manual/{foreign_insurance.pk}/'
                )
                self._assert_foreign_row_hidden(
                    client=actor,
                    get_path=insurance_path,
                    patch_path=insurance_path,
                    patch_body={
                        'name': '경계를 넘는 보험 수정',
                        'data_version': foreign_insurance.data_version,
                    },
                    delete_path=insurance_path,
                    delete_body={
                        'data_version': foreign_insurance.data_version,
                    },
                )
                mixed_insurance_path = (
                    f'/api/v1/customers/{actor_owned_customer.pk}/'
                    f'insurances/manual/{foreign_insurance.pk}/'
                )
                self._assert_foreign_row_hidden(
                    client=actor,
                    get_path=mixed_insurance_path,
                    patch_path=mixed_insurance_path,
                    patch_body={
                        'name': '부모를 섞은 보험 수정',
                        'data_version': foreign_insurance.data_version,
                    },
                    delete_path=mixed_insurance_path,
                    delete_body={
                        'data_version': foreign_insurance.data_version,
                    },
                )
                schedule_path = (
                    f'/api/v1/schedule-items/{foreign_schedule.pk}/'
                )
                self._assert_foreign_row_hidden(
                    client=actor,
                    get_path=schedule_path,
                    patch_path=schedule_path,
                    patch_body={'title': '경계를 넘는 일정 수정'},
                    delete_path=schedule_path,
                )
                notification_path = (
                    f'/api/v1/notifications/{foreign_notification.pk}/'
                )
                self._assert_foreign_row_hidden(
                    client=actor,
                    get_path=notification_path,
                    patch_path=(
                        f'/api/v1/notifications/'
                        f'{foreign_notification.pk}/read/'
                    ),
                    patch_body={},
                    delete_path=notification_path,
                )

        anchor.refresh_from_db()
        showcase_insurance.refresh_from_db()
        showcase_schedule.refresh_from_db()
        showcase_notification.refresh_from_db()
        self.ordinary_customer.refresh_from_db()
        self.ordinary_insurance.refresh_from_db()
        self.ordinary_schedule.refresh_from_db()
        self.ordinary_notification.refresh_from_db()
        self.assertEqual(
            self._isolation_state(
                anchor,
                showcase_insurance,
                showcase_schedule,
                showcase_notification,
            ),
            showcase_before,
        )
        self.assertEqual(
            self._isolation_state(
                self.ordinary_customer,
                self.ordinary_insurance,
                self.ordinary_schedule,
                self.ordinary_notification,
            ),
            ordinary_before,
        )

    def test_seeded_account_serves_all_primary_screen_contracts(self):
        client = self._showcase_client()

        dashboard = client.get('/api/v1/dashboard/')
        self.assertEqual(dashboard.status_code, 200, dashboard.content)
        for key in (
            'target_meetings',
            'target_premium',
            'actual_meetings',
            'actual_premium',
            'actual_new_customers',
            'expected_income',
        ):
            self.assertIn(key, dashboard.json())

        goal_months = list(
            MonthlyGoal.objects.filter(owner=self.showcase_user)
            .order_by('-year_month')
            .values_list('year_month', flat=True)
        )
        self.assertEqual(len(goal_months), 6)
        for month in goal_months:
            response = client.get(f'/api/v1/dashboard/?month={month}')
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(response.json()['year_month'], month)
        insights = client.get('/api/v1/dashboard/insights/?months=6')
        self.assertEqual(insights.status_code, 200, insights.content)
        self.assertEqual(len(insights.json()['monthly_trend']), 6)

        customer_count, customer_rows = self._paginated_results(
            client,
            '/api/v1/customers/',
        )
        self.assertEqual(customer_count, 50)
        self.assertEqual(len(customer_rows), 50)
        self.assertEqual(len({row['id'] for row in customer_rows}), 50)
        self.assertEqual(
            Counter(row['sales_stage'] for row in customer_rows),
            {'db': 14, 'contact': 12, 'meeting': 12, 'contract': 12},
        )

        for anchor_name in self.ANCHOR_NAMES:
            with self.subTest(anchor=anchor_name):
                customer = Customer.objects.get(
                    owner=self.showcase_user,
                    name=anchor_name,
                )
                detail = client.get(f'/api/v1/customers/{customer.pk}/')
                self.assertEqual(detail.status_code, 200, detail.content)
                self.assertEqual(detail.json()['name'], anchor_name)

                insurance_count, policies = self._paginated_results(
                    client,
                    (
                        f'/api/v1/customers/{customer.pk}/'
                        'insurances/manual/'
                    ),
                )
                self.assertGreaterEqual(insurance_count, 2)
                self.assertEqual(len(policies), insurance_count)

                heatmap = client.get(
                    f'/api/v1/customers/{customer.pk}/heatmap/',
                )
                self.assertEqual(heatmap.status_code, 200, heatmap.content)
                self.assertEqual(heatmap.json()['customer_id'], customer.pk)
                self.assertTrue(heatmap.json()['tree'])

                comparison = client.get(
                    f'/api/v1/customers/{customer.pk}/compare/',
                    {
                        'side_a_ids': str(policies[0]['id']),
                        'side_b_ids': str(policies[1]['id']),
                    },
                )
                self.assertEqual(
                    comparison.status_code,
                    200,
                    comparison.content,
                )
                comparison_body = comparison.json()
                self.assertEqual(
                    [row['id'] for row in comparison_body['current']['insurances']],
                    [policies[0]['id']],
                )
                self.assertEqual(
                    [row['id'] for row in comparison_body['proposed']['insurances']],
                    [policies[1]['id']],
                )

        schedule_count, schedule_rows = self._paginated_results(
            client,
            f"/api/v1/schedule-items/?month={timezone.localdate():%Y-%m}",
        )
        self.assertEqual(schedule_count, 30)
        self.assertEqual(len(schedule_rows), 30)

        meeting_count, meeting_rows = self._paginated_results(
            client,
            '/api/v1/meetings/',
        )
        self.assertEqual(meeting_count, 5)
        self.assertEqual(len(meeting_rows), 5)
        self.assertEqual(
            Counter(row['status'] for row in meeting_rows),
            {'pending': 2, 'confirmed': 3},
        )

        notification_count, notification_rows = self._paginated_results(
            client,
            '/api/v1/notifications/',
        )
        self.assertEqual(notification_count, 12)
        self.assertEqual(len(notification_rows), 12)

    def test_allowed_mutations_are_restored_by_the_next_seed(self):
        client = self._showcase_client()
        customer = Customer.objects.get(
            owner=self.showcase_user,
            name=self.ANCHOR_NAMES[0],
        )
        original_state = (
            customer.sales_stage,
            customer.memo,
            tuple(
                customer.tags.order_by('label').values_list(
                    'label',
                    flat=True,
                )
            ),
        )

        tag_response = client.post(
            '/api/v1/customer-tags/',
            {'label': '다음 상담'},
            format='json',
        )
        self.assertEqual(tag_response.status_code, 201, tag_response.content)
        original_tag_ids = list(
            customer.tags.values_list('pk', flat=True)
        )
        mutation = client.patch(
            f'/api/v1/customers/{customer.pk}/',
            {
                'sales_stage': Customer.STAGE_CONTRACT,
                'memo': '화면에서 변경한 내부 확인 메모',
                'tag_ids': [*original_tag_ids, tag_response.json()['id']],
            },
            format='json',
        )
        self.assertEqual(mutation.status_code, 200, mutation.content)
        self.assertEqual(mutation.json()['sales_stage'], 'contract')
        self.assertEqual(mutation.json()['memo'], '화면에서 변경한 내부 확인 메모')
        self.assertIn(
            '다음 상담',
            {tag['label'] for tag in mutation.json()['tags']},
        )

        start_at = timezone.now() + timezone.timedelta(days=2)
        schedule_response = client.post(
            '/api/v1/schedule-items/',
            {
                'kind': ScheduleItem.KIND_EVENT,
                'category': ScheduleItem.CAT_TASK,
                'title': '화면에서 추가한 확인 일정',
                'memo': '초기화 후 사라져야 하는 내부 변경',
                'customer': customer.pk,
                'start_at': start_at.isoformat(),
                'end_at': (
                    start_at + timezone.timedelta(minutes=30)
                ).isoformat(),
                'all_day': False,
            },
            format='json',
        )
        self.assertEqual(
            schedule_response.status_code,
            201,
            schedule_response.content,
        )
        self.assertEqual(
            ScheduleItem.objects.filter(owner=self.showcase_user).count(),
            31,
        )

        call_command('seed_showcase', '--apply', stdout=StringIO())

        restored_user = User.objects.get(email=_SHOWCASE_EMAIL)
        restored = Customer.objects.get(
            owner=restored_user,
            name=self.ANCHOR_NAMES[0],
        )
        restored_state = (
            restored.sales_stage,
            restored.memo,
            tuple(
                restored.tags.order_by('label').values_list(
                    'label',
                    flat=True,
                )
            ),
        )
        self.assertEqual(restored_state, original_state)
        self.assertFalse(
            CustomerTag.objects.filter(
                owner=restored_user,
                label='다음 상담',
            ).exists()
        )
        self.assertEqual(
            ScheduleItem.objects.filter(owner=restored_user).count(),
            30,
        )
        self.assertFalse(
            ScheduleItem.objects.filter(
                owner=restored_user,
                title='화면에서 추가한 확인 일정',
            ).exists()
        )

        relogin = self._authenticated_client(
            _SHOWCASE_EMAIL,
            _ARBITRARY_TEST_VALUE,
        )
        count, rows = self._paginated_results(
            relogin,
            '/api/v1/customers/',
        )
        self.assertEqual(count, 50)
        restored_row = next(
            row for row in rows if row['name'] == self.ANCHOR_NAMES[0]
        )
        restored_response = relogin.get(
            f"/api/v1/customers/{restored_row['id']}/",
        )
        self.assertEqual(
            restored_response.status_code,
            200,
            restored_response.content,
        )
        self.assertEqual(
            restored_response.json()['memo'],
            original_state[1],
        )

    def test_public_share_and_booking_payloads_disclose_only_intended_context(self):
        public = APIClient()
        snapshots = list(
            ShareSnapshot.objects.filter(
                owner=self.showcase_user,
            ).select_related('customer').order_by('pk')
        )
        self.assertEqual(len(snapshots), 2)

        forbidden_fragments = (
            _SHOWCASE_EMAIL.lower(),
            _ARBITRARY_TEST_VALUE.lower(),
            'internal',
            'showcase',
            'showcase_account',
            'showcase_seed',
            'is_showcase',
            '[demo]',
            '[촬영]',
            '데모',
            '테스트',
            '촬영용',
            'sample',
            'dummy',
        )

        booking_path = None
        booking_customer_id = None
        for snapshot in snapshots:
            response = public.get(f'/api/v1/s/{snapshot.share_token}/')
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(
                response.headers['X-Robots-Tag'],
                'noindex, nofollow',
            )
            self.assertEqual(
                response.headers['Cache-Control'],
                'private, no-store',
            )
            rendered = response.content.decode('utf-8').lower()
            for fragment in forbidden_fragments:
                self.assertNotIn(fragment, rendered)
            other_customers = (
                Customer.objects.filter(owner=self.showcase_user)
                .exclude(pk=snapshot.customer_id)
                .values_list('name', 'mobile_phone_number')
            )
            for other_name, other_phone in other_customers:
                self.assertNotIn(other_name, rendered)
                self.assertNotIn(other_phone, rendered)

            booking_url = response.json()['actions']['booking_url']
            parsed = urlparse(booking_url)
            self.assertEqual(parsed.netloc, 'app.example.invalid')
            booking_path = f"/api/v1{parsed.path.rstrip('/')}/"
            booking_customer_id = snapshot.customer_id

        booking = public.get(booking_path)
        self.assertEqual(booking.status_code, 200, booking.content)
        self.assertEqual(
            booking.headers['X-Robots-Tag'],
            'noindex, nofollow',
        )
        rendered_booking = booking.content.decode('utf-8').lower()
        for fragment in forbidden_fragments:
            self.assertNotIn(fragment, rendered_booking)
        other_customers = (
            Customer.objects.filter(owner=self.showcase_user)
            .exclude(pk=booking_customer_id)
            .values_list('name', 'mobile_phone_number')
        )
        for other_name, other_phone in other_customers:
            self.assertNotIn(other_name, rendered_booking)
            self.assertNotIn(other_phone, rendered_booking)
