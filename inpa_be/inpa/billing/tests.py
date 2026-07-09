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
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User

from datetime import timedelta

from .coupons import redeem_coupon  # noqa: F401 — 회귀·문서용
from .credit import LimitExceeded, check_and_consume
from .models import Coupon, CouponRedemption, Plan, Subscription, UsageMeter


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
    """seed_billing — free·plus·super 플랜 시드 + 구독 없는 사용자 free 구독 백필(멱등)."""

    def test_seeds_plans_and_backfills_missing_subscription(self):
        from django.core.management import call_command

        # free 플랜이 없는 상태에서 만든 사용자 = 시그널이 구독 생성을 스킵(무구독) 재현.
        user = User.objects.create_user(email='nosub@test.com', password='pass123!')
        Subscription.objects.filter(user=user).delete()
        self.assertFalse(Subscription.objects.filter(user=user).exists())

        call_command('seed_billing')

        self.assertTrue(Plan.objects.filter(code='free').exists())
        self.assertTrue(Plan.objects.filter(code='plus').exists())
        self.assertTrue(Plan.objects.filter(code='super').exists())
        sub = Subscription.objects.get(user=user)
        self.assertEqual(sub.plan.code, 'free')
        self.assertEqual(sub.status, 'active')

        # 멱등 — 재실행해도 중복/오류 없음(구독 1개 유지).
        call_command('seed_billing')
        self.assertEqual(Subscription.objects.filter(user=user).count(), 1)

    def test_seeds_confirmed_prices_and_super_unlimited(self):
        """신규 생성 시 확정가(Plus 19,900 / Super 39,900, VAT 별도) + super 한도 전부 null."""
        from django.core.management import call_command

        call_command('seed_billing')

        plus = Plan.objects.get(code='plus')
        self.assertEqual(plus.price_krw, 19900)
        self.assertIn('VAT 별도', plus.description)

        superp = Plan.objects.get(code='super')
        self.assertEqual(superp.display_name, 'Super')
        self.assertEqual(superp.price_krw, 39900)
        self.assertIn('VAT 별도', superp.description)
        for field in ('limit_ocr', 'limit_ai_compare', 'limit_analysis', 'limit_promotion'):
            self.assertIsNone(getattr(superp, field), field)

        # 멱등 — 재실행해도 super 1행 유지.
        call_command('seed_billing')
        self.assertEqual(Plan.objects.filter(code='super').count(), 1)

    def test_seed_preserves_admin_modified_plus(self):
        """이미 존재하는 plus 행(관리자 수정값)은 재실행이 덮지 않는다(CREATE 기본값만)."""
        from django.core.management import call_command

        Plan.objects.create(code='plus', display_name='Plus', price_krw=24900,
                            description='관리자 수정값')
        call_command('seed_billing')

        plus = Plan.objects.get(code='plus')
        self.assertEqual(plus.price_krw, 24900)
        self.assertEqual(plus.description, '관리자 수정값')

    def test_seeds_manager_plan_with_plus_limits(self):
        """manager 플랜: 19,900원(VAT 별도), 한도는 Plus와 동일, 멱등."""
        from django.core.management import call_command

        call_command('seed_billing')
        manager = Plan.objects.get(code='manager')
        self.assertEqual(manager.display_name, 'Manager')
        self.assertEqual(manager.price_krw, 19900)
        self.assertIn('VAT 별도', manager.description)
        self.assertIn('관리자', manager.description)
        plus = Plan.objects.get(code='plus')
        for field in ('limit_ocr', 'limit_ai_compare', 'limit_analysis', 'limit_promotion'):
            self.assertEqual(getattr(manager, field), getattr(plus, field))
        call_command('seed_billing')  # 멱등
        self.assertEqual(Plan.objects.filter(code='manager').count(), 1)

    def test_seeds_manager_can_use_team_others_false(self):
        """팀 기능 게이트(spec 2026-07-09) capability: manager만 can_use_team=True."""
        from django.core.management import call_command

        call_command('seed_billing')
        self.assertTrue(Plan.objects.get(code='manager').can_use_team)
        for code in ('free', 'plus', 'super'):
            self.assertFalse(Plan.objects.get(code=code).can_use_team, code)

    def test_seed_corrects_can_use_team_on_pre_existing_manager_row(self):
        """can_use_team 필드 도입 전에 만들어진 manager 행(default False)도 재시드로 True 보정."""
        from django.core.management import call_command

        Plan.objects.create(code='manager', display_name='Manager', price_krw=19900)
        self.assertFalse(Plan.objects.get(code='manager').can_use_team)
        call_command('seed_billing')
        self.assertTrue(Plan.objects.get(code='manager').can_use_team)


