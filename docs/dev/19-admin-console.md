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
| `Subscription` + `UsageMeter` | ♻ | 요금제 확인·변경 (dev/02 §12) |
| `ConsentLog` | ♻ READ-ONLY | 동의 감사 로그 열람 |
| `NormalizationDict` | ♻ + admin 매핑 | 정규화 사전 1탭 추가 |
| `UnmatchedLog` | ♻ + resolved 플래그 | 미매칭 검수 큐 |
| `Notification` | ♻ | 알림 발송 이력 확인 |

### 2.2 신규 모델 (admin 전용)

#### 2.2.1 `Notice` — 공지사항

> **정본 결정 9:** 모델명 `Notice` (구 `Announcement` 폐기). 정본 `dev/02 §10.6`.

```python
class Notice(models.Model):
    title        = models.CharField(max_length=200)
    body         = models.TextField()
    is_pinned    = models.BooleanField(default=False)  # 상단 고정
    is_published = models.BooleanField(default=False)  # False=임시저장
    published_at = models.DateTimeField(null=True, blank=True)  # null=임시저장
    author       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                      null=True, related_name='notices')  # admin 작성자
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)
```

- **가시성**: 공개읽기 + 관리자쓰기 (비인증 포함 GET 허용, 쓰기는 admin 전용).
- `published_at is None` → 임시저장(설계사에게 안 보임).
- `is_pinned=True` → 공지 목록 최상단 고정.

#### 2.2.2 `Faq` — 자주 묻는 질문

> **정본 결정 9:** 모델명 `Faq` (구 `FAQ` 폐기). 정본 `dev/02 §10.7`.

```python
class Faq(models.Model):
    question     = models.CharField(max_length=300)
    answer       = models.TextField()
    category     = models.CharField(max_length=50, default='general')  # general/billing/feature
    order        = models.SmallIntegerField(default=0)  # 노출 순서 (낮을수록 상위)
    is_published = models.BooleanField(default=False)
    author       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                      null=True, related_name='faqs')
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)
```

- **가시성**: 공개읽기 + 관리자쓰기 (비인증 포함 GET 허용, 쓰기는 admin 전용).
- `is_published=False` → 초안, 설계사에게 안 보임.
- `category`로 탭 분류(과금/기능/컴플라이언스 등).

#### 2.2.3 `Inquiry` — 1:1 문의

> **정본 결정 9:** `author` → `owner` FK(User CASCADE), `status` = 문자열 open|answered|closed. 정본 `dev/02 §10.8`.

```python
class Inquiry(models.Model):
    STATUS_CHOICES = (
        ('open',     '접수'),
        ('answered', '답변 완료'),
        ('closed',   '종결'),
    )

    owner       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                     related_name='inquiries')  # 설계사 (소유자)
    category    = models.CharField(max_length=30)
    title       = models.CharField(max_length=200)
    body        = models.TextField()
    status      = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)
```

관계: `Inquiry` →< `InquiryReply` (별도 모델). 답변은 `InquiryReply`로 스레드 구조.

- **가시성**: 비공개 — owner 본인 + admin. `OwnedQuerySetMixin` + `IsOwner` 적용.
- status: `open`(접수) → `answered`(답변 완료) → `closed`(종결). admin이 상태 전환.
- admin 답변 등록(`InquiryReply`) → status=answered → 설계사 인앱 알림(`Notification`).

#### 2.2.4 `Report` — 게시판 신고

> **정본 결정 9:** 모델명 `Report` (구 `BoardReport` 폐기). 가시성: 신고자 본인 조회 + admin 처리. 정본 `dev/02 §10.5`.

```python
class Report(models.Model):
    REASON_CHOICES = (
        ('spam',          '스팸'),
        ('inappropriate', '부적절한 내용'),
        ('misinformation','허위 정보'),
        ('other',         '기타'),
    )
    STATUS_CHOICES = (
        ('pending',   '검토 대기'),
        ('resolved',  '처리 완료'),
        ('dismissed', '기각'),
    )

    reporter        = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                         null=True, related_name='reports_filed')
    content_type    = models.CharField(max_length=20)   # 'post' | 'comment'
    object_id       = models.IntegerField()              # 신고 대상 게시물/댓글 ID
    reason          = models.CharField(max_length=30, choices=REASON_CHOICES)
    detail          = models.TextField(null=True, blank=True)  # 신고 사유 부연
    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    resolved_by     = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                         null=True, related_name='reports_actioned')
    resolved_at     = models.DateTimeField(null=True, blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['reporter', 'content_type', 'object_id'], name='uniq_report')]
```

