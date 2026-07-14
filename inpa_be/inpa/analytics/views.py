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
import logging

from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.response import Response
from rest_framework.views import APIView

from django.utils import timezone
from django.conf import settings

from inpa.analysis.calculate import calculate_total_analysis
from inpa.analysis.models import AnalysisCategory, AnalysisDetail, ChartDetail
from inpa.booking.models import WorkHour
from inpa.booking.tokens import make_booking_token
from inpa.core.copyguard import warn_if_advice_words
from inpa.core.permissions import IsEmailVerified
from inpa.customers.consent_texts import CONSENT_TEXTS_VERSION, has_current_overseas_consent
from inpa.customers.models import Customer

from .events import (
    is_bot_ua, is_dedup_view, log_event, viewer_fingerprint,
)
from .models import NorthStarEvent, ShareSnapshot

logger = logging.getLogger(__name__)

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
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'share_public'  # DB write/연산 증폭 DoS 방어(유포된 링크 1개로 반복호출 차단)

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


def _booking_url(customer):
    """'바로 상담 예약' CTA 링크 — 예약 가능할 때만 고객용 /b 링크를 신선하게 발급.

    BOOKING_ENABLED + 설계사(owner)에게 영업시간(WorkHour)이 있을 때만 발급한다.
    응답이 요청 시점마다 새로 만들어지므로 토큰 72h TTL 무관(고객이 보는 순간 유효).
    조건 미충족이면 None → 페이로드에서 키 부재 → FE는 기존 안내문으로 폴백.
    """
    if not getattr(settings, 'BOOKING_ENABLED', True):
        return None
    if not customer.owner_id or not WorkHour.objects.filter(owner_id=customer.owner_id).exists():
        return None
    base = (getattr(settings, 'FRONTEND_BASE_URL', '') or '').rstrip('/')
    return f'{base}/b/{make_booking_token(customer)}'


def _planner_phone(customer):
    """설계사 연락처(전화번호) — 공유뷰 '전화하기/문자하기' 버튼용. 없으면 None.

    2026-07-07: Profile.phone 실필드 신설(마이페이지 입력) → 프로브 1순위 'phone'이 감지해
    값이 있으면 planner_contact 가 자동으로 채워진다. 비어 있으면 None
    (호출부·FE는 null 처리 완비 — 키는 항상 존재, 값만 채워짐).
    """
    profile = getattr(customer.owner, 'profile', None)
    if profile is None:
        return None
    for attr in ('phone', 'phone_number', 'mobile_phone_number', 'contact_phone'):
        value = (getattr(profile, attr, '') or '').strip()
        if value:
            return value
    return None


def build_coverage_tree(customer, insurance_list, held_only=False):
    """주어진 보험 리스트만 집계한 담보 트리 + 합계 — '사실'만(neutral 강제, baseline 부재).

    공유뷰(/s)·셀프진단(/d)이 공유하는 단일 트리 빌더. held_amount(보유 보장금액)와
    status('none'|'neutral')만 노출한다(부족/충분 단정 물리 부재).

    held_only=True 면 보유(held>0) 담보만 남기고 빈 소분류/대분류를 가지치기한 트리
    (셀프진단 보험별 카드 상세용 — 그 보험이 실제 보장하는 담보 리스트).
    Returns (tree, summary).
    """
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
                if held_only and not held:
                    continue
                # ★ 공유뷰 status: 'none'(0원=미보유 사실) | 'neutral'. 부족/충분 부재.
                cell_status = 'none' if not held else 'neutral'
                detail_nodes.append({
                    'detail_id': det.id,
                    'name': det.name,
                    'held_amount': held,
                    'status': cell_status,
                    # ⚠️ baseline 키 물리 부재 — 설계사 기준선 공유뷰 노출 금지
                })
            if held_only and not detail_nodes:
                continue
            sub_nodes.append({
                'sub_category_id': sub.id,
                'name': sub.name,
                'details': detail_nodes,
            })
        if held_only and not sub_nodes:
            continue
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
    return tree, summary


def _build_share_payload(customer):
    """공유뷰 페이로드 — '사실'만(neutral 강제, baseline 부재).

    held_amount(보유 보장금액)와 status('none'|'neutral')만 노출한다.
    """
    #    ★ portfolio_type=1(보유)만 — 제안(2)/템플릿(0)이 고객 공유뷰·스냅샷에 '보유'로
    #    섞이지 않게 한다(dashboard/aggregation·churn·manager 와 동일 규칙).
    insurance_list = list(
        customer.customer_insurance_list
        .filter(portfolio_type=1)
        .prefetch_related('case_list__detail__analysis_detail',
                          'case_list__detail__chart_detail')
        .all()
    )
    tree, summary = build_coverage_tree(customer, insurance_list)

    payload = {
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
        # 담당 설계사 전화번호(없으면 null) — '전화하기/문자하기' 연락 레이어용(LB#8).
        'planner_contact': _planner_phone(customer),
    }
    # ★ '바로 상담 예약' CTA — 예약 가능할 때만 booking_url 포함(없으면 키 부재 → FE 폴백).
    booking_url = _booking_url(customer)
    if booking_url:
        payload['booking_url'] = booking_url
    # ★ 권유 단어 서버측 가드(#23, §97·금소법) — 고정 카피 필드만 검사(로그 관측, 화면은 유지).
    #   공유뷰(/s)와 셀프진단(/d, self_diagnosis.py 가 이 함수를 재사용)의 고정 카피를 함께 커버.
    #   데이터 필드(고객명·담보명·금액)는 검사하지 않는다(오탐 방지).
    warn_if_advice_words({'disclaimer': payload['disclaimer']}, where='share_payload')
    return payload


