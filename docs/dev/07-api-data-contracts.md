# 인파(Inpa) 첫 슬라이스 — API & 데이터 계약

> 증권 업로드 → OCR(claude_parse) → 담보 정규화 → 분석 파이프라인 + (a)공유뷰A 인사이트 API (b)히트맵 충족 그리드 API
> 정본 교차검증: foliio 실코드 `claude_parser.py:430/700`, `customers/calculate.py:245`, `utils.py:358`. 라인 100% 대조 완료.
> 등급 범례 — **♻ 무변경**(복사+리네임만) / **◑ 부분변경**(프롬프트·필드 추가) / **✦ 신규**(인파 net-new)

---

## 0. 문서 범위와 비범위

이 문서가 동결하는 것:
- [x] detect 파이프라인 6단계 (412 게이트 → 추출 → 파싱 → 정규화 3.5순위 → 계산 → 크레딧)
- [x] 공유뷰A 인사이트 API 요청/응답 JSON 전문
- [x] 히트맵 충족 그리드 API 요청/응답 JSON 전문
- [x] 데이터 모델 (담보 4계층 트리 / NormalizationDict / UnmatchedLog / NorthStarEvent / Customer +1필드)
- [x] foliio 포팅 등급(♻/◑/✦)별 구체

이 문서가 **다루지 않는** 것 (2차 웨이브):
- [ ] 비교안내서 `GET /customer/:id/compare/` (§97, G3 법무 미확정)
- [ ] AI 카톡 메시지 `POST /ai/message/` (G4 광고심의 미확정)
- [ ] 다건 일괄 OCR `POST /insurance/detect_batch/` (단건 happy만)
- [ ] 국외이전 동의 풀스택 (ConsentLog 6요건) — 이번엔 `consent_overseas_at` 필드 + 412 배선만
- [ ] graded 모드 3색 풀가동 — neutral 디폴트, 코드만 작성

---

## 1. 파이프라인 전체 — `POST /insurance/detect/`

증권 1장이 들어와 담보로 정규화되어 계산까지 도달하는 단일 동선. **순서는 의존성 강제**다.

### 1.1 요청

```
POST /api/v1/insurance/detect/
Content-Type: multipart/form-data
Authorization: Token <DRF_TOKEN>

  customer_id   : int     (필수)
  file          : binary  (필수, PDF)
  password      : string  (선택, 암호화 PDF 해제용)
  is_proposal   : bool     (선택, default false — true면 portfolio_type=2 제안)
```

### 1.2 처리 순서 (6단계)

```
POST /insurance/detect/
  │
  ├─① 동의 게이트  [✦ 신규 배선]
  │    customer.consent_overseas_at is None
  │      → 412 {reason:'CONSENT_OVERSEAS_REQUIRED'}   ★detect에만 물림
  │
  ├─② 텍스트 추출  [♻ utils.py:358 extract_text_from_pdf 무변경]
  │    pdfplumber(테이블 보존) → 실패 시 PyMuPDF 폴백
  │    암호화 PDF: doc.authenticate(password)
  │
  ├─③ Claude 파싱  [◑ claude_parser.py:430 claude_parse — 프롬프트만 개조]
  │    한화 fast-path → claude_parse(lines, is_proposal)
  │    프롬프트에 100+ 담보 트리 주입 (seed_taxonomy 결과)
  │
  ├─④ 담보 매칭   [◑ claude_parser.py:700 _add_coverage — 3.5순위 삽입]
  │    매칭 사다리 (아래 §2) → std_detail 연결 또는 UnmatchedLog 적재
  │
  ├─⑤ 계산        [♻ insurances/models.py CustomerInsurance.calculate 무변경]
  │    CustomerInsurance + CustomerInsuranceDetail 생성 → calculate()
  │    numpy_financial.fv 8케이스 분기 / 음수 guard max(0, assurance−renewal)
  │
  └─⑥ 크레딧 차감 [◑ credit.py — kind='ocr' 추가]
       detect = ocr 차감 (베타 FREE_TIER_UNLIMITED 우회)
```

### 1.3 응답