- **가시성**: 신고자 본인은 본인 신고 상태 조회만 가능. admin은 전체 처리.
- admin은 신고를 검토 후 `resolved`(글 삭제·작성자 경고) 또는 `dismissed`(기각).

#### 2.2.5 `PromotionOrder` + `PromotionOrderStatusLog` — 판촉물 주문

> **정본 결정 10:** `form_response`(JSON)·문자열 status·`PromotionOrderStatusLog` 별도 모델. `items`/`delivery_address` 폐기, SmallInt status 폐기. 정본 `dev/02 §11.3`·`§11.4`.

```python
class PromotionOrder(models.Model):
    STATUS_CHOICES = (
        ('pending',    '접수 대기'),
        ('reviewing',  '검토 중'),
        ('producing',  '제작 중'),
        ('shipping',   '배송 중'),
        ('completed',  '완료'),
        ('cancelled',  '취소'),
    )

    owner           = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                         null=True, related_name='promotion_orders')  # 주문 설계사
    sample          = models.ForeignKey('PromotionSample', on_delete=models.SET_NULL, null=True)
    form_response   = models.JSONField()   # 키=PromotionSample.form_fields[].key (품목·수량·배송지 등 흡수)
    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    admin_note      = models.TextField(null=True, blank=True)  # 설계사에게도 노출되는 처리 메모
    tracking_number = models.CharField(max_length=100, null=True, blank=True)
    carrier         = models.CharField(max_length=50, null=True, blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

class PromotionOrderStatusLog(models.Model):
    order       = models.ForeignKey(PromotionOrder, on_delete=models.CASCADE,
                                     related_name='status_logs')
    to_status   = models.CharField(max_length=20)
    changed_by  = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True)  # admin
    changed_at  = models.DateTimeField(auto_now_add=True)
    note        = models.TextField(default='')
```

- **가시성**: 설계사는 본인 주문만. admin은 전체. `OwnedQuerySetMixin` 적용.
- `form_response` JSON이 품목·수량·배송지 등 모든 주문 데이터를 흡수 (카탈로그 폼 필드 구조와 1:1).
- 상태 변경마다 `PromotionOrderStatusLog` 1행 추가 + 설계사에게 `Notification` 발송.
- `admin_note`는 설계사 화면에도 노출(배송 안내 등).

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
| `Subscription` / `UsageMeter` | 전체 읽기 + 플랜 변경 | 과금 이력은 READ-ONLY |
| `Customer` (고객 정보) | READ-ONLY | 수정·삭제 금지 (설계사 소유권 원칙) |
| `CustomerInsurance` | READ-ONLY | 동일 |
| `ConsentLog` | READ-ONLY | 수정·삭제 절대 금지 (감사 무결성) |
| `NormalizationDict` | 전체 CRUD | 매핑 1탭 검수 = 핵심 운영 기능 |
| `UnmatchedLog` | 읽기 + `resolved` 플래그 | 삭제 불가 (학습 로그 보존) |
| `Notice` | 전체 CRUD | — |
| `Faq` | 전체 CRUD | — |
| `Inquiry` | 읽기 + `InquiryReply` 작성 | 설계사 문의 원문 삭제 불가 |
| `Report` | 읽기 + 처리 액션 | 신고 원문 삭제 불가 |
| `PromotionOrder` | 읽기 + 상태 변경 + admin_note | 주문 내용(`form_response`) 수정 불가(설계사 제출 그대로) |
| `NorthStarEvent` | READ-ONLY 집계 | 원본 이벤트 수정 절대 금지 |

### 3.3 가시성 요약

