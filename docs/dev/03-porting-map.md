# dev/03 — foliio → 인파(Inpa) 포팅 지도

> **이 문서의 역할.** 인파(Inpa)는 새로 짓는 제품이 아니라 **이미 검증된 foliio 코드 위에 영업 OS 레이어를 얹는 작업**이다.
> 본 문서는 "foliio의 어느 파일을 → 인파에서 무엇으로 → 어느 등급(그대로/개조/신규)으로 바꾸는가"를 **파일·함수·라인 단위로 확정한 지도**다.
> 핵심 두 개를 정밀하게 못 박는다: ① 파일별 포팅 등급표(claude_parser · utils · calculate · models · views · credit), ② **보험사별 담보명 정규화 사전을 `_add_coverage` 매칭 4단계의 정확히 어느 틈에 끼우는가.**
>
> 인용된 모든 라인 번호는 foliio 실코드(`~/Desktop/foliio/Foliio_be/weapon/`)를 직접 정독해 확인했으며, 본 문서 집필 시점 코드와 **100% 일치**한다. (검증 명령은 §9 참조.)

---

## 0. 한눈 요약 — 왜 "포팅"이지 "신규 개발"이 아닌가

```
                  foliio 자산 (검증 완료)              인파 추가분
                  ─────────────────────              ──────────
  PDF 추출    ───  utils.py  extract_text_from_pdf  ──  ♻ 그대로
  OCR 파싱    ───  claude_parser.py  claude_parse   ──  ◑ 프롬프트만 손봄
  담보 매칭    ───  _add_coverage 4단계             ──  ◑ 한 줄 사이에 사전 삽입  ◀ 해자
  보험료 계산  ───  calculate.py  8케이스           ──  ♻ 그대로 (골든테스트 회귀)
  크레딧      ───  credit.py  _check_and_consume    ──  ◑ kind='ai' 추가
  공유링크    ───  Customer.share_token            ──  ♻ + ?ref= 계측만
  동의       ───  customer-agree                   ──  ◑ 국외이전 분리 + 로그  ◀ 법무 게이트
  cron       ───  expire/notify/reset/dormancy 패턴 ──  ♻ + 워치독 1개 신규
  ─────────────────────────────────────────────────────────────────
  신규로 새로 짜는 것:  ai_guardrail / normalization / heatmap / NormalizationDict
                       (= 해자 3종의 물리적 구현체 + §97 방패)
```

- **신규 의존성 0개.** `anthropic · pdfplumber · PyMuPDF · numpy-financial · DRF · Pillow` 전부 foliio가 이미 보유. `requirements.txt`는 foliio와 동일하게 시작.
- **DB는 MariaDB 유지.** 정규화 사전은 관계형(`NormalizationDict`)으로 충분 — PostgreSQL/JSONB 전환은 포팅비용만 늘리는 비최적화 결정으로 보류.
- **별도 repo** `~/Desktop/inpa`. foliio를 참조 소스로 두고 파일을 가져오며, foliio repo 자체는 건드리지 않는다.

> 등급 기호: **♻ 그대로(복사+무변경)** / **◑ 개조(가져와서 한 군데 손봄)** / **✦ 신규(새 파일)**.

---

## 1. 파일별 포팅 등급표 (마스터)

브리프가 요구한 5개 축 — `claude_parser · utils · calculate · models · views` + 부속(`credit`) — 을 등급과 함께 한 표로 못 박는다.

