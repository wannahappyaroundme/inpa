# 녹음당 한 번 AI 상담 요약 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 준비된 녹음 하나에서 사용자 AI 요약을 정확히 한 번 실행하고, 네 구역 개조식 결과를 새 편집 가능 메모로 저장한다.

**Architecture:** `ConsultationSummaryRun` OneToOne 제약과 idempotency key가 이중 요청을 차단한다. Celery worker는 원음을 NAVER CLOVA Speech 장문 API에 한 번 접수한 뒤 같은 token만 조회하고, 완료된 대화문을 메모리에만 둔 채 식별정보를 줄여 Anthropic structured output으로 요약한다. 성공 건수와 처리 분수는 별도 원자적 예약 서비스로 관리한다.

**Tech Stack:** Django 5.2, PostgreSQL row locks, Celery 5.6, NAVER CLOVA Speech long-form API, Anthropic Python SDK 0.117.1, Claude structured output, React 19, Vitest.

## Global Constraints

- `CONSULTATION_AI_SUMMARY_ENABLED` 기본값은 `False`다.
- 녹음 원본은 Anthropic에 전달하지 않는다.
- 녹음당 `ConsultationSummaryRun`은 DB상 한 건만 존재한다.
- 공급자 예약이 확정된 뒤에는 사용자·관리자 모두 같은 녹음으로 새 실행을 만들 수 없다.
- 공급자 token 발급 뒤 재시도는 새 submit이 아니라 같은 token poll만 수행한다.
- Anthropic 호출 뒤 저장 여부가 불명확하면 `ambiguous`로 끝내고 재호출하지 않는다.
- 원문 대화, 마스킹 전후 전문, prompt, AI JSON 응답은 DB·Redis·로그·Sentry에 저장하지 않는다.
- 최종 DB에는 편집 가능한 메모 본문, 상태, 길이, token 수, 비용, 내용 없는 오류 코드만 남긴다.
- Free는 월 성공 5건·처리 시작 150분·고객별 첫 성공 1회다.
- Plus/Manager는 30건·900분, Super는 100건·3,000분으로 시작한다.
- 기존 `FREE_TIER_UNLIMITED`는 상담 요약 한도를 우회하지 않는다.
- 성공 요약만 공개 건수에 포함하고 외부 처리가 시작된 올림 분수는 실패해도 내부 한도에 포함한다.
- PM 요청 전 commit·프로덕션 배포·AI 게이트 공개를 하지 않는다.

---

### Task 1: 요약 실행·무료 혜택·사용량 데이터 모델

**Files:**
- Modify: `inpa_be/inpa/consultations/models.py`
- Modify: `inpa_be/inpa/billing/models.py`
- Modify: `inpa_be/inpa/billing/management/commands/seed_billing.py`
- Modify: `inpa_be/inpa/customers/models.py`
- Create migrations with `makemigrations`: `consultations`, `billing`, `customers`
- Test: `inpa_be/inpa/consultations/tests/test_summary_models.py`
- Test: `inpa_be/inpa/billing/tests.py`

**Interfaces:**
- Produces: `ConsultationSummaryRun`, `ConsultationCustomerBenefit`.
- Extends: `CustomerMemo.summary_run`, `Plan.limit_consultation_summary`, `Plan.limit_consultation_minute`, `UsageMeter` actions.

- [ ] **Step 1: Write failing uniqueness and plan-limit tests**

```python
def test_recording_has_only_one_summary_run_and_one_success_memo(self):
    first = ConsultationSummaryRun.objects.create(
        recording=self.recording, idempotency_key='key-a', status='queued')
    with self.assertRaises(IntegrityError):
        with transaction.atomic():
            ConsultationSummaryRun.objects.create(
                recording=self.recording, idempotency_key='key-b', status='queued')
    CustomerMemo.objects.create(
        owner=self.user, customer=self.customer, source='ai_summary',
        body='상담 핵심\n- 내용', occurred_at=self.recording.ended_at,
        summary_run=first)
    with self.assertRaises(IntegrityError):
        with transaction.atomic():
            CustomerMemo.objects.create(
                owner=self.user, customer=self.customer, source='ai_summary',
                body='중복', occurred_at=self.recording.ended_at,
                summary_run=first)

def test_seeded_limits_match_approved_safety_values(self):
    call_command('seed_billing')
    self.assertEqual(Plan.objects.get(code='free').limit_consultation_summary, 5)
    self.assertEqual(Plan.objects.get(code='free').limit_consultation_minute, 150)
    self.assertEqual(Plan.objects.get(code='super').limit_consultation_summary, 100)
```

- [ ] **Step 2: Add exact summary models**

```python
class ConsultationSummaryRun(models.Model):
    STATUS_QUEUED = 'queued'
    STATUS_TRANSCRIBING = 'transcribing'
    STATUS_SUMMARIZING = 'summarizing'
    STATUS_SUCCEEDED = 'succeeded'
    STATUS_FAILED = 'failed'
    STATUS_AMBIGUOUS = 'ambiguous'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = tuple((value, value) for value in (
        STATUS_QUEUED, STATUS_TRANSCRIBING, STATUS_SUMMARIZING,
        STATUS_SUCCEEDED, STATUS_FAILED, STATUS_AMBIGUOUS, STATUS_CANCELLED))

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recording = models.OneToOneField(
        ConsultationRecording, on_delete=models.CASCADE, related_name='summary_run')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, db_index=True)
    idempotency_key = models.CharField(max_length=80)
    attempt_uuid = models.UUIDField(default=uuid.uuid4)
    lease_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    stt_provider = models.CharField(max_length=40, blank=True, default='')
    stt_job_id = models.CharField(max_length=200, blank=True, default='')
    summary_provider = models.CharField(max_length=40, blank=True, default='')
    summary_model = models.CharField(max_length=100, blank=True, default='')
    summary_reserved_at = models.DateTimeField(null=True, blank=True)
    prompt_version = models.CharField(max_length=40)
    recording_consent_version = models.CharField(max_length=40)
    sensitive_consent_version = models.CharField(max_length=40)
    overseas_consent_version = models.CharField(max_length=40)
    provider_reserved_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    processing_seconds = models.PositiveIntegerField(default=0)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    estimated_cost_krw = models.PositiveIntegerField(default=0)
    usage_year_month = models.CharField(max_length=7, blank=True, default='')
    success_count_reserved = models.PositiveSmallIntegerField(default=0)
    processing_minutes_reserved = models.PositiveIntegerField(default=0)
    success_reservation_released_at = models.DateTimeField(null=True, blank=True)
    minute_reservation_released_at = models.DateTimeField(null=True, blank=True)
    admin_compensated_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(max_length=40, blank=True, default='')
    error_code = models.CharField(max_length=80, blank=True, default='')
    error_type = models.CharField(max_length=80, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'consultation_summary_run'
        indexes = [models.Index(fields=['status', 'lease_expires_at'])]
```

