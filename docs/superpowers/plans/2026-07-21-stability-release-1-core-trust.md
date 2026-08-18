# Release 1 핵심 판정·동의·공유 신뢰성 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 잘못된 보장 판정을 기본 차단하고, 외부 AI 호출 전에 고객 동의 증적을 확정하며, 공개 공유와 여러 증권 비교가 발급 당시의 사실만 표현하도록 만든다.

**Architecture:** 보장 기준선 정규화·선택을 순수 모듈로 분리하고 `HEATMAP_GRADING_ENABLED=False`에서 모든 판정을 neutral로 유지한다. 셀프진단은 동의 receipt 트랜잭션과 외부 처리 트랜잭션을 분리한다. 공개 공유는 `ShareSnapshot`만 권위로 사용하고 과거 Customer token fallback은 독립 게이트로 닫는다. 화면은 서버 권위를 재계산하지 않고 사실·시점·다음 행동만 표현한다.

**Tech Stack:** Django 5.2/DRF/Decimal, Next.js 16/React 19/TypeScript, Vitest/Testing Library, Django TestCase.

## 2026-08-18 검증 결과 (아래 원문은 그대로 유지)

**이 릴리스 범위의 지적은 전부 해소된 상태다. 재검증 불필요.** 2026-08-18 세션에서 코드 대조로 확인했다.

- 보장 기준선 단위·상품군·연령·성별 판정: 2026-07-29 `analysis/baselines.py` 신설로 판정 권위가 한곳으로 모였고 골든 테스트로 고정됐다.
- 비교·공유·영업 문구 사실성: `comparison_source`/`guide_source` 표기, 중립 색상, "공유 당시" + `captured_at` KST 표기가 적용됐다.
- 소개 카드 연락처 필수: FE·BE가 동일 정규식으로 검증한다.
- 셀프진단 동의 선커밋: 외부 AI 호출 전 별도 트랜잭션으로 동의 증적을 먼저 커밋한다.
- 미발급 공유 토큰 404: `LEGACY_SHARE_FALLBACK_ENABLED`로 분리했고 기본값은 `False`다.

아래 원문은 당시 구현 계획 기록으로 보존한다. 전체 잔존 목록은 `docs/superpowers/specs/2026-07-21-comprehensive-stability-upgrade.md` §0 참고.

## Global Constraints

- 승인 설계는 `docs/superpowers/specs/2026-07-21-comprehensive-stability-upgrade.md`의 Release 1이다.
- `HEATMAP_GRADING_ENABLED`와 `LEGACY_SHARE_FALLBACK_ENABLED` 기본값은 모두 `False`다.
- 보장 판정 게이트는 코드·테스트 통과만으로 켜지 않는다. 비식별 gold set과 보험 도메인 검토가 별도 완료되어야 한다.
- 보험 검토형 파이프라인의 `INSURANCE_REVIEW_GATE_ENABLED`와 공유 호환 정책을 결합하지 않는다.
- 금액 비교에 `float`를 사용하지 않는다. 내부 판정 단위는 원이며 `Decimal` 또는 정수만 사용한다.
- 고객 공개 화면에는 내부 위험 용어, 설계사 책임 문구, 운영 게이트 이름을 표시하지 않는다.
- 다른 세션이 수정 중인 랜딩·게시판·요금제 파일은 제외한다.
- 모든 작업은 RED 테스트 확인 후 최소 구현, 대상 테스트, 관련 앱 테스트 순으로 진행한다.
- 아래 `git commit`은 자동 단계가 아니다. PM이 커밋을 요청한 경우에만 Conventional Commit으로 해당 작업 파일만 stage한다.

---

### Task 1: 기준선 정규화와 선택 계약을 순수 모듈로 고정

**Files:**

- Create: `inpa_be/inpa/analysis/baselines.py`
- Create: `inpa_be/inpa/analysis/test_baselines.py`
- Modify: `inpa_be/inpa/analysis/views.py`
- Modify: `inpa_be/inpa/customers/models.py`
- Modify: `inpa_be/config/settings/base.py`
- Modify: `inpa_be/.env.example`

- [ ] **Step 1: 골든 계산 테스트를 먼저 작성한다.**

