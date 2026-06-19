# 인파 첫 슬라이스 — 화면 스펙: 공유뷰A(삼쩜삼형) + 담보 히트맵

> 정본 교차검증: `design/00-design-system.md`, `02-ui-patterns.md`, `dev/07-api-data-contracts.md`(공유뷰A·히트맵 API 계약), `design/tokens/inpa-tokens.css`(토큰 SSOT). 모든 색은 semantic 토큰만 참조 — raw hex 직접 사용 금지. 임계·치수 수치는 `(추정)`.
> 이 문서는 **화면 계약·구조·순서**만 정의한다. 실제 구현 코드는 쓰지 않는다(컴포넌트 트리·props 시그니처·상태 다이어그램·페칭 순서까지). 제품명 **인파(Inpa)**.

---

## 0. 이 문서가 정의하는 것 / 안 하는 것

| 정의함 | 정의 안 함(다른 문서) |
|---|---|
| 공유뷰A·히트맵 두 화면의 섹션·컴포넌트·상태·인터랙션 | API 응답 JSON 전문 → `dev/07` |
| ASCII 와이어프레임(모바일/데스크톱) | 정규화 사전·8케이스 엔진 → `dev/06`, `dev/07` |
| Next.js 컴포넌트 트리·라우트·상태·페칭 순서(계약) | 픽셀 실측 Figma(미산출, §10 갭) |
| 디자인 토큰의 두 화면 소비 매핑 | 토큰 원본 정의 → `design/tokens/inpa-tokens.css` |
| 정직성 레드라인의 코드레벨 강제 지점 | 면책 확정 문안(법무 미수령, §10 갭) |

**화면 2종의 한 줄 정의**
- **공유뷰A** (`/s/[token]`): 고객이 카톡 링크로 받는 단일 페이지. "한 줄 인사이트 + 강조 숫자" 히어로로 보장 공백을 보여주고, 하단 CTA로 설계사 상담을 유도. 진입 자체가 북극성 `share_view` 발화 지점.
- **담보 히트맵** (`customer-analysis` 내 + 공유뷰 "전체보기"): 15+ 카테고리 × 100+ 담보를 3색 그리드로. 중립모드 디폴트. 설계사가 보장 공백을 한눈에 잡는 작업 화면.

---

## 1. 공통 디자인 레드라인 (두 화면 불변)

- [ ] **안전배지·심의완료·그린체크·금색인증 슬롯 물리 부재** — 컴포넌트 props에 해당 슬롯 자체가 없음(주석 처리 아님, 타입에 없음).
- [ ] **`disclaimer-footer` 상시고정** — 스크롤·접기 불가. 고정 문구 하드코딩: *"본 자료는 AI 1차 보조이며 최종 책임은 담당 설계사에게 있습니다."*(법무 확정 문안 대기 — §10 갭).
- [ ] **자동발송 사칭 금지** — 공유뷰 CTA는 클립보드 복사 / 설계사 연락처 오픈까지만. "자동전송"·"즉시발송" 카피 부재.
- [ ] **블루 3종 역할잠금**(§9) — 한 요소 교차 사용 금지. brand=CTA / accent-blue=강조숫자 / proposal=데이터셀.
- [ ] **강조숫자에 red 금지** — `accent-blue`만. 부족 ≠ 위험. `--danger`는 두 화면 미사용(비교안내서 §97 전용).
- [ ] **색 결정은 단일함수** — `statusOf(actual, baseline, mode)` 결과 문자열 → CSS변수 클래스(`.cell--enough`) 매핑만. 인라인 `style` hex 금지.
- [ ] **status 판정은 BE 권위** — FE는 `status` 문자열→클래스 매핑만. 임계 0.7·neutral/graded 플립은 전부 BE `heatmap.py` 단일진실원천. FE 재판정 금지.
- [ ] **색맹(deuteranopia/protanopia) 대응 = 이중 인코딩 필수** — 색만으로 status 구분 금지. 채움/좌4px바/점선/빗금 패턴 동반 + `aria-label`.

---

## 2. 공유뷰A — 화면 성격

