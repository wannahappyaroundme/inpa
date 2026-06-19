# 인파(Inpa) — AI(Claude) 활용 & 데이터

> 인파(Inpa)의 "심장" 문서. **증권 OCR → 담보 정규화 → 보장공백 진단 → 갈아타기 비교안내서 → AI 카톡 멘트**로 이어지는 분석 파이프라인이 어떻게 Claude를 호출하고, 어떤 데이터 모델 위에서 동작하며, 무엇이 출시를 막는지(컴플라이언스 게이트)를 다룬다.
> 모든 정량 수치는 베타 90일 실측 전 가설이므로 **(추정)** 라벨을 붙인다. 검증된 단가·모델 ID는 그대로 신뢰값으로 표기한다.
> 관련 문서: 데이터 모델·API는 `dev/02-data-model-and-api.md`, 포팅 지점은 `dev/03-porting-map.md`, 담보 분류 전체 사전은 `06-business-model.md`/taxonomy 부속 문서.

---

## 0. 한눈에 — 이 문서가 답하는 5가지

| # | 질문 | 핵심 답 | 절 |
|---|---|---|---|
| 1 | AI는 정확히 어디에 쓰이나? | 6개 터치포인트(M1~M6), 모든 호출에 입력·출력·가드레일 명세 | §1 |
| 2 | 담보 데이터는 어떻게 생겼나? | 15+ 카테고리 / 100+ 담보 4계층 트리 (foliio 모델 재활용) | §2 |
| 3 | 보험사마다 담보명이 다른 문제는? | `NormalizationDict` 사전 + 데이터 복리 플라이휠 | §3 |
| 4 | 출시를 막는 폭탄은? | 병력 국외이전 동의 게이트 + 기준선 출처 중립 모드 | §5 |
| 5 | AI 비용은 어떻게 통제하나? | Opus/Haiku 라우팅 + Prompt caching + Batches | §6 |

**설계 원칙 한 줄**: *"분석은 풀고(무료 미끼), 행동은 막는다(과금). 정확이 critical한 곳엔 Opus, 양으로 승부하는 곳엔 Haiku."*

---

## 1. AI 터치포인트 — 기능 × 입력 → Claude → 출력 × 가드레일

인파는 범용 챗봇이 아니다. AI는 **6개의 좁고 깊은 지점**에서만 호출된다. 각 호출은 "어떤 입력을 받아 / 어떤 모델이 / 무엇을 만들고 / 어떤 안전장치를 거치는가"가 명시적으로 정의된다.

### 1.1 터치포인트 표

| ID | 기능 | 입력(Input) | 모델 | 출력(Output) | 가드레일(Guardrail) | credit |
|---|---|---|---|---|---|---|
| **M1** | 증권 다건 OCR 파싱 | PDF/이미지 텍스트(증권 N장) | **Haiku 4.5** | 구조화 담보 JSON (100+ 필드) | 국외이전 동의 412 게이트 · 7필드 추출률 ≥85% · 한화 fast-path 우선 | insurance_credit (portfolio_type=1) |
| **M2** | 담보명 정규화 학습 | OCR 미매칭 raw_name | **Opus 4.8** | std_detail 매핑 후보 + confidence | admin 검수 전 자동승격 금지(운영 미결) · UNIQUE(company,raw_name) | — (백엔드) |
| **M3** | 보장공백 히트맵 판정 | 정규화된 담보 + 표준 기준선 | (모델 호출 없음, 룰) | status: enough/short/none/neutral | 기준선 출처 미확정 시 neutral 회색 폴백 | ai_credit |
| **M4** | 갈아타기 비교안내서 | 기존+제안 포트폴리오 | **Opus 4.8** | §97 6항목 비교 내러티브 | §97 필수항목 누락률=0% · 필수 미완료 시 발행 하드블록 · 면책카피 상시 | ai_credit |
| **M5** | 컴플라이언스 가드레일 | M4·M6 생성물 | (룰 + 경량 LLM 판정) | 위반 플래그 + 사유 | 단정표현/수익보장/비교과장 탐지 · 안전배지 금지 | (후처리, 무차감) |
| **M6** | AI 카톡 메시지 | 목적 enum + 고객 컨텍스트 | **Haiku 4.5** | 카톡 발송용 멘트(클립보드) | M5 통과 필수 · 자동발송 사칭 금지 · 복사만 | ai_credit |

