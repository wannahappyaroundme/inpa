# new.inpa.kr/test 서비스 중심 랜딩 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 운영 랜딩을 바꾸지 않고 `https://new.inpa.kr/test`에 실제 인파 서비스 화면이 크게 보이는 최종 후보 랜딩을 구현하고 운영 배포까지 검증한다.

**Architecture:** `new.inpa.kr/test`만 Next 내부 라우트 `/new/test`로 rewrite하고, 페이지 전용 서버 컴포넌트와 클라이언트 랜딩 컴포넌트를 분리한다. 화면·카피 데이터는 한 모듈에서 관리하고, 실제 운영 데모 계정으로 촬영한 비식별 이미지 5장을 정적 자산으로 제공한다. 기존 `new.inpa.kr/`, `www.inpa.kr/`, 백엔드, 인증 설정은 건드리지 않는다.

**Tech Stack:** Next.js 16.2.9 App Router/Proxy, React 19, TypeScript, Tailwind CSS v4, `next/image`, lucide-react, Vercel Analytics, Node 24 내장 테스트 러너, Vercel + Render 운영 환경

## Global Constraints

- 설계 SSOT: `docs/superpowers/specs/2026-07-16-new-landing-test-design.md`
- 격리 작업공간: `/Users/kyungsbook/Desktop/inpa/.worktrees/new-landing-test`
- 작업 브랜치: `codex/new-landing-test`
- `new.inpa.kr/` 영화 랜딩과 `www.inpa.kr/` 운영 랜딩은 불변이다.
- 로그인·가입은 각각 `https://www.inpa.kr/login`, `https://www.inpa.kr/register`로 연결한다.
- 실제 운영 데모 데이터만 촬영하며 계정 비밀번호, 고객 개인정보, 공유 토큰, localhost 주소는 이미지·소스·커밋에 남기지 않는다.
- 렌더 카피는 쉬운 말, 긍정 표현, 근거 있는 사실만 사용하고 em dash를 쓰지 않는다.
- 새 패키지, DB/API 변경, CORS/CSRF/OAuth/이메일 환경변수 변경은 없다.
- 완료 선언 전 `superpowers:verification-before-completion`을 사용한다.
- `npm`, `node`, 로컬 서버 명령은 `/Users/kyungsbook/Desktop/inpa/.worktrees/new-landing-test/inpa_fe`에서, `git` 명령은 `/Users/kyungsbook/Desktop/inpa/.worktrees/new-landing-test`에서 실행한다.

---

## Task 1: 테스트 경로 계약을 먼저 고정한다

**Files:**
- Create: `inpa_fe/lib/new-host-routing.ts`
- Create: `inpa_fe/lib/new-host-routing.test.ts`
- Modify: `inpa_fe/proxy.ts`
- Modify: `inpa_fe/package.json`
- Create: `inpa_fe/app/new/test/page.tsx`

- [ ] **Step 1: Next 16의 Proxy와 메타데이터 규칙을 현재 설치본에서 확인한다.**

Run:

```bash
sed -n '1,180p' node_modules/next/dist/docs/01-app/01-getting-started/16-proxy.md
sed -n '540,590p' node_modules/next/dist/docs/01-app/03-api-reference/04-functions/generate-metadata.md
```

Expected: `proxy.ts`의 rewrite/redirect 방식과 `Metadata.robots` 형식을 확인한다.

- [ ] **Step 2: 기존 경로와 새 경로를 모두 명시한 실패 테스트를 작성한다.**

`lib/new-host-routing.test.ts`의 핵심 계약:

```ts
import assert from "node:assert/strict";
import test from "node:test";
import { resolveNewHostRoute } from "./new-host-routing.ts";

test("new host의 운영 랜딩과 test 후보를 내부 라우트로 보낸다", () => {
  assert.deepEqual(resolveNewHostRoute("/", ""), { kind: "rewrite", target: "/new" });
  assert.deepEqual(resolveNewHostRoute("/test", ""), { kind: "rewrite", target: "/new/test" });
});

test("내부 주소는 공개 주소로 정규화한다", () => {
  assert.deepEqual(resolveNewHostRoute("/new", ""), { kind: "local-redirect", target: "/" });
  assert.deepEqual(resolveNewHostRoute("/new/test", ""), { kind: "local-redirect", target: "/test" });
});

test("그 밖의 서비스 경로와 검색값은 www로 보낸다", () => {
  assert.deepEqual(resolveNewHostRoute("/login", "?utm_source=nav"), {
    kind: "main-redirect",
    target: "https://www.inpa.kr/login?utm_source=nav",
  });
});
```

