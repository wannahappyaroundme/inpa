# 갱신/비갱신 요금 분리 (보장분석·비교분석) — Design Spec

> 작성 2026-07-02. 보장분석·비교분석에서 보험료를 **갱신형/비갱신형/적립**으로 나눠 **표·절대수치**로 보여준다.
> 원본 foliio의 데이터 완결성은 살리되, foliio의 **자체 기준 판정(레이더·충분도)은 이식하지 않는다**(금융법/보험중개 레드라인).

---

## 1. 목표 (Goal)

설계사가 고객의 보험료 구조를 **사실 그대로** 파악하도록, 보험료를 아래로 분리해 표시한다.

- **갱신형(payment_period_type=3='년 갱신')**: 갱신 시점마다 보험료가 달라질 수 있는 부분.
- **비갱신형(payment_period_type=1='년', 2='세')**: 만기까지 고정되는 부분.
- **적립(earned)**: 보장이 아닌 적립/환급 성격의 보험료(보험 단위 값).

가입설계서처럼 **담보 하나하나의 보험료**까지 나열한다.

### 비목표 (Non-goals / YAGNI)
- ❌ 도넛/파이 차트, 가로 막대, 나이대 세그먼트(coverage-segments) 등 **상대수치 시각화** — 전부 제외. 표+절대숫자만.
- ❌ 보험료에 대한 **등급·색·판정어**(적정/과함/부족/좋다/나쁘다/손해) — 인파는 보험을 판단하지 않는다.
- ❌ foliio의 자체 기준 판정(radar chart, chart_based_amount 대비 충분도) 이식.
- ❌ 갈아타기 권유. 비교분석의 KEEP/SWITCH verdict는 **설계사 내부 전용**, 고객 대면(`/s`)에 노출 0(기존 규칙 유지).
- ❌ 신규 계산 로직/모델 필드/마이그레이션. **데이터는 이미 계산되어 저장**되어 있고, 이 작업은 "이미 있는 값을 응답·화면에 드러내기"다.

---

## 2. 컴플라이언스 레드라인 (SPEC 전반에 강제)

인파가 보험의 옳고 그름을 판단하면 무등록 보험중개·금융법 위반이다. 기준은 설계사가 정한다.

1. **보험료 표시는 사실(등록된 숫자) 정리일 뿐.** 판정어·등급·색·권유 문구 **0**. 라벨은 사실만: "갱신형(갱신 시 달라질 수 있음)" / "비갱신형(만기까지 고정)".
2. **보험료엔 등급 개념 없음.** 등급(부족/적정/넉넉)은 지금처럼 **보장금액에만**, 그것도 **설계사가 세운 `PlannerBaseline`이 있을 때(graded)만**. 보험료는 항상 숫자만.
3. **비교분석**: 숫자·증감만. verdict(KEEP/SWITCH/NEUTRAL)는 BE가 고객 공유뷰에 애초에 전송하지 않음(현 구조 유지). 인파가 "갈아타세요" 권유하지 않음.
4. **데이터 확인 안내**(§5.3)는 "이 보험이 잘못됐다"가 아니라 "**등록된 숫자를 확인해 주세요**"(추출 데이터 정합성)로 중립 표현.
5. **고객 대면 노출 없음.** 이 기능은 설계사 내부 도구(보장분석 탭·비교분석 탭)에만. `/s` 공유뷰 무변경.

---

## 3. 데이터 현실 (검증 완료 — 설계의 근거)

추출 메커니즘은 **OCR이 아니라 pdfplumber**다. `pdfplumber.open().extract_text()`로 전자 PDF 텍스트를 뽑고(`inpa_be/inpa/insurances/views.py:130-132`), Claude(`core/ocr/claude_parser.py`) 또는 정규식 폴백(`core/ocr/ocrparsing.py`)이 담보·보험료로 구조화한다. **이미지/스캔 PDF는 거부**(`views.py:141-142`, `IMAGE_PDF`). 실제 OCR 라이브러리는 없다.

### 3.1 담보별 요금은 존재한다 (pdfplumber 경로)
`CustomerInsuranceDetail`(= 보험 1건의 담보 1개, `related_name="case_list"`, `insurances/models.py:436-478`):
- `detail.name` — 담보명(readable, `InsuranceDetail.name`)
- `premium` (`:459`) — 그 담보의 **월 보험료**
- `payment_period_type` (`:460`) — 1=년/2=세=**비갱신**, 3=년갱신=**갱신**
- `assurance_amount` (`:458`) — 보장금액
- `total_renewal_premium` / `total_non_renewal_premium` (`:465-466`) — 그 담보의 **총 갱신/비갱신 보험료**, `.calculate()`(`:479-516`)가 `premium`으로 산출(갱신은 `renewal_growth_rate` fv 반영)

