"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { AppNav } from "@/components/app-nav";
import { Card } from "@/components/ui";
import { useAuthGuard } from "@/lib/useAuthGuard";
import { listInquiries, type InquiryListItem, type InquiryStatus } from "@/lib/api";

function relativeDate(iso: string): string {
  return new Date(iso).toLocaleDateString("ko-KR", { year: "numeric", month: "short", day: "numeric" });
}

const STATUS_META: Record<InquiryStatus, { label: string; color: string }> = {
  open: { label: "답변 대기", color: "text-warning" },
  answered: { label: "답변 완료", color: "text-success" },
  closed: { label: "완료", color: "text-ink3" },
};

const CATEGORY_LABELS: Record<string, string> = {
  feature: "기능문의",
  billing: "요금결제",
  bug: "버그신고",
  other: "기타",
};

export default function InquiryPage() {
  const ready = useAuthGuard();

  const [inquiries, setInquiries] = useState<InquiryListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function loadInquiries() {
    if (!ready) return;
    setLoading(true);
    setError(null);
    listInquiries()
      .then(setInquiries)
      .catch(() => setError("문의 목록을 불러오지 못했어요."))
      .finally(() => setLoading(false));
  }

  useEffect(() => { loadInquiries(); }, [ready]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!ready) return null;

  return (
    <div className="min-h-dvh">
      <AppNav active="board" />
      <main className="mx-auto max-w-5xl px-4 sm:px-6 py-6">
        <div className="flex items-center justify-between mb-5">
          <h1 className="text-[22px] font-extrabold text-ink">1:1 문의</h1>
          <Link
            href="/boards/inquiry/new"
            className="rounded-xl bg-brand text-white text-[13px] font-bold px-4 py-2.5"
          >
            + 새 문의
          </Link>
        </div>

        {loading && <div className="py-12 text-center text-[14px] text-ink3">불러오는 중...</div>}

        {error && (
          <div className="p-3 rounded-xl bg-danger-tint border border-line text-[13px] text-danger flex items-center justify-between">
            <span>{error}</span>
            <button onClick={loadInquiries} className="ml-3 font-semibold underline shrink-0">재시도</button>
          </div>
        )}

        {!loading && !error && inquiries.length === 0 && (
          <div className="py-12 text-center">
            <p className="text-[15px] font-semibold text-ink3 mb-2">아직 문의 내역이 없어요</p>
            <p className="text-[13px] text-muted mb-5">궁금한 점이 있으시면 언제든 문의해 주세요.</p>
            <Link href="/boards/inquiry/new" className="inline-block rounded-xl bg-brand text-white text-[14px] font-bold px-6 py-2.5">
              문의하기
            </Link>
          </div>
        )}

        <div className="space-y-3">
          {inquiries.map((inq) => (
            <Link key={inq.id} href={`/boards/inquiry/${inq.id}`}>
              <Card className="p-4 hover:border-brand/40 transition">
                <div className="flex items-start gap-3">
                  <span className="shrink-0 rounded-full bg-surface2 text-ink3 text-[11px] font-semibold px-2 py-0.5 mt-0.5">
                    {CATEGORY_LABELS[inq.category] ?? inq.category}
                  </span>
                  <div className="flex-1 min-w-0">
                    <p className="text-[14px] font-semibold text-ink truncate">{inq.title}</p>
                    <p className="text-[12px] text-ink3 mt-0.5 tnum">{relativeDate(inq.created_at)}</p>
                  </div>
                  <div className="shrink-0 flex items-center gap-1.5">
                    <span className={`text-[12px] font-semibold ${STATUS_META[inq.status].color}`}>
                      {STATUS_META[inq.status].label}
                    </span>
                    <span className="text-ink3 text-[16px]">›</span>
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
