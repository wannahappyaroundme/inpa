# 상담 녹음과 7일 보관 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 고객 본인 동의 뒤 최대 60분 상담을 비공개 R2에 안정적으로 업로드·재생하고, 녹음 종료 기준 최대 7일 안에 자동 삭제한다.

**Architecture:** 새 `consultations` Django 앱이 원음 상태와 전용 storage adapter를 소유한다. 브라우저는 `MediaRecorder` 조각을 8MiB R2 multipart part로 직접 올리고, 서버는 완료 뒤 실제 미디어 형식·길이·크기를 검증한다. 법적 환경변수 게이트와 관리자 운영 스위치를 AND로 적용한다.

**Tech Stack:** Django 5.2, DRF 3.16, boto3 1.40, Cloudflare R2 S3 API, PyAV 18, Next.js 16 Client Components, MediaRecorder, React 19, Vitest.

## Global Constraints

- `CONSULTATION_RECORDING_ENABLED` 기본값은 `False`다.
- 관리자 운영 스위치는 환경변수 게이트가 열렸을 때만 다시 켤 수 있다.
- 녹음 최대 60분, 100MiB, audio-only다.
- multipart part는 8MiB, 마지막 part만 8MiB보다 작을 수 있다.
- 원음 object key는 `consultation-recordings/{recording_uuid}/source`이며 owner·customer 식별자를 포함하지 않는다.
- 원음은 DB, Django media, Render disk, 일반 backup, Sentry에 저장하지 않는다.
- `expires_at`은 서버가 녹음 종료 시각을 기준으로 계산하고 정확히 7일을 넘지 않는다.
- 앱 삭제 예정 시각은 녹음 종료 후 6일 23시간 45분으로 잡고 15분 cleanup command를 돌려 최대 7일 경계를 넘지 않게 한다.
- R2 lifecycle은 6일로 설정한다. lifecycle 실행이 최대 24시간 늦어져도 7일 경계 안에 들어오는 2차 안전망이다.
- 업로드·재생·삭제 API는 owner scope와 별도 throttle을 적용한다.
- iPhone Safari, Android Chrome, Samsung Internet 실기기 검증 전 일반 공개하지 않는다.
- PM 요청 전에는 commit·프로덕션 배포·게이트 공개를 하지 않는다.

---

### Task 1: consultations 앱과 녹음 상태 모델

**Files:**
- Create: `inpa_be/inpa/consultations/__init__.py`
- Create: `inpa_be/inpa/consultations/apps.py`
- Create: `inpa_be/inpa/consultations/models.py`
- Create: `inpa_be/inpa/consultations/migrations/__init__.py`
- Modify: `inpa_be/config/settings/base.py`
- Modify: `inpa_be/config/urls.py`
- Test: `inpa_be/inpa/consultations/tests/test_models.py`

**Interfaces:**
- Produces: `ConsultationRecording`, `ConsultationRuntimeConfig`, `ConsultationPilotAccess`.
- Produces settings: retention, size, duration, part size, presign TTL, dual gates.

- [ ] **Step 1: Write failing state and expiry tests**

```python
class ConsultationRecordingModelTests(TestCase):
    def test_ready_recording_expiry_is_server_stamped_within_seven_days(self):
        ended_at = timezone.now()
        recording = ConsultationRecording.objects.create(
            owner=self.user, customer=self.customer,
            status=ConsultationRecording.STATUS_UPLOADING,
            storage_key=f'consultation-recordings/{uuid.uuid4()}/source',
            multipart_upload_id='upload-1', mime_type='audio/webm')
        recording.mark_ready(
            ended_at=ended_at, byte_size=8_000_000,
            duration_ms=3_600_000, checksum='sha256:abc')
        self.assertEqual(recording.status, ConsultationRecording.STATUS_READY)
        self.assertLessEqual(recording.expires_at, ended_at + timedelta(days=7))
        self.assertGreater(recording.expires_at, ended_at + timedelta(days=6, hours=23))

    def test_runtime_switch_cannot_open_closed_environment_gate(self):
        config = ConsultationRuntimeConfig.solo()
        config.recording_enabled = True
        config.save(update_fields=['recording_enabled'])
        with override_settings(CONSULTATION_RECORDING_ENABLED=False):
            self.assertFalse(recording_feature_enabled())
```

- [ ] **Step 2: Run and verify missing app failure**

Run: `cd inpa_be && python manage.py test inpa.consultations.tests.test_models -v 2`

Expected: module not found로 FAIL.

- [ ] **Step 3: Add app settings and models**

```python
CONSULTATION_RECORDING_ENABLED = env.bool(
    'CONSULTATION_RECORDING_ENABLED', default=False)
CONSULTATION_RETENTION_HOURS = env.int(
    'CONSULTATION_RETENTION_HOURS', default=168)
CONSULTATION_RETENTION_SAFETY_MINUTES = env.int(
    'CONSULTATION_RETENTION_SAFETY_MINUTES', default=15)
CONSULTATION_MAX_DURATION_SECONDS = env.int(
    'CONSULTATION_MAX_DURATION_SECONDS', default=3600)
CONSULTATION_MAX_BYTES = env.int(
    'CONSULTATION_MAX_BYTES', default=100 * 1024 * 1024)
CONSULTATION_UPLOAD_PART_BYTES = env.int(
    'CONSULTATION_UPLOAD_PART_BYTES', default=8 * 1024 * 1024)
CONSULTATION_PRESIGN_TTL_SECONDS = env.int(
    'CONSULTATION_PRESIGN_TTL_SECONDS', default=600)
```

```python
class ConsultationRecording(models.Model):
    STATUS_UPLOADING = 'uploading'
    STATUS_READY = 'ready'
    STATUS_PROCESSING = 'processing'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'
    STATUS_AMBIGUOUS = 'ambiguous'
    STATUS_DELETING = 'deleting'
    STATUS_DELETED = 'deleted'
    STATUS_CHOICES = tuple((value, value) for value in (
        STATUS_UPLOADING, STATUS_READY, STATUS_PROCESSING, STATUS_COMPLETED,
        STATUS_FAILED, STATUS_AMBIGUOUS, STATUS_DELETING, STATUS_DELETED))

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name='consultation_recordings')
    customer = models.ForeignKey('customers.Customer', on_delete=models.CASCADE,
                                 related_name='consultation_recordings')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, db_index=True)
    storage_key = models.CharField(max_length=180, unique=True, null=True, blank=True)
    multipart_upload_id = models.CharField(max_length=512, blank=True, default='')
    mime_type = models.CharField(max_length=80)
    codec = models.CharField(max_length=80, blank=True, default='')
    byte_size = models.PositiveBigIntegerField(default=0)
    duration_ms = models.PositiveBigIntegerField(default=0)
    checksum = models.CharField(max_length=100, blank=True, default='')
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    uploaded_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    delete_reason = models.CharField(max_length=40, blank=True, default='')
    delete_result = models.CharField(max_length=40, blank=True, default='')
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'consultation_recording'
        indexes = [
            models.Index(fields=['owner', 'customer', '-created_at']),
            models.Index(fields=['status', 'expires_at']),
        ]

    def mark_ready(self, *, ended_at, byte_size, duration_ms, checksum):
        if self.status != self.STATUS_UPLOADING:
            raise ValueError('INVALID_RECORDING_TRANSITION')
        self.status = self.STATUS_READY
        self.ended_at = ended_at
        self.uploaded_at = timezone.now()
        retention = timedelta(
            hours=min(settings.CONSULTATION_RETENTION_HOURS, 168))
        safety = timedelta(minutes=max(
            settings.CONSULTATION_RETENTION_SAFETY_MINUTES, 15))
        self.expires_at = ended_at + retention - safety
        self.byte_size = byte_size
        self.duration_ms = duration_ms
        self.checksum = checksum
        self.multipart_upload_id = ''
        self.version += 1
        self.save()
```

