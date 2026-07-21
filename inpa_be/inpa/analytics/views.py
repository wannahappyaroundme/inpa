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
from inpa.customers.models import Customer

from .events import (
    is_bot_ua, is_dedup_view, log_event, viewer_fingerprint,
)
from .models import NorthStarEvent, ShareSnapshot
from .sharing import (
    PAYLOAD_VERSION_V2, ShareNotReady, create_share_snapshot,
)

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


def _snapshot_link_status(snapshot, *, now=None):
    """Derive the internal lifecycle from the public v2 authority rules."""
    if snapshot.payload_version != PAYLOAD_VERSION_V2:
        return 'history_only'
    if snapshot.revoked_at is not None:
        return 'revoked'
    current_time = now or timezone.now()
    if (snapshot.link_expires_at is None
            or snapshot.link_expires_at <= current_time):
        return 'expired'
    return 'active'


class _NoIndexMixin:
    """공유뷰 응답에 noindex 헤더 강제 (dev/13 §1.2 — 민감정보 검색 색인 물리 차단)."""

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response['X-Robots-Tag'] = 'noindex, nofollow'
        response['Cache-Control'] = 'private, no-store'
        return response


class ShareAnalysisView(_NoIndexMixin, APIView):
    """공유뷰 — GET /api/v1/s/<token>/ (AllowAny, 비인증).

    v2 ShareSnapshot 토큰으로 불변 분석 본문과 실시간 행동을 분리해 반환한다.
    gate OFF 전환 기간에만 과거 Customer 토큰을 임시 허용한다.
    """
    permission_classes = [AllowAny]
    authentication_classes = []  # 공개 — 인증 시도 자체 없음
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'share_public'  # DB write/연산 증폭 DoS 방어(유포된 링크 1개로 반복호출 차단)

    def get(self, request, token):
        snapshot, customer, reason = _resolve_public_share(token)
        if reason:
            return _gone(reason)

        ua = request.META.get('HTTP_USER_AGENT', '') or ''
        is_bot = is_bot_ua(ua)

        if snapshot is None:
            # gate OFF 전환 기간에만 허용되는 과거 Customer 토큰.
            body = _build_share_payload(customer)
            if not is_bot:
                customer.user_view_at = timezone.now()
                customer.save(update_fields=['user_view_at'])
            event_token = customer.share_token
        else:
            # 분석 본문은 저장값만 사용하고 연락/예약 행동만 요청 시점 값으로 만든다.
            body = {
                'snapshot': {
                    **snapshot.payload,
                    'captured_at': snapshot.captured_at.isoformat(),
                },
                'actions': _build_live_actions(customer),
            }
            if not is_bot:
                ShareSnapshot.objects.filter(
                    pk=snapshot.pk, first_viewed_at__isnull=True,
                ).update(first_viewed_at=timezone.now())
            event_token = snapshot.share_token

        # ── 5) share_view 적재 (BE 서버측정, viewer_fp 중복/봇 가드) ──
        fp = viewer_fingerprint(request)
        ref_code = request.query_params.get('ref') or None
        if is_bot:
            # 카톡 프리뷰/봇 → 신뢰 KPI 분자 제외. raw 로그만 채널 표기로 남긴다.
            log_event(NorthStarEvent.SHARE_VIEW, customer=customer, sender=customer.owner,
                      share_token=event_token, ref_code=ref_code,
                      viewer_fp=fp, channel='bot',
                      payload={'ua': ua[:200], 'excluded': 'bot'})
        elif not is_dedup_view(event_token, fp):
            log_event(NorthStarEvent.SHARE_VIEW, customer=customer, sender=customer.owner,
                      share_token=event_token, ref_code=ref_code,
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


def _build_live_actions(customer):
    actions = {'planner_contact': _planner_phone(customer)}
    booking_url = _booking_url(customer)
    if booking_url:
        actions['booking_url'] = booking_url
    return actions


def _resolve_public_share(token):
    """(v2 snapshot|None, customer|None, error reason|None).

    snapshot row가 하나라도 있으면 그 lifecycle을 최종 권위로 삼고 Customer 토큰으로
    되돌아가지 않는다. gate OFF일 때 snapshot이 전혀 없는 과거 링크만 임시 허용한다.
    """
    try:
        snapshot = (ShareSnapshot.objects.select_related(
            'customer__owner__profile').filter(share_token=token).first())
    except (ValueError, TypeError):
        return None, None, 'SHARE_LINK_INVALID'

    if snapshot is not None:
        customer = snapshot.customer
        if snapshot.owner_id != customer.owner_id:
            return None, None, 'SHARE_LINK_INVALID'
        link_status = _snapshot_link_status(snapshot)
        if link_status == 'history_only':
            return None, None, 'SHARE_LINK_INVALID'
        if link_status == 'revoked':
            return None, None, 'SHARE_LINK_REVOKED'
        if link_status == 'expired':
            return None, None, 'SHARE_LINK_EXPIRED'
        return snapshot, customer, None

    if not settings.LEGACY_SHARE_FALLBACK_ENABLED:
        return None, None, 'SHARE_LINK_INVALID'
    try:
        customer = Customer.objects.select_related(
            'owner__profile').get(share_token=token)
    except (Customer.DoesNotExist, ValueError, TypeError):
        return None, None, 'SHARE_LINK_INVALID'
    if (customer.share_expires_at is not None
            and customer.share_expires_at <= timezone.now()):
        return None, None, 'SHARE_LINK_EXPIRED'
    return None, customer, None


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


def _build_share_payload(
    customer, *, include_live_actions=True, insurance_list=None,
):
    """공유뷰 페이로드 — '사실'만(neutral 강제, baseline 부재).

    held_amount(보유 보장금액)와 status('none'|'neutral')만 노출한다.
    """
    #    ★ portfolio_type=1(보유)만 — 제안(2)/템플릿(0)이 고객 공유뷰·스냅샷에 '보유'로
    #    섞이지 않게 한다(dashboard/aggregation·churn·manager 와 동일 규칙).
    if insurance_list is None:
        insurance_list = list(
            customer.customer_insurance_list
            .analysis_ready()
            .filter(portfolio_type=1)
            .prefetch_related(
                'case_list__detail__analysis_detail',
                'case_list__analysis_detail_override',
                'case_list__detail__chart_detail')
            .all()
        )
    else:
        # 스냅샷 생성기는 같은 트랜잭션에서 잠근 정확한 보험 집합을 전달한다.
        insurance_list = list(insurance_list)
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
    }
    if include_live_actions:
        payload.update(_build_live_actions(customer))
    # ★ 권유 단어 서버측 가드(#23, §97·금소법) — 고정 카피 필드만 검사(로그 관측, 화면은 유지).
    #   공유뷰(/s)와 셀프진단(/d, self_diagnosis.py 가 이 함수를 재사용)의 고정 카피를 함께 커버.
    #   데이터 필드(고객명·담보명·금액)는 검사하지 않는다(오탐 방지).
    warn_if_advice_words({'disclaimer': payload['disclaimer']}, where='share_payload')
    return payload


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
          (고객 메뉴 배지로 귀속). 같은 날 중복은 Notification 부분 유니크 제약
          (owner+type+target_date+customer)의 IntegrityError를 성공 상태로 흡수한다.
        """
        from django.db import IntegrityError, transaction

        from inpa.notifications.models import NotifType, Notification
        target_date = timezone.localdate()
        notification_scope = {
            'owner': customer.owner,
            'notif_type': NotifType.SELF_DIAGNOSIS_LEAD,
            'customer': customer,
            'target_date': target_date,
        }
        try:
            with transaction.atomic():
                Notification.objects.create(
                    owner=customer.owner, notif_type=NotifType.SELF_DIAGNOSIS_LEAD,
                    title='고객 연락 요청',
                    body=f'{customer.name}님이 보장 안내 화면에서 연락을 요청했어요. '
                         f'전화 한 통으로 이어가 보세요.',
                    customer=customer, target_date=target_date)
            return 'created'
        except IntegrityError:
            # 같은 고객·같은 날 알림이 실제로 존재할 때만 멱등 성공이다.
            # 다른 무결성 오류를 중복으로 오인하면 연락 요청이 유실된다.
            return (
                'already_notified'
                if Notification.objects.filter(**notification_scope).exists()
                else 'failed'
            )
        except Exception:
            return 'failed'

    def post(self, request, token):
        snapshot, customer, reason = _resolve_public_share(token)
        if reason:
            return _gone(reason)
        event_token = snapshot.share_token if snapshot is not None else customer.share_token

        event_type = request.data.get('event_type', NorthStarEvent.CLIPBOARD_COPY)
        if event_type not in self._PUBLIC_ALLOWED:
            return Response(
                {'detail': '허용되지 않은 이벤트입니다.', 'code': 'EVENT_NOT_ALLOWED'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        fp = viewer_fingerprint(request)
        ref_code = request.query_params.get('ref') or None

        if event_type == NorthStarEvent.CALLBACK_REQUEST:
            # 알림을 먼저 확정한다. 실패한 요청을 이벤트 성공으로 남기면 재시도 때
            # 이미 처리된 것으로 오인하므로, 두 결과가 모두 성공해야 완료로 응답한다.
            notification = self._notify_callback(customer)
            if notification == 'failed':
                return Response({
                    'detail': '연결이 잠시 원활하지 않습니다. 다시 요청해 주세요.',
                    'code': 'CALLBACK_NOTIFICATION_FAILED',
                    'event_type': event_type,
                    'recorded': False,
                    'notification': 'failed',
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            event = log_event(
                event_type, customer=customer, sender=customer.owner,
                share_token=event_token, ref_code=ref_code,
                viewer_fp=fp, channel='web',
                payload={'source': 'share_view'},
            )
            if event is None:
                return Response({
                    'detail': '요청 기록 연결이 잠시 원활하지 않습니다. 다시 요청해 주세요.',
                    'code': 'EVENT_LOG_FAILED',
                    'event_type': event_type,
                    'recorded': False,
                    'notification': notification,
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            return Response({
                'status': 'logged',
                'event_type': event_type,
                'recorded': True,
                'notification': notification,
            }, status=status.HTTP_201_CREATED)

        if event_type == NorthStarEvent.CTA_CLICK:
            # 분석→예약 CTA 클릭 — channel='web'(콜백과 동일, 자동발송 아님). 알림 없음.
            event = log_event(
                event_type, customer=customer, sender=customer.owner,
                share_token=event_token, ref_code=ref_code,
                viewer_fp=fp, channel='web',
                payload={'source': 'share_view'},
            )
            if event is None:
                return Response({
                    'detail': '요청 기록 연결이 잠시 원활하지 않습니다.',
                    'code': 'EVENT_LOG_FAILED', 'event_type': event_type,
                    'recorded': False,
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            return Response({
                'status': 'logged',
                'event_type': event_type,
                'recorded': True,
            },
                            status=status.HTTP_201_CREATED)

        # ★ clipboard_copy 는 channel='clipboard' 고정(자동발송 사칭 금지).
        event = log_event(
            event_type, customer=customer, sender=customer.owner,
            share_token=event_token, ref_code=ref_code,
            viewer_fp=fp, channel='clipboard',
            payload={'delivery': 'clipboard'},
        )
        if event is None:
            return Response({
                'detail': '요청 기록 연결이 잠시 원활하지 않습니다.',
                'code': 'EVENT_LOG_FAILED', 'event_type': event_type,
                'recorded': False,
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({
            'status': 'logged',
            'event_type': event_type,
            'recorded': True,
        },
                        status=status.HTTP_201_CREATED)


class CustomerShareCreateView(APIView):
    """공유 토큰 발급 — POST /api/v1/customers/<customer_pk>/share/ (인증·소유자).

    v2 ShareSnapshot을 원자적으로 만들고 이전 링크를 즉시 회수한다.
    스냅샷 본문, 수명 주기, share_created 이벤트가 모두 성공할 때만 발급된다.

    ★ owner 격리: 본인 고객이 아니면 404(존재 은폐).
    크레딧 차감 없음(share_link 는 북극성 차단 금지 대상 — dev/23 §1.2).
    """
    permission_classes = [IsAuthenticated, IsEmailVerified]

    def _get_customer(self, customer_pk):
        from rest_framework.exceptions import NotFound
        try:
            return Customer.objects.get(
                pk=customer_pk, owner=self.request.user)
        except Customer.DoesNotExist:
            raise NotFound('고객을 찾을 수 없습니다.')

    def post(self, request, customer_pk):
        try:
            self._get_customer(customer_pk)
            snapshot = create_share_snapshot(
                customer_id=customer_pk,
                owner=request.user,
                payload_builder=_build_share_payload,
            )
        except ShareNotReady as exc:
            return Response({
                'code': 'INSURANCE_REVIEW_REQUIRED',
                'detail': str(exc),
            }, status=status.HTTP_409_CONFLICT)
        except Customer.DoesNotExist:
            raise NotFound('고객을 찾을 수 없습니다.')
        except NotFound:
            raise
        except Exception as exc:
            logger.error('share snapshot create failed: %s', type(exc).__name__)
            return Response({
                'code': 'SHARE_CREATE_UNAVAILABLE',
                'detail': '공유 내용을 그대로 두었어요. 잠시 뒤 다시 시도해 주세요.',
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        return Response({
            'customer_id': snapshot.customer_id,
            'snapshot_id': snapshot.id,
            'share_token': str(snapshot.share_token),
            'share_expires_at': snapshot.link_expires_at.isoformat(),
            'share_url': f'/s/{snapshot.share_token}',
        }, status=status.HTTP_201_CREATED)


class _ShareSnapshotScopedView(APIView):
    """owner 스코프 Customer 확보 공통 — analysis/flags.py::_CustomerScopedView 패턴 복제.

    쓰기가 없는 조회 전용 API라 어드민 read 우회를 허용한다(기존 히트맵/이력 관례).
    """
    permission_classes = [IsAuthenticated, IsEmailVerified]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response['Cache-Control'] = 'private, no-store'
        return response

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

    def _snapshot_queryset(self, customer, *, require_request_owner=False):
        queryset = ShareSnapshot.objects.filter(
            customer=customer,
            owner_id=customer.owner_id,
        )
        if require_request_owner:
            queryset = queryset.filter(owner=self.request.user)
        return queryset


def _snapshot_list_item(snap):
    """목록 응답 — payload 미포함(경량, dev/08 스펙)."""
    return {
        'id': snap.id,
        'link_status': _snapshot_link_status(snap),
        'captured_at': snap.captured_at.isoformat(),
        'payload_version': snap.payload_version,
        'link_expires_at': (
            snap.link_expires_at.isoformat() if snap.link_expires_at else None),
        'revoked_at': snap.revoked_at.isoformat() if snap.revoked_at else None,
        'revoked_reason': snap.revoked_reason,
        'first_viewed_at': (
            snap.first_viewed_at.isoformat() if snap.first_viewed_at else None),
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
        qs = self._snapshot_queryset(customer).order_by('-captured_at')
        return Response([_snapshot_list_item(s) for s in qs])


class CustomerShareSnapshotDetailView(_ShareSnapshotScopedView):
    """GET /api/v1/customers/<customer_pk>/share-snapshots/<snap_id>/ — 단건 상세(payload 포함).

    ★ owner 격리: 고객·스냅샷 둘 다 본인 소유여야 함(customer=customer 필터로 타 고객
    소속 스냅샷 id는 자동 404 — 존재 은폐).
    """

    def get(self, request, customer_pk, snap_id):
        customer = self._get_customer(customer_pk)
        try:
            snap = self._snapshot_queryset(customer).get(pk=snap_id)
        except ShareSnapshot.DoesNotExist:
            raise NotFound('공유 기록을 찾을 수 없습니다.')
        item = _snapshot_list_item(snap)
        item['payload'] = snap.payload
        item['consent_scopes'] = snap.consent_scopes
        return Response(item)


class CustomerShareSnapshotRevokeView(_ShareSnapshotScopedView):
    """POST .../share-snapshots/<id>/revoke/ — 본인 링크만 즉시 닫는다."""

    def post(self, request, customer_pk, snap_id):
        from django.db import transaction
        customer = self._get_customer(customer_pk)
        with transaction.atomic():
            try:
                snapshot = (self._snapshot_queryset(
                    customer, require_request_owner=True,
                ).select_for_update().get(
                    pk=snap_id,
                    payload_version=PAYLOAD_VERSION_V2,
                ))
            except ShareSnapshot.DoesNotExist:
                raise NotFound('공유 기록을 찾을 수 없습니다.')
            if _snapshot_link_status(snapshot) != 'active':
                return Response({
                    'code': 'SHARE_SNAPSHOT_NOT_ACTIVE',
                    'detail': '현재 사용 중인 공유 기록만 회수할 수 있어요.',
                }, status=status.HTTP_409_CONFLICT)
            snapshot.revoked_at = timezone.now()
            snapshot.revoked_reason = 'manual'
            snapshot.save(update_fields=['revoked_at', 'revoked_reason'])
        return Response({'id': snapshot.id, 'status': 'revoked'})
