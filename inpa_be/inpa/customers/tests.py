"""고객 도메인 핵심 게이트 테스트.

★ 필수 2종:
  1) owner 격리 — 설계사 A가 B의 고객을 조회·수정·삭제할 수 없다.
  2) 병력 동의 게이트 — consent_overseas_at 없으면 병력 등록 412 차단, 동의 후 201.
+ 하위 라우트 owner 격리, ConsentLog append-only, 동의 생성 시 스냅샷 동기화 보강.
"""
import datetime

from django.core import signing
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient
from django.test import TestCase, override_settings

from inpa.accounts.models import Profile, User
from inpa.billing.models import Plan, Subscription, UsageMeter
from inpa.insurances.models import CustomerInsurance

from .consent_texts import CONSENT_TEXTS_VERSION, has_current_overseas_consent
from .models import (
    ConsentLog, Customer, CustomerMedicalHistory, CustomerTag, JobRiskCode,
    PlannerBaseline,
)
from .presets import PRESET_ORIGIN_V0, PRESET_V0, iter_preset_rows
from .tokens import make_consent_token, read_consent_token


def _grant_overseas(customer, version=CONSENT_TEXTS_VERSION):
    """현재 문구 버전으로 받은 고객 본인 국외이전 동의 = Claude 게이트 통과 조건.

    version=''로 부르면 구버전 동의(재동의 필요) 상황을 재현한다.
    """
    customer.consent_overseas_at = timezone.now()
    customer.save(update_fields=['consent_overseas_at'])
    return ConsentLog.objects.create(
        customer=customer, scope=ConsentLog.SCOPE_OVERSEAS_MEDICAL,
        subject=ConsentLog.SUBJECT_CUSTOMER_SELF, doc_version=version)


def _make_planner(email):
    """이메일 인증 완료(is_active=True) + Profile 보유 설계사 + 인증된 APIClient 반환."""
    user = User.objects.create_user(email=email, password='inpaPass123!')
    user.is_active = True
    user.save(update_fields=['is_active'])
    Profile.objects.create(user=user, email_verified_at=timezone.now())
    client = APIClient()
    client.force_authenticate(user=user)
    return user, client


class OwnerIsolationTests(TestCase):
    """★ 멀티테넌시 격리 — 설계사 A는 B의 데이터에 절대 접근 불가."""

    def setUp(self):
        self.user_a, self.client_a = _make_planner('a@test.com')
        self.user_b, self.client_b = _make_planner('b@test.com')
        # B 소유 고객
        self.cust_b = Customer.objects.create(owner=self.user_b, name='B의고객',
                                              mobile_phone_number='010-1111-2222')

    def test_a_cannot_list_b_customer(self):
        """A의 목록에 B의 고객이 보이지 않는다."""
        r = self.client_a.get('/api/v1/customers/')
        self.assertEqual(r.status_code, 200)
        ids = [c['id'] for c in r.json()['results']]
        self.assertNotIn(self.cust_b.id, ids)

    def test_a_cannot_retrieve_b_customer(self):
        """A가 B의 고객 상세를 직접 조회하면 404(존재 자체를 숨김)."""
        r = self.client_a.get(f'/api/v1/customers/{self.cust_b.id}/')
        self.assertEqual(r.status_code, 404)

    def test_a_cannot_update_b_customer(self):
        r = self.client_a.patch(f'/api/v1/customers/{self.cust_b.id}/',
                                {'name': '탈취시도'}, format='json')
        self.assertEqual(r.status_code, 404)
        self.cust_b.refresh_from_db()
        self.assertEqual(self.cust_b.name, 'B의고객')

    def test_a_cannot_delete_b_customer(self):
        r = self.client_a.delete(f'/api/v1/customers/{self.cust_b.id}/')
        self.assertEqual(r.status_code, 404)
        self.assertTrue(Customer.objects.filter(id=self.cust_b.id).exists())

    def test_create_injects_owner(self):
        """생성 시 owner는 클라이언트 입력이 아니라 request.user로 주입된다."""
        r = self.client_a.post('/api/v1/customers/',
                               {'name': 'A의고객', 'mobile_phone_number': '010-3333-4444'},
                               format='json')
        self.assertEqual(r.status_code, 201)
        cust = Customer.objects.get(id=r.json()['id'])
        self.assertEqual(cust.owner_id, self.user_a.id)

    def test_a_cannot_access_b_family_subroute(self):
        """하위 라우트(가족)도 부모 고객 owner 격리 — A가 B 고객의 가족 라우트 접근 시 404."""
        r = self.client_a.get(f'/api/v1/customers/{self.cust_b.id}/family/')
        self.assertEqual(r.status_code, 404)

    def test_a_cannot_attach_b_tag(self):
        """A가 B의 태그를 본인 고객에 붙이려 하면 검증 거부(400)."""
        tag_b = CustomerTag.objects.create(owner=self.user_b, label='B태그')
        r = self.client_a.post('/api/v1/customers/',
                               {'name': 'A고객', 'tag_ids': [tag_b.id]}, format='json')
        self.assertEqual(r.status_code, 400)


@override_settings(ANALYZE_MEDICAL_ENABLED=True)
class MedicalConsentGateTests(TestCase):
    """★ 병력 동의 게이트 — consent_overseas_at 없으면 병력 등록 412 차단.

    (베타 게이트 ANALYZE_MEDICAL_ENABLED는 True로 켜고 동의게이트 자체를 검증.)
    """

    def setUp(self):
        self.user, self.client = _make_planner('planner@test.com')
        self.customer = Customer.objects.create(owner=self.user, name='홍길동',
                                                mobile_phone_number='010-0000-0000')

    def _post_medical(self):
        return self.client.post(
            f'/api/v1/customers/{self.customer.id}/medical/',
            {'disease_name': '고혈압', 'is_inpatient': False}, format='json')

    def test_medical_blocked_without_consent(self):
        """미동의(consent_overseas_at=null) → 412 + CONSENT_OVERSEAS_REQUIRED."""
        self.assertIsNone(self.customer.consent_overseas_at)
        r = self._post_medical()
        self.assertEqual(r.status_code, 412)
        self.assertEqual(r.json()['code'], 'CONSENT_OVERSEAS_REQUIRED')
        self.assertEqual(r.json()['reason'], 'missing')
        self.assertEqual(CustomerMedicalHistory.objects.count(), 0)

    def test_medical_allowed_after_consent(self):
        """현재 버전 고객 본인 동의 후 → 201 등록 성공."""
        _grant_overseas(self.customer)
        r = self._post_medical()
        self.assertEqual(r.status_code, 201)
        self.assertEqual(CustomerMedicalHistory.objects.count(), 1)

    def test_medical_old_version_consent_requires_reconsent(self):
        """구버전 문구로 받은 동의만 있으면 재동의 필요 → 412 reason=reconsent."""
        _grant_overseas(self.customer, version='')
        r = self._post_medical()
        self.assertEqual(r.status_code, 412)
        self.assertEqual(r.json()['code'], 'CONSENT_OVERSEAS_REQUIRED')
        self.assertEqual(r.json()['reason'], 'reconsent')
        self.assertEqual(CustomerMedicalHistory.objects.count(), 0)

    def test_planner_consent_does_not_unlock_gate(self):
        """★ P3c 카나리아: 설계사 동의 기록은 planner_attested(대리)로 남고 국외이전 게이트를
        열지 못한다. consent_overseas_at은 여전히 None, 병력 게이트도 412 유지."""
        r = self.client.post(
            f'/api/v1/customers/{self.customer.id}/consents/',
            {'scope': ConsentLog.SCOPE_OVERSEAS_MEDICAL, 'doc_version': 'OVERSEAS-v1.0'},
            format='json')
        self.assertEqual(r.status_code, 201)
        log = ConsentLog.objects.get(id=r.json()['id'])
        self.assertEqual(log.subject, ConsentLog.SUBJECT_PLANNER_ATTESTED)
        self.customer.refresh_from_db()
        self.assertIsNone(self.customer.consent_overseas_at)  # 게이트 안 열림
        r2 = self._post_medical()
        self.assertEqual(r2.status_code, 412)
        self.assertEqual(r2.json()['code'], 'CONSENT_OVERSEAS_REQUIRED')

    def test_planner_attested_stamps_current_version(self):
        """설계사 대리 동의도 현재 문구 버전으로 스탬프된다(서버 강제)."""
        r = self.client.post(
            f'/api/v1/customers/{self.customer.id}/consents/',
            {'scope': ConsentLog.SCOPE_MARKETING, 'doc_version': 'legacy-v1'},
            format='json')
        self.assertEqual(r.status_code, 201)
        log = ConsentLog.objects.get(id=r.json()['id'])
        self.assertEqual(log.doc_version, CONSENT_TEXTS_VERSION)

    def test_planner_cannot_forge_customer_self_subject(self):
        """설계사가 subject=customer_self로 위조해도 서버가 planner_attested로 강제(read_only)."""
        r = self.client.post(
            f'/api/v1/customers/{self.customer.id}/consents/',
            {'scope': ConsentLog.SCOPE_OVERSEAS_MEDICAL, 'subject': 'customer_self'},
            format='json')
        self.assertEqual(r.status_code, 201)
        log = ConsentLog.objects.get(id=r.json()['id'])
        self.assertEqual(log.subject, ConsentLog.SUBJECT_PLANNER_ATTESTED)

    def test_consent_log_is_append_only(self):
        """ConsentLog는 append-only — PATCH/DELETE 차단(405)."""
        r = self.client.post(
            f'/api/v1/customers/{self.customer.id}/consents/',
            {'scope': ConsentLog.SCOPE_MARKETING, 'doc_version': 'MKT-v1'}, format='json')
        self.assertEqual(r.status_code, 201)
        log_id = r.json()['id']
        r_patch = self.client.patch(
            f'/api/v1/customers/{self.customer.id}/consents/{log_id}/',
            {'purpose': '변조'}, format='json')
        self.assertEqual(r_patch.status_code, 405)
        r_del = self.client.delete(
            f'/api/v1/customers/{self.customer.id}/consents/{log_id}/')
        self.assertEqual(r_del.status_code, 405)


