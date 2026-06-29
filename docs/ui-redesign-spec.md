# 인파 대시보드 UI 리디자인 — Claude Code 작업 지시서

> **목표 한 줄**
> 현재(레퍼런스 2번) 상단 네비 대시보드의 **기능·데이터·라우팅은 그대로 두고**, 시각 언어만
> **레퍼런스 1번** 수준으로 — 큰 숫자, 컬러 아이콘 뱃지, 컬러 파이프라인, 넉넉한 여백·라운드 — 끌어올린다.
> **네비게이션은 상단 유지.** (사이드바 전환은 §8 옵션 참고)

> **사용법**
> 1. 이 파일을 레포에 `docs/ui-redesign-spec.md`로 넣는다.
> 2. Claude Code 세션에 **레퍼런스 1번 이미지를 첨부**하고, 아래 **Phase 0**부터 순서대로 프롬프트를 복붙한다.
> 3. 각 Phase는 "이 지시서(`docs/ui-redesign-spec.md`)의 해당 절을 따르라"고 참조시키면 가장 정확하다.

---

## 1. 절대 규칙 (Claude Code가 모든 Phase에서 지킬 것)

1. **기능/라우팅/데이터 패칭 로직 변경 금지.** 순수 프레젠테이션(JSX 구조 + className + 토큰)만 수정한다.
2. **새로 만들지 말고 찾아서 고친다.** 먼저 기존 컴포넌트 파일을 매핑한 뒤 그 파일을 수정한다.
3. **디자인 토큰 먼저.** 색·타이포·간격·라운드·그림자를 한 곳에 정의하고 전 컴포넌트가 참조한다. 컴포넌트에 하드코딩된 hex/px를 새로 추가하지 않는다.
4. **점진적 적용 + 매 단계 빌드 확인.** 한 번에 다 갈아엎지 않는다. Phase 단위로 커밋한다.
5. **품질 바닥선 유지:** TypeScript strict, 키보드 포커스 링, 색 대비(WCAG AA), 모바일까지 반응형, `prefers-reduced-motion` 존중.
6. **기능을 디자인 때문에 제거하지 않는다.** 보유계약 유지현황, 계약 유지율, 이번 달 목표, 환수 레이더, 캘린더 범례 등 기존 섹션은 전부 살린다.

---

## 2. 디자인 토큰 (정확값)

### 2.1 색

| 토큰 | HEX | 용도 |
|---|---|---|
| `brand` | `#2E50F0` | 주요 액션, 액티브 네비, 강조 막대, 게이지, 선택된 날짜 |
| `brand-dark` | `#2440C8` | hover/press |
| `brand-soft` | `#EAF0FF` | 아이콘 뱃지 배경, 액티브 네비 배경, 연한 강조 |
| `ink` | `#1B2540` | 본문 1차 텍스트, 큰 숫자 |
| `ink-sub` | `#8A94A6` | 라벨, 보조 텍스트 |
| `ink-muted` | `#AEB6C6` | 비활성, 화살표, placeholder |
| `canvas` | `#F3F5F9` | 페이지 배경 |
| `surface` | `#FFFFFF` | 카드 배경 |
| `line` | `#EEF1F6` | 보더/구분선 |
| `pos` / `pos-soft` | `#22B07D` / `#E7F6EF` | 증가(+%), 유지 안정 |
| `neg` / `neg-soft` | `#E4574F` / `#FCEDEC` | 감소(-%), 환수 위험, 경고 배너 |
| `warn` / `warn-soft` | `#D9A441` / `#FBF4E6` | 주의 |

**파이프라인 단계색**

| 단계 | 배경 | 강조(번호/텍스트) |
|---|---|---|
| 01 DB | `#F5F7FA` | `#8A94A6` |
| 02 TA | `#FCEDEC` | `#E4574F` |
| 03 FA | `#FBF4E6` | `#D9A441` |
| 04 청약 | `#E9F6EF` | `#22B07D` |

### 2.2 타이포 스케일 (폰트는 기존 Pretendard/Noto 유지)

