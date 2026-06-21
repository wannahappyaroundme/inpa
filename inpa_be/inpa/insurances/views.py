"""보험 OCR 업로드 ViewSet — 증권 PDF → Claude 파싱 → 정규화 → 포트폴리오 생성.

엔드포인트:
  POST /api/v1/customers/<customer_pk>/insurances/ocr/
    멀티파트(file=PDF) 업로드. 해당 고객(★ owner 격리)의 보험증권을 Claude API 로
    파싱하고, 보험사별 담보명을 표준 담보로 정규화한 뒤 CustomerInsurance +
    CustomerInsuranceDetail 을 생성한다.

★ 준법 물리 게이트 (CLAUDE.md 개발 착수 게이트 2, dev/12 §0 원칙 2):
  - 부모 Customer.consent_overseas_at(병력 국외이전 동의) 이 없으면
    Claude API 호출 **이전에** 412 CONSENT_OVERSEAS_REQUIRED 로 물리 차단.
    증권 OCR 은 Claude(미국 소재) 로 개인 보험정보를 국외이전하므로 동의가 선결.
    UI 숨김은 방어가 아니다 — 서버에서 막는다.

가시성 (dev/02 §0):
  - CustomerInsurance / CustomerInsuranceDetail → 소유자 전용 (customer__owner 경유).
    부모 Customer 를 owner 스코프 쿼리로 잡아 격리(없으면 404 = 존재 은폐).

벤더링 연결 (dev/03 포팅지도):
  - inpa.core.ocr.claude_parser.claude_parse 로 Claude 파싱.
  - _add_coverage 매칭 단계에 NormalizationDict 사전 룩업 콜백(normalizer) 을 주입 →
    보험사별 담보 원문명을 표준 담보(AnalysisDetail) 로 고정(데이터 복리 해자).
  - ANTHROPIC_API_KEY 는 settings(env) 에서만 — 하드코딩 금지.
"""
from django.conf import settings
from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from inpa.analysis.models import (
    AnalysisCategory, AnalysisDetail, AnalysisSubCategory, NormalizationDict,
)
from inpa.billing.credit import LimitExceeded, check_and_consume, log_claude_usage
from inpa.core.ocr.claude_parser import claude_parse
from inpa.core.permissions import IsEmailVerified
from inpa.customers.models import Customer

from .models import (
    CustomerInsurance, CustomerInsuranceDetail, InsuranceCategory,
    InsuranceDetail, InsuranceSubCategory,
)
from .serializers import CustomerInsuranceSerializerForDetail

# 최대 업로드 크기 (foliio 동일 정책)
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def _credit_exhausted_response(exc: LimitExceeded, user) -> Response:
    """LimitExceeded → 402 Payment Required (dev/02 §16 shape).

    FE는 402 + code='credit_exhausted' 수신 시 UpgradeGuideModal 표시.
    기능 자체를 차단하는 UI 는 사용하지 않는다(정직성 레드라인).
    """
    from inpa.billing.models import Subscription
    sub = Subscription.objects.select_related('plan').filter(user=user).first()
    membership = sub.plan.code if sub else 'free'
    return Response(
        {
            'detail': f'이번 달 한도({exc.limit}건)를 모두 사용했어요.',
            'code': 'credit_exhausted',
            'kind': exc.action,
            'membership': membership,
            'limit': exc.limit,
            'used': exc.current,
        },
        status=status.HTTP_402_PAYMENT_REQUIRED,
    )

# CustomerInsurance.insurance_type (1=생명/2=손해) ↔ Ocr_Data head dict 키
_LIFE_TYPE = 1
_LOSS_TYPE = 2


