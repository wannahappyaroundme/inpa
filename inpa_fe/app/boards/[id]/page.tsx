"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { AppNav } from "@/components/app-nav";
import { Card } from "@/components/ui";
import { useAuthGuard } from "@/lib/useAuthGuard";
import {
  getPost,
  listComments,
  createComment,
  updateComment,
  deleteComment,
  toggleLike,
  reportContent,
  deletePost,
  getProfile,
  type PostDetail,
  type CommentItem,
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

// ─── 신고 이유 ────────────────────────────────────────────────────────────────

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

  useEffect(() => {
    if (!target) { setDone(false); setErr(null); setDetail(""); setReason("spam"); }
  }, [target]);

  if (!target) return null;

  async function submit() {
    if (!target) return;
    setSubmitting(true);
    setErr(null);
    try {
      await reportContent({ content_type: target.contentType, object_id: target.objectId, reason, detail: detail || undefined });
      setDone(true);
    } catch {
      setErr("신고 접수 중 오류가 발생했어요.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="w-full max-w-sm mx-4 rounded-2xl bg-surface p-5 shadow-card" onClick={(e) => e.stopPropagation()}>
        {done ? (
          <>
            <p className="text-[15px] font-bold text-ink text-center">신고가 접수되었습니다</p>
            <p className="mt-2 text-[13px] text-ink3 text-center">검토 후 처리되며 결과는 별도 안내되지 않아요.</p>
            <button onClick={onClose} className="mt-5 w-full rounded-xl bg-brand text-white font-bold py-2.5 text-[14px]">확인</button>
          </>
        ) : (
          <>
            <p className="text-[16px] font-bold text-ink mb-4">신고 이유 선택</p>
            <div className="space-y-2">
              {REPORT_REASONS.map((r) => (
                <label key={r.value} className="flex items-center gap-3 cursor-pointer">
                  <input type="radio" name="reason" value={r.value} checked={reason === r.value} onChange={() => setReason(r.value)} className="accent-brand" />
                  <span className="text-[14px] text-ink">{r.label}</span>
                </label>
              ))}
            </div>
            {reason === "other" && (
              <textarea value={detail} onChange={(e) => setDetail(e.target.value)} placeholder="내용을 간략히 적어주세요 (선택)" className="mt-3 w-full rounded-xl border border-line bg-surface px-3 py-2 text-[13px] text-ink placeholder:text-muted outline-none focus:border-brand resize-none" rows={3} maxLength={300} />
            )}
            {err && <p className="mt-2 text-[13px] text-danger">{err}</p>}
            <div className="mt-4 flex gap-2">
              <button onClick={onClose} className="flex-1 rounded-xl border border-line text-ink2 font-semibold py-2.5 text-[14px]">취소</button>
              <button onClick={submit} disabled={submitting} className="flex-1 rounded-xl bg-danger text-white font-bold py-2.5 text-[14px] disabled:opacity-60">{submitting ? "접수 중..." : "신고하기"}</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ─── 댓글 카드 ───────────────────────────────────────────────────────────────

function CommentCard({
  comment,
  depth,
  currentUserId,
  onReply,
  onEdit,
  onDelete,
  onReport,
}: {
  comment: CommentItem;
  depth: number;
  currentUserId: number | null;
  onReply: (parentId: number, parentAuthor: string) => void;
  onEdit: (id: number, body: string) => void;
  onDelete: (id: number) => void;
  onReport: (id: number) => void;
}) {
  const isOwn = currentUserId !== null && comment.author.id === currentUserId;
  const deleted = comment.is_deleted;

  return (
    <div className={depth > 0 ? "ml-8 border-l-2 border-line pl-3" : ""}>
      <div className="py-3">
        {deleted ? (
          <p className="text-[13px] text-ink3 italic">삭제된 댓글입니다.</p>
        ) : (
          <>
            <div className="flex items-center gap-2 mb-1">
              <div className="w-7 h-7 rounded-full bg-accent-tint flex items-center justify-center text-[11px] font-bold text-brand shrink-0">
                {comment.author.display_name[0] ?? "?"}
              </div>
              <span className="text-[13px] font-semibold text-ink">{comment.author.display_name}</span>
              <span className="text-[11px] text-ink3 tnum">{relativeTime(comment.created_at)}</span>
              {comment.is_deleted === false && comment.updated_at !== comment.created_at && (
                <span className="text-[11px] text-ink3">· 수정됨</span>
              )}
            </div>
            <p className="text-[13px] text-ink leading-5 ml-9">{comment.body}</p>
            <div className="flex gap-3 ml-9 mt-1.5 text-[12px] text-ink3">
              {depth === 0 && (
                <button onClick={() => onReply(comment.id, comment.author.display_name)} className="hover:text-brand transition">
                  답글
                </button>
              )}
              {isOwn ? (
                <>
                  <button onClick={() => onEdit(comment.id, comment.body)} className="hover:text-brand transition">수정</button>
                  <button onClick={() => onDelete(comment.id)} className="hover:text-danger transition">삭제</button>
                </>
              ) : (
                <button onClick={() => onReport(comment.id)} className="hover:text-danger transition">신고</button>
              )}
            </div>
          </>
        )}
      </div>
      {/* 대댓글 (1단계) */}
      {comment.replies?.map((reply) => (
        <CommentCard
          key={reply.id}
          comment={reply}
          depth={depth + 1}
          currentUserId={currentUserId}
          onReply={onReply}
          onEdit={onEdit}
          onDelete={onDelete}
          onReport={onReport}
        />
      ))}
    </div>
  );
}

// ─── 게시글 상세 페이지 ──────────────────────────────────────────────────────

export default function PostDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const ready = useAuthGuard();

  const postId = Number(params.id);

  const [post, setPost] = useState<PostDetail | null>(null);
  const [comments, setComments] = useState<CommentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [liked, setLiked] = useState(false);
  const [likeCount, setLikeCount] = useState(0);

  const [commentBody, setCommentBody] = useState("");
  const [replyTo, setReplyTo] = useState<{ id: number; author: string } | null>(null);
  const [editingComment, setEditingComment] = useState<{ id: number; body: string } | null>(null);
  const [submittingComment, setSubmittingComment] = useState(false);

  const [currentUserId, setCurrentUserId] = useState<number | null>(null);
  const [reportTarget, setReportTarget] = useState<{ contentType: "post" | "comment"; objectId: number } | null>(null);

  useEffect(() => {
    if (!ready) return;
    getProfile().then((p) => {
      // email을 id로 쓸 수 없으므로 author.id 비교용 — 실제로는 BE에서 user.id를 반환해야 함
      // 현재 ProfileResponse에 id 필드 없음 → null 유지 (본인 여부 판단 불가 — graceful)
      setCurrentUserId(null);
    }).catch(() => {});
  }, [ready]);

  useEffect(() => {
    if (!ready || !postId) return;
    setLoading(true);
    Promise.all([getPost(postId), listComments(postId)])
      .then(([p, c]) => {
        setPost(p);
        setLikeCount(p.like_count);
        setComments(c);
      })
      .catch((e) => {
        if (e?.status === 404) {
          setError("존재하지 않는 게시글이에요.");
        } else {
          setError("게시글을 불러오지 못했어요.");
        }
      })
      .finally(() => setLoading(false));
  }, [ready, postId]);

  async function handleLike() {
    try {
      const res = await toggleLike(postId);
      setLiked(res.liked);
      setLikeCount(res.like_count);
    } catch {
      // 조용히 무시
    }
  }

  async function handleCommentSubmit() {
    if (!commentBody.trim()) return;
    setSubmittingComment(true);
    try {
      if (editingComment) {
        const updated = await updateComment(editingComment.id, commentBody);
        setComments((prev) => prev.map((c) => {
          if (c.id === updated.id) return updated;
          const replies = c.replies?.map((r) => r.id === updated.id ? updated : r);
          return { ...c, replies: replies ?? c.replies };
        }));
        setEditingComment(null);
      } else {
        const created = await createComment(postId, { body: commentBody, parent: replyTo?.id ?? null });
        if (replyTo) {
          setComments((prev) => prev.map((c) =>
            c.id === replyTo.id ? { ...c, replies: [...(c.replies ?? []), created] } : c
          ));
        } else {
          setComments((prev) => [...prev, { ...created, replies: [] }]);
        }
        setReplyTo(null);
      }
      setCommentBody("");
    } catch {
      alert("댓글 처리 중 오류가 발생했어요.");
    } finally {
      setSubmittingComment(false);
    }
  }

  async function handleDeleteComment(id: number) {
    if (!confirm("댓글을 삭제할까요?")) return;
    try {
      await deleteComment(id);
      setComments((prev) => prev.map((c) => {
        if (c.id === id) return { ...c, is_deleted: true, body: "" };
        const replies = c.replies?.map((r) => r.id === id ? { ...r, is_deleted: true, body: "" } : r);
        return { ...c, replies: replies ?? c.replies };
      }));
    } catch {
      alert("삭제 중 오류가 발생했어요.");
    }
  }

  async function handleDeletePost() {
    if (!confirm("이 게시글을 삭제할까요?")) return;
    try {
      await deletePost(postId);
      router.replace("/boards");
    } catch {
      alert("삭제 중 오류가 발생했어요.");
    }
  }

  if (!ready) return null;

  if (loading) {
    return (
      <div className="min-h-dvh">
        <AppNav active="board" />
        <main className="mx-auto max-w-[1440px] px-4 sm:px-6 py-6">
          <div className="py-12 text-center text-[14px] text-ink3">불러오는 중...</div>
        </main>
      </div>
    );
  }

  if (error || !post) {
    return (
      <div className="min-h-dvh">
        <AppNav active="board" />
        <main className="mx-auto max-w-[1440px] px-4 sm:px-6 py-6">
          <button onClick={() => router.back()} className="text-[13px] text-ink3 mb-4 flex items-center gap-1">‹ 뒤로</button>
          <div className="py-12 text-center">
            <p className="text-[15px] font-semibold text-ink3">{error ?? "게시글을 찾을 수 없어요."}</p>
            <Link href="/boards" className="mt-4 inline-block text-[13px] text-brand">게시판으로 돌아가기</Link>
          </div>
        </main>
      </div>
    );
  }

  const isOwn = currentUserId !== null && post.author.id === currentUserId;

  return (
    <div className="min-h-dvh">
      <AppNav active="board" />
      <main className="mx-auto max-w-[1440px] px-4 sm:px-6 py-6">
        {/* 상단 */}
        <div className="flex items-center justify-between mb-5">
          <button onClick={() => router.back()} className="text-[13px] text-ink3 flex items-center gap-1 hover:text-ink transition">
            ‹ 뒤로
          </button>
          {isOwn ? (
            <div className="flex gap-2 text-[13px]">
              <Link href={`/boards/${post.id}/edit`} className="text-brand font-semibold">수정</Link>
              <button onClick={handleDeletePost} className="text-danger font-semibold">삭제</button>
            </div>
          ) : (
            <button onClick={() => setReportTarget({ contentType: "post", objectId: post.id })} className="text-[13px] text-ink3 hover:text-danger transition">신고</button>
          )}
        </div>

        {/* 게시글 본문 */}
        <Card className="p-5 mb-4">
          {/* 카테고리 */}
          {post.category && (
            <span className="inline-block rounded-full bg-accent-tint text-brand px-3 py-0.5 text-[11px] font-semibold mb-3">{post.category}</span>
          )}

          {/* 제목 */}
          {post.title && (
            <h1 className="text-[20px] font-extrabold text-ink mb-2">{post.title}</h1>
          )}

          {/* 저자 정보 */}
          <div className="flex items-center gap-2.5 mb-4 pb-4 border-b border-line">
            <div className="w-9 h-9 rounded-full bg-accent-tint flex items-center justify-center text-[14px] font-bold text-brand shrink-0">
              {post.author.display_name[0] ?? "?"}
            </div>
            <div>
              <p className="text-[13px] font-semibold text-ink">{post.author.display_name}</p>
              <p className="text-[11px] text-ink3 tnum">
                {relativeTime(post.created_at)}
                {post.is_edited && " · 수정됨"}
                {" · 조회 "}{post.view_count}
              </p>
            </div>
          </div>

          {/* 본문 — XSS: 텍스트만 렌더, dangerouslySetInnerHTML 사용 안 함 */}
          <div className="text-[14px] text-ink leading-6 whitespace-pre-wrap break-words">
            {post.body}
          </div>

          {/* 첨부 파일 */}
          {post.attachments && post.attachments.length > 0 && (
            <div className="mt-4 space-y-2">
              {post.attachments.map((att) => (
                att.mime_type.startsWith("image/") ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img key={att.id} src={att.file_url} alt={att.file_name} className="w-full rounded-xl max-h-96 object-cover" />
                ) : (
                  <a key={att.id} href={att.file_url} download={att.file_name} className="flex items-center gap-2 p-3 rounded-xl border border-line text-[13px] text-brand hover:bg-accent-tint transition">
                    📎 {att.file_name}
                  </a>
                )
              ))}
            </div>
          )}

          {/* 좋아요 */}
          <div className="mt-5 pt-4 border-t border-line flex items-center gap-2">
            <button
              onClick={handleLike}
              className={`flex items-center gap-1.5 rounded-xl border px-4 py-2 text-[14px] font-semibold transition ${liked ? "border-brand bg-accent-tint text-brand" : "border-line text-ink3 hover:border-brand hover:text-brand"}`}
            >
              {liked ? "♥" : "♡"} <span className="tnum">{likeCount}</span>
            </button>
            <span className="text-[13px] text-ink3">💬 {post.comment_count}</span>
          </div>
        </Card>

        {/* 댓글 목록 */}
        <Card className="p-4 mb-4">
          <p className="text-[15px] font-bold text-ink mb-2">
            댓글 <span className="tnum text-ink3">{post.comment_count}</span>
          </p>
          {comments.length === 0 && (
            <p className="text-[13px] text-ink3 py-4 text-center">아직 댓글이 없어요. 첫 댓글을 달아보세요.</p>
          )}
          <div className="divide-y divide-line">
            {comments.map((c) => (
              <CommentCard
                key={c.id}
                comment={c}
                depth={0}
                currentUserId={currentUserId}
                onReply={(id, author) => { setReplyTo({ id, author }); setEditingComment(null); setCommentBody(""); }}
                onEdit={(id, body) => { setEditingComment({ id, body }); setCommentBody(body); setReplyTo(null); }}
                onDelete={handleDeleteComment}
                onReport={(id) => setReportTarget({ contentType: "comment", objectId: id })}
              />
            ))}
          </div>
        </Card>

        {/* 댓글 입력 */}
        <Card className="p-4 sticky bottom-4">
          {(replyTo || editingComment) && (
            <div className="flex items-center justify-between mb-2 text-[12px] text-ink3 bg-surface2 rounded-xl px-3 py-1.5">
              <span>
                {editingComment ? "댓글 수정 중" : `@${replyTo?.author}에게 답글`}
              </span>
              <button
                onClick={() => { setReplyTo(null); setEditingComment(null); setCommentBody(""); }}
                className="text-ink3 hover:text-danger"
              >
                ✕
              </button>
            </div>
          )}

          {/* 개인정보 경고 문구 (컴플라이언스) */}
          <p className="text-[11px] text-muted mb-2">고객 개인정보(이름·생년·병력 등)를 포함하지 마세요.</p>

          <div className="flex gap-2">
            <textarea
              value={commentBody}
              onChange={(e) => setCommentBody(e.target.value)}
              placeholder="댓글을 입력하세요"
              className="flex-1 rounded-xl border border-line bg-surface px-3 py-2.5 text-[13px] text-ink placeholder:text-muted outline-none focus:border-brand resize-none"
              rows={2}
              maxLength={2000}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) handleCommentSubmit();
              }}
            />
            <button
              onClick={handleCommentSubmit}
              disabled={!commentBody.trim() || submittingComment}
              className="rounded-xl bg-brand text-white text-[13px] font-bold px-4 disabled:opacity-60 shrink-0"
            >
              {submittingComment ? "..." : "등록"}
            </button>
          </div>
        </Card>

        {/* 신고 모달 */}
        <ReportModal target={reportTarget} onClose={() => setReportTarget(null)} />
      </main>
    </div>
  );
}
