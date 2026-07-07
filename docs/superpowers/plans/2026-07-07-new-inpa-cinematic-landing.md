# new.inpa.kr 시네마틱 랜딩 + Manager 요금제 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 새 도메인 new.inpa.kr에 클릭 전환 시네마(타자기 타이핑+타자음) → 스크롤 랜딩 하이브리드 브랜드 페이지를 만들고, billing에 Manager 플랜을 등록한다.

**Architecture:** 기존 `inpa_fe`에 `/new` 라우트를 추가하고 Next 16 `proxy.ts`(구 middleware)로 host가 new.inpa.kr인 요청의 `/`만 `/new`로 rewrite, 그 외 경로는 www로 redirect. www 랜딩 섹션은 `components/landing-sections.tsx`로 추출해 양쪽에서 재사용(www `/` 렌더 불변). 시네마 엔진은 클라이언트 상태 머신(게이트→장면 6개→스크롤 파트), 타자음은 WebAudio 합성(오디오 파일 0개).

**Tech Stack:** Next.js 16(App Router, proxy.ts) + React 19 + Tailwind v4 + WebAudio API. BE는 Django billing(시드+choices 마이그레이션).

**Spec:** `docs/superpowers/specs/2026-07-07-new-inpa-cinematic-landing-design.md`

## Global Constraints

- **www `/` 렌더 불변**: 섹션 추출은 이동만, 마크업·순서(Hero→TrustBar→Features→Showcase→Differentiators→**Audience**→HowItWorks→Pricing(3열)→Trust→FinalCTA→Footer) 변경 금지.
- **카피 레드라인**: em-dash(—) 금지, '준비 중' 금지(둘 다 `lint:copy`가 app/·components/ 전역 검사), 쉬운말·긍정 프레이밍, 과장·허위 우월 통계 금지.
- **가격 표기**: 노출 금액은 `19,900원 (VAT 별도)` 형식만. 부가세 포함 금액은 랜딩에 쓰지 않는다.
- **Manager 플랜**: price_krw=19900, 한도는 Plus와 동일(limit_ocr 200/ai_compare 100/analysis 200/promotion 100). 팀 기능 권한 게이트는 범위 밖.
- **reduced-motion**: `prefers-reduced-motion: reduce`면 타이핑 생략·즉시 표시.
- **소리**: AudioContext 생성은 반드시 게이트 버튼 클릭(사용자 제스처) 안에서.
- **모델 id 하드코딩 금지**(이번 작업엔 AI 호출 없음), 시네마 검은 화면은 영화 연출(다크모드 아님), 스크롤 파트는 라이트.
- **Next 16**: proxy는 프로젝트 루트 `proxy.ts`, export 함수명 `proxy`(또는 default). `middleware.ts` 아님.
- BE 검증: `python manage.py check` + `python manage.py test inpa` 전체 그린 + `makemigrations --check` clean. FE 검증: `npm run build` + `npm run lint:copy`.
- 커밋은 태스크 단위 Conventional Commits(한국어 스코프 가능). 마이그레이션은 billing 0006 1건만.

---

### Task 1: BE Manager 플랜 등록 (billing)

**Files:**
- Modify: `inpa_be/inpa/billing/models.py:31-37` (PLAN_CODE choices)
- Create: `inpa_be/inpa/billing/migrations/0006_manager_choice.py`
- Modify: `inpa_be/inpa/billing/management/commands/seed_billing.py`
- Modify: `inpa_be/inpa/billing/serializers.py:82` (AdminSubscriptionPatchSerializer)
- Modify: `inpa_be/inpa/billing/tests.py` (SeedBillingCommandTests에 1개 추가)

**Interfaces:**
- Produces: `Plan(code='manager')` row가 `seed_billing` 실행 시 생성됨(가격 19900, 한도 200/100/200/100). `GET /api/v1/billing/plans/`(AllowAny, price_krw 오름차순)에 자동 노출. 어드민 구독 부여 PATCH가 `plan_code='manager'` 허용.
- Consumes: 없음(독립 태스크).

- [ ] **Step 1: 실패하는 테스트 작성** — `tests.py`의 `SeedBillingCommandTests` 클래스 안에 추가(기존 `test_seeds_confirmed_prices_and_super_unlimited` 패턴):

```python
    def test_seeds_manager_plan_with_plus_limits(self):
        """manager 플랜: 19,900원(VAT 별도), 한도는 Plus와 동일, 멱등."""
        call_command('seed_billing')
        manager = Plan.objects.get(code='manager')
        self.assertEqual(manager.display_name, 'Manager')
        self.assertEqual(manager.price_krw, 19900)
        self.assertIn('VAT 별도', manager.description)
        self.assertIn('관리자', manager.description)
        plus = Plan.objects.get(code='plus')
        for field in ('limit_ocr', 'limit_ai_compare', 'limit_analysis', 'limit_promotion'):
            self.assertEqual(getattr(manager, field), getattr(plus, field))
        call_command('seed_billing')  # 멱등
        self.assertEqual(Plan.objects.filter(code='manager').count(), 1)
```

- [ ] **Step 2: 실패 확인**

Run: `cd inpa_be && python manage.py test inpa.billing.tests.SeedBillingCommandTests.test_seeds_manager_plan_with_plus_limits`
Expected: FAIL (`Plan.DoesNotExist: manager`)

- [ ] **Step 3: models.py PLAN_CODE에 manager 추가**

```python
    PLAN_CODE = (
        ('free', 'Free'),
        ('plus', 'Plus'),
        ('manager', 'Manager'),
        ('super', 'Super'),
    )
```

- [ ] **Step 4: choices 정합 마이그레이션 생성** — `python manage.py makemigrations billing -n manager_choice` 실행. 결과는 0005의 AlterField 패턴과 동일(DB 무영향, `makemigrations --check` 정합용). 생성 파일에 주석 한 줄 추가: `# Plan.code choices에 'manager' 추가 (DB 무영향)`

- [ ] **Step 5: seed_billing.py에 manager 블록 추가** — 상수(PLUS_DESCRIPTION 아래):

```python
MANAGER_DESCRIPTION = (
    '월 19,900원 (VAT 별도) · 관리자(팀장·지점장·지사장) 전용. '
    'Plus 전체 기능 + 팀원 인사 관리 · 팀원 개별 실적 관리 · 팀 전체 실적 관리.'
)
```

plus 블록과 super 블록 사이에(get_or_create, 한도는 plus와 동일 값):

