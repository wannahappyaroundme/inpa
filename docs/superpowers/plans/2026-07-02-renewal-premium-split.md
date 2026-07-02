# 갱신/비갱신 요금 분리 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 보장분석·비교분석에서 보험료를 갱신형/비갱신형/적립으로 나눠 표·절대수치로 보여주고, 담보별 요금(가입설계서 방식)까지 나열한다.

**Architecture:** 데이터(담보별 `premium`·`payment_period_type`·총 갱신/비갱신, 보험별 월/총 갱신·비갱신·적립)는 pdfplumber 저장 경로에서 **이미 계산·저장**되어 있다. 이 작업은 신규 계산 없이 "저장된 값을 응답·화면에 드러내기"다. BE는 시리얼라이저 2종 추가 + 히트맵/비교 응답 확장, FE는 타입 + 표 컴포넌트.

**Tech Stack:** Django 4.2 + DRF(BE, `inpa_be/`), Next.js 16 + React 19 + TS(FE, `inpa_fe/`). 설계서: `docs/superpowers/specs/2026-07-02-renewal-premium-split-design.md`.

## Global Constraints

- **컴플라이언스(레드라인):** 보험료는 사실 숫자만. 판정어(적정/과함/부족/좋다/나쁘다)·등급·색·권유 **금지**. 등급은 보장금액에만·설계사 기준(PlannerBaseline) 있을 때만. 보험료엔 등급 없음.
- **비교분석 verdict(KEEP/SWITCH)는 설계사 내부 전용** — 고객 공유뷰(`/s`) 무변경, BE가 고객에게 전송 안 함(기존 유지).
- **표·절대수치만.** 도넛/파이/가로막대/나이대 세그먼트 등 상대수치 시각화 금지.
- **em-dash(—) 금지**(렌더 문자열). `npm run lint:copy` 게이트 통과해야 함.
- **쉬운 말·긍정 톤·부인 문구 중립.** 데이터 안내는 "등록된 숫자를 확인해 주세요"(보험 판단 아님).
- **마이그레이션 0.** 모델 필드 전부 존재. 신규 필드/모델/DB 변경 없음.
- **테마 라이트 고정**(서비스 페이지 `dark:` 금지).
- 명령 실행 위치: BE는 `inpa_be/`, FE는 `inpa_fe/`. FE 검증 = `npm run build`(타입) + `npm run lint:copy`. BE 검증 = `python manage.py test`.
- **수기입력 보험 엣지:** `CustomerInsuranceManualViewSet`로 만든 보험은 `case_list`(담보 행)가 없다 → 담보별 요금 없음, 갱신/비갱신 분리도 0(보험 단위 필드 미채움). 오류 아님, `-`/빈 배열로 표시.

---

## File Structure

**백엔드 (`inpa_be/inpa/`)**
- `insurances/serializers.py` — `CaseFeeSerializer`(담보별 요금) + `InsuranceFeeSerializer`(보험별 요금+담보) 신규; `CustomerInsuranceManualSerializer` 필드 확장 (Task 1, 4)
- `analysis/views.py` — 히트맵 응답에 `insurances` 추가 (Task 2)
- `analysis/compare.py` — `_aggregate_side` 갱신/비갱신/적립 합 + `_respond`가 side에 `insurances` 추가 (Task 3)
- `insurances/tests.py`, `analysis/tests.py` — 테스트

**프론트엔드 (`inpa_fe/`)**
- `lib/api.ts` — 타입(`HeatmapSummary`·`InsuranceFee`·`InsuranceCaseFee`·`CompareSide`·`ManualInsuranceItem`) (Task 5)
- `components/premium-split.tsx` — `PremiumSummaryTable`·`CoverageFeeList`·`DataCheckNotice` 신규 (Task 6)
- `app/customer/[id]/page.tsx` — AnalysisTab(요약·담보표)·SwitchTab(비교표)·InsuranceCard(배지) (Task 6, 7, 8)

---

## Task 1: BE — 담보별/보험별 요금 시리얼라이저

**Files:**
- Modify: `inpa_be/inpa/insurances/serializers.py`
- Test: `inpa_be/inpa/insurances/tests.py`

**Interfaces:**
- Produces: `CaseFeeSerializer` → `{detail_name, premium, payment_period_type, is_renewal(bool), assurance_amount, total_renewal_premium, total_non_renewal_premium}`.
- Produces: `InsuranceFeeSerializer` → `{id, name, insurance_type, portfolio_type, monthly_premiums, monthly_renewal_premium, monthly_non_renewal_premium, monthly_earned_premium, total_premiums, total_renewal_premium, total_non_renewal_premium, total_earned_premium, case_fees: CaseFee[]}`. `case_fees` = `case_list` 직렬화(수기입력이면 `[]`).

- [ ] **Step 1: 실패 테스트 작성** — `inpa_be/inpa/insurances/tests.py` 끝에 추가

