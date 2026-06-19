# 인파(Inpa) — 관리자 콘솔 (Admin Console)

> dev/19 — 관리자 전용 백오피스. 설계사(유저) 관리·통계 대시보드·게시판/공지/FAQ 작성·1:1 문의 응대·동의 로그 열람·신고 모더레이션·요금제/사용량 관리·★판촉물 주문 처리. 본 문서는 정본 dev/02(데이터 모델·API)·dev/11(인증)·dev/06(MVP 슬라이스) 위에 관리자 레이어를 얹는다.

---

## 0. 이 문서가 잠그는 것

| # | 영역 | 핵심 결정 |
|---|---|---|
| 1 | Admin 로그인 | **이메일/비밀번호 전용** — 설계사 카카오 OAuth와 완전 분리. 별도 `/admin-login` 라우트 |
| 2 | Admin 권한 | `Profile.is_admin = True` 1필드. `OwnedQuerySetMixin` 화이트리스트 ①(데이터 bypass). 일반 설계사에 절대 부여 금지 |
| 3 | 멀티테넌시 | Admin은 전체 설계사 데이터 조회 가능. 단 **소유자 전용 데이터(고객·보험·분석)는 열람 가능이나 수정 금지** — 법무 원칙(설계사 소유권 침해 방지) |
| 4 | 판촉물 주문 처리 | 설계사가 주문 → admin이 접수·상태 변경·직접 제작 흐름. **온/오프라인 혼합 워크플로** |
| 5 | 동의 로그 | `ConsentLog` 열람 전용(READ-ONLY). 수정 불가(감사 무결성) |
| 6 | 정규화 사전 매핑 | `UnmatchedLog` admin 1탭 검수 → `NormalizationDict` 영구 추가 (데이터 복리 루프) |

**admin 콘솔 = 개발자 없이 운영이 돌아가게 하는 최소 백오피스.** PM(비개발자)이 브라우저에서 직접 처리할 수 있어야 한다.

---

## 1. 범위 (In / Out)

| 구분 | 포함 | 비고 |
|---|---|---|
| **In** | admin 이메일 로그인, 설계사 목록·상세, 통계 대시보드, 게시판(SNS피드) 글 삭제·신고 모더레이션, 공지사항 작성, FAQ 작성, 1:1 문의 응대, ConsentLog 열람, 판촉물 주문 처리, 정규화 사전 매핑, 요금제/사용량 한도 관리 | net-new BE + FE |
| **In(연계)** | `UnmatchedLog` 매핑 → `NormalizationDict` 추가 루프 | dev/02 §5 학습루프의 운영면 |
| **Out** | 설계사 고객 데이터 수정(고객·보험·분석·비교·캘린더) | 설계사 소유권 원칙 |
| **Out** | Django admin(`/django-admin/`) — 개발자 전용, 운영용 아님 | 별도 유지 |
| **Out(추정)** | 멀티 admin 권한 분리(슈퍼/서브) | MVP=단일 admin role. P2 이후 필요 시 추가 |

---

## 2. 데이터 모델

### 2.1 기존 모델 활용 (변경 없음)

admin 콘솔은 **신규 모델을 최소화**한다. 기존 모델을 읽고 상태 필드만 추가한다.

| 모델 | 재활용 방식 | admin 용도 |
|---|---|---|
| `User` + `Profile` | ♻ + `is_admin` 플래그 | 설계사 목록·상세·멤버십 관리 |
| `UserMembership` | ♻ | 요금제 확인·변경 |
| `ConsentLog` | ♻ READ-ONLY | 동의 감사 로그 열람 |
| `NormalizationDict` | ♻ + admin 매핑 | 정규화 사전 1탭 추가 |
| `UnmatchedLog` | ♻ + resolved 플래그 | 미매칭 검수 큐 |
| `Notification` | ♻ | 알림 발송 이력 확인 |

### 2.2 신규 모델 (admin 전용)

#### 2.2.1 `Announcement` — 공지사항

