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

from django.conf import settings
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User
from inpa.analysis.models import (
    AnalysisCategory, AnalysisDetail, AnalysisSubCategory,
)
from inpa.analytics.events import log_event
from inpa.analytics.models import NorthStarEvent
from inpa.analytics.sharing import PAYLOAD_VERSION_V2
from inpa.customers.models import ConsentLog, Customer
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

    def test_share_view_excludes_planner_verdict(self):
        """★ 회귀 가드(§97): 설계사 내부 판정(verdict·switch_warnings)은 고객 공유뷰에 절대 누수 금지."""
        import json
        body = self.public.get(self._url()).json()
        self.assertNotIn('verdict', body)
        self.assertNotIn('switch_warnings', body)
        # 중첩 누수까지 차단 — 직렬화 전체 문자열에 키가 없어야 한다.
        raw = json.dumps(body, ensure_ascii=False)
        self.assertNotIn('verdict', raw)
        self.assertNotIn('switch_warnings', raw)

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

    def test_share_view_no_booking_url_without_work_hours(self):
        """영업시간 미설정 → booking_url 키 부재(FE는 기존 안내문으로 폴백)."""
        body = self.public.get(self._url()).json()
        self.assertNotIn('booking_url', body)

    def test_share_view_booking_url_present_with_work_hours(self):
        """설계사 영업시간 설정 → '바로 예약' booking_url 포함(/b/<token>)."""
        from datetime import time
        from inpa.booking.models import WorkHour
        WorkHour.objects.create(owner=self.user, weekday=0,
                                start_time=time(9, 0), end_time=time(18, 0))
        body = self.public.get(self._url()).json()
        self.assertIn('booking_url', body)
        self.assertIn('/b/', body['booking_url'])

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


