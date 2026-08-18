from django.utils import timezone
from rest_framework import serializers

from inpa.customers.models import Customer

from .models import Meeting, MeetingSlot, WorkHour


class BookingCustomerListSerializer(serializers.ModelSerializer):
    """예약 고객 선택기 전용 최소 정보."""

    class Meta:
        model = Customer
        fields = ('id', 'name', 'mobile_phone_number', 'sales_stage')
        read_only_fields = fields


class WorkHourSerializer(serializers.ModelSerializer):
    """주간 업무시간 CRUD. start_time/end_time = KST 벽시계(변환 금지).

    같은 요일에 여러 구간을 둘 수 있다. 맞닿는 구간(09:00-12:00 + 12:00-18:00)은 그대로 허용하고,
    일부 겹침·완전 포함·완전 중복만 막는다(겹치면 고객 화면에 같은 시간이 두 번 보인다).
    """
    class Meta:
        model = WorkHour
        fields = ('id', 'weekday', 'start_time', 'end_time', 'created_at')
        read_only_fields = ('id', 'created_at')

    def validate(self, data):
        # PATCH 는 일부 필드만 오므로 기존 값과 합쳐서 검사한다(부분 수정도 같은 규칙 적용).
        instance = self.instance
        start = data.get('start_time', getattr(instance, 'start_time', None))
        end = data.get('end_time', getattr(instance, 'end_time', None))
        wd = data.get('weekday', getattr(instance, 'weekday', None))
        if start and end and start >= end:
            raise serializers.ValidationError({'end_time': '종료 시간이 시작보다 늦어야 해요.'})
        if wd is not None and not (0 <= wd <= 6):
            raise serializers.ValidationError({'weekday': '요일은 0(월)~6(일)이어야 해요.'})
        self._check_overlap(wd, start, end)
        return data

    def _check_overlap(self, weekday, start, end):
        """같은 소유자·같은 요일의 겹침 거절. 수정 중이면 자기 자신은 제외한다."""
        owner = getattr(self.context.get('request'), 'user', None)
        if owner is None or not getattr(owner, 'is_authenticated', False):
            return
        if weekday is None or not start or not end:
            return
        # half-open [start, end) 비교 → 12:00에서 맞닿는 두 구간은 겹침이 아니다.
        clash = WorkHour.objects.filter(
            owner=owner, weekday=weekday, start_time__lt=end, end_time__gt=start)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        existing = clash.order_by('start_time').first()
        if existing is None:
            return
        raise serializers.ValidationError({
            'start_time': (
                f'같은 요일에 이미 {existing.start_time:%H:%M}~{existing.end_time:%H:%M} '
                '업무시간이 있어요. 겹치지 않는 시간으로 바꾸거나, 기존 시간을 먼저 수정해 주세요.'
            )
        })


class MeetingSerializer(serializers.ModelSerializer):
    """설계사용 미팅 읽기 직렬화."""
    customer_name = serializers.SerializerMethodField()
    method_display = serializers.CharField(source='get_method_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Meeting
        fields = ('id', 'customer', 'customer_name', 'slot', 'start_at', 'duration_min',
                  'method', 'method_display', 'location_detail', 'customer_note',
                  'status', 'status_display', 'calendar_cleanup_pending', 'created_at')
        read_only_fields = fields

    def get_customer_name(self, obj):
        return obj.customer.name if obj.customer_id else '(삭제된 고객)'


class PublicSlotSerializer(serializers.ModelSerializer):
    """공개 예약 페이지용 — 최소 정보(상태/소유자 미노출)."""
    class Meta:
        model = MeetingSlot
        fields = ('id', 'start_at', 'duration_min')
