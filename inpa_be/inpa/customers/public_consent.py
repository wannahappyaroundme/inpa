"""고객 본인 동의 — 공개(비로그인) 다항목 경로 (P3c).

설계사가 만든 동의요청 링크(/c/<token>)를 고객이 본인 기기에서 연다. 토큰에 담긴
요청 scope만 고지·수집한다(개인정보 수집·이용 / 마케팅 수신 / 병력 국외이전).
  GET  /api/v1/c/<token>/  → 요청 항목 고지(필수/선택·고지문·이미 동의 여부)
  POST /api/v1/c/<token>/  → {agreed:[scope]} 동의 scope마다 ConsentLog(customer_self) 생성

★ 컴플라이언스: 정보주체 본인 동의만 기록. 필수(개인정보·국외이전) 미동의 시 412.
  마스킹 외 PII 미반환. noindex. 멱등(기존 동의 비파괴). 유료 전 법무 재검토.
"""
from django.core import signing
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from inpa.analytics.views import _NoIndexMixin, _mask_name

from .consent_texts import (
    CONSENT_TEXTS,
    CONSENT_TEXTS_VERSION,
    consent_lines,
    has_current_overseas_consent,
)
from .models import ConsentLog, Customer
from .tokens import read_consent_token

_DISCLAIMER = ('AI 분석 결과는 보조 자료이며, 최종 판단과 책임은 담당 설계사에게 있습니다. '
               '인파는 보험을 중개·권유하지 않습니다.')

# scope별 고지 메타 — 필수 여부/목적/안내만 여기서, 고지문(title·lines)은 consent_texts 단일 소스.
_SCOPE_META = {
    ConsentLog.SCOPE_PERSONAL_INFO: {
        'required': True,
        'purpose': '개인정보 수집·이용 동의(고객 본인)',
        'notice': '동의를 거부하실 수 있으며, 거부 시 상담 진행이 제한될 수 있어요.',
    },
    ConsentLog.SCOPE_MARKETING: {
        'required': False,
        'purpose': '마케팅·광고 정보 수신 동의(고객 본인)',
        'notice': '거부하셔도 상담·계약에는 영향이 없어요. 언제든 수신을 거부할 수 있어요.',
    },
    ConsentLog.SCOPE_OVERSEAS_MEDICAL: {
        'required': True,
        'purpose': '고객 본인 국외이전 동의(Claude API, 미국)',
        'notice': '증권 분석을 위한 국외이전에 한합니다.',
    },
}


class PublicConsentView(_NoIndexMixin, APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'consent_public'

    def _resolve(self, token):
        """토큰 → (customer, scopes, err). 만료=410, 위조/없음=404(존재 은폐)."""
        try:
            data = read_consent_token(token)
        except signing.SignatureExpired:
            return None, None, Response(
                {'code': 'LINK_EXPIRED',
                 'detail': '동의 링크가 만료됐어요. 담당 설계사에게 새 링크를 요청해 주세요.'},
                status=status.HTTP_410_GONE)
        except signing.BadSignature:
            return None, None, Response(
                {'code': 'LINK_INVALID', 'detail': '유효하지 않은 링크입니다.'},
                status=status.HTTP_404_NOT_FOUND)
        scopes = [s for s in data.get('scopes', []) if s in _SCOPE_META]
        customer = Customer.objects.filter(pk=data['pk']).select_related('owner__profile').first()
        if customer is None or not scopes:
            return None, None, Response(
                {'code': 'LINK_INVALID', 'detail': '유효하지 않은 링크입니다.'},
                status=status.HTTP_404_NOT_FOUND)
        return customer, scopes, None

    def _already(self, customer, scope):
        # 이미 동의 = unrevoked 로그 존재. serializers._consent_state는 latest만 쓰므로 동의→철회→재요청 후 불일치 가능(beta YAGNI).
        # 국외이전은 '현재 버전 문구로 받은 본인 동의'만 완료로 본다 → 구버전 동의 고객은 재동의(재-agree)가 가능해야 게이트가 열림.
        if scope == ConsentLog.SCOPE_OVERSEAS_MEDICAL:
            return has_current_overseas_consent(customer)
        return ConsentLog.objects.filter(
            customer=customer, scope=scope, revoked_at__isnull=True).exists()

    def get(self, request, token):
        customer, scopes, err = self._resolve(token)
        if err is not None:
            return err
        profile = getattr(customer.owner, 'profile', None)
        affiliation = getattr(profile, 'affiliation', '') or ''
        items = [{
            'scope': sc,
            'title': CONSENT_TEXTS[sc]['title'],
            'required': _SCOPE_META[sc]['required'],
            'already': self._already(customer, sc),
            'lines': consent_lines(sc),
            'notice': _SCOPE_META[sc]['notice'],
        } for sc in scopes]
        all_required_done = bool(items) and all(
            it['already'] for it in items if it['required'])
        return Response({
            'customer': {'name_masked': _mask_name(customer.name)},
            'planner': {'affiliation': affiliation},
            'items': items,
            'all_required_done': all_required_done,
            'disclaimer': _DISCLAIMER,
        })

    def post(self, request, token):
        customer, scopes, err = self._resolve(token)
        if err is not None:
            return err
        agreed = request.data.get('agreed') or []
        if not isinstance(agreed, list):
            agreed = []
        agreed = [s for s in agreed if s in scopes]  # 토큰 밖 scope 무시(위조 방지)

        required = [s for s in scopes if _SCOPE_META[s]['required']]
        missing = [s for s in required if s not in agreed and not self._already(customer, s)]
        if missing:
            return Response(
                {'code': 'CONSENT_REQUIRED', 'detail': '필수 동의 항목에 동의가 필요합니다.'},
                status=status.HTTP_412_PRECONDITION_FAILED)

        ip = request.META.get('REMOTE_ADDR')
        results = []
        with transaction.atomic():
            for sc in agreed:
                if self._already(customer, sc):
                    results.append({'scope': sc, 'consented': True, 'agreed_at': None})
                    continue
                log = ConsentLog.objects.create(
                    customer=customer, scope=sc,
                    subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
                    purpose=_SCOPE_META[sc]['purpose'],
                    doc_version=CONSENT_TEXTS_VERSION, ip=ip)
                if (sc == ConsentLog.SCOPE_OVERSEAS_MEDICAL
                        and customer.consent_overseas_at is None):
                    customer.consent_overseas_at = log.agreed_at
                    customer.save(update_fields=['consent_overseas_at'])
                results.append({'scope': sc, 'consented': True, 'agreed_at': log.agreed_at})
        return Response({'results': results, 'all_required_done': True},
                        status=status.HTTP_201_CREATED)


class ConsentTextsView(_NoIndexMixin, APIView):
    """공개 동의 고지문 단일 소스 — GET /api/v1/consent-texts/.

    화면(설계사 /c, 셀프진단 /d, OCR 업로드 모달)이 최신 문구를 서버에서 받아 렌더한다.
    FE는 실패 시 v2 문구로 로컬 폴백(옛 문구는 절대 쓰지 않음).
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'share_public'

    def get(self, request):
        return Response({'version': CONSENT_TEXTS_VERSION, 'texts': CONSENT_TEXTS})
