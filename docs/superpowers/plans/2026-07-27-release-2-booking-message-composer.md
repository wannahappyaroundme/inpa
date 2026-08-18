# Release 2 실제 고객 예약 문구·전체 링크 Composer 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 일정의 예약 설정 화면과 고객 상세에서 실제 등록 고객의 이름, 저장된 설계사 정보, 전체 `/b/<signed-token>` URL이 들어간 예약 안내를 만들고 정확히 복사한다.

**Architecture:** 백엔드 `templates_text.py`를 기본 예약 문구 렌더링의 단일 권위로 유지한다. 프런트는 고객 검색 picker, 실제 링크 생성·편집·복사를 담당하는 공용 `BookingMessageComposer`, 설정 저장 orchestration을 분리한다. 일정 화면은 dirty 설정을 먼저 PATCH한 뒤에만 booking request를 POST하며, 고객 상세 modal은 같은 composer에 미리 정해진 customer ID를 전달한다.

**Tech Stack:** Django 5.2/DRF, Next.js 16.2.9, React 19.2.4, TypeScript 5, Tailwind CSS 4, Vitest 4, Testing Library.

## Global Constraints

- 설계 SSOT는 `docs/superpowers/specs/2026-07-27-booking-message-composer-design.md`다.
- Release 1 `2026-07-27-release-1-public-signed-link-token-normalization.md`의 `/b` 정상화가 먼저 완료되어야 browser E2E를 통과할 수 있다.
- DB migration, booking token TTL, availability, Meeting 상태, 알림, Google Calendar 동기화는 변경하지 않는다.
- 고객명 free-text 링크는 만들지 않는다. owner-scoped 등록 고객 ID만 사용한다.
- 실제 메시지와 URL은 `BookingRequestResponse.message`, `booking_url`을 원문 권위로 사용한다.
- 프런트가 실제 메시지를 재조립하지 않는다.
- dirty 설정은 PATCH 성공 뒤에만 booking request를 POST한다. PATCH 실패 시 POST 호출은 0회다.
- 깨끗한 설정은 불필요한 PATCH 없이 booking request를 POST한다.
- 고객 변경 시 이전 고객의 메시지와 URL을 즉시 지운다.
- 생성 결과를 localStorage나 서버 설정에 저장하지 않는다. 화면을 다시 열거나 고객을 다시 선택하면 72시간 TTL의 새 링크를 만든다.
- `김보장`, `/b/…`, `고객이 받는 모습(예시)`를 서비스 화면에서 제거한다.
- 클립보드 실패를 성공으로 표시하지 않고, 메시지·URL은 직접 선택 가능하게 유지한다.
- 검색은 `listCustomers({ search, page: 1 })`만 사용하며 전체 고객 bulk fetch를 하지 않는다.
- 아래 커밋 단계는 PM이 별도로 요청한 경우에만 수행한다.

---

## File Structure

| 파일 | 책임 |
|---|---|
| `inpa_be/inpa/booking/templates_text.py` | 기본 문구와 `{소속직책}` optional spacing 단일 권위 |
| `inpa_be/inpa/booking/tests.py` | 실제 고객명·설계사 정보·전체 URL·owner/gate 회귀 |
| `inpa_fe/lib/booking-settings-state.ts` | profile ↔ 예약 설정 draft 변환, dirty 비교, PATCH payload |
| `inpa_fe/components/booking-customer-picker.tsx` | owner-scoped 고객 검색, 식별 정보, keyboard combobox |
| `inpa_fe/components/booking-message-composer.tsx` | prepare → booking POST → 편집·복사·열기 상태기계 |
| `inpa_fe/components/booking-settings.tsx` | 안전한 설정 load/save, 업무시간, picker와 composer 조합 |
| `inpa_fe/components/booking-modal.tsx` | modal shell, focus/Escape, 공용 composer 사용 |
| `inpa_fe/components/__tests__/booking-message-composer.test.tsx` | 생성 순서·원문·복사·stale·오류 회귀 |
| `inpa_fe/components/__tests__/booking-customer-picker.test.tsx` | debounce·latest-wins·empty/error·keyboard 회귀 |
| `inpa_fe/components/__tests__/booking-settings.test.tsx` | load/dirty/PATCH/가짜 preview 제거 통합 회귀 |
| `inpa_fe/components/__tests__/booking-modal.test.tsx` | 공용 composer·dialog focus 회귀 |

