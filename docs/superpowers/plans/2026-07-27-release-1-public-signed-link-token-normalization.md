# Release 1 공개 서명 링크 경로 토큰 정규화 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/c`, `/b`, `/r`, `/r/manage`, `/recruiting/join`의 raw 및 한 번 인코딩된 Django signed token을 같은 정상 링크로 처리하고, 잘못된 링크는 API 호출 전에 차단한다.

**Architecture:** 동적 경로 파라미터는 `lib/signed-route-token.ts`에서 정확히 한 번 decode하고 안전 문자 검사를 통과한 raw token으로 통일한다. 각 공개 route는 raw token만 API 함수에 넘기고, `lib/api.ts`가 경로 세그먼트를 정확히 한 번 encode한다. 404/410은 종료 상태, network/429/5xx는 같은 화면에서 재시도 가능한 상태로 분리한다.

**Tech Stack:** Next.js 16.2.9 App Router, React 19.2.4, TypeScript 5, Vitest 4, Testing Library.

## Global Constraints

- 설계 SSOT는 `docs/superpowers/specs/2026-07-27-public-signed-route-token-normalization-design.md`다.
- 이 릴리스는 프런트 전용이다. Django signer, token salt, TTL, DB schema를 변경하지 않는다.
- 정규화는 decode 정확히 1회, API 경로 encode 정확히 1회다.
- 허용 문자는 `A-Z a-z 0-9 . _ : -`뿐이며 빈 문자열, `.`, `..`는 거절한다.
- `%253A` 같은 이중 인코딩, 잘못된 `%` escape, slash, 공백, 제어문자는 API 호출 전에 거절한다.
- `/s`, `/d`, `/p`, 이메일 인증, 비밀번호 재설정 경로는 범위 밖이다.
- 404 위조/잘못된 링크와 410 만료 링크의 백엔드 상태 코드를 유지한다.
- 고객 화면에는 token·encode·서명 같은 내부 단어를 쓰지 않는다.
- 운영 동의 제출·철회·예약 생성은 금지하고, 운영에서는 GET만 검증한다.
- 아래 커밋 단계는 PM이 별도로 요청한 경우에만 수행한다.

---

## File Structure

| 파일 | 책임 |
|---|---|
| `inpa_fe/lib/signed-route-token.ts` | signed route token의 안전 검사와 1회 정규화 단일 권위 |
| `inpa_fe/components/__tests__/signed-route-token.test.tsx` | raw/encoded/double/malformed 순수 함수 회귀 |
| `inpa_fe/app/c/[token]/page.tsx` | 동의 route 정규화, terminal/retryable 로드 상태 |
| `inpa_fe/app/b/[token]/page.tsx` | 예약 route 정규화, terminal/retryable 로드 상태 |
| `inpa_fe/app/r/[token]/page.tsx` | 공개 지원 route에서 normalized token 전달 |
| `inpa_fe/app/r/manage/[token]/page.tsx` | 지원 관리 route에서 normalized token 전달 |
| `inpa_fe/app/recruiting/join/[token]/page.tsx` | 팀 합류 route를 공용 helper로 통합 |
| `inpa_fe/components/recruiting/public-recruiting-view-model.ts` | recruiting 전용 안전 검사 별칭만 유지 |
| `inpa_fe/components/recruiting/public-recruiting-view-model.test.ts` | 기존 recruiting 저장·복구 계약 회귀 |
| `inpa_fe/components/__tests__/public-signed-route-pages.test.tsx` | route가 normalized raw token만 API/하위 컴포넌트에 전달하는 통합 회귀 |
| `inpa_fe/components/__tests__/public-signed-api-paths.test.tsx` | raw token이 API 경로에서 정확히 한 번 encode되는 회귀 |

### Task 1: signed route token 단일 권위 추가

**Files:**

- Create: `inpa_fe/lib/signed-route-token.ts`
- Create: `inpa_fe/components/__tests__/signed-route-token.test.tsx`
- Modify: `inpa_fe/components/recruiting/public-recruiting-view-model.ts`
- Modify: `inpa_fe/components/recruiting/public-recruiting-view-model.test.ts`

**Interfaces:**

- Produces: `isSafeSignedRouteToken(value: unknown): value is string`
- Produces: `normalizeSignedRouteToken(value: unknown): string | null`
- Preserves: `isSafeRecruitingToken` export as an alias to the shared predicate

- [ ] **Step 1: 순수 함수 RED 테스트를 작성한다.**

