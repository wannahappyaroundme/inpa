"use client";

import Link from "next/link";
import { InpaMark } from "@/components/inpa-logo";

export default function BlogError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4 text-ink">
      <main className="w-full max-w-md rounded-3xl border border-line bg-surface p-8 text-center shadow-card">
        <div className="mx-auto flex size-14 items-center justify-center rounded-full bg-accent-tint">
          <InpaMark size={30} title="" />
        </div>
        <h1 className="mt-5 text-[22px] font-extrabold text-brand-ink">글을 다시 연결해볼게요</h1>
        <p className="mt-3 text-[14px] leading-7 text-ink3">
          연결이 잠시 느려졌어요. 아래 버튼을 누르면 보고 있던 글을 다시 불러옵니다.
        </p>
        <button
          type="button"
          onClick={reset}
          className="mt-6 min-h-[48px] w-full rounded-2xl bg-brand px-5 py-3 text-[14px] font-bold text-white transition hover:opacity-90"
        >
          다시 불러오기
        </button>
        <Link href="/blog" className="mt-4 inline-flex text-[13px] font-semibold text-brand hover:text-brand-ink">
          인파 블로그 목록 보기
        </Link>
      </main>
    </div>
  );
}