def _build_normalizer():
    """NormalizationDict 사전 → claude_parser._add_coverage 훅 콜백 생성 (dev/02 §5.2).

    반환 콜백: (original_name, company_idx) -> (cat_name, sub_name, det_name) | None.
      - 관리자 검수(source=admin_verified) 사전만 신뢰 — 자동매핑 오류 = 비교안내서 거짓
        = §97 위반 리스크이므로 보수적 기본값(검수본만 베타 매칭).
      - 매칭 성공 시 hit_count++ (데이터 복리 계측).
      - 표준 담보(AnalysisDetail) → (category, sub_category, detail) 이름 경로로 변환해
        foliio Ocr_Data.dict_detail_data 경로와 호환시킨다.
    매칭이 없으면 None → claude_parser 가 원본 매칭(_CATEGORY_MAP→키워드→fuzzy) 으로 폴백.
    """
    def normalizer(original_name, company_idx):
        if not original_name or company_idx is None or company_idx < 0:
            return None
        raw = original_name.replace(' ', '')
        entry = (
            NormalizationDict.objects
            .filter(company=company_idx, source=NormalizationDict.SOURCE_ADMIN_VERIFIED)
            .select_related('std_detail__sub_category__category')
            .filter(raw_name__in=[original_name, raw])
            .first()
        )
        if entry is None:
            return None
        det = entry.std_detail
        sub = det.sub_category
        cat = sub.category
        # hit_count++ (원자적 증가, 동시성 안전)
        NormalizationDict.objects.filter(pk=entry.pk).update(hit_count=entry.hit_count + 1)
        return (cat.name, sub.name, det.name)

    return normalizer


def _extract_pdf_lines(uploaded_file):
    """업로드 PDF 에서 텍스트 줄 리스트 추출. 전자(텍스트) PDF 만 지원.

    Returns:
        (lines, error_code) — 성공 시 (list[str], None). 실패 시 ([], 'IMAGE_PDF'|'PROCESSING_ERROR').
    """
    try:
        import pdfplumber
    except ImportError:
        return [], 'PROCESSING_ERROR'
    lines = []
    try:
        uploaded_file.seek(0)
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ''
                for ln in text.splitlines():
                    ln = ln.strip()
                    if ln:
                        lines.append(ln)
    except Exception as e:  # 손상/암호 PDF 등
        print(f'[ocr-upload] pdf extract error: {e}')
        return [], 'PROCESSING_ERROR'
    if not lines:
        # 텍스트 0줄 = 스캔/이미지 PDF → 거부 (Claude 호출 의미 없음)
        return [], 'IMAGE_PDF'
    return lines, None


def _get_or_create_detail(cat_name, sub_name, det_name, insurance_type):
    """표준 담보 경로(cat/sub/det) → InsuranceDetail(카탈로그) 1건 보장.

    CustomerInsuranceDetail.detail 은 InsuranceDetail FK(필수) 이므로, OCR 이 잡은
    표준 경로에 대응하는 카탈로그 행을 get_or_create 로 확보한다(시드가 비어 있어도 안전).
    """
    cat, _ = InsuranceCategory.objects.get_or_create(
        name=cat_name, defaults={'insurance_type': insurance_type})
    sub, _ = InsuranceSubCategory.objects.get_or_create(
        category=cat, name=sub_name, defaults={'insurance_type': insurance_type})
    det, _ = InsuranceDetail.objects.get_or_create(sub_category=sub, name=det_name)
    return det


def _parse_value(value):
    """Ocr_Data.dict_detail_data 값 문자열 파싱.

    형식: "납입기간:납입타입:보장기간:보장타입[:갱신N]:금액:보험료"
    Returns dict(payment_period, payment_period_type, warranty_period,
                 warranty_period_type, is_renewal, renewal_period, amount, premium)
    또는 None(형식 불량).
    """
    parts = value.split(':')
    if len(parts) < 6:
        return None
    renewal_period = 0
    is_renewal = False
    # 갱신 토큰 탐색 ("갱신N")
    renewal_tokens = [p for p in parts if p.startswith('갱신')]
    if renewal_tokens:
        is_renewal = True
        try:
            renewal_period = int(renewal_tokens[0][len('갱신'):] or '1')
        except ValueError:
            renewal_period = 1
    try:
        amount = int(parts[-2])
        premium = int(parts[-1])
        payment_period = int(parts[0])
        payment_period_type = int(parts[1])
        warranty_period = int(parts[2])
        warranty_period_type = int(parts[3])
    except (ValueError, IndexError):
        return None
    return {
        'payment_period': payment_period,
        'payment_period_type': payment_period_type,
        'warranty_period': warranty_period,
        'warranty_period_type': warranty_period_type,
        'is_renewal': is_renewal,
        'renewal_period': renewal_period,
        'amount': amount,
        'premium': premium,
    }