```python
        manager, manager_created = Plan.objects.get_or_create(
            code='manager',
            defaults={
                'display_name': 'Manager',
                'price_krw': 19900,  # VAT 별도 (확정 2026-07-07)
                'description': MANAGER_DESCRIPTION,
                'limit_ocr': 200, 'limit_ai_compare': 100,
                'limit_analysis': 200, 'limit_promotion': 100,
            },
        )
```

성공 메시지 라인에 manager 생성/존재 표시를 free·plus·super와 같은 형식으로 추가.

- [ ] **Step 6: serializers.py 어드민 choices 확장** — `AdminSubscriptionPatchSerializer.plan_code`의 `choices=['free', 'plus', 'super']` → `choices=['free', 'plus', 'manager', 'super']`

- [ ] **Step 7: 테스트 통과 확인**

Run: `cd inpa_be && python manage.py test inpa.billing && python manage.py check && python manage.py makemigrations --check --dry-run`
Expected: billing 전체 PASS, check 0 issues, "No changes detected"

- [ ] **Step 8: 전체 스위트**

Run: `cd inpa_be && python manage.py test inpa`
Expected: 573+1 = 574+ PASS (병렬 작업분 반영 후 기준)

- [ ] **Step 9: Commit**

```bash
git add inpa_be/inpa/billing
git commit -m "feat(요금제): Manager 플랜 등록 - 19,900원 VAT 별도, Plus 동일 한도 + 팀 관리 설명 (시드·choices 0006·어드민 부여)"
```

---

### Task 2: www 랜딩 섹션 공용 추출 (렌더 불변 리팩토링)

**Files:**
- Create: `inpa_fe/components/landing-sections.tsx`
- Modify: `inpa_fe/app/page.tsx` (본문을 import로 대체)

**Interfaces:**
- Produces: `components/landing-sections.tsx`가 다음을 **export**: `NAVY`, `MINT`, `FeatureIcon`, `LandingHeader`, `HeroSection`, `TrustBar`, `FeaturesSection`, `FeatureShowcaseSection`, `DifferentiatorsSection`, `AudienceSection`, `HowItWorksSection`, `PricingSection`(www 3열), `TrustSection`, `FinalCTASection`, `LandingFooter`. 모두 기존 `app/page.tsx` 코드 **그대로 이동**(수정 0).
- Consumes: 없음.

- [ ] **Step 1: 기준 스냅샷** — 리팩토링 전 dev 서버로 `/` HTML 저장:

Run: `cd inpa_fe && (npm run dev &) && sleep 8 && curl -s http://localhost:3000/ > /tmp/landing-before.html && kill %1`
(이미 dev가 떠 있으면 curl만.) Expected: HTML에 `설계사님은`·`클로징만 준비하세요` 포함.

- [ ] **Step 2: 새 파일 생성** — `components/landing-sections.tsx`를 `"use client"`로 시작, `app/page.tsx`의 import 블록(lucide, Link, InpaMark, Reveal/CountUp, LineCompareChart)과 `NAVY`/`MINT` 상수, 12개 섹션 + `FeatureIcon` + `ShowcaseViz`를 **문자 그대로 이동**하고 각 함수/상수에 `export` 키워드만 붙인다(`ShowcaseViz`는 `FeatureShowcaseSection` 내부 전용이므로 export 불필요, 파일 내 비공개 유지 가능). `tokenStore`/`useRouter`/`useEffect`는 이동하지 않는다(page 전용).

- [ ] **Step 3: app/page.tsx 축소** — 결과 전문:

```tsx
"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { tokenStore } from "@/lib/api";
import {
  LandingHeader, HeroSection, TrustBar, FeaturesSection, FeatureShowcaseSection,
  DifferentiatorsSection, AudienceSection, HowItWorksSection, PricingSection,
  TrustSection, FinalCTASection, LandingFooter,
} from "@/components/landing-sections";

// 인파 랜딩 — 섹션 본체는 components/landing-sections.tsx (new.inpa.kr 랜딩과 공용).
export default function LandingPage() {
  const router = useRouter();
  useEffect(() => { if (tokenStore.get()) router.replace("/home"); }, [router]);
  return (
    <>
      <LandingHeader />
      <main>
        <HeroSection />
        <TrustBar />
        <FeaturesSection />
        <FeatureShowcaseSection />
        <DifferentiatorsSection />
        <AudienceSection />
        <HowItWorksSection />
        <PricingSection />
        <TrustSection />
        <FinalCTASection />
      </main>
      <LandingFooter />
    </>
  );
}
```

- [ ] **Step 4: 불변 검증**

Run: `cd inpa_fe && npm run lint:copy && npm run build` 후 dev로 `/` HTML 재캡처, before와 본문 텍스트 diff(무의미한 해시 차이 제외):
`curl -s http://localhost:3000/ > /tmp/landing-after.html && python3 -c "import re,sys; s=[re.sub(r'/_next/[^\"]*','',open(f).read()) for f in ['/tmp/landing-before.html','/tmp/landing-after.html']]; sys.exit(0 if s[0]==s[1] else 1)" && echo SAME`
Expected: build PASS, `SAME` 출력(다르면 diff로 원인 확인 — 섹션 순서·마크업이 바뀌면 실패).

- [ ] **Step 5: Commit**

```bash
git add inpa_fe/components/landing-sections.tsx inpa_fe/app/page.tsx
git commit -m "refactor(랜딩): www 랜딩 섹션을 components/landing-sections.tsx로 추출 - 렌더 불변, new 랜딩과 공용"
```

---

### Task 3: 타자기 엔진 (사운드 + 타이핑 컴포넌트)

**Files:**
- Create: `inpa_fe/lib/typewriter-sound.ts`
- Create: `inpa_fe/components/typewriter.tsx`
- Modify: `inpa_fe/app/globals.css` (커서 깜빡임 keyframes 1블록 추가)

**Interfaces:**
- Produces:
  - `class TypewriterSound { init(): void; setMuted(m: boolean): void; key(space?: boolean): void; ding(): void; isReady: boolean }` — `init()`은 사용자 제스처 핸들러 안에서만 호출.
  - `<Typewriter text active revealAll charMs? onChar? onDone? className? showCursor? />` — `active`가 true가 되면 글자 단위 타이핑 시작, 글자마다 `onChar(ch)` 호출, 완료 시 `onDone()` 1회. `revealAll`이 true면 즉시 전체 표시 + `onDone`. reduced-motion이면 자동 즉시 표시.
- Consumes: 없음.