> **읽는 법**: M1/M6은 "양"(증권 수십 장, 메시지 반복 생성)이라 Haiku. M2/M4는 "정확"(정규화 사전 학습·§97 합법성)이라 Opus. M3는 LLM을 안 쓴다 — 결정론적 임계값 룰이라 비용 0·재현성 100%.

### 1.2 모델 라우팅의 이유 (충돌5 합의)

사업관리는 §97 합법성 때문에 비교안내서(M4)를 정확도 critical로 보고 **Opus**를 권장했고, per-call 원가 상승을 우려했다. 합의:

```
정확도 critical (합법성·데이터 복리)  →  Opus 4.8  →  M2 정규화 학습 · M4 비교안내서
양·반복 (OCR 다건 · 멘트 생성)        →  Haiku 4.5 →  M1 OCR · M6 메시지
야간 비실시간 배치                    →  Batches 50% 할인 (M1 대량 재처리 등)
```

Opus의 per-call 원가는 §6의 **Prompt caching**(정규화 사전을 system 블록에 고정 → 읽기 0.1×)으로 수백원대까지 낮춘다.

### 1.3 목적 enum 프롬프트 매핑 (M6)

AI 메시지는 자유 생성이 아니라 **6개 목적 칩** 중 하나를 골라야 한다. 목적별로 system 프롬프트의 톤·CTA가 달라진다.

| enum | 상황 | 메시지 성격 | §97 위험 |
|---|---|---|---|
| `need_awakening` | 보장공백 발견 | 니즈 환기, 단정 금지 | 중 — 과장 플래그 대상 |
| `expiry` | 만기 D-30 | 갱신/리모델링 안내 | 저 |
| `birthday` | 생일 | 관계 유지 인사 | 없음 |
| `gap` | 특정 담보 0원 | 공백 1건 집중 | 중 |
| `referral` | 소개 요청 | 제3자 동의 전제 환기 | **고 — 무작위발굴 위반 주의** |
| `remind` | 미응답 리마인드 | 후속 넛지 | 저 |

`referral`은 컴플라이언스(무작위 발굴 금지)와 직접 충돌하므로 M5 가드레일이 "제3자 동의 확인" 문구를 강제 삽입한다.

---

## 2. 담보 전체 체계 — 데이터 모델 (15+ 카테고리 / 100+ 담보)

분석의 정확도는 "우리가 담보를 얼마나 촘촘히 모델링했는가"에 비례한다. foliio의 4계층 분석 모델을 **그대로 재활용**하되, 시드 데이터를 30개 → 100+로 확장한다.

### 2.1 4계층 모델 (foliio 재활용 ♻)

```
AnalysisCategory        대분류 (사망 / 진단비 / 후유장해 / 수술 / 입원 / 실손 ...)
   └─ AnalysisSubCategory   중분류 (진단비-암 / 진단비-뇌 / 진단비-심장 ...)
        └─ AnalysisDetail        표준 담보 leaf ("일반암진단비", "뇌졸중진단비")  ← 정규화의 매핑 타겟
             └─ ChartDetail          차트 표기 단위 (chart_based_amount)
```

- **BE 무변경**: 모델 구조·`calculate_total_analysis` 출력은 그대로. 확장은 시드 데이터(`seed_taxonomy` command)만.
- **정규화의 매핑 타겟은 `AnalysisDetail`**: 보험사별 raw_name이 결국 이 leaf로 수렴한다(§3).

### 2.2 대분류 트리 (15+ 카테고리)

```
사망          ── 일반사망 · 재해사망 · 교통재해사망 · 질병사망 · 정기사망
진단비-암     ── 일반암 · 소액암 · 고액암 · 상피내암 · 유사암(경계성/제자리)
진단비-뇌     ── 뇌졸중 · 뇌출혈 · 뇌경색 · TIA(일과성)
진단비-심장   ── 급성심근경색 · 허혈성심장질환
진단비-중증   ── CI(중대질병) · 희귀난치성질환
후유장해      ── 상해후유장해 · 질병후유장해 (3~100%)
수술비        ── 1~5종수술 · 암수술 · 뇌수술 · 심장수술
입원비        ── 상해입원 · 질병입원 · 중환자실입원
실손          ── 질병입원/통원/처방 · 상해입원/통원/처방 · 비급여(도수·MRI·주사)
운전자        ── 형사합의금 · 벌금 · 변호사선임비용
일상생활배상  ── 일배책(가족/자녀)
간병/치매     ── LTC(장기요양) · 중증치매 · 경증치매
화상/골절     ── 화상진단 · 골절진단 · 깁스치료
3대질병 통합  ── 암·뇌·심 묶음 담보
만기환급/적립 ── 적립보험료 · 만기환급금
```