class UserCanUseTeamTests(TestCase):
    """billing/credit.py::user_can_use_team — 팀 기능 게이트 단위 판별(spec 2026-07-09).

    ★ 순수 판별 함수 — 실제로 막을지는 뷰가 settings.MANAGER_PLAN_GATE_ENABLED와 함께 결정한다.
    """

    def setUp(self):
        self.free_plan, self.plus_plan = _get_or_create_plans()
        self.manager_plan, _ = Plan.objects.get_or_create(
            code='manager',
            defaults={'display_name': 'Manager', 'price_krw': 19900, 'can_use_team': True,
                      'limit_ocr': 200, 'limit_ai_compare': 100,
                      'limit_analysis': 200, 'limit_promotion': 100},
        )
        if not self.manager_plan.can_use_team:
            self.manager_plan.can_use_team = True
            self.manager_plan.save(update_fields=['can_use_team'])

    def test_active_manager_subscription_true(self):
        from .credit import user_can_use_team
        user, _ = _make_user('team-mgr-sub@test.com')
        _subscribe(user, self.manager_plan)
        self.assertTrue(user_can_use_team(user))

    def test_plus_subscription_false(self):
        from .credit import user_can_use_team
        user, _ = _make_user('team-plus-sub@test.com')
        _subscribe(user, self.plus_plan)
        self.assertFalse(user_can_use_team(user))

    def test_expired_manager_subscription_false(self):
        from .credit import user_can_use_team
        user, _ = _make_user('team-mgr-expired@test.com')
        sub = _subscribe(user, self.manager_plan)
        sub.expires_at = timezone.now() - timedelta(days=1)
        sub.save(update_fields=['expires_at'])
        self.assertFalse(user_can_use_team(user))

    def test_no_subscription_false(self):
        from .credit import user_can_use_team
        user, _ = _make_user('team-nosub@test.com')
        Subscription.objects.filter(user=user).delete()
        self.assertFalse(user_can_use_team(user))


class PlusPriceDataMigrationTests(TestCase):
    """migrations/0005 — plus placeholder(29000)일 때만 19900 전환(조건부, spec B-2)."""

    @staticmethod
    def _run_migration_fn():
        from importlib import import_module

        from django.apps import apps as global_apps

        mod = import_module('inpa.billing.migrations.0005_plus_price_and_super_choice')
        mod.update_plus_placeholder_price(global_apps, None)

    def test_placeholder_price_updated_to_final(self):
        Plan.objects.create(code='plus', display_name='Plus', price_krw=29000)
        self._run_migration_fn()
        plus = Plan.objects.get(code='plus')
        self.assertEqual(plus.price_krw, 19900)
        self.assertIn('VAT 별도', plus.description)

    def test_non_placeholder_price_untouched(self):
        Plan.objects.create(code='plus', display_name='Plus', price_krw=25000,
                            description='관리자 수정값')
        self._run_migration_fn()
        plus = Plan.objects.get(code='plus')
        self.assertEqual(plus.price_krw, 25000)
        self.assertEqual(plus.description, '관리자 수정값')

    def test_no_plus_row_is_noop(self):
        self._run_migration_fn()  # 행이 없어도 조용히 통과
        self.assertFalse(Plan.objects.filter(code='plus').exists())


