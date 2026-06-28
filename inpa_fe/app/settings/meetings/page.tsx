"use client";

// 미팅 관리 — 다가오는 미팅(확정) + 가능한 시간(슬롯) 추가/삭제.
// 슬롯 입력은 datetime-local(브라우저 로컬=KST) → toISOString()으로 전송.

import { useState, useEffect, useCallback } from "react";
import { AppNav } from "@/components/app-nav";
import { SettingsTabs } from "@/components/settings-tabs";
import { Card } from "@/components/ui";
import { useAuthGuard } from "@/lib/useAuthGuard";
import {
  listMeetingSlots,
  createMeetingSlot,
  deleteMeetingSlot,
  listMeetings,
  type MeetingSlot,
  type Meeting,
  ApiError,
} from "@/lib/api";

function fmtKST(iso: string): string {
  try {
    return new Intl.DateTimeFormat("ko-KR", {
      month: "long", day: "numeric", weekday: "short",
      hour: "numeric", minute: "2-digit", timeZone: "Asia/Seoul",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

export default function MeetingsSettingsPage() {
  const ready = useAuthGuard();
  const [slots, setSlots] = useState<MeetingSlot[]>([]);
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [newAt, setNewAt] = useState("");
  const [newDur, setNewDur] = useState(30);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(() => {
    Promise.all([listMeetingSlots(true), listMeetings(true)])
      .then(([s, m]) => { setSlots(s.results); setMeetings(m.results); })
      .catch(() => { /* useAuthGuard 처리 */ });
  }, []);

  useEffect(() => { if (ready) load(); }, [ready, load]);

  const addSlot = useCallback(async () => {
    if (!newAt) return;
    // datetime-local 은 브라우저 로컬(KST)로 파싱 → toISOString 이 UTC 로 변환(정상).
    // 과거/직후 시각은 서버 400(미래강제) 전에 클라에서 막아 친절 안내.
    const dt = new Date(newAt);
    if (isNaN(dt.getTime())) { setErr("날짜·시간을 다시 확인해주세요."); return; }
    if (dt.getTime() <= Date.now() + 60_000) {
      setErr("지금보다 나중 시간을 골라주세요. (예약 가능 시간은 미래만 등록돼요)"); return;
    }
    setBusy(true); setErr(null);
    try {
      await createMeetingSlot({ start_at: dt.toISOString(), duration_min: newDur });
      setNewAt("");
      load();
    } catch (e: unknown) {
      setErr(e instanceof ApiError ? e.message : "슬롯 추가에 실패했어요.");
    } finally {
      setBusy(false);
    }
  }, [newAt, newDur, load]);

  // datetime-local min = 지금+5분(로컬 시각 문자열 YYYY-MM-DDTHH:mm)
  const minLocal = (() => {
    const d = new Date(Date.now() + 5 * 60_000);
    const p = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
  })();

  const removeSlot = useCallback(async (id: number) => {
    setBusy(true); setErr(null);
    try {
      await deleteMeetingSlot(id);
      load();
    } catch (e: unknown) {
      setErr(e instanceof ApiError ? e.message : "삭제에 실패했어요.");
    } finally {
      setBusy(false);
    }
  }, [load]);

  if (!ready) return null;

  return (
    <div className="min-h-dvh">
      <AppNav active="settings" />
      <main className="mx-auto max-w-xl px-4 sm:px-6 py-6 space-y-4">
        <SettingsTabs active="meetings" />
        <h1 className="text-[22px] font-extrabold text-ink">미팅 관리</h1>
        {err && (
          <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-2 text-[13px] text-rose-700">{err}</div>
        )}

        {/* 다가오는 미팅 */}
        <Card className="px-5 py-4">
          <div className="text-[15px] font-bold text-ink">다가오는 미팅</div>
          {meetings.length === 0 ? (
            <p className="mt-2 text-[13px] text-ink3">아직 확정된 미팅이 없어요.</p>
          ) : (
            <div className="mt-3 divide-y divide-line">
              {meetings.map((m) => (
                <div key={m.id} className="py-2.5">
                  <div className="text-[14px] font-semibold text-ink">{fmtKST(m.start_at)}</div>
                  <div className="text-[12px] text-ink3 mt-0.5">
                    {m.customer_name} · {m.method_display}
                    {m.location_detail ? ` · ${m.location_detail}` : ""}
                    {m.customer_note ? ` · “${m.customer_note}”` : ""}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        {/* 슬롯 추가 */}
        <Card className="px-5 py-4">
          <div className="text-[15px] font-bold text-ink">가능한 시간 추가</div>
          <p className="mt-1 text-[12px] text-ink3 leading-5">
            여기서 연 시간만 고객 예약 링크에 보입니다. (지난 시간은 자동으로 숨겨져요)
          </p>
          <div className="mt-3 flex flex-wrap items-end gap-2">
            <label className="block">
              <span className="text-[12px] text-ink3">날짜·시간</span>
              <input
                type="datetime-local"
                value={newAt}
                min={minLocal}
                onChange={(e) => setNewAt(e.target.value)}
                className="mt-1 block rounded-xl border border-line px-3 py-2 text-[14px]"
              />
            </label>
            <label className="block">
              <span className="text-[12px] text-ink3">소요(분)</span>
              <input
                type="number" min={10} max={240}
                value={newDur}
                onChange={(e) => setNewDur(Number(e.target.value) || 30)}
                className="mt-1 block w-24 rounded-xl border border-line px-3 py-2 text-[14px] tnum"
              />
            </label>
            <button
              disabled={busy || !newAt}
              onClick={addSlot}
              className="rounded-xl bg-brand text-white text-[13px] font-bold px-4 py-2.5 disabled:opacity-60"
            >
              추가
            </button>
          </div>
        </Card>

        {/* 열린 슬롯 목록 */}
        <Card className="px-5 py-4">
          <div className="text-[15px] font-bold text-ink">열린 시간</div>
          {slots.length === 0 ? (
            <p className="mt-2 text-[13px] text-ink3">열린 시간이 없어요. 위에서 추가해 주세요.</p>
          ) : (
            <div className="mt-3 divide-y divide-line">
              {slots.map((s) => (
                <div key={s.id} className="flex items-center justify-between py-2.5">
                  <div className="text-[14px] text-ink">{fmtKST(s.start_at)}<span className="text-[12px] text-ink3"> · {s.duration_min}분</span></div>
                  <button
                    disabled={busy}
                    onClick={() => removeSlot(s.id)}
                    className="text-[12px] font-semibold text-danger hover:underline disabled:opacity-60"
                  >
                    삭제
                  </button>
                </div>
              ))}
            </div>
          )}
        </Card>
      </main>
    </div>
  );
}
