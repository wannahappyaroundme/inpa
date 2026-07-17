# 보험증권 출시 증거 보강 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 보험 화면 테스트, 비공개 공급자 평가, PostgreSQL·Valkey·S3 동시성, 실제 브라우저 미리보기 증거를 재현 가능한 출시 게이트로 만든다.

**Architecture:** 운영 Claude 경로는 유지한다. 프런트 테스트는 CI에 편입하고, OpenAI는 evaluator-only adapter로 격리하며, staging은 production과 이름·DB·큐·저장소를 공유하지 않는다. 실제 표본·부하 결과는 aggregate-only로 남긴다.

**Tech Stack:** Next.js 16, React 19, Vitest 4, Testing Library, Django 5.2 LTS, PostgreSQL 16, Celery 5.6, Redis-compatible cache 8, S3-compatible storage, OpenAI Responses API Structured Outputs.

## Global Constraints

- `samples/`와 모든 비공개 평가 파일은 git에 추가하지 않는다.
- 디렉터리는 `0700`, 파일은 `0600`이며 파일명·원문·식별자·개별 예측을 출력하지 않는다.
- 운영 공급자는 Claude 한 곳이며 OpenAI는 평가 명령에서만 import한다.
- AI 모델 ID는 환경변수로만 주입하며 코드 기본값을 두지 않는다.
- production의 `INSURANCE_REVIEW_GATE_ENABLED`는 계속 `False`다.
- production deploy, legal gate activation, paid-mode activation은 하지 않는다.
- 사용자에게 보이는 문구는 쉬운 한국어, 긍정적 다음 행동, em dash 금지를 지킨다.
- 모든 동작 변경은 RED→GREEN 테스트 순서로 구현한다.

---

### Task 1: 프런트 보험 회귀 테스트와 CI

**Files:**
- Modify: `inpa_fe/package.json`
- Modify: `inpa_fe/package-lock.json`
- Create: `inpa_fe/vitest.config.ts`
- Create: `inpa_fe/vitest.setup.ts`
- Create/restore: `inpa_fe/components/__tests__/insurance-draft-editor.test.tsx`
- Create/restore: `inpa_fe/components/__tests__/insurance-review-workspace.test.tsx`
- Create/restore: `inpa_fe/components/__tests__/insurance-import-upload.test.tsx`
- Create/restore: `inpa_fe/components/__tests__/insurance-import-cards.test.tsx`
- Create/restore: `inpa_fe/components/__tests__/insurance-review-authority.test.tsx`
- Create/restore: `inpa_fe/components/__tests__/insurance-source-viewer.test.tsx`
- Create/restore: `inpa_fe/components/__tests__/share-public.test.tsx`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: client-only insurance components and existing ignored test archives under `.superpowers/sdd/`.
- Produces: `npm run test:run` as the tracked CI contract.

- [ ] Install exact compatible dev dependencies with npm so package and lockfile change together.

```bash
npm install --save-dev vitest@^4.1.7 jsdom@^29.1.1 @testing-library/react@^16.3.2 @testing-library/jest-dom@^6.9.1 @testing-library/user-event@^14.6.1
```

- [ ] Restore the latest file per feature from the Task 12, Task 13B1, and Task 16 archives. Do not copy Task 16's absolute module paths.
- [ ] Add failing tests for `STANDARD_MAPPING_AMBIGUOUS` and `STANDARD_MAPPING_CONTRADICTION`: show the specific easy-word guidance, move focus to the standard-path control, and keep final confirmation disabled before manual acknowledgement.
- [ ] Run those two tests and confirm failure for the missing tracked setup or missing current behavior.
- [ ] Add `test` and `test:run` scripts, jsdom config, `@` alias, jest-dom setup, automatic cleanup, and `restoreMocks`.
- [ ] Add the CI `Unit tests` step after copy guard and before build.
- [ ] Run `npm ci`, focused tests, full tests, `npm run lint:copy`, and `npm run build`.

Expected: all tracked tests pass, 149-file copy guard remains zero, and Next generates all 64 static pages.

### Task 2: evaluator-only OpenAI 비교와 표본 준비 안전장치

**Files:**
- Create: `inpa_be/requirements-eval.txt`
- Create: `inpa_be/inpa/insurances/import_openai_eval.py`
- Modify: `inpa_be/inpa/insurances/extraction_eval.py`
- Modify: `inpa_be/inpa/insurances/extraction_eval_adapters.py`
- Modify: `inpa_be/inpa/insurances/management/commands/eval_insurance_extraction.py`
- Test: `inpa_be/inpa/insurances/test_extraction_eval.py`
- Test: `inpa_be/inpa/insurances/test_import_claude.py`
- Modify: `inpa_be/.env.example`
- Modify: `docs/dev/27-insurance-review-operations.md`

**Interfaces:**
- Consumes: production `extract_pdf()` masked lines, `ClaudeExtractionPayload`, `_request_content`, provider-output privacy gate, private evaluator schema.
- Produces: diagnostic-only `openai_review/pre_review`; existing `legacy`, `review`, and release gates remain unchanged.

