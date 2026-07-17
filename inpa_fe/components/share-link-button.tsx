"use client";

// 고객 공유 링크 버튼. 한눈표의 서버 권위가 준비된 경우에만 새 불변 링크를 발급한다.

import { useCallback, useEffect, useRef, useState } from "react";
import { createShareLink, ApiError } from "@/lib/api";
import { copyText } from "@/lib/clipboard";

export interface ShareLinkButtonProps {
  customerId: number;
  authorityLoaded: boolean;
  canShare: boolean;
  shareBlockReason: string | null;
}

interface IssuedLink {
  snapshotId: number;
  token: string;
  url: string;
  expires: string;
}

function shareBlockMessage(reason: string | null): string {
  if (
    reason === "INSURANCE_REVIEW_REQUIRED" ||
    reason === "PENDING_INSURANCE_REVIEW" ||
    reason?.includes("확인할 보험")
  ) {
    return "확인할 보험 내용을 마치면 바로 공유할 수 있어요.";
  }
  if (
    reason === "NO_ANALYSIS_READY_INSURANCE" ||
    reason === "NO_INCLUDED_INSURANCE" ||
    reason?.includes("분석에 포함")
  ) {
    return "보험 내용을 확인하고 분석에 포함하면 바로 공유할 수 있어요.";
  }
  return "분석 내용을 확인하면 공유할 수 있어요.";
}

function shareCreateError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 409 || error.code === "INSURANCE_REVIEW_REQUIRED") {
      return "확인할 보험 내용을 마치면 바로 공유할 수 있어요.";
    }
    if (error.status === 503 || error.code === "SHARE_CREATE_UNAVAILABLE") {
      return "공유 내용을 그대로 두었어요. 잠시 뒤 다시 시도해 주세요.";
    }
    if (error.status === 429) {
      return "요청이 잠시 몰렸어요. 잠시 뒤 다시 만들어 주세요.";
    }
  }
  if (error instanceof TypeError) {
    return "인터넷 연결을 확인한 뒤 다시 만들어 주세요.";
  }
  return "공유 링크를 다시 만들어 주세요.";
}