**200 성공**
```json
{
  "insurance_id": 1024,
  "insurance_company": "삼성생명",
  "is_proposal": false,
  "coverages": [
    {
      "raw_name": "암진단급여금",
      "std_detail_id": 41,
      "std_detail_name": "일반암진단비",
      "match_source": "normalization",
      "assurance_amount": 30000000,
      "monthly_premium": 18500
    },
    {
      "raw_name": "뇌혈관질환진단비",
      "std_detail_id": 51,
      "std_detail_name": "뇌졸중진단비",
      "match_source": "keyword",
      "assurance_amount": 20000000,
      "monthly_premium": 9200
    }
  ],
  "unmatched": [
    {"raw_name": "특정고도장해연금", "occurrence": 1}
  ]
}
```

`match_source` enum (어느 사다리 칸에서 잡혔는지 = 신뢰도 추적):

| 값 | 사다리 칸 | 신뢰도 |
|---|---|---|
| `category_map` | 1순위 `_CATEGORY_MAP` | 최고 (결정론) |
| `keyword` | 2·3순위 키워드 | 높음 |
| `normalization` | **3.5순위 (해자)** | 중간 (admin 검증분) |
| `fuzzy` | 4순위 fuzzy | 낮음 (추측) |
| `none` | 미분류 → `unmatched[]` | — |

**에러 응답**

| 코드 | reason | 의미 | FE 처리 |
|---|---|---|---|
| 412 | `CONSENT_OVERSEAS_REQUIRED` | 국외이전 동의 미수신 | 동의 1탭 모달 → 동의 후 재시도 |
| 402 | `CREDIT_EXHAUSTED` | 크레딧 소진 (베타 미발생) | `UpgradeGuideModal` |
| 422 | `OCR_EXTRACT_FAILED` | 추출 0줄 (스캔본·손상) | 수기입력 폴백 동선 |
| 400 | `PASSWORD_REQUIRED` / `PASSWORD_WRONG` | 암호화 PDF 비번 | 비번 모달 |

> ★게이트 경계: **412는 오직 detect에만** 물린다. 공유뷰A·히트맵은 "추출 후 서버연산 = 무게이트 경로"이므로 G1~G5 어떤 법무 게이트에도 막히지 않는다. 막히는 건 입력단(OCR=Claude API=병력 국외이전)뿐.

---

## 2. 해자 코드 지점 — `_add_coverage` 3.5순위 삽입 (◑)

foliio `claude_parser.py:700`의 매칭 사다리에 **딱 한 칸을 끼워 넣는 것**이 인파의 차별 자산이다. 키워드보다 약하고 fuzzy보다 강한 위치 — 이것이 §97 부당권유(거짓 담보 매핑) 차단선.

### 2.1 기존 foliio 매칭 사다리 (`:712~729`, 무변경)

```
1순위  _CATEGORY_MAP.get(name)                 ← 결정론 정확 매칭
2순위  _match_by_keywords(original_name)        ← 원문 키워드
3순위  _match_by_keywords(detail_name)          ← 정제명 키워드
─────────────────────────────────────────────  ★ 여기 3.5순위 삽입 ★
4순위  _fuzzy_match_category(name)              ← 저신뢰 추측 (3글자+)
```

### 2.2 삽입 계약 (import 1줄 + 4줄)

```
# 3순위(_match_by_keywords detail) 직후, 4순위(fuzzy) 직전:

from inpa.insurances import normalization        # import 1줄

if not mapped:                                    # 4줄
    hit = normalization.lookup(company, raw_name) # (cat, sub, det) | None
    if hit:
        mapped, match_source = hit, "normalization"
    else:
        UnmatchedLog 적재 (occurrence++)
```

### 2.3 `normalization.lookup()` 계약

```
lookup(company: int, raw_name: str) -> (category, sub, detail) | None
  - NormalizationDict 조회: WHERE company=? AND raw_name=?
  - 베타: source='admin_verified'(검증분)만 매칭 → 오매핑 0 보장
  - hit  → hit_count++ (복리 카운터, 자주 쓰이는 매핑이 강해짐)
  - miss → None 반환 → 호출부가 UnmatchedLog.update_or_create(occurrence++)
```

