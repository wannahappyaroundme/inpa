import tempfile
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
from django.test import SimpleTestCase

from inpa.consultations.audio import open_clova_wav, open_openai_audio


def _write_webm(path):
    with av.open(str(path), mode='w', format='webm') as output:
        stream = output.add_stream('libopus', rate=48_000)
        stream.layout = 'mono'
        for index in range(10):
            samples = np.zeros((1, 4_800), dtype=np.float32)
            frame = av.AudioFrame.from_ndarray(
                samples,
                format='fltp',
                layout='mono',
            )
            frame.sample_rate = 48_000
            frame.pts = index * 4_800
            frame.time_base = Fraction(1, 48_000)
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode(None):
            output.mux(packet)


class _FakeStorage:
    def __init__(self, source):
        self.source = source

    def open_temp(self, _key):
        class _SourceContext:
            def __enter__(inner_self):
                return self.source

            def __exit__(inner_self, *_args):
                return False

        return _SourceContext()


class ConsultationAudioTests(SimpleTestCase):
    def test_webm_is_transcoded_to_clova_supported_mono_16khz_wav(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / 'source.webm'
            _write_webm(source)

            with open_clova_wav(
                _FakeStorage(source),
                'consultation-recordings/ignored/source',
            ) as prepared:
                prepared_path = Path(prepared.name)
                self.assertTrue(prepared_path.exists())
                with av.open(prepared) as container:
                    streams = [
                        stream for stream in container.streams
                        if stream.type == 'audio'
                    ]
                    self.assertEqual(len(streams), 1)
                    self.assertEqual(streams[0].codec_context.name, 'pcm_s16le')
                    self.assertEqual(streams[0].sample_rate, 16_000)
                    self.assertEqual(streams[0].codec_context.channels, 1)

            self.assertFalse(prepared_path.exists())

    def test_webm_is_compressed_for_long_openai_meetings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / 'source.webm'
            _write_webm(source)

            with open_openai_audio(
                _FakeStorage(source),
                'consultation-recordings/ignored/source',
            ) as prepared:
                prepared_path = Path(prepared.name)
                self.assertEqual(prepared_path.suffix, '.mp3')
                self.assertLess(prepared_path.stat().st_size, 25 * 1024 * 1024)
                with av.open(prepared) as container:
                    stream = container.streams.audio[0]
                    self.assertTrue(
                        stream.codec_context.name.startswith('mp3'),
                    )
                    self.assertEqual(stream.sample_rate, 16_000)
                    self.assertEqual(stream.codec_context.channels, 1)

            self.assertFalse(prepared_path.exists())
