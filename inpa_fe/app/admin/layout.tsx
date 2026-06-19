"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { href: "/admin",              label: "대시보드",       icon: "📊" },
  { href: "/admin/users",        label: "설계사 관리",     icon: "👤" },
  { href: "/admin/board",        label: "게시판 모더레이션", icon: "📋" },
  { href: "/admin/announcements",label: "공지사항",        icon: "📢" },
  { href: "/admin/faq",          label: "FAQ",            icon: "❓" },
  { href: "/admin/inquiries",    label: "1:1 문의",        icon: "💬" },
  { href: "/admin/orders",       label: "판촉물 주문",     icon: "📦" },
  { href: "/admin/consent-logs", label: "동의 로그",       icon: "🔑" },
  { href: "/admin/normalization",label: "정규화 매핑",     icon: "🗂️" },
  { href: "/admin/settings",     label: "설정",           icon: "⚙️" },
];

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="min-h-dvh flex">
      {/* 사이드바 */}
      <aside className="w-56 shrink-0 bg-surface border-r border-line flex flex-col hidden lg:flex">
        <div className="h-14 flex items-center px-5 border-b border-line">
          <span className="text-[15px] font-extrabold text-brand-ink">인파 Admin</span>
        </div>
        <nav className="flex-1 py-3 px-2 space-y-0.5 overflow-y-auto">
          {NAV.map((it) => {
            // 대시보드는 정확히 /admin 만 매칭
            const isActive =
              it.href === "/admin"
                ? pathname === "/admin"
                : pathname.startsWith(it.href);
            return (
              <Link
                key={it.href}
                href={it.href}
                className={`flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-[13px] font-semibold transition ${
                  isActive
                    ? "bg-accent-tint text-brand"
                    : "text-ink2 hover:bg-surface2"
                }`}
              >
                <span className="text-[16px] w-5 text-center">{it.icon}</span>
                {it.label}
              </Link>
            );
          })}
        </nav>
        <div className="p-3 border-t border-line">
          <Link
            href="/home"
            className="flex items-center gap-2 px-3 py-2 rounded-xl text-[12px] text-ink3 hover:bg-surface2 transition"
          >
            ← 설계사 화면으로
          </Link>
        </div>
      </aside>

      {/* 메인 */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* 모바일 상단 바 */}
        <header className="lg:hidden h-14 flex items-center px-4 border-b border-line bg-surface">
          <span className="text-[15px] font-extrabold text-brand-ink flex-1">인파 Admin</span>
          <select
            className="text-[13px] border border-line rounded-lg px-2 py-1.5 bg-surface text-ink"
            onChange={(e) => { window.location.href = e.target.value; }}
            value={NAV.find((n) =>
              n.href === "/admin" ? pathname === "/admin" : pathname.startsWith(n.href)
            )?.href ?? "/admin"}
          >
            {NAV.map((it) => (
              <option key={it.href} value={it.href}>
                {it.icon} {it.label}
              </option>
            ))}
          </select>
        </header>
        <main className="flex-1 overflow-y-auto">
          {children}
        </main>
      </div>
    </div>
  );
}
