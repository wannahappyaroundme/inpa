# 인파(Inpa) — DevOps & 배포 가이드

> **문서 ID**: `dev/20-devops-and-deploy.md`
> **작성일**: 2026-06-19
> **대상 독자**: 개발자(CTO겸 CPO), 추후 합류 인력, 인프라 운영자
> **전제**: FE = Next.js 16 + TypeScript + Tailwind / BE = Django 4.1 + DRF + Python / DB = MariaDB / 인증 = 이메일·비밀번호 전용(카카오 OAuth 제거)
> **원칙**: MVP 무료·저비용 우선. 스케일이 필요해지면 그때 유료 인프라로 올라탄다.

---

## 0. 한눈에 보는 인프라 구성

```
[설계사 브라우저]
       │ HTTPS
       ▼
┌──────────────────┐          ┌────────────────────────────────┐
│  Vercel (FE)     │  /api/*  │  IDC 서버 211.234.108.90       │
│  Next.js 16 SSR  │─────────▶│  nginx → gunicorn → Django 4.1 │
│  (무료 Hobby)    │          │  conda env: inpa               │
└──────────────────┘          │  systemd: inpa.service         │
                              │  MariaDB 10.3.39 (127.0.0.1)  │
                              └────────────────────────────────┘
                                           │ API 호출
                                           ▼
                              ┌────────────────────────────────┐
                              │  Anthropic Claude API (US)     │
                              │  Opus 4.8 (M1) / Haiku 4.5    │
                              └────────────────────────────────┘
```

| 구성요소 | 선택 | 이유 |
|---|---|---|
| **FE 배포** | Vercel Hobby (무료) | Next.js 공식 플랫폼, 무료 플랜으로 MVP 커버 |
| **BE 배포** | IDC 서버 (기존 인프라) | foliio 배포 인프라 그대로 승계, 비용 0 추가 |
| **DB** | MariaDB 10.3.39 (IDC 동거) | foliio 자산 승계, PG 전환 보류 |
| **AI** | Claude API (Anthropic, 미국) | foliio `claude_parser.py` 승계 |
| **이메일 발송** | Resend 무료 플랜 (월 3,000건) | SMTP 설정 불필요, Django 연동 쉬움 |
| **모니터링** | Sentry 무료 플랜 | BE 이미 조건부 init 완료 (`base.py:406-421`) |
| **시크릿** | `.env` → Vercel 환경변수 / IDC `.env` 파일 | MVP 수준, 정식 출시 전 Vault 검토 |

---

## 1. 환경 분리 (dev / staging / prod)

### 1.1 환경 구분

| 환경 | FE | BE | DB | 목적 |
|---|---|---|---|---|
| **local** | `npm run dev` (localhost:3000) | `DJANGO_SETTINGS_MODULE=config.settings.local` (localhost:8000) | 로컬 MariaDB | 개발 |
| **preview** | Vercel Preview (PR마다 자동) | IDC 스테이징 포트 또는 로컬 터널 | 스테이징 DB | QA·PM 검수 |
| **production** | Vercel Production | IDC `config.settings.idc` (gunicorn) | 프로덕션 DB | 실사용 |

### 1.2 Django settings 분리

```
config/
  settings/
    base.py          # 공통 (설치앱, 미들웨어, Sentry 조건부 init)
    local.py         # DEBUG=True, 로컬 DB, console 이메일 백엔드
    idc.py           # DEBUG=False, CORS 화이트리스트, secure cookie, SSL-via-nginx
```

> ⚠️ `manage.py` 기본값 = `config.settings.idc` (프로덕션).
> **로컬에서는 모든 명령에 `DJANGO_SETTINGS_MODULE=config.settings.local` 반드시 명시.**
> 안 붙이면 프로덕션 DB에 붙는다.

### 1.3 Next.js 환경변수 분리

```
.env.local          # 로컬 전용 (git 제외)
.env.preview        # Vercel Preview 환경 (Vercel 대시보드에서 관리)
.env.production     # Vercel Production (Vercel 대시보드에서 관리)
```

