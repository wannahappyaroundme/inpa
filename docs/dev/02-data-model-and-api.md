# 인파(Inpa) — 데이터 모델 & API 설계

> 본 문서는 인파(Inpa)의 백엔드 데이터 모델(DB 스키마)과 주요 API 계약(요청/응답 형태)을 정의한다.
> 모든 설계는 foliio 실코드를 직접 정독해 포팅 지점을 한 줄까지 확인한 위에 작성했다 — 추측이 아니라 검증된 자산 위의 재배치다.
> 검증 참조: `customers/models.py:76` Customer · `customers/calculate.py:245` calculate_total_analysis · `core/ocr/claude_parser.py:430/700` claude_parse/_add_coverage · `membership/credit.py:123` _check_and_consume · `insurances/models.py:53` AnalysisDetail.
> 정량 수치 중 베타 실측 전 가설은 모두 **(추정)** 라벨을 단다.

---

## 0. 한 장 요약 (투자자/디자이너용)

인파의 데이터 설계 한 문장: **"foliio가 이미 검증한 8케이스 보험료 엔진·증권 OCR·공유링크 모델을 그대로 가져오고, 그 위에 단 두 개의 신규 자산 — ① 병력 국외이전 동의를 물리적으로 강제하는 게이트(ConsentLog/consent_overseas_at), ② 쓸수록 두꺼워지는 보험사별 담보명 정규화 사전(NormalizationDict) — 을 얹는다."**

```
   [재활용 ♻ 90%]                    [신규 ✦ 10%]
 ┌────────────────────┐        ┌──────────────────────────┐
 │ Customer            │        │ consent_overseas_at (1필드)│  ← 모든 AI 기능의 물리적 게이트
 │ CustomerInsurance   │        │ ConsentLog (감사추적)      │
 │ AnalysisDetail 4계층 │  ─┐    │ NormalizationDict (해자)   │  ← 데이터 복리 플라이휠
 │ calculate.py 8케이스 │   ├──► │ unmatched_log (학습루프)   │
 │ share_token 공유뷰   │  ─┘    │ heatmap status (3색)       │
 │ credit.py 크레딧     │        │ ai_credit kind             │
 └────────────────────┘        └──────────────────────────┘
   포팅 비용 0                       신규 의존성 0개
```

핵심: **데이터 모델 신규 = 사실상 NormalizationDict 1개 + 동의 로그 2개뿐.** 나머지는 전부 foliio 자산의 재활용·시드 확장이다. 이것이 "foliio 코드 90% 재활용"의 물리적 근거다.

---

## 1. 모델 전체 지도

| 모델 | 출처 | 등급 | 역할 | 인파 변경점 |
|---|---|---|---|---|
| `Customer` | foliio `customers/models.py:76` | ◑ | 고객 마스터 (생년/성별/직업위험등급/연락처/병력/공유토큰) | **`consent_overseas_at` 1필드 추가** |
| `JobRiskCode` | foliio | ♻ | 직업 위험등급 코드 (메리츠 분류) | 무변경 |
| `CustomerMedicalHistory` | foliio | ♻ | 고객 병력 (민감정보 — 국외이전 동의 대상) | 무변경 |
| `CustomerInsurance` | foliio `insurances/models.py:194` | ♻ | 가입/제안 보험 (8케이스 계산 주체) | 무변경 |
| `CustomerInsuranceDetail` | foliio | ♻ | 담보별 케이스 (`calculate()` numpy_financial.fv) | 무변경 |
| `AnalysisCategory/SubCategory/Detail` | foliio `insurances/models.py:12~53` | ♻+시드 | 담보 분류 트리 4계층 (표준 틀) | **시드 30 → 100+ 담보 확장** |
| `ChartDetail` | foliio `insurances/models.py:67` | ♻ | 차트 기준 금액(`chart_based_amount`) | 무변경 (히트맵 기준선 hook) |
| `Membership / UserMembership` | foliio `membership/` | ◑ | 4티어 + 월 크레딧 | **`ai_credit` kind 추가** |
| `NormalizationDict` | — | ✦ **신규** | 보험사별 담보명 → 표준담보 정규화 사전 | 데이터 복리 해자 |
| `UnmatchedLog` | — | ✦ **신규** | OCR 미매칭 raw_name 적재 → admin 매핑 루프 | 학습 플라이휠 |
| `ConsentLog` | — | ✦ **신규** | 국외이전 동의 감사추적 (누가·언제·범위·버전·IP) | 법무 게이트 |
| `Notification` | foliio `accounts/` | ♻ | 인앱/이메일 알림 (워치독 신규 type) | type만 확장 |

