# Release 3 여러 증권 양쪽 중복 선택 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 고객의 분석 가능한 모든 증권을 한 카드 목록에서 왼쪽·오른쪽에 독립 선택하고, `A1+A2+A3` 대 `A1+A2+B1`처럼 같은 실제 증권을 양쪽에 포함해 비교한다.

**Architecture:** `lib/policy-comparison-selection.ts`가 독립 boolean 선택, 초기 preset, refresh reconciliation, 정렬된 API ID 배열, snapshot 동등성의 단일 권위를 맡는다. `AssignInsRow`는 선택 가능한 한 카드에 두 개의 `aria-pressed` 버튼을 렌더한다. `SwitchTab`은 선택 UI와 결과 상태를 분리하고 명시적 CTA에서만 compare API를 호출하며, 마지막 성공 snapshot과 현재 선택이 다르면 결과 표시와 복사를 잠근다.

**Tech Stack:** Next.js 16.2.9, React 19.2.4, TypeScript 5, Tailwind CSS 4, Vitest 4, Django 5.2/DRF.

## Global Constraints

- 설계 SSOT는 `docs/superpowers/specs/2026-07-27-multi-policy-overlap-selection-design.md`다.
- DB migration과 compare response shape를 변경하지 않는다.
- 내부 API `side_a_ids`, `side_b_ids`, response `current`, `proposed`는 하위호환을 위해 유지한다.
- 화면·복사·FAQ·landing에서 `왼쪽 구성`, `오른쪽 구성`을 사용한다.
- 사용자 화면의 `증권 A`, `증권 B`, `비교 묶음 A`, `비교 묶음 B`를 제거한다.
- 저장 분류 `portfolio_type`은 초기 preset에만 쓰며 사용자의 현재 비교 선택으로 표시하지 않는다.
- `portfolio_type=1` 신규 ID는 양쪽 선택, `portfolio_type=2` 신규 ID는 오른쪽만 선택한다.
- refresh 때 기존 ID의 left/right 선택을 보존하고 새 ID에만 preset을 적용한다.
- canceled, review 전, analysis 제외 보험은 양쪽 모두 선택할 수 없다.
- 한쪽 빈 구성과 완전히 같은 구성은 API를 호출하지 않는다.
- 토글은 API를 호출하지 않고 `선택한 구성 비교하기`만 호출한다.
- 선택 UI는 compare loading, 400/500, 402 중에도 유지한다.
- 마지막 성공 snapshot과 현재 선택이 다르면 이전 결과 본문과 복사를 잠근다.
- compare 계산의 중립성, 권유 금지, AI/publish gate는 변경하지 않는다.
- 아래 커밋 단계는 PM이 별도로 요청한 경우에만 수행한다.

---

## File Structure

| 파일 | 책임 |
|---|---|
| `inpa_fe/lib/policy-comparison-selection.ts` | 선택 type, preset, refresh reconciliation, ID snapshot |
| `inpa_fe/components/__tests__/policy-comparison-selection.test.tsx` | 순수 선택 모델 회귀 |
| `inpa_fe/components/insurance-review-cards.tsx` | 한 카드의 왼쪽·오른쪽 독립 버튼과 확인 상태 |
| `inpa_fe/components/__tests__/insurance-review-authority.test.tsx` | disabled/review/양쪽 선택 카드 회귀 |
| `inpa_fe/app/customer/[id]/page.tsx::SwitchTab` | 목록·선택·명시 실행·stale·error/402 orchestration |
| `inpa_fe/components/__tests__/multi-policy-overlap-selection.test.tsx` | 실제 SwitchTab 흐름과 payload 회귀 |
| `inpa_fe/components/charts.tsx` | 비교 막대 accessible label의 왼쪽/오른쪽 주입 |
| `inpa_fe/components/premium-split.tsx` | 보험료 표 기본 label |
| `inpa_fe/lib/compare-export.ts` | 고객 복사 텍스트의 왼쪽/오른쪽 label |
| `inpa_fe/components/__tests__/neutral-policy-comparison.test.tsx` | 결과·복사 중립 카피 회귀 |
| `inpa_be/inpa/analysis/tests.py` | 겹치는 ID의 양쪽 집계와 3 대 3 구성 회귀 |
| `inpa_be/inpa/analysis/compare.py` | invalid selection 사용자 detail의 왼쪽/오른쪽 카피 |
| `inpa_be/inpa/boards/management/commands/seed_boards.py` | untouched 공식 FAQ만 새 용어로 갱신 |
| `inpa_be/inpa/boards/tests.py` | FAQ 관리자 편집 보존과 새 용어 회귀 |
| `inpa_fe/scripts/check-copy.js` | 비교 노출면의 폐기 용어 재유입 차단 |
| `inpa_fe/scripts/check-copy.test.js` | 폐기 용어 rule과 comment/internal-key 예외 회귀 |
| `inpa_fe/package.json` | copy-lint rule test 실행 명령 |
| `.github/workflows/ci.yml` | copy guard rule test를 FE CI에 연결 |
| `inpa_fe/public/landing-test/compare.webp` | 실제 새 비교 화면 재촬영 |

