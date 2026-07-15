# Insurance Extraction Review Accuracy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 전자 보험증권 PDF를 Claude로 초안화하되 모든 담보 후보와 원문 근거를 보존하고, 설계사가 직접 확인한 보험만 분석·공유되도록 바꾼다. 여러 설계사가 동시에 요청해도 파일·작업·초안·확정 데이터·공유본이 서로 섞이지 않음을 PostgreSQL 경쟁 테스트와 60건 부하 시험으로 증명한다.

**Architecture:** 기존 동기 `/insurances/ocr/` 즉시저장 경로와 새 검토형 경로를 기능 스위치로 분리한다. 새 경로는 private R2 원본, PostgreSQL 작업 정본, Celery/Valkey 작업자, 줄 단위 근거를 포함한 Claude 구조화 결과, 결정론 검증기, 낙관적 초안 버전, 잠금 기반 확정 서비스로 구성한다. 분석은 중앙 `analysis_ready()` 필터와 케이스별 매핑 권위를 사용한다. 전환 배포에서 gate OFF인 동안만 과거 공유 링크 호환 조회를 유지하고, gate ON 출시 전 이를 0건으로 만든 뒤 공개 공유 링크는 불변 `ShareSnapshot`만 읽는다.

**Tech Stack:** Django 4.2/DRF/PostgreSQL, Celery 5.6 + Redis/Valkey, Cloudflare R2, Anthropic SDK의 단일 Claude 모델, Next.js 16/React 19/TypeScript/Tailwind, Vitest/Testing Library, Render web/background worker/Key Value.

## Global Constraints

- 승인 설계는 `docs/superpowers/specs/2026-07-16-insurance-extraction-accuracy-design.md`다. 기능 범위를 사진·스캔 PDF·GPT·자동 추천으로 넓히지 않는다.
- 새 파이프라인은 `core/ocr/claude_parser.py::_add_coverage`와 `_persist_ocr()`를 사용하지 않는다. 두 함수는 소액 담보를 버리고 같은 담보의 최대값만 남길 수 있어 모든 후보 보존 원칙과 충돌한다. 개인정보 마스킹, 회사 코드, 정규화 조회 같은 안전한 순수 자산만 재사용한다.
- Claude 결과는 언제나 초안이다. `planner_confirmed_source_match=true`와 미해결 항목 0건이 아니면 최종 보험을 만들거나 분석·공유에 넣지 않는다.
- 정본 연결 키는 항상 `owner_id + customer_id + job_uuid`다. 파일명, 고객명, 최근 작업, 프로세스 메모리로 결과를 연결하지 않는다.
- 모델 ID는 환경변수로만 주입한다. `claude_parser.py`, `verify.py`, `analysis/compare.py`, 설정의 모든 모델명 코드 기본값을 제거한다.
- 기능은 `INSURANCE_REVIEW_GATE_ENABLED=False`로 먼저 배포한다. 스테이징 평가와 PM 확인 전 운영에서 켜지 않는다. 운영 배포와 Render 유료 worker/Key Value 생성은 별도 PM 승인이 필요하다.
- 기존 보험은 이관 직후 `legacy_review_required`, `analysis_included=False`다. 스위치가 꺼진 동안에는 기존 화면을 유지하고, 스위치가 켜졌을 때만 새 필터를 강제해 갑작스러운 전체 분석 공백을 막는다.
- 원문 PDF, 마스킹 전 텍스트, Claude 원문 응답, 고객명, 원문 담보명은 로그·Sentry·관리자 집계에 넣지 않는다.
- 작업별 테스트는 먼저 실패를 확인하고 최소 구현 후 통과시킨다. 커밋은 아래 작업 단위로 작게 나누며, 공유 작업트리에서는 해당 작업 파일만 stage한다.

---

### Task 1: 검토형 기능 스위치와 비동기 실행 기반을 dormant 상태로 추가

**Files:**

- Modify: `inpa_be/requirements.txt`
- Create: `inpa_be/config/celery.py`
- Modify: `inpa_be/config/__init__.py`
- Modify: `inpa_be/config/settings/base.py`
- Modify: `inpa_be/config/settings/local.py`
- Modify: `inpa_be/config/settings/prod.py`
- Create: `inpa_be/inpa/core/sentry.py`
- Modify: `inpa_be/.env.example`
- Modify: `render.yaml`
- Test: `inpa_be/inpa/insurances/test_import_settings.py`

- [ ] **Step 1: 설정 계약을 먼저 테스트한다.**

```python
from django.conf import settings
from django.test import SimpleTestCase


class InsuranceImportSettingsTests(SimpleTestCase):
    def test_review_gate_is_closed_by_default(self):
        self.assertFalse(settings.INSURANCE_REVIEW_GATE_ENABLED)

    def test_model_id_has_no_code_fallback(self):
        self.assertEqual(settings.CLAUDE_MODEL_PARSE, '')

    def test_source_retention_defaults_to_24_hours(self):
        self.assertEqual(settings.INSURANCE_SOURCE_RETENTION_HOURS, 24)

    def test_document_resource_limits_are_finite(self):
        self.assertEqual(settings.INSURANCE_MAX_PAGES, 300)
        self.assertEqual(settings.INSURANCE_MAX_EXTRACTED_CHARS, 500_000)
        self.assertEqual(settings.INSURANCE_MAX_CANDIDATES, 2_000)
        self.assertEqual(settings.INSURANCE_MAX_QUEUED_PER_OWNER, 10)

    def test_celery_never_accepts_pickle(self):
        self.assertEqual(settings.CELERY_TASK_SERIALIZER, 'json')
        self.assertEqual(settings.CELERY_ACCEPT_CONTENT, ['json'])
```

- [ ] **Step 2: 실패를 확인한다.**

Run: `cd inpa_be && python manage.py test inpa.insurances.test_import_settings -v 2`

Expected: 새 설정이 없어 실패한다.

- [ ] **Step 3: Celery와 안전한 기본 설정을 추가한다.**

`requirements.txt`에는 기존 `anthropic==0.111.0`을 유지하고 `celery[redis]==5.6.3`만 추가한다. SDK 버전은 구조화 출력 계약 테스트가 현 버전에서 실패할 때만 별도 근거와 함께 변경한다.

```python
# config/celery.py
import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.local')

app = Celery('inpa')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
```

```python
# config/__init__.py
from .celery import app as celery_app

__all__ = ('celery_app',)
```

`base.py`에 다음 설정을 넣고, 실제 모델명 문자열은 두지 않는다.

```python
INSURANCE_REVIEW_GATE_ENABLED = env.bool(
    'INSURANCE_REVIEW_GATE_ENABLED', default=False)
INSURANCE_SOURCE_RETENTION_HOURS = env.int(
    'INSURANCE_SOURCE_RETENTION_HOURS', default=24)
INSURANCE_IMPORT_PER_OWNER_LIMIT = env.int(
    'INSURANCE_IMPORT_PER_OWNER_LIMIT', default=2)
INSURANCE_IMPORT_GLOBAL_LIMIT = env.int(
    'INSURANCE_IMPORT_GLOBAL_LIMIT', default=4)
INSURANCE_MAX_PAGES = env.int('INSURANCE_MAX_PAGES', default=300)
INSURANCE_MAX_EXTRACTED_CHARS = env.int(
    'INSURANCE_MAX_EXTRACTED_CHARS', default=500_000)
INSURANCE_MAX_CANDIDATES = env.int('INSURANCE_MAX_CANDIDATES', default=2_000)
INSURANCE_MAX_QUEUED_PER_OWNER = env.int(
    'INSURANCE_MAX_QUEUED_PER_OWNER', default=10)
CLAUDE_MODEL_PARSE = env('CLAUDE_MODEL_PARSE', default='')

CELERY_BROKER_URL = env('REDIS_URL', default='redis://localhost:6379/0')
CELERY_TASK_DEFAULT_QUEUE = 'insurance_imports'
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_SOFT_TIME_LIMIT = 420
CELERY_TASK_TIME_LIMIT = 480
CELERY_BROKER_TRANSPORT_OPTIONS = {'visibility_timeout': 600}
```

`InsuranceImportRuntimeConfig` 최초 생성값은 위 두 limit를 사용하고 이후 관리자 수정값을 보존한다. base/local `STORAGES`에는 `insurance_sources`라는 별도 private `FileSystemStorage`를 두고, prod에서는 기존 R2 option을 복제하되 `querystring_auth=True`, `file_overwrite=False`, `default_acl=None`을 강제한다. 원본 전용 alias가 구성되지 않으면 gate ON 접수를 fail closed 한다.

`prod.py`의 Sentry init에는 `send_default_pii=False`, `include_local_variables=False`, `before_send=inpa.core.sentry.scrub_event`를 함께 적용한다. `scrub_event`는 request body, frame vars, PDF/line/draft/provider payload 관련 extra keys를 삭제하고 job UUID·exception type·outcome enum만 남긴다.

`local.py`에서는 Redis 없이 개발할 수 있게 eager 실행을 명시한다. 단, API 테스트는 enqueue를 mock하고 worker 서비스 테스트는 함수를 직접 호출해 202 응답이 동기 완료로 바뀌지 않게 한다.

```python
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
```

- [ ] **Step 4: Render Blueprint에 web과 같은 비밀변수를 받는 Key Value, background worker, 시간별 cleanup cron을 추가한다.**

Worker command는 `celery -A config worker -l INFO -Q insurance_imports --concurrency 4`다. Key Value eviction은 `noeviction`으로 두고 web/worker에 같은 `REDIS_URL`, `DATABASE_URL`, `ANTHROPIC_API_KEY`, `CLAUDE_MODEL_PARSE`, R2 변수를 연결한다. cron command는 `python manage.py cleanup_insurance_imports`다. 실제 리소스 생성은 이 계획 실행 단계가 아니라 배포 승인 단계다.

- [ ] **Step 5: 설정 테스트와 Django check를 통과시킨다.**

Run: `cd inpa_be && python manage.py test inpa.insurances.test_import_settings -v 2 && python manage.py check`

Expected: 테스트 PASS, system check 0 issues.

- [ ] **Step 6: 커밋한다.**

```bash
git add inpa_be/requirements.txt inpa_be/config/celery.py inpa_be/config/__init__.py \
  inpa_be/config/settings/base.py inpa_be/config/settings/local.py \
  inpa_be/config/settings/prod.py inpa_be/inpa/core/sentry.py \
  inpa_be/.env.example render.yaml \
  inpa_be/inpa/insurances/test_import_settings.py
git commit -m "chore(보험): 검토 작업 큐 기반 추가"
```

### Task 2: 작업·결과·멱등 명령·확정 권위 모델을 additive migration으로 추가

**Files:**

- Modify: `inpa_be/inpa/insurances/models.py`
- Create: `inpa_be/inpa/insurances/migrations/0006_insurance_extraction_review.py`
- Modify: `inpa_be/inpa/insurances/admin.py`
- Test: `inpa_be/inpa/insurances/test_import_models.py`

- [ ] **Step 1: 모델 제약 테스트를 작성한다.**

다음 테스트명을 그대로 만든다.

