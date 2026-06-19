# 개발 착수 전 체크리스트 (Readiness) — 인파(Inpa)

> **문서 위치**: `dev/05-pre-dev-readiness.md`
> **목적**: 코드 한 줄 쓰기 전, 무엇이 막혀 있는가를 owner·blocking으로 못 박는다.
> **핵심 결론**: 진짜 블로커는 코드가 아니라 **(1) 담보 정규화 사전 (2) 충족 3색 임계치 (3) 북극성 로깅 스키마 (4) 디자인 토큰 SSOT**. 이 넷이 잠기면 개발은 따라온다.
> **두 축 분리**: 법무 게이트(출시 가부, 코드 아님)와 디자인/인프라/데이터/계측 blocking(착수 가부)은 별개 트랙이다. 법무가 막혀도 중립 기능(OCR·히트맵)은 선출시한다.

---

## 0. 이것부터 — 7일 착수 시퀀스

P0 blocking 항목을 **의존성 순서**로 정렬했다. 위에서부터 잠가야 아래가 풀린다.

```
D-0  ┌─ [데이터] 담보 정규화 사전 seed (seed_standard_coverages.py)  ← 모든 분석의 입력
     │   동시  [인프라] git remote + CI 활성화 (병렬 가능, 의존성 없음)
     │
D-1  ├─ [PM]   충족 3색 임계치 변수화 (coverage-thresholds.ts, 80/30 추정)
     │   동시  [디자인] 토큰 3레이어 SSOT 확정 (_inpa-tokens.scss)
     │
D-2  ├─ [인프라] 북극성 3이벤트 DB 선반영 (share_sent/opened/attributed)
     │   동시  [보안] BE 동의차단 + share_token noindex + 마스킹 stub
     │
D-3  └─ [디자인] 공용 위생 4종 + 402모달 1벌 제작  ← 전 P1 화면이 import
        ─────────────────────────────────────────────
        이후 P1 병행 트랙(OCR 골든셋 / 색맹감사 / 공유링크 / 정직성린트 …) 착수
```

**왜 이 순서인가**: 담보 사전이 없으면 히트맵 컬럼이 안 정해지고, 임계치가 없으면 셀 색을 못 칠하고, 토큰이 없으면 화면 코드를 시작 못 한다. 북극성 스키마는 나중에 붙이면 귀속(attribution)이 깨지므로 **DB 첫 마이그레이션에 박아야** 한다.

---

## 1. 법무 게이트 (G1~G4) — 출시 가부 결정

> 법무 결정은 **코드가 아니라 출시 가부**다. 막히면 중립 기능(OCR·히트맵)을 먼저 내고, 비교안내서·AI진단은 게이트 통과 후 **2차 웨이브**로 분리한다.

| 게이트 | 미결 질문 | 막히면 (출시 영향) | 디자인/코드 강제 |
|---|---|---|---|
| **G1** 민감정보 국외이전 동의 | 병력=민감정보를 Claude(Anthropic, 美) 전송. `customer-agree`로 충분한가, 별도 동의서·마스킹·온프레미스 필요한가 | **AI 기능 전체 출시 불가** | 동의 게이트 모달 + `consent-badge` 전화면 + BE 이중검사 |
| **G2** §97 비교안내 정확요건 | 부당승환 추정 기간(6개월 추정), 비교안내확인서 법정 **6항목** 정확 문구, 전자서명 유효성 | 비교안내서 PDF 출시 불가 | 6항목 체크리스트 잠금 + 서명 동선 + PDF 잠금 |
| **G3** 보험광고 사전심의 경계 | AI 생성 외부배포물(카톡 카피)의 사전심의 대상 범위·소속/심의필 표기 의무 | AI 카피 외부배포 불가 | 가드레일 차단 UI + 면책 푸터 |
| **G4** 코어담보 기준선 출처·면책 | 히트맵 "부족/없음" 판정의 기준선(권장 보장금액) 출처·법적 책임 | 히트맵 판정 카피 단정 불가 | "권장"→"참고" 톤다운 + 임계치 `(추정)` 배지 |

**Owner**: 준법/보안 + 대표 · **Blocking**: ✅ (출시 가부 — 단, 착수는 막지 않음)

**분리 전략 (대표 합의)**:
```
1차 웨이브 (게이트 무관 선출시 가능) : OCR 파싱 · 담보 히트맵 · 크레딧/멤버십
2차 웨이브 (게이트 통과 후)          : §97 비교안내서 PDF · AI 진단 내러티브 · 외부배포 카피
```

