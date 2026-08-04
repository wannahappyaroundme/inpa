# 인파 블로그 무료 자료 탭 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 인파 블로그 안에 `인파 블로그 | 무료 자료` 탭을 만들고, 기존 무료 자료 3종을 검색 안전한 독립 주소 그대로 한곳에서 찾게 한다.

**Architecture:** `/blog`와 새 정적 경로 `/blog/resources`가 서버 컴포넌트형 공용 탭을 공유한다. 자료 카드의 제목·설명·행동 문구는 기존 `PUBLIC_RESOURCES`를 그대로 소비하며, 기존 계산기와 양식 페이지는 변경하지 않는다. 검색 허용 목록과 사이트맵에 모음 경로를 명시하고 공개 사이트의 별도 `무료 도구` 메뉴는 제거한다.

**Tech Stack:** Next.js 16.2 App Router, React 19 Server Components, TypeScript, Tailwind CSS v4, Vitest, React Testing Library

## Global Constraints

- 블로그 브랜드명은 `인파 블로그`, 자료 탭명은 `무료 자료`로만 표시한다.
- 기존 `/tools/insurance-age`, `/resources/customer-management-sheet`, `/resources/consultation-checklist` 주소와 canonical은 유지한다.
- `/blog/resources`는 공개 색인과 sitemap 대상이며 canonical은 `/blog/resources`다.
- 사용자 화면은 라이트 고정이며 모바일 375px부터 잘림 없이 동작해야 한다.
- 사용자 문구에 em dash를 사용하지 않고, 쉬운 말과 긍정적인 다음 행동을 쓴다.
- DB, 백엔드, 관리자 블로그 CRUD, 자료 3종의 계산·다운로드·체크 로직은 변경하지 않는다.
- 프로덕션 코드는 반드시 실패하는 테스트를 먼저 확인한 뒤 작성한다.

---

## File Map

- Create `inpa_fe/components/blog-section-tabs.tsx`: `/blog`와 `/blog/resources`의 1차 탭 렌더링.
- Create `inpa_fe/app/blog/resources/page.tsx`: 무료 자료 모음, metadata, 카드 3종.
- Create `inpa_fe/components/__tests__/blog-free-resources.test.tsx`: 탭, 자료 카드, 메타데이터, 공개 메뉴 회귀 테스트.
- Modify `inpa_fe/app/blog/page.tsx`: 인파 블로그 명칭과 공용 탭 적용.
- Modify `inpa_fe/app/blog/[slug]/page.tsx`: 상세 헤더와 목록 링크 명칭 정리.
- Modify `inpa_fe/app/blog/loading.tsx`, `inpa_fe/app/blog/error.tsx`: 로딩·오류 화면 명칭 정리.
- Modify `inpa_fe/components/public-site-shell.tsx`: 독립 `무료 도구` 메뉴 제거.
- Modify `inpa_fe/components/public-discovery.tsx`: 홈페이지와 내부 발견 영역의 자료 제목을 `무료 자료`로 통일.
- Modify `inpa_fe/lib/search-policy.ts`: `/blog/resources` 색인 허용과 sitemap metadata 추가.
- Modify `inpa_fe/components/__tests__/search-policy.test.tsx`, `inpa_fe/components/__tests__/sitemap.test.tsx`: 새 경로의 검색 정책 회귀 검증.
- Modify `inpa_fe/scripts/check-copy.js`, `inpa_fe/scripts/check-copy.test.js`: 블로그·자료 화면에서 폐기된 명칭의 재등장 차단.
- Modify `README.md`, `AGENTS.md`: 운영 배포 후 현재 명칭과 배포 결과 기록.

---

### Task 1: 인파 블로그 공용 탭과 무료 자료 화면

**Files:**
- Create: `inpa_fe/components/__tests__/blog-free-resources.test.tsx`
- Create: `inpa_fe/components/blog-section-tabs.tsx`
- Create: `inpa_fe/app/blog/resources/page.tsx`
- Modify: `inpa_fe/app/blog/page.tsx`
- Modify: `inpa_fe/app/blog/[slug]/page.tsx`
- Modify: `inpa_fe/app/blog/loading.tsx`
- Modify: `inpa_fe/app/blog/error.tsx`

**Interfaces:**
- Consumes: `PUBLIC_RESOURCES` from `@/lib/public-resources`.
- Produces: `BlogSectionTabs({ activeSection }: { activeSection: "blog" | "resources" })`.
- Produces: static `metadata: Metadata` and default `BlogResourcesPage()` for `/blog/resources`.