---

## 2. Customer 모델 (◑ 개조 — 1필드 추가)

foliio `Customer`(`customers/models.py:76`)는 인파가 필요로 하는 필드를 **이미 전부 보유**한다. 신규 동의 게이트 필드 **1개**만 추가한다.

### 2.1 재활용 필드 (♻ 무변경)

| 필드 | 타입 | 용도 (인파) |
|---|---|---|
| `name` | CharField(20) | 고객명 |
| `mobile_phone_number` | CharField(15) | 연락처 (액션큐 원클릭 발신) |
| `birth_day` | CharField(10) | 생년 — `calculate_total_analysis(birth_day, ...)` 나이별 막대 입력 |
| `gender` | SmallInt (1=남/2=여, null) | 성별 — 분석/요약 표 표기 |
| `job_code` | FK `JobRiskCode` (SET_NULL) | 직업 위험등급(1~3급) — 손해보험 진단 |
| `medical_histories` | reverse FK `CustomerMedicalHistory` | **병력 = 민감정보 = 국외이전 동의 대상** |
| `share_token` | UUIDField (unique) | 공개 공유링크 — 북극성 열람 계측의 키 |
| `share_expires_at` | DateTimeField (null) | 공유 만료 (Q4 회수 정책 hook) |
| `user_view_at` | DateTimeField (null) | 고객 열람 시각 — 액션큐 "미열람" 신호 |
| `is_agree_term` | BooleanField | **기존 일반 동의 (≠ 국외이전 동의)** |
| `color` | CharField(10) | 색상 마커 (액션큐 분류) |
| `memo` | TextField | 설계사 메모 |

### 2.2 신규 필드 (✦ — 국외이전 동의 게이트)

```python
class Customer(models.Model):
    # ... foliio 기존 필드 전부 ...

    # ✦ 인파 신규: 병력(민감정보) Claude API(미국, Anthropic Inc.) 국외이전 동의 시각
    #   null = 미동의. detect API 호출 전 이 값을 확인 → null이면 412 게이트.
    #   is_agree_term(일반 동의)과 의도적으로 분리 — 법무 Q2 낙관 가정 금지 전제.
    consent_overseas_at = models.DateTimeField(
        '국외이전 동의 시각', default=None, null=True, blank=True
    )
```

> **설계 레드라인:** `is_agree_term` 한 필드로 국외이전까지 덮지 않는다. 병력은 개인정보보호법상 민감정보이고 Claude API는 미국(Anthropic, Inc.)으로 나간다. 동의 *시각·범위·문서버전·IP* 를 별도로 남기지 않으면 detect API 자체를 열 수 없다 — 이것이 `consent_overseas_at`(필드) + `ConsentLog`(로그) 2층 분리의 이유다. **(법무 선결 Q2 — 1탭 동의서 vs 별도 동의서 확정이 detect 출시 게이트.)**

---

## 3. ConsentLog 모델 (✦ 신규 — 감사추적)

`consent_overseas_at`은 "지금 동의 상태인가"의 스냅샷, `ConsentLog`는 "언제·어떤 버전·누가·어디서"의 불변 감사 로그다. 둘은 역할이 다르며 둘 다 필요하다.

```python
class ConsentLog(models.Model):
    CONSENT_TYPE = ((1, 'overseas'), (2, 'selfdiag'), (3, 'marketing'))

    customer    = models.ForeignKey(Customer, on_delete=models.CASCADE,
                                    related_name='consent_logs')
    consent_type = models.SmallIntegerField(choices=CONSENT_TYPE)  # overseas = AI 게이트
    agreed_at   = models.DateTimeField(auto_now_add=True)
    doc_version = models.CharField(max_length=20)   # 동의서 개정 버전 (예: "v1.0-2026Q3")
    ip          = models.GenericIPAddressField(null=True)
    scope       = models.CharField(max_length=200, default='')  # 이전 범위 (병력/진단명 등)
    revoked_at  = models.DateTimeField(default=None, null=True, blank=True)  # 철회
```

