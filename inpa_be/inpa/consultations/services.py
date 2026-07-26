import hashlib
import tempfile
from dataclasses import dataclass
from datetime import timedelta

import av
from av.error import FFmpegError
from botocore.exceptions import ClientError
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from inpa.customers.models import Customer

from .models import (
    ConsultationRecording,
    ConsultationRuntimeConfig,
)
from .storage import (
    InvalidMultipartParts,
    R2RecordingStorage,
    UploadedPart,
    validate_parts,
)

ALLOWED_RECORDING_MIME_TYPES = {
    'audio/mp4',
    'audio/ogg',
    'audio/ogg;codecs=opus',
    'audio/webm',
    'audio/webm;codecs=opus',
}


class ConsultationServiceError(RuntimeError):
    def __init__(self, code, detail, status_code):
        super().__init__(code)
        self.code = code
        self.detail = detail
        self.status_code = status_code


class InvalidRecording(ConsultationServiceError):
    def __init__(self, code, detail='녹음 파일을 확인한 뒤 다시 시도해 주세요.'):
        super().__init__(code, detail, 400)


@dataclass(frozen=True)
class AudioInspection:
    byte_size: int
    duration_ms: int
    codec: str
    checksum: str


def get_recording_storage():
    return R2RecordingStorage.from_settings()


def max_part_number():
    return (
        settings.CONSULTATION_MAX_BYTES
        + settings.CONSULTATION_UPLOAD_PART_BYTES
        - 1
    ) // settings.CONSULTATION_UPLOAD_PART_BYTES


def inspect_audio(chunks):
    """Inspect actual media bytes without retaining a source file after return."""
    hasher = hashlib.sha256()
    with tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024) as temp:
        size = 0
        for chunk in chunks:
            if not isinstance(chunk, bytes):
                raise InvalidRecording('RECORDING_BYTES_INVALID')
            size += len(chunk)
            if size > settings.CONSULTATION_MAX_BYTES:
                raise InvalidRecording('RECORDING_TOO_LARGE')
            hasher.update(chunk)
            temp.write(chunk)
        if size <= 0:
            raise InvalidRecording('RECORDING_EMPTY')
        temp.seek(0)
        try:
            with av.open(temp, mode='r') as container:
                audio_streams = [
                    stream for stream in container.streams
                    if stream.type == 'audio'
                ]
                if (
                    len(audio_streams) != 1
                    or any(stream.type == 'video' for stream in container.streams)
                ):
                    raise InvalidRecording('AUDIO_ONLY_REQUIRED')
                stream = audio_streams[0]
                duration_seconds = 0.0
                if container.duration:
                    duration_seconds = container.duration / av.time_base
                elif stream.duration is not None and stream.time_base is not None:
                    duration_seconds = float(stream.duration * stream.time_base)
                codec = stream.codec_context.name or ''
        except InvalidRecording:
            raise
        except (FFmpegError, ValueError, EOFError) as exc:
            raise InvalidRecording('RECORDING_FORMAT_INVALID') from exc

        duration_ms = int(round(duration_seconds * 1000))
        if (
            duration_ms <= 0
            or duration_ms > settings.CONSULTATION_MAX_DURATION_SECONDS * 1000
        ):
            raise InvalidRecording('RECORDING_DURATION_INVALID')
        return AudioInspection(
            byte_size=size,
            duration_ms=duration_ms,
            codec=codec,
            checksum=f'sha256:{hasher.hexdigest()}',
        )


def create_upload_session(*, owner, customer, mime_type, started_at):
    storage = get_recording_storage()
    session = None
    try:
        with transaction.atomic():
            config = ConsultationRuntimeConfig.objects.select_for_update().get(pk=1)
            locked_customer = Customer.objects.select_for_update().get(
                pk=customer.pk,
                owner=customer.owner,
            )
            if ConsultationRecording.objects.filter(
                owner=owner,
                customer=locked_customer,
                status=ConsultationRecording.STATUS_UPLOADING,
            ).exists():
                raise ConsultationServiceError(
                    'ACTIVE_RECORDING_EXISTS',
                    '진행 중인 녹음을 마치면 새 녹음을 시작할 수 있어요.',
                    409,
                )
            if ConsultationRecording.objects.filter(
                status=ConsultationRecording.STATUS_UPLOADING,
            ).count() >= config.global_active_limit:
                raise ConsultationServiceError(
                    'RECORDING_CAPACITY_REACHED',
                    '잠시 후 다시 시작하면 바로 녹음할 수 있어요.',
                    503,
                )
            recording = ConsultationRecording.objects.create(
                owner=owner,
                customer=locked_customer,
                mime_type=mime_type,
                started_at=started_at or timezone.now(),
            )
            session = storage.create(recording.id, mime_type)
            recording.storage_key = session.key
            recording.multipart_upload_id = session.upload_id
            recording.save(update_fields=[
                'storage_key',
                'multipart_upload_id',
                'updated_at',
            ])
            return recording
    except IntegrityError as exc:
        if session is not None:
            try:
                storage.abort(session.key, session.upload_id)
            except Exception:
                pass
        raise ConsultationServiceError(
            'ACTIVE_RECORDING_EXISTS',
            '진행 중인 녹음을 마치면 새 녹음을 시작할 수 있어요.',
            409,
        ) from exc
    except Exception:
        if session is not None:
            try:
                storage.abort(session.key, session.upload_id)
            except Exception:
                pass
        raise


