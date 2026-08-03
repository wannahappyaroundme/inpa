# Inpa Search and AI Growth Release 2: Evidence Hubs Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task. Use superpowers:test-driven-development before product code and superpowers:verification-before-completion before every success claim.

**Goal:** 보험설계사의 실제 검색 질문을 해결하면서 인파 기능을 자연스럽게 증명하는 솔루션 3개와 실무 가이드 4개를 공개한다.

**Architecture:** CMS를 늘리지 않고 `search-content.ts`의 타입이 있는 정적 원고를 `solutions/[slug]`와 `guides/[slug]` 두 템플릿으로 렌더한다. 모든 페이지는 답부터 제시하고, 실제 인파 화면, 단계별 실행법, 맞는 사용자, 한계, 관련 글, 첫 분석 CTA를 같은 정보 구조로 제공한다. sitemap·canonical·OG·Breadcrumb JSON-LD·내부 링크가 같은 content manifest를 사용한다.

**Tech Stack:** Next.js 16.2.9 static generation, React server components, TypeScript, Tailwind v4, Next Image, Vitest, existing 2880×1800 product WebP captures.

**Release status (2026-08-04):** Completed and live. PR #160 merged as `4dad276`; CI run `30829605143` passed. All seven URLs, metadata, JSON-LD, internal links, and sitemap entries were verified in production. Google/Naver console state remained unverified because the browser sessions were signed out; no duplicate sitemap submission was made.

## 공개 URL과 검색 의도

| URL | 답하려는 핵심 질문 | 제품 근거 |
|---|---|---|
| `/solutions/customer-management` | 보험설계사 고객 관리를 어떻게 한 흐름으로 하나 | 고객 단계별·목록 화면 |
| `/solutions/policy-analysis` | 여러 증권의 보장을 어떻게 같은 기준으로 정리하나 | 보장 한눈표·여러 증권 비교 화면 |
| `/solutions/sales-management` | 첫 연락부터 미팅·공유까지 어떻게 놓치지 않나 | 대시보드·일정 화면 |
| `/guides/first-consultation` | 첫 상담 전 무엇을 준비하나 | 고객 등록·일정·보장 정리 흐름 |
| `/guides/customer-follow-up` | 후속 연락을 어떤 순서로 관리하나 | 무접촉 표시·상태·단계별 화면 |
| `/guides/policy-review` | 증권을 받을 때 무엇을 확인하나 | 직접 입력·증권 정리·확인 흐름 |
| `/guides/factual-comparison` | 추천 없이 여러 증권을 어떻게 사실로 비교하나 | 증권 A/B 중립 비교 화면 |

## 파일 지도

- Create `inpa_fe/lib/search-content.ts`: 7개 원고와 관련 페이지 manifest.
- Create `inpa_fe/lib/search-content.test.ts`: 완전성·중복·copy·경로 계약.
- Create `inpa_fe/components/public-site-shell.tsx`: 공개 헤더·푸터·모바일 내비게이션.
- Create `inpa_fe/components/search-hub-page.tsx`: 답 우선 본문, proof, steps, FAQ, CTA 템플릿.
- Create `inpa_fe/components/public-discovery-strip.tsx`: 랜딩에서 솔루션·가이드로 가는 내부 링크.
- Create `inpa_fe/components/__tests__/search-hubs.test.tsx`: 렌더·메타·구조화 데이터 계약.
- Create `inpa_fe/app/solutions/[slug]/page.tsx`, `app/guides/[slug]/page.tsx`: 정적 route와 metadata.
- Modify `inpa_fe/components/structured-data.tsx`: `breadcrumbList`, `webPage` helper.
- Modify `inpa_fe/app/page.tsx`: discovery strip 추가.
- Modify `inpa_fe/app/faq/page.tsx`, `app/blog/page.tsx`, `app/blog/[slug]/page.tsx`: 관련 허브 링크.
- Modify `inpa_fe/lib/search-policy.ts`, `app/sitemap.ts`, 관련 테스트: 7개 공개 URL 추가.

### Task 0: Release 1 운영 기준에서 격리 브랜치를 만든다

- [ ] **Step 1: Release 1 운영 SHA와 origin/master 일치를 확인한다**

```bash
git fetch origin
git log -1 --oneline origin/master
```

- [ ] **Step 2: 격리 worktree를 만든다**

```bash
git worktree add -b codex/inpa-search-ai-evidence-hubs /tmp/inpa-search-ai-evidence-hubs origin/master
```

- [ ] **Step 3: 기준선을 실행한다**

```bash
cd /tmp/inpa-search-ai-evidence-hubs/inpa_fe
npm run test:run -- components/__tests__/search-policy.test.tsx components/__tests__/telemetry-privacy.test.tsx
npm run lint:copy
npm run build
```

Expected: Release 1 보호 계약이 모두 통과한다.

### Task 1: 타입이 있는 7개 원고 manifest를 만든다

**Interfaces:**

