# 고객 관리(CRUD) + 증권 업로드

> 인파(Inpa) — 보험설계사의 업무 OS
> 문서 ID: `dev/12-customer-crud-ocr.md` · 2026-06-19 · 정본 교차검증: `dev/02`(데이터모델·API)·`dev/07`(detect 6단계·공유뷰)·`dev/08`(화면)·`dev/09`(컴플라이언스)·`04-ia-and-ux`
> 범위: **기록 모드(A)의 심장부** — 고객 목록/검색/필터/상세 + 고객 등록 + 증권 업로드→detect(OCR)→담보 자동 채움. 구현 코드가 아니라 **계약·구조·흐름**을 못박는다.

---

## 0. 이 문서가 다루는 표면

설계사 하루 두 모드 중 **(A) 기록 모드** — 자투리·이동 중 한 손으로 증권/메모를 던져넣는 마찰 0 구간 — 의 BE·FE 계약을 확정한다. 영업 모드(B: 히트맵·§97 비교서·공유링크)는 별도 문서(`dev/13` 분석, `dev/14` 발굴)로 분리하고, 본 문서는 **그 무기들이 먹고 자라는 데이터(고객·보험·담보)를 어떻게 적재하는가**만 다룬다.

```
[증권 사진/PDF 투척]  ─OCR→  [고객 + 보험 + 담보 자동 채움]  ─→  히트맵/비교서/공유링크의 입력
        (기록 모드 A)                  (본 문서)                        (영업 모드 B, 별도 문서)
```

핵심 원칙 3개 (본 문서 전체 관통):
1. **기록은 마찰 0** — 손입력 노동이 3주 내 이탈 원인. 증권 던지면 채워져야 한다.
2. **detect 앞에 컴플라이언스 게이트** — 국외이전 동의(`consent_overseas_at`) 없으면 BE가 412로 물리 차단. UI 숨김은 방어가 아니다.
3. **foliio 재활용 우선** — `Customer`·`CustomerInsurance`·8케이스 calculate·N+1 회귀가드를 vendoring. net-new는 동의 게이트 1필드 + 정규화 사전.

---

## 1. 화면 IA — 기록 모드 동선

```
하단탭(설계사)  [홈] [고객] [＋증권] [캘린더] [내정보]
                        │       │
                        ▼       ▼
              /customer        업로드 드롭존(전역 FAB ⊕)
                 │                 │
       ┌─────────┼─────────┐       ▼
       ▼         ▼         ▼   업로드 큐(썸네일+진행률)
  검색바    정렬·필터칩  고객행×N    │
       │                 │         ▼
       │                 ▼   detect(OCR) ──412 동의게이트──▶ [국외이전 동의 모달]
       │            /customer/:id        │(미동의)            │(동의 후 재시도)
       │            ┌──────────┐         ▼
       │            탭: 분석/갈아타기/공백/이력   빈칸채우기 폼(신뢰도 색칩)
       ▼                                  │
  /customer/create (수기 등록 — OCR 폴백)   ▼
                                    저장→고객+보험 생성
```

세 진입로가 **같은 빈칸채우기 폼**으로 수렴한다: (a) 증권 detect → 자동 채움, (b) 수기 `/customer/create`, (c) 기존 고객 상세에서 "보험 추가". OCR은 폼을 **미리 채우는 보조**일 뿐, 최종 저장 책임은 설계사에게 있다(컴플라이언스: 인파는 판단·권유하지 않는다).

---

## 2. 데이터 모델 — foliio 재활용 + net-new

### 2.1 Customer (foliio ♻ — 거의 그대로)

`dev/02 §2`에서 동결된 변경점만. 재활용 필드는 무변경.

| 필드 | 출처 | 비고 |
|---|---|---|
| `name` | ♻ foliio | 공유뷰 노출 시 마스킹(§7.3) |
| `mobile` | ♻ | |
| `birth_day` | ♻ | 공유뷰는 연도만 (추정) |
| `gender` | ♻ (SmallInt 1=남/2=여, nullable) | foliio 2026-06 추가분 계승 |
| `job_code` | ♻ JobRiskCode FK | 직업위험 등급 |
| `medical_histories` | ♻ MedicalHistory | 민감정보 — 국외이전 동의 대상 |
| `share_token` | ♻ UUID | 공유링크 공개키 |
| `user_view_at` | ♻ | 미열람 액션큐 사유 산출 입력 |
| `color`, `memo` | ♻ | 설계사 분류용 |
| **`consent_overseas_at`** | **★ net-new** | detect 412 게이트 키 (DateTime, nullable) |
| **`share_expires_at`** | **★ net-new 예약** | 공유 TTL (Q4 미확정, 일단 nullable) |

