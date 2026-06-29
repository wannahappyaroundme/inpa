# Inpa — Agent Guide (CLAUDE.md)

> **Inpa (인파) = Insure + Partner.** AI sales-support web app for individually-contracted insurance planners (원수사/GA 위촉직). Code ported/reused from `~/Desktop/foliio` (Foliio analysis edition).
> **This file is the development SSOT, written for the AI coding agent.** The human PM does NOT read it — they read `README.md` (Korean, PM-facing). Keep this file English + dense + current; keep README Korean + plain. PM communicates in Korean → reply to the PM in Korean even though this guide is English.

---

## 1. Current state (2026-06-29)

- **Phase 1, live in production.** Monorepo: `inpa_be/` (Django 4.2 + DRF, Python 3.11, 13 apps) + `inpa_fe/` (Next.js 16 + React 19 + TS + Tailwind, ~55 routes: public / auth / admin).
- **Deployed:** BE → Render (`https://inpa-be.onrender.com`, `/healthz/` → `{"status":"ok","service":"inpa-be"}`, DEBUG=False) · FE → Vercel (`https://in-pa.vercel.app`) · DB → Neon Postgres · email → Resend · CI = GitHub Actions. All $0. Render free tier **sleeps when idle** → first request slow.
- **Deploy workflow:** commit on the reused feat branch **`feat/benchmark-ui-revamp`** → PR to `master` → **merge auto-deploys** Vercel + Render. ⚠️ **Parallel sessions share this branch** — `git fetch` + `git log origin/master..HEAD` before pushing; PR numbers interleave (not strictly mine).
- **What works today:** email + Google auth · customer pipeline (4-stage **단계별** board + **목록** view, `status` axis, staleness cue) · OCR → coverage normalization → **traffic-light heatmap** · self-diagnosis inbound link (`/d`) · consent flows (customer-self) · **Calendly-style booking** (work hours → auto free slots → accept/decline) · personal schedule/calendar · dashboards (goals, retention, manager ROI) · 직업급수 search · script/talk library · share view (content-protected, `/s`) · notifications · admin back-office (usage tracking).
- **Closed behind env flags until legal review:** medical-history collection, §97 comparison-doc publishing, overseas (Claude API) transfer, paid quota (402 — `FREE_TIER_UNLIMITED=True` in beta).

## 2. Context

- **Target users:** individually-contracted planners (sole proprietors) at carriers/GAs. Priority 1 = new planners (desperate for lead-gen); priority 2 = mid-career (management).
- **Value:** prospecting → coverage analysis → switch (갈아타기/승환) proposal in ONE flow. Analysis is the *start* of the sales action, not a report.
- **Differentiators:** (1) legitimize switching via an auto-generated 비교안내서 (comparison guide) as a §97 shield against improper-switching rules; (2) full 100+ coverage (담보) "frame" + per-carrier coverage-name normalization.
- **BM:** Freemium (all features open, free monthly quota, heavy users subscribe).
- **Org:** CPO = CTO (the user). No external legal counsel → compliance handled conservatively (safe defaults + public regulator/association guides), re-reviewed before paid launch.

## 3. Stack

- **FE:** Next.js 16 + React 19 + TypeScript + Tailwind v4. **Design tokens centralized in `app/globals.css`** (`:root` CSS vars → `@theme inline`; custom `@utility shadow-card`). ⚠️ `design/tokens/inpa-tokens.css` is a stale design reference, NOT the active source. **Nav = desktop left sidebar + mobile bottom tab** (`components/app-nav.tsx`; body push via `body:has(.app-sidebar) main{padding-left}`). Logos `design/logo/*.svg`.
- **BE:** Django 4.2 + DRF + Python 3.11. Reuses foliio's `core/ocr/claude_parser`, `customers/calculate.py` (8 cases, numpy_financial), coverage-normalization **verbatim** (re-porting risk avoidance = core asset).
- **DB:** PostgreSQL (prod = Neon free; local = SQLite). ORM-only, zero code impact, `psycopg2-binary`.
- **AI:** Anthropic Claude API. Model ids injected via env ONLY — `CLAUDE_MODEL_PARSE` (Opus: comparison/normalization), `CLAUDE_MODEL_BULK` (Haiku: bulk OCR), nightly = Batches. **NEVER hardcode model ids.**
- **Local-only dirs (gitignored, NEVER commit or quote):** `samples/` = real policy PDFs (PII/sensitive); `benchmark/` = UI reference screenshots; root `data/` = PM's raw data extracts (the operational copy lives under each app's `data/`). Root `*.jpeg`/`calender*.webp` are committed design refs.

