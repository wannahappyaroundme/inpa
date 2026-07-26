import hashlib
import hmac
from datetime import date
from types import SimpleNamespace
from unittest import mock

import httpx
from django.test import SimpleTestCase, override_settings

from .kicc import KiccBillingClient, KiccIntegrityError


class FakeResponse:
    def __init__(self, body, status_code=200):
        self.body = body
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                'bad response',
                request=mock.Mock(),
                response=mock.Mock(status_code=self.status_code),
            )

    def json(self):
        return self.body


def response_auth(secret, pg_cno, amount, transaction_date):
    message = f'{pg_cno}|{amount}|{transaction_date}'.encode()
    return hmac.new(
        secret.encode(), message, hashlib.sha256).hexdigest()


@override_settings(
    KICC_MALL_ID='T0000001',
    KICC_CLIENT_SECRET='test-secret',
    KICC_API_BASE_URL='https://testpgapi.easypay.co.kr',
)
class KiccBillingClientTests(SimpleTestCase):
    def setUp(self):
        self.http = mock.Mock()
        self.client = KiccBillingClient(http_client=self.http)
        self.order = SimpleNamespace(
            merchant_order_id='INPA-ORDER-1',
            amount_krw=21890,
            due_date=date(2027, 2, 5),
            attempts=SimpleNamespace(
                order_by=lambda *_: SimpleNamespace(
                    first=lambda: SimpleNamespace(
                        provider_request_id='INPA-REQUEST-1',
                        started_at=SimpleNamespace(
                            astimezone=lambda *_: SimpleNamespace(
                                strftime=lambda *_: '20270205')),
                    )),
            ),
        )

    def _approved_body(self, **overrides):
        body = {
            'resCd': '0000',
            'mallId': 'T0000001',
            'shopTransactionId': 'INPA-REQUEST-1',
            'shopOrderNo': 'INPA-ORDER-1',
            'pgCno': 'PG-1',
            'amount': 21890,
            'transactionDate': '20270205090000',
            'msgAuthValue': response_auth(
                'test-secret', 'PG-1', 21890, '20270205090000'),
        }
        body.update(overrides)
        return body

    def test_charge_validates_order_amount_and_merchant(self):
        self.http.post.return_value = FakeResponse(
            self._approved_body(mallId='WRONG'))
        with self.assertRaises(KiccIntegrityError):
            self.client.charge(
                self.order, 'bill-key', request_id='INPA-REQUEST-1')

    def test_charge_validates_response_hmac(self):
        self.http.post.return_value = FakeResponse(
            self._approved_body(msgAuthValue='tampered'))
        with self.assertRaises(KiccIntegrityError):
            self.client.charge(
                self.order, 'bill-key', request_id='INPA-REQUEST-1')

    def test_timeout_returns_unknown_and_never_retries_post(self):
        self.http.post.side_effect = httpx.TimeoutException('timeout')
        result = self.client.charge(
            self.order, 'bill-key', request_id='INPA-REQUEST-1')
        self.assertEqual(result.kind, 'unknown')
        self.assertEqual(result.code, 'TRANSPORT_UNKNOWN')
        self.assertEqual(self.http.post.call_count, 1)

    def test_charge_uses_official_billing_endpoint_and_fields(self):
        self.http.post.return_value = FakeResponse(self._approved_body())
        result = self.client.charge(
            self.order, 'bill-key', request_id='INPA-REQUEST-1')
        self.assertEqual(result.kind, 'approved')
        url = self.http.post.call_args.args[0]
        payload = self.http.post.call_args.kwargs['json']
        self.assertEqual(url, (
            'https://testpgapi.easypay.co.kr'
            '/api/trades/approval/batch'
        ))
        self.assertEqual(
            payload['payMethodInfo']['billKeyMethodInfo']['batchKey'],
            'bill-key',
        )
        self.assertEqual(payload['amount'], 21890)
        self.assertEqual(
            self.http.post.call_args.kwargs['timeout'], 30.0)

    def test_issue_key_returns_only_billing_and_masked_card_data(self):
        body = {
            'resCd': '0000',
            'mallId': 'T0000001',
            'shopTransactionId': 'expected-request',
            'shopOrderNo': 'REGISTER-1',
            'pgCno': 'PG-KEY-1',
            'amount': 0,
            'transactionDate': '20270105090000',
            'msgAuthValue': response_auth(
                'test-secret', 'PG-KEY-1', 0, '20270105090000'),
            'paymentInfo': {
                'cardInfo': {
                    'cardNo': 'secret-billing-key',
                    'issuerName': '신한카드',
                    'cardMaskNo': '123456******7890',
                },
            },
        }
        self.http.post.return_value = FakeResponse(body)
        result = self.client.issue_key(
            auth_id='AUTH-1',
            order_id='REGISTER-1',
            request_id='expected-request',
        )
        self.assertEqual(result.billing_key, 'secret-billing-key')
        self.assertEqual(result.card_brand, '신한카드')
        self.assertEqual(result.card_last4, '7890')

    def test_query_uses_original_request_id_and_never_charges(self):
        self.http.post.return_value = FakeResponse(self._approved_body())
        result = self.client.query(
            request_id='INPA-REQUEST-1',
            transaction_date='20270205',
            expected_order_id='INPA-ORDER-1',
            expected_amount=21890,
        )
        self.assertEqual(result.kind, 'approved')
        self.assertEqual(
            self.http.post.call_args.args[0],
            'https://testpgapi.easypay.co.kr'
            '/api/trades/retrieveTransaction',
        )
        self.assertEqual(self.http.post.call_count, 1)