**§97 6항목 (G2 placeholder)**: 기존보장 / 신계약보장 / 보험료비교 / 해지불이익 / 보장공백기간 / 청약철회 — 카피는 법무 확정 전까지 `§97_checklist[6]` placeholder 토큰. 디자인은 6칸 자리 + PDF 잠금(회색)만 선확정.

---

## 2. P0 Blocking 7종 — 착수 가부 (법무 외)

> 이게 없으면 해당 화면 **코딩 불가**. ⛔ = 빌드 차단.

### 2-1. ⛔ 담보 정규화 사전 seed `[데이터]`
- **무엇**: `06-coverage-taxonomy-reference.md`(15+ 카테고리 × 100+ leaf × 보험사별 alias)를 `seed_standard_coverages.py` management command로 변환 (JSON 중간 산출물).
- **왜 D-0**: OCR → 히트맵 → 비교안내서 **전부의 입력 데이터 전제**. 이게 없으면 히트맵 그리드 컬럼 수조차 안 정해진다. 모든 분석의 선행 의존.
- **Owner**: 개발(CTO) + PM · **Blocking**: ✅

### 2-2. ⛔ 충족 3색 임계치 변수화 `[PM + 개발]`
- **무엇**: 충족 80 / 부족·공백 30 경계(추정)를 `coverage-thresholds.ts` + SCSS 단일 상수로. `statusOf(rate)` 한 함수만 이 상수를 참조.
- **왜**: 경계값이 비면 히트맵 셀 색을 못 칠한다 = 히트맵 자체를 못 그림 (CEO P0). 법무 G4 확정 전까지 `// (추정)` 주석 강제, UI에 추정 배지 1개.
- **Owner**: PM + 개발 · **Blocking**: ✅

```ts
// coverage-thresholds.ts  — 단일 출처, 정책 변경 시 여기 1곳만 수정
export const COVERAGE_THRESHOLD = {
  sufficient: 0.8,  // (추정) — 법무 G4 기준선 확정 전
  gap:        0.3,  // (추정)
} as const;

export function statusOf(rate: number): 'sufficient' | 'insufficient' | 'gap' {
  if (rate >= COVERAGE_THRESHOLD.sufficient) return 'sufficient';
  if (rate >= COVERAGE_THRESHOLD.gap)        return 'insufficient';
  return 'gap';
}
```

### 2-3. ⛔ 북극성 로깅 스키마 DB 선반영 `[인프라]`
- **무엇**: `share_sent` / `share_opened` / `share_attributed` 3이벤트 + `share_token`에 발송채널·UTM 메타 부착.
- **왜**: 나중에 붙이면 귀속(attribution)이 깨진다. DB 첫 마이그레이션에 박아야 함. 출시해도 북극성 측정 불가하면 무의미.
- **Owner**: 개발(CTO) + PM · **Blocking**: ✅

```
share_sent       { share_token, sender_user, channel(kakao/link/sms), utm_*, sent_at }
share_opened     { share_token, opened_at, referrer, viewer_fingerprint(비식별) }
share_attributed { share_token, converted_event(상담요청/신규고객), attributed_at }
```

### 2-4. ⛔ 디자인 토큰 3레이어 SSOT `[디자인 + 개발]`
- **무엇**: primitive → semantic → component 3레이어 + SCSS `:root` CSS변수 브리지. 본 브리프 hex를 `_inpa-tokens.scss` 단일 출처화. foliio 잔존 하드코딩(`teal #00C5D1` / `pink #FF60B6`) **grep 제거**.
- **왜**: 화면 코드의 시작점. 히트맵 100+ 셀은 런타임 색칠이라 SCSS(컴파일타임)만으론 불가 → CSS 변수 브리지 필수.
- **Owner**: 디자인리드 + 개발 · **Blocking**: ✅

