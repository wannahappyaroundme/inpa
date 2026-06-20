# 인파(Inpa) — 배포 실전 가이드 (PM·비개발자용)

> **문서 ID**: `dev/25-deploy-guide.md`
> **작성일**: 2026-06-19
> **대상 독자**: PM(대표, 비개발자) — 마우스 클릭만으로 따라 할 수 있게 작성.
> **정본 아키텍처**: `dev/20-devops-and-deploy.md` (이 문서는 그 실행판이다.)
> **배포 그림(무료 $0)**: FE = Vercel (GitHub 자동배포) / BE = Render (무료 Web) / DB = Neon (무료 PostgreSQL) / CI = GitHub Actions(검증만).
> **갱신(2026-06-21)**: Railway 무료 티어 폐지로 **BE=Render·DB=Neon(무료)** 로 전환. DB는 MariaDB→**PostgreSQL**(Django ORM이라 코드 영향 없음, 로컬은 SQLite 유지).

---

## 0. 큰 그림 (3분 읽기)

```
[ 내 PC: git push ]
        │
        ▼
[ GitHub 저장소 ]──┬──▶ GitHub Actions (자동 검사: 백엔드 테스트 + 프론트 빌드 + 시크릿 스캔)
                   │
                   ├──▶ Vercel  : inpa_fe (프론트) 자동 배포 → 사용자가 보는 화면
                   │
                   └──▶ Render  : inpa_be (백엔드) 자동 배포 ──▶ Neon (PostgreSQL DB)
```

- **시크릿(비밀번호·API 키)은 코드에 절대 안 넣는다.** 항상 Vercel·Railway 대시보드의 "환경변수"에 넣는다.
- **`main` 브랜치에 합쳐지면(merge) 자동으로 배포된다.** 별도 "배포 버튼" 누를 필요 없음.
- 이 문서는 **a → e 순서**다. 위에서부터 그대로 따라 하면 된다.

> ⚠️ 한 가지만 기억: **`.env` 파일을 GitHub에 올리지 않는다.** 비밀 값은 전부 플랫폼 대시보드에 직접 입력한다.

---

## (a) GitHub 저장소 생성 · 코드 푸시

### a-1. GitHub 저장소 만들기
1. https://github.com 로그인 → 우측 상단 **`+`** → **New repository** 클릭.
2. 입력값:
   - **Repository name**: `inpa` (원하는 이름)
   - **Visibility**: **Private** (소스 비공개 권장)
   - "Add a README" 등 체크박스는 **모두 해제** (이미 로컬에 코드가 있으므로).
3. **Create repository** 클릭.
4. 다음 화면에 나오는 주소(`https://github.com/<내계정>/inpa.git`)를 복사해 둔다.

### a-2. 로컬 코드 올리기 (터미널)
> 터미널(맥: 터미널 앱)에서 아래를 **한 줄씩** 실행. `<내계정>`만 본인 것으로 교체.

```bash
cd /Users/kyungsbook/Desktop/inpa
git add .
git commit -m "chore: 배포 설정 및 초기 코드"
git branch -M main
git remote add origin https://github.com/<내계정>/inpa.git
git push -u origin main
```

- **성공 신호**: 마지막 줄에 `branch 'main' set up to track 'origin/main'` 비슷한 문구. GitHub 저장소 페이지를 새로고침하면 `inpa_be/`, `inpa_fe/`, `docs/` 폴더가 보인다.
- **흔한 오류**:
  - `remote origin already exists` → `git remote remove origin` 실행 후 다시 `git remote add ...`.
  - 로그인 창이 안 뜨고 막힘 → GitHub **Personal Access Token**을 비밀번호 대신 입력해야 함. (GitHub → Settings → Developer settings → Personal access tokens.)

### a-3. GitHub Actions 자동 검사 확인
- 푸시 직후 저장소의 **Actions** 탭에 `CI` 워크플로우가 돌기 시작한다.
- 3개 작업(`Backend`, `Frontend`, `Secret scan`)이 전부 **초록 체크**면 통과.
- 빨간 X가 뜨면 클릭해서 로그를 보고 개발자(또는 Claude)에게 전달.

---

