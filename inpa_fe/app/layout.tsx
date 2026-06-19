import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "인파 (Inpa) — 보험설계사의 AI 영업 파트너",
  description: "발굴 → 보장 분석 → 갈아타기 제안을 한 흐름으로. 인파(Inpa).",
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
