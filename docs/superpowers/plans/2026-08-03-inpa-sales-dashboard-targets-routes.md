# Inpa Sales Dashboard Targets and Routes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move all official-carrier spreadsheet data into the standalone Inpa execution dashboard and add five operational tabs, complete 80-target management, location overview, route order, map links, and scenario shortcuts without losing existing browser-saved edits.

**Architecture:** Keep one self-contained HTML file as the runtime and one jsdom contract test as the regression gate. Expand the existing state with normalized target, route, monthly-goal, criteria, and source arrays; derive every view from these single sources of truth; migrate existing `localStorage` state in place. Use an offline schematic overview plus generated Naver and Kakao map links instead of a live map SDK.

**Tech Stack:** HTML5, CSS3, vanilla JavaScript, browser localStorage and JSON File APIs, Vitest 4, jsdom 29.

## Global Constraints

- Modify only `docs/strategy/inpa-sales-marketing-execution.html`, `inpa_fe/components/__tests__/sales-marketing-execution-html.test.tsx`, and approved design/plan documents.
- Keep the dashboard a single HTML file with no external script, stylesheet, runtime API, login, or build step.
- Preserve browser storage key `inpa-sales-marketing-execution-v1` and all nonblank user-entered data.
- Seed exactly 80 official targets, exactly 40 priority targets, 20 August daily execution rows, 5 monthly goals, and 10 priority route clusters.
- Use easy Korean words, positive next-action framing, and no user-facing em dash.
- Do not connect the artifact to the Inpa production frontend or backend.
- Do not store customer names, policies, health data, or other customer-sensitive information.
- Do not commit unless the user explicitly requests a commit.

---

## File Map

- Modify `docs/strategy/inpa-sales-marketing-execution.html`: all data seeds, normalization, migration, tab shell, renderers, interactions, responsive styles, print behavior.
- Modify `inpa_fe/components/__tests__/sales-marketing-execution-html.test.tsx`: data-count, migration, tab, filter, route, map-link, persistence, and accessibility contracts.
- Reference `outputs/019fc1be-edd6-7463-8802-d532951ee7a8/build_inpa_targets.mjs`: authoritative researched target, daily, route, goal, criteria, and source values. Do not load it at runtime.
- Reference `docs/superpowers/specs/2026-08-03-inpa-sales-dashboard-targets-routes-design.md`: approved behavior and acceptance authority.

### Task 1: Freeze the Expanded Artifact Contract

**Files:**
- Modify: `inpa_fe/components/__tests__/sales-marketing-execution-html.test.tsx`
- Test: `inpa_fe/components/__tests__/sales-marketing-execution-html.test.tsx`

**Interfaces:**
- Consumes: existing `window.InpaExecution` test harness.
- Produces: assertions for `buildOfficialTargets()`, `buildMonthlyGoals()`, `buildRouteClusters()`, `getFilteredTargets(state)`, `buildMapUrl(provider, address)`, and storage migration.

- [ ] **Step 1: Add failing API and seed-count assertions**

Extend `ExecutionApi` with:

```ts
buildOfficialTargets: () => Array<Record<string, any>>;
buildMonthlyGoals: () => Array<Record<string, any>>;
buildRouteClusters: () => Array<Record<string, any>>;
getFilteredTargets: (state: Record<string, any>) => Array<Record<string, any>>;
buildMapUrl: (provider: "naver" | "kakao", address: string) => string;
```

Assert:

```ts
expect(defaults.targets).toHaveLength(80);
expect(defaults.targets.filter((target: any) => target.phase === "우선 40")).toHaveLength(40);
expect(defaults.targets.map((target: any) => target.rank).sort((a: number, b: number) => a - b))
  .toEqual(Array.from({ length: 80 }, (_, index) => index + 1));
expect(defaults.monthlyGoals).toHaveLength(5);
expect(defaults.routeClusters).toHaveLength(10);
expect(defaults.targets.every((target: any) => target.address && target.phone && target.source)).toBe(true);
```

- [ ] **Step 2: Add failing migration assertions**