- [ ] **Step 1: 테스트 작성 규칙을 확인한다**

Read `superpowers/test-driven-development/writing-good-tests.md` completely before editing a test.

- [ ] **Step 2: 탭과 자료 화면의 실패 테스트를 작성한다**

Create `components/__tests__/blog-free-resources.test.tsx` with focused behavioral assertions:

```tsx
import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import BlogResourcesPage, { metadata } from "@/app/blog/resources/page";
import { BlogSectionTabs } from "@/components/blog-section-tabs";
import { PUBLIC_INDEX_ROBOTS } from "@/lib/search-policy";

it("인파 블로그와 무료 자료를 독립 주소의 1차 탭으로 제공한다", () => {
  render(<BlogSectionTabs activeSection="resources" />);
  expect(screen.getByRole("link", { name: "인파 블로그" })).toHaveAttribute("href", "/blog");
  expect(screen.getByRole("link", { name: "무료 자료" })).toHaveAttribute("href", "/blog/resources");
  expect(screen.getByRole("link", { name: "무료 자료" })).toHaveAttribute("aria-current", "page");
});

it("무료 자료 화면에서 기존 자료 세 주소로 이동한다", () => {
  render(<BlogResourcesPage />);
  expect(screen.getByRole("heading", { level: 1, name: "무료 자료" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /보험나이 계산기/ })).toHaveAttribute("href", "/tools/insurance-age");
  expect(screen.getByRole("link", { name: /고객 관리표 빈 양식/ })).toHaveAttribute("href", "/resources/customer-management-sheet");
  expect(screen.getByRole("link", { name: /첫 상담 체크리스트/ })).toHaveAttribute("href", "/resources/consultation-checklist");
});

it("무료 자료 모음은 고유 canonical과 공개 색인 정책을 쓴다", () => {
  expect(metadata.alternates).toEqual({ canonical: "/blog/resources" });
  expect(metadata.robots).toEqual(PUBLIC_INDEX_ROBOTS);
  expect(metadata.openGraph).toMatchObject({ url: "/blog/resources" });
});
```

- [ ] **Step 3: 실패가 새 기능 부재 때문인지 확인한다**

Run:

```bash
cd inpa_fe
npm run test:run -- components/__tests__/blog-free-resources.test.tsx
```

Expected: FAIL because `@/components/blog-section-tabs` and `/blog/resources/page` do not exist.

- [ ] **Step 4: 공용 탭을 최소 구현한다**

Create `components/blog-section-tabs.tsx` as a synchronous server component:

```tsx
import Link from "next/link";

const SECTIONS = [
  { key: "blog", href: "/blog", label: "인파 블로그" },
  { key: "resources", href: "/blog/resources", label: "무료 자료" },
] as const;

export function BlogSectionTabs({ activeSection }: { activeSection: "blog" | "resources" }) {
  return (
    <nav aria-label="인파 블로그 메뉴" className="...">
      {SECTIONS.map((section) => (
        <Link
          key={section.key}
          href={section.href}
          aria-current={activeSection === section.key ? "page" : undefined}
          className="..."
        >
          {section.label}
        </Link>
      ))}
    </nav>
  );
}
```

Use a two-column rounded segmented control with a 44px minimum target and visible focus ring. Do not add client state because the route is the state.

- [ ] **Step 5: 무료 자료 모음 페이지를 최소 구현한다**

Create `app/blog/resources/page.tsx`:

```tsx
import type { Metadata } from "next";
import Link from "next/link";

import { BlogSectionTabs } from "@/components/blog-section-tabs";
import { InpaMark } from "@/components/inpa-logo";
import { PUBLIC_RESOURCES } from "@/lib/public-resources";
import { PUBLIC_INDEX_ROBOTS } from "@/lib/search-policy";

const PATH = "/blog/resources";
const DESCRIPTION = "보험설계사가 가입 전에도 바로 쓸 수 있는 보험나이 계산기, 고객 관리표 빈 양식과 첫 상담 체크리스트를 모았습니다.";

export const metadata: Metadata = {
  title: "무료 자료",
  description: DESCRIPTION,
  alternates: { canonical: PATH },
  robots: PUBLIC_INDEX_ROBOTS,
  openGraph: { type: "website", locale: "ko_KR", siteName: "인파(Inpa)", title: "무료 자료 · 인파 블로그", description: DESCRIPTION, url: PATH, images: [{ url: "/opengraph-image.jpg", width: 1200, height: 630 }] },
  twitter: { card: "summary_large_image", title: "무료 자료 · 인파 블로그", description: DESCRIPTION, images: ["/opengraph-image.jpg"] },
};
```

