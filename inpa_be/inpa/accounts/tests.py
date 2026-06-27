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
        # 둘 다 매니저에 배정, 한 명만 공유 동의
        Profile.objects.filter(user=self.agent_yes).update(
            manager=self.manager, manager_share_opt_in=True)
        Profile.objects.filter(user=self.agent_no).update(
            manager=self.manager, manager_share_opt_in=False)

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

    def test_non_manager_sees_empty(self):
        _, lone = _verified_planner('lone@test.com')
        body = lone.get('/api/v1/manager/dashboard/').json()
        self.assertEqual(body['agent_count'], 0)
        self.assertEqual(body['agents'], [])

    def test_profile_exposes_mode_fields(self):
        body = self.mc.get('/api/v1/auth/profile/').json()
        for k in ('affiliation_type', 'manager_share_opt_in', 'managed_agents_count', 'manager_email'):
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
