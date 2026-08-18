# Release 3 예약 상태기계·Google Calendar 동기화 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 미팅 수락·거절·취소가 한 번만 유효한 명시적 상태 전이를 따르게 하고, Google Calendar 생성·삭제가 실패하거나 순서가 뒤집혀도 최종 DB 상태와 수렴하도록 만든다.

**Architecture:** 예약 상태 변경은 `booking/services.py`의 단일 transaction에서 Meeting, 고객 영업 단계, 위치 snapshot, 동기화 version, outbox를 함께 확정한다. 외부 Google 호출은 커밋 뒤 Celery worker가 수행한다. 각 outbox는 Meeting의 증가하는 version을 가지며, 늦게 도착한 과거 작업은 `superseded`로 종료한다. Google event ID는 Meeting ID에서 결정론적으로 만들어 재시도 삽입 중복을 막는다. broker 발행 실패 시 DB outbox가 남고 시간별 drain 명령이 복구한다.

**Tech Stack:** Django 5.2/DRF/PostgreSQL, Celery 5.6/Redis, Google Calendar API, Next.js 16/React 19, Django TestCase/TransactionTestCase.

## 2026-08-18 검증 결과 (아래 원문은 그대로 유지)

**이 릴리스 범위는 PR #173(머지 `52cf912`)으로 처리됐다. 단, 구현 형태는 아래 원문 계획과 다르다.** 원문은 outbox 테이블 + Celery worker + 결정론적 event ID를 설계했으나, 실제로는 더 작은 형태로 들어갔다. 다음 세션은 원문이 아니라 아래 실제 구현을 기준으로 볼 것.

실제 구현:
- 구글 캘린더 이벤트 삭제 함수 신설 (`accounts/google_calendar.py::delete_meeting_event`, 404/410 멱등).
- `booking/calendar_sync.py`가 취소·거절 시 삭제를 수행하고, **삭제가 확인된 뒤에만** `google_event_id`를 정리한다.
- 실패는 `Meeting.calendar_cleanup_pending`(migration booking `0004`, additive)으로 남고 `run_daily_jobs`가 재시도한다. 구글 연동이 끊긴 계정은 재시도 배치에서 제외한다.
- 취소는 조건부 update로 원자화됐다 (대기·확정 → 취소만 허용, 이미 취소는 멱등 200, 거절 건은 409).
- WorkHour 겹침·포함·완전중복을 저장 시 거절한다 (half-open 비교, PATCH는 자기 자신 제외). 슬롯 dedupe 적용.
- `BOOKING_PUBLIC_HORIZON_DAYS`(기본 14)를 공개 GET과 POST가 공유하고, 기간 밖은 400 `TIME_OUT_OF_RANGE`다 (기존 60일 하드코딩 제거).
- 검증: BE 2,602 OK/39 skip, 수정 전 RED 13건 확인.

잔존:
- WorkHour 완전중복을 막는 **DB 제약**은 아직 없다 (현재는 애플리케이션 레벨 검증만). 프로덕션의 기존 중복 여부를 먼저 확인한 뒤 별도로 처리해야 한다.

아래 원문은 당시 구현 계획 기록으로 보존한다. 전체 잔존 목록은 `docs/superpowers/specs/2026-07-21-comprehensive-stability-upgrade.md` §0 참고.

## Global Constraints

