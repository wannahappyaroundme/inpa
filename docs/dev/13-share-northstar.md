# 공유링크 & 북극성 계측

> 인파(Inpa) 개발 기획서 — dev/13
> 정본 교차: `dev/02-data-model-and-api.md`(모델·크레딧·§97), `dev/07-api-data-contracts.md`(detect 6단계·공유뷰·히트맵), `dev/09-compliance.md`(컴플라이언스 절대원칙)
> 작성 2026-06-19. 이 문서가 잠그는 건 **공유링크의 생명주기**와 **북극성 6종 이벤트 스키마**. 둘 다 **Day1 동결 = 사후복원 불가**. 구현 코드가 아니라 계약·구조·흐름을 못박는다.

---

## 0. 왜 이 문서가 가장 위험한가

북극성=**발송 × 열람 × 귀속**(곱셈형). 곱셈형 지표는 한 항이라도 사후에 계측을 붙이면 그 이전 데이터가 영구 공백이 된다. 특히 **귀속(`referral_attributed`)** 과 **열람(`share_view`)** 은 첫 마이그레이션에 스키마가 박혀 있지 않으면 복원이 불가능하다. MAU·전환율은 사후 재집계가 되지만, "누가 보낸 링크를 누가 열어서 누구에게 귀속됐는가"는 그 순간 기록하지 않으면 영원히 사라진다.

```
북극성 = Σ(share_link_create) × P(share_view | create) × P(referral_attributed | view)
          ─────────────────    ─────────────────────    ─────────────────────────
          발송 (설계사 행동)      열람 (고객 행동, 서버측정)    귀속 (인바운드 신규)
```

그래서 이 문서의 절대 규칙 3가지:
1. **6종 이벤트 스키마는 Sprint0에 동결**한다. 개발 D-0 이전에 잠그지 못하면 Sprint1 착수 불가.
2. **`share_view`는 BE 서버측정**한다. 클라이언트 측정은 카톡 인앱 프리뷰·봇이 분모를 오염시켜 신뢰 불가.
3. **공유뷰는 '사실'만** 노출한다. 부족/충분/추천 판정 prop은 **물리적으로 부재**(컴플라이언스 절대원칙, dev/09).

---

## 1. 공유링크 생명주기 — share_token

### 1.1 상태 머신

공유링크는 `Customer.share_token`(UUID) 1개에 종속된다. foliio 패턴(`generate_share_link/`)을 재활용하되, 인파는 **만료·회수**를 net-new로 추가한다.

```
                 generate_share_link/
   [없음] ──────────────────────────▶ [활성 ACTIVE]
                                          │   token=UUIDv4, share_expires_at=now+TTL
                                          │
            ┌─────────────────────────────┼─────────────────────────────┐
            │ rotate (재발급)              │ 만료 (now>expires_at)        │ 회수 (revoke)
            ▼                             ▼                             ▼
   [활성: 새 token]              [만료 EXPIRED]                  [회수 REVOKED]
   (구 token 즉시 무효)          410 Gone + 안내                 410 Gone + 안내
            │                             │                             │
            └─────────────────────────────┴──── 재발급 시 ─────────────▶ [활성: 새 token]
```

| 상태 | 진입 조건 | 응답 | viewer 노출 |
|---|---|---|---|
| ACTIVE | 발급/재발급 직후, `now < share_expires_at`, `revoked_at is None` | 200 + 공유뷰 | 정상 |
| EXPIRED | `now >= share_expires_at` | 410 Gone | "만료된 링크입니다" 안내만, **데이터 0** |
| REVOKED | `revoked_at is not None` | 410 Gone | "회수된 링크입니다" 안내만, **데이터 0** |
| INVALID | token 미존재/형식오류 | 404 | "잘못된 링크입니다", **데이터 0** |

핵심 레드라인: **EXPIRED/REVOKED/INVALID 모든 분기에서 고객 데이터(납입현황·담보) 노출 0**. 민감 분석이 만료 후에도 단톡방 영구 링크로 새어나가는 사고 방지.

### 1.2 발급/회수/만료 계약

| 동작 | 엔드포인트 | 권한 | 효과 |
|---|---|---|---|
| 발급/재발급 | `POST /customer/:id/generate_share_link/` | 본인(`IsOwner`) | 새 UUIDv4 token + `share_expires_at=now+TTL`, **구 token 즉시 무효**(rotate=회수 포함) |
| 회수 | `POST /customer/:id/revoke_share_link/` (신규 ✦) | 본인 | `revoked_at=now`, token 유지하되 410 게이트 |
| 만료(자동) | (배치/조회시점 판정) | — | `now>=share_expires_at`→410, 별도 API 없음 |
| 조회 | `GET /customer/:id/share/analysis/?token=&ref=` | AllowAny + token | 200/410/404 분기 |