```python
class ConsultationRuntimeConfig(models.Model):
    recording_enabled = models.BooleanField(default=False)
    max_duration_seconds = models.PositiveIntegerField(default=3600)
    max_bytes = models.PositiveBigIntegerField(default=100 * 1024 * 1024)
    global_active_limit = models.PositiveSmallIntegerField(default=20)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def solo(cls):
        return cls.objects.get_or_create(pk=1)[0]


class ConsultationPilotAccess(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    recording_allowed = models.BooleanField(default=False)
    summary_allowed = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
```

- [ ] **Step 4: Register the app and generate migration**

Add `'inpa.consultations'` to `INSTALLED_APPS` and `path('api/v1/', include('inpa.consultations.urls'))` after the app URL file exists in Task 4.

Run: `cd inpa_be && python manage.py makemigrations consultations && python manage.py migrate`

Expected: initial consultations migration 생성·적용 성공.

- [ ] **Step 5: Implement the dual-gate helper and run tests**

```python
def recording_feature_enabled(user=None):
    if not settings.CONSULTATION_RECORDING_ENABLED:
        return False
    if not ConsultationRuntimeConfig.solo().recording_enabled:
        return False
    if user is None or getattr(getattr(user, 'profile', None), 'is_admin', False):
        return True
    access = ConsultationPilotAccess.objects.filter(user=user).first()
    return bool(access and access.recording_allowed)
```

Run: `cd inpa_be && python manage.py test inpa.consultations.tests.test_models -v 2`

Expected: PASS.

- [ ] **Step 6: Commit only after PM asks**

```bash
git add inpa_be/inpa/consultations inpa_be/config/settings/base.py inpa_be/config/urls.py
git commit -m "feat(녹음): 상담 녹음 도메인 추가"
```

### Task 2: 고객 본인 녹음·민감정보 동의 범위

**Files:**
- Modify: `inpa_be/inpa/customers/models.py`
- Modify: `inpa_be/inpa/customers/consent_texts.py`
- Modify: `inpa_be/inpa/customers/public_consent.py`
- Modify: `inpa_be/inpa/customers/views.py`
- Create: `inpa_be/inpa/customers/migrations/0017_consultation_consent_scopes.py`
- Test: `inpa_be/inpa/customers/tests.py`
- Modify: `inpa_fe/app/c/[token]/page.tsx`
- Modify: `inpa_fe/lib/api.ts`

**Interfaces:**
- Produces scopes: `consultation_recording`, `consultation_sensitive`.
- Produces: `has_current_consultation_recording_consent(customer)`.

- [ ] **Step 1: Write failing current-version consent tests**

```python
def test_only_customer_self_current_consents_open_recording(self):
    for scope in ('consultation_recording', 'consultation_sensitive'):
        ConsentLog.objects.create(
            customer=self.customer, scope=scope,
            subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
            doc_version=CONSULTATION_CONSENT_VERSIONS[scope])
    self.assertTrue(has_current_consultation_recording_consent(self.customer))
    ConsentLog.objects.filter(scope='consultation_sensitive').update(revoked_at=timezone.now())
    self.assertFalse(has_current_consultation_recording_consent(self.customer))

```

- [ ] **Step 2: Add scope constants and versioned copy**

```python
SCOPE_CONSULTATION_RECORDING = 'consultation_recording'
SCOPE_CONSULTATION_SENSITIVE = 'consultation_sensitive'
```

```python
CONSULTATION_CONSENT_VERSIONS = {
    ConsentLog.SCOPE_CONSULTATION_RECORDING: 'v1-2026-07-22',
    ConsentLog.SCOPE_CONSULTATION_SENSITIVE: 'v1-2026-07-22',
}

CONSULTATION_CONSENT_TEXTS = {
    ConsentLog.SCOPE_CONSULTATION_RECORDING: {
        'title': '상담 녹음과 원본 보관',
        'body': '상담 내용을 메모로 정리하기 위해 녹음합니다. 원본 녹음은 인파에서 최대 7일 보관한 뒤 자동 삭제됩니다.',
        'required': True,
    },
    ConsentLog.SCOPE_CONSULTATION_SENSITIVE: {
        'title': '상담 중 민감정보 처리',
        'body': '상담 중 건강 등 민감한 내용이 포함될 수 있으며, 상담 메모 작성 목적으로 처리됩니다.',
        'required': True,
    },
}
```

- [ ] **Step 3: Add the current-consent helper**

```python
def has_current_consultation_recording_consent(customer):
    for scope, version in CONSULTATION_CONSENT_VERSIONS.items():
        if not ConsentLog.objects.filter(
            customer=customer, scope=scope,
            subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
            doc_version=version, revoked_at__isnull=True,
        ).exists():
            return False
    return True
```

`PublicConsentView`의 item 정의와 `ConsentRequestCreateView._ALLOWED_REQUEST_SCOPES`에 두 scope를 추가한다. POST는 token에 담긴 scope만 기록하는 기존 위조 방지 계약을 그대로 사용한다.

- [ ] **Step 4: Generate migration and run consent tests**

Run: `cd inpa_be && python manage.py makemigrations customers && python manage.py test inpa.customers -v 1`

Expected: 기존 동의 테스트와 새 상담 동의 테스트 모두 PASS.

- [ ] **Step 5: Render the two new items without exposing internal gates**

`/c/[token]`은 API의 `items[]`를 그대로 렌더하므로 하드코딩된 scope union만 아래처럼 확장한다.

```ts
export type ConsentScope =
  | 'personal_info'
  | 'marketing'
  | 'overseas_medical'
  | 'consultation_recording'
  | 'consultation_sensitive'
  | 'consultation_overseas_summary';
```

Run: `cd inpa_fe && npm run test:run -- components/__tests__/share-public.test.tsx && npm run build`

