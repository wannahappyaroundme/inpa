# Inpa Search and AI Growth Release 1: Safe Indexing Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Use superpowers:test-driven-development before product code and superpowers:verification-before-completion before every success claim.

**Goal:** 공개 근거 페이지만 색인하고, 고객별 토큰·고객 ID·쿼리값은 Vercel Analytics, Speed Insights, Sentry에 전송되기 전에 비식별화한다.

**Architecture:** 루트 메타데이터를 fail-closed `noindex`로 바꾸고 공개 페이지가 `index,follow`를 명시하게 한다. sitemap은 이 공개 allowlist에서 생성하며 초안 약관은 제거한다. 전역 분석 컴포넌트와 Sentry는 하나의 순수 URL 비식별화 모듈을 공유하고, 민감한 동적 경로는 템플릿 경로로 바꾸며 query/hash를 모두 버린다.

**Tech Stack:** Next.js 16.2.9 App Router metadata routes, TypeScript, Vitest, Vercel Analytics 2, Speed Insights 2, Sentry Next.js 10.

## 계약과 제약

- Next 구현 전에 설치된 문서 `node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/01-metadata/robots.md`와 `sitemap.md`를 다시 읽는다.
- 검색 허용 정적 URL은 `/`, `/story`, `/blog`, `/faq`, `/data-policy`다. 공개 게시된 `/blog/[slug]`는 서버 값 `is_noindex=false`일 때만 허용한다.
- `/legal/*`는 현재 초안 레이아웃의 `noindex`를 유지하고 sitemap에서 제거한다.
- `/s/`, `/b/`, `/c/`, `/d/`, `/p/`, `/r/`, `/recruiting/join/`, `/admin`, `/api`는 robots에서 계속 차단한다.
- signed token, 고객 ID, 주문 ID, 게시판 비공개 ID, 이메일, 전화번호, query/hash 원문은 telemetry payload에 남지 않는다.
- 비식별화가 URL을 해석하지 못하면 원문을 보내지 않고 `https://www.inpa.kr/telemetry-redacted`로 대체한다.
- `OAI-SearchBot`을 포함한 검색·AI 봇은 동일한 공개 허용·민감 경로 차단 규칙을 쓴다. 별도 `llms.txt`는 만들지 않는다.

## 파일 지도

- Create `inpa_fe/lib/search-policy.ts`: 공개 색인 목록, route 분류, robots 상수, 메타데이터 상수.
- Create `inpa_fe/lib/telemetry-privacy.ts`: URL·문자열·Sentry event 비식별화 순수 함수.
- Create `inpa_fe/components/public-telemetry.tsx`: Vercel Analytics·Speed Insights `beforeSend` 연결.
- Create `inpa_fe/components/__tests__/search-policy.test.tsx`: 색인·robots·sitemap 계약.
- Create `inpa_fe/components/__tests__/telemetry-privacy.test.tsx`: canary 비유출 회귀 테스트.
- Modify `inpa_fe/app/layout.tsx`: fail-closed robots와 안전한 전역 telemetry.
- Modify `inpa_fe/app/page.tsx`, `app/story/page.tsx`, `app/faq/page.tsx`, `app/blog/page.tsx`, `app/blog/[slug]/page.tsx`, `app/data-policy/page.tsx`: 명시적 공개 robots와 canonical.
- Modify `inpa_fe/app/robots.ts`, `app/sitemap.ts`: 단일 정책 모듈 사용, 초안 제거, 동적 글 최신 목록 fail-closed 조회.
- Modify `inpa_fe/lib/sentry-shared.ts`: `beforeSend`·`beforeBreadcrumb` 비식별화.
- Modify `inpa_fe/components/__tests__/sitemap.test.tsx`: 새 계약으로 통합.
- Modify `inpa_be/inpa/boards/views.py`, `inpa_be/inpa/boards/tests.py`: noindex 글 제외와 sitemap `no-store` header.

### Task 0: 격리 worktree와 기준선 만들기

- [ ] **Step 1: 공유 폴더 상태와 원격 기준을 확인한다**

