"use client";

import { useCallback, useEffect, useId, useRef } from "react";

import { BookingMessageComposer } from "@/components/booking-message-composer";

function focusIfConnected(target: HTMLElement | null): void {
  if (target?.isConnected) target.focus();
}

const FOCUSABLE_SELECTOR = [
  "button:not([disabled])",
  "a[href]",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(", ");

export function BookingModal({
  customerId,
  onClose,
}: {
  customerId: number;
  onClose: () => void;
}) {
  const titleId = useId();
  const descriptionId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  const closingRef = useRef(false);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  const close = useCallback(() => {
    if (closingRef.current) return;
    closingRef.current = true;
    onCloseRef.current();
  }, []);

  useEffect(() => {
    closingRef.current = false;
    restoreFocusRef.current = document.activeElement as HTMLElement | null;
    const frame = requestAnimationFrame(() => closeRef.current?.focus());

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        close();
        return;
      }
      if (event.key !== "Tab") return;

      const focusable = Array.from(
        dialogRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR) ?? [],
      );
      if (focusable.length === 0) {
        event.preventDefault();
        dialogRef.current?.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const activeElement = document.activeElement;
      if (event.shiftKey && (activeElement === first || !focusable.includes(activeElement as HTMLElement))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (activeElement === last || !focusable.includes(activeElement as HTMLElement))) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("keydown", onKeyDown);
      focusIfConnected(restoreFocusRef.current);
    };
  }, [close]);

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 sm:items-center sm:p-4">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        tabIndex={-1}
        className="max-h-[calc(100dvh-1rem)] w-full overflow-y-auto rounded-t-3xl bg-surface px-6 pb-8 pt-6 shadow-xl sm:max-w-md sm:rounded-3xl"
      >
        <div className="flex items-start justify-between gap-4">
          <h2 id={titleId} className="text-[19px] font-extrabold text-ink">미팅 예약 링크</h2>
          <button
            ref={closeRef}
            type="button"
            aria-label="닫기"
            onClick={close}
            className="grid h-11 w-11 shrink-0 place-items-center rounded-xl text-[22px] text-ink3 hover:bg-surface2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
          >
            ×
          </button>
        </div>
        <p id={descriptionId} className="mt-3 text-[14px] leading-6 text-ink2">
          고객이 편한 시간을 직접 고를 수 있도록, 예약 안내 문구와 링크를 만들어 보세요.
        </p>
        <div className="mt-5">
          <BookingMessageComposer customerId={customerId} />
        </div>
      </div>
    </div>
  );
}
