import io
import tempfile
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings

from inpa.consultations.comparison import ConsultationComparisonService
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


class FakeContainer:
    def __init__(self, streams, frames=()):
        self.streams = streams
        self.frames = frames

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def decode(self, *, audio):
        if audio != 0:
            raise AssertionError('unexpected audio stream')
        return iter(self.frames)


@override_settings(
    CONSULTATION_COMPARISON_MAX_BYTES=1024 * 1024,
    CONSULTATION_COMPARISON_MAX_DURATION_SECONDS=300,
)
class ComparisonAudioTests(SimpleTestCase):
    def setUp(self):
        self.temp_root = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_root.cleanup)
        self.original_temporary_directory = tempfile.TemporaryDirectory

    def _tracked_temporary_directory(self, *args, **kwargs):
        kwargs['dir'] = self.temp_root.name
        return self.original_temporary_directory(*args, **kwargs)

    def _assert_rejected_and_cleaned(self, upload, expected_code):
        with patch(
            'inpa.consultations.comparison_audio.tempfile.TemporaryDirectory',
            side_effect=self._tracked_temporary_directory,
        ):
            with self.assertRaises(ComparisonAudioError) as raised:
                with prepare_comparison_audio(upload):
                    self.fail('rejected audio reached provider boundary')
        self.assertEqual(raised.exception.code, expected_code)
        self.assertEqual(list(Path(self.temp_root.name).iterdir()), [])

    def test_rejects_unsupported_extension_before_temp_file_is_used(self):
        upload = SimpleUploadedFile('synthetic.txt', b'not audio')

        with patch(
            'inpa.consultations.comparison_audio.tempfile.TemporaryDirectory',
        ) as temporary_directory:
            with self.assertRaisesRegex(
                ComparisonAudioError,
                'AUDIO_FORMAT_UNSUPPORTED',
            ):
                with prepare_comparison_audio(upload):
                    self.fail('unsupported audio reached provider boundary')
        temporary_directory.assert_not_called()

    @override_settings(CONSULTATION_COMPARISON_MAX_BYTES=32)
    def test_rejects_declared_size_over_limit_before_temp_copy(self):
        upload = SimpleUploadedFile('synthetic.wav', b'x' * 33)

        with patch(
            'inpa.consultations.comparison_audio.tempfile.TemporaryDirectory',
        ) as temporary_directory:
            with self.assertRaises(ComparisonAudioError) as raised:
                with prepare_comparison_audio(upload):
                    self.fail('oversized audio reached provider boundary')

        self.assertEqual(raised.exception.code, 'AUDIO_TOO_LARGE')
        temporary_directory.assert_not_called()

    @override_settings(CONSULTATION_COMPARISON_MAX_BYTES=32)
    def test_rejects_actual_copied_bytes_over_false_declared_size(self):
        upload = SimpleUploadedFile('synthetic.wav', b'x' * 33)
        upload.size = 1

        self._assert_rejected_and_cleaned(upload, 'AUDIO_TOO_LARGE')

    @override_settings(CONSULTATION_COMPARISON_MAX_DURATION_SECONDS=1)
    def test_rejects_over_duration_and_removes_temp_file(self):
        upload = SimpleUploadedFile('synthetic.wav', make_wav(seconds=2))

        self._assert_rejected_and_cleaned(upload, 'AUDIO_TOO_LONG')

    def test_rejects_corrupt_audio_and_removes_temp_file(self):
        upload = SimpleUploadedFile('synthetic.wav', b'not a wav')

        self._assert_rejected_and_cleaned(upload, 'AUDIO_INVALID')

    def test_rejects_empty_file_with_empty_audio_code_and_cleans_temp(self):
        upload = SimpleUploadedFile('synthetic.wav', b'')

        self._assert_rejected_and_cleaned(upload, 'AUDIO_EMPTY')

    def test_rejects_video_stream_and_removes_temp_file(self):
        upload = SimpleUploadedFile('synthetic.mp4', b'synthetic container')
        container = FakeContainer([
            SimpleNamespace(type='audio', duration=1, time_base=1),
            SimpleNamespace(type='video', duration=1, time_base=1),
        ])

        with patch(
            'inpa.consultations.comparison_audio.av.open',
            return_value=container,
        ):
            self._assert_rejected_and_cleaned(
                upload,
                'AUDIO_ONLY_REQUIRED',
            )

    def test_rejects_multiple_audio_streams_and_removes_temp_file(self):
        upload = SimpleUploadedFile('synthetic.wav', b'synthetic container')
        container = FakeContainer([
            SimpleNamespace(type='audio', duration=1, time_base=1),
            SimpleNamespace(type='audio', duration=1, time_base=1),
        ])

        with patch(
            'inpa.consultations.comparison_audio.av.open',
            return_value=container,
        ):
            self._assert_rejected_and_cleaned(
                upload,
                'AUDIO_ONLY_REQUIRED',
            )

    def test_decodes_duration_when_stream_metadata_is_unavailable(self):
        upload = SimpleUploadedFile('synthetic.wav', b'synthetic container')
        container = FakeContainer(
            [SimpleNamespace(type='audio', duration=None, time_base=None)],
            frames=(
                SimpleNamespace(samples=8_000, sample_rate=16_000),
                SimpleNamespace(samples=8_000, sample_rate=16_000),
            ),
        )

        with patch(
            'inpa.consultations.comparison_audio.av.open',
            return_value=container,
        ), patch(
            'inpa.consultations.comparison_audio.tempfile.TemporaryDirectory',
            side_effect=self._tracked_temporary_directory,
        ):
            with prepare_comparison_audio(upload) as prepared:
                path = prepared.path
                self.assertEqual(prepared.duration_seconds, 1.0)
                self.assertTrue(path.exists())

        self.assertFalse(path.exists())
        self.assertEqual(list(Path(self.temp_root.name).iterdir()), [])

    def test_rejects_zero_length_audio_and_removes_temp_file(self):
        upload = SimpleUploadedFile('synthetic.wav', b'synthetic container')
        container = FakeContainer([
            SimpleNamespace(type='audio', duration=0, time_base=1),
        ])

        with patch(
            'inpa.consultations.comparison_audio.av.open',
            return_value=container,
        ):
            self._assert_rejected_and_cleaned(upload, 'AUDIO_EMPTY')

    def test_rejected_audio_never_calls_transcriber_or_summarizers(self):
        transcriber = Mock()
        first_summarizer = Mock(provider='openai')
        second_summarizer = Mock(provider='anthropic')
        service = ConsultationComparisonService(
            transcriber=transcriber,
            summarizers=(first_summarizer, second_summarizer),
        )

        with self.assertRaises(ComparisonAudioError) as raised:
            service.compare(
                SimpleUploadedFile('synthetic.wav', b'not a wav'),
            )

        self.assertEqual(raised.exception.code, 'AUDIO_INVALID')
        transcriber.transcribe.assert_not_called()
        first_summarizer.summarize.assert_not_called()
        second_summarizer.summarize.assert_not_called()

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