- [ ] **Step 1: lib/typewriter-sound.ts 작성** — 전문:

```ts
// WebAudio 타자기 사운드 합성 — 오디오 파일 없이 키 클릭음을 만든다.
// AudioContext는 브라우저 자동재생 정책상 사용자 제스처(입장 게이트 클릭) 안에서 init() 해야 소리가 난다.
export class TypewriterSound {
  private ctx: AudioContext | null = null;
  private master: GainNode | null = null;
  private muted = false;

  init() {
    if (this.ctx || typeof window === "undefined") return;
    const Ctor = window.AudioContext
      ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctor) return;
    this.ctx = new Ctor();
    this.master = this.ctx.createGain();
    this.master.gain.value = 0.5;
    this.master.connect(this.ctx.destination);
  }

  get isReady() { return this.ctx !== null; }

  setMuted(m: boolean) {
    this.muted = m;
    if (this.master && this.ctx) {
      this.master.gain.setTargetAtTime(m ? 0 : 0.5, this.ctx.currentTime, 0.01);
    }
  }

  /** 글자 하나 = '탁'. 공백·문장부호는 살짝 낮고 부드럽게. 글자마다 톤을 흔들어 반복감을 없앤다. */
  key(space = false) {
    if (!this.ctx || !this.master || this.muted) return;
    if (this.ctx.state === "suspended") void this.ctx.resume();
    const t = this.ctx.currentTime;
    const dur = 0.05;
    const buf = this.ctx.createBuffer(1, Math.ceil(this.ctx.sampleRate * dur), this.ctx.sampleRate);
    const data = buf.getChannelData(0);
    for (let i = 0; i < data.length; i++) {
      data[i] = (Math.random() * 2 - 1) * (1 - i / data.length) ** 2;
    }
    const src = this.ctx.createBufferSource();
    src.buffer = buf;
    const band = this.ctx.createBiquadFilter();
    band.type = "bandpass";
    band.frequency.value = (space ? 1300 : 2100) + Math.random() * 600;
    band.Q.value = 1.2;
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(space ? 0.22 : 0.4, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + dur);
    src.connect(band); band.connect(g); g.connect(this.master);
    src.start(t);
    const osc = this.ctx.createOscillator();
    osc.type = "square";
    osc.frequency.value = 140 + Math.random() * 40;
    const og = this.ctx.createGain();
    og.gain.setValueAtTime(0.1, t);
    og.gain.exponentialRampToValueAtTime(0.001, t + 0.03);
    osc.connect(og); og.connect(this.master);
    osc.start(t); osc.stop(t + 0.035);
  }

  /** 장면 완료음: 타자기 줄바꿈 '딩'. */
  ding() {
    if (!this.ctx || !this.master || this.muted) return;
    const t = this.ctx.currentTime;
    const osc = this.ctx.createOscillator();
    osc.type = "sine";
    osc.frequency.value = 1568; // G6 근처, 옛 타자기 벨 느낌
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(0.18, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.5);
    osc.connect(g); g.connect(this.master);
    osc.start(t); osc.stop(t + 0.5);
  }
}
```

- [ ] **Step 2: globals.css에 커서 keyframes 추가** — `@keyframes cellPop` 블록 근처(모션 유틸 구역)에:

```css
/* 시네마 랜딩 타자기 커서 */
@keyframes twBlink { 0%, 49% { opacity: 1; } 50%, 100% { opacity: 0; } }
.tw-cursor { display: inline-block; width: 0.55em; height: 1.15em; margin-left: 2px; vertical-align: -0.18em; background: currentColor; animation: twBlink 1s steps(1) infinite; }
@media (prefers-reduced-motion: reduce) { .tw-cursor { animation: none; } }
```

- [ ] **Step 3: components/typewriter.tsx 작성** — 전문:

```tsx
"use client";

import { useEffect, useRef, useState } from "react";

// 글자 단위 타이핑. revealAll → 즉시 전체 표시. 문장부호 뒤에는 잠깐 쉼(타자 리듬).
type Props = {
  text: string;
  active: boolean;
  revealAll: boolean;
  charMs?: number;
  onChar?: (ch: string) => void;
  onDone?: () => void;
  className?: string;
  showCursor?: boolean;
};

const PAUSE_AFTER = new Set([".", ",", "?", "!", ":", "…"]);

export function Typewriter({
  text, active, revealAll, charMs = 70, onChar, onDone, className = "", showCursor = true,
}: Props) {
  const [count, setCount] = useState(0);
  const doneRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cbRef = useRef({ onChar, onDone });
  cbRef.current = { onChar, onDone };

  useEffect(() => {
    doneRef.current = false;
    setCount(0);
  }, [text]);

  useEffect(() => {
    if (!active) return;
    const reduced = typeof window !== "undefined"
      && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (revealAll || reduced) {
      setCount(text.length);
      if (!doneRef.current) { doneRef.current = true; cbRef.current.onDone?.(); }
      return;
    }
    let i = 0;
    const tick = () => {
      if (i >= text.length) {
        if (!doneRef.current) { doneRef.current = true; cbRef.current.onDone?.(); }
        return;
      }
      const ch = text[i];
      i += 1;
      setCount(i);
      if (ch.trim() !== "") cbRef.current.onChar?.(ch);
      const pause = PAUSE_AFTER.has(ch) ? 340 : 0;
      const jitter = Math.random() * 40 - 20;
      timerRef.current = setTimeout(tick, charMs + pause + jitter);
    };
    timerRef.current = setTimeout(tick, 160);
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [active, revealAll, text, charMs]);

  return (
    <span className={className} aria-label={text}>
      <span aria-hidden>{text.slice(0, count)}</span>
      {showCursor && count < text.length && active && !revealAll ? <span className="tw-cursor" aria-hidden /> : null}
      {showCursor && (count >= text.length || revealAll) ? <span className="tw-cursor" aria-hidden /> : null}
    </span>
  );
}
```

- [ ] **Step 4: 타입 검증**

Run: `cd inpa_fe && npm run build`
Expected: PASS (컴포넌트 미사용 상태여도 컴파일 대상).

- [ ] **Step 5: Commit**

```bash
git add inpa_fe/lib/typewriter-sound.ts inpa_fe/components/typewriter.tsx inpa_fe/app/globals.css
git commit -m "feat(시네마): 타자기 엔진 - WebAudio 합성 타자음 + 글자 단위 타이핑 컴포넌트"
```

---

### Task 4: 브랜드 스토리 섹션 (스크롤 파트 신규 6종) + 이미지 자산