```python
from inpa.insurances.models import CustomerInsurance, CustomerInsuranceDetail, InsuranceDetail
from inpa.insurances.serializers import CaseFeeSerializer, InsuranceFeeSerializer


class FeeSerializerTests(TestCase):
    """담보별/보험별 요금 노출 — 갱신/비갱신 사실 직렬화."""

    def setUp(self):
        from inpa.accounts.models import Profile, User
        from django.utils import timezone
        self.user = User.objects.create_user(email='fee@test.com', password='inpaPass123!')
        Profile.objects.create(user=self.user, email_verified_at=timezone.now())
        from inpa.customers.models import Customer
        self.customer = Customer.objects.create(owner=self.user, name='김보장')
        self.ci = CustomerInsurance.objects.create(
            customer=self.customer, name='무배당 갱신암보험', insurance_type=2, portfolio_type=1,
            monthly_premiums=30000, monthly_renewal_premium=20000, monthly_non_renewal_premium=10000,
            monthly_earned_premium=0, total_premiums=1000, total_renewal_premium=700,
            total_non_renewal_premium=300, total_earned_premium=0)
        self.det = InsuranceDetail.objects.create(name='암진단비')
        self.case = CustomerInsuranceDetail.objects.create(
            insurance=self.ci, detail=self.det, premium=20000, payment_period_type=3,
            assurance_amount=50000000, total_renewal_premium=700, total_non_renewal_premium=0)

    def test_case_fee_fields_and_is_renewal(self):
        data = CaseFeeSerializer(self.case).data
        self.assertEqual(data['detail_name'], '암진단비')
        self.assertEqual(data['premium'], 20000)
        self.assertEqual(data['payment_period_type'], 3)
        self.assertTrue(data['is_renewal'])            # type==3 → 갱신
        self.assertEqual(data['assurance_amount'], 50000000)

    def test_insurance_fee_nests_case_fees(self):
        data = InsuranceFeeSerializer(self.ci).data
        self.assertEqual(data['monthly_renewal_premium'], 20000)
        self.assertEqual(data['monthly_non_renewal_premium'], 10000)
        self.assertEqual(len(data['case_fees']), 1)
        self.assertEqual(data['case_fees'][0]['detail_name'], '암진단비')

    def test_manual_insurance_has_empty_case_fees(self):
        manual = CustomerInsurance.objects.create(
            customer=self.customer, name='직접입력보험', insurance_type=1, portfolio_type=1,
            monthly_premiums=50000)
        data = InsuranceFeeSerializer(manual).data
        self.assertEqual(data['case_fees'], [])        # 담보 행 없음
        self.assertEqual(data['monthly_premiums'], 50000)
```

- [ ] **Step 2: 실패 확인**

Run (in `inpa_be/`): `python manage.py test inpa.insurances.tests.FeeSerializerTests -v 2`
Expected: FAIL — `ImportError: cannot import name 'CaseFeeSerializer'`.

- [ ] **Step 3: 시리얼라이저 추가** — `insurances/serializers.py`의 `CustomerInsuranceDetailSerializer`(43행) 아래에 추가

```python
class CaseFeeSerializer(serializers.ModelSerializer):
    """담보별 요금(사실) — 판정 없음. 갱신 여부는 payment_period_type=3."""
    detail_name = serializers.CharField(source='detail.name', read_only=True)
    is_renewal = serializers.SerializerMethodField()

    class Meta:
        model = CustomerInsuranceDetail
        fields = ('detail_name', 'premium', 'payment_period_type', 'is_renewal',
                  'assurance_amount', 'total_renewal_premium', 'total_non_renewal_premium')
        read_only_fields = fields

    def get_is_renewal(self, obj):
        return obj.payment_period_type == 3


class InsuranceFeeSerializer(serializers.ModelSerializer):
    """보험별 요금 요약 + 담보별 요금(case_fees). 수기입력 보험은 case_fees=[]."""
    case_fees = CaseFeeSerializer(source='case_list', many=True, read_only=True)

    class Meta:
        model = CustomerInsurance
        fields = ('id', 'name', 'insurance_type', 'portfolio_type',
                  'monthly_premiums', 'monthly_renewal_premium',
                  'monthly_non_renewal_premium', 'monthly_earned_premium',
                  'total_premiums', 'total_renewal_premium',
                  'total_non_renewal_premium', 'total_earned_premium',
                  'case_fees')
        read_only_fields = fields
```

- [ ] **Step 4: 통과 확인**

Run: `python manage.py test inpa.insurances.tests.FeeSerializerTests -v 2`
Expected: PASS (3 tests).

- [ ] **Step 5: 커밋**

```bash
git add inpa_be/inpa/insurances/serializers.py inpa_be/inpa/insurances/tests.py
git commit -m "feat(요금분리): 담보별/보험별 요금 시리얼라이저(CaseFee·InsuranceFee)"
```

---

## Task 2: BE — 보장분석(히트맵) 응답에 보험별 요금 추가

**Files:**
- Modify: `inpa_be/inpa/analysis/views.py`(응답 dict, 231행 부근)
- Test: `inpa_be/inpa/analysis/tests.py`

**Interfaces:**
- Consumes: `InsuranceFeeSerializer`(Task 1).
- Produces: `GET /customers/<id>/heatmap/` 응답에 `insurances: InsuranceFee[]` 추가. `summary`는 무변경(이미 6필드 포함).