### 2.1 성격
- 고객(비로그인)이 보는 화면. **글로벌 헤더 숨김** — `--header-h: 0`(`$global-header-h` 토큰을 0으로 오버라이드).
- 인파 로고는 **워드마크만 회색조**로 푸터 근처 후퇴(설계사가 주인공). 상단 70% 설계사 브랜딩 / 하단 1줄 `Powered by 인파`(노출 비율은 §10 갭, A/B 대상).
- `robots: noindex` — 민감 분석이 검색 노출되면 안 됨.
- SSR 필수 — 카톡 OG 프리뷰 카드(`og:title`/`og:image`) 서버 렌더.

### 2.2 레이아웃 (모바일 퍼스트, 단일 컬럼 480~720px 중앙)
세로 순서:

| # | 섹션 | 컴포넌트 | 비고 |
|---|---|---|---|
| 1 | 설계사 미니 헤더 | `ShareHeaderMini` | 설계사 프로필 + 면책배지(작게). 글로벌헤더 대체 |
| 2 | **인사이트 히어로** | `InsightHero` | 삼쩜삼형 "한 줄 인사이트 + 강조 숫자" |
| 3 | 요약 KPI 3카드 | `CostSummaryCard` + `CoverageSummaryCard` | 월 보험료 / 보장 충족 / 공백 담보 수 |
| 4 | 담보 요약 리스트 | `CoverageSummaryCard` 내 | 상위 부족/없음 leaf 3~5개 칩 행 |
| 5 | 나이별 보장 막대 | (상세 토글 시) | FE 도출, 0원=회색 단일 / 보장=연속 |
| 6 | 전문가 확인 배너 | `ExpertBanner` | 삼쩜삼 패턴 "전문가 확인 권장" |
| 7 | `disclaimer-footer` | `DisclaimerFooter` | 상시고정 |
| 8 | 하단 고정 CTA | `StickyCTA` | `fixed bottom-0` + safe-area, "○○ 설계사에게 맞춤설계 받기" |

---

## 3. 공유뷰A — 컴포넌트별 스펙

### 3.1 `InsightHero` (핵심)
구조: `Eyebrow(고객명 + 생성일)` → `InsightHeadline(display 28/900)` → 문장 내 `HiliteNumber`만 강조 → `ProgressBar`(보장 충족 진행바).

- **강조 규칙**: 강조 숫자·담보명만 `--accent-blue` 볼드, 나머지는 `--ink`. red 금지.
- **정직성 카피 분기 (단일 지점 = `mode`)**:

| mode | 헤드라인 패턴 | 강조숫자 | 근거 |
|---|---|---|---|
| `neutral`(디폴트) | "○○님은 **고액암 진단비**가 아직 없어요" | 담보명만(보유 0원 = none 사실만 단정) | Q1 기준선 미확정 → "부족" 단정 금지 |
| `graded`(Q1 확정 후) | "○○님은 지금 **암 진단비 3,000만원**이 비어 있어요" | 금액 | std_baseline 권위 확보 후만 |

- [ ] neutral에서 "부족/위험" 문자열 출력 금지(컴파일·런타임 양단 가드).
- [ ] 한 줄 인사이트 **선정 우선순위는 BE가 내려준 `insights[0]`**(없음 > 부족, 금액 큰 순 — `dev/07` insights 도출 규칙). FE는 순서 변경 금지, 표기 상한 = Top1(히어로) / 리스트는 Top3~5.
- [ ] `ProgressBar`: neutral 모드에선 **% 게이지 숨김**(권위 없는 % 표시 금지) → 보유/미보유 비율 막대만 회색조.

### 3.2 요약 KPI 3카드
`rounded-2xl border shadow-sm`. 숫자 전부 `Intl.NumberFormat('ko-KR')` + `tabular-nums`.

| 카드 | 값 | neutral 표기 | 색 |
|---|---|---|---|
| 월 납입 보험료 | `analysis.monthly_*` 합 | 동일 | `--ink` |
| 보장 충족 | "충분 N · 부족 N · 없음 N" | "**보유 N · 미보유 N**"(충분/부족 카운트 숨김) | 히트맵 3색 도트 |
| 공백 담보 | "N개" | 동일(none 기반) | `--cov-none` |

- [ ] 충족 카운트의 분모 단위(100+ leaf 전체 vs 상위 카테고리 롤업)는 `dev/07`/BE 정의 따름 — §10 갭.

