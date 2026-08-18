# 여러 고객 메모와 기존 메모 이관 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 고객 상세의 단일 메모를 작성·수정 시각이 있는 여러 메모 카드로 바꾸고 기존 본문을 손실 없이 이관한다.

**Architecture:** `CustomerMemo`를 `customers` 앱에 추가하고 nested owner-scoped API로 CRUD한다. 기존 `Customer.memo`는 한 배포 동안 구버전 화면 호환 브리지로만 유지하며, 새 UI는 `기록 > 메모 N개`를 사용한다.

**Tech Stack:** Django 5.2, DRF 3.16, PostgreSQL/SQLite, Next.js 16 Client Components, React 19, TypeScript, Tailwind v4, Vitest.

## Global Constraints

- `CustomerMemo.body` 최대 10,000자, 빈 문자열은 저장하지 않는다.
- 직접 메모 생성 시각은 서버 `timezone.now()`를 사용한다.
- 직접 메모 생성만 `Customer.last_contacted_at`을 올리고 수정·삭제·이관은 바꾸지 않는다.
- 정렬은 `COALESCE(occurred_at, created_at), created_at, id` 내림차순이다.
- 다른 설계사의 고객·메모는 존재 여부를 숨기는 404로 응답한다.
- 사용자 화면 copy에는 `—`를 쓰지 않는다.
- 기존 작업 파일을 보존하고 PM 요청 전에는 commit하지 않는다.

---

### Task 1: 메모 모델과 손실 없는 이관 마이그레이션

**Files:**
- Modify: `inpa_be/inpa/customers/models.py`
- Create: `inpa_be/inpa/customers/migrations/0016_customermemo.py`
- Test: `inpa_be/inpa/customers/tests.py`

**Interfaces:**
- Produces: `CustomerMemo`, `CustomerMemo.SOURCE_MANUAL`, `SOURCE_AI_SUMMARY`, `SOURCE_LEGACY`.
- Consumes: existing `Customer`, `settings.AUTH_USER_MODEL`.

- [ ] **Step 1: Write the failing model and migration tests**

```python
class CustomerMemoModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('memo-owner@example.com', password='pass1234')
        self.customer = Customer.objects.create(owner=self.user, name='메모 고객')

    def test_customer_allows_many_memos_but_only_one_legacy_row(self):
        CustomerMemo.objects.create(
            owner=self.user, customer=self.customer,
            source=CustomerMemo.SOURCE_MANUAL, body='첫 메모', occurred_at=timezone.now())
        CustomerMemo.objects.create(
            owner=self.user, customer=self.customer,
            source=CustomerMemo.SOURCE_MANUAL, body='둘째 메모', occurred_at=timezone.now())
        CustomerMemo.objects.create(
            owner=self.user, customer=self.customer,
            source=CustomerMemo.SOURCE_LEGACY, body='기존 메모')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CustomerMemo.objects.create(
                    owner=self.user, customer=self.customer,
                    source=CustomerMemo.SOURCE_LEGACY, body='중복 기존 메모')
```

- [ ] **Step 2: Run the focused test and verify the missing model failure**

Run: `cd inpa_be && python manage.py test inpa.customers.tests.CustomerMemoModelTests -v 2`

Expected: `ImportError` 또는 `CustomerMemo` 미정의로 FAIL.

- [ ] **Step 3: Add the model**

```python
class CustomerMemo(models.Model):
    SOURCE_MANUAL = 'manual'
    SOURCE_AI_SUMMARY = 'ai_summary'
    SOURCE_LEGACY = 'legacy_migrated'
    SOURCE_CHOICES = (
        (SOURCE_MANUAL, '직접 작성'),
        (SOURCE_AI_SUMMARY, '녹음 요약'),
        (SOURCE_LEGACY, '기존 메모'),
    )

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='customer_memos')
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name='memos')
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    body = models.TextField(max_length=10_000)
    occurred_at = models.DateTimeField(null=True, blank=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'customer_memo'
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(body=''), name='customer_memo_body_not_empty'),
            models.UniqueConstraint(
                fields=['customer'], condition=models.Q(source='legacy_migrated'),
                name='uniq_customer_legacy_memo'),
        ]
        indexes = [models.Index(fields=['customer', '-created_at'])]
```