```python
from decimal import Decimal
from django.test import SimpleTestCase

from inpa.analysis.baselines import normalize_money, select_baseline
from inpa.customers.models import PlannerBaseline


class BaselineMoneyTests(SimpleTestCase):
    def test_ten_thousand_won_is_converted_to_won(self):
        self.assertEqual(
            normalize_money(Decimal('5000'), PlannerBaseline.UNIT_TEN_THOUSAND_WON),
            Decimal('50000000'),
        )

    def test_won_is_not_scaled(self):
        self.assertEqual(
            normalize_money(Decimal('50000000'), PlannerBaseline.UNIT_WON),
            Decimal('50000000'),
        )

    def test_account_unit_is_not_money(self):
        self.assertIsNone(
            normalize_money(Decimal('3'), PlannerBaseline.UNIT_ACCOUNT)
        )
```

테스트 fixture로 같은 `coverage_key`에 다음 후보를 만든다.

- 생명·30s·남
- 생명·30s·공통
- 손해·30s·남
- 생명·60s+·여
- 실손·30s·남

다음 테스트명을 포함한다.

```python
def test_exact_age_and_gender_win(self): ...
def test_common_gender_is_the_only_gender_fallback(self): ...
def test_wrong_age_never_falls_back(self): ...
def test_life_never_uses_nonlife(self): ...
def test_ambiguous_indemnity_and_annuity_are_neutral(self): ...
def test_multiple_equally_specific_rows_are_neutral(self): ...
```

- [ ] **Step 2: 테스트가 현재 코드에서 실패함을 확인한다.**

Run: `cd inpa_be && python manage.py test inpa.analysis.test_baselines -v 2`

Expected: `inpa.analysis.baselines`와 단위 상수가 없어 실패한다.

- [ ] **Step 3: 모델 단위 상수와 순수 정규화 함수를 구현한다.**

`PlannerBaseline`에 기존 숫자 값을 유지하는 상수를 추가한다. 마이그레이션은 만들지 않는다.

```python
UNIT_TEN_THOUSAND_WON = 1
UNIT_WON = 2
UNIT_ACCOUNT = 3
UNIT_CHOICES = (
    (UNIT_TEN_THOUSAND_WON, '만원'),
    (UNIT_WON, '원'),
    (UNIT_ACCOUNT, '구좌'),
)
```

`baselines.py`의 공개 인터페이스는 아래로 제한한다.

```python
from decimal import Decimal


def normalize_money(value, unit):
    if value is None or unit == PlannerBaseline.UNIT_ACCOUNT:
        return None
    amount = Decimal(value)
    if unit == PlannerBaseline.UNIT_TEN_THOUSAND_WON:
        return amount * Decimal('10000')
    if unit == PlannerBaseline.UNIT_WON:
        return amount
    return None


def select_baseline(candidates, *, insurance_type, age_band, gender):
    product_group = {1: PlannerBaseline.PRODUCT_GROUP_LIFE,
                     2: PlannerBaseline.PRODUCT_GROUP_NONLIFE}.get(insurance_type)
    if product_group is None or age_band is None:
        return None
    scoped = [row for row in candidates
              if row.product_group == product_group and row.age_band == age_band]
    exact = [row for row in scoped if row.gender == gender]
    common = [row for row in scoped if row.gender is None]
    chosen = exact or common
    return chosen[0] if len(chosen) == 1 else None
```

- [ ] **Step 4: 실제 날짜만 연령대로 변환하도록 고친다.**

`_age_band()`는 `YYYY-MM-DD`와 `YYYY.MM.DD`의 완전한 실제 날짜만 허용한다. 월만·연도만 있는 값, `2026-02-31`, 빈 값은 `None`이다. 현재 연도 단순 차감 대신 KST `timezone.localdate()` 기준 만 나이를 계산하고 기존 보험나이 계산과 혼동하지 않는다.

- [ ] **Step 5: 안전 게이트 설정 테스트와 설정을 추가한다.**

```python
@override_settings(HEATMAP_GRADING_ENABLED=False)
def test_grading_gate_is_closed(self): ...
```

```python
# config/settings/base.py
HEATMAP_GRADING_ENABLED = env.bool(
    'HEATMAP_GRADING_ENABLED', default=False)
```

`.env.example`에는 `HEATMAP_GRADING_ENABLED=False`를 넣고 도메인 검토 전 개방 금지 주석을 남긴다.

- [ ] **Step 6: 골든 테스트를 통과시킨다.**

Run: `cd inpa_be && python manage.py test inpa.analysis.test_baselines -v 2`

Expected: 위 단위·연령·성별·상품군 골든 케이스 전부 PASS.

