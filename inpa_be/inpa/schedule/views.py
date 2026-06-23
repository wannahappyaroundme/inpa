"""개인 일정 ViewSet — /api/v1/schedule-items/ (소유자 전용).

★ OwnedQuerySetMixin(조회 격리 + owner 자동주입) + IsOwner(객체검사) + IsEmailVerified.
★ BOOKING_ENABLED 게이트 없음 — 개인 일정은 컴플라이언스 위험 없는 중립 기능.
"""
import datetime

from django.db.models import Q
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from inpa.core.mixins import OwnedQuerySetMixin
from inpa.core.permissions import IsEmailVerified, IsOwner

from .models import ScheduleItem
from .serializers import ScheduleItemSerializer


def _month_bounds_utc(month):
    """'YYYY-MM'(KST) → (start, end) aware datetime. 실패 시 None.

    KST 그 달 1일 00:00 ~ 다음 달 1일 00:00. Django 가 UTC 로 환산해 쿼리(USE_TZ=True).
    단순 __year/__month 대신 경계 환산을 써 월말 자정 일정이 옆 달로 새는 것 방지.
    """
    try:
        y, m = month.split('-')
        y, m = int(y), int(m)
        datetime.datetime(y, m, 1)  # 유효성
    except (ValueError, AttributeError, TypeError):
        return None
    tz = timezone.get_current_timezone()  # Asia/Seoul (settings.TIME_ZONE)
    start = timezone.make_aware(datetime.datetime(y, m, 1), tz)
    end = timezone.make_aware(
        datetime.datetime(y + 1, 1, 1) if m == 12 else datetime.datetime(y, m + 1, 1), tz)
    return start, end


class ScheduleItemViewSet(OwnedQuerySetMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsEmailVerified, IsOwner]
    serializer_class = ScheduleItemSerializer
    queryset = ScheduleItem.objects.select_related('customer').all()

    def get_queryset(self):
        qs = super().get_queryset()  # OwnedQuerySetMixin: owner 격리
        kind = self.request.query_params.get('kind')
        if kind:
            qs = qs.filter(kind=kind)
        month = self.request.query_params.get('month')
        if month:
            bounds = _month_bounds_utc(month)
            if bounds:
                start, end = bounds
                # 단건은 그 달, 반복 차단(recur_weekday)은 항상 포함(FE 가 주차별 전개)
                qs = qs.filter(
                    Q(start_at__gte=start, start_at__lt=end)
                    | Q(recur_weekday__isnull=False))
        return qs

    @action(detail=True, methods=['post'])
    def toggle_done(self, request, pk=None):
        """할일 완료 토글. get_object() 가 owner 격리 + IsOwner 통과."""
        item = self.get_object()
        item.is_done = not item.is_done
        item.done_at = timezone.now() if item.is_done else None
        item.save(update_fields=['is_done', 'done_at', 'updated_at'])
        return Response(self.get_serializer(item).data)