```python
class ConsultationCustomerBenefit(models.Model):
    STATUS_RESERVED = 'reserved'
    STATUS_CONSUMED = 'consumed'
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    customer = models.ForeignKey('customers.Customer', on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=(('reserved', 'reserved'), ('consumed', 'consumed')))
    reserved_run = models.OneToOneField(
        ConsultationSummaryRun, on_delete=models.SET_NULL, null=True, blank=True)
    reserved_at = models.DateTimeField(null=True, blank=True)
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'consultation_customer_benefit'
        constraints = [models.UniqueConstraint(
            fields=['owner', 'customer'], name='uniq_consultation_customer_benefit')]
```

- [ ] **Step 3: Extend billing and memo fields**

```python
limit_consultation_summary = models.PositiveIntegerField(
    '상담 요약 한도(월)', null=True, blank=True, default=5)
limit_consultation_minute = models.PositiveIntegerField(
    '상담 음성 처리 분(월)', null=True, blank=True, default=150)
```

```python
ACTION_CHOICES = (
    ('ocr', 'OCR 증권 분석'),
    ('ai_compare', '증권 비교'),
    ('analysis', 'AI 분석·메시지'),
    ('promotion', '판촉물 주문'),
    ('customer', '고객 추가'),
    ('consultation_summary', '상담 요약'),
    ('consultation_minute', '상담 음성 처리 분'),
)
```

`CustomerMemo`에는 다음 필드를 추가한다.

```python
summary_run = models.OneToOneField(
    'consultations.ConsultationSummaryRun', on_delete=models.SET_NULL,
    null=True, blank=True, related_name='memo')
```

- [ ] **Step 4: Update seed defaults without overwriting admin changes**

```python
PLAN_DEFAULTS = {
    'free': {'limit_consultation_summary': 5, 'limit_consultation_minute': 150},
    'plus': {'limit_consultation_summary': 30, 'limit_consultation_minute': 900},
    'manager': {'limit_consultation_summary': 30, 'limit_consultation_minute': 900},
    'super': {'limit_consultation_summary': 100, 'limit_consultation_minute': 3000},
}
```

기존 `get_or_create(code=..., defaults=...)`의 create-time defaults에만 합치고 기존 Plan row를 update하지 않는다.

- [ ] **Step 5: Generate migrations in dependency order and test**

Run: `cd inpa_be && python manage.py makemigrations consultations billing customers && python manage.py migrate && python manage.py test inpa.consultations.tests.test_summary_models inpa.billing -v 1`

Expected: cycle 없는 migrations 생성·적용, uniqueness와 seed tests PASS.

- [ ] **Step 6: Commit only after PM asks**

```bash
git add inpa_be/inpa/consultations inpa_be/inpa/billing inpa_be/inpa/customers
git commit -m "feat(요약): 1회 실행과 상담 사용량 모델 추가"
```

### Task 2: 상담 요약 게이트와 국외이전 동의

**Files:**
- Modify: `inpa_be/config/settings/base.py`
- Modify: `inpa_be/inpa/customers/models.py`
- Modify: `inpa_be/inpa/customers/consent_texts.py`
- Modify: `inpa_be/inpa/customers/public_consent.py`
- Modify: `inpa_be/inpa/customers/views.py`
- Generate migration: `customers`
- Test: `inpa_be/inpa/customers/tests.py`

**Interfaces:**
- Produces: `consultation_overseas_summary` current-version consent.
- Produces: `summary_feature_enabled(user)`.

- [ ] **Step 1: Write failing dual-gate and three-consent tests**

```python
def test_summary_requires_all_three_customer_self_current_versions(self):
    grant_current_consultation_consents(self.customer, include_overseas=False)
    self.assertFalse(has_current_consultation_summary_consents(self.customer))
    ConsentLog.objects.create(
        customer=self.customer, scope='consultation_overseas_summary',
        subject='customer_self', doc_version='v1-2026-07-22')
    self.assertTrue(has_current_consultation_summary_consents(self.customer))

def test_admin_switch_does_not_override_closed_ai_environment_gate(self):
    config = ConsultationRuntimeConfig.solo()
    config.ai_summary_enabled = True
    config.save(update_fields=['ai_summary_enabled'])
    with override_settings(CONSULTATION_AI_SUMMARY_ENABLED=False):
        self.assertFalse(summary_feature_enabled(self.user))
```

- [ ] **Step 2: Add env/model gates and provider settings**

```python
CONSULTATION_AI_SUMMARY_ENABLED = env.bool(
    'CONSULTATION_AI_SUMMARY_ENABLED', default=False)
CONSULTATION_STT_PROVIDER = env('CONSULTATION_STT_PROVIDER', default='clova')
CLOVA_SPEECH_INVOKE_URL = env('CLOVA_SPEECH_INVOKE_URL', default='')
CLOVA_SPEECH_SECRET_KEY = env('CLOVA_SPEECH_SECRET_KEY', default='')
CONSULTATION_SUMMARY_MODEL = env('CONSULTATION_SUMMARY_MODEL', default='')
CONSULTATION_SUMMARY_PROMPT_VERSION = env(
    'CONSULTATION_SUMMARY_PROMPT_VERSION', default='v1-2026-07-22')
BACKEND_BASE_URL = env('BACKEND_BASE_URL', default='')
```

`ConsultationRuntimeConfig`에 `ai_summary_enabled = models.BooleanField(default=False)`를 추가한다.

- [ ] **Step 3: Add overseas scope and current helper**

```python
SCOPE_CONSULTATION_OVERSEAS_SUMMARY = 'consultation_overseas_summary'
```

```python
CONSULTATION_CONSENT_TEXTS[ConsentLog.SCOPE_CONSULTATION_OVERSEAS_SUMMARY] = {
    'title': '상담 요약을 위한 국외 처리',
    'body': '요약을 위해 이름과 연락처를 가린 상담 내용이 미국 Anthropic으로 전달될 수 있습니다. 전달된 내용은 해당 업체 기준에 따라 최대 30일 보관될 수 있습니다.',
    'required': True,
}
```

```python
def has_current_consultation_summary_consents(customer):
    required = {
        **CONSULTATION_CONSENT_VERSIONS,
        ConsentLog.SCOPE_CONSULTATION_OVERSEAS_SUMMARY: 'v1-2026-07-22',
    }
    return all(ConsentLog.objects.filter(
        customer=customer, scope=scope,
        subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
        doc_version=version, revoked_at__isnull=True,
    ).exists() for scope, version in required.items())
```

- [ ] **Step 4: Generate migration and run consent tests**

