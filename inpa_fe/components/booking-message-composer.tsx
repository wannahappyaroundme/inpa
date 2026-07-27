"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";

import { createBookingRequest } from "@/lib/api";
import { copyText } from "@/lib/clipboard";

export interface BookingMessageComposerProps {
  customerId: number | null;
  prepare?: () => Promise<void>;
  disabled?: boolean;
}

type ComposerState = "idle" | "preparing" | "generating" | "success" | "error";
type CopyTarget = "message" | "link" | null;

const COPY_ERROR = "복사하지 못했어요. 문구를 길게 눌러 직접 복사해 주세요.";

export function BookingMessageComposer({
  customerId,
  prepare,
  disabled = false,
}: BookingMessageComposerProps) {
  const [state, setState] = useState<ComposerState>("idle");
  const [message, setMessage] = useState("");
  const [bookingUrl, setBookingUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<CopyTarget>(null);
  const requestGeneration = useRef(0);
  const copyTimer = useRef<number | null>(null);
  const messageId = useId();

  const clearCopyTimer = useCallback(() => {
    if (copyTimer.current !== null) {
      window.clearTimeout(copyTimer.current);
      copyTimer.current = null;
    }
  }, []);

  useEffect(() => {
    requestGeneration.current += 1;
    clearCopyTimer();
    setState("idle");
    setMessage("");
    setBookingUrl("");
    setError(null);
    setCopied(null);

    return () => {
      requestGeneration.current += 1;
      clearCopyTimer();
    };
  }, [customerId, clearCopyTimer]);

  const generate = useCallback(async () => {
    if (customerId === null || disabled || state === "preparing" || state === "generating") return;
    const generation = ++requestGeneration.current;
    clearCopyTimer();
    setError(null);
    setCopied(null);

    if (prepare) {
      setState("preparing");
      try {
        await prepare();
      } catch {
        if (generation !== requestGeneration.current) return;
        setState("error");
        setError("예약 설정을 다시 저장해 주세요.");
        return;
      }
    }

    if (generation !== requestGeneration.current) return;
    setState("generating");
    try {
      const result = await createBookingRequest(customerId);
      if (generation !== requestGeneration.current) return;
      setMessage(result.message);
      setBookingUrl(result.booking_url);
      setState("success");
    } catch {
      if (generation !== requestGeneration.current) return;
      setState("error");
      setError("문구를 다시 만들 수 있어요.");
    }
  }, [clearCopyTimer, customerId, disabled, prepare, state]);

  const copy = useCallback(async (text: string, target: Exclude<CopyTarget, null>) => {
    const generation = requestGeneration.current;
    clearCopyTimer();
    setError(null);
    setCopied(null);
    const succeeded = await copyText(text);
    if (generation !== requestGeneration.current) return;
    if (!succeeded) {
      setError(COPY_ERROR);
      return;
    }
    setCopied(target);
    copyTimer.current = window.setTimeout(() => {
      setCopied(null);
      copyTimer.current = null;
    }, 2000);
  }, [clearCopyTimer]);

  const isBusy = state === "preparing" || state === "generating";
  const canGenerate = customerId !== null && !disabled && !isBusy;
  const actionLabel = state === "error" ? "다시 만들기" : "고객에게 보낼 문구 만들기";

  return (
    <section className="min-w-0 rounded-2xl border border-line bg-surface p-4 sm:p-5" aria-label="예약 안내 문구">
      <div aria-live="polite" className="sr-only">
        {state === "preparing" ? "예약 설정을 저장하고 있어요." : state === "generating" ? "고객에게 보낼 문구를 만들고 있어요." : copied === "message" ? "메시지를 복사했어요." : copied === "link" ? "링크를 복사했어요." : ""}
      </div>
      {error && <p role="alert" className="mb-3 rounded-xl bg-danger-tint px-3 py-2.5 text-[13px] font-semibold text-danger-ink">{error}</p>}

      {customerId === null && (
        <p className="mb-3 text-[13px] leading-5 text-ink2">고객을 먼저 고르면 바로 예약 안내를 만들 수 있어요.</p>
      )}

      {state !== "success" ? (
        <button
          type="button"
          onClick={() => void generate()}
          disabled={!canGenerate}
          className="min-h-11 w-full rounded-xl bg-brand px-4 text-[14px] font-bold text-white transition disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
        >
          {state === "preparing" ? "예약 설정 저장 중..." : state === "generating" ? "문구 만드는 중..." : actionLabel}
        </button>
      ) : (
        <div className="min-w-0 space-y-3">
          <label htmlFor={messageId} className="block text-[13px] font-bold text-ink">고객에게 보낼 메시지</label>
          <textarea
            id={messageId}
            aria-label="고객에게 보낼 메시지"
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            rows={5}
            className="w-full rounded-xl border border-line bg-surface2 px-3 py-2.5 text-[13px] leading-5 text-ink outline-none focus:border-brand focus:ring-2 focus:ring-brand/15"
          />
          <button type="button" onClick={() => void copy(message, "message")} className="min-h-11 w-full rounded-xl bg-brand px-4 text-[14px] font-bold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2">
            메시지 전체 복사
          </button>
          <p className="select-text rounded-xl border border-line bg-surface2 px-3 py-2.5 text-[12px] leading-5 text-ink2" style={{ overflowWrap: "anywhere" }}>{bookingUrl}</p>
          <div className="grid gap-2 sm:grid-cols-2">
            <button type="button" onClick={() => void copy(bookingUrl, "link")} className="min-h-11 rounded-xl border border-line bg-surface px-4 text-[14px] font-bold text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2">
              링크만 복사
            </button>
            <a href={bookingUrl} target="_blank" rel="noopener noreferrer" className="flex min-h-11 items-center justify-center rounded-xl border border-line bg-surface px-4 text-[14px] font-bold text-ink2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2">
              고객 화면 열기
            </a>
          </div>
          {copied && <p aria-live="polite" className="text-[13px] font-semibold text-success-ink">{copied === "message" ? "메시지를 복사했어요." : "링크를 복사했어요."}</p>}
        </div>
      )}
    </section>
  );
}
