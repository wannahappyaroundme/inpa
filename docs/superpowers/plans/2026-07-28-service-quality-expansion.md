# 인파 서비스 품질 확장 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 판촉물 가격·장바구니를 제외하고 프로필·게시판, 담보 기준, 화법, 무료 1개월 휴대전화 인증, 상담 녹음 30일·다운로드를 서비스 가능한 수준으로 구현한다.

**Architecture:** 기존 Django/DRF 단일 API 게이트와 Next.js 클라이언트 구조를 유지한다. 권한·가격·혜택·보존기간 같은 판단은 서버가 소유하고 화면은 서버 응답을 표현한다. 스키마와 동의 의미가 다른 다섯 릴리스를 독립 작업으로 만들되 한 브랜치에서 순서대로 통합한다.

**Tech Stack:** Django 5.2 LTS, DRF, PostgreSQL/SQLite, Next.js 16.2, React 19.2, TypeScript, Tailwind v4, Vitest, SOLAPI REST v4.

## Global Constraints

- 구현 범위는 설계서의 릴리스 A-E다. 판촉물 가격·장바구니는 구현하지 않는다.
- 인파는 담보명·분류·단위만 제공하며 기준금액을 추천하거나 자동 입력하지 않는다.
- 담보 기본값은 전체 상품·전연령·성별 공통이며, 생명·손해·연령·성별 예외가 더 구체적인 순서로 우선한다.
- 화법은 가입의 다음 행동을 분명히 하되 보험 가입·보험금 지급·우월성·절감 효과를 단정하지 않는다.
- 기본 화법은 운영 원본이고 사용자가 덮어쓰지 않는다. 개인 화법만 소유자 범위로 CRUD한다.
- 회원가입은 휴대전화 중복으로 막지 않는다. 무료 1개월 활성화 직전에만 SMS 인증과 수혜 이력을 확인한다.
- SMS 인증은 번호 통제 확인이며 사람의 영구 고유식별이라고 표현하지 않는다.
- SOLAPI 비밀값은 `SOLAPI_API_KEY`, `SOLAPI_API_SECRET`, `SOLAPI_SENDER_NUMBER` 환경변수만 사용한다.
- 휴대전화 식별 HMAC은 `PHONE_IDENTITY_HMAC_KEY`를 사용하며 원문 번호와 인증번호를 로그에 남기지 않는다.
- 녹음 안내 화면의 사용자는 설계사다. 설계사가 보험 가입 희망자에게 문구를 직접 읽고 동의를 확인한다.
- 고객 본인 최신 전자 동의와 설계사의 매회 구두고지 완료 확인이 모두 있어야 녹음을 시작한다.
- 기존 녹음은 7일을 유지하고 새 동의문으로 생성한 신규 녹음만 30일 보관한다.
- 사용자 작성 화법 본문, 고객명, 전화번호 원문, 인증번호, 음성 내용, 서명 URL을 분석 이벤트·일반 로그에 저장하지 않는다.
- 서비스 화면은 light-fixed이며 사용자 문구에 em dash(`—`)를 넣지 않는다.
- 모든 새 동작은 실패하는 테스트를 먼저 확인한 후 최소 구현하고, 관련 테스트를 다시 통과시킨다.
- 프로젝트 규칙에 따라 사용자의 별도 요청 전에는 커밋·푸시·PR·배포를 하지 않는다.

---

### Task 1: 프로필 성명과 게시판 본인 관리

**Files:**
- Modify: `inpa_be/inpa/boards/serializers.py`
- Modify: `inpa_be/inpa/boards/views.py`
- Modify: `inpa_be/inpa/boards/tests.py`
- Modify: `inpa_fe/lib/api.ts`
- Modify: `inpa_fe/app/settings/account/page.tsx`
- Modify: `inpa_fe/app/boards/page.tsx`
- Modify: `inpa_fe/app/boards/[id]/page.tsx`
- Create: `inpa_fe/components/board-item-menu.tsx`
- Create: `inpa_fe/components/__tests__/board-item-menu.test.tsx`

**Interfaces:**
- Consumes: 기존 `Profile.name`, `Profile.affiliation`, `Profile.title`, `Profile.phone`, 게시글·댓글 작성자/관리자 권한.
- Produces: 게시글·댓글 응답의 `can_manage: boolean`, 성명 우선 작성자 표시, 재사용 가능한 `BoardItemMenu`.

- [ ] **Step 1: 게시판 응답 권한 테스트를 먼저 추가한다**

`inpa_be/inpa/boards/tests.py`에 작성자·타인·관리자 각각 목록·상세·댓글 응답의 `can_manage`와 성명 표시를 검증한다.

```python
def test_feed_exposes_server_owned_manage_permission(self):
    self.user_a.profile.name = '황예진'
    self.user_a.profile.save(update_fields=['name'])
    own = self.client_a.get('/api/v1/board/posts/').json()['results'][0]
    other = self.client_b.get('/api/v1/board/posts/').json()['results'][0]
    admin = self.client_admin.get('/api/v1/board/posts/').json()['results'][0]
    self.assertEqual(own['author']['display_name'], '황예진')
    self.assertTrue(own['can_manage'])
    self.assertFalse(other['can_manage'])
    self.assertTrue(admin['can_manage'])
```

댓글 테스트는 최상위 댓글과 `replies` 모두 같은 request context로 `can_manage`가 계산되는지 확인한다.

- [ ] **Step 2: 백엔드 RED를 확인한다**

Run:

```bash
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py test \
  inpa.boards.tests.PostEditDeleteTests \
  inpa.boards.tests.CommentTests -v 2
```

Expected: `can_manage` 필드가 없고 작성자명이 이메일 앞부분이라 FAIL.

- [ ] **Step 3: 서버가 관리 권한과 성명을 계산하게 한다**

`serializers.py`에 공통 헬퍼를 추가한다.

```python
def _can_manage(obj, request):
    if request is None or not request.user.is_authenticated:
        return False
    from inpa.core.permissions import _is_admin
    return obj.author_id == request.user.id or _is_admin(request.user)

def _author_display(author):
    if author is None:
        return '탈퇴한 사용자'
    name = (getattr(getattr(author, 'profile', None), 'name', '') or '').strip()
    return name or '이름 미입력'
```

`PostFeedSerializer`, `PostDetailSerializer`, `CommentSerializer`에 `can_manage = SerializerMethodField()`를 넣고 `context['request']`를 사용한다. `PostViewSet.create()` 응답에도 request context를 전달한다. 게시글·댓글 queryset은 `author__profile`을 `select_related`해 추가 쿼리를 막는다.

- [ ] **Step 4: 백엔드 GREEN을 확인한다**

Run:

```bash
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py test inpa.boards -v 1
```

Expected: PASS, 기존 작성자 204·타인 403 권한 테스트도 유지.

- [ ] **Step 5: 메뉴 컴포넌트의 FE 실패 테스트를 작성한다**

