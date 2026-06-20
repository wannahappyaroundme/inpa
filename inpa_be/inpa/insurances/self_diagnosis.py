"""셀프진단 인바운드 — 비로그인 잠재고객이 ?ref 설계사 링크로 본인 증권 진단.

★ 컴플라이언스 (확정 결정 + 게이트, 우회 0):
  - 제3자(잠재고객) 동의 2건 필수: ①국외이전(Claude API, 미국) ②담당 설계사에게 전달.
    하나라도 없으면 412 — OCR(Claude) 호출 전에 물리 차단.
  - 병력 미수집(증권 담보 사실만). 결과는 neutral 강제(부족/충분 판정 금지 = _build_share_payload).
  - 리드는 ref 설계사 소유 Customer(lead_source='self_diagnosis')로 생성 + 설계사 알림.
  - ★★ 유료 정식출시 전 법무 재검토 필요(G5 무작위발굴·제3자 동의 — CLAUDE.md 개발 전 게이트).

엔드포인트: POST /api/v1/d/<refcode>/  (AllowAny, multipart: file=PDF)
"""
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from inpa.accounts.models import Profile
from inpa.analytics.events import log_event
from inpa.analytics.models import NorthStarEvent
from inpa.analytics.views import _build_share_payload
from inpa.core.ocr.claude_parser import claude_parse
from inpa.customers.models import ConsentLog, Customer
from inpa.notifications.models import NotifType, Notification

from .views import (
    _MAX_UPLOAD_BYTES, _build_normalizer, _extract_pdf_lines, _persist_ocr,
)


def _truthy(v):
    return str(v).lower() in ('1', 'true', 'on', 'yes', 'y')


class SelfDiagnosisView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, refcode):
        # 1) refcode → 설계사 resolve (없으면 404 = 존재 은폐)
        profile = Profile.objects.filter(ref_code=refcode).select_related('user').first()
        if profile is None:
            return Response({'code': 'INVALID_REF', 'detail': '유효하지 않은 링크입니다.'},
                            status=status.HTTP_404_NOT_FOUND)
        planner = profile.user

        # 2) ★ 제3자 동의 게이트 (Claude 호출 전 물리 차단)
        consent_overseas = _truthy(request.data.get('consent_overseas'))
        consent_share = _truthy(request.data.get('consent_share'))
        if not (consent_overseas and consent_share):
            return Response(
                {'code': 'CONSENT_REQUIRED',
                 'detail': '증권 분석을 위해 ①국외이전(Claude, 미국) ②담당 설계사 전달 동의가 모두 필요합니다.'},
                status=status.HTTP_412_PRECONDITION_FAILED)

        # 3) 파일 검증
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

        # 4) PDF 텍스트 추출
        lines, extract_err = _extract_pdf_lines(upload)
        if extract_err == 'IMAGE_PDF':
            return Response({'code': 'IMAGE_PDF', 'detail': '전자 PDF 형식 파일로 부탁드립니다.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if extract_err:
            return Response({'code': 'PROCESSING_ERROR', 'detail': '문서 처리 중 오류가 발생했습니다.'},
                            status=status.HTTP_400_BAD_REQUEST)

        # 5) API 키
        if not getattr(settings, 'ANTHROPIC_API_KEY', ''):
            return Response({'code': 'OCR_UNAVAILABLE', 'detail': 'OCR 분석이 현재 비활성화되어 있습니다.'},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)

        # 6) Claude 파싱 (정규화 훅 주입 — 로그인과 동일)
        ocr_data = claude_parse(lines, normalizer=_build_normalizer())
        if ocr_data is None:
            return Response({'code': 'PARSE_FAILED', 'detail': '증권을 인식하지 못했습니다.'},
                            status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        # 7) 리드 Customer 생성(설계사 소유) + 동의 로그 + 포트폴리오
        ip = request.META.get('REMOTE_ADDR')
        name = (request.data.get('name') or '').strip() or '셀프진단 잠재고객'
        phone = (request.data.get('phone') or '').strip()
        with transaction.atomic():
            customer = Customer.objects.create(
                owner=planner, name=name[:20], mobile_phone_number=phone[:15],
                is_agree_term=True,                    # 담당 설계사 전달 동의
                consent_overseas_at=timezone.now(),    # 국외이전 동의 → OCR 게이트 충족
                lead_source='self_diagnosis', lead_created_at=timezone.now(),
            )
            ConsentLog.objects.create(
                customer=customer, scope=ConsentLog.SCOPE_OVERSEAS_MEDICAL,
                purpose='셀프진단 증권 OCR 국외이전(Claude, 미국)', ip=ip)
            _persist_ocr(customer, ocr_data)

        # 8) 귀속 이벤트 + 설계사 알림(리드)
        log_event(NorthStarEvent.REFERRAL_ATTRIBUTED, customer=customer, sender=planner,
                  ref_code=refcode, channel='self_diagnosis', payload={'lead': True})
        try:
            Notification.objects.create(
                owner=planner, notif_type=NotifType.SELF_DIAGNOSIS_LEAD,
                title='새 셀프진단 리드',
                body=f'{name} 잠재고객이 셀프진단을 완료했어요. CRM에서 확인하세요.',
                customer=customer)
        except Exception:
            pass

        # 9) neutral 결과(사실만) 반환 — 부족/충분 판정 없음
        payload = _build_share_payload(customer)
        payload['lead_created'] = True
        return Response(payload, status=status.HTTP_201_CREATED)
