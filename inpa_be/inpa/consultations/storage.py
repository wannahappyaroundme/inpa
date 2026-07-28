"""Private object storage for consultation source recordings.

Keys are server-owned UUID namespaces. Customer names, emails, phone numbers,
and other identifying text must never enter object keys or metadata.
"""

import re
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from dataclasses import dataclass

import boto3
from botocore.exceptions import ClientError
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

DEFAULT_STREAM_CHUNK_BYTES = 1_048_576


class InvalidMultipartParts(ValueError):
    pass


class RecordingDeleteVerificationFailed(RuntimeError):
    pass


@dataclass(frozen=True)
class MultipartSession:
    key: str
    upload_id: str


@dataclass(frozen=True)
class UploadedPart:
    part_number: int
    etag: str
    byte_size: int


def recording_id_from_key(key):
    prefix = 'consultation-recordings/'
    suffix = '/source'
    if not isinstance(key, str) or not key.startswith(prefix) or not key.endswith(suffix):
        return None
    raw = key[len(prefix):-len(suffix)]
    try:
        parsed = uuid.UUID(raw)
    except (TypeError, ValueError):
        return None
    return parsed if str(parsed) == raw else None


def validate_parts(parts, *, part_bytes, max_bytes):
    """Return ordered parts only when the client manifest is structurally safe."""
    if part_bytes <= 0 or max_bytes <= 0:
        raise InvalidMultipartParts('INVALID_STORAGE_LIMIT')
    ordered = sorted(parts, key=lambda item: item.part_number)
    expected_numbers = list(range(1, len(ordered) + 1))
    if not ordered or [item.part_number for item in ordered] != expected_numbers:
        raise InvalidMultipartParts('INVALID_PART_SEQUENCE')
    if any(
        not item.etag
        or len(item.etag) > 200
        or '\r' in item.etag
        or '\n' in item.etag
        for item in ordered
    ):
        raise InvalidMultipartParts('INVALID_PART_ETAG')
    if any(item.byte_size != part_bytes for item in ordered[:-1]):
        raise InvalidMultipartParts('INVALID_NONFINAL_PART_SIZE')
    if ordered[-1].byte_size <= 0 or ordered[-1].byte_size > part_bytes:
        raise InvalidMultipartParts('INVALID_FINAL_PART_SIZE')
    if sum(item.byte_size for item in ordered) > max_bytes:
        raise InvalidMultipartParts('RECORDING_TOO_LARGE')
    return ordered