```tsx
import { describe, expect, it } from "vitest";
import {
  isSafeSignedRouteToken,
  normalizeSignedRouteToken,
} from "@/lib/signed-route-token";

const SIGNED = "eyJwayI6MTI4fQ:1wo9X8:k8naBaeSr-UhWUIbw-0KvWK1c8";

describe("signed route token", () => {
  it("accepts raw and one encoded token as the same raw token", () => {
    expect(normalizeSignedRouteToken(SIGNED)).toBe(SIGNED);
    expect(normalizeSignedRouteToken(encodeURIComponent(SIGNED))).toBe(SIGNED);
  });

  it.each([
    encodeURIComponent(encodeURIComponent(SIGNED)),
    "broken%2",
    "has/slash",
    "has%2Fslash",
    "has space",
    "%00control",
    ".",
    "..",
    "",
  ])("rejects unsafe input %s", (value) => {
    expect(normalizeSignedRouteToken(value)).toBeNull();
  });

  it("rejects non strings", () => {
    expect(normalizeSignedRouteToken(undefined)).toBeNull();
    expect(normalizeSignedRouteToken(["signed"])).toBeNull();
  });

  it("uses the same predicate for already decoded values", () => {
    expect(isSafeSignedRouteToken(SIGNED)).toBe(true);
    expect(isSafeSignedRouteToken("has%3Aescape")).toBe(false);
  });
});
```

- [ ] **Step 2: 새 테스트가 RED인지 확인한다.**

Run:

```bash
cd inpa_fe
npm run test:run -- components/__tests__/signed-route-token.test.tsx
```

Expected: `@/lib/signed-route-token`이 없어 FAIL.

- [ ] **Step 3: helper를 최소 계약으로 구현한다.**

```ts
const SAFE_SIGNED_ROUTE_TOKEN = /^[A-Za-z0-9._:-]+$/;

export function isSafeSignedRouteToken(value: unknown): value is string {
  return (
    typeof value === "string"
    && value.length > 0
    && value !== "."
    && value !== ".."
    && SAFE_SIGNED_ROUTE_TOKEN.test(value)
  );
}

export function normalizeSignedRouteToken(value: unknown): string | null {
  if (typeof value !== "string") return null;
  try {
    const decoded = decodeURIComponent(value);
    return isSafeSignedRouteToken(decoded) ? decoded : null;
  } catch {
    return null;
  }
}
```

- [ ] **Step 4: recruiting의 중복 정규화 구현을 제거한다.**

`public-recruiting-view-model.ts`에서 로컬 정규식과 `normalizeRecruitingRouteToken` 구현을 삭제하고, 기존 호출부 호환이 필요한 predicate만 명시적으로 별칭 export한다.

```ts
import { isSafeSignedRouteToken } from "@/lib/signed-route-token";

export const isSafeRecruitingToken = isSafeSignedRouteToken;
```

`public-recruiting-view-model.test.ts`에서는 normalize 전용 assertion을 새 순수 함수 테스트로 옮긴다. 지원서 저장, manage token 복구, URL 조립 테스트는 그대로 유지한다.

- [ ] **Step 5: 순수 함수와 기존 recruiting unit을 GREEN으로 만든다.**

Run:

```bash
cd inpa_fe
npm run test:run -- components/__tests__/signed-route-token.test.tsx
npm run test:unit
```

Expected: 두 명령 모두 PASS.

- [ ] **Step 6: PM이 커밋을 요청한 경우에만 Task 1 파일만 커밋한다.**

```bash
git add inpa_fe/lib/signed-route-token.ts inpa_fe/components/__tests__/signed-route-token.test.tsx inpa_fe/components/recruiting/public-recruiting-view-model.ts inpa_fe/components/recruiting/public-recruiting-view-model.test.ts
git commit -m "fix(공개링크): 서명 경로 토큰 정규화 통합"
```

### Task 2: 고객 동의 `/c`에 정규화와 재시도 상태 적용

**Files:**

- Modify: `inpa_fe/app/c/[token]/page.tsx`
- Create: `inpa_fe/components/__tests__/public-signed-route-pages.test.tsx`

**Interfaces:**

- Consumes: `normalizeSignedRouteToken`
- Consumes: raw token contract of `getConsentDisclosure` and `submitConsent`
- Produces: invalid route API call count 0
- Produces: network/429/5xx retry button, 404/410 terminal card

- [ ] **Step 1: encoded route와 invalid route RED 테스트를 작성한다.**

테스트 fixture는 필수 동의 한 건을 가진 완전한 `ConsentDisclosure`를 사용한다.