```scss
/* layer 1 primitive (의미 없는 원자색) */
$indigo-700:#1E40C4; $indigo-600:#3B5BDB; $mint-500:#12B5A4;
$amber-500:#F59E0B;  $gray-400:#ADB5BD;   $red-600:#E03131;

/* layer 2 semantic (화면이 참조하는 유일 레이어) */
$brand:            $indigo-700;  // 헤더/CTA/로고 — 셀에 못 씀
$data-proposal:    $indigo-600;  // 제안선/충분셀 — 헤더/CTA에 못 씀
$data-existing:    $mint-500;
$status-short:     $amber-500;
$status-gap:       $gray-400;
$danger:           $red-600;

/* :root 브리지 — 런타임 셀 색칠용 */
:root {
  --brand:         #{$brand};
  --data-proposal: #{$data-proposal};
  --data-existing: #{$data-existing};
  --status-short:  #{$status-short};
  --status-gap:    #{$status-gap};
}
```
> **인디고 충돌 0 규칙**: 브랜드 `#1E40C4`(헤더/CTA/로고)는 **셀에 못 쓰고**, 데이터 `#3B5BDB`(충분셀/제안선)는 **헤더/CTA에 못 쓴다**. stylelint `color-no-hex`로 raw hex 직접 사용 차단.

### 2-5. ⛔ git remote 연결 + CI 활성화 `[인프라]`
- **무엇**: `.github/workflows/ci.yml` 템플릿은 존재하나 remote 미연결로 CI가 안 돈다. GitHub private repo 생성 → remote 연결 → CI 자동 활성. gitleaks pre-commit 동작 확인.
- **모노레포 결정 (권장)**: foliio 모노레포 `inpa/` 디렉토리. 이유: `calculate.py` 8-case · `claude_parser` · `share_token` 재사용이 **해자**라 코드 공유가 이득.
- **Owner**: 개발(CTO) · **Blocking**: ✅

### 2-6. ⛔ BE 동의차단 + share_token noindex + 마스킹 stub `[보안]`
- **무엇**: ① 동의 미통과 시 **AI 호출 자체를 BE에서 차단**(FE 비활성만으론 불충분 — UI 숨김은 방어 아님). ② share_token `robots: noindex` + 만료/회수/조회로그. ③ 마스킹 stub(`진단명 → 카테고리 코드`).
- **왜**: 민감 분석이 검색엔진·단톡방에 영구 노출되는 사고 방지. 법무 G1이 "원문 전송 불가"로 나올 경우의 대비책.
- **Owner**: 준법/보안 + 개발 · **Blocking**: ✅

### 2-7. ⛔ 공용 위생 컴포넌트 4종 + 402모달 `[디자인 + 개발]`
- **무엇**: `disclaimer-footer` · `consent-badge`(3상태) · `credit-gauge` · `skeleton-heatmap` + 402 업그레이드 모달 1벌.
- **왜 P1 최선행**: 전 P1 화면이 import한다. 화면별 재디자인이 최대 중복 리스크. **디자인 라이브러리에서 안전배지 슬롯을 물리 삭제**(실수로도 못 넣게).
- **Owner**: 디자인리드 + 개발 · **Blocking**: ✅ (foliio 크레딧게이지·402모달은 포팅, 신규는 면책푸터·동의배지·skeleton)

---

## 3. P1 병행 트랙 — 1차 스프린트 내 (non-blocking)

| 항목 | 내용 | Owner | Blocking |
|---|---|---|---|
| **OCR 골든셋 라벨링** | `Test/` 107개 PDF(삼성/교보/한화/현대/DB) 매핑 정답지 라벨링. 부정확하면 히트맵이 거짓말 = 레드라인 위반. 매핑 실패분 = 회색 점선으로 정직하게 surface (추정 2~3일, 데이터 인력) | 개발 + PM | ❌ |
| **히트맵 색맹/명암비 감사** | 충족 3색 deuteranopia/protanopia 통과(명도차 ≥40) + 색·패턴 이중 인코딩 확정 + 본문 4.5:1 / 표헤더 3:1 전수 체크. Pretendard Variable woff2 subset self-host | 디자인리드 | ❌ |
| **공유링크 인프라** | 공개뷰 헤더숨김 + 만료/회수 + OG카드. foliio `share_token` 상속하되 열람로깅 · 동의만료 시 자동 비활성. `$global-header-h` 단일출처 변수 검수(z-index 회귀 트랩) | 개발 + 디자인리드 | ❌ |
| **정직성 디자인린트 + 금지카피** | 안전배지/심의완료/AI보장/보장완료 금지를 QA 체크리스트 + AI멘트 생성 프롬프트 가드레일로 주입. 위반카피 골든 회귀 **100건** CI에 박기 | 준법/보안 + 마케터 | ❌ |
| **디자인 QA 환경** | 스테이징 프리뷰 URL + 시안 검수 루프(PM 비개발자 브라우저 직접 확인). 디바이스 매트릭스(갤럭시 중저가 엄지도달 + 아이폰SE, 야외 저휘도 amber 회피) | 개발 + PM | ❌ |
| **인파-OO 기능 네이밍** | 한글 기능명 6종(한눈표/비교장/오늘의인파/한마디/소개고리) + i18n 키 영향검토(ko 우선). 명함 co-brand 템플릿 + 공유QR 동선 | 마케터 + PM | ❌ |

