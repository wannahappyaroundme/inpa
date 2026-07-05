// 내 소개 카드(디지털 명함) 공개 페이지 레이아웃 — Server Component.
// robots noindex(다른 공개 토큰 라우트 4종과 동일 원칙) + 라우트 공통 정적 OG — lib/public-og.ts 공통 빌더 사용.
import type { Metadata } from "next";
import type { ReactNode } from "react";
import { publicTokenMetadata } from "@/lib/public-og";

export const metadata: Metadata = publicTokenMetadata(
  "담당 설계사 소개 · 인파",
  "설계사 소개를 확인하고 무료 보장 점검을 신청해 보세요.",
);

export default function IntroCardLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