- [ ] **Step 1: 실패 테스트 작성** — `analysis/tests.py` 끝에 추가

```python
class HeatmapInsurancesTests(TestCase):
    """히트맵 응답이 보험별 요금(insurances)을 담아 보낸다."""

    def setUp(self):
        from inpa.accounts.models import Profile, User
        from django.utils import timezone
        from rest_framework.test import APIClient
        from inpa.customers.models import Customer
        from inpa.insurances.models import CustomerInsurance
        self.user = User.objects.create_user(email='hm@test.com', password='inpaPass123!')
        self.user.is_active = True; self.user.save(update_fields=['is_active'])
        Profile.objects.create(user=self.user, email_verified_at=timezone.now())
        self.client = APIClient(); self.client.force_authenticate(user=self.user)
        self.customer = Customer.objects.create(owner=self.user, name='김보장')
        CustomerInsurance.objects.create(
            customer=self.customer, name='보험A', insurance_type=2, portfolio_type=1,
            monthly_premiums=30000, monthly_renewal_premium=20000, monthly_non_renewal_premium=10000)

    def test_heatmap_includes_insurances_with_split(self):
        r = self.client.get(f'/api/v1/customers/{self.customer.id}/heatmap/')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn('insurances', body)
        self.assertEqual(body['insurances'][0]['monthly_renewal_premium'], 20000)
        self.assertIn('case_fees', body['insurances'][0])
```

(주의: heatmap URL이 다르면 기존 `analysis/tests.py`의 히트맵 테스트에서 실제 경로 확인 후 맞춤.)

- [ ] **Step 2: 실패 확인**

Run: `python manage.py test inpa.analysis.tests.HeatmapInsurancesTests -v 2`
Expected: FAIL — 응답에 `insurances` 키 없음(KeyError/assertIn 실패).

- [ ] **Step 3: 뷰 수정** — `analysis/views.py` import에 `InsuranceFeeSerializer` 추가하고, 응답 dict(231행 `return Response({`)에 한 줄 추가

import 부(파일 상단 `from inpa.insurances.serializers import ...` 있으면 거기에, 없으면 신규):
```python
from inpa.insurances.serializers import InsuranceFeeSerializer
```
응답 dict에서 `'summary': summary,` 다음 줄에 추가:
```python
            'insurances': InsuranceFeeSerializer(insurance_list, many=True).data,
```
(`insurance_list`는 이미 133행에서 `case_list__detail` prefetch됨 → N+1 없음.)

- [ ] **Step 4: 통과 확인**

Run: `python manage.py test inpa.analysis.tests.HeatmapInsurancesTests -v 2`
Expected: PASS.

- [ ] **Step 5: 회귀 + 커밋**

Run: `python manage.py test inpa.analysis -v 1` → 기존 히트맵 테스트 포함 PASS.
```bash
git add inpa_be/inpa/analysis/views.py inpa_be/inpa/analysis/tests.py
git commit -m "feat(요금분리): 히트맵 응답에 보험별 요금(insurances) 추가"
```

---

## Task 3: BE — 비교분석 갱신/비갱신 분리 + 보험별 요금

**Files:**
- Modify: `inpa_be/inpa/analysis/compare.py`(`_aggregate_side` 93행, `_respond` 292-326행)
- Test: `inpa_be/inpa/analysis/tests.py`

**Interfaces:**
- Consumes: `InsuranceFeeSerializer`(Task 1).
- Produces: `POST /customers/<id>/compare/` 응답의 `current`/`proposed`에 6필드(`monthly_renewal_premium, monthly_non_renewal_premium, monthly_earned_premium, total_renewal_premium, total_non_renewal_premium, total_earned_premium`) + `insurances: InsuranceFee[]` 추가. `rows`·`verdict` 등 무변경.

- [ ] **Step 1: 실패 테스트 작성** — `analysis/tests.py` 끝에 추가

```python
class CompareRenewalSplitTests(TestCase):
    def setUp(self):
        from inpa.accounts.models import Profile, User
        from django.utils import timezone
        from rest_framework.test import APIClient
        from inpa.customers.models import Customer
        from inpa.insurances.models import CustomerInsurance
        self.user = User.objects.create_user(email='cmp@test.com', password='inpaPass123!')
        self.user.is_active = True; self.user.save(update_fields=['is_active'])
        Profile.objects.create(user=self.user, email_verified_at=timezone.now())
        self.client = APIClient(); self.client.force_authenticate(user=self.user)
        self.customer = Customer.objects.create(owner=self.user, name='김보장')
        CustomerInsurance.objects.create(
            customer=self.customer, name='보유A', insurance_type=2, portfolio_type=1,
            monthly_premiums=30000, monthly_renewal_premium=20000, monthly_non_renewal_premium=10000,
            monthly_earned_premium=0)
        CustomerInsurance.objects.create(
            customer=self.customer, name='제안B', insurance_type=2, portfolio_type=2,
            monthly_premiums=25000, monthly_renewal_premium=5000, monthly_non_renewal_premium=20000,
            monthly_earned_premium=0)

    def test_compare_sides_carry_renewal_split_and_insurances(self):
        r = self.client.post(f'/api/v1/customers/{self.customer.id}/compare/', {}, format='json')
        self.assertEqual(r.status_code, 200)
        cur = r.json()['current']; prop = r.json()['proposed']
        self.assertEqual(cur['monthly_renewal_premium'], 20000)
        self.assertEqual(prop['monthly_non_renewal_premium'], 20000)
        self.assertEqual(cur['insurances'][0]['name'], '보유A')
        self.assertIn('case_fees', cur['insurances'][0])
```