class SharePayloadProposalExclusionTests(TestCase):
    """★ 제안(portfolio_type=2)이 고객 공유뷰(/s)에 '보유'로 섞이지 않는다."""

    def setUp(self):
        self.user, _ = _make_planner('share-proposal@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='제안고객', birth_day='1985.05.05', gender=1)
        self.det = _build_std_tree()
        self.idet = _catalog_detail_linked_to(self.det)
        # 보유(pt=1) 5천만원
        _make_portfolio(self.customer, self.idet, assurance_amount=50000000)
        # 제안(pt=2) 3억 — 공유뷰 보유 보장금액에 섞이면 안 된다.
        prop = CustomerInsurance.objects.create(
            customer=self.customer, insurance_type=2, name='제안보험',
            portfolio_type=2, payment_period_type=1, payment_period=20,
            monthly_premiums=90000, monthly_assurance_premium=90000)
        CustomerInsuranceDetail.objects.create(
            insurance=prop, detail=self.idet, assurance_amount=300000000,
            premium=30000, payment_period_type=1, payment_period=20,
            warranty_period_type=1, warranty_period='100')
        prop.set_renewal_month()
        prop.calculate()
        prop.save()
        self.public = APIClient()

    def test_proposal_excluded_from_share_payload(self):
        body = self.public.get(f'/api/v1/s/{self.customer.share_token}/').json()
        held = body['tree'][0]['sub_categories'][0]['details'][0]['held_amount']
        self.assertEqual(held, 50000000)  # 보유만(제안 3억 제외)


@override_settings(INSURANCE_REVIEW_GATE_ENABLED=True)
class ShareAnalysisEligibilityTests(TestCase):
    """공개 공유 자료도 분석과 동일한 확정 보험 필터를 사용한다."""

    def setUp(self):
        self.user, _ = _make_planner('share-ready@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='공유검토고객', birth_day='1985.05.05')
        standard = _build_std_tree()
        catalog = _catalog_detail_linked_to(standard)
        ready = _make_portfolio(self.customer, catalog, 50000000)
        ready.review_status = 'confirmed'
        ready.analysis_included = True
        ready.confirmed_at = timezone.now()
        ready.save(update_fields=(
            'review_status', 'analysis_included', 'confirmed_at'))
        _make_portfolio(self.customer, catalog, 300000000)
        self.public = APIClient()

    def test_share_payload_contains_only_analysis_ready_insurance(self):
        from inpa.analytics.views import _build_share_payload
        body = _build_share_payload(self.customer)
        held = body['tree'][0]['sub_categories'][0]['details'][0]['held_amount']
        self.assertEqual(held, 50000000)

    def test_share_creation_rejects_when_any_held_insurance_is_unconfirmed(self):
        client = APIClient()
        client.force_authenticate(user=self.user)
        response = client.post(
            f'/api/v1/customers/{self.customer.id}/share/')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'INSURANCE_REVIEW_REQUIRED')
        self.assertFalse(ShareSnapshot.objects.filter(
            customer=self.customer).exists())


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

    def test_cta_click_accepted_and_logged(self):
        """★ 분석→예약 CTA 클릭(FE가 전송) → 허용·적재. channel='web'(자동발송 아님)."""
        r = self.public.post(self._url(),
                             {'event_type': 'cta_click'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        ev = NorthStarEvent.objects.get(
            event_type=NorthStarEvent.CTA_CLICK,
            share_token=self.customer.share_token)
        self.assertEqual(ev.channel, 'web')
        self.assertEqual(ev.sender, self.user)

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
        self.assertEqual(r2.json()['snapshot']['mode'], 'neutral')

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


class CustomerHistoryTests(TestCase):
    """고객 이력 타임라인 — GET /api/v1/customers/<id>/history/.

    검증:
      1) 3개 소스(NorthStarEvent·ConsentLog·CustomerInsurance) 병합 + 시간 역순
      2) 표준 형태 {type, label, at, meta} + clipboard_copy='복사'(자동발송 사칭 금지)
      3) owner 격리 — A는 B 고객 이력 조회 불가(404)
      4) 데이터 없으면 빈 배열 / 인증 게이트
    """

    def setUp(self):
        self.user, self.client = _make_planner('history@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='이력고객', birth_day='1985.05.05', gender=1)

    def _url(self, customer_id=None):
        return f'/api/v1/customers/{customer_id or self.customer.id}/history/'

    def test_history_merges_three_sources_time_desc(self):
        """NorthStarEvent + ConsentLog + CustomerInsurance 병합 → 시간 역순."""
        # ① NorthStarEvent (ocr_upload, clipboard_copy)
        log_event(NorthStarEvent.OCR_UPLOAD, customer=self.customer,
                  sender=self.user, channel='web')
        log_event(NorthStarEvent.CLIPBOARD_COPY, customer=self.customer,
                  sender=self.user, channel='clipboard',
                  payload={'delivery': 'clipboard'})
        # ② ConsentLog (동의 + 철회)
        log = ConsentLog.objects.create(
            customer=self.customer, scope=ConsentLog.SCOPE_OVERSEAS_MEDICAL,
            doc_version='OVERSEAS-v1.0')
        log.revoked_at = timezone.now()
        log.save(update_fields=['revoked_at'])
        # ③ CustomerInsurance (보유 증권 등록)
        CustomerInsurance.objects.create(
            customer=self.customer, insurance_type=2, name='보유보험',
            portfolio_type=1)

        r = self.client.get(self._url())
        self.assertEqual(r.status_code, 200)
        events = r.json()['events']
        # 2(northstar) + 2(consent 동의+철회) + 1(insurance) = 5
        self.assertEqual(len(events), 5)
        # 표준 형태 키 보장
        for e in events:
            self.assertEqual(set(e.keys()), {'type', 'label', 'at', 'meta'})
        # 시간 역순(at desc) — 인접쌍 비교
        ats = [e['at'] for e in events]
        self.assertEqual(ats, sorted(ats, reverse=True))
        # 소스별 타입 존재
        types = {e['type'] for e in events}
        self.assertIn('ocr_upload', types)
        self.assertIn('clipboard_copy', types)
        self.assertIn('consent_agreed', types)
        self.assertIn('consent_revoked', types)
        self.assertIn('insurance_registered', types)

    def test_clipboard_copy_labeled_copy_not_send(self):
        """★ 자동발송 사칭 금지 — clipboard_copy 라벨은 '복사'(발송 단정 없음)."""
        log_event(NorthStarEvent.CLIPBOARD_COPY, customer=self.customer,
                  sender=self.user, channel='clipboard')
        events = self.client.get(self._url()).json()['events']
        copy_ev = next(e for e in events if e['type'] == 'clipboard_copy')
        self.assertIn('복사', copy_ev['label'])
        self.assertNotIn('발송', copy_ev['label'])

    def test_history_empty_when_no_events(self):
        """이벤트 없으면 빈 배열(200)."""
        r = self.client.get(self._url())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['events'], [])

    def test_history_owner_isolation(self):
        """★ A는 B 고객 이력 조회 불가 → 404(존재 은폐)."""
        _, client_b = _make_planner('history-b@test.com')
        # B 고객에 이벤트 적재(있어도 A는 못 봄)
        log_event(NorthStarEvent.OCR_UPLOAD, customer=self.customer,
                  sender=self.user, channel='web')
        r = client_b.get(self._url())
        self.assertEqual(r.status_code, 404)

    def test_history_only_this_customer_events(self):
        """다른 고객 이벤트는 섞이지 않는다(고객 단위 격리)."""
        other = Customer.objects.create(
            owner=self.user, name='다른고객', birth_day='1990.01.01')
        log_event(NorthStarEvent.OCR_UPLOAD, customer=other,
                  sender=self.user, channel='web')
        log_event(NorthStarEvent.OCR_UPLOAD, customer=self.customer,
                  sender=self.user, channel='web')
        events = self.client.get(self._url()).json()['events']
        self.assertEqual(len(events), 1)  # self.customer 것만

    def test_history_unknown_customer_404(self):
        r = self.client.get(self._url(customer_id=999999))
        self.assertEqual(r.status_code, 404)

    def test_history_requires_auth(self):
        c = APIClient()
        r = c.get(self._url())
        self.assertEqual(r.status_code, 401)


# ─── /s 상담 연결(콜백) — spec 2026-07-04 Part2 (LB#8) ──────────────

from unittest import mock  # noqa: E402

from inpa.notifications.models import Notification, NotifType  # noqa: E402


class ShareContactLayerTests(TestCase):
    """planner_contact 페이로드 + callback_request 이벤트 → 설계사 알림(하루 1회)."""

    def setUp(self):
        self.user, _ = _make_planner('contact-layer@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='콜백고객', birth_day='1990.01.01')
        self.public = APIClient()

    def _view_url(self):
        return f'/api/v1/s/{self.customer.share_token}/'

    def _event_url(self):
        return f'/api/v1/s/{self.customer.share_token}/event/'

    def test_payload_planner_contact_null_when_no_phone_field(self):
        """Profile.phone(2026-07-07 신설)이 비어 있으면 planner_contact=null(키는 존재)."""
        r = self.public.get(self._view_url())
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn('planner_contact', body)
        self.assertIsNone(body['planner_contact'])
        self.assertEqual(r['Cache-Control'], 'private, no-store')

    def test_payload_planner_contact_present_when_phone_exists(self):
        """전화번호 필드가 생기면 페이로드에 그대로 실린다(배선 검증)."""
        with mock.patch('inpa.analytics.views._planner_phone',
                        return_value='010-1234-5678'):
            r = self.public.get(self._view_url())
        self.assertEqual(r.json()['planner_contact'], '010-1234-5678')

    def test_payload_planner_contact_from_profile_phone_field(self):
        """실필드 회귀(2026-07-07 Profile.phone): 마이페이지에 전화번호를 저장하면
        /s 페이로드 planner_contact가 그 번호로 자동 활성(전화하기/문자하기 버튼)."""
        profile = self.user.profile
        profile.phone = '010-9876-5432'
        profile.save(update_fields=['phone'])
        r = self.public.get(self._view_url())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['planner_contact'], '010-9876-5432')

    def test_callback_request_creates_notification_to_owner(self):
        """callback_request → 이벤트 적재 + 소유 설계사에게 알림 1건(기존 타입 재사용)."""
        r = self.public.post(self._event_url(),
                             {'event_type': 'callback_request'}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json(), {
            'status': 'logged',
            'event_type': 'callback_request',
            'recorded': True,
            'notification': 'created',
        })
        self.assertEqual(r['Cache-Control'], 'private, no-store')
        self.assertEqual(NorthStarEvent.objects.filter(
            event_type=NorthStarEvent.CALLBACK_REQUEST,
            share_token=self.customer.share_token).count(), 1)
        notif = Notification.objects.get(owner=self.user)
        self.assertEqual(notif.notif_type, NotifType.SELF_DIAGNOSIS_LEAD)
        self.assertEqual(notif.title, '고객 연락 요청')
        self.assertEqual(notif.customer_id, self.customer.id)
        self.assertIn('콜백고객님이 보장 안내 화면에서 연락을 요청했어요', notif.body)

    def test_callback_request_same_day_dedupes_notification_but_logs_event(self):
        """같은 공유건 같은 날 재요청 → 알림은 1건 유지, 이벤트 로그는 2건."""
        self.public.post(self._event_url(),
                         {'event_type': 'callback_request'}, format='json')
        r2 = self.public.post(self._event_url(),
                              {'event_type': 'callback_request'}, format='json')
        self.assertEqual(r2.status_code, 201)
        self.assertEqual(NorthStarEvent.objects.filter(
            event_type=NorthStarEvent.CALLBACK_REQUEST).count(), 2)
        self.assertEqual(Notification.objects.filter(owner=self.user).count(), 1)
        self.assertEqual(r2.json()['notification'], 'already_notified')

    def test_callback_notification_failure_is_retryable_and_not_logged(self):
        with mock.patch(
                'inpa.notifications.models.Notification.objects.create',
                side_effect=RuntimeError('notification unavailable')):
            response = self.public.post(
                self._event_url(), {'event_type': 'callback_request'},
                format='json')

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['code'],
                         'CALLBACK_NOTIFICATION_FAILED')
        self.assertFalse(response.json()['recorded'])
        self.assertEqual(NorthStarEvent.objects.filter(
            event_type=NorthStarEvent.CALLBACK_REQUEST).count(), 0)

    def test_callback_unexpected_integrity_error_is_not_misreported_as_duplicate(self):
        from django.db import IntegrityError

        with mock.patch(
                'inpa.notifications.models.Notification.objects.create',
                side_effect=IntegrityError('unexpected constraint')):
            response = self.public.post(
                self._event_url(), {'event_type': 'callback_request'},
                format='json')

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['code'],
                         'CALLBACK_NOTIFICATION_FAILED')
        self.assertFalse(response.json()['recorded'])
        self.assertEqual(Notification.objects.filter(owner=self.user).count(), 0)
        self.assertEqual(NorthStarEvent.objects.filter(
            event_type=NorthStarEvent.CALLBACK_REQUEST).count(), 0)

    def test_callback_log_failure_reports_failure_and_retry_converges(self):
        with mock.patch('inpa.analytics.views.log_event', return_value=None):
            failed = self.public.post(
                self._event_url(), {'event_type': 'callback_request'},
                format='json')

        self.assertEqual(failed.status_code, 503)
        self.assertEqual(failed.json()['code'], 'EVENT_LOG_FAILED')
        self.assertFalse(failed.json()['recorded'])
        self.assertEqual(Notification.objects.filter(owner=self.user).count(), 1)
        retried = self.public.post(
            self._event_url(), {'event_type': 'callback_request'},
            format='json')
        self.assertEqual(retried.status_code, 201)
        self.assertEqual(retried.json()['notification'], 'already_notified')
        self.assertEqual(NorthStarEvent.objects.filter(
            event_type=NorthStarEvent.CALLBACK_REQUEST).count(), 1)

    def test_callback_on_expired_token_404_no_notification(self):
        self.customer.share_expires_at = timezone.now() - timezone.timedelta(days=1)
        self.customer.save(update_fields=['share_expires_at'])
        r = self.public.post(self._event_url(),
                             {'event_type': 'callback_request'}, format='json')
        self.assertEqual(r.status_code, 404)
        self.assertEqual(Notification.objects.count(), 0)


class AdviceCopyGuardTests(TestCase):
    """권유 단어 서버측 가드(#23, §97·금소법) — 유틸 + 현행 고정 카피 클린 단언."""

    def test_contains_advice_words_matches(self):
        from inpa.core.copyguard import contains_advice_words
        self.assertEqual(contains_advice_words('이 상품을 추천 드립니다'), '추천')
        self.assertEqual(contains_advice_words('지금 갈아타면 좋아요'), '갈아타')
        self.assertEqual(contains_advice_words('기존 보험은 해지하세요'), '해지하세요')
        self.assertEqual(contains_advice_words('이쪽이 더 유리해요'), '더 유리')
        self.assertEqual(contains_advice_words('오늘 가입하세요'), '가입하세요')
        self.assertEqual(contains_advice_words('이 상품으로 전환하세요'), '전환하세요')

    def test_referrer_word_not_flagged(self):
        """'추천인'(referrer)은 정당한 단어 — 부정형 전방탐색으로 제외."""
        from inpa.core.copyguard import contains_advice_words
        self.assertIsNone(contains_advice_words('추천인 코드를 입력하세요'))

    def test_clean_text_passes(self):
        from inpa.core.copyguard import contains_advice_words
        self.assertIsNone(contains_advice_words(''))
        self.assertIsNone(contains_advice_words(None))
        self.assertIsNone(contains_advice_words('등록된 보장 정보를 정리한 참고 자료입니다.'))

    def test_warn_logs_error_but_returns_hits(self):
        from inpa.core.copyguard import warn_if_advice_words
        with self.assertLogs('inpa.core.copyguard', level='ERROR') as cm:
            hits = warn_if_advice_words({'disclaimer': '갈아타 보세요'}, where='unit-test')
        self.assertEqual(hits, [('disclaimer', '갈아타')])
        self.assertIn('권유 단어 가드', cm.output[0])

    def test_current_share_disclaimer_clean(self):
        """현행 공유뷰 고정 카피(SHARE_DISCLAIMER)는 클린해야 한다."""
        from inpa.analytics.views import SHARE_DISCLAIMER
        from inpa.core.copyguard import contains_advice_words
        self.assertIsNone(contains_advice_words(SHARE_DISCLAIMER))

    def test_share_payload_fixed_copy_clean(self):
        """공유 페이로드 생성 시 가드 로그(ERROR)가 발생하지 않는다(고객 화면 무영향)."""
        from inpa.analytics.views import _build_share_payload
        user, _ = _make_planner('advice-guard@test.com')
        det = _build_std_tree()
        idet = _catalog_detail_linked_to(det)
        customer = Customer.objects.create(owner=user, name='홍길동', birth_day='1990.01.01')
        _make_portfolio(customer, idet, 10000000)
        with self.assertNoLogs('inpa.core.copyguard', level='ERROR'):
            payload = _build_share_payload(customer)
        self.assertIn('disclaimer', payload)


# ─── 공유(/s) 스냅샷 보관 — spec 2026-07-08, 프리런치 #27 ─────────────────

from datetime import timedelta as _timedelta  # noqa: E402

from inpa.analytics.models import ShareSnapshot  # noqa: E402


class ShareSnapshotCaptureTests(TestCase):
    """공유 생성 시 스냅샷 캡처 — payload 일치, 동의/사전 버전 스탬프, 보존기간 계산."""

    def setUp(self):
        self.user, self.client = _make_planner('snap-capture@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='홍길동', birth_day='1985.05.05', gender=1)
        self.det = _build_std_tree()
        self.idet = _catalog_detail_linked_to(self.det)
        _make_portfolio(self.customer, self.idet, assurance_amount=20000000)

    def test_normal_share_uses_current_payload_builder_and_returns_201(self):
        r = self.client.post(f'/api/v1/customers/{self.customer.id}/share/')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(
            ShareSnapshot.objects.filter(customer=self.customer).count(), 1)
        snapshot = ShareSnapshot.objects.get(customer=self.customer)
        self.assertEqual(snapshot.insurance_count, 1)
        detail = snapshot.payload['tree'][0]['sub_categories'][0]['details'][0]
        self.assertEqual(detail['held_amount'], 20_000_000)

    def test_snapshot_payload_matches_build_share_payload(self):
        from inpa.analytics.views import _build_share_payload
        self.client.post(f'/api/v1/customers/{self.customer.id}/share/')
        snap = ShareSnapshot.objects.get(customer=self.customer)
        self.assertEqual(
            snap.payload,
            _build_share_payload(self.customer, include_live_actions=False))

    def test_snapshot_stamps_consent_dict_and_insurance_count(self):
        from inpa.customers.consent_texts import CONSENT_TEXTS_VERSION
        from inpa.customers.models import ConsentLog
        ConsentLog.objects.create(
            customer=self.customer, scope=ConsentLog.SCOPE_OVERSEAS_MEDICAL,
            subject=ConsentLog.SUBJECT_CUSTOMER_SELF, doc_version=CONSENT_TEXTS_VERSION)
        self.customer.consent_overseas_at = timezone.now()
        self.customer.save(update_fields=['consent_overseas_at'])
        self.client.post(f'/api/v1/customers/{self.customer.id}/share/')
        snap = ShareSnapshot.objects.get(customer=self.customer)
        self.assertTrue(snap.consent_overseas)
        self.assertEqual(snap.consent_doc_version, CONSENT_TEXTS_VERSION)
        self.assertIn('overseas_medical', snap.consent_scopes)
        self.assertEqual(snap.insurance_count, 1)
        self.assertTrue(snap.dict_version)  # SeedMarker 부재 시 코드 SEED_VERSION 폴백

    def test_snapshot_payload_and_count_use_the_same_insurance_set(self):
        from inpa.analytics.sharing import create_share_snapshot

        captured = {}

        def payload_builder(customer, *, include_live_actions,
                            insurance_list):
            captured['include_live_actions'] = include_live_actions
            captured['insurance_ids'] = [item.pk for item in insurance_list]
            return {'insurance_ids': captured['insurance_ids']}

        snapshot = create_share_snapshot(
            customer_id=self.customer.pk,
            owner=self.user,
            payload_builder=payload_builder,
        )

        self.assertFalse(captured['include_live_actions'])
        self.assertEqual(snapshot.payload['insurance_ids'],
                         captured['insurance_ids'])
        self.assertEqual(snapshot.insurance_count,
                         len(captured['insurance_ids']))

    def test_share_query_count_does_not_scale_with_coverage_rows(self):
        def issue_and_count(customer):
            with CaptureQueriesContext(connection) as queries:
                response = self.client.post(
                    f'/api/v1/customers/{customer.id}/share/')
            self.assertEqual(response.status_code, 201, response.content)
            return len(queries)

        one_coverage_queries = issue_and_count(self.customer)

        many_customer = Customer.objects.create(
            owner=self.user,
            name='담보많은고객',
            birth_day='1985.05.05',
            gender=1,
        )
        many_insurance = _make_portfolio(
            many_customer,
            self.idet,
            assurance_amount=20_000_000,
        )
        for index in range(24):
            CustomerInsuranceDetail.objects.create(
                insurance=many_insurance,
                detail=self.idet,
                assurance_amount=1_000_000 + index,
                premium=1_000,
                payment_period_type=1,
                payment_period=20,
                warranty_period_type=1,
                warranty_period='100',
            )

        many_coverage_queries = issue_and_count(many_customer)

        self.assertLessEqual(
            many_coverage_queries,
            one_coverage_queries + 6,
            (f'1 coverage={one_coverage_queries} queries, '
             f'25 coverages={many_coverage_queries} queries'),
        )

    def test_retention_expires_at_180_days_from_capture(self):
        self.client.post(f'/api/v1/customers/{self.customer.id}/share/')
        snap = ShareSnapshot.objects.get(customer=self.customer)
        expected = snap.captured_at + _timedelta(days=180)
        self.assertLess(abs((snap.retention_expires_at - expected).total_seconds()), 5)

    def test_std_tree_change_after_capture_does_not_alter_stored_payload(self):
        """불변/무FK — 캡처 후 표준트리 이름이 바뀌어도 저장된 payload는 그대로."""
        self.client.post(f'/api/v1/customers/{self.customer.id}/share/')
        snap = ShareSnapshot.objects.get(customer=self.customer)
        original_name = snap.payload['tree'][0]['sub_categories'][0]['details'][0]['name']
        self.det.name = '완전히 다른 이름'
        self.det.save(update_fields=['name'])
        snap.refresh_from_db()
        stored_name = snap.payload['tree'][0]['sub_categories'][0]['details'][0]['name']
        self.assertEqual(stored_name, original_name)
        self.assertNotEqual(stored_name, '완전히 다른 이름')

    def test_snapshot_payload_excludes_planner_verdict_and_pii(self):
        """★ 회귀 가드(§97) — 공유뷰와 동일하게 verdict/switch_warnings/전화/메모 등 누수 금지."""
        import json
        self.client.post(f'/api/v1/customers/{self.customer.id}/share/')
        snap = ShareSnapshot.objects.get(customer=self.customer)
        raw = json.dumps(snap.payload, ensure_ascii=False)
        self.assertNotIn('verdict', raw)
        self.assertNotIn('switch_warnings', raw)
        self.assertNotIn('mobile_phone_number', raw)
        self.assertNotIn('memo', raw)
        self.assertEqual(snap.payload['customer']['name_masked'], '홍**')
        self.assertEqual(snap.payload['customer']['birth_year'], 1985)

    def test_capture_failure_blocks_share_link_issuance_atomically(self):
        """_build_share_payload 예외 → 링크·스냅샷·이벤트 모두 만들지 않는다."""
        old_token = self.customer.share_token
        with mock.patch('inpa.analytics.views._build_share_payload',
                        side_effect=RuntimeError('boom')):
            r = self.client.post(f'/api/v1/customers/{self.customer.id}/share/')
        self.assertEqual(r.status_code, 503)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.share_token, old_token)
        self.assertEqual(ShareSnapshot.objects.filter(customer=self.customer).count(), 0)
        self.assertFalse(NorthStarEvent.objects.filter(
            event_type=NorthStarEvent.SHARE_CREATED,
            customer=self.customer).exists())

    def test_customer_delete_cascades_share_snapshots(self):
        """고객 삭제 → ShareSnapshot도 함께 삭제(CASCADE, PII 동반 파기)."""
        self.client.post(f'/api/v1/customers/{self.customer.id}/share/')
        self.assertEqual(ShareSnapshot.objects.filter(customer=self.customer).count(), 1)
        self.customer.delete()
        self.assertEqual(ShareSnapshot.objects.count(), 0)


class ShareSnapshotReadApiTests(TestCase):
    """GET .../share-snapshots/ (목록·경량) · .../share-snapshots/<id>/ (상세·payload)."""

    def setUp(self):
        self.user, self.client = _make_planner('snap-read@test.com')
        self.customer = Customer.objects.create(owner=self.user, name='공유기록고객')

    def _create_snapshot(self, customer=None, owner=None, **overrides):
        now = timezone.now()
        values = dict(
            owner=owner or self.user, customer=customer or self.customer,
            share_token=None, payload={'tree': [], 'summary': {}, 'disclaimer': 'x',
                                       'customer': {'name_masked': '공**'}, 'mode': 'neutral'},
            consent_overseas=False, consent_doc_version='v2-2026-07-04',
            consent_scopes=[], dict_version='v1', insurance_count=0,
            retention_expires_at=now + _timedelta(days=180))
        values.update(overrides)
        return ShareSnapshot.objects.create(**values)

    def test_list_is_newest_first_and_excludes_payload(self):
        s1 = self._create_snapshot()
        s2 = self._create_snapshot()
        r = self.client.get(f'/api/v1/customers/{self.customer.id}/share-snapshots/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Cache-Control'], 'private, no-store')
        body = r.json()
        self.assertEqual([item['id'] for item in body], [s2.id, s1.id])
        for item in body:
            self.assertNotIn('payload', item)

    def test_detail_includes_payload(self):
        snap = self._create_snapshot()
        r = self.client.get(
            f'/api/v1/customers/{self.customer.id}/share-snapshots/{snap.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Cache-Control'], 'private, no-store')
        self.assertIn('payload', r.json())
        self.assertEqual(r.json()['payload']['customer']['name_masked'], '공**')

    def test_list_derives_lifecycle_before_timezone_date_checks(self):
        now = timezone.now()
        history = self._create_snapshot(
            payload_version='v1-legacy-actions',
            share_token=uuid.uuid4(),
            link_expires_at=now + _timedelta(days=30))
        active = self._create_snapshot(
            payload_version='v2-immutable-analysis',
            share_token=uuid.uuid4(),
            link_expires_at=now + _timedelta(days=30))
        revoked = self._create_snapshot(
            payload_version='v2-immutable-analysis',
            share_token=uuid.uuid4(),
            revoked_at=now,
            link_expires_at=now + _timedelta(days=30))
        expired = self._create_snapshot(
            payload_version='v2-immutable-analysis',
            share_token=uuid.uuid4(),
            link_expires_at=now - _timedelta(microseconds=1))

        statuses = []
        for zone in ('UTC', 'Asia/Seoul'):
            with timezone.override(zone):
                response = self.client.get(
                    f'/api/v1/customers/{self.customer.id}/share-snapshots/')
            self.assertEqual(response.status_code, 200, response.content)
            statuses.append({
                item['id']: item['link_status'] for item in response.json()
            })

        expected = {
            history.pk: 'history_only',
            active.pk: 'active',
            revoked.pk: 'revoked',
            expired.pk: 'expired',
        }
        self.assertEqual(statuses, [expected, expected])

    def test_revoke_accepts_only_active_v2_snapshot(self):
        now = timezone.now()
        active = self._create_snapshot(
            payload_version='v2-immutable-analysis',
            share_token=uuid.uuid4(),
            link_expires_at=now + _timedelta(days=1))
        revoked = self._create_snapshot(
            payload_version='v2-immutable-analysis',
            share_token=uuid.uuid4(), revoked_at=now,
            link_expires_at=now + _timedelta(days=1))
        expired = self._create_snapshot(
            payload_version='v2-immutable-analysis',
            share_token=uuid.uuid4(),
            link_expires_at=now - _timedelta(seconds=1))
        history = self._create_snapshot(
            payload_version='v1-legacy-actions',
            share_token=uuid.uuid4(),
            link_expires_at=now + _timedelta(days=1))

        accepted = self.client.post(
            f'/api/v1/customers/{self.customer.id}/share-snapshots/'
            f'{active.id}/revoke/')
        self.assertEqual(accepted.status_code, 200, accepted.content)
        for snapshot in (revoked, expired):
            response = self.client.post(
                f'/api/v1/customers/{self.customer.id}/share-snapshots/'
                f'{snapshot.id}/revoke/')
            self.assertEqual(response.status_code, 409, response.content)
            self.assertEqual(
                response.json()['code'], 'SHARE_SNAPSHOT_NOT_ACTIVE')
        hidden_history = self.client.post(
            f'/api/v1/customers/{self.customer.id}/share-snapshots/'
            f'{history.id}/revoke/')
        self.assertEqual(hidden_history.status_code, 404, hidden_history.content)

    def test_list_owner_isolation_404(self):
        """타 설계사 고객의 스냅샷 목록 조회 → 404(존재 은폐)."""
        self._create_snapshot()
        _, client_b = _make_planner('snap-read-b@test.com')
        r = client_b.get(f'/api/v1/customers/{self.customer.id}/share-snapshots/')
        self.assertEqual(r.status_code, 404)

    def test_detail_owner_isolation_404(self):
        snap = self._create_snapshot()
        _, client_b = _make_planner('snap-read-b2@test.com')
        r = client_b.get(
            f'/api/v1/customers/{self.customer.id}/share-snapshots/{snap.id}/')
        self.assertEqual(r.status_code, 404)

    def test_detail_snapshot_belonging_to_another_customer_404(self):
        """스냅샷 id는 존재하지만 URL의 고객과 다른 고객 소속 → 404."""
        other = Customer.objects.create(owner=self.user, name='다른고객')
        other_snap = self._create_snapshot(customer=other)
        r = self.client.get(
            f'/api/v1/customers/{self.customer.id}/share-snapshots/{other_snap.id}/')
        self.assertEqual(r.status_code, 404)

    def test_list_excludes_snapshot_with_mismatched_owner(self):
        foreign, _ = _make_planner('snap-mismatch-list@test.com')
        mismatched = self._create_snapshot(owner=foreign)
        response = self.client.get(
            f'/api/v1/customers/{self.customer.id}/share-snapshots/')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(mismatched.id, [item['id'] for item in response.json()])

    def test_detail_hides_snapshot_with_mismatched_owner(self):
        foreign, _ = _make_planner('snap-mismatch-detail@test.com')
        mismatched = self._create_snapshot(owner=foreign)
        response = self.client.get(
            f'/api/v1/customers/{self.customer.id}/share-snapshots/{mismatched.id}/')
        self.assertEqual(response.status_code, 404)

    def test_revoke_hides_snapshot_with_mismatched_owner(self):
        foreign, _ = _make_planner('snap-mismatch-revoke@test.com')
        mismatched = self._create_snapshot(owner=foreign)
        response = self.client.post(
            f'/api/v1/customers/{self.customer.id}/share-snapshots/{mismatched.id}/revoke/')
        self.assertEqual(response.status_code, 404)
        mismatched.refresh_from_db()
        self.assertIsNone(mismatched.revoked_at)

    def test_requires_auth(self):
        from rest_framework.test import APIClient
        anon = APIClient()
        r = anon.get(f'/api/v1/customers/{self.customer.id}/share-snapshots/')
        self.assertEqual(r.status_code, 401)