### Task 1: 독립 선택 모델과 refresh 불변식 추가

**Files:**

- Create: `inpa_fe/lib/policy-comparison-selection.ts`
- Create: `inpa_fe/components/__tests__/policy-comparison-selection.test.tsx`
- Consume: `inpa_fe/lib/api.ts::ManualInsuranceItem`

**Interfaces:**

- Produces:

```ts
export type ComparisonSide = "left" | "right";

export interface PolicySideSelection {
  left: boolean;
  right: boolean;
}

export type PolicySelectionMap = Record<number, PolicySideSelection>;

export interface PolicySelectionSnapshot {
  leftIds: number[];
  rightIds: number[];
}
```

- Produces:

```ts
isPolicyComparisonSelectable(item: ManualInsuranceItem): boolean
reconcilePolicySelection(
  items: ManualInsuranceItem[],
  previous: PolicySelectionMap,
): PolicySelectionMap
buildPolicySelectionSnapshot(selection: PolicySelectionMap): PolicySelectionSnapshot
isSamePolicyIdSet(left: number[], right: number[]): boolean
isSamePolicySelectionSnapshot(
  left: PolicySelectionSnapshot,
  right: PolicySelectionSnapshot,
): boolean
```

- [ ] **Step 1: 초기 preset RED 테스트를 작성한다.**

네 보험 fixture:

```tsx
const a1 = insurance({ id: 1, portfolio_type: 1 });
const a2 = insurance({ id: 2, portfolio_type: 1 });
const a3 = insurance({ id: 3, portfolio_type: 1 });
const b1 = insurance({ id: 4, portfolio_type: 2 });

expect(reconcilePolicySelection([a1, a2, a3, b1], {})).toEqual({
  1: { left: true, right: true },
  2: { left: true, right: true },
  3: { left: true, right: true },
  4: { left: false, right: true },
});
```

- [ ] **Step 2: disabled와 refresh 보존 RED 테스트를 작성한다.**

```tsx
const previous = {
  1: { left: true, right: true },
  2: { left: true, right: false },
};
const refreshed = [
  insurance({ id: 1, portfolio_type: 1 }),
  insurance({ id: 2, portfolio_type: 1 }),
  insurance({ id: 3, portfolio_type: 2 }),
  insurance({ id: 4, portfolio_type: 1, is_cancelled: true }),
];

expect(reconcilePolicySelection(refreshed, previous)).toEqual({
  1: { left: true, right: true },
  2: { left: true, right: false },
  3: { left: false, right: true },
  4: { left: false, right: false },
});
```

`review_status !== "confirmed"`와 `analysis_included=false`도 양쪽 false인지 assertion한다.

- [ ] **Step 3: snapshot·동일 구성 RED 테스트를 작성한다.**

```tsx
const snapshot = buildPolicySelectionSnapshot({
  3: { left: true, right: false },
  1: { left: true, right: true },
  4: { left: false, right: true },
  2: { left: true, right: true },
});

expect(snapshot).toEqual({
  leftIds: [1, 2, 3],
  rightIds: [1, 2, 4],
});
expect(isSamePolicyIdSet([3, 1, 2], [2, 3, 1])).toBe(true);
expect(isSamePolicyIdSet([1, 2, 3], [1, 2, 4])).toBe(false);
```

- [ ] **Step 4: RED를 확인한다.**

Run:

```bash
cd inpa_fe
npm run test:run -- components/__tests__/policy-comparison-selection.test.tsx
```

Expected: 새 selection 모듈이 없어 FAIL.

- [ ] **Step 5: preset과 reconciliation을 구현한다.**

```ts
export function isPolicyComparisonSelectable(
  item: ManualInsuranceItem,
): boolean {
  return (
    item.review_status === "confirmed"
    && item.analysis_included
    && !item.is_cancelled
  );
}

function initialSelection(item: ManualInsuranceItem): PolicySideSelection {
  if (!isPolicyComparisonSelectable(item)) {
    return { left: false, right: false };
  }
  if (item.portfolio_type === 1) {
    return { left: true, right: true };
  }
  if (item.portfolio_type === 2) {
    return { left: false, right: true };
  }
  return { left: false, right: false };
}
```

`reconcilePolicySelection`은 현재 rows에 있는 ID만 반환한다. 선택 불가로 바뀐 ID는 previous와 관계없이 양쪽 false로 강제한다. 선택 가능한 기존 ID는 false 값까지 그대로 보존한다.

- [ ] **Step 6: snapshot을 ID 오름차순으로 고정한다.**

정렬은 API 의미를 바꾸기 위한 것이 아니라 동일 snapshot 비교와 테스트 재현성을 위한 것이다. 입력 map을 mutate하지 않고 새 배열을 반환한다.

- [ ] **Step 7: 순수 함수 테스트를 GREEN으로 만든다.**

Run:

```bash
cd inpa_fe
npm run test:run -- components/__tests__/policy-comparison-selection.test.tsx
```