- [ ] **Step 2: 실패 확인**

Run: `python manage.py test inpa.analysis.tests.CompareRenewalSplitTests -v 2`
Expected: FAIL — `current`에 `monthly_renewal_premium`/`insurances` 없음.

- [ ] **Step 3: `_aggregate_side` 확장** — `compare.py:93` 함수 교체

```python
def _aggregate_side(insurance_list):
    """한 측(보유/제안) → (summary, {coverage_name: amount}) 집계. 사실만, 판정 없음.

    summary: 월/총 보험료 + 갱신/비갱신/적립 분리(모델의 기존 필드 합, None 안전).
    coverage_amounts: 표준 담보(AnalysisDetail.name)별 보장금액 합.
    """
    keys = ('monthly_premiums', 'monthly_renewal_premium', 'monthly_non_renewal_premium',
            'monthly_earned_premium', 'total_premiums', 'total_renewal_premium',
            'total_non_renewal_premium', 'total_earned_premium')
    if not insurance_list:
        return {k: None for k in keys}, {}

    acc = {k: 0 for k in keys}
    coverage_amounts = {}
    for ci in insurance_list:
        for k in keys:
            v = getattr(ci, k, None)
            if v is not None:
                acc[k] += v
        for case in ci.case_list.all():
            amount = case.assurance_amount or 0
            if amount <= 0:
                continue
            std_names = [ad.name for ad in case.detail.analysis_detail.all()]
            if not std_names:
                std_names = [case.detail.name]
            for name in std_names:
                coverage_amounts[name] = coverage_amounts.get(name, 0) + amount

    summary = {k: (round(acc[k]) if isinstance(acc[k], float) else acc[k]) for k in keys}
    return summary, coverage_amounts
```

- [ ] **Step 4: `_respond`에서 side에 insurances 추가** — `compare.py`의 `_respond`, `current_summary, current_amounts = _aggregate_side(current_list)`(292행) 뒤에 추가

```python
        from inpa.insurances.serializers import InsuranceFeeSerializer  # 지역 import(순환 방지)
        current_summary['insurances'] = InsuranceFeeSerializer(current_list, many=True).data
        proposed_summary['insurances'] = InsuranceFeeSerializer(proposed_list, many=True).data
```
(응답의 `'current': current_summary` / `'proposed': proposed_summary`가 그대로 `insurances`를 실어 나름. `_generate_guide_draft`는 summary의 숫자 키만 참조하므로 무해.)

- [ ] **Step 5: 통과 + 회귀 + 커밋**

Run: `python manage.py test inpa.analysis.tests.CompareRenewalSplitTests -v 2` → PASS.
Run: `python manage.py test inpa.analysis -v 1` → 기존 compare 테스트 PASS.
```bash
git add inpa_be/inpa/analysis/compare.py inpa_be/inpa/analysis/tests.py
git commit -m "feat(요금분리): 비교분석 갱신/비갱신/적립 분리 + 보험별 요금"
```

---

## Task 4: BE — 수기 보험 시리얼라이저 갱신 필드 노출

**Files:**
- Modify: `inpa_be/inpa/insurances/serializers.py`(`CustomerInsuranceManualSerializer`, 49-61행)
- Test: `inpa_be/inpa/insurances/tests.py`

**Interfaces:**
- Produces: 수기 보험 목록/상세 응답에 `payment_period_type, monthly_renewal_premium, monthly_non_renewal_premium, monthly_earned_premium` 추가(수기입력이면 대개 null).

- [ ] **Step 1: 실패 테스트 작성** — `insurances/tests.py`의 `FeeSerializerTests`에 메서드 추가

```python
    def test_manual_serializer_exposes_renewal_fields(self):
        from inpa.insurances.serializers import CustomerInsuranceManualSerializer
        data = CustomerInsuranceManualSerializer(self.ci).data
        self.assertIn('monthly_renewal_premium', data)
        self.assertIn('monthly_non_renewal_premium', data)
        self.assertIn('payment_period_type', data)
```

- [ ] **Step 2: 실패 확인**

Run: `python manage.py test inpa.insurances.tests.FeeSerializerTests.test_manual_serializer_exposes_renewal_fields -v 2`
Expected: FAIL — 키 없음.

- [ ] **Step 3: 필드 추가** — `CustomerInsuranceManualSerializer.Meta.fields`(57행) 교체

