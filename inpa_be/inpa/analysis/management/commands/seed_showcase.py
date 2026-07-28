"""Create, reset, or purge the configured internal showcase account."""

import calendar
import datetime

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from inpa.accounts.models import Profile
from inpa.analysis.management.commands.seed_normalization import STANDARD_TREE
from inpa.analysis.models import AnalysisDetail
from inpa.analysis.showcase_data import (
    ANCHOR_CUSTOMER_KEYS,
    CUSTOMERS,
    INSURANCES,
    validate_showcase_specs,
)
from inpa.analytics.models import NorthStarEvent
from inpa.analytics.sharing import create_share_snapshot
from inpa.analytics.views import _build_share_payload
from inpa.billing.models import Plan, Subscription
from inpa.booking.models import Meeting, WorkHour
from inpa.customers.consent_texts import consent_version_for_scope
from inpa.customers.models import ConsentLog, Customer, CustomerTag
from inpa.dashboard.models import MonthlyGoal
from inpa.insurances.import_services import _calculate_materialized_insurance
from inpa.insurances.models import (
    CustomerInsurance,
    CustomerInsuranceDetail,
    InsuranceDetail,
)
from inpa.notifications.models import Notification, NotifType
from inpa.schedule.models import ScheduleItem


User = get_user_model()

_STANDARD_MARKER = '[표준]'
_SHOWCASE_PROFILE = {
    'name': '박도윤',
    'affiliation': '한빛금융서비스',
    'title': '팀장',
}

# Synthetic coverage labels are intentionally natural, while the immutable
# analysis tree uses its historic exact names. This map is the only bridge.
_COVERAGE_TO_STANDARD = {
    '간병인입원일당': '질병입원일당',
    '간병인지원': '질병입원비',
    '갑상선암진단': '갑상선암진단비',
    '경도치매진단': '질병후유장해',
    '고액암진단': '특정암진단비',
    '골절수술': '골절수술비',
    '골절진단': '상해후유장해',
    '교통사고처리지원': '형사합의실손비',
    '교통상해입원일당': '상해입원일당',
    '교통상해후유장해': '상해후유장해',
    '급성심근경색진단': '급성심근경색진단비',
    '깁스치료': '상해수술비',
    '뇌졸중진단': '뇌졸중진단비',
    '뇌혈관수술': '질병수술비',
    '뇌혈관질환진단': '뇌혈관질환진단비',
    '방사선치료': '항암방사선치료비',
    '변호사비용': '변호사선임비',
    '비급여도수치료': '실손비급여도수치료',
    '비급여주사': '실손비급여주사',
    '상해수술': '상해수술비',
    '상해입원일당': '상해입원일당',
    '상해종수술': '상해수술비',
    '상해후유장해': '상해후유장해',
    '소아암진단': '일반암진단비',
    '스포츠상해진단': '상해후유장해',
    '심혈관수술': '질병수술비',
    '암수술': '암수술비',
    '어린이골절진단': '상해수술비',
    '어린이상해수술': '상해수술비',
    '어린이입원일당': '질병입원일당',
    '어린이질병수술': '질병수술비',
    '여성특정질환수술': '질병수술비',
    '운전자벌금': '대인벌금',
    '유방암진단': '특정암진단비',
    '유사암진단': '유사암진단비',
    '응급실내원': '질병입원비',
    '의료비입원': '실손입원급여',
    '의료비통원': '실손통원급여',
    '일반사망': '일반사망',
    '일반암진단': '일반암진단비',
    '일상생활배상': '일상생활배상책임',
    '장기요양진단': '질병후유장해',
    '중증치매진단': '고도후유장해',
    '질병수술': '질병수술비',
    '질병입원일당': '질병입원일당',
    '질병종수술': '질병수술비',
    '질병후유장해': '질병후유장해',
    '치매진단': '질병후유장해',
    '치아임플란트': '질병수술비',
    '치아크라운': '질병수술비',
    '특정감염병진단': '희귀난치성질환입원일당',
    '표적항암치료': '표적항암약물치료비',
    '항암약물치료': '항암약물치료비',
    '허혈성심장질환진단': '허혈성심장질환진단비',
    '화상수술': '화상수술비',
    '화상진단': '화상수술비',
}
_STANDARD_PATHS = {
    detail_name: (
        f'{_STANDARD_MARKER}{category_name}',
        subcategory_name,
    )
    for category_name, _insurance_type, subcategories in STANDARD_TREE
    for subcategory_name, details in subcategories
    for detail_name, _chart_based_amount in details
}