---

### Task 2: 히트맵 API와 화면을 fail-closed 계약에 연결

**Files:**

- Modify: `inpa_be/inpa/analysis/views.py`
- Modify: `inpa_be/inpa/analysis/tests.py`
- Modify: `inpa_fe/lib/api.ts`
- Modify: `inpa_fe/components/heatmap.tsx`
- Modify: `inpa_fe/components/__tests__/insurance-review-authority.test.tsx`

- [ ] **Step 1: API 회귀 테스트를 RED로 만든다.**

`HeatmapGradedTests`에 다음을 추가한다.

```python
@override_settings(HEATMAP_GRADING_ENABLED=False)
def test_gate_closed_keeps_every_cell_neutral_even_with_baselines(self): ...

@override_settings(HEATMAP_GRADING_ENABLED=True)
def test_fifty_million_won_equals_five_thousand_ten_thousand_won(self): ...

@override_settings(HEATMAP_GRADING_ENABLED=True)
def test_twenty_million_is_shortage_against_thirty_million(self): ...

@override_settings(HEATMAP_GRADING_ENABLED=True)
def test_account_unit_and_wrong_scope_stay_neutral(self): ...
```

응답 계약은 다음을 확인한다.

```python
self.assertEqual(body['mode'], 'neutral')
self.assertTrue(body['baseline_present'])
self.assertFalse(body['grading_enabled'])
```

- [ ] **Step 2: 현재 테스트 실패를 확인한다.**

Run: `cd inpa_be && python manage.py test inpa.analysis.tests.HeatmapNeutralGateTests inpa.analysis.tests.HeatmapGradedTests -v 2`

Expected: 게이트·원 단위 정규화·상품군 필터가 없어 새 테스트 실패.

- [ ] **Step 3: 카테고리의 `insurance_type`을 판정 함수에 전달한다.**

기존 coverage name 인덱스는 유지하되 `_pick_baseline` 점수 선택을 삭제하고 Task 1의 `select_baseline()`을 사용한다. `held_amount`, `min`, `max` 모두 `Decimal`로 비교한다. API JSON에는 정규화된 원 단위 숫자와 원래 입력 단위를 함께 보낸다.

```python
mode = (
    'graded'
    if settings.HEATMAP_GRADING_ENABLED and baselines
    else 'neutral'
)

status, baseline = _grade(
    det.name,
    held,
    insurance_type=cat.insurance_type,
)
```

`baseline` 응답은 다음 모양을 사용한다.

```json
{
  "min": 30000000,
  "max": 50000000,
  "display_unit": 1,
  "baseline_source": "planner"
}
```

- [ ] **Step 4: FE 타입과 안내 상태를 분리한다.**

`HeatmapResponse`에 `grading_enabled: boolean`을 추가한다. `baseline_present && !grading_enabled`이면 버튼 문구는 `설정한 기준 확인하기`, 기준이 없으면 `기준 설정하기`다. 두 상태 모두 판정 색과 라벨을 그리지 않는다.

- [ ] **Step 5: BE·FE 대상 테스트를 통과시킨다.**

Run:

```bash
cd inpa_be && python manage.py test inpa.analysis.tests inpa.analysis.test_baselines -v 2
cd ../inpa_fe && npm test -- --run components/__tests__/insurance-review-authority.test.tsx
```

Expected: API와 화면이 gate closed에서 neutral, gate open의 정확한 scope에서만 graded.

---

### Task 3: 셀프진단 동의 receipt를 외부 AI 호출 전에 확정

**Files:**

- Modify: `inpa_be/inpa/insurances/self_diagnosis.py`
- Modify: `inpa_be/inpa/insurances/tests.py`

- [ ] **Step 1: 호출 순서와 실패 보존 테스트를 추가한다.**

`SelfDiagnosisConsentTests`에 아래 테스트를 작성한다.

```python
def test_consent_receipts_exist_before_claude_parse(self):
    def assert_receipts_then_parse(*args, **kwargs):
        customer = Customer.objects.get(
            owner=self.planner,
            mobile_phone_number='01012345678',
        )
        self.assertTrue(ConsentLog.objects.filter(
            customer=customer,
            scope=ConsentLog.SCOPE_PERSONAL_INFO,
            subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
        ).exists())
        self.assertTrue(ConsentLog.objects.filter(
            customer=customer,
            scope=ConsentLog.SCOPE_OVERSEAS_MEDICAL,
            subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
        ).exists())
        raise RuntimeError('provider down')
```