- [ ] **Step 4: Generate the schema migration, then add an idempotent data operation**

Run: `cd inpa_be && python manage.py makemigrations customers`

Expected: `0016_customermemo.py`가 생성되고 첫 operation 이름이 `CustomerMemo`인 `migrations.CreateModel`이다.

생성된 migration의 `CreateModel` 바로 뒤에 다음 함수와 `RunPython` operation을 추가한다.

```python
def forwards(apps, schema_editor):
    Customer = apps.get_model('customers', 'Customer')
    CustomerMemo = apps.get_model('customers', 'CustomerMemo')
    rows = []
    for customer in Customer.objects.exclude(memo='').iterator(chunk_size=500):
        if customer.memo.strip():
            rows.append(CustomerMemo(
                owner_id=customer.owner_id,
                customer_id=customer.id,
                source='legacy_migrated',
                body=customer.memo,
                occurred_at=None,
            ))
    CustomerMemo.objects.bulk_create(rows, ignore_conflicts=True, batch_size=500)
```

생성된 `Migration.operations`에서 `CustomerMemo`의 `CreateModel` 바로 다음 원소로 아래 한 줄을 넣는다. 생성된 schema operation과 dependency는 그대로 보존한다.

```python
migrations.RunPython(forwards, migrations.RunPython.noop),
```

- [ ] **Step 5: Inspect and apply the migration, then run the test**

Run: `cd inpa_be && python manage.py makemigrations --check && python manage.py migrate && python manage.py test inpa.customers.tests.CustomerMemoModelTests -v 2`

Expected: 새 migration 이름이 `0016_customermemo.py`, migration 적용 성공, 테스트 PASS.

- [ ] **Step 6: Commit only after PM asks**

```bash
git add inpa_be/inpa/customers/models.py inpa_be/inpa/customers/migrations/0016_customermemo.py inpa_be/inpa/customers/tests.py
git commit -m "feat(메모): 여러 고객 메모 모델 추가"
```

### Task 2: 메모 서비스와 owner-scoped CRUD API

**Files:**
- Create: `inpa_be/inpa/customers/memos.py`
- Modify: `inpa_be/inpa/customers/serializers.py`
- Modify: `inpa_be/inpa/customers/views.py`
- Modify: `inpa_be/inpa/customers/urls.py`
- Test: `inpa_be/inpa/customers/tests.py`

**Interfaces:**
- Produces: `create_manual_memo(*, customer, owner, body)`, `update_memo(*, memo, body, expected_revision)`, `bump_last_contacted_at(customer_id, at)`.
- Produces API: `GET/POST /api/v1/customers/{customer_pk}/memos/`, `PATCH/DELETE /api/v1/customers/{customer_pk}/memos/{pk}/`.

- [ ] **Step 1: Write failing CRUD, ordering, conflict, and ownership tests**

```python
class CustomerMemoApiTests(APITestCase):
    def test_create_lists_and_edits_without_bumping_contact_on_edit(self):
        self.client.force_authenticate(self.user)
        created = self.client.post(self.url, {'body': '첫 상담 메모'}, format='json')
        self.assertEqual(created.status_code, 201)
        self.customer.refresh_from_db()
        contacted_at = self.customer.last_contacted_at
        changed = self.client.patch(
            f"{self.url}{created.data['id']}/",
            {'body': '첫 상담 메모 수정', 'revision': 1}, format='json')
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.data['revision'], 2)
        self.assertIsNotNone(changed.data['edited_at'])
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.last_contacted_at, contacted_at)

    def test_stale_revision_is_409_and_foreign_owner_is_404(self):
        response = self.client.patch(
            f'{self.url}{self.memo.id}/',
            {'body': '충돌', 'revision': 999}, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'MEMO_EDIT_CONFLICT')
        self.client.force_authenticate(self.other_user)
        self.assertEqual(self.client.get(self.url).status_code, 404)
```