@override_settings(ANALYZE_MEDICAL_ENABLED=False)
class BetaMedicalDisabledTests(TestCase):
    """★ 베타 게이트(council 2026-06-21 P0-3) — ANALYZE_MEDICAL_ENABLED=False면
    국외이전 동의가 있어도 병력 등록을 403으로 차단(베타 미수집)."""

    def setUp(self):
        self.user, self.client = _make_planner('beta@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='홍길동', mobile_phone_number='010-0000-0000',
            consent_overseas_at=timezone.now())  # 동의가 있어도 차단되어야 함

    def test_medical_blocked_in_beta(self):
        r = self.client.post(
            f'/api/v1/customers/{self.customer.id}/medical/',
            {'disease_name': '고혈압', 'is_inpatient': False}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()['code'], 'MEDICAL_DISABLED_BETA')
        self.assertEqual(CustomerMedicalHistory.objects.count(), 0)


class ConsentLogRetentionTests(TestCase):
    """★ 동의기록 보존(council 2026-06-21 P0-5) — 고객 삭제(파기) 후에도
    ConsentLog는 SET_NULL로 남는다(처리방침상 동의기록 5년 보관)."""

    def test_consent_log_survives_customer_delete(self):
        user, _ = _make_planner('retain@test.com')
        customer = Customer.objects.create(owner=user, name='파기대상',
                                           mobile_phone_number='010-9999-8888')
        log = ConsentLog.objects.create(
            customer=customer, scope=ConsentLog.SCOPE_OVERSEAS_MEDICAL,
            doc_version='OVERSEAS-v1.0')
        log_id = log.id
        customer.delete()  # 고객 파기
        # 동의기록은 남고, customer 링크만 null
        self.assertTrue(ConsentLog.objects.filter(id=log_id).exists())
        log.refresh_from_db()
        self.assertIsNone(log.customer_id)


class CustomerSelfConsentTests(TestCase):
    """★ P3c: 고객 본인 국외이전 동의 — 토큰·동의요청(설계사)·공개 동의(고객)."""

    def setUp(self):
        cache.clear()  # ScopedRateThrottle(consent_public) 카운터 초기화
        self.user_a, self.client_a = _make_planner('agent_a@test.com')
        self.user_b, self.client_b = _make_planner('agent_b@test.com')
        self.customer = Customer.objects.create(
            owner=self.user_a, name='홍길동', mobile_phone_number='010-0000-0000')
        self.public = APIClient()  # 비인증 공개 클라이언트

    # ── 토큰 ──
    def test_token_roundtrip(self):
        token = make_consent_token(self.customer)
        self.assertEqual(read_consent_token(token)['pk'], self.customer.id)

    def test_token_expired(self):
        token = make_consent_token(self.customer)
        with override_settings(CONSENT_TOKEN_TTL_HOURS=0):
            with self.assertRaises(signing.SignatureExpired):
                read_consent_token(token)

    def test_token_tampered(self):
        with self.assertRaises(signing.BadSignature):
            read_consent_token('not.a.valid-token')

    # ── 설계사: 동의 요청 링크 생성 ──
    def test_consent_request_owner_ok(self):
        r = self.client_a.post(f'/api/v1/customers/{self.customer.id}/consent-requests/')
        self.assertEqual(r.status_code, 201)
        body = r.json()
        self.assertIn('token', body)
        self.assertIn('/c/', body['consent_url'])
        self.assertFalse(body['already_consented'])
        self.assertEqual(read_consent_token(body['token'])['pk'], self.customer.id)

    def test_consent_request_owner_isolation(self):
        """타 설계사(B)는 A의 고객으로 링크를 만들 수 없다(404)."""
        r = self.client_b.post(f'/api/v1/customers/{self.customer.id}/consent-requests/')
        self.assertEqual(r.status_code, 404)

    # ── 공개: 고지 GET ──
    def test_public_get_discloses_masked(self):
        token = make_consent_token(self.customer)
        r = self.public.get(f'/api/v1/c/{token}/')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body['customer']['name_masked'], '홍**')
        # 다항목화: 구 overseas_medical 단일 토큰 → items[0]['already'] 확인
        self.assertIn('items', body)
        overseas_item = next(it for it in body['items'] if it['scope'] == 'overseas_medical')
        self.assertFalse(overseas_item['already'])
        # PII 누출 금지 — 전화/생년/병력 미포함
        self.assertNotIn('010-0000-0000', r.content.decode())

    def test_public_get_expired_410(self):
        token = make_consent_token(self.customer)
        with override_settings(CONSENT_TOKEN_TTL_HOURS=0):
            r = self.public.get(f'/api/v1/c/{token}/')
        self.assertEqual(r.status_code, 410)

    def test_public_get_invalid_404(self):
        r = self.public.get('/api/v1/c/bad-token/')
        self.assertEqual(r.status_code, 404)

    # ── 공개: 동의 제출 POST ──
    def test_public_post_consent_unlocks_gate(self):
        token = make_consent_token(self.customer)
        r = self.public.post(f'/api/v1/c/{token}/',
                             {'agreed': ['overseas_medical']}, format='json')
        self.assertEqual(r.status_code, 201)
        self.customer.refresh_from_db()
        self.assertIsNotNone(self.customer.consent_overseas_at)  # OCR 게이트 해제
        log = ConsentLog.objects.filter(customer=self.customer).latest('agreed_at')
        self.assertEqual(log.subject, ConsentLog.SUBJECT_CUSTOMER_SELF)
        self.assertEqual(log.doc_version, CONSENT_TEXTS_VERSION)  # 버전 스탬프

    def test_public_post_without_consent_412(self):
        token = make_consent_token(self.customer)
        r = self.public.post(f'/api/v1/c/{token}/', {}, format='json')
        self.assertEqual(r.status_code, 412)
        self.customer.refresh_from_db()
        self.assertIsNone(self.customer.consent_overseas_at)

    def test_public_post_idempotent(self):
        """재동의가 기존 스냅샷 시각을 덮지 않는다(append-only 정신)."""
        token = make_consent_token(self.customer)
        self.public.post(f'/api/v1/c/{token}/',
                         {'agreed': ['overseas_medical']}, format='json')
        self.customer.refresh_from_db()
        first = self.customer.consent_overseas_at
        self.public.post(f'/api/v1/c/{token}/',
                         {'agreed': ['overseas_medical']}, format='json')
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.consent_overseas_at, first)

    def test_old_version_consent_is_reagreeable_via_c(self):
        """구버전 문구로 동의한 고객(consent_overseas_at 세팅됨)이 /c 로 재동의해 게이트를 다시 연다.

        LB-2 회복 경로: GET에서 overseas already=False(체크박스 재활성) → POST가 새 v2 로그 생성
        → has_current_overseas_consent 통과. 구버전 로그만 있으면 게이트가 막혀 있어야 한다.
        """
        # 구버전 동의 재현: consent_overseas_at 세팅 + doc_version='' 로그
        _grant_overseas(self.customer, version='')
        self.assertFalse(has_current_overseas_consent(self.customer))  # 게이트 아직 닫힘

        token = make_consent_token(self.customer)
        # GET: 구버전 고객도 overseas 항목이 재동의 가능(already=False)해야 함
        g = self.public.get(f'/api/v1/c/{token}/')
        self.assertEqual(g.status_code, 200)
        overseas_item = next(it for it in g.json()['items']
                             if it['scope'] == 'overseas_medical')
        self.assertFalse(overseas_item['already'])

        # POST: 새 v2 로그가 생성되어 게이트가 열림
        r = self.public.post(f'/api/v1/c/{token}/',
                             {'agreed': ['overseas_medical']}, format='json')
        self.assertEqual(r.status_code, 201)
        self.customer.refresh_from_db()
        self.assertTrue(has_current_overseas_consent(self.customer))
        # 새 로그는 현재 버전으로 스탬프됨
        latest = ConsentLog.objects.filter(
            customer=self.customer, scope=ConsentLog.SCOPE_OVERSEAS_MEDICAL,
        ).latest('agreed_at')
        self.assertEqual(latest.doc_version, CONSENT_TEXTS_VERSION)

    @override_settings(REQUIRE_CUSTOMER_SELF_CONSENT=True)
    def test_customer_self_unlocks_in_strict_mode(self):
        """전방검증: strict 모드여도 고객 본인 동의는 정상적으로 게이트를 연다."""
        token = make_consent_token(self.customer)
        r = self.public.post(f'/api/v1/c/{token}/',
                             {'agreed': ['overseas_medical']}, format='json')
        self.assertEqual(r.status_code, 201)
        self.customer.refresh_from_db()
        self.assertIsNotNone(self.customer.consent_overseas_at)


