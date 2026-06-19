# 인파(Inpa) — 시스템 아키텍처 & 스택

> 문서 ID: `dev/01-architecture-and-stack.md`
> 최종 갱신: 2026-06-19 (이메일/비밀번호 인증 전환, Next.js+Tailwind 스택 확정)
> 대상 독자: PM(의사결정), 디자이너(가시성·UX 게이트), 개발자(포팅·구현 지도)
> 제품명: **인파(Inpa)** — 위촉직 보험설계사의 AI 영업 파트너
> 핵심 전제: foliio 코드 **vendoring(재사용)**. 인파 = 새 시스템이 아니라 검증 자산을 옮기는 작업.
> 모든 추정 수치에는 `(추정)` 라벨을 명시한다.

---

## 0. 한 문단 요약

인파는 foliio(보험 포트폴리오 분석 SaaS)의 검증된 파이프라인을 **그대로 들고 와** 영업 OS로 정체성을 바꾼 제품이다. 기술 리스크는 신규 4개 모듈(담보 정규화·히트맵·가드레일·만기 워치독)과 법무 게이트 1개에 국한된다.

**2026-06-19 확정 스택 변경:**
- **FE: Angular 17 → Next.js 16 + TypeScript + Tailwind v4** (Claude Code 개발 속도 + 디자인 토큰 매핑 유리)
- **인증: 카카오 OAuth → 이메일/비밀번호 전용** (카카오 의존성 제거, 표준 이메일 인증 흐름)
- BE·DB·AI는 foliio 자산 그대로 — Django 4.1 + DRF + MariaDB + Claude API

---

