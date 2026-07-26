from types import SimpleNamespace

from cryptography.fernet import Fernet, InvalidToken
from django.test import SimpleTestCase, override_settings

from .payment_tokens import (
    PaymentConfigurationError,
    decrypt_billing_token,
    decrypt_billing_token_object,
    encrypt_billing_token,
)


@override_settings(
    PAYMENT_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    PAYMENT_TOKEN_KEY_VERSION='v1',
)
class PaymentTokenTests(SimpleTestCase):
    def test_encrypted_token_does_not_contain_plain_billing_key(self):
        encrypted = encrypt_billing_token('secret-billing-key')
        self.assertNotIn('secret-billing-key', encrypted.ciphertext)
        self.assertEqual(
            decrypt_billing_token_object(encrypted),
            'secret-billing-key',
        )

    def test_model_shaped_token_can_be_decrypted(self):
        encrypted = encrypt_billing_token('billing-key')
        token = SimpleNamespace(
            encrypted_token=encrypted.ciphertext,
            key_version='v1',
        )
        self.assertEqual(decrypt_billing_token(token), 'billing-key')

    def test_unknown_key_version_fails_closed(self):
        encrypted = encrypt_billing_token('billing-key')
        token = SimpleNamespace(
            encrypted_token=encrypted.ciphertext,
            key_version='retired-key',
        )
        with self.assertRaisesMessage(
                PaymentConfigurationError, 'PAYMENT_TOKEN_KEY_VERSION_UNKNOWN'):
            decrypt_billing_token(token)

    @override_settings(PAYMENT_TOKEN_ENCRYPTION_KEY='')
    def test_missing_key_fails_before_encrypting(self):
        with self.assertRaisesMessage(
                PaymentConfigurationError, 'PAYMENT_TOKEN_KEY_MISSING'):
            encrypt_billing_token('billing-key')

    def test_tampered_ciphertext_is_rejected(self):
        encrypted = encrypt_billing_token('billing-key')
        tampered = SimpleNamespace(
            ciphertext=encrypted.ciphertext[:-1] + 'x',
            key_version='v1',
        )
        with self.assertRaises(InvalidToken):
            decrypt_billing_token_object(tampered)
