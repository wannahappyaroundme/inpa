# 인파(Inpa) — 대시보드 · 캘린더 · 업무기록

> dev/15 — 로그인 첫 화면(대시보드)의 데이터 모델·화면 스펙. 정본 dev/06~09(MVP 슬라이스·API 계약·화면 스펙·컴플라이언스)와 dev/10(planner_baseline)·dev/12(고객 CRUD) 위에 얹는 **설계사 본진의 "매일 들어올 이유"** 레이어. 본 문서는 net-new 영역(캘린더·업무기록 모델)을 계약·구조·흐름으로 정의한다. 구현 코드가 아닌 모델/화면/계약을 다룬다.
> **v2 패치 2026-06-19: 이메일/비밀번호 인증 전환, 가시성 매트릭스 명시, KPI 5종 확정, 캘린더 신호등 4색 확정.**

---

## [v2 패치 요약]

| 항목 | v1 | v2 (이번 패치) |
|---|---|---|
| 인증 방식 | 미명시(카카오 OAuth 가정) | **이메일/비밀번호 전용** |
| 가시성 분류 | 미명시 | **소유자 전용** (`CalendarEvent`, `Task`, `WorkNote`, `ContactLog` 전부 `owner FK + OwnedQuerySetMixin`) |
| KPI 카드 | 3~4개 언급 | **5종 확정** (내 고객·이번 달 만기·오늘 할 일·이번 달 신규·미열람 공유) |
| 캘린더 색 | 미확정 | **4색 신호등 확정** (만기 red·생일 amber·상담 green·할일 blue, 오늘 하이라이트) |

---

## 0. 이 문서가 푸는 문제

설계사는 하루에 두 모드를 오간다.

- **(A) 기록 모드** — 자투리·이동 중, 한 손. 메모/할일/접촉이력을 마찰 0으로 던져넣는다.
- **(B) 영업 모드** — 고객 앞·통화 직전. 무기(히트맵·비교서·공유링크)를 꺼낸다.

대시보드는 이 둘의 **착지점이자 발사대**다. 아침에 켜면 "오늘 누구에게 무엇을"이 0클릭으로 보이고(액션큐), 그 일감의 출처는 **캘린더 이벤트(만기/생일/상담/할일)**와 **업무기록(메모/할일/접촉이력)**이다. 즉 이 문서는 대시보드를 떠받치는 **두 신규 데이터 모델**과 그것을 그리는 **화면 스펙**을 못박는다.

핵심 원칙 3줄:
1. **홈은 매일 들어올 이유다.** 여기서 이탈하면 제품이 죽는다. KPI 한 줄 + 캘린더 + 액션큐.
2. **기록(A)은 마찰 0, 영업(B)은 발송으로 수렴.** 업무기록은 손입력 노동을 줄이는 쪽으로, 캘린더는 일감을 만드는 쪽으로 설계한다.
3. **컴플라이언스가 모든 표면의 게이트.** 대시보드는 설계사 내부면이라 판정어 허용 — 단 고객 공유로 새는 경로엔 자동 필터. KPI 카드는 "사실 카운트"만, 충족/위험 판정 금지.

---

## 1. 범위 (in / out)

| 구분 | 포함 | 비고 |
|---|---|---|
| **In** | 대시보드 홈(KPI 한 줄 + 액션큐 + 캘린더), 캘린더 이벤트 모델(`CalendarEvent`), 업무기록 모델(`WorkNote`/`Task`/`ContactLog`), 데스크톱 반응형 | net-new BE 모델 2~3종 |
| **In(계약만)** | 액션큐 사유 판정 입력(만기/동의/생일/미열람/인바운드)의 데이터 출처 매핑 | 판정 로직 자체는 §6 |
| **Out** | 히트맵·비교안내서·공유뷰 화면 스펙 | dev/08·dev/10 정본 참조 |
| **Out** | planner_baseline 모델·기준설정 UI | dev/10 |
| **Out** | 북극성 6종 이벤트 스키마 동결 | dev/07(B1), 본 문서는 **소비자**로만 참조 |
| **Out(추정)** | 캘린더 외부 연동(구글/네이버 캘린더 양방향 sync) | (추정) P2 이후, 본 MVP는 인파 내부 이벤트만 |