- 승인 설계는 `docs/superpowers/specs/2026-07-21-comprehensive-stability-upgrade.md`의 Release 3다.
- DB 상태 변경이 주 작업이고 Google Calendar는 부가 동기화다. Google 장애가 수락·취소를 롤백하지 않는다.
- 허용 전이는 `pending -> confirmed`, `pending -> declined`, `confirmed -> canceled`뿐이다.
- 유효하지 않은 전이는 409 `INVALID_MEETING_TRANSITION`으로 통일한다.
- accept transaction에는 status, 대면 장소 snapshot, 고객 `sales_stage`, `fa_reached_at`, `last_contacted_at`, outbox가 함께 들어간다.
- 취소는 confirmed만 가능하며 delete outbox를 만든다.
- Google API의 400/401/403은 재시도하지 않는다. 401은 재연결 상태로, 403/400은 안전한 오류 코드로 남긴다.
- network/timeout/429/5xx만 최대 3회, 1초·2초·4초 backoff로 재시도한다.
- delete 404는 성공이다.
- 로그에는 refresh token, 고객명, 전화번호, 위치, 메모, Google 응답 본문을 남기지 않는다.
- WorkHour는 같은 요일에 여러 구간과 서로 맞닿는 구간을 허용한다. 실제 겹침과 완전 중복만 거부한다.
- public 예약 GET과 POST 재검증의 horizon은 같은 설정값 14일이다.
- Render worker queue·cron 변경은 코드 선언까지만 한다. Blueprint sync와 비용 변경은 별도 PM 승인이다.
- 아래 커밋 단계는 PM이 별도로 요청한 경우에만 수행한다.

---

### Task 1: 예약 상태 전이를 도메인 서비스로 고정

**Files:**

- Create: `inpa_be/inpa/booking/services.py`
- Create: `inpa_be/inpa/booking/test_services.py`
- Modify: `inpa_be/inpa/booking/views.py`
- Modify: `inpa_be/inpa/booking/tests.py`

- [ ] **Step 1: 상태 matrix를 RED 테스트로 작성한다.**

```python
class MeetingTransitionTests(TestCase):
    def test_pending_can_confirm(self): ...
    def test_pending_can_decline(self): ...
    def test_confirmed_can_cancel(self): ...
    def test_confirmed_cannot_confirm_again(self): ...
    def test_declined_cannot_cancel(self): ...
    def test_canceled_cannot_confirm_or_cancel_again(self): ...
```

API 테스트는 잘못된 전이가 모두 `409`와 아래 body를 반환하는지 확인한다.

```json
{"code":"INVALID_MEETING_TRANSITION","detail":"현재 상태에서 처리할 수 없어요."}
```

- [ ] **Step 2: accept의 원자 데이터 테스트를 추가한다.**

```python
def test_confirm_updates_meeting_customer_and_outbox_in_one_transaction(self): ...
def test_confirm_snapshots_in_person_location_only(self): ...
def test_confirm_stamps_first_fa_and_last_contacted(self): ...
def test_confirm_never_demotes_contract_customer(self): ...
```

초기 단계 db/contact는 meeting으로 승급하고 `fa_reached_at`, `last_contacted_at`이 저장된다. contract는 단계와 최초 FA 시각을 보존하되 `last_contacted_at`은 수락 행동 시각으로 갱신한다.

- [ ] **Step 3: 현재 API의 RED를 확인한다.**

Run: `cd inpa_be && python manage.py test inpa.booking.test_services inpa.booking.tests.BookingCoreTests -v 2`

Expected: service/outbox가 없고 cancel이 어떤 상태에서도 가능해 실패.

- [ ] **Step 4: transition exception과 잠금 서비스를 추가한다.**

```python
class InvalidMeetingTransition(Exception):
    pass


@transaction.atomic
def confirm_meeting(*, meeting_id, owner):
    meeting = (
        Meeting.objects.select_for_update()
        .select_related('customer', 'owner__profile')
        .get(pk=meeting_id, owner=owner)
    )
    if meeting.status != Meeting.STATUS_PENDING:
        raise InvalidMeetingTransition
    now = timezone.now()
    meeting.status = Meeting.STATUS_CONFIRMED
    meeting.calendar_sync_version += 1
    ...
    meeting.save(update_fields=[...])
    ...
    job = enqueue_calendar_sync_locked(meeting, operation='upsert')
    transaction.on_commit(lambda: dispatch_calendar_sync(job.pk))
    return meeting
```

`decline_meeting()`은 pending만 declined로 바꾸고 outbox를 만들지 않는다. `cancel_meeting()`은 confirmed만 canceled로 바꾸고 delete outbox를 만든다.

- [ ] **Step 5: Customer `save(update_fields=...)` 함정을 명시적으로 처리한다.**

