import type { Metadata } from "next";
import { CinemaLanding } from "@/components/cinema-landing";

const TITLE = "인파(Inpa) · 수많은 인파 속, 흔들림 없는 안내";
const DESCRIPTION = "人波 속에서 INPA가. 보험설계사의 영업 흐름을 한곳에 잇는 인파의 이야기를 만나보세요.";
const OG_IMAGE = { url: "/opengraph-image.jpg", width: 1200, height: 630 };

export const metadata: Metadata = {
  title: { absolute: TITLE },
  description: DESCRIPTION,
  alternates: { canonical: "/story" },
  openGraph: {
    type: "website",
    locale: "ko_KR",
    siteName: "인파(Inpa)",
    title: TITLE,
    description: DESCRIPTION,
    url: "/story",
    images: [OG_IMAGE],
  },
  twitter: {
    card: "summary_large_image",
    title: TITLE,
    description: DESCRIPTION,
    images: [OG_IMAGE.url],
  },
};

export default function StoryPage() {
  return <CinemaLanding />;
}
