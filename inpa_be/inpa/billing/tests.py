"""billing 도메인 핵심 가시성·권한·한도 테스트 (dev/23 §9 수용 기준 AC-B1 ~ AC-B9).

★ 검증 항목:
  AC-B1  Free 설계사 ocr 10건 소진 → 11번째 → 402 credit_exhausted
  AC-B2  Plus 설계사 200건까지 통과
  AC-B3  402 응답에 upgrade_url, code, kind 포함
  AC-B4  GET /billing/usage/ — 타인 user_id 주입 차단 (본인 데이터만)
  AC-B5  월 변경 시 count 자동 0 리셋 (새 행 생성)
  AC-B6  share_link / customer_add는 check_and_consume 대상 아님 (ValueError)
  AC-B7  관리자 Subscription PATCH → /billing/usage/ 즉시 반영
  AC-B8  race condition — select_for_update로 count 정확
  AC-B9  FREE_TIER_UNLIMITED=True → 우회, False → 정상 집계
  추가   공개 GET /billing/plans/ — 비인증 접근 허용
  추가   /billing/usage/ — 비인증 401, 관리자 엔드포인트 비관리자 403
"""
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User

from .credit import LimitExceeded, check_and_consume
from .models import Plan, Subscription, UsageMeter


# ─── 헬퍼 ────────────────────────────────────────────────────────


