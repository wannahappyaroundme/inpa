import { ImageResponse } from "next/og";

// 앱 아이콘 (탭/홈화면). design/logo/inpa-appicon.svg 모티프 재현.
export const size = { width: 64, height: 64 };
export const contentType = "image/png";

export default function Icon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#1B2A57",
          borderRadius: 15,
        }}
      >
        <svg width="64" height="64" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M14 45 Q32 23 50 45" fill="none" stroke="#FFFFFF" strokeWidth="6.6" strokeLinecap="round" />
          <path d="M21 44 Q32 12 43 44" fill="none" stroke="#FFFFFF" strokeWidth="3.8" strokeLinecap="round" opacity="0.9" />
          <circle cx="32" cy="31" r="3.1" fill="#FFFFFF" />
        </svg>
      </div>
    ),
    { ...size }
  );
}
