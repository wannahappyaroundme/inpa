# Planner Baseline Grading Source Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply only planner-reviewed coverage baselines to heatmap and comparison grading while keeping unreviewed legacy preset or source-less values neutral until the planner explicitly adopts them.

**Architecture:** Keep the existing global grading gate as the environment-level kill switch, then add one centralized source-eligibility policy shared by heatmap and comparison. Preserve all stored rows and API request shapes; the editor carries source and stored-row metadata so unchanged preset or source-less legacy values can be explicitly adopted through the existing batch endpoint.

**Tech Stack:** Django 5.2, Django REST Framework, PostgreSQL/SQLite ORM, Next.js 16, React 19, TypeScript, Vitest, Testing Library, Tailwind CSS

## Global Constraints

- `planner` is the only grading-eligible source in this release.
- `preset` and `null` remain stored but never drive `부족·적정·넉넉`.
- Saving or explicitly adopting a preset or source-less stored row converts it to `baseline_source='planner'` and clears `preset_origin`.
- `baseline_source`, `preset_origin`, and `is_active` are server-owned on general CRUD; frontend write payloads omit all three.
- No database migration, row deletion, bulk source conversion, or demo teardown.
- Keep `HEATMAP_GRADING_ENABLED=False` as the code default; set the Render web service explicitly to `True`.
- Heatmap and comparison must consume the same eligibility helper.
- Existing API request shapes and existing response fields remain compatible.
- Rendered copy must not expose `v0`, `preset`, `gate`, or other internal terms.
- No em dash (`—`) in rendered copy.
- Do not commit, push, merge, or deploy until the PM separately authorizes that Git action or production action.

## Final-review follow-up (2026-07-29)

**Progress:** Tasks 1-4 are implemented and had their previous review pass. The final reviews found legacy status, inactive re-use, server-owned active-state, documentation, and rolling-deployment gaps; the follow-ups keep the policy and public request compatibility while correcting those contracts. The pre-fix full backend run recorded `2,237 OK, 39 skipped`; it is historical evidence only. Final focused and full verification must be rerun after these fixes. The PM has authorized push, merge, and production deployment; execution and production verification are still pending.

**Acceptance criteria:**

- The legacy response returns `is_active`; `is_applied` remains `is_grading_eligible_baseline` truth, while `requires_adoption` means only preset or source-less adoption is needed.
- A legacy planner fallback that is actually usable shows `분석에 적용 중`; an inactive planner row shows `연결 후 다시 사용 필요`; an eligible but unresolved row shows `연결 필요`; preset or source-less rows show `연결 후 금액 확인 필요`.
- Linking preserves `baseline_source` and `preset_origin`; a catalog reload keeps the linked detail in the pending-adoption state until explicit batch save.
- An unchanged requested inactive planner, preset, or source-less row becomes active planner source and clears `preset_origin`; untouched scopes remain unchanged.
- Draft equality includes active state, while the existing batch request keeps omitting source and active-state fields. A successful save clears the re-use affordance only for the requested scope.
- General POST/PATCH requests cannot set `is_active`; the serializer ignores client attempts, the model default owns create state, and only the explicit batch save reactivates an existing row.

**Deployment order, pending execution:** Before merge, temporarily disable auto-deploy for the Render web service. Merge, wait until the compatible frontend is `Ready` in Vercel production, then manually deploy the exact merge commit to the Render web service and restore auto-deploy. No deployment has been executed by this follow-up.

---

### Task 1: Centralize baseline source eligibility

**Files:**
- Modify: `inpa_be/inpa/customers/models.py:510-566`
- Modify: `inpa_be/inpa/customers/serializers.py:150-210`
- Modify: `inpa_be/inpa/customers/views.py:760-925`
- Modify: `inpa_be/inpa/customers/presets.py:26-36`
- Modify: `inpa_be/inpa/analysis/baselines.py:1-75`
- Test: `inpa_be/inpa/analysis/test_baselines.py:1-205`

**Interfaces:**
- Produces: `PlannerBaseline.SOURCE_PLANNER = 'planner'`
- Produces: `PlannerBaseline.SOURCE_PRESET = 'preset'`
- Produces: `is_grading_eligible_baseline(row: PlannerBaseline | object) -> bool`
- Produces: `grading_eligible_baselines(candidates: Iterable[PlannerBaseline]) -> list[PlannerBaseline]`
- Consumes: existing `PlannerBaseline.is_active` and `baseline_source`