- [ ] Write failing tests proving `openai_review` is rejected without `OPENAI_EVAL_API_KEY` or `OPENAI_EVAL_MODEL`, provider calls remain zero when masking fails, and output PII causes a safe aggregate failure with no raw value in logs.
- [ ] Write a failing test proving release-gate evaluation ignores `openai_review` as an authority and still requires trusted Claude review/post-review evidence.
- [ ] Add evaluator-only OpenAI SDK dependency in `requirements-eval.txt`, never the production `requirements.txt`.
- [ ] Implement an adapter that lazily imports the SDK, calls Responses API Structured Outputs with `store=False`, model from `OPENAI_EVAL_MODEL`, the same Pydantic schema and masked request content, then applies `assert_provider_payload_pii_safe` before scoring.
- [ ] Extend `parse_compare()` and aggregate reporting with `openai_review` while keeping legacy compatibility and current release-gate names.
- [ ] Add env and operations documentation that states this is not production failover and not proof of OCR accuracy.
- [ ] Run focused evaluator/privacy tests, `manage.py check`, migration drift check, and full backend tests.

Expected: synthetic Claude/OpenAI comparisons are reproducible; real provider execution fails closed before a call when credentials or private truth are missing.

### Task 3: staging fixture·PostgreSQL·Valkey·private storage gate

**Files:**
- Modify: `render.yaml`
- Create: `render.staging.yaml`
- Modify: `inpa_be/.env.example`
- Modify: `inpa_be/scripts/load/insurance_import_concurrency.py`
- Modify: `inpa_be/inpa/insurances/test_import_load_script.py`
- Create: `inpa_be/inpa/insurances/management/commands/prepare_insurance_load_fixture.py`
- Create: `inpa_be/inpa/insurances/management/commands/cleanup_insurance_load_fixture.py`
- Create: `inpa_be/inpa/insurances/test_import_load_fixture.py`
- Modify: `docs/dev/27-insurance-review-operations.md`

**Interfaces:**
- Consumes: existing 20-owner runner, owner-scoped APIs, review-required job model, token auth, S3 alias, Celery queue.
- Produces: private `scenario.json`, `auth.json`, synthetic PDFs, prepared jobs, and aggregate result contract outside all worktrees.

- [ ] Write failing render contract test proving cleanup cron receives the same `REDIS_URL` and staging service names never equal production names.
- [ ] Write failing fixture tests for exactly 20 owners×3 synthetic digital PDFs, four prepared review jobs, `0700/0600` output, no real sample path, deterministic cleanup scope, and refusal unless staging/load flag is explicitly enabled.
- [ ] Write failing runner tests for drain timeout separate from 45-second request polling and owner queue/end-to-end p95 reporting.
- [ ] Connect cron `REDIS_URL`, add distinct staging blueprint names, implement fixture/cleanup commands, and add the two p95 measurements without weakening privacy allowlists.
- [ ] Start local PostgreSQL 16, Valkey 8, and MinIO with ephemeral names and volumes. Run migrations, skip-free PostgreSQL competition tests, queue ping, private-storage save/signed-read/exact-delete tests, and the 60-worker synthetic runner contract.
- [ ] Stop and remove only the explicitly named local validation containers and volumes after aggregate evidence is saved in `/private/tmp` with mode `0600`.

Expected: PostgreSQL tests have no skip, cross-owner visibility and duplicate analysis remain zero, and no production service is touched.

### Task 4: 실제 브라우저·미리보기·최종 리뷰

**Files:**
- Modify only if a verified browser finding requires a TDD fix.
- Update: `docs/dev/27-insurance-review-operations.md` with aggregate browser evidence.

**Interfaces:**
- Consumes: local synthetic account/data, local backend/frontend, approved branch.
- Produces: aggregate desktop/mobile/keyboard evidence and a preview URL only if external auth succeeds.

- [ ] Start backend and frontend on dedicated local ports with review gate closed and synthetic data only.
- [ ] In a real browser, verify desktop and mobile upload entry, progress status, consent modal focus trap/Escape/return focus, ambiguous mapping guidance and exact field focus, same-value manual confirmation, final confirmation lock, share callback success/error retry, and no horizontal overflow.
- [ ] Record accessibility violations by rule/count only; never screenshot or export real policy content.
- [ ] Push the reviewed branch, let CI run, and connect Vercel Preview only to a separately named staging API. If GitHub/Vercel auth is unavailable, record the exact auth blocker and do not substitute production.
- [ ] Run fresh full backend tests, full frontend tests, copy guard, production build, current-tree gitleaks, and an independent correctness/security/UX review.
- [ ] Confirm production gate remains closed and do not merge or production-deploy.

Expected: local real-browser evidence exists; preview deployment is either verified with its URL or explicitly blocked by authentication without any production mutation.
