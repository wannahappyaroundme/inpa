# Inpa Production Integration and Deploy Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge the committed `feat/design-refactor` and `codex/insurance-review-accuracy` work with the latest `origin/master`, preserve every independent quality gate, and verify the Vercel and Render production deployments.

**Architecture:** Build a clean integration branch from `origin/master` in a separate worktree so the uncommitted landing work in `/Users/kyungsbook/Desktop/inpa` stays untouched. Merge the design branch first, then the insurance branch, resolving configuration conflicts by keeping the union of scripts, dependencies, CI gates, and failure records. Push one reviewed integration branch, merge it to `master`, then verify production and complete the two-audience documentation closeout.

**Tech Stack:** Git worktrees, GitHub PRs, Django 5.2 LTS, PostgreSQL 16 concurrency tests, Next.js 16, React 19, npm, Vitest, Node test runner, Vercel, Render.

## Global Constraints

- Keep `/Users/kyungsbook/Desktop/inpa` uncommitted landing and documentation changes untouched and out of this deployment.
- Do not discard either branch's tests or dependencies when resolving conflicts.
- Keep compliance-sensitive feature flags closed.
- Run the full backend and frontend gates on the resolved merge before pushing.
- Merge to `master` only after GitHub checks pass.
- Roll back to the previous production commit if either production health check fails.

---

### Task 1: Create an isolated production integration branch

**Files:**
- No source files modified.
- Worktree: `/Users/kyungsbook/Desktop/inpa/.worktrees/production-integration`

**Interfaces:**
- Consumes: `origin/master`, `feat/design-refactor`, `codex/insurance-review-accuracy`
- Produces: clean branch `codex/production-integration`

- [ ] **Step 1: Reconfirm remote state and dirty-worktree isolation**

```bash
git fetch origin --prune
git -C /Users/kyungsbook/Desktop/inpa status --short
git worktree list --porcelain
```

Expected: the main worktree still has only the known landing/docs WIP; both feature branches resolve to named commits.

- [ ] **Step 2: Create the clean integration worktree from remote master**

```bash
git worktree add -b codex/production-integration /Users/kyungsbook/Desktop/inpa/.worktrees/production-integration origin/master
```

Expected: the new worktree is clean and tracks the latest fetched `origin/master` commit.

### Task 2: Merge committed design work without the local WIP

**Files:**
- Modify: `inpa_fe/package.json`
- Regenerate: `inpa_fe/package-lock.json`

**Interfaces:**
- Consumes: latest `origin/master`, committed `feat/design-refactor`
- Produces: integration branch containing landing tests and recruiting tests together

- [ ] **Step 1: Merge the committed design branch**

```bash
git merge --no-ff feat/design-refactor
```

Expected: only `inpa_fe/package.json` requires manual resolution.

- [ ] **Step 2: Resolve the frontend script and dependency union**

The resolved `scripts` must contain all of these entries:

```json
{
  "test:landing": "tsc --module commonjs --moduleResolution node --target es2020 --esModuleInterop --skipLibCheck --outDir .next/landing-tests lib/new-host-routing.ts lib/new-host-routing.test.ts lib/test-landing-content.ts lib/test-landing-content.test.ts && node --test .next/landing-tests/new-host-routing.test.js .next/landing-tests/test-landing-content.test.js",
  "test:unit": "tsx --test app/admin/recruiting/view-model.test.ts app/notifications/notification-action.test.ts components/recruiting/public-recruiting-view-model.test.ts components/recruiting/recruiting-integration.test.ts components/recruiting/recruiting-view-model.test.ts lib/admin-api-error.test.ts lib/auth-return.test.ts"
}
```

Keep `qrcode`, `@types/qrcode`, and `tsx` from the design branch.

- [ ] **Step 3: Regenerate and validate the lockfile**

```bash
npm install --package-lock-only
npm ci
npm run test:landing
npm run test:unit
```

Expected: both independent frontend test suites pass.

- [ ] **Step 4: Commit the design/master integration**

```bash
git add inpa_fe/package.json inpa_fe/package-lock.json
git commit -m "merge: master와 design-refactor 통합"
```

### Task 3: Merge the insurance analysis upgrade

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `.Codex/failures.md`
- Modify: `inpa_fe/package.json`
- Regenerate: `inpa_fe/package-lock.json`

**Interfaces:**
- Consumes: merged master/design state and `codex/insurance-review-accuracy`
- Produces: one integration branch with all product, privacy, concurrency, and frontend gates

- [ ] **Step 1: Merge the insurance branch**

```bash
git merge --no-ff codex/insurance-review-accuracy
```

Expected conflicts: CI workflow, package manifest, package lock, and the internal failure log.

- [ ] **Step 2: Resolve all conflicts by union**

The final frontend scripts must include:

```json
{
  "test": "vitest",
  "test:run": "vitest run",
  "test:landing": "tsc --module commonjs --moduleResolution node --target es2020 --esModuleInterop --skipLibCheck --outDir .next/landing-tests lib/new-host-routing.ts lib/new-host-routing.test.ts lib/test-landing-content.ts lib/test-landing-content.test.ts && node --test .next/landing-tests/new-host-routing.test.js .next/landing-tests/test-landing-content.test.js",
  "test:unit": "tsx --test app/admin/recruiting/view-model.test.ts app/notifications/notification-action.test.ts components/recruiting/public-recruiting-view-model.test.ts components/recruiting/recruiting-integration.test.ts components/recruiting/recruiting-view-model.test.ts lib/admin-api-error.test.ts lib/auth-return.test.ts"
}
```