```python
class InsuranceExtractionModelTests(TestCase):
    def test_same_active_hash_is_unique_only_within_owner_customer_and_portfolio(self):
        self.make_job()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.make_job()

    def test_same_hash_different_owner_creates_independent_jobs(self):
        first = self.make_job()
        second = self.make_job(owner=self.other_owner, customer=self.other_customer)
        self.assertNotEqual(first.id, second.id)

    def test_result_is_unique_per_job_and_provider(self):
        job = self.make_job()
        InsuranceExtractionResult.objects.create(job=job, provider='claude')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                InsuranceExtractionResult.objects.create(job=job, provider='claude')

    def test_idempotency_key_cannot_be_reused_with_different_request_hash(self):
        job = self.make_job()
        InsuranceImportCommand.objects.create(
            job=job, operation='patch', idempotency_key=self.command_key,
            request_sha256='a' * 64)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                InsuranceImportCommand.objects.create(
                    job=job, operation='patch', idempotency_key=self.command_key,
                    request_sha256='b' * 64)

    def test_legacy_rows_are_not_claimed_as_confirmed(self):
        insurance = CustomerInsurance.objects.create(
            customer=self.customer, portfolio_type=1)
        self.assertEqual(insurance.review_status, 'legacy_review_required')
        self.assertFalse(insurance.analysis_included)
```

`make_job()`은 setUp에서 만든 owner/customer와 고정 SHA-256을 사용하는 helper다. 같은 명령 key와 다른 request hash는 서비스 계층에서 409로 바뀌는 API 테스트도 Task 7에서 추가한다.

- [ ] **Step 2: 실패를 확인한다.**

Run: `cd inpa_be && python manage.py test inpa.insurances.test_import_models -v 2`

Expected: 신규 모델 import 실패.

- [ ] **Step 3: 모델을 추가한다.**

`InsuranceExtractionJob`은 UUID PK, owner/customer, nullable target insurance, `add|replace` intent, portfolio type, status, file hash/size/page count/safe name, private storage key/expiry/delete time, masked lines/draft/validation JSON, schema/prompt/normalization version, 시각 필드, error enum, attempt UUID/lease, attempt/lease-expiry/edit/confirmed-coverage count, draft version, target data version, create idempotency key를 가진다.

```python
class InsuranceExtractionJob(models.Model):
    ACTIVE_STATUSES = ('queued', 'extracting', 'validating', 'review_required')
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    target_insurance = models.ForeignKey(
        'CustomerInsurance', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='replacement_jobs')
    intent = models.CharField(max_length=12, choices=(('add', 'add'), ('replace', 'replace')))
    portfolio_type = models.SmallIntegerField()
    status = models.CharField(max_length=24, default='queued', db_index=True)
    file_sha256 = models.CharField(max_length=64)
    file_size = models.PositiveBigIntegerField()
    page_count = models.PositiveSmallIntegerField(null=True, blank=True)
    safe_display_name = models.CharField(max_length=120)
    source_storage_key = models.CharField(max_length=500, default='', blank=True)
    source_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    source_deleted_at = models.DateTimeField(null=True, blank=True)
    masked_lines = models.JSONField(default=list, blank=True)
    draft_payload = models.JSONField(default=dict, blank=True)
    validation_summary = models.JSONField(default=dict, blank=True)
    schema_version = models.CharField(max_length=40, default='')
    prompt_version = models.CharField(max_length=40, default='')
    normalization_version = models.CharField(max_length=40, default='')
    attempt_uuid = models.UUIDField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    lease_expired_count = models.PositiveSmallIntegerField(default=0)
    planner_edit_count = models.PositiveIntegerField(default=0)
    confirmed_coverage_count = models.PositiveIntegerField(default=0)
    draft_version = models.PositiveIntegerField(default=1)
    target_insurance_version = models.PositiveIntegerField(null=True, blank=True)
    create_idempotency_key = models.UUIDField(null=True, blank=True)
    error_code = models.CharField(max_length=40, default='', blank=True)
    error_type = models.CharField(max_length=40, default='', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    canceled_at = models.DateTimeField(null=True, blank=True)
```

Migration에는 활성 상태 조건부 unique `(owner, customer, file_sha256, portfolio_type)`, 값이 있는 `(owner, create_idempotency_key)`, owner/customer/status와 lease 인덱스를 넣는다. 상태 문자열은 migration에 고정해 런타임 상수 import로 과거 migration이 변하지 않게 한다.

`InsuranceExtractionResult`는 `(job, provider)` unique이고, 구조화 payload와 PII 없는 메트릭만 가진다. `InsuranceImportCommand`는 `(job, operation, idempotency_key)` unique, request SHA-256, response status/body를 저장해 PATCH/confirm 재전송을 재생한다.

`InsuranceImportRuntimeConfig` singleton은 `per_owner_concurrency`, `global_concurrency`, `force_manual_carrier_codes`를 가진다. seed 삭제/재생성 없이 `solo()`로 읽고, Django Admin에서 PM이 재배포 없이 조절한다. 기능 게이트 자체는 출시 경계이므로 env read-only를 유지한다.

`CustomerInsurance`에는 다음을 추가한다.

```python
review_status = models.CharField(max_length=32, default='legacy_review_required')
source_job = models.OneToOneField(
    'InsuranceExtractionJob', on_delete=models.SET_NULL,
    null=True, blank=True, related_name='confirmed_insurance')
confirmed_at = models.DateTimeField(null=True, blank=True)
confirmed_by = models.ForeignKey(
    settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
analysis_included = models.BooleanField(default=False)
confirmation_source = models.CharField(max_length=24, default='')
data_version = models.PositiveIntegerField(default=1)
```

`CustomerInsuranceDetail`에는 source page/line/text, JSON review reasons, mapping source, M2M `analysis_detail_override`, confirmed time를 추가하고 `effective_analysis_details()`를 정의한다.

```python
def effective_analysis_details(self):
    if self.mapping_source in {'planner_override', 'manual'}:
        return self.analysis_detail_override.all()
    return self.detail.analysis_detail.all()
```

- [ ] **Step 4: 데이터 migration의 정직한 기본값을 검증한다.**

기존 행은 `legacy_review_required`, `analysis_included=False`, `confirmation_source=''`다. 기존 자료를 자동으로 confirmed로 올리지 않는다. 신규 수동 입력도 최종 확인 전에는 같은 상태다.

- [ ] **Step 5: migration과 모델 테스트를 통과시킨다.**

Run: `cd inpa_be && python manage.py makemigrations --check --dry-run && python manage.py test inpa.insurances.test_import_models -v 2`

Expected: 새 migration 누락 없음, 테스트 PASS.

- [ ] **Step 6: 커밋한다.**

```bash
git add inpa_be/inpa/insurances/models.py \
  inpa_be/inpa/insurances/migrations/0006_insurance_extraction_review.py \
  inpa_be/inpa/insurances/admin.py inpa_be/inpa/insurances/test_import_models.py
git commit -m "feat(보험): 검토 작업과 확정 권위 모델 추가"
```

### Task 3: PDF 줄 근거·후보 보존·private 원본 저장 계약 구현

**Files:**

- Create: `inpa_be/inpa/insurances/import_contract.py`
- Create: `inpa_be/inpa/insurances/import_pdf.py`
- Create: `inpa_be/inpa/insurances/import_storage.py`
- Test: `inpa_be/inpa/insurances/test_import_pdf.py`
- Test: `inpa_be/inpa/insurances/test_import_storage.py`

- [ ] **Step 1: PDF 헤더, 줄 ID, 후보 보존, 저장 키 격리 테스트를 작성한다.**

필수 테스트:

- `.pdf` 확장자여도 `%PDF-` 헤더가 아니면 `INVALID_PDF`
- 암호화 PDF는 `ENCRYPTED_PDF`, 이미지 PDF는 `IMAGE_PDF`
- 301페이지는 `TOO_MANY_PAGES`, 마스킹 줄 합계 500,001자는 `DOCUMENT_TOO_LONG`, 후보 2,001개는 `TOO_MANY_CANDIDATES`
- 각 줄 ID가 `p03-l014` 형태이고 페이지·줄 번호가 안정적
- 마스킹 전 텍스트는 반환·저장 계약에 없음
- 서로 다른 owner/customer/job의 key가 절대 같지 않음
- 한 job 삭제가 정확한 key 한 개에만 호출됨

- [ ] **Step 2: 실패를 확인한다.**

Run: `cd inpa_be && python manage.py test inpa.insurances.test_import_pdf inpa.insurances.test_import_storage -v 2`

Expected: 신규 모듈 import 실패.

- [ ] **Step 3: 명시적 데이터 계약을 만든다.**

```python
@dataclass(frozen=True)
class MaskedLine:
    line_id: str
    page: int
    line: int
    text_masked: str


@dataclass(frozen=True)
class CoverageCandidate:
    candidate_id: str
    evidence_line_ids: tuple[str, ...]
    text_masked: str
```

`extract_pdf()`는 스트리밍 SHA-256, magic bytes, 50MB, 암호화, 최대 300페이지, 마스킹 후 최대 500,000자, 최대 후보 2,000개, 페이지별 텍스트 존재를 검증한다. 상한을 넘으면 일부만 잘라 Claude에 보내지 않고 안전 오류로 끝낸다. `_strip_identity` 후의 `MaskedLine`만 영속화하고, 금액·기간·담보 표제 패턴으로 잡은 모든 `CoverageCandidate`를 별도 목록으로 반환한다. 후보 검출이 확신하지 못한 행도 버리지 않고 `needs_review` 후보로 남긴다.

- [ ] **Step 4: 저장 키와 삭제 가드를 구현한다.**

```python
def source_key(job):
    return (
        f'insurance-imports/{job.owner_id}/{job.customer_id}/'
        f'{job.id}/source.pdf'
    )


def assert_source_namespace(job, key):
    if key != source_key(job):
        raise SourceNamespaceMismatch
```

`storages['insurance_sources']`를 통해 private R2를 사용한다. 저장과 삭제 전에 namespace를 검증하고 prefix 일괄 삭제 API는 만들지 않는다. source storage key는 어떤 serializer에도 포함하지 않는다.

- [ ] **Step 5: 테스트를 통과시킨다.**

Run: `cd inpa_be && python manage.py test inpa.insurances.test_import_pdf inpa.insurances.test_import_storage -v 2`

Expected: 테스트 PASS.

- [ ] **Step 6: 커밋한다.**

```bash
git add inpa_be/inpa/insurances/import_contract.py \
  inpa_be/inpa/insurances/import_pdf.py inpa_be/inpa/insurances/import_storage.py \
  inpa_be/inpa/insurances/test_import_pdf.py inpa_be/inpa/insurances/test_import_storage.py
git commit -m "feat(보험): PDF 근거와 작업별 원본 격리 추가"
```

### Task 4: 모든 담보 후보를 보존하는 단일 Claude 추출 어댑터와 결정론 검증기 구현

**Files:**

- Create: `inpa_be/inpa/insurances/import_claude.py`
- Create: `inpa_be/inpa/insurances/import_validation.py`
- Modify: `inpa_be/inpa/core/ocr/claude_parser.py`
- Modify: `inpa_be/inpa/insurances/verify.py`
- Modify: `inpa_be/inpa/analysis/compare.py`
- Test: `inpa_be/inpa/insurances/test_import_claude.py`
- Test: `inpa_be/inpa/insurances/test_import_validation.py`

- [ ] **Step 1: 추출 계약과 재시도 정책 테스트를 먼저 작성한다.**

