import Link from "next/link";

function Logo() {
  return (
    <svg viewBox="0 0 48 48" width="26" height="26" aria-hidden>
      <path d="M6 34 Q24 14 42 34" fill="none" stroke="#12B5A4" strokeWidth="6" strokeLinecap="round" />
      <path d="M12 33 Q24 3 36 33" fill="none" stroke="var(--brand)" strokeWidth="3.4" strokeLinecap="round" />
      <circle cx="24" cy="22" r="2.7" fill="var(--brand)" />
    </svg>
  );
}

export function AppNav({ active }: { active?: "home" | "customers" | "analysis" }) {
  const items = [
    { key: "home", href: "/home", label: "대시보드" },
    { key: "customers", href: "/customers", label: "고객" },
    { key: "analysis", href: "/analysis", label: "분석" },
  ];
  return (
    <header className="sticky top-0 z-30 bg-surface/90 backdrop-blur border-b border-line">
      <div className="mx-auto max-w-5xl px-4 sm:px-6 h-14 flex items-center justify-between">
        <div className="flex items-center gap-4 sm:gap-6">
          <Link href="/home" className="flex items-center gap-2">
            <Logo />
            <span className="font-extrabold text-brand-ink text-[17px]">인파</span>
          </Link>
          <nav className="flex items-center gap-0.5">
            {items.map((it) => (
              <Link
                key={it.key}
                href={it.href}
                className={`px-2.5 sm:px-3 py-1.5 rounded-lg text-[13px] sm:text-[14px] font-semibold transition ${
                  active === it.key ? "text-brand bg-accent-tint" : "text-ink2 hover:bg-surface2"
                }`}
              >
                {it.label}
              </Link>
            ))}
          </nav>
        </div>
        <div className="w-8 h-8 rounded-full bg-brand text-white flex items-center justify-center text-[13px] font-bold">이</div>
      </div>
    </header>
  );
}
