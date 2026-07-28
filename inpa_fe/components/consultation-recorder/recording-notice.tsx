"use client";

import { CircleAlert } from "lucide-react";
import type { Ref } from "react";

export function RecordingNotice({
  noticeText,
  checked,
  onCheckedChange,
  onDecline,
  onStart,
  startBlocked,
  checkboxRef,
}: {
  noticeText: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  onDecline: () => void;
  onStart: () => void;
  startBlocked: boolean;
  checkboxRef?: Ref<HTMLInputElement>;
}) {
  return (
    <aside
      role="note"
      aria-label="설계사용 녹음 필수 안내"
      className="min-w-0 rounded-2xl border-2 border-danger bg-danger-tint p-4 sm:p-5"
    >
      <div className="flex items-start gap-3">
        <CircleAlert
          role="img"
          aria-label="중요 안내"
          className="mt-0.5 h-6 w-6 shrink-0 text-danger-ink"
        />
        <div className="min-w-0">
          <p className="text-[11px] font-extrabold tracking-wide text-danger-ink">
            설계사 직접 안내
          </p>
          <h3 className="mt-1 text-[17px] font-extrabold text-ink">
            녹음 전 필수 안내
          </h3>
          <p className="mt-2 text-[13px] font-semibold leading-6 text-ink2">
            보험 가입 희망자에게 아래 문구를 직접 읽고 동의를 확인해 주세요.
          </p>
        </div>
      </div>

      <blockquote className="mt-4 rounded-xl border border-danger/30 bg-surface px-4 py-3 text-[14px] font-semibold leading-7 text-ink">
        {noticeText}
      </blockquote>

      <label className="mt-4 flex cursor-pointer items-start gap-3 rounded-xl bg-surface px-3 py-3 text-[13px] font-bold leading-6 text-ink">
        <input
          ref={checkboxRef}
          type="checkbox"
          checked={checked}
          onChange={(event) => onCheckedChange(event.target.checked)}
          className="mt-1 h-5 w-5 shrink-0 accent-brand"
        />
        <span>
          보험 가입 희망자에게 위 내용을 안내했고, 녹음 동의를 확인했습니다.
        </span>
      </label>

      <div
        data-testid="recording-notice-actions"
        className="mt-4 flex flex-col gap-2 sm:flex-row"
      >
        <button
          type="button"
          onClick={onDecline}
          className="min-h-12 w-full rounded-xl border border-line bg-surface px-4 text-[14px] font-bold text-ink2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 sm:flex-1"
        >
          상담 메모로 기록하기
        </button>
        <button
          type="button"
          onClick={onStart}
          disabled={!checked || startBlocked}
          className="min-h-12 w-full rounded-xl bg-brand px-4 text-[15px] font-extrabold text-white disabled:cursor-not-allowed disabled:opacity-45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 sm:flex-1"
        >
          녹음 시작
        </button>
      </div>
    </aside>
  );
}