필수 테스트:

- 모델 env가 비면 Claude를 호출하지 않고 `MODEL_NOT_CONFIGURED`
- 모든 추출 필드에 `evidence_line_ids`가 없으면 schema 실패
- 문서 속 명령문은 데이터로만 취급하는 system prompt 포함
- timeout/network/429/5xx만 1, 2, 4초로 최대 3회
- 400/401/403은 1회 후 종료
- SDK 자체 retry는 0
- 로그 레코드에 lines/prompt/raw response 없음

- [ ] **Step 2: 검증기 테스트를 작성한다.**

```python
def test_candidate_conservation_created_unmatched_excluded_equals_detected():
    result = validate_draft(lines, candidates, provider_payload)
    assert result.summary['detected_candidates'] == (
        result.summary['assigned']
        + result.summary['unmatched']
        + result.summary['intentionally_excluded']
    )


def test_value_without_matching_evidence_is_no_evidence():
    assert issue.state == 'no_evidence'


def test_validator_flags_date_order_duplicate_and_premium_mismatch():
    assert {item.code for item in result.issues} == {
        'CONTRACT_AFTER_EXPIRY', 'DUPLICATE_SOURCE_ROW', 'PREMIUM_SUM_MISMATCH'
    }
```

- [ ] **Step 3: 실패를 확인한다.**

Run: `cd inpa_be && python manage.py test inpa.insurances.test_import_claude inpa.insurances.test_import_validation -v 2`

Expected: 신규 모듈 import 실패.

- [ ] **Step 4: 새 Claude JSON Schema를 구현한다.**

새 응답은 `policy`와 `coverage_rows[]`를 가진다. 각 row는 `row_id`, 원문명, 가입금액, 보험료, 갱신·기간, `source_candidate_ids`, `evidence_line_ids`를 포함한다. `confidence` 필드는 만들지 않는다. 로컬 후보 중 Claude가 응답하지 않은 후보도 서버가 `unmatched/needs_review` 행으로 되살린다.

```python
def extract(masked_lines, candidates, schema_version):
    model = settings.CLAUDE_MODEL_PARSE
    if not model:
        raise ExtractionFailure('MODEL_NOT_CONFIGURED')
    client = anthropic.Anthropic(
        api_key=settings.ANTHROPIC_API_KEY, max_retries=0)
    return _call_with_retry(
        client=client,
        model=model,
        masked_lines=masked_lines,
        candidates=candidates,
        schema_version=schema_version,
    )
```

현재 SDK의 strict structured-output 파라미터를 사용하고 SDK signature 계약 테스트로 고정한다. 새 흐름은 legacy `claude_parse()`와 `_add_coverage()`를 호출하지 않는다.

- [ ] **Step 5: 결정론 검증기를 구현한다.**

검증기는 날짜 순서, 음수, 쉼표/원/만원 단위의 근거 숫자 일치, 같은 source candidate 중복, 후보 보존식, 비교 가능한 보험료 합계, 갱신·납입 조합, 보험사/보험종류 모순을 검사한다. 값을 자동 수정하지 않고 `review_ready|needs_review|no_evidence|unmatched|invalid|manual` 상태와 code를 만든다.

- [ ] **Step 6: 기존 모든 모델 fallback을 제거한다.**

`claude_parser.py`, `verify.py`, `analysis/compare.py`, `base.py`에서 실제 모델명 문자열을 제거하고 env 미설정 시 fail closed 한다. 기존 동기 경로의 회귀 테스트도 함께 수정한다.

- [ ] **Step 7: 테스트를 통과시킨다.**

Run: `cd inpa_be && python manage.py test inpa.insurances.test_import_claude inpa.insurances.test_import_validation inpa.insurances.tests -v 2`

Expected: 신규 테스트와 기존 OCR 회귀 테스트 PASS.

- [ ] **Step 8: 커밋한다.**

```bash
git add inpa_be/inpa/insurances/import_claude.py \
  inpa_be/inpa/insurances/import_validation.py \
  inpa_be/inpa/core/ocr/claude_parser.py inpa_be/inpa/insurances/verify.py \
  inpa_be/inpa/analysis/compare.py inpa_be/inpa/insurances/test_import_claude.py \
  inpa_be/inpa/insurances/test_import_validation.py
git commit -m "feat(보험): 근거 기반 Claude 초안 검증 추가"
```

### Task 5: 업로드 접수·중복 수렴·작업 조회·원본 단기 URL API 구현

**Files:**

- Create: `inpa_be/inpa/insurances/import_serializers.py`
- Create: `inpa_be/inpa/insurances/import_views.py`
- Create: `inpa_be/inpa/insurances/import_services.py`
- Modify: `inpa_be/config/settings/base.py`
- Modify: `inpa_be/inpa/insurances/urls.py`
- Modify: `inpa_be/inpa/insurances/views.py`
- Test: `inpa_be/inpa/insurances/test_import_api.py`

- [ ] **Step 1: API 계약 테스트를 작성한다.**

계약:

```text
POST /api/v1/customers/<id>/insurance-imports/
GET  /api/v1/customers/<id>/insurance-imports/
GET  /api/v1/insurance-imports/<job_id>/
GET  /api/v1/insurance-imports/<job_id>/source-url/
GET  /api/v1/insurance-imports/config/
```

필수 테스트:

- 현재 버전 고객 본인 동의가 없으면 저장·enqueue 전에 412
- 유효 PDF는 `202 {job_id,status:'queued'}`
- 같은 active hash는 같은 job을 202로 반환하고 재차감·재저장·재enqueue하지 않음
- review_required job의 24시간 원본만 삭제된 뒤 같은 PDF를 다시 고르면 기존 초안에 exact source key와 새 만료시각만 연결하고 재Claude·재차감하지 않음
- 같은 confirmed hash는 `409 DUPLICATE_CONFIRMED`와 기존 insurance id/version, 허용 의도 `add|replace` 반환
- 같은 idempotency key/같은 body는 동일 응답, 다른 body는 409
- customer list는 해당 owner/customer 작업만 반환
- foreign job status/source는 모두 404
- source URL 응답은 짧은 만료, storage key 비노출, `private, no-store`
- local/test storage도 5분 Django-signed preview token으로 동작하고 위조·만료·삭제 source는 404
- config는 `review_workflow_enabled`, `accepted_input='digital_pdf'`, `max_file_bytes=52428800`만 반환하고 모델·storage·비밀값은 반환하지 않음
- create는 기존 user별 `ocr` throttle 20/hour와 queued cap 10을 모두 적용하고, source URL은 `insurance_import_source` 120/hour, 나머지 owner API는 `insurance_import` 600/hour를 적용
- throttle/queued cap 초과는 Claude·storage 전에 429이며 같은 owner의 active duplicate 조회는 기존 job을 반환
- 기능 스위치 OFF에서는 신규 접수 404, 기존 `/ocr/` 동작 유지
- 기능 스위치 ON에서는 기존 `/ocr/`가 즉시저장 우회로가 되지 않고 신규 접수 서비스로 위임

- [ ] **Step 2: 실패를 확인한다.**

Run: `cd inpa_be && python manage.py test inpa.insurances.test_import_api -v 2`

Expected: route 404 또는 import 실패.

- [ ] **Step 3: 접수 서비스를 구현한다.**

접수는 owner/customer 검증, 동의, PDF preflight, SHA-256, 중복/멱등 확인, queued cap, credit check, job 생성, exact key 저장을 한 서비스에 둔다. 중복 검사를 throttle 이후, queued cap과 credit보다 먼저 실행한다. 기존 review_required job의 source만 만료된 경우에는 같은 hash를 확인한 뒤 새 exact key와 `source_expires_at`만 원자적으로 연결하고 기존 draft를 그대로 반환한다. DB commit 후에만 `transaction.on_commit(lambda: process_insurance_import.delay(str(job.id)))`를 호출한다. broker publish 실패 시 job을 `QUEUE_UNAVAILABLE`로 만들고 exact key만 삭제하며, 사용량 환불은 한 번만 수행한다.

`REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']`에는 기존 `ocr: 20/hour`를 유지하고 `insurance_import: 600/hour`, `insurance_import_source: 120/hour`를 추가한다. create view는 `throttle_scope='ocr'`, status/list/draft/PATCH/confirm/cancel은 `insurance_import`, source-url 발급은 `insurance_import_source`를 사용한다.

- [ ] **Step 4: owner 인증 후 5분짜리 원본 URL을 반환한다.**

직접 storage key는 반환하지 않는다. R2 signed URL은 300초 만료와 `ResponseContentDisposition=inline`, `ResponseCacheControl=private,no-store`를 사용한다. FE iframe은 localStorage 토큰을 헤더로 보낼 수 없으므로 owner-authenticated API가 signed URL을 먼저 발급해야 한다. local/test FileSystemStorage는 job UUID와 source key digest만 담은 Django-signed token을 발급하고 `/insurance-imports/source/<token>/`에서 `max_age=300`, source 미삭제, namespace 일치를 재검증한 뒤 `FileResponse`로 보낸다. 이 응답도 `Cache-Control: private, no-store`, `Content-Disposition: inline`, frame 허용 CSP를 명시한다.

- [ ] **Step 5: 테스트를 통과시킨다.**

Run: `cd inpa_be && python manage.py test inpa.insurances.test_import_api -v 2`

Expected: 모든 상태·소유권·중복 테스트 PASS.

- [ ] **Step 6: 커밋한다.**

```bash
git add inpa_be/inpa/insurances/import_serializers.py \
  inpa_be/inpa/insurances/import_views.py inpa_be/inpa/insurances/import_services.py \
  inpa_be/config/settings/base.py \
  inpa_be/inpa/insurances/urls.py inpa_be/inpa/insurances/views.py \
  inpa_be/inpa/insurances/test_import_api.py
git commit -m "feat(보험): 멱등 업로드 작업 API 추가"
```

### Task 6: worker claim·사용자별 공정성·attempt CAS·lease 복구 구현

**Files:**

- Create: `inpa_be/inpa/insurances/tasks.py`
- Modify: `inpa_be/inpa/insurances/import_services.py`
- Create: `inpa_be/inpa/insurances/management/commands/cleanup_insurance_imports.py`
- Test: `inpa_be/inpa/insurances/test_import_worker.py`

- [ ] **Step 1: 상태 전이와 늦은 worker 차단 테스트를 작성한다.**

필수 테스트명:

```text
test_worker_refetches_owner_customer_and_key_from_database
test_late_attempt_cas_cannot_overwrite_new_attempt
test_per_owner_limit_is_checked_under_owner_row_lock
test_different_owners_can_run_in_parallel
test_transport_retry_does_not_consume_credit_twice
test_worker_rechecks_current_consent_immediately_before_claude
test_consent_revoked_while_queued_never_calls_claude
test_resource_limit_failure_refunds_credit_once
test_empty_coverage_result_is_failed_not_review_required
test_cleanup_recovers_expired_lease
test_cleanup_deletes_expired_review_required_source_but_keeps_draft
test_cleanup_deletes_only_exact_expired_source_key
test_worker_exception_sentry_event_contains_no_lines_or_payload
```

- [ ] **Step 2: 실패를 확인한다.**

Run: `cd inpa_be && python manage.py test inpa.insurances.test_import_worker -v 2`

Expected: task import 실패.

