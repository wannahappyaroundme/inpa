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
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from inpa.analytics.views import _NoIndexMixin, _mask_name
from inpa.customers.models import Customer
from inpa.notifications.models import NotifType, Notification

from .models import Meeting, MeetingSlot
from .serializers import PublicSlotSerializer
from .tokens import read_booking_token

_METHODS = [
    {'key': Meeting.METHOD_IN_PERSON, 'label': '대면'},
    {'key': Meeting.METHOD_PHONE, 'label': '전화'},
    {'key': Meeting.METHOD_VIDEO, 'label': '화상'},
]
_METHOD_LABELS = {m['key']: m['label'] for m in _METHODS}
_DISCLAIMER = ('본 페이지는 상담 일정 안내용입니다. 인파는 보험을 중개·권유하지 않으며 AI가 응답하지 않습니다. '
               '일정 확정 후 담당 설계사가 직접 연락드립니다.')


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
        slots = MeetingSlot.objects.filter(
            owner=customer.owner, status=MeetingSlot.STATUS_OPEN, start_at__gte=timezone.now()
        ).order_by('start_at')
        return Response({
            'customer': {'name_masked': _mask_name(customer.name)},
            'planner': {
                'affiliation': getattr(profile, 'affiliation', '') or '',
                'location': getattr(profile, 'booking_location', '') or '',
            },
            'methods': _METHODS,
            'slots': PublicSlotSerializer(slots, many=True).data,
            'disclaimer': _DISCLAIMER,
        })

    def post(self, request, token):
        customer, err = self._resolve(token)
        if err is not None:
            return err
        slot_id = request.data.get('slot_id')
        method = request.data.get('method')
        note = (request.data.get('note') or '')[:2000]
        if not slot_id:
            return Response({'code': 'SLOT_REQUIRED', 'detail': '시간을 선택해 주세요.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if method not in _METHOD_LABELS:
            return Response({'code': 'METHOD_INVALID', 'detail': '상담 방식을 선택해 주세요.'},
                            status=status.HTTP_400_BAD_REQUEST)
        profile = getattr(customer.owner, 'profile', None)
        location = (getattr(profile, 'booking_location', '') or '') if method == Meeting.METHOD_IN_PERSON else ''

        with transaction.atomic():
            slot = (MeetingSlot.objects.select_for_update()
                    .filter(pk=slot_id, owner=customer.owner,
                            status=MeetingSlot.STATUS_OPEN, start_at__gte=timezone.now())
                    .first())
            if slot is None:
                return Response(
                    {'code': 'SLOT_TAKEN',
                     'detail': '이미 예약됐거나 마감된 시간이에요. 다른 시간을 선택해 주세요.'},
                    status=status.HTTP_409_CONFLICT)
            meeting = Meeting.objects.create(
                owner=customer.owner, customer=customer, slot=slot,
                start_at=slot.start_at, duration_min=slot.duration_min,
                method=method, location_detail=location, customer_note=note,
                status=Meeting.STATUS_CONFIRMED)
            slot.status = MeetingSlot.STATUS_BOOKED
            slot.save(update_fields=['status'])

        # 설계사 알림(실패 격리)
        try:
            Notification.objects.create(
                owner=customer.owner, notif_type=NotifType.MEETING_BOOKED,
                title='새 미팅 예약',
                body=f'{customer.name}님이 {timezone.localtime(meeting.start_at):%m/%d %H:%M} '
                     f'{_METHOD_LABELS[method]} 미팅을 예약했어요.',
                customer=customer)
        except Exception:
            pass

        return Response(
            {'confirmed': True, 'start_at': meeting.start_at,
             'method': method, 'location_detail': meeting.location_detail},
            status=status.HTTP_201_CREATED)
