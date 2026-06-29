"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AppNav } from "@/components/app-nav";
import { Card } from "@/components/ui";
import { useAuthGuard } from "@/lib/useAuthGuard";
import { createPost } from "@/lib/api";

const CATEGORIES = ["꿀팁", "질문", "모집", "정보공유"];

export default function BoardNewPage() {
  const router = useRouter();
  const ready = useAuthGuard();

  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [category, setCategory] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!ready) return null;

  async function handleSubmit() {
    if (!body.trim()) {
      setError("본문을 입력해 주세요.");
      return;
    }
    if (body.length > 5000) {
      setError("본문은 5,000자 이내로 작성해 주세요.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const post = await createPost({
        title: title.trim() || undefined,
        body: body.trim(),
        category: category || null,
      });
      router.replace(`/boards/${post.id}`);
    } catch {
      setError("게시글 등록 중 오류가 발생했어요. 잠시 후 다시 시도하세요.");
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
          <h1 className="text-[17px] font-extrabold text-ink">새 글쓰기</h1>
          <button
            onClick={handleSubmit}
            disabled={submitting || !body.trim()}
            className="rounded-xl bg-brand text-white text-[13px] font-bold px-4 py-2 disabled:opacity-60"
          >
            {submitting ? "등록 중..." : "등록"}
          </button>
        </div>

        <Card className="p-4 space-y-4">
          {/* 카테고리 */}
          <div>
            <label className="block text-[12px] font-semibold text-ink3 mb-2">카테고리 (선택)</label>
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => setCategory("")}
                className={`rounded-full px-3 py-1 text-[12px] font-semibold transition border ${
                  category === "" ? "bg-brand text-white border-brand" : "bg-surface border-line text-ink2 hover:border-brand hover:text-brand"
                }`}
              >
                없음
              </button>
              {CATEGORIES.map((cat) => (
                <button
                  key={cat}
                  onClick={() => setCategory(cat)}
                  className={`rounded-full px-3 py-1 text-[12px] font-semibold transition border ${
                    category === cat ? "bg-brand text-white border-brand" : "bg-surface border-line text-ink2 hover:border-brand hover:text-brand"
                  }`}
                >
                  {cat}
                </button>
              ))}
            </div>
          </div>

          {/* 제목 */}
          <div>
            <label className="block text-[12px] font-semibold text-ink3 mb-2">제목 (선택)</label>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="제목을 입력하세요"
              maxLength={200}
              className="w-full rounded-xl border border-line bg-surface px-4 py-2.5 text-[14px] text-ink placeholder:text-muted outline-none focus:border-brand"
            />
          </div>

          {/* 본문 */}
          <div>
            <label className="block text-[12px] font-semibold text-ink3 mb-2">
              본문 <span className="text-danger">*</span>
            </label>
            {/* 개인정보 경고 (컴플라이언스) */}
            <p className="text-[11px] text-muted mb-2">
              고객 개인정보(이름·생년·병력 등)를 포함하지 마세요.
            </p>
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="내용을 입력하세요"
              maxLength={5000}
              rows={12}
              className="w-full rounded-xl border border-line bg-surface px-4 py-3 text-[14px] text-ink placeholder:text-muted outline-none focus:border-brand resize-none leading-6"
            />
            <p className="text-right text-[11px] text-muted tnum mt-1">
              {body.length} / 5,000자
            </p>
          </div>
        </Card>

        {error && (
          <div className="mt-4 p-3 rounded-xl bg-danger-tint border border-line text-[13px] text-danger">
            {error}
          </div>
        )}
      </main>
    </div>
  );
}