Expected: preset, disabled, refresh, sorted snapshot, set equality PASS.

### Task 2: 한 카드에 왼쪽·오른쪽 독립 선택 구현

**Files:**

- Modify: `inpa_fe/components/insurance-review-cards.tsx`
- Modify: `inpa_fe/components/__tests__/insurance-review-authority.test.tsx`

**Interfaces:**

- Removes: `SideAssign = "A" | "B" | "none"`
- Produces:

```ts
export function AssignInsRow(props: {
  it: ManualInsuranceItem;
  value: PolicySideSelection;
  onChange: (value: PolicySideSelection) => void;
  onReview?: (insuranceId: number) => void;
}): React.ReactNode
```

- [ ] **Step 1: 양쪽 동시 선택 RED 테스트를 작성한다.**

```tsx
const onChange = vi.fn();
render(
  <AssignInsRow
    it={insurance({ id: 1, name: "A1" })}
    value={{ left: true, right: false }}
    onChange={onChange}
  />,
);

await userEvent.setup().click(
  screen.getByRole("button", { name: "A1 오른쪽에 포함" }),
);
expect(onChange).toHaveBeenCalledWith({ left: true, right: true });
```

왼쪽 해제는 `{left:false,right:false}`, 양쪽 선택 상태에서 왼쪽 해제는 `{left:false,right:true}`를 반환하는 assertion도 추가한다.

- [ ] **Step 2: accessible/disabled/양쪽 상태 RED 테스트를 작성한다.**

검증:

```text
왼쪽 버튼 aria-pressed=true
오른쪽 버튼 aria-pressed=true
양쪽 포함 텍스트 badge 표시
버튼 accessible name에 증권명+방향 포함
review 전 보험은 두 버튼 disabled
review action은 기존처럼 노출
두 버튼 min-height 44px
비교 제외 단일 선택 버튼 없음
비교 묶음 A/B badge 없음
```

- [ ] **Step 3: 카드 props와 렌더를 독립 boolean으로 변경한다.**

버튼 동작:

```ts
onChange({ ...value, left: !value.left });
onChange({ ...value, right: !value.right });
```

사용자에게 보이는 저장 분류 badge는 선택 상태와 혼동되므로 제거한다. 카드의 사실 정보는 보험사·증권명, 계약자·피보험자, 월 보험료, 계약 기간, 분석 포함/확인 필요 상태만 유지한다.

- [ ] **Step 4: 카드 테스트를 GREEN으로 만든다.**

Run:

```bash
cd inpa_fe
npm run test:run -- components/__tests__/insurance-review-authority.test.tsx
```

Expected: 독립 toggle, 양쪽 포함, disabled/review PASS.

### Task 3: SwitchTab을 명시 실행·stale-safe 상태기계로 변경

**Files:**

- Modify: `inpa_fe/app/customer/[id]/page.tsx`
- Create: `inpa_fe/components/__tests__/multi-policy-overlap-selection.test.tsx`
- Consume: selection module
- Consume: `compareCustomer(customerId, { sideAIds, sideBIds })`

**Interfaces:**

- Produces:

```ts
type CompareRunStatus = "idle" | "loading" | "success" | "error";

interface SuccessfulComparison {
  data: CompareResponse;
  snapshot: PolicySelectionSnapshot;
}
```

- Preserves: `compareReqRef` latest-request guard
- Produces: testable named export `SwitchTab`

- [ ] **Step 1: 실제 3+1 preset과 payload RED 테스트를 작성한다.**

`listAllManualInsurances`가 A1, A2, A3 `portfolio_type=1`, B1 `portfolio_type=2`를 반환하게 한다.

초기 assertion:

```text
왼쪽 구성 3개
오른쪽 구성 4개
비교 API 자동 호출 0회
```

오른쪽 A3 버튼을 눌러 해제하고 CTA를 누른 뒤:

```tsx
expect(compareCustomer).toHaveBeenCalledWith(77, {
  sideAIds: [1, 2, 3],
  sideBIds: [1, 2, 4],
});
```

- [ ] **Step 2: invalid selection API 0회 RED 테스트를 작성한다.**

두 경우를 각각 만든다.

```text
왼쪽 0개 -> 왼쪽 구성에 증권을 골라 주세요.
양쪽 ID set 동일 -> 오른쪽 구성을 조정하면 차이를 볼 수 있어요.
```

각 경우 `compareCustomer` 호출은 0회고 CTA는 비활성 또는 local guard로 종료해야 한다.

- [ ] **Step 3: 오류·402 중 카드 유지 RED 테스트를 작성한다.**

compare 500:

```tsx
expect(await screen.findByText("비교 내용을 불러오지 못했어요.")).toBeTruthy();
expect(screen.getByRole("button", { name: "A1 왼쪽에 포함" })).toBeTruthy();
expect(screen.getByRole("button", { name: "선택한 구성 비교하기" })).toBeTruthy();
```

402:

```text
UpgradeModal open
네 보험 카드 계속 렌더
선택 count 보존
안내 닫은 뒤 다시 비교 가능
```

