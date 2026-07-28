from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone as datetime_timezone
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import threading
import time as monotonic_time
import unittest
from unittest import mock

from django.conf import settings
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.core.cache import cache
from django.core.management import call_command
from django.db import (
    DatabaseError,
    IntegrityError,
    close_old_connections,
    connection,
)
from django.test import (
    SimpleTestCase,
    TestCase,
    TransactionTestCase,
    override_settings,
)
from django.utils import timezone
import httpx
from rest_framework.test import APITestCase

from inpa.accounts.models import Profile

from . import phone_verification as phone_verification_module
from .coupons import (
    CouponError,
    hold_recurring_coupon,
    preflight_recurring_coupon,
    redeem_held_coupon,
)
from .models import (
    BenefitGrantException,
    BenefitGrantLedger,
    BillingAgreement,
    Coupon,
    CouponClaim,
    CouponRedemption,
    ManualBenefitReview,
    PaymentMethodToken,
    PhoneVerificationChallenge,
    Plan,
    RecurringPaymentConsent,
    Subscription,
    VerifiedPhoneIdentity,
)
from .phone_verification import (
    PhoneVerificationError,
    _increment_rate_limit,
    build_phone_identity,
    create_otp_challenge,
    enforce_phone_request_limits,
    normalize_kr_mobile,
    _rate_cache_key,
    verify_otp_challenge,
)
from .sms import (
    SmsSendResult,
    SolapiProviderError,
    SolapiSmsClient,
    build_solapi_auth_header,
)


User = get_user_model()
TEST_PHONE_IDENTITY_SECRET = 'phone-identity-test-value-32-bytes-min'
TEST_SOLAPI_PUBLIC_ID = 'test-public-id'
TEST_SOLAPI_SIGNING_VALUE = 'test-signing-value'
PHONE_RATE_TEST_CACHE_TABLE = 'test_phone_rate_cache'
PHONE_RATE_DATABASE_CACHE = {
    'default': {
        'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
        'LOCATION': PHONE_RATE_TEST_CACHE_TABLE,
    },
}
PHONE_RATE_STRESS_REPETITIONS = 20


@override_settings(
    PHONE_IDENTITY_HMAC_KEY=TEST_PHONE_IDENTITY_SECRET,
    PHONE_IDENTITY_HMAC_KEY_VERSION='test-v1',
)
class PhoneIdentityAndOtpTests(TestCase):
    def setUp(self):
        Plan.objects.create(
            code='free',
            display_name='무료',
            price_krw=0,
        )
        self.user = User.objects.create_user(
            email='phone-identity@example.com',
            password='test-password',
        )

    def test_normalizes_only_supported_korean_mobile_numbers(self):
        self.assertEqual(
            normalize_kr_mobile('010-1234-5678'),
            '01012345678',
        )
        self.assertEqual(
            normalize_kr_mobile('+82 10 1234 5678'),
            '01012345678',
        )

        invalid_values = (
            '02-1234-5678',
            '011-123-4567',
            '+81 10 1234 5678',
            '010-123-4567',
            '010-1234-56789',
            '010-1234-ABCD',
        )
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(PhoneVerificationError) as caught:
                    normalize_kr_mobile(value)
                self.assertEqual(caught.exception.code, 'invalid_phone')
                self.assertNotIn(value, str(caught.exception))

    def test_identity_hmac_is_stable_but_key_version_separated(self):
        canonical = '01012345678'
        signing_key = 'same-key-material-at-least-32-bytes'
        first = build_phone_identity(
            canonical,
            key=signing_key,
            key_version='v1',
        )
        repeated = build_phone_identity(
            canonical,
            key=signing_key,
            key_version='v1',
        )
        rotated = build_phone_identity(
            canonical,
            key=signing_key,
            key_version='v2',
        )

        self.assertEqual(first.digest, repeated.digest)
        self.assertEqual(first.last4, '5678')
        self.assertEqual(len(first.digest), 64)
        self.assertNotEqual(first.digest, rotated.digest)
        self.assertEqual(rotated.key_version, 'v2')
        self.assertNotIn(canonical, first.digest)

    def test_identity_hmac_rejects_keys_shorter_than_32_bytes(self):
        with self.assertRaises(PhoneVerificationError) as captured:
            build_phone_identity(
                '01012345678',
                key='x' * 31,
                key_version='v1',
            )

        self.assertEqual(
            captured.exception.code,
            'phone_verification_setup_required',
        )

    def test_challenge_stores_only_password_hash_and_is_one_time(self):
        challenge, raw_code = create_otp_challenge(
            user=self.user,
            canonical_phone='01012345678',
            provider_transaction_ref='message-group-1',
        )

        self.assertEqual(len(raw_code), 6)
        self.assertTrue(raw_code.isdigit())
        self.assertNotEqual(challenge.otp_hash, raw_code)
        self.assertTrue(check_password(raw_code, challenge.otp_hash))
        stored = PhoneVerificationChallenge.objects.get(pk=challenge.pk)
        encoded = str({
            field.name: getattr(stored, field.name)
            for field in stored._meta.fields
        })
        self.assertNotIn('01012345678', encoded)
        self.assertNotIn(raw_code, encoded)

        identity = verify_otp_challenge(
            user=self.user,
            challenge_id=challenge.pk,
            canonical_phone='01012345678',
            code=raw_code,
        )
        self.assertEqual(identity.user, self.user)
        self.assertEqual(identity.phone_last4, '5678')

        with self.assertRaises(PhoneVerificationError) as caught:
            verify_otp_challenge(
                user=self.user,
                challenge_id=challenge.pk,
                canonical_phone='01012345678',
                code=raw_code,
            )
        self.assertEqual(caught.exception.code, 'phone_verification_failed')

    def test_challenge_expires_after_five_minutes(self):
        challenge, raw_code = create_otp_challenge(
            user=self.user,
            canonical_phone='01012345678',
            provider_transaction_ref='message-group-2',
        )
        PhoneVerificationChallenge.objects.filter(pk=challenge.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1),
        )

        with self.assertRaises(PhoneVerificationError) as caught:
            verify_otp_challenge(
                user=self.user,
                challenge_id=challenge.pk,
                canonical_phone='01012345678',
                code=raw_code,
            )
        self.assertEqual(caught.exception.code, 'phone_verification_failed')

    def test_five_failed_codes_lock_the_challenge(self):
        challenge, raw_code = create_otp_challenge(
            user=self.user,
            canonical_phone='01012345678',
            provider_transaction_ref='message-group-3',
        )

        for expected_remaining in (4, 3, 2, 1, 0):
            with self.assertRaises(PhoneVerificationError) as caught:
                verify_otp_challenge(
                    user=self.user,
                    challenge_id=challenge.pk,
                    canonical_phone='01012345678',
                    code='000000' if raw_code != '000000' else '999999',
                )
            self.assertEqual(
                caught.exception.code,
                'phone_verification_failed',
            )
            self.assertEqual(
                caught.exception.attempts_remaining,
                expected_remaining,
            )

        with self.assertRaises(PhoneVerificationError) as caught:
            verify_otp_challenge(
                user=self.user,
                challenge_id=challenge.pk,
                canonical_phone='01012345678',
                code=raw_code,
            )
        self.assertEqual(caught.exception.attempts_remaining, 0)

        challenge.refresh_from_db()
        self.assertEqual(challenge.attempt_count, 5)
        self.assertIsNone(challenge.verified_at)
        self.assertIsNone(challenge.consumed_at)