```python
class Announcement(models.Model):
    title       = models.CharField(max_length=200)
    body        = models.TextField()
    is_pinned   = models.BooleanField(default=False)  # 상단 고정
    published_at = models.DateTimeField(null=True, blank=True)  # null=임시저장
    author      = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True, related_name='announcements')  # admin 작성자
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)
```

- **가시성**: 모든 설계사 읽기 전용. admin만 작성·수정·삭제.
- `published_at is None` → 임시저장(설계사에게 안 보임).
- `is_pinned=True` → 공지 목록 최상단 고정.

#### 2.2.2 `FAQ` — 자주 묻는 질문

```python
class FAQ(models.Model):
    question    = models.CharField(max_length=300)
    answer      = models.TextField()
    category    = models.CharField(max_length=50, default='general')  # general/billing/feature
    order       = models.SmallIntegerField(default=0)  # 노출 순서 (낮을수록 상위)
    is_published = models.BooleanField(default=False)
    author      = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True, related_name='faqs')
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)
```

- **가시성**: 모든 설계사 읽기 전용. admin만 작성·수정·삭제.
- `is_published=False` → 초안, 설계사에게 안 보임.
- `category`로 탭 분류(과금/기능/컴플라이언스 등).

#### 2.2.3 `Inquiry` — 1:1 문의

```python
class Inquiry(models.Model):
    STATUS = ((1, 'pending'), (2, 'in_progress'), (3, 'resolved'), (4, 'closed'))

    author      = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True, related_name='inquiries')  # 설계사
    title       = models.CharField(max_length=200)
    body        = models.TextField()
    status      = models.SmallIntegerField(choices=STATUS, default=1)
    admin_reply = models.TextField(null=True, blank=True)  # admin 응답
    replied_at  = models.DateTimeField(null=True, blank=True)
    replied_by  = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True, related_name='inquiry_replies')  # admin
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)
```

- **가시성**: 작성 설계사 + admin만. 다른 설계사는 열람 불가.
- `admin_reply` 입력 → `replied_at` 자동 기록 → 설계사에게 인앱 알림(`Notification`).
- status: `pending`(접수) → `in_progress`(처리 중) → `resolved`(답변 완료) → `closed`.

#### 2.2.4 `BoardReport` — 게시판 신고

```python
class BoardReport(models.Model):
    REASON = ((1, 'spam'), (2, 'inappropriate'), (3, 'misinformation'), (4, 'other'))
    STATUS = ((1, 'pending'), (2, 'reviewed'), (3, 'actioned'), (4, 'dismissed'))

    reporter    = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True, related_name='reports_filed')
    post_id     = models.IntegerField()       # 신고 대상 게시물 ID (FeedPost 또는 댓글)
    post_type   = models.CharField(max_length=20)  # 'post' | 'comment'
    reason      = models.SmallIntegerField(choices=REASON)
    detail      = models.TextField(null=True, blank=True)  # 신고 사유 부연
    status      = models.SmallIntegerField(choices=STATUS, default=1)
    action_note = models.TextField(null=True, blank=True)  # admin 처리 메모
    actioned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True, related_name='reports_actioned')
    actioned_at = models.DateTimeField(null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
```

- **가시성**: admin만. 신고자 본인은 자신이 접수한 신고 상태만 확인 가능.
- admin은 신고를 검토 후 `actioned`(글 삭제·작성자 경고) 또는 `dismissed`(기각).

#### 2.2.5 `PromotionOrder` — 판촉물 주문

```python
class PromotionOrder(models.Model):
    STATUS = (
        (1, 'submitted'),    # 접수 (설계사 제출 완료)
        (2, 'confirmed'),    # 접수 확인 (admin 확인)
        (3, 'in_production'),# 제작 중
        (4, 'shipped'),      # 배송 중
        (5, 'completed'),    # 완료
        (6, 'cancelled'),    # 취소
    )

    owner       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True, related_name='promotion_orders')  # 주문 설계사
    items       = models.JSONField()  # [{"product_id": 1, "name": "리플렛A", "qty": 100}, ...]
    delivery_address = models.TextField()  # 배송지 (설계사 입력)
    memo        = models.TextField(null=True, blank=True)  # 요청 메모
    status      = models.SmallIntegerField(choices=STATUS, default=1)
    admin_note  = models.TextField(null=True, blank=True)  # admin 처리 메모
    status_updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                           null=True, related_name='orders_managed')
    status_updated_at = models.DateTimeField(null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)
```

