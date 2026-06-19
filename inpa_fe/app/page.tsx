import Link from "next/link";

function Logo() {
  return (
    <svg viewBox="0 0 48 48" width="40" height="40" aria-label="인파" role="img">
      <path d="M6 34 Q24 14 42 34" fill="none" stroke="#12B5A4" strokeWidth="6" strokeLinecap="round" />
      <path d="M12 33 Q24 3 36 33" fill="none" stroke="var(--brand)" strokeWidth="3.4" strokeLinecap="round" />
      <circle cx="24" cy="22" r="2.7" fill="var(--brand)" />
    </svg>
  );
}

const links = [
  { href: "/home", tag: "설계사 · 첫 화면", title: "대시보드", desc: "KPI 카드 + 캘린더로 일정·업무 한눈에", accent: true },
  { href: "/customers", tag: "설계사", title: "고객 관리", desc: "고객 목록·검색·등록 (CRM)" },
  { href: "/analysis", tag: "설계사 도구", title: "담보 한눈표 (히트맵)", desc: "설계사 기준 대비 충족 · 신호등 4색" },
  { href: "/s/demo", tag: "고객이 보는 화면", title: "고객 공유뷰", desc: "납입 현황 진단 한 장 (카톡 공유)" },
];

export default function Home() {
  return (
    <main className="mx-auto w-full max-w-md min-h-dvh px-5 py-12 flex flex-col gap-8">
      <div className="flex items-center gap-3">
        <Logo />
        <div>
          <div className="text-xl font-extrabold text-brand-ink tracking-tight">
            인파 <span className="text-ink3 font-medium">Inpa</span>
          </div>
          <div className="text-[13px] text-ink3">보험설계사의 업무 OS · AI 영업 파트너</div>
        </div>
      </div>

      <div className="flex flex-col gap-3">
        {links.map((l) => (
          <Link key={l.href} href={l.href} className="block rounded-2xl bg-surface border border-line p-5 shadow-sm active:scale-[0.99] transition">
            <div className={`text-[13px] font-semibold ${l.accent ? "text-accent" : "text-brand"}`}>{l.tag}</div>
            <div className="mt-1 text-[17px] font-bold text-ink">{l.title}</div>
            <div className="mt-1 text-[13px] text-ink3">{l.desc} →</div>
          </Link>
        ))}
      </div>

      <div className="mt-auto text-[12px] text-muted">
        Next.js 16 · Tailwind v4 · 다크/라이트 자동 · 표지판 파랑 #0B57D0 + 신호등 4색
      </div>
    </main>
  );
}