`package.json`에 우선 추가:

```json
"test:landing": "node --test lib/new-host-routing.test.ts"
```

Run: `npm run test:landing`

Expected: `ERR_MODULE_NOT_FOUND` 또는 `resolveNewHostRoute` 미정의로 FAIL.

- [ ] **Step 3: 경로 판단을 순수 함수로 만들고 Proxy에 연결한다.**

`lib/new-host-routing.ts`의 형태:

```ts
export const MAIN_ORIGIN = "https://www.inpa.kr";

export type NewHostRoute =
  | { kind: "rewrite"; target: "/new" | "/new/test" }
  | { kind: "local-redirect"; target: "/" | "/test" }
  | { kind: "main-redirect"; target: string };

export function resolveNewHostRoute(pathname: string, search: string): NewHostRoute {
  if (pathname === "/") return { kind: "rewrite", target: "/new" };
  if (pathname === "/test") return { kind: "rewrite", target: "/new/test" };
  if (pathname === "/new") return { kind: "local-redirect", target: "/" };
  if (pathname === "/new/test") return { kind: "local-redirect", target: "/test" };
  return { kind: "main-redirect", target: `${MAIN_ORIGIN}${pathname}${search}` };
}
```

`proxy.ts`는 host 판별 뒤 이 결과만 `NextResponse.rewrite` 또는 `NextResponse.redirect`로 변환한다. 기존 matcher는 유지한다.

- [ ] **Step 4: noindex 서버 페이지를 만든다.**

`app/new/test/page.tsx`:

```tsx
import type { Metadata } from "next";
import { TestLanding } from "@/components/test-landing";

export const metadata: Metadata = {
  title: { absolute: "인파 실제 서비스 둘러보기" },
  description: "고객 관리부터 보장분석, 일정, 성과까지 이어지는 인파의 실제 화면을 확인해보세요.",
  alternates: { canonical: "https://new.inpa.kr/test" },
  robots: { index: false, follow: false },
};

export default function NewLandingTestPage() {
  return <TestLanding />;
}
```

이 단계에서는 `components/test-landing.tsx`에 최소한의 임시 export만 만들어 경로 빌드가 가능하게 한다. 사용자에게 보이는 임시 문구는 다음 작업에서 즉시 교체하며 이 상태로 배포하지 않는다.

- [ ] **Step 5: 경로 테스트와 빌드를 통과시킨다.**

Run:

```bash
npm run test:landing
npm run build
```

Expected: 경로 테스트 전부 PASS, Next 빌드 성공, route 목록에 `○ /new/test` 표시.

- [ ] **Step 6: 경로 단위만 커밋한다.**

```bash
git add inpa_fe/lib/new-host-routing.ts inpa_fe/lib/new-host-routing.test.ts inpa_fe/proxy.ts inpa_fe/package.json inpa_fe/app/new/test/page.tsx inpa_fe/components/test-landing.tsx
git commit -m "feat(랜딩): new test 경로 분리"
```

---

## Task 2: 실제 데모 서비스 화면 5장을 안전하게 준비한다

**Files:**
- Create: `inpa_fe/public/landing-test/dashboard.webp`
- Create: `inpa_fe/public/landing-test/customers.webp`
- Create: `inpa_fe/public/landing-test/coverage.webp`
- Create: `inpa_fe/public/landing-test/compare.webp`
- Create: `inpa_fe/public/landing-test/schedule.webp`

- [ ] **Step 1: 인앱 브라우저의 기존 로그인 세션으로 `[DEMO]` 계정인지 확인한다.**

화면에서 이름·소속에 `[DEMO]` 표시가 있는지 확인한다. 세션이 풀렸을 때만 이미 검증된 데모 계정으로 다시 로그인하며, 자격증명은 소스·명령 기록·문서에 적지 않는다.

