"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AppNav } from "@/components/app-nav";
import { Card } from "@/components/ui";
import { useAuthGuard } from "@/lib/useAuthGuard";
import { createInquiry, type InquiryCategory } from "@/lib/api";

const CATEGORY_OPTIONS: { value: InquiryCategory; label: string }[] = [
  { value: "feature", label: "기능문의" },
  { value: "billing", label: "요금결제" },
  { value: "bug", label: "버그신고" },
  { value: "other", label: "기타" },
];

export default function InquiryNewPage() {
  const router = useRouter();
  const ready = useAuthGuard();

  const [category, setCategory] = useState<InquiryCategory>("feature");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!ready) return null;

  async function handleSubmit() {
    if (!title.trim()) {
      setError("제목을 입력해 주세요.");
      return;
    }
    if (!body.trim()) {
      setError("내용을 입력해 주세요.");
      return;
    }
    if (title.length > 200) {
      setError("제목은 200자 이내로 입력해 주세요.");
      return;
    }
    if (body.length > 3000) {
      setError("내용은 3,000자 이내로 입력해 주세요.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const inq = await createInquiry({ category, title: title.trim(), body: body.trim() });
      router.replace(`/boards/inquiry/${inq.id}`);
    } catch {
      setError("문의 등록 중 오류가 발생했어요. 잠시 후 다시 시도하세요.");
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-dvh">
      <AppNav active="board" />
      <main className="mx-auto max-w-2xl px-4 sm:px-6 py-6">
        <div className="flex items-center justify-between mb-5">
          <button onClick={() => router.back()} className="text-[13px] text-ink3 flex items-center gap-1 hover:text-ink transition">
            ‹ 취소
          </button>
          <h1 className="text-[17px] font-extrabold text-ink">1:1 문의</h1>
          <button
            onClick={handleSubmit}
            disabled={submitting || !title.trim() || !body.trim()}
            className="rounded-xl bg-brand text-white text-[13px] font-bold px-4 py-2 disabled:opacity-60"
          >
            {submitting ? "등록 중..." : "등록"}
          </button>
        </div>

        <Card className="p-4 space-y-4">
          {/* 카테고리 */}
          <div>
            <label className="block text-[12px] font-semibold text-ink3 mb-2">
              카테고리 <span className="text-danger">*</span>
            </label>
            <div className="grid grid-cols-2 gap-2">
              {CATEGORY_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setCategory(opt.value)}
                  className={`rounded-xl border py-2.5 text-[13px] font-semibold transition ${
                    category === opt.value
                      ? "bg-brand text-white border-brand"
                      : "bg-surface border-line text-ink2 hover:border-brand hover:text-brand"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* 제목 */}
          <div>
            <label className="block text-[12px] font-semibold text-ink3 mb-2">
              제목 <span className="text-danger">*</span>
            </label>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="문의 제목을 입력하세요"
              maxLength={200}
              className="w-full rounded-xl border border-line bg-surface px-4 py-2.5 text-[14px] text-ink placeholder:text-muted outline-none focus:border-brand"
            />
          </div>

          {/* 내용 */}
          <div>
            <label className="block text-[12px] font-semibold text-ink3 mb-2">
              내용 <span className="text-danger">*</span>
            </label>
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="문의 내용을 상세히 입력해 주세요"
              maxLength={3000}
              rows={10}
              className="w-full rounded-xl border border-line bg-surface px-4 py-3 text-[14px] text-ink placeholder:text-muted outline-none focus:border-brand resize-none leading-6"
            />
            <p className="text-right text-[11px] text-muted tnum mt-1">{body.length} / 3,000자</p>
          </div>

          <p className="text-[12px] text-ink3 bg-surface2 rounded-xl px-4 py-3">
            평균 답변 시간은 1~3 영업일이에요. 급한 문의는 본문에 연락처를 남겨주세요.
          </p>
        </Card>

        {error && (
          <div className="mt-4 p-3 rounded-xl bg-red-50 border border-red-200 text-[13px] text-red-700">
            {error}
          </div>
        )}
      </main>
    </div>
  );
}
