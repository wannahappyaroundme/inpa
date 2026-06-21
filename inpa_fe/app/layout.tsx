import type { Metadata, Viewport } from "next";
import Script from "next/script";
import "./globals.css";
import { PwaRegister } from "@/components/pwa-register";

// 구글 소셜 로그인(GIS) — 클라이언트 ID가 설정된 경우에만 로드(미설정=미로드).
const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://inpa.kr";
const TITLE = "인파(Inpa) — 설계사님은 클로징만 준비하세요";
const DESCRIPTION =
  "새 고객 발굴 → 증권 분석 → 보장 한눈에 → 갈아타기 비교까지 한 동선으로. 보험설계사의 AI 영업 파트너, 인파(Inpa).";

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
  // PWA: app/manifest.ts 가 <link rel="manifest"> 자동 주입. iOS 홈화면 앱 설정.
  appleWebApp: {
    capable: true,
    title: "인파",
    statusBarStyle: "default",
  },
};

export const viewport: Viewport = {
  themeColor: "#1B2A57",
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
      <body className="min-h-full flex flex-col">
        <PwaRegister />
        {GOOGLE_CLIENT_ID && (
          <Script src="https://accounts.google.com/gsi/client" strategy="afterInteractive" />
        )}
        {children}
      </body>
    </html>
  );
}