- [ ] **Step 2: Run tests and verify 404 route failure**

Run: `cd inpa_be && python manage.py test inpa.customers.tests.CustomerMemoApiTests -v 2`

Expected: memo route 미등록으로 FAIL.

- [ ] **Step 3: Implement transaction-safe services**

```python
from django.db import transaction
from django.utils import timezone

from .models import Customer, CustomerMemo


def bump_last_contacted_at(customer_id, at):
    with transaction.atomic():
        customer = Customer.objects.select_for_update().get(pk=customer_id)
        if customer.last_contacted_at is None or customer.last_contacted_at < at:
            customer.last_contacted_at = at
            customer.save(update_fields=['last_contacted_at'])


def create_manual_memo(*, customer, owner, body):
    clean = body.strip()
    if not clean:
        raise ValueError('EMPTY_MEMO')
    now = timezone.now()
    with transaction.atomic():
        memo = CustomerMemo.objects.create(
            owner=owner, customer=customer, source=CustomerMemo.SOURCE_MANUAL,
            body=clean, occurred_at=now)
        bump_last_contacted_at(customer.id, now)
    return memo


def update_memo(*, memo, body, expected_revision):
    clean = body.strip()
    if not clean:
        raise ValueError('EMPTY_MEMO')
    with transaction.atomic():
        locked = CustomerMemo.objects.select_for_update().get(pk=memo.pk)
        if locked.revision != expected_revision:
            raise ValueError('MEMO_EDIT_CONFLICT')
        if locked.body != clean:
            locked.body = clean
            locked.revision += 1
            locked.edited_at = timezone.now()
            locked.save(update_fields=['body', 'revision', 'edited_at', 'updated_at'])
        return locked
```

- [ ] **Step 4: Add serializer and viewset**

```python
class CustomerMemoSerializer(serializers.ModelSerializer):
    source_label = serializers.CharField(source='get_source_display', read_only=True)

    class Meta:
        model = CustomerMemo
        fields = ('id', 'source', 'source_label', 'body', 'occurred_at',
                  'created_at', 'updated_at', 'edited_at', 'revision')
        read_only_fields = ('id', 'source', 'source_label', 'occurred_at',
                            'created_at', 'updated_at', 'edited_at', 'revision')

    def validate_body(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('메모 내용을 입력해 주세요.')
        return value
```

```python
class CustomerMemoViewSet(_CustomerScopedViewSet):
    serializer_class = CustomerMemoSerializer
    queryset = CustomerMemo.objects.all()

    def get_queryset(self):
        return (super().get_queryset()
                .annotate(display_at=Coalesce('occurred_at', 'created_at'))
                .order_by('-display_at', '-created_at', '-id'))

    def perform_create(self, serializer):
        memo = create_manual_memo(
            customer=self.get_customer(), owner=self.request.user,
            body=serializer.validated_data['body'])
        serializer.instance = memo

    def partial_update(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        revision = request.data.get('revision')
        if type(revision) is not int:
            return Response({'code': 'MEMO_REVISION_REQUIRED',
                             'detail': '최신 메모를 다시 불러와 주세요.'}, status=400)
        try:
            memo = update_memo(
                memo=self.get_object(), body=serializer.validated_data['body'],
                expected_revision=revision)
        except ValueError as exc:
            if str(exc) == 'MEMO_EDIT_CONFLICT':
                return Response({'code': 'MEMO_EDIT_CONFLICT',
                                 'detail': '다른 화면에서 수정된 메모예요. 최신 내용을 확인해 주세요.'},
                                status=409)
            raise
        return Response(self.get_serializer(memo).data)
```

- [ ] **Step 5: Register nested routes and run tests**