- [ ] **Step 4: 선택 변경과 늦은 응답 RED 테스트를 작성한다.**

첫 비교 성공 뒤 A3 선택을 바꾸면:

```text
선택이 바뀌었어요. 다시 비교하면 새 구성으로 결과를 볼 수 있어요.
이전 결과 본문 숨김
증권 비교표 내용 복사 disabled
```

비교 요청을 보류한 상태에서 토글을 바꾸고 과거 응답을 resolve하면 과거 표가 렌더되지 않아야 한다.

- [ ] **Step 5: refresh 보존 RED 테스트를 작성한다.**

A3 오른쪽을 해제한 뒤 증권 추가 refresh에서 B2가 새로 들어오게 한다.

```text
A3 오른쪽=false 보존
B2 오른쪽=true preset
기존 결과 stale
비교 API 자동 호출 0회
```

- [ ] **Step 6: 목록과 비교 상태를 분리해 구현한다.**

state:

```ts
const [selection, setSelection] = useState<PolicySelectionMap>({});
const [compareStatus, setCompareStatus] =
  useState<CompareRunStatus>("idle");
const [successfulComparison, setSuccessfulComparison] =
  useState<SuccessfulComparison | null>(null);
const [compareError, setCompareError] = useState<string | null>(null);
```

목록 load 성공 때 `reconcilePolicySelection(rows, previous)`만 수행한다. 기존 자동 `useEffect(() => doCompare())`를 삭제한다.

`SwitchTab`은 default page 동작을 바꾸지 않는 named export로 전환해 통합 테스트가 실제 orchestration을 렌더하도록 한다.

- [ ] **Step 7: toggle이 in-flight 결과를 무효화하게 한다.**

각 카드의 `onChange`에서:

```text
selection 갱신
compareReqRef 증가
compareStatus idle
compareError 제거
upgrade modal 상태 정리
```

마지막 성공 결과는 snapshot과 함께 보관하지만, 현재 snapshot이 다르면 결과 본문과 copy를 렌더하지 않는다.

- [ ] **Step 8: 명시 CTA에서 snapshot을 고정하고 API를 호출한다.**

```ts
const snapshot = buildPolicySelectionSnapshot(selection);
if (snapshot.leftIds.length === 0) return;
if (snapshot.rightIds.length === 0) return;
if (isSamePolicyIdSet(snapshot.leftIds, snapshot.rightIds)) return;
```

요청 성공 때만 `{data, snapshot}`을 저장한다. 실패 때 선택과 이전 snapshot은 보존하되 현재 선택 결과로 표시하지 않는다. 402는 modal state만 열고 selector를 return으로 교체하지 않는다.

- [ ] **Step 9: 구성 요약과 CTA를 구현한다.**

카드 목록 위:

```text
왼쪽 구성 N개
오른쪽 구성 N개
선택된 증권 이름 chip
```

동명이 있을 수 있으므로 chip key는 insurance ID다. 모바일에서는 첫 두 이름과 `외 N개`를 사용하며 전체 목록은 접근 가능한 텍스트로 남긴다.

카드 목록 아래:

```text
선택한 구성 비교하기
```

비교 중에는 `비교하고 있어요`로 바꾸고 중복 클릭만 막는다. 카드 자체는 계속 조작 가능하며 조작 시 진행 중 응답은 폐기한다.

아직 비교하지 않은 idle 결과 영역에는 `왼쪽과 오른쪽 구성을 확인한 뒤 비교해 주세요.`를 표시한다. 한쪽 빈 구성, 동일 구성, stale, API 오류는 이 결과 영역에서 다음 행동을 안내하며 카드 목록을 교체하지 않는다.

- [ ] **Step 10: SwitchTab 통합 테스트를 GREEN으로 만든다.**

Run:

```bash
cd inpa_fe
npm run test:run -- components/__tests__/multi-policy-overlap-selection.test.tsx components/__tests__/policy-comparison-selection.test.tsx components/__tests__/insurance-review-authority.test.tsx
```

Expected: 3+1 payload, invalid no-call, error/402 persistence, stale blocking, refresh preservation PASS.

### Task 4: 결과·차트·복사 문구를 왼쪽/오른쪽으로 통일

**Files:**

- Modify: `inpa_fe/app/customer/[id]/page.tsx`
- Modify: `inpa_fe/components/charts.tsx`
- Modify: `inpa_fe/components/premium-split.tsx`
- Modify: `inpa_fe/lib/compare-export.ts`
- Modify: `inpa_fe/components/__tests__/neutral-policy-comparison.test.tsx`
- Modify: `inpa_fe/components/__tests__/multi-policy-overlap-selection.test.tsx`

**Interfaces:**

- Produces:

```ts
CompareBarChart({
  items,
  format,
  className,
  labelA = "왼쪽 구성",
  labelB = "오른쪽 구성",
})
```

- Defaults: `ComparePremiumSplit` labels are `왼쪽 구성`, `오른쪽 구성`
- Copy: `buildCompareExportText(data, "왼쪽 구성", "오른쪽 구성")`