> **왜 이 깊이인가**: 히트맵(M3)이 "🔴 일반암은 있는데 🟡 유사암이 부족"을 짚으려면 leaf 단위 분류가 필요하다. 대충 "암 보장 있음"으로 뭉치면 갈아타기 wedge가 죽는다.

### 2.3 시드 확장 명령

```bash
python manage.py seed_taxonomy   # AnalysisCategory/Sub/Detail/ChartDetail 100+ leaf + 정규화 사전 v0 seed
```

`seed_taxonomy`는 (1) 담보 트리 100+ leaf, (2) 상위 30담보 × 5대 보험사 정규화 사전 부트스트랩(~200행)을 한 번에 심는다. Phase 0 법무 산출물(기준선 출처)이 확정되면 표준 금액 컬럼만 추가 주입한다.

---

## 3. 보험사별 담보명 정규화 — 분석/OCR의 심장 (데이터 복리 해자)

### 3.1 문제: 같은 담보, 다른 이름

같은 "일반암 진단"이라도 보험사·상품마다 명칭이 다르다. OCR이 raw_name을 뽑아도 우리 표준 leaf에 못 붙이면 분석이 비어 버린다.

| 표준 담보 (AnalysisDetail) | 삼성생명 | 교보생명 | 한화생명 | 메리츠화재 |
|---|---|---|---|---|
| 일반암진단비 | 암진단**급부금** | 암진단**보험금** | 암진단자금 | 암진단비(일반) |
| 뇌졸중진단비 | 뇌졸중진단급부금 | 뇌졸중진단보험금 | 뇌졸중치료자금 | 뇌졸중진단비 |
| 급성심근경색진단비 | 급성심근경색급부금 | AMI진단보험금 | 심근경색진단자금 | 급성심근경색증진단비 |

범용 AI(ChatGPT)는 이 사전을 갖고 있지 않다. **이게 모방하기 어려운 데이터 복리의 정체** — 쓸수록 두꺼워지는 우리만의 매핑 자산이다.

### 3.2 NormalizationDict 모델 (신규 ✦ — 복리의 물리적 구현체)

```
NormalizationDict
  std_detail_id   FK → AnalysisDetail      # 표준 담보 leaf (우리 틀)
  company         SmallInt                  # 삼성생명/교보/한화/신한라이프/삼성화재 ...
  raw_name        CharField  db_index       # "암진단급부금", "암진단보험금"
  source          CharField                 # seed / ocr_learned / admin_verified
  confidence      SmallInt                  # 자동학습 신뢰도 (0~100)
  verified_by     FK User  null             # admin 검수자
  hit_count       Int                       # 매칭될 때마다 ++  ← 두꺼워지는 증거
  UNIQUE(company, raw_name)                  # 같은 보험사 같은 이름은 1행
```

- `hit_count`: 빈도 우선순위. 자주 맞는 매핑이 위로 올라와 다음 OCR을 가속.
- `UNIQUE(company, raw_name)`: 한 보험사의 한 명칭은 단 하나의 표준 담보에만 매핑(모순 방지).
- 관계형으로 충분 — **MariaDB 유지**(PG/JSONB 전환 보류, 충돌7 합의). 포팅 비용 0.

### 3.3 데이터 복리 루프 (플라이휠)

```
   ┌──────────────────────────────────────────────────────────┐
   │                                                          │
   ▼                                                          │
[OCR] raw_name 추출 ──▶ NormalizationDict 조회                 │
   │                         │                                │
   │                  매칭 성공 → hit_count++ → 표준 담보 확정   │
   │                         │                                │
   │                  매칭 실패                                 │
   ▼                         ▼                                │
[unmatched_log 적재] ──▶ [admin 1탭 매핑 UI] ──▶ 사전 영구 추가 ─┘
                          (source=admin_verified)
   "다음부터 같은 raw_name은 자동 매칭"
```

쓸수록 unmatched가 줄고, 사전이 두꺼워지고, OCR 정확도가 오른다. 신규 진입자는 이 누적 사전을 복제할 수 없다.

> **운영 미결 (openQuestion)**: `hit_count` 5회+ 시 admin 검수 없이 자동 승격할지 여부. 자동매핑 오류는 비교안내서를 거짓으로 만들어 **§97 위반 리스크**가 되므로, 정확도 vs 운영비용 트레이드오프를 베타 후 결정. 현재 전제는 **admin 검수 필수**.