def _month_date(today, months_ago, day):
    month_start = today.replace(day=1) - relativedelta(months=months_ago)
    last_day = calendar.monthrange(month_start.year, month_start.month)[1]
    return month_start.replace(day=min(day, last_day))


def _aware(local_date, hour=12, minute=0):
    local_value = datetime.datetime.combine(
        local_date,
        datetime.time(hour=hour, minute=minute),
    )
    return timezone.make_aware(
        local_value,
        timezone.get_current_timezone(),
    )


def _future_weekdays(today, count):
    dates = []
    candidate = today + datetime.timedelta(days=1)
    while len(dates) < count:
        if candidate.weekday() < 5:
            dates.append(candidate)
        candidate += datetime.timedelta(days=1)
    return dates


class Command(BaseCommand):
    help = '설정된 내부 시연 계정을 원자적으로 생성·초기화·삭제합니다.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help='실제 변경을 승인합니다.',
        )
        parser.add_argument(
            '--purge',
            action='store_true',
            help='안전 가드를 통과한 시연 계정을 삭제합니다.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        validate_showcase_specs()
        self._validate_spec_mapping()
        if not options['apply']:
            raise CommandError(
                '변경하려면 --apply를 함께 입력해 주세요.'
            )

        email, password = self._configured_credentials()
        catalog = self._load_standard_catalog()
        plan = self._get_super_plan()
        target = (
            User.objects.select_for_update()
            .select_related('profile')
            .filter(email=email)
            .first()
        )

        if options['purge']:
            if target is None:
                raise CommandError('삭제할 시연 계정을 찾을 수 없습니다.')
            self._assert_safe_target(target, email)
            self._delete_showcase_user(target)
            self.stdout.write(self.style.SUCCESS(
                '내부 시연 계정 삭제 완료'
            ))
            return

        if target is not None:
            self._assert_safe_target(target, email)
            self._delete_showcase_user(target)

        user = self._create_account(
            email=email,
            password=password,
            plan=plan,
        )
        now = timezone.now()
        today = timezone.localdate(now)
        customers = self._create_customers(user, now, today)
        coverage_count = self._create_insurances(
            user,
            customers,
            catalog,
            now,
            today,
        )
        self._create_monthly_goals(user, today)
        self._create_schedule_items(user, customers, today)
        self._create_work_hours(user)
        self._create_meetings(user, customers, today)
        self._create_notifications(user, customers, today)
        self._create_public_shares(user, customers, now)

        representative_ids = ', '.join(
            str(customers[key].pk)
            for key in ANCHOR_CUSTOMER_KEYS[:2]
        )
        self.stdout.write(self.style.SUCCESS(
            '내부 시연 계정 생성 완료'
        ))
        self.stdout.write(
            f'고객 {len(customers)} / 증권 {len(INSURANCES)} / '
            f'담보 {coverage_count}'
        )
        self.stdout.write(f'대표 고객 ID: {representative_ids}')
        self.stdout.write(
            '공유 경로: /s/<보호된 토큰> / 예약 경로: /b/<보호된 토큰>'
        )

    @staticmethod
    def _configured_credentials():
        raw_email = getattr(settings, 'SHOWCASE_ACCOUNT_EMAIL', '')
        email = str(raw_email or '').strip()
        if not email or raw_email != email:
            raise CommandError(
                'SHOWCASE_ACCOUNT_EMAIL 설정을 확인해 주세요.'
            )
        password = getattr(settings, 'SHOWCASE_ACCOUNT_PASSWORD', '')
        if not isinstance(password, str) or not password:
            raise CommandError(
                'SHOWCASE_ACCOUNT_PASSWORD 설정을 확인해 주세요.'
            )
        return email, password

    @staticmethod
    def _validate_spec_mapping():
        coverage_names = {
            coverage.name
            for policy in INSURANCES
            for coverage in policy.coverages
        }
        mapped_names = set(_COVERAGE_TO_STANDARD)
        missing_mappings = sorted(coverage_names - mapped_names)
        stale_mappings = sorted(mapped_names - coverage_names)
        missing_paths = sorted(
            {
                standard_name
                for standard_name in _COVERAGE_TO_STANDARD.values()
                if standard_name not in _STANDARD_PATHS
            }
        )
        errors = []
        if missing_mappings:
            errors.append(
                '합성 담보 매핑 누락: ' + ', '.join(missing_mappings)
            )
        if stale_mappings:
            errors.append(
                '사용하지 않는 합성 담보 매핑: ' + ', '.join(stale_mappings)
            )
        if missing_paths:
            errors.append(
                '표준 담보 경로 누락: ' + ', '.join(missing_paths)
            )
        if errors:
            raise CommandError(' / '.join(errors))

    @staticmethod
    def _load_standard_catalog():
        required_names = sorted(set(_COVERAGE_TO_STANDARD.values()))
        analysis_rows = list(
            AnalysisDetail.objects.select_related(
                'sub_category__category',
            ).filter(
                name__in=required_names,
                sub_category__category__name__startswith=_STANDARD_MARKER,
            ).order_by('pk')
        )
        insurance_rows = list(
            InsuranceDetail.objects.select_related(
                'sub_category__category',
            ).filter(
                name__in=required_names,
                sub_category__category__name__startswith=_STANDARD_MARKER,
            ).order_by('pk')
        )
        analysis_by_path = {}
        insurance_by_path = {}
        duplicates = []
        for row in analysis_rows:
            path = (
                row.sub_category.category.name,
                row.sub_category.name,
                row.name,
            )
            if path in analysis_by_path:
                duplicates.append('/'.join(path))
            analysis_by_path[path] = row
        for row in insurance_rows:
            path = (
                row.sub_category.category.name,
                row.sub_category.name,
                row.name,
            )
            if path in insurance_by_path:
                duplicates.append('/'.join(path))
            insurance_by_path[path] = row

        missing = []
        catalog = {}
        for coverage_name, standard_name in _COVERAGE_TO_STANDARD.items():
            category_name, subcategory_name = _STANDARD_PATHS[standard_name]
            path = (category_name, subcategory_name, standard_name)
            analysis_detail = analysis_by_path.get(path)
            insurance_detail = insurance_by_path.get(path)
            if analysis_detail is None:
                missing.append('분석/' + '/'.join(path))
            if insurance_detail is None:
                missing.append('저장/' + '/'.join(path))
            if analysis_detail is not None and insurance_detail is not None:
                catalog[coverage_name] = (
                    analysis_detail,
                    insurance_detail,
                )

        if missing or duplicates:
            parts = []
            if missing:
                parts.append(
                    '필요한 표준 담보 누락: ' + ', '.join(sorted(set(missing)))
                )
            if duplicates:
                parts.append(
                    '표준 담보 중복: ' + ', '.join(sorted(set(duplicates)))
                )
            raise CommandError(' / '.join(parts))
        return catalog

    @staticmethod
    def _get_super_plan():
        try:
            return Plan.objects.get(code='super')
        except Plan.DoesNotExist as exc:
            raise CommandError(
                '활성 Super 요금제를 먼저 준비해 주세요.'
            ) from exc
        except Plan.MultipleObjectsReturned as exc:
            raise CommandError(
                'Super 요금제 구성을 확인해 주세요.'
            ) from exc

    @staticmethod
    def _assert_safe_target(user, configured_email):
        if user.email != configured_email:
            raise CommandError('설정된 시연 계정과 대상이 일치하지 않습니다.')
        profile = getattr(user, 'profile', None)
        if profile is None or not profile.is_showcase:
            raise CommandError(
                '시연 계정 표식이 없는 계정은 변경하지 않습니다.'
            )
        if user.is_staff or user.is_superuser or profile.is_admin:
            raise CommandError(
                '관리자 권한이 있는 계정은 변경하지 않습니다.'
            )

    @staticmethod
    def _delete_showcase_user(user):
        customer_ids = list(
            Customer.objects.filter(owner=user).values_list('pk', flat=True)
        )
        ConsentLog.objects.filter(customer_id__in=customer_ids).delete()
        NorthStarEvent.objects.filter(
            Q(sender=user) | Q(customer_id__in=customer_ids)
        ).delete()
        user.delete()

    @staticmethod
    def _create_account(*, email, password, plan):
        now = timezone.now()
        user = User.objects.create_user(
            email=email,
            password=password,
            is_active=True,
            is_staff=False,
            is_superuser=False,
        )
        Profile.objects.create(
            user=user,
            email_verified_at=now,
            tos_agreed_at=now,
            tos_doc_version='v1',
            pp_agreed_at=now,
            pp_doc_version='v1',
            onboarding_completed_at=now,
            tour_completed_at=now,
            is_admin=False,
            is_showcase=True,
            license_self_declared=True,
            agent_type=Profile.AGENT_BOTH,
            affiliation_type=Profile.AFFILIATION_GA,
            booking_default_duration=30,
            booking_buffer_min=60,
            booking_location='한빛금융서비스 상담실',
            **_SHOWCASE_PROFILE,
        )
        Subscription.objects.update_or_create(
            user=user,
            defaults={
                'plan': plan,
                'status': 'active',
                'expires_at': None,
                'cancelled_at': None,
                'pg_subscription_id': '',
                'auto_renew': False,
                'next_billing_at': None,
            },
        )
        return user

    @staticmethod
    def _create_customers(user, now, today):
        tag_by_label = {}
        for label in sorted({
            label
            for spec in CUSTOMERS
            for label in spec.tags
        }):
            tag_by_label[label] = CustomerTag.objects.create(
                owner=user,
                label=label,
            )

        customers = {}
        for index, spec in enumerate(CUSTOMERS, start=1):
            created_date = _month_date(
                today,
                (index - 1) % 6,
                ((index * 3) % 27) + 1,
            )
            created_at = _aware(created_date)
            fa_reached_at = None
            if spec.stage in {
                Customer.STAGE_MEETING,
                Customer.STAGE_CONTRACT,
            }:
                fa_reached_at = min(
                    now,
                    created_at + datetime.timedelta(days=2),
                )
            customer = Customer.objects.create(
                owner=user,
                name=spec.name,
                mobile_phone_number=spec.phone,
                birth_day=spec.birth_date.isoformat(),
                gender=spec.gender,
                memo=(
                    f'{spec.memo}\n'
                    f'생활 맥락: {spec.family_context}\n'
                    f'확인할 보장: {spec.coverage_focus}'
                ),
                is_agree_term=True,
                lead_source=spec.source,
                lead_created_at=created_at,
                sales_stage=spec.stage,
                status=spec.status,
                fa_reached_at=fa_reached_at,
                last_contacted_at=now - datetime.timedelta(
                    days=(index * 2) % 21,
                ),
                is_favorite=spec.key in ANCHOR_CUSTOMER_KEYS,
                is_pinned=spec.key in ANCHOR_CUSTOMER_KEYS[:2],
            )
            if spec.tags:
                customer.tags.add(*(tag_by_label[label] for label in spec.tags))
            Customer.objects.filter(pk=customer.pk).update(
                created_at=created_at,
                updated_at=created_at,
                fa_reached_at=fa_reached_at,
            )
            customer.created_at = created_at
            customer.updated_at = created_at
            customer.fa_reached_at = fa_reached_at
            customers[spec.key] = customer
        return customers

    @staticmethod
    def _create_insurances(user, customers, catalog, now, today):
        coverage_count = 0
        for index, spec in enumerate(INSURANCES, start=1):
            registered_date = _month_date(
                today,
                spec.registered_month_offset,
                ((index * 5) % 27) + 1,
            )
            registered_at = _aware(registered_date, hour=14)
            contract_date = registered_date - relativedelta(
                years=2 + (index % 5),
            )
            expiry_date = contract_date + relativedelta(years=30)
            insurance_type = (
                2
                if spec.product_type in {
                    '상해보장형',
                    '운전자보장형',
                    '의료비보장형',
                }
                else 1
            )
            insurance = CustomerInsurance.objects.create(
                customer=customers[spec.customer_key],
                insurance_type=insurance_type,
                name=f'{spec.company_name} {spec.product_type}',
                contractor_name=customers[spec.customer_key].name,
                insured_name=(
                    '자녀'
                    if spec.insured_role == 'child'
                    else customers[spec.customer_key].name
                ),
                is_same_insured=spec.insured_role == 'self',
                portfolio_type=1,
                payment_period_type=1,
                warranty_period_type=2,
                payment_period=20,
                warranty_period=30,
                contract_date=contract_date.isoformat(),
                expiry_date=expiry_date.isoformat(),
                monthly_premiums=spec.monthly_premium,
                monthly_assurance_premium=spec.monthly_premium,
                current_payment_period=max(
                    1,
                    (
                        (today.year - contract_date.year) * 12
                        + today.month
                        - contract_date.month
                        + 1
                    ),
                ),
                payment_status=1,
                next_payment_date=today + relativedelta(months=1),
                review_status='confirmed',
                confirmed_at=registered_at,
                confirmed_by=user,
                analysis_included=True,
                confirmation_source='showcase_seed',
            )
            for coverage in spec.coverages:
                analysis_detail, insurance_detail = catalog[coverage.name]
                case = CustomerInsuranceDetail.objects.create(
                    insurance=insurance,
                    detail=insurance_detail,
                    raw_name=coverage.name,
                    assurance_amount=coverage.insured_amount,
                    premium=coverage.monthly_premium,
                    renewal_period=(
                        1 if coverage.renewable else None
                    ),
                    payment_period_type=(
                        3 if coverage.renewable else 1
                    ),
                    payment_period=20,
                    warranty_period_type=2,
                    warranty_period='30',
                    mapping_source='planner_override',
                    confirmed_at=registered_at,
                )
                case.analysis_detail_override.add(analysis_detail)
                coverage_count += 1
            _calculate_materialized_insurance(insurance)
            CustomerInsurance.objects.filter(pk=insurance.pk).update(
                created_at=registered_at,
                updated_at=registered_at,
            )
        return coverage_count

    @staticmethod
    def _create_monthly_goals(user, today):
        for months_ago in range(6):
            month_date = _month_date(today, months_ago, 1)
            MonthlyGoal.objects.create(
                owner=user,
                year_month=month_date.strftime('%Y-%m'),
                target_meetings=18 + (5 - months_ago),
                target_premium=900_000 + (5 - months_ago) * 100_000,
                income_multiplier=10,
            )

    @staticmethod
    def _create_schedule_items(user, customers, today):
        customer_list = [
            customers[spec.key]
            for spec in CUSTOMERS
        ]
        month_days = calendar.monthrange(today.year, today.month)[1]
        other_days = [
            day
            for day in range(1, month_days + 1)
            if day != today.day
        ]
        categories = (
            ScheduleItem.CAT_MEETING,
            ScheduleItem.CAT_TASK,
            ScheduleItem.CAT_RENEWAL,
            ScheduleItem.CAT_ANNIVERSARY,
            ScheduleItem.CAT_ETC,
        )
        for index in range(30):
            customer = customer_list[index]
            if index < 3:
                item_date = today
            else:
                item_date = today.replace(
                    day=other_days[(index - 3) % len(other_days)],
                )
            start_at = _aware(
                item_date,
                hour=9 + (index % 8),
                minute=30 if index % 2 else 0,
            )
            kind = (
                ScheduleItem.KIND_TODO
                if index >= 24
                else ScheduleItem.KIND_EVENT
            )
            ScheduleItem.objects.create(
                owner=user,
                kind=kind,
                category=categories[index % len(categories)],
                title=(
                    f'{customer.name}님 보장 확인'
                    if kind == ScheduleItem.KIND_EVENT
                    else f'{customer.name}님 다음 연락 준비'
                ),
                customer=customer,
                start_at=start_at,
                end_at=(
                    None
                    if kind == ScheduleItem.KIND_TODO
                    else start_at + datetime.timedelta(minutes=60)
                ),
                is_done=kind == ScheduleItem.KIND_TODO and index % 2 == 0,
                done_at=(
                    start_at
                    if kind == ScheduleItem.KIND_TODO and index % 2 == 0
                    else None
                ),
            )

    @staticmethod
    def _create_work_hours(user):
        for weekday in range(5):
            WorkHour.objects.create(
                owner=user,
                weekday=weekday,
                start_time=datetime.time(9, 0),
                end_time=datetime.time(18, 0),
            )

    @staticmethod
    def _create_meetings(user, customers, today):
        statuses = (
            Meeting.STATUS_PENDING,
            Meeting.STATUS_PENDING,
            Meeting.STATUS_CONFIRMED,
            Meeting.STATUS_CONFIRMED,
            Meeting.STATUS_CONFIRMED,
        )
        methods = (
            Meeting.METHOD_IN_PERSON,
            Meeting.METHOD_PHONE,
            Meeting.METHOD_VIDEO,
            Meeting.METHOD_IN_PERSON,
            Meeting.METHOD_PHONE,
        )
        for index, meeting_date in enumerate(
            _future_weekdays(today, len(statuses))
        ):
            Meeting.objects.create(
                owner=user,
                customer=customers[ANCHOR_CUSTOMER_KEYS[index]],
                start_at=_aware(
                    meeting_date,
                    hour=10 + (index % 4) * 2,
                ),
                duration_min=30,
                method=methods[index],
                location_detail=(
                    '한빛금융서비스 상담실'
                    if methods[index] == Meeting.METHOD_IN_PERSON
                    else ''
                ),
                customer_note='상담 전에 등록된 보장 내용을 함께 확인해요.',
                status=statuses[index],
                google_event_id=None,
            )

    @staticmethod
    def _create_notifications(user, customers, today):
        notif_types = (
            NotifType.CONSULT_REMINDER,
            NotifType.TASK_DUE,
            NotifType.EXPIRY_SOON,
            NotifType.BIRTHDAY_SOON,
        )
        for index, spec in enumerate(CUSTOMERS[:12]):
            customer = customers[spec.key]
            Notification.objects.create(
                owner=user,
                notif_type=notif_types[index % len(notif_types)],
                title=f'{customer.name}님 일정 확인',
                body='오늘 할 일을 확인하고 다음 상담을 준비해 주세요.',
                target_date=today + datetime.timedelta(days=index + 1),
                customer=customer,
                is_read=index % 2 == 0,
                sent_email=False,
            )

    @staticmethod
    def _create_public_shares(user, customers, now):
        for key in ANCHOR_CUSTOMER_KEYS[:2]:
            customer = customers[key]
            for scope in (
                ConsentLog.SCOPE_PERSONAL_INFO,
                ConsentLog.SCOPE_OVERSEAS_MEDICAL,
            ):
                ConsentLog.objects.create(
                    customer=customer,
                    scope=scope,
                    subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
                    purpose='보장 내용을 정리하고 공유하기 위해 사용',
                    doc_version=consent_version_for_scope(scope),
                )
            Customer.objects.filter(pk=customer.pk).update(
                consent_overseas_at=now,
            )
            customer.consent_overseas_at = now
            create_share_snapshot(
                customer_id=customer.pk,
                owner=user,
                payload_builder=_build_share_payload,
            )
