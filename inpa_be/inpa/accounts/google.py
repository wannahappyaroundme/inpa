"""구글 OAuth 공용 — 게이트 헬퍼 + ID 토큰 검증.

google 라이브러리는 함수 내부에서 lazy import(미설치/미설정 시 Django 부팅 무해).
"""
from django.conf import settings

_GOOGLE_ISSUERS = {'accounts.google.com', 'https://accounts.google.com'}


def google_login_enabled():
    """소셜 로그인 활성 = 마스터 스위치 + 클라이언트 ID."""
    return bool(settings.GOOGLE_OAUTH_ENABLED and settings.GOOGLE_OAUTH_CLIENT_ID)


def google_calendar_enabled():
    """캘린더 활성 = 로그인 + 시크릿 + redirect URI(코드 플로우 필요)."""
    return bool(
        google_login_enabled()
        and settings.GOOGLE_OAUTH_CLIENT_SECRET
        and settings.GOOGLE_OAUTH_REDIRECT_URI
    )


class GoogleTokenError(Exception):
    """ID 토큰 검증 실패(서명/만료/audience/issuer/email_verified)."""


def verify_google_id_token(id_token_str):
    """구글 ID 토큰 검증 → 클레임 dict. 실패 시 GoogleTokenError(사유는 내부용)."""
    from google.oauth2 import id_token as google_id_token
    from google.auth.transport import requests as google_requests

    try:
        # 라이브러리가 서명·audience(client_id)·만료를 검증.
        claims = google_id_token.verify_oauth2_token(
            id_token_str, google_requests.Request(), settings.GOOGLE_OAUTH_CLIENT_ID)
    except Exception as exc:  # ValueError 등 모두 토큰 오류로 수렴
        raise GoogleTokenError(f'verify failed: {exc}')

    if claims.get('iss') not in _GOOGLE_ISSUERS:
        raise GoogleTokenError('bad issuer')
    if not claims.get('email'):
        raise GoogleTokenError('no email')
    if not claims.get('email_verified'):
        raise GoogleTokenError('email not verified')
    return claims
