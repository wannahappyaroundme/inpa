# OpenAI Consultation Pilot Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let only `test@inpa.kr` record a customer consultation, create exactly one OpenAI summary per recording, and save it as an editable item in the existing multi-memo timeline.

**Architecture:** Keep the existing recording/R2/memo pipeline and add a consultation-only showcase exception guarded by environment, runtime, and per-user switches. Route the worker through provider adapters selected by environment, use OpenAI diarized transcription and strict structured summary output, and preserve the current one-to-one summary run as the one-shot authority. Preserve the current immutable `v2-30d` retention policy and its exact 720-hour enforcement without adding a migration.

**Tech Stack:** Django 5.2, DRF, Celery, PostgreSQL, private Cloudflare R2, OpenAI Python SDK, Next.js 16, React 19, TypeScript.

---

### Task 1: Preserve the exact 30-day policy

**Files:**
- Modify: `inpa_be/inpa/consultations/tests/test_models.py`
- Modify: `inpa_be/inpa/consultations/tests/test_migrations.py`
- Modify: `inpa_be/inpa/customers/tests.py`
- Modify: `inpa_be/inpa/consultations/recording_policy.py`
- Modify: `inpa_be/inpa/customers/consent_texts.py`
- Modify: `inpa_be/inpa/consultations/models.py`

- [ ] Prove the existing `v2-30d` snapshot, 30-day planner notice, and exact 720-hour production check.
- [ ] Keep the recording consent version and current database constraint unchanged.
- [ ] Confirm this feature creates no retention migration.
- [ ] Run focused tests and `python manage.py makemigrations --check`.

### Task 2: Permit only the exact showcase consultation pilot

**Files:**
- Modify: `inpa_be/inpa/consultations/tests/test_showcase_guards.py`
- Modify: `inpa_be/inpa/consultations/tests/test_summary_gates.py`
- Modify: `inpa_be/inpa/consultations/gates.py`
- Modify: `inpa_be/inpa/consultations/views.py`
- Modify: `inpa_be/inpa/consultations/summary_service.py`
- Modify: `inpa_be/config/settings/base.py`

- [ ] Replace the blanket showcase expectation with failing tests proving the extra pilot flag opens only consultation mutations for the exact configured showcase account.
- [ ] Add negative tests for flag-off, wrong email, missing showcase profile flag, and missing user pilot permission.
- [ ] Add `CONSULTATION_SHOWCASE_PILOT_ENABLED=False` and a consultation-specific permission that leaves all other showcase external actions blocked.
- [ ] Narrow the worker enqueue filter so only eligible owners can enter the queue.
- [ ] Run showcase, gate, API, and concurrency tests.

### Task 3: Add the OpenAI end-user provider adapters

**Files:**
- Create: `inpa_be/inpa/consultations/tests/test_openai_summary_provider.py`
- Create: `inpa_be/inpa/consultations/providers/openai_summary.py`
- Modify: `inpa_be/inpa/consultations/providers/base.py`
- Modify: `inpa_be/inpa/consultations/audio.py`
- Modify: `inpa_be/config/settings/base.py`

- [ ] Write failing unit tests for diarized Korean transcription, stable speaker labels, strict JSON summary, `store=False`, token/model extraction, empty and malformed responses, explicit non-receipt, and ambiguous timeout handling.
- [ ] Add `CONSULTATION_SUMMARY_PROVIDER` and `OPENAI_CONSULTATION_SUMMARY_MODEL`, both environment-selected.
- [ ] Implement direct OpenAI transcription and summary adapters without persisting transcript text.
- [ ] Convert the private object to a 16 kHz mono, 32 kbps MP3 so a 60-minute meeting stays under the OpenAI upload limit.
- [ ] Run the provider tests.

### Task 4: Route the background worker and preserve one-shot semantics

**Files:**
- Modify: `inpa_be/inpa/consultations/tests/test_summary_worker.py`
- Modify: `inpa_be/inpa/consultations/tests/test_summary_concurrency.py`
- Modify: `inpa_be/inpa/consultations/summary_worker.py`
- Modify: `inpa_be/inpa/billing/pricing.py`

