# 설계사 기준 설정 (Planner Baseline)

> **문서 ID**: `dev/10-planner-criteria.md`
> **버전**: v0.2 · **작성일**: 2026-06-19 · **현재화**: 2026-07-29
> **상태**: 구현 완료, 운영 배포 전. 활성 `planner` 기준만 판정에 사용하는 정책이 코드와 테스트에 반영됨
> **선행 정본**: `dev/09-compliance.md`(컴플라이언스 절대원칙) · `dev/07-api-data-contracts.md`(한눈표 응답 계약) · `dev/02-data-model-and-api.md`(모델 지도)
> **제품**: 인파(Inpa) — 보험설계사의 업무 OS

---

## 0. 한 줄 요약 (TL;DR)

설계사가 **연령대 × 성별 × 상품군별 권장 보장 밴드(기준선)** 를 직접 설정·저장하고, 그 기준이 **한눈표의 넉넉·적정·부족 판정에 단일 입력**으로 들어간다.

**왜 이 문서가 컴플라이언스의 심장인가**: 인파는 "이 고객은 보장이 부족하다"를 **자체적으로 판정할 근거를 보유하지 않는다.** 부족/충분이라는 단어가 화면에 뜨려면, 그 판정 기준은 **반드시 라이선스를 가진 설계사 본인이 활성 상태로 설정한 값**이어야 한다. 운영 웹은 활성 `planner` 기준에만 판정을 사용하고, 코드 기본값은 판정을 닫은 상태로 시작한다. 이 문서는 그 단일 입력의 데이터 모델·UI 흐름·책임 경계를 못박는다.

---

## 1. 책임 경계 — 누가 무엇을 판정하는가 (절대원칙)

이 문서 전체를 규정하는 단 하나의 원칙(`dev/09 §1` 계승):

> **인파는 보장의 적정성을 판정·권유하지 않는다. 판정 기준의 소유자는 설계사다.**

### 1.1 판정 주체 분리표

| 구분 | 인파(Inpa)가 하는 것 | 설계사가 하는 것 |
|---|---|---|
| 기준선 값 | 저장·연산·표시(계산기) | **설정·결정·책임**(판단자) |
| 충족 판정 | `actual` vs `baseline` 산술 비교만 | 비교 결과의 **해석·고객 권유** |
| 과거 참고값 | 저장·표시하되 확인 전 판정 제외 | 확인 후 사용·수정·폐기 결정 |
| 고객 노출 | '사실'만(`dev/09 §1` 공유뷰) | 부족/충분의 **구두 설명** |

### 1.2 "인파는 판정 근거를 자체 보유하지 않는다"의 기술적 구현

이 원칙은 추상적 선언이 아니라 **코드 레벨 물리 강제**로 박힌다:

```
is_active != true 또는 baseline_source != 'planner'
                         →  status='neutral'
                            (판정 문구·색 미표시)
─────────────────────────────────────────────────────────
is_active == true 그리고 baseline_source == 'planner'
                         →  graded 모드 허용
                            (shortage/adequate/over 중 산술 판정)
```

- **인파 디폴트 상태 = neutral**. 설계사가 판정 가능한 기준을 설정하지 않으면 보유 금액만 기본 색으로 표시하고 넉넉·적정·부족은 표시하지 않는다.
- 즉 **"부족" 한 글자가 화면에 뜨는 순간, 그 책임의 출처는 100% 설계사의 설정값**이다. 인파가 임의로 만든 기준이 아니다.
- 이 단일 게이트(`is_active + baseline_source`)가 **준법 통제점**이다. 운영 웹 판정은 활성 `planner` 기준만 사용하며, 코드 기본값은 fail-closed다.

### 1.3 과거 참고값의 책임 경계

현재 인파가 새 참고 금액을 제공하는 기능은 닫혀 있다. 기존 DB에 남은 `preset`·출처 미상 행은 다음 경계를 적용한다.

- 기존 `baseline_source='preset'` 값은 보관하되 판정에서 제외한다.
- 설계사가 금액을 확인해 저장한 행만 `baseline_source='planner'`, `preset_origin=null`, `is_active=true`로 전환한다.
- 향후 공식 참고값을 제공하려면 출처와 유지 책임자를 먼저 확정하고, 화면에 참고용이라는 점과 출처를 명시한 뒤 별도 승인을 거친다.

---

## 2. 데이터 모델 — `planner_baseline`

### 2.1 모델 위치 및 멀티테넌시