- [ ] **Step 1: Write failing eligibility tests**

Add imports and focused tests to `inpa_be/inpa/analysis/test_baselines.py`:

```python
from inpa.analysis.baselines import (
    grading_eligible_baselines,
    is_grading_eligible_baseline,
    normalize_money,
    select_baseline,
)


class BaselineSourceEligibilityTests(SimpleTestCase):
    def test_only_active_planner_source_is_grading_eligible(self):
        planner = _baseline(
            PlannerBaseline.PRODUCT_GROUP_NONLIFE,
            '30s',
            1,
            'planner',
            baseline_source='planner',
        )
        preset = _baseline(
            PlannerBaseline.PRODUCT_GROUP_NONLIFE,
            '30s',
            1,
            'preset',
            baseline_source='preset',
        )
        source_less = _baseline(
            PlannerBaseline.PRODUCT_GROUP_NONLIFE,
            '30s',
            1,
            'source-less',
            baseline_source=None,
        )
        inactive = _baseline(
            PlannerBaseline.PRODUCT_GROUP_NONLIFE,
            '30s',
            1,
            'inactive',
            is_active=False,
            baseline_source='planner',
        )

        self.assertTrue(is_grading_eligible_baseline(planner))
        self.assertFalse(is_grading_eligible_baseline(preset))
        self.assertFalse(is_grading_eligible_baseline(source_less))
        self.assertFalse(is_grading_eligible_baseline(inactive))
        self.assertEqual(grading_eligible_baselines(
            [preset, source_less, planner, inactive]), [planner])

    def test_select_baseline_rejects_unreviewed_preset_defensively(self):
        preset = _baseline(
            PlannerBaseline.PRODUCT_GROUP_NONLIFE,
            '30s',
            1,
            'preset',
            baseline_source='preset',
        )

        self.assertIsNone(select_baseline(
            [preset],
            insurance_type=PlannerBaseline.PRODUCT_GROUP_NONLIFE,
            age_band='30s',
            gender=1,
        ))
```

- [ ] **Step 2: Run the tests and confirm the policy is missing**

Run:

```bash
cd inpa_be
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py test inpa.analysis.test_baselines.BaselineSourceEligibilityTests
```

Expected: import failure for `grading_eligible_baselines` or a failed assertion because `preset` is currently accepted.

- [ ] **Step 3: Add model constants and the central helper**

In `PlannerBaseline`:

```python
SOURCE_PLANNER = 'planner'
SOURCE_PRESET = 'preset'
```

In `inpa_be/inpa/analysis/baselines.py`:

```python
def is_grading_eligible_baseline(row):
    return bool(
        getattr(row, 'is_active', True)
        and getattr(row, 'baseline_source', None)
        == PlannerBaseline.SOURCE_PLANNER
    )


def grading_eligible_baselines(candidates):
    return [
        row for row in candidates
        if is_grading_eligible_baseline(row)
    ]
```

Update `select_baseline` to call `is_grading_eligible_baseline(row)` instead of accepting every truthy source. Replace literal writes in serializers, batch save, and preset creation with `SOURCE_PLANNER` or `SOURCE_PRESET`.

- [ ] **Step 4: Run the focused baseline tests**

Run:

```bash
cd inpa_be
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py test inpa.analysis.test_baselines
```

Expected: all baseline tests pass.

- [ ] **Step 5: Prepare the checkpoint commit**

Stage only the Task 1 files. Commit only after PM authorization:

```bash
git add inpa_be/inpa/customers/models.py inpa_be/inpa/customers/serializers.py inpa_be/inpa/customers/views.py inpa_be/inpa/customers/presets.py inpa_be/inpa/analysis/baselines.py inpa_be/inpa/analysis/test_baselines.py
git commit -m "refactor(담보기준): 판정 가능 출처를 중앙화"
```

---

### Task 2: Apply the source policy to heatmap and comparison

**Files:**
- Modify: `inpa_be/inpa/analysis/views.py:193-250`
- Modify: `inpa_be/inpa/analysis/views.py:317-330`
- Modify: `inpa_be/inpa/analysis/compare.py:246-280`
- Test: `inpa_be/inpa/analysis/test_baselines.py:209-280`
- Test: `inpa_be/inpa/analysis/tests.py:718-915`