- **가시성**: 설계사는 본인 주문만. admin은 전체.
- `items`는 JSONField로 유연하게(판촉물 카탈로그 변경에 스키마 마이그레이션 불필요).
- 상태 변경마다 설계사에게 `Notification` 발송.

---

## 3. 권한 / 가시성 매트릭스

### 3.1 admin role 정의

```python
# Profile 기존 필드 재사용 — 신규 추가 없음
Profile.is_admin = True  # admin 게이트

# 핵심 원칙
# 1. admin은 OwnedQuerySetMixin 화이트리스트 ①에 의해 모든 쿼리 bypass
# 2. 단, '소유자 전용' 데이터는 READ-ONLY (고객·보험·분석 등)
# 3. admin 권한을 설계사 계정에 부여하면 데이터 격리가 무너짐 → 절대 금지
```

### 3.2 데이터별 admin 접근 범위

| 데이터 | admin 접근 | 제한 |
|---|---|---|
| `User` + `Profile` | 전체 읽기 + 멤버십 변경 | 비밀번호 직접 변경 불가(reset 링크 발송만) |
| `UserMembership` | 전체 읽기 + 플랜 변경 | 과금 이력은 READ-ONLY |
| `Customer` (고객 정보) | READ-ONLY | 수정·삭제 금지 (설계사 소유권 원칙) |
| `CustomerInsurance` | READ-ONLY | 동일 |
| `ConsentLog` | READ-ONLY | 수정·삭제 절대 금지 (감사 무결성) |
| `NormalizationDict` | 전체 CRUD | 매핑 1탭 검수 = 핵심 운영 기능 |
| `UnmatchedLog` | 읽기 + `resolved` 플래그 | 삭제 불가 (학습 로그 보존) |
| `Announcement` | 전체 CRUD | — |
| `FAQ` | 전체 CRUD | — |
| `Inquiry` | 읽기 + 응답(`admin_reply`) | 설계사 문의 원문 삭제 불가 |
| `BoardReport` | 읽기 + 처리 액션 | 신고 원문 삭제 불가 |
| `PromotionOrder` | 읽기 + 상태 변경 + 메모 | 주문 내용 수정 불가(설계사 제출 그대로) |
| `NorthStarEvent` | READ-ONLY 집계 | 원본 이벤트 수정 절대 금지 |

### 3.3 가시성 요약

```
[공유 — 모든 설계사가 봄]
  Announcement (admin 작성, 전체 읽기)
  FAQ          (admin 작성, 전체 읽기)
  게시판 SNS피드 글·댓글 (설계사 작성, 전체 읽기)

[비공개 — 작성자 + admin]
  Inquiry (1:1 문의)
  BoardReport (신고 접수)

[소유자 + admin]
  PromotionOrder (설계사 본인 주문 + admin 전체)
  UserMembership / 사용량

[admin 전용]
  통계 대시보드 (전체 집계)
  ConsentLog 열람
  NormalizationDict 매핑 큐
  UnmatchedLog 검수 큐
```

---

## 4. 화면 구성 — admin 콘솔 IA

### 4.1 진입점

```
/admin-login          → admin 전용 이메일/비밀번호 로그인 (설계사 로그인과 완전 분리)
/admin/*              → 인증된 admin만 접근 (미인증 시 /admin-login 리다이렉트)
```

**설계사 콘솔(`/home`, `/customer`, ...)**과 **admin 콘솔(`/admin/*`)**은 URL 네임스페이스가 분리된다.

### 4.2 사이드바 메뉴