class AuthGateTests(TestCase):
    """인증/이메일 인증 게이트."""

    def test_unauthenticated_blocked(self):
        c = APIClient()
        self.assertEqual(c.get('/api/v1/customers/').status_code, 401)

    def test_unverified_email_blocked(self):
        """이메일 미인증(is_active=False) → IsEmailVerified 403."""
        user = User.objects.create_user(email='unverified@test.com', password='inpaPass123!')
        Profile.objects.create(user=user)
        c = APIClient()
        c.force_authenticate(user=user)
        r = c.get('/api/v1/customers/')
        self.assertEqual(r.status_code, 403)


class ApplyPresetTests(TestCase):
    """★ PRESET_DISABLED — apply-preset 은 §97/무등록중개 레드라인으로 비활성.
       모든 호출(인증 성공 포함)이 400 PRESET_DISABLED 를 반환하고 PlannerBaseline 행을 만들지 않음."""

    URL = '/api/v1/planner-baselines/apply-preset/'
    NONLIFE = PlannerBaseline.PRODUCT_GROUP_NONLIFE   # 2

    def setUp(self):
        self.user_a, self.client_a = _make_planner('preset-a@test.com')

    def test_apply_preset_returns_400_and_creates_nothing(self):
        """프리셋 적용 → 400 PRESET_DISABLED, PlannerBaseline 행 0개."""
        r = self.client_a.post(self.URL, {'product_group': self.NONLIFE}, format='json')
        self.assertEqual(r.status_code, 400)
        body = r.json()
        self.assertEqual(body.get('code'), 'PRESET_DISABLED')
        self.assertEqual(
            PlannerBaseline.objects.filter(owner=self.user_a).count(), 0)

    def test_apply_preset_any_group_returns_400(self):
        """상품군 값과 무관하게 400 반환."""
        for pg in [1, 2, 3, 4]:
            r = self.client_a.post(self.URL, {'product_group': pg}, format='json')
            self.assertEqual(r.status_code, 400,
                             msg=f'product_group={pg} 는 400 이어야 함')

    def test_unauthenticated_blocked(self):
        c = APIClient()
        r = c.post(self.URL, {'product_group': self.NONLIFE}, format='json')
        self.assertEqual(r.status_code, 401)

    def test_unverified_email_blocked(self):
        user = User.objects.create_user(email='preset-unverified@test.com',
                                        password='inpaPass123!')
        Profile.objects.create(user=user)
        c = APIClient()
        c.force_authenticate(user=user)
        r = c.post(self.URL, {'product_group': self.NONLIFE}, format='json')
        self.assertEqual(r.status_code, 403)


