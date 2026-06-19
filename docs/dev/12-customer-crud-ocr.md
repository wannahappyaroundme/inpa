# 고객 관리(CRUD) + 증권 업로드

> 인파(Inpa) — 보험설계사의 업무 OS
> 문서 ID: `dev/12-customer-crud-ocr.md` · 2026-06-19 (v2 패치: 이메일/비번 인증·가시성 매트릭스·CRM 강화·planner_baseline neutral 통제점 반영 / v2.1 정본 정렬: CASCADE·ConsentLog agreed_at·UnmatchedLog 가시성·CustomerMedicalHistory 별도모델·terms_agreed_at 폐기)
> 정본 교차검증: `dev/02`(데이터모델·API)·`dev/07`(detect 6단계·공유뷰)·`dev/08`(화면)·`dev/09`(컴플라이언스)·`dev/10`(planner_baseline)·`dev/11`(인증)·`04-ia-and-ux`
> 범위: **기록 모드(A)의 심장부** — 고객 목록/검색/필터/상세 + 고객 등록 + 증권 업로드→detect(OCR)→담보 자동 채움. 구현 코드가 아니라 **계약·구조·흐름**을 못박는다.

---

## [v2 패치 요약]

이 문서에서 변경된 핵심 사항은 다음과 같다. 독자는 이 절을 읽으면 이전 v1과의 차이를 파악할 수 있다.

| 항목 | v1 | v2 (이번 패치) | v2.1 (정본 정렬) |
|---|---|---|---|
| 인증 방식 | 카카오 OAuth (foliio ♻) | **이메일/비밀번호 전용** — 카카오 OAuth 전면 제거 | — |
| 가시성 분류 | 미명시 | **소유자 전용** 명시 (`owner FK` + `OwnedQuerySetMixin` + `IsOwner`) | — |
| 고객 목록 | 기본 리스트 | **카드형 목록·검색바·태그·만기 임박 배지** 추가 | — |
| 고객 등록 폼 | 기본 필드 | **가족구성(FamilyMember)·메모(memo) 강화** | — |
| 히트맵 기준 | 미명시 | ★**planner_baseline 준법 통제점** 명시 (`baseline_source==null → neutral 강제`) | — |
| 갈아타기 비교 | 언급만 | §97 비교안내 **섹션 5.4로 확장** | — |
| **Customer.owner on_delete** | SET_NULL (foliio 패턴) | SET_NULL 유지 언급 | **CASCADE** — 탈퇴 시 고객 개인정보 연쇄 삭제 (결정 8) |
| **ConsentLog 타임스탬프** | consented_at | consented_at | **agreed_at** (정본 dev/02 §4.1, 결정 5류) |
| **UnmatchedLog 가시성** | 관리자 전용 | 관리자 전용 | **공유(전역) + 관리자 검수** (결정 정본 dev/02 §0) |
| **CustomerMedicalHistory** | MedicalHistory 필드 참조 | MedicalHistory 필드 참조 | **별도 모델(§4.4) + 직렬화 계약** 명시 |
| **약관 동의 필드명** | terms_agreed_at | terms_agreed_at | **tos_agreed_at / pp_agreed_at** (terms_agreed_at 폐기, 결정 5) |
| **갈아타기 제안보험 입력** | 미명시 | 미명시 | **portfolio_type=2 등록 엔드포인트 + compare API 연결** 명시 (§4.5) |

---

## 0. 이 문서가 다루는 표면

설계사 하루 두 모드 중 **(A) 기록 모드** — 자투리·이동 중 한 손으로 증권/메모를 던져넣는 마찰 0 구간 — 의 BE·FE 계약을 확정한다. 영업 모드(B: 히트맵·§97 비교서·공유링크)는 별도 문서(`dev/13` 공유링크·북극성, `dev/10` planner_baseline)로 분리하고, 본 문서는 **그 무기들이 먹고 자라는 데이터(고객·보험·담보)를 어떻게 적재하는가**를 다룬다.

```
[증권 사진/PDF 투척]  ─OCR→  [고객 + 보험 + 담보 자동 채움]  ─→  히트맵/비교서/공유링크의 입력
        (기록 모드 A)                  (본 문서)                        (영업 모드 B, 별도 문서)
```

핵심 원칙 4개 (본 문서 전체 관통):
1. **기록은 마찰 0** — 손입력 노동이 3주 내 이탈 원인. 증권 던지면 채워져야 한다.
2. **detect 앞에 컴플라이언스 게이트** — 국외이전 동의(`consent_overseas_at`) 없으면 BE가 412로 물리 차단. UI 숨김은 방어가 아니다.
3. **foliio 재활용 우선** — `Customer`·`CustomerInsurance`·8케이스 calculate·N+1 회귀가드를 vendoring. net-new는 동의 게이트 1필드 + 정규화 사전.
4. **★준법 통제점** — `planner_baseline.source == null`이면 히트맵 충족 판정을 `neutral` 강제. "부족/충분" 단정은 설계사가 기준을 설정한 후에만 발화. 인파는 판단·권유하지 않는다.

---

## 1. 인증 방식 (v2 변경사항 — ★이메일/비밀번호 전용)

### 1.1 인증 파이프라인 변경

