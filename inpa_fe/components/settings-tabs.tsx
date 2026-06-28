"use client";

// 설정 공용 탭바 — 흩어져 있던 설정 4종(기준·미팅·알림·계정)을 한 줄로 묶어 이동.
// nav '기준'(=설정 진입)에서 다른 설정으로 가는 길을 명확히.

import Link from "next/link";

const TABS = [
  { key: "baseline", href: "/settings/baseline", label: "기준" },
  { key: "meetings", href: "/settings/meetings", label: "미팅" },
  { key: "reminders", href: "/settings/reminders", label: "알림" },
  { key: "account", href: "/settings/account", label: "계정" },
] as const;

export type SettingsTabKey = (typeof TABS)[number]["key"];

export function SettingsTabs({ active }: { active: SettingsTabKey }) {
  return (
    <nav className="-mx-1 mb-4 flex gap-1 overflow-x-auto pb-1" aria-label="설정 메뉴">
      {TABS.map((t) => (
        <Link
          key={t.key}
          href={t.href}
          aria-current={t.key === active ? "page" : undefined}
          className={`shrink-0 rounded-full px-3.5 py-1.5 text-[13px] font-semibold transition ${
            t.key === active ? "bg-brand text-white" : "bg-surface2 text-ink2 hover:bg-line"
          }`}
        >
          {t.label}
        </Link>
      ))}
    </nav>
  );
}
