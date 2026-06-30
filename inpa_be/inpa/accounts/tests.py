"""계정 도메인 happy-path + 핵심 게이트 테스트."""
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Profile, User
from .tokens import make_email_verify_token


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AuthFlowTests(TestCase):
    def setUp(self):
        self.c = APIClient()
        self.reg = {
            'email': 'planner@test.com', 'password': 'inpaPass123!',
            'password_confirm': 'inpaPass123!', 'tos_agreed': True, 'pp_agreed': True,
            'agent_type': 3,
        }

    def _register(self):
        return self.c.post('/api/v1/auth/register/', self.reg, format='json')

    def test_full_auth_flow(self):
        # 회원가입 → 비활성 + 인증메일
        r = self._register()
        self.assertEqual(r.status_code, 201)
        user = User.objects.get(email='planner@test.com')
        self.assertFalse(user.is_active)
        self.assertEqual(len(mail.outbox), 1)

        # 미인증 로그인 차단
        r = self.c.post('/api/v1/auth/login/', {'email': self.reg['email'], 'password': self.reg['password']}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()['code'], 'EMAIL_NOT_VERIFIED')

        # 이메일 인증
        r = self.c.post('/api/v1/auth/verify-email/', {'token': make_email_verify_token(user)}, format='json')
        self.assertEqual(r.status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertIsNotNone(Profile.objects.get(user=user).email_verified_at)

        # 로그인 → 토큰
        r = self.c.post('/api/v1/auth/login/', {'email': self.reg['email'], 'password': self.reg['password']}, format='json')
        self.assertEqual(r.status_code, 200)
        token = r.json()['token']
        self.assertTrue(token)

        # 토큰으로 profile 접근
        auth = APIClient()
        auth.credentials(HTTP_AUTHORIZATION='Token ' + token)
        r = auth.get('/api/v1/auth/profile/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['ref_code'])

    def test_login_ignores_stale_token_header(self):
        """회귀: 무효 Authorization 토큰 헤더가 붙어도 로그인은 401 아님 → 200.

        버그: 브라우저 localStorage 의 헌 토큰이 로그인 요청에 실리면 DRF 전역
        TokenAuthentication 이 그 무효 토큰을 보고 뷰 실행 전에 401 로 막았다.
        공개 로그인은 authentication_classes=[] 로 토큰을 무시해야 한다.
        """
        # 정상 플로우로 활성+인증 사용자 준비
        self._register()
        user = User.objects.get(email=self.reg['email'])
        self.c.post('/api/v1/auth/verify-email/', {'token': make_email_verify_token(user)}, format='json')
        # 무효 토큰 헤더를 달고 로그인
        stale = APIClient()
        stale.credentials(HTTP_AUTHORIZATION='Token stale_invalid_token_123')
        r = stale.post('/api/v1/auth/login/',
                       {'email': self.reg['email'], 'password': self.reg['password']}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json().get('token'))

    def test_unauthenticated_blocked(self):
        self.assertEqual(self.c.get('/api/v1/auth/profile/').status_code, 401)

    def test_duplicate_email_rejected(self):
        self._register()
        self.assertEqual(self._register().status_code, 400)

    def test_login_lockout_after_5_fails(self):
        self._register()
        User.objects.filter(email=self.reg['email']).update(is_active=True)
        for _ in range(5):
            self.c.post('/api/v1/auth/login/', {'email': self.reg['email'], 'password': 'wrong!'}, format='json')
        r = self.c.post('/api/v1/auth/login/', {'email': self.reg['email'], 'password': 'wrong!'}, format='json')
        self.assertEqual(r.status_code, 423)
        self.assertEqual(r.json()['code'], 'ACCOUNT_LOCKED')

    def test_password_reset_flow(self):
        self._register()
        User.objects.filter(email=self.reg['email']).update(is_active=True)
        r = self.c.post('/api/v1/auth/password-reset/', {'email': self.reg['email']}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(mail.outbox), 2)  # 가입메일 + 재설정메일


def _verified_planner(email):
    from django.utils import timezone
    user = User.objects.create_user(email=email, password='inpaPass123!')
    user.is_active = True
    user.save(update_fields=['is_active'])
    Profile.objects.create(user=user, email_verified_at=timezone.now())
    c = APIClient()
    c.force_authenticate(user=user)
    return user, c


class ManagerDashboardTests(TestCase):
    """지점장 대시보드 — 동의(manager_share_opt_in)한 소속 설계사만 집계, PII 비노출."""

    def setUp(self):
        self.manager, self.mc = _verified_planner('manager@test.com')
        self.agent_yes, _ = _verified_planner('agent-yes@test.com')
        self.agent_no, _ = _verified_planner('agent-no@test.com')
        # 둘 다 매니저에 배정, 한 명만 공유(full=활동+실적), 한 명은 공유 안 함(none)
        Profile.objects.filter(user=self.agent_yes).update(
            manager=self.manager, manager_share_level='full')
        Profile.objects.filter(user=self.agent_no).update(
            manager=self.manager, manager_share_level='none')

    def test_only_consented_agent_included(self):
        from inpa.customers.models import Customer
        Customer.objects.create(owner=self.agent_yes, name='고객A', birth_day='1990.01.01', gender=1)
        Customer.objects.create(owner=self.agent_no, name='고객B', birth_day='1990.01.01', gender=1)
        body = self.mc.get('/api/v1/manager/dashboard/').json()
        self.assertEqual(body['agent_count'], 1)  # 동의한 1명만
        self.assertEqual(body['totals']['customer_count'], 1)
        # 개별 고객 PII 미노출 — 집계 수치만
        raw = str(body)
        self.assertNotIn('고객A', raw)
        self.assertNotIn('고객B', raw)

    def test_agent_kpi_includes_performance_fields(self):
        from inpa.customers.models import Customer
        Customer.objects.create(owner=self.agent_yes, name='신규', birth_day='1990.01.01', gender=1)
        body = self.mc.get('/api/v1/manager/dashboard/').json()
        agent = body['agents'][0]
        for k in ('premium_month', 'new_month', 'meetings_month', 'premium_delta',
                  'funnel', 'product_mix', 'last_login', 'is_active_month', 'shares_performance'):
            self.assertIn(k, agent)
        self.assertTrue(agent['shares_performance'])    # full 동의 → 실적 공개
        self.assertGreaterEqual(agent['new_month'], 1)  # 이번 달 신규 고객
        self.assertTrue(agent['is_active_month'])       # 활동 있음
        self.assertEqual(set(agent['funnel'].keys()), {'db', 'contact', 'meeting', 'contract'})
        self.assertEqual(set(agent['product_mix'].keys()), {'life', 'nonlife'})
        for k in ('premium_month', 'new_month', 'active_member_count', 'perf_agent_count'):
            self.assertIn(k, body['totals'])
        self.assertIn('team_product_mix', body)
        self.assertIn('team_premium_trend', body)

    def test_activity_only_hides_performance(self):
        """활동만 동의(activity) → 실적(보험료·유지율) None·shares_performance False, 팀 실적 합계 제외."""
        from inpa.customers.models import Customer
        agent_act, _ = _verified_planner('agent-act@test.com')
        Profile.objects.filter(user=agent_act).update(
            manager=self.manager, manager_share_level='activity')
        Customer.objects.create(owner=agent_act, name='활동고객', sales_stage='contact')
        body = self.mc.get('/api/v1/manager/dashboard/').json()
        self.assertEqual(body['agent_count'], 2)  # full(agent_yes) + activity(agent_act)
        act = next(a for a in body['agents'] if not a['shares_performance'])
        self.assertIsNone(act['premium_month'])   # 실적 비공개
        self.assertIsNone(act['retention_y1'])
        self.assertIn('new_month', act)           # 활동은 공유
        self.assertEqual(body['totals']['perf_agent_count'], 1)  # full 1명만 실적 합산

    def test_non_manager_sees_empty(self):
        _, lone = _verified_planner('lone@test.com')
        body = lone.get('/api/v1/manager/dashboard/').json()
        self.assertEqual(body['agent_count'], 0)
        self.assertEqual(body['agents'], [])

    def test_profile_exposes_mode_fields(self):
        body = self.mc.get('/api/v1/auth/profile/').json()
        for k in ('affiliation_type', 'manager_share_opt_in', 'manager_share_level',
                  'managed_agents_count', 'manager_email'):
            self.assertIn(k, body)
        self.assertEqual(body['managed_agents_count'], 2)  # 배정 총원(동의 무관)


class WithdrawTests(TestCase):
    """회원 탈퇴 — 이메일가입(비번 확인) / 구글가입(이메일 확인, 개인정보 삭제권)."""

    def test_has_usable_password_flag(self):
        _email_user, ec = _verified_planner('w-email@inpa.local')
        self.assertTrue(ec.get('/api/v1/auth/profile/').json()['has_usable_password'])
        guser = User.objects.create_user(email='w-google@inpa.local', password=None)
        guser.is_active = True
        guser.save(update_fields=['is_active'])
        Profile.objects.create(user=guser, email_verified_at=timezone.now())
        gc = APIClient(); gc.force_authenticate(user=guser)
        self.assertFalse(gc.get('/api/v1/auth/profile/').json()['has_usable_password'])

    def test_email_user_withdraw_requires_password(self):
        user, c = _verified_planner('w1@inpa.local')
        self.assertEqual(c.post('/api/v1/auth/withdraw/', {'password': 'wrong'}, format='json').status_code, 400)
        r = c.post('/api/v1/auth/withdraw/', {'password': 'inpaPass123!'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(email='w1@inpa.local').exists())

    def test_google_user_withdraw_by_email_confirm(self):
        guser = User.objects.create_user(email='w-g@inpa.local', password=None)
        guser.is_active = True
        guser.save(update_fields=['is_active'])
        Profile.objects.create(user=guser, email_verified_at=timezone.now())
        gc = APIClient(); gc.force_authenticate(user=guser)
        # 비번 없으니 confirm(이메일) 필요 — 틀리면 400
        self.assertEqual(gc.post('/api/v1/auth/withdraw/', {'confirm': 'nope'}, format='json').status_code, 400)
        r = gc.post('/api/v1/auth/withdraw/', {'confirm': 'w-g@inpa.local'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(email='w-g@inpa.local').exists())


class IntroCardTests(TestCase):
    """소개 카드(공개 /p) — GET 카드, POST 상담신청 → db 리드(introduction)."""

    def setUp(self):
        self.planner, _ = _verified_planner('intro@test.com')
        self.profile = Profile.objects.get(user=self.planner)
        self.profile.name = '홍길동'
        self.profile.intro_text = '3년차 손해보험 전문'
        self.profile.save(update_fields=['name', 'intro_text'])
        self.public = APIClient()

    def test_get_card(self):
        r = self.public.get(f'/api/v1/p/{self.profile.ref_code}/')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body['planner']['name'], '홍길동')
        self.assertEqual(body['planner']['intro_text'], '3년차 손해보험 전문')
        self.assertEqual(body['self_diagnosis_url'], f'/d/{self.profile.ref_code}')

    def test_post_creates_db_lead(self):
        from inpa.customers.models import Customer
        r = self.public.post(f'/api/v1/p/{self.profile.ref_code}/',
                             {'name': '김상담', 'phone': '010-1234-5678', 'agreed': True}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.json()['lead_created'])
        c = Customer.objects.get(owner=self.planner, name='김상담')
        self.assertEqual(c.sales_stage, 'db')
        self.assertEqual(c.lead_source, 'introduction')
        self.assertIsNone(c.consent_overseas_at)   # 소개 카드는 국외이전 동의 없음(병력/OCR 아님)

    def test_post_requires_consent(self):
        r = self.public.post(f'/api/v1/p/{self.profile.ref_code}/',
                             {'name': '김상담', 'agreed': False}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_invalid_ref_404(self):
        self.assertEqual(self.public.get('/api/v1/p/NOPENOPE/').status_code, 404)