v1은 카카오 OAuth(foliio `KakaoLoginView` ♻)를 사용했으나, **v2에서 이메일/비밀번호 전용으로 전면 전환**한다. 카카오 OAuth 코드·뷰·설정을 일절 포팅하지 않는다.

| 흐름 | 구현 |
|---|---|
| 회원가입 | `POST /api/v1/auth/register/` — 이메일·비밀번호·이름 + 약관 동의 통합 |
| 이메일 인증 | 가입 직후 인증 이메일 발송 → 링크 클릭 → 계정 활성화(`User.is_active=True`, `Profile.email_verified_at` 기록) |
| 로그인 | `POST /api/v1/auth/login/` — 이메일·비밀번호 → DRF Token 발급 |
| 비밀번호 찾기 | `POST /api/v1/auth/password-reset/` — 이메일 입력 → 재설정 토큰 링크 발송 → `POST /api/v1/auth/password-reset/confirm/` |
| 로그아웃 | `POST /api/v1/auth/logout/` — 서버 Token 폐기 |

```
[이메일/비번 입력]
   └─ POST /auth/register/
         └─ 인증 이메일 발송
               └─ GET /api/v1/auth/verify-email/?token=<one-time-token>
                     └─ is_active=True → 로그인 가능
                           └─ POST /auth/login/ → DRF Token
                                 └─ Authorization: Token <...> 헤더로 모든 API 인증
```

### 1.2 가입 폼 — 약관 동의 통합

가입 단계에서 약관 동의를 **한 화면에 통합**한다(별도 온보딩 단계 없음).

| 필드 | 필수 | 설명 |
|---|---|---|
| `email` | ✔ | 로그인 ID + 인증 대상 |
| `password` / `confirm_password` | ✔ | 최소 8자, 숫자·문자 혼합 |
| `name` | ✔ | 설계사 이름 |
| 서비스 이용약관 동의 체크 | ✔ | 미동의 시 가입 불가 |
| 개인정보 처리방침 동의 체크 | ✔ | 미동의 시 가입 불가 |
| 마케팅 정보 수신 동의 | 선택 | 선택 미동의 허용 |

**레드라인**: 가입 시 약관 동의(`Profile.tos_agreed_at` / `pp_agreed_at`)는 설계사 본인 약관이다. 고객 국외이전 동의(`Customer.consent_overseas_at`)와 **절대 혼동하지 않는다** — 이 둘의 주체·시점·대상이 다르다(`dev/09 §5`). (`terms_agreed_at` 폐기 — `dev/02 §2.2` 결정 5)

### 1.3 인증 전 접근 차단 (`User.is_active` / `IsEmailVerified`)

이메일 인증을 완료(`User.is_active=True`, `Profile.email_verified_at` 기록)하지 않은 계정은 API 게이트(`IsEmailVerified`)가 403을 반환한다. 인증 이메일 재발송 엔드포인트(`POST /api/v1/auth/resend-verification/`) 별도 제공.

| 화이트리스트(인증 우회) | 이유 |
|---|---|
| 회원가입·로그인·비밀번호 찾기 | 인증 전 동작 필요 |
| 이메일 인증 링크(`/verify-email`) | 인증 전 동작 필요 |
| 공유뷰(`/s/[token]`) | 고객(비로그인) 열람 |
| 멤버십 가격표 | 공개 페이지 |

> **카카오 OAuth 전면 제거**: `KakaoLoginView`, `kakao_login/` 엔드포인트, JS SDK 초기화, Redirect URI 설정, `sessionStorage` 이중호출 가드 — 인파 코드베이스에 일절 존재하지 않는다. foliio의 카카오 관련 파일은 vendoring 대상에서 **명시적으로 제외**한다.

---

## 2. 가시성 매트릭스 — 고객 관련 엔티티 (소유자 전용)

아래 표는 **이 문서가 다루는 고객·보험 관련 엔티티 전체**의 가시성 분류다. "소유자 전용"은 `owner FK` + `OwnedQuerySetMixin` + `IsOwner`의 3중 강제를 의미한다.

| 엔티티 | 가시성 | owner FK | 근거 |
|---|---|---|---|
| `Customer` | **소유자 전용** | `owner(User)` | 고객 정보 = 설계사 자산 |
| `CustomerConsent` | **소유자 전용** | `Customer.owner` 경유 | 고객 동의서 |
| `CustomerInsurance` | **소유자 전용** | `Customer.owner` 경유 | 보험 정보 |
| `InsuranceCoverage` | **소유자 전용** | `CustomerInsurance` 경유 | 담보 데이터 |
| `InsuranceAnalysis` | **소유자 전용** | `owner(User)` | 히트맵·분석 결과 |
| `planner_baseline` | **소유자 전용** | `owner(User)` | 설계사 기준선 |
| `ConsentLog` | **소유자 전용** | `Customer.owner` 경유 | 동의 감사추적 |
| `NormalizationDict` | 공유(관리자만 쓰기) | — | 정규화 사전, 설계사는 읽기만 |
| `UnmatchedLog` | **공유(전역) + 관리자 검수** | — | 미매칭 학습루프 — OCR 경유 전 설계사가 간접 기여, 검수·매핑은 관리자 (`dev/02 §0`) |
| `NorthStarEvent` | 관리자 전용 + 본인 발송 이벤트 | `sender_user` | 계측 로그 |