@override_settings(INSURANCE_REVIEW_GATE_ENABLED=True)
class ShareSnapshotAtomicCreateTests(TestCase):
    """링크, 불변 본문, 발급 이벤트는 하나의 트랜잭션으로만 생긴다."""

    def setUp(self):
        self.user, self.client = _make_planner('snapshot-atomic@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='원자성고객', birth_day='1985.05.05')
        self.ready = CustomerInsurance.objects.create(
            customer=self.customer, portfolio_type=1, name='확인보험',
            review_status='confirmed', analysis_included=True,
            confirmed_at=timezone.now())

    def test_payload_build_failure_rolls_back_token_snapshot_and_event(self):
        old_token = self.customer.share_token
        with mock.patch(
                'inpa.analytics.views._build_share_payload',
                side_effect=RuntimeError('synthetic failure')):
            response = self.client.post(
                f'/api/v1/customers/{self.customer.id}/share/')

        self.assertEqual(response.status_code, 503)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.share_token, old_token)
        self.assertIsNone(self.customer.share_sent_at)
        self.assertEqual(ShareSnapshot.objects.count(), 0)
        self.assertEqual(NorthStarEvent.objects.filter(
            event_type=NorthStarEvent.SHARE_CREATED).count(), 0)

    def test_unconfirmed_held_insurance_returns_409_without_link_or_event(self):
        CustomerInsurance.objects.create(
            customer=self.customer, portfolio_type=1, name='확인전보험')
        old_token = self.customer.share_token

        response = self.client.post(
            f'/api/v1/customers/{self.customer.id}/share/')

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'INSURANCE_REVIEW_REQUIRED')
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.share_token, old_token)
        self.assertEqual(ShareSnapshot.objects.count(), 0)
        self.assertEqual(NorthStarEvent.objects.filter(
            event_type=NorthStarEvent.SHARE_CREATED).count(), 0)

    def test_no_confirmed_included_insurance_returns_409(self):
        self.ready.delete()
        response = self.client.post(
            f'/api/v1/customers/{self.customer.id}/share/')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'INSURANCE_REVIEW_REQUIRED')
        self.assertEqual(ShareSnapshot.objects.count(), 0)
        self.assertEqual(NorthStarEvent.objects.filter(
            event_type=NorthStarEvent.SHARE_CREATED).count(), 0)

    def test_excluded_canceled_and_superseded_insurances_do_not_block_ready_one(self):
        CustomerInsurance.objects.create(
            customer=self.customer, portfolio_type=1, name='분석제외',
            review_status='excluded', analysis_included=False)
        CustomerInsurance.objects.create(
            customer=self.customer, portfolio_type=1, name='해지',
            review_status='draft', analysis_included=False, is_cancelled=True)
        CustomerInsurance.objects.create(
            customer=self.customer, portfolio_type=1, name='교체',
            review_status='superseded', analysis_included=False)
        response = self.client.post(
            f'/api/v1/customers/{self.customer.id}/share/')
        self.assertEqual(response.status_code, 201, response.content)


