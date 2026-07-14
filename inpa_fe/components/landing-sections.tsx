"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { InpaMark } from "@/components/inpa-logo";
import { Reveal, CountUp } from "@/components/reveal";
import { LineCompareChart } from "@/components/charts";
import { getBillingEvent } from "@/lib/api";
import {
  LayoutGrid, BarChart3, ArrowLeftRight, ShieldCheck, ScanLine,
  Upload, Sparkles, Share2, Check, FileCheck,
  Users, CalendarDays, MessageSquare, Target, Package, type LucideIcon,
} from "lucide-react";

// 인파 랜딩 섹션 본체 — app/page.tsx(www)와 new.inpa.kr 랜딩이 공용으로 쓴다.
// 인파 랜딩 — Phase B: Phase A(다크 명암 리듬·lucide·타이포) + 경량 모션(스크롤 등장·카운트업·히트맵 팝).
// ★ 컴플라이언스: 단정·과장 카피 금지. AI 초안·중개권유 아님·면책 고정. 모션은 reduced-motion 존중.

export const NAVY = "#152a5e";
export const MINT = "#12B5A4";

export function FeatureIcon({ icon: Icon, tone = "brand" }: { icon: LucideIcon; tone?: "brand" | "mint" }) {
  return (
    <div className="w-11 h-11 rounded-xl flex items-center justify-center"
      style={tone === "mint" ? { background: "rgba(18,181,164,.14)", color: MINT } : { background: "var(--accent-tint)", color: "var(--brand)" }}>
      <Icon size={22} strokeWidth={1.75} aria-hidden />
    </div>
  );
}

export function LandingHeader() {
  return (
    <header className="sticky top-0 z-30 bg-[var(--surface)]/85 backdrop-blur border-b border-[var(--line)]" style={{ height: "var(--header-h)" }}>
      <div className="mx-auto max-w-6xl px-4 sm:px-6 md:px-8 lg:px-16 h-full flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2">
          <InpaMark size={30} />
          <span className="font-extrabold text-[var(--brand-ink)] text-[18px] tracking-tight">인파</span>
        </Link>
        <div className="flex items-center gap-1 sm:gap-2">
          <Link href="/blog" className="px-3 sm:px-4 py-2 rounded-xl text-[var(--ink-2)] text-[14px] font-semibold min-h-[44px] flex items-center hover:bg-[var(--surface-2)] transition">블로그</Link>
          <Link href="/login" className="px-3 sm:px-4 py-2 rounded-xl text-[var(--ink-2)] text-[14px] font-semibold min-h-[44px] flex items-center hover:bg-[var(--surface-2)] transition">로그인</Link>
          <Link href="/register" className="px-3 sm:px-4 py-2 rounded-xl bg-[var(--brand)] text-white text-[14px] font-semibold min-h-[44px] flex items-center hover:opacity-90 transition">무료로 시작하기</Link>
        </div>
      </div>
    </header>
  );
}