- [ ] **Step 1: 결과 카피 RED 테스트를 새 용어로 바꾼다.**

```tsx
expect(chart.getAttribute("aria-label"))
  .toContain("왼쪽 구성 10 오른쪽 구성 20");
expect(screen.getByText("왼쪽 구성")).toBeTruthy();
expect(screen.getByText("오른쪽 구성")).toBeTruthy();

const copy = buildCompareExportText(
  response,
  "왼쪽 구성",
  "오른쪽 구성",
);
expect(copy).toContain("왼쪽 구성");
expect(copy).toContain("오른쪽 구성");
expect(copy).not.toMatch(/증권 A|증권 B|현재와 제안|갈아타기|승환/);
```

- [ ] **Step 2: 차트가 label props를 accessible text에 사용하게 한다.**

막대 색상은 기존 neutral visual token을 유지한다. visible legend와 `role=img aria-label`이 같은 label props를 사용해 화면과 스크린리더 용어가 갈라지지 않게 한다.

- [ ] **Step 3: 결과 영역 상수를 새 용어로 고정한다.**

```ts
const labelA = "왼쪽 구성";
const labelB = "오른쪽 구성";
```

월 보험료, 총 보험료, 갱신/비갱신 표, 보장 비교 제목·legend·table header, 빈 선택 안내, copy text가 이 상수를 사용하게 한다.

- [ ] **Step 4: copy 가능 조건에 snapshot freshness를 포함한다.**

```text
성공 result 존재
현재 snapshot과 result snapshot 동일
compareStatus가 loading 아님
목록 refresh error 없음
```

하나라도 아니면 copy 호출 0회다. copy 실패는 기존 `copyText` false 안내를 유지한다.

- [ ] **Step 5: neutral comparison 테스트를 GREEN으로 만든다.**

Run:

```bash
cd inpa_fe
npm run test:run -- components/__tests__/neutral-policy-comparison.test.tsx components/__tests__/multi-policy-overlap-selection.test.tsx
```

Expected: visible/accessibility/copy가 왼쪽·오른쪽으로 일치하고 권유어 0건.

### Task 5: 겹치는 보험 ID의 backend 3 대 3 집계 회귀 고정

**Files:**

- Modify: `inpa_be/inpa/analysis/tests.py`
- Modify: `inpa_be/inpa/analysis/compare.py`

**Interfaces:**

- Preserves request:

```json
{
  "side_a_ids": [1, 2, 3],
  "side_b_ids": [1, 2, 4]
}
```

- Preserves response slots: `current` = left aggregate, `proposed` = right aggregate

- [ ] **Step 1: A1+A2+A3 대 A1+A2+B1 RED 회귀 테스트를 추가한다.**

`CompareFactsTests`에 다음 집계를 추가한다.

```python
def test_overlapping_three_policy_sets_aggregate_each_side_once(self):
    a1 = _make_portfolio_typed(
        self.customer, self.idet, 10_000_000,
        portfolio_type=1, monthly=10_000)
    a2 = _make_portfolio_typed(
        self.customer, self.idet, 20_000_000,
        portfolio_type=1, monthly=20_000)
    a3 = _make_portfolio_typed(
        self.customer, self.idet, 30_000_000,
        portfolio_type=1, monthly=30_000)
    b1 = _make_portfolio_typed(
        self.customer, self.idet, 40_000_000,
        portfolio_type=2, monthly=40_000)

    response = self.client.post(
        f'/api/v1/customers/{self.customer.id}/compare/',
        {
            'side_a_ids': [a1.id, a2.id, a3.id],
            'side_b_ids': [a1.id, a2.id, b1.id],
        },
        format='json',
    )

    self.assertEqual(response.status_code, 200)
    body = response.json()
    self.assertEqual(body['current']['monthly_premiums'], 60_000)
    self.assertEqual(body['proposed']['monthly_premiums'], 70_000)
    row = next(
        item for item in body['rows']
        if item['coverage'] == '사망보장')
    self.assertEqual(row['current_amount'], 60_000_000)
    self.assertEqual(row['proposed_amount'], 70_000_000)
    self.assertEqual(row['delta'], 10_000_000)
```

이 테스트는 현 backend 기능을 문서화하는 회귀이므로 현재도 PASS할 수 있다. PASS하면 계산 코드를 바꾸지 않는다.

- [ ] **Step 2: invalid selection detail만 새 사용자 용어로 바꾼다.**

```python
{
    'code': 'INVALID_COMPARISON_SELECTION',
    'detail': '왼쪽 구성과 오른쪽 구성에 각각 하나 이상 골라 주세요.',
}
```

status code와 code는 그대로 유지한다. 테스트에서 detail과 code를 함께 assertion한다.

- [ ] **Step 3: compare backend 회귀를 실행한다.**

Run:

```bash
cd inpa_be
./venv/bin/python manage.py test inpa.analysis.tests.CompareFactsTests -v 2
```

Expected: 겹치는 ID 집계, invalid/foreign/ineligible 차단, legacy compatibility 모두 PASS.

