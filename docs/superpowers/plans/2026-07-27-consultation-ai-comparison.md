# Consultation AI Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 관리자만 가상 상담 음성 한 건을 올려 OpenAI 화자 구분 전사 한 번과 OpenAI·Claude 요약 각 한 번을 공정하게 A/B 비교하는 무저장 내부 검토 화면을 만든다.

**Architecture:** 기존 상담 녹음·요약 경로와 분리된 `consultations` 비교 서비스가 업로드를 임시 파일로 검증하고 OpenAI 전사를 한 번 수행한다. 기존 개인정보 가림 로직으로 만든 동일 전사문을 두 요약 공급자에 병렬 전달하고, 관리자 API가 무작위 A/B 결과를 반환하며 Next 관리자 화면은 평가가 끝날 때까지 모델명을 가린다.

**Tech Stack:** Django 5.2, Django REST Framework, PyAV 18, OpenAI Python SDK 2.46.0, Anthropic Python SDK 0.117.1, Next.js 16.2.9, React 19.2.4, TypeScript, Tailwind v4, Vitest.

## Global Constraints

- 비교 화면과 API는 기존 `IsAdmin` 권한을 서버에서 강제하며 일반 사용자와 비로그인 요청을 허용하지 않는다.
- `CONSULTATION_AI_COMPARISON_ENABLED=False`가 기본값이며 운영 녹음·AI 요약 스위치의 설정과 동작은 바꾸지 않는다.
- 모델 ID는 `OPENAI_TRANSCRIPTION_MODEL`, `OPENAI_COMPARISON_MODEL`, `ANTHROPIC_COMPARISON_MODEL`에서만 읽고 코드에 고정하지 않는다.
- 최대 크기는 `26214400`바이트, 최대 길이는 `300`초다. 지원 확장자는 `flac`, `mp3`, `mp4`, `mpeg`, `mpga`, `m4a`, `ogg`, `wav`, `webm`이다.
- 업로드 파일은 성공·실패와 무관하게 요청 범위 임시 디렉터리에서 삭제하며 DB, R2, 고객 메모, 사용량, 결제에 쓰지 않는다.
- OpenAI 전사는 정확히 한 번 만들고 같은 가림 전사문을 OpenAI·Claude 요약에 각각 한 번 전달한다.
- 두 요약은 기존 `SUMMARY_JSON_SCHEMA`의 네 구역을 사용하고 공급자 한쪽 실패 시 다른 결과와 전사문을 보존한다.
- OpenAI Responses API는 `store=False`를 사용한다. SDK 자동 재시도는 끄고 명확한 연결 전 실패에만 1초, 2초, 4초 재시도를 허용하며 시간초과는 자동 재호출하지 않는다.
- 파일명, API 키, 음성, 전사문, 요약문을 로그에 남기지 않는다. 로그에는 단계, 안전한 결과 코드, 예외 종류, 크기와 처리시간만 허용한다.
- UI는 기존 관리자 색상·간격·`Card` 구성과 관리자 가드를 재사용하고 서비스 화면에 `dark:` 변형을 추가하지 않는다.
- 사용자 문구는 쉬운 한국어와 긍정 안내를 사용하며 렌더 문자열에 em dash를 넣지 않는다.
- 실제 API 연결 확인은 합성 음성만 사용한다. 운영 배포와 기능 플래그 활성화는 이 계획의 구현 범위 밖이며 별도 승인을 받는다.

---

### Task 1: 임시 오디오 검증 경계와 환경 설정

**Files:**
- Create: `inpa_be/inpa/consultations/comparison_audio.py`
- Create: `inpa_be/inpa/consultations/tests/test_comparison_audio.py`
- Modify: `inpa_be/config/settings/base.py:110-120,272-315`
- Modify: `inpa_be/.env.example:67-86`
- Modify: `inpa_be/requirements.txt`
- Modify: `render.yaml:55-105`

**Interfaces:**
- Produces: `ComparisonAudioError(code: str)`.
- Produces: `PreparedComparisonAudio(path: pathlib.Path, duration_seconds: float, byte_size: int)`.
- Produces: `prepare_comparison_audio(uploaded_file) -> ContextManager[PreparedComparisonAudio]`.
- The context manager accepts Django `UploadedFile`, checks the approved extension and configured size before copying, counts actual copied bytes, opens the file with PyAV, requires exactly one audio stream and no video stream, derives or decodes duration, enforces the configured duration, and removes its temporary directory on every exit path.