`board-item-menu.test.tsx`에서 실제 컴포넌트를 렌더한다.

```tsx
it("shows edit and delete for manageable items", async () => {
  render(<BoardItemMenu canManage editHref="/boards/1/edit"
    onDelete={() => undefined} onReport={() => undefined} />);
  await userEvent.click(screen.getByRole("button", { name: "더보기" }));
  expect(screen.getByRole("menuitem", { name: "수정" })).toBeInTheDocument();
  expect(screen.getByRole("menuitem", { name: "삭제" })).toBeInTheDocument();
  expect(screen.queryByRole("menuitem", { name: "신고" })).not.toBeInTheDocument();
});
```

타인 항목은 신고만 보이고 Escape로 닫히며 호출 버튼으로 포커스가 복귀하는 테스트를 별도로 둔다.

- [ ] **Step 6: FE RED를 확인한다**

Run:

```bash
npm run test:run -- components/__tests__/board-item-menu.test.tsx
```

Expected: 모듈이 없어 FAIL.

- [ ] **Step 7: 게시판 화면을 `can_manage` 계약으로 전환한다**

`lib/api.ts`의 `PostFeedItem`, `PostDetail`, `CommentItem`에 `can_manage: boolean`을 추가한다. `BoardItemMenu`는 `role="menu"`/`menuitem`, Escape 닫기, 외부 클릭 닫기, 포커스 복귀를 제공한다.

목록과 상세에서 다음을 삭제한다.

```ts
const [currentUserId] = useState<number | null>(null);
const isOwn = currentUserId !== null && item.author.id === currentUserId;
```

대신 `item.can_manage`를 사용한다. 삭제 중에는 해당 버튼을 비활성화하고, 실패하면 항목을 제거하지 않은 채 `다시 시도해 주세요`를 표시한다.

- [ ] **Step 8: 계정 설정에 단일 기본 프로필 카드를 만든다**

`settings/account/page.tsx` state에 `name`, `affiliation`, `title`을 추가하고 프로필 조회 시 채운다. 기존 전화번호 단독 카드를 `기본 프로필` 카드로 바꿔 네 필드를 한 번에 저장한다.

```ts
await patch({
  name: name.trim(),
  affiliation: affiliation.trim(),
  title: title.trim(),
  phone: phone.trim(),
}, "기본 프로필을 저장했어요");
```

라벨은 `성명`, `소속`, `직책`, `휴대전화`를 사용한다. 성명은 `maxLength={30}`, 휴대전화는 기존 숫자·하이픈 입력 제한을 유지한다.

- [ ] **Step 9: Task 1 전체 검증**

Run:

```bash
npm run test:run -- components/__tests__/board-item-menu.test.tsx
npm run build
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py check
```

Expected: 모두 PASS. 브라우저에서 계정 저장, 내 글 목록·상세·댓글 삭제, 타인 신고 메뉴를 확인한다.

---

### Task 2: 담보 기준 데이터 모델·카탈로그·선택 규칙

**Files:**
- Modify: `inpa_be/inpa/customers/models.py`
- Modify: `inpa_be/inpa/customers/serializers.py`
- Modify: `inpa_be/inpa/customers/views.py`
- Modify: `inpa_be/inpa/customers/urls.py`
- Modify: `inpa_be/inpa/analysis/baselines.py`
- Modify: `inpa_be/inpa/analysis/views.py`
- Modify: `inpa_be/inpa/analysis/compare.py`
- Modify: `inpa_be/inpa/analysis/test_baselines.py`
- Modify: `inpa_be/inpa/customers/tests.py`
- Create: `inpa_be/inpa/customers/migrations/0023_baseline_catalog_scope.py`

**Interfaces:**
- Consumes: `AnalysisDetail` 표준 담보 트리와 기존 `PlannerBaseline`.
- Produces: `GET /api/v1/baseline-catalog/`, `POST /api/v1/planner-baselines/batch/`, `PlannerBaselineRevision`, 표준 담보 FK와 고정된 선택 우선순위.

- [ ] **Step 1: 선택 규칙 실패 테스트를 추가한다**

`analysis/test_baselines.py`에 다음 literal 우선순위를 검증한다.

```python
def test_select_baseline_falls_back_by_product_age_and_gender(self):
    rows = [
        baseline(product_group=0, age_band='all', gender=None, label='all-default'),
        baseline(product_group=0, age_band='30s', gender=None, label='all-30-common'),
        baseline(product_group=2, age_band='all', gender=1, label='nonlife-all-male'),
        baseline(product_group=2, age_band='30s', gender=1, label='nonlife-30-male'),
    ]
    chosen = select_baseline(rows, insurance_type=2, age_band='30s', gender=1)
    self.assertEqual(chosen.label, 'nonlife-30-male')
```

각 더 구체적인 행을 하나씩 제거하면서 `nonlife-all-male`, `all-30-common`, `all-default`로 내려가는 별도 케이스를 둔다. `insurance_type=0` 공통 담보도 전체 상품 기본값을 선택해야 한다.

- [ ] **Step 2: 선택 규칙 RED를 확인한다**

Run:

```bash
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py test \
  inpa.analysis.test_baselines -v 2
```

Expected: 상품 전체 코드와 `all` 연령이 없어 FAIL.

- [ ] **Step 3: 모델과 유일 제약을 구현한다**

`PlannerBaseline`에 다음을 추가한다.

```python
PRODUCT_GROUP_ALL = 0
AGE_ALL = 'all'
analysis_detail = models.ForeignKey(
    'analysis.AnalysisDetail',
    null=True, blank=True, on_delete=models.PROTECT,
    related_name='planner_baselines',
)
```

새 쓰기는 `analysis_detail`을 필수로 하고 `coverage_key`는 선택한 표준 담보명으로 서버가 채운다. 기존 `coverage_key`는 호환 스냅샷으로 유지한다.

기존 nullable gender 유일 제약을 다음 두 제약으로 교체한다.

```python
models.UniqueConstraint(
    fields=['owner', 'analysis_detail', 'product_group', 'age_band'],
    condition=models.Q(gender__isnull=True, analysis_detail__isnull=False),
    name='uniq_baseline_common_gender',
)
models.UniqueConstraint(
    fields=['owner', 'analysis_detail', 'product_group', 'age_band', 'gender'],
    condition=models.Q(gender__isnull=False, analysis_detail__isnull=False),
    name='uniq_baseline_specific_gender',
)
```

`PlannerBaselineRevision`은 `owner=OneToOneField`, `revision=PositiveBigIntegerField(default=0)`, `updated_at`을 가진다.

- [ ] **Step 4: 마이그레이션과 backfill을 만든다**