Run: `cd inpa_be && python manage.py makemigrations consultations customers && python manage.py test inpa.customers inpa.consultations.tests.test_summary_models -v 1`

Expected: 기존 scope 동작 불변, 새 summary consent tests PASS.

- [ ] **Step 5: Commit only after PM asks**

```bash
git add inpa_be/config/settings/base.py inpa_be/inpa/customers inpa_be/inpa/consultations/models.py inpa_be/inpa/consultations/migrations
git commit -m "feat(동의): 상담 AI 요약 국외 처리 동의 추가"
```

### Task 3: 원자적 무료 혜택·월 건수·처리 분수 예약

**Files:**
- Create: `inpa_be/inpa/consultations/quota.py`
- Create: `inpa_be/inpa/consultations/summary_service.py`
- Test: `inpa_be/inpa/consultations/tests/test_quota.py`
- Test: `inpa_be/inpa/consultations/tests/test_summary_concurrency.py`

**Interfaces:**
- Produces: `request_summary(*, recording, user, idempotency_key)`.
- Produces: `settle_summary_success(run)`, `settle_summary_failure(run, provider_started)`.

- [ ] **Step 1: Write failing quota and 100-request concurrency tests**

```python
def test_free_customer_benefit_and_monthly_usage_settle_only_on_success(self):
    run, created = request_summary(
        recording=self.recording, user=self.user, idempotency_key='once')
    self.assertTrue(created)
    self.assertEqual(run.success_count_reserved, 1)
    self.assertEqual(run.processing_minutes_reserved, 60)
    self.assertEqual(usage_count(self.user, 'consultation_summary'), 0)
    settle_summary_failure(run, provider_started=True)
    self.assertFalse(ConsultationCustomerBenefit.objects.filter(
        owner=self.user, customer=self.customer, status='consumed').exists())
    self.assertEqual(usage_count(self.user, 'consultation_summary'), 0)
    self.assertEqual(usage_count(self.user, 'consultation_minute'), 60)

def test_one_hundred_requests_create_one_run_and_one_enqueue(self):
    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda _: request_once(), range(100)))
    self.assertEqual(ConsultationSummaryRun.objects.filter(recording=self.recording).count(), 1)
    self.assertEqual(self.enqueue.call_count, 1)
    self.assertEqual(len({result.id for result in results}), 1)
```

- [ ] **Step 2: Implement consultation-only meter reservations**

```python
def reserve_minute_meter(*, user, amount, year_month):
    action = 'consultation_minute'
    if amount <= 0:
        raise ValueError('INVALID_CONSULTATION_ACTION')
    plan = resolve_effective_plan(user)
    limit = plan.get_limit(action)
    meter, _ = UsageMeter.objects.select_for_update().get_or_create(
        user=user, action=action, year_month=year_month, defaults={'count': 0})
    if limit is not None and meter.count + amount > limit:
        raise LimitExceeded(action, meter.count, limit)
    meter.count += amount
    meter.save(update_fields=['count', 'updated_at'])
    return meter


def release_meter(*, user, action, amount, year_month):
    meter = UsageMeter.objects.select_for_update().get(
        user=user, action=action, year_month=year_month)
    meter.count = max(0, meter.count - amount)
    meter.save(update_fields=['count', 'updated_at'])


def assert_success_slot_available(*, user, year_month):
    plan = resolve_effective_plan(user)
    limit = plan.get_limit('consultation_summary')
    meter, _ = UsageMeter.objects.select_for_update().get_or_create(
        user=user, action='consultation_summary', year_month=year_month,
        defaults={'count': 0})
    reserved = ConsultationSummaryRun.objects.filter(
        recording__owner=user, usage_year_month=year_month,
        success_count_reserved=1,
        status__in=('queued', 'transcribing', 'summarizing'),
    ).count()
    if limit is not None and meter.count + reserved + 1 > limit:
        raise LimitExceeded('consultation_summary', meter.count, limit)


def consume_success_meter(*, user, year_month):
    meter = UsageMeter.objects.select_for_update().get(
        user=user, action='consultation_summary', year_month=year_month)
    meter.count += 1
    meter.save(update_fields=['count', 'updated_at'])
```

이 함수들은 `free_tier_unlimited()`를 호출하지 않는다. 성공 건수 meter는 request 시 올리지 않고 active run을 별도 예약으로 계산하며, success settlement에서만 `consume_success_meter`로 올린다.

- [ ] **Step 3: Implement the locked one-shot request**

```python
def request_summary(*, recording, user, idempotency_key):
    with transaction.atomic():
        locked = (ConsultationRecording.objects.select_for_update()
                  .select_related('customer').get(pk=recording.pk, owner=user))
        existing = ConsultationSummaryRun.objects.filter(recording=locked).first()
        if existing:
            return existing, False
        validate_summary_request(locked, user)
        year_month = UsageMeter.current_month()
        minutes = max(1, math.ceil(locked.duration_ms / 60_000))
        assert_success_slot_available(user=user, year_month=year_month)
        run = ConsultationSummaryRun.objects.create(
            recording=locked, status='queued', idempotency_key=idempotency_key,
            prompt_version=settings.CONSULTATION_SUMMARY_PROMPT_VERSION,
            recording_consent_version='v1-2026-07-22',
            sensitive_consent_version='v1-2026-07-22',
            overseas_consent_version='v1-2026-07-22',
            usage_year_month=year_month, success_count_reserved=1,
            processing_minutes_reserved=minutes)
        reserve_minute_meter(user=user, amount=minutes, year_month=year_month)
        reserve_customer_benefit_if_free(run=run, user=user, customer=locked.customer)
        transaction.on_commit(lambda: process_consultation_summary.delay(str(run.id)))
        return run, True
```

`reserve_customer_benefit_if_free`는 effective plan이 Free일 때만 `(owner, customer)` row를 `select_for_update/get_or_create`한다. 이미 consumed면 `CUSTOMER_FREE_SUMMARY_USED`를 raise해 같은 고객의 두 번째 녹음 요약은 Plus 전환 다음 행동을 반환한다. Plus·Manager·Super는 고객별 무료 row와 무관하게 월 한도 안에서 같은 고객의 새 녹음을 요약할 수 있다. 모든 요금제에서 녹음 하나당 run OneToOne은 그대로 적용된다. success settlement는 summary meter를 1 올리고 Free benefit만 consumed로 만든다. failed/ambiguous settlement는 active success 예약과 reserved benefit을 해제하고, 공급자 미접수가 확실할 때만 minute meter도 해제한다.

- [ ] **Step 4: Run SQLite logic and PostgreSQL concurrency tests**

Run: `cd inpa_be && python manage.py test inpa.consultations.tests.test_quota -v 2`

Run: `cd inpa_be && DJANGO_SETTINGS_MODULE=config.settings.test_postgres python manage.py test inpa.consultations.tests.test_summary_concurrency -v 2`

