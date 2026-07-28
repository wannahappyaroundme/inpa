# Inactive planner baseline follow-up report

Date: 2026-07-29

## Scope

- Added `is_active` to catalog stored scopes and legacy rows.
- Kept `is_applied` bound to the central eligibility helper.
- Separated source adoption (`preset`/`null`) from inactive planner re-use.
- Preserved the existing batch request shape. The frontend never sends source or active-state fields.
- Updated only the specified stale policy references, plan, and design notes. README and AGENTS were not changed.

## TDD evidence

RED was observed before implementation:

- Backend legacy-catalog regression failed with `KeyError: 'is_active'`.
- Frontend editor regression received `undefined` instead of inactive state.
- Drawer and page regressions could not find the re-use copy/action.

GREEN focused verification:

```text
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py test \
  inpa.customers.tests.PlannerBaselineCatalogTests \
  inpa.analysis.test_baselines \
  inpa.analysis.tests
Ran 183 tests in 74.080s
OK

npm test -- --run lib/baseline-editor.test.ts \
  components/__tests__/baseline-detail-drawer.test.tsx \
  components/__tests__/baseline-settings-page.test.tsx \
  components/__tests__/baseline-api-contract.test.tsx
Test Files  4 passed (4)
Tests  49 passed (49)
```

## Verification

```text
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py check
System check identified no issues (0 silenced).

npm run lint:copy
정직성 카피 가드 통과 (295개 파일, 위반 0)

npm run build
Compiled successfully; TypeScript finished; 74/74 static pages generated.
```

The first sandboxed build stopped without output after about two minutes. It was interrupted and rerun once outside the sandbox; the recorded successful result above is from that rerun.

## Deployment note

No deployment was performed. Execution remains pending: Vercel frontend must be `Ready` before Render backend starts. If Render auto-deploy starts concurrently, cancel or hold it and start Render only after Vercel is `Ready`.

## Remaining concern

The focused backend run emits expected warning logs for deliberate unauthorized/invalid-request and mocked-provider cases. It completed with `OK`; no new warning condition was introduced by this follow-up.