**`NEXT_PUBLIC_*` 누출 규칙** (절대 위반 금지):
- `NEXT_PUBLIC_API_URL` — BE 엔드포인트만 허용 (도메인 공개 OK)
- `NEXT_PUBLIC_SENTRY_DSN` — Sentry DSN은 공개 OK (특성상)
- **절대 금지**: `NEXT_PUBLIC_CLAUDE_API_KEY`, `NEXT_PUBLIC_SECRET_KEY`, DB 자격증명, 이메일 서비스 API 키
- 시크릿은 **서버사이드 전용** (Next.js Route Handler / Django BE에서만 사용)

---

## 2. 환경변수 목록

### 2.1 BE 환경변수 (IDC `.env` 파일)

```bash
# Django
SECRET_KEY=<랜덤 50자 이상>
DJANGO_SETTINGS_MODULE=config.settings.idc
DEBUG=False

# DB
DJANGO_DEFAULT_DATABASE_HOST=127.0.0.1
DJANGO_DEFAULT_DATABASE_PORT=3306
DJANGO_DEFAULT_DATABASE_NAME=inpa_db
DJANGO_DEFAULT_DATABASE_USER=inpa
DJANGO_DEFAULT_DATABASE_PASSWORD=<strong password>

# Claude API
CLAUDE_API_KEY=<anthropic api key>
CLAUDE_MONTHLY_BUDGET_KRW=100000      # 월 예산 캡 (원, 초과 시 알림)

# 이메일 발송 (Resend)
RESEND_API_KEY=<resend api key>
EMAIL_FROM=noreply@inpa.kr             # 발신 주소 (도메인 확정 후 교체)

# Sentry
SENTRY_DSN=<sentry dsn>
SENTRY_ENVIRONMENT=inpa-prod

# 기능 플래그 (베타)
FREE_TIER_UNLIMITED=True               # 베타 기간 무제한. 정식 출시 시 False
SUPER_BETA_EXPIRY=2099-12-31          # 베타 만료일 (출시일 확정 후 교체)

# 국외이전 동의 게이트
AI_OVERSEAS_GATE_ENABLED=True          # False면 412 게이트 비활성 (테스트용)
```

### 2.2 FE 환경변수 (Vercel 대시보드)

```bash
# 공개 변수 (NEXT_PUBLIC_)
NEXT_PUBLIC_API_URL=https://api.inpa.kr/api/v1   # BE 도메인 확정 후 교체

# 서버사이드 전용 (절대 NEXT_PUBLIC_ 접두사 금지)
SENTRY_AUTH_TOKEN=<sentry auth token>             # 소스맵 업로드 전용
```

---

## 3. 시크릿 관리

### 3.1 원칙

- 하드코딩 API 키 = **코드리뷰 즉시 reject + pre-commit 차단**
- `.env` 파일은 `.gitignore`에 반드시 포함
- `.env.example` 커밋 (키 값 없음, 키 이름만)
- 노출 발생 시: **키 즉시 로테이션 → `git filter-repo` 히스토리 제거 → 팀 공지**

### 3.2 `.gitignore` 필수 항목

```
.env
.env.local
.env.*.local
*.pem
*.key
*.p12
secrets/
config/credentials*
__pycache__/
*.pyc
node_modules/
.next/
dist/
```

### 3.3 pre-commit gitleaks 설정

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.4
    hooks:
      - id: gitleaks
```

> 설치: `pip install pre-commit && pre-commit install`
> CI에서도 동일하게 실행 (§4.2).

---

## 4. CI 파이프라인

### 4.1 CI 트리거

| 트리거 | 실행 내용 |
|---|---|
| PR 생성 / 업데이트 | lint + test + build (전체) |
| `main` 브랜치 push | lint + test + build + **Vercel Production 배포** |
| 그 외 브랜치 push | lint + test (빌드 생략) |

### 4.2 GitHub Actions 워크플로우

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  backend:
    runs-on: ubuntu-latest
    services:
      mariadb:
        image: mariadb:10.3
        env:
          MYSQL_ROOT_PASSWORD: test
          MYSQL_DATABASE: inpa_test
          MYSQL_USER: inpa
          MYSQL_PASSWORD: test
        options: --health-cmd="mysqladmin ping" --health-timeout=5s
        ports:
          - 3306:3306
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.8'
          cache: 'pip'
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: gitleaks (시크릿 스캔)
        uses: gitleaks/gitleaks-action@v2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
      - name: Lint (ruff)
        run: ruff check .
      - name: Run tests
        env:
          DJANGO_SETTINGS_MODULE: config.settings.local
          DJANGO_DEFAULT_DATABASE_HOST: 127.0.0.1
          DJANGO_DEFAULT_DATABASE_NAME: inpa_test
          DJANGO_DEFAULT_DATABASE_USER: inpa
          DJANGO_DEFAULT_DATABASE_PASSWORD: test
          CLAUDE_API_KEY: dummy-for-ci
          RESEND_API_KEY: dummy-for-ci
        run: |
          python manage.py migrate
          pytest --tb=short -q
      - name: 8케이스 골든테스트 (보험료 계산 회귀)
        run: pytest weapon/insurances/tests/test_premium_calculation_8cases.py -v

  frontend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: inpa_fe
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'
          cache-dependency-path: inpa_fe/package-lock.json
      - run: npm ci
      - name: Type check
        run: npx tsc --noEmit
      - name: Build
        run: npm run build
        env:
          NEXT_PUBLIC_API_URL: http://localhost:8000/api/v1
```