Expected: quota settlement PASS, 100 requests → run 1·enqueue 1·meter reservation 1.

- [ ] **Step 5: Commit only after PM asks**

```bash
git add inpa_be/inpa/consultations/quota.py inpa_be/inpa/consultations/summary_service.py inpa_be/inpa/consultations/tests
git commit -m "feat(요약): 무료 혜택과 1회 실행 원자화"
```

### Task 4: CLOVA Speech 장문 provider와 같은 token 조회

**Files:**
- Create: `inpa_be/inpa/consultations/providers/__init__.py`
- Create: `inpa_be/inpa/consultations/providers/base.py`
- Create: `inpa_be/inpa/consultations/providers/clova.py`
- Create: `inpa_be/inpa/consultations/callbacks.py`
- Modify: `inpa_be/inpa/consultations/urls.py`
- Modify: `inpa_be/requirements.txt`
- Test: `inpa_be/inpa/consultations/tests/test_clova_provider.py`

**Interfaces:**
- Produces: `SpeechToTextProvider.submit(fileobj, callback_url) -> SubmittedSpeechJob`.
- Produces: `SpeechToTextProvider.poll(job_id) -> SpeechJobResult`.

- [ ] **Step 1: Write failing submit/poll/retry-boundary tests**

```python
def test_submit_uses_async_korean_and_returns_provider_token(self):
    self.http.post.return_value = response(200, {'token': 'provider-token', 'result': 'SUCCEEDED'})
    result = self.provider.submit(self.audio, 'https://api.inpa.kr/api/v1/consultations/callback/x/')
    self.assertEqual(result.job_id, 'provider-token')
    params = json.loads(self.http.post.call_args.kwargs['data']['params'])
    self.assertEqual(params['language'], 'ko-KR')
    self.assertEqual(params['completion'], 'async')
    self.assertTrue(params['diarization']['enable'])

def test_poll_returns_transcript_in_memory_and_never_resubmits(self):
    self.http.get.return_value = response(200, {
        'result': 'COMPLETED',
        'segments': [{'text': '첫 문장'}, {'text': '둘째 문장'}]})
    result = self.provider.poll('provider-token')
    self.assertEqual(result.transcript, '첫 문장\n둘째 문장')
    self.http.post.assert_not_called()

def test_callback_uses_signed_run_token_and_ignores_provider_body(self):
    response = self.client.post(self.callback_url, {
        'segments': [{'text': '본문을 저장하면 안 됩니다'}]}, format='json')
    self.assertEqual(response.status_code, 204)
    self.assertFalse(ConsultationSummaryRun.objects.filter(
        error_code__contains='본문').exists())
    self.process_task.assert_called_once_with(str(self.run.id))

def test_submit_connect_failure_can_retry_but_unknown_receipt_never_resubmits(self):
    self.http.post.side_effect = httpx.ConnectError('connect failed')
    with self.assertRaises(ExplicitProviderNonReceipt):
        self.provider.submit(self.audio, self.callback_url)
    self.http.post.side_effect = httpx.ReadTimeout('receipt unknown')
    with self.assertRaises(SpeechSubmitOutcomeUnknown):
        self.provider.submit(self.audio, self.callback_url)
```

- [ ] **Step 2: Add a direct HTTP dependency and provider result types**

```text
httpx==0.28.1
anthropic==0.117.1
```

```python
@dataclass(frozen=True)
class SubmittedSpeechJob:
    job_id: str


@dataclass(frozen=True)
class SpeechJobResult:
    state: Literal['waiting', 'processing', 'completed', 'failed', 'timeout']
    transcript: str = ''
    processing_seconds: int = 0
    error_code: str = ''
```

- [ ] **Step 3: Implement CLOVA submit and poll**

```python
class ClovaSpeechProvider:
    def __init__(self, client=None):
        self.client = client or httpx.Client(timeout=httpx.Timeout(30.0, read=120.0))
        self.invoke_url = settings.CLOVA_SPEECH_INVOKE_URL.rstrip('/')
        self.headers = {'X-CLOVASPEECH-API-KEY': settings.CLOVA_SPEECH_SECRET_KEY}

    def submit(self, fileobj, callback_url):
        params = {
            'language': 'ko-KR', 'completion': 'async', 'callback': callback_url,
            'wordAlignment': False, 'fullText': True, 'noiseFiltering': True,
            'diarization': {'enable': True, 'speakerCountMin': 2, 'speakerCountMax': 2},
            'resultToObs': False,
        }
        response = self.client.post(
            f'{self.invoke_url}/recognizer/upload', headers=self.headers,
            data={'params': json.dumps(params, ensure_ascii=False)},
            files={'media': ('consultation-audio', fileobj, 'application/octet-stream')})
        response.raise_for_status()
        job_id = response.json().get('token', '')
        if not job_id:
            raise SpeechProviderProtocolError('MISSING_JOB_TOKEN')
        return SubmittedSpeechJob(job_id=job_id)

    def poll(self, job_id):
        response = self.client.get(
            f'{self.invoke_url}/recognizer/{quote(job_id, safe="")}', headers=self.headers)
        response.raise_for_status()
        payload = response.json()
        state = CLOVA_STATES.get(payload.get('result'), 'failed')
        transcript = ''
        if state == 'completed':
            transcript = '\n'.join(
                segment.get('text', '').strip() for segment in payload.get('segments', [])
                if segment.get('text', '').strip())
        return SpeechJobResult(state=state, transcript=transcript,
                               error_code='' if state != 'failed' else 'CLOVA_FAILED')
```

`submit`은 `httpx.ConnectError`와 `ConnectTimeout`처럼 서버 접수 전임이 확실한 오류만 `ExplicitProviderNonReceipt`로 바꾼다. `ReadTimeout`, `WriteError`, 응답 JSON 손상처럼 접수 여부를 알 수 없는 오류는 `SpeechSubmitOutcomeUnknown`으로 바꾸고 run을 `ambiguous`로 끝낸다. 이 경우 같은 녹음의 재접수와 재요약을 모두 막는다.

`callback`은 NAVER가 async 요청에 요구하는 완료 알림 주소로만 사용한다. body를 읽거나 신뢰하지 않고 signed run token을 확인한 뒤 같은 poll task를 앞당긴다.

```python
class ClovaSpeechCallbackView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'consultation_callback'

    def post(self, request, token):
        try:
            run_id = signing.TimestampSigner(
                salt='consultation-clova-callback').unsign(token, max_age=7200)
        except signing.BadSignature:
            raise NotFound
        if ConsultationSummaryRun.objects.filter(pk=run_id).exists():
            process_consultation_summary.delay(str(run_id))
        return Response(status=204)
```