공유뷰(`/s/[token]`)는 `AllowAny + share_token` 화이트리스트이나, **노출 필드가 물리적으로 제한**된다(`dev/09 §1` — 납입현황 사실·담보 사실만, 판정 prop 물리 부재).

---

## 3. 화면 IA — 기록 모드 동선

```
하단탭(설계사)  [홈] [고객] [＋증권] [캘린더] [내정보]
                        │       │
                        ▼       ▼
              /customer        업로드 드롭존(전역 FAB ⊕)
                 │                 │
       ┌─────────┼─────────┐       ▼
       ▼         ▼         ▼   업로드 큐(썸네일+진행률)
  검색바    정렬·필터칩  고객카드×N    │
  [이름·전화검색]  [전체|만기임박|신규|동의미수신|태그]
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

## 4. 데이터 모델 — foliio 재활용 + net-new

### 4.1 Customer (foliio ♻ — 거의 그대로)

`dev/02 §2`에서 동결된 변경점만. 재활용 필드는 무변경.

| 필드 | 출처 | 비고 |
|---|---|---|
| `name` | ♻ foliio | 공유뷰 노출 시 마스킹(§9.3) |
| `mobile` | ♻ | |
| `birth_day` | ♻ | 공유뷰는 연도만 (추정) |
| `gender` | ♻ (SmallInt 1=남/2=여, nullable) | foliio 2026-06 추가분 계승 |
| `job_code` | ♻ JobRiskCode FK | 직업위험 등급 |
| `medical_histories` | ♻ **CustomerMedicalHistory** (별도 모델, §4.4) | 민감정보 — 국외이전 동의 대상, 공유뷰 물리 제거 |
| `share_token` | ♻ UUID | 공유링크 공개키 |
| `user_view_at` | ♻ | 미열람 액션큐 사유 산출 입력 |
| `color` | ♻ | 설계사 분류용 (태그 색 선택) |
| `memo` | ♻ | 설계사 내부 메모 (타임라인·목록 확장) |
| **`consent_overseas_at`** | **★ net-new** | detect 412 게이트 키 (DateTime, nullable) |
| **`share_expires_at`** | **★ net-new 예약** | 공유 TTL (Q4 미확정, 일단 nullable) |
| **`tags`** | **★ net-new** | 설계사 자유 분류 태그 (M2M 또는 JSON array — §4.3 참조) |

- **`owner` `on_delete=CASCADE`** — 설계사 탈퇴 시 고객 개인정보 자동 삭제. foliio의 `SET_NULL` 패턴(유령행)은 인파에서 **채택 금지** (`dev/02 §3.1` 결정 8). 탈퇴 유예·복구 창은 Subscription 레벨에서 처리(openGap).
- `total_monthly_premiums`: foliio N+1 트랩 계승 — **목록 응답이 row별 `annotate(Sum, filter=portfolio_type=1)`로 내려준다**. FE는 보험별 재계산 금지.

### 4.2 FamilyMember (net-new — 가족구성)

설계사가 고객의 가족 정보를 기록해 **가족 단위 보장 공백 파악** 및 갱신 시 추가 상담 기회를 포착하는 데 쓴다.

```
FamilyMember
──────────────────────────────────────────────
  id              PK
  customer        FK(Customer, on_delete=CASCADE)  -- 소유자는 Customer 경유 설계사
  relation        str            -- 'self' | 'spouse' | 'child' | 'parent' | 'other'
  name            str(null)      -- 가족 이름 (선택)
  birth_day       date(null)     -- 생년월일 (만기·생일 알림 재료)
  gender          smallint(null) -- 1=남/2=여
  memo            str(null)
  created_at / updated_at
──────────────────────────────────────────────
```

- `customer.owner` 경유 소유자 격리 — `FamilyMember` 쿼리셋에도 `filter(customer__owner=request.user)` 강제.
- 공유뷰에서 **노출 0** — FamilyMember는 설계사 내부 도구, 고객에게 보여주는 화면에 물리 부재.
- v1에서 없던 신규 모델. 마이그레이션 순서는 `Customer` 이후.

### 4.3 CustomerTag (net-new — 태그)

설계사가 고객을 자유롭게 분류하는 태그 체계. 고객 목록 필터칩에 연동된다.

```
CustomerTag
──────────────────────────────────────────────
  id              PK
  owner           FK(User)          -- 태그는 설계사 소유 (다른 설계사 태그 공유 X)
  label           str               -- 태그 이름 (예: "VIP", "갱신예정", "자녀관심")
  color           str(null)         -- 목록 색 칩 hex 또는 토큰 키 (추정)
  UNIQUE(owner, label)
──────────────────────────────────────────────

Customer ↔ CustomerTag : M2M (customer_tags 조인 테이블)
```

- `OwnedQuerySetMixin` 적용 — 본인 태그만 조회.
- 공유뷰 노출 0.

### 4.4 CustomerMedicalHistory (foliio ♻ — 별도 모델, 민감정보)

foliio `MedicalHistory`(`customers/models.py`) 무변경 포팅. **병력 = 민감정보 = 국외이전 동의 대상**이므로 Customer 인라인 필드가 아니라 **별도 모델**로 관리한다(`dev/02 §3.4`).

직렬화 계약:
- `GET /api/v1/customer/:id/` 응답 내 `medical_histories` 배열로 중첩 직렬화.
- 공유뷰(`/s/[token]`) 응답 serializer에서 **물리 제거** — `fields` 선언에 포함하지 않는다.
- `ConsentLog(scope=overseas_medical)` + `Customer.consent_overseas_at` 2중 게이트 아래에서만 Claude API 경유 detect에 전달.

```
CustomerMedicalHistory
──────────────────────────────────────────────
  id            PK
  customer      FK(Customer, on_delete=CASCADE)   -- customer__owner 경유 소유자 격리
  disease_name  str       -- 병명/진단
  diagnosed_at  date(null)
  memo          str(null)
  created_at / updated_at