- `on_delete=SET_NULL` foliio 패턴 유지 — 설계사 탈퇴 시 고객 데이터 보존.
- `total_monthly_premiums`: foliio N+1 트랩 계승 — **목록 응답이 row별 `annotate(Sum, filter=portfolio_type=1)`로 내려준다**. FE는 보험별 재계산 금지.

### 2.2 CustomerInsurance (foliio ♻ — 무변경)

8케이스 calculate·음수 guard(`monthly_non_renewal_premium = max(0, assurance − renewal)`)·`custom_coverages` JSON 전부 재활용. **모델 무변경이 회귀 게이트** — 8케이스 골든 179 passed 불변이 포팅 무결성의 증거.

### 2.3 net-new 모델 4종 (정규화·동의·계측)

| 모델 | 핵심 필드 | 역할 |
|---|---|---|
| `NormalizationDict` | `UNIQUE(company, raw_name)`, `std_name`, `category`, `source`(admin_verified/ocr_learned), `hit_count` | 담보명 정규화 정본 — 해자. 베타는 `admin_verified`만 매칭 |
| `UnmatchedLog` | `company`, `raw_name`, `occurrence`(++), `created_at` | 미매칭 학습루프 → admin 1탭 승격 |
| `ConsentLog` | `customer FK`, `scope`(민감/국외/제3자), `doc_version`, `ip`, `consented_at`, `revoked_at` | 국외이전 동의 감사추적 (6요건) |
| `NorthStarEvent` | `event_type(1~6)`, `share_token`, `sender_user`, `ref_code`, `viewer_fp`, `meta JSON` | 북극성 계측 — **Day1 동결, 사후복원 불가** |

> 담보 트리(StandardCoverage 4계층)는 foliio ♻ **모델 무변경 + 시드 30→100+**. 새 테이블을 만들면 calculate 8케이스가 단절된다 — 절대 금지.

---

## 3. 고객 목록/검색/필터/상세 — API 계약

### 3.1 목록 `GET /api/v1/customer/`

```
GET /customer/?q=홍&sort=expiry&filter=expiring&page=1
Auth: DRF Token (본인 소유만)
```
**응답 (row별 annotate — N+1 회귀가드 포팅):**
```json
{
  "count": 42,
  "next": "?page=2",
  "results": [
    {
      "id": 1031,
      "name": "홍**",                          // 목록은 마스킹 안 함(본인 화면), 공유뷰만 마스킹
      "gender": 1,
      "birth_day": "1986-03-12",
      "age": 40,
      "insurance_count": 4,                    // portfolio_type=1 보유 보험 수
      "total_monthly_premiums": 287000,        // ★ annotate(Sum, filter=portfolio_type=1) — FE 재계산 금지
      "last_contact_at": "2026-06-10T09:00:00+09:00",
      "expiry_soon": true,                     // D-30 이내 만기 보험 존재
      "consent_overseas_at": null,             // 동의 게이트 상태 — 액션큐/상세에서 사용
      "color": "blue",
      "share_token": "a1b2…"
    }
  ]
}
```

| 파라미터 | 값 | 처리 |
|---|---|---|
| `q` | 문자열 | 이름·연락처 부분일치 (BE LIKE, PII 로그 금지) |
| `sort` | `recent`(기본)/`expiry`/`name`/`premium` | **BE 권위 정렬** — FE 재정렬 금지 |
| `filter` | `all`/`expiring`/`new`/`no_consent` | 칩 매핑 |
| `page` | 정수 | DRF 페이지네이션 |

> **탭 전환 시 sort/filter reset** — foliio admin 패턴 계승. 새로고침 보존은 URL searchParams(`?q&sort&filter`)로 FE가 동기화.

### 3.2 생성 `POST /api/v1/customer/`

```json
// 요청
{
  "name": "홍길동", "mobile": "010-1234-5678",
  "birth_day": "1986-03-12", "gender": 1,
  "job_code": 12, "color": "blue", "memo": ""
}
// 응답 201 → {id, share_token, ...}
// 한도 초과 시 402 {reason:'CREDIT_EXHAUSTED', limit, remaining}
```
- **`customer_credit` 차감** (foliio 크레딧 엔진 ♻). 베타 `FREE_TIER_UNLIMITED=True`면 무차감.
- `remaining=null` / `is_unlimited=True` → 무제한 (0은 exhausted 아님 — foliio §8 트랩 계승).

### 3.3 상세 `GET /api/v1/customer/:id/`