- [ ] **Step 2: 각 화면에서 촬영 전 개인정보와 주소를 점검한다.**

촬영 대상:

1. 대시보드 `/home`
2. 고객관리 `/customers`
3. 보장분석, 데모 고객의 분석 탭
4. 비교분석, 데모 고객의 비교 탭
5. 일정 `/schedule`

각 페이지의 최신 DOM snapshot과 화면을 확인하고, 실제 고객 연락처·공유 링크·살아 있는 토큰·`localhost` 문자열이 한 건이라도 있으면 촬영하지 않는다.

- [ ] **Step 3: 같은 데스크톱 뷰포트로 PNG 원본을 저장한다.**

인앱 브라우저를 1440×1000으로 맞춘 뒤 본문 핵심 영역을 촬영한다. 브라우저 스크린샷 bytes를 Node 작업공간의 `/tmp/inpa-landing-capture/`에 저장한다. 페이지별 캡처 직후 직접 열어 제목·숫자·상태가 읽히는지 확인한다.

- [ ] **Step 4: 여백과 위험 영역을 잘라 WebP로 변환한다.**

예시 명령:

```bash
mkdir -p public/landing-test
cwebp -quiet -q 86 /tmp/inpa-landing-capture/dashboard.png -o public/landing-test/dashboard.webp
cwebp -quiet -q 86 /tmp/inpa-landing-capture/customers.png -o public/landing-test/customers.webp
cwebp -quiet -q 86 /tmp/inpa-landing-capture/coverage.png -o public/landing-test/coverage.webp
cwebp -quiet -q 86 /tmp/inpa-landing-capture/compare.png -o public/landing-test/compare.webp
cwebp -quiet -q 86 /tmp/inpa-landing-capture/schedule.png -o public/landing-test/schedule.webp
```

필요한 crop은 `magick input.png -crop WIDTHxHEIGHT+X+Y +repage output.png`로 수행한다. 모든 결과는 최소 너비 1,200px, 동일한 16:10 또는 화면에 맞는 안정된 비율을 사용한다.

- [ ] **Step 5: 이미지 품질과 민감정보를 사람 눈으로 재검수한다.**

Run:

```bash
file public/landing-test/*.webp
du -h public/landing-test/*.webp
```

Expected: 5개 모두 WebP, 최소 1,200px 너비, 이미지당 약 500KB 이하. `view_image`로 5장을 원본 크기로 열어 `[DEMO]` 외 개인정보, 토큰, localhost, 잘린 핵심 문구가 없음을 확인한다.

- [ ] **Step 6: 이미지 자산만 커밋한다.**

```bash
git add inpa_fe/public/landing-test/dashboard.webp inpa_fe/public/landing-test/customers.webp inpa_fe/public/landing-test/coverage.webp inpa_fe/public/landing-test/compare.webp inpa_fe/public/landing-test/schedule.webp
git commit -m "chore(랜딩): 실제 데모 화면 자산 추가"
```

---

## Task 3: 랜딩 콘텐츠 계약과 정적 섹션을 구현한다

**Files:**
- Create: `inpa_fe/lib/test-landing-content.ts`
- Create: `inpa_fe/lib/test-landing-content.test.ts`
- Modify: `inpa_fe/components/test-landing.tsx`
- Reuse: `inpa_fe/components/inpa-logo.tsx`

- [ ] **Step 1: 콘텐츠 구조에 대한 실패 테스트를 작성한다.**

`lib/test-landing-content.test.ts`의 핵심:

```ts
import assert from "node:assert/strict";
import test from "node:test";
import {
  FACTS,
  PRODUCT_SCREENS,
  WORKFLOW_STEPS,
  buildServiceUrl,
} from "./test-landing-content.ts";

test("제품 증거는 실제 화면 5개를 순서대로 제공한다", () => {
  assert.deepEqual(PRODUCT_SCREENS.map(({ id }) => id), [
    "dashboard", "customers", "coverage", "compare", "schedule",
  ]);
});

test("핵심 사실과 사용 흐름 수를 고정한다", () => {
  assert.equal(FACTS.length, 3);
  assert.equal(WORKFLOW_STEPS.length, 4);
});

test("서비스 링크에 원래 UTM을 보존한다", () => {
  assert.equal(
    buildServiceUrl("/register", "?utm_source=nav&utm_campaign=test"),
    "https://www.inpa.kr/register?utm_source=nav&utm_campaign=test",
  );
});
```