저장 경로(pdfplumber → Claude/정규식 → DB, `views.py::_persist_ocr`):
1. `CustomerInsuranceDetail` 생성 시 `premium`·`payment_period_type`·`assurance_amount` 채움(`views.py:270-279`).
2. 각 case `.calculate(ci)` 호출 → 담보별 총 갱신/비갱신 채움(`views.py:297-299`).
3. `ci.calculate()` → 보험 단위 집계(`views.py:300`, `models.py:336-433`): `monthly_renewal_premium`·`monthly_non_renewal_premium`·`monthly_earned_premium`·`total_renewal_premium`·`total_non_renewal_premium`·`total_earned_premium`(`models.py:427-433`).

### 3.2 보험 단위·포트폴리오 요약은 이미 응답에 온다
`analysis/views.py:221-229`가 히트맵 `summary`에 이미 아래를 담아 보낸다(FE 타입만 미선언):
`monthly_premiums, monthly_renewal_premium, monthly_non_renewal_premium, monthly_earned_premium, total_premiums, total_renewal_premium, total_non_renewal_premium, total_earned_premium, total_cancellation_refund, total_cancellation_loss, total_prepaid_insurance_premium, total_pay_insurance_premium`.
히트맵은 `insurance_list`(= `CustomerInsuranceSerializer.data`)도 함께 보낸다.

### 3.3 ★ 엣지: 수기(직접) 입력 보험은 담보 행이 없다
`CustomerInsuranceManualViewSet`(`views.py:457-458`)는 `CustomerInsuranceDetail`(case_list)을 **생성하지 않는다**. `.calculate()`도 안 돈다. 따라서 수기입력 보험은:
- 담보별 요금 **없음** → 담보별 표에서 그 보험은 "직접 입력(담보 내역 없음)"으로 표기.
- 갱신/비갱신 분리도 **없음**(보험 단위 `monthly_renewal_premium` 등 미채움) → 요약에서 이 보험은 `monthly_premiums`(합계)에만 기여, 갱신/비갱신엔 0.
- 결과: **`갱신+비갱신+적립`이 `합계`보다 작을 수 있다**(그 차이 = 수기입력분 + 미분류분). §5.3 데이터 안내가 이 차이를 중립적으로 처리.

---

## 4. 아키텍처 개요

```
[BE] CustomerInsuranceDetail(담보별 premium·type·총갱신/비갱신)  ← 이미 저장됨(pdfplumber 경로)
      │
      ├─ (신규 노출) CaseFeeSerializer  ─────────────┐
      │                                              ▼
   보장분석: CustomerHeatmapView                비교분석: CustomerCompareView
      │  insurance_list에 case_fees[] 중첩          │  _aggregate_side에 갱신/비갱신/적립 합 추가
      │  summary(이미 옴)                           │  current/proposed에 case_fees[] 중첩
      ▼                                              ▼
[FE] HeatmapResponse.summary(+6필드) +         CompareResponse.current/proposed(+필드)
     insurance_list[].case_fees[]              + insurance별 case_fees[]
      │                                              │
      ▼                                              ▼
   보장분석 탭: 요약 표 + 담보별 요금 표          비교분석 탭: 현재↔제안 요약 표 + 담보별 표 + 증감
   + 데이터 확인 안내(중립)                       (증감=절대금액, 판정/권유 없음)
```

**마이그레이션 0** (모델 필드 전부 존재). 신규 = 시리얼라이저/응답 필드 + FE 표.

---

## 5. 컴포넌트별 설계 (Units)

각 유닛은 하나의 목적, 명확한 인터페이스, 독립 테스트 가능하게.

### 5.1 BE — 담보별 요금 시리얼라이저 (신규)
**파일:** `inpa_be/inpa/insurances/serializers.py`
**신규:** `CaseFeeSerializer(ModelSerializer)` — `CustomerInsuranceDetail` 대상, 아래 read-only 필드:
- `detail_name` (source=`detail.name`)
- `premium` (월 보험료)
- `payment_period_type` (1/2/3)
- `is_renewal` (SerializerMethodField: `payment_period_type == 3`)
- `assurance_amount` (보장금액)
- `total_renewal_premium`, `total_non_renewal_premium`

