"""알림 도메인 핵심 가시성·권한 테스트 (dev/22 §9 수용 기준).

★ 필수 검증:
  1) 소유자 격리 — 설계사 A가 B의 알림에 접근 불가 (OwnedQuerySetMixin 강제)
  2) 읽음 처리 단일 / 일괄 정상 작동
  3) ReminderRule bulk PATCH 저장 확인
  4) unread-count 배지 숫자 정확성
  5) 인증/이메일인증 게이트
  6) 중복 Notification UniqueConstraint 동작
  7) Notification 생성 API 없음 (FE 직접 생성 차단)
"""
from datetime import date

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User
from inpa.customers.models import Customer

from .models import Notification, NotifType, ReminderRule, create_reminder_rules_for_user


# ─── 헬퍼 ─────────────────────────────────────────────────────────

def _make_planner(email):
    """이메일 인증 완료 설계사 + APIClient 반환."""
    user = User.objects.create_user(email=email, password='inpaPass123!')
    user.is_active = True
    user.save(update_fields=['is_active'])
    Profile.objects.create(user=user, email_verified_at=timezone.now())
    client = APIClient()
    client.force_authenticate(user=user)
    return user, client


def _make_notif(owner, notif_type=NotifType.EXPIRY_SOON, **kwargs):
    """테스트용 알림 생성."""
    return Notification.objects.create(
        owner=owner,
        notif_type=notif_type,
        title='테스트 알림',
        body='테스트 본문',
        **kwargs,
    )


# ─── 1. 소유자 격리 ────────────────────────────────────────────────