Render the existing blog header, `BlogSectionTabs activeSection="resources"`, a `무료 자료` heading, one privacy explanation, and three `PUBLIC_RESOURCES` cards. Use `md:grid-cols-2 lg:grid-cols-3`; each entire card is a `Link` and shows `resource.actionLabel`.

- [ ] **Step 6: 기존 블로그 화면에 명칭과 탭을 적용한다**

Modify `app/blog/page.tsx`:

```tsx
<span>인파 블로그</span>
...
<h1>인파 블로그</h1>
<BlogSectionTabs activeSection="blog" />
```

Place the 1차 tab above the existing category `nav`; keep all category query and pagination behavior unchanged. Update static title, OG title and description to `인파 블로그`.

Modify detail, loading and error surfaces so the visible blog brand and list-return label use `인파 블로그`. Do not change article URLs or API calls.

- [ ] **Step 7: 집중 테스트를 통과시킨다**

Run:

```bash
cd inpa_fe
npm run test:run -- components/__tests__/blog-free-resources.test.tsx components/__tests__/blog-public.test.tsx
```

Expected: PASS, with existing async blog list/category tests unchanged.

- [ ] **Step 8: 첫 기능 단위를 커밋한다**

```bash
git add inpa_fe/components/__tests__/blog-free-resources.test.tsx inpa_fe/components/blog-section-tabs.tsx inpa_fe/app/blog/resources/page.tsx inpa_fe/app/blog/page.tsx 'inpa_fe/app/blog/[slug]/page.tsx' inpa_fe/app/blog/loading.tsx inpa_fe/app/blog/error.tsx
git commit -m "feat(블로그): 무료 자료 탭 추가"
```

---

### Task 2: 공개 메뉴와 검색 경로를 무료 자료 구조로 통합

**Files:**
- Modify: `inpa_fe/components/__tests__/blog-free-resources.test.tsx`
- Modify: `inpa_fe/components/__tests__/search-policy.test.tsx`
- Modify: `inpa_fe/components/__tests__/sitemap.test.tsx`
- Modify: `inpa_fe/components/public-site-shell.tsx`
- Modify: `inpa_fe/components/public-discovery.tsx`
- Modify: `inpa_fe/lib/search-policy.ts`
- Modify: `inpa_fe/app/sitemap.ts`

**Interfaces:**
- Consumes: `CURRENT_INDEXABLE_PATHS` and `staticSitemapEntries(siteUrl)`.
- Produces: exact indexable path `/blog/resources` with monthly change frequency and priority `0.7`.

- [ ] **Step 1: 공개 메뉴와 검색 정책의 실패 테스트를 추가한다**

Extend `blog-free-resources.test.tsx`:

```tsx
import { PublicSiteShell } from "@/components/public-site-shell";
import { PublicDiscoverySection } from "@/components/public-discovery";

it("공개 상단 메뉴는 무료 자료를 블로그 안에서 찾게 한다", () => {
  render(<PublicSiteShell><main>본문</main></PublicSiteShell>);
  expect(screen.queryByRole("link", { name: "무료 도구" })).not.toBeInTheDocument();
  expect(screen.getAllByRole("link", { name: "블로그" })[0]).toHaveAttribute("href", "/blog");
});

it("홈페이지 자료 영역은 무료 자료 이름을 쓴다", () => {
  render(<PublicDiscoverySection />);
  expect(screen.getByRole("heading", { name: "무료 자료" })).toBeInTheDocument();
});
```

Extend `search-policy.test.tsx`:

```tsx
import { metadata as blogResourcesMetadata } from "@/app/blog/resources/page";

expect(blogResourcesMetadata.robots).toEqual({ index: true, follow: true });
expect(classifySearchPath("/blog/resources")).toBe("indexable");
```

Extend `sitemap.test.tsx`:

```tsx
expect(paths).toContain("/blog/resources");
```

- [ ] **Step 2: 변경 전 실패를 확인한다**

Run:

