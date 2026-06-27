# 인파 (Inpa) — Claude Code 가이드

> 보험설계사용 AI 영업지원 웹앱 신사업. **인파(Inpa) = 인슈어(Insure) + 파트너(Partner)** = 보험설계사 곁의 영업 파트너.
> 코드는 `~/Desktop/foliio`(Foliio 분석판, 고년차용)에서 포팅·재활용.
> **현재: Phase 1 진행 중 — BE 13개 Django 앱 + FE 전체 라우트(공개·인증·관리자 60+ 페이지) 구현됨.**
> 구글 연동(소셜로그인+캘린더)·미팅예약·개인 일정·동의흐름까지 동작. 컴플라이언스 게이트(병력수집·§97 발행·국외이전)는 정식 출시 전까지 env 플래그로 닫힌 상태. `docs/dev/00~25` 개발 문서 + `docs/dev/00-INDEX.md`(SSOT)도 함께 유지.

## 핵심 컨텍스트
- **타겟**: 원수사·GA 위촉직(개인사업자) 보험설계사. 1순위 신입(발굴 절박), 2순위 중견(관리).
- **가치**: 새 고객 발굴 → 보장분석 → 갈아타기 제안을 한 동선으로. 분석=영업 행동의 시작점.
- **차별점**: ①갈아타기(승환)를 자동 비교안내서로 합법화(부당승환 §97 방패) ②담보 100+ 전체 '틀' + 보험사별 담보명 정규화.
- **BM**: Freemium (기능 다 열되 무료 월 횟수 제한, 헤비유저 구독).

## 스택 (2026-06-19 확정 — Claude Code 개발 최적)
- **FE: Next.js + TypeScript + Tailwind** (Angular 대신 — Claude Code 개발 속도·디자인 토큰 매핑 유리. foliio 랜딩도 Next.js 16).
- **BE: Django 4.2 + DRF + Python 3.11** — foliio의 `core/ocr/claude_parser`·`customers/calculate.py`(8케이스, numpy_financial)·담보 정규화 로직을 **그대로 재사용**(재포팅 위험 회피 = 핵심 자산).
- DB: **PostgreSQL**(운영=Neon 무료, 로컬=SQLite) — 2026-06-21 Railway 무료티어 폐지로 MariaDB→PG 전환(Django ORM이라 코드 영향 0, `psycopg2-binary`). / AI: Claude API(비교안내서·정규화=Opus 4.8 / 다건OCR=Haiku / 야간=Batches).
- **재사용=Python 백엔드 / 신규=Next.js 프론트**(3축 화면은 어차피 신규). Angular 컴포넌트는 재구현.
- 디자인 토큰: `design/tokens/inpa-tokens.css`(:root CSS변수) → Tailwind config 매핑. 로고: `design/logo/*.svg`.
- 로컬 전용 디렉터리(커밋 금지, `.gitignore` 차단): `samples/` = 실제 증권·가입설계서 PDF(PII·민감정보 — 절대 커밋·인용 금지) · `benchmark/` = UI 벤치마킹 참조 스크린샷(디자인 레퍼런스 전용). 루트의 `*.jpeg`·`calender*.webp`는 커밋된 디자인 참조 이미지.
- CPO=CTO 겸임(사용자 결정). 외부 법무 자문 계약 없음 → 컴플라이언스 게이트는 보수적 기본값+공개 가이드(협회·금감원)로 자체 처리, 유료 정식출시 전 재검토.

## 개발 명령어 (commands)
**모노레포**: `inpa_be/`(Django) + `inpa_fe/`(Next.js)가 한 저장소. 각 디렉터리에서 명령 실행.

### 백엔드 (`inpa_be/`, Python 3.11)
- 셋업: `pip install -r requirements.txt`(venv 권장). 기본 설정 = `config.settings.local`(SQLite — `manage.py`가 자동 지정).
- 서버: `python manage.py runserver` → http://localhost:8000 (API 루트 `/api/v1/`, 헬스체크 `/healthz/`).
- 마이그레이션: `python manage.py makemigrations` → `python manage.py migrate`.
- 전체 테스트: `python manage.py test inpa` / 단일: `python manage.py test inpa.booking` · `python manage.py test inpa.accounts.tests.LoginTests.test_x`(점 표기).
- 배포 전 점검(필수): `python manage.py check`.
- 시드(화면 렌더 확인용, 멱등): 데모 데이터 `python manage.py seed_demo` · 정규화 사전 `python manage.py seed_normalization` · 백오피스 관리자 계정 `python manage.py create_admin`. (배포 시 Render `startCommand`는 `seed_normalization`만 자동 실행 — `seed_demo`는 수동.)
- Django admin: `/admin/`. (운영 백오피스는 별도 `admin_console` API + FE `/admin/*`.)