**Interfaces:**
- Consumes: `grading_eligible_baselines(candidates)`
- Produces heatmap fields: `applied_baseline_count: int`
- Produces heatmap fields: `unapplied_baseline_count: int`
- Preserves: `baseline_count`, `baseline_present`, `grading_enabled`, `mode`

- [ ] **Step 1: Write failing heatmap tests for preset exclusion and response counts**

Extend `HeatmapGradingGateTests`:

```python
@override_settings(HEATMAP_GRADING_ENABLED=True)
def test_preset_is_stored_but_not_applied(self):
    baseline = PlannerBaseline.objects.get(owner=self.user)
    baseline.baseline_source = PlannerBaseline.SOURCE_PRESET
    baseline.preset_origin = 'v0_starter'
    baseline.save(update_fields=['baseline_source', 'preset_origin'])

    body = self.client.get(
        f'/api/v1/customers/{self.customer.id}/heatmap/').json()

    self.assertEqual(body['mode'], 'neutral')
    self.assertTrue(body['baseline_present'])
    self.assertEqual(body['baseline_count'], 1)
    self.assertEqual(body['applied_baseline_count'], 0)
    self.assertEqual(body['unapplied_baseline_count'], 1)

@override_settings(HEATMAP_GRADING_ENABLED=True)
def test_planner_baseline_is_applied(self):
    body = self.client.get(
        f'/api/v1/customers/{self.customer.id}/heatmap/').json()

    self.assertEqual(body['mode'], 'graded')
    self.assertEqual(body['baseline_count'], 1)
    self.assertEqual(body['applied_baseline_count'], 1)
    self.assertEqual(body['unapplied_baseline_count'], 0)
```

- [ ] **Step 2: Write a failing comparison test**

Add to `CompareFactsTests`:

```python
@override_settings(HEATMAP_GRADING_ENABLED=True)
def test_mode_excludes_unreviewed_preset_baseline(self):
    _make_portfolio_typed(
        self.customer, self.idet, 50000000, portfolio_type=1)
    PlannerBaseline.objects.create(
        owner=self.user,
        analysis_detail=self.det,
        coverage_key=self.det.name,
        product_group=PlannerBaseline.PRODUCT_GROUP_NONLIFE,
        age_band='30s',
        gender=1,
        recommend_min=100000000,
        unit=PlannerBaseline.UNIT_WON,
        baseline_source=PlannerBaseline.SOURCE_PRESET,
        preset_origin='v0_starter',
    )

    self.assertEqual(self._get().json()['mode'], 'neutral')
```

- [ ] **Step 3: Run the focused tests and verify failure**

Run:

```bash
cd inpa_be
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py test inpa.analysis.test_baselines.HeatmapGradingGateTests inpa.analysis.tests.CompareFactsTests
```

Expected: preset heatmap or comparison reports `graded`, and the new count fields are absent.

- [ ] **Step 4: Split stored and applied baselines in the heatmap**

Use one stored list and the Task 1 helper:

```python
stored_baselines = list(
    PlannerBaseline.objects
    .filter(owner=customer.owner, is_active=True)
    .exclude(baseline_source__isnull=True)
)
applied_baselines = grading_eligible_baselines(stored_baselines)
mode = (
    'graded'
    if settings.HEATMAP_GRADING_ENABLED and applied_baselines
    else 'neutral'
)
```

Pass `applied_baselines` to `baseline_candidates_for_detail`. Preserve `baseline_count=len(stored_baselines)` and add:

```python
'applied_baseline_count': len(applied_baselines),
'unapplied_baseline_count': (
    len(stored_baselines) - len(applied_baselines)
),
```

- [ ] **Step 5: Apply the same helper in comparison**

In `_mode_for_customer`, load the stored active rows once, then call:

```python
baselines = grading_eligible_baselines(stored_baselines)
if not baselines:
    return 'neutral'
```

Do not change comparison rows, premium summaries, warnings, or guide gates.

- [ ] **Step 6: Run focused and full analysis tests**

Run:

```bash
cd inpa_be
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py test inpa.analysis.test_baselines inpa.analysis.tests
```

Expected: all analysis tests pass.