## 4. Commands

Monorepo — run BE commands in `inpa_be/`, FE in `inpa_fe/`.

### Backend (`inpa_be/`)
- Setup: `pip install -r requirements.txt` (venv). Default settings = `config.settings.local` (SQLite; `manage.py` sets it).
- Run: `python manage.py runserver` → :8000 (API root `/api/v1/`, health `/healthz/`).
- Migrations: `makemigrations` → `migrate`. **Pre-deploy check (required):** `python manage.py check`.
- Tests: all = `python manage.py test inpa`; app = `python manage.py test inpa.booking`; single = `python manage.py test inpa.accounts.tests.LoginTests.test_x`.
- Seeds (idempotent): `seed_demo` (demo data — manual only, NOT in deploy) · `seed_normalization` (coverage dict) · `seed_jobs` (직업급수 707-row `JobRiskCode` from `inpa/customers/data/job_risk_codes.json`; **bulk upsert + sync/prune**: deletes any `(sctg_cd,name)` not in the file → the file is the source of truth, so swapping the data file converges prod to exactly the file; `Customer.job_code` is SET_NULL so customers survive a swap) · `seed_promotion` (판촉물 카테고리 골격) · `create_admin`. Render `startCommand` = `migrate → createcachetable → seed_normalization → seed_jobs → seed_promotion → gunicorn` (all idempotent, every deploy; `createcachetable` backs the DB cache for rate-limit throttling).
- Django admin `/admin/`. Ops back-office = separate `admin_console` API + FE `/admin/*`.

### Frontend (`inpa_fe/`, Node 20)
- Setup: `npm ci`. Dev: `npm run dev` → :3000. Build: `npm run build` (**also typechecks — the ONLY FE gate; no FE test runner or lint script**). Prod: `npm start`.
- BE URL = `NEXT_PUBLIC_API_BASE` (fallback `localhost:8000/api/v1` + console warning if unset). **Build-time inlined → redeploy Vercel after changing the env var.**
- ⚠️ **Next 16 differs from training data** (`inpa_fe/AGENTS.md`): read `node_modules/next/dist/docs/` for the relevant guide before writing Next-API code.

### CI / Deploy (`.github/workflows/ci.yml`)
- On push/PR to main·master: (1) BE `check` + `test inpa`, (2) FE `npm ci` + `build`, (3) gitleaks secret scan.
- **Deploy is NOT CI** — Vercel(FE) + Render(BE, `render.yaml`) auto-deploy from GitHub; DB = Neon.

## 5. Architecture (big picture — spans multiple files)

### Request flow
Browser → Next page (`inpa_fe/app/**`) → **`inpa_fe/lib/api.ts`** (single BE-call gate: all endpoints+types in one file; admin in `lib/adminApi.ts`) → DRF `/api/v1/` (`config/urls.py` fans out to per-app `urls.py`) → ViewSet → model. Auth = DRF TokenAuthentication; token in FE `localStorage['inpa_token']` (`tokenStore`). Error bodies `{error|code|detail}` → normalized to FE `ApiError` (carries `.status`, `.code`, message).

### Multitenancy (visibility) — enforced in ONE place, never bypass
`inpa/core/mixins.py::OwnedQuerySetMixin` (filters to own rows + auto-injects owner on create) + `inpa/core/permissions.py::IsOwner`/`IsAdmin`/`IsEmailVerified`. **Owner-scoped ViewSets MUST attach this mixin + IsOwner.** Admin (`profile.is_admin`) bypasses read. Shared exceptions only: boards/notices/FAQ/promo-samples. SSOT: `docs/dev/02` §0 visibility matrix.