추가 필수 테스트:

```python
def test_provider_failure_keeps_consent_and_customer_but_no_insurance(self): ...
def test_retry_reuses_customer_and_does_not_duplicate_same_receipt(self): ...
def test_invalid_date_phone_or_file_never_creates_receipt(self): ...
def test_partial_file_failure_keeps_successful_file_only(self): ...
```

- [ ] **Step 2: 테스트가 현재 순서에서 실패함을 확인한다.**

Run: `cd inpa_be && python manage.py test inpa.insurances.tests.SelfDiagnosisConsentTests -v 2`

Expected: mock Claude가 실행되는 시점에는 Customer/ConsentLog가 없어 실패.

- [ ] **Step 3: 검증, receipt, 외부 처리, 결과 저장의 네 단계를 함수로 분리한다.**

같은 파일 안에 다음 private helper를 둔다. 새 서비스 파일은 만들지 않는다.

```python
def _upsert_customer_and_receipts(*, planner, name, phone, birth, gender,
                                  ip, has_files, marketing, third_party):
    with transaction.atomic():
        customer, _created = Customer.objects.select_for_update().get_or_create(
            owner=planner,
            lead_source=Customer.LEAD_SELF_DIAGNOSIS,
            mobile_phone_number=phone[:15],
            defaults={...},
        )
        ConsentLog.objects.get_or_create(
            customer=customer,
            scope=ConsentLog.SCOPE_PERSONAL_INFO,
            subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
            doc_version=CONSENT_TEXTS_VERSION,
            defaults={'purpose': ..., 'ip': ip},
        )
        if has_files:
            ConsentLog.objects.get_or_create(...SCOPE_OVERSEAS_MEDICAL...)
            if customer.consent_overseas_at is None:
                customer.consent_overseas_at = timezone.now()
                customer.save(update_fields=['consent_overseas_at'])
        return customer
```

실제 날짜는 `datetime.date.fromisoformat()`으로 확인한다. provider 설정, 파일 확장자·크기, 개수·일일 한도 등 외부 호출 전 확인 가능한 모든 항목을 receipt 생성 전에 끝낸다.

- [ ] **Step 4: AI 호출은 첫 트랜잭션 커밋 뒤에만 실행한다.**

legacy 동기 파싱은 receipt helper 반환 뒤 실행한다. 검토형 gate ON은 기존 `receive_import()`를 같은 customer로 호출한다. 성공한 legacy 보험 저장은 두 번째 `transaction.atomic()`에서 처리한다. provider 실패 로그는 exception type과 outcome enum만 남긴다.

- [ ] **Step 5: 중복·부분 실패 계약을 보존한다.**

기존 `_ci_signature()` 중복 방지를 유지한다. 선택 동의는 해당 체크가 있을 때만 receipt를 만들고, 같은 문서 버전의 재시도는 동일 receipt를 재사용한다. 응답의 성공·실패 파일 수와 이벤트 계측은 실제 저장 결과를 사용한다.

- [ ] **Step 6: 관련 앱 테스트를 통과시킨다.**

Run: `cd inpa_be && python manage.py test inpa.insurances.tests.SelfDiagnosisConsentTests inpa.insurances.tests.SelfDiagnosisMultiPdfTests inpa.insurances.tests.SelfDiagnosisGateTests -v 2`

Expected: 실패 provider에서도 동의 receipt 보존, 보험 0건, PII 로그 0건.

---

### Task 4: 소개카드 상담 신청에 연락 가능한 휴대폰 계약 적용

**Files:**

- Modify: `inpa_be/inpa/accounts/public.py`
- Modify: `inpa_be/inpa/accounts/tests.py`
- Modify: `inpa_fe/lib/api.ts`
- Modify: `inpa_fe/app/p/[refcode]/page.tsx`
- Create: `inpa_fe/components/__tests__/introduction-card.test.tsx`

- [ ] **Step 1: BE 실패 테스트를 작성한다.**

```python
def test_intro_lead_requires_valid_mobile_phone(self): ...
def test_intro_lead_normalizes_hyphens_before_deduplication(self): ...
def test_invalid_phone_creates_no_customer_consent_event_or_notification(self): ...
```

`01012345678`과 `010-1234-5678` 재제출이 고객 1명으로 유지됨을 확인한다.

