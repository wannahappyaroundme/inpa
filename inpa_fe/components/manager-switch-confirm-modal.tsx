"use client";

import { useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";

import { focusIfConnected } from "./recruiting/public-recruiting-view-model";
import { getWrappedFocusIndex } from "./recruiting/recruiting-integration";

interface ManagerSwitchConfirmModalProps {
  open: boolean;
  email: string;
  saving: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ManagerSwitchConfirmModal({
  open,
  email,
  saving,
  onConfirm,
  onCancel,
}: ManagerSwitchConfirmModalProps) {
  const titleId = useId();
  const descriptionId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const savingRef = useRef(saving);
  const cancelActionRef = useRef(onCancel);

  useEffect(() => {
    savingRef.current = saving;
    cancelActionRef.current = onCancel;
  });

  useEffect(() => {
    if (!open) return;
    restoreFocusRef.current = document.activeElement as HTMLElement | null;
    const frame = requestAnimationFrame(() => cancelRef.current?.focus());

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !savingRef.current) {
        event.preventDefault();
        cancelActionRef.current();
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
        focusable[targetIndex]?.focus();
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
        if (event.target === event.currentTarget && !saving) onCancel();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        tabIndex={-1}
        className="w-full rounded-t-3xl bg-surface px-6 pb-8 pt-6 shadow-xl sm:max-w-md sm:rounded-2xl"
      >
        <h2 id={titleId} className="text-[18px] font-extrabold text-ink">
          연결할 관리자를 바꿀까요?
        </h2>
        <p id={descriptionId} className="mt-3 text-[14px] leading-6 text-ink2">
          고객 정보와 지금 선택한 공유 범위는 그대로 유지되고, 연결된 관리자만 바뀌어요.
        </p>
        <p className="mt-3 rounded-xl border border-line bg-surface2 px-3.5 py-3 text-[13px] text-ink2">
          <span className="font-semibold text-ink">새 관리자:</span>{" "}
          <span className="break-all">{email}</span>
        </p>
        <div className="mt-6 flex flex-col-reverse gap-2.5 sm:flex-row">
          <button
            ref={cancelRef}
            type="button"
            disabled={saving}
            onClick={onCancel}
            className="min-h-12 flex-1 rounded-2xl border border-line bg-surface text-[14px] font-semibold text-ink2 disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
          >
            현재 관리자 유지
          </button>
          <button
            type="button"
            disabled={saving}
            onClick={onConfirm}
            className="min-h-12 flex-1 rounded-2xl bg-brand text-[14px] font-bold text-white disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
          >
            {saving ? "변경하는 중..." : "관리자 변경"}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