체크리스트 — ConsentLog가 충족해야 할 법무 요건:
- [ ] **누가**: `customer` FK (정보주체 식별)
- [ ] **언제**: `agreed_at` (불변)
- [ ] **무엇을**: `scope` (이전 정보 범위)
- [ ] **어느 버전 동의서**: `doc_version` (동의서 개정 시 추적)
- [ ] **어디서**: `ip` (동의 출처)
- [ ] **철회 가능성**: `revoked_at` (개인정보 권리)

> 셀프진단(지인 제3자) 동선은 `consent_type=2 (selfdiag)` — 정보주체 본인이 1탭 동의하는 별도 동선이 필요하다. **(컴플라이언스 Q4 미결: 제3자 동의 1탭 법적 충분성.)**

---

## 4. 담보 분류 트리 (♻ 4계층 재활용 + 시드 100+ 확장)

### 4.1 모델 구조 — foliio 4계층 그대로

foliio는 이미 담보 분류를 4계층 관계형 모델로 보유한다(`insurances/models.py:12~85`). **모델은 무변경, 시드 데이터만 30 → 100+ 로 확장**한다.

```
AnalysisCategory      (대분류 15+)   insurance_type(1생명/2손해)
   └─ AnalysisSubCategory (중분류)
        └─ AnalysisDetail (세부담보 leaf 100+)   chart_based_amount ← 히트맵 기준선 hook
             └─ ChartDetail (차트 표시 단위)      chart_based_amount
```

> `AnalysisDetail.chart_based_amount`(`insurances/models.py:57`)가 **표준 보장 기준선의 물리적 저장 위치**다. 히트맵 3색 판정(§7.4)의 `std_baseline`이 여기서 나온다. 단 이 값의 *권위·출처*는 코드가 아니라 법무가 정한다 **(법무 선결 Q1).**

### 4.2 트리 — 15+ 대분류 / 100+ 세부담보

전체 정의는 `06-coverage-taxonomy-reference.md` §2·§3이 정본. 요약하면:

```
[생명 + 손해 통합 표준 틀]

사망          ├ 일반사망 · 재해사망 · 교통재해사망 · 질병사망 · 정기사망
진단비-암      ├ 일반암 · 소액암 · 고액암 · 상피내암 · 유사암(갑상선 등)
진단비-뇌      ├ 뇌졸중 · 뇌출혈 · 뇌경색 · 일과성허혈(TIA)
진단비-심장    ├ 급성심근경색 · 허혈성심장질환
진단비-중증희귀 ├ CI(중대질병) · 희귀난치
후유장해       ├ 상해후유장해 · 질병후유장해
수술비         ├ 1~5종수술 · 암수술 · 뇌수술 · 심장수술
입원비         ├ 상해입원 · 질병입원 · 중환자실(ICU)
실손(급여)     ├ 질병입원 · 질병통원 · 질병처방 · 상해입원 · 상해통원 · 상해처방
실손(비급여)   ├ 도수치료 · MRI · 비급여주사
운전자         ├ 형사합의금 · 벌금 · 변호사선임
일상생활배상    ├ 일배책(가족일상생활배상)
간병/치매      ├ 장기간병(LTC) · 중증치매
재물/기타      ├ 화상 · 골절 · 깁스 · 3대질병통합 · 만기환급/적립
```

> `insurance_type`(1=생명/2=손해)으로 생손보를 분리 관리한다 — 메모리 `project_market_structure`의 "생명 vs 손해 분리" 원칙 반영. 손해보험 override(일반사망/재해사망)는 `insurance_type==1`로 게이트 (foliio post-v1.6 fix 그대로).

### 4.3 시드 명령

```bash
python manage.py seed_taxonomy   # AnalysisCategory/Detail 100+ + NormalizationDict 부트스트랩
```

---

## 5. 보험사별 담보명 정규화 사전 (✦ 신규 — 데이터 복리 해자)

### 5.1 왜 필요한가 — 분석/OCR의 심장

같은 담보라도 보험사마다 이름이 다르다. OCR이 추출한 `raw_name`을 우리 표준 담보(`AnalysisDetail`)에 못 붙이면 히트맵·비교안내서가 전부 무너진다.

| 표준 담보 (인파 틀) | 삼성생명 | 교보생명 | 한화생명 | 삼성화재 |
|---|---|---|---|---|
| 일반암진단비 | 암진단**급부금** | 암진단**보험금** | 암진단자금 | 암진단비(일반암) |
| 뇌졸중진단비 | 뇌졸중진단급부금 | 뇌졸중진단보험금 | 뇌졸중자금 | 뇌혈관질환진단비 |
| 급성심근경색진단비 | 급성심근경색급부금 | AMI진단보험금 | 심근경색자금 | 허혈성심장질환진단비 |

