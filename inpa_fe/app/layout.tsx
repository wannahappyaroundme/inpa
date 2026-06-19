import type { Metadata } from "next";
import "./globals.css";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://inpa.kr";
const TITLE = "인파(Inpa) — 설계사님은 클로징만 준비하세요";
const DESCRIPTION =
  "새 고객 발굴 → 증권 OCR → 보장 분석 → 갈아타기 비교까지 한 동선으로. 보험설계사의 AI 영업 파트너, 인파(Inpa).";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: TITLE,
    template: "%s · 인파(Inpa)",
  },
  description: DESCRIPTION,
  applicationName: "인파(Inpa)",
  keywords: ["보험설계사", "보장분석", "증권 OCR", "갈아타기", "영업지원", "인파", "Inpa"],
  openGraph: {
    type: "website",
    locale: "ko_KR",
    siteName: "인파(Inpa)",
    title: TITLE,
    description: DESCRIPTION,
    url: SITE_URL,
    // og:image는 app/opengraph-image.tsx 가 자동 생성
  },
  twitter: {
    card: "summary_large_image",
    title: TITLE,
    description: DESCRIPTION,
    // twitter:image는 opengraph-image 를 재사용 (Next 자동 매핑)
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko" className="h-full antialiased">
      <head>
        <link
          rel="stylesheet"
          as="style"
          href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable.min.css"
        />
      </head>
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
