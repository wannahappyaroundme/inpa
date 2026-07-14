"use client";

// 일정(캘린더) — 개인 일정/할일/고정 차단 + 미팅 통합 표시. 추가/수정/완료.
// (알림은 캘린더에 그리지 않고 우측 상단 종 알림함에서만 본다 — PM 06.29)
// ★ 타임존: 단건 datetime은 new Date()↔toISOString(KST 브라우저), 표시는 Intl(Asia/Seoul).
//   반복 차단 시각(HH:MM:SS 문자열)은 절대 new Date()에 넣지 말 것 → slice(0,5)로만.

import { useState, useEffect, useMemo, useCallback } from "react";
import { useRouter } from "next/navigation";
import { AppNav } from "@/components/app-nav";
import { Card } from "@/components/ui";
import { BookingSettings } from "@/components/booking-settings";
import { AvailabilityShare } from "@/components/availability-share";
import { useAuthGuard } from "@/lib/useAuthGuard";
import {
  listScheduleItems, createScheduleItem, updateScheduleItem, deleteScheduleItem,
  toggleScheduleDone, listMeetings, listAllCustomers,
  listPendingMeetings, acceptMeeting, declineMeeting,
  ApiError,
  type ScheduleItem, type ScheduleKind, type ScheduleCategory,
  type Meeting,
  type CustomerListItem,
} from "@/lib/api";

const WEEK = ["일", "월", "화", "수", "목", "금", "토"];
const pad = (n: number) => String(n).padStart(2, "0");

// 동작 구분(kind): todo 완료체크·block 차단 판정용
type Kind = ScheduleKind | "meeting";
// 색/범례 분류(5분류) — PM 06.24·06.29 (알림 분류 제거, 종 알림함으로 일원화)
type Cat = ScheduleCategory;
const CAT_META: Record<Cat, { dot: string; label: string }> = {
  meeting: { dot: "bg-brand", label: "고객미팅" },
  anniversary: { dot: "bg-pink-400", label: "생일·기념일" },
  renewal: { dot: "bg-amber-400", label: "만기·갱신" },
  task: { dot: "bg-emerald-500", label: "업무" },
  etc: { dot: "bg-muted", label: "기타" },
};
// 분류 선택지(생성 폼) — kind/올데이 기본값 매핑
const CAT_OPTIONS: { cat: ScheduleCategory; label: string; kind: ScheduleKind; allDay?: boolean }[] = [
  { cat: "meeting", label: "고객미팅", kind: "event" },
  { cat: "anniversary", label: "생일·기념일", kind: "event", allDay: true },
  { cat: "renewal", label: "만기·갱신", kind: "event", allDay: true },
  { cat: "task", label: "업무", kind: "todo" },
  { cat: "etc", label: "기타", kind: "event" },
];

function kstYmd(iso: string): string {
  try {
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit",
    }).format(new Date(iso));
  } catch { return iso.slice(0, 10); }
}
function kstTime(iso: string): string {
  try {
    return new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", hour12: false,
    }).format(new Date(iso));
  } catch { return ""; }
}
// JS getDay()(0=일) → 모델 recur_weekday(0=월..6=일)
function pyWeekday(d: Date): number { return (d.getDay() + 6) % 7; }