### Task 6: 저장 분류·FAQ·landing의 폐기 용어를 사용자 언어로 교체

**Files:**

- Modify: `inpa_fe/app/admin/demo/compare/page.tsx`
- Modify: `inpa_fe/app/admin/demo/page.tsx`
- Modify: `inpa_fe/app/analysis/page.tsx`
- Modify: `inpa_fe/app/onboarding/page.tsx`
- Modify: `inpa_fe/components/brand-story-sections.tsx`
- Modify: `inpa_fe/components/landing-sections.tsx`
- Modify: `inpa_fe/components/insurance-import-cards.tsx`
- Modify: `inpa_fe/components/insurance-manual-modal.tsx`
- Modify: `inpa_fe/components/insurance-manual-review.tsx`
- Modify: `inpa_fe/lib/landing-content.ts`
- Modify: `inpa_fe/lib/mock.ts`
- Modify: `inpa_be/inpa/analysis/management/commands/seed_demo.py`
- Modify: `inpa_be/inpa/boards/management/commands/seed_boards.py`
- Modify: `inpa_be/inpa/boards/tests.py`
- Modify: affected FE tests

**Interfaces:**

- Rendered comparison sides: `왼쪽 구성`, `오른쪽 구성`
- Rendered portfolio storage labels:

```text
portfolio_type=1 -> 현재 등록 증권
portfolio_type=2 -> 비교 화면에서 추가한 증권
```

- [ ] **Step 1: rendered copy inventory를 기준선으로 저장한다.**

Run:

```bash
git grep -n -E "증권 A|증권 B|비교 묶음 A|비교 묶음 B" -- inpa_fe inpa_be/inpa/analysis/compare.py inpa_be/inpa/analysis/management/commands/seed_demo.py inpa_be/inpa/boards/management/commands/seed_boards.py
```

분류:

```text
user-rendered string -> 교체
test expected string -> 새 계약으로 교체
internal API key/comment -> 하위호환 설명이면 유지 가능
historical migration constant -> untouched official row 비교용이면 유지
```

- [ ] **Step 2: 저장 분류 UI를 선택 방향과 분리한다.**

변경표:

| 기존 | 변경 |
|---|---|
| 비교 묶음 A | 현재 등록 증권 |
| 비교 묶음 B | 비교 화면에서 추가한 증권 |
| A 또는 B를 선택 | 등록 위치를 선택 |

`portfolio_type` 값 1/2와 API payload는 바꾸지 않는다. manual modal 기본값 2도 유지한다.

- [ ] **Step 3: 설명·demo·landing copy를 새 용어로 바꾼다.**

변경 예:

```text
선택한 증권 A와 증권 B
-> 선택한 왼쪽 구성과 오른쪽 구성

증권 A · 증권 B를 같은 기준으로
-> 왼쪽 구성 · 오른쪽 구성을 같은 기준으로
```

제품 설명에는 방향보다 가치가 자연스러우면 `선택한 두 구성을 같은 기준으로`를 사용한다. 결과 표·legend처럼 정확한 mapping이 필요한 곳은 `왼쪽 구성`, `오른쪽 구성`을 쓴다.

- [ ] **Step 4: 공식 FAQ를 admin-safe 방식으로 갱신한다.**

현재 공식 A/B answer를 legacy constant로 보존하고 새 answer를 추가한다.

```python
LEGACY_COMPARE_FAQ_ANSWER_AB = (
    '선택한 증권을 증권 A와 증권 B 묶음으로 나눠, 담보·보장금액·보험료 차이를 '
    '같은 기준의 표와 그래프로 확인하는 기능이에요. '
    '인파가 등록된 보장 정보를 정리한 참고 자료입니다.'
)
COMPARE_FAQ_ANSWER = (
    '고객의 증권을 왼쪽 구성과 오른쪽 구성에 자유롭게 담아, 담보·보장금액·보험료 '
    '차이를 같은 기준의 표와 그래프로 확인하는 기능이에요. 같은 증권을 양쪽에 '
    '함께 넣을 수도 있어요. 인파가 등록된 보장 정보를 정리한 참고 자료입니다.'
)
```

기존 row의 question과 answer가 공식 A/B 기본값과 정확히 같을 때만 새 answer로 갱신한다. 관리자가 수정한 FAQ는 보존한다. seed를 두 번 실행해 중복 0건을 확인한다.

- [ ] **Step 5: board seed RED/GREEN 테스트를 갱신한다.**

```python
self.assertIn('왼쪽 구성과 오른쪽 구성', faq.answer)
self.assertIn('같은 증권을 양쪽에 함께', faq.answer)
self.assertNotIn('증권 A', faq.answer)
self.assertNotIn('증권 B', faq.answer)
```

관리자 편집 보존 테스트와 idempotency 테스트는 그대로 통과해야 한다.

- [ ] **Step 6: copy·seed 테스트를 실행한다.**

Run:

```bash
cd inpa_be
./venv/bin/python manage.py test inpa.boards.tests -v 2
```

