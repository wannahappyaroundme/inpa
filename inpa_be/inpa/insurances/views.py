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
import logging

from django.conf import settings
from django.db import transaction
from django.db.models import F
from rest_framework import status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.response import Response

from inpa.analysis.models import (
    AnalysisCategory, AnalysisDetail, AnalysisSubCategory, NormalizationDict,
    UnmatchedLog,
)
from inpa.analytics.events import log_event
from inpa.analytics.models import NorthStarEvent
from inpa.billing.credit import LimitExceeded, check_and_consume, log_claude_usage
from inpa.core.ocr.claude_parser import claude_parse
from inpa.core.permissions import IsEmailVerified
from inpa.customers.consent_texts import has_current_overseas_consent
from inpa.customers.models import Customer

from .coverage_bridge import resolve_std_detail
from .models import (
    CustomerInsurance, CustomerInsuranceDetail, InsuranceCategory,
    InsuranceDetail, InsuranceSubCategory,
)
from .serializers import (
    CustomerInsuranceManualSerializer, CustomerInsuranceSerializerForDetail,
)

# ★ PII 로그 레드라인(LB#9): 업로드 파일 내용·추출 텍스트를 절대 로그에 찍지 않는다.
logger = logging.getLogger(__name__)

# 최대 업로드 크기 (foliio 동일 정책)
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024

# Claude 가 결과를 만들지 못한 '전송 계층' 실패 outcome — 방금 차감한 크레딧을 되돌린다.
# empty / json_invalid 는 Claude 가 출력을 만든(=비용 발생) 것이므로 되돌리지 않는다.
_TRANSPORT_FAILURE_OUTCOMES = frozenset({'no_key', 'package_missing', 'timeout', 'api_error'})


def _refund_ocr_credit(user):
    """전송 계층 실패로 결과를 못 만들었을 때, check_and_consume 로 방금 올린 ocr 카운터 1건을 되돌린다.

    - 베타(FREE_TIER_UNLIMITED=True)면 UsageMeter 행 자체가 없어 0건 갱신 = 무해한 no-op.
    - count>0 행만 -1 (PositiveIntegerField 음수 방지).
    - 되돌리기 실패가 사용자 응답을 막지 않도록 예외 격리(계측·정산은 부가 처리).
    """
    try:
        from inpa.billing.models import UsageMeter
        UsageMeter.objects.filter(
            user=user, action='ocr', year_month=UsageMeter.current_month(),
            count__gt=0,
        ).update(count=F('count') - 1)
    except Exception as exc:  # 되돌리기 실패는 삼킨다 — 본 응답을 깨뜨리지 않는다.
        logger.warning('[ocr-upload] credit refund failed: %s', type(exc).__name__)


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
        # 예외 타입·메시지만 — 파일 내용/추출 텍스트는 로그 금지 (PII 로그 레드라인).
        logger.warning('[ocr-upload] pdf extract error: %s: %s', type(e).__name__, e)
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
    # [P0] 표준 담보(AnalysisDetail) 다리 연결 — 히트맵/계산이 보유금액을 집계하려면
    # detail.analysis_detail M2M 가 있어야 한다(없으면 held=0). 파서 이름↔표준 이름이
    # 달라 명시 맵(coverage_bridge)으로 잇는다. 미대응이면 std=None → 미연결(graceful).
    # ★ 연결이 하나도 없을 때만 잇는다(repair_analysis_links 와 동일 후보 규칙) —
    #   어드민 정정(set([new_leaf]), 담보 사전 피드백)이 다음 업로드에서 옛 leaf 재추가로
    #   되돌려지거나 이중 연결(히트맵 이중 집계)되는 것을 방지. 무연결 신규/기존 행은
    #   기존처럼 브리지로 연결(멱등: 이미 같은 std 에 연결된 행은 exists 로 스킵).
    std = resolve_std_detail(cat_name, sub_name, det_name)
    if std is not None and not det.analysis_detail.exists():
        det.analysis_detail.add(std)
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