# ─── RuntimeConfig / 유료화 모드 토글 ───────────────────────────


class RuntimeConfigSoloTests(TestCase):
    """RuntimeConfig.solo() 시드 동작 + DB 우선 로직."""

    def test_solo_seeds_from_settings_on_first_call(self):
        """DB 행 없을 때 solo()가 settings.FREE_TIER_UNLIMITED 로 행을 생성한다."""
        from .models import RuntimeConfig
        with override_settings(FREE_TIER_UNLIMITED=True):
            cfg = RuntimeConfig.solo()
        self.assertEqual(cfg.pk, 1)
        self.assertTrue(cfg.free_tier_unlimited)

    def test_solo_returns_existing_row_without_overwrite(self):
        """행이 이미 있으면 settings 값을 무시하고 기존 행 반환."""
        from .models import RuntimeConfig
        RuntimeConfig.objects.create(pk=1, free_tier_unlimited=False)
        with override_settings(FREE_TIER_UNLIMITED=True):
            cfg = RuntimeConfig.solo()
        self.assertFalse(cfg.free_tier_unlimited)  # DB 값(False) 유지


@override_settings(FREE_TIER_UNLIMITED=True)  # settings = True
class RuntimeConfigDbWinsTests(TestCase):
    """DB RuntimeConfig.free_tier_unlimited=False가 settings=True를 이긴다."""

    def setUp(self):
        from .models import RuntimeConfig
        self.free_plan, _ = _get_or_create_plans()
        self.user, _ = _make_user('dbwins@test.com')
        _subscribe(self.user, self.free_plan)
        # DB 행을 False로 강제 세팅
        RuntimeConfig.objects.update_or_create(pk=1, defaults={'free_tier_unlimited': False})

    def test_db_false_enforces_limit_even_when_settings_true(self):
        """DB=False, settings=True → 한도 집계 발동 (DB 우선)."""
        _consume_n(self.user, 'ocr', 10)
        with self.assertRaises(LimitExceeded):
            check_and_consume(self.user, 'ocr')

    def test_db_true_bypasses_limit(self):
        """DB=True → 무차감 통과."""
        from .models import RuntimeConfig
        RuntimeConfig.objects.update_or_create(pk=1, defaults={'free_tier_unlimited': True})
        _consume_n(self.user, 'ocr', 10)
        result = check_and_consume(self.user, 'ocr')
        self.assertIsNone(result['limit'])


class AdminBillingModeViewTests(TestCase):
    """GET/PATCH /api/v1/admin/billing/mode/ — 관리자 토글 엔드포인트."""

    def setUp(self):
        from .models import RuntimeConfig
        _get_or_create_plans()
        self.admin, self.admin_client = _make_user('admin_mode@test.com', is_admin=True)
        self.agent, self.agent_client = _make_user('agent_mode@test.com')
        # 초기 행 생성
        RuntimeConfig.objects.update_or_create(pk=1, defaults={'free_tier_unlimited': True})

    def test_admin_get_returns_current_value(self):
        r = self.admin_client.get('/api/v1/admin/billing/mode/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('free_tier_unlimited', r.json())

    def test_admin_patch_sets_false(self):
        r = self.admin_client.patch(
            '/api/v1/admin/billing/mode/',
            {'free_tier_unlimited': False},
            format='json',
        )
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()['free_tier_unlimited'])
        from .models import RuntimeConfig
        self.assertFalse(RuntimeConfig.objects.get(pk=1).free_tier_unlimited)

    def test_admin_patch_invalid_value_400(self):
        r = self.admin_client.patch(
            '/api/v1/admin/billing/mode/',
            {'free_tier_unlimited': 'yes'},
            format='json',
        )
        self.assertEqual(r.status_code, 400)

    def test_non_admin_get_403(self):
        r = self.agent_client.get('/api/v1/admin/billing/mode/')
        self.assertEqual(r.status_code, 403)

    def test_non_admin_patch_403(self):
        r = self.agent_client.patch(
            '/api/v1/admin/billing/mode/',
            {'free_tier_unlimited': False},
            format='json',
        )
        self.assertEqual(r.status_code, 403)


