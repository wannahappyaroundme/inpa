"""계정 도메인 happy-path + 핵심 게이트 테스트."""
from datetime import timedelta
from unittest import mock

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

    def test_register_with_planner_fields(self):
        """회원가입에서 소속·직책·설계사 번호(영문·숫자 혼용 가능)를 함께 저장."""
        payload = {**self.reg, 'affiliation': '메리츠화재 강남지점', 'title': '팀장',
                   'license_no': 'AB-2026-0012345'}  # 회사별 영문·숫자 혼용 형식
        r = self.c.post('/api/v1/auth/register/', payload, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        p = Profile.objects.get(user__email=self.reg['email'])
        self.assertEqual(p.affiliation, '메리츠화재 강남지점')
        self.assertEqual(p.title, '팀장')
        self.assertEqual(p.license_no, 'AB-2026-0012345')

    def test_register_rejects_bad_license_no(self):
        """설계사 번호는 느슨한 형식(영문/숫자/하이픈 4~20자)만 확인 — 그 외 400.

        자릿수 강제 금지(PM 2026-07-07): 회사·협회별로 숫자·영문 혼용이라
        특수문자·과도한 길이·너무 짧은 값만 거른다.
        """
        for bad in ('a!', '12', '가나다라마', 'x' * 21):
            r = self.c.post('/api/v1/auth/register/',
                            {**self.reg, 'license_no': bad}, format='json')
            self.assertEqual(r.status_code, 400, bad)

    def test_register_saves_utm_fields(self):
        """가입 시 utm_source/medium/campaign이 Profile에 그대로 저장(활성화 퍼널 #16 유입 캡처)."""
        payload = {**self.reg, 'utm_source': 'naver', 'utm_medium': 'cpc', 'utm_campaign': 'summer2026'}
        r = self.c.post('/api/v1/auth/register/', payload, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        p = Profile.objects.get(user__email=self.reg['email'])
        self.assertEqual(p.utm_source, 'naver')
        self.assertEqual(p.utm_medium, 'cpc')
        self.assertEqual(p.utm_campaign, 'summer2026')

    def test_register_without_utm_defaults_to_blank(self):
        """utm_* 미전달 시 빈 값 저장(퍼널 집계에서 'direct'로 폴백하는 쪽은 admin_console 책임)."""
        r = self._register()
        self.assertEqual(r.status_code, 201, r.content)
        p = Profile.objects.get(user__email=self.reg['email'])
        self.assertEqual(p.utm_source, '')
        self.assertEqual(p.utm_medium, '')
        self.assertEqual(p.utm_campaign, '')

    def test_register_sanitizes_utm_value(self):
        """위험문자 제거(영숫자·-_.만 허용) + 60자 절단 — 가입을 막지 않고 값만 다듬는다."""
        payload = {**self.reg, 'utm_source': '<script>alert(1)</script>;drop table' + 'x' * 60}
        r = self.c.post('/api/v1/auth/register/', payload, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        p = Profile.objects.get(user__email=self.reg['email'])
        self.assertLessEqual(len(p.utm_source), 60)
        self.assertRegex(p.utm_source, r'^[A-Za-z0-9._-]*$')

    def test_register_succeeds_even_if_email_send_fails(self):
        """메일 발송 실패가 가입을 500으로 만들지 않는다(2026-07-07 프로드 사고 회귀).

        유저는 생성되고 201 + email_sent=false + 재발송 안내 메시지를 받는다.
        (발송 실패 후 재시도하면 '이미 가입된 이메일' 400에 갇히는 최악 경로 차단)
        """
        with mock.patch('inpa.accounts.views.send_mail',
                        side_effect=OSError('smtp down')):
            r = self._register()
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertFalse(body['email_sent'])
        self.assertIn('다시 받기', body['message'])
        self.assertTrue(User.objects.filter(email=self.reg['email']).exists())

    def test_resend_verification_stays_200_on_send_failure(self):
        """재발송도 발송 실패 시 500 대신 200 유지(계정 존재 노출 방지 응답 불변)."""
        self._register()
        with mock.patch('inpa.accounts.views.send_mail',
                        side_effect=OSError('smtp down')):
            r = self.c.post('/api/v1/auth/resend-verification/',
                            {'email': self.reg['email']}, format='json')
        self.assertEqual(r.status_code, 200)

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

    def test_this_month_uses_kst_localdate(self):
        """★ KST 경계 회귀(§7): '이번 달' 집계가 timezone.localdate(KST) 기준이어야 한다.
        UTC date.today() 를 쓰면 KST/UTC 월경계 날에 이번 달 실적이 어긋난다."""
        import datetime as _dt
        from unittest import mock
        from inpa.customers.models import Customer
        c = Customer.objects.create(owner=self.agent_yes, name='FA고객',
                                    birth_day='1990.01.01', gender=1)
        # 8월(KST)에 FA 최초 도달 — save 훅 우회 위해 update. UTC 03:00 = KST 12:00 → KST 8월.
        Customer.objects.filter(pk=c.pk).update(
            fa_reached_at=_dt.datetime(2026, 8, 15, 3, 0, tzinfo=_dt.timezone.utc))
        # localdate 를 8월로 고정. 코드가 localdate 를 쓰면 이번 달=8월 → FA 를 집계.
        # (수정 전엔 date.today()=UTC 라 이 mock 이 무시되어 meetings_month=0 → 실패)
        with mock.patch('inpa.accounts.manager.timezone.localdate',
                        return_value=_dt.date(2026, 8, 1)):
            body = self.mc.get('/api/v1/manager/dashboard/').json()
        agent = body['agents'][0]
        self.assertEqual(agent['meetings_month'], 1)

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


class TeamInviteTests(TestCase):
    """팀 초대 링크(#24) — 토큰 왕복 + PIPA-clean 레드라인(share_level 무접촉) 게이트."""

    def setUp(self):
        self.manager, self.mclient = _verified_planner('team-mgr@test.com')
        mp = self.manager.profile
        mp.name = '박팀장'
        mp.affiliation = '인파금융 강남지점'
        mp.save(update_fields=['name', 'affiliation'])
        self.public = APIClient()
        self.reg = {
            'email': 'newbie@test.com', 'password': 'inpaPass123!',
            'password_confirm': 'inpaPass123!', 'tos_agreed': True, 'pp_agreed': True,
        }

    def _invite_url(self):
        r = self.mclient.post('/api/v1/manager/invite-link/')
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()['url']

    def _token_from(self, url):
        return url.split('invite=')[1]

    def test_invite_link_issued(self):
        url = self._invite_url()
        self.assertIn('/register?invite=', url)
        self.assertTrue(self._token_from(url))

    def test_invite_link_requires_auth(self):
        self.assertEqual(self.public.post('/api/v1/manager/invite-link/').status_code, 401)

    def test_invite_info_valid(self):
        token = self._token_from(self._invite_url())
        r = self.public.get('/api/v1/manager/invite-info/', {'token': token})
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body['manager_name'], '박팀장')
        self.assertEqual(body['affiliation'], '인파금융 강남지점')

    def test_invite_info_invalid_404(self):
        r = self.public.get('/api/v1/manager/invite-info/', {'token': 'garbage-token'})
        self.assertEqual(r.status_code, 404)

    @override_settings(TEAM_INVITE_TTL_DAYS=0)
    def test_invite_info_expired_404(self):
        token = self._token_from(self._invite_url())
        r = self.public.get('/api/v1/manager/invite-info/', {'token': token})
        self.assertEqual(r.status_code, 404)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_register_with_invite_links_manager_and_presets_affiliation(self):
        """토큰 왕복: 링크 생성 → 가입 → manager FK 연결 + 빈 affiliation 프리셋."""
        token = self._token_from(self._invite_url())
        r = self.public.post('/api/v1/auth/register/',
                             {**self.reg, 'invite_token': token}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        p = Profile.objects.get(user__email='newbie@test.com')
        self.assertEqual(p.manager_id, self.manager.pk)
        self.assertEqual(p.affiliation, '인파금융 강남지점')  # 비어 있었으므로 프리셋

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_invite_never_presets_share_level(self):
        """★ 회귀(레드라인): 초대 가입이어도 manager_share_level=none 유지(동의 프리셋 금지)."""
        token = self._token_from(self._invite_url())
        r = self.public.post('/api/v1/auth/register/',
                             {**self.reg, 'invite_token': token}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        p = Profile.objects.get(user__email='newbie@test.com')
        self.assertEqual(p.manager_share_level, Profile.SHARE_NONE)
        self.assertFalse(p.manager_share_opt_in)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_invite_keeps_own_affiliation(self):
        """가입자가 소속을 직접 입력하면 초대 프리셋이 덮어쓰지 않는다."""
        token = self._token_from(self._invite_url())
        r = self.public.post(
            '/api/v1/auth/register/',
            {**self.reg, 'invite_token': token, 'affiliation': '내가 쓴 소속'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        p = Profile.objects.get(user__email='newbie@test.com')
        self.assertEqual(p.affiliation, '내가 쓴 소속')
        self.assertEqual(p.manager_id, self.manager.pk)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_register_with_invalid_invite_still_succeeds(self):
        """무효 토큰은 무시(+로그) — 가입은 성공하고 manager 미연결."""
        r = self.public.post('/api/v1/auth/register/',
                             {**self.reg, 'invite_token': 'broken-token'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        p = Profile.objects.get(user__email='newbie@test.com')
        self.assertIsNone(p.manager_id)
        self.assertEqual(p.manager_share_level, Profile.SHARE_NONE)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_register_with_expired_invite_still_succeeds(self):
        """만료 토큰도 가입을 막지 않는다(토큰만 무시)."""
        token = self._token_from(self._invite_url())
        with override_settings(TEAM_INVITE_TTL_DAYS=0):
            r = self.public.post('/api/v1/auth/register/',
                                 {**self.reg, 'invite_token': token}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        p = Profile.objects.get(user__email='newbie@test.com')
        self.assertIsNone(p.manager_id)


class ManagerPlanGateTests(TestCase):
    """팀 기능 권한 게이트(MANAGER_PLAN_GATE_ENABLED, spec 2026-07-09) — 대시보드 + 초대 링크.

    ★ 기본 OFF(dormant) — 게이트 없이도 현행 동작(인증 설계사 누구나 이용)이 그대로 보존돼야 한다.
      ON일 때만 Manager 요금제(billing.Plan.can_use_team=True) 활성·미만료 구독 여부로 402를 가른다.
    """

    def setUp(self):
        from inpa.billing.models import Plan, Subscription
        self.Plan = Plan
        self.Subscription = Subscription
        self.user, self.client = _verified_planner('gate-agent@test.com')
        self.free_plan, _ = Plan.objects.get_or_create(
            code='free', defaults={'display_name': '무료', 'price_krw': 0})
        self.manager_plan, _ = Plan.objects.get_or_create(
            code='manager', defaults={
                'display_name': 'Manager', 'price_krw': 19900, 'can_use_team': True,
            })
        if not self.manager_plan.can_use_team:  # 필드가 나중에 도입된 기존 행 보정(시드와 동일 로직)
            self.manager_plan.can_use_team = True
            self.manager_plan.save(update_fields=['can_use_team'])

    def _subscribe(self, plan, expires_at=None):
        self.Subscription.objects.filter(user=self.user).delete()
        return self.Subscription.objects.create(
            user=self.user, plan=plan, status='active', expires_at=expires_at)

    def test_gate_off_default_preserves_current_behavior(self):
        """기본값(게이트 OFF) — 구독이 없어도(free조차 아니어도) 대시보드·초대 링크 200."""
        self.Subscription.objects.filter(user=self.user).delete()
        r1 = self.client.get('/api/v1/manager/dashboard/')
        self.assertEqual(r1.status_code, 200, r1.content)
        r2 = self.client.post('/api/v1/manager/invite-link/')
        self.assertEqual(r2.status_code, 200, r2.content)

    @override_settings(MANAGER_PLAN_GATE_ENABLED=True)
    def test_gate_on_without_manager_plan_blocks_402(self):
        self._subscribe(self.free_plan)
        r1 = self.client.get('/api/v1/manager/dashboard/')
        self.assertEqual(r1.status_code, 402, r1.content)
        self.assertEqual(r1.json()['code'], 'manager_plan_required')
        r2 = self.client.post('/api/v1/manager/invite-link/')
        self.assertEqual(r2.status_code, 402, r2.content)
        self.assertEqual(r2.json()['code'], 'manager_plan_required')

    @override_settings(MANAGER_PLAN_GATE_ENABLED=True)
    def test_gate_on_with_active_manager_subscription_allows(self):
        self._subscribe(self.manager_plan)
        r1 = self.client.get('/api/v1/manager/dashboard/')
        self.assertEqual(r1.status_code, 200, r1.content)
        r2 = self.client.post('/api/v1/manager/invite-link/')
        self.assertEqual(r2.status_code, 200, r2.content)

    @override_settings(MANAGER_PLAN_GATE_ENABLED=True)
    def test_gate_on_with_expired_manager_subscription_blocks_402(self):
        self._subscribe(self.manager_plan, expires_at=timezone.now() - timedelta(days=1))
        r1 = self.client.get('/api/v1/manager/dashboard/')
        self.assertEqual(r1.status_code, 402, r1.content)
        self.assertEqual(r1.json()['code'], 'manager_plan_required')

    @override_settings(MANAGER_PLAN_GATE_ENABLED=True)
    def test_invite_info_stays_public_regardless_of_gate(self):
        """GET invite-info는 공개(AllowAny) — 게이트와 무관, 무효 토큰이면 그냥 404(게이트 402 아님)."""
        public = APIClient()
        r = public.get('/api/v1/manager/invite-info/', {'token': 'garbage-token'})
        self.assertEqual(r.status_code, 404)


class ProfilePhoneTests(TestCase):
    """Profile.phone(2026-07-07) — PATCH 왕복 + 형식(숫자·하이픈·선두 +, 20자) 검증."""

    def setUp(self):
        self.user, self.c = _verified_planner('phone@test.com')

    def test_phone_patch_roundtrip(self):
        r = self.c.patch('/api/v1/auth/profile/', {'phone': '010-1234-5678'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['phone'], '010-1234-5678')
        self.assertEqual(self.c.get('/api/v1/auth/profile/').json()['phone'], '010-1234-5678')
        self.assertEqual(Profile.objects.get(user=self.user).phone, '010-1234-5678')

    def test_phone_allows_plus_prefix_and_blank_clear(self):
        r = self.c.patch('/api/v1/auth/profile/', {'phone': '+82-10-1234-5678'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        # 빈 값으로 지우기 허용(공유뷰 연락 버튼 비활성으로 회귀)
        r2 = self.c.patch('/api/v1/auth/profile/', {'phone': ''}, format='json')
        self.assertEqual(r2.status_code, 200, r2.content)
        self.assertEqual(r2.json()['phone'], '')

    def test_phone_rejects_bad_chars(self):
        for bad in ('010-1234-56ab', '공일공-1234', '010 1234 5678', '010(1234)5678'):
            r = self.c.patch('/api/v1/auth/profile/', {'phone': bad}, format='json')
            self.assertEqual(r.status_code, 400, bad)
        self.assertEqual(Profile.objects.get(user=self.user).phone, '')

    def test_phone_rejects_over_20_chars(self):
        r = self.c.patch('/api/v1/auth/profile/', {'phone': '0' * 21}, format='json')
        self.assertEqual(r.status_code, 400, r.content)


@override_settings(GOOGLE_OAUTH_ENABLED=True, GOOGLE_OAUTH_CLIENT_ID='cid')
class GoogleLinkSecurityTests(TestCase):
    """FIX 1 — 구글 로그인이 선점(미인증) 계정을 탈취로부터 방어."""

    def setUp(self):
        self.public = APIClient()

    @mock.patch('inpa.accounts.views.verify_google_id_token')
    def test_unverified_account_activated_and_old_password_dies(self, mock_verify):
        # 공격자가 피해자 이메일을 선점(미인증 = is_active=False) + 비번 설정.
        victim = User.objects.create_user(email='victim@test.com', password='attackerPass1!')
        self.assertFalse(victim.is_active)
        self.assertTrue(victim.has_usable_password())
        mock_verify.return_value = {'sub': 'gVictim', 'email': 'victim@test.com',
                                    'email_verified': True}
        r = self.public.post('/api/v1/auth/google/', {'id_token': 'x'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        victim.refresh_from_db()
        # 소유권 증명 → 활성화 + 인증 도장.
        self.assertTrue(victim.is_active)
        self.assertIsNotNone(victim.profile.email_verified_at)
        self.assertEqual(victim.profile.google_sub, 'gVictim')
        # 선점자 비번은 무효화 → 더 이상 로그인 불가(본인은 비번 재설정으로 복구).
        self.assertFalse(victim.has_usable_password())
        r2 = self.public.post('/api/v1/auth/login/',
                              {'email': 'victim@test.com', 'password': 'attackerPass1!'},
                              format='json')
        self.assertNotEqual(r2.status_code, 200)

    @mock.patch('inpa.accounts.views.verify_google_id_token')
    def test_verified_account_keeps_parallel_password(self, mock_verify):
        # 이미 인증된 본인 계정은 병행 로그인용 비번을 보존.
        user, _ = _verified_planner('owner@test.com')
        mock_verify.return_value = {'sub': 'gOwner', 'email': 'owner@test.com',
                                    'email_verified': True}
        r = self.public.post('/api/v1/auth/google/', {'id_token': 'x'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        user.refresh_from_db()
        self.assertTrue(user.has_usable_password())
        r2 = self.public.post('/api/v1/auth/login/',
                              {'email': 'owner@test.com', 'password': 'inpaPass123!'},
                              format='json')
        self.assertEqual(r2.status_code, 200)


class TeamInviteInfoNoIndexTests(TestCase):
    """FIX 2 — 공개 초대 정보 뷰도 noindex(X-Robots-Tag) 헤더를 낸다."""

    def test_invite_info_sends_noindex_header(self):
        from .invite import make_invite_token
        mgr = User.objects.create_user(email='mgr@test.com', is_active=True)
        Profile.objects.create(user=mgr, name='매니저')
        token = make_invite_token(mgr)
        c = APIClient()
        r = c.get(f'/api/v1/manager/invite-info/?token={token}')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn('noindex', r['X-Robots-Tag'])


class IntroCardDailyCapTests(TestCase):
    """FIX 3 — 소개 카드 상담 신청도 refcode 일일상한(429)을 적용."""

    def setUp(self):
        from inpa.customers.models import Customer
        self.Customer = Customer
        self.planner = User.objects.create_user(email='intro@test.com', is_active=True)
        self.profile = Profile.objects.create(user=self.planner, name='설계사')
        self.refcode = self.profile.ref_code
        self.public = APIClient()

    def test_daily_cap_returns_429(self):
        from inpa.accounts import public as public_mod
        # 상한 직전까지 오늘자 소개 리드를 채운다.
        for i in range(public_mod.INTRO_DAILY_CAP_PER_REF):
            self.Customer.objects.create(
                owner=self.planner, name=f'리드{i}',
                lead_source=self.Customer.LEAD_INTRODUCTION,
                lead_created_at=timezone.now())
        r = self.public.post(f'/api/v1/p/{self.refcode}/',
                             {'name': '초과고객', 'phone': '010-9999-0000', 'agreed': 'true'},
                             format='json')
        self.assertEqual(r.status_code, 429, r.content)
        self.assertEqual(r.json()['code'], 'DAILY_LIMIT')

    def test_under_cap_creates_lead(self):
        r = self.public.post(f'/api/v1/p/{self.refcode}/',
                             {'name': '홍길동', 'phone': '010-1234-5678', 'agreed': 'true'},
                             format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(self.Customer.objects.filter(
            owner=self.planner, lead_source=self.Customer.LEAD_INTRODUCTION).exists())