### Task 1: 백엔드 기본 예약 문구를 실제 설계사 정보까지 자연스럽게 렌더

**Files:**

- Modify: `inpa_be/inpa/booking/templates_text.py`
- Modify: `inpa_be/inpa/booking/tests.py`
- Verify: `inpa_be/inpa/booking/views.py::BookingRequestCreateView.post`

**Interfaces:**

- Preserves: `render_booking_message(template, customer_name, planner_name, url, planner_label="") -> str`
- Produces: default message includes customer, optional affiliation/title, planner, full URL
- Preserves: custom template placeholders `{고객명}`, `{소속직책}`, `{설계사명}`, `{링크}`

- [ ] **Step 1: 기본·custom 문구 RED 테스트를 작성한다.**

`BookingCoreTests`에 아래 네 테스트를 추가한다.

```python
@override_settings(FRONTEND_BASE_URL='https://www.inpa.kr')
def test_booking_request_default_message_contains_real_identity_and_full_url(self):
    self.profile_a.name = '황예진'
    self.profile_a.title = '팀장'
    self.profile_a.booking_msg_template = ''
    self.profile_a.save(update_fields=[
        'name', 'title', 'booking_msg_template',
    ])

    response = self.client_a.post(
        f'/api/v1/customers/{self.customer.id}/booking-requests/')
    self.assertEqual(response.status_code, 201)
    body = response.json()
    self.assertIn('홍길동 고객님', body['message'])
    self.assertIn('A생명 팀장 황예진 보험설계사입니다.', body['message'])
    self.assertTrue(body['booking_url'].startswith('https://www.inpa.kr/b/'))
    self.assertIn(body['booking_url'], body['message'])
```

```python
def test_booking_request_default_message_has_no_double_space_without_label(self):
    self.profile_a.name = '황예진'
    self.profile_a.affiliation = ''
    self.profile_a.title = ''
    self.profile_a.booking_msg_template = ''
    self.profile_a.save(update_fields=[
        'name', 'affiliation', 'title', 'booking_msg_template',
    ])

    body = self.client_a.post(
        f'/api/v1/customers/{self.customer.id}/booking-requests/').json()
    self.assertIn('안녕하세요. 황예진 보험설계사입니다.', body['message'])
    self.assertNotIn('안녕하세요.  황예진', body['message'])
```

```python
def test_booking_request_custom_template_keeps_optional_label_contract(self):
    self.profile_a.name = '황예진'
    self.profile_a.affiliation = ''
    self.profile_a.title = ''
    self.profile_a.booking_msg_template = (
        '{고객명}님, {소속직책} {설계사명}입니다.\n{링크}')
    self.profile_a.save(update_fields=[
        'name', 'affiliation', 'title', 'booking_msg_template',
    ])

    body = self.client_a.post(
        f'/api/v1/customers/{self.customer.id}/booking-requests/').json()
    self.assertIn('홍길동님, 황예진입니다.', body['message'])
    self.assertNotIn('  ', body['message'])
```

```python
def test_booking_request_leaves_no_known_placeholder(self):
    body = self.client_a.post(
        f'/api/v1/customers/{self.customer.id}/booking-requests/').json()
    for placeholder in ('{고객명}', '{소속직책}', '{설계사명}', '{링크}'):
        self.assertNotIn(placeholder, body['message'])
```

- [ ] **Step 2: RED를 확인한다.**

Run:

```bash
cd inpa_be
./venv/bin/python manage.py test inpa.booking.tests.BookingCoreTests -v 2
```