Expected: 공개 동의 화면 build PASS, 두 상담 항목은 token scope에 있을 때만 표시.

- [ ] **Step 6: Commit only after PM asks**

```bash
git add inpa_be/inpa/customers inpa_fe/app/c/[token]/page.tsx inpa_fe/lib/api.ts
git commit -m "feat(동의): 상담 녹음 고객 본인 동의 추가"
```

### Task 3: 전용 R2 multipart storage adapter

**Files:**
- Create: `inpa_be/inpa/consultations/storage.py`
- Modify: `inpa_be/config/settings/base.py`
- Modify: `inpa_be/requirements.txt`
- Test: `inpa_be/inpa/consultations/tests/test_storage.py`

**Interfaces:**
- Produces: `RecordingStorage.create`, `presign_part`, `complete`, `abort`, `head`, `presign_get`, `delete`, `iter_object`.
- Consumes dedicated `CONSULTATION_STORAGE_*` environment variables.

- [ ] **Step 1: Write failing adapter contract tests with a fake S3 client**

```python
def test_storage_uses_uuid_only_namespace_and_short_presigned_urls(self):
    recording_id = uuid.uuid4()
    storage = R2RecordingStorage(client=self.client, bucket='private-audio')
    result = storage.create(recording_id, 'audio/webm')
    self.assertEqual(result.key, f'consultation-recordings/{recording_id}/source')
    self.assertNotIn('@', result.key)
    storage.presign_part(result.key, result.upload_id, part_number=1)
    self.client.generate_presigned_url.assert_called_once_with(
        'upload_part', Params={'Bucket': 'private-audio', 'Key': result.key,
                               'UploadId': result.upload_id, 'PartNumber': 1},
        ExpiresIn=600)

def test_complete_rejects_non_uniform_or_small_nonfinal_parts(self):
    with self.assertRaises(InvalidMultipartParts):
        validate_parts([
            UploadedPart(1, 'etag-1', 4 * 1024 * 1024),
            UploadedPart(2, 'etag-2', 1 * 1024 * 1024),
        ], part_bytes=8 * 1024 * 1024, max_bytes=100 * 1024 * 1024)
```

- [ ] **Step 2: Add pinned media dependency and environment settings**

```text
av==18.0.0
```

```python
CONSULTATION_STORAGE_BUCKET = env('CONSULTATION_STORAGE_BUCKET', default='')
CONSULTATION_STORAGE_ENDPOINT = env('CONSULTATION_STORAGE_ENDPOINT', default='')
CONSULTATION_STORAGE_REGION = env('CONSULTATION_STORAGE_REGION', default='auto')
CONSULTATION_STORAGE_ACCESS_KEY_ID = env('CONSULTATION_STORAGE_ACCESS_KEY_ID', default='')
CONSULTATION_STORAGE_SECRET_ACCESS_KEY = env('CONSULTATION_STORAGE_SECRET_ACCESS_KEY', default='')
```

- [ ] **Step 3: Implement the adapter contract**

```python
@dataclass(frozen=True)
class MultipartSession:
    key: str
    upload_id: str


@dataclass(frozen=True)
class UploadedPart:
    part_number: int
    etag: str
    byte_size: int


def validate_parts(parts, *, part_bytes, max_bytes):
    ordered = sorted(parts, key=lambda item: item.part_number)
    if not ordered or [item.part_number for item in ordered] != list(range(1, len(ordered) + 1)):
        raise InvalidMultipartParts
    if any(item.byte_size != part_bytes for item in ordered[:-1]):
        raise InvalidMultipartParts
    if ordered[-1].byte_size <= 0 or ordered[-1].byte_size > part_bytes:
        raise InvalidMultipartParts
    if sum(item.byte_size for item in ordered) > max_bytes:
        raise InvalidMultipartParts
    return ordered


class R2RecordingStorage:
    prefix = 'consultation-recordings'

    def create(self, recording_id, mime_type):
        key = f'{self.prefix}/{recording_id}/source'
        response = self.client.create_multipart_upload(
            Bucket=self.bucket, Key=key, ContentType=mime_type,
            Metadata={'retention': '7-days'})
        return MultipartSession(key=key, upload_id=response['UploadId'])

    def presign_part(self, key, upload_id, part_number):
        return self.client.generate_presigned_url(
            'upload_part', Params={'Bucket': self.bucket, 'Key': key,
                                   'UploadId': upload_id, 'PartNumber': part_number},
            ExpiresIn=settings.CONSULTATION_PRESIGN_TTL_SECONDS)

    def complete(self, key, upload_id, parts):
        return self.client.complete_multipart_upload(
            Bucket=self.bucket, Key=key, UploadId=upload_id,
            MultipartUpload={'Parts': [
                {'PartNumber': part.part_number, 'ETag': part.etag} for part in parts]})

    def delete(self, key):
        self.client.delete_object(Bucket=self.bucket, Key=key)
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response.get('ResponseMetadata', {}).get('HTTPStatusCode') == 404:
                return
            raise
        raise RecordingDeleteVerificationFailed
```

다음 메서드를 같은 class에 추가한다.

```python
    def abort(self, key, upload_id):
        self.client.abort_multipart_upload(
            Bucket=self.bucket, Key=key, UploadId=upload_id)

    def head(self, key):
        return self.client.head_object(Bucket=self.bucket, Key=key)

    def iter_object(self, key, chunk_size=1024 * 1024):  # gitleaks:allow
        body = self.client.get_object(Bucket=self.bucket, Key=key)['Body']
        try:
            for chunk in iter(lambda: body.read(chunk_size), b''):
                yield chunk
        finally:
            body.close()

    def presign_get(self, key):
        return self.client.generate_presigned_url(
            'get_object', Params={
                'Bucket': self.bucket, 'Key': key,
                'ResponseContentDisposition': 'inline'}, ExpiresIn=300)
```

- [ ] **Step 4: Run adapter tests**

Run: `cd inpa_be && python manage.py test inpa.consultations.tests.test_storage -v 2`

Expected: namespace·part validation·presign·complete·delete verification PASS.

- [ ] **Step 5: Commit only after PM asks**

```bash
git add inpa_be/inpa/consultations/storage.py inpa_be/inpa/consultations/tests/test_storage.py inpa_be/config/settings/base.py inpa_be/requirements.txt
git commit -m "feat(녹음): 비공개 R2 분할 업로드 추가"
```

### Task 4: 업로드·검증·재생·조기 삭제 API

**Files:**
- Create: `inpa_be/inpa/consultations/serializers.py`
- Create: `inpa_be/inpa/consultations/services.py`
- Create: `inpa_be/inpa/consultations/views.py`
- Create: `inpa_be/inpa/consultations/urls.py`
- Test: `inpa_be/inpa/consultations/tests/test_api.py`
- Test: `inpa_be/inpa/consultations/tests/test_concurrency.py`

