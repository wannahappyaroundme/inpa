# Release 2 데이터 무결성·오류 상태·시간대 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 로드 실패가 기존 설정을 덮어쓰거나 실제 빈 데이터처럼 보이지 않게 하고, 느린 이전 요청이 최신 고객·월 선택을 덮어쓰지 못하게 하며, 모든 일정 날짜 계산을 브라우저 시간대와 무관한 KST 계약으로 통일한다.

**Architecture:** 읽기 상태를 `loading | ready | empty | error`로 명시하고 저장은 해당 데이터가 `ready`일 때만 허용한다. 변경 저장은 최초 서버 snapshot과 비교한 diff PATCH만 보낸다. 검색·월 조회는 요청 세대 번호와 AbortSignal을 사용해 latest-wins로 만든다. KST 날짜·입력 변환은 순수 유틸리티 하나에 모으고 공개 토큰 페이지는 영구 오류와 일시 오류를 분리한다.

**Tech Stack:** Next.js 16/React 19/TypeScript, Vitest/Testing Library, DRF `ApiError` contract, Intl DateTimeFormat.

## 2026-08-18 검증 결과 (아래 원문은 그대로 유지)

**이 릴리스 범위는 일부만 해소됐다. 잔존 항목이 가장 많이 남은 릴리스다.** 2026-08-18 세션에서 코드 대조로 확인했다.

해소:
- 예약 설정 로드 실패 시 저장 차단은 적용됨.

잔존 (후속 후보, 아직 미착수):
1. `/analysis` 화면의 고객 목록이 API 실패 시 재시도 없이 빈 상태로 표시된다 (`inpa_fe/app/analysis/page.tsx:176-187`).
2. 요청 경합 가드가 세 곳에 미적용이다 (`app/home/page.tsx:212`, `app/schedule/page.tsx:125`, `app/customers/page.tsx:221`). 유틸 `lib/latest-request.ts`는 이미 존재하므로 적용만 하면 된다.
3. 일정 입력이 브라우저 시간대에 의존한다 (`app/schedule/page.tsx:74,76,81`). 공용 KST 모듈이 아직 없다.
4. 예약 설정 저장이 전체 payload PATCH다. diff PATCH 미적용.

아래 원문은 당시 구현 계획 기록으로 보존한다. 전체 잔존 목록은 `docs/superpowers/specs/2026-07-21-comprehensive-stability-upgrade.md` §0 참고.

## Global Constraints

- 승인 설계는 `docs/superpowers/specs/2026-07-21-comprehensive-stability-upgrade.md`의 Release 2다.
- 화면은 light-fixed를 유지한다. 서비스 화면에 `dark:` variant를 추가하지 않는다.
- API 오류를 빈 배열이나 기본값으로 치환하지 않는다.
- 설정을 읽지 못한 상태에서는 저장 버튼을 활성화하지 않는다.
- optimistic delete가 실패하면 반드시 최신 서버 상태를 다시 읽고 사용자에게 안내한다.
- 모든 월·오늘·벽시계 입력은 Asia/Seoul 기준이다. 브라우저의 로컬 시간대에 기대지 않는다.
- 공개 `/s`, `/b`, `/c`, `/d`, `/p`는 404/410과 network/5xx를 다른 화면으로 보여준다.
- 복구 버튼은 같은 요청을 재시도하고, 새 링크 요청 안내는 실제 만료·위조에만 사용한다.
- 랜딩·게시판·요금제 동시 작업 파일은 제외한다.
- 아래 커밋 단계는 PM이 별도로 요청한 경우에만 수행한다.

---

### Task 1: KST 날짜와 latest-wins를 순수 유틸리티로 고정

**Files:**

- Create: `inpa_fe/lib/kst.ts`
- Create: `inpa_fe/lib/latest-request.ts`
- Create: `inpa_fe/components/__tests__/kst-and-latest-request.test.tsx`