db/contact 고객 승급 시 최소 아래 필드를 포함한다.

```python
customer.save(update_fields=[
    'sales_stage',
    'fa_reached_at',
    'last_contacted_at',
])
```

contract 고객도 `last_contacted_at`만 저장한다. `fa_reached_at`은 최초 값 이후 덮어쓰지 않는다.

- [ ] **Step 6: ViewSet을 얇게 바꾸고 409를 통일한다.**

`accept`, `decline`, `cancel`은 owner-scoped object ID와 service 호출, serializer 반환만 담당한다. 기존 `_push_to_google()`과 넓은 `except Exception: pass`는 제거한다.

- [ ] **Step 7: 상태 테스트를 통과시킨다.**

Run: `cd inpa_be && python manage.py test inpa.booking.test_services inpa.booking.tests.BookingCoreTests -v 2`

초기에는 다음 Task의 모델이 없어 일부 테스트가 실패할 수 있다. Task 2까지 연속 수행한 뒤 모두 PASS여야 한다.

---

### Task 2: additive outbox·동기화 version 모델과 마이그레이션 추가

**Files:**

- Modify: `inpa_be/inpa/booking/models.py`
- Create: `inpa_be/inpa/booking/migrations/0004_calendar_sync_outbox.py`
- Modify: `inpa_be/inpa/booking/admin.py`
- Modify: `inpa_be/inpa/booking/serializers.py`
- Create: `inpa_be/inpa/booking/test_calendar_outbox.py`

- [ ] **Step 1: 모델 불변식 테스트를 작성한다.**

```python
class CalendarOutboxModelTests(TestCase):
    def test_meeting_version_is_unique_per_outbox(self): ...
    def test_outbox_error_fields_reject_raw_provider_body(self): ...
    def test_meeting_defaults_to_not_connected(self): ...
```

같은 `(meeting, version)` job 두 개는 `IntegrityError`여야 한다. `last_error_code`는 enum 길이만 허용하고 자유 텍스트 필드는 만들지 않는다.

- [ ] **Step 2: 모델과 migration을 추가한다.**

`Meeting` additive fields:

```python
CALENDAR_SYNC_NOT_CONNECTED = 'not_connected'
CALENDAR_SYNC_PENDING = 'pending'
CALENDAR_SYNC_SYNCED = 'synced'
CALENDAR_SYNC_ERROR = 'error'
CALENDAR_SYNC_REAUTH = 'reauth_required'

calendar_sync_status = models.CharField(
    max_length=20,
    choices=CALENDAR_SYNC_STATUS_CHOICES,
    default=CALENDAR_SYNC_NOT_CONNECTED,
)
calendar_sync_version = models.PositiveIntegerField(default=0)
```

Outbox 모델:

```python
class GoogleCalendarOutbox(models.Model):
    OP_UPSERT = 'upsert'
    OP_DELETE = 'delete'
    STATUS_PENDING = 'pending'
    STATUS_PROCESSING = 'processing'
    STATUS_SUCCEEDED = 'succeeded'
    STATUS_FAILED = 'failed'
    STATUS_SUPERSEDED = 'superseded'

    meeting = models.ForeignKey(
        Meeting, on_delete=models.CASCADE, related_name='calendar_sync_jobs')
    operation = models.CharField(max_length=10, choices=OP_CHOICES)
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=12, choices=STATUS_CHOICES,
                              default=STATUS_PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    available_at = models.DateTimeField(default=timezone.now, db_index=True)
    last_error_code = models.CharField(max_length=40, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['meeting', 'version'], name='uniq_calendar_job_meeting_version')]
```

- [ ] **Step 3: migration 검증을 실행한다.**

Run:

```bash
cd inpa_be
python manage.py makemigrations --check --dry-run
python manage.py migrate
python manage.py showmigrations booking
```

Expected: 새 migration 외 추가 변경 0건, `0004` applied.

- [ ] **Step 4: serializer에 설계사용 동기화 상태만 노출한다.**