Expected: 현재 default가 소속·직책을 포함하지 않거나 custom template에서 연속 공백이 남아 새 테스트가 FAIL.

- [ ] **Step 3: default template에 optional label을 포함한다.**

```python
DEFAULT_BOOKING_MSG_TEMPLATE = (
    '{고객명} 고객님, 안녕하세요. {소속직책} {설계사명} 보험설계사입니다.\n'
    '가능하신 날짜를 선택해 주시면 자세한 보험 상담을 도와드리겠습니다.\n'
    '아래 링크에서 편하신 시간을 골라주세요 👇\n'
    '{링크}'
)
```

- [ ] **Step 4: `{소속직책}` 바로 뒤 한 칸을 optional 단위로 치환한다.**

```python
def render_booking_message(
        template, customer_name, planner_name, url, planner_label=''):
    text = template or DEFAULT_BOOKING_MSG_TEMPLATE
    label = (planner_label or '').strip()
    name = (planner_name or '').strip() or '담당 설계사'
    text = text.replace(
        '{소속직책} ',
        f'{label} ' if label else '',
    )
    return (text
            .replace('{고객명}', customer_name or '고객')
            .replace('{소속직책}', label)
            .replace('{설계사명}', name)
            .replace('{링크}', url))
```

이 구현은 기존 custom template의 placeholder 이름을 바꾸지 않고, 가장 흔한 `{소속직책} {설계사명}` 조합에서 빈 label 공백만 제거한다. 임의의 사용자 문장 전체 공백을 정규화하지 않는다.

- [ ] **Step 5: backend 예약 회귀를 GREEN으로 만든다.**

Run:

```bash
cd inpa_be
./venv/bin/python manage.py test inpa.booking.tests.BookingCoreTests -v 2
./venv/bin/python manage.py check
```

Expected: 실제 문구 테스트와 기존 owner isolation, gate, public booking 테스트 모두 PASS.

### Task 2: 예약 설정 draft와 dirty 판정 순수 모듈 추가

**Files:**

- Create: `inpa_fe/lib/booking-settings-state.ts`
- Create: `inpa_fe/components/__tests__/booking-settings.test.tsx`

**Interfaces:**

- Produces: `BookingSettingsDraft`
- Produces: `profileToBookingSettings(profile: ProfileResponse): BookingSettingsDraft`
- Produces: `bookingSettingsPayload(draft: BookingSettingsDraft): ProfileUpdatePayload`
- Produces: `isSameBookingSettings(left, right): boolean`

- [ ] **Step 1: trim·number·dirty RED 테스트를 작성한다.**

```tsx
const draft = {
  name: " 황예진 ",
  affiliation: " 부산지점 ",
  title: " FC ",
  template: "{고객명}님\n{링크}",
  location: " 서면 ",
  duration: 30,
  buffer: 60,
};

expect(bookingSettingsPayload(draft)).toEqual({
  name: "황예진",
  affiliation: "부산지점",
  title: "FC",
  booking_msg_template: "{고객명}님\n{링크}",
  booking_location: "서면",
  booking_default_duration: 30,
  booking_buffer_min: 60,
});

expect(isSameBookingSettings(draft, { ...draft })).toBe(true);
expect(isSameBookingSettings(draft, { ...draft, title: "팀장" })).toBe(false);
```

profile fixture에서 `null` affiliation과 빈 template가 각각 빈 문자열로 안전하게 변환되는 assertion도 추가한다.

- [ ] **Step 2: RED를 확인한다.**

Run:

```bash
cd inpa_fe
npm run test:run -- components/__tests__/booking-settings.test.tsx
```

Expected: 새 모듈이 없어 FAIL.

- [ ] **Step 3: exact draft와 payload 함수를 구현한다.**

```ts
export interface BookingSettingsDraft {
  name: string;
  affiliation: string;
  title: string;
  template: string;
  location: string;
  duration: number;
  buffer: number;
}
```

`isSameBookingSettings`는 `bookingSettingsPayload` 결과의 일곱 필드를 직접 비교한다. `JSON.stringify`나 Profile 전체 비교를 쓰지 않아 unrelated profile 변경이 dirty에 섞이지 않게 한다.