def create_part_url(*, recording, part_number):
    if recording.status != ConsultationRecording.STATUS_UPLOADING:
        raise ConsultationServiceError(
            'RECORDING_UPLOAD_FINISHED',
            '업로드를 마친 녹음이에요.',
            409,
        )
    if not 1 <= part_number <= max_part_number():
        raise ConsultationServiceError(
            'INVALID_PART_NUMBER',
            '녹음 파일 크기를 확인해 주세요.',
            400,
        )
    return get_recording_storage().presign_part(
        recording.storage_key,
        recording.multipart_upload_id,
        part_number,
    )


def _delete_invalid_completed_source(recording, storage, reason):
    now = timezone.now()
    try:
        storage.delete(recording.storage_key)
    except Exception:
        recording.status = ConsultationRecording.STATUS_DELETING
        recording.delete_result = 'retry_required'
    else:
        recording.status = ConsultationRecording.STATUS_DELETED
        recording.storage_key = None
        recording.deleted_at = now
        recording.delete_result = 'verified'
    recording.delete_reason = reason
    recording.multipart_upload_id = ''
    recording.version += 1
    recording.save(update_fields=[
        'status',
        'storage_key',
        'multipart_upload_id',
        'deleted_at',
        'delete_reason',
        'delete_result',
        'version',
        'updated_at',
    ])


def complete_upload(*, recording_id, owner, customer, parts, ended_at):
    uploaded_parts = [
        UploadedPart(
            part_number=item['part_number'],
            etag=item['etag'],
            byte_size=item['byte_size'],
        )
        for item in parts
    ]
    try:
        ordered = validate_parts(
            uploaded_parts,
            part_bytes=settings.CONSULTATION_UPLOAD_PART_BYTES,
            max_bytes=settings.CONSULTATION_MAX_BYTES,
        )
    except InvalidMultipartParts as exc:
        raise InvalidRecording(str(exc)) from exc

    storage = get_recording_storage()
    validation_error = None
    with transaction.atomic():
        recording = ConsultationRecording.objects.select_for_update().get(
            pk=recording_id,
            owner=owner,
            customer=customer,
        )
        if recording.status != ConsultationRecording.STATUS_UPLOADING:
            return recording

        expected_size = sum(part.byte_size for part in ordered)
        try:
            storage.complete(
                recording.storage_key,
                recording.multipart_upload_id,
                ordered,
            )
        except ClientError:
            try:
                head = storage.head(recording.storage_key)
            except ClientError:
                raise
            if head.get('ContentLength') != expected_size:
                raise

        try:
            head = storage.head(recording.storage_key)
            if head.get('ContentLength') != expected_size:
                raise InvalidRecording('RECORDING_SIZE_MISMATCH')
            inspection = inspect_audio(
                storage.iter_object(recording.storage_key),
            )
            if inspection.byte_size != expected_size:
                raise InvalidRecording('RECORDING_SIZE_MISMATCH')
        except InvalidRecording as exc:
            _delete_invalid_completed_source(
                recording,
                storage,
                reason='validation_failed',
            )
            validation_error = exc
        else:
            actual_end = min(ended_at or timezone.now(), timezone.now())
            if recording.started_at and actual_end < recording.started_at:
                actual_end = recording.started_at + timedelta(
                    milliseconds=inspection.duration_ms,
                )
                actual_end = min(actual_end, timezone.now())
            recording.mark_ready(
                ended_at=actual_end,
                byte_size=inspection.byte_size,
                duration_ms=inspection.duration_ms,
                codec=inspection.codec,
                checksum=inspection.checksum,
            )
    if validation_error is not None:
        raise validation_error
    return recording


def create_play_url(*, recording):
    if recording.status == ConsultationRecording.STATUS_UPLOADING:
        raise ConsultationServiceError(
            'RECORDING_NOT_READY',
            '녹음을 마치면 원본을 바로 재생할 수 있어요.',
            409,
        )
    if (
        not recording.storage_key
        or recording.status in (
            ConsultationRecording.STATUS_DELETING,
            ConsultationRecording.STATUS_DELETED,
        )
        or (recording.expires_at and recording.expires_at <= timezone.now())
    ):
        raise ConsultationServiceError(
            'RECORDING_SOURCE_EXPIRED',
            '원본 녹음 보관을 마쳤어요. 정리된 상담 메모를 확인해 주세요.',
            410,
        )
    return get_recording_storage().presign_get(recording.storage_key)


def delete_source(*, recording_id, owner, customer, reason):
    storage = get_recording_storage()
    with transaction.atomic():
        recording = ConsultationRecording.objects.select_for_update().get(
            pk=recording_id,
            owner=owner,
            customer=customer,
        )
        if recording.status == ConsultationRecording.STATUS_DELETED:
            return recording
        key = recording.storage_key
        upload_id = recording.multipart_upload_id
        was_uploading = recording.status == ConsultationRecording.STATUS_UPLOADING
        recording.status = ConsultationRecording.STATUS_DELETING
        recording.delete_reason = reason
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
        if was_uploading and upload_id:
            storage.abort(key, upload_id)
        if key:
            storage.delete(key)
    except Exception as exc:
        raise ConsultationServiceError(
            'RECORDING_DELETE_RETRY',
            '삭제 요청을 접수했어요. 원본 확인이 끝나면 자동으로 반영됩니다.',
            503,
        ) from exc

    with transaction.atomic():
        recording = ConsultationRecording.objects.select_for_update().get(
            pk=recording_id,
            owner=owner,
            customer=customer,
        )
        recording.status = ConsultationRecording.STATUS_DELETED
        recording.storage_key = None
        recording.multipart_upload_id = ''
        recording.deleted_at = timezone.now()
        recording.delete_result = 'verified'
        recording.version += 1
        recording.save(update_fields=[
            'status',
            'storage_key',
            'multipart_upload_id',
            'deleted_at',
            'delete_result',
            'version',
            'updated_at',
        ])
    return recording
