# 인파(Inpa) — 알림 & 리마인더

> dev/22 — 설계사 본인 대상 알림 센터(인앱 + 선택 이메일). 정본 교차: dev/15(대시보드·캘린더), dev/02(데이터 모델), dev/07(API 계약), dev/09(컴플라이언스). 이 문서는 알림 데이터 모델·트리거 규칙·화면·API·수용기준을 못박는다.
>
> **핵심 원칙 1줄**: 알림은 **설계사 본인에게만** 가는 영업 행동 트리거다. 고객에게 자동 발송하는 경로는 물리적으로 없다.

---

## 0. 이 문서가 잠그는 것

| # | 영역 | 핵심 결정 |
|---|---|---|
| 1 | 알림 방향 | 설계사 본인 전용. 고객 자동발송 = 물리 부재 (정직성 레드라인) |
| 2 | 인앱 알림센터 | `/notifications` 페이지 + 헤더 벨 배지(읽지 않은 수) |
| 3 | 이메일 알림 | 선택(opt-in). 설계사가 켜야 수신. 설치형 디폴트 = 꺼짐 |
| 4 | 트리거 5종 | 만기 임박·생일 D-7·상담 약속·할 일 마감·미열람 공유 |
| 5 | ReminderRule | 설계사가 "며칠 전"을 직접 설정. 인파가 권고값을 기본으로 제공 |
| 6 | 멀티테넌시 | Notification은 `owner` FK 소유자 전용. OwnedQuerySetMixin 적용 |
| 7 | 대시보드·캘린더 연동 | 알림 탭은 dev/15 액션큐와 같은 데이터 소스를 소비. 중복 팝업 금지 |

**절대 레드라인 3개**

1. **고객에게 자동발송 없음** — 알림은 설계사 내부 트리거. `customer.mobile_phone_number`에 직접 API 발송 경로 물리 부재.
2. **AI 생성물 면책 고정** — 이메일·인앱에 AI 요약이 들어가면 "AI 초안 · 최종 책임 설계사" 고정 문구 필수.
3. **소유자 격리** — `Notification.owner`가 없는 조회 0건. 설계사 A 알림이 B에게 노출 = 코드리뷰 reject.

---

## 1. 범위 (in / out)

| 구분 | 포함 | 비고 |
|---|---|---|
| **In** | 인앱 알림 센터 화면·벨 배지, Notification 모델, ReminderRule 모델, 알림 5종 트리거, 이메일 발송(선택 opt-in) | net-new BE 모델 2종 |
| **In** | 대시보드 액션큐와 데이터 연동 (같은 소스, 다른 뷰) | dev/15 소비자 |
| **In** | 캘린더 이벤트 기반 트리거 (만기/생일/상담/할일) | CalendarEvent FK |
| **Out** | 고객에게 발송하는 카카오톡·SMS 자동화 | 정직성 레드라인, 설계사 수동 발송만 |
| **Out** | 설계사 그룹/팀 알림 공유 | 테넌트 = 설계사 1인 (P2 이후) |
| **Out** | 푸시 알림(모바일 앱 기반) | (추정) P2. 베타는 인앱+이메일만 |
| **Out** | 자동 AI 리포트 이메일(주간 요약 등) | (추정) P2. 레드라인(AI 초안 면책) 동반 필요 |

---

## 2. 데이터 모델 (net-new 2종)

### 2.1 모델 관계도

```
User(설계사)
  │
  ├─< Notification   ← 발화된 알림(read/unread 상태 머신)
  │       │ owner FK
  │       │ notif_type (5종 enum)
  │       │ target_date (트리거 기준일)
  │       │ calendar_event FK (nullable — 만기/생일/상담/할일)
  │       │ customer FK (nullable)
  │       │ is_read (bool)
  │       │ sent_email (bool — 이메일 발송 여부)
  │
  └─< ReminderRule   ← "며칠 전" 설정(설계사가 변경 가능)
          │ owner FK
          │ rule_type (5종 enum, notif_type 1:1)
          │ days_before (int — 이 트리거는 며칠 전에 알릴지)
          │ enabled (bool)
          │ email_enabled (bool — 이메일도 보낼지)
```

**설계 결정 2가지**