```tsx
const consentDisclosure = {
  customer: { name_masked: "김**" },
  planner: { affiliation: "부산지점" },
  items: [{
    scope: "personal_info" as const,
    title: "상담을 위한 개인정보 이용",
    required: true,
    already: false,
    revocable: false,
    lines: ["상담 준비에 필요한 정보를 이용합니다."],
    notice: "동의 내용은 언제든 확인할 수 있어요.",
  }],
  all_required_done: false,
  disclaimer: "동의 내용을 확인해 주세요.",
};
```

다음 assertion을 추가한다.

```tsx
navigation.token = encodeURIComponent(SIGNED);
api.getConsentDisclosure.mockResolvedValue(consentDisclosure);
render(<CustomerConsentPage />);
await waitFor(() => expect(api.getConsentDisclosure).toHaveBeenCalledWith(SIGNED));

navigation.token = encodeURIComponent(encodeURIComponent(SIGNED));
render(<CustomerConsentPage />);
expect(await screen.findByText("링크를 열 수 없어요")).toBeTruthy();
expect(api.getConsentDisclosure).not.toHaveBeenCalled();
```

- [ ] **Step 2: 404/410과 retryable 오류 RED 테스트를 작성한다.**

```tsx
api.getConsentDisclosure.mockRejectedValueOnce(
  new ApiError(410, "LINK_EXPIRED", "담당 설계사에게 새 링크를 요청해 주세요."),
);
render(<CustomerConsentPage />);
expect(await screen.findByText("링크를 열 수 없어요")).toBeTruthy();
expect(screen.queryByRole("button", { name: "다시 불러오기" })).toBeNull();

api.getConsentDisclosure
  .mockRejectedValueOnce(new ApiError(503, "TEMPORARY", "temporary"))
  .mockResolvedValueOnce(consentDisclosure);
render(<CustomerConsentPage />);
expect(await screen.findByText("잠시 연결이 원활하지 않아요")).toBeTruthy();
await userEvent.setup().click(screen.getByRole("button", { name: "다시 불러오기" }));
expect(await screen.findByText("상담을 위한 개인정보 이용")).toBeTruthy();
```

network `TypeError`와 429도 같은 retryable assertion 표에 넣는다.

- [ ] **Step 3: submit과 revoke가 같은 normalized token을 쓰는 RED 테스트를 추가한다.**

동의 체크 후 제출, 이미 동의한 fixture의 철회를 각각 실행하고 아래를 확인한다.

```tsx
expect(api.submitConsent).toHaveBeenCalledWith(
  SIGNED,
  ["personal_info"],
);

expect(api.submitConsent).toHaveBeenCalledWith(
  SIGNED,
  [],
  ["personal_info"],
);
```

- [ ] **Step 4: `/c`에서 route token을 한 번 정규화한다.**

```ts
const params = useParams<{ token?: string | string[] }>();
const token = normalizeSignedRouteToken(params?.token);
```

로드 함수는 호출 시작마다 이전 retryable 오류를 지우고, token이 `null`이면 fetch 없이 terminal 상태를 설정한다. 상태 shape를 다음과 같이 고정한다.

```ts
type PublicLoadFailure = {
  kind: "terminal" | "retryable";
  message: string;
};
```

분류 규칙:

```text
invalid route token -> terminal
ApiError 404 or 410 -> terminal, backend detail 표시
ApiError 429 or 500 이상 -> retryable, 일반 연결 안내
TypeError/network -> retryable, 일반 연결 안내
```

retryable card에는 `다시 불러오기` 버튼을 둔다. terminal card에는 버튼을 두지 않고 새 링크 요청 행동을 안내한다.

- [ ] **Step 5: 동의 route 테스트를 GREEN으로 만든다.**

Run:

```bash
cd inpa_fe
npm run test:run -- components/__tests__/public-signed-route-pages.test.tsx
```

Expected: encoded GET·POST·철회와 오류 상태 assertion이 PASS.

### Task 3: 고객 예약 `/b`에 같은 경계 적용

**Files:**

- Modify: `inpa_fe/app/b/[token]/page.tsx`
- Modify: `inpa_fe/components/__tests__/public-signed-route-pages.test.tsx`

**Interfaces:**

- Consumes: `normalizeSignedRouteToken`
- Consumes: raw token contract of `getBookingInfo` and `submitBooking`
- Produces: encoded GET/POST가 같은 raw token을 사용

- [ ] **Step 1: 예약 fixture와 encoded GET RED 테스트를 추가한다.**

