# 인파(Inpa) — 시스템 아키텍처 & 스택

> 문서 ID: `dev/01-architecture-and-stack.md`
> 대상 독자: 투자자(비용·확장성), 디자이너(공유뷰·게이트 UX), 개발자(포팅·구현)
> 제품명: **인파(Inpa)** — 위촉직 보험설계사의 AI 영업 파트너
> 전제: foliio 코드 **90% 재활용**, 신규 의존성 **0개**, 별도 repo `~/Desktop/inpa`
> 모든 추정 수치에는 `(추정)` 라벨을 명시한다.

---

## 0. 한 문단 요약

인파는 foliio(보험 포트폴리오 분석 SaaS)의 검증된 파이프라인을 **그대로 들고 와** 영업 OS로 정체성을 바꾼 제품이다. 기술적으로는 새 시스템을 짓는 게 아니라 **검증 자산을 옮기는 작업**이다. Angular 17 SPA → nginx → gunicorn/Django 4.1(DRF) → MariaDB라는 foliio의 4단 구조를 유지하고, OCR(pdfplumber→PyMuPDF), 8케이스 보험료 계산(`numpy_financial.fv`), 공유링크(`share_token`), 크레딧 엔진(`credit.py`)을 무변경으로 재사용한다. 신규로 짓는 것은 단 4개 — 담보명 정규화 엔진, 히트맵 3색 판정, AI 가드레일(보험업법 룰셋), 만기 워치독 cron — 이고, 이 위에 **단 하나의 물리적 게이트**가 얹힌다. 병력(민감정보)이 Claude API(미국)로 나가므로, `detect` 호출 전에 **국외이전 동의(`consent_overseas_at`)를 확인하고 미동의 시 412로 막는다.** 이 게이트가 모든 AI 기능의 출시 가부를 쥔다.

---