> 범용 AI(ChatGPT)는 이 사전을 갖지 못한다. **쓸수록 두꺼워지는 정규화 사전이 모방 불가능한 데이터 복리 해자**다 — 해자 3종 중 ②.

### 5.2 NormalizationDict 모델

```python
class NormalizationDict(models.Model):
    SOURCE = (
        (1, 'seed'),           # seed_taxonomy 부트스트랩
        (2, 'ocr_learned'),    # OCR 자동학습 (admin 미검수)
        (3, 'admin_verified'), # admin 1탭 검수 완료
    )

    std_detail  = models.ForeignKey('AnalysisDetail', on_delete=models.CASCADE,
                                    related_name='aliases')   # 표준 담보 (우리 틀의 leaf)
    company     = models.SmallIntegerField()          # 보험사 코드 (삼성생명/교보/한화/삼성화재...)
    raw_name    = models.CharField(max_length=120, db_index=True)  # "암진단급부금"
    source      = models.SmallIntegerField(choices=SOURCE, default=1)
    confidence  = models.SmallIntegerField(default=100)   # 자동학습 신뢰도(0~100)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, blank=True)  # admin 검수자
    hit_count   = models.IntegerField(default=0)          # ★ 매칭될 때마다 ++ (데이터 복리)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['company', 'raw_name'],
                                    name='uniq_norm_company_rawname')
        ]
        indexes = [models.Index(fields=['raw_name'])]
```

### 5.3 데이터 복리 학습 루프

```
[OCR detect] raw_name="암진단급부금"
      │
      ▼
NormalizationDict.get(company=삼성생명, raw_name)
      │
   ┌──┴── 매칭 O ──► std_detail 연결 + hit_count += 1  ──► 분석 진행
   │
   └── 매칭 X ──► UnmatchedLog 적재
                       │
                       ▼
              [admin 1탭 매핑 UI] raw_name → AnalysisDetail 선택
                       │
                       ▼
              NormalizationDict 영구 추가 (source=admin_verified)
                       │
                       ▼
              ★ 다음 OCR부터 자동 매칭 — 사전이 두꺼워짐 (복리)
```

```python
class UnmatchedLog(models.Model):
    company    = models.SmallIntegerField()
    raw_name   = models.CharField(max_length=120, db_index=True)
    occurrence = models.IntegerField(default=1)   # 같은 raw_name 누적 빈도
    sample_ctx = models.CharField(max_length=300, default='')  # OCR 주변 텍스트
    resolved   = models.BooleanField(default=False)  # admin 매핑 완료 여부
    created_at = models.DateTimeField(auto_now_add=True)
```

> **미결(운영 Q):** `hit_count`/`occurrence` 임계(예: 동일 raw_name 5회+ admin 검수 없이 `ocr_learned` → 자동 승격) 허용 여부. 자동매핑 오류 = 비교안내서 거짓 = §97 위반 리스크. 정확도 vs 운영비용 트레이드오프 — 운영 주체·검수 UI 미정. 베타까지는 **`admin_verified`만 매칭에 사용**(보수적 기본값).

---

## 6. 보험·계산 모델 (♻ 무변경 — 8케이스 엔진)

`CustomerInsurance`(`insurances/models.py:194`) + `CustomerInsuranceDetail` + `calculate.py`는 **한 줄도 건드리지 않는다.** foliio 8케이스 골든테스트(`test_premium_calculation_8cases.py`)를 그대로 회귀 가드로 가져온다.

| 필드 | 값 | 인파 용도 |
|---|---|---|
| `portfolio_type` | 0=템플릿/1=기존가입/2=제안 | 갈아타기 비교의 좌(1)·우(2) 분기 |
| `insurance_type` | 1=생명/2=손해 | 생손보 분리 계산 |
| `monthly_{premiums,assurance,renewal,non_renewal,earned}_premium` | — | 비용요약 표 |
| `case_list` → `CustomerInsuranceDetail` | `calculate()` (numpy_financial.fv) | 케이스별 미래가치 |

> **음수 guard 보존:** `monthly_non_renewal_premium = max(0, assurance − renewal)` (foliio 2026-05-29 fix) 그대로. **8케이스 변경 시 골든테스트 재실행** 원칙 인파에도 동일 적용.