- [ ] **Step 1: 브라우저 시간대 독립 테스트를 RED로 작성한다.**

다음 공개 함수를 테스트한다.

```ts
import {
  daysInMonth,
  kstDateToUtcNoonIso,
  kstLocalInputToIso,
  kstMonthKey,
  kstToday,
  parseRealDate,
} from "@/lib/kst";

it("rejects impossible dates", () => {
  expect(parseRealDate("2026-02-31")).toBeNull();
});

it("converts KST wall clock without browser timezone", () => {
  expect(kstLocalInputToIso("2026-07-21T09:30"))
    .toBe("2026-07-21T00:30:00.000Z");
});

it("stores all-day as KST noon", () => {
  expect(kstDateToUtcNoonIso("2026-07-21"))
    .toBe("2026-07-21T03:00:00.000Z");
});
```

Fake timer를 `2026-07-31T15:30:00Z`로 고정해 `kstToday()`와 `kstMonthKey()`가 `2026-08-01`, `2026-08`인지 확인한다.

- [ ] **Step 2: 이전 요청 무효화 테스트를 작성한다.**

`createLatestRequestGuard()`는 다음 계약을 가진다.

```ts
const guard = createLatestRequestGuard();
const first = guard.begin();
const second = guard.begin();
expect(first.isLatest()).toBe(false);
expect(second.isLatest()).toBe(true);
guard.cancelAll();
expect(second.isLatest()).toBe(false);
```

각 `begin()`은 `signal`, `isLatest()`, `finish()`를 반환한다. 새 요청 시작 시 이전 controller를 abort한다.

- [ ] **Step 3: 테스트 실패를 확인한다.**

Run: `cd inpa_fe && npm test -- --run components/__tests__/kst-and-latest-request.test.tsx`

Expected: 두 유틸리티 모듈이 없어 실패.

- [ ] **Step 4: 고정 UTC+9 순수 변환을 구현한다.**

한국은 DST가 없으므로 벽시계 입력은 명시적으로 9시간을 뺀 UTC로 만든다. `new Date(localString)`을 사용하지 않는다.

```ts
const KST_OFFSET_HOURS = 9;

export function kstLocalInputToIso(value: string): string {
  const parts = parseLocalDateTime(value);
  if (!parts || !isRealDate(parts.year, parts.month, parts.day)) {
    throw new Error("INVALID_KST_DATETIME");
  }
  return new Date(Date.UTC(
    parts.year,
    parts.month - 1,
    parts.day,
    parts.hour - KST_OFFSET_HOURS,
    parts.minute,
  )).toISOString();
}
```

`kstToday(now = new Date())`는 `Intl.DateTimeFormat(..., {timeZone: "Asia/Seoul"}).formatToParts()`를 사용한다. 달력 격자 계산은 UTC 생성자와 UTC getter만 사용한다.

- [ ] **Step 5: 최신 요청 guard를 구현한다.**

```ts
export function createLatestRequestGuard() {
  let generation = 0;
  let controller: AbortController | null = null;
  return {
    begin() {
      controller?.abort();
      controller = new AbortController();
      const mine = ++generation;
      return {
        signal: controller.signal,
        isLatest: () => mine === generation && !controller?.signal.aborted,
        finish: () => undefined,
      };
    },
    cancelAll() {
      generation += 1;
      controller?.abort();
    },
  };
}
```

실제 구현은 각 token이 자기 controller를 캡처하도록 해 새 controller가 생겨도 `isLatest()`가 올바르게 동작하게 한다.

- [ ] **Step 6: 유틸리티 테스트를 통과시킨다.**

Run: `cd inpa_fe && npm test -- --run components/__tests__/kst-and-latest-request.test.tsx`

Expected: impossible date, KST 월 경계, 벽시계, latest-wins 모두 PASS.

---

### Task 2: API wrapper에 취소 신호를 전달하고 오류 분류를 단일화

**Files:**