**무변경 유지 항목** (회귀 위험 0):
- [x] 진단비 처치성 가드 (`:734`) — 처치/치료 키워드 진단비 오매핑 방지
- [x] 최대값 dedup (`:774`) — 동일 담보 중복 시 최대값 유지
- [x] 음수 guard — `monthly_non_renewal_premium = max(0, assurance − renewal)`

---

## 3. (a) 공유뷰A — 인사이트 API

**`GET /customer/:id/share/analysis/?token=<share_token>&ref=<설계사코드>`**

| 속성 | 값 |
|---|---|
| 권한 | `AllowAny` + `share_token` 검증 (foliio CustomerViewSet 공개뷰 패턴) |
| 동작 | `calculate_total_analysis()` [♻ calculate.py:245 무변경] 출력 **그대로** + `insights[]` 카드 + 계측 |
| 계측 | 진입 시 `share_view` 서버 적재 / `?ref=` 있으면 `referral_attributed` 귀속 (Day1, 사후복원 불가) |
| 크레딧 | 무차감 (열람은 과금 없음) |
| robots | `noindex` 헤더 (민감 분석 검색노출 방지) |

### 3.1 요청

```
GET /api/v1/customer/1024/share/analysis/?token=a1b2c3d4-...&ref=PL0457
  (Authorization 헤더 없음 — 무인증 공개뷰)
```

### 3.2 응답 200

`calculate_total_analysis` 출력(`monthly_*`/`total_*`/`case_list`/`chart_list`)을 그대로 내리고, 그 위에 `insights[]`·`disclaimer`만 인파가 얇게 덧붙인다.

```json
{
  "customer": {
    "name": "홍**",
    "gender": 1,
    "birth_day": "1985"
  },

  "monthly_premiums": 152000,
  "monthly_renewal_premium": 38000,
  "monthly_non_renewal_premium": 102000,
  "monthly_earned_premium": 12000,
  "total_premiums": 48700000,
  "total_cancellation_loss": 0,

  "case_list": [
    {
      "name": "일반암진단비",
      "total_premium": 30000000,
      "non_renewal_old_list": [0,0,30000000,30000000,30000000,30000000,0,0,0,0],
      "renewal_old_list":     [0,0,0,0,0,0,0,0,0,0],
      "is_show_old_price": true
    }
  ],

  "chart_list": [
    {"name": "암", "chart_based_amount": 50000000, "actual_amount": 30000000}
  ],

  "insights": [
    {
      "key": "cancer_none",
      "headline": "이 고객은 고액암 진단비가 아직 없어요",
      "emphasis_value": 0,
      "severity": "none",
      "detail_id": 42
    }
  ],

  "disclaimer": "AI 1차 보조 분석입니다. 최종 책임은 담당 설계사에게 있습니다.",
  "computed_at": "2026-06-19T09:12:00+09:00"
}
```

### 3.3 필드 타입 표

| 필드 | 타입 | 출처 | 비고 |
|---|---|---|---|
| `customer.name` | string | Customer | **마스킹** (홍** — Q 미결, §8) |
| `customer.gender` | int\|null | Customer.gender | 1=남/2=여/null |
| `customer.birth_day` | string | Customer.birth_day | 연도만 (개인정보 최소화, 추정) |
| `monthly_premiums` | int | calculate.py ♻ | KRW 정수 |
| `monthly_non_renewal_premium` | int | calculate.py ♻ | 음수 guard 적용 |
| `total_cancellation_loss` | int | calculate.py ♻ | 해지환급 손실 |
| `case_list[].non_renewal_old_list` | int[10] | calculate.py ♻ | **항상 10칸 고정** → FE가 연속막대 도출 |
| `case_list[].renewal_old_list` | int[10] | calculate.py ♻ | 동일 |
| `case_list[].is_show_old_price` | bool | calculate.py ♻ | 막대 노출 여부 |
| `chart_list[].chart_based_amount` | int | AnalysisDetail | **기준선 hook** (히트맵 std_baseline과 동일 출처) |
| `chart_list[].actual_amount` | int | calculate.py ♻ | 실제 보장액 |
| `insights[]` | object[] | ✦ BE 얇은 헬퍼 | §3.4 |
| `disclaimer` | string | ✦ 하드코딩 | 상시 고정 |

