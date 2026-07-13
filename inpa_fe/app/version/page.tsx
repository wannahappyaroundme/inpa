import type { Metadata } from "next";
import { CinemaLandingV2 } from "@/components/cinema-landing-v2";

// 시네마 랜딩 v2 미리보기 — PM 비교 검토용. 라이브(/new)는 불변.
// 승인되면 /new를 v2로 교체하고 이 라우트는 제거한다.
export const metadata: Metadata = {
  title: { absolute: "인파(Inpa) · 새 랜딩 미리보기" },
  robots: { index: false, follow: false },
};

export default function VersionPreviewPage() {
  return <CinemaLandingV2 />;
}