- [ ] **Step 1: Write failing audio-boundary tests**

```python
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings

from inpa.consultations.comparison_audio import (
    ComparisonAudioError,
    prepare_comparison_audio,
)


@override_settings(
    CONSULTATION_COMPARISON_MAX_BYTES=1024 * 1024,
    CONSULTATION_COMPARISON_MAX_DURATION_SECONDS=300,
)
class ComparisonAudioTests(SimpleTestCase):
    def test_rejects_unsupported_extension_before_temp_file_is_used(self):
        upload = SimpleUploadedFile('synthetic.txt', b'not audio')
        with self.assertRaisesRegex(ComparisonAudioError, 'AUDIO_FORMAT_UNSUPPORTED'):
            with prepare_comparison_audio(upload):
                self.fail('unsupported audio reached provider boundary')

    def test_removes_temp_file_after_success(self):
        upload = SimpleUploadedFile('synthetic.wav', make_wav(seconds=1))
        with prepare_comparison_audio(upload) as prepared:
            path = prepared.path
            self.assertTrue(path.exists())
            self.assertGreater(prepared.duration_seconds, 0)
        self.assertFalse(path.exists())

    def test_removes_temp_file_when_consumer_raises(self):
        upload = SimpleUploadedFile('synthetic.wav', make_wav(seconds=1))
        with self.assertRaisesRegex(RuntimeError, 'provider failed'):
            with prepare_comparison_audio(upload) as prepared:
                path = prepared.path
                raise RuntimeError('provider failed')
        self.assertFalse(path.exists())
```

The test file defines `make_wav(seconds: int, sample_rate: int = 16000) -> bytes` with `io.BytesIO` and the standard-library `wave` module so no fixture contains customer data.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
cd inpa_be
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py test \
  inpa.consultations.tests.test_comparison_audio
```

Expected: import failure for missing `inpa.consultations.comparison_audio`.

- [ ] **Step 3: Add exact comparison settings and dependency**

Add these values to Django settings:

```python
CONSULTATION_AI_COMPARISON_ENABLED = env.bool(
    'CONSULTATION_AI_COMPARISON_ENABLED', default=False)
CONSULTATION_COMPARISON_MAX_BYTES = env.int(
    'CONSULTATION_COMPARISON_MAX_BYTES', default=25 * 1024 * 1024)
CONSULTATION_COMPARISON_MAX_DURATION_SECONDS = env.int(
    'CONSULTATION_COMPARISON_MAX_DURATION_SECONDS', default=300)
OPENAI_API_KEY = env('OPENAI_API_KEY', default='')
OPENAI_TRANSCRIPTION_MODEL = env('OPENAI_TRANSCRIPTION_MODEL', default='')
OPENAI_COMPARISON_MODEL = env('OPENAI_COMPARISON_MODEL', default='')
ANTHROPIC_COMPARISON_MODEL = env('ANTHROPIC_COMPARISON_MODEL', default='')
```

Pin `openai==2.46.0` in `requirements.txt`. Add the same variables without values to `.env.example`; keep the comparison flag `False`. Add only the web service Render variables:

```yaml
- key: CONSULTATION_AI_COMPARISON_ENABLED
  value: "False"
- key: OPENAI_API_KEY
  sync: false
- key: OPENAI_TRANSCRIPTION_MODEL
  sync: false
- key: OPENAI_COMPARISON_MODEL
  sync: false
- key: ANTHROPIC_COMPARISON_MODEL
  sync: false
- key: CONSULTATION_COMPARISON_MAX_BYTES
  value: "26214400"
- key: CONSULTATION_COMPARISON_MAX_DURATION_SECONDS
  value: "300"
```

Do not add comparison variables to the consultation Celery worker or cleanup cron because the endpoint is synchronous on `inpa-be`.

- [ ] **Step 4: Implement the minimum audio context manager**

```python
SUPPORTED_COMPARISON_EXTENSIONS = frozenset({
    '.flac', '.mp3', '.mp4', '.mpeg', '.mpga',
    '.m4a', '.ogg', '.wav', '.webm',
})


class ComparisonAudioError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class PreparedComparisonAudio:
    path: Path
    duration_seconds: float
    byte_size: int


