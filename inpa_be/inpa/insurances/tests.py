"""증권 OCR 업로드 핵심 게이트 테스트 (dev/12 §0 원칙, dev/03 포팅지도).

★ 필수 3종 (작업 지시):
  (a) 동의 게이트 — consent_overseas_at 없으면 OCR 업로드 412 + Claude 호출 0회(물리 차단).
  (b) Claude 클라이언트 mock — 파싱 → CustomerInsurance + CustomerInsuranceDetail 생성 검증.
  (c) owner 격리 — 설계사 A 가 B 고객에 OCR 업로드하면 404(존재 은폐).
+ 정규화 훅(NormalizationDict) 적용 / API 키 미설정 503 / anthropic 실클라이언트 mock 보강.

★ 실제 Claude 호출 금지 — 모든 파싱 경로는 mock.
"""
from unittest import mock

from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User
from inpa.analysis.models import (
    AnalysisCategory, AnalysisDetail, AnalysisSubCategory, NormalizationDict,
)
from inpa.core.ocr.ocrdata import Ocr_Data
from inpa.customers.models import Customer

from .models import CustomerInsurance, CustomerInsuranceDetail


def _make_planner(email):
    """이메일 인증 완료(is_active=True) + Profile 보유 설계사 + 인증된 APIClient."""
    user = User.objects.create_user(email=email, password='inpaPass123!')
    user.is_active = True
    user.save(update_fields=['is_active'])
    Profile.objects.create(user=user, email_verified_at=timezone.now())
    client = APIClient()
    client.force_authenticate(user=user)
    return user, client


def _dummy_pdf():
    """동의/격리 게이트는 PDF 추출 이전에 차단되므로 내용 무관한 더미 PDF."""
    return SimpleUploadedFile('policy.pdf', b'%PDF-1.4 dummy', content_type='application/pdf')


def _ocr_url(customer_pk):
    return f'/api/v1/customers/{customer_pk}/insurances/ocr/'


def _fake_ocr_data():
    """Claude 응답을 흉내낸 Ocr_Data — 손해보험 + 암진단 담보 1건.

    실제 _convert_to_ocr_data 출력과 동일한 형태(dict_loss_head_data + dict_detail_data
    값 문자열 'pay:paytype:war:wartype:amount:premium')로 만든다.
    """
    ocr = Ocr_Data()
    ocr.parsing_method = 'claude'
    ocr.is_same_insured = True
    head = ocr.dict_loss_head_data
    head['손해보험'] = 2  # 삼성화재
    head['상품명'] = '무배당 종합보험'
    head['계약자'] = '홍길동'
    head['피보험자'] = '홍길동'
    head['납입기간'] = 20
    head['보장기간'] = 100
    head['월납입보험료'] = 50000
    head['월보장보험료'] = 50000
    head['계약일'] = '2020.01.15'
    head['payment_period_type'] = 1
    head['warranty_period_type'] = 1
    # 담보: 진단비 > 암 > 일반암, 5천만원, 보험료 1만원, 20년납/100세만기
    ocr.dict_detail_data['진단비']['암']['일반암'].append('20:1:100:1:50000000:10000')
    return ocr