```ts
const migrated = api.normalizeState({
  version: 1,
  targets: [{ id: "user-target", company: "사용자 입력", branch: "보존 지점", note: "유지" }],
  settings: { focusDate: "2026-08-03" },
});
expect(migrated.targets.some((target: any) => target.id === "user-target" && target.note === "유지")).toBe(true);
expect(migrated.targets.filter((target: any) => target.isOfficialSeed)).toHaveLength(80);
expect(migrated.settings.activeTab).toBe("today");
```

- [ ] **Step 3: Add failing UI assertions**

Assert five `role="tab"` buttons, one visible `role="tabpanel"`, `우선 40곳` and `전체 80곳` controls, target filters, an offline location overview, route cluster cards, and Naver/Kakao link targets with `rel="noopener"`.

- [ ] **Step 4: Run the focused test and confirm failure**

Run from `inpa_fe/`:

```bash
npm test -- --run components/__tests__/sales-marketing-execution-html.test.tsx
```

Expected: FAIL because expanded seed APIs, five tabs, and route UI do not exist.

### Task 2: Seed and Normalize the Spreadsheet Data

**Files:**
- Modify: `docs/strategy/inpa-sales-marketing-execution.html`
- Test: `inpa_fe/components/__tests__/sales-marketing-execution-html.test.tsx`

**Interfaces:**
- Produces `buildOfficialTargets(): Target[]`, `buildMonthlyGoals(): MonthlyGoal[]`, `buildRouteClusters(): RouteCluster[]`, `buildSelectionCriteria(): SelectionCriterion[]`, `buildSourceRegistry(): SourceEntry[]`.
- `buildDefaultState()` consumes all five seed builders.
- `normalizeState(input)` merges official seeds and user-entered targets.

- [ ] **Step 1: Set schema version and stable target fields**

Set `SCHEMA_VERSION = 2`. Extend `normalizeTarget()` to include:

```js
rank, phase, week, cluster, sector, channel, address, phone,
managerImpact, plannerAccess, officialCertainty, guroAccess, effectScore,
recommendedApproach, contactStatus, meetingStatus, managerTeam,
lastContactAt, meetingAt, activeUsers, feedbackUsers,
source, sourceCheckedAt, isOfficialSeed
```

Keep existing compatibility fields unchanged.

- [ ] **Step 2: Add all spreadsheet seed builders**

Copy the researched values from `build_inpa_targets.mjs` into literal arrays inside the HTML. Assign stable IDs `official-target-001` through `official-target-080`, route IDs `route-cluster-01` through `route-cluster-10`, and month IDs `monthly-goal-2026-08` through `monthly-goal-2026-12`.

- [ ] **Step 3: Replace August generic tasks with exact daily actions**

Add `buildAugustExecutionTasks()` with one dated record per weekday from `2026-08-03` through `2026-08-28`. Each record preserves spreadsheet targets for contact, manager appointments, field meetings, actual use, feedback, representative role, operations role, and completion condition. `buildTasks()` uses these exact August tasks and retains the existing generated plan for `2026-09-01` through `2026-12-31`.

- [ ] **Step 4: Implement non-destructive target migration**

```js
function mergeOfficialTargets(existingTargets) {
  const official = buildOfficialTargets();
  const incoming = Array.isArray(existingTargets) ? existingTargets.map(normalizeTarget) : [];
  const userRows = incoming.filter((item) => !item.isOfficialSeed && !isBlankLegacyTarget(item));
  const byId = new Map(incoming.filter((item) => item.isOfficialSeed).map((item) => [item.id, item]));
  return official.map((seed) => normalizeTarget({ ...seed, ...(byId.get(seed.id) || {}) })).concat(userRows);
}
```

`normalizeState()` must use this merge while `buildDefaultState()` returns only the 80 official rows.

- [ ] **Step 5: Run focused data and migration tests**

Run the focused test. Expected: seed-count and migration assertions pass; tab assertions still fail.

### Task 3: Replace Anchor Navigation with Five Persistent Tabs

**Files:**
- Modify: `docs/strategy/inpa-sales-marketing-execution.html`
- Test: `inpa_fe/components/__tests__/sales-marketing-execution-html.test.tsx`

**Interfaces:**
- Produces `setActiveTab(tabId)`, `renderTabs()`, and `settings.activeTab`.
- Tab IDs: `today`, `targets`, `planning`, `locations`, `scenarios`.

- [ ] **Step 1: Add the semantic tab shell**

