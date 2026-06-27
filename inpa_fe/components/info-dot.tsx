"use client";

import { useState } from "react";

/** ? 점 — 클릭/탭하면 설명 팝오버. 단계 라벨·KPI 용어 풀이 등 공용(쉬운말 가이드). */
export function InfoDot({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="relative inline-flex">
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
        onBlur={() => setOpen(false)}
        aria-label="설명 보기"
        className="w-4 h-4 rounded-full border border-line text-[10px] font-bold text-ink3 leading-none flex items-center justify-center hover:bg-surface2"
      >
        ?
      </button>
      {open && (
        <span className="absolute left-0 top-5 z-30 w-56 rounded-lg border border-line bg-surface px-3 py-2 text-[11px] leading-4 text-ink2 shadow-lg">
          {text}
        </span>
      )}
    </span>
  );
}
