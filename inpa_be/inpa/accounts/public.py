"""소개 카드(공개) — 비로그인 잠재고객이 설계사 소개 링크(/p/<ref>)로 접근.

GET  /api/v1/p/<refcode>/  → 설계사 소개(이름·소속·직책·한줄소개) + 셀프진단 링크(/d).
POST /api/v1/p/<refcode>/  → '상담 신청' → 설계사 소유 db 리드 자동 생성(lead_source='introduction').

★ 레드라인: 고객 대면 = 혜택+다음 행동만. 병력/OCR/국외이전 없음(consent_overseas_at 미설정).
  상담 신청 동의는 개인정보·연락 1건(고객 본인). ref_code 해석은 셀프진단(self_diagnosis)과 동일.
"""
import re

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from inpa.accounts.models import Profile
from inpa.analytics.events import log_event
from inpa.analytics.models import NorthStarEvent
from inpa.analytics.views import _NoIndexMixin
from inpa.customers.consent_texts import CONSENT_TEXTS_VERSION
from inpa.customers.models import ConsentLog, Customer
from inpa.notifications.models import NotifType, Notification


def _planner_name(profile):
    return (profile.name or '').strip() or (profile.affiliation or '').strip() or '담당 설계사'


class IntroductionCardView(_NoIndexMixin, APIView):
    """설계사 소개 카드(공개) — GET 카드 데이터 / POST 상담 신청(db 리드 생성)."""
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'self_diagnosis'  # 무인증 비용/남용 방어 — 셀프진단과 동일 버킷

    def _resolve(self, refcode):
        return Profile.objects.filter(ref_code=refcode).select_related('user').first()

    def get(self, request, refcode):
        profile = self._resolve(refcode)
        if profile is None:
            return Response({'code': 'INVALID_REF', 'detail': '유효하지 않은 링크입니다.'},
                            status=status.HTTP_404_NOT_FOUND)
        return Response({
            'planner': {
                'name': _planner_name(profile),
                'affiliation': (profile.affiliation or '').strip(),
                'title': (profile.title or '').strip(),
                'intro_text': (profile.intro_text or '').strip(),
            },
            'self_diagnosis_url': f'/d/{refcode}',
        })

    def post(self, request, refcode):
        profile = self._resolve(refcode)
        if profile is None:
            return Response({'code': 'INVALID_REF', 'detail': '유효하지 않은 링크입니다.'},
                            status=status.HTTP_404_NOT_FOUND)
        planner = profile.user
        name = (request.data.get('name') or '').strip()
        phone = re.sub(r'[^0-9-]', '', (request.data.get('phone') or '').strip())
        agreed = str(request.data.get('agreed')).lower() in ('1', 'true', 'on', 'yes', 'y')
        if not name:
            return Response({'code': 'NAME_REQUIRED', 'detail': '이름을 입력해 주세요.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if not agreed:
            return Response({'code': 'CONSENT_REQUIRED', 'detail': '개인정보 수집·연락에 동의가 필요해요.'},
                            status=status.HTTP_400_BAD_REQUEST)
        ip = request.META.get('REMOTE_ADDR')
        with transaction.atomic():
            # 같은 phone+설계사 소개 리드가 이미 있으면 재사용(CRM 중복 방지).
            customer = None
            if phone:
                customer = Customer.objects.filter(
                    owner=planner, lead_source=Customer.LEAD_INTRODUCTION,
                    mobile_phone_number=phone[:15]).first()
            if customer is None:
                customer = Customer.objects.create(
                    owner=planner, name=name[:20], mobile_phone_number=phone[:15],
                    is_agree_term=True, lead_source=Customer.LEAD_INTRODUCTION,
                    lead_created_at=timezone.now())
            ConsentLog.objects.create(
                customer=customer, scope=ConsentLog.SCOPE_PERSONAL_INFO,
                subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
                purpose='소개 카드 상담 신청·연락 동의',
                doc_version=CONSENT_TEXTS_VERSION, ip=ip)
        log_event(NorthStarEvent.REFERRAL_ATTRIBUTED, customer=customer, sender=planner,
                  ref_code=refcode, channel='intro_card', payload={'lead': True})
        try:
            Notification.objects.create(
                owner=planner, notif_type=NotifType.SELF_DIAGNOSIS_LEAD,
                title='새 상담 신청',
                body=f'{name}님이 소개 카드에서 상담을 신청했어요. 고객 목록에서 확인하세요.',
                customer=customer)
        except Exception:
            pass
        return Response({'lead_created': True}, status=status.HTTP_201_CREATED)
