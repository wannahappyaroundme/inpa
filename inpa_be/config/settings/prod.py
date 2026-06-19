"""운영 설정 — MariaDB(매니지드), 보안 헤더, whitenoise 정적서빙.

Railway(BE+MySQL/MariaDB) 환경변수 주입을 전제로 한다.
모든 호스트/오리진/시크릿은 코드에 하드코딩하지 않고 env에서 읽는다.
base.py / local.py 는 건드리지 않는다(로컬 테스트 보호) — whitenoise 미들웨어는 이 파일에만 추가.
"""
from .base import *  # noqa: F401,F403

DEBUG = False

# ── 호스트 / 오리진 (전부 env 주입) ───────────────────────────────
# Railway 도메인·커스텀 도메인을 콤마로 구분해 ALLOWED_HOSTS 에 넣는다.
# 예: ALLOWED_HOSTS=inpa-be.up.railway.app,api.inpa.kr
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=[])  # noqa: F405

# CSRF (Django admin·세션쿠키 사용 시 필수). https 스킴 포함 전체 URL.
# 예: CSRF_TRUSTED_ORIGINS=https://inpa.kr,https://inpa-be.up.railway.app
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[])  # noqa: F405

# CORS (Vercel FE → Railway BE). https 스킴 포함 전체 URL.
# 예: CORS_ALLOWED_ORIGINS=https://inpa.vercel.app,https://inpa.kr
CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=[])  # noqa: F405
CORS_ALLOW_CREDENTIALS = True

# ── DB ───────────────────────────────────────────────────────────
# DATABASE_URL=mysql://user:pass@host:3306/db (Railway MySQL 플러그인 주입, django-environ 파싱)
DATABASES = {
    'default': env.db('DATABASE_URL'),  # noqa: F405
}

# ── 정적파일 (whitenoise — prod 전용) ─────────────────────────────
# collectstatic 산출물을 gunicorn 단독으로 압축·캐시 서빙.
STATIC_ROOT = BASE_DIR / 'staticfiles'  # noqa: F405
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}
# SecurityMiddleware 바로 뒤에 whitenoise 삽입 (base.MIDDLEWARE 복사본 수정 — base 원본 불변).
MIDDLEWARE = list(MIDDLEWARE)  # noqa: F405
_security_idx = MIDDLEWARE.index('django.middleware.security.SecurityMiddleware')
MIDDLEWARE.insert(_security_idx + 1, 'whitenoise.middleware.WhiteNoiseMiddleware')

# ── 보안 헤더 ─────────────────────────────────────────────────────
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
