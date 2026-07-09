"""증권 OCR 업로드 핵심 게이트 테스트 (dev/12 §0 원칙, dev/03 포팅지도).

★ 필수 3종 (작업 지시):
  (a) 동의 게이트 — consent_overseas_at 없으면 OCR 업로드 412 + Claude 호출 0회(물리 차단).
  (b) Claude 클라이언트 mock — 파싱 → CustomerInsurance + CustomerInsuranceDetail 생성 검증.
  (c) owner 격리 — 설계사 A 가 B 고객에 OCR 업로드하면 404(존재 은폐).
+ 정규화 훅(NormalizationDict) 적용 / API 키 미설정 503 / anthropic 실클라이언트 mock 보강.

★ 실제 Claude 호출 금지 — 모든 파싱 경로는 mock.
"""
from decimal import Decimal
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
from inpa.customers.consent_texts import CONSENT_TEXTS_VERSION
from inpa.customers.models import ConsentLog, Customer

from .models import (
    CustomerInsurance, CustomerInsuranceDetail, InsuranceDetail,
    InsuranceCategory, InsuranceSubCategory,
)
from .serializers import CaseFeeSerializer, InsuranceFeeSerializer


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


def _grant_overseas(customer, version=CONSENT_TEXTS_VERSION):
    """현재 문구 버전 고객 본인 국외이전 동의 = OCR 게이트 통과 조건.

    version=''로 부르면 구버전 동의(재동의 필요) 상황 재현.
    """
    customer.consent_overseas_at = timezone.now()
    customer.save(update_fields=['consent_overseas_at'])
    return ConsentLog.objects.create(
        customer=customer, scope=ConsentLog.SCOPE_OVERSEAS_MEDICAL,
        subject=ConsentLog.SUBJECT_CUSTOMER_SELF, doc_version=version)


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
    # 케이스별 원문명 병렬 맵 (claude_parser._add_coverage 가 실는 형태 — 담보 사전 피드백)
    ocr._raw_name_by_case = {
        ('진단비', '암', '일반암', '20:1:100:1:50000000:10000'): '삼성 암진단특약(무배당)',
    }
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
        self.assertEqual(r.json()['reason'], 'missing')
        # ★ Claude 호출이 물리적으로 일어나지 않았는지 확인
        m_parse.assert_not_called()
        self.assertEqual(CustomerInsurance.objects.count(), 0)

    def test_ocr_upload_old_version_consent_requires_reconsent(self):
        """구버전 문구 동의만 있으면 재동의 필요 → 412 reason=reconsent, Claude 호출 0."""
        _grant_overseas(self.customer, version='')
        with mock.patch('inpa.insurances.views.claude_parse') as m_parse:
            r = self.client.post(
                _ocr_url(self.customer.id), {'file': _dummy_pdf()}, format='multipart')
        self.assertEqual(r.status_code, 412)
        self.assertEqual(r.json()['code'], 'CONSENT_OVERSEAS_REQUIRED')
        self.assertEqual(r.json()['reason'], 'reconsent')
        m_parse.assert_not_called()

    def test_planner_attested_consent_does_not_open_gate(self):
        """★ 카나리아: 설계사 대리 동의(현재 버전이어도)는 게이트를 열지 못한다 → 412."""
        self.customer.consent_overseas_at = timezone.now()
        self.customer.save(update_fields=['consent_overseas_at'])
        ConsentLog.objects.create(
            customer=self.customer, scope=ConsentLog.SCOPE_OVERSEAS_MEDICAL,
            subject=ConsentLog.SUBJECT_PLANNER_ATTESTED, doc_version=CONSENT_TEXTS_VERSION)
        with mock.patch('inpa.insurances.views.claude_parse') as m_parse:
            r = self.client.post(
                _ocr_url(self.customer.id), {'file': _dummy_pdf()}, format='multipart')
        self.assertEqual(r.status_code, 412)
        self.assertEqual(r.json()['reason'], 'reconsent')
        m_parse.assert_not_called()

    def test_ocr_upload_passes_gate_after_consent(self):
        """현재 버전 고객 본인 동의가 있으면 게이트 통과 → 파싱 단계 진입(여기선 mock)."""
        _grant_overseas(self.customer)
        with mock.patch('inpa.insurances.views.claude_parse', return_value=_fake_ocr_data()) as m_parse, \
                mock.patch('inpa.insurances.views._extract_pdf_lines',
                           return_value=(['삼성화재 종합보험 암진단 5천만원'], None)), \
                override_settings(ANTHROPIC_API_KEY='sk-ant-test', OCR_VERIFY_ENABLED=False):
            r = self.client.post(
                _ocr_url(self.customer.id), {'file': _dummy_pdf()}, format='multipart')
        self.assertEqual(r.status_code, 201, r.content)
        m_parse.assert_called_once()


