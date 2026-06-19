"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { AppNav } from "@/components/app-nav";
import { Card } from "@/components/ui";
import { useAuthGuard } from "@/lib/useAuthGuard";
import { listSamples, type PromotionSampleListItem } from "@/lib/api";

const CATEGORIES = ["전체", "달력", "다이어리", "생활용품", "기타"] as const;

export default function PromotionPage() {
  const ready = useAuthGuard();

  const [samples, setSamples] = useState<PromotionSampleListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeCategory, setActiveCategory] = useState<string>("전체");

  useEffect(() => {
    if (!ready) return;
    setLoading(true);
    setError(null);
    listSamples()
      .then((res) => setSamples(res.results))
      .catch(() => setError("판촉물 목록을 불러오지 못했어요. 잠시 후 다시 시도하세요."))
      .finally(() => setLoading(false));
  }, [ready]);

  if (!ready) return null;

  const filtered =
    activeCategory === "전체"
      ? samples
      : samples.filter((s) => s.category === activeCategory);

  return (
    <div className="min-h-dvh">
      <AppNav active="promotion" />
      <main className="mx-auto max-w-5xl px-4 sm:px-6 py-6">
        {/* 헤더 */}
        <div className="flex items-center justify-between">
          <h1 className="text-[22px] font-extrabold text-ink">판촉물</h1>
          <Link
            href="/promotion/orders"
            className="text-[13px] font-semibold text-brand"
          >
            내 주문 목록 ›
          </Link>
        </div>

        {/* 카테고리 필터 칩 */}
        <div className="mt-4 flex gap-2 overflow-x-auto pb-1">
          {CATEGORIES.map((cat) => (
            <button
              key={cat}
              onClick={() => setActiveCategory(cat)}
              className={`shrink-0 px-3.5 py-1.5 rounded-full text-[13px] font-semibold transition border ${
                activeCategory === cat
                  ? "bg-brand text-white border-brand"
                  : "bg-surface border-line text-ink2 hover:bg-surface2"
              }`}
            >
              {cat}
            </button>
          ))}
        </div>

        {/* 에러 */}
        {error && (
          <div className="mt-4 p-3 rounded-xl bg-red-50 border border-red-200 text-[13px] text-red-700">
            {error}
          </div>
        )}

        {/* 로딩 */}
        {loading && !samples.length && (
          <div className="mt-8 text-center text-[14px] text-ink3">불러오는 중...</div>
        )}

        {/* 빈 상태 */}
        {!loading && !error && filtered.length === 0 && (
          <div className="mt-12 flex flex-col items-center gap-2 text-center">
            <p className="text-[15px] font-semibold text-ink">등록된 판촉물 샘플이 없습니다</p>
            <p className="text-[13px] text-ink3">관리자에게 문의해 주세요.</p>
          </div>
        )}

        {/* 샘플 그리드 */}
        <div className="mt-4 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
          {filtered.map((s) => (
            <Link key={s.id} href={`/promotion/${s.id}`} className="group">
              <Card className="overflow-hidden transition hover:shadow-md">
                {/* 대표 이미지 */}
                <div className="aspect-square bg-surface2 relative overflow-hidden">
                  {s.primary_image ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={s.primary_image}
                      alt={s.name}
                      className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-200"
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-muted text-[12px]">
                      이미지 없음
                    </div>
                  )}
                  {/* 주문 불가 배지 */}
                  {!s.is_available && (
                    <div className="absolute inset-0 bg-black/40 flex items-center justify-center">
                      <span className="bg-white/90 text-ink text-[12px] font-bold px-2.5 py-1 rounded-full">
                        주문 불가
                      </span>
                    </div>
                  )}
                </div>
                {/* 카드 하단 */}
                <div className="p-3">
                  <p className="text-[14px] font-bold text-ink leading-snug line-clamp-2">
                    {s.name}
                  </p>
                  <div className="mt-1.5 flex items-center gap-1.5">
                    <span className="text-[11px] font-semibold text-brand bg-accent-tint px-2 py-0.5 rounded-full">
                      {s.category}
                    </span>
                    {s.is_available ? (
                      <span className="text-[11px] text-success font-semibold">주문 가능</span>
                    ) : (
                      <span className="text-[11px] text-muted font-semibold">주문 불가</span>
                    )}
                  </div>
                </div>
              </Card>
            </Link>
          ))}
        </div>
      </main>
    </div>
  );
}