```python
_memo = _nested(views.CustomerMemoViewSet)

urlpatterns += [
    path('customers/<int:customer_pk>/memos/', _memo['list'], name='memo-list'),
    path('customers/<int:customer_pk>/memos/<int:pk>/', _memo['detail'], name='memo-detail'),
]
```

Run: `cd inpa_be && python manage.py test inpa.customers.tests.CustomerMemoApiTests -v 2`

Expected: CRUD·409·404·정렬 테스트 PASS.

- [ ] **Step 6: Commit only after PM asks**

```bash
git add inpa_be/inpa/customers/memos.py inpa_be/inpa/customers/serializers.py inpa_be/inpa/customers/views.py inpa_be/inpa/customers/urls.py inpa_be/inpa/customers/tests.py
git commit -m "feat(메모): 여러 메모 API 추가"
```

### Task 3: 구버전 단일 메모 호환 브리지와 이관 감사

**Files:**
- Modify: `inpa_be/inpa/customers/memos.py`
- Modify: `inpa_be/inpa/customers/serializers.py`
- Modify: `inpa_be/inpa/customers/views.py`
- Create: `inpa_be/inpa/customers/management/commands/audit_customer_memos.py`
- Test: `inpa_be/inpa/customers/tests.py`

**Interfaces:**
- Produces: `sync_legacy_memo(*, customer, owner, body, source)`.
- Preserves: old `PATCH /customers/{id}/ {memo}` and bulk import during one deployment.

- [ ] **Step 1: Write failing compatibility tests**

```python
def test_legacy_patch_updates_old_field_and_one_legacy_row_atomically(self):
    response = self.client.patch(
        f'/api/v1/customers/{self.customer.id}/', {'memo': '구버전 저장'}, format='json')
    self.assertEqual(response.status_code, 200)
    self.customer.refresh_from_db()
    self.assertEqual(self.customer.memo, '구버전 저장')
    row = self.customer.memos.get(source=CustomerMemo.SOURCE_LEGACY)
    self.assertEqual(row.body, '구버전 저장')

def test_new_customer_and_bulk_memo_become_manual_memos(self):
    single = self.client.post('/api/v1/customers/', {'name': '단건', 'memo': '단건 메모'})
    self.assertEqual(CustomerMemo.objects.get(customer_id=single.data['id']).source, 'manual')
    bulk = self.client.post('/api/v1/customers/bulk/', {
        'customers': [{'name': '일괄', 'memo': '일괄 메모'}]}, format='json')
    self.assertEqual(bulk.status_code, 201)
    self.assertEqual(CustomerMemo.objects.get(customer__name='일괄').body, '일괄 메모')
```

- [ ] **Step 2: Run and verify missing bridge failures**

Run: `cd inpa_be && python manage.py test inpa.customers.tests.CustomerMemoCompatibilityTests -v 2`

Expected: `CustomerMemo` row가 없어 FAIL.

- [ ] **Step 3: Implement the compatibility service**

```python
def sync_legacy_memo(*, customer, owner, body, source):
    clean = (body or '').strip()
    with transaction.atomic():
        locked = Customer.objects.select_for_update().get(pk=customer.pk)
        locked.memo = body or ''
        locked.save(update_fields=['memo', 'updated_at'])
        if not clean:
            CustomerMemo.objects.filter(
                customer=locked, source=CustomerMemo.SOURCE_LEGACY).delete()
            return None
        occurred_at = timezone.now() if source == CustomerMemo.SOURCE_MANUAL else None
        memo, _ = CustomerMemo.objects.update_or_create(
            customer=locked,
            defaults={'owner': owner, 'source': source, 'body': clean,
                      'occurred_at': occurred_at})
        return memo
```

`CustomerSerializer.create/update`와 bulk 생성 루프에서 `memo` 입력이 있을 때 이 함수를 호출한다. 기존 고객 PATCH는 `SOURCE_LEGACY`, 배포 후 새 고객·bulk 생성은 `SOURCE_MANUAL`을 사용한다.