마이그레이션은 기존 `coverage_key == AnalysisDetail.name`이 유일하게 일치할 때 FK를 채운다. 이름이 0개 또는 2개 이상 일치하면 FK를 비워 기존 직접 입력으로 보존한다. 기존 age_band는 유지하며 새 기본 행만 `all`을 사용한다. 중복 공통행은 값이 완전히 같을 때 가장 오래된 한 행만 보존하고, 값이 다르면 migration을 실패시켜 수동 검토가 필요함을 알린다.

Run:

```bash
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py makemigrations --check
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py migrate
```

Expected: 적용할 누락 migration 없음, migrate 성공.

- [ ] **Step 5: 선택 함수를 고정된 specificity 점수로 구현한다**

`select_baseline()`은 활성·출처 있는 후보만 받고 다음 튜플을 작은 값 우선으로 정렬한다.

```python
product_rank = 0 if row.product_group == exact_group else 1
age_rank = 0 if row.age_band == age_band else 1
gender_rank = 0 if row.gender == gender else 1
rank = (product_rank, age_rank, gender_rank)
```

허용 후보는 상품군 `(exact_group, ALL)`, 연령 `(exact_age, all)`, 성별 `(exact_gender, None)` 안에 있는 행뿐이다. 동률이 둘 이상이면 잘못된 데이터이므로 `None`을 반환해 거짓 판정을 막는다.

- [ ] **Step 6: 카탈로그·batch API 실패 테스트를 작성한다**

`customers/tests.py`에 다음을 검증한다.

- 카탈로그가 대분류·중분류·담보 정렬을 유지하고 미검증 금액을 포함하지 않음
- 사용자 기준만 합쳐지고 타인 값은 보이지 않음
- 빈 값 change는 행을 만들지 않음
- 같은 revision의 여러 change가 한 transaction으로 저장됨
- 오래된 revision은 `409 baseline_revision_conflict`
- 타인/존재하지 않는 detail ID는 400
- batch 실패 시 일부 행도 저장되지 않음

요청 계약:

```json
{
  "revision": 3,
  "changes": [
    {
      "analysis_detail_id": 10,
      "product_group": 0,
      "age_band": "all",
      "gender": null,
      "recommend_min": "5000",
      "recommend_max": null,
      "unit": 1
    }
  ]
}
```

- [ ] **Step 7: API RED를 확인한다**

Run:

```bash
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py test \
  inpa.customers.tests.PlannerBaselineCatalogTests -v 2
```

Expected: route와 revision 모델이 없어 FAIL.

- [ ] **Step 8: 카탈로그와 원자적 batch 저장을 구현한다**

`BaselineCatalogView` GET은 표준 트리와 현재 사용자의 FK 연결 기준을 한 번에 반환한다.

```json
{
  "revision": 3,
  "categories": [
    {
      "id": 1,
      "name": "진단비",
      "subcategories": [
        {
          "id": 2,
          "name": "암",
          "details": [
            {"id": 10, "name": "일반암 진단비", "unit": 1, "baselines": []}
          ]
        }
      ]
    }
  ]
}
```

POST batch는 `transaction.atomic()` 안에서 revision 행을 `select_for_update()`하고 요청 revision을 비교한다. 각 change는 `update_or_create`; `recommend_min`과 `recommend_max`가 모두 null이면 해당 scope 행을 삭제한다. `coverage_key`, `baseline_source='planner'`, `owner`는 서버가 강제한다. 모두 성공한 뒤 revision을 1 증가시킨다.

- [ ] **Step 9: 분석·비교 조회를 FK 우선으로 전환한다**

히트맵과 비교에서 해당 `AnalysisDetail`의 후보를 `analysis_detail_id`로 찾는다. FK가 없는 기존 행은 같은 `coverage_key` exact match로만 호환한다. 공통 담보 `insurance_type=0`도 `PRODUCT_GROUP_ALL` 후보를 선택할 수 있게 한다.

- [ ] **Step 10: Task 2 전체 검증**

Run:

```bash
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py test \
  inpa.analysis inpa.customers -v 1
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py check
```

Expected: PASS. PostgreSQL 별도 테스트 환경에서 두 공통 gender 행의 동시 삽입 중 하나가 유일 제약으로 실패해야 한다.

---

### Task 3: 담보 전체 기준표 화면

**Files:**
- Modify: `inpa_fe/lib/api.ts`
- Create: `inpa_fe/lib/baseline-editor.ts`
- Create: `inpa_fe/lib/baseline-editor.test.ts`
- Rewrite: `inpa_fe/app/settings/baseline/page.tsx`
- Create: `inpa_fe/components/baseline-detail-drawer.tsx`
- Create: `inpa_fe/components/__tests__/baseline-detail-drawer.test.tsx`

**Interfaces:**
- Consumes: Task 2의 `GET /baseline-catalog/`, `POST /planner-baselines/batch/`.
- Produces: 전체 담보 카탈로그 편집기, 변경 집합 계산, 기본·상세 기준 UI.

- [ ] **Step 1: 편집 상태 실패 테스트를 작성한다**

`baseline-editor.test.ts`에 서버 카탈로그와 현재 입력 상태의 diff를 literal로 검증한다.

```ts
it("emits only changed non-empty scopes and deletes cleared scopes", () => {
  const changes = buildBaselineChanges(serverRows, draftRows);
  expect(changes).toEqual([
    {
      analysis_detail_id: 10,
      product_group: 0,
      age_band: "all",
      gender: null,
      recommend_min: "5000",
      recommend_max: null,
      unit: 1,
    },
    {
      analysis_detail_id: 11,
      product_group: 0,
      age_band: "all",
      gender: null,
      recommend_min: null,
      recommend_max: null,
      unit: 1,
    },
  ]);
});
```

검색은 대·중·담보명 모두 찾고, `입력한 담보만`은 값이 하나라도 있는 detail만 남기며, 빈 문자열은 null로 정규화하는 테스트를 둔다.

- [ ] **Step 2: FE RED를 확인한다**

Run:

```bash
npm run test:run -- lib/baseline-editor.test.ts
```

Expected: 모듈이 없어 FAIL.

- [ ] **Step 3: API 타입과 순수 편집 로직을 구현한다**

`ProductGroup`에 `0`을 추가하고 `BaselineAgeBand = "all" | "20s" | "30s" | "40s" | "50s" | "60s+"`를 정의한다. 카탈로그 응답과 batch payload 타입·함수를 `lib/api.ts`에 추가한다.

`baseline-editor.ts`는 다음 순수 함수만 소유한다.

- `catalogToDraft(catalog)`
- `normalizeBaselineAmount(value)`
- `buildBaselineChanges(server, draft)`
- `filterBaselineCatalog(catalog, query, configuredOnly)`
- `countChangedScopes(server, draft)`

- [ ] **Step 4: 상세 드로어 접근성 실패 테스트를 작성한다**

실제 드로어를 렌더해 제목, 상품 범위, 연령, 성별, 기준금액, 선택형 넉넉 기준금액을 확인한다. Escape 닫기와 호출 버튼 포커스 복귀를 테스트한다. 빈 상세값 삭제가 `onChange`에 null scope를 전달하는지 확인한다.