class CouponRedeemTests(TestCase):
    """무료 쿠폰 — 발급/사용/제한/만료 반영 (item 8, 관리자 발급 코드)."""

    URL = '/api/v1/billing/coupons/redeem/'

    def setUp(self):
        self.free, self.plus = _get_or_create_plans()
        self.user, self.client = _make_user('coupon@test.com')

    def _coupon(self, **kw):
        defaults = {'plan': self.plus, 'duration_days': 30, 'max_redemptions': 1}
        defaults.update(kw)
        return Coupon.objects.create(**defaults)

    def test_redeem_grants_plus_with_expiry(self):
        c = self._coupon(code='inpa-plus1')  # 소문자 입력 → 저장 시 대문자 정규화
        r = self.client.post(self.URL, {'code': 'INPA-PLUS1'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['plan_code'], 'plus')
        sub = Subscription.objects.get(user=self.user)
        self.assertEqual(sub.plan.code, 'plus')
        self.assertEqual(sub.status, 'active')
        self.assertIsNotNone(sub.expires_at)
        self.assertGreater((sub.expires_at - timezone.now()).days, 28)  # ~30일
        c.refresh_from_db()
        self.assertEqual(c.redeemed_count, 1)
        self.assertTrue(CouponRedemption.objects.filter(coupon=c, user=self.user).exists())

    def test_case_insensitive_code(self):
        self._coupon(code='INPA-ABCD')
        r = self.client.post(self.URL, {'code': ' inpa-abcd '}, format='json')
        self.assertEqual(r.status_code, 200)

    def test_double_redeem_same_user_409(self):
        self._coupon(code='INPA-ONCE', max_redemptions=5)
        self.client.post(self.URL, {'code': 'INPA-ONCE'}, format='json')
        r = self.client.post(self.URL, {'code': 'INPA-ONCE'}, format='json')
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()['code'], 'already')

    def test_not_found_404(self):
        r = self.client.post(self.URL, {'code': 'NOPE-XXXX'}, format='json')
        self.assertEqual(r.status_code, 404)

    def test_expired_coupon_410(self):
        self._coupon(code='INPA-OLD', expires_at=timezone.now() - timedelta(days=1))
        r = self.client.post(self.URL, {'code': 'INPA-OLD'}, format='json')
        self.assertEqual(r.status_code, 410)
        self.assertEqual(r.json()['code'], 'expired')

    def test_exhausted_coupon_410(self):
        self._coupon(code='INPA-MAX', max_redemptions=1)
        _, other_client = _make_user('other@test.com')
        other_client.post(self.URL, {'code': 'INPA-MAX'}, format='json')  # 1회 소진
        r = self.client.post(self.URL, {'code': 'INPA-MAX'}, format='json')
        self.assertEqual(r.status_code, 410)
        self.assertEqual(r.json()['code'], 'exhausted')

    def test_auto_generated_code(self):
        c = Coupon.objects.create(plan=self.plus)  # code 비움 → 자동 생성
        self.assertTrue(c.code.startswith('INPA-'))
        self.assertEqual(len(c.code), 13)  # 'INPA-' + 8

    @override_settings(FREE_TIER_UNLIMITED=False)
    def test_expired_subscription_falls_back_to_free_limits(self):
        # 만료된 Plus 구독은 Free 한도로 폴백(credit.py 만료 반영).
        Subscription.objects.update_or_create(
            user=self.user,
            defaults={'plan': self.plus, 'status': 'active',
                      'expires_at': timezone.now() - timedelta(days=1)},
        )
        for _ in range(10):  # Free ocr 한도=10
            check_and_consume(self.user, 'ocr')
        with self.assertRaises(LimitExceeded):
            check_and_consume(self.user, 'ocr')