### 4.3 커밋 메시지 규칙 (commitlint)

```yaml
# .commitlintrc.yml
extends: ['@commitlint/config-conventional']
rules:
  type-enum:
    - 2
    - always
    - [feat, fix, refactor, docs, test, chore, perf, security]
```

> 허용 타입: `feat`(신규) · `fix`(버그) · `refactor` · `docs` · `test` · `chore` · `perf` · `security`
> 예시: `feat(ocr): 다건 일괄 업로드 detect_batch API 추가`

---

## 5. FE 배포 — Vercel

### 5.1 Vercel 설정

| 항목 | 값 |
|---|---|
| **플랜** | Hobby (무료) — MVP |
| **프레임워크** | Next.js (자동 감지) |
| **루트 디렉토리** | `inpa_fe/` |
| **Build 명령** | `npm run build` |
| **Output 디렉토리** | `.next` (자동) |
| **Node 버전** | 20.x |

### 5.2 FE 배포 흐름

```
개발자 push → GitHub → Vercel 자동 트리거
                │
                ├─ PR 브랜치: Preview 배포 (https://<branch>.inpa.vercel.app)
                │             → PM이 브라우저에서 직접 확인
                │
                └─ main 브랜치: Production 배포 (https://inpa.kr 또는 커스텀 도메인)
                               → 자동 배포 (PR merge 후 즉시)
```

### 5.3 Vercel 롤백

```bash
# Vercel 대시보드 → Deployments → 이전 배포 → "Promote to Production"
# 또는 CLI:
vercel rollback <deployment-url>
```

> 롤백은 FE만 되돌린다. BE 마이그레이션이 이미 적용됐다면 BE도 함께 롤백 계획 필요.

---

## 6. BE 배포 — IDC 서버

### 6.1 서버 구조

```
IDC 서버 211.234.108.90  user: pample
  /home/pample/work/inpa/Inpa_be/    ← Django 소스
  /var/www/<도메인>/html/             ← (미사용: FE는 Vercel)
  conda env: inpa
  systemd: inpa.service
  nginx: /etc/nginx/sites-enabled/inpa
```

### 6.2 배포 스크립트 (`deploy-be.sh`)

```bash
#!/bin/bash
# deploy-be.sh — BE 배포 (로컬 맥에서 실행)
set -e

SERVER=pample@211.234.108.90
REMOTE_PATH=/home/pample/work/inpa/Inpa_be
DJANGO_SETTINGS=config.settings.idc

echo "=== [1/4] 코드 동기화 ==="
rsync -avz --exclude='.env' --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='.git' \
  ./ ${SERVER}:${REMOTE_PATH}/

echo "=== [2/4] 마이그레이션 ==="
ssh ${SERVER} "cd ${REMOTE_PATH} && conda run -n inpa \
  python manage.py migrate --settings=${DJANGO_SETTINGS}"

echo "=== [3/4] 정적파일 수집 ==="
ssh ${SERVER} "cd ${REMOTE_PATH} && conda run -n inpa \
  python manage.py collectstatic --noinput --settings=${DJANGO_SETTINGS}"

echo "=== [4/4] gunicorn 재시작 ==="
ssh ${SERVER} "sudo systemctl restart inpa.service"

echo "=== 배포 완료 ==="
echo "상태 확인: ssh ${SERVER} 'sudo systemctl status inpa.service'"
```