- [ ] **Step 3: claim을 DB 잠금으로 구현한다.**

작업자는 메시지의 job UUID만 받는다. transaction 안에서 job, `InsuranceImportRuntimeConfig`, owner User row를 순서대로 잠그고, 전체 active lease와 해당 owner의 만료되지 않은 active lease가 runtime limit 미만일 때만 새 attempt UUID와 lease를 기록한다. 한도면 개인정보 없는 countdown으로 retry한다.

```python
updated = InsuranceExtractionJob.objects.filter(
    id=job_id,
    attempt_uuid=attempt_id,
    status=expected_status,
).update(status=next_status, **safe_fields)
if updated != 1:
    raise StaleAttempt
```

Claude 입력·응답은 task 지역 변수로만 두고 모듈 전역 캐시를 만들지 않는다. owner/customer/key namespace가 DB와 맞지 않으면 `SOURCE_NAMESPACE_MISMATCH`로 종료한다.

claim 후 PDF를 읽더라도 Claude 호출 직전에 `has_current_overseas_consent(job.customer)`를 다시 조회한다. 업로드 후 대기 중 철회·문서 버전 변경이 감지되면 `CONSENT_REVOKED_BEFORE_TRANSFER`로 멈추고 Claude client 호출 0건, credit 1회 환불, draft 미생성을 보장한다.

- [ ] **Step 4: queued → extracting → validating → review_required 전이를 구현한다.**

PDF 줄 추출, Claude 어댑터, 결정론 검증은 각각 분리 호출한다. `InsuranceExtractionResult`와 job 초안 저장은 현재 attempt CAS가 성공할 때만 반영한다. 감지 담보 0건, schema 실패, API 실패는 보험 레코드를 만들지 않고 safe error code로 failed 처리한다. 페이지·문자·후보 상한은 Claude 호출 전에 실패하고 credit을 정확히 한 번 환불한다.

검출 carrier code가 RuntimeConfig의 `force_manual_carrier_codes`에 있으면 모든 coverage row를 `needs_review`로 올리고 `CARRIER_MANUAL_REVIEW` 사유를 추가한다. 값을 바꾸거나 삭제하지 않으며, 다음 claim부터 관리자 설정 변경이 반영된다.

- [ ] **Step 5: cleanup을 다중 삭제 가드로 구현한다.**

시스템 `source_expires_at <= now` AND `source_deleted_at is null` AND (live lease가 없거나 lease가 만료됨) 조건이면 job 상태와 무관하게 exact key를 삭제하고 `source_deleted_at`을 찍는다. `review_required`의 draft와 validation은 보존해 같은 hash 재업로드로 원본만 다시 연결할 수 있게 한다. active lease가 만료되면 attempt를 먼저 무효화한 뒤 exact source를 삭제하고, 재시도 가능 상태는 queued로 되돌리거나 최대 재시도 후 failed 처리한다.

worker 예외 로그는 job UUID, exception type, outcome enum만 남긴다. Sentry capture 테스트는 sentinel 고객명·마스킹 줄·structured payload를 local variable과 extra에 넣고 전송 event 직렬화 어디에도 sentinel이 없음을 assert한다.

- [ ] **Step 6: 테스트를 통과시킨다.**

Run: `cd inpa_be && python manage.py test inpa.insurances.test_import_worker -v 2`

Expected: CAS·공정성·cleanup 테스트 PASS.

- [ ] **Step 7: 커밋한다.**

```bash
git add inpa_be/inpa/insurances/tasks.py \
  inpa_be/inpa/insurances/import_services.py \
  inpa_be/inpa/insurances/management/commands/cleanup_insurance_imports.py \
  inpa_be/inpa/insurances/test_import_worker.py
git commit -m "feat(보험): 격리된 추출 worker와 lease 복구 추가"
```

### Task 7: 초안 조회·수정·취소와 명령 멱등성 API 구현

**Files:**

- Modify: `inpa_be/inpa/insurances/import_serializers.py`
- Modify: `inpa_be/inpa/insurances/import_views.py`
- Modify: `inpa_be/inpa/insurances/import_services.py`
- Modify: `inpa_be/inpa/insurances/urls.py`
- Test: `inpa_be/inpa/insurances/test_import_draft_api.py`

- [ ] **Step 1: 초안 API 테스트를 먼저 작성한다.**

계약:

```text
GET   /api/v1/insurance-imports/<job_id>/draft/
PATCH /api/v1/insurance-imports/<job_id>/draft/
POST  /api/v1/insurance-imports/<job_id>/cancel/
```

필수 테스트:

- `review_required` 전에는 draft GET이 409 `DRAFT_NOT_READY`
- 응답에 `draft_version`, policy, 모든 coverage row, validation issues, 표준 담보 선택지와 버전, unresolved count 포함
- storage key, raw Claude response, 마스킹 전 텍스트 비포함
- PATCH는 `draft_version`과 `Idempotency-Key` 필수
- 같은 key/같은 request hash는 저장된 응답 재생, 같은 key/다른 body는 409
- 오래된 version은 409 `DRAFT_VERSION_CHANGED`와 current version 반환
- 수정·표준 위치 배정·분석 제외·중복 제외·제외 취소 후 검증기를 다시 실행
- 제외는 사유 필수, 중복 제외는 대상 row 필수
- foreign draft/PATCH/cancel은 404
- canceled job은 다시 수정·확정할 수 없으며 exact source key만 삭제 예약

- [ ] **Step 2: 실패를 확인한다.**

Run: `cd inpa_be && python manage.py test inpa.insurances.test_import_draft_api -v 2`

Expected: route 또는 serializer 부재로 실패.

- [ ] **Step 3: 검토 응답 스키마를 고정한다.**

```json
{
  "job_id": "uuid",
  "customer_id": 1,
  "status": "review_required",
  "draft_version": 3,
  "policy": {
    "company_code": 6,
    "product_name": {"value": "무배당 건강보험", "state": "review_ready", "evidence_line_ids": ["p01-l004"]},
    "monthly_premium": {"value": 124000, "state": "needs_review", "evidence_line_ids": ["p02-l011"]}
  },
  "coverages": [],
  "validation": {"unresolved_count": 2, "issues": []},
  "standard_coverages": {"version": "seed-version", "items": []}
}
```

표준 담보 선택지는 별도 전역 최신 조회가 아니라 초안의 `normalization_version`과 같은 버전으로 응답한다. route의 customer id는 화면 문맥일 뿐 API 권위가 아니며 응답 customer id와 불일치하면 FE가 안전 오류로 처리한다.

- [ ] **Step 4: PATCH를 row 단위 allowlist로 구현한다.**

클라이언트가 전체 `draft_payload`를 덮어쓰지 못하게 policy 허용 필드와 coverage row 허용 동작만 serializer로 받는다. 서버가 evidence와 원본 candidate id를 유지하고, planner edit에는 `manual` 상태와 edit counter를 기록한다. PATCH 후 항상 `validate_draft()`를 다시 실행하고 `draft_version=F('draft_version')+1`을 조건부 update한다.

- [ ] **Step 5: 테스트를 통과시킨다.**

Run: `cd inpa_be && python manage.py test inpa.insurances.test_import_draft_api -v 2`

Expected: 버전·멱등·소유권·행 보존 테스트 PASS.

- [ ] **Step 6: 커밋한다.**

```bash
git add inpa_be/inpa/insurances/import_serializers.py \
  inpa_be/inpa/insurances/import_views.py inpa_be/inpa/insurances/import_services.py \
  inpa_be/inpa/insurances/urls.py inpa_be/inpa/insurances/test_import_draft_api.py
git commit -m "feat(보험): 버전 기반 검토 초안 API 추가"
```

### Task 8: 설계사 확인 확정·교체 충돌·직접 입력 담보 CRUD 구현

**Files:**

- Modify: `inpa_be/inpa/insurances/import_services.py`
- Modify: `inpa_be/inpa/insurances/import_serializers.py`
- Modify: `inpa_be/inpa/insurances/import_views.py`
- Modify: `inpa_be/inpa/insurances/views.py`
- Modify: `inpa_be/inpa/insurances/serializers.py`
- Modify: `inpa_be/inpa/insurances/urls.py`
- Test: `inpa_be/inpa/insurances/test_import_confirm.py`
- Test: `inpa_be/inpa/insurances/test_manual_review.py`

- [ ] **Step 1: 확정 차단과 원자성 테스트를 작성한다.**

필수 테스트명:

```text
test_confirmation_requires_planner_source_checkbox
test_unresolved_candidate_blocks_confirmation
test_no_evidence_amount_blocks_confirmation
test_stale_draft_version_returns_409
test_confirm_rollback_leaves_no_partial_insurance
test_confirm_is_idempotent_for_same_command_key
test_different_request_with_same_command_key_returns_409
test_confirmed_insurance_preserves_source_evidence
test_confirm_does_not_mutate_global_mapping
test_replace_marks_old_insurance_superseded_after_new_is_complete
test_target_data_version_change_returns_import_target_changed
```

- [ ] **Step 2: 직접 입력 테스트를 작성한다.**

수동 보험 생성은 확인 전 `analysis_included=False`다. owner는 기본정보와 담보 행을 추가·수정·삭제하고 표준 위치를 직접 배정할 수 있다. 마지막 `/confirm/`에서 같은 검증기를 거쳐야 confirmed가 된다. 타 설계사 보험·담보는 모든 동작에서 404다.

- [ ] **Step 3: 실패를 확인한다.**

Run: `cd inpa_be && python manage.py test inpa.insurances.test_import_confirm inpa.insurances.test_manual_review -v 2`

Expected: confirm/manual coverage route 부재로 실패.

- [ ] **Step 4: 확정 서비스를 하나의 transaction으로 구현한다.**

```python
@transaction.atomic
def confirm_import(*, job_id, owner, draft_version, target_version,
                   planner_confirmed_source_match):
    if planner_confirmed_source_match is not True:
        raise ImportConflict('SOURCE_CONFIRMATION_REQUIRED')
    job = (InsuranceExtractionJob.objects.select_for_update()
           .select_related('customer', 'target_insurance')
           .get(id=job_id, owner=owner, customer__owner=owner))
    customer = Customer.objects.select_for_update().get(
        id=job.customer_id, owner=owner)
    validate_confirmable(job, draft_version)
    target = lock_and_validate_target(job, target_version)
    insurance = materialize_confirmed_insurance(job, customer, owner)
    if target is not None:
        target.review_status = 'superseded'
        target.analysis_included = False
        target.data_version = F('data_version') + 1
        target.save(update_fields=['review_status', 'analysis_included', 'data_version'])
    job.status = 'confirmed'
    job.confirmed_at = timezone.now()
    job.confirmed_coverage_count = insurance.case_list.count()
    job.save(update_fields=['status', 'confirmed_at', 'confirmed_coverage_count'])
    transaction.on_commit(lambda: delete_exact_source.delay(str(job.id)))
    return insurance
```

`materialize_confirmed_insurance()`는 모든 final row를 만든 뒤 기존 8-case 계산을 호출한다. 하나라도 실패하면 새 보험, 담보, supersede, job status가 모두 rollback된다. target 교체는 현재 `data_version`과 job의 캡처 version이 같을 때만 성공한다.

- [ ] **Step 5: 직접 입력 API를 확장한다.**

