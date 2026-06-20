"""인파 백엔드 공통 설정. 환경별 분리: local(SQLite) / prod(MariaDB)."""
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR / '.env')

SECRET_KEY = env('SECRET_KEY', default='dev-insecure-change-me')
DEBUG = env('DEBUG')
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['*'])

# ── 앱 ───────────────────────────────────────────────────────────
DJANGO_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]
THIRD_PARTY_APPS = [
    'rest_framework',
    'rest_framework.authtoken',
    'corsheaders',
]
# inpa.* = foliio의 weapon 네임스페이스를 인파로 리네임한 앱 패키지
LOCAL_APPS = [
    'inpa.accounts',
    'inpa.customers',
    'inpa.analysis',       # 담보 분류 트리 + 정규화 사전 (공유 전역 마스터)
    'inpa.insurances',     # 보험/계산 (소유자 전용 — customer__owner 경유)
    'inpa.notifications',  # 알림 센터 + 리마인더 설정 (소유자 전용, dev/22)
    'inpa.billing',        # 요금제 · 구독 · 사용량 한도 (dev/23)
    'inpa.boards',         # 게시판 & 커뮤니티 (혼합 가시성, dev/17)
    'inpa.promotion',      # 판촉물 주문제작 (혼합 가시성: 샘플=공유/주문=소유자+관리자, dev/21)
    'inpa.admin_console',  # 관리자 콘솔 (IsAdmin 전용 백오피스, dev/19)
    'inpa.analytics',      # ★ 북극성 계측 + 공유뷰 (NorthStarEvent Day1 동결, dev/13)
]
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# ── DB (기본 SQLite — local 상속, prod에서 MariaDB로 override) ────
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# ── 인증 ─────────────────────────────────────────────────────────
AUTH_USER_MODEL = 'accounts.User'  # 이메일/비밀번호 전용 (카카오 OAuth 폐기)

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
     'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    # 목록 응답은 {count, next, previous, results} 형태 (dev/12 §5.1 계약)
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
}

# ── 토큰 TTL / 로그인 잠금 (dev/02 §2.3, dev/11 정본) ────────────
# 비밀번호 재설정: default_token_generator + 이 타임아웃(1h)
PASSWORD_RESET_TIMEOUT = env.int('PASSWORD_RESET_TIMEOUT', default=3600)
# 이메일 인증: TimestampSigner max_age (24h)
EMAIL_VERIFY_TOKEN_TTL_HOURS = env.int('EMAIL_VERIFY_TOKEN_TTL_HOURS', default=24)
# 로그인 5회 실패 → 10분 잠금 (423)
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 600

# ── 이메일 (로컬=콘솔 / 운영=Resend SMTP) ────────────────────────
EMAIL_BACKEND = env('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='no-reply@inpa.local')
EMAIL_HOST = env('EMAIL_HOST', default='')
EMAIL_PORT = env.int('EMAIL_PORT', default=465)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')
EMAIL_USE_SSL = env.bool('EMAIL_USE_SSL', default=False)

FRONTEND_BASE_URL = env('FRONTEND_BASE_URL', default='http://localhost:3000')

# ── Claude API (보험증권 OCR 파싱 · 담보 정규화 — Phase 1.1) ───────
# 하드코딩 금지: env(.env)에서만 주입. 비어 있으면 claude_parser 가 None 반환(OCR 비활성).
ANTHROPIC_API_KEY = env('ANTHROPIC_API_KEY', default='')
# 벤더링한 foliio claude_parser 는 settings.CLAUDE_API_KEY 를 읽는다(무변경 보존) → 동일 키 별칭.
CLAUDE_API_KEY = ANTHROPIC_API_KEY

# ── Claude 모델 정본 (BE 비용 거버넌스) ────────────────────────────
# 추측 금지·하드코딩 금지: 모델 ID는 settings(env)에서만 주입.
#  - 정확도-critical(증권 OCR 파싱·담보 정규화·갈아타기 비교) = Opus 4.8
#  - 대량·저비용(다건 OCR·메시지 생성) = Haiku 4.5
# 과거 하드코딩 'claude-sonnet-4-20250514' 는 제거됨(claude_parser 가 settings 에서 읽음).
CLAUDE_MODEL_PARSE = env('CLAUDE_MODEL_PARSE', default='claude-opus-4-8')
CLAUDE_MODEL_BULK = env('CLAUDE_MODEL_BULK', default='claude-haiku-4-5')

# ── CORS ─────────────────────────────────────────────────────────
CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=['http://localhost:3000'])

# ── i18n ─────────────────────────────────────────────────────────
LANGUAGE_CODE = 'ko-kr'
TIME_ZONE = 'Asia/Seoul'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ── 요금제 베타 스위치 (dev/23 §3, G4) ──────────────────────────────
# True(베타) = 한도 체크 전부 우회(무차감). 정식 출시 시 False 로 flip.
# 환경변수 FREE_TIER_UNLIMITED=true/false 로 런타임 제어.
FREE_TIER_UNLIMITED = env.bool('FREE_TIER_UNLIMITED', default=True)

# ── 갈아타기(승환) 비교 게이트 (dev/09 중개금지 · dev/02 §16 · §97) ──────
# ★ 컴플라이언스 게이트 — 우회 금지. 둘 다 기본 False (보수적 기본값).
#   COMPARE_AI_ENABLED=True 여야만 AI 비교안내서 초안 생성(check_and_consume+Claude).
#     False면 비교표(순수 데이터)는 동작하되 guide_draft=null·guide_enabled=false.
#   COMPARE_PUBLISH_ENABLED=False 이면 고객 발송(publish)을 403 으로 하드블록한다.
#     §97(부당승환) 법무 확정 전까지 비교안내서 발행 금지 — 정식 출시 전 재검토.
COMPARE_AI_ENABLED = env.bool('COMPARE_AI_ENABLED', default=False)
COMPARE_PUBLISH_ENABLED = env.bool('COMPARE_PUBLISH_ENABLED', default=False)
