"""미팅 예약 인증 API — 슬롯 CRUD / 미팅 목록·취소 / 예약 링크 생성.

owner 격리(OwnedQuerySetMixin + IsOwner). BOOKING_ENABLED 게이트.
미팅 생성은 공개 경로(public_booking.py)에서만 — 여기선 읽기·취소.
"""
from django.conf import settings
from django.utils import timezone
from django.db import IntegrityError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from inpa.core.mixins import OwnedQuerySetMixin
from inpa.core.permissions import IsEmailVerified, IsOwner
from inpa.customers.models import Customer

from .models import Meeting, WorkHour
from .serializers import MeetingSerializer, WorkHourSerializer
from .templates_text import DEFAULT_BOOKING_MSG_TEMPLATE, render_booking_message
from .tokens import make_booking_token


def _booking_enabled():
    return bool(getattr(settings, 'BOOKING_ENABLED', False))


def _push_to_google(meeting):
    """미팅 확정(수락) 시 구글 캘린더에 등록 — 연동된 설계사만, 실패는 격리(예약엔 영향 없음)."""
    try:
        from inpa.accounts.google import google_calendar_enabled
        profile = getattr(meeting.owner, 'profile', None)
        if google_calendar_enabled() and profile and profile.google_calendar_refresh_token:
            from inpa.accounts.google_calendar import insert_meeting_event
            name = meeting.customer.name if meeting.customer_id else '고객'
            event_id = insert_meeting_event(profile, meeting, name)
            if event_id:
                meeting.google_event_id = event_id
                meeting.save(update_fields=['google_event_id'])
    except Exception:
        pass


class WorkHourViewSet(OwnedQuerySetMixin, viewsets.ModelViewSet):
    """설계사 주간 업무시간 CRUD — /api/v1/work-hours/ (owner 전용).

    여기서 정한 요일·시간 안에서 미팅·차단·버퍼를 빼고 빈 시간을 고객에게 자동 노출한다.
    """
    permission_classes = [IsAuthenticated, IsEmailVerified, IsOwner]
    serializer_class = WorkHourSerializer
    queryset = WorkHour.objects.all()

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not _booking_enabled():
            raise PermissionDenied('미팅 예약 기능이 현재 비활성화되어 있습니다.')

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class MeetingViewSet(OwnedQuerySetMixin, viewsets.ReadOnlyModelViewSet):
    """미팅 조회 + 취소 — /api/v1/meetings/ (owner 전용). 생성은 공개 경로만."""
    permission_classes = [IsAuthenticated, IsEmailVerified, IsOwner]
    serializer_class = MeetingSerializer
    queryset = Meeting.objects.select_related('customer').all()

    def get_queryset(self):
        qs = super().get_queryset()
        st = self.request.query_params.get('status')
        if st:
            qs = qs.filter(status=st)
        elif self.request.query_params.get('upcoming') == 'true':
            qs = qs.filter(status=Meeting.STATUS_CONFIRMED, start_at__gte=timezone.now())
        return qs

    @action(detail=True, methods=['post'])
    def accept(self, request, pk=None):
        """대기 중인 예약 신청을 수락 → 확정 + 구글 캘린더 등록."""
        meeting = self.get_object()
        if meeting.status != Meeting.STATUS_PENDING:
            return Response({'detail': '대기 중인 예약만 수락할 수 있어요.'},
                            status=status.HTTP_400_BAD_REQUEST)
        meeting.status = Meeting.STATUS_CONFIRMED
        meeting.save(update_fields=['status'])
        # 수락 = 만나기로 확정 → 고객을 FA(대면) 단계로 자동 승급(db/contact일 때만).
        # Customer.save() 훅이 fa_reached_at 최초 도달 시각을 자동 스탬프 → '이번 달 미팅' 실적 반영.
        c = meeting.customer
        if c and c.sales_stage in (Customer.STAGE_DB, Customer.STAGE_CONTACT):
            c.sales_stage = Customer.STAGE_MEETING
            # fa_reached_at은 save() 훅이 채우므로 update_fields에 함께 넣어야 영속됨(update_fields 함정).
            c.save(update_fields=['sales_stage', 'fa_reached_at'])
        _push_to_google(meeting)
        return Response(self.get_serializer(meeting).data)

    @action(detail=True, methods=['post'])
    def decline(self, request, pk=None):
        """대기 중인 예약 신청을 거절 → 그 시간이 다시 비워진다."""
        meeting = self.get_object()
        if meeting.status != Meeting.STATUS_PENDING:
            return Response({'detail': '대기 중인 예약만 거절할 수 있어요.'},
                            status=status.HTTP_400_BAD_REQUEST)
        meeting.status = Meeting.STATUS_DECLINED
        meeting.save(update_fields=['status'])
        return Response(self.get_serializer(meeting).data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        meeting = self.get_object()
        meeting.status = Meeting.STATUS_CANCELED
        meeting.save(update_fields=['status'])
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
        planner_name = ((getattr(profile, 'name', '') or '')
                        or (getattr(profile, 'affiliation', '') or '')
                        or request.user.email)
        planner_label = ' '.join(
            p for p in ((getattr(profile, 'affiliation', '') or '').strip(),
                        (getattr(profile, 'title', '') or '').strip()) if p)
        template = getattr(profile, 'booking_msg_template', '') or DEFAULT_BOOKING_MSG_TEMPLATE
        message = render_booking_message(template, customer.name, planner_name, url,
                                         planner_label=planner_label)
        return Response(
            {'token': token, 'booking_url': url, 'message': message},
            status=status.HTTP_201_CREATED)