---

## 7. 주요 API 계약

엔드포인트 출처: `insurances/views.py:detect` + `customers/views.py:analysis/compare` 재활용 + 신규 heatmap/guardrail/message. base path `/api/v1/`.

### 7.0 API 지도

| Method · Path | 출처 | 등급 | credit | 게이트 |
|---|---|---|---|---|
| `POST /insurance/detect/` | foliio detect | ◑ | `ai_credit`(=insurance) | **국외이전 미동의 412** |
| `POST /insurance/detect_batch/` | — | ✦ | N×`ai_credit` | 동의 412 / 부분실패 허용 |
| `GET /customer/:id/analysis/` | foliio | ♻ | — | 본인/공유토큰 |
| `GET /customer/:id/heatmap/` | — | ✦ | — | 기준선 미확정 시 neutral |
| `GET /customer/:id/compare/` | foliio + ◑ | ◑ | — | **§97 6항목 미완 시 발행 하드블록** |
| `POST /ai/message/` | — | ✦ | `ai_credit` | 클립보드만 (자동발송 X) |
| `POST /ai/guardrail_check/` | — | ✦ | — | 보험업법 룰셋 판정 |
| `GET /customer/:id/share/analysis/?token=&ref=` | foliio | ♻ | — | **열람 이벤트 계측 (북극성)** |

---

### 7.1 `POST /insurance/detect/` — 증권 업로드 → OCR (◑ + 국외이전 게이트)

증권 PDF 업로드 → 텍스트 추출 → Claude 파싱 → **정규화 사전 결합** → 표준담보 매핑.
파이프라인: `extract_text_from_pdf`(`utils.py:358`, pdfplumber→PyMuPDF 폴백, 암호화 `authenticate`) → 한화 fast-path → `claude_parse`(`claude_parser.py:430`) → regex fallback.

**Request** (multipart):
```
POST /api/v1/insurance/detect/
  customer_id: 123
  file: <증권.pdf>
  password: "******"        # 암호화 PDF (선택)
  is_proposal: false        # true=제안서(미래 보험료)
```

**게이트 (호출 진입 시점):**
```python
if customer.consent_overseas_at is None:
    return Response(status=412, data={
        "reason": "CONSENT_OVERSEAS_REQUIRED",
        "consent_url": f"/check/{customer.share_token}",
    })
```

**Response 200** (정규화 적용된 표준담보):
```json
{
  "insurance_company": "삼성생명",
  "product_name": "삼성생명 종합보장보험",
  "insurance_type": 1,
  "coverages": [
    {
      "raw_name": "암진단급부금",
      "std_detail_id": 41,
      "std_detail_name": "일반암진단비",
      "match_source": "admin_verified",
      "assurance_amount": 30000000,
      "monthly_premium": 12000,
      "payment_type": 1,
      "warranty_type": 2
    }
  ],
  "unmatched": [
    { "raw_name": "특정고도질병진단비", "logged": true }
  ]
}
```

체크리스트 — detect 응답 계약:
- [ ] 매칭된 담보는 `std_detail_id` + `match_source` 동반 (정규화 사전 경유 명시)
- [ ] 미매칭은 `unmatched[]` + `UnmatchedLog` 적재 (학습루프)
- [ ] OCR 7필드 추출률 ≥ 85% (가드레일 지표) — 7 → 100+ 필드로 확장
- [ ] `ai_credit` 차감 (베타 `FREE_TIER_UNLIMITED=True` 우회)

---

### 7.2 `POST /insurance/detect_batch/` — 다건 일괄 OCR (✦ 신규 M1)

증권 N장 일괄 큐잉, **부분 실패 허용**. 야간 배치는 Claude Batches API(50% 할인) 경로.

**Request**: `customer_id`, `files[]: [<a.pdf>, <b.pdf>, ...]`
**Response 207** (Multi-Status):
```json
{
  "succeeded": [ { "file": "a.pdf", "insurance_id": 501, "coverages": 12 } ],
  "partial_failed": [
    { "file": "b.pdf", "reason": "PDF_ENCRYPTED_NO_PASSWORD" },
    { "file": "c.pdf", "reason": "OCR_LOW_CONFIDENCE", "extracted": 3 }
  ]
}
```