```bash
cd inpa_fe
npm run test:run -- components/__tests__/blog-free-resources.test.tsx components/__tests__/search-policy.test.tsx components/__tests__/sitemap.test.tsx
```

Expected: FAIL because the public shell still exposes `무료 도구`, the homepage section uses the previous heading, and `/blog/resources` is absent from `CURRENT_INDEXABLE_PATHS`.

- [ ] **Step 3: 공개 메뉴와 자료 영역을 정리한다**

Modify `components/public-site-shell.tsx` by deleting only:

```tsx
{ href: "/#tools", label: "무료 도구" },
```

Keep `블로그` linked to `/blog`. Modify `components/public-discovery.tsx` so the landing section h2 and compact link section both use `무료 자료`. Keep `id="tools"` temporarily for old external anchors and keep each direct resource link for SEO and returning visitors.

- [ ] **Step 4: 검색 허용 목록과 사이트맵에 새 모음 경로를 추가한다**

Modify `lib/search-policy.ts`:

```ts
export const CURRENT_INDEXABLE_PATHS = [
  "/",
  ...getSearchHubPaths(),
  ...getPublicResourcePaths(),
  "/story",
  "/blog",
  "/blog/resources",
  "/faq",
  "/data-policy",
] as const;

const SITEMAP_META = {
  // existing rows
  "/blog/resources": { changeFrequency: "monthly", priority: 0.7 },
};
```

Update only comments in `app/sitemap.ts` to match the current names. Do not change the backend blog sitemap fallback behavior.

- [ ] **Step 5: 검색·메뉴 집중 테스트를 통과시킨다**

Run:

```bash
cd inpa_fe
npm run test:run -- components/__tests__/blog-free-resources.test.tsx components/__tests__/search-policy.test.tsx components/__tests__/sitemap.test.tsx
```

Expected: PASS and sitemap order still equals `CURRENT_INDEXABLE_PATHS` before dynamic posts.

- [ ] **Step 6: 두 번째 기능 단위를 커밋한다**

```bash
git add inpa_fe/components/__tests__/blog-free-resources.test.tsx inpa_fe/components/__tests__/search-policy.test.tsx inpa_fe/components/__tests__/sitemap.test.tsx inpa_fe/components/public-site-shell.tsx inpa_fe/components/public-discovery.tsx inpa_fe/lib/search-policy.ts inpa_fe/app/sitemap.ts
git commit -m "feat(자료): 공개 탐색과 검색 경로 통합"
```

---

### Task 3: 확정 명칭의 자동 회귀 방지

**Files:**
- Modify: `inpa_fe/scripts/check-copy.test.js`
- Modify: `inpa_fe/scripts/check-copy.js`
- Modify: active blog comments in `inpa_fe/app`, `inpa_fe/components`, `inpa_fe/lib` only where they still use a retired blog brand label.

**Interfaces:**
- Produces: copy-lint rule scoped to `app/blog`, `components/blog-section-tabs.tsx`, and `components/public-discovery.tsx`.

- [ ] **Step 1: 폐기된 화면 명칭을 잡는 실패 테스트를 작성한다**

Add a helper that creates `app/blog/page.tsx` under a temporary root and assert the two retired labels each produce one violation, while `인파 블로그` and `무료 자료` produce zero.

```js
test("blocks retired blog and resource labels on blog surfaces", () => {
  for (const label of ["인파 노트", "유용한 자료"]) {
    assert.equal(scanBlogSurface(`export default function Page(){return <div>${label}</div>}`).length, 1);
  }
  assert.equal(scanBlogSurface("export default function Page(){return <div>인파 블로그 무료 자료</div>}").length, 0);
});
```

These strings are internal regression fixtures, not rendered UI.

- [ ] **Step 2: 실패를 확인한다**

Run:

```bash
cd inpa_fe
npm run test:copy-lint
```

Expected: FAIL because no naming rule exists.

- [ ] **Step 3: 경로 한정 카피 규칙을 구현한다**

Add a scoped rule in `scripts/check-copy.js`:

```js
const BLOG_RESOURCE_SURFACES = [
  "app/blog",
  "components/blog-section-tabs.tsx",
  "components/public-discovery.tsx",
];

{
  name: "폐기된 블로그·자료 명칭",
  re: /인파 노트|유용한 자료/,
  paths: BLOG_RESOURCE_SURFACES,
  hint: "블로그는 '인파 블로그', 자료 탭은 '무료 자료'로 표시하세요.",
},
```

