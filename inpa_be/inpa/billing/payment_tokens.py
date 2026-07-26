"""KICC 빌키의 애플리케이션 레벨 암호화."""

from dataclasses import dataclass

from cryptography.fernet import Fernet
from django.conf import settings


class PaymentConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class EncryptedToken:
    ciphertext: str
    key_version: str


def _fernet():
    raw_key = getattr(settings, 'PAYMENT_TOKEN_ENCRYPTION_KEY', '')
    if not raw_key:
        raise PaymentConfigurationError('PAYMENT_TOKEN_KEY_MISSING')
    try:
        return Fernet(raw_key.encode())
    except (TypeError, ValueError) as exc:
        raise PaymentConfigurationError(
            'PAYMENT_TOKEN_KEY_INVALID') from exc


def encrypt_billing_token(raw: str) -> EncryptedToken:
    if not raw:
        raise PaymentConfigurationError('PAYMENT_TOKEN_EMPTY')
    return EncryptedToken(
        ciphertext=_fernet().encrypt(raw.encode()).decode(),
        key_version=getattr(settings, 'PAYMENT_TOKEN_KEY_VERSION', 'v1'),
    )


def _assert_current_version(key_version):
    if key_version != getattr(
            settings, 'PAYMENT_TOKEN_KEY_VERSION', 'v1'):
        raise PaymentConfigurationError(
            'PAYMENT_TOKEN_KEY_VERSION_UNKNOWN')


def decrypt_billing_token_object(token) -> str:
    _assert_current_version(token.key_version)
    return _fernet().decrypt(token.ciphertext.encode()).decode()


def decrypt_billing_token(token) -> str:
    _assert_current_version(token.key_version)
    return _fernet().decrypt(token.encrypted_token.encode()).decode()