- [ ] **Step 2: BE RED를 확인한다.**

Run: `cd inpa_be && python manage.py test inpa.accounts.tests.IntroCardTests -v 2`

Expected: 현재 phone 선택 계약 때문에 빈 번호 요청이 201이어서 실패.

- [ ] **Step 3: BE에서 숫자 정규화와 필수 검증을 넣는다.**

```python
phone_digits = re.sub(r'[^0-9]', '', request.data.get('phone') or '')
if not re.fullmatch(r'01[0-9]{8,9}', phone_digits):
    return Response(
        {'code': 'INVALID_PHONE', 'detail': '올바른 휴대폰 번호를 입력해 주세요.'},
        status=status.HTTP_400_BAD_REQUEST,
    )
```

Customer에는 정규화한 숫자만 저장하고, 고객·동의·이벤트·알림은 검증 성공 뒤에만 만든다.

- [ ] **Step 4: FE 계약과 화면 테스트를 RED로 만든다.**

`submitIntroLead` payload의 `phone?: string`을 `phone: string`으로 바꾼다. 테스트는 휴대폰 input, `inputMode="tel"`, 잘못된 번호에서 버튼 비활성 또는 inline 안내, 성공 API payload를 확인한다.

- [ ] **Step 5: FE 입력·오류·성공 상태를 구현한다.**

고객 화면 카피는 `연락받을 휴대폰 번호`와 `상담 내용을 확인한 뒤 연락드려요`처럼 다음 행동을 설명한다. API 400은 기존 성공 화면으로 넘어가지 않고 필드 가까이에 표시한다.

- [ ] **Step 6: BE·FE 테스트를 통과시킨다.**

Run:

```bash
cd inpa_be && python manage.py test inpa.accounts.tests.IntroCardTests -v 2
cd ../inpa_fe && npm test -- --run components/__tests__/introduction-card.test.tsx
```

---

### Task 5: 공개 공유를 snapshot-only로 전환하고 시점을 노출

**Files:**

- Modify: `inpa_be/config/settings/base.py`
- Modify: `inpa_be/.env.example`
- Modify: `inpa_be/inpa/analytics/views.py`
- Modify: `inpa_be/inpa/analytics/tests.py`
- Modify: `inpa_be/inpa/customers/serializers.py`
- Modify: `inpa_fe/lib/api.ts`
- Modify: `inpa_fe/components/share-snapshot-content.tsx`
- Modify: `inpa_fe/app/s/[token]/page.tsx`
- Modify: `inpa_fe/components/__tests__/share-public.test.tsx`

- [ ] **Step 1: 신규 안전 기본값과 읽기 전용 테스트를 작성한다.**

```python
@override_settings(LEGACY_SHARE_FALLBACK_ENABLED=False)
def test_unbacked_customer_token_is_404(self): ...

@override_settings(
    LEGACY_SHARE_FALLBACK_ENABLED=True,
    INSURANCE_REVIEW_GATE_ENABLED=True,
)
def test_legacy_fallback_is_independent_from_review_gate(self): ...

def test_customer_patch_cannot_change_share_lifecycle_fields(self): ...
```

PATCH 테스트는 `share_token`, `share_sent_at`, `share_expires_at`을 보낸 뒤 DB 값이 모두 그대로인지 확인한다.

- [ ] **Step 2: 현재 테스트 실패를 확인한다.**

Run: `cd inpa_be && python manage.py test inpa.analytics.tests.ShareSnapshotRolloutCompatibilityTests inpa.analytics.tests.ShareSnapshotAuthorityTests -v 2`

Expected: 별도 fallback 설정이 없고 `share_expires_at`이 쓰기 가능해 실패.

- [ ] **Step 3: 독립 공유 호환 게이트를 추가한다.**

```python
LEGACY_SHARE_FALLBACK_ENABLED = env.bool(
    'LEGACY_SHARE_FALLBACK_ENABLED', default=False)
```

`_resolve_public_share()`는 snapshot 검색 후 다음 한 줄로 fallback 여부를 결정한다.

```python
if not settings.LEGACY_SHARE_FALLBACK_ENABLED:
    return None, None, 'SHARE_LINK_INVALID'
```

`CustomerSerializer.read_only_fields`에 `share_expires_at`을 추가한다. snapshot이 하나라도 있으면 revoked·expired·history 상태를 Customer로 되돌리지 않는 기존 terminal 권위는 유지한다.