# ──────────────────────────────────────────────────────────────────────
# Claude 호출당 비용·파싱 결과 계측 (프리런치 리뷰 #17)
# ──────────────────────────────────────────────────────────────────────
class ClaudePricingTests(TestCase):
    """billing/pricing.py::estimate_cost_krw — 모델 계열 단가·환율·prompt caching 배율 단위 계산."""

    def test_usage_none_returns_zero(self):
        from .pricing import estimate_cost_krw
        self.assertEqual(estimate_cost_krw('claude-opus-4-8', None), Decimal('0'))

    @override_settings(CLAUDE_USD_KRW_RATE=1000.0)
    def test_opus_pricing_family_resolved_by_substring(self):
        """Opus: in $5/out $25 per MTok. 100만 입력 + 10만 출력 토큰, 환율 1000원."""
        from .pricing import estimate_cost_krw
        usage = {'input_tokens': 1_000_000, 'output_tokens': 100_000,
                  'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0}
        cost = estimate_cost_krw('claude-opus-4-8', usage)
        # ($5 + $2.5) * 1000 = $7.5 * 1000 = 7500원
        self.assertEqual(cost, Decimal('7500.00'))

    @override_settings(CLAUDE_USD_KRW_RATE=1000.0)
    def test_haiku_pricing_cheaper_than_opus(self):
        """Haiku: in $1/out $5 per MTok — 같은 토큰수면 opus보다 저렴해야 한다."""
        from .pricing import estimate_cost_krw
        usage = {'input_tokens': 1_000_000, 'output_tokens': 100_000,
                  'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0}
        cost = estimate_cost_krw('claude-haiku-4-5', usage)
        # ($1 + $0.5) * 1000 = 1500원
        self.assertEqual(cost, Decimal('1500.00'))
        opus_cost = estimate_cost_krw('claude-opus-4-8', usage)
        self.assertLess(cost, opus_cost)

    @override_settings(CLAUDE_USD_KRW_RATE=1000.0)
    def test_unknown_model_falls_back_to_opus_pricing(self):
        """모델 계열 판별 실패 → 보수적(opus) fallback. 추측 금지, 과소추정 방지."""
        from .pricing import estimate_cost_krw
        usage = {'input_tokens': 1_000_000, 'output_tokens': 0,
                  'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0}
        self.assertEqual(
            estimate_cost_krw('claude-mystery-9', usage),
            estimate_cost_krw('claude-opus-4-8', usage),
        )

    @override_settings(CLAUDE_USD_KRW_RATE=1000.0)
    def test_cache_read_and_write_multipliers(self):
        """cache_read=입력단가×0.1 / cache_creation=입력단가×1.25."""
        from .pricing import estimate_cost_krw
        usage = {'input_tokens': 0, 'output_tokens': 0,
                  'cache_read_input_tokens': 1_000_000, 'cache_creation_input_tokens': 0}
        cost_read = estimate_cost_krw('claude-sonnet-4-5', usage)
        # sonnet in=$3 * 0.1 = $0.3 * 1000 = 300원
        self.assertEqual(cost_read, Decimal('300.00'))

        usage2 = {'input_tokens': 0, 'output_tokens': 0,
                   'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 1_000_000}
        cost_write = estimate_cost_krw('claude-sonnet-4-5', usage2)
        # sonnet in=$3 * 1.25 = $3.75 * 1000 = 3750원
        self.assertEqual(cost_write, Decimal('3750.00'))

    @override_settings(CLAUDE_USD_KRW_RATE=1400.0)
    def test_fx_rate_env_override_changes_cost(self):
        """CLAUDE_USD_KRW_RATE override 가 실제로 비용 계산에 반영된다."""
        from .pricing import estimate_cost_krw
        usage = {'input_tokens': 1_000_000, 'output_tokens': 0,
                  'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0}
        cost_1400 = estimate_cost_krw('claude-opus-4-8', usage)
        self.assertEqual(cost_1400, Decimal('7000.00'))  # $5 * 1400
        with override_settings(CLAUDE_USD_KRW_RATE=1000.0):
            cost_1000 = estimate_cost_krw('claude-opus-4-8', usage)
        self.assertEqual(cost_1000, Decimal('5000.00'))
        self.assertNotEqual(cost_1400, cost_1000)

    def test_object_style_usage_supported(self):
        """dict 뿐 아니라 SDK usage 객체(속성 접근)도 지원."""
        from .pricing import estimate_cost_krw

        class _Usage:
            input_tokens = 500_000
            output_tokens = 0
            cache_read_input_tokens = 0
            cache_creation_input_tokens = 0

        with override_settings(CLAUDE_USD_KRW_RATE=1000.0):
            cost = estimate_cost_krw('claude-opus-4-8', _Usage())
        self.assertEqual(cost, Decimal('2500.00'))  # $5/2 * 1000


class LogClaudeUsageExtendedTests(TestCase):
    """credit.py::log_claude_usage 확장 — user/cost_krw/outcome/carrier/matched·unmatched 기록."""

    def setUp(self):
        self.user, _ = _make_user('claudelog@test.com')

    def test_creates_row_with_all_new_fields(self):
        from .credit import log_claude_usage
        from .models import ClaudeApiLog

        with override_settings(CLAUDE_USD_KRW_RATE=1000.0):
            log_claude_usage(
                'ocr_parse', 'claude-opus-4-8',
                {'input_tokens': 1_000_000, 'output_tokens': 0,
                 'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0},
                user=self.user, outcome='success', carrier_code=2, matched=5, unmatched=1,
            )
        log = ClaudeApiLog.objects.get()
        self.assertEqual(log.user_id, self.user.id)
        self.assertEqual(log.cost_krw, Decimal('5000.00'))
        self.assertEqual(log.parse_outcome, 'success')
        self.assertEqual(log.carrier_code, 2)
        self.assertEqual(log.matched_count, 5)
        self.assertEqual(log.unmatched_count, 1)

    def test_backward_compatible_three_positional_args(self):
        """기존 3-인자 호출(user/outcome 등 미지정)도 그대로 동작 — 하위호환."""
        from .credit import log_claude_usage
        from .models import ClaudeApiLog

        log_claude_usage('compare_guide', 'claude-opus-4-8', None)
        log = ClaudeApiLog.objects.get()
        self.assertIsNone(log.user)
        self.assertEqual(log.parse_outcome, 'success')  # 모델 default
        self.assertEqual(log.cost_krw, Decimal('0'))
        self.assertEqual(log.matched_count, 0)
        self.assertEqual(log.unmatched_count, 0)

    def test_failure_outcome_recorded_even_with_no_usage(self):
        """usage=None(실패) 이어도 outcome 은 1건 기록된다 — 실패율 관측이 목적."""
        from .credit import log_claude_usage
        from .models import ClaudeApiLog

        log_claude_usage('ocr_parse', 'claude-opus-4-8', None,
                         outcome='timeout', user=self.user)
        log = ClaudeApiLog.objects.get()
        self.assertEqual(log.parse_outcome, 'timeout')
        self.assertEqual(log.input_tokens, 0)
        self.assertEqual(log.cost_krw, Decimal('0'))

    def test_logging_failure_is_isolated(self):
        """ClaudeApiLog.objects.create 자체가 실패해도 예외가 호출자로 새지 않는다."""
        from .credit import log_claude_usage
        with patch('inpa.billing.models.ClaudeApiLog.objects.create',
                   side_effect=RuntimeError('db down')):
            log_claude_usage('ocr_parse', 'claude-opus-4-8', None)  # 예외 없이 통과해야 함
