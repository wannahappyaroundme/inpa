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

엔드포인트: POST /api/v1/d/<refcode>/  (AllowAny, multipart: name·phone·birth·gender 필수, file=PDF 선택)
"""
import re

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
SELF_DIAG_DAILY_CAP_PER_REF = 30          # 설계사(refcode) 1명당 하루 셀프진단 리드 상한

from inpa.accounts.models import Profile
from inpa.analytics.events import log_event
from inpa.analytics.models import NorthStarEvent
from inpa.analytics.views import _NoIndexMixin, _build_share_payload
from inpa.core.ocr.claude_parser import claude_parse
from inpa.customers.consent_texts import CONSENT_TEXTS_VERSION
from inpa.customers.models import ConsentLog, Customer
from inpa.notifications.models import NotifType, Notification

from .views import _build_normalizer, _extract_pdf_lines, _persist_ocr


def _truthy(v):
    return str(v).lower() in ('1', 'true', 'on', 'yes', 'y')


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
        ip = request.META.get('REMOTE_ADDR')
        upload = request.FILES.get('file')
        has_file = upload is not None
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
        if has_file and not consent_overseas:
            return Response(
                {'code': 'CONSENT_REQUIRED',
                 'detail': '증권 분석을 위해 국외이전(Claude, 미국) 동의가 필요합니다.'},
                status=status.HTTP_412_PRECONDITION_FAILED)

        # 4) (PDF 있을 때만) 파일 검증 → 텍스트 추출 → Claude 파싱
        ocr_data = None
        if has_file:
            if upload.size > SELF_DIAG_MAX_BYTES:
                return Response({'code': 'FILE_TOO_LARGE', 'detail': '5MB 이하의 PDF만 업로드 가능합니다.'},
                                status=status.HTTP_400_BAD_REQUEST)
            if not upload.name.lower().endswith('.pdf'):
                return Response({'code': 'IMAGE_PDF', 'detail': '전자 PDF 형식 파일로 부탁드립니다.'},
                                status=status.HTTP_400_BAD_REQUEST)

            lines, extract_err = _extract_pdf_lines(upload)
            if extract_err == 'IMAGE_PDF':
                return Response({'code': 'IMAGE_PDF', 'detail': '전자 PDF 형식 파일로 부탁드립니다.'},
                                status=status.HTTP_400_BAD_REQUEST)
            if extract_err:
                return Response({'code': 'PROCESSING_ERROR', 'detail': '문서 처리 중 오류가 발생했습니다.'},
                                status=status.HTTP_400_BAD_REQUEST)

            if not getattr(settings, 'ANTHROPIC_API_KEY', ''):
                return Response({'code': 'OCR_UNAVAILABLE', 'detail': 'OCR 분석이 현재 비활성화되어 있습니다.'},
                                status=status.HTTP_503_SERVICE_UNAVAILABLE)

            # ★ refcode 일일 '파싱 시도' 상한 — 동일 phone 재사용으로 DB 리드수 캡(57-64)을
            #   우회하는 비용폭탄 차단. prod는 DatabaseCache(워커 공유)라 정확. 비싼 호출 직전 증가·검사.
            attempt_key = f'selfdiag-attempts:{refcode}:{today.isoformat()}'
            if cache.get(attempt_key, 0) >= SELF_DIAG_DAILY_CAP_PER_REF:
                return Response(
                    {'code': 'DAILY_LIMIT', 'detail': '오늘 이 링크의 진단 한도를 초과했습니다. 내일 다시 시도해 주세요.'},
                    status=status.HTTP_429_TOO_MANY_REQUESTS)
            cache.add(attempt_key, 0, 60 * 60 * 24)
            try:
                cache.incr(attempt_key)
            except ValueError:
                cache.set(attempt_key, 1, 60 * 60 * 24)

            ocr_data = claude_parse(lines, normalizer=_build_normalizer())
            if ocr_data is None:
                return Response({'code': 'PARSE_FAILED', 'detail': '증권을 인식하지 못했습니다.'},
                                status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        # 5) 리드 Customer 생성(설계사 소유) + 동의 로그 (+ PDF 있으면 포트폴리오)
        phone = phone_digits
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
            if has_file:
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
            if ocr_data is not None:
                _persist_ocr(customer, ocr_data)

        # 6) 귀속 이벤트 + 설계사 알림(리드)
        log_event(NorthStarEvent.REFERRAL_ATTRIBUTED, customer=customer, sender=planner,
                  ref_code=refcode, channel='self_diagnosis', payload={'lead': True, 'analyzed': has_file})
        try:
            body = (f'{name} 잠재고객이 셀프진단을 완료했어요. CRM에서 확인하세요.' if has_file
                    else f'{name} 잠재고객이 상담을 신청했어요(증권 미첨부). 직접 연락해 도와주세요.')
            Notification.objects.create(
                owner=planner, notif_type=NotifType.SELF_DIAGNOSIS_LEAD,
                title='새 셀프진단 리드', body=body, customer=customer)
        except Exception:
            pass

        # 7) 응답 — PDF 있으면 neutral 결과(사실만, 부족/충분 판정 없음), 없으면 접수 확인만.
        if has_file:
            payload = _build_share_payload(customer)
            payload['lead_created'] = True
            payload['analyzed'] = True
            return Response(payload, status=status.HTTP_201_CREATED)
        return Response({'lead_created': True, 'analyzed': False}, status=status.HTTP_201_CREATED)