- [ ] **Step 7: Prepare the checkpoint commit**

Stage only Task 2 files. Commit only after PM authorization:

```bash
git add inpa_be/inpa/analysis/views.py inpa_be/inpa/analysis/compare.py inpa_be/inpa/analysis/test_baselines.py inpa_be/inpa/analysis/tests.py
git commit -m "feat(담보기준): 직접 저장한 기준만 판정에 적용"
```

---

### Task 3: Add explicit legacy-baseline adoption to the baseline editor

**Files:**
- Modify: `inpa_fe/lib/api.ts:1170-1195`
- Modify: `inpa_fe/lib/api.ts:1350-1368`
- Modify: `inpa_fe/lib/baseline-editor.ts:1-330`
- Modify: `inpa_fe/components/baseline-detail-drawer.tsx`
- Modify: `inpa_fe/app/settings/baseline/page.tsx`
- Modify: `inpa_fe/components/heatmap.tsx:370-405`
- Test: `inpa_fe/lib/baseline-editor.test.ts`
- Test: `inpa_fe/components/__tests__/baseline-detail-drawer.test.tsx`
- Test: `inpa_fe/components/__tests__/baseline-settings-page.test.tsx`
- Test: `inpa_fe/components/__tests__/insurance-review-authority.test.tsx`

**Interfaces:**
- Extends: `HeatmapResponse.applied_baseline_count?: number`
- Extends: `HeatmapResponse.unapplied_baseline_count?: number`
- Extends: `BaselineCatalogStoredScope.baseline_source: string | null`
- Extends: `BaselineDraftScope.baseline_source: string | null`
- Extends: `BaselineDraftScope.is_stored: boolean`
- Produces: `adoptBaselineScope(scope: BaselineDraftScope) -> BaselineDraftScope`
- Produces: `normalizeSavedBaselineDraft(draft, changes, revision) -> BaselineDraftCatalog`

- [ ] **Step 1: Write a failing editor test for unchanged adoption**

Add to `inpa_fe/lib/baseline-editor.test.ts`:

```typescript
it("builds a save change when an unchanged preset is adopted", () => {
  const server = catalogWithScope({
    recommend_min: "5000",
    recommend_max: null,
    baseline_source: "preset",
  });
  const draft = catalogToDraft(server);
  const scope = firstScope(draft);
  scope.baseline_source = "planner";

  expect(buildBaselineChanges(catalogToDraft(server), draft)).toEqual([
    expect.objectContaining({
      recommend_min: "5000",
      recommend_max: null,
    }),
  ]);
});
```

Use the existing test factories in that file; extend their stored-scope defaults with `baseline_source`.

- [ ] **Step 2: Write failing drawer and heatmap copy tests**

In `baseline-detail-drawer.test.tsx`, render both a preset scope and a stored source-less scope and assert:

```typescript
expect(screen.getByText(
  "이 금액을 확인한 뒤 내 기준으로 사용하면 분석에 반영돼요."
)).toBeTruthy();
await user.click(screen.getByRole("button", { name: "내 기준으로 사용" }));
expect(onScopeChange).toHaveBeenCalledWith(
  expect.anything(),
  expect.objectContaining({ baseline_source: "planner" }),
);
```

In `insurance-review-authority.test.tsx`, add a neutral heatmap with:

```typescript
baseline_present: true,
grading_enabled: true,
baseline_count: 1,
applied_baseline_count: 0,
unapplied_baseline_count: 1,
```

Assert the settings link contains “금액을 확인하고 저장하면 내 기준으로 적용돼요.”

- [ ] **Step 3: Run the focused frontend tests and verify failure**

Run:

```bash
cd inpa_fe
npm run test:run -- lib/baseline-editor.test.ts components/__tests__/baseline-detail-drawer.test.tsx components/__tests__/baseline-settings-page.test.tsx components/__tests__/insurance-review-authority.test.tsx
```

Expected: source metadata or adoption control is absent.

- [ ] **Step 4: Preserve source metadata and make source changes dirty**

Add `baseline_source` to `BaselineCatalogStoredScope` and `BaselineDraftScope`. Set empty default scopes to `null`. Add `is_stored` to the draft so API-linked source-less rows remain distinguishable from synthesized empty inputs. Include source in `sameScopeValue`:

```typescript
left.baseline_source === right.baseline_source
```

Keep `PlannerBaselineBatchChange` unchanged. `asChange` must explicitly return only the existing request fields so `baseline_source` is not accepted from the browser:

```typescript
function asChange(scope: BaselineDraftScope): PlannerBaselineBatchChange {
  return {
    analysis_detail_id: scope.analysis_detail_id,
    product_group: scope.product_group,
    age_band: scope.age_band,
    gender: scope.gender,
    recommend_min: normalizeBaselineAmount(scope.recommend_min),
    recommend_max: normalizeBaselineAmount(scope.recommend_max),
    unit: scope.unit,
  };
}
```

- [ ] **Step 5: Add the explicit adoption control**

For stored rows whose `baseline_source` is `preset` or `null`, render the approved copy and button. Do not show the action for a synthesized empty input. The click handler supplies:

```typescript
{
  ...scope,
  baseline_source: "planner",
}
```

The page uses the existing `setScope` and Save flow. A normal amount edit remains a change; the server batch endpoint continues to force source `planner`. After success, normalize only the exact scopes included in the batch request so untouched preset or source-less rows stay pending adoption in the local screen state.

- [ ] **Step 6: Use applied counts in heatmap copy**

Calculate:

```typescript
const appliedBaselineCount =
  heatmap.applied_baseline_count ?? heatmap.baseline_count;
const unappliedBaselineCount =
  heatmap.unapplied_baseline_count ?? 0;
```

Use `appliedBaselineCount` in “내 기준 N개 적용 중”. When mode is neutral, grading is enabled, and `unappliedBaselineCount > 0`, render:

```text
금액을 확인하고 저장하면 내 기준으로 적용돼요.
```

Keep existing stored-with-gate-closed and no-baseline states distinct.

- [ ] **Step 7: Run focused frontend tests**

Run:

```bash
cd inpa_fe
npm run test:run -- lib/baseline-editor.test.ts components/__tests__/baseline-detail-drawer.test.tsx components/__tests__/baseline-settings-page.test.tsx components/__tests__/insurance-review-authority.test.tsx
```

Expected: all focused tests pass.

- [ ] **Step 8: Prepare the checkpoint commit**

Stage only Task 3 files. Commit only after PM authorization:

```bash
git add inpa_fe/lib/api.ts inpa_fe/lib/baseline-editor.ts inpa_fe/components/baseline-detail-drawer.tsx inpa_fe/app/settings/baseline/page.tsx inpa_fe/components/heatmap.tsx inpa_fe/lib/baseline-editor.test.ts inpa_fe/components/__tests__/baseline-detail-drawer.test.tsx inpa_fe/components/__tests__/baseline-settings-page.test.tsx inpa_fe/components/__tests__/insurance-review-authority.test.tsx
git commit -m "feat(담보기준): 확인한 이전 기준을 직접 기준으로 전환"
```

---

### Task 4: Prepare the production gate and operational documentation

**Files:**
- Modify: `render.yaml:61-70`
- Modify: `inpa_be/.env.example:40-47`
- Modify after successful production deployment: `README.md`
- Modify after successful production deployment: `AGENTS.md`
- Test: `inpa_be/inpa/analysis/test_baselines.py`

**Interfaces:**
- Produces production env: `HEATMAP_GRADING_ENABLED=True` on `inpa-be`
- Preserves default: `HEATMAP_GRADING_ENABLED=False` in `base.py`

- [ ] **Step 1: Add a settings regression test**

Add a test that confirms the code default remains closed by inspecting settings without an override:

```python
def test_code_default_remains_fail_closed(self):
    self.assertFalse(settings.HEATMAP_GRADING_ENABLED)
```

Place it in a settings-focused test class that does not inherit a class-level grading override.

- [ ] **Step 2: Add the explicit Render web setting**

Under the `inpa-be` service env vars:

```yaml
- key: HEATMAP_GRADING_ENABLED
  value: "True"  # 설계사가 직접 저장한 기준만 판정에 적용
```

Do not add this setting to the insurance worker.

- [ ] **Step 3: Update the environment example**

Keep:

```dotenv
HEATMAP_GRADING_ENABLED=False
```

Update its comment to state that production may enable it only because source eligibility excludes unreviewed preset rows.

- [ ] **Step 4: Validate configuration**