### 프론트엔드 (`inpa_fe/`, Node 20, **Next.js 16 + React 19**)
- 셋업: `npm ci`. 개발: `npm run dev` → http://localhost:3000. 빌드: `npm run build`(타입체크 겸함). 운영: `npm start`.
- BE 주소 = `NEXT_PUBLIC_API_BASE`(미설정 시 `localhost:8000/api/v1` 폴백 + 콘솔 경고). **빌드타임 인라인이라 Vercel 환경변수 변경 후 재배포 필요.**
- 린트/테스트 스크립트 없음. ⚠️ `inpa_fe/AGENTS.md` 경고: **Next 16은 훈련데이터와 다름 — 코드 전 `node_modules/next/dist/docs/` 해당 가이드 확인.**
- **테마 가드레일**: 서비스 페이지 = **라이트 고정**, 다크모드는 **어드민 한정**(`app/admin/layout.tsx`가 `.theme-system`로 시스템 다크/라이트 추종). 서비스 화면에 `dark:` 변형 추가 금지. 제품 UI 카피는 `§`·법조문 표기 빼고 쉬운 말(레드라인).

### CI / 배포 (`.github/workflows/ci.yml`)
- push/PR(main·master) 시 3개 잡: ①BE `check`+`test inpa` ②FE `npm ci`+`build` ③gitleaks 시크릿 스캔.
- 배포는 CI가 아님 — **Vercel(FE)·Render(BE, `render.yaml`)가 GitHub 연동 자동배포**, DB=Neon(PostgreSQL).

## 코드 아키텍처 (big picture — 여러 파일을 읽어야 보이는 것)

### 요청 흐름
브라우저 → Next 페이지(`inpa_fe/app/**`) → **`inpa_fe/lib/api.ts`**(BE 호출 단일 게이트 — 모든 엔드포인트·타입 한 파일에 정의, 관리자는 `lib/adminApi.ts`) → DRF `/api/v1/`(`config/urls.py`가 앱별 `urls.py`로 분배) → ViewSet → 모델. 인증 = DRF TokenAuthentication, 토큰은 FE `localStorage['inpa_token']`(`tokenStore`). 에러 `{error|code|detail}` → FE `ApiError`로 정규화.

### 멀티테넌시(가시성)는 한 곳에서 강제 — 우회 금지
`inpa/core/mixins.py` `OwnedQuerySetMixin`(본인 데이터만 조회 + 생성 시 owner 자동 주입) + `inpa/core/permissions.py` `IsOwner`/`IsAdmin`/`IsEmailVerified`. **소유자 전용 ViewSet엔 이 믹스인+IsOwner를 반드시 부착.** 관리자(`profile.is_admin`)는 조회 우회. 공유(게시판·공지·FAQ·판촉샘플)만 예외. (정본: `docs/dev/02` §0 가시성 매트릭스.)