```text
POST   /customers/<customer_id>/insurances/manual/
PATCH  /customers/<customer_id>/insurances/manual/<insurance_id>/
POST   /customers/<customer_id>/insurances/manual/<insurance_id>/coverages/
PATCH  /customers/<customer_id>/insurances/manual/<insurance_id>/coverages/<case_id>/
DELETE /customers/<customer_id>/insurances/manual/<insurance_id>/coverages/<case_id>/
POST   /customers/<customer_id>/insurances/manual/<insurance_id>/confirm/
```

수동 coverage는 `mapping_source='manual'`, 원문 근거는 없음, 설계사 최종 확인 전 `manual` 상태다. 금액·표준 위치·기간 조합 검증은 import confirm과 같은 순수 validator를 사용한다.

- [ ] **Step 6: 테스트를 통과시킨다.**

Run: `cd inpa_be && python manage.py test inpa.insurances.test_import_confirm inpa.insurances.test_manual_review -v 2`

Expected: rollback·교체 충돌·수동 확인 테스트 PASS.

- [ ] **Step 7: 커밋한다.**

```bash
git add inpa_be/inpa/insurances/import_services.py \
  inpa_be/inpa/insurances/import_serializers.py inpa_be/inpa/insurances/import_views.py \
  inpa_be/inpa/insurances/views.py inpa_be/inpa/insurances/serializers.py \
  inpa_be/inpa/insurances/urls.py inpa_be/inpa/insurances/test_import_confirm.py \
  inpa_be/inpa/insurances/test_manual_review.py
git commit -m "feat(보험): 원자적 검토 확정과 담보 직접 입력 추가"
```

### Task 9: 확정·포함·정상 보험만 분석하고 케이스별 매핑 override를 사용

**Files:**

- Modify: `inpa_be/inpa/insurances/models.py`
- Modify: `inpa_be/inpa/analysis/calculate.py`
- Modify: `inpa_be/inpa/analysis/views.py`
- Modify: `inpa_be/inpa/analysis/compare.py`
- Modify: `inpa_be/inpa/analytics/views.py`
- Modify: `inpa_be/inpa/insurances/serializers.py`
- Test: `inpa_be/inpa/analysis/tests.py`
- Test: `inpa_be/inpa/analytics/tests.py`

- [ ] **Step 1: 중앙 분석 대상 필터 테스트를 작성한다.**

`AnalysisEligibilityGateTests`에서 `legacy_review_required`, `excluded`, `superseded`, `analysis_included=False`, `is_cancelled=True`를 각각 만들고 gate ON에서 합계 제외를 확인한다. confirmed+included+정상만 포함한다. `?insurance_id=<미확정>`도 404여야 한다. gate OFF에서는 기존 fixture 분석이 그대로 유지되어야 한다.

- [ ] **Step 2: 케이스별 override 격리 테스트를 작성한다.**

A/B 고객이 같은 global `InsuranceDetail`을 사용하게 한 뒤 A case만 override한다. A 합계만 새 분석 위치로 이동하고 B와 global M2M은 변하지 않아야 한다. share payload와 compare도 같은 effective mapping을 사용해야 한다.

- [ ] **Step 3: 실패를 확인한다.**

Run:

```bash
cd inpa_be
python manage.py test \
  inpa.analysis.tests.AnalysisEligibilityGateTests \
  inpa.analysis.tests.CaseMappingOverrideTests -v 2
```

Expected: 미확정 보험 포함 또는 override 무시로 실패.

- [ ] **Step 4: `CustomerInsuranceQuerySet.analysis_ready()`를 단일 권위로 추가한다.**

```python
class CustomerInsuranceQuerySet(models.QuerySet):
    def analysis_ready(self):
        qs = self.filter(is_cancelled=False).exclude(review_status='superseded')
        if settings.INSURANCE_REVIEW_GATE_ENABLED:
            qs = qs.filter(review_status='confirmed', analysis_included=True)
        return qs
```

`portfolio_type`은 helper에 넣지 않는다. 히트맵/share는 `.analysis_ready().filter(portfolio_type=1)`, compare는 보유·제안을 명시 ID로 고르되 `.analysis_ready()`를 통과시킨다.

- [ ] **Step 5: 계산기의 전역 매핑 접근을 effective mapping으로 바꾼다.**

```python
analysis_detail_id_list = list(
    case.effective_analysis_details().values_list('id', flat=True))
```

모든 대상 query는 다음 세 prefetch를 포함한다.

```python
'case_list__detail__analysis_detail',
'case_list__analysis_detail_override',
'case_list__detail__chart_detail',
```

- [ ] **Step 6: 분석 응답에 상태 요약을 추가한다.**

`included_insurance_count`, `excluded_insurance_count`, `last_confirmed_at`, `pending_review_count`, `can_share`, `share_block_reason`를 반환해 FE가 서버 권위와 같은 이유를 표시하게 한다.

- [ ] **Step 7: 테스트를 통과시킨다.**

Run: `cd inpa_be && python manage.py test inpa.analysis inpa.analytics -v 2`

Expected: 신규 gate/override와 기존 계산 회귀 테스트 PASS.

- [ ] **Step 8: 커밋한다.**

```bash
git add inpa_be/inpa/insurances/models.py inpa_be/inpa/analysis/calculate.py \
  inpa_be/inpa/analysis/views.py inpa_be/inpa/analysis/compare.py \
  inpa_be/inpa/analytics/views.py inpa_be/inpa/insurances/serializers.py \
  inpa_be/inpa/analysis/tests.py inpa_be/inpa/analytics/tests.py
git commit -m "feat(분석): 확인된 보험과 개별 매핑만 합산"
```

### Task 10: ShareSnapshot을 공개 링크의 유일한 권위로 전환

**Files:**

- Modify: `inpa_be/inpa/analytics/models.py`
- Create: `inpa_be/inpa/analytics/migrations/0004_share_snapshot_token_authority.py`
- Create: `inpa_be/inpa/analytics/sharing.py`
- Create: `inpa_be/inpa/analytics/management/__init__.py`
- Create: `inpa_be/inpa/analytics/management/commands/__init__.py`
- Create: `inpa_be/inpa/analytics/management/commands/audit_share_snapshot_links.py`
- Modify: `inpa_be/inpa/analytics/views.py`
- Modify: `inpa_be/inpa/analytics/urls.py`
- Modify: `inpa_be/inpa/customers/public_consent.py`
- Modify: `inpa_be/inpa/notifications/jobs.py`
- Test: `inpa_be/inpa/analytics/tests.py`
- Test: `inpa_be/inpa/customers/tests.py`
- Test: `inpa_be/inpa/notifications/tests.py`

- [ ] **Step 1: 링크 원자성·불변성·수명 테스트를 작성한다.**

필수 테스트:

- payload build 실패 시 token/snapshot/event 모두 0건
- 발급 후 보험·담보·전역 트리를 바꿔도 `/s/<token>`의 분석 본문은 동일
- 새 링크 발급 시 이전 링크 404
- explicit revoke, 만료, 동의 철회, 고객 삭제 후 404
- 공개 event도 revoked/expired token이면 404
- 첫 열람은 해당 snapshot의 `first_viewed_at`만 기록
- 다른 설계사의 snapshot/token/event 교차 귀속 0
- share 생성 시 미확정 포함 보험이 있으면 안전한 409, 링크 미생성
- snapshot 없는 legacy Customer token과 live booking URL을 포함한 legacy snapshot 수를 dry-run으로 집계하고 임의 현재 payload backfill을 하지 않음

- [ ] **Step 2: 예약 CTA 수명 회귀 테스트를 별도로 작성한다.**

현재 booking token은 72시간, 공유 링크는 90일이다. snapshot에 `booking_url`을 얼리면 4일째 CTA가 죽는다. 분석 본문과 실시간 행동을 분리한다.

```python
def test_share_analysis_payload_is_frozen_but_booking_action_is_fresh(self):
    first = client.get(url).json()
    with freeze_time(timezone.now() + timedelta(days=4)):
        second = client.get(url).json()
    self.assertEqual(first['snapshot'], second['snapshot'])
    self.assertNotEqual(first['actions']['booking_url'],
                        second['actions']['booking_url'])
```

- [ ] **Step 3: 실패를 확인한다.**

Run:

```bash
cd inpa_be
python manage.py test \
  inpa.analytics.tests.ShareSnapshotAuthorityTests \
  inpa.analytics.tests.ShareSnapshotAtomicCreateTests \
  inpa.customers.tests.PublicConsentRevocationTests \
  inpa.notifications.tests.ShareSnapshotUnreadTests -v 2
```

Expected: 현재 live DB 재계산과 best-effort snapshot 때문에 실패.

- [ ] **Step 4: snapshot lifecycle 필드를 추가한다.**

기존 nullable `share_token`은 non-null row에서 unique 권위로 바꾸고 `payload_version`, `link_expires_at`, `revoked_at`, `revoked_reason`, `first_viewed_at`을 추가한다. 새 snapshot은 `payload_version='v2-immutable-analysis'`, 기존 row는 `v1-legacy-actions`다. migration은 중복 legacy token이 있으면 최신 1건만 유지하고 나머지 token을 null로 바꾼 뒤 조건부 unique constraint를 적용한다. snapshot이 없는 과거 Customer token과 72시간 booking URL이 payload 안에 얼어 있는 v1 snapshot은 발급 당시 분석 본문과 행동을 안전하게 분리할 수 없으므로 현재 DB payload로 소급 backfill하거나 자동 승격하지 않는다.

- [ ] **Step 5: 공유 서비스를 한 transaction으로 구현한다.**

```python
@transaction.atomic
def create_share_snapshot(customer, owner):
    customer = Customer.objects.select_for_update().get(
        id=customer.id, owner=owner)
    assert_shareable(customer)
    payload = _build_share_payload(customer, include_live_actions=False)
    revoke_active_snapshots(customer, reason='reissued')
    snapshot = ShareSnapshot.objects.create(
        owner=owner,
        customer=customer,
        share_token=uuid.uuid4(),
        payload_version='v2-immutable-analysis',
        payload=payload,
        link_expires_at=timezone.now() + timedelta(days=90),
        retention_expires_at=retention_deadline(),
        insurance_count=eligible_insurance_count(customer),
    )
    log_share_created(snapshot)
    customer.share_token = snapshot.share_token
    customer.share_sent_at = timezone.now()
    customer.share_expires_at = snapshot.link_expires_at
    customer.save(update_fields=['share_token', 'share_sent_at', 'share_expires_at'])
    return snapshot
```

어느 단계든 실패하면 전부 rollback한다. 새로 발급되는 링크는 gate 상태와 무관하게 v2 snapshot 권위를 사용한다. gate OFF에서는 snapshot이 없거나 v1인 legacy Customer token만 기존 조회를 임시 유지하고, gate ON에서는 fallback 없이 active v2 `ShareSnapshot.share_token`으로만 조회한다. `audit_share_snapshot_links`는 기본 dry-run으로 unbacked/v1 legacy link 수를 나눠 보고하고, `--revoke-legacy`는 별도 운영 승인 후 해당 token을 닫는다.

- [ ] **Step 6: 불변 본문과 live action envelope를 분리한다.**