- **기존 테이블** `planner_baseline`. 이번 판정 출처 정책은 기존 필드를 사용하므로 추가 마이그레이션이 없다.
- **소유 단위 = 설계사 1인**(`owner FK(User)`). 멀티테넌시 row-level 격리(`OwnedQuerySetMixin` + `IsOwner`) 적용 대상. GA 지점 공유 기준은 범위 밖.
- 기준선은 **고객별이 아니라 설계사별 전역 정책**이다. 한 설계사의 모든 고객 히트맵이 이 한 벌의 밴드를 공유한다. (개별 고객 override는 §6 향후과제.)

### 2.2 스키마 정의

```
planner_baseline
─────────────────────────────────────────────────────────────
  id              PK
  owner           FK(User)            -- 설계사 소유, 격리 필터 단일점
  analysis_detail FK(null)            -- 연결된 표준 담보. null이면 이전 미연결 행
  coverage_key    str(indexed)        -- 표준 담보 이름 폴백·이전 행 식별
  product_group   smallint            -- 0=전체/1=생명/2=손해/3=실손/4=연금저축
  age_band        str                 -- 'all'|'20s'|'30s'|'40s'|'50s'|'60s+'
  gender          smallint(null)      -- 1=남/2=여/null=공통(성별 무관 밴드)
  recommend_min   decimal(null)       -- 기준금액(이 밑=status shortage)
  recommend_max   decimal(null)       -- 넉넉 기준금액(이 위=status over)
  unit            smallint            -- 1=만원/2=원/3=구좌 등 (담보별 단위 차이 흡수)
  baseline_source str                 -- 'planner'(확인·저장) | 'preset'(확인 전 참고값) | null(과거 출처 미상)
  preset_origin   str(null)           -- 과거 참고값 출처 라벨
  is_active       bool                -- 서버 소유. false면 판정 제외
  created_at / updated_at
─────────────────────────────────────────────────────────────
  UNIQUE(owner, analysis_detail, product_group, age_band, gender)
    -- analysis_detail이 연결된 행에만 조건부 적용
```

### 2.3 키 설계 주석

- **연결 행 조건부 UNIQUE**: 한 설계사가 동일 (표준 담보 × 상품군 × 연령대 × 성별) 조합에 기준을 중복 정의하지 못하게 강제한다. `analysis_detail=null`인 이전 행은 카탈로그에서 별도로 정리한다.
- **`gender=null` 폴백**: 성별 무관 밴드. 판정 시 (성별 일치 행 우선 → 없으면 null 행) 2단 폴백. 설계사가 성별 구분 없이 한 줄로 설정하는 케이스 수용.
- **`age_band` 문자열 enum**: 정수 나이 대신 밴드 문자열로 저장 → 고객 정확한 나이를 밴드로 매핑하는 책임은 판정 함수(FE 무관, BE 권위).
- **`baseline_source` 3값 분기**: `null`(과거 출처 미상→neutral 강제) / `'planner'`(설계사가 확인·저장→판정 가능) / `'preset'`(확인 전 참고값→neutral 강제, `preset_origin`에 출처 라벨 동반). **§1.2 게이트의 물리 키.**
- **`recommend_max` nullable**: 상한 미설정 가능. 상한이 없으면 `over`(넉넉)를 판정하지 않고 하한 기준으로 `shortage`/`adequate`만 나눈다.

### 2.4 운영 상태

- 이번 변경은 기존 `baseline_source`, `preset_origin`, `is_active` 필드만 사용하므로 DB 마이그레이션이 없다.
- 표준 담보 트리는 `seed_normalization`이 먼저 보장한다.
- 기존 `preset`·`null`·비활성 행은 일괄 변환하거나 삭제하지 않는다. 설계사가 화면에서 요청한 범위만 저장 시 활성 `planner` 기준으로 전환한다.

---

## 3. 한눈표 판정 계약

### 3.1 백엔드 단일 권위

`inpa/analysis/views.py::CustomerHeatmapView`가 보유 금액 집계와 상태 판정을 수행한다. 출처·활성 여부의 공통 규칙은 `inpa/analysis/baselines.py::is_grading_eligible_baseline`과 `select_baseline`에 있다. FE는 응답의 `mode`와 `status`를 표시할 뿐 금액을 다시 판정하지 않는다.