| # | foliio 원본 (파일:라인) | 핵심 심볼 | 등급 | 인파에서의 처리 | 손대는 이유 |
|---|---|---|---|---|---|
| 1 | `core/utils.py:358` | `extract_text_from_pdf(pdf_path, password=None)` | ♻ | 무변경 복사. pdfplumber 1순위 → PyMuPDF 폴백, 암호화 PDF `doc.authenticate(password)` (`:340`/`:455`) 경로 그대로 | PDF→텍스트는 보험사 무관 순수 추출. 영업 로직과 독립 |
| 2 | `core/ocr/claude_parser.py:430` | `claude_parse(text_lines, is_proposal=False)` | ◑ | 함수 시그니처·흐름 유지. `_SYSTEM_PROMPT`(`:143`)에 **100+ 담보 트리** 주입, 모델 라우팅 Opus/Haiku 분기 추가 | 추출 정확도를 100+ 담보로 끌어올림. 한화 fast-path→claude→regex fallback 경로는 **보존** |
| 3 | `core/ocr/claude_parser.py:700` | `_add_coverage(ocr, cov, ...)` | ◑ | **4단계 매칭 → 5단계.** 3순위(detail 키워드)와 4순위(fuzzy) 사이에 **정규화 사전 단계 삽입** (→ §2) | 보험사별 이름차이를 표준 담보로 흡수 = **데이터 복리 해자** |
| 4 | `customers/calculate.py:245` | `calculate_total_analysis(...)` | ♻ | 무변경. `case_list[].non_renewal_old_list[10]` / `renewal_old_list[10]` / `chart_list[].chart_based_amount` 출력 구조 그대로 | 8케이스 보험료 계산은 인파의 **분석 엔진 심장**. 검증된 자산 — 손대면 회귀 위험만 |
| 5 | `customers/calculate.py:18` | `calculate_analysis(...)` (단건) | ♻ | 무변경. heatmap이 이 출력을 입력으로 소비 | 위와 동일 |
| 6 | `insurances/models.py` | `CustomerInsurance` / `CustomerInsuranceDetail.calculate()` | ♻ | 무변경. `portfolio_type`(0템플릿/1기존/2제안)·`insurance_type`(1생명/2손해)·`monthly_*_premium` 필드 그대로. `numpy_financial.fv` 갱신 미래가치 보존 | 8케이스의 데이터 구조 정의부. compare/heatmap이 전부 이 위에 선다 |
| 7 | `customers/models.py:76` | `Customer` | ♻+1필드 | `birth_day/gender/job_code(JobRiskCode)/mobile/medical_histories/share_token` 전부 재활용. **신규 필드 단 1개: `consent_overseas_at`**(null=미동의 게이트) | 영업에 필요한 고객 속성은 foliio가 이미 다 보유. 추가는 법무 게이트 1필드뿐 |
| 8 | `membership/credit.py:123` | `_check_and_consume(user, kind)` | ◑ | `kind` enum `('customer','insurance','promotion')` 에 **`'ai'` 추가**. AI 호출(메시지/비교안내서)당 차감. 402 shape·`FREE_TIER_UNLIMITED` 베타우회 그대로 | 분기 1개 추가로 AI 과금 게이트 완성. 구조 재발명 불필요 |
| 9 | `customers/views.py` `detect`/`analysis`/`compare` | ViewSet 액션 | ♻+◑ | `analysis`는 ♻. `detect`는 ◑(정규화 결합 + **국외이전 동의 412 게이트**). `compare`는 ◑(§97 비교안내 필드 보강) | 라우팅·권한·share_token 공개뷰 패턴 재활용, 액션 본문만 보강 |
| 10 | `community/content_filter.py` | PII/욕설 정규식 | ◑→✦ | **패턴 재사용 철학**만 가져와 `core/ai_guardrail.py`로 재작성(보험업법 §97/광고심의 룰셋) | "정규식 후처리로 위험 표현 플래그"라는 **기법**은 같지만 룰셋이 완전히 다름 |
| 11 | `accounts/.../commands/*.py` cron | `expirememberships`/`notifymembership`/`resetmonthlycredit`/`process_dormancy` | ♻+✦ | cron **패턴**(idempotent + 자기치유 `_ensure_period_synced`)을 그대로 본떠 **워치독(M4 후속)** 신규 command 작성 | 만기·갱신 스캔 cron의 골격은 검증됨. 룰만 갈아끼움 |

### 신규 파일 목록 (✦ — 해자의 물리적 구현체)