- [ ] **Step 4: Add a content-safe audit command**

```python
def digest(values):
    hasher = hashlib.sha256()
    for pk, body in values.iterator(chunk_size=500):
        hasher.update(str(pk).encode())
        hasher.update(b'\0')
        hasher.update((body or '').encode())
        hasher.update(b'\0')
    return hasher.hexdigest()


class Command(BaseCommand):
    def handle(self, *args, **options):
        old = Customer.objects.exclude(memo='').order_by('pk').values_list('pk', 'memo')
        new = CustomerMemo.objects.filter(
            source=CustomerMemo.SOURCE_LEGACY).order_by('customer_id').values_list('customer_id', 'body')
        result = {'old_count': old.count(), 'new_count': new.count(),
                  'old_hash': digest(old), 'new_hash': digest(new)}
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
        if result['old_count'] != result['new_count'] or result['old_hash'] != result['new_hash']:
            raise CommandError('기존 메모 이관 대조가 일치하지 않습니다.')
```

- [ ] **Step 5: Run focused tests and audit**

Run: `cd inpa_be && python manage.py test inpa.customers.tests.CustomerMemoCompatibilityTests -v 2 && python manage.py audit_customer_memos`

Expected: tests PASS, audit JSON의 count와 hash 쌍이 동일.

- [ ] **Step 6: Commit only after PM asks**

```bash
git add inpa_be/inpa/customers/memos.py inpa_be/inpa/customers/serializers.py inpa_be/inpa/customers/views.py inpa_be/inpa/customers/management/commands/audit_customer_memos.py inpa_be/inpa/customers/tests.py
git commit -m "feat(메모): 기존 단일 메모 안전 이관"
```

### Task 4: 프론트 API 계약과 메모 카드 컴포넌트

**Files:**
- Modify: `inpa_fe/lib/api.ts`
- Create: `inpa_fe/components/customer-memos.tsx`
- Create: `inpa_fe/components/__tests__/customer-memos.test.tsx`

**Interfaces:**
- Produces: `CustomerMemo`, `listCustomerMemos`, `createCustomerMemo`, `updateCustomerMemo`, `deleteCustomerMemo`.
- Produces: `<CustomerMemos customerId onCountChange />`, local `MemoListView`, local `MemoCard`.

- [ ] **Step 1: Write failing component tests**

```tsx
it('shows memo count, dates, edit marker, empty state, and keeps draft on save failure', async () => {
  api.listCustomerMemos.mockResolvedValue({ count: 1, next: null, previous: null, results: [memo] });
  api.createCustomerMemo.mockRejectedValue(new ApiError(500, 'SAVE_FAILED', '저장에 실패했어요.'));
  render(<CustomerMemos customerId={31} onCountChange={vi.fn()} />);
  expect(await screen.findByText('상담 메모 1개')).toBeTruthy();
  expect(screen.getByText('직접 작성')).toBeTruthy();
  expect(screen.getByText(/마지막 수정/)).toBeTruthy();
  await userEvent.click(screen.getByRole('button', { name: '메모 작성' }));
  await userEvent.type(screen.getByLabelText('새 메모'), '저장할 내용');
  await userEvent.click(screen.getByRole('button', { name: '메모 저장' }));
  expect(await screen.findByText('저장에 실패했어요.')).toBeTruthy();
  expect((screen.getByLabelText('새 메모') as HTMLTextAreaElement).value).toBe('저장할 내용');
});
```

- [ ] **Step 2: Run and verify missing component failure**

Run: `cd inpa_fe && npm run test:run -- components/__tests__/customer-memos.test.tsx`

Expected: module not found로 FAIL.

- [ ] **Step 3: Add exact API types and functions**

