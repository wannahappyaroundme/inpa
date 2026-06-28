# Inpa — Agent Guide (CLAUDE.md)

> **Inpa (인파) = Insure + Partner.** AI sales-support web app for individually-contracted insurance planners (원수사/GA 위촉직). Code ported/reused from `~/Desktop/foliio` (Foliio analysis edition).
> **This file is the development SSOT, written for the AI coding agent.** The human PM does NOT read this — they read `README.md` (Korean, PM-facing). Keep this file English + dense + current; keep README Korean + PM-facing. PM communicates in Korean → reply to the PM in Korean even though this guide is English.

## Current state (as of 2026-06-28)
- **Phase 1 in progress.** Monorepo: `inpa_be/` (Django 4.2 + DRF, Python 3.11, 13 apps) + `inpa_fe/` (Next.js 16 + React 19 + TS + Tailwind; 60+ routes: public/auth/admin).
- **Deployed & live:** BE → Render (`https://inpa-be.onrender.com`, `/healthz/` returns `{"status":"ok"}`, DEBUG=False verified), FE → Vercel, DB → Neon Postgres, email → Resend. New-signup → OCR-upload flow runs in prod. (Render free tier sleeps when idle → first request is slow.)
- **Working:** Google (social login + calendar), meeting booking, personal schedule, consent flows, customer sales pipeline (kanban), OCR → coverage normalization → heatmap, dashboards (retention + manager ROI).
- **Compliance gates CLOSED via env** until legal review: medical-history collection, §97 comparison-doc publishing, overseas (Claude API) transfer.

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
- Seeds (idempotent): `seed_demo` (demo data — manual only, NOT in deploy), `seed_normalization` (coverage dict — Render runs this on every deploy), `create_admin` (back-office admin).
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
- `insurances` — insurance/coverage (owner-scoped via `customer__owner`); churn radar (`churn.py`, `is_cancelled`/`cancelled_at` → retention); public self-diagnosis (`self_diagnosis.py` `/d/<ref>`); OCR cross-verify (`verify.py`); manual insurance entry.
- `analysis` — **standard coverage tree + per-carrier coverage-name normalization dict (shared global master)**. Calc engine `calculate.py` (heatmap); switch `compare.py`+`switch_verdict.py` (KEEP/SWITCH/NEUTRAL = planner-internal ONLY, never shown to customer per §97). Core foliio-ported asset.
- `booking` — Calendly-style meeting booking: slots/meetings + public link (`public_booking.py` `/b/<token>`).
- `schedule` — personal schedule/todo/recurring-block (`ScheduleItem`, owner-scoped, FE `/schedule`). **Separate from `booking`** — the calendar just draws both. `kind` (event/todo/block = behavior) ⟂ `category` (5 types = color/legend: meeting / birthday-anniversary / expiry-renewal / work / other) + yearly-recurring birthday/anniversary (`anniversary_md`). ⚠️ **TIMEZONE rule:** single start/end = stored UTC shown KST / recurring-block `recur_*_time` = KST wall-clock stored as-is (NEVER convert — conversion shifts 9h) / all_day & timeless todo = stored KST noon.
- `dashboard` — monthly goal (manual) + actuals (computed), expected-salary multiplier. Retention 1/2/3yr (`compute_retention`; if 0 cancellations → `has_cancellation_data=false`, not computed) + manager team aggregation (`accounts/manager.py` reuses `compute_funnel`/`compute_retention`/`compute_team_roi` in a team loop; no PII; ROI labeled "estimate").
- `notifications` (alerts+reminders, incl. promo/digital-asset types) · `billing` (plans + usage limits; 402 over-limit via `credit.py`) · `boards` (board/notice/FAQ/inquiry, mixed visibility) · `promotion` (promo orders + **digital assets** `is_digital`/`digital_file`: 1 free download → 2nd+ → admin queue `PromotionDownload` + admin alert) · `admin_console` (IsAdmin back-office) · `analytics` (north-star event tracking).
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
- **Honesty redlines:** no "reviewed/safe" badges (warranty liability); AI output always carries "AI draft · final responsibility = planner" disclaimer. No one-tap auto-send (KakaoTalk can't) → clipboard-copy / open-KakaoTalk only.
- **Git:** Conventional Commits (Korean scope ok, e.g. `feat(동의)`). Small per-feature commits; don't mix refactor + feature. Commit only when the user asks. Branch before working on the default branch.

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
- **Plan 90% / Execute 10%:** new features → agree on a roadmap-style plan BEFORE coding. Present options as pros/cons with a recommendation.
- Compliance (overseas-transfer consent, improper-switching, ad review) is a feature gate — never bypass.

## Recent work & pending backlog
**Recently built:** marketing/personal-info **consent collection** (spec/plan `docs/superpowers/specs|plans/2026-06-28-marketing-consent-collection*`; reuses ConsentLog/subject; `/c` multi-scope, `/d` + registration-modal recording; consent badges with self/planner distinction; BE 107 tests). Manual insurance entry + proposal input. Share-link FE (`/s/<token>` 90d — coverage-table share, NOT a §97 comparison doc). Password change + account withdrawal (Google signups withdraw via email confirmation = deletion right; password change rotates the token to avoid logout). OCR false-positive fix (`COVERAGE_KEYWORDS`: 양성뇌종양→뇌출혈 alias removed → unmatched; 상피내암→유사암 routing). P2 UI cleanup (shared settings tabbar, mobile safe-area, data-policy raw-code removed, preset button disabled).
**Pending backlog** (also memory `qa-audit-backlog`):
- ⬜ **402 upgrade modal** — BE done (returns 402 for all 4 features); FE needs a soft notice modal + wiring at OCR/analysis/compare/promotion. Pre-launch (hidden in beta).
- ⬜ **Admin terms/flags 404** — FE `app/admin/settings/page.tsx` calls `/admin/settings/policy-versions/` (needs new `PolicyVersion` model; `ConsentLog.doc_version` is only a CharField) and `/admin/settings/flags/` (PATCH missing). Admin-only. **Compliance gates are env-controlled — do NOT let admin runtime-toggle them; recommend flags GET = read-only display.**
- ⬜ **Deploy-guide gaps** (`docs/dev/25`): `FRONTEND_BASE_URL` mislabeled optional; compliance flags undocumented; `.env.example` DB URL still MariaDB.
- ⬜ OCR remaining: 종합보험 17-22 unmatched coverages; life-insurance 변액 `company_idx=-1`. See memory `ocr-coverage-sections`.

## Docs map (`docs/`)
- **`docs/dev/00-INDEX.md` = dev-docs master map (SSOT entry).** Full route map, doc index, stream↔entity mapping.
- `docs/dev/02-data-model-and-api.md` = data-model SSOT (42 entities + visibility matrix).
- `docs/dev/` streams: 01 architecture · 11 auth · 12 customer/OCR · 13 share · 14·16 compliance/legal · 15 dashboard · 17 boards · 18 mobile · 19 admin · 20 devops · 21 promotion · 22 notifications · 23 billing · 24 landing · 25 deploy guide (PM).
- `docs/superpowers/specs|plans/` = brainstorm specs + implementation plans.
- `docs/01~07` (root) = business/product planning originals. `docs/_archive-foliio/` = old archive.
- Decision history / session memory: `.claude/projects/.../memory/MEMORY.md` (+ linked: `qa-audit-backlog`, `ocr-coverage-sections`, `sqlite-vs-postgres-seed-trap`, `google-integration-planned`).
