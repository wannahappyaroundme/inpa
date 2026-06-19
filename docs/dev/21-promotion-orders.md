# 인파(Inpa) — 판촉물 주문제작 시스템

> **문서 ID**: `dev/21-promotion-orders.md` · 2026-06-19 · 정본
> **교차 정본**: `dev/02`(데이터모델·API) · `dev/01`(아키텍처·스택) · `dev/11`(인증·멀티테넌시)
> **범위**: 설계사가 판촉물 샘플을 보고 내용을 입력하여 주문을 넣으면, 관리자가 직접 제작·발송하는 수동 주문제작 플로우 전체.

---

## 0. 이 문서가 푸는 문제

보험설계사는 영업 현장에서 달력·다이어리·볼펜 등 판촉물을 고객에게 나눠준다. 지금은 설계사가 직접 인쇄소를 찾거나, GA 본사에 별도 연락해야 한다. 인파는 이 과정을 앱 안에서 끝낸다.

**핵심 흐름 두 단계:**
1. **설계사**: 샘플 고르기 → 폼 작성 → 주문 제출 (앱 안에서 끝)
2. **관리자**: 주문 목록 확인 → 외부 인쇄소에 직접 발주 → 상태 업데이트 → 완료

자동 발주·자동 발송은 없다. 관리자가 주문을 보고 수동으로 진행한다. 이 방식이 초기 운영비를 낮추고, 제작 품질을 관리자가 직접 통제할 수 있게 한다.

**가시성 원칙** (`dev/11` 멀티테넌시 매트릭스):
- `PromotionSample`(샘플 카탈로그) = **공유** — 모든 설계사가 볼 수 있음. `owner` FK 없음.
- `PromotionOrder`(주문) = **소유자 + 관리자** — 설계사는 본인 주문만, 관리자는 전체 주문 처리.

---

## 1. 화면 구성 (IA)

```
[설계사 앱]  하단탭  [홈] [고객] [+증권] [캘린더] [내정보]
                                                       │
                                              /my → 판촉물 탭 (혹은 별도 진입)
                                                       │
                    ┌──────────────────────────────────┘
                    ▼
            /promotion                      ← 샘플 목록 (공유, 모든 설계사 열람)
                 │
                 ├── 샘플 카드 클릭
                 │
                 ▼
            /promotion/:sampleId            ← 샘플 상세 + 주문 폼
            ┌─────────────────────────────────────┐
            │  [왼쪽] 샘플 이미지 갤러리               │
            │  [오른쪽] 구글폼식 동적 입력 폼           │
            │           → 수량·문구·색상 등 항목        │
            │           → [예약(주문) 제출] 버튼        │
            └─────────────────────────────────────┘
                 │
                 ▼
            /promotion/orders               ← 내 주문 목록 (본인 주문만)
                 │
                 └── /promotion/orders/:orderId  ← 주문 상세 + 상태 타임라인

[관리자 어드민]
            /admin/promotion/orders         ← 전체 주문 목록 + 상태 변경
            /admin/promotion/samples        ← 샘플 등록·수정·삭제 + 폼 필드 관리
```

---

## 2. 화면 상세 스펙

### 2.1 샘플 목록 `/promotion`

| 요소 | 설명 |
|---|---|
| 레이아웃 | 카드 그리드 (모바일 2열, 데스크톱 3~4열) |
| 카드 내용 | 대표 이미지 · 샘플명 · 카테고리 칩 · 주문 가능 여부 배지 |
| 필터 | 카테고리 칩 탭 (전체 / 달력 / 다이어리 / 생활용품 / 기타) |
| 빈 상태 | "등록된 판촉물 샘플이 없습니다" + 관리자 문의 안내 |

### 2.2 샘플 상세 + 주문 폼 `/promotion/:sampleId`

**레이아웃: 2열 분할 (좌우 나란히)**