### 3.4 매칭 엔진을 어디에 끼우나 — 정확한 포팅 지점 (◑)

foliio `claude_parser.py`의 `_add_coverage`는 4단계 매칭이다. **3순위(detail 키워드)와 4순위(fuzzy) 사이**에 정규화 사전 단계를 삽입한다.

```
[기존 4단계]                          [인파 5단계 — ◑ 개조]
1. 정확 매칭 (_CATEGORY_MAP)           1. 정확 매칭
2. 키워드 매칭                          2. 키워드 매칭
3. detail 키워드 매칭                   3. detail 키워드 매칭
4. fuzzy 매칭 (3글자+)                  ★ NormalizationDict 조회 (company, raw_name)  ← 신규
                                       4. fuzzy 매칭
                                       └─ 전부 실패 → unmatched_log 적재
```

포팅 참조 라인: `claude_parser.py:700 _add_coverage`, `claude_parser.py:466 _SYSTEM_PROMPT`(100+ 담보 트리 주입). 매칭 엔진 본체는 신규 `insurances/normalization.py`.

---

## 4. OCR — 증권 → 구조화 담보 (M1)

### 4.1 추출 체인 (foliio 재활용 ♻)

```
PDF 업로드 ──▶ extract_text_from_pdf (core/utils.py)
                  ├─ pdfplumber  (1순위, 테이블 구조 보존)
                  └─ PyMuPDF     (폴백)
                  └─ 암호화 PDF: password authenticate
              ──▶ text_lines
              ──▶ claude_parse(text_lines, is_proposal)   ← Haiku 4.5
                  ├─ 한화 fast-path (정규식 직행)
                  ├─ Claude 파싱 (담보 트리 system 프롬프트)
                  └─ regex fallback
              ──▶ _add_coverage 5단계 (정규화 사전 결합, §3.4)
              ──▶ 구조화 담보 JSON (100+ 필드)
```

신규 의존성 0개: `anthropic / pdfplumber / PyMuPDF` 모두 foliio 보유.

### 4.2 다건 OCR (M1 — detect_batch ✦)

증권 N장을 한 번에 큐잉하고 **부분 실패를 허용**한다. 1장이 깨져도 나머지는 살린다.

```
POST /api/v1/insurance/detect_batch/
  입력: [증권1.pdf, 증권2.pdf, ... 증권N.pdf]
  출력: { parsed: [...], partial_failed: [{file, reason}, ...] }
```

- 외부 API 규칙(전역): 부분 실패 OK, 어느 장이 실패했는지 로그. 배치 호출 사이 딜레이.
- 재시도: 네트워크/타임아웃만 1s→2s→4s 최대 3회. 401/403/400은 재시도 금지.

### 4.3 OCR 정확도 가드레일

| 항목 | 기준 | 근거 |
|---|---|---|
| 7필드 추출률 | ≥ 85% | 가드레일 지표(기획 05) |
| 진단비 키워드 | 처치/치료 제외, **진단만** | foliio 트랩(과매칭) — 명시 리스트로 관리, 정규식 느슨화 금지 |
| 중복 매칭 | 표준 담보 1개씩, 최대값 유지 | post-v1.6 fix 계승 |
| 음수 보험료 | `max(0, …)` guard | foliio 2026-05-29 fix 계승 |

---

## 5. 컴플라이언스 게이트 — 출시 가부를 쥔 폭탄

> **이 절은 코드가 아니라 법무 산출물에 종속된다.** Phase 0(코드 0줄)에서 선결되지 않으면 AI 기능 전체가 막힌다.

### 5.1 가장 무서운 단일 폭탄 — 병력 국외이전 동의 (충돌2)

병력(민감정보)이 Claude API(미국, Anthropic Inc.)로 나간다. 이 동의가 없으면 **detect API 자체를 못 연다**. 전 AI 기능의 물리적 게이트.

```
detect 호출 흐름:
  요청 ──▶ Customer.consent_overseas_at 확인
            │
            ├─ NULL(미동의) ──▶ 412 게이트 + FE 동의 모달
            │
            └─ 동의 시각 존재 ──▶ Claude 호출 진행
```

**낙관 가정 금지 (합의된 기본 전제):** customer-agree의 기존 `is_agree_term` 1필드로 커버된다고 가정하지 않는다. **별도 필드 + 별도 로그**로 설계한다.