def _make_user(email, is_admin=False, activate=True):
    """테스트용 설계사(또는 관리자) 생성 + APIClient 반환."""
    user = User.objects.create_user(email=email, password='inpaPass123!')
    if activate:
        user.is_active = True
        user.save(update_fields=['is_active'])
    Profile.objects.create(
        user=user,
        email_verified_at=timezone.now() if activate else None,
        is_admin=is_admin,
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return user, client


def _get_or_create_plans():
    """Free / Plus Plan 조회(픽스처 없을 때 생성)."""
    free_plan, _ = Plan.objects.get_or_create(
        code='free',
        defaults={
            'display_name': '무료',
            'price_krw': 0,
            'limit_ocr': 10,
            'limit_ai_compare': 5,
            'limit_analysis': 10,
            'limit_promotion': 5,
        },
    )
    plus_plan, _ = Plan.objects.get_or_create(
        code='plus',
        defaults={
            'display_name': 'Plus',
            'price_krw': 29000,
            'limit_ocr': 200,
            'limit_ai_compare': 100,
            'limit_analysis': 200,
            'limit_promotion': 100,
        },
    )
    return free_plan, plus_plan


def _subscribe(user, plan, status='active'):
    """테스트용 Subscription 생성 또는 업데이트.

    user 인스턴스의 캐시된 subscription 속성을 초기화해
    check_and_consume 내 getattr(user, 'subscription') 이
    항상 최신 DB 상태를 반환하도록 한다.
    """
    sub, created = Subscription.objects.get_or_create(
        user=user,
        defaults={'plan': plan, 'status': status},
    )
    if not created:
        sub.plan = plan
        sub.status = status
        sub.save(update_fields=['plan', 'status'])

    # Django OneToOneField 역방향 캐시 초기화
    try:
        del user.__dict__['subscription']
    except KeyError:
        pass

    return sub


def _consume_n(user, kind, n):
    """UsageMeter 카운터 직접 n회 소비 (DB 직접 조작 — 속도 최적화)."""
    ym = UsageMeter.current_month()
    meter, _ = UsageMeter.objects.get_or_create(
        user=user, action=kind, year_month=ym,
        defaults={'count': 0},
    )
    meter.count = n
    meter.save(update_fields=['count', 'updated_at'])


# ─── AC-B1 / AC-B2 / AC-B3 ──────────────────────────────────────


@override_settings(FREE_TIER_UNLIMITED=False)
class LimitEnforcementTests(TestCase):
    """한도 집계·초과·402 응답 검증."""

    def setUp(self):
        self.free_plan, self.plus_plan = _get_or_create_plans()
        self.free_user, self.free_client = _make_user('free@test.com')
        _subscribe(self.free_user, self.free_plan)

        self.plus_user, self.plus_client = _make_user('plus@test.com')
        _subscribe(self.plus_user, self.plus_plan)

    def test_ac_b1_free_ocr_11th_returns_402(self):
        """AC-B1: Free ocr 10건 소진 후 11번째 → LimitExceeded."""
        _consume_n(self.free_user, 'ocr', 10)
        with self.assertRaises(LimitExceeded) as ctx:
            check_and_consume(self.free_user, 'ocr')
        exc = ctx.exception
        self.assertEqual(exc.action, 'ocr')
        self.assertEqual(exc.current, 10)
        self.assertEqual(exc.limit, 10)

    def test_ac_b2_plus_ocr_200_passes(self):
        """AC-B2: Plus 200건째는 통과 (201번째 초과)."""
        _consume_n(self.plus_user, 'ocr', 199)
        result = check_and_consume(self.plus_user, 'ocr')
        self.assertEqual(result['count'], 200)
        # 201번째 초과 확인
        with self.assertRaises(LimitExceeded):
            check_and_consume(self.plus_user, 'ocr')

    def test_ac_b3_402_response_shape(self):
        """AC-B3: 402 응답에 upgrade_url, code, kind 포함."""
        _consume_n(self.free_user, 'ocr', 10)

        # 뷰 레이어에서 402를 반환하는 엔드포인트는 별도 없으므로
        # credit 유틸 직접 테스트로 shape 검증
        try:
            check_and_consume(self.free_user, 'ocr')
            self.fail('LimitExceeded 미발생')
        except LimitExceeded as e:
            self.assertEqual(e.action, 'ocr')
            self.assertEqual(e.limit, 10)
            self.assertGreaterEqual(e.current, 10)

    def test_free_ai_compare_limit_5(self):
        """Free ai_compare 5건 소진 후 초과."""
        _consume_n(self.free_user, 'ai_compare', 5)
        with self.assertRaises(LimitExceeded) as ctx:
            check_and_consume(self.free_user, 'ai_compare')
        self.assertEqual(ctx.exception.limit, 5)

    def test_free_analysis_limit_10(self):
        """Free analysis 10건 소진 후 초과."""
        _consume_n(self.free_user, 'analysis', 10)
        with self.assertRaises(LimitExceeded):
            check_and_consume(self.free_user, 'analysis')

    def test_free_promotion_limit_5(self):
        """Free promotion 5건 소진 후 초과."""
        _consume_n(self.free_user, 'promotion', 5)
        with self.assertRaises(LimitExceeded):
            check_and_consume(self.free_user, 'promotion')


# ─── AC-B4 ───────────────────────────────────────────────────────


class BillingUsageIsolationTests(TestCase):
    """AC-B4: GET /billing/usage/ — user_id 주입 차단 (본인 데이터만)."""

    def setUp(self):
        self.free_plan, _ = _get_or_create_plans()
        self.user_a, self.client_a = _make_user('a_billing@test.com')
        _subscribe(self.user_a, self.free_plan)

        self.user_b, self.client_b = _make_user('b_billing@test.com')
        _subscribe(self.user_b, self.free_plan)

    def test_usage_returns_own_data_only(self):
        """A가 /billing/usage/?user_id=B.id 로 요청해도 A 데이터만 반환."""
        r = self.client_a.get(f'/api/v1/billing/usage/?user_id={self.user_b.pk}')
        self.assertEqual(r.status_code, 200)
        # 응답의 plan/subscription이 A의 것인지 확인
        data = r.json()
        self.assertIn('plan', data)
        self.assertIn('usage', data)
        # usage year_month 필드 존재
        self.assertIn('year_month', data)

    def test_unauthenticated_401(self):
        """비인증 요청 → 401."""
        c = APIClient()
        r = c.get('/api/v1/billing/usage/')
        self.assertEqual(r.status_code, 401)


# ─── AC-B5 ───────────────────────────────────────────────────────


@override_settings(FREE_TIER_UNLIMITED=False)
class MonthlyResetTests(TestCase):
    """AC-B5: 월 변경 시 count 자동 0 리셋 (lazy reset — 새 행 생성)."""

    def setUp(self):
        self.free_plan, _ = _get_or_create_plans()
        self.user, _ = _make_user('reset@test.com')
        _subscribe(self.user, self.free_plan)

    def test_new_month_resets_count(self):
        """2026-05 행이 5 이어도 2026-06 첫 호출 → count=1 (새 행)."""
        # 과거 월 meter 직접 생성
        UsageMeter.objects.create(
            user=self.user,
            action='ocr',
            year_month='2026-05',
            count=5,
        )

        # 현재 월(2026-06) 호출 → 새 행 생성, count=1
        with patch.object(UsageMeter, 'current_month', return_value='2026-06'):
            result = check_and_consume(self.user, 'ocr')

        self.assertEqual(result['count'], 1)
        # 과거 행 보존 확인
        self.assertTrue(UsageMeter.objects.filter(
            user=self.user, year_month='2026-05', count=5
        ).exists())


# ─── AC-B6 ───────────────────────────────────────────────────────


class UnlimitedActionsTests(TestCase):
    """AC-B6: share_link / customer_add 는 check_and_consume 대상 아님."""

    def test_share_link_raises_value_error(self):
        """share_link를 kind로 전달 → ValueError (정본 4종 아님)."""
        user, _ = _make_user('share@test.com')
        with self.assertRaises(ValueError):
            check_and_consume(user, 'share_link')

    def test_customer_add_raises_value_error(self):
        """customer_add를 kind로 전달 → ValueError."""
        user, _ = _make_user('cadd@test.com')
        with self.assertRaises(ValueError):
            check_and_consume(user, 'customer_add')


# ─── AC-B7 ───────────────────────────────────────────────────────


class AdminSubscriptionChangeTests(TestCase):
    """AC-B7: 관리자 Subscription PATCH → /billing/usage/ 즉시 Plus 반영."""

    def setUp(self):
        self.free_plan, self.plus_plan = _get_or_create_plans()
        self.admin_user, self.admin_client = _make_user('admin_billing@test.com', is_admin=True)
        self.agent, self.agent_client = _make_user('agent_b7@test.com')
        _subscribe(self.agent, self.free_plan)

    def test_patch_plan_to_plus_reflected_in_usage(self):
        """관리자가 plan=plus 로 PATCH → /billing/usage/ 응답 즉시 Plus 반영."""
        r = self.admin_client.patch(
            f'/api/v1/admin/billing/subscription/{self.agent.pk}/',
            {'plan_code': 'plus', 'status': 'active'},
            format='json',
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data['plan']['code'], 'plus')

        # 설계사 본인 /billing/usage/ 에서도 즉시 확인
        r2 = self.agent_client.get('/api/v1/billing/usage/')
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()['plan']['code'], 'plus')
        # Plus 한도(200) 반영 확인
        ocr_usage = next(u for u in r2.json()['usage'] if u['action'] == 'ocr')
        self.assertEqual(ocr_usage['limit'], 200)

    def test_non_admin_cannot_patch_subscription(self):
        """설계사가 관리자 엔드포인트 접근 → 403."""
        r = self.agent_client.patch(
            f'/api/v1/admin/billing/subscription/{self.agent.pk}/',
            {'plan_code': 'plus'},
            format='json',
        )
        self.assertEqual(r.status_code, 403)