### Django app map (`inpa_be/inpa/`, 13 apps; `core` is a shared package)
- **`accounts`** — User (email PK), Profile, auth (signup / email-verify / login-lock / password-reset / password-change / withdrawal), Google (`google.py` social login, `google_calendar.py`), onboarding, manager dashboard (`manager.py`). Profile holds booking settings: `booking_msg_template`, `booking_default_duration`, `booking_buffer_min` (앞뒤 여유, default 60), `title` (직책).
- **`customers`** — customer CRUD; consent log (`ConsentLog`); customer-self public consent (`public_consent.py` `/c/<token>`); baseline presets (`presets.py`); contract disclosure checklist (`ContractChecklistItem`, `/customers/<id>/checklist/`).
  - **Two orthogonal axes:** `sales_stage` (db/contact/meeting/contract → shown **DB/TA/FA/청약**, the funnel position) ⟂ `status` (**active/hold/dormant/closed = 진행중/보류/휴면/종료**, the engagement state; default `active`). Only `active` customers get the staleness/무접촉 cue (subtle left-edge bar + 'N일 무접촉'); parked rows are dimmed + foldable via a '진행중만' toggle. `status` is NOT in SUBSTANTIVE (changing it does NOT bump `last_contacted_at`).
  - **D-Day auto-update** (`views.py::CustomerViewSet.perform_update`, `SUBSTANTIVE` set): a PATCH touching substantive fields (memo/info/`sales_stage`/churn…) bumps `last_contacted_at=now`; favorite/pin/`status` toggles do NOT. **PM decision: a 단계별 stage move IS an action → `sales_stage` is in SUBSTANTIVE.**
  - **`fa_reached_at`** (`models.py::save()` hook): timestamp the FIRST time `sales_stage` becomes `meeting`(FA); never overwritten → re-entry NOT recounted. Drives the dashboard "이번 달 미팅" metric.
  - **`compute_insurance_age`** (models.py): 보험나이 = 만 나이 + (직전 생일로부터 6개월 이상이면 +1). FE mirrors this live (`computeInsuranceAge` in the customer detail).
  - **`JobRiskCode`** = 직업급수 global master (shared, read-only; **707 메리츠 jobs** via `seed_jobs`; fields: name/alt_name/risk_grade 1·2·3·9/synonym(`|`-joined)/description/kidi_cd). `Customer.job_code` FK (SET_NULL). Search: `GET /api/v1/jobs/search/?q=` (`JobSearchView`, substring on name+alt+synonym+kidi, relevance-ranked; mounted top-level `jobs/search/`). FE: pick a job → 직업급수 auto-fills (registration modal **and** customer-detail InfoTab).
- **`insurances`** — insurance/coverage (owner-scoped via `customer__owner`); churn radar (`churn.py`, `is_cancelled`/`cancelled_at` → retention); public self-diagnosis (`self_diagnosis.py` `/d/<ref>`); OCR cross-verify (`verify.py`); manual ("직접 입력") insurance entry. **OCR upload (`/customers/<id>/insurances/ocr/`) is consent-gated**: 412 if `consent_overseas_at` is null (FE opens the consent modal before the file-pick, so a planner never hits a raw error).
- **`analysis`** — **standard coverage tree + per-carrier coverage-name normalization dict (shared global master)**. Calc engine `calculate.py` (heatmap); switch `compare.py`+`switch_verdict.py` (KEEP/SWITCH/NEUTRAL = planner-internal ONLY, never shown to customer per §97). Core foliio-ported asset.
  - **Heatmap UI** (`components/heatmap.tsx`): **traffic-light — 넉넉=green / 적정=yellow / 부족=red**. The '중립' status/chip/legend is **REMOVED** — when no baseline (`mode='neutral'`) the heatmap shows held amounts only (no grade color/label) + a clickable **'기준 설정하기' CTA** → `/settings/baseline` (never the word '중립'). 2-column category grid for scannability. **BE grading authority + honesty redline UNCHANGED** (no false grading without a baseline — the FE just hides grades & nudges to set one).