**Files:**
- Create: `inpa_fe/public/landing-new/scatter-bg.webp` · `crowd-dark.webp` · `journey.webp` · `desk-dashboard.webp` (시안 PDF에서 추출·최적화 완료본, 스크래치패드 `pdf-assets/`에서 복사)
- Modify: `inpa_fe/components/inpa-logo.tsx` (옵션 prop `dotColor` 추가, 기본값 기존 `#DC2626` — 동작 불변)
- Create: `inpa_fe/components/brand-story-sections.tsx`

**Interfaces:**
- Produces: `brand-story-sections.tsx`가 export: `BrandDefinitionSection`, `PlannerJourneySection`, `SalesProcessMapSection`, `ClosingHeroSection`, `PersonaSection`, `PricingFourTiers`. 모두 prop 없는 프레젠테이션 섹션.
- Consumes: `Reveal`(components/reveal), `InpaMark`(dotColor), `Link`.

- [ ] **Step 1: InpaMark에 dotColor 추가** — Props에 `dotColor?: string;`(주석: i점 색. 기본 빨강, 페르소나 카드에서 노랑/초록 사용), 시그니처 기본값 `dotColor = "#DC2626"`, i-dot `<circle ... fill="#DC2626" />`와 ping circle 3개의 `fill`을 `{dotColor}`로 치환.

- [ ] **Step 2: 이미지 복사** — 스크래치패드 `pdf-assets/*.webp` 4개를 `inpa_fe/public/landing-new/`로 복사. `ls -lh`로 4파일(28K~59K) 확인.

- [ ] **Step 3: brand-story-sections.tsx 작성** — `"use client"`. 전문(핵심 구조 — 구현자는 이 마크업을 그대로 사용하되 Tailwind 세부 간격은 시안에 맞게 미세 조정 가능):

