# Multi-Policy Visual Comparison Copy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reframe every rendered comparison surface as a neutral visual comparison of multiple policies, using `증권 A/증권 B` without changing stored portfolio semantics or API shapes.

**Architecture:** Keep `portfolio_type`, `ai_compare`, and current/proposed response fields as backward-compatible internal identifiers. Change only rendered copy, comparison labels, obsolete switch-specific panels, seed defaults, and display labels; add a scoped copy gate so the old positioning cannot return silently.

**Tech Stack:** Next.js 16, React 19, TypeScript, Vitest, Django 5.2, Django TestCase, PostgreSQL/SQLite-compatible ORM, Render and Vercel auto-deploy.

## Global Constraints

- User-facing comparison labels are always `증권 A` and `증권 B`.
- User-facing comparison surfaces must not render `현재/제안`, `갈아타기/승환`, or `비교안내서` framing.
- Internal DB fields, API keys, and stored `portfolio_type` values remain unchanged.
- Comparison output remains factual: coverage, insured amount, premium, and numeric differences only.
- Do not add em-dashes or negative dead-end copy.
- Keep service pages light-fixed and preserve all existing loading/error/race-protection behavior.
- Production deployment is authorized by the user for this plan after tests, review, PR merge, and rollback check.

---

### Task 1: Add neutral-comparison regression gates

**Files:**
- Modify: `inpa_fe/scripts/check-copy.js`
- Modify: `inpa_fe/lib/landing-content.test.ts`
- Modify: `inpa_fe/components/__tests__/insurance-review-authority.test.tsx`

**Interfaces:**
- Consumes: existing source scanner and Vitest suite.
- Produces: a scoped CI failure when deprecated comparison framing is rendered again.

- [ ] **Step 1: Add scoped forbidden-copy rules before changing product code**

Add exact comparison surface paths and these rules to `RULES`:

```js
const MULTI_POLICY_SURFACES = [
  "app/customer/[id]/page.tsx",
  "app/faq/page.tsx",
  "app/onboarding/page.tsx",
  "app/settings/account/page.tsx",
  "app/admin/demo",
  "components/landing-sections.tsx",
  "components/brand-story-sections.tsx",
  "components/insurance-manual-modal.tsx",
  "components/insurance-manual-review.tsx",
  "components/insurance-review-cards.tsx",
  "components/upgrade-modal.tsx",
  "lib/landing-content.ts",
  "lib/compare-export.ts",
];

{ name: "교체 전제 비교 문구", re: /현재와 제안|현재 보험과 새 제안|기존과 제안|유지·전환|갈아타기|승환|비교안내서/, paths: MULTI_POLICY_SURFACES, hint: "여러 증권의 A/B 시각 비교로 표현하세요." },
```

- [ ] **Step 2: Change behavior expectations to neutral labels**

Add to `landing-content.test.ts`:

```ts
test("증권 비교 화면은 여러 증권의 중립 시각 비교로 설명한다", () => {
  const compare = PRODUCT_SCREENS.find(({ id }) => id === "compare");
  assert.equal(compare?.label, "증권 비교");
  assert.match(compare?.title ?? "", /여러 증권/);
  assert.doesNotMatch(JSON.stringify({ compare, WORKFLOW_STEPS }), /현재와 제안|갈아타기|승환|비교안내서/);
});
```

Change the two button assertions in `insurance-review-authority.test.tsx` to `증권 A` and `증권 B`.

- [ ] **Step 3: Run the new gates and verify RED**

Run:

```bash
npm run lint:copy
npx vitest run lib/landing-content.test.ts components/__tests__/insurance-review-authority.test.tsx
```

Expected: both commands fail because the product still renders old comparison framing and `A안/B안`.

---

### Task 2: Neutralize the authenticated comparison workflow

**Files:**
- Modify: `inpa_fe/app/customer/[id]/page.tsx`
- Modify: `inpa_fe/components/insurance-review-cards.tsx`
- Modify: `inpa_fe/components/insurance-manual-modal.tsx`
- Modify: `inpa_fe/components/insurance-manual-review.tsx`
- Modify: `inpa_fe/components/upgrade-modal.tsx`
- Modify: `inpa_fe/lib/compare-export.ts`
- Test: `inpa_fe/components/__tests__/insurance-review-authority.test.tsx`