**Interfaces:**
- Produces recording-list, capability, upload-session, part-url, complete, detail, play-url, source-delete endpoints.
- Consumes `RecordingStorage` and current customer-self consents.

- [ ] **Step 1: Write failing gate, owner, idempotency, validation, and delete tests**

```python
def test_upload_session_requires_gate_owner_and_both_current_consents(self):
    response = self.client.post(f'/api/v1/customers/{self.customer.id}/recordings/upload-sessions/', {
        'mime_type': 'audio/webm', 'started_at': timezone.now().isoformat()}, format='json')
    self.assertEqual(response.status_code, 412)
    self.assertEqual(response.data['code'], 'CONSULTATION_CONSENT_REQUIRED')

def test_complete_is_idempotent_and_server_validates_actual_media(self):
    first = self.client.post(self.complete_url, self.valid_parts, format='json')
    second = self.client.post(self.complete_url, self.valid_parts, format='json')
    self.assertEqual(first.status_code, 200)
    self.assertEqual(second.data['id'], first.data['id'])
    self.assertEqual(self.storage.complete.call_count, 1)

def test_play_and_delete_foreign_owner_are_404(self):
    self.client.force_authenticate(self.other_user)
    self.assertEqual(self.client.post(self.play_url).status_code, 404)
    self.assertEqual(self.client.delete(self.delete_url).status_code, 404)

def test_recording_list_restores_ready_and_deleted_metadata_after_reload(self):
    response = self.client.get(
        f'/api/v1/customers/{self.customer.id}/recordings/?page=1')
    self.assertEqual(response.status_code, 200)
    self.assertEqual(response.data['count'], 2)
    self.assertNotIn('storage_key', response.data['results'][0])
```

- [ ] **Step 2: Add response serializers**

```python
class ConsultationRecordingSerializer(serializers.ModelSerializer):
    source_available = serializers.SerializerMethodField()

    class Meta:
        model = ConsultationRecording
        fields = ('id', 'status', 'mime_type', 'codec', 'byte_size', 'duration_ms',
                  'started_at', 'ended_at', 'uploaded_at', 'expires_at', 'deleted_at',
                  'delete_reason', 'source_available', 'version')
        read_only_fields = fields

    def get_source_available(self, obj):
        return obj.status not in (obj.STATUS_DELETING, obj.STATUS_DELETED) and bool(obj.storage_key)
```

- [ ] **Step 3: Implement media inspection without retaining a local copy**

```python
def inspect_audio(fileobj):
    hasher = hashlib.sha256()
    with tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024) as temp:
        size = 0
        for chunk in iter(lambda: fileobj.read(1024 * 1024), b''):
            size += len(chunk)
            if size > settings.CONSULTATION_MAX_BYTES:
                raise InvalidRecording('RECORDING_TOO_LARGE')
            hasher.update(chunk)
            temp.write(chunk)
        temp.seek(0)
        with av.open(temp, mode='r') as container:
            audio_streams = [stream for stream in container.streams if stream.type == 'audio']
            if len(audio_streams) != 1 or any(stream.type == 'video' for stream in container.streams):
                raise InvalidRecording('AUDIO_ONLY_REQUIRED')
            duration_ms = int((container.duration or 0) / av.time_base * 1000)
            codec = audio_streams[0].codec_context.name or ''
        if duration_ms <= 0 or duration_ms > settings.CONSULTATION_MAX_DURATION_SECONDS * 1000:
            raise InvalidRecording('RECORDING_DURATION_INVALID')
        return AudioInspection(size, duration_ms, codec, f'sha256:{hasher.hexdigest()}')
```

- [ ] **Step 4: Implement exact state-locked endpoint behavior**

```python
class UploadSessionView(CustomerRecordingMixin, APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'consultation_upload'

    def post(self, request, customer_pk):
        customer = self.get_customer(customer_pk)
        if not recording_feature_enabled(request.user):
            return Response({'code': 'CONSULTATION_RECORDING_CLOSED',
                             'detail': '메모 작성으로 상담 내용을 바로 남길 수 있어요.'}, status=403)
        if not has_current_consultation_recording_consent(customer):
            return Response({'code': 'CONSULTATION_CONSENT_REQUIRED',
                             'detail': '고객 동의를 먼저 받으면 상담 녹음을 시작할 수 있어요.'}, status=412)
        mime_type = request.data.get('mime_type', '')
        if mime_type not in ALLOWED_RECORDING_MIME_TYPES:
            raise ValidationError({'mime_type': '이 브라우저의 녹음 형식을 확인해 주세요.'})
        recording = create_upload_session(
            owner=request.user, customer=customer, mime_type=mime_type,
            started_at=parse_datetime(request.data.get('started_at', '')))
        return Response(UploadSessionSerializer(recording).data, status=201)
```

`create_upload_session`은 user/customer active upload를 `select_for_update`로 확인하고 storage multipart를 만든 뒤 DB row를 저장한다. part URL은 순번 1-13만 발급한다. complete는 row lock 뒤 part 목록 검증 → storage complete → object HEAD → `inspect_audio` → `mark_ready` 순서이며, 같은 ready row 요청은 현재 serializer를 반환한다. play URL과 delete는 ready 이후 exact key만 사용한다.

- [ ] **Step 5: Register routes and throttle rates**

```python
urlpatterns = [
    path('customers/<int:customer_pk>/recordings/', RecordingListView.as_view()),
    path('customers/<int:customer_pk>/recordings/capability/', RecordingCapabilityView.as_view()),
    path('customers/<int:customer_pk>/recordings/upload-sessions/', UploadSessionView.as_view()),
    path('customers/<int:customer_pk>/recordings/<uuid:recording_id>/', RecordingDetailView.as_view()),
    path('customers/<int:customer_pk>/recordings/<uuid:recording_id>/parts/<int:part_number>/', RecordingPartURLView.as_view()),
    path('customers/<int:customer_pk>/recordings/<uuid:recording_id>/complete-upload/', CompleteUploadView.as_view()),
    path('customers/<int:customer_pk>/recordings/<uuid:recording_id>/play-url/', RecordingPlayURLView.as_view()),
    path('customers/<int:customer_pk>/recordings/<uuid:recording_id>/source/', RecordingSourceDeleteView.as_view()),
]
```

`RecordingListView`는 owner-scoped customer를 먼저 조회하고 `-created_at` 순으로 페이지네이션한다. deleted metadata도 반환해 화면 재접속 뒤 `원본 녹음은 보관을 마치고 삭제됐어요.` 상태를 복구하되, `storage_key`, checksum, multipart id는 serializer에 포함하지 않는다.

```python
CONSULTATION_THROTTLE_RATES = {
    'consultation_upload': env('CONSULTATION_UPLOAD_RATE', default='30/hour'),
    'consultation_play': env('CONSULTATION_PLAY_RATE', default='120/hour'),
}
```

