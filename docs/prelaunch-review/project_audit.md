# Inpa — Pre-Launch Project Audit

> **Date:** 2026-07-03 · **Method:** 6 parallel area audits (backend, frontend, deploy/infra, security/privacy, demo-data/half-built, docs/claims) + adversarial completeness critic + live production probes. All claims verified against code with file:line evidence; gitignored sensitive dirs (`samples/`, `benchmark/`) untouched.
> **Purpose:** Ground truth for the multi-persona pre-launch debate. Personas must argue from THIS document, not hypotheticals.

---

## 1. Product & stack snapshot

- **Inpa (인파)** = B2B SaaS for individually-contracted Korean insurance agents (원수사/GA 위촉직). Customers are the AGENTS, not policyholders. Vision: prospecting → policy analysis → comparison → CRM in one flow.
- **Legal frame:** platform CANNOT recommend switch/cancel/renew (보험업법 §97, 금소법). It shows neutral numeric comparison tables; judgment belongs to the licensed agent. This posture is implemented in code (see §7).
- **Stack:** Django 4.2 + DRF (Python 3.11, 13 apps) on Render free tier · Next.js 16 + React 19 + TS + Tailwind v4 (62 routes) on Vercel · Neon Postgres · Cloudflare R2 media (signed URLs) · Resend email · Anthropic Claude API (pdfplumber text extraction + Claude parse; "OCR" is a legacy misnomer — image PDFs are rejected) · GitHub Actions CI (BE tests 455, FE build + em-dash copy lint + gitleaks). All infra $0.
- **BM:** freemium. Beta = unlimited (`FREE_TIER_UNLIMITED=True`, now DB-toggleable at runtime by admin). Plans seeded: free (OCR10/compare5/analysis10/promo5 per month), plus (₩29,000 placeholder, admin-editable). **No payment gateway exists** — Plus is grantable only via admin coupon or Django admin.

## 2. Live production verification (probed 2026-07-03)

| Check | Result |
|---|---|
| BE `https://inpa-be.onrender.com/healthz/` | `{"status":"ok"}` |
| FE `https://www.inpa.kr` | 200, correct OG/meta, `inpa.kr` → 308 → www |
| `in-pa.vercel.app` (documented FE URL) | **DEPLOYMENT_NOT_FOUND** — dead alias; stale refs in README/CLAUDE.md + `app/layout.tsx:15` fallback + `booking-settings.tsx:26` example copy |
| `robots.txt` | Missing (serves 404 page) |
| Public `GET /api/v1/billing/plans/` | **4 `[DEMO]` plans live and `is_active:true`** (`demo_free`, `demo_beta`, `demo_plus` ₩29,000, `demo_pro` ₩59,000) alongside real `free`+`plus` — demo data confirmed leaking in prod |

## 3. Feature inventory — built and working (verified in code)

**Auth & account.** Email signup → email-verify (hard login gate) → login with 5-fail/10-min lockout → password reset/change (token rotation) → withdrawal (hard delete, CASCADE wipes owned customers). Google login + Google Calendar (event auto-created on booking accept), env-gated dark when unset. Onboarding attestation. `accounts/urls.py:10-27`.

**Customer CRM.** Full CRUD; two orthogonal axes: `sales_stage` (DB/TA/FA/청약 funnel) ⟂ `status` (진행중/보류/휴면/종료). Board (단계별) + list views, stage deep-links, staleness cue (N일 무접촉), D-Day auto-bump on substantive PATCH, `fa_reached_at` first-FA timestamp driving "이번 달 미팅". Bulk paste-registration with editable preview table. Contact logs (5 outcomes, resets staleness). Family members, tags, contract disclosure checklist, 직업급수 707-row job master with relevance search. Consent: multi-scope signed tokens `/c/<token>`, planner-attested consents server-forced and can NEVER open the overseas gate — only customer-self consent does.

**Policy analysis pipeline (core asset).** PDF upload (412 without customer-self overseas consent → FE opens consent modal first; 503 without API key; quota check) → pdfplumber + Claude parse → standard coverage tree M2M → heatmap. Traffic-light grading (부족/적정/넉넉) ONLY when the planner set their own baseline (`PlannerBaseline`); otherwise neutral held-amounts + "기준 설정하기" CTA — never false grades. Renewal/non-renewal premium split (갱신/비갱신/적립) as facts-only tables, zero verdict words. Coverage-name normalization dict (V0, ~substring longest-first matching) + admin unmatched-log review UI. Manual (직접 입력) entry fallback wired at 3 OCR-failure call sites.