```ts
export type SearchHubKind = "solution" | "guide";
export interface SearchHubContent {
  kind: SearchHubKind;
  slug: string;
  title: string;
  description: string;
  answer: string;
  fitFor: string[];
  steps: { title: string; body: string }[];
  evidence: { src: string; alt: string; caption: string }[];
  checklist: string[];
  limitations: string[];
  faq: { q: string; a: string }[];
  relatedPaths: string[];
  updatedAt: string;
}
export const SEARCH_HUBS: readonly SearchHubContent[];
export function getSearchHub(kind: SearchHubKind, slug: string): SearchHubContent | undefined;
export function getSearchHubPaths(): string[];
```

- [ ] **Step 1: manifest 완전성 실패 테스트를 쓴다**

정확히 7개, slug/path/title 중복 없음, solution 3·guide 4, evidence 파일 존재, alt/caption 있음, steps 3개 이상, FAQ 3개 이상, 관련 경로 유효, CTA 대상 `/register`, em dash·금칙어·법률 조항 표기 없음, 제공하지 않는 자동 메시지 발송·추천 판정 주장 없음으로 검사한다.

- [ ] **Step 2: RED를 확인한다**

```bash
npm run test:run -- lib/search-content.test.ts
```

- [ ] **Step 3: 실제 제품 증거를 기준으로 원고를 작성한다**

기존 `/landing-test/customers.webp`, `coverage.webp`, `compare.webp`, `dashboard.webp`, `schedule.webp`만 사용한다. 문단은 `질문에 대한 짧은 답 -> 왜 놓치는지 -> 인파에서 하는 순서 -> 직접 확인할 체크리스트 -> 맞는 사용자 -> 한계 -> 다음 행동` 순서로 쓴다.

- [ ] **Step 4: 원고 테스트와 copy lint를 통과시킨다**

```bash
npm run test:run -- lib/search-content.test.ts
npm run lint:copy
```

- [ ] **Step 5: 원고 manifest만 커밋한다**

```bash
git add inpa_fe/lib/search-content.ts inpa_fe/lib/search-content.test.ts
git commit -m "feat(검색): 설계사 질문 중심 공개 원고 7개 추가"
```

### Task 2: 공통 공개 템플릿과 구조화 데이터를 구현한다

- [ ] **Step 1: 실패하는 렌더 계약 테스트를 쓴다**

각 종류 샘플 페이지에 단 하나의 h1, 답 우선 문단, fitFor, steps, 실제 screenshot alt/caption, limitations, FAQ, 관련 링크, `/register` CTA가 있는지 검사한다. Breadcrumb JSON-LD의 첫 항목은 홈, 마지막 항목은 현재 canonical이어야 한다.

- [ ] **Step 2: RED를 확인한다**

```bash
npm run test:run -- components/__tests__/search-hubs.test.tsx
```

- [ ] **Step 3: `PublicSiteShell`과 `SearchHubPage`를 구현한다**

공개 shell은 홈, 솔루션, 가이드, 블로그, FAQ, 무료 시작 CTA를 제공한다. 본문은 모바일 320px부터 읽히고, screenshot은 `<Image>`로 dimensions와 responsive sizes를 지정한다. 로딩 API가 없는 정적 페이지이므로 네트워크 오류 상태는 만들지 않는다. slug가 manifest에 없으면 `notFound()`한다.

- [ ] **Step 4: 구조화 데이터 helper를 추가한다**

`breadcrumbList(items)`와 `webPage({name,description,url,dateModified})`를 추가한다. 정적 원고만 JSON-LD에 넣고 사용자 입력은 넣지 않는다. 평점, 후기, 수상, 임의 통계 schema는 추가하지 않는다.

- [ ] **Step 5: 렌더 테스트를 GREEN으로 만든다**

```bash
npm run test:run -- components/__tests__/search-hubs.test.tsx
```

- [ ] **Step 6: 템플릿과 구조화 데이터만 커밋한다**

```bash
git add inpa_fe/components/public-site-shell.tsx inpa_fe/components/search-hub-page.tsx inpa_fe/components/structured-data.tsx inpa_fe/components/__tests__/search-hubs.test.tsx
git commit -m "feat(검색): 근거 중심 공개 페이지 템플릿 구현"
```

### Task 3: 7개 정적 route와 metadata를 구현한다

- [ ] **Step 1: route 계약 테스트를 추가한다**

`generateStaticParams()`가 종류별 정확한 slug를 반환하고 `dynamicParams=false`이며, metadata에 고유 title·description·canonical·OG URL·`PUBLIC_INDEX_ROBOTS`가 있는지 검사한다.

- [ ] **Step 2: RED를 확인한다**

```bash
npm run test:run -- components/__tests__/search-hubs.test.tsx
```

- [ ] **Step 3: 두 dynamic route를 구현한다**

`app/solutions/[slug]/page.tsx`와 `app/guides/[slug]/page.tsx`가 manifest를 읽어 build-time 정적 HTML을 만든다. 두 route에서 같은 template을 재사용하고 kind mismatch는 404 처리한다.

- [ ] **Step 4: route 테스트와 build를 통과시킨다**

```bash
npm run test:run -- components/__tests__/search-hubs.test.tsx
npm run build
```

Expected: build route 목록에 7개가 모두 정적 페이지로 나온다.