### Django 앱 지도 (`inpa_be/inpa/`, 13개 — `settings/base.py` LOCAL_APPS / `core`는 공유 패키지로 별도)
- `accounts` — User(이메일 PK)·Profile·인증(가입/이메일인증/로그인잠금/비번재설정)·구글(`google.py` 소셜로그인, `google_calendar.py` 캘린더)·온보딩·지점장 대시보드(`manager.py`).
- `customers` — 고객 CRUD·동의로그(`ConsentLog`)·고객 본인 동의 공개링크(`public_consent.py` `/c/<token>`)·기준선 프리셋(`presets.py`). 영업 4단계(`sales_stage` db/contact/meeting/contract = **DB/TA/FA/청약** 표시)·즐겨찾기/상단고정/최종연락(방치 색상경보)·아바타색·명함(`business_card`)·보험나이(`compute_insurance_age` 상령일)·계약 설명의무 체크리스트(`ContractChecklistItem`, `/customers/<id>/checklist/`).
- `insurances` — 보험/담보(소유자 전용, `customer__owner` 경유)·환수레이더(`churn.py`, 해지 추적 `is_cancelled`/`cancelled_at` → 유지율)·셀프진단 공개(`self_diagnosis.py` `/d/<ref>`)·OCR 교차검증(`verify.py`).
- `analysis` — **표준 담보 트리 + 보험사별 담보명 정규화 사전(공유 전역 마스터)**. 계산엔진 `calculate.py`(히트맵), 갈아타기 `compare.py`+`switch_verdict.py`(KEEP/SWITCH/NEUTRAL = 설계사 내부 전용, 고객 노출 금지 §97). foliio 포팅 핵심 자산.
- `booking` — 미팅예약(Calendly식): 슬롯/미팅 + 공개 예약링크(`public_booking.py` `/b/<token>`).
- `schedule` — 개인 일정/할일/고정차단(`ScheduleItem` 1모델, 소유자 전용, FE `/schedule`). **`booking`과 별개** — 캘린더는 둘을 같이 그리기만(예약 이중락 비파괴). `kind`(event/todo/block=동작) ⟂ `category`(5분류=색/범례: 고객미팅·생일/기념일·만기/갱신·업무·기타) + 생일·기념일 매년 반복(`anniversary_md`). ⚠️ 타임존 규약: 단건 start/end=UTC 저장·KST 표시 / 반복차단 `recur_*_time`=KST 벽시계 그대로(변환 금지, 변환 시 9h 밀림) / all_day·시각없는 todo=KST 정오 저장.
- `dashboard` — 월별 목표(수동)+실적(계산), 예상월급 배율. 계약 유지율 1/2/3년(`compute_retention` — 해지 입력 0건이면 `has_cancellation_data=false`로 미계산) + 관리직 팀집계(`accounts/manager.py`가 `compute_funnel`·`compute_retention`·`compute_team_roi` 팀 루프 재사용, PII 비노출, ROI=추정 라벨).
- `notifications`(알림+리마인더, 판촉물/전자자료 타입 포함) · `billing`(요금제·사용량 한도) · `boards`(게시판·공지·FAQ·문의, 혼합 가시성) · `promotion`(판촉물 주문 + **전자자료** `is_digital`/`digital_file`: 1회 무료 다운로드 → 2회차+ 어드민 큐 `PromotionDownload` + 관리자 알림) · `admin_console`(IsAdmin 백오피스) · `analytics`(북극성 이벤트 계측).
- `core` — 공통 믹스인·권한 + `core/ocr/`(foliio 벤더링: `claude_parser.py`·`ocrparsing.py`·`ocrdata.py` 보험사 코드).

### 증권 분석 파이프라인 (foliio 재사용의 핵심 동선)
증권 PDF 업로드(`POST /customers/<id>/insurances/ocr/`) → `core/ocr/claude_parser`(pdfplumber + Claude Opus, `ANTHROPIC_API_KEY` 게이트, 미설정 시 503) → `CustomerInsuranceDetail`(`InsuranceDetail.analysis_detail` M2M로 표준 트리에 매핑) → `analysis/calculate.py`가 leaf별 `held_amount` 합산 → `PlannerBaseline`(설계사 기준선) 매칭되면 `graded`(부족/적정/넉넉), 없으면 `neutral` → 히트맵/공유뷰.

### 공개(비인증) 토큰 엔드포인트 — FE 라우트와 1:1
`/s/<token>`(공유뷰) · `/b/<token>`(예약) · `/c/<token>`(고객 본인 동의) · `/d/<ref>`(셀프진단). 전부 TimestampSigner 토큰 + ScopedRateThrottle. FE는 `app/s|b|c|d/[token]/`.

### 설정·기능 게이트 (`settings/base.py` — env로 제어, 코드 우회 금지)
- 환경 분리: `local`(SQLite·DEBUG·콘솔이메일·`/media/` 로컬서빙) ↔ `prod`(Postgres `DATABASE_URL`·whitenoise·보안헤더·Sentry, SECRET_KEY 미설정 시 fail-loud).
- 미디어(업로드: 명함·전자자료) 저장 — **AWS 불필요**, 3모드(prod, 우선순위): ①**S3 호환 오브젝트 스토리지**(`AWS_STORAGE_BUCKET_NAME`+`AWS_*`, django-storages·boto3 — **Cloudflare R2** 무료 권장: `AWS_S3_ENDPOINT_URL`=R2·`REGION=auto`. Supabase/B2도 동일. 비공개 서명URL=PII 보호) ②**Render 영속 디스크**(`MEDIA_DISK_PATH`=마운트경로, 유료·단일 인스턴스) ③**로컬 임시**(미설정 — 재배포 시 소실). 로컬 개발은 base `/media/` 직접 서빙.
- **컴플라이언스 게이트(기본 닫힘)**: `COMPARE_AI_ENABLED`(갈아타기 AI초안) · `COMPARE_PUBLISH_ENABLED`(고객 발송 — §97 법무 전 하드블록) · `ANALYZE_MEDICAL_ENABLED`(병력 수집 BE 차단) · `REQUIRE_CUSTOMER_SELF_CONSENT`.
- 기능 플래그: `FREE_TIER_UNLIMITED`(베타 한도 우회) · `BOOKING_ENABLED` · `OCR_VERIFY_ENABLED` · `GOOGLE_OAUTH_*`(미설정 = 기능 숨김).
- Claude 모델은 하드코딩 금지 — `CLAUDE_MODEL_PARSE`(Opus) · `CLAUDE_MODEL_BULK`(Haiku)를 env에서만 주입.