Use buttons with `role="tab"`, `aria-selected`, and `aria-controls`. Wrap each main surface in `role="tabpanel"`; inactive panels receive `hidden`.

- [ ] **Step 2: Map existing renderers into tab panels**

- `today`: existing today checklist plus today route summary.
- `targets`: target manager and design-partner manager with subview controls.
- `planning`: calendar, overview KPI, monthly goals, weekly reviews.
- `locations`: offline overview, cluster cards, route timeline.
- `scenarios`: scenario library.

- [ ] **Step 3: Persist and restore active-tab state**

`settings.activeTab` defaults to `today`; click actions call `setActiveTab()`, `saveState()`, and `renderTabs()`. An invalid stored tab falls back to `today`.

- [ ] **Step 4: Add responsive and print tab behavior**

Below 760px, tab buttons keep readable width inside horizontal scrolling. Print hides tab buttons and renders the active panel without clipped inputs.

- [ ] **Step 5: Run focused tab tests**

Expected: semantic-tab and persistence assertions pass.

### Task 4: Build the 80-Target Operational Manager

**Files:**
- Modify: `docs/strategy/inpa-sales-marketing-execution.html`
- Test: `inpa_fe/components/__tests__/sales-marketing-execution-html.test.tsx`

**Interfaces:**
- Produces `getFilteredTargets(state)`, `renderTargetFilters()`, `renderTargetRows()`, and settings `targetView`, `targetFilters`.
- Consumes the single `state.targets` array.

- [ ] **Step 1: Add filter state normalization**

Normalize:

```js
targetView: "priority40" | "all80";
targetFilters: { search: string; company: string; sector: string; region: string; cluster: string; contactStatus: string; meetingStatus: string; };
```

- [ ] **Step 2: Implement target filtering and counts**

`priority40` includes official ranks 1 through 40. Search covers company, branch, cluster, address, and phone. Dropdown values derive from current official targets rather than hard-coded company lists.

- [ ] **Step 3: Render desktop table and mobile cards**

Desktop rows expose research facts, score, editable execution state, dates, counts, note, source, location button, and scenario button. Mobile cards show company, branch, phone, address, current state, next action, and expandable detail.

- [ ] **Step 4: Wire edits to the existing delegated event system**

Use existing `data-collection="targets"`, stable IDs, and `data-field`. Date, number, text, textarea, and select edits save immediately. No duplicate copy of target state is created.

- [ ] **Step 5: Add empty and error states**

When filters return zero rows, show `필터를 초기화하면 전체 거점을 다시 볼 수 있어요.` Missing address shows `주소를 채우면 지도에서 열 수 있어요.`

- [ ] **Step 6: Run focused target tests**

Expected: counts, filters, edit persistence, and mobile markup assertions pass.

### Task 5: Build Location Overview, Route Order, and Map Links

**Files:**
- Modify: `docs/strategy/inpa-sales-marketing-execution.html`
- Test: `inpa_fe/components/__tests__/sales-marketing-execution-html.test.tsx`

**Interfaces:**
- Produces `buildMapUrl(provider, address)`, `targetsForCluster(clusterId)`, `recommendedRouteForDate(date, state)`, `renderLocationOverview()`, and settings `origin`, `selectedCluster`.

- [ ] **Step 1: Implement safe map-link generation**

