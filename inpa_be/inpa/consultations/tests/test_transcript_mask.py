from django.test import SimpleTestCase

from inpa.consultations.transcript_mask import (
    UnsafeTranscript,
    mask_transcript,
)


class TranscriptMaskTests(SimpleTestCase):
    def test_removes_known_names_phone_email_resident_and_account_numbers(self):
        raw = (
            '홍길동 고객 010-2468-1357, abc@example.com, '
            '900101-1234567, 계좌 110-123-456789'
        )

        result = mask_transcript(raw, known_names=['홍길동'])

        for value in (
            '홍길동',
            '010-2468-1357',
            'abc@example.com',
            '900101-1234567',
            '110-123-456789',
        ):
            self.assertNotIn(value, result.text)
        self.assertTrue(result.residual_scan_passed)
        self.assertIn('[이름_1]', result.text)

    def test_empty_or_excessive_transcript_fails_closed(self):
        with self.assertRaises(UnsafeTranscript):
            mask_transcript('   ', known_names=[])
        with self.assertRaises(UnsafeTranscript):
            mask_transcript('가' * 120_001, known_names=[])