> ⚠️ **스코프 충돌 미해결(상속)**: dev/06 첫 슬라이스는 "홈 액션큐 풀버전 2차 제외 — 이번엔 고객목록+상세만"이라 못박았다. 그런데 03-features·본 문서는 홈을 리텐션 핵심으로 본다. **본 문서의 입장**: 첫 데모 슬라이스 ≠ T0 6주 MVP. 첫 슬라이스엔 **홈을 정적 KPI + 캘린더 read-only + 액션큐 1종(만기)만** 최소 포함하고, 캘린더 쓰기/업무기록 풀스택은 T0 6주 안에 넣는다. (PM 결정 필요 — §8 G-1)

---

## 2. 가시성 매트릭스 — 대시보드·캘린더·업무기록 엔티티 (v2 명시)

이 문서가 다루는 모든 엔티티는 **소유자 전용**이다. 멀티테넌시 가시성 매트릭스(`dev/12 §2` 참조)의 "소유자 전용" 분류를 그대로 상속한다.

| 엔티티 | 가시성 | owner FK | 비고 |
|---|---|---|---|
| `CalendarEvent` | **소유자 전용** | `owner(User)` | `OwnedQuerySetMixin` 적용 |
| `Task` | **소유자 전용** | `owner(User)` | `OwnedQuerySetMixin` 적용 |
| `WorkNote` | **소유자 전용** | `owner(User)` | 공유뷰 물리 부재 |
| `ContactLog` | **소유자 전용** | `owner(User)` | 공유뷰 물리 부재 |
| KPI 집계(`/home/summary/`) | **소유자 전용** | 인증 필수 | `request.user` 스코프로만 집계 |

**레드라인**: `WorkNote.body`·`ContactLog.summary`는 설계사 내부면 — 판정어 허용. 단 **공유뷰(`/s/[token]`) 응답 prop에 물리 부재**. grep 골든회귀로 검증.

---

## 3. 데이터 모델 (net-new)

대시보드를 떠받치는 신규 모델은 4종이다. 모두 `inpa_be`에 신설(foliio엔 없음). FK 소유자는 설계사(`User`), 고객 연결은 nullable(고객 없는 순수 메모/할일 허용).

### 3.1 모델 관계도 (ASCII)

```
User(설계사)
  │
  ├─< CalendarEvent ────┐ (만기/생일/상담/할일 — 캘린더에 점으로 찍히는 모든 것)
  │      │ customer_id(nullable)
  │      │ source_type: auto(만기/생일 파생) | manual(상담/할일 직접)
  │      │
  ├─< Task ─────────────┘ (할일 — CalendarEvent와 1:1 옵션, 체크박스 본체)
  │      │ done / snoozed_until
  │
  ├─< WorkNote (메모 — 고객별 자유 텍스트 타임라인)
  │      │ customer_id(nullable)
  │
  └─< ContactLog (접촉이력 — 통화/문자/카톡/미팅 발생 기록)
         │ customer_id(required)
         │ channel / direction / outcome
```

설계 결정: **`CalendarEvent`가 허브**다. 만기·생일은 BE가 파생 생성(`source_type=auto`)하고, 상담·할일은 설계사가 직접 만든다(`source_type=manual`). `Task`는 "체크 가능한 할일"의 본체이고 `CalendarEvent`에 그림자로 비친다. 이렇게 분리하는 이유는 §2.6.

### 3.2 `CalendarEvent` — 캘린더 이벤트 허브

```jsonc
{
  "id": 1024,
  "owner_id": 7,                  // FK User (설계사)
  "customer_id": 312,             // FK Customer, nullable (순수 일정 허용)
  "event_type": "expiry",         // expiry | birthday | consult | task  (4종)
  "source_type": "auto",          // auto(파생) | manual(직접입력)
  "title": "김영희 실손 만기",      // 표시 제목
  "date": "2026-07-15",           // 발생일 (KST, date-only)
  "time": null,                   // "14:30" or null (종일 이벤트)
  "all_day": true,
  "linked_task_id": null,         // event_type=task일 때 Task 1:1 (없으면 null)
  "origin_ref": {                 // auto 파생의 출처 추적 (idempotent 재생성 키)
    "kind": "customer_insurance", // customer_insurance | customer_birthday | null
    "ref_id": 8801                // 만기→CustomerInsurance.id, 생일→Customer.id
  },
  "memo": "",                     // 짧은 비고 (설계사 내부, 고객 비노출)
  "created_at": "2026-06-19T09:02:00+09:00",
  "updated_at": "2026-06-19T09:02:00+09:00"
}
```