```json
{
  "id": 1031, "name": "홍길동", "gender": 1, "birth_day": "1986-03-12",
  "job": {"code": 12, "label": "사무직", "risk_grade": 1},
  "medical_histories": [ … ],
  "consent_overseas_at": null,                 // null → 상위 AI 탭 블러+자물쇠
  "insurances": [
    {"id": 88, "company": "삼성생명", "product": "…",
     "portfolio_type": 1, "monthly_premiums": 92000, "expiry_at": "2026-07-05"}
  ],
  "share_token": "a1b2…", "user_view_at": null
}
```
- 상세 화면 탭 4종: **분석**(히트맵, `dev/13`) / **갈아타기**(§97, `dev/14`) / **공백**(미보유 담보) / **이력**(ActivityLog). 본 문서는 보험 적재까지만; 탭 내용은 영업 모드 문서로.
- `consent_overseas_at is null` → 분석/갈아타기 탭 **블러+자물쇠 UX**(데이터 게이트 아님 — 412는 detect에만). 동의 완료 시 초록 배지.

### 3.4 수정·삭제

| | 계약 |
|---|---|
| `PATCH /customer/:id/` | 본인만. 빈칸채우기 폼 재사용 |
| `DELETE /customer/:id/` | **soft delete**(본인만). foliio `deleted_at` 패턴 |

---

## 4. 고객 등록 — 수기 + OCR 수렴 폼

세 진입로가 같은 폼으로 수렴(§1). 폼 필드와 검증:

| 필드 | 필수 | 검증 | OCR 자동채움 |
|---|---|---|---|
| 이름 | ✔ | 1자+ | ◑ 확정/추정 색칩 |
| 생년월일 | ✔ | YYYY-MM-DD | ◑ |
| 성별 | (추정) 선택 | 1/2 | ◑ |
| 연락처 | △ | 휴대폰 정규식 | ✕ (증권에 없음) |
| 직업위험 | △ | JobRiskCode | ✕ (수기) |
| 보험사 | ✔(보험행) | enum | ◑ |
| 담보 행 | — | custom_coverages | ◑ 정규화 매칭 |

**신뢰도 색칩 규칙:** OCR 추출값은 `match_source` 기반 2색 — 🟢 초록=확정(`category_map`/`admin_verified`) / 🟡 노랑=추정(`fuzzy`/`keyword`). 미매칭은 빈칸+회색 안내. 설계사가 노랑 칩을 눈으로 검수 후 저장 → 최종 책임 설계사에게 귀속(컴플라이언스).

---

## 5. 증권 detect (OCR) — 6단계 의존성 파이프라인

`dev/07 §1.2`에서 동결된 6단계. 순서가 강제다.

```
POST /api/v1/customer_insurance/detect/   (multipart: file, customer_id)

①  동의 게이트     consent_overseas_at is None  ──▶ 412 {reason:'CONSENT_OVERSEAS_REQUIRED'}
        │ (detect에만 물림 — 다른 API는 무게이트)
        ▼ 통과
②  extract        pdfplumber → PyMuPDF 폴백 (foliio utils.py ♻)
        ▼
③  claude_parse   Claude Haiku, BE 100% 경유 (키 노출 0, 컴플라이언스)
        ▼
④  _add_coverage  3.5순위에 normalization 삽입 ★해자
        │  category_map → keyword → [normalization] → detail_name → fuzzy(3자+)
        │  미매칭 → UnmatchedLog(occurrence++)
        ▼
⑤  calculate      8케이스 (foliio ♻ 무변경) + 음수 guard
        ▼
⑥  ai_credit 차감  (portfolio_type==1 보험만)
        ▼
   응답 {info, ocrResult, match_summary}
```

### 5.1 detect 응답 계약

```json
{
  "info": { "name": "홍길동", "birth_day": "1986-03-12", "gender": 1,
            "company": "삼성생명", "product": "…", "expiry_at": "2046-03-11" },
  "ocrResult": {
    "coverages": [
      {"raw_name": "암진단비", "std_name": "암진단", "category": "진단",
       "amount": 30000000, "match_source": "normalization", "confidence": "high"},
      {"raw_name": "특정질병수술비", "std_name": null,
       "amount": 1000000, "match_source": "none", "confidence": "low"}
    ],
    "premium": { "monthly_premiums": 92000 }
  },
  "match_summary": { "matched": 11, "unmatched": 2, "rate": 0.846 }
}
```

- `match_source` enum: `category_map`/`keyword`/`normalization`/`fuzzy`/`none` — 신뢰도 추적·색칩 직결.
- **베타는 `admin_verified`만 매칭**(오매핑 0 우선). `ocr_learned` 자동승격은 P1.
- **OCR=Haiku** 고정 (정확도 critical한 §97 비교서만 Opus). BE 100% 경유 — 키 클라 노출 0.

