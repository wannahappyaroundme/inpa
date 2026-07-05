// 공유뷰 레이아웃 — Server Component.
// robots noindex + 라우트 공통 정적 OG(고객 대면 문구) — lib/public-og.ts 공통 빌더 사용.
import type { Metadata } from "next";
import type { ReactNode } from "react";
import { publicTokenMetadata } from "@/lib/public-og";

export const metadata: Metadata = publicTokenMetadata(
  "내 보험 한눈에 보기 · 인파",
  "담당 설계사가 정리한 내 보장 내용을 확인해 보세요.",
);

export default function ShareLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
