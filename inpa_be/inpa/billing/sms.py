"""SOLAPI SMS v4 어댑터.

전화번호, 메시지, 인증번호, 인증 헤더, 공급자 본문은 로그에 남기지 않는다.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import logging
import re
import secrets
import time

from django.conf import settings
import httpx


logger = logging.getLogger(__name__)

SOLAPI_SEND_URL = (
    'https://api.solapi.com/messages/v4/send-many/detail'
)
_SAFE_TRANSACTION_ID = re.compile(r'[^A-Za-z0-9_.:-]+')
_RETRY_DELAYS_SECONDS = (1, 2)
_HTTP_TIMEOUT = httpx.Timeout(
    connect=3.0,
    read=10.0,
    write=5.0,
    pool=2.0,
)


class SolapiProviderError(RuntimeError):
    def __init__(self, code, *, status_code=None):
        self.code = code
        self.status_code = status_code
        super().__init__(code)


@dataclass(frozen=True)
class SmsSendResult:
    provider_transaction_id: str


def _utc_iso_seconds(value):
    normalized = value.astimezone(timezone.utc).replace(microsecond=0)
    return normalized.isoformat().replace('+00:00', 'Z')


def build_solapi_auth_header(
    api_key,
    api_secret,
    *,
    now=None,
    salt=None,
):
    current = now or datetime.now(timezone.utc)
    date = _utc_iso_seconds(current)
    request_salt = salt or secrets.token_hex(16)
    if not 12 <= len(request_salt.encode('utf-8')) <= 64:
        raise ValueError('SOLAPI salt must be 12-64 bytes')
    signature = hmac.new(
        str(api_secret).encode('utf-8'),
        f'{date}{request_salt}'.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()
    return (
        f'HMAC-SHA256 apiKey={api_key}, date={date}, '
        f'salt={request_salt}, signature={signature}'
    )


def _digits_only(value):
    normalized = str(value or '')
    if not normalized or not normalized.isdigit():
        raise SolapiProviderError('provider_not_configured')
    return normalized


def _safe_transaction_id(value):
    return _SAFE_TRANSACTION_ID.sub('', str(value or ''))[:120]


def _provider_transaction_id(response):
    try:
        payload = response.json()
    except (TypeError, ValueError) as exc:
        raise SolapiProviderError(
            'provider_invalid_response',
            status_code=response.status_code,
        ) from exc
    if not isinstance(payload, dict):
        raise SolapiProviderError(
            'provider_invalid_response',
            status_code=response.status_code,
        )
    group_info = payload.get('groupInfo')
    nested = (
        group_info.get('groupId')
        if isinstance(group_info, dict)
        else ''
    )
    return _safe_transaction_id(
        payload.get('groupId') or nested or payload.get('messageId')
    )


class SolapiSmsClient:
    def __init__(
        self,
        *,
        api_key=None,
        api_secret=None,
        sender_number=None,
        http_client=None,
        sleep=None,
    ):
        self.api_key = (
            getattr(settings, 'SOLAPI_API_KEY', '')
            if api_key is None else str(api_key)
        )
        self.api_secret = (
            getattr(settings, 'SOLAPI_API_SECRET', '')
            if api_secret is None else str(api_secret)
        )
        sender = (
            getattr(settings, 'SOLAPI_SENDER_NUMBER', '')
            if sender_number is None else str(sender_number)
        )
        if not self.api_key or not self.api_secret:
            raise SolapiProviderError('provider_not_configured')
        self.sender_number = _digits_only(sender)
        self._owns_http_client = http_client is None
        self.http = (
            httpx.Client()
            if self._owns_http_client
            else http_client
        )
        self.sleep = sleep or time.sleep

    def send_verification_sms(
        self,
        canonical_phone,
        code,
        *,
        now=None,
        salt=None,
    ):
        try:
            return self._send_verification_sms(
                canonical_phone,
                code,
                now=now,
                salt=salt,
            )
        finally:
            if self._owns_http_client:
                self.http.close()

    def _send_verification_sms(
        self,
        canonical_phone,
        code,
        *,
        now=None,
        salt=None,
    ):
        recipient = _digits_only(canonical_phone)
        raw_code = str(code or '')
        if not re.fullmatch(r'\d{6}', raw_code):
            raise ValueError('OTP must contain six digits')
        body = {
            'messages': [{
                'to': recipient,
                'from': self.sender_number,
                'text': (
                    f'[인파] 인증번호는 {raw_code}입니다. '
                    '5분 안에 입력해 주세요.'
                ),
                'type': 'SMS',
            }],
        }

        for attempt in range(3):
            attempt_salt = (
                salt
                if attempt == 0 and salt is not None
                else secrets.token_hex(16)
            )
            headers = {
                'Authorization': build_solapi_auth_header(
                    self.api_key,
                    self.api_secret,
                    now=now,
                    salt=attempt_salt,
                ),
                'Content-Type': 'application/json',
            }
            try:
                response = self.http.post(
                    SOLAPI_SEND_URL,
                    json=body,
                    headers=headers,
                    timeout=_HTTP_TIMEOUT,
                )
            except (httpx.RequestError, OSError, TimeoutError) as exc:
                if attempt < 2:
                    self.sleep(_RETRY_DELAYS_SECONDS[attempt])
                    continue
                logger.warning(
                    'solapi_sms_failed result=provider_unavailable '
                    'status=none exception=%s',
                    exc.__class__.__name__,
                )
                raise SolapiProviderError(
                    'provider_unavailable',
                ) from exc

            status_code = response.status_code
            if 200 <= status_code < 300:
                try:
                    transaction_id = _provider_transaction_id(response)
                except SolapiProviderError as exc:
                    logger.warning(
                        'solapi_sms_failed result=%s status=%s '
                        'exception=%s',
                        exc.code,
                        status_code,
                        exc.__class__.__name__,
                    )
                    raise
                logger.info(
                    'solapi_sms_result result=sent status=%s '
                    'provider_transaction_id=%s',
                    status_code,
                    transaction_id or 'none',
                )
                return SmsSendResult(
                    provider_transaction_id=transaction_id,
                )

            retryable = status_code == 429 or status_code >= 500
            if retryable and attempt < 2:
                self.sleep(_RETRY_DELAYS_SECONDS[attempt])
                continue

            result = (
                'provider_unavailable'
                if retryable
                else 'provider_rejected'
            )
            logger.warning(
                'solapi_sms_failed result=%s status=%s exception=none',
                result,
                status_code,
            )
            raise SolapiProviderError(
                result,
                status_code=status_code,
            )

        raise SolapiProviderError('provider_unavailable')