## 확정 결정 (2026-06-19 세션)
- **인증 = 이메일/비밀번호 + 구글 OAuth 병행** (2026-06-21 변경 — 카카오는 폐기 유지). 회원가입→이메일 인증→로그인→비번찾기(이메일 토큰). 비번 해시 PBKDF2. 토큰은 Django 서명 토큰. 구글 로그인=검증 이메일로 기존 계정 링크(병행)·신규는 온보딩서 자격/소속 수집. 구글 캘린더=미팅 확정 시 이벤트 자동생성(이름 기본 마스킹). 전부 `GOOGLE_OAUTH_*` env 게이트(미설정=숨김).
- **데이터 가시성**: 게시판(SNS 피드)·공지·FAQ·판촉물 샘플 = **공유**(전 설계사). 그 외(고객·동의·보험·분석·비교·캘린더·KPI·알림·기준) = **소유자 전용**(OwnedQuerySetMixin+IsOwner). 1:1문의=작성자+관리자. 판촉물 주문=소유자+관리자. `Customer.owner on_delete=CASCADE`.
- **배포 = GitHub 자동배포(무료 $0)**: FE→Vercel, BE→Render(무료, `render.yaml`), DB→Neon(무료 PostgreSQL), CI=GitHub Actions(gitleaks·commitlint). 이메일=Resend. (Railway는 무료티어 폐지로 제외)
- **랜딩페이지**(`/`, 공개): 히어로 "**설계사님은 클로징만 준비하세요**".
- **판촉물** = 샘플 사진 + 구글폼식 입력 + 예약 → 운영팀 수동 주문제작(자동발송 없음). (구 'promotion 14종 자동생성' 모델 폐기)
- 한도(Freemium): 베타 무제한(`FREE_TIER_UNLIMITED`), 수치·결제는 정식 전. planner_baseline 프리셋: 베타는 직접입력만.

## PM 06.24 피드백 반영 (2026-06-26 세션)
- **고객 영업화면**: 4단계 칸반 = **DB→TA→FA→청약**(내부값 `db/contact/meeting/contract` 유지, 표시라벨만). 칸반=가로 스크롤 4열 보드(각 단계 세로 일렬). 방치 색상경보(최종연락 없으면 등록일 기준 3일↑ amber/7일↑ red **ring**, 정렬: 고정>즐겨찾기>방치). 아바타 디폴트=인파 로고+파스텔 팔레트(`color`). 직업 위험등급 배지·보험나이(상령일). 고객상세 **정보 탭**(좌 메모/우 상세/하단 명함) + **계약 탭**(설명의무 체크리스트, 해피콜 대체).
- **캘린더 5분류**(위 schedule), **유지율·관리직 ROI**(위 dashboard).
- **판촉물 전자자료**(위 promotion): 1회 무료→어드민 큐+알림. 운영팀이 Django admin에서 `digital_file` 등록·발송.
- **마케팅 방향**(토론): 개인="잡일 줄이고 첫 고객 만들기", 관리직="팀 성과·ROI"(추정 라벨). 랜딩 `AudienceSection` + 관리직 태그라인.
- **컴플라이언스 결정**: 명함 Vision OCR=보류(수기 폴백). 포인트/현금 보상=보험업법 §98 특별이익 소지 → **폐기**, 자사 SaaS 혜택·활동기반으로 재설계 후 법무(보류). "지점장"→"관리직" 용어는 UI 카피만.

