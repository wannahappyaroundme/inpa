// 셀프진단 레이아웃 — Server Component.
// robots noindex: 잠재고객 개인 보험정보가 오갈 수 있는 공개 진단 링크는 검색엔진 수집 차단.
import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

export default function SelfDiagnosisLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