## (b) Vercel에 프론트엔드(inpa_fe) 연결

### b-1. 프로젝트 import
1. https://vercel.com → **GitHub 계정으로 로그인**.
2. 대시보드 → **Add New...** → **Project**.
3. 방금 만든 `inpa` 저장소 옆 **Import** 클릭. (처음이면 "GitHub 앱 설치/권한 허용" 한 번 뜸 → 허용.)

### b-2. 핵심 설정 — 루트 디렉토리
> 인파는 한 저장소에 FE/BE가 같이 있으므로 **프론트 폴더를 지정**해야 한다.

1. **Root Directory** 항목에서 **Edit** → **`inpa_fe`** 선택. (★ 가장 중요. 이걸 안 하면 빌드 실패.)
2. **Framework Preset**: `Next.js` (자동 감지됨).
3. **Build Command / Output**: 기본값 그대로 (vercel.json이 처리).

### b-3. 환경변수 입력
> **Environment Variables** 섹션에서 아래를 추가. (BE 주소는 (c) 단계에서 Railway 배포 후 확정되므로, 우선 임시로 넣고 (c) 끝나면 교체한다.)

| Name | Value 예시 | 비고 |
|---|---|---|
| `NEXT_PUBLIC_API_BASE` | `https://inpa-be.up.railway.app/api/v1` | Railway BE 주소 + `/api/v1`. (c)에서 확정 후 교체 |

- `NEXT_PUBLIC_`로 시작하는 값은 브라우저에 공개되어도 되는 값만 넣는다. **API 키·비밀번호는 절대 여기 넣지 않는다.**
- 참고 양식: `inpa_fe/.env.production.example`.

### b-4. 배포
1. **Deploy** 클릭 → 1~3분 대기.
2. **성공 신호**: "Congratulations" 화면 + `https://inpa-xxxx.vercel.app` 주소 생성. 그 주소를 메모(=프론트 도메인).
3. **흔한 오류**:
   - 빌드 실패 + `No Next.js version detected` → Root Directory를 `inpa_fe`로 안 잡은 것. b-2 다시.
   - 화면은 뜨는데 데이터가 안 옴 → `NEXT_PUBLIC_API_BASE`가 틀렸거나 (c)의 CORS 미설정. (e)에서 점검.

---

## (c) Railway에 백엔드(inpa_be) + MySQL 연결

### c-1. 프로젝트 + DB 만들기
1. https://railway.app → **GitHub로 로그인**.
2. **New Project** → **Deploy from GitHub repo** → `inpa` 선택. (권한 요청 시 허용.)
3. 서비스가 생성되면 → 그 서비스 클릭 → **Settings** 탭 → **Root Directory**를 **`inpa_be`**로 지정. (★ FE/BE 한 저장소이므로 필수.)
4. DB 추가: 프로젝트 화면에서 **New** → **Database** → **Add MySQL**. (MariaDB 호환. Render는 관리형 Postgres만이라 인파는 Railway를 쓴다.)

### c-2. DATABASE_URL 연결 (DB → BE)
1. BE 서비스 → **Variables** 탭 → **New Variable** → **Add Reference** 선택.
2. 방금 만든 MySQL의 **`DATABASE_URL`**(또는 `MYSQL_URL`)을 참조로 추가하고, 변수 이름을 **`DATABASE_URL`**로 맞춘다.
   - 형식은 `mysql://user:pass@host:3306/dbname` 이어야 한다. 참조를 쓰면 자동으로 채워진다.

### c-3. BE 환경변수 입력 (Variables 탭)
> 아래 이름을 **정확히 그대로** 입력. 값은 본인 것으로. (시크릿은 여기에만, 코드/`.env`에는 절대 안 넣음.)

> **★ 코드 안전판(이미 적용됨 — 사고 방지용):**
> - `railway.json`·`nixpacks.toml`이 **`DJANGO_SETTINGS_MODULE=config.settings.prod`를 강제** → 변수를 깜빡해도 `local`(SQLite/DEBUG)로 조용히 뜨는 사고 차단. (그래도 명시 입력 권장)
> - **`SECRET_KEY` 미설정 시 서버가 일부러 부팅 거부**(`prod.py` 가드, `ImproperlyConfigured`) → 데모키로 토큰 서명되는 사고 차단. **= SECRET_KEY는 필수.**
> - `inpa_be/.railwayignore`가 **로컬 `.env`(실제 키)·sqlite의 업로드를 차단** → 시크릿은 반드시 아래 Variables에 직접 입력.
> - `DEBUG`는 `prod.py`가 항상 `False`로 강제 → **별도 입력 불필요.**