```
┌──────────────────────┬──────────────────────────────────┐
│  [왼쪽] 이미지 갤러리   │  [오른쪽] 주문 폼                  │
│                      │                                  │
│  ● 대표 이미지         │  샘플명: OO 달력 2026              │
│  ○ 썸네일 1           │  카테고리: 달력                    │
│  ○ 썸네일 2           │                                  │
│  ○ 썸네일 3           │  ─ 동적 폼 필드 (관리자 정의) ─     │
│                      │                                  │
│  [샘플 설명 텍스트]    │  수량: [  100  ]                  │
│                      │  문구 (이름·연락처): [__________]  │
│                      │  로고 파일 첨부: [파일 선택]         │
│                      │  색상: ○빨강 ○파랑 ○검정           │
│                      │  요청사항: [___________________]  │
│                      │                                  │
│                      │  [예약(주문) 제출]                 │
└──────────────────────┴──────────────────────────────────┘
```

**모바일**: 이미지 상단, 폼 하단으로 세로 배치.

**폼 필드 동작 규칙:**
- 필드 목록은 `PromotionSample.form_fields` JSON에서 동적으로 렌더링. (관리자가 샘플별로 다른 필드를 구성)
- 필드 타입: `text` / `number` / `select` / `radio` / `checkbox` / `textarea` / `file`
- `required: true` 필드 미입력 시 [제출] 버튼 비활성.
- 파일 첨부는 S3 presigned URL 방식 (추정 — 스토리지 정책 확정 전).

**제출 후 동작:**
- 성공(201) → 토스트 "주문이 접수되었습니다" + `/promotion/orders`로 이동.
- 실패(402 크레딧 부족) → "이번 달 주문 한도를 초과했습니다" 인라인 에러.

### 2.3 내 주문 목록 `/promotion/orders`

| 요소 | 설명 |
|---|---|
| 목록 항목 | 샘플명 · 주문일 · 수량 · 현재 상태 배지 · 상세보기 링크 |
| 상태 배지 색 | 예약접수=회색 · 검토중=파랑 · 제작중=노랑 · 발송=주황 · 완료=초록 · 취소=빨강 |
| 빈 상태 | "아직 주문한 판촉물이 없습니다" + [샘플 보러 가기] 버튼 |

### 2.4 주문 상세 `/promotion/orders/:orderId`

```
주문 #20260619-0042   [예약접수]

샘플: OO 달력 2026
수량: 100개
제출 내용:
  - 문구: 홍길동 보험설계사 010-1234-5678
  - 색상: 파랑
  - 요청사항: "로고 좌측 하단 배치 부탁드립니다"

─ 진행 상태 타임라인 ─────────────────────
  ● 2026-06-19 14:32  예약 접수
  ○ 검토중
  ○ 제작중
  ○ 발송
  ○ 완료

[관리자 메모 (설계사에게 보임)]
  현재 메모 없음
```

---

## 3. 데이터 모델

### 3.1 `PromotionSample` (샘플 카탈로그 — 공유, `owner` FK 없음)

관리자만 등록·수정·삭제한다. 모든 설계사가 읽기만 한다.

```python
class PromotionSample(models.Model):
    # 기본 정보
    name          = models.CharField(max_length=100)         # 샘플명 (예: "OO 달력 2026")
    category      = models.CharField(max_length=30)          # 카테고리 (달력/다이어리/생활용품/기타)
    description   = models.TextField(blank=True)             # 설명 (재질·사이즈·납기 등)
    is_available  = models.BooleanField(default=True)        # 주문 가능 여부 (품절·단종 시 False)

    # 이미지 (복수)
    # PromotionSampleImage(OneToMany)로 분리 → § 3.3 참조

    # 동적 폼 필드 정의 (JSON)
    # 관리자가 샘플별로 수집할 항목을 자유롭게 정의한다.
    # 예: [{"key":"quantity","label":"수량","type":"number","required":true,"min":10},
    #      {"key":"text","label":"문구","type":"text","required":true,"maxLength":40},
    #      {"key":"color","label":"색상","type":"radio","options":["빨강","파랑","검정"],"required":true}]
    form_fields   = models.JSONField(default=list)

    # 메타
    sort_order    = models.IntegerField(default=0)           # 목록 노출 순서
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', '-created_at']

    # 소유자 FK 없음 — 공유 데이터. OwnedQuerySetMixin 미적용.
    # 읽기: AllowAny(설계사 인증 후) / 쓰기: IsAdmin only
```