- [ ] **Step 4: 순수 함수 테스트를 GREEN으로 만든다.**

Run:

```bash
cd inpa_fe
npm run test:run -- components/__tests__/booking-settings.test.tsx
```

Expected: draft/payload/dirty assertion PASS.

### Task 3: owner-scoped 고객 검색 picker 구현

**Files:**

- Create: `inpa_fe/components/booking-customer-picker.tsx`
- Create: `inpa_fe/components/__tests__/booking-customer-picker.test.tsx`
- Consume: `inpa_fe/lib/api.ts::listCustomers`

**Interfaces:**

- Produces:

```ts
export interface BookingCustomerPickerProps {
  value: CustomerListItem | null;
  onChange: (customer: CustomerListItem | null) => void;
  disabled?: boolean;
}
```

- Search contract: `listCustomers({ page: 1, search: trimmed || undefined })`

- [ ] **Step 1: 검색·선택 RED 테스트를 작성한다.**

```tsx
render(<BookingCustomerPicker value={null} onChange={onChange} />);
await userEvent.setup().type(
  screen.getByRole("combobox", { name: "고객 선택" }),
  "김보",
);
await vi.advanceTimersByTimeAsync(300);
expect(listCustomers).toHaveBeenLastCalledWith({ page: 1, search: "김보" });
await userEvent.setup().click(
  await screen.findByRole("option", { name: /김보장/ }),
);
expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ id: 31 }));
```

테스트는 fake timer를 쓰며 `afterEach(() => vi.useRealTimers())`로 복구한다.

- [ ] **Step 2: latest-wins RED 테스트를 작성한다.**

`김` 검색 promise를 보류하고 `김보` 검색을 먼저 성공시킨 뒤, 늦은 `김` 응답을 resolve한다.

```tsx
expect(screen.getByRole("option", { name: /김보장/ })).toBeTruthy();
expect(screen.queryByRole("option", { name: /김이전/ })).toBeNull();
```

- [ ] **Step 3: empty/error/keyboard RED 테스트를 작성한다.**

검증 항목:

```text
첫 빈 검색 결과 0건 -> 고객을 먼저 추가하면 바로 예약 안내를 만들 수 있어요.
고객 추가하기 -> /customers
검색 실패 -> 다시 불러오기
ArrowDown/ArrowUp -> active descendant 이동
Enter -> active option 선택
Escape -> listbox 닫기
선택 행 -> 고객명, 전화번호 일부 마스킹, DB/TA/FA/청약 표시
```

전화번호는 `010-****-5678` 형식으로 표시하고 전체 번호를 combobox 결과 DOM에 렌더하지 않는다.

- [ ] **Step 4: 300ms debounce와 request generation guard를 구현한다.**

핵심 상태:

```ts
const [query, setQuery] = useState("");
const [results, setResults] = useState<CustomerListItem[]>([]);
const [status, setStatus] = useState<"idle" | "loading" | "success" | "error">("idle");
const [activeIndex, setActiveIndex] = useState(-1);
const requestGeneration = useRef(0);
```

요청마다 generation을 증가시키고 현재 번호인 응답만 반영한다. unmount에서도 증가시켜 늦은 응답을 폐기한다. 빈 검색은 작은 첫 페이지를 요청하며 `listAllCustomers`를 호출하지 않는다.

- [ ] **Step 5: combobox 접근성 계약을 구현한다.**

```text
input role=combobox, aria-label=고객 선택
aria-expanded, aria-controls, aria-activedescendant
results role=listbox
row role=option, aria-selected
loading role=status
error role=alert
```

선택 후 입력에는 고객명이 보이고, 새 검색을 시작하면 기존 generated message는 상위 `onChange`를 통해 제거될 수 있게 한다.

- [ ] **Step 6: picker 테스트를 GREEN으로 만든다.**

Run:

```bash
cd inpa_fe
npm run test:run -- components/__tests__/booking-customer-picker.test.tsx
```

Expected: search, generation guard, empty/error, keyboard, PII masking assertion PASS.

### Task 4: 실제 문구 생성·편집·복사 공용 Composer 구현

**Files:**

- Create: `inpa_fe/components/booking-message-composer.tsx`
- Create: `inpa_fe/components/__tests__/booking-message-composer.test.tsx`
- Consume: `inpa_fe/lib/api.ts::createBookingRequest`
- Consume: `inpa_fe/lib/clipboard.ts::copyText`

**Interfaces:**

- Produces:

```ts
export interface BookingMessageComposerProps {
  customerId: number | null;
  prepare?: () => Promise<void>;
  disabled?: boolean;
}
```

- State contract: `idle | preparing | generating | success | error`

- [ ] **Step 1: prepare → POST 순서 RED 테스트를 작성한다.**

```tsx
const order: string[] = [];
const prepare = vi.fn(async () => {
  order.push("prepare");
});
vi.mocked(createBookingRequest).mockImplementation(async () => {
  order.push("create");
  return {
    token: "signed:token",
    booking_url: "https://www.inpa.kr/b/signed:token",
    message: "김보장 고객님, 황예진 보험설계사입니다.\nhttps://www.inpa.kr/b/signed:token",
  };
});

render(<BookingMessageComposer customerId={31} prepare={prepare} />);
await userEvent.setup().click(
  screen.getByRole("button", { name: "고객에게 보낼 문구 만들기" }),
);
await waitFor(() => expect(order).toEqual(["prepare", "create"]));
expect(createBookingRequest).toHaveBeenCalledWith(31);
```

- [ ] **Step 2: prepare 실패 시 POST 0회 RED 테스트를 작성한다.**

```tsx
const prepare = vi.fn().mockRejectedValue(new Error("SAVE_FAILED"));
render(<BookingMessageComposer customerId={31} prepare={prepare} />);
await userEvent.setup().click(
  screen.getByRole("button", { name: "고객에게 보낼 문구 만들기" }),
);
expect(await screen.findByText("예약 설정을 다시 저장해 주세요.")).toBeTruthy();
expect(createBookingRequest).not.toHaveBeenCalled();
```

- [ ] **Step 3: 서버 원문·편집·복사 RED 테스트를 작성한다.**

검증:

```tsx
expect(screen.getByDisplayValue(serverResponse.message)).toBeTruthy();
expect(screen.getByText(serverResponse.booking_url)).toBeTruthy();

await userEvent.setup().clear(screen.getByLabelText("고객에게 보낼 메시지"));
await userEvent.setup().type(
  screen.getByLabelText("고객에게 보낼 메시지"),
  "편집한 실제 메시지",
);
await userEvent.setup().click(
  screen.getByRole("button", { name: "메시지 전체 복사" }),
);
expect(copyText).toHaveBeenCalledWith("편집한 실제 메시지");

await userEvent.setup().click(
  screen.getByRole("button", { name: "링크만 복사" }),
);
expect(copyText).toHaveBeenCalledWith(serverResponse.booking_url);
```

- [ ] **Step 4: copy failure와 고객 변경 RED 테스트를 작성한다.**

`copyText`가 `false`를 반환하면 `복사하지 못했어요. 문구를 길게 눌러 직접 복사해 주세요.`가 `role=alert`로 보이고 성공 문구는 없어야 한다.

customerId 31의 POST를 보류한 채 32로 rerender한 뒤 31 응답을 resolve한다.

```tsx
expect(screen.queryByText(/customer-31-token/)).toBeNull();
expect(screen.getByRole("button", {
  name: "고객에게 보낼 문구 만들기",
})).toBeTruthy();
```

- [ ] **Step 5: 공용 composer 상태기계를 구현한다.**

구현 규칙:

```text
customerId null -> CTA disabled, 고객 선택 안내
generate 중 -> 중복 클릭 차단
prepare resolve -> createBookingRequest
prepare reject -> settings error, create 호출 없음
create reject -> 고객 선택 유지, 다시 만들기
success -> editable textarea + full immutable URL + three actions
customerId change -> generation invalidation, message/url/error/copy state 초기화
unmount -> timer와 generation 폐기
```

성공 UI:

```text
고객에게 보낼 메시지
메시지 전체 복사
링크만 복사
고객 화면 열기
```

URL은 `overflow-wrap:anywhere`와 `select-text`를 사용한다. 세 action은 최소 높이 44px을 지킨다. status는 `aria-live=polite`, 오류는 `role=alert`로 표시한다.

- [ ] **Step 6: composer 테스트를 GREEN으로 만든다.**

Run:

```bash
cd inpa_fe
npm run test:run -- components/__tests__/booking-message-composer.test.tsx
```

Expected: 호출 순서, POST 차단, 원문, 편집 copy, URL copy, copy failure, stale response PASS.

### Task 5: BookingSettings를 안전한 load/save + 실제 고객 작업 화면으로 변경

**Files:**

- Modify: `inpa_fe/components/booking-settings.tsx`
- Modify: `inpa_fe/components/__tests__/booking-settings.test.tsx`
- Consume: `BookingCustomerPicker`
- Consume: `BookingMessageComposer`
- Consume: booking settings state helpers

**Interfaces:**

- Produces: `saveSettings(options?: { announce?: boolean }): Promise<void>`
- Provides to composer: `prepare={saveDirtySettings}`
- Preserves: WorkHour CRUD, duration, buffer, location settings

- [ ] **Step 1: profile load 상태 RED 테스트를 작성한다.**

검증:

```text
loading -> 실제 input 대신 skeleton, 저장·생성 비활성
load failure -> 빈 값이 저장된 것처럼 보이지 않고 다시 불러오기
retry success -> 서버 profile 값 렌더
```

`getProfile` 실패 후 `updateProfile`, `createBookingRequest` 호출은 0회다.

- [ ] **Step 2: clean/dirty 저장 순서 RED 테스트를 작성한다.**

dirty 설정:

```tsx
expect(updateProfile.mock.invocationCallOrder[0])
  .toBeLessThan(createBookingRequest.mock.invocationCallOrder[0]);
```

clean 설정:

```tsx
expect(updateProfile).not.toHaveBeenCalled();
expect(createBookingRequest).toHaveBeenCalledWith(31);
```

PATCH reject:

```tsx
expect(createBookingRequest).not.toHaveBeenCalled();
expect(screen.getByDisplayValue("수정 중인 이름")).toBeTruthy();
```

- [ ] **Step 3: fake preview 제거 RED 테스트를 작성한다.**

```tsx
render(<BookingSettings />);
await screen.findByDisplayValue("황예진");
expect(screen.queryByText(/고객이 받는 모습/)).toBeNull();
expect(screen.queryByText(/김보장/)).toBeNull();
expect(screen.queryByText(/\/b\/…/)).toBeNull();
expect(screen.getByText("고객에게 예약 안내 보내기")).toBeTruthy();
```

- [ ] **Step 4: profile load와 snapshot을 명시적 상태로 구현한다.**

```ts
type ProfileLoadStatus = "loading" | "success" | "error";
const [draft, setDraft] = useState<BookingSettingsDraft | null>(null);
const [savedSnapshot, setSavedSnapshot] =
  useState<BookingSettingsDraft | null>(null);
```

성공 때 같은 변환 결과를 draft와 snapshot에 넣는다. 실패 때 draft를 기본값으로 만들지 않는다. retry는 `getProfile()`을 다시 호출한다.

- [ ] **Step 5: save 함수가 서버 응답으로 snapshot을 갱신하게 한다.**