Keep `qrcode`, `tsx`, `@types/qrcode`, Vitest, jsdom, and all Testing Library packages. In CI, run `test:landing`, `test:unit`, and `test:run`, and retain the PostgreSQL concurrency job. Combine both dated entries in `.Codex/failures.md` without deleting either lesson.

- [ ] **Step 3: Regenerate the lockfile**

```bash
npm install --package-lock-only
npm ci
```

Expected: `package-lock.json` is generated from the resolved manifest and contains no conflict markers.

- [ ] **Step 4: Commit the insurance integration**

```bash
git add .github/workflows/ci.yml .Codex/failures.md inpa_fe/package.json inpa_fe/package-lock.json
git commit -m "merge: 보험 분석 업그레이드 통합"
```

### Task 4: Run the complete pre-deploy verification

**Files:**
- No source changes expected.

**Interfaces:**
- Consumes: resolved integration branch
- Produces: deployable commit with recorded evidence

- [ ] **Step 1: Verify backend and schema state**

```bash
cd inpa_be
../.venv/bin/python manage.py check
../.venv/bin/python manage.py makemigrations --check --dry-run
../.venv/bin/python manage.py test inpa --noinput
```

Expected: system check clean, no missing migrations, full suite passes.

- [ ] **Step 2: Verify PostgreSQL concurrency gates**

```bash
cd inpa_be
../.venv/bin/python manage.py test inpa.insurances.test_import_concurrency inpa.analytics.test_share_snapshot_concurrency --settings=config.settings.test_postgres --parallel=1 -v 2
```

Expected: all tenant-isolation and row-lock tests pass against PostgreSQL 16.

- [ ] **Step 3: Verify every frontend gate and production build**

```bash
cd inpa_fe
npm ci
npm run lint:copy
npm run test:landing
npm run test:unit
npm run test:run
NEXT_PUBLIC_API_BASE=http://localhost:8000/api/v1 npm run build
```

Expected: copy guard, all three test suites, type checking, and production build pass.

- [ ] **Step 4: Verify repository hygiene**

```bash
git diff --check
gitleaks dir . --redact
git status --short
```

Expected: no whitespace errors, no secret findings, and a clean integration worktree.

### Task 5: Publish, merge, and verify production

**Files:**
- No additional source changes before the PR merge.

**Interfaces:**
- Consumes: verified integration commit
- Produces: merged `master`, Vercel frontend deployment, Render backend deployment

- [ ] **Step 1: Push the integration branch**

```bash
git push -u origin codex/production-release
```

- [ ] **Step 2: Open a ready PR to `master`**

Use the GitHub connector with base `master`, head `codex/production-release`, and include all local verification results in the PR body.

- [ ] **Step 3: Wait for required checks and merge**

Expected required checks: backend, frontend, gitleaks, PostgreSQL concurrency, and connected deployment previews. Merge only after required checks succeed.

Before merging, open the production `inpa-be` environment settings and confirm
that both `CLAUDE_MODEL_PARSE` and `CLAUDE_MODEL_BULK` are present and non-empty.
An existing Render Blueprint does not prompt for newly added `sync: false`
values. Keep `INSURANCE_REVIEW_GATE_ENABLED=False` and confirm there are no
queued or running insurance-import jobs for this first worker deployment.

- [ ] **Step 4: Verify production**

```bash
curl -fsS https://inpa-be.onrender.com/healthz/
curl -fsSI https://www.inpa.kr/
```

Expected backend body: `{"status":"ok","service":"inpa-be"}`. Expected frontend: successful HTTP response. In Render, also confirm the worker broker connection and `ready` log, the cleanup cron result, applied migrations and the new uniqueness constraints, inherited model/R2 settings, and zero queued/running imports. Sentry remains optional and is not inherited by the worker until its key is explicitly configured. Confirm all compliance and insurance-review gates remain `False`. Verify the insurance upload/review page in the browser and observe deployment status for at least five minutes.

- [ ] **Step 5: Roll back on a failed production check**

If the frontend fails, use Vercel rollback to the preceding production deployment. If the backend or worker fails, close the insurance-review gate and restore the preceding Render deploy. Do not reverse the new database migrations: `insurances.0011` has a data-cleanup reverse path. Revert the release commit on `master` only after capturing the failure evidence. After activation in a later release, stop new insurance uploads and drain the worker before every deploy because Render's maximum graceful-shutdown window is 300 seconds.

### Task 6: Close out PM and agent documentation

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`

**Interfaces:**
- Consumes: verified production result
- Produces: PM-facing and agent-facing documentation that matches production

- [ ] **Step 1: Record the shipped behavior and verification**

Update `README.md` in Korean with the insurance upload, masked external analysis, manual uncertainty review, and concurrent planner isolation. Update `AGENTS.md` in dense English with architecture, commands, conflict-resolution outcome, deployment commit, and latest test counts.

- [ ] **Step 2: Commit, push, and verify the documentation closeout**

```bash
git add README.md AGENTS.md
git commit -m "docs: 보험 분석 운영 배포 상태 반영"
git push origin master
```

Expected: the documentation commit reaches `master`; repeat the frontend and backend health checks after the resulting deployment completes.