def _current_consent_scopes(customer):
    """캡처 시점 유효(미철회) 고객 본인(customer_self) 동의 scope 목록 — 스냅샷 감사용."""
    from inpa.customers.models import ConsentLog
    return list(
        ConsentLog.objects.filter(
            customer=customer,
            subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
            revoked_at__isnull=True,
        ).values_list('scope', flat=True).distinct()
    )


def _current_dict_version():
    """정규화 사전 버전 — SeedMarker(seed_normalization) 라이브 값 우선, 없으면 코드 SEED_VERSION."""
    from inpa.analysis.models import SeedMarker
    live = (SeedMarker.objects.filter(key='seed_normalization')
            .values_list('version', flat=True).first())
    if live:
        return live
    try:
        from inpa.analysis.management.commands.seed_normalization import SEED_VERSION
        return SEED_VERSION
    except Exception:  # noqa: BLE001 — 임포트 실패해도 스냅샷 캡처는 계속돼야 함
        return ''


class ShareEventView(_NoIndexMixin, APIView):
    """공유뷰 행동 적재 — POST /api/v1/s/<token>/event/ (AllowAny).

    Body: {"event_type": "clipboard_copy", "channel": "clipboard", "payload": {...}}
    공유뷰에서 발생하는 비인증 행동(clipboard_copy 등)을 적재한다.

    ★ 허용 event_type: 공유뷰 발화 가능한 것만(clipboard_copy). 자동발송 사칭 금지 —
      channel='clipboard' 고정(복사≠발송, dev/13 §4).
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'share_public'  # 무제한 NorthStarEvent 적재(KPI 오염·디스크 소모) 방어

    # 비인증 공유뷰에서 적재 허용하는 이벤트(화이트리스트) — 임의 이벤트 위조 차단
    _PUBLIC_ALLOWED = frozenset({NorthStarEvent.CLIPBOARD_COPY,
                                 NorthStarEvent.CALLBACK_REQUEST,
                                 NorthStarEvent.CTA_CLICK})

    def _notify_callback(self, customer):
        """콜백(연락 요청) → 설계사 알림 1건. 같은 공유건은 하루(KST) 1회만(중복 방지).

        ★ 새 NotifType 추가 금지(메뉴 배지 파티션 유지) — SELF_DIAGNOSIS_LEAD 재사용
          (고객 메뉴 배지로 귀속). dedupe 1차 = 같은 share_token의 오늘(KST) 선행
          callback_request 이벤트 존재 검사(호출부에서 log_event 이전에 판정), 2차 =
          Notification 부분 유니크 제약(owner+type+target_date+customer) IntegrityError 흡수.
        """
        from django.db import IntegrityError, transaction

        from inpa.notifications.models import NotifType, Notification
        try:
            with transaction.atomic():
                Notification.objects.create(
                    owner=customer.owner, notif_type=NotifType.SELF_DIAGNOSIS_LEAD,
                    title='고객 연락 요청',
                    body=f'{customer.name}님이 보장 안내 화면에서 연락을 요청했어요. '
                         f'전화 한 통으로 이어가 보세요.',
                    customer=customer, target_date=timezone.localdate())
        except IntegrityError:
            pass  # 같은 고객·같은 날 알림이 이미 있음 — 1건으로 수렴
        except Exception:
            pass  # 알림 실패가 공개 응답을 깨지 않게 격리(이벤트 로그는 이미 적재)

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

        if event_type == NorthStarEvent.CALLBACK_REQUEST:
            # 알림 dedupe 판정은 이벤트 적재 '이전'의 오늘(KST) 선행 이벤트 기준 —
            # 이벤트 로그는 매번 기록하되 알림은 같은 공유건당 하루 1회.
            day_start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
            already_today = NorthStarEvent.objects.filter(
                event_type=NorthStarEvent.CALLBACK_REQUEST,
                share_token=customer.share_token,
                created_at__gte=day_start).exists()
            log_event(
                event_type, customer=customer, sender=customer.owner,
                share_token=customer.share_token, ref_code=ref_code,
                viewer_fp=fp, channel='web',
                payload={'source': 'share_view'},
            )
            if not already_today:
                self._notify_callback(customer)
            return Response({'status': 'logged', 'event_type': event_type},
                            status=status.HTTP_201_CREATED)

        if event_type == NorthStarEvent.CTA_CLICK:
            # 분석→예약 CTA 클릭 — channel='web'(콜백과 동일, 자동발송 아님). 알림 없음.
            log_event(
                event_type, customer=customer, sender=customer.owner,
                share_token=customer.share_token, ref_code=ref_code,
                viewer_fp=fp, channel='web',
                payload={'source': 'share_view'},
            )
            return Response({'status': 'logged', 'event_type': event_type},
                            status=status.HTTP_201_CREATED)

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

        from django.db import transaction

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

        # ── 공유(/s) 스냅샷 캡처 (spec 2026-07-08, 프리런치 #27) ──────────────
        # 그 순간 고객이 실제로 받을 /s 화면을 그대로 기록(§97 분쟁 시 "그때 무엇을
        # 보여줬는가" 증거). ★ 캡처 실패가 공유 링크 발급을 절대 막지 않는다 — 예외는
        # 타입만 로그(PII 로그 레드라인, §7) 하고 링크는 정상 201로 발급된다.
        try:
            # 보유기간 stamp: 0 이하(파기 중단 스위치)면 기본 180일로 stamp 해 과거시각
            # 저장을 피한다(파기 재개 시 정상 수명으로 복귀; 파기 자체는 jobs 가드가 막음).
            retention_days = settings.SHARE_SNAPSHOT_RETENTION_DAYS
            if retention_days <= 0:
                retention_days = 180
            with transaction.atomic():  # savepoint — 캡처 DB오류가 토큰 회전을 오염시키지 않도록
                snapshot_payload = _build_share_payload(customer)
                ShareSnapshot.objects.create(
                    owner=request.user,
                    customer=customer,
                    share_token=customer.share_token,
                    payload=snapshot_payload,
                    consent_overseas=has_current_overseas_consent(customer),
                    consent_doc_version=CONSENT_TEXTS_VERSION,
                    consent_scopes=_current_consent_scopes(customer),
                    dict_version=_current_dict_version(),
                    insurance_count=customer.customer_insurance_list.count(),
                    retention_expires_at=timezone.now() + timedelta(days=retention_days),
                )
        except Exception as exc:  # noqa: BLE001 — 격리(링크 발급 우선), 내용 없이 타입만 로그
            # logger.error(exc_info 없음): §7 PII 로그 레드라인 — 예외 타입명만 남긴다.
            logger.error('share snapshot capture failed: %s', type(exc).__name__)

        return Response({
            'customer_id': customer.id,
            'share_token': str(customer.share_token),
            'share_expires_at': customer.share_expires_at.isoformat(),
            'share_url': f'/s/{customer.share_token}',
        }, status=status.HTTP_201_CREATED)


class _ShareSnapshotScopedView(APIView):
    """owner 스코프 Customer 확보 공통 — analysis/flags.py::_CustomerScopedView 패턴 복제.

    쓰기가 없는 조회 전용 API라 어드민 read 우회를 허용한다(기존 히트맵/이력 관례).
    """
    permission_classes = [IsAuthenticated, IsEmailVerified]

    def _is_admin(self):
        profile = getattr(self.request.user, 'profile', None)
        return bool(getattr(profile, 'is_admin', False))

    def _get_customer(self, customer_pk):
        qs = Customer.objects.all()
        if not self._is_admin():
            qs = qs.filter(owner=self.request.user)
        try:
            return qs.get(pk=customer_pk)
        except Customer.DoesNotExist:
            raise NotFound('고객을 찾을 수 없습니다.')


def _snapshot_list_item(snap):
    """목록 응답 — payload 미포함(경량, dev/08 스펙)."""
    return {
        'id': snap.id,
        'captured_at': snap.captured_at.isoformat(),
        'retention_expires_at': snap.retention_expires_at.isoformat(),
        'insurance_count': snap.insurance_count,
        'consent_overseas': snap.consent_overseas,
        'consent_doc_version': snap.consent_doc_version,
        'dict_version': snap.dict_version,
    }


class CustomerShareSnapshotListView(_ShareSnapshotScopedView):
    """GET /api/v1/customers/<customer_pk>/share-snapshots/ — 공유 기록 목록(최신순, 경량).

    ★ owner 격리: 본인 고객이 아니면 404(존재 은폐).
    """

    def get(self, request, customer_pk):
        customer = self._get_customer(customer_pk)
        qs = ShareSnapshot.objects.filter(customer=customer).order_by('-captured_at')
        return Response([_snapshot_list_item(s) for s in qs])


class CustomerShareSnapshotDetailView(_ShareSnapshotScopedView):
    """GET /api/v1/customers/<customer_pk>/share-snapshots/<snap_id>/ — 단건 상세(payload 포함).

    ★ owner 격리: 고객·스냅샷 둘 다 본인 소유여야 함(customer=customer 필터로 타 고객
    소속 스냅샷 id는 자동 404 — 존재 은폐).
    """

    def get(self, request, customer_pk, snap_id):
        customer = self._get_customer(customer_pk)
        try:
            snap = ShareSnapshot.objects.get(pk=snap_id, customer=customer)
        except ShareSnapshot.DoesNotExist:
            raise NotFound('공유 기록을 찾을 수 없습니다.')
        item = _snapshot_list_item(snap)
        item['payload'] = snap.payload
        item['consent_scopes'] = snap.consent_scopes
        return Response(item)
