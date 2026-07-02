"use client";

// ════════════════════════════════════════════════════════════════════════════
// BaselineRequiredModal — 히트맵이 neutral(기준 미설정) 상태일 때 표시하는 안내 모달.
// 설계사에게 기준 설정을 유도하되, 닫고 그냥 볼 수 있는 NON-blocking 모달.
//
// ★ 컴플라이언스:
//  - 인파 제공 기준 없음. 설계사 직접 설정만 안내.
//  - 긍정 프레이밍. 부정문("안 됩니다/불가") 금지.
//  - em-dash(—) 금지. 라이트 테마 고정(dark: 없음).
// ════════════════════════════════════════════════════════════════════════════

import { useRouter } from "next/navigation";

interface BaselineRequiredModalProps {
  onDismiss: () => void;
}

export function BaselineRequiredModal({ onDismiss }: BaselineRequiredModalProps) {
  const router = useRouter();

  function goToBaseline() {
    router.push("/settings/baseline");
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40"
      role="dialog"
      aria-modal="true"
      aria-labelledby="baseline-required-title"
      onClick={(e) => {
        if (e.target === e.currentTarget) onDismiss();
      }}
    >
      <div className="w-full sm:max-w-md bg-surface rounded-t-3xl sm:rounded-2xl px-6 pt-6 pb-8 shadow-xl">
        <h2
          id="baseline-required-title"
          className="text-[18px] font-extrabold text-ink"
        >
          보장 기준을 먼저 설정해 주세요
        </h2>
        <p className="mt-3 text-[14px] text-ink2 leading-6">
          설계사님이 기준을 정하면 넉넉, 적정, 부족을 한눈에 볼 수 있어요.
          <br />
          기준을 설정하지 않으면 보유 금액만 보여드려요.
        </p>

        <div className="mt-6 flex flex-col gap-2.5">
          <button
            onClick={goToBaseline}
            className="w-full rounded-2xl bg-brand text-white text-[15px] font-bold py-3.5 transition"
          >
            기준 설정하러 가기
          </button>
          <button
            onClick={onDismiss}
            className="w-full rounded-2xl border border-line bg-surface text-[14px] font-semibold text-ink2 py-3 transition"
          >
            그냥 볼게요
          </button>
        </div>
      </div>
    </div>
  );
}
