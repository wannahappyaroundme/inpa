"use client";

import { useState, useEffect, useCallback, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { useAdminGuard } from "@/lib/useAdminGuard";
import {
  adminListOrders,
  adminUpdateOrderStatus,
  adminGetOrder,
  type AdminOrderListItem,
} from "@/lib/adminApi";
import { type PromotionOrderStatus, type PromotionOrderDetail } from "@/lib/api";
import { Card } from "@/components/ui";

const STATUS_LABELS: Record<PromotionOrderStatus, string> = {
  pending:   "접수 대기",
  reviewing: "검토 중",
  producing: "제작 중",
  shipping:  "배송 중",
  completed: "완료",
  cancelled: "취소",
};

const STATUS_FLOW: PromotionOrderStatus[] = [
  "pending", "reviewing", "producing", "shipping", "completed",
];

function fmt(d: string): string {
  return new Date(d).toLocaleDateString("ko-KR", { year: "numeric", month: "2-digit", day: "2-digit" });
}

function OrdersContent() {
  const ready = useAdminGuard();
  const searchParams = useSearchParams();
  const router = useRouter();

  const page = Number(searchParams.get("page") ?? "1");
  const statusFilter = (searchParams.get("status") as PromotionOrderStatus | null) ?? undefined;

  const [items, setItems] = useState<AdminOrderListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [hasNext, setHasNext] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [selectedOrder, setSelectedOrder] = useState<PromotionOrderDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [statusNote, setStatusNote] = useState("");
  const [trackingNumber, setTrackingNumber] = useState("");
  const [carrier, setCarrier] = useState("");
  const [updating, setUpdating] = useState(false);

  const fetchList = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await adminListOrders({ page, status: statusFilter });
      setItems(res.results);
      setTotal(res.count);
      setHasNext(!!res.next);
    } catch {
      setError("주문 목록을 불러오지 못했어요.");
    } finally {
      setLoading(false);
    }
  }, [page, statusFilter]);

  useEffect(() => { if (ready) fetchList(); }, [ready, fetchList]);

  async function openDetail(id: number) {
    setDetailLoading(true);
    setSelectedOrder(null);
    try {
      const d = await adminGetOrder(id);
      setSelectedOrder(d);
      setStatusNote(d.admin_note);
      setTrackingNumber(d.tracking_number);
      setCarrier(d.carrier);
    } catch {
      /* 무시 */
    } finally {
      setDetailLoading(false);
    }
  }

  async function handleStatusUpdate(nextStatus: PromotionOrderStatus) {
    if (!selectedOrder) return;
    setUpdating(true);
    try {
      await adminUpdateOrderStatus(selectedOrder.id, {
        status: nextStatus,
        admin_note: statusNote,
        tracking_number: trackingNumber || undefined,
        carrier: carrier || undefined,
        note: statusNote,
      });
      await fetchList();
      await openDetail(selectedOrder.id);
    } catch {
      alert("상태 변경에 실패했어요.");
    } finally {
      setUpdating(false);
    }
  }

  if (!ready) return null;

  const filterOptions: (PromotionOrderStatus | undefined)[] = [
    undefined, "pending", "reviewing", "producing", "shipping", "completed", "cancelled",
  ];

  return (
    <div className="p-6">
      <h1 className="text-[22px] font-extrabold text-ink mb-4">판촉물 주문 처리</h1>

      {/* 필터 */}
      <div className="flex gap-2 mb-4 flex-wrap">
        {filterOptions.map((s) => (
          <button
            key={s ?? "all"}
            onClick={() => {
              const qs = new URLSearchParams();
              if (s) qs.set("status", s);
              qs.set("page", "1");
              router.push(`/admin/orders?${qs.toString()}`);
            }}
            className={`px-3 py-1.5 rounded-lg text-[12px] font-semibold transition ${
              statusFilter === s
                ? "bg-brand text-white"
                : "bg-surface2 text-ink2 hover:bg-line"
            }`}
          >
            {s ? STATUS_LABELS[s] : "전체"}
          </button>
        ))}
      </div>

      {error && (
        <div className="mb-4 p-3 rounded-xl bg-red-50 border border-red-200 text-[13px] text-red-700">{error}</div>
      )}

      {loading && <div className="text-[14px] text-ink3">불러오는 중...</div>}

      <div className="flex flex-col lg:flex-row gap-5">
        {/* 목록 */}
        <div className="flex-1 min-w-0">
          {!loading && (
            <>
              <div className="text-[12px] text-ink3 mb-2 tnum">전체 {total}건</div>
              <Card>
                <div className="divide-y divide-line">
                  {items.length === 0 && (
                    <div className="px-4 py-8 text-center text-[13px] text-ink3">주문이 없어요.</div>
                  )}
                  {items.map((item) => (
                    <button
                      key={item.id}
                      onClick={() => openDetail(item.id)}
                      className={`w-full text-left px-4 py-3.5 hover:bg-surface2 transition ${
                        selectedOrder?.id === item.id ? "bg-accent-tint" : ""
                      }`}
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <span
                          className={`text-[11px] font-semibold rounded-full px-2 py-0.5 ${
                            item.status === "pending"
                              ? "bg-orange-50 text-warning"
                              : item.status === "completed"
                              ? "bg-green-50 text-success"
                              : item.status === "cancelled"
                              ? "bg-red-50 text-danger"
                              : "bg-surface2 text-ink3"
                          }`}
                        >
                          {STATUS_LABELS[item.status]}
                        </span>
                        <span className="text-[11px] text-ink3 tnum">#{item.id}</span>
                      </div>
                      <div className="text-[14px] font-semibold text-ink">
                        {item.sample_name ?? "상품 미확인"}
                      </div>
                      <div className="text-[12px] text-ink3 mt-0.5">
                        {item.owner_email} · {fmt(item.created_at)}
                      </div>
                    </button>
                  ))}
                </div>
              </Card>
              <div className="flex gap-3 mt-3 justify-center">
                {page > 1 && (
                  <button
                    onClick={() => {
                      const qs = new URLSearchParams(searchParams.toString());
                      qs.set("page", String(page - 1));
                      router.push(`/admin/orders?${qs.toString()}`);
                    }}
                    className="text-[13px] font-semibold text-brand"
                  >
                    ← 이전
                  </button>
                )}
                <span className="text-[13px] text-ink3 tnum">페이지 {page}</span>
                {hasNext && (
                  <button
                    onClick={() => {
                      const qs = new URLSearchParams(searchParams.toString());
                      qs.set("page", String(page + 1));
                      router.push(`/admin/orders?${qs.toString()}`);
                    }}
                    className="text-[13px] font-semibold text-brand"
                  >
                    다음 →
                  </button>
                )}
              </div>
            </>
          )}
        </div>

        {/* 상세 패널 */}
        {(selectedOrder || detailLoading) && (
          <div className="w-96 shrink-0">
            {detailLoading && <div className="text-[13px] text-ink3">불러오는 중...</div>}
            {selectedOrder && (
              <Card className="p-5">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-[14px] font-bold text-ink">
                    주문 #{selectedOrder.id} · {selectedOrder.sample?.name ?? "상품 미확인"}
                  </span>
                  <button onClick={() => setSelectedOrder(null)} className="text-ink3 text-[18px] leading-none hover:text-ink">×</button>
                </div>
                <div className="text-[12px] text-ink3 mb-3">{fmt(selectedOrder.created_at)}</div>

                {/* form_response */}
                <div className="bg-surface2 rounded-xl p-3 mb-4">
                  <div className="text-[12px] font-semibold text-ink3 mb-2">주문 내역</div>
                  {Object.entries(selectedOrder.form_response).map(([k, v]) => (
                    <div key={k} className="flex gap-2 text-[12px] mb-1">
                      <span className="text-ink3 shrink-0">{k}:</span>
                      <span className="text-ink">{String(v)}</span>
                    </div>
                  ))}
                </div>

                {/* 상태 타임라인 */}
                <div className="mb-4">
                  <div className="text-[12px] font-semibold text-ink3 mb-2">진행 상태</div>
                  <div className="flex gap-1 flex-wrap">
                    {STATUS_FLOW.map((s) => {
                      const idx = STATUS_FLOW.indexOf(selectedOrder.status as PromotionOrderStatus);
                      const sIdx = STATUS_FLOW.indexOf(s);
                      return (
                        <span
                          key={s}
                          className={`text-[11px] font-semibold rounded-full px-2 py-0.5 ${
                            sIdx < idx
                              ? "bg-surface2 text-ink3"
                              : sIdx === idx
                              ? "bg-brand text-white"
                              : "bg-surface2 text-muted"
                          }`}
                        >
                          {STATUS_LABELS[s]}
                        </span>
                      );
                    })}
                  </div>
                  {selectedOrder.status_logs.length > 0 && (
                    <div className="mt-2 space-y-1">
                      {selectedOrder.status_logs.map((log, i) => (
                        <div key={i} className="text-[11px] text-ink3 tnum">
                          {fmt(log.changed_at)} → {STATUS_LABELS[log.to_status]}
                          {log.note && <span> ({log.note})</span>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* 처리 메모 + 상태 전환 */}
                <div className="space-y-3">
                  <div>
                    <label className="block text-[12px] font-semibold text-ink3 mb-1">처리 메모 (설계사에게도 노출)</label>
                    <textarea
                      value={statusNote}
                      onChange={(e) => setStatusNote(e.target.value)}
                      rows={2}
                      className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-[13px] text-ink outline-none focus:border-brand resize-none"
                      placeholder="예: 제작 시작합니다"
                    />
                  </div>
                  <div className="flex gap-2">
                    <div className="flex-1">
                      <label className="block text-[12px] font-semibold text-ink3 mb-1">송장번호</label>
                      <input
                        value={trackingNumber}
                        onChange={(e) => setTrackingNumber(e.target.value)}
                        className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-[12px] text-ink outline-none focus:border-brand"
                        placeholder="배송 시 입력"
                      />
                    </div>
                    <div className="flex-1">
                      <label className="block text-[12px] font-semibold text-ink3 mb-1">택배사</label>
                      <input
                        value={carrier}
                        onChange={(e) => setCarrier(e.target.value)}
                        className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-[12px] text-ink outline-none focus:border-brand"
                        placeholder="예: CJ대한통운"
                      />
                    </div>
                  </div>

                  {/* 다음 상태 버튼 */}
                  <div className="flex gap-2 flex-wrap">
                    {STATUS_FLOW.filter((s) => {
                      const curIdx = STATUS_FLOW.indexOf(selectedOrder.status as PromotionOrderStatus);
                      const sIdx = STATUS_FLOW.indexOf(s);
                      return sIdx > curIdx;
                    }).slice(0, 1).map((nextStatus) => (
                      <button
                        key={nextStatus}
                        disabled={updating}
                        onClick={() => handleStatusUpdate(nextStatus)}
                        className="flex-1 rounded-xl bg-brand text-white text-[13px] font-bold py-2.5 disabled:opacity-50 transition"
                      >
                        {updating ? "처리 중..." : `${STATUS_LABELS[nextStatus]}으로 변경`}
                      </button>
                    ))}
                    {selectedOrder.status !== "cancelled" && (
                      <button
                        disabled={updating}
                        onClick={() => handleStatusUpdate("cancelled")}
                        className="rounded-xl border border-danger text-danger text-[12px] font-semibold px-3 py-2 disabled:opacity-50 transition hover:bg-red-50"
                      >
                        취소
                      </button>
                    )}
                  </div>
                </div>
              </Card>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default function AdminOrdersPage() {
  return (
    <Suspense fallback={null}>
      <OrdersContent />
    </Suspense>
  );
}
