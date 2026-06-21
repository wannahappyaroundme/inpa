"use client";

import Link from "next/link";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { tokenStore } from "@/lib/api";
import { InpaMark } from "@/components/inpa-logo";
import { Reveal, CountUp } from "@/components/reveal";
import {
  LayoutGrid, BarChart3, ArrowLeftRight, ShieldCheck, ScanLine,
  Upload, Sparkles, Share2, Check, FileCheck, Ban, type LucideIcon,
} from "lucide-react";

// 인파 랜딩 — Phase B: Phase A(다크 명암 리듬·lucide·타이포) + 경량 모션(스크롤 등장·카운트업·히트맵 팝).
// ★ 컴플라이언스: 단정·과장 카피 금지. AI 초안·중개권유 아님·면책 고정. 모션은 reduced-motion 존중.

const NAVY = "#152a5e";
const MINT = "#12B5A4";

function FeatureIcon({ icon: Icon, tone = "brand" }: { icon: LucideIcon; tone?: "brand" | "mint" }) {
  return (
    <div className="w-11 h-11 rounded-xl flex items-center justify-center"
      style={tone === "mint" ? { background: "rgba(18,181,164,.14)", color: MINT } : { background: "var(--accent-tint)", color: "var(--brand)" }}>
      <Icon size={22} strokeWidth={1.75} aria-hidden />
    </div>
  );
}

function LandingHeader() {
  return (
    <header className="sticky top-0 z-30 bg-[var(--surface)]/85 backdrop-blur border-b border-[var(--line)]" style={{ height: "var(--header-h)" }}>
      <div className="mx-auto max-w-6xl px-4 sm:px-6 md:px-8 lg:px-16 h-full flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2">
          <InpaMark size={30} />
          <span className="font-extrabold text-[var(--brand-ink)] text-[18px] tracking-tight">인파</span>
        </Link>
        <div className="flex items-center gap-2">
          <Link href="/login" className="px-4 py-2 rounded-xl text-[var(--ink-2)] text-[14px] font-semibold min-h-[44px] flex items-center hover:bg-[var(--surface-2)] transition">로그인</Link>
          <Link href="/register" className="px-4 py-2 rounded-xl bg-[var(--brand)] text-white text-[14px] font-semibold min-h-[44px] flex items-center hover:opacity-90 transition">무료로 시작하기</Link>
        </div>
      </div>
    </header>
  );
}

