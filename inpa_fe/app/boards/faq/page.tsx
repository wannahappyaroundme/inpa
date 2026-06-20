// FAQ 아코디언 — AllowAny GET, 비로그인 접근 가능

"use client";

import { useState, useEffect, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { AppNav } from "@/components/app-nav";
import { Card } from "@/components/ui";
import { listFaqs, type FaqItem } from "@/lib/api";

// 서브탭
function SubTabs({ active }: { active: "feed" | "notice" | "faq" }) {
  const tabs = [
    { key: "feed" as const, label: "게시판", href: "/boards" },
    { key: "notice" as const, label: "공지사항", href: "/boards/notice" },
    { key: "faq" as const, label: "FAQ", href: "/boards/faq" },
  ];
  return (
    <div className="flex border-b border-line mb-5">
      {tabs.map((t) => (
        <Link key={t.key} href={t.href}
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

// 아코디언 항목
function FaqAccordionItem({ faq }: { faq: FaqItem }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-b border-line last:border-b-0">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="w-full flex items-center justify-between py-4 text-left gap-3"
      >
        <span className="text-[14px] font-semibold text-ink leading-5">{faq.question}</span>
        <span aria-hidden className={`text-ink3 text-[18px] shrink-0 transition-transform ${open ? "rotate-180" : ""}`}>
          ˅
        </span>
      </button>
      {open && (
        <div className="pb-4 text-[13px] text-ink2 leading-6 whitespace-pre-wrap">
          {faq.answer}
        </div>
      )}
    </div>
  );
}

// FAQ 내부 컴포넌트 (useSearchParams 분리 → Suspense 필요)
function FaqContent() {
  const searchParams = useSearchParams();
  const initQ = searchParams.get("q") ?? "";

  const [faqs, setFaqs] = useState<FaqItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState(initQ);
  const [search, setSearch] = useState(initQ);

  useEffect(() => {
    const id = setTimeout(() => setSearch(searchInput), 400);
    return () => clearTimeout(id);
  }, [searchInput]);

  useEffect(() => {
    setLoading(true);
    listFaqs({ q: search || undefined })
      .then((list) => setFaqs(list.filter((f) => f.is_published)))
      .catch(() => setError("FAQ를 불러오지 못했어요."))
      .finally(() => setLoading(false));
  }, [search]);

  // 카테고리별 그룹핑 + order 정렬
  const grouped = faqs.reduce<Record<string, FaqItem[]>>((acc, f) => {
    (acc[f.category] ??= []).push(f);
    return acc;
  }, {});
  Object.values(grouped).forEach((g) => g.sort((a, b) => a.order - b.order));
  const categories = Object.keys(grouped);

  return (
    <>
      {/* 검색 */}
      <div className="mb-5">
        <input
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          placeholder="궁금한 내용을 검색하세요"
          className="w-full rounded-xl border border-line bg-surface px-4 py-2.5 text-[14px] text-ink placeholder:text-muted outline-none focus:border-brand"
        />
      </div>

      {loading && <div className="py-12 text-center text-[14px] text-ink3">불러오는 중...</div>}
      {error && <div className="p-3 rounded-xl bg-red-50 border border-red-200 text-[13px] text-red-700">{error}</div>}

      {!loading && !error && faqs.length === 0 && (
        <div className="py-12 text-center text-[14px] text-ink3">
          {search ? "검색 결과가 없어요." : "등록된 FAQ가 없어요."}
        </div>
      )}

      {/* 카테고리별 아코디언 */}
      <div className="space-y-4">
        {categories.map((cat) => (
          <Card key={cat} className="px-4">
            <div className="py-3 border-b border-line">
              <span className="text-[13px] font-bold text-brand">{cat}</span>
            </div>
            {grouped[cat].map((faq) => (
              <FaqAccordionItem key={faq.id} faq={faq} />
            ))}
          </Card>
        ))}
      </div>
    </>
  );
}

export default function FaqPage() {
  return (
    <div className="min-h-dvh">
      <AppNav active="board" />
      <main className="mx-auto max-w-5xl px-4 sm:px-6 py-6">
        <h1 className="text-[22px] font-extrabold text-ink mb-5">게시판</h1>
        <SubTabs active="faq" />
        <Suspense fallback={<div className="py-12 text-center text-[14px] text-ink3">불러오는 중...</div>}>
          <FaqContent />
        </Suspense>
      </main>
    </div>
  );
}
