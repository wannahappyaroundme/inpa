"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  LayoutDashboard, Users, Calendar, BarChart3, MessageSquareText,
  SlidersHorizontal, ClipboardList, Gift, LineChart, Shield, Bell,
  ChevronRight, type LucideIcon,
} from "lucide-react";
import { getProfile, getUnreadCount, tokenStore } from "@/lib/api";
import { BottomNav } from "./bottom-nav";

function Logo({ size = 26 }: { size?: number }) {
  return (
    <svg viewBox="0 0 48 48" width={size} height={size} aria-hidden>
      <path d="M16.5 41 V15.5 H25 A7 7 0 0 1 25 29.5 H16.5" fill="none" stroke="#1E40C4" strokeWidth="7.6" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="16.5" cy="5.05" r="3.9" fill="#DC2626" />
    </svg>
  );
}

export type NavKey =
  | "home"
  | "customers"
  | "analysis"
  | "schedule"
  | "scripts"
  | "board"
  | "promotion"
  | "settings"
  | "manager"
  | "notifications"
  | "admin";

type Item = { key: NavKey; href: string; label: string; icon: LucideIcon };

/** 사이드바 한 줄(데스크탑). 액티브 = 연한 파랑 pill + 파란 글씨. 알림은 우측 미읽음 배지. */
function SideItem({
  item,
  active,
  badge = 0,
}: {
  item: Item;
  active: boolean;
  badge?: number;
}) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={`relative flex items-center gap-3 px-3 py-2.5 rounded-xl text-[14px] font-semibold transition ${
        active ? "bg-brand-soft text-brand" : "text-ink2 hover:bg-surface2 hover:text-ink"
      }`}
    >
      <Icon className="w-[18px] h-[18px] shrink-0" strokeWidth={2} />
      <span className="flex-1 truncate">{item.label}</span>
      {badge > 0 && (
        <span className="min-w-[18px] h-[18px] px-1 rounded-full bg-danger text-white text-[10px] font-bold flex items-center justify-center tnum">
          {badge > 99 ? "99+" : badge}
        </span>
      )}
    </Link>
  );
}

