"use client";

import { track } from "@vercel/analytics";
import {
  ArrowRight,
  BarChart3,
  CalendarDays,
  Check,
  ChevronDown,
  LayoutGrid,
  Menu,
  ScanLine,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Target,
  Users,
  X,
} from "lucide-react";
import Image from "next/image";
import { useEffect, useState } from "react";
import { InpaMark } from "@/components/inpa-logo";
import { LandingProductGallery } from "@/components/landing-product-gallery";
import { PricingFourTiers } from "@/components/brand-story-sections";
import {
  AUDIENCES,
  DIFFERENTIATORS,
  FACTS,
  FAQS,
  HERO,
  PRODUCT_SCREENS,
  WORKFLOW_STEPS,
  buildServiceUrl,
} from "@/lib/landing-content";

type CtaPosition = "header" | "hero" | "pricing" | "footer";
type CtaAction = "register" | "login";

const FACT_ICONS = [LayoutGrid, ScanLine, SlidersHorizontal] as const;
const WORKFLOW_ICONS = [Users, ScanLine, BarChart3, CalendarDays] as const;

function landingTrack(name: string, data?: Record<string, string>) {
  try {
    track(name, data);
  } catch {
    // 계측 실패는 화면 이용을 막지 않는다.
  }
}

function CtaLink({
  href,
  position,
  action,
  children,
  className,
}: {
  href: string;
  position: CtaPosition;
  action: CtaAction;
  children: string;
  className: string;
}) {
  return (
    <a
      href={href}
      className={className}
      onClick={() => landingTrack("landing_test_cta", { position, action })}
    >
      {children}
    </a>
  );
}