공개 응답은 `{snapshot: stored_payload, actions: fresh_safe_actions}`다. `snapshot`은 DB를 재계산하지 않는다. `actions.booking_url`만 현재 snapshot customer와 영업시간을 확인해 요청 시점에 새 72시간 token으로 만든다. 전화·문자 연락처도 `actions`에 두고 현재 profile 값만 사용한다. FE와 self-diagnosis가 응답 shape를 구분하도록 회귀 테스트를 추가한다.

- [ ] **Step 7: 철회·파기·미열람 알림을 snapshot 기준으로 바꾼다.**

동의 철회와 고객 삭제는 snapshot을 회수/삭제하고, 보유기간 job은 snapshot 자체를 삭제한다. 미열람 알림은 `captured_at`, `first_viewed_at`, `link_expires_at`, `revoked_at`을 권위로 사용한다. revoke API `POST /customers/<customer_id>/share-snapshots/<snapshot_id>/revoke/`는 owner scope 404를 강제한다.

- [ ] **Step 8: self-diagnosis 즉시 분석 우회로를 닫는다.**

`insurances/self_diagnosis.py`는 gate ON에서 신규 보험을 즉시 분석하지 않고 설계사 확인 대기 상태로 만든다. 고객 화면은 `담당 설계사가 증권 내용을 확인한 뒤 안내해 드려요.`와 다음 행동만 보여준다. gate OFF 기존 흐름 회귀 테스트도 유지한다.

- [ ] **Step 9: 테스트를 통과시킨다.**

Run: `cd inpa_be && python manage.py test inpa.analytics inpa.customers inpa.notifications inpa.insurances -v 2`

Expected: 원자성·불변성·예약 CTA·철회·self-diagnosis 테스트 PASS.

- [ ] **Step 10: 커밋한다.**

```bash
git add inpa_be/inpa/analytics/models.py \
  inpa_be/inpa/analytics/migrations/0004_share_snapshot_token_authority.py \
  inpa_be/inpa/analytics/sharing.py \
  inpa_be/inpa/analytics/management/__init__.py \
  inpa_be/inpa/analytics/management/commands/__init__.py \
  inpa_be/inpa/analytics/management/commands/audit_share_snapshot_links.py \
  inpa_be/inpa/analytics/views.py \
  inpa_be/inpa/analytics/urls.py inpa_be/inpa/customers/public_consent.py \
  inpa_be/inpa/notifications/jobs.py inpa_be/inpa/analytics/tests.py \
  inpa_be/inpa/customers/tests.py inpa_be/inpa/notifications/tests.py \
  inpa_be/inpa/insurances/self_diagnosis.py
git commit -m "feat(공유): 불변 스냅샷을 공개 링크 권위로 전환"
```

### Task 11: 프론트 단위테스트 기반과 비동기 업로드·작업 복구 흐름 추가

**Files:**

- Modify: `inpa_fe/package.json`
- Modify: `inpa_fe/package-lock.json`
- Create: `inpa_fe/vitest.config.ts`
- Create: `inpa_fe/vitest.setup.ts`
- Create: `inpa_fe/lib/insurance-imports.ts`
- Create: `inpa_fe/lib/__tests__/insurance-imports.test.ts`
- Modify: `inpa_fe/lib/api.ts`
- Modify: `inpa_fe/components/ocr-upload.tsx`
- Create: `inpa_fe/components/insurance-import-cards.tsx`
- Create: `inpa_fe/components/__tests__/insurance-import-upload.test.tsx`
- Create: `inpa_fe/components/__tests__/insurance-import-cards.test.tsx`
- Modify: `inpa_fe/app/customer/[id]/page.tsx`
- Modify: `inpa_fe/app/analysis/page.tsx`

- [ ] **Step 1: Vitest/RTL 최소 기반을 설치하고 red/green을 확인한다.**

devDependencies는 `vitest`, `jsdom`, `@testing-library/react`, `@testing-library/jest-dom`, `@testing-library/user-event`다. script는 `test`와 `test:run`을 추가한다. 먼저 `expect(1).toBe(2)` 한 건이 실패함을 확인하고 `expect(1).toBe(1)`로 바꿔 runner 자체를 검증한다.

Run: `cd inpa_fe && npm run test:run`

Expected: 최종 smoke test PASS.

- [ ] **Step 2: 순수 preflight와 상태 문구 테스트를 작성한다.**

`lib/insurance-imports.ts`는 50MB, MIME, `%PDF-` magic bytes, UUID idempotency 생성, unresolved count, 실제 상태 문구를 다룬다. 가짜 퍼센트와 타이머를 만들지 않는다.

```ts
export const IMPORT_STATUS_COPY: Record<InsuranceImportStatus, string> = {
  queued: "분석 순서를 기다리고 있어요",
  extracting: "증권 내용을 읽고 있어요",
  validating: "읽은 내용을 확인하고 있어요",
  review_required: "직접 확인할 내용이 준비됐어요",
  confirmed: "확인한 내용이 분석에 반영됐어요",
  failed: "증권 원문을 다시 선택해 주세요",
  canceled: "선택한 증권 작업을 정리했어요",
  superseded: "새로 확인한 자료가 반영됐어요",
};
```

- [ ] **Step 3: `lib/api.ts`에 정확한 타입과 endpoint 함수를 추가한다.**

타입은 `InsuranceImportStatus`, `ReviewState`, `CoverageResolution`, `InsuranceImportListItem`, `InsuranceImportJob`, `InsuranceImportDraft`, `InsuranceDraftPolicy`, `InsuranceDraftCoverageRow`, `StandardCoverageOption`, `ValidationIssue`, `DraftPatchPayload`, `ConfirmPayload`, `SourceUrlResponse`다.

함수:

```ts
createInsuranceImport(customerId, file, options)
getInsuranceImportConfig()
listInsuranceImports(customerId)
getInsuranceImport(jobId)
getInsuranceImportDraft(jobId)
patchInsuranceImportDraft(jobId, payload, idempotencyKey)
confirmInsuranceImport(jobId, payload, idempotencyKey)
cancelInsuranceImport(jobId, idempotencyKey)
getInsuranceImportSourceUrl(jobId)
```

`ConfirmPayload`은 `planner_confirmed_source_match: true`를 literal type으로 갖는다. `ManualInsuranceItem`, `InsuranceFee`, `HeatmapResponse`, `ShareViewResponse`에는 server review/include/state summary와 `{snapshot, actions}` shape를 반영한다.

- [ ] **Step 4: 기존 fake stage 동기 upload를 202 job 생성으로 바꾸는 테스트를 작성한다.**

ConsentModal, 412, 402 흐름은 유지한다. runtime config가 ON이면 성공 후 `/customer/<id>/insurance-imports/<jobId>`로 이동하고, active duplicate는 기존 job 열기, confirmed duplicate는 기존 보험 보기/새 보험 추가/교체 선택을 보여준다. config가 OFF이면 기존 `uploadInsuranceOcr()`와 동기 성공 흐름을 유지해 dormant backend 배포가 운영 업로드를 깨뜨리지 않는다. 같은 파일 input 재선택이 가능해야 한다.

- [ ] **Step 5: 고객 분석 탭에 작업 목록을 분석보다 먼저 배치한다.**

`insurance-import-cards.tsx`는 config ON에서만 queued/extracting/validating/review_required/failed/canceled/confirmed를 실제 DB 상태로 표시한다. page refresh 후 `listInsuranceImports(customerId)`로 복구하고, response customer id가 route와 다르면 목록을 렌더하지 않고 고객 목록으로 안내한다. 보유 `portfolio_type=1`과 제안 `portfolio_type=2`, `/analysis` 허브가 같은 create 함수를 사용한다. config fetch 실패는 gate OFF로 추측하지 않고 재시도 안내를 보여 줘 안전한 신규 흐름이 legacy 즉시저장으로 조용히 후퇴하지 않게 한다.

- [ ] **Step 6: 테스트·copy lint·build를 통과시킨다.**

Run:

```bash
cd inpa_fe
npm run test:run
npm run lint:copy
npm run build
```

Expected: tests PASS, forbidden copy 0, Next build 성공.

- [ ] **Step 7: 커밋한다.**

```bash
git add inpa_fe/package.json inpa_fe/package-lock.json inpa_fe/vitest.config.ts \
  inpa_fe/vitest.setup.ts inpa_fe/lib/insurance-imports.ts \
  inpa_fe/lib/__tests__/insurance-imports.test.ts inpa_fe/lib/api.ts \
  inpa_fe/components/ocr-upload.tsx inpa_fe/components/insurance-import-cards.tsx \
  inpa_fe/components/__tests__/insurance-import-upload.test.tsx \
  inpa_fe/components/__tests__/insurance-import-cards.test.tsx \
  'inpa_fe/app/customer/[id]/page.tsx' inpa_fe/app/analysis/page.tsx
git commit -m "feat(보험): 비동기 증권 작업과 이어보기 추가"
```

### Task 12: 원문과 초안을 나란히 확인하는 검토 화면 구현

**Files:**

- Create: `inpa_fe/app/customer/[id]/insurance-imports/[jobId]/page.tsx`
- Create: `inpa_fe/components/insurance-review-workspace.tsx`
- Create: `inpa_fe/components/insurance-draft-editor.tsx`
- Create: `inpa_fe/components/insurance-source-viewer.tsx`
- Create: `inpa_fe/components/__tests__/insurance-review-workspace.test.tsx`
- Create: `inpa_fe/components/__tests__/insurance-draft-editor.test.tsx`
- Create: `inpa_fe/components/__tests__/insurance-source-viewer.test.tsx`

- [ ] **Step 1: Next 16 로컬 문서를 다시 확인하고 Client boundary를 고정한다.**

읽을 문서:

```text
node_modules/next/dist/docs/01-app/03-api-reference/01-directives/use-client.md
node_modules/next/dist/docs/01-app/02-guides/lazy-loading.md
node_modules/next/dist/docs/03-api-reference/03-file-conventions/dynamic-routes.md
node_modules/next/dist/docs/04-functions/use-params.md
```

localStorage token, polling, 편집이 필요한 route는 Client Component로 만들고 `useParams<{id:string;jobId:string}>()` 값을 숫자/UUID로 검증한다.

- [ ] **Step 2: polling·새로고침·오류 상태 테스트를 먼저 작성한다.**

중첩 `setInterval`은 쓰지 않는다. 요청이 끝난 뒤 `setTimeout`으로 다음 GET을 예약하고 unmount/새 request sequence에서 이전 응답을 폐기한다. queued→extracting→validating→review_required, failed, canceled, 404, network retry를 테스트한다. 상태 wrapper는 `role="status" aria-live="polite"`, 실패는 `role="alert"`다.

- [ ] **Step 3: draft editor 행동 테스트를 작성한다.**

확인할 항목 먼저 정렬, 기본정보 수정, 표준 위치 변경, 분석 제외 사유, 중복 대상 지정, 제외 취소, 첫 미해결 항목 focus/scroll, 100행 키보드 순서를 검증한다. virtual list는 사용하지 않고 필터/접기로 탐색 부담을 낮춘다.

CTA 활성 조건:

```ts
const canConfirm =
  plannerConfirmedSourceMatch &&
  unresolvedCount === 0 &&
  !isSaving &&
  !hasVersionConflict;
```

정확 문구:

```text
자동으로 정리한 내용이에요. 증권 원문과 같은지 직접 확인해 주세요.
증권 원문과 같은지 확인했습니다
검토 완료하고 분석에 반영
확인이 필요한 항목 N개
```

