# Plan: 고객 카드 재설계 + D-Day 자동갱신

Branch: feat/benchmark-ui-revamp
Base commit: f90ff6f

## Global Constraints
- Service pages = light-fixed, NO `dark:` variants anywhere
- No new files unless absolutely required; edit existing files
- No branch/push; commit only
- Keep `e.stopPropagation()` on ⋯ menu and its items
- Click card body → navigate `/customer/{id}` (no inline edit)
- Staleness ring (ringCls) unchanged; contract stage exempt
- All existing drag-and-drop kanban behavior preserved
- BE: `from django.utils import timezone` already imported in views.py — check before adding
- Commit message exactly: `feat(고객): 카드 재설계(⋯메뉴·단계배지·경과일·청약더보기·범례인라인) + D-Day 자동갱신(substantive 변경시)`

## Task 1 — BE: D-Day auto-update (perform_update + churn touch)

Files:
- `inpa_be/inpa/customers/views.py` — add `perform_update` to CustomerViewSet
- `inpa_be/inpa/insurances/churn.py` — touch customer.last_contacted_at on cancel patch

### CustomerViewSet.perform_update
Add after `get_serializer_class` in CustomerViewSet:

```python
SUBSTANTIVE = {
    'name', 'gender', 'birth_day', 'mobile_phone_number',
    'job_code', 'memo', 'color', 'avatar_label',
    'lead_source', 'is_agree_term', 'sales_stage', 'tag_ids',
}

def perform_update(self, serializer):
    keys = set(self.request.data.keys())
    if keys & self.SUBSTANTIVE:
        serializer.save(last_contacted_at=timezone.now())
    else:
        serializer.save()
```

Note: `from django.utils import timezone` is already imported in views.py (line 7). Verify before adding.

### InsuranceChurnView.patch — customer touch
After `ci.save(...)` at end of patch(), add:
```python
if 'is_cancelled' in request.data or 'cancelled_at' in request.data:
    from inpa.customers.models import Customer
    Customer.objects.filter(pk=ci.customer_id).update(last_contacted_at=timezone.now())
```

Also add `from django.utils import timezone` at top of churn.py imports if not already there (check first — `datetime` is imported but `timezone` may not be).

## Task 2 — BE: Tests for D-Day auto-update

File: `inpa_be/inpa/customers/tests.py`

Add a new test class `DdayAutoUpdateTests` at the END of the file (after all existing classes).

```python
class DdayAutoUpdateTests(TestCase):
    """D-Day 자동갱신: substantive 필드 PATCH → last_contacted_at 갱신. is_favorite/is_pinned만 → 불변."""

    def setUp(self):
        self.user, self.client = _make_planner('dday@test.com')
        self.cust = Customer.objects.create(
            owner=self.user,
            name='테스트고객',
            mobile_phone_number='010-0000-0000',
            last_contacted_at=None,
        )

    def test_substantive_patch_updates_last_contacted_at(self):
        """memo 수정 → last_contacted_at이 ~now로 갱신된다."""
        before = timezone.now()
        r = self.client.patch(
            f'/api/v1/customers/{self.cust.id}/',
            {'memo': '메모 수정'},
            format='json',
        )
        self.assertEqual(r.status_code, 200)
        self.cust.refresh_from_db()
        self.assertIsNotNone(self.cust.last_contacted_at)
        self.assertGreaterEqual(self.cust.last_contacted_at, before)

    def test_non_substantive_patch_does_not_update_last_contacted_at(self):
        """is_favorite만 PATCH → last_contacted_at 불변."""
        original_ts = self.cust.last_contacted_at  # None
        r = self.client.patch(
            f'/api/v1/customers/{self.cust.id}/',
            {'is_favorite': True},
            format='json',
        )
        self.assertEqual(r.status_code, 200)
        self.cust.refresh_from_db()
        self.assertEqual(self.cust.last_contacted_at, original_ts)
```

Run: `cd inpa_be && python manage.py test inpa.customers inpa.insurances && python manage.py check`

## Task 3 — FE: Customer card redesign

File: `inpa_fe/app/customers/page.tsx`

### Summary of changes needed:
1. Remove `FavPinButtons` component and `MetaBadges` component (or keep MetaBadges if used elsewhere — check)
2. Add helpers: `daysSince(dateStr)` → int, `elapsedLabel(last_contacted_at, created_at)` → "오늘"/"N일전"
3. Add `stageBadge(stage)` → `{ label, cls }` for DB/TA/FA/청약 colored pills
4. Add `DotMenu` component (⋯ dropdown) with pin/fav toggles + "방금 연락함"
5. New `ListCard` component — renders the new 2-row layout for list view
6. New `KanbanCard` component — same 2-row layout for kanban view (compact)
7. Move legend INLINE next to "고객 N" heading (same line, flex wrap)
8. Add `showContract` state (default false) + "더보기" toggle button for kanban 청약 column
9. Card body = `<div onClick={() => router.push(\`/customer/\${c.id}\`)} ...>` (import useRouter)
10. Keep drag events on kanban card wrapper; click the card body navigates

