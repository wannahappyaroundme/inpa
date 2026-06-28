"use client";

// 미팅 예약 링크 모달 — 설계사가 고객별 예약 링크를 만들어 직접 전달(복사/카톡).
// ★ 자동발송 없음(정직성 레드라인). 메시지는 설계사 템플릿으로 미리 채워지고 즉석 편집 가능.

import { useState, useCallback } from "react";
import { createBookingRequest } from "@/lib/api";

export function BookingModal({
  customerId,
  onClose,
}: {
  customerId: number;
  onClose: () => void;
}) {
  const [loading, setLoading] = useState(false);
  const [url, setUrl] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<"none" | "msg" | "url">("none");

  const generate = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await createBookingRequest(customerId);
      setUrl(r.booking_url);
      setMessage(r.message);
    } catch {
      setError("링크 생성 중 오류가 발생했어요. 다시 시도해 주세요.");
    } finally {
      setLoading(false);
    }
  }, [customerId]);

  const copy = useCallback(async (text: string, which: "msg" | "url") => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(which);
      setTimeout(() => setCopied("none"), 2000);
    } catch {
      /* 미지원 무시 */
    }
  }, []);

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40"
      role="dialog"
      aria-modal="true"
      aria-labelledby="booking-modal-title"
    >
      <div className="w-full sm:max-w-md bg-surface rounded-t-3xl sm:rounded-2xl px-6 pt-6 pb-8 shadow-xl">
        <h2 id="booking-modal-title" className="text-[18px] font-extrabold text-ink">
          미팅 예약 링크
        </h2>
        <p className="mt-3 text-[14px] text-ink2 leading-6">
          고객에게 보낼 예약 링크를 만들어요. 고객이 링크에서 <b className="font-semibold text-ink">직접 시간을 고르면</b>{" "}
          알림이 와요. 아래 메시지를 복사해 카톡·문자로 고객에게 보내세요.
        </p>

        {error && (
          <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-[13px] text-rose-700">
            {error}
          </div>
        )}

        <div className="mt-5 flex flex-col gap-2.5">
          {!url ? (
            <button
              onClick={generate}
              disabled={loading}
              className="w-full rounded-2xl bg-brand text-white text-[15px] font-bold py-3.5 disabled:opacity-60 transition"
            >
              {loading ? "링크 생성 중…" : "예약 링크 만들기"}
            </button>
          ) : (
            <>
              {/* 편집 가능한 메시지 */}
              <label className="text-[12px] font-semibold text-ink3">고객에게 보낼 메시지(편집 가능)</label>
              <textarea
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                rows={4}
                className="w-full rounded-xl border border-line bg-surface2 px-3 py-2.5 text-[13px] text-ink2 leading-5"
              />
              <button
                onClick={() => copy(message, "msg")}
                className="w-full rounded-2xl bg-brand text-white text-[15px] font-bold py-3.5 transition"
              >
                {copied === "msg" ? "메시지 복사됐어요!" : "메시지 복사하기"}
              </button>

              {/* 링크만 */}
              <div className="rounded-xl border border-line bg-surface2 px-3 py-2.5 text-[12px] text-ink2 break-all select-all">
                {url}
              </div>
              <div className="flex gap-2.5">
                <button
                  onClick={() => copy(url, "url")}
                  className="flex-1 rounded-2xl border border-line bg-surface text-[14px] font-semibold text-ink2 py-3 transition"
                >
                  {copied === "url" ? "링크 복사됨!" : "링크만 복사"}
                </button>
                <a
                  href={url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="rounded-2xl border border-line bg-surface text-[14px] font-semibold text-ink2 px-4 py-3 flex items-center"
                >
                  미리보기 ↗
                </a>
              </div>
            </>
          )}
          <button
            onClick={onClose}
            className="w-full rounded-2xl border border-line bg-surface text-[14px] font-semibold text-ink2 py-3 transition"
          >
            닫기
          </button>
        </div>
      </div>
    </div>
  );
}