```tsx
const bookingInfo = {
  customer: { name_masked: "김**" },
  planner: { affiliation: "부산지점", name: "황예진" },
  methods: [{ key: "phone" as const, label: "전화" }],
  duration_min: 30,
  slots: [{
    start_at: "2026-07-28T10:00:00+09:00",
    duration_min: 30,
  }],
  disclaimer: "예약 요청 뒤 담당 설계사가 확인해요.",
};

navigation.token = encodeURIComponent(SIGNED);
api.getBookingInfo.mockResolvedValue(bookingInfo);
render(<PublicBookingPage />);
await waitFor(() => expect(api.getBookingInfo).toHaveBeenCalledWith(SIGNED));
```

- [ ] **Step 2: 예약 POST와 invalid/no-fetch RED 테스트를 추가한다.**

시간과 방식을 선택하고 신청한 뒤 다음을 확인한다.

```tsx
expect(api.submitBooking).toHaveBeenCalledWith(SIGNED, {
  start_at: "2026-07-28T10:00:00+09:00",
  method: "phone",
  note: undefined,
});
```

double encoded, slash, malformed `%` route에서는 `getBookingInfo`와 `submitBooking` 호출이 모두 0회여야 한다.

- [ ] **Step 3: 예약의 terminal/retryable 상태 RED 테스트를 추가한다.**

404·410은 retry 버튼 없이 새 링크 요청 안내를, 429·503·network는 `다시 불러오기`로 성공 화면에 복귀하는지 확인한다.

- [ ] **Step 4: `/b`가 normalized raw token만 사용하도록 구현한다.**

`/c`와 같은 분류 규칙을 적용하되 예약 사용자 카피를 사용한다.

```text
terminal title: 링크를 열 수 없어요
retryable title: 잠시 연결이 원활하지 않아요
retry action: 다시 불러오기
```

409 예약 충돌은 기존대로 선택 시간을 비우고 `load()`로 최신 슬롯을 다시 가져온다. 이때도 normalized raw token을 유지한다.

- [ ] **Step 5: 동의·예약 route 테스트를 함께 GREEN으로 만든다.**

Run:

```bash
cd inpa_fe
npm run test:run -- components/__tests__/public-signed-route-pages.test.tsx
```

Expected: `/c`, `/b` 전체 PASS.

### Task 4: 세 영입 route를 공용 helper로 통합

**Files:**

- Modify: `inpa_fe/app/r/[token]/page.tsx`
- Modify: `inpa_fe/app/r/manage/[token]/page.tsx`
- Modify: `inpa_fe/app/recruiting/join/[token]/page.tsx`
- Modify: `inpa_fe/components/__tests__/public-signed-route-pages.test.tsx`

**Interfaces:**

- Consumes: `normalizeSignedRouteToken`
- Produces: 세 server page가 raw/encoded token을 동일 raw prop으로 전달
- Produces: invalid token은 빈 문자열로 전달되어 기존 `isSafeRecruitingToken` 안전 오류 상태 사용

- [ ] **Step 1: 세 async page의 raw/encoded prop RED 테스트를 작성한다.**

각 page 함수를 직접 호출하고 반환 React element의 `props.token`을 검사한다.

```tsx
const raw = await PublicRecruitingPage({
  params: Promise.resolve({ token: SIGNED }),
});
const encoded = await PublicRecruitingPage({
  params: Promise.resolve({ token: encodeURIComponent(SIGNED) }),
});
const invalid = await PublicRecruitingPage({
  params: Promise.resolve({ token: encodeURIComponent(encodeURIComponent(SIGNED)) }),
});

expect(raw.props.token).toBe(SIGNED);
expect(encoded.props.token).toBe(SIGNED);
expect(invalid.props.token).toBe("");
```

같은 assertion을 `RecruitingManagePage`, `RecruitingJoinPage`에 적용한다.

- [ ] **Step 2: 세 page가 공용 helper를 직접 호출하게 바꾼다.**

```ts
const { token } = await params;
return <PublicRecruitingApplication token={normalizeSignedRouteToken(token) ?? ""} />;
```

manage와 join도 각 하위 컴포넌트만 다르고 같은 경계를 사용한다.

- [ ] **Step 3: route·recruiting 테스트를 GREEN으로 만든다.**

Run:

```bash
cd inpa_fe
npm run test:run -- components/__tests__/public-signed-route-pages.test.tsx
npm run test:unit
```

Expected: route integration과 기존 recruiting unit 모두 PASS.

### Task 5: API 1회 encode 계약과 전체 검증

**Files:**

