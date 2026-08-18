"use client";

// 루트 오류 경계 — 어느 화면에서 런타임 오류가 나도 인파 톤의 안내를 보여준다.
// 고객이 받는 링크(/s /b /c /d /p)도 이 경계 안에 들어오므로 문구는 쉬운 한국어 + 다음 행동만 담는다.
// 오류 상세·스택·digest 는 화면에 노출하지 않는다(내부 정보 보호).
import Link from "next/link";
import { InpaMark } from "@/components/inpa-logo";

export default function AppError({
  reset,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  reset: () => void;
  unstable_retry?: () => void;
}) {
  // Next 16은 unstable_retry(서버 데이터까지 다시 불러옴)와 reset을 함께 넘긴다.
  const retry = unstable_retry ?? reset;

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4 text-ink">
      <main className="w-full max-w-md rounded-3xl border border-line bg-surface p-8 text-center shadow-card">
        <div className="mx-auto flex size-14 items-center justify-center rounded-full bg-accent-tint">
          <InpaMark size={30} title="" />
        </div>
        <h1 className="mt-5 text-[22px] font-extrabold break-keep text-brand-ink">
          화면을 다시 불러올게요
        </h1>
        <p className="mt-3 text-[14px] leading-7 break-keep text-ink3">
          잠시 연결이 느려졌어요. 다시 시도하면 보고 있던 화면을 이어서 볼 수 있어요.
        </p>
        <button
          type="button"
          onClick={() => retry()}
          className="mt-6 min-h-[48px] w-full rounded-2xl bg-brand px-5 py-3 text-[14px] font-bold text-white transition hover:opacity-90"
        >
          다시 시도하기
        </button>
        <Link
          href="/"
          className="mt-4 inline-flex text-[13px] font-semibold text-brand hover:text-brand-ink"
        >
          첫 화면으로 가기
        </Link>
      </main>
    </div>
  );
}