Run:

```bash
git status --short --branch
git log --oneline -10
git fetch origin
```

Expected: 공유 폴더의 다른 변경을 확인하고 최신 `origin/master`를 확보한다.

- [ ] **Step 2: 격리 브랜치와 worktree를 만든다**

`superpowers:using-git-worktrees`를 사용한다.

```bash
git worktree add -b codex/inpa-search-ai-safe-indexing /tmp/inpa-search-ai-safe-indexing origin/master
```

Expected: `/tmp/inpa-search-ai-safe-indexing`가 clean 상태다.

- [ ] **Step 3: 승인 문서를 격리 worktree에 복제한다**

`apply_patch`로 spec, index, 세 릴리스 계획을 같은 경로에 추가한 뒤 `cmp`로 원본과 byte equality를 확인한다.

- [ ] **Step 4: 제품 변경 전 기준선을 실행한다**

```bash
cd /tmp/inpa-search-ai-safe-indexing/inpa_fe
npm run test:run -- components/__tests__/sitemap.test.tsx
npm run lint:copy
npm run build
```

Expected: 기존 테스트·copy lint·Next build가 통과한다. 실패하면 `superpowers:systematic-debugging`으로 기존 실패와 환경 실패를 먼저 분리한다.

- [ ] **Step 5: 문서만 첫 커밋한다**

```bash
git add docs/superpowers/specs/2026-08-03-inpa-search-ai-growth-design.md docs/superpowers/plans/2026-08-03-inpa-search-ai-growth-index.md docs/superpowers/plans/2026-08-03-inpa-search-ai-growth-release-1-safe-indexing.md docs/superpowers/plans/2026-08-03-inpa-search-ai-growth-release-2-evidence-hubs.md docs/superpowers/plans/2026-08-03-inpa-search-ai-growth-release-3-resources-measurement.md
git commit -m "docs(검색): 검색·AI 성장 설계와 실행 계획"
```

### Task 1: 색인 정책을 단일 allowlist로 만든다

**Interfaces:**

```ts
export const PUBLIC_INDEX_ROBOTS: Metadata["robots"];
export const CURRENT_INDEXABLE_PATHS: readonly string[];
export const SENSITIVE_CRAWL_PREFIXES: readonly string[];
export type SearchPathClass = "indexable" | "sensitive" | "private_or_utility";
export function classifySearchPath(pathname: string): SearchPathClass;
export function staticSitemapEntries(siteUrl: string): MetadataRoute.Sitemap;
```

- [ ] **Step 1: 실패하는 정책 테스트를 쓴다**

다음을 검증한다.

```ts
expect(rootMetadata.robots).toEqual({ index: false, follow: false });
expect(landingMetadata.robots).toEqual({ index: true, follow: true });
expect(storyMetadata.robots).toEqual({ index: true, follow: true });
expect(faqMetadata.robots).toEqual({ index: true, follow: true });
expect(blogMetadata.robots).toEqual({ index: true, follow: true });
expect(dataPolicyMetadata.robots).toEqual({ index: true, follow: true });
expect((await sitemap()).map((row) => new URL(row.url).pathname)).not.toContain("/legal/terms");
expect(JSON.stringify(robots().rules)).toContain("/s/");
expect(JSON.stringify(robots().rules)).toContain("OAI-SearchBot");
expect(classifySearchPath("/s/secret")).toBe("sensitive");
expect(classifySearchPath("/customers")).toBe("private_or_utility");
```

- [ ] **Step 2: targeted test가 RED인지 확인한다**

```bash
npm run test:run -- components/__tests__/search-policy.test.tsx components/__tests__/sitemap.test.tsx
```

Expected: 루트 noindex, 공개 index, legal sitemap 제거 계약에서 실패한다.

- [ ] **Step 3: `search-policy.ts`와 루트 fail-closed 메타를 구현한다**