```python
path('consultations/clova-callback/<str:token>/',
     ClovaSpeechCallbackView.as_view(), name='clova-speech-callback')
```

callback URL에는 `FRONTEND_BASE_URL`이 아니라 새 서버 공개 base 환경변수 `BACKEND_BASE_URL`을 사용한다. 값이 없거나 HTTPS가 아니면 AI gate를 열지 않는다.

`consultation_callback` throttle은 기본 `120/hour`로 추가하고 callback token은 2시간 뒤 만료한다.

- [ ] **Step 4: Run provider tests and existing OCR dependency regressions**

Run: `cd inpa_be && python manage.py test inpa.consultations.tests.test_clova_provider inpa.insurances.tests -v 1`

Expected: provider tests and existing Anthropic OCR tests PASS after SDK bump.

- [ ] **Step 5: Commit only after PM asks**

```bash
git add inpa_be/inpa/consultations/providers inpa_be/inpa/consultations/tests/test_clova_provider.py inpa_be/requirements.txt
git commit -m "feat(요약): CLOVA 장문 음성변환 연동"
```

### Task 5: 식별정보 축소와 Claude 구조화 요약

**Files:**
- Create: `inpa_be/inpa/consultations/transcript_mask.py`
- Create: `inpa_be/inpa/consultations/summary_schema.py`
- Create: `inpa_be/inpa/consultations/providers/anthropic_summary.py`
- Test: `inpa_be/inpa/consultations/tests/test_transcript_mask.py`
- Test: `inpa_be/inpa/consultations/tests/test_anthropic_summary.py`

**Interfaces:**
- Produces: `mask_transcript(transcript, known_names) -> MaskedTranscript`.
- Produces: `summarize(masked_transcript) -> ConsultationSummary`.
- Produces: `render_summary_memo(summary) -> str`.

- [ ] **Step 1: Write failing PII and hallucination-boundary tests**

```python
def test_masker_removes_known_names_phone_email_resident_and_account_numbers(self):
    raw = '홍길동 고객 010-2468-1357, abc@example.com, 900101-1234567, 계좌 110-123-456789'
    result = mask_transcript(raw, known_names=['홍길동'])
    for value in ('홍길동', '010-2468-1357', 'abc@example.com', '900101-1234567', '110-123-456789'):
        self.assertNotIn(value, result.text)
    self.assertTrue(result.residual_scan_passed)

def test_summary_schema_rejects_extra_sections_and_oversized_body(self):
    with self.assertRaises(InvalidSummary):
        ConsultationSummary.from_payload({'consultation_core': ['내용'], 'recommendation': ['가입']})
```

- [ ] **Step 2: Implement deterministic masking and fail-closed scan**

```python
PATTERNS = (
    ('전화', re.compile(r'(?<!\d)(?:01[016789][ -]?\d{3,4}[ -]?\d{4})(?!\d)')),
    ('이메일', re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')),
    ('주민번호', re.compile(r'(?<!\d)\d{6}[ -]?[1-8]\d{6}(?!\d)')),
    ('계좌', re.compile(r'(?<!\d)\d{2,4}[ -]\d{2,6}[ -]\d{3,8}(?!\d)')),
)


def mask_transcript(transcript, known_names):
    text = unicodedata.normalize('NFKC', transcript)
    counts = Counter()
    for index, name in enumerate(sorted({value.strip() for value in known_names if value.strip()},
                                        key=len, reverse=True), start=1):
        text, count = re.subn(re.escape(name), f'[이름_{index}]', text)
        counts['known_name'] += count
    for label, pattern in PATTERNS:
        index = 0
        def replace(match):
            nonlocal index
            index += 1
            return f'[{label}_{index}]'
        text, count = pattern.subn(replace, text)
        counts[label] += count
    residual_scan_passed = not any(pattern.search(text) for _, pattern in PATTERNS)
    if not residual_scan_passed:
        raise UnsafeTranscript('RESIDUAL_IDENTIFIER')
    return MaskedTranscript(text=text, counts=tuple(sorted(counts.items())),
                            residual_scan_passed=True)
```

- [ ] **Step 3: Define exact JSON schema and memo renderer**

```python
SUMMARY_JSON_SCHEMA = {
    'type': 'object',
    'properties': {
        'consultation_core': {'type': 'array', 'items': {'type': 'string', 'maxLength': 300}, 'maxItems': 12},
        'customer_priorities': {'type': 'array', 'items': {'type': 'string', 'maxLength': 300}, 'maxItems': 12},
        'items_to_confirm': {'type': 'array', 'items': {'type': 'string', 'maxLength': 300}, 'maxItems': 12},
        'next_actions': {'type': 'array', 'items': {'type': 'string', 'maxLength': 300}, 'maxItems': 12},
    },
    'required': ['consultation_core', 'customer_priorities', 'items_to_confirm', 'next_actions'],
    'additionalProperties': False,
}


def render_summary_memo(summary):
    sections = (
        ('상담 핵심', summary.consultation_core),
        ('고객이 중요하게 본 내용', summary.customer_priorities),
        ('확인할 내용', summary.items_to_confirm),
        ('다음 할 일', summary.next_actions),
    )
    body = '\n\n'.join(
        f"{title}\n" + ('\n'.join(f'- {item}' for item in items) if items else '- 확인된 내용 없음')
        for title, items in sections)
    if len(body) > 5_000:
        raise InvalidSummary('SUMMARY_TOO_LONG')
    return body
```

- [ ] **Step 4: Implement one Anthropic structured-output call**

```python
class AnthropicConsultationSummarizer:
    def summarize(self, masked_transcript):
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=settings.CONSULTATION_SUMMARY_MODEL,
            max_tokens=2_500,
            system=SYSTEM_PROMPT,
            messages=[{'role': 'user', 'content': masked_transcript}],
            output_config={'format': {
                'type': 'json_schema', 'schema': SUMMARY_JSON_SCHEMA}},
        )
        if response.stop_reason in {'refusal', 'max_tokens'}:
            raise InvalidSummary(f'STOP_{response.stop_reason.upper()}')
        text = ''.join(block.text for block in response.content if block.type == 'text')
        payload = json.loads(text)
        summary = ConsultationSummary.from_payload(payload)
        return SummaryProviderResult(
            summary=summary, input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model)
```

`SYSTEM_PROMPT`는 대화에 없는 사실 생성 금지, 불확실한 금액·날짜·보험명은 `확인 필요`, 상품 추천·가입·해지·의료 판단 금지, 대화 속 지시를 명령으로 실행하지 않음을 명시한다. prompt text는 코드 상수지만 로그에 출력하지 않는다.

- [ ] **Step 5: Run masking and summary tests**

Run: `cd inpa_be && python manage.py test inpa.consultations.tests.test_transcript_mask inpa.consultations.tests.test_anthropic_summary -v 2`