class ConsentGateTests(TestCase):
    """(a) ★ 국외이전 동의 물리 게이트 — 동의 없으면 Claude 호출 전 412."""

    def setUp(self):
        self.user, self.client = _make_planner('owner@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='무동의고객', mobile_phone_number='010-0000-0000')
        # consent_overseas_at = None (디폴트) → 게이트 차단 대상

    def test_ocr_upload_blocked_without_consent_412(self):
        with mock.patch('inpa.insurances.views.claude_parse') as m_parse:
            r = self.client.post(
                _ocr_url(self.customer.id), {'file': _dummy_pdf()}, format='multipart')
        self.assertEqual(r.status_code, 412)
        self.assertEqual(r.json()['code'], 'CONSENT_OVERSEAS_REQUIRED')
        # ★ Claude 호출이 물리적으로 일어나지 않았는지 확인
        m_parse.assert_not_called()
        self.assertEqual(CustomerInsurance.objects.count(), 0)

    def test_ocr_upload_passes_gate_after_consent(self):
        """동의 시각이 채워지면 게이트 통과 → 파싱 단계 진입(여기선 mock)."""
        self.customer.consent_overseas_at = timezone.now()
        self.customer.save(update_fields=['consent_overseas_at'])
        with mock.patch('inpa.insurances.views.claude_parse', return_value=_fake_ocr_data()) as m_parse, \
                mock.patch('inpa.insurances.views._extract_pdf_lines',
                           return_value=(['삼성화재 종합보험 암진단 5천만원'], None)), \
                override_settings(ANTHROPIC_API_KEY='sk-ant-test'):
            r = self.client.post(
                _ocr_url(self.customer.id), {'file': _dummy_pdf()}, format='multipart')
        self.assertEqual(r.status_code, 201, r.content)
        m_parse.assert_called_once()


@override_settings(ANTHROPIC_API_KEY='sk-ant-test')
class OcrParsePersistTests(TestCase):
    """(b) Claude mock → 파싱 → CustomerInsurance + Detail 생성."""

    def setUp(self):
        self.user, self.client = _make_planner('parse@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='동의고객', birth_day='1985.03.10', gender=1,
            consent_overseas_at=timezone.now())

    def _upload(self):
        """_extract_pdf_lines 와 claude_parse 를 mock 하여 실제 _persist_ocr 변환을 탄다."""
        with mock.patch('inpa.insurances.views.claude_parse', return_value=_fake_ocr_data()), \
                mock.patch('inpa.insurances.views._extract_pdf_lines',
                           return_value=(['삼성화재 무배당 종합보험 암진단 5천만원'], None)):
            return self.client.post(
                _ocr_url(self.customer.id), {'file': _dummy_pdf()}, format='multipart')

    def test_creates_customer_insurance(self):
        r = self._upload()
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual(body['code'], 'OK')
        self.assertEqual(body['parsing_method'], 'claude')
        self.assertEqual(body['created_cases'], 1)

        # CustomerInsurance 1건 — 소유자 고객에 귀속, 보유(portfolio_type=1)
        self.assertEqual(CustomerInsurance.objects.count(), 1)
        ci = CustomerInsurance.objects.get()
        self.assertEqual(ci.customer_id, self.customer.id)
        self.assertEqual(ci.portfolio_type, 1)
        self.assertEqual(ci.insurance_type, 2)  # 손해보험
        self.assertEqual(ci.name, '무배당 종합보험')
        self.assertEqual(ci.contractor_name, '홍길동')
        self.assertEqual(ci.monthly_premiums, 50000)

        # CustomerInsuranceDetail 1건 — 일반암 5천만원
        self.assertEqual(CustomerInsuranceDetail.objects.count(), 1)
        case = CustomerInsuranceDetail.objects.get()
        self.assertEqual(case.insurance_id, ci.id)
        self.assertEqual(case.assurance_amount, 50000000)
        self.assertEqual(case.detail.name, '일반암')

    def test_calculate_engine_ran(self):
        """foliio 8케이스 엔진이 호출되어 계산 필드가 채워졌는지(무변경 호출 검증)."""
        self._upload()
        ci = CustomerInsurance.objects.get()
        # set_renewal_month() → non_renewal_month = payment_period*12 = 240
        self.assertEqual(ci.non_renewal_month, 240)
        # calculate() 가 total_premiums 를 산출(0 이상으로 채워짐)
        self.assertIsNotNone(ci.total_premiums)

    def test_no_real_claude_call(self):
        """anthropic 패키지를 실제로 import/호출하지 않는다(mock 경계 확인)."""
        with mock.patch('inpa.insurances.views.claude_parse', return_value=_fake_ocr_data()) as m, \
                mock.patch('inpa.insurances.views._extract_pdf_lines',
                           return_value=(['dummy'], None)):
            self.client.post(_ocr_url(self.customer.id), {'file': _dummy_pdf()}, format='multipart')
        m.assert_called_once()
        # claude_parse 에 normalizer 콜백이 주입됐는지(정규화 훅 배선 확인)
        _, kwargs = m.call_args
        self.assertIn('normalizer', kwargs)
        self.assertTrue(callable(kwargs['normalizer']))

    def test_missing_api_key_returns_503(self):
        with override_settings(ANTHROPIC_API_KEY=''), \
                mock.patch('inpa.insurances.views._extract_pdf_lines',
                           return_value=(['dummy'], None)), \
                mock.patch('inpa.insurances.views.claude_parse') as m_parse:
            r = self.client.post(
                _ocr_url(self.customer.id), {'file': _dummy_pdf()}, format='multipart')
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()['code'], 'OCR_UNAVAILABLE')
        m_parse.assert_not_called()  # 키 없으면 파싱조차 시도 안 함

    def test_image_pdf_rejected(self):
        """텍스트 0줄(스캔/이미지 PDF) → 400 IMAGE_PDF, Claude 호출 0."""
        with mock.patch('inpa.insurances.views._extract_pdf_lines',
                        return_value=([], 'IMAGE_PDF')), \
                mock.patch('inpa.insurances.views.claude_parse') as m_parse:
            r = self.client.post(
                _ocr_url(self.customer.id), {'file': _dummy_pdf()}, format='multipart')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['code'], 'IMAGE_PDF')
        m_parse.assert_not_called()


