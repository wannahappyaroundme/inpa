"""공유뷰 + 북극성 계측 게이트 테스트 (dev/13).

흐름 검증(작업 지시 필수):
  1) 공유 생성 (POST /customers/<id>/share/) → 토큰 발급 + share_created 적재
  2) GET 공유뷰 (/s/<token>/) → 200 + neutral 강제 + baseline 부재 + 면책 + share_view 적재
  3) POST 이벤트 (/s/<token>/event/) → clipboard_copy 적재
  4) 만료/없는 토큰 → 404 (데이터 0)

+ 컴플라이언스 레드라인: 부족/충분 단정 부재(status none|neutral), PII 마스킹,
  noindex 헤더, viewer_fp 중복제거, 봇 UA 제외, owner 격리.
"""
import uuid

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User
from inpa.analysis.models import (
    AnalysisCategory, AnalysisDetail, AnalysisSubCategory,
)
from inpa.analytics.models import NorthStarEvent
from inpa.customers.models import Customer
from inpa.insurances.models import (
    CustomerInsurance, CustomerInsuranceDetail, InsuranceCategory,
    InsuranceDetail, InsuranceSubCategory,
)


def _make_planner(email):
    user = User.objects.create_user(email=email, password='inpaPass123!')
    user.is_active = True
    user.save(update_fields=['is_active'])
    Profile.objects.create(user=user, email_verified_at=timezone.now())
    client = APIClient()
    client.force_authenticate(user=user)
    return user, client


def _build_std_tree():
    cat = AnalysisCategory.objects.create(insurance_type=2, name='상해', order=1)
    sub = AnalysisSubCategory.objects.create(insurance_type=2, category=cat,
                                             name='사망/후유', order=1)
    det = AnalysisDetail.objects.create(sub_category=sub, name='사망보장', order=1)
    return det


def _catalog_detail_linked_to(analysis_detail):
    icat = InsuranceCategory.objects.create(insurance_type=2, name='손보상품', order=1)
    isub = InsuranceSubCategory.objects.create(insurance_type=2, category=icat,
                                               name='보장', order=1)
    idet = InsuranceDetail.objects.create(sub_category=isub, name='사망담보', order=1)
    idet.analysis_detail.add(analysis_detail)
    return idet


def _make_portfolio(customer, catalog_detail, assurance_amount):
    ci = CustomerInsurance.objects.create(
        customer=customer, insurance_type=2, name='테스트보험',
        portfolio_type=1, payment_period_type=1, payment_period=20,
        monthly_premiums=50000, monthly_assurance_premium=50000,
    )
    CustomerInsuranceDetail.objects.create(
        insurance=ci, detail=catalog_detail,
        assurance_amount=assurance_amount, premium=10000,
        payment_period_type=1, payment_period=20,
        warranty_period_type=1, warranty_period='100',
    )
    ci.set_renewal_month()
    ci.calculate()
    ci.save()
    return ci


