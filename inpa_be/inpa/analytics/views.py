"""공유뷰(공개) + 북극성 이벤트 적재 API (dev/13 §1·§4, dev/06 §2.1 #7·#8).

엔드포인트:
  GET  /api/v1/s/<token>/         공유뷰 — AllowAny(비인증). 담보 한눈표 읽기전용·공유용.
                                  ★ baseline 노출 금지 = neutral 강제(부족/충분 단정 금지).
                                  면책 고지 포함. share_view 적재(viewer_fp 중복제거).
  POST /api/v1/s/<token>/event/  공유뷰 행동 적재 — AllowAny. clipboard_copy 등.
  POST /api/v1/customers/<id>/share/  공유 토큰 발급 — 인증. share_created 적재.

★ 컴플라이언스 물리강제(dev/13 §1.3 · §5.4):
  - 공유뷰는 '사실'만: 보유 담보 + 보장금액. status 는 'none'(0원) | 'neutral' 만.
    'shortage'|'adequate'|'over' 는 응답에서 물리 부재(부족/충분 단정 금지).
  - baseline(설계사 기준선) 일절 미노출.
  - 병력(민감정보)·연락처·생월일 미노출. 이름 마스킹, birth_year 만.
  - DisclaimerFooter 카피 상시 포함.
  - noindex 헤더(X-Robots-Tag) 강제.
  - 만료/회수/없는 토큰 → 데이터 0 (404).
  - 크레딧 차감 없음(비인증 공개 열람자).
"""
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django.utils import timezone

from inpa.analysis.calculate import calculate_total_analysis
from inpa.analysis.models import AnalysisCategory, AnalysisDetail, ChartDetail
from inpa.core.permissions import IsEmailVerified
from inpa.customers.models import Customer

from .events import (
    is_bot_ua, is_dedup_view, log_event, viewer_fingerprint,
)
from .models import NorthStarEvent

# 공유뷰 면책 고지 (dev/13 §1.3 · 정직성 레드라인 — "심의완료/안전" 금지, AI 면책 고정).
SHARE_DISCLAIMER = (
    '본 자료는 담당 설계사가 제공하는 1차 보조자료이며, '
    '최종 판단과 책임은 담당 설계사에게 있습니다.'
)


def _mask_name(name: str) -> str:
    """고객명 마스킹 (dev/13 §6 Q3 보수적 디폴트). '홍길동' → '홍**'."""
    if not name:
        return ''
    if len(name) == 1:
        return name
    return name[0] + '*' * (len(name) - 1)


def _birth_year(birth_day):
    """'YYYY.MM.DD' / 'YYYY-MM-DD' → 연도(int) 또는 None. 생월일은 마스킹(노출 금지)."""
    if not birth_day:
        return None
    raw = str(birth_day).replace('-', '.').strip()
    head = raw.split('.')[0]
    try:
        return int(head)
    except (ValueError, TypeError):
        return None


def _gone(reason):
    """만료/회수 응답 — 데이터 0 (dev/13 §1.1 레드라인).

    명세상 410 Gone 이 정본이나, 이번 라운드는 '없는 토큰'과 동일하게 404 로
    데이터 노출 0 을 보수적으로 강제한다(만료/회수/없음 모두 정보 0).
    """
    return Response(
        {'reason': reason, 'detail': '유효하지 않은 공유 링크입니다.'},
        status=status.HTTP_404_NOT_FOUND,
    )


class _NoIndexMixin:
    """공유뷰 응답에 noindex 헤더 강제 (dev/13 §1.2 — 민감정보 검색 색인 물리 차단)."""

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response['X-Robots-Tag'] = 'noindex, nofollow'
        return response


