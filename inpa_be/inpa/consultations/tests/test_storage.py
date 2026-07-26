import uuid
from unittest.mock import MagicMock

from botocore.exceptions import ClientError
from django.test import SimpleTestCase, override_settings

from inpa.consultations.storage import (
    InvalidMultipartParts,
    MultipartSession,
    R2RecordingStorage,
    RecordingDeleteVerificationFailed,
    UploadedPart,
    validate_parts,
)


class MultipartValidationTests(SimpleTestCase):
    def test_accepts_contiguous_full_parts_and_one_smaller_final_part(self):
        parts = [
            UploadedPart(part_number=2, etag='"two"', byte_size=1024),
            UploadedPart(part_number=1, etag='"one"', byte_size=8 * 1024 * 1024),
        ]

        ordered = validate_parts(
            parts,
            part_bytes=8 * 1024 * 1024,
            max_bytes=100 * 1024 * 1024,
        )

        self.assertEqual([part.part_number for part in ordered], [1, 2])

    def test_rejects_missing_duplicate_small_middle_or_oversized_total_parts(self):
        invalid_sets = [
            [UploadedPart(2, '"two"', 1)],
            [UploadedPart(1, '"one"', 1), UploadedPart(1, '"again"', 1)],
            [
                UploadedPart(1, '"one"', 4 * 1024 * 1024),
                UploadedPart(2, '"two"', 1024),
            ],
            [
                UploadedPart(1, '"one"', 8 * 1024 * 1024),
                UploadedPart(2, '"two"', 8 * 1024 * 1024),
            ],
        ]

        for parts in invalid_sets:
            with self.subTest(parts=parts), self.assertRaises(InvalidMultipartParts):
                validate_parts(
                    parts,
                    part_bytes=8 * 1024 * 1024,
                    max_bytes=9 * 1024 * 1024,
                )

    def test_rejects_empty_or_too_large_final_part(self):
        for size in (0, 8 * 1024 * 1024 + 1):
            with self.subTest(size=size), self.assertRaises(InvalidMultipartParts):
                validate_parts(
                    [UploadedPart(1, '"one"', size)],
                    part_bytes=8 * 1024 * 1024,
                    max_bytes=100 * 1024 * 1024,
                )


@override_settings(
    CONSULTATION_PRESIGN_TTL_SECONDS=600,
    CONSULTATION_UPLOAD_PART_BYTES=8 * 1024 * 1024,
    CONSULTATION_MAX_BYTES=100 * 1024 * 1024,
)
class R2RecordingStorageTests(SimpleTestCase):
    def setUp(self):
        self.client = MagicMock()
        self.storage = R2RecordingStorage(client=self.client, bucket='private-audio')

    def test_create_uses_uuid_only_namespace(self):
        recording_id = uuid.uuid4()
        self.client.create_multipart_upload.return_value = {'UploadId': 'upload-1'}

        result = self.storage.create(recording_id, 'audio/webm')

        self.assertEqual(
            result,
            MultipartSession(
                key=f'consultation-recordings/{recording_id}/source',
                upload_id='upload-1',
            ),
        )
        self.assertNotIn('@', result.key)
        self.client.create_multipart_upload.assert_called_once_with(
            Bucket='private-audio',
            Key=result.key,
            ContentType='audio/webm',
            Metadata={'retention': '7-days'},
        )

    def test_presign_part_uses_short_ttl_and_scoped_parameters(self):
        key = f'consultation-recordings/{uuid.uuid4()}/source'
        self.client.generate_presigned_url.return_value = 'https://upload.example'

        url = self.storage.presign_part(key, 'upload-1', part_number=1)

        self.assertEqual(url, 'https://upload.example')
        self.client.generate_presigned_url.assert_called_once_with(
            'upload_part',
            Params={
                'Bucket': 'private-audio',
                'Key': key,
                'UploadId': 'upload-1',
                'PartNumber': 1,
            },
            ExpiresIn=600,
        )

    def test_complete_validates_and_sends_ordered_part_etags(self):
        key = f'consultation-recordings/{uuid.uuid4()}/source'
        parts = [
            UploadedPart(2, '"two"', 1024),
            UploadedPart(1, '"one"', 8 * 1024 * 1024),
        ]

        self.storage.complete(key, 'upload-1', parts)

        self.client.complete_multipart_upload.assert_called_once_with(
            Bucket='private-audio',
            Key=key,
            UploadId='upload-1',
            MultipartUpload={
                'Parts': [
                    {'PartNumber': 1, 'ETag': '"one"'},
                    {'PartNumber': 2, 'ETag': '"two"'},
                ],
            },
        )

    def test_delete_verifies_object_is_absent(self):
        key = f'consultation-recordings/{uuid.uuid4()}/source'
        self.client.head_object.side_effect = ClientError(
            {
                'Error': {'Code': '404', 'Message': 'Not Found'},
                'ResponseMetadata': {'HTTPStatusCode': 404},
            },
            'HeadObject',
        )

        self.storage.delete(key)

        self.client.delete_object.assert_called_once_with(
            Bucket='private-audio',
            Key=key,
        )

    def test_abort_treats_already_missing_multipart_upload_as_success(self):
        key = f'consultation-recordings/{uuid.uuid4()}/source'
        self.client.abort_multipart_upload.side_effect = ClientError(
            {
                'Error': {'Code': 'NoSuchUpload', 'Message': 'Missing'},
                'ResponseMetadata': {'HTTPStatusCode': 404},
            },
            'AbortMultipartUpload',
        )

        self.storage.abort(key, 'upload-1')

    def test_delete_raises_when_object_still_exists(self):
        key = f'consultation-recordings/{uuid.uuid4()}/source'
        self.client.head_object.return_value = {'ContentLength': 10}

        with self.assertRaises(RecordingDeleteVerificationFailed):
            self.storage.delete(key)

    def test_rejects_key_outside_recording_namespace(self):
        with self.assertRaises(ValueError):
            self.storage.presign_get('customer-name/audio.webm')