`MeetingSerializer.fields`에 `calendar_sync_status`를 read-only로 추가한다. `last_error_code`, attempts, Google event ID, token은 노출하지 않는다.

- [ ] **Step 5: admin은 관측 전용으로 등록한다.**

outbox의 add/delete 권한을 막고 list_display는 meeting id, operation, version, status, attempts, available_at만 표시한다. 검색에 고객명·전화번호를 추가하지 않는다.

- [ ] **Step 6: 모델 테스트를 통과시킨다.**

Run: `cd inpa_be && python manage.py test inpa.booking.test_calendar_outbox -v 2`

---

### Task 3: Google adapter를 멱등 upsert·delete 계약으로 확장

**Files:**

- Modify: `inpa_be/inpa/accounts/google_calendar.py`
- Modify: `inpa_be/inpa/accounts/test_google.py`

- [ ] **Step 1: adapter RED 테스트를 작성한다.**

```python
def test_event_id_is_deterministic_for_meeting(self): ...
def test_upsert_reuses_same_event_id_after_retry(self): ...
def test_delete_404_is_success(self): ...
def test_401_maps_to_auth_error_without_token_or_body(self): ...
def test_429_and_5xx_map_to_transient_error(self): ...
def test_400_and_403_map_to_permanent_error(self): ...
```

Google client는 mock한다. 테스트 assertion이나 failure output에 refresh token이 들어가지 않게 한다.

- [ ] **Step 2: RED를 확인한다.**

Run: `cd inpa_be && python manage.py test inpa.accounts.test_google.GoogleCalendarTests -v 2`

Expected: 현재 insert-only 함수와 삭제 함수 부재로 실패.

- [ ] **Step 3: PII-safe 예외 계층과 결정론 ID를 구현한다.**

```python
class CalendarSyncError(Exception):
    code = 'CALENDAR_ERROR'
    retryable = False

class CalendarTransientError(CalendarSyncError):
    code = 'CALENDAR_TRANSIENT'
    retryable = True

class CalendarAuthError(CalendarSyncError):
    code = 'CALENDAR_AUTH_REQUIRED'


def calendar_event_id(meeting_id: int) -> str:
    digest = hashlib.sha256(f'inpa-meeting:{meeting_id}'.encode()).hexdigest()
    return f'inpa{digest[:40]}'
```

Google event ID 허용 문자 계약을 공식 client 동작과 테스트로 확인한다. 고객명 mask와 최소 event body는 기존 정책을 유지한다.

- [ ] **Step 4: upsert를 재시도 안전하게 만든다.**

`upsert_meeting_event(profile, meeting, customer_name)`은 결정론 ID로 `events().update()`를 먼저 시도하고 404일 때 해당 ID를 body에 넣어 insert한다. insert 409는 같은 event가 이미 생긴 것으로 보고 update로 수렴한다. 성공하면 항상 같은 event ID를 반환한다.

- [ ] **Step 5: delete adapter를 추가한다.**

```python
def delete_meeting_event(profile, meeting_id):
    event_id = calendar_event_id(meeting_id)
    try:
        service.events().delete(calendarId='primary', eventId=event_id).execute()
    except HttpError as exc:
        if exc.resp.status == 404:
            return event_id
        raise map_calendar_error(exc) from None
    return event_id
```

외부 예외 메시지나 response content를 다시 raise하지 않는다.

- [ ] **Step 6: adapter 테스트를 통과시킨다.**

Run: `cd inpa_be && python manage.py test inpa.accounts.test_google -v 2`

---

### Task 4: outbox worker·재시도·복구 drain 구현

**Files:**

- Create: `inpa_be/inpa/booking/tasks.py`
- Create: `inpa_be/inpa/booking/management/__init__.py`
- Create: `inpa_be/inpa/booking/management/commands/__init__.py`
- Create: `inpa_be/inpa/booking/management/commands/drain_calendar_sync.py`
- Create: `inpa_be/inpa/booking/test_calendar_tasks.py`
- Modify: `inpa_be/config/settings/base.py`
- Modify: `render.yaml`

- [ ] **Step 1: 작업 상태와 재시도 테스트를 작성한다.**