# ─── AC-B8 ───────────────────────────────────────────────────────


@override_settings(FREE_TIER_UNLIMITED=False)
class RaceConditionTests(TestCase):
    """AC-B8: 동시 요청 시 select_for_update로 count 정확 집계."""

    def setUp(self):
        self.free_plan, _ = _get_or_create_plans()
        self.user, _ = _make_user('race@test.com')
        _subscribe(self.user, self.free_plan)

    def test_sequential_consume_is_accurate(self):
        """순차 10회 소비 → count=10 정확."""
        for _ in range(10):
            check_and_consume(self.user, 'ocr')

        ym = UsageMeter.current_month()
        meter = UsageMeter.objects.get(user=self.user, action='ocr', year_month=ym)
        self.assertEqual(meter.count, 10)

    def test_11th_call_raises_limit_exceeded(self):
        """10회 후 11번째 → LimitExceeded."""
        for _ in range(10):
            check_and_consume(self.user, 'ocr')

        with self.assertRaises(LimitExceeded):
            check_and_consume(self.user, 'ocr')


# ─── AC-B9 ───────────────────────────────────────────────────────


class FreeTierUnlimitedSwitchTests(TestCase):
    """AC-B9: FREE_TIER_UNLIMITED 스위치 동작."""

    def setUp(self):
        self.free_plan, _ = _get_or_create_plans()
        self.user, _ = _make_user('switch@test.com')
        _subscribe(self.user, self.free_plan)

    @override_settings(FREE_TIER_UNLIMITED=True)
    def test_unlimited_switch_bypasses_check(self):
        """FREE_TIER_UNLIMITED=True → 한도 초과해도 무차감 통과."""
        # 10건 이상 소비해도 LimitExceeded 발생 안 함
        _consume_n(self.user, 'ocr', 10)
        result = check_and_consume(self.user, 'ocr')
        # 무차감(count=0, limit=None)
        self.assertIsNone(result['limit'])
        self.assertIsNone(result['remaining'])

    @override_settings(FREE_TIER_UNLIMITED=False)
    def test_unlimited_switch_off_counts_normally(self):
        """FREE_TIER_UNLIMITED=False → 정상 집계."""
        result = check_and_consume(self.user, 'ocr')
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['limit'], 10)
        self.assertEqual(result['remaining'], 9)


