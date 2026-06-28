"use client";

import { useState, useEffect, use } from "react";
import Link from "next/link";
import { AppNav } from "@/components/app-nav";
import { Card } from "@/components/ui";
import { useAuthGuard } from "@/lib/useAuthGuard";
import {
  getMyOrder,
  cancelOrder,
  ApiError,
  type PromotionOrderDetail,
  type PromotionOrderStatus,
  type PromotionOrderStatusLog,
} from "@/lib/api";

// ── 상태 메타 ────────────────────────────────────────────────────────────────

const STATUS_ORDER: PromotionOrderStatus[] = [
  "pending",
  "reviewing",
  "producing",
  "shipping",
  "completed",
];

const STATUS_LABEL: Record<PromotionOrderStatus, string> = {
  pending:   "예약 접수",
  reviewing: "검토 중",
  producing: "제작 중",
  shipping:  "발송",
  completed: "완료",
  cancelled: "취소",
};

const STATUS_BADGE: Record<
  PromotionOrderStatus,
  { bg: string; text: string }
> = {
  pending:   { bg: "bg-surface2",      text: "text-ink3" },
  reviewing: { bg: "bg-brand-soft",    text: "text-brand" },
  producing: { bg: "bg-warning-tint",  text: "text-warning" },
  shipping:  { bg: "bg-warning-tint",  text: "text-warning" },
  completed: { bg: "bg-success-tint",  text: "text-success" },
  cancelled: { bg: "bg-danger-tint",   text: "text-danger" },
};