### 3.3 `CoverageSummaryCard` — 담보 요약 리스트
- 히트맵 전체가 아닌 **상위 부족/없음 leaf 3~5개**만. 각 행 = `담보명 + 상태칩(이중인코딩)`.
- "전체 보장 한눈표 보기 →" 텍스트 버튼 → 히트맵(또는 동일 페이지 아코디언). 공유뷰는 요약, 풀 히트맵은 설계사 측 본진.

### 3.4 `ExpertBanner` / `DisclaimerFooter` / `StickyCTA`
- `ExpertBanner`: "정확한 진단은 담당 설계사 확인을 권장합니다" 톤. 안전배지 슬롯 없음.
- `DisclaimerFooter`: §1 고정 문구. variant prop만 받고 문구는 하드코딩(타입유니온에서 "안전/심의완료/보장" 제외).
- `StickyCTA`: `fixed bottom-0` + `pb-[env(safe-area-inset-bottom)]`. 클릭 동선(연락처 오픈 / 상담폼 / 전화 / 카톡)은 §10 갭 — 결정 후 보조 계측 이벤트명 배선.

---

## 4. 공유뷰A — 상태 5종

| 상태 | 트리거 | 표현 |
|---|---|---|
| `loading` | SSR 직후 hydration 전 / 재검증 | 히어로 skeleton(한 줄 바 + 숫자 블록) + 카드 3 skeleton |
| `empty` | 분석 데이터 없음 | 회색 점선 일러스트 + "아직 분석 전이에요"(고객뷰엔 희소 — 설계사 측 가이드) |
| `error`(만료) | token 무효/만료(Q4 hook) | **만료 전용 화면** `ExpiredView`: "이 링크는 만료되었어요" + 설계사 연락 안내. 응답코드 410(추정) |
| `locked` | — | 공유뷰는 무차감 경로 → **locked 없음** |
| `neutral` | `baseline_source == null` → BE가 mode=neutral | %·충족 단정 전부 숨김, none/보유여부만 |

---

## 5. 공유뷰A — ASCII 와이어프레임 (모바일)

```
(글로벌 헤더 숨김 — 콘텐츠가 최상단, --header-h:0)
┌─────────────────────────────┐
│ [설계사 프로필]  김설계 ·생명  │ ← ShareHeaderMini (상단 70% 설계사)
├─────────────────────────────┤
│ ○○님 · 2026.06.19 분석       │ ← Eyebrow caption (ink-2)
│                             │
│ ○○님은                       │ ← InsightHeadline display 28/900 ink
│ 고액암 진단비가               │   담보명=accent-blue 볼드
│ 아직 없어요                  │   (neutral: 금액 단정 없음)
│ ▓▓▓▓▓░░░░░  (보유비율 막대)   │ ← ProgressBar (neutral=회색조, %숨김)
│ ───────────────────────     │
│ ┌─────┐┌─────┐┌─────┐       │
│ │월보험││충족 ││공백 │ ← KPI 3카드
│ │15.2만││보유3 ││ 4개 │   tabular-nums
│ │     ││미보4 ││     │   (neutral: 보유/미보유)
│ └─────┘└─────┘└─────┘       │
│                             │
│ 채워야 할 보장              │ ← 섹션헤더 heading
│ ▎고액암진단비   [없음·┊점선] │ ← CoverageSummaryCard
│ ▎질병후유장해   [부족·▌amber]│   각 행 담보명+상태칩
│ ▎간병비        [없음·┊점선]  │
│ [전체 보장 한눈표 보기 →]    │ ← 텍스트버튼 → 히트맵
│                             │
│ (상세 토글 시) 나이별 보장   │
│ ▆▆▆▆░░░░▆▆  (연속 막대)      │ ← FE 도출
│                             │
│ ⓘ 정확한 진단은 설계사 확인  │ ← ExpertBanner
│ ─ disclaimer-footer ──────  │ ← 상시고정 (접기 불가)
│ 본 자료는 AI 1차 보조이며    │
│ 최종 책임은 담당 설계사…      │
│         powered by 인파      │ ← 워드마크 회색조 후퇴
└─────────────────────────────┘
┌─────────────────────────────┐
│  [ ○○ 설계사에게 맞춤설계 ]   │ ← StickyCTA fixed bottom #1E40C4
└─────────────────────────────┘   + safe-area-inset-bottom
```