| 신규 파일 | 책임 | foliio에서 빌려온 패턴 |
|---|---|---|
| `core/ai_guardrail.py` | 생성물 보험업법 룰셋 판정 (단정표현·수익보장·비교과장 플래그) | `content_filter.py` 정규식 후처리 |
| `insurances/normalization.py` | `NormalizationDict` 조회·매칭 엔진 (raw_name → 표준 담보) | `_add_coverage`의 매칭 헬퍼 스타일 |
| `customers/heatmap.py` | 담보별 3색(enough/short/none) 충족률 판정 | `calculate_total_analysis` 출력 소비 |
| `ai/message_prompts.py` | 목적 enum(니즈환기/만기/생일/공백/소개/리마인드) → 프롬프트 매핑 | `_SYSTEM_PROMPT` 상수 패턴 |
| `management/commands/watchdog.py` | 만기 D-30·동의 미수신·미열람 링크 스캔 → 액션큐 적재 | cron command 패턴 |
| `management/commands/seed_taxonomy.py` | 100+ 담보 트리 + 정규화 사전 ~200행 seed | `loadinitialmemberships`/`seed_templates` 패턴 |
| `accounts/models.py` `ConsentLog`(신규 모델) | 국외이전 동의 감사추적 (누가·언제·범위·doc_version·ip) | — (법무 신규) |
| `insurances/models.py` `NormalizationDict`(신규 모델) | 보험사별 담보명 사전 (데이터 복리) | — (해자 신규, §2.3) |

---

## 2. 핵심 1 — 보험사별 담보명 정규화 사전을 `_add_coverage`에 끼우는 법

이 한 군데가 인파의 **데이터 복리 해자**가 코드로 박히는 지점이다. 정밀하게 못 박는다.

### 2.1 문제 — 같은 담보, 보험사마다 다른 이름

같은 "일반암 진단비"인데 보험사마다 표기가 다르다. 범용 AI(ChatGPT)는 이 사전이 없어 못 따라온다. 우리는 **쓸수록 두꺼워지는 사전**을 쌓는다.

| 표준 담보 (우리 틀의 leaf) | 삼성생명 | 교보 | 한화 | 현대해상 | … |
|---|---|---|---|---|---|
| 진단비 › 암 › 일반암 | 암진단**급부금** | 암진단**보험금** | 암진단비(일반) | 일반암진단담보 | (추정) |
| 진단비 › 뇌 › 뇌졸중 | 뇌졸중진단급부금 | 뇌졸중진단보험금 | 뇌졸중진단비 | … | (추정) |

> 위 매핑 예시 중 보험사별 실제 표기는 청약서·약관 대조 필요분 일부가 **(추정)** — Phase0 seed 단계에서 상위 30담보 × 5사 실증 확정.

### 2.2 현재 foliio `_add_coverage` 매칭 4단계 (실코드 `claude_parser.py:700~726`)

```
def _add_coverage(ocr, cov, default_payment, default_warranty):
    key = (category, subcategory, detail_name)
    mapped = _CATEGORY_MAP.get(key)                 # 1순위: 정확 매칭 (:712-714)
    if not mapped and original_name:
        mapped = _match_by_keywords(original_name)   # 2순위: 원본명 키워드 (:716-718)
    if not mapped and detail_name:
        mapped = _match_by_keywords(detail_name)     # 3순위: detail명 키워드 (:720-722)
    if not mapped:
        mapped = _fuzzy_match_category(...)          # 4순위: fuzzy 최후수단 (:724-726)
    if not mapped:
        return                                       # 미매칭 → case 생성 안 함 (:728-729)
```

`mapped`는 `(cat, sub, det)` 3-튜플 = 우리 표준 담보 트리의 경로. 못 찾으면 그 담보는 **버려진다**(case 미생성). 바로 이 "버려지는 raw_name"이 사전이 잡아야 할 먹잇감이다.

### 2.3 삽입 지점 — 3순위(detail 키워드) 뒤, 4순위(fuzzy) 앞 ◀ 정확히 여기

