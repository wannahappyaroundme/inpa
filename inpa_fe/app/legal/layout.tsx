// 법무 페이지 레이아웃 — 초안(시행 전)이라 검색 색인 보류(noindex). 정식 시행 시 해제.
import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

export default function LegalLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
