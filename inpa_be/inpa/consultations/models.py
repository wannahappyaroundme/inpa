import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class ConsultationRecording(models.Model):
    STATUS_UPLOADING = 'uploading'
    STATUS_READY = 'ready'
    STATUS_PROCESSING = 'processing'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'
    STATUS_AMBIGUOUS = 'ambiguous'
    STATUS_DELETING = 'deleting'
    STATUS_DELETED = 'deleted'
    STATUS_CHOICES = tuple((value, value) for value in (
        STATUS_UPLOADING,
        STATUS_READY,
        STATUS_PROCESSING,
        STATUS_COMPLETED,
        STATUS_FAILED,
        STATUS_AMBIGUOUS,
        STATUS_DELETING,
        STATUS_DELETED,
    ))

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='consultation_recordings',
    )
    customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.CASCADE,
        related_name='consultation_recordings',
    )
    client_session_id = models.UUIDField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_UPLOADING,
        db_index=True,
    )
    storage_key = models.CharField(
        max_length=180,
        unique=True,
        null=True,
        blank=True,
    )
    multipart_upload_id = models.CharField(max_length=512, blank=True, default='')
    mime_type = models.CharField(max_length=80)
    codec = models.CharField(max_length=80, blank=True, default='')
    byte_size = models.PositiveBigIntegerField(default=0)
    duration_ms = models.PositiveBigIntegerField(default=0)
    checksum = models.CharField(max_length=100, blank=True, default='')
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    uploaded_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    delete_reason = models.CharField(max_length=40, blank=True, default='')
    delete_result = models.CharField(max_length=40, blank=True, default='')
    delete_attempts = models.PositiveSmallIntegerField(default=0)
    last_delete_attempt_at = models.DateTimeField(null=True, blank=True)
    last_delete_error_type = models.CharField(max_length=80, blank=True, default='')
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'consultation_recording'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['owner', 'customer', '-created_at']),
            models.Index(fields=['status', 'expires_at']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['owner', 'customer'],
                condition=models.Q(status='uploading'),
                name='uniq_active_consultation_upload',
            ),
            models.UniqueConstraint(
                fields=['owner', 'client_session_id'],
                condition=models.Q(client_session_id__isnull=False),
                name='uniq_consultation_client_session',
            ),
        ]

    def mark_ready(
        self,
        *,
        ended_at,
        byte_size,
        duration_ms,
        checksum,
        codec='',
    ):
        if self.status != self.STATUS_UPLOADING:
            raise ValueError('INVALID_RECORDING_TRANSITION')
        retention = timedelta(
            hours=max(1, min(settings.CONSULTATION_RETENTION_HOURS, 168)),
        )
        requested_safety = timedelta(
            minutes=max(settings.CONSULTATION_RETENTION_SAFETY_MINUTES, 15),
        )
        safety = min(requested_safety, retention - timedelta(minutes=1))
        self.status = self.STATUS_READY
        self.ended_at = ended_at
        self.uploaded_at = timezone.now()
        self.expires_at = ended_at + retention - safety
        self.byte_size = byte_size
        self.duration_ms = duration_ms
        self.codec = codec
        self.checksum = checksum
        self.multipart_upload_id = ''
        self.version += 1
        self.save(update_fields=[
            'status',
            'ended_at',
            'uploaded_at',
            'expires_at',
            'byte_size',
            'duration_ms',
            'codec',
            'checksum',
            'multipart_upload_id',
            'version',
            'updated_at',
        ])


class ConsultationRuntimeConfig(models.Model):
    recording_enabled = models.BooleanField(default=False)
    ai_summary_enabled = models.BooleanField(default=False)
    max_duration_seconds = models.PositiveIntegerField(default=3600)
    max_bytes = models.PositiveBigIntegerField(default=100 * 1024 * 1024)
    global_active_limit = models.PositiveSmallIntegerField(default=20)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'consultation_runtime_config'
        verbose_name = '상담 녹음 운영 설정'

    @classmethod
    def solo(cls):
        return cls.objects.get_or_create(
            pk=1,
            defaults={
                'max_duration_seconds': settings.CONSULTATION_MAX_DURATION_SECONDS,
                'max_bytes': settings.CONSULTATION_MAX_BYTES,
            },
        )[0]


class ConsultationPilotAccess(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='consultation_pilot_access',
    )
    recording_allowed = models.BooleanField(default=False)
    summary_allowed = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'consultation_pilot_access'
        verbose_name = '상담 녹음 파일럿 계정'