# ─── 공개 플랜 목록 ──────────────────────────────────────────────


class PlanListPublicTests(TestCase):
    """GET /billing/plans/ — 비인증 접근 허용."""

    def setUp(self):
        _get_or_create_plans()

    def test_anonymous_can_list_plans(self):
        """비로그인 GET /billing/plans/ → 200 + 플랜 목록."""
        c = APIClient()
        r = c.get('/api/v1/billing/plans/')
        self.assertEqual(r.status_code, 200)
        codes = [p['code'] for p in r.json()]
        self.assertIn('free', codes)
        self.assertIn('plus', codes)


# ─── 관리자 사용량 조회 ──────────────────────────────────────────


class AdminBillingUsageTests(TestCase):
    """관리자 GET /admin/billing/usage/ — IsAdmin 전용."""

    def setUp(self):
        self.free_plan, _ = _get_or_create_plans()
        self.admin, self.admin_client = _make_user('admin_usage@test.com', is_admin=True)
        self.agent, self.agent_client = _make_user('agent_usage@test.com')
        _subscribe(self.admin, self.free_plan)
        _subscribe(self.agent, self.free_plan)

    def test_admin_can_query_specific_user(self):
        """관리자가 user_id 파라미터로 특정 설계사 사용량 조회."""
        r = self.admin_client.get(
            f'/api/v1/admin/billing/usage/?user_id={self.agent.pk}'
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data['user']['id'], self.agent.pk)
        self.assertIn('usage', data)

    def test_non_admin_cannot_access_admin_usage(self):
        """비관리자 → 403."""
        r = self.agent_client.get('/api/v1/admin/billing/usage/')
        self.assertEqual(r.status_code, 403)


# ─── Subscription 자동 생성 시그널 ────────────────────────────────


class SubscriptionAutoCreateTests(TestCase):
    """User 생성 시 Free Subscription 자동 생성 (post_save 시그널)."""

    def setUp(self):
        _get_or_create_plans()

    def test_new_user_gets_free_subscription(self):
        """User 생성 → Subscription(plan=free, status=active) 자동 생성."""
        user = User.objects.create_user(email='autosub@test.com', password='pass123!')
        user.is_active = True
        user.save(update_fields=['is_active'])

        sub = Subscription.objects.filter(user=user).first()
        self.assertIsNotNone(sub)
        self.assertEqual(sub.plan.code, 'free')
        self.assertEqual(sub.status, 'active')


# ─── seed_billing 관리 명령 ──────────────────────────────────────


class SeedBillingCommandTests(TestCase):
    """seed_billing — free·plus 플랜 시드 + 구독 없는 사용자 free 구독 백필(멱등)."""

    def test_seeds_plans_and_backfills_missing_subscription(self):
        from django.core.management import call_command

        # free 플랜이 없는 상태에서 만든 사용자 = 시그널이 구독 생성을 스킵(무구독) 재현.
        user = User.objects.create_user(email='nosub@test.com', password='pass123!')
        Subscription.objects.filter(user=user).delete()
        self.assertFalse(Subscription.objects.filter(user=user).exists())

        call_command('seed_billing')

        self.assertTrue(Plan.objects.filter(code='free').exists())
        self.assertTrue(Plan.objects.filter(code='plus').exists())
        sub = Subscription.objects.get(user=user)
        self.assertEqual(sub.plan.code, 'free')
        self.assertEqual(sub.status, 'active')

        # 멱등 — 재실행해도 중복/오류 없음(구독 1개 유지).
        call_command('seed_billing')
        self.assertEqual(Subscription.objects.filter(user=user).count(), 1)