```tsx
"use client";

import Link from "next/link";
import { Check } from "lucide-react";
import { Reveal } from "@/components/reveal";
import { InpaMark } from "@/components/inpa-logo";

// new.inpa.kr 스크롤 파트 전용 브랜드 섹션. 시안 landing_page.pdf p9~p14.
// 카피 레드라인: em-dash 금지, '준비 중' 금지, 가격은 'N원 (VAT 별도)'만.

export function BrandDefinitionSection() {
  return (
    <section className="py-24 md:py-32 bg-[var(--surface)] text-center">
      <Reveal className="mx-auto max-w-3xl px-6">
        <h2 className="text-[34px] sm:text-[48px] font-extrabold text-[var(--brand)] tracking-tight">Insure Partner, INPA</h2>
        <p className="mt-8 text-[17px] sm:text-[20px] text-[var(--ink-2)] leading-relaxed">
          인파(INPA)는 인파(人波) 속에서도<br />
          표지판처럼 명확한 방향을,<br />
          신호등처럼 분명한 판단 기준을 제시하는<br />
          올인원 영업지원 서비스입니다.
        </p>
      </Reveal>
    </section>
  );
}

export function PlannerJourneySection() {
  return (
    <section className="py-20 md:py-28 bg-[var(--surface-2)] text-center">
      <Reveal className="mx-auto max-w-4xl px-6">
        <h2 className="text-[28px] sm:text-[36px] font-extrabold text-[var(--brand)] tracking-tight">설계사의 설계사, 인파</h2>
        <p className="mt-3 text-[16px] sm:text-[18px] text-[var(--ink-3)]">상담 준비부터 청약까지, 당신의 모든 동선을 설계합니다</p>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/landing-new/journey.webp" alt="상담 준비부터 청약까지 이어지는 여정 일러스트" className="mt-10 w-full max-w-3xl mx-auto h-auto" loading="lazy" />
      </Reveal>
    </section>
  );
}

// 보험 영업 프로세스 맵 (시안 p11) — HTML로 재구성(이미지보다 선명·반응형).
const PROCESS: { stage: string; groups: { name: string; items: { label: string; highlight?: boolean }[] }[] }[] = [
  { stage: "고객 획득", groups: [
    { name: "판촉", items: [{ label: "판촉물 디자인" }, { label: "판촉물 발주" }] },
    { name: "TM", items: [{ label: "콜스크립트 작성" }, { label: "상담 내용 기록" }] },
  ]},
  { stage: "TA", groups: [
    { name: "최초 접촉", items: [{ label: "메시지 작성" }, { label: "상담 일정 예약" }, { label: "상담 내용 기록" }] },
  ]},
  { stage: "상담 준비", groups: [
    { name: "증권 분석", items: [{ label: "기보유 증권 분석" }] },
    { name: "비교 분석", items: [{ label: "신규 가입 설계" }, { label: "가입제안서 분석" }, { label: "비교 분석" }] },
    { name: "상담 준비", items: [{ label: "비교 자료 시각화" }, { label: "영업 자료 생성" }] },
  ]},
  { stage: "FA", groups: [
    { name: "프레젠테이션", items: [{ label: "보유 상품 설명" }, { label: "제안 상품 설명" }, { label: "상품 비교 설명" }] },
    { name: "클로징", items: [{ label: "클로징 멘트", highlight: true }] },
  ]},
  { stage: "청약", groups: [
    { name: "청약서 작성", items: [{ label: "고지 의무 이행" }] },
  ]},
  { stage: "사후관리", groups: [
    { name: "보험금 청구", items: [{ label: "청구 가이드 제공" }] },
    { name: "기념일", items: [{ label: "정기 안부 연락" }, { label: "생일 축하 연락" }, { label: "생애주기별 연락" }, { label: "기타 기념일 연락" }] },
  ]},
];

export function SalesProcessMapSection() {
  return (
    <section className="py-20 md:py-28 bg-[var(--surface)]">
      <div className="mx-auto max-w-6xl px-4 sm:px-6">
        <Reveal>
          <div className="mx-auto max-w-3xl rounded-2xl bg-[var(--brand)] text-white text-center font-extrabold text-[20px] sm:text-[24px] py-4">보험 영업</div>
        </Reveal>
        <div className="mt-8 overflow-x-auto pb-4">
          <div className="flex gap-3 min-w-[1080px]">
            {PROCESS.map((col, i) => (
              <div key={col.stage} className="flex-1 min-w-[160px]">
                <div className="relative rounded-xl bg-[var(--brand)] text-white text-center font-bold text-[15px] py-2.5">
                  {col.stage}
                  {i < PROCESS.length - 1 ? <span className="absolute -right-3 top-1/2 -translate-y-1/2 text-[var(--brand)] font-extrabold">›</span> : null}
                </div>
                <div className="mt-3 space-y-3">
                  {col.groups.map((g) => (
                    <div key={g.name} className="rounded-xl border border-[var(--line)] p-3">
                      <div className="text-center text-[13px] font-bold text-[var(--ink)]">{g.name}</div>
                      <div className="mt-2 space-y-1.5">
                        {g.items.map((it) => (
                          <div key={it.label}
                            className={`rounded-lg text-center text-[12px] font-semibold py-1.5 px-1 ${it.highlight
                              ? "border border-[var(--danger)] text-[var(--danger)] bg-[var(--danger-tint)]"
                              : "bg-[var(--surface-2)] text-[var(--ink-3)]"}`}>
                            {it.label}
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
        <p className="mt-2 text-center text-[13px] text-[var(--ink-3)] sm:hidden">옆으로 밀어서 전체 과정을 볼 수 있어요</p>
      </div>
    </section>
  );
}

export function ClosingHeroSection() {
  return (
    <section className="relative overflow-hidden">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/landing-new/desk-dashboard.webp" alt="" aria-hidden className="absolute inset-0 w-full h-full object-cover opacity-40" loading="lazy" />
      <div className="absolute inset-0 bg-white/55" />
      <Reveal className="relative mx-auto max-w-4xl px-6 py-28 md:py-40 text-center">
        <h2 className="inline-block bg-[var(--accent-tint)]/80 px-4 py-1.5 rounded-xl text-[30px] sm:text-[46px] font-extrabold tracking-tight text-[var(--brand)]">
          설계사님은 <span className="text-[var(--danger)]">클로징</span>만 준비하세요
        </h2>
        <p className="mt-5 inline-block bg-white/75 px-3 py-1 rounded-lg text-[16px] sm:text-[22px] font-bold text-[var(--ink-2)]">
          상담 준비부터 청약까지, 나머지는 <span className="text-[var(--brand)]">인파</span>가 준비합니다
        </p>
      </Reveal>
    </section>
  );
}

const PERSONAS = [
  { dot: "#C73E38", label: "인파 for 설계사" },
  { dot: "#E7B23E", label: "인파 for 관리자" },
  { dot: "#6AAC72", label: "인파 for 가입자" },
];

export function PersonaSection() {
  return (
    <section className="py-20 md:py-28 bg-[var(--surface-2)] text-center">
      <div className="mx-auto max-w-5xl px-6">
        <Reveal>
          <h2 className="text-[28px] sm:text-[36px] font-extrabold text-[var(--brand)] tracking-tight">모두를 위한 인슈어 파트너, 인파</h2>
          <p className="mt-3 text-[15px] sm:text-[17px] text-[var(--ink-3)]">설계사, 관리자, 가입자 도움이 필요한 모두에게 든든한 파트너가 되어드립니다</p>
        </Reveal>
        <div className="mt-12 grid grid-cols-1 sm:grid-cols-3 gap-6">
          {PERSONAS.map((p, i) => (
            <Reveal key={p.label} delay={i * 90} className="rounded-2xl bg-[var(--accent-tint)]/60 border border-[var(--line)] px-6 py-10 flex flex-col items-center gap-6">
              <InpaMark size={96} dotColor={p.dot} title={p.label} />
              <div className="font-extrabold text-[17px] text-[var(--brand)]">{p.label}</div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

// 요금제 4단 (시안 p14 + VAT 별도 병기). 표기 한도는 시안 그대로(마케팅 문안).
const TIERS: {
  name: string; badge?: string; managerOnly?: boolean; price: string; vat?: boolean;
  features: string[]; footnote: string; highlight?: boolean;
}[] = [
  { name: "Basic", price: "0원",
    features: ["증권 자동 분석 월 5건", "비교 분석 월 1건 체험", "고객 추가 최대 5인"],
    footnote: "모든 설계사(관리직 포함)가 사용할 수 있는 기능입니다." },
  { name: "Manager", managerOnly: true, price: "19,900원", vat: true,
    features: ["Plus 모든 기능 사용 가능", "팀원 인사 관리", "팀원 개별 실적 관리", "팀 전체 실적 관리"],
    footnote: "팀장, 지점장, 지사장 등 관리자만 사용할 수 있는 기능입니다." },
  { name: "Plus", badge: "추천", highlight: true, price: "19,900원", vat: true,
    features: ["증권 자동 분석 월 100건", "비교 분석 월 50건", "영업 리포트 생성 월 50건", "신규 고객 추가 월 30인"],
    footnote: "모든 설계사(관리직 포함)가 사용할 수 있는 기능입니다." },
  { name: "Super", price: "39,900원", vat: true,
    features: ["증권 자동 분석 무제한", "비교 분석 무제한", "영업 리포트 생성 무제한", "신규 고객 추가 무제한"],
    footnote: "모든 설계사(관리직 포함)가 사용할 수 있는 기능입니다." },
];

export function PricingFourTiers() {
  return (
    <section className="py-20 md:py-28 bg-[var(--surface)]">
      <div className="mx-auto max-w-6xl px-4 sm:px-6">
        <Reveal>
          <h2 className="text-[28px] sm:text-[36px] font-extrabold text-[var(--brand)] text-center tracking-tight">인파 for 설계사 / 관리자 요금제</h2>
          <p className="mt-3 text-center text-[15px] sm:text-[17px] text-[var(--ink-3)]">최초 가입 시 한 달 무료 사용 쿠폰과 모바일 명함 무료 제작 쿠폰을 드립니다</p>
        </Reveal>
        <div className="mt-12 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
          {TIERS.map((t, i) => (
            <Reveal key={t.name} delay={i * 80}
              className={`rounded-2xl bg-[var(--surface)] p-6 flex flex-col gap-3 ${t.highlight ? "border-2 border-[var(--brand)]" : "border border-[var(--line)]"}`}>
              <div className="flex items-center gap-2">
                <span className={`text-[14px] font-bold ${t.highlight ? "text-[var(--brand)]" : "text-[var(--ink-3)]"}`}>{t.name}</span>
                {t.badge ? <span className="px-2 py-0.5 rounded-full bg-[var(--accent-tint)] text-[var(--brand)] text-[11px] font-bold">{t.badge}</span> : null}
                {t.managerOnly ? <span className="px-2 py-0.5 rounded-full bg-[var(--warning-tint)] text-[var(--warning-ink)] text-[11px] font-bold">관리자 전용</span> : null}
              </div>
              <div className="text-[26px] font-extrabold text-[var(--ink)]">
                {t.price}{t.vat ? <span className="ml-1 text-[12px] font-semibold text-[var(--ink-3)]">월 (VAT 별도)</span> : null}
              </div>
              <ul className="flex flex-col gap-2.5 text-[14px] text-[var(--ink-2)] mt-1">
                {t.features.map((f) => (
                  <li key={f} className="flex gap-2 items-start">
                    <Check size={16} className="text-[var(--success)] mt-0.5 shrink-0" strokeWidth={2.4} />{f}
                  </li>
                ))}
              </ul>
              <p className="mt-auto pt-3 text-[12px] text-[var(--ink-3)] leading-relaxed">{t.footnote}</p>
            </Reveal>
          ))}
        </div>
        <Reveal className="mt-10 mx-auto max-w-2xl rounded-2xl border border-[var(--line)] bg-[var(--surface-2)] p-6 flex items-center gap-5">
          <InpaMark size={56} dotColor="#6AAC72" title="인파 for 가입자" />
          <div className="text-left">
            <div className="text-[15px] font-extrabold text-[var(--success-ink)]">FREE!</div>
            <p className="mt-1 text-[14px] text-[var(--ink-2)] leading-relaxed">인파 for 가입자 서비스는 무료로 제공됩니다.<br />지금 바로 내 보험을 무료로 점검해보세요.</p>
          </div>
        </Reveal>
        <div className="mt-10 text-center">
          <Link href="/register" className="inline-flex px-8 py-4 rounded-2xl bg-[var(--brand)] text-white font-bold text-[16px] min-h-[52px] items-center justify-center hover:opacity-90 transition">무료로 시작하기</Link>
        </div>
      </div>
    </section>
  );
}
```

