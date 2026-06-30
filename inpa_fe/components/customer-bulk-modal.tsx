"use client";

// 고객 일괄 등록 — 붙여넣기(한 줄에 한 명: 이름 연락처) → 미리보기 → 한 번에 등록.
// ★ CSV 파일 아님. 카톡·문자·메모에서 복사한 텍스트를 그대로 붙여넣으면 됨.
//   서버가 (이름+연락처) 중복은 건너뛴다. 이름만 있어도 등록 가능.

import { useState, useMemo } from "react";
import { createCustomersBulk, type BulkCustomerRow } from "@/lib/api";

const PHONE_RE = /(01[0-9][-\s]?\d{3,4}[-\s]?\d{4})/;

function parseLine(raw: string): BulkCustomerRow | null {
  const line = raw.trim();
  if (!line) return null;
  const m = line.match(PHONE_RE);
  const phone = m ? m[1].replace(/\s/g, "") : "";
  let name = (m ? line.replace(m[1], "") : line).replace(/[,\t·|]+/g, " ").trim();
  name = name.replace(/\s+/g, " ").trim();
  if (!name) return null;
  return { name: name.slice(0, 20), mobile_phone_number: phone.slice(0, 15) };
}

export function CustomerBulkModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<{ created: number; skipped: number } | null>(null);

  const { rows, ignored } = useMemo(() => {
    const out: BulkCustomerRow[] = [];
    let ig = 0;
    for (const l of text.split("\n")) {
      if (!l.trim()) continue;
      const r = parseLine(l);
      if (r) out.push(r);
      else ig++;
    }
    return { rows: out, ignored: ig };
  }, [text]);

  async function submit() {
    if (!rows.length) return;
    setSaving(true);
    setError(null);
    try {
      setDone(await createCustomersBulk(rows));
    } catch {
      setError("등록 중 오류가 났어요. 잠시 후 다시 시도해 주세요.");
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 sm:p-4" onClick={onClose}>
      <div
        className="w-full sm:max-w-lg bg-surface rounded-t-2xl sm:rounded-2xl p-5 shadow-xl max-h-[90dvh] overflow-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {done ? (
          <div className="text-center py-4">
            <div className="text-[18px] font-bold text-ink">{done.created}명 등록 완료</div>
            <p className="mt-1 text-[13px] text-ink3">
              {done.skipped > 0 ? `중복이거나 비어 있는 ${done.skipped}건은 건너뛰었어요.` : "모두 새로 등록됐어요."}
            </p>
            <button onClick={onCreated} className="mt-4 w-full rounded-xl bg-brand text-white py-2.5 text-[14px] font-bold">
              고객 목록 보기
            </button>
          </div>
        ) : (
          <>
            <div className="text-[16px] font-bold text-ink">여러 명 한 번에 등록</div>
            <p className="mt-1 text-[12px] text-ink3 leading-5">
              한 줄에 한 명씩 <b>이름과 연락처</b>를 붙여넣으세요. 카톡·문자·메모에서 복사한 그대로면 돼요. (연락처는 없어도 등록돼요)
            </p>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={6}
              placeholder={"김민수 010-1234-5678\n이영희 010-2222-3333\n박철수"}
              className="mt-3 w-full rounded-xl border border-line bg-surface px-3 py-2 text-[14px] text-ink placeholder:text-muted outline-none focus:border-brand resize-none leading-6"
            />
            <div className="mt-3 flex items-center justify-between text-[12px]">
              <span className="font-semibold text-ink2">미리보기 {rows.length}명</span>
              {ignored > 0 && <span className="text-ink3">인식 못한 줄 {ignored}개</span>}
            </div>
            {rows.length > 0 && (
              <div className="mt-2 max-h-44 overflow-auto rounded-xl border border-line divide-y divide-line">
                {rows.slice(0, 50).map((r, i) => (
                  <div key={i} className="flex items-center gap-3 px-3 py-1.5 text-[13px]">
                    <span className="w-6 text-ink3 tnum">{i + 1}</span>
                    <span className="flex-1 font-semibold text-ink truncate">{r.name}</span>
                    <span className="text-ink3 tnum">{r.mobile_phone_number || "연락처 없음"}</span>
                  </div>
                ))}
                {rows.length > 50 && (
                  <div className="px-3 py-1.5 text-[12px] text-ink3 text-center">…외 {rows.length - 50}명</div>
                )}
              </div>
            )}
            {error && <div className="mt-2 text-[12px] text-cnone">{error}</div>}
            <div className="mt-4 flex gap-2">
              <button onClick={onClose} className="flex-1 rounded-xl border border-line bg-surface2 py-2.5 text-[14px] font-semibold text-ink2">
                취소
              </button>
              <button
                onClick={submit}
                disabled={!rows.length || saving}
                className="flex-1 rounded-xl bg-brand text-white py-2.5 text-[14px] font-bold disabled:opacity-50"
              >
                {saving ? "등록 중..." : `${rows.length}명 등록`}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