class SolapiSmsClientTests(TestCase):
    def setUp(self):
        self.http = mock.Mock()
        self.sleep = mock.Mock()
        self.client = SolapiSmsClient(
            api_key='key',
            api_secret='secret',
            sender_number='0212345678',
            http_client=self.http,
            sleep=self.sleep,
        )
        self.now = datetime(
            2026,
            7,
            28,
            tzinfo=datetime_timezone.utc,
        )

    @staticmethod
    def _response(status_code, payload=None):
        return httpx.Response(
            status_code,
            json=payload or {},
            request=httpx.Request(
                'POST',
                'https://api.solapi.com/messages/v4/send-many/detail',
            ),
        )

    def test_builds_official_fixed_hmac_header(self):
        header = build_solapi_auth_header(
            'key',
            'secret',
            now=self.now,
            salt='0123456789abcdef',
        )
        self.assertEqual(
            header,
            'HMAC-SHA256 apiKey=key, date=2026-07-28T00:00:00Z, '
            'salt=0123456789abcdef, '
            'signature='
            'a7c7ad62e22b00ae8c005b95024e8d9c95768f43c5bfd06de00e3c31c936d638',
        )

    def test_sends_digits_only_official_message_body_with_bounded_timeout(self):
        self.http.post.return_value = self._response(
            200,
            {'groupId': 'group-1'},
        )

        result = self.client.send_verification_sms(
            '01012345678',
            '123456',
            now=self.now,
            salt='0123456789abcdef',
        )

        self.assertEqual(result.provider_transaction_id, 'group-1')
        args, kwargs = self.http.post.call_args
        self.assertEqual(
            args[0],
            'https://api.solapi.com/messages/v4/send-many/detail',
        )
        self.assertEqual(kwargs['json'], {
            'messages': [{
                'to': '01012345678',
                'from': '0212345678',
                'text': '[인파] 인증번호는 123456입니다. 5분 안에 입력해 주세요.',
                'type': 'SMS',
            }],
        })
        self.assertEqual(
            kwargs['headers']['Authorization'],
            build_solapi_auth_header(
                'key',
                'secret',
                now=self.now,
                salt='0123456789abcdef',
            ),
        )
        self.assertIsInstance(kwargs['timeout'], httpx.Timeout)
        self.assertLessEqual(kwargs['timeout'].connect, 3.0)
        self.assertLessEqual(kwargs['timeout'].read, 10.0)

    def test_retries_timeout_429_and_server_errors_three_total_attempts(self):
        timeout = httpx.ReadTimeout(
            'timed out',
            request=httpx.Request('POST', 'https://provider.invalid'),
        )
        self.http.post.side_effect = [
            timeout,
            self._response(429),
            self._response(200, {'groupId': 'group-final'}),
        ]

        result = self.client.send_verification_sms(
            '01012345678',
            '123456',
        )

        self.assertEqual(result.provider_transaction_id, 'group-final')
        self.assertEqual(self.http.post.call_count, 3)
        self.assertEqual(
            [call.args[0] for call in self.sleep.call_args_list],
            [1, 2],
        )

    def test_does_not_retry_client_errors_or_sleep_after_final_failure(self):
        for status_code in (400, 401, 403):
            with self.subTest(status_code=status_code):
                self.http.reset_mock()
                self.sleep.reset_mock()
                self.http.post.return_value = self._response(status_code)

                with self.assertRaises(SolapiProviderError) as caught:
                    self.client.send_verification_sms(
                        '01012345678',
                        '123456',
                    )

                self.assertEqual(
                    caught.exception.code,
                    'provider_rejected',
                )
                self.assertEqual(self.http.post.call_count, 1)
                self.sleep.assert_not_called()

        self.http.reset_mock()
        self.sleep.reset_mock()
        self.http.post.side_effect = [
            self._response(503),
            self._response(503),
            self._response(503),
        ]
        with self.assertRaises(SolapiProviderError):
            self.client.send_verification_sms(
                '01012345678',
                '123456',
            )
        self.assertEqual(self.http.post.call_count, 3)
        self.assertEqual(
            [call.args[0] for call in self.sleep.call_args_list],
            [1, 2],
        )

    def test_failure_log_does_not_contain_phone_otp_auth_or_provider_body(self):
        sentinel = 'sentinel-sensitive-provider-body'
        self.http.post.return_value = self._response(
            400,
            {'error': sentinel},
        )

        with self.assertLogs('inpa.billing.sms', level='WARNING') as logs:
            with self.assertRaises(SolapiProviderError):
                self.client.send_verification_sms(
                    '01012345678',
                    '654321',
                    now=self.now,
                    salt='0123456789abcdef',
                )

        output = '\n'.join(logs.output)
        for forbidden in (
            sentinel,
            '01012345678',
            '654321',
            '0123456789abcdef',
            'a7c7ad62e22b00ae8c005b95024e8d9c95768f43c5bfd06de00e3c31c936d638',
        ):
            self.assertNotIn(forbidden, output)
        self.assertIn('provider_rejected', output)

    @mock.patch('inpa.billing.sms.httpx.Client')
    def test_closes_internally_created_http_client_after_success(
        self,
        client_class,
    ):
        internal = client_class.return_value
        internal.post.return_value = self._response(
            200,
            {'groupId': 'group-owned-success'},
        )
        client = SolapiSmsClient(
            api_key='key',
            api_secret='secret',
            sender_number='0212345678',
            sleep=self.sleep,
        )

        result = client.send_verification_sms(
            '01012345678',
            '123456',
        )

        self.assertEqual(
            result.provider_transaction_id,
            'group-owned-success',
        )
        internal.close.assert_called_once_with()

    @mock.patch('inpa.billing.sms.httpx.Client')
    def test_closes_internally_created_http_client_after_failures(
        self,
        client_class,
    ):
        for responses in (
            [self._response(400)],
            [
                self._response(503),
                self._response(503),
                self._response(503),
            ],
        ):
            with self.subTest(
                statuses=[response.status_code for response in responses],
            ):
                internal = client_class.return_value
                internal.reset_mock()
                internal.post.side_effect = responses
                client = SolapiSmsClient(
                    api_key='key',
                    api_secret='secret',
                    sender_number='0212345678',
                    sleep=self.sleep,
                )

                with self.assertRaises(SolapiProviderError):
                    client.send_verification_sms(
                        '01012345678',
                        '123456',
                    )

                internal.close.assert_called_once_with()

    def test_does_not_close_injected_http_client(self):
        external = mock.Mock()
        external.post.side_effect = [
            self._response(503),
            self._response(503),
            self._response(503),
        ]
        client = SolapiSmsClient(
            api_key='key',
            api_secret='secret',
            sender_number='0212345678',
            http_client=external,
            sleep=self.sleep,
        )

        with self.assertRaises(SolapiProviderError):
            client.send_verification_sms(
                '01012345678',
                '123456',
            )

        external.close.assert_not_called()