```python
def test_newer_meeting_version_supersedes_old_upsert(self): ...
def test_success_marks_outbox_and_meeting_synced(self): ...
def test_transient_error_schedules_one_two_four_seconds(self): ...
def test_third_transient_failure_is_terminal_error(self): ...
def test_auth_error_sets_reauth_without_retry(self): ...
def test_delete_404_converges_to_not_connected(self): ...
def test_dispatch_failure_leaves_pending_row_for_drain(self): ...
def test_drain_enqueues_only_due_pending_rows(self): ...
```

- [ ] **Step 2: RED를 확인한다.**

Run: `cd inpa_be && python manage.py test inpa.booking.test_calendar_tasks -v 2`

- [ ] **Step 3: DB claim과 stale version 확인을 구현한다.**

worker는 outbox ID만 인자로 받는다. `select_for_update(skip_locked=True)`로 pending/due row를 claim한다. claim 후 `job.version != meeting.calendar_sync_version`이면 외부 호출 없이 superseded로 종료한다.

```python
@shared_task(bind=True, queue='calendar_sync', max_retries=3)
def sync_google_calendar(self, outbox_id):
    claimed = claim_calendar_job(outbox_id)
    if claimed is None:
        return 'noop'
    try:
        run_calendar_job(claimed)
    except CalendarTransientError as exc:
        schedule_retry(claimed, code=exc.code)
        raise self.retry(exc=CalendarTransientError(exc.code),
                         countdown=(1, 2, 4)[claimed.attempts - 1])
```

Celery exception에도 외부 메시지나 PII가 포함되지 않게 code-only exception을 사용한다.

- [ ] **Step 4: 성공·영구 실패의 Meeting 상태를 함께 갱신한다.**

- upsert 성공: `google_event_id=deterministic id`, `calendar_sync_status=synced`
- delete 성공/404: `google_event_id=None`, `calendar_sync_status=not_connected`
- 401: `calendar_sync_status=reauth_required`
- 영구 오류·retry 소진: `calendar_sync_status=error`

모든 갱신은 job version이 여전히 current일 때만 한다.

- [ ] **Step 5: 발행 함수와 drain 명령을 구현한다.**

`dispatch_calendar_sync(job_id)`는 `.delay(str(job_id))` 실패를 code-only log로 남기고 re-raise하지 않는다. outbox row는 pending 상태라 사라지지 않는다.

`drain_calendar_sync --limit 100`은 due pending job ID만 읽고 enqueue한다. 출력은 `queued`, `failed`, `skipped` 수량뿐이다.

- [ ] **Step 6: Celery route와 Render 선언을 추가한다.**

```python
CELERY_TASK_ROUTES = {
    'inpa.booking.tasks.sync_google_calendar': {'queue': 'calendar_sync'},
}
```

`render.yaml` worker command:

```text
celery -A config worker -l INFO -Q insurance_imports,calendar_sync --concurrency 4
```

기존 hourly cron start command는 두 명령이 순차 실행되도록 바꾼다.

```text
python manage.py cleanup_insurance_imports && python manage.py drain_calendar_sync --limit 100
```

Blueprint sync는 하지 않는다.

- [ ] **Step 7: worker 테스트를 통과시킨다.**

Run: `cd inpa_be && python manage.py test inpa.booking.test_calendar_tasks -v 2`

---

### Task 5: WorkHour 겹침과 공개 예약 horizon 계약 강화

**Files:**

- Modify: `inpa_be/inpa/booking/models.py`
- Create: `inpa_be/inpa/booking/migrations/0005_workhour_unique.py`
- Modify: `inpa_be/inpa/booking/serializers.py`
- Modify: `inpa_be/inpa/booking/views.py`
- Modify: `inpa_be/inpa/booking/availability.py`
- Modify: `inpa_be/inpa/booking/public_booking.py`
- Modify: `inpa_be/config/settings/base.py`
- Modify: `inpa_be/inpa/booking/tests.py`

- [ ] **Step 1: 업무시간 불변식 테스트를 작성한다.**