```ts
async function saveSettings({ announce = true } = {}): Promise<void> {
  if (!draft || !savedSnapshot) throw new Error("PROFILE_NOT_READY");
  if (isSameBookingSettings(draft, savedSnapshot)) {
    if (announce) setMessage("저장된 설정이에요.");
    return;
  }
  const updated = await updateProfile(bookingSettingsPayload(draft));
  const nextSnapshot = profileToBookingSettings(updated);
  setDraft(nextSnapshot);
  setSavedSnapshot(nextSnapshot);
  if (announce) setMessage("예약 설정을 저장했어요.");
}
```

composer에는 `prepare={() => saveSettings({ announce: false })}`를 전달한다. 저장 실패는 throw해 composer가 POST를 막도록 한다.

- [ ] **Step 6: 두 화면 구역을 렌더한다.**

구역 1 `예약 기본 설정`:

```text
내 이름, 소속, 직책
예약 안내 문구
업무시간
대면 미팅 장소
미팅 시간
앞뒤 여유
예약 설정 저장
```

구역 2 `고객에게 예약 안내 보내기`:

```text
BookingCustomerPicker
선택 고객 식별 행
BookingMessageComposer
```

고객을 새로 선택하면 `selectedCustomer`를 바꾸며 composer의 customerId 변경으로 이전 결과를 즉시 제거한다. 고객이 없으면 `/customers`의 `고객 추가하기` 링크를 제공한다.

프런트의 기본 문구 상수는 `DEFAULT_TPL_PLACEHOLDER`처럼 실제 생성에 쓰이지 않는 이름으로 바꾸고 textarea placeholder에만 사용한다. 문구 생성은 항상 backend response를 사용한다.

- [ ] **Step 7: WorkHour 오류 상태도 복구 행동을 제공한다.**

`listWorkHours` 실패를 빈 업무시간으로 위장하지 않는다. `업무시간을 불러오지 못했어요.`와 `다시 불러오기`를 표시한다. delete 실패는 optimistic 제거 뒤 목록 재조회에 실패하면 오류를 표시해 사용자가 현재 서버 상태를 다시 확인할 수 있게 한다.

- [ ] **Step 8: BookingSettings 테스트를 GREEN으로 만든다.**

Run:

```bash
cd inpa_fe
npm run test:run -- components/__tests__/booking-settings.test.tsx components/__tests__/booking-customer-picker.test.tsx components/__tests__/booking-message-composer.test.tsx
```

Expected: profile load, dirty ordering, fake preview removal, work-hour retry, customer generation PASS.

### Task 6: 고객 상세 BookingModal을 같은 Composer shell로 축소

**Files:**

- Modify: `inpa_fe/components/booking-modal.tsx`
- Create: `inpa_fe/components/__tests__/booking-modal.test.tsx`

**Interfaces:**

- Preserves: `BookingModal({ customerId, onClose })`
- Consumes: `BookingMessageComposer customerId={customerId}`
- Produces: Escape/close/focus restoration

- [ ] **Step 1: 공용 composer와 modal 접근성 RED 테스트를 작성한다.**

검증:

```text
dialog aria-labelledby가 실제 제목을 가리킴
열릴 때 첫 조작 요소에 focus
Escape -> onClose 1회
Tab/Shift+Tab -> dialog 안에서 순환
닫힐 때 열기 전 activeElement로 focus 복귀
createBookingRequest는 composer를 통해 customerId로 호출
clipboard 실패 안내는 일정 화면과 같은 문구
```

- [ ] **Step 2: modal 내부 생성·copy 중복 코드를 제거한다.**

modal은 다음만 담당한다.

```text
backdrop
dialog title와 설명
BookingMessageComposer
닫기
focus capture/trap/restore
Escape
```

`navigator.clipboard.writeText` 직접 호출과 silent catch를 삭제한다.

- [ ] **Step 3: modal 테스트를 GREEN으로 만든다.**

Run:

```bash
cd inpa_fe
npm run test:run -- components/__tests__/booking-modal.test.tsx components/__tests__/booking-message-composer.test.tsx
```

Expected: modal shell과 공용 composer assertion PASS.

### Task 7: 카피·전체 테스트·브라우저 E2E 검증

**Files:**