테스트 파일을 만든 뒤 `package.json`의 명령을 다음처럼 확장한다.

```json
"test:landing": "node --test lib/new-host-routing.test.ts lib/test-landing-content.test.ts"
```

Run: `npm run test:landing`

Expected: `test-landing-content.ts` 미정의로 FAIL.

- [ ] **Step 2: 콘텐츠와 링크 생성 함수를 한 모듈에 구현한다.**

`PRODUCT_SCREENS` 각 항목은 `id`, `label`, `title`, `description`, `image`, `imageAlt`, `highlights`를 가진다. 카피 기준:

- hero 보조 문구: `내 손안의 인슈어 파트너`
- hero 제목: `설계사님은 클로징만 준비하세요`
- 사실: `100개 이상 담보를 같은 틀로`, `증권 한 장 자동 정리`, `설계사님이 정한 기준 적용`
- 흐름: `고객과 증권 등록`, `보장 자동 정리`, `현재와 제안 비교`, `고객 안내와 다음 일정 관리`
- CTA: `무료로 시작하기`, `로그인`, `인파 이야기 60초 보기`

`buildServiceUrl`은 `utm_`으로 시작하는 검색값만 복사하고 기존 유입값을 덮어쓰지 않는다. 브라우저가 없을 때는 검색값 없이 정상 URL을 반환한다.

- [ ] **Step 3: 헤더·hero·사실 정보·사용 흐름을 구현한다.**

`TestLanding`은 전용 라이트 페이지로 다음 순서를 가진다.

1. 고정 헤더와 모바일 메뉴
2. hero 카피 + 실제 대시보드 이미지
3. 빠른 사실 3개
4. 실제 제품 둘러보기 자리
5. 4단계 사용 흐름
6. 차별점 2개
7. 개인 설계사·관리직 대상 카드
8. 요금·FAQ·역할 안내
9. 마지막 CTA와 푸터

기존 `InpaMark`, 색상 토큰, 버튼 언어를 재사용한다. 실제 운영 설정과 다른 가격·한도·통계를 새로 만들지 않는다. 가격 숫자가 확정되어 있지 않으면 `베타 기간에는 핵심 기능을 부담 없이 확인할 수 있어요`처럼 현재 사용 가능한 상태만 설명한다.

- [ ] **Step 4: 섹션별 CTA에 위치값을 붙여 계측한다.**

```ts
function landingTrack(name: string, data?: Record<string, string>) {
  try { track(name, data); } catch { /* 계측 실패는 화면을 막지 않음 */ }
}
```

이벤트:

- `landing_test_cta` `{ position: "header" | "hero" | "pricing" | "footer", action: "register" | "login" }`
- `landing_test_brand_story`

- [ ] **Step 5: 콘텐츠 테스트·카피 가드·빌드를 통과시킨다.**

Run:

```bash
npm run test:landing
npm run lint:copy
npm run build
```

Expected: 모든 테스트 PASS, 금지 표기 0, Next 빌드 성공.

- [ ] **Step 6: 정적 랜딩 구조를 커밋한다.**

```bash
git add inpa_fe/lib/test-landing-content.ts inpa_fe/lib/test-landing-content.test.ts inpa_fe/components/test-landing.tsx
git commit -m "feat(랜딩): 서비스 중심 후보 구조 구현"
```

---

## Task 4: 실제 화면 탭과 접근 가능한 확대 보기를 구현한다

**Files:**
- Create: `inpa_fe/components/test-product-gallery.tsx`
- Modify: `inpa_fe/components/test-landing.tsx`
- Modify: `inpa_fe/lib/test-landing-content.ts`

- [ ] **Step 1: 상호작용의 상태 계약을 작성하고 테스트한다.**

콘텐츠 테스트에 다음을 추가한다.

```ts
test("각 제품 화면은 이미지와 2~3개 강조점을 가진다", () => {
  for (const screen of PRODUCT_SCREENS) {
    assert.match(screen.image, /^\/landing-test\/.+\.webp$/);
    assert.ok(screen.highlights.length >= 2 && screen.highlights.length <= 3);
  }
});
```

