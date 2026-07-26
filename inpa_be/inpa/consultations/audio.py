"""Ephemeral audio preparation for the speech-to-text provider."""

import tempfile
from contextlib import contextmanager
from pathlib import Path

import av
from av.error import FFmpegError


class AudioTranscodeError(RuntimeError):
    pass


def _mux_encoded(output, stream, frame):
    for packet in stream.encode(frame):
        output.mux(packet)


@contextmanager
def open_clova_wav(storage, storage_key):
    """Yield a mono 16 kHz PCM WAV and remove both temp files on exit."""
    try:
        with storage.open_temp(storage_key) as source_path:
            with tempfile.TemporaryDirectory(
                prefix='inpa-consultation-clova-',
            ) as output_dir:
                output_path = Path(output_dir) / 'consultation-audio.wav'
                with (
                    av.open(str(source_path), mode='r') as source,
                    av.open(str(output_path), mode='w', format='wav') as output,
                ):
                    audio_streams = [
                        stream for stream in source.streams
                        if stream.type == 'audio'
                    ]
                    if (
                        len(audio_streams) != 1
                        or any(
                            stream.type == 'video'
                            for stream in source.streams
                        )
                    ):
                        raise AudioTranscodeError('AUDIO_ONLY_REQUIRED')
                    output_stream = output.add_stream('pcm_s16le', rate=16_000)
                    output_stream.layout = 'mono'
                    resampler = av.AudioResampler(
                        format='s16',
                        layout='mono',
                        rate=16_000,
                    )
                    for frame in source.decode(audio=0):
                        for converted in resampler.resample(frame):
                            _mux_encoded(output, output_stream, converted)
                    for converted in resampler.resample(None):
                        _mux_encoded(output, output_stream, converted)
                    _mux_encoded(output, output_stream, None)
                if not output_path.exists() or output_path.stat().st_size <= 44:
                    raise AudioTranscodeError('TRANSCODED_AUDIO_EMPTY')
                with output_path.open('rb') as prepared:
                    yield prepared
    except AudioTranscodeError:
        raise
    except (FFmpegError, OSError, ValueError, EOFError) as exc:
        raise AudioTranscodeError(type(exc).__name__) from exc
