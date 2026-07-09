"use client";

// 고객 일괄 등록 — 붙여넣기(한 줄에 한 명: 이름 연락처)로 빠르게 불러온 뒤,
// 표에서 성별·생년월일·직업급수·유입경로·메모·아바타까지 행별로 보정해 한 번에 등록.
// ★ CSV 파일 아님. 카톡·문자·메모에서 복사한 텍스트를 그대로 붙여넣으면 됨.
//   서버가 (이름+연락처) 중복은 건너뛴다. 이름만 있어도 등록 가능.

import { useState, useEffect, useMemo } from "react";
import {
  createCustomersBulk, searchJobs, LEAD_SOURCES, ApiError,
  type BulkCustomerRow, type JobMatch,
} from "@/lib/api";
import { AVATAR_PALETTE, CustomerAvatar } from "@/components/ui";

const PHONE_RE = /(01[0-9][-\s]?\d{3,4}[-\s]?\d{4})/;

interface EditRow {
  name: string;
  phone: string;
  gender: "" | "1" | "2";
  birth: string;
  job: JobMatch | null;
  lead: string;
  memo: string;
  avatarLabel: string;
  color: string;
}

function emptyRow(): EditRow {
  return { name: "", phone: "", gender: "", birth: "", job: null, lead: "", memo: "", avatarLabel: "", color: "" };
}

function parseLine(raw: string): EditRow | null {
  const line = raw.trim();
  if (!line) return null;
  const m = line.match(PHONE_RE);
  const phone = m ? m[1].replace(/\s/g, "") : "";
  let name = (m ? line.replace(m[1], "") : line).replace(/[,\t·|]+/g, " ").trim();
  name = name.replace(/\s+/g, " ").trim();
  if (!name) return null;
  return { ...emptyRow(), name: name.slice(0, 20), phone: phone.slice(0, 15) };
}

function parseText(text: string): EditRow[] {
  const out: EditRow[] = [];
  for (const l of text.split("\n")) {
    const r = parseLine(l);
    if (r) out.push(r);
  }
  return out;
}

// 팔레트 hex → 한글 색이름(표 셀 select용). 팔레트가 바뀌어도 hex로 폴백.
const COLOR_NAMES: Record<string, string> = {
  "#F8D7DD": "분홍", "#FCE2CF": "주황", "#FBF0C9": "노랑",
  "#DDEEDC": "초록", "#D6EAF1": "하늘", "#DFE1FA": "파랑",
  "#ECDDF3": "보라", "#E7E9ED": "회색", "#D5D8DE": "진회색",
};

function gradeChip(grade: number): string {
  if (grade === 1) return "bg-emerald-100 text-emerald-700";
  if (grade === 2) return "bg-amber-100 text-amber-700";
  if (grade === 3) return "bg-rose-100 text-rose-700";
  return "bg-surface2 text-ink3";
}

const cellCls =
  "rounded-md border border-line bg-surface px-2 py-1.5 text-[12px] text-ink placeholder:text-muted outline-none focus:border-brand";