**Interfaces:**
- Consumes: existing `CompareResponse`, `compareCustomer`, assignment state, and upload hooks.
- Produces: the same API calls and calculations rendered as `증권 A/증권 B` facts only.

- [ ] **Step 1: Make comparison labels invariant**

Replace conditional current/proposal label inference with:

```ts
const labelA = "증권 A";
const labelB = "증권 B";
```

Remove the `labels` state, `setLabels`, `canonical`, `aTypes`, `bTypes`, and `nextLabels` code. Preserve request numbering, stale-response rejection, and assignment defaults.

- [ ] **Step 2: Rename the selection and upload controls**

Render:

```tsx
비교할 증권 고르기 <span>증권 A {aCount} · 증권 B {bCount}</span>
```

Use `증권 추가` for the upload button, `비교 묶음 A/B` in manual forms, `증권 A/B` on assignment buttons, and `비교에서 제외` for the none state. Keep numeric `portfolio_type` values unchanged.

- [ ] **Step 3: Remove switch-specific rendered panels**

Delete the rendered `switch_warnings`, `AI 비교안내서`, tooltip, and publish button sections from the customer comparison tab. Remove now-unused publishing state and handler. Do not change backend response fields or feature gates.

- [ ] **Step 4: Rename factual output and quota copy**

Use `증권 비교표`, `증권 비교 한도`, `증권 비교표 내용 복사`, and:

```ts
const lines: string[] = ["증권 비교표"];
```

Keep the customer short disclaimer and all numeric formatting unchanged.

- [ ] **Step 5: Verify GREEN for authenticated surfaces**

Run:

```bash
npx vitest run components/__tests__/insurance-review-authority.test.tsx
npm run lint:copy
```

Expected: the authority test and scoped copy gate pass.

- [ ] **Step 6: Commit authenticated workflow**

```bash
git add inpa_fe/app/customer/[id]/page.tsx inpa_fe/components/insurance-review-cards.tsx inpa_fe/components/insurance-manual-modal.tsx inpa_fe/components/insurance-manual-review.tsx inpa_fe/components/upgrade-modal.tsx inpa_fe/lib/compare-export.ts inpa_fe/scripts/check-copy.js inpa_fe/lib/landing-content.test.ts inpa_fe/components/__tests__/insurance-review-authority.test.tsx
git commit -m "fix(보험): 증권 비교를 중립 A/B 시각화로 전환"
```

---

### Task 3: Align public landing, onboarding, metadata, and demo evidence

**Files:**
- Modify: `inpa_fe/lib/landing-content.ts`
- Modify: `inpa_fe/components/landing-sections.tsx`
- Modify: `inpa_fe/components/brand-story-sections.tsx`
- Modify: `inpa_fe/app/layout.tsx`
- Modify: `inpa_fe/app/manifest.ts`
- Modify: `inpa_fe/app/faq/page.tsx`
- Modify: `inpa_fe/app/onboarding/page.tsx`
- Modify: `inpa_fe/app/settings/account/page.tsx`
- Modify: `inpa_fe/app/legal/terms/page.tsx`
- Modify: `inpa_fe/app/admin/demo/compare/page.tsx`
- Modify: `inpa_fe/app/admin/demo/layout.tsx`
- Modify: `inpa_fe/app/admin/demo/page.tsx`
- Modify: `inpa_fe/app/admin/users/[id]/page.tsx`
- Modify: `inpa_fe/public/landing-test/compare.webp`
- Test: `inpa_fe/lib/landing-content.test.ts`
- Test: `inpa_fe/components/__tests__/service-landing.test.tsx`
- Test: `inpa_fe/components/__tests__/pricing-four-tiers.test.tsx`

**Interfaces:**
- Consumes: shared landing content constants and existing actual product gallery.
- Produces: one positioning across www landing, cinema landing, SEO metadata, onboarding, pricing, FAQ, and admin demo.

- [ ] **Step 1: Update shared landing content**

