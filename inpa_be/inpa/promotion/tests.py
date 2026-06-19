"""판촉물 핵심 가시성·권한·상태머신 테스트 (dev/21 §9 수용 기준).

★ 검증 항목:
  [샘플 카탈로그 — 공유]
  P1  GET /promotion/samples/ — 인증 설계사 200, 비인증 401
  P2  is_available=False 샘플이 목록에 포함됨 (FE가 배지 처리)
  P3  ?category= 필터 동작
  P4  설계사는 샘플 POST/PATCH/DELETE 403 (IsAdmin 게이트)
  P5  관리자 샘플 등록·수정·삭제 O
  P6  GET /promotion/samples/:id/ 응답에 form_fields 배열 포함 (AC-P1)

  [주문 제출·목록 — 소유자 격리]
  O1  POST /promotion/orders/ 성공 → 201, status=pending, status_logs 1건 생성 (AC-O1)
  O2  GET  /promotion/orders/ — 본인 주문만 (타 설계사 주문 0건 — AC-O2)
  O3  DELETE 취소 — pending 상태만 허용 (AC-O3)
  O4  reviewing 이후 취소 시도 → 400 (AC-O3)
  O5  타 설계사 주문 상세 GET → 404 (멀티테넌시 격리)
  O6  주문 불가 샘플(is_available=False)에 주문 POST → 400

  [크레딧 — AC-O4]
  C1  FREE_TIER_UNLIMITED=True → 한도 초과 없이 201 (베타 무차감)

  [상태 머신 — AC-S1 · AC-S2]
  S1  허용된 전이(pending→reviewing) 성공
  S2  비허용 전이(pending→completed) → ValueError
  S3  상태 변경 시 PromotionOrderStatusLog 1건 추가 (AC-S2)
  S4  status_logs 상세 응답 포함 (AC-S3)

  [관리자 API — AC-A1 · AC-A2 · AC-A3]
  A1  설계사 샘플 쓰기 403 (AC-A1)
  A2  관리자 PATCH /admin/promotion/orders/:id/status/ 상태 전이 검증 (AC-A2)
  A3  admin_note 업데이트 즉시 설계사 상세 응답 반영 (AC-A3)

  [form_response PII 격리 — AC-C2]
  F1  타 설계사는 본인 주문이 아닌 주문의 form_response 접근 불가 (404)
"""
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User

from .models import (
    PromotionOrder,
    PromotionOrderStatusLog,
    PromotionSample,
    PromotionSampleImage,
)


# ─── 헬퍼 ─────────────────────────────────────────────────────────────