class R2RecordingStorage:
    prefix = 'consultation-recordings'
    _key_pattern = re.compile(
        r'^consultation-recordings/'
        r'([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})'
        r'/source$',
    )
    _download_filename_pattern = re.compile(
        r'^consultation-recording-[0-9]{8}\.(webm|ogg|m4a)$',
    )

    def __init__(self, *, client, bucket):
        if not bucket:
            raise ImproperlyConfigured('CONSULTATION_STORAGE_BUCKET is required')
        self.client = client
        self.bucket = bucket

    @classmethod
    def from_settings(cls):
        required = {
            'bucket': settings.CONSULTATION_STORAGE_BUCKET,
            'endpoint': settings.CONSULTATION_STORAGE_ENDPOINT,
            'access_key': settings.CONSULTATION_STORAGE_ACCESS_KEY_ID,
            'secret_key': settings.CONSULTATION_STORAGE_SECRET_ACCESS_KEY,
        }
        if any(not value for value in required.values()):
            raise ImproperlyConfigured(
                'Consultation recording storage credentials are incomplete',
            )
        client = boto3.client(
            's3',
            endpoint_url=required['endpoint'],
            region_name=settings.CONSULTATION_STORAGE_REGION,
            aws_access_key_id=required['access_key'],
            aws_secret_access_key=required['secret_key'],
        )
        return cls(client=client, bucket=required['bucket'])

    def _validate_key(self, key):
        match = self._key_pattern.fullmatch(key or '')
        if match is None:
            raise ValueError('INVALID_RECORDING_STORAGE_KEY')
        if str(uuid.UUID(match.group(1))) != match.group(1):
            raise ValueError('INVALID_RECORDING_STORAGE_KEY')
        return key

    def iter_keys(self):
        paginator = self.client.get_paginator('list_objects_v2')
        for page in paginator.paginate(
            Bucket=self.bucket,
            Prefix=f'{self.prefix}/',
        ):
            for item in page.get('Contents', []):
                key = item.get('Key')
                if recording_id_from_key(key) is not None:
                    yield key

    @staticmethod
    def _validate_upload_id(upload_id):
        if not upload_id or len(upload_id) > 512 or '\r' in upload_id or '\n' in upload_id:
            raise ValueError('INVALID_MULTIPART_UPLOAD_ID')

    def create(
        self,
        recording_id,
        mime_type,
        *,
        retention_hours,
        retention_days,
        retention_policy_version,
    ):
        recording_uuid = uuid.UUID(str(recording_id))
        key = f'{self.prefix}/{recording_uuid}/source'
        response = self.client.create_multipart_upload(
            Bucket=self.bucket,
            Key=key,
            ContentType=mime_type,
            Metadata={
                'retention': f'{retention_days}-days',
                'retention-hours': str(retention_hours),
                'retention-days': str(retention_days),
                'retention-policy': retention_policy_version,
            },
        )
        upload_id = response.get('UploadId', '')
        self._validate_upload_id(upload_id)
        return MultipartSession(key=key, upload_id=upload_id)

    def presign_part(self, key, upload_id, part_number):
        self._validate_key(key)
        self._validate_upload_id(upload_id)
        if not isinstance(part_number, int) or not 1 <= part_number <= 10_000:
            raise ValueError('INVALID_PART_NUMBER')
        return self.client.generate_presigned_url(
            'upload_part',
            Params={
                'Bucket': self.bucket,
                'Key': key,
                'UploadId': upload_id,
                'PartNumber': part_number,
            },
            ExpiresIn=settings.CONSULTATION_PRESIGN_TTL_SECONDS,
        )

    def complete(self, key, upload_id, parts):
        self._validate_key(key)
        self._validate_upload_id(upload_id)
        ordered = validate_parts(
            parts,
            part_bytes=settings.CONSULTATION_UPLOAD_PART_BYTES,
            max_bytes=settings.CONSULTATION_MAX_BYTES,
        )
        return self.client.complete_multipart_upload(
            Bucket=self.bucket,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={
                'Parts': [
                    {'PartNumber': part.part_number, 'ETag': part.etag}
                    for part in ordered
                ],
            },
        )

    def abort(self, key, upload_id):
        self._validate_key(key)
        self._validate_upload_id(upload_id)
        try:
            return self.client.abort_multipart_upload(
                Bucket=self.bucket,
                Key=key,
                UploadId=upload_id,
            )
        except ClientError as exc:
            status_code = exc.response.get('ResponseMetadata', {}).get('HTTPStatusCode')
            error_code = exc.response.get('Error', {}).get('Code')
            if status_code == 404 or error_code in {'404', 'NoSuchUpload', 'NotFound'}:
                return None
            raise

    def head(self, key):
        self._validate_key(key)
        return self.client.head_object(Bucket=self.bucket, Key=key)

    def iter_object(self, key, chunk_size=DEFAULT_STREAM_CHUNK_BYTES):
        self._validate_key(key)
        if chunk_size <= 0:
            raise ValueError('INVALID_CHUNK_SIZE')
        body = self.client.get_object(Bucket=self.bucket, Key=key)['Body']
        try:
            while True:
                chunk = body.read(chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            body.close()

    @contextmanager
    def open_temp(self, key, chunk_size=DEFAULT_STREAM_CHUNK_BYTES):
        """Download one exact recording into an ephemeral, private temp file."""
        self._validate_key(key)
        if chunk_size <= 0:
            raise ValueError('INVALID_CHUNK_SIZE')
        with tempfile.TemporaryDirectory(
            prefix='inpa-consultation-source-',
        ) as temp_dir:
            path = Path(temp_dir) / 'source'
            with path.open('xb') as target:
                for chunk in self.iter_object(key, chunk_size=chunk_size):
                    target.write(chunk)
            yield path

    def presign_get(self, key):
        self._validate_key(key)
        return self.client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': self.bucket,
                'Key': key,
                'ResponseContentDisposition': 'inline',
            },
            ExpiresIn=300,
        )

    def presign_download(self, key, filename):
        self._validate_key(key)
        if self._download_filename_pattern.fullmatch(filename or '') is None:
            raise ValueError('INVALID_RECORDING_DOWNLOAD_FILENAME')
        return self.client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': self.bucket,
                'Key': key,
                'ResponseContentDisposition': (
                    f'attachment; filename="{filename}"'
                ),
            },
            ExpiresIn=300,
        )

    def delete(self, key):
        self._validate_key(key)
        self.client.delete_object(Bucket=self.bucket, Key=key)
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            status_code = exc.response.get('ResponseMetadata', {}).get('HTTPStatusCode')
            error_code = exc.response.get('Error', {}).get('Code')
            if status_code == 404 or error_code in {'404', 'NoSuchKey', 'NotFound'}:
                return
            raise
        raise RecordingDeleteVerificationFailed('RECORDING_OBJECT_STILL_EXISTS')