### 3.4 `insights[]` 도출 규칙 (✦ BE 얇은 헬퍼, calculate 무변경)

`chart_list`의 `actual_amount` vs `chart_based_amount` 차액 상위 N개를 "한 줄 인사이트 + 강조 숫자" 카드로 변환한다. **calculate.py는 손대지 않는다** — 별도 헬퍼가 출력만 가공.

```
insight 한 건 스키마:
  key            : string   고유 키 (cancer_none, brain_short, ...)
  headline       : string   한 줄 문장 (정직성 레드라인 적용)
  emphasis_value : int      강조 숫자 (KRW) — FE가 accent-blue 볼드
  severity       : enum     none | short | enough  (neutral 모드는 none만)
  detail_id      : int      AnalysisDetail FK (바텀시트 연결)
```

★**중립모드 발화 정책** (Q1 std_baseline 출처 미확정 동안):

| mode | 발화 대상 | headline 톤 | 예시 |
|---|---|---|---|
| `neutral` (디폴트) | **`actual_amount==0` 항목만** | "없음(0원)" 사실만 — **'부족' 단정 금지** | "고액암 진단비가 **아직 없어요**" |
| `graded` (Q1 확정 후) | none + short | 금액 단정 허용 | "암 진단비 **3,000만원 부족**" |

- neutral 동안 `severity`는 `none`만 내려간다. `short`/`enough` 단정은 보류.
- 표기 상한 개수·우선순위(없음>부족? 차액 큰 순?)·반올림 단위(천만원?)는 **미결** (§8, blocking).
- `non_renewal_old_list`/`renewal_old_list` 10칸 → **연속 보장구간 막대는 FE 도출** (foliio 2026-06 원칙, BE 무변경).

---

## 4. (b) 히트맵 — 담보 충족 그리드 API

**`GET /customer/:id/heatmap/`**

| 속성 | 값 |
|---|---|
| 권한 | 본인(IsAuthenticated) 또는 `share_token` |
| 구현 | 신규 얇은 레이어 `customers/heatmap.py` (✦) |
| 입력 | `calculate_total_analysis`의 `chart_list[].actual_amount` vs `AnalysisDetail.chart_based_amount` |
| 권위 | status 판정·임계 0.7·neutral/graded 플립 = **전부 BE 단일 진실 원천**. FE는 status 문자열→CSS클래스 매핑만 |
| 크레딧 | 무차감 |

### 4.1 요청

```
GET /api/v1/customer/1024/heatmap/
  (본인: Authorization: Token <…> / 공유: ?token=<share_token>)
```

### 4.2 응답 200

```json
{
  "baseline_source": null,
  "mode": "neutral",
  "computed_at": "2026-06-19T09:12:00+09:00",
  "categories": [
    {
      "category": "진단비-암",
      "insurance_type": 1,
      "details": [
        {
          "detail": "일반암진단비",
          "detail_id": 41,
          "actual_amount": 30000000,
          "std_baseline": 50000000,
          "status": "short"
        },
        {
          "detail": "고액암진단비",
          "detail_id": 42,
          "actual_amount": 0,
          "std_baseline": 30000000,
          "status": "none"
        }
      ]
    }
  ]
}
```

### 4.3 필드 타입 표

| 필드 | 타입 | 비고 |
|---|---|---|
| `baseline_source` | string\|null | 기준선 출처. **`null`이면 강제 `neutral`** (Q1 미확정) |
| `mode` | enum | `neutral` \| `graded` |
| `computed_at` | string | 런타임 계산 시각 (캐시 도입 시 hook) |
| `categories[].category` | string | 15+ 카테고리 |
| `categories[].insurance_type` | int | 1=생명/2=손해 |
| `details[].detail` | string | 100+ 세부담보명 |
| `details[].detail_id` | int | AnalysisDetail FK |
| `details[].actual_amount` | int | 실제 보장액 (chart_list 출처) |
| `details[].std_baseline` | int | `chart_based_amount` |
| `details[].status` | enum | `none`\|`short`\|`enough`\|`neutral` |

