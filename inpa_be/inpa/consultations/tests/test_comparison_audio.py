import io
import wave

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings

from inpa.consultations.comparison_audio import (
    ComparisonAudioError,
    prepare_comparison_audio,
)


def make_wav(seconds: int, sample_rate: int = 16_000) -> bytes:
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b'\x00\x00' * sample_rate * seconds)
    return output.getvalue()


@override_settings(
    CONSULTATION_COMPARISON_MAX_BYTES=1024 * 1024,
    CONSULTATION_COMPARISON_MAX_DURATION_SECONDS=300,
)
class ComparisonAudioTests(SimpleTestCase):
    def test_rejects_unsupported_extension_before_temp_file_is_used(self):
        upload = SimpleUploadedFile('synthetic.txt', b'not audio')

        with self.assertRaisesRegex(ComparisonAudioError, 'AUDIO_FORMAT_UNSUPPORTED'):
            with prepare_comparison_audio(upload):
                self.fail('unsupported audio reached provider boundary')

    def test_removes_temp_file_after_success(self):
        upload = SimpleUploadedFile('synthetic.wav', make_wav(seconds=1))

        with prepare_comparison_audio(upload) as prepared:
            path = prepared.path
            self.assertTrue(path.exists())
            self.assertGreater(prepared.duration_seconds, 0)

        self.assertFalse(path.exists())

    def test_removes_temp_file_when_consumer_raises(self):
        upload = SimpleUploadedFile('synthetic.wav', make_wav(seconds=1))

        with self.assertRaisesRegex(RuntimeError, 'provider failed'):
            with prepare_comparison_audio(upload) as prepared:
                path = prepared.path
                raise RuntimeError('provider failed')

        self.assertFalse(path.exists())