@contextmanager
def prepare_comparison_audio(uploaded_file):
    extension = Path(uploaded_file.name or '').suffix.lower()
    if extension not in SUPPORTED_COMPARISON_EXTENSIONS:
        raise ComparisonAudioError('AUDIO_FORMAT_UNSUPPORTED')
    if uploaded_file.size > settings.CONSULTATION_COMPARISON_MAX_BYTES:
        raise ComparisonAudioError('AUDIO_TOO_LARGE')
    with tempfile.TemporaryDirectory(
        prefix='inpa-consultation-comparison-',
    ) as temp_dir:
        path = Path(temp_dir) / f'audio{extension}'
        byte_size = 0
        with path.open('wb') as destination:
            for chunk in uploaded_file.chunks():
                byte_size += len(chunk)
                if byte_size > settings.CONSULTATION_COMPARISON_MAX_BYTES:
                    raise ComparisonAudioError('AUDIO_TOO_LARGE')
                destination.write(chunk)
        duration_seconds = _inspect_audio_duration(path)
        if duration_seconds > settings.CONSULTATION_COMPARISON_MAX_DURATION_SECONDS:
            raise ComparisonAudioError('AUDIO_TOO_LONG')
        yield PreparedComparisonAudio(path, duration_seconds, byte_size)
```

`_inspect_audio_duration(path: Path) -> float` opens the container with PyAV,
requires one audio stream and no video stream, uses the stream duration and time
base when both exist, otherwise decodes frames and sums
`frame.samples / frame.sample_rate`, and rejects zero-length or unreadable audio.
The implementation raises only these client-safe codes:
`AUDIO_FORMAT_UNSUPPORTED`, `AUDIO_TOO_LARGE`, `AUDIO_INVALID`,
`AUDIO_ONLY_REQUIRED`, `AUDIO_EMPTY`, `AUDIO_TOO_LONG`. It never includes the
original file name or exception message in a code.

- [ ] **Step 5: Verify GREEN and regression**

Run:

```bash
cd inpa_be
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/pip install openai==2.46.0
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py test \
  inpa.consultations.tests.test_comparison_audio \
  inpa.consultations.tests.test_audio
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py check
```

Expected: all tests pass and system check reports no issues.

- [ ] **Step 6: Commit**

```bash
git add inpa_be/inpa/consultations/comparison_audio.py \
  inpa_be/inpa/consultations/tests/test_comparison_audio.py \
  inpa_be/config/settings/base.py inpa_be/.env.example \
  inpa_be/requirements.txt render.yaml
git commit -m "feat(상담): AI 비교 오디오 검증 경계 추가"
```

### Task 2: OpenAI 전사와 두 구조화 요약 공급자

**Files:**
- Create: `inpa_be/inpa/consultations/providers/comparison_base.py`
- Create: `inpa_be/inpa/consultations/providers/openai_comparison.py`
- Create: `inpa_be/inpa/consultations/providers/anthropic_comparison.py`
- Create: `inpa_be/inpa/consultations/tests/test_comparison_providers.py`

**Interfaces:**
- Produces: `ComparisonTranscriptSegment(speaker: str, text: str, start_seconds: float | None, end_seconds: float | None)`.
- Produces: `ComparisonTranscription(segments: Sequence[ComparisonTranscriptSegment], model: str, latency_ms: int)`.
- Produces: `ComparisonSummaryResult(summary: ConsultationSummary, model: str, latency_ms: int, input_tokens: int, output_tokens: int)`.
- Produces: `ComparisonProviderFailure(code: str)` for known final failures.
- Produces: `ComparisonOutcomeUnknown(code: str)` for timeouts or ambiguous receipt.
- Produces: `retry_explicit_nonreceipt(operation, sleep=time.sleep)`, which retries only `ExplicitProviderNonReceipt` after `1`, `2`, `4` seconds and never retries any other exception.
- Produces: `OpenAIComparisonTranscriber.transcribe(path: Path) -> ComparisonTranscription`.
- Produces: `OpenAIComparisonSummarizer.summarize(masked_transcript: str) -> ComparisonSummaryResult`.
- Produces: `AnthropicComparisonSummarizer.summarize(masked_transcript: str) -> ComparisonSummaryResult`.

- [ ] **Step 1: Write failing provider contract tests**

```python
def test_openai_transcriber_requests_diarized_korean_transcript(self):
    client = FakeOpenAIClient(
        transcription=FakeDiarizedTranscript(
            text='전체 대화',
            segments=[
                FakeSegment('speaker_0', 0.0, 1.2, '안녕하세요'),
                FakeSegment('speaker_1', 1.3, 2.1, '반갑습니다'),
            ],
        ),
    )
    result = OpenAIComparisonTranscriber(client=client).transcribe(self.audio_path)

    self.assertEqual([row.speaker for row in result.segments], ['화자 1', '화자 2'])
    self.assertEqual(client.transcription_kwargs['response_format'], 'diarized_json')
    self.assertEqual(client.transcription_kwargs['chunking_strategy'], 'auto')
    self.assertEqual(client.transcription_kwargs['language'], 'ko')


