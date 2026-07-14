"use client";

import { useState, useEffect, useCallback, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { useAdminGuard } from "@/lib/useAdminGuard";
import {
  adminListInquiries,
  adminReplyInquiry,
  adminUpdateInquiryStatus,
  adminGetInquiry,
  type AdminInquiryListItem,
  type AdminInquiryDetail,
} from "@/lib/adminApi";
import { type InquiryStatus, type InquiryCategory } from "@/lib/api";
import { Card } from "@/components/ui";

const STATUS_LABELS: Record<InquiryStatus, string> = {
  open: "접수",
  answered: "답변 완료",
  closed: "종결",
};

const CATEGORY_LABELS: Record<InquiryCategory, string> = {
  feedback: "의견",
  feature: "제안",
  bug: "불편",
  billing: "요금·결제",
  other: "기타",
};

const CATEGORY_FILTERS: (InquiryCategory | undefined)[] = [
  undefined, "feedback", "feature", "bug", "billing", "other",
];

function catLabel(c: string): string {
  return (CATEGORY_LABELS as Record<string, string>)[c] ?? c;
}

function fmt(d: string): string {
  return new Date(d).toLocaleDateString("ko-KR", { year: "numeric", month: "2-digit", day: "2-digit" });
}

/** 별점 표시(이용 의견). rating 없으면 아무것도 그리지 않음. */
function StarRating({ rating }: { rating: number | null }) {
  if (!rating) return null;
  return (
    <span className="inline-flex items-center gap-0.5 text-warn" aria-label={`별점 ${rating}점`}>
      {[1, 2, 3, 4, 5].map((n) => (
        <span key={n} className={n <= rating ? "text-warn" : "text-line"}>★</span>
      ))}
    </span>
  );
}

function InquiriesContent() {
  const ready = useAdminGuard();
  const searchParams = useSearchParams();
  const router = useRouter();

  const page = Number(searchParams.get("page") ?? "1");
  const statusFilter = (searchParams.get("status") as InquiryStatus | null) ?? undefined;
  const categoryFilter = (searchParams.get("category") as InquiryCategory | null) ?? undefined;

  const [items, setItems] = useState<AdminInquiryListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [hasNext, setHasNext] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<AdminInquiryDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [replyText, setReplyText] = useState("");
  const [replying, setReplying] = useState(false);

  const fetchList = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await adminListInquiries({ page, status: statusFilter, category: categoryFilter });
      setItems(res.results);
      setTotal(res.count);
      setHasNext(!!res.next);
    } catch {
      setError("문의 목록을 불러오지 못했어요.");
    } finally {
      setLoading(false);
    }
  }, [page, statusFilter, categoryFilter]);

  useEffect(() => { if (ready) fetchList(); }, [ready, fetchList]);

  async function openDetail(id: number) {
    setSelectedId(id);
    setDetail(null);
    setDetailLoading(true);
    try {
      const d = await adminGetInquiry(id);
      setDetail(d);
    } catch {
      /* 상세 로드 실패 무시 */
    } finally {
      setDetailLoading(false);
    }
  }

  async function handleReply() {
    if (!selectedId || !replyText.trim()) return;
    setReplying(true);
    try {
      await adminReplyInquiry(selectedId, replyText);
      setReplyText("");
      const d = await adminGetInquiry(selectedId);
      setDetail(d);
      await fetchList();
    } catch {
      alert("답변 등록에 실패했어요.");
    } finally {
      setReplying(false);
    }
  }

  async function handleStatusChange(id: number, status: InquiryStatus) {
    try {
      await adminUpdateInquiryStatus(id, status);
      await fetchList();
      if (selectedId === id) {
        const d = await adminGetInquiry(id);
        setDetail(d);
      }
    } catch {
      alert("상태 변경에 실패했어요.");
    }
  }

  if (!ready) return null;

  return (
    <div>
      <h1 className="text-[22px] font-extrabold text-ink mb-6">1:1 문의</h1>

      {/* 상태 필터 */}
      <div className="flex gap-2 mb-2 flex-wrap">
        {([undefined, "open", "answered", "closed"] as (InquiryStatus | undefined)[]).map((s) => (
          <button
            key={s ?? "all"}
            onClick={() => {
              const qs = new URLSearchParams();
              if (s) qs.set("status", s);
              if (categoryFilter) qs.set("category", categoryFilter);
              qs.set("page", "1");
              router.push(`/admin/inquiries?${qs.toString()}`);
            }}
            className={`px-3 py-1.5 rounded-lg text-[13px] font-semibold transition ${
              statusFilter === s
                ? "bg-brand-soft text-brand"
                : "bg-surface2 text-ink2 hover:bg-line"
            }`}
          >
            {s ? STATUS_LABELS[s] : "전체"}
          </button>
        ))}
      </div>

      {/* 종류 필터 */}
      <div className="flex gap-2 mb-4 flex-wrap">
        {CATEGORY_FILTERS.map((c) => (
          <button
            key={c ?? "all"}
            onClick={() => {
              const qs = new URLSearchParams();
              if (statusFilter) qs.set("status", statusFilter);
              if (c) qs.set("category", c);
              qs.set("page", "1");
              router.push(`/admin/inquiries?${qs.toString()}`);
            }}
            className={`px-3 py-1.5 rounded-lg text-[13px] font-semibold transition ${
              categoryFilter === c
                ? "bg-brand-soft text-brand"
                : "bg-surface2 text-ink2 hover:bg-line"
            }`}
          >
            {c ? CATEGORY_LABELS[c] : "전체 종류"}
          </button>
        ))}
      </div>

      {error && (
        <div className="mb-4 p-3 rounded-xl bg-danger-tint border border-line text-[13px] text-danger-ink">{error}</div>
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
                    <div className="px-4 py-8 text-center text-ink3 text-[13px]">문의가 없어요.</div>
                  )}
                  {items.map((item) => (
                    <button
                      key={item.id}
                      onClick={() => openDetail(item.id)}
                      className={`w-full text-left px-4 py-3.5 hover:bg-surface2 transition ${
                        selectedId === item.id ? "bg-accent-tint" : ""
                      }`}
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <span
                          className={`text-[11px] font-semibold rounded-full px-2 py-0.5 ${
                            item.status === "open"
                              ? "bg-danger-tint text-danger-ink"
                              : item.status === "answered"
                              ? "bg-success-tint text-success-ink"
                              : "bg-surface2 text-ink3"
                          }`}
                        >
                          {STATUS_LABELS[item.status]}
                        </span>
                        <span className="text-[11px] font-semibold rounded-full px-2 py-0.5 bg-surface2 text-ink2">
                          {catLabel(item.category)}
                        </span>
                        <StarRating rating={item.rating} />
                      </div>
                      <div className="text-[14px] font-semibold text-ink truncate">{item.title}</div>
                      <div className="text-[12px] text-ink3 mt-0.5">
                        {item.owner_email ?? (
                          <span className="text-warn-ink font-semibold">비회원</span>
                        )}{" "}
                        · {fmt(item.created_at)}
                      </div>
                    </button>
                  ))}
                </div>
              </Card>

              {/* 페이지네이션 */}
              <div className="flex gap-3 mt-3 justify-center">
                {page > 1 && (
                  <button
                    onClick={() => {
                      const qs = new URLSearchParams(searchParams.toString());
                      qs.set("page", String(page - 1));
                      router.push(`/admin/inquiries?${qs.toString()}`);
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
                      router.push(`/admin/inquiries?${qs.toString()}`);
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
        {selectedId && (
          <div className="w-96 shrink-0">
            {detailLoading && <div className="text-[13px] text-ink3">불러오는 중...</div>}
            {detail && (
              <Card className="p-5">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-[14px] font-bold text-ink">{detail.title}</span>
                  <button
                    onClick={() => setSelectedId(null)}
                    className="text-ink3 text-[18px] leading-none hover:text-ink"
                  >
                    ×
                  </button>
                </div>
                <div className="flex items-center gap-2 mb-1.5">
                  <span className="text-[11px] font-semibold rounded-full px-2 py-0.5 bg-surface2 text-ink2">
                    {catLabel(detail.category)}
                  </span>
                  <StarRating rating={detail.rating} />
                  <span className="text-[12px] text-ink3">{fmt(detail.created_at)}</span>
                </div>

                {/* 작성자 — 로그인 설계사면 이메일, 아니면 비회원(+답변 이메일) */}
                <div className="text-[12px] text-ink3 mb-3">
                  {detail.owner_email ? (
                    <>보낸 사람: {detail.owner_email}</>
                  ) : (
                    <>
                      <span className="text-warn-ink font-semibold">비회원</span>
                      {detail.contact_email ? (
                        <> · 답변 이메일: <span className="text-ink2">{detail.contact_email}</span></>
                      ) : (
                        <> · 답변 받을 이메일 없음</>
                      )}
                    </>
                  )}
                </div>

                <p className="text-[14px] text-ink leading-6 mb-4 whitespace-pre-wrap">{detail.body}</p>

                {/* 불편 신고 화면 정보(관리자 전용) */}
                {detail.meta && (detail.meta.path || detail.meta.user_agent || detail.meta.viewport) && (
                  <div className="mb-4 rounded-xl bg-surface2 px-3 py-2.5 space-y-1">
                    <div className="text-[11px] font-semibold text-ink3 mb-1">보낸 화면 정보</div>
                    {detail.meta.path && (
                      <div className="text-[12px] text-ink2 break-all">
                        <span className="text-ink3">화면 주소</span> {detail.meta.path}
                      </div>
                    )}
                    {detail.meta.viewport && (
                      <div className="text-[12px] text-ink2">
                        <span className="text-ink3">화면 크기</span> {detail.meta.viewport}
                      </div>
                    )}
                    {detail.meta.user_agent && (
                      <div className="text-[12px] text-ink2 break-all">
                        <span className="text-ink3">브라우저</span> {detail.meta.user_agent}
                      </div>
                    )}
                  </div>
                )}

                {/* 비회원 답변 안내 */}
                {!detail.owner_email && (
                  <div className="mb-4 rounded-xl bg-warn-soft px-3 py-2.5 text-[12px] text-warn-ink leading-5">
                    {detail.contact_email
                      ? "비회원 문의예요. 답변은 위 이메일로 직접 보내주세요(앱 알림은 전달되지 않아요)."
                      : "비회원 문의예요. 답변 받을 이메일이 없어 기록용으로만 남길 수 있어요."}
                  </div>
                )}

                {/* 상태 변경 */}
                <div className="flex gap-2 mb-4">
                  {(["open", "answered", "closed"] as InquiryStatus[]).map((s) => (
                    <button
                      key={s}
                      disabled={detail.status === s}
                      onClick={() => handleStatusChange(detail.id, s)}
                      className={`text-[11px] font-semibold rounded-full px-3 py-1 transition ${
                        detail.status === s
                          ? "bg-brand-soft text-brand"
                          : "bg-surface2 text-ink2 hover:bg-line"
                      }`}
                    >
                      {STATUS_LABELS[s]}
                    </button>
                  ))}
                </div>

                {/* 기존 답변 */}
                {detail.replies.length > 0 && (
                  <div className="border-t border-line pt-3 mb-3 space-y-3">
                    {detail.replies.map((r) => (
                      <div key={r.id} className="bg-accent-tint rounded-xl px-3 py-2.5">
                        <div className="text-[11px] text-ink3 mb-1">{r.author_email} · {fmt(r.created_at)}</div>
                        <p className="text-[13px] text-ink whitespace-pre-wrap">{r.body}</p>
                      </div>
                    ))}
                  </div>
                )}

                {/* 답변 작성 */}
                <textarea
                  value={replyText}
                  onChange={(e) => setReplyText(e.target.value)}
                  placeholder="답변을 입력하세요"
                  rows={3}
                  className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-[13px] text-ink outline-none focus:border-brand resize-none"
                />
                <button
                  onClick={handleReply}
                  disabled={replying || !replyText.trim()}
                  className="mt-2 w-full rounded-xl bg-brand text-white text-[13px] font-bold py-2.5 disabled:opacity-50 transition"
                >
                  {replying ? "등록 중..." : "답변 등록"}
                </button>
              </Card>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default function AdminInquiriesPage() {
  return (
    <Suspense fallback={null}>
      <InquiriesContent />
    </Suspense>
  );
}
