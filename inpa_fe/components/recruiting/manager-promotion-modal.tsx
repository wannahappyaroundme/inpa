"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";

import { acknowledgeManagerPromotion } from "@/lib/api";
import {
  getManagerPromotionDestination,
  getManagerPromotionSecondaryLabel,
  getWrappedFocusIndex,
  type ManagerPromotionIntent,
} from "./recruiting-integration";

function focusIfConnected(target: HTMLElement | null): void {
  if (target?.isConnected) target.focus();
}

export function ManagerPromotionModal({
  open,
  recruitingEnabled,
  onAcknowledged,
}: {
  open: boolean;
  recruitingEnabled: boolean;
  onAcknowledged: () => void;
}) {
  const router = useRouter();
  const titleId = useId();
  const descriptionId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const primaryRef = useRef<HTMLButtonElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const busyRef = useRef(false);
  const completeRef = useRef<(intent: ManagerPromotionIntent) => void>(() => {});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const complete = useCallback(
    async (intent: ManagerPromotionIntent) => {
      if (busyRef.current) return;
      busyRef.current = true;
      setBusy(true);
      setError(null);
      try {
        await acknowledgeManagerPromotion();
        onAcknowledged();
        const destination = getManagerPromotionDestination(
          intent,
          recruitingEnabled,
        );
        if (destination) router.push(destination);
      } catch {
        busyRef.current = false;
        setBusy(false);
        setError(
          "연결이 잠시 지연되고 있어요. 다시 시도하면 이어서 확인할 수 있어요.",
        );
      }
    },
    [onAcknowledged, recruitingEnabled, router],
  );

  useEffect(() => {
    completeRef.current = (intent) => {
      void complete(intent);
    };
  }, [complete]);

  useEffect(() => {
    if (!open) return;
    busyRef.current = false;
    setBusy(false);
    setError(null);
    restoreFocusRef.current = document.activeElement as HTMLElement | null;
    const frame = requestAnimationFrame(() => primaryRef.current?.focus());

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !busyRef.current) {
        event.preventDefault();
        completeRef.current("close");
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(
        dialogRef.current?.querySelectorAll<HTMLElement>(
          "button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])",
        ) ?? [],
      );
      if (focusable.length === 0) {
        event.preventDefault();
        dialogRef.current?.focus();
        return;
      }
      const activeIndex = focusable.indexOf(document.activeElement as HTMLElement);
      const targetIndex = getWrappedFocusIndex(
        activeIndex,
        focusable.length,
        event.shiftKey,
      );
      if (targetIndex !== null) {
        event.preventDefault();
        focusable[targetIndex].focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("keydown", onKeyDown);
      focusIfConnected(restoreFocusRef.current);
    };
  }, [open]);

  if (!open || typeof document === "undefined") return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 sm:items-center sm:p-4"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busyRef.current) {
          void complete("close");
        }
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        aria-busy={busy}
        tabIndex={-1}
        className="w-full rounded-t-3xl bg-surface px-6 pb-8 pt-6 shadow-xl sm:max-w-md sm:rounded-3xl"
      >
        <div className="flex items-start justify-between gap-4">
          <h2 id={titleId} className="text-[20px] font-extrabold text-ink">
            Manager로 승격되었어요
          </h2>
          <button
            type="button"
            aria-label="닫기"
            disabled={busy}
            onClick={() => void complete("close")}
            className="grid h-9 w-9 shrink-0 place-items-center rounded-xl text-[22px] text-ink3 hover:bg-surface2 disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
          >
            ×
          </button>
        </div>
        <p id={descriptionId} className="mt-3 text-[14px] leading-6 text-ink2">
          첫 팀원이 합류해 팀 관리 기능이 열렸습니다. 추가 결제 없이 계속 이용할 수 있어요.
        </p>
        {error && (
          <p role="alert" className="mt-3 rounded-xl bg-danger-tint px-3 py-2 text-[13px] text-danger">
            {error}
          </p>
        )}
        <div className="mt-6 flex flex-col gap-2.5 sm:flex-row">
          <button
            ref={primaryRef}
            type="button"
            disabled={busy}
            onClick={() => void complete("team")}
            className="min-h-12 flex-1 rounded-2xl bg-brand px-4 text-[14px] font-bold text-white disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
          >
            팀 현황 보기
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => void complete("recruit")}
            className="min-h-12 flex-1 rounded-2xl border border-line bg-surface px-4 text-[14px] font-semibold text-ink2 disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
          >
            {getManagerPromotionSecondaryLabel(recruitingEnabled)}
          </button>
        </div>
        {busy && (
          <p className="mt-3 text-center text-[12px] text-ink3" aria-live="polite">
            확인 내용을 저장하고 있어요.
          </p>
        )}
      </div>
    </div>,
    document.body,
  );
}