```bash
cd inpa_fe
npm run test:run
```

Expected: FAQ, rendered copy, component expectations PASS.

### Task 7: 폐기 용어 재유입을 copy lint로 차단

**Files:**

- Modify: `inpa_fe/scripts/check-copy.js`
- Create: `inpa_fe/scripts/check-copy.test.js`
- Modify: `inpa_fe/package.json`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**

- Produces scoped rule over `MULTI_POLICY_SURFACES`

- [ ] **Step 1: 새 scoped rule이 실패하는 fixture를 추가한다.**

다음 rendered string 각각이 violation이어야 한다.

```text
증권 A
증권 B
비교 묶음 A
비교 묶음 B
```

주석과 internal API key `side_a_ids`, `side_b_ids`, `current`, `proposed`는 violation이 아니어야 한다.

```js
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const { scanCopy } = require("./check-copy");

function scanCustomerComparison(source) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "inpa-copy-"));
  const file = path.join(root, "app/customer/[id]/page.tsx");
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, source);
    return scanCopy(root).violations;
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
}

test("blocks retired rendered comparison labels", () => {
  for (const label of [
    "증권 A",
    "증권 B",
    "비교 묶음 A",
    "비교 묶음 B",
  ]) {
    const violations = scanCustomerComparison(
      `export default function Page(){return <div>${label}</div>}`,
    );
    assert.equal(violations.length, 1);
  }
});

test("allows comments and compatibility keys", () => {
  const violations = scanCustomerComparison(`
    // 증권 A는 과거 화면 용어다.
    const payload = { side_a_ids: [1], side_b_ids: [2] };
    export default function Page(){return <div>{payload.current}</div>}
  `);
  assert.equal(violations.length, 0);
});
```

- [ ] **Step 2: copy lint rule을 추가한다.**

```js
{
  name: "폐기된 증권 비교 방향 용어",
  re: /증권 [AB]|비교 묶음 [AB]/,
  paths: MULTI_POLICY_SURFACES,
  hint: "화면에는 왼쪽 구성·오른쪽 구성, 저장 분류에는 현재 등록 증권·비교 화면에서 추가한 증권을 쓰세요.",
}
```

`MULTI_POLICY_SURFACES`에 Task 6에서 바꾼 모든 rendered source를 포함한다. historical backend constants와 테스트 data는 FE lint 범위에 넣지 않는다.

- [ ] **Step 3: package script와 CI를 연결한다.**

`package.json`:

```json
"test:copy-lint": "node --test scripts/check-copy.test.js"
```

`.github/workflows/ci.yml`의 기존 `Copy guard (정직성 카피)` 다음에 추가한다.

```yaml
- name: Copy guard rule tests
  run: npm run test:copy-lint
```

- [ ] **Step 4: copy lint와 정적 inventory를 실행한다.**

Run:

```bash
cd inpa_fe
npm run test:copy-lint
npm run lint:copy
```

```bash
git grep -n -E "증권 A|증권 B|비교 묶음 A|비교 묶음 B" -- inpa_fe/app inpa_fe/components inpa_fe/lib
```

Expected:

- copy lint PASS
- 남은 grep 결과는 comment, test fixture, historical compatibility로 분류되고 사용자 렌더 string은 0건

### Task 8: landing 실제 비교 화면 재촬영

**Files:**

- Modify: `inpa_fe/public/landing-test/compare.webp`
- Verify: `inpa_fe/lib/landing-content.ts`
- Reference: `docs/superpowers/specs/2026-07-24-landing-screenshot-quality-design.md`

- [ ] **Step 1: 촬영용 로컬 데이터를 재생성한다.**

Run:

```bash
cd inpa_be
./venv/bin/python manage.py seed_normalization
./venv/bin/python manage.py seed_capture
```

Expected: `capture@inpa.local` 로그인 정보와 촬영 고객 ID가 출력되고, 실제 표준 트리와 가상 고객 데이터가 준비된다.

- [ ] **Step 2: 새 비교 UX로 승인 사례를 구성한다.**

촬영 고객의 여러 증권 비교 탭에서:

```text
왼쪽 구성 3개
오른쪽 구성 3개
공통 증권 2개
왼쪽 전용 1개
오른쪽 전용 1개
비교 결과 성공
```

화면에 `[DEMO]`, `[가칭]`, 비정상 전화번호, 실제 개인정보, 폐기된 A/B 용어가 없어야 한다.

- [ ] **Step 3: 기존 screenshot 품질 계약으로 compare만 재촬영한다.**

브라우저는 desktop 1440×900, device scale factor 2를 사용한다. 핵심 selector 요약, 카드 일부, 보험료/보장 결과가 한 장 안에서 읽히게 scroll 위치를 잡는다. 최종 canvas는 2880×1800, 배경 `#F3F5F9`, 기존 side margin과 bottom fade를 유지한다.

출력:

```text
inpa_fe/public/landing-test/compare.webp
width 2880
height 1800
WebP
```

- [ ] **Step 4: 이미지와 landing 렌더를 시각 검증한다.**

검증:

```text
텍스트 선명도
왼쪽/오른쪽 label 일치
같은 증권 양쪽 포함이 요약에서 이해됨
가로 잘림 없음
모바일 landing에서 이미지 비율 유지
alt text가 새 화면과 일치
```

### Task 9: 전체 회귀와 실제 브라우저 검증

**Files:**

- Verify: all Release 3 files

- [ ] **Step 1: FE 전체 게이트를 실행한다.**

Run:

```bash
cd inpa_fe
npm run test:unit
npm run test:run
npm run test:copy-lint
npm run lint:copy
npm run build
```

Expected: 모두 PASS.

- [ ] **Step 2: BE 비교·board와 전체 Django check를 실행한다.**

Run:

```bash
cd inpa_be
./venv/bin/python manage.py check
./venv/bin/python manage.py test inpa.analysis.tests.CompareFactsTests inpa.boards.tests -v 2
```

Expected: compare/FAQ PASS, migration 변경 0건.

- [ ] **Step 3: desktop browser에서 승인 사례를 검증한다.**

```text
1. 실제 로컬 테스트 고객 상세 열기
2. 여러 증권 비교 탭 선택
3. 카드 4개와 초기 왼쪽 3, 오른쪽 4 확인
4. A3의 오른쪽만 해제
5. A1·A2는 양쪽 포함인지 확인
6. 선택한 구성 비교하기 클릭
7. Network body가 side_a_ids=[A1,A2,A3], side_b_ids=[A1,A2,B1]인지 확인
8. 월 보험료·담보 합계가 각 side와 일치하는지 확인
9. 표·chart aria-label·복사값이 왼쪽/오른쪽 용어인지 확인
```

- [ ] **Step 4: stale/error/402를 browser에서 검증한다.**

```text
성공 뒤 토글 변경 -> 이전 결과 숨김, copy disabled
compare 500 -> 카드와 선택 유지, 다시 비교
compare 402 -> UpgradeModal 뒤 카드와 선택 유지
목록 refresh -> 기존 off 선택 보존, 새 보험만 preset
느린 요청 중 toggle -> 과거 응답 미표시
```

- [ ] **Step 5: 390px mobile과 keyboard만으로 검증한다.**

```text
카드 가로 넘침 0
두 선택 버튼 높이 44px 이상
Tab으로 왼쪽/오른쪽 각각 이동
Space/Enter로 독립 toggle
CTA를 목록 아래에서 발견 가능
status/error가 screen reader live region에 전달
```

- [ ] **Step 6: PM이 커밋을 요청한 경우에만 Release 3 변경을 커밋한다.**

첫 커밋은 선택 기능과 계산 회귀만 담는다.

```bash
git add inpa_fe/lib/policy-comparison-selection.ts inpa_fe/components/insurance-review-cards.tsx 'inpa_fe/app/customer/[id]/page.tsx' inpa_fe/components/charts.tsx inpa_fe/components/premium-split.tsx inpa_fe/lib/compare-export.ts inpa_fe/components/__tests__/policy-comparison-selection.test.tsx inpa_fe/components/__tests__/insurance-review-authority.test.tsx inpa_fe/components/__tests__/multi-policy-overlap-selection.test.tsx inpa_fe/components/__tests__/neutral-policy-comparison.test.tsx inpa_be/inpa/analysis/compare.py inpa_be/inpa/analysis/tests.py
git commit -m "feat(증권비교): 양쪽 중복 선택과 명시 비교"
```

두 번째 커밋은 사용자 카피·FAQ·landing 자산만 담는다.

```bash
git add inpa_fe/scripts/check-copy.js inpa_fe/scripts/check-copy.test.js inpa_fe/package.json .github/workflows/ci.yml inpa_fe/app/admin/demo/compare/page.tsx inpa_fe/app/admin/demo/page.tsx inpa_fe/app/analysis/page.tsx inpa_fe/app/onboarding/page.tsx inpa_fe/components/brand-story-sections.tsx inpa_fe/components/landing-sections.tsx inpa_fe/components/insurance-import-cards.tsx inpa_fe/components/insurance-manual-modal.tsx inpa_fe/components/insurance-manual-review.tsx inpa_fe/lib/landing-content.ts inpa_fe/lib/mock.ts inpa_fe/public/landing-test/compare.webp inpa_be/inpa/analysis/management/commands/seed_demo.py inpa_be/inpa/boards/management/commands/seed_boards.py inpa_be/inpa/boards/tests.py
git commit -m "refactor(증권비교): 왼쪽 오른쪽 사용자 용어 통일"
```

## Release 3 완료 증거

```text
Changed: 독립 양쪽 선택, 명시 비교 CTA, stale 결과 차단, 왼쪽/오른쪽 용어
Verified by: selection/Card/SwitchTab Vitest, CompareFactsTests, board seed, copy lint, Next build, desktop/mobile browser
Result: left=[A1,A2,A3], right=[A1,A2,B1], 공통 ID 양쪽 각 1회 집계, 오류 중 선택 유지
Unverified: 없음
```
