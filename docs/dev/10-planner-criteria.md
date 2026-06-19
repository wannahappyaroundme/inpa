# 설계사 기준 설정 (Planner Baseline)

> **문서 ID**: `dev/10-planner-criteria.md`
> **버전**: v0.1 (초안) · **작성일**: 2026-06-19
> **상태**: 기획 착수 — Sprint0 게이트 항목(G4-2, planner_baseline 모델 미설계)을 해소하기 위한 정본 초안
> **선행 정본**: `dev/09-compliance.md`(컴플라이언스 절대원칙) · `dev/07-api-data-contracts.md`(히트맵 동결분 `heatmap_status`) · `dev/02-data-model-and-api.md`(모델 지도)
> **제품**: 인파(Inpa) — 보험설계사의 업무 OS

---

## 0. 한 줄 요약 (TL;DR)

설계사가 **연령대 × 성별 × 상품군별 권장 보장 밴드(기준선)** 를 직접 설정·저장하고, 그 기준이 **히트맵의 충족(넉넉/적정/부족/없음) 판정에 단일 입력**으로 들어간다.

**왜 이 문서가 컴플라이언스의 심장인가**: 인파는 "이 고객은 보장이 부족하다"를 **자체적으로 판정할 근거를 보유하지 않는다.** 부족/충분이라는 단어가 화면에 뜨려면, 그 판정 기준은 **반드시 라이선스를 가진 설계사 본인이 설정한 값**이어야 한다. `planner_baseline` 테이블이 없으면 히트맵 3색(enough/short)은 **영구히 활성화할 수 없다**(neutral 모드 고정). 이 문서는 그 단일 입력의 데이터 모델·UI 흐름·책임 경계를 못박는다.

---

## 1. 책임 경계 — 누가 무엇을 판정하는가 (절대원칙)

이 문서 전체를 규정하는 단 하나의 원칙(`dev/09 §1` 계승):

> **인파는 보장의 적정성을 판정·권유하지 않는다. 판정 기준의 소유자는 설계사다.**

### 1.1 판정 주체 분리표

| 구분 | 인파(Inpa)가 하는 것 | 설계사가 하는 것 |
|---|---|---|
| 기준선 값 | 저장·연산·표시(계산기) | **설정·결정·책임**(판단자) |
| 충족 판정 | `actual` vs `baseline` 산술 비교만 | 비교 결과의 **해석·고객 권유** |
| 기본 프리셋 | "참고용" 제공(출처 명시) | 채택·수정·폐기 결정 |
| 고객 노출 | '사실'만(`dev/09 §1` 공유뷰) | 부족/충분의 **구두 설명** |

### 1.2 "인파는 판정 근거를 자체 보유하지 않는다"의 기술적 구현

이 원칙은 추상적 선언이 아니라 **코드 레벨 물리 강제**로 박힌다:

```
baseline_source == null  →  heatmap_status() 강제 neutral
                            (enough/short 발화 물리 차단)
─────────────────────────────────────────────────────────
baseline_source == 'planner'  →  graded 모드 허용
                                 (설계사가 값을 넣었을 때만)
```

- **인파 디폴트 상태 = neutral**. 설계사가 `planner_baseline`을 한 번도 설정하지 않으면 히트맵은 `none`(0원=객관적 사실)만 회색으로 표기하고, enough/short는 **물리적으로 발화하지 않는다.**
- 즉 **"부족" 한 글자가 화면에 뜨는 순간, 그 책임의 출처는 100% 설계사의 설정값**이다. 인파가 임의로 만든 기준이 아니다.
- 이 단일 게이트(`baseline_source`)가 **준법 통제점**이다. `dev/09 §5`의 "graded 플립 = BE 단일스위치"가 여기서 **테이블 존재 여부 + source 값**으로 구현된다.

### 1.3 기본 프리셋의 책임 경계 (디스클레이머 의무)

인파는 설계사 편의를 위해 **기본 프리셋(참고용 시드값)** 을 제공할 수 있다. 단, 이는 컴플라이언스 지뢰밭이므로 다음을 **의무 강제**한다:

- (추정) 프리셋 채택 시에도 `baseline_source = 'planner'` 로 기록 — **"인파가 정했다"가 아니라 "설계사가 인파 프리셋을 채택했다"** 로 책임 귀속.
- 프리셋 화면 상시 디스클레이머: **"본 기준은 참고용이며, 출처는 [출처]입니다. 최종 기준은 설계사님이 조정·확정하셔야 합니다."**
- **프리셋 출처 명시 필수**(`dev/09 §2` 준법 가드 ②). 출처 없는 프리셋 제공 금지 → 후술 §4.3에서 출처 미확정(G4-1/Q1) 시 **프리셋 비활성** 유지.