export function ShareLinkButton({
  customerId,
  authorityLoaded,
  canShare,
  shareBlockReason,
}: ShareLinkButtonProps) {
  const [open, setOpen] = useState(false);
  const [issued, setIssued] = useState<IssuedLink | null>(null);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(false);
  const requestRef = useRef(0);
  const inFlightRef = useRef(false);
  const customerRef = useRef(customerId);
  const issuedRef = useRef<IssuedLink | null>(issued);
  const copyTimerRef = useRef<number | null>(null);
  const copyGenerationRef = useRef(0);
  const openerRef = useRef<HTMLButtonElement | null>(null);
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  customerRef.current = customerId;
  issuedRef.current = issued;

  const clearCopyTimer = useCallback(() => {
    if (copyTimerRef.current !== null) {
      window.clearTimeout(copyTimerRef.current);
      copyTimerRef.current = null;
    }
  }, []);

  const resetCopyFeedback = useCallback(() => {
    copyGenerationRef.current += 1;
    clearCopyTimer();
    setCopied(false);
  }, [clearCopyTimer]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestRef.current += 1;
      copyGenerationRef.current += 1;
      clearCopyTimer();
      inFlightRef.current = false;
    };
  }, [clearCopyTimer]);

  useEffect(() => {
    requestRef.current += 1;
    inFlightRef.current = false;
    setOpen(false);
    setIssued(null);
    setLoading(false);
    resetCopyFeedback();
    setError(null);
  }, [customerId, resetCopyFeedback]);

  const closeDialog = useCallback(() => setOpen(false), []);

  useEffect(() => {
    if (!open || !issued) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButtonRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeDialog();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>("*")).filter(
        (element) => element.matches(
          "button:not(:disabled), input:not(:disabled), a[href], [tabindex]:not([tabindex='-1'])"
        )
      );
      if (focusable.length === 0) return;
      const currentIndex = focusable.indexOf(document.activeElement as HTMLElement);
      const nextIndex = event.shiftKey
        ? (currentIndex <= 0 ? focusable.length - 1 : currentIndex - 1)
        : (currentIndex < 0 || currentIndex === focusable.length - 1 ? 0 : currentIndex + 1);
      event.preventDefault();
      focusable[nextIndex].focus();
    };
    document.addEventListener("keydown", onKeyDown);
    const opener = openerRef.current;
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      if (opener?.isConnected) opener.focus();
    };
  }, [closeDialog, issued, open]);

  const generate = useCallback(async () => {
    if (!authorityLoaded || !canShare || inFlightRef.current) return;
    inFlightRef.current = true;
    const requestId = ++requestRef.current;
    setLoading(true);
    setOpen(false);
    setIssued(null);
    resetCopyFeedback();
    setError(null);
    try {
      const response = await createShareLink(customerId);
      if (
        !mountedRef.current ||
        requestRef.current !== requestId ||
        customerRef.current !== customerId ||
        response.customer_id !== customerId
      ) {
        return;
      }
      const origin = typeof window !== "undefined" ? window.location.origin : "";
      setIssued({
        snapshotId: response.snapshot_id,
        token: response.share_token,
        url: `${origin}${response.share_url}`,
        expires: response.share_expires_at,
      });
      setOpen(true);
    } catch (caught) {
      if (
        mountedRef.current &&
        requestRef.current === requestId &&
        customerRef.current === customerId
      ) {
        setError(shareCreateError(caught));
      }
    } finally {
      if (
        mountedRef.current &&
        requestRef.current === requestId &&
        customerRef.current === customerId
      ) {
        inFlightRef.current = false;
        setLoading(false);
      }
    }
  }, [authorityLoaded, canShare, customerId, resetCopyFeedback]);

  const copy = useCallback(async () => {
    if (!issued?.url) return;
    const copyGeneration = ++copyGenerationRef.current;
    const issuedToken = issued.token;
    clearCopyTimer();
    setCopied(false);
    if (
      await copyText(issued.url) &&
      mountedRef.current &&
      copyGenerationRef.current === copyGeneration &&
      customerRef.current === customerId &&
      issuedRef.current?.token === issuedToken
    ) {
      setCopied(true);
      copyTimerRef.current = window.setTimeout(() => {
        if (
          mountedRef.current &&
          copyGenerationRef.current === copyGeneration &&
          customerRef.current === customerId &&
          issuedRef.current?.token === issuedToken
        ) {
          copyTimerRef.current = null;
          setCopied(false);
        }
      }, 1800);
    }
  }, [clearCopyTimer, customerId, issued]);

  const disabled = !authorityLoaded || !canShare || loading;
  const authorityMessage = authorityLoaded && canShare
    ? null
    : shareBlockMessage(authorityLoaded ? shareBlockReason : null);

  return (
    <>
      <div className="flex flex-col items-start gap-1">
        <button
          ref={openerRef}
          type="button"
          onClick={generate}
          disabled={disabled}
          className="rounded-xl border border-line bg-surface px-3 py-2 text-[13px] font-semibold text-ink2 hover:bg-surface2 transition disabled:cursor-not-allowed disabled:opacity-60"
        >
          {loading ? "생성 중…" : "공유 링크"}
        </button>
        {authorityMessage && (
          <span className="max-w-52 text-[11px] leading-4 text-ink3">
            {authorityMessage}
          </span>
        )}
      </div>
      {error && (
        <span role="alert" className="max-w-64 self-center text-[12px] leading-5 text-danger">
          {error}
        </span>
      )}
      {open && issued && (
        <div
          className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 sm:items-center sm:p-4"
          onClick={closeDialog}
        >
          <div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="share-link-title"
            data-snapshot-id={issued.snapshotId}
            data-share-token={issued.token}
            className="max-h-[90dvh] w-full overflow-y-auto rounded-t-2xl bg-surface p-5 sm:max-w-md sm:rounded-2xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <h2 id="share-link-title" className="text-[16px] font-extrabold text-ink">
                고객 공유 링크
              </h2>
              <button
                ref={closeButtonRef}
                type="button"
                onClick={closeDialog}
                aria-label="닫기"
                className="px-1 text-[20px] leading-none text-ink3"
              >
                ✕
              </button>
            </div>
            <p className="mt-1 text-[12px] leading-5 text-ink3">
              고객에게 보유 보장 현황을 보여주는 링크예요. 링크를 복사해 고객에게 전달하세요.
            </p>
            <div className="mt-3 flex items-center gap-2">
              <input
                readOnly
                value={issued.url}
                onFocus={(event) => event.currentTarget.select()}
                aria-label="고객 공유 주소"
                className="min-w-0 flex-1 truncate rounded-xl border border-line bg-surface2 px-3 py-2 text-[12px] text-ink2"
              />
              <button
                type="button"
                onClick={copy}
                className="shrink-0 rounded-xl bg-brand px-4 py-2 text-[13px] font-bold text-white"
              >
                {copied ? "복사됨" : "복사"}
              </button>
            </div>
            <p className="mt-2 text-[11px] text-ink3">
              만료: {new Date(issued.expires).toLocaleDateString("ko-KR")} (90일). 다시 만들면 이전 링크는 바로 종료돼요.
            </p>
          </div>
        </div>
      )}
    </>
  );
}