def _persist_ocr(customer, ocr_data):
    """Ocr_Data → CustomerInsurance + CustomerInsuranceDetail 생성 후 계산 엔진 실행.

    8케이스 보험료 엔진(set_renewal_month / calculate)은 foliio 무변경 호출만 한다.
    """
    # ── 1) head dict 선택 (생명/손해) ──
    life_head = ocr_data.dict_life_head_data
    loss_head = ocr_data.dict_loss_head_data
    if life_head.get('생명보험', -1) > -1:
        head, insurance_type = life_head, _LIFE_TYPE
    elif loss_head.get('손해보험', -1) > -1:
        head, insurance_type = loss_head, _LOSS_TYPE
    else:
        # 보험사 미감지 — 손해보험 dict 를 디폴트로(담보 데이터가 거기 누적됨)
        head, insurance_type = loss_head, _LOSS_TYPE

    contractor = head.get('계약자', '') or None
    insured = head.get('피보험자', '') or None

    # ── 2) CustomerInsurance(보유=portfolio_type 1) 생성 ──
    ci = CustomerInsurance.objects.create(
        customer=customer,
        insurance_type=insurance_type,
        portfolio_type=1,  # 보유(기존가입) — 갈아타기 비교 좌측
        name=head.get('상품명', '') or None,
        contractor_name=contractor,
        insured_name=insured,
        is_same_insured=ocr_data.is_same_insured,
        payment_period=head.get('납입기간') or None,
        warranty_period=head.get('보장기간') or None,
        contract_date=head.get('계약일', '') or None,
        expiry_date=(loss_head.get('만기일', '') or None) if insurance_type == _LOSS_TYPE else None,
        monthly_premiums=head.get('월납입보험료') or None,
        monthly_assurance_premium=head.get('월보장보험료') or None,
        monthly_renewal_premium=head.get('월갱신보험료') or None,
        monthly_earned_premium=head.get('월적립보험료') or None,
        monthly_contract_premium=head.get('월주계약보험료') or None,
        monthly_special_premium=head.get('월특약보험료') or None,
        cancellation_refund=head.get('해약환급금') or None,
        renewal_growth_rate=head.get('갱신증가율') or None,
        payment_period_type=head.get('payment_period_type', 1),
        warranty_period_type=head.get('warranty_period_type', 1),
    )

    # ── 3) 담보 케이스(dict_detail_data) → CustomerInsuranceDetail ──
    created_cases = 0
    for cat_name, subs in ocr_data.dict_detail_data.items():
        for sub_name, dets in subs.items():
            for det_name, value_list in dets.items():
                for value in value_list:
                    parsed = _parse_value(value)
                    if not parsed or parsed['amount'] <= 0:
                        continue
                    detail = _get_or_create_detail(
                        cat_name, sub_name, det_name, insurance_type)
                    # payment_period_type: 갱신형이면 3(년갱신), 아니면 OCR 타입(1년/2세)
                    pp_type = 3 if parsed['is_renewal'] else parsed['payment_period_type']
                    CustomerInsuranceDetail.objects.create(
                        insurance=ci,
                        detail=detail,
                        assurance_amount=parsed['amount'],
                        premium=parsed['premium'] or None,
                        payment_period=parsed['payment_period'] or None,
                        payment_period_type=pp_type,
                        warranty_period=str(parsed['warranty_period']) if parsed['warranty_period'] else None,
                        warranty_period_type=parsed['warranty_period_type'],
                    )
                    created_cases += 1

    # ── 4) 8케이스 보험료 엔진 (foliio 무변경) ──
    ci.set_renewal_month()  # save() 포함
    for case in ci.case_list.all():
        case.calculate(ci)
        case.save()
    ci.calculate()
    ci.save()

    return ci, created_cases


