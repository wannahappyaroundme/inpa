"""운영 설정 — MariaDB(매니지드), 보안 헤더. Render/Railway 환경변수 주입."""
from .base import *  # noqa: F401,F403

DEBUG = False

# DATABASE_URL=mysql://user:pass@host:3306/inpa (django-environ 파싱)
DATABASES = {
    'default': env.db('DATABASE_URL'),  # noqa: F405
}

# 보안 헤더
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
