import { ImageResponse } from "next/og";

// OG/트위터 공유 이미지 (1200x630). 브랜드 토큰색 + 히어로 카피 + 트윈아크 로고.
export const alt = "인파(Inpa) — 설계사님은 클로징만 준비하세요";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "72px 80px",
          background: "linear-gradient(135deg, #0A3A86 0%, #0B57D0 55%, #12B5A4 130%)",
          color: "#FFFFFF",
          fontFamily: "sans-serif",
        }}
      >
        {/* 상단: 로고 락업 */}
        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          <div
            style={{
              width: 88,
              height: 88,
              borderRadius: 22,
              background: "#1B2A57",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <svg width="88" height="88" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M14 45 Q32 23 50 45" fill="none" stroke="#FFFFFF" strokeWidth="6.6" strokeLinecap="round" />
              <path d="M21 44 Q32 12 43 44" fill="none" stroke="#FFFFFF" strokeWidth="3.8" strokeLinecap="round" opacity="0.9" />
              <circle cx="32" cy="31" r="3.1" fill="#FFFFFF" />
            </svg>
          </div>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <span style={{ fontSize: 44, fontWeight: 800, letterSpacing: -1 }}>인파 · Inpa</span>
            <span style={{ fontSize: 24, opacity: 0.85 }}>보험설계사의 AI 영업 파트너</span>
          </div>
        </div>

        {/* 히어로 카피 */}
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <span style={{ fontSize: 76, fontWeight: 800, lineHeight: 1.12, letterSpacing: -2 }}>
            설계사님은
          </span>
          <span style={{ fontSize: 76, fontWeight: 800, lineHeight: 1.12, letterSpacing: -2 }}>
            클로징만 준비하세요
          </span>
        </div>

        {/* 하단: 동선 요약 */}
        <div style={{ display: "flex", alignItems: "center", gap: 18, fontSize: 28, opacity: 0.95 }}>
          <span>발굴</span>
          <span style={{ opacity: 0.6 }}>→</span>
          <span>증권 OCR</span>
          <span style={{ opacity: 0.6 }}>→</span>
          <span>보장 분석</span>
          <span style={{ opacity: 0.6 }}>→</span>
          <span>갈아타기 비교</span>
        </div>
      </div>
    ),
    { ...size }
  );
}
