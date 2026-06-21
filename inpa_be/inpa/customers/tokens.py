"""고객 동의 요청 토큰 — 별도 DB 테이블 없는 stateless 서명 방식 (P3c).

설계사가 '동의 요청 링크'를 만들면 customer.pk를 서명한 토큰을 발급한다.
고객이 본인 기기에서 /c/<token> 로 열어 국외이전 동의를 직접 한다.
accounts/tokens.py(이메일 인증) 패턴 그대로 — TimestampSigner(max_age).
"""
from django.conf import settings
from django.core import signing

CONSENT_SALT = 'inpa-consent-request'


def make_consent_token(customer):
    """customer.pk 를 서명한 동의요청 토큰 발급."""
    return signing.dumps(customer.pk, salt=CONSENT_SALT)


def read_consent_token(token):
    """유효하면 customer pk 반환, 만료/위조면 signing 예외(SignatureExpired/BadSignature)."""
    max_age = settings.CONSENT_TOKEN_TTL_HOURS * 3600
    return signing.loads(token, salt=CONSENT_SALT, max_age=max_age)