```ts
export type CustomerMemoSource = 'manual' | 'ai_summary' | 'legacy_migrated';

export interface CustomerMemo {
  id: number;
  source: CustomerMemoSource;
  source_label: string;
  body: string;
  occurred_at: string | null;
  created_at: string;
  updated_at: string;
  edited_at: string | null;
  revision: number;
}

export const listCustomerMemos = (customerId: number, page = 1) =>
  request<PaginatedResult<CustomerMemo>>('GET', `/customers/${customerId}/memos/?page=${page}`, undefined, true);
export const createCustomerMemo = (customerId: number, body: string) =>
  request<CustomerMemo>('POST', `/customers/${customerId}/memos/`, { body }, true);
export const updateCustomerMemo = (customerId: number, memo: CustomerMemo, body: string) =>
  request<CustomerMemo>('PATCH', `/customers/${customerId}/memos/${memo.id}/`,
    { body, revision: memo.revision }, true);
export const deleteCustomerMemo = async (customerId: number, memoId: number) =>
  requestVoid('DELETE', `/customers/${customerId}/memos/${memoId}/`, true);
```

- [ ] **Step 4: Implement the component states**

```tsx
interface Props {
  customerId: number;
  onCountChange: (count: number) => void;
}

interface MemoListViewProps {
  data: PaginatedResult<CustomerMemo> | null;
  mode: 'list' | 'create';
  draft: string;
  error: string | null;
  onDraftChange: (value: string) => void;
  onCreate: () => Promise<void>;
  onEdit: (memo: CustomerMemo, body: string) => Promise<void>;
  onDelete: (memoId: number) => Promise<void>;
  onReload: () => Promise<void>;
  onModeChange: (mode: 'list' | 'create') => void;
}

export function CustomerMemos({ customerId, onCountChange }: Props) {
  const [data, setData] = useState<PaginatedResult<CustomerMemo> | null>(null);
  const [draft, setDraft] = useState('');
  const [mode, setMode] = useState<'list' | 'create'>('list');
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    const result = await listCustomerMemos(customerId);
    setData(result);
    onCountChange(result.count);
  }, [customerId, onCountChange]);

  async function saveNew() {
    try {
      const created = await createCustomerMemo(customerId, draft);
      setData((current) => current && ({ ...current, count: current.count + 1,
        results: [created, ...current.results] }));
      setDraft('');
      setMode('list');
      setError(null);
      onCountChange((data?.count ?? 0) + 1);
    } catch (value) {
      setError(value instanceof ApiError ? value.message : '메모를 저장하지 못했어요. 다시 저장해 주세요.');
    }
  }

  async function saveEdit(memo: CustomerMemo, body: string) {
    try {
      const changed = await updateCustomerMemo(customerId, memo, body);
      setData((current) => current && ({ ...current,
        results: current.results.map((item) => item.id === changed.id ? changed : item) }));
      setError(null);
    } catch (value) {
      if (value instanceof ApiError && value.code === 'MEMO_EDIT_CONFLICT') await reload();
      setError(value instanceof ApiError ? value.message : '최신 메모를 다시 확인해 주세요.');
    }
  }

  async function removeMemo(memoId: number) {
    if (!window.confirm('이 메모를 삭제할까요?')) return;
    await deleteCustomerMemo(customerId, memoId);
    setData((current) => current && ({ ...current, count: current.count - 1,
      results: current.results.filter((item) => item.id !== memoId) }));
    onCountChange(Math.max(0, (data?.count ?? 1) - 1));
  }

  return <MemoListView data={data} mode={mode} draft={draft} error={error}
    onDraftChange={setDraft} onCreate={saveNew} onEdit={saveEdit}
    onDelete={removeMemo} onReload={reload} onModeChange={setMode} />;
}
```