**필수 (이게 없으면 서버가 안 뜨거나 FE↔BE 전면 차단):**

| Name (정확히) | Value 예시 | 설명 |
|---|---|---|
| `SECRET_KEY` | `<랜덤 50자 이상>` | Django 서명 키. **미설정 시 부팅 거부**. 아래 생성법 |
| `DATABASE_URL` | (c-2에서 참조로 자동) | MySQL 연결 문자열 |
| `ALLOWED_HOSTS` | `inpa-be.up.railway.app` | 콤마로 여러 개. 커스텀 도메인 생기면 추가 |
| `CSRF_TRUSTED_ORIGINS` | `https://inpa-be.up.railway.app` | https 포함 전체 URL. admin 로그인용 |
| `CORS_ALLOWED_ORIGINS` | `https://inpa-xxxx.vercel.app` | (b-4) 프론트 주소. https 포함, 와일드카드 ❌ |
| `DJANGO_SETTINGS_MODULE` | `config.settings.prod` | 코드가 이미 강제하나 명시 권장 |

**곧/선택 (없어도 서버는 뜸):**

| Name (정확히) | Value 예시 | 설명 |
|---|---|---|
| `ANTHROPIC_API_KEY` | `sk-ant-xxxx` | Claude 키(시크릿). `.railwayignore`로 .env 안 올라가니 **여기 직접 입력**. 비우면 OCR/AI만 비활성, 서버는 정상 |
| `FRONTEND_BASE_URL` | `https://inpa-xxxx.vercel.app` | 이메일 링크 생성용 (프론트 주소) |
| `EMAIL_BACKEND` | `django.core.mail.backends.smtp.EmailBackend` | 운영 이메일 발송 |
| `EMAIL_HOST` | `smtp.resend.com` | Resend SMTP |
| `EMAIL_PORT` | `465` | |
| `EMAIL_HOST_USER` | `resend` | Resend는 고정값 `resend` |
| `EMAIL_HOST_PASSWORD` | `re_xxxxxxxx` | Resend API 키 (시크릿) |
| `EMAIL_USE_SSL` | `True` | 465 포트는 SSL |
| `DEFAULT_FROM_EMAIL` | `noreply@inpa.kr` | 발신 주소 (도메인 인증 후) |
| `SENTRY_DSN` | `https://...@sentry.io/...` | 에러 관측(선택). 있으면 `prod.py`가 자동 init |

> **SECRET_KEY 생성법**: 터미널에서
> `python3 -c "import secrets; print(secrets.token_urlsafe(64))"`
> 출력된 문자열을 값으로 붙여넣기. (★ 채팅·문서에 남기지 말 것)

> **★ 비용 안전망 (필수 — 코드 밖 최후 방어선):** 셀프진단(`/d/<ref>`)은 무인증 공개 경로다. 코드에 throttle(IP 5건/시간)+refcode 일일상한(30)+5MB 제한을 넣었지만, **Anthropic 콘솔에서 월 spend limit + 사용량 알림**을 반드시 설정해 Claude 비용 폭주의 최종 상한을 건다. (베타는 `FREE_TIER_UNLIMITED=True`라 인증 사용자도 무차감 — 콘솔 상한이 유일한 비용 캡)

- **성공 신호**: 저장하면 Railway가 자동으로 재배포를 시작한다(Deployments 탭에 새 빌드).
- **흔한 오류**:
  - 배포가 `ImproperlyConfigured: SECRET_KEY ...`로 실패 → `SECRET_KEY` 미입력. 위 생성법으로 넣고 재배포.
  - 배포는 됐는데 502/접속 안 됨 → `ALLOWED_HOSTS`에 Railway 도메인이 빠짐. 표대로 추가.
  - FE에서 `CORS` 빨간 에러 → `CORS_ALLOWED_ORIGINS`에 정확한 Vercel 주소(https 포함).
  - `ANTHROPIC_API_KEY`를 비워도 서버는 뜬다(증권 OCR/AI만 비활성). 키는 나중에 넣어도 됨.