```python
def test_adjacent_workhours_are_allowed(self): ...       # 09:00-12:00, 12:00-18:00
def test_overlapping_workhours_are_rejected(self): ...   # 09:00-12:00, 11:00-13:00
def test_exact_duplicate_is_rejected(self): ...
def test_slot_generator_deduplicates_legacy_overlap(self): ...
def test_post_rejects_slot_beyond_same_fourteen_day_horizon(self): ...
```

legacy overlap row는 DB fixture로 직접 만든 뒤 generator 결과 start_at이 유일한지 확인한다.

- [ ] **Step 2: RED를 확인한다.**

Run: `cd inpa_be && python manage.py test inpa.booking.tests.BookingCoreTests -v 2`

- [ ] **Step 3: exact duplicate DB 제약을 additive migration으로 추가한다.**

```python
models.UniqueConstraint(
    fields=['owner', 'weekday', 'start_time', 'end_time'],
    name='uniq_workhour_owner_weekday_range',
)
```

Migration 전에 동일 exact row가 존재할 가능성을 dry-run 조회로 확인하고 자동 삭제하지 않는다. 중복이 있으면 PM에게 수량만 보고하고 migration 적용을 멈춘다.

- [ ] **Step 4: 겹침 검사를 owner row lock 안에서 수행한다.**

serializer는 친절한 400 validation을 제공하고, ViewSet `perform_create/perform_update`는 transaction에서 owner User row를 `select_for_update()`한 뒤 같은 검사를 다시 수행한다. 조건은 half-open interval이다.

```python
overlap = qs.filter(start_time__lt=end, end_time__gt=start)
```

따라서 12:00에 맞닿는 두 구간은 허용된다.

- [ ] **Step 5: generator 출력을 set으로 dedupe한다.**

`slots`는 datetime set에 추가한 뒤 정렬된 list로 반환한다. 이는 기존 겹침 row가 migration 전 존재하는 경우에도 고객에게 같은 시각을 두 번 보이지 않는 방어다.

- [ ] **Step 6: horizon 설정을 GET과 POST에 함께 사용한다.**

```python
BOOKING_PUBLIC_HORIZON_DAYS = env.int(
    'BOOKING_PUBLIC_HORIZON_DAYS', default=14)
```

`is_slot_available()`에 `days` 인자를 추가하고 public GET·POST 모두 이 설정값을 전달한다. 하드코딩된 60일 재검증을 제거한다.

- [ ] **Step 7: migration과 예약 테스트를 통과시킨다.**

Run:

```bash
cd inpa_be
python manage.py migrate
python manage.py test inpa.booking -v 2
```

---

### Task 6: 설계사 일정 화면에 동기화 상태와 복구 행동 노출

**Files:**

- Modify: `inpa_fe/lib/api.ts`
- Modify: `inpa_fe/app/schedule/page.tsx`
- Create: `inpa_fe/components/__tests__/meeting-calendar-sync-status.test.tsx`

- [ ] **Step 1: FE 상태 matrix 테스트를 작성한다.**

| API 상태 | 화면 |
|---|---|
| `pending` | `Google 일정에 반영 중` |
| `synced` | 별도 경고 없음 |
| `reauth_required` | `Google Calendar를 다시 연결하면 일정이 반영돼요` + 설정 링크 |
| `error` | `인파 일정은 저장됐어요. Google 일정 반영을 다시 확인해 주세요` |
| `not_connected` | 연동하지 않은 사용자에게 경고 없음 |

- [ ] **Step 2: RED를 확인한다.**

Run: `cd inpa_fe && npm test -- --run components/__tests__/meeting-calendar-sync-status.test.tsx`

- [ ] **Step 3: API 타입과 일정 카드 표현을 구현한다.**

```ts
export type CalendarSyncStatus =
  | "not_connected"
  | "pending"
  | "synced"
  | "error"
  | "reauth_required";
```

고객 이름·일정 시각·예약 상태가 주 정보이고 동기화 상태는 보조 문구로 둔다. `error`를 예약 실패처럼 빨간 거절 카드로 만들지 않는다.

