"""셀프진단 인바운드 — 비로그인 잠재고객이 ?ref 설계사 링크로 본인 증권 진단.

★ 컴플라이언스 (확정 결정 + 게이트, 우회 0):
  - 본인 식별 정보 필수: 이름·연락처·생년월일·성별 (PM 06.30 — 리드 가치↑).
  - 동의: 개인정보 수집·이용(설계사 전달)은 항상 필수. 국외이전(Claude)은 증권 PDF가
    실제 전송될 때만 필수 → OCR(Claude) 호출 전 412로 물리 차단.
  - ★ 제3자 제공·인파 플랫폼 활용 / 마케팅 수신은 '선택' 동의(개인정보보호법상 강제 금지).
    체크 시에만 ConsentLog 기록. 거부해도 진단·접수는 진행.
  - 증권 PDF는 선택 — 없으면 OCR 생략하고 리드만 등록('설계사가 연락' 안내).
  - 병력 미수집(증권 담보 사실만). 결과는 neutral 강제(부족/충분 판정 금지 = _build_share_payload).
  - 리드는 ref 설계사 소유 Customer(lead_source='self_diagnosis')로 생성 + 설계사 알림.
  - ★★ 유료 정식출시 전 법무 재검토 필요(G5 무작위발굴·제3자 동의 — CLAUDE.md 개발 전 게이트).

★ 다중 증권 (PM 2026-07-07): 'files' 멀티파트 필드로 1회 최대 5장. 파일별 독립
  파싱(하나 실패해도 나머지 진행) + 파일 1장당 일일 파싱 카운터 1회 소모. 응답에
  보험별 카드용 insurances[] (name/company_label/보험료/담보수/개별 트리/status).
  기존 단일 'file' 필드·최상위 tree/summary(전체 합산)는 하위호환 유지.

엔드포인트: POST /api/v1/d/<refcode>/  (AllowAny, multipart: name·phone·birth·gender 필수,
            files=PDF 여러 장(선택, 최대 5) 또는 legacy file=PDF 1장)
"""
import logging
import re
import uuid

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

# 무인증 경로 — 비용/남용 방어 상수.
SELF_DIAG_MAX_BYTES = 5 * 1024 * 1024     # 5MB (인증 OCR 50MB보다 강하게)
SELF_DIAG_DAILY_CAP_PER_REF = 30          # 설계사(refcode) 1명당 하루 셀프진단 리드/파싱 상한
SELF_DIAG_MAX_FILES = 5                   # 1회 요청당 증권 PDF 상한 (PM 2026-07-07)

from inpa.accounts.models import Profile
from inpa.analytics.events import log_event
from inpa.analytics.models import NorthStarEvent
from inpa.analytics.views import _NoIndexMixin, _build_share_payload, build_coverage_tree
from inpa.billing.credit import LimitExceeded, log_claude_usage
from inpa.core.copyguard import warn_if_advice_words
from inpa.core.ocr.claude_parser import claude_parse
from inpa.core.ocr.ocrdata import LifeInsurance, LossInsurance
from inpa.customers.consent_texts import CONSENT_TEXTS_VERSION
from inpa.customers.models import ConsentLog, Customer
from inpa.notifications.models import NotifType, Notification

from .views import (
    _build_normalizer, _extract_pdf_lines, _parse_value, _persist_ocr,
)

logger = logging.getLogger(__name__)

# ── 고객 대면 카드 안내 문구 (§6 레드라인: 혜택+다음 행동, 판정어·부정어 0) ──
MSG_FILE_FAILED = '이 증권은 읽지 못했어요. 담당 설계사가 직접 확인해 드릴 거예요.'
MSG_FILE_TOO_LARGE = '파일이 5MB보다 커서 읽지 못했어요. 담당 설계사가 직접 확인해 드릴 거예요.'
MSG_FILE_SKIPPED = '오늘은 여기까지 정리했어요. 담당 설계사가 나머지를 도와드릴 거예요.'
MSG_MAX_FILES = '증권은 한 번에 5장까지 정리해 드려요. 나머지는 담당 설계사가 함께 확인해 드릴게요.'
MSG_COVERAGE_REVIEW_REQUIRED = (
    '이 담보는 증권 원문에서 확인하면 정확하게 정리할 수 있어요. '
    '담당 설계사가 직접 확인해 드릴게요.')

