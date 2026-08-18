# Inpa Sales Marketing Execution Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one standalone editable HTML dashboard that turns Inpa's 2026-08-03 through 2026-12-31 sales and marketing strategy into daily checklists, an outreach pipeline, design-partner follow-up, scenarios, editable KPIs, and browser-local persistence.

**Architecture:** One self-contained HTML file owns its CSS, seed data, rendering, event delegation, localStorage persistence, JSON backup/restore, and print layout. A Vitest/jsdom contract test reads the standalone file without connecting it to the Inpa application, verifies its seeded scope and interactions, and protects the single-file behavior.

**Tech Stack:** HTML5, CSS3, vanilla JavaScript, browser localStorage, JSON File/Blob APIs, Vitest 4, jsdom 29.

## Global Constraints

- Deliverable path is `docs/strategy/inpa-sales-marketing-execution.html`.
- The deliverable must remain a single HTML file with no external runtime dependency, API, server, login, or build step.
- Do not modify or connect the existing Inpa frontend or backend runtime.
- Use the Inpa light palette: brand `#2F58DC`, canvas `#F3F5F9`, surface `#FFFFFF`, ink `#14171F`, line `#E6E9EF`.
- All plan copy, dates, quantities, target rows, partner rows, and scenario content must be editable in the UI.
- Check state, edits, added rows, and deleted rows must save immediately to localStorage.
- Include JSON export/import, default-state reset confirmation, and print styling.
- Include no LinkedIn policy, Naver spam-mail policy, or spam-regulation explanation/link in the dashboard.
- Operational outreach is phone, one-to-one text follow-up, direct visit, introduction, seminar, interview, and repeat-use support.
- Do not commit any file unless the user explicitly asks.

## Calendar-First Redesign Addendum

### Task 5: Today Checklist as the First Working Surface

**Files:**
- Modify: `docs/strategy/inpa-sales-marketing-execution.html`
- Modify: `inpa_fe/components/__tests__/sales-marketing-execution-html.test.tsx`

**Interfaces:**
- Consumes: `DashboardState.tasks`, `DashboardState.settings.focusDate`, existing delegated `data-collection` controls.
- Produces: `getTodayPresentationDate(state, now)`, `getOverdueTasks(state, date)`, and a first `#todaySection` immediately after the sticky navigation.

- [ ] **Step 1: Add a failing structure test**

Assert that `#todaySection` precedes `#overviewSection`, the today section exposes a checklist, and overdue incomplete tasks are separated from the current date tasks.

- [ ] **Step 2: Run the focused test and verify failure**

Run `npm test -- --run components/__tests__/sales-marketing-execution-html.test.tsx` from `inpa_fe/`. Expected: the first-surface and overdue assertions fail against the existing overview-first layout.

- [ ] **Step 3: Implement the today-first renderer**

Move `#todaySection` before `#overviewSection`, render current-date tasks first, render earlier incomplete tasks in a separate collapsible block, and use the nearest future campaign date when today has no task. Keep existing edit, checkbox, actual, owner, and note controls.

- [ ] **Step 4: Run the focused test**

Run the command from Step 2. Expected: the new today-first assertions pass.

### Task 6: Interactive Month Calendar

**Files:**
- Modify: `docs/strategy/inpa-sales-marketing-execution.html`
- Modify: `inpa_fe/components/__tests__/sales-marketing-execution-html.test.tsx`

**Interfaces:**
- Consumes: normalized `state.settings.calendarMonth`, `state.settings.selectedDate`, and `state.tasks`.
- Produces: `buildMonthCells(month)`, `renderCalendar()`, month navigation actions, calendar task checkboxes, and the selected-date detail checklist.

- [ ] **Step 1: Add failing calendar behavior tests**

Assert a seven-column calendar, 42 day cells, task labels inside date cells, previous/next/today controls, a maximum of three visible task labels per cell, and selection of a day updating the detail checklist.

- [ ] **Step 2: Run the focused test and verify failure**

Run `npm test -- --run components/__tests__/sales-marketing-execution-html.test.tsx` from `inpa_fe/`. Expected: calendar grid and navigation assertions fail against the existing monthly table.

- [ ] **Step 3: Implement calendar state normalization**

Extend `normalizeState()` so missing `calendarMonth` and `selectedDate` values derive from the campaign period without changing the storage key or resetting any saved arrays.

- [ ] **Step 4: Implement the month grid and interactions**

