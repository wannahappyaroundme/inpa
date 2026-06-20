import { ImageResponse } from "next/og";

// iOS 홈화면 아이콘(apple-touch-icon, 180×180). app/icon.tsx 모티프 확대.
export const size = { width: 180, height: 180 };
export const contentType = "image/png";

export default function AppleIcon() {
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
        }}
      >
        <svg width="180" height="180" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M14 45 Q32 23 50 45" fill="none" stroke="#FFFFFF" strokeWidth="6.6" strokeLinecap="round" />
          <path d="M21 44 Q32 12 43 44" fill="none" stroke="#FFFFFF" strokeWidth="3.8" strokeLinecap="round" opacity="0.9" />
          <circle cx="32" cy="31" r="3.1" fill="#FFFFFF" />
        </svg>
      </div>
    ),
    { ...size }
  );
}