- [ ] **Step 6: Run API and concurrency tests**

Run: `cd inpa_be && python manage.py test inpa.consultations.tests.test_api inpa.consultations.tests.test_concurrency -v 2`

Expected: gate·consent·404·multipart·actual media·idempotency·double complete tests PASS.

- [ ] **Step 7: Commit only after PM asks**

```bash
git add inpa_be/inpa/consultations inpa_be/config/settings/base.py
git commit -m "feat(녹음): 업로드 재생 삭제 API 추가"
```

### Task 5: 7일 자동 삭제와 fail-closed 운영

**Files:**
- Create: `inpa_be/inpa/consultations/cleanup.py`
- Create: `inpa_be/inpa/consultations/signals.py`
- Create: `inpa_be/inpa/consultations/management/commands/cleanup_consultation_recordings.py`
- Create: `inpa_be/inpa/consultations/management/commands/audit_consultation_storage.py`
- Modify: `render.yaml`
- Test: `inpa_be/inpa/consultations/tests/test_cleanup.py`

**Interfaces:**
- Produces: `cleanup_expired_recordings(now, limit)`, 15-minute cron, storage audit.

- [ ] **Step 1: Write failing boundary, retry, and circuit-breaker tests**

```python
def test_cleanup_never_deletes_before_expiry_and_verifies_after_expiry(self):
    cleanup_expired_recordings(now=self.recording.expires_at - timedelta(seconds=1), limit=100)
    self.storage.delete.assert_not_called()
    cleanup_expired_recordings(now=self.recording.expires_at, limit=100)
    self.storage.delete.assert_called_once_with(self.recording.storage_key)
    self.recording.refresh_from_db()
    self.assertEqual(self.recording.status, 'deleted')
    self.assertIsNone(self.recording.storage_key)

def test_overdue_or_repeated_delete_failure_closes_runtime_uploads(self):
    self.storage.delete.side_effect = RecordingDeleteVerificationFailed
    for _ in range(3):
        cleanup_expired_recordings(now=self.recording.expires_at + timedelta(hours=1), limit=100)
    self.assertFalse(ConsultationRuntimeConfig.solo().recording_enabled)

def test_customer_delete_enqueues_exact_random_keys_before_cascade(self):
    key = self.recording.storage_key
    self.customer.delete()
    self.delete_exact_sources.assert_called_once()
    self.assertEqual(self.delete_exact_sources.call_args.args[0][0]['storage_key'], key)

def test_public_revocation_schedules_immediate_source_deletion(self):
    response = self.client.post(self.public_url, {
        'revoked': ['consultation_recording']}, format='json')
    self.assertEqual(response.status_code, 200)
    self.delete_customer_sources.assert_called_once_with(
        self.customer.id, reason='consent_revoked')
```

- [ ] **Step 2: Implement system-stamped deletion selection**

```python
def cleanup_expired_recordings(*, now=None, limit=200, storage=None):
    now = now or timezone.now()
    storage = storage or get_recording_storage()
    ids = list(ConsultationRecording.objects.filter(
        expires_at__isnull=False, expires_at__lte=now,
        status__in=SOURCE_PRESENT_STATUSES,
    ).order_by('expires_at').values_list('id', flat=True)[:limit])
    for recording_id in ids:
        with transaction.atomic():
            recording = ConsultationRecording.objects.select_for_update().get(pk=recording_id)
            if recording.expires_at is None or recording.expires_at > now:
                continue
            exact_key = recording.storage_key
            if not exact_key:
                continue
            recording.status = ConsultationRecording.STATUS_DELETING
            recording.version += 1
            recording.save(update_fields=['status', 'version', 'updated_at'])
        try:
            storage.delete(exact_key)
        except Exception as exc:
            record_delete_failure(recording_id, type(exc).__name__, now)
            continue
        mark_source_deleted(recording_id, reason='retention_expired', now=now)
```

`mark_source_deleted`는 row lock 뒤 `storage_key=None`, `checksum=''`, `status='deleted'`, `deleted_at=now`, `delete_reason`, `delete_result='verified_absent'`를 한 번에 저장한다. 이미 deleted인 행은 같은 결과를 반환한다. `expires_at` 이후에는 cleanup 실행 전이라도 play URL을 발급하지 않는다.

고객·계정 삭제는 DB cascade가 object key를 지우기 전에 `pre_delete` signal이 random exact key와 multipart upload id만 복사해 commit 뒤 삭제 task에 전달한다. task payload에는 owner/customer ID나 이름을 넣지 않는다.

```python
@receiver(pre_delete, sender=Customer)
def delete_consultation_sources_with_customer(sender, instance, **kwargs):
    sources = list(instance.consultation_recordings.exclude(
        storage_key__isnull=True).values('storage_key', 'multipart_upload_id'))
    if sources:
        transaction.on_commit(lambda values=sources:
            delete_exact_sources.delay(values, reason='customer_deleted'))
```

`ConsultationsConfig.ready()`에서 `from . import signals`를 실행한다. account 삭제는 Customer cascade가 같은 signal을 발생시키므로 별도 broad user signal을 만들지 않는다.

`delete_customer_sources(customer_id, reason)` Celery task는 해당 고객의 source-present row UUID를 먼저 조회한 뒤 각 row에 `delete_recording_source(recording_id, reason)`를 호출한다. uploading row면 multipart를 abort하고, ready 이후 row면 object delete와 HEAD 부재를 확인한다. `PublicConsentView._apply_revocations`가 녹음 또는 민감정보 scope를 철회하면 아래 hook으로 commit 뒤 task를 예약한다. Task 2에서는 아직 이 task를 참조하지 않고, 이 Task에서 hook과 회귀 테스트를 함께 추가한다.

```python
if scope in {
    ConsentLog.SCOPE_CONSULTATION_RECORDING,
    ConsentLog.SCOPE_CONSULTATION_SENSITIVE,
}:
    transaction.on_commit(lambda customer_id=customer.id:
        delete_customer_sources.delay(customer_id, reason='consent_revoked'))
```

삭제 선택은 user-editable 필드가 아닌 server-stamped `expires_at`, 상태, exact key 세 조건을 모두 사용한다. 실패 로그에는 recording UUID와 exception type만 기록한다.

- [ ] **Step 3: Add command and 15-minute Blueprint cron**

```python
class Command(BaseCommand):
    def handle(self, *args, **options):
        result = cleanup_expired_recordings(limit=500)
        self.stdout.write(json.dumps(result, sort_keys=True))
```

```yaml
  - type: cron
    name: inpa-consultation-recording-cleanup
    runtime: python
    rootDir: inpa_be
    schedule: "*/15 * * * *"
    buildCommand: pip install -r requirements.txt
    startCommand: python manage.py cleanup_consultation_recordings
```

