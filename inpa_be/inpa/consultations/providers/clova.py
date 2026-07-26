import json
from urllib.parse import quote

import httpx
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .base import (
    ExplicitProviderNonReceipt,
    SpeechJobResult,
    SpeechProviderProtocolError,
    SpeechProviderTemporaryError,
    SpeechSubmitOutcomeUnknown,
    SubmittedSpeechJob,
)


CLOVA_STATES = {
    'WAITING': 'waiting',
    'PROCESSING': 'processing',
    'COMPLETED': 'completed',
    'FAILED': 'failed',
    'TIMEOUT': 'timeout',
}


class ClovaSpeechProvider:
    def __init__(self, client=None):
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(30.0, read=120.0),
        )
        self.invoke_url = settings.CLOVA_SPEECH_INVOKE_URL.rstrip('/')
        secret = settings.CLOVA_SPEECH_SECRET_KEY
        if not self.invoke_url or not secret:
            raise ImproperlyConfigured(
                'CLOVA Speech credentials are incomplete',
            )
        self.headers = {'X-CLOVASPEECH-API-KEY': secret}

    def submit(self, fileobj, callback_url):
        params = {
            'language': 'ko-KR',
            'completion': 'async',
            'callback': callback_url,
            'wordAlignment': False,
            'fullText': True,
            'noiseFiltering': True,
            'diarization': {
                'enable': True,
                'speakerCountMin': 2,
                'speakerCountMax': 2,
            },
            'resultToObs': False,
        }
        try:
            response = self.client.post(
                f'{self.invoke_url}/recognizer/upload',
                headers=self.headers,
                data={'params': json.dumps(params, ensure_ascii=False)},
                files={
                    'media': (
                        'consultation-audio.wav',
                        fileobj,
                        'audio/wav',
                    ),
                },
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise ExplicitProviderNonReceipt(
                type(exc).__name__,
            ) from exc
        except httpx.HTTPError as exc:
            raise SpeechSubmitOutcomeUnknown(type(exc).__name__) from exc
        try:
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise SpeechSubmitOutcomeUnknown(type(exc).__name__) from exc
        job_id = payload.get('token', '')
        if not isinstance(job_id, str) or not job_id.strip():
            raise SpeechSubmitOutcomeUnknown('MISSING_JOB_TOKEN')
        return SubmittedSpeechJob(job_id=job_id.strip())

    def poll(self, job_id):
        if not isinstance(job_id, str) or not job_id:
            raise SpeechProviderProtocolError('INVALID_JOB_TOKEN')
        try:
            response = self.client.get(
                f'{self.invoke_url}/recognizer/{quote(job_id, safe="")}',
                headers=self.headers,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise SpeechProviderTemporaryError(type(exc).__name__) from exc
        except (TypeError, ValueError) as exc:
            raise SpeechProviderProtocolError(
                'INVALID_POLL_RESPONSE',
            ) from exc
        raw_state = payload.get('result')
        state = CLOVA_STATES.get(raw_state, 'failed')
        transcript = ''
        if state == 'completed':
            segments = payload.get('segments', [])
            if not isinstance(segments, list):
                raise SpeechProviderProtocolError('INVALID_SEGMENTS')
            transcript = '\n'.join(
                item.get('text', '').strip()
                for item in segments
                if (
                    isinstance(item, dict)
                    and isinstance(item.get('text'), str)
                    and item.get('text', '').strip()
                )
            )
            if not transcript:
                return SpeechJobResult(
                    state='failed',
                    error_code='CLOVA_EMPTY_TRANSCRIPT',
                )
        return SpeechJobResult(
            state=state,
            transcript=transcript,
            error_code='' if state != 'failed' else 'CLOVA_FAILED',
        )
