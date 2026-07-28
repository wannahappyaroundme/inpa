"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Copy, Share2, X } from "lucide-react";
import Link from "next/link";

import { copyText } from "@/lib/clipboard";

interface TalkTemplateShareProps {
  open: boolean;
  title: string;
  text: string;
  disabledReason: string | null;
  accountSettingsNeeded?: boolean;
  onClose: () => void;
}

function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    error.name === "AbortError"
  );
}

export function TalkTemplateShare({
  open,
  title,
  text,
  disabledReason,
  accountSettingsNeeded = false,
  onClose,
}: TalkTemplateShareProps) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  const contentGenerationRef = useRef(0);
  const copyOperationRef = useRef(0);
  const shareOperationRef = useRef(0);
  const mountedRef = useRef(true);
  const [copying, setCopying] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [copyMessage, setCopyMessage] = useState("");
  const [shareError, setShareError] = useState("");
  onCloseRef.current = onClose;

  useEffect(() => {
    contentGenerationRef.current += 1;
    setCopyMessage("");
    setShareError("");
  }, [open, text, title]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      copyOperationRef.current += 1;
      shareOperationRef.current += 1;
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    openerRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusTimer = window.setTimeout(() => closeRef.current?.focus());

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(
        dialogRef.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
        ),
      );
      if (focusable.length === 0) {
        event.preventDefault();
        dialogRef.current.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      } else if (!dialogRef.current.contains(document.activeElement)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    const opener = openerRef.current;
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
      if (opener?.isConnected) opener.focus();
    };
  }, [open]);

  if (!open) return null;

  const supportsDeviceShare =
    typeof navigator !== "undefined" &&
    typeof navigator.share === "function";
  const actionsDisabled = Boolean(disabledReason);

  async function handleCopy() {
    if (actionsDisabled || copying) return;
    const operation = ++copyOperationRef.current;
    const contentGeneration = contentGenerationRef.current;
    setCopying(true);
    const copied = await copyText(text);
    if (
      !mountedRef.current ||
      copyOperationRef.current !== operation
    ) {
      return;
    }
    setCopying(false);
    if (contentGenerationRef.current === contentGeneration) {
      setCopyMessage(
        copied
          ? "문구를 복사했어요."
          : "복사가 중단됐어요. 문구를 길게 눌러 직접 복사해 주세요.",
      );
    }
  }

  async function handleDeviceShare() {
    if (
      actionsDisabled ||
      sharing ||
      typeof navigator.share !== "function"
    ) {
      return;
    }
    const operation = ++shareOperationRef.current;
    const contentGeneration = contentGenerationRef.current;
    setSharing(true);
    setShareError("");
    try {
      await navigator.share({ title, text });
    } catch (error) {
      if (
        mountedRef.current &&
        shareOperationRef.current === operation &&
        contentGenerationRef.current === contentGeneration &&
        !isAbortError(error)
      ) {
        setShareError(
          "기기 공유 연결이 중단됐어요. 문구 복사를 이용해 주세요.",
        );
      }
    } finally {
      if (
        mountedRef.current &&
        shareOperationRef.current === operation
      ) {
        setSharing(false);
      }
    }
  }

  return (
    <div className="fixed inset-0 z-[110] flex items-end justify-center sm:items-center sm:p-4">
      <div
        aria-hidden="true"
        data-testid="talk-share-backdrop"
        onMouseDown={onClose}
        className="absolute inset-0 bg-ink/40 backdrop-blur-[2px]"
      />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="relative flex max-h-[92dvh] w-full flex-col overflow-hidden rounded-t-3xl bg-surface shadow-2xl sm:max-w-lg sm:rounded-3xl"
      >
        <header className="flex items-start justify-between gap-4 border-b border-line px-5 py-4 sm:px-6">
          <div>
            <p className="text-xs font-semibold text-brand">공유 전 확인</p>
            <h2 id={titleId} className="mt-1 text-lg font-extrabold text-ink">
              {title}
            </h2>
            <p className="mt-1 text-xs leading-5 text-ink3">
              최종 문구를 확인한 뒤 복사하거나 기기 공유를 선택하세요.
            </p>
          </div>
          <button
            ref={closeRef}
            type="button"
            aria-label="닫기"
            onClick={onClose}
            className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-xl border border-line text-ink3 transition hover:bg-surface2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
          >
            <X aria-hidden="true" size={20} />
          </button>
        </header>

        <div className="overflow-y-auto bg-canvas px-5 py-5 sm:px-6">
          <label className="block">
            <span className="text-sm font-bold text-ink">최종 공유 문구</span>
            <textarea
              readOnly
              aria-label="최종 공유 문구"
              value={text}
              onFocus={(event) => event.currentTarget.select()}
              rows={9}
              className="mt-2 min-h-44 w-full resize-y rounded-2xl border border-line bg-surface px-4 py-3 text-sm leading-6 text-ink outline-none focus-visible:ring-2 focus-visible:ring-brand"
            />
          </label>

          {disabledReason && (
            <div className="mt-4 rounded-xl border border-warn/30 bg-warn-soft px-4 py-3">
              <p className="text-sm font-bold text-warn-ink">
                광고 문구를 공유하기 전에 확인해 주세요
              </p>
              <p className="mt-1 text-xs leading-5 text-warn-ink">
                {disabledReason}
              </p>
              {accountSettingsNeeded && (
                <Link
                  href="/settings/account"
                  className="mt-2 inline-flex min-h-10 items-center rounded-lg border border-warn/30 bg-surface px-3 text-xs font-bold text-warn-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
                >
                  계정 설정 열기
                </Link>
              )}
            </div>
          )}

          {shareError && (
            <p
              role="alert"
              className="mt-4 rounded-xl border border-danger/20 bg-danger-soft px-4 py-3 text-sm font-semibold text-danger"
            >
              {shareError}
            </p>
          )}

          <p
            aria-live="polite"
            className="mt-3 min-h-5 text-xs font-semibold text-ink2"
          >
            {copyMessage}
          </p>
        </div>

        <footer className="grid gap-2 border-t border-line bg-surface px-5 py-4 sm:grid-cols-2 sm:px-6">
          <button
            type="button"
            disabled={actionsDisabled || copying}
            onClick={handleCopy}
            className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl bg-brand px-5 text-sm font-bold text-white transition hover:bg-brand/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Copy aria-hidden="true" size={17} />
            {copying ? "복사 중" : "문구 복사"}
          </button>
          {supportsDeviceShare && (
            <button
              type="button"
              disabled={actionsDisabled || sharing}
              onClick={handleDeviceShare}
              className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl border border-line bg-surface px-5 text-sm font-bold text-ink transition hover:bg-surface2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Share2 aria-hidden="true" size={17} />
              {sharing ? "공유창 여는 중" : "기기에서 공유"}
            </button>
          )}
        </footer>
      </div>
    </div>
  );
}