class ShareAnalysisView(_NoIndexMixin, APIView):
    """공유뷰 — GET /api/v1/s/<token>/ (AllowAny, 비인증).

    Customer.share_token 으로 조회(만료 share_expires_at 체크) → 담보 한눈표(히트맵)를
    ★읽기전용·공유용·neutral 강제로 반환. share_view 이벤트 적재(viewer_fp 중복제거).
    """
    permission_classes = [AllowAny]
    authentication_classes = []  # 공개 — 인증 시도 자체 없음

    def get(self, request, token):
        # ── 1) 토큰 조회 (없음/형식오류 → 404, 존재 은폐) ──────────────
        try:
            customer = Customer.objects.get(share_token=token)
        except (Customer.DoesNotExist, ValueError, Exception):
            # ValueError: 잘못된 UUID 형식. 그 외도 보수적으로 404.
            return _gone('SHARE_LINK_INVALID')

        # ── 2) 만료 체크 (share_expires_at 지났으면 데이터 0) ──────────
        if customer.share_expires_at is not None and customer.share_expires_at <= timezone.now():
            return _gone('SHARE_LINK_EXPIRED')

        # ── 3) 담보 한눈표 (neutral 강제 — baseline 미노출, 부족/충분 단정 금지) ──
        body = _build_share_payload(customer)

        # ── 4) 고객 열람 시각 갱신 ───────────────────────────────────
        customer.user_view_at = timezone.now()
        customer.save(update_fields=['user_view_at'])

        # ── 5) share_view 적재 (BE 서버측정, viewer_fp 중복/봇 가드) ──
        ua = request.META.get('HTTP_USER_AGENT', '') or ''
        fp = viewer_fingerprint(request)
        ref_code = request.query_params.get('ref') or None
        if is_bot_ua(ua):
            # 카톡 프리뷰/봇 → 신뢰 KPI 분자 제외. raw 로그만 채널 표기로 남긴다.
            log_event(NorthStarEvent.SHARE_VIEW, customer=customer, sender=customer.owner,
                      share_token=customer.share_token, ref_code=ref_code,
                      viewer_fp=fp, channel='bot',
                      payload={'ua': ua[:200], 'excluded': 'bot'})
        elif not is_dedup_view(customer.share_token, fp):
            log_event(NorthStarEvent.SHARE_VIEW, customer=customer, sender=customer.owner,
                      share_token=customer.share_token, ref_code=ref_code,
                      viewer_fp=fp, channel='web',
                      payload={'ua': ua[:200]})
        # dedup(24h 내 동일 viewer) → 적재 생략(분모 오염 방지)

        return Response(body)


def _build_share_payload(customer):
    """공유뷰 페이로드 — '사실'만(neutral 강제, baseline 부재).

    held_amount(보유 보장금액)와 status('none'|'neutral')만 노출한다.
    """
    insurance_list = list(
        customer.customer_insurance_list
        .prefetch_related('case_list__detail__analysis_detail',
                          'case_list__detail__chart_detail')
        .all()
    )

    analysis_details = list(AnalysisDetail.objects.all().values(
        'id', 'name', 'order', 'chart_based_amount', 'sub_category_id'))
    case_list = [dict(d) for d in analysis_details]
    chart_list = [dict(c) for c in ChartDetail.objects.all().values(
        'id', 'name', 'order', 'chart_based_amount', 'insurance_type', 'chart_type')]

    result = calculate_total_analysis(
        customer.birth_day, case_list, chart_list, insurance_list)
    held_by_detail_id = {c['id']: c.get('total_premium', 0) for c in result['case_list']}

    tree = []
    categories = (AnalysisCategory.objects
                  .prefetch_related('sub_categories__details')
                  .order_by('order', 'id'))
    for cat in categories:
        sub_nodes = []
        for sub in cat.sub_categories.all().order_by('order', 'id'):
            detail_nodes = []
            for det in sub.details.all().order_by('order', 'id'):
                held = held_by_detail_id.get(det.id, 0)
                # ★ 공유뷰 status: 'none'(0원=미보유 사실) | 'neutral'. 부족/충분 부재.
                cell_status = 'none' if not held else 'neutral'
                detail_nodes.append({
                    'detail_id': det.id,
                    'name': det.name,
                    'held_amount': held,
                    'status': cell_status,
                    # ⚠️ baseline 키 물리 부재 — 설계사 기준선 공유뷰 노출 금지
                })
            sub_nodes.append({
                'sub_category_id': sub.id,
                'name': sub.name,
                'details': detail_nodes,
            })
        tree.append({
            'category_id': cat.id,
            'name': cat.name,
            'insurance_type': cat.insurance_type,
            'sub_categories': sub_nodes,
        })

    summary_keys = (
        'monthly_premiums', 'monthly_renewal_premium', 'monthly_non_renewal_premium',
        'total_premiums', 'total_renewal_premium', 'total_non_renewal_premium',
    )
    summary = {k: result[k] for k in summary_keys}

    return {
        'customer': {
            'name_masked': _mask_name(customer.name),
            'gender': customer.gender,
            'birth_year': _birth_year(customer.birth_day),
            # ⚠️ mobile_phone_number/memo/medical_histories 미포함(민감정보·PII)
        },
        'mode': 'neutral',          # ★ 공유뷰는 항상 neutral
        'summary': summary,
        'tree': tree,
        'disclaimer': SHARE_DISCLAIMER,
    }