Render Sunday-through-Saturday headers and six weeks of date cells. Each current-month cell shows up to three task checkboxes, a remaining-count label, and a date-selection button. Add previous, next, and today actions and render the selected date's full editable task table below the grid.

- [ ] **Step 5: Add responsive and print layout**

Use a readable fixed minimum calendar width inside an overflow container below 760px. Preserve desktop seven-column layout and include task text in print while hiding navigation controls.

- [ ] **Step 6: Run focused and full verification**

Run `npm test -- --run components/__tests__/sales-marketing-execution-html.test.tsx`, `npm test -- --run`, and `npm run build` from `inpa_fe/`. Open the standalone HTML at 1280x720 and 390x844, confirm checkbox synchronization, date selection, month navigation, no page-wide overflow, and zero browser warnings or errors.

---

## File Map

- Create `docs/strategy/inpa-sales-marketing-execution.html`: complete standalone dashboard, seed plan, state handling, calculations, responsive and print layout.
- Create `inpa_fe/components/__tests__/sales-marketing-execution-html.test.tsx`: artifact contract, seed coverage, edit/check/save, KPI, add/delete, and import normalization tests.
- Use existing `docs/superpowers/specs/2026-08-02-inpa-sales-marketing-execution-dashboard-design.md` as the requirement authority.

### Task 1: Artifact Contract Tests

**Files:**
- Create: `inpa_fe/components/__tests__/sales-marketing-execution-html.test.tsx`
- Test target: `docs/strategy/inpa-sales-marketing-execution.html`

**Interfaces:**
- Consumes: standalone HTML at `../docs/strategy/inpa-sales-marketing-execution.html` relative to `inpa_fe/`.
- Expects: `window.InpaExecution` with `buildDefaultState()`, `getState()`, `setState(nextState)`, `calculateKpis(state)`, `saveState()`, and `storageKey`.
- Produces: executable acceptance contract for later tasks.

- [ ] **Step 1: Write the failing artifact contract**

Create a Vitest test that:

```ts
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { JSDOM } from "jsdom";
import { describe, expect, it } from "vitest";

const artifactPath = resolve(
  process.cwd(),
  "../docs/strategy/inpa-sales-marketing-execution.html",
);

async function loadDashboard() {
  const html = readFileSync(artifactPath, "utf8");
  const dom = new JSDOM(html, {
    runScripts: "dangerously",
    resources: "usable",
    url: "https://inpa.local/execution",
    pretendToBeVisual: true,
  });
  await new Promise<void>((resolveReady) => {
    dom.window.addEventListener("load", () => resolveReady(), { once: true });
  });
  return dom;
}
```

Assert that the artifact exists, contains no external script/stylesheet URL, exposes the required API, seeds at least 100 dated execution tasks and 28 scenarios, spans 2026-08-03 through 2026-12-31, and contains no `linkedin.com`, `spamcheck`, or `불법스팸` text.

- [ ] **Step 2: Add interaction assertions**

Test that:

```ts
const { window } = await loadDashboard();
const api = window.InpaExecution;
const state = api.getState();
state.meta.title = "수정한 실행판";
state.tasks[0].done = true;
api.setState(state);
api.saveState();

expect(JSON.parse(window.localStorage.getItem(api.storageKey)!).meta.title)
  .toBe("수정한 실행판");
expect(JSON.parse(window.localStorage.getItem(api.storageKey)!).tasks[0].done)
  .toBe(true);
```

Also assert that KPI calculation respects manual overrides, final-user qualification counts partner data correctly, and malformed imported rows are normalized rather than crashing.

- [ ] **Step 3: Run the new test and confirm the artifact is missing**

Run:

```bash
cd inpa_fe
npm test -- --run components/__tests__/sales-marketing-execution-html.test.tsx
```

Expected: FAIL because `docs/strategy/inpa-sales-marketing-execution.html` does not exist.

### Task 2: Standalone Shell, Seed Plan, and Responsive Layout

**Files:**
- Create: `docs/strategy/inpa-sales-marketing-execution.html`
- Test: `inpa_fe/components/__tests__/sales-marketing-execution-html.test.tsx`

**Interfaces:**
- Produces: `window.InpaExecution.buildDefaultState(): DashboardState` and initial semantic DOM regions.
- `DashboardState` keys: `version`, `meta`, `kpis`, `tasks`, `targets`, `partners`, `scenarios`, `reviews`, `settings`.
- Later tasks consume the same stable state keys.