_EXISTING_IMPORT_KINDS = frozenset({
    'active_duplicate', 'confirmed_duplicate', 'idempotent_replay',
    'legacy_idempotent_replay', 'source_reattached',
})
_PENDING_IMPORT_STATUSES = frozenset({
    'queued', 'extracting', 'validating', 'review_required',
})


def _safe_review_failure(status_codes):
    """공개 고객용 접수 오류. 내부 코드·상세·파일명을 반영하지 않는다."""
    if any(code >= 500 for code in status_codes):
        return (
            status.HTTP_503_SERVICE_UNAVAILABLE,
            'REVIEW_INTAKE_UNAVAILABLE',
            '담당 설계사에게 확인 요청을 남겼어요. 증권은 다시 선택해 주세요.',
        )
    if status.HTTP_429_TOO_MANY_REQUESTS in status_codes:
        return (
            status.HTTP_429_TOO_MANY_REQUESTS,
            'REVIEW_BUSY',
            '담당 설계사에게 확인 요청을 남겼어요. 잠시 후 다시 제출해 주세요.',
        )
    if status.HTTP_402_PAYMENT_REQUIRED in status_codes:
        return (
            status.HTTP_402_PAYMENT_REQUIRED,
            'REVIEW_LIMIT_REACHED',
            '담당 설계사에게 직접 확인 요청을 남겼어요.',
        )
    if status.HTTP_412_PRECONDITION_FAILED in status_codes:
        return (
            status.HTTP_412_PRECONDITION_FAILED,
            'CONSENT_REQUIRED',
            '동의 내용을 확인한 뒤 증권을 다시 제출해 주세요.',
        )
    if status.HTTP_409_CONFLICT in status_codes:
        return (
            status.HTTP_409_CONFLICT,
            'REVIEW_INTAKE_CONFLICT',
            '같은 증권 접수를 확인하고 있어요. 담당 설계사에게 요청은 전달했어요.',
        )
    return (
        status.HTTP_400_BAD_REQUEST,
        'POLICY_FILES_NOT_RECEIVED',
        'PDF 증권 파일을 다시 선택해 주세요. 담당 설계사에게 확인 요청은 전달했어요.',
    )


def _truthy(v):
    return str(v).lower() in ('1', 'true', 'on', 'yes', 'y')


def _display_name(filename):
    """업로드 파일명 → 카드 표시용 폴백 이름(.pdf 확장자 제거)."""
    base = (filename or '').rsplit('/', 1)[-1].rsplit('\\', 1)[-1]
    if base.lower().endswith('.pdf'):
        base = base[:-4]
    return base.strip() or '내 증권'


def _company_label(ocr_data):
    """파싱된 head dict 의 회사 인덱스 → 회사명 라벨. 미감지/범위 밖이면 None."""
    life_head = getattr(ocr_data, 'dict_life_head_data', None) or {}
    loss_head = getattr(ocr_data, 'dict_loss_head_data', None) or {}
    life_idx = life_head.get('생명보험', -1)
    if isinstance(life_idx, int) and 0 <= life_idx < len(LifeInsurance.company):
        return LifeInsurance.company[life_idx]
    loss_idx = loss_head.get('손해보험', -1)
    if isinstance(loss_idx, int) and 0 <= loss_idx < len(LossInsurance.company):
        return LossInsurance.company[loss_idx]
    return None