## 1. 시스템 아키텍처 다이어그램

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          사용자 (설계사 / 고객)                              │
│                                                                            │
│   설계사 앱뷰                          고객 공유뷰 (헤더·탭 숨김)             │
│   /home /customer /switch ...          /s/:token  /check/:token            │
└───────────────┬──────────────────────────────────┬─────────────────────────┘
                │ HTTPS                              │ HTTPS (?ref=설계사코드)
                ▼                                    ▼
        ┌───────────────────────────────────────────────────┐
        │   Angular 17 SPA  (TypeScript 5.4 / SCSS / RxJS)   │
        │   - share_token 공개뷰 (인증 우회, 토큰 검증만)      │
        │   - credit 인디케이터 폴링 / 업그레이드 모달          │
        └───────────────────────┬───────────────────────────┘
                                │  /api/v1/*
                                ▼
                        ┌───────────────┐
                        │     nginx     │  SSL 종단 / 정적 / 미디어 / 라우팅
                        │   (IDC 서버)   │
                        └───────┬───────┘
                                │  127.0.0.1:8000
                                ▼
        ┌───────────────────────────────────────────────────┐
        │   gunicorn → Django 4.1.13 + DRF 3.14             │
        │   (conda env: inpa / systemd: inpa.service)       │
        │                                                   │
        │   ┌─────────────┐  ┌──────────────┐  ┌─────────┐ │
        │   │ detect API  │  │ analysis API │  │ ai API  │ │
        │   │ (♻+정규화)   │  │ (♻ 8케이스)   │  │ (✦신규)  │ │
        │   └──────┬──────┘  └──────────────┘  └────┬────┘ │
        │          │                                 │      │
        │   ┌──────▼───────────── 게이트 ────────────▼────┐ │
        │   │ consent_overseas_at 확인 → 미동의 412       │ │  ← 병력 국외이전 동의
        │   └──────┬───────────────────────────────┬─────┘ │     (모든 AI 기능의 물리적 관문)
        └──────────┼───────────────────────────────┼───────┘
                   │                               │
        ┌──────────▼──────────┐         ┌──────────▼──────────┐
        │  PDF 텍스트 추출      │         │   Claude API (US)   │
        │  pdfplumber → PyMuPDF│         │   Anthropic, Inc.   │  ← 국외이전 대상
        │  (암호화 authenticate)│         │   M1=Opus / M2~=Haiku│
        └─────────────────────┘         └─────────────────────┘
                   │
        ┌──────────▼──────────────────────────────────────────┐
        │   MariaDB 10.3.39  (inpa_db, 127.0.0.1:3306)        │
        │   utf8mb4_unicode_ci / 일일 백업 cron                 │
        │   Customer · CustomerInsurance · NormalizationDict   │
        │   AnalysisCategory~ChartDetail(4계층) · ConsentLog   │
        └─────────────────────────────────────────────────────┘
                   ▲
        ┌──────────┴──────────┐
        │  numpy_financial.fv │  갱신보험료 미래가치 (8케이스 中 4·8)
        └─────────────────────┘
```

**읽는 법**

- **왼쪽 흐름(PDF 추출)**은 국외이전 동의가 필요 없다 — 텍스트 추출은 서버 내부에서만 일어난다.
- **오른쪽 흐름(Claude API)**만 병력 데이터를 미국으로 보낸다. 그래서 게이트는 `detect`·`ai/*` 호출 경로에만 박힌다. 분석·히트맵·계산은 추출된 데이터로 서버에서 도는 무게이트 경로다.
- 이 분리가 **컴플라이언스 fallback의 물리적 근거**다(§6).

---

## 2. 핵심 기술 결정 — DB는 MariaDB 유지

| 항목 | 결정 | 이유 |
|---|---|---|
| **DB** | **MariaDB 10.3.39 유지** (PostgreSQL 전환 보류) | 포팅 비용 0. foliio 검증 자산을 그대로 승계. 정규화 사전은 관계형 모델(`NormalizationDict`)로 충분 — JSONB 불필요. PG 전환은 비최적화 결정으로 판단해 보류. |
| **FE** | Angular 17.3 + TS 5.4 + SCSS + RxJS 7.8 | foliio FE 전체 재활용. layout(헤더/탭/share-view 헤더숨김) 라우팅만 재배치. |
| **BE** | Django 4.1.13 + DRF 3.14.0 (Python 3.8) | foliio BE 전체 재활용. settings 분리 패턴(`local`/`idc`) 승계. |
| **차트/PDF** | chart.js 4 + ng2-charts 6 + jspdf-html2canvas | foliio 보유. 히트맵·방사형(제안색 인디고 `#3B5BDB`) 재사용. |
| **OCR 텍스트** | pdfplumber 1순위 → PyMuPDF 폴백 | foliio `core/utils.py` 무변경. 암호화 PDF `authenticate` 경로 보존. |
| **AI** | Anthropic Claude API (`anthropic` SDK) | foliio `claude_parser.py` 보유. 라우팅만 신규(§5). |
| **재무계산** | `numpy_financial.fv` | 8케이스 골든테스트로 검증된 로직. 무변경. |

> **투자자 관점 한 줄:** "신규 시스템 구축"이 아니라 "검증된 시스템의 정체성 전환"이다. 기술 리스크는 신규 4개 모듈(정규화·히트맵·가드레일·워치독)과 법무 게이트 1개에 국한된다.

---

## 3. 신규 의존성 = 0개

인파가 필요로 하는 모든 패키지는 foliio `requirements.txt`에 **이미 존재**한다. `requirements.txt`는 foliio와 동일하게 시작한다.

| 패키지 | 용도 | foliio 보유 |
|---|---|:--:|
| `anthropic` | Claude API (OCR 파싱 / 비교안내서 / 메시지 생성) | ✅ |
| `pdfplumber` | PDF 테이블 구조 보존 추출 (1순위) | ✅ |
| `PyMuPDF` | PDF 추출 폴백 + 암호화 처리 | ✅ |
| `numpy-financial` | 갱신보험료 미래가치(`fv`) | ✅ |
| `djangorestframework` | API 레이어 | ✅ |
| `Pillow` | 이미지 리사이즈(공유 미리보기 등) | ✅ |
| `Django 4.1.13` | 웹 프레임워크 | ✅ |

> **체크리스트:** 신규 `pip install` 없음. `migrate` + `seed_taxonomy`만 추가 실행.

---

## 4. foliio → 인파 포팅 등급표 (♻ 그대로 / ◑ 개조 / ✦ 신규)

영역별 처리 등급. 정확한 라인 참조와 파일별 액션은 `dev/03-porting-map.md`가 정본이다 — 여기서는 아키텍처 수준의 지도만 제시한다.

| 영역 | foliio 자산 | 등급 | 인파 처리 |
|---|---|:--:|---|
| OCR 텍스트 추출 | `core/utils.py` `extract_text_from_pdf` (pdfplumber→PyMuPDF, 암호화) | ♻ | 무변경 |
| OCR 파싱 | `core/ocr/claude_parser.py` `claude_parse(text_lines, is_proposal)` | ◑ | 시스템 프롬프트에 100+ 담보 트리 주입 |
| 담보 매칭 | `claude_parser.py` `_add_coverage` 4단계 | ◑ | **3·4순위 사이에 정규화 사전 단계 삽입** |
| 보험료 계산 | `customers/calculate.py` `calculate_total_analysis` (8케이스) | ♻ | 무변경 (`non_renewal_old_list[10]`/`renewal_old_list[10]` 그대로) |
| 크레딧 | `membership/credit.py` (`FREE_TIER_UNLIMITED` 베타우회) | ◑ | `ai_credit` kind 추가, AI 호출당 차감 |
| 공유링크 | `Customer.share_token` + analysis/compare 공개뷰 | ♻ | `?ref=` 파라미터 + 열람 계측 이벤트만 추가 |
| 동의 | `customer-agree` + `Customer.is_agree_term` | ◑ | **국외이전 동의 분리 필드 + ConsentLog** |
| Cron | `expirememberships`/`notifymembership`/`process_dormancy` 패턴 | ♻ | 만기·갱신 **워치독(M4)** 신규 command 추가 |
| 콘텐츠 필터 | `community/content_filter.py` (PII 정규식) | ◑ | `ai_guardrail.py`로 보험업법 룰셋 신규 |
| 분석 모델 | `AnalysisCategory/SubCategory/Detail/ChartDetail` 4계층 | ♻ | 무변경 + 시드 30→100+ 담보 확장 |
| 정규화 사전 | — | ✦ | `NormalizationDict` 신규 모델 (데이터 복리 해자) |
| 히트맵 | — | ✦ | `customers/heatmap.py` 3색 판정 |

**신규(✦)로 새로 짜는 파일은 단 6개**

```
core/ai_guardrail.py                    # 보험업법 §97/광고심의 룰셋 (판정·플래그)
insurances/normalization.py             # NormalizationDict 매칭 엔진
customers/heatmap.py                    # 충족/부족/없음 3색 판정
management/commands/watchdog.py         # M4 만기·갱신 cron
management/commands/seed_taxonomy.py    # 100+ 담보 + 정규화 사전 시드
ai/message_prompts.py                   # 목적 enum별 카톡 메시지 프롬프트
```

---

## 5. AI 라우팅 & 비용 거버넌스

검증된 모델 ID·단가(2026-06 기준, Anthropic 공식). **추측 금지 — 아래 값은 확정값이다.**

| 용도 | 모델 | 모델 ID | 입력 $/MTok | 출력 $/MTok | 이유 |
|---|---|---|---:|---:|---|
| **M1 비교안내서 / 정규화 사전 학습** | Claude Opus 4.8 | `claude-opus-4-8` | $5.00 | $25.00 | §97 합법성 때문에 정확도 critical. 실시간 경로. |
| **M2~M4·M6 다건 OCR / 메시지** | Claude Haiku 4.5 | `claude-haiku-4-5` | $1.00 | $5.00 | 다건·대량 처리. 원가 최적화. |
| (참고) 중간 옵션 | Claude Sonnet 4.6 | `claude-sonnet-4-6` | $3.00 | $15.00 | 필요 시 M1 원가 타협 카드 |

**비용 절감 2단 레버 (호출당 원가를 수백 원대로)**

1. **Prompt caching — 정규화 사전을 system 블록에 고정.**
   - 프롬프트 캐싱은 **prefix 매칭**이다. 100+ 담보 트리 + 정규화 사전을 `system` 블록 앞단에 고정(`cache_control: ephemeral`)하고, **고객 가변값(병력·담보 텍스트)은 breakpoint 뒤로** 보낸다.
   - 캐시 읽기 ≈ 기본 입력가의 **0.1×**, 쓰기 ≈ **1.25×**(5분 TTL). 같은 사전을 매 호출 재사용하므로 2회차부터 손익분기를 넘긴다.
   - 검증 포인트: 응답 `usage.cache_read_input_tokens`가 0이면 silent invalidator(시스템 프롬프트 내 타임스탬프/비결정적 JSON 정렬 등)를 의심.
2. **Batches API — 야간 배치 50% 할인.**
   - 비실시간 다건 OCR(M2~)·대량 재계산은 야간 배치로 돌려 **전 토큰 50% 할인**.

**측정·운영 규칙**

- 토큰 측정은 반드시 `count_tokens` 엔드포인트로(모델별). **`tiktoken` 금지** — Claude 토큰을 15~20% 과소계산한다.
- **호출당 로깅 + 월 예산 캡 + 임박 알림**. 보조지표 = "발송 액션당 AI 비용".
- 모델 전환 시 캐시는 모델 스코프라 무효화됨 — M1↔M2를 한 요청 안에서 섞지 않는다.

---

## 6. 보안 — 국외이전 동의 게이트가 모든 것의 관문

### 6.1 detect 호출 전 412 게이트 (가장 단단한 폭탄)

병력은 **민감정보**다. Claude API는 **미국(Anthropic, Inc.)**에 있다. 따라서 민감정보 국외이전 동의 없이는 `detect` API 자체를 열 수 없다.

```
[설계사] 증권 업로드
    │
    ▼
[BE] detect 진입
    │
    ├─ Customer.consent_overseas_at IS NULL ?
    │        │
    │        ├─ YES → 412 Precondition Failed  ──▶ [FE] 국외이전 동의 모달
    │        │                                       (정보주체 본인 1탭 동의 동선)
    │        │
    │        └─ NO  → ConsentLog 기록 후 진행
    │
    ▼
[Claude API (US)] 호출
```

- **별도 필드 전제(낙관 가정 금지):** 기존 `customer-agree`의 `is_agree_term` 1필드로 커버 가능한지가 법무 미결 사항(Q2)이므로, 설계는 **`consent_overseas_at` 별도 필드 + `ConsentLog` 분리**를 기본 전제로 한다. 법무 자문 후 단일 필드로 합쳐도 되지만, 분리 전제로 짜두면 막히지 않는다.
- **ConsentLog 감사추적:** `ConsentLog(customer, type=overseas, agreed_at, ip, doc_version)` — 누가·언제·어떤 동의서 버전으로·어떤 IP에서 동의했는지 기록. 준법 감사·분쟁 대비.
- **셀프진단(지인) 동선:** 제3자(지인) 정보 수집 시 정보주체 **본인 1탭 동의** 동선이 별도로 필요(법적 충분성은 Q4 미결).

### 6.2 게이트가 막혔을 때의 fallback (중립 기능 선출시)

법무 게이트가 길어지면 **중립 기능부터** 출시한다.

```
OCR(M1)  →  히트맵 none 중립(M3)  →  정규화(M2)
   │              │                      │
   └ 텍스트 추출만   └ "보유=0원 여부"만      └ 사전 매칭
     (국외이전 無)     회색 중립 표기            (국외이전 無)
                     (enough/short 판정 보류)

   비교안내서 · AI메시지  →  §97 정확요건 + 국외이전 동의 확정 후 오픈
```

> 히트맵 기준선 출처(금감원/보험연구원/자체)가 미확정(Q1)인 동안에는 **enough/short 판정을 보류**하고 `none`(보유=0원 여부)만 회색 중립으로 표기한다. 임계값 코드(`std_baseline * 0.7`)는 미리 짜두되, 데이터 권위는 Phase0 법무 산출물로 받는다.

### 6.3 그 외 보안 기준

| 항목 | 처리 |
|---|---|
| **PII 필터** | foliio `content_filter.py` 정규식(KR mobile/RRN/card/사업자번호) 재사용. 커뮤니티·메시지 입력 검증. |
| **시크릿 관리** | `Foliio_be/.env` 패턴 승계: `SECRET_KEY`, `CLAUDE_API_KEY`, `DJANGO_DEFAULT_DATABASE_*`. **`environment.prod.ts`·`NEXT_PUBLIC_*`에 키 절대 금지.** |
| **settings 분리** | `config.settings.local` / `config.settings.idc`. 로컬은 **반드시** `DJANGO_SETTINGS_MODULE=config.settings.local` 명시(미명시 시 prod로 붙음). |
| **DRF 기본 권한** | `IsAuthenticated`. 공개 API만 명시적 `AllowAny`. 공유링크는 `share_token` 쿼리 파라미터 검증. |
| **share_token 정책** | 만료·회수·`robots noindex` 정책은 Q4 미결 — 설계 시 만료 필드 자리 확보. |
| **DB 문자셋** | `DATABASES['OPTIONS']['init_command']`로 `utf8mb4_unicode_ci` 강제(foliio 기지정) — 한글 WHERE 안전. |

---

## 7. 로컬 셋업 · 의존성

별도 repo `~/Desktop/inpa`, foliio를 포팅 참조로 둔다.

### 7.1 백엔드

```bash
# 1. 의존성 (foliio와 동일 — 신규 0개)
pip install -r requirements.txt

# 2. DB 마이그레이션 (로컬 설정 명시 필수)
DJANGO_SETTINGS_MODULE=config.settings.local python manage.py migrate

# 3. 담보 트리 + 정규화 사전 시드 (신규 command)
DJANGO_SETTINGS_MODULE=config.settings.local python manage.py seed_taxonomy

# 4. 개발 서버
DJANGO_SETTINGS_MODULE=config.settings.local python manage.py runserver
```

> ⚠️ `manage.py` 기본값은 foliio 패턴을 따라 `config.settings.idc`(프로덕션)이다. **로컬에서는 매 명령에 `DJANGO_SETTINGS_MODULE=config.settings.local`을 붙여야** 한다. 안 붙이면 프로덕션 DB로 붙는다.

### 7.2 프론트엔드

```bash
npm install
npm run start        # http://localhost:4200
npm run build        # → dist/
```

### 7.3 검증 (done ≠ 코드 작성)

```bash
pytest                                              # 회귀 가드
pytest weapon/insurances/tests/test_premium_calculation_8cases.py -v   # 8케이스 골든테스트 (포팅 검증 기준선)
```

- **8케이스 골든테스트는 foliio에서 그대로 가져와** 회귀 가드로 쓴다. 보험료 계산을 건드릴 때마다 재실행.
- 정규화 사전은 신규 테스트: `raw_name → 표준담보` happy path + `unmatched` 학습 루프.

---

## 8. 배포 개요

foliio의 rsync 기반 배포 스크립트 패턴을 그대로 승계한다(IDC 서버, conda env, systemd, nginx).

```
[로컬 맥]                          [IDC 서버 211.234.108.90]
                                   user: pample
deploy-be.sh  ──rsync──▶  /home/pample/work/inpa/Inpa_be/
   │                          │
   │                          ├─ conda activate inpa
   │                          ├─ migrate (idc 설정)
   │                          ├─ collectstatic
   │                          └─ gunicorn 재시작 (systemd: inpa.service)
   │
deploy-fe.sh  ──rsync──▶  /var/www/<도메인>/html/  (Angular dist)
                          nginx 서빙

[nginx]  /api/v1/ → 127.0.0.1:8000 (Django)
         /static/ /media/ → 정적·업로드
```

| 항목 | 값 |
|---|---|
| 프로덕션 설정 | `config.settings.idc` (DEBUG=False, CORS 화이트리스트, secure cookie, SSL via nginx) |
| conda env | `inpa` (foliio의 `backup`/`foliio` env 건드리지 않음) |
| systemd | `inpa.service` (재부팅 자동 시작) |
| **cron — 신규** | 만기·갱신 **워치독**(`watchdog.py`) 추가. foliio의 일일/월간 cron 패턴 위에 얹음. |
| 베타 우회 | `FREE_TIER_UNLIMITED=True` (정식 출시 시 `False`). `SUPER_BETA_EXPIRY=2099-12-31`(출시일 미확정). |
| 의존성 설치 | ⚠️ 배포 스크립트는 `pip install`을 자동 실행하지 **않음** — 서버에서 `conda activate inpa && pip install -r requirements.txt` 수동 실행. |

> **배포 안전 체크리스트(프로덕션):** 테스트 통과 → 빌드 성공 → env var diff(dev vs prod) → DB 마이그레이션 순서 → 롤백 경로 확인. 프로덕션 배포는 **명시적 승인 필수**.

---

## 9. AI 비용 거버넌스 요약 (투자자용 한 칸)

| 레버 | 효과 | 근거 |
|---|---|---|
| Prompt caching (정규화 사전 system 고정) | 캐시 읽기 ≈ 입력가 0.1× | prefix 매칭, 2회차부터 손익분기 |
| Batches API (야간 배치) | 전 토큰 **50% 할인** | 비실시간 다건 OCR·재계산 |
| 모델 라우팅 (M1 Opus / M2~ Haiku) | 다건 경로 Haiku로 원가 1/5 | §97 정확도 필요한 M1만 Opus |
| 호출당 로깅 + 월 예산 캡 | 비용 누수 방지 | 보조지표=발송 액션당 AI 비용 |

호출당 실제 원가 절대값은 베타 90일 실측 후 토큰화한다 **(추정)** — 현 단계에서는 "캐싱+배치+라우팅으로 호출당 수백 원대" 가설.

---

## 10. 미해소 사항 (이 문서가 의존하는 법무·운영 선결)

| # | 쟁점 | 영향 | 상태 |
|---|---|---|---|
| Q1 | 표준 보장 기준선 출처·권위(금감원/보험연구원/자체) | 히트맵 enough/short 판정 게이트 | Phase0 법무 — 확정 전 `none` 중립만 |
| Q2 | 병력 국외이전 동의 = `customer-agree` 1탭 vs `consent_overseas_at` 분리 | detect API 자체를 여는 조건 | 분리 전제로 설계(낙관 금지) |
| Q3 | §97 비교안내 정확요건 6항목 법적 확정 | 비교안내서 발행 하드블록 룰 | Phase0 법무 |
| Q4 | 셀프진단(제3자) 동의 충분성 + share_token 만료·회수·noindex | 바이럴 루프·공유뷰 | Phase0 법무 |
| 운영 | 정규화 사전 `unmatched` 자동승격 임계(hit_count 5회+ 자동매핑 허용 여부) | 자동매핑 오류 시 §97 위반 vs 운영비용 | 운영 주체 미정 |

---

### 관련 문서
- `dev/02-data-model-and-api.md` — `NormalizationDict`/`ConsentLog`/`Customer(+consent_overseas_at)` 전체 필드, API 표(detect/heatmap/compare/ai)
- `dev/03-porting-map.md` — 파일별·라인별 포팅 액션(정본)
- `dev/04-build-plan.md` — Phase0(법무 게이트)/Phase1(MVP 6주) 스프린트·게이트
