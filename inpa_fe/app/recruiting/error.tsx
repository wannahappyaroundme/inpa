"use client";

import { useEffect } from "react";

export default function RecruitingRouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main className="mx-auto flex min-h-dvh max-w-xl items-center px-4 py-10">
      <section
        role="alert"
        className="w-full rounded-3xl border border-line bg-surface px-6 py-10 text-center shadow-card"
      >
        <h1 className="text-[20px] font-extrabold text-ink">
          영입 화면을 다시 열면 이어서 확인할 수 있어요.
        </h1>
        <p className="mt-2 text-[14px] leading-6 text-ink3">
          입력하던 내용은 화면을 확인한 뒤 다시 저장해 주세요.
        </p>
        <button
          type="button"
          onClick={reset}
          className="mt-6 min-h-11 rounded-xl bg-brand px-6 py-3 text-[14px] font-bold text-white transition hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
        >
          화면 다시 열기
        </button>
      </section>
    </main>
  );
}