**데스크톱 차이**: 720px 중앙 정렬 유지(밀도화면 아님 → 멀티컬럼 금지). 히어로 폰트만 display 32까지 확대. CTA는 하단 고정 대신 콘텐츠 끝 inline + sticky 둘 다 허용.

---

## 6. 히트맵 — 화면 성격 & 레이아웃

### 6.1 성격
- 설계사 작업 화면(`customer-analysis` 내) + 공유뷰 "전체보기" 진입. **무게이트 서버연산 경로** — 412 동의게이트는 detect(OCR 입력단)에만 물림, 히트맵 조회엔 안 물림.
- IA 문서의 "동의 미수신 → 히트맵 블러+잠금"은 **UX 표현이지 데이터 게이트가 아님**. 히트맵을 그리려면 이미 detect로 담보가 입력돼 있어야 함(데이터 진입 경로) → 히트맵 단독 선출시엔 수기입력 폴백 동선 전제.

### 6.2 레이아웃
- **모바일**: 좌측 카테고리 라벨 `position:sticky left-0` 고정 + 셀 `overflow-x-auto` 가로스크롤. 상단 `[간략|상세]` 세그먼트(기본 상세) + 필터칩 행(전체/없음/부족/충분, 가로스크롤). 100+ 담보 → 카테고리 아코디언 경량화(초기 렌더).
- **데스크톱**: 좌측 카테고리 컬럼 sticky + 우측 멀티컬럼 셀 그리드(밀도화면 멀티컬럼 허용).
- 셀 크기: 모바일 24×24 / 데스크톱 32×32, 간격 2px, radius-sm 4px. 탭 영역 44px(접근성, 셀보다 패딩 확장).

---

## 7. 히트맵 — 셀 디자인 (이중 인코딩)

| status | fill | 보더 | 텍스트 | 패턴(색맹 대응) |
|---|---|---|---|---|
| `enough` | 연한 인디고 틴트 | — | `--cov-enough #3B5BDB` | 채움 |
| `short` | 연한 amber 틴트 | 좌측 4px `#F59E0B` 바 | `--ink` | **좌측 액센트바** |
| `none` | 투명 | 점선 `--cov-none #ADB5BD` | gray | **점선 보더** |
| `neutral` | gray-050 | 점선 회색 | "—" | 점선(판정보류) |
| 미분류 | gray-050 | 점선 회색 | "미분류" | 점선 칩 |

- [ ] **fill은 항상 연한 틴트, 텍스트·보더만 진하게** — 4종색 동시노출 가독성.
- [ ] **amber(부족) ≠ red(위험)** — 히트맵엔 red 절대 없음. red는 비교안내서 §97 불리점 전용.
- [ ] 색 결정 = `statusOf(actual, baseline, mode)` 단일 함수 → `.cell--enough` 등 CSS변수 클래스. 인라인 hex 금지.
- [ ] 셀 `aria-label="일반암진단비: 부족"` — 스크린리더용 이중인코딩.

### 7.1 셀 탭 → 바텀시트 (`vaul`)
내용: 담보명 / 현 보장액 / 권장 기준선(**graded만** 노출) / 갭 금액 / 출처주석 `ⓘ`(권위 확정 전 "(추정)" 배지).
- neutral 셀 탭: "보유 여부만 표시 중 — 기준선 확정 시 충족 판정 제공"(거짓 충족 금지).

---

## 8. 히트맵 — 상태 5종 & 와이어프레임

### 8.1 상태 5종

| 상태 | 트리거 | 표현 |
|---|---|---|
| `loading` | useQuery isLoading | `skeleton-heatmap`(카테고리 행 × 셀 그리드 회색 펄스) |
| `empty` | 보험 미등록 | 점선 일러스트 + "증권을 등록하면 보장 공백이 보여요" + `[증권 등록]` CTA(콜드스타트 발굴) |
| `error`(부분) | OCR 실패/미분류분 | 해당 셀만 회색 surface + "미분류 N건" 경고 배너 — **전체 실패 아님, 부분만 표시** |
| `locked` | — | 히트맵 조회 무차감 → **locked 없음**. 단 OCR 등록은 `insurance` 크레딧 게이트(402→UpgradeGuideModal) |
| `neutral` | `baseline_source == null` | 전 셀 none/neutral만, 상단 `ⓘ "기준선 출처 확정 전 — 보유 여부만 표시"` 고정 배너 |

