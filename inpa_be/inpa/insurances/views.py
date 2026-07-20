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
import uuid

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import APIException, NotFound
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.response import Response
from rest_framework.views import APIView

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
from . import import_services
from .import_validation import MANUAL_COVERAGE_FIELDS, validate_draft
from .models import (
    CustomerInsurance, CustomerInsuranceDetail, InsuranceCategory,
    InsuranceDetail, InsuranceSubCategory, ManualInsuranceCommand,
)
from .serializers import (
    CustomerInsuranceManualSerializer, CustomerInsuranceSerializerForDetail,
    ManualCoverageDeleteSerializer, ManualCoveragePatchSerializer,
    ManualCoverageReadSerializer, ManualCoverageWriteSerializer,
    ManualInsuranceConfirmSerializer, ManualInsuranceExcludeSerializer,
    _manual_policy_payload,
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
        # PDF 라이브러리 예외 메시지에는 원문 조각이 섞일 수 있어 타입만 기록한다.
        logger.warning(
            '[ocr-upload] pdf extract error type=%s', type(e).__name__)
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

        # 검토형 게이트가 켜진 뒤에는 이 레거시 주소도 동일한 비동기 접수 서비스만
        # 사용한다. 아래 즉시 저장 경로로 우회할 수 없다.
        if getattr(settings, 'INSURANCE_REVIEW_GATE_ENABLED', False):
            from .import_views import delegate_legacy_import
            return delegate_legacy_import(request, customer)

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
                {'code': 'OCR_UNAVAILABLE',
                 'detail': '지금은 증권 자동 분석을 사용할 수 없어요. 직접 입력으로 등록할 수 있어요.'},
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

        review_required_count = getattr(
            ocr_data, '_manual_review_coverage_count', 0)
        if review_required_count:
            return Response(
                {
                    'code': 'COVERAGE_REVIEW_REQUIRED',
                    'detail': (
                        '증권 원문을 확인해 담보 위치를 직접 수정해 주세요.'),
                    'review_required_count': review_required_count,
                },
                status=status.HTTP_409_CONFLICT,
            )

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
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']
    parent_lookup = 'customer_pk'

    def _is_admin(self):
        profile = getattr(self.request.user, 'profile', None)
        return bool(getattr(profile, 'is_admin', False))

    def get_customer(self, *, for_write=False):
        qs = Customer.objects.all()
        if for_write or not self._is_admin():
            qs = qs.filter(owner=self.request.user)
        try:
            return qs.get(pk=self.kwargs[self.parent_lookup])
        except Customer.DoesNotExist:
            raise NotFound('고객을 찾을 수 없습니다.')

    def get_queryset(self):
        return (CustomerInsurance.objects
                .filter(customer=self.get_customer(), portfolio_type__in=(1, 2))
                .order_by('-created_at'))

    def create(self, request, *args, **kwargs):
        # 존재 은폐가 입력값 검증보다 먼저다. 다른 설계사의 고객 ID로
        # 잘못된 본문을 보내도 필드 오류 대신 같은 404를 돌려준다.
        self.get_customer(for_write=True)
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        customer = self.get_customer(for_write=True)
        with transaction.atomic():
            customer_qs = Customer.objects.select_for_update().filter(
                pk=customer.pk, owner=self.request.user)
            try:
                customer = customer_qs.get()
            except Customer.DoesNotExist as exc:
                raise NotFound('고객을 찾을 수 없습니다.') from exc
            serializer.save(
                customer=customer,
                review_status='draft',
                analysis_included=False,
                confirmation_source='',
            )

    def partial_update(self, request, *args, **kwargs):
        self.get_customer(for_write=True)
        with transaction.atomic():
            try:
                instance = self.get_queryset().select_for_update().get(
                    pk=kwargs['pk'])
            except CustomerInsurance.DoesNotExist as exc:
                raise NotFound('보험을 찾을 수 없습니다.') from exc
            serializer = self.get_serializer(
                instance, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            expected_version = serializer.validated_data['data_version']
            if instance.data_version != expected_version:
                return Response({
                    'code': 'INSURANCE_VERSION_CHANGED',
                    'detail': '다른 화면에서 내용이 바뀌었어요. 최신 내용을 확인해 주세요.',
                    'current_version': instance.data_version,
                }, status=status.HTTP_409_CONFLICT)
            if instance.review_status not in {
                    'draft', 'legacy_review_required'}:
                return Response({
                    'code': 'MANUAL_INSURANCE_CONFIRMED',
                    'detail': '확인한 보험은 새 자료로 추가해 주세요.',
                }, status=status.HTTP_409_CONFLICT)
            serializer.save()
            updated = CustomerInsurance.objects.filter(
                pk=instance.pk, data_version=expected_version).update(
                    data_version=F('data_version') + 1)
            if updated != 1:
                raise ManualVersionChanged()
            instance.refresh_from_db()
        return Response(self.get_serializer(instance).data)

    def destroy(self, request, *args, **kwargs):
        customer = self.get_customer(for_write=True)
        serializer = ManualCoverageDeleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected_version = serializer.validated_data['data_version']
        with transaction.atomic():
            customer_qs = Customer.objects.select_for_update().filter(
                pk=customer.pk, owner=request.user)
            try:
                customer_qs.get()
            except Customer.DoesNotExist as exc:
                raise NotFound('고객을 찾을 수 없습니다.') from exc
            try:
                insurance = self.get_queryset().select_for_update().get(
                    pk=kwargs['pk'])
            except CustomerInsurance.DoesNotExist as exc:
                raise NotFound('보험을 찾을 수 없습니다.') from exc
            if insurance.data_version != expected_version:
                return _manual_error(
                    'INSURANCE_VERSION_CHANGED',
                    '다른 화면에서 내용이 바뀌었어요. 최신 내용을 확인해 주세요.',
                    current_version=insurance.data_version,
                )
            if insurance.review_status not in {
                    'draft', 'legacy_review_required'}:
                return _manual_error(
                    'MANUAL_INSURANCE_PRESERVED',
                    '확인 기록은 그대로 두고 새 자료를 추가해 주세요.',
                )
            insurance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


def _owned_manual_insurance(owner, customer_pk, insurance_pk, *, lock=False):
    queryset = CustomerInsurance.objects
    if lock:
        queryset = queryset.select_for_update()
    try:
        return queryset.get(
            pk=insurance_pk,
            customer_id=customer_pk,
            customer__owner=owner,
            portfolio_type__in=(1, 2),
        )
    except CustomerInsurance.DoesNotExist as exc:
        raise NotFound('보험을 찾을 수 없습니다.') from exc


def _manual_error(code, detail, *, current_version=None):
    body = {'code': code, 'detail': detail}
    if current_version is not None:
        body['current_version'] = current_version
    return Response(body, status=status.HTTP_409_CONFLICT)


def _manual_import_error(exc):
    return Response(
        {'code': exc.code, 'detail': exc.detail, **exc.extra},
        status=exc.status_code,
    )


def _manual_idempotency_key(request):
    raw_value = request.headers.get('Idempotency-Key')
    if not raw_value:
        raise serializers.ValidationError({
            'Idempotency-Key':
                '요청을 안전하게 이어갈 수 있도록 다시 시도해 주세요.',
        })
    try:
        return uuid.UUID(raw_value)
    except (TypeError, ValueError, AttributeError) as exc:
        raise serializers.ValidationError({
            'Idempotency-Key': '요청 정보를 새로 고친 뒤 다시 시도해 주세요.',
        }) from exc


class ManualVersionChanged(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = 'INSURANCE_VERSION_CHANGED'
    default_detail = {
        'code': 'INSURANCE_VERSION_CHANGED',
        'detail': '다른 화면에서 내용이 바뀌었어요. 최신 내용을 확인해 주세요.',
    }


def _bump_manual_version(insurance_id, expected_version):
    updated = CustomerInsurance.objects.filter(
        pk=insurance_id, data_version=expected_version).update(
            data_version=F('data_version') + 1)
    if updated != 1:
        raise ManualVersionChanged()


def _assert_manual_mutable(insurance, expected_version):
    if insurance.data_version != expected_version:
        return _manual_error(
            'INSURANCE_VERSION_CHANGED',
            '다른 화면에서 내용이 바뀌었어요. 최신 내용을 확인해 주세요.',
            current_version=insurance.data_version)
    if insurance.review_status not in {'draft', 'legacy_review_required'}:
        return _manual_error(
            'MANUAL_INSURANCE_CONFIRMED',
            '확인한 보험은 새 자료로 추가해 주세요.')
    if insurance.is_cancelled:
        return _manual_error(
            'MANUAL_INSURANCE_NOT_REVIEWABLE',
            '계약 상태를 확인한 뒤 새 자료로 추가해 주세요.')
    return None


def _manual_row_payload(values, *, row_id):
    return {
        'row_id': row_id,
        'raw_name': values.get('raw_name'),
        'assurance_amount': values.get('assurance_amount'),
        'premium': values.get('premium'),
        'is_renewal': values.get('is_renewal'),
        'renewal_period': values.get('renewal_period'),
        'payment_period': values.get('payment_period'),
        'payment_period_unit': values.get('payment_period_unit'),
        'warranty_period': values.get('warranty_period'),
        'warranty_period_unit': values.get('warranty_period_unit'),
        'disposition': 'assigned',
        'standard_category': values.get('standard_category'),
        'standard_subcategory': values.get('standard_subcategory'),
        'standard_detail_name': values.get('standard_detail_name'),
        'exclusion_reason': None,
        'duplicate_of_row_id': None,
        # Manual entry has no source artifact. These server-owned fields are
        # always empty and cannot be supplied by the request serializer.
        'source_candidate_ids': [],
        'evidence_line_ids': [],
        'manual_fields': list(MANUAL_COVERAGE_FIELDS),
    }


def _manual_policy_values(insurance):
    return {
        'company': insurance.company,
        'insurance_type': insurance.insurance_type,
        'name': insurance.name,
        'contract_date': insurance.contract_date,
        'expiry_date': insurance.expiry_date,
        'monthly_premiums': insurance.monthly_premiums,
    }


def _validate_manual_draft(insurance, rows):
    return validate_draft(
        [], [], {
            'policy': _manual_policy_payload(
                _manual_policy_values(insurance)),
            'coverage_rows': rows,
        },
        allow_manual=True,
        allow_manual_without_evidence=True,
    )


def _validated_manual_rows(insurance, rows):
    validation = _validate_manual_draft(insurance, rows)
    validated_rows = validation.draft['coverage_rows']
    if any(row.get('state') not in {'manual', 'review_ready'}
           for row in validated_rows):
        raise serializers.ValidationError({
            'code': 'MANUAL_DRAFT_INVALID',
            'detail': '기간과 금액을 다시 확인해 주세요.',
            'issues': [
                {'code': issue.code, 'field': issue.field}
                for issue in validation.issues
            ],
        })
    return validated_rows


def _manual_values_from_case(case):
    analysis_details = list(
        case.effective_analysis_details().select_related(
            'sub_category__category').order_by('pk')[:2])
    analysis_detail = (
        analysis_details[0] if len(analysis_details) == 1 else None)
    try:
        warranty_period = (
            int(case.warranty_period)
            if case.warranty_period not in (None, '') else None)
    except (TypeError, ValueError):
        warranty_period = None
    return {
        'raw_name': case.raw_name,
        'assurance_amount': case.assurance_amount,
        'premium': case.premium,
        'is_renewal': case.is_renewal_case,
        'renewal_period': case.renewal_period,
        'payment_period': case.payment_period,
        'payment_period_unit': (
            'lifetime'
            if case.payment_period_type == 4
            else ('age' if case.payment_period_type == 2 else 'years')),
        'warranty_period': warranty_period,
        'warranty_period_unit': {
            1: 'age', 2: 'years', 4: 'lifetime',
        }.get(case.warranty_period_type),
        'standard_category': (
            analysis_detail.sub_category.category.name
            .removeprefix('[표준]')
            if analysis_detail is not None else None),
        'standard_subcategory': (
            analysis_detail.sub_category.name
            if analysis_detail is not None else None),
        'standard_detail_name': (
            analysis_detail.name if analysis_detail is not None else None),
    }


def _save_manual_case(insurance, row, *, instance=None,
                      mapping_changed=True):
    analysis_detail = import_services._standard_analysis_detail(row)
    (payment_type, payment_period, warranty_type,
     warranty_period) = import_services._period_types(row)
    values = {
        'raw_name': row['raw_name'][:200],
        'assurance_amount': row.get('assurance_amount'),
        'premium': row.get('premium'),
        'renewal_period': row.get('renewal_period'),
        'payment_period': payment_period,
        'payment_period_type': payment_type,
        'warranty_period': (
            str(warranty_period) if warranty_period is not None else None),
        'warranty_period_type': warranty_type,
        'confirmed_at': None,
    }
    if instance is None:
        catalog_detail = import_services._catalog_detail_for_override(
            row, insurance.insurance_type)
        instance = CustomerInsuranceDetail.objects.create(
            insurance=insurance,
            detail=catalog_detail,
            mapping_source='manual',
            review_reason=[],
            source_page=None,
            source_line_start=None,
            source_line_end=None,
            source_text_masked='',
            source_candidate_ids=[],
            evidence_line_ids=[],
            **values)
    else:
        if mapping_changed:
            values['detail'] = import_services._catalog_detail_for_override(
                row, insurance.insurance_type)
            values['mapping_source'] = 'manual'
        for field, value in values.items():
            setattr(instance, field, value)
        instance.save(update_fields=(*values.keys(), 'updated_at'))
    if instance.mapping_source == 'manual' and mapping_changed:
        instance.analysis_detail_override.set([analysis_detail])
    return instance


def _manual_review_bundle(insurance):
    cases = list(
        insurance.case_list.select_related(
            'detail__sub_category__category').prefetch_related(
            'detail__analysis_detail', 'analysis_detail_override')
        .order_by('pk'))
    return {
        'insurance_id': insurance.pk,
        'insurance': CustomerInsuranceManualSerializer(insurance).data,
        'data_version': insurance.data_version,
        'review_status': insurance.review_status,
        'analysis_included': insurance.analysis_included,
        'confirmation_source': insurance.confirmation_source,
        'confirmation_requirements': {
            'planner_confirmed_contents': {'required': True},
        },
        'standard_coverages': import_services.standard_coverage_catalog(),
        'coverages': ManualCoverageReadSerializer(cases, many=True).data,
    }


class ManualCoverageCollectionView(APIView):
    permission_classes = [IsAuthenticated, IsEmailVerified]

    def get(self, request, customer_pk, insurance_pk):
        insurance = _owned_manual_insurance(
            request.user, customer_pk, insurance_pk)
        return Response(_manual_review_bundle(insurance))

    def post(self, request, customer_pk, insurance_pk):
        _owned_manual_insurance(request.user, customer_pk, insurance_pk)
        serializer = ManualCoverageWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        expected_version = payload.pop('data_version')
        try:
            with transaction.atomic():
                insurance = _owned_manual_insurance(
                    request.user, customer_pk, insurance_pk, lock=True)
                conflict = _assert_manual_mutable(
                    insurance, expected_version)
                if conflict:
                    return conflict
                row = _validated_manual_rows(insurance, [
                    _manual_row_payload(
                        payload, row_id='manual-new')])[0]
                case = _save_manual_case(insurance, row)
                _bump_manual_version(insurance.pk, expected_version)
        except import_services.ImportReceptionError as exc:
            return _manual_import_error(exc)
        body = dict(ManualCoverageReadSerializer(case).data)
        body['data_version'] = expected_version + 1
        return Response(body, status=status.HTTP_201_CREATED)


class ManualCoverageDetailView(APIView):
    permission_classes = [IsAuthenticated, IsEmailVerified]

    def _case(self, insurance, case_pk, *, lock=False):
        queryset = insurance.case_list
        if lock:
            queryset = queryset.select_for_update()
        try:
            return queryset.get(pk=case_pk)
        except CustomerInsuranceDetail.DoesNotExist as exc:
            raise NotFound('담보를 찾을 수 없습니다.') from exc

    def patch(self, request, customer_pk, insurance_pk, case_pk):
        scoped = _owned_manual_insurance(
            request.user, customer_pk, insurance_pk)
        self._case(scoped, case_pk)
        serializer = ManualCoveragePatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        changes = dict(serializer.validated_data)
        expected_version = changes.pop('data_version')
        mapping_fields = {
            'standard_category', 'standard_subcategory',
            'standard_detail_name'}
        mapping_changed = bool(mapping_fields.intersection(changes))
        try:
            with transaction.atomic():
                insurance = _owned_manual_insurance(
                    request.user, customer_pk, insurance_pk, lock=True)
                conflict = _assert_manual_mutable(
                    insurance, expected_version)
                if conflict:
                    return conflict
                case = self._case(insurance, case_pk, lock=True)
                values = _manual_values_from_case(case)
                values.update(changes)
                row = _validated_manual_rows(insurance, [
                    _manual_row_payload(
                        values, row_id=f'manual-{case.pk}')])[0]
                case = _save_manual_case(
                    insurance, row, instance=case,
                    mapping_changed=mapping_changed)
                _bump_manual_version(insurance.pk, expected_version)
        except import_services.ImportReceptionError as exc:
            return _manual_import_error(exc)
        body = dict(ManualCoverageReadSerializer(case).data)
        body['data_version'] = expected_version + 1
        return Response(body)

    def delete(self, request, customer_pk, insurance_pk, case_pk):
        scoped = _owned_manual_insurance(
            request.user, customer_pk, insurance_pk)
        self._case(scoped, case_pk)
        serializer = ManualCoverageDeleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected_version = serializer.validated_data['data_version']
        with transaction.atomic():
            insurance = _owned_manual_insurance(
                request.user, customer_pk, insurance_pk, lock=True)
            conflict = _assert_manual_mutable(insurance, expected_version)
            if conflict:
                return conflict
            case = self._case(insurance, case_pk, lock=True)
            deleted_case_id = case.pk
            case.delete()
            _bump_manual_version(insurance.pk, expected_version)
        return Response({
            'insurance_id': insurance.pk,
            'deleted_coverage_id': deleted_case_id,
            'data_version': expected_version + 1,
        })


class ManualInsuranceConfirmView(APIView):
    permission_classes = [IsAuthenticated, IsEmailVerified]

    def post(self, request, customer_pk, insurance_pk):
        _owned_manual_insurance(request.user, customer_pk, insurance_pk)
        idempotency_key = _manual_idempotency_key(request)
        serializer = ManualInsuranceConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected_version = serializer.validated_data['data_version']
        request_sha256 = import_services._command_request_sha256(
            serializer.validated_data)
        with transaction.atomic():
            insurance = _owned_manual_insurance(
                request.user, customer_pk, insurance_pk, lock=True)
            command = (
                ManualInsuranceCommand.objects.select_for_update().filter(
                    insurance=insurance,
                    operation='confirm',
                    idempotency_key=idempotency_key,
                ).first()
            )
            if command is not None:
                try:
                    response_status, response_body = (
                        import_services._replay_command(
                            command, request_sha256))
                except import_services.ImportReceptionError as exc:
                    return _manual_import_error(exc)
                return Response(response_body, status=response_status)
            conflict = _assert_manual_mutable(insurance, expected_version)
            if conflict:
                return conflict
            cases = list(
                insurance.case_list.select_for_update().order_by('pk'))
            if not cases:
                return _manual_error(
                    'MANUAL_COVERAGE_REQUIRED',
                    '담보를 한 개 이상 입력하면 바로 확인할 수 있어요.')
            rows = [
                _manual_row_payload(
                    _manual_values_from_case(case),
                    row_id=f'manual-{case.pk}')
                for case in cases
            ]
            validation = _validate_manual_draft(insurance, rows)
            if validation.summary.get('unresolved_count') != 0:
                policy_invalid = any(
                    issue.scope == 'policy'
                    for issue in validation.issues)
                return Response({
                    'code': (
                        'MANUAL_POLICY_INVALID'
                        if policy_invalid else 'MANUAL_DRAFT_INVALID'),
                    'detail': '보험 기본정보와 담보를 다시 확인해 주세요.',
                    'issues': [
                        {
                            'code': issue.code,
                            'scope': issue.scope,
                            'field': issue.field,
                        }
                        for issue in validation.issues
                    ],
                }, status=status.HTTP_409_CONFLICT)
            try:
                import_services._assert_calculation_prerequisites(
                    insurance.customer, validation.draft)
            except import_services.ImportReceptionError as exc:
                return _manual_import_error(exc)
            command = ManualInsuranceCommand.objects.create(
                insurance=insurance,
                operation='confirm',
                idempotency_key=idempotency_key,
                request_sha256=request_sha256,
            )
            # Canonicalize validated dates inside this atomic confirmation so
            # calculation failure rolls every change back.
            for field in ('contract_date', 'expiry_date'):
                value = getattr(insurance, field)
                if value is not None:
                    setattr(
                        insurance, field,
                        import_services._model_date(value))
            insurance.save(update_fields=(
                'contract_date', 'expiry_date', 'updated_at'))
            import_services._calculate_materialized_insurance(insurance)
            now = timezone.now()
            previous_review_status = insurance.review_status
            confirmation_source = (
                'legacy_review'
                if previous_review_status == 'legacy_review_required'
                else 'manual_entry')
            updated = CustomerInsurance.objects.filter(
                pk=insurance.pk,
                customer_id=customer_pk,
                customer__owner=request.user,
                review_status=previous_review_status,
                data_version=expected_version,
            ).update(
                review_status='confirmed',
                analysis_included=True,
                confirmation_source=confirmation_source,
                confirmed_by=request.user,
                confirmed_at=now,
                data_version=F('data_version') + 1,
            )
            if updated != 1:
                raise ManualVersionChanged()
            CustomerInsuranceDetail.objects.filter(
                insurance=insurance).update(confirmed_at=now)
            insurance.refresh_from_db()
            response_body = {
                'insurance_id': insurance.pk,
                'review_status': insurance.review_status,
                'analysis_included': insurance.analysis_included,
                'data_version': insurance.data_version,
                'confirmation_source': insurance.confirmation_source,
                'confirmed_at': insurance.confirmed_at.isoformat(),
            }
            command.response_status = status.HTTP_200_OK
            command.response_body = response_body
            command.completed_at = now
            command.save(update_fields=(
                'response_status', 'response_body', 'completed_at'))
        return Response(response_body)


class ManualInsuranceExcludeView(APIView):
    permission_classes = [IsAuthenticated, IsEmailVerified]

    def post(self, request, customer_pk, insurance_pk):
        _owned_manual_insurance(request.user, customer_pk, insurance_pk)
        serializer = ManualInsuranceExcludeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected_version = serializer.validated_data['data_version']
        reason = serializer.validated_data['reason']
        with transaction.atomic():
            insurance = _owned_manual_insurance(
                request.user, customer_pk, insurance_pk, lock=True)
            conflict = _assert_manual_mutable(insurance, expected_version)
            if conflict:
                return conflict
            updated = CustomerInsurance.objects.filter(
                pk=insurance.pk,
                customer_id=customer_pk,
                customer__owner=request.user,
                review_status=insurance.review_status,
                is_cancelled=False,
                data_version=expected_version,
            ).update(
                review_status='excluded',
                analysis_included=False,
                review_exclusion_reason=reason,
                data_version=F('data_version') + 1,
            )
            if updated != 1:
                raise ManualVersionChanged()
            insurance.refresh_from_db()
        return Response({
            'insurance_id': insurance.pk,
            'review_status': insurance.review_status,
            'analysis_included': insurance.analysis_included,
            'data_version': insurance.data_version,
            'exclusion_reason': insurance.review_exclusion_reason,
        })