function HeroSection() {
  const cells = ["line","line","enough","line","short","line",
    "line","enough","line","over","line","line",
    "short","line","line","enough","line","none",
    "line","line","enough","line","short","line"] as const;
  return (
    <section className="relative overflow-hidden" style={{ background: `linear-gradient(135deg, ${NAVY} 0%, #0c1f49 60%, #0a1838 100%)` }}>
      <div className="pointer-events-none absolute -top-24 -right-24 w-[480px] h-[480px] rounded-full opacity-20" style={{ background: `radial-gradient(circle, ${MINT} 0%, transparent 70%)` }} />
      <div className="relative mx-auto max-w-6xl px-4 sm:px-6 md:px-8 lg:px-16 py-20 md:py-28">
        <div className="flex flex-col md:flex-row items-center gap-12 md:gap-16">
          <Reveal className="flex-1 text-center md:text-left">
            <span className="inline-block text-[13px] font-bold tracking-wide" style={{ color: MINT }}>보험설계사 AI 영업 파트너</span>
            <h1 className="mt-3 text-[36px] sm:text-[48px] md:text-[56px] font-extrabold text-white leading-[1.12] tracking-tight">
              설계사님은<br />클로징만 준비하세요
            </h1>
            <p className="mt-5 text-[16px] sm:text-[19px] text-white/80 leading-relaxed max-w-xl mx-auto md:mx-0">
              발굴부터 보장분석, 갈아타기 제안까지 — 인파가 준비하고, 설계사님이 완성합니다.
            </p>
            <p className="mt-2 text-[14px] sm:text-[15px] text-white/55 leading-relaxed max-w-lg mx-auto md:mx-0">
              증권 한 장으로 고객 보장 공백을 한 화면에. 합법적인 비교안내서 초안까지.
            </p>
            <div className="mt-9 flex flex-col sm:flex-row gap-3 justify-center md:justify-start">
              <Link href="/register" className="w-full sm:w-auto px-7 py-4 rounded-2xl bg-white text-[var(--brand-ink)] font-bold text-[16px] min-h-[52px] flex items-center justify-center hover:bg-white/90 transition shadow-lg">무료로 시작하기</Link>
              <a href="#features" className="w-full sm:w-auto px-7 py-4 rounded-2xl border border-white/25 text-white font-bold text-[16px] min-h-[52px] flex items-center justify-center hover:bg-white/10 transition">기능 둘러보기</a>
            </div>
            <p className="mt-4 text-[13px] text-white/45">신용카드 불필요 · 베타 기간 무제한 · 이메일로 가입</p>
          </Reveal>

          <Reveal delay={120} className="flex-1 w-full max-w-md md:max-w-none">
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
                    <span className="text-[12px] font-bold text-[var(--ink)]">갈아타기 분석</span>
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

function TrustBar() {
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
          <span className="text-[14px] font-semibold text-[var(--ink-2)]">§97 <CountUp to={6} />항목 자동 체크</span>
        </div>
      </div>
    </section>
  );
}

function FeaturesSection() {
  const cards = [
    { icon: LayoutGrid, title: "보장 한눈표 (히트맵)", desc: "고객의 현재 보장을 100개 이상 담보 항목으로 한 화면에. 보유·공백을 색으로 즉시 확인합니다." },
    { icon: BarChart3, title: "보장 공백 분석", desc: "보유 0인 담보를 모아 우선순위로 정렬합니다. 충분·부족 판단은 설계사님이 설정한 기준선을 따릅니다." },
    { icon: ArrowLeftRight, title: "갈아타기 비교안내서", desc: "기존과 제안을 나란히 정리한 비교안내 자료를 만듭니다. 부당승환(§97) 예방 항목이 함께 정리됩니다." },
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
            <Reveal key={c.title} delay={i * 90} className="rounded-2xl bg-[var(--surface)] border border-[var(--line)] p-7 shadow-[0_1px_2px_rgba(16,24,40,.04),0_12px_28px_-12px_rgba(16,24,40,.10)] hover:-translate-y-0.5 transition">
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

function DifferentiatorsSection() {
  const items = [
    { icon: ShieldCheck, badge: "§97 6항목 자동 완성 — 미달이면 발행 불가", title: "부당승환 걱정 없는 비교안내",
      desc: "보험업법 제97조가 요구하는 6가지 비교 항목(해지환급금 손실·면책기간·예정이율 등)을 자동으로 정리합니다. 기준 미달 시 고객 발행을 차단해 법적 리스크를 줄입니다." },
    { icon: LayoutGrid, badge: "담보 100+ 표준화 · 보험사별 명칭 자동 매핑", title: "어떤 보험사 증권도 같은 틀로",
      desc: "'암진단급부금', '일반암진단비', '암진단 특약' — 회사마다 다른 이름을 100개 이상 표준 담보로 자동 정규화합니다. 데이터가 쌓일수록 매칭 정확도가 높아집니다." },
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

function HowItWorksSection() {
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
        <p className="mt-8 text-center text-[13px] text-[var(--ink-3)]">자동 발송은 지원하지 않습니다. 메시지는 클립보드 복사 후 직접 전달해 주세요.</p>
      </div>
    </section>
  );
}

function PricingSection() {
  const free = ["증권 분석 월 N건 (베타 확정)", "비교안내서 월 1건 체험", "보장 히트맵 조회 무제한"];
  const plus = ["증권 분석 더 많이", "비교안내서 복수 발행", "AI 분석·메시지 제한 완화", "판촉물 주문 제한 완화"];
  return (
    <section className="py-20 md:py-28 bg-[var(--surface)]">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 md:px-8 lg:px-16">
        <Reveal>
          <h2 className="text-[28px] sm:text-[36px] font-extrabold text-[var(--brand-ink)] text-center tracking-tight">요금제</h2>
          <p className="mt-3 text-center text-[15px] text-[var(--ink-3)]">베타 기간 전 기능 무료 — 정식 출시 후에도 베타 가입자 혜택 유지.</p>
        </Reveal>
        <div className="mt-12 grid grid-cols-1 md:grid-cols-2 gap-6 max-w-3xl mx-auto">
          <Reveal className="rounded-2xl bg-[var(--surface)] border border-[var(--line)] p-7 flex flex-col gap-3">
            <div className="text-[13px] font-semibold text-[var(--ink-3)] uppercase tracking-wide">무료</div>
            <div className="text-[34px] font-extrabold text-[var(--ink)]">0원</div>
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
            <div className="text-[24px] font-extrabold text-[var(--ink)]">추후 공개</div>
            <ul className="flex flex-col gap-2.5 text-[14px] text-[var(--ink-2)] mt-1">
              {plus.map((f) => (<li key={f} className="flex gap-2 items-start"><Check size={17} className="text-[var(--success)] mt-0.5 shrink-0" strokeWidth={2.4} />{f}</li>))}
            </ul>
            <Link href="/register" className="mt-auto w-full py-3.5 rounded-xl border-2 border-[var(--brand)] text-[var(--brand)] font-bold text-[15px] text-center min-h-[50px] flex items-center justify-center hover:bg-[var(--accent-tint)] transition">베타 신청하기</Link>
          </Reveal>
        </div>
      </div>
    </section>
  );
}

function TrustSection() {
  const items = [
    { icon: FileCheck, title: "AI 초안, 최종책임은 설계사", desc: "인파가 만든 비교안내서·메시지는 AI 초안입니다. 보장 판단과 최종 전달 책임은 담당 설계사님에게 있습니다." },
    { icon: Ban, title: "'심의완료'·'안전' 배지 없음", desc: "특정 상품이 심의를 완료했다거나 안전하다는 표시를 하지 않습니다. 인파는 보험을 중개·권유하지 않습니다." },
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

function FinalCTASection() {
  return (
    <section className="py-20 md:py-28 text-center" style={{ background: `linear-gradient(135deg, ${NAVY}, #0a1838)` }}>
      <Reveal className="mx-auto max-w-2xl px-6">
        <h2 className="text-[28px] sm:text-[40px] font-extrabold text-white leading-tight tracking-tight">
          지금, 첫 고객의<br /><span style={{ color: MINT }}>보장 공백</span>부터 보세요
        </h2>
        <p className="mt-4 text-[16px] text-white/70">증권 한 장이면 시작입니다. 베타 기간 무료.</p>
        <Link href="/register" className="mt-8 inline-flex px-8 py-4 rounded-2xl bg-white text-[var(--brand-ink)] font-bold text-[16px] min-h-[52px] items-center justify-center hover:bg-white/90 transition shadow-lg">무료로 분석 시작하기</Link>
        <p className="mt-4 text-[13px] text-white/45">신용카드 불필요 · 이메일로 가입</p>
      </Reveal>
    </section>
  );
}

function LandingFooter() {
  return (
    <footer className="text-white py-12" style={{ background: "#0a1838" }}>
      <div className="mx-auto max-w-6xl px-4 sm:px-6 md:px-8 lg:px-16">
        <div className="flex flex-col md:flex-row gap-8 md:gap-0 md:justify-between">
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2"><InpaMark size={24} /><span className="font-extrabold text-[17px]">인파 (Inpa)</span></div>
            <p className="text-[13px] text-white/55 max-w-xs leading-relaxed">보험설계사의 AI 영업 파트너. 발굴부터 보장분석, 갈아타기 제안까지.</p>
          </div>
          <div className="flex flex-col gap-2.5 text-[13px]">
            <Link href="/legal/terms" className="text-white/70 hover:text-white transition">이용약관</Link>
            <Link href="/legal/privacy" className="text-white/70 hover:text-white transition">개인정보처리방침</Link>
            <Link href="/data-policy" className="text-white/70 hover:text-white transition">데이터 처리 안내</Link>
          </div>
        </div>
        <div className="mt-10 pt-6 border-t border-white/15 text-[12px] text-white/40 flex flex-col gap-1">
          <p>회사 정보는 법인 설립·정식 출시 시 기재됩니다. (현재 예비창업 베타 단계)</p>
          <p className="mt-2 text-white/55">AI 초안이며 최종 판단·책임은 설계사님에게 있습니다. 인파는 보험 중개·권유를 하지 않습니다.</p>
          <p className="mt-1">© 2026 Inpa. All rights reserved.</p>
        </div>
      </div>
    </footer>
  );
}

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
        <DifferentiatorsSection />
        <HowItWorksSection />
        <PricingSection />
        <TrustSection />
        <FinalCTASection />
      </main>
      <LandingFooter />
    </>
  );
}
