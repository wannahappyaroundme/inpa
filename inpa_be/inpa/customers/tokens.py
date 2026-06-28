"""고객 동의 요청 토큰 — 별도 DB 테이블 없는 stateless 서명 방식 (P3c).

설계사가 '동의 요청 링크'를 만들면 customer.pk + 요청 동의 scope를 서명한 토큰을 발급한다.
고객이 본인 기기에서 /c/<token> 로 열어 해당 동의를 직접 한다.
accounts/tokens.py(이메일 인증) 패턴 — TimestampSigner(max_age).
★ 하위호환: 구 토큰(서명된 int pk)은 국외이전(overseas_medical) 단일 동의로 해석.
"""
from django.conf import settings
from django.core import signing

from .models import ConsentLog

CONSENT_SALT = 'inpa-consent-request'


def make_consent_token(customer, scopes=None):
    """customer.pk + 요청 scope 목록을 서명한 동의요청 토큰 발급.
    scopes 미지정 시 국외이전 단일(기존 OCR 동선 호환)."""
    payload = {'pk': customer.pk,
               'scopes': scopes or [ConsentLog.SCOPE_OVERSEAS_MEDICAL]}
    return signing.dumps(payload, salt=CONSENT_SALT)


def read_consent_token(token):
    """유효하면 {'pk': int, 'scopes': [str]} 반환. 만료/위조면 signing 예외.
    구 토큰(int pk)은 국외이전 단일로 정규화."""
    max_age = settings.CONSENT_TOKEN_TTL_HOURS * 3600
    data = signing.loads(token, salt=CONSENT_SALT, max_age=max_age)
    if isinstance(data, int):
        return {'pk': data, 'scopes': [ConsentLog.SCOPE_OVERSEAS_MEDICAL]}
    return data