Run: `npm run test:landing`

Expected: 아직 완성되지 않은 항목이 있으면 FAIL.

- [ ] **Step 2: WAI-ARIA 탭 패턴으로 화면 전환을 구현한다.**

`TestProductGallery` 요구사항:

- `role="tablist"`, 각 버튼 `role="tab"`, `aria-selected`, `aria-controls`
- 선택된 화면만 큰 `next/image`로 렌더
- 왼쪽·오른쪽 화살표로 탭 이동, Enter/Space로 선택
- 모바일에서는 가로로 잘리는 전체 화면 대신 이미지 컨테이너를 좌측 핵심 영역에 맞추고, 화면 이름·설명은 별도로 읽히게 표시
- 탭 선택 시 `landing_test_product_tab` `{ screen: id }` 계측
- 이미지 로딩 전후 같은 aspect-ratio를 유지하고 실패해도 설명·CTA는 남김

- [ ] **Step 3: 포커스가 갇히고 복귀하는 확대 보기를 구현한다.**

요구사항:

- 확대 버튼에 명확한 accessible name 제공
- 열릴 때 확대 닫기 버튼으로 포커스 이동
- Tab/Shift+Tab이 모달 내부에서 순환
- ESC와 배경 클릭, 닫기 버튼으로 종료
- 종료 후 원래 확대 버튼으로 포커스 복귀
- 모달 열린 동안 body 스크롤 잠금과 해제
- `role="dialog"`, `aria-modal="true"`, 화면 제목 연결
- 열 때 `landing_test_product_zoom` `{ screen: id }` 계측

- [ ] **Step 4: 대시보드 hero와 제품 탭을 같은 데이터에서 연결한다.**

hero는 `PRODUCT_SCREENS[0]`의 실제 대시보드 이미지를 재사용하되 첫 화면 가시성 때문에 `priority`로 로드한다. 나머지 4장은 lazy loading을 유지한다.

- [ ] **Step 5: 테스트·카피·빌드를 통과시킨다.**

Run:

```bash
npm run test:landing
npm run lint:copy
npm run build
```

Expected: 테스트 PASS, 금지 표기 0, TypeScript 오류 0.

- [ ] **Step 6: 제품 갤러리를 커밋한다.**

```bash
git add inpa_fe/components/test-product-gallery.tsx inpa_fe/components/test-landing.tsx inpa_fe/lib/test-landing-content.ts inpa_fe/lib/test-landing-content.test.ts
git commit -m "feat(랜딩): 실제 화면 탭과 확대 보기 추가"
```

---

## Task 5: 반응형·접근성·시각 완성도를 실제 브라우저에서 다듬는다

**Files:**
- Modify: `inpa_fe/components/test-landing.tsx`
- Modify: `inpa_fe/components/test-product-gallery.tsx`
- Modify only if shared utility is necessary: `inpa_fe/app/globals.css`

- [ ] **Step 1: 로컬 운영 모드로 페이지를 띄운다.**

Run:

```bash
npm run dev
```

Expected: `http://localhost:3000/new/test`가 200으로 렌더되고 콘솔 오류가 없다.

- [ ] **Step 2: 1440px 데스크톱 화면을 검수하고 조정한다.**

확인:

- 첫 화면에 제목, 설명, `무료로 시작하기`, 실제 대시보드가 동시에 보임
- 제품 화면의 핵심 글자가 확대 없이도 구분됨
- 섹션 사이 간격과 제목 길이가 일정함
- 헤더 anchor가 올바른 섹션으로 이동함
- 최대 콘텐츠 너비가 1,200px 안에서 안정적임

- [ ] **Step 3: 768px 태블릿과 390px 모바일을 검수하고 조정한다.**

확인:

- 가로 넘침 0
- 모바일 메뉴 열기·닫기·anchor 이동 가능
- hero CTA가 손가락으로 누르기 쉬운 44px 이상 높이
- 제품 탭이 잘리지 않고 현재 선택 상태가 보임
- 실제 화면은 읽을 수 있는 crop과 별도 설명을 제공
- 4단계 사용 흐름이 가로 스크롤 없이 2×2 또는 세로 구조로 보임
- 고정 헤더가 제목과 포커스를 가리지 않음