export function HeroSection() {
  const cells = ["line","line","enough","line","short","line",
    "line","enough","line","over","line","line",
    "short","line","line","enough","line","none",
    "line","line","enough","line","short","line"] as const;
  return (
    <section className="relative overflow-hidden" style={{ background: `linear-gradient(135deg, ${NAVY} 0%, #0c1f49 60%, #0a1838 100%)` }}>
      <div className="pointer-events-none absolute -top-24 -right-24 w-[480px] h-[480px] rounded-full opacity-20" style={{ background: `radial-gradient(circle, ${MINT} 0%, transparent 70%)` }} />
      <div className="relative mx-auto max-w-6xl px-4 sm:px-6 md:px-8 lg:px-16 py-20 md:py-28">
        <div className="flex flex-col md:flex-row items-center gap-12 md:gap-16">
          <Reveal immediate className="flex-1 text-center md:text-left">
            <span className="inline-block text-[13px] font-bold tracking-wide" style={{ color: MINT }}>보험설계사 AI 영업 파트너</span>
            <h1 className="mt-3 text-[36px] sm:text-[48px] md:text-[56px] font-extrabold text-white leading-[1.12] tracking-tight">
              설계사님은<br />클로징만 준비하세요
            </h1>
            <p className="mt-5 text-[16px] sm:text-[19px] text-white/80 leading-relaxed max-w-xl mx-auto md:mx-0">
              발굴부터 보장분석, 비교 분석까지. 인파가 준비하고, 설계사님이 완성합니다.
            </p>
            <p className="mt-2 text-[14px] sm:text-[15px] text-white/55 leading-relaxed max-w-lg mx-auto md:mx-0">
              증권 한 장으로 고객 보장 공백을 한 화면에. AI 비교안내서 초안까지, 최종 검토는 설계사님이.
            </p>
            <div className="mt-9 flex flex-col sm:flex-row gap-3 justify-center md:justify-start">
              <Link href="/register" className="w-full sm:w-auto px-7 py-4 rounded-2xl bg-white text-[var(--brand-ink)] font-bold text-[16px] min-h-[52px] flex items-center justify-center hover:bg-white/90 transition shadow-lg">무료로 시작하기</Link>
              <a href="#features" className="w-full sm:w-auto px-7 py-4 rounded-2xl border border-white/25 text-white font-bold text-[16px] min-h-[52px] flex items-center justify-center hover:bg-white/10 transition">기능 둘러보기</a>
            </div>
            <p className="mt-4 text-[13px] text-white/45">신용카드 불필요 · 베타 기간 전 기능 무료 · 이메일로 가입</p>
          </Reveal>

          <Reveal immediate delay={120} className="flex-1 w-full max-w-md md:max-w-none">
            <div className="rounded-2xl bg-white shadow-2xl overflow-hidden ring-1 ring-black/5">
              <div className="flex items-center gap-1.5 px-4 py-2.5 border-b border-[var(--line)] bg-[var(--surface-2)]">
                <span className="w-2.5 h-2.5 rounded-full" style={{ background: "var(--cov-none)" }} />
                <span className="w-2.5 h-2.5 rounded-full" style={{ background: "var(--cov-short)" }} />
                <span className="w-2.5 h-2.5 rounded-full" style={{ background: "var(--cov-enough)" }} />
                <span className="ml-2 text-[11px] font-semibold text-[var(--ink-3)]">김영수님 · 보장 한눈표</span>
              </div>
              <div className="p-4">
                <div className="grid grid-cols-6 gap-1.5">
                  {cells.map((k, i) => (
                    <span key={i} className="aspect-square rounded-[4px] cell-pop"
                      style={{ background: k === "line" ? "var(--line)" : `var(--cov-${k})`, animationDelay: `${300 + i * 32}ms` }} />
                  ))}
                </div>
                <div className="mt-4 rounded-xl border border-[var(--line)] p-3">
                  <div className="flex items-center justify-between">
                    <span className="text-[12px] font-bold text-[var(--ink)]">비교 분석</span>
                    <span className="inline-flex items-center gap-1 text-[11px] font-bold rounded-full px-2 py-0.5" style={{ color: "var(--brand)", background: "var(--accent-tint)" }}>
                      <ArrowLeftRight size={12} strokeWidth={2.2} /> 유지·전환 변동 비교
                    </span>
                  </div>
                  <div className="mt-2.5 space-y-1.5 text-[12px]">
                    <div className="flex justify-between"><span className="text-[var(--ink-3)]">해지 손실(추정)</span><span className="font-semibold text-[var(--ink)] tnum">-1,200,000원</span></div>
                    <div className="flex justify-between"><span className="text-[var(--ink-3)]">면책기간 리셋</span><span className="font-semibold text-[var(--cov-short)]">재적용 가능</span></div>
                  </div>
                </div>
              </div>
            </div>
            <p className="mt-2 text-center text-[11px] text-white/40">예시 화면</p>
          </Reveal>
        </div>
      </div>
    </section>
  );
}

export function TrustBar() {
  return (
    <section className="bg-[var(--surface)] border-b border-[var(--line)]">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 md:px-8 lg:px-16 py-6 grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="flex items-center gap-2.5 justify-center sm:justify-start">
          <LayoutGrid size={18} strokeWidth={1.75} className="text-[var(--accent-blue)]" aria-hidden />
          <span className="text-[14px] font-semibold text-[var(--ink-2)]">담보 <CountUp to={100} suffix="+" /> 항목 한눈에</span>
        </div>
        <div className="flex items-center gap-2.5 justify-center sm:justify-start">
          <ScanLine size={18} strokeWidth={1.75} className="text-[var(--accent-blue)]" aria-hidden />
          <span className="text-[14px] font-semibold text-[var(--ink-2)]">증권 한 장 자동 정리</span>
        </div>
        <div className="flex items-center gap-2.5 justify-center sm:justify-start">
          <ShieldCheck size={18} strokeWidth={1.75} className="text-[var(--accent-blue)]" aria-hidden />
          <span className="text-[14px] font-semibold text-[var(--ink-2)]">비교 시 유의사항 점검</span>
        </div>
      </div>
    </section>
  );
}