class OwnerIsolationTests(TestCase):
    """★ 멀티테넌시 격리 — 설계사 A는 B의 알림에 절대 접근 불가."""

    def setUp(self):
        self.user_a, self.client_a = _make_planner('a@test.com')
        self.user_b, self.client_b = _make_planner('b@test.com')
        self.notif_b = _make_notif(self.user_b)

    def test_a_cannot_list_b_notification(self):
        """A 목록에 B의 알림이 노출되지 않는다."""
        r = self.client_a.get('/api/v1/notifications/')
        self.assertEqual(r.status_code, 200)
        ids = [n['id'] for n in r.json()['results']]
        self.assertNotIn(self.notif_b.id, ids)

    def test_a_cannot_retrieve_b_notification(self):
        """A가 B의 알림 상세 조회 → 404 (존재 자체 숨김)."""
        r = self.client_a.get(f'/api/v1/notifications/{self.notif_b.id}/')
        self.assertEqual(r.status_code, 404)

    def test_a_cannot_read_b_notification(self):
        """A가 B의 알림 읽음 처리 → 404."""
        r = self.client_a.patch(f'/api/v1/notifications/{self.notif_b.id}/read/')
        self.assertEqual(r.status_code, 404)
        self.notif_b.refresh_from_db()
        self.assertFalse(self.notif_b.is_read)

    def test_a_cannot_delete_b_notification(self):
        """A가 B의 알림 삭제 → 404, 실제 삭제 안 됨."""
        r = self.client_a.delete(f'/api/v1/notifications/{self.notif_b.id}/')
        self.assertEqual(r.status_code, 404)
        self.assertTrue(Notification.objects.filter(id=self.notif_b.id).exists())

    def test_a_unread_count_excludes_b(self):
        """unread-count는 본인 미읽음만 집계."""
        _make_notif(self.user_b)  # B에게 추가 알림 (미읽음)
        r = self.client_a.get('/api/v1/notifications/unread-count/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['unread_count'], 0)  # A는 알림 없음

    def test_read_all_only_marks_own(self):
        """read-all은 본인 알림만 읽음 처리. B의 알림은 영향 없음."""
        notif_a = _make_notif(self.user_a)
        self.client_a.post('/api/v1/notifications/read-all/')
        self.notif_b.refresh_from_db()
        notif_a.refresh_from_db()
        self.assertTrue(notif_a.is_read)
        self.assertFalse(self.notif_b.is_read)

    def test_admin_read_all_does_not_mark_other_users(self):
        """★ 관리자여도 read-all은 본인 알림만 읽음 처리 — OwnedQuerySetMixin의 관리자
        전체조회 우회로 전 사용자 알림을 교차 테넌시로 쓰던 버그 회귀 방지."""
        admin = User.objects.create_user(email='admin@test.com', password='inpaPass123!')
        admin.is_active = True
        admin.save(update_fields=['is_active'])
        Profile.objects.create(user=admin, is_admin=True, email_verified_at=timezone.now())
        admin_client = APIClient()
        admin_client.force_authenticate(user=admin)

        own = _make_notif(admin)
        r = admin_client.post('/api/v1/notifications/read-all/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['updated'], 1)  # 관리자 본인 1건만
        own.refresh_from_db()
        self.notif_b.refresh_from_db()
        self.assertTrue(own.is_read)
        self.assertFalse(self.notif_b.is_read)  # 다른 사용자 알림은 그대로

    def test_admin_unread_count_only_counts_own(self):
        """★ 관리자 unread-count도 본인 것만 집계(전 사용자 합산 금지)."""
        admin = User.objects.create_user(email='admin2@test.com', password='inpaPass123!')
        admin.is_active = True
        admin.save(update_fields=['is_active'])
        Profile.objects.create(user=admin, is_admin=True, email_verified_at=timezone.now())
        admin_client = APIClient()
        admin_client.force_authenticate(user=admin)
        _make_notif(admin)  # 본인 1건
        r = admin_client.get('/api/v1/notifications/unread-count/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['unread_count'], 1)  # B의 알림은 제외


# ─── 2. 읽음 처리 ─────────────────────────────────────────────────

class ReadMarkTests(TestCase):
    """읽음 처리 단일/일괄 정상 작동."""

    def setUp(self):
        self.user, self.client = _make_planner('planner@test.com')

    def test_mark_read_single(self):
        """단일 PATCH /read/ → is_read=True 전환."""
        notif = _make_notif(self.user)
        self.assertFalse(notif.is_read)
        r = self.client.patch(f'/api/v1/notifications/{notif.id}/read/')
        self.assertEqual(r.status_code, 200)
        notif.refresh_from_db()
        self.assertTrue(notif.is_read)

    def test_mark_read_idempotent(self):
        """이미 읽음 상태에 다시 read/ 호출 → 200 유지, DB 변화 없음."""
        notif = _make_notif(self.user, is_read=True)
        r = self.client.patch(f'/api/v1/notifications/{notif.id}/read/')
        self.assertEqual(r.status_code, 200)

    def test_read_all(self):
        """POST /read-all/ → 모든 미읽음 알림 읽음 처리."""
        for _ in range(3):
            _make_notif(self.user)
        r = self.client.post('/api/v1/notifications/read-all/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['updated'], 3)
        self.assertEqual(
            Notification.objects.filter(owner=self.user, is_read=False).count(), 0
        )

    def test_unread_count_decrements(self):
        """읽음 처리 후 unread-count 감소."""
        for _ in range(3):
            _make_notif(self.user)
        r1 = self.client.get('/api/v1/notifications/unread-count/')
        self.assertEqual(r1.json()['unread_count'], 3)

        # 1개 읽음
        first = Notification.objects.filter(owner=self.user).first()
        self.client.patch(f'/api/v1/notifications/{first.id}/read/')

        r2 = self.client.get('/api/v1/notifications/unread-count/')
        self.assertEqual(r2.json()['unread_count'], 2)


# ─── 2-b. unread-count 카테고리 배지(네비 고객/일정) ─────────────────

class UnreadCategoryTests(TestCase):
    """unread-count의 customers/schedule = 전체 미읽음의 부분집합 + 읽으면 소거('알림처럼')."""

    def setUp(self):
        self.user, self.client = _make_planner('catbadge@test.com')

    def test_breakdown_subsets_and_clear(self):
        _make_notif(self.user, NotifType.SELF_DIAGNOSIS_LEAD)          # 고객
        _make_notif(self.user, NotifType.BIRTHDAY_SOON)               # 고객
        _make_notif(self.user, NotifType.MEETING_BOOKED)              # 일정
        _make_notif(self.user, NotifType.BOARD_COMMENT)               # 게시판
        _make_notif(self.user, NotifType.PROMOTION_DIGITAL_READY)     # 판촉물
        _make_notif(self.user, NotifType.PROMOTION_DIGITAL_REQUESTED)  # 관리자
        r = self.client.get('/api/v1/notifications/unread-count/').json()
        self.assertEqual(r['unread_count'], 6)  # 전체(받은함)
        self.assertEqual(r['customers'], 2)
        self.assertEqual(r['schedule'], 1)
        self.assertEqual(r['board'], 1)
        self.assertEqual(r['promotion'], 1)
        self.assertEqual(r['admin'], 1)
        # 파티션 검증 — 각 카테고리 합 = 전체.
        self.assertEqual(r['customers'] + r['schedule'] + r['board'] + r['promotion'] + r['admin'],
                         r['unread_count'])
        # 고객 알림 하나 읽으면 customers·전체 감소, 나머지 불변.
        lead = Notification.objects.filter(
            owner=self.user, notif_type=NotifType.SELF_DIAGNOSIS_LEAD).first()
        self.client.patch(f'/api/v1/notifications/{lead.id}/read/')
        r2 = self.client.get('/api/v1/notifications/unread-count/').json()
        self.assertEqual(r2['unread_count'], 5)
        self.assertEqual(r2['customers'], 1)
        self.assertEqual(r2['board'], 1)
        self.assertEqual(r2['promotion'], 1)
        self.assertEqual(r2['admin'], 1)


# ─── 3. 삭제 ─────────────────────────────────────────────────────

class DeleteTests(TestCase):
    """단일 삭제 — 실제 삭제(soft delete 아님)."""

    def setUp(self):
        self.user, self.client = _make_planner('planner2@test.com')

    def test_delete_notification(self):
        notif = _make_notif(self.user)
        r = self.client.delete(f'/api/v1/notifications/{notif.id}/')
        self.assertEqual(r.status_code, 204)
        self.assertFalse(Notification.objects.filter(id=notif.id).exists())


# ─── 4. ReminderRule ──────────────────────────────────────────────

class ReminderRuleTests(TestCase):
    """ReminderRule CRUD — 소유자 전용."""

    def setUp(self):
        self.user_a, self.client_a = _make_planner('ra@test.com')
        self.user_b, self.client_b = _make_planner('rb@test.com')
        create_reminder_rules_for_user(self.user_a)
        create_reminder_rules_for_user(self.user_b)

    def test_list_returns_own_rules(self):
        """GET /reminder-rules/ → 본인 5종만 반환."""
        r = self.client_a.get('/api/v1/reminder-rules/')
        self.assertEqual(r.status_code, 200)
        rule_types = [x['rule_type'] for x in r.json()]
        self.assertIn('expiry_soon', rule_types)
        self.assertEqual(len(rule_types), 5)

    def test_a_cannot_see_b_rules(self):
        """A의 목록에 B의 rule이 섞이지 않는다."""
        r = self.client_a.get('/api/v1/reminder-rules/')
        owner_ids_in_db = set(
            ReminderRule.objects.filter(
                id__in=[x['id'] for x in r.json()]
            ).values_list('owner_id', flat=True)
        )
        self.assertEqual(owner_ids_in_db, {self.user_a.id})

    def test_bulk_update(self):
        """PATCH /reminder-rules/bulk/ → 변경 저장 후 전체 5종 반환."""
        r = self.client_a.patch(
            '/api/v1/reminder-rules/bulk/',
            [
                {'rule_type': 'expiry_soon', 'days_before': 14, 'email_enabled': True},
                {'rule_type': 'birthday_soon', 'days_before': 3},
            ],
            format='json',
        )
        self.assertEqual(r.status_code, 200)
        result = {x['rule_type']: x for x in r.json()}
        self.assertEqual(result['expiry_soon']['days_before'], 14)
        self.assertTrue(result['expiry_soon']['email_enabled'])
        self.assertEqual(result['birthday_soon']['days_before'], 3)
        # 전체 5종 반환 확인
        self.assertEqual(len(r.json()), 5)

    def test_bulk_update_invalid_days_before(self):
        """days_before 범위 초과(>90) → 400."""
        r = self.client_a.patch(
            '/api/v1/reminder-rules/bulk/',
            [{'rule_type': 'expiry_soon', 'days_before': 91}],
            format='json',
        )
        self.assertEqual(r.status_code, 400)

    def test_bulk_update_invalid_format(self):
        """배열이 아닌 형태 전송 → 400."""
        r = self.client_a.patch(
            '/api/v1/reminder-rules/bulk/',
            {'rule_type': 'expiry_soon', 'days_before': 5},
            format='json',
        )
        self.assertEqual(r.status_code, 400)

    def test_create_reminder_rules_idempotent(self):
        """create_reminder_rules_for_user 중복 호출 → 5종 초과 생성 안 됨."""
        create_reminder_rules_for_user(self.user_a)
        create_reminder_rules_for_user(self.user_a)
        count = ReminderRule.objects.filter(owner=self.user_a).count()
        self.assertEqual(count, 5)


# ─── 5. 인증 게이트 ────────────────────────────────────────────────

class AuthGateTests(TestCase):
    """인증·이메일인증 게이트."""

    def test_unauthenticated_blocked(self):
        c = APIClient()
        self.assertEqual(c.get('/api/v1/notifications/').status_code, 401)
        self.assertEqual(c.get('/api/v1/reminder-rules/').status_code, 401)

    def test_unverified_email_blocked(self):
        """이메일 미인증(is_active=False) → 403."""
        user = User.objects.create_user(email='unv@test.com', password='inpaPass123!')
        Profile.objects.create(user=user)
        c = APIClient()
        c.force_authenticate(user=user)
        self.assertEqual(c.get('/api/v1/notifications/').status_code, 403)
        self.assertEqual(c.get('/api/v1/reminder-rules/').status_code, 403)


# ─── 6. FE 직접 생성 차단 ────────────────────────────────────────

class NotificationCreateBlockTests(TestCase):
    """Notification은 BE 내부 전용 — FE API에서 직접 생성 불가."""

    def setUp(self):
        self.user, self.client = _make_planner('noc@test.com')

    def test_post_notification_not_allowed(self):
        """POST /notifications/ → 405 (라우트 없음)."""
        r = self.client.post(
            '/api/v1/notifications/',
            {
                'notif_type': 'expiry_soon',
                'title': '임의 생성 시도',
                'body': '본문',
            },
            format='json',
        )
        self.assertEqual(r.status_code, 405)


# ─── 7. is_read 필터 ──────────────────────────────────────────────

class IsReadFilterTests(TestCase):
    """?is_read=true/false 쿼리파라미터 필터."""

    def setUp(self):
        self.user, self.client = _make_planner('flt@test.com')
        _make_notif(self.user, is_read=False)
        _make_notif(self.user, is_read=True)

    def test_filter_unread(self):
        r = self.client.get('/api/v1/notifications/?is_read=false')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(all(not n['is_read'] for n in r.json()['results']))

    def test_filter_read(self):
        r = self.client.get('/api/v1/notifications/?is_read=true')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(all(n['is_read'] for n in r.json()['results']))


# ─── 8. UniqueConstraint (중복 방지) ──────────────────────────────

class UniquenessTests(TestCase):
    """동일 (owner, notif_type, target_date, customer_id) 중복 방지 (dev/22 §3.2)."""

    def setUp(self):
        self.user, _ = _make_planner('dup@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='김중복', mobile_phone_number='010-0000-9999'
        )

    def test_duplicate_notif_rejected(self):
        """동일 (owner, notif_type, target_date, customer) 2번 생성 → DB 에러."""
        from django.db import IntegrityError
        kwargs = dict(
            owner=self.user,
            notif_type=NotifType.EXPIRY_SOON,
            title='만기 알림',
            body='본문',
            target_date=date(2026, 8, 1),
            customer=self.customer,
        )
        Notification.objects.create(**kwargs)
        with self.assertRaises(IntegrityError):
            Notification.objects.create(**kwargs)


# ─── 9. 일일 배치(run_daily_jobs) — 생산자·멱등·엔드포인트·하트비트 ──
# spec 2026-07-04 §Tests: 엔드포인트 인증 / 생산자별 정확성·룰 OFF / 멱등 / KST / 하트비트.

from datetime import datetime, time, timedelta  # noqa: E402

from django.test import override_settings  # noqa: E402
from django.utils import timezone as tz  # noqa: E402

from inpa.analysis.models import SeedMarker  # noqa: E402
from inpa.booking.models import Meeting  # noqa: E402
from inpa.insurances.models import CustomerInsurance  # noqa: E402
from inpa.schedule.models import ScheduleItem  # noqa: E402

from .jobs import HEARTBEAT_KEY, run_daily_jobs  # noqa: E402
from .jobs import (  # noqa: E402
    produce_birthday_soon, produce_consult_reminder, produce_expiry_soon,
    produce_share_unread, produce_task_due,
)


def _kst_dt(day, hour, minute=0):
    """KST 벽시계 → aware datetime (TIME_ZONE=Asia/Seoul)."""
    return tz.make_aware(datetime.combine(day, time(hour, minute)))


class DailyJobsEndpointTests(TestCase):
    """POST /api/v1/jobs/run-daily/ — X-JOB-TOKEN 인증 (fail-closed)."""

    URL = '/api/v1/jobs/run-daily/'

    @override_settings(JOB_RUNNER_TOKEN='')
    def test_env_unset_returns_404(self):
        r = APIClient().post(self.URL, HTTP_X_JOB_TOKEN='anything')
        self.assertEqual(r.status_code, 404)

    @override_settings(JOB_RUNNER_TOKEN='sekrit-token')
    def test_wrong_token_returns_403(self):
        r = APIClient().post(self.URL, HTTP_X_JOB_TOKEN='wrong')
        self.assertEqual(r.status_code, 403)

    @override_settings(JOB_RUNNER_TOKEN='sekrit-token')
    def test_missing_token_returns_403(self):
        r = APIClient().post(self.URL)
        self.assertEqual(r.status_code, 403)

    @override_settings(JOB_RUNNER_TOKEN='sekrit-token')
    def test_correct_token_returns_counts(self):
        r = APIClient().post(self.URL, HTTP_X_JOB_TOKEN='sekrit-token')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn('counts', body)
        self.assertIn('birthday_soon', body['counts'])
        self.assertEqual(body['errors'], {})
        # 성공 실행 → 하트비트 마커 기록
        marker = SeedMarker.objects.get(key=HEARTBEAT_KEY)
        self.assertEqual(marker.version, tz.localdate().isoformat())


class DailyJobProducerTests(TestCase):
    """생산자 5종 — 정확한 알림 생성 + ReminderRule OFF 존중 + KST 날짜 산정."""

    def setUp(self):
        self.user, _ = _make_planner('jobs@test.com')
        create_reminder_rules_for_user(self.user)
        self.today = tz.localdate()

    def _rule(self, rule_type):
        return ReminderRule.objects.get(owner=self.user, rule_type=rule_type)

    # ── birthday_soon ──────────────────────────────────────────

    def _birthday_customer(self, offset_days, name='김생일', status='active'):
        bd = self.today + timedelta(days=offset_days)
        # 1992 = 윤년(2/29 안전). 생일 CharField 'YYYY-MM-DD'.
        return Customer.objects.create(
            owner=self.user, name=name, status=status,
            birth_day=f'1992-{bd.month:02d}-{bd.day:02d}')

    def test_birthday_soon_created(self):
        c = self._birthday_customer(3)
        self.assertEqual(produce_birthday_soon(self.today), 1)
        n = Notification.objects.get(notif_type=NotifType.BIRTHDAY_SOON)
        self.assertEqual(n.owner, self.user)
        self.assertEqual(n.customer, c)
        self.assertIn('김생일', n.body)
        self.assertEqual(n.target_date, self.today + timedelta(days=3))

    def test_birthday_outside_lead_not_created(self):
        self._birthday_customer(10)  # 기본 리드 7일 밖
        self.assertEqual(produce_birthday_soon(self.today), 0)

    def test_birthday_rule_off_produces_nothing(self):
        self._birthday_customer(3)
        rule = self._rule(NotifType.BIRTHDAY_SOON)
        rule.enabled = False
        rule.save(update_fields=['enabled'])
        self.assertEqual(produce_birthday_soon(self.today), 0)

    def test_birthday_inactive_customer_skipped(self):
        self._birthday_customer(3, status='closed')
        self.assertEqual(produce_birthday_soon(self.today), 0)

    # ── expiry_soon ────────────────────────────────────────────

    def _expiring_insurance(self, offset_days, name='건강보험'):
        customer = Customer.objects.create(owner=self.user, name='김만기')
        exp = self.today + timedelta(days=offset_days)
        return CustomerInsurance.objects.create(
            customer=customer, portfolio_type=1, name=name,
            expiry_date=exp.strftime('%Y.%m.%d'))

    def test_expiry_soon_created(self):
        ci = self._expiring_insurance(20)  # 기본 리드 30일 내
        self.assertEqual(produce_expiry_soon(self.today), 1)
        n = Notification.objects.get(notif_type=NotifType.EXPIRY_SOON)
        self.assertEqual(n.owner, self.user)
        self.assertEqual(n.customer, ci.customer)
        self.assertIn('김만기', n.body)
        self.assertIn('건강보험', n.body)

    def test_expiry_outside_lead_not_created(self):
        self._expiring_insurance(60)
        self.assertEqual(produce_expiry_soon(self.today), 0)

    def test_expiry_rule_off_produces_nothing(self):
        self._expiring_insurance(20)
        rule = self._rule(NotifType.EXPIRY_SOON)
        rule.enabled = False
        rule.save(update_fields=['enabled'])
        self.assertEqual(produce_expiry_soon(self.today), 0)

    # ── consult_reminder ───────────────────────────────────────

    def test_consult_reminder_for_tomorrow_meeting(self):
        customer = Customer.objects.create(owner=self.user, name='김상담')
        Meeting.objects.create(
            owner=self.user, customer=customer,
            start_at=_kst_dt(self.today + timedelta(days=1), 14),
            method=Meeting.METHOD_PHONE, status=Meeting.STATUS_CONFIRMED)
        self.assertEqual(produce_consult_reminder(self.today), 1)
        n = Notification.objects.get(notif_type=NotifType.CONSULT_REMINDER)
        self.assertIn('김상담', n.body)
        self.assertIn('14:00', n.body)
        self.assertEqual(n.target_date, self.today + timedelta(days=1))

    def test_consult_reminder_pending_meeting_skipped(self):
        customer = Customer.objects.create(owner=self.user, name='김대기')
        Meeting.objects.create(
            owner=self.user, customer=customer,
            start_at=_kst_dt(self.today + timedelta(days=1), 14),
            method=Meeting.METHOD_PHONE, status=Meeting.STATUS_PENDING)
        self.assertEqual(produce_consult_reminder(self.today), 0)

    def test_consult_reminder_for_meeting_schedule_item(self):
        ScheduleItem.objects.create(
            owner=self.user, kind=ScheduleItem.KIND_EVENT,
            category=ScheduleItem.CAT_MEETING, title='보장 점검 미팅',
            start_at=_kst_dt(self.today + timedelta(days=1), 10))
        self.assertEqual(produce_consult_reminder(self.today), 1)
        n = Notification.objects.get(notif_type=NotifType.CONSULT_REMINDER)
        self.assertIn('보장 점검 미팅', n.body)
        self.assertEqual(n.calendar_event_id, ScheduleItem.objects.get().id)

    def test_consult_reminder_rule_off(self):
        customer = Customer.objects.create(owner=self.user, name='김끔')
        Meeting.objects.create(
            owner=self.user, customer=customer,
            start_at=_kst_dt(self.today + timedelta(days=1), 14),
            method=Meeting.METHOD_PHONE, status=Meeting.STATUS_CONFIRMED)
        rule = self._rule(NotifType.CONSULT_REMINDER)
        rule.enabled = False
        rule.save(update_fields=['enabled'])
        self.assertEqual(produce_consult_reminder(self.today), 0)

    # ── task_due ───────────────────────────────────────────────

    def test_task_due_today_created(self):
        customer = Customer.objects.create(owner=self.user, name='김할일')
        ScheduleItem.objects.create(
            owner=self.user, kind=ScheduleItem.KIND_TODO, customer=customer,
            title='서류 전달', start_at=_kst_dt(self.today, 12))  # 시각 없는 todo = KST 정오 규약
        self.assertEqual(produce_task_due(self.today), 1)
        n = Notification.objects.get(notif_type=NotifType.TASK_DUE)
        self.assertIn('서류 전달', n.body)
        self.assertIn('김할일', n.body)
        self.assertEqual(n.target_date, self.today)

    def test_task_due_lead_window_respects_days_before(self):
        # 기본 days_before=1: 내일 마감은 D-1 미리 알림, 리드 밖(5일 뒤)은 미발화
        ScheduleItem.objects.create(
            owner=self.user, kind=ScheduleItem.KIND_TODO, title='내일 마감 일',
            start_at=_kst_dt(self.today + timedelta(days=1), 12))
        ScheduleItem.objects.create(
            owner=self.user, kind=ScheduleItem.KIND_TODO, title='다음주 일',
            start_at=_kst_dt(self.today + timedelta(days=5), 12))
        self.assertEqual(produce_task_due(self.today), 1)
        n = Notification.objects.get(notif_type=NotifType.TASK_DUE)
        self.assertIn('내일 마감 일', n.body)
        self.assertIn('D-1', n.body)
        self.assertEqual(n.target_date, self.today + timedelta(days=1))
        # 마감 당일 재실행: 같은 할 일은 target_date=마감일 dedupe 로 중복 생성 없음
        self.assertEqual(produce_task_due(self.today + timedelta(days=1)), 0)
        self.assertEqual(
            Notification.objects.filter(notif_type=NotifType.TASK_DUE).count(), 1)

    def test_task_due_done_skipped(self):
        ScheduleItem.objects.create(
            owner=self.user, kind=ScheduleItem.KIND_TODO, title='끝난 일',
            start_at=_kst_dt(self.today, 12), is_done=True)
        self.assertEqual(produce_task_due(self.today), 0)

    def test_task_due_rule_off(self):
        ScheduleItem.objects.create(
            owner=self.user, kind=ScheduleItem.KIND_TODO, title='오늘 일',
            start_at=_kst_dt(self.today, 12))
        rule = self._rule(NotifType.TASK_DUE)
        rule.enabled = False
        rule.save(update_fields=['enabled'])
        self.assertEqual(produce_task_due(self.today), 0)

    # ── share_unread ───────────────────────────────────────────

    def test_share_unread_created_after_24h(self):
        Customer.objects.create(
            owner=self.user, name='김공유',
            share_sent_at=tz.now() - timedelta(days=2))
        self.assertEqual(produce_share_unread(self.today), 1)
        n = Notification.objects.get(notif_type=NotifType.SHARE_UNREAD)
        self.assertIn('김공유', n.body)

    def test_share_unread_recent_send_skipped(self):
        Customer.objects.create(
            owner=self.user, name='김최근',
            share_sent_at=tz.now() - timedelta(hours=2))  # 24h 미경과
        self.assertEqual(produce_share_unread(self.today), 0)

    def test_share_unread_viewed_skipped(self):
        Customer.objects.create(
            owner=self.user, name='김열람',
            share_sent_at=tz.now() - timedelta(days=2),
            user_view_at=tz.now() - timedelta(days=1))
        self.assertEqual(produce_share_unread(self.today), 0)

    def test_share_unread_rule_off(self):
        Customer.objects.create(
            owner=self.user, name='김끔공유',
            share_sent_at=tz.now() - timedelta(days=2))
        rule = self._rule(NotifType.SHARE_UNREAD)
        rule.enabled = False
        rule.save(update_fields=['enabled'])
        self.assertEqual(produce_share_unread(self.today), 0)

    # ── 소유자 격리 ─────────────────────────────────────────────

    def test_producer_owner_scoped(self):
        """B 설계사 고객의 생일 알림은 B에게만 — A에게 절대 누출 금지."""
        user_b, _ = _make_planner('jobs-b@test.com')
        bd = self.today + timedelta(days=2)
        Customer.objects.create(
            owner=user_b, name='김비고객',
            birth_day=f'1992-{bd.month:02d}-{bd.day:02d}')
        produce_birthday_soon(self.today)
        self.assertFalse(Notification.objects.filter(owner=self.user).exists())
        self.assertTrue(Notification.objects.filter(owner=user_b).exists())


class DailyJobsIdempotencyTests(TestCase):
    """같은 KST 날 재실행 → 신규 0건, 중복 행 없음 + 하트비트."""

    def setUp(self):
        self.user, _ = _make_planner('idem@test.com')
        create_reminder_rules_for_user(self.user)
        today = tz.localdate()
        bd = today + timedelta(days=3)
        Customer.objects.create(
            owner=self.user, name='김생일',
            birth_day=f'1992-{bd.month:02d}-{bd.day:02d}')
        cust = Customer.objects.create(owner=self.user, name='김만기')
        CustomerInsurance.objects.create(
            customer=cust, portfolio_type=1, name='암보험',
            expiry_date=(today + timedelta(days=10)).strftime('%Y.%m.%d'))
        Meeting.objects.create(
            owner=self.user, customer=cust,
            start_at=_kst_dt(today + timedelta(days=1), 15),
            method=Meeting.METHOD_IN_PERSON, status=Meeting.STATUS_CONFIRMED)
        ScheduleItem.objects.create(
            owner=self.user, kind=ScheduleItem.KIND_TODO, title='오늘 마감 일',
            start_at=_kst_dt(today, 12))
        Customer.objects.create(
            owner=self.user, name='김공유',
            share_sent_at=tz.now() - timedelta(days=2))

    def test_second_run_creates_nothing(self):
        first = run_daily_jobs()
        self.assertEqual(first['total_created'], 5)
        self.assertEqual(first['errors'], {})
        count_after_first = Notification.objects.count()

        second = run_daily_jobs()
        self.assertEqual(second['total_created'], 0)
        self.assertEqual(Notification.objects.count(), count_after_first)

    def test_heartbeat_written_on_success(self):
        run_daily_jobs()
        marker = SeedMarker.objects.get(key=HEARTBEAT_KEY)
        self.assertEqual(marker.version, tz.localdate().isoformat())


# ─── 10. 인바운드 리드 보유기간 자동 파기 (spec 2026-07-04 Part1 §5) ──

from inpa.customers.models import ConsentLog, ContactLog  # noqa: E402

from .jobs import cleanup_expired_leads  # noqa: E402


class LeadRetentionTests(TestCase):
    """LEAD_RETENTION_DAYS(기본 180) 초과·미전환 인바운드 리드만 파기. 직접 등록은 절대 보존."""

    def setUp(self):
        self.user, _ = _make_planner('retention@test.com')
        self.today = tz.localdate()

    def _lead(self, age_days, source=Customer.LEAD_SELF_DIAGNOSIS, **kwargs):
        """실제 인바운드 리드 시뮬레이션 — /d·/p 유입 경로처럼 lead_created_at 기록."""
        cust = Customer.objects.create(owner=self.user, name='김리드',
                                       lead_source=source, **kwargs)
        Customer.objects.filter(pk=cust.pk).update(
            created_at=tz.now() - timedelta(days=age_days),
            lead_created_at=tz.now() - timedelta(days=age_days))
        return cust

    def test_expired_inbound_lead_deleted_with_summary_notification(self):
        """181일 무활동 셀프진단 리드 → 삭제 + 설계사 요약 알림 1건 + 동의로그 잔존."""
        cust = self._lead(181)
        log = ConsentLog.objects.create(customer=cust,
                                        scope=ConsentLog.SCOPE_PERSONAL_INFO,
                                        subject=ConsentLog.SUBJECT_CUSTOMER_SELF)
        # 동의도 유입 당시(181일 전) 기록 — 신선 동의는 활동으로 간주돼 보존됨
        ConsentLog.objects.filter(pk=log.pk).update(
            agreed_at=tz.now() - timedelta(days=181))
        deleted = cleanup_expired_leads(self.today)
        self.assertEqual(deleted, 1)
        self.assertFalse(Customer.objects.filter(pk=cust.pk).exists())
        # 동의 감사 로그는 SET_NULL로 잔존
        log = ConsentLog.objects.get(scope=ConsentLog.SCOPE_PERSONAL_INFO)
        self.assertIsNone(log.customer_id)
        notifs = Notification.objects.filter(owner=self.user,
                                             title='잠재고객 정보 자동 정리')
        self.assertEqual(notifs.count(), 1)
        self.assertIn('1명', notifs.first().body)

    def test_boundary_179_days_kept(self):
        """179일 리드는 보존(경계 하한)."""
        cust = self._lead(179)
        self.assertEqual(cleanup_expired_leads(self.today), 0)
        self.assertTrue(Customer.objects.filter(pk=cust.pk).exists())
        self.assertEqual(Notification.objects.count(), 0)

    def test_conversion_traces_protect_lead(self):
        """전환 흔적(보험/접촉기록/미팅/단계 이동/최근 연락)이 있으면 보존."""
        with_ins = self._lead(200)
        CustomerInsurance.objects.create(customer=with_ins, portfolio_type=1, name='보험')
        with_contact = self._lead(200)
        ContactLog.objects.create(owner=self.user, customer=with_contact,
                                  result=ContactLog.RESULT_CONNECTED)
        with_meeting = self._lead(200)
        Meeting.objects.create(owner=self.user, customer=with_meeting,
                               start_at=tz.now(), method=Meeting.METHOD_PHONE,
                               status=Meeting.STATUS_PENDING)
        staged = self._lead(200)
        Customer.objects.filter(pk=staged.pk).update(sales_stage=Customer.STAGE_CONTACT)
        recent_touch = self._lead(200)
        Customer.objects.filter(pk=recent_touch.pk).update(
            last_contacted_at=tz.now() - timedelta(days=10))
        self.assertEqual(cleanup_expired_leads(self.today), 0)
        self.assertEqual(Customer.objects.count(), 5)

    def test_direct_registered_customer_never_deleted(self):
        """설계사 직접 등록(lead_source direct/null) 고객은 아무리 오래돼도 대상 아님."""
        direct = self._lead(400, source=Customer.LEAD_DIRECT)
        no_source = Customer.objects.create(owner=self.user, name='김직접')
        Customer.objects.filter(pk=no_source.pk).update(
            created_at=tz.now() - timedelta(days=400))
        self.assertEqual(cleanup_expired_leads(self.today), 0)
        self.assertTrue(Customer.objects.filter(pk=direct.pk).exists())
        self.assertTrue(Customer.objects.filter(pk=no_source.pk).exists())

    def test_manual_customer_with_introduction_source_never_deleted(self):
        """수기 등록 + 유입경로 '소개'(introduction) 선택 고객은 절대 대상 아님.

        lead_source='introduction'은 등록 모달·일괄 등록에서 설계사가 직접 고를 수
        있는 유입경로 → source 만으로 거르면 오삭제(2026-07-04 리뷰 blocker).
        판별자 = lead_created_at(인바운드 유입 경로만 기록, 수기/일괄은 null).
        """
        manual = Customer.objects.create(owner=self.user, name='김소개',
                                         lead_source=Customer.LEAD_INTRODUCTION)
        Customer.objects.filter(pk=manual.pk).update(
            created_at=tz.now() - timedelta(days=400))  # lead_created_at=None 유지
        self.assertEqual(cleanup_expired_leads(self.today), 0)
        self.assertTrue(Customer.objects.filter(pk=manual.pk).exists())
        self.assertEqual(Notification.objects.count(), 0)

    def test_fresh_consent_protects_old_lead(self):
        """200일 된 인바운드 리드가 오늘 재신청(새 ConsentLog) → 보존.

        /d·/p 재신청은 전화번호 dedupe로 기존 고객을 재사용하며 새 ConsentLog 만
        남김 → 신선한 동의 = 활동(새 동의 직후 파기 역설 방지, 2026-07-04 리뷰 major).
        """
        cust = self._lead(200, source=Customer.LEAD_INTRODUCTION)
        ConsentLog.objects.create(customer=cust,
                                  scope=ConsentLog.SCOPE_PERSONAL_INFO,
                                  subject=ConsentLog.SUBJECT_CUSTOMER_SELF)
        self.assertEqual(cleanup_expired_leads(self.today), 0)
        self.assertTrue(Customer.objects.filter(pk=cust.pk).exists())
        self.assertEqual(Notification.objects.count(), 0)

    def test_idempotent_rerun_no_duplicate_notification(self):
        """같은 날 재실행 — 2회차 삭제 0·알림 중복 0."""
        self._lead(181, source=Customer.LEAD_INTRODUCTION)
        self.assertEqual(cleanup_expired_leads(self.today), 1)
        self.assertEqual(cleanup_expired_leads(self.today), 0)
        self.assertEqual(
            Notification.objects.filter(title='잠재고객 정보 자동 정리').count(), 1)

    @override_settings(LEAD_RETENTION_DAYS=0)
    def test_zero_or_unset_days_skips(self):
        """LEAD_RETENTION_DAYS ≤ 0 → 파기 스킵(안전 스위치)."""
        cust = self._lead(400)
        self.assertEqual(cleanup_expired_leads(self.today), 0)
        self.assertTrue(Customer.objects.filter(pk=cust.pk).exists())

    def test_run_daily_jobs_includes_cleanup_step(self):
        """daily runner에 정리 단계 탑재 — counts에 삭제 수, 알림 생산 합계와 분리."""
        self._lead(181)
        result = run_daily_jobs()
        self.assertEqual(result['counts']['lead_retention_deleted'], 1)
        self.assertEqual(result['errors'], {})


# ─── 공유(/s) 스냅샷 보유기간 자동 파기 (spec 2026-07-08, 프리런치 #27) ──

from inpa.analytics.models import ShareSnapshot  # noqa: E402

from .jobs import cleanup_expired_share_snapshots  # noqa: E402


class ShareSnapshotRetentionTests(TestCase):
    """SHARE_SNAPSHOT_RETENTION_DAYS(기본 180) 경과 스냅샷만 파기. 미만은 보존."""

    def setUp(self):
        self.user, _ = _make_planner('snap-retention@test.com')
        self.customer = Customer.objects.create(owner=self.user, name='김공유기록')

    def _snapshot(self, retention_days_from_now):
        return ShareSnapshot.objects.create(
            owner=self.user, customer=self.customer,
            payload={'tree': [], 'summary': {}, 'disclaimer': 'x',
                     'customer': {'name_masked': '김**'}, 'mode': 'neutral'},
            retention_expires_at=tz.now() + timedelta(days=retention_days_from_now))

    def test_expired_snapshot_deleted(self):
        expired = self._snapshot(-1)  # 이미 어제 만료
        kept = self._snapshot(10)     # 아직 10일 남음
        deleted = cleanup_expired_share_snapshots(tz.now())
        self.assertEqual(deleted, 1)
        self.assertFalse(ShareSnapshot.objects.filter(pk=expired.pk).exists())
        self.assertTrue(ShareSnapshot.objects.filter(pk=kept.pk).exists())

    def test_idempotent_rerun_no_error(self):
        self._snapshot(-1)
        self.assertEqual(cleanup_expired_share_snapshots(tz.now()), 1)
        self.assertEqual(cleanup_expired_share_snapshots(tz.now()), 0)

    @override_settings(SHARE_SNAPSHOT_RETENTION_DAYS=0)
    def test_zero_days_pauses_purge(self):
        """안전 스위치: 0 이하면 이미 만료된 스냅샷도 파기하지 않는다(소송 보전 등)."""
        expired = self._snapshot(-5)
        self.assertEqual(cleanup_expired_share_snapshots(tz.now()), 0)
        self.assertTrue(ShareSnapshot.objects.filter(pk=expired.pk).exists())

    def test_run_daily_jobs_includes_share_snapshot_cleanup_step(self):
        """daily runner에 정리 단계 탑재 — 하트비트 유지, 중복 삭제 없음(멱등)."""
        self._snapshot(-1)
        result = run_daily_jobs()
        self.assertEqual(result['counts']['share_snapshot_retention_deleted'], 1)
        self.assertEqual(result['errors'], {})
        marker = SeedMarker.objects.get(key=HEARTBEAT_KEY)
        self.assertEqual(marker.version, tz.localdate().isoformat())
        # 재실행 — 이미 삭제됐으니 0, 에러 없이 하트비트 그대로.
        second = run_daily_jobs()
        self.assertEqual(second['counts']['share_snapshot_retention_deleted'], 0)
        self.assertEqual(second['errors'], {})


# ─── 인증 멈춤 데드맨 알람 (spec 2026-07-08, 프리런치 #16) ────────────────

from .jobs import check_signup_verification_flatline  # noqa: E402


class SignupVerificationFlatlineTests(TestCase):
    """가입≥임계(기본 3)+인증 0건 → 관리자 알림. 인증>0 또는 가입<임계 → 무알림. 하루 1회 멱등."""

    def setUp(self):
        self.today = tz.localdate()
        # 관리자 계정은 '오늘 새 가입/오늘 인증'이 아니게 어제자로 백데이팅(집계 오염 방지) —
        # 관리자 본인의 email_verified_at까지 오늘 창에 잡히면 '오늘 인증 0건' 시나리오가 깨진다.
        admin_user = User.objects.create_user(email='admin-flatline@test.com', password='inpaPass123!')
        admin_user.is_active = True
        admin_user.save(update_fields=['is_active'])
        yesterday = tz.now() - timedelta(days=1)
        Profile.objects.create(user=admin_user, is_admin=True, email_verified_at=yesterday)
        User.objects.filter(pk=admin_user.pk).update(date_joined=yesterday)
        self.admin = admin_user

    def _signup(self, email, verified=False):
        user = User.objects.create_user(email=email, password='inpaPass123!')
        Profile.objects.create(
            user=user, email_verified_at=tz.now() if verified else None)
        return user

    def test_triggers_when_signups_over_threshold_and_zero_verifications(self):
        for i in range(3):
            self._signup(f'flat{i}@test.com')
        created = check_signup_verification_flatline(self.today)
        self.assertEqual(created, 1)
        notif = Notification.objects.get(owner=self.admin, notif_type=NotifType.SIGNUP_VERIFY_FLATLINE)
        self.assertIn('3', notif.body)
        self.assertNotIn('—', notif.body)

    def test_no_trigger_when_a_verification_happened(self):
        self._signup('v0@test.com', verified=True)
        self._signup('v1@test.com')
        self._signup('v2@test.com')
        created = check_signup_verification_flatline(self.today)
        self.assertEqual(created, 0)
        self.assertFalse(
            Notification.objects.filter(notif_type=NotifType.SIGNUP_VERIFY_FLATLINE).exists())

    def test_no_trigger_when_below_min_signups(self):
        self._signup('below0@test.com')
        self._signup('below1@test.com')  # 기본 임계 3 미만
        created = check_signup_verification_flatline(self.today)
        self.assertEqual(created, 0)

    def test_idempotent_rerun_same_day(self):
        for i in range(3):
            self._signup(f'idem{i}@test.com')
        first = check_signup_verification_flatline(self.today)
        self.assertEqual(first, 1)
        second = check_signup_verification_flatline(self.today)
        self.assertEqual(second, 0)
        self.assertEqual(
            Notification.objects.filter(notif_type=NotifType.SIGNUP_VERIFY_FLATLINE).count(), 1)

    def test_fans_out_to_every_admin_once(self):
        """관리자 여러 명이면 각자 1건씩(중복 없이) 받는다."""
        admin2 = User.objects.create_user(email='admin2-flat@test.com', password='inpaPass123!')
        yesterday = tz.now() - timedelta(days=1)
        Profile.objects.create(user=admin2, is_admin=True, email_verified_at=yesterday)
        User.objects.filter(pk=admin2.pk).update(date_joined=yesterday)
        for i in range(3):
            self._signup(f'fan{i}@test.com')
        created = check_signup_verification_flatline(self.today)
        self.assertEqual(created, 2)  # admin + admin2 각 1건
        for a in (self.admin, admin2):
            self.assertEqual(Notification.objects.filter(
                owner=a, notif_type=NotifType.SIGNUP_VERIFY_FLATLINE).count(), 1)

    def test_demo_accounts_excluded_from_counts(self):
        """@inpa.local 데모 계정은 가입·인증 집계에서 제외(실장애 중 seed_demo가 알람 억제 방지)."""
        for i in range(3):
            self._signup(f'realflat{i}@test.com')
        # 데모 인증 계정을 오늘 만들어도 '오늘 인증 0건'이 유지되어 알람이 떠야 함.
        self._signup('demo-verified@inpa.local', verified=True)
        created = check_signup_verification_flatline(self.today)
        self.assertEqual(created, 1)

    def test_run_daily_jobs_includes_check_step_and_heartbeat_intact(self):
        for i in range(3):
            self._signup(f'runner{i}@test.com')
        result = run_daily_jobs()
        self.assertEqual(result['counts']['signup_verify_flatline'], 1)
        self.assertEqual(result['errors'], {})
        marker = SeedMarker.objects.get(key=HEARTBEAT_KEY)
        self.assertEqual(marker.version, tz.localdate().isoformat())

    def test_detects_signups_from_previous_afternoon_rolling_window(self):
        """★ 롤링 창(지금-lookback일 ~ 지금) — 08:00 실행 시 전날 오후 가입도 포착.
        달력-오늘만 보던 창은 전날 오후 가입을 놓쳐 인증 장애를 늦게 잡던 버그 회귀 방지."""
        # 전날 오후(약 17시간 전)로 가입 시각 백데이팅 — 달력상 '오늘'이 아니지만
        # 롤링 창(지금-1일) 안에는 들어온다.
        prev_afternoon = tz.now() - timedelta(hours=17)
        for i in range(3):
            u = self._signup(f'prevpm{i}@test.com')
            User.objects.filter(pk=u.pk).update(date_joined=prev_afternoon)
        created = check_signup_verification_flatline(self.today)
        self.assertEqual(created, 1)
        self.assertTrue(Notification.objects.filter(
            owner=self.admin, notif_type=NotifType.SIGNUP_VERIFY_FLATLINE).exists())


# ─── 문의/피드백 알림 유형 버킷 매핑 (support) ────────────────────────

from .models import ADMIN_NOTIF_TYPES, BOARD_NOTIF_TYPES  # noqa: E402


class InquiryNotifTypeBucketTests(TestCase):
    """1:1 문의 알림 2종이 올바른 네비 카테고리 버킷에 들어간다."""

    def test_inquiry_answered_in_board_bucket(self):
        self.assertIn(NotifType.INQUIRY_ANSWERED.value, BOARD_NOTIF_TYPES)

    def test_inquiry_received_in_admin_bucket(self):
        self.assertIn(NotifType.INQUIRY_RECEIVED.value, ADMIN_NOTIF_TYPES)