def test_both_summarizers_enforce_the_same_existing_schema(self):
    openai_result = OpenAIComparisonSummarizer(
        client=FakeOpenAISummaryClient(valid_payload),
    ).summarize('화자 1: 가림 전사문')
    anthropic_result = AnthropicComparisonSummarizer(
        client=FakeAnthropicClient(valid_payload),
    ).summarize('화자 1: 가림 전사문')

    self.assertEqual(openai_result.summary, anthropic_result.summary)
    self.assertEqual(
        FakeOpenAISummaryClient.last_format['schema'],
        SUMMARY_JSON_SCHEMA,
    )
    self.assertEqual(
        FakeAnthropicClient.last_format['schema'],
        SUMMARY_JSON_SCHEMA,
    )
```

The fakes mirror the SDK response fields used by production: OpenAI `output_text`, `model`, `usage.input_tokens`, `usage.output_tokens`; Anthropic `content[].type/text`, `stop_reason`, `model`, `usage.input_tokens`, `usage.output_tokens`.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
cd inpa_be
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py test \
  inpa.consultations.tests.test_comparison_providers
```

Expected: imports fail because the comparison provider modules do not exist.

- [ ] **Step 3: Implement shared types and exact retry boundary**

```python
def retry_explicit_nonreceipt(operation, sleep=time.sleep):
    delays = (1, 2, 4)
    for attempt in range(len(delays) + 1):
        try:
            return operation()
        except ExplicitProviderNonReceipt:
            if attempt == len(delays):
                raise
            sleep(delays[attempt])
```

Provider adapters instantiate SDK clients with `max_retries=0`. Convert only a root `httpx.ConnectError` to `ExplicitProviderNonReceipt`; convert SDK timeout classes to `ComparisonOutcomeUnknown`; convert non-retryable HTTP/protocol/invalid-JSON errors to safe `ComparisonProviderFailure` codes.

- [ ] **Step 4: Implement OpenAI diarized transcription**

Use the SDK call:

```python
response = self.client.audio.transcriptions.create(
    file=audio_file,
    model=settings.OPENAI_TRANSCRIPTION_MODEL,
    response_format='diarized_json',
    chunking_strategy='auto',
    language='ko',
)
```

Map raw speaker IDs by first appearance to `화자 1`, `화자 2`, and so on. Strip empty segment text, reject an empty result with `TRANSCRIPT_EMPTY`, and record elapsed milliseconds with `time.monotonic()`. Do not pass prompts, log probabilities, or timestamp granularity to the diarization model.

- [ ] **Step 5: Implement equal-schema OpenAI and Anthropic summaries**

OpenAI uses:

```python
response = self.client.responses.create(
    model=settings.OPENAI_COMPARISON_MODEL,
    instructions=SYSTEM_PROMPT,
    input=masked_transcript,
    text={
        'format': {
            'type': 'json_schema',
            'name': 'consultation_summary',
            'strict': True,
            'schema': SUMMARY_JSON_SCHEMA,
        },
    },
    max_output_tokens=2_500,
    store=False,
)
```

Anthropic uses the existing `SYSTEM_PROMPT`, `SUMMARY_JSON_SCHEMA`, and the same `2_500` output-token ceiling but reads `ANTHROPIC_COMPARISON_MODEL`. Parse both through `ConsultationSummary.from_payload`; malformed or refused content is a provider failure and is never automatically regenerated.

- [ ] **Step 6: Verify GREEN and existing provider regression**

Run:

```bash
cd inpa_be
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py test \
  inpa.consultations.tests.test_comparison_providers \
  inpa.consultations.tests.test_anthropic_summary \
  inpa.consultations.tests.test_clova_provider
```

Expected: all tests pass, including unchanged production provider tests.

- [ ] **Step 7: Commit**