──────────────────────────────────────────────
```

> **레드라인**: `medical_histories` 필드를 Customer JSON에 직접 임베드하거나 flat 직렬화하면 공유뷰 마스킹이 누락될 수 있다 — serializer 계층 분리를 반드시 유지한다.

### 4.5 CustomerInsurance (foliio ♻ — 무변경)

8케이스 calculate·음수 guard(`monthly_non_renewal_premium = max(0, assurance − renewal)`)·`custom_coverages` JSON 전부 재활용. **모델 무변경이 회귀 게이트** — 8케이스 골든 179 passed 불변이 포팅 무결성의 증거.

`portfolio_type` 값:
- `1` = 기존 가입 보험 (비교안내서 좌측)
- `2` = 제안 보험 (비교안내서 우측) ← **갈아타기 비교 입력 엔드포인트** `POST /api/v1/customer/:id/insurance/` 에 `portfolio_type=2`로 등록. 설계사가 신규 제안 상품을 직접 입력하거나 OCR로 투척하면 이 타입으로 저장된다. `GET /customer/:id/compare/` API가 `portfolio_type=1`·`=2`를 pair로 소비(`dev/02 §15.5`).
- `0` = 템플릿

### 4.6 net-new 모델 4종 (정규화·동의·계측)

| 모델 | 핵심 필드 | 역할 |
|---|---|---|
| `NormalizationDict` | `UNIQUE(company, raw_name)`, `std_name`, `category`, `source`(admin_verified/ocr_learned), `hit_count` | 담보명 정규화 정본 — 해자. 베타는 `admin_verified`만 매칭 |
| `UnmatchedLog` | `company`, `raw_name`, `occurrence`(++), `created_at` | 미매칭 학습루프 → admin 1탭 승격 |
| `ConsentLog` | `customer FK`, `scope`(민감/국외/제3자), `doc_version`, `ip`, `agreed_at`(auto_now_add, 불변), `revoked_at` | 국외이전 동의 감사추적 (6요건) — `dev/02 §4.1` 정본 |
| `NorthStarEvent` | `event_type(1~6)`, `share_token`, `sender_user`, `ref_code`, `viewer_fp`, `meta JSON` | 북극성 계측 — **Day1 동결, 사후복원 불가** |

> 담보 트리(StandardCoverage 4계층)는 foliio ♻ **모델 무변경 + 시드 30→100+**. 새 테이블을 만들면 calculate 8케이스가 단절된다 — 절대 금지.

---

## 5. 고객 목록/검색/필터/상세 — API 계약

### 5.1 목록 `GET /api/v1/customer/` (v2 강화: 카드형·태그·만기 배지)

```
GET /customer/?q=홍&sort=expiry&filter=expiring&tags=VIP,갱신예정&page=1
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
      "name": "홍길동",
      "gender": 1,
      "birth_day": "1986-03-12",
      "age": 40,
      "insurance_count": 4,
      "total_monthly_premiums": 287000,
      "last_contact_at": "2026-06-10T09:00:00+09:00",
      "expiry_soon": true,
      "expiry_days_min": 12,
      "consent_overseas_at": null,
      "color": "blue",
      "tags": ["VIP", "갱신예정"],
      "memo_preview": "자녀 보험 관심…",
      "family_count": 3,
      "share_token": "a1b2…"
    }
  ]
}
```

**v2 추가 필드 설명:**

| 필드 | 의미 | FE 사용처 |
|---|---|---|
| `expiry_soon` | D-30 이내 만기 보험 존재 (bool) | 카드 우상단 **빨간 배지** "만기 D-12" |
| `expiry_days_min` | 가장 임박한 만기까지 남은 일수 | 배지 숫자 표시 |
| `tags` | 설계사가 붙인 태그 배열 | 카드 하단 태그 칩 |
| `memo_preview` | `WorkNote` 최신 메모 앞 30자 | 카드 내 메모 미리보기 |
| `family_count` | 가족구성원 수 | 카드 부가 정보 |

| 파라미터 | 값 | 처리 |
|---|---|---|
| `q` | 문자열 | 이름·연락처 부분일치 (BE LIKE, PII 로그 금지) |
| `sort` | `recent`(기본)/`expiry`/`name`/`premium` | **BE 권위 정렬** — FE 재정렬 금지 |
| `filter` | `all`/`expiring`/`new`/`no_consent`/`tagged` | 칩 매핑 |
| `tags` | 콤마 구분 태그 이름 | 다중 태그 AND 필터 |
| `page` | 정수 | DRF 페이지네이션 |

> **탭 전환 시 sort/filter reset** — foliio admin 패턴 계승. 새로고침 보존은 URL searchParams(`?q&sort&filter&tags`)로 FE가 동기화.

### 5.2 고객 카드 UX 스펙 (v2 신규)

카드형 목록(`/customer`)은 기존 테이블 행 대신 **카드 그리드**로 전환한다.

```
┌─────────────────────────────────┐
│ 홍길동  40세 남                [만기 D-12] ← expiry_soon 빨간 배지
│ 010-1234-5678  사무직          │
│ 보험 4건 · 월 287,000원        │
│ 마지막 접촉: 06-10            │
│ 자녀 보험 관심…  ← memo_preview  │
│ [VIP] [갱신예정] ← 태그 칩     │
│ 가족 3명 · 동의 ○             │
└─────────────────────────────────┘
```

- **만기 임박 배지**: `expiry_soon=true`일 때 `--danger` 색 "만기 D-N" 배지. `N = expiry_days_min`.
- **동의 상태 표시**: `consent_overseas_at is null`이면 🔒 잠금 아이콘 (AI 분석 불가 상태 인지).
- **카드 탭**: `/customer/:id` 상세로 이동. 스와이프 액션(모바일): 왼쪽→[메모 추가], 오른쪽→[접촉 기록].
- **빈 상태(고객 0)**: 콜드스타트 `[증권 올리기]` CTA 단일 표시. 스켈레톤 카드로 로딩 표현.

### 5.3 생성 `POST /api/v1/customer/`

```json
// 요청
{
  "name": "홍길동", "mobile": "010-1234-5678",
  "birth_day": "1986-03-12", "gender": 1,
  "job_code": 12, "color": "blue", "memo": "첫 상담. 자녀 보험 관심.",
  "tags": ["VIP", "신규"]
}
// 응답 201 → {id, share_token, ...}
// 한도 초과 시 402 {reason:'CREDIT_EXHAUSTED', limit, remaining}
```
- **`customer_credit` 차감** (foliio 크레딧 엔진 ♻). 베타 `FREE_TIER_UNLIMITED=True`면 무차감.
- `remaining=null` / `is_unlimited=True` → 무제한 (0은 exhausted 아님 — foliio §8 트랩 계승).

### 5.4 상세 `GET /api/v1/customer/:id/`

```json
{
  "id": 1031, "name": "홍길동", "gender": 1, "birth_day": "1986-03-12",
  "job": {"code": 12, "label": "사무직", "risk_grade": 1},
  "medical_histories": [ … ],
  "consent_overseas_at": null,
  "memo": "첫 상담. 자녀 보험 관심.",
  "tags": ["VIP", "갱신예정"],
  "family_members": [
    {"id": 1, "relation": "spouse", "name": "김영희", "birth_day": "1988-05-20", "gender": 2}
  ],
  "insurances": [
    {"id": 88, "company": "삼성생명", "product": "…",
     "portfolio_type": 1, "monthly_premiums": 92000, "expiry_at": "2026-07-05"}
  ],
  "share_token": "a1b2…", "user_view_at": null
}
```

- 상세 화면 탭 4종: **분석**(히트맵·준법 통제점) / **갈아타기**(§97, §5.6) / **공백**(미보유 담보) / **이력**(ActivityLog/타임라인). 보험 적재까지만이 본 문서; 탭 내용은 영업 모드 문서 참조.
- `consent_overseas_at is null` → 분석/갈아타기 탭 **블러+자물쇠 UX**(데이터 게이트 아님 — 412는 detect에만). 동의 완료 시 초록 배지.
- **★ planner_baseline 통제점**: 분석 탭 히트맵 로드 시 `baseline_source`를 BE가 확인한다. `null`이면 `heatmap_status()` = `neutral` 강제. "부족/충분" 판정 문자열은 설계사가 기준을 설정해야만 발화한다 (`dev/10 §3.1` 참조).

### 5.5 수정·삭제

| | 계약 |
|---|---|
| `PATCH /customer/:id/` | 본인만. 빈칸채우기 폼 재사용. 태그·메모·가족구성 업데이트 포함 |
| `DELETE /customer/:id/` | **soft delete**(본인만). foliio `deleted_at` 패턴 |

### 5.6 갈아타기 비교 (§97 비교안내) — 분석 탭 내

§97 비교안내서는 설계사가 기존 보험과 신규 제안 보험을 **조항 단위로 비교**해 고객에게 서면 제공하는 금감원 요건 준수 기능이다. 부당승환(§97 위반) 방어막으로 작동한다.

```
[갈아타기 탭 진입]
   ├ 기존 보험: CustomerInsurance(portfolio_type=1) 자동 로드
   ├ 제안 보험: 설계사가 비교안내 폼에 직접 입력(또는 OCR 투척)
   └ BE compare API → 담보별 유불리 차이표 생성 → 공유링크(비교안내서 전용 URL)