같은 파일에 `function MemoListView(props: MemoListViewProps)`와 `function MemoCard({ memo, onEdit, onDelete })`를 정의한다. `data === null`이면 3개 skeleton, `error`와 data 없음이면 재시도, `count === 0`이면 `첫 상담 메모를 남겨보세요.`와 `메모 작성`, 그 외에는 카드 목록과 `next`가 있을 때 `이전 메모 더 보기`를 렌더한다. 메모 카드는 local edit draft와 저장 중 상태를 소유하고 실패하면 draft를 유지한다. 표시 시각은 `occurred_at ?? created_at`, 기존 메모는 `옮긴 시각`, AI 메모는 `상담`, 직접 메모는 `작성`으로 표기한다. 날짜는 `Intl.DateTimeFormat('ko-KR', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Seoul' })`로 통일한다. `edited_at`이 있으면 `마지막 수정 {포맷된 시각} · 수정됨`을 추가한다.

- [ ] **Step 5: Run component tests**

Run: `cd inpa_fe && npm run test:run -- components/__tests__/customer-memos.test.tsx`

Expected: loading·empty·create·edit·delete·409·pagination 테스트 PASS.

- [ ] **Step 6: Commit only after PM asks**

```bash
git add inpa_fe/lib/api.ts inpa_fe/components/customer-memos.tsx inpa_fe/components/__tests__/customer-memos.test.tsx
git commit -m "feat(메모): 여러 메모 카드 UI 추가"
```

### Task 5: 고객 상세 정보 구조 통합

**Files:**
- Modify: `inpa_be/inpa/customers/serializers.py`
- Modify: `inpa_be/inpa/customers/views.py`
- Modify: `inpa_fe/lib/api.ts`
- Modify: `inpa_fe/app/customer/[id]/page.tsx`
- Test: `inpa_be/inpa/customers/tests.py`
- Test: `inpa_fe/components/__tests__/customer-memos.test.tsx`

**Interfaces:**
- Adds `memo_count: number` to customer list/detail.
- Keeps URL key `tab=history`; visible label changes to `기록`.

- [ ] **Step 1: Write failing count and integration tests**

```python
def test_customer_detail_returns_real_memo_count(self):
    CustomerMemo.objects.create(owner=self.user, customer=self.customer,
                                source='manual', body='하나', occurred_at=timezone.now())
    response = self.client.get(f'/api/v1/customers/{self.customer.id}/')
    self.assertEqual(response.data['memo_count'], 1)
```

```tsx
it('moves memo from info to 기록 and preserves activity timeline', async () => {
  render(<CustomerDetailPage />);
  expect(await screen.findByRole('tab', { name: '기록' })).toBeTruthy();
  expect(screen.queryByRole('button', { name: '메모 저장' })).toBeNull();
  await userEvent.click(screen.getByRole('tab', { name: '기록' }));
  expect(screen.getByRole('tab', { name: '메모 2개' })).toBeTruthy();
  expect(screen.getByRole('tab', { name: '활동' })).toBeTruthy();
});
```

- [ ] **Step 2: Run and verify failures**

Run: `cd inpa_be && python manage.py test inpa.customers.tests.CustomerMemoCountTests -v 2`

Run: `cd inpa_fe && npm run test:run -- components/__tests__/customer-memos.test.tsx`

Expected: `memo_count`와 `기록` UI가 없어 FAIL.

- [ ] **Step 3: Annotate and serialize memo count**

```python
def get_queryset(self):
    return (super().get_queryset()
            .select_related('job_code')
            .prefetch_related('tags', 'family_members', 'medical_histories', 'consent_logs')
            .annotate(memo_count=models.Count('memos', distinct=True)))
```

두 customer serializer에 아래 필드와 field name을 추가한다.

```python
memo_count = serializers.IntegerField(read_only=True)
```

- [ ] **Step 4: Integrate the existing customer page**

```tsx
const TABS = [
  { key: 'analysis', label: '분석' },
  { key: 'switch', label: '여러 증권 비교' },
  { key: 'info', label: '정보' },
  { key: 'contract', label: '계약' },
  { key: 'history', label: '기록' },
] as const;
```

`InfoTab`에서 `memo`, `savingMemo`, `saveMemo`, 메모 textarea 카드를 제거하고 상세정보 카드를 전체 폭으로 유지한다. `HistoryTab`은 다음 계약으로 바꾼다.

