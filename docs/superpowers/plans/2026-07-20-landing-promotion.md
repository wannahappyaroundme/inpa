# www 랜딩 승격 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 서비스 중심 후보 랜딩을 `www.inpa.kr` 메인으로 승격하고, 기존 4단 요금표와 `/story` 영화형 소개, 이전 주소 영구 이동을 완성한다.

**Architecture:** 메인과 스토리는 각각 `/`와 `/story`의 서버 페이지가 기존 클라이언트 랜딩을 조합한다. 요금표는 `PricingFourTiers` 단일 원본을 재사용하고, `new.inpa.kr`의 두 공개 주소는 Proxy에서 308로 새 공식 주소에 연결한다. 사용자 행동은 기존 UTM과 분석 이벤트를 유지한다.

**Tech Stack:** Next.js 16.2.9 App Router·Proxy, React 19.2.4, TypeScript, Tailwind CSS v4, Node test, Vitest, Vercel Analytics.

## Global Constraints

- rendered copy는 쉬운 한국어, 긍정형, em dash 없음.
- 라이트 서비스 화면만 사용하고 서비스 화면에 `dark:` 변형을 추가하지 않는다.
- 기존 실제 제품 이미지와 개인정보 보호 처리를 바꾸지 않는다.
- 새 패키지, 백엔드, DB, 결제 로직 변경 없음.
- 커밋·푸시·PR·운영 배포는 별도 명시 승인 전 수행하지 않는다.
- Next.js 16의 `proxy.ts`, metadata, redirect 규칙은 설치된 문서를 기준으로 한다.

---

## File Structure

- `inpa_fe/app/page.tsx`: 정식 메인 조합, JSON-LD·로그인 전환·문의 위젯 보존.
- `inpa_fe/app/story/page.tsx`: 영화형 인파 이야기 메타데이터와 화면.
- `inpa_fe/app/new/page.tsx`: www의 `/new` 호환 영구 이동.
- `inpa_fe/app/new/test/page.tsx`: www의 `/new/test` 호환 영구 이동.
- `inpa_fe/components/service-landing.tsx`: 승격된 메인 랜딩 화면과 링크.
- `inpa_fe/components/landing-product-gallery.tsx`: 실제 제품 화면 탭·확대 보기.
- `inpa_fe/lib/landing-content.ts`: 랜딩 문구·제품 데이터·URL 유틸리티.
- `inpa_fe/lib/landing-content.test.ts`: 제품·URL 계약 테스트.
- `inpa_fe/components/brand-story-sections.tsx`: 공용 4단 요금표의 선택적 앵커·가입 주소.
- `inpa_fe/components/cinema-landing.tsx`: www `/story` 기준 링크·UTM.
- `inpa_fe/lib/new-host-routing.ts`: new 도메인 이전 목적지 순수 함수.
- `inpa_fe/lib/new-host-routing.test.ts`: new 도메인 이전 회귀 테스트.
- `inpa_fe/proxy.ts`: new 도메인 308 응답.
- `inpa_fe/package.json`: 이동된 랜딩 테스트 경로.

### Task 1: 이전 주소 규칙을 테스트 우선으로 변경

**Files:**
- Modify: `inpa_fe/lib/new-host-routing.test.ts`
- Modify: `inpa_fe/lib/new-host-routing.ts`
- Modify: `inpa_fe/proxy.ts`

**Interfaces:**
- Produces: `resolveNewHostRoute(pathname: string, search: string): { kind: "main-redirect"; target: string }`
- Produces: new host 응답 상태 308.

- [x] **Step 1: 실패 테스트 작성**

`new-host-routing.test.ts`를 아래 계약으로 바꾼다.

