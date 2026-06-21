"""고객 본인 국외이전 동의 — 공개(비로그인) 경로 (P3c).

설계사가 만든 동의요청 링크(/c/<token>)를 고객이 본인 기기에서 연다.
  GET  /api/v1/c/<token>/  → 최소 고지(마스킹 이름·설계사 소속·고지문)
  POST /api/v1/c/<token>/  → consent_overseas=true 시 ConsentLog(customer_self) + 게이트 해제

★ 컴플라이언스: 정보주체 본인 동의만 국외이전 게이트(consent_overseas_at)를 연다.
  마스킹 외 PII(전화·생년·병력·메모) 미반환. noindex. 멱등(기존 동의 비파괴).
  유료 정식출시 전 법무 재검토 필요.
"""
from django.core import signing
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from inpa.analytics.views import _NoIndexMixin, _mask_name

from .models import ConsentLog, Customer
from .tokens import read_consent_token

_SCOPE_TEXT = '보험증권 분석을 위한 정보의 국외이전(Claude API, 미국 소재 Anthropic)'
_PURPOSE_TEXT = ('업로드하신 보험증권의 텍스트를 AI로 분석·정규화하기 위해 미국 소재 '
                 'Anthropic(Claude API)으로 전송·처리됩니다. 처리 완료 후 별도 저장하지 않습니다.')
_DISCLAIMER = ('본 동의는 보험증권 분석을 위한 국외이전에 한합니다. AI 분석 결과는 보조 자료이며, '
               '최종 판단과 책임은 담당 설계사에게 있습니다.')


def _truthy(v):
    return str(v).lower() in ('1', 'true', 'on', 'yes', 'y')


class PublicConsentView(_NoIndexMixin, APIView):
    """고객 본인 동의 — AllowAny + noindex + throttle. self_diagnosis.py 패턴."""
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'consent_public'

    def _resolve(self, token):
        """토큰 → Customer. 만료=410, 위조/없음=404(존재 은폐). (customer, err_response)."""
        try:
            pk = read_consent_token(token)
        except signing.SignatureExpired:
            return None, Response(
                {'code': 'LINK_EXPIRED',
                 'detail': '동의 링크가 만료됐어요. 담당 설계사에게 새 링크를 요청해 주세요.'},
                status=status.HTTP_410_GONE)
        except signing.BadSignature:
            return None, Response(
                {'code': 'LINK_INVALID', 'detail': '유효하지 않은 링크입니다.'},
                status=status.HTTP_404_NOT_FOUND)
        customer = Customer.objects.filter(pk=pk).select_related('owner__profile').first()
        if customer is None:
            return None, Response(
                {'code': 'LINK_INVALID', 'detail': '유효하지 않은 링크입니다.'},
                status=status.HTTP_404_NOT_FOUND)
        return customer, None

    def get(self, request, token):
        customer, err = self._resolve(token)
        if err is not None:
            return err
        profile = getattr(customer.owner, 'profile', None)
        affiliation = getattr(profile, 'affiliation', '') or ''
        return Response({
            'customer': {'name_masked': _mask_name(customer.name)},
            'planner': {'affiliation': affiliation},
            'already_consented': customer.consent_overseas_at is not None,
            'scope_text': _SCOPE_TEXT,
            'purpose_text': _PURPOSE_TEXT,
            'disclaimer': _DISCLAIMER,
        })

    def post(self, request, token):
        customer, err = self._resolve(token)
        if err is not None:
            return err
        if not _truthy(request.data.get('consent_overseas')):
            return Response(
                {'code': 'CONSENT_REQUIRED',
                 'detail': '국외이전(Claude API, 미국) 동의가 필요합니다.'},
                status=status.HTTP_412_PRECONDITION_FAILED)
        ip = request.META.get('REMOTE_ADDR')
        with transaction.atomic():
            log = ConsentLog.objects.create(
                customer=customer, scope=ConsentLog.SCOPE_OVERSEAS_MEDICAL,
                subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
                purpose='고객 본인 국외이전 동의(Claude API, 미국)', ip=ip)
            # 멱등 — 기존 동의 시각은 덮지 않는다(append-only 정신).
            if customer.consent_overseas_at is None:
                customer.consent_overseas_at = log.agreed_at
                customer.save(update_fields=['consent_overseas_at'])
        return Response(
            {'consented': True, 'consented_at': customer.consent_overseas_at},
            status=status.HTTP_201_CREATED)
