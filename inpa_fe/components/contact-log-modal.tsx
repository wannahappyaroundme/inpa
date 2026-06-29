"use client";

// 접촉 결과 기록 모달 — 전화·문자 결과(부재중·연결·약속·거절·보류) + 메모 저장.
// 저장 시 BE가 고객 last_contacted_at도 함께 갱신(무접촉 경보 리셋 = 기존 '방금 연락함'과 동일).

import { useState } from "react";
import { createContactLog, CONTACT_RESULTS, type ContactResult } from "@/lib/api";

export function ContactLogModal({
  customerId,
  onClose,
  onSaved,
}: {
  customerId: number;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [result, setResult] = useState<ContactResult | null>(null);
  const [memo, setMemo] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    if (!result) return;
    setSaving(true);
    setError(null);
    try {
      await createContactLog(customerId, { result, memo: memo.trim() || undefined });
      onSaved();
      onClose();
    } catch {
      setError("저장에 실패했어요. 잠시 후 다시 시도하세요.");
      setSaving(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 sm:p-4"
      onClick={onClose}
    >
      <div
        className="w-full sm:max-w-md bg-surface rounded-t-2xl sm:rounded-2xl p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="text-[16px] font-bold text-ink">연락 결과 기록</div>
        <p className="mt-1 text-[12px] text-ink3">전화·문자 결과를 남기면 무접촉 표시가 초기화돼요.</p>
        <div className="mt-3 grid grid-cols-5 gap-1.5">
          {CONTACT_RESULTS.map((r) => (
            <button
              key={r.key}
              type="button"
              onClick={() => setResult(r.key)}
              className={`rounded-lg border py-2 text-[13px] font-semibold transition ${
                result === r.key ? "border-brand bg-brand-soft text-brand" : "border-line bg-surface2 text-ink2"
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
        <textarea
          value={memo}
          onChange={(e) => setMemo(e.target.value)}
          placeholder="메모(선택) - 예: 다음 주 화요일 다시 연락"
          rows={3}
          className="mt-3 w-full rounded-xl border border-line bg-surface px-3 py-2 text-[14px] text-ink placeholder:text-muted outline-none focus:border-brand resize-none"
        />
        {error && <div className="mt-2 text-[12px] text-cnone">{error}</div>}
        <div className="mt-4 flex gap-2">
          <button
            onClick={onClose}
            className="flex-1 rounded-xl border border-line bg-surface2 py-2.5 text-[14px] font-semibold text-ink2"
          >
            취소
          </button>
          <button
            onClick={save}
            disabled={!result || saving}
            className="flex-1 rounded-xl bg-brand text-white py-2.5 text-[14px] font-bold disabled:opacity-50"
          >
            {saving ? "저장 중..." : "기록 저장"}
          </button>
        </div>
      </div>
    </div>
  );
}
