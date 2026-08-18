import type { Metadata } from "next";
import Link from "next/link";
import { InpaMark } from "@/components/inpa-logo";

// 없는 주소로 들어왔을 때의 화면. 루트 레이아웃 안에서 그려지므로 서비스 톤 그대로 쓸 수 있다.
// 고객이 받은 링크가 만료·수정된 경우에도 여기로 오므로, 막다른 길 대신 다음 행동을 준다.
export const metadata: Metadata = {
  title: "찾는 화면이 없어요",
  robots: { index: false, follow: false },
};

export default function NotFound() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4 text-ink">
      <main className="w-full max-w-md rounded-3xl border border-line bg-surface p-8 text-center shadow-card">
        <div className="mx-auto flex size-14 items-center justify-center rounded-full bg-accent-tint">
          <InpaMark size={30} title="" />
        </div>
        <h1 className="mt-5 text-[22px] font-extrabold break-keep text-brand-ink">
          찾는 화면이 여기에는 없어요
        </h1>
        <p className="mt-3 text-[14px] leading-7 break-keep text-ink3">
          주소가 바뀌었거나 링크가 조금 달라진 것 같아요. 첫 화면에서 원하는 메뉴로 바로 갈 수 있어요.
          고객에게 받은 링크라면 담당 설계사에게 새 링크를 요청해 주세요.
        </p>
        <Link
          href="/"
          className="mt-6 inline-flex min-h-[48px] w-full items-center justify-center rounded-2xl bg-brand px-5 py-3 text-[14px] font-bold text-white transition hover:opacity-90"
        >
          첫 화면으로 가기
        </Link>
      </main>
    </div>
  );
}
