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
        _make_notif(self.user, NotifType.SELF_DIAGNOSIS_LEAD)  # 고객
        _make_notif(self.user, NotifType.BIRTHDAY_SOON)        # 고객
        _make_notif(self.user, NotifType.MEETING_BOOKED)       # 일정
        _make_notif(self.user, NotifType.BOARD_COMMENT)        # 기타(받은함만)
        r = self.client.get('/api/v1/notifications/unread-count/').json()
        self.assertEqual(r['unread_count'], 4)  # 전체(받은함)
        self.assertEqual(r['customers'], 2)
        self.assertEqual(r['schedule'], 1)
        # 고객 알림 하나 읽으면 customers·전체 감소, schedule 불변.
        lead = Notification.objects.filter(
            owner=self.user, notif_type=NotifType.SELF_DIAGNOSIS_LEAD).first()
        self.client.patch(f'/api/v1/notifications/{lead.id}/read/')
        r2 = self.client.get('/api/v1/notifications/unread-count/').json()
        self.assertEqual(r2['unread_count'], 3)
        self.assertEqual(r2['customers'], 1)
        self.assertEqual(r2['schedule'], 1)


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
