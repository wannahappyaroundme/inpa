"use client";

import { useState, useEffect, useCallback, useRef, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { AppNav } from "@/components/app-nav";
import { Card } from "@/components/ui";
import { useAuthGuard } from "@/lib/useAuthGuard";
import {
  listPosts,
  listNotices,
  toggleLike,
  reportContent,
  type PostFeedItem,
  type NoticeItem,
  type ReportReason,
} from "@/lib/api";

// ─── 날짜 포맷 ────────────────────────────────────────────────────────────────

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const min = Math.floor(diff / 60_000);
  if (min < 1) return "방금";
  if (min < 60) return `${min}분 전`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}시간 전`;
  const d = Math.floor(hr / 24);
  if (d < 7) return `${d}일 전`;
  return new Date(iso).toLocaleDateString("ko-KR", { month: "short", day: "numeric" });
}

// ─── 신고 모달 ────────────────────────────────────────────────────────────────

const REPORT_REASONS: { value: ReportReason; label: string }[] = [
  { value: "spam", label: "스팸 · 광고" },
  { value: "hate", label: "혐오 · 차별" },
  { value: "adult", label: "음란 · 불건전" },
  { value: "fake", label: "허위정보" },
  { value: "other", label: "기타" },
];

function ReportModal({
  target,
  onClose,
}: {
  target: { contentType: "post" | "comment"; objectId: number } | null;
  onClose: () => void;
}) {
  const [reason, setReason] = useState<ReportReason>("spam");
  const [detail, setDetail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (!target) return null;

  async function submit() {
    if (!target) return;
    setSubmitting(true);
    setErr(null);
    try {
      await reportContent({
        content_type: target.contentType,
        object_id: target.objectId,
        reason,
        detail: detail || undefined,
      });
      setDone(true);
    } catch {
      setErr("신고 접수 중 오류가 발생했어요. 잠시 후 다시 시도하세요.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onClose}
    >
      <div
        className="w-full max-w-sm mx-4 rounded-2xl bg-surface p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        {done ? (
          <>
            <p className="text-[15px] font-bold text-ink text-center">신고가 접수되었습니다</p>
            <p className="mt-2 text-[13px] text-ink3 text-center">검토 후 처리되며 결과는 별도로 안내되지 않아요.</p>
            <button
              onClick={onClose}
              className="mt-5 w-full rounded-xl bg-brand text-white font-bold py-2.5 text-[14px]"
            >
              확인
            </button>
          </>
        ) : (
          <>
            <p className="text-[16px] font-bold text-ink mb-4">신고 이유 선택</p>
            <div className="space-y-2">
              {REPORT_REASONS.map((r) => (
                <label key={r.value} className="flex items-center gap-3 cursor-pointer">
                  <input
                    type="radio"
                    name="reason"
                    value={r.value}
                    checked={reason === r.value}
                    onChange={() => setReason(r.value)}
                    className="accent-brand"
                  />
                  <span className="text-[14px] text-ink">{r.label}</span>
                </label>
              ))}
            </div>
            {reason === "other" && (
              <textarea
                value={detail}
                onChange={(e) => setDetail(e.target.value)}
                placeholder="신고 내용을 간략히 적어주세요 (선택)"
                className="mt-3 w-full rounded-xl border border-line bg-surface px-3 py-2 text-[13px] text-ink placeholder:text-muted outline-none focus:border-brand resize-none"
                rows={3}
                maxLength={300}
              />
            )}
            {err && <p className="mt-2 text-[13px] text-danger">{err}</p>}
            <div className="mt-4 flex gap-2">
              <button
                onClick={onClose}
                className="flex-1 rounded-xl border border-line text-ink2 font-semibold py-2.5 text-[14px]"
              >
                취소
              </button>
              <button
                onClick={submit}
                disabled={submitting}
                className="flex-1 rounded-xl bg-danger text-white font-bold py-2.5 text-[14px] disabled:opacity-60"
              >
                {submitting ? "접수 중..." : "신고하기"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ─── PostCard ────────────────────────────────────────────────────────────────

function PostCard({
  post,
  currentUserId,
  onLike,
  onReport,
  onDelete,
}: {
  post: PostFeedItem;
  currentUserId: number | null;
  onLike: (id: number) => void;
  onReport: (contentType: "post", objectId: number) => void;
  onDelete: (id: number) => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const isOwn = currentUserId !== null && post.author.id === currentUserId;

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    }
    if (menuOpen) document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [menuOpen]);

  return (
    <Card className="p-4">
      {/* 헤더 */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="w-9 h-9 rounded-full bg-accent-tint flex items-center justify-center text-[14px] font-bold text-brand shrink-0">
            {post.author.display_name[0] ?? "?"}
          </div>
          <div className="min-w-0">
            <p className="text-[13px] font-semibold text-ink truncate">{post.author.display_name}</p>
            <p className="text-[11px] text-ink3 tnum">{relativeTime(post.created_at)}{post.is_edited && " · 수정됨"}</p>
          </div>
        </div>

        {/* 더보기 메뉴 */}
        <div className="relative shrink-0" ref={menuRef}>
          <button
            onClick={() => setMenuOpen((v) => !v)}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-ink3 hover:bg-surface2 text-[18px]"
            aria-label="더보기"
          >
            ⋯
          </button>
          {menuOpen && (
            <div className="absolute right-0 top-9 z-20 w-32 rounded-xl bg-surface border border-line shadow-lg py-1">
              {isOwn ? (
                <>
                  <Link
                    href={`/boards/${post.id}/edit`}
                    className="block px-4 py-2 text-[13px] text-ink hover:bg-surface2"
                    onClick={() => setMenuOpen(false)}
                  >
                    수정
                  </Link>
                  <button
                    onClick={() => { setMenuOpen(false); onDelete(post.id); }}
                    className="w-full text-left px-4 py-2 text-[13px] text-danger hover:bg-surface2"
                  >
                    삭제
                  </button>
                </>
              ) : (
                <button
                  onClick={() => { setMenuOpen(false); onReport("post", post.id); }}
                  className="w-full text-left px-4 py-2 text-[13px] text-danger hover:bg-surface2"
                >
                  신고
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      {/* 본문 */}
      <Link href={`/boards/${post.id}`} className="block mt-3">
        {post.title && (
          <p className="text-[15px] font-bold text-ink line-clamp-1 mb-1">{post.title}</p>
        )}
        {post.body_preview && (
          <p className="text-[13px] text-ink2 leading-5 line-clamp-3">{post.body_preview}</p>
        )}
        {post.thumbnail_url && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={post.thumbnail_url}
            alt=""
            className="mt-2 w-full max-h-48 object-cover rounded-xl"
          />
        )}
      </Link>

      {/* 푸터 */}
      <div className="mt-3 pt-3 border-t border-line flex items-center gap-4 text-[12px] text-ink3">
        <button
          onClick={() => onLike(post.id)}
          className="flex items-center gap-1 hover:text-brand transition"
        >
          <span>♡</span>
          <span className="tnum">{post.like_count}</span>
        </button>
        <Link href={`/boards/${post.id}`} className="flex items-center gap-1 hover:text-brand transition">
          <span>💬</span>
          <span className="tnum">{post.comment_count}</span>
        </Link>
        <span className="flex items-center gap-1">
          <span>조회</span>
          <span className="tnum">{post.view_count}</span>
        </span>
        {post.category && (
          <span className="ml-auto rounded-full bg-accent-tint text-brand px-2 py-0.5 text-[11px] font-semibold">
            {post.category}
          </span>
        )}
      </div>
    </Card>
  );
}

// ─── 카테고리 칩 ──────────────────────────────────────────────────────────────

const CATEGORIES = ["전체", "꿀팁", "질문", "모집", "정보공유"];

// ─── 탭 서브네비 ──────────────────────────────────────────────────────────────

type BoardTab = "feed" | "notice" | "faq";

function SubTabs({ active }: { active: BoardTab }) {
  const tabs: { key: BoardTab; label: string; href: string }[] = [
    { key: "feed", label: "게시판", href: "/boards" },
    { key: "notice", label: "공지사항", href: "/boards/notice" },
    { key: "faq", label: "FAQ", href: "/boards/faq" },
  ];
  return (
    <div className="flex border-b border-line mb-4">
      {tabs.map((t) => (
        <Link
          key={t.key}
          href={t.href}
          className={`px-4 py-2.5 text-[13px] font-semibold border-b-2 transition ${
            active === t.key
              ? "border-brand text-brand"
              : "border-transparent text-ink3 hover:text-ink"
          }`}
        >
          {t.label}
        </Link>
      ))}
    </div>
  );
}

// ─── 피드 내부 컴포넌트 (useSearchParams 분리) ───────────────────────────────

function BoardFeedContent() {
  const searchParams = useSearchParams();
  const ready = useAuthGuard();

  const [posts, setPosts] = useState<PostFeedItem[]>([]);
  const [pinnedPosts, setPinnedPosts] = useState<PostFeedItem[]>([]);
  const [pinnedNotices, setPinnedNotices] = useState<NoticeItem[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [selectedCategory, setSelectedCategory] = useState<string>("전체");
  const [search, setSearch] = useState(searchParams.get("q") ?? "");
  const [searchInput, setSearchInput] = useState(search);

  const [reportTarget, setReportTarget] = useState<{ contentType: "post" | "comment"; objectId: number } | null>(null);
  const [currentUserId] = useState<number | null>(null); // 실제 구현 시 getProfile에서 주입

  // 피드 초기 로드
  const loadFeed = useCallback(async (cat: string, q: string) => {
    setLoading(true);
    setError(null);
    try {
      const params: Parameters<typeof listPosts>[0] = {};
      if (cat !== "전체") params.cursor = undefined;
      const res = await listPosts(params);
      const pinned = res.results.filter((p) => p.is_pinned);
      const normal = res.results.filter((p) => !p.is_pinned);
      const filtered = normal.filter((p) => {
        const catMatch = cat === "전체" || p.category === cat;
        const qMatch = !q || p.title.includes(q) || p.body_preview.includes(q);
        return catMatch && qMatch;
      });
      setPinnedPosts(pinned);
      setPosts(filtered);
      setNextCursor(res.next_cursor);
    } catch {
      setError("게시글을 불러오지 못했어요. 잠시 후 다시 시도하세요.");
    } finally {
      setLoading(false);
    }
  }, []);

  // 공지 핀 로드 (AllowAny — 비로그인도 가능)
  useEffect(() => {
    listNotices()
      .then((list) => setPinnedNotices(list.filter((n) => n.is_pinned && n.is_published).slice(0, 3)))
      .catch(() => setPinnedNotices([]));
  }, []);

  useEffect(() => {
    if (!ready) return;
    loadFeed(selectedCategory, search);
  }, [ready, selectedCategory, search, loadFeed]);

  // 검색 디바운스
  useEffect(() => {
    const id = setTimeout(() => setSearch(searchInput), 500);
    return () => clearTimeout(id);
  }, [searchInput]);

  async function handleLoadMore() {
    if (!nextCursor || loadingMore) return;
    setLoadingMore(true);
    try {
      const res = await listPosts({ cursor: nextCursor });
      const more = res.results.filter((p) => !p.is_pinned);
      setPosts((prev) => [...prev, ...more]);
      setNextCursor(res.next_cursor);
    } catch {
      // 무한스크롤 실패 시 조용히 무시
    } finally {
      setLoadingMore(false);
    }
  }

  async function handleLike(postId: number) {
    try {
      const res = await toggleLike(postId);
      setPosts((prev) =>
        prev.map((p) => (p.id === postId ? { ...p, like_count: res.like_count } : p))
      );
    } catch {
      // 좋아요 실패 — 조용히 무시
    }
  }

  async function handleDelete(postId: number) {
    if (!confirm("이 게시글을 삭제할까요?")) return;
    try {
      const { deletePost } = await import("@/lib/api");
      await deletePost(postId);
      setPosts((prev) => prev.filter((p) => p.id !== postId));
    } catch {
      alert("삭제 중 오류가 발생했어요. 잠시 후 다시 시도하세요.");
    }
  }

  if (!ready) return null;

  return (
    <>
      {/* 서브탭 */}
      <SubTabs active="feed" />

      {/* 공지 핀 배너 */}
      {pinnedNotices.length > 0 && (
        <div className="mb-4 space-y-2">
          {pinnedNotices.map((n) => (
            <Link
              key={n.id}
              href={`/boards/notice/${n.id}`}
              className="flex items-center gap-2 rounded-xl bg-accent-tint border border-accent-tint px-4 py-2.5 text-[13px] text-brand font-semibold"
            >
              <span className="shrink-0">📌</span>
              <span className="truncate">{n.title}</span>
            </Link>
          ))}
        </div>
      )}

      {/* 검색 */}
      <div className="mb-4">
        <input
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          placeholder="게시글 검색"
          className="w-full rounded-xl border border-line bg-surface px-4 py-2.5 text-[14px] text-ink placeholder:text-muted outline-none focus:border-brand"
        />
      </div>

      {/* 카테고리 칩 */}
      <div className="flex gap-2 overflow-x-auto pb-1 mb-4 scrollbar-none">
        {CATEGORIES.map((cat) => (
          <button
            key={cat}
            onClick={() => setSelectedCategory(cat)}
            className={`shrink-0 rounded-full px-3.5 py-1.5 text-[12px] font-semibold transition ${
              selectedCategory === cat
                ? "bg-brand text-white"
                : "bg-surface border border-line text-ink2 hover:border-brand hover:text-brand"
            }`}
          >
            {cat}
          </button>
        ))}
      </div>

      {/* 고정 게시글 */}
      {pinnedPosts.length > 0 && (
        <div className="mb-4 space-y-3">
          {pinnedPosts.map((p) => (
            <PostCard
              key={p.id}
              post={p}
              currentUserId={currentUserId}
              onLike={handleLike}
              onReport={(ct, id) => setReportTarget({ contentType: ct, objectId: id })}
              onDelete={handleDelete}
            />
          ))}
        </div>
      )}

      {/* 에러 */}
      {error && (
        <div className="mb-4 p-3 rounded-xl bg-red-50 border border-red-200 text-[13px] text-red-700">
          {error}
        </div>
      )}

      {/* 로딩 */}
      {loading && !posts.length && (
        <div className="py-12 text-center text-[14px] text-ink3">불러오는 중...</div>
      )}

      {/* 빈 상태 */}
      {!loading && !error && posts.length === 0 && (
        <div className="py-12 text-center">
          <p className="text-[15px] font-semibold text-ink3 mb-2">아직 게시글이 없어요</p>
          <p className="text-[13px] text-muted mb-5">첫 글을 써보세요</p>
          <Link
            href="/boards/new"
            className="inline-block rounded-xl bg-brand text-white text-[14px] font-bold px-6 py-2.5"
          >
            글쓰기
          </Link>
        </div>
      )}

      {/* 게시글 목록 */}
      <div className="space-y-3">
        {posts.map((p) => (
          <PostCard
            key={p.id}
            post={p}
            currentUserId={currentUserId}
            onLike={handleLike}
            onReport={(ct, id) => setReportTarget({ contentType: ct, objectId: id })}
            onDelete={handleDelete}
          />
        ))}
      </div>

      {/* 더 보기 */}
      {nextCursor && (
        <div className="mt-5 text-center">
          <button
            onClick={handleLoadMore}
            disabled={loadingMore}
            className="rounded-xl border border-line text-[13px] font-semibold text-brand px-6 py-2.5 hover:bg-accent-tint transition disabled:opacity-60"
          >
            {loadingMore ? "불러오는 중..." : "더 보기"}
          </button>
        </div>
      )}

      {/* 신고 모달 */}
      <ReportModal
        target={reportTarget}
        onClose={() => setReportTarget(null)}
      />
    </>
  );
}

// ─── 페이지 (Suspense 래핑) ──────────────────────────────────────────────────

export default function BoardsPage() {
  return (
    <div className="min-h-dvh">
      <AppNav active="board" />
      <main className="mx-auto max-w-5xl px-4 sm:px-6 py-6">
        <div className="flex items-center justify-between mb-5">
          <h1 className="text-[22px] font-extrabold text-ink">게시판</h1>
          <Link
            href="/boards/new"
            className="rounded-xl bg-brand text-white text-[13px] font-bold px-4 py-2.5"
          >
            ✎ 글쓰기
          </Link>
        </div>
        <Suspense fallback={<div className="py-12 text-center text-[14px] text-ink3">불러오는 중...</div>}>
          <BoardFeedContent />
        </Suspense>
      </main>
    </div>
  );
}
