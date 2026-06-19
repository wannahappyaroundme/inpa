"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getProfile, getUnreadCount, tokenStore } from "@/lib/api";

function Logo() {
  return (
    <svg viewBox="0 0 48 48" width="26" height="26" aria-hidden>
      <path d="M6 34 Q24 14 42 34" fill="none" stroke="#12B5A4" strokeWidth="6" strokeLinecap="round" />
      <path d="M12 33 Q24 3 36 33" fill="none" stroke="var(--brand)" strokeWidth="3.4" strokeLinecap="round" />
      <circle cx="24" cy="22" r="2.7" fill="var(--brand)" />
    </svg>
  );
}

export type NavKey =
  | "home"
  | "customers"
  | "analysis"
  | "board"
  | "promotion"
  | "notifications"
  | "admin";

function BellIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M13.7 21a2 2 0 0 1-3.4 0" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function AppNav({ active }: { active?: NavKey }) {
  const [unread, setUnread] = useState(0);
  const [isAdmin, setIsAdmin] = useState(false);
  const [initial, setInitial] = useState("이");

  useEffect(() => {
    if (!tokenStore.get()) return;
    // 미읽음 카운트 (벨 배지) — 실패해도 0 유지
    getUnreadCount()
      .then((r) => setUnread(r.unread_count))
      .catch(() => setUnread(0));
    // 프로필 — 관리자 여부 + 이니셜
    getProfile()
      .then((p) => {
        setIsAdmin(p.is_admin);
        if (p.email) setInitial(p.email[0].toUpperCase());
      })
      .catch(() => { /* 토큰 만료 등 — 무시 */ });
  }, []);

  const items: { key: NavKey; href: string; label: string }[] = [
    { key: "home", href: "/home", label: "대시보드" },
    { key: "customers", href: "/customers", label: "고객" },
    { key: "analysis", href: "/analysis", label: "분석" },
    { key: "board", href: "/board", label: "게시판" },
    { key: "promotion", href: "/promotion", label: "판촉물" },
  ];

  return (
    <header className="sticky top-0 z-30 bg-surface/90 backdrop-blur border-b border-line">
      <div className="mx-auto max-w-5xl px-4 sm:px-6 h-14 flex items-center justify-between">
        <div className="flex items-center gap-4 sm:gap-6 min-w-0">
          <Link href="/home" className="flex items-center gap-2 shrink-0">
            <Logo />
            <span className="font-extrabold text-brand-ink text-[17px]">인파</span>
          </Link>
          <nav className="flex items-center gap-0.5 overflow-x-auto">
            {items.map((it) => (
              <Link
                key={it.key}
                href={it.href}
                className={`px-2.5 sm:px-3 py-1.5 rounded-lg text-[13px] sm:text-[14px] font-semibold transition whitespace-nowrap ${
                  active === it.key ? "text-brand bg-accent-tint" : "text-ink2 hover:bg-surface2"
                }`}
              >
                {it.label}
              </Link>
            ))}
            {isAdmin && (
              <Link
                href="/admin"
                className={`px-2.5 sm:px-3 py-1.5 rounded-lg text-[13px] sm:text-[14px] font-semibold transition whitespace-nowrap ${
                  active === "admin" ? "text-brand bg-accent-tint" : "text-ink2 hover:bg-surface2"
                }`}
              >
                관리자
              </Link>
            )}
          </nav>
        </div>

        <div className="flex items-center gap-2 sm:gap-3 shrink-0">
          {/* 알림 벨 + 미읽음 배지 */}
          <Link
            href="/notifications"
            aria-label={unread > 0 ? `알림 ${unread}건 미읽음` : "알림"}
            className={`relative w-9 h-9 rounded-lg flex items-center justify-center transition ${
              active === "notifications" ? "text-brand bg-accent-tint" : "text-ink2 hover:bg-surface2"
            }`}
          >
            <BellIcon />
            {unread > 0 && (
              <span className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 rounded-full bg-danger text-white text-[10px] font-bold flex items-center justify-center tnum">
                {unread > 99 ? "99+" : unread}
              </span>
            )}
          </Link>

          <Link
            href="/profile"
            aria-label="내 계정"
            className="w-8 h-8 rounded-full bg-brand text-white flex items-center justify-center text-[13px] font-bold"
          >
            {initial}
          </Link>
        </div>
      </div>
    </header>
  );
}
