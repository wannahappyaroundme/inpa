from django.utils import timezone
from rest_framework import serializers

from .models import Meeting, MeetingSlot, WorkHour


class WorkHourSerializer(serializers.ModelSerializer):
    """주간 업무시간 CRUD. start_time/end_time = KST 벽시계(변환 금지)."""
    class Meta:
        model = WorkHour
        fields = ('id', 'weekday', 'start_time', 'end_time', 'created_at')
        read_only_fields = ('id', 'created_at')

    def validate(self, data):
        start = data.get('start_time')
        end = data.get('end_time')
        if start and end and start >= end:
            raise serializers.ValidationError({'end_time': '종료 시간이 시작보다 늦어야 해요.'})
        wd = data.get('weekday')
        if wd is not None and not (0 <= wd <= 6):
            raise serializers.ValidationError({'weekday': '요일은 0(월)~6(일)이어야 해요.'})
        return data


class MeetingSerializer(serializers.ModelSerializer):
    """설계사용 미팅 읽기 직렬화."""
    customer_name = serializers.SerializerMethodField()
    method_display = serializers.CharField(source='get_method_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Meeting
        fields = ('id', 'customer', 'customer_name', 'slot', 'start_at', 'duration_min',
                  'method', 'method_display', 'location_detail', 'customer_note',
                  'status', 'status_display', 'created_at')
        read_only_fields = fields

    def get_customer_name(self, obj):
        return obj.customer.name if obj.customer_id else '(삭제된 고객)'


class PublicSlotSerializer(serializers.ModelSerializer):
    """공개 예약 페이지용 — 최소 정보(상태/소유자 미노출)."""
    class Meta:
        model = MeetingSlot
        fields = ('id', 'start_at', 'duration_min')
