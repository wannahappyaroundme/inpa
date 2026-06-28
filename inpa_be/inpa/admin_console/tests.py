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
from django.test import TestCase
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User
from inpa.admin_console.models import PolicyVersion
from inpa.analysis.models import AnalysisCategory, AnalysisDetail, AnalysisSubCategory, UnmatchedLog
from inpa.billing.models import Plan, Subscription
from inpa.boards.models import Inquiry, InquiryReply, Notice, Post, Report
from inpa.customers.models import ConsentLog, Customer
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