`정확함`, `AI 검증 완료`, `OCR`은 렌더 문구에 쓰지 않는다.

- [ ] **Step 4: desktop split/mobile dialog 원본 보기를 구현한다.**

desktop은 `lg:grid-cols-[minmax(0,1fr)_minmax(440px,1fr)]`, 왼쪽 sticky PDF, 오른쪽 editor다. owner API에서 5분 signed URL을 받고 `<iframe title="증권 원문, 3페이지" referrerPolicy="no-referrer">`에 `#page=3&zoom=page-width`를 붙인다.

mobile은 `원문 보기` 버튼으로 `role="dialog" aria-modal="true"` 전체화면을 열고 ESC/닫기/focus return을 구현한다. 새 화면 열기 fallback을 제공한다. URL 만료 시 재발급하고 source 삭제 상태면 같은 파일 재선택 안내를 제공한다.

- [ ] **Step 5: optimistic version과 confirm 충돌 UI를 구현한다.**

409 `DRAFT_VERSION_CHANGED`는 최신 draft를 다시 읽고 `다른 화면에서 내용이 바뀌었어요. 최신 내용을 불러왔습니다.`를 보여준다. `IMPORT_TARGET_CHANGED`는 최신 보험 보기로 이동한다. confirm 성공 후 `/customer/<id>?tab=analysis`로 돌아가 heatmap과 보험 목록을 새로 읽는다.

- [ ] **Step 6: 컴포넌트 테스트와 build를 통과시킨다.**

Run:

```bash
cd inpa_fe
npm run test:run -- insurance-review-workspace insurance-draft-editor insurance-source-viewer
npm run lint:copy
npm run build
```

Expected: interaction/a11y tests PASS, build 성공.

- [ ] **Step 7: 커밋한다.**

```bash
git add 'inpa_fe/app/customer/[id]/insurance-imports/[jobId]/page.tsx' \
  inpa_fe/components/insurance-review-workspace.tsx \
  inpa_fe/components/insurance-draft-editor.tsx \
  inpa_fe/components/insurance-source-viewer.tsx \
  inpa_fe/components/__tests__/insurance-review-workspace.test.tsx \
  inpa_fe/components/__tests__/insurance-draft-editor.test.tsx \
  inpa_fe/components/__tests__/insurance-source-viewer.test.tsx
git commit -m "feat(보험): 원문 대조 검토 화면 추가"
```

### Task 13: 직접 입력·기존 보험 확인·분석 상태·불변 공유 UI를 한 흐름으로 연결

**Files:**

- Modify: `inpa_fe/components/insurance-manual-modal.tsx`
- Modify: `inpa_fe/components/insurance-draft-editor.tsx`
- Modify: `inpa_fe/app/customer/[id]/page.tsx`
- Modify: `inpa_fe/components/heatmap.tsx`
- Modify: `inpa_fe/components/share-link-button.tsx`
- Modify: `inpa_fe/components/share-snapshot-panel.tsx`
- Modify: `inpa_fe/app/s/[token]/page.tsx`
- Modify: `inpa_fe/lib/api.ts`
- Test: `inpa_fe/components/__tests__/insurance-manual-review.test.tsx`
- Test: `inpa_fe/components/__tests__/share-authority.test.tsx`

- [ ] **Step 1: 수동 보험의 담보 편집·최종 확인 테스트를 작성한다.**

기본정보만 저장하면 한눈표에 포함되지 않는다. 담보 추가/수정/삭제, 표준 위치 선택, 확인 체크, confirm 후 포함을 테스트한다. 수동 행도 금액/기간 오류가 있으면 CTA가 막혀야 한다.

- [ ] **Step 2: legacy 전환 화면을 구현한다.**

gate ON일 때 `legacy_review_required` 보험은 목록에는 보이지만 분석 포함 표시를 하지 않는다. `기존 자료 확인하기`로 기본정보·담보를 열고 원본이 없는 사실을 안내한 뒤 설계사가 직접 확인/수정한다. 자동으로 confirmed 처리하지 않는다.

- [ ] **Step 3: 분석 화면의 권위 상태를 표시한다.**

포함 보험 수, 제외 보험 수, 마지막 확인 시각, 확인 대기 수를 heatmap 위에 보여준다. 합계 금액을 누르면 보험→원문 담보→가입금액 근거를 펼친다. 기준선이 없을 때 기존 `기준 설정하기` 흐름은 그대로 유지한다.

- [ ] **Step 4: 공유 차단·snapshot preview·회수 UI를 구현한다.**

`can_share=false`면 서버 `share_block_reason`을 쉬운 말로 표시하고 버튼을 비활성화한다. share 생성 409/500은 기존 링크가 발급된 것처럼 보이면 안 된다. 공유 기록에 active/revoked/expired 상태와 회수 버튼을 추가하고, 고객 미리보기는 저장된 `snapshot` 본문을 사용한다.

공개 `/s`는 새 `{snapshot, actions}` 응답을 렌더한다. 보험 본문은 snapshot, 예약/전화/문자는 actions를 사용한다. 4일 후 다시 열어도 예약 CTA가 정상임을 component test에서 mock token 변화로 확인한다.

- [ ] **Step 5: 테스트·copy lint·build를 통과시킨다.**

Run:

```bash
cd inpa_fe
npm run test:run
npm run lint:copy
npm run build
```

Expected: manual/legacy/share tests PASS, build 성공.

- [ ] **Step 6: 커밋한다.**

```bash
git add inpa_fe/components/insurance-manual-modal.tsx \
  inpa_fe/components/insurance-draft-editor.tsx 'inpa_fe/app/customer/[id]/page.tsx' \
  inpa_fe/components/heatmap.tsx inpa_fe/components/share-link-button.tsx \
  inpa_fe/components/share-snapshot-panel.tsx 'inpa_fe/app/s/[token]/page.tsx' \
  inpa_fe/lib/api.ts inpa_fe/components/__tests__/insurance-manual-review.test.tsx \
  inpa_fe/components/__tests__/share-authority.test.tsx
git commit -m "feat(보험): 확인부터 분석과 공유까지 연결"
```

### Task 14: PII 없는 운영 지표와 private 골든 평가 명령 추가

**Files:**

- Modify: `inpa_be/inpa/admin_console/views.py`
- Modify: `inpa_be/inpa/admin_console/urls.py`
- Modify: `inpa_be/inpa/admin_console/tests.py`
- Modify: `inpa_fe/lib/adminApi.ts`
- Modify: `inpa_fe/app/admin/claude-cost/page.tsx`
- Modify: `inpa_fe/app/admin/settings/page.tsx`
- Create: `inpa_be/inpa/insurances/extraction_eval.py`
- Create: `inpa_be/inpa/insurances/management/commands/eval_insurance_extraction.py`
- Test: `inpa_be/inpa/insurances/test_extraction_eval.py`
- Create: `docs/dev/27-insurance-review-operations.md`

- [ ] **Step 1: 관리자 지표의 권한·PII 부재 테스트를 작성한다.**

관리자 200, 일반 설계사 403, `@inpa.local` 제외, p50/p95 경계값, 감지 담보 0건, queue wait/review time, retry/lease expiry, validation state, carrier code별 미매칭, 수정률, 토큰/비용을 검증한다. response JSON에 `draft_payload`, `structured_payload`, file name, raw_name, customer name이 없음을 문자열 검사한다. RuntimeConfig의 동시 실행 상한은 관리자 화면에서 변경하고 다음 claim부터 반영되는지 API 테스트한다.

- [ ] **Step 2: 기존 Claude 비용 endpoint를 확장한다.**

별도 원문 관리 화면을 만들지 않는다. 기존 비용 화면에 작업 상태 분포, 대기/처리 p50·p95, 검토 준비/확인 필요/근거 없음/미매칭 비율, 후보/확정 수, 수정률, 실패율을 추가한다. 비용은 기존 Claude log와 extraction result 중 한 권위만 합산해 중복 계상하지 않는다. 기능 스위치는 관리자 설정에 read-only로 표시하고 변경은 env 배포 절차로만 한다.

- [ ] **Step 3: 기존 정규화 골든셋과 분리된 PDF scorer를 테스트한다.**

`analysis/golden_eval.py`와 `analysis/data/golden_set.json`은 수정하지 않는다. 새 scorer는 합성 JSON fixture로 insurer/product/date/amount exact match, coverage recall/precision, mapping accuracy, silent omission, validation catch rate를 계산한다. manifest validator는 서로 다른 비식별 case 100건 이상, 정답 coverage row 1,000행 이상, 생명/손해와 주요 carrier/구·신 양식 strata가 모두 있지 않으면 실행 전에 exit 2로 막는다. `silent_omission > 0`이면 release gate exit code 1이다.

- [ ] **Step 4: 제한 저장소 manifest 계약을 구현한다.**

명령:

```bash
cd inpa_be
python manage.py eval_insurance_extraction \
  --dataset-root /secure/inpa-eval \
  --manifest /secure/inpa-eval/holdout.json \
  --split holdout \
  --compare legacy,review \
  --fail-on-release-gates
```

manifest에는 비식별 `case_id`, PDF 상대경로, 사람이 확정한 정답 JSON 상대경로와 비식별 strata code만 둔다. PDF·정답·실패 원문은 git, CI artifact, 로그에 넣지 않는다. 실제 Claude holdout은 staging의 접근 통제 환경에서만 실행한다.

`legacy`는 현재 pdfplumber→Claude 결과를 DB에 저장하지 않고 scorer 공통 row schema로 변환하고, `review`는 새 줄 근거→Claude→validator의 설계사 수정 전 결과와 사람이 확정한 수정 후 결과를 각각 채점한다. 두 경로는 같은 `CLAUDE_MODEL_PARSE`, 정규화 버전, 입력 PDF split을 사용한다. 보고서는 A/B별 정확도, 조용한 누락, 검토로 보낸 오류, 검토 후 중대한 금액 오류, p50/p95, 비용을 같은 표에 기록한다.

- [ ] **Step 5: 테스트와 관리자 build를 통과시킨다.**

Run:

```bash
cd inpa_be
python manage.py test inpa.admin_console inpa.insurances.test_extraction_eval -v 2
cd ../inpa_fe
npm run test:run
npm run build
```

Expected: 권한/PII/scorer tests PASS, build 성공.

- [ ] **Step 6: 커밋한다.**

```bash
git add inpa_be/inpa/admin_console/views.py inpa_be/inpa/admin_console/urls.py \
  inpa_be/inpa/admin_console/tests.py inpa_fe/lib/adminApi.ts \
  inpa_fe/app/admin/claude-cost/page.tsx inpa_fe/app/admin/settings/page.tsx \
  inpa_be/inpa/insurances/extraction_eval.py \
  inpa_be/inpa/insurances/management/commands/eval_insurance_extraction.py \
  inpa_be/inpa/insurances/test_extraction_eval.py \
  docs/dev/27-insurance-review-operations.md
git commit -m "feat(보험): 추출 품질 계측과 골든 평가 추가"
```

### Task 15: PostgreSQL 실제 경쟁 CI와 60건 staging 부하 검증 추가

**Files:**