@override_settings(ANTHROPIC_API_KEY='sk-ant-test', CLAUDE_API_KEY='sk-ant-test')
class AnthropicClientMockTests(TestCase):
    """(b 보강) anthropic.Anthropic SDK 자체를 mock → 실제 claude_parse 파이프라인 통과.

    벤더링한 claude_parser 전 구간(JSON 추출→_convert_to_ocr_data→_add_coverage→정규화 훅)을
    실제로 태우되, 네트워크 경계(anthropic.Anthropic.messages.create)만 가짜 응답으로 교체한다.
    anthropic 미설치 환경에서는 skip(실 호출 0 보장).
    """

    def setUp(self):
        self.user, self.client = _make_planner('sdk@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='SDK고객', birth_day='1990.06.01',
            consent_overseas_at=timezone.now())

    def test_real_parser_with_mocked_sdk_creates_insurance(self):
        import importlib.util
        if importlib.util.find_spec('anthropic') is None:
            self.skipTest('anthropic 미설치 — SDK mock 테스트 skip(실 호출 0)')

        import json as _json
        fake_json = _json.dumps({
            'insurance_type': 'loss', 'company_name': '삼성화재',
            'product_name': '무배당 종합보험', 'contractor': '김철수', 'insured': '김철수',
            'is_same_insured': True, 'payment_period': 20, 'warranty_period': 100,
            'warranty_period_unit': '세', 'contract_date': '2021.02.01', 'expiry_date': '',
            'monthly_premium': 60000, 'monthly_guarantee_premium': 60000,
            'coverages': [{
                'name': '일반암진단비', 'category': '진단비', 'subcategory': '암',
                'detail_name': '일반암', 'amount': 30000000, 'premium': 8000,
                'payment_period': 20, 'payment_period_type': 1,
                'warranty_period': 100, 'warranty_period_type': 1,
                'is_renewal': False, 'renewal_period': 0,
            }],
            'unmatched_coverages': [],
        })

        # anthropic.Anthropic().messages.create(...).content[0].text == fake_json
        fake_block = mock.Mock()
        fake_block.text = fake_json
        fake_msg = mock.Mock()
        fake_msg.content = [fake_block]
        fake_client = mock.Mock()
        fake_client.messages.create.return_value = fake_msg

        import anthropic
        with mock.patch.object(anthropic, 'Anthropic', return_value=fake_client) as m_client, \
                mock.patch('inpa.insurances.views._extract_pdf_lines',
                           return_value=(['삼성화재 무배당 종합보험 일반암진단비 3천만원'], None)):
            r = self.client.post(
                _ocr_url(self.customer.id), {'file': _dummy_pdf()}, format='multipart')

        self.assertEqual(r.status_code, 201, r.content)
        m_client.assert_called_once()  # SDK 클라이언트가 정확히 1회 생성됨(실 네트워크 없음)
        ci = CustomerInsurance.objects.get()
        self.assertEqual(ci.name, '무배당 종합보험')
        self.assertEqual(ci.insurance_type, 2)
        case = CustomerInsuranceDetail.objects.get()
        self.assertEqual(case.assurance_amount, 30000000)
        self.assertEqual(case.detail.name, '일반암')