```

**컴플라이언스 강제:**
- 비교안내서의 불리점 셀은 **`--danger`(red) 전용**. 히트맵(amber)과 색 교차 금지.
- "갈아타기 권유" 카피 부재. 인파는 비교 사실을 표시할 뿐, 권유 주체는 설계사.
- 비교안내서 발급 = `NorthStarEvent(event_type=analysis_complete)` 적재.

---

## 6. 고객 등록 — 수기 + OCR 수렴 폼 (v2 강화)

세 진입로가 같은 폼으로 수렴(§3). 폼 필드와 검증:

| 필드 | 필수 | 검증 | OCR 자동채움 |
|---|---|---|---|
| 이름 | ✔ | 1자+ | ◑ 확정/추정 색칩 |
| 생년월일 | ✔ | YYYY-MM-DD | ◑ |
| 성별 | (추정) 선택 | 1/2 | ◑ |
| 연락처 | △ | 휴대폰 정규식 | ✕ (증권에 없음) |
| 직업위험 | △ | JobRiskCode | ✕ (수기) |
| 메모 | — | 자유 텍스트 | ✕ (수기) |
| 태그 | — | 기존 태그 선택 또는 신규 생성 | ✕ |
| 보험사 | ✔(보험행) | enum | ◑ |
| 담보 행 | — | custom_coverages | ◑ 정규화 매칭 |

**가족구성 서브 폼** (선택, 고객 등록 후 추가 가능):
```
가족 구성원 추가 [+ 추가]
  relation(배우자/자녀/부모/기타) → 이름(선택) → 생년월일(선택) → 성별
  저장 → POST /customer/:id/family/
