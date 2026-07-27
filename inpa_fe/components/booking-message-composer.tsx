"use client";

import { useCallback, useId, useLayoutEffect, useRef, useState } from "react";

import { createBookingRequest } from "@/lib/api";
import { copyText } from "@/lib/clipboard";

export interface BookingMessageComposerProps {
  customerId: number | null;
  prepare?: () => Promise<void>;
  disabled?: boolean;
  onBusyChange?: (busy: boolean) => void;
}

type ComposerState = "idle" | "preparing" | "generating" | "success" | "error";
type CopyTarget = "message" | "link" | null;

const COPY_ERROR = "복사하지 못했어요. 문구를 길게 눌러 직접 복사해 주세요.";

export function BookingMessageComposer({
  customerId,
  prepare,
  disabled = false,
  onBusyChange,
}: BookingMessageComposerProps) {
  const [state, setState] = useState<ComposerState>("idle");
  const [stateOwnerCustomerId, setStateOwnerCustomerId] = useState<number | null>(customerId);
  const [message, setMessage] = useState("");
  const [bookingUrl, setBookingUrl] = useState("");
  const [resultCustomerId, setResultCustomerId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorOwnerCustomerId, setErrorOwnerCustomerId] = useState<number | null>(customerId);
  const [copied, setCopied] = useState<CopyTarget>(null);
  const [copiedOwnerCustomerId, setCopiedOwnerCustomerId] = useState<number | null>(customerId);
  const requestGeneration = useRef(0);
  const latestCustomerId = useRef<number | null>(customerId);
  const inFlight = useRef<{ customerId: number; generation: number } | null>(null);
  const busyGeneration = useRef<number | null>(null);
  const copyTimer = useRef<number | null>(null);
  const messageId = useId();

  const clearCopyTimer = useCallback(() => {
    if (copyTimer.current !== null) {
      window.clearTimeout(copyTimer.current);
      copyTimer.current = null;
    }
  }, []);

  const releaseBusy = useCallback((generation?: number) => {
    if (
      busyGeneration.current === null
      || (generation !== undefined && busyGeneration.current !== generation)
    ) {
      return;
    }
    busyGeneration.current = null;
    onBusyChange?.(false);
  }, [onBusyChange]);

  useLayoutEffect(() => {
    latestCustomerId.current = customerId;
    requestGeneration.current += 1;
    inFlight.current = null;
    releaseBusy();
    clearCopyTimer();
    setState("idle");
    setStateOwnerCustomerId(customerId);
    setMessage("");
    setBookingUrl("");
    setResultCustomerId(null);
    setError(null);
    setErrorOwnerCustomerId(customerId);
    setCopied(null);
    setCopiedOwnerCustomerId(customerId);

    return () => {
      requestGeneration.current += 1;
      inFlight.current = null;
      releaseBusy();
      clearCopyTimer();
    };
  }, [customerId, clearCopyTimer, releaseBusy]);

  const generate = useCallback(async () => {
    if (customerId === null || disabled || inFlight.current?.customerId === customerId) return;
    const generation = ++requestGeneration.current;
    inFlight.current = { customerId, generation };
    busyGeneration.current = generation;
    onBusyChange?.(true);
    clearCopyTimer();
    setError(null);
    setErrorOwnerCustomerId(customerId);
    setCopied(null);
    setCopiedOwnerCustomerId(customerId);
    setStateOwnerCustomerId(customerId);

    const isCurrentRequest = () => (
      generation === requestGeneration.current && latestCustomerId.current === customerId
    );

    try {
      if (prepare) {
        setState("preparing");
        try {
          await prepare();
        } catch {
          if (!isCurrentRequest()) return;
          setState("error");
          setStateOwnerCustomerId(customerId);
          setError("예약 설정을 다시 저장해 주세요.");
          setErrorOwnerCustomerId(customerId);
          return;
        }
      }

      if (!isCurrentRequest()) return;
      setState("generating");
      setStateOwnerCustomerId(customerId);
      try {
        const result = await createBookingRequest(customerId);
        if (!isCurrentRequest()) return;
        setMessage(result.message);
        setBookingUrl(result.booking_url);
        setResultCustomerId(customerId);
        setState("success");
        setStateOwnerCustomerId(customerId);
      } catch {
        if (!isCurrentRequest()) return;
        setState("error");
        setStateOwnerCustomerId(customerId);
        setError("문구를 다시 만들 수 있어요.");
        setErrorOwnerCustomerId(customerId);
      }
    } finally {
      if (
        inFlight.current?.generation === generation
        && inFlight.current.customerId === customerId
      ) {
        inFlight.current = null;
      }
      releaseBusy(generation);
    }
  }, [clearCopyTimer, customerId, disabled, onBusyChange, prepare, releaseBusy]);

  const copy = useCallback(async (text: string, target: Exclude<CopyTarget, null>) => {
    const generation = requestGeneration.current;
    const copyCustomerId = customerId;
    clearCopyTimer();
    setError(null);
    setErrorOwnerCustomerId(copyCustomerId);
    setCopied(null);
    setCopiedOwnerCustomerId(copyCustomerId);
    const succeeded = await copyText(text);
    if (generation !== requestGeneration.current || latestCustomerId.current !== copyCustomerId) return;
    if (!succeeded) {
      setError(COPY_ERROR);
      setErrorOwnerCustomerId(copyCustomerId);
      return;
    }
    setCopied(target);
    setCopiedOwnerCustomerId(copyCustomerId);
    copyTimer.current = window.setTimeout(() => {
      if (generation !== requestGeneration.current || latestCustomerId.current !== copyCustomerId) return;
      setCopied(null);
      copyTimer.current = null;
    }, 2000);
  }, [clearCopyTimer, customerId]);

  const visibleState = stateOwnerCustomerId === customerId ? state : "idle";
  const visibleError = errorOwnerCustomerId === customerId ? error : null;
  const visibleCopied = copiedOwnerCustomerId === customerId ? copied : null;
  const isCurrentResult = visibleState === "success" && resultCustomerId === customerId;
  const isBusy = visibleState === "preparing" || visibleState === "generating";
  const canGenerate = customerId !== null && !disabled && !isBusy;
  const actionLabel = visibleState === "error" ? "다시 만들기" : "고객에게 보낼 문구 만들기";

  return (
    <section className="min-w-0 rounded-2xl border border-line bg-surface p-4 sm:p-5" aria-label="예약 안내 문구">
      <div aria-live="polite" className="sr-only">
        {visibleState === "preparing" ? "예약 설정을 저장하고 있어요." : visibleState === "generating" ? "고객에게 보낼 문구를 만들고 있어요." : visibleCopied === "message" ? "메시지를 복사했어요." : visibleCopied === "link" ? "링크를 복사했어요." : ""}
      </div>
      {visibleError && <p role="alert" className="mb-3 rounded-xl bg-danger-tint px-3 py-2.5 text-[13px] font-semibold text-danger-ink">{visibleError}</p>}

      {customerId === null && (
        <p className="mb-3 text-[13px] leading-5 text-ink2">고객을 먼저 고르면 바로 예약 안내를 만들 수 있어요.</p>
      )}

      {!isCurrentResult ? (
        <button
          type="button"
          onClick={() => void generate()}
          disabled={!canGenerate}
          className="min-h-11 w-full rounded-xl bg-brand px-4 text-[14px] font-bold text-white transition disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
        >
          {visibleState === "preparing" ? "예약 설정 저장 중..." : visibleState === "generating" ? "문구 만드는 중..." : actionLabel}
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
          {visibleCopied && <p aria-live="polite" className="text-[13px] font-semibold text-success-ink">{visibleCopied === "message" ? "메시지를 복사했어요." : "링크를 복사했어요."}</p>}
        </div>
      )}
    </section>
  );
}