- **TTL 기본값 (추정)**: 90일. 영구 노출 방지 vs 설계사 재발송 마찰 사이 균형. **미결 — 기획서 확정 필요**(아래 §6 Q1).
- **rotate 정책**: 재발급 시 구 token은 즉시 죽는다. 이미 카톡으로 나간 구 링크는 410. 설계사가 "다시 보내기" 누르면 새 token 발급 → 구 link 사용자는 만료 안내.
- **noindex 강제**: 공유뷰 응답 헤더 `X-Robots-Tag: noindex, nofollow` + HTML `<meta name="robots" content="noindex">`. SSR(카톡 OG)은 허용하되 검색엔진 색인은 물리 차단. 민감정보가 구글에 잡히는 사고 방지.

### 1.3 공유뷰 응답 계약 (컴플라이언스 물리강제)

`GET /customer/:id/share/analysis/?token=&ref=` 는 `calculate_total_analysis`(foliio ♻) 출력을 **그대로** 내리되, 판정 prop은 **타입에서 물리 제외**한다.

```jsonc
// 200 OK — 공유뷰 페이로드 (사실만)
{
  "customer": {
    "name_masked": "홍**",          // 이름 마스킹 (보수적 디폴트, §6 Q3)
    "gender": 1,                     // 1=남/2=여
    "birth_year": 1985              // 연도만 (생월일 마스킹)
    // ⚠️ medical_histories 미포함 (민감정보, 공유뷰 노출 범위 미확정 → 보수적 제외)
  },
  "payment_status": {               // ✅ '사실'
    "total_monthly_premium": 187000,
    "paid_amount": 4200000,
    "remaining_amount": 9800000,
    "next_expiry_at": "2031-03-01"
  },
  "coverages": [                     // ✅ '사실' — 보유 담보 + 보장금액만
    { "name": "암진단비", "assurance_amount": 30000000 },
    { "name": "뇌혈관질환진단비", "assurance_amount": 0, "severity": "none" }
    // ⚠️ "severity" 는 neutral 모드에서 'none'(0원)만 발화. 'short'|'enough' 타입 부재.
  ],
  "insights": [                      // 얇게 덧붙임 — 카피 규칙 §6 Q2 미결
    { "type": "none", "text": "뇌혈관질환 담보는 현재 미보유 상태입니다." }
    // ⚠️ '부족'/'추천' 단정 금지. none(미보유) 사실 진술만.
  ],
  "disclaimer": "본 자료는 설계사가 제공하는 1차 보조자료이며, 최종 판단과 책임은 담당 설계사에게 있습니다."
}
```

```jsonc
// 410 Gone — EXPIRED/REVOKED
{ "reason": "SHARE_LINK_EXPIRED" | "SHARE_LINK_REVOKED", "detail": "..." }
// 데이터 필드 일절 없음
```

**타입 경계 (dev/09 절대원칙, CTO 입장 계승)**: 공유뷰 컴포넌트 `severity` 유니온은 `'none' | 'neutral'` 만 허용. `'short' | 'enough'` 는 **타입에서 제외 = 컴파일 차단**. 런타임 가드가 아니라 컴파일 타임 차단이라 "실수로 부족 표기"가 물리적으로 불가능하다. `DisclaimerFooter` 상시 고정(스크롤·접기 불가).

---

## 2. 북극성 6종 이벤트 — 스키마 동결 (★Day1 절대전제)

### 2.1 이벤트 6종 정의

```
파이프라인 위치별 이벤트 (설계사 깔때기):

  [증권 투척]      [분석 완료]        [링크 발급]         [복사]              [열람★]          [귀속★]
       │               │                  │                  │                  │                │
  ocr_upload ──▶ analysis_complete ──▶ share_link_create ──▶ share_clipboard_copy ──▶ share_view ──▶ referral_attributed
   (설계사)         (BE 연산)          (설계사 행동)       (발송 프록시)       (고객, 서버측정)   (인바운드 신규)
```

