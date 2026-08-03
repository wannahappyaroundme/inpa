import Link from "next/link";
import type { ReactNode } from "react";

import { InpaMark } from "@/components/inpa-logo";

const NAV_ITEMS = [
  { href: "/#solutions", label: "솔루션" },
  { href: "/#guides", label: "실무 가이드" },
  { href: "/#tools", label: "무료 도구" },
  { href: "/blog", label: "블로그" },
  { href: "/faq", label: "자주 묻는 질문" },
] as const;

export function PublicSiteShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-canvas text-ink">
      <header className="sticky top-0 z-30 border-b border-line/80 bg-surface/95 backdrop-blur">
        <div className="mx-auto flex min-h-[68px] max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
          <Link
            href="/"
            aria-label="인파 홈"
            className="flex shrink-0 items-center gap-2 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
          >
            <InpaMark size={30} />
            <span className="text-[16px] font-extrabold tracking-tight text-brand-ink">인파</span>
          </Link>

          <nav aria-label="공개 메뉴" className="hidden items-center gap-1 md:flex">
            {NAV_ITEMS.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="rounded-lg px-3 py-2 text-[13px] font-semibold text-ink2 transition hover:bg-canvas hover:text-brand-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
              >
                {item.label}
              </Link>
            ))}
          </nav>

          <Link
            href="/register"
            className="inline-flex min-h-[44px] shrink-0 items-center justify-center rounded-xl bg-brand px-4 py-2 text-[13px] font-bold text-white transition hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
          >
            무료로 시작하기
          </Link>
        </div>

        <nav
          aria-label="모바일 공개 메뉴"
          className="flex gap-1 overflow-x-auto border-t border-line/70 px-4 py-2 md:hidden"
        >
          {NAV_ITEMS.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="shrink-0 rounded-lg px-3 py-2 text-[12px] font-semibold text-ink2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
            >
              {item.label}
            </Link>
          ))}
        </nav>
      </header>

      {children}

      <footer className="border-t border-line bg-surface">
        <div className="mx-auto flex max-w-6xl flex-col gap-5 px-4 py-10 sm:px-6 md:flex-row md:items-end md:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <InpaMark size={24} />
              <span className="text-[14px] font-extrabold text-brand-ink">인파(Inpa)</span>
            </div>
            <p className="mt-3 max-w-xl text-[12px] leading-6 text-ink3">
              보험설계사의 고객 발굴, 증권 정리, 여러 증권 비교, 일정과 고객 관리를 한 흐름으로 잇는 웹 서비스입니다.
            </p>
          </div>
          <nav aria-label="하단 메뉴" className="flex flex-wrap gap-x-4 gap-y-2 text-[12px] text-ink3">
            <Link href="/data-policy" className="hover:text-brand-ink">데이터 처리 안내</Link>
            <Link href="/legal/terms" className="hover:text-brand-ink">이용약관</Link>
            <Link href="/legal/privacy" className="hover:text-brand-ink">개인정보처리방침</Link>
            <a href="mailto:hello.fingo.official@gmail.com" className="hover:text-brand-ink">문의</a>
          </nav>
        </div>
      </footer>
    </div>
  );
}
