// 공유뷰 레이아웃 — Server Component.
// robots noindex: 고객 개인 보험정보가 담긴 공유 링크는 검색엔진 수집 차단.
import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

export default function ShareLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