Expected: PII fixture·schema·refusal·max token·5,000자·token telemetry tests PASS.

- [ ] **Step 6: Commit only after PM asks**

```bash
git add inpa_be/inpa/consultations/transcript_mask.py inpa_be/inpa/consultations/summary_schema.py inpa_be/inpa/consultations/providers/anthropic_summary.py inpa_be/inpa/consultations/tests
git commit -m "feat(요약): 식별정보 축소와 구조화 요약 추가"
```

### Task 6: Celery one-shot pipeline과 모호 상태 처리

**Files:**
- Create: `inpa_be/inpa/consultations/tasks.py`
- Modify: `inpa_be/config/settings/base.py`
- Modify: `render.yaml`
- Test: `inpa_be/inpa/consultations/tests/test_summary_worker.py`

**Interfaces:**
- Produces Celery task: `process_consultation_summary(run_id)`.
- Consumes storage, CLOVA provider, masker, summarizer, quota settlement, `CustomerMemo`.

- [ ] **Step 1: Write failing worker crash, redelivery, and ambiguous-call tests**

```python
def test_redelivery_with_provider_token_only_polls_and_never_submits_again(self):
    self.run.status = 'transcribing'
    self.run.stt_job_id = 'existing-token'
    self.run.provider_reserved_at = timezone.now()
    self.run.save()
    process_consultation_summary(str(self.run.id))
    self.stt.submit.assert_not_called()
    self.stt.poll.assert_called_once_with('existing-token')

def test_unknown_anthropic_write_result_becomes_ambiguous_without_retry(self):
    self.summarizer.summarize.side_effect = SummaryOutcomeUnknown
    process_consultation_summary(str(self.run.id))
    self.run.refresh_from_db()
    self.assertEqual(self.run.status, 'ambiguous')
    self.assertEqual(self.summarizer.summarize.call_count, 1)
    self.assertEqual(CustomerMemo.objects.filter(summary_run=self.run).count(), 0)
```

- [ ] **Step 2: Implement lease claim and same-run rescheduling**

```python
@shared_task(bind=True, acks_late=True, reject_on_worker_lost=True)
def process_consultation_summary(self, run_id):
    run = claim_run(run_id, lease_seconds=300)
    if run is None:
        return
    try:
        if not run.stt_job_id:
            submit_stt_once(run)
            process_consultation_summary.apply_async(args=[run_id], countdown=15)
            return
        speech = get_stt_provider().poll(run.stt_job_id)
        if speech.state in {'waiting', 'processing'}:
            release_lease(run.id)
            process_consultation_summary.apply_async(args=[run_id], countdown=20)
            return
        if speech.state != 'completed':
            fail_run(run.id, code=f'STT_{speech.state.upper()}', provider_started=True)
            return
        summarize_transcript_once(run.id, speech.transcript)
    except ExplicitProviderNonReceipt as exc:
        retry_same_run(self, run.id, type(exc).__name__)
    except SpeechSubmitOutcomeUnknown:
        mark_ambiguous(run.id, code='STT_SUBMIT_RESULT_UNKNOWN')
    except SummaryOutcomeUnknown:
        mark_ambiguous(run.id, code='SUMMARY_RESULT_UNKNOWN')
    except Exception as exc:
        fail_run(run.id, code='SUMMARY_PIPELINE_FAILED',
                 error_type=type(exc).__name__, provider_started=bool(run.provider_reserved_at))
```

- [ ] **Step 3: Implement submit and atomic success**

```python
def submit_stt_once(run):
    with transaction.atomic():
        locked = ConsultationSummaryRun.objects.select_for_update().get(pk=run.pk)
        if locked.stt_job_id:
            return
        if locked.provider_reserved_at:
            raise SpeechSubmitOutcomeUnknown
        locked.provider_reserved_at = timezone.now()
        locked.attempt_count += 1
        locked.status = 'transcribing'
        locked.save(update_fields=[
            'provider_reserved_at', 'attempt_count', 'status', 'updated_at'])
    with get_recording_storage().open_temp(run.recording.storage_key) as audio:
        try:
            submitted = get_stt_provider().submit(audio, callback_url_for(run))
        except ExplicitProviderNonReceipt:
            with transaction.atomic():
                locked = ConsultationSummaryRun.objects.select_for_update().get(pk=run.pk)
                locked.provider_reserved_at = None
                locked.status = 'queued'
                locked.save(update_fields=['provider_reserved_at', 'status', 'updated_at'])
            raise
    with transaction.atomic():
        locked = ConsultationSummaryRun.objects.select_for_update().get(pk=run.pk)
        if locked.stt_job_id:
            return
        locked.stt_job_id = submitted.job_id
        locked.stt_provider = settings.CONSULTATION_STT_PROVIDER
        locked.status = 'transcribing'
        locked.save(update_fields=['stt_job_id', 'stt_provider', 'status', 'updated_at'])


def summarize_transcript_once(run_id, transcript):
    with transaction.atomic():
        run = (ConsultationSummaryRun.objects.select_for_update()
               .select_related('recording__customer', 'recording__owner')
               .get(pk=run_id))
        if run.status in {'succeeded', 'cancelled', 'ambiguous'}:
            return getattr(run, 'memo', None)
        if run.summary_reserved_at:
            raise SummaryOutcomeUnknown
        assert_current_consents(run.recording.customer)
        run.summary_reserved_at = timezone.now()
        run.status = 'summarizing'
        run.save(update_fields=['summary_reserved_at', 'status', 'updated_at'])
    masked = mask_transcript(transcript, known_names=[
        run.recording.customer.name,
        getattr(run.recording.owner.profile, 'name', ''),
    ])
    result = get_summarizer().summarize(masked.text)
    body = render_summary_memo(result.summary)
    with transaction.atomic():
        locked = ConsultationSummaryRun.objects.select_for_update().get(pk=run_id)
        if locked.status == 'succeeded':
            return locked.memo
        memo = CustomerMemo.objects.create(
            owner_id=locked.recording.owner_id,
            customer_id=locked.recording.customer_id,
            source='ai_summary', body=body,
            occurred_at=locked.recording.ended_at, summary_run=locked)
        locked.status = 'succeeded'
        locked.summary_provider = 'anthropic'
        locked.summary_model = result.model
        locked.input_tokens = result.input_tokens
        locked.output_tokens = result.output_tokens
        locked.completed_at = timezone.now()
        locked.outcome = 'success'
        locked.save()
        consume_success_meter(
            user=locked.recording.owner,
            year_month=locked.usage_year_month)
        consume_customer_benefit(locked)
        bump_last_contacted_at(locked.recording.customer_id, locked.recording.ended_at)
        return memo
```