### 8.2 ASCII 와이어 (모바일, 가로스크롤)

```
┌──────────────────────────────┐
│ [간략 | 상세]  ← ViewSegment   │
│ (전체)(없음)(부족)(충분)←칩스크롤│ ← FilterChips overflow-x-auto
│ ⓘ 기준선 확정 전·보유여부만    │ ← BaselineSourceNote (graded면 숨김)
├────────┬─────────────────────┤
│카테고리 │ 셀 셀 셀 셀 셀 →     │ ← 우측 가로스크롤 영역
│(sticky)│ (좌열 left-0 고정)    │
│진단비-암│[■충분][▌부족][┊없음] │
│ 후유장해│[┊없음][■충분][▌부족] │
│ 간병    │[┊없음][┊없음][┊미분류]│
│  …     │ … (15+ 카테고리)     │
│        │ ▶ 아코디언 접기/펼치기 │
└────────┴─────────────────────┘
        ↓ 셀 탭 (vaul 바텀시트)
┌──────────────────────────────┐
│ 일반암진단비          [×]      │
│ 현 보장   3,000만원           │
│ 권장 기준 5,000만원 (추정)ⓘ   │ ← graded만 노출
│ 갭       -2,000만원 (amber)   │
└──────────────────────────────┘
```

### 8.3 ASCII 와이어 (데스크톱, 멀티컬럼)

```
┌──────────┬──────────────────────────────────┐
│ 카테고리  │ 일반암 고액암 뇌혈관 심혈관 …      │ ← 컬럼헤더 label 13/700
│ (sticky) │ ┌──┐┌──┐┌──┐┌──┐                 │
│ 진단비-암 │ │■ ││┊ ││▌ ││■ │  32×32 셀       │
│ 후유장해  │ │┊ ││■ ││┊ ││▌ │                 │
│ 간병     │ │┊ ││┊ ││■ ││┊ │  멀티컬럼 그리드 │
└──────────┴──────────────────────────────────┘
 [범례] ■충분(채움)  ▌부족(좌4px바)  ┊없음(점선)  — 중립
```

---

## 9. 토큰 매핑 (두 화면 소비 semantic 토큰만 — `inpa-tokens.css` SSOT)

| 토큰 | 값 | 두 화면 역할 | 교차금지 |
|---|---|---|---|
| `--brand` | `#1E40C4` | 공유뷰 CTA (헤더는 숨김) | accent/proposal로 못 씀 |
| `--accent-blue` | `#3182F6` | 히어로 강조숫자 · 진행바 · info | **셀 금지** |
| `--cov-enough` | `#3B5BDB` | 히트맵 충분셀 · 요약 충분칩 | **헤더/CTA 금지** |
| `--cov-short` | `#F59E0B` | 부족셀(좌4px바) · 부족칩 | — |
| `--cov-none` | `#ADB5BD` | 없음/미분류/neutral(점선) | — |
| `--danger` | `#E03131` | **두 화면 미사용**(비교안내서 전용) | 강조숫자·셀에 금지 |
| `--ink` | `#16181D` | 본문 텍스트 / 전 숫자 | — |
| `--header-h` | `0`(공유뷰) | 글로벌 헤더 숨김 오버라이드 | — |

- **Tailwind 매핑**: `theme.extend.colors`가 CSS변수 참조만(`'cov-short':'var(--cov-short)'`). 색은 유틸 클래스로만(`bg-cov-short`, `text-accent-blue`) — hex 하드코딩은 `stylelint color-no-hex`로 빌드 차단.
- **블루 3종 역할잠금**: brand(CTA) / accent-blue(강조숫자) / proposal=cov-enough(데이터셀). 빌드타임에 다른 클래스로 분리 → 교차 사용을 코드리뷰에서 즉시 포착.
- **임계 단일참조**: `$threshold-sufficient 0.8`(추정) / `$threshold-gap 0.3`(추정) → `statusOf` 단일 함수만 참조. **단, 판정 자체는 BE 권위** — FE 임계는 표시 보조용일 뿐 status 재계산 금지.
- 숫자: 전부 `Intl.NumberFormat('ko-KR')` + `font-variant-numeric: tabular-nums`(자리정렬).

