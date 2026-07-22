# 인파(Inpa) — 배포 실전 가이드 (PM·비개발자용)

> **문서 ID**: `dev/25-deploy-guide.md`
> **작성일**: 2026-06-19
> **대상 독자**: PM(대표, 비개발자) — 마우스 클릭만으로 따라 할 수 있게 작성.
> **정본 아키텍처**: `dev/20-devops-and-deploy.md` (이 문서는 그 실행판이다.)
> **현재 배포 그림(월 $7 + 사용량)**: FE = Vercel / Render 작업공간 = Hobby 무료 / BE = Render Starter($7/월) / DB = Neon 무료 PostgreSQL / CI = GitHub Actions(검증만).
> **갱신(2026-07-22)**: `inpa-be`를 Starter 상시 가동으로 전환했고 배포 `Live`와 `/healthz/` 정상 응답을 확인했다. DB는 PostgreSQL, 로컬은 SQLite를 유지한다.

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

- **시크릿(비밀번호·API 키)은 코드에 절대 안 넣는다.** 항상 Vercel·Render·Neon 대시보드의 "환경변수"에 넣는다.
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
> **Environment Variables** 섹션에서 아래를 추가. (BE 주소는 (c) 단계에서 Render 배포 후 확정되므로, 우선 임시로 넣고 (c) 끝나면 교체한다.)

| Name | Value 예시 | 비고 |
|---|---|---|
| `NEXT_PUBLIC_API_BASE` | `https://inpa-be.onrender.com/api/v1` | Render BE 주소 + `/api/v1`. (c)에서 확정 후 교체 |

- `NEXT_PUBLIC_`로 시작하는 값은 브라우저에 공개되어도 되는 값만 넣는다. **API 키·비밀번호는 절대 여기 넣지 않는다.**
- 참고 양식: `inpa_fe/.env.production.example`.

### b-4. 배포
1. **Deploy** 클릭 → 1~3분 대기.
2. **성공 신호**: "Congratulations" 화면 + `https://inpa-xxxx.vercel.app` 주소 생성. 그 주소를 메모(=프론트 도메인).
3. **흔한 오류**:
   - 빌드 실패 + `No Next.js version detected` → Root Directory를 `inpa_fe`로 안 잡은 것. b-2 다시.
   - 화면은 뜨는데 데이터가 안 옴 → `NEXT_PUBLIC_API_BASE`가 틀렸거나 (c)의 CORS 미설정. (e)에서 점검.

---

## (c) Neon(무료 DB) + Render Starter(BE) 연결

> **현재 조합 (월 $7 + 사용량)**: DB = **Neon**(무료 PostgreSQL) / Render 작업공간 = **Hobby 무료** / BE = **Starter $7/월**.
> Starter는 유휴 절전 대상이 아니므로 고객의 첫 접속이 무료 인스턴스 기동을 기다리지 않는다.

### c-1. Neon에서 무료 PostgreSQL 만들기
1. https://neon.tech → **GitHub로 로그인** → **Create project** (이름 `inpa`, 리전은 Render와 가깝게 **US West(Oregon)** 권장).
2. 생성되면 **Connection string** 복사 = **`DATABASE_URL`**.
   - 형식: `postgresql://user:pass@...neon.tech/dbname?sslmode=require`
   - "Pooled connection"(풀링) 문자열이 보이면 그걸 복사(서버리스에 유리).

### c-2. Render에 백엔드 배포 (Blueprint)
1. https://render.com → **GitHub로 로그인**.
2. **New → Blueprint** → `inpa` 저장소 선택. 저장소 루트의 **`render.yaml`**을 Render가 자동 인식(서비스 `inpa-be`, Root `inpa_be`, Starter 플랜, 빌드·시작·헬스체크 전부 정의됨).
   - (Blueprint가 안 보이면 **New → Web Service** → repo 선택 → **Root Directory `inpa_be`** 지정 → Build/Start 명령은 `render.yaml` 내용 그대로 입력.)
3. 생성 중 **sync:false 변수 입력 창**이 뜨면 아래 (c-3) 값을 넣고 **Apply**.

### c-3. 환경변수 (대부분 `render.yaml`이 자동 — 아래만 직접 입력)

> **★ 코드/Blueprint가 이미 처리하는 것 (손댈 필요 없음):**
> - `render.yaml`이 **`DJANGO_SETTINGS_MODULE=config.settings.prod`·빌드·시작·헬스체크**를 정의.
> - **`SECRET_KEY`는 Render가 자동 생성**(`generateValue`) → 직접 만들 필요 없음. (미설정 시 `prod.py` 가드가 부팅 거부 = 데모키 사고 차단)
> - **`ALLOWED_HOSTS`·`CSRF`는 Render 도메인을 코드가 자동 포함**(`RENDER_EXTERNAL_HOSTNAME`) → 커스텀 도메인 안 쓰면 입력 불필요.
> - **`DEBUG`는 항상 `False`** 강제. **`.env`는 git 미추적**이라 업로드 안 됨(시크릿은 아래에만).