- [ ] **Step 4: 키보드와 움직임 줄이기를 검수한다.**

확인:

- Tab 순서가 시각 순서와 같음
- 모든 링크·버튼에 보이는 focus ring이 있음
- 제품 탭 화살표 이동 작동
- 확대 열기 → 포커스 내부 유지 → ESC → 원래 버튼 복귀
- `prefers-reduced-motion: reduce`에서 등장·스크롤 효과를 생략
- 색상만으로 상태를 설명하지 않음

- [ ] **Step 5: 링크·검색 차단·오류 상태를 확인한다.**

확인:

- 가입·로그인·브랜드 이야기 링크가 정확함
- URL의 기존 `utm_source`, `utm_medium`, `utm_campaign`이 www CTA에 보존됨
- `<meta name="robots" content="noindex, nofollow">` 존재
- 이미지 로딩/실패 시 레이아웃 이동과 빈 카드가 없음
- 콘솔 error 0, hydration warning 0

- [ ] **Step 6: 자동 검증을 다시 실행하고 시각 보정만 커밋한다.**

Run:

```bash
npm run test:landing
npm run lint:copy
npm run build
```

Expected: 모두 exit 0.

```bash
git add inpa_fe/components/test-landing.tsx inpa_fe/components/test-product-gallery.tsx inpa_fe/app/globals.css
git commit -m "fix(랜딩): 반응형과 접근성 완성도 보정"
```

`globals.css`를 바꾸지 않았다면 해당 파일은 stage하지 않는다.

---

## Task 6: 회귀 검증과 독립 코드리뷰를 마친다

**Files:**
- Review: Task 1~5에서 변경한 모든 파일
- Update if findings require: 해당 변경 파일

- [ ] **Step 1: 변경 범위와 비밀정보를 점검한다.**

Run:

```bash
git status --short
git diff origin/master...HEAD --stat
git diff origin/master...HEAD -- inpa_fe
rg -n "demoPass|localhost|88%|30분|40분|Claude AI|—|준비 중" inpa_fe/app/new/test inpa_fe/components/test-* inpa_fe/lib/test-* inpa_fe/public/landing-test || true
```

Expected: 요청 범위 파일만 변경, 자격증명·로컬 주소·금지 카피 0건.

- [ ] **Step 2: 전체 프론트엔드 게이트를 새로 실행한다.**

Run:

```bash
npm run test:landing
npm run lint:copy
npm run build
```

Expected: 테스트 PASS, 카피 가드 PASS, Next 빌드 PASS.

- [ ] **Step 3: 로컬 host 라우팅을 실제 HTTP로 검증한다.**

빌드 후 서버를 띄우고:

```bash
curl -sS -D - -o /tmp/new-test.html -H 'Host: new.inpa.kr' http://127.0.0.1:3000/test
curl -sS -D - -o /dev/null -H 'Host: new.inpa.kr' http://127.0.0.1:3000/new/test
curl -sS -D - -o /tmp/new-root.html -H 'Host: new.inpa.kr' http://127.0.0.1:3000/
curl -sS -D - -o /tmp/www-root.html -H 'Host: www.inpa.kr' http://127.0.0.1:3000/
```

Expected:

- `/test`: 200, 내부 `/new/test` 내용
- `/new/test`: `/test`로 redirect
- new `/`: 기존 영화 랜딩 내용
- www `/`: 기존 운영 랜딩 내용

- [ ] **Step 4: 별도 리뷰를 요청한다.**

`superpowers:requesting-code-review`를 사용해 다음 관점으로 검토한다.

- 라우팅 회귀와 canonical/noindex
- 실제 화면의 개인정보·정직한 카피
- 키보드·모달·모바일 UX
- UTM 보존과 계측 실패 격리
- 이미지 크기와 첫 화면 성능

확인된 문제는 수정하고 Task 6 Step 2~3을 다시 실행한다. 기각한 의견은 이유를 기록한다.

- [ ] **Step 5: 검증 보정 커밋이 필요하면 별도로 만든다.**

```bash
git status --short
# 위 출력에서 Task 6 리뷰로 실제 수정한 파일 경로만 하나씩 git add 한다.
git commit -m "fix(랜딩): 배포 전 검증 결과 반영"
```