- Verify: all booking files
- Verify: `inpa_fe/app/schedule/page.tsx`
- Verify: `inpa_fe/app/customer/[id]/page.tsx`

- [ ] **Step 1: fake/placeholder 카피 정적 검사를 실행한다.**

Run:

```bash
cd inpa_fe
rg -n "김보장|고객이 받는 모습\\(예시\\)|/b/…|https://www\\.inpa\\.kr/b/…" components/booking-settings.tsx components/booking-message-composer.tsx components/booking-modal.tsx
```

Expected: 0건.

테스트 fixture의 실제 URL은 허용하지만 렌더 소스에 줄임표 URL을 두지 않는다.

- [ ] **Step 2: 프런트 전체 게이트를 실행한다.**

Run:

```bash
cd inpa_fe
npm run test:unit
npm run test:run
npm run lint:copy
npm run build
```

Expected: 모두 PASS.

- [ ] **Step 3: backend 전체 예약 회귀를 실행한다.**

Run:

```bash
cd inpa_be
./venv/bin/python manage.py check
./venv/bin/python manage.py test inpa.booking -v 2
```

Expected: 전체 booking PASS, migration 변경 0건.

- [ ] **Step 4: 로컬 브라우저 E2E를 실제 테스트 고객으로 수행한다.**

준비:

```text
설계사 이름: 황예진
소속: 부산지점
직책: FC
등록 고객: 로컬 테스트 고객 1명
업무시간: 다음 영업일 09:00~18:00
미팅 시간: 30분
앞뒤 여유: 60분
```

흐름:

```text
1. /schedule에서 예약 설정 로드
2. 소속·직책을 수정한 채 저장 버튼을 따로 누르지 않음
3. 실제 등록 고객 검색·선택
4. 고객에게 보낼 문구 만들기
5. Network에서 PATCH /auth/profile/ 뒤 POST /booking-requests/ 순서 확인
6. textarea에 실제 고객명, 부산지점 FC, 황예진, full /b token 확인
7. 메시지 전체 복사와 링크만 복사의 clipboard 원문 확인
8. 고객 화면 열기로 /b 링크 정상 표시
9. 시간·상담 방식 선택 후 예약 요청
10. 설계사 알림에서 수락
11. /schedule 일정 반영 확인
```

- [ ] **Step 5: 실패 주입을 브라우저에서 확인한다.**

```text
profile GET 500 -> retry 뒤 복구
profile PATCH 500 -> 입력 보존, booking POST 없음
customer search 500 -> picker 안 retry
booking POST 500 -> 고객 선택 보존, 다시 만들기
clipboard permission deny -> 성공 표시 없음, 직접 복사 안내
mobile 390px -> URL 가로 넘침 없음, action 높이 44px 이상
```

- [ ] **Step 6: PM이 커밋을 요청한 경우에만 Release 2 변경을 커밋한다.**

```bash
git add inpa_be/inpa/booking/templates_text.py inpa_be/inpa/booking/tests.py inpa_fe/lib/booking-settings-state.ts inpa_fe/components/booking-customer-picker.tsx inpa_fe/components/booking-message-composer.tsx inpa_fe/components/booking-settings.tsx inpa_fe/components/booking-modal.tsx inpa_fe/components/__tests__/booking-customer-picker.test.tsx inpa_fe/components/__tests__/booking-message-composer.test.tsx inpa_fe/components/__tests__/booking-settings.test.tsx inpa_fe/components/__tests__/booking-modal.test.tsx
git commit -m "feat(예약): 실제 고객 안내 문구와 전체 링크 생성"
```

## Release 2 완료 증거

```text
Changed: 서버 권위 예약 문구, 등록 고객 검색, 공용 composer, 설정 저장 후 생성
Verified by: Django booking test, Vitest components, copy lint, Next build, local booking E2E
Result: 실제 고객명·설계사 정보·full URL 표시와 복사, fake preview 0건, PATCH 실패 시 POST 0회
Unverified: 자동 문자·카카오 발송은 설계 비목표라 구현하지 않음
```