| # | event_type | 발생 시점 | 측정 주체 | 신뢰도 | 비고 |
|---|---|---|---|---|---|
| 1 | `ocr_upload` | 증권 detect 호출 성공 | BE | 보조 | 깔때기 입구. 활동량 |
| 2 | `analysis_complete` | `calculate_total_analysis` 완료 | BE | 보조 | 분석=미끼 지표 |
| 3 | `share_link_create` | `generate_share_link/` 성공 | BE | **발송(곱셈 1항)** | 설계사 행동 |
| 4 | `share_clipboard_copy` | 클립보드 복사 클릭 | FE→BE | 보조(발송 프록시) | **복사≠발송**, 단정 금지 |
| 5 | `share_view` ★ | 공유뷰 200 응답(서버) | **BE 서버측정** | **열람(곱셈 2항)·신뢰 KPI** | viewer_fp 중복가드 |
| 6 | `referral_attributed` ★ | `?ref=` 보유 view에서 신규 인바운드 | BE | **귀속(곱셈 3항)** | ref_code × share_token |

**첫 슬라이스 성공 정의 = `share_view` 1건 증명.** MAU·전환율은 허영지표로 강등. "보냈고, 열렸다"가 곱셈의 첫 두 항이고, 이게 인파 정체성(분석툴 → 영업 OS)의 계측적 증거다.

### 2.2 `NorthStarEvent` 스키마 (첫 마이그레이션 고정)

`dev/07 §5.4` 기반. **이 표가 Sprint0 동결 대상.** 사후 컬럼 추가는 가능하나, 기존 컬럼 의미 변경·삭제는 귀속 영구 파손.

```jsonc
NorthStarEvent {
  "id":           "BigAutoField PK",
  "event_type":   "SmallInt 1~6 (위 표 # 고정 — 절대 재배치 금지)",
  "share_token":  "UUID, null (1·2번 이벤트는 token 무관)",
  "sender_user":  "FK User, null=SET_NULL (발신 설계사 — 탈퇴해도 이벤트 보존)",
  "ref_code":     "CharField, null (귀속 코드, §3)",
  "channel":      "CharField (kakao/clipboard/device/web)",
  "viewer_fp":    "CharField, null (비식별 지문 — 5·6번 중복제거 키)",
  "meta":         "JSONField (확장 슬롯 — 사후 추가는 여기로만)",
  "created_at":   "DateTime auto_now_add (UTC 저장, KST 표기)"
}
```

**설계 원칙 — 왜 단일 테이블인가**: 6종을 별 테이블로 쪼개면 깔때기 조인이 6중 조인이 되고, 사후 이벤트 추가 시 마이그레이션이 6벌이 된다. `event_type` enum + `meta JSON` 확장 슬롯으로 **단일 테이블 append-only 로그**를 만든다. 이게 곱셈 깔때기를 단일 GROUP BY로 집계 가능하게 한다.

```sql
-- 북극성 깔때기 1쿼리 (개념)
SELECT event_type, COUNT(DISTINCT viewer_fp) AS unique_n, COUNT(*) AS raw_n
FROM northstar_event
WHERE created_at >= :since
GROUP BY event_type;
-- share_view(5)의 unique_n = 신뢰 KPI 분자
```

### 2.3 인덱스 / 보존 (추정)

```
INDEX (event_type, created_at)        -- 깔때기 시계열
INDEX (share_token)                   -- 링크별 추적 (create→view 매칭)
INDEX (ref_code, event_type)          -- 귀속 집계
INDEX (sender_user, created_at)       -- 설계사별 KPI 카드
보존: append-only, soft-delete 없음. 개인정보 아님(viewer_fp=비식별). 보존기간 무기한 (추정 — §6 Q4)
```

---

## 3. 귀속 — `?ref=` × `share_token`

### 3.1 귀속 흐름

```
설계사 A (ref_code=A7K3) ──[공유링크 발송]──▶  https://inpa.kr/s/<token>?ref=A7K3
                                                          │
                                              고객/잠재고객 열람 (share_view, ref_code=A7K3 기록)
                                                          │
                                          그 viewer가 [나도 인파 쓰기] → 카카오 가입
                                                          │
                                       referral_attributed (sender_user=A, ref_code=A7K3)
                                                          │
                                       설계사 A 액션큐 "🔗인바운드" 카드 + 귀속 크레딧
```

귀속의 정의: **`?ref=` 보유 공유링크를 열람한 viewer가 신규 가입**하면 그 가입을 발신 설계사에게 귀속. 이게 북극성 곱셈의 마지막 항이자 인파의 바이럴 루프(설계사→고객→고객의 지인 설계사)이다.

### 3.2 ref_code 발급 체계 — ★미결(blocking)

`ref_code`는 귀속 정확도의 근간인데 **발급 로직이 Day1 스키마만 있고 공백**이다. 동결해야 할 항목:

| 항목 | 옵션 | (추정) 디폴트 |
|---|---|---|
| 생성 | User당 1개 영구 vs 링크당 1개 | User당 1개 영구(`User.ref_code`) |
| 형식 | 짧은 base32(예 `A7K3`) vs UUID | base32 6자 (URL 친화·공유 마찰↓) |
| 유일성 | UNIQUE 제약 | `UNIQUE(ref_code)` |
| 위변조 | 추측 가능 short code의 악용 | (추정) 귀속은 가입 1회 한정 + sender≠viewer 검증 |

> **이건 §6 Q5로 Sprint0 게이트.** ref_code 없이도 `share_view`(열람)는 측정되지만, `referral_attributed`(귀속=곱셈 3항)는 ref_code 체계 없이 측정 불가.

### 3.3 viewer_fp — 분모 오염 방지 (★미결)

`share_view`가 신뢰 KPI인 이상, **분모 오염(카톡 인앱 프리뷰·봇·설계사 본인 미리보기)을 막는 viewer_fp 중복제거 규칙**이 동결돼야 한다.

```
viewer_fp = 비식별 지문 (개인정보 아님 — 해시 기반)
  구성 후보 (추정): hash(IP 대역 + User-Agent + Accept-Language) — 일별 솔트

중복/오염 제거 규칙 (동결 필요):
  ① 동일 (share_token, viewer_fp) 24h 내 재열람 → 1건으로 카운트
  ② User-Agent = 카톡 인앱 프리뷰 봇(KAKAOTALK-Scrap 등) → share_view 제외(별도 raw 로그만)
  ③ 알려진 봇/크롤러 UA → 제외
  ④ sender_user 본인 열람(로그인 세션 일치) → 보조 카운트, 신뢰 KPI 분자 제외
```

핵심: **카톡으로 링크 보내면 카톡 서버가 OG 프리뷰용으로 먼저 1회 긁는다**. 이걸 share_view로 세면 "보내자마자 열람 1" 거짓 신호 → 분모 영구 오염. UA 필터가 Day1에 없으면 첫 데이터부터 오염된다.

---

## 4. 이벤트 발화 지점 — 6종 트리거 매핑

각 이벤트가 **어느 BE 흐름에서, 무엇을 입력으로** 발화되는지 계약. FE는 4번(clipboard_copy)만 트리거하고 나머지는 BE 권위.

```
① ocr_upload          ← detect 6단계 ⑥ ai_credit 차감 직후 (성공 경로만)
                         meta: {customer_id, match_rate, source_breakdown}

② analysis_complete   ← calculate_total_analysis 반환 직후
                         meta: {customer_id, coverage_count}

③ share_link_create   ← generate_share_link/ 성공, token 발급 트랜잭션 내
                         share_token=신규, channel=web, sender_user=request.user

④ share_clipboard_copy← FE [복사] 클릭 → POST /event/clipboard_copy/ (경량 엔드포인트)
                         channel=clipboard. ⚠️ delivery='clipboard' 고정(자동발송 사칭 금지)

⑤ share_view ★        ← GET /share/analysis/ 200 응답 직전, viewer_fp 산출 후
                         중복가드(§3.3) 통과 시에만 적재. ref_code 동반 기록.

⑥ referral_attributed★← 신규 카카오 가입(KakaoLoginView) 시 세션에 ref_code 보유 확인
                         → sender_user 역산 적재. sender≠viewer 검증.
```

**컴플라이언스 못박기**: ④ clipboard_copy의 `channel='clipboard'`, `delivery='clipboard'`는 **자동발송이 아님을 계측 레벨에서 고정**. 인파는 카톡 자동발송을 하지 않는다(dev/09). "복사해서 설계사가 직접 붙여넣음"이 유일한 발송 경로 → 계측도 이를 사칭하면 안 된다.

---

## 5. Day1 동결 체크리스트

Sprint0 종료 = 아래 전부 ✅ 여야 Sprint1(공유링크 구현) 착수 가능.

### 5.1 스키마 동결 (사후복원 불가 — 절대)
- [ ] `NorthStarEvent` 6종 `event_type` enum **번호 고정**(1~6, 재배치 금지)
- [ ] `NorthStarEvent` 컬럼 9종(`event_type/share_token/sender_user/ref_code/channel/viewer_fp/meta/created_at/id`) **첫 마이그레이션 포함**
- [ ] `Customer.share_expires_at` + `revoked_at` 필드 마이그레이션 포함
- [ ] 인덱스 4종(event_type+created_at / share_token / ref_code+event_type / sender_user+created_at)
- [ ] `meta JSON` 확장 슬롯 합의(사후 추가는 meta로만, 기존 컬럼 불변)