```
Customer
  consent_overseas_at   DateTime null   # null = 미동의 = 게이트 ON

ConsentLog (✦ 감사추적)
  customer    FK
  type        "overseas"
  agreed_at   DateTime
  ip          이용자 IP
  doc_version 동의서 버전          # 동의서 개정 시 추적
```

> **막히면 fallback**: 법무 자문 전까지 detect를 못 열면, **중립 기능부터 선출시** — OCR(M1) → 히트맵 none 중립(M3) → 정규화(M2). 비교안내서(M4)·메시지(M6)는 §97·동의 확정 후 오픈.

### 5.2 기준선 출처 중립 모드 (충돌3)

히트맵(M3)의 🟡부족/🔴없음 판정은 "표준 보장 기준선" 데이터에 종속한다. 자체 컨센서스로 "부족"을 단정하면 **부당권유 리스크**.

```
status 판정 로직 (M3):
  none     if  actual_amount == 0                       # 0원 = 객관적 사실, 안전
  short    if  actual_amount <  std_baseline * 0.7      # 출처 확정 시에만
  enough   if  actual_amount >= std_baseline * 0.7
  neutral  if  std_baseline 출처 미확정                  # ← 현재 기본값, 회색 표기
```

- **임계값 코드(`std_baseline * 0.7`)는 미리 짜둔다.** 데이터 권위(금감원/보험연구원/자체+면책)만 Phase 0 법무 선결.
- 출처 확정 전: **none(0원 보유여부)만 회색 중립 표기.** enough/short 판정 보류.
- UI는 출처 주석 자리(ⓘ)만 확보.

### 5.3 §97 비교안내 정확요건 (M4)

갈아타기 비교안내서는 부당승환(§97)의 합법 방패다. **6항목 체크리스트 미완료 시 발행 하드블록.** 불리점(해지손실·면책리셋·예정이율·갱신전환)을 자동 경고하고, 면책고지("AI 1차 보조, 최종책임 설계사")를 상시 노출한다. **"심의 안전/완료" 배지 절대 금지.**

### 5.4 ai_guardrail 룰셋 (M5 — content_filter 개조 ◑)

foliio `content_filter.py`(PII 정규식)를 `ai_guardrail.py`로 개조해 보험업법 룰셋을 얹는다.

| 플래그 | 탐지 대상 | 예시 |
|---|---|---|
| 단정표현 | "무조건", "100% 보장" | 확정적 단언 |
| 수익보장 | "수익률 X% 보장" | 투자 수익 약속 |
| 비교과장 | "타사보다 무조건 유리" | 근거 없는 우위 단정 |

후처리 단계로 동작, 위반 시 플래그 + 사유 반환. PII 정규식(mobile/RRN/card)은 그대로 재사용.

---

## 6. 비용 · 캐싱 — AI 원가를 수백원대로

### 6.1 검증된 단가 (per MTok, 신뢰값)

| 모델 | 모델 ID | input $/1M | output $/1M | context | 용도 |
|---|---|---|---|---|---|
| Opus 4.8 | `claude-opus-4-8` | $5 | $25 | 1M | M2 정규화 학습 · M4 비교안내서 |
| Sonnet 4.6 | `claude-sonnet-4-6` | $3 | $15 | 1M | (중간 난이도 폴백 옵션) |
| Haiku 4.5 | `claude-haiku-4-5` | $1 | $5 | 200K | M1 OCR · M6 메시지 |

> 위 단가·모델 ID는 claude-api 레퍼런스(cached 2026-06-04) 검증값. 모델 라우팅 근거는 §1.2.

### 6.2 비용 절감 2단 레버

**① Prompt caching — 정규화 사전을 system 블록에 고정**

캐싱은 **prefix 매칭**이다. 프리픽스의 한 바이트라도 바뀌면 그 뒤 전체가 무효화된다. 그래서:

```
[system 블록]  정규화 사전 + 담보 트리 + §97 프롬프트   ← cache_control: {type:"ephemeral"} 고정
                                                       (안정 = 프리픽스 = 캐시 읽기 0.1×)
[messages 블록] 고객별 가변값(증권 텍스트, 담보값)       ← breakpoint 뒤, 매 호출 변동
```