---

## 2. 데이터 모델 — `planner_baseline`

### 2.1 모델 위치 및 멀티테넌시

- **신규 테이블** `planner_baseline` (CTO 산출물 "신규 모델" 목록에 추가 — 기존 NormalizationDict/ConsentLog/NorthStarEvent + 업무OS 3종에 이어).
- **소유 단위 = 설계사 1인**(`owner FK(User)`). 멀티테넌시 row-level 격리(`OwnedQuerySetMixin` + `IsOwner`) 적용 대상. GA 지점 공유 기준은 범위 밖.
- 기준선은 **고객별이 아니라 설계사별 전역 정책**이다. 한 설계사의 모든 고객 히트맵이 이 한 벌의 밴드를 공유한다. (개별 고객 override는 §6 향후과제.)

### 2.2 스키마 정의

```
planner_baseline
─────────────────────────────────────────────────────────────
  id              PK
  owner           FK(User)            -- 설계사 소유, 격리 필터 단일점
  coverage_key    str(indexed)        -- 표준 담보 키(StandardCoverage 4계층의 leaf)
  product_group   smallint            -- 상품군: 1=생명/2=손해/3=실손/4=연금저축 (추정 enum)
  age_band        str                 -- 연령대: '20s'|'30s'|'40s'|'50s'|'60s+' (추정 5밴드)
  gender          smallint(null)      -- 1=남/2=여/null=공통(성별 무관 밴드)
  recommend_min   decimal(null)       -- 권장 하한(이 밑=short/부족)
  recommend_max   decimal(null)       -- 권장 상한(이 위=over/넉넉) (추정, over 표기는 §3.2)
  unit            smallint            -- 1=만원/2=원/3=구좌 등 (담보별 단위 차이 흡수)
  source          str                 -- 'planner'(직접) | 'preset:<id>'(프리셋 채택) | null
  preset_origin   str(null)           -- 프리셋 채택 시 출처 라벨(디스클레이머 표시용)
  is_active       bool                -- soft toggle(밴드 비활성화 시 해당 셀 neutral 복귀)
  created_at / updated_at
─────────────────────────────────────────────────────────────
  UNIQUE(owner, coverage_key, product_group, age_band, gender)
```

### 2.3 키 설계 주석

- **`UNIQUE(owner, coverage_key, product_group, age_band, gender)`**: 한 설계사가 동일 (담보 × 상품군 × 연령대 × 성별) 조합에 밴드를 중복 정의 못 하게 강제. 충족 판정 시 단일 행 결정성 보장.
- **`gender=null` 폴백**: 성별 무관 밴드. 판정 시 (성별 일치 행 우선 → 없으면 null 행) 2단 폴백. 설계사가 성별 구분 없이 한 줄로 설정하는 케이스 수용.
- **`age_band` 문자열 enum**: 정수 나이 대신 밴드 문자열로 저장 → 고객 정확한 나이를 밴드로 매핑하는 책임은 판정 함수(FE 무관, BE 권위).
- **`source` 3값 분기**: `null`(미설정→neutral 강제) / `'planner'`(직접 입력) / `'preset:<id>'`(프리셋 채택, `preset_origin`에 출처 라벨 동반). **§1.2 게이트의 물리 키.**
- **`recommend_max` nullable**: 상한 미설정 가능. 상한 없으면 over(넉넉) 판정 미발화, min 미달만 short 판정. (보수적 디폴트 — §3.2 참조.)

### 2.4 마이그레이션 순서 (BE 산출물 §6 계승)

```
makemigrations
  → migrate (NorthStarEvent 포함 — Day1 동결분)
  → migrate (planner_baseline 추가 — 본 문서)
  → seed_taxonomy (StandardCoverage 100+ — coverage_key의 FK 무결성 선행)
  → loadinitialmemberships
  → [조건부] seed_baseline_preset (§4.3 출처 확정 후에만 실행)
```

> ⚠️ `planner_baseline.coverage_key`는 `seed_taxonomy`의 StandardCoverage leaf를 참조하므로 **반드시 담보 트리 시드 이후** 마이그레이션/시드. 순서 역전 시 고아 키 발생.

---