export function FeaturesSection() {
  const cards = [
    { icon: LayoutGrid, title: "보장 한눈표 (히트맵)", desc: "고객의 현재 보장을 100개 이상 담보 항목으로 한 화면에. 보유·공백을 색으로 즉시 확인합니다." },
    { icon: BarChart3, title: "보장 공백 분석", desc: "보유 0인 담보를 모아 우선순위로 정렬합니다. 충분·부족 판단은 설계사님이 설정한 기준선을 따릅니다." },
    { icon: ArrowLeftRight, title: "비교 분석 안내서", desc: "기존과 제안을 나란히 정리하고, 해지손실·면책기간 재적용·예정이율 같은 비교 시 불이익을 빠짐없이 짚어줍니다." },
  ];
  return (
    <section id="features" className="py-20 md:py-28 bg-[var(--surface)]">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 md:px-8 lg:px-16">
        <Reveal>
          <h2 className="text-[28px] sm:text-[36px] font-extrabold text-[var(--brand-ink)] text-center tracking-tight">핵심 기능</h2>
          <p className="mt-3 text-center text-[16px] text-[var(--ink-3)]">발굴 → 분석 → 제안, 한 동선으로 이어집니다.</p>
        </Reveal>
        <div className="mt-12 grid grid-cols-1 md:grid-cols-3 gap-5">
          {cards.map((c, i) => (
            <Reveal key={c.title} delay={i * 90} className="rounded-2xl bg-[var(--surface)] border border-[var(--line)] p-7 shadow-card hover:-translate-y-0.5 transition">
              <FeatureIcon icon={c.icon} />
              <h3 className="mt-4 font-bold text-[17px] text-[var(--ink)]">{c.title}</h3>
              <p className="mt-2 text-[14px] text-[var(--ink-3)] leading-relaxed">{c.desc}</p>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

// 기능 미리보기(벤치마킹 002~007) — 카드별 작은 데모 비주얼. 마케팅용 예시(실데이터 아님).
function ShowcaseViz({ kind }: { kind: "analysis" | "funnel" | "calendar" | "message" | "kpi" | "promo" }) {
  switch (kind) {
    case "analysis":
      return (
        <div className="w-full">
          <LineCompareChart
            series={[
              { label: "기존", color: "var(--existing)", points: [18, 30, 24, 38, 32] },
              { label: "제안", color: "var(--proposal)", points: [26, 40, 38, 52, 60] },
            ]}
          />
          <div className="mt-1 flex gap-3 text-[10px] text-ink3">
            <span className="inline-flex items-center gap-1"><span className="w-2.5 h-[3px] rounded" style={{ background: "var(--existing)" }} />기존</span>
            <span className="inline-flex items-center gap-1"><span className="w-2.5 h-[3px] rounded" style={{ background: "var(--proposal)" }} />제안</span>
          </div>
        </div>
      );
    case "funnel": {
      const cols = [{ l: "DB", v: 12 }, { l: "TA", v: 8 }, { l: "FA", v: 5 }, { l: "청약", v: 3 }];
      return (
        <div className="grid grid-cols-4 gap-1.5 h-full w-full items-end">
          {cols.map((c, i) => (
            <div key={c.l} className="flex flex-col items-center">
              <span className="text-[10px] font-bold text-ink tnum">{c.v}</span>
              <div className="w-full h-10 flex items-end">
                <div className="w-full rounded-t" style={{ height: `${(c.v / 12) * 100}%`, background: i === 3 ? "var(--brand)" : "var(--accent-tint)" }} />
              </div>
              <span className="text-[9px] text-ink3 mt-0.5">{c.l}</span>
            </div>
          ))}
        </div>
      );
    }
    case "calendar":
      return (
        <div className="grid grid-cols-7 gap-1 w-full">
          {Array.from({ length: 14 }, (_, i) => i + 1).map((d) => (
            <span
              key={d}
              className={`text-[8.5px] text-center rounded-full py-0.5 ${d === 12 ? "bg-brand text-white font-bold" : "text-ink3"}`}
            >
              {d}
            </span>
          ))}
        </div>
      );
    case "message":
      return (
        <div className="w-full space-y-1">
          <div className="inline-block max-w-full rounded-lg rounded-bl-none bg-accent-tint text-ink2 text-[10px] px-2 py-1 leading-snug">
            안녕하세요 김OO님, 상담 일정을 예약해 주세요 🙂
          </div>
          <div className="text-[10px] font-semibold text-brand">🔗 booking.inpa.co/1234</div>
        </div>
      );
    case "kpi":
      return (
        <div className="w-full">
          <div className="flex items-baseline justify-between">
            <span className="text-[10px] text-ink3">목표 달성률</span>
            <span className="text-[14px] font-extrabold text-brand tnum">85%</span>
          </div>
          <div className="mt-1 h-2 rounded-full bg-surface overflow-hidden">
            <div className="h-full rounded-full bg-brand" style={{ width: "85%" }} />
          </div>
          <div className="mt-1.5 text-[9px] text-ink3 tnum">목표 1억 · 실적 8,500만</div>
        </div>
      );
    case "promo":
      return (
        <div className="flex gap-1.5 w-full h-full items-center">
          {["달력", "다이어리", "생활용품"].map((l) => (
            <div key={l} className="flex-1 rounded-lg bg-surface border border-line py-3 text-center text-[9px] text-ink3">
              {l}
            </div>
          ))}
        </div>
      );
  }
}

// 실제 화면 캡처가 있는 카드는 ShowcaseViz(마케팅용 예시 그래픽) 대신 이걸 씀 — 2026-07-15 PM 지시(가짜 목업 대신 실제 화면, 적절한 위치에 배치).
const REAL_SHOTS: Partial<Record<"analysis" | "funnel" | "calendar" | "message" | "kpi" | "promo", { src: string; alt: string }>> = {
  analysis: { src: "/landing-new/compare-analysis.webp", alt: "보험 분석 & 비교 실제 화면: 현재 보장과 제안 보장의 담보별 비교" },
  funnel: { src: "/landing-new/customer-pipeline.webp", alt: "고객 관리 시스템 실제 화면: 고객 검색과 영업 단계별 분류" },
  calendar: { src: "/landing-new/schedule-calendar.webp", alt: "일정 & 예약 관리 실제 화면: 캘린더와 오늘 일정" },
};

export function FeatureShowcaseSection() {
  const cards: { icon: LucideIcon; title: string; sub: string; kind: "analysis" | "funnel" | "calendar" | "message" | "kpi" | "promo" }[] = [
    { icon: ArrowLeftRight, title: "보험 분석 & 비교", sub: "기존 증권 분석 및 비교 차트 제공", kind: "analysis" },
    { icon: Users, title: "고객 관리 시스템", sub: "영업 4단계별 고객 분류·관리", kind: "funnel" },
    { icon: CalendarDays, title: "일정 & 예약 관리", sub: "상담 일정 예약 및 자동 등록", kind: "calendar" },
    { icon: MessageSquare, title: "문자 & 예약 링크", sub: "예약 링크·메시지 문구를 복사해 직접 전달", kind: "message" },
    { icon: Target, title: "성과 관리 & KPI", sub: "목표 설정 및 성과 추적", kind: "kpi" },
    { icon: Package, title: "판촉물 디자인 & 발주", sub: "디자인 요청부터 발주까지 한번에", kind: "promo" },
  ];
  return (
    <section className="py-20 md:py-28 bg-[var(--surface-2)]">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 md:px-8 lg:px-16">
        <Reveal>
          <h2 className="text-[28px] sm:text-[36px] font-extrabold text-[var(--brand-ink)] text-center tracking-tight">기능 한눈에 보기</h2>
          <p className="mt-3 text-center text-[16px] text-[var(--ink-3)]">분석부터 고객관리·일정·성과까지, 영업 한 동선을 한 앱에서.</p>
        </Reveal>
        <div className="mt-12 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {cards.map((c, i) => {
            const shot = REAL_SHOTS[c.kind];
            return (
              <Reveal
                key={c.title}
                delay={(i % 3) * 90}
                className="rounded-2xl bg-[var(--surface)] border border-[var(--line)] p-6 shadow-card hover:-translate-y-0.5 transition"
              >
                <FeatureIcon icon={c.icon} />
                <h3 className="mt-4 font-bold text-[16px] text-[var(--ink)]">{c.title}</h3>
                <p className="mt-1.5 text-[13px] text-[var(--ink-3)] leading-relaxed">{c.sub}</p>
                {shot ? (
                  <div className="mt-4 rounded-xl border border-[var(--line)] overflow-hidden h-24">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={shot.src} alt={shot.alt} className="w-full h-full object-cover object-top" loading="lazy" />
                  </div>
                ) : (
                  <div className="mt-4 rounded-xl bg-[var(--surface-2)] border border-[var(--line)] px-3 min-h-[84px] h-24 flex items-center">
                    <ShowcaseViz kind={c.kind} />
                  </div>
                )}
              </Reveal>
            );
          })}
        </div>
      </div>
    </section>
  );
}

export function DifferentiatorsSection() {
  const items = [
    { icon: ShieldCheck, badge: "비교 분석 가드레일: 점검 전엔 발행 잠금", title: "비교 시 불이익을 빠짐없이 점검하는 비교안내",
      desc: "다른 상품으로 바꿀 때 고객에게 불리할 수 있는 항목(해지환급금 손실·면책기간 재적용·예정이율 등)을 빠짐없이 점검하도록 돕습니다. 점검 전에는 고객 발행을 잠가 빠뜨림을 줄여요. 공식 비교안내서는 설계사님이 직접 확인해 완성합니다." },
    { icon: LayoutGrid, badge: "담보 100+ 표준화 · 보험사별 명칭 자동 매핑", title: "어떤 보험사 증권도 같은 틀로",
      desc: "'암진단급부금', '일반암진단비', '암진단 특약'처럼 회사마다 다른 이름을 100개 이상 표준 담보로 자동 정규화합니다. 데이터가 쌓일수록 매칭 정확도가 높아집니다." },
  ];
  return (
    <section className="py-20 md:py-28" style={{ background: NAVY }}>
      <div className="mx-auto max-w-6xl px-4 sm:px-6 md:px-8 lg:px-16">
        <Reveal><h2 className="text-[28px] sm:text-[36px] font-extrabold text-white text-center tracking-tight">인파만의 차별점</h2></Reveal>
        <div className="mt-12 grid grid-cols-1 md:grid-cols-2 gap-6">
          {items.map((it, i) => (
            <Reveal key={it.title} delay={i * 90} className="rounded-2xl bg-white/[0.06] border border-white/10 p-7">
              <div className="mb-4"><FeatureIcon icon={it.icon} tone="mint" /></div>
              <span className="inline-block mb-3 px-3 py-1 rounded-full text-[12px] font-bold" style={{ background: "rgba(18,181,164,.16)", color: MINT }}>{it.badge}</span>
              <h3 className="font-bold text-[18px] text-white">{it.title}</h3>
              <p className="mt-2 text-[14px] text-white/65 leading-relaxed">{it.desc}</p>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

export function HowItWorksSection() {
  const steps = [
    { n: "1", icon: Upload, title: "증권 PDF 업로드", desc: "고객 보험 증권 PDF를 올리세요. 여러 장 한 번에 가능합니다." },
    { n: "2", icon: Sparkles, title: "자동 분석·정리", desc: "스캔 → 인식 → 분류 → 분석 단계로 담보를 표준 틀에 매핑하고 보장 공백을 계산합니다." },
    { n: "3", icon: Share2, title: "비교안내서 · 메시지 공유", desc: "고객에게 보낼 비교안내서·메시지를 만들고, 클립보드로 복사해 직접 전달하세요." },
  ];
  return (
    <section className="py-20 md:py-28 bg-[var(--surface-2)]">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 md:px-8 lg:px-16">
        <Reveal><h2 className="text-[28px] sm:text-[36px] font-extrabold text-[var(--brand-ink)] text-center tracking-tight">어떻게 쓰나요?</h2></Reveal>
        <div className="mt-12 grid grid-cols-1 md:grid-cols-3 gap-6">
          {steps.map((s, i) => (
            <Reveal key={s.n} delay={i * 90} className="rounded-2xl bg-[var(--surface)] border border-[var(--line)] p-7">
              <div className="flex items-center gap-3">
                <span className="w-8 h-8 rounded-full bg-[var(--brand)] text-white font-bold text-[14px] flex items-center justify-center">{s.n}</span>
                <FeatureIcon icon={s.icon} />
              </div>
              <h3 className="mt-4 font-bold text-[16px] text-[var(--ink)]">{s.title}</h3>
              <p className="mt-2 text-[14px] text-[var(--ink-3)] leading-relaxed">{s.desc}</p>
            </Reveal>
          ))}
        </div>
        <p className="mt-8 text-center text-[13px] text-[var(--ink-3)]">메시지를 복사해 고객에게 바로 전달하세요.</p>
      </div>
    </section>
  );
}

export function PricingSection() {
  // 첫 결제 보너스 이벤트가 실제 켜져 있을 때만 이벤트 문구를 노출(§6 정직성). 기본 false.
  // 연 결제 할인(2개월 무료)은 실제 가격이므로 항상 노출한다.
  const [bonusEnabled, setBonusEnabled] = useState(false);
  useEffect(() => {
    let alive = true;
    getBillingEvent()
      .then((e) => { if (alive) setBonusEnabled(e.first_paid_bonus_enabled); })
      .catch(() => { if (alive) setBonusEnabled(false); });
    return () => { alive = false; };
  }, []);
  const free = ["증권 분석·비교 분석 핵심 기능 포함", "베타 기간에는 월 한도 없이", "보장 한눈표 조회 무제한"];
  const plus = ["증권 분석 더 많이", "비교안내서 복수 발행", "AI 분석·메시지 제한 완화", "판촉물 주문 제한 완화"];
  const superPlan = ["Plus의 모든 기능 포함", "증권 분석·비교안내서 무제한", "AI 분석·메시지 무제한", "판촉물 주문 무제한"];
  return (
    <section className="py-20 md:py-28 bg-[var(--surface)]">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 md:px-8 lg:px-16">
        <Reveal>
          <h2 className="text-[28px] sm:text-[36px] font-extrabold text-[var(--brand-ink)] text-center tracking-tight">요금제</h2>
          <p className="mt-3 text-center text-[15px] text-[var(--ink-3)]">지금은 베타 기간이라 모든 요금제 기능을 무료로 이용할 수 있어요.</p>
          <div className="mt-5 mx-auto max-w-2xl rounded-2xl border border-[var(--brand)] bg-[var(--accent-tint)] px-5 py-3 text-center">
            {bonusEnabled && (
              <p className="text-[14px] font-bold text-[var(--brand)]">첫 유료 결제 시 한 달 더 (2개월 이용)</p>
            )}
            <p className="mt-0.5 text-[13px] text-[var(--ink-2)]">연 결제 시 2개월 무료 · 약 17% 할인</p>
          </div>
        </Reveal>
        <div className="mt-12 grid grid-cols-1 md:grid-cols-3 gap-6 max-w-5xl mx-auto">
          <Reveal className="rounded-2xl bg-[var(--surface)] border border-[var(--line)] p-7 flex flex-col gap-3">
            <div className="text-[13px] font-semibold text-[var(--ink-3)] uppercase tracking-wide">무료</div>
            <div className="text-[28px] font-extrabold text-[var(--ink)]">0원</div>
            <p className="text-[13px] text-[var(--ink-3)]">이제 고객 명단을 만들기 시작한 설계사님에게 딱 맞아요.</p>
            <ul className="flex flex-col gap-2.5 text-[14px] text-[var(--ink-2)] mt-1">
              {free.map((f) => (<li key={f} className="flex gap-2 items-start"><Check size={17} className="text-[var(--success)] mt-0.5 shrink-0" strokeWidth={2.4} />{f}</li>))}
            </ul>
            <Link href="/register" className="mt-auto w-full py-3.5 rounded-xl bg-[var(--brand)] text-white font-bold text-[15px] text-center min-h-[50px] flex items-center justify-center hover:opacity-90 transition">무료로 시작하기</Link>
          </Reveal>
          <Reveal delay={90} className="rounded-2xl bg-[var(--surface)] border-2 border-[var(--brand)] p-7 flex flex-col gap-3 relative">
            <div className="flex items-center gap-2">
              <div className="text-[13px] font-semibold text-[var(--brand)] uppercase tracking-wide">Plus</div>
              <span className="px-2 py-0.5 rounded-full bg-[var(--accent-tint)] text-[var(--brand)] text-[11px] font-bold">추천</span>
            </div>
            <div className="text-[28px] font-extrabold text-[var(--ink)]">월 19,900원 <span className="text-[13px] font-semibold text-[var(--ink-3)]">(VAT 별도)</span></div>
            <div className="text-[13px] font-semibold text-[var(--brand)]">연 199,000원 · 2개월 무료 (VAT 별도)</div>
            <p className="text-[13px] text-[var(--ink-3)]">증권 분석이 일상이 된 설계사님에게 딱 맞아요.</p>
            <ul className="flex flex-col gap-2.5 text-[14px] text-[var(--ink-2)] mt-1">
              {plus.map((f) => (<li key={f} className="flex gap-2 items-start"><Check size={17} className="text-[var(--success)] mt-0.5 shrink-0" strokeWidth={2.4} />{f}</li>))}
            </ul>
            <Link href="/register" className="mt-auto w-full py-3.5 rounded-xl border-2 border-[var(--brand)] text-[var(--brand)] font-bold text-[15px] text-center min-h-[50px] flex items-center justify-center hover:bg-[var(--accent-tint)] transition">베타 신청하기</Link>
          </Reveal>
          <Reveal delay={180} className="rounded-2xl bg-[var(--surface)] border border-[var(--line)] p-7 flex flex-col gap-3">
            <div className="text-[13px] font-semibold text-[var(--ink-3)] uppercase tracking-wide">Super</div>
            <div className="text-[28px] font-extrabold text-[var(--ink)]">월 39,900원 <span className="text-[13px] font-semibold text-[var(--ink-3)]">(VAT 별도)</span></div>
            <div className="text-[13px] font-semibold text-[var(--brand)]">연 399,000원 · 2개월 무료 (VAT 별도)</div>
            <p className="text-[13px] text-[var(--ink-3)]">팀 단위로, 한도 걱정 없이 쓰는 설계사님에게 딱 맞아요.</p>
            <ul className="flex flex-col gap-2.5 text-[14px] text-[var(--ink-2)] mt-1">
              {superPlan.map((f) => (<li key={f} className="flex gap-2 items-start"><Check size={17} className="text-[var(--success)] mt-0.5 shrink-0" strokeWidth={2.4} />{f}</li>))}
            </ul>
            <Link href="/register" className="mt-auto w-full py-3.5 rounded-xl border border-[var(--line)] text-[var(--ink)] font-bold text-[15px] text-center min-h-[50px] flex items-center justify-center hover:bg-[var(--surface-2)] transition">무료로 먼저 확인해보기</Link>
          </Reveal>
        </div>
      </div>
    </section>
  );
}

export function TrustSection() {
  const items = [
    { icon: FileCheck, title: "인파는 보험을 중개하지 않아요", desc: "인파는 보험을 중개·권유하지 않는 분석·정리 소프트웨어입니다. 보장 판단과 고객 안내는 설계사님의 업무이며, 산출물은 AI가 정리한 참고 자료입니다. 특정 상품이 심의를 완료했다거나 안전하다는 표시도 하지 않습니다." },
  ];
  return (
    <section className="py-20 md:py-28 bg-[var(--accent-tint)]">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 md:px-8 lg:px-16">
        <Reveal><h2 className="text-[28px] sm:text-[36px] font-extrabold text-[var(--brand-ink)] text-center tracking-tight">인파가 지키는 원칙</h2></Reveal>
        <div className="mt-12 grid grid-cols-1 md:grid-cols-2 gap-6">
          {items.map((it, i) => (
            <Reveal key={it.title} delay={i * 90} className="rounded-2xl bg-[var(--surface)] border border-[var(--line)] p-7 flex gap-4">
              <FeatureIcon icon={it.icon} />
              <div>
                <h3 className="font-bold text-[16px] text-[var(--ink)]">{it.title}</h3>
                <p className="mt-1.5 text-[14px] text-[var(--ink-3)] leading-relaxed">{it.desc}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

export function FinalCTASection() {
  return (
    <section className="py-20 md:py-28 text-center" style={{ background: `linear-gradient(135deg, ${NAVY}, #0a1838)` }}>
      <Reveal className="mx-auto max-w-2xl px-6">
        <h2 className="text-[28px] sm:text-[40px] font-extrabold text-white leading-tight tracking-tight">
          지금, 첫 고객의<br /><span style={{ color: MINT }}>보장 공백</span>부터 보세요
        </h2>
        <p className="mt-4 text-[16px] text-white/70">증권 한 장이면 시작입니다. 지금은 베타 기간이라 전 기능 무료예요.</p>
        <Link href="/register" className="mt-8 inline-flex px-8 py-4 rounded-2xl bg-white text-[var(--brand-ink)] font-bold text-[16px] min-h-[52px] items-center justify-center hover:bg-white/90 transition shadow-lg">무료로 분석 시작하기</Link>
        <p className="mt-4 text-[13px] text-white/45">신용카드 불필요 · 이메일로 가입</p>
      </Reveal>
    </section>
  );
}

export function LandingFooter() {
  return (
    <footer className="text-white py-12" style={{ background: "#0a1838" }}>
      <div className="mx-auto max-w-6xl px-4 sm:px-6 md:px-8 lg:px-16">
        <div className="flex flex-col md:flex-row gap-8 md:gap-0 md:justify-between">
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2"><InpaMark size={24} /><span className="font-extrabold text-[17px]">인파 (Inpa)</span></div>
            <p className="text-[13px] text-white/55 max-w-xs leading-relaxed">보험설계사의 AI 영업 파트너. 발굴부터 보장분석, 비교 분석까지.</p>
          </div>
          <div className="flex flex-col gap-2.5 text-[13px]">
            <Link href="/blog" className="text-white/70 hover:text-white transition">블로그</Link>
            <Link href="/faq" className="text-white/70 hover:text-white transition">자주 묻는 질문</Link>
            <Link href="/legal/terms" className="text-white/70 hover:text-white transition">이용약관</Link>
            <Link href="/legal/privacy" className="text-white/70 hover:text-white transition">개인정보처리방침</Link>
            <Link href="/data-policy" className="text-white/70 hover:text-white transition">데이터 처리 안내</Link>
          </div>
        </div>
        <div className="mt-10 pt-6 border-t border-white/15 text-[12px] text-white/40 flex flex-col gap-1">
          <p>(주)서울엘엔에스금융컨설팅 · 대표 황희철 · 사업자등록번호 109-86-17632 · 통신판매업신고 2021-서울구로-1990 · 서울특별시 금천구 서부샛길 606, A동 24층 2409호 · hello.fingo.official@gmail.com</p>
          <p className="mt-2 text-white/55">인파는 보험을 중개·권유하지 않는 분석·정리 도구이며, 산출물은 AI가 정리한 참고 자료예요.</p>
          <p className="mt-1">© 2026 Inpa. All rights reserved.</p>
        </div>
      </div>
    </footer>
  );
}

// 두 청중(개인/관리직) 가치 — 마케팅 방향(PM 06.24 토론)
export function AudienceSection() {
  const cards = [
    {
      tag: "개인 설계사",
      title: "잡일은 88% 줄이고,\n그 시간으로 첫 고객을 만드세요",
      body: "증권 분석 30분 → 3분, 제안서 40분 → 5분. 번 시간은 발굴에. 셀프진단 링크 하나면 잠재고객이 알아서 내 고객 명단에 들어옵니다.",
    },
    {
      tag: "관리직(팀장·지점장)",
      title: "팀원이 편해지면\n팀장님 숫자가 좋아집니다",
      body: "월말 취합 엑셀은 그만. 팀 퍼널·유지율·이번 달 실적을 실시간으로 봅니다. 보고 받지 마세요, 인파에서 바로 보세요. (성과 수치는 추정)",
    },
  ];
  return (
    <section className="py-20 md:py-28 bg-[var(--surface)]">
      <div className="mx-auto max-w-5xl px-4 sm:px-6">
        <Reveal>
          <h2 className="text-[28px] sm:text-[36px] font-extrabold text-[var(--brand-ink)] text-center tracking-tight">어떤 분에게 딱 맞나요?</h2>
        </Reveal>
        <div className="mt-10 grid gap-5 md:grid-cols-2">
          {cards.map((c) => (
            <Reveal key={c.tag}>
              <div className="h-full rounded-2xl border border-[var(--line)] bg-[var(--surface-2)] p-6">
                <span className="inline-block text-[12px] font-bold text-brand bg-accent-tint px-2.5 py-1 rounded-full">{c.tag}</span>
                <h3 className="mt-3 text-[20px] font-extrabold text-[var(--brand-ink)] leading-snug whitespace-pre-line">{c.title}</h3>
                <p className="mt-2.5 text-[14px] text-[var(--ink-2)] leading-6">{c.body}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
