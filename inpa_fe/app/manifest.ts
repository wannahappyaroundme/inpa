import type { MetadataRoute } from "next";

// PWA 매니페스트 — 설치형 앱(홈화면 추가). Next App Router가 /manifest.webmanifest 로 서빙 + <link> 자동 주입.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "인파(Inpa) — 보험설계사 AI 파트너",
    short_name: "인파",
    description: "발굴 → 증권 OCR → 보장분석 → 갈아타기까지 한 동선. 설계사의 AI 영업 파트너.",
    start_url: "/home",
    scope: "/",
    display: "standalone",
    orientation: "portrait",
    lang: "ko",
    background_color: "#ffffff",
    theme_color: "#1B2A57",
    icons: [
      { src: "/inpa-mark.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
      { src: "/apple-icon", sizes: "180x180", type: "image/png", purpose: "any" },
      { src: "/icon", sizes: "64x64", type: "image/png", purpose: "any" },
    ],
  };
}