### 5.2 추출률 게이트 (추정 — 분모 미확정)

| 항목 | 값 | 상태 |
|---|---|---|
| 목표 추출률 | ≥85% | 골든셋 107PDF |
| 정규화 오매핑률 | ≤5% | (추정) |
| 분모 정의 | 7필드 vs 100+필드, 필드별 가중치 | **미확정(G-N8)** — PASS/FAIL 측정 불가 |

### 5.3 부분 실패·다건

- 첫 슬라이스는 **단건 happy path만**. 다건 `detect_batch`(여러 장 동시 투척)는 2차 웨이브.
- 부분 실패(일부 담보 미매칭)는 정상 응답 + `match_source:none` 표기 — 설계사 수기 보정 폴백.

---

## 6. 컴플라이언스 게이트 — 국외이전 동의

> `dev/09` 절대원칙: 병력 등 민감정보가 미국(Anthropic)으로 나가므로 **고객 동의 없이 detect 호출 불가**. UI 숨김 ≠ 방어, BE 412 차단.

### 6.1 동의 흐름

```
[증권 detect 시도]
      │
      ▼
consent_overseas_at is None?  ──No──▶ detect 진행
      │ Yes
      ▼
412 {reason:'CONSENT_OVERSEAS_REQUIRED'}
      │
      ▼
[국외이전 동의 모달]  쉬운말 설명(무엇을·왜·어디로) + 항목별 체크(민감정보/국외이전/제3자)
      │  ├ 설계사 대리 동의(현장)
      │  └ 셀프동의 링크(고객 직접) — 선택
      ▼
POST /customer/:id/consent_overseas/  → consent_overseas_at=now + ConsentLog 적재
      │
      ▼
detect 재시도 → 통과
```

### 6.2 ConsentLog 6요건 (감사추적)

| 요건 | 필드 |
|---|---|
| 누가 | `customer FK` (+ 대리 설계사 `sender_user`) |
| 언제 | `consented_at` |
| 무엇을 | `scope`(민감정보/국외이전/제3자) |
| 버전 | `doc_version` |
| 어디서 | `ip` |
| 철회 | `revoked_at` |

- **첫 슬라이스**: `consent_overseas_at` + 412 배선만. ConsentLog 풀스택(6요건·doc_version·회수동선)은 P1.
- **레드라인**: "안전배지/심의완료" 카피 0건 — `grep` 골든 회귀로 차단. 인파는 중개·권유하지 않는다.

---

## 7. 공유뷰 PII — 보수적 디폴트

> 본 문서는 적재만 다루지만, 적재 데이터가 공유뷰로 새는 범위를 여기서 못박는다(공유뷰 풀계약은 `dev/08`).

### 7.1 노출 허용 (사실만)

납입현황(납입률/낸·남은 보험료/만기) + 보유담보(이름 + 보장금액). **부족/충분/추천 판정 prop 물리 부재.**

### 7.2 노출 금지

병력(민감정보)·주민번호·연락처·직업위험 — 공유뷰 응답에서 **물리 제거**(serializer 필드 부재).

### 7.3 마스킹 디폴트 (§8 확정 전 보수적)

| 항목 | 디폴트 |
|---|---|
| 고객명 | 첫 글자 + `**` (홍**) |
| 생년월일 | 연도만 (1986년생) (추정) |
| 병력 | 노출 0 |

→ 마스킹 규칙 정본화 전까지 BE가 **이름 마스킹·연도만** 강제. 단톡방 영구노출 사고 방지.

---

## 8. 수용기준 (AC) 체크리스트

**고객 CRUD**
- [ ] AC-C1 목록 `GET /customer/`가 row별 `total_monthly_premiums` annotate를 내려준다(N+1 회귀 테스트 포팅, FE 재계산 0).
- [ ] AC-C2 `sort`/`filter`는 BE 권위. FE 재정렬 코드 부재.
- [ ] AC-C3 생성 시 `customer_credit` 차감, 베타 무제한(`remaining=null→∞`, 0은 exhausted 아님).
- [ ] AC-C4 삭제는 soft delete, 본인만. 탈퇴 시 `on_delete=SET_NULL` 보존.
- [ ] AC-C5 빈 상태(고객0)=콜드스타트 `[증권 올리기]` CTA, 로딩=스켈레톤 행.