---

## 10. Next.js 컴포넌트 트리 · 라우트 · 상태 · 페칭 (계약)

### 10.1 라우트

| 라우트 | 렌더 | 인증 | 비고 |
|---|---|---|---|
| `app/s/[token]/page.tsx` | **Server Component (SSR)** | 우회(공개) | 공유뷰A. `?ref=` searchParam 보존, `metadata={robots:'noindex'}` |
| `app/check/[token]/page.tsx` | (자리만 선점) | — | detect 412 `consent_url` 착지점(이번 슬라이스 배선 X) |
| `customer-analysis`(planner 그룹) | Client(히트맵 섹션) | 설계사 인증 | 히트맵 호스트 화면 |

### 10.2 공유뷰A 컴포넌트 트리 (Server Component SSR + Query hydration)

```
app/s/[token]/page.tsx  (Server Component)
  └ getShareAnalysis(token, ref)  ← SSR fetch (서버에서 share_view·referral_attributed 발화)
  └ <HydrationBoundary state={dehydrate(queryClient)}>
      └ <ShareLayout>            (헤더/탭 숨김, max-w 480, 하단 CTA 안전영역 pb)
          ├ <ShareHeaderMini/>           설계사 프로필 + 면책배지(작게)
          ├ <InsightHero>               ★ 한 줄 인사이트 + 강조숫자
          │   ├ <Eyebrow/>              고객명 + 생성일
          │   ├ <InsightHeadline/>      display 28/900, 문장
          │   ├ <HiliteNumber/>         강조숫자/담보명 (text-accent-blue)
          │   └ <ProgressBar/>          보장충족 진행바 (neutral=%숨김)
          ├ <CoverageSummaryCard/>      담보 요약 3~5줄 (상태칩)
          ├ <CostSummaryCard/>          월 보험료 / 총납입
          ├ <ExpertBanner/>            전문가 확인 권장 배너
          ├ <DisclaimerFooter/>         ★면책 고정 (공용 재사용)
          └ <StickyCTA/>               맞춤 설계 받기 (fixed bottom)
```

### 10.3 히트맵 컴포넌트 트리 (Client Component + useQuery)

```
<HeatmapSection>   ('use client')
  └ useQuery(heatmap(customerId, mode))
  ├ <ViewSegment/>             [간략 | 상세] toggle group (useState)
  ├ <FilterChips/>             전체/없음/부족/충분 (overflow-x-auto, useState)
  ├ <BaselineSourceNote/>      ⓘ 출처 주석 (mode==='neutral' → "보유여부만")
  ├ <HeatmapGrid>              가로스크롤 + 좌측 sticky 라벨열
  │   ├ <StickyLabelCol/>      position:sticky left-0 z-10 (카테고리/담보명)
  │   └ <HeatCell/> × N        status→.cell--* 매핑 (BE 권위, FE 판정 X)
  ├ <Legend/>                  3색 범례 + 색맹 패턴 동반 표기
  └ <DisclaimerFooter/>        공용 재사용
```

### 10.4 상태 · 데이터 페칭 (계약)

| 구분 | 방식 | 비고 |
|---|---|---|
| 공유뷰A 서버상태 | Server Component SSR fetch → `dehydrate` → `HydrationBoundary` | `staleTime 5min`(거의 정적), `retry 1`, `gcTime 30min` |
| 히트맵 서버상태 | Client `useQuery` | 인터랙션(가로스크롤·필터·세그먼트) 무거워 클라이언트 |
| UI 로컬상태 | `useState`(필터칩·세그먼트·아코디언) | 전역 store 불필요(이번 슬라이스) |
| 에러 분기 | **412/402/207은 throw 대신 typed result 분기** | 에러바운더리 대신 분기 렌더. 공유뷰는 412 무관(추출후 서버연산 경로) |

**queryKeys**
```
shareAnalysis: (token)        => ['share','analysis', token]
heatmap:       (id, mode)     => ['customer', id, 'heatmap', mode]
```