- [ ] **Step 4: 검증**

Run: `cd inpa_fe && npm run lint:copy && npm run build`
Expected: 둘 다 PASS. (가격 표기 규칙: `19,900원` + `월 (VAT 별도)` 소자 확인, 부가세 포함 금액 없음.)

- [ ] **Step 5: Commit**

```bash
git add inpa_fe/public/landing-new inpa_fe/components/brand-story-sections.tsx inpa_fe/components/inpa-logo.tsx
git commit -m "feat(시네마): 브랜드 스토리 섹션 6종(정의·여정·프로세스맵·클로징·페르소나·요금 4단) + 시안 이미지 자산"
```

---

### Task 5: 시네마 엔진 + /new 라우트 조립

**Files:**
- Create: `inpa_fe/components/cinema-landing.tsx`
- Create: `inpa_fe/app/new/page.tsx`

**Interfaces:**
- Consumes: `Typewriter`, `TypewriterSound`(Task 3) · `brand-story-sections`(Task 4) · `landing-sections`(Task 2).
- Produces: `<CinemaLanding />` (prop 없음) — 게이트 → 장면 6개 → 스크롤 랜딩 상태 머신 전체.

- [ ] **Step 1: components/cinema-landing.tsx 작성** — 전문:

```tsx
"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Volume2, VolumeX } from "lucide-react";
import { Typewriter } from "@/components/typewriter";
import { TypewriterSound } from "@/lib/typewriter-sound";
import { InpaMark } from "@/components/inpa-logo";
import {
  LandingHeader, TrustBar, FeaturesSection, FeatureShowcaseSection,
  DifferentiatorsSection, AudienceSection, HowItWorksSection,
  TrustSection, FinalCTASection, LandingFooter,
} from "@/components/landing-sections";
import {
  BrandDefinitionSection, PlannerJourneySection, SalesProcessMapSection,
  ClosingHeroSection, PersonaSection, PricingFourTiers,
} from "@/components/brand-story-sections";

// new.inpa.kr 시네마 랜딩 — 게이트(소리 허용) → 장면 6개(클릭 전환) → 스크롤 랜딩.
// 시안: landing_page.pdf p2~p14 / 스펙: docs/superpowers/specs/2026-07-07-new-inpa-cinematic-landing-design.md

type Beat = { text: string; mono?: boolean };
type Scene = {
  id: string;
  bg: "black" | "scatter" | "crowd" | "blue";
  beats: Beat[];
};

const SCENES: Scene[] = [
  { id: "definition", bg: "black", beats: [{ text: "人波 : 수많은 사람을 이르는 말" }] },
  { id: "problem", bg: "scatter", beats: [
    { text: "오늘도 흩어진 고객 명단, 엑셀, 메모장, 카톡 사이를 헤매고 있나요?" },
    { text: "보험설계사의 업무는 늘 人波 속에 있습니다." },
  ]},
  { id: "reveal", bg: "black", beats: [{ text: "INPA : Insure Partner", mono: true }] },
  { id: "bridge", bg: "black", beats: [{ text: "人波 속에서 INPA가...", mono: true }] },
  { id: "crowd", bg: "crowd", beats: [{ text: "수많은 인파 속, 흔들림 없는 안내" }] },
  { id: "promise", bg: "blue", beats: [{ text: "오직 당신만을 위한 인슈어 파트너가 되어드립니다" }] },
];

const BG_IMAGES = ["/landing-new/scatter-bg.webp", "/landing-new/crowd-dark.webp"];

type Mode = "gate" | "film" | "landing";

export function CinemaLanding() {
  const [mode, setMode] = useState<Mode>("gate");
  const [sceneIdx, setSceneIdx] = useState(0);
  const [beatIdx, setBeatIdx] = useState(0);
  const [beatDone, setBeatDone] = useState(false);
  const [revealAll, setRevealAll] = useState(false);
  const [muted, setMuted] = useState(false);
  const soundRef = useRef<TypewriterSound | null>(null);

  const scene = SCENES[sceneIdx];

  // 다음 장면 배경 미리 받아 클릭 시 끊김 방지
  useEffect(() => {
    if (typeof window === "undefined") return;
    BG_IMAGES.forEach((src) => { const img = new Image(); img.src = src; });
  }, []);

  const start = useCallback((withSound: boolean) => {
    const s = new TypewriterSound();
    if (withSound) s.init(); // 사용자 제스처 안 — 자동재생 정책 통과 지점
    s.setMuted(!withSound);
    soundRef.current = s;
    setMuted(!withSound);
    setMode("film");
  }, []);

  const skipToLanding = useCallback(() => {
    setMode("landing");
    if (typeof window !== "undefined") window.scrollTo(0, 0);
  }, []);

  const advance = useCallback(() => {
    if (mode !== "film") return;
    if (!beatDone) { setRevealAll(true); return; } // 타이핑 중 클릭 = 문장 즉시 완성
    const s = SCENES[sceneIdx];
    if (beatIdx < s.beats.length - 1) {
      setBeatIdx((b) => b + 1); setBeatDone(false); setRevealAll(false);
      return;
    }
    if (sceneIdx < SCENES.length - 1) {
      setSceneIdx((i) => i + 1); setBeatIdx(0); setBeatDone(false); setRevealAll(false);
      return;
    }
    skipToLanding();
  }, [mode, beatDone, sceneIdx, beatIdx, skipToLanding]);

  // 키보드: Space / Enter / → 로 진행
  useEffect(() => {
    if (mode !== "film") return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === " " || e.key === "Enter" || e.key === "ArrowRight") { e.preventDefault(); advance(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mode, advance]);

  const toggleMute = useCallback(() => {
    setMuted((m) => {
      const next = !m;
      if (!next && soundRef.current && !soundRef.current.isReady) soundRef.current.init();
      soundRef.current?.setMuted(next);
      return next;
    });
  }, []);

  const bgClass = useMemo(() => {
    switch (scene.bg) {
      case "blue": return "bg-[var(--brand)]";
      case "black": case "scatter": case "crowd": default: return "bg-black";
    }
  }, [scene.bg]);

  if (mode === "landing") {
    return (
      <>
        <LandingHeader />
        <main>
          <BrandDefinitionSection />
          <PlannerJourneySection />
          <SalesProcessMapSection />
          <ClosingHeroSection />
          <TrustBar />
          <FeaturesSection />
          <FeatureShowcaseSection />
          <DifferentiatorsSection />
          <AudienceSection />
          <HowItWorksSection />
          <PersonaSection />
          <PricingFourTiers />
          <TrustSection />
          <FinalCTASection />
        </main>
        <LandingFooter />
      </>
    );
  }

  if (mode === "gate") {
    return (
      <div className="fixed inset-0 z-50 bg-black text-white flex flex-col items-center justify-center gap-10 px-6 text-center">
        <InpaMark size={72} live intense pColor="#FFFFFF" />
        <div>
          <p className="text-[15px] text-white/60">인파(Inpa)</p>
          <h1 className="mt-2 text-[24px] sm:text-[30px] font-extrabold tracking-tight">1분, 인파가 준비한 짧은 이야기</h1>
        </div>
        <div className="flex flex-col sm:flex-row gap-3">
          <button type="button" onClick={() => start(true)}
            className="px-7 py-4 rounded-2xl bg-white text-black font-bold text-[16px] min-h-[52px] hover:bg-white/90 transition">
            소리와 함께 시작하기
          </button>
          <button type="button" onClick={() => start(false)}
            className="px-7 py-4 rounded-2xl border border-white/30 text-white font-bold text-[16px] min-h-[52px] hover:bg-white/10 transition">
            조용히 보기
          </button>
        </div>
        <button type="button" onClick={skipToLanding} className="text-[14px] text-white/45 underline underline-offset-4 hover:text-white/70 transition">
          건너뛰고 서비스 소개 보기
        </button>
      </div>
    );
  }

  // mode === "film"
  return (
    <div role="button" tabIndex={0} onClick={advance} onKeyDown={() => {}}
      aria-label="화면을 누르면 다음 장면으로 넘어갑니다"
      className={`fixed inset-0 z-50 ${bgClass} text-white cursor-pointer select-none overflow-hidden transition-colors duration-700`}>
      {/* 배경 레이어 */}
      {scene.bg === "scatter" ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src="/landing-new/scatter-bg.webp" alt="" aria-hidden className="absolute inset-0 w-full h-full object-cover" />
      ) : null}
      {scene.bg === "crowd" ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src="/landing-new/crowd-dark.webp" alt="" aria-hidden className="absolute inset-0 w-full h-full object-cover opacity-90" />
      ) : null}
      {scene.bg === "blue" ? (
        <div className="absolute inset-0 flex items-center justify-center opacity-15">
          <InpaMark size={560} pColor="#FFFFFF" dotColor="#8D3B72" />
        </div>
      ) : null}

      {/* 상단 컨트롤 */}
      <div className="absolute top-0 inset-x-0 flex items-center justify-end gap-2 p-4 sm:p-6">
        <button type="button" aria-label={muted ? "소리 켜기" : "소리 끄기"}
          onClick={(e) => { e.stopPropagation(); toggleMute(); }}
          className="w-11 h-11 rounded-full border border-white/25 flex items-center justify-center text-white/70 hover:bg-white/10 transition">
          {muted ? <VolumeX size={18} /> : <Volume2 size={18} />}
        </button>
        <button type="button" onClick={(e) => { e.stopPropagation(); skipToLanding(); }}
          className="px-4 h-11 rounded-full border border-white/25 text-[14px] font-semibold text-white/70 hover:bg-white/10 transition">
          건너뛰기
        </button>
      </div>

      {/* 자막(장면 텍스트) */}
      <div className="absolute inset-0 flex flex-col items-center justify-center px-6">
        <div className={scene.bg === "scatter" ? "text-[var(--ink)]" : "text-white"}>
          {scene.beats.slice(0, beatIdx + 1).map((b, i) => (
            <p key={`${scene.id}-${i}`}
              className={`text-center leading-relaxed ${b.mono ? "font-mono tracking-wide" : "font-bold"} ${
                i === 0 && scene.beats.length > 1 && beatIdx > 0 ? "text-[16px] sm:text-[22px] opacity-80" : "text-[20px] sm:text-[32px]"} ${i > 0 ? "mt-5 font-extrabold" : ""}`}>
              {i < beatIdx ? b.text : (
                <Typewriter
                  text={b.text}
                  active={mode === "film"}
                  revealAll={revealAll}
                  onChar={(ch) => soundRef.current?.key(ch === " ")}
                  onDone={() => { setBeatDone(true); soundRef.current?.ding(); }}
                />
              )}
            </p>
          ))}
        </div>
      </div>

      {/* 하단: 진행 도트 + 계속 힌트 */}
      <div className="absolute bottom-0 inset-x-0 flex flex-col items-center gap-4 p-6">
        <p className={`text-[13px] transition-opacity duration-500 ${beatDone ? "opacity-70" : "opacity-0"} ${scene.bg === "scatter" ? "text-[var(--ink-3)]" : "text-white/70"}`}>
          화면을 눌러 계속
        </p>
        <div className="flex gap-2" aria-hidden>
          {SCENES.map((s, i) => (
            <span key={s.id} className={`w-2 h-2 rounded-full transition ${i === sceneIdx ? "bg-[var(--danger)]" : scene.bg === "scatter" ? "bg-black/20" : "bg-white/25"}`} />
          ))}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: app/new/page.tsx 작성** — 전문:

```tsx
import type { Metadata } from "next";
import { CinemaLanding } from "@/components/cinema-landing";

