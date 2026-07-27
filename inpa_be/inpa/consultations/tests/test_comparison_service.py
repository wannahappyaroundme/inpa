from contextlib import contextmanager
from pathlib import Path
import tempfile
from unittest.mock import patch

from django.test import SimpleTestCase

from inpa.consultations.providers.comparison_base import (
    ComparisonOutcomeUnknown,
    ComparisonProviderFailure,
    ComparisonSummaryResult,
    ComparisonTranscriptSegment,
    ComparisonTranscription,
)
from inpa.consultations.summary_schema import ConsultationSummary


def make_upload():
    return object()


def valid_summary():
    return ConsultationSummary(
        consultation_core=('상담 핵심',),
        customer_priorities=('고객 우선순위',),
        items_to_confirm=('확인할 내용',),
        next_actions=('다음 할 일',),
    )


class FakeTranscriber:
    def __init__(self, segments):
        self.segments = segments
        self.calls = 0

    def transcribe(self, path):
        self.calls += 1
        return ComparisonTranscription(
            segments=self.segments,
            model='transcriber-model',
            latency_ms=12,
        )


class FailingTranscriber:
    def transcribe(self, path):
        raise ComparisonProviderFailure('TRANSCRIPTION_REJECTED')


class CapturingSummarizer:
    def __init__(self, provider):
        self.provider = provider
        self.calls = 0
        self.received = None

    def summarize(self, masked_transcript):
        self.calls += 1
        self.received = masked_transcript
        return ComparisonSummaryResult(
            summary=valid_summary(),
            model=f'{self.provider}-model',
            latency_ms=24,
            input_tokens=40,
            output_tokens=10,
        )


class SuccessfulSummarizer(CapturingSummarizer):
    pass


class FailingSummarizer(CapturingSummarizer):
    def __init__(self, provider, error):
        super().__init__(provider)
        self.error = error

    def summarize(self, masked_transcript):
        self.calls += 1
        self.received = masked_transcript
        raise self.error


class ComparisonServiceTests(SimpleTestCase):
    def setUp(self):
        self.prepared_paths = []

    @contextmanager
    def _prepared_audio(self, _uploaded_file):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'comparison.wav'
            path.write_bytes(b'synthetic')
            self.prepared_paths.append(path)
            yield type('PreparedAudio', (), {'path': path})()

    def _assert_temp_audio_removed(self):
        self.assertEqual(len(self.prepared_paths), 1)
        self.assertFalse(self.prepared_paths[0].exists())

    def _service(self, **kwargs):
        from inpa.consultations.comparison import ConsultationComparisonService

        return ConsultationComparisonService(**kwargs)

    def _compare(self, service):
        from inpa.consultations import comparison

        with patch.object(
            comparison,
            'prepare_comparison_audio',
            self._prepared_audio,
        ):
            return service.compare(make_upload())

    def test_calls_transcriber_once_and_sends_identical_masked_text_to_both(self):
        transcriber = FakeTranscriber([
            ComparisonTranscriptSegment(
                speaker='화자 1',
                text='김고객 전화는 010-1234-5678입니다',
                start_seconds=0.0,
                end_seconds=2.0,
            ),
        ])
        first = CapturingSummarizer('openai')
        second = CapturingSummarizer('anthropic')

        payload = self._compare(self._service(
            transcriber=transcriber,
            summarizers=(first, second),
            shuffle=lambda rows: None,
        ))

        self.assertEqual(transcriber.calls, 1)
        self.assertEqual(first.received, second.received)
        self.assertNotIn('010-1234-5678', first.received)
        self.assertEqual(first.received, '화자 1: 김고객 전화는 [전화_1]입니다')
        self.assertEqual([row['slot'] for row in payload['results']], ['A', 'B'])
        self.assertEqual(
            payload['transcript']['segments'],
            [{
                'speaker': '화자 1',
                'text': '김고객 전화는 [전화_1]입니다',
                'start_seconds': 0.0,
                'end_seconds': 2.0,
            }],
        )
        self._assert_temp_audio_removed()

    def test_keeps_success_when_other_summary_provider_fails(self):
        valid_segments = (
            ComparisonTranscriptSegment(
                speaker='화자 1',
                text='상담 내용을 확인합니다',
                start_seconds=0.0,
                end_seconds=2.0,
            ),
        )
        payload = self._compare(self._service(
            transcriber=FakeTranscriber(valid_segments),
            summarizers=(
                SuccessfulSummarizer('openai'),
                FailingSummarizer(
                    'anthropic',
                    ComparisonProviderFailure('SUMMARY_REFUSED'),
                ),
            ),
            shuffle=lambda rows: None,
        ))

        self.assertEqual(payload['results'][0]['status'], 'success')
        self.assertEqual(payload['results'][1]['status'], 'failed')
        self.assertIsNone(payload['results'][1]['summary'])
        self.assertEqual(payload['results'][1]['error_code'], 'SUMMARY_REFUSED')
        self._assert_temp_audio_removed()

    def test_marks_unknown_provider_outcome_separately(self):
        valid_segments = (
            ComparisonTranscriptSegment(
                speaker='화자 1',
                text='상담 내용을 확인합니다',
                start_seconds=0.0,
                end_seconds=2.0,
            ),
        )
        payload = self._compare(self._service(
            transcriber=FakeTranscriber(valid_segments),
            summarizers=(
                FailingSummarizer(
                    'openai',
                    ComparisonOutcomeUnknown('SUMMARY_TIMEOUT'),
                ),
                SuccessfulSummarizer('anthropic'),
            ),
            shuffle=lambda rows: None,
        ))

        self.assertEqual(payload['results'][0]['status'], 'outcome_unknown')
        self.assertEqual(payload['results'][0]['error_code'], 'SUMMARY_TIMEOUT')
        self.assertEqual(payload['results'][1]['status'], 'success')
        self._assert_temp_audio_removed()

    def test_replaces_provider_controlled_error_codes_with_safe_fallbacks(self):
        valid_segments = (
            ComparisonTranscriptSegment(
                speaker='화자 1',
                text='상담 내용을 확인합니다',
                start_seconds=0.0,
                end_seconds=2.0,
            ),
        )
        unsafe_failure = ' customer phone 010-1234-5678! '
        unsafe_unknown = 'timeout: transcript content\n'

        payload = self._compare(self._service(
            transcriber=FakeTranscriber(valid_segments),
            summarizers=(
                FailingSummarizer(
                    'openai',
                    ComparisonProviderFailure(unsafe_failure),
                ),
                FailingSummarizer(
                    'anthropic',
                    ComparisonOutcomeUnknown(unsafe_unknown),
                ),
            ),
            shuffle=lambda rows: None,
        ))

        self.assertEqual(
            [row['error_code'] for row in payload['results']],
            ['SUMMARY_FAILED', 'SUMMARY_OUTCOME_UNKNOWN'],
        )
        self.assertNotIn(unsafe_failure, str(payload))
        self.assertNotIn(unsafe_unknown, str(payload))
        self._assert_temp_audio_removed()

    def test_does_not_start_summaries_after_transcription_failure(self):
        first = CapturingSummarizer('openai')
        second = CapturingSummarizer('anthropic')

        with self.assertRaises(ComparisonProviderFailure):
            self._compare(self._service(
                transcriber=FailingTranscriber(),
                summarizers=(first, second),
            ))

        self.assertEqual(first.calls + second.calls, 0)
        self._assert_temp_audio_removed()