```ts
test("new host의 운영 랜딩은 www 이야기로 영구 이전한다", () => {
  assert.deepEqual(resolveNewHostRoute("/", "?utm_source=old"), {
    kind: "main-redirect",
    target: "https://www.inpa.kr/story?utm_source=old",
  });
});

test("new host의 test 후보는 www 메인으로 영구 이전한다", () => {
  assert.deepEqual(resolveNewHostRoute("/test", "?utm_source=old"), {
    kind: "main-redirect",
    target: "https://www.inpa.kr/?utm_source=old",
  });
});

test("과거 내부 랜딩 주소도 같은 공식 주소로 이전한다", () => {
  assert.deepEqual(resolveNewHostRoute("/new", ""), {
    kind: "main-redirect",
    target: "https://www.inpa.kr/story",
  });
  assert.deepEqual(resolveNewHostRoute("/new/test", ""), {
    kind: "main-redirect",
    target: "https://www.inpa.kr/",
  });
});
```

- [x] **Step 2: RED 확인**

Run: `cd inpa_fe && npm run test:landing`
Expected: 기존 함수가 `rewrite` 또는 `local-redirect`를 반환해 FAIL.

- [x] **Step 3: 최소 구현**

```ts
export const MAIN_ORIGIN = "https://www.inpa.kr";

export type NewHostRoute = { kind: "main-redirect"; target: string };

export function resolveNewHostRoute(pathname: string, search: string): NewHostRoute {
  if (pathname === "/" || pathname === "/new") {
    return { kind: "main-redirect", target: `${MAIN_ORIGIN}/story${search}` };
  }
  if (pathname === "/test" || pathname === "/new/test") {
    return { kind: "main-redirect", target: `${MAIN_ORIGIN}/${search}` };
  }
  return { kind: "main-redirect", target: `${MAIN_ORIGIN}${pathname}${search}` };
}
```

`proxy.ts`는 `resolveNewHostRoute`의 target을 `NextResponse.redirect(route.target, 308)`로 반환한다.

- [x] **Step 4: GREEN 확인**

Run: `cd inpa_fe && npm run test:landing`
Expected: 주소 테스트 포함 전체 PASS.

### Task 2: 후보 랜딩 소스 이름을 정식 이름으로 승격

**Files:**
- Move: `inpa_fe/lib/test-landing-content.ts` → `inpa_fe/lib/landing-content.ts`
- Move: `inpa_fe/lib/test-landing-content.test.ts` → `inpa_fe/lib/landing-content.test.ts`
- Move: `inpa_fe/components/test-product-gallery.tsx` → `inpa_fe/components/landing-product-gallery.tsx`
- Move: `inpa_fe/components/test-landing.tsx` → `inpa_fe/components/service-landing.tsx`
- Modify: `inpa_fe/package.json`

**Interfaces:**
- Produces: `ServiceLanding`, `LandingProductGallery`.
- Preserves: `PRODUCT_SCREENS`, `buildServiceUrl`, 키보드·확대 계약과 `landing_test_*` 분석 이벤트.

- [x] **Step 1: 테스트 import와 명령을 먼저 새 경로로 변경**

`landing-content.test.ts`의 import를 `./landing-content`로, `package.json`의 `test:landing` 입력·출력 경로를 `landing-content.ts`, `landing-content.test.ts`, `landing-content.test.js`로 바꾼다.

- [x] **Step 2: RED 확인**

Run: `cd inpa_fe && npm run test:landing`
Expected: 새 `landing-content.ts`가 없어 컴파일 FAIL.

- [x] **Step 3: 파일 이동과 export 이름 변경**

- `TestLanding` → `ServiceLanding`
- `TestProductGallery` → `LandingProductGallery`
- 모든 import를 `@/lib/landing-content`, `@/components/landing-product-gallery`로 변경
- 분석 이벤트와 DOM id는 기존 데이터 연속성과 접근성 회귀 방지를 위해 유지

- [x] **Step 4: GREEN 확인**

Run: `cd inpa_fe && npm run test:landing`
Expected: 전체 PASS.

