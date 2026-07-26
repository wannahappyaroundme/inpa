"""KICC EasyPay 빌키 API 어댑터.

공급자 필드명·URL·응답 무결성 검증은 이 파일에만 둔다. 승인 POST는
네트워크 예외에서 재호출하지 않고 unknown을 반환한다.
"""

from dataclasses import dataclass
from datetime import datetime
import hashlib
import hmac
import re
from typing import Literal
from zoneinfo import ZoneInfo

from django.conf import settings
import httpx


_KST = ZoneInfo('Asia/Seoul')
_SAFE_CODE = re.compile(r'[^A-Za-z0-9_-]+')


class KiccConfigurationError(RuntimeError):
    pass


class KiccIntegrityError(RuntimeError):
    pass


class KiccProviderDeclined(RuntimeError):
    def __init__(self, code):
        self.code = _safe_code(code)
        super().__init__(self.code)


@dataclass(frozen=True)
class RegistrationResult:
    auth_page_url: str


@dataclass(frozen=True)
class IssueKeyResult:
    billing_key: str
    card_brand: str
    card_last4: str


@dataclass(frozen=True)
class ChargeResult:
    kind: Literal['approved', 'declined', 'unknown']
    provider_transaction_id: str = ''
    code: str = ''
    amount_krw: int = 0


@dataclass(frozen=True)
class OperationResult:
    kind: Literal['approved', 'declined', 'unknown']
    provider_transaction_id: str = ''
    code: str = ''


def _safe_code(value):
    return _SAFE_CODE.sub('', str(value or ''))[:40] or 'UNKNOWN'