### 3.2 `PromotionSampleImage` (샘플 이미지 — 공유, `PromotionSample` 종속)

```python
class PromotionSampleImage(models.Model):
    sample     = models.ForeignKey(PromotionSample, on_delete=models.CASCADE,
                                   related_name='images')
    image_url  = models.URLField()                           # S3 URL
    is_primary = models.BooleanField(default=False)          # 대표 이미지 여부
    sort_order = models.IntegerField(default=0)
```

### 3.3 `PromotionOrder` (주문 — 소유자 + 관리자)

설계사가 제출하는 주문. `owner`(설계사)와 관리자만 볼 수 있다.

```python
class PromotionOrder(models.Model):

    # ── 상태 머신 ─────────────────────────────────────────────────────
    STATUS_PENDING   = 'pending'    # 예약 접수 — 설계사가 폼 제출 직후
    STATUS_REVIEWING = 'reviewing'  # 검토 중   — 관리자가 주문 확인
    STATUS_PRODUCING = 'producing'  # 제작 중   — 외부 인쇄소 발주 완료
    STATUS_SHIPPED   = 'shipped'    # 발송      — 운송장 생성
    STATUS_DONE      = 'done'       # 완료      — 수령 확인
    STATUS_CANCELLED = 'cancelled'  # 취소      — 설계사 요청 또는 관리자 처리불가

    STATUS_CHOICES = [
        (STATUS_PENDING,   '예약 접수'),
        (STATUS_REVIEWING, '검토 중'),
        (STATUS_PRODUCING, '제작 중'),
        (STATUS_SHIPPED,   '발송'),
        (STATUS_DONE,      '완료'),
        (STATUS_CANCELLED, '취소'),
    ]

    VALID_TRANSITIONS = {
        STATUS_PENDING:   [STATUS_REVIEWING, STATUS_CANCELLED],
        STATUS_REVIEWING: [STATUS_PRODUCING, STATUS_CANCELLED],
        STATUS_PRODUCING: [STATUS_SHIPPED,   STATUS_CANCELLED],
        STATUS_SHIPPED:   [STATUS_DONE,      STATUS_CANCELLED],
        STATUS_DONE:      [],   # 종결 상태
        STATUS_CANCELLED: [],   # 종결 상태
    }

    # ── 연결 ──────────────────────────────────────────────────────────
    owner     = models.ForeignKey(settings.AUTH_USER_MODEL,
                                  on_delete=models.SET_NULL, null=True,
                                  related_name='promotion_orders')  # 소유자(설계사)
    sample    = models.ForeignKey(PromotionSample,
                                  on_delete=models.SET_NULL, null=True)  # 선택한 샘플

    # ── 폼 응답 ───────────────────────────────────────────────────────
    # 설계사가 입력한 폼 필드 응답 전체를 저장.
    # 키는 PromotionSample.form_fields[].key와 일치.
    # 예: {"quantity": 100, "text": "홍길동 010-1234-5678", "color": "파랑"}
    form_response = models.JSONField(default=dict)

    # ── 상태 ──────────────────────────────────────────────────────────
    status        = models.CharField(max_length=20, choices=STATUS_CHOICES,
                                     default=STATUS_PENDING, db_index=True)

    # ── 관리자 메모 (설계사에게도 보임) ──────────────────────────────────
    admin_note    = models.TextField(blank=True)

    # ── 발송 정보 (STATUS_SHIPPED 이후) ──────────────────────────────────
    tracking_number = models.CharField(max_length=100, blank=True)  # 운송장 번호 (선택)
    carrier         = models.CharField(max_length=50, blank=True)   # 택배사명 (선택)

    # ── 메타 ──────────────────────────────────────────────────────────
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def transition_to(self, new_status, admin_user):
        """상태 전이 유효성 검사 후 저장. 잘못된 전이 시 ValueError."""
        allowed = self.VALID_TRANSITIONS.get(self.status, [])
        if new_status not in allowed:
            raise ValueError(
                f"'{self.status}' → '{new_status}' 전이는 허용되지 않습니다."
            )
        self.status = new_status
        self.save(update_fields=['status', 'updated_at'])
        PromotionOrderStatusLog.objects.create(
            order=self, to_status=new_status, changed_by=admin_user
        )
```

