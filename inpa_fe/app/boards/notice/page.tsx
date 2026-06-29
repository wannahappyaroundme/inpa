// 공지사항 목록 — AllowAny GET, 비로그인 접근 가능
// 'use client' 필요: 클라이언트에서 listNotices() 호출

"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { AppNav } from "@/components/app-nav";
import { Card } from "@/components/ui";
import { listNotices, type NoticeItem } from "@/lib/api";

function relativeDate(iso: string): string {
  return new Date(iso).toLocaleDateString("ko-KR", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

// 서브탭 — boards 공통
function SubTabs({ active }: { active: "feed" | "notice" | "faq" }) {
  const tabs = [
    { key: "feed" as const, label: "게시판", href: "/boards" },
    { key: "notice" as const, label: "공지사항", href: "/boards/notice" },
    { key: "faq" as const, label: "FAQ", href: "/boards/faq" },
  ];
  return (
    <div className="flex border-b border-line mb-5">
      {tabs.map((t) => (
        <Link
          key={t.key}
          href={t.href}
          className={`px-4 py-2.5 text-[13px] font-semibold border-b-2 transition ${
            active === t.key ? "border-brand text-brand" : "border-transparent text-ink3 hover:text-ink"
          }`}
        >
          {t.label}
        </Link>
      ))}
    </div>
  );
}

export default function NoticePage() {
  const [notices, setNotices] = useState<NoticeItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function load() {
    setLoading(true);
    setError(null);
    listNotices()
      .then((list) => {
        // 발행된 것만 표시, 핀 고정 먼저
        const published = list.filter((n) => n.is_published);
        const sorted = [
          ...published.filter((n) => n.is_pinned),
          ...published.filter((n) => !n.is_pinned),
        ];
        setNotices(sorted);
      })
      .catch(() => setError("공지사항을 불러오지 못했어요. 잠시 후 다시 시도하세요."))
      .finally(() => setLoading(false));
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, []);

  return (
    <div className="min-h-dvh">
      <AppNav active="board" />
      <main className="mx-auto max-w-5xl px-4 sm:px-6 py-6">
        <h1 className="text-[22px] font-extrabold text-ink mb-5">게시판</h1>
        <SubTabs active="notice" />

        {loading && (
          <div className="py-12 text-center text-[14px] text-ink3">불러오는 중...</div>
        )}

        {error && (
          <div className="p-3 rounded-xl bg-danger-tint border border-line text-[13px] text-danger flex items-center justify-between">
            <span>{error}</span>
            <button onClick={load} className="ml-3 font-semibold underline shrink-0">재시도</button>
          </div>
        )}

        {!loading && !error && notices.length === 0 && (
          <div className="py-12 text-center text-[14px] text-ink3">등록된 공지사항이 없어요.</div>
        )}

        <div className="space-y-3">
          {notices.map((n) => (
            <Link key={n.id} href={`/boards/notice/${n.id}`}>
              <Card className="p-4 hover:border-brand/40 transition">
                <div className="flex items-start gap-3">
                  {n.is_pinned && (
                    <span className="shrink-0 rounded-full bg-brand-soft text-brand text-[11px] font-bold px-2 py-0.5 mt-0.5">
                      📌 공지
                    </span>
                  )}
                  <div className="flex-1 min-w-0">
                    <p className="text-[14px] font-semibold text-ink truncate">{n.title}</p>
                    <p className="text-[12px] text-ink3 mt-0.5 tnum">{relativeDate(n.created_at)}</p>
                  </div>
                  <span className="text-ink3 text-[16px] shrink-0">›</span>
                </div>
              </Card>
            </Link>
          ))}
        </div>
      </main>
    </div>
  );
}