class KiccBillingClient:
    _REGISTRATION_PATH = '/api/ep9/trades/webpay'
    _ISSUE_KEY_PATH = '/api/ep9/trades/approval'
    _CHARGE_PATH = '/api/trades/approval/batch'
    _QUERY_PATH = '/api/trades/retrieveTransaction'
    _REVOKE_KEY_PATH = '/api/trades/removeBatchKey'
    _CANCEL_PATH = '/api/trades/revise'

    def __init__(self, *, http_client=None):
        self.mall_id = getattr(settings, 'KICC_MALL_ID', '')
        self.secret = getattr(settings, 'KICC_CLIENT_SECRET', '')
        self.base_url = getattr(
            settings, 'KICC_API_BASE_URL', '').rstrip('/')
        if not all((self.mall_id, self.secret, self.base_url)):
            raise KiccConfigurationError('KICC_NOT_CONFIGURED')
        self.http = http_client or httpx.Client()

    def _url(self, path):
        return f'{self.base_url}{path}'

    def _post_once(self, path, payload, *, timeout=30.0):
        response = self.http.post(
            self._url(path), json=payload, timeout=timeout)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise KiccIntegrityError('KICC_RESPONSE_NOT_OBJECT')
        return body

    @staticmethod
    def _today():
        return datetime.now(tz=_KST).strftime('%Y%m%d')

    def _validate_echo(
        self,
        body,
        *,
        request_id=None,
        order_id=None,
        amount_krw=None,
        require_auth=True,
    ):
        if body.get('mallId') != self.mall_id:
            raise KiccIntegrityError('KICC_MALL_MISMATCH')
        if (
            request_id is not None
            and body.get('shopTransactionId') != request_id
        ):
            raise KiccIntegrityError('KICC_REQUEST_MISMATCH')
        if (
            order_id is not None
            and body.get('shopOrderNo') != order_id
        ):
            raise KiccIntegrityError('KICC_ORDER_MISMATCH')
        if amount_krw is not None:
            try:
                response_amount = int(body.get('amount'))
            except (TypeError, ValueError) as exc:
                raise KiccIntegrityError(
                    'KICC_AMOUNT_INVALID') from exc
            if response_amount != int(amount_krw):
                raise KiccIntegrityError('KICC_AMOUNT_MISMATCH')
        if require_auth:
            self._validate_response_auth(body, amount_krw or 0)

    def _validate_response_auth(self, body, amount_krw):
        pg_cno = str(body.get('pgCno') or '')
        transaction_date = str(body.get('transactionDate') or '')
        actual = str(body.get('msgAuthValue') or '')
        if not all((pg_cno, transaction_date, actual)):
            raise KiccIntegrityError('KICC_AUTH_MISSING')
        message = f'{pg_cno}|{int(amount_krw)}|{transaction_date}'
        expected = hmac.new(
            self.secret.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected.lower(), actual.lower()):
            raise KiccIntegrityError('KICC_AUTH_MISMATCH')

    def start_registration(
        self,
        *,
        order_id,
        return_url,
        device_type='mobile',
        goods_name='인파 Plus 무료 이용',
    ):
        body = self._post_once(self._REGISTRATION_PATH, {
            'mallId': self.mall_id,
            'shopOrderNo': order_id,
            'amount': 0,
            'payMethodTypeCode': '81',
            'currency': '00',
            'returnUrl': return_url,
            'deviceTypeCode': (
                'pc' if device_type == 'pc' else 'mobile'),
            'clientTypeCode': '00',
            'langFlag': 'KOR',
            'orderInfo': {
                'goodsName': goods_name,
                'goodsTypeCode': '1',
            },
            'payMethodInfo': {
                'billKeyMethodInfo': {'certType': '0'},
            },
        })
        if body.get('resCd') != '0000':
            raise KiccProviderDeclined(body.get('resCd'))
        auth_url = str(body.get('authPageUrl') or '')
        if not auth_url.startswith('https://'):
            raise KiccIntegrityError('KICC_AUTH_URL_INVALID')
        return RegistrationResult(auth_page_url=auth_url)

    def issue_key(self, *, auth_id, order_id, request_id):
        body = self._post_once(self._ISSUE_KEY_PATH, {
            'mallId': self.mall_id,
            'shopTransactionId': request_id,
            'authorizationId': auth_id,
            'shopOrderNo': order_id,
            'approvalReqDate': self._today(),
        })
        if body.get('resCd') != '0000':
            raise KiccProviderDeclined(body.get('resCd'))
        self._validate_echo(
            body,
            request_id=request_id,
            order_id=order_id,
            amount_krw=0,
        )
        card = (body.get('paymentInfo') or {}).get('cardInfo') or {}
        billing_key = str(card.get('cardNo') or '')
        masked = str(card.get('cardMaskNo') or '')
        digits = ''.join(char for char in masked if char.isdigit())
        if not billing_key or len(digits) < 4:
            raise KiccIntegrityError('KICC_CARD_RESULT_INVALID')
        return IssueKeyResult(
            billing_key=billing_key,
            card_brand=str(card.get('issuerName') or '')[:40],
            card_last4=digits[-4:],
        )

    def charge(self, order, billing_key, *, request_id):
        payload = {
            'mallId': self.mall_id,
            'shopTransactionId': request_id,
            'shopOrderNo': order.merchant_order_id,
            'approvalReqDate': self._today(),
            'amount': order.amount_krw,
            'currency': '00',
            'orderInfo': {'goodsName': '인파 Plus 월 이용'},
            'payMethodInfo': {
                'billKeyMethodInfo': {'batchKey': billing_key},
                'cardMethodInfo': {
                    'installmentMonth': 0,
                    'freeInstallmentUsed': False,
                },
            },
        }
        try:
            body = self._post_once(self._CHARGE_PATH, payload)
        except (httpx.RequestError, OSError, TimeoutError):
            return ChargeResult(
                kind='unknown', code='TRANSPORT_UNKNOWN')
        if body.get('resCd') != '0000':
            return ChargeResult(
                kind='declined', code=_safe_code(body.get('resCd')))
        self._validate_echo(
            body,
            request_id=request_id,
            order_id=order.merchant_order_id,
            amount_krw=order.amount_krw,
        )
        return ChargeResult(
            kind='approved',
            provider_transaction_id=str(body.get('pgCno') or ''),
            code=_safe_code(body.get('statusCode') or '0000'),
            amount_krw=int(body['amount']),
        )

    def query(
        self,
        *,
        request_id,
        transaction_date,
        expected_order_id,
        expected_amount,
    ):
        try:
            body = self._post_once(self._QUERY_PATH, {
                'mallId': self.mall_id,
                'shopTransactionId': request_id,
                'transactionDate': transaction_date,
            })
        except (httpx.RequestError, OSError, TimeoutError):
            return ChargeResult(
                kind='unknown', code='TRANSPORT_UNKNOWN')
        if body.get('resCd') != '0000':
            code = _safe_code(body.get('resCd'))
            if code in {'VTIM', 'VT00'}:
                return ChargeResult(kind='unknown', code=code)
            return ChargeResult(kind='declined', code=code)
        self._validate_echo(
            body,
            request_id=request_id,
            order_id=expected_order_id,
            amount_krw=expected_amount,
            require_auth=False,
        )
        return ChargeResult(
            kind='approved',
            provider_transaction_id=str(body.get('pgCno') or ''),
            code=_safe_code(body.get('statusCode') or '0000'),
            amount_krw=int(body['amount']),
        )

    def revoke_key(self, billing_key, *, request_id):
        try:
            body = self._post_once(self._REVOKE_KEY_PATH, {
                'mallId': self.mall_id,
                'shopTransactionId': request_id,
                'batchKey': billing_key,
                'removeReqDate': self._today(),
            })
        except (httpx.RequestError, OSError, TimeoutError):
            return OperationResult(
                kind='unknown', code='TRANSPORT_UNKNOWN')
        if body.get('resCd') != '0000':
            return OperationResult(
                kind='declined', code=_safe_code(body.get('resCd')))
        if (
            body.get('mallId') != self.mall_id
            or body.get('shopTransactionId') != request_id
        ):
            raise KiccIntegrityError('KICC_REVOKE_ECHO_MISMATCH')
        return OperationResult(kind='approved', code='0000')

    def cancel(
        self,
        transaction_id,
        amount_krw,
        reason,
        *,
        request_id,
    ):
        message = f'{transaction_id}|{request_id}'
        request_auth = hmac.new(
            self.secret.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()
        try:
            body = self._post_once(self._CANCEL_PATH, {
                'mallId': self.mall_id,
                'shopTransactionId': request_id,
                'pgCno': transaction_id,
                'reviseTypeCode': '40',
                'amount': amount_krw,
                'cancelReqDate': self._today(),
                'msgAuthValue': request_auth,
                'reviseMessage': str(reason or '정기결제 취소')[:100],
            })
        except (httpx.RequestError, OSError, TimeoutError):
            return OperationResult(
                kind='unknown', code='TRANSPORT_UNKNOWN')
        if body.get('resCd') != '0000':
            return OperationResult(
                kind='declined', code=_safe_code(body.get('resCd')))
        if (
            body.get('mallId') != self.mall_id
            or body.get('shopTransactionId') != request_id
            or str(body.get('oriPgCno') or '') != transaction_id
            or int(body.get('cancelAmount') or -1) != int(amount_krw)
        ):
            raise KiccIntegrityError('KICC_CANCEL_ECHO_MISMATCH')
        return OperationResult(
            kind='approved',
            provider_transaction_id=str(
                body.get('cancelPgCno') or ''),
            code=_safe_code(body.get('statusCode') or '0000'),
        )