> **주의**: 배포 스크립트는 `pip install`을 자동 실행하지 않는다. 의존성 변경 시 서버에서 수동으로:
> `conda activate inpa && pip install -r requirements.txt`

### 6.3 nginx 설정 (요약)

```nginx
server {
    listen 443 ssl;
    server_name api.inpa.kr;           # 도메인 확정 후 교체
    # SSL 인증서 (Let's Encrypt 무료)
    ssl_certificate /etc/letsencrypt/live/api.inpa.kr/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.inpa.kr/privkey.pem;

    location /api/v1/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /static/ {
        alias /home/pample/work/inpa/Inpa_be/staticfiles/;
    }

    location /media/ {
        alias /home/pample/work/inpa/Inpa_be/media/;
    }

    # FE는 Vercel에서 서빙 — nginx에서 별도 처리 불필요
}
```

### 6.4 systemd 서비스 (`inpa.service`)

```ini
[Unit]
Description=Inpa Django Backend
After=network.target mariadb.service

[Service]
User=pample
Group=pample
WorkingDirectory=/home/pample/work/inpa/Inpa_be
Environment="PATH=/home/pample/miniconda3/envs/inpa/bin"
Environment="DJANGO_SETTINGS_MODULE=config.settings.idc"
EnvironmentFile=/home/pample/work/inpa/Inpa_be/.env
ExecStart=/home/pample/miniconda3/envs/inpa/bin/gunicorn \
    config.wsgi:application \
    --bind 127.0.0.1:8000 \
    --workers 3 \
    --timeout 120
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

---

## 7. DB 마이그레이션 순서

마이그레이션 순서가 틀리면 FK 무결성 위반이 난다. **반드시 아래 순서를 지킨다.**

```bash
# 1. 기본 Django 마이그레이션
python manage.py migrate

# 2. 담보 트리 + 정규화 사전 시드 (StandardCoverage FK의 선행 데이터)
#    → planner_baseline.coverage_key가 이 데이터를 참조
python manage.py seed_taxonomy

# 3. 멤버십 초기 데이터
python manage.py loadinitialmemberships

# 4. (조건부) 기준선 프리셋 시드
#    → G4-1(기준선 출처·권위) 확정 후에만 실행
#    → 출처 미확정 상태로 실행 금지 (컴플라이언스 위반)
# python manage.py seed_baseline_preset
```

### 7.1 마이그레이션 원칙

- 마이그레이션 파일은 **커밋 전 반드시 `git diff`로 검토** (모델 실수가 DB 구조 파괴)
- `makemigrations` 후 `sqlmigrate`로 실제 SQL 확인
- 프로덕션 마이그레이션은 **배포 직전 단독 실행** (애플리케이션 재시작 전)
- 롤백 계획: 마이그레이션 `down`(`--fake` 또는 이전 상태로 되돌리기) 미리 검증

### 7.2 롤백 경로 (BE)

```bash
# 특정 마이그레이션으로 되돌리기
python manage.py migrate <앱이름> <이전 마이그레이션번호>
# 예: python manage.py migrate customers 0023