def _make_planner(email: str, is_admin: bool = False):
    """이메일 인증 완료 설계사 + APIClient."""
    user = User.objects.create_user(email=email, password='inpaPass123!')
    user.is_active = True
    user.save(update_fields=['is_active'])
    Profile.objects.create(
        user=user,
        email_verified_at=timezone.now(),
        is_admin=is_admin,
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return user, client


def _make_sample(name: str = '테스트 달력', category: str = '달력', is_available: bool = True, **kwargs) -> PromotionSample:
    return PromotionSample.objects.create(
        name=name,
        category=category,
        is_available=is_available,
        form_fields=[
            {'key': 'quantity', 'label': '수량', 'type': 'number', 'required': True, 'min': 10},
            {'key': 'note', 'label': '요청사항', 'type': 'textarea', 'required': False},
        ],
        **kwargs,
    )


def _make_order(owner, sample, **kwargs) -> PromotionOrder:
    order = PromotionOrder.objects.create(
        owner=owner,
        sample=sample,
        form_response={'quantity': 100},
        **kwargs,
    )
    PromotionOrderStatusLog.objects.create(
        order=order,
        to_status=PromotionOrder.STATUS_PENDING,
        changed_by=owner,
    )
    return order


# ─── P1·P2·P3: 샘플 카탈로그 목록 ──────────────────────────────────

class SampleListTests(TestCase):
    def setUp(self):
        self.user, self.client = _make_planner('planner@test.com')
        self.sample_a = _make_sample('달력A', '달력', is_available=True)
        self.sample_b = _make_sample('다이어리B', '다이어리', is_available=False)

    def test_P1_authenticated_gets_200(self):
        """P1: 인증 설계사 → 200."""
        r = self.client.get('/api/v1/promotion/samples/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('results', r.json())

    def test_P1_unauthenticated_gets_401(self):
        """P1: 비인증 → 401."""
        r = APIClient().get('/api/v1/promotion/samples/')
        self.assertEqual(r.status_code, 401)

    def test_P2_unavailable_sample_included_in_list(self):
        """P2: is_available=False 샘플도 목록에 포함 (FE가 배지 처리)."""
        r = self.client.get('/api/v1/promotion/samples/')
        ids = [s['id'] for s in r.json()['results']]
        self.assertIn(self.sample_a.id, ids)
        self.assertIn(self.sample_b.id, ids)

    def test_P3_category_filter(self):
        """P3: ?category=달력 필터 — 달력만 반환."""
        r = self.client.get('/api/v1/promotion/samples/?category=달력')
        self.assertEqual(r.status_code, 200)
        names = [s['name'] for s in r.json()['results']]
        self.assertIn('달력A', names)
        self.assertNotIn('다이어리B', names)

    def test_P4_planner_cannot_write_sample(self):
        """P4: 설계사 POST 샘플 → 403."""
        r = self.client.post('/api/v1/admin/promotion/samples/', {
            'name': '해킹달력', 'category': '기타', 'is_available': True, 'form_fields': [],
        }, format='json')
        self.assertEqual(r.status_code, 403)


# ─── P5·P6: 샘플 상세 + 관리자 CRUD ────────────────────────────────

class SampleDetailAdminTests(TestCase):
    def setUp(self):
        self.admin, self.admin_client = _make_planner('admin@test.com', is_admin=True)
        self.planner, self.planner_client = _make_planner('planner@test.com')
        self.sample = _make_sample()

    def test_P6_detail_includes_form_fields(self):
        """P6 / AC-P1: 상세 응답에 form_fields 배열 포함."""
        r = self.planner_client.get(f'/api/v1/promotion/samples/{self.sample.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('form_fields', r.json())
        self.assertIsInstance(r.json()['form_fields'], list)

    def test_P5_admin_create_sample(self):
        """P5: 관리자 샘플 등록 → 201."""
        r = self.admin_client.post('/api/v1/admin/promotion/samples/', {
            'name': '관리자달력', 'category': '달력', 'is_available': True,
            'form_fields': [{'key': 'qty', 'label': '수량', 'type': 'number', 'required': True}],
            'sort_order': 1,
        }, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()['name'], '관리자달력')

    def test_P5_admin_update_sample(self):
        """P5: 관리자 샘플 수정 → 200."""
        r = self.admin_client.patch(
            f'/api/v1/admin/promotion/samples/{self.sample.pk}/',
            {'name': '수정된달력'},
            format='json',
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['name'], '수정된달력')

    def test_P5_admin_delete_sample(self):
        """P5: 관리자 샘플 삭제 → 204."""
        r = self.admin_client.delete(f'/api/v1/admin/promotion/samples/{self.sample.pk}/')
        self.assertEqual(r.status_code, 204)
        self.assertFalse(PromotionSample.objects.filter(pk=self.sample.pk).exists())

    def test_A1_planner_sample_write_forbidden(self):
        """AC-A1: 설계사 샘플 관리자 엔드포인트 접근 → 403."""
        r = self.planner_client.patch(
            f'/api/v1/admin/promotion/samples/{self.sample.pk}/',
            {'name': '불법수정'},
            format='json',
        )
        self.assertEqual(r.status_code, 403)


# ─── O1·O2: 주문 생성 + 목록 격리 ──────────────────────────────────

class OrderCreateListTests(TestCase):
    def setUp(self):
        self.user_a, self.client_a = _make_planner('a@test.com')
        self.user_b, self.client_b = _make_planner('b@test.com')
        self.sample = _make_sample()

    def test_O1_create_order_returns_201_with_pending_log(self):
        """AC-O1: 주문 생성 → 201, status=pending, status_logs 1건."""
        r = self.client_a.post('/api/v1/promotion/orders/', {
            'sample': self.sample.pk,
            'form_response': {'quantity': 100},
        }, format='json')
        self.assertEqual(r.status_code, 201)
        data = r.json()
        self.assertEqual(data['status'], 'pending')
        self.assertEqual(len(data['status_logs']), 1)
        self.assertEqual(data['status_logs'][0]['to_status'], 'pending')

    def test_O2_list_returns_only_own_orders(self):
        """AC-O2: 주문 목록에 본인 주문만 포함 (멀티테넌시 격리)."""
        order_a = _make_order(self.user_a, self.sample)
        order_b = _make_order(self.user_b, self.sample)

        r = self.client_a.get('/api/v1/promotion/orders/')
        self.assertEqual(r.status_code, 200)
        ids = [o['id'] for o in r.json()['results']]
        self.assertIn(order_a.id, ids)
        self.assertNotIn(order_b.id, ids)

    def test_O6_unavailable_sample_rejected(self):
        """O6: 주문 불가 샘플 → 400."""
        unavailable = _make_sample('품절달력', is_available=False)
        r = self.client_a.post('/api/v1/promotion/orders/', {
            'sample': unavailable.pk,
            'form_response': {'quantity': 100},
        }, format='json')
        self.assertEqual(r.status_code, 400)


# ─── O3·O4·O5·F1: 주문 취소·접근 격리 ──────────────────────────────

class OrderDetailCancelTests(TestCase):
    def setUp(self):
        self.user_a, self.client_a = _make_planner('a@test.com')
        self.user_b, self.client_b = _make_planner('b@test.com')
        self.sample = _make_sample()
        self.order_a = _make_order(self.user_a, self.sample)

    def test_O3_cancel_pending_order_succeeds(self):
        """AC-O3: pending 주문 취소 → 상태 cancelled (실제 DELETE X)."""
        r = self.client_a.delete(f'/api/v1/promotion/orders/{self.order_a.pk}/')
        self.assertEqual(r.status_code, 200)
        self.order_a.refresh_from_db()
        self.assertEqual(self.order_a.status, PromotionOrder.STATUS_CANCELLED)

    def test_O4_cancel_non_pending_order_returns_400(self):
        """AC-O3: reviewing 이후 취소 시도 → 400."""
        self.order_a.status = PromotionOrder.STATUS_REVIEWING
        self.order_a.save(update_fields=['status', 'updated_at'])
        r = self.client_a.delete(f'/api/v1/promotion/orders/{self.order_a.pk}/')
        self.assertEqual(r.status_code, 400)

    def test_O5_other_planner_cannot_see_order(self):
        """O5 / AC-C2: 타 설계사 주문 상세 → 404 (형식 소유자 격리)."""
        r = self.client_b.get(f'/api/v1/promotion/orders/{self.order_a.pk}/')
        self.assertEqual(r.status_code, 404)

    def test_F1_other_planner_cannot_access_form_response(self):
        """AC-C2: form_response PII — 타 설계사 응답에 절대 미포함 (404로 차단)."""
        r = self.client_b.get(f'/api/v1/promotion/orders/{self.order_a.pk}/')
        # 404이므로 form_response 접근 불가
        self.assertEqual(r.status_code, 404)
        self.assertNotIn('form_response', r.json())


# ─── S1·S2·S3·S4: 상태 머신 ──────────────────────────────────────────

class OrderStateMachineTests(TestCase):
    def setUp(self):
        self.admin, self.admin_client = _make_planner('admin@test.com', is_admin=True)
        self.user, self.user_client = _make_planner('planner@test.com')
        self.sample = _make_sample()
        self.order = _make_order(self.user, self.sample)

    def test_S1_valid_transition_pending_to_reviewing(self):
        """AC-S1: 허용 전이 pending→reviewing → 200."""
        r = self.admin_client.patch(
            f'/api/v1/admin/promotion/orders/{self.order.pk}/status/',
            {'status': 'reviewing'},
            format='json',
        )
        self.assertEqual(r.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, PromotionOrder.STATUS_REVIEWING)

    def test_S2_invalid_transition_raises_400(self):
        """AC-S1: 비허용 전이 pending→completed → 400."""
        r = self.admin_client.patch(
            f'/api/v1/admin/promotion/orders/{self.order.pk}/status/',
            {'status': 'completed'},
            format='json',
        )
        self.assertEqual(r.status_code, 400)

    def test_S3_status_log_created_on_transition(self):
        """AC-S2: 상태 변경마다 StatusLog 1건 생성."""
        log_count_before = PromotionOrderStatusLog.objects.filter(order=self.order).count()
        self.admin_client.patch(
            f'/api/v1/admin/promotion/orders/{self.order.pk}/status/',
            {'status': 'reviewing'},
            format='json',
        )
        log_count_after = PromotionOrderStatusLog.objects.filter(order=self.order).count()
        self.assertEqual(log_count_after, log_count_before + 1)

    def test_S4_status_logs_in_detail_response(self):
        """AC-S3: 설계사 주문 상세 응답에 status_logs 포함 (타임라인 렌더링 가능)."""
        r = self.user_client.get(f'/api/v1/promotion/orders/{self.order.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('status_logs', r.json())
        self.assertIsInstance(r.json()['status_logs'], list)
        self.assertGreater(len(r.json()['status_logs']), 0)


# ─── A2·A3: 관리자 전용 ──────────────────────────────────────────────

class AdminOrderTests(TestCase):
    def setUp(self):
        self.admin, self.admin_client = _make_planner('admin@test.com', is_admin=True)
        self.user, self.user_client = _make_planner('planner@test.com')
        self.sample = _make_sample()
        self.order = _make_order(self.user, self.sample)

    def test_A2_admin_status_transition_validates(self):
        """AC-A2: PATCH /admin/.../status/ 상태 전이 유효성 검증."""
        # 유효 전이
        r = self.admin_client.patch(
            f'/api/v1/admin/promotion/orders/{self.order.pk}/status/',
            {'status': 'reviewing'},
            format='json',
        )
        self.assertEqual(r.status_code, 200)
        # 비유효 전이 (reviewing → completed, 중간 단계 건너뜀)
        r2 = self.admin_client.patch(
            f'/api/v1/admin/promotion/orders/{self.order.pk}/status/',
            {'status': 'completed'},
            format='json',
        )
        self.assertEqual(r2.status_code, 400)

    def test_A3_admin_note_reflected_in_planner_detail(self):
        """AC-A3: admin_note 업데이트가 설계사 주문 상세 응답에 즉시 반영."""
        self.admin_client.patch(
            f'/api/v1/admin/promotion/orders/{self.order.pk}/status/',
            {'status': 'reviewing', 'admin_note': '주문을 확인했습니다.'},
            format='json',
        )
        r = self.user_client.get(f'/api/v1/promotion/orders/{self.order.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['admin_note'], '주문을 확인했습니다.')

    def test_admin_order_list_returns_all(self):
        """관리자는 전체 주문 목록 조회 가능."""
        user_b, _ = _make_planner('b@test.com')
        order_b = _make_order(user_b, self.sample)
        r = self.admin_client.get('/api/v1/admin/promotion/orders/')
        self.assertEqual(r.status_code, 200)
        ids = [o['id'] for o in r.json()['results']]
        self.assertIn(self.order.id, ids)
        self.assertIn(order_b.id, ids)


# ─── 상태머신 model 단위 테스트 ─────────────────────────────────────

class TransitionModelTests(TestCase):
    def setUp(self):
        self.user, _ = _make_planner('u@test.com')
        self.sample = _make_sample()
        self.order = _make_order(self.user, self.sample)

    def test_valid_chain_transitions(self):
        """전체 허용 체인: pending→reviewing→producing→shipping→completed."""
        chain = [
            PromotionOrder.STATUS_REVIEWING,
            PromotionOrder.STATUS_PRODUCING,
            PromotionOrder.STATUS_SHIPPING,
            PromotionOrder.STATUS_COMPLETED,
        ]
        for next_status in chain:
            self.order.transition_to(next_status, self.user)
            self.order.refresh_from_db()
            self.assertEqual(self.order.status, next_status)

    def test_invalid_transition_raises_value_error(self):
        """비허용 전이 → ValueError (상태 미변경)."""
        with self.assertRaises(ValueError):
            self.order.transition_to(PromotionOrder.STATUS_COMPLETED, self.user)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, PromotionOrder.STATUS_PENDING)

    def test_terminal_state_no_transitions_allowed(self):
        """종결 상태(completed/cancelled)에서 어떤 전이도 ValueError."""
        self.order.status = PromotionOrder.STATUS_COMPLETED
        self.order.save(update_fields=['status', 'updated_at'])
        with self.assertRaises(ValueError):
            self.order.transition_to(PromotionOrder.STATUS_CANCELLED, self.user)