cron에 DB와 `CONSULTATION_STORAGE_*` env를 web service와 동일한 `fromService` 또는 `sync: false` secret으로 연결한다. 법적 feature gate는 cleanup 실행 조건으로 사용하지 않는다.

- [ ] **Step 4: Add the content-safe audit**

`audit_consultation_storage`는 DB의 source-present UUID key 집합과 R2 prefix key 집합을 비교해 `missing_db_object`, `orphan_object`, `overdue_object` 개수와 UUID만 출력한다. `--apply`가 있을 때 orphan exact key를 삭제하며 기본 실행은 read-only다.

- [ ] **Step 5: Run cleanup tests**

Run: `cd inpa_be && python manage.py test inpa.consultations.tests.test_cleanup -v 2 && python manage.py cleanup_consultation_recordings`

Expected: boundary·retry·fail-closed PASS, local command JSON 출력.

- [ ] **Step 6: Commit only after PM asks**

```bash
git add inpa_be/inpa/consultations/cleanup.py inpa_be/inpa/consultations/management render.yaml inpa_be/inpa/consultations/tests/test_cleanup.py
git commit -m "feat(녹음): 원본 7일 자동 삭제 추가"
```

### Task 6: 브라우저 녹음·분할 업로드 상태 머신

**Files:**
- Create: `inpa_fe/components/consultation-recorder/use-consultation-recorder.ts`
- Create: `inpa_fe/components/consultation-recorder/upload-parts.ts`
- Create: `inpa_fe/components/consultation-recorder/recorder-types.ts`
- Create: `inpa_fe/components/consultation-recorder/recorder-provider.tsx`
- Modify: `inpa_fe/app/layout.tsx`
- Modify: `inpa_fe/lib/api.ts`
- Test: `inpa_fe/components/consultation-recorder/use-consultation-recorder.test.ts`
- Test: `inpa_fe/components/consultation-recorder/upload-parts.test.ts`

**Interfaces:**
- Produces state: `idle | requesting_permission | recording | paused | stopping | uploading | ready | interrupted | error`.
- Produces `RecorderSessionContextValue`, `start(customerId)`, `pause`, `resume`, `stop`, `discard`, upload progress.

- [ ] **Step 1: Write failing MIME selection, 8MiB buffering, and timer tests**

```ts
test('chooses the first browser-supported audio type', () => {
  const supported = (value: string) => value === 'audio/mp4';
  assert.equal(selectRecordingMimeType(supported), 'audio/mp4');
});

test('emits uniform 8MiB parts and one smaller final part', async () => {
  const parts = await collectUploadParts([
    new Blob([new Uint8Array(5 * MIB)]),
    new Blob([new Uint8Array(5 * MIB)]),
    new Blob([new Uint8Array(1 * MIB)]),
  ], 8 * MIB);
  assert.deepEqual(parts.map((part) => part.size), [8 * MIB, 3 * MIB]);
});

test('stops at 60 minutes and emits 45, 55, and 59 minute notices', () => {
  assert.equal(recordingNotice(45 * 60), '45분 동안 녹음했어요.');
  assert.equal(recordingNotice(55 * 60), '5분 뒤 녹음이 마무리돼요.');
  assert.equal(recordingNotice(59 * 60), '1분 뒤 녹음이 마무리돼요.');
  assert.equal(shouldAutoStop(60 * 60), true);
});
```

- [ ] **Step 2: Add API types and methods**

```ts
export interface ConsultationRecording {
  id: string;
  status: 'uploading' | 'ready' | 'processing' | 'completed' | 'failed' | 'ambiguous' | 'deleting' | 'deleted';
  mime_type: string;
  codec: string;
  byte_size: number;
  duration_ms: number;
  started_at: string | null;
  ended_at: string | null;
  expires_at: string | null;
  deleted_at: string | null;
  source_available: boolean;
  version: number;
}

export const createRecordingUpload = (customerId: number, mimeType: string, startedAt: string) =>
  request<RecordingUploadSession>('POST', `/customers/${customerId}/recordings/upload-sessions/`,
    { mime_type: mimeType, started_at: startedAt }, true);
export const getRecordingPartUrl = (customerId: number, recordingId: string, partNumber: number) =>
  request<RecordingPartURL>('POST', `/customers/${customerId}/recordings/${recordingId}/parts/${partNumber}/`, {}, true);
export const completeRecordingUpload = (customerId: number, recordingId: string, parts: CompletedPart[], endedAt: string) =>
  request<ConsultationRecording>('POST', `/customers/${customerId}/recordings/${recordingId}/complete-upload/`,
    { parts, ended_at: endedAt }, true);
export const listConsultationRecordings = (customerId: number, page = 1) =>
  request<PaginatedResult<ConsultationRecording>>(
    'GET', `/customers/${customerId}/recordings/?page=${page}`, undefined, true);
```

- [ ] **Step 3: Implement MIME and part utilities**

```ts
const CANDIDATES = [
  'audio/webm;codecs=opus',
  'audio/mp4;codecs=mp4a.40.2',
  'audio/mp4',
  'audio/webm',
];

export function selectRecordingMimeType(isSupported = MediaRecorder.isTypeSupported) {
  return CANDIDATES.find((value) => isSupported(value)) ?? null;
}

export async function uploadBufferedParts(chunks: Blob[], partBytes: number, upload: UploadPart) {
  let pending = new Blob();
  let partNumber = 1;
  const completed: CompletedPart[] = [];
  for (const chunk of chunks) {
    pending = new Blob([pending, chunk]);
    while (pending.size >= partBytes) {
      const current = pending.slice(0, partBytes);
      pending = pending.slice(partBytes);
      completed.push(await upload(partNumber++, current));
    }
  }
  if (pending.size > 0) completed.push(await upload(partNumber, pending));
  return completed;
}
```

실제 hook은 전체 chunks를 종료 때까지 모으지 않고 다음 누적 버퍼를 `dataavailable`마다 호출한다.

```ts
export class MultipartBuffer {
  private pending = new Blob();
  private nextPart = 1;
  private completed: CompletedPart[] = [];
  private queue: Promise<void> = Promise.resolve();

  constructor(private readonly partBytes: number, private readonly upload: UploadPart) {}

  push(chunk: Blob) {
    this.pending = new Blob([this.pending, chunk]);
    while (this.pending.size >= this.partBytes) {
      const part = this.pending.slice(0, this.partBytes);
      this.pending = this.pending.slice(this.partBytes);
      const partNumber = this.nextPart++;
      this.queue = this.queue.then(async () => {
        this.completed.push(await this.upload(partNumber, part));
      });
    }
  }

  async finish() {
    if (this.pending.size > 0) {
      const part = this.pending;
      this.pending = new Blob();
      const partNumber = this.nextPart++;
      this.queue = this.queue.then(async () => {
        this.completed.push(await this.upload(partNumber, part));
      });
    }
    await this.queue;
    return [...this.completed];
  }
}
```