### 3.4 `PromotionOrderStatusLog` (상태 변경 이력)

설계사 상세 화면의 타임라인 및 관리자 감사추적에 사용한다.

```python
class PromotionOrderStatusLog(models.Model):
    order      = models.ForeignKey(PromotionOrder, on_delete=models.CASCADE,
                                   related_name='status_logs')
    to_status  = models.CharField(max_length=20)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL,
                                   on_delete=models.SET_NULL, null=True)  # 관리자
    changed_at = models.DateTimeField(auto_now_add=True)
    note       = models.TextField(blank=True)   # 이 전이에 딸린 메모 (옵션)
```

---

## 4. API 계약

### 4.1 샘플 카탈로그 (공유, 읽기 전용 — 설계사)

| 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|
| `GET` | `/api/v1/promotion/samples/` | Token | 샘플 목록 (카테고리 필터 지원) |
| `GET` | `/api/v1/promotion/samples/:id/` | Token | 샘플 상세 (form_fields 포함) |

**`GET /promotion/samples/` 응답 예시:**
```json
{
  "count": 12,
  "results": [
    {
      "id": 3,
      "name": "OO 달력 2026",
      "category": "달력",
      "description": "A4 벽걸이 달력. 12장 인쇄. 납기 10~14 영업일.",
      "is_available": true,
      "primary_image": "https://cdn.inpa.kr/samples/3/main.jpg",
      "sort_order": 1
    }
  ]
}
```

**쿼리 파라미터:**
- `?category=달력` — 카테고리 필터
- `?available=true` — 주문 가능 항목만

**`GET /promotion/samples/:id/` 응답 예시 (폼 필드 포함):**
```json
{
  "id": 3,
  "name": "OO 달력 2026",
  "category": "달력",
  "description": "A4 벽걸이 달력...",
  "is_available": true,
  "images": [
    {"url": "https://cdn.inpa.kr/samples/3/main.jpg", "is_primary": true},
    {"url": "https://cdn.inpa.kr/samples/3/detail1.jpg", "is_primary": false}
  ],
  "form_fields": [
    {"key": "quantity", "label": "수량", "type": "number", "required": true, "min": 50, "step": 50},
    {"key": "name_text", "label": "인쇄 문구 (이름·연락처)", "type": "text", "required": true, "maxLength": 40},
    {"key": "color", "label": "색상", "type": "radio",
     "options": ["빨강", "파랑", "검정"], "required": true},
    {"key": "logo_file", "label": "로고 파일 (PNG/AI)", "type": "file", "required": false,
     "accept": [".png", ".ai", ".pdf"]},
    {"key": "note", "label": "추가 요청사항", "type": "textarea", "required": false, "maxLength": 200}
  ]
}
```

### 4.2 주문 (소유자 — 설계사)

| 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|
| `POST` | `/api/v1/promotion/orders/` | Token | 주문 제출 |
| `GET` | `/api/v1/promotion/orders/` | Token | 내 주문 목록 (본인 소유만) |
| `GET` | `/api/v1/promotion/orders/:id/` | Token (IsOwner) | 내 주문 상세 + 상태 타임라인 |
| `DELETE` | `/api/v1/promotion/orders/:id/` | Token (IsOwner) | 주문 취소 (pending 상태만) |

**`POST /promotion/orders/` 요청 예시:**
```json
{
  "sample": 3,
  "form_response": {
    "quantity": 100,
    "name_text": "홍길동 보험설계사 010-1234-5678",
    "color": "파랑",
    "note": "로고 좌측 하단 배치 부탁드립니다"
  }
}
```

**`POST` 응답 201:**
```json
{
  "id": 42,
  "status": "pending",
  "status_display": "예약 접수",
  "sample": {"id": 3, "name": "OO 달력 2026"},
  "form_response": { "quantity": 100, "name_text": "홍길동 ...", "color": "파랑" },
  "admin_note": "",
  "tracking_number": "",
  "created_at": "2026-06-19T14:32:00+09:00"
}
```