> **원칙:** 한 장 실패가 전체를 죽이지 않는다(`partial_failed[]`). 외부 API rule(부분 실패 OK, 실패 항목만 로그) 준수.

---

### 7.3 `GET /customer/:id/analysis/` — 분석 집계 (♻ 무변경)

`calculate_total_analysis(birth_day, case_list, chart_list, insurance_list)`(`calculate.py:245`) 출력을 **그대로** 반환. BE 무변경.

**Response 200** (검증된 출력 구조):
```json
{
  "monthly_premiums": 152000,
  "monthly_renewal_premium": 38000,
  "monthly_non_renewal_premium": 102000,
  "monthly_earned_premium": 12000,
  "total_premiums": 48700000,
  "total_renewal_premium": 9200000,
  "total_non_renewal_premium": 33000000,
  "total_earned_premium": 6500000,
  "total_cancellation_refund": 0,
  "total_cancellation_loss": 0,
  "case_list": [
    {
      "name": "일반암진단비",
      "total_premium": 30000000,
      "total_renewal_premium": 0,
      "total_non_renewal_premium": 30000000,
      "non_renewal_old_list": [0,0,30000000,30000000,30000000,30000000,0,0,0,0],
      "renewal_old_list":     [0,0,0,0,0,0,0,0,0,0],
      "is_show_old_price": true
    }
  ],
  "chart_list": [
    { "name": "암", "chart_based_amount": 30000000 }
  ]
}
```

> `non_renewal_old_list`/`renewal_old_list`는 **항상 10칸 고정**(`calculate.py:268`). 연속 보장구간(0원=회색 단일 / 보장=연속 막대) 도출은 **FE에서**(foliio 2026-06 원칙) — BE 무변경.

---

### 7.4 `GET /customer/:id/heatmap/` — 담보 한눈표 3색 (✦ 신규 M3)

15+ 카테고리 × 세부담보 그리드를 충분/부족/없음 3색으로. `analysis`의 실제 보장액 vs 표준 기준선(`AnalysisDetail.chart_based_amount`) 비교.

**Response 200**:
```json
{
  "baseline_source": null,             // 출처 미확정 → 중립 모드 (Q1)
  "mode": "neutral",                   // "neutral" | "graded"
  "categories": [
    {
      "category": "진단비-암",
      "details": [
        { "detail": "일반암진단비", "actual_amount": 30000000,
          "std_baseline": 50000000, "status": "short" },
        { "detail": "고액암진단비", "actual_amount": 0,
          "std_baseline": 30000000, "status": "none" }
      ]
    }
  ]
}
```

**status 판정 로직 (신규):**
```python
def heatmap_status(actual, std_baseline, mode):
    if mode == "neutral":                    # 기준선 출처 미확정 (Q1 게이트)
        return "none" if actual == 0 else "neutral"   # 보유여부(0원)만 회색 표기
    # graded 모드 (Q1 확정 후):
    if actual == 0:                  return "none"     # 🔴 없음
    if actual < std_baseline * 0.7:  return "short"    # 🟡 부족
    return "enough"                                    # 🟢 충분
```

> **중립 모드 = 출시 안전장치.** 표준 기준선의 출처·권위(금감원/보험연구원/자체+면책)가 확정되기 전(**법무 Q1**)까지 `enough/short` 판정을 **보류**하고 `none`(0원 보유여부)만 회색 중립으로 표기한다. 임계값 코드(`*0.7`)는 미리 짜두되 데이터 권위 확정 시 `mode="graded"`로 플립. UI는 출처주석(ⓘ) 자리만 확보.

---

### 7.5 `GET /customer/:id/compare/` — 갈아타기 비교안내서 (♻ + ◑ §97)

foliio 기존가입(`portfolio_type=1`) vs 제안(`portfolio_type=2`) 매트릭스에 **§97 비교안내 정확요건 필드**를 결합.

**Response 200** (§97 필드 추가):
```json
{
  "existing": { "monthly_premiums": 152000, "case_list": [ ... ] },
  "proposal": { "monthly_premiums": 138000, "case_list": [ ... ] },
  "switch_warnings": [
    { "type": "cancellation_loss", "label": "해지환급금 손실", "amount": 1200000 },
    { "type": "exemption_reset",   "label": "면책기간 리셋",   "detail": "암 90일 재적용" },
    { "type": "rate_change",       "label": "예정이율 하락",   "from": 2.5, "to": 1.8 },
    { "type": "renewal_conversion","label": "비갱신→갱신 전환" }
  ],
  "compliance_checklist": {
    "items_required": 6,
    "items_completed": 4,
    "publishable": false                // ★ 6항목 미완 → 발행 하드블록
  },
  "disclaimer": "AI 1차 보조, 최종책임 설계사"
}
```