- [ ] **Step 5: route만 커밋한다**

```bash
git add 'inpa_fe/app/solutions/[slug]/page.tsx' 'inpa_fe/app/guides/[slug]/page.tsx' inpa_fe/components/__tests__/search-hubs.test.tsx
git commit -m "feat(검색): 솔루션 3개와 실무 가이드 4개 공개"
```

### Task 4: 랜딩·블로그·FAQ·sitemap에서 발견 경로를 잇는다

- [ ] **Step 1: 내부 링크와 sitemap 실패 테스트를 쓴다**

랜딩 discovery strip에 3개 solution과 4개 guide가 최소 한 번씩 연결되고, FAQ·blog 공개 shell에서 허브로 갈 수 있으며, sitemap에 7개가 중복 없이 포함되는지 검사한다.

- [ ] **Step 2: RED를 확인한다**

```bash
npm run test:run -- components/__tests__/search-hubs.test.tsx components/__tests__/search-policy.test.tsx
```

- [ ] **Step 3: 발견 경로를 구현한다**

`PublicDiscoveryStrip`을 `app/page.tsx`의 `ServiceLanding` 다음에 넣어 기존 랜딩 컴포넌트를 건드리지 않는다. FAQ와 blog의 관련 링크는 `PublicSiteShell` 또는 작은 공유 nav로 통합해 중복 카피를 줄인다.

- [ ] **Step 4: allowlist와 sitemap을 manifest 기반으로 확장한다**

`getSearchHubPaths()` 결과가 `search-policy.ts`의 정적 entries에 들어가게 하되 정적 import cycle이 없도록 policy가 content의 path-only export를 소비한다. sitemap 순서는 home, solution, guide, 기타 공개 페이지, blog post로 고정한다.

- [ ] **Step 5: 테스트와 copy lint를 통과시킨다**

```bash
npm run test:run -- components/__tests__/search-hubs.test.tsx components/__tests__/search-policy.test.tsx components/__tests__/sitemap.test.tsx
npm run lint:copy
```

- [ ] **Step 6: 내부 링크·sitemap만 커밋한다**

```bash
git add inpa_fe/components/public-discovery-strip.tsx inpa_fe/app/page.tsx inpa_fe/app/faq/page.tsx inpa_fe/app/blog/page.tsx 'inpa_fe/app/blog/[slug]/page.tsx' inpa_fe/lib/search-policy.ts inpa_fe/app/sitemap.ts inpa_fe/components/__tests__/search-hubs.test.tsx inpa_fe/components/__tests__/search-policy.test.tsx inpa_fe/components/__tests__/sitemap.test.tsx
git commit -m "feat(검색): 공개 근거 페이지의 내부 연결과 sitemap 확장"
```

### Task 5: 시각 QA, 독립 리뷰, PR, 운영 배포

- [ ] **Step 1: 전체 FE 게이트를 실행한다**

```bash
npm run test:run
npm run lint:copy
npm run build
git diff --check
```

- [ ] **Step 2: 브라우저에서 7개 페이지를 desktop·mobile로 검수한다**

`browser:control-in-app-browser`를 사용해 1440×900과 390×844에서 7개 URL을 본다. 첫 화면 답, 이미지 crop, 캡션, 단계, CTA, keyboard focus, 320px overflow, reduced-motion, canonical/robots를 검사하고 대표 화면을 캡처한다.

- [ ] **Step 3: 구조화 데이터와 사실성을 검수한다**

렌더 HTML의 JSON-LD를 JSON parse하고 canonical과 breadcrumb URL 일치를 검사한다. 제품 제공 여부는 현재 `AGENTS.md`의 기능 목록과 실제 route 화면을 대조한다.

- [ ] **Step 4: 독립 리뷰를 요청하고 중요 항목을 수정한다**

`superpowers:requesting-code-review`로 검색 의도, 제품 사실성, 보험·규정 중립성, UX, 접근성, 개인정보를 검토한다. Critical/Important 0이 될 때까지 재검증한다.

- [ ] **Step 5: PR·CI·운영 배포를 완료한다**

`github:yeet`로 `feat(검색): 설계사 질문 중심 근거 허브 7개` PR을 만들고 최신 master diff를 확인한다. CI 성공 후 병합하고 Vercel/Render가 merge SHA를 배포했는지 확인한다.

- [ ] **Step 6: 운영 URL 7개와 sitemap을 확인한다**

각 URL의 200, title, description, canonical, index/follow, OG image, JSON-LD를 확인한다. sitemap에 7개가 있고 `/legal/*`, private route, token route가 없는지 확인한다. Sentry와 Vercel 오류를 5분 관찰한다.

- [ ] **Step 7: 기존 검색 도구에는 재등록하지 않고 오류만 감사한다**

`browser:control-in-app-browser`의 기존 로그인 세션으로 Google Search Console과 네이버 서치어드바이저를 연다. 소유권, sitemap 최신 성공, 색인 오류를 확인하고 실제 오류가 있을 때만 같은 `/sitemap.xml`을 재제출한다. 클릭한 메뉴, 상태값, 성공 신호를 운영 기록에 남긴다.