- [ ] Write failing tests for the OpenAI path from ready recording to exactly one memo, no second provider call on redelivery, masked transcript input, and correct provider/model/latency/cost telemetry.
- [ ] Add provider factories and a synchronous OpenAI worker branch while preserving the existing CLOVA/Anthropic path.
- [ ] Reserve each paid step before calling the provider; retry only explicit connect non-receipt and make uncertain outcomes terminal.
- [ ] Add provider-aware cost estimation using environment-configured rates when a reliable catalog price is not available.
- [ ] Run worker, summary API, quota, and concurrency tests.

### Task 5: Expose the provider and finish the customer UI

**Files:**
- Modify: `inpa_be/inpa/consultations/tests/test_api.py`
- Modify: `inpa_be/inpa/consultations/serializers.py`
- Modify: `inpa_fe/lib/api.ts`
- Modify: `inpa_fe/components/consultation-recorder.tsx`
- Modify: `inpa_fe/components/customer-memos.tsx`
- Modify: `inpa_fe/tests/consultation-recorder.test.tsx`
- Modify: `inpa_fe/tests/customer-memos.test.tsx`

- [ ] Write failing API and component tests for OpenAI labels, one-shot completed state, multi-memo reload, manual edit retention, 30-day copy, mobile states, and consent guidance.
- [ ] Add a safe provider enum to capability and summary status responses without exposing model IDs or prompts.
- [ ] Render `OpenAI로 핵심 메모 만들기`, keep the success card terminal, and refresh the existing memo timeline when the memo arrives.
- [ ] Run focused front-end tests and the full unit suite.

### Task 6: Complete admin observability and production configuration

**Files:**
- Modify: `inpa_be/inpa/consultations/tests/test_api.py`
- Modify: `inpa_be/inpa/consultations/admin_service.py`
- Modify: `inpa_be/inpa/admin_console/views.py`
- Modify: `inpa_fe/lib/adminApi.ts`
- Modify: `inpa_fe/app/admin/consultations/page.tsx`
- Modify: `inpa_be/config/settings/prod.py`
- Modify: `inpa_be/.env.example`
- Modify: `render.yaml`
- Modify: `docs/dev/28-consultation-recording-operations.md`

- [ ] Write failing tests that the admin snapshot includes provider, model, tokens, processing seconds, outcome, and estimated cost without raw transcript or prompt.
- [ ] Add the metadata to the admin API and table with honest estimated-cost labeling.
- [ ] Preserve production retention validation at exact v2 720 hours and propagate OpenAI/pilot settings to the consultation worker.
- [ ] Document exact Render values, R2 lifecycle expectations, rollback switches, and the synthetic-audio production check.
- [ ] Run configuration and admin tests.

### Task 7: Verify, review, publish, and exercise the paid path

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`

- [ ] Apply migrations locally and inspect the resulting consultation constraints.
- [ ] Run `python manage.py check`, full backend tests, full frontend tests, copy lint, Next production build, and dependency security audits.
- [ ] Perform a correctness, tenancy, privacy, retry/idempotency, UX, and compliance review; fix every confirmed important finding.
- [ ] Update the PM README and developer SSOT with the shipped behavior, environment switches, and verification evidence.
- [ ] Fetch `origin/master`, commit only owned files, push `codex/openai-consultation-pilot`, open a PR, and wait for all CI checks.
- [ ] Merge the PR to `master`; confirm Vercel and Render deploy the merge SHA and both production health checks pass.
- [ ] Enable only the exact test-account environment/runtime/user switches.
- [ ] In `test@inpa.kr`, use consented no-PII synthetic audio to confirm upload, paid OpenAI transcription and summary, exactly one editable memo, second-summary rejection, latency/cost telemetry, and private-source cleanup behavior.
- [ ] Keep rollback ready: close `CONSULTATION_SHOWCASE_PILOT_ENABLED`, then the runtime summary/recording switches if any production check fails.