> **§97 하드블록:** `compliance_checklist.publishable == false`면 비교안내서 **발행 불가**(필수 6항목 누락률 = 0% 강제). 불리점(해지손실/면책리셋/예정이율/갱신전환)은 자동 경고로 상시 노출. "안전배지" 절대 금지, 면책 카피만. **(법무 Q3 — 6항목 법적 확정 내용이 하드블록 룰 근거.)**

---

### 7.6 `POST /ai/message/` — AI 카톡 메시지 (✦ 신규 M6, 클립보드만)

목적 enum 칩 선택 → Claude 생성 → `ai_guardrail` 후처리 → **클립보드 복사만**(자동발송 사칭 금지).

**Request**:
```json
{ "customer_id": 123, "purpose": "renewal", "tone": "friendly" }
```
`purpose ∈ {needs(니즈환기), renewal(만기), birthday(생일), gap(공백), referral(소개), remind(리마인드)}`

**Response 200**:
```json
{
  "message": "○○님, 가입하신 암보험 만기가 D-30 남았어요...",
  "guardrail": { "passed": true, "flags": [] },
  "delivery": "clipboard"            // ★ 자동발송 아님 — 복사 후 설계사가 직접 전송
}
```

> 정직성 레드라인: `delivery`는 항상 `clipboard`. 원탭 자동발송 사칭 금지. 복사 클릭은 **발송 프록시 보조지표**로만 계측, 신뢰 KPI는 `share_view`(서버 측정).

---

### 7.7 `POST /ai/guardrail_check/` — 보험업법 룰셋 판정 (✦ 신규 M5)

foliio `content_filter.py`(PII 정규식) 패턴을 재사용해 `ai_guardrail.py`로 보험업법 룰셋 신규.

**Response 200**:
```json
{
  "passed": false,
  "flags": [
    { "rule": "guarantee_return", "match": "수익 보장", "severity": "block" },
    { "rule": "absolute_term",    "match": "무조건",    "severity": "warn" },
    { "rule": "compare_exaggerate", "match": "최고",    "severity": "warn" }
  ]
}
```
룰: 단정표현 / 수익보장 / 비교과장 플래그 → 생성물 후처리. `severity=block`이면 메시지·비교안내서 출력 차단.

---

### 7.8 `GET /customer/:id/share/analysis/?token=&ref=` — 공유 열람 + 계측 (♻ + 계측)

foliio 공유뷰(글로벌헤더 숨김 패턴) 재활용 + **북극성 열람 이벤트 계측 + 리퍼럴 귀속**.

**Request**: `?token=<share_token>&ref=<설계사코드>`
**동작**:
- 공개 열람 (인증 불필요, `share_token` 검증)
- `share_view` 이벤트 적재 (서버 측정 = 신뢰 KPI)
- `?ref=` 존재 시 `referral_attributed` 귀속 (**계측 인프라 Day1, 캠페인 활성화 Phase2**)

> 귀속 계측은 **사후 복원 불가** → 첫 배포 전 이벤트 스펙 확정 필수. 이벤트: `ocr_upload / analysis_complete / share_link_create / share_clipboard_copy / share_view / referral_attributed`.

---

## 8. 크레딧 모델 (◑ — ai_credit kind 추가)

foliio `credit.py:123 _check_and_consume(user, kind)`는 `kind ∈ {customer, insurance, promotion}`을 지원. 인파는 **`ai_credit`(AI 호출 차감)을 추가**한다 — 무료 라인 "분석은 풀고 행동은 막는다"의 물리적 집행점.

| 동작 | credit kind | 무료(Basic) | Plus+ |
|---|---|---|---|
| 증권 OCR 등록 | `insurance` | 허용 | 허용 |
| 분석/히트맵 조회 | — (무차감) | 허용 | 허용 |
| 비교안내서 **생성** | `ai_credit` | **1건 체험** | 복수 |
| 비교안내서 **발송/복수** | `ai_credit` | ✗ | 허용 |
| AI 메시지 생성 | `ai_credit` | ✗ | 허용 |