- Verify: `inpa_fe/lib/api.ts`
- Modify only if regression test exposes a violation: `inpa_fe/lib/api.ts`
- Create: `inpa_fe/components/__tests__/public-signed-api-paths.test.tsx`
- Verify: all files changed in Tasks 1-4

**Interfaces:**

- Consumes: route에서 정규화된 raw token
- Preserves: `encodeURIComponent(token)` exactly once in public API path builders

- [ ] **Step 1: fetch URL 계약 테스트를 추가한다.**

`global.fetch`를 mock하고 아래 네 함수가 raw token을 한 번 인코딩한 URL을 만드는지 확인한다.

```tsx
vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
  new Response(JSON.stringify({}), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  }),
));

await getConsentDisclosure(SIGNED);
expect(fetch).toHaveBeenLastCalledWith(
  expect.stringContaining(`/c/${encodeURIComponent(SIGNED)}/`),
);

await getBookingInfo(SIGNED);
expect(fetch).toHaveBeenLastCalledWith(
  expect.stringContaining(`/b/${encodeURIComponent(SIGNED)}/`),
);
```

`submitConsent`, `submitBooking`도 같은 URL assertion을 하고 method가 POST인지 확인한다. 기대 URL에 `%253A`가 포함되지 않는 assertion을 추가한다.

- [ ] **Step 2: 정적 이중 encode 흔적을 검사한다.**

Run:

```bash
cd inpa_fe
rg -n "encodeURIComponent\\(encodeURIComponent|decodeURIComponent\\(decodeURIComponent|normalizeRecruitingRouteToken" app components lib
```

Expected: 이중 호출과 폐기한 recruiting normalize 함수 참조 0건.

- [ ] **Step 3: 프런트 전체 게이트를 실행한다.**

Run:

```bash
cd inpa_fe
npm run test:run -- components/__tests__/public-signed-api-paths.test.tsx
npm run test:unit
npm run test:run
npm run lint:copy
npm run build
```

Expected: 모두 PASS, Next build가 `/c/[token]`, `/b/[token]`, `/r/[token]`, `/r/manage/[token]`, `/recruiting/join/[token]`을 성공적으로 빌드.

- [ ] **Step 4: 브라우저에서 preview 공개 링크를 검증한다.**

검증 순서:

```text
1. 로컬 테스트 고객으로 동의 링크와 예약 링크 생성
2. 생성된 raw URL을 그대로 열어 실제 내용 확인
3. colon을 %3A로 바꾼 URL을 열어 같은 내용 확인
4. %를 %25로 한 번 더 바꾼 URL에서 안전 오류 확인
5. network offline 또는 503 mock 뒤 다시 불러오기 확인
6. expired fixture에서 새 링크 요청 안내 확인
```

Expected:

- 정상 링크는 disclosure/slots를 표시한다.
- double encoded 링크는 API request 0회다.
- retryable 오류는 같은 URL에서 회복된다.

- [ ] **Step 5: 운영은 읽기 전용 GET만 검증한다.**

PM이 운영 배포를 승인한 뒤 실제 발급된 `/c`와 `/b` 링크를 열어 항목과 슬롯이 표시되는지만 확인한다. 동의 체크, 철회, 예약 신청 버튼은 누르지 않는다.

- [ ] **Step 6: PM이 커밋을 요청한 경우에만 Release 1 변경을 커밋한다.**

```bash
git add inpa_fe/lib/signed-route-token.ts 'inpa_fe/app/c/[token]/page.tsx' 'inpa_fe/app/b/[token]/page.tsx' 'inpa_fe/app/r/[token]/page.tsx' 'inpa_fe/app/r/manage/[token]/page.tsx' 'inpa_fe/app/recruiting/join/[token]/page.tsx' inpa_fe/components/recruiting/public-recruiting-view-model.ts inpa_fe/components/recruiting/public-recruiting-view-model.test.ts inpa_fe/components/__tests__/signed-route-token.test.tsx inpa_fe/components/__tests__/public-signed-route-pages.test.tsx inpa_fe/components/__tests__/public-signed-api-paths.test.tsx
git commit -m "fix(공개링크): 동의 예약 영입 경로 이중 인코딩 수정"
```

## Release 1 완료 증거

```text
Changed: 공개 signed route token을 한 번 decode, API에서 한 번 encode하도록 통합
Verified by: helper test, route test, recruiting unit, copy lint, Next build, preview browser
Result: raw/encoded 정상, double/malformed API 호출 0회, 404/410 종료, network/5xx 재시도
Unverified: 운영 POST 동작은 실제 고객 데이터 보호를 위해 로컬 테스트로 대체
```
