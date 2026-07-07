import Link from "next/link";
import type { ReactNode } from "react";

// 조항 블록
export function Article({ n, title, children }: { n?: number; title: string; children: ReactNode }) {
  return (
    <section>
      <h2 className="text-[16px] font-bold text-[var(--ink)] mb-1.5">
        {n ? `제${n}조 ` : ""}{title}
      </h2>
      <div className="space-y-2">{children}</div>
    </section>
  );
}

// 공용 법무 페이지 셸 (공개·비로그인). 헤더/면책 고지/푸터 + prose 스타일.
export function LegalPage({
  title,
  effective,
  children,
}: {
  title: string;
  effective: string;
  children: ReactNode;
}) {
  return (
    <div className="min-h-dvh bg-[var(--surface-2)]">
      <header className="sticky top-0 z-10 border-b border-[var(--line)] bg-[var(--surface)]/95 backdrop-blur">
        <div className="mx-auto max-w-3xl px-5 h-14 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2">
            <svg viewBox="0 0 48 48" width="24" height="24" aria-hidden>
              <path d="M16.5 41 V15.5 H25 A7 7 0 0 1 25 29.5 H16.5" fill="none" stroke="#1E40C4" strokeWidth="7.6" strokeLinecap="round" strokeLinejoin="round" />
              <circle cx="16.5" cy="5.05" r="3.9" fill="#DC2626" />
            </svg>
            <span className="font-extrabold text-[var(--brand-ink)] text-[16px]">인파</span>
          </Link>
          <Link href="/" className="text-[13px] text-[var(--ink-3)] hover:text-[var(--brand)]">← 홈으로</Link>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-5 py-8">
        <h1 className="text-[26px] font-extrabold text-[var(--ink)]">{title}</h1>
        <p className="mt-1 text-[13px] text-[var(--ink-3)]">{effective}</p>

        <div className="mt-4 rounded-xl border border-[var(--line)] bg-[var(--surface)] px-4 py-3 text-[13px] text-[var(--ink-3)] leading-6">
          인파는 보험을 중개·권유하지 않는 분석·정리 소프트웨어입니다. 보장 판단과 고객 안내는
          설계사님의 업무이며, 산출물은 AI가 정리한 참고 자료입니다.
        </div>

        <article className="mt-6 space-y-6 text-[14px] leading-7 text-[var(--ink-2)]">
          {children}
        </article>

        <footer className="mt-12 pt-6 border-t border-[var(--line)] text-[12px] text-[var(--ink-3)]">
          <Link href="/legal/terms" className="hover:text-[var(--brand)]">이용약관</Link>
          {" · "}
          <Link href="/legal/privacy" className="hover:text-[var(--brand)]">개인정보처리방침</Link>
        </footer>
      </main>
    </div>
  );
}

// 표 헬퍼
export function LegalTable({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[13px] border-collapse">
        <thead>
          <tr className="bg-[var(--surface-2)]">
            {head.map((h, i) => (
              <th key={i} className="border border-[var(--line)] px-2.5 py-2 text-left font-semibold text-[var(--ink)]">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {r.map((c, j) => (
                <td key={j} className="border border-[var(--line)] px-2.5 py-2 align-top text-[var(--ink-2)]">{c}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