The compare product screen must use:

```ts
label: "증권 비교",
title: "여러 증권을 같은 기준으로 나란히",
description: "선택한 증권들의 담보와 보험료를 같은 기준의 표와 그래프로 확인합니다.",
imageAlt: "인파 증권 비교 실제 화면: 증권 A와 증권 B의 담보별 금액 비교",
```

The workflow step must use `여러 증권 비교` and describe A/B selection without advice or replacement language.

- [ ] **Step 2: Update both landing implementations**

Use these concepts consistently:

```ts
"여러 증권을 같은 기준으로"
"담보·보장금액·보험료 차이 비교"
"원하는 증권을 A와 B로 골라 표와 그래프로 확인"
```

Replace the hero mock rows for surrender loss and waiting-period reset with neutral policy A/B premiums and coverage differences. Replace comparison-guide pricing labels with `증권 비교` limits.

- [ ] **Step 3: Update onboarding, FAQ, settings, metadata, legal feature list, and admin demo**

Remove user-facing replacement framing. The admin demo must show only A/B premium cards, coverage table, and disclaimer; delete verdict and switch-warning cards. Preserve internal mock data for backward compatibility if other files consume it.

- [ ] **Step 4: Replace the visible comparison screenshot**

Create a temporary uncommitted capture route that renders the real `CompareBarChart` with the new `증권 A/증권 B` labels on a 1440×442 light canvas. Run the local Next app, capture that element through the in-app browser, convert the lossless capture to WebP, replace `public/landing-test/compare.webp`, visually inspect it, then remove the temporary route before staging.

- [ ] **Step 5: Verify public surfaces**

Run:

```bash
npx vitest run lib/landing-content.test.ts components/__tests__/service-landing.test.tsx components/__tests__/pricing-four-tiers.test.tsx
npm run lint:copy
```

Expected: all targeted tests and the copy gate pass.

- [ ] **Step 6: Commit public surfaces**

```bash
git add inpa_fe/lib/landing-content.ts inpa_fe/components/landing-sections.tsx inpa_fe/components/brand-story-sections.tsx inpa_fe/app/layout.tsx inpa_fe/app/manifest.ts inpa_fe/app/faq/page.tsx inpa_fe/app/onboarding/page.tsx inpa_fe/app/settings/account/page.tsx inpa_fe/app/legal/terms/page.tsx inpa_fe/app/admin/demo/compare/page.tsx inpa_fe/app/admin/demo/layout.tsx inpa_fe/app/admin/demo/page.tsx inpa_fe/app/admin/users/[id]/page.tsx inpa_fe/public/landing-test/compare.webp inpa_fe/lib/landing-content.test.ts inpa_fe/components/__tests__/service-landing.test.tsx inpa_fe/components/__tests__/pricing-four-tiers.test.tsx
git commit -m "fix(랜딩): 여러 증권 시각 비교로 문구 통일"
```

---

### Task 4: Update production seed copy and admin display labels safely

**Files:**
- Modify: `inpa_be/inpa/boards/management/commands/seed_boards.py`
- Modify: `inpa_be/inpa/boards/tests.py`
- Modify: `inpa_be/inpa/analysis/management/commands/seed_demo.py`
- Modify: `inpa_be/inpa/billing/models.py`
- Modify: `inpa_be/inpa/billing/views.py`
- Create: `inpa_be/inpa/billing/migrations/0012_neutral_comparison_labels.py`

**Interfaces:**
- Consumes: current idempotent deployment seeds and unchanged action keys.
- Produces: neutral default copy for new installs and exact-match upgrades for untouched production defaults.

- [ ] **Step 1: Write an exact-match seed regression test**

Add a `SeedBoardsNeutralCopyTests` test that creates the old official FAQ and notice body, runs `call_command("seed_boards")`, and asserts one published FAQ named `여러 증권 비교는 무엇인가요?` whose answer contains `증권 A와 증권 B` and none of the deprecated phrases.

- [ ] **Step 2: Run the backend test and verify RED**

Run:

```bash
/tmp/inpa-copy-py311/bin/python manage.py test inpa.boards.tests.SeedBoardsNeutralCopyTests
```