# 코드 롤백 (rsync로 이전 버전 재배포)
# → deploy-be.sh를 이전 커밋 태그로 실행
```

> 데이터 손실 마이그레이션(컬럼 삭제 등)은 **반드시 롤백 쿼리를 사전 작성하고 PM 승인 후 실행**.

---

## 8. 이메일 발송 인프라

인파의 이메일 발송은 세 가지 경우다: ① 가입 이메일 인증, ② 비밀번호 재설정, ③ 알림/리마인더(Phase 1.5+).

### 8.1 서비스 선택: Resend

| 항목 | 내용 |
|---|---|
| **서비스** | [Resend](https://resend.com) |
| **무료 한도** | 월 3,000건 (도메인 인증 후) |
| **Django 연동** | `django-resend` 패키지 또는 `requests` 직접 호출 |
| **발신 도메인** | `inpa.kr` (도메인 확정 후 DNS SPF/DKIM 설정) |

> **선택 이유**: SMTP 설정 불필요. 대시보드에서 발송 로그·bounce 확인 용이. 무료 플랜으로 MVP 충분. Gmail SMTP 대비 Deliverability 우위.

### 8.2 이메일 타입별 명세

| 타입 | 트리거 | 발신자 | 제목 (예시) | 만료 |
|---|---|---|---|---|
| **가입 인증** | 회원가입 완료 즉시 | noreply@inpa.kr | `[인파] 이메일 인증을 완료해 주세요` | 24시간 |
| **비밀번호 재설정** | 비밀번호 찾기 요청 | noreply@inpa.kr | `[인파] 비밀번호 재설정 링크입니다` | 1시간 |
| **만기 알림** (Phase 1.5) | watchdog cron | noreply@inpa.kr | `[인파] OO님 고객의 보험이 30일 후 만기됩니다` | — |

### 8.3 Django 이메일 설정

**local.py (개발용 — 실제 발송 없음)**:
```python
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
```

**idc.py (프로덕션 — Resend 사용)**:
```python
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.resend.com'
EMAIL_PORT = 465
EMAIL_USE_SSL = True
EMAIL_HOST_USER = 'resend'
EMAIL_HOST_PASSWORD = os.environ['RESEND_API_KEY']
DEFAULT_FROM_EMAIL = 'noreply@inpa.kr'
```

### 8.4 이메일 토큰 보안

- 토큰은 **cryptographically random** (`secrets.token_urlsafe(32)`)
- DB에 해시값만 저장 (`hashlib.sha256`). 원문은 저장 안 함
- 인증 토큰: 24시간 만료. 비번 재설정: 1시간 만료
- 토큰 사용 즉시 무효화 (1회용)
- 이메일 인증 미완료 계정은 로그인 차단 (`is_email_verified=False → 401`)

---

## 9. 인증 플로우 (이메일·비밀번호 전용)

> ⚠️ **확정 결정**: 카카오 OAuth 전면 제거. 이메일·비밀번호 전용.
> `dev/11-auth-onboarding.md`의 카카오 내용은 이 결정으로 무효화됨.

### 9.1 인증 흐름 4종

```
[회원가입]
  POST /api/v1/accounts/register/  {email, password, password2}
    → User 생성 (is_email_verified=False)
    → 이메일 인증 토큰 발급 + 인증 메일 발송
    → 응답: {message: "인증 메일을 발송했습니다"}

[이메일 인증]
  GET /api/v1/accounts/verify-email/?token=<token>
    → 토큰 검증 + 만료 확인
    → User.is_email_verified = True
    → 응답: 인증 완료 페이지로 리다이렉트

[로그인]
  POST /api/v1/accounts/login/  {email, password}
    → is_email_verified 확인 (미인증 → 401 + "인증 메일을 확인해 주세요")
    → bcrypt 비밀번호 검증
    → DRF Token 발급
    → 응답: {token: "...", profile: {...}}

[비밀번호 재설정]
  1. POST /api/v1/accounts/password-reset/  {email}
     → 재설정 토큰 발급 + 메일 발송

  2. POST /api/v1/accounts/password-reset/confirm/  {token, new_password}
     → 토큰 검증 (1시간 내, 1회용)
     → 비밀번호 변경
```

### 9.2 가입 시 약관 동의 통합

가입 API 요청에 약관 동의를 함께 받는다.

```json
POST /api/v1/accounts/register/
{
  "email": "agent@example.com",
  "password": "...",
  "password2": "...",
  "terms_agreed": true,           // 필수: 서비스 이용약관
  "privacy_agreed": true,         // 필수: 개인정보 처리방침
  "marketing_agreed": false       // 선택: 마케팅 수신 동의
}
```

- `terms_agreed`, `privacy_agreed` 중 하나라도 false → 400 거절
- 동의 시각은 `User.terms_agreed_at`, `User.privacy_agreed_at` 기록 (감사 추적)

---

## 10. 모니터링

### 10.1 Sentry (에러 트래킹)

BE는 `base.py:406-421`에 조건부 init 이미 완료 (foliio 승계).

```python
# config/settings/base.py (승계, 수정 없음)
if os.environ.get('SENTRY_DSN'):
    import sentry_sdk
    sentry_sdk.init(
        dsn=os.environ['SENTRY_DSN'],
        environment=os.environ.get('SENTRY_ENVIRONMENT', 'development'),
        traces_sample_rate=0.1,
    )