```python
        fields = ('id', 'name', 'insurance_type', 'portfolio_type',
                  'monthly_premiums', 'monthly_renewal_premium',
                  'monthly_non_renewal_premium', 'monthly_earned_premium',
                  'payment_period_type', 'contract_date', 'expiry_date',
                  'contractor_name', 'insured_name', 'is_same_insured',
                  'payment_status', 'is_cancelled', 'cancelled_at', 'created_at')
```
(신규 필드는 읽기 노출용. 쓰기(수기 등록)는 기존대로 monthly_premiums 등만 입력 — 신규 필드는 optional이라 등록 검증 무영향. `read_only_fields`는 `('id','created_at')` 유지.)

- [ ] **Step 4: 통과 + 회귀 + 커밋**

Run: `python manage.py test inpa.insurances -v 1` → PASS(수기 등록 기존 테스트 포함).
```bash
git add inpa_be/inpa/insurances/serializers.py inpa_be/inpa/insurances/tests.py
git commit -m "feat(요금분리): 수기 보험 시리얼라이저에 갱신/비갱신 월보험료 노출"
```

---

## Task 5: FE — api.ts 타입

**Files:**
- Modify: `inpa_fe/lib/api.ts`(`HeatmapSummary`:813, `HeatmapResponse`:819, `CompareSide`:2264, `ManualInsuranceItem`:2325)

**Interfaces:**
- Produces: `InsuranceCaseFee`, `InsuranceFee` 타입; `HeatmapSummary`·`CompareSide`·`ManualInsuranceItem` 확장; `HeatmapResponse.insurances`, `CompareSide.insurances`.

- [ ] **Step 1: 타입 추가/확장** — `HeatmapSummary`(813행) 위에 신규 타입 추가

```typescript
export interface InsuranceCaseFee {
  detail_name: string;
  premium: number | null;             // 월 보험료(담보)
  payment_period_type: number;        // 1 년/2 세 = 비갱신, 3 년갱신 = 갱신
  is_renewal: boolean;
  assurance_amount: number | null;
  total_renewal_premium: number | null;
  total_non_renewal_premium: number | null;
}

export interface InsuranceFee {
  id: number;
  name: string | null;
  insurance_type: number;
  portfolio_type: number;
  monthly_premiums: number | null;
  monthly_renewal_premium: number | null;
  monthly_non_renewal_premium: number | null;
  monthly_earned_premium: number | null;
  total_premiums: number | null;
  total_renewal_premium: number | null;
  total_non_renewal_premium: number | null;
  total_earned_premium: number | null;
  case_fees: InsuranceCaseFee[];      // 수기입력 보험은 []
}
```

- [ ] **Step 2: `HeatmapSummary` 확장**(813행) — 필드 추가

```typescript
export interface HeatmapSummary {
  monthly_premiums: number | null;
  monthly_renewal_premium: number | null;
  monthly_non_renewal_premium: number | null;
  monthly_earned_premium: number | null;
  total_premiums: number | null;
  total_renewal_premium: number | null;
  total_non_renewal_premium: number | null;
  total_earned_premium: number | null;
  [key: string]: unknown;
}
```

- [ ] **Step 3: `HeatmapResponse`에 insurances**(819행 인터페이스 본문에 추가)

```typescript
  insurances: InsuranceFee[];
```

- [ ] **Step 4: `CompareSide` 확장**(2264행) — 필드 추가

```typescript
export interface CompareSide {
  monthly_premiums: number | null;
  total_premiums: number | null;
  monthly_renewal_premium: number | null;
  monthly_non_renewal_premium: number | null;
  monthly_earned_premium: number | null;
  total_renewal_premium: number | null;
  total_non_renewal_premium: number | null;
  total_earned_premium: number | null;
  insurances: InsuranceFee[];
}
```

- [ ] **Step 5: `ManualInsuranceItem` 확장**(2325행) — 필드 추가(옵셔널)

```typescript
  monthly_renewal_premium?: number | null;
  monthly_non_renewal_premium?: number | null;
  monthly_earned_premium?: number | null;
  payment_period_type?: number | null;
```

- [ ] **Step 6: 빌드 + 커밋**

Run (in `inpa_fe/`): `npm run build` → 성공(기존 사용처는 옵셔널/추가라 무영향).
```bash
git add inpa_fe/lib/api.ts
git commit -m "feat(요금분리): FE 타입(InsuranceFee·case_fee + summary/side 확장)"
```

---

## Task 6: FE — 보장분석 요약·담보별 요금 표 + 데이터 확인 안내

**Files:**
- Create: `inpa_fe/components/premium-split.tsx`
- Modify: `inpa_fe/app/customer/[id]/page.tsx`(AnalysisTab — 히트맵 렌더 영역)

**Interfaces:**
- Consumes: `HeatmapSummary`, `InsuranceFee`(Task 5). `fmtWon`(`@/components/heatmap`).
- Produces: `<PremiumSplitSection summary={...} insurances={...} />`.

- [ ] **Step 1: 컴포넌트 작성** — `inpa_fe/components/premium-split.tsx` 신규