### 4.4 `heatmap_status()` 판정 계약 (BE 권위)

```
heatmap_status(actual, std_baseline, mode) -> status:
  if mode == "neutral":
      return "none"  if actual == 0  else  "neutral"   # 회색만, 단정 보류
  # graded (Q1 확정 후):
  if actual == 0:                  return "none"        # 없음  #ADB5BD
  if actual < std_baseline * 0.7:  return "short"       # 부족  #F59E0B
  return "enough"                                       # 충분  #3B5BDB
```

**상태 ↔ 색 매핑** (FE는 문자열→클래스만):

| status | 색 (CSS 변수) | hex | 이중인코딩 (색각 대응) |
|---|---|---|---|
| `enough` | `--cov-enough` | `#3B5BDB` 인디고 | 연한 틴트 채움 |
| `short` | `--cov-short` | `#F59E0B` amber | 좌측 4px 바 |
| `none` | `--cov-none` | `#ADB5BD` 회색 | 점선 보더 |
| `neutral` | gray-050 | — | 점선 `—` |

> ★`baseline_source=null` → 무조건 `mode=neutral` 강제. graded 플립은 Q1(법무) 확정 후 **BE 1곳만** 바꾸면 전체 전환. FE 재배포 불필요.

---

## 5. 데이터 모델

### 5.1 담보 분류 트리 (4계층, ♻ 모델 무변경 + 시드 30→100+)

foliio `insurances/models.py`의 기존 4계층을 그대로 쓴다. **새 `StandardCoverage` 테이블을 만들지 않는다** — calculate.py 8케이스 엔진이 이 4계층을 입력으로 받으므로 단절되면 안 됨.

```
AnalysisCategory  (대분류: 진단비/입원비/수술비/사망/실손/배상 … 15+)
   └─ AnalysisSubCategory  (중분류: 진단비-암 / 진단비-뇌 / 진단비-심장 …)
        └─ AnalysisDetail   (세부담보: 일반암진단비/고액암진단비 … 100+)
             │  + chart_based_amount  ← ★히트맵 기준선 hook (std_baseline)
             └─ ChartDetail   (차트 매핑)
```

- `chart_based_amount` = 히트맵 `std_baseline` + 공유뷰 `chart_based_amount`의 **단일 출처**.
- 시드: `seed_taxonomy` 명령으로 30 → 100+ 확장 (Sprint1, 모든 분석의 입력).

### 5.2 NormalizationDict — 정규화 사전 (✦ 신규, 해자)

```
NormalizationDict
  std_detail    FK(AnalysisDetail, CASCADE, related_name='aliases')
  company       SmallInt          # 보험사 코드 (생손보 통합 enum, §6)
  raw_name      CharField(120, db_index)
  source        SmallInt          # 1=seed / 2=ocr_learned / 3=admin_verified
  confidence    SmallInt  default=100
  verified_by   FK(User, SET_NULL, null)
  hit_count     Int       default=0    # 매칭 시 ++ (복리 카운터)

  Meta:
    UniqueConstraint(['company','raw_name'], name='uniq_norm_company_rawname')
    Index(['raw_name'])
```

- **UNIQUE(company, raw_name)** — 같은 보험사 같은 원문은 한 매핑만.
- 베타 정책: **`source='admin_verified'`만 매칭** (오매핑 0 보장). `ocr_learned` 자동승격 임계(hit_count≥N)는 운영 미결.
- `hit_count` 복리 — 자주 쓰이는 매핑이 강해지는 학습 신호.

### 5.3 UnmatchedLog — 학습 루프 (✦ 신규)

```
UnmatchedLog
  company      SmallInt
  raw_name     CharField(120, db_index)
  occurrence   Int          # 누적 (같은 미매칭 반복 시 ++)
  sample_ctx   TextField    # OCR 원문 맥락 일부
  resolved     Bool default=False
  created_at   DateTime
```