@override_settings(
    FREE_TRIAL_PHONE_VERIFICATION_ENABLED=True,
    PHONE_IDENTITY_HMAC_KEY=TEST_PHONE_IDENTITY_SECRET,
    PHONE_IDENTITY_HMAC_KEY_VERSION='test-v1',
)
class PhoneRequestRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_user_limit_is_five_per_ten_minutes(self):
        for index in range(5):
            enforce_phone_request_limits(
                user_id='user-1',
                phone_hmac=f'phone-{index}',
                ip_address=f'192.0.2.{index + 1}',
            )

        with self.assertRaises(PhoneVerificationError) as caught:
            enforce_phone_request_limits(
                user_id='user-1',
                phone_hmac='phone-six',
                ip_address='192.0.2.99',
            )
        self.assertEqual(caught.exception.code, 'phone_request_limited')

    def test_user_limit_is_ten_per_day_across_short_windows(self):
        for index in range(10):
            enforce_phone_request_limits(
                user_id='daily-user',
                phone_hmac=f'daily-phone-{index}',
                ip_address=f'198.51.100.{index + 1}',
            )
            prefix = _rate_cache_key('user-10m', 'daily-user')
            cache.delete_many([
                f'{prefix}:slot:{slot}'
                for slot in range(5)
            ])

        with self.assertRaises(PhoneVerificationError) as caught:
            enforce_phone_request_limits(
                user_id='daily-user',
                phone_hmac='daily-phone-final',
                ip_address='198.51.100.99',
            )
        self.assertEqual(caught.exception.code, 'phone_request_limited')

    def test_phone_limit_is_three_per_ten_minutes_across_users(self):
        for index in range(3):
            enforce_phone_request_limits(
                user_id=f'phone-user-{index}',
                phone_hmac='same-phone-hmac',
                ip_address=f'203.0.113.{index + 1}',
            )

        with self.assertRaises(PhoneVerificationError) as caught:
            enforce_phone_request_limits(
                user_id='phone-user-final',
                phone_hmac='same-phone-hmac',
                ip_address='203.0.113.99',
            )
        self.assertEqual(caught.exception.code, 'phone_request_limited')

    def test_ip_limit_is_ten_per_ten_minutes_without_raw_ip_cache_key(self):
        ip_address = '192.0.2.200'
        for index in range(10):
            enforce_phone_request_limits(
                user_id=f'ip-user-{index}',
                phone_hmac=f'ip-phone-{index}',
                ip_address=ip_address,
            )

        with self.assertRaises(PhoneVerificationError) as caught:
            enforce_phone_request_limits(
                user_id='ip-user-final',
                phone_hmac='ip-phone-final',
                ip_address=ip_address,
            )
        self.assertEqual(caught.exception.code, 'phone_request_limited')
        cache_keys = ' '.join(str(key) for key in cache._cache.keys())
        self.assertNotIn(ip_address, cache_keys)
        self.assertNotIn('01012345678', cache_keys)
        self.assertNotIn(
            hashlib.sha256(ip_address.encode()).hexdigest(),
            cache_keys,
        )

    def test_same_user_and_phone_have_sixty_second_resend_cooldown(self):
        enforce_phone_request_limits(
            user_id='cooldown-user',
            phone_hmac='cooldown-phone',
            ip_address='198.51.100.200',
        )
        with self.assertRaises(PhoneVerificationError) as caught:
            enforce_phone_request_limits(
                user_id='cooldown-user',
                phone_hmac='cooldown-phone',
                ip_address='198.51.100.200',
            )
        self.assertEqual(caught.exception.code, 'phone_request_cooldown')

    def test_cooldown_backend_failure_preserves_unavailable_error(self):
        backend_error = PhoneVerificationError(
            'phone_rate_limit_unavailable',
            '인증번호 발송을 다시 준비하고 있어요. 잠시 뒤 시도해 주세요.',
        )
        with mock.patch(
            'inpa.billing.phone_verification._increment_rate_limit',
            side_effect=[
                None,
                None,
                None,
                None,
                backend_error,
            ],
        ):
            with self.assertRaises(PhoneVerificationError) as caught:
                enforce_phone_request_limits(
                    user_id='backend-user',
                    phone_hmac='backend-phone',
                    ip_address='192.0.2.10',
                )

        self.assertEqual(
            caught.exception.code,
            'phone_rate_limit_unavailable',
        )


@override_settings(
    CACHES=PHONE_RATE_DATABASE_CACHE,
    FREE_TRIAL_PHONE_VERIFICATION_ENABLED=True,
    PHONE_IDENTITY_HMAC_KEY=TEST_PHONE_IDENTITY_SECRET,
    PHONE_IDENTITY_HMAC_KEY_VERSION='test-v1',
)
class PhoneRequestDatabaseCacheConcurrencyTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        call_command(
            'createcachetable',
            PHONE_RATE_TEST_CACHE_TABLE,
            verbosity=0,
        )

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def _run_concurrently(self, attempts, callback):
        barrier = threading.Barrier(attempts)

        def invoke(index):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    callback(index)
                    return 'accepted'
                except PhoneVerificationError as exc:
                    return exc.code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=attempts) as executor:
            return list(executor.map(invoke, range(attempts)))

    def assert_limit(self, results, expected_accepted):
        self.assertEqual(
            results.count('accepted'),
            expected_accepted,
            results,
        )
        self.assertEqual(
            len(results) - expected_accepted,
            results.count('phone_request_limited')
            + results.count('phone_request_cooldown'),
            results,
        )

    def test_user_ten_minute_limit_accepts_only_five_concurrently(self):
        started = monotonic_time.monotonic()
        for repeat in range(PHONE_RATE_STRESS_REPETITIONS):
            cache.clear()
            results = self._run_concurrently(
                8,
                lambda index: enforce_phone_request_limits(
                    user_id=f'same-user-10m-{repeat}',
                    phone_hmac=f'unique-phone-{repeat}-{index}',
                    ip_address=f'192.0.{repeat}.{index + 1}',
                ),
            )
            with self.subTest(repeat=repeat):
                self.assert_limit(results, 5)
        self.assertLess(
            monotonic_time.monotonic() - started,
            20,
        )

    def test_user_daily_limit_accepts_only_ten_concurrently(self):
        started = monotonic_time.monotonic()
        for repeat in range(PHONE_RATE_STRESS_REPETITIONS):
            cache.clear()
            results = self._run_concurrently(
                14,
                lambda _index: _increment_rate_limit(
                    'user-day',
                    f'same-user-day-{repeat}',
                    limit=10,
                    timeout=86400,
                ),
            )
            with self.subTest(repeat=repeat):
                self.assert_limit(results, 10)
        self.assertLess(
            monotonic_time.monotonic() - started,
            20,
        )

    def test_phone_limit_accepts_only_three_concurrently(self):
        started = monotonic_time.monotonic()
        for repeat in range(PHONE_RATE_STRESS_REPETITIONS):
            cache.clear()
            results = self._run_concurrently(
                7,
                lambda index: enforce_phone_request_limits(
                    user_id=f'unique-phone-user-{repeat}-{index}',
                    phone_hmac=f'same-phone-hmac-{repeat}',
                    ip_address=f'198.51.{repeat}.{index + 1}',
                ),
            )
            with self.subTest(repeat=repeat):
                self.assert_limit(results, 3)
        self.assertLess(
            monotonic_time.monotonic() - started,
            20,
        )

    def test_ip_limit_accepts_only_ten_concurrently(self):
        raw_ip = '203.0.113.200'
        started = monotonic_time.monotonic()
        for repeat in range(PHONE_RATE_STRESS_REPETITIONS):
            cache.clear()
            results = self._run_concurrently(
                14,
                lambda index: enforce_phone_request_limits(
                    user_id=f'unique-ip-user-{repeat}-{index}',
                    phone_hmac=f'unique-ip-phone-{repeat}-{index}',
                    ip_address=raw_ip,
                ),
            )
            with self.subTest(repeat=repeat):
                self.assert_limit(results, 10)
        with connection.cursor() as cursor:
            cursor.execute(
                f'SELECT cache_key FROM {PHONE_RATE_TEST_CACHE_TABLE}',
            )
            stored_keys = ' '.join(
                str(row[0])
                for row in cursor.fetchall()
            )
        self.assertNotIn(raw_ip, stored_keys)
        self.assertNotIn('01012345678', stored_keys)
        self.assertLess(
            monotonic_time.monotonic() - started,
            20,
        )

    def test_cooldown_accepts_only_one_concurrently(self):
        started = monotonic_time.monotonic()
        for repeat in range(PHONE_RATE_STRESS_REPETITIONS):
            cache.clear()
            results = self._run_concurrently(
                5,
                lambda _index: enforce_phone_request_limits(
                    user_id=f'same-cooldown-user-{repeat}',
                    phone_hmac=f'same-cooldown-phone-{repeat}',
                    ip_address=f'192.0.{repeat}.250',
                ),
            )
            with self.subTest(repeat=repeat):
                self.assert_limit(results, 1)
        self.assertLess(
            monotonic_time.monotonic() - started,
            20,
        )

    def test_expired_bucket_mutex_recovers_and_admits_request(self):
        prefix = _rate_cache_key('stale-lock', 'same-value')
        lock_key = f'{prefix}:lock'
        cache.set(lock_key, 'stale-owner', timeout=-1)

        _increment_rate_limit(
            'stale-lock',
            'same-value',
            limit=1,
            timeout=60,
        )

        self.assertEqual(
            cache.get(f'{prefix}:slot:0'),
            1,
        )
        self.assertIsNone(cache.get(lock_key))

    def test_non_owner_cannot_release_reacquired_bucket_mutex(self):
        prefix = _rate_cache_key('owned-lock', 'same-value')
        lock_key = f'{prefix}:lock'
        cache.set(lock_key, 'current-owner', timeout=60)

        phone_verification_module._release_rate_bucket_lock(
            lock_key,
            'stale-owner',
        )

        self.assertEqual(cache.get(lock_key), 'current-owner')

    def test_bucket_mutex_deadline_uses_distinct_fail_closed_error(self):
        with (
            mock.patch.object(
                phone_verification_module,
                '_RATE_LOCK_WAIT_SECONDS',
                0.02,
            ),
            mock.patch(
                'inpa.billing.phone_verification.cache.add',
                side_effect=DatabaseError('cache unavailable'),
            ),
        ):
            started = monotonic_time.monotonic()
            with self.assertRaises(PhoneVerificationError) as caught:
                _increment_rate_limit(
                    'backend-failure',
                    'same-value',
                    limit=3,
                    timeout=60,
                )

        self.assertEqual(
            caught.exception.code,
            'phone_rate_limit_unavailable',
        )
        self.assertLess(
            monotonic_time.monotonic() - started,
            1,
        )