```
[인파 Admin]
├── 📊 대시보드          /admin
├── 👤 설계사 관리       /admin/users
├── 📋 게시판 모더레이션  /admin/board
├── 📢 공지사항          /admin/announcements
├── ❓ FAQ              /admin/faq
├── 💬 1:1 문의          /admin/inquiries
├── 📦 판촉물 주문        /admin/orders
├── 🔑 동의 로그          /admin/consent-logs
├── 🗂️ 정규화 매핑 큐    /admin/normalization
└── ⚙️ 설정             /admin/settings
```

### 4.3 화면별 스펙

#### A. 대시보드 `/admin`

운영 핵심 지표를 한눈에. **사실 카운트만, 판정어 금지.**

```
┌─ 오늘 현황 카드 4종 ──────────────────────────────────────────────┐
│  신규 가입 설계사 | 신규 주문(판촉물) | 미처리 문의 | 신규 신고       │
└────────────────────────────────────────────────────────────────────┘

┌─ 누적 지표 카드 ──────────────────────────────────────────────────┐
│  전체 설계사 수 | 전체 고객 수(READ-ONLY) | 전체 OCR 업로드         │
│  이번 달 share_view 건수 | 이번 달 referral_attributed 건수         │
└────────────────────────────────────────────────────────────────────┘

┌─ 요금제 분포 (도넛 차트) ─────────────────────────────────────────┐
│  Basic / Plus / Pro / Beta (티어별 설계사 수)                       │
└────────────────────────────────────────────────────────────────────┘

┌─ 최근 미처리 항목 (빠른 접근) ────────────────────────────────────┐
│  ⚠ 판촉물 주문 N건 대기 중 → [주문 처리]                           │
│  ⚠ 1:1 문의 N건 미응답 → [문의 보기]                              │
│  ⚠ 신고 N건 검토 대기 → [신고 처리]                               │
│  ⚠ 정규화 매핑 N건 대기 → [매핑 큐]                              │
└────────────────────────────────────────────────────────────────────┘
```

- 모든 숫자: `Intl.NumberFormat('ko-KR')` + `tabular-nums`.
- 새로고침 간격: (추정) 5분 폴링 또는 수동 새로고침 버튼. 실시간 WebSocket은 MVP 범위 외.

#### B. 설계사 관리 `/admin/users`

| 컬럼 | 내용 |
|---|---|
| 이름 / 이메일 | 설계사 기본 정보 |
| 소속 | `Profile.affiliation` |
| 요금제 | `UserMembership.plan` |
| 가입일 | `User.date_joined` |
| 마지막 로그인 | `User.last_login` |
| 상태 | 활성/휴면/탈퇴 (`is_dormant`, `will_delete_at`) |
| 액션 | 상세보기, 요금제 변경, 비밀번호 재설정 링크 발송 |

**검색/필터**: 이름·이메일, 요금제, 상태, 가입기간, 소속.

**상세 `/admin/users/:id`**:
- 프로필 정보 (읽기)
- 요금제·AI 크레딧 사용량 (변경 가능)
- 이번 달 OCR 업로드 수·share_view 수 (읽기)
- ConsentLog 목록 (읽기)
- `owner=NULL` 고객이 있을 경우 → 재배정 버튼 표시(dev/11 §4.4 SET_NULL 유령행 처리)

**요금제 변경**: 드롭다운 선택 → 확인 다이얼로그 → `UserMembership` 업데이트 → 설계사 인앱 알림.

**비밀번호 재설정**: admin이 직접 변경하지 않음. 이메일로 재설정 링크 발송 → 설계사 본인이 변경. (보안 원칙: admin이 비밀번호를 알아서는 안 됨.)

#### C. 게시판 모더레이션 `/admin/board`

SNS 피드 글·댓글 신고 처리.

```
┌─ 신고 큐 (status=pending 우선) ──────────────────────────────────┐
│  신고일 | 신고자 | 대상 (글/댓글 미리보기) | 이유 | 상태          │
│  ────────────────────────────────────────────────────────         │
│  [검토] → 원문 보기 (글 전문 + 신고 사유 상세)                     │
│    → [삭제 처리]  post 삭제 + 작성자 경고 알림 + status=actioned  │
│    → [기각]       status=dismissed + action_note 입력             │
└────────────────────────────────────────────────────────────────────┘
```