| 역할 | 클래스 | 비고 |
|---|---|---|
| 페이지 인사 | `text-2xl font-bold text-ink` | "안녕하세요, … 👋" |
| 섹션 제목 | `text-base font-bold text-ink` | "영업 단계별 고객" 등 |
| 카드 라벨 | `text-sm font-medium text-ink-sub` | 숫자 위 라벨 |
| **큰 숫자** | `text-3xl font-bold text-ink tracking-tight` | 통계 카드 핵심. 강조 카드는 `text-4xl` |
| 단위(명/건/원) | `text-sm font-medium text-ink-sub` | 숫자에 baseline 정렬 |
| 증감(델타) | `text-xs font-semibold` + `text-pos`/`text-neg` | 화살표 아이콘 동반 |
| 보조 설명 | `text-sm text-ink-sub leading-relaxed` | 빈 상태/안내 |

### 2.3 라운드 · 그림자 · 간격

| 토큰 | 값 |
|---|---|
| `rounded-card` | `1rem` (16px) — 카드 |
| `rounded-inner` | `0.75rem` (12px) — 아이콘 뱃지·내부 블록 |
| `rounded-pill` | `9999px` — 델타/탭/액티브 pill |
| `shadow-card` | `0 1px 3px rgba(16,24,40,.06), 0 1px 2px rgba(16,24,40,.04)` |
| 카드 패딩 | `p-5` (20px) 기본 / 큰 카드 `p-6` |
| 그리드 간격 | `gap-4` (16px) / 섹션 사이 `space-y-5` |
| 콘텐츠 최대폭 | `max-w-[1240px] mx-auto px-4 md:px-6` |

---

## 3. 전역 설정 지시

### 3.1 `tailwind.config.ts` extend (예시)

```ts
// theme.extend
colors: {
  brand: { DEFAULT: '#2E50F0', dark: '#2440C8', soft: '#EAF0FF' },
  ink:   { DEFAULT: '#1B2540', sub: '#8A94A6', muted: '#AEB6C6' },
  canvas: '#F3F5F9',
  line:  '#EEF1F6',
  pos:   { DEFAULT: '#22B07D', soft: '#E7F6EF' },
  neg:   { DEFAULT: '#E4574F', soft: '#FCEDEC' },
  warn:  { DEFAULT: '#D9A441', soft: '#FBF4E6' },
  stage1: { bg: '#F5F7FA', fg: '#8A94A6' },
  stage2: { bg: '#FCEDEC', fg: '#E4574F' },
  stage3: { bg: '#FBF4E6', fg: '#D9A441' },
  stage4: { bg: '#E9F6EF', fg: '#22B07D' },
},
borderRadius: { card: '1rem', inner: '0.75rem' },
boxShadow: { card: '0 1px 3px rgba(16,24,40,.06), 0 1px 2px rgba(16,24,40,.04)' },
```

`bg-canvas`를 `<body>` 또는 최상위 레이아웃에 적용한다.

### 3.2 공통 컴포넌트 도입 (권장)

리스타일을 일관되게 하려면 아래 프리미티브를 먼저 만들고 모든 섹션이 재사용한다.

```tsx
// components/ui/Card.tsx
export function Card({ className = '', ...p }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={`bg-white rounded-card shadow-card p-5 ${className}`} {...p} />;
}

// components/ui/SectionTitle.tsx
export function SectionTitle({ title, action }: { title: string; action?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between mb-4">
      <h3 className="text-base font-bold text-ink">{title}</h3>
      {action}
    </div>
  );
}
```

---

## 4. 컴포넌트별 변경 명세 (현재 → 목표)

> 각 절은 "목표 모습 → JSX 골격 → 핵심 클래스" 순. 골격은 토큰 클래스를 쓴 **참고용**이며, 기존 데이터·props에 맞춰 적용한다.

### 4.1 상단 네비게이션 (유지 + 정돈)

- **목표:** 상단 그대로. 액티브 메뉴는 `bg-brand-soft text-brand rounded-pill` pill, 비액티브는 `text-ink-sub hover:text-ink`. 좌측 로고(P 인파), 우측 알림 벨(뱃지 카운트)+아바타. `sticky top-0 z-40 bg-white border-b border-line`.
- **핵심:** 메뉴 간격 `gap-1`, 항목 패딩 `px-3 py-2 text-sm font-medium`. 컨테이너는 §2.3 최대폭.