- [ ] **Step 1: Build the single-file semantic shell**

Add one HTML document containing:

```html
<header id="campaignHeader"></header>
<nav id="sectionNav" aria-label="실행판 메뉴"></nav>
<main>
  <section id="overviewSection"></section>
  <section id="todaySection"></section>
  <section id="calendarSection"></section>
  <section id="targetSection"></section>
  <section id="partnerSection"></section>
  <section id="scenarioSection"></section>
  <section id="reviewSection"></section>
</main>
```

Add accessible buttons and form labels, horizontal containment for wide tables, 44px minimum touch targets, visible focus states, mobile stacking below 760px, and print rules that hide editing controls while preserving content.

- [ ] **Step 2: Implement `buildDefaultState()`**

Seed:

- campaign period 2026-08-03 through 2026-12-31;
- KPI targets 120, 40, 28, 45, 100, 60, 42, 30, 24, and 20;
- at least 100 weekday-specific tasks with date, region, category, action, metric, target, actual, owner, method, note, and done state;
- the 28 approved scenarios, each with title, timing, goal, preparation, steps, success, stop, and follow-up;
- one editable blank target row and one editable blank partner row;
- weekly retrospective entries through the end of December.

Generate weekday tasks deterministically from explicit phase definitions:

```js
const phases = [
  { start: "2026-08-03", end: "2026-08-07", region: "서울 전역", mode: "준비" },
  { start: "2026-08-10", end: "2026-08-31", region: "서울 4개 권역", mode: "서울 집중" },
  { start: "2026-09-01", end: "2026-09-30", region: "서울·인천·부천·수원·성남", mode: "수도권 확장" },
  { start: "2026-10-01", end: "2026-10-15", region: "천안·대전·청주", mode: "충청 출장" },
  { start: "2026-10-16", end: "2026-10-31", region: "대구·부산", mode: "영남 출장" },
  { start: "2026-11-01", end: "2026-11-13", region: "울산·창원 또는 광주·전주", mode: "신규 모집 마감" },
  { start: "2026-11-14", end: "2026-12-31", region: "성과 상위 4개 권역", mode: "유지·인터뷰" },
];
```

Weekday templates must give each date a specific action rather than a generic placeholder.

- [ ] **Step 3: Render the initial read-only view from state**

Implement separate render functions:

```js
renderHeader(state);
renderOverview(state);
renderToday(state);
renderCalendar(state);
renderTargets(state);
renderPartners(state);
renderScenarios(state);
renderReviews(state);
```

Render overview metrics, today's tasks, monthly task groups, editable data tables, scenario details, and weekly review fields without adding persistence yet.

- [ ] **Step 4: Run the artifact test**

Run the Task 1 command. Expected: seed-scope assertions pass; persistence interaction assertions may still fail until Task 3.

### Task 3: Editing, Persistence, KPI Calculation, and Backup

**Files:**
- Modify: `docs/strategy/inpa-sales-marketing-execution.html`
- Test: `inpa_fe/components/__tests__/sales-marketing-execution-html.test.tsx`

**Interfaces:**
- Consumes: stable `DashboardState` from Task 2.
- Produces: `normalizeState(input)`, `getState()`, `setState(nextState)`, `calculateKpis(state)`, `saveState()`, `exportState()`, `importState(file)`, and `resetState()`.

- [ ] **Step 1: Add state normalization and safe restore**

Implement schema version `1`, array/type guards, defaults for missing fields, and error recovery:

```js
function normalizeState(input) {
  const defaults = buildDefaultState();
  if (!input || typeof input !== "object") return defaults;
  return {
    ...defaults,
    ...input,
    meta: { ...defaults.meta, ...(input.meta || {}) },
    settings: { ...defaults.settings, ...(input.settings || {}) },
    kpis: Array.isArray(input.kpis) ? input.kpis.map(normalizeKpi) : defaults.kpis,
    tasks: Array.isArray(input.tasks) ? input.tasks.map(normalizeTask) : defaults.tasks,
    targets: Array.isArray(input.targets) ? input.targets.map(normalizeTarget) : defaults.targets,
    partners: Array.isArray(input.partners) ? input.partners.map(normalizePartner) : defaults.partners,
    scenarios: Array.isArray(input.scenarios) ? input.scenarios.map(normalizeScenario) : defaults.scenarios,
    reviews: Array.isArray(input.reviews) ? input.reviews.map(normalizeReview) : defaults.reviews,
  };
}
```

