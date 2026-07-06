// 셀프진단 레이아웃 — Server Component.
// robots noindex + 라우트 공통 정적 OG(고객 대면 문구) — lib/public-og.ts 공통 빌더 사용.
import type { Metadata } from "next";
import type { ReactNode } from "react";
import { publicTokenMetadata } from "@/lib/public-og";

export const metadata: Metadata = publicTokenMetadata(
  "내 보험, 지금 상황에 맞을까요?",
  "1분이면 무료로 확인할 수 있어요.",
  "/og-self-diagnosis.jpeg", // 셀프진단 전용 OG 이미지(PM 제작, public/)
);

export default function SelfDiagnosisLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