```tsx
"use client";

// 보험료 갱신/비갱신/적립 분리 — 표·절대수치만(판정·색·등급 없음). 사실 정리.
import { fmtWon } from "@/components/heatmap";
import type { HeatmapSummary, InsuranceFee } from "@/lib/api";

function Row({ label, value }: { label: string; value: number | null | undefined }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-line last:border-0">
      <span className="text-[13px] text-ink2">{label}</span>
      <span className="text-[14px] font-semibold text-ink tnum">{value == null ? "-" : fmtWon(value)}</span>
    </div>
  );
}

function SummaryTable({ title, renewal, nonRenewal, earned, total }: {
  title: string; renewal: number | null; nonRenewal: number | null; earned: number | null; total: number | null;
}) {
  return (
    <div className="rounded-xl border border-line bg-surface px-4 py-3">
      <div className="text-[13px] font-bold text-ink mb-1.5">{title}</div>
      <Row label="갱신형 (갱신 시 달라질 수 있어요)" value={renewal} />
      <Row label="비갱신형 (만기까지 고정)" value={nonRenewal} />
      <Row label="적립" value={earned} />
      <div className="flex items-center justify-between pt-2 mt-1 border-t border-line">
        <span className="text-[13px] font-bold text-ink">합계</span>
        <span className="text-[15px] font-extrabold text-ink tnum">{total == null ? "-" : fmtWon(total)}</span>
      </div>
    </div>
  );
}

function DataCheckNotice({ summary }: { summary: HeatmapSummary }) {
  const mp = summary.monthly_premiums ?? 0;
  const r = summary.monthly_renewal_premium ?? 0;
  const nr = summary.monthly_non_renewal_premium ?? 0;
  const e = summary.monthly_earned_premium ?? 0;
  const gap = mp - r - nr - e;
  const overage = Math.max(0, -gap);
  const unclassified = gap > 1000 && gap > mp * 0.05 ? gap : 0;
  if (overage <= 0 && unclassified <= 0) return null;
  const msg = overage > 0
    ? `등록된 담보 보험료 합이 월 보험료보다 큽니다. 등록된 숫자를 확인해 주세요. (차이 ${fmtWon(overage)})`
    : `월 보험료 중 일부가 갱신·비갱신·적립으로 분류되지 않았어요(직접 입력 보험 포함 가능). 등록된 숫자를 확인해 주세요. (${fmtWon(unclassified)})`;
  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-[12px] text-amber-800 leading-5">
      {msg}
    </div>
  );
}

function CoverageFeeList({ insurances }: { insurances: InsuranceFee[] }) {
  const withCases = insurances.filter((i) => i.case_fees.length > 0);
  const manual = insurances.filter((i) => i.case_fees.length === 0);
  return (
    <div className="space-y-3">
      {withCases.map((ins) => (
        <div key={ins.id} className="rounded-xl border border-line bg-surface">
          <div className="flex items-center justify-between px-4 py-2 border-b border-line">
            <span className="text-[13px] font-bold text-ink">{ins.name ?? "보험"}</span>
            <span className="text-[12px] text-ink3">월 {ins.monthly_premiums == null ? "-" : fmtWon(ins.monthly_premiums)}</span>
          </div>
          <div className="px-4 py-1.5">
            <div className="flex items-center text-[11px] text-ink3 py-1 border-b border-line">
              <span className="flex-1">담보</span>
              <span className="w-16 text-right">구분</span>
              <span className="w-24 text-right">월 보험료</span>
            </div>
            {ins.case_fees.map((c, i) => (
              <div key={i} className="flex items-center text-[13px] text-ink2 py-1.5 border-b border-line last:border-0">
                <span className="flex-1">{c.detail_name}</span>
                <span className="w-16 text-right text-[12px] text-ink3">{c.is_renewal ? "갱신형" : "비갱신형"}</span>
                <span className="w-24 text-right font-semibold text-ink tnum">{c.premium == null ? "-" : fmtWon(c.premium)}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
      {manual.map((ins) => (
        <div key={ins.id} className="rounded-xl border border-line bg-surface2 px-4 py-2.5 flex items-center justify-between">
          <span className="text-[13px] text-ink2">{ins.name ?? "보험"} · 직접 입력(담보 내역 없음)</span>
          <span className="text-[12px] text-ink3">월 {ins.monthly_premiums == null ? "-" : fmtWon(ins.monthly_premiums)}</span>
        </div>
      ))}
    </div>
  );
}

export function PremiumSplitSection({ summary, insurances }: { summary: HeatmapSummary; insurances: InsuranceFee[] }) {
  return (
    <section className="mt-6 space-y-3">
      <h3 className="text-[15px] font-bold text-ink">보험료 (갱신/비갱신)</h3>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <SummaryTable title="월 보험료" renewal={summary.monthly_renewal_premium}
          nonRenewal={summary.monthly_non_renewal_premium} earned={summary.monthly_earned_premium}
          total={summary.monthly_premiums} />
        <SummaryTable title="총 보험료" renewal={summary.total_renewal_premium}
          nonRenewal={summary.total_non_renewal_premium} earned={summary.total_earned_premium}
          total={summary.total_premiums} />
      </div>
      <DataCheckNotice summary={summary} />
      <h4 className="text-[14px] font-bold text-ink pt-1">담보별 요금</h4>
      <CoverageFeeList insurances={insurances} />
    </section>
  );
}
```

