"""Temporary audio validation for admin-only consultation comparisons."""

import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import av
from av.error import FFmpegError
from django.conf import settings


SUPPORTED_COMPARISON_EXTENSIONS = frozenset({
    '.flac', '.mp3', '.mp4', '.mpeg', '.mpga',
    '.m4a', '.ogg', '.wav', '.webm',
})


class ComparisonAudioError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class PreparedComparisonAudio:
    path: Path
    duration_seconds: float
    byte_size: int


def _inspect_audio_duration(path: Path) -> float:
    try:
        with av.open(str(path), mode='r') as container:
            audio_streams = [
                stream for stream in container.streams
                if stream.type == 'audio'
            ]
            if len(audio_streams) != 1 or any(
                stream.type == 'video' for stream in container.streams
            ):
                raise ComparisonAudioError('AUDIO_ONLY_REQUIRED')

            audio_stream = audio_streams[0]
            if (
                audio_stream.duration is not None
                and audio_stream.time_base is not None
            ):
                duration_seconds = float(
                    audio_stream.duration * audio_stream.time_base)
            else:
                duration_seconds = 0.0
                for frame in container.decode(audio=0):
                    if frame.sample_rate <= 0:
                        raise ComparisonAudioError('AUDIO_INVALID')
                    duration_seconds += frame.samples / frame.sample_rate
    except ComparisonAudioError:
        raise
    except (FFmpegError, OSError, ValueError, EOFError) as exc:
        raise ComparisonAudioError('AUDIO_INVALID') from exc

    if duration_seconds <= 0:
        raise ComparisonAudioError('AUDIO_EMPTY')
    return duration_seconds


@contextmanager
def prepare_comparison_audio(uploaded_file):
    extension = Path(uploaded_file.name or '').suffix.lower()
    if extension not in SUPPORTED_COMPARISON_EXTENSIONS:
        raise ComparisonAudioError('AUDIO_FORMAT_UNSUPPORTED')
    if uploaded_file.size > settings.CONSULTATION_COMPARISON_MAX_BYTES:
        raise ComparisonAudioError('AUDIO_TOO_LARGE')

    with tempfile.TemporaryDirectory(
        prefix='inpa-consultation-comparison-',
    ) as temp_dir:
        path = Path(temp_dir) / f'audio{extension}'
        byte_size = 0
        with path.open('wb') as destination:
            for chunk in uploaded_file.chunks():
                byte_size += len(chunk)
                if byte_size > settings.CONSULTATION_COMPARISON_MAX_BYTES:
                    raise ComparisonAudioError('AUDIO_TOO_LARGE')
                destination.write(chunk)

        duration_seconds = _inspect_audio_duration(path)
        if duration_seconds > settings.CONSULTATION_COMPARISON_MAX_DURATION_SECONDS:
            raise ComparisonAudioError('AUDIO_TOO_LONG')
        yield PreparedComparisonAudio(path, duration_seconds, byte_size)
