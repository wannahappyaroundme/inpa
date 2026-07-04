# Spec: 일일 배치 러너 + 리마인더 실제 발송 (LB #5 + #6, H-1 해소)

> Launch-blocking #5(runner) + #6(reminder producers + 8am digest), combined because #6 rides on #5.
> Problem (audit H-1): `birthday_soon`, `expiry_soon`(customer-facing), `consult_reminder`, `task_due`, `share_unread` notifications are created NOWHERE outside seed_demo — no scheduler exists in repo or render.yaml. The FE ships /settings/reminders (rule types), nav badges, and calendar legends for alerts that never fire. `notifications/admin.py` admits generation was designed for a cron never built.

## Decisions (locked)

1. **Runner = HTTP-triggered service + command wrapper.** One service function (e.g. `notifications/jobs.py::run_daily_jobs()`) called by BOTH:
   - `POST /api/v1/jobs/run-daily/` — auth via header `X-JOB-TOKEN` matched against env `JOB_RUNNER_TOKEN` (unset env ⇒ endpoint returns 404: fail-closed). Throttled. Returns per-producer counts JSON.
   - management command `run_daily_jobs` (manual/Render-Shell use).
   No Celery, no new infra. Keep total runtime well under the 120s gunicorn timeout (simple queries only).
2. **External trigger = GitHub Actions cron** `.github/workflows/daily-jobs.yml`: schedule `0 23 * * *` (= 08:00 KST) + `workflow_dispatch`, single step curling the endpoint with secret `JOB_RUNNER_TOKEN`. Retry once on non-200 (cold start tolerance; seeds are marker-no-ops now). Document required setup: GH repo secret + Render env var (comment in render.yaml envVars, sync:false).
3. **Idempotent per KST day.** Re-running the same day creates NO duplicates: each producer dedupes against existing Notification rows for the same (user, type, target, KST-day window). Ground the dedupe on the actual Notification model fields (read it first; message-string matching is acceptable only if no better key exists — prefer reference FKs/target ids where present).
4. **Producers (respect ReminderRule settings per user; all date math in KST — CLAUDE.md §7 timezone gotcha; discover the real model fields first, do not guess):**
   - `birthday_soon`: owner's active customers whose birthday (month-day) is within the rule's lead days.
   - `expiry_soon`: customer insurances with 만기/갱신 date within lead days (use the real field the churn/schedule code uses).
   - `consult_reminder`: tomorrow's (KST) confirmed meetings + 고객미팅-category schedule items.
   - `task_due`: todos due today (KST), not done.
   - `share_unread`: shares created ≥ N days ago never viewed (only if the analytics/share models make "viewed" cheap to query — if not cheap, SKIP and record why in notes; do not invent tracking).
   If `ReminderRule` lacks a per-type toggle/lead-day field for any of these, follow the existing model semantics exactly; never add fields (migration 0 for rules).
5. **Digest shape = batched individual notifications.** The 8am run creates normal typed notifications (so the existing per-menu badge partition keeps working). NO lump-sum single message. No email/SMS (BOOKING_EMAIL_ENABLED stays untouched).
6. **Dead-man heartbeat:** on success write `analysis.SeedMarker(key='daily_jobs', version=<KST date>)` (reuse the existing model — no new model). Expose nothing new in UI now (H-2 Sentry item will alert on it later).
7. **Migration count: 0.** If a producer truly cannot be built without schema change, SKIP it and record in notes (do not migrate).
8. **Out of scope:** PIPA retention deletion job (LB#10), backups (LB#4), email digests, admin UI, Sentry wiring.

## Redlines

- Notification copy: plain easy Korean, positive tone, NO em-dash, no jargon ('D-3' okay). Reuse existing notification message styles (read existing producers e.g. meeting_booked, self_diagnosis_lead).
- Owner-scoping absolute: a producer must never leak another planner's customer into a notification.
- Respect `ReminderRule` OFF = produce nothing for that user+type.

## Tests (BE)

1. Endpoint auth: no/wrong token → 404/403; correct token → 200 with counts. Env unset → 404.
2. Each producer: fixture → run → correct notification (type, user, message contains customer name); rule OFF → none.
3. Idempotency: run twice same (frozen) day → counts second run = 0, no duplicate rows.
4. KST boundary: use timezone-aware freezing consistent with existing dashboard tests' KST approach.
5. Heartbeat marker written on success.
6. Full suite green (`python manage.py test inpa`, 470+).

## Verification gates before reporting done

- `python manage.py check` + full suite (paste real tails). `makemigrations --check` = no changes.
- Local proof: seeded scratch data → run command → paste created-notification list; run again → 0 created.
- Report: files changed, producer list with dedupe keys, skipped producers + why, the exact GH secret/Render env setup lines for the PM runbook.
