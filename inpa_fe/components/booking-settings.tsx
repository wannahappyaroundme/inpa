"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { BookingCustomerPicker } from "@/components/booking-customer-picker";
import { BookingMessageComposer } from "@/components/booking-message-composer";
import { Card } from "@/components/ui";
import {
  createWorkHour, deleteWorkHour, getProfile, listWorkHours, updateProfile, SALES_STAGES,
  type BookingCustomerListItem, type WorkHour,
} from "@/lib/api";
import {
  bookingSettingsPayload, isSameBookingSettings, profileToBookingSettings,
  type BookingSettingsDraft,
} from "@/lib/booking-settings-state";

const WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"];
const DEFAULT_TPL_PLACEHOLDER =
  "{고객명} 고객님, 안녕하세요. {소속직책} {설계사명} 보험설계사입니다.\n" +
  "가능하신 날짜를 선택해 주시면 자세한 보험 상담을 도와드리겠습니다.\n" +
  "아래 링크에서 편하신 시간을 골라주세요 👇\n{링크}";

type ProfileLoadStatus = "loading" | "success" | "error";
type WorkHourLoadStatus = "loading" | "success" | "error";

function maskCustomerPhone(phone: string | null): string {
  const digits = phone?.replace(/\D/g, "") ?? "";
  return digits.length >= 8 ? `${digits.slice(0, 3)}-****-${digits.slice(-4)}` : "연락처 일부 숨김";
}

function customerStage(customer: BookingCustomerListItem): string {
  return SALES_STAGES.find((stage) => stage.key === customer.sales_stage)?.label ?? "";
}