## 1. 시스템 아키텍처 다이어그램

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          사용자 (설계사 / 고객)                              │
│                                                                            │
│   설계사 앱뷰                          고객 공유뷰 (헤더·탭 숨김)             │
│   /home /customers /analysis ...       /s/:token  /check/:token            │
└───────────────┬──────────────────────────────────┬─────────────────────────┘
                │ HTTPS                              │ HTTPS
                ▼                                    ▼
        ┌───────────────────────────────────────────────────┐
        │   Next.js 16 (App Router, RSC + Client)             │
        │   TypeScript 5 / Tailwind v4 / React 19             │
        │   - /app/  (App Router, 서버 컴포넌트 기본)           │
        │   - /components/  (공통 UI 컴포넌트)                  │
        │   - /lib/  (API 클라이언트, 유틸)                     │
        │   - share_token 공개뷰 (인증 우회, 토큰 검증만)        │
        └───────────────────────┬───────────────────────────┘
                                │  /api/v1/*
                                ▼
                        ┌───────────────┐
                        │     nginx     │  SSL 종단 / Next.js 빌드 서빙 / 미디어
                        │   (IDC 서버)   │  /api/v1/ → 127.0.0.1:8000 (Django)
                        └───────┬───────┘
                                │  127.0.0.1:8000
                                ▼
        ┌───────────────────────────────────────────────────┐
        │   gunicorn → Django 4.1.13 + DRF 3.14             │
        │   (conda env: inpa / systemd: inpa.service)       │
        │                                                    │
        │   ┌─────────────┐  ┌──────────────┐  ┌─────────┐  │
        │   │ detect API  │  │ analysis API │  │ ai API  │  │
        │   │ (♻+정규화)   │  │ (♻ 8케이스)   │  │ (✦신규)  │  │
        │   └──────┬──────┘  └──────────────┘  └────┬────┘  │
        │          │                                 │       │
        │   ┌──────▼───────────── 게이트 ────────────▼─────┐  │
        │   │ consent_overseas_at 확인 → 미동의 412        │  │  ← 병력 국외이전 동의
        │   └──────┬───────────────────────────────┬──────┘  │     (모든 AI 기능의 관문)
        └──────────┼───────────────────────────────┼─────────┘
                   │                               │
        ┌──────────▼──────────┐         ┌──────────▼──────────┐
        │  PDF 텍스트 추출      │         │   Claude API (US)   │
        │  pdfplumber → PyMuPDF│         │   Anthropic, Inc.   │  ← 국외이전 대상
        │  (암호화 authenticate)│         │   M1=Opus / M2~=Haiku│
        └─────────────────────┘         └─────────────────────┘
                   │
        ┌──────────▼──────────────────────────────────────────┐
        │   MariaDB 10.3.39  (inpa_db, 127.0.0.1:3306)        │
        │   utf8mb4_unicode_ci / 일일 백업 cron                 │
        │   User·Profile·Customer·CustomerInsurance            │
        │   AnalysisCategory~ChartDetail(4계층)·ConsentLog     │
        │   NormalizationDict (데이터 복리 해자)                 │
        └─────────────────────────────────────────────────────┘
                   ▲
        ┌──────────┴──────────┐
        │  numpy_financial.fv │  갱신보험료 미래가치 (8케이스 中 4·8)
        └─────────────────────┘
```

---

## 2. 확정 기술 결정

| 항목 | 결정 | 이유 |
|---|---|---|
| **FE** | **Next.js 16 + TypeScript 5 + Tailwind v4** | Claude Code 개발 속도 · App Router RSC = API 라운드트립 최소화 · 디자인 토큰 CSS변수 → Tailwind `@theme inline` 매핑 자연스러움 |
| **인증** | **이메일/비밀번호 전용** (카카오 OAuth 전면 제거) | 카카오 콘솔 운영 의존성 제거 · 표준 이메일 인증 흐름 = 법무·운영 단순화 |
| **BE** | Django 4.1.13 + DRF 3.14.0 (Python 3.8) | foliio BE 전체 vendoring. settings 분리 패턴(`local`/`idc`) 승계. |
| **DB** | **MariaDB 10.3.39 유지** (PostgreSQL 전환 보류) | 포팅 비용 0. foliio 검증 자산 승계. 정규화 사전은 관계형으로 충분. |
| **AI** | Anthropic Claude API (`anthropic` SDK) | foliio `claude_parser.py` vendoring. 모델 라우팅 Opus/Haiku 분기. |
| **재무계산** | `numpy_financial.fv` | 8케이스 골든테스트로 검증된 로직. 무변경. |
| **OCR** | pdfplumber 1순위 → PyMuPDF 폴백 | foliio `core/utils.py` 무변경 vendoring. 암호화 PDF `authenticate` 경로 보존. |
| **디자인 시스템** | `design/tokens/inpa-tokens.css` → Tailwind v4 `@theme inline` | CSS 변수 단일 진실 공급원(SSOT). FE globals.css에 이미 적용 완료. |

---

## 3. 프로젝트 폴더 구조

### 3.1 백엔드 (inpa_be)

```
inpa_be/
├── config/
│   ├── settings/
│   │   ├── base.py           # 공통 설정
│   │   ├── local.py          # 로컬 개발 (DEBUG=True, SQLite or local MariaDB)
│   │   └── idc.py            # 프로덕션 (DEBUG=False, IDC MariaDB, CORS whitelist)
│   ├── urls.py
│   └── wsgi.py
│
├── accounts/                  # 인증·사용자 (★ 이메일/비밀번호 신규)
│   ├── models.py              # User (CustomUser), Profile (OneToOne)
│   ├── serializers.py         # RegisterSerializer, LoginSerializer, PasswordResetSerializer
│   ├── views.py               # RegisterView, LoginView, LogoutView, PasswordResetRequest/Confirm
│   ├── tokens.py              # 이메일 인증 토큰 / 비밀번호 재설정 토큰 유틸
│   ├── emails.py              # 이메일 발송 (Django send_mail)
│   ├── permissions.py         # IsOwner (★ 멀티테넌시 핵심)
│   ├── mixins.py              # OwnedQuerySetMixin (★ 멀티테넌시 핵심)
│   └── migrations/
│
├── customers/                 # 고객 관리 (foliio ♻)
│   ├── models.py              # Customer (+consent_overseas_at), CustomerMedicalHistory
│   ├── views.py               # CustomerViewSet (OwnedQuerySetMixin 상속 필수)
│   ├── calculate.py           # ★ foliio vendoring — calculate_total_analysis (weapon→inpa)
│   ├── heatmap.py             # ✦ 신규 — 3색 판정
│   └── migrations/
│
├── insurances/                # 보험·담보 (foliio ♻)
│   ├── models.py              # CustomerInsurance, CustomerInsuranceDetail, AnalysisCategory 4계층
│   │                          #   + NormalizationDict (✦ 신규), UnmatchedLog (✦ 신규)
│   ├── views.py               # detect, detect_batch, analysis, compare
│   ├── normalization.py       # ✦ 신규 — 정규화 사전 lookup 엔진
│   └── migrations/
│
├── core/                      # 공통 유틸 (foliio ♻)
│   ├── utils.py               # ★ foliio vendoring — extract_text_from_pdf (weapon→inpa)
│   ├── ocr/
│   │   └── claude_parser.py   # ★ foliio vendoring — claude_parse, _add_coverage (weapon→inpa, ◑ 개조)
│   └── ai_guardrail.py        # ✦ 신규 — 보험업법 룰셋 판정
│
├── ai/                        # AI 라우팅 (✦ 신규)
│   ├── views.py               # message/, guardrail_check/
│   └── message_prompts.py     # 목적 enum별 프롬프트
│
├── membership/                # 크레딧·요금제 (foliio ♻)
│   ├── models.py              # Membership, UserMembership
│   └── credit.py              # ★ foliio vendoring — _check_and_consume (+ai kind)
│
├── community/                 # 게시판·공지·FAQ (★ 공유 가시성)
│   ├── models.py              # Post, Comment, Notice, FAQ
│   └── views.py               # 전체 공개 읽기 / 작성자만 수정
│
├── notifications/             # 알림·리마인더 (foliio ♻ + 신규 type)
│   └── models.py
│
├── management/
│   └── commands/
│       ├── seed_taxonomy.py   # ✦ 100+ 담보 + 정규화 사전 시드
│       └── watchdog.py        # ✦ 만기·갱신 일배치 cron
│
├── requirements.txt           # foliio와 동일 시작 (신규 의존성 0개)
├── .env.example               # ★ 환경변수 템플릿 (아래 §4 참조)
└── manage.py
```

### 3.2 프론트엔드 (inpa_fe)

```
inpa_fe/                       # Next.js 16 + TypeScript + Tailwind v4
├── app/                       # App Router (서버 컴포넌트 기본)
│   ├── layout.tsx             # 루트 레이아웃 (폰트·글로벌 CSS 임포트)
│   ├── globals.css            # ★ 디자인 토큰 CSS변수 + Tailwind @theme inline 매핑 (완료)
│   ├── page.tsx               # 루트 → /login 리다이렉트
│   │
│   ├── (auth)/                # 인증 라우트 그룹 (레이아웃 분리)
│   │   ├── login/             # /login — 이메일/비밀번호 로그인
│   │   ├── register/          # /register — 회원가입 + 약관 동의 통합
│   │   ├── verify-email/      # /verify-email?token= — 이메일 인증
│   │   ├── forgot-password/   # /forgot-password — 비밀번호 찾기 이메일 입력
│   │   └── reset-password/    # /reset-password?token= — 비밀번호 재설정
│   │
│   ├── (app)/                 # 앱 라우트 그룹 (인증 + 온보딩 완료 가드)
│   │   ├── home/              # /home — 대시보드
│   │   ├── customers/         # /customers — 고객 목록
│   │   │   └── [id]/          # /customers/[id] — 고객 상세
│   │   │       ├── analysis/  # 보장 분석 / 히트맵
│   │   │       └── compare/   # 갈아타기 비교안내서
│   │   ├── calendar/          # /calendar — 캘린더
│   │   ├── community/         # /community — 게시판 SNS 피드
│   │   ├── promotions/        # /promotions — 판촉물 카탈로그
│   │   └── settings/          # /settings — 내 계정·요금제
│   │
│   ├── onboarding/            # /onboarding — 약관·위촉·콜드스타트 3단계
│   │
│   └── s/[token]/             # /s/:token — 고객 공유뷰 (인증 불필요)
│
├── components/
│   ├── ui.tsx                 # 공통 UI 원자 컴포넌트 (Button, Input, Card, Badge, Modal 등)
│   ├── app-nav.tsx            # 사이드바/탭 네비게이션
│   ├── auth/                  # 인증 전용 컴포넌트
│   │   ├── LoginForm.tsx
│   │   ├── RegisterForm.tsx
│   │   └── PasswordResetForm.tsx
│   ├── customers/             # 고객 관련 컴포넌트
│   │   ├── CustomerCard.tsx
│   │   ├── HeatmapGrid.tsx    # 담보 한눈표 3색
│   │   └── ColdStartCard.tsx  # 빈 상태 단일 CTA
│   └── shared/
│       ├── DisclaimerBadge.tsx # "AI 초안·최종책임 설계사" 면책 고정 컴포넌트
│       └── ComplianceGate.tsx  # 컴플라이언스 차단 UX
│
├── lib/
│   ├── api.ts                 # API 클라이언트 (fetch wrapper, 에러 처리)
│   ├── auth.ts                # 토큰 저장·갱신 유틸 (localStorage → httpOnly cookie 검토)
│   └── mock.ts                # 개발용 mock 데이터 (현재 존재)
│
├── public/
│   └── fonts/                 # Pretendard Variable
│
├── design/ -> ../../design/   # 디자인 토큰 (symlink 또는 복사)
│
├── next.config.ts
├── tailwind.config.ts         # (필요 시 추가 — v4는 CSS-first)
├── tsconfig.json
└── package.json               # next 16, react 19, tailwind v4
```

---

## 4. 환경변수 (.env.example)

`.env` 는 `.gitignore`에 반드시 포함. 실제 값은 절대 커밋 금지.

### 4.1 백엔드 (.env — inpa_be/)

```bash
# ── Django ──
SECRET_KEY=changeme-long-random-string
DJANGO_SETTINGS_MODULE=config.settings.local    # 로컬: local / 프로덕션: idc (명시 필수)
DEBUG=True                                       # 프로덕션: False

# ── DB (MariaDB) ──
DJANGO_DEFAULT_DATABASE_HOST=127.0.0.1
DJANGO_DEFAULT_DATABASE_PORT=3306
DJANGO_DEFAULT_DATABASE_NAME=inpa_db
DJANGO_DEFAULT_DATABASE_USER=inpa_user
DJANGO_DEFAULT_DATABASE_PASSWORD=changeme

# ── AI ──
CLAUDE_API_KEY=sk-ant-api-...                   # Anthropic API 키 — 절대 FE로 노출 금지
CLAUDE_MODEL_M1=claude-opus-4-8                 # 비교안내서·정규화 (정확도 critical)
CLAUDE_MODEL_M2=claude-haiku-4-5                # 다건 OCR·메시지 (원가 최적화)

# ── 이메일 (Django send_mail) ──
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com                        # 또는 AWS SES
EMAIL_PORT=587
EMAIL_HOST_USER=noreply@inpa.kr
EMAIL_HOST_PASSWORD=changeme
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=인파 <noreply@inpa.kr>

# ── 인증 토큰 ──
EMAIL_VERIFY_TOKEN_TTL_HOURS=24                  # 이메일 인증 링크 유효시간
PASSWORD_RESET_TOKEN_TTL_HOURS=1                 # 비밀번호 재설정 링크 유효시간

# ── 운영 제어 ──
FREE_TIER_UNLIMITED=True                         # 베타 크레딧 무제한 (정식 출시 시 False)
SUPER_BETA_EXPIRY=2099-12-31

# ── CORS ──
CORS_ALLOWED_ORIGINS=http://localhost:3000,https://inpa.kr
```

### 4.2 프론트엔드 (.env.local — inpa_fe/)

```bash
# ── API ──
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000    # 로컬 BE 주소
# 프로덕션: NEXT_PUBLIC_API_BASE_URL=https://api.inpa.kr

# ★ NEXT_PUBLIC_* 는 브라우저에 노출됨 — API 키·시크릿 절대 금지
# CLAUDE_API_KEY 같은 값은 BE 전용 .env에만
```

---

## 5. 디자인 시스템 — 토큰 → Tailwind v4 매핑

### 5.1 CSS변수 단일 진실 공급원 (SSOT)

디자인 토큰은 `design/tokens/inpa-tokens.css`가 정본이다. FE의 `app/globals.css`에서 이 변수들을 임포트하고, Tailwind v4의 `@theme inline` 블록으로 CSS 유틸리티 클래스로 매핑한다.

**이미 `inpa_fe/app/globals.css`에 구현 완료된 내용:**

| CSS 변수 (`:root`) | Tailwind 클래스 | 용도 |
|---|---|---|
| `--brand: #1E40C4` | `text-brand`, `bg-brand`, `border-brand` | 1차 CTA·헤더·로고 |
| `--brand-ink: #1B2A57` | `text-brand-ink`, `bg-brand-ink` | 푸터·신뢰 앵커 |
| `--accent-blue: #3182F6` | `text-accent`, `bg-accent` | 강조 숫자·진행바·링크 |
| `--accent-tint: #EAF2FE` | `bg-accent-tint` | 강조 배경 틴트 |
| `--proposal: #3B5BDB` | `text-proposal`, `bg-proposal` | 제안 컬럼 (히트맵·비교표 전용) |
| `--existing: #12B5A4` | `text-existing`, `bg-existing` | 기존 보유 컬럼 |
| `--cov-enough` | `bg-enough` | 히트맵: 충분 |
| `--cov-short` | `bg-short` | 히트맵: 부족 |
| `--cov-none` | `bg-cnone` | 히트맵: 없음 |
| `--danger: #E03131` | `text-danger`, `bg-danger` | 해지손해·§97 경고 |
| `--ink: #16181D` | `text-ink` | 기본 텍스트 |
| `--surface: #FFFFFF` | `bg-surface` | 카드 배경 |
| `--surface-2: #F7F8FA` | `bg-surface2` | 페이지 배경 |
| `--line: #E5E8EB` | `border-line` | 구분선 |

다크모드: `@media (prefers-color-scheme: dark)` 에서 CSS 변수만 교체. Tailwind 클래스는 동일하게 사용.

### 5.2 블루 3종 역할 분리 (엄수)

⚠️ 같은 파란색처럼 보여도 **역할이 다른 3개**다. 한 요소에 교차 적용 금지.

| 토큰 | 역할 | 사용 위치 |
|---|---|---|
| `--brand` (`text-brand`) | 브랜드 CTA · 헤더 | 로고, 주요 버튼 |
| `--accent-blue` (`text-accent`) | 강조·인사이트 | 강조 숫자, 링크, 진행바 |
| `--proposal` (`bg-proposal`) | 데이터 시각화 | 히트맵·비교표 제안 컬럼 **전용** |

### 5.3 폰트

```css
font-family: 'Pretendard Variable', Pretendard, -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
```

Pretendard Variable은 `public/fonts/`에 로컬 호스팅. CDN 의존성 없음.

---

## 6. 공통 컴포넌트 목록

`components/ui.tsx`에 원자 단위 컴포넌트를 집약한다. 지금 존재하는 파일을 기반으로 확장.

### 6.1 원자 UI (ui.tsx)

| 컴포넌트 | Props 핵심 | 용도 |
|---|---|---|
| `<Button>` | `variant(primary/secondary/ghost/danger)`, `size`, `loading` | 전체 CTA |
| `<Input>` | `type`, `error`, `label`, `hint` | 폼 입력 |
| `<Card>` | `padding`, `shadow` | 섹션 래퍼 |
| `<Badge>` | `color(brand/success/warning/danger/neutral)` | 상태 표시 |
| `<Modal>` | `open`, `onClose`, `title` | 다이얼로그 |
| `<Toast>` | `type`, `message` | 인라인 피드백 |
| `<Spinner>` | `size` | 로딩 |
| `<EmptyState>` | `title`, `cta`, `ctaHref` | 빈 상태 (콜드스타트) |

### 6.2 레이아웃 (app-nav.tsx)

| 컴포넌트 | 역할 |
|---|---|
| `<AppNav>` | 사이드바 (데스크탑) / 하단 탭바 (모바일) |
| `<ShareViewLayout>` | 고객 공유뷰 전용 레이아웃 (헤더·탭 숨김) |
| `<AuthLayout>` | 인증 화면 전용 레이아웃 (센터 카드) |

### 6.3 도메인 컴포넌트

| 컴포넌트 | 파일 | 역할 |
|---|---|---|
| `<DisclaimerBadge>` | `shared/DisclaimerBadge.tsx` | "AI 초안·최종책임 설계사" 면책 — **AI 생성물에 반드시 포함** |
| `<ComplianceGate>` | `shared/ComplianceGate.tsx` | 컴플라이언스 미충족 시 화면 차단 UX |
| `<HeatmapGrid>` | `customers/HeatmapGrid.tsx` | 담보 한눈표 3색 그리드 |
| `<ColdStartCard>` | `customers/ColdStartCard.tsx` | 빈 상태 단일 CTA (`/customers/create`로 수렴) |
| `<ConsentOverseasModal>` | `customers/ConsentOverseasModal.tsx` | 고객 국외이전 동의 수집 모달 (detect 412 트리거) |

**정직성 레드라인:** `DisclaimerBadge`는 AI 생성 콘텐츠(비교안내서·카톡 메시지) 어디에도 빠지면 안 된다. "심의완료/안전" 배지는 절대 만들지 않는다.

---

## 7. 인증 코어 — 이메일/비밀번호 전용

### 7.1 인증 흐름 전체 (ASCII)

```
[회원가입]
설계사 → /register (이메일·비밀번호·약관 동의 통합 폼)
              │
              ▼
         [BE] 이메일 중복 확인 → User 생성(is_active=False) → 이메일 인증 발송
              │
              ▼
         [이메일] "인파 가입 인증" 링크 (토큰 24h TTL)
              │
              ▼
         /verify-email?token=<TOKEN>
              │
              ▼
         [BE] 토큰 검증 → is_active=True → 온보딩 라우팅

[로그인]
설계사 → /login (이메일·비밀번호)
              │
              ▼
         [BE] 이메일/비밀번호 검증 → is_active 확인 → Token(DRF) 발급
              │
              ▼
         [FE] Token 저장 → /home 또는 /onboarding (onboarding_completed_at IS NULL)

[비밀번호 찾기]
설계사 → /forgot-password (이메일 입력)
              │
              ▼
         [BE] 이메일 존재 확인 → 재설정 토큰 발급 → 이메일 발송 (1h TTL)
              │
              ▼
         [이메일] "비밀번호 재설정" 링크
              │
              ▼
         /reset-password?token=<TOKEN> (새 비밀번호 입력)
              │
              ▼
         [BE] 토큰 검증(만료·1회용) → 비밀번호 교체 → Token 폐기 (모든 세션 강제 로그아웃)
```

### 7.2 비밀번호 해시 — bcrypt

Django 기본 `PBKDF2PasswordHasher` 대신 **bcrypt**를 사용한다. 설치 후 `settings/base.py`에 설정:

```python
# requirements.txt 에 추가 (foliio 재확인 필요, 없으면 1개 신규)
bcrypt
django[bcrypt]  # 또는 django-bcrypt

# config/settings/base.py
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.BCryptSHA256PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',  # 기존 해시 폴백
]
```

> bcrypt를 1순위로 두면 신규 비밀번호는 bcrypt로 해시, 기존 PBKDF2 해시는 폴백으로 검증. foliio 사용자가 없으므로 폴백 미사용이지만 안전하게 유지.

### 7.3 이메일 인증 토큰 (`accounts/tokens.py`)

```python
# 구조 (실제 구현 코드가 아닌 설계 명세)
# Django의 PasswordResetTokenGenerator를 상속해 두 종류의 토큰을 만든다.

class EmailVerifyTokenGenerator(PasswordResetTokenGenerator):
    """회원가입 이메일 인증 토큰 (24h TTL)"""
    def _make_hash_value(self, user, timestamp):
        return f"{user.pk}{timestamp}{user.is_active}"

class PasswordResetTokenGenerator(PasswordResetTokenGenerator):
    """비밀번호 재설정 토큰 (1h TTL, 사용 후 무효화)"""
    def _make_hash_value(self, user, timestamp):
        return f"{user.pk}{timestamp}{user.password}"
    # 비밀번호 변경 시 password 해시가 바뀌어 토큰 자동 무효화 (1회용 보장)
```

TTL은 `settings.PASSWORD_RESET_TIMEOUT` (Django 기본: 259200초 = 3일)을 `.env`에서 재정의:
- 이메일 인증: 86400 (24h)
- 비밀번호 재설정: 3600 (1h)

### 7.4 세션·토큰 저장 (FE)

- DRF Token을 발급한다 (`knox` 또는 기본 `authtoken`). foliio 패턴 ♻.
- FE 저장: **httpOnly 쿠키** (XSS 방어) → 추정: 베타는 localStorage, 정식 출시 시 httpOnly 쿠키로 전환.
- 모든 API 요청: `Authorization: Token <TOKEN>` 헤더.
- 토큰 만료: 베타는 무기한(추정). 정식 출시 시 재검토.

### 7.5 가입 폼 — 약관 동의 통합

회원가입 폼(`/register`)에 약관 동의 체크박스를 통합한다. 별도 온보딩 STEP가 아니라 **가입 시점에 한 번에**.

| 항목 | 필수 여부 |
|---|---|
| 이메일 | 필수 |
| 비밀번호 (8자+, 문자+숫자) | 필수 |
| 비밀번호 확인 | 필수 |
| 서비스 이용약관 동의 | 필수 (미동의 시 가입 버튼 비활성) |
| 개인정보 처리방침 동의 | 필수 |
| 마케팅 정보 수신 동의 | 선택 |
| 위촉 자기신고 (설계사 자격 보유 확인) | 필수 (`license_self_declared`) |

> 위촉 자기신고를 가입 폼에 통합해 별도 온보딩 STEP 수를 줄인다. 기존 `11-auth-onboarding.md`의 STEP 2(위촉확인)를 가입 폼으로 당긴 것. 카카오 OAuth 제거로 온보딩 흐름이 단순화됨.

### 7.6 온보딩 흐름 (가입 후)

이메일/비밀번호 가입으로 온보딩이 간소화된다:

```
회원가입(/register) → 이메일 인증(/verify-email?token=) → /home 또는 /onboarding

/onboarding:
  STEP 1: 첫 고객 등록 유도 (콜드스타트 CTA — skip 허용)

onboarding_completed_at: 이메일 인증 완료 시점에 기록
```

약관 동의 + 위촉 자기신고가 가입 폼에 통합되었으므로, 온보딩은 **콜드스타트 유도 1단계**만 남는다.

---

## 8. 가시성 매트릭스 — 데이터 접근 정책

이 매트릭스가 데이터 모델·API 권한·화면 접근에 **일관 적용**되는 단일 진실이다.

| 카테고리 | 가시성 | owner FK | 예시 엔티티 |
|---|---|---|---|
| **공유** | 모든 설계사 | 없음 | 게시판 피드(글·댓글·좋아요), 공지사항, FAQ, 판촉물 샘플 카탈로그 |
| **비공개** | 작성자 + 관리자 | 있음 | 1:1 문의 |
| **소유자 전용** | 본인 + 관리자 | 있음 (OwnedQuerySetMixin 강제) | 고객 정보·고객 동의·보험 정보·보험 분석·비교·캘린더·KPI/대시보드·알림/리마인더·설계사 기준(planner_baseline) |
| **소유자 + 관리자** | 본인 + 관리자 (역할 다름) | 있음 | 판촉물 주문(설계사=본인 주문, 관리자=전체 처리), 요금제·사용량 |

**테넌트 = 설계사 1인.** '공유' 항목을 제외한 모든 것은 `owner` 스코프.

### 8.1 OwnedQuerySetMixin (단일 강제점)

```python
# accounts/mixins.py — 구조 명세 (코드 아님)
class OwnedQuerySetMixin:
    """
    소유자 전용 ViewSet에 상속 강제.
    admin bypass 포함. request.user 없는 접근 = 코드리뷰 reject.
    """
    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.profile.is_admin:   # 화이트리스트 ①: admin bypass
            return qs
        return qs.filter(owner=self.request.user)  # 그 외 전부 user 필터
```

**적용 규칙 (절대원칙):**
- 소유자 전용 모든 ViewSet(`CustomerViewSet`, `CustomerInsuranceViewSet`, `CalendarViewSet`, `ActivityLogViewSet` 등)은 `OwnedQuerySetMixin` 상속 **강제**.
- `request.user` 없는 데이터 접근 = **코드리뷰 reject**.
- **회귀테스트 Day1**: "설계사 A가 설계사 B 고객 조회 → 404" 테스트를 소유 모델 전부에 작성.

### 8.2 IsOwner (객체 레벨 권한)

```python
# accounts/permissions.py — 구조 명세
class IsOwner(BasePermission):
    def has_object_permission(self, request, view, obj):
        return (
            obj.owner == request.user
            or request.user.profile.is_admin
        )
```

### 8.3 공유 가시성 ViewSet (owner 없음)

게시판·공지사항·FAQ는 `OwnedQuerySetMixin` 미사용. `IsAuthenticatedOrReadOnly`로 인증 사용자 전체 읽기 허용. 쓰기는 작성자 또는 admin.

### 8.4 화이트리스트 (인증 우회)

| 경로 | 메커니즘 | 근거 |
|---|---|---|
| `/api/v1/accounts/register/` | `AllowAny` | 가입 진입점 |
| `/api/v1/accounts/login/` | `AllowAny` | 로그인 진입점 |
| `/api/v1/accounts/verify-email/` | `AllowAny` | 이메일 인증 토큰 |
| `/api/v1/accounts/password-reset/` | `AllowAny` | 비밀번호 재설정 |
| `/api/v1/accounts/password-reset-confirm/` | `AllowAny` | 비밀번호 재설정 확인 |
| `/api/v1/memberships/` (GET) | `AllowAny` | 가격표 공개 |
| `/api/v1/s/:token/` | `AllowAny` + `share_token` 검증 | 고객 공유뷰 |
| `/api/v1/notices/` (GET) | `IsAuthenticatedOrReadOnly` | 공지사항 읽기 |
| `/api/v1/faq/` (GET) | `IsAuthenticatedOrReadOnly` | FAQ 읽기 |

---

## 9. foliio vendoring 맵 (weapon → inpa 리네임)

### 9.1 vendoring 원칙

- 별도 repo `~/Desktop/inpa`. foliio(`~/Desktop/foliio`)를 참조 소스로 두고 파일을 **복사(vendoring)**한다. foliio repo는 건드리지 않는다.
- `weapon/` 네임스페이스를 `inpa/` 앱 구조로 리네임한다. import path 전체 일괄 교체.
- 복사 후 foliio repo 변경이 생겨도 자동 동기화하지 않는다 — 인파는 독립 코드베이스.

### 9.2 핵심 vendoring 파일 (♻ 무변경)

| foliio 원본 (weapon/) | 인파 위치 | 리네임 액션 | 비고 |
|---|---|---|---|
| `core/utils.py` (`:358` `extract_text_from_pdf`) | `core/utils.py` | import path만 교체 | pdfplumber→PyMuPDF 폴백, 암호화 `authenticate` ♻ |
| `customers/calculate.py` (`:245` `calculate_total_analysis`, `:18` `calculate_analysis`) | `customers/calculate.py` | import path만 교체 | 8케이스 엔진 무변경. 골든테스트 회귀 가드 |
| `insurances/models.py` (`CustomerInsurance`, `CustomerInsuranceDetail`, `AnalysisCategory` 4계층) | `insurances/models.py` | `weapon.` → `inpa.` | 모델 무변경. 시드만 100+로 확장 |
| `membership/credit.py` (`:123` `_check_and_consume`) | `membership/credit.py` | import path 교체 + `kind='ai'` 분기 추가 | ◑ 개조 |
| cron 패턴 (`expirememberships`, `notifymembership`, `resetmonthlycredit`, `process_dormancy`) | `management/commands/*.py` | 패턴 ♻ + watchdog 신규 추가 | |

### 9.3 핵심 vendoring 파일 (◑ 개조)

| foliio 원본 | 인파 위치 | 개조 내용 |
|---|---|---|
| `core/ocr/claude_parser.py` (`:430` `claude_parse`, `:700` `_add_coverage`) | `core/ocr/claude_parser.py` | `_SYSTEM_PROMPT`에 100+ 담보 트리 주입 · Prompt caching breakpoint · 모델 라우팅 Opus/Haiku · **`_add_coverage` 3.5순위에 정규화 사전 lookup 삽입** |
| `customers/models.py` (`:76` `Customer`) | `customers/models.py` | `consent_overseas_at` 필드 1개 추가 |
| `customers/views.py` (`detect`, `compare`) | `customers/views.py` | detect: 국외이전 412 게이트 · compare: §97 필드 보강 |
| `community/content_filter.py` (PII 정규식 패턴) | `core/ai_guardrail.py` | 기법 재사용, 룰셋은 보험업법으로 교체 (✦ 신규 파일) |

### 9.4 정규화 사전 삽입 지점 (`_add_coverage` 3.5순위)

foliio `claude_parser.py:720-726` 의 3순위(detail 키워드)와 4순위(fuzzy) **사이**에 삽입:

```
3순위: _match_by_keywords(detail_name)   ← 기존 유지
3.5순위: normalization.lookup(company, raw_name)  ← ★ 삽입 (hit_count++ 복리)
4순위: _fuzzy_match_category(...)        ← 기존 유지
```

**왜 이 위치인가:** 1~3순위(결정론적)가 실패 후, 4순위(fuzzy=저신뢰 추측) 전. 보험사 확정 매핑이 fuzzy보다 신뢰도가 높고, §97 비교안내서의 정확성 요건 때문에 fuzzy가 정규화 사전보다 앞서면 안 된다.

### 9.5 리네임 일괄 교체 체크리스트

```bash
# 복사 후 import path 전체 교체 (sed 또는 IDE 일괄치환)
# 예: from weapon.customers import ... → from customers import ...
#     from weapon.core import ...     → from core import ...

grep -r "weapon\." inpa_be/ | grep -v ".pyc"   # 잔여 weapon. 참조 0건 확인
```

---

## 10. AI 라우팅 & 비용 거버넌스

| 용도 | 모델 | 모델 ID | 입력 $/MTok | 출력 $/MTok |
|---|---|---|---:|---:|
| **M1 비교안내서 / 정규화 사전** | Claude Opus 4.8 | `claude-opus-4-8` | $5.00 | $25.00 |
| **M2~M6 다건 OCR / 메시지** | Claude Haiku 4.5 | `claude-haiku-4-5` | $1.00 | $5.00 |
| (참고) 중간 옵션 | Claude Sonnet 4.6 | `claude-sonnet-4-6` | $3.00 | $15.00 |

**비용 절감 레버:**
1. **Prompt caching**: 100+ 담보 트리를 `system` 블록에 고정(`cache_control: ephemeral`). 캐시 읽기 ≈ 입력가 0.1×.
2. **Batches API**: 야간 다건 OCR = 전 토큰 50% 할인.
3. **토큰 측정**: 반드시 `count_tokens` 엔드포인트 사용. `tiktoken` 금지 (Claude 토큰 15~20% 과소계산).

---

## 11. 보안 — 국외이전 동의 게이트

### 11.1 detect 호출 전 412 게이트

```
설계사 → 증권 업로드
         │
         ▼
BE detect 진입
         │
         ├─ Customer.consent_overseas_at IS NULL?
         │        YES → 412 Precondition Failed
         │               → FE: ConsentOverseasModal 표시 (고객 1탭 동의)
         │        NO  → ConsentLog 기록 후 Claude API 호출 진행
         │
         ▼
Claude API (US) 호출
```

### 11.2 보안 기준

| 항목 | 처리 |
|---|---|
| **비밀번호 해시** | bcrypt (§7.2) |
| **PII 필터** | foliio `content_filter.py` 정규식 재사용 (KR mobile/RRN/card/사업자번호) |
| **시크릿 관리** | `.env` → IDC 서버 환경변수. `NEXT_PUBLIC_*`에 API 키 절대 금지 |
| **settings 분리** | `config.settings.local` / `config.settings.idc`. 로컬 매 명령에 명시 필수 |
| **DRF 기본 권한** | `IsAuthenticated`. 공개 API만 명시적 `AllowAny` |
| **CORS** | `CORS_ALLOWED_ORIGINS` 명시 (`.env`에서 관리) |
| **DB 문자셋** | `utf8mb4_unicode_ci` 강제 (한글 WHERE 안전) |
| **share_token** | UUID, 만료 필드 자리 확보 (만료·회수 정책 Q4 미결) |
| **준법 컨트롤포인트** | `planner_baseline.baseline_source == null` → neutral 강제. 분석 결과 "부족/충분" 단정 금지 |

---

## 12. 로컬 셋업 (빠른 시작)

### 12.1 백엔드

```bash
# 1. foliio 코드 복사 (vendoring)
cp -r ~/Desktop/foliio/Foliio_be/weapon/core        ~/Desktop/inpa/inpa_be/core
cp -r ~/Desktop/foliio/Foliio_be/weapon/customers   ~/Desktop/inpa/inpa_be/customers
cp -r ~/Desktop/foliio/Foliio_be/weapon/insurances  ~/Desktop/inpa/inpa_be/insurances
cp -r ~/Desktop/foliio/Foliio_be/weapon/membership  ~/Desktop/inpa/inpa_be/membership
# 이후 import path weapon. → 앱 네임스페이스로 일괄 교체

# 2. 환경 설정
conda create -n inpa python=3.8
conda activate inpa
pip install -r requirements.txt
cp .env.example .env       # .env 값 채우기

# 3. DB 마이그레이션 (로컬 설정 명시 필수)
DJANGO_SETTINGS_MODULE=config.settings.local python manage.py migrate

# 4. 담보 트리 + 정규화 사전 시드
DJANGO_SETTINGS_MODULE=config.settings.local python manage.py seed_taxonomy

# 5. 개발 서버
DJANGO_SETTINGS_MODULE=config.settings.local python manage.py runserver
```

> ⚠️ `DJANGO_SETTINGS_MODULE=config.settings.local` 을 매 명령에 붙이지 않으면 **프로덕션 DB로 붙는다.** foliio 패턴 그대로 승계.

### 12.2 프론트엔드

```bash
cd ~/Desktop/inpa/inpa_fe
npm install
npm run dev      # http://localhost:3000
npm run build    # 빌드 검증
```

### 12.3 검증 (done ≠ 코드 작성)

```bash
# BE 회귀 가드
pytest
pytest insurances/tests/test_premium_calculation_8cases.py -v   # 8케이스 골든테스트

# FE 타입 검사
cd inpa_fe && npx tsc --noEmit

# 멀티테넌시 격리 확인 (Day1 필수)
# 설계사 A로 고객 생성 → 설계사 B로 조회 → 404 응답 확인
```

---

## 13. 배포 개요

foliio의 rsync 기반 배포 패턴 승계. **프로덕션 배포는 명시적 승인 필수.**

```
[로컬 맥]                          [IDC 서버 211.234.108.90]
                                   user: pample
deploy-be.sh  ──rsync──▶  /home/pample/work/inpa/inpa_be/
   │                          │
   │                          ├─ conda activate inpa
   │                          ├─ migrate (idc 설정)
   │                          ├─ collectstatic
   │                          └─ gunicorn 재시작 (systemd: inpa.service)
   │
deploy-fe.sh  ──rsync──▶  /var/www/<도메인>/html/  (Next.js .next/static + public)
              또는 npm run build → out/ 배포
              nginx: / → Next.js 서빙, /api/v1/ → 127.0.0.1:8000 (Django)
```

| 항목 | 값 |
|---|---|
| 프로덕션 설정 | `config.settings.idc` (DEBUG=False, CORS 화이트리스트, SSL via nginx) |
| conda env | `inpa` |
| systemd | `inpa.service` |
| cron (신규) | `watchdog.py` 만기·갱신 일배치 |
| 베타 우회 | `FREE_TIER_UNLIMITED=True` |

---

## 14. 미해소 항목

| # | 쟁점 | 영향 | 상태 |
|---|---|---|---|
| Q1 | 표준 보장 기준선 출처·권위 (금감원/보험연구원/자체) | 히트맵 `graded` 모드 게이트 | 확정 전 `neutral` 중립만 |
| Q2 | 병력 국외이전 동의 별도 동의서 vs 통합 | detect API 출시 게이트 | 분리 전제로 설계(낙관 금지) |
| Q3 | §97 비교안내 정확요건 6항목 법적 확정 | 비교안내서 발행 하드블록 룰 | Phase0 법무 |
| Q4 | 셀프진단(제3자) 동의 충분성 + share_token 만료·회수 | 바이럴 루프·공유뷰 | Phase0 법무 |
| 운영 | 정규화 사전 자동승격 임계 (`hit_count` 기준) | §97 위반 리스크 vs 운영비용 | 베타까지 `admin_verified`만 사용 |
| 인증 | 이메일 발송 서비스 선택 (Gmail SMTP vs AWS SES) | 발송 안정성 · 베타 비용 | Gmail SMTP 기본값, 정식 시 SES |
| 세션 | DRF Token vs Knox (다중 디바이스 세션 관리) | 세션 보안·만료 정책 | 베타는 기본 Token, 정식 재검토 |
| FE 저장 | localStorage vs httpOnly 쿠키 (토큰 저장) | XSS 방어 | 베타 localStorage, 정식 쿠키 |

---

### 관련 문서

- `dev/02-data-model-and-api.md` — 데이터 모델 전체 필드, API 계약
- `dev/03-porting-map.md` — 파일별·라인별 포팅 액션 (정본)
- `dev/04-build-plan.md` — Phase0(법무 게이트)/Phase1(MVP) 스프린트·게이트
- `dev/07-api-data-contracts.md` — 상세 API 계약
- `dev/09-compliance-broker-line.md` — 컴플라이언스 레드라인
- `dev/11-auth-onboarding.md` — 인증·온보딩 상세 (이 문서와 연계, 카카오 OAuth 제거 기준으로 별도 갱신 필요)
