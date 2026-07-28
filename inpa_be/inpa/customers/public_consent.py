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
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from inpa.analytics.views import _NoIndexMixin, _mask_name

from .consent_texts import (
    CONSENT_TEXTS,
    CONSENT_TEXTS_VERSION,
    CONSULTATION_CONSENT_VERSIONS,
    CONSULTATION_SUMMARY_CONSENT_VERSION,
    consent_version_for_scope,
    consent_lines,
    has_current_overseas_consent,
    lock_customer_consent_state,
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
    ConsentLog.SCOPE_CONSULTATION_RECORDING: {
        'required': True,
        'purpose': '상담 녹음과 원본 보관 동의(고객 본인)',
        'notice': '녹음 파일은 상담을 마치고 30일 동안 보관한 뒤 자동 삭제됩니다.',
    },
    ConsentLog.SCOPE_CONSULTATION_SENSITIVE: {
        'required': True,
        'purpose': '상담 중 민감정보 처리 동의(고객 본인)',
        'notice': '건강 등 민감한 내용은 상담 메모 작성 목적으로 처리됩니다.',
    },
    ConsentLog.SCOPE_CONSULTATION_OVERSEAS_SUMMARY: {
        'required': True,
        'purpose': '상담 요약을 위한 국외 처리 동의(고객 본인)',
        'notice': '이름과 연락처를 가린 상담 내용을 요약하는 데 사용됩니다.',
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
        if scope in CONSULTATION_CONSENT_VERSIONS:
            return ConsentLog.objects.filter(
                customer=customer,
                scope=scope,
                subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
                revoked_at__isnull=True,
                doc_version=CONSULTATION_CONSENT_VERSIONS[scope],
            ).exists()
        if scope == ConsentLog.SCOPE_CONSULTATION_OVERSEAS_SUMMARY:
            return ConsentLog.objects.filter(
                customer=customer,
                scope=scope,
                subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
                revoked_at__isnull=True,
                doc_version=CONSULTATION_SUMMARY_CONSENT_VERSION,
            ).exists()
        return ConsentLog.objects.filter(
            customer=customer, scope=scope, revoked_at__isnull=True).exists()

    def _revocable(self, customer, scope):
        """철회 가능 = 살아있는(unrevoked) 로그가 하나라도 있는가 — subject·버전 불문.

        already(국외이전은 현재 버전 본인 동의만 True)와 기준이 다르다: 구버전 동의나
        설계사 대리(planner_attested) 기록도 정보주체가 철회할 수 있어야 한다(PIPA 철회권).
        """
        return ConsentLog.objects.filter(
            customer=customer, scope=scope, revoked_at__isnull=True).exists()

    def _apply_revocations(self, customer, scopes_to_revoke, ip):
        """철회 실행 — 해당 scope의 모든 unrevoked ConsentLog(subject 불문)에
        revoked_at/revoke_ip 스탬프. 재철회는 0건 갱신(멱등). 국외이전 철회 시
        Customer.consent_overseas_at 스냅샷도 함께 비워 표시(동의 완료 배지)·게이트가
        일관되게 '미동의' 상태로 돌아간다(이미 저장된 분석 자료는 그대로 유지).

        ★ personal_info(개인정보 수집·이용) 철회 = "내 정보 보관을 중단해 달라"는
        요청이므로, 그 고객의 공유(/s) 기록(ShareSnapshot)도 함께 즉시 파기한다
        (spec 2026-07-08). 다른 scope(overseas_medical 등) 철회는 공유 기록과
        무관해 보존한다.
        """
        now = timezone.now()
        results = []
        delete_consultation_sources = False
        cancel_consultation_summaries = False
        for sc in scopes_to_revoke:
            updated = ConsentLog.objects.filter(
                customer=customer, scope=sc, revoked_at__isnull=True,
            ).update(revoked_at=now, revoke_ip=ip)
            if sc == ConsentLog.SCOPE_OVERSEAS_MEDICAL and customer.consent_overseas_at is not None:
                customer.consent_overseas_at = None
                customer.save(update_fields=['consent_overseas_at'])
            if sc == ConsentLog.SCOPE_PERSONAL_INFO:
                from inpa.analytics.models import ShareSnapshot
                ShareSnapshot.objects.filter(customer=customer).delete()
                # gate OFF 전환 기간의 Customer 토큰 fallback도 즉시 닫는다.
                customer.share_expires_at = now
                customer.save(update_fields=['share_expires_at'])
            if sc in {
                ConsentLog.SCOPE_CONSULTATION_RECORDING,
                ConsentLog.SCOPE_CONSULTATION_SENSITIVE,
            }:
                delete_consultation_sources = True
            if sc in {
                ConsentLog.SCOPE_CONSULTATION_RECORDING,
                ConsentLog.SCOPE_CONSULTATION_SENSITIVE,
                ConsentLog.SCOPE_CONSULTATION_OVERSEAS_SUMMARY,
            }:
                cancel_consultation_summaries = True
            results.append({'scope': sc, 'revoked': True, 'updated_logs': updated})
        if cancel_consultation_summaries:
            from inpa.consultations.tasks import cancel_customer_summaries
            transaction.on_commit(
                lambda customer_id=customer.id: cancel_customer_summaries.delay(
                    customer_id,
                    reason='CONSENT_REVOKED',
                ),
            )
        if delete_consultation_sources:
            from inpa.consultations.tasks import delete_customer_sources
            transaction.on_commit(
                lambda customer_id=customer.id: delete_customer_sources.delay(
                    customer_id,
                    reason='consent_revoked',
                ),
            )
        return results

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
            # 철회 가능 여부(살아있는 동의 존재) — FE가 '동의 철회' 버튼 노출 판단에 사용.
            'revocable': self._revocable(customer, sc),
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

        # 철회(revoked) — agreed와 동일 원칙: 토큰 밖 scope 무시(위조 가드).
        # agreed에도 함께 온 scope는 철회 목록에서 제외(철회→재동의를 한 요청에서 하려는
        # 의도가 아니라 충돌 입력으로 보고, 동의 유지가 안전한 해석).
        revoked = request.data.get('revoked') or []
        if not isinstance(revoked, list):
            revoked = []
        revoked = [s for s in revoked if s in scopes and s not in agreed]

        pure_revoke = bool(revoked) and not agreed

        ip = request.META.get('REMOTE_ADDR')
        with transaction.atomic():
            locked_customer = lock_customer_consent_state(
                customer_id=customer.id,
            )
            if locked_customer is None:
                return Response(
                    {
                        'code': 'LINK_INVALID',
                        'detail': '유효하지 않은 링크입니다.',
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

            # 필수 미동의 412는 '동의 제출'에만 적용. 철회 전용 요청은
            # 필수 항목도 철회할 수 있어야 하므로 통과시킨다.
            if not pure_revoke:
                required = [
                    scope for scope in scopes
                    if _SCOPE_META[scope]['required']
                ]
                missing = [
                    scope for scope in required
                    if scope not in agreed
                    and not self._already(locked_customer, scope)
                ]
                if missing:
                    return Response(
                        {
                            'code': 'CONSENT_REQUIRED',
                            'detail': '필수 동의 항목에 동의가 필요합니다.',
                        },
                        status=status.HTTP_412_PRECONDITION_FAILED,
                    )

            results = []
            revoked_results = self._apply_revocations(
                locked_customer,
                revoked,
                ip,
            )
            for sc in agreed:
                if self._already(locked_customer, sc):
                    results.append({'scope': sc, 'consented': True, 'agreed_at': None})
                    continue
                log = ConsentLog.objects.create(
                    customer=locked_customer, scope=sc,
                    subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
                    purpose=_SCOPE_META[sc]['purpose'],
                    doc_version=consent_version_for_scope(sc), ip=ip)
                if (sc == ConsentLog.SCOPE_OVERSEAS_MEDICAL
                        and locked_customer.consent_overseas_at is None):
                    locked_customer.consent_overseas_at = log.agreed_at
                    locked_customer.save(update_fields=['consent_overseas_at'])
                results.append({'scope': sc, 'consented': True, 'agreed_at': log.agreed_at})
            all_required_done = all(
                self._already(locked_customer, scope)
                for scope in scopes if _SCOPE_META[scope]['required']
            )
        return Response(
            {'results': results, 'revoked': revoked_results,
             'all_required_done': all_required_done},
            status=status.HTTP_200_OK if pure_revoke else status.HTTP_201_CREATED)


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