```

**신뢰도 색칩 규칙:** OCR 추출값은 `match_source` 기반 2색 — 🟢 초록=확정(`category_map`/`admin_verified`) / 🟡 노랑=추정(`fuzzy`/`keyword`). 미매칭은 빈칸+회색 안내. 설계사가 노랑 칩을 눈으로 검수 후 저장 → 최종 책임 설계사에게 귀속(컴플라이언스).

---

## 7. 증권 detect (OCR) — 6단계 의존성 파이프라인

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
⑥  ocr 크레딧 차감  (portfolio_type==1 보험만, kind=`ocr`)
        ▼
   응답 {info, ocrResult, match_summary}
```

### 7.1 detect 응답 계약

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

### 7.2 ★ planner_baseline 준법 통제점 — 담보 한눈표·히트맵 연동

OCR로 담보가 적재된 후 히트맵을 그릴 때, **충족 판정(`short`/`enough`)은 설계사가 `planner_baseline`을 설정해야만 발화**한다. 이 흐름이 인파 준법의 심장이다.

```
[detect 완료 → 담보 저장]
       │
       ▼
GET /customer/:id/analysis/  (히트맵 요청, 설계사 인증 필수)
       │
       ▼
 heatmap_status(actual, baseline, mode)   (dev/10 §3.1 — BE 단일 권위)
       │
       ├─ baseline == None OR baseline.source == null
       │       └─▶  status = 'none'(actual==0) 또는 'neutral'(보유)
       │              ★ "부족/충분" 발화 물리 차단
       │
       └─ baseline.source in ('planner', 'preset:*')  AND  mode='graded'
               └─▶  status = 'none' | 'short' | 'enough' | 'over'
                      ★ 설계사 기준 기반 판정
```

**FE 계약:**
- 히트맵 컴포넌트는 BE가 내려준 `status` 문자열을 CSS 클래스로 매핑할 뿐 — **FE 재판정 절대 금지**.
- `neutral` 상태에서 상단 고정 배너: `"기준선 미설정 — 보유 여부만 표시 중. [내 기준 설정 →]"` (클릭 시 `/settings/baseline`).
- 공유뷰는 `severity='none'|'neutral'`만 — `'short'|'enough'`는 **타입에서 물리 제외**(컴파일 차단, `dev/08 §1`).

### 7.3 추출률 게이트 (추정 — 분모 미확정)

| 항목 | 값 | 상태 |
|---|---|---|
| 목표 추출률 | ≥85% | 골든셋 107PDF |
| 정규화 오매핑률 | ≤5% | (추정) |
| 분모 정의 | 7필드 vs 100+필드, 필드별 가중치 | **미확정(G-N8)** — PASS/FAIL 측정 불가 |

### 7.4 부분 실패·다건

- 첫 슬라이스는 **단건 happy path만**. 다건 `detect_batch`(여러 장 동시 투척)는 2차 웨이브.
- 부분 실패(일부 담보 미매칭)는 정상 응답 + `match_source:none` 표기 — 설계사 수기 보정 폴백.

---

## 8. 컴플라이언스 게이트 — 국외이전 동의

> `dev/09` 절대원칙: 병력 등 민감정보가 미국(Anthropic)으로 나가므로 **고객 동의 없이 detect 호출 불가**. UI 숨김 ≠ 방어, BE 412 차단.

### 8.1 동의 흐름

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

### 8.2 ConsentLog 6요건 (감사추적)

| 요건 | 필드 |
|---|---|
| 누가 | `customer FK` (+ 대리 설계사 `sender_user`) |
| 언제 | `agreed_at` (auto_now_add, 불변) |
| 무엇을 | `scope`(민감정보/국외이전/제3자) |
| 버전 | `doc_version` |
| 어디서 | `ip` |
| 철회 | `revoked_at` |

- **첫 슬라이스**: `consent_overseas_at` + 412 배선만. ConsentLog 풀스택(6요건·doc_version·회수동선)은 P1.
- **레드라인**: "안전배지/심의완료" 카피 0건 — `grep` 골든 회귀로 차단. 인파는 중개·권유하지 않는다.

---

## 9. 공유뷰 PII — 보수적 디폴트