**왜 이 틈인가:**
- 1~3순위(정확·키워드)는 **고신뢰 결정론적 매칭** → 우리 사전보다 우선해야 함(사전 오염 방지).
- 4순위 fuzzy는 **저신뢰 추측** → §97 비교안내서가 이걸 믿고 "기존이 부족"이라 단정하면 **부당권유 리스크**. 사전(보험사 확정 매핑)이 fuzzy보다 **반드시 먼저** 와야 함.
- 따라서 정규화 사전은 **"키워드보다 약하지만 fuzzy보다 강한"** 3.5순위.

```
    mapped = _match_by_keywords(detail_name)         # 3순위 (:720-722)  ← 기존 유지

    # ── [신규] 3.5순위: 보험사별 정규화 사전 ──────────────────────
    if not mapped:
        mapped = normalization.lookup(
            company=ocr.company,          # OCR이 식별한 보험사
            raw_name=original_name,       # 보험사 원문 담보명
        )                                 # hit → hit_count += 1 (복리)
        # miss → UnmatchedLog 적재 (admin 1탭 매핑 대기)
    # ────────────────────────────────────────────────────────────

    if not mapped:
        mapped = _fuzzy_match_category(...)           # 4순위 (:724-726)  ← 기존 유지
```

> 구현은 `insurances/normalization.py`(✦)의 `lookup(company, raw_name) -> (cat, sub, det) | None`. `_add_coverage`에는 **import 1줄 + 위 4줄**만 추가한다. 나머지 `_add_coverage` 본문(진단비 처치성 가드 `:738-740`, 최대값 유지 dedup `:774-797`)은 **전부 그대로**.

### 2.4 데이터 복리 루프 — 사전이 두꺼워지는 메커니즘

```
  ┌────────────────────────────────────────────────────────────────┐
  │ ① OCR이 raw_name 만남                                            │
  │      hit  → NormalizationDict 매칭 + hit_count++  (자동, 즉시)    │
  │      miss → UnmatchedLog(company, raw_name, customer) 적재        │
  │                              │                                   │
  │ ② admin 1탭 매핑 (운영 화면) │  raw_name → 표준 담보 leaf 선택    │
  │                              ▼                                   │
  │ ③ NormalizationDict 영구 추가 (source='admin_verified')          │
  │                              │                                   │
  │ ④ 다음 고객부터 같은 raw_name 자동 매칭 (운영비 0)               │
  └──────────────────────────────┬─────────────────────────────────┘
       hit_count 누적 → 빈도순 우선순위 + 자동승격 후보
```

`NormalizationDict` 모델(✦, `insurances/models.py`에 추가):

```
NormalizationDict
  std_detail   FK → AnalysisDetail   # 표준 담보 (우리 틀의 leaf)
  company      SmallInt              # 삼성생명/교보/한화/현대해상/…
  raw_name     CharField(db_index)   # "암진단급부금"
  source       CharField             # seed / ocr_learned / admin_verified
  confidence   SmallInt              # 자동학습 신뢰도
  verified_by  FK User (null)        # admin 검수자
  hit_count    Int                   # 매칭될수록 ++  ← 복리 카운터
  UNIQUE(company, raw_name)          # 같은 보험사·같은 원문은 1행
```

### 2.5 ⚠ 자동승격 임계 — 운영 미결(openQuestion)

`hit_count ≥ 5` 같은 빈도로 admin 검수 없이 자동매핑을 허용할지는 **미결**.
- 허용 시 운영비↓ 그러나 **자동매핑이 틀리면 비교안내서가 거짓 → §97 위반**.
- 결정 전까지 **기본값 = 수동 검수 only**(`source='admin_verified'`만 매칭에 사용, `ocr_learned`는 후보로만). 운영 주체·검수 UI는 별도 운영 문서에서 확정.

---

## 3. 핵심 2 — claude_parse 프롬프트 개조 (◑)

`claude_parser.py:466`에서 `system_prompt = _SYSTEM_PROMPT + (...)` 조립. **개조 2가지:**