- 신고 처리 후 신고자에게 인앱 알림(처리 결과).
- 같은 글에 신고가 N건 이상 쌓이면 대시보드 카드에 경고 카운트 증가.

#### D. 공지사항 `/admin/announcements`

| 동작 | 설명 |
|---|---|
| 목록 | 전체 공지 (임시저장 포함). `published_at` 기준 내림차순 |
| 작성 | 제목 + 본문(마크다운 지원(추정)) + 상단고정 여부 + 게시/임시저장 |
| 수정 | 게시 후에도 수정 가능. 수정 시 `updated_at` 갱신 |
| 삭제 | 소프트 삭제 (설계사 화면에서만 안 보임, DB 보존) |
| 즉시 게시 | `published_at = now()` |

**설계사 화면**(`/announcements`): `published_at IS NOT NULL` 항목만. `is_pinned` 항목 상단 고정.

#### E. FAQ `/admin/faq`

| 동작 | 설명 |
|---|---|
| 목록 | 카테고리별 탭 + `order` 순서 |
| 작성/수정 | 질문·답변·카테고리·순서·공개여부 |
| 순서 변경 | (추정) 드래그 또는 순서 숫자 직접 입력 |
| 공개/비공개 토글 | `is_published` 플립 |

#### F. 1:1 문의 `/admin/inquiries`

```
┌─ 문의 목록 (status=pending 우선) ────────────────────────────────┐
│  접수일 | 설계사명 | 제목 | 상태 | 처리자                          │
│  ────────────────────────────────────────────────────────         │
│  [응답] → 문의 전문 열람                                           │
│    → admin_reply 텍스트 입력 → [답변 등록]                        │
│    → status=resolved, replied_at=now(), 설계사 알림 발송           │
└────────────────────────────────────────────────────────────────────┘
```

- **필터**: 상태별(pending/in_progress/resolved/closed), 기간, 설계사명.
- 응답 후에도 status를 `closed`로 직접 변경 가능(이슈 종결 확인).
- 설계사가 추가 문의를 남기면 status가 다시 `in_progress`로 전환.

#### G. 판촉물 주문 `/admin/orders`

```
┌─ 주문 목록 (status=submitted 우선) ──────────────────────────────┐
│  주문일 | 설계사명 | 주문 내역 요약 | 배송지 | 상태 | 처리일        │
│  ────────────────────────────────────────────────────────         │
│  [처리] → 상세 모달                                                │
│    주문 상세: 설계사 정보 + 주문 품목(items) + 배송지 + 메모        │
│    상태 변경: submitted → confirmed → in_production → shipped → completed │
│    admin_note: 내부 처리 메모 (제작 업체, 송장번호 등)             │
└────────────────────────────────────────────────────────────────────┘
```

**상태 변경 흐름 (운영 워크플로)**:

```
설계사 주문 제출 → [submitted]
  ↓ admin 확인 + 내부 처리 메모
[confirmed]   → 설계사 알림 "주문이 접수 확인되었습니다"
  ↓ 제작 착수
[in_production] → 설계사 알림 "제작이 시작되었습니다"
  ↓ 발송
[shipped]    → 설계사 알림 "배송이 시작되었습니다" (admin_note에 송장번호 입력)
  ↓ 수령 확인
[completed]  → 설계사 알림 "주문이 완료되었습니다"
```

- 상태 변경마다 `status_updated_by`, `status_updated_at` 자동 기록.
- `cancelled`: 어느 단계에서든 취소 가능(설계사 요청 또는 admin 판단). 취소 사유 `admin_note` 필수.

**주문 통계 (대시보드 연동)**: 이번 달 주문 건수, 완료율, 평균 처리 기간(submitted→completed). (추정) 제작 비용 집계는 외부 회계 시스템 연동 → MVP 범위 외.

#### H. 동의 로그 `/admin/consent-logs`

```
┌─ ConsentLog 목록 (READ-ONLY) ────────────────────────────────────┐
│  고객명(마스킹) | 설계사명 | 동의 종류 | 동의일 | 버전 | IP | 철회 │
│  ────────────────────────────────────────────────────────         │
│  [상세] → ConsentLog 전체 필드 열람                               │
│  ※ 수정·삭제 버튼 물리 부재 (감사 무결성)                         │
└────────────────────────────────────────────────────────────────────┘
```