**증권 detect(OCR)**
- [ ] AC-O1 detect 호출 전 `consent_overseas_at is None`→**412** `CONSENT_OVERSEAS_REQUIRED`(detect에만, UI 숨김 아닌 BE 차단).
- [ ] AC-O2 6단계 순서 강제 + `_add_coverage` 3.5순위 normalization 삽입.
- [ ] AC-O3 8케이스 골든 **179 passed 불변**(포팅 무결성 회귀 게이트).
- [ ] AC-O4 `match_source` enum 5종으로 신뢰도 색칩(🟢확정/🟡추정/빈칸 미매칭).
- [ ] AC-O5 베타는 `admin_verified`만 매칭(오매핑 0). OCR=Haiku, BE 100% 경유.
- [ ] AC-O6 음수 guard `max(0, assurance−renewal)` 적용.

**컴플라이언스**
- [ ] AC-G1 ConsentLog 6요건 감사추적(첫 슬라이스는 `consent_overseas_at`+412 배선만).
- [ ] AC-G2 공유뷰 병력·연락처·직업 물리 제거 + 이름 마스킹·연도만.
- [ ] AC-G3 "안전배지/심의완료" 카피 0건(grep 골든 회귀).

---

## 9. 기획 갭 (blocking ★ / non-blocking)

| # | 갭 | 영향 | 상태 |
|---|---|---|---|
| G-1 ★ | **정규화 사전 v0 시드 ~150행**(상위30담보×5사) + 보험사 `company` code enum 실번호 | 미완 시 `_add_coverage` 매칭 불가 → 히트맵 거짓=정직성 레드라인 | D-0 전제. 데이터 인력 2~3일 선투입, owner·일정 미확정 |
| G-2 ★ | **OCR 골든셋 107PDF 정답 라벨링** + 실고객 PII(병력/주민번호) 마스킹·익명화 후 QA 픽스처 커밋(gitleaks 통과) | 추출률 85% PASS/FAIL 측정 불가 | 선결 |
| G-3 ★ | **OCR 추출률 85% 게이트 분모 정의**(7필드 vs 100+필드, 필드별 가중치, 오매핑 ≤5% 임계) | PASS/FAIL 판정 불가 | 미확정 |
| G-4 ★ | **Q2 국외이전 동의 1탭 법적 안전선 대표 승인**(외부 법무자문 없음·CPO=CTO, 보수적 자체처리) | 막히면 detect 전체 봉인 → 수기입력+히트맵 neutral 데모로 우회 | 대표 승인 게이트 |
| G-5 ★ | **북극성 6종 스키마 Day1 동결**(payload·중복제거키·`?ref=` 형식 첫 마이그레이션) | 사후복원 불가 — Sprint1 착수 절대 선행 | 미동결 |
| G-6 | 보험사 `company` code enum 실번호 체계(청약서·약관 대조) | NormalizationDict UNIQUE 키이자 정규화 정본 | G-1과 묶임 |
| G-7 | 공유뷰 PII 노출범위 확정(고객명 마스킹/gender null/병력) — 현재 보수적 디폴트로만 우회 | 개인정보 사고 | §8 미결 |
| G-8 | `ai_credit` 무료 한도 숫자(공유뷰 발급 차감 여부 포함) | 베타 90일 실측 전 추정 유지 | 추정 |
| G-9 | 정규화 자동승격 임계(`hit_count≥N → ocr_learned`) 운영주체·검수 UI | 베타는 `admin_verified`만으로 우회 | non-block |
| G-10 | 직업위험(JobRiskCode) 입력 UX·필수여부 + 성별 null 표기 규칙 | 폼 props 확정 불가 | non-block, 출시 전 확정 |
| G-11 | `share_token` 만료 TTL·회수 동선·보존기간·만료 응답코드(410?) | 단톡방 영구노출 | `share_expires_at` 예약만, Q4 미확정 |

---

## 10. 마이그레이션·착수 순서

```
1. makemigrations + migrate
     └ NorthStarEvent 포함 (★ Day1 동결, 사후복원 불가 — G-5)
2. seed_taxonomy   (최선행 — 모든 분석 입력)
     ├ 담보 30→100+ 시드
     └ NormalizationDict v0 ~150행 (G-1 — owner 미정)
3. loadinitialmemberships  (ai_credit kind 추가, 0=무제한 sentinel)
4. vendoring  weapon → inpa (gunicorn 8001, inpa_db)
```

**BE blocking 5종 (Sprint0 게이트):** ①북극성 6종 스키마 동결 ②정규화 v0 ~150행 + 보험사 enum + 골든셋 107PDF ③insights 카피규칙(공유뷰, `dev/08`) ④Q2 동의 1탭 대표승인 ⑤chart_based_amount 100+ 시드값(히트맵, `dev/13`). 코드는 따라온다 — **잠가야 할 건 데이터·법무·계측 3종이다.**