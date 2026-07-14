# Feedback widget + admin spacing normalization + usage tracking fix — Design spec

Date: 2026-07-10 · Status: PM-approved design (this doc). A separate full-codebase bug audit (13-dimension workflow) runs in parallel; its confirmed findings are reported/approved separately and implemented alongside this spec.

## PM decisions (locked)

- Custom widget ONLY, no ChannelTalk / external chat. No auto-prompts ever (foliio's FeedbackPrompt/NPS auto-survey is explicitly NOT ported) — the widget opens only on user click, no badges/popups/reminders.
- Exposure: all logged-in planner screens + the www landing (`/`, anonymous submissions allowed). EXCLUDED: customer-facing token pages (/s /d /c /b /p), /admin, /login·/register auth pages, and the /new cinematic landing (don't break the film experience; PM can extend later).
- Storage: extend `boards.Inquiry` (reuse admin reply/status flow + admin page) — NOT a new feedback app.
- Admin must see submissions (existing /admin/inquiries) and get notified (admin bell).

## ① Feedback widget

### BE (boards app, 1 additive migration)

- `Inquiry.category` += `('feedback', '이용 의견')`.
- `Inquiry.owner` → `null=True, blank=True` (keep CASCADE for owned rows). Anonymous submissions have `owner=None`. `OwnedQuerySetMixin` filters `owner=user`, so null-owner rows never leak into planner lists.
- New fields: `rating` PositiveSmallIntegerField null (1..5, validated; feedback category only), `meta` JSONField null (bug reports auto-attach `{path, user_agent, viewport}` — admin-only surface), `contact_email` EmailField blank default '' (anonymous reply channel).
- New endpoint `POST /api/v1/feedback/` (boards, `FeedbackCreateView`, AllowAny + `ScopedRateThrottle` scope `feedback` — add rate to settings, e.g. 10/hour): accepts `{category, body, rating?, meta?, contact_email?}`; `title` auto-generated server-side (category label + body first 30 chars). If `request.user` is authenticated → `owner=user` (submission appears in their 문의 내역, reply notifications work as today); else `owner=None` (+optional contact_email). Body length cap (e.g. 2000 chars), meta key whitelist, rating clamp.
- New `NotifType.INQUIRY_RECEIVED = 'inquiry_received'` (admin-facing) added to `ADMIN_NOTIF_TYPES`; fan out to admins (pattern: `analysis/flags.py::_notify_admins`) on EVERY new Inquiry create — both the widget endpoint and the existing `/board/inquiries/` create (closes the current gap: admins are never notified of new inquiries). notifications migration = choices AlterField (no-op data).

### FE

- New `components/feedback-widget.tsx` (client). Mounted twice: (a) inside `components/app-nav.tsx` → auto-appears on every authed service page (AppNav is imported per-page; admin/public/token/auth pages don't render it); (b) directly in the landing `app/page.tsx` (anonymous mode).
- FAB: fixed bottom-right round button (chat icon + "의견" label), desktop `bottom-6 right-6`; mobile offset above `app-bottom-nav` + safe-area (landing has no bottom nav → plain bottom offset). z-index below modals (z-40 FAB / z-50 panel), never overlaps sheet/modals.
- Panel: chat-style card — header (InpaMark + "인파팀에게 들려주세요"), greeting bubble, then choice chips → inline form per mode:
  1. **이용 의견** (`feedback`): star 1..5 + textarea.
  2. **기능 제안** (`feature`): textarea.
  3. **불편 신고** (`bug`): textarea + auto-attach meta with visible one-line notice "빠른 확인을 위해 지금 보고 계신 화면 주소가 함께 전달돼요".
  4. **1:1 문의**: authed → link to `/boards/inquiry/new`; anonymous → same form as 기능 제안 but category `other` + "답변 받을 이메일(선택)" input. Anonymous 의견/제안/불편 also show the optional email input.
- Submit → thank-you bubble. Authed: "답변이 오면 알림으로 알려드려요" + 문의 내역 link. Anonymous: "이메일을 남겨주시면 답변드릴게요". Copy per §6 (easy words, positive framing, no em-dash); `check-copy.js` ROOTS already includes `components` + `lib`.
- a11y: Escape/backdrop closes, focus moves into panel, aria-labels on FAB.
- `lib/api.ts`: `submitFeedback(payload)` (public endpoint, works with or without token).

### Admin

- `/admin/inquiries`: category filter chips (전체/의견/제안/불편/기능문의/요금결제/기타), star display for feedback rows, meta block (path/UA/viewport) in the detail pane, anonymous rows labeled "비회원" + contact_email shown. BE `AdminInquiryListView` gains `?category=` filter if absent; serializers expose the new fields.
- Admin bell badge lights via `INQUIRY_RECEIVED` (existing `adminUnread` machinery — zero FE badge work).
- Anonymous rows: reply UI still works for record-keeping, but show a hint that the reply is delivered only if the PM emails the `contact_email` (no in-app recipient). Status flow unchanged.

## ② Admin spacing normalization (presentation-only)

- Centralize outer padding: `app/admin/layout.tsx` `<main>` gains `p-4 sm:p-6`; strip per-page outer paddings (`p-6`, milestones `p-5 lg:p-7`, and the three zero-padding analytics pages usage/claude-cost/activation-funnel).
- Normalize idioms across all 16 admin pages: stat cards `px-4 py-3.5` + grid `gap-3`; page `h1` `text-[22px] font-extrabold mb-6` (analytics pages keep their flex header row, add the same bottom margin); ONE boxed error-banner idiom (pick the token pair that exists in globals.css among danger-tint/danger-ink vs neg-soft/neg-ink and sweep the drifted variants); FAQ two-column body → `flex flex-col lg:flex-row gap-5` (mobile stack fix). Keep intentional max-widths (settings max-w-3xl, user-detail max-w-2xl, milestones max-w-5xl).
- No data/logic change. Verify by visual pass over every admin page.

## ③ Usage tracking fixes

- Emit missing events via `analytics/events.py::log_event` (already exception-isolated):
  - `OCR_UPLOAD` on successful planner OCR upload (`POST /customers/<id>/insurances/ocr/` success path only — NOT self-diagnosis, which is customer inbound).
  - `ANALYSIS_VIEW` on the heatmap analysis endpoint (owner as sender).
  - Honest zero: counts start at deploy; no backfill.
- `AdminUsageView`: split event types into `planner_activity` (ocr_upload, analysis_view, share_created, clipboard_copy) vs `customer_response` (share_view, callback_request, referral_attributed). Users ranking sorts by planner-activity total; response carries both groups.
- FE `/admin/usage`: two labeled column groups "설계사 활동" / "고객 반응"; sort by 설계사 활동.
- Day toggles on usage/claude-cost/activation-funnel gain `전체` (days=0 — BE already supports).
- `adminApi.ts` `AdminLoginResponse` → `{id, email}` (matches BE).

## Out of scope

ChannelTalk embed, auto NPS/survey prompts, feature-request upvotes, dedicated feedback stats dashboard, /new cinematic landing mount. Revisit post-launch if feedback volume warrants.

## Verification plan

- BE: `python manage.py test inpa` full suite + new tests: feedback endpoint (authed/anonymous/throttle/validation), INQUIRY_RECEIVED fan-out + ADMIN_NOTIF_TYPES partition, OCR_UPLOAD/ANALYSIS_VIEW emission, AdminUsageView grouping, admin category filter.
- FE: `npm run build` + `npm run lint:copy`.
- Runtime: dev servers — widget open/submit on landing (anonymous) and on a service page (authed) → row in /admin/inquiries + admin bell badge; usage page shows nonzero after an OCR upload + analysis view; visual pass over all admin pages.
- Close-out: update README.md + CLAUDE.md after merge/deploy (standing rule).