export const metadata: Metadata = {
  title: { absolute: "인파(Inpa) · 수많은 인파 속, 흔들림 없는 안내" },
  description: "人波 속에서 INPA가. 보험설계사의 모든 영업을 한곳에, 인파의 이야기를 만나보세요.",
  alternates: { canonical: "https://new.inpa.kr/" },
};

export default function NewLandingPage() {
  return <CinemaLanding />;
}
```

- [ ] **Step 3: 빌드 + 스모크**

Run: `cd inpa_fe && npm run lint:copy && npm run build`
Expected: PASS.
Run(dev 스모크): dev 서버 기동 후 `curl -s http://localhost:3000/new | grep -o "소리와 함께 시작하기"` → `소리와 함께 시작하기` 출력, `curl -s http://localhost:3000/ | grep -c "클로징만 준비하세요"` → 1 이상(www 불변).

- [ ] **Step 4: Commit**

```bash
git add inpa_fe/components/cinema-landing.tsx inpa_fe/app/new
git commit -m "feat(시네마): /new 시네마 랜딩 - 게이트·장면 6개(타자기+타자음)·스크롤 전환 조립"
```

---

### Task 6: proxy.ts (new.inpa.kr host 라우팅)

**Files:**
- Create: `inpa_fe/proxy.ts` (프로젝트 루트, app/과 같은 레벨)

