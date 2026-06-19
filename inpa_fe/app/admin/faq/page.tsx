"use client";

import { useState, useEffect } from "react";
import { useAdminGuard } from "@/lib/useAdminGuard";
import { adminCreateFaq, adminUpdateFaq, adminDeleteFaq } from "@/lib/adminApi";
import { listFaqs, type FaqItem } from "@/lib/api";
import { Card } from "@/components/ui";

const CATEGORIES = ["general", "billing", "feature", "compliance"];
const CAT_LABELS: Record<string, string> = {
  general:    "일반",
  billing:    "요금",
  feature:    "기능",
  compliance: "컴플라이언스",
};

export default function AdminFaqPage() {
  const ready = useAdminGuard();

  const [faqs, setFaqs] = useState<FaqItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [catFilter, setCatFilter] = useState("all");

  const [isNew, setIsNew] = useState(false);
  const [editing, setEditing] = useState<FaqItem | null>(null);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [category, setCategory] = useState("general");
  const [order, setOrder] = useState(0);
  const [isPublished, setIsPublished] = useState(false);
  const [saving, setSaving] = useState(false);

  async function fetchFaqs() {
    setLoading(true);
    setError(null);
    try {
      const res = await listFaqs();
      setFaqs(res);
    } catch {
      setError("FAQ를 불러오지 못했어요.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { if (ready) fetchFaqs(); }, [ready]);

  function openNew() {
    setEditing(null);
    setIsNew(true);
    setQuestion("");
    setAnswer("");
    setCategory("general");
    setOrder(0);
    setIsPublished(false);
  }

  function openEdit(f: FaqItem) {
    setIsNew(false);
    setEditing(f);
    setQuestion(f.question);
    setAnswer(f.answer);
    setCategory(f.category);
    setOrder(f.order);
    setIsPublished(f.is_published);
  }

  function closeForm() {
    setIsNew(false);
    setEditing(null);
  }

  async function handleSave() {
    setSaving(true);
    try {
      if (isNew) {
        await adminCreateFaq({ question, answer, category, order, is_published: isPublished });
      } else if (editing) {
        await adminUpdateFaq(editing.id, { question, answer, category, order, is_published: isPublished });
      }
      closeForm();
      await fetchFaqs();
    } catch {
      alert("저장에 실패했어요.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: number) {
    if (!confirm("삭제하시겠어요?")) return;
    try {
      await adminDeleteFaq(id);
      await fetchFaqs();
    } catch {
      alert("삭제에 실패했어요.");
    }
  }

  if (!ready) return null;

  const filtered = catFilter === "all" ? faqs : faqs.filter((f) => f.category === catFilter);
  const showForm = isNew || editing !== null;

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-[22px] font-extrabold text-ink">FAQ</h1>
        <button
          onClick={openNew}
          className="rounded-xl bg-brand text-white text-[13px] font-bold px-4 py-2.5"
        >
          + FAQ 작성
        </button>
      </div>

      {/* 카테고리 탭 */}
      <div className="flex gap-2 mb-4 flex-wrap">
        {["all", ...CATEGORIES].map((c) => (
          <button
            key={c}
            onClick={() => setCatFilter(c)}
            className={`px-3 py-1.5 rounded-lg text-[13px] font-semibold transition ${
              catFilter === c ? "bg-brand text-white" : "bg-surface2 text-ink2 hover:bg-line"
            }`}
          >
            {c === "all" ? "전체" : CAT_LABELS[c] ?? c}
          </button>
        ))}
      </div>

      {error && (
        <div className="mb-4 p-3 rounded-xl bg-red-50 border border-red-200 text-[13px] text-red-700">{error}</div>
      )}

      {loading && <div className="text-[14px] text-ink3">불러오는 중...</div>}

      <div className="flex gap-5">
        {/* 목록 */}
        <div className="flex-1 min-w-0">
          {!loading && (
            <Card>
              <div className="divide-y divide-line">
                {filtered.length === 0 && (
                  <div className="px-4 py-8 text-center text-[13px] text-ink3">FAQ가 없어요.</div>
                )}
                {filtered.sort((a, b) => a.order - b.order).map((f) => (
                  <div key={f.id} className="flex items-start px-4 py-3.5 gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                        <span className="text-[11px] rounded-full px-2 py-0.5 bg-surface2 text-ink3 font-semibold">
                          {CAT_LABELS[f.category] ?? f.category}
                        </span>
                        {!f.is_published && (
                          <span className="text-[10px] font-bold rounded-full px-2 py-0.5 bg-surface2 text-muted">비공개</span>
                        )}
                        <span className="text-[12px] text-ink3 tnum">순서 {f.order}</span>
                      </div>
                      <div className="text-[14px] font-semibold text-ink">{f.question}</div>
                      <div className="text-[12px] text-ink3 mt-0.5 line-clamp-2">{f.answer}</div>
                    </div>
                    <div className="flex gap-2 shrink-0">
                      <button onClick={() => openEdit(f)} className="text-[12px] font-semibold text-brand hover:underline">수정</button>
                      <button onClick={() => handleDelete(f.id)} className="text-[12px] font-semibold text-danger hover:underline">삭제</button>
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
                <h2 className="text-[15px] font-bold text-ink">{isNew ? "새 FAQ" : "FAQ 수정"}</h2>
                <button onClick={closeForm} className="text-ink3 text-[18px] leading-none hover:text-ink">×</button>
              </div>
              <div className="space-y-3">
                <div>
                  <label className="block text-[12px] font-semibold text-ink3 mb-1">카테고리</label>
                  <select
                    value={category}
                    onChange={(e) => setCategory(e.target.value)}
                    className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-[13px] text-ink outline-none focus:border-brand"
                  >
                    {CATEGORIES.map((c) => (
                      <option key={c} value={c}>{CAT_LABELS[c] ?? c}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-[12px] font-semibold text-ink3 mb-1">질문</label>
                  <input
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-[14px] text-ink outline-none focus:border-brand"
                  />
                </div>
                <div>
                  <label className="block text-[12px] font-semibold text-ink3 mb-1">답변</label>
                  <textarea
                    value={answer}
                    onChange={(e) => setAnswer(e.target.value)}
                    rows={5}
                    className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-[13px] text-ink outline-none focus:border-brand resize-none"
                  />
                </div>
                <div>
                  <label className="block text-[12px] font-semibold text-ink3 mb-1">노출 순서</label>
                  <input
                    type="number"
                    value={order}
                    onChange={(e) => setOrder(Number(e.target.value))}
                    className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-[13px] text-ink outline-none focus:border-brand"
                  />
                </div>
                <label className="flex items-center gap-2 text-[13px] text-ink cursor-pointer">
                  <input type="checkbox" checked={isPublished} onChange={(e) => setIsPublished(e.target.checked)} />
                  공개 (체크 해제 = 비공개)
                </label>
                <button
                  onClick={handleSave}
                  disabled={saving || !question.trim() || !answer.trim()}
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