1. 소유자의 활성 기준 중 `baseline_source='planner'`인 행만 후보로 남긴다.
2. 운영 `HEATMAP_GRADING_ENABLED=True`이고 판정 가능한 기준이 하나 이상일 때만 응답 `mode='graded'`.
3. 담보마다 연결된 `analysis_detail`을 우선 사용하고, 과거 미연결 행은 동일 `coverage_key`만 폴백한다.
4. 상품군 정확 일치 → 전체 상품, 연령대 정확 일치 → 전연령, 성별 정확 일치 → 공통 순으로 선택한다. 같은 우선순위 후보가 여러 개면 해당 담보는 `neutral`.
5. 단위가 구좌이거나 하한·상한이 비정상인 행은 판정에 쓰지 않는다.

### 3.2 응답 상태와 색

| `status` | 화면 문구 | 색 | 조건 |
|---|---|---|---|
| `shortage` | 부족 | 빨강 | 하한이 있고 보유 금액이 하한보다 작음 |
| `adequate` | 적정 | 노랑 | 하한 이상이며, 설정된 상한을 넘지 않음 |
| `over` | 넉넉 | 초록 | 상한이 0보다 크고 보유 금액이 상한을 넘음 |
| `neutral` | 상태 문구 없음 | 기본 회색 | 판정 모드가 닫혔거나 해당 담보에 맞는 기준이 없음 |

한눈표 응답은 기존 `baseline_count`와 함께 `applied_baseline_count`, `unapplied_baseline_count`, `grading_enabled`를 제공한다. `baseline_count`는 출처가 있는 활성 행 수이며, 실제 판정 적용 수는 `applied_baseline_count`가 권위다.

### 3.3 고객 공유 범위

설계사 내부 한눈표와 여러 증권 비교만 이 기준을 사용한다. 고객 공개 화면에 설계사 기준 설정 UI를 노출하지 않는다.

---

## 4. 설정 UI 흐름

### 4.1 진입과 기본 화면

- 한눈표 상단에서 `/settings/baseline`으로 이동한다. 판정 중이면 적용 개수를, 판정 전이면 기준을 확인·저장하는 다음 행동을 안내한다.
- 설정 화면은 표준 담보 전체를 카테고리·하위 분류별로 보여준다.
- 각 담보 행에서 전체 상품·전연령·성별 공통의 `기준금액`을 바로 입력한다.
- 검색과 `입력한 담보만` 필터를 제공한다.
- 빈 값은 저장하지 않으며, 바뀐 항목 수와 `변경 내용 저장` 버튼을 하단에 고정한다.

### 4.2 담보 상세 설정

- 담보 행의 `조건별 설정`을 열면 오른쪽 drawer에서 전체 기본값과 상품·연령·성별 상세값을 편집한다.
- `기준금액`은 적정의 시작 금액, `넉넉 기준금액`은 선택 입력이다.
- 필요할 때만 상세 범위를 추가하고, 상세값을 지우면 다음 배치 저장에서 해당 범위를 삭제한다.
- `baseline_source='preset'`, 출처 없는 과거 값, 비활성 `planner` 값은 각각 `내 기준으로 사용` 또는 `내 기준으로 다시 사용`을 눌러야 변경 대상으로 잡힌다.
- 저장 요청에는 출처와 활성 상태를 보내지 않는다. 서버가 요청된 범위만 `baseline_source='planner'`, `preset_origin=null`, `is_active=true`로 확정한다.

### 4.3 이전 미연결 기준

- `analysis_detail`이 없는 이전 행은 화면 위쪽 `기존 직접 입력` 영역에 표시한다.
- 설계사가 표준 담보를 선택해 연결하거나 필요 없는 행을 삭제한다.
- 연결은 이름과 `analysis_detail`만 바꾸며 출처와 활성 상태를 유지한다.
- 연결 후에도 참고값·출처 미상·비활성 값은 명시적 사용 동작과 배치 저장 전까지 판정에 들어가지 않는다.

### 4.4 참고값 제공 상태

`POST /api/v1/planner-baselines/apply-preset/`은 현재 `PRESET_DISABLED` 400을 반환한다. 인파가 제공하는 참고 금액을 화면에서 새로 불러오는 버튼은 없다. DB에 남아 있는 과거 `preset` 값은 삭제하지 않고, 설계사가 확인·저장한 범위만 `planner`로 전환한다.

---

## 5. API 계약 (현재 구현)