- **`booking`** — Calendly-style meeting booking (**full engine**). **`WorkHour`** (recurring weekly work hours, KST wall-clock) → **`availability.py::generate_available_slots`** computes free slots = work hours − meetings(±`Profile.booking_buffer_min`) − schedule blocks (recur + single, time-overlap). Public `/b/<token>` GET returns computed slots (identified by `start_at`, **NOT** a stored slot row); POST creates a **PENDING** `Meeting` (Profile-row `select_for_update` lock + `is_slot_available` recheck → 409 conflict w/ '담당 설계사와 상의' warning) + planner `meeting_booked` notification (carries `meeting` FK). Planner **accept** (`/meetings/<id>/accept/`) → confirmed + Google Calendar event (created here, not at booking time); **decline** (`/decline/`) → frees the time. `Meeting.status` = pending/confirmed/canceled/declined. Pending visible in the bell + the **/schedule '예약 요청' card**. `{소속직책}` merge field = `affiliation`+`title`. Legacy manual `MeetingSlot` CRUD remains but is NOT in the availability engine. ★ **Timezone:** all overlap math in KST aware (UTC meetings/events → `localtime`; WorkHour/recur-block TimeFields = KST wall-clock → combine with KST date).
- **`schedule`** — personal schedule/todo/recurring-block (`ScheduleItem`, owner-scoped, FE `/schedule`). **Separate from `booking`** — the calendar just draws both. `kind` (event/todo/block = behavior) ⟂ `category` (5 types = color/legend: 고객미팅 / 생일·기념일 / 만기·갱신 / 업무 / 기타) + yearly-recurring birthday/anniversary (`anniversary_md`). ⚠️ **TIMEZONE rule:** single start/end = stored UTC shown KST / recurring-block `recur_*_time` = KST wall-clock stored as-is (**NEVER convert** — shifts 9h) / all_day & timeless todo = stored KST noon.
- **`dashboard`** — monthly goal (manual) + actuals (`aggregation.py`), expected-salary multiplier. **`compute_actuals` meetings = distinct customers who first reached FA this month** (`Customer.fa_reached_at`), NOT `booking.Meeting`; premium = this-month registered-policy monthly-premium sum; new_customers = this-month created. Retention 1/2/3yr (`compute_retention`; 0 cancellations → `has_cancellation_data=false`) + manager team aggregation (`accounts/manager.py`, no PII, ROI labeled "estimate"). **Both the home calendar and the /schedule calendar use the SAME 5-category legend** (고객미팅/생일·기념일/만기·갱신/업무/기타), colored by `ScheduleCategory`; the 알림 category is removed from both (alerts live in the top-right bell only).
- **`notifications`** (alerts+reminders, incl. promo/digital-asset + `meeting_booked` types; `Notification.meeting` FK powers accept/decline) · **`billing`** (plans + usage limits; 402 over-limit via `credit.py`) · **`boards`** (board/notice/FAQ/inquiry, mixed visibility) · **`promotion`** (promo orders + digital assets: 1 free download → 2nd+ → admin queue; category skeleton via `seed_promotion`) · **`admin_console`** (IsAdmin back-office; usage tracking, demo accounts excluded, FE `/admin/usage`) · **`analytics`** (north-star event tracking).
- **Security hardening:** DRF rate-limit throttling backed by Django **DB cache** (`createcachetable` in startCommand) — anti DoS / cost-bomb (OCR/AI) / brute-force. **Content protection** = FE `components/content-guard.tsx` on the share view (`/s`): watermark + copy-block + image-save deterrence (deterrent, not real DRM).
- **`core`** — shared mixins/permissions + `core/ocr/` (foliio vendored: `claude_parser.py`, `ocrparsing.py`, `ocrdata.py` carrier codes).

### OCR → analysis pipeline (the core foliio-reuse flow)
Policy PDF upload (`POST /customers/<id>/insurances/ocr/`) → `core/ocr/claude_parser` (pdfplumber + Claude Opus; `ANTHROPIC_API_KEY`-gated, 503 if unset; `max_tokens=8192`) → `CustomerInsuranceDetail` (M2M to standard tree) → `analysis/calculate.py` sums `held_amount` per leaf → if a `PlannerBaseline` matches → `graded` (부족/적정/넉넉); else `neutral` → heatmap/share view.
Normalization SSOT: `core/ocr/ocrparsing.py::COVERAGE_KEYWORDS` — ONE dict shared by both pipelines. Matching = **substring (`if kw in name`) + longest-keyword-first**. Fix mis-matches in dict DATA, not logic (see Gotchas).

### Public (unauthenticated) token endpoints — 1:1 with FE routes
`/s/<token>` (share view) · `/b/<token>` (booking) · `/c/<token>` (customer-self consent) · `/d/<ref>` (self-diagnosis). All use TimestampSigner tokens + ScopedRateThrottle. FE at `app/s|b|c|d/[token]/`.