```js
function buildMapUrl(provider, address) {
  const query = encodeURIComponent(String(address || "").trim());
  if (!query) return "";
  return provider === "kakao"
    ? `https://map.kakao.com/link/search/${query}`
    : `https://map.naver.com/p/search/${query}`;
}
```

Links use `target="_blank"` and `rel="noopener"`. Address copy uses `navigator.clipboard.writeText()` with a textarea fallback.

- [ ] **Step 2: Render the offline regional overview**

Render schematic regions for 서울 서부, 강남·서초, 수도권, 충청, 영남, 호남, 강원, 제주. Each region displays official-target count, priority-target count, and status count. Pins are derived from region membership and clearly labeled `위치 관계를 보는 개요도이며 실제 축척과 다릅니다.`

- [ ] **Step 3: Render the 10 priority route clusters**

Each card shows sequence, week, district, building, representative address, target count, company, recommended visit date, operating method, and included branches. Selecting a card reveals every branch phone and address.

- [ ] **Step 4: Implement route-decision scenarios**

`recommendedRouteForDate()` applies:

1. no confirmed meeting: show priority call list, no departure recommendation;
2. one confirmed meeting: lead with that building;
3. two or more meetings in one building: recommend 30-minute grouped visits;
4. multiple buildings: meeting time first, seeded route order second;
5. nationwide region with fewer than two confirmed manager meetings: recommend remote confirmation.

- [ ] **Step 5: Add origin and route timeline controls**

Default origin is `구로`; it is editable and saved. Timeline displays origin, numbered stops, branch details, next action, and map buttons without claiming live travel time.

- [ ] **Step 6: Run focused route tests**

Expected: overview counts, 10 clusters, map URLs, no-meeting rule, and multi-meeting grouping pass.

### Task 6: Integrate Monthly Goals and Contextual Scenarios

**Files:**
- Modify: `docs/strategy/inpa-sales-marketing-execution.html`
- Test: `inpa_fe/components/__tests__/sales-marketing-execution-html.test.tsx`

**Interfaces:**
- Produces `renderMonthlyGoals()`, `scenarioCategory(item)`, `recommendedScenarioForTarget(target)`, and settings `scenarioCategory`.

- [ ] **Step 1: Render the five monthly goal rows**

Show month, new targets, manager meetings, new users, cumulative feedback users, travel condition, month-end condition, and editable judgment (`미달`, `달성`, `초과달성`).

- [ ] **Step 2: Categorize existing scenarios without rewriting their content**

Map scenario IDs to seven categories: first contact, appointment/material, manager meeting, planner activation, retention, objection/internal check, travel/revisit.

- [ ] **Step 3: Add contextual scenario shortcuts**

Map target state to scenario categories. A target row and today card opens the scenario tab, stores the selected category, and expands the first recommended scenario.

- [ ] **Step 4: Keep KPI meaning aligned with the 20-user outcome**

The planning header always shows first use, D7 reuse, feedback users, final 20 goal, and overdue follow-ups. Activity metrics remain in the detailed KPI table.

- [ ] **Step 5: Run focused scenario and monthly-goal tests**

Expected: five monthly rows, category filters, shortcuts, and 20-goal summary pass.

### Task 7: Complete Interaction, Accessibility, and Regression Verification

**Files:**
- Modify: `docs/strategy/inpa-sales-marketing-execution.html`
- Modify: `inpa_fe/components/__tests__/sales-marketing-execution-html.test.tsx`

**Interfaces:**
- Consumes all earlier state and render interfaces.
- Produces the final standalone artifact.

- [ ] **Step 1: Add keyboard and focus behavior**

Arrow keys move between main tabs; Enter and Space activate. After a location or scenario shortcut, focus moves to the destination heading. All buttons keep visible focus and at least 44px touch size.

- [ ] **Step 2: Finish empty, loading-free, and failure states**

The file has no asynchronous loading. Clipboard failure keeps address text visible and shows a concise toast. Corrupt storage preserves a recovery copy. Import errors leave current state unchanged.

- [ ] **Step 3: Run copy checks**

Run:

```bash
rg -n "—|OCR|리드|칸반|안 됩니다|못 합니다|불가|준비 중" docs/strategy/inpa-sales-marketing-execution.html
```

Expected: no forbidden user-facing copy findings.

- [ ] **Step 4: Run focused and full automated verification**

From `inpa_fe/`:

```bash
npm test -- --run components/__tests__/sales-marketing-execution-html.test.tsx
npm test -- --run
npm run build
```

Expected: focused test passes, full tests pass, and Next production build succeeds.

- [ ] **Step 5: Open and verify the local artifact**

Inspect `file:///Users/kyungsbook/Desktop/inpa/docs/strategy/inpa-sales-marketing-execution.html` at 1440px desktop and 390px mobile. Verify tab switching, priority/all filtering, search, edits, location overview, route clusters, map links, scenario shortcuts, JSON persistence, reload, and no console error.

- [ ] **Step 6: Verify storage migration manually**

Seed a version-1 state with one edited task and one user target, reload, and confirm the edited values plus all 80 official targets remain.

- [ ] **Step 7: Report without committing**

Report changed files, exact automated results, browser sizes checked, and any remaining unverified external behavior. Do not stage or commit.