- **필터**: 동의 종류(overseas/selfdiag/marketing), 기간, 설계사, 철회 여부.
- 고객명은 `홍**` 마스킹 (PII 최소 노출).
- admin도 `ConsentLog` 삭제 불가 — API 레벨에서 DELETE 미구현.
- 법무 감사 요청 시: CSV 내보내기 버튼(추정). 다운로드 이력 별도 로깅.

#### I. 정규화 매핑 큐 `/admin/normalization`

**이 화면이 데이터 복리 해자의 운영 엔진이다.** (dev/02 §5 학습루프)

```
┌─ 미매칭 큐 (UnmatchedLog, resolved=False 우선) ──────────────────┐
│  raw_name | 보험사 | 발생 횟수 | 주변 텍스트(sample_ctx) | 매핑   │
│  ────────────────────────────────────────────────────────         │
│  "특정고도질병진단비" | 삼성생명 | 7회 | ... | [AnalysisDetail 검색] │
│                                                    ↓ 드롭다운 선택  │
│                                              [매핑 등록] → resolved=True │
└────────────────────────────────────────────────────────────────────┘

┌─ 기존 사전 (NormalizationDict) ──────────────────────────────────┐
│  표준 담보 | raw_name | 보험사 | 출처 | 신뢰도 | 조회 횟수         │
│  검색 + 수정(신뢰도 조정) + 삭제(오매핑 정정)                     │
└────────────────────────────────────────────────────────────────────┘
```

**1탭 매핑 흐름**:
1. `UnmatchedLog` 미해결 항목 선택
2. `AnalysisDetail` 검색 (표준 담보명 입력 → 자동완성)
3. `[매핑 등록]` → `NormalizationDict` 추가(`source=admin_verified`) + `UnmatchedLog.resolved=True`
4. 다음 OCR부터 자동 매칭 (hit_count 증가)

**오매핑 정정**: `NormalizationDict` 상세에서 `[삭제]` → 다시 `UnmatchedLog` 큐로. 오매핑 방지가 §97 위반 방어선이므로 정정 이력 별도 로그 (추정: `admin_note` 컬럼 추가).

---

## 5. API 계약 (admin 전용 엔드포인트)

> 모든 admin API는 `IsAdminUser` permission 필수. base path `/api/v1/admin/`.

| Method · Path | 용도 | 응답 |
|---|---|---|
| `GET /admin/dashboard/` | 운영 지표 집계 (오늘/누적 카운트 + 요금제 분포) | 집계 JSON |
| `GET /admin/users/` | 설계사 목록 (검색·필터) | 페이지네이션 |
| `GET /admin/users/:id/` | 설계사 상세 + 크레딧 사용량 | 상세 JSON |
| `PATCH /admin/users/:id/membership/` | 요금제 변경 | 업데이트된 멤버십 |
| `POST /admin/users/:id/send_reset_email/` | 비밀번호 재설정 이메일 발송 | `{sent: true}` |
| `GET /admin/inquiries/` | 문의 목록 (필터: status/기간) | 페이지네이션 |
| `PATCH /admin/inquiries/:id/reply/` | 문의 응답 등록 | 업데이트된 Inquiry |
| `GET /admin/reports/` | 신고 목록 | 페이지네이션 |
| `PATCH /admin/reports/:id/action/` | 신고 처리(삭제/기각) | 업데이트된 BoardReport |
| `GET /admin/orders/` | 판촉물 주문 목록 | 페이지네이션 |
| `PATCH /admin/orders/:id/status/` | 주문 상태 변경 + admin_note | 업데이트된 PromotionOrder |
| `GET /admin/consent-logs/` | 동의 로그 목록 (READ-ONLY) | 페이지네이션 |
| `GET /admin/normalization/unmatched/` | 미매칭 큐 목록 | 페이지네이션 |
| `POST /admin/normalization/map/` | 매핑 등록 (unmatched → dict) | 생성된 NormalizationDict |
| `GET /admin/normalization/dict/` | 기존 사전 목록 + 검색 | 페이지네이션 |
| `DELETE /admin/normalization/dict/:id/` | 오매핑 삭제 | `{deleted: true}` |
| `GET /api/v1/announcements/` | 공지사항 목록 (설계사 공개) | 페이지네이션 |
| `POST /api/v1/admin/announcements/` | 공지 작성 | 생성된 Announcement |
| `PATCH /api/v1/admin/announcements/:id/` | 공지 수정 | 업데이트 |
| `DELETE /api/v1/admin/announcements/:id/` | 공지 삭제(소프트) | `{deleted: true}` |
| `GET /api/v1/faq/` | FAQ 목록 (설계사 공개, published_only) | 카테고리별 |
| `POST /api/v1/admin/faq/` | FAQ 작성 | 생성된 FAQ |
| `PATCH /api/v1/admin/faq/:id/` | FAQ 수정 | 업데이트 |
| `DELETE /api/v1/admin/faq/:id/` | FAQ 삭제 | `{deleted: true}` |