**`GET /promotion/orders/:id/` 응답 (상태 타임라인 포함):**
```json
{
  "id": 42,
  "status": "reviewing",
  "status_display": "검토 중",
  "sample": {"id": 3, "name": "OO 달력 2026"},
  "form_response": { "quantity": 100, "name_text": "홍길동 ...", "color": "파랑" },
  "admin_note": "로고 파일을 별도로 이메일로 보내주세요.",
  "tracking_number": "",
  "status_logs": [
    {"to_status": "pending",   "status_display": "예약 접수", "changed_at": "2026-06-19T14:32:00+09:00"},
    {"to_status": "reviewing", "status_display": "검토 중",   "changed_at": "2026-06-19T17:00:00+09:00"}
  ],
  "created_at": "2026-06-19T14:32:00+09:00"
}
```

**취소 `DELETE /promotion/orders/:id/`:**
- `pending` 상태일 때만 허용. 다른 상태면 `400 {"detail": "이미 처리 중인 주문은 취소할 수 없습니다."}`.
- 내부적으로 `transition_to(STATUS_CANCELLED, ...)` 호출 (실제 DELETE가 아닌 상태 전이).

### 4.3 관리자 전용 API

| 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|
| `GET` | `/api/v1/admin/promotion/orders/` | Token (IsAdmin) | 전체 주문 목록 + 상태·날짜 필터 |
| `PATCH` | `/api/v1/admin/promotion/orders/:id/status/` | Token (IsAdmin) | 상태 변경 + 관리자 메모 |
| `GET/POST/PATCH/DELETE` | `/api/v1/admin/promotion/samples/` | Token (IsAdmin) | 샘플 CRUD |
| `POST` | `/api/v1/admin/promotion/samples/:id/images/` | Token (IsAdmin) | 샘플 이미지 추가 |
| `DELETE` | `/api/v1/admin/promotion/samples/:id/images/:imgId/` | Token (IsAdmin) | 샘플 이미지 삭제 |

**관리자 주문 목록 `GET /admin/promotion/orders/`:**

쿼리 파라미터:
- `?status=pending` — 상태 필터 (복수 가능: `?status=pending&status=reviewing`)
- `?date_from=2026-06-01&date_to=2026-06-30` — 날짜 범위
- `?search=홍길동` — 설계사명 검색 (추정)

**관리자 상태 변경 `PATCH /admin/promotion/orders/:id/status/`:**
```json
// 요청
{
  "status": "producing",
  "admin_note": "6월 30일 발송 예정입니다."
}

// 응답 200
{
  "id": 42,
  "status": "producing",
  "admin_note": "6월 30일 발송 예정입니다.",
  "updated_at": "2026-06-20T09:00:00+09:00"
}
```

잘못된 상태 전이 시 `400 {"detail": "'pending' → 'done' 전이는 허용되지 않습니다."}`.

---

## 5. 권한 · 가시성

| 데이터 | 설계사(본인) | 설계사(타인) | 관리자 |
|---|---|---|---|
| `PromotionSample` 목록·상세 | 읽기 O | 읽기 O (공유) | 읽기/쓰기/삭제 |
| `PromotionOrder` 목록·상세 | 본인 것만 O | X (404) | 전체 O + 상태 변경 |
| `PromotionOrderStatusLog` | 본인 주문의 로그만 | X | 전체 |

**권한 구현 원칙** (`dev/11` 멀티테넌시 규칙):
- `PromotionSample` ViewSet: `OwnedQuerySetMixin` **미적용** (공유 데이터). 읽기=인증된 설계사 전원, 쓰기=`IsAdmin`.
- `PromotionOrder` ViewSet: `OwnedQuerySetMixin` **적용** (소유자 전용). `get_queryset()`은 `filter(owner=request.user)` 강제. `IsOwner` permission으로 상세·삭제 보호.
- 관리자 뷰셋(`/admin/promotion/...`): `IsAdmin` permission, `OwnedQuerySetMixin` bypass.

---

## 6. 크레딧·한도 (추정)

판촉물 주문은 **`promotion_credit`** 종류로 월 한도를 제한한다. foliio `_check_and_consume(user, kind='promotion')` ♻ 재사용.