```tsx
function HistoryTab({ customerId, memoCount, onMemoCountChange }: {
  customerId: number;
  memoCount: number;
  onMemoCountChange: (count: number) => void;
}) {
  const [view, setView] = useState<'memos' | 'activity'>('memos');
  return <div>
    <div role="tablist" aria-label="고객 기록">
      <button role="tab" aria-selected={view === 'memos'} onClick={() => setView('memos')}>
        메모 {memoCount}개
      </button>
      <button role="tab" aria-selected={view === 'activity'} onClick={() => setView('activity')}>
        활동
      </button>
    </div>
    {view === 'memos'
      ? <CustomerMemos customerId={customerId} onCountChange={onMemoCountChange} />
      : <CustomerActivity customerId={customerId} />}
  </div>;
}
```

기존 `HistoryTab` 본문은 `CustomerActivity`로 이름만 바꾸고 동작은 보존한다. 고객 요약 카드에는 `/customer/{id}?tab=history&view=memos` 링크로 `메모 N개`를 추가한다.

- [ ] **Step 5: Run focused and full release checks**

Run: `cd inpa_be && python manage.py test inpa.customers inpa.analytics -v 1`

Run: `cd inpa_fe && npm run test:run -- components/__tests__/customer-memos.test.tsx && npm run lint:copy && npm run build`

Expected: 모두 PASS, Next build에서 기존 고객 상세 route 유지.

- [ ] **Step 6: Commit only after PM asks**

```bash
git add inpa_be/inpa/customers/serializers.py inpa_be/inpa/customers/views.py inpa_be/inpa/customers/tests.py inpa_fe/lib/api.ts 'inpa_fe/app/customer/[id]/page.tsx' inpa_fe/components/__tests__/customer-memos.test.tsx
git commit -m "feat(고객): 기록 탭에 여러 메모 통합"
```

### Task 6: Release 1 런타임·마이그레이션 검증

**Files:**
- Modify only if findings require fixes: files from Tasks 1-5

**Interfaces:**
- Produces a verified multiple-memo release; no recording code yet.

- [ ] **Step 1: Run backend full checks**

Run: `cd inpa_be && python manage.py check && python manage.py test inpa`

Expected: system check 0 issues, entire suite PASS.

- [ ] **Step 2: Prove PostgreSQL migration and concurrency**

Run: `cd inpa_be && DJANGO_SETTINGS_MODULE=config.settings.test_postgres python manage.py migrate && DJANGO_SETTINGS_MODULE=config.settings.test_postgres python manage.py test inpa.customers.tests.CustomerMemoApiTests`

Expected: migration and focused PostgreSQL tests PASS.

- [ ] **Step 3: Call the API with a local server**

```bash
curl -sS -H "Authorization: Token $INPA_TEST_TOKEN" http://127.0.0.1:8000/api/v1/customers/$INPA_TEST_CUSTOMER_ID/memos/
```

Expected: JSON 최상위에 `count`, `next`, `previous`, `results` 키가 있고 다른 owner의 메모 본문은 없다.

- [ ] **Step 4: Run frontend full checks and browser QA**

Run: `cd inpa_fe && npm run test:run && npm run lint:copy && npm run build && npm run dev`

Expected: tests·copy lint·build PASS. Browser에서 desktop/mobile 모두 `기록`, `메모 N개`, 작성·수정·삭제·빈 상태·오류 상태가 기존 디자인과 일치.

- [ ] **Step 5: Run migration content audit**

Run: `cd inpa_be && python manage.py audit_customer_memos`

Expected: old/new count와 SHA-256 hash 일치.

- [ ] **Step 6: Stop before production**

프로덕션 migration·배포는 실행하지 않는다. 결과를 `Changed / Verified by / Result / Unverified` 형식으로 PM에게 보고하고 별도 승인을 요청한다.
