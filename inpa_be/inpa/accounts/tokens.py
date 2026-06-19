"""인증 토큰 — 별도 DB 테이블 없는 stateless 방식 (dev/02 §2.3 정본).

- 이메일 인증: TimestampSigner (max_age=24h). 인증은 멱등.
- 비밀번호 재설정: Django default_token_generator + uidb64 (1회용 자동보장, TTL=PASSWORD_RESET_TIMEOUT=1h).
"""
from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core import signing
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

EMAIL_VERIFY_SALT = 'inpa-email-verify'


# ── 이메일 인증 ──────────────────────────────────────────────────
def make_email_verify_token(user):
    return signing.dumps(user.pk, salt=EMAIL_VERIFY_SALT)


def read_email_verify_token(token):
    """유효하면 user pk 반환, 만료/위조면 signing 예외(BadSignature/SignatureExpired)."""
    max_age = settings.EMAIL_VERIFY_TOKEN_TTL_HOURS * 3600
    return signing.loads(token, salt=EMAIL_VERIFY_SALT, max_age=max_age)


# ── 비밀번호 재설정 ──────────────────────────────────────────────
def make_password_reset_pair(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return uid, token


def get_user_from_uid(UserModel, uidb64):
    try:
        pk = force_str(urlsafe_base64_decode(uidb64))
        return UserModel.objects.get(pk=pk)
    except (TypeError, ValueError, OverflowError, UserModel.DoesNotExist):
        return None


def check_password_reset_token(user, token):
    return default_token_generator.check_token(user, token)