### Detailed spec:

#### New helpers (add near top of file after existing helpers):

```tsx
function daysSince(dateStr: string | null | undefined): number {
  if (!dateStr) return Infinity;
  const diff = Date.now() - new Date(dateStr).getTime();
  return Math.floor(diff / 86_400_000);
}

function elapsedLabel(lastContacted: string | null | undefined, createdAt: string): string {
  const d = daysSince(lastContacted ?? createdAt);
  if (d <= 0) return "오늘";
  return `${d}일전`;
}
```

#### stageBadge helper:
```tsx
const STAGE_BADGE: Record<string, { label: string; cls: string }> = {
  db:       { label: "DB",   cls: "bg-surface2 text-ink3 border-line" },
  contact:  { label: "TA",   cls: "bg-blue-50 text-blue-700 border-blue-200" },
  meeting:  { label: "FA",   cls: "bg-violet-50 text-violet-700 border-violet-200" },
  contract: { label: "청약", cls: "bg-success-tint text-success-ink border-enough/30" },
};
```

#### DotMenu component (inside file, after helpers):
```tsx
function DotMenu({
  c,
  onToggle,
  onContacted,
}: {
  c: CustomerListItem;
  onToggle: (id: number, payload: Partial<CustomerWritePayload>, optimistic: Partial<CustomerListItem>) => void;
  onContacted: (id: number) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative" onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        aria-label="더보기 메뉴"
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}
        className="text-[16px] text-ink3 hover:text-ink px-1.5 py-0.5 rounded-lg hover:bg-surface2 leading-none"
      >
        ⋯
      </button>
      {open && (
        <div
          className="absolute right-0 top-full mt-1 z-20 bg-surface border border-line rounded-xl shadow-lg py-1 min-w-[130px] text-[13px]"
          onClick={(e) => e.stopPropagation()}
        >
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onToggle(c.id, { is_pinned: !c.is_pinned }, { is_pinned: !c.is_pinned }); setOpen(false); }}
            className="w-full text-left px-4 py-2 hover:bg-surface2 flex items-center gap-2"
          >
            {c.is_pinned ? "📌 고정 해제" : "📍 상단고정"}
          </button>
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onToggle(c.id, { is_favorite: !c.is_favorite }, { is_favorite: !c.is_favorite }); setOpen(false); }}
            className="w-full text-left px-4 py-2 hover:bg-surface2 flex items-center gap-2"
          >
            {c.is_favorite ? "★ 즐겨찾기 해제" : "☆ 즐겨찾기"}
          </button>
          <hr className="my-1 border-line" />
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onContacted(c.id); setOpen(false); }}
            className="w-full text-left px-4 py-2 hover:bg-surface2 text-brand"
          >
            방금 연락함
          </button>
        </div>
      )}
    </div>
  );
}
```

#### Card body layout (used in BOTH list and kanban):
Top row: `avatar` + `name` + `gender·grade` badge + right-aligned `DotMenu`
Bottom row: `phone` + `stage pill` + `elapsed`

#### List card (replaces current Card block at ~283-329):
```tsx
// list view card
<Card
  key={c.id}
  className={`p-3.5 cursor-pointer hover:shadow-md transition ${ringCls(lvl)}`}
  onClick={() => router.push(`/customer/${c.id}`)}
>
  <div className="flex items-start gap-3">
    <CustomerAvatar label={c.avatar_label} color={c.color} size={40} />
    <div className="flex-1 min-w-0">
      {/* top row */}
      <div className="flex items-center gap-1.5">
        <span className="text-[15px] font-bold text-ink truncate">{c.name}</span>
        {genderLabel(c.gender) || c.job_risk_grade ? (
          <span className="text-[11px] text-ink3 shrink-0">
            {[genderLabel(c.gender), c.job_risk_grade ? `${c.job_risk_grade}급` : ""].filter(Boolean).join("·")}
          </span>
        ) : null}
        <div className="ml-auto shrink-0">
          <DotMenu c={c} onToggle={patchCustomer} onContacted={markContacted} />
        </div>
      </div>
      {/* bottom row */}
      <div className="mt-1 flex items-center gap-2 flex-wrap">
        <span className="text-[12px] text-ink3">{c.mobile_phone_number ?? "연락처 없음"}</span>
        {(() => {
          const sb = STAGE_BADGE[c.sales_stage];
          return sb ? (
            <span className={`text-[10px] font-semibold rounded-full px-2 py-0.5 border ${sb.cls}`}>{sb.label}</span>
          ) : null;
        })()}
        <span className="text-[11px] text-ink3">{elapsedLabel(c.last_contacted_at, c.created_at)}</span>
      </div>
    </div>
  </div>
</Card>
```