- [ ] **Step 2: AnalysisTab에서 렌더** — `app/customer/[id]/page.tsx`

상단 import에 추가:
```tsx
import { PremiumSplitSection } from "@/components/premium-split";
```
AnalysisTab의 히트맵(`<HeatmapGrid .../>`) 렌더 뒤, 히트맵 데이터가 있을 때 추가:
```tsx
      {heatmap && heatmap.insurance_count > 0 && (
        <PremiumSplitSection summary={heatmap.summary} insurances={heatmap.insurances} />
      )}
```
(정확한 위치: AnalysisTab에서 `heatmap` 상태로 히트맵을 그리는 JSX 블록 바로 아래. `heatmap.insurances`는 Task 2에서 응답에 추가됨.)

- [ ] **Step 3: 빌드 + 카피가드**

Run (in `inpa_fe/`): `npm run build` → 성공. `npm run lint:copy` → 위반 0(문구에 em-dash 없음 확인).

- [ ] **Step 4: 커밋**

```bash
git add inpa_fe/components/premium-split.tsx "inpa_fe/app/customer/[id]/page.tsx"
git commit -m "feat(요금분리): 보장분석 요약·담보별 요금 표 + 데이터 확인 안내"
```

---

## Task 7: FE — 비교분석 갱신/비갱신 표 + 증감

**Files:**
- Modify: `inpa_fe/components/premium-split.tsx`(비교용 컴포넌트 추가)
- Modify: `inpa_fe/app/customer/[id]/page.tsx`(SwitchTab)

**Interfaces:**
- Consumes: `CompareResponse`·`CompareSide`(Task 5). `fmtWon`.
- Produces: `<ComparePremiumSplit current={...} proposed={...} />`.

- [ ] **Step 1: 비교 컴포넌트 추가** — `premium-split.tsx` 끝에 추가

```tsx
import type { CompareSide } from "@/lib/api";

function DeltaCell({ cur, prop }: { cur: number | null; prop: number | null }) {
  if (cur == null || prop == null) return <span className="text-ink3">-</span>;
  const d = prop - cur;
  const sign = d > 0 ? "+" : d < 0 ? "-" : "";
  return <span className="tnum text-ink2">{sign}{fmtWon(Math.abs(d))}</span>;
}

function CompareRow({ label, cur, prop }: { label: string; cur: number | null; prop: number | null }) {
  return (
    <div className="grid grid-cols-4 items-center text-[13px] py-1.5 border-b border-line last:border-0">
      <span className="text-ink2">{label}</span>
      <span className="text-right font-semibold text-ink tnum">{cur == null ? "-" : fmtWon(cur)}</span>
      <span className="text-right font-semibold text-ink tnum">{prop == null ? "-" : fmtWon(prop)}</span>
      <span className="text-right"><DeltaCell cur={cur} prop={prop} /></span>
    </div>
  );
}

export function ComparePremiumSplit({ current, proposed }: { current: CompareSide; proposed: CompareSide }) {
  return (
    <section className="mt-5 rounded-xl border border-line bg-surface px-4 py-3">
      <h4 className="text-[14px] font-bold text-ink mb-2">보험료 비교 (갱신/비갱신)</h4>
      <div className="grid grid-cols-4 text-[11px] text-ink3 pb-1 border-b border-line">
        <span></span><span className="text-right">현재</span><span className="text-right">제안</span><span className="text-right">증감</span>
      </div>
      <div className="text-[12px] font-bold text-ink3 pt-2">월 보험료</div>
      <CompareRow label="갱신형" cur={current.monthly_renewal_premium} prop={proposed.monthly_renewal_premium} />
      <CompareRow label="비갱신형" cur={current.monthly_non_renewal_premium} prop={proposed.monthly_non_renewal_premium} />
      <CompareRow label="적립" cur={current.monthly_earned_premium} prop={proposed.monthly_earned_premium} />
      <CompareRow label="합계" cur={current.monthly_premiums} prop={proposed.monthly_premiums} />
      <div className="text-[12px] font-bold text-ink3 pt-3">총 보험료</div>
      <CompareRow label="갱신형" cur={current.total_renewal_premium} prop={proposed.total_renewal_premium} />
      <CompareRow label="비갱신형" cur={current.total_non_renewal_premium} prop={proposed.total_non_renewal_premium} />
      <CompareRow label="적립" cur={current.total_earned_premium} prop={proposed.total_earned_premium} />
      <CompareRow label="합계" cur={current.total_premiums} prop={proposed.total_premiums} />
    </section>
  );
}
```

- [ ] **Step 2: SwitchTab에서 렌더** — `app/customer/[id]/page.tsx`

import에 `ComparePremiumSplit` 추가(같은 파일에서 `PremiumSplitSection`와 함께):
```tsx
import { PremiumSplitSection, ComparePremiumSplit } from "@/components/premium-split";
```
SwitchTab의 비교 결과(`data.current`/`data.proposed`)가 있는 곳, 기존 담보 비교표 위/아래에 추가:
```tsx
      {data && <ComparePremiumSplit current={data.current} proposed={data.proposed} />}
```
(담보별 요금 상세가 더 필요하면 `data.current.insurances`로 `CoverageFeeList` 재사용 — 이번 태스크 범위는 요약·증감표. 담보별 상세는 동일 `CoverageFeeList` export를 붙여 확장 가능.)