class ShareCreateTests(TestCase):
    """1) 공유 토큰 발급 — POST /customers/<id>/share/."""

    def setUp(self):
        self.user, self.client = _make_planner('share-create@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='공유고객', birth_day='1985.05.05', gender=1)

    def test_create_share_rotates_token_and_logs(self):
        old_token = self.customer.share_token
        r = self.client.post(f'/api/v1/customers/{self.customer.id}/share/')
        self.assertEqual(r.status_code, 201)
        body = r.json()
        # rotate — 새 토큰 발급(구 토큰 무효)
        self.customer.refresh_from_db()
        self.assertNotEqual(str(old_token), body['share_token'])
        self.assertEqual(str(self.customer.share_token), body['share_token'])
        self.assertIsNotNone(self.customer.share_expires_at)
        # share_created 1건 적재
        self.assertEqual(
            NorthStarEvent.objects.filter(
                event_type=NorthStarEvent.SHARE_CREATED,
                customer=self.customer, sender=self.user).count(), 1)

    def test_create_share_owner_isolation(self):
        """A는 B 고객 공유 토큰을 발급할 수 없다 → 404."""
        _, client_b = _make_planner('share-create-b@test.com')
        r = client_b.post(f'/api/v1/customers/{self.customer.id}/share/')
        self.assertEqual(r.status_code, 404)

    def test_create_share_requires_auth(self):
        c = APIClient()
        r = c.post(f'/api/v1/customers/{self.customer.id}/share/')
        self.assertEqual(r.status_code, 401)


class ShareViewTests(TestCase):
    """2) 공유뷰 GET /s/<token>/ — 200 + neutral + 면책 + share_view 적재."""

    def setUp(self):
        self.user, self.client = _make_planner('share-view@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='홍길동', birth_day='1985.05.05', gender=1)
        self.det = _build_std_tree()
        self.idet = _catalog_detail_linked_to(self.det)
        _make_portfolio(self.customer, self.idet, assurance_amount=50000000)
        self.public = APIClient()  # 비인증

    def _url(self):
        return f'/api/v1/s/{self.customer.share_token}/'

    def test_share_view_returns_200_neutral(self):
        r = self.public.get(self._url())
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body['mode'], 'neutral')
        self.assertIn('disclaimer', body)
        # ★ 부족/충분 단정 부재 — status 는 none|neutral 만, baseline 키 물리 부재
        for cat in body['tree']:
            for sub in cat['sub_categories']:
                for det in sub['details']:
                    self.assertIn(det['status'], ('none', 'neutral'))
                    self.assertNotIn('baseline', det)

    def test_share_view_held_amount_visible(self):
        r = self.public.get(self._url())
        body = r.json()
        held = body['tree'][0]['sub_categories'][0]['details'][0]['held_amount']
        self.assertEqual(held, 50000000)
        # 보유 담보 → status='neutral'(보유 사실), 0원이면 'none'
        self.assertEqual(
            body['tree'][0]['sub_categories'][0]['details'][0]['status'], 'neutral')

    def test_share_view_pii_masked(self):
        r = self.public.get(self._url())
        cust = r.json()['customer']
        self.assertEqual(cust['name_masked'], '홍**')          # 이름 마스킹
        self.assertEqual(cust['birth_year'], 1985)             # 연도만(생월일 부재)
        self.assertNotIn('mobile_phone_number', cust)          # 연락처 부재
        self.assertNotIn('medical_histories', cust)            # 병력 부재

    def test_share_view_logs_share_view_event(self):
        self.public.get(self._url())
        self.assertEqual(
            NorthStarEvent.objects.filter(
                event_type=NorthStarEvent.SHARE_VIEW,
                share_token=self.customer.share_token).count(), 1)

    def test_share_view_dedup_within_24h(self):
        """동일 viewer_fp 24h 내 재열람 → share_view 1건만(분모 오염 방지)."""
        self.public.get(self._url())
        self.public.get(self._url())  # 같은 클라이언트(동일 지문)
        self.assertEqual(
            NorthStarEvent.objects.filter(
                event_type=NorthStarEvent.SHARE_VIEW,
                share_token=self.customer.share_token).count(), 1)

    def test_share_view_bot_ua_excluded_as_bot_channel(self):
        """카톡 프리뷰 봇 UA → channel='bot'(신뢰 KPI 분자 제외)."""
        self.public.get(self._url(), HTTP_USER_AGENT='KaKaoTalk-Scrap/1.0')
        ev = NorthStarEvent.objects.get(
            event_type=NorthStarEvent.SHARE_VIEW,
            share_token=self.customer.share_token)
        self.assertEqual(ev.channel, 'bot')

    def test_share_view_noindex_header(self):
        r = self.public.get(self._url())
        self.assertEqual(r['X-Robots-Tag'], 'noindex, nofollow')

    def test_share_view_updates_user_view_at(self):
        self.public.get(self._url())
        self.customer.refresh_from_db()
        self.assertIsNotNone(self.customer.user_view_at)

    def test_share_view_records_ref_code(self):
        self.public.get(self._url() + '?ref=A7K3XX')
        ev = NorthStarEvent.objects.get(
            event_type=NorthStarEvent.SHARE_VIEW,
            share_token=self.customer.share_token)
        self.assertEqual(ev.ref_code, 'A7K3XX')


class ShareViewGateTests(TestCase):
    """4) 만료/회수/없는 토큰 → 404 (데이터 0)."""

    def setUp(self):
        self.user, _ = _make_planner('share-gate@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='만료고객', birth_day='1985.05.05')
        self.public = APIClient()

    def test_expired_token_returns_404_no_data(self):
        self.customer.share_expires_at = timezone.now() - timezone.timedelta(days=1)
        self.customer.save(update_fields=['share_expires_at'])
        r = self.public.get(f'/api/v1/s/{self.customer.share_token}/')
        self.assertEqual(r.status_code, 404)
        body = r.json()
        self.assertEqual(body['reason'], 'SHARE_LINK_EXPIRED')
        self.assertNotIn('tree', body)        # 데이터 0
        self.assertNotIn('customer', body)

    def test_unknown_token_returns_404(self):
        r = self.public.get(f'/api/v1/s/{uuid.uuid4()}/')
        self.assertEqual(r.status_code, 404)

    def test_malformed_token_404(self):
        """UUID 형식 아님 → 라우트 미매칭 404(존재 은폐)."""
        r = self.public.get('/api/v1/s/not-a-uuid/')
        self.assertEqual(r.status_code, 404)


class ShareEventTests(TestCase):
    """3) 공유뷰 이벤트 적재 — POST /s/<token>/event/."""

    def setUp(self):
        self.user, _ = _make_planner('share-event@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='이벤트고객', birth_day='1985.05.05')
        self.public = APIClient()

    def _url(self):
        return f'/api/v1/s/{self.customer.share_token}/event/'

    def test_clipboard_copy_logged_with_clipboard_channel(self):
        r = self.public.post(self._url(),
                             {'event_type': 'clipboard_copy'}, format='json')
        self.assertEqual(r.status_code, 201)
        ev = NorthStarEvent.objects.get(
            event_type=NorthStarEvent.CLIPBOARD_COPY,
            share_token=self.customer.share_token)
        # ★ 자동발송 사칭 금지 — channel='clipboard' 고정
        self.assertEqual(ev.channel, 'clipboard')
        self.assertEqual(ev.payload.get('delivery'), 'clipboard')

    def test_disallowed_event_rejected(self):
        """비인증 공유뷰에서 임의 이벤트 위조 차단 (화이트리스트 외 400)."""
        r = self.public.post(self._url(),
                             {'event_type': 'referral_attributed'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['code'], 'EVENT_NOT_ALLOWED')

    def test_event_on_expired_token_404(self):
        self.customer.share_expires_at = timezone.now() - timezone.timedelta(days=1)
        self.customer.save(update_fields=['share_expires_at'])
        r = self.public.post(self._url(),
                             {'event_type': 'clipboard_copy'}, format='json')
        self.assertEqual(r.status_code, 404)


class ShareFullFlowTests(TestCase):
    """End-to-end: 공유 생성 → 다른 기기 열람 → 복사 (북극성 곱셈 첫 항 증명)."""

    def setUp(self):
        self.user, self.client = _make_planner('flow@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='플로우고객', birth_day='1990.01.01', gender=2)
        det = _build_std_tree()
        idet = _catalog_detail_linked_to(det)
        _make_portfolio(self.customer, idet, assurance_amount=30000000)

    def test_create_then_view_then_copy(self):
        # 1) 설계사가 공유 생성
        r1 = self.client.post(f'/api/v1/customers/{self.customer.id}/share/')
        self.assertEqual(r1.status_code, 201)
        token = r1.json()['share_token']

        # 2) 다른 기기(비인증 공개)에서 열람 → share_view 적재
        viewer = APIClient()
        r2 = viewer.get(f'/api/v1/s/{token}/')
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()['mode'], 'neutral')

        # 3) 공유뷰에서 복사 → clipboard_copy 적재
        r3 = viewer.post(f'/api/v1/s/{token}/event/',
                         {'event_type': 'clipboard_copy'}, format='json')
        self.assertEqual(r3.status_code, 201)

        # 북극성 깔때기 3종 적재 확인 (create → view → copy)
        self.assertTrue(NorthStarEvent.objects.filter(
            event_type=NorthStarEvent.SHARE_CREATED, share_token=token).exists())
        self.assertTrue(NorthStarEvent.objects.filter(
            event_type=NorthStarEvent.SHARE_VIEW, share_token=token).exists())
        self.assertTrue(NorthStarEvent.objects.filter(
            event_type=NorthStarEvent.CLIPBOARD_COPY, share_token=token).exists())