- 캐시 읽기 ≈ **0.1×** 기본 input 단가 → Opus의 무거운 사전 비용이 90% 절감.
- 캐시 쓰기 1.25×(5분 TTL) / 2×(1시간 TTL). 5분 TTL 기준 **2회 호출이면 손익분기**.
- **최소 캐시 프리픽스**: Opus 4.8 = 4096 토큰, Haiku 4.5 = 4096, Sonnet 4.6 = 2048. 사전이 이보다 짧으면 캐시가 조용히 안 걸린다(에러 없음).
- **침묵 무효화 주의**: system 프롬프트에 `now()`·UUID·정렬 안 된 JSON·세션ID 넣지 말 것. `usage.cache_read_input_tokens`가 0이면 어딘가 프리픽스가 매 호출 바뀌는 것.
- 캐시는 **모델별로 스코프**된다 — M1(Haiku)과 M4(Opus)는 서로 다른 캐시. 한 호출 안에서 모델을 바꾸면 무효화.

**② Batches API — 야간 비실시간 50% 할인**

실시간이 아닌 작업(대량 증권 재처리, 정규화 사전 일괄 재매핑)은 Batches로.

- 50% 단가 할인, 배치당 ≤ 100K 요청 / 256MB.
- 대부분 1시간 내 완료, 최대 24시간. 결과 29일 보관.
- M1 야간 백필·M2 사전 일괄 학습에 적합. M4 비교안내서는 실시간 경로라 Batches 부적합.

### 6.3 토큰 측정 — `count_tokens` (tiktoken 금지)

모델별 측정은 반드시 `POST /v1/messages/count_tokens`(SDK `client.messages.count_tokens`). **tiktoken은 OpenAI 토크나이저라 Claude를 15~20% 과소집계** — 모델별 예산·비용 계산이 틀어진다. Opus 4.8 / Sonnet 4.6 / Haiku 4.5는 동일 토크나이저 계열이므로 셋 사이 토큰 수는 대략 일정(단가만 차이).

### 6.4 비용 거버넌스

```
호출당 로깅 (모델·input/output 토큰·캐시 read/write·원가)
   └─▶ 월 예산 캡 + 임박 알림 (전역 외부 API 비용 규칙)
   └─▶ 보조지표: "발송 액션당 AI 비용"  ← 북극성(발송)과 비용을 직접 연결
```

호출당 원가를 §6.2 두 레버로 수백원대(추정)까지 낮추고, "발송 1건당 얼마"를 KPI로 추적해 비용이 가치(발송)에 비례하는지 감시한다.

---

## 7. foliio 재활용 등급 요약 (이 문서 범위)

| 영역 | foliio 자산 | 등급 | 인파 처리 |
|---|---|---|---|
| PDF 추출 | `core/utils.py extract_text_from_pdf` | ♻ | 무변경 |
| OCR 파싱 | `claude_parser.py claude_parse` | ◑ | system 프롬프트에 100+ 담보 트리 주입 |
| 담보 매칭 | `claude_parser.py _add_coverage` | ◑ | 3·4순위 사이 정규화 사전 단계 삽입 |
| 분석 4계층 | `AnalysisCategory/Sub/Detail/ChartDetail` | ♻ | 시드 30→100+ 확장(seed_taxonomy) |
| 동의 | `customer-agree / is_agree_term` | ◑ | consent_overseas_at + ConsentLog 분리 |
| 가드레일 | `content_filter.py` (PII 정규식) | ◑ | ai_guardrail.py 보험업법 룰셋 |
| 정규화 사전 | — | ✦ | NormalizationDict 신규 |
| 히트맵 | — | ✦ | heatmap.py 3색+neutral 신규 |
| 목적 enum | — | ✦ | message_prompts.py 신규 |

(♻ 그대로 · ◑ 개조 · ✦ 신규. 전체 포팅 지도는 `dev/03-porting-map.md`.)

---

## 8. 미해소 과제 (openQuestions — 이 문서 관련)

- **[법무 Q1]** 표준 보장 기준선의 출처·권위(금감원/보험연구원/자체+면책)? 확정 전 M3는 neutral 회색만. *→ §5.2*
- **[법무 Q2]** 병력 국외이전 동의를 customer-agree 1탭으로 커버 가능? 또는 consent_overseas_at 별도 필드 필수? 전 AI 기능 게이트. *→ §5.1*
- **[법무 Q3]** §97 비교안내 6항목 법적 확정 내용 + AI 추출 누락분 책임 경계. *→ §5.3*
- **[운영]** 정규화 사전 `hit_count` 5회+ 자동승격 허용 여부 + 검수 UI 운영 주체. 자동매핑 오류 = §97 거짓 리스크. *→ §3.3*

---

*문서 끝. 다음 읽기: 데이터 모델·API 상세는 `dev/02-data-model-and-api.md`, 포팅 라인 참조는 `dev/03-porting-map.md`.*