Run:

```bash
cd inpa_be
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py check
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py makemigrations --check --dry-run
```

Expected: system check passes and “No changes detected”.

- [ ] **Step 5: Prepare the checkpoint commit**

Stage only configuration and tests. Commit only after PM authorization:

```bash
git add render.yaml inpa_be/.env.example inpa_be/inpa/analysis/test_baselines.py
git commit -m "chore(담보기준): 직접 기준 판정 운영 게이트 준비"
```

- [ ] **Step 6: Update service docs only after merge and production verification**

After the production deployment succeeds, update:

- `README.md`: planner-entered standards are live; old starter values require explicit adoption.
- `AGENTS.md`: exact source policy, response fields, Render setting, CI run, merge SHA, deployment IDs, and smoke evidence.

Do not claim deployment in either document before the actual production checks pass.

---

### Task 5: Full verification and release handoff

**Files:**
- Verify all modified files
- Modify only confirmed post-deploy facts in `README.md` and `AGENTS.md`

**Interfaces:**
- Consumes all Tasks 1-4
- Produces a release-ready branch, test evidence, and a production rollout checklist

- [ ] **Step 1: Run backend focused tests**

```bash
cd inpa_be
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py test inpa.analysis.test_baselines inpa.analysis.tests inpa.customers.tests
```

Expected: all targeted backend tests pass.

- [ ] **Step 2: Run the complete backend suite**

```bash
cd inpa_be
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py check
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py test inpa
```

Expected: all tests pass with only the repository’s documented skips.

- [ ] **Step 3: Run frontend verification**

```bash
cd inpa_fe
npm run test:run
npm run lint:copy
npm run build
```

Expected: all Vitest tests pass, copy lint reports 0 findings, and Next.js builds all routes.

- [ ] **Step 4: Verify the diff**

```bash
git diff --check
git status --short
git diff --stat origin/master...HEAD
```

Expected: no whitespace errors, only planned files changed, and no unrelated user work staged.

- [ ] **Step 5: Request independent review**

Review lenses:

- Correctness: preset cannot enter grading through heatmap, comparison, legacy fallback, or unchanged adoption.
- Security and tenancy: owner filtering and server-owned source, preset origin, and active-state assignment remain intact.
- UX: all three states are distinct on mobile and desktop.
- Insurance-domain honesty: no unreviewed Inpa value is presented as an authoritative standard.
- Operations: code default remains closed and only the Render web service opens the gate.

Fix every confirmed Critical or Important finding and rerun affected tests.

- [ ] **Step 6: Request Git and production approval**

Before external actions, present:

- changed file list
- full test results
- review result
- planned commit messages
- rollback: set `HEATMAP_GRADING_ENABLED=False` and redeploy

Wait for explicit PM approval before staging, committing, pushing, merging, or production deployment.

- [ ] **Step 7: After approval, stage, commit, push, PR, merge, and deploy**

Before push:

```bash
git fetch origin
git log --oneline origin/master..HEAD
```

Use a ready PR from `codex/planner-baseline-grading` to `master`. Merge only when backend, PostgreSQL concurrency, frontend, gitleaks, and Vercel checks all pass.

Before merge, temporarily disable auto-deploy for the Render web service. After merge, wait until the Vercel frontend deployment is `Ready`, manually deploy the exact merge commit to Render web, verify it is live, and restore auto-deploy.

- [ ] **Step 8: Verify production**

Check:

```text
GET https://inpa-be.onrender.com/healthz/ -> 200
GET https://www.inpa.kr/settings/baseline -> 200
GET https://www.inpa.kr/customers/<test-customer> -> 200 after authentication
```

With a non-identifying test account:

1. A preset-only row returns `mode='neutral'`, `applied_baseline_count=0`.
2. `내 기준으로 사용` followed by Save returns success.
3. The next heatmap returns `mode='graded'`, `applied_baseline_count=1`.
4. The same customer comparison mode is `graded`.
5. Deactivate the test baseline after verification.

- [ ] **Step 9: Update and verify final documentation**

Record actual merge SHA, CI run, Vercel status, Render web status, health response, and smoke results in `README.md` and `AGENTS.md`. Run:

```bash
git diff --check
cd inpa_fe
npm run lint:copy
```

Expected: clean diff and 0 copy findings.