```

FE Sentry 추가 (`inpa_fe/next.config.ts`에 withSentryConfig 래핑):
- 소스맵 업로드: CI에서 `SENTRY_AUTH_TOKEN`으로 자동 업로드
- 에러 경계: Next.js `error.tsx` + Sentry 캡처

**알림 설정 (Sentry 대시보드)**:
- Unhandled Exception → Slack/이메일 즉시 알림
- 이슈 발생률 급증 → 알림

### 10.2 Web Vitals (FE 성능)

Next.js 기본 내장 Web Vitals를 Sentry Performance로 수집:

```typescript
// inpa_fe/app/layout.tsx (또는 별도 instrumentation.ts)
export function reportWebVitals(metric: NextWebVitalsMetric) {
  // Sentry Performance로 전송
}
```

목표 (MVP 기준):
- LCP (Largest Contentful Paint): < 2.5초
- FID (First Input Delay): < 100ms
- CLS (Cumulative Layout Shift): < 0.1

### 10.3 슬로우 쿼리 (BE)

Django 개발 환경에서 쿼리 로그:
```python
# local.py
LOGGING = {
    'loggers': {
        'django.db.backends': {
            'level': 'DEBUG',
            'handlers': ['console'],
        }
    }
}
```

프로덕션 MariaDB 슬로우 쿼리 로그:
```sql
-- my.cnf에 추가
slow_query_log = 1
slow_query_log_file = /var/log/mysql/slow.log
long_query_time = 1   -- 1초 초과 쿼리 기록
```

> **목표**: 100ms 초과 경고, 1초 초과 알림.

### 10.4 Claude API 비용 모니터링

```python
# 모든 Claude API 호출 후 로깅 (base_claude_client.py)
response = client.messages.create(...)
logger.info(
    "claude_api_call",
    extra={
        "model": response.model,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "cache_read_input_tokens": getattr(response.usage, 'cache_read_input_tokens', 0),
        "purpose": purpose,  # 'ocr_parse' / 'compare_guide' / 'message_gen' 등
        "customer_id": customer_id,
    }
)
```

- 월 예산 캡 (`CLAUDE_MONTHLY_BUDGET_KRW`) 80% 도달 시 관리자 이메일 알림
- 100% 도달 시 AI 기능 일시 차단 + 긴급 알림

---

## 11. 프로덕션 배포 체크리스트

> ⚠️ **프로덕션 배포는 PM(대표) 명시적 승인 후에만 실행한다.**

```
배포 전 (코드 준비)
  [ ] pytest 전체 통과 (8케이스 골든 포함)
  [ ] npm run build 성공 (FE 빌드 오류 없음)
  [ ] tsc --noEmit 통과 (타입 오류 없음)
  [ ] gitleaks 통과 (시크릿 노출 없음)
  [ ] commitlint 통과 (커밋 메시지 규칙 준수)

배포 전 (인프라 확인)
  [ ] .env 변수 diff 확인 (dev와 prod 차이점 검토)
  [ ] DB 마이그레이션 순서 확인 (seed 선행 여부)
  [ ] 롤백 경로 확인 (이전 배포 태그 또는 마이그레이션 버전)
  [ ] PM 승인 수령

배포 실행
  [ ] BE 배포: ./deploy-be.sh (마이그레이션 포함)
  [ ] FE 배포: Vercel main 브랜치 머지 (자동)

배포 후 검증
  [ ] 실제 URL 접속 + 로그인 happy path 확인
  [ ] 이메일 발송 테스트 (가입/비번재설정)
  [ ] Sentry 5분 모니터링 (신규 오류 없음)
  [ ] BE API curl 테스트 (핵심 엔드포인트)
  [ ] 슬로우 쿼리 로그 이상 없음

배포 후 기록
  [ ] 배포 사항 PM에게 요약 보고
  [ ] 이슈 발생 시 즉시 롤백 결정
```

---

## 12. 로컬 개발 환경 셋업

### 12.1 백엔드 셋업

```bash
# 1. conda 환경 생성 (foliio와 별도)
conda create -n inpa python=3.8
conda activate inpa

# 2. 의존성 설치 (신규 패키지 0개)
pip install -r requirements.txt

# 3. .env.local 생성 (.env.example 복사 후 값 채우기)
cp .env.example .env.local

# 4. DB 마이그레이션 (로컬 설정 명시 필수!)
DJANGO_SETTINGS_MODULE=config.settings.local python manage.py migrate