Expected: FAIL because the command still seeds and preserves the old copy.

- [ ] **Step 3: Implement safe production copy convergence**

Before `get_or_create`, update only rows whose question/title and answer/body exactly match the shipped old defaults. This updates untouched official data while preserving any Django Admin edits. Seed new environments with neutral copy and do not delete rows.

- [ ] **Step 4: Rename display labels without changing keys**

Keep `ai_compare`, `compare_guide`, and `limit_ai_compare` identifiers. Change only verbose/choice/API labels to `증권 비교`, then generate migration `0012_neutral_comparison_labels.py` with Django `AlterField` operations.

- [ ] **Step 5: Verify backend copy and migration**

Run:

```bash
/tmp/inpa-copy-py311/bin/python manage.py test inpa.boards.tests.SeedBoardsNeutralCopyTests inpa.billing
/tmp/inpa-copy-py311/bin/python manage.py check
/tmp/inpa-copy-py311/bin/python manage.py makemigrations --check --dry-run
```

Expected: tests pass, system check reports no issues, and no uncommitted migrations are detected.

- [ ] **Step 6: Commit backend display copy**

```bash
git add inpa_be/inpa/boards/management/commands/seed_boards.py inpa_be/inpa/boards/tests.py inpa_be/inpa/analysis/management/commands/seed_demo.py inpa_be/inpa/billing/models.py inpa_be/inpa/billing/views.py inpa_be/inpa/billing/migrations/0012_neutral_comparison_labels.py
git commit -m "fix(운영): 증권 비교 기본 문구를 중립화"
```

---

### Task 5: Documentation, full verification, review, merge, and deployment

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `docs/superpowers/plans/2026-07-20-multi-policy-visual-comparison-copy.md`

**Interfaces:**
- Consumes: completed implementation and deployment workflow.
- Produces: current PM/dev documentation, reviewed PR, and verified production deployment.

- [ ] **Step 1: Update project documentation**

Document that user-facing comparison is `증권 A/B` neutral visualization, switch-specific panels are hidden, and internal API/storage identifiers remain unchanged. Do not rewrite historical decision documents.

- [ ] **Step 2: Run full local verification**

Run:

```bash
cd inpa_fe && npm run lint:copy && npm run test:run && npm run build
cd ../inpa_be && /tmp/inpa-copy-py311/bin/python manage.py check && /tmp/inpa-copy-py311/bin/python manage.py makemigrations --check --dry-run && /tmp/inpa-copy-py311/bin/python manage.py test inpa
```

Expected: copy gate passes, 97+ frontend tests pass, production build exits 0, Django check/migration check pass, and the full backend suite exits 0.

- [ ] **Step 3: Run visual QA**

Start backend and frontend locally. In the in-app browser inspect the www landing and customer comparison at desktop and mobile widths. Confirm the replacement screenshot, A/B labels, loading/empty states, and no deprecated positioning.

- [ ] **Step 4: Request adversarial code review**

Review `origin/master..HEAD` for correctness, UX consistency, legal positioning, seed safety, migration safety, and test gaps. Fix all Critical and Important findings, then rerun affected verification.

- [ ] **Step 5: Commit documentation and fixes**

```bash
git add README.md AGENTS.md docs/superpowers/plans/2026-07-20-multi-policy-visual-comparison-copy.md
git commit -m "docs: 여러 증권 비교 운영 기준 반영"
```

- [ ] **Step 6: Push, open PR, and wait for all CI checks**

```bash
git fetch origin
git push -u origin codex/multi-policy-copy
```

Create a PR to `master`, verify the diff contains only this plan, and merge only after all required checks pass.

- [ ] **Step 7: Verify production deployment**

Confirm Vercel serves the updated www and cinema landing copy. Confirm the Render deploy for the merge commit is Live and `/healthz/` returns HTTP 200. Confirm the scoped comparison feature remains functional without enabling unrelated legal gates.

- [ ] **Step 8: Mark this plan complete**

Change every checkbox to `[x]` only after its evidence exists, commit the final status if needed, and report any intentionally unverified item.