**직접 입력할 변수 (Blueprint의 `sync:false`):**

| Name | Value | 설명 |
|---|---|---|
| `DATABASE_URL` | (c-1 Neon 문자열) | **필수**. `postgresql://...neon.tech/...?sslmode=require` |
| `CORS_ALLOWED_ORIGINS` | `https://<vercel-도메인>` | **필수**. 프론트 주소, https 포함, 와일드카드 ❌ |
| `ANTHROPIC_API_KEY` | `sk-ant-...` | 선택이지만 OCR/AI를 쓰면 **필수**. 비우면 OCR/AI 호출이 **503**(서버 자체는 정상) |
| `FRONTEND_BASE_URL` | `https://<vercel-도메인>` | ⚠️ **준필수**. 미설정 시 기본값 `http://localhost:3000` → 이메일 인증·고객 동의(`/c`)·예약(`/b`) 링크가 전부 localhost로 생성돼 **실서비스에서 안 열림**. 운영이면 반드시 Vercel 주소로 설정 |
| `EMAIL_*` (7종) | Resend 값 | 선택. 가입/비번 메일용 — 부록 C 표 참고 |
| `SENTRY_DSN` | `https://...@sentry.io/...` | 선택. 있으면 `prod.py`가 자동 init |
| **기능·컴플라이언스 플래그** | (대개 미설정 = 안전 기본값) | `FREE_TIER_UNLIMITED`(기본 **True** = 베타 무제한, 끄면 402 한도 발동) · `COMPARE_AI_ENABLED`·`COMPARE_PUBLISH_ENABLED`(§97)·`ANALYZE_MEDICAL_ENABLED`(병력) = 기본 **False**(닫힘 — 법무 검토 전까지 유지) · `BOOKING_ENABLED`(기본 True) · `GOOGLE_OAUTH_*`(미설정 = 구글 기능 숨김). **컴플라이언스 게이트는 정식 출시·법무 검토 후에만 flip** |

> **커스텀 도메인**을 붙이면 그때 `ALLOWED_HOSTS`·`CSRF_TRUSTED_ORIGINS`에 그 도메인을 추가한다.

> **★ 비용 안전망 (필수 — 코드 밖 최후 방어선):** 셀프진단(`/d/<ref>`)은 무인증 공개 경로다. 코드에 throttle(IP 5건/시간)+refcode 일일상한(30)+5MB 제한을 넣었지만, **Anthropic 콘솔에서 월 spend limit + 사용량 알림**을 반드시 설정해 Claude 비용 폭주의 최종 상한을 건다. (베타는 `FREE_TIER_UNLIMITED=True`라 인증 사용자도 무차감 — 콘솔 상한이 유일한 비용 캡)

- **성공 신호**: Render 서비스 → **Logs**에 `Applying ... OK`(마이그레이션) → `Booting worker`(gunicorn) → 헬스체크 통과(초록 Live).
- **흔한 오류**:
  - 빌드 `ImproperlyConfigured: SECRET_KEY` → `generateValue`가 안 먹은 경우, Variables에 SECRET_KEY 수동값 입력.
  - DB 연결 실패 → `DATABASE_URL`이 Neon 문자열인지, 끝에 `?sslmode=require` 있는지 확인.
  - FE에서 `CORS` 빨간 에러 → `CORS_ALLOWED_ORIGINS`에 정확한 Vercel 주소(https 포함).
  - `ANTHROPIC_API_KEY`를 비워도 서버는 뜬다(증권 OCR/AI만 비활성). 키는 나중에 넣어도 됨.

### c-4. 도메인 확정 후 연결
1. Render 서비스 상단 주소 **`https://inpa-be.onrender.com`** = **BE 주소**.
2. **Vercel** `NEXT_PUBLIC_API_BASE` = `이 주소 + /api/v1` 로 **교체 후 반드시 재배포**(빌드타임 값이라 기존 빌드엔 반영 안 됨).
3. Render `CORS_ALLOWED_ORIGINS`에 실제 Vercel 주소가 있는지 확인. (`ALLOWED_HOSTS`는 코드가 Render 도메인 자동 포함)

---

## (d) 데이터베이스 마이그레이션 실행