**Comparison (보유 vs 제안).** Planner selects which held/proposed policies to compare (checkboxes → `current_ids`/`proposed_ids`); table labels each coverage 추가/삭제/변경/유지; aggregate premium split deltas as absolute amounts. KEEP/SWITCH verdict is planner-internal only, never on customer surfaces. AI draft + §97 publish behind default-OFF flags (publish additionally returns 501 stub even if flipped).

**Booking (Calendly-style).** Recurring `WorkHour` → free-slot computation (meetings ± buffer, schedule blocks, all KST-aware) → public `/b/<token>` (72h) → PENDING meeting (row lock + recheck → 409) → planner accept/decline; accept auto-promotes customer to FA + creates Google Calendar event. Copy-link only (no auto-send).

**Schedule & dashboard.** Personal calendar (event/todo/recurring block ⟂ 5 color categories, yearly anniversaries), home dashboard: monthly goal + achievement donut, 4 stat cards with MoM deltas, funnel pipeline with stage conversion (snapshot, honestly labeled), premium trend, retention donut → 유지 회차 타이머 (13/25회차 imminent, auto-computed from contract date, no 연체/미납 claims — system can't know payment status). Manager dashboard: 3-level share consent (none/activity/full), per-agent KPIs, PII-masked, ROI labeled estimate.

**Growth surfaces (public token pages, all noindexed + throttled + signed).** `/s` share view (masked name, no grades, watermark + copy-deterrence) · `/d` self-diagnosis lead-gen (identity required, PDF optional, consent capture incl. optional third-party/marketing, creates owner lead + notification) · `/p` planner intro card (GET card, POST 상담신청 → lead) · `/b` booking · `/c` consent.

**Ops & platform.** Notification inbox + nav badges (13 types partitioned across menus, 60s poll) — read side works, see §5 for the producer gap. Boards/notices/FAQ/1:1 inquiries (real seeded content, 4 notices + 6 FAQs). Promotion catalog (7 samples, 1-free-then-admin-queue digital assets) — but zero design images uploaded (§5). Billing skeleton: usage metering, 402 + UpgradeModal wired at 5+ call sites (dormant in beta), admin coupon issue/redeem with expiry-aware entitlement, runtime paid-mode DB toggle via `/admin/settings`. Admin console: 14 pages, all `IsAdmin` (usage, users + read-only customer lists, inquiries, reports, orders, normalization dict CRUD, notices/FAQ, plan settings, policy versions, feature flags read-only, billing mode). North-star event analytics with bot filtering.

**Test/quality substrate.** 455 BE tests (heaviest: insurances 68, customers 66; lightest: schedule 12), CI = BE check+tests, FE build + copy lint, gitleaks. No FE test runner. CI runs on SQLite, prod is Postgres.

## 4. Feature gates (verified defaults in `config/settings/base.py`)

| Flag | Default | Effect |
|---|---|---|
| `FREE_TIER_UNLIMITED` | **True** (DB RuntimeConfig overrides env; fail-OPEN on exception) | Quota/402 disabled in beta |
| `COMPARE_AI_ENABLED` | False | AI comparison draft off (data table still works) |
| `COMPARE_PUBLISH_ENABLED` | False | §97 comparison-doc publish → 403 (and 501 stub behind it) |
| `ANALYZE_MEDICAL_ENABLED` | False | Medical-history collection blocked at API |
| `REQUIRE_CUSTOMER_SELF_CONSENT` | False | **Inert flag** — enforcement is hardcoded stricter anyway |
| `BOOKING_ENABLED` | True | Booking live |
| `BOOKING_EMAIL_ENABLED` | False | **No-op** — no sender implementation exists |
| `OCR_VERIFY_ENABLED` | True | Second Claude cross-verify per upload (2× Claude cost) |
| `GOOGLE_OAUTH_ENABLED` | False unless env set (set in prod) | Google login/calendar |

## 5. Half-built / dormant / placeholder inventory

1. **Notification/reminder PRODUCERS missing (biggest functional gap).** `birthday_soon`, `expiry_soon` (customer-facing), `consult_reminder`, `task_due`, `share_unread`, `board_comment`, `board_like` are created NOWHERE outside `seed_demo` — no cron/scheduler exists in repo or `render.yaml`. The FE ships a full `/settings/reminders` page (5 rule types), badges, and calendar legends for alerts that never fire. Live producers: `meeting_booked`, `self_diagnosis_lead`, promotion types, on-demand `unpaid_d_alert`, admin messages. `notifications/admin.py:16` admits generation was designed for a cron never built.
2. **No payment path.** Zero gateway code (no Toss/PortOne/Stripe). Flipping paid mode fires 402s whose modal copy is stale beta-era ("정식 출시 후에는…") and whose only CTA is 1:1 문의. Plus price ₩29,000 is a self-labeled unconfirmed placeholder.
3. **Promotion storefront has zero images** — `inpa_fe/public/promo/` contains only a README; all 7 seeded samples render the "이미지 없음" fallback in prod.
4. **Landing pricing card renders literal "증권 분석 월 N건 (베타 확정)"** — unresolved `N` on the most public marketing surface (`app/page.tsx:335`).
5. **Legal placeholders:** terms 시행일 "[확정 후 기재]", no 사업자등록/통신판매업 번호, no named CPO (privacy law requires one); honestly disclosed as 예비창업, must close at incorporation/paid launch.
6. **Consent revocation (철회) promised, not built.** `ConsentLog.revoked_at` fields + docstrings + customer-facing copy "언제든 수신을 거부할 수 있어요" exist; no revoke endpoint/UI anywhere.
7. **Board attachments dead-end:** metadata endpoint assumes a presigned-upload flow that has no issuance endpoint; accepts arbitrary `file_url` strings.
8. Dormant-by-design (documented): baseline presets (`PRESET_DISABLED` 400), MeetingSlot model (API removed), §97 publish stub, medical gate, business-card Vision OCR ("자동 인식은 준비 중이에요"), Kakao/Naver login rows ("준비 중" badges — violates the project's own §6c no-negative-copy redline in 3 places), `/admin/milestones` static data, `/admin/demo/*` mock showcase (admin-gated, intentional), ~1,000 lines of dead foliio rule-parser code (`ocr_parsing()` referenced JSON data file doesn't exist in repo).
9. Sentry: SDK installed, init code present, but `SENTRY_DSN` declared in NO config (render.yaml/.env.example) — prod almost certainly runs blind. FE has analytics but no error tracking.
10. Email: `EMAIL_BACKEND` defaults to console; no prod.py override; Resend vars are manual dashboard entries (blueprint has only a comment); `DEFAULT_FROM_EMAIL` default invalid (`no-reply@inpa.local`); SPF/DKIM/DMARC self-documented as open gaps (dev/20 G-3/G-6). Works today (users do sign up) but fail-silent and un-codified.

## 6. Risk register

### LAUNCH-BLOCKING

**LB-1 · Destructive `seed_normalization` on every boot silently zeroes existing analyses.**
`_cleanup()` delete-recreates the whole [표준] coverage tree with new PKs on EVERY Render boot (deploys AND free-tier cold-start wakes). CASCADE severs (a) all `InsuranceDetail.analysis_detail` M2M links the heatmap aggregates — previously scanned customers' held amounts silently drop to 0 until the same coverage name is re-uploaded by anyone — and (b) ALL `NormalizationDict` rows including `admin_verified`/`ocr_learned` (FK CASCADE via `std_detail`), destroying accumulated admin review work. "Idempotent" is count-true, identity-false; render.yaml and CLAUDE.md both mis-describe it as safe. Confirmed independently by two audit passes. `seed_normalization.py:553-612`, `analysis/models.py:57,76,128`, `insurances/models.py:109`, `calculate.py:367`, `insurances/views.py:156-163`.
*Fix direction:* natural-key upsert (never delete leaves) or post-seed re-link, plus move seeds out of the per-boot path.

**LB-2 · Consent collected on a false retention claim (PIPA cross-border).**
The `/c` overseas-transfer consent item and the OCR-upload consent modal still state "보유 기간: 처리 후 즉시 삭제" for data sent to Claude — contradicting the already-corrected privacy policy ("Anthropic의 데이터 처리·보관 정책에 따름 · 학습 미사용"). Production consents are being recorded against an overstated deletion promise; the 2026-07-01 wording fix reached only the legal pages. `/d`'s required overseas checkbox states no retention at all. `public_consent.py:57`, `components/ocr-upload.tsx:345`, vs `legal/privacy/page.tsx:79,84`.

**LB-3 · Demo data + repo-committed credentials live in prod (CONFIRMED).**
Public `GET /billing/plans/` returns 4 active `[DEMO]` plans today (live probe). `seed_demo` creates `@inpa.local` accounts `is_active=True` with the password `demoPass123!` committed in the repo — anyone with repo access can plausibly log into prod, post to shared boards, and burn Claude quota. One Render-Shell session (delete/deactivate demo plans + accounts) settles it. `seed_demo.py:62-70,440-441,1216-1232`, `billing/views.py:104-116`.

### HIGH

**H-1 · Reminder/alert engine never fires** (see §5-1). Planners configure birthday/만기 reminders that silently never arrive — a direct product-promise failure for the CRM/retention value prop, and invisible because the read-side UI all works.
**H-2 · No error monitoring anywhere.** Sentry DSN nowhere, FE error tracking absent, and this stack is full of deliberately-silent failure modes (console email fallback, credit fail-open, seed skips, FE catch-to-null on /home). Nobody would learn prod is broken.
**H-3 · No DB backup/restore.** Neon free PITR window only; no pg_dump automation, no restore runbook — while the boot path itself contains destructive seeds (LB-1, `seed_jobs` prune). A bad deploy currently has no recovery path.
**H-4 · Render free-tier cold start on customer-facing links.** `/b`, `/d`, `/c`, email-verify hit a sleeping BE: ~30-60s spin-up INCLUDING the full migrate+5-seed chain before gunicorn binds. First impression for a customer clicking an agent's link; also multiplies LB-1 (every wake re-wipes).
**H-5 · Landing pricing placeholder "월 N건"** on the public marketing page (§5-4) — violates the product's own copy redline and reads unfinished at the exact moment of first-visitor trust.
**H-6 · Legal identity placeholders** (§5-5): defensible during 예비창업, but a live PIPA gap (unnamed CPO) while actively collecting policy/lead PII; hard gate before paid launch or incorporation.
**H-7 · Consent withdrawal right promised but unimplemented** (§5-6): PIPA grants withdrawal; marketing-consent withdrawal must be as easy as consent.
**H-8 · Email transport fail-silent + un-codified** (§5-10): works today, but a lost dashboard var = every new signup dead-ends at verify-email with zero error signal (and no Sentry to notice). Verify Resend domain auth end-to-end + codify in blueprint before launch.

### MEDIUM (condensed)

- **Login endpoints have no IP throttle** (only per-email 5-fail lockout): password spraying at scale; email-keyed lockout enables targeted account-lock DoS. Admin login IS throttled; planner login is not. `accounts/views.py:130-133,177-184`.
- **PII in stdout logs:** on Claude parse failure the parser prints the first 200 chars of raw parsed-policy JSON (can include insured name/birth/coverages) to Render logs — outside every disclosed retention boundary; no LOGGING config exists. `claude_parser.py:616,631`.
- **PIPA retention/deletion gaps:** no retention automation for self-diagnosis lead PII (people who never become clients) or ConsentLog raw IPs (survive customer deletion via SET_NULL); R2 media files (business cards, profile photos) orphaned after account deletion — CASCADE removes rows, never storage objects.
- **Google OAuth verification status unknown:** `calendar.events` is a sensitive scope; if the consent screen is in Testing mode, refresh tokens expire after 7 days → calendar sync silently dies for all connected planners; 100-user cap. Nothing in repo/docs records the state. One-time Console check needed.
- **Paid-flip cliff:** flipping the (built) runtime toggle fires 402s with stale modal copy, placeholder price, and no way to pay (§5-2). Flip day needs a bundle: copy + price + payment path (or manual sales motion).
- **CI/deploy gaps:** deploys are NOT gated on CI (Vercel/Render auto-deploy on merge regardless of red checks — unless GitHub branch protection exists, unverifiable from repo); CI tests on SQLite while prod is PG (the repo's own documented bite); no rollback runbook; migrate-on-boot; FE/BE rollback skew possible.
- **`root data/` is actually committed** (3 Meritz proprietary job-grade files) despite CLAUDE.md declaring it gitignored/never-commit — policy drift + third-party data-licensing exposure if repo is ever shared.
- **`/s` share-view CTA silently does nothing** for customers when the planner has no WorkHour (`담당 설계사에게 물어보기` logs an event, no feedback) — dead-feeling button on the customer-facing surface.
- **Promotion catalog images** (§5-3): functional but looks abandoned to first users.
- **OCR inside sync gunicorn workers** (2 workers, 120s timeout, 512MB): one slow parse (up to 2 Claude calls with `OCR_VERIFY_ENABLED=True`) ties up half of serving capacity; worker-kill mid-upload = 502.
- **Unverified V0 normalization dict** re-seeded to prod every deploy; header itself demands domain-expert verification "before production use". Mitigated by neutral display + admin review path, but accuracy of the core differentiator is unaudited.
- **`SECRET_KEY generateValue`:** a blueprint resync regenerates the key → every outstanding signed link (verify/consent/booking/share) instantly invalidates.

### LOW (condensed)

Non-expiring DRF token in localStorage · Google refresh token plaintext (encryption deferred, excluded from serializers) · `/c`,`/b` tokens unrevocable within 72h TTL · 3 rendered "준비 중" strings violate the §6c copy redline (copy-guard only checks em-dash) · `/home` swallows all fetch errors to empty-looking dashboard · bottom-nav sheet per-link badges defined but never rendered (changelog claims they exist) · 3 hand-rolled fetch helpers (business-card/customer-delete/OCR upload) bypass the 401 auto-logout · FE `/p` page lacks the robots-noindex meta the other 4 public pages have (BE header still covers API) · `credit.py` fail-open + billing signal silent-skip + stale `loaddata` remediation message · `robots.txt`/sitemap absent · dead `in-pa.vercel.app` refs · doc drift: `docs/dev/00-INDEX.md` route map ~half wrong (2026-06-19 stale), dev/14's automated copy-blacklist enforcement never built (only em-dash lint), docs/06 4-tier pricing superseded but conflicting, `fa_reached_at` no backfill (known), route count 62 not ~55.

## 7. Compliance posture — verified strong

All four documented legal gates are REAL and default-closed in code; docs and code agree on the legal position:
1. §97 comparison-doc publish → 403 + 501 stub (`compare.py:382`); KEEP/SWITCH verdict never reaches customer surfaces (structurally absent from `/s` payload).
2. Overseas-transfer consent physically gates every Claude call (412 before parse; only customer-self consent opens the gate; planner-attested forgery-guarded server-side).
3. Medical/sensitive data collection blocked at API (`customers/views.py:214`).
4. 무등록중개 avoidance: no Inpa-provided 적정금액 anywhere (presets disabled), grading exists only against the planner's own baseline, neutral otherwise; premiums shown facts-only.
Also verified: policy PDFs are NEVER persisted (in-memory pdfplumber only); share payload is PII-minimized (masked name + birth year, fingerprints hashed); multitenancy checked across ~100 view classes with zero unscoped owner views found; admin console fully IsAdmin; secrets hygiene clean (gitleaks in CI, no hardcoded keys, `.env` ignored).
**But note the asymmetry:** the gates are enforced by structure + review, not by the automated word-level blocker dev/14 describes (never built) — and LB-2 shows the consent-surface copy drifting from the legal pages.

## 8. Strengths to preserve (for the debate)

- Single-point multitenancy + consent architecture that genuinely cannot be bypassed from the FE.
- Honesty-by-design: no grades without planner baseline, no payment-status claims, verdicts planner-internal — this is the moat against both regulators and trust-loss.
- The full agent workflow loop actually exists end-to-end: lead capture (`/d`,`/p`) → pipeline → analysis → comparison → booking → dashboard. Rare completeness for pre-launch.
- Ops maturity above stage: 455 tests, CI secret scanning, idempotent-ish seed chain, runtime paid-mode toggle, admin back-office for a non-dev operator.
- Docs culture: CLAUDE.md is near-perfectly accurate; drift concentrates in older planning docs.

## 9. Key facts personas must anchor on

1. Product is LIVE at www.inpa.kr with real signups; this is a pre-launch review, not greenfield.
2. The analysis heatmap is currently being silently wiped by every deploy/cold-start (LB-1) — any argument about "analysis quality" must start here.
3. Reminders/alerts — a core CRM promise — do not fire at all (H-1).
4. There is no way to pay money today (no gateway); monetization arguments must include the missing payment path.
5. Legal gates are solid; the legal risk lives in consent-copy drift (LB-2), PIPA operational duties (withdrawal, retention, CPO), and placeholder legal identity — not in the comparison feature itself.
6. Infra is $0 free-tier: cold starts, no backups, no monitoring. "Launch" at any scale collides with this immediately.
7. Core normalization dictionary is unverified V0 starter data; differentiation claims rest on it.
8. Promotion (판촉물) menu exists but has no images; marketing surfaces beyond the landing page are minimal.
9. 62 FE routes / 13 BE apps / 455 tests / all-Korean UI with strict plain-language + positive-framing copy rules.
10. Beta is free-unlimited; the paid flip is one admin toggle away but commercially unready (price placeholder, stale modal, no purchase flow).