```tsx
<header className="sticky top-0 z-40 bg-white border-b border-line">
  <div className="max-w-[1240px] mx-auto px-4 md:px-6 h-14 flex items-center gap-6">
    <div className="flex items-center gap-1.5 font-bold text-ink">{/* 로고 */}P <span>인파</span></div>
    <nav className="flex items-center gap-1">
      {items.map(it => (
        <a key={it.href} className={`px-3 py-2 text-sm font-medium rounded-pill ${
          it.active ? 'bg-brand-soft text-brand' : 'text-ink-sub hover:text-ink'}`}>{it.label}</a>
      ))}
    </nav>
    <div className="ml-auto flex items-center gap-3">{/* 벨 + 아바타 */}</div>
  </div>
</header>
```

### 4.2 인사 + 날짜 헤더 (유지)

- **목표:** `안녕하세요, demo 설계사님 👋`은 `text-2xl font-bold text-ink`. 우측에 날짜 `text-sm text-ink-sub`. 본문 상단 한 줄.

```tsx
<div className="flex items-end justify-between pt-6 pb-4">
  <h1 className="text-2xl font-bold text-ink">안녕하세요, {name} 설계사님 👋</h1>
  <span className="text-sm text-ink-sub">{today}</span>
</div>
```

### 4.3 통계 카드 5개 (가장 큰 변화 — 아이콘 뱃지 + 큰 숫자 + 델타)

- **현재:** 라벨 + 작은 숫자뿐, 아이콘 없음.
- **목표:** 각 카드 왼쪽에 **컬러 아이콘 뱃지**(48px, `rounded-inner`, soft 배경 + 컬러 아이콘). 라벨(작은 회색) → **큰 숫자**(`text-3xl bold`) + 단위 → 델타(컬러 + 화살표). `lucide-react` 아이콘 사용.
- **매핑(아이콘/톤):** 내 고객=`Users`/brand · 이번 달 신규=`UserPlus`/brand(+%는 pos) · 이번 달 미팅=`CalendarCheck`/brand · 이번 달 보험료=`Wallet`/brand(-%는 neg) · 환수 위험=`AlertTriangle`/neg.
- **그리드:** `grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4`.

```tsx
// components/dashboard/StatCard.tsx
type Tone = 'brand' | 'pos' | 'neg' | 'warn';
const badge: Record<Tone, string> = {
  brand: 'bg-brand-soft text-brand',
  pos:   'bg-pos-soft text-pos',
  neg:   'bg-neg-soft text-neg',
  warn:  'bg-warn-soft text-warn',
};
export function StatCard({ icon: Icon, label, value, unit, delta, tone = 'brand' }: {
  icon: LucideIcon; label: string; value: string; unit?: string;
  delta?: { dir: 'up' | 'down'; text: string }; tone?: Tone;
}) {
  return (
    <Card className="flex items-start gap-4">
      <div className={`shrink-0 w-12 h-12 rounded-inner grid place-items-center ${badge[tone]}`}>
        <Icon className="w-6 h-6" strokeWidth={2} />
      </div>
      <div className="min-w-0">
        <p className="text-sm font-medium text-ink-sub">{label}</p>
        <p className="mt-1 flex items-baseline gap-1">
          <span className="text-3xl font-bold text-ink tracking-tight">{value}</span>
          {unit && <span className="text-sm font-medium text-ink-sub">{unit}</span>}
        </p>
        {delta && (
          <span className={`mt-1 inline-flex items-center gap-0.5 text-xs font-semibold ${
            delta.dir === 'up' ? 'text-pos' : 'text-neg'}`}>
            {delta.dir === 'up' ? <ArrowUpRight className="w-3.5 h-3.5" /> : <ArrowDownRight className="w-3.5 h-3.5" />}
            {delta.text}
          </span>
        )}
      </div>
    </Card>
  );
}
```

