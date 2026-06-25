"""운영 설정 — PostgreSQL(Neon 매니지드), 보안 헤더, whitenoise 정적서빙.

Render(BE) + Neon(PostgreSQL) 환경변수 주입을 전제로 한다.
모든 호스트/오리진/시크릿은 코드에 하드코딩하지 않고 env에서 읽는다.
base.py / local.py 는 건드리지 않는다(로컬 테스트 보호) — whitenoise 미들웨어는 이 파일에만 추가.
"""
from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403

DEBUG = False

# ── 안전판: 운영에서 데모 SECRET_KEY 로 토큰 서명되는 사고 차단 (fail-loud) ──
# Render 환경변수에 SECRET_KEY 미설정 시 base 의 데모 default 가 들어오는데,
# 그 상태로 gunicorn 이 뜨면 토큰 위조가 가능해진다. 빌드(collectstatic)는 더미키를 주입하므로 통과.
if SECRET_KEY == 'dev-insecure-change-me':  # noqa: F405
    raise ImproperlyConfigured(
        'SECRET_KEY 가 설정되지 않았습니다. Render 환경변수에 SECRET_KEY 를 넣어주세요. '
        "(생성: python3 -c \"import secrets; print(secrets.token_urlsafe(64))\")"
    )

# ── 호스트 / 오리진 (전부 env 주입) ───────────────────────────────
# Render 도메인·커스텀 도메인을 콤마로 구분해 ALLOWED_HOSTS 에 넣는다.
# (Render 도메인은 RENDER_EXTERNAL_HOSTNAME 으로 자동 추가됨 — 아래 참조)
# 예: ALLOWED_HOSTS=inpa-be.onrender.com,api.inpa.kr
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=[])  # noqa: F405

# CSRF (Django admin·세션쿠키 사용 시 필수). https 스킴 포함 전체 URL.
# 예: CSRF_TRUSTED_ORIGINS=https://inpa.kr,https://inpa-be.onrender.com
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[])  # noqa: F405

# CORS (Vercel FE → Render BE). https 스킴 포함 전체 URL.
# 예: CORS_ALLOWED_ORIGINS=https://inpa.vercel.app,https://inpa.kr
CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=[])  # noqa: F405
CORS_ALLOW_CREDENTIALS = True

# Render 무료 티어: 플랫폼이 주입하는 외부 도메인을 ALLOWED_HOSTS/CSRF에 자동 포함
# (사용자가 도메인을 수기 입력하지 않아도 502/400 안 나게). 커스텀 도메인은 env로 추가.
_render_host = env('RENDER_EXTERNAL_HOSTNAME', default='')  # noqa: F405
if _render_host:
    ALLOWED_HOSTS = list(ALLOWED_HOSTS) + [_render_host]
    CSRF_TRUSTED_ORIGINS = list(CSRF_TRUSTED_ORIGINS) + [f'https://{_render_host}']

# ── DB ───────────────────────────────────────────────────────────
# DATABASE_URL=postgres://user:pass@host:5432/db (Neon PostgreSQL, django-environ 파싱)
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

# ── 에러 관측 (Sentry) — SENTRY_DSN 있을 때만 활성. 없으면 조용히 패스. ──
_SENTRY_DSN = env('SENTRY_DSN', default='')  # noqa: F405
if _SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    sentry_sdk.init(
        dsn=_SENTRY_DSN,
        integrations=[DjangoIntegration()],
        traces_sample_rate=0.1,
        send_default_pii=False,  # 개인정보 비전송(컴플라이언스)
        environment='production',
    )
