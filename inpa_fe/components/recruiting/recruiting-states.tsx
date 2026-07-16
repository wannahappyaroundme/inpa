"use client";

export function RecruitingLoading({ fullPage = false }: { fullPage?: boolean }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className={`${fullPage ? "mx-auto min-h-dvh max-w-[1440px] px-4 py-6 sm:px-6" : ""} space-y-3`}
    >
      <span className="sr-only">영입 대화를 불러오는 중이에요.</span>
      {fullPage && (
        <>
          <div aria-hidden="true" className="h-8 w-40 animate-pulse rounded-lg bg-line" />
          <div aria-hidden="true" className="h-12 w-full animate-pulse rounded-2xl bg-line" />
          <div aria-hidden="true" className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[0, 1, 2, 3].map((item) => (
              <div key={item} className="h-24 animate-pulse rounded-2xl bg-line" />
            ))}
          </div>
        </>
      )}
      {[0, 1, 2].map((item) => (
        <div
          key={item}
          aria-hidden="true"
          className="rounded-2xl border border-line bg-surface p-4 shadow-card"
        >
          <div className="h-4 w-28 animate-pulse rounded bg-line" />
          <div className="mt-3 h-3 w-full animate-pulse rounded bg-surface2" />
          <div className="mt-2 h-3 w-2/3 animate-pulse rounded bg-surface2" />
        </div>
      ))}
    </div>
  );
}

export function RecruitingEmpty() {
  return (
    <div className="rounded-2xl border border-line bg-surface px-5 py-10 text-center shadow-card">
      <p className="text-[15px] font-bold text-ink">아직 영입 대화가 없어요.</p>
      <p className="mt-2 text-[13px] leading-5 text-ink3">
        아는 설계사 한 분에게 내 영입 링크를 먼저 보내보세요.
      </p>
    </div>
  );
}

export function RecruitingError({
  onRetry,
  message = "영입 대화를 다시 불러오면 이어서 확인할 수 있어요.",
}: {
  onRetry: () => void;
  message?: string;
}) {
  return (
    <div
      role="alert"
      className="rounded-2xl border border-line bg-surface px-5 py-8 text-center shadow-card"
    >
      <p className="text-[14px] font-semibold text-ink">{message}</p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-4 min-h-[44px] rounded-xl bg-brand px-5 py-2.5 text-[14px] font-bold text-white transition hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)] focus-visible:ring-offset-2"
      >
        다시 불러오기
      </button>
    </div>
  );
}
