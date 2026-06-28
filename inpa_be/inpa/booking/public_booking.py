"""미팅 예약 공개 경로 — 고객이 /b/<token>에서 슬롯 선택(비로그인). (public_consent.py 미러)

GET  /api/v1/b/<token>/  → 설계사 정보 + 열린 미래 슬롯 + 방식. (마스킹 이름만, PII 미노출)
POST /api/v1/b/<token>/  → {slot_id, method, note} → 원자적 확정 + 설계사 알림.

★ 중복예약: select_for_update 행잠금 + status='open' 필터로 단 1명만 성공(나머지 409).
★ 정직성: noindex, 자동발송 없음, disclaimer 고정.
"""
from django.conf import settings
from django.core import signing
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from inpa.analytics.views import _NoIndexMixin, _mask_name
from inpa.customers.models import Customer
from inpa.notifications.models import NotifType, Notification

from .availability import generate_available_slots, is_slot_available
from .models import Meeting
from .tokens import read_booking_token

_BOOKING_DAYS = 14  # 공개 페이지에 노출할 향후 일수

_METHODS = [
    {'key': Meeting.METHOD_IN_PERSON, 'label': '대면'},
    {'key': Meeting.METHOD_PHONE, 'label': '전화'},
    {'key': Meeting.METHOD_VIDEO, 'label': '화상'},
]
_METHOD_LABELS = {m['key']: m['label'] for m in _METHODS}
_DISCLAIMER = ('본 페이지는 상담 일정 안내용입니다. 인파는 보험을 중개·권유하지 않으며 AI가 응답하지 않습니다. '
               '일정 확정 후 담당 설계사가 직접 연락드립니다.')


def _planner_label(profile):
    """소속 + 직책 합쳐 표시(예: '부산지점 FC'). 둘 다 비면 빈 문자열."""
    aff = (getattr(profile, 'affiliation', '') or '').strip()
    title = (getattr(profile, 'title', '') or '').strip()
    return ' '.join(p for p in (aff, title) if p)


def _planner_settings(profile):
    dur = getattr(profile, 'booking_default_duration', 30) or 30
    buf = getattr(profile, 'booking_buffer_min', 60)
    return dur, (60 if buf is None else buf)


class PublicBookingView(_NoIndexMixin, APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'booking_public'

    def _resolve(self, token):
        """토큰 → Customer. 비활성/위조/없음=404, 만료=410. (customer, err_response)."""
        if not getattr(settings, 'BOOKING_ENABLED', False):
            return None, Response({'code': 'LINK_INVALID', 'detail': '유효하지 않은 링크입니다.'},
                                  status=status.HTTP_404_NOT_FOUND)
        try:
            pk = read_booking_token(token)
        except signing.SignatureExpired:
            return None, Response(
                {'code': 'LINK_EXPIRED',
                 'detail': '예약 링크가 만료됐어요. 담당 설계사에게 새 링크를 요청해 주세요.'},
                status=status.HTTP_410_GONE)
        except signing.BadSignature:
            return None, Response({'code': 'LINK_INVALID', 'detail': '유효하지 않은 링크입니다.'},
                                  status=status.HTTP_404_NOT_FOUND)
        customer = Customer.objects.filter(pk=pk).select_related('owner__profile').first()
        if customer is None:
            return None, Response({'code': 'LINK_INVALID', 'detail': '유효하지 않은 링크입니다.'},
                                  status=status.HTTP_404_NOT_FOUND)
        return customer, None

    def get(self, request, token):
        customer, err = self._resolve(token)
        if err is not None:
            return err
        profile = getattr(customer.owner, 'profile', None)
        dur, buf = _planner_settings(profile)
        slots = generate_available_slots(
            customer.owner, days=_BOOKING_DAYS, duration_min=dur, buffer_min=buf, step_min=dur)
        return Response({
            'customer': {'name_masked': _mask_name(customer.name)},
            'planner': {
                'affiliation': _planner_label(profile),
                'name': getattr(profile, 'name', '') or '',
            },
            'methods': _METHODS,
            'duration_min': dur,
            'slots': [{'start_at': s.isoformat(), 'duration_min': dur} for s in slots],
            'disclaimer': _DISCLAIMER,
        })

    def post(self, request, token):
        customer, err = self._resolve(token)
        if err is not None:
            return err
        start_raw = request.data.get('start_at')
        method = request.data.get('method')
        note = (request.data.get('note') or '')[:2000]
        if not start_raw:
            return Response({'code': 'SLOT_REQUIRED', 'detail': '시간을 선택해 주세요.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if method not in _METHOD_LABELS:
            return Response({'code': 'METHOD_INVALID', 'detail': '상담 방식을 선택해 주세요.'},
                            status=status.HTTP_400_BAD_REQUEST)
        start_at = parse_datetime(start_raw)
        if start_at is None:
            return Response({'code': 'TIME_INVALID', 'detail': '시간 형식이 올바르지 않아요.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if timezone.is_naive(start_at):
            start_at = timezone.make_aware(start_at)
        profile = getattr(customer.owner, 'profile', None)
        dur, buf = _planner_settings(profile)

        from inpa.accounts.models import Profile
        with transaction.atomic():
            # 같은 설계사 동시 신청 직렬화(프로필 행 잠금) → 재확인 후 생성(경합 시 1명만 성공).
            Profile.objects.select_for_update().filter(user=customer.owner).first()
            if not is_slot_available(customer.owner, start_at, duration_min=dur, buffer_min=buf):
                return Response(
                    {'code': 'SLOT_TAKEN',
                     'detail': '이 시간은 방금 다른 분이 잡았거나 지금은 예약할 수 없어요. 다른 시간을 골라 주세요. '
                               '꼭 이 시간이어야 하면 담당 설계사와 상의해 주세요.'},
                    status=status.HTTP_409_CONFLICT)
            meeting = Meeting.objects.create(
                owner=customer.owner, customer=customer, slot=None,
                start_at=start_at, duration_min=dur,
                method=method, location_detail='', customer_note=note,
                status=Meeting.STATUS_PENDING)

        # 설계사 알림(수락/거절 — meeting 연결, 실패 격리)
        try:
            Notification.objects.create(
                owner=customer.owner, notif_type=NotifType.MEETING_BOOKED,
                title='새 미팅 예약 요청',
                body=f'{customer.name}님이 {timezone.localtime(meeting.start_at):%m/%d %H:%M} '
                     f'{_METHOD_LABELS[method]} 미팅을 신청했어요. 수락하면 일정에 확정돼요.',
                customer=customer, meeting=meeting)
        except Exception:
            pass

        # 구글 캘린더는 설계사가 '수락'할 때 등록(대기 상태에선 미등록).
        return Response(
            {'requested': True, 'status': Meeting.STATUS_PENDING,
             'start_at': meeting.start_at, 'method': method},
            status=status.HTTP_201_CREATED)
