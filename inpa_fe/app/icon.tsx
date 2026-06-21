import { ImageResponse } from "next/og";

// 앱 아이콘 (탭/홈화면). iP 모노그램(흰 배경·파란 P·빨간 점) — design/logo/inpa-mark.svg.
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
          background: "#FFFFFF",
          borderRadius: 14,
        }}
      >
        <svg width="64" height="64" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M16.5 41 V15.5 H25 C28.9 15.5 32 18.6 32 22.5 C32 26.4 28.9 29.5 25 29.5 H16.5" fill="none" stroke="#1E40C4" strokeWidth="7.6" strokeLinecap="round" strokeLinejoin="round" />
          <circle cx="16.5" cy="5.05" r="3.9" fill="#DC2626" />
        </svg>
      </div>
    ),
    { ...size }
  );
}
