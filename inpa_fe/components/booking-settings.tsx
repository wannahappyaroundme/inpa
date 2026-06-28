"use client";

// 예약 설정 — 내 이름·소속·직책·안내 문구 + 주간 업무시간 + 미팅 시간/여유.
// 업무시간(WorkHour)을 정해두면, 그 안의 빈 시간이 고객 링크에 자동으로 노출된다(Calendly식).
// updateProfile(PATCH /auth/profile/) + work-hours CRUD.

import { useState, useEffect, useCallback } from "react";
import { Card } from "@/components/ui";
import {
  getProfile, updateProfile,
  listWorkHours, createWorkHour, deleteWorkHour,
  type WorkHour,
} from "@/lib/api";

const WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"];
const DEFAULT_TPL =
  "{고객명} 고객님, 안녕하세요. {소속직책} {설계사명} 보험설계사입니다.\n" +
  "가능하신 날짜를 선택해 주시면 자세한 보험 상담을 도와드리겠습니다.\n" +
  "아래 링크에서 편하신 시간을 골라주세요 👇\n{링크}";

function fillPreview(tpl: string, name: string, label: string): string {
  return (tpl || DEFAULT_TPL)
    .replace(/\{고객명\}/g, "김보장")
    .replace(/\{소속직책\}/g, label || "")
    .replace(/\{설계사명\}/g, name || "담당 설계사")
    .replace(/\{링크\}/g, "https://in-pa.vercel.app/b/…");
}

