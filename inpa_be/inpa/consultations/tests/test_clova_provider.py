import io
import json
from unittest.mock import Mock

import httpx
from django.test import SimpleTestCase, override_settings

from inpa.consultations.providers.base import (
    ExplicitProviderNonReceipt,
    SpeechSubmitOutcomeUnknown,
)
from inpa.consultations.providers.clova import ClovaSpeechProvider


@override_settings(
    CLOVA_SPEECH_INVOKE_URL='https://clova.example/invoke',
    CLOVA_SPEECH_SECRET_KEY='test-secret',
)
class ClovaSpeechProviderTests(SimpleTestCase):
    def setUp(self):
        self.http = Mock()
        self.provider = ClovaSpeechProvider(client=self.http)
        self.audio = io.BytesIO(b'RIFF-test-audio')

    def test_submit_uses_async_korean_and_returns_provider_token(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            'token': 'provider-token',
            'result': 'SUCCEEDED',
        }
        self.http.post.return_value = response

        result = self.provider.submit(
            self.audio,
            'https://api.inpa.kr/api/v1/consultations/callback/x/',
        )

        self.assertEqual(result.job_id, 'provider-token')
        params = json.loads(self.http.post.call_args.kwargs['data']['params'])
        self.assertEqual(params['language'], 'ko-KR')
        self.assertEqual(params['completion'], 'async')
        self.assertTrue(params['diarization']['enable'])
        self.assertFalse(params['resultToObs'])

    def test_poll_returns_transcript_in_memory_and_never_resubmits(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            'result': 'COMPLETED',
            'segments': [
                {'text': '첫 문장'},
                {'text': '둘째 문장'},
            ],
        }
        self.http.get.return_value = response

        result = self.provider.poll('provider-token')

        self.assertEqual(result.state, 'completed')
        self.assertEqual(result.transcript, '첫 문장\n둘째 문장')
        self.http.post.assert_not_called()

    def test_submit_connect_failure_can_retry_but_unknown_receipt_cannot(self):
        self.http.post.side_effect = httpx.ConnectError('connect failed')
        with self.assertRaises(ExplicitProviderNonReceipt):
            self.provider.submit(self.audio, 'https://api.inpa.kr/callback/')

        self.http.post.side_effect = httpx.ReadTimeout('receipt unknown')
        with self.assertRaises(SpeechSubmitOutcomeUnknown):
            self.provider.submit(self.audio, 'https://api.inpa.kr/callback/')