- Modify: `inpa_fe/lib/api.ts`
- Create: `inpa_fe/lib/load-state.ts`
- Create: `inpa_fe/components/public-load-error.tsx`
- Create: `inpa_fe/components/__tests__/public-load-error.test.tsx`

- [ ] **Step 1: 영구 오류와 일시 오류 분류 테스트를 작성한다.**

```ts
expect(classifyPublicLoadError(new ApiError(404, "INVALID", "...")))
  .toBe("terminal");
expect(classifyPublicLoadError(new ApiError(410, "EXPIRED", "...")))
  .toBe("terminal");
expect(classifyPublicLoadError(new ApiError(503, "DOWN", "...")))
  .toBe("retryable");
expect(classifyPublicLoadError(new TypeError("Failed to fetch")))
  .toBe("retryable");
```

컴포넌트 테스트는 retryable 상태에서 `다시 불러오기` 버튼이 있고 terminal 상태에는 새 링크 요청 안내만 있는지 확인한다.

- [ ] **Step 2: `request()`가 선택적 AbortSignal을 받는 테스트를 추가한다.**

API 테스트가 별도 파일로 분리되어 있지 않다면 `public-load-error.test.tsx`에서 mocked fetch로 signal 전달을 검증한다. AbortError는 사용자 오류로 표시하지 않고 호출부가 무시할 수 있도록 그대로 throw한다.

- [ ] **Step 3: RED를 확인한다.**

Run: `cd inpa_fe && npm test -- --run components/__tests__/public-load-error.test.tsx`

- [ ] **Step 4: 요청 options를 additive하게 확장한다.**

```ts
export interface RequestOptions {
  signal?: AbortSignal;
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  auth = false,
  extraHeaders: Record<string, string> = {},
  options: RequestOptions = {},
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal: options.signal,
  });
  ...
}
```

기존 호출 시그니처는 깨지지 않아야 한다. 목록 API 중 customers, schedule, meetings만 우선 `options?: RequestOptions`를 공개한다.

- [ ] **Step 5: 공통 load-state와 공개 오류 컴포넌트를 구현한다.**

```ts
export type LoadState = "idle" | "loading" | "ready" | "empty" | "error";
export type PublicLoadErrorKind = "terminal" | "retryable";
```

`PublicLoadError`는 `kind`, `message`, `onRetry`만 받는다. 서버 원문 stack·digest·민감 정보를 렌더링하지 않는다.

- [ ] **Step 6: 테스트와 typecheck를 통과시킨다.**

Run:

```bash
cd inpa_fe
npm test -- --run components/__tests__/public-load-error.test.tsx
npm run build
```

---

### Task 3: 예약 설정을 독립 로드·diff PATCH·복구 가능한 저장으로 변경

**Files:**

- Modify: `inpa_fe/components/booking-settings.tsx`
- Create: `inpa_fe/components/__tests__/booking-settings.test.tsx`

- [ ] **Step 1: 데이터 덮어쓰기 회귀 테스트를 작성한다.**

mock API로 다음을 검증한다.

```ts
it("blocks profile save until profile has loaded", async () => ...);
it("shows retry when profile load fails and sends no PATCH", async () => ...);
it("keeps work-hour failure separate from profile readiness", async () => ...);
it("PATCHes only fields changed from the server snapshot", async () => ...);
it("restores a deleted work hour when DELETE fails", async () => ...);
```

profile 성공 + workhours 실패일 때 profile form은 편집·저장 가능하고, 업무시간 영역만 재시도 상태여야 한다. 반대 경우 profile 저장은 차단하되 업무시간 추가·삭제는 서버 데이터가 로드된 뒤 독립 동작한다.

- [ ] **Step 2: 현재 구현에서 RED를 확인한다.**

Run: `cd inpa_fe && npm test -- --run components/__tests__/booking-settings.test.tsx`

Expected: 현재 catch가 실패를 숨기고 모든 필드를 PATCH하므로 실패.

