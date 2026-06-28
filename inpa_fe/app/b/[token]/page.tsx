"use client";

// 미팅 예약 공개 페이지(비로그인) — 고객이 설계사의 '비어 있는 시간'에서 직접 고른다.
// ★ 마스킹 이름만 표시(PII 미노출). 시간 선택 후 '신청' → 설계사 수락 시 확정(대기 흐름).
//   409 = 그 시간이 방금 마감/충돌 → 경고 + 다시 고르기.

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
  const [selectedStart, setSelectedStart] = useState<string | null>(null);
  const [method, setMethod] = useState<MeetingMethod | null>(null);
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [done, setDone] = useState<{ start_at: string; method: MeetingMethod } | null>(null);

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
    if (selectedStart === null || method === null) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const r = await submitBooking(token, { start_at: selectedStart, method, note: note.trim() || undefined });
      setDone({ start_at: r.start_at, method: r.method });
    } catch (e: unknown) {
      if (e instanceof ApiError && e.status === 409) {
        setSubmitError(e.message); // BE 친절 메시지(상의 안내 포함)
        setSelectedStart(null);
        load(); // 빈 시간 새로고침(마감/충돌 시간 사라짐)
      } else {
        setSubmitError(e instanceof ApiError ? e.message : "신청에 실패했어요. 잠시 후 다시 시도해 주세요.");
      }
    } finally {
      setSubmitting(false);
    }
  }, [token, selectedStart, method, note, load]);

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

  // ── 신청 접수(대기) ──
  if (done) {
    const methodLabel = info?.methods.find((m) => m.key === done.method)?.label ?? "";
    return (
      <div className="mx-auto w-full max-w-md min-h-dvh bg-surface2">
        <header className="px-5 pt-5 pb-3 bg-accent-tint">
          <div className="text-[13px] font-bold text-brand">⌃ 인파 상담 예약</div>
        </header>
        <main className="px-5 pb-10 flex flex-col items-center text-center">
          <div className="mt-16 text-[40px]">📩</div>
          <h1 className="mt-4 text-[20px] font-extrabold text-ink">신청이 접수됐어요</h1>
          <p className="mt-2 text-[15px] font-semibold text-ink">{fmtKST(done.start_at)} · {methodLabel}</p>
          <p className="mt-3 text-[14px] text-ink3 leading-6">
            담당 설계사가 확인하면 이 시간으로 확정돼요. 곧 연락드릴 거예요. 이 창은 닫으셔도 됩니다.
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

  const canSubmit = selectedStart !== null && method !== null && !submitting;

  return (
    <div className="mx-auto w-full max-w-md min-h-dvh bg-surface2">
      <header className="px-5 pt-5 pb-3 bg-accent-tint">
        <div className="text-[13px] font-bold text-brand">⌃ 인파 상담 예약</div>
      </header>
      <main className="px-5 pb-10">
        <h1 className="pt-6 text-[22px] font-extrabold text-ink leading-8">상담 시간 고르기</h1>
        <p className="mt-2 text-[14px] text-ink3 leading-6">
          {info.customer.name_masked}님, {info.planner.name || "담당 설계사"}
          {info.planner.affiliation ? ` (${info.planner.affiliation})` : ""}님과 상담할 시간을 직접 골라주세요.
          고르신 뒤 설계사님이 확인하면 확정됩니다.
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

        {/* 빈 시간 */}
        <h2 className="mt-5 text-[13px] font-semibold text-ink3 mb-2">비어 있는 시간</h2>
        {info.slots.length === 0 ? (
          <Card className="px-4 py-6 text-center text-[14px] text-ink3">
            지금 고를 수 있는 시간이 없어요. 담당 설계사에게 문의해 주세요.
          </Card>
        ) : (
          <div className="space-y-2 max-h-[44vh] overflow-y-auto pr-0.5">
            {info.slots.map((s) => (
              <button
                key={s.start_at}
                onClick={() => setSelectedStart(s.start_at)}
                className={`w-full text-left rounded-xl border px-4 py-3 text-[15px] font-semibold transition ${
                  selectedStart === s.start_at ? "border-brand bg-accent-tint text-brand" : "border-line bg-surface text-ink"
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
          <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-[13px] text-amber-800 leading-5">
            {submitError}
          </div>
        )}

        <button
          onClick={submit}
          disabled={!canSubmit}
          className="mt-4 w-full rounded-2xl bg-brand text-white text-[16px] font-bold py-4 disabled:opacity-50 active:scale-[0.99] transition"
        >
          {submitting ? "신청 중…" : "이 시간으로 신청"}
        </button>
        <p className="mt-3 text-[11px] text-ink3 leading-5 text-center">{info.disclaimer}</p>
      </main>
    </div>
  );
}