```bash
git add inpa_be/inpa/consultations/providers/comparison_base.py \
  inpa_be/inpa/consultations/providers/openai_comparison.py \
  inpa_be/inpa/consultations/providers/anthropic_comparison.py \
  inpa_be/inpa/consultations/tests/test_comparison_providers.py
git commit -m "feat(상담): OpenAI 전사와 이중 요약 공급자 추가"
```

### Task 3: 동일 전사문 병렬 비교 오케스트레이션

**Files:**
- Create: `inpa_be/inpa/consultations/comparison.py`
- Create: `inpa_be/inpa/consultations/tests/test_comparison_service.py`

**Interfaces:**
- Consumes: `prepare_comparison_audio(uploaded_file)`.
- Consumes: `OpenAIComparisonTranscriber`, `OpenAIComparisonSummarizer`, `AnthropicComparisonSummarizer`.
- Produces: `ConsultationComparisonService(transcriber=None, summarizers=None, shuffle=None)`.
- Produces: `ConsultationComparisonService.compare(uploaded_file) -> dict`.
- The returned dictionary has `transcript.segments[]` and exactly two `results[]` entries with `slot`, `provider`, `model`, `status`, `summary`, `latency_ms`, `input_tokens`, `output_tokens`, `error_code`.

- [ ] **Step 1: Write failing fairness and failure-isolation tests**

```python
def test_calls_transcriber_once_and_sends_identical_masked_text_to_both(self):
    transcriber = FakeTranscriber([
        ComparisonTranscriptSegment(
            speaker='화자 1',
            text='김고객 전화는 010-1234-5678입니다',
            start_seconds=0.0,
            end_seconds=2.0,
        ),
    ])
    first = CapturingSummarizer('openai')
    second = CapturingSummarizer('anthropic')

    payload = ConsultationComparisonService(
        transcriber=transcriber,
        summarizers=(first, second),
        shuffle=lambda rows: None,
    ).compare(make_upload())

    self.assertEqual(transcriber.calls, 1)
    self.assertEqual(first.received, second.received)
    self.assertNotIn('010-1234-5678', first.received)
    self.assertEqual([row['slot'] for row in payload['results']], ['A', 'B'])


def test_keeps_success_when_other_summary_provider_fails(self):
    payload = ConsultationComparisonService(
        transcriber=FakeTranscriber(valid_segments),
        summarizers=(
            SuccessfulSummarizer('openai'),
            FailingSummarizer('anthropic', ComparisonProviderFailure('PROVIDER_REJECTED')),
        ),
        shuffle=lambda rows: None,
    ).compare(make_upload())

    self.assertEqual(payload['results'][0]['status'], 'success')
    self.assertEqual(payload['results'][1]['status'], 'failed')
    self.assertIsNone(payload['results'][1]['summary'])


def test_does_not_start_summaries_after_transcription_failure(self):
    first = CapturingSummarizer('openai')
    second = CapturingSummarizer('anthropic')
    with self.assertRaises(ComparisonProviderFailure):
        ConsultationComparisonService(
            transcriber=FailingTranscriber(),
            summarizers=(first, second),
        ).compare(make_upload())
    self.assertEqual(first.calls + second.calls, 0)
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
cd inpa_be
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py test \
  inpa.consultations.tests.test_comparison_service
```

Expected: import failure for missing `inpa.consultations.comparison`.

- [ ] **Step 3: Implement masking, parallel execution, and random slots**

The service:

1. Opens `prepare_comparison_audio`.
2. Calls the transcriber once.
3. Applies `mask_transcript(segment.text, known_names=())` to each segment.
4. Builds one immutable summary input with `f'{speaker}: {text}'` rows joined by newline.
5. Runs the two summarizers through `ThreadPoolExecutor(max_workers=2)`.
6. Converts `ComparisonOutcomeUnknown` to `status='outcome_unknown'`; known failure to `status='failed'`; success to `status='success'`.
7. Shuffles only the two completed result dictionaries, then assigns `A` and `B`.
8. Returns masked segments only.

Every submitted future receives the exact same `masked_transcript` string. The service never catches transcription errors as partial summary results.

- [ ] **Step 4: Verify GREEN and cleanup on all service paths**

Run:

```bash
cd inpa_be
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py test \
  inpa.consultations.tests.test_comparison_service \
  inpa.consultations.tests.test_comparison_audio \
  inpa.consultations.tests.test_transcript_mask
```

Expected: all tests pass and each test that captures a prepared path sees it absent after return or exception.

- [ ] **Step 5: Commit**