- Create: `inpa_be/config/settings/test_postgres.py`
- Create: `inpa_be/inpa/insurances/test_import_concurrency.py`
- Create: `inpa_be/scripts/load/insurance_import_concurrency.py`
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: SQLite가 아닌 PostgreSQL 경쟁 테스트를 작성한다.**

`TransactionTestCase`, `ThreadPoolExecutor`, `threading.Barrier`, 각 thread의 `close_old_connections()`, 별도 `APIClient`를 사용한다. `TestCase`의 바깥 transaction이나 SQLite로 `select_for_update`를 검증하지 않는다.

필수 assertion:

- 같은 owner/customer/hash 동시 접수는 job 1건
- 같은 hash/다른 owner는 독립 job 2건
- 늦은 attempt CAS update 0건
- 같은 고객의 서로 다른 증권 동시 확정은 모두 보존
- 같은 target 교체는 한 건 성공, 다른 건 409 `IMPORT_TARGET_CHANGED`
- 타 owner job/draft/source/confirm/cancel 모두 404
- 한 job cleanup이 다른 key를 삭제하지 않음

- [ ] **Step 2: PostgreSQL CI job을 추가한다.**

GitHub Actions service는 PostgreSQL 16을 사용하고 health check 후 다음을 실행한다.

```yaml
services:
  postgres:
    image: postgres:16
    env:
      POSTGRES_DB: inpa_test
      POSTGRES_USER: postgres
      POSTGRES_HOST_AUTH_METHOD: trust
    ports: ['5432:5432']
    options: >-
      --health-cmd "pg_isready -U postgres -d inpa_test"
      --health-interval 10s --health-timeout 5s --health-retries 5
env:
  DATABASE_URL: postgresql://postgres@127.0.0.1:5432/inpa_test
  DJANGO_SETTINGS_MODULE: config.settings.test_postgres
```

```bash
python manage.py test inpa.insurances.test_import_concurrency \
  --settings=config.settings.test_postgres --parallel=1 -v 2
```

조건부 unique, row lock, transaction isolation을 운영 DB 계열에서 검증한다. 기존 SQLite 전체 suite는 그대로 유지한다.

- [ ] **Step 3: staging 60건 load script를 구현한다.**

표준 라이브러리 `concurrent.futures`와 HTTP client를 사용한다. scenario 파일은 git 밖에 두며 20 owner × 3 PDF, 같은 hash 교차 owner, 같은 target 교체를 포함한다.

```bash
cd inpa_be
python scripts/load/insurance_import_concurrency.py \
  --base-url "$STAGING_API_BASE" \
  --scenario /secure/inpa-load/scenario.json \
  --workers 60
```

script는 교차 귀속 0, 중복 합산 0, 모든 job의 owner/customer/job 일치, 사용자별 대기시간, 전체 p95를 계산하고 하나라도 어기면 exit 1이다. 인증 토큰·파일 경로·원문은 결과 JSON에 기록하지 않는다.

- [ ] **Step 4: CI 대상 테스트를 로컬 PostgreSQL 또는 승인된 CI에서 통과시킨다.**

Run: 위 targeted command.

Expected: concurrency tests PASS. 로컬 PostgreSQL이 없으면 CI 결과를 완료 증거로 남기고 SQLite PASS로 대체 주장하지 않는다.

- [ ] **Step 5: 커밋한다.**

```bash
git add inpa_be/config/settings/test_postgres.py \
  inpa_be/inpa/insurances/test_import_concurrency.py \
  inpa_be/scripts/load/insurance_import_concurrency.py .github/workflows/ci.yml
git commit -m "test(보험): PostgreSQL 동시성 출시 게이트 추가"
```

### Task 16: 전체 검증, adversarial review, staged rollout, 운영 승인 경계

**Files:**

- Modify after implementation+merge+deploy only: `README.md`
- Modify after implementation+merge+deploy only: `AGENTS.md`
- Modify if repeated failures occur: `.Codex/failures.md`

- [ ] **Step 1: backend 전체 검증을 새 출력으로 실행한다.**

```bash
cd inpa_be
python manage.py makemigrations --check --dry-run
python manage.py check
python manage.py test inpa
python manage.py eval_normalization
```

Expected: migration drift 0, check 0 issues, 전체 tests PASS, normalization hard gate PASS.

- [ ] **Step 2: frontend 전체 검증을 새 출력으로 실행한다.**

```bash
cd inpa_fe
npm run test:run
npm run lint:copy
npm run build
```

Expected: tests PASS, forbidden copy 0, Next production build 성공.

- [ ] **Step 3: 독립 adversarial review를 실행한다.**

네 관점으로 분리한다.

1. Correctness: 후보 보존식, 금액/날짜, rollback, 동일 파일 중복.
2. Security/privacy: owner 404, signed source URL, PII log, storage key, consent before Claude.
3. Concurrency/infra: attempt CAS, lease, same-target replacement, per-owner fairness, worker loss.
4. UX/accessibility: 확인 필요 강조, 수동 수정, 320px, 200%, 키보드, 스크린리더, 100행.

확인된 finding은 수정하고 같은 대상 테스트를 추가한다. 기각 finding은 근거를 `docs/dev/27-insurance-review-operations.md`에 기록한다.

- [ ] **Step 4: staging에 gate OFF로 먼저 배포한다.**

Migration 적용 후 PostgreSQL에서 `insurance_extraction_job`의 조건부 unique/index와 `share_snapshot` token unique를 `SELECT`/introspection으로 확인한다. `python manage.py audit_share_snapshot_links` dry-run으로 snapshot 없는 기존 활성 링크와 v1 legacy snapshot 수를 각각 보고하고, 현재 payload를 과거 자료처럼 소급 저장하지 않는다. web, worker, Valkey, private R2를 연결하고 worker 중단/재시작, lease 회수, exact source cleanup을 시험한다.

- [ ] **Step 5: staging에서만 gate ON 후 실제 흐름을 검증한다.**

실제 전자 PDF로 202→새로고침 복구→원문 근거→수정→confirm→한눈표→snapshot share를 확인한다. 두 브라우저 로그인 세션에서 타 job 404와 화면 교차 0을 확인한다. Chrome/Safari/iOS의 PDF `#page` 이동이 실패하면 출시를 멈추고 `react-pdf/pdfjs`를 Client-only dynamic import하는 별도 수정 후 재검증한다.

필수 화면 조건:

- 320px, 200% zoom, 긴 보험명, 담보 100개
- keyboard only, VoiceOver 또는 NVDA
- network disconnect, empty draft, Claude fail, duplicate active/confirmed
- 4일 경과 snapshot의 새 예약 CTA

- [ ] **Step 6: private holdout과 60건 load gate를 통과시킨다.**

출시 차단 기준은 최소 100건·1,000행 holdout 충족, review 경로 silent omission 0, 검토 후 중대한 금액 오류 0, 미확정/해지/제외/교체 보험 포함 0, 교차 귀속 0, duplicate 합산 0, stale overwrite 0, snapshot mismatch 0, snapshot 없는/v1 legacy 공개 fallback 0건이다. legacy A와 review B 비교표가 생성되지 않거나 하나라도 실패하면 운영 gate를 열지 않는다.

- [ ] **Step 7: PM에게 staging 증거와 비용을 보고하고 운영 배포 승인을 별도로 받는다.**

보고 형식:

```text
Changed: 검토형 업로드, 설계사 확인, 확정 분석, 불변 공유, 동시성 격리
Verified by: 전체 테스트, PostgreSQL 경쟁 CI, private holdout, staging 60건, 브라우저/a11y
Result: 각 gate의 실제 수치와 PASS/FAIL
Unverified: 실제 설계사 피드백에서만 확인 가능한 항목
Infrastructure cost: Render worker/Key Value/cron 예상 월비용
Rollback: INSURANCE_REVIEW_GATE_ENABLED=False + 이전 web release
```

명시적 승인 전에는 production 환경변수를 켜거나 production deploy를 실행하지 않는다. snapshot 없는 legacy 링크 회수도 별도 승인 범위에 포함하고, 해당 설계사에게 기존 보험 확인 후 새 링크를 발급할 안내를 준비한다.

승인 후 production gate를 켜기 직전에 `python manage.py audit_share_snapshot_links --revoke-legacy`를 실행하고 다시 dry-run해 unbacked/v1 active link가 0건인지 확인한다. 0건이 아니면 gate를 켜지 않는다. 회수 대상 설계사에게는 기존 보험 확인 후 새 링크를 발급하는 다음 행동을 안내한다.

- [ ] **Step 8: 승인 후 production 배포와 실제 URL 검증을 마친 다음에만 두 문서를 갱신한다.**

`README.md`는 PM용 한국어 로드맵, `AGENTS.md`는 agent용 영어 SSOT로 갱신한다. 실제 `/healthz/`, import 202, worker completion, share curl, browser render, Sentry/latency 5분 관찰까지 끝난 뒤 docs commit을 만든다.

```bash
git add README.md AGENTS.md docs/dev/27-insurance-review-operations.md
git commit -m "docs(보험): 검토형 분석 운영 상태 반영"
```

## Self-review Checklist

- [ ] 스캔 PDF·사진·GPT·추천이 구현 범위에 들어가지 않았다.
- [ ] 기존 후보 삭제/최대값 병합 함수를 새 흐름에서 호출하지 않는다.
- [ ] 모든 신규 API가 owner와 customer owner를 함께 검사하고 foreign ID를 404로 숨긴다.
- [ ] 큐 message에는 job UUID만 있고 worker가 DB에서 owner/customer/key를 다시 읽는다.
- [ ] source delete는 exact key 한 건이며 prefix 삭제가 없다.
- [ ] retry/중복 PATCH/중복 confirm이 비용·최종 보험을 중복 생성하지 않는다.
- [ ] 미해결·근거 없음·미확정 보험이 분석 또는 공유에 들어갈 경로가 없다.
- [ ] case override가 global mapping과 다른 고객에게 전파되지 않는다.
- [ ] snapshot failure가 token/event를 남기지 않고, 공개 분석 본문이 현재 DB를 다시 계산하지 않는다.
- [ ] gate ON 전 legacy live-DB 공유 fallback이 감사·회수 또는 재발급으로 0건이 됐다.
- [ ] 72시간 booking action과 90일 불변 분석 snapshot의 수명이 분리됐다.
- [ ] self-diagnosis가 gate ON에서 사람 확인을 우회하지 않는다.
- [ ] SQLite가 아닌 PostgreSQL에서 실제 잠금 경쟁을 검증한다.
- [ ] 관리자·로그·Sentry에 PDF/원문/고객명/raw payload가 없다.
- [ ] 계획의 모든 신규 파일, endpoint, enum, error code, test command가 구체적이며 미정 항목이나 생략 코드가 없다.

## Execution Choice

1. **Subagent-Driven Development (Recommended):** 이 세션에서 task별 구현 agent와 독립 review agent를 순차 배치한다. 각 task는 테스트와 작은 커밋까지 끝낸 뒤 다음 task로 넘어간다.
2. **Inline Execution:** 주 agent가 같은 순서를 직접 실행하고 Task 9, 10, 15, 16에서만 독립 adversarial review agent를 호출한다.

권장 선택은 1번이다. 공유 작업트리의 사용자 변경을 보존하고, backend import·frontend review·analysis/share·concurrency를 서로 다른 agent가 구현하되 task 경계와 커밋 순서는 이 문서를 단일 정본으로 사용한다.
