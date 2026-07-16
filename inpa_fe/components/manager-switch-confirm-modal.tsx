"use client";

import { useEffect } from "react";

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
  useEffect(() => {
    if (!open) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape" && !saving) onCancel();
    }
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [onCancel, open, saving]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-label="관리자 변경 확인"
      onClick={(event) => {
        if (event.target === event.currentTarget && !saving) onCancel();
      }}
    >
      <div className="w-full sm:max-w-md rounded-t-3xl sm:rounded-2xl bg-surface px-6 pt-6 pb-8 shadow-xl">
        <h2 className="text-[18px] font-extrabold text-ink">연결할 관리자를 바꿀까요?</h2>
        <p className="mt-3 text-[14px] leading-6 text-ink2">
          고객 정보와 지금 선택한 공유 범위는 그대로 유지되고, 연결된 관리자만 바뀌어요.
        </p>
        <p className="mt-3 rounded-xl border border-line bg-surface2 px-3.5 py-3 text-[13px] text-ink2">
          <span className="font-semibold text-ink">새 관리자:</span>{" "}
          <span className="break-all">{email}</span>
        </p>
        <div className="mt-6 flex flex-col-reverse gap-2.5 sm:flex-row">
          <button
            type="button"
            autoFocus
            disabled={saving}
            onClick={onCancel}
            className="min-h-12 flex-1 rounded-2xl border border-line bg-surface text-[14px] font-semibold text-ink2 disabled:opacity-60"
          >
            현재 관리자 유지
          </button>
          <button
            type="button"
            disabled={saving}
            onClick={onConfirm}
            className="min-h-12 flex-1 rounded-2xl bg-brand text-[14px] font-bold text-white disabled:opacity-60"
          >
            {saving ? "변경하는 중..." : "관리자 변경"}
          </button>
        </div>
      </div>
    </div>
  );
}
