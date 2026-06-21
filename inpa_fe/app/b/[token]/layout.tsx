// 미팅 예약 공개 페이지 레이아웃 — Server Component.
// robots noindex: 고객 정보가 오가는 예약 링크는 검색엔진 수집 차단(동의/공유와 동일 원칙).
import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

export default function BookingLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