| 멤버십 | 월 판촉물 주문 한도 | 비고 |
|---|---|---|
| 무료(Free) | 1건 | (추정 — 베타 실측 전 가설) |
| 플러스(Plus) | 5건 | (추정) |
| 프리미엄(Premium) | 무제한 | (추정) |

- 베타 기간 중 `FREE_TIER_UNLIMITED=True` 설정 시 전 멤버십 무제한.
- 한도 초과 시 `POST /promotion/orders/` → `402 {"reason": "CREDIT_EXHAUSTED", "kind": "promotion", "remaining": 0}`.

> **(추정)** 한도 수치는 베타 90일 실측 후 조정. `dev/02` `Membership` 모델의 `promotion_credit` 필드 추가 확정 필요.

---

## 7. 컴플라이언스 · 면책

### 7.1 판촉물 광고심의

보험 관련 내용이 판촉물에 인쇄되는 경우 광고심의 대상이 될 수 있다. **인파는 판촉물 인쇄 내용의 적법성을 보증하지 않는다.**

- 설계사가 입력하는 `name_text`(인쇄 문구)에 보험 상품명·수익 보장 표현·단정적 권유 문구가 포함될 경우 `ai_guardrail` 플래그를 고려한다 (추정 — 1차 MVP에는 과감한 필터링보다 고지로 대응).
- 판촉물 폼 하단 고정 문구: **"입력한 내용의 광고심의 적합성은 설계사 본인이 확인해야 합니다. 인파는 인쇄 내용의 법적 적합성을 보증하지 않습니다."**

### 7.2 자동 발송 없음

- 주문 제출 = **예약 접수**. 실제 제작·발송은 관리자 수동 진행.
- 설계사에게 "제작 완료", "발송 완료" 알림은 인앱 Notification(`dev/02` Notification 모델 재사용)으로만. 카카오 알림톡·SMS 자동발송 없음 (광고심의·원탭 자동발송 정책).

### 7.3 PII 처리

- `form_response` JSON에 설계사 연락처·주소 등이 포함될 수 있다. 단, 이는 설계사 본인 정보이며 인쇄 문구로 사용한다 — 민감정보(병력) 국외이전 동의 대상이 아니다.
- `form_response`는 소유자(`owner`) + 관리자만 접근 가능. API 응답에서 타 설계사에게 절대 노출 금지.

---

## 8. 관리자 어드민 화면 스펙

### 8.1 샘플 관리 `/admin/promotion/samples`

| 기능 | 설명 |
|---|---|
| 샘플 목록 | 이름·카테고리·주문 가능 여부·주문 건수 표시 |
| 샘플 등록 | 이름·카테고리·설명 입력 + 이미지 업로드(복수) + 폼 필드 빌더 |
| 폼 필드 빌더 | 필드 추가(타입 선택) → 드래그 순서 변경 → 미리보기 |
| 샘플 비활성 | `is_available=False` 토글 → 설계사 목록에서 "주문 불가" 배지 |

**폼 필드 빌더 UI (관리자):**
```
[필드 추가 +]
─────────────────────────────────────────
● 수량       타입: 숫자  필수: ✓   [↑][↓][삭제]
  최솟값: 50 / 단위: 50
─────────────────────────────────────────
● 인쇄 문구   타입: 텍스트 필수: ✓  [↑][↓][삭제]
  최대 글자수: 40
─────────────────────────────────────────
[미리보기]
```

### 8.2 주문 처리 `/admin/promotion/orders`

| 기능 | 설명 |
|---|---|
| 주문 목록 | 접수일·설계사명·샘플명·수량·현재 상태·최종 업데이트 |
| 상태 필터 | 상태별 탭 (예약접수 N건 / 검토중 / 제작중 / 발송 / 완료 / 취소) |
| 상태 변경 | 주문 클릭 → 상세 → [다음 단계로] 버튼 + 메모 입력 후 저장 |
| 메모 | `admin_note` 편집 → 설계사 상세 화면에도 노출 |
| 운송장 | `STATUS_SHIPPED` 시 택배사·운송장 번호 입력 필드 노출 |
| 일괄 처리 | (추정) 같은 샘플 여러 건 선택 → 상태 일괄 변경 (MVP 이후) |