- `ReminderRule`과 `Notification`을 분리한 이유: Rule은 *"언제 발화할 조건"*을 저장하고, Notification은 *"실제 발화된 결과"*를 저장한다. 둘을 섞으면 설정값이 이력에 오염된다.
- `CalendarEvent FK`를 Notification에 넣는 이유: 알림을 클릭 시 해당 이벤트/고객 상세로 원클릭 이동하기 위해. FK가 없으면 FE가 별도 추가 조회를 해야 한다(N+1 트랩).

---

### 2.2 `Notification` — 발화된 알림

```jsonc
{
  "id": 3001,
  "owner_id": 7,                    // FK User(설계사) — 소유자 전용
  "notif_type": "expiry_soon",      // 5종 enum (§2.4 참조)
  "title": "김영희 실손 만기 D-14",  // 알림 제목 (FE 표시)
  "body": "7월 28일 만기입니다. 갱신 안내를 준비해 보세요.",
  "target_date": "2026-07-28",      // 트리거 기준일 (만기일/생일/약속일 등)
  "customer_id": 312,               // FK Customer, nullable
  "calendar_event_id": 1024,        // FK CalendarEvent, nullable
  "is_read": false,                 // 읽음 여부
  "sent_email": false,              // 이메일 발송 여부 (opt-in 설정 기반)
  "created_at": "2026-07-14T09:00:00+09:00"
}
```

**필드 규칙**

| 필드 | 규칙 |
|---|---|
| `owner_id` | 필수. OwnedQuerySetMixin이 모든 조회에 `filter(owner=request.user)` 강제 |
| `notif_type` | 5종 고정 enum (§2.4). 확장 시 마이그레이션 필요 |
| `title` / `body` | BE가 생성. 설계사 내부면이므로 판정어 허용. 고객 공유뷰로 절대 새지 않음 |
| `target_date` | 정렬·그룹화 기준 (당일/미래/지난 알림) |
| `customer_id` | 알림 클릭 → `/customer/:id` 직통. nullable(고객 없는 시스템 알림용) |
| `calendar_event_id` | 알림 클릭 → 캘린더 해당 날짜 포커스. nullable |
| `is_read` | PATCH `/notifications/:id/read/` → true 전환. 일괄 읽음 가능 |
| `sent_email` | 이메일 발송 후 true. 중복 발송 방지 |

---

### 2.3 `ReminderRule` — 설계사별 알림 설정

```jsonc
{
  "id": 201,
  "owner_id": 7,
  "rule_type": "expiry_soon",       // Notification.notif_type과 1:1 대응
  "days_before": 30,                // 기준일 30일 전에 알림 발화
  "enabled": true,                  // 이 유형 알림을 받을지
  "email_enabled": false,           // 이메일로도 받을지 (opt-in, 기본 꺼짐)
  "updated_at": "2026-06-19T12:00:00+09:00"
}
```

**기본값 (설계사가 처음 가입 시 자동 생성 — 이후 변경 가능)**

| rule_type | days_before 기본값 | enabled | email_enabled |
|---|---|---|---|
| `expiry_soon` (만기 임박) | 30 | true | false |
| `birthday_soon` (생일 D-7) | 7 | true | false |
| `consult_reminder` (상담 약속) | 1 | true | false |
| `task_due` (할 일 마감) | 1 | true | false |
| `share_unread` (미열람 공유) | 0 | true | false |

> **(추정)** days_before 기본값은 설계사 실무 피드백 전 가설. 베타 실측 후 조정 필요. `expiry_soon` 30일은 dev/15 액션큐 사유1 임계값(G-3 미확정)과 동일 기준으로 맞춘다. PM 확정 시 동시 변경.

---

### 2.4 `notif_type` 5종 정의

| type | 한국어 라벨 | 트리거 소스 | 기준일 | 기본 days_before |
|---|---|---|---|---|
| `expiry_soon` | 만기 임박 | `CalendarEvent(event_type=expiry)` | 만기일 | 30 |
| `birthday_soon` | 고객 생일 | `CalendarEvent(event_type=birthday)` | 생일 | 7 |
| `consult_reminder` | 상담 약속 | `CalendarEvent(event_type=consult)` | 상담 약속일 | 1 |
| `task_due` | 할 일 마감 | `Task.due_date` | 마감일 | 1 |
| `share_unread` | 미열람 공유 | `Customer.user_view_at` (null 상태 24h+) | 공유 발송 후 24h | 0 |

**`share_unread` 특이사항**: 다른 4종은 CalendarEvent/Task의 날짜 기반이지만, `share_unread`는 시간 기반(24h). `days_before=0`은 "발송 후 24h 경과 시 발화"로 해석한다. (추정) Cron은 4시간 간격 실행으로 24h±4h 오차 허용.