---

## 4. 인프라 readiness — 11항목 실측 상태표

| # | 항목 | 현 상태 (실측) | 착수 전 조치 |
|---|---|---|---|
| 1 | **git remote / CI** | `ci.yml` 템플릿 존재, **remote 미연결 → CI 안 돔** (origin 제거됨) | private repo 생성 → remote 연결 → CI 자동 활성. 모노레포 `inpa/` 권장 |
| 2 | **env scaffold** | `.env.example` 충실(Sentry/Kakao/KICC/Claude 슬롯) | 인파 키 분리: `CLAUDE_API_KEY` 월 캡 + `SENTRY_ENVIRONMENT=inpa-prod`. gitleaks 동작 확인 |
| 3 | **Django scaffold** | 4.1.13 + DRF 가동, 앱 분리 깔끔 | 신규 앱 2개: `coverage`(정규화+매트릭스) · `comparison`(§97). 기존 `analytics` 재사용 |
| 4 | **Angular scaffold** | 17.3, lazy ~22개, `customer-analysis/-compare` 존재 | 신규 lazy 3개: `heatmap` · `compare-doc` · `action-queue`. 기존 customer-analysis 위에 **얇게** 얹기 |
| 5 | **DB / 마이그레이션** | MariaDB 10.3.39, utf8mb4 강제 | 신규 테이블 3종(아래 §5). 마이그레이션 순서 = 사전 seed가 매트릭스보다 **선행** |
| 6 | **Sentry** | **BE 조건부 init 완료** (`base.py:406-421`, DSN env에 박힘), FE wired | 인파 전용 project 분리(노이즈 격리) + FE source map 업로드 CI 스텝 |
| 7 | **정규화 사전 seed** | `06-coverage-taxonomy.md` 작성됨(생명/손해 100+ alias) | → `seed_standard_coverages.py`로 변환. **모든 분석의 선행 의존** (D-0) |
| 8 | **샘플 증권 PDF** | `Test/` 107개 PDF + `ocrdata/` · `Standard/` 존재 | OCR→정규화 회귀셋 골든화. 보험사 매핑 정답지 라벨링(데이터 인력 추정 2~3일) |
| 9 | **이벤트 계측 스펙** | `analytics` 앱(page-view+event) 가동, pmf-admin 연동 | 북극성 3이벤트 스키마 확정(§2-3). share_token에 UTM·발송채널 메타 |
| 10 | **foliio 코드 접근** | 로컬 풀 소스 보유, `deploy-be/fe.sh` 동작 | 재사용 자산 8종(아래). 신규 작성은 3축 화면 + 위생 4종뿐 |
| 11 | **테스트 baseline** | **pytest 179 passed**(8-case 골든 포함) | 인파 추가분(§7). 8-case 골든은 **절대 불변** (회귀 게이트) |

**재사용 자산 8종 (해자 — 신규 작성 0)**: `share_token` · promotion 14종 에디터 · 크레딧 시스템 · `calculate.py` 8-case · `claude_parser` · `customer-analysis/-compare` · 402모달 · `credit-gauge`.

---

## 5. 신규 DB 테이블 + 앱/모듈 구조

### 신규 테이블 3종 (마이그레이션 순서 = seed 선행)
```
StandardCoverage   표준 담보 트리 (카테고리 → leaf). seed_standard_coverages.py로 사전 적재 ← 최선행
   └ category, leaf_name, life_or_loss(생명/손해), recommended_baseline(G4 확정 전 추정), sort
CoverageAlias      보험사별 담보명 → 표준 매핑 (삼성 "암진단급부금" → 표준 "일반암진단비")
   └ FK StandardCoverage, insurer, raw_name, confidence
CoverageMatrix     고객 × 담보 충족도 BE 선계산 캐시 (런타임 분석 금지)
   └ FK Customer, FK StandardCoverage, current_amount, baseline, rate, status(statusOf 산출)
```