**공통 API 원칙**:
- `IsAdminUser` permission: `request.user.profile.is_admin == True` 확인. False면 403.
- 설계사 API와 네임스페이스 분리 (`/admin/` prefix). admin 엔드포인트에 일반 설계사 접근 불가.
- 페이지네이션: `?page=&page_size=` (기본 20). 대용량 목록(ConsentLog·설계사) 필수.
- 정렬: `?ordering=-created_at` 기본값.

---

## 6. 인증 — admin 전용 이메일/비밀번호 로그인

### 6.1 흐름

```
[admin]                [inpa_fe /admin-login]               [inpa_be]
  │  이메일/비밀번호     │                                        │
  │──────────────────→  │                                        │
  │                     │ POST /api/v1/admin/auth/login/         │
  │                     │──────────────────────────────────────→ │
  │                     │                                   authenticate(email, pw)
  │                     │                                   + check is_admin=True
  │                     │  { token }                             │
  │                     │←───────────────────────────────────────│
  │                     │ localStorage: admin_token              │
  │                     │ → /admin (대시보드)                     │
```

### 6.2 admin 인증 API

| Method · Path | 용도 | 비고 |
|---|---|---|
| `POST /api/v1/admin/auth/login/` | 이메일+비밀번호 → DRF Token | `is_admin=False`면 403 |
| `POST /api/v1/admin/auth/logout/` | 토큰 폐기 | — |

**로그인 응답**:
```json
{
  "token": "9a8b7c…",
  "admin": {
    "email": "admin@inpa.kr",
    "name": "운영자"
  }
}
```

### 6.3 설계사 로그인과의 분리

- 설계사: `/login` → 이메일/비밀번호 → `POST /api/v1/auth/login/` → 토큰 발급
- admin: `/admin-login` → 이메일/비밀번호 → `POST /api/v1/admin/auth/login/` → `is_admin` 확인 후 토큰 발급
- 두 토큰은 동일한 DRF Token 모델이지만 **별도 엔드포인트 + is_admin 게이트**로 구분.
- admin 토큰으로 설계사 API 호출 시 `OwnedQuerySetMixin` bypass가 적용됨에 주의 — admin이 설계사 데이터를 직접 조작하지 않도록 FE 레벨에서도 admin 전용 뷰만 노출.

---

## 7. 컴플라이언스 · 면책

| 영역 | 규칙 |
|---|---|
| ConsentLog | admin도 수정·삭제 불가. API DELETE 미구현. 감사 무결성 최우선 |
| 고객 데이터 열람 | admin은 READ-ONLY. 설계사의 고객 정보를 admin이 수정하면 소유권 침해 |
| 판정어 금지 | admin 대시보드 지표도 사실 카운트만. "활성화율 낮음/위험" 등 판정 레이블 금지 |
| PII 마스킹 | 동의 로그의 고객명은 `홍**` 마스킹. admin도 원칙 적용 |
| admin 로그 | (추정) admin 주요 액션(요금제 변경·신고 처리·매핑 등록)은 별도 audit log 적재. MVP에서는 `status_updated_by` / `actioned_by` / `verified_by` FK로 대체 |
| 비밀번호 | admin이 설계사 비밀번호를 직접 보거나 변경하지 않음. 재설정 이메일 발송만 허용 |

