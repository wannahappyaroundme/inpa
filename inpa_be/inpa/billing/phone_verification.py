"""무료 1개월 혜택용 휴대전화 식별과 SMS 인증.

원문 번호는 함수 호출 동안에만 존재하며 DB, 캐시 키, 로그에 남기지 않는다.
"""

from dataclasses import dataclass
import hashlib
import hmac
import re
import secrets
import threading
import time
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone

from .models import (
    BenefitGrantLedger,
    ManualBenefitReview,
    PhoneVerificationChallenge,
    VerifiedPhoneIdentity,
)
from .sms import SolapiSmsClient


OTP_TTL_SECONDS = 300
OTP_MAX_ATTEMPTS = 5
_ALLOWED_PHONE_INPUT = re.compile(r'^[0-9+().\s-]+$')
_KEY_VERSION = re.compile(r'^[A-Za-z0-9_.-]{1,20}$')
_RATE_NAMESPACE = 'free-trial-phone-v1'
_RATE_LOCK_TTL_SECONDS = 5
_RATE_LOCK_WAIT_SECONDS = 2
_RATE_LOCK_RELEASE_WAIT_SECONDS = 0.5
_RATE_LOCK_RETRY_MIN_SECONDS = 0.002
_RATE_LOCK_RETRY_JITTER_MS = 5
_RATE_LOCAL_LOCK_STRIPES = tuple(
    threading.Lock()
    for _index in range(128)
)
# SQLite 기반 DatabaseCache는 서로 다른 키도 하나의 DB 쓰기 잠금을
# 다툰다. 버킷별 stripe 뒤에서 캐시 임계 구간만 짧게 직렬화해,
# 같은 프로세스의 정상 요청을 백엔드 장애로 오인하지 않게 한다.
_RATE_LOCAL_CACHE_GATE = threading.Lock()


class PhoneVerificationError(ValueError):
    def __init__(
        self,
        code,
        detail,
        *,
        attempts_remaining=None,
    ):
        self.code = code
        self.detail = detail
        self.attempts_remaining = attempts_remaining
        super().__init__(detail)


class _RateLimitBackendUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class PhoneIdentity:
    digest: str
    key_version: str
    last4: str


def normalize_kr_mobile(raw_phone):
    """지원하는 대한민국 010 번호만 11자리 숫자로 정규화한다."""

    value = str(raw_phone or '').strip()
    if not value or not _ALLOWED_PHONE_INPUT.fullmatch(value):
        raise PhoneVerificationError(
            'invalid_phone',
            '휴대전화 번호를 다시 확인해 주세요.',
        )
    compact = re.sub(r'[().\s-]', '', value)
    if compact.startswith('+82'):
        local = compact[3:]
        if local.startswith('0'):
            local = local[1:]
        compact = f'0{local}'
    elif '+' in compact or compact.startswith('82'):
        raise PhoneVerificationError(
            'invalid_phone',
            '휴대전화 번호를 다시 확인해 주세요.',
        )
    if (
        not compact.isdigit()
        or len(compact) != 11
        or not compact.startswith('010')
    ):
        raise PhoneVerificationError(
            'invalid_phone',
            '휴대전화 번호를 다시 확인해 주세요.',
        )
    return compact


def mask_kr_mobile(canonical_phone):
    canonical = normalize_kr_mobile(canonical_phone)
    return f'{canonical[:3]}-****-{canonical[-4:]}'


def build_phone_identity(
    canonical_phone,
    *,
    key=None,
    key_version=None,
):
    canonical = normalize_kr_mobile(canonical_phone)
    secret = (
        getattr(settings, 'PHONE_IDENTITY_HMAC_KEY', '')
        if key is None else str(key)
    )
    version = (
        getattr(settings, 'PHONE_IDENTITY_HMAC_KEY_VERSION', 'v1')
        if key_version is None else str(key_version)
    )
    if (
        not secret
        or len(secret.encode('utf-8'))
        < settings.PHONE_IDENTITY_HMAC_KEY_MIN_BYTES
        or not _KEY_VERSION.fullmatch(version)
    ):
        raise PhoneVerificationError(
            'phone_verification_setup_required',
            '휴대전화 인증 설정을 확인하고 있어요. 잠시 뒤 다시 시도해 주세요.',
        )

    # 키 버전을 도메인 분리에 포함한다. 같은 버전은 안정적으로 비교되고,
    # 새 버전은 이전 식별값과 우연히 같은 값으로 취급되지 않는다.
    domain_key = hmac.new(
        secret.encode('utf-8'),
        f'inpa.free-trial.phone:{version}'.encode('utf-8'),
        hashlib.sha256,
    ).digest()
    digest = hmac.new(
        domain_key,
        canonical.encode('ascii'),
        hashlib.sha256,
    ).hexdigest()
    return PhoneIdentity(
        digest=digest,
        key_version=version,
        last4=canonical[-4:],
    )