### 4.4 영업 단계별 고객 — 파이프라인 컬러화

- **현재:** 흰 카드 1장에 01~04가 평평하게 나열.
- **목표:** 단계별 **컬러 카드 4개 + 사이 화살표**. 각 카드: 상단에 `01` 번호(단계색 fg, bold) + 코드/이름, 하단에 큰 숫자 + 단위. 화살표는 `lg`에서만 카드 사이에 표시.
- **그리드:** `grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3`. 상단 우측에 `칸반 보기 →`(`text-sm text-brand`).

```tsx
const stages = [
  { no: '01', name: 'DB',  count: '6', unit: '명', bg: 'bg-stage1-bg', fg: 'text-stage1-fg' },
  { no: '02', name: 'TA',  count: '6', unit: '명', bg: 'bg-stage2-bg', fg: 'text-stage2-fg' },
  { no: '03', name: 'FA',  count: '4', unit: '명', bg: 'bg-stage3-bg', fg: 'text-stage3-fg' },
  { no: '04', name: '청약', count: '5', unit: '건', bg: 'bg-stage4-bg', fg: 'text-stage4-fg' },
];
<Card>
  <SectionTitle title="영업 단계별 고객"
    action={<a className="text-sm font-medium text-brand">칸반 보기 →</a>} />
  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
    {stages.map((s, i) => (
      <div key={s.no} className="relative">
        <div className={`rounded-inner p-4 ${s.bg}`}>
          <div className="flex items-center gap-2">
            <span className={`text-sm font-bold ${s.fg}`}>{s.no}</span>
            <span className="text-sm font-semibold text-ink">{s.name}</span>
          </div>
          <p className="mt-3 flex items-baseline gap-1">
            <span className="text-2xl font-bold text-ink">{s.count}</span>
            <span className="text-sm text-ink-sub">{s.unit}</span>
          </p>
        </div>
        {i < stages.length - 1 && (
          <ChevronRight className="hidden lg:block absolute -right-2.5 top-1/2 -translate-y-1/2 w-5 h-5 text-ink-muted" />
        )}
      </div>
    ))}
  </div>
</Card>
```

> `bg-stage1-bg` 형태가 config에서 안 잡히면, 단계별 클래스를 `const tone = { '01': 'bg-[#F5F7FA] text-[#8A94A6]', ... }` 식 맵으로 직접 줘도 된다.

### 4.5 월별 보험료 추이 (막대 차트)

- **목표:** 막대 6개(1~6월). 일반 막대 `bg-brand-soft`, **최신/강조 막대 `bg-brand`** + 상단에 값 라벨(`text-xs font-semibold text-brand`, 예 `27만`). 막대 상단 `rounded-t-md`. 축 라벨 `text-xs text-ink-sub`. (1번처럼 `3개월·6개월·1년` 탭을 우상단 pill 토글로 추가해도 좋음 — 기존 데이터 범위에 맞게.)
- **주의:** 차트 라이브러리를 쓰고 있으면 색만 토큰으로 교체. div 막대면 높이 비율만 유지.

### 4.6 보유계약 유지현황 (도넛) — 유지·정돈

- **목표:** 도넛 색을 토큰으로: 유지 안정=`pos`, 주의=`warn`, 환수 위험=`neg`, 회차 미입력=`ink-muted`. 가운데 숫자 `text-2xl font-bold text-ink` + 라벨. 범례는 컬러 점 + `text-sm`, 우측 숫자 `font-semibold`.

### 4.7 이번 달 목표 (프로그레스)

- **목표:** 진행 바 높이 `h-2 rounded-full bg-line`, 채움 `bg-brand`(100% 달성 항목은 그대로 brand, 경과 바는 `bg-ink-muted`). 우측 수치 `font-bold text-ink`, 퍼센트 `text-brand`. 카드 우상단 `목표 수정`(`text-sm text-brand`).

### 4.8 환수 레이더 경고 배너

- **목표:** `bg-neg-soft border border-neg/20 rounded-card p-4`. 좌측 `AlertTriangle text-neg`, 제목 `font-bold text-ink` + `위험 1건`(`text-neg`), 보조 설명 `text-sm text-ink-sub`, 우측 `ChevronRight text-ink-muted`. 클릭 영역 유지.

