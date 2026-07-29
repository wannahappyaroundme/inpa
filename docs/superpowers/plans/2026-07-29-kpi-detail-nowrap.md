# KPI And Detail Button No-Wrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep dashboard KPI values with their units and coverage “상세 설정” button contents on one line, while allowing KPI text to scale from 28px down to 16px as card space narrows.

**Architecture:** Keep the change in the existing shared `StatCard` and baseline settings button. Use CSS container-relative sizing plus `white-space: nowrap`, avoiding JavaScript measurement and resize observers.

**Tech Stack:** React 19, Next.js 16, TypeScript, Tailwind CSS v4, Vitest, Testing Library

## Global Constraints

- KPI value and unit must always stay on one line.
- KPI font size must remain between 16px and 28px.
- “상세 설정” icon and label must stay on one line.
- Do not change data formatting, API behavior, card padding, or user-facing copy.
- Keep service pages light-fixed and do not add dark-mode styles.

---

### Task 1: Add layout regression coverage

**Files:**
- Create: `inpa_fe/components/__tests__/stat-card-layout.test.tsx`
- Modify: `inpa_fe/components/__tests__/baseline-settings-page.test.tsx`

**Interfaces:**
- Consumes: `StatCard` and `BaselineSettingsPage`
- Produces: regression assertions for no-wrap and responsive KPI sizing classes

- [x] **Step 1: Write failing tests**

```tsx
expect(valueRow).toHaveClass("whitespace-nowrap");
expect(value).toHaveStyle({ fontSize: "clamp(16px, 22cqw, 28px)" });
expect(detailButton).toHaveClass("whitespace-nowrap");
```

- [x] **Step 2: Run tests to verify they fail**

Run:

```bash
npx vitest run components/__tests__/stat-card-layout.test.tsx components/__tests__/baseline-settings-page.test.tsx
```

Expected: failures because the three responsive no-wrap rules are absent.

### Task 2: Implement the minimal responsive layout

**Files:**
- Modify: `inpa_fe/components/ui.tsx`
- Modify: `inpa_fe/app/settings/baseline/page.tsx`

**Interfaces:**
- Consumes: existing `StatCard` props and baseline detail-row rendering
- Produces: the same public interfaces with layout-only CSS changes

- [x] **Step 1: Make the KPI content a size container and keep its value row together**

```tsx
<div className="min-w-0 flex-1 [container-type:inline-size]">
  <p className="mt-1 flex items-baseline gap-1 whitespace-nowrap">
```

- [x] **Step 2: Scale the KPI value within the approved bounds**

```tsx
style={{ fontSize: "clamp(16px, 22cqw, 28px)" }}
```

- [x] **Step 3: Keep the detail button contents together**

```tsx
className="... whitespace-nowrap ..."
```

- [x] **Step 4: Run focused tests**

Run:

```bash
npx vitest run components/__tests__/stat-card-layout.test.tsx components/__tests__/baseline-settings-page.test.tsx
```

Expected: both test files pass.

### Task 3: Verify release readiness

**Files:**
- No additional source files

**Interfaces:**
- Consumes: final frontend source
- Produces: build and browser evidence

- [x] **Step 1: Run frontend tests, copy lint, and production build**

```bash
npm run test:run
npm run lint:copy
npm run build
```

Expected: all commands exit 0.

- [x] **Step 2: Verify responsive rendering**

Check the dashboard KPI cards and baseline detail buttons at mobile, tablet, and desktop widths. Confirm that KPI value/unit and button icon/label remain one line without crossing card padding.

- [x] **Step 3: Review only the intended diff**

```bash
git diff --check
git diff --stat
git status --short
```

Expected: only the plan, two source files, and two test files are changed.