---

## 3. 알림 트리거 로직

### 3.1 발화 흐름

```
[Cron / 이벤트 hook]
        │
        ├─ 매일 오전 9시 KST (cron) ─────────────────────────────────────────────────────┐
        │    대상: expiry_soon / birthday_soon / consult_reminder / task_due             │
        │    쿼리:                                                                       │
        │      CalendarEvent(date = today + days_before)                                │
        │      × ReminderRule(rule_type = 해당, enabled=true, owner=설계사)             │
        │      × Notification이 오늘 이미 발화되지 않은 것 (중복 방지)                    │
        │    → Notification 생성 (is_read=false, sent_email=false)                     │
        │    → email_enabled=true 이면 이메일 발송 → sent_email=true                    │
        │                                                                                │
        ├─ 4시간 간격 cron ─────────────────────────────────────────────────────────────┐ │
        │    대상: share_unread                                                          │ │
        │    쿼리: Customer 중 share_token이 있고 user_view_at IS NULL                  │ │
        │    조건: 공유 발송 시각(share_sent_at 추정 — §6.1 갭) + 24h 경과              │ │
        │    × ReminderRule(share_unread, enabled=true)                                 │ │
        │    → Notification 생성                                                        │ │
        │                                                                                │ │
        └─ 실시간 hook (Django signal) ──────────────────────────────────────────────── │─┘
             CalendarEvent.post_save (manual 이벤트 생성 시)
             → consult_reminder / task_due ReminderRule 즉시 체크
             → 당일 또는 내일이면 즉시 Notification 생성 (cron 대기 없이)
```

### 3.2 중복 방지 규칙

- 동일 `(owner, notif_type, target_date, customer_id)` 조합의 Notification이 오늘 이미 존재하면 발화 생략.
- `expiry_soon`은 같은 만기일에 대해 1회만 발화. 설계사가 알림을 읽고 삭제해도 재발화 없음(다음 만기일 있으면 별도 Notification).

### 3.3 트리거 ↔ 대시보드 액션큐 관계

dev/15 액션큐와 알림 센터는 **같은 데이터 소스를 두 가지 뷰로 소비**한다.

| | 대시보드 액션큐 | 알림 센터 |
|---|---|---|
| 소스 | CalendarEvent + Task + Customer | Notification (발화된 기록) |
| 갱신 | 실시간 SSR(BE 권위 정렬) | is_read 상태 머신 |
| 목적 | "오늘 할 일" 우선순위 큐 | 과거 알림 이력 + 읽음 관리 |
| 중복 | 두 화면 동시에 같은 사유 표시 가능 (의도됨) | — |

**왜 중복이 의도됨인가**: 액션큐는 "지금 할 일의 발사대", 알림 센터는 "놓쳤을 때 복기하는 인박스". 역할이 다르다. FE에서 "액션큐에 있으면 알림 숨기기" 같은 처리를 하면 의존성이 복잡해지고 UX를 더 혼란스럽게 만든다.

---

## 4. 화면 스펙

### 4.1 헤더 벨 배지

```
┌─ 헤더 ──────────────────────────────┐
│  [인파 로고]    ...   [🔔 3]  [내정보] │
└──────────────────────────────────────┘
```

- 벨 아이콘 우상단 배지 숫자 = `Notification(owner=me, is_read=false).count()`
- 최대 표시: `99+` (100 이상이면 `99+`로 클리핑)
- 0개이면 배지 미표시 (빈 벨만)
- 클릭 → `/notifications` 로 이동 (드롭다운 패널 미사용, 페이지 이동 단순화)
- 폴링: `staleTime` 60초 (SWR or React Query). 실시간 WebSocket은 (추정) P2.

### 4.2 알림 센터 `/notifications`

