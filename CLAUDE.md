# Inpa — Agent Guide (CLAUDE.md)

> **Inpa (인파) = Insure + Partner.** AI sales-support web app for individually-contracted insurance planners (원수사/GA 위촉직). Code ported/reused from `~/Desktop/foliio` (Foliio analysis edition).
> **This file is the development SSOT, written for the AI coding agent.** The human PM does NOT read this — they read `README.md` (Korean, PM-facing). Keep this file English + dense + current; keep README Korean + PM-facing. PM communicates in Korean → reply to the PM in Korean even though this guide is English.

## Current state (as of 2026-06-29, after PRs #1–16 merged & deployed)
- **Phase 1 in progress.** Monorepo: `inpa_be/` (Django 4.2 + DRF, Python 3.11, 13 apps) + `inpa_fe/` (Next.js 16 + React 19 + TS + Tailwind; ~55 routes: public/auth/admin).
- **Deployed & live:** BE → Render (`https://inpa-be.onrender.com`, `/healthz/` → `{"status":"ok","service":"inpa-be"}`, DEBUG=False), FE → Vercel (`https://in-pa.vercel.app`), DB → Neon Postgres, email → Resend. **Deploy workflow = PR feat→master** (feat branch `feat/benchmark-ui-revamp` is reused across rounds; merge auto-deploys Vercel+Render). Render free tier sleeps when idle → first request slow. ⚠️ **Parallel sessions** also commit to this branch — `git fetch` + `git log origin/master..HEAD` before pushing; PRs interleave (numbers not strictly mine).
- **Working:** Google (social login + calendar), meeting booking, personal schedule, consent flows, customer sales pipeline (kanban), OCR → coverage normalization → heatmap, dashboards (retention + manager ROI), 직업급수(job-grade) search, planner script/talk library, share-view content protection, admin usage tracking.
- **Compliance gates CLOSED via env** until legal review: medical-history collection, §97 comparison-doc publishing, overseas (Claude API) transfer.
- **Shipped this session (2026-06-28/29, PRs #8–16 — see "Recent work" for the per-PR breakdown):** Round-2 UI revamp (2-row customer card + D-Day auto-update, monthly-premium chart, heatmap coverage-only toggle + 2-tier chips, script-library, booking layout); 직업급수 707 import + `/jobs/search/` + modal search & bottom-sheet; em-dash purge + beta→coupon landing; "이번 달 미팅" = FA-first-reach; dashboard notifications removed; **copy tone cleanup** (disclaimers consolidated, auto-send negatives & aggressive framing removed); **security hardening** (DoS/rate-limit + DB-cache throttle); **content protection** (share-view watermark/copy-block); **판촉물 골격** (`seed_promotion`); **admin usage tracking**; heatmap category badge = held-coverage count ("보유 N개").

## Context
- **Target users:** individually-contracted planners (sole proprietors) at carriers/GAs. Priority 1 = new planners (desperate for lead-gen); priority 2 = mid-career (management).
- **Value:** prospecting → coverage analysis → switch (갈아타기/승환) proposal in ONE flow. Analysis is the *start* of the sales action, not a report.
- **Differentiators:** (1) legitimize switching via an auto-generated 비교안내서 (comparison guide) as a §97 shield against improper-switching rules; (2) full 100+ coverage (담보) "frame" + per-carrier coverage-name normalization.
- **BM:** Freemium (all features open, free monthly quota, heavy users subscribe).
- **Org:** CPO = CTO (the user). No external legal counsel → compliance handled conservatively (safe defaults + public regulator/association guides), re-reviewed before paid launch.

## Stack
- **FE:** Next.js 16 + React 19 + TypeScript + Tailwind. Design tokens `design/tokens/inpa-tokens.css` (:root CSS vars) → Tailwind config. Logos `design/logo/*.svg`.
- **BE:** Django 4.2 + DRF + Python 3.11. Reuses foliio's `core/ocr/claude_parser`, `customers/calculate.py` (8 cases, numpy_financial), coverage-normalization **verbatim** (re-porting risk avoidance = core asset).
- **DB:** PostgreSQL (prod = Neon free; local = SQLite). MariaDB→PG switch on 2026-06-21 (Railway free tier killed); ORM-only, zero code impact, `psycopg2-binary`.
- **AI:** Anthropic Claude API. Model ids injected via env ONLY — `CLAUDE_MODEL_PARSE` (Opus: comparison/normalization), `CLAUDE_MODEL_BULK` (Haiku: bulk OCR), nightly = Batches. NEVER hardcode model ids.
- **Deploy:** FE→Vercel, BE→Render (`render.yaml`), DB→Neon, email→Resend, CI=GitHub Actions. All GitHub-connected auto-deploy, $0.
- **Local-only dirs (gitignored, NEVER commit or quote):** `samples/` = real policy PDFs (PII/sensitive); `benchmark/` = UI reference screenshots. Root `*.jpeg`/`calender*.webp` are committed design refs.

## Commands
Monorepo — run BE commands in `inpa_be/`, FE in `inpa_fe/`.

### Backend (`inpa_be/`)
- Setup: `pip install -r requirements.txt` (venv). Default settings = `config.settings.local` (SQLite; `manage.py` sets it).
- Run: `python manage.py runserver` → :8000 (API root `/api/v1/`, health `/healthz/`).
- Migrations: `python manage.py makemigrations` → `migrate`.
- Tests: all = `python manage.py test inpa`; app = `python manage.py test inpa.booking`; single = `python manage.py test inpa.accounts.tests.LoginTests.test_x`.
- Pre-deploy check (required): `python manage.py check`.
- Seeds (idempotent): `seed_demo` (demo data — manual only, NOT in deploy), `seed_normalization` (coverage dict), `seed_jobs` (직업급수 707-row JobRiskCode from `inpa/customers/data/job_risk_codes.json`, bulk upsert), `seed_promotion` (판촉물 카테고리 골격: 명함/달력/리플렛/팜플렛/파일보관함), `create_admin` (back-office admin). Render `startCommand` chain = `migrate → createcachetable → seed_normalization → seed_jobs → seed_promotion → gunicorn` (all idempotent, run every deploy; `createcachetable` backs the DB cache used by rate-limit throttling).
- Django admin `/admin/`. Ops back-office = separate `admin_console` API + FE `/admin/*`.

### Frontend (`inpa_fe/`, Node 20)
- Setup: `npm ci`. Dev: `npm run dev` → :3000. Build: `npm run build` (**also typechecks — the ONLY FE gate; there is no FE test runner or lint script**). Prod: `npm start`.
- BE URL = `NEXT_PUBLIC_API_BASE` (fallback `localhost:8000/api/v1` + console warning if unset). **Build-time inlined → redeploy Vercel after changing the env var.**
- ⚠️ **Next 16 differs from training data** (`inpa_fe/AGENTS.md`): read `node_modules/next/dist/docs/` for the relevant guide before writing Next-API code.

### CI / Deploy (`.github/workflows/ci.yml`)
- On push/PR to main·master: (1) BE `check`+`test inpa`, (2) FE `npm ci`+`build`, (3) gitleaks secret scan.
- Deploy is NOT CI — Vercel(FE) + Render(BE, `render.yaml`) auto-deploy from GitHub; DB = Neon.

## Architecture (big picture — spans multiple files)

### Request flow
Browser → Next page (`inpa_fe/app/**`) → **`inpa_fe/lib/api.ts`** (single BE-call gate: all endpoints+types in one file; admin in `lib/adminApi.ts`) → DRF `/api/v1/` (`config/urls.py` fans out to per-app `urls.py`) → ViewSet → model. Auth = DRF TokenAuthentication; token in FE `localStorage['inpa_token']` (`tokenStore`). Error bodies `{error|code|detail}` → normalized to FE `ApiError` (carries `.status`, `.code`, message).

### Multitenancy (visibility) — enforced in ONE place, never bypass
`inpa/core/mixins.py::OwnedQuerySetMixin` (filters to own rows + auto-injects owner on create) + `inpa/core/permissions.py::IsOwner`/`IsAdmin`/`IsEmailVerified`. **Owner-scoped ViewSets MUST attach this mixin + IsOwner.** Admin (`profile.is_admin`) bypasses read. Shared exceptions only: boards/notices/FAQ/promo-samples. SSOT: `docs/dev/02` §0 visibility matrix.

### Django app map (`inpa_be/inpa/`, 13 apps; `core` is a shared package)
- `accounts` — User (email PK), Profile, auth (signup / email-verify / login-lock / password-reset / password-change / withdrawal), Google (`google.py` social login, `google_calendar.py`), onboarding, manager dashboard (`manager.py`).
- `customers` — customer CRUD; consent log (`ConsentLog`); customer-self public consent (`public_consent.py` `/c/<token>`); baseline presets (`presets.py`). `sales_stage` (db/contact/meeting/contract → shown DB/TA/FA/청약); favorite/pin/last-contact (staleness color alert); avatar color; business card; insurance age (`compute_insurance_age`); contract disclosure checklist (`ContractChecklistItem`, `/customers/<id>/checklist/`).
  - **D-Day auto-update** (`views.py::CustomerViewSet.perform_update`, `SUBSTANTIVE` set): a PATCH touching substantive fields (memo/info/`sales_stage`/churn…) bumps `last_contacted_at=now`; favorite/pin toggles do NOT. **PM decision: a kanban stage move IS an action → `sales_stage` is in SUBSTANTIVE (counts as contact).**
  - **`fa_reached_at`** (Customer field, `models.py::save()` hook): timestamp the FIRST time `sales_stage` becomes `meeting`(FA); never overwritten → DB→TA→FA / FA→청약→FA re-entry is NOT recounted. Drives the dashboard "이번 달 미팅" metric (see `dashboard`).
  - **`JobRiskCode`** = 직업급수 global master (shared, read-only, owner-agnostic; 707 메리츠 jobs via `seed_jobs`; fields: name/alt_name/risk_grade 1·2·3·9/synonym/description/kidi_cd). `Customer.job_code` FK. Search: `GET /api/v1/jobs/search/?q=` (`views.py::JobSearchView`, IsAuthenticated, substring match on name+alt+synonym+kidi, relevance-ranked; mounted top-level `jobs/search/` to dodge the `customers/<pk>` router). FE: registration modal "직업급수 찾기".
- `insurances` — insurance/coverage (owner-scoped via `customer__owner`); churn radar (`churn.py`, `is_cancelled`/`cancelled_at` → retention); public self-diagnosis (`self_diagnosis.py` `/d/<ref>`); OCR cross-verify (`verify.py`); manual insurance entry.
- `analysis` — **standard coverage tree + per-carrier coverage-name normalization dict (shared global master)**. Calc engine `calculate.py` (heatmap); switch `compare.py`+`switch_verdict.py` (KEEP/SWITCH/NEUTRAL = planner-internal ONLY, never shown to customer per §97). Core foliio-ported asset.
- `booking` — Calendly-style meeting booking: slots/meetings + public link (`public_booking.py` `/b/<token>`).
- `schedule` — personal schedule/todo/recurring-block (`ScheduleItem`, owner-scoped, FE `/schedule`). **Separate from `booking`** — the calendar just draws both. `kind` (event/todo/block = behavior) ⟂ `category` (5 types = color/legend: meeting / birthday-anniversary / expiry-renewal / work / other) + yearly-recurring birthday/anniversary (`anniversary_md`). ⚠️ **TIMEZONE rule:** single start/end = stored UTC shown KST / recurring-block `recur_*_time` = KST wall-clock stored as-is (NEVER convert — conversion shifts 9h) / all_day & timeless todo = stored KST noon.
- `dashboard` — monthly goal (manual) + actuals (computed in `aggregation.py`), expected-salary multiplier. **`compute_actuals` meetings = distinct customers who first reached FA this month** (`Customer.fa_reached_at__year/month`), NOT `booking.Meeting` (decoupled — booking confirmation count is irrelevant to this metric); premium = this-month registered-policy monthly-premium sum; new_customers = this-month created. Retention 1/2/3yr (`compute_retention`; if 0 cancellations → `has_cancellation_data=false`, not computed) + manager team aggregation (`accounts/manager.py` reuses `compute_funnel`/`compute_retention`/`compute_team_roi` in a team loop; no PII; ROI labeled "estimate"). **FE home dashboard calendar draws ONLY my schedule items + booking meetings (notifications removed → top-right bell); legend = 4 kinds (일정/할일/차단/미팅).** (The `/schedule` tab calendar keeps its own 5-category legend — that is correct, distinct from this.)
- `notifications` (alerts+reminders, incl. promo/digital-asset types) · `billing` (plans + usage limits; 402 over-limit via `credit.py`) · `boards` (board/notice/FAQ/inquiry, mixed visibility) · `promotion` (promo orders + **digital assets** `is_digital`/`digital_file`: 1 free download → 2nd+ → admin queue `PromotionDownload` + admin alert; **category skeleton** 명함/달력/리플렛/팜플렛/파일보관함 via `seed_promotion`; category = free string, the consts are just standard tags) · `admin_console` (IsAdmin back-office; **usage tracking** = per-planner feature-usage aggregation, demo accounts excluded, FE `/admin/usage`) · `analytics` (north-star event tracking).
- **Security hardening (`f535cd9`, 2026-06-28 audit):** DRF rate-limit throttling backed by Django **DB cache** (`createcachetable` in Render startCommand) — anti DoS / cost-bomb (OCR/AI) / credential brute-force. **Content protection** = FE `components/content-guard.tsx` on the share view (`/s`): watermark + copy-block + global image-save deterrence + console warning (deterrent, not real DRM).
- `core` — shared mixins/permissions + `core/ocr/` (foliio vendored: `claude_parser.py`, `ocrparsing.py`, `ocrdata.py` carrier codes).

### OCR → analysis pipeline (the core foliio-reuse flow)
Policy PDF upload (`POST /customers/<id>/insurances/ocr/`) → `core/ocr/claude_parser` (pdfplumber + Claude Opus; `ANTHROPIC_API_KEY`-gated, 503 if unset; `max_tokens=8192`) → `CustomerInsuranceDetail` (`InsuranceDetail.analysis_detail` M2M maps to standard tree) → `analysis/calculate.py` sums `held_amount` per leaf → if a `PlannerBaseline` matches → `graded` (부족/적정/넉넉 = lacking/adequate/ample); else `neutral` → heatmap/share view.
Normalization SSOT: `core/ocr/ocrparsing.py::COVERAGE_KEYWORDS` — ONE dict shared by both pipelines (text-line `_match_coverage`; Claude `_match_by_keywords` via `_KEYWORD_TO_PATH`). Matching = **substring (`if kw in name`) + longest-keyword-first**. Fix mis-matches in dict DATA, not logic (see Gotchas).

### Public (unauthenticated) token endpoints — 1:1 with FE routes
`/s/<token>` (share view) · `/b/<token>` (booking) · `/c/<token>` (customer-self consent) · `/d/<ref>` (self-diagnosis). All use TimestampSigner tokens + ScopedRateThrottle. FE at `app/s|b|c|d/[token]/`.

### Settings & feature gates (`settings/base.py` — env-controlled, NEVER bypass in code)
- Env split: `local` (SQLite, DEBUG, console email, `/media/` local serve) ↔ `prod` (Postgres `DATABASE_URL`, whitenoise, security headers, Sentry; **fail-loud if SECRET_KEY unset**).
- Media (uploads: cards, digital assets) — **no AWS required**, 3 prod modes by priority: (1) S3-compatible object storage (`AWS_STORAGE_BUCKET_NAME`+`AWS_*`; **Cloudflare R2** recommended free: `AWS_S3_ENDPOINT_URL`=R2, `REGION=auto`; private signed URLs protect PII); (2) Render persistent disk (`MEDIA_DISK_PATH`, paid, single instance); (3) local-temp (unset — lost on redeploy). Local dev serves `/media/`.
- **Compliance gates (default CLOSED):** `COMPARE_AI_ENABLED` (switch AI draft) · `COMPARE_PUBLISH_ENABLED` (customer send — §97 hard-block pre-legal) · `ANALYZE_MEDICAL_ENABLED` (BE blocks medical collection) · `REQUIRE_CUSTOMER_SELF_CONSENT`.
- **Feature flags:** `FREE_TIER_UNLIMITED` (beta quota bypass — currently True, so 402 never fires) · `BOOKING_ENABLED` · `OCR_VERIFY_ENABLED` · `GOOGLE_OAUTH_*` (unset = feature hidden).

## Conventions & redlines
- **Theme guardrail:** service pages = **light-fixed**; dark mode = **admin only** (`app/admin/layout.tsx` `.theme-system`). NEVER add `dark:` variants to service screens.
- **Copy:** product UI = plain language, NO `§`/legal-clause notation in service copy. (Internal/planner-only boxes may reference §97.)
- **NO em-dash (`—`, U+2014) in user-facing copy** — PM finds it "AI-sounding." Use comma / period / colon / parentheses / a Korean particle instead. No-value placeholder = `-` (hyphen), never `—`. The middle-dot `·`, hyphen `-`, and en-dash `–` are fine. Code comments are exempt (users don't read them). When sweeping, only touch rendered strings.
- **Honesty redlines (still hold, but DISCLAIMERS ARE CONSOLIDATED — PM 06.28):** no "reviewed/safe" badges (warranty liability). The "AI 초안 / 인파는 보험 중개 안 함" disclaimer must exist, but ONLY at official spots — **signup/onboarding, 약관(terms), data-policy page, and customer-facing AI output (`/s` share, `/d` self-diagnosis, the AI 비교초안 box)** — as ONE brief line each. Do NOT sprinkle it on every component/card (PM found it fear-mongering & spammy). Unified wording: *"인파는 보험을 중개·권유하지 않는 분석·정리 소프트웨어입니다. 보장 판단과 고객 안내는 설계사님의 업무이며, 산출물은 AI가 정리한 참고 자료입니다."*; customer-output short form: *"인파가 등록된 보장 정보를 정리한 참고 자료입니다."* Tone = factual ("중개 안 하는 도구"), NOT blame ("모든/최종 책임은 설계사").
- **Copy tone redlines (PM 06.28):** (a) NO "자동 발송 없음 / 안 만들었다" negatives — they read as an unfinished product; use positive instructions ("복사해 고객에게 전달하세요"). (b) NO aggressive/defensive legal framing in product copy ("분쟁 대비 자료", litigation/evidence tone → use "고객 안내 이력 / 상담 기록"); the formal ToS legal clauses (분쟁해결·준거법·면책 article) stay as-is. (c) Business-professional Korean, not casual ("아는 고객에게만" → "수신 동의를 받았거나 거래 관계가 있는 고객에게만"). One-tap auto-send still does not exist (KakaoTalk can't) → clipboard-copy / open-KakaoTalk; just don't phrase it as a *lack*.
- **Git:** Conventional Commits (Korean scope ok, e.g. `feat(동의)`). Small per-feature commits; don't mix refactor + feature. Commit only when the user asks. Branch before working on the default branch.
- **Docs upkeep (standing PM rule):** whenever a feature is fully implemented AND merged to master AND deployed, UPDATE both `README.md` (Korean, PM-facing — add a dated session bullet) and this `CLAUDE.md` (current state + the affected sections). The PM reads README every session; the agent reads CLAUDE.md every run, so both must reflect reality. Do this as the closing step of a deploy, without being re-asked.

## Gotchas (read BEFORE touching the area — these have bitten)
- **Email verification = BE self-contained token** (`accounts`): `signing.dumps(pk)` → both link and verify use `token` ONLY, no `uid` (UNLIKE reset-password). **If FE requires `uid`, signup is fully blocked — do NOT regress.** Resend button exists.
- **Consent token is multi-scope** (`customers/tokens.py`): `make_consent_token(customer, scopes=None)`; `read_consent_token` returns `{pk, scopes}` (legacy bare-int tokens normalize to `{pk, scopes:['overseas_medical']}` — keep backward compat). `/c` GET returns `items[]`; POST body `{agreed:[scope]}`; only token-scoped consents are recorded (forgery guard); required scope unmet → 412.
- **Consent subject enforcement:** planner-recorded consents are `subject=planner_attested` (server-forced, serializer read_only) and CANNOT open the `consent_overseas_at` gate; only `customer_self` (via `/c` or self-diagnosis) opens it.
- **OCR normalization substring trap** (`core/ocr/ocrparsing.py::COVERAGE_KEYWORDS`): substring + longest-first matching means a coverage name containing a shorter keyword gets mis-routed (e.g. '상피내암' contains '암진단'). Fix in dict DATA (remove bad alias / add a correct longer keyword), NOT the matching logic. No migration (Python constant). Add a regression test calling `_match_coverage` directly.
- **`NEXT_PUBLIC_API_BASE` build-time inline:** changing it in Vercel needs a redeploy. If prod FE calls localhost, it's unset/not-redeployed.
- **`FRONTEND_BASE_URL` is effectively required** (default `localhost:3000`): unset in prod → email-verify / consent / booking links generate as localhost = broken. (Mislabeled "optional" in `docs/dev/25`.)
- **402 hidden in beta:** `FREE_TIER_UNLIMITED=True` bypasses all limit checks → 402 never fires now. BE already returns 402 `{code:'credit_exhausted', kind, limit, used}` for OCR/analysis/compare/promotion. Flipping the flag at launch without an FE notice modal = users see red errors.
- **SQLite vs Postgres seed trap** (memory `sqlite-vs-postgres-seed-trap`): local SQLite ignores varchar length, prod PG rejects. Validate seeds/fixtures against PG too. Prod `seed_demo` is manual via Render Shell.

## Pre-build compliance gates (zero code until resolved)
1. Coverage baseline (core 담보) source + disclaimer definition.
2. Medical (sensitive) data → Claude API overseas-transfer consent form — **legal prerequisite**.
3. Switch comparison-doc §97 legal requirements finalized.
→ Do NOT start AI-analysis / comparison-doc features before these 3. If blocked, build OCR + coverage table (neutral features) first. Build order (docs/07 §0): common components → OCR + normalization → coverage table → switch comparison → customer message → customer detail / gaps.

## Locked product decisions
- **Auth = email/password + Google OAuth** (KakaoTalk dropped). Signup → email-verify → login → password-reset (email token). PBKDF2 hash; Django signed tokens. Google login links to an existing account by verified email; new Google users collect credential/affiliation in onboarding. Google Calendar auto-creates an event on meeting confirm (name masked by default). All behind `GOOGLE_OAUTH_*` (unset = hidden).
- **Data visibility:** boards (SNS feed) / notices / FAQ / promo samples = **shared** (all planners). Everything else (customers, consent, insurance, analysis, compare, calendar, KPI, alerts, baselines) = **owner-only** (`OwnedQuerySetMixin`+`IsOwner`). 1:1 inquiry = author+admin. Promo orders = owner+admin. `Customer.owner on_delete=CASCADE`.
- **Landing** (`/`, public): hero "설계사님은 클로징만 준비하세요" (you just prepare the closing). `AudienceSection` (individual vs manager) + manager taglines.
- **Promotion** = sample photo + Google-form-style input + booking → ops team manual production (no auto-send). (Old "promotion auto-generate 14 types" model dropped.)
- **Freemium quota:** beta unlimited (`FREE_TIER_UNLIMITED`); numbers/payment post-launch. `PlannerBaseline` presets: beta is direct-input only.
- **Dropped/deferred:** business-card Vision OCR = deferred (manual fallback). Point/cash rewards = improper-benefit risk under Insurance Business Act §98 → dropped; redesign to SaaS-benefit/activity-based later (legal hold). "지점장"→"관리직" wording is UI copy only.

## Working with the PM
- PM is **non-developer**, communicates in **Korean**, reads `README.md` only (not this file). Reply in Korean, plain words, no consulting jargon.
- **Plan 90% / Execute 10%:** new features → agree on a roadmap-style plan BEFORE coding. Present options as pros/cons with a recommendation. The PM often pushes "바로 해줘" (just do it) — honor momentum, but for **schema/migration or semantic-redefinition changes still surface a 2-line plan + confirm** before coding (cheap insurance against building the wrong thing).
- Compliance (overseas-transfer consent, improper-switching, ad review) is a feature gate — never bypass.
- **Close every deploy by updating README.md + CLAUDE.md** (see Conventions → Docs upkeep). Standing rule, do it unprompted.

## Recent work & pending backlog
**Shipped & deployed (2026-06-28, PRs #8–11):**
- **PR #8** — marketing/personal-info **consent collection** (`/c` multi-scope, `/d` + registration-modal, self vs planner_attested badges, BE 107 tests); **402 upgrade modal** (FE soft-notice + wiring at OCR/analysis/compare/promotion — hidden while `FREE_TIER_UNLIMITED=True`); **admin terms/flags** (`PolicyVersion` model + GET/POST; feature-flags GET read-only — runtime toggle BLOCKED since gates are env-controlled, PATCH→405); OCR false-positive fix; deploy-guide gaps closed; CLAUDE.md rewritten to English.
- **PR #9 (Round-2 UI + 직업급수)** — 2-row customer card + ⋯menu (DotMenu via **body portal**, escapes kanban `overflow-x-auto`) + D-Day auto-update; monthly-premium chart (period filter, gray target / blue avg overlay lines, bar-area `relative` so lines map to the 96px box); heatmap coverage-only toggle + mobile-1-row/desktop-2-tier chips; script-library +4 categories; booking-settings inline layout; **직업급수 707 import + `/jobs/search/` + modal job-search + bottom-sheet drag.** Reviewed by a multi-dimension adversarial workflow (9 findings fixed).
- **PR #10 (copy)** — em-dash purged from all user-facing copy; beta-free → "최초 가입 1달 무료 쿠폰" landing.
- **PR #11 (dashboard)** — "이번 달 미팅" = FA-first-reach (`fa_reached_at`, dedup, booking-independent); dashboard notifications removed; calendar legend → 4 kinds.
- **PR #13 (copy tone)** — disclaimers consolidated to official spots + business tone; auto-send negatives removed (positive instructions); aggressive "분쟁 대비" framing softened; informal "아는 고객" → business (see Conventions → Honesty/Copy-tone redlines). Bundled with a security-hardening commit (`f535cd9`: DoS/rate-limit + `createcachetable` in Render startCommand) + 판촉물 image-fit fix authored in a parallel session.
- **PR #14** — bug fixes: heatmap category badge showed the raw `insurance_type` int → first changed to `get_insurance_type_display()` label, then **PR #16 corrected it to the held-coverage COUNT** ("보유 N개", computed in `heatmap.tsx` from `heatmap.tree` so it equals 보장 내역, filter-independent) — that was the PM's actual intent; InfoTab save-success message now clears when the form is edited again (useEffect on field state); 설명의무 체크리스트 note trimmed (dropped the record-for-later framing). Bundled with parallel-session features: **content protection** (`content-guard.tsx`: share-view watermark + copy-block + global image-save deterrence) and **판촉물 골격** (category constants + `seed_promotion`).
- **PR #16** — heatmap badge = held-coverage count (see PR #14 note). Bundled with parallel-session **admin usage tracking** (`admin_console` per-planner feature-usage aggregation, demo accounts excluded; FE `/admin/usage`).
**Pending backlog** (also memory `qa-audit-backlog`):
- ⬜ OCR remaining: 종합보험 17-22 unmatched coverages; life-insurance 변액 `company_idx=-1`. See memory `ocr-coverage-sections`.
- ⬜ At launch: flipping `FREE_TIER_UNLIMITED=False` activates 402 + the upgrade modal (already built) — verify the modal copy + the "1-month coupon" entitlement wiring before flipping.
- ⬜ Backfill consideration: pre-existing FA/청약 customers have `fa_reached_at=null` (not counted in any month) — fine going forward; revisit only if historical meeting counts are needed.

## Docs map (`docs/`)
- **`docs/dev/00-INDEX.md` = dev-docs master map (SSOT entry).** Full route map, doc index, stream↔entity mapping.
- `docs/dev/02-data-model-and-api.md` = data-model SSOT (42 entities + visibility matrix).
- `docs/dev/` streams: 01 architecture · 11 auth · 12 customer/OCR · 13 share · 14·16 compliance/legal · 15 dashboard · 17 boards · 18 mobile · 19 admin · 20 devops · 21 promotion · 22 notifications · 23 billing · 24 landing · 25 deploy guide (PM).
- `docs/superpowers/specs|plans/` = brainstorm specs + implementation plans.
- `docs/01~07` (root) = business/product planning originals. `docs/_archive-foliio/` = old archive.
- Decision history / session memory: `.claude/projects/.../memory/MEMORY.md` (+ linked: `qa-audit-backlog`, `ocr-coverage-sections`, `sqlite-vs-postgres-seed-trap`, `google-integration-planned`).
