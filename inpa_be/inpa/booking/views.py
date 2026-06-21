"""미팅 예약 인증 API — 슬롯 CRUD / 미팅 목록·취소 / 예약 링크 생성.

owner 격리(OwnedQuerySetMixin + IsOwner). BOOKING_ENABLED 게이트.
미팅 생성은 공개 경로(public_booking.py)에서만 — 여기선 읽기·취소.
"""
from django.conf import settings
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from inpa.core.mixins import OwnedQuerySetMixin
from inpa.core.permissions import IsEmailVerified, IsOwner
from inpa.customers.models import Customer

from .models import Meeting, MeetingSlot
from .serializers import MeetingSerializer, MeetingSlotSerializer
from .templates_text import DEFAULT_BOOKING_MSG_TEMPLATE, render_booking_message
from .tokens import make_booking_token


def _booking_enabled():
    return bool(getattr(settings, 'BOOKING_ENABLED', False))


class MeetingSlotViewSet(OwnedQuerySetMixin, viewsets.ModelViewSet):
    """설계사 가용 슬롯 CRUD — /api/v1/meeting-slots/ (owner 전용)."""
    permission_classes = [IsAuthenticated, IsEmailVerified, IsOwner]
    serializer_class = MeetingSlotSerializer
    queryset = MeetingSlot.objects.all()

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not _booking_enabled():
            raise PermissionDenied('미팅 예약 기능이 현재 비활성화되어 있습니다.')

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.query_params.get('upcoming') == 'true':
            qs = qs.filter(status=MeetingSlot.STATUS_OPEN, start_at__gte=timezone.now())
        return qs

    def perform_create(self, serializer):
        dur = serializer.validated_data.get('duration_min')
        if not dur:
            profile = getattr(self.request.user, 'profile', None)
            dur = getattr(profile, 'booking_default_duration', 30) or 30
        serializer.save(owner=self.request.user, duration_min=dur)

    def _block_if_booked(self):
        if self.get_object().status == MeetingSlot.STATUS_BOOKED:
            raise PermissionDenied('이미 예약된 슬롯은 수정/삭제할 수 없습니다. 미팅을 먼저 취소하세요.')

    def update(self, request, *args, **kwargs):
        self._block_if_booked()
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        self._block_if_booked()
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        self._block_if_booked()
        return super().destroy(request, *args, **kwargs)


class MeetingViewSet(OwnedQuerySetMixin, viewsets.ReadOnlyModelViewSet):
    """미팅 조회 + 취소 — /api/v1/meetings/ (owner 전용). 생성은 공개 경로만."""
    permission_classes = [IsAuthenticated, IsEmailVerified, IsOwner]
    serializer_class = MeetingSerializer
    queryset = Meeting.objects.select_related('customer').all()

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.query_params.get('upcoming') == 'true':
            qs = qs.filter(status=Meeting.STATUS_CONFIRMED, start_at__gte=timezone.now())
        return qs

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        meeting = self.get_object()
        meeting.status = Meeting.STATUS_CANCELED
        meeting.save(update_fields=['status'])
        # 취소해도 슬롯은 재오픈하지 않음(MVP — 설계사가 새 슬롯 추가).
        return Response(self.get_serializer(meeting).data)


class BookingRequestCreateView(APIView):
    """미팅 예약 링크 생성 — POST /api/v1/customers/<customer_pk>/booking-requests/.

    설계사(소유자)가 본인 고객의 예약 링크를 만든다. 응답의 message는 설계사가
    클립보드 복사/카톡으로 직접 전달(자동발송 없음 — 정직성 레드라인).
    """
    permission_classes = [IsAuthenticated, IsEmailVerified]

    def _is_admin(self):
        profile = getattr(self.request.user, 'profile', None)
        return bool(getattr(profile, 'is_admin', False))

    def _get_customer(self, pk):
        qs = Customer.objects.all()
        if not self._is_admin():
            qs = qs.filter(owner=self.request.user)  # owner 격리 — 타 설계사 고객 404
        try:
            return qs.get(pk=pk)
        except Customer.DoesNotExist:
            raise NotFound('고객을 찾을 수 없습니다.')

    def post(self, request, customer_pk):
        if not _booking_enabled():
            raise PermissionDenied('미팅 예약 기능이 현재 비활성화되어 있습니다.')
        customer = self._get_customer(customer_pk)
        token = make_booking_token(customer)
        base = (getattr(settings, 'FRONTEND_BASE_URL', '') or '').rstrip('/')
        url = f'{base}/b/{token}'
        profile = getattr(request.user, 'profile', None)
        planner_name = (getattr(profile, 'affiliation', '') or '') or request.user.email
        template = getattr(profile, 'booking_msg_template', '') or DEFAULT_BOOKING_MSG_TEMPLATE
        message = render_booking_message(template, customer.name, planner_name, url)
        return Response(
            {'token': token, 'booking_url': url, 'message': message},
            status=status.HTTP_201_CREATED)
