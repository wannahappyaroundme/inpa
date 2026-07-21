"""소개 카드(공개) — 비로그인 잠재고객이 설계사 소개 링크(/p/<ref>)로 접근.

GET  /api/v1/p/<refcode>/  → 설계사 소개(이름·소속·직책·한줄소개) + 셀프진단 링크(/d).
POST /api/v1/p/<refcode>/  → '상담 신청' → 설계사 소유 db 리드 자동 생성(lead_source='introduction').

★ 레드라인: 고객 대면 = 혜택+다음 행동만. 병력/OCR/국외이전 없음(consent_overseas_at 미설정).
  상담 신청 동의는 개인정보·연락 1건(고객 본인). ref_code 해석은 셀프진단(self_diagnosis)과 동일.
"""
import re

from django.db import transaction
from django.db.models import F, Value
from django.db.models.functions import Replace
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

# 무인증 경로 — 설계사(refcode) 1명당 하루 소개 카드 상담 신청 상한(셀프진단과 동일 방어).
INTRO_DAILY_CAP_PER_REF = 30


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
        raw_phone = request.data.get('phone')
        phone_digits = re.sub(r'[^0-9]', '', raw_phone) if isinstance(raw_phone, str) else ''
        agreed = str(request.data.get('agreed')).lower() in ('1', 'true', 'on', 'yes', 'y')
        if not name:
            return Response({'code': 'NAME_REQUIRED', 'detail': '이름을 입력해 주세요.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if not re.fullmatch(r'01[0-9]{8,9}', phone_digits):
            return Response(
                {'code': 'INVALID_PHONE', 'detail': '올바른 휴대폰 번호를 입력해 주세요.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not agreed:
            return Response({'code': 'CONSENT_REQUIRED', 'detail': '개인정보 수집·연락에 동의가 필요해요.'},
                            status=status.HTTP_400_BAD_REQUEST)
        ip = request.META.get('REMOTE_ADDR')
        with transaction.atomic():
            # 같은 소개카드로 들어온 요청은 프로필 행을 잠가 중복 고객·알림 생성을 직렬화한다.
            Profile.objects.select_for_update().get(pk=profile.pk)
            # ★ refcode 일일상한(DB 카운트 — 워커 무관). 셀프진단과 동일한 무인증 남용 방어.
            #   KST 기준(§7): '오늘'은 timezone.localdate() 로 집계.
            todays_leads = Customer.objects.filter(
                owner=planner, lead_source=Customer.LEAD_INTRODUCTION,
                lead_created_at__date=timezone.localdate()).count()
            if todays_leads >= INTRO_DAILY_CAP_PER_REF:
                return Response(
                    {'code': 'DAILY_LIMIT',
                     'detail': '오늘 이 링크의 상담 신청 한도를 초과했어요. 내일 다시 시도해 주세요.'},
                    status=status.HTTP_429_TOO_MANY_REQUESTS)
            # 같은 phone+설계사 소개 리드가 이미 있으면 재사용(CRM 중복 방지).
            customer = Customer.objects.filter(
                owner=planner, lead_source=Customer.LEAD_INTRODUCTION,
            ).annotate(
                normalized_mobile_phone=Replace(F('mobile_phone_number'), Value('-'), Value('')),
            ).filter(normalized_mobile_phone=phone_digits).first()
            created = customer is None
            if customer is None:
                customer = Customer.objects.create(
                    owner=planner, name=name[:20], mobile_phone_number=phone_digits,
                    is_agree_term=True, lead_source=Customer.LEAD_INTRODUCTION,
                    lead_created_at=timezone.now())
            if created:
                ConsentLog.objects.create(
                    customer=customer, scope=ConsentLog.SCOPE_PERSONAL_INFO,
                    subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
                    purpose='소개 카드 상담 신청·연락 동의',
                    doc_version=CONSENT_TEXTS_VERSION, ip=ip)
        if created:
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
