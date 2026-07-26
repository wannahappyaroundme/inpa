from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers

from .models import ConsultationRecording
from .services import ALLOWED_RECORDING_MIME_TYPES


class ConsultationRecordingSerializer(serializers.ModelSerializer):
    source_available = serializers.SerializerMethodField()

    class Meta:
        model = ConsultationRecording
        fields = (
            'id',
            'status',
            'mime_type',
            'codec',
            'byte_size',
            'duration_ms',
            'started_at',
            'ended_at',
            'uploaded_at',
            'expires_at',
            'deleted_at',
            'delete_reason',
            'source_available',
            'version',
            'created_at',
            'updated_at',
        )
        read_only_fields = fields

    def get_source_available(self, obj):
        if obj.status not in (
            obj.STATUS_READY,
            obj.STATUS_PROCESSING,
            obj.STATUS_COMPLETED,
            obj.STATUS_FAILED,
            obj.STATUS_AMBIGUOUS,
        ):
            return False
        if not obj.storage_key:
            return False
        return obj.expires_at is None or obj.expires_at > timezone.now()


class UploadSessionRequestSerializer(serializers.Serializer):
    client_session_id = serializers.UUIDField()
    mime_type = serializers.ChoiceField(choices=sorted(ALLOWED_RECORDING_MIME_TYPES))
    started_at = serializers.DateTimeField(required=False)

    def validate_started_at(self, value):
        now = timezone.now()
        if value > now + timedelta(minutes=5):
            raise serializers.ValidationError('기기 시간을 확인한 뒤 다시 시작해 주세요.')
        return value


class UploadedPartSerializer(serializers.Serializer):
    part_number = serializers.IntegerField(min_value=1, max_value=10_000)
    etag = serializers.CharField(max_length=200, trim_whitespace=False)
    byte_size = serializers.IntegerField(min_value=1)


class CompleteUploadRequestSerializer(serializers.Serializer):
    parts = UploadedPartSerializer(many=True, allow_empty=False)
    ended_at = serializers.DateTimeField(required=False)

    def validate_ended_at(self, value):
        if value > timezone.now() + timedelta(minutes=5):
            raise serializers.ValidationError('기기 시간을 확인한 뒤 다시 완료해 주세요.')
        return value

    def validate_parts(self, value):
        max_parts = (
            settings.CONSULTATION_MAX_BYTES
            + settings.CONSULTATION_UPLOAD_PART_BYTES
            - 1
        ) // settings.CONSULTATION_UPLOAD_PART_BYTES
        if len(value) > max_parts:
            raise serializers.ValidationError('녹음 파일 크기를 확인해 주세요.')
        return value