- [ ] `_SYSTEM_PROMPT`(`:143`)의 담보 분류 섹션을 **30 leaf → 100+ 담보 트리**로 확장 (06 taxonomy 문서 기준). 함수 시그니처 `claude_parse(text_lines, is_proposal=False)`는 **불변** — FE/뷰 호출부 영향 0.
- [ ] **Prompt caching**: 100+ 담보 트리 + 정규화 사전 요약을 `system` 블록에 고정하고 `cache_control` breakpoint를 건다. 고객 가변값(증권 텍스트)은 breakpoint **뒤**로 → 캐시 읽기 0.1×.
- [ ] **모델 라우팅**: 비교안내서·정규화 학습 경로 = Opus(정확도 critical), 다건 OCR(M1) = Haiku, 야간 배치 = Batches 50% 할인. 토큰 측정은 `count_tokens`(tiktoken 금지).

> **보존 필수:** 한화 fast-path → `claude_parse` → regex fallback 의 3단 추출 경로. 7필드 → 100+ 필드로 폭만 넓히고 **경로 구조는 그대로**.

---

## 4. 동의 게이트 개조 (◑) — 모든 AI 기능의 물리적 스위치

병력(민감정보)이 Claude API(미국)로 나가므로, `detect` 호출 **전** 동의 확인이 detect API 자체를 여는 조건이다.

- [ ] `customers/models.py` `Customer`에 `consent_overseas_at`(DateTime, null) 추가 — **null = 미동의**.
- [ ] `ConsentLog`(✦) 모델: `customer / type='overseas' / agreed_at / ip / doc_version` 감사추적.
- [ ] `detect` 뷰 진입부 가드: `consent_overseas_at`가 null이면 **412** 반환 → FE 동의 모달.
- [ ] FE `customer-agree`(foliio `is_agree_term` 1탭)를 **국외이전 동의 분리 화면 + 로그 기록**으로 개조.
- [ ] 셀프진단(지인) 동선: 정보주체 **본인 1탭 동의** 후 진행.

> ⚠ **법무 게이트(Phase0).** `consent_overseas_at` 별도 필드 + 별도 동의서 + `ConsentLog` 분리는 **낙관 가정 금지**의 기본 전제다. 막히면 fallback: OCR·히트맵(none 중립)만 먼저 출시.

---

## 5. 신규 분석 레이어 (✦) — heatmap / guardrail

`calculate_total_analysis`(♻) 출력을 입력으로 받는 **얇은 신규 레이어**. BE 계산 엔진은 무변경.

**heatmap 3색 status 판정 (`customers/heatmap.py`):**

```
status = none    if actual_amount == 0
       = short   if actual_amount <  std_baseline * 0.7
       = enough  if actual_amount >= std_baseline * 0.7
```

> ⚠ **기준선 중립 모드(Phase0 미결, Q1).** `std_baseline` 출처·권위(금감원/보험연구원/자체+면책) 확정 전까지 **enough/short 판정 보류**, `none`(0원 보유여부)만 **회색 중립**으로 표기. 임계값 코드(`*0.7`)는 미리 짜두되 데이터 권위는 법무 산출물. UI는 출처주석(ⓘ) 자리만 확보.

**ai_guardrail (`core/ai_guardrail.py`):** AI 생성물(메시지·비교안내서) 후처리로 보험업법 위험 표현(단정/수익보장/비교과장) 플래그. `content_filter.py` 정규식 후처리 기법 차용, 룰셋만 교체. **'안전/심의완료' 배지 절대 금지 — 'AI 1차 보조, 최종책임 설계사' 면책 카피 고정.**

---

## 6. 정확 라인 참조 (포팅 시 펼쳐볼 좌표)