- [ ] **Step 3: profile과 workhours 상태를 분리한다.**

```ts
const [profileState, setProfileState] = useState<LoadState>("loading");
const [workHoursState, setWorkHoursState] = useState<LoadState>("loading");
const initialProfile = useRef<BookingProfileFields | null>(null);
```

각 load 함수는 독립 `retryProfile`, `retryWorkHours`로 만든다. catch에서 기본값이나 빈 배열을 성공 상태처럼 저장하지 않는다.

- [ ] **Step 4: diff PATCH builder를 순수 함수로 분리해 같은 테스트 파일에서 검증한다.**

```ts
export function changedBookingFields(
  initial: BookingProfileFields,
  current: BookingProfileFields,
): Partial<BookingProfileFields> {
  return Object.fromEntries(
    Object.keys(current)
      .filter((key) => current[key] !== initial[key])
      .map((key) => [key, current[key]]),
  );
}
```

변경이 0개면 PATCH하지 않고 `바뀐 내용이 없어요`를 표시한다. 성공하면 반환된 서버 profile을 새 snapshot으로 갱신한다.

- [ ] **Step 5: 저장·삭제 오류를 화면 가까이에 표시한다.**

profile load 실패에는 `예약 설정을 다시 불러오기`, workhours 실패에는 `업무시간 다시 불러오기`를 둔다. 삭제 실패 시 list를 서버에서 다시 읽고, 재읽기도 실패하면 삭제 전 local snapshot을 복구한다.

- [ ] **Step 6: 테스트를 통과시킨다.**

Run: `cd inpa_fe && npm test -- --run components/__tests__/booking-settings.test.tsx`

---

### Task 4: 분석 고객 목록과 고객 검색에서 오류·빈 상태·요청 경합을 분리

**Files:**

- Modify: `inpa_fe/app/analysis/page.tsx`
- Modify: `inpa_fe/app/customers/page.tsx`
- Create: `inpa_fe/components/__tests__/analysis-customer-load.test.tsx`
- Create: `inpa_fe/components/__tests__/customer-search-latest.test.tsx`

- [ ] **Step 1: 분석 고객 목록 실패 테스트를 작성한다.**

`listAllCustomers`가 실패하면 `고객 없음`을 표시하지 않고 `고객 목록을 불러오지 못했어요`와 `다시 불러오기`를 표시해야 한다. 성공한 빈 배열일 때만 `등록된 고객이 없어요`와 고객 추가 CTA를 표시한다.

- [ ] **Step 2: 검색 응답 역전 테스트를 작성한다.**

첫 요청 `김`, 둘째 요청 `김민`을 deferred promise로 만들고 둘째를 먼저 resolve한다. 첫 응답이 나중에 도착해도 `김민` 결과가 유지되어야 한다. AbortError는 오류 배너를 만들지 않는다.

- [ ] **Step 3: RED를 확인한다.**

Run:

```bash
cd inpa_fe
npm test -- --run components/__tests__/analysis-customer-load.test.tsx components/__tests__/customer-search-latest.test.tsx
```

- [ ] **Step 4: 분석 페이지에 `customersState`와 retry를 추가한다.**

초기 성공 후 새로고침 실패가 발생해도 마지막 성공 목록을 지우지 않는다. 대신 비차단 오류 배너를 보여주고 재시도할 수 있게 한다. 최초 실패는 full error state다.

- [ ] **Step 5: 고객 검색에 latest request guard를 연결한다.**

검색어, status/stage filter, page 조합마다 새 token을 만든다. state 변경과 unmount에서 이전 요청을 abort한다. `fetchCustomers`를 서로 다른 두 effect가 중복 호출하지 않도록 초기 load와 debounce 흐름을 하나로 합친다.

- [ ] **Step 6: 테스트를 통과시킨다.**

Run:

```bash
cd inpa_fe
npm test -- --run components/__tests__/analysis-customer-load.test.tsx components/__tests__/customer-search-latest.test.tsx
```