```
┌─ 알림 ───────────────────────────────────────────────────────────┐
│  [전체 읽음 처리]                              [설정 →] (/settings/reminders) │
├──────────────────────────────────────────────────────────────────┤
│  오늘                                                              │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │ 🟣 [만기 임박]  김영희 실손 D-14               07-14 09:00  │    │
│  │    "7월 28일 만기입니다. 갱신 안내를 준비해 보세요."           │    │
│  │    [고객 보기 →]                               ● 미읽음      │    │
│  └──────────────────────────────────────────────────────────┘    │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │ 🎂 [생일]  이순자 D-3                          07-14 09:00  │    │
│  │    "7월 17일 생일입니다. 축하 메시지를 보내보세요."            │    │
│  │    [고객 보기 →]                                            │    │
│  └──────────────────────────────────────────────────────────┘    │
├──────────────────────────────────────────────────────────────────┤
│  어제                                                              │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │ 📨 [미열람]  박철수 공유링크 24h 미열람         07-13 13:05  │    │
│  │    [재발송 준비 →]                                           │    │
│  └──────────────────────────────────────────────────────────┘    │
│  ...                                   [더 보기 / 무한스크롤]       │
└──────────────────────────────────────────────────────────────────┘
```

**표시 규칙**

| 요소 | 규칙 |
|---|---|
| 그룹 | 오늘 / 어제 / 이번 주 / 이전 (날짜 기준 시간 역순) |
| 미읽음 | 좌측 `● 미읽음` 도트 + 배경 약간 강조(`--surface-1` vs `--surface-0`) |
| 읽음 처리 | 항목 클릭 시 자동 읽음(`PATCH /notifications/:id/read/`) |
| 일괄 읽음 | 상단 [전체 읽음 처리] 버튼 → `POST /notifications/read-all/` |
| 삭제 | 개별 스와이프 삭제 또는 우클릭 메뉴 삭제 (`DELETE /notifications/:id/`) |
| 원클릭 이동 | [고객 보기 →] → `/customer/:id`. 해당 고객 없으면 버튼 미표시 |
| 재발송 | `share_unread` 알림의 [재발송 준비 →] → `/customer/:id` 공유탭 (클립보드 복사 — 자동발송 금지) |

**타입별 아이콘·색**

| notif_type | 아이콘 | 색 |
|---|---|---|
| `expiry_soon` | 🟣 | `--cal-expiry` (보라 — 캘린더와 동일, red 금지) |
| `birthday_soon` | 🎂 | `--cal-birthday` (분홍) |
| `consult_reminder` | 💬 | `--accent-blue` |
| `task_due` | ✅ | `--success` |
| `share_unread` | 📨 | `--ink-3` |

> dev/15 §2.2 컬러 팔레트 동일 적용. `expiry_soon` 알림은 **보라** (red = §97 비교안내 전용, 여기 금지).

### 4.3 알림 설정 `/settings/reminders`

```
┌─ 알림 설정 ──────────────────────────────────────────────────────┐
│                                                                    │
│  만기 임박                                    [켜짐 ●]            │
│  ○ 만기 몇 일 전에 알릴까요?  [30] 일 전                         │
│  □ 이메일로도 받기                                                 │
│                                                                    │
│  고객 생일                                    [켜짐 ●]            │
│  ○ 생일 몇 일 전에 알릴까요?  [ 7] 일 전                         │
│  □ 이메일로도 받기                                                 │
│                                                                    │
│  상담 약속                                    [켜짐 ●]            │
│  ○ 약속 몇 일 전에 알릴까요?  [ 1] 일 전                         │
│  □ 이메일로도 받기                                                 │
│                                                                    │
│  할 일 마감                                   [켜짐 ●]            │
│  ○ 마감 몇 일 전에 알릴까요?  [ 1] 일 전                         │
│  □ 이메일로도 받기                                                 │
│                                                                    │
│  공유 미열람 (24시간)                         [켜짐 ●]            │
│  ○ 24시간 후 자동 발화 (변경 불가)                                 │
│  □ 이메일로도 받기                                                 │
│                                                                    │
│  [저장]                                                            │
└──────────────────────────────────────────────────────────────────┘
```

**설정 UX 규칙**

- `share_unread`의 `days_before`는 고정(24h). 켜짐/꺼짐과 이메일만 토글 가능.
- `days_before` 입력 범위: 0~90 (이 바깥은 BE가 400 반환).
- 이메일 opt-in은 **설계사별 설정** — 디폴트 꺼짐. 켜면 `ReminderRule.email_enabled=true`.
- 설정 저장 = `PATCH /api/v1/reminder-rules/bulk/` (5개 일괄 패치).

### 4.4 상태 3종

| 상태 | 렌더 |
|---|---|
| 알림 없음 | "아직 알림이 없어요. 고객을 등록하면 만기·생일 알림이 시작됩니다." + `[첫 고객 등록]` CTA |
| 로딩 | 스켈레톤 3행 |
| 에러 | "알림을 불러오지 못했어요. [재시도]" 배너 |