- [ ] **Step 5: 상세 드로어와 전체 페이지를 구현한다**

기본 페이지는 다음 순서로 렌더한다.

1. 제목과 설명
2. 담보 검색
3. `입력한 담보만` 토글
4. 카테고리 접힘 영역
5. 담보명+기준금액+상세 설정 행
6. 변경 N개와 고정 저장 버튼

모바일은 카드 행, `sm` 이상은 table semantics를 사용한다. 기본 행은 `product_group=0`, `age_band='all'`, `gender=null`이다. `넉넉 기준금액`은 선택 입력이며 자동 계산하지 않는다.

저장 중 입력·버튼을 비활성화한다. 409이면 로컬 값을 자동 덮어쓰지 않고 다음 문구와 새로 불러오기 버튼을 표시한다.

> 다른 화면에서 기준이 변경됐어요. 최신 내용을 확인한 뒤 다시 저장해 주세요.

- [ ] **Step 6: FE GREEN과 빌드를 확인한다**

Run:

```bash
npm run test:run -- lib/baseline-editor.test.ts \
  components/__tests__/baseline-detail-drawer.test.tsx
npm run build
```

Expected: PASS. 실제 브라우저에서 360px·1440px 너비, 검색, 카테고리 접기, 기본값 저장, 상세 예외, 미저장 이탈 경고를 확인한다.

---

### Task 4: 개인 화법 저장 API

**Files:**
- Create: `inpa_be/inpa/talks/__init__.py`
- Create: `inpa_be/inpa/talks/apps.py`
- Create: `inpa_be/inpa/talks/models.py`
- Create: `inpa_be/inpa/talks/serializers.py`
- Create: `inpa_be/inpa/talks/views.py`
- Create: `inpa_be/inpa/talks/urls.py`
- Create: `inpa_be/inpa/talks/admin.py`
- Create: `inpa_be/inpa/talks/tests.py`
- Create: `inpa_be/inpa/talks/migrations/__init__.py`
- Create: `inpa_be/inpa/talks/migrations/0001_initial.py`
- Modify: `inpa_be/config/settings/base.py`
- Modify: `inpa_be/config/urls.py`

**Interfaces:**
- Consumes: 인증 사용자와 프론트 기본 화법의 stable `source_key`.
- Produces: `/api/v1/talk-templates/` 개인 CRUD와 `/api/v1/talk-template-preferences/` 기본 화법 숨김·복구.

- [ ] **Step 1: 소유자 격리 실패 테스트를 작성한다**

`talks/tests.py`에 다음을 테스트한다.

```python
def test_personal_template_is_owner_scoped(self):
    created = self.client_a.post('/api/v1/talk-templates/', {
        'title': '내 마무리',
        'body': '{고객명} 고객님, 오늘 신청 절차를 이어가겠습니다.',
        'category': 'closing',
        'channel': 'message',
        'sort_order': 10,
    }, format='json')
    self.assertEqual(created.status_code, 201)
    self.assertEqual(
        self.client_b.get('/api/v1/talk-templates/').json()['results'], [])
    self.assertEqual(
        self.client_b.delete(
            f"/api/v1/talk-templates/{created.json()['id']}/").status_code,
        404,
    )
```

빈 제목·본문, 5,000자 초과, 허용되지 않은 채널, XSS 문자열이 응답에서 문자열로만 유지되는지, soft delete 후 목록 제외, 기본 source_key 숨김·복구를 각각 검증한다.

- [ ] **Step 2: 백엔드 RED를 확인한다**

Run:

```bash
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py test inpa.talks -v 2
```

Expected: 앱과 route가 없어 FAIL.

- [ ] **Step 3: 개인 화법 모델을 구현한다**

`PersonalTalkTemplate`:

```python
owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
source_key = models.CharField(max_length=80, null=True, blank=True)
title = models.CharField(max_length=100)
body = models.TextField(max_length=5000)
category = models.CharField(max_length=40)
channel = models.CharField(max_length=20, choices=(('message', '메시지'), ('call', '통화')))
sort_order = models.IntegerField(default=0)
is_active = models.BooleanField(default=True)
is_deleted = models.BooleanField(default=False)
created_at = models.DateTimeField(auto_now_add=True)
updated_at = models.DateTimeField(auto_now=True)
```

`TalkTemplatePreference`는 `(owner, source_key)` 유일, `is_hidden` boolean을 가진다. 사용자가 시스템 원본을 수정하지 않도록 source_key는 출처 추적일 뿐 기본 템플릿 행과 FK를 맺지 않는다.

- [ ] **Step 4: API를 소유자 범위로 구현한다**

`OwnedQuerySetMixin + IsOwner`를 사용해 개인 템플릿 CRUD를 구현한다. create 시 owner를 서버가 주입한다. destroy는 `is_deleted=True` soft delete다. preference PUT body는 다음 계약을 사용한다.

```json
{"source_key": "closing-next-step", "is_hidden": true}
```

목록 응답은 `results`와 `hidden_source_keys`를 함께 반환한다. 정렬은 `sort_order, created_at`.

- [ ] **Step 5: 백엔드 GREEN을 확인한다**

Run:

```bash
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py test inpa.talks -v 1
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py check
```

Expected: PASS, migration 누락 없음.

---

### Task 5: 화법 30개 교정·내 템플릿 UI·공유

**Files:**
- Modify: `inpa_fe/lib/copy-library.ts`
- Modify: `inpa_fe/lib/api.ts`
- Modify: `inpa_fe/lib/clipboard.ts`
- Rewrite: `inpa_fe/app/scripts/page.tsx`
- Create: `inpa_fe/lib/talk-template-view-model.ts`
- Create: `inpa_fe/lib/talk-template-view-model.test.ts`
- Create: `inpa_fe/components/talk-template-editor.tsx`
- Create: `inpa_fe/components/talk-template-share.tsx`
- Create: `inpa_fe/components/__tests__/talk-template-editor.test.tsx`
- Create: `inpa_fe/components/__tests__/talk-template-share.test.tsx`
- Modify: `inpa_fe/components/__tests__/copy-library.test.tsx`
- Modify: `inpa_fe/scripts/check-copy.js`
- Modify: `inpa_fe/scripts/check-copy.test.js`

**Interfaces:**
- Consumes: Task 4 개인 화법 API와 기존 `{고객명}`, `{설계사명}`, `{소속직책}` 변수.
- Produces: stable key를 가진 기본 화법 30개, 개인 CRUD, 모든 기기의 인파 공유창.

- [ ] **Step 1: 카피 실패 테스트를 강화한다**

`copy-library.test.tsx`는 렌더된 30개 기본 문구를 모두 검사한다. 다음 표현은 발견 시 실패한다.