```
[공개읽기 + 관리자쓰기]
  Notice (admin 작성, 비인증 포함 전체 읽기)
  Faq    (admin 작성, 비인증 포함 전체 읽기)

[공유 — 모든 설계사가 봄]
  게시판 SNS피드 글·댓글 (설계사 작성, 전체 읽기)

[비공개 — 작성자 + admin]
  Inquiry (1:1 문의, owner FK CASCADE)

[신고자 본인 조회 + admin 처리]
  Report (신고 접수)

[소유자 + admin]
  PromotionOrder (설계사 본인 주문 + admin 전체)
  Subscription / UsageMeter (요금제·사용량)

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
| 요금제 | `Subscription.plan` |
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
- `Customer.owner`는 CASCADE(설계사 탈퇴 시 고객 데이터 함께 삭제 — dev/02 §3.1 결정 8). 유령행 발생 시나리오는 CASCADE에 의해 제거됨. soft-delete 유예기간 정책은 openGap.
- admin 데이터 열람 시: `planner_baseline` 없는 고객의 담보 상태는 **neutral 강제** — admin 화면에서도 "부족/충분" 단정 금지. 사실 카운트(보유금액)만 표기(dev/02 §1 준법 통제점).

**요금제 변경**: 드롭다운 선택 → 확인 다이얼로그 → `Subscription` 업데이트 → 설계사 인앱 알림.

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

> **정본 결정 9:** 모델명 `Notice`. 설계사 화면 라우트 `/notice`.

| 동작 | 설명 |
|---|---|
| 목록 | 전체 공지 (임시저장 포함). `published_at` 기준 내림차순 |
| 작성 | 제목 + 본문(마크다운 지원(추정)) + 상단고정 여부 + 게시/임시저장 |
| 수정 | 게시 후에도 수정 가능. 수정 시 `updated_at` 갱신 |
| 삭제 | 소프트 삭제 (설계사 화면에서만 안 보임, DB 보존) |
| 즉시 게시 | `published_at = now()`, `is_published = True` |

**설계사 화면**(`/notice`): `is_published=True` 항목만 (비인증 포함 AllowAny GET). `is_pinned` 항목 상단 고정.

#### E. FAQ `/admin/faq`

> **정본 결정 9:** 모델명 `Faq`. 설계사 화면 라우트 `/faq` (비인증 포함 AllowAny GET).

| 동작 | 설명 |
|---|---|
| 목록 | 카테고리별 탭 + `order` 순서 |
| 작성/수정 | 질문·답변·카테고리·순서·공개여부 |
| 순서 변경 | (추정) 드래그 또는 순서 숫자 직접 입력 |
| 공개/비공개 토글 | `is_published` 플립 |

#### F. 1:1 문의 `/admin/inquiries`

```
┌─ 문의 목록 (status=open 우선) ────────────────────────────────────┐
│  접수일 | 설계사명 | 제목 | 상태 | 처리자                          │
│  ────────────────────────────────────────────────────────         │
│  [응답] → 문의 전문 열람                                           │
│    → InquiryReply 텍스트 입력 → [답변 등록]                       │
│    → status=answered, 설계사 알림 발송                             │
└────────────────────────────────────────────────────────────────────┘
```

- **필터**: 상태별(open/answered/closed), 기간, 설계사명.
- 응답 후에도 status를 `closed`로 직접 변경 가능(이슈 종결 확인).
- 설계사가 추가 문의를 남기면 admin이 수동으로 status를 다시 `open`으로 전환 가능.

#### G. 판촉물 주문 `/admin/orders`

```
┌─ 주문 목록 (status=pending 우선) ──────────────────────────────────┐
│  주문일 | 설계사명 | 주문 내역 요약(form_response) | 상태 | 처리일  │
│  ────────────────────────────────────────────────────────           │
│  [처리] → 상세 모달                                                  │
│    주문 상세: 설계사 정보 + form_response(품목·수량·배송지 등) + 상태 타임라인 │
│    상태 변경: pending → reviewing → producing → shipping → completed  │
│    admin_note: 처리 메모 (설계사에게도 노출, 송장번호 등)              │
└────────────────────────────────────────────────────────────────────────┘
```

**상태 변경 흐름 (운영 워크플로)**:

```
설계사 주문 제출 → [pending]
  ↓ admin 검토 + admin_note
[reviewing]   → 설계사 알림 "주문을 검토 중입니다"
  ↓ 제작 착수
[producing]   → 설계사 알림 "제작이 시작되었습니다"
  ↓ 발송
[shipping]    → 설계사 알림 "배송이 시작되었습니다" (admin_note에 송장번호 입력)
  ↓ 수령 확인
[completed]   → 설계사 알림 "주문이 완료되었습니다"
```

- 상태 변경마다 `PromotionOrderStatusLog` 1행 자동 적재(`changed_by`, `changed_at`, `note`).
- `cancelled`: 어느 단계에서든 취소 가능(설계사 요청 또는 admin 판단). 취소 사유 `admin_note` 필수.
- `tracking_number`·`carrier` 필드: shipping 전환 시 입력 (form_response와 별도, 발송 추적용).

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

#### J. 운영 설정 `/admin/settings`

> **정본 결정 14(dev/00 §3.9):** `/admin/settings` = 요금제 Plan·한도, 약관 PolicyVersion, 기능 플래그·`FREE_TIER_UNLIMITED` 관리.

```
┌─ 요금제 & 한도 ────────────────────────────────────────────────────┐
│  Plan(free/plus) 목록: display_name · price_krw                    │
│  한도 필드: limit_ocr / limit_ai_compare / limit_analysis / limit_promotion │
│  null = 무제한 sentinel. 변경 → Plan 테이블 업데이트               │
└────────────────────────────────────────────────────────────────────┘

