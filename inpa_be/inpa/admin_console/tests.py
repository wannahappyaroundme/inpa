"""admin_console 핵심 가시성·권한 테스트 (dev/19 §8 수용 기준).

★ 검증 항목:
  [인증]
  AC1  admin 로그인 → 200 + token (is_admin=True)
  AC2  설계사(is_admin=False)로 admin 로그인 → 403
  AC3  설계사 token으로 /api/v1/admin/* 호출 → 403

  [대시보드]
  D1   GET /api/v1/admin/dashboard/ — admin 200, 비인증 401
  D2   대시보드 응답에 판정어 없음 (사실 카운트 키만 확인)

  [설계사 관리]
  U1   GET /api/v1/admin/users/ — admin 200, 설계사 403
  U2   PATCH /api/v1/admin/users/:id/subscription/ — 요금제 변경 + 알림 생성
  U3   POST /api/v1/admin/users/:id/send_reset_email/ — 메일 발송

  [1:1 문의]
  I1   GET /api/v1/admin/inquiries/ — admin 전체 조회
  I2   POST /api/v1/admin/inquiries/:id/reply/ — 답변 → status=answered + 알림
  I3   PATCH /api/v1/admin/inquiries/:id/status/ — 상태 변경

  [신고]
  R1   PATCH /api/v1/admin/reports/:id/action/ — resolved → 게시글 is_hidden=True + 알림
  R2   dismissed 처리 → 게시글 is_hidden 변화 없음

  [판촉물 주문]
  O1   PATCH /api/v1/admin/orders/:id/status/ — 상태 전이 + StatusLog + 알림
  O2   허용되지 않은 상태 전이 → 400

  [동의 로그]
  CL1  GET /api/v1/admin/consent-logs/ — admin 200, 설계사 403
  CL2  DELETE 요청 → 405 (Method Not Allowed) — 감사 무결성

  [정규화 매핑]
  NM1  POST /api/v1/admin/normalization/map/ — UnmatchedLog → NormalizationDict + resolved=True

  [공지사항]
  N1   POST /api/v1/admin/notices/ — admin 작성 → GET /api/v1/board/notices/ 노출
  N2   임시저장(is_published=False) → 설계사 GET에 미노출

  [요금제 설정]
  P1   PATCH /api/v1/admin/settings/plans/:code/ — 한도 변경
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User
from inpa.admin_console.models import PolicyVersion
from inpa.analysis.models import AnalysisCategory, AnalysisDetail, AnalysisSubCategory, UnmatchedLog
from inpa.billing.credit import add_months
from inpa.billing.models import Plan, Subscription
from inpa.boards.models import Inquiry, InquiryReply, Notice, Post, Report
from inpa.customers.models import ConsentLog, Customer
from inpa.insurances.models import CustomerInsurance
from inpa.notifications.models import Notification
from inpa.promotion.models import PromotionOrder, PromotionOrderStatusLog, PromotionSample


# ─── 헬퍼 ─────────────────────────────────────────────────────────────

def _make_user(email, password='inpaPass123!', is_admin=False, active=True):
    """이메일 인증 완료 User + Profile 생성."""
    user = User.objects.create_user(email=email, password=password)
    user.is_active = active
    user.save()
    profile, _ = Profile.objects.get_or_create(user=user)
    profile.is_admin = is_admin
    profile.save()
    return user


def _auth_client(user):
    """DRF Token 인증 APIClient."""
    from rest_framework.authtoken.models import Token
    client = APIClient()
    token, _ = Token.objects.get_or_create(user=user)
    client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
    return client


def _make_plan(code='free', display_name='Free', price_krw=0):
    plan, _ = Plan.objects.get_or_create(
        code=code,
        defaults={'display_name': display_name, 'price_krw': price_krw},
    )
    return plan


def _make_sample():
    return PromotionSample.objects.create(
        name='테스트 달력',
        category='달력',
        form_fields=[{'key': 'quantity', 'label': '수량', 'type': 'number', 'required': True}],
    )


# ─── AC: admin 인증 ─────────────────────────────────────────────────

class AdminAuthTest(TestCase):
    """AC1-AC3: admin 로그인 + 권한 분리."""

    def setUp(self):
        self.admin = _make_user('admin@inpa.kr', is_admin=True)
        self.planner = _make_user('planner@inpa.kr', is_admin=False)

    def test_AC1_admin_login_success(self):
        """AC1: admin 이메일/비밀번호 로그인 → 200 + token."""
        res = self.client.post('/api/v1/admin/auth/login/', {
            'email': 'admin@inpa.kr', 'password': 'inpaPass123!',
        }, content_type='application/json')
        self.assertEqual(res.status_code, 200)
        self.assertIn('token', res.json())
        self.assertIn('admin', res.json())

    def test_AC1b_admin_login_ignores_stale_token(self):
        """AC1b(회귀): 무효 Authorization 토큰 헤더가 붙어도 로그인은 401 아님 → 200.

        버그: DRF 전역 TokenAuthentication 이 공개 로그인 뷰에서도 돌아, 브라우저
        localStorage 의 헌 토큰이 로그인 요청에 실리면 뷰 실행 전에 401 로 막았다
        (비번 검증조차 안 됨). authentication_classes=[] 로 공개 로그인은 토큰 무시해야 한다.
        """
        res = self.client.post(
            '/api/v1/admin/auth/login/',
            {'email': 'admin@inpa.kr', 'password': 'inpaPass123!'},
            content_type='application/json',
            HTTP_AUTHORIZATION='Token stale_invalid_token_123',
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.assertIn('token', res.json())

    def test_AC2_planner_cannot_admin_login(self):
        """AC2: 설계사(is_admin=False)로 admin 로그인 → 403."""
        res = self.client.post('/api/v1/admin/auth/login/', {
            'email': 'planner@inpa.kr', 'password': 'inpaPass123!',
        }, content_type='application/json')
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()['code'], 'FORBIDDEN')

    def test_AC3_planner_token_admin_endpoint_403(self):
        """AC3: 설계사 token으로 /api/v1/admin/dashboard/ → 403."""
        client = _auth_client(self.planner)
        res = client.get('/api/v1/admin/dashboard/')
        self.assertEqual(res.status_code, 403)


# ─── D: 대시보드 ────────────────────────────────────────────────────

class AdminDashboardTest(TestCase):
    """D1-D2: 대시보드 지표 + 판정어 금지."""

    def setUp(self):
        self.admin = _make_user('admin@inpa.kr', is_admin=True)
        self.client_admin = _auth_client(self.admin)

    def test_D1_dashboard_200(self):
        """D1: admin GET /admin/dashboard/ → 200."""
        res = self.client_admin.get('/api/v1/admin/dashboard/')
        self.assertEqual(res.status_code, 200)

    def test_D1_unauthenticated_401(self):
        """D1: 비인증 GET /admin/dashboard/ → 401."""
        res = self.client.get('/api/v1/admin/dashboard/')
        self.assertEqual(res.status_code, 401)

    def test_D2_dashboard_no_judgment_labels(self):
        """D2: 대시보드 응답에 판정어 없음 — 사실 카운트 키만 확인."""
        res = self.client_admin.get('/api/v1/admin/dashboard/')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        # 판정어 금지 — 아래 키만 존재해야 함
        judgment_words = ['위험', '낮음', '부족', '경고', '주의', 'bad', 'risk', 'low']
        response_str = str(data).lower()
        for word in judgment_words:
            # 값이 아닌 키 레벨에서 판정어 미노출 확인
            self.assertNotIn(word, list(data.keys()),
                             f"대시보드 키에 판정어 '{word}' 발견")


# ─── U: 설계사 관리 ─────────────────────────────────────────────────

class AdminUserManagementTest(TestCase):
    """U1-U3: 설계사 관리."""

    def setUp(self):
        self.admin = _make_user('admin@inpa.kr', is_admin=True)
        self.planner = _make_user('planner@test.kr', is_admin=False)
        self.plan = _make_plan()
        Subscription.objects.get_or_create(user=self.planner, defaults={'plan': self.plan})
        self.client_admin = _auth_client(self.admin)
        self.client_planner = _auth_client(self.planner)

    def test_U1_admin_user_list(self):
        """U1: admin → 설계사 목록 200, 설계사 → 403."""
        res_admin = self.client_admin.get('/api/v1/admin/users/')
        self.assertEqual(res_admin.status_code, 200)
        self.assertIn('results', res_admin.json())

        res_planner = self.client_planner.get('/api/v1/admin/users/')
        self.assertEqual(res_planner.status_code, 403)

    def test_U4_admin_user_customers(self):
        """U4: admin → 설계사 고객 목록 200(비민감 필드만), 설계사 → 403."""
        from inpa.customers.models import Customer
        Customer.objects.create(owner=self.planner, name='홍고객',
                                mobile_phone_number='010-1111-2222', sales_stage='contact')
        res = self.client_admin.get(f'/api/v1/admin/users/{self.planner.id}/customers/')
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body['count'], 1)
        row = body['results'][0]
        self.assertEqual(row['name'], '홍고객')
        for k in ('sales_stage', 'sales_stage_display', 'status', 'insurance_count', 'last_contacted_at'):
            self.assertIn(k, row)
        self.assertNotIn('memo', row)        # 민감/불필요 필드 미노출
        self.assertNotIn('birth_day', row)
        res_planner = self.client_planner.get(f'/api/v1/admin/users/{self.planner.id}/customers/')
        self.assertEqual(res_planner.status_code, 403)

    def test_U2_subscription_change(self):
        """U2: admin이 설계사 요금제 변경 → Subscription 업데이트 + 알림 생성."""
        plus_plan = _make_plan('plus', 'Plus', 9900)
        res = self.client_admin.patch(
            f'/api/v1/admin/users/{self.planner.id}/subscription/',
            {'plan_code': 'plus'},
            format='json',
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['plan_code'], 'plus')
        # 설계사에게 알림 생성 확인
        self.assertTrue(Notification.objects.filter(owner=self.planner).exists())

    def test_U3_send_reset_email(self):
        """U3: admin이 비밀번호 재설정 이메일 발송 → {sent: true}."""
        res = self.client_admin.post(
            f'/api/v1/admin/users/{self.planner.id}/send_reset_email/',
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()['sent'])


# ─── 연구독 + 첫 유료 보너스 (spec 2026-07-15) ───────────────────────

class AdminSubscriptionCycleBonusTest(TestCase):
    """관리자 구독 부여 시 결제 주기(월/연) 만료 계산 + 첫 유료 보너스(+1개월, 사용자당 1회)."""

    def setUp(self):
        from inpa.billing.models import RuntimeConfig
        self.admin = _make_user('admin_cycle@inpa.kr', is_admin=True)
        self.planner = _make_user('planner_cycle@test.kr', is_admin=False)
        self.free = _make_plan('free', '무료', 0)
        self.plus = _make_plan('plus', 'Plus', 19900)
        Subscription.objects.get_or_create(user=self.planner, defaults={'plan': self.free})
        self.client_admin = _auth_client(self.admin)
        # 기본 이벤트 OFF 상태로 시작.
        RuntimeConfig.objects.update_or_create(pk=1, defaults={'first_paid_bonus_enabled': False})

    def _grant(self, plan_code, billing_cycle=None):
        body = {'plan_code': plan_code, 'status': 'active'}
        if billing_cycle:
            body['billing_cycle'] = billing_cycle
        res = self.client_admin.patch(
            f'/api/v1/admin/users/{self.planner.id}/subscription/', body, format='json')
        return res

    def _sub(self):
        return Subscription.objects.get(user=self.planner)

    def _assert_months(self, expires_at, months, anchor):
        """expires_at 이 anchor + months개월 근처(±2일)인지."""
        expected = add_months(anchor, months)
        delta = abs((expires_at - expected).total_seconds())
        self.assertLess(delta, 2 * 24 * 3600,
                        f'만료가 {months}개월 기대와 다름: {expires_at} vs {expected}')

    def test_monthly_grant_expires_one_month(self):
        before = timezone.now()
        res = self._grant('plus', 'monthly')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['billing_cycle'], 'monthly')
        sub = self._sub()
        self.assertEqual(sub.billing_cycle, 'monthly')
        self._assert_months(sub.expires_at, 1, before)
        self.assertFalse(sub.first_paid_bonus_used)  # 이벤트 OFF

    def test_annual_grant_expires_twelve_months(self):
        before = timezone.now()
        res = self._grant('plus', 'annual')
        self.assertEqual(res.status_code, 200)
        sub = self._sub()
        self.assertEqual(sub.billing_cycle, 'annual')
        self._assert_months(sub.expires_at, 12, before)

    def test_first_paid_bonus_on_adds_one_month_and_marks_used(self):
        from inpa.billing.models import RuntimeConfig
        RuntimeConfig.objects.update_or_create(pk=1, defaults={'first_paid_bonus_enabled': True})
        before = timezone.now()
        res = self._grant('plus', 'monthly')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()['first_paid_bonus_used'])
        sub = self._sub()
        self.assertTrue(sub.first_paid_bonus_used)
        # 1개월 + 보너스 1개월 = 2개월.
        self._assert_months(sub.expires_at, 2, before)

    def test_second_grant_does_not_get_bonus_again(self):
        from inpa.billing.models import RuntimeConfig
        RuntimeConfig.objects.update_or_create(pk=1, defaults={'first_paid_bonus_enabled': True})
        self._grant('plus', 'monthly')  # 1st = 보너스 소진
        self.assertTrue(self._sub().first_paid_bonus_used)
        before = timezone.now()
        self._grant('plus', 'monthly')  # 2nd = 보너스 없음
        sub = self._sub()
        self.assertTrue(sub.first_paid_bonus_used)
        self._assert_months(sub.expires_at, 1, before)  # 보너스 없이 1개월

    def test_bonus_off_no_extra_month(self):
        # 기본 OFF.
        before = timezone.now()
        self._grant('plus', 'monthly')
        sub = self._sub()
        self.assertFalse(sub.first_paid_bonus_used)
        self._assert_months(sub.expires_at, 1, before)

    def test_annual_plus_bonus_first_is_thirteen_months(self):
        from inpa.billing.models import RuntimeConfig
        RuntimeConfig.objects.update_or_create(pk=1, defaults={'first_paid_bonus_enabled': True})
        before = timezone.now()
        self._grant('plus', 'annual')
        sub = self._sub()
        self.assertTrue(sub.first_paid_bonus_used)
        # 12개월 + 보너스 1개월 = 13개월.
        self._assert_months(sub.expires_at, 13, before)

    def test_free_plan_keeps_expires_none(self):
        # 유료(연구독)로 만료를 세팅한 뒤 free 로 내리면 무기한(None) 복귀.
        self._grant('plus', 'annual')
        self.assertIsNotNone(self._sub().expires_at)
        self._grant('free')
        sub = self._sub()
        self.assertEqual(sub.plan.code, 'free')
        self.assertIsNone(sub.expires_at)

    def test_paid_grant_without_cycle_preserves_existing_expiry(self):
        """하위호환: billing_cycle 미지정 유료 부여는 기존 expires_at 을 강제하지 않는다."""
        # 기존 무기한(None) 유료 부여 관례 재현 — cycle 없이 plus 부여.
        res = self._grant('plus')  # billing_cycle 없음
        self.assertEqual(res.status_code, 200)
        sub = self._sub()
        self.assertEqual(sub.plan.code, 'plus')
        self.assertIsNone(sub.expires_at)  # 만료 강제 안 함


# ─── I: 1:1 문의 ────────────────────────────────────────────────────

class AdminInquiryTest(TestCase):
    """I1-I3: 1:1 문의 관리."""

    def setUp(self):
        self.admin = _make_user('admin@inpa.kr', is_admin=True)
        self.planner = _make_user('planner@test.kr', is_admin=False)
        self.inquiry = Inquiry.objects.create(
            owner=self.planner,
            category='bug',
            title='버그 신고',
            body='버그가 발생했습니다.',
        )
        self.client_admin = _auth_client(self.admin)

    def test_I1_admin_inquiry_list(self):
        """I1: admin → 전체 문의 조회 (OwnedQuerySetMixin bypass)."""
        res = self.client_admin.get('/api/v1/admin/inquiries/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['count'], 1)

    def test_I2_reply_creates_answer_and_notification(self):
        """I2: 답변 등록 → status=answered + 설계사 알림."""
        res = self.client_admin.post(
            f'/api/v1/admin/inquiries/{self.inquiry.id}/reply/',
            {'body': '확인 후 수정하겠습니다.'},
            format='json',
        )
        self.assertEqual(res.status_code, 201)
        self.inquiry.refresh_from_db()
        self.assertEqual(self.inquiry.status, Inquiry.STATUS_ANSWERED)
        self.assertTrue(
            InquiryReply.objects.filter(inquiry=self.inquiry).exists()
        )
        self.assertTrue(Notification.objects.filter(owner=self.planner).exists())

    def test_I3_status_change(self):
        """I3: admin이 문의 상태 변경 → closed."""
        res = self.client_admin.patch(
            f'/api/v1/admin/inquiries/{self.inquiry.id}/status/',
            {'status': 'closed'},
            format='json',
        )
        self.assertEqual(res.status_code, 200)
        self.inquiry.refresh_from_db()
        self.assertEqual(self.inquiry.status, Inquiry.STATUS_CLOSED)

    def test_category_filter(self):
        """?category= 필터 — 해당 카테고리만 반환."""
        Inquiry.objects.create(
            owner=self.planner, category='feedback', title='[이용 의견] 좋아요',
            body='좋아요', rating=5,
        )
        res = self.client_admin.get('/api/v1/admin/inquiries/?category=feedback')
        self.assertEqual(res.status_code, 200)
        cats = {row['category'] for row in res.json()['results']}
        self.assertEqual(cats, {'feedback'})

    def test_new_fields_exposed_and_anonymous_labeled(self):
        """익명(owner=None) 행 = '비회원' + rating/meta/contact_email 노출."""
        anon = Inquiry.objects.create(
            owner=None, category='bug', title='[불편 신고] 버그',
            body='버그', meta={'path': '/x', 'user_agent': 'UA', 'viewport': '390x844'},
            contact_email='guest@example.com',
        )
        # 목록: 비회원 표기 + rating/contact_email
        listing = self.client_admin.get('/api/v1/admin/inquiries/?category=bug')
        row = next(r for r in listing.json()['results'] if r['id'] == anon.id)
        self.assertEqual(row['owner_display'], '비회원')
        self.assertIsNone(row['owner_email'])
        self.assertIn('rating', row)
        self.assertEqual(row['contact_email'], 'guest@example.com')
        # 상세: meta 블록 노출
        detail = self.client_admin.get(f'/api/v1/admin/inquiries/{anon.id}/')
        body = detail.json()
        self.assertEqual(body['owner_display'], '비회원')
        self.assertEqual(body['meta']['path'], '/x')


# ─── R: 신고 모더레이션 ────────────────────────────────────────────

class AdminReportTest(TestCase):
    """R1-R2: 신고 처리."""

    def setUp(self):
        self.admin = _make_user('admin@inpa.kr', is_admin=True)
        self.planner = _make_user('planner@test.kr', is_admin=False)
        self.post = Post.objects.create(author=self.planner, body='테스트 게시글')
        self.report = Report.objects.create(
            reporter=self.planner,
            content_type=Report.CONTENT_POST,
            object_id=self.post.pk,
            reason=Report.REASON_SPAM,
        )
        self.client_admin = _auth_client(self.admin)

    def test_R1_resolved_hides_post_and_notifies(self):
        """R1: resolved → 게시글 is_hidden=True + 신고자 알림."""
        res = self.client_admin.patch(
            f'/api/v1/admin/reports/{self.report.id}/action/',
            {'action': 'resolved'},
            format='json',
        )
        self.assertEqual(res.status_code, 200)
        self.post.refresh_from_db()
        self.assertTrue(self.post.is_hidden)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, Report.STATUS_RESOLVED)
        self.assertTrue(Notification.objects.filter(owner=self.planner).exists())

    def test_R2_dismissed_does_not_hide_post(self):
        """R2: dismissed → 게시글 is_hidden 변화 없음."""
        res = self.client_admin.patch(
            f'/api/v1/admin/reports/{self.report.id}/action/',
            {'action': 'dismissed'},
            format='json',
        )
        self.assertEqual(res.status_code, 200)
        self.post.refresh_from_db()
        self.assertFalse(self.post.is_hidden)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, Report.STATUS_DISMISSED)


# ─── O: 판촉물 주문 ─────────────────────────────────────────────────

class AdminOrderTest(TestCase):
    """O1-O2: 판촉물 주문 상태 전이."""

    def setUp(self):
        self.admin = _make_user('admin@inpa.kr', is_admin=True)
        self.planner = _make_user('planner@test.kr', is_admin=False)
        sample = _make_sample()
        self.order = PromotionOrder.objects.create(
            owner=self.planner,
            sample=sample,
            form_response={'quantity': 100},
        )
        self.client_admin = _auth_client(self.admin)

    def test_O1_status_transition_and_log(self):
        """O1: pending → reviewing 전이 + StatusLog 적재 + 설계사 알림."""
        res = self.client_admin.patch(
            f'/api/v1/admin/orders/{self.order.id}/status/',
            {'status': 'reviewing', 'admin_note': '검토 중입니다.'},
            format='json',
        )
        self.assertEqual(res.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, PromotionOrder.STATUS_REVIEWING)
        self.assertTrue(PromotionOrderStatusLog.objects.filter(order=self.order).exists())
        self.assertTrue(Notification.objects.filter(owner=self.planner).exists())

    def test_O2_invalid_transition_400(self):
        """O2: pending → shipping (허용되지 않은 전이) → 400."""
        res = self.client_admin.patch(
            f'/api/v1/admin/orders/{self.order.id}/status/',
            {'status': 'shipping'},
            format='json',
        )
        self.assertEqual(res.status_code, 400)


# ─── CL: 동의 로그 ──────────────────────────────────────────────────

class AdminConsentLogTest(TestCase):
    """CL1-CL2: 동의 로그 가시성 + DELETE 금지."""

    def setUp(self):
        self.admin = _make_user('admin@inpa.kr', is_admin=True)
        self.planner = _make_user('planner@test.kr', is_admin=False)
        self.customer = Customer.objects.create(
            owner=self.planner, name='홍길동',
        )
        self.consent = ConsentLog.objects.create(
            customer=self.customer,
            scope=ConsentLog.SCOPE_OVERSEAS_MEDICAL,
        )
        self.client_admin = _auth_client(self.admin)
        self.client_planner = _auth_client(self.planner)

    def test_CL1_admin_can_read_consent_logs(self):
        """CL1: admin → 동의 로그 조회 200, 설계사 → 403."""
        res_admin = self.client_admin.get('/api/v1/admin/consent-logs/')
        self.assertEqual(res_admin.status_code, 200)

        res_planner = self.client_planner.get('/api/v1/admin/consent-logs/')
        self.assertEqual(res_planner.status_code, 403)

    def test_CL2_delete_not_allowed(self):
        """CL2: DELETE /api/v1/admin/consent-logs/ → 405 (감사 무결성)."""
        res = self.client_admin.delete('/api/v1/admin/consent-logs/')
        self.assertEqual(res.status_code, 405)

    def test_CL1_customer_name_masked(self):
        """CL1: 동의 로그 응답에서 고객명 마스킹 ('홍**') 확인."""
        res = self.client_admin.get('/api/v1/admin/consent-logs/')
        self.assertEqual(res.status_code, 200)
        results = res.json()['results']
        self.assertTrue(len(results) > 0)
        masked = results[0]['customer_name_masked']
        self.assertTrue(masked.endswith('**'), f"마스킹 미적용: {masked}")
        # P3c: 동의 주체(subject) 노출 — 감사 필수
        self.assertIn('subject', results[0])
        self.assertEqual(results[0]['subject'], ConsentLog.SUBJECT_PLANNER_ATTESTED)
        self.assertIn('subject_display', results[0])


# ─── NM: 정규화 매핑 ────────────────────────────────────────────────

class AdminNormalizationTest(TestCase):
    """NM1: 미매칭 → 정규화 사전 매핑."""

    def setUp(self):
        self.admin = _make_user('admin@inpa.kr', is_admin=True)
        self.client_admin = _auth_client(self.admin)
        # AnalysisDetail 생성 (외래 키 체인)
        cat = AnalysisCategory.objects.create(name='생명', insurance_type=1)
        sub = AnalysisSubCategory.objects.create(name='사망', category=cat, insurance_type=1)
        self.detail = AnalysisDetail.objects.create(name='일반사망', sub_category=sub)
        self.unmatched = UnmatchedLog.objects.create(
            company=1, raw_name='일반사망보험금', occurrence=3,
        )

    def test_NM1_map_unmatched_to_dict(self):
        """NM1: POST /admin/normalization/map/ → NormalizationDict 생성 + resolved=True."""
        from inpa.analysis.models import NormalizationDict
        res = self.client_admin.post('/api/v1/admin/normalization/map/', {
            'unmatched_log_id': self.unmatched.id,
            'std_detail_id': self.detail.id,
            'confidence': 95,
        }, format='json')
        self.assertEqual(res.status_code, 201)
        self.unmatched.refresh_from_db()
        self.assertTrue(self.unmatched.resolved)
        self.assertTrue(
            NormalizationDict.objects.filter(
                company=1, raw_name='일반사망보험금',
                source=NormalizationDict.SOURCE_ADMIN_VERIFIED,
            ).exists()
        )


# ─── F: 담보 위치 확인 요청 (설계사 피드백 검수, 2026-07-09) ──────────

class AdminCoverageFlagTest(TestCase):
    """F1-F6: 플래그 목록/승인(사전 등록 + M2M 교정 + 충돌 경고)/반려/권한."""

    def setUp(self):
        from inpa.insurances.models import (
            CustomerInsurance, CustomerInsuranceDetail, InsuranceCategory,
            InsuranceDetail, InsuranceSubCategory,
        )
        self.admin = _make_user('admin@inpa.kr', is_admin=True)
        self.client_admin = _auth_client(self.admin)
        self.planner = _make_user('planner@inpa.kr')
        self.client_planner = _auth_client(self.planner)
        self.customer = Customer.objects.create(owner=self.planner, name='홍길동')

        # 표준 트리([표준] 마커) — 잘못 매핑된 leaf(old) + 올바른 leaf(new)
        cat = AnalysisCategory.objects.create(name='[표준] 진단비', insurance_type=0)
        sub = AnalysisSubCategory.objects.create(name='암', category=cat, insurance_type=0)
        self.old_leaf = AnalysisDetail.objects.create(name='일반암', sub_category=sub)
        self.new_leaf = AnalysisDetail.objects.create(name='유사암', sub_category=sub)
        # 비표준(seed_demo 류) leaf — leaves 응답에서 제외돼야 함
        demo_cat = AnalysisCategory.objects.create(name='데모', insurance_type=0)
        demo_sub = AnalysisSubCategory.objects.create(name='데모암', category=demo_cat, insurance_type=0)
        self.demo_leaf = AnalysisDetail.objects.create(name='데모일반암', sub_category=demo_sub)

        # 카탈로그 담보(전역 공유) — 현재 old_leaf 에 연결됨
        icat = InsuranceCategory.objects.create(name='손보상품', insurance_type=2)
        isub = InsuranceSubCategory.objects.create(name='보장', category=icat, insurance_type=2)
        self.idet = InsuranceDetail.objects.create(sub_category=isub, name='상피내암진단')
        self.idet.analysis_detail.add(self.old_leaf)

        ci = CustomerInsurance.objects.create(
            customer=self.customer, insurance_type=2, portfolio_type=1,
            name='테스트보험', company=2)
        self.case = CustomerInsuranceDetail.objects.create(
            insurance=ci, detail=self.idet, assurance_amount=10_000_000,
            raw_name='상피내암진단특약')

        from inpa.analysis.models import CoverageFlag
        self.flag = CoverageFlag.objects.create(
            owner=self.planner, customer=self.customer,
            analysis_detail=self.old_leaf, case=self.case,
            raw_name_snapshot='상피내암진단특약', company=2, note='유사암 같아요')

    def _resolve_url(self, flag_id):
        return f'/api/v1/admin/normalization/flags/{flag_id}/resolve/'

    def test_F1_list_defaults_to_open(self):
        from inpa.analysis.models import CoverageFlag
        CoverageFlag.objects.create(
            owner=self.planner, customer=self.customer,
            analysis_detail=self.old_leaf, raw_name_snapshot='이미처리',
            company=2, status=CoverageFlag.STATUS_REJECTED)
        res = self.client_admin.get('/api/v1/admin/normalization/flags/')
        self.assertEqual(res.status_code, 200)
        rows = res.json()['results']
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['raw_name_snapshot'], '상피내암진단특약')
        self.assertEqual(row['company'], 2)
        self.assertEqual(row['planner_email'], 'planner@inpa.kr')
        self.assertEqual(row['customer_name'], '홍길동')
        self.assertEqual(row['current_mapping'], '일반암')
        self.assertEqual(row['status'], 'open')
        # status=all → 2건
        res_all = self.client_admin.get('/api/v1/admin/normalization/flags/?status=all')
        self.assertEqual(res_all.json()['count'], 2)

    def test_F2_accept_creates_dict_relinks_and_warns(self):
        from inpa.analysis.models import CoverageFlag, NormalizationDict
        # 부분문자열 관계의 기존 사전 행('암진단' ⊂ '상피내암진단특약') → 경고 대상
        NormalizationDict.objects.create(
            std_detail=self.old_leaf, company=2, raw_name='암진단',
            source=NormalizationDict.SOURCE_ADMIN_VERIFIED)
        res = self.client_admin.post(self._resolve_url(self.flag.id), {
            'action': 'accept', 'std_detail_id': self.new_leaf.id, 'memo': '유사암으로 정정',
        }, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        # 사전 행: admin_verified + verified_by
        norm = NormalizationDict.objects.get(company=2, raw_name='상피내암진단특약')
        self.assertEqual(norm.std_detail_id, self.new_leaf.id)
        self.assertEqual(norm.source, NormalizationDict.SOURCE_ADMIN_VERIFIED)
        self.assertEqual(norm.verified_by_id, self.admin.id)
        self.assertTrue(body['dict_created'])
        # M2M 교체(카탈로그 전역 정정)
        self.assertEqual(
            list(self.idet.analysis_detail.values_list('id', flat=True)),
            [self.new_leaf.id])
        self.assertEqual(body['relinked'], 1)
        # 충돌 경고(차단 없음)
        self.assertTrue(any('암진단' in w for w in body['warnings']))
        # 플래그 상태
        self.flag.refresh_from_db()
        self.assertEqual(self.flag.status, CoverageFlag.STATUS_ACCEPTED)
        self.assertEqual(self.flag.resolved_by_id, self.admin.id)
        self.assertEqual(self.flag.resolution_memo, '유사암으로 정정')

    def test_F2b_accept_without_std_detail_400(self):
        res = self.client_admin.post(self._resolve_url(self.flag.id), {
            'action': 'accept',
        }, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()['code'], 'STD_DETAIL_REQUIRED')

    def test_F3_reject_sets_status_and_memo(self):
        from inpa.analysis.models import CoverageFlag, NormalizationDict
        res = self.client_admin.post(self._resolve_url(self.flag.id), {
            'action': 'reject', 'memo': '현재 매핑이 맞아요',
        }, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        self.flag.refresh_from_db()
        self.assertEqual(self.flag.status, CoverageFlag.STATUS_REJECTED)
        self.assertEqual(self.flag.resolution_memo, '현재 매핑이 맞아요')
        self.assertEqual(self.flag.resolved_by_id, self.admin.id)
        self.assertEqual(NormalizationDict.objects.count(), 0)
        # M2M 무변경
        self.assertEqual(
            list(self.idet.analysis_detail.values_list('id', flat=True)),
            [self.old_leaf.id])

    def test_F4_already_resolved_409(self):
        self.client_admin.post(self._resolve_url(self.flag.id), {
            'action': 'reject',
        }, format='json')
        res = self.client_admin.post(self._resolve_url(self.flag.id), {
            'action': 'accept', 'std_detail_id': self.new_leaf.id,
        }, format='json')
        self.assertEqual(res.status_code, 409)

    def test_F5_planner_cannot_access(self):
        res = self.client_planner.get('/api/v1/admin/normalization/flags/')
        self.assertEqual(res.status_code, 403)
        res2 = self.client_planner.post(self._resolve_url(self.flag.id), {
            'action': 'reject',
        }, format='json')
        self.assertEqual(res2.status_code, 403)

    def test_F6_leaves_standard_scope_only(self):
        res = self.client_admin.get('/api/v1/admin/normalization/leaves/')
        self.assertEqual(res.status_code, 200)
        ids = [row['id'] for row in res.json()]
        self.assertIn(self.old_leaf.id, ids)
        self.assertIn(self.new_leaf.id, ids)
        self.assertNotIn(self.demo_leaf.id, ids)  # 비표준([표준] 마커 없음) 제외
        row = next(r for r in res.json() if r['id'] == self.old_leaf.id)
        self.assertEqual(row['category_name'], '[표준] 진단비')
        self.assertEqual(row['sub_category_name'], '암')

    def test_F7_dashboard_counts_open_flags(self):
        res = self.client_admin.get('/api/v1/admin/dashboard/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['open_flags'], 1)

    def test_F8_accept_company_negative_skips_dict_but_relinks(self):
        """보험사 미감지(company=-1) 승인: 죽은 사전 행을 만들지 않되 연결은 정정."""
        from inpa.analysis.models import CoverageFlag, NormalizationDict
        from inpa.insurances.models import (
            CustomerInsurance, CustomerInsuranceDetail, InsuranceDetail,
        )
        icat = self.idet.sub_category.category
        isub = self.idet.sub_category
        idet2 = InsuranceDetail.objects.create(sub_category=isub, name='미감지담보')
        idet2.analysis_detail.add(self.old_leaf)
        ci2 = CustomerInsurance.objects.create(
            customer=self.customer, insurance_type=2, portfolio_type=1,
            name='미감지보험', company=-1)
        case2 = CustomerInsuranceDetail.objects.create(
            insurance=ci2, detail=idet2, assurance_amount=5_000_000,
            raw_name='미감지원문특약')
        flag2 = CoverageFlag.objects.create(
            owner=self.planner, customer=self.customer,
            analysis_detail=self.old_leaf, case=case2,
            raw_name_snapshot='미감지원문특약', company=-1, note='분류 이상')
        res = self.client_admin.post(self._resolve_url(flag2.id), {
            'action': 'accept', 'std_detail_id': self.new_leaf.id,
        }, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        # 사전 행은 생성되지 않음(파싱 룩업이 company<0 을 조회 안 하므로 죽은 행 방지)
        self.assertFalse(body['dict_created'])
        self.assertFalse(
            NormalizationDict.objects.filter(raw_name='미감지원문특약').exists())
        # 연결 정정은 그대로 수행
        self.assertEqual(
            list(idet2.analysis_detail.values_list('id', flat=True)),
            [self.new_leaf.id])
        self.assertEqual(body['relinked'], 1)
        flag2.refresh_from_db()
        self.assertEqual(flag2.status, CoverageFlag.STATUS_ACCEPTED)

    def test_F9_accept_wipes_all_prior_leaves(self):
        """카탈로그 행이 여러 leaf 에 연결돼 있어도 승인 후 정확히 [new_leaf] 하나만 남음."""
        from inpa.analysis.models import CoverageFlag
        from inpa.insurances.models import (
            CustomerInsurance, CustomerInsuranceDetail, InsuranceDetail,
        )
        isub = self.idet.sub_category
        # old_leaf + demo_leaf 둘 다에 연결된 카탈로그 행
        idet3 = InsuranceDetail.objects.create(sub_category=isub, name='이중연결담보')
        idet3.analysis_detail.add(self.old_leaf, self.demo_leaf)
        ci3 = CustomerInsurance.objects.create(
            customer=self.customer, insurance_type=2, portfolio_type=1,
            name='이중보험', company=2)
        case3 = CustomerInsuranceDetail.objects.create(
            insurance=ci3, detail=idet3, assurance_amount=3_000_000,
            raw_name='이중연결원문')
        flag3 = CoverageFlag.objects.create(
            owner=self.planner, customer=self.customer,
            analysis_detail=self.old_leaf, case=case3,
            raw_name_snapshot='이중연결원문', company=2)
        res = self.client_admin.post(self._resolve_url(flag3.id), {
            'action': 'accept', 'std_detail_id': self.new_leaf.id,
        }, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        # set([new]) 이므로 기존 2개 leaf 전부 치워지고 new_leaf 하나만
        self.assertEqual(
            list(idet3.analysis_detail.values_list('id', flat=True)),
            [self.new_leaf.id])

    def test_F10_accept_raw_name_over_120_warns_truncation(self):
        """원문이 120자를 넘으면 절단 경고가 응답 warnings 에 포함(파싱 미스 고지)."""
        from inpa.analysis.models import NormalizationDict
        long_raw = '초장문담보명' * 25  # 150자 > 120
        res = self.client_admin.post(self._resolve_url(self.flag.id), {
            'action': 'accept', 'std_detail_id': self.new_leaf.id,
            'raw_name': long_raw,
        }, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertTrue(any('120자' in w for w in body['warnings']))
        # 사전 행은 120자로 절단 저장
        norm = NormalizationDict.objects.get(std_detail=self.new_leaf, company=2)
        self.assertEqual(len(norm.raw_name), 120)

    def test_F11_accept_golden_set_mismatch_warns(self):
        """골든셋 앵커와 다른 leaf 로 승인하면 비차단 경고(트랜잭션 밖·전체 재채점 없음)."""
        from inpa.analysis.models import CoverageFlag
        # 골든셋 앵커: company=2, raw_name='상피내암진단비' → 기대 '유사암진단비'.
        # old_leaf 는 이름이 '일반암'이라 기대와 다름 → 경고가 떠야 한다.
        flag = CoverageFlag.objects.create(
            owner=self.planner, customer=self.customer,
            analysis_detail=self.old_leaf, raw_name_snapshot='상피내암진단비',
            company=2, note='골든셋 불일치 테스트')
        res = self.client_admin.post(self._resolve_url(flag.id), {
            'action': 'accept', 'std_detail_id': self.old_leaf.id,
        }, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertTrue(any('골든셋' in w and '유사암진단비' in w for w in body['warnings']))
        # 승인 응답은 전체 재채점을 하지 않는다(성능) — 정확도는 전용 카드에서 조회.
        self.assertNotIn('golden_accuracy', body)

    def test_F12_accept_golden_set_match_no_warning(self):
        """골든셋 기대와 같은 leaf 로 승인하면 골든셋 경고가 없다."""
        from inpa.analysis.models import AnalysisDetail, CoverageFlag
        # new_leaf 이름을 골든셋 기대값('유사암진단비')과 맞춘다.
        AnalysisDetail.objects.filter(pk=self.new_leaf.pk).update(name='유사암진단비')
        self.new_leaf.refresh_from_db()
        flag = CoverageFlag.objects.create(
            owner=self.planner, customer=self.customer,
            analysis_detail=self.old_leaf, raw_name_snapshot='상피내암진단비',
            company=2, note='골든셋 일치 테스트')
        res = self.client_admin.post(self._resolve_url(flag.id), {
            'action': 'accept', 'std_detail_id': self.new_leaf.id,
        }, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertFalse(any('골든셋' in w for w in body['warnings']))


# ─── M: 골든셋 정규화 정확도 기준선 (프리런치 리뷰 #18) ────────────────

class AdminNormalizationAccuracyTest(TestCase):
    """GET /admin/normalization/accuracy/ — admin 전용, 사실 수치 shape."""

    def setUp(self):
        from io import StringIO

        from django.core.management import call_command

        call_command('seed_normalization', stdout=StringIO())
        self.admin = _make_user('admin@inpa.kr', is_admin=True)
        self.client_admin = _auth_client(self.admin)
        self.planner = _make_user('planner@inpa.kr')
        self.client_planner = _auth_client(self.planner)

    def test_M1_admin_gets_accuracy_shape(self):
        from inpa.analysis.golden_eval import GOLDEN_SET_MIN_ACCURACY

        res = self.client_admin.get('/api/v1/admin/normalization/accuracy/')
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertIn('accuracy', body)
        self.assertIn('total', body)
        self.assertIn('passed', body)
        self.assertIn('anchor_total', body)
        self.assertIn('anchor_passed', body)
        self.assertEqual(body['exact_auto_mapped'], 174)
        self.assertEqual(body['safe_human_review'], 66)
        self.assertEqual(body['unsafe_auto_mapped'], 0)
        self.assertEqual(body['safe_decision_rate'], 1.0)
        self.assertEqual(body['evaluation_scope'], 'fallback_golden_set_only')
        self.assertIn('운영 OCR 정확도', body['evaluation_scope_note'])
        self.assertIn('sample_failures', body)
        self.assertEqual(body['min_accuracy'], GOLDEN_SET_MIN_ACCURACY)
        # 앵커는 100% 통과해야 한다(시드 DB 기준).
        self.assertEqual(body['anchor_passed'], body['anchor_total'])
        self.assertLessEqual(len(body['sample_failures']), 20)

    def test_M2_planner_forbidden(self):
        res = self.client_planner.get('/api/v1/admin/normalization/accuracy/')
        self.assertEqual(res.status_code, 403)


# ─── N: 공지사항 ─────────────────────────────────────────────────────

class AdminNoticeTest(TestCase):
    """N1-N2: 공지사항 admin 작성 + 설계사 노출 확인."""

    def setUp(self):
        self.admin = _make_user('admin@inpa.kr', is_admin=True)
        self.planner = _make_user('planner@test.kr', is_admin=False)
        self.client_admin = _auth_client(self.admin)
        self.client_planner = _auth_client(self.planner)

    def test_N1_published_notice_visible_to_planners(self):
        """N1: admin 작성(is_published=True) → 설계사 GET /board/notices/ 노출."""
        self.client_admin.post('/api/v1/admin/notices/', {
            'title': '공개 공지', 'body': '내용', 'is_published': True,
        }, format='json')
        res = self.client_planner.get('/api/v1/board/notices/')
        self.assertEqual(res.status_code, 200)
        titles = [n['title'] for n in res.json()]
        self.assertIn('공개 공지', titles)

    def test_N2_draft_notice_not_visible_to_planners(self):
        """N2: 임시저장(is_published=False) → 설계사 GET에 미노출."""
        self.client_admin.post('/api/v1/admin/notices/', {
            'title': '임시저장 공지', 'body': '내용', 'is_published': False,
        }, format='json')
        res = self.client_planner.get('/api/v1/board/notices/')
        self.assertEqual(res.status_code, 200)
        titles = [n['title'] for n in res.json()]
        self.assertNotIn('임시저장 공지', titles)


# ─── P: 요금제 설정 ─────────────────────────────────────────────────

class AdminPlanTest(TestCase):
    """P1: 요금제 한도 변경."""

    def setUp(self):
        self.admin = _make_user('admin@inpa.kr', is_admin=True)
        self.plan = _make_plan()
        self.client_admin = _auth_client(self.admin)

    def test_P1_plan_limit_update(self):
        """P1: PATCH /admin/settings/plans/:code/ → limit_ocr 변경."""
        res = self.client_admin.patch(
            f'/api/v1/admin/settings/plans/{self.plan.code}/',
            {'limit_ocr': 50},
            format='json',
        )
        self.assertEqual(res.status_code, 200)
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.limit_ocr, 50)


# ─── PV: 약관 버전 ──────────────────────────────────────────────────

class AdminPolicyVersionTest(TestCase):
    """PV1-PV3: 약관 버전 POST→201 후 GET 목록 확인 + 비admin 차단."""

    def setUp(self):
        self.admin = _make_user('admin@inpa.kr', is_admin=True)
        self.planner = _make_user('planner@test.kr', is_admin=False)
        self.client_admin = _auth_client(self.admin)
        self.client_planner = _auth_client(self.planner)

    def test_PV1_create_policy_version_201(self):
        """PV1: admin POST → 약관 버전 생성 201."""
        res = self.client_admin.post(
            '/api/v1/admin/settings/policy-versions/',
            {
                'policy_type': 'tos',
                'version': '2026-06-28',
                'effective_at': '2026-07-01T00:00:00Z',
                'requires_reconsent': False,
            },
            format='json',
        )
        self.assertEqual(res.status_code, 201, res.content)
        data = res.json()
        self.assertEqual(data['policy_type'], 'tos')
        self.assertEqual(data['version'], '2026-06-28')
        self.assertFalse(data['requires_reconsent'])
        self.assertIn('id', data)

    def test_PV2_list_shows_created(self):
        """PV2: POST 후 GET 목록에 생성된 버전 노출."""
        PolicyVersion.objects.create(
            policy_type='pp',
            version='v2.0',
            effective_at='2026-06-01T00:00:00Z',
            requires_reconsent=True,
        )
        res = self.client_admin.get('/api/v1/admin/settings/policy-versions/')
        self.assertEqual(res.status_code, 200)
        results = res.json()['results']
        self.assertTrue(len(results) >= 1)
        versions = [r['version'] for r in results]
        self.assertIn('v2.0', versions)
        # requires_reconsent 확인
        pp_entry = next(r for r in results if r['version'] == 'v2.0')
        self.assertTrue(pp_entry['requires_reconsent'])

    def test_PV3_non_admin_403(self):
        """PV3: 설계사(is_admin=False) → GET/POST 모두 403."""
        res_get = self.client_planner.get('/api/v1/admin/settings/policy-versions/')
        self.assertEqual(res_get.status_code, 403)

        res_post = self.client_planner.post(
            '/api/v1/admin/settings/policy-versions/',
            {'policy_type': 'tos', 'version': 'v1', 'effective_at': '2026-07-01T00:00:00Z'},
            format='json',
        )
        self.assertEqual(res_post.status_code, 403)


# ─── FF: 기능 플래그 ─────────────────────────────────────────────────

class AdminFeatureFlagsTest(TestCase):
    """FF1-FF2: 기능 플래그 GET(설정값 반영) + PATCH 미구현(405)."""

    def setUp(self):
        self.admin = _make_user('admin@inpa.kr', is_admin=True)
        self.planner = _make_user('planner@test.kr', is_admin=False)
        self.client_admin = _auth_client(self.admin)
        self.client_planner = _auth_client(self.planner)

    def test_FF1_get_returns_settings_values(self):
        """FF1: GET /admin/settings/flags/ → 200, 설정값 포함 응답."""
        from django.conf import settings as dj_settings
        res = self.client_admin.get('/api/v1/admin/settings/flags/')
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        # 필수 플래그 키 존재 확인
        for key in ['FREE_TIER_UNLIMITED', 'COMPARE_AI_ENABLED', 'COMPARE_PUBLISH_ENABLED',
                    'ANALYZE_MEDICAL_ENABLED', 'BOOKING_ENABLED', 'OCR_VERIFY_ENABLED']:
            self.assertIn(key, data, f"플래그 키 누락: {key}")
            # 값이 boolean임을 확인
            self.assertIsInstance(data[key], bool, f"{key} 값이 bool이 아님")
        # settings 실제값과 일치 확인
        self.assertEqual(data['FREE_TIER_UNLIMITED'], getattr(dj_settings, 'FREE_TIER_UNLIMITED', True))

    def test_FF2_non_admin_403(self):
        """FF2: 설계사(is_admin=False) → 403."""
        res = self.client_planner.get('/api/v1/admin/settings/flags/')
        self.assertEqual(res.status_code, 403)

    def test_FF3_patch_not_allowed(self):
        """FF3: PATCH /admin/settings/flags/ → 405 (env 우회 차단 컴플라이언스 원칙)."""
        res = self.client_admin.patch(
            '/api/v1/admin/settings/flags/',
            {'FREE_TIER_UNLIMITED': False},
            format='json',
        )
        self.assertEqual(res.status_code, 405)


# ─── Claude 호출당 비용·파싱 결과 계측 (프리런치 리뷰 #17) ────────────────────

class AdminClaudeCostTest(TestCase):
    """GET /api/v1/admin/claude-cost/?days= — IsAdmin 격리 + 집계 shape + 데모 제외."""

    def setUp(self):
        from inpa.billing.models import ClaudeApiLog

        self.ClaudeApiLog = ClaudeApiLog
        self.admin = _make_user('admin_cost@inpa.kr', is_admin=True)
        self.planner = _make_user('planner_cost@test.kr', is_admin=False)
        self.demo = _make_user('demo_cost@inpa.local', is_admin=False)
        self.client_admin = _auth_client(self.admin)
        self.client_planner = _auth_client(self.planner)

        # 성공 1건(설계사) — 매칭 3/미매칭 1, 회사코드 2
        ClaudeApiLog.objects.create(
            action='ocr_parse', model='claude-opus-4-8', user=self.planner,
            input_tokens=1000, output_tokens=200, cost_krw=Decimal('7000.00'),
            parse_outcome='success', carrier_code=2, matched_count=3, unmatched_count=1,
        )
        # 실패 1건(설계사) — timeout, 비용 0
        ClaudeApiLog.objects.create(
            action='ocr_parse', model='claude-opus-4-8', user=self.planner,
            parse_outcome='timeout',
        )
        # 공개 /d 경로 — user=None(데모 아님, 집계에 포함되어야 함)
        ClaudeApiLog.objects.create(
            action='self_diagnosis', model='claude-opus-4-8', user=None,
            input_tokens=500, cost_krw=Decimal('3500.00'),
            parse_outcome='success', carrier_code=2, matched_count=1, unmatched_count=0,
        )
        # 데모 계정 — 집계에서 제외되어야 함
        ClaudeApiLog.objects.create(
            action='ocr_parse', model='claude-opus-4-8', user=self.demo,
            input_tokens=999999, cost_krw=Decimal('99999.00'), parse_outcome='success',
        )

    def test_CC1_admin_gets_200_shape(self):
        """CC1: admin → 200 + 필수 키 shape."""
        res = self.client_admin.get('/api/v1/admin/claude-cost/?days=30')
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        for key in ('days', 'total_calls', 'total_cost_krw', 'cost_is_estimate',
                    'usd_krw_rate', 'success_rate', 'outcome_counts', 'by_action',
                    'daily', 'by_carrier'):
            self.assertIn(key, data, f'키 누락: {key}')
        self.assertTrue(data['cost_is_estimate'])

    def test_CC2_non_admin_403(self):
        """CC2: 설계사 → 403."""
        res = self.client_planner.get('/api/v1/admin/claude-cost/')
        self.assertEqual(res.status_code, 403)

    def test_CC3_demo_account_excluded_public_included(self):
        """CC3: @inpa.local 데모 제외, user=None(공개 /d) 은 포함 — 총 3건(성공2·실패1)."""
        res = self.client_admin.get('/api/v1/admin/claude-cost/?days=30')
        data = res.json()
        self.assertEqual(data['total_calls'], 3)
        self.assertEqual(data['total_cost_krw'], 10500.0)  # 7000 + 3500 (데모 99999 제외)

    def test_CC4_outcome_counts_and_success_rate(self):
        """CC4: outcome 분포(성공 2·timeout 1) + 성공률 계산."""
        res = self.client_admin.get('/api/v1/admin/claude-cost/?days=30')
        data = res.json()
        self.assertEqual(data['outcome_counts'].get('success'), 2)
        self.assertEqual(data['outcome_counts'].get('timeout'), 1)
        self.assertAlmostEqual(data['success_rate'], 66.7, places=1)

    def test_CC5_by_action_breakdown(self):
        """CC5: action별 호출수·비용 분해(데모 제외)."""
        res = self.client_admin.get('/api/v1/admin/claude-cost/?days=30')
        by_action = {row['action']: row for row in res.json()['by_action']}
        self.assertEqual(by_action['ocr_parse']['calls'], 2)
        self.assertEqual(by_action['self_diagnosis']['calls'], 1)

    def test_CC6_by_carrier_unmatched_rate(self):
        """CC6: carrier_code=2 매칭 4(3+1)/미매칭 1 → 미매칭율 = 1/5*100 = 20.0%."""
        res = self.client_admin.get('/api/v1/admin/claude-cost/?days=30')
        rows = res.json()['by_carrier']
        row = next(r for r in rows if r['carrier_code'] == 2)
        self.assertEqual(row['matched'], 4)
        self.assertEqual(row['unmatched'], 1)
        self.assertEqual(row['unmatched_rate'], 20.0)

    def test_CC7_days_zero_means_all_time(self):
        """CC7: days=0 → 기간 제한 없이 전체(데모 제외 3건)."""
        res = self.client_admin.get('/api/v1/admin/claude-cost/?days=0')
        self.assertEqual(res.json()['total_calls'], 3)

    def test_CC8_days_only_zero_is_all_time_and_other_values_are_bounded(self):
        self.assertEqual(
            self.client_admin.get(
                '/api/v1/admin/claude-cost/?days=-9').json()['days'], 1)
        self.assertEqual(
            self.client_admin.get(
                '/api/v1/admin/claude-cost/?days=999').json()['days'], 365)
        self.assertEqual(
            self.client_admin.get(
                '/api/v1/admin/claude-cost/?days=invalid').json()['days'], 30)


class AdminInsuranceReviewMetricsTest(TestCase):
    """운영 지표는 실제 worker snapshot과 PII 없는 원장만 집계한다."""

    def setUp(self):
        from inpa.billing.models import ClaudeApiLog
        from inpa.customers.consent_texts import CONSENT_TEXTS_VERSION
        from inpa.insurances.models import (
            InsuranceExtractionJob,
            InsuranceExtractionResult,
        )

        self.ClaudeApiLog = ClaudeApiLog
        self.Job = InsuranceExtractionJob
        self.Result = InsuranceExtractionResult
        self.admin = _make_user('review_metrics_admin@inpa.kr', is_admin=True)
        self.planner = _make_user('review_metrics_planner@test.kr')
        self.demo = _make_user('review_metrics_demo@inpa.local')
        self.client_admin = _auth_client(self.admin)
        self.now = timezone.now()
        self.sentinel = 'PII_SENTINEL_CUSTOMER_POLICY_RAW_PATH_7788'
        self.enum_sentinel = 'PII_ENUM_7788'
        self.customer = Customer.objects.create(
            owner=self.planner,
            name=self.sentinel,
            mobile_phone_number='010-9999-7788',
            consent_overseas_at=self.now,
        )
        self.demo_customer = Customer.objects.create(
            owner=self.demo,
            name='DEMO_SENTINEL_NAME',
            consent_overseas_at=self.now,
        )
        for customer in (self.customer, self.demo_customer):
            ConsentLog.objects.create(
                customer=customer,
                scope=ConsentLog.SCOPE_OVERSEAS_MEDICAL,
                subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
                doc_version=CONSENT_TEXTS_VERSION,
            )

        self.confirmed = self._run_worker_job(
            number=1, carrier_code=7,
            input_tokens=11, output_tokens=22,
            cache_read=33, cache_creation=44,
        )
        self._set_timing(
            self.confirmed,
            status='confirmed', created_ms=-10_000, started_ms=-9_000,
            result_ms=-5_000, completed_ms=-5_000, confirmed_ms=0,
            attempt_count=2, lease_expired_count=1,
            planner_edit_count=3, confirmed_coverage_count=1,
        )
        self.failed = self._run_worker_job(
            number=2, carrier_code=7, rows=False)
        self._set_timing(
            self.failed,
            status='failed', created_ms=-20_000, started_ms=-18_000,
            result_ms=-11_000, completed_ms=-10_000,
        )
        self.queued = self._make_worker_job(number=3)
        self.Job.objects.filter(pk=self.queued.pk).update(
            created_at=self._at(-3_000))
        self.queued.refresh_from_db()
        self.invalid_timing = self._run_worker_job(
            number=4, carrier_code=8)
        self._set_timing(
            self.invalid_timing,
            status='confirmed', created_ms=-4_000, started_ms=-5_000,
            result_ms=-2_000, completed_ms=-2_000, confirmed_ms=-3_000,
        )
        demo_job = self._run_worker_job(
            number=5, owner=self.demo, customer=self.demo_customer,
            carrier_code=9, input_tokens=999, output_tokens=999)
        self._set_timing(
            demo_job,
            status='confirmed', created_ms=-10_000, started_ms=-9_000,
            result_ms=-5_000, completed_ms=-5_000, confirmed_ms=0,
        )

        planner_logs = self.ClaudeApiLog.objects.filter(user=self.planner)
        planner_logs.update(cost_krw=Decimal('0.00'))
        planner_logs.filter(input_tokens=11).update(cost_krw=Decimal('10.00'))
        self.Result.objects.filter(job=self.confirmed).update(
            estimated_cost_krw=Decimal('99999.00'),
            structured_payload={
                'raw_name': self.sentinel,
                'file_path': f'/private/{self.sentinel}.pdf',
            },
        )
        summary = self.confirmed.validation_summary
        summary[self.sentinel] = self.sentinel
        self.Job.objects.filter(pk=self.confirmed.pk).update(
            safe_display_name=f'{self.sentinel}.pdf',
            draft_payload={
                'policy': {'product_name': self.sentinel},
                'coverage_rows': [{'raw_name': self.sentinel}],
            },
            validation_summary=summary,
        )

    def _at(self, milliseconds):
        return self.now + timedelta(milliseconds=milliseconds)

    def _make_worker_job(self, *, number, owner=None, customer=None):
        from inpa.insurances.import_contract import extracted_source_readability
        from inpa.insurances.test_import_worker import _extracted

        owner = owner or self.planner
        customer = customer or self.customer
        extracted = _extracted()
        job = self.Job.objects.create(
            owner=owner,
            customer=customer,
            intent='add',
            portfolio_type=1,
            status='queued',
            file_sha256=f'{number:064x}',
            file_size=extracted.file_size,
            page_count=extracted.page_count,
            safe_display_name='policy.pdf',
            source_storage_key=(
                f'insurance-imports/{owner.pk}/{customer.pk}/'
                f'{number}/source.pdf'),
            source_expires_at=self.now + timedelta(hours=24),
            validation_summary={
                '_system': {
                    'source_readability': extracted_source_readability(
                        extracted),
                },
            },
        )
        return job

    def _run_worker_job(
            self, *, number, owner=None, customer=None, carrier_code=None,
            rows=True, input_tokens=0, output_tokens=0,
            cache_read=0, cache_creation=0):
        from unittest import mock

        from inpa.insurances.import_claude import ExtractionResult
        from inpa.insurances.tasks import run_insurance_import
        from inpa.insurances.test_import_worker import (
            _extracted,
            _provider_payload,
        )

        job = self._make_worker_job(
            number=number, owner=owner, customer=customer)
        provider = ExtractionResult(
            payload=_provider_payload(
                company_code=carrier_code, rows=rows),
            model_id='claude-opus-4-8',
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read,
            cache_creation_input_tokens=cache_creation,
            latency_ms=123,
        )
        with mock.patch(
                'inpa.insurances.tasks._extract_job_pdf',
                return_value=_extracted()), mock.patch(
                    'inpa.insurances.tasks.claude_extract',
                    return_value=provider), mock.patch(
                        'inpa.insurances.tasks.delete_source'):
            run_insurance_import(str(job.pk))
        job.refresh_from_db()
        return job

    def _set_timing(
            self, job, *, status, created_ms, started_ms,
            result_ms, completed_ms, confirmed_ms=None,
            attempt_count=None, lease_expired_count=None,
            planner_edit_count=None, confirmed_coverage_count=None):
        update = {
            'status': status,
            'created_at': self._at(created_ms),
            'started_at': self._at(started_ms),
            'completed_at': self._at(completed_ms),
            'confirmed_at': (
                self._at(confirmed_ms) if confirmed_ms is not None else None),
        }
        for key, value in (
                ('attempt_count', attempt_count),
                ('lease_expired_count', lease_expired_count),
                ('planner_edit_count', planner_edit_count),
                ('confirmed_coverage_count', confirmed_coverage_count)):
            if value is not None:
                update[key] = value
        self.Job.objects.filter(pk=job.pk).update(**update)
        result = self.Result.objects.get(job=job, provider='claude')
        self.Result.objects.filter(pk=result.pk).update(
            created_at=self._at(result_ms))
        job.refresh_from_db()

    def test_metrics_use_nearest_rank_explicit_denominators_and_initial_snapshot(self):
        from unittest import mock

        with mock.patch(
                'inpa.admin_console.views.timezone.now',
                return_value=self.now):
            data = self.client_admin.get(
                '/api/v1/admin/claude-cost/?days=30').json()

        self.assertEqual(data['total_cost_krw'], 10.0)
        self.assertEqual(data['total_tokens'], {
            'input': 11,
            'output': 22,
            'cache_read': 33,
            'cache_creation': 44,
        })
        review = data['insurance_review']
        self.assertEqual(review['job_count'], 4)
        self.assertEqual(
            review['status_counts'],
            {'queued': 1, 'confirmed': 2, 'failed': 1})
        self.assertEqual(review['queue_wait_ms'], {
            'sample_count': 2,
            'invalid_timing_count': 1,
            'p50': 1000,
            'p95': 2000,
        })
        self.assertEqual(review['current_queue_wait_ms']['sample_count'], 1)
        self.assertEqual(review['current_queue_wait_ms']['p50'], 3000)
        self.assertEqual(review['processing_ms'], {
            'sample_count': 3,
            'invalid_timing_count': 0,
            'p50': 4000,
            'p95': 7000,
        })
        self.assertEqual(review['review_ms_proxy'], {
            'sample_count': 1,
            'invalid_timing_count': 1,
            'p50': 5000,
            'p95': 5000,
        })
        self.assertEqual(review['attempts'], {
            'job_count': 4,
            'total': 4,
            'retry_attempts': 1,
            'retry_jobs': 1,
            'retry_job_rate': 25.0,
        })
        self.assertEqual(review['leases'], {
            'job_count': 4,
            'expired': 1,
            'expired_jobs': 1,
            'expired_job_rate': 25.0,
        })
        validation = review['validation']
        self.assertEqual(validation['initial_metrics_sample_count'], 3)
        self.assertEqual(validation['no_provider_job_count'], 1)
        self.assertEqual(validation['pending_provider_metrics_count'], 0)
        self.assertEqual(validation['invalid_initial_metrics_count'], 0)
        self.assertEqual(validation['provider_rows'], 2)
        self.assertEqual(validation['row_count'], 2)
        self.assertEqual(validation['state_counts']['invalid'], 2)
        self.assertEqual(validation['detected_candidates'], 2)
        self.assertEqual(validation['assigned'], 0)
        self.assertEqual(validation['unmatched'], 2)
        self.assertEqual(validation['confirmed_coverages'], 1)
        self.assertEqual(review['corrections'], {
            'confirmed_jobs': 2,
            'jobs_with_edits': 1,
            'job_correction_rate': 50.0,
            'edit_actions': 3,
        })
        self.assertEqual(review['failures'], {
            'provider_calls': 3,
            'failed_calls': 1,
            'failure_rate': 33.3,
            'zero_provider_rows': 1,
        })
        carrier7 = next(
            row for row in review['by_carrier']
            if row['carrier_code'] == 7)
        self.assertEqual(carrier7, {
            'carrier_code': 7,
            'sample_count': 2,
            'assigned': 0,
            'unmatched': 1,
            'unmatched_rate': 100.0,
        })

    def test_missing_snapshot_denominators_distinguish_no_provider_pending_and_malformed(self):
        from unittest import mock

        from inpa.insurances.import_contract import PDFImportError
        from inpa.insurances.tasks import (
            _reserve_provider_call,
            claim_import,
            run_insurance_import,
        )

        pre_provider = self._make_worker_job(number=20)
        with mock.patch(
                'inpa.insurances.tasks._extract_job_pdf',
                side_effect=PDFImportError('PDF_PARSE_RESOURCE_LIMIT')), \
                mock.patch('inpa.insurances.tasks.delete_source'):
            run_insurance_import(str(pre_provider.pk))

        pending = self._make_worker_job(number=21)
        pending_claim = claim_import(pending.pk)
        _reserve_provider_call(pending_claim)

        malformed = self._make_worker_job(number=22)
        self.Job.objects.filter(pk=malformed.pk).update(
            status='failed',
            validation_summary={
                '_system': {
                    'provider_started': True,
                    'initial_metrics': {'schema_version': self.sentinel},
                },
            },
        )

        data = self.client_admin.get(
            '/api/v1/admin/claude-cost/?days=30').json()
        validation = data['insurance_review']['validation']
        self.assertEqual(validation['no_provider_job_count'], 2)
        self.assertEqual(validation['pending_provider_metrics_count'], 1)
        self.assertEqual(validation['invalid_initial_metrics_count'], 1)

    def test_structurally_valid_snapshot_without_provider_start_is_not_a_sample(self):
        import copy

        fake = self._make_worker_job(number=23)
        source_metrics = copy.deepcopy(
            self.confirmed.validation_summary['_system']['initial_metrics'])
        self.Job.objects.filter(pk=fake.pk).update(
            validation_summary={
                '_system': {
                    'provider_started': False,
                    'initial_metrics': source_metrics,
                },
            },
        )
        self.Result.objects.create(
            job=fake,
            provider='claude',
            model_id='forged-model',
            outcome='review_required',
        )

        data = self.client_admin.get(
            '/api/v1/admin/claude-cost/?days=30').json()
        validation = data['insurance_review']['validation']
        self.assertEqual(validation['initial_metrics_sample_count'], 3)
        self.assertEqual(validation['no_provider_job_count'], 2)
        self.assertEqual(validation['pending_provider_metrics_count'], 0)
        self.assertEqual(validation['invalid_initial_metrics_count'], 0)

    def test_provider_snapshot_with_inconsistent_terminal_result_is_invalid(self):
        import copy

        fake = self._make_worker_job(number=24)
        source_metrics = copy.deepcopy(
            self.confirmed.validation_summary['_system']['initial_metrics'])
        self.Job.objects.filter(pk=fake.pk).update(
            status='failed',
            validation_summary={
                '_system': {
                    'provider_started': True,
                    'initial_metrics': source_metrics,
                },
            },
        )
        self.Result.objects.create(
            job=fake,
            provider='claude',
            model_id='inconsistent-model',
            outcome='review_required',
        )

        data = self.client_admin.get(
            '/api/v1/admin/claude-cost/?days=30').json()
        validation = data['insurance_review']['validation']
        self.assertEqual(validation['initial_metrics_sample_count'], 3)
        self.assertEqual(validation['no_provider_job_count'], 1)
        self.assertEqual(validation['pending_provider_metrics_count'], 0)
        self.assertEqual(validation['invalid_initial_metrics_count'], 1)

    def test_processing_percentiles_exclude_canceled_and_superseded_jobs(self):
        for number, status in ((30, 'canceled'), (31, 'superseded')):
            job = self._run_worker_job(number=number, carrier_code=7)
            self._set_timing(
                job,
                status=status,
                created_ms=-100_000,
                started_ms=-90_000,
                result_ms=-10_000,
                completed_ms=-10_000,
            )

        data = self.client_admin.get(
            '/api/v1/admin/claude-cost/?days=30').json()
        self.assertEqual(
            data['insurance_review']['processing_ms'], {
                'sample_count': 3,
                'invalid_timing_count': 0,
                'p50': 4000,
                'p95': 7000,
            },
        )

    def test_metrics_response_recursively_excludes_raw_payload_and_pii_sentinels(self):
        import json

        self.ClaudeApiLog.objects.create(
            action=self.enum_sentinel,
            model='safe-model',
            user=self.planner,
            parse_outcome=self.enum_sentinel,
            carrier_code=199,
        )
        self.Job.objects.filter(pk=self.queued.pk).update(
            status=self.enum_sentinel)

        data = self.client_admin.get(
            '/api/v1/admin/claude-cost/?days=30').json()
        forbidden_keys = {
            'draft_payload', 'structured_payload', 'masked_lines',
            'validation_summary', 'safe_display_name', 'raw_name',
            'product_name', 'customer_name', 'email', 'file_path',
        }

        def walk(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    self.assertNotIn(key, forbidden_keys)
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(data)
        rendered = json.dumps(data, ensure_ascii=False)
        self.assertNotIn(self.sentinel, rendered)
        self.assertNotIn(self.enum_sentinel, rendered)
        self.assertNotIn('010-9999-7788', rendered)
        self.assertNotIn('DEMO_SENTINEL_NAME', rendered)
        self.assertIn('other', data['outcome_counts'])
        self.assertIn(
            'other', data['insurance_review']['status_counts'])
        self.assertIn('other', {
            row['action'] for row in data['by_action']})
        self.assertNotIn(199, {
            row['carrier_code'] for row in data['by_carrier']})


@override_settings(
    INSURANCE_REVIEW_GATE_ENABLED=False,
    INSURANCE_SOURCE_RETENTION_HOURS=24,
)
class AdminInsuranceImportSettingsTest(TestCase):
    def setUp(self):
        from inpa.insurances.models import InsuranceImportRuntimeConfig

        self.Config = InsuranceImportRuntimeConfig
        self.admin = _make_user('import_settings_admin@inpa.kr', is_admin=True)
        self.planner = _make_user('import_settings_planner@test.kr')
        self.client_admin = _auth_client(self.admin)
        self.client_planner = _auth_client(self.planner)
        self.Config.objects.update_or_create(
            pk=1,
            defaults={
                'per_owner_concurrency': 2,
                'global_concurrency': 4,
                'force_manual_carrier_codes': [],
            },
        )
        self.url = '/api/v1/admin/settings/insurance-import/'

    def test_admin_gets_runtime_and_read_only_deployment_values(self):
        response = self.client_admin.get(self.url)

        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data['runtime']['per_owner_concurrency'], 2)
        self.assertEqual(data['runtime']['global_concurrency'], 4)
        self.assertEqual(data['runtime']['force_manual_carrier_codes'], [])
        self.assertEqual(data['deployment'], {
            'insurance_review_gate_enabled': False,
            'source_retention_hours': 24,
        })

    def test_get_sanitizes_corrupt_runtime_json_at_response_boundary(self):
        sentinel = 'PII_RUNTIME_CONFIG_7788'
        self.Config.objects.filter(pk=1).update(
            force_manual_carrier_codes=[
                1, 0, 1, True, 9999, sentinel, {'raw': sentinel},
            ],
        )

        response = self.client_admin.get(self.url)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            response.json()['runtime']['force_manual_carrier_codes'], [0, 1])
        self.assertNotIn(sentinel, str(response.json()))

    def test_non_admin_cannot_read_or_patch(self):
        self.assertEqual(self.client_planner.get(self.url).status_code, 403)
        self.assertEqual(
            self.client_planner.patch(
                self.url, {'global_concurrency': 5}, format='json').status_code,
            403,
        )

    def test_patch_validates_allowlist_exact_types_bounds_and_relationship(self):
        invalid_payloads = (
            {'per_owner_concurrency': True},
            {'per_owner_concurrency': 0},
            {'global_concurrency': 101},
            {'per_owner_concurrency': 5, 'global_concurrency': 4},
            {'force_manual_carrier_codes': [9999]},
            {'force_manual_carrier_codes': '0'},
            {'deployment': {'insurance_review_gate_enabled': True}},
            {'insurance_review_gate_enabled': True},
            {'source_retention_hours': 48},
            {'unknown': 1},
        )

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                response = self.client_admin.patch(
                    self.url, payload, format='json')
                self.assertEqual(response.status_code, 400, response.content)

        config = self.Config.objects.get(pk=1)
        self.assertEqual(
            (config.per_owner_concurrency, config.global_concurrency,
             config.force_manual_carrier_codes),
            (2, 4, []),
        )

    def test_patch_deduplicates_sorts_and_updates_all_fields_atomically(self):
        response = self.client_admin.patch(self.url, {
            'per_owner_concurrency': 3,
            'global_concurrency': 6,
            'force_manual_carrier_codes': [1, 0, 1],
        }, format='json')

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['runtime'], {
            'per_owner_concurrency': 3,
            'global_concurrency': 6,
            'force_manual_carrier_codes': [0, 1],
            'updated_at': response.json()['runtime']['updated_at'],
        })
        config = self.Config.objects.get(pk=1)
        self.assertEqual(
            (config.per_owner_concurrency, config.global_concurrency,
             config.force_manual_carrier_codes),
            (3, 6, [0, 1]),
        )

    def test_claimed_attempt_keeps_snapshot_and_next_claim_reads_patch(self):
        from inpa.insurances.models import InsuranceExtractionJob
        from inpa.insurances.tasks import claim_import

        customer = Customer.objects.create(
            owner=self.planner, name='설정 테스트 고객')

        def make_job(number):
            return InsuranceExtractionJob.objects.create(
                owner=self.planner,
                customer=customer,
                intent='add',
                portfolio_type=1,
                status='queued',
                file_sha256=f'{number:064x}',
                file_size=100,
                safe_display_name='policy.pdf',
            )

        first_job = make_job(101)
        second_job = make_job(102)
        first_claim = claim_import(first_job.pk)

        response = self.client_admin.patch(
            self.url,
            {'force_manual_carrier_codes': [0]},
            format='json',
        )
        second_claim = claim_import(second_job.pk)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(first_claim.force_manual_carrier_codes, ())
        self.assertEqual(second_claim.force_manual_carrier_codes, (0,))
        first_job.refresh_from_db()
        self.assertEqual(first_job.attempt_uuid, first_claim.attempt_uuid)
        self.assertEqual(first_job.status, 'extracting')


# ─── AF: 활성화 퍼널 (spec 2026-07-08, 프리런치 #16) ─────────────────────

class AdminActivationFunnelTest(TestCase):
    """GET /api/v1/admin/activation-funnel/?days= — 코호트 퍼널 + UTM 분해 + 7일 활성화 창."""

    def setUp(self):
        self.admin = _make_user('admin_funnel@inpa.kr', is_admin=True)
        self.planner = _make_user('planner_funnel@test.kr', is_admin=False)
        # admin/planner 본인도 User라 코호트에 잡힌다 — 테스트 코호트(a/b/c) 오염 방지 위해
        # 아주 예전 가입으로 백데이팅(days 윈도우 어떤 값을 써도 절대 안 잡히게).
        far_past = timezone.now() - timedelta(days=3650)
        User.objects.filter(pk__in=[self.admin.pk, self.planner.pk]).update(date_joined=far_past)
        self.client_admin = _auth_client(self.admin)
        self.client_planner = _auth_client(self.planner)

        # user_a: 10일 전 가입, 인증, 6일째 활성화 조건 충족(분석·공유 둘 다 창 안) → activates.
        self.user_a = self._cohort_user(
            'a@test.com', signup_days_ago=10, verified=True,
            analysis_offset_days=2, share_offset_days=6, utm_source='naver')
        # user_b: 10일 전 가입, 인증, 분석은 창 안(2일)인데 공유가 8일 뒤(창 밖) → 활성화 안 됨.
        self.user_b = self._cohort_user(
            'b@test.com', signup_days_ago=10, verified=True,
            analysis_offset_days=2, share_offset_days=8, utm_source='')
        # user_c: 5일 전 가입, 미인증, 고객·분석·공유 전부 없음.
        self.user_c = self._cohort_user(
            'c@test.com', signup_days_ago=5, verified=False, utm_source='google')
        # 데모 계정 — 뭘 다 갖춰도 코호트에서 완전 제외돼야 함.
        self.demo = self._cohort_user(
            'demo_funnel@inpa.local', signup_days_ago=1, verified=True,
            analysis_offset_days=0, share_offset_days=0, utm_source='naver')

    def _cohort_user(self, email, signup_days_ago, verified=False,
                     analysis_offset_days=None, share_offset_days=None, utm_source=''):
        user = User.objects.create_user(email=email, password='inpaPass123!')
        user.is_active = True
        user.save(update_fields=['is_active'])
        joined = timezone.now() - timedelta(days=signup_days_ago)
        User.objects.filter(pk=user.pk).update(date_joined=joined)
        Profile.objects.create(
            user=user, email_verified_at=(joined if verified else None), utm_source=utm_source)

        if analysis_offset_days is not None or share_offset_days is not None:
            cust = Customer.objects.create(owner=user, name=f'고객-{email}')
            Customer.objects.filter(pk=cust.pk).update(
                created_at=joined + timedelta(days=1))
            if share_offset_days is not None:
                # 첫 공유 = 불변 NorthStarEvent.SHARE_CREATED(sender=설계사) 최초 시각 기준.
                from inpa.analytics.models import NorthStarEvent
                ev = NorthStarEvent.objects.create(
                    event_type=NorthStarEvent.SHARE_CREATED, sender=user, customer=cust)
                NorthStarEvent.objects.filter(pk=ev.pk).update(
                    created_at=joined + timedelta(days=share_offset_days))
            if analysis_offset_days is not None:
                ins = CustomerInsurance.objects.create(customer=cust, portfolio_type=1, name='암보험')
                CustomerInsurance.objects.filter(pk=ins.pk).update(
                    created_at=joined + timedelta(days=analysis_offset_days))
        return user

    def test_AF1_non_admin_403_anon_401(self):
        """AF1: 설계사 → 403, 비인증 → 401."""
        self.assertEqual(
            self.client_planner.get('/api/v1/admin/activation-funnel/').status_code, 403)
        self.assertEqual(
            APIClient().get('/api/v1/admin/activation-funnel/').status_code, 401)

    def test_AF2_demo_account_excluded_from_cohort(self):
        """AF2: @inpa.local은 무엇을 갖춰도 코호트에서 완전 제외(가입수에도 안 잡힘)."""
        res = self.client_admin.get('/api/v1/admin/activation-funnel/?days=30')
        data = res.json()
        self.assertEqual(data['signup_count'], 3)  # a, b, c만 — demo 제외
        sources = {row['source'] for row in data['utm_sources']}
        # demo 의 naver 유입이 섞였다면 naver signups가 2가 됨 — 1이어야 함(=a만).
        naver = next(r for r in data['utm_sources'] if r['source'] == 'naver')
        self.assertEqual(naver['signups'], 1)

    def test_AF3_step_counts_and_conversion_rates(self):
        """AF3: 단계별 인원 + 직전 단계 대비 전환율(%) — a·b만 인증·고객·분석·공유 보유."""
        res = self.client_admin.get('/api/v1/admin/activation-funnel/?days=30')
        data = res.json()
        by_step = {s['step']: s for s in data['steps']}
        self.assertEqual(by_step['signup']['count'], 3)
        self.assertEqual(by_step['verified']['count'], 2)
        self.assertEqual(by_step['first_customer']['count'], 2)
        self.assertEqual(by_step['first_analysis']['count'], 2)
        self.assertEqual(by_step['first_share']['count'], 2)
        self.assertAlmostEqual(by_step['verified']['conversion_rate'], 66.7, places=1)
        self.assertEqual(by_step['first_customer']['conversion_rate'], 100.0)

    def test_AF4_activation_7day_boundary(self):
        """AF4: 6일째 첫분석+공유 완료(둘 다 창 안) → 활성. 8일째 공유는 창 밖 → 비활성."""
        res = self.client_admin.get('/api/v1/admin/activation-funnel/?days=30')
        data = res.json()
        by_step = {s['step']: s for s in data['steps']}
        self.assertEqual(by_step['activated']['count'], 1)  # user_a만
        self.assertEqual(data['avg_days_to_activation'], 6.0)

    def test_AF4b_activation_exactly_7days_is_inclusive(self):
        """AF4b: 정확히 7일째 분석·공유 완료도 활성(<= 창, 경계 포함)."""
        self._cohort_user(
            'edge7@test.com', signup_days_ago=10, verified=True,
            analysis_offset_days=7, share_offset_days=7, utm_source='edge')
        res = self.client_admin.get('/api/v1/admin/activation-funnel/?days=30')
        by_step = {s['step']: s for s in res.json()['steps']}
        self.assertEqual(by_step['activated']['count'], 2)  # user_a + edge7

    def test_AF4c_activation_share_uses_immutable_event_not_share_sent_at(self):
        """AF4c(리뷰 blocker 회귀): 공유 재발급으로 share_sent_at 이 나중 시각으로 덮여도
        첫 공유는 불변 SHARE_CREATED 최초 시각을 쓰므로 활성화가 뒤집히지 않는다."""
        from inpa.customers.models import Customer as C
        cust = C.objects.filter(owner=self.user_a).first()
        # 20일 뒤(창 밖)로 share_sent_at 을 덮어써도 activated 는 여전히 1(user_a).
        C.objects.filter(pk=cust.pk).update(share_sent_at=timezone.now())
        res = self.client_admin.get('/api/v1/admin/activation-funnel/?days=30')
        by_step = {s['step']: s for s in res.json()['steps']}
        self.assertEqual(by_step['activated']['count'], 1)

    def test_AF5_utm_breakdown(self):
        """AF5: utm_source별 가입·활성화 — 빈 값은 'direct'로 집계."""
        res = self.client_admin.get('/api/v1/admin/activation-funnel/?days=30')
        rows = {r['source']: r for r in res.json()['utm_sources']}
        self.assertEqual(rows['naver']['signups'], 1)
        self.assertEqual(rows['naver']['activated'], 1)
        self.assertEqual(rows['direct']['signups'], 1)  # user_b (utm_source='')
        self.assertEqual(rows['direct']['activated'], 0)
        self.assertEqual(rows['google']['signups'], 1)  # user_c
        self.assertEqual(rows['google']['activated'], 0)

    def test_AF6_no_judgment_words(self):
        """AF6: 응답 키/문자열에 판정어 없음 — 사실 카운트·비율만(§6)."""
        res = self.client_admin.get('/api/v1/admin/activation-funnel/?days=30')
        data = res.json()
        judgment_words = ['위험', '낮음', '부족', '경고', '주의', 'bad', 'risk', 'low']
        response_str = str(data).lower()
        for word in judgment_words:
            self.assertNotIn(word.lower(), response_str, f"응답에 판정어 '{word}' 발견")

    def test_AF7_days_window_narrows_cohort(self):
        """AF7: days 창을 좁히면(3일) 10일 전 가입한 a·b는 코호트에서 빠진다."""
        res = self.client_admin.get('/api/v1/admin/activation-funnel/?days=3')
        data = res.json()
        self.assertEqual(data['signup_count'], 0)  # a·b(10일 전)·c(5일 전) 전부 창 밖


# ─── FIX 1: 관리자 액션 알림 라우팅 (EXPIRY_SOON 오분류 방지) ──────────

class AdminNotificationRoutingTest(TestCase):
    """FIX 1: 주문 상태·문의 답변·신고 결과·요금제 변경 알림이 '만기 임박'(EXPIRY_SOON,
    일정 배지)으로 잘못 라우팅되지 않고 각자의 올바른 버킷으로 가는지."""

    def setUp(self):
        self.admin = _make_user('admin@inpa.kr', is_admin=True)
        self.planner = _make_user('planner@test.kr', is_admin=False)
        self.client_admin = _auth_client(self.admin)

    def test_inquiry_reply_uses_inquiry_answered(self):
        """문의 답변 알림 = INQUIRY_ANSWERED(게시판 버킷), EXPIRY_SOON 아님."""
        from inpa.notifications.models import NotifType
        inquiry = Inquiry.objects.create(
            owner=self.planner, category='bug', title='버그', body='내용')
        res = self.client_admin.post(
            f'/api/v1/admin/inquiries/{inquiry.id}/reply/',
            {'body': '확인했습니다.'}, format='json')
        self.assertEqual(res.status_code, 201)
        notif = Notification.objects.filter(owner=self.planner).latest('created_at')
        self.assertEqual(notif.notif_type, NotifType.INQUIRY_ANSWERED)

    def test_order_status_uses_promotion_status(self):
        """주문 상태 알림 = PROMOTION_STATUS(판촉물 버킷), 제목에 em-dash 없음."""
        from inpa.notifications.models import NotifType
        sample = _make_sample()
        order = PromotionOrder.objects.create(
            owner=self.planner, sample=sample, form_response={'quantity': 100})
        res = self.client_admin.patch(
            f'/api/v1/admin/orders/{order.id}/status/',
            {'status': 'reviewing', 'admin_note': '검토 중'}, format='json')
        self.assertEqual(res.status_code, 200)
        notif = Notification.objects.filter(owner=self.planner).latest('created_at')
        self.assertEqual(notif.notif_type, NotifType.PROMOTION_STATUS)
        self.assertNotIn('—', notif.title)  # em-dash(U+2014) 금지

    def test_report_result_routes_to_board_bucket(self):
        """신고 처리 결과 알림은 게시판 버킷, EXPIRY_SOON 아님."""
        from inpa.notifications.models import NotifType, BOARD_NOTIF_TYPES
        post = Post.objects.create(author=self.planner, body='글')
        report = Report.objects.create(
            reporter=self.planner, content_type=Report.CONTENT_POST,
            object_id=post.pk, reason=Report.REASON_SPAM)
        res = self.client_admin.patch(
            f'/api/v1/admin/reports/{report.id}/action/',
            {'action': 'resolved'}, format='json')
        self.assertEqual(res.status_code, 200)
        notif = Notification.objects.filter(owner=self.planner).latest('created_at')
        self.assertNotEqual(notif.notif_type, NotifType.EXPIRY_SOON)
        self.assertIn(notif.notif_type, BOARD_NOTIF_TYPES)

    def test_plan_change_not_expiry_soon(self):
        """요금제 변경 알림은 EXPIRY_SOON(일정 버킷) 재사용 금지."""
        from inpa.notifications.models import NotifType
        _make_plan('plus', 'Plus', 19900)
        res = self.client_admin.patch(
            f'/api/v1/admin/users/{self.planner.id}/subscription/',
            {'plan_code': 'plus'}, format='json')
        self.assertEqual(res.status_code, 200)
        notif = Notification.objects.filter(owner=self.planner).latest('created_at')
        self.assertNotEqual(notif.notif_type, NotifType.EXPIRY_SOON)


# ─── FIX 2: 대시보드 '오늘' 카운트 KST 기준(§7) ─────────────────────────

class AdminDashboardKstTest(TestCase):
    """FIX 2: today_new_users 는 localdate()(KST) 로 버킷팅 — UTC/KST 경계일에
    date.today()(UTC)를 쓰면 카운트가 빠지던 문제 회귀 방지."""

    def setUp(self):
        self.admin = _make_user('admin@inpa.kr', is_admin=True)
        self.client_admin = _auth_client(self.admin)

    def test_today_count_uses_kst_localdate(self):
        from datetime import datetime, timezone as dt_timezone
        from unittest import mock

        # 2026-07-13 20:00 UTC = 2026-07-14 05:00 KST → UTC 날짜와 KST 날짜가 다른 순간.
        frozen = datetime(2026, 7, 13, 20, 0, 0, tzinfo=dt_timezone.utc)
        planner = _make_user('boundary@test.kr')
        # 경계 유저는 그 순간 가입(KST 날짜 = 2026-07-14).
        User.objects.filter(pk=planner.pk).update(date_joined=frozen)
        # admin 은 오늘 카운트에 섞이지 않도록 40일 전으로.
        User.objects.filter(pk=self.admin.pk).update(
            date_joined=frozen - timedelta(days=40))

        with mock.patch('django.utils.timezone.now', return_value=frozen):
            res = self.client_admin.get('/api/v1/admin/dashboard/')
        self.assertEqual(res.status_code, 200)
        # KST(2026-07-14) 기준이면 경계 유저 1명이 잡힌다(UTC 2026-07-13 기준이면 0 = 버그).
        self.assertEqual(res.json()['today_new_users'], 1)


# ─── FIX 3/5: 사용량 그룹핑 + days=0 전체기간 ───────────────────────────

class AdminUsageGroupingTest(TestCase):
    """FIX 3: 설계사 활동 vs 고객 반응 2그룹 분리·순위는 설계사 활동 기준.
    FIX 5: days=0 는 전체 기간(시간 필터 없음)으로 허용."""

    def setUp(self):
        self.admin = _make_user('admin@inpa.kr', is_admin=True)
        self.planner = _make_user('planner@test.kr')
        self.other = _make_user('other@test.kr')
        self.client_admin = _auth_client(self.admin)

    def test_grouping_and_ranking(self):
        from inpa.analytics.models import NorthStarEvent
        # planner: 설계사 활동 2 + 고객 반응 3
        NorthStarEvent.objects.create(sender=self.planner, event_type='ocr_upload')
        NorthStarEvent.objects.create(sender=self.planner, event_type='share_created')
        for _ in range(3):
            NorthStarEvent.objects.create(sender=self.planner, event_type='share_view')
        # other: 설계사 활동 3
        for _ in range(3):
            NorthStarEvent.objects.create(sender=self.other, event_type='analysis_view')

        res = self.client_admin.get('/api/v1/admin/usage/?days=0')  # 전체 기간(FIX 5)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['days'], 0)
        self.assertEqual(data['group_totals']['planner_activity'], 5)   # 2 + other 3
        self.assertEqual(data['group_totals']['customer_response'], 3)
        # ★ 순위는 설계사 활동 기준: other(3) 가 planner(2) 보다 앞.
        self.assertEqual(data['users'][0]['email'], 'other@test.kr')
        p = next(u for u in data['users'] if u['email'] == 'planner@test.kr')
        self.assertEqual(p['planner_activity'], 2)
        self.assertEqual(p['customer_response'], 3)
        self.assertEqual(p['total'], 5)  # 하위호환(전체 합) 유지


# ─── FIX 4: 관리자 사용량 화면 = 강제와 동일한 유효 요금제 한도 ──────────

class AdminEffectiveLimitsTest(TestCase):
    """FIX 4(#9 admin part): 구독이 만료/해지면 강제는 Free 폴백 → 관리자 상세 화면의
    한도도 Free 로 보여야 한다(resolve_effective_plan 공용)."""

    def setUp(self):
        self.admin = _make_user('admin@inpa.kr', is_admin=True)
        self.planner = _make_user('planner@test.kr')
        _make_plan('free', 'Free')  # 기본 한도(ocr 10, ai_compare 5 ...)
        self.plus = Plan.objects.create(
            code='plus', display_name='Plus', price_krw=19900,
            limit_ocr=100, limit_ai_compare=100, limit_analysis=100,
            limit_promotion=100, limit_customer=100)
        self.client_admin = _auth_client(self.admin)

    def test_expired_subscription_shows_free_limits(self):
        Subscription.objects.create(user=self.planner, plan=self.plus, status='expired')
        res = self.client_admin.get(f'/api/v1/admin/users/{self.planner.id}/')
        self.assertEqual(res.status_code, 200)
        limits = res.json()['usage_limits']
        self.assertEqual(limits['ocr'], 10)        # Free (Plus 100 아님)
        self.assertEqual(limits['ai_compare'], 5)

    def test_active_subscription_shows_plan_limits(self):
        Subscription.objects.create(user=self.planner, plan=self.plus, status='active')
        res = self.client_admin.get(f'/api/v1/admin/users/{self.planner.id}/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['usage_limits']['ocr'], 100)  # Plus
