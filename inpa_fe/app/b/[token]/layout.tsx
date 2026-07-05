// 미팅 예약 공개 페이지 레이아웃 — Server Component.
// robots noindex + 라우트 공통 정적 OG(고객 대면 문구) — lib/public-og.ts 공통 빌더 사용.
import type { Metadata } from "next";
import type { ReactNode } from "react";
import { publicTokenMetadata } from "@/lib/public-og";

export const metadata: Metadata = publicTokenMetadata(
  "상담 시간 고르기 · 인파",
  "편한 시간을 직접 골라 주세요.",
);

export default function BookingLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