> 빌드/시작 설정은 저장소 루트의 **`render.yaml`**에 이미 들어 있다.
> - **빌드**: `pip install -r requirements.txt` + 정적파일 수집(whitenoise, 빌드용 더미 키 주입)
> - **시작**: `python manage.py migrate --noinput` (테이블 자동 생성) → `gunicorn config.wsgi:application`

### d-1. 기본 마이그레이션 (자동)
- 환경변수 저장 후 배포되면 **시작 시 migrate가 자동 실행**되어 Neon에 테이블이 만들어진다.
- **확인**: Render BE 서비스 → **Logs** → `Applying ... OK` 줄들이 보이면 성공.

### d-2. 초기 데이터 시드 (최초 1회 수동)
> 담보 표준 트리 + 보험사별 담보명 정규화 사전(v0)을 1회만 수동 주입. Render Starter 서비스의 **Shell** 탭에서 실행한다.

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
- **Network 탭에서 API 요청이 Render(onrender.com) 도메인으로** 가는지 확인. `localhost:8000`으로 가면 Vercel `NEXT_PUBLIC_API_BASE` 미반영 → 값 입력 후 **재배포**. (콘솔에 "NEXT_PUBLIC_API_BASE 미설정" 경고도 뜸)
- 에러 있으면 → (c-3) `CORS_ALLOWED_ORIGINS`에 **정확한 프론트 주소(https 포함)**가 있는지 확인 후 BE 재배포.

### e-4. 회원가입 → 이메일 인증 (happy path)
1. 프론트에서 회원가입.
2. Resend 대시보드(또는 받은 메일함)에서 인증 메일 수신 확인 → 링크 클릭 → 로그인.
- 메일 안 옴 → (c-3) `EMAIL_*` 값·Resend 도메인 인증 점검.

### e-5. admin 접속
- `https://<BE주소>/admin/` → (d-3) 슈퍼유저로 로그인 → 데이터 조회.

---

## 부록 A. 시크릿 관리 원칙 (꼭 지키기)
- 비밀 값(`SECRET_KEY`, `EMAIL_HOST_PASSWORD`, `ANTHROPIC_API_KEY`, `DATABASE_URL`)은 **Vercel/Render/Neon 대시보드 환경변수에만**.
- `.env` 파일은 로컬 개발 전용이며 **GitHub에 올라가지 않는다**(`.gitignore` 처리됨). 공유는 값 없는 `*.env.example`로. (Render는 git 저장소만 빌드하므로 `.env`가 올라갈 일이 없음 — `.railwayignore`/`.dockerignore`도 함께 둬서 어떤 빌더에서도 안전.)
- 키가 실수로 노출되면: **즉시 해당 플랫폼에서 키 재발급(로테이션)** → 환경변수 교체 → 재배포.

## 부록 B. 롤백 (문제 생기면 되돌리기)
- **FE(Vercel)**: 대시보드 → Deployments → 이전 정상 배포 → **Promote to Production**.
- **BE(Render)**: 대시보드 → 서비스 → **Deploys** → 이전 정상 배포 → **Rollback to this deploy**.
- DB 구조 변경(컬럼 삭제 등) 롤백은 코드 롤백과 별개 — 개발자 확인 필요(`dev/20` §7.2).

## 부록 C. 환경변수 한눈표 (어디에 무엇을)
| 변수 | 위치 | 시크릿? |
|---|---|---|
| `NEXT_PUBLIC_API_BASE` `NEXT_PUBLIC_SITE_URL` | Vercel | 공개 OK (빌드타임 인라인 — 변경 시 재배포) |
| `DJANGO_SETTINGS_MODULE` `CORS_ALLOWED_ORIGINS` `FRONTEND_BASE_URL` `EMAIL_HOST` `EMAIL_PORT` `EMAIL_HOST_USER` `EMAIL_USE_SSL` `DEFAULT_FROM_EMAIL` `SENTRY_DSN` | Render | 공개 OK |
| `SECRET_KEY`(자동생성) `DATABASE_URL`(Neon) `EMAIL_HOST_PASSWORD` `ANTHROPIC_API_KEY` | Render | **시크릿** |

> `DEBUG`는 `config.settings.prod`가 항상 `False`로 강제 → 불필요. `DJANGO_SETTINGS_MODULE`·빌드·시작은 `render.yaml`이 정의. `ALLOWED_HOSTS`·`CSRF`는 Render 도메인 자동 포함(`RENDER_EXTERNAL_HOSTNAME`).

---

*관련 문서: `dev/20-devops-and-deploy.md`(정본 아키텍처) · `dev/11-auth-onboarding.md`(인증) · `dev/09-compliance-broker-line.md`(컴플라이언스 게이트).*
