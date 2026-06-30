"""알림 도메인 ViewSet (dev/22 §5 API 계약).

가시성 강제 3중 (dev/02 §0 소유자 전용):
  ① OwnedQuerySetMixin — get_queryset이 owner=request.user로 필터 (관리자 bypass)
  ② IsOwner — 객체 단위 소유자 확인
  ③ IsEmailVerified — 이메일 인증 완료 사용자만

엔드포인트 목록 (dev/22 §5.1):
  GET  /api/v1/notifications/                  목록 (페이지네이션, ?is_read 필터)
  GET  /api/v1/notifications/unread-count/     미읽음 수 (벨 배지용)
  POST /api/v1/notifications/read-all/         전체 읽음 처리
  PATCH /api/v1/notifications/{id}/read/       단일 읽음 처리
  DELETE /api/v1/notifications/{id}/           단일 삭제 (실제 삭제)
  GET  /api/v1/reminder-rules/                 내 설정 5종 조회
  PATCH /api/v1/reminder-rules/bulk/           설정 일괄 업데이트

★ 정직성 레드라인: 고객 자동발송 경로 물리 부재 (dev/22 §6.2).
  Notification 생성 API 없음 — BE 내부(cron/signal)에서만 생성.
"""
from django.db import transaction
from django.db.models import Count
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from inpa.core.mixins import OwnedQuerySetMixin
from inpa.core.permissions import IsEmailVerified, IsOwner

from .models import CUSTOMER_NOTIF_TYPES, SCHEDULE_NOTIF_TYPES, Notification, ReminderRule
from .serializers import (
    NotificationSerializer,
    ReminderRuleBulkItemSerializer,
    ReminderRuleSerializer,
)


class NotificationViewSet(OwnedQuerySetMixin, viewsets.GenericViewSet):
    """알림 센터 — 소유자 전용 (dev/22 §5.1).

    FE 생성 금지: Notification은 BE cron/signal만 생성. 이 ViewSet은 읽기·상태변경·삭제만 노출.
    """
    permission_classes = [IsAuthenticated, IsEmailVerified, IsOwner]
    serializer_class = NotificationSerializer
    queryset = Notification.objects.select_related('customer')

    def get_queryset(self):
        qs = super().get_queryset()
        # ?is_read=true/false 필터 (dev/22 §5.1)
        is_read = self.request.query_params.get('is_read')
        if is_read is not None:
            qs = qs.filter(is_read=is_read.lower() == 'true')
        return qs

    # ── GET /notifications/ ────────────────────────────────────────
    def list(self, request, *args, **kwargs):
        """알림 목록 (created_at 내림차순, 페이지네이션)."""
        qs = self.get_queryset()
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

    # ── GET /notifications/unread-count/ ──────────────────────────
    @action(detail=False, methods=['get'], url_path='unread-count')
    def unread_count(self, request):
        """미읽음 수 — 벨 배지(전체) + 네비 카테고리 배지(고객/일정). 60초 폴링.

        customers/schedule는 전체(unread_count)의 부분집합 — 알림은 받은함 전체 유지.
        소거는 표준 읽음 처리(read/read-all)로 줄어듦 = '알림처럼'.
        """
        by_type = dict(
            self.get_queryset().filter(is_read=False)
            .values_list('notif_type').annotate(c=Count('id'))
        )
        total = sum(by_type.values())
        customers = sum(v for k, v in by_type.items() if k in CUSTOMER_NOTIF_TYPES)
        schedule = sum(v for k, v in by_type.items() if k in SCHEDULE_NOTIF_TYPES)
        return Response({'unread_count': total, 'customers': customers, 'schedule': schedule})

    # ── POST /notifications/read-all/ ─────────────────────────────
    @action(detail=False, methods=['post'], url_path='read-all')
    def read_all(self, request):
        """전체 읽음 처리 (dev/22 §4.2 [전체 읽음 처리] 버튼)."""
        updated = self.get_queryset().filter(is_read=False).update(is_read=True)
        return Response({'updated': updated})

    # ── PATCH /notifications/{id}/read/ ───────────────────────────
    @action(detail=True, methods=['patch'], url_path='read')
    def mark_read(self, request, pk=None):
        """단일 읽음 처리 — 알림 항목 클릭 시 자동 호출 (dev/22 §4.2)."""
        notif = self.get_object()
        if not notif.is_read:
            notif.is_read = True
            notif.save(update_fields=['is_read'])
        serializer = self.get_serializer(notif)
        return Response(serializer.data)

    # ── DELETE /notifications/{id}/ ───────────────────────────────
    def destroy(self, request, *args, **kwargs):
        """단일 삭제 — 실제 삭제(soft delete 아님, dev/22 §5.5)."""
        notif = self.get_object()
        notif.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ── retrieve ───────────────────────────────────────────────────
    def retrieve(self, request, *args, **kwargs):
        notif = self.get_object()
        serializer = self.get_serializer(notif)
        return Response(serializer.data)


class ReminderRuleViewSet(OwnedQuerySetMixin, viewsets.GenericViewSet):
    """알림 설정 5종 — 소유자 전용 (dev/22 §5.4·§5.5).

    GET  /reminder-rules/        내 설정 5종 전체 반환
    PATCH /reminder-rules/bulk/  변경할 rule만 부분 전송, 저장된 전체 5종 반환
    """
    permission_classes = [IsAuthenticated, IsEmailVerified, IsOwner]
    serializer_class = ReminderRuleSerializer
    queryset = ReminderRule.objects.all()

    # ── GET /reminder-rules/ ──────────────────────────────────────
    def list(self, request, *args, **kwargs):
        """내 알림 설정 5종 목록."""
        qs = self.get_queryset().order_by('rule_type')
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

    # ── PATCH /reminder-rules/bulk/ ───────────────────────────────
    @action(detail=False, methods=['patch'], url_path='bulk')
    def bulk_update(self, request):
        """설정 일괄 업데이트 (dev/22 §5.5).

        요청: [{"rule_type": "expiry_soon", "days_before": 14, ...}, ...]
        응답: 저장된 전체 5종 반환 (§5.4 동일 포맷).
        변경할 rule만 부분 전송 가능. 없는 rule_type은 건너뜀.
        """
        if not isinstance(request.data, list):
            return Response(
                {'detail': '배열(list) 형태로 전송해야 합니다.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 요청 검증
        items_serializer = ReminderRuleBulkItemSerializer(data=request.data, many=True)
        items_serializer.is_valid(raise_exception=True)
        validated = items_serializer.validated_data

        with transaction.atomic():
            rules_qs = self.get_queryset()
            rules_map = {r.rule_type: r for r in rules_qs}

            for item in validated:
                rule_type = item['rule_type']
                rule = rules_map.get(rule_type)
                if rule is None:
                    continue  # 존재하지 않는 rule_type은 건너뜀 (가입 시 자동 생성됐어야 함)

                update_fields = []
                if 'days_before' in item:
                    rule.days_before = item['days_before']
                    update_fields.append('days_before')
                if 'enabled' in item:
                    rule.enabled = item['enabled']
                    update_fields.append('enabled')
                if 'email_enabled' in item:
                    rule.email_enabled = item['email_enabled']
                    update_fields.append('email_enabled')
                if update_fields:
                    update_fields.append('updated_at')
                    rule.save(update_fields=update_fields)

        # 저장된 전체 5종 반환 (dev/22 §5.5)
        qs = self.get_queryset().order_by('rule_type')
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)