**402 응답 shape** (`credit.py:155` 실제 구조 기반):
```json
{
  "detail": "이번 달 AI 한도(N건)를 모두 사용했어요.",
  "code": "credit_exhausted",
  "kind": "ai",
  "membership": "Basic",
  "limit": 1,
  "used": 1
}
```
→ FE는 `UpgradeGuideModal` 표시. 베타 기간 `FREE_TIER_UNLIMITED=True`로 전부 우회, 정식 출시 시 `False` flip.

> 정확한 한도 숫자(월 N건)는 **베타 90일 실측 후 토큰화** — 전부 **(추정)** 라벨 유지. `monthly_*_credit=0`은 **무제한 sentinel**(Super + 베타), `∞`로 표시. `remaining==0`이 아니라 `is_unlimited`로 판별.

---

## 9. Notification & Cron (♻ + 워치독 신규 type)

foliio `Notification` + cron 패턴(`expirememberships`/`notifymembership`/`resetmonthlycredit`/`process_dormancy`) 재활용. 인파 신규:

| 신규 | 종류 | 트리거 |
|---|---|---|
| `Notification` type | `policy_expiring`(만기 D-30) / `consent_pending`(동의 미수신) / `referral_attributed` | 액션큐 피드 |
| cron command | `watchdog`(✦ M4 후행, Phase1.5) | 만기·갱신·생일 일배치 → 액션큐 |
| cron command | `resetmonthlycredit` (♻) | 월 1일 `ai_credit_used` 리셋 |

---

## 10. 마이그레이션 & 시드 순서

```bash
# 1. 모델 마이그레이션 (로컬: settings.local 필수)
DJANGO_SETTINGS_MODULE=config.settings.local python manage.py makemigrations
DJANGO_SETTINGS_MODULE=config.settings.local python manage.py migrate

# 2. 담보 트리 + 정규화 사전 시드 (30 → 100+)
python manage.py seed_taxonomy

# 3. 멤버십 4티어 시드 (foliio 재활용)
python manage.py loadinitialmemberships
```

체크리스트 — 데이터 모델 PR 완료 정의:
- [ ] `consent_overseas_at` 마이그레이션 + detect 412 게이트 동작
- [ ] `ConsentLog` 6요건 필드 + 감사추적 SELECT 검증
- [ ] `NormalizationDict` UNIQUE(company, raw_name) + `hit_count` 증가 확인
- [ ] `UnmatchedLog` → admin 매핑 → 자동매칭 루프 happy path 테스트
- [ ] `seed_taxonomy` 100+ 담보 적재 후 `AnalysisDetail.count() ≥ 100`
- [ ] foliio 8케이스 골든테스트 회귀 통과 (`test_premium_calculation_8cases.py`)
- [ ] heatmap status 단위테스트 (none/short/enough + neutral 폴백)

---

## 11. 미결 항목 (법무·운영 게이트)

| ID | 항목 | 막는 것 | 기본 가정 |
|---|---|---|---|
| **Q1** | 표준 기준선 출처·권위 | heatmap `graded` 모드 | 확정 전 `neutral`(none만 표기) |
| **Q2** | 국외이전 동의 1탭 vs 별도 동의서 | **detect API 전체** | 별도 필드+ConsentLog 분리(낙관 금지) |
| **Q3** | §97 비교안내 6항목 법적 확정 | compare 발행 하드블록 | 6항목 미완 시 `publishable=false` |
| **Q4** | 셀프진단 제3자 동의 충분성 | `consent_type=selfdiag` 동선 | share_token 만료·회수 정책 동반 |
| 운영 | 정규화 사전 자동승격 임계 | `ocr_learned` 자동매칭 | 베타까지 `admin_verified`만 사용 |
| 가격 | `ai_credit` 무료 한도 숫자 | 전환율 레버 | 베타 90일 실측 후 토큰화 (추정 유지) |

> **fallback 원칙:** 컴플라이언스 게이트가 막히면 중립 기능부터 선출시 — OCR(M1) → 히트맵 `none` 중립(M3) → 정규화(M2). 비교안내서·메시지는 §97·동의 확정 후 오픈.

---

*본 문서는 인파(Inpa) 개발 정본 11종 중 `dev/02-data-model-and-api.md`. 아키텍처는 `dev/01-architecture-and-stack.md`, 파일별 포팅 지점은 `dev/03-porting-map.md`, 빌드 순서는 `dev/04-build-plan.md` 참조.*
