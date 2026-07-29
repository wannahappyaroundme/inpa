# Landing Manager Copy and Showcase Recruiting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align the public landing pricing and navigation with the live Plus-to-Manager behavior, and replace the showcase recruiting workspace's generic error with a safe read-only explanation.

**Architecture:** Keep the change frontend-only. Reuse the existing shared pricing and service-landing components, then make `StatusPanel` treat only `ApiError.code === "SHOWCASE_ACTION_RESTRICTED"` from optional public-page/campaign reads as a restricted capability instead of a workspace failure; summary and candidate reads remain unchanged.

**Tech Stack:** Next.js 16.2, React 19, TypeScript, Tailwind CSS 4, Vitest, Testing Library.

## Global Constraints

- Do not expose `Profile.is_showcase` through the profile API.
- Do not relax any backend showcase guard or enable any production feature flag.
- Do not add insurance-review notices or FAQs while the reviewed-import gate is closed.
- User-facing Korean must use easy words, positive next-action framing, and no em dash.
- Service pages remain light-fixed.
- Write each regression test first and observe the expected failure before changing production code.

---

### Task 1: Public landing pricing and navigation

**Files:**
- Modify: `inpa_fe/components/__tests__/pricing-four-tiers.test.tsx`
- Modify: `inpa_fe/components/__tests__/service-landing.test.tsx`
- Modify: `inpa_fe/components/brand-story-sections.tsx`
- Modify: `inpa_fe/components/service-landing.tsx`

**Interfaces:**
- Consumes: existing `PricingFourTiers({ id, registerHref })` and `ServiceLanding()`.
- Produces: the same component signatures with a three-card pricing model and one responsive header navigation.

- [ ] **Step 1: Write the failing pricing test**

Change the pricing test to assert the customer-visible contract:

```tsx
expect(screen.queryByText("관리자 전용")).not.toBeInTheDocument();
expect(screen.queryByText("Manager", { selector: "span" })).not.toBeInTheDocument();
expect(screen.getByText("첫 설계사 합류 시 Manager 역할 자동 활성화")).toBeInTheDocument();
expect(screen.getAllByText("19,900원")).toHaveLength(1);
expect(screen.getByText("인파 요금제")).toBeInTheDocument();
```

- [ ] **Step 2: Write the failing landing navigation test**

Update the blog assertion from `인파 노트` to `블로그` and add:

```tsx
const header = screen.getByRole("banner");
expect(header).toHaveTextContent("블로그");
expect(header).toHaveTextContent("로그인");
expect(header).toHaveTextContent("무료로 시작하기");
expect(header).not.toHaveTextContent("실제 화면");
expect(header).not.toHaveTextContent("주요 기능");
expect(header).not.toHaveTextContent("요금");
expect(header).not.toHaveTextContent("자주 묻는 질문");
expect(screen.queryByRole("button", { name: "메뉴 열기" })).not.toBeInTheDocument();
```

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```bash
cd inpa_fe
npx vitest run components/__tests__/pricing-four-tiers.test.tsx components/__tests__/service-landing.test.tsx
```

Expected: pricing assertions fail because the Manager card and duplicate price still exist; landing assertions fail because the old anchor navigation, hamburger button, and `인파 노트` still exist.

- [ ] **Step 4: Implement the three-card pricing model**

In `brand-story-sections.tsx`:

- remove `managerOnly` from the tier type and rendering;
- delete the standalone Manager tier;
- add the exact Plus features:

```ts
"첫 설계사 합류 시 Manager 역할 자동 활성화"
"팀원과 팀 전체 흐름 관리"
```

- set the Plus footnote to `개인 설계 업무와 팀 관리를 같은 Plus에서 이용합니다.`;
- change the title to `인파 요금제`;
- use `grid-cols-1 sm:grid-cols-3`.

- [ ] **Step 5: Implement one responsive header navigation**

In `service-landing.tsx`:

- remove `menuOpen`, `Menu`, and `X`;
- replace the desktop anchors and mobile menu with one `nav` containing `블로그`, `로그인`, and `무료로 시작하기`;
- retain the existing UTM-aware `CtaLink` destinations;
- replace the footer label `인파 노트` with `블로그`.

- [ ] **Step 6: Run the focused tests and verify GREEN**

Run:

```bash
cd inpa_fe
npx vitest run components/__tests__/pricing-four-tiers.test.tsx components/__tests__/service-landing.test.tsx
```

Expected: both test files pass with zero failures.

- [ ] **Step 7: Commit the landing change**

```bash
git add inpa_fe/components/__tests__/pricing-four-tiers.test.tsx \
  inpa_fe/components/__tests__/service-landing.test.tsx \
  inpa_fe/components/brand-story-sections.tsx \
  inpa_fe/components/service-landing.tsx
git commit -m "fix(랜딩): Manager 역할과 Plus 요금 안내 통일"
```

### Task 2: Showcase recruiting read-only fallback