- [ ] **Step 4: FE 테스트와 build를 통과시킨다.**

Run:

```bash
cd inpa_fe
npm test -- --run components/__tests__/meeting-calendar-sync-status.test.tsx
npm run build
```

---

### Task 7: PostgreSQL 경쟁·장애 복구·통합 검증

**Files:**

- Create: `inpa_be/inpa/booking/test_postgres_concurrency.py`
- Review: Release 3에서 수정한 파일만

- [ ] **Step 1: SQLite에서 제외되는 PostgreSQL 경쟁 테스트를 작성한다.**

`TransactionTestCase`와 두 DB connection/thread로 다음을 검증한다.

```python
@skipUnless(connection.vendor == 'postgresql', 'PostgreSQL lock test')
def test_accept_and_decline_race_has_one_winner(self): ...

@skipUnless(connection.vendor == 'postgresql', 'PostgreSQL lock test')
def test_accept_and_cancel_sequence_has_monotonic_versions(self): ...

@skipUnless(connection.vendor == 'postgresql', 'PostgreSQL lock test')
def test_overlapping_workhour_create_race_has_one_winner(self): ...
```

최종 outbox version은 Meeting current version과 같고 active job은 하나여야 한다.

- [ ] **Step 2: BE 대상·전체 테스트를 실행한다.**

```bash
cd inpa_be
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test inpa.booking inpa.accounts.test_google -v 2
```

- [ ] **Step 3: 임시 PostgreSQL에서 경쟁 테스트를 실행한다.**

기존 프로젝트 PostgreSQL 테스트 환경을 사용한다. 새 DB나 외부 리소스가 필요하면 먼저 승인을 받는다.

```bash
DJANGO_SETTINGS_MODULE=config.settings.test_postgres \
  python manage.py test inpa.booking.test_postgres_concurrency -v 2
```

Expected: race당 성공 1개, 충돌 1개, 중복 outbox/event 0개.

- [ ] **Step 4: fake Google client로 runtime 경로를 호출한다.**

API로 pending 예약 생성, accept, worker 직접 실행, cancel, delete worker 실행 순서를 탄다. DB 결과:

- accept: confirmed, version 1, synced, deterministic event ID
- cancel: canceled, version 2, not_connected, event ID null
- stale version 1 재실행: superseded, 외부 insert 호출 0회

- [ ] **Step 5: 실제 Google 테스트 계정 검증은 별도 승인 후 수행한다.**

테스트용 planner와 비민감 synthetic 고객만 사용한다. 실제 검증 시 일정 1건 생성·중복 수락 후 1건 유지·취소 후 삭제를 확인한다. 운영 사용자 계정과 실제 고객 정보는 사용하지 않는다.

- [ ] **Step 6: Render 선언 diff를 검토하되 sync하지 않는다.**

worker가 `insurance_imports,calendar_sync` 두 queue를 듣고 hourly cron이 cleanup 뒤 drain을 실행하는지만 확인한다. 서비스 plan, instance count, 비용은 바꾸지 않는다.

- [ ] **Step 7: FE 전체 회귀와 브라우저 스모크를 실행한다.**

```bash
cd ../inpa_fe
npm test -- --run
npm run lint:copy
npm run build
```

390px 일정 화면에서 pending/synced/reauth/error 문구가 레이아웃을 깨지 않고, 취소 뒤 시간 슬롯이 다시 열리는지 확인한다.

- [ ] **Step 8: diff·보안·PII review 후 PM 검토 지점에서 멈춘다.**

```bash
git diff --check
git diff -- inpa_be/inpa/booking inpa_be/inpa/accounts/google_calendar.py \
  inpa_be/config/settings/base.py render.yaml inpa_fe/app/schedule/page.tsx inpa_fe/lib/api.ts
```

로그·모델·admin·Celery exception에 token, 고객명, 전화번호, 위치, note가 없는지 확인한다. 커밋, Blueprint sync, Preview, Production은 별도 요청 전 실행하지 않는다.