function fmtMeetingTime(iso: string): string {
  try {
    return new Intl.DateTimeFormat("ko-KR", {
      month: "long", day: "numeric", weekday: "short",
      hour: "numeric", minute: "2-digit", timeZone: "Asia/Seoul",
    }).format(new Date(iso));
  } catch { return iso; }
}
// datetime-local 값(로컬=KST) → ISO(UTC)
function localToIso(v: string): string { return new Date(v).toISOString(); }
// 날짜만(YYYY-MM-DD) → KST 정오 ISO (all_day/시각없는 todo — 날짜 불변 보장)
function dateToNoonIso(ymd: string): string {
  const [y, m, d] = ymd.split("-").map(Number);
  return new Date(y, m - 1, d, 12, 0, 0).toISOString();
}
// ISO → datetime-local 입력값(YYYY-MM-DDTHH:mm, 로컬)
function isoToLocalInput(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

interface DayItem {
  key: string; time: string; title: string; kind: Kind; cat: Cat; sort: number;
  item?: ScheduleItem;       // 편집 가능(schedule)
  isDone?: boolean;
}

const BLANK = {
  id: 0 as number, kind: "event" as ScheduleKind, category: "meeting" as ScheduleCategory,
  title: "", memo: "",
  customer: null as number | null, dateTime: "", date: "", allDay: false,
  recurWeekday: 1, recurStart: "12:00", recurEnd: "13:00", blockRepeat: true,
};

export default function SchedulePage() {
  const router = useRouter();
  const ready = useAuthGuard();
  const [items, setItems] = useState<ScheduleItem[]>([]);
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [pending, setPending] = useState<Meeting[]>([]);
  const [customers, setCustomers] = useState<CustomerListItem[]>([]);
  const [err, setErr] = useState<string | null>(null);
  // 로더 무음 실패 방지 — 하나라도 실패하면 상단 배너 1개 + 다시 시도(home 페이지와 동일 패턴).
  const [loadFailed, setLoadFailed] = useState(false);

  const now = new Date();
  const [viewY, setViewY] = useState(now.getFullYear());
  const [viewM, setViewM] = useState(now.getMonth() + 1);
  const [selDay, setSelDay] = useState(now.getDate());

  // 추가/수정 모달
  const [modal, setModal] = useState<typeof BLANK | null>(null);
  const [saving, setSaving] = useState(false);

  const monthStr = `${viewY}-${pad(viewM)}`;

  const loadCustomers = useCallback(() => {
    listAllCustomers().then((r) => setCustomers(r)).catch(() => { setCustomers([]); setLoadFailed(true); });
  }, []);

  const load = useCallback(() => {
    setLoadFailed(false);
    listScheduleItems({ month: monthStr })
      .then((r) => setItems(r.results)).catch(() => { setItems([]); setLoadFailed(true); });
    listMeetings(true).then((r) => setMeetings(r.results)).catch(() => { setMeetings([]); setLoadFailed(true); });
    listPendingMeetings().then((r) => setPending(r.results)).catch(() => { setPending([]); setLoadFailed(true); });
  }, [monthStr]);

  // 다시 시도 = 일정 + 고객을 함께 재로드(고객만 실패한 경우도 회복).
  const retryAll = useCallback(() => { load(); loadCustomers(); }, [load, loadCustomers]);

  const acceptPending = useCallback(async (id: number) => {
    setPending((p) => p.filter((m) => m.id !== id));
    try { await acceptMeeting(id); load(); } catch { load(); }
  }, [load]);
  const declinePending = useCallback(async (id: number) => {
    setPending((p) => p.filter((m) => m.id !== id));
    try { await declineMeeting(id); } catch { load(); }
  }, [load]);

  useEffect(() => { if (ready) load(); }, [ready, load]);
  useEffect(() => {
    if (!ready) return;
    loadCustomers();
  }, [ready, loadCustomers]);

  // 날짜별 일정 맵 (반복 차단은 이 달의 해당 요일에 전개)
  const agenda = useMemo(() => {
    const map = new Map<string, DayItem[]>();
    const add = (it: DayItem) => { const a = map.get(it.key) ?? []; a.push(it); map.set(it.key, a); };

    for (const s of items) {
      if (s.kind === "block" && s.recur_weekday !== null) {
        // 반복 차단 — 이 달 모든 해당 요일에 전개(DB row는 1개)
        const dim = new Date(viewY, viewM, 0).getDate();
        const st = (s.recur_start_time || "").slice(0, 5);
        const et = (s.recur_end_time || "").slice(0, 5);
        for (let d = 1; d <= dim; d++) {
          if (pyWeekday(new Date(viewY, viewM - 1, d)) === s.recur_weekday) {
            add({ key: `${monthStr}-${pad(d)}`, time: st || "종일", sort: st ? Number(st.replace(":", "")) : -1,
              title: `${s.title} (${st}~${et}, 예약불가)`, kind: "block", cat: "etc", item: s });
          }
        }
        continue;
      }
      // 생일·기념일: anniversary_md(MM-DD)로 매년 반복 — 이 달이면 해당 일에 표시
      if (s.category === "anniversary" && s.anniversary_md) {
        const [mm, dd] = s.anniversary_md.split("-");
        if (mm === pad(viewM)) {
          add({ key: `${monthStr}-${dd}`, time: "종일", sort: -1,
            title: `🎂 ${s.title}`, kind: "event", cat: "anniversary", item: s });
        }
        continue;
      }
      if (!s.start_at) continue;
      const ymd = kstYmd(s.start_at);
      const tm = s.all_day ? "종일" : kstTime(s.start_at);
      add({ key: ymd, time: tm || "종일", sort: tm && tm !== "종일" ? Number(tm.replace(":", "")) : -1,
        title: s.title, kind: s.kind, cat: s.category, item: s, isDone: s.kind === "todo" ? s.is_done : undefined });
    }
    for (const m of meetings) {
      const t = kstTime(m.start_at);
      add({ key: kstYmd(m.start_at), time: t || "-", sort: t ? Number(t.replace(":", "")) : 0,
        title: `${m.customer_name} · ${m.method_display}`, kind: "meeting", cat: "meeting" });
    }
    for (const [, arr] of map) arr.sort((a, b) => a.sort - b.sort);
    return map;
  }, [items, meetings, viewY, viewM, monthStr]);

  function shiftMonth(delta: number) {
    let y = viewY, m = viewM + delta;
    if (m < 1) { m = 12; y--; }
    if (m > 12) { m = 1; y++; }
    setViewY(y); setViewM(m); setSelDay(1);
  }

  const selYmd = `${monthStr}-${pad(selDay)}`;
  const selectedItems = agenda.get(selYmd) ?? [];

  function openAdd() {
    setErr(null);
    setModal({ ...BLANK, date: selYmd, dateTime: `${selYmd}T10:00` });
  }
  function openEdit(s: ScheduleItem) {
    setErr(null);
    if (s.kind === "block" && s.recur_weekday !== null) {
      setModal({ ...BLANK, id: s.id, kind: "block", category: s.category, title: s.title, memo: s.memo, blockRepeat: true,
        recurWeekday: s.recur_weekday, recurStart: (s.recur_start_time || "12:00").slice(0, 5),
        recurEnd: (s.recur_end_time || "13:00").slice(0, 5) });
      return;
    }
    setModal({
      ...BLANK, id: s.id, kind: s.kind, category: s.category, title: s.title, memo: s.memo, customer: s.customer,
      allDay: s.all_day, blockRepeat: false,
      date: s.start_at ? kstYmd(s.start_at) : selYmd,
      dateTime: s.start_at ? isoToLocalInput(s.start_at) : `${selYmd}T10:00`,
    });
  }

  async function save() {
    if (!modal) return;
    if (!modal.title.trim()) { setErr("제목을 입력해주세요."); return; }
    setSaving(true); setErr(null);
    try {
      let payload: Parameters<typeof createScheduleItem>[0];
      if (modal.kind === "block" && modal.blockRepeat) {
        payload = { kind: "block", category: "etc", title: modal.title.trim(), memo: modal.memo,
          recur_weekday: modal.recurWeekday, recur_start_time: modal.recurStart, recur_end_time: modal.recurEnd };
      } else if (modal.kind === "todo") {
        payload = { kind: "todo", category: modal.category, title: modal.title.trim(), memo: modal.memo,
          customer: modal.customer, start_at: modal.date ? dateToNoonIso(modal.date) : null, all_day: true };
      } else {
        // event 또는 단건 block
        const startIso = modal.allDay ? dateToNoonIso(modal.date) : localToIso(modal.dateTime);
        const annivMd = modal.category === "anniversary" && modal.date ? modal.date.slice(5) : "";
        payload = { kind: modal.kind, category: modal.category, anniversary_md: annivMd,
          title: modal.title.trim(), memo: modal.memo,
          customer: modal.kind === "event" ? modal.customer : null,
          start_at: startIso, all_day: modal.allDay };
      }
      if (modal.id) await updateScheduleItem(modal.id, payload);
      else await createScheduleItem(payload);
      setModal(null);
      load();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "저장에 실패했어요.");
    } finally { setSaving(false); }
  }

  async function toggleDone(s: ScheduleItem) {
    setErr(null);
    try { await toggleScheduleDone(s.id); load(); }
    catch (e) { setErr(e instanceof ApiError ? e.message : "완료 처리에 실패했어요. 잠시 후 다시 시도하세요."); }
  }
  async function remove(id: number) {
    setErr(null);
    try { await deleteScheduleItem(id); setModal(null); load(); }
    catch (e) { setErr(e instanceof ApiError ? e.message : "삭제에 실패했어요. 잠시 후 다시 시도하세요."); }
  }

  if (!ready) return null;

  // 캘린더 셀
  const first = new Date(viewY, viewM - 1, 1).getDay();
  const days = new Date(viewY, viewM, 0).getDate();
  const cells: (number | null)[] = [...Array(first).fill(null), ...Array.from({ length: days }, (_, i) => i + 1)];
  const isCurMonth = now.getFullYear() === viewY && now.getMonth() + 1 === viewM;
  const todayD = now.getDate();

  return (
    <div className="min-h-dvh">
      <AppNav active="schedule" />
      <main className="mx-auto max-w-[1440px] px-4 sm:px-6 py-6">
        <h1 className="text-[22px] font-extrabold text-ink mb-4">일정</h1>

        {/* 로더 실패 통합 배너 — 하나라도 못 불러오면 여기 1개 + 다시 시도(빈 캘린더로 오인 방지) */}
        {loadFailed && (
          <div
            role="alert"
            className="mb-4 flex items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 px-3.5 py-2.5 text-[13px]"
          >
            <span className="text-amber-800">일정을 못 불러왔어요.</span>
            <button
              type="button"
              onClick={retryAll}
              className="shrink-0 rounded-lg bg-surface px-3 py-1.5 text-[12px] font-semibold text-brand border border-line hover:border-brand transition"
            >
              다시 시도
            </button>
          </div>
        )}

        {/* 예약 요청(대기) — 알림을 놓쳐도 여기서 수락/거절 */}
        {pending.length > 0 && (
          <Card className="mb-4 p-4 border-brand/30">
            <div className="text-[14px] font-bold text-ink">예약 요청 {pending.length}건 · 수락 대기</div>
            <p className="mt-0.5 text-[12px] text-ink3">고객이 신청한 시간이에요. 수락하면 일정에 확정됩니다.</p>
            <div className="mt-3 space-y-2">
              {pending.map((m) => (
                <div key={m.id} className="flex items-center gap-2 rounded-xl border border-line bg-surface px-3 py-2.5">
                  <div className="flex-1 min-w-0">
                    <div className="text-[14px] font-semibold text-ink truncate">{m.customer_name} · {m.method_display}</div>
                    <div className="text-[12px] text-ink3">{fmtMeetingTime(m.start_at)}</div>
                  </div>
                  <button onClick={() => acceptPending(m.id)}
                    className="shrink-0 rounded-lg bg-brand text-white text-[12px] font-bold px-3 py-1.5">수락</button>
                  <button onClick={() => declinePending(m.id)}
                    className="shrink-0 rounded-lg border border-line text-ink2 text-[12px] font-semibold px-3 py-1.5 hover:bg-surface2">거절</button>
                </div>
              ))}
            </div>
          </Card>
        )}
        {err && !modal && (
          <div className="mb-3 rounded-xl border border-danger/30 bg-danger-tint px-4 py-2 text-[13px] text-danger">{err}</div>
        )}

        <div className="lg:grid lg:grid-cols-3 lg:gap-5">
          {/* 캘린더 */}
          <Card className="lg:col-span-2 p-4 sm:p-5">
            <div className="flex items-center justify-between mb-3">
              <button onClick={() => shiftMonth(-1)} className="w-8 h-8 rounded-lg hover:bg-surface2 text-ink2 text-[18px]">‹</button>
              <div className="text-[16px] font-bold text-ink">{viewY}년 {viewM}월</div>
              <button onClick={() => shiftMonth(1)} className="w-8 h-8 rounded-lg hover:bg-surface2 text-ink2 text-[18px]">›</button>
            </div>
            <div className="grid grid-cols-7 text-center text-[12px] mb-1">
              {WEEK.map((w, i) => <div key={w} className={i === 0 ? "text-danger" : "text-ink3"}>{w}</div>)}
            </div>
            <div className="grid grid-cols-7">
              {cells.map((d, i) => {
                if (!d) return <div key={i} />;
                const isSun = i % 7 === 0;
                const isToday = isCurMonth && d === todayD;
                const isSel = d === selDay;
                let cls = isSun ? "text-danger" : "text-ink2";
                if (isToday && !isSel) cls = "text-brand font-bold";
                if (isSel) cls = "bg-brand text-white font-bold";
                const ymd = `${monthStr}-${pad(d)}`;
                const dayItems = agenda.get(ymd);
                const hasBlock = dayItems?.some((it) => it.kind === "block");
                const cats = dayItems ? Array.from(new Set(dayItems.map((it) => it.cat))).slice(0, 4) : [];
                return (
                  <div key={i} className={`flex flex-col items-center pt-1.5 pb-1 min-h-[56px] rounded-lg ${hasBlock ? "bg-surface2/60" : ""}`}>
                    <button onClick={() => setSelDay(d)}
                      className={`w-9 h-9 rounded-full flex items-center justify-center text-[14px] font-medium ${cls}`}>{d}</button>
                    {cats.length > 0 && (
                      <div className="flex gap-0.5 mt-1">
                        {cats.map((c, j) => <span key={j} className={`w-1.5 h-1.5 rounded-full ${CAT_META[c].dot}`} />)}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
            <div className="mt-3 flex flex-wrap gap-3 text-[12px] text-ink3">
              {(Object.keys(CAT_META) as Cat[]).map((c) => (
                <span key={c} className="inline-flex items-center gap-1.5">
                  <span className={`w-2 h-2 rounded-full ${CAT_META[c].dot}`} />{CAT_META[c].label}
                </span>
              ))}
            </div>
          </Card>

          {/* 선택일 패널 */}
          <Card className="mt-4 lg:mt-0 p-4 sm:p-5">
            <div className="flex items-center justify-between mb-3">
              <div className="text-[15px] font-bold text-ink">{viewM}월 {selDay}일</div>
              <button onClick={openAdd} className="rounded-lg bg-brand text-white text-[13px] font-bold px-3 py-1.5">+ 추가</button>
            </div>
            {selectedItems.length > 0 ? (
              <div className="space-y-2.5">
                {selectedItems.map((t, i) => {
                  const editable = !!t.item;
                  return (
                    <div key={i} className="flex gap-2.5 items-start">
                      <div className="text-[12px] font-semibold text-ink3 w-11 shrink-0 tnum pt-0.5">{t.time}</div>
                      {t.kind === "todo" && t.item ? (
                        <button onClick={() => toggleDone(t.item!)} aria-label="완료 토글"
                          className={`mt-0.5 w-4 h-4 rounded border shrink-0 ${t.isDone ? "bg-brand border-brand" : "border-line"}`}>
                          {t.isDone && <span className="text-white text-[10px] leading-none">✓</span>}
                        </button>
                      ) : (
                        <span className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${CAT_META[t.cat].dot}`} />
                      )}
                      <button disabled={!editable} onClick={() => editable && openEdit(t.item!)}
                        className={`flex-1 text-left text-[14px] leading-5 ${t.isDone ? "line-through text-ink3" : "text-ink"} ${editable ? "hover:text-brand" : ""}`}>
                        {t.title}
                      </button>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="py-6 text-center text-[13px] text-ink3">이 날 일정이 없어요.<div className="text-[12px] mt-1">+ 추가로 일정·할일·차단을 넣어보세요.</div></div>
            )}
          </Card>
        </div>

        {/* 예약 가용시간 관리 — 가로 카드 */}
        <button
          onClick={() => router.push("/settings/meetings")}
          className="mt-6 w-full flex items-center justify-between gap-3 rounded-2xl border border-line bg-surface px-5 py-4 text-left shadow-card hover:border-brand transition"
        >
          <div className="min-w-0">
            <div className="text-[15px] font-bold text-ink">예약 가용시간 관리</div>
            <div className="mt-0.5 text-[13px] text-ink3">상담 받을 요일과 시간을 정해두면, 고객이 빈 시간에 바로 예약할 수 있어요.</div>
          </div>
          <span className="shrink-0 text-[13px] font-semibold text-brand">관리 →</span>
        </button>

        {/* 예약(가용시간) 받기 — 공유문구 + 설정 */}
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <AvailabilityShare />
          <BookingSettings />
        </div>
      </main>

      {/* 추가/수정 모달 */}
      {modal && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-end sm:items-center justify-center p-0 sm:p-4" onClick={() => setModal(null)}>
          <div className="bg-surface w-full sm:max-w-md rounded-t-2xl sm:rounded-2xl p-5 max-h-[90dvh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="text-[17px] font-bold text-ink mb-3">{modal.id ? "수정" : "추가"}</div>
            {!modal.id && (
              <div className="grid grid-cols-3 gap-1.5 mb-4">
                {CAT_OPTIONS.map((o) => {
                  const active = modal.category === o.cat && modal.kind !== "block";
                  return (
                    <button key={o.cat}
                      onClick={() => setModal({ ...modal, category: o.cat, kind: o.kind, allDay: o.allDay ?? modal.allDay })}
                      className={`rounded-lg py-2 text-[12px] font-semibold ${active ? "bg-brand text-white" : "bg-surface2 text-ink2"}`}>
                      {o.label}
                    </button>
                  );
                })}
                <button
                  onClick={() => setModal({ ...modal, kind: "block", category: "etc", blockRepeat: true })}
                  className={`rounded-lg py-2 text-[12px] font-semibold ${modal.kind === "block" ? "bg-brand text-white" : "bg-surface2 text-ink2"}`}>
                  예약차단
                </button>
              </div>
            )}
            {err && <div className="mb-3 rounded-lg bg-danger-tint text-danger text-[13px] px-3 py-2">{err}</div>}

            <label className="block mb-3">
              <span className="text-[12px] text-ink3">제목</span>
              <input value={modal.title} onChange={(e) => setModal({ ...modal, title: e.target.value })}
                placeholder={modal.kind === "block" ? "예) 점심·외근" : modal.kind === "todo" ? "예) 갱신 안내 전화" : "예) OO고객 미팅"}
                className="mt-1 w-full rounded-xl border border-line px-3 py-2.5 text-[14px]" />
            </label>

            {modal.kind === "block" ? (
              <>
                <div className="flex gap-1.5 mb-3">
                  <button onClick={() => setModal({ ...modal, blockRepeat: true })}
                    className={`flex-1 rounded-lg py-2 text-[13px] font-semibold ${modal.blockRepeat ? "bg-brand-soft text-brand" : "bg-surface2 text-ink2"}`}>매주 반복</button>
                  <button onClick={() => setModal({ ...modal, blockRepeat: false })}
                    className={`flex-1 rounded-lg py-2 text-[13px] font-semibold ${!modal.blockRepeat ? "bg-brand-soft text-brand" : "bg-surface2 text-ink2"}`}>이번 한 번</button>
                </div>
                {modal.blockRepeat ? (
                  <>
                    <label className="block mb-3">
                      <span className="text-[12px] text-ink3">요일</span>
                      <div className="mt-1 flex gap-1">
                        {["월", "화", "수", "목", "금", "토", "일"].map((w, idx) => (
                          <button key={w} onClick={() => setModal({ ...modal, recurWeekday: idx })}
                            className={`flex-1 rounded-lg py-2 text-[13px] font-semibold ${modal.recurWeekday === idx ? "bg-brand text-white" : "bg-surface2 text-ink2"}`}>{w}</button>
                        ))}
                      </div>
                    </label>
                    <div className="flex gap-2 mb-3">
                      <label className="flex-1"><span className="text-[12px] text-ink3">시작</span>
                        <input type="time" value={modal.recurStart} onChange={(e) => setModal({ ...modal, recurStart: e.target.value })}
                          className="mt-1 w-full rounded-xl border border-line px-3 py-2 text-[14px]" /></label>
                      <label className="flex-1"><span className="text-[12px] text-ink3">종료</span>
                        <input type="time" value={modal.recurEnd} onChange={(e) => setModal({ ...modal, recurEnd: e.target.value })}
                          className="mt-1 w-full rounded-xl border border-line px-3 py-2 text-[14px]" /></label>
                    </div>
                  </>
                ) : (
                  <label className="block mb-3"><span className="text-[12px] text-ink3">날짜·시간</span>
                    <input type="datetime-local" value={modal.dateTime} onChange={(e) => setModal({ ...modal, dateTime: e.target.value })}
                      className="mt-1 w-full rounded-xl border border-line px-3 py-2 text-[14px]" /></label>
                )}
              </>
            ) : modal.kind === "todo" ? (
              <label className="block mb-3"><span className="text-[12px] text-ink3">마감일(선택)</span>
                <input type="date" value={modal.date} onChange={(e) => setModal({ ...modal, date: e.target.value })}
                  className="mt-1 w-full rounded-xl border border-line px-3 py-2 text-[14px]" /></label>
            ) : (
              <>
                <label className="flex items-center justify-between mb-3">
                  <span className="text-[13px] text-ink2">온종일</span>
                  <button onClick={() => setModal({ ...modal, allDay: !modal.allDay })}
                    className={`relative w-11 h-6 rounded-full transition ${modal.allDay ? "bg-brand" : "bg-line"}`}>
                    <span className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition-all ${modal.allDay ? "left-[22px]" : "left-0.5"}`} />
                  </button>
                </label>
                {modal.allDay ? (
                  <label className="block mb-3"><span className="text-[12px] text-ink3">날짜</span>
                    <input type="date" value={modal.date} onChange={(e) => setModal({ ...modal, date: e.target.value })}
                      className="mt-1 w-full rounded-xl border border-line px-3 py-2 text-[14px]" /></label>
                ) : (
                  <label className="block mb-3"><span className="text-[12px] text-ink3">날짜·시간</span>
                    <input type="datetime-local" value={modal.dateTime} onChange={(e) => setModal({ ...modal, dateTime: e.target.value })}
                      className="mt-1 w-full rounded-xl border border-line px-3 py-2 text-[14px]" /></label>
                )}
                <label className="block mb-3"><span className="text-[12px] text-ink3">고객 연결(선택)</span>
                  <select value={modal.customer ?? ""} onChange={(e) => setModal({ ...modal, customer: e.target.value ? Number(e.target.value) : null })}
                    className="mt-1 w-full rounded-xl border border-line px-3 py-2.5 text-[14px] bg-surface">
                    <option value="">연결 안 함</option>
                    {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select></label>
              </>
            )}

            <label className="block mb-4"><span className="text-[12px] text-ink3">메모(선택)</span>
              <textarea value={modal.memo} onChange={(e) => setModal({ ...modal, memo: e.target.value })} rows={2}
                className="mt-1 w-full rounded-xl border border-line px-3 py-2 text-[14px]" /></label>

            <div className="flex gap-2">
              <button disabled={saving} onClick={save}
                className="flex-1 rounded-xl bg-brand text-white text-[14px] font-bold py-3 disabled:opacity-60">{saving ? "저장 중…" : "저장"}</button>
              {modal.id ? (
                <button onClick={() => remove(modal.id)} className="rounded-xl border border-danger/30 text-danger text-[14px] font-semibold px-4 py-3">삭제</button>
              ) : (
                <button onClick={() => setModal(null)} className="rounded-xl border border-line text-ink2 text-[14px] font-semibold px-4 py-3">취소</button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