**typed result 분기 (의사 계약, 구현 아님)**
```
type FetchResult<T> =
  | { ok: true; data: T }
  | { ok: false; kind: 'consent_required'; consentUrl }   // 412 — detect 전용, 공유뷰 무관
  | { ok: false; kind: 'credit_exhausted'; limit; remaining }  // 402
  | { ok: false; kind: 'partial'; matched; unmatchedCount }    // 207
  | { ok: false; kind: 'expired' }                        // 410(추정) → ExpiredView
  | { ok: false; kind: 'error' }
```

### 10.5 페칭 순서 (공유뷰A 진입 = 북극성 첫 곱 '열람')

```
1. 고객이 카톡 링크 탭 → GET /s/<token>?ref=<설계사코드>
2. Server Component: getShareAnalysis(token, ref) SSR fetch
   → BE가 share_token 검증 + share_view 이벤트 적재 + ?ref→referral_attributed 귀속
   (★FE는 ?ref= 쿼리를 라우팅에서 소실시키지 않는 것만 책임. 계측 발화는 BE 권위)
3. analysis JSON → dehydrate → HydrationBoundary로 클라이언트 전달
4. 클라이언트 hydration: InsightHero/카드 인터랙션 활성, CTA 클릭만 보조 계측(gtag/내부 endpoint)
```

---

## 11. 정직성 레드라인 — 코드레벨 강제 지점 (체크리스트)

- [ ] `DisclaimerFooter` / `ConsentBadge` props 타입유니온에서 **"안전" / "심의완료" / "보장" 워딩 제외** → 컴파일 단계 차단.
- [ ] `InsightHero` 카피는 `mode` 단일 분기. `neutral`에서 "부족/위험" 출력 경로 자체 부재(타입+런타임).
- [ ] 강조색(`accent-blue`)을 위험표현에 못 쓰게 lint 규칙(클래스 조합 경고) — 부족 ≠ 위험.
- [ ] 자동발송 사칭 금지: 공유뷰 CTA = 클립보드/연락처 오픈까지. "자동전송" 카피 부재.
- [ ] 히트맵 셀 색 = `statusOf` 단일함수 → CSS변수 클래스만. 인라인 hex `stylelint color-no-hex` 차단.
- [ ] status 판정 BE 권위 — FE는 문자열→클래스 매핑만, 임계 재계산 코드 부재.
- [ ] 면책 고정문구 상시노출 — `disclaimer-footer` DOM 존재 여부 QA 검증(접기·제거 불가).

---

## 12. 인터랙션 규칙

- [ ] 트랜지션 ≤150ms, 바운스 금지(작업도구 톤).
- [ ] 셀 호버 = 틴트 1단계 진하게(데스크톱만). 모바일은 탭→바텀시트.
- [ ] 셀 그리드 `OnPush + trackBy` 대응(렌더 최소화). 런타임 분석 금지 — BE 출력 소비만.
- [ ] 숫자 전부 `Intl.NumberFormat('ko-KR')` + `tabular-nums`.
- [ ] `safe-area-inset-bottom` 패딩 — iOS 홈바 / 갤럭시 제스처바와 StickyCTA 겹침 방지.
- [ ] `?ref=` 쿼리 라우팅 소실 금지(귀속 깨짐 = 북극성 데이터 손실).

---

## 13. 계측 매핑 (Day1 동결 스펙 — 사후복원 불가)

| 이벤트 | 발화 주체 | 트리거 시점 | 비고 |
|---|---|---|---|
| `share_view` | **BE** | 공유뷰A 진입(SSR fetch) | 북극성 첫 곱 '열람'. FE는 `?ref=` 보존만 책임 |
| `referral_attributed` | **BE** | `?ref=<설계사코드>` 동반 진입 | share_token × ref_code 결합 귀속 |
| `share_clipboard_copy` | FE(보조) | 설계사가 링크 복사 | 공유뷰 외 — 설계사 화면 |
| CTA 클릭 | FE(보조) | StickyCTA "맞춤설계" 탭 | `gtag`/내부 endpoint. 이벤트명 §10 갭(동선 확정 후) |