### Task 3: 4단 요금표를 메인 랜딩에 공용 삽입

**Files:**
- Modify: `inpa_fe/components/brand-story-sections.tsx`
- Modify: `inpa_fe/components/service-landing.tsx`
- Modify: `inpa_fe/lib/landing-content.test.ts`
- Create: `inpa_fe/components/pricing-four-tiers.test.tsx`

**Interfaces:**
- Produces: `PricingFourTiers({ id?, registerHref? })`.
- Consumes: 메인 랜딩의 UTM 보존 `registerUrl`.

- [x] **Step 1: 실패 계약 테스트 추가**

`pricing-four-tiers.test.tsx`에서 API를 고정 응답으로 대체한 뒤 공용 요금표 자체를 렌더한다.

```tsx
vi.mock("@/lib/api", () => ({
  getBillingEvent: vi.fn().mockResolvedValue({ first_paid_bonus_enabled: false }),
}));

test("공용 4단 요금표는 앵커와 UTM 가입 주소를 받는다", () => {
  render(
    <PricingFourTiers
      id="pricing"
      registerHref="https://www.inpa.kr/register?utm_source=nav"
    />,
  );

  expect(document.querySelector("#pricing")).toBeInTheDocument();
  expect(screen.getByText("Manager")).toBeInTheDocument();
  expect(screen.getByText("Plus")).toBeInTheDocument();
  expect(screen.getByText("Super")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "무료로 시작하기" })).toHaveAttribute(
    "href",
    "https://www.inpa.kr/register?utm_source=nav",
  );
});
```

- [x] **Step 2: RED 확인**

Run: `cd inpa_fe && npm run test:run`
Expected: 기존 베타 안내만 렌더되어 4단 요금표 제목을 찾지 못해 FAIL.

- [x] **Step 3: 최소 구현**

기존 `PricingFourTiers` 본문은 바꾸지 않고 아래 세 줄만 확장한다.

```diff
-export function PricingFourTiers() {
+export function PricingFourTiers({
+  id,
+  registerHref = "/register",
+}: {
+  id?: string;
+  registerHref?: string;
+} = {}) {
```

기존 section 시작 태그는 정확히 다음으로 바꾼다.

```tsx
<section id={id} className="scroll-mt-20 py-20 md:py-28 bg-[var(--surface)]">
```

기존 마지막 가입 링크의 `href="/register"`만 `href={registerHref}`로 바꾼다.

`service-landing.tsx`의 기존 어두운 베타 안내 섹션을 다음으로 교체한다.

```tsx
<div onClickCapture={() => landingTrack("landing_test_cta", { position: "pricing", action: "register" })}>
  <PricingFourTiers id="pricing" registerHref={registerUrl} />
</div>
```

실제 click capture는 등록 링크에서만 발생하도록 `closest("a")`의 href를 확인한다.

- [x] **Step 4: GREEN 확인**

Run: `cd inpa_fe && npm run test:run`
Expected: 새 요금표 렌더 테스트와 기존 화면 테스트 PASS.

### Task 4: 메인·스토리·호환 주소 페이지 조합

**Files:**
- Modify: `inpa_fe/app/page.tsx`
- Create: `inpa_fe/app/story/page.tsx`
- Modify: `inpa_fe/app/new/page.tsx`
- Modify: `inpa_fe/app/new/test/page.tsx`
- Modify: `inpa_fe/components/service-landing.tsx`
- Modify: `inpa_fe/components/cinema-landing.tsx`

**Interfaces:**
- `/` renders `ServiceLanding` + `JsonLd` + `LandingClient` + `FeedbackWidget anonymous`.
- `/story` renders `CinemaLanding` with canonical `/story`.
- `/new`, `/new/test` call Next 16 `permanentRedirect`.

- [x] **Step 1: 실패 화면 테스트 추가**

Vitest + Testing Library로 다음을 확인한다.

