"use client";

// 미팅 예약 공개 페이지(비로그인) — 고객이 설계사 가용 슬롯에서 시간을 직접 고른다.
// ★ 마스킹 이름만 표시(PII 미노출). 슬롯 선택+방식 선택 후 확정. 409=이미 예약됨 → 슬롯 새로고침.

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import { Card } from "@/components/ui";
import {
  getBookingInfo,
  submitBooking,
  ApiError,
  type PublicBookingInfo,
  type MeetingMethod,
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

export default function PublicBookingPage() {
  const params = useParams();
  const token = typeof params?.token === "string" ? params.token : "";

  const [info, setInfo] = useState<PublicBookingInfo | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [slotId, setSlotId] = useState<number | null>(null);
  const [method, setMethod] = useState<MeetingMethod | null>(null);
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [done, setDone] = useState<{ start_at: string; location_detail: string; method: MeetingMethod } | null>(null);

  const load = useCallback(() => {
    if (!token) return;
    getBookingInfo(token)
      .then(setInfo)
      .catch((e: unknown) =>
        setLoadError(e instanceof ApiError ? e.message : "예약 페이지를 열 수 없어요. 담당 설계사에게 새 링크를 요청해 주세요.")
      );
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const submit = useCallback(async () => {
    if (slotId === null || method === null) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const r = await submitBooking(token, { slot_id: slotId, method, note: note.trim() || undefined });
      setDone({ start_at: r.start_at, location_detail: r.location_detail, method: r.method });
    } catch (e: unknown) {
      if (e instanceof ApiError && e.status === 409) {
        setSubmitError("앗, 방금 그 시간이 마감됐어요. 다른 시간을 골라주세요.");
        setSlotId(null);
        load(); // 슬롯 목록 새로고침(마감 슬롯 사라짐)
      } else {
        setSubmitError(e instanceof ApiError ? e.message : "예약에 실패했어요. 잠시 후 다시 시도해 주세요.");
      }
    } finally {
      setSubmitting(false);
    }
  }, [token, slotId, method, note, load]);

  // ── 만료/위조 ──
  if (loadError) {
    return (
      <div className="mx-auto w-full max-w-md min-h-dvh bg-surface2 flex items-center justify-center px-5">
        <Card className="px-6 py-8 text-center">
          <div className="text-[15px] font-bold text-ink">링크를 열 수 없어요</div>
          <p className="mt-2 text-[13px] text-ink3 leading-5">{loadError}</p>
        </Card>
      </div>
    );
  }

  // ── 완료 ──
  if (done) {
    const methodLabel = info?.methods.find((m) => m.key === done.method)?.label ?? "";
    return (
      <div className="mx-auto w-full max-w-md min-h-dvh bg-surface2">
        <header className="px-5 pt-5 pb-3 bg-accent-tint">
          <div className="text-[13px] font-bold text-brand">⌃ 인파 상담 예약</div>
        </header>
        <main className="px-5 pb-10 flex flex-col items-center text-center">
          <div className="mt-16 text-[40px]">📅</div>
          <h1 className="mt-4 text-[20px] font-extrabold text-ink">예약이 확정됐어요</h1>
          <p className="mt-2 text-[15px] font-semibold text-ink">{fmtKST(done.start_at)} · {methodLabel}</p>
          {done.location_detail && (
            <p className="mt-1 text-[13px] text-ink3">장소: {done.location_detail}</p>
          )}
          <p className="mt-3 text-[14px] text-ink3 leading-6">
            담당 설계사가 곧 연락드릴 거예요. 이 창은 닫으셔도 됩니다.
          </p>
        </main>
      </div>
    );
  }

  // ── 로딩 ──
  if (!info) {
    return (
      <div className="mx-auto w-full max-w-md min-h-dvh bg-surface2 flex items-center justify-center">
        <div className="text-[13px] text-ink3">불러오는 중…</div>
      </div>
    );
  }

  const inPersonSelected = method === "in_person";
  const canSubmit = slotId !== null && method !== null && !submitting;

  return (
    <div className="mx-auto w-full max-w-md min-h-dvh bg-surface2">
      <header className="px-5 pt-5 pb-3 bg-accent-tint">
        <div className="text-[13px] font-bold text-brand">⌃ 인파 상담 예약</div>
      </header>
      <main className="px-5 pb-10">
        <h1 className="pt-6 text-[22px] font-extrabold text-ink leading-8">상담 시간 예약</h1>
        <p className="mt-2 text-[14px] text-ink3 leading-6">
          {info.customer.name_masked}님, 담당 설계사
          {info.planner.affiliation ? ` (${info.planner.affiliation})` : ""}와의 상담 시간을 직접 골라주세요.
        </p>

        {/* 방식 */}
        <h2 className="mt-5 text-[13px] font-semibold text-ink3 mb-2">상담 방식</h2>
        <div className="grid grid-cols-3 gap-2">
          {info.methods.map((m) => (
            <button
              key={m.key}
              onClick={() => setMethod(m.key)}
              className={`rounded-xl border py-2.5 text-[14px] font-semibold transition ${
                method === m.key ? "border-brand bg-accent-tint text-brand" : "border-line bg-surface text-ink2"
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>
        {inPersonSelected && info.planner.location && (
          <p className="mt-2 text-[12px] text-ink3">대면 장소: {info.planner.location}</p>
        )}

        {/* 슬롯 */}
        <h2 className="mt-5 text-[13px] font-semibold text-ink3 mb-2">가능한 시간</h2>
        {info.slots.length === 0 ? (
          <Card className="px-4 py-6 text-center text-[14px] text-ink3">
            지금 열린 시간이 없어요. 담당 설계사에게 문의해 주세요.
          </Card>
        ) : (
          <div className="space-y-2">
            {info.slots.map((s) => (
              <button
                key={s.id}
                onClick={() => setSlotId(s.id)}
                className={`w-full text-left rounded-xl border px-4 py-3 text-[15px] font-semibold transition ${
                  slotId === s.id ? "border-brand bg-accent-tint text-brand" : "border-line bg-surface text-ink"
                }`}
              >
                {fmtKST(s.start_at)}
                <span className="text-[12px] font-normal text-ink3"> · {s.duration_min}분</span>
              </button>
            ))}
          </div>
        )}

        {/* 메모 */}
        <h2 className="mt-5 text-[13px] font-semibold text-ink3 mb-2">남길 말 (선택)</h2>
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={2}
          placeholder="상담 시 참고할 내용을 적어주세요"
          className="w-full rounded-xl border border-line bg-surface px-3 py-2.5 text-[14px]"
        />

        {submitError && (
          <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-[13px] text-rose-700">
            {submitError}
          </div>
        )}

        <button
          onClick={submit}
          disabled={!canSubmit}
          className="mt-4 w-full rounded-2xl bg-brand text-white text-[16px] font-bold py-4 disabled:opacity-50 active:scale-[0.99] transition"
        >
          {submitting ? "예약 중…" : "이 시간으로 예약"}
        </button>
        <p className="mt-3 text-[11px] text-ink3 leading-5 text-center">{info.disclaimer}</p>
      </main>
    </div>
  );
}
