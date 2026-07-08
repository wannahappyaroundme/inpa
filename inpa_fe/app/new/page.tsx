import type { Metadata } from "next";
import { CinemaLanding } from "@/components/cinema-landing";

export const metadata: Metadata = {
  title: { absolute: "인파(Inpa) · 수많은 인파 속, 흔들림 없는 안내" },
  description: "人波 속에서 INPA가. 보험설계사의 모든 영업을 한곳에, 인파의 이야기를 만나보세요.",
  alternates: { canonical: "https://new.inpa.kr/" },
};

export default function NewLandingPage() {
  return <CinemaLanding />;
}