- [ ] **Step 4: Implement the recorder hook**

`start()`가 사용자 클릭 안에서 `navigator.mediaDevices.getUserMedia({ audio: true })`를 호출하고, session 생성 뒤 `MediaRecorder.start(5_000)`을 시작한다. `dataavailable`은 blob을 `MultipartBuffer.push`에 즉시 전달하고, stop event가 `finish()`와 complete API를 기다린 뒤 `ready`로 전환한다. page visibility·track ended·beforeunload는 `interrupted` 또는 닫기 경고만 만들며 백그라운드 지속을 약속하지 않는다.

```ts
export function useConsultationRecorder(customerId: number) {
  const [state, setState] = useState<RecorderState>({ kind: 'idle' });
  const recorderRef = useRef<MediaRecorder | null>(null);
  const startedAtRef = useRef<string | null>(null);

  const stop = useCallback(() => {
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== 'inactive') {
      setState({ kind: 'stopping' });
      recorder.stop();
    }
  }, []);

  useEffect(() => {
    if (state.kind !== 'recording') return;
    const timer = window.setInterval(() => {
      setState((current) => current.kind === 'recording'
        ? { ...current, elapsedSeconds: current.elapsedSeconds + 1 }
        : current);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [state.kind]);

  return { state, start, pause, resume, stop, discard };
}
```

`RecorderProvider`는 RootLayout의 `{children}`을 감싸 active recording을 route 변경에도 유지한다. 같은 고객 상세의 탭 이동은 끊김 없이 유지하고, 다른 route의 링크 클릭 시 확인창을 보여준다. 확인 없이 route가 바뀐 경우에도 전역 mini bar가 남아 녹음을 잃지 않는다.

```ts
export interface RecorderSessionContextValue {
  customerId: number | null;
  state: RecorderState;
  isActive: boolean;
  start: (customerId: number) => Promise<void>;
  pause: () => void;
  resume: () => void;
  stop: () => void;
  discard: () => Promise<void>;
}
```

`useGlobalRecorderSession()`이 이 계약과 단 하나의 `MediaRecorder`, `MultipartBuffer`, upload session을 소유한다. 고객별 `useConsultationRecorder(customerId)`는 context의 start에 customerId를 바인딩한 얇은 wrapper로만 만들고 별도 recorder를 생성하지 않는다. `RecordingMiniBar`의 props는 `{ session: RecorderSessionContextValue }`로 고정한다.

```tsx
export function RecorderProvider({ children }: { children: React.ReactNode }) {
  const session = useGlobalRecorderSession();
  useEffect(() => {
    if (!session.isActive) return;
    const beforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', beforeUnload);
    return () => window.removeEventListener('beforeunload', beforeUnload);
  }, [session.isActive]);
  return <RecorderContext.Provider value={session}>
    {children}
    {session.isActive && <RecordingMiniBar session={session} />}
  </RecorderContext.Provider>;
}
```

RootLayout body 안의 `{children}`을 다음처럼 감싼다. RootLayout은 Server Component로 유지되고 provider만 Client Component boundary가 된다.

```tsx
<RecorderProvider>{children}</RecorderProvider>
```

- [ ] **Step 5: Run hook and upload tests**

Run: `cd inpa_fe && npm run test:run -- components/consultation-recorder/use-consultation-recorder.test.ts components/consultation-recorder/upload-parts.test.ts`

Expected: MIME·permission·pause/resume·auto-stop·interrupt·retry·part size tests PASS.

- [ ] **Step 6: Commit only after PM asks**

```bash
git add inpa_fe/components/consultation-recorder inpa_fe/lib/api.ts
git commit -m "feat(녹음): 브라우저 녹음과 이어올리기 추가"
```

### Task 7: 기존 메모 화면에 녹음 UX 통합

**Files:**
- Create: `inpa_fe/components/consultation-recorder/consultation-recorder.tsx`
- Create: `inpa_fe/components/consultation-recorder/recording-card.tsx`
- Modify: `inpa_fe/components/customer-memos.tsx`
- Test: `inpa_fe/components/__tests__/consultation-recorder.test.tsx`

**Interfaces:**
- Consumes `<CustomerMemos>` and recorder hook.
- Produces record consent, active mini-bar, upload, playback, early-delete UI, reload-safe recording list.

- [ ] **Step 1: Write failing end-user flow tests**

```tsx
it('shows seven-day copy, one-shot notice, recording controls, and deleted source state', async () => {
  api.getRecordingCapability.mockResolvedValue({ recording_enabled: true, consent_current: true,
    max_duration_seconds: 3600, max_bytes: 104857600 });
  render(<ConsultationRecorder customerId={31} />);
  await userEvent.click(await screen.findByRole('button', { name: '상담 녹음' }));
  expect(screen.getByText(/인파에서 최대 7일 보관/)).toBeTruthy();
  expect(screen.getByText(/녹음 하나당 요약은 한 번/)).toBeTruthy();
  expect(screen.getByRole('button', { name: '녹음 시작' })).toBeTruthy();
});

it('offers consent link and QR when customer consent is missing', async () => {
  api.getRecordingCapability.mockResolvedValue({ recording_enabled: true, consent_current: false,
    max_duration_seconds: 3600, max_bytes: 104857600 });
  render(<ConsultationRecorder customerId={31} />);
  await userEvent.click(await screen.findByRole('button', { name: '상담 녹음' }));
  expect(screen.getByRole('button', { name: '동의 링크 복사' })).toBeTruthy();
  expect(screen.getByRole('button', { name: '동의 완료 다시 확인' })).toBeTruthy();
});
```

- [ ] **Step 2: Implement the modal and mini recorder**

```tsx
export function ConsultationRecorder({ customerId }: { customerId: number }) {
  const recorder = useRecorderContext();
  const [open, setOpen] = useState(false);
  const [capability, setCapability] = useState<RecordingCapability | null>(null);

  async function openRecorder() {
    const next = await getRecordingCapability(customerId);
    setCapability(next);
    setOpen(true);
  }

  return <>
    <button onClick={openRecorder} className="rounded-xl bg-brand px-4 py-2 text-[13px] font-bold text-white">
      상담 녹음
    </button>
    {open && <RecordingDialog customerId={customerId} capability={capability} recorder={recorder}
      onClose={() => setOpen(false)} />}
  </>;
}
```

전역 provider가 mini bar를 한 번만 렌더하므로 modal 컴포넌트 안에서는 중복 렌더하지 않는다.

Dialog는 7일 안내, 동의 링크/QR, 마이크 권한 안내, 경과시간, 45·55·59분 안내, pause/resume/stop, 실제 upload progress, 종료 확인을 상태별로 렌더한다. 버튼은 모두 44px 이상이고 `aria-live="polite"` 상태 문구를 사용한다.