@override_settings(ANTHROPIC_API_KEY='sk-ant-test')
class OwnerIsolationTests(TestCase):
    """(c) ★ owner 격리 — A 는 B 고객에 OCR 업로드 불가."""

    def setUp(self):
        self.user_a, self.client_a = _make_planner('a@test.com')
        self.user_b, self.client_b = _make_planner('b@test.com')
        self.cust_b = Customer.objects.create(
            owner=self.user_b, name='B의고객', consent_overseas_at=timezone.now())

    def test_a_cannot_ocr_upload_to_b_customer(self):
        with mock.patch('inpa.insurances.views.claude_parse') as m_parse, \
                mock.patch('inpa.insurances.views._extract_pdf_lines',
                           return_value=(['dummy'], None)):
            r = self.client_a.post(
                _ocr_url(self.cust_b.id), {'file': _dummy_pdf()}, format='multipart')
        self.assertEqual(r.status_code, 404)  # 존재 은폐
        m_parse.assert_not_called()
        self.assertEqual(CustomerInsurance.objects.count(), 0)


@override_settings(ANTHROPIC_API_KEY='sk-ant-test')
class NormalizationHookTests(TestCase):
    """정규화 훅(NormalizationDict) — 보험사별 담보 원문명 → 표준 담보 매핑 + hit_count++."""

    def setUp(self):
        self.user, self.client = _make_planner('norm@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='정규화고객', consent_overseas_at=timezone.now())
        # 표준 담보 트리: 진단비 > 암 > 일반암
        cat = AnalysisCategory.objects.create(insurance_type=2, name='진단비', order=1)
        sub = AnalysisSubCategory.objects.create(insurance_type=2, category=cat, name='암', order=1)
        self.std = AnalysisDetail.objects.create(sub_category=sub, name='일반암', order=1)
        # 삼성화재(2) 의 보험사별 표기 "삼성헬스케어암진단" → 일반암 (관리자 검수본)
        self.entry = NormalizationDict.objects.create(
            std_detail=self.std, company=2, raw_name='삼성헬스케어암진단',
            source=NormalizationDict.SOURCE_ADMIN_VERIFIED, hit_count=0)

    def test_normalizer_maps_raw_to_standard_and_increments_hit(self):
        from inpa.insurances.views import _build_normalizer
        normalizer = _build_normalizer()
        result = normalizer('삼성헬스케어암진단', 2)  # company_idx=2 (삼성화재)
        self.assertEqual(result, ('진단비', '암', '일반암'))
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.hit_count, 1)  # ★ 데이터 복리 계측

    def test_normalizer_returns_none_for_unknown(self):
        from inpa.insurances.views import _build_normalizer
        normalizer = _build_normalizer()
        self.assertIsNone(normalizer('알수없는담보명', 2))
        self.assertIsNone(normalizer('삼성헬스케어암진단', 7))  # 다른 보험사 → 미스