export function ServiceLanding() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [search, setSearch] = useState("");

  useEffect(() => {
    setSearch(window.location.search);
  }, []);

  const registerUrl = buildServiceUrl("/register", search);
  const loginUrl = buildServiceUrl("/login", search);
  const dashboard = PRODUCT_SCREENS[0];

  return (
    <div id="top" className="theme-light min-h-screen overflow-x-clip bg-[var(--surface)] text-[var(--ink)]">
      <header className="sticky top-0 z-50 h-16 border-b border-[var(--line)] bg-white/95 backdrop-blur">
        <div className="mx-auto flex h-full max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
          <a
            href="#top"
            className="flex min-h-11 items-center gap-2 rounded-xl focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--brand)]"
            aria-label="인파 랜딩 맨 위로"
          >
            <InpaMark size={31} />
            <span className="text-lg font-extrabold tracking-tight text-[var(--brand-ink)]">인파</span>
          </a>

          <nav className="hidden items-center gap-1 md:flex" aria-label="주요 메뉴">
            <a href="#product" className="rounded-xl px-3 py-3 text-sm font-semibold text-[var(--ink-2)] hover:bg-[var(--surface-2)]">실제 화면</a>
            <a href="#workflow" className="rounded-xl px-3 py-3 text-sm font-semibold text-[var(--ink-2)] hover:bg-[var(--surface-2)]">주요 기능</a>
            <a href="#pricing" className="rounded-xl px-3 py-3 text-sm font-semibold text-[var(--ink-2)] hover:bg-[var(--surface-2)]">요금</a>
            <a href="/blog" className="rounded-xl px-3 py-3 text-sm font-semibold text-[var(--ink-2)] hover:bg-[var(--surface-2)]">인파 노트</a>
            <a href="#faq" className="rounded-xl px-3 py-3 text-sm font-semibold text-[var(--ink-2)] hover:bg-[var(--surface-2)]">자주 묻는 질문</a>
          </nav>

          <div className="hidden items-center gap-2 md:flex">
            <CtaLink
              href={loginUrl}
              position="header"
              action="login"
              className="inline-flex min-h-11 items-center justify-center rounded-xl px-4 text-sm font-bold text-[var(--ink-2)] hover:bg-[var(--surface-2)]"
            >
              로그인
            </CtaLink>
            <CtaLink
              href={registerUrl}
              position="header"
              action="register"
              className="inline-flex min-h-11 items-center justify-center rounded-xl bg-[var(--brand)] px-5 text-sm font-bold text-white shadow-sm hover:bg-[var(--brand-ink)]"
            >
              무료로 시작하기
            </CtaLink>
          </div>

          <button
            type="button"
            className="inline-flex size-11 items-center justify-center rounded-xl border border-[var(--line)] text-[var(--ink)] md:hidden"
            aria-label={menuOpen ? "메뉴 닫기" : "메뉴 열기"}
            aria-controls="service-landing-mobile-menu"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((open) => !open)}
          >
            {menuOpen ? <X size={22} aria-hidden /> : <Menu size={22} aria-hidden />}
          </button>
        </div>

        {menuOpen && (
          <div id="service-landing-mobile-menu" className="border-b border-[var(--line)] bg-white px-4 py-4 shadow-lg md:hidden">
            <nav className="mx-auto grid max-w-7xl gap-1" aria-label="모바일 메뉴">
              {[
                ["#product", "실제 화면"],
                ["#workflow", "주요 기능"],
                ["#pricing", "요금"],
                ["/blog", "인파 노트"],
                ["#faq", "자주 묻는 질문"],
              ].map(([href, label]) => (
                <a
                  key={href}
                  href={href}
                  className="flex min-h-11 items-center rounded-xl px-3 text-sm font-bold text-[var(--ink-2)] hover:bg-[var(--surface-2)]"
                  onClick={() => setMenuOpen(false)}
                >
                  {label}
                </a>
              ))}
              <div className="mt-2 grid grid-cols-2 gap-2 border-t border-[var(--line)] pt-4">
                <CtaLink
                  href={loginUrl}
                  position="header"
                  action="login"
                  className="inline-flex min-h-11 items-center justify-center rounded-xl border border-[var(--line)] text-sm font-bold text-[var(--ink-2)]"
                >
                  로그인
                </CtaLink>
                <CtaLink
                  href={registerUrl}
                  position="header"
                  action="register"
                  className="inline-flex min-h-11 items-center justify-center rounded-xl bg-[var(--brand)] text-sm font-bold text-white"
                >
                  무료로 시작하기
                </CtaLink>
              </div>
            </nav>
          </div>
        )}
      </header>

      <main>
      <section className="relative overflow-hidden border-b border-[var(--line)] bg-[linear-gradient(145deg,#f8faff_0%,#eef3ff_54%,#ffffff_100%)]">
        <div className="pointer-events-none absolute -right-36 -top-36 size-96 rounded-full bg-[var(--accent-tint)] blur-3xl" />
        <div className="relative mx-auto grid max-w-7xl items-center gap-12 px-4 py-16 sm:px-6 sm:py-20 lg:grid-cols-[0.86fr_1.14fr] lg:px-8 lg:py-28">
          <div className="text-center lg:text-left">
            <div className="inline-flex items-center gap-2 rounded-full border border-[#cfd9fb] bg-white px-4 py-2 text-sm font-bold text-[var(--brand)] shadow-sm">
              <Sparkles size={16} aria-hidden />
              {HERO.eyebrow}
            </div>
            <h1 className="mt-6 break-keep text-[40px] font-extrabold leading-[1.12] tracking-[-0.04em] text-[var(--brand-ink)] sm:text-[54px] lg:text-[64px]">
              {HERO.title}
            </h1>
            <p className="mx-auto mt-6 max-w-xl break-keep text-base leading-7 text-[var(--ink-2)] sm:text-lg lg:mx-0">
              {HERO.description}
            </p>
            <div className="mt-8 flex flex-col justify-center gap-3 sm:flex-row lg:justify-start">
              <CtaLink
                href={registerUrl}
                position="hero"
                action="register"
                className="inline-flex min-h-13 items-center justify-center gap-2 rounded-2xl bg-[var(--brand)] px-7 py-3.5 text-base font-bold text-white shadow-lg shadow-blue-200 hover:bg-[var(--brand-ink)]"
              >
                무료로 시작하기
              </CtaLink>
              <a
                href="/story"
                className="inline-flex min-h-13 items-center justify-center gap-2 rounded-2xl border border-[var(--line-2)] bg-white px-7 py-3.5 text-base font-bold text-[var(--ink)] hover:border-[var(--brand)] hover:text-[var(--brand)]"
                onClick={() => landingTrack("landing_test_brand_story")}
              >
                인파 이야기 60초 보기
                <ArrowRight size={18} aria-hidden />
              </a>
            </div>
            <p className="mt-4 text-sm text-[var(--ink-3)]">베타 기간에는 핵심 기능을 부담 없이 확인할 수 있어요</p>
          </div>

          <figure className="rounded-[26px] border border-white bg-white p-2 shadow-[0_24px_80px_rgba(30,64,196,0.16)] sm:p-3">
            <div className="flex items-center gap-1.5 border-b border-[var(--line)] px-2 pb-2.5 sm:px-3">
              <span className="size-2.5 rounded-full bg-[var(--cov-none)]" />
              <span className="size-2.5 rounded-full bg-[var(--cov-short)]" />
              <span className="size-2.5 rounded-full bg-[var(--cov-enough)]" />
              <span className="ml-2 text-xs font-bold text-[var(--ink-3)]">실제 인파 화면</span>
            </div>
            <Image
              src={dashboard.image}
              alt={dashboard.imageAlt}
              width={dashboard.width}
              height={dashboard.height}
              priority
              sizes="(max-width: 1024px) 100vw, 58vw"
              className="mt-2 h-auto w-full rounded-2xl border border-[var(--line)]"
            />
            <figcaption className="px-2 pb-1 pt-3 text-center text-xs font-semibold text-[var(--ink-3)]">
              대시보드 실제 화면
            </figcaption>
          </figure>
        </div>
      </section>

      <section className="border-b border-[var(--line)] bg-white" aria-label="인파 핵심 사실">
        <div className="mx-auto grid max-w-7xl divide-y divide-[var(--line)] px-4 sm:px-6 md:grid-cols-3 md:divide-x md:divide-y-0 lg:px-8">
          {FACTS.map((fact, index) => {
            const Icon = FACT_ICONS[index];
            return (
              <article key={fact.title} className="flex gap-4 py-7 md:px-6 md:first:pl-0 md:last:pr-0">
                <span className="flex size-11 shrink-0 items-center justify-center rounded-2xl bg-[var(--accent-tint)] text-[var(--brand)]">
                  <Icon size={21} strokeWidth={1.8} aria-hidden />
                </span>
                <div>
                  <h2 className="break-keep text-[15px] font-extrabold text-[var(--ink)]">{fact.title}</h2>
                  <p className="mt-1 break-keep text-sm leading-6 text-[var(--ink-3)]">{fact.description}</p>
                </div>
              </article>
            );
          })}
        </div>
      </section>

      <section id="product" className="scroll-mt-20 bg-[var(--canvas)] py-20 sm:py-24">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-3xl text-center">
            <p className="text-sm font-extrabold tracking-wide text-[var(--brand)]">실제 서비스 화면</p>
            <h2 className="mt-3 break-keep text-3xl font-extrabold tracking-tight text-[var(--brand-ink)] sm:text-4xl">
              영업의 처음부터 다음 약속까지 한곳에서
            </h2>
            <p className="mt-4 break-keep text-base leading-7 text-[var(--ink-2)]">
              데모 계정의 실제 화면으로 인파에서 이어지는 업무를 확인해보세요.
            </p>
          </div>

          <LandingProductGallery />
        </div>
      </section>

      <section id="workflow" className="scroll-mt-20 bg-white py-20 sm:py-24">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-3xl text-center">
            <p className="text-sm font-extrabold tracking-wide text-[var(--brand)]">사용 흐름</p>
            <h2 className="mt-3 break-keep text-3xl font-extrabold tracking-tight text-[var(--brand-ink)] sm:text-4xl">
              한 번 등록하면 다음 행동이 이어져요
            </h2>
          </div>

          <ol className="relative mt-12 grid gap-4 md:grid-cols-4">
            {WORKFLOW_STEPS.map((step, index) => {
              const Icon = WORKFLOW_ICONS[index];
              return (
                <li key={step.title} className="relative rounded-3xl border border-[var(--line)] bg-white p-6 shadow-card">
                  <div className="flex items-center justify-between">
                    <span className="flex size-12 items-center justify-center rounded-2xl bg-[var(--accent-tint)] text-[var(--brand)]">
                      <Icon size={22} strokeWidth={1.8} aria-hidden />
                    </span>
                    <span className="text-sm font-extrabold text-[var(--muted)]">0{index + 1}</span>
                  </div>
                  <h3 className="mt-5 break-keep text-lg font-extrabold text-[var(--ink)]">{step.title}</h3>
                  <p className="mt-2 break-keep text-sm leading-6 text-[var(--ink-3)]">{step.description}</p>
                  {index < WORKFLOW_STEPS.length - 1 && (
                    <ArrowRight className="absolute -bottom-4 left-1/2 z-10 -translate-x-1/2 rotate-90 rounded-full bg-white p-1 text-[var(--brand)] md:-right-3 md:bottom-auto md:left-auto md:top-1/2 md:translate-x-0 md:-translate-y-1/2 md:rotate-0" size={28} aria-hidden />
                  )}
                </li>
              );
            })}
          </ol>
        </div>
      </section>

      <section className="bg-[var(--canvas)] py-20 sm:py-24">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="grid gap-6 lg:grid-cols-2">
            {DIFFERENTIATORS.map((item, index) => (
              <article key={item.title} className="rounded-3xl border border-[var(--line)] bg-white p-7 shadow-card sm:p-9">
                <span className={`flex size-12 items-center justify-center rounded-2xl ${index === 0 ? "bg-[var(--accent-tint)] text-[var(--brand)]" : "bg-[var(--success-tint)] text-[var(--success-ink)]"}`}>
                  {index === 0 ? <Target size={23} aria-hidden /> : <ShieldCheck size={23} aria-hidden />}
                </span>
                <p className="mt-6 text-sm font-extrabold text-[var(--brand)]">인파가 다른 점 {index + 1}</p>
                <h2 className="mt-2 break-keep text-2xl font-extrabold text-[var(--ink)]">{item.title}</h2>
                <p className="mt-3 break-keep text-base leading-7 text-[var(--ink-2)]">{item.description}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="audience" className="scroll-mt-20 bg-white py-20 sm:py-24">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-3xl text-center">
            <p className="text-sm font-extrabold tracking-wide text-[var(--brand)]">이런 분께 딱 맞아요</p>
            <h2 className="mt-3 break-keep text-3xl font-extrabold tracking-tight text-[var(--brand-ink)] sm:text-4xl">
              일하는 방식에 맞춰 필요한 화면부터
            </h2>
          </div>
          <div className="mt-12 grid gap-6 md:grid-cols-2">
            {AUDIENCES.map((audience, index) => (
              <article key={audience.label} className="rounded-3xl border border-[var(--line)] bg-[var(--surface-2)] p-7 sm:p-9">
                <div className="flex items-center gap-3">
                  <span className="flex size-12 items-center justify-center rounded-2xl bg-white text-[var(--brand)] shadow-sm">
                    {index === 0 ? <Users size={23} aria-hidden /> : <BarChart3 size={23} aria-hidden />}
                  </span>
                  <span className="font-extrabold text-[var(--brand)]">{audience.label}</span>
                </div>
                <h3 className="mt-6 break-keep text-2xl font-extrabold text-[var(--ink)]">{audience.title}</h3>
                <p className="mt-3 break-keep text-base leading-7 text-[var(--ink-2)]">{audience.description}</p>
                <ul className="mt-6 space-y-3">
                  {audience.highlights.map((highlight) => (
                    <li key={highlight} className="flex items-center gap-2 text-sm font-bold text-[var(--ink-2)]">
                      <Check size={17} className="text-[var(--success-ink)]" strokeWidth={2.5} aria-hidden />
                      {highlight}
                    </li>
                  ))}
                </ul>
              </article>
            ))}
          </div>
        </div>
      </section>

      <div
        onClickCapture={(event) => {
          const link = (event.target as HTMLElement).closest?.("a");
          if (!link?.getAttribute("href")?.includes("/register")) return;
          landingTrack("landing_test_cta", { position: "pricing", action: "register" });
        }}
      >
        <PricingFourTiers id="pricing" registerHref={registerUrl} />
      </div>

      <section id="faq" className="scroll-mt-20 bg-[var(--canvas)] py-20 sm:py-24">
        <div className="mx-auto max-w-4xl px-4 sm:px-6 lg:px-8">
          <div className="text-center">
            <p className="text-sm font-extrabold tracking-wide text-[var(--brand)]">자주 묻는 질문</p>
            <h2 className="mt-3 break-keep text-3xl font-extrabold tracking-tight text-[var(--brand-ink)] sm:text-4xl">
              시작 전에 궁금한 점을 확인하세요
            </h2>
          </div>
          <div className="mt-10 space-y-3">
            {FAQS.map((faq) => (
              <details key={faq.question} className="group rounded-2xl border border-[var(--line)] bg-white px-5 py-1 shadow-sm sm:px-6">
                <summary className="flex min-h-16 cursor-pointer list-none items-center justify-between gap-4 py-4 font-extrabold text-[var(--ink)] focus-visible:outline-2 focus-visible:outline-[var(--brand)]">
                  <span className="break-keep">{faq.question}</span>
                  <ChevronDown className="shrink-0 text-[var(--brand)] transition-transform group-open:rotate-180" size={20} aria-hidden />
                </summary>
                <p className="break-keep border-t border-[var(--line)] py-5 text-sm leading-6 text-[var(--ink-2)]">{faq.answer}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      <section className="bg-white py-20 sm:py-24" aria-labelledby="role-title">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-3xl text-center">
            <p className="text-sm font-extrabold tracking-wide text-[var(--brand)]">역할 안내</p>
            <h2 id="role-title" className="mt-3 break-keep text-3xl font-extrabold tracking-tight text-[var(--brand-ink)] sm:text-4xl">
              인파가 정리하고, 설계사님이 완성해요
            </h2>
          </div>
          <div className="mt-12 grid gap-6 md:grid-cols-2">
            <article className="rounded-3xl border border-[var(--line)] bg-[var(--accent-tint)] p-7 sm:p-9">
              <span className="text-sm font-extrabold text-[var(--brand)]">인파가 맡는 일</span>
              <h3 className="mt-3 break-keep text-xl font-extrabold text-[var(--ink)]">등록된 정보를 같은 틀로 정리</h3>
              <p className="mt-3 break-keep text-sm leading-6 text-[var(--ink-2)]">증권의 보험과 담보, 두 구성의 차이, 고객 단계와 일정을 보기 쉽게 연결합니다.</p>
            </article>
            <article className="rounded-3xl border border-[var(--line)] bg-[var(--success-tint)] p-7 sm:p-9">
              <span className="text-sm font-extrabold text-[var(--success-ink)]">설계사님이 완성하는 일</span>
              <h3 className="mt-3 break-keep text-xl font-extrabold text-[var(--ink)]">보장 판단과 고객 안내</h3>
              <p className="mt-3 break-keep text-sm leading-6 text-[var(--ink-2)]">정리된 내용을 직접 확인하고, 고객 상황에 맞는 판단과 안내를 완성합니다.</p>
            </article>
          </div>
        </div>
      </section>

      <section className="bg-white py-20 text-center sm:py-24">
        <div className="mx-auto max-w-3xl px-4 sm:px-6">
          <InpaMark size={48} live className="mx-auto" />
          <h2 className="mt-6 break-keep text-3xl font-extrabold tracking-tight text-[var(--brand-ink)] sm:text-4xl">
            첫 고객부터 한 흐름으로 관리해보세요
          </h2>
          <p className="mt-4 break-keep text-base leading-7 text-[var(--ink-2)]">
            고객 관리, 증권 정리, 보장 확인, 비교, 일정을 인파에서 이어갈 수 있습니다.
          </p>
          <div className="mt-8 flex flex-col justify-center gap-3 sm:flex-row">
            <CtaLink
              href={registerUrl}
              position="footer"
              action="register"
              className="inline-flex min-h-13 items-center justify-center rounded-2xl bg-[var(--brand)] px-8 py-3.5 text-base font-extrabold text-white shadow-lg shadow-blue-100 hover:bg-[var(--brand-ink)]"
            >
              무료로 시작하기
            </CtaLink>
            <CtaLink
              href={loginUrl}
              position="footer"
              action="login"
              className="inline-flex min-h-13 items-center justify-center rounded-2xl border border-[var(--line-2)] bg-white px-8 py-3.5 text-base font-extrabold text-[var(--ink)] hover:border-[var(--brand)] hover:text-[var(--brand)]"
            >
              로그인
            </CtaLink>
          </div>
        </div>
      </section>
      </main>

      <footer className="bg-[#0a1838] py-12 text-white">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="flex flex-col gap-8 md:flex-row md:items-start md:justify-between">
            <div>
              <div className="flex items-center gap-2">
                <InpaMark size={26} pColor="#FFFFFF" />
                <span className="text-lg font-extrabold">인파 (Inpa)</span>
              </div>
              <p className="mt-3 max-w-sm break-keep text-sm leading-6 text-white/60">내 손안의 인슈어 파트너, 고객 관리부터 다음 일정까지 한곳에서 이어갑니다.</p>
            </div>
            <nav className="grid grid-cols-2 gap-x-8 gap-y-3 text-sm" aria-label="정책 메뉴">
              <a href="/blog" className="text-white/70 hover:text-white">인파 노트</a>
              <a href="/faq" className="text-white/70 hover:text-white">자주 묻는 질문</a>
              <a href="/legal/terms" className="text-white/70 hover:text-white">이용약관</a>
              <a href="/legal/privacy" className="text-white/70 hover:text-white">개인정보처리방침</a>
              <a href="/data-policy" className="text-white/70 hover:text-white">데이터 처리 안내</a>
              <a href="mailto:hello.fingo.official@gmail.com" className="text-white/70 hover:text-white">문의</a>
            </nav>
          </div>
          <div className="mt-10 border-t border-white/15 pt-6 text-center text-xs leading-5 text-white/45">
            <p>(주)서울엘엔에스금융컨설팅 · 대표 황희철 · 사업자등록번호 109-86-17632 · 통신판매업신고 2021-서울구로-1990</p>
            <p>서울특별시 금천구 서부샛길 606, A동 24층 2409호 · hello.fingo.official@gmail.com</p>
            <p className="mt-2">© 2026 Inpa. All rights reserved.</p>
          </div>
        </div>
      </footer>
    </div>
  );
}
