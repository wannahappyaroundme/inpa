// 고객 본인 동의 페이지 레이아웃 — Server Component (P3c).
// robots noindex + 라우트 공통 정적 OG(고객 대면 문구) — lib/public-og.ts 공통 빌더 사용.
import type { Metadata } from "next";
import type { ReactNode } from "react";
import { publicTokenMetadata } from "@/lib/public-og";

export const metadata: Metadata = publicTokenMetadata(
  "보험 정리 동의 · 인파",
  "동의하면 담당 설계사가 내 보험을 한눈에 정리해 드려요.",
);

export default function ConsentLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