- [ ] 이벤트명·페이로드 스키마는 **Sprint 0에서 동결된 스펙 그대로** — 변경 시 사후복원 불가.
- [ ] **데모 1건 한 사이클**: 본인 증권 → 히트맵(중립모드) → 공유링크 복사 → 카톡 발송 → 고객 폰에서 인사이트 카드 열람 → 서버 `share_view` 1건 적재. = 슬라이스 게이트(북극성 첫 항 '열람' 증명).

---

## 14. 개발 착수 전 미해소 갭 (이 두 화면 종속)

| # | 갭 | blocking | owner |
|---|---|---|---|
| 1 | **InsightHero 한 줄 인사이트 산출 규칙 + neutral 카피 분기** — 우선순위(없음>부족? 금액 큰 순), 표기 상한(Top1), 반올림 단위. 고객 노출이라 정직성 직접 적용 | ✅ | PM + 디자인 |
| 2 | **면책·동의·CTA 카피 6종 확정 문안** — 미확정이면 타입유니온 잠금·푸터 높이·CTA 겹침 확정 불가. CTA 동선(연락처/상담폼/전화/카톡) + 클릭 계측 이벤트명 | ✅ | PM + 디자인 + 법무 |
| 3 | **계측 이벤트 스펙 동결** — `share_view`/`referral_attributed`/CTA클릭 이름·파라미터·`?ref=` 형식. 사후복원 불가 | ✅ | 대표 + PM + 개발 |
| 4 | **충족 3색 임계 + 기준선 출처(Q1)** — neutral 디폴트라 당장 안 쓰나 graded 활성 시점 권위. 데모 "왜 부족이라 단정하냐" 답변 스크립트 | — | PM + 개발 |
| 5 | **share_token 만료·회수·noindex(Q4)** — TTL·회수 동선·만료 응답코드(410?)·ExpiredView 트리거 | — | PM + 개발 + 보안 |
| 6 | **공유뷰 PII 마스킹** — 고객명(홍**), gender null 표기, 병력 노출 범위. 공유뷰 응답 노출 한계 | — | PM + 보안 + QA |
| 7 | **히트맵 100+ 담보 한글 라벨 확정표 + IA** — 컬럼헤더/셀 라벨, 아코디언 기본상태·정렬(공백우선?), 가로 컬럼 정의(보유1건? 기존vs제안 2열?). NormalizationDict v0 라벨과 1:1 동기 | — | 디자인 + 데이터 |
| 8 | **미분류 셀 노출 임계** — OCR 신뢰도 몇 % 미만을 "미분류" 회색 처리할지 + "미분류 N건" 카운트 산출 규칙 BE 합의 | — | QA + 개발 |
| 9 | **디자인 산출물(Figma)** — 8pt 그리드 실측, 히어로 레이아웃, 셀 24/32px·탭영역 44px, 토큰 동기화(복사 vs symlink) SSOT 드리프트 방지 | — | 디자인 |
| 10 | **디바이스·접근성 매트릭스** — deuteranopia/protanopia 명도차 ≥40, 야외 저휘도 amber(#F59E0B) 가독성, safe-area 실기기 검수 | — | 개발 + 디자인 + PM |

---

## 15. 수용 기준 (이 두 화면 한정)

- [ ] 공유링크 진입 시 다른 기기 열람이 서버 `share_view` **1건** 적재(`?ref=` 동반 시 `referral_attributed`도).
- [ ] `disclaimer-footer`가 두 화면 모두 DOM 상시 존재(접기·제거 불가) — QA DOM 검증.
- [ ] 안전배지/심의 슬롯이 컴포넌트 타입에 **물리 부재**(주석 아님) — 컴파일 검증.
- [ ] 히트맵 status 4종(none/short/enough/neutral) 전수 렌더 + 이중인코딩(채움/좌4px바/점선/빗금) 시각 검증.
- [ ] neutral 모드에서 "부족/위험" 문자열·% 게이지 **미노출** — 런타임 + 카피 grep 검증.
- [ ] 블루 3종 교차 사용 0건 — 유틸 클래스 grep(`text-accent-blue`가 셀에, `bg-cov-enough`가 CTA에 없음).
- [ ] `npm run build` + `tsc --noEmit` + `stylelint`(color-no-hex) 무오류.
