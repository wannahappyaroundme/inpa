# Guided Talk Playbooks Implementation Plan

> PM approved direct execution and production deployment on 2026-07-29. No additional approval checkpoint is required.

**Goal:** Add two modern guided customer-sales playbooks with objection branches while preserving all existing quick-copy and personal-template behavior.

**Architecture:** Keep the existing 30-copy registry and personal-template API untouched. Add a versioned frontend-only playbook registry and a focused guided UI component, then integrate it into `/scripts` as the default mode. Replace generated customer-name query strings with owner-scoped customer ID lookup. No migration.

**Stack:** Next.js 16, React 19, TypeScript, Tailwind v4, Vitest/Testing Library, existing Vercel Analytics and API gateway.

---

## Task 1: Lock the playbook content contract with failing tests

**Files**

- Create: `inpa_fe/lib/guided-talk-playbooks.ts`
- Create: `inpa_fe/lib/guided-talk-playbooks.test.ts`

**Steps**

1. Write tests for two unique playbooks, stable version/key format, expected step counts, unique step keys, and valid objection references.
2. Write safety tests for disclosure in the first step, terminal opt-out/re-refusal, forbidden claims, company/product names, fear and discriminatory wording.
3. Write substitution tests for empty and complete customer/planner/referrer variables.
4. Run the new test and confirm it fails because the registry does not exist.
5. Implement the smallest typed registry and renderer that makes the tests pass.
6. Run the test again and confirm green.

## Task 2: Build the guided playbook interaction test-first

**Files**

- Create: `inpa_fe/components/guided-talk-playbooks.tsx`
- Create: `inpa_fe/components/__tests__/guided-talk-playbooks.test.tsx`

**Steps**

1. Write component tests for playbook selection, current-step semantics, previous/next navigation, free stage jumping, and final actions.
2. Write tests for objection open/close focus behavior and terminal branch copy.
3. Write tests proving copy receives only rendered `spokenText`, never goal/checklist/coach content.
4. Write tests for analytics payload allowlists with no customer/referrer/name/text fields.
5. Run and observe the expected component-not-found failure.
6. Implement the responsive three-area/single-column component with accessible controls.
7. Run focused tests until green.

## Task 3: Integrate `실전 상담 | 빠른 문구` without regressing the library

**Files**

- Modify: `inpa_fe/app/scripts/page.tsx`
- Modify: `inpa_fe/components/__tests__/scripts-page.test.tsx`

**Steps**

1. Add failing page tests for default guided mode, switching to quick mode, query-driven quick mode, and preservation of existing quick filters/actions.
2. Add referrer local input visible only where guided copy needs it.
3. Reuse the existing profile/customer variables and share dialog for customer-sendable follow-up text only.
4. Keep personal-template loading/error independent so the guided registry remains usable.
5. Run focused page tests and fix only integration regressions.

## Task 4: Remove customer names from generated URLs

**Files**

- Modify: `inpa_fe/components/call-list.tsx`
- Modify: `inpa_fe/app/customer/[id]/page.tsx`
- Modify: `inpa_fe/app/scripts/page.tsx`
- Modify: `inpa_fe/components/__tests__/scripts-page.test.tsx`
- Modify or create focused tests for call-list/customer detail links where current coverage exists.

**Steps**

1. Add failing assertions that every generated scripts link uses `customerId` and contains no encoded name.
2. Add page tests for successful `getCustomer`, 404/failure fallback, and a late response not replacing manual input.
3. Change the three generated links to `customerId`.
4. Load the customer through the existing API gateway and retain legacy `customer` read compatibility without generating it.
5. Run focused tests to green.

## Task 5: Copy guard and compatibility verification

**Files**

- Modify: `inpa_fe/components/__tests__/copy-library.test.tsx`
- Modify if necessary: `inpa_fe/scripts/check-copy.js`

**Steps**

1. Add the playbook registry to rendered-copy scanning.
2. Add regression patterns for guarantees, fear, discrimination, stale figures, company/product promotion and purpose-concealing phrasing.
3. Confirm existing 30-copy exact-count/stable-key tests still pass.
4. Run all talk/template tests, copy lint, and `git diff --check`.

## Task 6: Runtime and release verification

**Steps**

1. Run the full frontend Vitest suite.
2. Run `npm run lint:copy`.
3. Run `npm run build`.
4. Start the frontend against the local backend and inspect `/scripts` at 360px, 390px, 768px and 1440px.
5. Verify playbook selection, stage navigation, objection branches, customer lookup, copy/share, profile failure, personal-template failure, and quick-library CRUD affordances.
6. Run an independent correctness/security/UX/copy review; fix confirmed findings and rerun affected gates.
7. Fetch origin and confirm the branch diff before staging owned files.
8. Commit with Conventional Commits, push, open a ready PR, wait for CI, merge.
9. Verify the exact merge commit in Vercel production. If Render receives a deployment, wait for its terminal state; otherwise confirm backend health stayed healthy.
10. Smoke-test `https://www.inpa.kr/scripts` and `https://inpa-be.onrender.com/healthz/`, then observe errors for five minutes.
11. Update `README.md` and `AGENTS.md` with the merged/deployed state, commit through a docs PR, merge, and verify the final production state.