┌─ 약관 버전 PolicyVersion ─────────────────────────────────────────┐
│  tos / pp / overseas 별 최신 버전 + 이력                           │
│  신규 버전 등록 → version 문자열 + effective_at + requires_reconsent │
└────────────────────────────────────────────────────────────────────┘

┌─ 기능 플래그 ──────────────────────────────────────────────────────┐
│  FREE_TIER_UNLIMITED: True(베타) / False(정식)                     │
│  기타 기능 플래그 (추정: 비교안내서 공개 여부, 야간 배치 on/off 등)  │
└────────────────────────────────────────────────────────────────────┘
```

- 변경은 admin 확인 다이얼로그 필수 (한도·약관·플래그는 전 설계사에 즉시 영향).
- `FREE_TIER_UNLIMITED=False` 전환 시 베타 사용량 초기화 정책 별도 결정(openGap).

---

## 5. API 계약 (admin 전용 엔드포인트)

> 모든 admin API는 `IsAdminUser` permission 필수. base path `/api/v1/admin/`.

| Method · Path | 용도 | 응답 |
|---|---|---|
| `GET /admin/dashboard/` | 운영 지표 집계 (오늘/누적 카운트 + 요금제 분포) | 집계 JSON |
| `GET /admin/users/` | 설계사 목록 (검색·필터) | 페이지네이션 |
| `GET /admin/users/:id/` | 설계사 상세 + 크레딧 사용량 | 상세 JSON |
| `PATCH /admin/users/:id/subscription/` | 요금제 변경 (`Subscription` 업데이트) | 업데이트된 Subscription |
| `POST /admin/users/:id/send_reset_email/` | 비밀번호 재설정 이메일 발송 | `{sent: true}` |
| `GET /admin/inquiries/` | 문의 목록 (필터: status/기간) | 페이지네이션 |
| `POST /admin/inquiries/:id/reply/` | 답변 등록 (`InquiryReply` 생성 + status=answered + 설계사 알림) | 생성된 InquiryReply |
| `PATCH /admin/inquiries/:id/status/` | 문의 상태 변경 (open/answered/closed) | 업데이트된 Inquiry |
| `GET /admin/reports/` | 신고 목록 | 페이지네이션 |
| `PATCH /admin/reports/:id/action/` | 신고 처리(삭제/기각) | 업데이트된 Report |
| `GET /admin/orders/` | 판촉물 주문 목록 | 페이지네이션 |
| `PATCH /admin/orders/:id/status/` | 주문 상태 변경 + admin_note (→ PromotionOrderStatusLog 적재) | 업데이트된 PromotionOrder |
| `GET /admin/consent-logs/` | 동의 로그 목록 (READ-ONLY) | 페이지네이션 |
| `GET /admin/normalization/unmatched/` | 미매칭 큐 목록 | 페이지네이션 |
| `POST /admin/normalization/map/` | 매핑 등록 (unmatched → dict) | 생성된 NormalizationDict |
| `GET /admin/normalization/dict/` | 기존 사전 목록 + 검색 | 페이지네이션 |
| `DELETE /admin/normalization/dict/:id/` | 오매핑 삭제 | `{deleted: true}` |
| `GET /api/v1/notices/` | 공지사항 목록 (AllowAny — 비인증 포함 공개읽기, `is_published=True`만) | 페이지네이션 |
| `POST /api/v1/admin/notices/` | 공지 작성 | 생성된 Notice |
| `PATCH /api/v1/admin/notices/:id/` | 공지 수정 | 업데이트 |
| `DELETE /api/v1/admin/notices/:id/` | 공지 삭제(소프트) | `{deleted: true}` |
| `GET /api/v1/faq/` | FAQ 목록 (AllowAny — 비인증 포함 공개읽기, `is_published=True`만) | 카테고리별 |
| `POST /api/v1/admin/faq/` | FAQ 작성 | 생성된 Faq |
| `PATCH /api/v1/admin/faq/:id/` | FAQ 수정 | 업데이트 |
| `DELETE /api/v1/admin/faq/:id/` | FAQ 삭제 | `{deleted: true}` |
| `GET /api/v1/admin/settings/plans/` | Plan 목록 + 한도 조회 | Plan JSON 배열 |
| `PATCH /api/v1/admin/settings/plans/:code/` | Plan 한도 변경 | 업데이트된 Plan |
| `GET /api/v1/admin/settings/policy-versions/` | PolicyVersion 목록 | 페이지네이션 |
| `POST /api/v1/admin/settings/policy-versions/` | 약관 신규 버전 등록 | 생성된 PolicyVersion |
| `PATCH /api/v1/admin/settings/flags/` | 기능 플래그 변경(`FREE_TIER_UNLIMITED` 등) | 업데이트된 플래그 맵 |

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
| planner_baseline neutral 강제 | admin이 설계사 고객 보장 데이터를 열람할 때도 `planner_baseline` 없는 담보는 "부족/충분" 단정 금지 → 보유 금액(사실)만 표기. 동일 원칙이 admin 뷰에도 적용됨 (dev/02 §1 준법 통제점) |
| PII 마스킹 | 동의 로그의 고객명은 `홍**` 마스킹. admin도 원칙 적용 |
| admin 로그 | (추정) admin 주요 액션(요금제 변경·신고 처리·매핑 등록)은 별도 audit log 적재. MVP에서는 `status_updated_by` / `actioned_by` / `verified_by` FK로 대체 |
| 비밀번호 | admin이 설계사 비밀번호를 직접 보거나 변경하지 않음. 재설정 이메일 발송만 허용 |

---

## 8. 수용 기준 (Definition of Done)

- [ ] `/admin-login` → 이메일/비밀번호 → `is_admin=True` 확인 → `/admin` 진입. `is_admin=False` 설계사는 403.
- [ ] 설계사 목록: 검색·필터·요금제(`Subscription`) 변경·비밀번호 재설정 이메일 발송 동작.
- [ ] 판촉물 주문: pending → reviewing → producing → shipping → completed 전체 상태 흐름 동작. 상태 변경마다 `PromotionOrderStatusLog` 적재 + 설계사 `Notification` 발송 확인.
- [ ] 1:1 문의: `InquiryReply` 등록 → `Inquiry.status=answered` → 설계사 알림 발송. `InquiryReply` 스레드 구조로 답변 목록 조회 동작.
- [ ] 신고(`Report`) 처리: 글 삭제 액션 → `object_id` 해당 게시물 소프트 삭제 + 신고자 알림.
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
| A-2 | **판촉물 카탈로그 관리** (admin이 직접 판촉물 상품 목록·`PromotionSample.form_fields`를 추가·수정) | `PromotionOrder.form_response` JSON 구조와 연동 | MVP: `/admin/promotion/samples` CRUD 구현 목표(dev/21). `form_fields` 빌더 UI는 P1 이후 |
| A-3 | **정규화 사전 오매핑 이력 로그** (삭제 시 audit) | 비교안내서 §97 오류 방어 | 기본값: `admin_note` 필드에 텍스트 기록(테이블 별도 추가는 P1) |
| A-4 | **admin 감사 로그** (주요 액션 별도 테이블) | 컴플라이언스 요구 가능성 | MVP: FK(`actioned_by`, `replied_by`) 수준. 정식 출시 전 감사 로그 테이블 여부 법무 확인 |
| A-5 | **ConsentLog CSV 내보내기** (법무 감사 요청 대응) | 법무 요청 시 즉시 필요 | (추정) 버튼 자리만 확보, 다운로드 이력 로깅 동반 필요 |
| A-6 | **설계사 강제 탈퇴·계정 정지** (약관 위반) | 운영 필수 | MVP: `is_dormant` 수동 설정으로 대체(추정). 정식 ban 기능은 P1 |
| A-7 | **판촉물 주문 비용 집계** (월간 제작비 총액) | 외부 회계 연동 필요 | MVP: admin_note에 수기 입력. 자동 집계는 P2 |

---

*본 문서는 인파(Inpa) 개발 정본 `dev/19-admin-console.md`. 상위 정본: `dev/02-data-model-and-api.md`(모델), `dev/11-auth-onboarding.md`(인증·멀티테넌시), `dev/06-mvp-slice-plan.md`(빌드 순서). 가시성 매트릭스 기준: CLAUDE.md 확정 멀티테넌시 매트릭스.*