### 4.9 캘린더

- **목표:** 머리글 `‹ 2026년 6월 ›` 가운데 `font-bold text-ink`, 좌우 화살표 버튼. 우상단 `+ 추가`는 `bg-brand text-white rounded-pill px-3 py-1.5 text-sm`. 요일: 일=`text-neg`, 토=`text-brand`, 평일=`text-ink-sub`. 날짜 셀 `text-sm`, **오늘/선택일**은 `bg-brand text-white rounded-full` 원형. 이벤트 점은 기존 범례 색 유지(작은 `w-1.5 h-1.5 rounded-full`). 하단 범례 그대로.

### 4.10 오늘의 일정 · 할 일

- **목표:** 항목마다 좌측 컬러 점 + 시간/대상 `font-medium text-ink`, 보조 `text-sm text-ink-sub`. 하단 `일정 전체 보기·추가 →` 버튼 `border border-line rounded-inner text-brand`.

### 4.11 (선택) 하단 퀵액션 바

- 1번 하단의 `고객 리스트 / 보장 분석 / 비교 분석 리포트 / 상담 예약 문자 / 일정 관리` 같은 바로가기 카드. 인파에 동등 기능이 있으면 `grid grid-cols-2 md:grid-cols-5 gap-3`로 추가. 각 카드: 아이콘 + 라벨 + `ChevronRight`. **없으면 생략.**

---

## 5. 백엔드(DRF) 보조 작업 — 표시용 값 내려주기

프론트가 화면에서 계산하지 않도록, 대시보드 시리얼라이저에 **computed 필드**를 추가한다. (스키마 변경 없음, 집계만.)

```jsonc
// GET /api/dashboard/summary  응답 형태(예시)
{
  "advisor_name": "demo",
  "as_of": "2026-06-26",
  "stats": {
    "my_clients":       { "value": 21, "unit": "명" },
    "new_this_month":   { "value": 7,  "unit": "명", "delta_pct": 75,  "delta_dir": "up" },
    "meetings":         { "value": 0,  "unit": "건" },
    "premium_this_mo":  { "value": 27, "unit": "만원", "delta_pct": -16, "delta_dir": "down" },
    "clawback_risk":    { "value": 1,  "unit": "건", "tone": "neg" }
  },
  "pipeline": [
    { "no": "01", "name": "DB", "count": 6, "unit": "명" },
    { "no": "02", "name": "TA", "count": 6, "unit": "명" },
    { "no": "03", "name": "FA", "count": 4, "unit": "명" },
    { "no": "04", "name": "청약", "count": 5, "unit": "건" }
  ],
  "monthly_premium": [
    { "label": "1월", "value": 8 }, { "label": "2월", "value": 14 },
    { "label": "3월", "value": 11 }, { "label": "4월", "value": 20 },
    { "label": "5월", "value": 24 }, { "label": "6월", "value": 27, "highlight": true }
  ],
  "retention": { "total": 10, "stable": 8, "warning": 0, "risk": 1, "missing": 1 },
  "goal": { "elapsed_pct": 87, "d_day": 4, "meet": { "done": 0, "target": 3 },
            "premium": { "done": 27, "target": 15, "pct": 100 }, "expected_salary": 270 }
}
```

- `delta_pct`/`delta_dir`은 `(이번달 - 지난달) / 지난달`을 **백엔드에서** 계산해 내려준다.
- 프론트는 위 형태를 그대로 매핑만 한다(계산 금지).
- 기존 엔드포인트가 이미 일부 값을 주면, **형태만 위에 맞춰 정렬**하고 빠진 computed 필드만 추가한다.

---

## 6. 단계별 Claude Code 프롬프트 (복붙용)

> 각 블록을 그대로 붙여넣는다. 1번 이미지를 첨부한 상태로 진행하면 정확도가 올라간다.

### Phase 0 — 탐색 & 계획 (코드 수정 금지)