**인터페이스(생산):** 담보 1행 = `{detail_name, premium, payment_period_type, is_renewal, assurance_amount, total_renewal_premium, total_non_renewal_premium}`.

### 5.2 BE — 보장분석(히트맵) insurance_list에 담보별 요금 중첩
**파일:** `inpa_be/inpa/insurances/serializers.py`(`CustomerInsuranceSerializer`), `inpa_be/inpa/analysis/views.py`
- `CustomerInsuranceSerializer`에 `case_fees = CaseFeeSerializer(source='case_list', many=True, read_only=True)` 추가. (+ 이미 노출 중이 아니면 `monthly_renewal_premium`·`monthly_non_renewal_premium`·`monthly_earned_premium`도 확인해 노출)
- `views.py`의 heatmap `summary`는 **변경 없음**(이미 6필드 포함). `insurance_list`가 자동으로 `case_fees`를 실어 나른다.
- N+1 방지: `insurance_list` 쿼리에 `.prefetch_related('case_list__detail')` 확인/추가.

**인터페이스:** `GET /customers/<id>/heatmap/` 응답의 `insurance_list[].case_fees[]`.

### 5.3 FE — 보장분석 표 3종
**파일:** `inpa_fe/lib/api.ts`, `inpa_fe/components/heatmap.tsx`, `inpa_fe/app/customer/[id]/page.tsx`(AnalysisTab), `inpa_fe/app/analysis/page.tsx`
1. **요약 표(월):** 갱신 / 비갱신 / 적립 / 합계 = `summary.monthly_renewal_premium`·`monthly_non_renewal_premium`·`monthly_earned_premium`·`monthly_premiums`.
2. **요약 표(총):** `total_renewal_premium`·`total_non_renewal_premium`·`total_earned_premium`·`total_premiums`.
3. **담보별 요금 표(보험별로 묶음, 가입설계서 방식):** 각 보험(`insurance_list[i]`)마다 `case_fees[]` 나열 — `담보명 | 월 보험료 | 구분(갱신형/비갱신형) | 총 보험료`. 순수 한 종류면 보험 헤더에 '갱신형/비갱신형' 배지. **담보 내역 없는 보험(수기입력)**은 "직접 입력 · 담보 내역 없음, 월 보험료 {monthly_premiums}"로 한 줄.

**데이터 확인 안내(중립, foliio 공식 재사용):** `gap = monthly_premiums - (renewal + non_renewal + earned)`.
- `overage = max(0, -gap)` > 0 → "등록된 담보 보험료 합이 월 보험료보다 큽니다. 숫자를 확인해 주세요."
- `unclassified = gap` (단, `gap > 1000` **그리고** `gap > monthly_premiums * 0.05` 일 때만) → "월 보험료 중 일부가 갱신/비갱신/적립으로 분류되지 않았어요(수기입력 보험 포함 가능). 숫자를 확인해 주세요."
- 문구는 **데이터 확인**이지 보험 판단 아님. '기타' 줄은 만들지 않음(foliio도 0으로 숨김).

값이 null/미상이면 `-`. **판정·색·등급 없음**(요약·담보 표 전부 무채색 숫자).

### 5.4 BE — 비교분석 갱신/비갱신 분리
**파일:** `inpa_be/inpa/analysis/compare.py`
- `_aggregate_side(insurance_list)`가 지금 `monthly_premiums`·`total_premiums`만 합산(`:93-129`). **추가**: 모델의 기존 필드를 합산 —
  `monthly_renewal_premium, monthly_non_renewal_premium, monthly_earned_premium, total_renewal_premium, total_non_renewal_premium, total_earned_premium` (None 안전 합산). **신규 계산 없음.**
- 각 side 응답에 `case_fees_by_insurance`(보험별 `{insurance_name, case_fees[]}`) 추가(§5.1 재사용) — 담보별 표(현재/제안)용.
- verdict/switch_warnings/guide 등 나머지 응답 구조 **무변경**(고객 대면 미전송 규칙 유지).

**인터페이스:** `POST /customers/<id>/compare/` 응답 `current`/`proposed`에 6개 premium 필드 + `case_fees_by_insurance` 추가.

