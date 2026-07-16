import type { Metadata } from "next";
import { TestLanding } from "@/components/test-landing";

export const metadata: Metadata = {
  title: { absolute: "인파 실제 서비스 둘러보기" },
  description: "고객 관리부터 보장분석, 일정, 성과까지 이어지는 인파의 실제 화면을 확인해보세요.",
  alternates: { canonical: "https://new.inpa.kr/test" },
  robots: { index: false, follow: false },
};

export default function NewLandingTestPage() {
  return <TestLanding />;
}