---

## 5. API 계약

### 5.1 엔드포인트 목록

| Path | Method | 용도 | 권한 |
|---|---|---|---|
| `/api/v1/notifications/` | GET | 알림 목록 (페이지네이션, 필터: `is_read`) | 소유자 |
| `/api/v1/notifications/:id/read/` | PATCH | 단일 읽음 처리 | 소유자 |
| `/api/v1/notifications/read-all/` | POST | 전체 읽음 처리 | 소유자 |
| `/api/v1/notifications/:id/` | DELETE | 단일 삭제 | 소유자 |
| `/api/v1/notifications/unread-count/` | GET | 미읽음 수 (벨 배지용) | 소유자 |
| `/api/v1/reminder-rules/` | GET | 내 알림 설정 5종 조회 | 소유자 |
| `/api/v1/reminder-rules/bulk/` | PATCH | 설정 일괄 업데이트 | 소유자 |

### 5.2 응답 스키마 — `GET /notifications/`

```jsonc
{
  "count": 12,
  "next": "/api/v1/notifications/?page=2",
  "results": [
    {
      "id": 3001,
      "notif_type": "expiry_soon",
      "title": "김영희 실손 만기 D-14",
      "body": "7월 28일 만기입니다. 갱신 안내를 준비해 보세요.",
      "target_date": "2026-07-28",
      "customer_id": 312,
      "customer_name": "김영희",      // 조회 편의용 join
      "calendar_event_id": 1024,
      "is_read": false,
      "created_at": "2026-07-14T09:00:00+09:00"
    }
    // ...
  ]
}
```

### 5.3 응답 스키마 — `GET /notifications/unread-count/`

```json
{
  "unread_count": 3
}
```

> FE는 60초 staleTime으로 폴링. `unread_count >= 100`이면 UI는 `99+` 표시.

### 5.4 응답 스키마 — `GET /reminder-rules/`

```jsonc
[
  {
    "id": 201,
    "rule_type": "expiry_soon",
    "days_before": 30,
    "enabled": true,
    "email_enabled": false
  },
  {
    "id": 202,
    "rule_type": "birthday_soon",
    "days_before": 7,
    "enabled": true,
    "email_enabled": false
  }
  // ... 5종
]
```

### 5.5 `PATCH /reminder-rules/bulk/`

```jsonc
// 요청 — 변경할 rule만 부분 전송 가능
[
  { "rule_type": "expiry_soon", "days_before": 14, "enabled": true, "email_enabled": true },
  { "rule_type": "birthday_soon", "days_before": 3 }
]

// 응답 — 저장된 전체 5종 반환 (§5.4 동일 포맷)
```

**API 원칙**

- 모든 엔드포인트: `Authorization: Token <DRF_TOKEN>` 필수. `OwnedQuerySetMixin` 적용 — `filter(owner=request.user)` 강제.
- `GET /notifications/` 정렬: `created_at` 내림차순 (최신 먼저). FE 재정렬 금지(BE 권위).
- Notification의 `body`는 BE가 생성한 한국어 고정 문구 (§5.6 템플릿). FE가 생성 금지.
- `DELETE /notifications/:id/` — 소프트 삭제 아님. 실제 삭제 (감사 목적 불필요). 단 이메일 발송 이력(`sent_email=true`)은 별도 `EmailLog` 모델로 보관 (추정 — §6.2 갭).

### 5.6 알림 본문 템플릿 (BE 생성)

| notif_type | title 템플릿 | body 템플릿 |
|---|---|---|
| `expiry_soon` | `{고객명} {보험명} 만기 D-{n}` | `{만기일} 만기입니다. 갱신 안내를 준비해 보세요.` |
| `birthday_soon` | `{고객명} 생일 D-{n}` | `{생일}입니다. 축하 메시지를 보내보세요.` |
| `consult_reminder` | `{고객명} 상담 약속 D-{n}` | `{약속일 시간} 상담이 있습니다. 미리 준비하세요.` |
| `task_due` | `할 일 마감 D-{n}: {할일 제목}` | `{마감일} 마감입니다.` |
| `share_unread` | `{고객명} 공유링크 24시간 미열람` | `공유한 자료를 아직 열어보지 않았어요. 필요하면 다시 안내해 보세요.` |

> `{n}`은 발화 시점의 D-day 계산값. `D-0`이면 "오늘"로 대체. 설계사 내부면이므로 판정어 허용.