| Path | Method | 인증 | 동작 |
|---|---|---|---|
| `/api/v1/baseline-catalog/` | GET | 로그인·이메일 인증 | 표준 담보 전체, 소유자 기준, 이전 미연결 기준, revision 조회 |
| `/api/v1/planner-baselines/` | GET | 소유자 전용 | 본인 기준 목록 조회 |
| `/api/v1/planner-baselines/` | POST | 소유자 전용 | 직접 기준 1행 생성. 출처·활성 상태는 서버 결정 |
| `/api/v1/planner-baselines/{id}/` | PATCH | 소유자 전용 | 금액·범위 수정. `baseline_source`, `preset_origin`, `is_active`는 읽기 전용 |
| `/api/v1/planner-baselines/{id}/` | DELETE | 소유자 전용 | 해당 행 삭제, revision 증가 |
| `/api/v1/planner-baselines/{id}/link/` | POST | 소유자 전용 | 이전 행을 표준 담보에 연결. 출처·활성 상태 보존 |
| `/api/v1/planner-baselines/batch/` | POST | 소유자 전용 | revision 기반 일괄 저장. 요청 범위만 활성 `planner`로 확정 |
| `/api/v1/planner-baselines/apply-preset/` | POST | 소유자 전용 | 현재 `PRESET_DISABLED` 400 |

- 모든 기준 CRUD는 `OwnedQuerySetMixin`과 `IsOwner`로 소유자를 격리한다.
- 일반 생성·수정 API에서도 `baseline_source`, `preset_origin`, `is_active`는 서버 소유다. 명시적 재사용은 설정 화면의 배치 저장 경로로만 활성화한다.
- 배치 revision이 최신 값과 다르면 `baseline_revision_conflict` 409를 반환하고 화면은 최신 내용 다시 불러오기를 제공한다.
- 운영 판정 스위치가 닫혔거나 고객 담보와 맞는 활성 `planner` 기준이 없으면 한눈표와 비교 모두 `neutral`이다.

---

## 6. 책임 경계 재확인 + 향후 과제

### 6.1 이 문서가 잠그는 것

- ✅ **G4-2 해소**: `planner_baseline` 모델 스키마 동결 → 히트맵 graded 활성화의 데이터 근거 확보.
- ✅ **컴플라이언스 단일 입력 확보**: 충족 판정의 유일한 기준 출처 = 설계사가 활성화한 `baseline_source='planner'` 값.
- ✅ **neutral 강제 게이트**: 비활성 행과 `planner`가 아닌 출처를 모델·함수 양단에서 neutral로 처리.

### 6.2 현재 운영 경계와 이후 결정

| 항목 | 현재 결정 | 이후 조건 |
|---|---|---|
| **기존 프리셋 시드값** | 확인 전 판정 제외 | 공식 출처·유지 주체가 확정되면 별도 승인 |
| **3색 판정** | 운영 웹에서 활성 `planner` 기준만 사용 | 이상 시 환경 설정을 닫고 재배포 |
| **코드 기본값** | `HEATMAP_GRADING_ENABLED=False` | 새 환경은 항상 neutral로 시작 |
| **나이대·상품군** | 현행 5밴드×4상품군 유지 | 실제 운영 피드백을 근거로 별도 변경 |

### 6.3 향후 과제 (P1+)

- **개별 고객 override**: 현재 설계사 전역 밴드만. 특정 고객 맞춤 기준은 `customer_baseline_override`(P1.5 (추정)).
- **밴드 버전 이력**: 기준 변경 감사추적(`baseline_history`) — 분쟁 시 "당시 어떤 기준이었나" 복원. (추정) 준법 권고로 P1 검토.
- **프리셋 큐레이션 주체**: 출처 확정 후 누가 프리셋을 유지·갱신하는가(admin self-service vs 외부 권위 인용) 미정.

---

## 7. 이후 검토 항목

| # | 갭 | 유형 | owner | 비고 |
|---|---|---|---|---|
| B-1 | 공식 프리셋 시드값 100+ 담보 `recommend_min/max` + **출처·권위** | later | PM+준법+데이터 | 확정 전까지 기존 참고값은 판정 제외 |
| B-2 | 공식 프리셋 유지·갱신 책임자 | later | PM+운영 | 관리자 편집과 변경 이력 포함 |
| B-3 | 공식 프리셋 제공 시 출처 라벨 정본 문구 | later | 준법 | "참고용·설계사 확인" + 출처 명시 |
| N-5 | 개별 고객 override 필요성(전역 밴드 한계) | future | PM | P1.5 검토 |
| N-6 | 밴드 변경 감사추적(`baseline_history`) | future | 준법 | 분쟁 대비 복원 |

---

> **다음 액션**: 전체 회귀검증과 운영 배포를 마친 뒤, 비식별 테스트 계정에서 `preset/null → 확인·저장 → planner 판정` 흐름을 점검한다. 이상 시 `HEATMAP_GRADING_ENABLED=False`로 되돌리고 재배포한다.
