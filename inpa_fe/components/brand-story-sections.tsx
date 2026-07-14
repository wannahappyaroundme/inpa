"use client";

import Link from "next/link";
import { Check, Users, Phone, BarChart3, CalendarClock, Gift, type LucideIcon } from "lucide-react";
import { Reveal } from "@/components/reveal";
import { InpaMark } from "@/components/inpa-logo";

// new.inpa.kr 스크롤 파트 전용 브랜드 섹션. 시안 landing_page.pdf p1(포스터)·p9~p14.
// 카피 레드라인: em-dash 금지, '준비 중' 금지, 가격은 'N원 (VAT 별도)'만.

// 시안 p1(발표용 포스터, 영화 파트 제외분) — 스크롤 랜딩 맨 위에 배치.
const HERO_ROW: { icon: LucideIcon; label: string; bg: string }[] = [
  { icon: Users, label: "고객 관리", bg: "#2F58DC" },
  { icon: Phone, label: "영업 단계별 관리", bg: "#EC4C6B" },
  { icon: BarChart3, label: "분석 & 리포트", bg: "#D97706" },
  { icon: CalendarClock, label: "일정 & 예약", bg: "#059669" },
  { icon: Gift, label: "판촉물 제작", bg: "#8B5CF6" },
];

// 로고를 중심으로 도는 5개 아이콘(시안의 원형 배치 좌표, 상단부터 시계방향)
const HERO_ORBIT: { icon: LucideIcon; bg: string; top: string; left: string }[] = [
  { icon: Users, bg: "#2F58DC", top: "8%", left: "50%" },
  { icon: BarChart3, bg: "#D97706", top: "37%", left: "90%" },
  { icon: Gift, bg: "#8B5CF6", top: "84%", left: "75%" },
  { icon: CalendarClock, bg: "#059669", top: "84%", left: "25%" },
  { icon: Phone, bg: "#EC4C6B", top: "37%", left: "10%" },
];