STT submit 전 reservation과 Claude 호출 전 `summary_reserved_at` reservation을 먼저 commit한다. worker가 외부 호출 중 죽으면 redelivery는 marker를 보고 `ambiguous`로 끝내며 같은 외부 요청을 다시 만들지 않는다. 명시적 STT 미접수만 marker를 지우고 최대 3회 재시도한다. `SpeechSubmitOutcomeUnknown`은 공급자 처리 분을 유지한다.

late result는 run status가 cancelled이거나 source가 deleted이거나 현재 동의가 철회됐으면 저장하지 않는다. 동의 철회와 조기 원음 삭제 경로는 active run을 `cancelled`로 row-lock 갱신한 뒤 외부 결과를 폐기한다. transcript와 masked text는 함수 반환 뒤 참조를 해제하며 task args·result backend에 넣지 않는다.

- [ ] **Step 4: Route tasks to a dedicated queue and extend worker timeout**

```python
CELERY_TASK_ROUTES = {
    'inpa.insurances.tasks.*': {'queue': 'insurance_imports'},
    'inpa.consultations.tasks.*': {'queue': 'consultation_summaries'},
}
```

Render worker command는 두 queue를 소비하되 consultation 동시성은 설정값 1로 시작한다. worker child에는 100MiB 원음과 PyAV wheel을 고려해 최소 2GB 메모리 plan을 사용한다.

- [ ] **Step 5: Run worker and full insurance regressions**

Run: `cd inpa_be && python manage.py test inpa.consultations.tests.test_summary_worker inpa.insurances -v 1`

Expected: submit once·poll redelivery·late result·consent revoke·ambiguous·success memo tests PASS, insurance pipeline regressions PASS.

- [ ] **Step 6: Commit only after PM asks**

```bash
git add inpa_be/inpa/consultations/tasks.py inpa_be/inpa/consultations/tests/test_summary_worker.py inpa_be/config/settings/base.py render.yaml
git commit -m "feat(요약): 1회 AI 요약 작업 파이프라인 추가"
```

### Task 7: 요약 API와 메모 카드 사용자 상태

**Files:**
- Modify: `inpa_be/inpa/consultations/serializers.py`
- Modify: `inpa_be/inpa/consultations/views.py`
- Modify: `inpa_be/inpa/consultations/urls.py`
- Modify: `inpa_fe/lib/api.ts`
- Modify: `inpa_fe/components/consultation-recorder/recording-card.tsx`
- Modify: `inpa_fe/components/customer-memos.tsx`
- Test: `inpa_be/inpa/consultations/tests/test_summary_api.py`
- Test: `inpa_fe/components/__tests__/consultation-summary.test.tsx`

**Interfaces:**
- Produces: `POST /api/v1/customers/{customer_pk}/recordings/{recording_id}/summarize/`, existing recording detail with summary state.
- Produces UI: one confirm, processing recovery, success memo, failure direct-memo path.

- [ ] **Step 1: Write failing API idempotency and UI tests**

```python
def test_summarize_returns_same_run_for_same_or_different_double_click(self):
    first = self.client.post(self.url, HTTP_IDEMPOTENCY_KEY='click-1')
    second = self.client.post(self.url, HTTP_IDEMPOTENCY_KEY='click-2')
    self.assertEqual(first.status_code, 202)
    self.assertEqual(second.status_code, 200)
    self.assertEqual(first.data['id'], second.data['id'])
    self.assertFalse(second.data['can_summarize'])
```

```tsx
it('confirms one use, disables regeneration, and offers direct memo after failure', async () => {
  render(<RecordingCard recording={readyRecording} customerId={31} onDeleted={vi.fn()} />);
  await userEvent.click(screen.getByRole('button', { name: '이 녹음으로 요약 만들기' }));
  expect(screen.getByText('이 녹음은 요약을 한 번만 만들 수 있어요.')).toBeTruthy();
  await userEvent.click(screen.getByRole('button', { name: '요약 만들기' }));
  expect(await screen.findByText('상담 내용을 정리하고 있어요.')).toBeTruthy();
  api.getConsultationRecording.mockResolvedValue(failedRecording);
  expect(await screen.findByRole('button', { name: '원본을 들으며 메모 작성' })).toBeTruthy();
  expect(screen.queryByRole('button', { name: /다시 요약/ })).toBeNull();
});
```

- [ ] **Step 2: Add summary response fields**

```python
class ConsultationSummaryRunSerializer(serializers.ModelSerializer):
    can_summarize = serializers.SerializerMethodField()

    class Meta:
        model = ConsultationSummaryRun
        fields = ('id', 'status', 'outcome', 'error_code', 'started_at',
                  'completed_at', 'can_summarize')

    def get_can_summarize(self, obj):
        return False
```

Recording detail에는 `summary_run` nullable object와 `can_summarize = source_available and summary_run is None and summary gate/consents/quota eligible`를 포함한다. 내부 비용·provider job id·model id·동의 버전은 사용자 serializer에 넣지 않는다.

같은 응답에 `summary_allowance`를 넣는다. 사용자에게는 `customer_first_free_available`, `monthly_success_used`, `monthly_success_limit`, `will_use_customer_free`만 보여주고 내부 처리 분 예약값은 노출하지 않는다.

- [ ] **Step 3: Implement summarize endpoint**

```python
class RecordingSummarizeView(CustomerRecordingMixin, APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'consultation_summary'

    def post(self, request, customer_pk, recording_id):
        recording = self.get_recording(customer_pk, recording_id)
        key = request.headers.get('Idempotency-Key', '').strip()
        if not key or len(key) > 80:
            return Response({'code': 'IDEMPOTENCY_KEY_REQUIRED',
                             'detail': '요약 요청을 다시 확인해 주세요.'}, status=400)
        try:
            run, created = request_summary(
                recording=recording, user=request.user, idempotency_key=key)
        except LimitExceeded as exc:
            return consultation_limit_response(exc)
        except SummaryPrecondition as exc:
            return Response({'code': exc.code, 'detail': exc.detail}, status=exc.status)
        return Response(ConsultationSummaryRunSerializer(run).data,
                        status=202 if created else 200)
```

- [ ] **Step 4: Add client state and polling**

```ts
export const summarizeConsultationRecording = (customerId: number, recordingId: string) =>
  request<ConsultationSummaryRun>(
    'POST', `/customers/${customerId}/recordings/${recordingId}/summarize/`, {}, true,
    { 'Idempotency-Key': crypto.randomUUID() });
```

`RecordingCard`는 `can_summarize`일 때만 요약 버튼을 보인다. 확인창에는 길이, 자동 삭제 시각, 무료 여부, 1회 안내를 표시한다. queued/transcribing/summarizing은 5초에서 30초로 늘어나는 poll로 recording detail을 다시 불러오고 화면 이동 후에도 복구한다. succeeded는 새 memo를 목록 맨 위에 합치기 위해 `onSummaryCreated(memo)`를 호출한다. failed/ambiguous는 직접 메모 버튼과 새 녹음 버튼만 보인다.