```text
우리 대시보드를 리디자인할 거야. 지금은 코드를 바꾸지 말고 분석만 해줘.

1) 현재 대시보드(홈/대시보드 라우트) 화면을 구성하는 컴포넌트 파일을 전부 찾아 트리로 보여줘.
2) 다음 섹션이 각각 어느 파일/컴포넌트에 있는지 매핑해줘:
   상단 네비, 인사+날짜 헤더, 통계 카드 5개, 영업 단계별 고객, 월별 보험료 추이,
   보유계약 유지현황(도넛), 계약 유지율, 이번 달 목표, 환수 레이더, 캘린더, 오늘의 일정·할 일.
3) 현재 색/폰트/간격/라운드가 어디서 정의되는지(tailwind.config, globals.css, 인라인) 정리해줘.
4) 데이터 패칭 방식(서버 컴포넌트 / React Query·SWR / fetch 위치)도 알려줘.
계획만 제안하고 코드는 아직 건드리지 마. 첨부한 1번 이미지가 목표 비주얼이야.
```

### Phase 1 — 디자인 토큰 + 공통 컴포넌트

```text
docs/ui-redesign-spec.md의 §2, §3을 따라 디자인 토큰을 중앙화해줘.
- tailwind.config의 theme.extend에 colors / borderRadius(card,inner) / boxShadow(card)를 §2,§3.1대로 추가.
- 페이지 배경을 bg-canvas로 적용.
- components/ui/Card.tsx, components/ui/SectionTitle.tsx를 §3.2대로 생성.
아직 개별 섹션은 건드리지 말고, 토큰과 공통 컴포넌트만. 끝나면 빌드가 통과하는지 확인하고 변경 파일 목록을 보여줘.
```

### Phase 2 — 상단 네비 + 인사 헤더 + 레이아웃 셸

```text
§4.1, §4.2, §2.3을 따라 적용해줘.
- 상단 네비는 위치 유지. 액티브 메뉴 pill(bg-brand-soft text-brand), sticky, border-b border-line.
- 본문을 max-w-[1240px] mx-auto px-4 md:px-6 컨테이너로 감싸고 섹션 간 space-y-5.
- 인사 헤더(text-2xl font-bold) + 우측 날짜(text-sm text-ink-sub) 한 줄.
기능/링크는 그대로. 모바일에서 네비가 깨지지 않게 반응형도 확인해줘.
```

### Phase 3 — 통계 카드 5개

```text
§4.3을 따라 통계 카드를 리디자인해줘.
- components/dashboard/StatCard.tsx를 명세대로 만들고(아이콘 뱃지 + 큰 숫자 + 델타),
  기존 5개 카드를 이 컴포넌트로 교체. 데이터/props는 기존 값 그대로 연결.
- 아이콘/톤 매핑: 내 고객=Users/brand, 이번 달 신규=UserPlus/brand(델타 up=pos),
  이번 달 미팅=CalendarCheck/brand, 이번 달 보험료=Wallet/brand(델타 down=neg), 환수 위험=AlertTriangle/neg.
- 그리드 grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4.
숫자가 크고 굵게, 한눈에 들어오는 게 목표야(1번 이미지 참고).
```

### Phase 4 — 영업 단계 파이프라인 컬러화

```text
§4.4를 따라 영업 단계별 고객을 단계별 컬러 카드 4개 + 화살표로 바꿔줘.
- 01 회색 / 02 분홍 / 03 크림 / 04 녹색 (§2.1 단계색).
- 카드 사이 화살표는 lg에서만. 우상단 '칸반 보기 →' 유지.
- 단계별 카운트는 기존 데이터 연결. 모바일은 1~2열로 떨어지게.
```

### Phase 5 — 차트(월별 추이 + 유지현황 도넛)

```text
§4.5, §4.6을 따라 차트 색을 토큰으로 교체해줘.
- 월별 보험료 추이: 일반 막대 bg-brand-soft, 최신 강조 막대 bg-brand + 값 라벨(text-brand).
- 보유계약 유지현황 도넛: 유지 안정=pos, 주의=warn, 환수 위험=neg, 회차 미입력=ink-muted. 범례 정돈.
차트 라이브러리를 쓰면 색 옵션만 바꾸고, 데이터/계산 로직은 손대지 마.
```