`PUBLIC_INDEX_ROBOTS`, 현재 공개 5개 경로, 공개 동적 접두사, robots 차단 접두사, `classifySearchPath`, sitemap 메타를 한 파일에 둔다. exact·segment-boundary로 판정하며 substring은 쓰지 않는다. `app/layout.tsx`의 전역 metadata에 `robots: {index:false, follow:false}`를 추가한다.

- [ ] **Step 4: 공개 페이지만 명시적으로 열고 sitemap을 정렬한다**

5개 공개 페이지에 `PUBLIC_INDEX_ROBOTS`와 canonical을 명시한다. 게시글 상세는 `post.is_noindex`면 `noindex,nofollow`, 아니면 `PUBLIC_INDEX_ROBOTS`를 반환한다. sitemap은 정적 allowlist 뒤에 게시글을 slug 기준으로 중복 제거하여 붙이고 invalid `updated_at`은 생략한다.

- [ ] **Step 5: 정책 테스트를 GREEN으로 만든다**

```bash
npm run test:run -- components/__tests__/search-policy.test.tsx components/__tests__/sitemap.test.tsx
```

- [ ] **Step 6: 색인 정책만 커밋한다**

```bash
git add inpa_fe/lib/search-policy.ts inpa_fe/app/layout.tsx inpa_fe/app/page.tsx inpa_fe/app/story/page.tsx inpa_fe/app/faq/page.tsx inpa_fe/app/blog/page.tsx 'inpa_fe/app/blog/[slug]/page.tsx' inpa_fe/app/data-policy/page.tsx inpa_fe/app/robots.ts inpa_fe/app/sitemap.ts inpa_fe/components/__tests__/search-policy.test.tsx inpa_fe/components/__tests__/sitemap.test.tsx
git commit -m "security(검색): 공개 페이지만 색인하도록 기본값 차단"
```

### Task 2: 게시글 sitemap을 최신 공개 목록으로만 만든다

**Interfaces:**

```ts
export async function getBlogSitemap(): Promise<{ slug: string; updated_at: string }[]>;
```

- [ ] **Step 1: backend와 frontend 실패 테스트를 쓴다**

Backend는 published+indexable 글만 반환하고 draft·`is_noindex=true` 글을 제외해야 한다. Frontend는 중복 slug와 잘못된 날짜를 제거하고, backend 예외 시 동적 글 없이 정적 sitemap 5개만 반환해야 한다. 이전 성공 목록을 유지하는 cache가 없는지도 계약으로 고정한다.

- [ ] **Step 2: RED를 확인한다**

```bash
cd inpa_be
python manage.py test inpa.boards.tests.BlogPublicReadTests
cd ../inpa_fe
npm run test:run -- components/__tests__/sitemap.test.tsx
```

- [ ] **Step 3: backend sitemap 계약을 바로잡는다**

`BlogPostViewSet.sitemap`을 `is_published=True, is_noindex=False`로 제한하고 `Cache-Control: no-store`를 응답에 설정한다. slug와 updated_at만 반환한다.

- [ ] **Step 4: Next sitemap을 요청별 최신 목록으로 구현한다**

설치된 Next 16의 `caching-without-cache-components.md`를 확인하고 `force-dynamic` sitemap에서 `getBlogSitemap`을 요청마다 직접 호출한다. 성공 결과를 별도 cache에 보관하지 않으며, 호출이 실패하면 과거 목록 대신 정적 공개 URL 5개로 즉시 축소한다. 로그에는 URL·응답 본문을 남기지 않는다.

- [ ] **Step 5: 양쪽 테스트를 GREEN으로 만든다**

```bash
cd inpa_be
python manage.py test inpa.boards.tests.BlogPublicReadTests
cd ../inpa_fe
npm run test:run -- components/__tests__/sitemap.test.tsx
```

- [ ] **Step 6: sitemap fail-closed 일관성만 커밋한다**

```bash
git add inpa_be/inpa/boards/views.py inpa_be/inpa/boards/tests.py inpa_fe/lib/blog-sitemap-cache.ts inpa_fe/app/sitemap.ts inpa_fe/components/__tests__/sitemap.test.tsx
git commit -m "security(검색): sitemap을 최신 공개 목록으로 제한"
```