> 본 문서는 적재만 다루지만, 적재 데이터가 공유뷰로 새는 범위를 여기서 못박는다(공유뷰 풀계약은 `dev/08`).

### 9.1 노출 허용 (사실만)

납입현황(납입률/낸·남은 보험료/만기) + 보유담보(이름 + 보장금액). **부족/충분/추천 판정 prop 물리 부재.**

### 9.2 노출 금지

병력(민감정보)·주민번호·연락처·직업위험·메모(`WorkNote`)·태그·가족구성(`FamilyMember`) — 공유뷰 응답에서 **물리 제거**(serializer 필드 부재).

### 9.3 마스킹 디폴트 (§8 확정 전 보수적)

| 항목 | 디폴트 |
|---|---|
| 고객명 | 첫 글자 + `**` (홍**) |
| 생년월일 | 연도만 (1986년생) (추정) |
| 병력 | 노출 0 |
| 가족구성 | 노출 0 |
| 태그 | 노출 0 |

→ 마스킹 규칙 정본화 전까지 BE가 **이름 마스킹·연도만** 강제. 단톡방 영구노출 사고 방지.

---

## 10. 수용기준 (AC) 체크리스트

**인증 (v2 신규)**
- [ ] AC-A1 이메일/비밀번호 가입 → 이메일 인증 → 로그인 → DRF Token 발급 정상 동작.
- [ ] AC-A2 미인증(`User.is_active=False`) 상태에서 보호 API 호출 → `IsEmailVerified` 게이트 403.
- [ ] AC-A3 비밀번호 재설정 토큰 1회 사용 후 무효화.
- [ ] AC-A4 카카오 OAuth 관련 코드·엔드포인트·설정 파일이 코드베이스에 **완전 부재** (grep 검증).
- [ ] AC-A5 가입 폼에서 약관 동의(서비스/개인정보 필수, 마케팅 선택) 통합 처리.

**고객 CRUD (v2 강화)**
- [ ] AC-C1 목록 `GET /customer/`가 row별 `total_monthly_premiums` annotate를 내려준다(N+1 회귀 테스트 포팅, FE 재계산 0).
- [ ] AC-C2 `sort`/`filter`는 BE 권위. FE 재정렬 코드 부재.
- [ ] AC-C3 생성 시 `customer_credit` 차감, 베타 무제한(`remaining=null→∞`, 0은 exhausted 아님).
- [ ] AC-C4 삭제는 soft delete, 본인만. `Customer.owner on_delete=CASCADE` — 설계사 탈퇴 시 고객 행 연쇄 삭제(`dev/02` 결정 8).
- [ ] AC-C5 빈 상태(고객0)=콜드스타트 `[증권 올리기]` CTA, 로딩=스켈레톤 카드.
- [ ] AC-C6 `expiry_soon=true`일 때 카드 우상단에 만기 임박 배지("만기 D-N") 표시.
- [ ] AC-C7 태그 CRUD(`CustomerTag`) + 목록 필터칩 `?tags=` 파라미터 동작.
- [ ] AC-C8 가족구성(`FamilyMember`) CRUD — `POST /customer/:id/family/`, 공유뷰 노출 0.
- [ ] AC-C9 메모(`memo`) 저장·수정·목록 미리보기(30자) 표시.
- [ ] AC-C10 가시성 격리: 설계사 A가 설계사 B의 고객을 조회하면 404 (회귀 테스트).

**증권 detect(OCR)**
- [ ] AC-O1 detect 호출 전 `consent_overseas_at is None`→**412** `CONSENT_OVERSEAS_REQUIRED`(detect에만, UI 숨김 아닌 BE 차단).
- [ ] AC-O2 6단계 순서 강제 + `_add_coverage` 3.5순위 normalization 삽입.
- [ ] AC-O3 8케이스 골든 **179 passed 불변**(포팅 무결성 회귀 게이트).
- [ ] AC-O4 `match_source` enum 5종으로 신뢰도 색칩(🟢확정/🟡추정/빈칸 미매칭).
- [ ] AC-O5 베타는 `admin_verified`만 매칭(오매핑 0). OCR=Haiku, BE 100% 경유.
- [ ] AC-O6 음수 guard `max(0, assurance−renewal)` 적용.

**★ planner_baseline 준법 통제점**
- [ ] AC-P1 `planner_baseline.source == null`이면 히트맵 모든 셀 `neutral`/`none`만. "부족(`short`)/충분(`enough`)" 문자열 **미발화** (런타임 + grep 검증).
- [ ] AC-P2 설계사가 `planner_baseline`을 1행 이상 저장한 후 `graded` 모드에서만 `short`/`enough` 발화.
- [ ] AC-P3 공유뷰 `severity` 타입 유니온이 `'none'|'neutral'`만 — 컴파일 차단.
- [ ] AC-P4 히트맵 `neutral` 모드에서 상단 배너 `"기준선 미설정 — 보유 여부만 표시"` 고정 노출.

**컴플라이언스**
- [ ] AC-G1 ConsentLog 6요건 감사추적(첫 슬라이스는 `consent_overseas_at`+412 배선만).
- [ ] AC-G2 공유뷰 병력·연락처·직업·메모·태그·가족구성 물리 제거 + 이름 마스킹·연도만.
- [ ] AC-G3 "안전배지/심의완료" 카피 0건(grep 골든 회귀).
- [ ] AC-G4 설계사 약관 동의(`Profile.tos_agreed_at` / `pp_agreed_at`) ≠ 고객 국외이전 동의 (`Customer.consent_overseas_at`) — 혼용 코드 0건. `terms_agreed_at` 폐기 확인(grep 검증).