export function BookingSettings() {
  const [profileStatus, setProfileStatus] = useState<ProfileLoadStatus>("loading");
  const [draft, setDraft] = useState<BookingSettingsDraft | null>(null);
  const [savedSnapshot, setSavedSnapshot] = useState<BookingSettingsDraft | null>(null);
  const [saving, setSaving] = useState(false);
  const [composerBusy, setComposerBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [selectedCustomer, setSelectedCustomer] = useState<BookingCustomerListItem | null>(null);

  const [workHourStatus, setWorkHourStatus] = useState<WorkHourLoadStatus>("loading");
  const [workHours, setWorkHours] = useState<WorkHour[]>([]);
  const [whWeekday, setWhWeekday] = useState(0);
  const [whStart, setWhStart] = useState("09:00");
  const [whEnd, setWhEnd] = useState("18:00");
  const [whErr, setWhErr] = useState<string | null>(null);
  const mountedRef = useRef(true);
  const profileRequestGeneration = useRef(0);
  const workHourRequestGeneration = useRef(0);
  const draftRef = useRef<BookingSettingsDraft | null>(null);

  const replaceDraft = useCallback((nextDraft: BookingSettingsDraft) => {
    draftRef.current = nextDraft;
    setDraft(nextDraft);
  }, []);

  const loadProfile = useCallback(async () => {
    const generation = ++profileRequestGeneration.current;
    setProfileStatus("loading");
    setMessage(null);
    try {
      const nextDraft = profileToBookingSettings(await getProfile());
      if (!mountedRef.current || generation !== profileRequestGeneration.current) return;
      replaceDraft(nextDraft);
      setSavedSnapshot(nextDraft);
      setProfileStatus("success");
    } catch {
      if (!mountedRef.current || generation !== profileRequestGeneration.current) return;
      setProfileStatus("error");
    }
  }, [replaceDraft]);

  const loadWorkHours = useCallback(async (): Promise<"success" | "failure" | "stale"> => {
    const generation = ++workHourRequestGeneration.current;
    setWorkHourStatus("loading");
    setWhErr(null);
    try {
      const response = await listWorkHours();
      if (!mountedRef.current || generation !== workHourRequestGeneration.current) return "stale";
      setWorkHours(response.results);
      setWorkHourStatus("success");
      return "success";
    } catch {
      if (!mountedRef.current || generation !== workHourRequestGeneration.current) return "stale";
      setWorkHourStatus("error");
      return "failure";
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    void loadProfile();
    void loadWorkHours();
    return () => {
      mountedRef.current = false;
      profileRequestGeneration.current += 1;
      workHourRequestGeneration.current += 1;
    };
  }, [loadProfile, loadWorkHours]);

  const saveSettings = useCallback(async ({ announce = true }: { announce?: boolean } = {}) => {
    const requestDraft = draftRef.current;
    if (!requestDraft || !savedSnapshot) throw new Error("PROFILE_NOT_READY");
    if (isSameBookingSettings(requestDraft, savedSnapshot)) {
      if (announce) setMessage("저장된 설정이에요.");
      return;
    }

    setSaving(true);
    if (announce) setMessage(null);
    try {
      const updated = await updateProfile(bookingSettingsPayload(requestDraft));
      const nextSnapshot = profileToBookingSettings(updated);
      setSavedSnapshot(nextSnapshot);
      if (draftRef.current && isSameBookingSettings(draftRef.current, requestDraft)) {
        replaceDraft(nextSnapshot);
      }
      if (announce) setMessage("예약 설정을 저장했어요.");
    } catch (error) {
      if (announce) setMessage("저장에 실패했어요. 입력한 내용은 그대로 있어요.");
      throw error;
    } finally {
      setSaving(false);
    }
  }, [replaceDraft, savedSnapshot]);

  const addWorkHour = useCallback(async () => {
    if (workHourStatus !== "success") return;
    setWhErr(null);
    if (whStart >= whEnd) {
      setWhErr("종료가 시작보다 늦어야 해요.");
      return;
    }
    try {
      const workHour = await createWorkHour({ weekday: whWeekday, start_time: whStart, end_time: whEnd });
      setWorkHours((current) => [...current, workHour].sort((a, b) =>
        a.weekday - b.weekday || a.start_time.localeCompare(b.start_time)));
    } catch {
      setWhErr("추가에 실패했어요. 다시 시도해 주세요.");
    }
  }, [whEnd, whStart, whWeekday, workHourStatus]);

  const removeWorkHour = useCallback(async (id: number) => {
    if (workHourStatus !== "success") return;
    setWhErr(null);
    setWorkHours((current) => current.filter((workHour) => workHour.id !== id));
    try {
      await deleteWorkHour(id);
    } catch {
      const recovery = await loadWorkHours();
      if (recovery === "stale") return;
      if (recovery === "success") {
        setWhErr("삭제를 다시 확인했어요.");
      } else {
        setWorkHourStatus("error");
        setWhErr("삭제 상태를 확인하지 못했어요. 업무시간을 다시 불러와 현재 상태를 확인해 주세요.");
      }
    }
  }, [loadWorkHours, workHourStatus]);

  const inputCls = "min-h-11 rounded-xl border border-line px-3 py-2 text-[14px] disabled:bg-surface disabled:text-ink3";

  if (profileStatus === "loading") {
    return (
      <Card className="px-5 py-4" aria-busy="true">
        <div className="text-[15px] font-bold text-ink">예약 설정</div>
        <div data-testid="booking-settings-skeleton" className="mt-4 animate-pulse space-y-3" aria-label="예약 설정을 불러오고 있어요.">
          <div className="h-11 rounded-xl bg-surface2" />
          <div className="h-28 rounded-xl bg-surface2" />
          <div className="h-11 rounded-xl bg-surface2" />
        </div>
        <button disabled className="mt-4 min-h-11 rounded-xl bg-brand px-4 text-[13px] font-bold text-white disabled:opacity-60">예약 설정 저장</button>
        <button disabled className="mt-3 min-h-11 w-full rounded-xl bg-brand px-4 text-[14px] font-bold text-white disabled:opacity-60">고객에게 보낼 문구 만들기</button>
      </Card>
    );
  }

  if (profileStatus === "error") {
    return (
      <Card className="px-5 py-4">
        <div className="text-[15px] font-bold text-ink">예약 설정</div>
        <div role="alert" className="mt-4 rounded-xl bg-danger-tint px-3 py-3 text-[13px] text-danger-ink">
          예약 설정을 불러오지 못했어요. 다시 불러오면 이어서 설정할 수 있어요.
        </div>
        <button type="button" onClick={() => void loadProfile()} className="mt-3 min-h-11 rounded-xl border border-brand px-4 text-[13px] font-bold text-brand">다시 불러오기</button>
      </Card>
    );
  }

  if (!draft) return null;

  return (
    <Card className="px-5 py-4">
      <div className="text-[15px] font-bold text-ink">예약 기본 설정</div>
      <p className="mt-1 text-[12px] leading-5 text-ink3">업무시간을 정해두면 비어 있는 시간만 고객에게 보여요.</p>
      {message && <div role="status" className="mt-3 rounded-xl bg-accent-tint px-3 py-2 text-[13px] text-brand">{message}</div>}

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <label className="block"><span className="text-[12px] text-ink3">내 이름</span><input disabled={composerBusy} value={draft.name} onChange={(event) => replaceDraft({ ...draft, name: event.target.value })} placeholder="예) 홍길동" className={`mt-1 w-full ${inputCls}`} /></label>
        <label className="block"><span className="text-[12px] text-ink3">소속</span><input disabled={composerBusy} value={draft.affiliation} onChange={(event) => replaceDraft({ ...draft, affiliation: event.target.value })} placeholder="예) 부산지점" className={`mt-1 w-full ${inputCls}`} /></label>
        <label className="block"><span className="text-[12px] text-ink3">직책</span><input disabled={composerBusy} value={draft.title} onChange={(event) => replaceDraft({ ...draft, title: event.target.value })} placeholder="예) FC, 팀장" className={`mt-1 w-full ${inputCls}`} /></label>
      </div>

      <label className="mt-4 block"><span className="text-[12px] text-ink3">예약 안내 문구</span><textarea disabled={composerBusy} value={draft.template} onChange={(event) => replaceDraft({ ...draft, template: event.target.value })} rows={4} placeholder={DEFAULT_TPL_PLACEHOLDER} className="mt-1 w-full rounded-xl border border-line px-3 py-2 text-[13px] leading-5 disabled:bg-surface disabled:text-ink3" /></label>
      <p className="mt-1 text-[12px] leading-5 text-ink3">문구에 넣을 수 있는 내용: <b>{"{고객명}"} · {"{소속직책}"} · {"{설계사명}"} · {"{링크}"}</b>. 기본 문구는 입력 전 안내용이며, 고객에게 보낼 문구는 실제 생성 결과로만 보여요.</p>

      <div className="mt-5">
        <div className="text-[13px] font-bold text-ink">업무시간</div>
        <p className="mt-0.5 text-[12px] leading-5 text-ink3">이 시간 안에서 미팅과 여유 시간을 뺀 빈 시간만 고객에게 보여요.</p>
        {workHourStatus === "loading" && <p role="status" className="mt-2 text-[12px] text-ink3">업무시간을 불러오고 있어요.</p>}
        {workHourStatus === "error" && <div role="alert" className="mt-2 rounded-xl bg-danger-tint px-3 py-2 text-[12px] text-danger-ink">업무시간을 불러오지 못했어요.<button type="button" onClick={() => void loadWorkHours()} className="ml-2 min-h-11 font-bold underline">업무시간 다시 불러오기</button></div>}
        {workHourStatus === "success" && workHours.length > 0 && <div className="mt-2 flex flex-wrap gap-2">{workHours.map((workHour) => <span key={workHour.id} className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1 text-[12px] text-ink2">{WEEKDAYS[workHour.weekday]} {workHour.start_time.slice(0, 5)}~{workHour.end_time.slice(0, 5)}<button type="button" onClick={() => void removeWorkHour(workHour.id)} aria-label="삭제" className="min-h-11 text-ink3 hover:text-rose-600">✕</button></span>)}</div>}
        <div className="mt-2 flex flex-wrap items-end gap-2"><select aria-label="업무 요일" disabled={workHourStatus !== "success"} value={whWeekday} onChange={(event) => setWhWeekday(Number(event.target.value))} className={inputCls}>{WEEKDAYS.map((weekday, index) => <option key={weekday} value={index}>{weekday}요일</option>)}</select><input aria-label="업무 시작 시간" disabled={workHourStatus !== "success"} type="time" value={whStart} onChange={(event) => setWhStart(event.target.value)} className={inputCls} /><span className="text-ink3">~</span><input aria-label="업무 종료 시간" disabled={workHourStatus !== "success"} type="time" value={whEnd} onChange={(event) => setWhEnd(event.target.value)} className={inputCls} /><button type="button" disabled={workHourStatus !== "success"} onClick={() => void addWorkHour()} className="min-h-11 rounded-xl border border-brand px-3 text-[13px] font-semibold text-brand disabled:opacity-60">+ 추가</button></div>
        {whErr && <div role="alert" className="mt-2 text-[12px] text-danger-ink">{whErr}</div>}
      </div>

      <label className="mt-5 block"><span className="text-[12px] text-ink3">대면 미팅 장소</span><input disabled={composerBusy} value={draft.location} onChange={(event) => replaceDraft({ ...draft, location: event.target.value })} placeholder="예) 부산 서면 스타벅스 1층" className={`mt-1 w-full ${inputCls}`} /></label>
      <div className="mt-5 flex flex-wrap items-end gap-3"><label className="flex flex-col gap-1"><span className="text-[12px] text-ink3">미팅 시간(분)</span><input disabled={composerBusy} type="number" min={10} max={240} value={draft.duration} onChange={(event) => replaceDraft({ ...draft, duration: Number(event.target.value) || 30 })} className="min-h-11 w-24 rounded-xl border border-line px-3 text-center text-[14px] tnum" /></label><label className="flex flex-col gap-1"><span className="text-[12px] text-ink3">앞뒤 여유(분, 이동시간)</span><input disabled={composerBusy} type="number" min={0} max={180} step={15} value={draft.buffer} onChange={(event) => replaceDraft({ ...draft, buffer: Number(event.target.value) || 0 })} className="min-h-11 w-24 rounded-xl border border-line px-3 text-center text-[14px] tnum" /></label><button type="button" disabled={saving || composerBusy} onClick={() => void saveSettings().catch(() => undefined)} className="min-h-11 rounded-xl bg-brand px-4 text-[13px] font-bold text-white disabled:opacity-60">예약 설정 저장</button></div>

      <section className="mt-7 border-t border-line pt-5" aria-labelledby="booking-message-title">
        <h2 id="booking-message-title" className="text-[15px] font-bold text-ink">고객에게 예약 안내 보내기</h2>
        <p className="mt-1 text-[12px] leading-5 text-ink3">고객을 고르면 실제 예약 링크와 안내 문구를 바로 만들 수 있어요.</p>
        <div className="mt-4"><BookingCustomerPicker value={selectedCustomer} onChange={setSelectedCustomer} disabled={saving || composerBusy} /></div>
        {selectedCustomer && <p className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-xl bg-surface2 px-3 py-2 text-[13px] text-ink2"><b className="text-ink">{selectedCustomer.name}</b><span>{maskCustomerPhone(selectedCustomer.mobile_phone_number)}</span><span className="rounded-md bg-white px-2 py-0.5 text-[12px] font-bold text-ink2">{customerStage(selectedCustomer)}</span><span>고객에게 보낼 안내를 준비하고 있어요.</span></p>}
        <div className="mt-3"><BookingMessageComposer customerId={selectedCustomer?.id ?? null} prepare={() => saveSettings({ announce: false })} disabled={saving || composerBusy} onBusyChange={setComposerBusy} /></div>
      </section>
    </Card>
  );
}