If localStorage JSON is invalid, keep the corrupt value under a timestamped recovery key and start from defaults with a visible non-blocking notice.

- [ ] **Step 2: Add editable controls and delegated events**

Use inputs, textareas, selects, and checkboxes with `data-collection`, `data-id`, and `data-field`. One root `input`/`change` handler updates state and calls a debounced save. Add explicit buttons for task, target, partner, and scenario row creation; duplicate incomplete task to another date; and delete with confirmation.

Editable campaign title and descriptions use form controls in edit mode, not unsafe HTML injection. User-entered strings are assigned with `textContent` or input `value`, never `innerHTML`.

- [ ] **Step 3: Add KPI calculations**

Implement:

```js
function qualifiesFinalPartner(partner, campaignEnd) {
  return Number(partner.meaningfulWeeks) >= 6
    && Number(partner.coreFlows) >= 2
    && Number(partner.feedbackCount) >= 3
    && Number(partner.activeWeeksLast4) >= 3
    && daysBetween(partner.lastUsedAt, campaignEnd) <= 30;
}
```

Task-sourced KPIs sum `actual` for matching `metricId`. Partner-sourced KPIs count checked partner milestones. A non-empty numeric `manualActual` overrides the automatic value. Display target, actual, percentage capped visually at 100%, remaining count, and the lowest achievement KPI.

- [ ] **Step 4: Add save status and JSON backup/restore**

Use storage key `inpa-sales-marketing-execution-v1`. Save on every debounced edit and immediately on checks/add/delete. Show `저장됨 HH:MM:SS`. Export a UTF-8 JSON file named `inpa-sales-marketing-backup-YYYY-MM-DD.json`. Import only after parsing and normalization succeeds; otherwise show an error without replacing current state. Reset requires a native confirm dialog.

- [ ] **Step 5: Run all artifact tests**

Run:

```bash
cd inpa_fe
npm test -- --run components/__tests__/sales-marketing-execution-html.test.tsx
```

Expected: all tests pass.

### Task 4: Browser QA, Mobile QA, Print QA, and Final Content Audit

**Files:**
- Modify if needed: `docs/strategy/inpa-sales-marketing-execution.html`
- Modify if needed: `inpa_fe/components/__tests__/sales-marketing-execution-html.test.tsx`

**Interfaces:**
- Consumes: completed standalone dashboard.
- Produces: verified file ready for PM use.

- [ ] **Step 1: Run syntax and contract checks**

Run the focused Vitest command, then parse the HTML with jsdom and fail on any captured `window.error` or `unhandledrejection` event. Expected: zero runtime errors and all tests pass.

- [ ] **Step 2: Serve and inspect desktop layout**

Run:

```bash
python3 -m http.server 8765 --directory docs/strategy
```

Open `http://127.0.0.1:8765/inpa-sales-marketing-execution.html` at desktop width. Verify section navigation, sticky header, editable title, KPI cards, monthly groups, tables, scenario accordions, add/delete, save status, and backup controls.

- [ ] **Step 3: Inspect mobile layout**

Use a 390x844 viewport. Verify no page-wide horizontal overflow, controls wrap, tables use contained horizontal scrolling, checkboxes retain 44px touch targets, and dialogs/menus remain usable.

- [ ] **Step 4: Verify persistence and recovery manually**

Edit one title, check one task, add one target, add one partner, set partner qualification values, reload, and confirm all values remain. Export JSON, reset, import the JSON, and confirm the same values return.

- [ ] **Step 5: Inspect print preview**

Verify controls and destructive buttons are hidden, page background is white, KPI values and checked tasks are visible, tables split cleanly, and text does not clip.

- [ ] **Step 6: Audit required content and forbidden content**

Run:

```bash
rg -n "linkedin\.com|spamcheck|불법스팸|TODO|TBD|—" docs/strategy/inpa-sales-marketing-execution.html
```

Expected: no matches. Confirm that phone, text, direct visit, introduction, mini-seminar, regional trip, D2, D7, D14, D30, D42, weekly KPI, and final 20-user criteria are all present.

- [ ] **Step 7: Report without committing**

Report the created HTML and test paths, focused test result, desktop/mobile/browser result, persistence and JSON result, and any intentionally unverified item. Do not stage or commit.