---

## 11. 기획 갭 (blocking ★ / non-blocking)

| # | 갭 | 영향 | 상태 |
|---|---|---|---|
| G-1 ★ | **정규화 사전 v0 시드 ~150행**(상위30담보×5사) + 보험사 `company` code enum 실번호 | 미완 시 `_add_coverage` 매칭 불가 → 히트맵 거짓=정직성 레드라인 | D-0 전제. 데이터 인력 2~3일 선투입, owner·일정 미확정 |
| G-2 ★ | **OCR 골든셋 107PDF 정답 라벨링** + 실고객 PII(병력/주민번호) 마스킹·익명화 후 QA 픽스처 커밋(gitleaks 통과) | 추출률 85% PASS/FAIL 측정 불가 | 선결 |
| G-3 ★ | **OCR 추출률 85% 게이트 분모 정의**(7필드 vs 100+필드, 필드별 가중치, 오매핑 ≤5% 임계) | PASS/FAIL 판정 불가 | 미확정 |
| G-4 ★ | **국외이전 동의 1탭 법적 안전선 대표 승인**(외부 법무자문 없음·CPO=CTO, 보수적 자체처리) | 막히면 detect 전체 봉인 → 수기입력+히트맵 neutral 데모로 우회 | 대표 승인 게이트 |
| G-5 ★ | **북극성 6종 스키마 Day1 동결**(payload·중복제거키·`?ref=` 형식 첫 마이그레이션) | 사후복원 불가 — Sprint1 착수 절대 선행 | 미동결 |
| G-6 | 보험사 `company` code enum 실번호 체계(청약서·약관 대조) | NormalizationDict UNIQUE 키이자 정규화 정본 | G-1과 묶임 |
| G-7 | 공유뷰 PII 노출범위 확정(고객명 마스킹/gender null/병력) — 현재 보수적 디폴트로만 우회 | 개인정보 사고 | §8 미결 |
| G-8 | `ocr` 크레딧(kind=`ocr`) 무료 한도 숫자(공유뷰 발급 차감 여부 포함) | 베타 90일 실측 전 추정 유지 | 추정 |
| G-9 | 정규화 자동승격 임계(`hit_count≥N → ocr_learned`) 운영주체·검수 UI | 베타는 `admin_verified`만으로 우회 | non-block |
| G-10 | 직업위험(JobRiskCode) 입력 UX·필수여부 + 성별 null 표기 규칙 | 폼 props 확정 불가 | non-block, 출시 전 확정 |
| G-11 | `share_token` 만료 TTL·회수 동선·보존기간·만료 응답코드(410?) | 단톡방 영구노출 | `share_expires_at` 예약만, Q4 미확정 |
| G-12 (v2.1 해소) | **이메일 발송 인프라** = **Resend 확정** (`dev/20` 결정 15). TTL: 이메일 인증 24h, 비번 재설정 1h. 재발송 rate-limit 구현 필요 | 인프라 선택 완료 — Resend API key·환경변수 세팅 남음 | dev/20 참조 |
| G-13 (v2 신규) | **`CustomerTag` 정렬·색·최대 개수 UX 규칙** 미확정 | 카드 UI overflow 처리 불가 | non-block |
| G-14 (v2 신규) | **`FamilyMember` 보험 연결** — 가족 구성원 보험을 별도 `CustomerInsurance`로 관리 vs JSON만 유지 | 가족 단위 분석 범위 결정 | PM 결정 필요 (추정: 베타는 JSON만, 분석 연결은 P1) |

---

## 12. 마이그레이션·착수 순서

```
1. makemigrations + migrate
     └ NorthStarEvent 포함 (★ Day1 동결, 사후복원 불가 — G-5)
2. seed_taxonomy   (최선행 — 모든 분석 입력)
     ├ 담보 30→100+ 시드
     └ NormalizationDict v0 ~150행 (G-1 — owner 미정)
3. loadinitialmemberships  (ocr·ai_compare·analysis·promotion 크레딧 kind 4종, 0=무제한 sentinel)
4. vendoring  weapon → inpa (gunicorn 8001, inpa_db)
     └ 제외 대상: KakaoLoginView, kakao_login endpoint, JS SDK 초기화 코드 (★ v2 전면 제거)
5. 신규 모델 migrate
     ├ CustomerTag + Customer↔CustomerTag M2M
     ├ FamilyMember
     └ planner_baseline (dev/10 §2.4 순서 준수: seed_taxonomy 이후)
```

**BE blocking 5종 (Sprint0 게이트):** ①북극성 6종 스키마 동결 ②정규화 v0 ~150행 + 보험사 enum + 골든셋 107PDF ③insights 카피규칙(공유뷰, `dev/08`) ④국외이전 동의 1탭 대표승인 ⑤chart_based_amount 100+ 시드값(히트맵, `dev/10`). ~~이메일 발송 인프라~~ → **Resend 확정(G-12 해소, `dev/20`)**. 코드는 따라온다 — **잠가야 할 건 데이터·법무·계측·인프라 4종이다.**