```ts
const forbiddenClaims = [
  "마음에 걸리는",
  "편하실 때",
  "천천히 생각",
  "결정은 고객님 몫",
  "보험료를 아낀 분도 많아요",
  "받을 수 있는 돈",
  "어느 쪽이 유리",
  "예전 상품엔 약한",
  "굳이 바꿀 필요 없어",
  "뭘 권하려는 건 아니고",
];
```

각 템플릿은 stable `key`, title, body를 가져야 하고 key 30개가 유일해야 한다. 고객 행동을 요청하지 않는 템플릿을 찾기 위해 각 문구가 질문 또는 `확인`, `선택`, `진행`, `예약`, `준비`, `보내` 중 하나를 포함하는지도 검사한다.

- [ ] **Step 2: 카피 RED를 확인한다**

Run:

```bash
npm run test:run -- components/__tests__/copy-library.test.tsx
npm run lint:copy
```

Expected: 현재 수동적·단정적 표현 때문에 FAIL.

- [ ] **Step 3: 기본 화법 30개를 전면 교정한다**

모든 템플릿을 `확인된 내용 → 고객 가치 → 작은 다음 행동 → 선택지` 구조로 다시 쓴다. 범용 템플릿은 분석 결과를 주장하지 않는다. 청약 직전 문구의 기준 예시는 다음과 같다.

```text
{고객명} 고객님, 오늘 확인한 보험료와 보장 내용을 한 번 더 점검한 뒤 신청 절차를 이어가겠습니다. 지금 진행할지, 조정할 항목부터 함께 볼지 말씀해 주세요.
```

광고문자 템플릿은 실제 설계사 연락처와 사전에 설정한 수신거부 정보가 없으면 공유할 수 없게 표시하고 가짜 번호를 넣지 않는다.

- [ ] **Step 4: view-model과 API RED 테스트를 작성한다**

`talk-template-view-model.test.ts`는 기본·개인·숨김 결합, `내 템플릿으로 저장` payload, 정렬, 고객명 치환 후 원본 미변경을 검증한다.

Run:

```bash
npm run test:run -- lib/talk-template-view-model.test.ts
```

Expected: 모듈이 없어 FAIL.

- [ ] **Step 5: 개인 화법 API와 편집기를 구현한다**

`lib/api.ts`에 `PersonalTalkTemplate`, list/create/update/delete, preference 저장 함수를 추가한다. 편집기는 제목, 분류, 채널, 본문, 변수 삽입, 저장·취소를 제공한다. 개인 템플릿 삭제는 확인 대화상자를 거치고 기본 템플릿은 `내 목록에서 숨기기`와 `기본값으로 되돌리기`를 제공한다.

- [ ] **Step 6: 공유 실패 테스트를 작성한다**

`talk-template-share.test.tsx`에서 다음을 검증한다.

- 공유창에는 항상 `문구 복사`
- `navigator.share`가 있으면 `기기에서 공유`
- `AbortError`는 오류로 표시하지 않음
- 다른 share 오류 후에도 복사 가능
- 복사 성공은 `aria-live`
- Escape와 포커스 복귀

- [ ] **Step 7: 인파 공유창을 구현한다**

카드의 주 버튼은 `공유`다. 버튼은 먼저 인파 modal/bottom sheet를 열고, 그 안에서 복사와 시스템 공유를 선택한다. 복사할 때만 고객명 등이 치환된 최종 문장을 만들며 서버에 저장하지 않는다.

- [ ] **Step 8: Task 5 전체 검증**

Run:

```bash
npm run test:run -- components/__tests__/copy-library.test.tsx \
  lib/talk-template-view-model.test.ts \
  components/__tests__/talk-template-editor.test.tsx \
  components/__tests__/talk-template-share.test.tsx
npm run lint:copy
npm run build
```

Expected: PASS. 360px 모바일에서 bottom sheet, 1440px 데스크톱에서 dialog, 복사와 시스템 공유 지원·미지원 흐름을 확인한다.

---

### Task 6: 무료 1개월 SMS 인증·수혜 원장·SOLAPI 연동

**Files:**
- Modify: `inpa_be/inpa/billing/models.py`
- Modify: `inpa_be/inpa/billing/admin.py`
- Modify: `inpa_be/inpa/billing/coupons.py`
- Modify: `inpa_be/inpa/billing/serializers.py`
- Modify: `inpa_be/inpa/billing/views.py`
- Modify: `inpa_be/inpa/billing/urls.py`
- Create: `inpa_be/inpa/billing/phone_verification.py`
- Create: `inpa_be/inpa/billing/sms.py`
- Create: `inpa_be/inpa/billing/test_phone_verification.py`
- Create: `inpa_be/inpa/billing/migrations/0018_phone_benefit_identity.py`
- Modify: `inpa_be/config/settings/base.py`
- Modify: `inpa_be/.env.example`
- Modify: `render.yaml`

**Interfaces:**
- Consumes: `recurring_trial` 쿠폰 preflight·redeem 흐름.
- Produces: SMS challenge API, 인증 신원, `plus_trial_month` 수혜 원장, 관리자 수동심사 API, SOLAPI provider.

- [ ] **Step 1: 정규화·HMAC·OTP 실패 테스트를 작성한다**

`test_phone_verification.py`에서 다음 literal을 사용한다.

```python
self.assertEqual(normalize_kr_mobile('010-1234-5678'), '01012345678')
self.assertEqual(normalize_kr_mobile('+82 10 1234 5678'), '01012345678')
```

010이 아닌 번호, 길이 오류는 400이다. 같은 번호·같은 HMAC key는 같은 식별값, 다른 key version은 다른 식별값이다. OTP 원문은 challenge DB에 저장되지 않고 5분 후 만료, 5회 실패 후 잠기며 성공한 challenge는 재사용할 수 없어야 한다.

- [ ] **Step 2: RED를 확인한다**

Run:

```bash
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py test \
  inpa.billing.test_phone_verification -v 2
```

Expected: 모듈과 모델이 없어 FAIL.

- [ ] **Step 3: 데이터 모델을 구현한다**

`PhoneVerificationChallenge`:

- UUID PK
- user FK
- `phone_hmac`, `phone_last4`
- `otp_hash`
- `attempt_count`, `max_attempts=5`
- `expires_at`, `verified_at`, `consumed_at`
- `created_at`

`VerifiedPhoneIdentity`:

- user OneToOne
- `phone_hmac`, `key_version`, `phone_last4`
- `provider='solapi_sms'`, `verified_at`, `provider_transaction_ref`

`BenefitGrantLedger`:

- `identity_hmac`, `benefit_code='plus_trial_month'`
- user FK `SET_NULL`
- `granted_at`, `granted_until`
- coupon snapshot JSON
- 유일 `(identity_hmac, benefit_code)`

`ManualBenefitReview`:

- user, identity_hmac, phone_last4, contact_email, reason
- status `pending|approved|rejected|consumed`
- reviewer, decision_reason, decided_at, created_at