// 행별 직업급수 검색 셀 — 검색 → 선택 시 job 적용(미선택 가능). 단건 등록 모달 패턴 재사용.
function JobCell({ value, onChange }: { value: JobMatch | null; onChange: (j: JobMatch | null) => void }) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<JobMatch[]>([]);
  const [open, setOpen] = useState(false);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    const query = q.trim();
    if (!query) { setResults([]); setOpen(false); return; }
    let alive = true;
    setSearching(true);
    const t = setTimeout(() => {
      searchJobs(query)
        .then((rows) => { if (alive) { setResults(rows); setOpen(true); } })
        .catch(() => { if (alive) setResults([]); })
        .finally(() => { if (alive) setSearching(false); });
    }, 250);
    return () => { alive = false; clearTimeout(t); };
  }, [q]);

  if (value) {
    return (
      <div className="flex items-center gap-1 rounded-md border border-line bg-accent-tint px-2 py-1 min-w-[150px] grow">
        <span className="text-[12px] text-ink truncate flex-1">{value.name}</span>
        <span className={`shrink-0 rounded-full text-[10px] font-bold px-1.5 py-0.5 ${gradeChip(value.risk_grade)}`}>{value.risk_grade_label}</span>
        <button type="button" onClick={() => onChange(null)} className="shrink-0 text-ink3 hover:text-ink text-[13px] leading-none" aria-label="직업 지우기">×</button>
      </div>
    );
  }
  return (
    <div className="relative min-w-[150px] grow">
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => { if (results.length) setOpen(true); }}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder="직업 검색(선택)"
        className={`${cellCls} w-full`}
      />
      {open && q.trim() && (
        <div className="absolute z-20 mt-1 w-[240px] max-h-52 overflow-y-auto rounded-lg border border-line bg-surface shadow-lg">
          {searching && results.length === 0 ? (
            <div className="px-3 py-2 text-[12px] text-ink3">찾는 중…</div>
          ) : results.length > 0 ? (
            results.map((j) => (
              <button
                key={j.id}
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => { onChange(j); setQ(""); setResults([]); setOpen(false); }}
                className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left hover:bg-surface2 border-b border-line last:border-b-0"
              >
                <span className="min-w-0">
                  <span className="block text-[12px] text-ink truncate">{j.name}</span>
                  {j.description_short && <span className="block text-[10px] text-ink3 truncate">{j.description_short}</span>}
                </span>
                <span className={`shrink-0 rounded-full text-[10px] font-bold px-1.5 py-0.5 ${gradeChip(j.risk_grade)}`}>{j.risk_grade_label}</span>
              </button>
            ))
          ) : (
            <div className="px-3 py-2 text-[12px] text-ink3">결과가 없어요.</div>
          )}
        </div>
      )}
    </div>
  );
}