### 신규 모듈
- **Django 앱 2종**: `coverage`(정규화 사전 + 히트맵 매트릭스) · `comparison`(§97 비교안내서 룰엔진)
- **Angular lazy 3종**: `heatmap` · `compare-doc` · `action-queue` — 모두 기존 `customer-analysis` 위에 얇게 얹기

---

## 6. 4대 UI 잠금 (준법 — 디자인이 컴플라이언스를 못 깨게)

| # | 잠금 | 구현 강제 |
|---|---|---|
| 1 | **안전배지 금지** | "금감원 심의완료 / 합법 보증" 배지를 **디자인 라이브러리 슬롯 자체에서 물리 삭제**. 붙이는 순간 보증책임 전가 → 소송 대상 |
| 2 | **면책 푸터 상시 고정** | `disclaimer-footer`: 모든 AI 생성물 하단 고정, 스크롤·접기 불가, 항상 viewport 내. *"AI 1차 보조입니다. 최종 검토·발송 책임은 설계사 본인에게 있습니다."* |
| 3 | **동의 게이트 BE 이중검사** | AI 진입 = `consent-badge`(동의/미동의/만료) 검사. 미동의 시 분석(비-AI)만 허용, AI 비활성(회색) + **BE에서도 호출 차단** |
| 4 | **§97 6항목 + 서명 전 PDF 잠금 / 자동발송 미설계** | 6항목 전부 ✓ + 전자서명 전까지 PDF 버튼 회색. **"카톡 자동발송" 버튼 미설계** — 클립보드 복사 / 카톡 열기만 |

> **amber ≠ red 의미 분리**: 부족(개선 여지) = amber `#F59E0B`, 위험(해지손해/§97 불리점/부당승환) = red `#E03131`. 부당승환 불리점은 **막는** UX(부추기지 않음).

---

## 7. 테스트 baseline + 인파 추가 골든

| 골든셋 | 내용 | 게이트 |
|---|---|---|
| **8-case 계산 골든** | `test_premium_calculation_8cases.py` — **pytest 179 passed 절대 불변** | 회귀 시 빌드 차단 |
| **정규화 매핑 골든** | 보험사별 담보명 → 표준 매핑 정답지 (Test/ 107 PDF 기반) | 매핑 실패 = 회색 점선 surface |
| **충족률 경계값** | `statusOf(rate)` 80/30 경계 단위 테스트 | 임계치 변경 시 1곳 검증 |
| **§97 6항목 검증** | 6항목 전부 ✓ 전까지 PDF 잠금 상태머신 | 미충족 시 PDF 비활성 |
| **정직성 가드레일 100건** | 위반 카피(안전배지/AI보장/보장완료) 회귀 100건 CI | 룰셋 변경 시 자동 검증 |

---

## 8. 최대 구현 리스크 — UI가 아니라 정규화 파이프라인

> **히트맵 색칠은 쉽다. "삼성 암진단급부금 → 표준 일반암진단비" 매핑이 틀리면 히트맵 전체가 거짓이 된다.** 그리고 거짓 히트맵은 정직성 레드라인 위반이다.

- **착수 1순위는 화면이 아니라 seed 사전 + OCR 회귀셋 라벨링**. 매핑 실패분을 회색 점선으로 정직하게 surface하는 UX가 이 리스크의 안전판.
- **히트맵 셀 구현 규칙**: `OnPush` + `trackBy` 필수. 색은 **CSS 변수 클래스**(`.cell--sufficient`)로 — `ngStyle` 인라인 hex 금지(리플로우 · CSP 위반).
- **매트릭스는 BE 선계산·캐시** (`CoverageMatrix` 테이블). 런타임 분석 금지.
- **모바일 = 카테고리 아코디언 + 가로스크롤**, 데스크톱만 멀티컬럼 허용.

---

## 9. 한 줄 결론

> 법무 게이트(G1~G4)는 **출시**를 막고, P0 7종은 **착수**를 막는다. 두 트랙은 별개다. 착수 블로커의 핵심은 **담보 사전(D-0) → 임계치 → 토큰 → 북극성 스키마** 순서이며, 최대 리스크는 UI가 아니라 **정규화 파이프라인의 매핑 정확도**다. 코드보다 데이터와 토큰이 먼저다.
