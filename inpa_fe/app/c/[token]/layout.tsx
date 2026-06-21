// 고객 본인 동의 페이지 레이아웃 — Server Component (P3c).
// robots noindex: 고객 보험정보 동의 링크는 검색엔진 수집 차단(공유뷰와 동일 원칙).
import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

export default function ConsentLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