class InsuranceOcrViewSet(viewsets.ViewSet):
    """증권 OCR 업로드 — 소유자 격리 + 국외이전 동의 물리 게이트.

    POST /api/v1/customers/<customer_pk>/insurances/ocr/   (multipart: file=PDF)
    """
    permission_classes = [IsAuthenticated, IsEmailVerified]
    parser_classes = [MultiPartParser, FormParser]
    parent_lookup = 'customer_pk'

    def _is_admin(self):
        profile = getattr(self.request.user, 'profile', None)
        return bool(getattr(profile, 'is_admin', False))

    def get_customer(self):
        qs = Customer.objects.all()
        if not self._is_admin():
            qs = qs.filter(owner=self.request.user)
        try:
            return qs.get(pk=self.kwargs[self.parent_lookup])
        except Customer.DoesNotExist:
            raise NotFound('고객을 찾을 수 없습니다.')

    def create(self, request, *args, **kwargs):
        # ── 0) owner 격리 (없으면 404 — 존재 은폐) ──
        customer = self.get_customer()

        # ── 1) ★ 국외이전 동의 물리 게이트 (Claude 호출 이전에 차단) ──
        if customer.consent_overseas_at is None:
            return Response(
                {'code': 'CONSENT_OVERSEAS_REQUIRED',
                 'detail': '증권 OCR 분석 전 고객의 병력·보험정보 국외이전(Claude API, 미국) '
                           '동의가 필요합니다.'},
                status=status.HTTP_412_PRECONDITION_FAILED)

        # ── 2) 파일 검증 ──
        upload = request.FILES.get('file')
        if upload is None:
            return Response({'code': 'FILE_REQUIRED', 'detail': 'file(PDF) 업로드가 필요합니다.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if upload.size > _MAX_UPLOAD_BYTES:
            return Response({'code': 'FILE_TOO_LARGE', 'detail': '50MB 이하의 PDF만 업로드 가능합니다.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if not upload.name.lower().endswith('.pdf'):
            return Response({'code': 'IMAGE_PDF', 'detail': '전자 PDF 형식 파일로 부탁드립니다.'},
                            status=status.HTTP_400_BAD_REQUEST)

        # ── 3) PDF 텍스트 추출 ──
        lines, extract_err = _extract_pdf_lines(upload)
        if extract_err == 'IMAGE_PDF':
            return Response(
                {'code': 'IMAGE_PDF',
                 'detail': '전자 PDF 형식 파일로 부탁드립니다. (스캔/이미지 PDF는 지원하지 않습니다)'},
                status=status.HTTP_400_BAD_REQUEST)
        if extract_err:
            return Response({'code': 'PROCESSING_ERROR', 'detail': '문서 처리 중 오류가 발생했습니다.'},
                            status=status.HTTP_400_BAD_REQUEST)

        # ── 4) API 키 확인 (하드코딩 금지 — settings/env) ──
        if not getattr(settings, 'ANTHROPIC_API_KEY', ''):
            return Response(
                {'code': 'OCR_UNAVAILABLE', 'detail': 'OCR 분석이 현재 비활성화되어 있습니다.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE)

        # ── 5) 크레딧 차감 (kind='ocr') — Claude 호출 직전. 한도 초과 시 402 ──
        #    검증(동의·파일)을 모두 통과한 뒤 차감해, 입력 오류가 크레딧을 소모하지 않게 한다.
        #    베타 FREE_TIER_UNLIMITED=True 면 통과(무차감).
        try:
            check_and_consume(request.user, 'ocr')
        except LimitExceeded as exc:
            return _credit_exhausted_response(exc, request.user)

        # ── 6) Claude 파싱 (정규화 훅 주입) ──
        ocr_data = claude_parse(lines, normalizer=_build_normalizer())
        if ocr_data is None:
            return Response(
                {'code': 'PARSE_FAILED',
                 'detail': '증권을 인식하지 못했습니다. 직접 입력해 주세요.'},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        # ── 6.1) Claude usage → ClaudeApiLog (관리자 비용 로깅) ──
        log_claude_usage(
            action='ocr_parse',
            model=getattr(ocr_data, '_claude_model', ''),
            usage=getattr(ocr_data, '_claude_usage', None),
        )

        # ── 7) 포트폴리오 + 담보 생성 (트랜잭션) + 계산 엔진 ──
        with transaction.atomic():
            ci, created_cases = _persist_ocr(customer, ocr_data)

        # ── 7.1) 정확도 다중검사 — Claude 교차검증(원문↔파싱). 실패는 격리. ──
        if getattr(settings, 'OCR_VERIFY_ENABLED', False):
            from inpa.insurances.verify import verify_extraction
            verification = verify_extraction(lines, ci)
            if verification is not None:
                ci.verification = verification
                ci.save(update_fields=['verification', 'updated_at'])
                log_claude_usage('ocr_verify', getattr(settings, 'CLAUDE_MODEL_PARSE', ''), None)

        data = CustomerInsuranceSerializerForDetail(ci).data
        return Response(
            {'code': 'OK',
             'parsing_method': getattr(ocr_data, 'parsing_method', 'claude'),
             'created_cases': created_cases,
             'verification': getattr(ci, 'verification', None),
             'insurance': data},
            status=status.HTTP_201_CREATED)