`CustomerMemos` mount 시 `listConsultationRecordings(customerId)`를 호출하고 loading skeleton, 재시도 오류, 빈 상태, 페이지 더 보기를 제공한다. 업로드 완료 콜백은 새 recording을 목록 첫 항목에 합치고, 재접속·새로고침 때는 서버 목록으로 동일 상태를 복구한다.

- [ ] **Step 3: Implement ready and deleted recording cards**

```tsx
export function RecordingCard({ customerId, recording, onDeleted }: Props) {
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  if (!recording.source_available) {
    return <Card className="p-4"><p>원본 녹음은 보관을 마치고 삭제됐어요.</p>
      <p className="mt-1 text-[12px] text-ink3">요약 메모는 그대로 남아요.</p></Card>;
  }
  return <Card className="p-4">
    <p className="text-[13px] font-semibold text-ink">원본 녹음</p>
    <p className="mt-1 text-[12px] text-ink3">{formatExpiry(recording.expires_at)} 자동 삭제</p>
    {audioUrl ? <audio controls src={audioUrl} className="mt-3 w-full" />
      : <button onClick={async () => setAudioUrl((await getRecordingPlayUrl(customerId, recording.id)).url)}>
          녹음 듣기
        </button>}
    <button onClick={() => confirmAndDeleteSource(customerId, recording.id, onDeleted)}>
      원본 녹음 지금 삭제
    </button>
  </Card>;
}
```

- [ ] **Step 4: Integrate with memo header and run tests**

`CustomerMemos` 제목 오른쪽에 `<ConsultationRecorder>`를 주 버튼, `메모 작성`을 보조 버튼으로 배치한다. 녹음 기능이 gate-off면 recorder는 숨기고 메모 작성만 유지한다.

Run: `cd inpa_fe && npm run test:run -- components/__tests__/consultation-recorder.test.tsx components/__tests__/customer-memos.test.tsx && npm run lint:copy && npm run build`

Expected: flow·copy·a11y tests PASS, build PASS.

- [ ] **Step 5: Commit only after PM asks**

```bash
git add inpa_fe/components/consultation-recorder inpa_fe/components/customer-memos.tsx inpa_fe/components/__tests__/consultation-recorder.test.tsx
git commit -m "feat(고객): 상담 녹음 UX 통합"
```

### Task 8: 관리자 운영 화면과 파일럿 검증

**Files:**
- Modify: `inpa_be/inpa/admin_console/serializers.py`
- Modify: `inpa_be/inpa/admin_console/views.py`
- Modify: `inpa_be/inpa/admin_console/urls.py`
- Modify: `inpa_fe/lib/adminApi.ts`
- Create: `inpa_fe/app/admin/consultations/page.tsx`
- Modify: `inpa_fe/app/admin/layout.tsx`
- Create: `docs/dev/28-consultation-recording-operations.md`
- Test: `inpa_be/inpa/admin_console/tests.py`
- Test: `inpa_fe/app/admin/consultations/page.test.tsx`

**Interfaces:**
- Produces admin settings/status without content access.
- Produces exact R2 and mobile pilot runbook.

- [ ] **Step 1: Write failing admin redaction and dual-gate tests**

```python
def test_admin_consultation_response_has_counts_but_no_content_or_identity(self):
    response = self.client.get('/api/v1/admin/consultations/')
    self.assertEqual(response.status_code, 200)
    encoded = json.dumps(response.data, ensure_ascii=False)
    self.assertNotIn('storage_key', encoded)
    self.assertNotIn('customer_name', encoded)
    self.assertNotIn('memo', encoded)
    self.assertIn('overdue_source_count', response.data['status'])

def test_admin_cannot_enable_when_environment_gate_is_closed(self):
    with override_settings(CONSULTATION_RECORDING_ENABLED=False):
        response = self.client.patch('/api/v1/admin/consultations/', {'recording_enabled': True})
    self.assertEqual(response.status_code, 409)
    self.assertEqual(response.data['code'], 'CONSULTATION_ENV_GATE_CLOSED')
```

- [ ] **Step 2: Add admin response contract**

```python
class AdminConsultationSettingsView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        config = ConsultationRuntimeConfig.solo()
        return Response({
            'environment_gate_open': settings.CONSULTATION_RECORDING_ENABLED,
            'settings': AdminConsultationConfigSerializer(config).data,
            'status': consultation_status_snapshot(),
            'pilot_users': AdminConsultationPilotSerializer(
                ConsultationPilotAccess.objects.select_related('user'), many=True).data,
        })

    def patch(self, request):
        if request.data.get('recording_enabled') is True and not settings.CONSULTATION_RECORDING_ENABLED:
            return Response({'code': 'CONSULTATION_ENV_GATE_CLOSED',
                             'detail': '환경 설정 검토를 마친 뒤 운영 스위치를 켤 수 있어요.'}, status=409)
        serializer = AdminConsultationConfigSerializer(
            ConsultationRuntimeConfig.solo(), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
```

- [ ] **Step 3: Add admin page states**

관리자 페이지는 환경 게이트, 운영 스위치, 파일럿 계정, active upload, ready source, deleted, overdue, delete failure, orphan count를 카드로 표시한다. 모든 로딩·오류·빈 상태에 재시도 또는 다음 설정 행동을 둔다. 원음 재생·URL·고객명·메모 본문 요소는 만들지 않는다.

- [ ] **Step 4: Write the exact operations runbook**

Runbook에는 다음 copyable 값과 성공 신호를 적는다.

```text
Bucket: inpa-consultation-recordings
Prefix: consultation-recordings/
AllowedOrigins: https://www.inpa.kr
AllowedMethods: PUT, GET, HEAD
AllowedHeaders: content-type
ExposeHeaders: ETag
Multipart abort: 1 day
Object lifecycle: consultation-recordings/ after 6 days, secondary maximum-7-day guard
```

환경변수 이름은 Task 3의 `CONSULTATION_STORAGE_*`, 기능 게이트는 `CONSULTATION_RECORDING_ENABLED=false`로 기록한다.

- [ ] **Step 5: Run full Release 2 verification**

Run: `cd inpa_be && python manage.py check && python manage.py test inpa`

Run: `cd inpa_fe && npm run test:run && npm run lint:copy && npm run build`

Expected: all PASS.

실기기에서는 60분, 전화 수신, 잠금, 앱 전환, Bluetooth 변경, Wi-Fi/LTE 전환, 이어올리기, 재생, 조기 삭제를 각 기기에서 기록한다. R2 삭제 뒤 HEAD 404와 만료된 GET URL 실패를 확인한다.

- [ ] **Step 6: Stop before production and gate opening**

Preview 결과와 실기기·삭제 증거를 PM에게 보고한다. 프로덕션 배포, `CONSULTATION_RECORDING_ENABLED=true`, 관리자 운영 스위치 활성은 각각 별도 승인 전 실행하지 않는다.