**학습 루프**:
```
OCR miss → UnmatchedLog.update_or_create(occurrence++)
  → admin 대시보드에서 1탭 매핑
  → NormalizationDict(source='admin_verified') 영구 추가
  → 다음 OCR부터 3.5순위에서 자동 hit
  → resolved=True
```

### 5.4 NorthStarEvent — 북극성 계측 (✦ 신규, ★Day1 동결)

> ★레드라인: 이 모델은 **첫 마이그레이션에 박혀야** 한다. 나중에 붙이면 귀속이 영구 깨진다 (사후복원 불가).

```
NorthStarEvent
  event_type    SmallInt    # 1~6 (아래 6종 동결)
  share_token   UUID(db_index, null)     # 귀속 키
  sender_user   FK(User, SET_NULL, null) # 발송 설계사
  ref_code      CharField(null)          # ?ref=<설계사코드> 귀속
  channel       CharField(null)          # kakao / link / sms
  viewer_fp     CharField(null)          # 비식별 fingerprint (열람자, 분모 오염 방지)
  meta          JSONField(default=dict)  # utm_*, referrer …
  created_at    DateTime(auto_now_add, db_index)
```

**이벤트 6종 (Sprint0 동결 — 사후복원 불가)**:

| # | event_type | 발화 지점 | 곱셈 항 | 신뢰도 |
|---|---|---|---|---|
| 1 | `ocr_upload` | detect 진입 | (입력) | 보조 |
| 2 | `analysis_complete` | 분석 화면 진입 완료 | (생성) | 보조 |
| 3 | `share_link_create` | 공유링크 발급 | **발송** | 보조 |
| 4 | `share_clipboard_copy` | 클립보드 복사 | 발송 프록시 | **복사≠발송, 단정 금지** |
| 5 | `share_view` | `/s/[token]` 진입 (BE 서버측정) | **열람** | ★**신뢰 KPI** |
| 6 | `referral_attributed` | `?ref=` 동반 진입 | **귀속** | ★신뢰 KPI |

- 북극성 = 곱셈형 (발송 × 열람 × 귀속). 첫 슬라이스 성공 정의 = **열람(`share_view`) 단 1건 증명**.
- `share_view`는 **BE 서버측정**(클라 측정 신뢰 불가). `viewer_fp`로 봇·카톡 인앱 프리뷰 중복 카운팅 방지 (분모 오염 방지 규칙은 §8 미결).
- `?ref=<설계사코드>` → `referral_attributed` 동시 적재. **ref_code 발급 체계는 미설계** (§8, 코드 생성·유일성·위변조 방지).

### 5.5 Customer (◑ +1필드)

```
Customer  [foliio 재활용 + 1필드 추가]
  ♻ share_token            UUID (공개 공유 링크)
  ♻ birth_day              CharField (분석 입력)
  ♻ gender                 SmallInt (1=남/2=여, null)
  ♻ total_monthly_premiums computed
  ◑ consent_overseas_at    DateTime(null)   ← ★신규 1필드 (detect 412 게이트 키)
  (예약) share_expires_at  DateTime(null)   ← Q4 만료 자리만 확보
```

- `consent_overseas_at is None` → detect 412. **공유뷰/히트맵은 이 필드와 무관** (무게이트 경로).
- ConsentLog 6요건 풀스택은 P1 — 이번엔 **필드 + 게이트 배선만**.

---

## 6. 정규화 사전 정본 (시드 v0)

### 6.1 보험사 코드 enum (`company` SmallInt — 생손보 통합 번호)

> ⚠ 실제 번호 체계는 청약서·약관 대조로 확정 필요 (§8 blocking). 아래는 형식 예시 (추정).

| code | 보험사 | 구분 |
|---|---|---|
| 11 | 삼성생명 | 생명 |
| 12 | 교보생명 | 생명 |
| 13 | 한화생명 | 생명 |
| 21 | 삼성화재 | 손해 |
| 22 | 현대해상 | 손해 |