---

### Task 5: 일정·홈 달력을 KST와 latest-wins 계약으로 통일

**Files:**

- Modify: `inpa_fe/app/schedule/page.tsx`
- Modify: `inpa_fe/app/home/page.tsx`
- Modify: `inpa_fe/lib/api.ts`
- Create: `inpa_fe/components/__tests__/schedule-kst-latest.test.tsx`
- Create: `inpa_fe/components/__tests__/home-calendar-kst.test.tsx`

- [ ] **Step 1: 월 전환 응답 역전 테스트를 작성한다.**

7월 요청 후 바로 8월로 이동하고 8월 응답을 먼저 resolve한다. 늦은 7월 응답이 8월 grid, 일정 목록, 로딩 상태를 바꾸지 않아야 한다. schedule items와 meetings는 같은 월 token을 공유하되 각 API 실패를 식별할 수 있어야 한다.

- [ ] **Step 2: 다른 브라우저 시간대에서 같은 월·오늘을 만드는 테스트를 작성한다.**

Node TZ를 바꾸는 대신 Task 1 순수 함수를 fake time으로 검증하고, 페이지가 `new Date()` 직접 계산 대신 해당 함수를 호출하는지 mock한다. KST 8월 1일 00:30일 때 홈 D-day와 일정 기본 월이 8월이어야 한다.

- [ ] **Step 3: RED를 확인한다.**

Run:

```bash
cd inpa_fe
npm test -- --run components/__tests__/schedule-kst-latest.test.tsx components/__tests__/home-calendar-kst.test.tsx
```

- [ ] **Step 4: schedule의 날짜 변환을 `lib/kst.ts`로 교체한다.**

삭제 대상:

```ts
new Date(v).toISOString()
new Date(y, m - 1, d, 12, 0, 0).toISOString()
```

대체:

```ts
kstLocalInputToIso(v)
kstDateToUtcNoonIso(ymd)
daysInMonth(viewY, viewM)
weekdayOfKstDate(viewY, viewM, day)
```

반복 차단의 `HH:MM`은 계속 벽시계 문자열로 보내며 Date로 변환하지 않는다.

- [ ] **Step 5: schedule/home 조회에 독립 guard를 적용한다.**

schedule 달력, 홈 미니 달력, 홈 오늘 일정은 서로 다른 guard를 가진다. 월 이동이나 unmount에서 cancel한다. 마지막 성공 데이터를 유지한 채 새 월 로딩을 얹고, 실패 시 선택 월과 데이터 월이 다르게 섞이지 않게 한다.

- [ ] **Step 6: 테스트를 통과시킨다.**

Run:

```bash
cd inpa_fe
npm test -- --run components/__tests__/schedule-kst-latest.test.tsx components/__tests__/home-calendar-kst.test.tsx
```

---

### Task 6: 공개 토큰 페이지에서 만료와 일시 장애를 분리

**Files:**

- Modify: `inpa_fe/app/s/[token]/page.tsx`
- Modify: `inpa_fe/app/b/[token]/page.tsx`
- Modify: `inpa_fe/app/c/[token]/page.tsx`
- Modify: `inpa_fe/app/d/[ref]/page.tsx`
- Modify: `inpa_fe/app/p/[refcode]/page.tsx`
- Modify: `inpa_fe/components/__tests__/share-public.test.tsx`
- Create: `inpa_fe/components/__tests__/public-token-recovery.test.tsx`

- [ ] **Step 1: 각 페이지 공통 오류 matrix 테스트를 작성한다.**

| 응답 | 화면 | 버튼 |
|---|---|---|
| 404/410 | `이 링크의 이용 기간이 끝났어요` 또는 서버의 안전한 안내 | `담당 설계사에게 새 링크 요청` 안내 |
| 408/429/500/502/503/504/network | `연결이 잠시 원활하지 않아요` | `다시 불러오기` |
| AbortError | 기존 화면 유지 | 없음 |

