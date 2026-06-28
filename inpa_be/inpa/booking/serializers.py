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


class MeetingSlotSerializer(serializers.ModelSerializer):
    """설계사 슬롯 CRUD. status는 서버 관리(read_only)."""
    class Meta:
        model = MeetingSlot
        fields = ('id', 'start_at', 'duration_min', 'status', 'created_at')
        read_only_fields = ('id', 'status', 'created_at')

    def validate_start_at(self, value):
        # ★ 미래강제 로직 유지(레드존 — public_booking·테스트가 전제). 메시지만 친절화.
        if value <= timezone.now():
            raise serializers.ValidationError(
                '지난 시간은 슬롯으로 만들 수 없어요. 지금보다 나중 시각을 골라주세요.')
        return value


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