**`event_type` 4종 정의 — ★ 캘린더 신호등 4색 확정 (v2)**

| type | 캘린더 색 도트 (신호등 팔레트) | 생성 | 소유 출처 | 액션큐 연동 |
|---|---|---|---|---|
| `expiry` 만기 | 🔴 `--cal-expiry-red` **(빨강)** | auto | `CustomerInsurance` 만기일 | 사유1 (D-30↓) |
| `birthday` 생일 | 🟡 `--cal-birthday-amber` **(노랑/amber)** | auto | `Customer` 생년월일 | 사유3 (D-7) |
| `consult` 상담 | 🟢 `--cal-consult-green` **(초록)** | manual | 설계사 직접 | 당일 아젠다 |
| `task` 할일 | 🔵 `--cal-task-blue` **(파랑)** | manual | `Task` 1:1 | 사유 외(당일 아젠다) |

**오늘 하이라이트**: 오늘 날짜 셀은 배경 fill + 도트 색 강화. `date === today → .cal-today` 클래스.

> ⚠️ **v2 색 변경 이유 (v1과 차이)**: v1은 만기를 `--cal-expiry`(보라/남보라)로, dev/08 레드라인 *"red는 §97 비교안내 전용"*을 근거로 설계했다. **v2에서는 캘린더 신호등 4색(만기 red·생일 amber·상담 green·할일 blue) 시스템으로 전환**한다. 이유: 신호등 직관성이 사용자 인지 부담을 줄이고, **캘린더 내 red는 §97 비교안내서와 교차되지 않는** 독립 팔레트이므로 컴플라이언스 위반이 아니다. `--danger`(#E03131)와 **별도 토큰** `--cal-expiry-red`를 정의해 히트맵/비교안내서와 토큰 레벨에서 분리한다. 액션큐 만기 도트도 `--danger`가 아니라 `--cal-expiry-red`로 통일 (이원화 제거, 단순화). 이 결정을 `design/tokens/inpa-tokens.css`에 반드시 주석으로 기록할 것.
>
> **레드라인 재확인**: 히트맵 셀의 `short`(부족) 색은 여전히 **amber만** (`--cov-short`). `--cal-expiry-red`는 캘린더 이벤트 도트와 액션큐 만기 배지에만 사용. 히트맵·공유뷰에는 0건.

### 3.3 `Task` — 할일 본체

```jsonc
{
  "id": 5501,
  "owner_id": 7,
  "customer_id": 312,           // nullable
  "title": "김영희 갱신 안내 전화",
  "due_date": "2026-07-15",     // CalendarEvent.date와 동기 (task 이벤트 생성 시)
  "done": false,
  "done_at": null,
  "snoozed_until": null,        // 스누즈 시 미래일 → 그날까지 액션큐/아젠다에서 숨김
  "priority": 2,                // 1=높음 2=보통 3=낮음 (정렬 보조)
  "created_at": "...",
  "updated_at": "..."
}
```

- `Task` 생성 시 옵션으로 `CalendarEvent(event_type=task, linked_task_id=self)` 동반 생성 → 캘린더에 점으로 비침.
- `done=true` → 캘린더 도트 회색 처리(취소선), 액션큐에서 제거.
- `snoozed_until` → 그날 0시까지 액션큐·아젠다 숨김(완료 아님, 미루기). **(추정)** 스누즈 기본 옵션: 내일/3일후/다음주.

### 3.4 `WorkNote` — 메모(고객별 자유 타임라인)

```jsonc
{
  "id": 9001,
  "owner_id": 7,
  "customer_id": 312,           // nullable (고객 없는 순수 메모 허용)
  "body": "통화함. 자녀 보험 관심. 7월 만기 시 비교안내 검토 요청.",
  "pinned": false,              // 고객 상세 타임라인 상단 고정
  "created_at": "2026-06-19T15:20:00+09:00",
  "updated_at": "2026-06-19T15:20:00+09:00"
}
```

- 고객 상세 **타임라인 탭**의 본문. 시간 역순 정렬, `pinned` 우선.
- **컴플 가드**: `WorkNote.body`는 설계사 내부면 — 판정어 허용. 단 **고객 공유뷰로 절대 새지 않음**(공유뷰 prop에 물리 부재). grep 골든회귀로 검증.

### 3.5 `ContactLog` — 접촉이력

```jsonc
{
  "id": 7701,
  "owner_id": 7,
  "customer_id": 312,           // required (접촉은 항상 고객 대상)
  "channel": "call",            // call | sms | kakao | meet | email
  "direction": "outbound",      // outbound | inbound
  "outcome": "connected",       // connected | no_answer | scheduled | declined  (추정 enum)
  "summary": "갱신 안내. 다음주 미팅 약속.",
  "occurred_at": "2026-06-19T14:05:00+09:00",
  "created_at": "...",
  "next_action_task_id": 5502   // 이 접촉에서 파생된 Task (nullable) — "다음 약속" 자동 할일화
}
```

- **기록 모드(A)의 핵심**: 통화 직후 한 손으로 `channel + outcome + summary` 3탭 입력.
- `next_action_task_id` → 접촉 끝에 "다음 약속" 잡으면 `Task` + `CalendarEvent(consult)` 자동 생성. **이게 액션큐로 다시 흘러들어 루프를 닫는다**(기록 → 일감 → 발송).
- `direction=inbound` → 인바운드 접촉, 북극성 귀속(referral_attributed)과는 별개의 수기 기록.

### 3.6 설계 결정 Q&A

**Q. 왜 `CalendarEvent`와 `Task`를 분리하나? (할일을 캘린더 안에 넣으면 안 되나)**
A. `Task`는 **체크/스누즈/완료 상태 머신**을 가진다. `CalendarEvent`는 "그날 무엇이 있다"는 **표시 단위**다. 만기·생일은 체크할 대상이 아니라 인지할 사실이고, 할일만 체크가 필요하다. 분리하면 (a) 만기/생일을 캘린더에 가볍게 찍고 (b) 할일만 상태를 무겁게 관리하며 (c) 둘 다 같은 캘린더 그리드에 점으로 통합된다. 1:1 옵션 링크(`linked_task_id`)로 연결.

**Q. 왜 만기/생일을 `auto`로 파생 저장하나? (조회 시 계산하면 안 되나)**
A. **액션큐 정렬과 캘린더 월 조회 성능** 때문. 만기 D-day는 `CustomerInsurance` 만기일에서 매번 계산 가능하지만, 캘린더 월 그리드가 수백 건을 매 조회 계산하면 N+1(foliio 트랩 상속). `auto` 이벤트로 미리 materialise하고 **idempotent 재생성**(`origin_ref` 키로 upsert)으로 만기일 수정 시 동기화. (추정) 재생성 트리거: 보험 생성/수정 signal + 일 1회 cron 보정.

**Q. 접촉이력과 메모를 왜 나누나?**
A. `ContactLog`는 **구조화 이벤트**(채널·방향·결과 enum → 통계/액션큐 입력), `WorkNote`는 **비구조 자유 텍스트**(맥락 보존). 접촉은 "언제 무슨 채널로 어떤 결과"가 KPI가 되지만 메모는 검색·고정용. 섞으면 통계가 더러워진다(foliio community 필터 교훈: 구조화/비구조 분리).

---

## 3. 화면 스펙 — 대시보드 `/home` (로그인 첫 화면)

### 3.1 레이아웃 (모바일 퍼스트 → 데스크톱 반응형)

```
┌─ 모바일 (단일 컬럼) ──────────────┐      ┌─ 데스크톱 (사이드네비 + 2컬럼, max-w 1200, --header-h 80) ─┐
│ [헤더: 설계사명      크레딧바 ∞] │      │ ┌──────┐ ┌─────────────────┬──────────────────────┐ │
│ ┌── KPI 한 줄 (가로스크롤) ──┐  │      │ │ 사이드 │ │ KPI 한 줄 (4~5 카드 펼침)               │ │
│ │ 고객 만기 할일 신규 미열람│  │      │ │ 네비  │ ├─────────────────┼──────────────────────┤ │
│ └────────────────────────┘  │      │ │ 홈    │ │ 액션큐 (좌)       │ 캘린더 월그리드 (우)   │ │
│ ┌── 액션큐 (우선순위 5종) ──┐  │      │ │ 고객  │ │  🔴 만기 D-30      │  [월 7-col grid]      │ │
│ │ 🔴 김영희 만기 D-12 [갈아타기]│      │ │ 발굴⊕ │ │  🟠 동의 미수신     │  선택일 → 우하 아젠다  │ │
│ │ 🟠 박철수 동의대기 [링크복사] │      │ │ 분석  │ │  🎂 생일 D-3       ├──────────────────────┤ │
│ │ 🎂 ...                    │      │ │ 내정보 │ │  📨 미열람 24h     │ <DayAgenda> 당일 일정  │ │
│ └────────────────────────┘  │      │ └──────┘ │  🔗 인바운드       │  + 업무(체크박스)      │ │
│ ┌── 캘린더 (주간 스트립) ──┐    │      │          └─────────────────┴──────────────────────┘ │
│ │ 월 화 수 목 금 토 일      │    │      │  ※ 데스크톱=밀도화면 멀티컬럼 허용                       │
│ │  •     •  •      ••       │    │      └────────────────────────────────────────────────────┘
│ │ <DayAgenda 당일 일정/업무>│    │
│ └────────────────────────┘    │
│ [하단탭5: 홈 고객 ⊕발굴 분석 나]│
└──────────────────────────────┘
```

- **렌더 전략**: 액션큐 정렬·D-day는 **BE 권위 → RSC SSR fetch → dehydrate → HydrationBoundary**. 인터랙션(스누즈/완료/캘린더 월 전환)만 client.
- **데스크톱 멀티컬럼 정책**: 대시보드·캘린더는 **밀도화면 → 2컬럼 허용**. 공유뷰만 단일컬럼 강제(480~720). 화면별 컬럼 정책은 §5.4 표로 명문.

### 3.2 KPI 카드 한 줄 — ★ 5종 확정 (v2)

| # | 카드 라벨 | 값 출처 (BE 집계, `request.user` 스코프) | 표기 예시 |
|---|---|---|---|
| 1 | **내 고객** | `Customer.objects.filter(owner=request.user, deleted_at__isnull=True).count()` | `1,204` |
| 2 | **이번 달 만기** | `CalendarEvent(event_type='expiry', date__month=this_month, owner=user).count()` | `12` |
| 3 | **오늘 할 일** | `Task(due_date=today, done=False, snoozed_until__isnull_or_past=True, owner=user).count()` | `5` |
| 4 | **이번 달 신규** | `Customer(created_at__month=this_month, owner=user).count()` | `8` |
| 5 | **미열람 공유** | 공유링크 발급 후 24h 이상 `NorthStarEvent(share_view)` 미존재 count (북극성 소비) | `3` |

**API 응답 (`GET /api/v1/home/summary/`):**
```json
{
  "total_customers": 1204,
  "expiry_this_month": 12,
  "tasks_today": 5,
  "new_customers_this_month": 8,
  "unread_shares": 3,
  "credit": { "remaining": null, "is_unlimited": true }
}
```

**계약(절대)**:
- 모든 숫자 `Intl.NumberFormat('ko-KR')` + `tabular-nums`. 강조색 = `--accent-blue`, 라벨 = `--ink-2`.
- **카드에 충족/위험 판정 금지** — 사실 카운트만. "부족 3" 같은 판정어 컴파일 차단(블랙리스트).
- `unread_shares`는 `NorthStarEvent(share_view)` Day1 스키마 동결 이후에만 정확. 북극성 스키마 동결 전까지는 `0`으로 stub 처리(가짜 0 표시, 배지 숨김).
- 크레딧바: `credit.remaining=null`→`∞`(0은 무제한 센티넬 — foliio §8 트랩 상속, `remaining==0` 아님).

### 3.3 액션큐 (홈의 심장)

사유 5종 **우선순위 정렬 고정**(BE 권위, FE 재정렬 금지):

| 우선 | 사유 | 도트 | 입력 데이터 | 원클릭 액션 |
|---|---|---|---|---|
| 1 | 만기 D-30↓ | 🔴 `--danger` | `CalendarEvent(expiry)` D-day | **갈아타기 분석** → `/customer/:id` 비교 탭 |
| 2 | 동의 미수신 | 🟠 `--cov-short` | `consent_overseas_at is None` | **동의링크 복사**(클립보드) |
| 3 | 생일 D-7 | 🎂 `--cal-birthday` | `CalendarEvent(birthday)` D-day | **축하 메시지 복사** |
| 4 | 공유 미열람 24h | 📨 `--ink-3` | `share_view` 부재(북극성) | **재발송**(클립보드) |
| 5 | 인바운드 열람/귀속 | 🔗 `--brand` | `referral_attributed`(북극성) | **상담 전환** → 상담 일정 생성 |

**계약(절대)**:
- AC: 사유별 **우측 버튼 1개 = 원클릭**(2클릭 금지). 정렬은 BE가 내린 순서 고정.
- 액션 카피는 전부 **"복사 / 분석 열기 / 전환"까지** — **"자동발송·즉시전송" 물리 부재**(클립보드만, 정직성 레드라인).
- 스와이프 완료/스누즈는 `Task.snoozed_until`·보조 계측으로만 적재(**북극성 아님**).

### 3.4 상태 5종

| 상태 | 표현 |
|---|---|
| loading | 스켈레톤 KPI 3장 + 큐 3행 |
| empty(고객0) | 콜드스타트 — "첫 고객을 등록해 보세요" + `[증권 올리기]` CTA |
| error | 큐 일부 실패 → 부분 표시 + 상단 `[재시도]` 배너 |
| 한도(베타) | 크레딧바 `∞` 배너(대시보드 자체는 무차감) |
| 정상 | 위 전체 |

---

## 4. 화면 스펙 — 캘린더 (대시보드 내장)

### 4.1 컴포넌트·반응형

- `<DataCalendar>` 7-col grid. 일자별 **이벤트 도트**(`event_type` 색 범례), 선택일=채운 원, 미래일 dimmed, 빈 달=점선 일러스트.
- **모바일**: 주간 가로 스트립(7일 도트) 우선 → 탭 시 세로 아젠다. **데스크톱**: 풀 월그리드 + 우측 `<DayAgenda>` 패널(토스/럽맘형).
- 월 전환: 좌우 화살표(`useState`), `queryKey ['calendar', year, month]`.

### 4.2 `<DayAgenda>` — 선택일 일정/업무

```
2026-07-15 (화)
─────────────────
🟣 14:00  김영희 실손 만기        [갈아타기]
💬 15:30  박철수 상담 (consult)
✅ ─       김영희 갱신 안내 전화   [ ] ← Task 체크박스
🎂 ─       이순자 생일
```

- 일정(`consult`)·만기(`expiry`)·생일(`birthday`)은 읽기, **할일(`task`)만 체크박스**(`Task.done` 토글 → 캘린더 도트 회색).
- FAB로 빠른 추가(상담/할일). 추가 시 `CalendarEvent` + (할일이면) `Task` 동반 생성.

### 4.3 페칭 계약

```
GET /api/v1/calendar/?year=2026&month=7
→ { events: [CalendarEvent...], by_day: { "2026-07-15": ["expiry","consult","task"] } }
```

- `by_day`는 도트 렌더용 사전계산(FE 그룹핑 부담 제거). `staleTime` 짧게(만기/일정 변동 잦음).
- **만기/생일 `auto` 이벤트는 조회 시 실시간 계산 아님** — §2.6대로 materialise된 행을 읽음(N+1 가드).

---

## 5. 화면 스펙 — 업무기록 (고객 상세 타임라인 + 기록 모드)

### 5.1 진입 경로

업무기록은 **두 곳**에서 쓴다.
1. **고객 상세 "타임라인" 탭** — 해당 고객의 `WorkNote` + `ContactLog` + 파생 `Task`를 시간 역순 통합 피드.
2. **기록 모드 빠른 입력**(한 손) — 통화 직후 `[+접촉]` 또는 `[+메모]` 바텀시트(`vaul`).

### 5.2 고객 상세 타임라인 탭 (통합 피드)

```
김영희 · 여 · 1985  [분석][히트맵][공유이력][타임라인●]
─────────────────────────────────────────────
📌 [고정 메모] 자녀 보험 관심                    (WorkNote.pinned)
─────────────────────────────────────────────
06-19 14:05  📞 통화(out) · 연결 · "갱신 안내, 다음주 미팅"   (ContactLog)
             └ 파생 할일: 7/15 미팅 [ ]                    (next_action_task → Task)
06-15 10:20  📝 메모: 7월 만기 시 비교안내 검토 요청         (WorkNote)
06-10 09:00  📨 공유링크 발송 → 열람(06-10 21:30) → 귀속    (북극성, 공유이력 연동)
```

- **통합 피드 정렬**: `occurred_at`/`created_at` 역순. `pinned` 메모 최상단 고정.
- 북극성 이벤트(발송/열람/귀속)도 같은 타임라인에 read-only로 비침 → **공유이력 탭과 데이터 공유**(귀속 가시화).
- 색: 채널 아이콘 = 중립색(`--ink-*`), 데이터셀 블루(`--cov-*`)·CTA 브랜드와 교차 금지.

### 5.3 기록 모드 빠른 입력 (마찰 0)

| 입력 | 필드(최소) | 탭 수 목표 |
|---|---|---|
| `[+접촉]` | channel(아이콘 5택) → outcome(4택) → summary(선택) | 3탭 |
| `[+메모]` | body(텍스트) → 저장 | 2탭 |
| `[+할일]` | title → due_date(오늘/내일/날짜) | 3탭 |

- **AC**: 접촉 입력 후 "다음 약속 잡기" 토글 → `next_action_task` 자동 생성(루프 닫기).
- 자동저장 race-safe(`switchMap`, foliio 계승). 미저장 변경 경고.

### 5.4 화면별 컬럼·컴플 정책 (명문화)

| 화면 | 컬럼 | 판정어 | red 허용 |
|---|---|---|---|
| 대시보드/홈 | 모바일1·데스크톱2 | 허용(내부면) | 액션큐 만기 도트만 |
| 캘린더 | 모바일1·데스크톱2 | 허용 | ✗(만기=보라) |
| 업무기록(타임라인) | 단일 피드 | 허용(내부면) | ✗ |
| 공유뷰 | **단일 강제(480~720)** | **금지(블랙리스트)** | ✗ |

> 핵심: 대시보드·캘린더·업무기록은 **설계사 내부면 → 판정어 허용**. 단 `WorkNote`/`ContactLog` 본문이 **고객 공유뷰로 새는 경로는 물리 차단**(공유 prop에 부재 + grep 골든회귀).

---

## 6. API 계약 (신규)

> 북극성 6종(B1)·planner_baseline(dev/10)·detect 412 게이트(dev/09)는 정본 참조 — 본 표는 **net-new만**.

| Path | Method | Purpose | 게이트 |
|---|---|---|---|
| `/api/v1/home/summary/` | GET | KPI 5종 카운트 + 크레딧 | 인증 |
| `/api/v1/home/actions/` | GET | 액션큐 (BE 우선순위 정렬, 사유 5종) | 인증 |
| `/api/v1/calendar/` | GET | `?year&month` → events + by_day | 인증 |
| `/api/v1/calendar/events/` | POST/PATCH/DELETE | consult/task 직접 CRUD (auto는 읽기전용) | 소유자 |
| `/api/v1/tasks/` | GET/POST/PATCH | 할일 CRUD + `done`/`snoozed_until` 토글 | 소유자 |
| `/api/v1/customer/:id/notes/` | GET/POST/PATCH/DELETE | WorkNote (soft delete) | 소유자 |
| `/api/v1/customer/:id/contacts/` | GET/POST | ContactLog + `next_action` 동반 Task | 소유자 |
| `/api/v1/customer/:id/timeline/` | GET | WorkNote+ContactLog+Task+북극성 통합 피드 | 소유자/공유token X |

**계약 원칙**:
- `auto` 이벤트(만기/생일)는 **읽기 전용** — 직접 CRUD 거부(파생 출처 수정으로만 변경).
- `timeline/`은 **share_token 접근 불가**(설계사 내부면, 고객 공유뷰 물리 분리).
- 정렬은 BE 권위(액션큐·타임라인), FE 재정렬 금지.
- `0=∞` 센티넬, `remaining=null` 체크(`remaining==0` 아님).

---

## 7. 흐름 — 기록이 일감이 되어 발송으로 닫히는 루프

```
[기록 모드 A]                    [대시보드 홈]                  [영업 모드 B]
통화 → ContactLog(out,connected) → 액션큐: 만기 D-12 🔴 ───────→ /customer/:id 비교탭
  └ next_action → Task(7/15)         사유1 정렬 상단              → 히트맵(영업 무기)
        │                              │                          → [공유링크 복사]
        ▼                              ▼                                │
  CalendarEvent(consult,7/15)    캘린더 7/15 도트 💬              카톡 발송
        │                              │                                │
        └──────────────────────────────┴────── share_view(북극성) ◀────┘
                                       │
                                미열람 24h → 액션큐 사유4 📨 재발송 → (루프 반복)
```

**핵심**: 기록(A)이 `Task`/`CalendarEvent`로 materialise → 홈 액션큐가 우선순위로 끌어올림 → 영업(B)이 발송으로 수렴 → 북극성(share_view)이 계측 → 미열람이 다시 액션큐로. **이 루프가 "매일 들어올 이유"의 메커니즘**이다.

---

## 8. 기획 갭 / 미해결 (blocking ★ / non-block)

### ★ blocking — Sprint0 게이트

- **G-1 스코프 충돌(상속, 최우선)**: dev/06 첫 슬라이스 "홈 2차 제외" vs 03-features·본 문서 "홈=리텐션 핵심". **첫 데모 슬라이스 ≠ T0 6주 MVP** 경계를 PM이 명시 정리해야 6역할 혼선 차단. 본 문서 권고: 첫 슬라이스 = 정적 KPI + 캘린더 read-only + **액션큐 만기 1종**, 캘린더 쓰기·업무기록 풀스택은 T0 6주.
- **G-2 캘린더 색 팔레트 동결**: 만기 도트 = 스캐폴드 mock의 빨강(`bg-cnone`)은 **red 전용 레드라인 위반**. `--cal-expiry`(보라 계열) 등 **데이터색·신호등과 분리된 중립 카테고리 팔레트** 신규 정의 필요(PM/디자인). 단 **액션큐 만기 도트는 `--danger` 🔴 예외 허용** — 이 이원화를 토큰 SSOT 주석에 명문화.
- **G-3 액션큐 사유 임계값 미확정**: 만기 D-30 / 생일 D-7 / 미열람 24h는 전부 **(추정)**. BE 우선순위 정렬 로직 동결 전 PM 확정 필요.
- **G-4 액션큐 데이터 출처 종속**: 만기 D-day는 `CustomerInsurance` 만기일 **OCR 추출 신뢰도**에 종속(누락 시 액션큐 사유1 비는다). 미열람 24h는 **북극성 share_view 스키마(B1) Day1 동결 선행** — 계측 없으면 사유4 도출 불가.

### non-block — 출시 전 확정

- **N-1 `auto` 이벤트 재생성 트리거**: 보험 생성/수정 signal + cron 보정 주기·idempotent upsert 키(`origin_ref`) 운영 규칙 **(추정)** 미동결.
- **N-2 `Task.snoozed_until` 스누즈 기본 옵션**(내일/3일/다음주) UX **(추정)**, 영속 위치(서버 확정 — localStorage 아님).
- **N-3 `ContactLog.outcome` enum 확정**: `connected/no_answer/scheduled/declined`는 **(추정)** — 설계사 실무 용어 검증 필요.
- **N-4 외부 캘린더 연동**(구글/네이버 양방향 sync): **(추정)** P2 이후. MVP는 인파 내부 이벤트만.
- **N-5 캘린더 데이터모델 정본(dev/10 연동)**: 본 §2가 초안. `CalendarEvent`/`Task` 모델·마이그레이션 owner·일정 미확정.
- **N-6 통합 타임라인 ↔ 공유이력 탭 데이터 공유 매핑**: 북극성 6종 이벤트 → 타임라인 UI 행 매핑 상세 미정(공유이력 탭과 동일 소스 보장 규칙).
- **N-7 디자인 픽셀 실측**: 캘린더 셀(24/32px)·탭영역(44px)·`<DayAgenda>` 행 높이 Figma 미산출 → 컴포넌트 props 확정 불가(dev/08과 동일 갭).

> **PM 다음 액션**: ① G-1 경계 잠금회의(첫 슬라이스 vs T0) ② G-2 캘린더 팔레트 디자인 동결(보라+액션큐 red 예외 명문) ③ G-3 사유 임계값 확정 ④ §2 모델을 dev/10 정본으로 승격(owner·마이그레이션 일정 배정) ⑤ B1(북극성 스키마) 동결 선행 확인 — 액션큐 사유4 종속.