페이지별 정확한 서버 코드가 404 또는 410이면 terminal로 취급한다. 400은 요청 자체가 잘못된 경우 terminal로 취급하되 원문 내부 오류를 그대로 노출하지 않는다.

- [ ] **Step 2: 현재 페이지가 모든 실패를 terminal로 보이는 RED를 확인한다.**

Run: `cd inpa_fe && npm test -- --run components/__tests__/public-token-recovery.test.tsx components/__tests__/share-public.test.tsx`

- [ ] **Step 3: 각 load 함수에 retryable state와 request token을 적용한다.**

token/refcode가 바뀌면 이전 data, success, copied, submit error, contact action을 모두 초기화하고 이전 요청을 abort한다. 재시도는 같은 token을 사용해 GET만 다시 보낸다.

- [ ] **Step 4: 고객용 카피와 접근성을 정리한다.**

오류 영역은 `role="alert"`, 로딩 영역은 `aria-live="polite"`, 다시 불러오기 버튼은 실제 button을 쓴다. 내부 코드, `컴플라이언스`, `게이트`, `토큰` 같은 단어는 고객 화면에 표시하지 않는다.

- [ ] **Step 5: 공개 페이지 테스트를 통과시킨다.**

Run: `cd inpa_fe && npm test -- --run components/__tests__/public-token-recovery.test.tsx components/__tests__/share-public.test.tsx`

---

### Task 7: Release 2 통합·브라우저 검증

**Files:**

- No product file changes
- Review: Release 2에서 수정한 파일만

- [ ] **Step 1: FE 전체 테스트·카피·build를 실행한다.**

```bash
cd inpa_fe
npm test -- --run
npm run lint:copy
npm run build
```

Expected: 전체 PASS, copy finding 0, Next 16 build 성공.

- [ ] **Step 2: Django API 계약에 회귀가 없는지 확인한다.**

```bash
cd ../inpa_be
python manage.py check
python manage.py test inpa.booking inpa.schedule inpa.accounts.tests.IntroCardTests -v 2
```

- [ ] **Step 3: 브라우저 시간대를 세 가지로 바꿔 로컬 Preview를 확인한다.**

Chrome DevTools Sensors의 Timezone에서 `Asia/Seoul`, `America/Los_Angeles`, `UTC`를 각각 선택한다. 모든 경우 다음 결과가 같아야 한다.

- 오늘 날짜와 기본 월
- 일정 입력 09:30 KST의 서버 전송 ISO
- 월말 D-day와 달력 셀
- 공개 예약 시각의 KST 표시

- [ ] **Step 4: 네트워크 실패를 브라우저에서 재현한다.**

DevTools Network offline 또는 API 차단으로 예약 설정, 분석 목록, 공개 `/b`, `/c`, `/p`를 확인한다. 빈 데이터나 만료 화면으로 보이지 않고 retry가 있어야 한다. 연결 복구 후 같은 버튼으로 정상 화면이 돌아와야 한다.

- [ ] **Step 5: 요청 경합을 실제 UI에서 확인한다.**

Network Slow 3G에서 고객 검색어를 빠르게 바꾸고 일정 월을 3회 이동한다. 마지막 검색어·마지막 월만 남고 console에 unhandled rejection이 없어야 한다.

- [ ] **Step 6: 320px·390px 접근성 스모크를 수행한다.**

예약 설정, 고객 목록, 일정, 공개 토큰 5종에서 가로 넘침 0건, 키보드로 retry/save 접근 가능, 오류 안내가 색상만으로 표현되지 않는지 확인한다.

- [ ] **Step 7: diff와 동시 작업 충돌을 확인하고 PM 검토 지점에서 멈춘다.**

```bash
git diff --check
git status --short
```

랜딩·boards·Manager 요금제 파일이 Release 2 diff에 포함되지 않아야 한다. 커밋·Preview·Production은 별도 요청 전 실행하지 않는다.
