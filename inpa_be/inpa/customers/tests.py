"""고객 도메인 핵심 게이트 테스트.

★ 필수 2종:
  1) owner 격리 — 설계사 A가 B의 고객을 조회·수정·삭제할 수 없다.
  2) 병력 동의 게이트 — consent_overseas_at 없으면 병력 등록 412 차단, 동의 후 201.
+ 하위 라우트 owner 격리, ConsentLog append-only, 동의 생성 시 스냅샷 동기화 보강.
"""
from django.core import signing
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient
from django.test import TestCase, override_settings

from inpa.accounts.models import Profile, User

from .models import (
    ConsentLog, Customer, CustomerMedicalHistory, CustomerTag, PlannerBaseline,
)
from .presets import PRESET_ORIGIN_V0, PRESET_V0, iter_preset_rows
from .tokens import make_consent_token, read_consent_token


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
        self.assertEqual(CustomerMedicalHistory.objects.count(), 0)

    def test_medical_allowed_after_consent(self):
        """동의 후 → 201 등록 성공."""
        self.customer.consent_overseas_at = timezone.now()
        self.customer.save(update_fields=['consent_overseas_at'])
        r = self._post_medical()
        self.assertEqual(r.status_code, 201)
        self.assertEqual(CustomerMedicalHistory.objects.count(), 1)

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
        self.assertEqual(read_consent_token(token), self.customer.id)

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
        self.assertEqual(read_consent_token(body['token']), self.customer.id)

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
        self.assertFalse(body['already_consented'])
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
        r = self.public.post(f'/api/v1/c/{token}/', {'consent_overseas': 'true'}, format='json')
        self.assertEqual(r.status_code, 201)
        self.customer.refresh_from_db()
        self.assertIsNotNone(self.customer.consent_overseas_at)  # OCR 게이트 해제
        log = ConsentLog.objects.filter(customer=self.customer).latest('agreed_at')
        self.assertEqual(log.subject, ConsentLog.SUBJECT_CUSTOMER_SELF)

    def test_public_post_without_consent_412(self):
        token = make_consent_token(self.customer)
        r = self.public.post(f'/api/v1/c/{token}/', {}, format='json')
        self.assertEqual(r.status_code, 412)
        self.customer.refresh_from_db()
        self.assertIsNone(self.customer.consent_overseas_at)

    def test_public_post_idempotent(self):
        """재동의가 기존 스냅샷 시각을 덮지 않는다(append-only 정신)."""
        token = make_consent_token(self.customer)
        self.public.post(f'/api/v1/c/{token}/', {'consent_overseas': 'true'}, format='json')
        self.customer.refresh_from_db()
        first = self.customer.consent_overseas_at
        self.public.post(f'/api/v1/c/{token}/', {'consent_overseas': 'true'}, format='json')
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.consent_overseas_at, first)

    @override_settings(REQUIRE_CUSTOMER_SELF_CONSENT=True)
    def test_customer_self_unlocks_in_strict_mode(self):
        """전방검증: strict 모드여도 고객 본인 동의는 정상적으로 게이트를 연다."""
        token = make_consent_token(self.customer)
        r = self.public.post(f'/api/v1/c/{token}/', {'consent_overseas': 'true'}, format='json')
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
    """★ v0 스타터 프리셋 적용 — 생성·owner 격리·멱등·검증·준법 게이트."""

    URL = '/api/v1/planner-baselines/apply-preset/'
    NONLIFE = PlannerBaseline.PRODUCT_GROUP_NONLIFE   # 2 (프리셋 행 다수)
    ANNUITY = PlannerBaseline.PRODUCT_GROUP_ANNUITY   # 4 (v0 빈 프리셋)

    def setUp(self):
        self.user_a, self.client_a = _make_planner('preset-a@test.com')
        self.user_b, self.client_b = _make_planner('preset-b@test.com')

    @staticmethod
    def _expected_rows(product_group):
        return list(iter_preset_rows(product_group))

    def test_apply_creates_baselines_for_owner(self):
        """프리셋 적용 → 해당 상품군 전체 행 생성, owner=요청자, source/origin 라벨 고정."""
        expected = self._expected_rows(self.NONLIFE)
        self.assertGreater(len(expected), 0)  # 손해는 프리셋 행이 있어야 의미 있는 테스트

        r = self.client_a.post(self.URL, {'product_group': self.NONLIFE}, format='json')
        self.assertEqual(r.status_code, 201)
        body = r.json()
        self.assertEqual(body['created'], len(expected))
        self.assertEqual(body['preset_origin'], PRESET_ORIGIN_V0)
        self.assertIn('검토', body['note'])  # 한계 고지 문구 존재(정직성 레드라인)

        qs = PlannerBaseline.objects.filter(owner=self.user_a, product_group=self.NONLIFE)
        self.assertEqual(qs.count(), len(expected))
        for b in qs:
            self.assertEqual(b.owner_id, self.user_a.id)
            self.assertEqual(b.baseline_source, 'preset')   # ★ graded 게이트 ON
            self.assertEqual(b.preset_origin, PRESET_ORIGIN_V0)
            self.assertTrue(b.is_active)
            self.assertEqual(b.unit, 1)

    def test_apply_is_idempotent(self):
        """재적용 시 중복 생성 없음(created=0) — 설계사 수정값 보존 멱등."""
        r1 = self.client_a.post(self.URL, {'product_group': self.NONLIFE}, format='json')
        first = r1.json()['created']
        self.assertGreater(first, 0)
        count_after_first = PlannerBaseline.objects.filter(owner=self.user_a).count()

        r2 = self.client_a.post(self.URL, {'product_group': self.NONLIFE}, format='json')
        self.assertEqual(r2.status_code, 201)
        self.assertEqual(r2.json()['created'], 0)
        # 행 수 불변(멱등)
        self.assertEqual(
            PlannerBaseline.objects.filter(owner=self.user_a).count(),
            count_after_first)

    def test_idempotent_preserves_planner_edits(self):
        """설계사가 프리셋 행을 직접 수정해도 재적용이 덮어쓰지 않는다."""
        self.client_a.post(self.URL, {'product_group': self.NONLIFE}, format='json')
        b = PlannerBaseline.objects.filter(owner=self.user_a).first()
        b.recommend_min = 99999
        b.baseline_source = 'planner'  # 설계사가 직접 확정한 값으로 전환
        b.save(update_fields=['recommend_min', 'baseline_source'])

        r = self.client_a.post(self.URL, {'product_group': self.NONLIFE}, format='json')
        self.assertEqual(r.json()['created'], 0)
        b.refresh_from_db()
        self.assertEqual(float(b.recommend_min), 99999)      # 보존
        self.assertEqual(b.baseline_source, 'planner')       # 프리셋이 훼손하지 않음

    def test_owner_isolation(self):
        """A 적용은 B 데이터에 영향 없음 — owner 격리."""
        self.client_a.post(self.URL, {'product_group': self.NONLIFE}, format='json')
        self.assertEqual(
            PlannerBaseline.objects.filter(owner=self.user_b).count(), 0)
        # B가 적용해도 A 행 수에 영향 없음
        a_count = PlannerBaseline.objects.filter(owner=self.user_a).count()
        self.client_b.post(self.URL, {'product_group': self.NONLIFE}, format='json')
        self.assertEqual(
            PlannerBaseline.objects.filter(owner=self.user_a).count(), a_count)
        self.assertGreater(
            PlannerBaseline.objects.filter(owner=self.user_b).count(), 0)

    def test_empty_product_group_returns_zero(self):
        """v0 미정의 상품군(연금) → 정상 201 + created=0(거짓 성공 아님)."""
        self.assertEqual(len(self._expected_rows(self.ANNUITY)), 0)
        r = self.client_a.post(self.URL, {'product_group': self.ANNUITY}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()['created'], 0)

    def test_missing_product_group_400(self):
        r = self.client_a.post(self.URL, {}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_invalid_product_group_400(self):
        """허용 코드 밖(99) → 400."""
        r = self.client_a.post(self.URL, {'product_group': 99}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_non_integer_product_group_400(self):
        r = self.client_a.post(self.URL, {'product_group': 'abc'}, format='json')
        self.assertEqual(r.status_code, 400)

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

    def test_preset_coverage_keys_match_standard_tree(self):
        """★ 매칭 무결성: 프리셋 coverage_key 는 표준 담보 트리(seed) 표준 담보명과 일치해야
        히트맵/비교 판정에서 매칭된다. 시드 후 모든 coverage_key 가 표준 담보로 존재함을 검증."""
        from django.core.management import call_command
        from inpa.analysis.models import AnalysisDetail

        call_command('seed_normalization', verbosity=0)
        std_names = set(AnalysisDetail.objects.values_list('name', flat=True))

        preset_keys = set()
        for groups in PRESET_V0.values():
            for coverage_key, _bands in groups:
                preset_keys.add(coverage_key)

        missing = preset_keys - std_names
        self.assertEqual(missing, set(),
                         f'표준 담보 트리에 없는 프리셋 coverage_key: {missing}')
