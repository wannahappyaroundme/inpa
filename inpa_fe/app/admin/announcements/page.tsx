"use client";

import { useState, useEffect } from "react";
import { useAdminGuard } from "@/lib/useAdminGuard";
import { adminCreateNotice, adminUpdateNotice, adminDeleteNotice } from "@/lib/adminApi";
import { listNotices, type NoticeItem } from "@/lib/api";
import { Card } from "@/components/ui";

function fmt(d: string | null): string {
  if (!d) return "임시저장";
  return new Date(d).toLocaleDateString("ko-KR", { year: "numeric", month: "2-digit", day: "2-digit" });
}

export default function AdminAnnouncementsPage() {
  const ready = useAdminGuard();

  const [notices, setNotices] = useState<NoticeItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [editing, setEditing] = useState<NoticeItem | null>(null);
  const [isNew, setIsNew] = useState(false);

  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [isPinned, setIsPinned] = useState(false);
  const [isPublished, setIsPublished] = useState(false);
  const [saving, setSaving] = useState(false);

  async function fetchNotices() {
    setLoading(true);
    setError(null);
    try {
      const res = await listNotices();
      setNotices(res);
    } catch {
      setError("공지사항을 불러오지 못했어요.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { if (ready) fetchNotices(); }, [ready]);

  function openNew() {
    setEditing(null);
    setIsNew(true);
    setTitle("");
    setBody("");
    setIsPinned(false);
    setIsPublished(false);
  }

  function openEdit(n: NoticeItem) {
    setIsNew(false);
    setEditing(n);
    setTitle(n.title);
    setBody(n.body);
    setIsPinned(n.is_pinned);
    setIsPublished(n.is_published);
  }

  function closeForm() {
    setEditing(null);
    setIsNew(false);
  }

  async function handleSave() {
    setSaving(true);
    try {
      if (isNew) {
        await adminCreateNotice({
          title,
          body,
          is_pinned: isPinned,
          is_published: isPublished,
          published_at: isPublished ? new Date().toISOString() : null,
        });
      } else if (editing) {
        await adminUpdateNotice(editing.id, {
          title,
          body,
          is_pinned: isPinned,
          is_published: isPublished,
        });
      }
      closeForm();
      await fetchNotices();
    } catch {
      alert("저장에 실패했어요.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: number) {
    if (!confirm("삭제하시겠어요? 설계사 화면에서 비노출됩니다.")) return;
    try {
      await adminDeleteNotice(id);
      await fetchNotices();
    } catch {
      alert("삭제에 실패했어요.");
    }
  }

  if (!ready) return null;

  const showForm = isNew || editing !== null;

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-[22px] font-extrabold text-ink">공지사항</h1>
        <button
          onClick={openNew}
          className="rounded-xl bg-brand text-white text-[13px] font-bold px-4 py-2.5"
        >
          + 공지 작성
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 rounded-xl bg-danger-tint border border-line text-[13px] text-danger-ink">{error}</div>
      )}

      <div className="flex flex-col lg:flex-row gap-5">
        {/* 목록 */}
        <div className="flex-1 min-w-0">
          {loading && <div className="text-[14px] text-ink3">불러오는 중...</div>}
          {!loading && (
            <Card>
              <div className="divide-y divide-line">
                {notices.length === 0 && (
                  <div className="px-4 py-8 text-center text-[13px] text-ink3">공지사항이 없어요.</div>
                )}
                {notices.map((n) => (
                  <div key={n.id} className="flex items-center px-4 py-3.5 gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                        {n.is_pinned && (
                          <span className="text-[10px] font-bold rounded-full px-2 py-0.5 bg-brand text-white">고정</span>
                        )}
                        {!n.is_published && (
                          <span className="text-[10px] font-bold rounded-full px-2 py-0.5 bg-surface2 text-ink3">임시저장</span>
                        )}
                        <span className="text-[14px] font-semibold text-ink truncate">{n.title}</span>
                      </div>
                      <div className="text-[12px] text-ink3">
                        {fmt(n.published_at ?? null)}
                      </div>
                    </div>
                    <div className="flex gap-2 shrink-0">
                      <button
                        onClick={() => openEdit(n)}
                        className="text-[12px] font-semibold text-brand hover:underline"
                      >
                        수정
                      </button>
                      <button
                        onClick={() => handleDelete(n.id)}
                        className="text-[12px] font-semibold text-danger hover:underline"
                      >
                        삭제
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>

        {/* 편집 폼 */}
        {showForm && (
          <div className="w-96 shrink-0">
            <Card className="p-5">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-[15px] font-bold text-ink">
                  {isNew ? "새 공지 작성" : "공지 수정"}
                </h2>
                <button onClick={closeForm} className="text-ink3 text-[18px] leading-none hover:text-ink">×</button>
              </div>
              <div className="space-y-3">
                <div>
                  <label className="block text-[12px] font-semibold text-ink3 mb-1">제목</label>
                  <input
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-[14px] text-ink outline-none focus:border-brand"
                  />
                </div>
                <div>
                  <label className="block text-[12px] font-semibold text-ink3 mb-1">본문</label>
                  <textarea
                    value={body}
                    onChange={(e) => setBody(e.target.value)}
                    rows={6}
                    className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-[13px] text-ink outline-none focus:border-brand resize-none"
                  />
                </div>
                <label className="flex items-center gap-2 text-[13px] text-ink cursor-pointer">
                  <input type="checkbox" checked={isPinned} onChange={(e) => setIsPinned(e.target.checked)} />
                  상단 고정
                </label>
                <label className="flex items-center gap-2 text-[13px] text-ink cursor-pointer">
                  <input type="checkbox" checked={isPublished} onChange={(e) => setIsPublished(e.target.checked)} />
                  즉시 게시 (체크 해제 = 임시저장)
                </label>
                <button
                  onClick={handleSave}
                  disabled={saving || !title.trim() || !body.trim()}
                  className="w-full rounded-xl bg-brand text-white text-[13px] font-bold py-2.5 disabled:opacity-50 transition"
                >
                  {saving ? "저장 중..." : "저장"}
                </button>
              </div>
            </Card>
          </div>
        )}
      </div>
    </div>
  );
}