---

## Task 7: PR을 병합하고 운영 URL을 배포·확인한다

**Files:**
- No product file expected unless deployment verification finds a confirmed defect
- Update after successful merge and deploy: `README.md`, `AGENTS.md`

- [ ] **Step 1: 원격 최신 상태와 커밋 범위를 확인한다.**

Run:

```bash
git fetch origin
git status --short
git log --oneline origin/master..HEAD
git diff --check origin/master...HEAD
```

Expected: 작업트리 clean, 이번 랜딩 관련 커밋만 존재, whitespace 오류 0.

- [ ] **Step 2: 작업 브랜치를 push한다.**

```bash
git push -u origin codex/new-landing-test
```

Expected: 원격 브랜치 생성 성공.

- [ ] **Step 3: PR을 만들고 CI를 확인한다.**

```bash
gh pr create --base master --head codex/new-landing-test --title "feat: new.inpa.kr/test 서비스 중심 랜딩" --body-file /tmp/new-landing-pr-body.md
gh pr checks --watch
```

PR 본문에는 변경 요약, 기존 화면 불변, 실제 화면 비식별 검수, 자동·브라우저 검증 결과, rollback 방법을 적는다.

Expected: Backend, Frontend, gitleaks CI 전부 PASS.

- [ ] **Step 4: master에 병합해 Vercel 운영 배포를 시작한다.**

```bash
gh pr merge --merge --delete-branch
```

Expected: PR merged, Vercel이 master 배포 시작. 이번 변경은 프론트 정적 페이지와 Proxy뿐이라 DB migration과 Render 설정 변경은 없다.

- [ ] **Step 5: 실제 운영 주소와 기존 주소를 브라우저·HTTP로 검증한다.**

Run:

```bash
curl -sS -I https://new.inpa.kr/test
curl -sS -I https://new.inpa.kr/new/test
curl -sS -I https://new.inpa.kr/
curl -sS -I https://www.inpa.kr/
```

Expected:

- `https://new.inpa.kr/test`: 200
- `https://new.inpa.kr/new/test`: `/test`로 redirect
- `https://new.inpa.kr/`: 기존 영화 랜딩 200
- `https://www.inpa.kr/`: 기존 운영 랜딩 200

인앱 브라우저로 390px·768px·1440px 렌더, 탭, 확대, ESC, 포커스 복귀, CTA, noindex, 콘솔 오류 0을 다시 확인한다. Vercel/브라우저 오류를 5분간 관찰한다.

- [ ] **Step 6: 문제가 있으면 즉시 되돌릴 수 있는 상태를 확인한다.**

Rollback: PR merge commit을 `git revert`하는 긴급 PR 또는 Vercel의 이전 성공 배포 Promote/Rollback. DB 변경은 없으므로 데이터 rollback은 필요 없다.

- [ ] **Step 7: 배포 완료 뒤 두 문서를 최소 범위로 갱신한다.**

- `README.md`: PM용으로 `/test` 후보 주소와 목적, 기존 랜딩 불변을 한 단락 추가
- `AGENTS.md`: 현재 상태와 라우팅 계약을 간결하게 추가

문서만 별도 커밋·PR·배포하고 실제 주소가 유지되는지 최종 확인한다.

---

## Definition of Done

- [ ] `https://new.inpa.kr/test`가 200이고 첫 화면에 실제 제품과 CTA가 함께 보인다.
- [ ] 제품 화면 5개가 탭과 확대 보기로 작동한다.
- [ ] 390px, 768px, 1440px에서 가로 넘침과 잘림이 없다.
- [ ] 키보드, ESC, 포커스 복귀, 움직임 줄이기 설정이 작동한다.
- [ ] 개인정보·토큰·localhost·자격증명이 자산과 소스에 없다.
- [ ] `noindex, nofollow`가 실제 응답 HTML에 있다.
- [ ] `new.inpa.kr/`과 `www.inpa.kr/`이 변경 전과 동일하게 작동한다.
- [ ] `npm run test:landing`, `npm run lint:copy`, `npm run build`, CI가 모두 통과한다.
- [ ] PR 병합·Vercel 운영 배포·실제 URL 검증·문서 갱신이 완료된다.