## 3. 히트맵 충족 판정 반영 — `heatmap_status()` 계약

### 3.1 단일 권위 함수 (BE)

충족 판정은 **BE 단 1곳**(`heatmap_status(actual, baseline, mode)`)에서 결정한다(`dev/07` 히트맵 동결분 + CTO 산출물 §5 계승). FE는 BE가 내린 status 문자열을 **렌더만** 한다. FE 재판정 절대 금지.

```
heatmap_status(actual, baseline, mode):
    # mode = 'neutral' | 'graded'
    if baseline is None or baseline.source is None:
        return 'none' if actual == 0 else 'neutral'   # ← 기준 미설정 강제 중립
    if mode == 'neutral':
        return 'none' if actual == 0 else 'neutral'   # ← 전역 중립 디폴트(베타)
    # mode == 'graded' AND baseline.source in ('planner','preset:*')
    if actual == 0:                  return 'none'      # 없음(회색)
    if actual <  baseline.recommend_min:  return 'short'   # 부족(amber)
    if baseline.recommend_max and actual > baseline.recommend_max:
                                     return 'over'      # 넉넉
    return 'enough'                                      # 적정
```

### 3.2 4색 신호등 ↔ status 매핑

| status | 신호등 색 | 의미 | 발화 조건 | 비고 |
|---|---|---|---|---|
| `none` | 회색 | 없음(0원) | `actual == 0` | **neutral 모드에서 유일 발화** = 객관적 사실 |
| `short` | amber(부족) | 권장 하한 미달 | graded ∧ `actual < min` | **red 아님** — red(#E03131)는 §97 전용 색잠금 |
| `enough` | green | 적정 | graded ∧ min≤actual≤max | — |
| `over` | (추정) 청록/blue | 넉넉(과보장) | graded ∧ `actual > max` | `recommend_max` 설정 시만 |

> **컴플라이언스 절대 가드**: `short`(부족)는 amber로만. **red 절대 부재**(준법 산출물 §2 ④). red는 §97 비교안내서 불리점 전용으로 색 잠금됨(`dev/09`).

### 3.3 baseline 주입 흐름

```
[히트맵 요청]  GET /customer/:id/analysis/  (설계사 내부도구, 인증 필수)
       │
       ▼
  calculate_total_analysis()  ──→  담보별 actual 값(보유 보장금액)
       │
       ▼
  per-cell:  match planner_baseline
             WHERE owner=request.user
               AND coverage_key=cell.key
               AND product_group=cell.product_group
               AND age_band=map(customer.age)        ← 고객 나이→밴드 매핑
               AND (gender=customer.gender OR gender IS NULL)  ← 2단 폴백
               AND is_active=true
       │
       ▼
  heatmap_status(actual, matched_baseline, mode=user.heatmap_mode)
       │
       ▼
  status 문자열 → FE 렌더(3색 또는 neutral)
```

- **고객 나이 → age_band 매핑**: 판정 시점 `customer.birth_day` 기준 만나이 산출 → 밴드 문자열 변환. BE 권위(FE는 나이 미전송).
- **gender 2단 폴백**: 성별 일치 행 우선, 없으면 `gender IS NULL` 공통 행. 둘 다 없으면 해당 셀 baseline=None → neutral.
- **공유뷰(고객 노출)에는 이 경로 자체가 부재**: 공유뷰는 status prop 물리 부재(`dev/09 §1`, 준법 §1). planner_baseline은 **설계사 내부 히트맵에만** 주입된다.

---

## 4. 설정 UI 흐름

### 4.1 진입점 — "기준 설정"의 책임 전가 동선

준법 산출물 §2의 핵심 요구: **"왜 부족이라 단정?" → "설계사님이 설정한 기준입니다"** 로 답하는 동선을 화면에 물리적으로 확보.

```
[히트맵 화면]
   ├─ (neutral 모드) 상단 배너: "충족 판정을 켜려면 [내 기준 설정] →"
   └─ (graded 모드) 셀 hover/tap → "이 판정은 회원님이 설정한 기준 기준입니다 · [기준 수정]"
                                                              │
                                                              ▼
                                              [설정 > 보장 기준(Baseline) 화면]
```

- 진입점은 **2곳**: ① 히트맵 상단(neutral→graded 유도 배너), ② 셀 단위 [기준 수정] 딥링크. 둘 다 동일한 설정 화면으로 수렴.
- 설정 화면은 **설계사 본인만**(`IsOwner`). 고객 공유뷰에는 노출 0.

### 4.2 설정 화면 구조 (모바일 퍼스트 + 데스크톱 반응형)

설계사 도구이므로 데스크톱 반응형까지. 구조:

```
┌─ 보장 기준 설정 ───────────────────────────────┐
│  [상품군 탭]  생명 │ 손해 │ 실손 │ 연금저축       │
│  ────────────────────────────────────────────  │
│  [연령대 ▼ 30대]   [성별 ⦿공통 ○남 ○여]          │
│  ────────────────────────────────────────────  │
│  담보            권장하한    권장상한   상태       │
│  ─────────────  ────────   ────────  ─────      │
│  암진단비         [3,000]만   [5,000]만  ●활성     │
│  뇌혈관진단비     [2,000]만   [    ]만   ●활성     │
│  실손(입원)       [   ]       [   ]      ○비활성    │
│  …                                              │
│  ────────────────────────────────────────────  │
│  ⓘ 본 기준은 참고용 프리셋을 바탕으로 하며,        │
│    최종 기준은 설계사님이 조정·확정하셔야 합니다.   │
│    [프리셋 출처: ____]                            │
│  ────────────────────────────────────────────  │
│  [프리셋 불러오기]            [저장]              │
└──────────────────────────────────────────────┘
```

**상호작용 사양**:
- **상품군 탭 전환** 시 필터 리셋(foliio admin-dashboard sort/filter reset on tab change 패턴 계승).
- **연령대 × 성별 셀렉터**: 선택 조합에 해당하는 밴드 행 집합 표시. 빈 칸 = 미설정(neutral).
- **밴드 입력**: 하한/상한 숫자 입력 + 활성 토글. 상한 빈칸 허용(over 미판정).
- **저장 시** `source='planner'` 기록. 프리셋 불러오기 후 저장 시 `source='preset:<id>'` + `preset_origin` 기록.
- **디스클레이머 상시 노출**(접기 불가) — §1.3 의무.

### 4.3 기본 프리셋 (참고용 — 디스클레이머 의무)

**프리셋 = 콜드스타트 완화 장치.** 설계사가 빈 화면에서 100+ 담보 밴드를 손으로 채우는 마찰을 줄인다. 단 컴플라이언스 의무:

| 항목 | 규칙 |
|---|---|
| 채택 시 source | `'preset:<id>'` (인파가 정한 게 **아니라** 설계사가 채택) |
| 출처 명시 | `preset_origin` 필수 — 디스클레이머에 표시 |
| 수정 가능성 | 채택 후 설계사가 개별 밴드 수정 자유(수정 시 해당 행 `source='planner'` 승격) |
| **출처 미확정 시** | **프리셋 비활성** — Q1/G4-1(기준선 출처·권위) 미확정 동안 프리셋 제공 보류 |

> ⚠️ **블로킹 의존성**: 프리셋의 시드값(`recommend_min/max` 100+ 담보분)과 그 **출처·권위**(금감원/보험연구원/자체+면책 중 무엇)는 **Q1/G4-1 미확정**이다. 출처 없는 프리셋은 "인파가 임의 기준을 정했다"는 컴플라이언스 위반이 되므로, **출처 확정 전까지 프리셋 탭 비활성**하고 설계사 직접 입력(`source='planner'`)만 허용한다. 이것이 neutral 우회와 함께 가는 **이중 안전판**이다.

---

## 5. API 계약 (요약)

| Path | Method | 인증 | 동작 |
|---|---|---|---|
| `/baseline/` | GET | `IsOwner` | 본인 밴드 전체 조회(상품군/연령/성별 필터 쿼리) |
| `/baseline/` | POST | `IsOwner` | 밴드 생성(`source='planner'`) |
| `/baseline/:id/` | PATCH | `IsOwner` | 밴드 수정(프리셋→planner 승격 포함) |
| `/baseline/:id/` | DELETE | `IsOwner` | 밴드 삭제(soft, `is_active=false` 권장) |
| `/baseline/bulk/` | PUT | `IsOwner` | 화면 단위 일괄 저장(상품군×연령×성별 행집합) |
| `/baseline/presets/` | GET | `IsOwner` | (조건부) 프리셋 목록 — 출처 확정 시만 활성 |
| `/baseline/apply_preset/` | POST | `IsOwner` | 프리셋 채택→본인 밴드로 복사(`source='preset:<id>'`) |

- 전 엔드포인트 `OwnedQuerySetMixin` 적용 — `request.user` 없는 접근 0(공유뷰 화이트리스트 대상 아님).
- **`heatmap_mode` 토글**: `user.heatmap_mode`(neutral/graded)는 별도 사용자 설정. graded 전환은 **planner_baseline 1행 이상 존재 + Q1 출처 확정** 동시 충족 시에만 UI 허용(추정).

---

## 6. 책임 경계 재확인 + 향후 과제

### 6.1 이 문서가 잠그는 것 (Sprint0 게이트 해소)

- ✅ **G4-2 해소**: `planner_baseline` 모델 스키마 동결 → 히트맵 graded 활성화의 데이터 근거 확보.
- ✅ **컴플라이언스 단일 입력 확보**: 충족 판정의 유일한 기준 출처 = 설계사 설정값(`source='planner'|'preset:*'`).
- ✅ **neutral 강제 게이트**: `baseline_source=null → 강제 neutral`을 모델·함수 양단에 물리 박음.

### 6.2 이 문서가 잠그지 못하는 것 (상위 블로킹 의존)

| 미결 | 출처 | 영향 | 우회 |
|---|---|---|---|
| **프리셋 시드값 + 출처·권위** | Q1 / G4-1 | graded 프리셋 비활성 | 설계사 직접 입력(`planner`)만 허용 |
| **graded 플립 최종 승인** | `dev/09 §5` 준법 게이트 | 3색 활성 시점 | neutral 디폴트 유지(베타) |
| **chart_based_amount 시드** | BE 산출물 blocking #5 | 히트맵 기준선 거짓위험 | planner_baseline로 출처 이관 |
| **age_band/product_group enum 확정** | (추정) 본 문서 | 매핑 정확도 | 5밴드×4상품군 (추정) 잠정 |

### 6.3 향후 과제 (P1+)

- **개별 고객 override**: 현재 설계사 전역 밴드만. 특정 고객 맞춤 기준은 `customer_baseline_override`(P1.5 (추정)).
- **밴드 버전 이력**: 기준 변경 감사추적(`baseline_history`) — 분쟁 시 "당시 어떤 기준이었나" 복원. (추정) 준법 권고로 P1 검토.
- **프리셋 큐레이션 주체**: 출처 확정 후 누가 프리셋을 유지·갱신하는가(admin self-service vs 외부 권위 인용) 미정.

---

## 7. 미결 항목 (갭) — Sprint0 잠금 회의 상정

| # | 갭 | 유형 | owner | 비고 |
|---|---|---|---|---|
| B-1 | 프리셋 시드값 100+ 담보 `recommend_min/max` + **출처·권위**(Q1/G4-1) | **blocking** | PM+준법+데이터 | 미확정 시 프리셋 탭 비활성, 직접입력만 |
| B-2 | graded 플립 최종 승인(`dev/09 §5` 준법 게이트) | **blocking** | 대표+준법 | Q1 출처+면책문안 없이 플립 금지 |
| B-3 | 프리셋 채택 시 디스클레이머 출처 라벨 정본 문구 | **blocking** | 준법 | "참고용·설계사 조정" + 출처 명시 의무 |
| N-1 | `age_band` 5밴드 경계(20s/30s/.../60s+) + 만나이 매핑 규칙 | non-block | PM | (추정) 잠정 5밴드 |
| N-2 | `product_group` 4값 enum(생명/손해/실손/연금) 확정 | non-block | BE+PM | (추정) 담보 트리와 정합 필요 |
| N-3 | `recommend_max`(상한/과보장) 표기 정책 — over status 노출 여부 | non-block | PM+준법 | 상한 nullable, over 보수적 미발화 가능 |
| N-4 | gender 2단 폴백(성별일치→null공통) UX 노출 방식 | non-block | PM+디자인 | 설계사 입력 편의 vs 정확도 |
| N-5 | 개별 고객 override 필요성(전역 밴드 한계) | future | PM | P1.5 검토 |
| N-6 | 밴드 변경 감사추적(`baseline_history`) | future | 준법 | 분쟁 대비 복원 |

---

> **다음 액션**: 본 초안을 Sprint0 게이트 잠금 회의에 상정 → B-1(프리셋 출처)·B-2(graded 플립)·B-3(디스클레이머 문구)를 준법·대표 승인 안건으로 묶음. 승인 전까지 **neutral 디폴트 + 설계사 직접입력(`source='planner'`)** 만으로 `planner_baseline` 골격 구현 착수 가능(프리셋·graded는 게이트 통과 후 활성).