"use client";

import { useState, useEffect, useCallback, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { useAdminGuard } from "@/lib/useAdminGuard";
import {
  adminListReports,
  adminActionReport,
  type AdminReportListItem,
  type ReportStatus,
} from "@/lib/adminApi";
import { Card } from "@/components/ui";

const STATUS_LABELS: Record<ReportStatus, string> = {
  pending:   "검토 대기",
  resolved:  "처리 완료",
  dismissed: "기각",
};

const REASON_LABELS: Record<string, string> = {
  spam:          "스팸",
  inappropriate: "부적절한 내용",
  misinformation:"허위 정보",
  hate:          "혐오",
  adult:         "성인 콘텐츠",
  fake:          "허위 정보",
  other:         "기타",
};

function fmt(d: string): string {
  return new Date(d).toLocaleDateString("ko-KR", { year: "numeric", month: "2-digit", day: "2-digit" });
}

function BoardContent() {
  const ready = useAdminGuard();
  const searchParams = useSearchParams();
  const router = useRouter();

  const page = Number(searchParams.get("page") ?? "1");
  const statusFilter = (searchParams.get("status") as ReportStatus | null) ?? undefined;

  const [items, setItems] = useState<AdminReportListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [hasNext, setHasNext] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [actionNote, setActionNote] = useState<Record<number, string>>({});
  const [acting, setActing] = useState<number | null>(null);

  const fetchList = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await adminListReports({ page, status: statusFilter });
      setItems(res.results);
      setTotal(res.count);
      setHasNext(!!res.next);
    } catch {
      setError("신고 목록을 불러오지 못했어요.");
    } finally {
      setLoading(false);
    }
  }, [page, statusFilter]);

  useEffect(() => { if (ready) fetchList(); }, [ready, fetchList]);

  async function handleAction(id: number, action: "resolved" | "dismissed") {
    setActing(id);
    try {
      await adminActionReport(id, { action, note: actionNote[id] });
      await fetchList();
    } catch {
      alert("처리에 실패했어요.");
    } finally {
      setActing(null);
    }
  }

  if (!ready) return null;

  return (
    <div className="p-6">
      <h1 className="text-[22px] font-extrabold text-ink mb-4">게시판 모더레이션</h1>

      {/* 필터 */}
      <div className="flex gap-2 mb-4 flex-wrap">
        {([undefined, "pending", "resolved", "dismissed"] as (ReportStatus | undefined)[]).map((s) => (
          <button
            key={s ?? "all"}
            onClick={() => {
              const qs = new URLSearchParams();
              if (s) qs.set("status", s);
              qs.set("page", "1");
              router.push(`/admin/board?${qs.toString()}`);
            }}
            className={`px-3 py-1.5 rounded-lg text-[13px] font-semibold transition ${
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

      {!loading && (
        <>
          <div className="text-[12px] text-ink3 mb-2 tnum">전체 {total}건</div>
          <div className="space-y-3">
            {items.length === 0 && (
              <div className="text-center py-8 text-[13px] text-ink3">신고가 없어요.</div>
            )}
            {items.map((item) => (
              <Card key={item.id} className="p-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1 flex-wrap">
                      <span
                        className={`text-[11px] font-semibold rounded-full px-2 py-0.5 ${
                          item.status === "pending"
                            ? "bg-orange-50 text-warning"
                            : item.status === "resolved"
                            ? "bg-green-50 text-success"
                            : "bg-surface2 text-ink3"
                        }`}
                      >
                        {STATUS_LABELS[item.status]}
                      </span>
                      <span className="text-[12px] text-ink3">
                        {item.content_type === "post" ? "게시글" : "댓글"} #{item.object_id}
                      </span>
                      <span className="text-[12px] text-ink font-semibold">
                        {REASON_LABELS[item.reason] ?? item.reason}
                      </span>
                    </div>
                    <div className="text-[12px] text-ink3">
                      신고자: {item.reporter_email ?? "미상"} · {fmt(item.created_at)}
                    </div>
                    {item.detail && (
                      <p className="text-[13px] text-ink mt-1">{item.detail}</p>
                    )}
                  </div>

                  {item.status === "pending" && (
                    <div className="flex flex-col gap-2 shrink-0 w-40">
                      <input
                        value={actionNote[item.id] ?? ""}
                        onChange={(e) => setActionNote((prev) => ({ ...prev, [item.id]: e.target.value }))}
                        placeholder="처리 사유"
                        className="rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[12px] text-ink outline-none focus:border-brand"
                      />
                      <button
                        onClick={() => handleAction(item.id, "resolved")}
                        disabled={acting === item.id}
                        className="rounded-lg bg-danger text-white text-[12px] font-bold py-1.5 disabled:opacity-50"
                      >
                        삭제 처리
                      </button>
                      <button
                        onClick={() => handleAction(item.id, "dismissed")}
                        disabled={acting === item.id}
                        className="rounded-lg border border-line text-ink2 text-[12px] font-semibold py-1.5 disabled:opacity-50 hover:bg-surface2"
                      >
                        기각
                      </button>
                    </div>
                  )}
                </div>
              </Card>
            ))}
          </div>

          <div className="flex gap-3 mt-4 justify-center">
            {page > 1 && (
              <button
                onClick={() => {
                  const qs = new URLSearchParams(searchParams.toString());
                  qs.set("page", String(page - 1));
                  router.push(`/admin/board?${qs.toString()}`);
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
                  router.push(`/admin/board?${qs.toString()}`);
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
  );
}

export default function AdminBoardPage() {
  return (
    <Suspense fallback={null}>
      <BoardContent />
    </Suspense>
  );
}
