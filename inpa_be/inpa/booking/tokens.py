"""미팅 예약 토큰 — stateless 서명 (customers/tokens.py와 동일 패턴).

설계사가 고객별 예약 링크를 만들면 customer.pk를 서명한 토큰을 발급한다.
고객이 /b/<token> 으로 열어 슬롯을 직접 고른다.
"""
from django.conf import settings
from django.core import signing

BOOKING_SALT = 'inpa-booking-request'


def make_booking_token(customer):
    return signing.dumps(customer.pk, salt=BOOKING_SALT)


def read_booking_token(token):
    """유효하면 customer pk 반환, 만료/위조면 signing 예외(SignatureExpired/BadSignature)."""
    max_age = settings.BOOKING_TOKEN_TTL_HOURS * 3600
    return signing.loads(token, salt=BOOKING_SALT, max_age=max_age)
