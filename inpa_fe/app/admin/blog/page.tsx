"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useAdminGuard } from "@/lib/useAdminGuard";
import {
  adminListBlogPosts,
  adminDeleteBlogPost,
  type BlogAdmin,
} from "@/lib/adminApi";
import { Card } from "@/components/ui";

type StatusFilter = "" | "published" | "draft";

function fmt(d: string | null): string {
  if (!d) return "-";
  return new Date(d).toLocaleDateString("ko-KR", { year: "numeric", month: "2-digit", day: "2-digit" });
}

const STATUS_TABS: { key: StatusFilter; label: string }[] = [
  { key: "", label: "전체" },
  { key: "published", label: "게시됨" },
  { key: "draft", label: "임시저장" },
];

export default function AdminBlogListPage() {
  const ready = useAdminGuard();
  const router = useRouter();

  const [posts, setPosts] = useState<BlogAdmin[]>([]);
  const [count, setCount] = useState(0);
  const [hasNext, setHasNext] = useState(false);
  const [hasPrev, setHasPrev] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<StatusFilter>("");
  const [page, setPage] = useState(1);

  const fetchPosts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await adminListBlogPosts({ status: status || undefined, page });
      setPosts(res.results);
      setCount(res.count);
      setHasNext(!!res.next);
      setHasPrev(!!res.previous);
    } catch {
      setError("블로그 목록을 불러오지 못했어요.");
    } finally {
      setLoading(false);
    }
  }, [status, page]);

  useEffect(() => {
    if (ready) fetchPosts();
  }, [ready, fetchPosts]);

  async function handleDelete(post: BlogAdmin) {
    if (!confirm(`'${post.title}' 글을 내릴까요? 공개 화면에서만 숨겨지고 기록은 보존돼요.`)) return;
    try {
      await adminDeleteBlogPost(post.id);
      await fetchPosts();
    } catch {
      alert("삭제에 실패했어요.");
    }
  }

  if (!ready) return null;

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-[22px] font-extrabold text-ink">블로그</h1>
        <button
          onClick={() => router.push("/admin/blog/new")}
          className="rounded-xl bg-brand px-4 py-2.5 text-[13px] font-bold text-white"
        >
          + 새 글
        </button>
      </div>

      {/* 상태 필터 */}
      <div className="mb-4 flex gap-2">
        {STATUS_TABS.map((t) => (
          <button
            key={t.key || "all"}
            onClick={() => {
              setStatus(t.key);
              setPage(1);
            }}
            className={`rounded-full px-3.5 py-1.5 text-[13px] font-semibold transition ${
              status === t.key
                ? "bg-brand text-white"
                : "border border-line bg-surface text-ink2 hover:border-brand"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {error && (
        <div className="mb-4 rounded-xl border border-line bg-danger-tint p-3 text-[13px] text-danger-ink">
          {error}
        </div>
      )}

      <Card>
        {loading ? (
          <div className="px-4 py-10 text-center text-[14px] text-ink3">불러오는 중...</div>
        ) : posts.length === 0 ? (
          <div className="px-4 py-12 text-center text-[13px] text-ink3">
            아직 글이 없어요. 오른쪽 위 &lsquo;새 글&rsquo;로 첫 글을 써보세요.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-[13px]">
              <thead>
                <tr className="border-b border-line text-left text-[12px] text-ink3">
                  <th className="px-4 py-3 font-semibold">제목</th>
                  <th className="px-3 py-3 font-semibold">카테고리</th>
                  <th className="px-3 py-3 font-semibold">상태</th>
                  <th className="px-3 py-3 font-semibold">게시일</th>
                  <th className="px-3 py-3 font-semibold text-right">조회</th>
                  <th className="px-4 py-3 font-semibold text-right">관리</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {posts.map((p) => (
                  <tr key={p.id} className="align-middle">
                    <td className="px-4 py-3">
                      <div className="font-semibold text-ink line-clamp-1">{p.title}</div>
                      <div className="mt-0.5 text-[11px] text-ink3">/blog/{p.slug}</div>
                    </td>
                    <td className="px-3 py-3 text-ink2 whitespace-nowrap">{p.category_label}</td>
                    <td className="px-3 py-3">
                      {p.is_published ? (
                        <span className="rounded-full bg-success-tint px-2 py-0.5 text-[11px] font-bold text-success-ink">
                          게시됨
                        </span>
                      ) : (
                        <span className="rounded-full bg-surface2 px-2 py-0.5 text-[11px] font-bold text-ink3">
                          임시저장
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-3 text-ink3 whitespace-nowrap">{fmt(p.published_at)}</td>
                    <td className="px-3 py-3 text-right text-ink2 tnum">{p.view_count.toLocaleString()}</td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-2.5 whitespace-nowrap">
                        <button
                          onClick={() => router.push(`/admin/blog/${p.id}/edit`)}
                          className="text-[12px] font-semibold text-brand hover:underline"
                        >
                          수정
                        </button>
                        {p.is_published && (
                          <a
                            href={`/blog/${p.slug}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-[12px] font-semibold text-ink2 hover:underline"
                          >
                            미리보기
                          </a>
                        )}
                        <button
                          onClick={() => handleDelete(p)}
                          className="text-[12px] font-semibold text-danger hover:underline"
                        >
                          내리기
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* 페이지네이션 */}
      {(hasPrev || hasNext) && (
        <div className="mt-5 flex items-center justify-center gap-3">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={!hasPrev}
            className="rounded-xl border border-line bg-surface px-4 py-2 text-[13px] font-semibold text-ink2 disabled:opacity-40"
          >
            ← 이전
          </button>
          <span className="text-[13px] font-semibold text-ink3">
            {page}쪽 · 전체 {count.toLocaleString()}건
          </span>
          <button
            onClick={() => setPage((p) => p + 1)}
            disabled={!hasNext}
            className="rounded-xl border border-line bg-surface px-4 py-2 text-[13px] font-semibold text-ink2 disabled:opacity-40"
          >
            다음 →
          </button>
        </div>
      )}
    </div>
  );
}