def _persist_ocr(customer, ocr_data, portfolio_type=1):
    """Ocr_Data → CustomerInsurance + CustomerInsuranceDetail 생성 후 계산 엔진 실행.

    portfolio_type: 1=보유(증권 업로드, 갈아타기 비교 좌측) / 2=제안(가입제안서 업로드, 우측).
    8케이스 보험료 엔진(set_renewal_month / calculate)은 foliio 무변경 호출만 한다.
    """
    # ── 1) head dict 선택 (생명/손해) ──
    life_head = ocr_data.dict_life_head_data
    loss_head = ocr_data.dict_loss_head_data
    if life_head.get('생명보험', -1) > -1:
        head, insurance_type = life_head, _LIFE_TYPE
        # ★ 사전 코드 공간 규약(seed_normalization 보험사 코드): 손해 = raw index,
        #   생명 = 200 + LifeInsurance index (예: 삼성생명=206). head dict 는 raw index
        #   유지(ocrdata 소비자 불변) — 사전/로그 공간으로 나갈 때만 오프셋 적용.
        company_code = 200 + life_head.get('생명보험', -1)
    elif loss_head.get('손해보험', -1) > -1:
        head, insurance_type = loss_head, _LOSS_TYPE
        company_code = loss_head.get('손해보험', -1)
    else:
        # 보험사 미감지 — 손해보험 dict 를 디폴트로(담보 데이터가 거기 누적됨)
        head, insurance_type = loss_head, _LOSS_TYPE
        company_code = -1

    contractor = head.get('계약자', '') or None
    insured = head.get('피보험자', '') or None

    # ── 2) CustomerInsurance(보유=portfolio_type 1) 생성 ──
    ci = CustomerInsurance.objects.create(
        customer=customer,
        insurance_type=insurance_type,
        portfolio_type=portfolio_type,  # 1=보유(좌측) / 2=제안(갈아타기 우측)
        # ✦ 담보 사전 피드백: 감지된 보험사 코드 보존(-1=미감지). 오매핑 신고 시
        #   NormalizationDict(company, raw_name) 별칭 등록의 company 원천.
        company=company_code,
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
    # ✦ 담보 사전 피드백: claude_parser._add_coverage 가 실은 케이스별 원문명 병렬 맵.
    #   키 = (cat, sub, det, value). 레거시/직접 입력 경로에는 맵이 없어 빈 값.
    raw_name_map = getattr(ocr_data, '_raw_name_by_case', None) or {}
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
                    raw_name = (raw_name_map.get(
                        (cat_name, sub_name, det_name, value)) or '')[:200]
                    CustomerInsuranceDetail.objects.create(
                        insurance=ci,
                        detail=detail,
                        raw_name=raw_name,
                        assurance_amount=parsed['amount'],
                        premium=parsed['premium'] or None,
                        payment_period=parsed['payment_period'] or None,
                        payment_period_type=pp_type,
                        warranty_period=str(parsed['warranty_period']) if parsed['warranty_period'] else None,
                        warranty_period_type=parsed['warranty_period_type'],
                    )
                    created_cases += 1

    # ── 3.5) 미매칭 담보 → UnmatchedLog 적재 (학습 플라이휠, dev/02 §5.3) ──
    # 표준에 없어 버려진 담보를 기록 → admin 검수 → NormalizationDict(admin_verified)
    # 승격 → 다음 OCR 자동매칭(데이터 복리). 없으면 컷 담보가 흔적 없이 소실.
    for raw in getattr(ocr_data, '_unmatched_coverages', []) or []:
        raw_name = (raw or '').strip()[:120]
        if not raw_name:
            continue
        log, created = UnmatchedLog.objects.get_or_create(
            company=company_code, raw_name=raw_name)
        if not created:
            # 재등장 → 발생 횟수 누적(F 표현식, 경쟁조건 안전)
            UnmatchedLog.objects.filter(pk=log.pk).update(occurrence=F('occurrence') + 1)

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
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'ocr'  # Claude Opus 비용폭탄 방어 — 유저별 시간당 상한
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
        #    현재 문구 버전으로 받은 고객 본인 동의만 게이트를 연다(구버전=재동의 필요).
        if not has_current_overseas_consent(customer):
            reason = 'reconsent' if customer.consent_overseas_at is not None else 'missing'
            return Response(
                {'code': 'CONSENT_OVERSEAS_REQUIRED', 'reason': reason,
                 'detail': '증권 OCR 분석 전 고객의 병력·보험정보 국외이전(Claude API, 미국) '
                           '동의가 필요합니다.'},
                status=status.HTTP_412_PRECONDITION_FAILED)

        # ── 2) 파일 검증 ──
        # 1=보유(증권) 기본 / 2=제안(가입제안서 업로드). 비교 분석 탭에서 2로 보낸다.
        try:
            portfolio_type = int(request.data.get('portfolio_type') or 1)
        except (TypeError, ValueError):
            portfolio_type = 1
        if portfolio_type not in (1, 2):
            portfolio_type = 1

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
        claude_meta = {}
        ocr_data = claude_parse(lines, normalizer=_build_normalizer(), meta=claude_meta)

        # ── 6.1) Claude usage → ClaudeApiLog (성공·실패 모두 1건 — 관리자 비용/결과 로깅) ──
        #    ★ 실패(ocr_data is None)여도 outcome(json_invalid/api_error/timeout/...)이 신호이므로
        #    아래 실패 응답보다 먼저 기록한다(프리런치 #17). claude_parse 를 직접 mock 하는
        #    기존 테스트는 meta 를 채우지 않으므로 ocr_data 유무로 안전한 fallback 을 둔다.
        outcome = claude_meta.get('outcome') or ('success' if ocr_data is not None else 'api_error')
        log_claude_usage(
            action='ocr_parse',
            model=claude_meta.get('model') or getattr(settings, 'CLAUDE_MODEL_PARSE', ''),
            usage=claude_meta.get('usage'),
            user=request.user,
            outcome=outcome,
            carrier_code=claude_meta.get('carrier_code'),
            matched=claude_meta.get('matched_count'),
            unmatched=claude_meta.get('unmatched_count'),
        )

        if ocr_data is None:
            # ★ FIX: Claude 호출 자체가 실패(timeout/api_error/no_key 등)해 결과가 없으면
            #   방금 차감한 ocr 크레딧을 되돌린다. empty/json_invalid(=Claude 가 응답을
            #   만든 경우)는 실제 비용이 발생했으므로 차감을 유지한다.
            if outcome in _TRANSPORT_FAILURE_OUTCOMES:
                _refund_ocr_credit(request.user)
            return Response(
                {'code': 'PARSE_FAILED',
                 'detail': '증권을 인식하지 못했습니다. 직접 입력해 주세요.'},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        # ── 7) 포트폴리오 + 담보 생성 (트랜잭션) + 계산 엔진 ──
        with transaction.atomic():
            ci, created_cases = _persist_ocr(customer, ocr_data, portfolio_type=portfolio_type)

        # ── 7.05) 북극성 계측 — 증권 OCR 업로드 성공(깔때기 입구). 실패는 격리(log_event 내부). ──
        #    설계사(owner) 능동 업로드만 집계 — 셀프진단(/d) 공개 경로는 여기로 오지 않는다.
        log_event(NorthStarEvent.OCR_UPLOAD, customer=customer,
                  sender=request.user, channel='web')

        # ── 7.1) 정확도 다중검사 — Claude 교차검증(원문↔파싱). 실패는 격리. ──
        if getattr(settings, 'OCR_VERIFY_ENABLED', False):
            from inpa.insurances.verify import verify_extraction
            verification, verify_usage = verify_extraction(lines, ci)
            if verification is not None:
                ci.verification = verification
                ci.save(update_fields=['verification', 'updated_at'])
            # ★ FIX(프리런치 #17): 과거 usage=None 하드코딩으로 토큰이 항상 0으로 찍히던 버그.
            #   실제 msg.usage 를 verify_extraction 이 반환하도록 고쳤다. 실패도 1건 기록.
            log_claude_usage(
                'ocr_verify',
                getattr(settings, 'CLAUDE_MODEL_PARSE', ''),
                verify_usage,
                user=request.user,
                outcome='success' if verification is not None else 'api_error',
            )

        data = CustomerInsuranceSerializerForDetail(ci).data
        return Response(
            {'code': 'OK',
             'parsing_method': getattr(ocr_data, 'parsing_method', 'claude'),
             'created_cases': created_cases,
             'verification': getattr(ci, 'verification', None),
             'insurance': data},
            status=status.HTTP_201_CREATED)


class CustomerInsuranceManualViewSet(viewsets.ModelViewSet):
    """고객 보유/제안 보험 수기 CRUD — OCR 폴백(이미지/실패/키없음) + 제안 입력.

    GET/POST          /api/v1/customers/<customer_pk>/insurances/manual/
    GET/PATCH/DELETE  /api/v1/customers/<customer_pk>/insurances/manual/<pk>/

    owner 전용(customer__owner 경유 — 부모 Customer 가 본인 것이 아니면 404=존재 은폐).
    담보 트리 없이 생성되므로 분석 히트맵엔 '보유 여부'만, 환수레이더·월보험료 요약에 반영.
    portfolio_type 1=보유 / 2=제안(갈아타기 비교 우측 입력 경로도 겸함).
    """
    serializer_class = CustomerInsuranceManualSerializer
    permission_classes = [IsAuthenticated, IsEmailVerified]
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

    def get_queryset(self):
        return (CustomerInsurance.objects
                .filter(customer=self.get_customer(), portfolio_type__in=(1, 2))
                .order_by('-created_at'))

    def perform_create(self, serializer):
        serializer.save(customer=self.get_customer())