#### Kanban card (replaces current div block at ~356-399):
```tsx
<div
  key={c.id}
  draggable
  onDragStart={() => setDragId(c.id)}
  onDragEnd={() => setDragId(null)}
  className={`rounded-xl bg-surface border border-line p-3 cursor-grab active:cursor-grabbing ${ringCls(lvl)} ${moving.has(c.id) ? "opacity-50" : ""}`}
  onClick={() => router.push(`/customer/${c.id}`)}
>
  <div className="flex items-start gap-2">
    <CustomerAvatar label={c.avatar_label} color={c.color} size={32} />
    <div className="flex-1 min-w-0">
      {/* top row */}
      <div className="flex items-center gap-1">
        <span className="text-[13px] font-bold text-ink truncate">{c.name}</span>
        {(genderLabel(c.gender) || c.job_risk_grade) && (
          <span className="text-[10px] text-ink3 shrink-0">
            {[genderLabel(c.gender), c.job_risk_grade ? `${c.job_risk_grade}급` : ""].filter(Boolean).join("·")}
          </span>
        )}
        <div className="ml-auto shrink-0">
          <DotMenu c={c} onToggle={patchCustomer} onContacted={markContacted} />
        </div>
      </div>
      {/* bottom row */}
      <div className="mt-1 flex items-center gap-1.5 flex-wrap">
        <span className="text-[11px] text-ink3 truncate">{c.mobile_phone_number ?? ""}</span>
        {(() => {
          const sb = STAGE_BADGE[c.sales_stage];
          return sb ? (
            <span className={`text-[9px] font-semibold rounded-full px-1.5 py-0.5 border ${sb.cls}`}>{sb.label}</span>
          ) : null;
        })()}
        <span className="text-[10px] text-ink3">{elapsedLabel(c.last_contacted_at, c.created_at)}</span>
      </div>
    </div>
  </div>
</div>
```

#### Heading + legend (replace ~222-262 area):
```tsx
<div className="flex items-start justify-between gap-2 flex-wrap">
  <div className="flex items-center gap-x-4 gap-y-1 flex-wrap">
    <h1 className="text-[22px] font-extrabold text-ink">
      고객 <span className="text-ink3 tnum">{loading ? "..." : totalCount}</span>
    </h1>
    {/* 방치 경보 범례 — 제목 옆 인라인 */}
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink3 pt-1">
      <span className="inline-flex items-center gap-1"><span className="w-3 h-3 rounded-[4px] border-2 border-short" />3일+</span>
      <span className="inline-flex items-center gap-1"><span className="w-3 h-3 rounded-[4px] border-2 border-cnone" />7일+</span>
      <span className="text-muted">테두리 = 연락 끊긴 기간</span>
    </div>
  </div>
  <div className="flex items-center gap-2">
    {/* view toggle + 고객 등록 button — unchanged */}
  </div>
</div>
```
(Remove the separate legend `<div className="mt-3 flex flex-wrap ...">` block that was below the heading)

#### showContract state + kanban 청약 toggle:
Add state: `const [showContract, setShowContract] = useState(false);`

In kanban SALES_STAGES.map(), wrap contract column:
```tsx
{stage.key === "contract" && !showContract ? null : (
  <div key={stage.key} ...>
    {/* existing column JSX */}
  </div>
)}
```

Add toggle button before the kanban grid (inside `view === "kanban"` block):
```tsx
<div className="mt-3 flex items-center justify-end">
  <button
    type="button"
    onClick={() => setShowContract((v) => !v)}
    className="text-[12px] font-semibold text-ink3 border border-line rounded-lg px-3 py-1.5 hover:bg-surface2"
  >
    {showContract ? "청약 숨기기" : "청약 더보기"}
  </button>
</div>
```

#### Import useRouter:
Add `import { useRouter } from "next/navigation";` at top.
Add `const router = useRouter();` inside `CustomersPage` component.

#### Remove FavPinButtons from JSX (it's still defined but no longer rendered — or delete it entirely).

### After implementation:
`cd inpa_fe && npm run build` — must succeed (55 routes, 0 type errors).

## Task 4 — Commit + Write report

1. Run final verify:
   - BE: `cd inpa_be && python manage.py test inpa.customers inpa.insurances && python manage.py check`
   - FE: `cd inpa_fe && npm run build`
2. Commit all: `git add -A && git commit -m "feat(고객): 카드 재설계(⋯메뉴·단계배지·경과일·청약더보기·범례인라인) + D-Day 자동갱신(substantive 변경시)"`
3. Write report to `/Users/kyungsbook/Desktop/inpa/.superpowers/sdd/card-redesign-report.md`

Report must cover:
- Card layout changes summary
- ⋯ menu implementation
- D-Day rule + churn touch
- Tests added (class + method names)
- BE test result (pass count)
- FE build result (routes count, any warnings)
- Commit SHA
- Anything unsure or deferred