Because comments are stripped, historical technical comments do not produce false positives; update nearby active comments to the current brand for agent clarity.

- [ ] **Step 4: 카피 규칙과 전체 현재 카피를 검증한다**

Run:

```bash
cd inpa_fe
npm run test:copy-lint
npm run lint:copy
```

Expected: node tests PASS and copy scan reports zero findings.

- [ ] **Step 5: 명칭 회귀 방지를 커밋한다**

```bash
git add inpa_fe/scripts/check-copy.js inpa_fe/scripts/check-copy.test.js inpa_fe/app inpa_fe/components inpa_fe/lib
git commit -m "test(카피): 블로그 무료 자료 명칭 고정"
```

Stage only files actually changed by this task; never use `git add -A` or `git add -u`.

---

### Task 4: 전체 검증, 리뷰, GitHub 병합과 운영 배포

**Files:**
- No production code expected unless verification reveals a defect.
- Modify after deployment: `README.md`, `AGENTS.md`.

**Interfaces:**
- Produces: verified production `/blog` and `/blog/resources`, unchanged existing resource routes.

- [ ] **Step 1: 전체 프론트 자동검사를 실행한다**

```bash
cd inpa_fe
npm run test:run
npm run test:copy-lint
npm run lint:copy
npm run lint:blog
npm run build
```

Expected: all Vitest suites pass, copy lint has zero findings, blog release lint passes, and Next build lists `/blog/resources` as a route.

- [ ] **Step 2: 로컬 운영 빌드를 실제 브라우저로 확인한다**

Run `npm start` from the successful build, then inspect at 1440px desktop and 375px mobile:

- `/blog`: `인파 블로그` active, category filters intact.
- `/blog/resources`: `무료 자료` active, three cards and all buttons visible.
- each of the three resource URLs: original calculator/download/check behavior still works.
- public resource shell: no independent `무료 도구` nav item.
- canonical and OG metadata exist in rendered HTML.

- [ ] **Step 3: 변경 범위와 안전성을 독립적으로 리뷰한다**

Use `superpowers:requesting-code-review`, check correctness, SEO, accessibility, mobile UX, copy, and regression risk. Fix every confirmed Critical/Important finding with a failing test first; record rejected findings with reasons.

- [ ] **Step 4: 원격 최신 상태를 확인하고 기능 브랜치를 게시한다**

```bash
git fetch origin
git log --oneline --left-right origin/master...HEAD
git status --short
git push -u origin codex/blog-free-resources
```

Use `github:yeet` to open a ready PR with verification evidence. Wait for GitHub Actions and fix any failure before merge.

- [ ] **Step 5: PR을 병합하고 자동 배포를 확인한다**

Merge only after all required checks pass. Wait for Vercel production deployment to report Ready. This change has no backend or DB work, so Render health is a regression smoke check only.

- [ ] **Step 6: 운영 URL을 직접 검증한다**

Verify:

```text
https://www.inpa.kr/blog
https://www.inpa.kr/blog/resources
https://www.inpa.kr/tools/insurance-age
https://www.inpa.kr/resources/customer-management-sheet
https://www.inpa.kr/resources/consultation-checklist
https://www.inpa.kr/sitemap.xml
https://inpa-be.onrender.com/healthz/
```

Expected: all pages 200; sitemap includes `/blog/resources` exactly once; tabs and links match the approved names; backend health returns `{"status":"ok","service":"inpa-be"}`.

- [ ] **Step 7: 현재 기준 문서를 배포 사실로 갱신한다**

Update `README.md` in Korean with the user-visible navigation and exact production verification. Update `AGENTS.md` in dense English with the standing naming rule and deployed commit/PR/check facts. Replace active current-state references to the retired blog brand with `인파 블로그`; historical plan files remain unchanged.

- [ ] **Step 8: 문서 변경도 검사·병합·배포한다**

Run `git diff --check`, commit only `README.md` and `AGENTS.md`, push a short-lived docs branch or the existing branch if GitHub still permits it, open/merge the docs PR, and confirm the final production URL remains healthy.

- [ ] **Step 9: 최종 보고한다**

Report exactly:

```text
Changed: [사용자 관점 변경]
Verified by: [테스트, 빌드, 브라우저, 운영 URL]
Result: [PR, 운영 상태, sitemap]
Unverified: [없으면 없음]
```