export function AppNav({ active }: { active?: NavKey }) {
  const [unread, setUnread] = useState(0);
  const [custUnread, setCustUnread] = useState(0);     // 고객 관련 미읽음(네비 배지)
  const [schedUnread, setSchedUnread] = useState(0);   // 일정 관련 미읽음(네비 배지)
  const [isAdmin, setIsAdmin] = useState(false);
  const [isManager, setIsManager] = useState(false);
  const [initial, setInitial] = useState("이");
  const [name, setName] = useState("");
  const [sub, setSub] = useState("");

  useEffect(() => {
    if (!tokenStore.get()) return;
    const poll = () =>
      getUnreadCount()
        .then((r) => { setUnread(r.unread_count); setCustUnread(r.customers); setSchedUnread(r.schedule); })
        .catch(() => { /* 무시 */ });
    poll();
    const timer = setInterval(poll, 60000);
    getProfile()
      .then((p) => {
        setIsAdmin(p.is_admin);
        setIsManager((p.managed_agents_count ?? 0) > 0);
        if (p.email) setInitial(p.email[0].toUpperCase());
        setName(p.name?.trim() || (p.email ? p.email.split("@")[0] : "설계사"));
        setSub(p.affiliation?.trim() || p.title?.trim() || p.email || "");
      })
      .catch(() => { /* 토큰 만료 등 — 무시 */ });
    return () => clearInterval(timer);
  }, []);

  const items: Item[] = [
    { key: "home", href: "/home", label: "대시보드", icon: LayoutDashboard },
    { key: "customers", href: "/customers", label: "고객", icon: Users },
    { key: "schedule", href: "/schedule", label: "일정", icon: Calendar },
    { key: "analysis", href: "/analysis", label: "분석", icon: BarChart3 },
    { key: "scripts", href: "/scripts", label: "화법", icon: MessageSquareText },
    { key: "settings", href: "/settings/baseline", label: "기준", icon: SlidersHorizontal },
    { key: "board", href: "/boards", label: "게시판", icon: ClipboardList },
    { key: "promotion", href: "/promotion", label: "판촉물", icon: Gift },
  ];
  const managerItem: Item = { key: "manager", href: "/manager", label: "관리직 KPI", icon: LineChart };
  const adminItem: Item = { key: "admin", href: "/admin", label: "관리자", icon: Shield };
  const notiItem: Item = { key: "notifications", href: "/notifications", label: "알림", icon: Bell };

  return (
    <>
      {/* 데스크탑 좌측 사이드바 (sm+). 모바일에선 숨고 하단 탭바(BottomNav)를 쓴다. */}
      <aside className="app-sidebar hidden sm:flex flex-col fixed left-0 top-0 h-dvh w-60 bg-surface border-r border-line z-30">
        <Link href="/home" className="flex items-center gap-2 px-5 h-16 shrink-0">
          <Logo />
          <span className="font-extrabold text-brand-ink text-[18px]">인파</span>
        </Link>
        <nav className="flex-1 overflow-y-auto scrollbar-none px-3 py-2 space-y-0.5">
          {items.map((it) => (
            <SideItem
              key={it.key}
              item={it}
              active={active === it.key}
              badge={it.key === "customers" ? custUnread : it.key === "schedule" ? schedUnread : 0}
            />
          ))}
          {isManager && <SideItem item={managerItem} active={active === "manager"} />}
          {isAdmin && <SideItem item={adminItem} active={active === "admin"} />}
          <SideItem item={notiItem} active={active === "notifications"} badge={unread} />
        </nav>
        <Link
          href="/settings/account"
          className="m-3 mt-auto flex items-center gap-2.5 rounded-xl border border-line p-2.5 hover:bg-surface2 transition"
        >
          <span className="w-9 h-9 rounded-full bg-brand text-white flex items-center justify-center text-[14px] font-bold shrink-0">
            {initial}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-[13px] font-bold text-ink truncate">{name || "설계사"}</span>
            <span className="block text-[11px] text-ink3 truncate">{sub}</span>
          </span>
          <ChevronRight className="w-4 h-4 text-muted shrink-0" />
        </Link>
      </aside>

      {/* 모바일 상단바 (sm 미만, sticky) — 로고 + 알림 벨 + 아바타 */}
      <header className="app-topbar sm:hidden sticky top-0 z-30 h-14 bg-surface/90 backdrop-blur border-b border-line flex items-center justify-between px-4">
        <Link href="/home" className="flex items-center gap-1.5">
          <Logo size={22} />
          <span className="font-extrabold text-brand-ink text-[16px]">인파</span>
        </Link>
        <div className="flex items-center gap-2">
          <Link
            href="/notifications"
            aria-label={unread > 0 ? `알림 ${unread}건 미읽음` : "알림"}
            className={`relative w-9 h-9 rounded-lg flex items-center justify-center transition ${
              active === "notifications" ? "text-brand bg-brand-soft" : "text-ink2 hover:bg-surface2"
            }`}
          >
            <Bell className="w-5 h-5" strokeWidth={2} />
            {unread > 0 && (
              <span className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 rounded-full bg-danger text-white text-[10px] font-bold flex items-center justify-center tnum">
                {unread > 99 ? "99+" : unread}
              </span>
            )}
          </Link>
          <Link
            href="/settings/account"
            aria-label="내 계정"
            className="w-8 h-8 rounded-full bg-brand text-white flex items-center justify-center text-[13px] font-bold"
          >
            {initial}
          </Link>
        </div>
      </header>

      <BottomNav active={active} isAdmin={isAdmin} isManager={isManager} custUnread={custUnread} schedUnread={schedUnread} />
    </>
  );
}