```bash
git add inpa_be/inpa/consultations/comparison.py \
  inpa_be/inpa/consultations/tests/test_comparison_service.py
git commit -m "feat(상담): 동일 전사문 A/B 비교 서비스 추가"
```

### Task 4: 관리자 전용 multipart 비교 API

**Files:**
- Modify: `inpa_be/inpa/admin_console/serializers.py:775`
- Modify: `inpa_be/inpa/admin_console/views.py:66-90,2691`
- Modify: `inpa_be/inpa/admin_console/urls.py:15-30,73-83`
- Modify: `inpa_be/config/settings/base.py:110-120`
- Modify: `inpa_be/.env.example:74-78`
- Create: `inpa_be/inpa/consultations/tests/test_comparison_api.py`

**Interfaces:**
- Produces: `AdminConsultationComparisonSerializer` with required `audio=FileField` and required `synthetic_confirmed=BooleanField`.
- Produces: `AdminConsultationComparisonView.post`.
- Produces: `POST /api/v1/admin/consultations/comparison/`.
- Produces: DRF scope `consultation_comparison` with env rate `CONSULTATION_COMPARISON_RATE`, default `10/hour`.

- [ ] **Step 1: Write failing permission, gate, validation, and no-write tests**

```python
@override_settings(
    CONSULTATION_AI_COMPARISON_ENABLED=True,
    OPENAI_API_KEY='test-value',
    OPENAI_TRANSCRIPTION_MODEL='env-transcriber',
    OPENAI_COMPARISON_MODEL='env-openai-summary',
    ANTHROPIC_API_KEY='test-value',
    ANTHROPIC_COMPARISON_MODEL='env-anthropic-summary',
)
class AdminConsultationComparisonApiTests(APITestCase):
    url = '/api/v1/admin/consultations/comparison/'

    def test_anonymous_and_non_admin_cannot_spend_provider_cost(self):
        anonymous = self.client.post(self.url, {}, format='multipart')
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.user_token.key}')
        regular = self.client.post(self.url, {}, format='multipart')
        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(regular.status_code, 403)
        self.service.compare.assert_not_called()

    @override_settings(CONSULTATION_AI_COMPARISON_ENABLED=False)
    def test_closed_environment_gate_returns_before_external_call(self):
        response = self.post_as_admin(self.valid_payload())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['code'], 'CONSULTATION_COMPARISON_CLOSED')
        self.service.compare.assert_not_called()

    def test_requires_explicit_synthetic_confirmation(self):
        payload = self.valid_payload()
        payload['synthetic_confirmed'] = False
        response = self.post_as_admin(payload)
        self.assertEqual(response.status_code, 400)
        self.service.compare.assert_not_called()

    def test_success_does_not_create_product_rows(self):
        before = {
            'recordings': ConsultationRecording.objects.count(),
            'memos': CustomerMemo.objects.count(),
            'usage': UsageMeter.objects.count(),
            'orders': PaymentOrder.objects.count(),
        }
        response = self.post_as_admin(self.valid_payload())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(before, {
            'recordings': ConsultationRecording.objects.count(),
            'memos': CustomerMemo.objects.count(),
            'usage': UsageMeter.objects.count(),
            'orders': PaymentOrder.objects.count(),
        })
```

Patch `inpa.admin_console.views.ConsultationComparisonService` at the external service boundary; keep authentication, parsing, serializer validation, settings readiness checks, and response mapping real.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
cd inpa_be
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py test \
  inpa.consultations.tests.test_comparison_api
```

Expected: `404` for the new route or import failure for the missing view.

- [ ] **Step 3: Implement serializer, readiness checks, throttle, and route**

Request order is fixed:

1. DRF authentication.
2. `IsAdmin`.
3. `CONSULTATION_AI_COMPARISON_ENABLED`.
4. all five required key/model settings.
5. serializer and `synthetic_confirmed is True`.
6. comparison service.

Return safe errors:

```python
{
    'CONSULTATION_COMPARISON_CLOSED': (403, '내부 비교 설정을 켜면 바로 확인할 수 있어요.'),
    'CONSULTATION_COMPARISON_NOT_READY': (503, '두 AI 연결 설정을 마치면 비교를 시작할 수 있어요.'),
    'SYNTHETIC_CONFIRMATION_REQUIRED': (400, '가상 녹음 확인을 선택해 주세요.'),
    'TRANSCRIPTION_FAILED': (502, '음성을 글로 바꾸는 단계를 다시 시작해 주세요.'),
    'TRANSCRIPTION_OUTCOME_UNKNOWN': (502, '처리 상태를 확인한 뒤 새 비교를 시작해 주세요.'),
}
```

Map `ComparisonAudioError` to `400` with its safe code. Summary-side failures stay inside a successful `200` comparison payload.

- [ ] **Step 4: Verify GREEN and all consultation regressions**

Run:

```bash
cd inpa_be
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py test \
  inpa.consultations \
  inpa.admin_console.tests.AdminConsultationSettingsTest
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py check
```

Expected: all consultation tests and the existing admin consultation settings tests pass.

- [ ] **Step 5: Commit**

```bash
git add inpa_be/inpa/admin_console/serializers.py \
  inpa_be/inpa/admin_console/views.py \
  inpa_be/inpa/admin_console/urls.py \
  inpa_be/config/settings/base.py inpa_be/.env.example \
  inpa_be/inpa/consultations/tests/test_comparison_api.py