def _ocr_signature(ocr_data):
    """파싱된 증권 1건의 안정 서명 — (보험사코드, 상품명, 정렬된 담보·금액 지문).

    _persist_ocr 가 실제로 저장할 값과 같은 규약으로 계산한다(회사코드 오프셋·상품명·
    담보명↔금액). 같은 증권을 다시 제출하면 같은 서명이 나와 중복 저장을 건너뛴다.
    """
    life_head = getattr(ocr_data, 'dict_life_head_data', None) or {}
    loss_head = getattr(ocr_data, 'dict_loss_head_data', None) or {}
    if life_head.get('생명보험', -1) > -1:
        # ★ 사전 코드 공간 규약(_persist_ocr 와 동일): 생명 = 200 + LifeInsurance index.
        company_code = 200 + life_head.get('생명보험', -1)
        product = (life_head.get('상품명') or '').strip()
    elif loss_head.get('손해보험', -1) > -1:
        company_code = loss_head.get('손해보험', -1)
        product = (loss_head.get('상품명') or '').strip()
    else:
        company_code = -1
        product = (loss_head.get('상품명') or '').strip()

    coverages = []
    for _cat, subs in (getattr(ocr_data, 'dict_detail_data', None) or {}).items():
        for _sub, dets in subs.items():
            for det_name, value_list in dets.items():
                for value in value_list:
                    parsed = _parse_value(value)
                    if not parsed or parsed['amount'] <= 0:
                        continue
                    coverages.append((det_name, parsed['amount']))
    return (company_code, product, tuple(sorted(coverages)))


def _ci_signature(ci):
    """기존 CustomerInsurance 1건의 서명 — _ocr_signature 와 동일 규약으로 비교 가능."""
    coverages = [
        (case.detail.name, case.assurance_amount)
        for case in ci.case_list.all()
        if case.assurance_amount and case.assurance_amount > 0
    ]
    return (ci.company, (ci.name or '').strip(), tuple(sorted(coverages)))