export function CustomerBulkModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [text, setText] = useState("");
  const [rows, setRows] = useState<EditRow[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<{ created: number; skipped: number } | null>(null);

  const named = useMemo(() => rows.filter((r) => r.name.trim()), [rows]);
  const pending = useMemo(() => parseText(text).length, [text]);
  const willRegister = named.length + pending;

  function addFromText() {
    const parsed = parseText(text);
    if (parsed.length) {
      setRows((rs) => [...rs, ...parsed].slice(0, 200));
      setText("");
    }
  }

  function update(i: number, patch: Partial<EditRow>) {
    setRows((rs) => rs.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  }
  function removeRow(i: number) {
    setRows((rs) => rs.filter((_, idx) => idx !== i));
  }

  async function submit() {
    // 표에 안 넣고 남겨둔 붙여넣기 줄이 있으면 먼저 합친다.
    const working = text.trim() ? [...rows, ...parseText(text)].slice(0, 200) : rows;
    const targets = working.filter((r) => r.name.trim());
    if (!targets.length) return;
    setSaving(true);
    setError(null);
    const payload: BulkCustomerRow[] = targets.map((r) => ({
      name: r.name.trim().slice(0, 20),
      mobile_phone_number: r.phone.trim() || undefined,
      gender: r.gender || undefined,
      birth_day: r.birth || undefined,
      job_code: r.job ? String(r.job.id) : undefined,
      lead_source: r.lead || undefined,
      memo: r.memo.trim() || undefined,
      avatar_label: r.avatarLabel.trim() || undefined,
      color: r.color || undefined,
    }));
    try {
      setDone(await createCustomersBulk(payload));
    } catch (e) {
      if (e instanceof ApiError && e.status === 402) {
        // 고객 추가 한도 도달(유료 전환 후에만 발생) → 긍정 업그레이드 안내.
        setError("이번 달 고객 추가 한도를 넘어서 등록할 수 없었어요. 요금제를 올리면 더 등록할 수 있어요.");
      } else {
        setError("등록 중 오류가 났어요. 잠시 후 다시 시도해 주세요.");
      }
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 sm:p-4" onClick={onClose}>
      <div
        className="w-full sm:max-w-5xl bg-surface rounded-t-2xl sm:rounded-2xl p-5 shadow-xl max-h-[92dvh] overflow-auto"
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
              한 줄에 한 명씩 <b>이름과 연락처</b>를 붙여넣고 <b>표에 추가</b>를 누르세요. 아래 표에서 성별·생년월일·직업급수·유입경로·메모·아바타를 채우면 됩니다. (이름만 있어도 등록돼요)
            </p>

            {/* 붙여넣기 → 표에 추가 */}
            <div className="mt-3 flex flex-col sm:flex-row gap-2">
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={3}
                placeholder={"김민수 010-1234-5678\n이영희 010-2222-3333\n박철수"}
                className="flex-1 rounded-xl border border-line bg-surface px-3 py-2 text-[14px] text-ink placeholder:text-muted outline-none focus:border-brand resize-none leading-6"
              />
              <button
                onClick={addFromText}
                disabled={!pending}
                className="shrink-0 rounded-xl border border-brand bg-accent-tint text-brand text-[13px] font-bold px-4 py-2 disabled:opacity-40"
              >
                표에 추가{pending ? ` (${pending})` : ""}
              </button>
            </div>

            {/* 편집 표 */}
            <div className="mt-3 flex items-center justify-between text-[12px]">
              <span className="font-semibold text-ink2">
                등록 대상 {named.length}명
                {rows.length > named.length && <span className="text-ink3 font-normal"> (이름 없는 {rows.length - named.length}행 제외)</span>}
              </span>
              <button onClick={() => setRows((rs) => [...rs, emptyRow()].slice(0, 200))} className="text-brand font-semibold">+ 직접 추가</button>
            </div>

            {rows.length > 0 ? (
              <div className="mt-2 space-y-1.5">
                {rows.map((r, i) => (
                  <div key={i} className="relative flex flex-wrap items-center gap-1.5 rounded-xl border border-line px-2 py-2">
                    <span className="w-5 text-center text-[11px] text-ink3 tnum shrink-0">{i + 1}</span>
                    <input value={r.name} onChange={(e) => update(i, { name: e.target.value.slice(0, 20) })} placeholder="이름" className={`${cellCls} w-24`} />
                    <input value={r.phone} onChange={(e) => update(i, { phone: e.target.value.slice(0, 15) })} placeholder="연락처" inputMode="tel" className={`${cellCls} w-32`} />
                    <select value={r.gender} onChange={(e) => update(i, { gender: e.target.value as EditRow["gender"] })} className={`${cellCls} w-16`}>
                      <option value="">성별</option>
                      <option value="1">남</option>
                      <option value="2">여</option>
                    </select>
                    <input type="date" value={r.birth} onChange={(e) => update(i, { birth: e.target.value })} className={`${cellCls} w-[132px]`} />
                    <JobCell value={r.job} onChange={(j) => update(i, { job: j })} />
                    <select value={r.lead} onChange={(e) => update(i, { lead: e.target.value })} className={`${cellCls} w-20`}>
                      <option value="">유입</option>
                      {LEAD_SOURCES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                    </select>
                    <input value={r.memo} onChange={(e) => update(i, { memo: e.target.value })} placeholder="메모" className={`${cellCls} min-w-[100px] grow`} />
                    <CustomerAvatar label={r.avatarLabel} color={r.color || null} size={28} />
                    <input value={r.avatarLabel} onChange={(e) => update(i, { avatarLabel: e.target.value.slice(0, 3) })} placeholder="글씨" maxLength={3} className={`${cellCls} w-14`} />
                    <select value={r.color} onChange={(e) => update(i, { color: e.target.value })} className={`${cellCls} w-16`}>
                      <option value="">기본</option>
                      {AVATAR_PALETTE.map((hex) => <option key={hex} value={hex}>{COLOR_NAMES[hex] ?? hex}</option>)}
                    </select>
                    <button type="button" onClick={() => removeRow(i)} className="shrink-0 w-6 h-6 rounded-md text-ink3 hover:bg-surface2 hover:text-ink text-[15px] leading-none" aria-label="행 삭제">×</button>
                  </div>
                ))}
              </div>
            ) : (
              <div className="mt-2 rounded-xl border border-dashed border-line py-6 text-center text-[13px] text-ink3">
                위에 붙여넣고 <b className="text-ink2">표에 추가</b>를 누르거나 <b className="text-ink2">+ 직접 추가</b>로 시작하세요.
              </div>
            )}

            {error && <div className="mt-2 text-[12px] text-cnone">{error}</div>}
            <div className="mt-4 flex gap-2">
              <button onClick={onClose} className="flex-1 rounded-xl border border-line bg-surface2 py-2.5 text-[14px] font-semibold text-ink2">
                취소
              </button>
              <button
                onClick={submit}
                disabled={!willRegister || saving}
                className="flex-1 rounded-xl bg-brand text-white py-2.5 text-[14px] font-bold disabled:opacity-50"
              >
                {saving ? "등록 중..." : `${willRegister}명 등록`}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