---

## 9. 수용 기준 (Definition of Done)

**샘플 카탈로그**
- [ ] AC-P1 `GET /promotion/samples/` 응답에 `form_fields` 배열이 포함되고, FE가 이를 동적 렌더링한다.
- [ ] AC-P2 `is_available=False` 샘플은 목록에 "주문 불가" 배지로 표시되고, 폼 제출 버튼이 비활성이다.
- [ ] AC-P3 카테고리 필터 칩이 동작한다 (BE `?category=` 쿼리 처리).

**주문 제출·목록**
- [ ] AC-O1 `POST /promotion/orders/` 성공 시 상태 `pending`, `status_logs` 1건 생성.
- [ ] AC-O2 `GET /promotion/orders/` 응답에 본인 주문만 포함 (타 설계사 주문 0건 — 멀티테넌시 격리).
- [ ] AC-O3 `pending` 상태 주문만 설계사가 취소(`DELETE`) 가능. `reviewing` 이후 취소 시도 시 `400`.
- [ ] AC-O4 한도 초과 시 `402 CREDIT_EXHAUSTED` 반환.

**상태 머신**
- [ ] AC-S1 허용된 전이만 성공(`200`), 비허용 전이 시 `400`.
- [ ] AC-S2 상태 변경마다 `PromotionOrderStatusLog` 1건 생성.
- [ ] AC-S3 `status_logs` 는 설계사 주문 상세 응답에 포함되어 타임라인 렌더링 가능.

**관리자**
- [ ] AC-A1 관리자가 샘플을 등록·수정·삭제할 수 있다 (설계사는 쓰기 불가 → `403`).
- [ ] AC-A2 `PATCH /admin/promotion/orders/:id/status/`가 상태 전이 유효성을 검증한다.
- [ ] AC-A3 `admin_note` 업데이트가 설계사 주문 상세 응답에 즉시 반영된다.

**컴플라이언스**
- [ ] AC-C1 주문 폼 하단 면책 문구가 고정 렌더링된다 (CSS hidden 불가, 항상 노출).
- [ ] AC-C2 `form_response` 가 타 설계사 API 응답에 절대 포함되지 않는다 (`grep` 회귀).
- [ ] AC-C3 관리자 상태 변경 알림이 인앱 Notification으로만 전송됨 (카카오/SMS 0건).

---

## 10. 기획 갭 (openGaps)

| # | 갭 | 영향 | 상태 |
|---|---|---|---|
| G-1 | **파일 첨부 스토리지 정책 미확정** (S3 버킷·presigned URL 만료 시간·파일 크기 제한) | 로고 파일 업로드 필드 구현 불가 | 스토리지 정책 확정 선결 |
| G-2 | **`promotion_credit` 한도 수치 미확정** (Free 1건 / Plus 5건 / Premium 무제한 모두 추정) | 크레딧 차감 로직 숫자 고정 불가 | 베타 실측 전 임시값 사용 |
| G-3 | **운송장 자동 연동 (택배사 API)** 미범위 | 설계사가 배송 추적을 인파 밖에서 해야 함 | MVP 이후(수동 입력으로 우회) |
| G-4 | **광고심의 대상 여부** — 이름·연락처만 인쇄하는 경우 vs 보험 상품명 포함 시 기준 | 폼 가드레일 강도 결정 불가 | 법무 보수적 기본값(면책 고지)으로 우회 |
| G-5 | **알림 트리거 타이밍** — 관리자가 상태를 바꿀 때 즉시 Notification 발송인지, 배치 발송인지 미확정 | Notification 구현 방식 | 즉시 발송 기본값(추정)으로 시작 |
| G-6 | **일괄 상태 변경** — 관리자가 여러 주문을 선택해 상태를 한꺼번에 바꾸는 기능 범위 미확정 | 관리자 운영 효율 | MVP 이후로 제외, openGaps 기록 |
| G-7 | **샘플 폼 필드 타입 확장** — `date`, `address`, `phone` 등 추가 필요 여부 미확정 | 특수 판촉물(예: 웨딩 선물) 지원 | 운영 중 수요 확인 후 추가 |