challenge에는 전화번호 원문을 저장하지 않는다. verify 요청이 번호를 다시 보내고 서버가 HMAC 일치 여부를 확인한다.

- [ ] **Step 4: SOLAPI 인증·발송 테스트를 작성한다**

외부 HTTP만 mock하고 HMAC header 생성과 요청 body는 실제 함수로 검증한다.

```python
header = build_solapi_auth_header(
    'key', 'secret',
    now=datetime(2026, 7, 28, tzinfo=timezone.utc),
    salt='0123456789abcdef',
)
self.assertEqual(
    header,
    'HMAC-SHA256 apiKey=key, date=2026-07-28T00:00:00Z, '
    'salt=0123456789abcdef, '
    'signature=a7c7ad62e22b00ae8c005b95024e8d9c95768f43c5bfd06de00e3c31c936d638',
)
```

실제 signature literal은 `date+salt`와 secret을 별도 명령으로 한 번 계산해 테스트에 고정한다. 발송은 `POST https://api.solapi.com/messages/v4/send-many/detail`, `messages[0].to/from/text/type='SMS'` 계약을 검증한다. 400·401·403은 재시도하지 않고, timeout·429·5xx는 최대 3회 1s·2s·4s backoff 후 실패한다.

- [ ] **Step 5: SOLAPI provider를 구현한다**

Python 표준 `hmac`, `hashlib`, `secrets`와 기존 HTTP dependency를 사용한다. Authorization은 `HMAC-SHA256`, 매 요청 새로운 16-byte salt, UTC ISO 8601, `signature = HMAC_SHA256(secret, date+salt)`다.

문자:

```text
[인파] 인증번호는 123456입니다. 5분 안에 입력해 주세요.
```

설정값이 없거나 gate가 닫혀 있으면 발송을 시도하지 않고 `503 phone_verification_setup_required`를 반환한다.

- [ ] **Step 6: API와 rate limit 실패 테스트를 작성한다**

API 계약:

- `POST /billing/free-trial/phone/request/ {"phone":"01012345678"}`
- `POST /billing/free-trial/phone/verify/ {"challenge_id":"...","phone":"...","code":"123456"}`
- `POST /billing/free-trial/manual-reviews/ {"contact_email":"...","reason":"..."}`
- 관리자 list/detail decision API

request 응답은 `challenge_id`, `expires_in_seconds=300`, `phone_masked='010-****-5678'`만 포함한다. 같은 사용자·번호·IP의 반복 요청, OTP 오류, 이미 수혜한 번호, 계정 존재 여부가 응답 내용으로 드러나지 않는지 검증한다.

- [ ] **Step 7: 인증 API와 수혜 게이트를 구현한다**

요청 단계에서 원문 번호는 발송 후 버린다. verification 성공 시 `VerifiedPhoneIdentity`를 upsert한다.

발송 제한은 다음 값으로 고정한다.

- 같은 사용자: 10분에 5회, 하루 10회
- 같은 전화번호 HMAC: 10분에 3회
- 같은 IP: 10분에 10회
- 재발송 대기: 60초
- challenge 만료: 300초
- challenge별 확인 실패: 5회

rate-limit 카운터는 DB cache를 사용하고 키에는 원문 전화번호와 IP를 넣지 않고 HMAC만 넣는다.

`recurring_trial` preflight는 gate가 열려 있을 때 다음을 요구한다.

1. 인증 신원 존재
2. 같은 identity+benefit ledger 없음, 또는 이 사용자에게 소비되지 않은 approved manual review 존재

실제 `redeem_held_coupon()` transaction에서 `BenefitGrantLedger`를 생성한다. 중복 유일 제약이면 승인된 review를 잠그고 `consumed`로 바꾼 뒤 예외 지급한다. 쿠폰·구독 지급이 실패하면 ledger와 review 상태도 롤백된다.

- [ ] **Step 8: 관리자 심사와 설정을 구현한다**

관리자는 pending 목록에서 마스킹 번호, 연락 이메일, 사유만 보고 승인·반려 사유를 기록한다. 일반 Django admin에도 read-mostly 모델을 등록한다.

설정:

```python
FREE_TRIAL_PHONE_VERIFICATION_ENABLED = env_bool(
    'FREE_TRIAL_PHONE_VERIFICATION_ENABLED', False)
SOLAPI_API_KEY = os.getenv('SOLAPI_API_KEY', '')
SOLAPI_API_SECRET = os.getenv('SOLAPI_API_SECRET', '')
SOLAPI_SENDER_NUMBER = os.getenv('SOLAPI_SENDER_NUMBER', '')
PHONE_IDENTITY_HMAC_KEY = os.getenv('PHONE_IDENTITY_HMAC_KEY', '')
PHONE_IDENTITY_HMAC_KEY_VERSION = os.getenv(
    'PHONE_IDENTITY_HMAC_KEY_VERSION', 'v1')
```

gate 기본값은 닫힘이다. 운영에서 gate를 열 때 네 비밀값이 모두 없으면 fail-loud한다.

- [ ] **Step 9: Task 6 전체 검증**

Run:

```bash
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py test \
  inpa.billing.test_phone_verification \
  inpa.billing.test_card_registration \
  inpa.billing.tests -v 1
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py check
```

Expected: PASS. PostgreSQL에서 같은 번호로 동시에 두 redeem 요청을 보내도 구독과 ledger가 한 번만 생성된다.

---

### Task 7: 무료혜택 인증·수동심사 화면

**Files:**
- Modify: `inpa_fe/lib/api.ts`
- Modify: `inpa_fe/app/settings/billing/page.tsx`
- Create: `inpa_fe/components/free-trial-phone-verification.tsx`
- Create: `inpa_fe/components/__tests__/free-trial-phone-verification.test.tsx`
- Create: `inpa_fe/app/admin/benefit-reviews/page.tsx`
- Modify: `inpa_fe/lib/adminApi.ts`
- Modify: `inpa_fe/app/admin/layout.tsx`

**Interfaces:**
- Consumes: Task 6의 SMS·수동심사 API와 recurring coupon preflight의 `phone_verification_required`.
- Produces: 쿠폰 시작 전 인증 단계, 중복 번호 수동심사, 관리자 처리 화면.

- [ ] **Step 1: 인증 컴포넌트 실패 테스트를 작성한다**

실제 컴포넌트에서 다음 상태를 검증한다.

- 휴대전화 입력
- 인증번호 발송 후 마스킹 번호·5분 타이머
- 6자리 입력·확인
- 재발송 cooldown
- 잘못된 코드의 남은 시도 안내
- 중복 번호는 `확인 요청하기`
- 이메일·사유 제출 후 접수 완료
- 로딩·재시도·키보드 포커스

- [ ] **Step 2: RED를 확인한다**

Run:

```bash
npm run test:run -- components/__tests__/free-trial-phone-verification.test.tsx
```

Expected: 모듈이 없어 FAIL.

- [ ] **Step 3: API와 인증 UI를 구현한다**

쿠폰 preflight가 `phone_verification_required`를 반환하면 기존 쿠폰 입력값을 유지하고 인증 단계를 연다. 인증 성공 후 같은 preflight를 한 번만 재호출한다. 전화번호는 숫자와 하이픈 입력을 받고 서버 정규화 오류를 그대로 쉬운 문구로 표시한다.

중복 문구:

> 확인이 필요한 번호예요. 이메일과 간단한 사유를 남기면 확인 후 안내해 드릴게요.

계정 존재나 이전 사용자의 이메일은 노출하지 않는다.

- [ ] **Step 4: 관리자 화면을 구현한다**

`/admin/benefit-reviews`는 pending/approved/rejected 필터, 마스킹 번호, 이메일, 사유, 접수일, 결정 사유를 제공한다. 승인·반려는 확인 대화상자와 필수 사유를 사용한다. 원문 번호·인증번호는 표시하지 않는다.

- [ ] **Step 5: Task 7 전체 검증**

Run:

```bash
npm run test:run -- components/__tests__/free-trial-phone-verification.test.tsx
npm run build
```

Expected: PASS. 모바일과 데스크톱에서 쿠폰→SMS→preflight 재개, 중복→심사 접수, 관리자 결정을 확인한다.

---

### Task 8: 녹음 고지 증빙·신규 30일·다운로드 API

**Files:**
- Modify: `inpa_be/inpa/consultations/models.py`
- Modify: `inpa_be/inpa/consultations/serializers.py`
- Modify: `inpa_be/inpa/consultations/views.py`
- Modify: `inpa_be/inpa/consultations/urls.py`
- Modify: `inpa_be/inpa/consultations/storage.py`
- Modify: `inpa_be/inpa/consultations/cleanup.py`
- Modify: `inpa_be/inpa/consultations/tests/test_api.py`
- Modify: `inpa_be/inpa/consultations/tests/test_cleanup.py`
- Modify: `inpa_be/inpa/customers/consent_texts.py`
- Modify: `inpa_be/inpa/customers/tests.py`
- Create: `inpa_be/inpa/consultations/migrations/0007_recording_notice_retention.py`
- Modify: `inpa_be/config/settings/base.py`
- Modify: `inpa_be/.env.example`
- Modify: `render.yaml`

**Interfaces:**
- Consumes: 기존 고객 본인 `consultation_recording`·`consultation_sensitive` 최신 동의와 R2 private storage.
- Produces: notice v2 증빙, 신규 720시간 snapshot, 소유자 전용 attachment URL.

- [ ] **Step 1: 기존 7일·신규 30일 경계 실패 테스트를 작성한다**

테스트는 기존 v1 recording의 `expires_at`을 고정한 뒤 migration/새 정책 호출이 이를 바꾸지 않는지 검증한다. 새 v2 session은 다음을 만족해야 한다.

```python
self.assertEqual(
    recording.expires_at - recording.ready_at,
    timedelta(days=30),
)
self.assertEqual(recording.retention_days_snapshot, 30)
```

notice 없이 session 생성은 400 `recording_notice_required`, 잘못된 notice version은 409 `recording_notice_changed`, 최신 고객 본인 동의가 없으면 기존 412를 유지한다.

- [ ] **Step 2: RED를 확인한다**

Run:

```bash
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py test \
  inpa.consultations.tests.test_api \
  inpa.consultations.tests.test_cleanup -v 2
```

Expected: notice 필드와 30일 snapshot이 없어 FAIL.

- [ ] **Step 3: 동의문과 녹음 snapshot 모델을 버전화한다**

고객 녹음 동의문을 30일 내용으로 새 버전 발행한다. 기존 consent log는 수정하지 않는다.

`ConsultationRecording`에 다음을 추가한다.

```python
notice_version = models.CharField(max_length=40)
notice_attested_at = models.DateTimeField()
notice_text_hash = models.CharField(max_length=64)
retention_days_snapshot = models.PositiveSmallIntegerField(default=7)
retention_policy_version = models.CharField(max_length=40, default='v1-7d')
```

기존 행은 `v1-7d`, 7일로 backfill하고 `expires_at`을 변경하지 않는다. 새 행은 `v2-30d`, 30일이다.

- [ ] **Step 4: 녹음 세션의 고지 증빙을 강제한다**

업로드 세션 body:

```json
{
  "mime_type": "audio/webm",
  "notice_attested": true,
  "notice_version": "consultation-notice-v2-2026-07-28"
}
```

서버는 사용자 입력 문구를 저장하지 않고 서버 SSOT 문구의 SHA-256을 계산한다. `notice_attested is True`와 exact version을 요구하고 서버 현재시각을 저장한다. 고객 본인 최신 동의 검사는 그대로 먼저 수행한다. capability 응답은 `retention_days`, `planner_notice_version`, `planner_notice_text`를 같은 서버 SSOT에서 내려준다.

- [ ] **Step 5: 보존기간 SSOT를 30일로 전환한다**

`CONSULTATION_RETENTION_HOURS` 기본값을 720으로 바꾸고 허용 범위를 1..720으로 제한한다. capability는 설정에서 `retention_days`를 계산한다. R2 metadata와 모든 새 recording snapshot은 같은 값을 사용한다. cleanup은 각 row의 `expires_at`만 신뢰한다.

- [ ] **Step 6: 다운로드 실패 테스트를 작성한다**

다음을 검증한다.

- 소유 설계사 200, URL 만료 300초 이하
- `ResponseContentDisposition`이 `attachment`
- 안전한 파일명과 실제 codec 확장자
- 타인 404
- 일반 관리자도 404
- expired/deleted/consent withdrawn 410
- 응답·로그에 storage key와 서명 URL 전체가 남지 않음

- [ ] **Step 7: 소유자 전용 다운로드 endpoint를 구현한다**

route:

```text
POST /api/v1/customers/<customer_pk>/recordings/<uuid>/download-url/
```

`RecordingDownloadURLView`는 `customer.owner_id == request.user.id`를 직접 요구해 관리자 read bypass를 허용하지 않는다. storage helper는 기존 play URL과 분리하고 다음 disposition을 사용한다.

```python
attachment; filename="consultation-recording-20260728.webm"
```

사용자 응답에는 URL과 `expires_in_seconds=300`만 반환한다. 감사 이벤트에는 user ID, recording UUID, result enum만 기록한다.

- [ ] **Step 8: Task 8 전체 검증**

Run:

```bash
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py test \
  inpa.consultations inpa.customers -v 1
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py check
```

Expected: PASS. migration 전 v1 fixture가 7일, migration 후 새 v2가 30일이다.

---

### Task 9: 설계사용 녹음 고지·다운로드 화면

