# 요금표 한도 정합 (PM 확정 (A): 랜딩 4한도 전부) — Spec

> 2026-07-09. PM 지시: 랜딩(new.inpa.kr) 요금표에 적힌 한도가 정확 → billing이 그 숫자를 실제로 강제하게 정합. 4한도 전부(증권 분석·비교 분석·영업 리포트 생성·**신규 고객 추가**). 리포트·고객 한도는 새로 구현.

## 랜딩 → billing 매핑 (확정)
- 증권 자동 분석 → `limit_ocr`('ocr', 증권 OCR 업로드)
- 비교 분석 → `limit_ai_compare`('ai_compare', compare.py)
- **영업 리포트 생성 → `limit_analysis`('analysis', 보장분석 heatmap = 설계사가 영업에 쓰는 리포트)** ← 해석(PM 보고: 별도 리포트 기능 없음, 보장분석이 그 리포트)
- **신규 고객 추가 → 신규 `limit_customer`('customer')** ← 현재 고객 생성에 한도 없음, 신설
- 판촉물(`limit_promotion`) → 랜딩 미표기, 현행 유지(별개 축)

## 랜딩 숫자 (정합 목표)
| 요금제 | 증권(ocr) | 비교(ai_compare) | 리포트(analysis) | 고객(customer) |
|---|---|---|---|---|
| Free | 5 | 1 | 5(랜딩 미표기 → 체험 수준 보수) | 5 |
| Plus | 100 | 50 | 50 | 30 |
| Manager | 100 | 50 | 50 | 30 (Plus 동일) |
| Super | 무제한(None) | None | None | None |

- 현행 대비 변경: free ocr 10→5, ai_compare 5→1, analysis 10→5, promotion 유지. plus/manager ocr 200→100, ai_compare 100→50, analysis 200→50, promotion 유지. super 유지.
- ★ **고객 한도 의미 통일:** 무료 랜딩 '최대 5인'(총량 뉘앙스) vs Plus '월 30인'(월). 기존 UsageMeter가 **월별**이라 전부 월별로 통일(free 5/월, plus 30/월, super 무제한). PM 보고: 무료를 '총 5명 하드캡'으로 원하면 후속 소폭 조정.

## 설계

### 1. BE — Plan 필드 + kind 추가 (billing 마이그레이션, additive)
- `Plan.limit_customer` SmallIntegerField(null=True) — null=무제한. `get_limit`가 'customer' 처리.
- `credit.py::_ALLOWED_KINDS` += 'customer'. (UsageMeter는 action 문자열 범용이라 모델 변경 무.)

### 2. BE — 한도 강제 (고객 생성)
- `customers/views.py::CustomerViewSet.perform_create`(단건) + `bulk_create`(N건): 생성 전 `check_and_consume(request.user, 'customer')`. bulk는 N건이면 잔여 한도 확인 후 N 소모(잔여 < N이면 402, 부분 생성 안 함 or 가능한 만큼? → **전량 402**로 단순·명확). `LimitExceeded` → 402 `{code:'credit_exhausted', kind:'customer', ...}`(기존 패턴).
- ★ `FREE_TIER_UNLIMITED`(베타 바이패스) 존중 = 지금은 dormant(유료 전환 시 작동). 기존 4 kind와 동일.
- 소개/셀프진단 자동 유입 리드 생성(public 경로)도 고객 생성인가? → **인바운드 자동 리드는 한도에서 제외**(설계사 능동 추가만 카운트; 안 그러면 고객이 셀프진단하면 설계사 한도가 깎임 = 불합리). perform_create/bulk_create(설계사 UI 경로)만 소모.

### 3. seed_billing — 한도 정합
- free/plus/manager/super의 limit_ocr/ai_compare/analysis/customer를 위 표대로. **get_or_create defaults는 CREATE 시만** → 기존 프로드 행은 관리자 수정값 보존이 원칙이나, 이번은 '랜딩 정합'이 목적이므로 **기존 행도 이 4개 한도를 명시 보정**(price/display/promotion 등 다른 필드는 불변). limit_customer는 신규 컬럼이라 전 플랜에 세팅.
- Django Admin PlanAdmin에 limit_customer 노출.

### 4. FE — 한도 표시
- `lib/api.ts` PlanLimits/BillingUsage 타입에 `limit_customer` + usage 'customer' 추가.
- 사용량 화면(settings/account 또는 admin usage)에 고객 한도 표시. 업그레이드 모달은 기존 402 kind 처리 재사용(kind='customer'면 '고객 추가 한도' 문구). §6 카피.
- 랜딩 요금표(brand-story-sections.tsx)는 **이미 정확**(PM 확정) → 변경 없음. billing을 랜딩에 맞추는 방향.

### 테스트 (BE)
- 'customer' kind: check_and_consume 정상(베타 바이패스 시 무제한, 게이트 시 한도).
- 고객 생성 한도: FREE_TIER_UNLIMITED=False + free 한도 도달 시 5번째 고객 생성 402. bulk N > 잔여면 402.
- 인바운드 자동 리드(셀프진단/소개)는 한도 미소모 회귀.
- seed_billing: 4 플랜 한도가 표대로 + limit_customer 세팅 + 기존 행 보정.
- get_limit('customer') 정확.

### 마이그레이션 / 컴플라이언스
- 마이그레이션 1(billing: limit_customer). additive.
- 베타 dormant(FREE_TIER_UNLIMITED=True) → 현행 무변경, 유료 전환 시 랜딩대로 강제. 정직성: 랜딩 표기 = 실제 강제(과장 없음).
- 고객 대면 무변경.