### Task 3: telemetry URL을 전송 전에 비식별화한다

**Interfaces:**

```ts
export function sanitizeTelemetryUrl(raw: string, baseUrl?: string): string;
export function redactSensitiveText(value: string): string;
export function sanitizeAnalyticsEvent<T extends { url: string }>(event: T): T | null;
export function sanitizeSentryEvent(event: Event): Event | null;
export function sanitizeSentryBreadcrumb(breadcrumb: Breadcrumb): Breadcrumb | null;
```

Template examples:

```text
/s/secret-token?customer=kim -> /s/[token]
/customer/482?tab=analysis -> /customer/[id]
/promotion/orders/93 -> /promotion/orders/[id]
/boards/inquiry/71 -> /boards/inquiry/[id]
unknown malformed URL -> /telemetry-redacted
```

Vercel Analytics·Speed Insights는 `classifySearchPath(pathname)==="indexable"`인 이벤트만 비식별화 후 전송한다. `sensitive`와 `private_or_utility`는 `null`을 반환한다. Sentry 오류는 진단 가능성을 위해 event를 유지하되 URL·문자열을 fail-closed로 비식별화한다.

- [ ] **Step 1: canary가 포함된 실패 테스트를 쓴다**

고정 canary `TOPSECRET-CUSTOMER-482`와 `010-9876-5432`를 URL, Sentry request, transaction, exception, breadcrumb에 각각 넣는다. sanitizer 결과 전체를 `JSON.stringify`했을 때 두 canary와 query/hash가 모두 없고 템플릿 경로만 남아야 한다. Vercel event는 `/`, `/faq`, `/blog/public-slug`에서만 남고 `/home`, `/customers`, `/s/TOPSECRET-CUSTOMER-482`에서는 `null`이어야 한다.

- [ ] **Step 2: targeted test가 RED인지 확인한다**

```bash
npm run test:run -- components/__tests__/telemetry-privacy.test.tsx
```

- [ ] **Step 3: 순수 비식별화 함수를 구현한다**

`URL` 파싱 후 origin은 `https://www.inpa.kr`로 고정하고 query/hash를 제거한다. 알려진 token·numeric ID segment를 `[token]`, `[id]`로 치환한다. 문자열 안의 absolute/relative URL, 이메일, 한국 전화번호 패턴도 redaction한다. 파싱·순회 예외는 원문을 반환하지 않는 fail-closed 결과로 끝낸다.

- [ ] **Step 4: Vercel 전역 분석 컴포넌트를 연결한다**

`public-telemetry.tsx`를 client component로 만들고 `<Analytics beforeSend={sanitizeAnalyticsEvent}/>`와 `<SpeedInsights beforeSend={sanitizeAnalyticsEvent}/>`를 렌더한다. `app/layout.tsx`의 직접 import·렌더를 이 컴포넌트 하나로 교체한다.

- [ ] **Step 5: Sentry 공통 옵션을 연결한다**

`SENTRY_BASE_OPTIONS`에 `beforeSend: sanitizeSentryEvent`, `beforeBreadcrumb: sanitizeSentryBreadcrumb`를 추가한다. `sendDefaultPii:false`, replay 없음, `tracesSampleRate:0`은 유지한다.

- [ ] **Step 6: canary 테스트와 전체 FE 테스트를 통과시킨다**

```bash
npm run test:run -- components/__tests__/telemetry-privacy.test.tsx
npm run test:run
```

- [ ] **Step 7: 개인정보 경계만 커밋한다**

```bash
git add inpa_fe/lib/telemetry-privacy.ts inpa_fe/components/public-telemetry.tsx inpa_fe/components/__tests__/telemetry-privacy.test.tsx inpa_fe/app/layout.tsx inpa_fe/lib/sentry-shared.ts
git commit -m "security(분석): 공개 URL의 토큰과 식별자 비식별화"
```

### Task 4: 데이터 처리 안내의 공개 정합성을 바로잡는다

- [ ] **Step 1: stale copy를 잡는 실패 테스트를 추가한다**