export function HeroPosterSection() {
  return (
    <section className="py-20 md:py-28 bg-[var(--surface-2)] overflow-hidden">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 md:px-8">
        <div className="flex flex-col md:flex-row md:items-center gap-12 md:gap-16">
          <Reveal immediate className="flex-1 text-center md:text-left">
            <span className="inline-block text-[13px] font-bold text-[var(--ink-3)]">내 손안의 인슈어 파트너</span>
            <h1 className="mt-3 text-[36px] sm:text-[44px] md:text-[40px] lg:text-[52px] font-extrabold text-[var(--ink)] leading-[1.15] tracking-tight break-keep">
              보험설계사의<br />
              <span className="text-[var(--brand)]">모든 영업</span>을 한곳에
            </h1>
            <div className="mt-9 flex flex-wrap gap-4 sm:gap-6 justify-center md:justify-start">
              {HERO_ROW.map((f) => (
                <div key={f.label} className="flex flex-col items-center gap-2 w-[74px]">
                  <div className="w-14 h-14 rounded-2xl flex items-center justify-center shrink-0" style={{ background: f.bg }}>
                    <f.icon size={26} color="#fff" strokeWidth={2} aria-hidden />
                  </div>
                  <span className="text-[12px] font-semibold text-[var(--ink-2)] text-center leading-tight break-keep">{f.label}</span>
                </div>
              ))}
            </div>
          </Reveal>
          <Reveal immediate delay={120} className="flex-1 flex items-center justify-center w-full">
            <div className="relative w-[280px] h-[280px] sm:w-[340px] sm:h-[340px]" aria-hidden>
              <div className="absolute inset-[8%] rounded-full border-2 border-dashed border-[var(--line-2)]" />
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="w-[46%] h-[46%] rounded-full bg-[var(--accent-tint)]" />
              </div>
              <div className="absolute inset-0 flex items-center justify-center">
                <InpaMark size={96} />
              </div>
              {HERO_ORBIT.map((n, i) => (
                <div key={i} className="absolute w-12 h-12 sm:w-14 sm:h-14 rounded-full flex items-center justify-center shadow-card"
                  style={{ top: n.top, left: n.left, transform: "translate(-50%, -50%)", background: n.bg }}>
                  <n.icon size={20} color="#fff" strokeWidth={2} />
                </div>
              ))}
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}

// 제품 증거 섹션 — 실제 서비스 화면 캡처(2026-07-14 PM 지시: 가짜 목업 대신 진짜 화면 캡처로 교체).
// 데모 계정([DEMO] 표시 데이터)으로 촬영, 개별 고객 목록처럼 이름·연락처가 여러 건 노출되는 화면은 제외.
export function ProductPreviewSection() {
  return (
    <section className="py-20 md:py-28 bg-[var(--surface)] text-center">
      <div className="mx-auto max-w-5xl px-4 sm:px-6">
        <Reveal>
          <h2 className="text-[28px] sm:text-[36px] font-extrabold text-[var(--brand)] tracking-tight break-keep">증권 한 장으로, 보장 공백이 한눈에</h2>
          <p className="mt-3 text-[16px] sm:text-[18px] text-[var(--ink-2)] leading-relaxed break-keep">
            100개 이상 담보를 색으로 정리하고, 오늘 할 일까지 한 화면에서 확인하세요.
          </p>
        </Reveal>
        <div className="mt-10 grid grid-cols-1 md:grid-cols-2 gap-6 text-left">
          <Reveal delay={100}>
            <div className="rounded-2xl bg-[var(--surface)] shadow-card border border-[var(--line)] overflow-hidden">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/landing-new/coverage-analysis.webp" alt="보장 분석 화면: 담보별 넉넉·적정·부족을 색으로 표시" className="w-full h-auto" loading="lazy" />
            </div>
            <p className="mt-2 text-center text-[13px] text-[var(--ink-3)]">보장 분석 · 실제 화면</p>
          </Reveal>
          <Reveal delay={160}>
            <div className="rounded-2xl bg-[var(--surface)] shadow-card border border-[var(--line)] overflow-hidden">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/landing-new/dashboard.webp" alt="대시보드 화면: 이번 달 목표·영업 단계별 고객·월별 보험료 추이" className="w-full h-auto" loading="lazy" />
            </div>
            <p className="mt-2 text-center text-[13px] text-[var(--ink-3)]">대시보드 · 실제 화면</p>
          </Reveal>
        </div>
        <div className="mt-6 grid grid-cols-1 sm:grid-cols-2 gap-6 text-left">
          <Reveal delay={200}>
            <div className="rounded-2xl bg-[var(--surface)] shadow-card border border-[var(--line)] overflow-hidden">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/landing-new/compare-analysis.webp" alt="비교 분석 화면: 현재 보장과 제안 보장의 담보별 증감 비교" className="w-full h-auto" loading="lazy" />
            </div>
            <p className="mt-2 text-center text-[13px] text-[var(--ink-3)]">비교 분석 · 실제 화면</p>
          </Reveal>
          <Reveal delay={240}>
            <div className="rounded-2xl bg-[var(--surface)] shadow-card border border-[var(--line)] overflow-hidden">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/landing-new/schedule-calendar.webp" alt="일정 관리 화면: 상담·할 일이 정리된 캘린더" className="w-full h-auto" loading="lazy" />
            </div>
            <p className="mt-2 text-center text-[13px] text-[var(--ink-3)]">일정 관리 · 실제 화면</p>
          </Reveal>
        </div>
        <Reveal delay={280} className="mt-6 text-left">
          <div className="rounded-2xl bg-[var(--surface)] shadow-card border border-[var(--line)] overflow-hidden">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/landing-new/customer-pipeline.webp" alt="고객 관리 화면: 고객 검색, 단계별·목록 보기 전환, 일괄 등록" className="w-full h-auto" loading="lazy" />
          </div>
          <p className="mt-2 text-center text-[13px] text-[var(--ink-3)]">고객 관리 · 실제 화면</p>
        </Reveal>
        <Reveal delay={320} className="mt-10">
          <Link href="/register" className="inline-flex px-8 py-4 rounded-2xl bg-[var(--brand)] text-white font-bold text-[16px] min-h-[52px] items-center justify-center hover:opacity-90 transition shadow-lg">무료로 시작하기</Link>
          <p className="mt-3 text-[13px] text-[var(--ink-3)]">신용카드 불필요 · 이메일로 가입</p>
        </Reveal>
      </div>
    </section>
  );
}

export function BrandDefinitionSection() {
  return (
    <section className="py-24 md:py-32 bg-[var(--surface)] text-center">
      <Reveal className="mx-auto max-w-3xl px-6">
        <h2 className="text-[34px] sm:text-[48px] font-extrabold text-[var(--brand)] tracking-tight">Insurance Partner, INPA</h2>
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
  { name: "무료", price: "0원",
    features: ["증권 자동 분석 월 5건", "비교 분석 월 1건 체험", "영업 리포트 생성 월 5건", "신규 고객 추가 월 5인"],
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
          <p className="mt-3 text-center text-[15px] sm:text-[17px] text-[var(--ink-3)]">지금은 베타 기간이라 모든 기능을 무료로 이용할 수 있어요</p>
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