## PM 06.28 세션 (발굴 입구·화법·정직성·QA P0)
- **발굴 입구**: 셀프진단 링크 위젯(`components/self-diagnosis-share.tsx`) = 홈 상단·고객목록 헤더 배치 → 받은 사람이 `/d/<ref>`에서 직접 동의·입력하면 리드 자동 등록. 카피 "아는 고객에게만"(제3자 동의 가드). 유입경로 측정 복원: `Customer.lead_source` choices(소개·명함·행사·직접·셀프진단) + 고객 등록 모달 select.
- **화법/문구 라이브러리**(`/scripts`, nav '화법'): `lib/copy-library.ts` 5카테고리(소개요청·거절응대·약속확정 TA·니즈환기 FA·안부 AS) 정적 데이터 + `{고객명}`/`{설계사명}` 치환(`renderCopy`). 공용 `lib/clipboard.ts`(`copyText`). ⚠️ 문자광고 가드: 카톡(개인 1:1)/문자(광고규제) 채널 배지 + (광고)·무료수신거부·야간(21~08시) 금지·아는 고객에게만.
- **계약 체크리스트 '불리사항 고지'**: `DEFAULT_CONTRACT_CHECKLIST` 8번째 항목(모듈 상수=마이그레이션 불필요, `apply_template` 멱등→기존 체크리스트엔 미반영·신규부터). 계약 탭에 §97 구두고지 **내부 안내 박스**('설계사 내부·고객 비노출' 배지, 구체항목은 비교탭 `switch_warnings`로 유도 — 복제 안 함).
- **정직성/쉬운말 카피**: 랜딩 '합법' 단정 제거(→AI 초안·최종책임 설계사)·'문자 발송' 모순 해소(→복사·직접 전달). 홈 실명 인사(`profile.name`)·환수 위험 `?` 툴팁·TA/FA 쉬운말·"방치"→"연락 끊긴 기간". `InfoDot`=`components/info-dot.tsx` 공용화(StatCard 재사용, ui.tsx 클라 경계 불변).
- **QA P0 수정(2026-06-28 실서비스 감사)**: ⚠️ **이메일 인증 = BE 토큰 self-contained**(`signing.dumps(pk)` → 링크·검증 모두 `token`만, uid 없음. reset-password와 달리 **FE가 uid 요구하면 가입 전면 차단 — 회귀 금지**) + 재발송 버튼. · OCR `max_tokens` 4096→**8192**(담보 많은 종합보험 JSON 잘림). · 고객 이력 탭 `meta` raw 덤프 제거(scope·`*_id` 내부필드 비노출). · 판촉 이미지 `onError` 폴백. **남은 QA P1 백로그=프로젝트 메모리 `qa-audit-backlog.md`**(수기 보험등록·제안입력·공유링크FE·탈퇴/비번FE·OCR오탐·배포 env).

## 문서 (`docs/`)
- **`docs/dev/00-INDEX.md` = 개발 문서 마스터 지도(SSOT 진입점)**. 전체 라우트맵·문서 인덱스·스트림↔엔티티 매핑.
- `docs/dev/02-data-model-and-api.md` — **데이터모델 정본(SSOT, 42 엔티티 + 가시성 매트릭스)**.
- `docs/dev/01`(아키텍처) `11`(인증) `12`(고객/OCR) `13`(공유) `14·16`(컴플라이언스/법무) `15`(대시보드) `17`(게시판) `18`(모바일) `19`(관리자) `20`(데브옵스) `21`(판촉물) `22`(알림) `23`(요금제) `24`(랜딩) `25`(배포 실전 가이드, PM용) — 스트림별 명세.
- `docs/01~07`(루트) — 사업·제품 기획 원본(Foliio 영업지원 에디션 명칭). `docs/_archive-foliio/` — 구 기획 아카이브.

## 개발 착수 전 게이트 (코드 0줄, 선결)
1. 보장 기준선(코어담보) 출처·면책 정의
2. 민감정보(병력) Claude API 국외이전 동의서 — **법무 선결**
3. 갈아타기 비교안내 법적 요건(§97) 확정
→ 이 3개 전에 AI 분석/비교안내서 기능 빌드 시작 금지. 막히면 OCR·담보표(중립 기능)부터.

## 빌드 순서 (docs/07 §0)
공통 컴포넌트 → 증권 OCR+담보 정규화 → 담보 한눈표 → 갈아타기 비교표 → 고객 메시지 → 고객상세/공백.
(포팅 지도: foliio의 `core/ocr/claude_parser.py`·`customers/calculate.py`·`insurances/models.py` 기준 — 보험사별 담보명 정규화 사전을 `_add_coverage` 매칭 단계에 끼움.)

## 작업 원칙 (사용자 = PM, 비개발자)
- 새 기능은 계획 합의 후 실행 (Plan 90% / Execute 10%). 코드 전 로드맵으로 설명.
- 한국어 소통. 컨설팅 용어 지양, 쉬운 말.
- 컴플라이언스(국외이전 동의·부당승환·광고심의)는 기능의 게이트 — 우회 금지.

## 정직성 레드라인 (제품 원칙)
- "심의 완료/안전" 배지 금지(보증책임). AI 생성물엔 "AI 초안·최종책임 설계사" 면책 고정.
- 원탭 자동발송 없음(카카오 불가) → 클립보드 복사/카톡 열기까지만.