### Settings & feature gates (`settings/base.py` — env-controlled, NEVER bypass in code)
- Env split: `local` (SQLite, DEBUG, console email, `/media/` local) ↔ `prod` (Postgres `DATABASE_URL`, whitenoise, security headers, Sentry; **fail-loud if SECRET_KEY unset**).
- Media uploads — **no AWS required**, 3 prod modes by priority: (1) S3-compatible (`AWS_*`; **Cloudflare R2** free recommended; private signed URLs protect PII); (2) Render persistent disk (`MEDIA_DISK_PATH`, paid); (3) local-temp (unset — lost on redeploy). Local dev serves `/media/`.
- **Compliance gates (default CLOSED):** `COMPARE_AI_ENABLED` · `COMPARE_PUBLISH_ENABLED` (§97 hard-block pre-legal) · `ANALYZE_MEDICAL_ENABLED` · `REQUIRE_CUSTOMER_SELF_CONSENT`.
- **Feature flags:** `FREE_TIER_UNLIMITED` (beta quota bypass — currently True, 402 never fires) · `BOOKING_ENABLED` · `OCR_VERIFY_ENABLED` · `GOOGLE_OAUTH_*` (unset = feature hidden).

## 6. Conventions & redlines

- **★ Easy-words · positive-framing · audience-split (STANDING — the product's voice; applies to ALL planning AND code).** Three parts, never bypass:
  - **(a) Easy words for the planner (설계사).** Plain everyday Korean; never jargon/feature-words in rendered UI. '수기 입력'→'직접 입력'; 'OCR'→'증권 스캔/자동 정리'; 'Kanban/칸반'→'단계별'; 'list/리스트'→'목록'; 'lead/리드'→'고객'. If a planner would have to decode the word, rewrite it.
  - **(b) Audience split.** Risk/ops concepts (책임 회피, 법적 리스크, 컴플라이언스, §97, 부당승환, 국외이전 '게이트', planner_attested, 환수…) live ONLY in planner-internal boxes / this dev doc. **Customer-facing surfaces (`/s` · `/d` · `/c` · `/b`) show ONLY benefit + the next action** — never the legal machinery.
  - **(c) Positive guidance, never negative/not-yet/beta-sounding.** Forbidden in rendered copy: '안 됩니다', '못 합니다', '불가', '준비 중', '아직 없음', '자동 발송 없음', red rejection for an expected state. Reframe every block as the NEXT step (consent-gated upload → "고객 동의를 먼저 보내면 바로 분석할 수 있어요", not "동의 없이는 분석 불가").
- **NO em-dash (`—`, U+2014) in user-facing copy** — PM finds it "AI-sounding." Use comma / period / colon / parentheses / a Korean particle. No-value placeholder = `-` (hyphen), never `—`. Middle-dot `·`, hyphen `-`, en-dash `–` are fine. Code comments are exempt. When sweeping, only touch rendered strings.
- **Honesty redlines (disclaimers CONSOLIDATED):** no "reviewed/safe" badges (warranty liability). The "AI 초안 / 인파는 보험 중개 안 함" disclaimer exists ONLY at official spots — signup/onboarding, 약관, data-policy, and customer-facing AI output (`/s`, `/d`, AI 비교초안 box) — as ONE brief line each. Do NOT sprinkle it on every card. Unified wording: *"인파는 보험을 중개·권유하지 않는 분석·정리 소프트웨어입니다. 보장 판단과 고객 안내는 설계사님의 업무이며, 산출물은 AI가 정리한 참고 자료입니다."*; customer short form: *"인파가 등록된 보장 정보를 정리한 참고 자료입니다."* Tone = factual ("중개 안 하는 도구"), NOT blame ("모든 책임은 설계사").
- **Theme guardrail:** service pages = **light-fixed**; dark mode = **admin only** (`app/admin/layout.tsx` `.theme-system`). NEVER add `dark:` variants to service screens.
- **Copy:** product UI = plain language, NO `§`/legal-clause notation in service copy. (Internal/planner-only boxes may reference §97.)
- **Git:** Conventional Commits (Korean scope ok, e.g. `feat(동의)`). Small per-feature commits; don't mix refactor + feature. Commit only when the user asks. Branch before working on the default branch.
- **Docs upkeep (standing rule):** whenever a feature is implemented AND merged AND deployed, UPDATE both `README.md` (Korean, PM-facing) and this `CLAUDE.md` (sections above + the changelog). Do it as the closing step of a deploy, unprompted.

## 7. Gotchas (read BEFORE touching the area — these have bitten)

- **Email verification = BE self-contained token** (`accounts`): `signing.dumps(pk)` → link and verify use `token` ONLY, no `uid` (UNLIKE reset-password). **If FE requires `uid`, signup is fully blocked — do NOT regress.** Resend button exists.
- **Consent token is multi-scope** (`customers/tokens.py`): `make_consent_token(customer, scopes=None)`; `read_consent_token` returns `{pk, scopes}` (legacy bare-int → `{pk, scopes:['overseas_medical']}`, keep compat). `/c` GET → `items[]`; POST `{agreed:[scope]}`; only token-scoped consents recorded (forgery guard); required scope unmet → 412.
- **Consent subject enforcement:** planner-recorded consents are `subject=planner_attested` (server-forced) and CANNOT open the `consent_overseas_at` gate; only `customer_self` (via `/c` or self-diagnosis) opens it. **Registration modal no longer has planner self-check consent boxes** — consent is collected by sending the customer the `/c` link.
- **OCR normalization substring trap** (`core/ocr/ocrparsing.py::COVERAGE_KEYWORDS`): substring + longest-first means a name containing a shorter keyword mis-routes (e.g. '상피내암' contains '암진단'). Fix in dict DATA, NOT the logic. No migration. Add a regression test calling `_match_coverage` directly.
- **Booking timezone:** `availability.py` must keep ALL comparisons in KST aware. WorkHour/recur-block TimeFields are KST wall-clock (combine with the KST date); meetings/single events are UTC (`timezone.localtime`). Mixing them naively shifts 9h.
- **`NEXT_PUBLIC_API_BASE` build-time inline:** changing it in Vercel needs a redeploy. If prod FE calls localhost, it's unset/not-redeployed.
- **`FRONTEND_BASE_URL` is effectively required** (default `localhost:3000`): unset in prod → email-verify / consent / booking links generate as localhost = broken.
- **402 hidden in beta:** `FREE_TIER_UNLIMITED=True` bypasses all limit checks. BE already returns 402 `{code:'credit_exhausted', kind, limit, used}` for OCR/analysis/compare/promotion. Flipping the flag without an FE notice modal = users see red errors.
- **SQLite vs Postgres seed trap** (memory `sqlite-vs-postgres-seed-trap`): local SQLite ignores varchar length, prod PG rejects. Validate seeds/fixtures against PG too (e.g. `JobRiskCode.name` max 120). Prod `seed_demo` is manual via Render Shell.

## 8. Pre-build compliance gates (zero code until resolved)

1. Coverage baseline (core 담보) source + disclaimer definition.
2. Medical (sensitive) data → Claude API overseas-transfer consent form — **legal prerequisite**.
3. Switch comparison-doc §97 legal requirements finalized.

→ Do NOT start AI-analysis / comparison-doc features before these 3. If blocked, build OCR + coverage table (neutral features) first. Build order (docs/07 §0): common components → OCR + normalization → coverage table → switch comparison → customer message → customer detail / gaps.

## 9. Locked product decisions

- **Auth = email/password + Google OAuth** (KakaoTalk dropped). Signup → email-verify → login → password-reset (email token). PBKDF2 hash; Django signed tokens. Google login links to an existing account by verified email; new Google users collect credential/affiliation in onboarding. Google Calendar auto-creates an event on meeting **accept** (name masked by default). All behind `GOOGLE_OAUTH_*` (unset = hidden).
- **Data visibility:** boards / notices / FAQ / promo samples = **shared**. Everything else (customers, consent, insurance, analysis, compare, calendar, KPI, alerts, baselines) = **owner-only**. 1:1 inquiry = author+admin. Promo orders = owner+admin. `Customer.owner on_delete=CASCADE`.
- **Landing** (`/`, public): hero "설계사님은 클로징만 준비하세요." `AudienceSection` (individual vs manager) + manager taglines.
- **Booking** = planner sets recurring work hours → customer picks a free slot via `/b` link → planner accepts → confirmed (no auto-send; planner copies the link/message).
- **Promotion** = sample photo + Google-form-style input + booking → ops team manual production (no auto-send).
- **Freemium quota:** beta unlimited (`FREE_TIER_UNLIMITED`); numbers/payment post-launch. `PlannerBaseline` presets: beta is direct-input only.
- **Dropped/deferred:** business-card Vision OCR = deferred (manual fallback). Point/cash rewards = improper-benefit risk under §98 → dropped (legal hold). "지점장"→"관리직" wording is UI copy only.

## 10. Working with the PM

- PM is **non-developer**, communicates in **Korean**, reads `README.md` only. Reply in Korean, plain words, no consulting jargon.
- **Plan 90% / Execute 10%:** new features → agree on a roadmap-style plan BEFORE coding; present options as pros/cons with a recommendation. PM often pushes "바로 해줘" — honor momentum, but for **schema/migration or semantic-redefinition changes still surface a 2-line plan + confirm** first.
- Compliance (overseas-transfer consent, improper-switching, ad review) is a feature gate — never bypass.
- **Close every deploy by updating README.md + CLAUDE.md.** Standing rule, do it unprompted.

## 11. Changelog (newest first — condensed; the durable detail lives in the sections above)

- **2026-06-29 (design refactor — merged PR #25, DEPLOYED):** app-wide visual system per `docs/ui-redesign-spec.md` (presentation-only; data/routing/logic unchanged; 4 brand colors 파랑#2F58DC/초록#6AAC72/노랑#E7B23E/빨강#C73E38 kept; spec's alt hexes ignored per PM). **Nav: top bar → desktop LEFT SIDEBAR** (`components/app-nav.tsx` = `fixed w-60` aside w/ icon nav + profile card; mobile = slim sticky topbar + existing BottomNav). Body shifts via `globals.css` `body:has(.app-sidebar) main{padding-left:17rem}` (15rem sidebar + 2rem gutter; **no per-page edits**). **Tokens centralized in `app/globals.css`** (`@theme inline` + `@utility shadow-card`; added `canvas`/`brand-soft`/`pos·neg·warn`(+soft/ink) aliases derived from the 4 colors. ⚠️ `design/tokens/inpa-tokens.css` is a STALE reference, NOT active). **Dashboard (`app/home`) → 12-col (8+4) glanceable grid:** 목표+달성률 도넛게이지 / 4 StatCards(아이콘 뱃지+큰 숫자+전월대비 증감) / 단계 컬러 파이프라인+화살표 / 막대+캘린더 (좌 8); 오늘일정·유지현황·유지율·예약/판촉 CTA (우 레일 4); 하단 퀵액션 바. **환수 레이더 카드 대시보드에서 제거**(라우트 `/churn-radar`는 유지), 환수위험 stat은 4칸에서 제외. **StatCard**에 옵셔널 `icon`/`tone`(lucide) 추가. **BE:** `dashboard` 시리얼라이저에 computed `deltas`(전월 대비 %, 가산만·무마이그레이션; FE 우선 사용, 추이로 폴백). 서비스 전반 + 공개링크 4종(s/b/c/d — 동의·면책·워터마크 보존) + 어드민 20p(다크) 토큰 통일. 스크린샷 `~/Desktop/inpa-design-shots-v2/`.
- **2026-06-29 (rounds 1–3, this session):**
  - *Customer:* added `status` axis (진행중/보류/휴면/종료) + softened staleness cue; labels 칸반→단계별 / 리스트→목록; **단계별 board shows top-10 per stage + 더보기**; registration modal dropped planner-attested consent boxes (customer-self link only) + consent-aware OCR upload + 수기→직접 입력; **detail page restructured** (정보=default tab, removed from the bar, reached via summary '세부정보' link; 영업단계+상태 one row; summary 최종연락일 D+N; InfoTab 생년월일 dropdowns + live 보험나이 + editable 직업 + '동의 완료').
  - *Booking:* **→ Calendly engine** (`WorkHour` + `availability.py` free-slot generation; buffer; PENDING + accept/decline; 409 conflict; `Notification.meeting`; google push moved to accept; booking-settings + public page rewritten). Migrations `booking 0003`, `accounts 0007`, `notifications 0007`, `customers 0013` (status).
  - *Analysis:* heatmap → **traffic-light** (넉넉 green/적정 yellow/부족 red), **중립 removed** from UI (no-baseline → '기준 설정' CTA), 2-column.
  - *Dashboard/data:* premium-bar amount label moved inside the bar (white); self-diagnosis copy de-jargoned ('리드' removed); home & /schedule calendars unified to 5 categories (알림 removed); **job master → PM's 메리츠 707** + `seed_jobs` sync/prune.
  - *Customer detail (later in session):* summary card holds avatar+name+phone+최종연락 D+N+세부정보 link AND the 영업단계/상태 selectors (one card, selectors centered); InfoTab 생년월일 = year·month·day dropdowns (2:1:1 width, '년' suffix); **per-insurance cards** (분석=보유, 비교=제안 — 보험제목·종류·계약자·피보험자·월보험료·기간, via `listManualInsurances` + serializer now exposes `contractor_name`/`insured_name`); **공백(gap) tab removed** + tab bar no longer h-scrolls; **비교 분석 proposal entry** (제안서 업로드 = OCR with `portfolio_type=2` param / 직접 입력 = manual modal `defaultPortfolioType=2`) + compare table now labels each coverage 추가/삭제/변경/유지. **비교 분석 selection**: planner picks which 보유 + 제안 insurances to compare (checkboxes), `compareCustomer` POSTs `current_ids`/`proposed_ids`, aggregate + diff reflect the selection (`compare.py::_selected_ids`).
  - *Standing redline added:* easy-words · positive-framing · audience-split (§6).
- **2026-06-28 (PRs #8–16):** consent collection (`/c` multi-scope) + 402 upgrade modal (hidden in beta); Round-2 UI (2-row customer card + DotMenu body-portal, monthly-premium chart, script library); 직업급수 707 + `/jobs/search/`; em-dash purge; "이번 달 미팅" = FA-first-reach; copy-tone cleanup; security hardening (rate-limit + DB cache); content protection (`content-guard.tsx`); 판촉물 골격 (`seed_promotion`); admin usage tracking; heatmap badge = held-coverage count ("보유 N개").

## 12. Pending backlog (also memory `qa-audit-backlog`)

- ⬜ OCR remaining: 종합보험 17-22 unmatched coverages; life-insurance 변액 `company_idx=-1`. See memory `ocr-coverage-sections`.
- ⬜ At launch: flipping `FREE_TIER_UNLIMITED=False` activates 402 + the upgrade modal (already built) — verify modal copy + "1-month coupon" entitlement wiring first.
- ⬜ Booking: the legacy manual `MeetingSlot` page is now orphaned (the public flow uses work hours only) — consider removing/redirecting it. The public booking `start_at` flow is automated-test-verified but not browser-smoke-tested.
- ✅ 비교 분석 selection DONE: `compare.py::_respond` accepts `current_ids`/`proposed_ids` (GET query or POST body via `_selected_ids`; absent=all, present-empty=none) → planner checks which 보유/제안 to compare in SwitchTab (`SelectInsRow`, re-compares on toggle), aggregate + 추가/삭제/변경 reflect the selection. `compareCustomer(id, {currentIds, proposedIds})` POSTs when a selection is given.
- ⬜ `GapTab` function in `customer/[id]/page.tsx` is now dead code (공백 tab removed) — remove it + any then-unused imports on the next pass.
- ⬜ Backfill: pre-existing FA/청약 customers have `fa_reached_at=null` (not counted) — fine going forward.

## 13. Docs map (`docs/`)

- **`docs/dev/00-INDEX.md` = dev-docs master map (SSOT entry).** Full route map, doc index, stream↔entity mapping.
- `docs/dev/02-data-model-and-api.md` = data-model SSOT (42 entities + visibility matrix).
- `docs/dev/` streams: 01 architecture · 11 auth · 12 customer/OCR · 13 share · 14·16 compliance/legal · 15 dashboard · 17 boards · 18 mobile · 19 admin · 20 devops · 21 promotion · 22 notifications · 23 billing · 24 landing · 25 deploy guide (PM).
- `docs/superpowers/specs|plans/` = brainstorm specs + implementation plans. `docs/01~07` (root) = business/product planning originals. `docs/_archive-foliio/` = old archive.
- Decision history / session memory: `.claude/projects/.../memory/MEMORY.md` (+ linked: `qa-audit-backlog`, `ocr-coverage-sections`, `sqlite-vs-postgres-seed-trap`, `google-integration-planned`).