class ShareEventView(_NoIndexMixin, APIView):
    """공유뷰 행동 적재 — POST /api/v1/s/<token>/event/ (AllowAny).

    Body: {"event_type": "clipboard_copy", "channel": "clipboard", "payload": {...}}
    공유뷰에서 발생하는 비인증 행동(clipboard_copy 등)을 적재한다.

    ★ 허용 event_type: 공유뷰 발화 가능한 것만(clipboard_copy). 자동발송 사칭 금지 —
      channel='clipboard' 고정(복사≠발송, dev/13 §4).
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    # 비인증 공유뷰에서 적재 허용하는 이벤트(화이트리스트) — 임의 이벤트 위조 차단
    _PUBLIC_ALLOWED = frozenset({NorthStarEvent.CLIPBOARD_COPY})

    def post(self, request, token):
        try:
            customer = Customer.objects.get(share_token=token)
        except (Customer.DoesNotExist, ValueError, Exception):
            return _gone('SHARE_LINK_INVALID')

        if customer.share_expires_at is not None and customer.share_expires_at <= timezone.now():
            return _gone('SHARE_LINK_EXPIRED')

        event_type = request.data.get('event_type', NorthStarEvent.CLIPBOARD_COPY)
        if event_type not in self._PUBLIC_ALLOWED:
            return Response(
                {'detail': '허용되지 않은 이벤트입니다.', 'code': 'EVENT_NOT_ALLOWED'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        fp = viewer_fingerprint(request)
        ref_code = request.query_params.get('ref') or None
        # ★ clipboard_copy 는 channel='clipboard' 고정(자동발송 사칭 금지).
        log_event(
            event_type, customer=customer, sender=customer.owner,
            share_token=customer.share_token, ref_code=ref_code,
            viewer_fp=fp, channel='clipboard',
            payload={'delivery': 'clipboard'},
        )
        return Response({'status': 'logged', 'event_type': event_type},
                        status=status.HTTP_201_CREATED)


class CustomerShareCreateView(APIView):
    """공유 토큰 발급 — POST /api/v1/customers/<customer_pk>/share/ (인증·소유자).

    Customer.share_token 을 rotate(재발급)하고 share_expires_at=now+TTL 을 설정한다.
    구 token 은 즉시 무효(새 UUID 발급). share_created 이벤트 적재(발송=곱셈 1항).

    ★ owner 격리: 본인 고객이 아니면 404(존재 은폐).
    크레딧 차감 없음(share_link 는 북극성 차단 금지 대상 — dev/23 §1.2).
    """
    permission_classes = [IsAuthenticated, IsEmailVerified]

    # TTL 기본값 90일(dev/13 §6 Q1 디폴트 — 영구노출 방지 vs 재발송 마찰 균형)
    SHARE_TTL_DAYS = 90

    def _is_admin(self):
        profile = getattr(self.request.user, 'profile', None)
        return bool(getattr(profile, 'is_admin', False))

    def _get_customer(self, customer_pk):
        from rest_framework.exceptions import NotFound
        qs = Customer.objects.all()
        if not self._is_admin():
            qs = qs.filter(owner=self.request.user)
        try:
            return qs.get(pk=customer_pk)
        except Customer.DoesNotExist:
            raise NotFound('고객을 찾을 수 없습니다.')

    def post(self, request, customer_pk):
        import uuid
        from datetime import timedelta

        customer = self._get_customer(customer_pk)

        # rotate — 새 UUID 발급(구 token 즉시 무효) + TTL 설정 + 발송 시각 기록
        customer.share_token = uuid.uuid4()
        customer.share_expires_at = timezone.now() + timedelta(days=self.SHARE_TTL_DAYS)
        customer.share_sent_at = timezone.now()
        customer.save(update_fields=['share_token', 'share_expires_at', 'share_sent_at'])

        # 발급한 설계사의 ref_code 동반 기록(귀속 매칭 근간)
        profile = getattr(request.user, 'profile', None)
        ref_code = getattr(profile, 'ref_code', None)

        log_event(
            NorthStarEvent.SHARE_CREATED, customer=customer, sender=request.user,
            share_token=customer.share_token, ref_code=ref_code, channel='web',
            payload={'customer_id': customer.id, 'ttl_days': self.SHARE_TTL_DAYS},
        )

        return Response({
            'customer_id': customer.id,
            'share_token': str(customer.share_token),
            'share_expires_at': customer.share_expires_at.isoformat(),
            'share_url': f'/s/{customer.share_token}',
        }, status=status.HTTP_201_CREATED)
