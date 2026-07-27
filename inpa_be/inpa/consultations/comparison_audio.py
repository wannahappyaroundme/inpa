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


def _require_work_time(deadline) -> None:
    if deadline is not None:
        deadline.require_work_time(code='TRANSCRIPTION_TIMEOUT')


def _inspect_audio_duration(path: Path, *, deadline=None) -> float:
    _require_work_time(deadline)
    try:
        with av.open(str(path), mode='r') as container:
            _require_work_time(deadline)
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
                if (
                    duration_seconds
                    > settings.CONSULTATION_COMPARISON_MAX_DURATION_SECONDS
                ):
                    raise ComparisonAudioError('AUDIO_TOO_LONG')
            else:
                duration_seconds = 0.0
                for frame in container.decode(audio=0):
                    _require_work_time(deadline)
                    if frame.sample_rate <= 0:
                        raise ComparisonAudioError('AUDIO_INVALID')
                    duration_seconds += frame.samples / frame.sample_rate
                    if (
                        duration_seconds
                        > settings.CONSULTATION_COMPARISON_MAX_DURATION_SECONDS
                    ):
                        raise ComparisonAudioError('AUDIO_TOO_LONG')
    except ComparisonAudioError:
        raise
    except (FFmpegError, OSError, ValueError, EOFError) as exc:
        raise ComparisonAudioError('AUDIO_INVALID') from exc

    if duration_seconds <= 0:
        raise ComparisonAudioError('AUDIO_EMPTY')
    return duration_seconds


@contextmanager
def _prepare_comparison_audio_in(
    uploaded_file,
    *,
    temp_dir,
    extension,
    deadline,
):
    path = Path(temp_dir) / f'audio{extension}'
    byte_size = 0
    _require_work_time(deadline)
    with path.open('wb') as destination:
        for chunk in uploaded_file.chunks():
            _require_work_time(deadline)
            byte_size += len(chunk)
            if byte_size > settings.CONSULTATION_COMPARISON_MAX_BYTES:
                raise ComparisonAudioError('AUDIO_TOO_LARGE')
            destination.write(chunk)

    if byte_size == 0:
        raise ComparisonAudioError('AUDIO_EMPTY')
    duration_seconds = _inspect_audio_duration(path, deadline=deadline)
    _require_work_time(deadline)
    yield PreparedComparisonAudio(path, duration_seconds, byte_size)


@contextmanager
def prepare_comparison_audio(uploaded_file, *, deadline=None, temp_dir=None):
    extension = Path(uploaded_file.name or '').suffix.lower()
    if extension not in SUPPORTED_COMPARISON_EXTENSIONS:
        raise ComparisonAudioError('AUDIO_FORMAT_UNSUPPORTED')
    if uploaded_file.size > settings.CONSULTATION_COMPARISON_MAX_BYTES:
        raise ComparisonAudioError('AUDIO_TOO_LARGE')

    if temp_dir is not None:
        with _prepare_comparison_audio_in(
            uploaded_file,
            temp_dir=temp_dir,
            extension=extension,
            deadline=deadline,
        ) as prepared:
            yield prepared
        return

    with tempfile.TemporaryDirectory(
        prefix='inpa-consultation-comparison-',
    ) as owned_temp_dir:
        with _prepare_comparison_audio_in(
            uploaded_file,
            temp_dir=owned_temp_dir,
            extension=extension,
            deadline=deadline,
        ) as prepared:
            yield prepared