@override_settings(ANTHROPIC_API_KEY='sk-ant-test', OCR_VERIFY_ENABLED=False)
class OcrParsePersistTests(TestCase):
    """(b) Claude mock → 파싱 → CustomerInsurance + Detail 생성."""

    def setUp(self):
        self.user, self.client = _make_planner('parse@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='동의고객', birth_day='1985.03.10', gender=1)
        _grant_overseas(self.customer)

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

    def test_persist_stores_raw_name_and_company(self):
        """담보 사전 피드백(2026-07-09): 케이스 원문명 + 보험사 코드 보존 회귀."""
        r = self._upload()
        self.assertEqual(r.status_code, 201, r.content)
        ci = CustomerInsurance.objects.get()
        self.assertEqual(ci.company, 2)  # 삼성화재 (head['손해보험'])
        case = CustomerInsuranceDetail.objects.get()
        self.assertEqual(case.raw_name, '삼성 암진단특약(무배당)')

    def test_persist_raw_name_empty_without_map(self):
        """원문 맵이 없는 레거시 Ocr_Data 경로 → raw_name 빈 값(graceful)."""
        ocr = _fake_ocr_data()
        del ocr._raw_name_by_case
        with mock.patch('inpa.insurances.views.claude_parse', return_value=ocr), \
                mock.patch('inpa.insurances.views._extract_pdf_lines',
                           return_value=(['dummy'], None)):
            r = self.client.post(
                _ocr_url(self.customer.id), {'file': _dummy_pdf()}, format='multipart')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(CustomerInsuranceDetail.objects.get().raw_name, '')

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


class BridgePreservesAdminLinkTests(TestCase):
    """★ _get_or_create_detail 은 무연결 행만 브리지로 잇는다 (2026-07-09 리뷰 F3).

    카탈로그(InsuranceDetail) 행은 전 고객 공유 — 어드민 정정(set([new_leaf]),
    담보 사전 피드백 accept)이 다음 업로드의 무조건 .add(bridge_std) 로 옛 leaf 가
    재추가되면 이중 연결 = 히트맵 이중 집계로 되돌아간다. repair_analysis_links 와
    동일한 '무연결 행만 후보' 규칙을 회귀로 고정한다.
    """

    def setUp(self):
        # 브리지 대상 [표준] 트리: PARSER_TO_STD[('진단비','암','일반암')] = '일반암진단비'
        cat = AnalysisCategory.objects.create(insurance_type=0, name='[표준] 진단비')
        sub = AnalysisSubCategory.objects.create(insurance_type=0, category=cat, name='암')
        self.bridge_leaf = AnalysisDetail.objects.create(sub_category=sub, name='일반암진단비')
        self.other_leaf = AnalysisDetail.objects.create(sub_category=sub, name='유사암진단비')

    def test_zero_link_row_gets_bridge_link(self):
        """무연결 신규 행은 기존처럼 브리지로 연결된다(기능 보존)."""
        from inpa.insurances.views import _get_or_create_detail
        det = _get_or_create_detail('진단비', '암', '일반암', 2)
        self.assertEqual(
            list(det.analysis_detail.values_list('id', flat=True)),
            [self.bridge_leaf.id])

    def test_admin_corrected_row_is_not_relinked_on_next_upload(self):
        """어드민 정정(set([other]))된 행은 다음 업로드에서 옛 leaf 가 재추가되지 않는다."""
        from inpa.insurances.views import _get_or_create_detail
        det = _get_or_create_detail('진단비', '암', '일반암', 2)
        # 어드민 정정 시뮬레이션 (resolve accept 의 M2M 교체와 동일)
        det.analysis_detail.set([self.other_leaf])
        # 다음 업로드가 같은 이름의 카탈로그 행을 다시 통과
        det2 = _get_or_create_detail('진단비', '암', '일반암', 2)
        self.assertEqual(det2.id, det.id)
        self.assertEqual(
            list(det2.analysis_detail.values_list('id', flat=True)),
            [self.other_leaf.id])  # 옛 브리지 leaf 미재추가 — 정정 보존


def _fake_life_ocr_data():
    """생명보험 Ocr_Data — head 는 raw index(6=삼성생명), 담보 1건 + 미매칭 1건."""
    ocr = Ocr_Data()
    ocr.parsing_method = 'claude'
    ocr.is_same_insured = True
    head = ocr.dict_life_head_data
    head['생명보험'] = 6  # 삼성생명 (LifeInsurance raw index)
    head['상품명'] = '무배당 종신보험'
    head['계약자'] = '홍길동'
    head['피보험자'] = '홍길동'
    head['납입기간'] = 20
    head['보장기간'] = 100
    head['월납입보험료'] = 50000
    head['계약일'] = '2020.01.15'
    ocr.dict_detail_data['진단비']['암']['일반암'].append('20:1:100:1:50000000:10000')
    ocr._unmatched_coverages = ['미지의생명담보']
    return ocr


class LifeCompanyDictSpaceTests(TestCase):
    """★ 생명보험 사전 코드 공간(200+index) 회귀 (2026-07-09 리뷰 F1).

    규약(seed_normalization 보험사 코드): 손해 = raw index, 생명 = 200 + LifeInsurance
    index (예: 삼성생명 = 206). head dict 는 raw index 를 유지하되, 사전(NormalizationDict)
    룩업·persist(company)·UnmatchedLog 는 전부 사전 공간 코드를 써야 한다.
    이 정합이 깨지면 생명 별칭이 등록돼도 파싱 시점에 절대 매칭되지 않는다.
    """

    def setUp(self):
        self.user, self.client = _make_planner('lifedict@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='생명고객', birth_day='1985.03.10', gender=1)
        # 파서 dict_detail_data 경로(진단비>암>일반암)와 같은 이름의 표준 트리
        # — normalizer 가 (cat,sub,det) 이름 경로를 돌려줘야 _add_coverage 가 안착.
        cat = AnalysisCategory.objects.create(insurance_type=1, name='진단비')
        sub = AnalysisSubCategory.objects.create(insurance_type=1, category=cat, name='암')
        self.std = AnalysisDetail.objects.create(sub_category=sub, name='일반암')

    def _parsed_life(self, coverage_name):
        """Claude 응답 JSON 흉내 — 삼성생명(사전 공간 206) + 담보 1건."""
        return {
            'insurance_type': 'life',
            'company_name': '삼성생명',
            'product_name': '무배당 종신보험',
            'contractor': '홍길동', 'insured': '홍길동', 'is_same_insured': True,
            'payment_period': 20, 'warranty_period': 100, 'monthly_premium': 50000,
            'coverages': [{
                'category': '', 'subcategory': '', 'detail_name': '',
                'name': coverage_name, 'amount': 50000000, 'premium': 10000,
                'payment_period': 20, 'payment_period_type': 1,
                'warranty_period': 100, 'warranty_period_type': 1,
            }],
        }

    def test_life_alias_200_space_fires_at_parse_time(self):
        """company=206(200+삼성생명) admin_verified 별칭이 파싱 시점 룩업에서 실제 발화."""
        from inpa.core.ocr.claude_parser import _convert_to_ocr_data
        from inpa.insurances.views import _build_normalizer
        # 키워드 매칭으로는 절대 안 잡히는 원문 → 별칭이 유일한 매칭 경로(회귀 증명)
        NormalizationDict.objects.create(
            std_detail=self.std, company=206, raw_name='우리집든든플랜2형',
            source=NormalizationDict.SOURCE_ADMIN_VERIFIED)
        ocr = _convert_to_ocr_data(
            self._parsed_life('우리집든든플랜2형'), normalizer=_build_normalizer())
        self.assertIsNotNone(ocr)
        # head dict 는 raw index 유지 (ocrdata 소비자 계약)
        self.assertEqual(ocr.dict_life_head_data['생명보험'], 6)
        # 별칭 발화 → 표준 경로에 담보 안착 + hit_count 증가
        self.assertEqual(
            ocr.dict_detail_data['진단비']['암']['일반암'],
            ['20:1:100:1:50000000:10000'])
        norm = NormalizationDict.objects.get(raw_name='우리집든든플랜2형')
        self.assertEqual(norm.hit_count, 1)

    def test_life_alias_in_raw_index_space_does_not_fire(self):
        """(음성 대조) raw index 공간(company=6)에 잘못 등록된 별칭은 매칭되지 않는다."""
        from inpa.core.ocr.claude_parser import _convert_to_ocr_data
        from inpa.insurances.views import _build_normalizer
        NormalizationDict.objects.create(
            std_detail=self.std, company=6, raw_name='우리집든든플랜2형',
            source=NormalizationDict.SOURCE_ADMIN_VERIFIED)
        ocr = _convert_to_ocr_data(
            self._parsed_life('우리집든든플랜2형'), normalizer=_build_normalizer())
        self.assertIsNotNone(ocr)
        self.assertEqual(ocr.dict_detail_data['진단비']['암']['일반암'], [])
        norm = NormalizationDict.objects.get(raw_name='우리집든든플랜2형')
        self.assertEqual(norm.hit_count, 0)

    def test_persist_life_company_code_offset(self):
        """persist: CustomerInsurance.company·UnmatchedLog.company = 200+index 공간."""
        from inpa.analysis.models import UnmatchedLog
        from inpa.insurances.views import _persist_ocr
        ci, _created = _persist_ocr(self.customer, _fake_life_ocr_data())
        self.assertEqual(ci.insurance_type, 1)  # 생명
        self.assertEqual(ci.company, 206)       # 200 + 6(삼성생명)
        log = UnmatchedLog.objects.get(raw_name='미지의생명담보')
        self.assertEqual(log.company, 206)


class AddCoverageRawNameMapTests(TestCase):
    """claude_parser._add_coverage 원문명 병렬 맵 회귀 (담보 사전 피드백, 2026-07-09).

    dict_detail_data 값 문자열에는 원문명이 없어 (cat, sub, det, value) 키의 병렬 맵으로
    실어 나른다 — _persist_ocr 저장 키와 정확히 같은 형태인지 파서 경로에서 직접 검증.
    """

    def test_add_coverage_records_raw_name(self):
        from inpa.core.ocr.claude_parser import _add_coverage
        ocr = Ocr_Data()
        cov = {'category': '진단비', 'subcategory': '암', 'detail_name': '일반암',
               'name': '삼성 암진단특약(무배당)', 'amount': 50000000, 'premium': 10000,
               'payment_period': 20, 'payment_period_type': 1,
               'warranty_period': 100, 'warranty_period_type': 1}
        _add_coverage(ocr, cov, 20, 100)
        value = '20:1:100:1:50000000:10000'
        self.assertEqual(ocr.dict_detail_data['진단비']['암']['일반암'], [value])
        self.assertEqual(
            ocr._raw_name_by_case[('진단비', '암', '일반암', value)],
            '삼성 암진단특약(무배당)')

    def test_dedup_replacement_records_new_raw_name(self):
        """동일 가입조건 큰 금액 교체 시 새 value 키로 원문이 기록된다."""
        from inpa.core.ocr.claude_parser import _add_coverage
        ocr = Ocr_Data()
        base = {'category': '진단비', 'subcategory': '암', 'detail_name': '일반암',
                'premium': 10000, 'payment_period': 20, 'payment_period_type': 1,
                'warranty_period': 100, 'warranty_period_type': 1}
        _add_coverage(ocr, {**base, 'name': '작은담보', 'amount': 10000000}, 20, 100)
        _add_coverage(ocr, {**base, 'name': '큰담보', 'amount': 50000000}, 20, 100)
        value = '20:1:100:1:50000000:10000'
        self.assertEqual(ocr.dict_detail_data['진단비']['암']['일반암'], [value])
        self.assertEqual(
            ocr._raw_name_by_case[('진단비', '암', '일반암', value)], '큰담보')


@override_settings(ANTHROPIC_API_KEY='sk-ant-test', CLAUDE_API_KEY='sk-ant-test', OCR_VERIFY_ENABLED=False)
class AnthropicClientMockTests(TestCase):
    """(b 보강) anthropic.Anthropic SDK 자체를 mock → 실제 claude_parse 파이프라인 통과.

    벤더링한 claude_parser 전 구간(JSON 추출→_convert_to_ocr_data→_add_coverage→정규화 훅)을
    실제로 태우되, 네트워크 경계(anthropic.Anthropic.messages.create)만 가짜 응답으로 교체한다.
    anthropic 미설치 환경에서는 skip(실 호출 0 보장).
    """

    def setUp(self):
        self.user, self.client = _make_planner('sdk@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='SDK고객', birth_day='1990.06.01')
        _grant_overseas(self.customer)

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


@override_settings(ANTHROPIC_API_KEY='sk-ant-test', CLAUDE_API_KEY='sk-ant-test',
                    OCR_VERIFY_ENABLED=False, CLAUDE_USD_KRW_RATE=1000.0)
class ClaudeApiLogWiringTests(TestCase):
    """프리런치 #17 — ocr_parse 호출 경로가 성공·실패 모두 ClaudeApiLog 1건을 남긴다."""

    def setUp(self):
        import importlib.util
        if importlib.util.find_spec('anthropic') is None:
            self.skipTest('anthropic 미설치 — SDK mock 테스트 skip(실 호출 0)')
        self.user, self.client = _make_planner('claudelog-ocr@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='로그고객', birth_day='1990.06.01')
        _grant_overseas(self.customer)

    def test_success_logs_user_outcome_carrier_matched_unmatched(self):
        from inpa.billing.models import ClaudeApiLog

        import json as _json
        fake_json = _json.dumps({
            'insurance_type': 'loss', 'company_name': '삼성화재',
            'product_name': '무배당 종합보험', 'contractor': '김철수', 'insured': '김철수',
            'is_same_insured': True, 'payment_period': 20, 'warranty_period': 100,
            'contract_date': '2021.02.01',
            'coverages': [{
                'name': '일반암진단비', 'category': '진단비', 'subcategory': '암',
                'detail_name': '일반암', 'amount': 30000000, 'premium': 8000,
            }],
            'unmatched_coverages': ['알수없는특약'],
        })
        fake_block = mock.Mock()
        fake_block.text = fake_json
        fake_usage = mock.Mock(input_tokens=1000, output_tokens=200,
                               cache_read_input_tokens=0, cache_creation_input_tokens=0)
        fake_msg = mock.Mock()
        fake_msg.content = [fake_block]
        fake_msg.usage = fake_usage
        fake_client = mock.Mock()
        fake_client.messages.create.return_value = fake_msg

        import anthropic
        with mock.patch.object(anthropic, 'Anthropic', return_value=fake_client), \
                mock.patch('inpa.insurances.views._extract_pdf_lines',
                           return_value=(['삼성화재 무배당 종합보험 일반암진단비 3천만원'], None)):
            r = self.client.post(
                _ocr_url(self.customer.id), {'file': _dummy_pdf()}, format='multipart')

        self.assertEqual(r.status_code, 201, r.content)
        log = ClaudeApiLog.objects.get(action='ocr_parse')
        self.assertEqual(log.user_id, self.user.id)
        self.assertEqual(log.parse_outcome, 'success')
        self.assertEqual(log.carrier_code, 2)  # 삼성화재 = 손해보험 raw idx 2
        self.assertEqual(log.matched_count, 1)
        self.assertEqual(log.unmatched_count, 1)
        self.assertEqual(log.input_tokens, 1000)
        self.assertEqual(log.output_tokens, 200)
        self.assertGreater(log.cost_krw, 0)

    def test_json_invalid_outcome_logged_on_bad_response(self):
        """Claude 응답이 JSON이 아니면 422 + ClaudeApiLog(outcome=json_invalid) 1건."""
        from inpa.billing.models import ClaudeApiLog

        fake_block = mock.Mock()
        fake_block.text = '이건 JSON이 아닙니다'
        fake_usage = mock.Mock(input_tokens=40, output_tokens=3,
                               cache_read_input_tokens=0, cache_creation_input_tokens=0)
        fake_msg = mock.Mock()
        fake_msg.content = [fake_block]
        fake_msg.usage = fake_usage
        fake_client = mock.Mock()
        fake_client.messages.create.return_value = fake_msg

        import anthropic
        with mock.patch.object(anthropic, 'Anthropic', return_value=fake_client), \
                mock.patch('inpa.insurances.views._extract_pdf_lines',
                           return_value=(['dummy'], None)):
            r = self.client.post(
                _ocr_url(self.customer.id), {'file': _dummy_pdf()}, format='multipart')

        self.assertEqual(r.status_code, 422)
        self.assertEqual(CustomerInsurance.objects.count(), 0)
        log = ClaudeApiLog.objects.get(action='ocr_parse')
        self.assertEqual(log.parse_outcome, 'json_invalid')
        self.assertEqual(log.user_id, self.user.id)
        self.assertEqual(log.input_tokens, 40)  # 실패해도 usage(호출 자체는 성공)는 기록

    def test_api_error_outcome_logged_on_sdk_exception(self):
        """SDK 호출 자체가 예외 → 422 + ClaudeApiLog(outcome=api_error, 토큰 0)."""
        from inpa.billing.models import ClaudeApiLog

        fake_client = mock.Mock()
        fake_client.messages.create.side_effect = RuntimeError('boom')

        import anthropic
        with mock.patch.object(anthropic, 'Anthropic', return_value=fake_client), \
                mock.patch('inpa.insurances.views._extract_pdf_lines',
                           return_value=(['dummy'], None)):
            r = self.client.post(
                _ocr_url(self.customer.id), {'file': _dummy_pdf()}, format='multipart')

        self.assertEqual(r.status_code, 422)
        log = ClaudeApiLog.objects.get(action='ocr_parse')
        self.assertEqual(log.parse_outcome, 'api_error')
        self.assertEqual(log.input_tokens, 0)
        self.assertEqual(log.cost_krw, Decimal('0'))


@override_settings(ANTHROPIC_API_KEY='sk-ant-test', OCR_VERIFY_ENABLED=False)
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


@override_settings(ANTHROPIC_API_KEY='sk-ant-test', OCR_VERIFY_ENABLED=False)
class NormalizationHookTests(TestCase):
    """정규화 훅(NormalizationDict) — 보험사별 담보 원문명 → 표준 담보 매핑 + hit_count++."""

    def setUp(self):
        self.user, self.client = _make_planner('norm@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='정규화고객')
        _grant_overseas(self.customer)
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


# ──────────────────────────────────────────────────────────────────────
# 환수 레이더(A/S) — GET /churn-radar/ 집계 + PATCH /insurances/<pk>/churn/
# ★ 보유(portfolio_type=1)만 / owner 전용 / 수기입력 추정.
# ──────────────────────────────────────────────────────────────────────
import datetime as _dt


def _make_held(customer, *, status=None, period=None, next_days=None, recovery=None):
    """보유(portfolio_type=1) 계약 1건 + 환수 필드 수기값."""
    nxt = None
    if next_days is not None:
        nxt = _dt.date.today() + _dt.timedelta(days=next_days)
    return CustomerInsurance.objects.create(
        customer=customer, insurance_type=2, name='보유보험', portfolio_type=1,
        payment_status=status, current_payment_period=period,
        next_payment_date=nxt, expected_recovery_amount=recovery,
    )


class ChurnRadarTests(TestCase):
    """환수 레이더 집계 + 수기입력 + owner 격리."""

    def setUp(self):
        self.user, self.client = _make_planner('churn@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='환수고객', birth_day='1988.03.03', gender=1)

    def test_radar_empty(self):
        body = self.client.get('/api/v1/churn-radar/').json()
        self.assertEqual(body['risk_count'], 0)
        self.assertEqual(body['expected_recovery_total'], 0)
        self.assertEqual(body['items'], [])

    def test_milestone_imminent_flagged(self):
        """25회차 2회 이내(24회차) → 회차 임박(is_at_risk), persistency=pre_25. 환수액 자동산출 없음."""
        _make_held(self.customer, period=24)
        body = self.client.get('/api/v1/churn-radar/').json()
        self.assertEqual(body['risk_count'], 1)
        self.assertEqual(body['expected_recovery_total'], 0)
        item = body['items'][0]
        self.assertTrue(item['is_at_risk'])
        self.assertEqual(item['persistency_stage'], 'pre_25')
        self.assertIn('25회차', item['risk_reason'])

    def test_midwindow_not_imminent(self):
        """회차 중간(18회차) → 임박 아님(13/25 어느 쪽도 2회 밖). 연체값 있어도 무시."""
        _make_held(self.customer, status=2, period=18)
        body = self.client.get('/api/v1/churn-radar/').json()
        self.assertEqual(body['risk_count'], 0)
        self.assertEqual(body['items'][0]['persistency_stage'], 'pre_25')

    def test_safe_period_not_imminent(self):
        """25회차 이상이면 환수 구간 밖 → 임박 아님."""
        _make_held(self.customer, period=30)
        body = self.client.get('/api/v1/churn-radar/').json()
        self.assertEqual(body['risk_count'], 0)
        self.assertEqual(body['items'][0]['persistency_stage'], 'safe')

    def test_proposed_excluded(self):
        """제안(portfolio_type=2)은 환수 대상 아님 → 리스트 제외."""
        CustomerInsurance.objects.create(
            customer=self.customer, insurance_type=2, name='제안보험',
            portfolio_type=2, payment_status=2, current_payment_period=3)
        body = self.client.get('/api/v1/churn-radar/').json()
        self.assertEqual(body['items'], [])

    def test_patch_updates_churn_fields(self):
        ci = _make_held(self.customer)
        r = self.client.patch(
            f'/api/v1/insurances/{ci.id}/churn/',
            {'current_payment_period': 8, 'payment_status': 2,
             'next_payment_date': '2026-07-01', 'expected_recovery_amount': 900000},
            format='json')
        self.assertEqual(r.status_code, 200)
        ci.refresh_from_db()
        self.assertEqual(ci.current_payment_period, 8)
        self.assertEqual(ci.payment_status, 2)
        self.assertEqual(ci.next_payment_date, _dt.date(2026, 7, 1))
        self.assertEqual(ci.expected_recovery_amount, 900000)

    def test_patch_rejects_bad_status(self):
        ci = _make_held(self.customer)
        r = self.client.patch(f'/api/v1/insurances/{ci.id}/churn/',
                              {'payment_status': 9}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_owner_isolation_radar_and_patch(self):
        """A의 보유계약은 B의 레이더에 안 보이고, B가 PATCH하면 404."""
        ci = _make_held(self.customer, status=2, period=4)
        _, client_b = _make_planner('churn-b@test.com')
        body_b = client_b.get('/api/v1/churn-radar/').json()
        self.assertEqual(body_b['items'], [])
        r = client_b.patch(f'/api/v1/insurances/{ci.id}/churn/',
                           {'current_payment_period': 1}, format='json')
        self.assertEqual(r.status_code, 404)


class ChurnSyncAlertsTests(TestCase):
    """환수 위험 → 인앱 Notification 생성(dedup)."""

    def setUp(self):
        self.user, self.client = _make_planner('sync@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='동기화고객', birth_day='1990.01.01', gender=1)

    def test_creates_and_dedups(self):
        from inpa.notifications.models import Notification, NotifType
        _make_held(self.customer, period=12)  # 13회차 1회 전 → 임박
        r1 = self.client.post('/api/v1/churn-radar/sync-alerts/')
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.json()['created'], 1)
        # 재호출 → 당일 dedup(고객당 1건)
        r2 = self.client.post('/api/v1/churn-radar/sync-alerts/')
        self.assertEqual(r2.json()['created'], 0)
        self.assertEqual(
            Notification.objects.filter(
                owner=self.user, notif_type=NotifType.UNPAID_D_ALERT).count(), 1)

    def test_no_risk_no_alert(self):
        _make_held(self.customer, status=1, period=30)  # 안전
        r = self.client.post('/api/v1/churn-radar/sync-alerts/')
        self.assertEqual(r.json()['created'], 0)


class SelfDiagnosisGateTests(TestCase):
    """셀프진단 인바운드 — 본인정보 필수 + 동의 게이트 + 무첨부 리드 접수(OCR 이전 단계)."""

    # 본인 식별 정보 필수 — 유효 페이로드 베이스(PM 06.30).
    BASE = {'name': '홍길동', 'phone': '01012345678', 'birth': '1990-01-01', 'gender': '1'}

    def setUp(self):
        from django.core.cache import cache
        cache.clear()  # ScopedRateThrottle 카운터 격리(테스트 간섭 방지)
        self.planner, _ = _make_planner('refplanner@test.com')
        self.ref = self.planner.profile.ref_code
        self.public = APIClient()  # 비로그인

    def test_invalid_ref_404(self):
        r = self.public.post('/api/v1/d/NOPECODE/', {}, format='multipart')
        self.assertEqual(r.status_code, 404)

    def test_missing_identity_400(self):
        """이름·연락처·생년월일·성별 없으면 400 — 동의 검사 전에 차단."""
        r = self.public.post(
            f'/api/v1/d/{self.ref}/',
            {'consent_overseas': 'true', 'consent_share': 'true'}, format='multipart')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['code'], 'NAME_REQUIRED')

    def test_invalid_phone_400(self):
        r = self.public.post(
            f'/api/v1/d/{self.ref}/',
            {**self.BASE, 'phone': '123', 'consent_share': 'true'}, format='multipart')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['code'], 'INVALID_PHONE')

    def test_missing_share_consent_412(self):
        """개인정보 수집·이용(설계사 전달) 동의 없으면 412."""
        r = self.public.post(f'/api/v1/d/{self.ref}/', {**self.BASE}, format='multipart')
        self.assertEqual(r.status_code, 412)
        self.assertEqual(r.json()['code'], 'CONSENT_REQUIRED')

    def test_no_pdf_creates_lead_201(self):
        """증권 미첨부라도 본인정보+필수동의면 리드 접수(201, analyzed=False). OCR 안 함."""
        from inpa.customers.models import Customer, ConsentLog
        r = self.public.post(
            f'/api/v1/d/{self.ref}/',
            {**self.BASE, 'consent_share': 'true'}, format='multipart')
        self.assertEqual(r.status_code, 201)
        body = r.json()
        self.assertTrue(body['lead_created'])
        self.assertFalse(body['analyzed'])
        c = Customer.objects.get(owner=self.planner, lead_source='self_diagnosis')
        self.assertEqual(c.name, '홍길동')
        self.assertEqual(c.birth_day, '1990-01-01')
        self.assertEqual(c.gender, 1)
        # 전송 없음 → 국외이전 게이트 비개방, 개인정보 동의는 기록.
        self.assertIsNone(c.consent_overseas_at)
        pi_log = c.consent_logs.get(scope=ConsentLog.SCOPE_PERSONAL_INFO)
        self.assertEqual(pi_log.doc_version, CONSENT_TEXTS_VERSION)  # 버전 스탬프
        self.assertFalse(c.consent_logs.filter(scope=ConsentLog.SCOPE_OVERSEAS_MEDICAL).exists())

    def test_third_party_consent_recorded(self):
        """제3자 제공·플랫폼 활용(선택) 체크 시에만 ConsentLog 기록."""
        from inpa.customers.models import Customer, ConsentLog
        r = self.public.post(
            f'/api/v1/d/{self.ref}/',
            {**self.BASE, 'consent_share': 'true', 'consent_thirdparty': 'true'}, format='multipart')
        self.assertEqual(r.status_code, 201)
        c = Customer.objects.get(owner=self.planner, lead_source='self_diagnosis')
        self.assertTrue(c.consent_logs.filter(scope=ConsentLog.SCOPE_THIRD_PARTY).exists())


# 테스트용 더미 값(실제 키 아님). 변수로 두어 'KEY=리터럴' 패턴을 만들지 않는다
# (gitleaks generic-api-key 오탐 회피 — 키 이름 없는 변수라 규칙에 걸리지 않음).
_DUMMY_KEY = 'test-key'


@override_settings(
    ANTHROPIC_API_KEY=_DUMMY_KEY,
    CLAUDE_API_KEY=_DUMMY_KEY,
    CLAUDE_USD_KRW_RATE=1000.0,
)
class SelfDiagnosisClaudeApiLogTests(TestCase):
    """프리런치 #17 — /d(비로그인 공개) 경로도 ClaudeApiLog 를 남긴다(user=None, 실 SDK mock)."""

    BASE = {'name': '홍길동', 'phone': '01012345678', 'birth': '1990-01-01', 'gender': '1',
            'consent_share': 'true', 'consent_overseas': 'true'}

    def setUp(self):
        import importlib.util
        if importlib.util.find_spec('anthropic') is None:
            self.skipTest('anthropic 미설치 — SDK mock 테스트 skip(실 호출 0)')
        from django.core.cache import cache
        cache.clear()
        self.planner, _ = _make_planner('claudelog-d@test.com')
        self.ref = self.planner.profile.ref_code
        self.public = APIClient()

    def test_public_diagnosis_logs_claude_api_log_with_null_user(self):
        from inpa.billing.models import ClaudeApiLog

        import json as _json
        fake_json = _json.dumps({
            'insurance_type': 'loss', 'company_name': '삼성화재',
            'product_name': '무배당 종합보험', 'payment_period': 20, 'warranty_period': 100,
            'coverages': [{
                'name': '일반암진단비', 'category': '진단비', 'subcategory': '암',
                'detail_name': '일반암', 'amount': 30000000, 'premium': 8000,
                'payment_period': 20, 'warranty_period': 100,
            }],
            'unmatched_coverages': [],
        })
        fake_block = mock.Mock()
        fake_block.text = fake_json
        fake_usage = mock.Mock(input_tokens=500, output_tokens=80,
                               cache_read_input_tokens=0, cache_creation_input_tokens=0)
        fake_msg = mock.Mock()
        fake_msg.content = [fake_block]
        fake_msg.usage = fake_usage
        fake_client = mock.Mock()
        fake_client.messages.create.return_value = fake_msg

        pdf = SimpleUploadedFile('policy.pdf', b'%PDF-1.4 dummy', content_type='application/pdf')

        import anthropic
        with mock.patch.object(anthropic, 'Anthropic', return_value=fake_client), \
                mock.patch('inpa.insurances.self_diagnosis._extract_pdf_lines',
                           return_value=(['삼성화재 무배당 종합보험 일반암진단비 3천만원'], None)):
            r = self.public.post(
                f'/api/v1/d/{self.ref}/', {**self.BASE, 'file': pdf}, format='multipart')

        self.assertEqual(r.status_code, 201, r.content)
        log = ClaudeApiLog.objects.get(action='self_diagnosis')
        self.assertIsNone(log.user)  # ★ /d 는 비로그인 공개 경로 → 귀속 없음
        self.assertEqual(log.parse_outcome, 'success')
        self.assertEqual(log.input_tokens, 500)
        self.assertEqual(log.output_tokens, 80)
        self.assertGreater(log.cost_krw, 0)


def _fake_ocr_product(product_name, cat='진단비', sub='암', det='일반암',
                      amount=50000000, monthly=30000):
    """다중 업로드용 mock Ocr_Data — 상품명·담보 경로를 파일별로 다르게 만든다."""
    ocr = Ocr_Data()
    ocr.parsing_method = 'claude'
    ocr.is_same_insured = True
    head = ocr.dict_loss_head_data
    head['손해보험'] = 2  # 삼성화재
    head['상품명'] = product_name
    head['계약자'] = '홍길동'
    head['피보험자'] = '홍길동'
    head['납입기간'] = 20
    head['보장기간'] = 100
    head['월납입보험료'] = monthly
    head['월보장보험료'] = monthly
    head['계약일'] = '2020.01.15'
    head['payment_period_type'] = 1
    head['warranty_period_type'] = 1
    ocr.dict_detail_data[cat][sub][det].append(f'20:1:100:1:{amount}:10000')
    return ocr


def _tree_detail_names(tree):
    """트리 → leaf 담보 이름 set (보험별 트리 분리 검증용)."""
    return {det['name'] for c in tree for s in c['sub_categories'] for det in s['details']}


# ──────────────────────────────────────────────────────────────────────
# 셀프진단 다중 증권(files) — 파일별 독립 파싱·캡 소모 + insurances[] 카드 응답
# ──────────────────────────────────────────────────────────────────────
@override_settings(ANTHROPIC_API_KEY='test-key')
class SelfDiagnosisMultiPdfTests(TestCase):
    """PM 2026-07-07: 증권 여러 장 업로드 → 보험별 카드(insurances[]) 응답."""

    BASE = {'name': '홍길동', 'phone': '01012345678', 'birth': '1990-01-01', 'gender': '1',
            'consent_share': 'true', 'consent_overseas': 'true'}

    def setUp(self):
        from django.core.cache import cache
        from django.core.management import call_command
        cache.clear()  # throttle + 파싱 카운터 격리
        call_command('seed_normalization')  # 표준 트리 — 보험별 트리 분리 검증에 필요
        self.planner, _ = _make_planner('multipdf@test.com')
        self.ref = self.planner.profile.ref_code
        self.public = APIClient()

    def _pdf(self, name):
        return SimpleUploadedFile(name, b'%PDF-1.4 dummy', content_type='application/pdf')

    def _post(self, files, extra=None):
        data = {**self.BASE, 'files': files, **(extra or {})}
        return self.public.post(f'/api/v1/d/{self.ref}/', data, format='multipart')

    def test_two_pdfs_two_insurance_cards_one_lead(self):
        """스펙 TC1: 2장 → insurances 2건, 각자 트리 분리, 고객 1명, 동의 로그 정상."""
        ocr_a = _fake_ocr_product('A종합보험', '진단비', '암', '일반암')          # → 일반암진단비
        ocr_b = _fake_ocr_product('B수술보험', '수술', '암', '암수술비')          # → 암수술비
        with mock.patch('inpa.insurances.self_diagnosis.claude_parse',
                        side_effect=[ocr_a, ocr_b]) as m_parse, \
                mock.patch('inpa.insurances.self_diagnosis._extract_pdf_lines',
                           return_value=(['line'], None)):
            r = self._post([self._pdf('a.pdf'), self._pdf('b.pdf')])
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual(m_parse.call_count, 2)  # 파일 1장당 1회 파싱
        cards = body['insurances']
        self.assertEqual(len(cards), 2)
        self.assertEqual([c['status'] for c in cards], ['ok', 'ok'])
        self.assertEqual([c['name'] for c in cards], ['A종합보험', 'B수술보험'])
        self.assertEqual(cards[0]['company_label'], '삼성화재')
        self.assertEqual(cards[0]['monthly_premium'], 30000)
        self.assertEqual(cards[0]['coverage_count'], 1)
        # ★ 보험별 트리 분리 — 각 카드 트리는 자기 담보만 담는다.
        names_a = _tree_detail_names(cards[0]['tree'])
        names_b = _tree_detail_names(cards[1]['tree'])
        self.assertIn('일반암진단비', names_a)
        self.assertNotIn('암수술비', names_a)
        self.assertIn('암수술비', names_b)
        self.assertNotIn('일반암진단비', names_b)
        # 고객(리드) 1명 + 보험 2건 귀속 + 동의 로그(개인정보·국외이전) 정상
        lead = Customer.objects.get(owner=self.planner, lead_source='self_diagnosis')
        self.assertEqual(CustomerInsurance.objects.filter(customer=lead).count(), 2)
        self.assertIsNotNone(lead.consent_overseas_at)
        self.assertEqual(lead.consent_logs.filter(scope=ConsentLog.SCOPE_OVERSEAS_MEDICAL).count(), 1)
        self.assertEqual(lead.consent_logs.filter(scope=ConsentLog.SCOPE_PERSONAL_INFO).count(), 1)
        # 최상위 요약(하위호환) = 성공 보험 합산
        self.assertEqual(body['summary']['monthly_premiums'], 60000)
        self.assertTrue(body['analyzed'])
        self.assertNotIn('notice', body)

    def test_six_files_processes_five_with_notice(self):
        """스펙 TC2: 6장 업로드 → 5장만 처리 + notice 안내(초과분 파싱 0회)."""
        ocrs = [_fake_ocr_product(f'보험{i}') for i in range(5)]
        with mock.patch('inpa.insurances.self_diagnosis.claude_parse',
                        side_effect=ocrs) as m_parse, \
                mock.patch('inpa.insurances.self_diagnosis._extract_pdf_lines',
                           return_value=(['line'], None)):
            r = self._post([self._pdf(f'p{i}.pdf') for i in range(6)])
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual(len(body['insurances']), 5)
        self.assertEqual(m_parse.call_count, 5)  # 6번째 파일은 받지 않음
        self.assertIn('5장', body['notice'])

    def test_parse_failure_isolated_per_file(self):
        """스펙 TC3: 1장 실패 + 1장 성공 → status 혼합, 요청은 201 유지."""
        ocr_ok = _fake_ocr_product('성공보험')
        with mock.patch('inpa.insurances.self_diagnosis.claude_parse',
                        side_effect=[None, ocr_ok]), \
                mock.patch('inpa.insurances.self_diagnosis._extract_pdf_lines',
                           return_value=(['line'], None)):
            r = self._post([self._pdf('bad.pdf'), self._pdf('good.pdf')])
        self.assertEqual(r.status_code, 201, r.content)
        cards = r.json()['insurances']
        self.assertEqual([c['status'] for c in cards], ['failed', 'ok'])
        self.assertEqual(cards[0]['name'], 'bad')          # 파일명 폴백(.pdf 제거)
        self.assertTrue(cards[0]['message'])               # 긍정 안내 문구 존재
        self.assertEqual(cards[0]['tree'], [])
        lead = Customer.objects.get(owner=self.planner, lead_source='self_diagnosis')
        self.assertEqual(CustomerInsurance.objects.filter(customer=lead).count(), 1)

    def test_daily_cap_consumed_per_file(self):
        """스펙 TC4: 남은 캡 1일 때 3장 → 1장 ok + 2장 skipped(파싱 1회만)."""
        from django.core.cache import cache
        from inpa.insurances.self_diagnosis import (
            MSG_FILE_SKIPPED, SELF_DIAG_DAILY_CAP_PER_REF)
        key = f'selfdiag-attempts:{self.ref}:{timezone.now().date().isoformat()}'
        cache.set(key, SELF_DIAG_DAILY_CAP_PER_REF - 1, 60 * 60 * 24)
        with mock.patch('inpa.insurances.self_diagnosis.claude_parse',
                        side_effect=[_fake_ocr_product('마지막보험')]) as m_parse, \
                mock.patch('inpa.insurances.self_diagnosis._extract_pdf_lines',
                           return_value=(['line'], None)):
            r = self._post([self._pdf('p1.pdf'), self._pdf('p2.pdf'), self._pdf('p3.pdf')])
        self.assertEqual(r.status_code, 201, r.content)
        cards = r.json()['insurances']
        self.assertEqual([c['status'] for c in cards], ['ok', 'skipped', 'skipped'])
        self.assertEqual(cards[1]['message'], MSG_FILE_SKIPPED)
        self.assertEqual(m_parse.call_count, 1)  # Claude 호출은 캡 안에서 1회만

    def test_legacy_single_file_field_still_works(self):
        """스펙 TC5: 기존 단일 'file' 필드 하위호환 — insurances 1건 + 기존 응답 유지."""
        with mock.patch('inpa.insurances.self_diagnosis.claude_parse',
                        return_value=_fake_ocr_product('단일보험')), \
                mock.patch('inpa.insurances.self_diagnosis._extract_pdf_lines',
                           return_value=(['line'], None)):
            r = self.public.post(
                f'/api/v1/d/{self.ref}/',
                {**self.BASE, 'file': self._pdf('one.pdf')}, format='multipart')
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual(len(body['insurances']), 1)
        self.assertEqual(body['insurances'][0]['status'], 'ok')
        self.assertEqual(body['insurances'][0]['name'], '단일보험')
        # 기존(하위호환) 최상위 형태 유지
        self.assertIn('tree', body)
        self.assertIn('summary', body)
        self.assertTrue(body['analyzed'])


# ──────────────────────────────────────────────────────────────────────
# 정확도 다중검사(verify.py) — 네트워크 없이 핵심 로직만(JSON 파싱·키없음 격리)
# ──────────────────────────────────────────────────────────────────────
class VerifyUnitTests(TestCase):
    def test_parse_json_variants(self):
        from inpa.insurances.verify import _parse_json
        self.assertEqual(_parse_json('{"confidence":"high"}')["confidence"], "high")
        self.assertEqual(_parse_json('```json\n{"confidence":"low"}\n```')["confidence"], "low")
        self.assertEqual(_parse_json('설명...\n{"confidence":"medium","issues":[]}\n끝')["confidence"], "medium")
        self.assertIsNone(_parse_json("not json at all"))

    @override_settings(ANTHROPIC_API_KEY='', CLAUDE_API_KEY='')
    def test_verify_returns_none_without_key(self):
        from inpa.insurances.verify import verify_extraction
        # 키 없으면 ci 접근 전에 (None, None) 반환(파싱 결과 안 깨뜨림 — 격리 보장)
        result, usage = verify_extraction(["삼성생명 종합보험"], None)
        self.assertIsNone(result)
        self.assertIsNone(usage)

    @override_settings(ANTHROPIC_API_KEY='sk-ant-test', CLAUDE_API_KEY='sk-ant-test')
    def test_verify_returns_real_usage_on_success(self):
        """★ 프리런치 #17 회귀 — verify_extraction 이 msg.usage 를 실제로 반환(과거 폐기 버그)."""
        from unittest import mock

        import anthropic

        from inpa.insurances.verify import verify_extraction

        fake_block = mock.Mock()
        fake_block.text = '{"confidence":"high","issues":[],"missing":[],"note":"ok"}'
        fake_usage = mock.Mock(input_tokens=100, output_tokens=20,
                               cache_read_input_tokens=0, cache_creation_input_tokens=0)
        fake_msg = mock.Mock()
        fake_msg.content = [fake_block]
        fake_msg.usage = fake_usage
        fake_client = mock.Mock()
        fake_client.messages.create.return_value = fake_msg

        with mock.patch.object(anthropic, 'Anthropic', return_value=fake_client):
            result, usage = verify_extraction(["삼성생명 종합보험"], mock.Mock(case_list=mock.Mock(all=lambda: [])))

        self.assertIsNotNone(result)
        self.assertEqual(result['confidence'], 'high')
        self.assertIs(usage, fake_usage)
        self.assertEqual(usage.input_tokens, 100)


# ──────────────────────────────────────────────────────────────────────
# [P0] OCR→표준담보 다리(coverage_bridge) — 실데이터에서 히트맵 보유금액이 잡히는지
#   버그: _get_or_create_detail 이 analysis_detail M2M 를 안 이어 held 가 전부 0 였음.
#   파서 이름(일반암)과 표준 이름(일반암진단비)이 달라 명시 맵으로 잇는다.
# ──────────────────────────────────────────────────────────────────────
@override_settings(ANTHROPIC_API_KEY='sk-ant-test', OCR_VERIFY_ENABLED=False)
class BridgeLinkTests(TestCase):
    """파서 leaf → 표준 AnalysisDetail 연결 + 히트맵 held>0 + 멱등."""

    def setUp(self):
        from django.core.management import call_command
        # [표준] 담보 트리(seed_normalization) 적재 — 일반암진단비 행 포함.
        call_command('seed_normalization')
        self.user, self.client = _make_planner('bridge@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='브리지고객', birth_day='1985.03.10', gender=1)
        _grant_overseas(self.customer)

    def _upload(self):
        """_fake_ocr_data(진단비>암>일반암 5천만) → 실제 _persist_ocr 변환."""
        with mock.patch('inpa.insurances.views.claude_parse', return_value=_fake_ocr_data()), \
                mock.patch('inpa.insurances.views._extract_pdf_lines',
                           return_value=(['삼성화재 종합보험 일반암 5천만원'], None)):
            return self.client.post(
                _ocr_url(self.customer.id), {'file': _dummy_pdf()}, format='multipart')

    def _std_cancer_detail(self):
        """[표준] 트리의 '일반암진단비' AnalysisDetail (동명 충돌 방지 마커 한정)."""
        return AnalysisDetail.objects.get(
            name='일반암진단비', sub_category__category__name__startswith='[표준]')

    def test_persist_links_parser_leaf_to_standard_detail(self):
        """업로드 케이스의 InsuranceDetail 이 표준 '일반암진단비' 에 연결된다."""
        r = self._upload()
        self.assertEqual(r.status_code, 201, r.content)
        case = CustomerInsuranceDetail.objects.get()
        self.assertEqual(case.detail.name, '일반암')  # 파서 leaf 이름
        # ★ 다리: 파서 leaf(일반암) → 표준(일반암진단비) M2M 연결됨
        std = self._std_cancer_detail()
        self.assertIn(std.id, case.detail.analysis_detail.values_list('id', flat=True))

    def test_heatmap_shows_held_amount(self):
        """히트맵에서 일반암진단비 보유금액이 5천만으로 집계된다(이전엔 0 버그)."""
        self._upload()
        r = self.client.get(f'/api/v1/customers/{self.customer.id}/heatmap/')
        self.assertEqual(r.status_code, 200, r.content)
        std = self._std_cancer_detail()
        held = None
        for cat in r.json()['tree']:
            for sub in cat['sub_categories']:
                for det in sub['details']:
                    if det['detail_id'] == std.id:
                        held = det['held_amount']
        self.assertEqual(held, 50000000)

    def test_link_is_idempotent_on_reupload(self):
        """같은 증권 2회 업로드해도 표준 담보 연결은 1건(.add 멱등)."""
        self._upload()
        self._upload()
        std = self._std_cancer_detail()
        # 동일 InsuranceDetail(get_or_create) 의 M2M 에 표준 행은 중복 없이 1건
        links = [d for d in CustomerInsuranceDetail.objects.values_list(
            'detail__analysis_detail', flat=True) if d == std.id]
        self.assertEqual(len(set(links)), 1)
        self.assertEqual(
            self._std_cancer_detail().sub_category.details.filter(
                name='일반암진단비').count(), 1)

    def test_unmapped_leaf_links_nothing_gracefully(self):
        """맵에 없는 파서 leaf(재해상해)는 미연결 — 에러 없이 held=0."""
        from inpa.insurances.coverage_bridge import resolve_std_detail
        self.assertIsNone(resolve_std_detail('상해', '상해', '재해상해'))
        self.assertIsNone(resolve_std_detail('없는', '경로', '담보'))


def _fake_ocr_section(cat, sub, det, amount=30000000):
    """수술/처치 등 신규 섹션 mock Ocr_Data — 손해보험 + 지정 leaf 1건."""
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
    ocr.dict_detail_data[cat][sub][det].append(f'20:1:100:1:{amount}:10000')
    return ocr


# ──────────────────────────────────────────────────────────────────────
# [수술·처치 섹션] 파서 신규 섹션 → 표준담보 연결 + 히트맵 held + 정확도 가드 + UnmatchedLog
# ──────────────────────────────────────────────────────────────────────
@override_settings(ANTHROPIC_API_KEY='sk-ant-test', OCR_VERIFY_ENABLED=False)
class SurgeryTreatmentSectionTests(TestCase):
    def setUp(self):
        from django.core.management import call_command
        call_command('seed_normalization')  # [표준]수술비·처치 트리 적재(멱등)
        self.user, self.client = _make_planner('surgery@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='수술처치고객', birth_day='1985.03.10', gender=1)
        _grant_overseas(self.customer)

    def _upload(self, ocr):
        with mock.patch('inpa.insurances.views.claude_parse', return_value=ocr), \
                mock.patch('inpa.insurances.views._extract_pdf_lines',
                           return_value=(['삼성화재 종합보험 수술/처치 담보'], None)):
            return self.client.post(
                _ocr_url(self.customer.id), {'file': _dummy_pdf()}, format='multipart')

    def _std(self, name):
        return AnalysisDetail.objects.get(
            name=name, sub_category__category__name__startswith='[표준]')

    def _held(self, std_id):
        r = self.client.get(f'/api/v1/customers/{self.customer.id}/heatmap/')
        self.assertEqual(r.status_code, 200, r.content)
        for cat in r.json()['tree']:
            for sub in cat['sub_categories']:
                for det in sub['details']:
                    if det['detail_id'] == std_id:
                        return det
        return None

    def test_surgery_section_links_and_held(self):
        """TC1 수술: 암수술비 5천만 → 표준 '암수술비' 연결 + 히트맵 held>0."""
        r = self._upload(_fake_ocr_section('수술', '암', '암수술비', 50000000))
        self.assertEqual(r.status_code, 201, r.content)
        case = CustomerInsuranceDetail.objects.get()
        std = self._std('암수술비')
        self.assertIn(std.id, case.detail.analysis_detail.values_list('id', flat=True))
        self.assertEqual(self._held(std.id)['held_amount'], 50000000)

    def test_treatment_section_links_and_held(self):
        """TC2 처치: 항암약물치료 1천만 → 신규 표준 '항암약물치료비' 연결 + held>0."""
        r = self._upload(_fake_ocr_section('처치', '항암', '항암약물치료', 10000000))
        self.assertEqual(r.status_code, 201, r.content)
        std = self._std('항암약물치료비')
        self.assertEqual(self._held(std.id)['held_amount'], 10000000)

    def test_treatment_leaf_neutral_without_baseline(self):
        """TC6 graceful: 기준선 없으면 처치 leaf는 neutral(에러 無)."""
        self._upload(_fake_ocr_section('처치', '항암', '항암방사선치료', 10000000))
        std = self._std('항암방사선치료비')
        self.assertEqual(self._held(std.id)['status'], 'neutral')

    def test_accuracy_guard_blocks_diagnosis_in_surgery(self):
        """TC3 정확도 가드: 원문 '암진단비'가 수술 섹션으로 와도 미연결(백스톱).

        대조: 원문이 진짜 수술('암수술비')이면 정상 연결.
        """
        from inpa.core.ocr.claude_parser import _add_coverage
        ocr = Ocr_Data()
        # 원문=암진단비(순수 진단), 구조=수술 섹션 → 가드가 차단
        _add_coverage(ocr, {'category': '수술', 'subcategory': '암',
                            'detail_name': '암수술비', 'name': '암진단비',
                            'amount': 50000000}, 20, 100)
        self.assertEqual(ocr.dict_detail_data['수술']['암']['암수술비'], [])
        # 원문=암수술비(진짜 수술) → 정상 연결
        _add_coverage(ocr, {'category': '수술', 'subcategory': '암',
                            'detail_name': '암수술비', 'name': '암수술비',
                            'amount': 50000000}, 20, 100)
        self.assertEqual(len(ocr.dict_detail_data['수술']['암']['암수술비']), 1)

    def test_unmatched_logged_and_occurrence_increments(self):
        """TC4 UnmatchedLog: 미매칭 담보가 적재되고 재업로드 시 occurrence 누적."""
        from inpa.analysis.models import UnmatchedLog
        ocr = _fake_ocr_section('수술', '암', '암수술비', 50000000)
        ocr._unmatched_coverages = ['조혈모세포이식수술비', '암입원비']
        self._upload(ocr)
        # 회사코드=2(삼성화재 head['손해보험']), 2건 적재
        self.assertEqual(UnmatchedLog.objects.filter(company=2).count(), 2)
        log = UnmatchedLog.objects.get(raw_name='조혈모세포이식수술비')
        self.assertEqual(log.occurrence, 1)
        # 재업로드 → 같은 raw_name 은 occurrence++ (행 추가 X)
        ocr2 = _fake_ocr_section('수술', '암', '암수술비', 50000000)
        ocr2._unmatched_coverages = ['조혈모세포이식수술비']
        self._upload(ocr2)
        log.refresh_from_db()
        self.assertEqual(log.occurrence, 2)
        self.assertEqual(UnmatchedLog.objects.filter(company=2).count(), 2)


class SeedNormalizationIdempotencyTests(TestCase):
    """TC5 멱등: seed_normalization 2회 → [표준] 카테고리·처치 불변, IntegrityError 無."""

    def test_seed_twice_is_idempotent(self):
        from django.core.management import call_command
        call_command('seed_normalization')
        cat1 = AnalysisCategory.objects.filter(name__startswith='[표준]').count()
        det1 = AnalysisDetail.objects.filter(
            sub_category__category__name__startswith='[표준]').count()
        call_command('seed_normalization')  # 2회차 — IntegrityError 나면 여기서 실패
        cat2 = AnalysisCategory.objects.filter(name__startswith='[표준]').count()
        det2 = AnalysisDetail.objects.filter(
            sub_category__category__name__startswith='[표준]').count()
        self.assertEqual(cat1, cat2)
        self.assertEqual(det1, det2)
        # 처치·입원비 신규 카테고리는 정확히 1개씩
        self.assertEqual(
            AnalysisCategory.objects.filter(name='[표준]처치').count(), 1)
        self.assertEqual(
            AnalysisCategory.objects.filter(name='[표준]입원비').count(), 1)


# ──────────────────────────────────────────────────────────────────────
# [입원 섹션] 정액 입원(일당/비) 표면화 + 실손 매처 분리(음성토큰 가드) + 단위가드
#   ★ 핵심 회귀: 정액 입원이 실손 입원의료비로 오염되지 않고, 실손은 그대로 매칭되는지.
# ──────────────────────────────────────────────────────────────────────
@override_settings(ANTHROPIC_API_KEY='sk-ant-test', OCR_VERIFY_ENABLED=False)
class InpatientSectionTests(TestCase):
    def setUp(self):
        from django.core.management import call_command
        call_command('seed_normalization')  # [표준]입원일당(재사용) + [표준]입원비(신규)
        self.user, self.client = _make_planner('inpatient@test.com')
        self.customer = Customer.objects.create(
            owner=self.user, name='입원고객', birth_day='1985.03.10', gender=1)
        _grant_overseas(self.customer)

    def _upload(self, ocr):
        with mock.patch('inpa.insurances.views.claude_parse', return_value=ocr), \
                mock.patch('inpa.insurances.views._extract_pdf_lines',
                           return_value=(['삼성화재 종합보험 입원 담보'], None)):
            return self.client.post(
                _ocr_url(self.customer.id), {'file': _dummy_pdf()}, format='multipart')

    def _std(self, name):
        return AnalysisDetail.objects.get(
            name=name, sub_category__category__name__startswith='[표준]')

    def _held(self, std_id):
        r = self.client.get(f'/api/v1/customers/{self.customer.id}/heatmap/')
        self.assertEqual(r.status_code, 200, r.content)
        for cat in r.json()['tree']:
            for sub in cat['sub_categories']:
                for det in sub['details']:
                    if det['detail_id'] == std_id:
                        return det
        return None

    def test_inpatient_daily_links_and_held(self):
        """TC1 일당: 질병입원일당 5만원/일 → 표준 '질병입원일당' 연결 + held>0."""
        r = self._upload(_fake_ocr_section('입원', '질병', '질병입원일당', 50000))
        self.assertEqual(r.status_code, 201, r.content)
        std = self._std('질병입원일당')
        self.assertEqual(self._held(std.id)['held_amount'], 50000)

    def test_inpatient_lumpsum_links_and_held(self):
        """TC2 입원비: 암입원비 500만(총액) → 신규 표준 '암입원비' 연결 + held>0."""
        r = self._upload(_fake_ocr_section('입원', '암', '암입원비', 5000000))
        self.assertEqual(r.status_code, 201, r.content)
        std = self._std('암입원비')
        self.assertEqual(self._held(std.id)['held_amount'], 5000000)

    def test_cross_section_regression_no_silsohn_pollution(self):
        """TC3 ★교차섹션 회귀: 정액 입원은 실손 path로 안 가고, 실손 입원의료비는 그대로.

        키워드 매칭이 substring 이라 짧은 '질병입원'이 '질병입원일당'을 빨아들이던 버그를
        음성토큰 가드로 차단했는지 — 실제 함수/반환형으로 락(text-line 파이프라인).
        """
        from inpa.core.ocr.ocrparsing import _match_coverage
        # 정액 입원 → 실손 아님(None)
        self.assertIsNone(_match_coverage('질병입원일당'))
        self.assertIsNone(_match_coverage('상해입원일당'))
        self.assertIsNone(_match_coverage('질병입원비(1일이상)'))
        # ★ 실손 회귀 0: 진짜 실손 입원의료비는 여전히 실손으로 매칭
        self.assertEqual(_match_coverage('질병입원의료비'),
                         '실손 의료비->질병->질병 입원 의료비')
        self.assertEqual(_match_coverage('상해입원의료비'),
                         '실손 의료비->상해->상해 입원 의료비')

    def test_false_positive_brain_tumor_not_mapped_to_cerebral_hemorrhage(self):
        """회귀: 양성뇌종양/뇌종양은 뇌출혈진단 path에 매핑되지 않아야 한다.

        Fix: 뇌출혈 keyword list에서 '뇌종양'·'양성뇌종양' 별칭 제거.
        양성뇌종양은 뇌출혈과 다른 담보이므로 unmatched(None)가 보수적으로 올바름.
        """
        from inpa.core.ocr.ocrparsing import _match_coverage
        # 오탐 제거 확인 — 뇌출혈 path가 아니어야 함
        self.assertNotEqual(_match_coverage('양성뇌종양진단비'), '진단비->뇌->뇌출혈')
        self.assertNotEqual(_match_coverage('뇌종양진단비'), '진단비->뇌->뇌출혈')
        # unmatched(None) 이 정상이지만, 다른 경로로 매핑되는 것도 허용(향후 추가 대비)
        # 핵심 보장: 뇌출혈 path로는 절대 가면 안 됨
        # 대조: 진짜 뇌출혈은 여전히 뇌출혈 path
        self.assertEqual(_match_coverage('뇌출혈진단비'), '진단비->뇌->뇌출혈')
        self.assertEqual(_match_coverage('뇌출혈보장'), '진단비->뇌->뇌출혈')

    def test_false_positive_in_situ_cancer_routed_to_yusamam_not_general(self):
        """회귀: 상피내암(제자리암)은 일반암이 아닌 유사암(소액암) path에 매핑되어야 한다.

        Fix: 유사암 keyword list에 '상피내암'·'상피내' 추가.
        longest-first 매칭으로 '상피내암'(5자)이 '암진단'(3자)보다 먼저 잡혀 일반암 오탐 차단.
        """
        from inpa.core.ocr.ocrparsing import _match_coverage
        # 상피내암 → 유사암 (일반암 아님)
        self.assertEqual(_match_coverage('상피내암진단비'), '진단비->암->유사암')
        self.assertNotEqual(_match_coverage('상피내암진단비'), '진단비->암->일반암')
        # 제자리암(기존 키워드 유지 확인)
        self.assertEqual(_match_coverage('제자리암진단비'), '진단비->암->유사암')
        # 대조: 진짜 일반암은 여전히 일반암 path
        self.assertEqual(_match_coverage('일반암진단비'), '진단비->암->일반암')

    def test_round_marker_parens_stripped_before_match(self):
        """전처리 회귀: 갱신 회차 괄호 표기 '(1차)/(제2차)'는 매칭 전에 제거된다.

        담보 정체성과 무관한 회차 표기가 붙어도 동일 담보로 매칭되게 함(정규화 정확도, P6c).
        """
        from inpa.core.ocr.ocrparsing import _match_coverage
        self.assertEqual(_match_coverage('뇌출혈진단비(1차)'), '진단비->뇌->뇌출혈')
        self.assertEqual(_match_coverage('뇌출혈진단비(제2차)'), '진단비->뇌->뇌출혈')
        # 대조: 회차 표기 없는 원본도 동일 결과
        self.assertEqual(_match_coverage('뇌출혈진단비'), '진단비->뇌->뇌출혈')

    def test_variable_life_without_company_classified_as_life(self):
        """회귀: 회사명이 없는 변액·종신 상품은 'unknown'이 아닌 'life'로 분류(회사는 -1 유지).

        회사는 추측하지 않되(정직, idx=-1), 상품 유형이 명백히 생명보험이면 type='life'로
        잡아 보험료·계약일·담보가 생명보험 경로로 정상 파싱되게 함.
        """
        from inpa.core.ocr.ocrparsing import _detect_company
        idx, itype, name = _detect_company(['변액유니버셜종신', '월보험료 100,000원'])
        self.assertEqual(itype, 'life')
        self.assertEqual(idx, -1)   # 회사는 추측하지 않음(정직)
        self.assertEqual(name, '')
        # 대조: 생명보험 신호 없는 미상 텍스트는 여전히 unknown
        self.assertEqual(_detect_company(['그냥 알 수 없는 텍스트'])[1], 'unknown')

    def test_claude_pipeline_fixed_benefit_not_polluting_silsohn(self):
        """TC3b: Claude가 정액 입원을 실손으로 오라우팅해도 가드가 실손 적재를 차단."""
        from inpa.core.ocr.claude_parser import _add_coverage
        ocr = Ocr_Data()
        # Claude 오라우팅 시뮬: 원문 '질병입원일당'인데 실손 입원의료비로 분류
        _add_coverage(ocr, {'category': '실손 의료비', 'subcategory': '질병',
                            'detail_name': '질병 입원 의료비', 'name': '질병입원일당',
                            'amount': 50000}, 20, 100)
        self.assertEqual(ocr.dict_detail_data['실손 의료비']['질병']['질병 입원 의료비'], [])
        # 대조: 진짜 실손 입원의료비는 정상 적재
        _add_coverage(ocr, {'category': '실손 의료비', 'subcategory': '질병',
                            'detail_name': '질병 입원 의료비', 'name': '질병입원의료비',
                            'amount': 30000000}, 20, 100)
        self.assertEqual(len(ocr.dict_detail_data['실손 의료비']['질병']['질병 입원 의료비']), 1)

    def test_value_guard_redirects_lumpsum_from_daily(self):
        """TC4 단위가드: 일당 leaf에 100만 초과 금액 → 입원비 leaf로 전환."""
        from inpa.core.ocr.claude_parser import _add_coverage
        ocr = Ocr_Data()
        # 일당으로 분류됐지만 금액 500만(총액형 오분류) → 질병입원비로 전환
        _add_coverage(ocr, {'category': '입원', 'subcategory': '질병',
                            'detail_name': '질병입원일당', 'name': '질병입원비',
                            'amount': 5000000}, 20, 100)
        self.assertEqual(ocr.dict_detail_data['입원']['질병']['질병입원일당'], [])
        self.assertEqual(len(ocr.dict_detail_data['입원']['질병']['질병입원비']), 1)
        # 대조: 정상 일당(5만원/일)은 일당 그대로
        _add_coverage(ocr, {'category': '입원', 'subcategory': '상해',
                            'detail_name': '상해입원일당', 'name': '상해입원일당',
                            'amount': 50000}, 20, 100)
        self.assertEqual(len(ocr.dict_detail_data['입원']['상해']['상해입원일당']), 1)

    def test_diagnosis_leak_guard_blocks_in_inpatient(self):
        """TC5 진단누수가드: 원문 '암진단비'가 입원 섹션으로 와도 미연결."""
        from inpa.core.ocr.claude_parser import _add_coverage
        ocr = Ocr_Data()
        _add_coverage(ocr, {'category': '입원', 'subcategory': '암',
                            'detail_name': '암입원비', 'name': '암진단비',
                            'amount': 30000000}, 20, 100)
        self.assertEqual(ocr.dict_detail_data['입원']['암']['암입원비'], [])
        # 대조: 진짜 암입원비는 정상
        _add_coverage(ocr, {'category': '입원', 'subcategory': '암',
                            'detail_name': '암입원비', 'name': '암입원비',
                            'amount': 30000000}, 20, 100)
        self.assertEqual(len(ocr.dict_detail_data['입원']['암']['암입원비']), 1)

    def test_inpatient_leaf_neutral_without_baseline(self):
        """TC7 graceful: 기준선 없으면 입원비 leaf는 neutral(에러 無)."""
        self._upload(_fake_ocr_section('입원', '암', '암입원비', 5000000))
        std = self._std('암입원비')
        self.assertEqual(self._held(std.id)['status'], 'neutral')


class ManualInsuranceTests(TestCase):
    """수기 보험 등록(보유/제안) — 생성·목록·portfolio_type 검증·owner 격리.

    OCR 실패/이미지/키없음 폴백 + 갈아타기 제안(type=2) 입력 경로를 한 엔드포인트로 검증.
    """

    def setUp(self):
        self.user, self.client = _make_planner('manual-a@inpa.local')
        self.customer = Customer.objects.create(
            owner=self.user, name='김고객', mobile_phone_number='010-1111-2222')

    def _url(self, cpk=None):
        return f'/api/v1/customers/{cpk or self.customer.pk}/insurances/manual/'

    def test_create_held_and_list(self):
        payload = {'name': '삼성생명 무배당 종합보험', 'insurance_type': 1,
                   'portfolio_type': 1, 'monthly_premiums': 85000,
                   'contract_date': '2024-03-01', 'expiry_date': '2054-03-01'}
        r = self.client.post(self._url(), payload, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data['portfolio_type'], 1)
        ci = CustomerInsurance.objects.get(pk=r.data['id'])
        self.assertEqual(ci.customer_id, self.customer.pk)
        rl = self.client.get(self._url())
        self.assertEqual(rl.status_code, 200)
        results = rl.data.get('results', rl.data)
        self.assertEqual(len(results), 1)

    def test_proposal_type_allowed(self):
        r = self.client.post(self._url(), {'name': '제안상품', 'insurance_type': 2,
                                           'portfolio_type': 2, 'monthly_premiums': 50000},
                             format='json')
        self.assertEqual(r.status_code, 201, r.content)

    def test_template_type_rejected(self):
        r = self.client.post(self._url(), {'name': 'x', 'portfolio_type': 0}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_owner_isolation_404(self):
        _other, other_client = _make_planner('manual-b@inpa.local')
        r = other_client.post(self._url(), {'name': 'x', 'portfolio_type': 1}, format='json')
        self.assertEqual(r.status_code, 404)


# ──────────────────────────────────────────────────────────────────────
# 셀프진단 동의 기록 — personal_info(필수) + marketing(선택) ConsentLog
# ──────────────────────────────────────────────────────────────────────
@override_settings(ANTHROPIC_API_KEY='test-key')
class SelfDiagnosisConsentTests(TestCase):
    """셀프진단 리드 생성 시 personal_info 동의가 항상, marketing은 선택으로 기록되는지."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()  # ScopedRateThrottle 카운터 격리
        self.planner, _ = _make_planner('sdconsent@test.com')
        self.ref = self.planner.profile.ref_code
        self.anon = APIClient()

    def _pdf(self):
        return SimpleUploadedFile('p.pdf', b'%PDF-1.4 test', content_type='application/pdf')

    @mock.patch('inpa.insurances.self_diagnosis.claude_parse', return_value=_fake_ocr_data())
    @mock.patch('inpa.insurances.self_diagnosis._extract_pdf_lines', return_value=(['line'], None))
    def test_lead_gets_personal_info_consent(self, *_):
        from inpa.customers.models import ConsentLog, Customer
        r = self.anon.post(f'/api/v1/d/{self.ref}/', {
            'file': self._pdf(), 'consent_overseas': 'true', 'consent_share': 'true',
            'name': '셀프김', 'phone': '010-9999-0000', 'birth': '1990-01-01', 'gender': '1',
        }, format='multipart')
        self.assertEqual(r.status_code, 201, r.content)
        cust = Customer.objects.get(owner=self.planner, mobile_phone_number='01099990000')
        self.assertTrue(ConsentLog.objects.filter(
            customer=cust, scope=ConsentLog.SCOPE_PERSONAL_INFO,
            subject=ConsentLog.SUBJECT_CUSTOMER_SELF).exists())
        self.assertFalse(ConsentLog.objects.filter(
            customer=cust, scope=ConsentLog.SCOPE_MARKETING).exists())

    @mock.patch('inpa.insurances.self_diagnosis.claude_parse', return_value=_fake_ocr_data())
    @mock.patch('inpa.insurances.self_diagnosis._extract_pdf_lines', return_value=(['line'], None))
    def test_marketing_optional(self, *_):
        from inpa.customers.models import ConsentLog, Customer
        r = self.anon.post(f'/api/v1/d/{self.ref}/', {
            'file': self._pdf(), 'consent_overseas': 'true', 'consent_share': 'true',
            'consent_marketing': 'true', 'name': '마케팅김', 'phone': '010-8888-0000',
            'birth': '1988-08-08', 'gender': '2',
        }, format='multipart')
        self.assertEqual(r.status_code, 201, r.content)
        cust = Customer.objects.get(owner=self.planner, mobile_phone_number='01088880000')
        self.assertTrue(ConsentLog.objects.filter(
            customer=cust, scope=ConsentLog.SCOPE_MARKETING,
            subject=ConsentLog.SUBJECT_CUSTOMER_SELF).exists())
        self.assertTrue(ConsentLog.objects.filter(
            customer=cust, scope=ConsentLog.SCOPE_PERSONAL_INFO,
            subject=ConsentLog.SUBJECT_CUSTOMER_SELF).exists())


# ──────────────────────────────────────────────────────────────────────
# 담보별/보험별 요금 노출 — 갱신/비갱신 사실 직렬화
# ──────────────────────────────────────────────────────────────────────
class FeeSerializerTests(TestCase):
    """담보별/보험별 요금 노출 — 갱신/비갱신 사실 직렬화."""

    def setUp(self):
        self.user = User.objects.create_user(email='fee@test.com', password='inpaPass123!')
        Profile.objects.create(user=self.user, email_verified_at=timezone.now())
        self.customer = Customer.objects.create(owner=self.user, name='김보장')
        self.ci = CustomerInsurance.objects.create(
            customer=self.customer, name='무배당 갱신암보험', insurance_type=2, portfolio_type=1,
            monthly_premiums=30000, monthly_renewal_premium=20000, monthly_non_renewal_premium=10000,
            monthly_earned_premium=0, total_premiums=1000, total_renewal_premium=700,
            total_non_renewal_premium=300, total_earned_premium=0)
        # InsuranceDetail 생성: sub_category FK 필요
        cat = InsuranceCategory.objects.create(insurance_type=2, name='진단비')
        sub = InsuranceSubCategory.objects.create(insurance_type=2, category=cat, name='암')
        self.det = InsuranceDetail.objects.create(sub_category=sub, name='암진단비')
        self.case = CustomerInsuranceDetail.objects.create(
            insurance=self.ci, detail=self.det, premium=20000, payment_period_type=3,
            assurance_amount=50000000, total_renewal_premium=700, total_non_renewal_premium=0)

    def test_case_fee_fields_and_is_renewal(self):
        data = CaseFeeSerializer(self.case).data
        self.assertEqual(data['detail_name'], '암진단비')
        self.assertEqual(data['premium'], 20000)
        self.assertEqual(data['payment_period_type'], 3)
        self.assertTrue(data['is_renewal'])            # type==3 → 갱신
        self.assertEqual(data['assurance_amount'], 50000000)
        self.assertEqual(data['total_renewal_premium'], 700)
        self.assertEqual(data['total_non_renewal_premium'], 0)

        # Non-renewal case: payment_period_type=1 (비갱신)
        case2 = CustomerInsuranceDetail.objects.create(
            insurance=self.ci, detail=self.det, premium=15000, payment_period_type=1,
            assurance_amount=30000000, total_renewal_premium=0, total_non_renewal_premium=500)
        data2 = CaseFeeSerializer(case2).data
        self.assertFalse(data2['is_renewal'])         # type==1 → 비갱신
        self.assertEqual(data2['premium'], 15000)
        self.assertEqual(data2['total_renewal_premium'], 0)
        self.assertEqual(data2['total_non_renewal_premium'], 500)

    def test_insurance_fee_nests_case_fees(self):
        data = InsuranceFeeSerializer(self.ci).data
        self.assertEqual(data['monthly_renewal_premium'], 20000)
        self.assertEqual(data['monthly_non_renewal_premium'], 10000)
        self.assertEqual(len(data['case_fees']), 1)
        self.assertEqual(data['case_fees'][0]['detail_name'], '암진단비')

    def test_manual_insurance_has_empty_case_fees(self):
        manual = CustomerInsurance.objects.create(
            customer=self.customer, name='직접입력보험', insurance_type=1, portfolio_type=1,
            monthly_premiums=50000)
        data = InsuranceFeeSerializer(manual).data
        self.assertEqual(data['case_fees'], [])        # 담보 행 없음
        self.assertEqual(data['monthly_premiums'], 50000)

    def test_manual_serializer_exposes_renewal_fields(self):
        """수기 보험 시리얼라이저가 갱신/비갱신 필드를 읽기 노출하는가."""
        from inpa.insurances.serializers import CustomerInsuranceManualSerializer
        data = CustomerInsuranceManualSerializer(self.ci).data
        self.assertIn('monthly_renewal_premium', data)
        self.assertIn('monthly_non_renewal_premium', data)
        self.assertIn('payment_period_type', data)
        self.assertIn('monthly_earned_premium', data)


class CoverageExpansionRegressionTests(TestCase):
    """2026-07-02 확장: 특수수술·특수입원·표적항암 담보 매핑 회귀 테스트.

    검증 항목:
    1. _match_coverage: 새 키워드가 올바른 path 반환, 잘못된 path 미반환.
    2. seed_normalization: 새 표준 leaf 생성 + alias 0 skip 확인.
    3. coverage_bridge: resolve_std_detail이 표준 AnalysisDetail에 연결.
    4. 중환자실입원일당 vs 질병중환자실입원일당 충돌 없음.
    """

    def test_match_coverage_special_surgery_routes_correctly(self):
        """특수수술 키워드가 수술->특수->* 경로로 매핑되는가."""
        from inpa.core.ocr.ocrparsing import _match_coverage

        self.assertEqual(_match_coverage('골절수술비'), '수술->특수->골절수술비')
        self.assertEqual(_match_coverage('화상수술비'), '수술->특수->화상수술비')
        self.assertEqual(_match_coverage('조혈모세포이식수술비'), '수술->특수->조혈모세포이식수술비')
        self.assertEqual(_match_coverage('장기이식수술비'), '수술->특수->장기이식수술비')
        self.assertEqual(_match_coverage('각막이식수술비'), '수술->특수->각막이식수술비')
        self.assertEqual(_match_coverage('흉터복원수술비'), '수술->특수->흉터복원수술비')
        self.assertEqual(_match_coverage('인공관절수술비'), '수술->특수->인공관절수술비')
        self.assertEqual(_match_coverage('호흡기수술비'), '수술->특수->호흡기수술비')

    def test_match_coverage_special_surgery_not_under_diagnosis(self):
        """특수수술 키워드가 진단비->* 경로로 흘러가지 않는가."""
        from inpa.core.ocr.ocrparsing import _match_coverage

        path = _match_coverage('골절수술비')
        self.assertIsNotNone(path)
        self.assertFalse(path.startswith('진단비->'),
                         f'골절수술비가 진단비 경로로 잘못 라우팅됨: {path}')
        path2 = _match_coverage('조혈모세포이식수술비')
        self.assertFalse(path2.startswith('진단비->'),
                         f'조혈모세포이식수술비가 진단비 경로로 잘못 라우팅됨: {path2}')

    def test_match_coverage_special_inpatient_routes_correctly(self):
        """특수입원 키워드가 입원->특수->* 경로로 매핑되는가."""
        from inpa.core.ocr.ocrparsing import _match_coverage

        self.assertEqual(_match_coverage('중환자실입원일당'), '입원->특수->중환자실입원일당')
        self.assertEqual(_match_coverage('환경성질환입원일당'), '입원->특수->환경성질환입원일당')
        self.assertEqual(_match_coverage('14대질병입원일당'), '입원->특수->14대질병입원일당')
        self.assertEqual(_match_coverage('여성특정질병입원일당'), '입원->특수->여성특정질병입원일당')
        self.assertEqual(_match_coverage('희귀난치성질환입원일당'), '입원->특수->희귀난치성질환입원일당')

    def test_match_coverage_special_inpatient_not_under_silsohn(self):
        """특수입원 키워드가 실손 의료비 경로로 오염되지 않는가."""
        from inpa.core.ocr.ocrparsing import _match_coverage

        path = _match_coverage('중환자실입원일당')
        self.assertIsNotNone(path)
        self.assertFalse(path.startswith('실손 의료비->'),
                         f'중환자실입원일당이 실손 경로로 잘못 라우팅됨: {path}')

    def test_icu_daily_distinct_from_disease_icu_daily(self):
        """질병중환자실입원일당(기존 leaf)과 중환자실입원일당(신규 특수입원 leaf)이
        각자 올바른 별개 경로로 라우팅되는지 검증.

        수정 전 버그(2026-07-02): '중환자실입원일당'이 '질병중환자실입원일당'의
        substring이어서 _match_coverage('질병중환자실입원일당')가 generic 특수입원
        경로('입원->특수->중환자실입원일당')로 오흡수됐다.

        수정 후: COVERAGE_KEYWORDS에 '입원->질병->질병중환자실입원일당' 엔트리를 먼저
        배치하고 keyword='질병중환자실입원일당'(전체 이름)으로 등록해 first-path-wins로
        정확한 경로를 반환하도록 했다.
        """
        from inpa.core.ocr.ocrparsing import _match_coverage

        generic_path = _match_coverage('중환자실입원일당')
        disease_path = _match_coverage('질병중환자실입원일당')

        # 1) 질병 ICU는 질병 전용 경로로 라우팅돼야 함
        self.assertEqual(
            disease_path,
            '입원->질병->질병중환자실입원일당',
            f'질병중환자실입원일당이 잘못된 경로로 라우팅됨: {disease_path}',
        )

        # 2) 일반(특수) ICU는 특수입원 경로로 라우팅돼야 함
        self.assertEqual(
            generic_path,
            '입원->특수->중환자실입원일당',
            f'중환자실입원일당이 잘못된 경로로 라우팅됨: {generic_path}',
        )

        # 3) 두 경로는 반드시 달라야 함
        self.assertNotEqual(
            disease_path,
            generic_path,
            '질병 ICU와 일반 ICU가 동일 경로로 흡수됨 — 충돌 미해결',
        )

    def test_match_coverage_targeted_chemo_routes_correctly(self):
        """표적항암 키워드가 처치->표적항암->* 경로로 매핑되는가."""
        from inpa.core.ocr.ocrparsing import _match_coverage

        self.assertEqual(_match_coverage('표적항암약물치료비'),
                         '처치->표적항암->표적항암약물치료')
        self.assertEqual(_match_coverage('표적항암방사선치료비'),
                         '처치->표적항암->표적항암방사선치료')

    def test_seed_normalization_creates_new_leaves_no_skip(self):
        """seed_normalization이 새 특수수술·특수입원·표적항암 leaf를 생성하고 skip=0인가."""
        from django.core.management import call_command
        from io import StringIO
        from inpa.analysis.models import AnalysisDetail

        out = StringIO()
        call_command('seed_normalization', stdout=out)
        output = out.getvalue()

        # skip=0 확인
        self.assertIn('skip=0', output)

        # 새 leaf 존재 확인 (STANDARD_TREE에서 생성됨)
        new_leaves = [
            '골절수술비', '화상수술비', '조혈모세포이식수술비', '장기이식수술비',
            '각막이식수술비', '흉터복원수술비', '인공관절수술비', '호흡기수술비',
            '중환자실입원일당', '환경성질환입원일당', '14대질병입원일당',
            '여성특정질병입원일당', '희귀난치성질환입원일당',
            '표적항암약물치료비', '표적항암방사선치료비',
        ]
        for leaf in new_leaves:
            exists = AnalysisDetail.objects.filter(
                name=leaf,
                sub_category__category__name__startswith='[표준]',
            ).exists()
            self.assertTrue(exists, f'표준 leaf 미생성: {leaf}')

    def test_bridge_resolve_new_special_leaves(self):
        """coverage_bridge가 새 특수 담보를 표준 AnalysisDetail에 연결하는가."""
        from django.core.management import call_command
        from inpa.insurances.coverage_bridge import resolve_std_detail

        call_command('seed_normalization')

        # 특수수술
        det = resolve_std_detail('수술', '특수', '골절수술비')
        self.assertIsNotNone(det)
        self.assertEqual(det.name, '골절수술비')

        det2 = resolve_std_detail('수술', '특수', '조혈모세포이식수술비')
        self.assertIsNotNone(det2)
        self.assertEqual(det2.name, '조혈모세포이식수술비')

        # 특수입원
        det3 = resolve_std_detail('입원', '특수', '중환자실입원일당')
        self.assertIsNotNone(det3)
        self.assertEqual(det3.name, '중환자실입원일당')

        # 표적항암
        det4 = resolve_std_detail('처치', '표적항암', '표적항암약물치료')
        self.assertIsNotNone(det4)
        self.assertEqual(det4.name, '표적항암약물치료비')

        det5 = resolve_std_detail('처치', '표적항암', '표적항암방사선치료')
        self.assertIsNotNone(det5)
        self.assertEqual(det5.name, '표적항암방사선치료비')