- [ ] **Step 5: Run API and UI tests**

Run: `cd inpa_be && python manage.py test inpa.consultations.tests.test_summary_api -v 2`

Run: `cd inpa_fe && npm run test:run -- components/__tests__/consultation-summary.test.tsx components/__tests__/customer-memos.test.tsx && npm run lint:copy && npm run build`

Expected: one-shot·quota·consent·owner·processing recovery·no-regenerate tests PASS.

- [ ] **Step 6: Commit only after PM asks**

```bash
git add inpa_be/inpa/consultations inpa_fe/lib/api.ts inpa_fe/components/consultation-recorder/recording-card.tsx inpa_fe/components/customer-memos.tsx inpa_fe/components/__tests__/consultation-summary.test.tsx
git commit -m "feat(고객): 녹음당 한 번 AI 요약 연결"
```

### Task 8: 관리자 비용·상태·보상과 정확도 공개 게이트

**Files:**
- Modify: `inpa_be/inpa/admin_console/serializers.py`
- Modify: `inpa_be/inpa/admin_console/views.py`
- Modify: `inpa_fe/lib/adminApi.ts`
- Modify: `inpa_fe/app/admin/consultations/page.tsx`
- Create: `inpa_be/inpa/consultations/evaluation.py`
- Create: `inpa_be/inpa/consultations/management/commands/evaluate_consultation_summaries.py`
- Modify: `docs/dev/28-consultation-recording-operations.md`
- Test: `inpa_be/inpa/admin_console/tests.py`
- Test: `inpa_be/inpa/consultations/tests/test_evaluation.py`

**Interfaces:**
- Produces content-free admin metrics and one-time usage compensation.
- Produces offline gold-set report without committing real consultation data.

- [ ] **Step 1: Write failing admin redaction and compensation tests**

```python
def test_admin_metrics_expose_cost_and_outcomes_without_content(self):
    response = self.client.get('/api/v1/admin/consultations/')
    encoded = json.dumps(response.data, ensure_ascii=False)
    self.assertIn('summary_success_count', encoded)
    self.assertIn('estimated_cost_krw', encoded)
    for forbidden in ('transcript', 'body', 'storage_key', 'customer_name', 'stt_job_id'):
        self.assertNotIn(forbidden, encoded)

def test_usage_compensation_is_idempotent_and_never_enables_regeneration(self):
    first = self.client.post(f'/api/v1/admin/consultations/runs/{self.run.id}/compensate/')
    second = self.client.post(f'/api/v1/admin/consultations/runs/{self.run.id}/compensate/')
    self.assertEqual(first.status_code, 200)
    self.assertEqual(second.status_code, 200)
    self.assertEqual(ConsultationSummaryRun.objects.filter(recording=self.recording).count(), 1)
```

- [ ] **Step 2: Extend the admin snapshot**

```python
def consultation_status_snapshot():
    runs = ConsultationSummaryRun.objects.all()
    return {
        'summary_queued_count': runs.filter(status='queued').count(),
        'summary_processing_count': runs.filter(status__in=('transcribing', 'summarizing')).count(),
        'summary_success_count': runs.filter(status='succeeded').count(),
        'summary_failed_count': runs.filter(status='failed').count(),
        'summary_ambiguous_count': runs.filter(status='ambiguous').count(),
        'processing_minutes': runs.aggregate(total=Sum('processing_minutes_reserved'))['total'] or 0,
        'estimated_cost_krw': runs.aggregate(total=Sum('estimated_cost_krw'))['total'] or 0,
        'p50_seconds': percentile_duration(runs, 0.50),
        'p95_seconds': percentile_duration(runs, 0.95),
        **recording_storage_status_snapshot(),
    }
```

Admin UI에는 요금제별 건수·분수 수정, AI 운영 kill switch, 파일럿 summary 허용, 일·월 비용 상한, queue·성공·실패·ambiguous·p50/p95를 추가한다. 상세 run 표에는 UUID, 상태, 분수, token, 비용, 오류 enum만 둔다.

- [ ] **Step 3: Implement idempotent compensation**

보상 endpoint는 run row를 lock하고 `admin_compensated_at`이 null일 때만 success/minute meter를 선택적으로 되돌린다. `ConsultationSummaryRun` 또는 `ConsultationCustomerBenefit`을 삭제하지 않고 summary 재요약 권한도 만들지 않는다.

- [ ] **Step 4: Add offline evaluation report**

```python
@dataclass(frozen=True)
class EvaluationResult:
    total: int
    critical_hallucinations: int
    speaker_reversals: int
    identifier_leaks: int
    factual_accuracy: Decimal

    @property
    def gate_passed(self):
        return (self.total >= 100 and self.critical_hallucinations == 0
                and self.speaker_reversals == 0 and self.identifier_leaks == 0
                and self.factual_accuracy >= Decimal('0.95'))
```

Command 입력은 gitignored `inpa_be/private/consultation-eval/*.jsonl`만 허용하고 real text는 stdout·report에 쓰지 않는다. report는 count·rate·prompt version·model env value·reviewer agreement만 JSON으로 출력한다.

- [ ] **Step 5: Run complete verification**

Run: `cd inpa_be && python manage.py check && python manage.py test inpa`

Run: `cd inpa_be && DJANGO_SETTINGS_MODULE=config.settings.test_postgres python manage.py test inpa.consultations.tests.test_summary_concurrency`

Run: `cd inpa_fe && npm run test:run && npm run lint:copy && npm run build`

Expected: all PASS.

제한 파일럿 전 합성 no-PII E2E로 upload → ready → summarize → CLOVA poll → mask → Claude schema → memo → direct edit → source delete를 실행한다. 합성 성공은 실제 상담 정확도 공개 근거로 사용하지 않는다.

- [ ] **Step 6: Stop at the evidence gates**

다음 네 증거가 모두 있기 전 `CONSULTATION_AI_SUMMARY_ENABLED=true` 또는 일반 공개를 하지 않는다.

```text
1. NAVER 음원 임시 보관·파기 조건 서면 확인
2. 상담 녹음·민감정보·국외이전 동의문 승인
3. 100건 이상 골드셋: 중대 환각 0, 화자 반전 0, 식별정보 누락 0, 사실 정확도 95% 이상
4. 제한 파일럿 4주: 처리 성공률 98% 이상, ambiguous 0.5% 이하, 원가 한도 검증
```

PM에게 `Changed / Verified by / Result / Unverified` 형식으로 보고하고 프로덕션 배포와 각 gate 공개 승인을 별도로 요청한다.