@override_settings(INSURANCE_REVIEW_GATE_ENABLED=True, BOOKING_TOKEN_TTL_HOURS=72)
class ShareSnapshotAuthorityTests(TestCase):
    """신규 공개 링크는 active v2 ShareSnapshot 하나만 권위로 사용한다."""

    def setUp(self):
        self.user, self.client = _make_planner('snapshot-authority@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='불변고객', birth_day='1985.05.05', gender=1)
        self.standard = _build_std_tree()
        catalog = _catalog_detail_linked_to(self.standard)
        self.insurance = _make_portfolio(self.customer, catalog, 20000000)
        self.insurance.review_status = 'confirmed'
        self.insurance.analysis_included = True
        self.insurance.confirmed_at = timezone.now()
        self.insurance.save(update_fields=(
            'review_status', 'analysis_included', 'confirmed_at'))
        self.case = self.insurance.case_list.get()
        self.public = APIClient()

    def _issue(self):
        response = self.client.post(
            f'/api/v1/customers/{self.customer.id}/share/')
        self.assertEqual(response.status_code, 201, response.content)
        return response.json(), ShareSnapshot.objects.get(
            share_token=response.json()['share_token'])

    def test_public_response_uses_frozen_snapshot_after_live_data_changes(self):
        issued, snapshot = self._issue()
        url = f"/api/v1/s/{issued['share_token']}/"
        first = self.public.get(url).json()['snapshot']

        self.case.assurance_amount = 999999999
        self.case.save(update_fields=['assurance_amount'])
        self.standard.name = '발급 뒤 바뀐 전역 담보명'
        self.standard.save(update_fields=['name'])
        self.customer.name = '발급 뒤 바뀐 고객명'
        self.customer.save(update_fields=['name'])

        second = self.public.get(url).json()['snapshot']
        snapshot.refresh_from_db()
        self.assertEqual(first, second)
        self.assertEqual(second, {
            **snapshot.payload,
            'captured_at': snapshot.captured_at.isoformat(),
        })
        self.assertNotIn('발급 뒤 바뀐 전역 담보명', str(second))

    def test_reissue_revokes_previous_link(self):
        first, first_snapshot = self._issue()
        second, _ = self._issue()
        self.assertNotEqual(first['share_token'], second['share_token'])
        first_snapshot.refresh_from_db()
        self.assertIsNotNone(first_snapshot.revoked_at)
        self.assertEqual(first_snapshot.revoked_reason, 'reissued')
        self.assertEqual(self.public.get(
            f"/api/v1/s/{first['share_token']}/").status_code, 404)
        self.assertEqual(self.public.get(
            f"/api/v1/s/{second['share_token']}/").status_code, 200)

    def test_explicit_revoke_closes_public_view_and_event(self):
        issued, snapshot = self._issue()
        revoke = self.client.post(
            f'/api/v1/customers/{self.customer.id}/share-snapshots/{snapshot.id}/revoke/')
        self.assertEqual(revoke.status_code, 200)
        url = f"/api/v1/s/{issued['share_token']}/"
        self.assertEqual(self.public.get(url).status_code, 404)
        event = self.public.post(
            f"{url}event/", {'event_type': 'clipboard_copy'}, format='json')
        self.assertEqual(event.status_code, 404)
        self.assertEqual(NorthStarEvent.objects.filter(
            event_type=NorthStarEvent.CLIPBOARD_COPY).count(), 0)

    def test_expired_snapshot_closes_public_view_and_event(self):
        issued, snapshot = self._issue()
        snapshot.link_expires_at = timezone.now() - timezone.timedelta(seconds=1)
        snapshot.save(update_fields=['link_expires_at'])
        url = f"/api/v1/s/{issued['share_token']}/"
        self.assertEqual(self.public.get(url).status_code, 404)
        self.assertEqual(self.public.post(
            f"{url}event/", {'event_type': 'clipboard_copy'}, format='json').status_code, 404)

    def test_first_view_marks_only_the_snapshot_used(self):
        _, old_snapshot = self._issue()
        issued, current_snapshot = self._issue()

        self.public.get(f"/api/v1/s/{issued['share_token']}/")

        old_snapshot.refresh_from_db()
        current_snapshot.refresh_from_db()
        self.assertIsNone(old_snapshot.first_viewed_at)
        self.assertIsNotNone(current_snapshot.first_viewed_at)

    def test_bot_preview_does_not_mark_snapshot_as_first_viewed(self):
        issued, snapshot = self._issue()
        url = f"/api/v1/s/{issued['share_token']}/"

        bot_response = self.public.get(
            url, HTTP_USER_AGENT='KakaoTalk-Scrap/1.0')

        self.assertEqual(bot_response.status_code, 200)
        snapshot.refresh_from_db()
        self.assertIsNone(snapshot.first_viewed_at)

        self.assertEqual(self.public.get(url).status_code, 200)
        snapshot.refresh_from_db()
        self.assertIsNotNone(snapshot.first_viewed_at)

    def test_revoke_owner_scope_hides_foreign_snapshot(self):
        _, snapshot = self._issue()
        _, foreign_client = _make_planner('snapshot-foreign@test.com')
        response = foreign_client.post(
            f'/api/v1/customers/{self.customer.id}/share-snapshots/{snapshot.id}/revoke/')
        self.assertEqual(response.status_code, 404)
        snapshot.refresh_from_db()
        self.assertIsNone(snapshot.revoked_at)

    def test_customer_deletion_closes_public_snapshot_link(self):
        issued, _ = self._issue()
        token = issued['share_token']
        self.customer.delete()
        self.assertEqual(
            self.public.get(f'/api/v1/s/{token}/').status_code, 404)

    def test_foreign_customer_snapshot_cannot_be_cross_assigned(self):
        other, other_client = _make_planner('snapshot-other@test.com')
        other_customer = Customer.objects.create(owner=other, name='다른소유고객')
        response = other_client.post(
            f'/api/v1/customers/{self.customer.id}/share/')
        self.assertEqual(response.status_code, 404)
        self.assertFalse(ShareSnapshot.objects.filter(
            owner=other, customer=self.customer).exists())
        self.assertFalse(NorthStarEvent.objects.filter(
            sender=other, customer=self.customer).exists())
        self.assertFalse(ShareSnapshot.objects.filter(
            customer=other_customer, owner=self.user).exists())

    def test_analysis_is_frozen_but_booking_and_phone_actions_are_live(self):
        from datetime import time
        from inpa.booking.models import WorkHour
        WorkHour.objects.create(
            owner=self.user, weekday=0, start_time=time(9), end_time=time(18))
        profile = self.user.profile
        profile.phone = '010-1111-2222'
        profile.save(update_fields=['phone'])
        issued, snapshot = self._issue()
        url = f"/api/v1/s/{issued['share_token']}/"

        with mock.patch(
                'inpa.analytics.views.make_booking_token',
                side_effect=['fresh-token-1', 'fresh-token-2']):
            first = self.public.get(url).json()
            profile.phone = '010-3333-4444'
            profile.save(update_fields=['phone'])
            second = self.public.get(url).json()

        self.assertEqual(first['snapshot'], second['snapshot'])
        self.assertEqual(first['snapshot'], {
            **snapshot.payload,
            'captured_at': snapshot.captured_at.isoformat(),
        })
        self.assertNotEqual(
            first['actions']['booking_url'], second['actions']['booking_url'])
        self.assertEqual(first['actions']['planner_contact'], '010-1111-2222')
        self.assertEqual(second['actions']['planner_contact'], '010-3333-4444')
        self.assertNotIn('booking_url', first['snapshot'])
        self.assertNotIn('planner_contact', first['snapshot'])

    def test_share_link_is_90_days_while_booking_tokens_are_72_hours(self):
        _, snapshot = self._issue()
        link_lifetime = snapshot.link_expires_at - snapshot.captured_at
        self.assertLess(abs(link_lifetime - timezone.timedelta(days=90)),
                        timezone.timedelta(seconds=5))
        self.assertEqual(settings.BOOKING_TOKEN_TTL_HOURS, 72)

    def test_four_day_old_booking_action_expires_but_fresh_action_works(self):
        import time as time_module
        from datetime import time
        from django.core import signing
        from inpa.booking.models import WorkHour
        from inpa.booking.tokens import read_booking_token

        WorkHour.objects.create(
            owner=self.user, weekday=0, start_time=time(9), end_time=time(18))
        issued, _ = self._issue()
        url = f"/api/v1/s/{issued['share_token']}/"
        base = time_module.time()
        with mock.patch('django.core.signing.time.time', return_value=base):
            first = self.public.get(url).json()
        with mock.patch(
                'django.core.signing.time.time',
                return_value=base + 4 * 24 * 60 * 60):
            second = self.public.get(url).json()
            old_token = first['actions']['booking_url'].rsplit('/', 1)[-1]
            fresh_token = second['actions']['booking_url'].rsplit('/', 1)[-1]
            with self.assertRaises(signing.SignatureExpired):
                read_booking_token(old_token)
            self.assertEqual(read_booking_token(fresh_token), self.customer.pk)
        self.assertEqual(first['snapshot'], second['snapshot'])

    @override_settings(LEGACY_SHARE_FALLBACK_ENABLED=False)
    def test_unbacked_customer_token_is_404(self):
        legacy = Customer.objects.create(owner=self.user, name='스냅샷없는고객')
        response = self.public.get(f'/api/v1/s/{legacy.share_token}/')
        self.assertEqual(response.status_code, 404)

    def test_snapshot_captured_at_is_server_authoritative_over_payload(self):
        issued, snapshot = self._issue()
        snapshot.payload['captured_at'] = '2000-01-01T00:00:00+00:00'
        snapshot.save(update_fields=['payload'])

        response = self.public.get(f"/api/v1/s/{issued['share_token']}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['snapshot']['captured_at'],
            snapshot.captured_at.isoformat(),
        )


class ShareSnapshotRolloutCompatibilityTests(TestCase):
    """명시적으로 연 legacy fallback만 과거 Customer 링크를 호환한다."""

    def setUp(self):
        self.user, self.client = _make_planner('snapshot-rollout@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='과거링크고객', birth_day='1985.05.05')
        self.public = APIClient()

    @override_settings(LEGACY_SHARE_FALLBACK_ENABLED=True)
    def test_gate_off_customer_token_keeps_legacy_shape(self):
        response = self.public.get(f'/api/v1/s/{self.customer.share_token}/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('mode', response.json())
        self.assertNotIn('snapshot', response.json())

    @override_settings(
        LEGACY_SHARE_FALLBACK_ENABLED=True,
        INSURANCE_REVIEW_GATE_ENABLED=True,
    )
    def test_legacy_fallback_is_independent_from_review_gate(self):
        response = self.public.get(f'/api/v1/s/{self.customer.share_token}/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('mode', response.json())
        self.assertNotIn('snapshot', response.json())

    def test_customer_patch_cannot_change_share_lifecycle_fields(self):
        self.customer.share_sent_at = timezone.now()
        self.customer.share_expires_at = timezone.now() + timezone.timedelta(days=30)
        self.customer.save(update_fields=('share_sent_at', 'share_expires_at'))
        original = (
            self.customer.share_token,
            self.customer.share_sent_at,
            self.customer.share_expires_at,
        )

        response = self.client.patch(
            f'/api/v1/customers/{self.customer.id}/',
            {
                'share_token': str(uuid.uuid4()),
                'share_sent_at': '2030-01-01T00:00:00Z',
                'share_expires_at': '2030-02-01T00:00:00Z',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.customer.refresh_from_db()
        self.assertEqual(
            (
                self.customer.share_token,
                self.customer.share_sent_at,
                self.customer.share_expires_at,
            ),
            original,
        )

    @override_settings(INSURANCE_REVIEW_GATE_ENABLED=False)
    def test_new_link_is_v2_even_while_gate_is_off(self):
        issued = self.client.post(
            f'/api/v1/customers/{self.customer.id}/share/')
        self.assertEqual(issued.status_code, 201)
        response = self.public.get(
            f"/api/v1/s/{issued.json()['share_token']}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), {'snapshot', 'actions'})

    @override_settings(LEGACY_SHARE_FALLBACK_ENABLED=True)
    def test_v1_history_snapshot_is_terminal_even_with_legacy_fallback(self):
        ShareSnapshot.objects.create(
            owner=self.user, customer=self.customer,
            share_token=self.customer.share_token,
            payload_version='v1-legacy-actions', payload={'mode': 'neutral'},
            retention_expires_at=timezone.now() + timezone.timedelta(days=180))
        self.customer.share_sent_at = timezone.now()
        self.customer.share_expires_at = timezone.now() + timezone.timedelta(days=30)
        self.customer.save(update_fields=('share_sent_at', 'share_expires_at'))
        response = self.public.get(f'/api/v1/s/{self.customer.share_token}/')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['reason'], 'SHARE_LINK_INVALID')

    @override_settings(LEGACY_SHARE_FALLBACK_ENABLED=True)
    def test_revoked_snapshot_is_terminal_even_with_legacy_fallback(self):
        customer = Customer.objects.create(
            owner=self.user, name='회수된과거고객',
            share_sent_at=timezone.now(),
            share_expires_at=timezone.now() + timezone.timedelta(days=30))
        ShareSnapshot.objects.create(
            owner=self.user, customer=customer,
            share_token=customer.share_token,
            payload_version=PAYLOAD_VERSION_V2, payload={'mode': 'neutral'},
            revoked_at=timezone.now(),
            link_expires_at=timezone.now() + timezone.timedelta(days=30),
            retention_expires_at=timezone.now() + timezone.timedelta(days=180))

        response = self.public.get(f'/api/v1/s/{customer.share_token}/')

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['reason'], 'SHARE_LINK_REVOKED')

    @override_settings(LEGACY_SHARE_FALLBACK_ENABLED=True)
    def test_expired_snapshot_is_terminal_even_with_legacy_fallback(self):
        customer = Customer.objects.create(
            owner=self.user, name='만료된과거고객',
            share_sent_at=timezone.now(),
            share_expires_at=timezone.now() + timezone.timedelta(days=30))
        ShareSnapshot.objects.create(
            owner=self.user, customer=customer,
            share_token=customer.share_token,
            payload_version=PAYLOAD_VERSION_V2, payload={'mode': 'neutral'},
            link_expires_at=timezone.now() - timezone.timedelta(seconds=1),
            retention_expires_at=timezone.now() + timezone.timedelta(days=180))

        response = self.public.get(f'/api/v1/s/{customer.share_token}/')

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['reason'], 'SHARE_LINK_EXPIRED')


class ShareSnapshotAuditCommandTests(TestCase):
    """과거 링크는 소급 재계산하지 않고 dry-run 수량만 분리한다."""

    def setUp(self):
        from io import StringIO
        self.StringIO = StringIO
        self.user, _ = _make_planner('snapshot-audit@test.com')
        self.unbacked = Customer.objects.create(
            owner=self.user, name='기록없는과거링크', share_sent_at=timezone.now())
        self.v1_customer = Customer.objects.create(
            owner=self.user, name='행동포함과거기록', share_sent_at=timezone.now())
        self.v1 = ShareSnapshot.objects.create(
            owner=self.user, customer=self.v1_customer,
            share_token=self.v1_customer.share_token,
            payload={'mode': 'neutral', 'booking_url': '/b/frozen-old-token'},
            retention_expires_at=timezone.now() + timezone.timedelta(days=180))
        revoked_token = uuid.uuid4()
        self.revoked_v1 = ShareSnapshot.objects.create(
            owner=self.user,
            customer=Customer.objects.create(
                owner=self.user, name='이미회수된기록',
                share_token=revoked_token,
                share_sent_at=timezone.now(),
                share_expires_at=timezone.now() + timezone.timedelta(days=30)),
            payload_version='v1-legacy-actions', share_token=revoked_token,
            revoked_at=timezone.now(), payload={'booking_url': '/b/revoked'},
            retention_expires_at=timezone.now() + timezone.timedelta(days=180))
        expired_token = uuid.uuid4()
        self.expired_v1 = ShareSnapshot.objects.create(
            owner=self.user,
            customer=Customer.objects.create(
                owner=self.user, name='이미만료된기록',
                share_token=expired_token,
                share_sent_at=timezone.now(),
                share_expires_at=timezone.now() - timezone.timedelta(days=1)),
            payload_version='v1-legacy-actions', share_token=expired_token,
            link_expires_at=timezone.now() - timezone.timedelta(days=1),
            payload={'booking_url': '/b/expired'},
            retention_expires_at=timezone.now() + timezone.timedelta(days=180))

    def test_dry_run_counts_unbacked_v1_and_frozen_booking_without_backfill(self):
        from django.core.management import call_command
        before = ShareSnapshot.objects.count()
        output = self.StringIO()
        call_command('audit_share_snapshot_links', stdout=output)
        text = output.getvalue()
        self.assertIn('unbacked_legacy_links=1', text)
        self.assertIn('v1_legacy_snapshots=1', text)
        self.assertIn('v1_frozen_booking_actions=1', text)
        self.assertIn('v1_history_snapshots=3', text)
        self.assertIn('v1_inactive_snapshots=2', text)
        self.assertIn('dry_run=true', text)
        self.assertEqual(ShareSnapshot.objects.count(), before)
        self.assertFalse(ShareSnapshot.objects.filter(
            customer=self.unbacked).exists())

    @override_settings(INSURANCE_REVIEW_GATE_ENABLED=False)
    def test_explicit_revoke_legacy_closes_customer_and_v1_links(self):
        from django.core.management import call_command
        call_command(
            'audit_share_snapshot_links', '--revoke-legacy',
            stdout=self.StringIO())
        after = self.StringIO()
        call_command('audit_share_snapshot_links', stdout=after)
        self.assertIn('unbacked_legacy_links=0', after.getvalue())
        self.assertIn('v1_legacy_snapshots=0', after.getvalue())
        self.unbacked.refresh_from_db()
        self.v1_customer.refresh_from_db()
        self.v1.refresh_from_db()
        self.assertLessEqual(self.unbacked.share_expires_at, timezone.now())
        self.assertLessEqual(self.v1_customer.share_expires_at, timezone.now())
        self.assertIsNotNone(self.v1.revoked_at)
        public = APIClient()
        self.assertEqual(public.get(
            f'/api/v1/s/{self.unbacked.share_token}/').status_code, 404)
        self.assertEqual(public.get(
            f'/api/v1/s/{self.v1_customer.share_token}/').status_code, 404)