---

## 8. 수용 기준 (Definition of Done)

- [ ] `/admin-login` → 이메일/비밀번호 → `is_admin=True` 확인 → `/admin` 진입. `is_admin=False` 설계사는 403.
- [ ] 설계사 목록: 검색·필터·요금제 변경·비밀번호 재설정 이메일 발송 동작.
- [ ] `owner=NULL` 유령 고객이 있는 설계사 상세에서 재배정 버튼 노출.
- [ ] 판촉물 주문: submitted → confirmed → in_production → shipped → completed 전체 상태 흐름 동작. 상태 변경마다 설계사 `Notification` 발송 확인.
- [ ] 1:1 문의: admin_reply 입력 → status=resolved → 설계사 알림 발송.
- [ ] 신고 처리: 글 삭제 액션 → `post_id` 해당 게시물 소프트 삭제 + 신고자 알림.
- [ ] ConsentLog 열람 화면에서 수정·삭제 버튼 DOM 및 API 모두 물리 부재 확인(grep).
- [ ] 정규화 매핑: UnmatchedLog → NormalizationDict 추가 → `resolved=True` → 다음 OCR 자동 매칭 happy path 테스트.
- [ ] 공지사항 작성 → 설계사 화면에서 즉시 노출 + 임시저장은 비노출 확인.
- [ ] admin 대시보드 지표에 판정어 없음: CI grep 골든 회귀 통과.
- [ ] `tsc --noEmit` + `pytest` + admin API permission 테스트(설계사 token으로 `/api/v1/admin/` 호출 → 403) 전 통과.

---

## 9. 기획 갭 / 미결

| # | 항목 | 영향 | 기본값 |
|---|---|---|---|
| A-1 | **멀티 admin role** (슈퍼/서브 권한 분리, 예: 컨텐츠 담당/운영 담당 분리) | (추정) 팀 확장 시 필요 | MVP: 단일 admin role. P2 이후 재검토 |
| A-2 | **판촉물 카탈로그 관리** (admin이 직접 판촉물 상품 목록을 추가·수정) | `PromotionOrder.items` JSON 구조와 연동 | MVP: items JSON 자유입력. 카탈로그 테이블은 P1 이후 |
| A-3 | **정규화 사전 오매핑 이력 로그** (삭제 시 audit) | 비교안내서 §97 오류 방어 | 기본값: `admin_note` 필드에 텍스트 기록(테이블 별도 추가는 P1) |
| A-4 | **admin 감사 로그** (주요 액션 별도 테이블) | 컴플라이언스 요구 가능성 | MVP: FK(`actioned_by`, `replied_by`) 수준. 정식 출시 전 감사 로그 테이블 여부 법무 확인 |
| A-5 | **ConsentLog CSV 내보내기** (법무 감사 요청 대응) | 법무 요청 시 즉시 필요 | (추정) 버튼 자리만 확보, 다운로드 이력 로깅 동반 필요 |
| A-6 | **설계사 강제 탈퇴·계정 정지** (약관 위반) | 운영 필수 | MVP: `is_dormant` 수동 설정으로 대체(추정). 정식 ban 기능은 P1 |
| A-7 | **판촉물 주문 비용 집계** (월간 제작비 총액) | 외부 회계 연동 필요 | MVP: admin_note에 수기 입력. 자동 집계는 P2 |

---

*본 문서는 인파(Inpa) 개발 정본 `dev/19-admin-console.md`. 상위 정본: `dev/02-data-model-and-api.md`(모델), `dev/11-auth-onboarding.md`(인증·멀티테넌시), `dev/06-mvp-slice-plan.md`(빌드 순서). 가시성 매트릭스 기준: CLAUDE.md 확정 멀티테넌시 매트릭스.*
