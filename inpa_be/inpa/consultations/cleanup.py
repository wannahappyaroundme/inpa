"""Retention deletion for consultation source recordings.

Selection uses only server-stamped expiry, source-present state, and exact UUID
keys. User-editable dates and memo text never participate.
"""

import logging

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import ConsultationRecording, ConsultationRuntimeConfig
from .services import get_recording_storage

logger = logging.getLogger(__name__)

SOURCE_PRESENT_STATUSES = {
    ConsultationRecording.STATUS_UPLOADING,
    ConsultationRecording.STATUS_READY,
    ConsultationRecording.STATUS_PROCESSING,
    ConsultationRecording.STATUS_COMPLETED,
    ConsultationRecording.STATUS_FAILED,
    ConsultationRecording.STATUS_AMBIGUOUS,
    ConsultationRecording.STATUS_DELETING,
}
DELETE_FAILURE_CIRCUIT_THRESHOLD = 3


def mark_source_deleted(recording_id, *, reason, now):
    with transaction.atomic():
        recording = ConsultationRecording.objects.select_for_update().get(
            pk=recording_id,
        )
        if recording.status == ConsultationRecording.STATUS_DELETED:
            return recording
        recording.status = ConsultationRecording.STATUS_DELETED
        recording.storage_key = None
        recording.multipart_upload_id = ''
        recording.checksum = ''
        recording.deleted_at = now
        recording.delete_reason = reason
        recording.delete_result = 'verified_absent'
        recording.last_delete_attempt_at = now
        recording.last_delete_error_type = ''
        recording.version += 1
        recording.save(update_fields=[
            'status',
            'storage_key',
            'multipart_upload_id',
            'checksum',
            'deleted_at',
            'delete_reason',
            'delete_result',
            'last_delete_attempt_at',
            'last_delete_error_type',
            'version',
            'updated_at',
        ])
        return recording


def record_delete_failure(recording_id, *, error_type, now):
    with transaction.atomic():
        recording = ConsultationRecording.objects.select_for_update().get(
            pk=recording_id,
        )
        if recording.status == ConsultationRecording.STATUS_DELETED:
            return None
        recording.status = ConsultationRecording.STATUS_DELETING
        recording.delete_attempts += 1
        recording.delete_result = 'retry_required'
        recording.last_delete_attempt_at = now
        recording.last_delete_error_type = error_type[:80]
        recording.version += 1
        recording.save(update_fields=[
            'status',
            'delete_attempts',
            'delete_result',
            'last_delete_attempt_at',
            'last_delete_error_type',
            'version',
            'updated_at',
        ])
        attempts = recording.delete_attempts
    if attempts >= DELETE_FAILURE_CIRCUIT_THRESHOLD:
        ConsultationRuntimeConfig.objects.filter(
            pk=1,
            recording_enabled=True,
        ).update(recording_enabled=False, updated_at=now)
    logger.error(
        'consultation source delete failed recording_id=%s error_type=%s attempts=%s',
        recording_id,
        error_type,
        attempts,
    )
    return attempts


def delete_recording_source(recording_id, *, reason, storage=None, now=None):
    now = now or timezone.now()
    storage = storage or get_recording_storage()
    with transaction.atomic():
        recording = ConsultationRecording.objects.select_for_update().get(
            pk=recording_id,
        )
        if recording.status == ConsultationRecording.STATUS_DELETED:
            return 'deleted'
        from .summary_worker import cancel_recording_summary
        cancel_recording_summary(
            recording.id,
            reason='RECORDING_SOURCE_DELETED',
        )
        effective_reason = (
            recording.delete_reason
            if (
                recording.status == ConsultationRecording.STATUS_DELETING
                and recording.delete_reason
            )
            else reason
        )
        exact_key = recording.storage_key
        upload_id = recording.multipart_upload_id
        if not exact_key:
            mark_source_deleted(
                recording_id,
                reason=effective_reason,
                now=now,
            )
            return 'deleted'
        recording.status = ConsultationRecording.STATUS_DELETING
        recording.delete_reason = effective_reason
        recording.delete_result = 'pending'
        recording.version += 1
        recording.save(update_fields=[
            'status',
            'delete_reason',
            'delete_result',
            'version',
            'updated_at',
        ])
    try:
        if upload_id:
            storage.abort(exact_key, upload_id)
        storage.delete(exact_key)
    except Exception as exc:
        attempts = record_delete_failure(
            recording_id,
            error_type=type(exc).__name__,
            now=now,
        )
        if attempts is None:
            return 'deleted'
        return 'failed'
    mark_source_deleted(
        recording_id,
        reason=effective_reason,
        now=now,
    )
    return 'deleted'


def cleanup_expired_recordings(*, now=None, limit=200, storage=None):
    now = now or timezone.now()
    safe_limit = max(1, min(int(limit), 1000))
    expired = Q(
        expires_at__isnull=False,
        expires_at__lte=now,
        status__in=SOURCE_PRESENT_STATUSES,
    )
    retry_required = Q(
        status=ConsultationRecording.STATUS_DELETING,
        delete_result='retry_required',
    )
    ids = list(
        ConsultationRecording.objects.filter(
            storage_key__isnull=False,
        )
        .filter(expired | retry_required)
        .order_by('expires_at')
        .values_list('id', flat=True)[:safe_limit]
    )
    result = {
        'selected': len(ids),
        'deleted': 0,
        'failed': 0,
        'skipped': 0,
    }
    if not ids:
        return result
    storage = storage or get_recording_storage()
    for recording_id in ids:
        with transaction.atomic():
            recording = ConsultationRecording.objects.select_for_update().get(
                pk=recording_id,
            )
            is_expired = (
                recording.expires_at is not None
                and recording.expires_at <= now
                and recording.status in SOURCE_PRESENT_STATUSES
            )
            needs_retry = (
                recording.status == ConsultationRecording.STATUS_DELETING
                and recording.delete_result == 'retry_required'
            )
            if not recording.storage_key or not (is_expired or needs_retry):
                result['skipped'] += 1
                continue
        outcome = delete_recording_source(
            recording_id,
            reason='retention_expired',
            storage=storage,
            now=now,
        )
        result[outcome] += 1
    return result
