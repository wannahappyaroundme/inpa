"""ScheduleItem 직렬화 — booking/serializers.py 패턴.

★ MeetingSlot 과 달리 과거시각 거부 없음(지난 일정·완료 할일도 봐야 함).
★ customer 는 본인 고객만 연결 가능(소유자 격리).
"""
from rest_framework import serializers

from .models import ScheduleItem


class ScheduleItemSerializer(serializers.ModelSerializer):
    customer_name = serializers.SerializerMethodField()

    class Meta:
        model = ScheduleItem
        fields = ('id', 'kind', 'title', 'memo', 'customer', 'customer_name',
                  'start_at', 'end_at', 'all_day', 'is_done', 'done_at',
                  'recur_weekday', 'recur_start_time', 'recur_end_time',
                  'created_at', 'updated_at')
        read_only_fields = ('id', 'done_at', 'created_at', 'updated_at')

    def get_customer_name(self, obj):
        return obj.customer.name if obj.customer_id else None

    def validate_customer(self, value):
        # 본인 고객만 연결(타 설계사 고객 id 위조 차단)
        if value is None:
            return value
        request = self.context.get('request')
        if request is not None and value.owner_id != request.user.id:
            raise serializers.ValidationError('본인 고객만 연결할 수 있어요.')
        return value

    def validate(self, attrs):
        def _val(f):
            return attrs.get(f, getattr(self.instance, f, None))

        kind = attrs.get('kind') or getattr(self.instance, 'kind', None)
        # 반복 차단이면 요일 + 시작/종료 시각 필수
        if kind == ScheduleItem.KIND_BLOCK and _val('recur_weekday') is not None:
            if _val('recur_start_time') is None or _val('recur_end_time') is None:
                raise serializers.ValidationError('반복 차단은 시작·종료 시각이 필요해요.')
        return attrs
