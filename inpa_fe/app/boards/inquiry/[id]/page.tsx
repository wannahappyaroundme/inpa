"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { AppNav } from "@/components/app-nav";
import { Card } from "@/components/ui";
import { useAuthGuard } from "@/lib/useAuthGuard";
import { getInquiry, type InquiryDetail, type InquiryStatus } from "@/lib/api";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("ko-KR", {
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const STATUS_META: Record<InquiryStatus, { label: string; color: string; bgColor: string }> = {
  open: { label: "답변 대기 중", color: "text-warning", bgColor: "bg-yellow-50 border-yellow-200" },
  answered: { label: "답변 완료", color: "text-success", bgColor: "bg-green-50 border-green-200" },
  closed: { label: "완료", color: "text-ink3", bgColor: "bg-surface2 border-line" },
};

const CATEGORY_LABELS: Record<string, string> = {
  feature: "기능문의",
  billing: "요금결제",
  bug: "버그신고",
  other: "기타",
};

export default function InquiryDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const ready = useAuthGuard();

  const inquiryId = Number(params.id);

  const [inquiry, setInquiry] = useState<InquiryDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready || !inquiryId) return;
    getInquiry(inquiryId)
      .then(setInquiry)
      .catch((e) => {
        if (e?.status === 404) setError("존재하지 않는 문의이거나 접근 권한이 없어요.");
        else setError("문의를 불러오지 못했어요.");
      })
      .finally(() => setLoading(false));
  }, [ready, inquiryId]);

  if (!ready) return null;

  if (loading) {
    return (
      <div className="min-h-dvh">
        <AppNav active="board" />
        <main className="mx-auto max-w-5xl px-4 sm:px-6 py-6">
          <div className="py-12 text-center text-[14px] text-ink3">불러오는 중...</div>
        </main>
      </div>
    );
  }

  if (error || !inquiry) {
    return (
      <div className="min-h-dvh">
        <AppNav active="board" />
        <main className="mx-auto max-w-5xl px-4 sm:px-6 py-6">
          <button onClick={() => router.back()} className="text-[13px] text-ink3 mb-4">‹ 뒤로</button>
          <div className="py-12 text-center">
            <p className="text-[15px] font-semibold text-ink3">{error ?? "문의를 찾을 수 없어요."}</p>
            <Link href="/boards/inquiry" className="mt-4 inline-block text-[13px] text-brand">내 문의 목록으로</Link>
          </div>
        </main>
      </div>
    );
  }

  const statusMeta = STATUS_META[inquiry.status];

  return (
    <div className="min-h-dvh">
      <AppNav active="board" />
      <main className="mx-auto max-w-5xl px-4 sm:px-6 py-6">
        <button onClick={() => router.back()} className="text-[13px] text-ink3 flex items-center gap-1 hover:text-ink transition mb-5">
          ‹ 내 문의 목록
        </button>

        {/* 상태 배너 */}
        <div className={`mb-4 p-3 rounded-xl border text-[13px] font-semibold ${statusMeta.bgColor} ${statusMeta.color}`}>
          {statusMeta.label}
        </div>

        {/* 문의 본문 */}
        <Card className="p-5 mb-4">
          <div className="flex items-center gap-2 mb-3">
            <span className="rounded-full bg-surface2 text-ink3 text-[11px] font-semibold px-2.5 py-0.5">
              {CATEGORY_LABELS[inquiry.category] ?? inquiry.category}
            </span>
          </div>
          <h1 className="text-[18px] font-extrabold text-ink mb-2">{inquiry.title}</h1>
          <p className="text-[12px] text-ink3 mb-4 pb-4 border-b border-line tnum">
            {formatDate(inquiry.created_at)}
          </p>
          <div className="text-[14px] text-ink leading-6 whitespace-pre-wrap break-words">
            {inquiry.body}
          </div>
        </Card>

        {/* 답변 목록 */}
        {inquiry.replies && inquiry.replies.length > 0 && (
          <div className="space-y-3 mb-4">
            {inquiry.replies.map((reply) => (
              <Card key={reply.id} className="p-5 border-l-4 border-brand">
                <div className="flex items-center gap-2 mb-3">
                  <div className="w-7 h-7 rounded-full bg-brand flex items-center justify-center text-white text-[11px] font-bold shrink-0">
                    인
                  </div>
                  <div>
                    <span className="text-[13px] font-bold text-brand">인파 운영팀</span>
                    <span className="text-[11px] text-ink3 ml-2 tnum">{formatDate(reply.created_at)}</span>
                  </div>
                </div>
                <div className="text-[14px] text-ink leading-6 whitespace-pre-wrap break-words">
                  {reply.body}
                </div>
              </Card>
            ))}
          </div>
        )}

        {/* 답변 대기 중 안내 */}
        {inquiry.status === "open" && (
          <div className="p-4 rounded-xl bg-surface2 text-[13px] text-ink3 text-center">
            평균 답변 시간은 1~3 영업일이에요. 빠른 시일 내에 답변 드릴게요.
          </div>
        )}
      </main>
    </div>
  );
}