- [ ] **Step 4: v2 공개 응답에 캡처 시점을 additive하게 넣는다.**

기존 `{snapshot, actions}` 모양은 유지하고 `snapshot.captured_at`을 추가한다. legacy v1 body를 다시 계산하거나 변형하지 않는다.

```python
body = {
    'snapshot': {**snapshot.payload, 'captured_at': snapshot.captured_at.isoformat()},
    'actions': _build_live_actions(customer),
}
```

payload 자체에 이미 같은 키가 있을 때 서버 필드가 최종 권위가 되도록 merge 순서를 고정한다.

- [ ] **Step 5: FE는 `공유 당시` 시점을 KST로 표시한다.**

`ShareSnapshotPayload`에 `captured_at: string`을 추가하고 `share-snapshot-content.tsx`의 `지금` 표현을 제거한다. KST 날짜 포맷 결과와 고객용 짧은 고지 1회만 보이는지 테스트한다. `/s`의 설계사용 `DisclaimerFooter`는 제거한다.

- [ ] **Step 6: 공유 대상 테스트를 통과시킨다.**

Run:

```bash
cd inpa_be && python manage.py test inpa.analytics.tests.ShareSnapshotAuthorityTests inpa.analytics.tests.ShareSnapshotRolloutCompatibilityTests inpa.analytics.tests.ShareSnapshotAuditCommandTests -v 2
cd ../inpa_fe && npm test -- --run components/__tests__/share-public.test.tsx
```

- [ ] **Step 7: Production 감사는 실행하지 않고 승인 대기 항목으로 남긴다.**

승인 전 실행 금지 명령:

```bash
python manage.py audit_share_snapshot_links
```

운영 실행 시 기대 출력은 PII·토큰 원문 없이 `unbacked_legacy_links`, `v1_legacy_snapshots`, `v1_inactive_snapshots`, `dry_run=true` 수량뿐이다. `--revoke-legacy`는 별도 명시 승인 없이는 실행하지 않는다.

---

### Task 6: 여러 증권 비교·공유·영업 문구의 사실성 정리

**Files:**

- Modify: `inpa_be/inpa/analysis/compare.py`
- Modify: `inpa_be/inpa/analysis/tests.py`
- Modify: `inpa_fe/app/customer/[id]/page.tsx`
- Modify: `inpa_fe/components/premium-split.tsx`
- Modify: `inpa_fe/components/share-snapshot-content.tsx`
- Modify: `inpa_fe/lib/copy-library.ts`
- Modify: `inpa_fe/scripts/check-copy.js`
- Modify: `inpa_fe/components/__tests__/neutral-policy-comparison.test.tsx`
- Modify: `inpa_fe/components/__tests__/share-public.test.tsx`
- Create: `inpa_fe/components/__tests__/copy-library.test.tsx`

- [ ] **Step 1: 결정론 결과가 AI로 표시되지 않는 테스트를 작성한다.**

다음을 고정한다.

- AI guide 응답이 실제로 존재할 때만 `AI가 정리한 참고 자료` 문구 표시
- 결정론 보험료·담보 표는 AI 문구 없음
- 좌우 차이는 브랜드 초록·경고 빨강 대신 같은 중립색
- 기본 비교 요청은 A/B 모두 1개 이상
- 잘못된 ID, 다른 고객 보험 ID, 빈 A/B는 빈 성공표가 아니라 400/404

- [ ] **Step 2: 카피 회귀 테스트를 먼저 실패시킨다.**

`copy-library.test.tsx`는 실제 노출되는 문구 목록에서 다음을 금지한다.

```ts
expect(renderedCopy).not.toMatch(/080-[0-9]/);
expect(renderedCopy).not.toMatch(/부담 없이|무조건|확실한|보장됩니다/);
```

`check-copy.js`가 `lib/copy-library.ts`를 스캔 대상에 포함하는지 별도 assertion을 둔다.

- [ ] **Step 3: BE 비교 입력 계약을 명시적으로 검증한다.**

`side_a_ids`와 `side_b_ids`를 정수 배열로 파싱하고, 각 side 최소 1개, 중복 ID 제거, customer owner scope를 강제한다. 실패는 `INVALID_COMPARISON_SELECTION` 또는 404로 반환한다. 기존 결과 키(`current`, `proposed` 등)는 호환을 위해 유지한다.

- [ ] **Step 4: FE 표현과 공유 고지를 정리한다.**