### Phase 6 — 목표·환수 레이더·캘린더·오늘의 일정

```text
§4.7~§4.10을 따라 나머지 섹션을 토큰에 맞게 정돈해줘.
- 이번 달 목표: 진행 바(h-2 rounded-full), 채움 bg-brand, 퍼센트 text-brand.
- 환수 레이더: bg-neg-soft 경고 배너, AlertTriangle, 클릭 영역 유지.
- 캘린더: 일=neg, 토=brand, 선택일 원형 bg-brand, '+ 추가' brand pill, 범례 유지.
- 오늘의 일정: 컬러 점 + 항목 텍스트 정돈, 하단 버튼 border-line.
```

### Phase 7 — QA & 마감

```text
마지막 점검을 해줘.
1) 모바일(360px)·태블릿·데스크톱에서 레이아웃이 깨지지 않는지.
2) 키보드 포커스 링이 보이는지, 색 대비가 충분한지(특히 ink-sub on white).
3) 남아있는 하드코딩 색/라운드를 토큰으로 정리.
4) pnpm/npm build와 타입체크 통과 확인.
5) 변경 전/후가 1번 이미지 느낌과 얼마나 가까운지 스스로 평가하고, 더 손볼 곳을 제안.
```

### Phase B — 백엔드 보조(선택, 프론트가 계산 중이면)

```text
docs/ui-redesign-spec.md §5의 응답 형태에 맞춰 대시보드 summary 시리얼라이저를 정리해줘.
- delta_pct/delta_dir(전월 대비)을 백엔드에서 계산해 내려주고,
- pipeline/monthly_premium/retention/goal을 명세 JSON 형태로 맞춰줘.
스키마 변경 없이 집계/computed 필드만. 기존 값이 이미 있으면 형태만 정렬하고 빠진 것만 추가.
```

---

## 7. 완료 기준 체크리스트

- [ ] 색·라운드·그림자·타이포가 `tailwind.config`/`globals.css` **한 곳**에서 정의되고, 컴포넌트에 새 하드코딩 hex가 없다.
- [ ] 통계 카드 5개에 **컬러 아이콘 뱃지 + 큰 숫자(text-3xl↑) + 델타**가 들어가 한눈에 읽힌다.
- [ ] 영업 단계가 **단계별 컬러 카드 + 화살표**로 흐름이 보인다.
- [ ] 차트·도넛·목표·캘린더 색이 토큰으로 통일됐다.
- [ ] **상단 네비 유지**, 액티브 pill·sticky 적용.
- [ ] 기존 섹션(유지현황·유지율·목표·환수 레이더·캘린더 범례)이 **하나도 빠지지 않았다.**
- [ ] 모바일까지 반응형, 포커스 링·대비 OK, build·타입체크 통과.
- [ ] 데이터/라우팅/패칭 로직은 변경되지 않았다(프레젠테이션만 수정).

---

## 8. (옵션) 상단 → 좌측 사이드바로 정말 바꾸려면

기본 권장은 **상단 유지**다. 그래도 사이드바를 원하면 별도 Phase로:

```text
대시보드를 좌측 사이드바 레이아웃으로 바꾸고 싶어(1번 이미지처럼). 단, 다른 페이지 영향은 최소화해줘.
1) AppShell 컴포넌트를 만들어 layout 단에서 nav 위치만 'sidebar' | 'top'으로 스위치 가능하게 추상화.
2) 사이드바: 폭 w-60, 로고 + 아이콘+라벨 메뉴(액티브 bg-brand-soft text-brand), 하단 사용자 프로필 카드.
3) 본문은 사이드바 우측에 flex-1, max-w 컨테이너 유지.
4) 모바일에서는 사이드바를 드로어로 접고 햄버거로 토글.
먼저 영향받는 라우트/레이아웃 파일을 매핑하고 계획부터 보여줘. 한 번에 바꾸지 말 것.
```

이 방식이면 토큰·카드 작업(Phase 1~7)은 그대로 재사용되고, 네비 컨테이너만 교체된다.