**Files:**
- Modify: `inpa_fe/lib/api.ts`
- Modify: `inpa_fe/components/consultation-recorder/consultation-recorder.tsx`
- Modify: `inpa_fe/components/consultation-recorder/recording-card.tsx`
- Modify: `inpa_fe/app/admin/consultations/page.tsx`
- Create: `inpa_fe/components/consultation-recorder/recording-notice.tsx`
- Create: `inpa_fe/components/__tests__/recording-notice.test.tsx`
- Modify: existing consultation recorder tests under `inpa_fe/components/__tests__/`

**Interfaces:**
- Consumes: Task 8 capability, upload session notice 계약, download URL.
- Produces: 설계사가 가입 희망자에게 직접 읽는 필수 고지, 세션별 확인, 녹음 다운로드.

- [ ] **Step 1: 고지 화면 실패 테스트를 작성한다**

실제 `RecordingNotice`를 렌더해 다음 문구와 동작을 검증한다.

```text
녹음 전 필수 안내
보험 가입 희망자에게 아래 문구를 직접 읽고 동의를 확인해 주세요.
본 상담은 상담 내용을 정확히 기록하고, 향후 상담 내용과 보험금 청구 관련 안내를 확인하는 참고자료로 활용하기 위해 녹음합니다. 원본은 인파에 30일 동안 보관된 뒤 자동 삭제됩니다. 녹음에 동의하시나요?
```

확인란:

```text
보험 가입 희망자에게 위 내용을 안내했고, 녹음 동의를 확인했습니다.
```

체크 전 시작 disabled, 체크 후 enabled, 세션 취소·완료·고객 변경 후 다시 unchecked를 검증한다. 적색만이 아니라 `role="note"`, 아이콘 accessible name, 제목을 확인한다.

- [ ] **Step 2: FE RED를 확인한다**

Run:

```bash
npm run test:run -- components/__tests__/recording-notice.test.tsx
```

Expected: 모듈이 없어 FAIL.

- [ ] **Step 3: 설계사용 고지와 세션 payload를 구현한다**

고지는 녹음 시작 화면의 설계사 영역에만 렌더한다. 고객 공개 동의 페이지에 같은 블록을 추가하지 않는다. capability의 `planner_notice_text`를 표시하고 체크 후 upload session에 `notice_attested=true`, capability의 `planner_notice_version`을 보낸다. 서버가 409를 반환하면 capability를 새로 받고 체크를 초기화한다.

가입 희망자가 거절하면 `상담 메모로 기록하기`로 고객 기록 탭에 이동한다.

- [ ] **Step 4: 다운로드 실패 테스트를 작성한다**

recording card에서 ready/completed row만 다운로드 버튼이 보이고, 클릭 시 download API를 호출해 브라우저를 attachment URL로 이동시키는지 검증한다. 만료·삭제·410은 버튼을 숨기고 `녹음이 정리되어 상담 메모를 확인할 수 있어요`로 다음 행동을 제공한다.

- [ ] **Step 5: 다운로드와 30일 동적 문구를 구현한다**

`getRecordingDownloadUrl()`을 추가한다. 오디오의 `controlsList="nodownload"`는 제거하되 재생과 다운로드 버튼을 분리한다. 모든 7일 하드코딩은 capability의 `retention_days`를 사용한다. 관리자 화면도 서버 값을 표현한다.

- [ ] **Step 6: Task 9 전체 검증**

Run:

```bash
npm run test:run -- components/__tests__/recording-notice.test.tsx \
  components/__tests__/consultation-recorder.test.tsx
npm run lint:copy
npm run build
```

Expected: PASS. 실제 브라우저에서 설계사 화면의 고지→체크→녹음, 새로고침 후 재확인, 30일 표시, 다운로드를 확인한다.

---

### Task 10: 전체 통합 검증과 운영 준비 문서

**Files:**
- Modify: `.Codex/failures.md` only if the same new failure recurs at least twice
- Modify: `docs/superpowers/specs/2026-07-28-service-quality-expansion-design.md`

**Interfaces:**
- Consumes: Tasks 1-9의 구현과 테스트 결과.
- Produces: 구현 검증 기록과 배포 전 외부 설정 목록. `README.md`와 `AGENTS.md`는 프로젝트 규칙대로 병합·운영 배포가 끝난 뒤 갱신한다.

- [ ] **Step 1: 전체 백엔드 검증**

Run:

```bash
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py check
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py makemigrations --check
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py test inpa
```

Expected: 0 failures. 예상된 4xx 테스트 로그 외 traceback 없음.

- [ ] **Step 2: 전체 프론트엔드 검증**

Run:

```bash
npm run test:run
npm run test:copy-lint
npm run lint:copy
npm run build
```

Expected: 0 failures, copy finding 0, Next build success.

- [ ] **Step 3: 실제 브라우저 happy path**

로컬 BE·FE를 실행하고 다음을 확인한다.

1. 성명 저장 후 게시판 작성자명 반영
2. 본인 글·댓글 삭제, 타인은 신고
3. 전체 담보 기본값과 상세 예외 저장 후 히트맵 판정 반영
4. 기본 화법 공유, 개인 화법 추가·수정·삭제
5. 브라우저 네트워크 격리 환경에서 SMS 인증 성공 응답 후 recurring trial preflight 재개
6. 중복 번호 수동심사 접수·관리자 승인
7. 설계사 고지 확인 없이는 녹음 시작 불가
8. 신규 녹음 30일·소유자 다운로드

- [ ] **Step 4: 보안·개인정보 점검**

Run:

```bash
git diff --check
```

Expected: whitespace 오류 없음. 별도로 변경 파일을 검토해 비밀값·전화번호 원문·인증번호·서명 URL이 로그 문장에 전달되지 않는지 확인한다.

- [ ] **Step 5: 설계서에 구현 검증 상태를 기록한다**

설계서의 상태를 `구현 완료·배포 대기`로 바꾸고 실제 실행한 테스트·브라우저 확인 결과와 남은 외부 설정을 기록한다. `README.md`와 `AGENTS.md`는 아직 수정하지 않는다. 병합·운영 배포가 완료되는 후속 작업에서 두 문서를 함께 갱신한다.

- [ ] **Step 6: 배포 전 외부 입력을 보고한다**

다음은 코드 완성과 별개인 운영 입력으로 분리한다.

- SOLAPI 계정과 사전 등록 발신번호
- `SOLAPI_API_KEY`
- `SOLAPI_API_SECRET`
- `SOLAPI_SENDER_NUMBER`
- 무작위 32-byte 이상 `PHONE_IDENTITY_HMAC_KEY`
- 개인정보 처리방침의 무료 프로그램 운영 종료 후 원장 보유기간 문구
- R2 lifecycle가 7일로 고정되어 있지 않다는 확인

사용자의 별도 요청 전에는 커밋·푸시·PR·운영 배포를 하지 않는다.
