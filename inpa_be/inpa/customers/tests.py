"""고객 도메인 핵심 게이트 테스트.

★ 필수 2종:
  1) owner 격리 — 설계사 A가 B의 고객을 조회·수정·삭제할 수 없다.
  2) 병력 동의 게이트 — consent_overseas_at 없으면 병력 등록 412 차단, 동의 후 201.
+ 하위 라우트 owner 격리, ConsentLog append-only, 동의 생성 시 스냅샷 동기화 보강.
"""
from django.utils import timezone
from rest_framework.test import APIClient
from django.test import TestCase

from inpa.accounts.models import Profile, User

from .models import ConsentLog, Customer, CustomerMedicalHistory, CustomerTag


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


class MedicalConsentGateTests(TestCase):
    """★ 병력 동의 게이트 — consent_overseas_at 없으면 병력 등록 412 차단."""

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

    def test_consent_log_syncs_snapshot(self):
        """overseas_medical 동의 로그 생성 → Customer.consent_overseas_at 스냅샷 동기화 → 병력 등록 가능."""
        r = self.client.post(
            f'/api/v1/customers/{self.customer.id}/consents/',
            {'scope': ConsentLog.SCOPE_OVERSEAS_MEDICAL, 'doc_version': 'OVERSEAS-v1.0'},
            format='json')
        self.assertEqual(r.status_code, 201)
        self.customer.refresh_from_db()
        self.assertIsNotNone(self.customer.consent_overseas_at)
        # 게이트 해제 확인
        r2 = self._post_medical()
        self.assertEqual(r2.status_code, 201)

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