### 5.2 측정 무결성 동결
- [ ] `share_view` = **BE 서버측정** 확정(클라 측정 금지)
- [ ] viewer_fp 구성·중복제거 규칙 4종(§3.3) 동결
- [ ] 카톡 인앱 프리뷰 봇 UA 제외 목록 1차 작성
- [ ] `share_clipboard_copy` = 발송 프록시(보조지표), 신뢰 KPI 아님 명시

### 5.3 귀속 동결
- [ ] `ref_code` 발급 체계(생성·형식·유일성·위변조) §6 Q5 확정
- [ ] `?ref=` URL 형식 + 가입 세션 전달 방식 확정
- [ ] sender≠viewer 검증 룰

### 5.4 컴플라이언스 동결
- [ ] 공유뷰 `severity` 유니온 `'none'|'neutral'`만 — `'short'|'enough'` **타입 제외**
- [ ] 판정 prop 공유뷰 페이로드 **물리 부재** 확인
- [ ] `DisclaimerFooter` 상시 고정
- [ ] noindex(`X-Robots-Tag` + meta) 강제
- [ ] EXPIRED/REVOKED/INVALID 전 분기 데이터 노출 0

---

## 6. 미결 항목 (기획서가 잠가야 BE 착수)

| # | 미결 | 영향 | blocking? | (추정) 디폴트 |
|---|---|---|---|---|
| Q1 | share_token **TTL** + 회수 동선 + 만료 응답코드 | 영구노출 사고 vs 재발송 마찰 | 중 | 90일 TTL, 만료=410 |
| Q2 | 공유뷰 **insights 카피 규칙**(우선순위·표기상한·반올림) | 고객 노출 = 정직성 직접적용 | **상(blocking)** | none 미보유 진술만, Top3 상한, 만원 반올림 |
| Q3 | 공유뷰 **PII 노출범위**(고객명 마스킹/gender/병력) | 개인정보 사고 | **상(blocking)** | 이름 마스킹·birth_year만·병력 제외 |
| Q4 | `NorthStarEvent` **보존기간** | 비식별이라 낮음 | 하 | 무기한 append-only |
| Q5 | **ref_code 발급 체계**(생성·유일성·위변조) | 귀속 정확도 근간 | **상(blocking)** | User당 영구 base32 6자, UNIQUE |
| Q6 | viewer_fp **중복제거 규칙** 최종 확정(봇 UA 목록) | share_view 분모 오염 | **상(blocking)** | §3.3 4종 룰 + 카톡 봇 UA 제외 |

### 6.1 BE blocking 4종 (Sprint0 게이트, 코드보다 먼저)
```
1. 북극성 6종 스키마 동결 (사후복원 불가)         → §5.1
2. ref_code 발급 체계 (귀속 곱셈 3항 근간)          → §3.2 / Q5
3. viewer_fp 중복제거 규칙 (share_view 분모 무결성)  → §3.3 / Q6
4. 공유뷰 insights 카피 + PII 범위 (정직성·개인정보)  → Q2 / Q3
```

### 6.2 비-blocking (Sprint1 중 확정 가능)
- share_token TTL 수치(90일은 디폴트로 착수 가능, 운영 중 조정)
- NorthStarEvent 보존기간(무기한 디폴트로 우회)
- clipboard_copy 경량 엔드포인트 rate-limit 정책

---

## 7. 정리 — 이 문서가 못박은 것

```
동결(사후 불가)            │ 우회 가능(디폴트로 착수)
──────────────────────────┼──────────────────────────
NorthStarEvent 6종 스키마  │ share_token TTL 수치
event_type enum 번호       │ 이벤트 보존기간
share_view BE 서버측정      │ clipboard rate-limit
viewer_fp 중복제거 키       │ insights 표기상한 미세조정
share_token 만료/회수 필드  │
공유뷰 severity 타입 제외   │
```

**한 줄 결론**: 인파의 북극성은 곱셈형이라 **계측이 코드보다 먼저**다. `NorthStarEvent` 6종 스키마 + `Customer.share_expires_at/revoked_at` 을 **첫 마이그레이션에 박는 것**이 Sprint0의 단일 최우선 게이트다. `share_view`는 서버가 센다, `severity`는 타입에서 부족/충분을 지운다, 만료된 링크는 데이터를 0으로 닫는다 — 이 셋이 사후에 못 고치는 결정이다.