- [ ] **Step 3: 빌드 + 카피가드 + 커밋**

Run: `npm run build` → 성공. `npm run lint:copy` → 0.
```bash
git add inpa_fe/components/premium-split.tsx "inpa_fe/app/customer/[id]/page.tsx"
git commit -m "feat(요금분리): 비교분석 갱신/비갱신 요약·증감 표(절대금액)"
```

---

## Task 8: FE — 보험 카드 갱신/비갱신 표시

**Files:**
- Modify: `inpa_fe/app/customer/[id]/page.tsx`(InsuranceCard — `listManualInsurances` 카드)

**Interfaces:**
- Consumes: `ManualInsuranceItem`(Task 5 확장 필드).

- [ ] **Step 1: 카드에 갱신/비갱신 표시 추가** — `InsuranceCard`(page.tsx `it.monthly_premiums` 표시부, 약 1011행)

기존 "월 보험료" 표시 아래에 추가(값 있을 때만):
```tsx
      {(it.monthly_renewal_premium != null || it.monthly_non_renewal_premium != null) && (
        <div className="mt-1 flex gap-3 text-[12px] text-ink3">
          {it.monthly_renewal_premium != null && <span>갱신 {fmtWon(it.monthly_renewal_premium)}</span>}
          {it.monthly_non_renewal_premium != null && <span>비갱신 {fmtWon(it.monthly_non_renewal_premium)}</span>}
        </div>
      )}
```
(`fmtWon`은 이 파일에서 이미 import됨 — heatmap에서. 없으면 `import { fmtWon } from "@/components/heatmap";` 확인.)

- [ ] **Step 2: 빌드 + 카피가드 + 커밋**

Run: `npm run build` → 성공. `npm run lint:copy` → 0.
```bash
git add "inpa_fe/app/customer/[id]/page.tsx"
git commit -m "feat(요금분리): 보험 카드에 월 갱신/비갱신 보험료 표시"
```

---

## Task 9: 최종 검증

- [ ] **Step 1: BE 전체**

Run (in `inpa_be/`): `python manage.py test inpa` → 전부 PASS.
Run: `python manage.py check` → 0 issues.

- [ ] **Step 2: FE 전체**

Run (in `inpa_fe/`): `npm run build` → 성공. `npm run lint:copy` → 위반 0.

- [ ] **Step 3: 수동 스모크(로컬)**

BE `runserver` + FE `npm run dev` → OCR(pdfplumber)로 등록된 고객 상세 → 보장분석 탭: 월/총 요약 표(갱신·비갱신·적립·합계) + 담보별 요금 표 + (필요시) 데이터 확인 안내. 비교분석 탭: 현재↔제안 갱신/비갱신 증감표. 판정어·색·등급 없음 확인.

---

## Self-Review

**1. Spec coverage**
- §5.1 CaseFeeSerializer/InsuranceFeeSerializer → Task 1 ✓
- §5.2 히트맵 insurances → Task 2 ✓
- §5.3 보장분석 표 3종 + 데이터 안내 → Task 6 ✓
- §5.4 비교 _aggregate_side 분리 + side insurances → Task 3 ✓
- §5.5 비교 표·증감 → Task 7 ✓
- §5.6 보험 카드 + Manual serializer → Task 4(BE), Task 8(FE) ✓
- §6 FE 타입 → Task 5 ✓
- §7 엣지(수기입력 case_fees=[], null='-') → Task 1(test)·Task 6(manual 분기) ✓
- §2 컴플라이언스(판정·색·등급 없음, verdict 미노출) → 표 컴포넌트 무채색·verdict 무변경 ✓
- §8 테스트 → 각 Task 테스트 + Task 9 ✓
- 마이그레이션 0 → 신규 필드 없음 ✓

**2. Placeholder scan** — TBD/TODO 없음. 모든 code step에 실제 코드·명령·기대출력. (Task 2·6·7의 "정확한 위치"는 실제 렌더 블록 지시 + 완전한 삽입 코드 제공.)

**3. Type consistency**
- `InsuranceCaseFee`/`InsuranceFee`: Task 5 정의 = Task 6·7 소비 일치 ✓
- `CaseFeeSerializer` fields(detail_name·premium·payment_period_type·is_renewal·assurance_amount·total_renewal_premium·total_non_renewal_premium) = FE `InsuranceCaseFee` 일치 ✓
- `InsuranceFeeSerializer` fields = FE `InsuranceFee` 일치(id·name·insurance_type·portfolio_type·월×4·총×4·case_fees) ✓
- `_aggregate_side` summary keys(8개) = `CompareSide` 확장 필드 일치 ✓
- `PremiumSplitSection(summary, insurances)` = AnalysisTab 호출 일치 / `ComparePremiumSplit(current, proposed)` = SwitchTab 호출 일치 ✓

이슈 없음.

---

## Execution Handoff

플랜 완료 → `docs/superpowers/plans/2026-07-02-renewal-premium-split.md`.