**Files:**
- Create: `inpa_fe/components/__tests__/recruiting-status-showcase.test.tsx`
- Modify: `inpa_fe/components/recruiting/recruiting-labels.ts`
- Modify: `inpa_fe/components/recruiting/status-panel.tsx`

**Interfaces:**
- Produces: `isShowcaseActionRestricted(error: unknown): boolean`.
- `StatusPanel` consumes the helper and keeps the existing public component API.

- [ ] **Step 1: Write the failing showcase component test**

Mock:

```ts
getRecruitingSummary -> a zero-count RecruitingSummary
listRecruitingCandidates -> { count: 0, next: null, previous: null, results: [] }
getRecruitingPage -> reject new ApiError(403, "SHOWCASE_ACTION_RESTRICTED", ...)
getRecruitingCampaign -> reject the same error
```

Render the real `StatusPanel` and assert:

```tsx
expect(await screen.findByText("시연 계정에서는 등록된 자료로 영입 흐름을 확인할 수 있어요.")).toBeInTheDocument();
expect(screen.getByText("오늘 확인")).toBeInTheDocument();
expect(screen.queryByRole("button", { name: "다시 불러오기" })).not.toBeInTheDocument();
expect(screen.queryByText("잠시 후 다시 확인하면 이어갈 수 있어요.")).not.toBeInTheDocument();
```

Add a second test where `getRecruitingPage` rejects `new ApiError(500, "500", "서버 오류")` and assert the existing retry error remains visible.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
cd inpa_fe
npx vitest run components/__tests__/recruiting-status-showcase.test.tsx
```

Expected: the showcase test fails because `StatusPanel` currently collapses the optional public reads into the generic error state.

- [ ] **Step 3: Add the exact showcase error classifier**

In `recruiting-labels.ts`:

```ts
export function isShowcaseActionRestricted(error: unknown): boolean {
  return error instanceof ApiError
    && error.code === "SHOWCASE_ACTION_RESTRICTED";
}
```

Do not classify every 403 response as showcase behavior.

- [ ] **Step 4: Separate required and optional context reads**

In `status-panel.tsx`:

- add `publicActionsRestricted` state;
- load the recruiting summary as required context;
- load page and campaign as optional public-action context;
- if the optional requests fail with `isShowcaseActionRestricted`, set `pageInfo` and `campaign` to `null`, set `publicActionsRestricted=true`, and do not set the general error;
- rethrow all other optional-context failures into the existing error path.

- [ ] **Step 5: Render the positive showcase state**

When `publicActionsRestricted` is true:

- show a status card above the summary with the exact lead sentence:

```text
시연 계정에서는 등록된 자료로 영입 흐름을 확인할 수 있어요.
```

- follow with:

```text
지원자가 연결되면 단계별 현황과 다음 연락이 이 화면에 표시돼요. 나의 영입 페이지 공개와 캠페인 링크는 일반 계정에서 이어갈 수 있어요.
```

- when the candidate list is empty, do not render `RecruitingEmpty` or any public-link CTA.

- [ ] **Step 6: Run the focused test and verify GREEN**

Run:

```bash
cd inpa_fe
npx vitest run components/__tests__/recruiting-status-showcase.test.tsx
```

Expected: showcase and ordinary-error cases both pass.

- [ ] **Step 7: Commit the showcase fallback**

```bash
git add inpa_fe/components/__tests__/recruiting-status-showcase.test.tsx \
  inpa_fe/components/recruiting/recruiting-labels.ts \
  inpa_fe/components/recruiting/status-panel.tsx
git commit -m "fix(시연): 영입 현황을 읽기 전용으로 안내"
```

### Task 3: Full verification and delivery

**Files:**
- Modify only if verification exposes a requirement regression.

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces: verified branch ready for PR.

- [ ] **Step 1: Run all frontend tests**

```bash
cd inpa_fe
npm run test:run
npm run test:unit
npm run test:copy-lint
```

Expected: all test commands exit 0.

- [ ] **Step 2: Run copy lint and production build**

```bash
cd inpa_fe
npm run lint:copy
npm run build
```

Expected: copy scan reports zero findings and Next.js build exits 0 with all routes generated.

- [ ] **Step 3: Inspect the final diff**

```bash
git diff --check
git status --short
git diff origin/master...HEAD --stat
```

Expected: no whitespace errors and only the approved spec, plan, tests, landing components, and recruiting components are changed.

- [ ] **Step 4: Push and open a PR**

Fetch immediately before push, confirm `origin/master..HEAD`, push `codex/landing-manager-copy`, and open a ready PR to `master`.

- [ ] **Step 5: Merge after CI passes**

Confirm backend, frontend, PostgreSQL concurrency, and secret scan checks are green before merging.

- [ ] **Step 6: Verify production**

After auto-deploy:

- public landing contains exactly one `19,900원`, no standalone Manager card, and the new Plus wording;
- public landing header contains only the approved three actions;
- authenticated showcase `/sales?tab=recruiting` shows the positive showcase status instead of `다시 불러오기`;
- `https://inpa-be.onrender.com/healthz/` returns `{"status":"ok","service":"inpa-be"}`.