### c-4. 공개 도메인 켜기
1. BE 서비스 → **Settings** → **Networking** → **Generate Domain** 클릭.
2. 생기는 주소(`https://inpa-be.up.railway.app`)를 메모 = **BE 주소**.
3. 이 주소를 기준으로:
   - (b-3) Vercel `NEXT_PUBLIC_API_BASE` = `이 주소 + /api/v1` 로 **교체**(Vercel → Project → Settings → Environment Variables → 수정 후 **반드시 재배포** — 빌드타임 값이라 기존 빌드엔 반영 안 됨).
   - (c-3) `ALLOWED_HOSTS`·`CSRF_TRUSTED_ORIGINS`에 이 **BE 도메인**이, `CORS_ALLOWED_ORIGINS`에 실제 **Vercel 주소**가 들어갔는지 확인 후 BE 재배포.

---

## (d) 데이터베이스 마이그레이션 실행

> 빌드/시작 설정은 `inpa_be/railway.json`·`inpa_be/nixpacks.toml`에 이미 들어 있다.
> - **빌드**: `pip install -r requirements.txt` + 정적파일 수집(whitenoise)
> - **배포 직전(Pre-deploy)**: `python manage.py migrate --noinput` (railway.json의 `preDeployCommand`) → **테이블 자동 생성**
> - **시작**: `gunicorn config.wsgi:application --bind 0.0.0.0:$PORT`

### d-1. 기본 마이그레이션 (자동)
- (c-3) 환경변수 저장 후 재배포되면 **migrate가 자동 실행**되어 기본 테이블이 만들어진다.
- **확인**: Railway BE 서비스 → **Deployments** → 최신 배포 → **View Logs** → `Applying ... OK` 줄들이 보이면 성공.

### d-2. 초기 데이터 시드 (최초 1회 수동)
> 담보 표준 트리 + 보험사별 담보명 정규화 사전(v0)을 1회만 수동 주입. Railway 서비스 → 우측 상단 **점 3개(⋮)** → **Shell**(또는 `railway run`) 에서 실행.

```bash
python manage.py seed_normalization
```

- **성공 신호**: 에러 없이 종료 + `표준 담보(leaf) : 37개 / 정규화 사전 행수: 182행` 메시지.
- ⚠️ `seed_normalization`은 **v0 스타터**(약관 원문 대조 검증 전)다. 프로덕션 운영 전 도메인 검증 필요.
- ⚠️ `seed_demo`(데모 고객·보험 데이터)는 **운영 DB에서 실행 금지** — 로컬 시연 전용이다.
- (기준선 프리셋 시드는 컴플라이언스 게이트 확정 전까지 **실행 금지** — `dev/09`·`dev/10` 참고.)

### d-3. 관리자 계정 만들기 (admin 로그인용, 선택)
```bash
python manage.py createsuperuser
```
- 이메일·비밀번호 입력 → `https://<BE주소>/admin/` 에서 로그인 가능.

---

## (e) 동작 확인 (배포 검증)

> 아래 5개를 순서대로. 하나라도 실패하면 그 단계 "흔한 오류"를 본다.

### e-1. 백엔드 헬스체크
- 브라우저 주소창에 **`https://<BE주소>/healthz/`** 입력.
- **성공 신호**: `{"status": "ok", "service": "inpa-be"}` 가 보임.
- **prod로 떴는지 확인**: 개발자도구 Network에서 응답 헤더에 `Strict-Transport-Security`가 있으면 prod 설정으로 뜬 증거. 또 일부러 없는 URL(`/nope/`)을 열어 **상세 스택트레이스가 안 보이면** `DEBUG=False` 정상.
- 실패(502/타임아웃) → (c-3) `ALLOWED_HOSTS`·`DATABASE_URL` 점검, Deployments 로그 확인.

