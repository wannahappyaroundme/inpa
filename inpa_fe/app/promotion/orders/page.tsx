"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { AppNav } from "@/components/app-nav";
import { Card } from "@/components/ui";
import { useAuthGuard } from "@/lib/useAuthGuard";
import { listMyOrders, type PromotionOrderListItem, type PromotionOrderStatus } from "@/lib/api";

// 상태 배지 색상 매핑
const STATUS_META: Record<
  PromotionOrderStatus,
  { label: string; bg: string; text: string }
> = {
  pending:   { label: "예약 접수", bg: "bg-surface2",       text: "text-ink3" },
  reviewing: { label: "검토 중",   bg: "bg-brand-soft",     text: "text-brand" },
  producing: { label: "제작 중",   bg: "bg-warning-tint",   text: "text-warning" },
  shipping:  { label: "발송",      bg: "bg-orange-50",      text: "text-orange-700" },
  completed: { label: "완료",      bg: "bg-success-tint",   text: "text-success" },
  cancelled: { label: "취소",      bg: "bg-danger-tint",    text: "text-danger" },
};

function StatusBadge({ status }: { status: PromotionOrderStatus }) {
  const meta = STATUS_META[status] ?? { label: status, bg: "bg-surface2", text: "text-ink3" };
  return (
    <span className={`text-[11px] font-bold px-2.5 py-0.5 rounded-full ${meta.bg} ${meta.text}`}>
      {meta.label}
    </span>
  );
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, "0")}.${String(d.getDate()).padStart(2, "0")}`;
}

export default function MyOrdersPage() {
  const ready = useAuthGuard();

  const [orders, setOrders] = useState<PromotionOrderListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready) return;
    setLoading(true);
    setError(null);
    listMyOrders()
      .then((res) => setOrders(res.results))
      .catch(() => setError("주문 목록을 불러오지 못했어요. 잠시 후 다시 시도하세요."))
      .finally(() => setLoading(false));
  }, [ready]);

  if (!ready) return null;

  return (
    <div className="min-h-dvh">
      <AppNav active="promotion" />
      <main className="mx-auto max-w-[1440px] px-4 sm:px-6 py-6">
        {/* 헤더 */}
        <div className="flex items-center justify-between">
          <h1 className="text-[22px] font-extrabold text-ink">내 주문 목록</h1>
          <Link
            href="/promotion"
            className="text-[13px] font-semibold text-brand"
          >
            ← 샘플 보러 가기
          </Link>
        </div>

        {/* 에러 */}
        {error && (
          <div className="mt-4 p-3 rounded-xl bg-danger-tint border border-line text-[13px] text-danger flex items-center justify-between">
            <span>{error}</span>
            <button
              onClick={() => {
                setLoading(true);
                setError(null);
                listMyOrders()
                  .then((res) => setOrders(res.results))
                  .catch(() => setError("주문 목록을 불러오지 못했어요. 잠시 후 다시 시도하세요."))
                  .finally(() => setLoading(false));
              }}
              className="ml-3 font-semibold underline shrink-0"
            >
              재시도
            </button>
          </div>
        )}

        {/* 로딩 */}
        {loading && !orders.length && (
          <div className="mt-8 text-center text-[14px] text-ink3">불러오는 중...</div>
        )}

        {/* 빈 상태 */}
        {!loading && !error && orders.length === 0 && (
          <div className="mt-12 flex flex-col items-center gap-3">
            <p className="text-[15px] font-semibold text-ink">아직 주문한 판촉물이 없습니다</p>
            <Link
              href="/promotion"
              className="rounded-xl bg-brand text-white text-[13px] font-bold px-5 py-2.5"
            >
              샘플 보러 가기
            </Link>
          </div>
        )}

        {/* 주문 목록 */}
        <div className="mt-4 space-y-3">
          {orders.map((order) => (
            <Link key={order.id} href={`/promotion/orders/${order.id}`}>
              <Card className="p-4 flex items-center gap-3 hover:shadow-md transition">
                {/* 샘플명 + 날짜 */}
                <div className="flex-1 min-w-0">
                  <p className="text-[15px] font-bold text-ink truncate">
                    {order.sample?.name ?? "(샘플 삭제됨)"}
                  </p>
                  <p className="text-[12px] text-ink3 mt-0.5 tnum">
                    {formatDate(order.created_at)}
                  </p>
                </div>
                {/* 상태 배지 */}
                <div className="shrink-0 flex items-center gap-2">
                  <StatusBadge status={order.status} />
                  <span className="text-ink3 text-[16px]">›</span>
                </div>
              </Card>
            </Link>
          ))}
        </div>
      </main>
    </div>
  );
}