@override_settings(
    FREE_TRIAL_PHONE_VERIFICATION_ENABLED=True,
    SOLAPI_API_KEY=TEST_SOLAPI_PUBLIC_ID,
    SOLAPI_API_SECRET=TEST_SOLAPI_SIGNING_VALUE,
    SOLAPI_SENDER_NUMBER='0212345678',
    PHONE_IDENTITY_HMAC_KEY=TEST_PHONE_IDENTITY_SECRET,
    PHONE_IDENTITY_HMAC_KEY_VERSION='test-v1',
)
class PhoneVerificationApiTests(APITestCase):
    def setUp(self):
        cache.clear()
        Plan.objects.create(
            code='free',
            display_name='무료',
            price_krw=0,
        )
        self.user = User.objects.create_user(
            email='phone-api@example.com',
            password='test-password',
        )
        self.client.force_authenticate(self.user)

    def tearDown(self):
        cache.clear()

    @override_settings(FREE_TRIAL_PHONE_VERIFICATION_ENABLED=False)
    def test_request_gate_is_closed_without_sending(self):
        with mock.patch(
            'inpa.billing.phone_verification.SolapiSmsClient',
        ) as client_class:
            response = self.client.post(
                '/api/v1/billing/free-trial/phone/request/',
                {'phone': '01012345678'},
                format='json',
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.data['code'],
            'phone_verification_setup_required',
        )
        client_class.assert_not_called()

    @mock.patch('inpa.billing.phone_verification.SolapiSmsClient')
    def test_request_returns_only_masked_challenge_contract(
        self,
        client_class,
    ):
        sender = client_class.return_value
        sender.send_verification_sms.return_value = SmsSendResult(
            provider_transaction_id='provider-group-1',
        )

        response = self.client.post(
            '/api/v1/billing/free-trial/phone/request/',
            {'phone': '+82 10 1234 5678'},
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(set(response.data), {
            'challenge_id',
            'expires_in_seconds',
            'phone_masked',
        })
        self.assertEqual(response.data['expires_in_seconds'], 300)
        self.assertEqual(
            response.data['phone_masked'],
            '010-****-5678',
        )
        challenge = PhoneVerificationChallenge.objects.get(
            pk=response.data['challenge_id'],
        )
        raw_code = sender.send_verification_sms.call_args.args[1]
        self.assertTrue(check_password(raw_code, challenge.otp_hash))
        self.assertEqual(
            challenge.provider_transaction_ref,
            'provider-group-1',
        )
        self.assertNotIn(
            '01012345678',
            str(PhoneVerificationChallenge.objects.values().get()),
        )

    @mock.patch('inpa.billing.phone_verification.SolapiSmsClient')
    def test_provider_failure_does_not_create_a_challenge(
        self,
        client_class,
    ):
        client_class.return_value.send_verification_sms.side_effect = (
            SolapiProviderError('provider_unavailable')
        )

        response = self.client.post(
            '/api/v1/billing/free-trial/phone/request/',
            {'phone': '01012345678'},
            format='json',
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.data['code'],
            'phone_verification_temporarily_unavailable',
        )
        self.assertFalse(PhoneVerificationChallenge.objects.exists())

    @mock.patch('inpa.billing.phone_verification.SolapiSmsClient')
    def test_invalid_phone_returns_generic_validation_without_send(
        self,
        client_class,
    ):
        raw_phone = '010-1234-ABCD'
        response = self.client.post(
            '/api/v1/billing/free-trial/phone/request/',
            {'phone': raw_phone},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'invalid_phone')
        self.assertNotIn(raw_phone, str(response.data))
        client_class.assert_not_called()

    @mock.patch('inpa.billing.phone_verification.SolapiSmsClient')
    def test_rate_limit_happens_before_second_provider_send(
        self,
        client_class,
    ):
        sender = client_class.return_value
        sender.send_verification_sms.return_value = SmsSendResult(
            provider_transaction_id='provider-group-rate',
        )
        first = self.client.post(
            '/api/v1/billing/free-trial/phone/request/',
            {'phone': '01012345678'},
            format='json',
        )
        second = self.client.post(
            '/api/v1/billing/free-trial/phone/request/',
            {'phone': '01012345678'},
            format='json',
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(
            second.data['code'],
            'phone_request_cooldown',
        )
        self.assertEqual(
            sender.send_verification_sms.call_count,
            1,
        )
        self.assertEqual(
            PhoneVerificationChallenge.objects.count(),
            1,
        )

    @mock.patch('inpa.billing.phone_verification.SolapiSmsClient')
    def test_verify_requires_matching_phone_and_code_then_consumes_once(
        self,
        client_class,
    ):
        sender = client_class.return_value
        sender.send_verification_sms.return_value = SmsSendResult(
            provider_transaction_id='provider-group-verify',
        )
        requested = self.client.post(
            '/api/v1/billing/free-trial/phone/request/',
            {'phone': '01012345678'},
            format='json',
        ).data
        raw_code = sender.send_verification_sms.call_args.args[1]

        wrong_phone = self.client.post(
            '/api/v1/billing/free-trial/phone/verify/',
            {
                'challenge_id': requested['challenge_id'],
                'phone': '01099995678',
                'code': raw_code,
            },
            format='json',
        )
        self.assertEqual(wrong_phone.status_code, 400)
        self.assertEqual(
            wrong_phone.data['code'],
            'phone_verification_failed',
        )
        self.assertNotIn('01099995678', str(wrong_phone.data))

        verified = self.client.post(
            '/api/v1/billing/free-trial/phone/verify/',
            {
                'challenge_id': requested['challenge_id'],
                'phone': '01012345678',
                'code': raw_code,
            },
            format='json',
        )
        self.assertEqual(verified.status_code, 200, verified.data)
        self.assertEqual(verified.data, {
            'verified': True,
            'phone_masked': '010-****-5678',
        })

        repeated = self.client.post(
            '/api/v1/billing/free-trial/phone/verify/',
            {
                'challenge_id': requested['challenge_id'],
                'phone': '01012345678',
                'code': raw_code,
            },
            format='json',
        )
        self.assertEqual(repeated.status_code, 400)
        self.assertEqual(
            repeated.data['code'],
            'phone_verification_failed',
        )

    @mock.patch('inpa.billing.phone_verification.SolapiSmsClient')
    def test_verify_failure_response_does_not_reveal_challenge_existence(
        self,
        client_class,
    ):
        sender = client_class.return_value
        sender.send_verification_sms.return_value = SmsSendResult(
            provider_transaction_id='provider-group-enumeration',
        )
        requested = self.client.post(
            '/api/v1/billing/free-trial/phone/request/',
            {'phone': '01012345678'},
            format='json',
        ).data

        wrong_code = self.client.post(
            '/api/v1/billing/free-trial/phone/verify/',
            {
                'challenge_id': requested['challenge_id'],
                'phone': '01012345678',
                'code': '000000',
            },
            format='json',
        )
        missing_challenge = self.client.post(
            '/api/v1/billing/free-trial/phone/verify/',
            {
                'challenge_id':
                    '00000000-0000-0000-0000-000000000000',
                'phone': '01012345678',
                'code': '000000',
            },
            format='json',
        )

        self.assertEqual(wrong_code.status_code, 400)
        self.assertEqual(missing_challenge.status_code, 400)
        self.assertEqual(wrong_code.data, missing_challenge.data)
        self.assertEqual(set(wrong_code.data), {'code', 'detail'})

    def test_request_uses_drf_proxy_aware_client_identity(self):
        rest_framework = {
            **settings.REST_FRAMEWORK,
            'NUM_PROXIES': 1,
        }
        with (
            override_settings(REST_FRAMEWORK=rest_framework),
            mock.patch(
                'inpa.billing.views.request_phone_verification',
                side_effect=PhoneVerificationError(
                    'phone_request_limited',
                    '요청이 많아요. 잠시 뒤 다시 시도해 주세요.',
                ),
            ) as request_verification,
        ):
            response = self.client.post(
                '/api/v1/billing/free-trial/phone/request/',
                {'phone': '01012345678'},
                format='json',
                REMOTE_ADDR='10.0.0.8',
                HTTP_X_FORWARDED_FOR='203.0.113.77',
            )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(
            request_verification.call_args.kwargs['ip_address'],
            '203.0.113.77',
        )

    def test_rate_limit_backend_deadline_returns_fail_closed_service_error(
        self,
    ):
        with mock.patch(
            'inpa.billing.views.request_phone_verification',
            side_effect=PhoneVerificationError(
                'phone_rate_limit_unavailable',
                '인증번호 발송을 다시 준비하고 있어요. 잠시 뒤 시도해 주세요.',
            ),
        ):
            response = self.client.post(
                '/api/v1/billing/free-trial/phone/request/',
                {'phone': '01012345678'},
                format='json',
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.data['code'],
            'phone_rate_limit_unavailable',
        )


class PhoneVerificationSettingsTests(SimpleTestCase):
    def test_local_defaults_keep_gate_closed_and_secrets_blank(self):
        self.assertFalse(
            settings.FREE_TRIAL_PHONE_VERIFICATION_ENABLED,
        )
        self.assertEqual(settings.SOLAPI_API_KEY, '')
        self.assertEqual(settings.SOLAPI_API_SECRET, '')
        self.assertEqual(settings.SOLAPI_SENDER_NUMBER, '')
        self.assertEqual(settings.PHONE_IDENTITY_HMAC_KEY, '')
        self.assertEqual(
            settings.PHONE_IDENTITY_HMAC_KEY_VERSION,
            'v1',
        )

    def test_production_gate_open_without_all_secrets_fails_loud(self):
        environment = os.environ.copy()
        environment.update({
            'DJANGO_SETTINGS_MODULE': 'config.settings.prod',
            'SECRET_KEY': 'test-' + 'only-settings-value',
            'DATABASE_URL': 'sqlite:///:memory:',
            'FREE_TRIAL_PHONE_VERIFICATION_ENABLED': 'True',
        })
        for name in (
            'SOLAPI_API_KEY',
            'SOLAPI_API_SECRET',
            'SOLAPI_SENDER_NUMBER',
            'PHONE_IDENTITY_HMAC_KEY',
        ):
            environment.pop(name, None)
        result = subprocess.run(
            [
                sys.executable,
                '-c',
                'import django; django.setup()',
            ],
            cwd=Path(settings.BASE_DIR),
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        output = f'{result.stdout}\n{result.stderr}'
        self.assertIn(
            'FREE_TRIAL_PHONE_VERIFICATION_ENABLED',
            output,
        )
        self.assertNotIn('test-only-settings-value', output)

    def test_production_gate_open_with_short_hmac_key_fails_loud(self):
        environment = os.environ.copy()
        environment.update({
            'DJANGO_SETTINGS_MODULE': 'config.settings.prod',
            'SECRET_KEY': 'test-' + 'only-settings-value',
            'DATABASE_URL': 'sqlite:///:memory:',
            'FREE_TRIAL_PHONE_VERIFICATION_ENABLED': 'True',
            'SOLAPI_API_KEY': 'test-public-value',
            'SOLAPI_API_SECRET': 'test-signing-value',
            'SOLAPI_SENDER_NUMBER': '01000000000',
            'PHONE_IDENTITY_HMAC_KEY': 'short-test-value',
        })
        result = subprocess.run(
            [
                sys.executable,
                '-c',
                'import django; django.setup()',
            ],
            cwd=Path(settings.BASE_DIR),
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        output = f'{result.stdout}\n{result.stderr}'
        self.assertIn('at least 32 bytes', output)
        self.assertNotIn('short-test-value', output)


@override_settings(
    FREE_TRIAL_PHONE_VERIFICATION_ENABLED=True,
    PHONE_IDENTITY_HMAC_KEY=TEST_PHONE_IDENTITY_SECRET,
    PHONE_IDENTITY_HMAC_KEY_VERSION='test-v1',
)
class PhoneBenefitCouponTests(TestCase):
    def setUp(self):
        self.free = Plan.objects.create(
            code='free',
            display_name='무료',
            price_krw=0,
        )
        self.plus = Plan.objects.create(
            code='plus',
            display_name='Plus',
            price_krw=19900,
        )
        self.user = User.objects.create_user(
            email='phone-benefit@example.com',
            password='test-password',
        )
        self.other = User.objects.create_user(
            email='phone-benefit-other@example.com',
            password='test-password',
        )
        self.coupon = Coupon.objects.create(
            code='PHONE-MONTH-1',
            plan=self.plus,
            coupon_kind='recurring_trial',
            duration_months=1,
            redeem_by=timezone.now() + timedelta(days=30),
            max_redemptions=10,
        )
        self.identity = self._verify_identity(self.user)

    @staticmethod
    def _verify_identity(user, phone='01012345678'):
        identity = build_phone_identity(phone)
        return VerifiedPhoneIdentity.objects.create(
            user=user,
            phone_hmac=identity.digest,
            key_version=identity.key_version,
            phone_last4=identity.last4,
            provider='solapi_sms',
            verified_at=timezone.now(),
            provider_transaction_ref='provider-test',
        )

    def _agreement(self, user):
        agreement = BillingAgreement.objects.create(
            user=user,
            plan=self.plus,
            status='trialing',
            billing_anchor_day=5,
            trial_duration_months=self.coupon.duration_months,
            current_period_starts_on=date(2027, 1, 5),
            current_period_ends_on=date(2027, 2, 4),
            next_charge_date=date(2027, 2, 5),
        )
        PaymentMethodToken.objects.create(
            agreement=agreement,
            encrypted_token='ciphertext',
            key_version='v1',
            card_brand='신한',
            card_last4='1234',
            status='active',
        )
        RecurringPaymentConsent.objects.create(
            agreement=agreement,
            kind='trial_start',
            consent_version='v1',
            plan_code='plus',
            amount_krw=21890,
            charge_date=date(2027, 2, 5),
            card_label='신한 끝 1234',
            cancel_effect=date(2027, 2, 4),
            display_snapshot_hash='a' * 64,
            accepted_at=timezone.now(),
        )
        return agreement

    def _existing_ledger(self, *, user=None, key_version='test-v1'):
        return BenefitGrantLedger.objects.create(
            identity_hmac=self.identity.phone_hmac,
            key_version=key_version,
            benefit_code=BenefitGrantLedger.BENEFIT_PLUS_TRIAL_MONTH,
            user=user or self.other,
            granted_at=timezone.now() - timedelta(days=90),
            granted_until=timezone.now() - timedelta(days=60),
            coupon_snapshot={'coupon_code': 'ORIGINAL'},
        )

    def _approved_review(self, *, user=None, identity_hmac=None):
        return ManualBenefitReview.objects.create(
            user=user or self.user,
            identity_hmac=identity_hmac or self.identity.phone_hmac,
            key_version=self.identity.key_version,
            phone_last4=self.identity.phone_last4,
            contact_email='review-contact@example.com',
            reason='번호 재할당 여부를 확인해 주세요.',
            status=ManualBenefitReview.STATUS_APPROVED,
            reviewer=self.other,
            decision_reason='운영 확인을 완료했습니다.',
            decided_at=timezone.now(),
        )

    def test_gate_open_preflight_requires_current_verified_identity(self):
        self.identity.delete()

        with self.assertRaises(CouponError) as caught:
            preflight_recurring_coupon(
                self.user,
                self.coupon.code,
            )

        self.assertEqual(
            caught.exception.code,
            'phone_verification_required',
        )
        self.assertFalse(CouponClaim.objects.exists())

    def test_existing_benefit_returns_stable_manual_review_code_only(self):
        self._existing_ledger()

        with self.assertRaises(CouponError) as caught:
            preflight_recurring_coupon(
                self.user,
                self.coupon.code,
            )

        self.assertEqual(
            caught.exception.code,
            'manual_benefit_review_required',
        )
        self.assertEqual(
            str(caught.exception),
            '확인이 필요한 번호예요. 이메일과 간단한 사유를 남기면 확인 후 안내해 드릴게요.',
        )
        self.assertNotIn(self.other.email, str(caught.exception))

    def test_key_version_change_fails_closed_before_coupon_hold(self):
        BenefitGrantLedger.objects.create(
            identity_hmac='f' * 64,
            key_version='previous-v0',
            benefit_code=BenefitGrantLedger.BENEFIT_PLUS_TRIAL_MONTH,
            user=self.other,
            granted_at=timezone.now() - timedelta(days=90),
            granted_until=timezone.now() - timedelta(days=60),
            coupon_snapshot={'coupon_code': 'PREVIOUS-KEY'},
        )

        with self.assertRaises(CouponError) as caught:
            hold_recurring_coupon(self.user, self.coupon.code)

        self.assertEqual(
            caught.exception.code,
            'phone_identity_key_rotation_required',
        )
        self.assertFalse(CouponClaim.objects.exists())

    def test_approved_review_for_same_user_and_identity_allows_hold(self):
        self._existing_ledger()
        review = self._approved_review()

        claim = hold_recurring_coupon(self.user, self.coupon.code)

        self.assertEqual(claim.status, 'held')
        self.assertEqual(
            claim.policy_snapshot['phone_identity_hmac'],
            self.identity.phone_hmac,
        )
        review.refresh_from_db()
        self.assertEqual(
            review.status,
            ManualBenefitReview.STATUS_APPROVED,
        )

    def test_approved_review_for_another_user_does_not_allow_hold(self):
        self._existing_ledger()
        self._approved_review(user=self.other)

        with self.assertRaises(CouponError) as caught:
            hold_recurring_coupon(self.user, self.coupon.code)

        self.assertEqual(
            caught.exception.code,
            'manual_benefit_review_required',
        )

    def test_first_redeem_creates_immutable_benefit_ledger_atomically(self):
        claim = hold_recurring_coupon(self.user, self.coupon.code)
        agreement = self._agreement(self.user)

        result = redeem_held_coupon(claim, agreement)

        ledger = BenefitGrantLedger.objects.get()
        self.assertEqual(ledger.identity_hmac, self.identity.phone_hmac)
        self.assertEqual(ledger.key_version, self.identity.key_version)
        self.assertEqual(ledger.user, self.user)
        self.assertEqual(
            ledger.benefit_code,
            BenefitGrantLedger.BENEFIT_PLUS_TRIAL_MONTH,
        )
        self.assertEqual(
            ledger.coupon_snapshot['coupon_code'],
            self.coupon.code,
        )
        self.assertEqual(
            timezone.localtime(ledger.granted_until).isoformat(),
            result['expires_at'],
        )
        self.assertFalse(BenefitGrantException.objects.exists())

    def test_approved_review_records_exception_without_mutating_original(self):
        original = self._existing_ledger()
        original_snapshot = {
            'user_id': original.user_id,
            'granted_at': original.granted_at,
            'granted_until': original.granted_until,
            'coupon_snapshot': original.coupon_snapshot.copy(),
        }
        review = self._approved_review()
        claim = hold_recurring_coupon(self.user, self.coupon.code)
        agreement = self._agreement(self.user)

        redeem_held_coupon(claim, agreement)

        original.refresh_from_db()
        review.refresh_from_db()
        exception = BenefitGrantException.objects.get()
        self.assertEqual(original.user_id, original_snapshot['user_id'])
        self.assertEqual(
            original.granted_at,
            original_snapshot['granted_at'],
        )
        self.assertEqual(
            original.granted_until,
            original_snapshot['granted_until'],
        )
        self.assertEqual(
            original.coupon_snapshot,
            original_snapshot['coupon_snapshot'],
        )
        self.assertEqual(exception.original_ledger, original)
        self.assertEqual(exception.review, review)
        self.assertEqual(exception.user, self.user)
        self.assertEqual(
            review.status,
            ManualBenefitReview.STATUS_CONSUMED,
        )
        self.assertIsNotNone(review.consumed_at)

    def test_coupon_failure_rolls_back_exception_and_review_consumption(self):
        original = self._existing_ledger()
        review = self._approved_review()
        claim = hold_recurring_coupon(self.user, self.coupon.code)
        agreement = self._agreement(self.user)
        before = Subscription.objects.get(user=self.user)
        before_values = (
            before.plan_id,
            before.status,
            before.expires_at,
        )

        with mock.patch(
            'inpa.billing.coupons.CouponRedemption.objects.create',
            side_effect=IntegrityError('forced redemption failure'),
        ):
            with self.assertRaises(IntegrityError):
                redeem_held_coupon(claim, agreement)

        review.refresh_from_db()
        claim.refresh_from_db()
        after = Subscription.objects.get(user=self.user)
        self.assertEqual(
            review.status,
            ManualBenefitReview.STATUS_APPROVED,
        )
        self.assertIsNone(review.consumed_at)
        self.assertFalse(BenefitGrantException.objects.exists())
        self.assertTrue(BenefitGrantLedger.objects.filter(
            pk=original.pk,
        ).exists())
        self.assertEqual(claim.status, 'held')
        self.assertEqual(
            (after.plan_id, after.status, after.expires_at),
            before_values,
        )
        self.assertEqual(self.coupon.redeemed_count, 0)


@override_settings(
    FREE_TRIAL_PHONE_VERIFICATION_ENABLED=True,
    PHONE_IDENTITY_HMAC_KEY=TEST_PHONE_IDENTITY_SECRET,
    PHONE_IDENTITY_HMAC_KEY_VERSION='test-v1',
)
class ManualBenefitReviewApiTests(APITestCase):
    def setUp(self):
        self.free = Plan.objects.create(
            code='free',
            display_name='무료',
            price_krw=0,
        )
        self.user = User.objects.create_user(
            email='manual-review-user@example.com',
            password='test-password',
        )
        self.admin_user = User.objects.create_user(
            email='manual-review-admin@example.com',
            password='test-password',
        )
        Profile.objects.create(
            user=self.admin_user,
            is_admin=True,
        )
        identity = build_phone_identity('01012345678')
        self.identity = VerifiedPhoneIdentity.objects.create(
            user=self.user,
            phone_hmac=identity.digest,
            key_version=identity.key_version,
            phone_last4=identity.last4,
            provider='solapi_sms',
            verified_at=timezone.now(),
            provider_transaction_ref='provider-review',
        )
        self.client.force_authenticate(self.user)

    def _ledger(self):
        return BenefitGrantLedger.objects.create(
            identity_hmac=self.identity.phone_hmac,
            key_version=self.identity.key_version,
            benefit_code=BenefitGrantLedger.BENEFIT_PLUS_TRIAL_MONTH,
            user=self.admin_user,
            granted_at=timezone.now() - timedelta(days=60),
            granted_until=timezone.now() - timedelta(days=30),
            coupon_snapshot={'coupon_code': 'FIRST'},
        )

    def _request(self, **overrides):
        payload = {
            'contact_email': 'contact@example.com',
            'reason': '번호 재할당 가능성을 확인해 주세요.',
        }
        payload.update(overrides)
        return self.client.post(
            '/api/v1/billing/free-trial/manual-reviews/',
            payload,
            format='json',
        )

    def test_review_request_requires_previous_benefit_for_current_identity(self):
        response = self._request()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.data['code'],
            'manual_benefit_review_not_required',
        )
        self.assertFalse(ManualBenefitReview.objects.exists())

    def test_review_request_rejects_client_phone_or_digest_binding(self):
        self._ledger()
        for injected in (
            {'phone': '01099999999'},
            {'identity_hmac': 'f' * 64},
        ):
            with self.subTest(injected=injected):
                response = self._request(**injected)
                self.assertEqual(response.status_code, 400)
        self.assertFalse(ManualBenefitReview.objects.exists())

    def test_review_request_is_idempotent_and_never_exposes_digest(self):
        self._ledger()

        first = self._request()
        second = self._request(
            contact_email='different@example.com',
            reason='다른 사유로 반복 제출',
        )

        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(first.data['id'], second.data['id'])
        self.assertEqual(first.data['status'], 'pending')
        self.assertEqual(
            first.data['phone_masked'],
            '010-****-5678',
        )
        encoded = str(first.data)
        self.assertNotIn(self.identity.phone_hmac, encoded)
        self.assertNotIn('01012345678', encoded)
        self.assertEqual(ManualBenefitReview.objects.count(), 1)

    def test_current_review_returns_only_the_users_current_identity(self):
        self._ledger()
        review = ManualBenefitReview.objects.create(
            user=self.user,
            identity_hmac=self.identity.phone_hmac,
            key_version=self.identity.key_version,
            phone_last4=self.identity.phone_last4,
            benefit_code=BenefitGrantLedger.BENEFIT_PLUS_TRIAL_MONTH,
            contact_email='contact@example.com',
            reason='번호 재할당 가능성을 확인해 주세요.',
            status=ManualBenefitReview.STATUS_REJECTED,
            reviewer=self.admin_user,
            decision_reason='확인 자료를 다시 남겨 주세요.',
            decided_at=timezone.now(),
        )
        other_identity = build_phone_identity('01099995678')
        ManualBenefitReview.objects.create(
            user=self.user,
            identity_hmac=other_identity.digest,
            key_version=other_identity.key_version,
            phone_last4=other_identity.last4,
            benefit_code=BenefitGrantLedger.BENEFIT_PLUS_TRIAL_MONTH,
            contact_email='other@example.com',
            reason='다른 번호의 요청입니다.',
            status=ManualBenefitReview.STATUS_PENDING,
        )

        response = self.client.get(
            '/api/v1/billing/free-trial/manual-reviews/',
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['id'], review.id)
        self.assertEqual(response.data['status'], 'rejected')
        self.assertEqual(response.data['phone_masked'], '010-****-5678')
        encoded = str(response.data)
        self.assertNotIn(self.identity.phone_hmac, encoded)
        self.assertNotIn(other_identity.digest, encoded)
        self.assertNotIn('01012345678', encoded)
        self.assertNotIn('01099995678', encoded)

    def test_current_review_returns_not_found_when_current_identity_has_none(self):
        self._ledger()
        other_identity = build_phone_identity('01099995678')
        ManualBenefitReview.objects.create(
            user=self.user,
            identity_hmac=other_identity.digest,
            key_version=other_identity.key_version,
            phone_last4=other_identity.last4,
            benefit_code=BenefitGrantLedger.BENEFIT_PLUS_TRIAL_MONTH,
            contact_email='other@example.com',
            reason='다른 번호의 요청입니다.',
            status=ManualBenefitReview.STATUS_PENDING,
        )

        response = self.client.get(
            '/api/v1/billing/free-trial/manual-reviews/',
        )

        self.assertEqual(response.status_code, 404)

    @override_settings(FREE_TRIAL_PHONE_VERIFICATION_ENABLED=False)
    def test_current_review_is_hidden_when_the_phone_benefit_gate_is_closed(self):
        self._ledger()
        ManualBenefitReview.objects.create(
            user=self.user,
            identity_hmac=self.identity.phone_hmac,
            key_version=self.identity.key_version,
            phone_last4=self.identity.phone_last4,
            benefit_code=BenefitGrantLedger.BENEFIT_PLUS_TRIAL_MONTH,
            contact_email='contact@example.com',
            reason='번호 재할당 가능성을 확인해 주세요.',
            status=ManualBenefitReview.STATUS_PENDING,
        )

        response = self.client.get(
            '/api/v1/billing/free-trial/manual-reviews/',
        )

        self.assertEqual(response.status_code, 404)

    def test_review_request_does_not_create_again_after_terminal_decision(self):
        self._ledger()
        review = ManualBenefitReview.objects.create(
            user=self.user,
            identity_hmac=self.identity.phone_hmac,
            key_version=self.identity.key_version,
            phone_last4=self.identity.phone_last4,
            benefit_code=BenefitGrantLedger.BENEFIT_PLUS_TRIAL_MONTH,
            contact_email='contact@example.com',
            reason='번호 재할당 가능성을 확인해 주세요.',
            status=ManualBenefitReview.STATUS_REJECTED,
            reviewer=self.admin_user,
            decision_reason='확인 자료를 다시 남겨 주세요.',
            decided_at=timezone.now(),
        )

        for review_status in (
            ManualBenefitReview.STATUS_REJECTED,
            ManualBenefitReview.STATUS_CONSUMED,
        ):
            with self.subTest(status=review_status):
                review.status = review_status
                review.consumed_at = (
                    timezone.now()
                    if review_status == ManualBenefitReview.STATUS_CONSUMED
                    else None
                )
                review.save(update_fields=['status', 'consumed_at'])

                response = self._request(
                    contact_email='different@example.com',
                    reason='다른 사유로 반복 제출',
                )

                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data['id'], review.id)
                self.assertEqual(response.data['status'], review_status)
                self.assertEqual(ManualBenefitReview.objects.count(), 1)

    def test_admin_list_detail_and_decision_are_masked_and_admin_only(self):
        self._ledger()
        created = self._request().data

        denied = self.client.get(
            '/api/v1/admin/billing/benefit-reviews/',
        )
        self.assertEqual(denied.status_code, 403)

        self.client.force_authenticate(self.admin_user)
        listed = self.client.get(
            '/api/v1/admin/billing/benefit-reviews/?status=pending',
        )
        self.assertEqual(listed.status_code, 200, listed.data)
        self.assertEqual(len(listed.data['results']), 1)
        item = listed.data['results'][0]
        self.assertEqual(item['id'], created['id'])
        self.assertEqual(item['phone_masked'], '010-****-5678')
        self.assertEqual(item['contact_email'], 'contact@example.com')
        encoded = str(listed.data)
        self.assertNotIn(self.identity.phone_hmac, encoded)
        self.assertNotIn('01012345678', encoded)
        self.assertNotIn('otp_hash', encoded)

        detail = self.client.get(
            f"/api/v1/admin/billing/benefit-reviews/{created['id']}/",
        )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data, item)

        blank = self.client.post(
            f"/api/v1/admin/billing/benefit-reviews/{created['id']}/decision/",
            {'decision': 'approved', 'reason': '  '},
            format='json',
        )
        self.assertEqual(blank.status_code, 400)

        approved = self.client.post(
            f"/api/v1/admin/billing/benefit-reviews/{created['id']}/decision/",
            {
                'decision': 'approved',
                'reason': '번호 사용 사유를 확인했습니다.',
            },
            format='json',
        )
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertEqual(approved.data['status'], 'approved')
        self.assertEqual(
            approved.data['decision_reason'],
            '번호 사용 사유를 확인했습니다.',
        )

        repeated = self.client.post(
            f"/api/v1/admin/billing/benefit-reviews/{created['id']}/decision/",
            {
                'decision': 'rejected',
                'reason': '결정을 바꿉니다.',
            },
            format='json',
        )
        self.assertEqual(repeated.status_code, 409)
        self.assertEqual(
            repeated.data['code'],
            'benefit_review_already_decided',
        )

    def test_admin_rejection_records_required_reason(self):
        self._ledger()
        created = self._request().data
        self.client.force_authenticate(self.admin_user)

        rejected = self.client.post(
            f"/api/v1/admin/billing/benefit-reviews/{created['id']}/decision/",
            {
                'decision': 'rejected',
                'reason': '확인 자료가 충분하지 않습니다.',
            },
            format='json',
        )

        self.assertEqual(rejected.status_code, 200)
        review = ManualBenefitReview.objects.get(pk=created['id'])
        self.assertEqual(
            review.status,
            ManualBenefitReview.STATUS_REJECTED,
        )
        self.assertEqual(review.reviewer, self.admin_user)
        self.assertIsNotNone(review.decided_at)


class PhoneVerificationDjangoAdminTests(SimpleTestCase):
    def test_sensitive_phone_models_are_registered_read_only_and_masked(self):
        safe_fields = {
            PhoneVerificationChallenge: {
                'id',
                'user',
                'phone_last4',
                'key_version',
                'attempt_count',
                'max_attempts',
                'expires_at',
                'verified_at',
                'consumed_at',
                'created_at',
            },
            VerifiedPhoneIdentity: {
                'id',
                'user',
                'phone_last4',
                'key_version',
                'provider',
                'verified_at',
                'created_at',
                'updated_at',
            },
            BenefitGrantLedger: {
                'id',
                'user',
                'key_version',
                'benefit_code',
                'granted_at',
                'granted_until',
                'created_at',
            },
            ManualBenefitReview: {
                'id',
                'user',
                'phone_last4',
                'key_version',
                'benefit_code',
                'contact_email',
                'reason',
                'status',
                'reviewer',
                'decision_reason',
                'decided_at',
                'consumed_at',
                'created_at',
            },
            BenefitGrantException: {
                'id',
                'original_ledger',
                'review',
                'user',
                'key_version',
                'benefit_code',
                'granted_at',
                'granted_until',
                'created_at',
            },
        }
        for model, expected_fields in safe_fields.items():
            with self.subTest(model=model.__name__):
                self.assertIn(model, admin.site._registry)
                model_admin = admin.site._registry[model]
                self.assertEqual(
                    set(model_admin.fields),
                    expected_fields,
                )
                self.assertFalse(
                    model_admin.has_add_permission(None),
                )
                self.assertFalse(
                    model_admin.has_change_permission(None),
                )
                self.assertFalse(
                    model_admin.has_delete_permission(None),
                )
                exposed = str({
                    'fields': model_admin.fields,
                    'list_display': model_admin.list_display,
                    'search_fields': model_admin.search_fields,
                })
                for forbidden in (
                    'phone_hmac',
                    'identity_hmac',
                    'otp_hash',
                    'provider_transaction_ref',
                    'coupon_snapshot',
                ):
                    self.assertNotIn(forbidden, exposed)


POSTGRES_ONLY = unittest.skipUnless(
    connection.vendor == 'postgresql',
    'PostgreSQL row-lock test',
)


def _threaded_call(callback):
    close_old_connections()
    try:
        return callback()
    finally:
        close_old_connections()


@POSTGRES_ONLY
@override_settings(
    FREE_TRIAL_PHONE_VERIFICATION_ENABLED=True,
    PHONE_IDENTITY_HMAC_KEY=TEST_PHONE_IDENTITY_SECRET,
    PHONE_IDENTITY_HMAC_KEY_VERSION='test-v1',
)
class PhoneBenefitPostgresConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        Plan.objects.create(
            code='free',
            display_name='무료',
            price_krw=0,
        )
        self.plus = Plan.objects.create(
            code='plus',
            display_name='Plus',
            price_krw=19900,
        )
        self.coupon = Coupon.objects.create(
            code='PHONE-CONCURRENT',
            plan=self.plus,
            coupon_kind='recurring_trial',
            duration_months=1,
            redeem_by=timezone.now() + timedelta(days=30),
            max_redemptions=10,
        )
        identity = build_phone_identity('01012345678')
        self.users = []
        self.claims = []
        self.agreements = []
        for index in range(2):
            user = User.objects.create_user(
                email=f'phone-concurrent-{index}@example.com',
                password='test-password',
            )
            VerifiedPhoneIdentity.objects.create(
                user=user,
                phone_hmac=identity.digest,
                key_version=identity.key_version,
                phone_last4=identity.last4,
                provider='solapi_sms',
                verified_at=timezone.now(),
                provider_transaction_ref=f'provider-{index}',
            )
            claim = hold_recurring_coupon(user, self.coupon.code)
            agreement = BillingAgreement.objects.create(
                user=user,
                plan=self.plus,
                status='trialing',
                billing_anchor_day=5,
                trial_duration_months=1,
                current_period_starts_on=date(2027, 1, 5),
                current_period_ends_on=date(2027, 2, 4),
                next_charge_date=date(2027, 2, 5),
            )
            PaymentMethodToken.objects.create(
                agreement=agreement,
                encrypted_token=f'ciphertext-{index}',
                key_version='v1',
                card_brand='신한',
                card_last4=f'123{index}',
                status='active',
            )
            RecurringPaymentConsent.objects.create(
                agreement=agreement,
                kind='trial_start',
                consent_version='v1',
                plan_code='plus',
                amount_krw=21890,
                charge_date=date(2027, 2, 5),
                card_label=f'신한 끝 123{index}',
                cancel_effect=date(2027, 2, 4),
                display_snapshot_hash=str(index) * 64,
                accepted_at=timezone.now(),
            )
            self.users.append(user)
            self.claims.append(claim)
            self.agreements.append(agreement)

    def test_two_users_with_same_identity_receive_one_ordinary_grant(self):
        barrier = threading.Barrier(2)

        def redeem(index):
            barrier.wait(timeout=5)
            try:
                redeem_held_coupon(
                    self.claims[index].pk,
                    self.agreements[index].pk,
                )
                return 'success'
            except CouponError as exc:
                return exc.code

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(
                _threaded_call,
                (
                    lambda: redeem(0),
                    lambda: redeem(1),
                ),
            ))

        self.assertCountEqual(
            results,
            ['success', 'manual_benefit_review_required'],
        )
        self.assertEqual(BenefitGrantLedger.objects.count(), 1)
        self.assertEqual(BenefitGrantException.objects.count(), 0)
        self.assertEqual(CouponRedemption.objects.count(), 1)
        self.assertEqual(
            CouponClaim.objects.filter(status='redeemed').count(),
            1,
        )
        self.assertEqual(
            Subscription.objects.filter(
                plan=self.plus,
                status='trial',
            ).count(),
            1,
        )