### 6.2 표준담보 × 보험사별 raw_name 매핑표 (상위 30담보 중 발췌, 추정)

> 각 보험사가 같은 담보를 다른 이름으로 부른다. 이 표가 정규화의 정본 — `NormalizationDict` seed 행이 된다.

| std_detail (표준) | 삼성생명 | 교보생명 | 한화생명 | 삼성화재 |
|---|---|---|---|---|
| 일반암진단비 | 암진단급여금 | 암진단보험금 | 암진단자금 | 암진단비 |
| 뇌졸중진단비 | 뇌졸중급여금 | 뇌졸중보험금 | 뇌혈관진단자금 | 뇌졸중진단비 |
| 급성심근경색진단비 | 급성심근경색급여금 | 심근경색보험금 | 심근경색진단자금 | 급성심근경색진단비 |
| 질병입원일당 | 질병입원급여금 | 질병입원보험금 | 입원자금 | 질병입원일당 |

명명 패턴 단서 (학습 가속): 삼성생명=**급여금** / 교보=**보험금** / 한화=**자금** / 삼성화재=**진단비·일당**.

### 6.3 학습 루프 (운영 동선)

```
1. OCR이 raw_name 추출 → 3.5순위 lookup miss
2. UnmatchedLog(occurrence++) 적재
3. admin 대시보드: 미매칭 큐 정렬(occurrence 큰 순)
4. admin 1탭: raw_name → std_detail 매핑
5. NormalizationDict(source='admin_verified', verified_by=admin) 영구 추가
6. 다음 OCR부터 자동 hit → hit_count 복리 증가
```
- 베타는 4~5단계 **사람 검증 필수** (admin_verified만 매칭). 자동승격은 운영 미결.
- 이 루프가 인파의 복리 해자 — 쓸수록 정규화 사전이 두꺼워지고 오매핑이 0에 수렴.

---

## 7. foliio 포팅 구체 (등급별)

| 등급 | 대상 | 범위 | 회귀 가드 |
|---|---|---|---|
| **♻ 무변경** | `customers/calculate.py:245 calculate_total_analysis` | 복사+리네임만 | 8케이스 골든 179 passed 불변 |
| ♻ | `insurances/models.py CustomerInsurance.calculate` (numpy_financial.fv) | 복사만 | 동일 |
| ♻ | `test_premium_calculation_8cases.py` | 즉시 이식 → green | **포팅 무결성 게이트** |
| ♻ | `core/utils.py extract_text_from_pdf:358` | 복사만 | — |
| ♻ | `Customer.share_token` 공개뷰 패턴 | 복사만 | — |
| **◑ 부분** | `core/ocr/claude_parser.py:430 claude_parse` | **프롬프트만** (100+ 담보 트리 주입) | 매칭 happy path |
| ◑ | `_add_coverage:700` | 3.5순위 import 1줄 + 4줄 삽입 | normalization happy + 학습루프 |
| ◑ | `Customer` 모델 | `+consent_overseas_at` 1필드 | — |
| ◑ | `membership/credit.py` | `+kind='ocr'` | 402 shape |
| **✦ 신규** | `insurances/normalization.py` | `lookup()` 함수 | 단위테스트 |
| ✦ | `customers/heatmap.py` | `heatmap_status()` + 그리드 빌드 | status 4상태 전수 (none/short/enough/neutral) |
| ✦ | `NormalizationDict` / `UnmatchedLog` | 신규 모델 + seed | UNIQUE 제약 |
| ✦ | `NorthStarEvent` | 신규 모델 (Day1 마이그레이션) | — |

### 7.1 권한·크레딧 요약

| API | 권한 | 크레딧 |
|---|---|---|
| `POST /insurance/detect/` | IsAuthenticated | `ocr` 차감 (kind='ocr' 경유, 베타 우회) |
| `GET /customer/:id/share/analysis/` | AllowAny + share_token | 무차감 |
| `GET /customer/:id/heatmap/` | IsAuthenticated 또는 share_token | 무차감 |

402 응답 shape (foliio 동일): `{reason:'CREDIT_EXHAUSTED', limit, remaining}` (`remaining=null` = unlimited 센티넬, `0`이 아님).