```tsx
expect(screen.getByRole("link", { name: "인파 이야기 60초 보기" })).toHaveAttribute("href", "/story");
expect(screen.getByRole("link", { name: "인파 노트" })).toHaveAttribute("href", "/blog");
expect(screen.getByRole("link", { name: "문의" })).toHaveAttribute("href", "mailto:hello.fingo.official@gmail.com");
```

- [x] **Step 2: RED 확인**

Run: `cd inpa_fe && npm run test:run`
Expected: 이야기 링크가 `/`, 헤더 블로그와 푸터 문의 링크가 없어 FAIL.

- [x] **Step 3: 메인 페이지 조합**

```tsx
export default function LandingPage() {
  return (
    <>
      <JsonLd data={[ORGANIZATION, WEBSITE, SOFTWARE_APP]} />
      <LandingClient />
      <ServiceLanding />
      <FeedbackWidget anonymous />
    </>
  );
}
```

- [x] **Step 4: 스토리와 이전 경로 구현**

`app/story/page.tsx`는 영화용 title·description·canonical `/story`와 `<CinemaLanding />`을 제공한다. `app/new/page.tsx`는 `permanentRedirect("/story")`, `app/new/test/page.tsx`는 `permanentRedirect("/")`를 호출한다.

- [x] **Step 5: 링크 보존 구현**

- 첫 화면 이야기 링크: `/story`
- 헤더·모바일 메뉴: `/blog`의 `인파 노트`
- 푸터: `/blog`, `/faq`, `/legal/terms`, `/legal/privacy`, `/data-policy`, `mailto:hello.fingo.official@gmail.com`
- 루트: 기존 익명 문의 위젯 유지
- CinemaLanding: www 내부 링크와 story 기준 UTM을 사용

- [x] **Step 6: GREEN 확인**

Run: `cd inpa_fe && npm run test:run && npm run test:landing`
Expected: 전체 PASS.

### Task 5: 회귀·시각·문서 검증

**Files:**
- Modify only if verification finds a scoped defect.

- [x] **Step 1: 자동검사**

Run individually:

```bash
cd inpa_fe
npm run test:landing
npm run test:unit
npm run test:run
npm run lint:copy
npm run build
```

Expected: 주소 0 fail, 단위검사 0 fail, Vitest 0 fail, 문구 위반 0, Next build 성공.

- [x] **Step 2: 로컬 운영 서버 주소 검사**

Run: `npm start` after build.

Expected:

- www host `/`: 200, 서비스 중심 랜딩
- www host `/story`: 200, 영화 게이트
- www host `/new`: `/story` 영구 이동
- www host `/new/test`: `/` 영구 이동
- new host `/`: `https://www.inpa.kr/story` 308
- new host `/test`: `https://www.inpa.kr/` 308
- 검색값 보존

- [x] **Step 3: 브라우저 시각·동작 검사**

390px, 768px, 1440px에서 다음을 실제 확인한다.

- 첫 화면 CTA와 실제 대시보드
- 모바일 메뉴
- 제품 탭 5개, 키보드 화살표, 확대, ESC, 포커스 복귀
- 4단 요금 카드와 `#pricing`
- 이야기, 블로그, 문의, FAQ, 로그인, 가입, 정책 링크
- 문의 위젯
- 가로 넘침 0, 콘솔 오류 0

- [x] **Step 4: 최종 다각도 검토**

정확성, 접근성, 모바일, 검색/canonical, UTM·분석, 주소 이전, 문구 정직성, 기존 서비스 링크 회귀를 검토한다. 발견 사항은 구현 범위 안에서 수정하고 자동·브라우저 검사를 다시 실행한다.

- [x] **Step 5: Git·배포 상태 보고**

변경 파일과 검증 결과를 `Changed / Verified by / Result / Unverified` 형식으로 보고한다. 커밋·푸시·PR·운영 배포는 사용자 승인 전 수행하지 않는다.