export function BookingSettings() {
  const [name, setName] = useState("");
  const [affiliation, setAffiliation] = useState("");
  const [title, setTitle] = useState("");
  const [tpl, setTpl] = useState("");
  const [dur, setDur] = useState(30);
  const [buffer, setBuffer] = useState(60);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const [workHours, setWorkHours] = useState<WorkHour[]>([]);
  const [whWeekday, setWhWeekday] = useState(0);
  const [whStart, setWhStart] = useState("09:00");
  const [whEnd, setWhEnd] = useState("18:00");
  const [whErr, setWhErr] = useState<string | null>(null);

  useEffect(() => {
    getProfile().then((p) => {
      setName(p.name ?? "");
      setAffiliation(p.affiliation ?? "");
      setTitle(p.title ?? "");
      setTpl(p.booking_msg_template ?? "");
      setDur(p.booking_default_duration ?? 30);
      setBuffer(p.booking_buffer_min ?? 60);
    }).catch(() => { /* useAuthGuard 처리 */ });
    listWorkHours().then((r) => setWorkHours(r.results)).catch(() => setWorkHours([]));
  }, []);

  const label = [affiliation.trim(), title.trim()].filter(Boolean).join(" ");

  const save = useCallback(async () => {
    setSaving(true); setMsg(null);
    try {
      await updateProfile({
        name: name.trim(), affiliation: affiliation.trim(), title: title.trim(),
        booking_msg_template: tpl, booking_default_duration: dur, booking_buffer_min: buffer,
      });
      setMsg("예약 설정을 저장했어요");
      setTimeout(() => setMsg(null), 2000);
    } catch {
      setMsg("저장에 실패했어요");
    } finally { setSaving(false); }
  }, [name, affiliation, title, tpl, dur, buffer]);

  const addWorkHour = useCallback(async () => {
    setWhErr(null);
    if (whStart >= whEnd) { setWhErr("종료가 시작보다 늦어야 해요."); return; }
    try {
      const wh = await createWorkHour({ weekday: whWeekday, start_time: whStart, end_time: whEnd });
      setWorkHours((prev) => [...prev, wh].sort((a, b) =>
        a.weekday - b.weekday || a.start_time.localeCompare(b.start_time)));
    } catch {
      setWhErr("추가에 실패했어요.");
    }
  }, [whWeekday, whStart, whEnd]);

  const removeWorkHour = useCallback(async (id: number) => {
    setWorkHours((prev) => prev.filter((w) => w.id !== id));
    try { await deleteWorkHour(id); } catch { listWorkHours().then((r) => setWorkHours(r.results)).catch(() => {}); }
  }, []);

  const inputCls = "rounded-xl border border-line px-3 py-2 text-[14px]";

  return (
    <Card className="px-5 py-4">
      <div className="text-[15px] font-bold text-ink">예약 설정</div>
      <p className="mt-1 text-[12px] text-ink3 leading-5">
        업무시간을 정해두면, 그 안의 <b className="text-ink2">비어 있는 시간</b>이 고객 링크에 자동으로 보여요.
        고객이 시간을 고르면 설계사님이 알림에서 수락하면 일정에 확정됩니다.
      </p>
      {msg && <div className="mt-2 rounded-lg bg-accent-tint text-brand text-[13px] px-3 py-2">{msg}</div>}

      {/* 내 정보 — 문구 자동 채움용 */}
      <div className="mt-4 grid sm:grid-cols-3 gap-3">
        <label className="block">
          <span className="text-[12px] text-ink3">내 이름</span>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="예) 홍길동"
            className={`mt-1 w-full ${inputCls}`} />
        </label>
        <label className="block">
          <span className="text-[12px] text-ink3">소속</span>
          <input value={affiliation} onChange={(e) => setAffiliation(e.target.value)} placeholder="예) 부산지점"
            className={`mt-1 w-full ${inputCls}`} />
        </label>
        <label className="block">
          <span className="text-[12px] text-ink3">직책</span>
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="예) FC, 팀장"
            className={`mt-1 w-full ${inputCls}`} />
        </label>
      </div>

      {/* 안내 문구 */}
      <label className="mt-4 block">
        <span className="text-[12px] text-ink3">예약 안내 문구(빈 칸이면 기본 문구)</span>
        <textarea value={tpl} onChange={(e) => setTpl(e.target.value)} rows={4}
          placeholder={DEFAULT_TPL}
          className="mt-1 w-full rounded-xl border border-line px-3 py-2 text-[13px] leading-5" />
      </label>
      <p className="mt-1 text-[12px] text-ink3 leading-5">
        넣을 수 있는 자동 채움: <b>{"{고객명}"} · {"{소속직책}"} · {"{설계사명}"} · {"{링크}"}</b>.
        실제 발송은 고객 화면에서 <b className="text-ink2">예약 링크 만들기</b>를 누르면 이 문구가 자동으로 채워지고, 복사해서 카톡·문자로 보내면 돼요.
      </p>
      {/* 미리보기 */}
      <div className="mt-2 rounded-xl border border-line bg-surface2 px-3 py-2.5">
        <div className="text-[11px] font-semibold text-ink3 mb-1">고객이 받는 모습(예시)</div>
        <pre className="whitespace-pre-wrap text-[12px] text-ink2 leading-5 font-sans">{fillPreview(tpl, name, label)}</pre>
      </div>

      {/* 업무시간 */}
      <div className="mt-5">
        <div className="text-[13px] font-bold text-ink">업무시간(요일·시간)</div>
        <p className="mt-0.5 text-[12px] text-ink3 leading-5">이 시간 안에서 미팅·차단·여유를 뺀 빈 시간만 고객에게 노출돼요.</p>
        {workHours.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-2">
            {workHours.map((w) => (
              <span key={w.id} className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1 text-[12px] text-ink2">
                {WEEKDAYS[w.weekday]} {w.start_time.slice(0, 5)}~{w.end_time.slice(0, 5)}
                <button onClick={() => removeWorkHour(w.id)} aria-label="삭제" className="text-ink3 hover:text-rose-600">✕</button>
              </span>
            ))}
          </div>
        )}
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <select value={whWeekday} onChange={(e) => setWhWeekday(Number(e.target.value))} className={inputCls}>
            {WEEKDAYS.map((w, i) => <option key={i} value={i}>{w}요일</option>)}
          </select>
          <input type="time" value={whStart} onChange={(e) => setWhStart(e.target.value)} className={inputCls} />
          <span className="text-ink3">~</span>
          <input type="time" value={whEnd} onChange={(e) => setWhEnd(e.target.value)} className={inputCls} />
          <button onClick={addWorkHour} className="rounded-xl border border-brand text-brand text-[13px] font-semibold px-3 py-2">+ 추가</button>
        </div>
        {whErr && <div className="mt-1 text-[12px] text-rose-600">{whErr}</div>}
      </div>

      {/* 미팅 시간 + 여유 + 저장 */}
      <div className="mt-5 flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1">
          <span className="text-[12px] text-ink3">미팅 시간(분)</span>
          <input type="number" min={10} max={240} value={dur} onChange={(e) => setDur(Number(e.target.value) || 30)}
            className="w-24 rounded-xl border border-line px-3 py-2 text-[14px] tnum text-center" />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-[12px] text-ink3">앞뒤 여유(분, 이동시간)</span>
          <input type="number" min={0} max={180} step={15} value={buffer} onChange={(e) => setBuffer(Number(e.target.value) || 0)}
            className="w-24 rounded-xl border border-line px-3 py-2 text-[14px] tnum text-center" />
        </label>
        <button disabled={saving} onClick={save}
          className="rounded-xl bg-brand text-white text-[13px] font-bold px-4 py-2.5 disabled:opacity-60">
          예약 설정 저장
        </button>
      </div>
    </Card>
  );
}