def generate_otp():
    return f'{secrets.randbelow(1_000_000):06d}'


def _rate_cache_key(namespace, value):
    secret = (
        getattr(settings, 'PHONE_IDENTITY_HMAC_KEY', '')
        or settings.SECRET_KEY
    )
    digest = hmac.new(
        str(secret).encode('utf-8'),
        (
            f'inpa.free-trial.rate:{namespace}:'
            f'{value}'
        ).encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()
    return f'{_RATE_NAMESPACE}:{namespace}:{digest}'


def _rate_local_lock(prefix):
    return _RATE_LOCAL_LOCK_STRIPES[
        int(prefix[-8:], 16) % len(_RATE_LOCAL_LOCK_STRIPES)
    ]


def _acquire_rate_bucket_lock(lock_key, *, deadline):
    token = secrets.token_hex(16)
    while True:
        try:
            acquired = cache.add(
                lock_key,
                token,
                timeout=_RATE_LOCK_TTL_SECONDS,
            )
        except DatabaseError:
            acquired = False
        if acquired:
            return token

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _RateLimitBackendUnavailable
        jitter = (
            secrets.randbelow(_RATE_LOCK_RETRY_JITTER_MS + 1)
            / 1000
        )
        time.sleep(min(
            _RATE_LOCK_RETRY_MIN_SECONDS + jitter,
            remaining,
        ))


def _release_rate_bucket_lock(lock_key, token):
    deadline = time.monotonic() + _RATE_LOCK_RELEASE_WAIT_SECONDS
    while True:
        try:
            if cache.get(lock_key) != token:
                return False
            if cache.delete(lock_key):
                return True
        except DatabaseError:
            pass

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        jitter = (
            secrets.randbelow(_RATE_LOCK_RETRY_JITTER_MS + 1)
            / 1000
        )
        time.sleep(min(
            _RATE_LOCK_RETRY_MIN_SECONDS + jitter,
            remaining,
        ))


def _rate_limit_backend_error():
    return PhoneVerificationError(
        'phone_rate_limit_unavailable',
        '인증번호 발송을 다시 준비하고 있어요. 잠시 뒤 시도해 주세요.',
    )


def _increment_rate_limit(namespace, value, *, limit, timeout):
    prefix = _rate_cache_key(namespace, value)
    lock_key = f'{prefix}:lock'
    slot_keys = [
        f'{prefix}:slot:{slot}'
        for slot in range(limit)
    ]
    deadline = time.monotonic() + _RATE_LOCK_WAIT_SECONDS
    local_lock = _rate_local_lock(prefix)
    remaining = deadline - time.monotonic()
    if remaining <= 0 or not local_lock.acquire(timeout=remaining):
        raise _rate_limit_backend_error()
    remaining = deadline - time.monotonic()
    if (
        remaining <= 0
        or not _RATE_LOCAL_CACHE_GATE.acquire(timeout=remaining)
    ):
        local_lock.release()
        raise _rate_limit_backend_error()
    try:
        try:
            lock_token = _acquire_rate_bucket_lock(
                lock_key,
                deadline=deadline,
            )
        except _RateLimitBackendUnavailable as exc:
            raise _rate_limit_backend_error() from exc
        try:
            try:
                occupied = cache.get_many(slot_keys)
            except DatabaseError as exc:
                raise _rate_limit_backend_error() from exc
            if len(occupied) >= limit:
                raise PhoneVerificationError(
                    'phone_request_limited',
                    '요청이 많아요. 잠시 뒤 다시 시도해 주세요.',
                )

            for slot_key in slot_keys:
                if slot_key in occupied:
                    continue
                try:
                    if cache.add(slot_key, 1, timeout=timeout):
                        return
                except DatabaseError as exc:
                    raise _rate_limit_backend_error() from exc

            # mutex를 가진 동안 비어 있던 슬롯을 얻지 못했다면
            # DatabaseCache가 내부 DB 오류를 False로 삼킨 경로다.
            raise _rate_limit_backend_error()
        finally:
            _release_rate_bucket_lock(lock_key, lock_token)
    finally:
        _RATE_LOCAL_CACHE_GATE.release()
        local_lock.release()


def enforce_phone_request_limits(
    *,
    user_id,
    phone_hmac,
    ip_address,
):
    """공급자 호출 전에 계정·번호·IP·재발송 제한을 모두 차감한다.

    앞 버킷을 얻은 뒤 뒤 버킷에서 거절되면 앞 슬롯은 TTL까지 남는다.
    발송 상한을 느슨하게 만들지 않는 의도적인 보수 집계다.
    """

    user_key = str(user_id)
    ip_key = str(ip_address or 'unknown')
    _increment_rate_limit(
        'user-10m',
        user_key,
        limit=5,
        timeout=600,
    )
    _increment_rate_limit(
        'user-day',
        user_key,
        limit=10,
        timeout=86400,
    )
    _increment_rate_limit(
        'phone-10m',
        phone_hmac,
        limit=3,
        timeout=600,
    )
    _increment_rate_limit(
        'ip-10m',
        ip_key,
        limit=10,
        timeout=600,
    )
    try:
        _increment_rate_limit(
            'cooldown',
            f'{user_key}:{phone_hmac}',
            limit=1,
            timeout=60,
        )
    except PhoneVerificationError as exc:
        if exc.code == 'phone_rate_limit_unavailable':
            raise
        raise PhoneVerificationError(
            'phone_request_cooldown',
            '잠시 뒤 인증번호를 다시 받을 수 있어요.',
        ) from exc


def request_phone_verification(
    *,
    user,
    raw_phone,
    ip_address,
    sms_client=None,
):
    if not getattr(
        settings,
        'FREE_TRIAL_PHONE_VERIFICATION_ENABLED',
        False,
    ):
        raise PhoneVerificationError(
            'phone_verification_setup_required',
            '휴대전화 인증 설정을 확인하고 있어요. 잠시 뒤 다시 시도해 주세요.',
        )
    canonical = normalize_kr_mobile(raw_phone)
    identity = build_phone_identity(canonical)
    enforce_phone_request_limits(
        user_id=user.pk,
        phone_hmac=identity.digest,
        ip_address=ip_address,
    )
    raw_code = generate_otp()
    sender = sms_client or SolapiSmsClient()
    result = sender.send_verification_sms(canonical, raw_code)
    challenge, _ = create_otp_challenge(
        user=user,
        canonical_phone=canonical,
        provider_transaction_ref=result.provider_transaction_id,
        code=raw_code,
    )
    return challenge


def create_manual_benefit_review(
    *,
    user,
    contact_email,
    reason,
):
    if not getattr(
        settings,
        'FREE_TRIAL_PHONE_VERIFICATION_ENABLED',
        False,
    ):
        raise PhoneVerificationError(
            'phone_verification_setup_required',
            '휴대전화 인증 설정을 확인하고 있어요. 잠시 뒤 다시 시도해 주세요.',
        )
    current_key_version = getattr(
        settings,
        'PHONE_IDENTITY_HMAC_KEY_VERSION',
        'v1',
    )
    benefit_code = BenefitGrantLedger.BENEFIT_PLUS_TRIAL_MONTH
    if BenefitGrantLedger.objects.filter(
        benefit_code=benefit_code,
    ).exclude(key_version=current_key_version).exists():
        raise PhoneVerificationError(
            'phone_identity_key_rotation_required',
            '휴대전화 인증 기준을 확인하고 있어요. 잠시 뒤 다시 시도해 주세요.',
        )
    identity = VerifiedPhoneIdentity.objects.filter(user=user).first()
    if (
        identity is None
        or identity.key_version != current_key_version
    ):
        raise PhoneVerificationError(
            'phone_verification_required',
            '휴대전화 인증을 마치면 확인 요청을 남길 수 있어요.',
        )
    if not BenefitGrantLedger.objects.filter(
        identity_hmac=identity.phone_hmac,
        benefit_code=benefit_code,
    ).exists():
        raise PhoneVerificationError(
            'manual_benefit_review_not_required',
            '현재 인증 번호로 무료 이용을 시작할 수 있어요.',
        )
    with transaction.atomic():
        existing = (
            ManualBenefitReview.objects.select_for_update()
            .filter(
                user=user,
                identity_hmac=identity.phone_hmac,
                key_version=identity.key_version,
                benefit_code=benefit_code,
            )
            .order_by('-created_at', '-pk')
            .first()
        )
        if existing is not None:
            return existing, False
        try:
            with transaction.atomic():
                review = ManualBenefitReview.objects.create(
                    user=user,
                    identity_hmac=identity.phone_hmac,
                    key_version=identity.key_version,
                    phone_last4=identity.phone_last4,
                    benefit_code=benefit_code,
                    contact_email=contact_email,
                    reason=reason,
                )
        except IntegrityError:
            review = ManualBenefitReview.objects.get(
                user=user,
                identity_hmac=identity.phone_hmac,
                benefit_code=benefit_code,
            )
            return review, False
        return review, True


def create_otp_challenge(
    *,
    user,
    canonical_phone,
    provider_transaction_ref='',
    code=None,
    now=None,
):
    """공급자 발송 성공 뒤에만 호출한다."""

    now = now or timezone.now()
    identity = build_phone_identity(canonical_phone)
    raw_code = code or generate_otp()
    if not re.fullmatch(r'\d{6}', raw_code):
        raise ValueError('OTP must contain six digits')
    challenge = PhoneVerificationChallenge.objects.create(
        user=user,
        phone_hmac=identity.digest,
        key_version=identity.key_version,
        phone_last4=identity.last4,
        otp_hash=make_password(raw_code),
        max_attempts=OTP_MAX_ATTEMPTS,
        expires_at=now + timedelta(seconds=OTP_TTL_SECONDS),
        provider_transaction_ref=str(provider_transaction_ref or '')[:120],
    )
    return challenge, raw_code


def _verification_failed(*, attempts_remaining=0):
    return PhoneVerificationError(
        'phone_verification_failed',
        '인증번호를 다시 확인해 주세요.',
        attempts_remaining=max(int(attempts_remaining), 0),
    )


def verify_otp_challenge(
    *,
    user,
    challenge_id,
    canonical_phone,
    code,
    now=None,
):
    now = now or timezone.now()
    identity = build_phone_identity(canonical_phone)
    failed_attempts_remaining = None
    with transaction.atomic():
        challenge = (
            PhoneVerificationChallenge.objects.select_for_update()
            .filter(pk=challenge_id, user=user)
            .first()
        )
        if challenge is None:
            raise _verification_failed()
        remaining = max(
            challenge.max_attempts - challenge.attempt_count,
            0,
        )
        if (
            challenge.expires_at <= now
            or challenge.verified_at is not None
            or challenge.consumed_at is not None
            or remaining == 0
        ):
            raise _verification_failed()

        matches_phone = (
            challenge.key_version == identity.key_version
            and hmac.compare_digest(
                challenge.phone_hmac,
                identity.digest,
            )
        )
        matches_code = check_password(str(code or ''), challenge.otp_hash)
        if not (matches_phone and matches_code):
            challenge.attempt_count += 1
            challenge.save(update_fields=['attempt_count'])
            failed_attempts_remaining = (
                challenge.max_attempts - challenge.attempt_count
            )
        else:
            challenge.verified_at = now
            challenge.consumed_at = now
            challenge.save(update_fields=['verified_at', 'consumed_at'])
            verified, _ = VerifiedPhoneIdentity.objects.update_or_create(
                user=user,
                defaults={
                    'phone_hmac': challenge.phone_hmac,
                    'key_version': challenge.key_version,
                    'phone_last4': challenge.phone_last4,
                    'provider': 'solapi_sms',
                    'verified_at': now,
                    'provider_transaction_ref':
                        challenge.provider_transaction_ref,
                },
            )
    if failed_attempts_remaining is not None:
        raise _verification_failed(
            attempts_remaining=failed_attempts_remaining,
        )
    return verified