---

## 6. 권한 · 가시성 · 컴플라이언스

### 6.1 멀티테넌시 가시성 매트릭스

| 항목 | 설계사 본인 | 다른 설계사 | 관리자 |
|---|---|---|---|
| 내 알림 목록 | 읽기·삭제 가능 | 조회 불가(OwnedQuerySetMixin, 404) | 전체 조회 가능(admin bypass) |
| 내 알림 설정 | 읽기·수정 가능 | 조회 불가 | 전체 조회 가능 |
| 알림 발화 (cron) | 본인 데이터 기반으로만 발화 | 개입 없음 | 관리자 발화 없음(설계사 알림은 자동 cron만) |

**절대 금지**: 관리자가 특정 설계사에게 수동으로 알림을 발화하는 기능. 알림은 cron + 이벤트 hook 자동화만. 관리자의 수동 "공지"는 `dev/` 공지사항 모델로 별도 처리 (알림 센터와 다른 채널).

### 6.2 고객 자동발송 금지 (정직성 레드라인)

인파의 알림은 **설계사 본인을 향한 행동 트리거**다. 고객에게 자동 발송하는 경로는 물리적으로 없다.

```
[Notification.created]
  └── 알림 센터에 저장 (owner = 설계사)
  └── 이메일 발송 (opt-in) → 설계사 이메일로만
  └── (없음) 고객 mobile_phone_number / 고객 이메일 발송 경로
```

설계사가 알림을 보고 고객에게 연락하는 것은 설계사의 자발적 행동 — 클립보드 복사 / 카톡 열기까지만 인파가 지원한다 (dev/15 §3.3 원클릭 액션 참조).

### 6.3 이메일 알림 컴플라이언스

- 이메일 수신 주소 = 설계사 가입 이메일 (인증된 이메일 전용). 수신 수정 불가 — 가입 이메일로 고정.
- 이메일 본문 하단 필수 포함: "이 메일은 인파 서비스 내 알림 설정에 따라 발송되었습니다. [알림 수신 해제]" 링크.
- 수신 해제 링크 클릭 → `ReminderRule.email_enabled = false` 일괄 처리.
- AI 생성물이 포함된 이메일(추후 AI 주간 요약 등)은 "AI 초안·최종 책임 설계사" 면책 고정. 현 5종 트리거는 AI 생성물 없음 — 면책 문구 불필요(단 본문 템플릿에 AI 개입 시 즉시 추가).

### 6.4 Notification 본문 ↔ 고객 공유뷰 격리

`Notification.body`는 설계사 내부면이므로 판정어(만기·부족·갱신 안내 등) 허용. 단 고객 공유뷰(`/s/[token]`)에 Notification 데이터가 절대 노출되지 않아야 한다.

구현 강제점:
- 공유뷰 API(`GET /share/:token/`) 응답에 Notification 관련 필드 0개.
- grep 골든회귀: 공유뷰 컴포넌트에 `notif`·`notification`·`reminder` 키워드 존재 시 CI 실패.

---

## 7. 대시보드 · 캘린더 연동

### 7.1 알림 → 대시보드 액션큐 흐름

```
[cron 09:00]
  CalendarEvent(expiry, D-30) 탐색
  → Notification(expiry_soon) 생성 → 알림 센터
  → 동시에 대시보드 액션큐 사유1도 해당 이벤트 포함 (별도 소스)
  → 설계사: 알림 벨 배지 클릭 → 알림 센터 → [고객 보기 →] → /customer/:id 비교탭
           또는 대시보드 액션큐에서도 같은 고객의 만기 카드 확인
```

**중요**: 알림 센터와 액션큐는 같은 사안을 다른 뷰로 제공한다. "알림을 읽었다 = 액션큐에서 사라진다"가 아니다. 둘은 독립적이다. 알림 읽음 처리(`is_read=true`)는 알림 센터에서의 배지 수만 줄인다.

### 7.2 알림 → 캘린더 연동

`calendar_event_id`가 있는 알림은 [캘린더에서 보기] 버튼을 추가로 제공한다. 클릭 시 `/home` 캘린더 해당 날짜로 포커스 이동(`?cal_date=YYYY-MM-DD` 쿼리파라미터 → FE 캘린더 날짜 세팅).

---

## 8. 기획 갭 / 미결

### ★ blocking — Sprint0 게이트