### e-2. 프론트 화면
- (b-4) Vercel 주소(`https://inpa-xxxx.vercel.app`) 접속 → 첫 화면이 뜨는지.
- 실패 → Vercel Deployments 로그 + Root Directory(`inpa_fe`) 확인.

### e-3. FE ↔ BE 통신 (CORS)
- 프론트에서 로그인/회원가입 등 데이터를 부르는 화면을 연다.
- 브라우저 **개발자도구(F12) → Console**에 `CORS` 빨간 에러가 없어야 한다.
- **Network 탭에서 API 요청이 Railway 도메인으로** 가는지 확인. `localhost:8000`으로 가면 Vercel `NEXT_PUBLIC_API_BASE` 미반영 → 값 입력 후 **재배포**. (콘솔에 "NEXT_PUBLIC_API_BASE 미설정" 경고도 뜸)
- 에러 있으면 → (c-3) `CORS_ALLOWED_ORIGINS`에 **정확한 프론트 주소(https 포함)**가 있는지 확인 후 BE 재배포.

### e-4. 회원가입 → 이메일 인증 (happy path)
1. 프론트에서 회원가입.
2. Resend 대시보드(또는 받은 메일함)에서 인증 메일 수신 확인 → 링크 클릭 → 로그인.
- 메일 안 옴 → (c-3) `EMAIL_*` 값·Resend 도메인 인증 점검.

### e-5. admin 접속
- `https://<BE주소>/admin/` → (d-3) 슈퍼유저로 로그인 → 데이터 조회.

---

## 부록 A. 시크릿 관리 원칙 (꼭 지키기)
- 비밀 값(`SECRET_KEY`, `EMAIL_HOST_PASSWORD`, `ANTHROPIC_API_KEY`, `DATABASE_URL`)은 **Vercel/Railway 대시보드 환경변수에만**.
- `.env` 파일은 로컬 개발 전용이며 **GitHub에 올라가지 않는다**(`.gitignore` 처리됨). 공유는 값 없는 `*.env.example`로.
- **`railway up`은 `.gitignore`가 아니라 `.railwayignore`를 본다** → `inpa_be/.railwayignore`에 `.env`를 넣어 실제 키 업로드를 차단해 둠. (대시보드 Variables가 정본)
- 키가 실수로 노출되면: **즉시 해당 플랫폼에서 키 재발급(로테이션)** → 환경변수 교체 → 재배포.

## 부록 B. 롤백 (문제 생기면 되돌리기)
- **FE(Vercel)**: 대시보드 → Deployments → 이전 정상 배포 → **Promote to Production**.
- **BE(Railway)**: 대시보드 → Deployments → 이전 정상 배포 → **Redeploy / Rollback**.
- DB 구조 변경(컬럼 삭제 등) 롤백은 코드 롤백과 별개 — 개발자 확인 필요(`dev/20` §7.2).

## 부록 C. 환경변수 한눈표 (어디에 무엇을)
| 변수 | 위치 | 시크릿? |
|---|---|---|
| `NEXT_PUBLIC_API_BASE` `NEXT_PUBLIC_SITE_URL` | Vercel | 공개 OK (빌드타임 인라인 — 변경 시 재배포) |
| `DJANGO_SETTINGS_MODULE` `ALLOWED_HOSTS` `CSRF_TRUSTED_ORIGINS` `CORS_ALLOWED_ORIGINS` `FRONTEND_BASE_URL` `EMAIL_HOST` `EMAIL_PORT` `EMAIL_HOST_USER` `EMAIL_USE_SSL` `DEFAULT_FROM_EMAIL` `SENTRY_DSN` | Railway | 공개 OK |
| `SECRET_KEY` `DATABASE_URL` `EMAIL_HOST_PASSWORD` `ANTHROPIC_API_KEY` | Railway | **시크릿** |

> `DEBUG`는 `config.settings.prod`가 항상 `False`로 강제 → 환경변수 불필요. `DJANGO_SETTINGS_MODULE`도 `railway.json`/`nixpacks.toml`이 prod로 강제(명시 권장).

---

*관련 문서: `dev/20-devops-and-deploy.md`(정본 아키텍처) · `dev/11-auth-onboarding.md`(인증) · `dev/09-compliance-broker-line.md`(컴플라이언스 게이트).*