렌더 문자열에 `정식 출시 시 게재`, `동의가 없으면 분석 호출 자체가 차단`, `병력` 기능 제공처럼 읽히는 단정이 없고 실제 문의 이메일과 현재 검토형 증권 정리 흐름만 설명하는지 검사한다.

- [ ] **Step 2: 테스트 RED를 확인한다**

```bash
npm run test:run -- components/__tests__/search-policy.test.tsx
```

- [ ] **Step 3: 실제 운영 상태와 맞는 문구로 교정한다**

활성 기능, 기본 비공개 기능, 고객 동의, 외부 AI 전송 가능성, 소유자 전용 접근, 원본 파일 정리, 탈퇴·문의 경로를 사실 범위에서만 쓴다. `hello.fingo.official@gmail.com`을 실제 문의 링크로 제공하고 법적 보증 표현은 제거한다.

- [ ] **Step 4: copy lint와 테스트를 통과시킨다**

```bash
npm run lint:copy
npm run test:run -- components/__tests__/search-policy.test.tsx
```

- [ ] **Step 5: 문구 교정만 커밋한다**

```bash
git add inpa_fe/app/data-policy/page.tsx inpa_fe/components/__tests__/search-policy.test.tsx
git commit -m "fix(안내): 데이터 처리 공개 문구를 운영 상태와 정렬"
```

### Task 5: 전체 검증, 독립 리뷰, PR, 운영 배포

- [ ] **Step 1: 전체 품질 게이트를 새로 실행한다**

```bash
cd /tmp/inpa-search-ai-safe-indexing/inpa_fe
npm run test:run
npm run lint:copy
npm run build
cd ..
git diff --check
git status --short
```

- [ ] **Step 2: 로컬 브라우저로 메타와 민감 라우트를 검수한다**

`browser:control-in-app-browser`를 사용해 `/`, `/faq`, `/blog`, `/data-policy`, `/home`, `/customers`, `/s/TOPSECRET-CUSTOMER-482`를 연다. 공개 페이지만 index, private는 noindex, token route는 noindex이며 화면에 hydration 오류가 없는지 확인한다. DevTools 수준의 전송 payload를 볼 수 없으면 sanitizer canary 단위 테스트를 운영 근거로 명시한다.

- [ ] **Step 3: `superpowers:requesting-code-review`로 독립 검토한다**

정확성, 개인정보, 검색 정책, 장애 폴백, 모바일 UX 관점에서 Critical/Important를 받고 확인된 항목을 수정한다.

- [ ] **Step 4: 최신 master와 차이를 확인하고 PR을 연다**

`github:yeet`를 사용한다. push 직전 `git fetch origin`, `git log --oneline origin/master..HEAD`, `git diff --name-only origin/master...HEAD`를 확인한다. PR 제목은 `security(검색): 공개 색인과 URL 비식별화 강화`로 한다.

- [ ] **Step 5: CI 성공 후 master에 병합해 운영 배포한다**

GitHub Actions의 backend, frontend, gitleaks가 모두 성공한 뒤 병합한다. Vercel과 Render 자동 배포가 새 master SHA를 가리킬 때까지 확인한다.

- [ ] **Step 6: 운영 smoke test와 5분 오류 관찰을 수행한다**

```bash
curl -fsS https://www.inpa.kr/robots.txt
curl -fsS https://www.inpa.kr/sitemap.xml
curl -fsSI https://www.inpa.kr/
curl -fsSI https://www.inpa.kr/home
curl -fsS https://inpa-be.onrender.com/healthz/
```

운영 HTML에서 공개 canonical/index, `/home` noindex, legal·noindex blog sitemap 제외를 확인한다. Sentry 새 오류와 Vercel 배포 오류를 5분간 60초 이하 간격으로 확인한다.

- [ ] **Step 7: 릴리스 증거를 기록한다**

PR, merge SHA, CI run, Vercel deployment, Render deployment, 운영 URL 응답, 남은 미검증 항목을 네 줄 보고 형식으로 남긴다. Release 1이 안정적일 때만 Release 2를 시작한다.