### 7.2 회귀 가드 체크리스트 (빌드 차단 게이트)

- [ ] 8케이스 골든 179 passed **불변** (포팅 무결성)
- [ ] `heatmap_status` 4상태 전수 단위테스트 (none/short/enough/neutral)
- [ ] normalization happy path + 학습루프 (miss→UnmatchedLog→admin매핑→hit)
- [ ] 음수 guard 보존: `monthly_non_renewal_premium = max(0, assurance − renewal)`
- [ ] OCR 추출률 ≥85% (분모 정의는 §8 미결)
- [ ] 정직성 금지카피 100건 100% 차단 (안전/심의완료/보장)

### 7.3 마이그레이션·시드 순서 (강제)

```
makemigrations
  → migrate
    → seed_taxonomy            (AnalysisCategory~Detail 100+ + NormalizationDict v0)
      → loadinitialmemberships (무료/플러스/프리미엄/슈퍼)
```
- 담보 트리 시드가 **모든 분석의 입력** → 최선행.
- NorthStarEvent는 첫 마이그레이션에 포함 (Day1 박기).

---

## 8. 미결 항목 표 (개발 착수 전 잠가야 함)

| # | 미결 | 영향 | 디폴트/우회 | blocking | owner |
|---|---|---|---|---|---|
| Q1 | `std_baseline` 출처·권위 (금감원/보험연구원/자체+면책) | heatmap graded·insights short/enough 단정 게이트 | **neutral 디폴트** (none만 발화) | ✗ (우회 가능) | PM+개발+법무 |
| — | `chart_based_amount` 100+ 담보별 실제 기준금액 시드값 작성 주체 | 히트맵 기준선 거짓 위험 | — | ✓ | 개발+데이터 |
| Q2 | 국외이전 동의 1탭 vs 풀스택 | detect 전체 412 게이트 | `consent_overseas_at`+412 배선만 | ✓ | 대표 |
| Q4 | `share_token` 만료·회수·noindex | 민감분석 영구노출 사고 | `share_expires_at` 필드 자리만 (응답코드 410? 미정) | ✗ | PM+보안 |
| ★ | 북극성 6종 스키마 동결 (필드·타입·중복제거 키) | 사후복원 불가 — 첫 배포 전 절대조건 | §5.4 동결안 | ✓ | 대표+PM |
| — | 정규화 사전 v0 ~150행 (상위30×5사 청약서 대조) + 보험사 코드 enum | 오매핑=히트맵 전체 거짓=정직성 레드라인 | §6 추정값 | ✓ | 개발+PM+데이터 |
| — | insights 발화 규칙 상세 (우선순위·표기 상한·반올림 단위) | 고객 노출 카피 = 정직성 레드라인 | 천만원 단위 (추정) | ✓ | PM+디자인 |
| — | 정규화 자동승격 임계 (hit_count≥N) | 자동 오매핑=§97 위반 | **admin_verified만** | ✗ | 개발+운영 |
| — | ref_code 발급 체계 (생성·유일성·위변조 방지) | 귀속 정확도 근간 | Day1 스키마만, 로직 미설계 | ✗ | 개발+PM |
| — | ocr 한도 숫자 | 공유뷰 발급 차감 여부 | 베타 90일 실측 (추정) | ✗ | PM |
| — | 공유뷰 PII 노출 범위 (고객명 마스킹 홍**/gender null/병력) | 개인정보 | 마스킹 규칙 미확정 | ✗ | PM+보안+QA |
| — | OCR 추출률 85% 게이트 분모 (7필드 vs 100+, 필드 가중치) | PASS/FAIL 판정 불가 | 측정단위 미정 | ✗ | QA+개발 |

> blocking 5종 (개발 D-0 전제): **북극성 스키마 동결 / 정규화 사전·OCR 골든셋 / insights 카피 규칙 / Q2 국외이전 1탭 / chart_based_amount 시드값**. 이 다섯이 잠기면 detect·히트맵·공유뷰 전부 착수 가능.
