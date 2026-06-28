"use client";

// 모바일 하단 탭바(벤치마킹 001). 데스크탑(sm+)에선 숨고 상단 AppNav 헤더를 쓴다.
// AppNav 내부에서 렌더 → 인증 페이지(헤더 있는 곳)에만 자동 노출(랜딩/로그인/공개링크 제외).
// 본문 가림 방지: globals.css 의 `body:has(.app-bottom-nav) main { padding-bottom }` 가 처리.
import Link from "next/link";
import { useState } from "react";
import type { NavKey } from "./app-nav";

function Icon({ name }: { name: "home" | "customers" | "schedule" | "analysis" | "more" }) {
  const common = {
    width: 22,
    height: 22,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };
  switch (name) {
    case "home":
      return (
        <svg {...common}>
          <path d="M3 11l9-8 9 8" />
          <path d="M5 10v10h14V10" />
        </svg>
      );
    case "customers":
      return (
        <svg {...common}>
          <circle cx="12" cy="8" r="4" />
          <path d="M4 21c0-4 4-6 8-6s8 2 8 6" />
        </svg>
      );
    case "schedule":
      return (
        <svg {...common}>
          <rect x="3" y="4" width="18" height="17" rx="2" />
          <path d="M3 9h18M8 2v4M16 2v4" />
        </svg>
      );
    case "analysis":
      return (
        <svg {...common}>
          <path d="M5 21V10M12 21V4M19 21v-7" />
        </svg>
      );
    case "more":
      return (
        <svg {...common}>
          <circle cx="5" cy="12" r="1.4" />
          <circle cx="12" cy="12" r="1.4" />
          <circle cx="19" cy="12" r="1.4" />
        </svg>
      );
  }
}

const TABS: { key: NavKey; href: string; label: string; icon: "home" | "customers" | "schedule" | "analysis" }[] = [
  { key: "home", href: "/home", label: "홈", icon: "home" },
  { key: "customers", href: "/customers", label: "고객", icon: "customers" },
  { key: "schedule", href: "/schedule", label: "일정", icon: "schedule" },
  { key: "analysis", href: "/analysis", label: "분석", icon: "analysis" },
];

const PRIMARY_KEYS: NavKey[] = ["home", "customers", "schedule", "analysis"];

export function BottomNav({
  active,
  isAdmin,
  isManager,
}: {
  active?: NavKey;
  isAdmin: boolean;
  isManager: boolean;
}) {
  const [moreOpen, setMoreOpen] = useState(false);
  const moreActive = !!active && !PRIMARY_KEYS.includes(active);

  const moreLinks: { href: string; label: string }[] = [
    { href: "/scripts", label: "화법" },
    { href: "/settings/baseline", label: "기준" },
    { href: "/boards", label: "게시판" },
    { href: "/promotion", label: "판촉물" },
    { href: "/notifications", label: "알림" },
    ...(isManager ? [{ href: "/manager", label: "관리직 KPI" }] : []),
    ...(isAdmin ? [{ href: "/admin", label: "관리자" }] : []),
    { href: "/settings/account", label: "내 계정" },
  ];

  const tabCls = (on: boolean) =>
    `flex flex-col items-center justify-center gap-0.5 py-2 text-[10px] font-semibold transition ${
      on ? "text-brand" : "text-ink3"
    }`;

  return (
    <>
      <nav
        className="app-bottom-nav sm:hidden fixed bottom-0 inset-x-0 z-40 bg-surface/95 backdrop-blur border-t border-line"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
        aria-label="하단 탭"
      >
        <div className="grid grid-cols-5">
          {TABS.map((t) => (
            <Link key={t.key} href={t.href} className={tabCls(active === t.key)}>
              <Icon name={t.icon} />
              {t.label}
            </Link>
          ))}
          <button type="button" onClick={() => setMoreOpen(true)} className={tabCls(moreActive)}>
            <Icon name="more" />
            더보기
          </button>
        </div>
      </nav>

      {moreOpen && (
        <div className="sm:hidden fixed inset-0 z-50" role="dialog" aria-modal="true">
          <div className="absolute inset-0 bg-black/40" onClick={() => setMoreOpen(false)} />
          <div
            className="absolute bottom-0 inset-x-0 bg-surface rounded-t-2xl p-4"
            style={{ paddingBottom: "calc(env(safe-area-inset-bottom) + 16px)" }}
          >
            <div className="flex items-center justify-between mb-3">
              <span className="text-[15px] font-bold text-ink">더보기</span>
              <button onClick={() => setMoreOpen(false)} className="text-[13px] text-ink3">
                닫기
              </button>
            </div>
            <div className="grid grid-cols-3 gap-2">
              {moreLinks.map((l) => (
                <Link
                  key={l.href}
                  href={l.href}
                  onClick={() => setMoreOpen(false)}
                  className="rounded-xl border border-line bg-surface2 py-3 text-center text-[13px] font-semibold text-ink2 active:scale-[0.98] transition"
                >
                  {l.label}
                </Link>
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
