"""알림 직렬화 (dev/22 §5 API 계약).

NotificationSerializer     — GET /notifications/ 응답 (customer_name join, dev/22 §5.2)
ReminderRuleSerializer     — GET/PATCH /reminder-rules/ 응답
ReminderRuleBulkSerializer — PATCH /reminder-rules/bulk/ 요청 검증
"""
from rest_framework import serializers

from .models import NotifType, Notification, ReminderRule

_DAYS_BEFORE_MAX = 90


class NotificationSerializer(serializers.ModelSerializer):
    """발화된 알림 직렬화.

    customer_name: 조회 편의용 join 필드 (dev/22 §5.2).
    owner는 응답에 노출하지 않음 — 항상 request.user 본인 것.
    """
    customer_name = serializers.SerializerMethodField()
    meeting_status = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            'id',
            'notif_type',
            'title',
            'body',
            'target_date',
            'customer',
            'customer_name',
            'calendar_event_id',
            'meeting',          # 미팅 예약 알림의 수락/거절 대상(없으면 null)
            'meeting_status',   # 'pending'이면 수락/거절 버튼 노출
            'is_read',
            'created_at',
        ]
        read_only_fields = fields  # 알림은 BE 생성 전용. FE에서 직접 생성 금지.

    def get_customer_name(self, obj):
        if obj.customer_id:
            return obj.customer.name if obj.customer else None
        return None

    def get_meeting_status(self, obj):
        return obj.meeting.status if obj.meeting_id else None


class ReminderRuleSerializer(serializers.ModelSerializer):
    """알림 설정 직렬화 (dev/22 §5.4).

    days_before: 0~90 범위 강제. 이 바깥은 400 반환.
    share_unread.days_before: UI에서 변경 불가(0 고정). BE는 수정 허용하되 프론트가 잠가야 함.
    """
    class Meta:
        model = ReminderRule
        fields = [
            'id',
            'rule_type',
            'days_before',
            'enabled',
            'email_enabled',
            'updated_at',
        ]
        read_only_fields = ['id', 'rule_type', 'updated_at']

    def validate_days_before(self, value):
        if not (0 <= value <= _DAYS_BEFORE_MAX):
            raise serializers.ValidationError(
                f'days_before는 0~{_DAYS_BEFORE_MAX} 범위여야 합니다.'
            )
        return value


class ReminderRuleBulkItemSerializer(serializers.Serializer):
    """bulk PATCH 단일 항목 (dev/22 §5.5).

    rule_type 필수. 나머지 필드는 선택(부분 전송 허용).
    """
    rule_type = serializers.ChoiceField(choices=NotifType.choices)
    days_before = serializers.IntegerField(min_value=0, max_value=_DAYS_BEFORE_MAX, required=False)
    enabled = serializers.BooleanField(required=False)
    email_enabled = serializers.BooleanField(required=False)