git commit -m "feat(관리자): 상담 AI 비교 API 추가"
```

### Task 5: 관리자 A/B 비교 화면과 평가 UX

**Files:**
- Create: `inpa_fe/app/admin/consultations/compare/page.tsx`
- Create: `inpa_fe/components/__tests__/admin-consultation-comparison-page.test.tsx`
- Modify: `inpa_fe/lib/adminApi.ts:30-70,1335-1445`
- Modify: `inpa_fe/app/admin/consultations/page.tsx:1-20,180-225`

**Interfaces:**
- Produces: `AdminConsultationComparisonResponse`.
- Produces: `adminCompareConsultation(audio: File, syntheticConfirmed: true)`.
- Produces: admin route `/admin/consultations/compare`.
- The page keeps file, confirmation, loading stage, response, per-slot evaluation flags, final selection, and reveal state only in React memory.

- [ ] **Step 1: Write failing client and page behavior tests**

```tsx
it("확인 전에는 비교를 시작하지 않고 다음 행동을 안내한다", async () => {
  render(<AdminConsultationComparisonPage />);
  fireEvent.change(screen.getByLabelText("가상 상담 음성"), {
    target: { files: [new File(["audio"], "synthetic.webm", { type: "audio/webm" })] },
  });
  fireEvent.click(screen.getByRole("button", { name: "비교 시작" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "가상 녹음 확인을 선택해 주세요",
  );
  expect(adminApi.adminCompareConsultation).not.toHaveBeenCalled();
});

it("A/B 결과는 평가 전 모델명을 가리고 선택 뒤 공개한다", async () => {
  adminApi.adminCompareConsultation.mockResolvedValue(successResponse);
  render(<AdminConsultationComparisonPage />);
  selectValidFileAndConfirm();
  fireEvent.click(screen.getByRole("button", { name: "비교 시작" }));

  expect(await screen.findByText("결과 A")).toBeInTheDocument();
  expect(screen.getByText("결과 B")).toBeInTheDocument();
  expect(screen.queryByText("env-openai-summary")).not.toBeInTheDocument();
  fireEvent.click(screen.getByLabelText("A 우세"));
  fireEvent.click(screen.getByRole("button", { name: "모델명 보기" }));
  expect(screen.getByText("env-openai-summary")).toBeInTheDocument();
  expect(screen.getByText("env-anthropic-summary")).toBeInTheDocument();
});

it("한쪽 실패에도 성공 결과와 공통 전사문을 유지한다", async () => {
  adminApi.adminCompareConsultation.mockResolvedValue(partialFailureResponse);
  render(<AdminConsultationComparisonPage />);
  selectValidFileAndConfirm();
  fireEvent.click(screen.getByRole("button", { name: "비교 시작" }));

  expect(await screen.findByText("상담 핵심")).toBeInTheDocument();
  expect(screen.getByText("한쪽 결과를 다시 확인해 주세요.")).toBeInTheDocument();
  fireEvent.click(screen.getByText("공통 전사문 보기"));
  expect(screen.getByText(/화자 1/)).toBeInTheDocument();
});
```

Add a client test that stubs `fetch`, calls `adminCompareConsultation`, and asserts the request body is `FormData`, includes `audio` and the string `"true"`, carries the auth header, and does not set `Content-Type` manually.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
cd inpa_fe
npm run test:run -- \
  components/__tests__/admin-consultation-comparison-page.test.tsx
```

Expected: import failures for the missing page and API function.

- [ ] **Step 3: Implement multipart admin client**

Add a `reqForm<T>(path: string, body: FormData)` helper alongside `req`. It sends `Authorization` when present, allows the browser to set the multipart boundary, normalizes errors with `normalizeAdminApiError`, and returns parsed JSON.

Use exact response types:

```ts
export interface AdminComparisonSummary {
  consultation_core: string[];
  customer_priorities: string[];
  items_to_confirm: string[];
  next_actions: string[];
}

export interface AdminComparisonResult {
  slot: "A" | "B";
  provider: "openai" | "anthropic";
  model: string;
  status: "success" | "failed" | "outcome_unknown";
  summary: AdminComparisonSummary | null;
  latency_ms: number;
  input_tokens: number;
  output_tokens: number;
  error_code: string;
}
```

- [ ] **Step 4: Implement the complete admin comparison state machine**

The page uses `useAdminGuard`, accepts only approved extensions, rejects files over `26214400` bytes before calling the API, prevents a second submit while loading, and clears previous results on a new file.

Loading messages advance with cleaned-up timers:

- immediately: `음성을 글로 바꾸고 있어요`
- after 8 seconds: `두 가지 요약을 만들고 있어요`
- after 25 seconds: `결과를 정리하고 있어요. 화면을 그대로 두면 이어집니다.`

Results use `grid gap-4 lg:grid-cols-2`, render only the four approved sections, keep transcript in a native `<details>`, and provide the five checkboxes for each slot. The `모델명 보기` button remains disabled until `A 우세`, `B 우세`, `동률`, or `판단 보류` is selected.

For a provider failure, render the slot and next action without raw `error_code`; reveal mode may show the safe status code with provider metadata. For total request failure, retain the chosen file and confirmation so the administrator can explicitly press `비교 시작` again.

- [ ] **Step 5: Add a discoverable link from consultation operations**

Import `Link` in `/admin/consultations/page.tsx` and add a secondary button in the header:

```tsx
<Link
  href="/admin/consultations/compare"
  className="min-h-11 rounded-xl border border-line bg-surface px-4 py-3 text-[13px] font-bold text-brand"
>
  상담 AI 비교
</Link>
```

Do not add a second sidebar item, so the existing `상담 녹음` navigation remains the single parent entry and no two entries appear active.

- [ ] **Step 6: Verify GREEN, copy, and production build**

Run:

```bash
cd inpa_fe
npm run test:run -- \
  components/__tests__/admin-consultation-comparison-page.test.tsx \
  components/__tests__/admin-consultations-page.test.tsx
npm run lint:copy
npm run build
```

Expected: all tests pass, copy lint has zero findings, and Next build lists `/admin/consultations/compare`.

- [ ] **Step 7: Commit**

```bash
git add inpa_fe/app/admin/consultations/compare/page.tsx \
  inpa_fe/components/__tests__/admin-consultation-comparison-page.test.tsx \
  inpa_fe/lib/adminApi.ts \
  inpa_fe/app/admin/consultations/page.tsx
git commit -m "feat(관리자): 상담 AI 블라인드 비교 화면 추가"
```

## Final Verification

- [ ] Run the complete backend suite:

```bash
cd inpa_be
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py check
/Users/kyungsbook/Desktop/inpa/inpa_be/.venv/bin/python manage.py test inpa
```

- [ ] Run the complete frontend suite and build:

```bash
cd inpa_fe
npm run test:run
npm run lint:copy
npm run build
```

- [ ] Verify dependency and secret state:

```bash
cd inpa_fe
npm audit --omit=dev
cd ..
git diff --check origin/master...HEAD
git status --short
```

- [ ] Start Django and make a multipart request with a generated synthetic WAV as an admin. With fake provider clients, verify `200`, masked transcript, two slots, and zero new consultation, memo, usage, or payment rows.
- [ ] With real API credentials only in a local or restricted preview environment, run one 3 to 5 minute synthetic consultation and verify one transcription plus one call per summary model. Do not place any credential or content in terminal output.
- [ ] Inspect application logs for the test window and verify they contain no file name, transcript, summary, or API key.
- [ ] Confirm `CONSULTATION_AI_COMPARISON_ENABLED`, `CONSULTATION_RECORDING_ENABLED`, and `CONSULTATION_AI_SUMMARY_ENABLED` remain `False` in committed defaults.
- [ ] Run a final adversarial review across correctness, privacy, cost duplication, API-key handling, accessibility, responsive UX, and unchanged production consultation behavior.