# 5. 담보 트리 시드
DJANGO_SETTINGS_MODULE=config.settings.local python manage.py seed_taxonomy

# 6. 개발 서버
DJANGO_SETTINGS_MODULE=config.settings.local python manage.py runserver
```

### 12.2 프론트엔드 셋업

```bash
cd inpa_fe

# 1. 의존성 설치
npm ci   # npm install 대신 ci 사용 (lockfile 정확히 재현)

# 2. .env.local 생성
echo "NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1" > .env.local

# 3. 개발 서버
npm run dev   # http://localhost:3000

# 타입 체크
npx tsc --noEmit

# 빌드 확인
npm run build
```

### 12.3 pre-commit 훅 설치

```bash
# 루트 디렉토리에서
pip install pre-commit
pre-commit install

# 수동 실행 (전체 파일)
pre-commit run --all-files
```

---

## 13. 수용 기준 (Definition of Done)

- [ ] `main` 브랜치 push → GitHub Actions CI 자동 실행 (lint + test + build) 통과
- [ ] PR merge → Vercel Preview 자동 배포 (PM 검수 URL 생성)
- [ ] `main` merge → Vercel Production 자동 배포 (5분 이내)
- [ ] gitleaks pre-commit 훅 동작 확인 (더미 키 삽입 → 커밋 차단)
- [ ] `NEXT_PUBLIC_*`에 시크릿 없음 (`grep -r "NEXT_PUBLIC_" inpa_fe/.env*` 검증)
- [ ] 이메일 인증 happy path 동작: 가입 → 메일 수신 → 클릭 → 로그인 성공
- [ ] 비밀번호 재설정 happy path: 요청 → 메일 수신 → 클릭 → 새 비번 설정 → 로그인
- [ ] Sentry 에러 캡처 동작: 의도적 500 에러 → Sentry 대시보드 확인
- [ ] BE 배포 스크립트 (`deploy-be.sh`) 1회 실제 실행 성공
- [ ] DB 마이그레이션 순서 검증: 빈 DB → 전체 migrate → seed_taxonomy 순서 성공
- [ ] Claude API 호출 비용 로그: `claude_api_call` 로그 Sentry/서버 로그에서 확인
- [ ] 슬로우 쿼리 로그 MariaDB에서 1초 초과 쿼리 기록 확인

---

## 14. 미결 항목 (openGaps)

| # | 항목 | 영향 | 해소 시점 |
|---|---|---|---|
| G-1 | **도메인 확정** (`inpa.kr` 또는 다른 도메인) | Vercel 커스텀 도메인, 이메일 발신 도메인, nginx server_name 전부 | 정식 출시 전 |
| G-2 | **SSL 인증서** — Let's Encrypt 자동 갱신 설정 | HTTPS 필수 (이메일 토큰 클릭, 개인정보 전송) | 도메인 확정 후 |
| G-3 | **이메일 발신 도메인 인증** (SPF/DKIM/DMARC 설정) | 이메일 Deliverability (스팸함 착신 방지) | 이메일 기능 출시 전 |
| G-4 | **Vercel → IDC BE CORS** 설정 | FE-BE 통신 (`CORS_ALLOWED_ORIGINS`에 Vercel 도메인 추가) | FE 배포 전 |
| G-5 | **월 예산 캡 알림 수신자** — 이메일 또는 Slack 웹훅 미지정 | Claude API 비용 초과 시 알림 누락 | Phase 1 시작 전 |
| G-6 | **Resend 도메인 인증** (DNS TXT 레코드) | 이메일 발송 불가 (도메인 인증 전 제한) | 도메인 확정 후 |
| G-7 | **MariaDB 일일 백업 cron** — foliio에 있었는지 확인 후 인파 서버에 동일 적용 | 데이터 손실 방지 | Phase 1 배포 전 |
| G-8 | **Sentry FE 프로젝트 분리** — 현재 foliio와 공유 여부 불명 | 노이즈 격리 + 인파 전용 알림 | CI 구성 시 |

---

*관련 문서: `dev/01-architecture-and-stack.md` (시스템 아키텍처) · `dev/04-build-plan.md` (Phase 일정) · `dev/11-auth-onboarding.md` (인증 상세 — 카카오 제거 결정으로 일부 무효, 본 문서 §9 우선) · `dev/09-compliance-broker-line.md` (컴플라이언스 게이트)*