`증권 A`, `증권 B`, 보험료·담보·차이값만 표시한다. 차이를 이득·손해처럼 보이게 하는 색과 자동 판단 문구를 제거한다. 고객 `/s`에는 `인파가 등록된 보장 정보를 정리한 참고 자료입니다.`를 공식 위치에 1회만 둔다.

- [ ] **Step 5: 카피 라이브러리를 정직한 템플릿으로 교체한다.**

가짜 대표번호를 삭제하고 실제 번호가 없는 템플릿은 `담당 설계사 연락처` 자리표시자 또는 전화 CTA 자체를 생략한다. 검증 불가 주장과 상품 권유처럼 보이는 표현을 삭제한다. `copy-library.ts`를 lint 입력에 추가하되 코드 주석은 검사 대상에서 제외한다.

- [ ] **Step 6: 대상 테스트와 카피 검사를 통과시킨다.**

Run:

```bash
cd inpa_be && python manage.py test inpa.analysis.tests -v 2
cd ../inpa_fe && npm test -- --run components/__tests__/neutral-policy-comparison.test.tsx components/__tests__/share-public.test.tsx components/__tests__/copy-library.test.tsx
npm run lint:copy
```

Expected: 비교 테스트 PASS, 카피 검사 0건, 결정론 화면에 AI 표시 0건.

---

### Task 7: Release 1 통합 검증과 검토 지점

**Files:**

- No product file changes
- Review: Release 1에서 수정한 파일만

- [ ] **Step 1: Django 정적·마이그레이션 검증을 실행한다.**

```bash
cd inpa_be
python manage.py check
python manage.py makemigrations --check --dry-run
```

Expected: 0 issues, 모델 상수만 추가했다면 no changes detected.

- [ ] **Step 2: Release 1 관련 BE 테스트를 한 번에 실행한다.**

```bash
python manage.py test \
  inpa.analysis \
  inpa.accounts.tests.IntroCardTests \
  inpa.insurances.tests.SelfDiagnosisConsentTests \
  inpa.insurances.tests.SelfDiagnosisMultiPdfTests \
  inpa.analytics.tests.ShareSnapshotAuthorityTests \
  inpa.analytics.tests.ShareSnapshotRolloutCompatibilityTests \
  -v 2
```

- [ ] **Step 3: FE 전체 테스트·카피·build를 실행한다.**

```bash
cd ../inpa_fe
npm test -- --run
npm run lint:copy
npm run build
```

- [ ] **Step 4: 로컬 API를 실제 호출한다.**

개발 DB의 synthetic 계정만 사용한다. 다음을 확인한다.

- gate closed heatmap: `mode=neutral`, `grading_enabled=false`
- 잘못된 소개카드 전화번호: 400, 고객·동의 0건 증가
- snapshot 없는 Customer token: 404
- snapshot 발급 후 공개 GET: 200, `snapshot.captured_at` 존재

- [ ] **Step 5: 390px 브라우저에서 화면을 확인한다.**

보장 분석, 소개카드, 공유 링크를 확인한다. 콘솔 오류 0건, 가로 넘침 0건, 키보드 포커스 이동 가능, 실패 상태에서 성공 문구가 나타나지 않아야 한다.

- [ ] **Step 6: 독립 adversarial review를 수행한다.**

관점은 correctness, privacy/consent, tenant isolation, compliance copy, UX recovery다. Critical/Important를 먼저 수정하고, 기각한 의견은 근거와 함께 Release 보고에 남긴다.

- [ ] **Step 7: PM 검토 전에 diff를 자체 점검한다.**

```bash
git diff --check
git status --short
git diff -- inpa_be/inpa/analysis inpa_be/inpa/insurances/self_diagnosis.py \
  inpa_be/inpa/accounts/public.py inpa_be/inpa/analytics/views.py \
  inpa_be/inpa/customers/serializers.py inpa_fe/lib/api.ts \
  inpa_fe/components/heatmap.tsx inpa_fe/components/share-snapshot-content.tsx
```

Expected: 다른 세션 파일이 stage되지 않았고 Release 1 범위만 포함.

- [ ] **Step 8: 커밋·Preview·Production은 멈추고 PM 결정을 받는다.**

보고 형식은 인덱스의 네 줄을 사용한다. `HEATMAP_GRADING_ENABLED`와 `LEGACY_SHARE_FALLBACK_ENABLED`는 계속 False다.