- **G-1 `share_unread` 트리거용 `share_sent_at` 컬럼 부재**: 현재 `Customer` 모델에 공유링크 생성 시각(`share_token` 발급 시각)이 없다. `user_view_at`(열람 시각)은 있지만, "공유 발송 후 24h"를 측정하려면 **마지막 공유 발송 시각(`share_sent_at`)** 컬럼이 필요하다. `Customer` 모델에 `share_sent_at: DateTimeField(null)` 추가 필요 — `dev/02` 데이터모델 delta로 올린다.
- **G-2 이메일 발송 인프라 미결**: 이메일 opt-in 설정이 있지만 발송 인프라(AWS SES / SendGrid 등)가 미선정. 베타 단계에서 이메일 opt-in을 UI에 노출하되 **실제 발송은 인프라 결정 후**. 인프라 없는 상태에서 `email_enabled=true`로 저장해도 발송 안 함 — BE `sent_email` 플래그 미전환.
- **G-3 days_before 임계값 동결 미확정**: `expiry_soon` 30일은 dev/15 G-3(액션큐 임계값)과 동일 가설. PM이 G-3를 확정하면 동시에 ReminderRule 기본값도 갱신 필요.

### non-block — 출시 전 확정

- **N-1 이메일 발송 이력 `EmailLog` 모델**: `sent_email=true` 플래그만으로는 감사 부족. `EmailLog(notification FK, sent_at, to_email, status)` 별도 모델 고려 — 정식 출시 전.
- **N-2 알림 보관 기간**: Notification 레코드를 언제까지 보관할지 미결. (추정) 90일 후 자동 삭제 cron. 이메일 opt-in 감사 목적이라면 `EmailLog`는 별도 보관.
- **N-3 실시간 알림 WebSocket**: 현재는 60초 폴링. 실시간(읽음 즉시 벨 배지 업데이트)은 (추정) P2. Django Channels 또는 SSE 도입 시점 미결.
- **N-4 알림 유형 확장**: 현재 5종 고정 enum. 멤버십 만료 임박·KPI 달성 등 신규 유형 추가 시 마이그레이션 필요 — `notif_type` choices 확장 패턴 정의 필요.
- **N-5 이메일 수신 해제 링크 토큰 발급**: 이메일 본문 [수신 해제] 링크는 인증 없이 동작해야 함(설계사가 이메일 클라이언트에서 바로 클릭). 1회용 해제 토큰 발급 로직 미설계.
- **N-6 알림 우선순위 정렬 기준**: 현재 `created_at` 내림차순. 미읽음 먼저 + 날짜 가중 정렬 옵션은 (추정) 베타 피드백 후.

---

## 9. 수용 기준 (Definition of Done)

- [ ] `Notification` / `ReminderRule` 마이그레이션 적용 + SELECT 확인
- [ ] OwnedQuerySetMixin 적용 확인 — "설계사 A가 B의 알림 조회 = 404" 회귀테스트
- [ ] Cron 매일 09:00 발화 → 4종(expiry/birthday/consult/task) Notification 생성 정상
- [ ] Cron 4h 간격 `share_unread` 발화 → 24h 경과 Customer에 Notification 생성 정상
- [ ] 중복 방지: 동일 `(owner, notif_type, target_date, customer_id)` 2회 발화 안 됨
- [ ] `GET /notifications/unread-count/` → 벨 배지 숫자 일치
- [ ] 알림 클릭 → `PATCH /notifications/:id/read/` 자동 호출 → `is_read=true` 전환
- [ ] [전체 읽음 처리] → `POST /notifications/read-all/` → `unread_count=0`
- [ ] `PATCH /reminder-rules/bulk/` → 설정 저장 → 다음 cron에 새 설정 반영
- [ ] 이메일 opt-in `email_enabled=true` 저장 — 단 인프라 미결 시 `sent_email` 미전환 (UI 저장만 가능, 실제 발송 보류)
- [ ] 공유뷰 grep 골든회귀: `/s/[token]` 컴포넌트에 `notification` 키워드 부재 확인
- [ ] 고객 자동발송 경로 부재 확인: `customer.mobile_phone_number` 또는 고객 이메일로의 발송 코드 0줄
- [ ] `expiry_soon` 알림 색 = `--cal-expiry` (보라). red 사용 시 CI 실패
- [ ] 알림 없음 empty state: "고객을 등록하면 만기·생일 알림이 시작됩니다" + `[첫 고객 등록]` CTA