**Interfaces:**
- Consumes: `/new` 라우트(Task 5).
- Produces: host `new.inpa.kr`의 `/` → `/new` rewrite(주소창은 `/` 유지) · `/new` → `/` redirect(주소 정규화) · 그 외 경로 → `https://www.inpa.kr` redirect. 다른 host(www·vercel 프리뷰·localhost)는 무개입.

- [ ] **Step 1: proxy.ts 작성** — 전문 (Next 16: 파일명 proxy, 함수명 proxy. `middleware.ts` 금지. runtime 옵션 설정 금지 — Node.js 기본):

```ts
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// new.inpa.kr = 브랜드 시네마 랜딩 전용 host.
// '/'만 /new로 rewrite(주소창 유지), 그 외 서비스 경로는 본진(www)으로 보낸다.
// www·프리뷰·localhost 트래픽은 어떤 개입도 하지 않는다.
const NEW_HOST = "new.inpa.kr";
const MAIN_ORIGIN = "https://www.inpa.kr";

export function proxy(request: NextRequest) {
  const host = (request.headers.get("host") ?? "").toLowerCase();
  const isNewHost = host === NEW_HOST || host.startsWith(`${NEW_HOST}:`);
  if (!isNewHost) return;

  const { pathname, search } = request.nextUrl;
  if (pathname === "/") {
    return NextResponse.rewrite(new URL("/new", request.url));
  }
  if (pathname === "/new") {
    return NextResponse.redirect(new URL("/", request.url)); // 중복 주소 정규화
  }
  return NextResponse.redirect(`${MAIN_ORIGIN}${pathname}${search}`);
}

export const config = {
  // 정적 자산(_next, 확장자 있는 파일)은 통과 — 랜딩 이미지·폰트가 new host에서 그대로 서빙되도록
  matcher: ["/((?!_next|.*\\..*).*)"],
};
```

- [ ] **Step 2: 로컬 검증** — dev 서버에서 Host 헤더로 시뮬레이션:

Run:
```bash
curl -s -H "Host: new.inpa.kr" http://localhost:3000/ | grep -o "소리와 함께 시작하기" | head -1
curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" -H "Host: new.inpa.kr" http://localhost:3000/login
curl -s http://localhost:3000/ | grep -o "클로징만 준비하세요" | head -1
```
Expected: 1행 `소리와 함께 시작하기`(rewrite 동작) · 2행 `307 https://www.inpa.kr/login`(서비스 경로 www행) · 3행 `클로징만 준비하세요`(host 미일치 시 무개입).

- [ ] **Step 3: 빌드**

Run: `cd inpa_fe && npm run build`
Expected: PASS ("ƒ Proxy" 또는 proxy 표시가 빌드 출력에 등장).

- [ ] **Step 4: Commit**

```bash
git add inpa_fe/proxy.ts
git commit -m "feat(시네마): proxy.ts - new.inpa.kr host는 / -> /new rewrite, 서비스 경로는 www로"
```

---

### Task 7: 최종 검증 + 문서 갱신

**Files:**
- Modify: `README.md` (진행 중 → 구현 완료로 갱신)
- Modify: `CLAUDE.md` (§11 changelog 항목 갱신: DESIGN LOCKED → 구현 반영, Manager 플랜 백로그 체크)

- [ ] **Step 1: BE 최종** — `cd inpa_be && python manage.py check && python manage.py test inpa` 전체 그린 실출력 확보.
- [ ] **Step 2: FE 최종** — `cd inpa_fe && npm run lint:copy && npm run build` 그린 실출력 확보.
- [ ] **Step 3: 브라우저 스모크(가능 범위)** — dev에서 curl 스모크 3종(Task 6 Step 2) 재확인 + `/new` HTML에 장면 텍스트·게이트·스크롤 섹션 마커 존재 확인. 실제 소리·클릭 체험은 배포 후 PM 확인 항목으로 보고서에 명기.
- [ ] **Step 4: 문서 갱신** — README '진행 중' 항목을 '구현 완료(배포 대기)'로, CLAUDE.md §11 항목에 구현 커밋 반영, §12 백로그의 Manager 플랜 항목을 ✅로(등록 완료, 권한 게이트는 별도 ⬜ 유지).
- [ ] **Step 5: Commit + Push**

```bash
git add README.md CLAUDE.md
git commit -m "docs(시네마): new.inpa.kr 랜딩 구현 반영 - README+CLAUDE.md"
git push origin feat/design-refactor
```

- [ ] **Step 6: PM 보고** — Changed/Verified by/Result/Unverified 형식 + new.inpa.kr DNS·Vercel 도메인 연결 클릭 단위 가이드(CNAME cname.vercel-dns.com, Vercel Domains에 new.inpa.kr 추가) 포함.