class SalesStageTests(TestCase):
    """영업 단계(칸반/퍼널) — 기본값·PATCH 단계이동·목록 노출·owner 격리."""

    def setUp(self):
        self.user_a, self.client_a = _make_planner('sa@test.com')
        self.user_b, self.client_b = _make_planner('sb@test.com')

    def test_default_stage_is_db(self):
        r = self.client_a.post('/api/v1/customers/', {'name': '신규리드'}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()['sales_stage'], Customer.STAGE_DB)

    def test_patch_moves_stage(self):
        cust = Customer.objects.create(owner=self.user_a, name='이동대상')
        r = self.client_a.patch(f'/api/v1/customers/{cust.id}/',
                                {'sales_stage': Customer.STAGE_MEETING}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['sales_stage'], Customer.STAGE_MEETING)
        cust.refresh_from_db()
        self.assertEqual(cust.sales_stage, Customer.STAGE_MEETING)

    def test_invalid_stage_rejected(self):
        cust = Customer.objects.create(owner=self.user_a, name='검증')
        r = self.client_a.patch(f'/api/v1/customers/{cust.id}/',
                                {'sales_stage': 'bogus'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_stage_in_list_serializer(self):
        Customer.objects.create(owner=self.user_a, name='목록', sales_stage=Customer.STAGE_CONTACT)
        r = self.client_a.get('/api/v1/customers/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['results'][0]['sales_stage'], Customer.STAGE_CONTACT)

    def test_cannot_move_others_customer(self):
        cust_b = Customer.objects.create(owner=self.user_b, name='B고객')
        r = self.client_a.patch(f'/api/v1/customers/{cust_b.id}/',
                                {'sales_stage': Customer.STAGE_CONTRACT}, format='json')
        self.assertEqual(r.status_code, 404)
        cust_b.refresh_from_db()
        self.assertEqual(cust_b.sales_stage, Customer.STAGE_DB)


class ConsentTokenScopeTests(TestCase):
    """토큰 다목적화 + 하위호환 + personal_info scope."""

    def setUp(self):
        self.user, self.client = _make_planner('tok@test.com')
        self.customer = Customer.objects.create(owner=self.user, name='김보장')

    def test_personal_info_scope_exists(self):
        self.assertEqual(ConsentLog.SCOPE_PERSONAL_INFO, 'personal_info')
        self.assertIn('personal_info', dict(ConsentLog.SCOPE_CHOICES))

    def test_token_roundtrip_with_scopes(self):
        tok = make_consent_token(self.customer, scopes=['personal_info', 'marketing'])
        data = read_consent_token(tok)
        self.assertEqual(data['pk'], self.customer.pk)
        self.assertEqual(set(data['scopes']), {'personal_info', 'marketing'})

    def test_token_default_scope_is_overseas(self):
        data = read_consent_token(make_consent_token(self.customer))
        self.assertEqual(data['scopes'], ['overseas_medical'])

    def test_legacy_int_token_backward_compat(self):
        from .tokens import CONSENT_SALT
        legacy = signing.dumps(self.customer.pk, salt=CONSENT_SALT)  # 구 형식: pk(int) 직접
        data = read_consent_token(legacy)
        self.assertEqual(data['pk'], self.customer.pk)
        self.assertEqual(data['scopes'], ['overseas_medical'])


class PublicConsentMultiScopeTests(TestCase):
    """공개 /c 다항목 동의 — 개인정보(필수)+마케팅(선택)."""

    def setUp(self):
        cache.clear()  # throttle 격리
        self.user, _ = _make_planner('pc@test.com')
        self.customer = Customer.objects.create(owner=self.user, name='김보장')
        self.anon = APIClient()  # 비인증(공개 경로)

    def _token(self, scopes):
        return make_consent_token(self.customer, scopes=scopes)

    def test_get_returns_requested_items(self):
        tok = self._token(['personal_info', 'marketing'])
        r = self.anon.get(f'/api/v1/c/{tok}/')
        self.assertEqual(r.status_code, 200)
        scopes = [it['scope'] for it in r.json()['items']]
        self.assertEqual(scopes, ['personal_info', 'marketing'])
        pi = next(it for it in r.json()['items'] if it['scope'] == 'personal_info')
        self.assertTrue(pi['required'])

    def test_post_agreed_creates_customer_self_logs(self):
        tok = self._token(['personal_info', 'marketing'])
        r = self.anon.post(f'/api/v1/c/{tok}/',
                           {'agreed': ['personal_info', 'marketing']}, format='json')
        self.assertEqual(r.status_code, 201)
        logs = ConsentLog.objects.filter(customer=self.customer)
        self.assertEqual(logs.count(), 2)
        self.assertTrue(all(l.subject == ConsentLog.SUBJECT_CUSTOMER_SELF for l in logs))

    def test_post_missing_required_returns_412(self):
        tok = self._token(['personal_info', 'marketing'])
        r = self.anon.post(f'/api/v1/c/{tok}/',
                           {'agreed': ['marketing']}, format='json')  # 필수 누락
        self.assertEqual(r.status_code, 412)
        self.assertEqual(ConsentLog.objects.filter(customer=self.customer).count(), 0)

    def test_overseas_token_sets_snapshot(self):
        tok = self._token(['overseas_medical'])
        r = self.anon.post(f'/api/v1/c/{tok}/',
                           {'agreed': ['overseas_medical']}, format='json')
        self.assertEqual(r.status_code, 201)
        self.customer.refresh_from_db()
        self.assertIsNotNone(self.customer.consent_overseas_at)

    def test_post_ignores_scope_not_in_token(self):
        """위조 방지 — 토큰에 없는 scope를 agreed에 넣어도 무시된다."""
        tok = self._token(['overseas_medical'])
        r = self.anon.post(f'/api/v1/c/{tok}/',
                           {'agreed': ['overseas_medical', 'personal_info']}, format='json')
        self.assertEqual(r.status_code, 201)
        scopes = set(ConsentLog.objects.filter(customer=self.customer)
                     .values_list('scope', flat=True))
        self.assertEqual(scopes, {'overseas_medical'})  # 토큰 밖 personal_info는 무시됨


class ConsentRequestScopeTests(TestCase):
    def setUp(self):
        self.user, self.client = _make_planner('cr@test.com')
        self.customer = Customer.objects.create(owner=self.user, name='김보장')

    def test_default_scope_overseas(self):
        r = self.client.post(f'/api/v1/customers/{self.customer.id}/consent-requests/',
                             {}, format='json')
        self.assertEqual(r.status_code, 201)
        data = read_consent_token(r.json()['token'])
        self.assertEqual(data['scopes'], ['overseas_medical'])

    def test_custom_scopes_encoded(self):
        r = self.client.post(f'/api/v1/customers/{self.customer.id}/consent-requests/',
                             {'scopes': ['personal_info', 'marketing']}, format='json')
        self.assertEqual(r.status_code, 201)
        data = read_consent_token(r.json()['token'])
        self.assertEqual(set(data['scopes']), {'personal_info', 'marketing'})

    def test_unknown_scope_rejected(self):
        r = self.client.post(f'/api/v1/customers/{self.customer.id}/consent-requests/',
                             {'scopes': ['hacker']}, format='json')
        self.assertEqual(r.status_code, 400)


class ConsentSerializerTests(TestCase):
    def setUp(self):
        self.user, self.client = _make_planner('ser@test.com')
        self.customer = Customer.objects.create(owner=self.user, name='김보장')

    def test_list_has_personal_info_consent_none(self):
        r = self.client.get('/api/v1/customers/')
        row = next(c for c in r.json()['results'] if c['id'] == self.customer.id)
        self.assertEqual(row['personal_info_consent'], 'none')

    def test_detail_consents_reflect_logs(self):
        ConsentLog.objects.create(customer=self.customer,
                                  scope=ConsentLog.SCOPE_PERSONAL_INFO,
                                  subject=ConsentLog.SUBJECT_CUSTOMER_SELF)
        ConsentLog.objects.create(customer=self.customer,
                                  scope=ConsentLog.SCOPE_MARKETING,
                                  subject=ConsentLog.SUBJECT_PLANNER_ATTESTED)
        r = self.client.get(f'/api/v1/customers/{self.customer.id}/')
        consents = r.json()['consents']
        self.assertEqual(consents['personal_info']['status'], 'agreed')
        self.assertEqual(consents['personal_info']['subject'], 'customer_self')
        self.assertEqual(consents['marketing']['subject'], 'planner_attested')


class DdayAutoUpdateTests(TestCase):
    """D-Day 자동갱신: substantive 필드 PATCH → last_contacted_at 갱신. is_favorite/is_pinned만 → 불변."""

    def setUp(self):
        self.user, self.client = _make_planner('dday@test.com')
        self.cust = Customer.objects.create(
            owner=self.user,
            name='테스트고객',
            mobile_phone_number='010-0000-0000',
            last_contacted_at=None,
        )

    def test_substantive_patch_updates_last_contacted_at(self):
        """memo 수정 → last_contacted_at이 ~now로 갱신된다."""
        before = timezone.now()
        r = self.client.patch(
            f'/api/v1/customers/{self.cust.id}/',
            {'memo': '메모 수정'},
            format='json',
        )
        self.assertEqual(r.status_code, 200)
        self.cust.refresh_from_db()
        self.assertIsNotNone(self.cust.last_contacted_at)
        self.assertGreaterEqual(self.cust.last_contacted_at, before)

    def test_non_substantive_patch_does_not_update_last_contacted_at(self):
        """is_favorite만 PATCH → last_contacted_at 불변."""
        original_ts = self.cust.last_contacted_at  # None
        r = self.client.patch(
            f'/api/v1/customers/{self.cust.id}/',
            {'is_favorite': True},
            format='json',
        )
        self.assertEqual(r.status_code, 200)
        self.cust.refresh_from_db()
        self.assertEqual(self.cust.last_contacted_at, original_ts)

    def test_patch_sales_stage_meeting_sets_fa_reached_at_once(self):
        """칸반 FA 이동(PATCH sales_stage=meeting) → fa_reached_at 기록, 재이동엔 불변."""
        self.assertIsNone(self.cust.fa_reached_at)
        r = self.client.patch(f'/api/v1/customers/{self.cust.id}/',
                             {'sales_stage': 'meeting'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.cust.refresh_from_db()
        self.assertIsNotNone(self.cust.fa_reached_at)
        first = self.cust.fa_reached_at
        # 청약 → 다시 FA: 최초 시각 보존(중복 카운트 방지)
        self.client.patch(f'/api/v1/customers/{self.cust.id}/', {'sales_stage': 'contract'}, format='json')
        self.client.patch(f'/api/v1/customers/{self.cust.id}/', {'sales_stage': 'meeting'}, format='json')
        self.cust.refresh_from_db()
        self.assertEqual(self.cust.fa_reached_at, first)


class JobSearchTests(TestCase):
    """직업급수 검색(전역 마스터) + 고객 job_code 적용."""

    def setUp(self):
        self.user, self.client = _make_planner('job@test.com')
        self.doctor = JobRiskCode.objects.create(
            sctg_cd='1110', name='의사', risk_grade=1, kidi_cd='011')
        self.council = JobRiskCode.objects.create(
            sctg_cd='1501', name='의회의원/공공단체임원', risk_grade=1,
            synonym='지방의회의원|시의원|도의원|구의원')

    def test_name_match_ranked_first(self):
        r = self.client.get('/api/v1/jobs/search/?q=의사')
        self.assertEqual(r.status_code, 200)
        results = r.data['results']
        self.assertTrue(results)
        self.assertEqual(results[0]['name'], '의사')
        self.assertEqual(results[0]['risk_grade'], 1)
        self.assertEqual(results[0]['risk_grade_label'], '1급')

    def test_synonym_match(self):
        """검색어(synonym)에만 있는 '시의원' 으로 의회의원 매칭."""
        r = self.client.get('/api/v1/jobs/search/?q=시의원')
        self.assertEqual(r.status_code, 200)
        names = [j['name'] for j in r.data['results']]
        self.assertIn('의회의원/공공단체임원', names)

    def test_empty_query_empty_results(self):
        r = self.client.get('/api/v1/jobs/search/?q=')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['results'], [])

    def test_requires_auth(self):
        anon = APIClient()
        r = anon.get('/api/v1/jobs/search/?q=의사')
        self.assertIn(r.status_code, (401, 403))

    def test_customer_job_code_apply(self):
        """검색 결과 id 를 job_code 로 고객 생성 → 직렬화에 job_risk_grade 반영."""
        r = self.client.post('/api/v1/customers/',
                             {'name': '김보장', 'job_code': self.doctor.id}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        cust = Customer.objects.get(pk=r.data['id'])
        self.assertEqual(cust.job_code_id, self.doctor.id)
        detail = self.client.get(f'/api/v1/customers/{cust.id}/')
        self.assertEqual(detail.data['job_risk_grade'], 1)
        self.assertEqual(detail.data['job_name'], '의사')


class ContactLogTests(TestCase):
    """접촉 결과 로그 — 생성 시 last_contacted_at 갱신, owner 격리, append-only."""

    def setUp(self):
        self.user_a, self.client_a = _make_planner('contact_a@test.com')
        self.user_b, self.client_b = _make_planner('contact_b@test.com')
        self.customer = Customer.objects.create(owner=self.user_a, name='접촉고객')

    def _url(self, cid=None):
        return f'/api/v1/customers/{cid or self.customer.id}/contact-logs/'

    def test_create_bumps_last_contacted(self):
        self.assertIsNone(self.customer.last_contacted_at)
        r = self.client_a.post(self._url(), {'result': 'no_answer', 'memo': '부재중'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.json()['result'], 'no_answer')
        self.assertEqual(r.json()['result_display'], '부재중')
        self.customer.refresh_from_db()
        self.assertIsNotNone(self.customer.last_contacted_at)  # 방치 경보 리셋

    def test_list_returns_own_logs(self):
        self.client_a.post(self._url(), {'result': 'connected'}, format='json')
        self.client_a.post(self._url(), {'result': 'appointment', 'memo': '내일 2시'}, format='json')
        body = self.client_a.get(self._url()).json()
        results = body['results'] if isinstance(body, dict) and 'results' in body else body
        self.assertEqual(len(results), 2)

    def test_owner_isolation(self):
        # B가 A의 고객에 접촉로그 시도 → 404(존재 은폐)
        r = self.client_b.post(self._url(), {'result': 'connected'}, format='json')
        self.assertEqual(r.status_code, 404)

    def test_append_only_no_delete(self):
        r = self.client_a.post(self._url(), {'result': 'hold'}, format='json')
        log_id = r.json()['id']
        rd = self.client_a.delete(f'{self._url()}{log_id}/')
        self.assertIn(rd.status_code, (404, 405))  # detail 라우트 미등록 + append-only


class CustomerBulkCreateTests(TestCase):
    """고객 일괄 등록 — 중복(이름+연락처) 건너뛰기, 이름 없는 행 무시, db 단계."""

    def setUp(self):
        self.user, self.client = _make_planner('bulk@test.com')

    def test_bulk_create_with_dedup(self):
        Customer.objects.create(owner=self.user, name='기존', mobile_phone_number='010-1')
        body = {'customers': [
            {'name': '김민수', 'mobile_phone_number': '010-1234-5678'},
            {'name': '기존', 'mobile_phone_number': '010-1'},                  # 기존 중복 → skip
            {'name': '김민수', 'mobile_phone_number': '010-1234-5678'},        # 배치 내 중복 → skip
            {'name': '', 'mobile_phone_number': '010-9'},                      # 이름 없음 → skip
            {'name': '이영희'},
        ]}
        r = self.client.post('/api/v1/customers/bulk/', body, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.json()['created'], 2)   # 김민수, 이영희
        self.assertEqual(r.json()['skipped'], 3)
        self.assertEqual(Customer.objects.filter(owner=self.user).count(), 3)  # 기존1 + 신규2
        new = Customer.objects.get(name='이영희')
        self.assertEqual(new.sales_stage, 'db')
        self.assertEqual(new.lead_source, 'direct')

    def test_bulk_empty_rejected(self):
        r = self.client.post('/api/v1/customers/bulk/', {'customers': []}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_bulk_create_full_fields(self):
        """일괄 등록도 성별·생년월일·직업급수·유입경로·메모·아바타를 행별로 반영."""
        job = JobRiskCode.objects.create(sctg_cd='D01', name='의사', risk_grade=1)
        body = {'customers': [
            {
                'name': '김보장', 'mobile_phone_number': '010-1111-2222',
                'gender': '1', 'birth_day': '1990-05-15',
                'job_code': str(job.id), 'lead_source': 'introduction',
                'memo': '지인 소개', 'avatar_label': 'KB', 'color': '#F8D7DD',
            },
            {
                'name': '이영희',
                'gender': '2',
                'job_code': '99999',          # 존재하지 않는 직업 id → 무시(None)
                'lead_source': 'weird',        # 잘못된 유입 → direct 폴백
            },
        ]}
        r = self.client.post('/api/v1/customers/bulk/', body, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.json()['created'], 2)

        a = Customer.objects.get(name='김보장')
        self.assertEqual(a.gender, 1)
        self.assertEqual(a.birth_day, '1990-05-15')
        self.assertEqual(a.job_code_id, job.id)
        self.assertEqual(a.lead_source, 'introduction')
        self.assertEqual(a.memo, '지인 소개')
        self.assertEqual(a.avatar_label, 'KB')
        self.assertEqual(a.color, '#F8D7DD')

        b = Customer.objects.get(name='이영희')
        self.assertEqual(b.gender, 2)
        self.assertIsNone(b.job_code_id)          # 없는 id → None
        self.assertEqual(b.lead_source, 'direct')  # 잘못된 값 → 폴백


class ConsentTextsEndpointTests(TestCase):
    """★ LB-2: 공개 동의 고지문 단일 소스 GET /consent-texts/."""

    def setUp(self):
        cache.clear()  # share_public ScopedRateThrottle 카운터 격리
        self.public = APIClient()

    def test_returns_version_and_all_scopes(self):
        r = self.public.get('/api/v1/consent-texts/')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body['version'], CONSENT_TEXTS_VERSION)
        texts = body['texts']
        for scope in ('overseas_medical', 'personal_info', 'third_party', 'marketing'):
            self.assertIn(scope, texts)
            self.assertIn('title', texts[scope])
            self.assertIn('body', texts[scope])
            self.assertIn('retention', texts[scope])

    def test_overseas_retention_wording_corrected(self):
        """옛 '즉시 삭제' 문구는 사라지고 Anthropic 정책 문구가 들어간다."""
        r = self.public.get('/api/v1/consent-texts/')
        overseas = r.json()['texts']['overseas_medical']['retention']
        self.assertNotIn('즉시 삭제', overseas)
        self.assertIn('Anthropic', overseas)
        # 전체 응답에도 옛 문구가 없어야 함
        self.assertNotIn('즉시 삭제', r.content.decode())


class SeedJobsMarkerTests(TestCase):
    """LB-1 시드 안전화: seed_jobs 버전 마커 — 2회차 no-op, --force 우회."""

    def _tiny_file(self):
        import json
        import tempfile
        rows = [{'sctg_cd': 'S01', 'name': '테스트직업', 'risk_grade': 1}]
        f = tempfile.NamedTemporaryFile(
            'w', suffix='.json', delete=False, encoding='utf-8')
        json.dump(rows, f)
        f.close()
        return f.name

    def test_marker_skips_second_run_force_bypasses(self):
        from io import StringIO

        from django.core.management import call_command

        from inpa.analysis.models import SeedMarker
        from inpa.customers.management.commands import seed_jobs as seed_jobs_mod
        from inpa.customers.models import JobRiskCode

        path = self._tiny_file()
        call_command('seed_jobs', '--file', path, stdout=StringIO())
        self.assertEqual(JobRiskCode.objects.count(), 1)
        self.assertEqual(
            SeedMarker.objects.get(key=seed_jobs_mod.MARKER_KEY).version,
            seed_jobs_mod.SEED_VERSION)

        # 2회차: 마커 최신 → no-op (파일 SSOT prune 로직도 실행 안 됨)
        out = StringIO()
        call_command('seed_jobs', '--file', path, stdout=out)
        self.assertIn('이미 최신', out.getvalue())

        # --force: 실제 실행 (upsert + 파일 SSOT 동기화 의미 유지)
        out2 = StringIO()
        call_command('seed_jobs', '--file', path, '--force', stdout=out2)
        self.assertIn('직업급수 시드 완료', out2.getvalue())
        self.assertEqual(JobRiskCode.objects.count(), 1)


class ConsentRevokeTests(TestCase):
    """공개 /c 동의 철회(LB#10) — revocable 노출, revoked[] 스탬프, 게이트·스냅샷 정합."""

    def setUp(self):
        cache.clear()  # throttle 격리
        self.user, _ = _make_planner('rv@test.com')
        self.customer = Customer.objects.create(owner=self.user, name='김철회')
        self.anon = APIClient()

    def _token(self, scopes):
        return make_consent_token(self.customer, scopes=scopes)

    def test_get_marks_agreed_scope_revocable(self):
        """동의된 scope는 revocable=true, 기록 없는 scope는 false."""
        ConsentLog.objects.create(
            customer=self.customer, scope=ConsentLog.SCOPE_MARKETING,
            subject=ConsentLog.SUBJECT_CUSTOMER_SELF, doc_version=CONSENT_TEXTS_VERSION)
        tok = self._token(['marketing', 'personal_info'])
        r = self.anon.get(f'/api/v1/c/{tok}/')
        self.assertEqual(r.status_code, 200)
        items = {it['scope']: it for it in r.json()['items']}
        self.assertTrue(items['marketing']['revocable'])
        self.assertFalse(items['personal_info']['revocable'])

    def test_post_revoked_stamps_all_unrevoked_logs_incl_planner_attested(self):
        """철회 = 해당 scope의 모든 unrevoked 로그(subject 불문) revoked_at 스탬프."""
        ConsentLog.objects.create(
            customer=self.customer, scope=ConsentLog.SCOPE_MARKETING,
            subject=ConsentLog.SUBJECT_CUSTOMER_SELF)
        ConsentLog.objects.create(
            customer=self.customer, scope=ConsentLog.SCOPE_MARKETING,
            subject=ConsentLog.SUBJECT_PLANNER_ATTESTED)
        tok = self._token(['marketing'])
        r = self.anon.post(f'/api/v1/c/{tok}/', {'revoked': ['marketing']}, format='json')
        self.assertEqual(r.status_code, 200)
        logs = ConsentLog.objects.filter(customer=self.customer,
                                         scope=ConsentLog.SCOPE_MARKETING)
        self.assertEqual(logs.count(), 2)
        self.assertTrue(all(l.revoked_at is not None for l in logs))
        # 재철회 멱등 — 추가 스탬프 없음, 응답 정상
        r2 = self.anon.post(f'/api/v1/c/{tok}/', {'revoked': ['marketing']}, format='json')
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()['revoked'][0]['updated_logs'], 0)

    @override_settings(ANTHROPIC_API_KEY='test-key')
    def test_overseas_revoke_closes_ocr_gate_with_missing_reason(self):
        """국외이전 철회 → 스냅샷(consent_overseas_at)도 비워져 OCR 게이트 412 reason=missing."""
        _grant_overseas(self.customer)
        self.assertTrue(has_current_overseas_consent(self.customer))
        tok = self._token(['overseas_medical'])
        r = self.anon.post(f'/api/v1/c/{tok}/', {'revoked': ['overseas_medical']},
                           format='json')
        self.assertEqual(r.status_code, 200)
        self.customer.refresh_from_db()
        self.assertIsNone(self.customer.consent_overseas_at)
        self.assertFalse(has_current_overseas_consent(self.customer))
        # OCR 업로드 게이트 — 철회 후 새 분석은 412(스냅샷까지 비웠으니 reason=missing)
        client = APIClient()
        client.force_authenticate(user=self.user)
        ocr = client.post(f'/api/v1/customers/{self.customer.id}/insurances/ocr/', {})
        self.assertEqual(ocr.status_code, 412)
        self.assertEqual(ocr.json()['code'], 'CONSENT_OVERSEAS_REQUIRED')
        self.assertEqual(ocr.json()['reason'], 'missing')

    def test_revoke_outside_token_scope_ignored(self):
        """토큰 밖 scope 철회는 무시(위조 가드) — 로그 불변."""
        ConsentLog.objects.create(
            customer=self.customer, scope=ConsentLog.SCOPE_MARKETING,
            subject=ConsentLog.SUBJECT_CUSTOMER_SELF)
        tok = self._token(['personal_info'])  # marketing 미포함 토큰
        r = self.anon.post(f'/api/v1/c/{tok}/',
                           {'agreed': ['personal_info'], 'revoked': ['marketing']},
                           format='json')
        self.assertEqual(r.status_code, 201)
        log = ConsentLog.objects.get(customer=self.customer,
                                     scope=ConsentLog.SCOPE_MARKETING)
        self.assertIsNone(log.revoked_at)

    def test_pure_revoke_of_required_scope_passes_412_check(self):
        """철회 전용 요청은 필수 미동의 412를 타지 않는다(철회권 보장)."""
        ConsentLog.objects.create(
            customer=self.customer, scope=ConsentLog.SCOPE_PERSONAL_INFO,
            subject=ConsentLog.SUBJECT_CUSTOMER_SELF)
        tok = self._token(['personal_info'])
        r = self.anon.post(f'/api/v1/c/{tok}/', {'revoked': ['personal_info']},
                           format='json')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()['all_required_done'])

    def test_revoke_then_reagree_reopens_gate(self):
        """왕복 — 철회 후 재동의(v2) → 새 로그 생성 + 게이트 다시 열림."""
        _grant_overseas(self.customer)
        tok = self._token(['overseas_medical'])
        self.anon.post(f'/api/v1/c/{tok}/', {'revoked': ['overseas_medical']},
                       format='json')
        self.assertFalse(has_current_overseas_consent(self.customer))
        r = self.anon.post(f'/api/v1/c/{tok}/', {'agreed': ['overseas_medical']},
                           format='json')
        self.assertEqual(r.status_code, 201)
        self.customer.refresh_from_db()
        self.assertIsNotNone(self.customer.consent_overseas_at)
        self.assertTrue(has_current_overseas_consent(self.customer))
        # 로그: 철회된 1건 + 살아있는 새 1건
        logs = ConsentLog.objects.filter(customer=self.customer,
                                         scope=ConsentLog.SCOPE_OVERSEAS_MEDICAL)
        self.assertEqual(logs.count(), 2)
        self.assertEqual(logs.filter(revoked_at__isnull=True).count(), 1)

    def test_revoke_updates_detail_serializer_state(self):
        """철회 후 고객 상세 consents 상태가 'revoked'로 일관 반영(표시 정합)."""
        ConsentLog.objects.create(
            customer=self.customer, scope=ConsentLog.SCOPE_MARKETING,
            subject=ConsentLog.SUBJECT_CUSTOMER_SELF)
        tok = self._token(['marketing'])
        self.anon.post(f'/api/v1/c/{tok}/', {'revoked': ['marketing']}, format='json')
        client = APIClient()
        client.force_authenticate(user=self.user)
        r = client.get(f'/api/v1/customers/{self.customer.id}/')
        self.assertEqual(r.json()['consents']['marketing']['status'], 'revoked')
        self.assertEqual(r.json()['marketing_consent'], 'revoked')

    def _make_snapshot(self, customer):
        from inpa.analytics.models import ShareSnapshot
        return ShareSnapshot.objects.create(
            owner=self.user, customer=customer,
            payload={'tree': [], 'summary': {}, 'disclaimer': 'x',
                     'customer': {'name_masked': '김**'}, 'mode': 'neutral'},
            retention_expires_at=timezone.now() + datetime.timedelta(days=180))

    def test_personal_info_revoke_purges_this_customers_share_snapshots(self):
        """개인정보(personal_info) 철회 = 그 고객의 공유(/s) 기록 전량 즉시 파기(spec 2026-07-08)."""
        from inpa.analytics.models import ShareSnapshot
        ConsentLog.objects.create(
            customer=self.customer, scope=ConsentLog.SCOPE_PERSONAL_INFO,
            subject=ConsentLog.SUBJECT_CUSTOMER_SELF)
        self._make_snapshot(self.customer)
        other_customer = Customer.objects.create(owner=self.user, name='다른고객')
        other_snap = self._make_snapshot(other_customer)

        tok = self._token(['personal_info'])
        r = self.anon.post(f'/api/v1/c/{tok}/', {'revoked': ['personal_info']},
                           format='json')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(ShareSnapshot.objects.filter(customer=self.customer).exists())
        # 다른 고객의 스냅샷은 무관 — 보존
        self.assertTrue(ShareSnapshot.objects.filter(pk=other_snap.pk).exists())

    def test_marketing_revoke_does_not_touch_share_snapshots(self):
        """personal_info 이외 scope 철회는 공유 기록과 무관(보존)."""
        from inpa.analytics.models import ShareSnapshot
        ConsentLog.objects.create(
            customer=self.customer, scope=ConsentLog.SCOPE_MARKETING,
            subject=ConsentLog.SUBJECT_CUSTOMER_SELF)
        snap = self._make_snapshot(self.customer)
        tok = self._token(['marketing'])
        r = self.anon.post(f'/api/v1/c/{tok}/', {'revoked': ['marketing']}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(ShareSnapshot.objects.filter(pk=snap.pk).exists())


class DailyCallListTests(TestCase):
    """오늘 전화 리스트(call-list) — 랭킹·격리·캡·안전성 (spec 2026-07-05)."""

    URL = '/api/v1/customers/call-list/'

    def setUp(self):
        self.user, self.client = _make_planner('caller@test.com')
        self.other, self.other_client = _make_planner('other@test.com')
        self.today = timezone.localdate()

    def _customer(self, name, owner=None, **kw):
        return Customer.objects.create(owner=owner or self.user, name=name, **kw)

    def _birth_str(self, days_ahead):
        """오늘+N일의 월·일을 가진 생일 문자열(1992 = 윤년이라 2/29도 유효)."""
        d = self.today + datetime.timedelta(days=days_ahead)
        return f'1992-{d.month:02d}-{d.day:02d}'

    def _expiry(self, customer, days_ahead, **kw):
        exp = self.today + datetime.timedelta(days=days_ahead)
        return CustomerInsurance.objects.create(
            customer=customer, name='테스트보험', portfolio_type=1,
            expiry_date=exp.strftime('%Y-%m-%d'), **kw)

    def test_ranking_birthday_over_expiry_over_idle(self):
        """생일 D-1(90) > 만기 D-5(70) > 무접촉 30일(30) 순서 + reasons 칩."""
        c_birth = self._customer('생일고객', birth_day=self._birth_str(1))
        c_exp = self._customer('만기고객')
        self._expiry(c_exp, 5)
        c_idle = self._customer(
            '무접촉고객',
            last_contacted_at=timezone.now() - datetime.timedelta(days=30))
        r = self.client.get(self.URL)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        names = [row['name'] for row in body['results']]
        self.assertEqual(names, ['생일고객', '만기고객', '무접촉고객'])
        self.assertEqual(body['total_candidates'], 3)
        by_name = {row['name']: row for row in body['results']}
        self.assertEqual(by_name['생일고객']['score'], 90)
        self.assertIn('생일 D-1', by_name['생일고객']['reasons'])
        self.assertEqual(by_name['만기고객']['score'], 70)
        self.assertIn('만기 D-5', by_name['만기고객']['reasons'])
        self.assertIn('무접촉', by_name['무접촉고객']['reasons'][0])
        self.assertEqual(by_name['무접촉고객']['id'], c_idle.id)
        self.assertEqual(by_name['생일고객']['id'], c_birth.id)

    def test_only_active_status(self):
        """보류·휴면·종료 고객은 사유가 강해도 제외."""
        for st in (Customer.STATUS_HOLD, Customer.STATUS_DORMANT,
                   Customer.STATUS_CLOSED):
            self._customer(
                f'파킹-{st}', status=st,
                last_contacted_at=timezone.now() - datetime.timedelta(days=40))
        active = self._customer(
            '진행중고객',
            last_contacted_at=timezone.now() - datetime.timedelta(days=10))
        r = self.client.get(self.URL)
        body = r.json()
        self.assertEqual([row['id'] for row in body['results']], [active.id])
        self.assertEqual(body['total_candidates'], 1)

    def test_owner_isolation(self):
        """타 설계사 고객은 사유가 있어도 절대 미노출."""
        self._customer(
            '남의고객', owner=self.other,
            birth_day=self._birth_str(0),
            last_contacted_at=timezone.now() - datetime.timedelta(days=50))
        mine = self._customer(
            '내고객', last_contacted_at=timezone.now() - datetime.timedelta(days=5))
        r = self.client.get(self.URL)
        body = r.json()
        self.assertEqual([row['id'] for row in body['results']], [mine.id])
        self.assertEqual(body['total_candidates'], 1)

    def test_zero_score_excluded_and_cap_10(self):
        """사유 없는(score 0) 고객 제외 + 10명 캡 + total_candidates."""
        fresh = self._customer('오늘등록')  # created 오늘 → 무접촉 0 → score 0
        # 단계 보정만으로는 리스트에 오르지 않음(사유 없음).
        momentum = self._customer('모멘텀만', sales_stage=Customer.STAGE_CONTACT)
        for i in range(12):
            self._customer(
                f'무접촉{i}',
                last_contacted_at=timezone.now() - datetime.timedelta(days=5 + i))
        r = self.client.get(self.URL)
        body = r.json()
        self.assertEqual(len(body['results']), 10)
        self.assertEqual(body['total_candidates'], 12)
        ids = {row['id'] for row in body['results']}
        self.assertNotIn(fresh.id, ids)
        self.assertNotIn(momentum.id, ids)

    def test_stage_bonus_applied_when_reason_exists(self):
        """같은 사유(무접촉 20일)면 TA/FA 단계가 +10으로 앞선다."""
        anchor = timezone.now() - datetime.timedelta(days=20)
        db_cust = self._customer('디비단계', last_contacted_at=anchor)
        ta_cust = self._customer('티에이단계', sales_stage=Customer.STAGE_CONTACT,
                                 last_contacted_at=anchor)
        r = self.client.get(self.URL)
        by_name = {row['name']: row for row in r.json()['results']}
        self.assertEqual(by_name['티에이단계']['score'],
                         by_name['디비단계']['score'] + 10)
        self.assertEqual([row['id'] for row in r.json()['results']],
                         [ta_cust.id, db_cust.id])

    def test_limit_param_default_cap_and_invalid(self):
        """?limit= 동작 — 기본 10 · 상한 50 클램프 · 비정상 값은 기본값."""
        for i in range(55):
            self._customer(
                f'무접촉{i}',
                last_contacted_at=timezone.now() - datetime.timedelta(days=3 + i))
        # 기본(파라미터 없음) = 10
        body = self.client.get(self.URL).json()
        self.assertEqual(len(body['results']), 10)
        self.assertEqual(body['total_candidates'], 55)
        # 명시 limit 반영
        body = self.client.get(self.URL, {'limit': '5'}).json()
        self.assertEqual(len(body['results']), 5)
        self.assertEqual(body['total_candidates'], 55)
        # 전용 화면 요청값(50) + 상한 초과는 50으로 클램프
        body = self.client.get(self.URL, {'limit': '50'}).json()
        self.assertEqual(len(body['results']), 50)
        body = self.client.get(self.URL, {'limit': '999'}).json()
        self.assertEqual(len(body['results']), 50)
        # 비정상 값(숫자 아님·0 이하)은 기본 10
        for bad in ('abc', '0', '-3'):
            body = self.client.get(self.URL, {'limit': bad}).json()
            self.assertEqual(len(body['results']), 10, msg=f'limit={bad}')

    def test_malformed_dates_are_safe(self):
        """생일·만기 문자열이 깨져도 200 + 그 사유만 조용히 무시."""
        self._customer('깨진생일', birth_day='19-XX')  # 파싱 불가 + 무접촉 0 → 제외
        broken_exp = self._customer(
            '깨진만기', last_contacted_at=timezone.now() - datetime.timedelta(days=3))
        self._expiry(broken_exp, 5)
        broken_exp.customer_insurance_list.update(expiry_date='2026.13.99')
        r = self.client.get(self.URL)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual([row['id'] for row in body['results']], [broken_exp.id])
        reasons = body['results'][0]['reasons']
        self.assertTrue(all('만기' not in x and '생일' not in x for x in reasons))
        self.assertEqual(body['total_candidates'], 1)


# ─── 신규 고객 추가 한도 (spec 2026-07-09 pricing-limits-align) ───────────────


def _consume_customer_quota(user, n):
    """billing UsageMeter('customer') 카운터를 n으로 직접 세팅(billing/tests.py::_consume_n과 동일 패턴)."""
    ym = UsageMeter.current_month()
    meter, _ = UsageMeter.objects.get_or_create(
        user=user, action='customer', year_month=ym, defaults={'count': 0})
    meter.count = n
    meter.save(update_fields=['count', 'updated_at'])


def _subscribe_free(user, limit_customer=5):
    """테스트 전용 free Plan(원하는 limit_customer)에 구독시킨다."""
    free_plan, created = Plan.objects.get_or_create(
        code='free',
        defaults={'display_name': '무료', 'price_krw': 0, 'limit_customer': limit_customer},
    )
    if not created and free_plan.limit_customer != limit_customer:
        free_plan.limit_customer = limit_customer
        free_plan.save(update_fields=['limit_customer'])
    Subscription.objects.update_or_create(
        user=user, defaults={'plan': free_plan, 'status': 'active'})
    return free_plan


@override_settings(FREE_TIER_UNLIMITED=False)
class CustomerQuotaEnforcementTests(TestCase):
    """CustomerViewSet 단건·일괄 등록 — 신규 고객 추가 한도(kind='customer') 강제.

    ★ FREE_TIER_UNLIMITED=False(유료 전환 후)에서만 발동 — 베타 dormant는
    CustomerQuotaBetaDormantTests 로 별도 검증한다.
    """

    def setUp(self):
        self.user, self.client = _make_planner('quota@test.com')
        _subscribe_free(self.user, limit_customer=5)

    def test_sixth_single_create_returns_402_credit_exhausted(self):
        _consume_customer_quota(self.user, 5)
        r = self.client.post('/api/v1/customers/', {'name': '고객6'}, format='json')
        self.assertEqual(r.status_code, 402, r.data)
        self.assertEqual(r.json()['code'], 'credit_exhausted')
        self.assertEqual(r.json()['kind'], 'customer')
        self.assertFalse(Customer.objects.filter(owner=self.user, name='고객6').exists())

    def test_fifth_single_create_passes(self):
        _consume_customer_quota(self.user, 4)
        r = self.client.post('/api/v1/customers/', {'name': '고객5'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(Customer.objects.filter(owner=self.user, name='고객5').exists())

    def test_bulk_batch_larger_than_remaining_returns_402_no_partial_create(self):
        """잔여 0(5/5 소진)인데 2건 일괄 등록 시도 → 402, 아무도 생성되지 않는다."""
        _consume_customer_quota(self.user, 5)
        body = {'customers': [{'name': '벌크1'}, {'name': '벌크2'}]}
        r = self.client.post('/api/v1/customers/bulk/', body, format='json')
        self.assertEqual(r.status_code, 402, r.data)
        self.assertEqual(r.json()['kind'], 'customer')
        self.assertEqual(
            Customer.objects.filter(owner=self.user, name__startswith='벌크').count(), 0)

    def test_bulk_partial_remaining_rejects_whole_batch_not_partial(self):
        """잔여 2(5-3)인데 3건 요청 → 전량 402(부분 생성 없음 — 2건만 만들고 끝내지 않는다)."""
        _consume_customer_quota(self.user, 3)
        body = {'customers': [{'name': 'A'}, {'name': 'B'}, {'name': 'C'}]}
        r = self.client.post('/api/v1/customers/bulk/', body, format='json')
        self.assertEqual(r.status_code, 402, r.data)
        self.assertEqual(
            Customer.objects.filter(owner=self.user, name__in=['A', 'B', 'C']).count(), 0)

    def test_bulk_within_remaining_creates_all(self):
        """잔여 2인데 2건 요청 → 통과, 2건 모두 생성."""
        _consume_customer_quota(self.user, 3)
        body = {'customers': [{'name': 'D'}, {'name': 'E'}]}
        r = self.client.post('/api/v1/customers/bulk/', body, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.json()['created'], 2)
        self.assertEqual(
            Customer.objects.filter(owner=self.user, name__in=['D', 'E']).count(), 2)


class CustomerQuotaBetaDormantTests(TestCase):
    """★ FREE_TIER_UNLIMITED=True(기본, 베타) → 고객 추가 한도는 dormant.

    지금 베타 사용자에게는 어떤 영향도 없어야 한다 — Free 한도(5)를 넘겨도 계속 생성된다.
    (default_settings에서 FREE_TIER_UNLIMITED 를 override 하지 않음 = 실제 배포 기본값과 동일)
    """

    def setUp(self):
        self.user, self.client = _make_planner('betaquota@test.com')
        _subscribe_free(self.user, limit_customer=5)

    def test_single_create_beyond_free_limit_still_succeeds(self):
        _consume_customer_quota(self.user, 999)
        r = self.client.post('/api/v1/customers/', {'name': '베타무제한'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)

    def test_bulk_beyond_free_limit_still_succeeds(self):
        body = {'customers': [{'name': f'베타{i}'} for i in range(10)]}
        r = self.client.post('/api/v1/customers/bulk/', body, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.json()['created'], 10)


class InboundLeadQuotaExclusionTests(TestCase):
    """★ 회귀(spec 2026-07-09): 인바운드 자동 리드(셀프진단 /d, 소개카드 /p)는 설계사의
    '신규 고객 추가' 한도를 소비하지 않는다 — 두 뷰 모두 Customer.objects.create()를 직접
    호출해 CustomerViewSet(perform_create/bulk_create)를 거치지 않기 때문이다. 한도가 이미
    완전히 소진된 설계사라도 잠재고객의 셀프진단·상담신청은 계속 성공해야 한다(그렇지 않으면
    고객이 셀프진단했다는 이유로 설계사의 한도가 깎이는 불합리가 생긴다).
    """

    def setUp(self):
        from django.core.cache import cache
        cache.clear()  # ScopedRateThrottle('self_diagnosis') 카운터 격리

    @override_settings(FREE_TIER_UNLIMITED=False)
    def test_self_diagnosis_lead_does_not_consume_customer_quota(self):
        planner, _ = _make_planner('inbound-diag@test.com')
        _subscribe_free(planner, limit_customer=5)
        _consume_customer_quota(planner, 5)  # 설계사 능동 한도 완전 소진

        public = APIClient()
        ref = planner.profile.ref_code
        r = public.post(f'/api/v1/d/{ref}/', {
            'name': '셀프진단고객', 'phone': '01099998888',
            'birth': '1990-01-01', 'gender': '1', 'consent_share': 'true',
        }, format='multipart')
        self.assertEqual(r.status_code, 201, r.data)  # 한도 소진과 무관하게 리드는 성공
        self.assertTrue(Customer.objects.filter(
            owner=planner, lead_source='self_diagnosis', name='셀프진단고객').exists())
        # UsageMeter('customer')는 여전히 5 — 인바운드 리드로 증가하지 않는다.
        ym = UsageMeter.current_month()
        meter = UsageMeter.objects.get(user=planner, action='customer', year_month=ym)
        self.assertEqual(meter.count, 5)

    @override_settings(FREE_TIER_UNLIMITED=False)
    def test_introduction_card_lead_does_not_consume_customer_quota(self):
        planner, _ = _make_planner('inbound-intro@test.com')
        _subscribe_free(planner, limit_customer=5)
        _consume_customer_quota(planner, 5)

        public = APIClient()
        ref = planner.profile.ref_code
        r = public.post(f'/api/v1/p/{ref}/',
                        {'name': '소개고객', 'phone': '010-2222-3333', 'agreed': True},
                        format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(Customer.objects.filter(
            owner=planner, lead_source='introduction', name='소개고객').exists())
        ym = UsageMeter.current_month()
        meter = UsageMeter.objects.get(user=planner, action='customer', year_month=ym)
        self.assertEqual(meter.count, 5)
