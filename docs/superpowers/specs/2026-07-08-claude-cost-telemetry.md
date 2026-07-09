# Claude 호출당 비용·파싱 결과 계측 (프리런치 리뷰 #17) — Spec

> 2026-07-08. Phase 2 로드맵 ④(PM 지시 병행). Panel scope (#17): "One structured, PII-scrubbed record per Claude call at the single call gate: token cost in won, feature, user, parse outcome, per-carrier unmatched-coverage rate surfaced in admin console. Replaces the raw stdout JSON print as failure data." partially built. 가격·verify-flag 결정·골든셋 코퍼스의 선행 데이터.

## 핵심 사실 (탐사)
- 호출 지점: 공유 `claude_parser.claude_parse`(callers: `insurances/views.py` ocr_parse, `self_diagnosis.py` /d) + 독립 SDK 2곳 `verify.verify_extraction`(insurances/views ocr_verify) + `compare._generate_guide_draft`(compare_guide). 모델=env `CLAUDE_MODEL_PARSE`(`CLAUDE_MODEL_BULK`는 dead).
- SDK 응답 `message.usage`(input/output/cache_read/cache_creation tokens) — claude_parser·compare는 **성공 경로만** stash, 실패·verify·self_diagnosis는 **누락**.
- 기존 `billing.ClaudeApiLog`(models.py:185) = per-call 로그(action/model/4토큰/created_at, **owner FK 없음·비용 없음·결과 없음**). `credit.py:130 log_claude_usage(action, model, usage)`가 씀(예외 격리). **버그: ocr_verify는 `log_claude_usage('ocr_verify', model, None)`로 항상 0토큰 기록**(실제 청구 호출인데). self_diagnosis는 아예 미기록.
- matched/unmatched 카운트 + carrier code는 `claude_parser.py:635-640`에서 이미 계산되나 `logger.info`로만 흘리고 **미영속**. `_persist_ocr`가 UnmatchedLog 적재(company=코드).
- 원화 단가·환율 **코드에 없음**(문서 docs/05·06에만: Opus 4.8 $5/$25 per MTok, Haiku 4.5 $1/$5). `RuntimeConfig` 싱글턴(billing/models.py:288, `free_tier_unlimited`) = '재배포 없이 토글' 선례.
- Admin 계측 3면 있으나 전부 비용/결과 미노출: `AdminUsageView`(NorthStarEvent funnel), `AdminBillingUsageView`(UsageMeter 쿼터). 차트 `components/charts.tsx`(CSS var 기반, 다크 안전).
- PII 레드라인(claude_parser.py:29): 로그에 증권 원문·응답 본문·상품/고객명 절대 금지. 허용 = 회사코드(int)·건수·길이·예외타입·토큰수. 회귀테스트 `ClaudeParserLogRedactionTests`.

## 설계

### 1. `ClaudeApiLog` 확장 (billing 마이그레이션 0007, additive)
추가 필드(전부 PII-safe):
- `user` FK(User, SET_NULL, null=True) — 귀속(이름 아님, id/FK만). 공개 /d는 null 허용.
- `cost_krw` DecimalField(max_digits=10, decimal_places=2, default=0) — **추정 비용**(토큰×단가×환율). 원천 진실은 토큰수, cost는 파생 추정.
- `parse_outcome` CharField(choices: `success`/`empty`/`json_invalid`/`api_error`/`timeout`/`no_key`/`package_missing`, default `success`, db_index).
- `carrier_code` SmallIntegerField(null=True) — 회사 코드(손해 raw / 생명 200+, UnmatchedLog 규약).
- `matched_count` SmallIntegerField(default=0) · `unmatched_count` SmallIntegerField(default=0).
- Meta: index (created_at), (action), (parse_outcome). (owner FK 있어도 이 로그는 운영/비용용 — 소유 스코프 아님, IsAdmin만 조회.)

### 2. 단가/환율 `billing/pricing.py`
- `MODEL_PRICING` dict: 모델 id 계열(substring 'opus'/'sonnet'/'haiku') → `{in_usd_per_mtok, out_usd_per_mtok, cache_read_mult=0.1, cache_write_mult=1.25}`. 문서 단가(Opus $5/$25, Haiku $1/$5, Sonnet $3/$15) 반영. 미상 모델 → opus 보수 fallback.
- 환율: `settings.CLAUDE_USD_KRW_RATE = env.float(default=1400.0)`(env 오버라이드). **추정치**(정밀 청구 아님).
- `estimate_cost_krw(model, usage) -> Decimal`: `(in/1e6*in_usd + out/1e6*out_usd + cache_read/1e6*in_usd*0.1 + cache_write/1e6*in_usd*1.25) * usd_krw`. usage None → 0.

### 3. `log_claude_usage` 확장 (credit.py)
- 시그니처: `log_claude_usage(action, model, usage, *, user=None, outcome='success', carrier_code=None, matched=None, unmatched=None)`. 하위호환(기존 3-인자 호출 유지). cost_krw = estimate_cost_krw. 예외 격리 유지(로깅으로, print 제거).
- **모든 경로 기록**(실패 포함): 
  - claude_parser callers: ocr_parse 성공·실패 양쪽 + carrier/matched/unmatched/outcome 전달. self_diagnosis도 호출(user=null, /d 공개).
  - **verify.py: 실제 usage 전달**(현 None 버그 수정) — `verify_extraction`이 usage 반환하도록 + 호출부가 log.
  - compare.py: 성공·실패(no_key/package/exception) 경로 전부 log(outcome 구분).
- claude_parse가 실패 경로에서도 usage/outcome/carrier/counts를 반환(또는 stash)하도록 최소 확장 → 호출부가 단일 지점에서 log. (자세한 배선은 각 모듈에서 이미 계산된 값 재사용.)

### 4. 어드민 API + FE (IsAdmin, 다크)
- `GET /api/v1/admin/claude-cost/?days=30` → 집계:
  - 총 호출수·총 추정비용(원)·outcome별 분포(성공률)·action(기능)별 비용/호출수·일별 비용 추이·**회사별 미매칭율**(carrier_code GROUP BY: sum(unmatched)/(sum(matched)+sum(unmatched))).
  - 데모(@inpa.local) 제외(AdminUsageView 관례).
- FE `app/admin/claude-cost/page.tsx`(다크): StatCard 행(총비용·호출·성공률) + 일별 비용 BarChart(charts.tsx 재사용) + 기능별 표 + outcome 도넛 + 회사별 미매칭율 표. **비용은 '추정' 명시**(환율·단가 추정치, §6 정직성). 판정어 금지(사실 수치만). admin/layout nav에 항목 추가.
- `lib/adminApi.ts`: `adminGetClaudeCost(days)` + 타입.

### 5. 잔여 print → logging 스윕 (레드라인 정합)
- compare.py:185/191/245, credit.py:166, analytics/events.py:85 → 내용 없는 logging(예외 타입만). PII 미유출이나 print 금지 레드라인 정합.

### 테스트 (BE)
- ClaudeApiLog 행 생성: mock SDK(`AnthropicClientMockTests` 패턴)로 성공 시 토큰·cost·outcome·carrier·matched/unmatched 정확 기록.
- **실패 경로 기록**: json_invalid/api_error/timeout 각각 outcome 스탬프 + (usage 있으면) 토큰 기록.
- verify.py 실제 usage 기록(0 아님) 회귀.
- self_diagnosis 호출이 ClaudeApiLog 남김(user null).
- cost 추정: estimate_cost_krw 단위 계산(opus/haiku 단가, 환율 override).
- PII: 로그 행에 raw name/응답 본문 없음(ClaudeParserLogRedactionTests 확장).
- 어드민 API: IsAdmin 격리(설계사 403), 집계 shape, 회사별 미매칭율 계산, 데모 제외.

### 마이그레이션 / 컴플라이언스
- 마이그레이션 1(billing 0007, additive). 고객 대면 무관.
- **cost_krw = 추정**(honesty): 토큰수가 진실, 비용은 파생 추정 — FE·필드 주석에 명시. 판정어 없음.
- PII-safe 필드만(회사코드 int·건수·토큰·outcome enum). raw name·응답 본문 절대 미저장.
- 어드민 전용(IsAdmin), 다크 허용.