class SelfDiagnosisView(_NoIndexMixin, APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    parser_classes = [MultiPartParser, FormParser]
    # ★ IP당 5건/시간 throttle(무인증 비용폭탄·DoS 방어). refcode 일일상한은 아래 DB 카운트로 2중.
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'self_diagnosis'

    def post(self, request, refcode):
        # 1) refcode → 설계사 resolve (없으면 404 = 존재 은폐)
        profile = Profile.objects.filter(ref_code=refcode).select_related('user').first()
        if profile is None:
            return Response({'code': 'INVALID_REF', 'detail': '유효하지 않은 링크입니다.'},
                            status=status.HTTP_404_NOT_FOUND)
        planner = profile.user

        # 1.5) ★ refcode 일일상한 (워커 무관 DB 카운트 — throttle의 워커별 한계 보완)
        today = timezone.now().date()
        todays_leads = Customer.objects.filter(
            owner=planner, lead_source='self_diagnosis', lead_created_at__date=today).count()
        if todays_leads >= SELF_DIAG_DAILY_CAP_PER_REF:
            return Response(
                {'code': 'DAILY_LIMIT', 'detail': '오늘 이 링크의 진단 한도를 초과했습니다. 내일 다시 시도해 주세요.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS)

        # 2) 입력값 — 본인 식별 정보 필수화(PM 06.30: 리드 가치↑). 증권 PDF는 선택.
        #    ★ 다중 파일: 'files' 리스트 + 기존 단일 'file' 하위호환(합쳐서 최대 5장).
        ip = request.META.get('REMOTE_ADDR')
        files = list(request.FILES.getlist('files'))
        legacy_single = request.FILES.get('file')
        if legacy_single is not None:
            files.insert(0, legacy_single)
        submitted_file_count = len(files)
        over_limit = submitted_file_count > SELF_DIAG_MAX_FILES
        overflow_file_count = max(
            0, submitted_file_count - SELF_DIAG_MAX_FILES)
        files = files[:SELF_DIAG_MAX_FILES]   # 초과분은 받지 않음(응답 notice 로 안내)
        has_files = bool(files)
        review_gate = getattr(
            settings, 'INSURANCE_REVIEW_GATE_ENABLED', False)
        name = (request.data.get('name') or '').strip()
        phone_digits = re.sub(r'[^0-9]', '', (request.data.get('phone') or '').strip())
        birth = (request.data.get('birth') or '').strip()        # YYYY-MM-DD
        gender_raw = (request.data.get('gender') or '').strip()  # '1'(남) | '2'(여)

        if not name:
            return Response({'code': 'NAME_REQUIRED', 'detail': '이름을 입력해 주세요.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if not re.fullmatch(r'01[0-9]{8,9}', phone_digits):
            return Response({'code': 'INVALID_PHONE', 'detail': '올바른 휴대폰 번호를 입력해 주세요.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', birth):
            return Response({'code': 'INVALID_BIRTH', 'detail': '생년월일을 정확히 선택해 주세요.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if gender_raw not in ('1', '2'):
            return Response({'code': 'INVALID_GENDER', 'detail': '성별을 선택해 주세요.'},
                            status=status.HTTP_400_BAD_REQUEST)
        gender = int(gender_raw)

        # 3) ★ 동의 게이트 — 개인정보 수집·이용(설계사 전달)은 항상 필수.
        #    국외이전(Claude)은 '증권 PDF가 실제로 전송될 때'만 필수(전송 없으면 불요).
        consent_overseas = _truthy(request.data.get('consent_overseas'))
        consent_share = _truthy(request.data.get('consent_share'))
        if not consent_share:
            return Response(
                {'code': 'CONSENT_REQUIRED',
                 'detail': '담당 설계사 전달(개인정보 수집·이용) 동의가 필요합니다.'},
                status=status.HTTP_412_PRECONDITION_FAILED)
        if has_files and not consent_overseas:
            return Response(
                {'code': 'CONSENT_REQUIRED',
                 'detail': '증권 분석을 위해 국외이전(Claude, 미국) 동의가 필요합니다.'},
                status=status.HTTP_412_PRECONDITION_FAILED)

        # 4) (PDF 있을 때만) 파일별 검증 → 텍스트 추출 → Claude 파싱.
        #    ★ 파일별 독립 실패 격리 — 한 장이 실패해도 나머지는 진행(status 로 구분).
        parsed_items = []   # 업로드 순서 보존: {display_name, ocr_data|None, status, message}
        if has_files and not review_gate:
            if not getattr(settings, 'ANTHROPIC_API_KEY', ''):
                return Response({'code': 'OCR_UNAVAILABLE',
                                 'detail': '지금은 증권을 바로 정리하기 어려워요. 담당 설계사가 직접 확인해 도와드릴게요.'},
                                status=status.HTTP_503_SERVICE_UNAVAILABLE)

            # ★ refcode 일일 '파싱 시도' 상한 — 동일 phone 재사용으로 DB 리드수 캡 우회하는
            #   비용폭탄 차단. prod는 DatabaseCache(워커 공유)라 정확. ★ 파일 1장 = 1회 소모.
            attempt_key = f'selfdiag-attempts:{refcode}:{today.isoformat()}'
            cache.add(attempt_key, 0, 60 * 60 * 24)
            for upload in files:
                item = {'display_name': _display_name(upload.name),
                        'ocr_data': None, 'status': 'failed', 'message': MSG_FILE_FAILED}
                # 캡 초과분은 파싱하지 않고 skipped 로 표시(요청 전체는 실패시키지 않음).
                if cache.get(attempt_key, 0) >= SELF_DIAG_DAILY_CAP_PER_REF:
                    item.update(status='skipped', message=MSG_FILE_SKIPPED)
                    parsed_items.append(item)
                    continue
                if upload.size > SELF_DIAG_MAX_BYTES:
                    item['message'] = MSG_FILE_TOO_LARGE
                    parsed_items.append(item)
                    continue
                if not upload.name.lower().endswith('.pdf'):
                    parsed_items.append(item)
                    continue
                lines, extract_err = _extract_pdf_lines(upload)
                if extract_err:  # IMAGE_PDF(스캔본) / PROCESSING_ERROR(손상 등)
                    parsed_items.append(item)
                    continue
                # 비싼 호출 직전 카운터 소모·검사(파일 1장당 1회).
                try:
                    cache.incr(attempt_key)
                except ValueError:
                    cache.set(attempt_key, 1, 60 * 60 * 24)
                claude_meta = {}
                try:
                    ocr_data = claude_parse(lines, normalizer=_build_normalizer(), meta=claude_meta)
                except Exception as e:  # 파일별 격리 — 내용 없는 로그만(PII 레드라인)
                    logger.warning('[self-diag] parse error: %s', type(e).__name__)
                    ocr_data = None
                # ★ 프리런치 #17: /d 는 비로그인 공개 경로 → user=None(귀속 없음). 성공·실패 모두 기록.
                #   claude_parse 를 직접 mock 하는 기존 다중 PDF 테스트는 meta 를 채우지 않으므로
                #   ocr_data 유무로 안전한 fallback 을 둔다(views.py ocr_parse 와 동일 패턴).
                outcome = claude_meta.get('outcome') or ('success' if ocr_data is not None else 'api_error')
                log_claude_usage(
                    action='self_diagnosis',
                    model=claude_meta.get('model') or getattr(settings, 'CLAUDE_MODEL_PARSE', ''),
                    usage=claude_meta.get('usage'),
                    user=None,
                    outcome=outcome,
                    carrier_code=claude_meta.get('carrier_code'),
                    matched=claude_meta.get('matched_count'),
                    unmatched=claude_meta.get('unmatched_count'),
                )
                if (ocr_data is not None
                        and getattr(
                            ocr_data,
                            '_manual_review_coverage_count',
                            0)):
                    item.update(
                        status='failed',
                        message=MSG_COVERAGE_REVIEW_REQUIRED,
                    )
                elif ocr_data is not None:
                    item.update(status='ok', ocr_data=ocr_data, message=None)
                parsed_items.append(item)

        # 5) 리드 Customer 생성(설계사 소유) + 동의 로그 (+ 파싱 성공 보험 전부 귀속)
        phone = phone_digits
        insurances_payload = None
        with transaction.atomic():
            # 같은 phone+설계사 셀프진단 리드가 이미 있으면 재사용(CRM 중복 오염 방지).
            customer = Customer.objects.filter(
                owner=planner, lead_source='self_diagnosis',
                mobile_phone_number=phone[:15]).first()
            if customer is None:
                customer = Customer.objects.create(
                    owner=planner, name=name[:20], mobile_phone_number=phone[:15],
                    birth_day=birth, gender=gender,
                    is_agree_term=True,                    # 개인정보 수집·이용 + 설계사 전달 동의
                    lead_source='self_diagnosis', lead_created_at=timezone.now(),
                )
            else:
                # 재방문 — 본인이 다시 제출한 최신 식별정보로 빈 칸만 보강(설계사 수정값은 보존).
                fields = []
                if not customer.birth_day and birth:
                    customer.birth_day = birth; fields.append('birth_day')
                if customer.gender is None:
                    customer.gender = gender; fields.append('gender')
                if fields:
                    customer.save(update_fields=fields)
            if has_files:
                # 국외이전 동의 → OCR 게이트 충족(이 시점에 실제 전송 발생).
                customer.consent_overseas_at = timezone.now()
                customer.save(update_fields=['consent_overseas_at'])
                ConsentLog.objects.create(
                    customer=customer, scope=ConsentLog.SCOPE_OVERSEAS_MEDICAL,
                    subject=ConsentLog.SUBJECT_CUSTOMER_SELF,  # 잠재고객 본인 동의(P3c)
                    purpose='셀프진단 증권 OCR 국외이전(Claude, 미국)',
                    doc_version=CONSENT_TEXTS_VERSION, ip=ip)
            # ✦ DB 자산화: 본인이 직접 제출 + 설계사 전달 동의 = 개인정보 수집·이용 동의로 명시 기록.
            ConsentLog.objects.create(
                customer=customer, scope=ConsentLog.SCOPE_PERSONAL_INFO,
                subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
                purpose='셀프진단 본인 제출·담당 설계사 전달',
                doc_version=CONSENT_TEXTS_VERSION, ip=ip)
            # ✦ 마케팅 수신(선택) — 체크 시에만.
            if _truthy(request.data.get('consent_marketing')):
                ConsentLog.objects.create(
                    customer=customer, scope=ConsentLog.SCOPE_MARKETING,
                    subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
                    purpose='셀프진단 마케팅 수신 동의',
                    doc_version=CONSENT_TEXTS_VERSION, ip=ip)
            # ✦ 제3자 제공·인파 플랫폼 활용(선택) — 체크 시에만. ★법상 강제 금지(필수 아님).
            if _truthy(request.data.get('consent_thirdparty')):
                ConsentLog.objects.create(
                    customer=customer, scope=ConsentLog.SCOPE_THIRD_PARTY,
                    subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
                    purpose='셀프진단 제3자 제공·인파 플랫폼 활용 동의',
                    doc_version=CONSENT_TEXTS_VERSION, ip=ip)
            # ── 파싱 성공 보험 전부 이 고객에 귀속 + 보험별 카드 페이로드 구성 ──
            if has_files:
                # ★ 중복 방지(재제출 시 금액 2배 버그): 같은 phone 리드를 재사용하므로
                #   이미 등록된 것과 동일한 증권(회사·상품·담보 지문 일치)은 다시 저장하지
                #   않고 기존 보험을 그대로 카드에 쓴다. 같은 요청 안의 동일 파일 2장도 커버.
                existing_by_sig = {}
                for prev_ci in (customer.customer_insurance_list
                                .filter(portfolio_type=1)
                                .prefetch_related('case_list__detail')):
                    existing_by_sig.setdefault(_ci_signature(prev_ci), prev_ci)
                entries = []
                for item in parsed_items:
                    if item['status'] != 'ok':
                        entries.append({
                            'name': item['display_name'], 'company_label': None,
                            'monthly_premium': None, 'total_premium': None,
                            'coverage_count': 0, 'tree': [],
                            'status': item['status'], 'message': item['message'],
                        })
                        continue
                    sig = _ocr_signature(item['ocr_data'])
                    dup = existing_by_sig.get(sig)
                    if dup is not None:
                        ci = dup
                        created_cases = ci.case_list.count()
                    else:
                        ci, created_cases = _persist_ocr(customer, item['ocr_data'])
                        existing_by_sig[sig] = ci
                    # ★ 그 보험만의 트리(보유 담보만 가지치기) — 카드 탭 상세용. neutral 강제.
                    tree = []
                    tree, _summary = build_coverage_tree(
                        customer, [ci], held_only=True)
                    entries.append({
                        'name': (ci.name or '').strip() or item['display_name'],
                        'company_label': _company_label(item['ocr_data']),
                        'monthly_premium': ci.monthly_premiums,
                        'total_premium': ci.total_premiums,
                        'coverage_count': created_cases,
                        'tree': tree,
                        'status': 'ok',
                    })
                insurances_payload = entries

        # gate ON은 legacy 즉시 파싱·저장을 거치지 않는다. 고객·동의가 확정된 뒤 기존
        # 검토형 접수 서비스에만 전달해 가명화, credit, owner, idempotency, queue 규칙을
        # 동일하게 적용한다. 공급자 호출은 승인된 worker가 큐를 가져간 뒤에만 가능하다.
        accepted_file_count = 0
        pending_accepted_count = 0
        existing_file_count = 0
        failed_file_count = overflow_file_count
        pending_existing_count = 0
        failure_status_codes = (
            [status.HTTP_400_BAD_REQUEST] * overflow_file_count)
        if has_files and review_gate:
            from . import import_services

            raw_key = request.headers.get('Idempotency-Key')
            try:
                request_key = uuid.UUID(str(raw_key))
            except (TypeError, ValueError, AttributeError):
                request_key = uuid.uuid4()
            attempt_key = f'selfdiag-attempts:{refcode}:{today.isoformat()}'
            cache.add(attempt_key, 0, 60 * 60 * 24)
            for index, upload in enumerate(files):
                if cache.get(attempt_key, 0) >= SELF_DIAG_DAILY_CAP_PER_REF:
                    failed_file_count += 1
                    failure_status_codes.append(
                        status.HTTP_429_TOO_MANY_REQUESTS)
                    continue
                if (upload.size > SELF_DIAG_MAX_BYTES
                        or not upload.name.lower().endswith('.pdf')):
                    failed_file_count += 1
                    failure_status_codes.append(status.HTTP_400_BAD_REQUEST)
                    continue
                try:
                    cache.incr(attempt_key)
                except ValueError:
                    cache.set(attempt_key, 1, 60 * 60 * 24)
                try:
                    result = import_services.receive_import(
                        owner=planner,
                        customer_pk=customer.pk,
                        uploaded_file=upload,
                        intent='add',
                        portfolio_type=1,
                        idempotency_key=uuid.uuid5(request_key, str(index)),
                    )
                except import_services.ImportReceptionError as exc:
                    failed_file_count += 1
                    failure_status_codes.append(
                        exc.status_code if exc.status_code in {
                            400, 402, 409, 412, 429,
                        } else status.HTTP_503_SERVICE_UNAVAILABLE)
                    logger.warning(
                        '[self-diag] review intake rejected: %s',
                        type(exc).__name__)
                    continue
                except LimitExceeded as exc:
                    failed_file_count += 1
                    failure_status_codes.append(
                        status.HTTP_402_PAYMENT_REQUIRED)
                    logger.warning(
                        '[self-diag] review intake rejected: %s',
                        type(exc).__name__)
                    continue
                except Exception as exc:
                    failed_file_count += 1
                    failure_status_codes.append(
                        status.HTTP_503_SERVICE_UNAVAILABLE)
                    logger.warning(
                        '[self-diag] review intake error: %s',
                        type(exc).__name__)
                    continue

                duplicate_kind = result.duplicate_kind
                job = result.job
                job_status = getattr(job, 'status', None)
                if getattr(job, 'pk', None) is not None:
                    try:
                        job.refresh_from_db(fields=['status'])
                        job_status = job.status
                    except Exception as exc:
                        failed_file_count += 1
                        failure_status_codes.append(
                            status.HTTP_503_SERVICE_UNAVAILABLE)
                        logger.warning(
                            '[self-diag] review intake status error: %s',
                            type(exc).__name__)
                        continue

                if duplicate_kind == 'created':
                    if (result.response_status == status.HTTP_202_ACCEPTED
                            and (job_status in _PENDING_IMPORT_STATUSES
                                 or job_status == 'confirmed')):
                        accepted_file_count += 1
                        if job_status in _PENDING_IMPORT_STATUSES:
                            pending_accepted_count += 1
                    else:
                        failed_file_count += 1
                        failure_status_codes.append(
                            status.HTTP_503_SERVICE_UNAVAILABLE)
                elif duplicate_kind in _EXISTING_IMPORT_KINDS:
                    if job_status == 'confirmed':
                        existing_file_count += 1
                    elif job_status in _PENDING_IMPORT_STATUSES:
                        existing_file_count += 1
                        pending_existing_count += 1
                    else:
                        failed_file_count += 1
                        failure_status_codes.append(
                            status.HTTP_503_SERVICE_UNAVAILABLE)
                else:
                    failed_file_count += 1
                    failure_status_codes.append(
                        status.HTTP_503_SERVICE_UNAVAILABLE)

        intake_available = (
            accepted_file_count + existing_file_count > 0)
        review_pending = bool(
            pending_accepted_count or pending_existing_count)
        event_file_count = (
            submitted_file_count if review_gate else len(files))
        legacy_analyzed = bool(
            not review_gate
            and any(
                item.get('status') == 'ok'
                for item in (insurances_payload or [])))

        # 6) 귀속 이벤트 + 설계사 알림(리드)
        log_event(NorthStarEvent.REFERRAL_ATTRIBUTED, customer=customer, sender=planner,
                  ref_code=refcode, channel='self_diagnosis',
                  payload={
                      'lead': True,
                      'analyzed': legacy_analyzed,
                      'review_pending': review_pending,
                      'files': event_file_count,
                      'queued_files': accepted_file_count,
                      'accepted_file_count': accepted_file_count,
                      'existing_file_count': existing_file_count,
                      'failed_file_count': failed_file_count,
                      'intake_succeeded': intake_available,
                  })
        try:
            if has_files and review_gate:
                if not intake_available:
                    body = (
                        f'{name} 고객님의 증권 {failed_file_count}장은 '
                        '직접 확인이 필요해요. 고객 목록에서 확인해 주세요.')
                else:
                    count_parts = []
                    if accepted_file_count:
                        count_parts.append(
                            f'{accepted_file_count}장 접수')
                    if existing_file_count:
                        count_parts.append(
                            f'기존 {existing_file_count}장 확인')
                    if failed_file_count:
                        count_parts.append(
                            f'{failed_file_count}장 직접 확인')
                    body = (
                        f'{name} 고객님 증권 처리 현황: '
                        f'{", ".join(count_parts)}. '
                        '고객 목록에서 확인해 주세요.')
            elif has_files and legacy_analyzed:
                body = f'{name} 고객님이 셀프진단을 완료했어요. 고객 목록에서 확인하세요.'
            elif has_files:
                body = (
                    f'{name} 고객님의 증권은 직접 확인이 필요해요. '
                    '고객 목록에서 확인해 주세요.')
            else:
                body = f'{name} 고객님이 상담을 신청했어요(증권 없이). 직접 연락해 도와주세요.'
            Notification.objects.create(
                owner=planner, notif_type=NotifType.SELF_DIAGNOSIS_LEAD,
                title='새 셀프진단 고객', body=body, customer=customer)
        except Exception:
            pass

        # 7) 응답 — PDF 있으면 neutral 결과(사실만, 부족/충분 판정 없음), 없으면 접수 확인만.
        #    최상위 tree/summary = 전체 합산(하위호환·요약 카드), insurances[] = 보험별 카드.
        if has_files:
            if review_gate:
                response_body = {
                    'lead_created': True,
                    'analyzed': False,
                    'review_pending': review_pending,
                    'accepted_file_count': accepted_file_count,
                    'existing_file_count': existing_file_count,
                    'failed_file_count': failed_file_count,
                }
                if intake_available:
                    if failed_file_count:
                        response_body['message'] = (
                            '담당 설계사가 접수된 증권을 확인하고, '
                            '나머지는 직접 확인해 안내해 드려요.')
                    elif review_pending:
                        response_body['message'] = (
                            '담당 설계사가 증권 내용을 '
                            '확인한 뒤 안내해 드려요.')
                    else:
                        response_body['message'] = (
                            '이미 확인된 증권을 바탕으로 '
                            '담당 설계사가 안내해 드려요.')
                    return Response(
                        response_body, status=status.HTTP_201_CREATED)

                response_status, code, detail = _safe_review_failure(
                    failure_status_codes)
                response_body.update({'code': code, 'detail': detail})
                return Response(response_body, status=response_status)
            payload = _build_share_payload(customer)
            payload['lead_created'] = True
            payload['analyzed'] = legacy_analyzed
            payload['insurances'] = insurances_payload
            # ★ 권유 단어 서버측 가드(#23) — 이번 응답에 실린 고정 카피만 관측(로그, 화면 유지).
            fixed_copy = {f'insurances[{i}].message': e['message']
                          for i, e in enumerate(insurances_payload) if e.get('message')}
            if over_limit:
                payload['notice'] = MSG_MAX_FILES
                fixed_copy['notice'] = MSG_MAX_FILES
            if fixed_copy:
                warn_if_advice_words(fixed_copy, where='self_diagnosis_cards')
            return Response(payload, status=status.HTTP_201_CREATED)
        return Response({'lead_created': True, 'analyzed': False}, status=status.HTTP_201_CREATED)