| foliio 좌표 | 심볼 | 포팅 액션 |
|---|---|---|
| `core/ocr/claude_parser.py:430` | `claude_parse(text_lines, is_proposal)` | 진입점 — 호출부 불변 보존 |
| `core/ocr/claude_parser.py:466` | `system_prompt = _SYSTEM_PROMPT + …` | 담보 트리 주입 + caching breakpoint |
| `core/ocr/claude_parser.py:143` | `_SYSTEM_PROMPT` | 30 → 100+ 담보 확장 |
| `core/ocr/claude_parser.py:94` | `_CATEGORY_MAP` | 1순위 정확 매칭 dict (확장) |
| `core/ocr/claude_parser.py:700` | `_add_coverage(...)` | **정규화 사전 삽입 본체** |
| `core/ocr/claude_parser.py:720-726` | 3순위~4순위 | **사전 = 3.5순위 끼우는 정확한 틈** |
| `core/utils.py:358` | `extract_text_from_pdf` | ♻ 그대로 (`:340`/`:455` authenticate 포함) |
| `customers/calculate.py:245` | `calculate_total_analysis` | ♻ 그대로 (heatmap 입력) |
| `customers/calculate.py:18` | `calculate_analysis` | ♻ 그대로 |
| `membership/credit.py:123` | `_check_and_consume(user, kind)` | `kind='ai'` 분기 추가 |
| `customers/models.py:76` | `Customer` | `+consent_overseas_at` 1필드 |

---

## 7. 검증 기준선 — 회귀 가드

- [ ] **8케이스 골든테스트 그대로 이식.** foliio `insurances/tests/test_premium_calculation_8cases.py`를 인파로 복사해 회귀 가드 (calculate.py가 ♻인 한 통과해야 정상). foliio 베타 기준 179 passed.
- [ ] **정규화 사전 신규 테스트.** ① happy path: `raw_name → 표준 담보 leaf` 매핑 + `hit_count++` 검증. ② 학습 루프: miss → `UnmatchedLog` 적재 → admin 매핑 → 다음 동일 `raw_name` 자동 hit.
- [ ] **OCR 추출률 ≥ 85%**(7→100+ 필드), **§97 필수항목 누락률 = 0%**(비교안내서 발행 하드블록).
- [ ] `verify.sh` 패턴(lint + test + build) 그대로 차용.

---

## 8. 기존 inpa/docs 정합성 메모

- 기존 `inpa/docs`(00~08 "Foliio 영업지원 에디션" 명칭)는 **인파 정체성으로 재작성** 대상. 제품명은 전부 **인파(Inpa)**.
- 본 11종 문서 세트가 **정본**. 등급 분류·라인 참조는 본 문서를 단일 출처로 한다.

---

## 9. 부록 — 라인 참조 검증 명령

```bash
# foliio 실코드와 본 지도의 좌표 일치 확인 (집필 시점 검증 완료)
cd ~/Desktop/foliio/Foliio_be/weapon
grep -n "def claude_parse\|def _add_coverage\|_SYSTEM_PROMPT\|_CATEGORY_MAP" core/ocr/claude_parser.py
grep -n "def extract_text_from_pdf\|authenticate"                            core/utils.py
grep -n "def calculate_total_analysis\|def calculate_analysis"               customers/calculate.py
grep -n "def _check_and_consume"                                             membership/credit.py
# 기대: claude_parse:430 / _add_coverage:700 / 3~4순위:720-726 /
#       _SYSTEM_PROMPT:143 / _CATEGORY_MAP:94 / extract_text_from_pdf:358 /
#       authenticate:340·455 / calculate_total_analysis:245 / calculate_analysis:18 /
#       _check_and_consume:123  ← 모두 일치 확인됨
```

---

### 부록 A — 등급 한 줄 체크리스트

- [x] **♻ 그대로:** `utils.py` PDF추출 · `calculate.py` 8케이스 · `models.py` Customer/CustomerInsurance · `share_token` · cron 패턴 · `credit.py` 골격
- [x] **◑ 개조:** `claude_parse` 프롬프트(담보 트리+caching) · `_add_coverage`(3.5순위 사전 삽입) · `customer-agree`→국외이전 동의+로그 · `content_filter`→`ai_guardrail`(룰셋) · `credit.py` `kind='ai'`
- [x] **✦ 신규:** `ai_guardrail.py` · `normalization.py` · `heatmap.py` · `message_prompts.py` · `watchdog.py` · `seed_taxonomy.py` · `NormalizationDict` 모델 · `ConsentLog` 모델
- [ ] **법무 게이트(Phase0, 코드 0줄):** ① 국외이전 동의서 개정안 ② §97 정확요건 6항목 ③ 기준선 출처·권위 — 막히면 OCR→히트맵(none)→정규화부터 선출시