function StatusBadge({ status }: { status: PromotionOrderStatus }) {
  const b = STATUS_BADGE[status] ?? { bg: "bg-surface2", text: "text-ink3" };
  return (
    <span className={`text-[12px] font-bold px-3 py-1 rounded-full ${b.bg} ${b.text}`}>
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

// ── 상태 타임라인 컴포넌트 ────────────────────────────────────────────────────

function Timeline({
  logs,
  currentStatus,
}: {
  logs: PromotionOrderStatusLog[];
  currentStatus: PromotionOrderStatus;
}) {
  const isCancelled = currentStatus === "cancelled";
  const reachedStatuses = new Set(logs.map((l) => l.to_status));
  const logByStatus: Record<string, PromotionOrderStatusLog | undefined> = {};
  for (const l of logs) {
    logByStatus[l.to_status] = l;
  }

  if (isCancelled) {
    const cancelLog = logByStatus["cancelled"];
    return (
      <div className="space-y-3">
        <div className="flex items-start gap-3">
          <div className="w-2.5 h-2.5 rounded-full bg-danger mt-1 shrink-0" />
          <div>
            <p className="text-[13px] font-semibold text-danger">취소됨</p>
            {cancelLog && (
              <p className="text-[12px] text-ink3 tnum mt-0.5">{formatDateTime(cancelLog.changed_at)}</p>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {STATUS_ORDER.map((s) => {
        const reached = reachedStatuses.has(s);
        const isCurrent = s === currentStatus;
        const log = logByStatus[s];
        return (
          <div key={s} className="flex items-start gap-3">
            <div
              className={`w-2.5 h-2.5 rounded-full mt-1 shrink-0 ${
                reached ? "bg-brand" : "bg-line-2"
              }`}
            />
            <div>
              <p
                className={`text-[13px] font-semibold ${
                  isCurrent ? "text-ink" : reached ? "text-ink2" : "text-muted"
                }`}
              >
                {STATUS_LABEL[s]}
              </p>
              {log && (
                <p className="text-[12px] text-ink3 tnum mt-0.5">
                  {formatDateTime(log.changed_at)}
                </p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── 메인 페이지 ─────────────────────────────────────────────────────────────

export default function OrderDetailPage({
  params,
}: {
  params: Promise<{ orderId: string }>;
}) {
  const { orderId } = use(params);
  const ready = useAuthGuard();

  const [order, setOrder] = useState<PromotionOrderDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [cancelDone, setCancelDone] = useState(false);

  useEffect(() => {
    if (!ready) return;
    const id = Number(orderId);
    if (isNaN(id)) {
      setPageError("잘못된 주문 주소예요.");
      setLoading(false);
      return;
    }
    getMyOrder(id)
      .then(setOrder)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 404) {
          setPageError("주문을 찾을 수 없어요.");
        } else {
          setPageError("주문 정보를 불러오지 못했어요.");
        }
      })
      .finally(() => setLoading(false));
  }, [ready, orderId]);

  if (!ready) return null;

  if (loading) {
    return (
      <div className="min-h-dvh">
        <AppNav active="promotion" />
        <div className="mt-16 text-center text-[14px] text-ink3">불러오는 중...</div>
      </div>
    );
  }

  if (pageError || !order) {
    return (
      <div className="min-h-dvh">
        <AppNav active="promotion" />
        <main className="mx-auto max-w-5xl px-4 sm:px-6 py-6">
          <Link href="/promotion/orders" className="text-[13px] text-brand">← 내 주문 목록</Link>
          <p className="mt-4 text-[14px] text-ink3">{pageError ?? "주문 정보를 찾을 수 없어요."}</p>
        </main>
      </div>
    );
  }

  async function handleCancel() {
    if (!order) return;
    setCancelling(true);
    setCancelError(null);
    try {
      await cancelOrder(order.id);
      setCancelDone(true);
      // 주문 상태 갱신 (취소 완료 표시)
      setOrder((prev) =>
        prev ? { ...prev, status: "cancelled", status_display: "취소" } : prev
      );
    } catch (err) {
      if (err instanceof ApiError) {
        setCancelError(err.message || "주문 취소에 실패했어요.");
      } else {
        setCancelError("주문 취소에 실패했어요. 다시 시도해 주세요.");
      }
    } finally {
      setCancelling(false);
    }
  }

  // form_response 표시용 엔트리 배열
  const formEntries = Object.entries(order.form_response);

  return (
    <div className="min-h-dvh">
      <AppNav active="promotion" />
      <main className="mx-auto max-w-5xl px-4 sm:px-6 py-6">
        {/* 뒤로 가기 */}
        <Link
          href="/promotion/orders"
          className="inline-flex items-center gap-1 text-[13px] text-ink3 hover:text-ink transition mb-5"
        >
          ← 내 주문 목록
        </Link>

        {/* 주문 번호 + 상태 */}
        <div className="flex items-start justify-between gap-3 mb-5">
          <div>
            <h1 className="text-[20px] font-extrabold text-ink">
              주문 #{String(order.id).padStart(4, "0")}
            </h1>
            <p className="text-[12px] text-ink3 tnum mt-0.5">
              {order.sample?.name ?? "(샘플 삭제됨)"}
            </p>
          </div>
          <StatusBadge status={order.status} />
        </div>

        <div className="grid md:grid-cols-2 gap-5">
          {/* 왼쪽: 제출 내용 */}
          <Card className="p-4 sm:p-5 space-y-4">
            <h2 className="text-[15px] font-bold text-ink">제출 내용</h2>
            {formEntries.length === 0 ? (
              <p className="text-[13px] text-muted">제출 내용이 없어요.</p>
            ) : (
              <dl className="space-y-3">
                {formEntries.map(([key, val]) => (
                  <div key={key} className="flex gap-3">
                    <dt className="text-[12px] font-semibold text-ink3 w-28 shrink-0 pt-0.5">
                      {key}
                    </dt>
                    <dd className="text-[13px] text-ink flex-1 break-words">
                      {Array.isArray(val)
                        ? (val as string[]).join(", ")
                        : String(val ?? "")}
                    </dd>
                  </div>
                ))}
              </dl>
            )}

            {/* 운송장 정보 (발송 이후) */}
            {(order.status === "shipping" || order.status === "completed") &&
              order.tracking_number && (
                <div className="mt-2 p-3 rounded-xl bg-surface2 text-[13px] text-ink">
                  <p className="font-semibold mb-1">배송 정보</p>
                  {order.carrier && <p>택배사: {order.carrier}</p>}
                  <p>운송장: {order.tracking_number}</p>
                </div>
              )}

            {/* 관리자 메모 */}
            {order.admin_note && (
              <div className="p-3 rounded-xl bg-accent-tint border border-brand/20 text-[13px] text-ink">
                <p className="font-semibold text-brand mb-1">관리자 메모</p>
                <p className="whitespace-pre-wrap">{order.admin_note}</p>
              </div>
            )}

            {/* 취소 에러 */}
            {cancelError && (
              <div className="p-3 rounded-xl bg-danger-tint border border-danger/20 text-[13px] text-danger">
                {cancelError}
              </div>
            )}

            {/* 취소 버튼 (pending 상태만) */}
            {order.status === "pending" && !cancelDone && (
              <button
                onClick={handleCancel}
                disabled={cancelling}
                className="w-full mt-1 rounded-xl border border-danger text-danger text-[13px] font-semibold py-2.5 hover:bg-danger-tint transition disabled:opacity-40"
              >
                {cancelling ? "취소 중..." : "주문 취소"}
              </button>
            )}
            {cancelDone && (
              <p className="text-[13px] text-ink3 text-center">주문이 취소되었습니다.</p>
            )}
          </Card>

          {/* 오른쪽: 진행 상태 타임라인 */}
          <Card className="p-4 sm:p-5 space-y-4">
            <h2 className="text-[15px] font-bold text-ink">진행 상태</h2>
            <Timeline logs={order.status_logs} currentStatus={order.status} />

            {/* 수동 제작 안내 */}
            <p className="text-[12px] text-muted pt-2 border-t border-line">
              주문 후 담당자가 확인해 제작·발송합니다. 진행 상황은 이 페이지에서 확인하세요.
            </p>
          </Card>
        </div>
      </main>
    </div>
  );
}