### 5.5 FE — 비교분석 표
**파일:** `inpa_fe/lib/api.ts`(`CompareSide`·`CompareResponse`), `inpa_fe/app/customer/[id]/page.tsx`(SwitchTab)
- **현재 ↔ 제안 요약 표:** 각 측 월/총 갱신·비갱신·적립·합계.
- **증감(절대금액):** 제안 − 현재 (예: `월 갱신 +12,000원`). 부호는 사실만, "유리/불리" 판정 없음.
- **담보별 요금(양측):** current/proposed 각 보험의 `case_fees[]` 표.

### 5.6 FE — 보험별 카드
**파일:** `inpa_be/inpa/insurances/serializers.py`(`CustomerInsuranceManualSerializer`), `inpa_fe/lib/api.ts`(`ManualInsuranceItem`), `inpa_fe/app/customer/[id]/page.tsx`(InsuranceCard)
- `CustomerInsuranceManualSerializer`에 `payment_period_type`·`monthly_renewal_premium`·`monthly_non_renewal_premium`·`monthly_earned_premium` 추가(있으면 값, 수기입력이라 없으면 null).
- 카드에 `월 갱신 / 월 비갱신 (/적립)` 표시 + 순수 한 종류면 배지. 값 없으면 `-`(수기입력).

---

## 6. FE 타입 변경 (정확 라인, `inpa_fe/lib/api.ts`)

- `HeatmapSummary`(`:813-817`): `monthly_renewal_premium?`, `monthly_non_renewal_premium?`, `monthly_earned_premium?`, `total_renewal_premium?`, `total_non_renewal_premium?`, `total_earned_premium?` (모두 `number | null`) 추가.
- 신규 `InsuranceCaseFee` 타입 + `CustomerInsuranceListItem`(heatmap `insurance_list` 항목)에 `case_fees: InsuranceCaseFee[]` 추가.
- `CompareSide`(`:2264-2267`): 위 6필드 추가.
- `CompareResponse`(`:2286-2300`): `current`/`proposed`에 `case_fees_by_insurance` 반영(필요 타입 추가).
- `ManualInsuranceItem`(`:2325-2340`): `payment_period_type?`, `monthly_renewal_premium?`, `monthly_non_renewal_premium?`, `monthly_earned_premium?` 추가.

---

## 7. 에러 처리 / 엣지

- **수기입력 보험**(case_list 없음): 담보별 표에서 "담보 내역 없음", 요약엔 합계만 기여 → §5.3 데이터 안내가 차이를 흡수. 절대 오류로 처리하지 않음.
- **null 보험료**: 표기 `-`. 합산 시 None 무시.
- **혼합 보험**(한 보험에 갱신+비갱신 담보): 담보별 표에 자연히 각 행이 다른 구분으로 나옴. 보험 헤더 배지는 '혼합'.
- **적립(earned)**: 담보 단위엔 없음(보험 단위 값). 요약·카드에만 표시.
- **합계 불변식**: 표시 계층에서 `monthly_premiums >= renewal+non_renewal+earned`가 일반적(초과 시 overage 경고). 강제 재계산 안 함(사실 존중).

---

## 8. 테스트

**BE (`python manage.py test inpa.analysis inpa.insurances`)**
- `_aggregate_side` 갱신/비갱신/적립 합산 정확성 + None 안전(수기입력 섞였을 때).
- 비교 응답에 6필드 + `case_fees_by_insurance` 존재.
- `CaseFeeSerializer` 필드 노출(`is_renewal` 파생 포함).
- 히트맵 `insurance_list[].case_fees[]` 존재 + 수기입력 보험은 빈 배열.
- 회귀: 기존 히트맵/비교 테스트 그린.

**FE**: `npm run build`(타입) + `npm run lint:copy`(em-dash 가드).

---

## 9. 아웃 오브 스코프 (명시)

- 담보별 나이대 세그먼트/막대(coverage-segments), 도넛, foliio radar/충분도.
- 수기입력에 담보 트리 추가(별도 대형 과제).
- 보험료 등급/판정/색.
- 고객 공유뷰(`/s`) 변경.

---

## 10. 파일 요약

**BE**: `insurances/serializers.py`(CaseFeeSerializer 신규 + CustomerInsuranceSerializer/ManualSerializer 확장), `analysis/compare.py`(_aggregate_side + 응답), `analysis/views.py`(prefetch 확인), `insurances/tests.py`·`analysis/tests.py`.
**FE**: `lib/api.ts`(타입), `components/heatmap.tsx`(요약·담보 표), `app/customer/[id]/page.tsx`(AnalysisTab·SwitchTab·InsuranceCard), `app/analysis/page.tsx`.
**마이그레이션**: 없음.
