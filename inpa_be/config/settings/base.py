"""인파 백엔드 공통 설정. 환경별 분리: local(SQLite) / prod(PostgreSQL)."""
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
    'inpa.booking',        # 미팅 예약 (Calendly식 내장 — 슬롯/미팅, 공개 /b/<token>, owner 전용)
    'inpa.dashboard',      # 대시보드 월별 목표 (수동 설정 + 실적 계산, owner 전용)
    'inpa.schedule',       # 개인 일정/할일/고정 차단 (캘린더, owner 전용 — 예약과 별도)
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

# ── DB (기본 SQLite — local 상속, prod에서 PostgreSQL로 override) ────
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
    # 무인증 경로(셀프진단) 남용·비용폭탄 방어용 throttle rate. ScopedRateThrottle 가 뷰별로 사용.
    # ★ LocMemCache(워커별)라 정확상한은 아님 — DB 일일상한과 병행. Redis 도입 시 강화(soon).
    'DEFAULT_THROTTLE_RATES': {
        'self_diagnosis': '5/hour',
        'consent_public': '10/hour',  # 고객 본인 동의 공개 경로(P3c) — 남용 방어
        'booking_public': '20/hour',  # 미팅 예약 공개 경로 — 슬롯 조회+예약(읽기 잦음)
        'ocr': '20/hour',             # 인증 OCR(Claude Opus) 비용폭탄 방어 — 유저별
        'share_public': '60/hour',    # 공유뷰 /s/ — DB write/연산 증폭 DoS 방어
        'auth_email': '5/hour',       # 가입/인증재발송/비번재설정 — 이메일 폭탄 방어
        'admin_login': '5/min',       # 관리자 로그인 무차별 대입 방어(IP 기준)
        'job_runner': '10/hour',      # 일일 배치 트리거 /jobs/run-daily/ — 토큰 대입/재실행 폭탄 방어
    },
}

# 테스트 실행 시 throttle 비활성 — 다수 테스트가 rate limit에 걸리는 것 방지(실동작은 보안 테스트로 별도 검증).
import sys as _sys  # noqa: E402
if 'test' in _sys.argv:
    REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'] = {
        k: None for k in REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']
    }

# ── 토큰 TTL / 로그인 잠금 (dev/02 §2.3, dev/11 정본) ────────────
# 비밀번호 재설정: default_token_generator + 이 타임아웃(1h)
PASSWORD_RESET_TIMEOUT = env.int('PASSWORD_RESET_TIMEOUT', default=3600)
# 이메일 인증: TimestampSigner max_age (24h)
EMAIL_VERIFY_TOKEN_TTL_HOURS = env.int('EMAIL_VERIFY_TOKEN_TTL_HOURS', default=24)
# 고객 동의 요청 링크(P3c): TimestampSigner max_age (72h)
CONSENT_TOKEN_TTL_HOURS = env.int('CONSENT_TOKEN_TTL_HOURS', default=72)
# 일일 배치 트리거 토큰 (spec 2026-07-04) — 미설정('')이면 /jobs/run-daily/ 404 (fail-closed).
# GitHub Secrets 의 JOB_RUNNER_TOKEN 과 동일 값으로 Render env 에 설정.
JOB_RUNNER_TOKEN = env('JOB_RUNNER_TOKEN', default='')
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

# ── 구글 연동 (소셜 로그인 + 캘린더) — 전부 env 게이트. 미설정 시 기능 dark ──────
# 로그인은 CLIENT_ID만, 캘린더는 SECRET+REDIRECT_URI까지 있어야 활성(헬퍼로 단일 판정).
GOOGLE_OAUTH_ENABLED = env.bool('GOOGLE_OAUTH_ENABLED', default=False)
GOOGLE_OAUTH_CLIENT_ID = env('GOOGLE_OAUTH_CLIENT_ID', default='')
GOOGLE_OAUTH_CLIENT_SECRET = env('GOOGLE_OAUTH_CLIENT_SECRET', default='')  # ★ secret — Render 전용
GOOGLE_OAUTH_REDIRECT_URI = env('GOOGLE_OAUTH_REDIRECT_URI', default='')    # 캘린더 callback (Console과 정확히 일치)
GOOGLE_OAUTH_STATE_TTL_SECONDS = env.int('GOOGLE_OAUTH_STATE_TTL_SECONDS', default=600)  # OAuth state(CSRF) TTL

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

# ── 미디어(업로드 파일 — 명함 등) ───────────────────────────────────
# 로컬·단일 인스턴스용. 운영 다중 인스턴스는 S3 등 오브젝트 스토리지로 전환 필요(추후).
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

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

# ── 증권 파싱 정확도 다중검사(Claude 교차검증) — 인증 OCR 경로 전용 ──────────
# True 면 OCR 파싱 후 Claude(Opus)로 '원문 ↔ 파싱결과'를 교차검증해 누락·금액오인식·오분류를
# 잡아 CustomerInsurance.verification 에 저장(설계사 확인용). 정확도 최우선이라 기본 True.
# 비용 민감 시 OCR_VERIFY_ENABLED=false 로 끔. (무인증 셀프진단은 비용 폭주 방지 위해 미적용)
OCR_VERIFY_ENABLED = env.bool('OCR_VERIFY_ENABLED', default=True)

# ── 병력(민감정보) 수집 베타 게이트 (council 2026-06-21 P0-3) ────────────────
# False(기본) = 베타에서 병력 등록(CustomerMedicalHistory create)을 API 단에서 물리 차단.
# 병력=민감정보. 국외이전 동의 적법요건·외부 법무 의견서 확정 전까지 '수집 자체'를 막는다.
# AI 분석은 증권 텍스트만 사용(병력은 Claude로 전송되지 않음)하므로 미수집과 무관하게 동작.
# 정식 출시 전(법무 검토 완료 후) True 로 flip. UI 숨김은 방어가 아니므로 BE에서 차단.
ANALYZE_MEDICAL_ENABLED = env.bool('ANALYZE_MEDICAL_ENABLED', default=False)

# ── 국외이전 동의 = 고객 본인 직접 동의 강제 (council 2026-06-21 P3c) ──────────
# HYBRID-A: 설계사 대리동의는 OCR 게이트(consent_overseas_at)를 절대 열지 못한다(상시).
# 이 플래그는 '향후 설계사 대리 fallback 자체를 둘지' 예약 스위치 — 현재 코드 경로상
# 대리동의 unlock은 어차피 없으므로 기본 False. 정식 출시 검토 시 재확정.
REQUIRE_CUSTOMER_SELF_CONSENT = env.bool('REQUIRE_CUSTOMER_SELF_CONSENT', default=False)

# ── 미팅 예약(Calendly식 내장) 게이트 ────────────────────────────────────────
# BOOKING_ENABLED=False면 예약 인증 API 403 + 공개 /b/<token> 404(존재 은폐).
# BOOKING_EMAIL_ENABLED: 자동 이메일 발송(정직성 레드라인=복사붙여넣기만) — 예약만, 미구현(기본 False).
# 토큰 TTL은 동의 링크와 동일 패턴(72h).
BOOKING_ENABLED = env.bool('BOOKING_ENABLED', default=True)
BOOKING_EMAIL_ENABLED = env.bool('BOOKING_EMAIL_ENABLED', default=False)
BOOKING_TOKEN_TTL_HOURS = env.int('BOOKING_TOKEN_TTL_HOURS', default=72)
