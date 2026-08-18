"use client";

// 루트 레이아웃까지 실패했을 때의 마지막 안전망.
// ★ 이 파일은 루트 레이아웃을 대체하므로 html/body를 직접 그려야 하고, globals.css가 적용되지 않는다
//   (node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/error.md "Global Error").
//   그래서 브랜드 톤(라이트 고정)을 인라인 스타일로 직접 넣는다. metadata export도 쓸 수 없어 <title> 태그를 쓴다.
// 오류 상세·스택·digest 는 화면에 노출하지 않는다.
import { InpaMark } from "@/components/inpa-logo";

const COLOR = {
  canvas: "#F3F5F9",
  surface: "#FFFFFF",
  line: "#E6E9EF",
  ink: "#14171F",
  ink3: "#6B7280",
  brand: "#2F58DC",
  brandInk: "#22409E",
  brandTint: "#EAF0FE",
};

const FONT =
  'Pretendard, -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Malgun Gothic", sans-serif';

export default function GlobalError({
  reset,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  reset: () => void;
  unstable_retry?: () => void;
}) {
  const retry = unstable_retry ?? reset;

  return (
    <html lang="ko">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "16px",
          backgroundColor: COLOR.canvas,
          color: COLOR.ink,
          fontFamily: FONT,
          wordBreak: "keep-all",
        }}
      >
        <title>화면을 다시 불러올게요 · 인파(Inpa)</title>
        <main
          style={{
            width: "100%",
            maxWidth: "420px",
            boxSizing: "border-box",
            padding: "32px",
            borderRadius: "24px",
            border: `1px solid ${COLOR.line}`,
            backgroundColor: COLOR.surface,
            boxShadow: "0 8px 24px rgba(20, 23, 31, 0.06)",
            textAlign: "center",
          }}
        >
          <div
            style={{
              width: "56px",
              height: "56px",
              margin: "0 auto",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              borderRadius: "9999px",
              backgroundColor: COLOR.brandTint,
            }}
          >
            <InpaMark size={30} title="" />
          </div>
          <h1
            style={{
              margin: "20px 0 0",
              fontSize: "22px",
              fontWeight: 800,
              color: COLOR.brandInk,
            }}
          >
            화면을 다시 불러올게요
          </h1>
          <p
            style={{
              margin: "12px 0 0",
              fontSize: "14px",
              lineHeight: 1.8,
              color: COLOR.ink3,
            }}
          >
            잠시 연결이 느려졌어요. 다시 시도하면 이어서 볼 수 있어요.
          </p>
          <button
            type="button"
            onClick={() => retry()}
            style={{
              marginTop: "24px",
              width: "100%",
              minHeight: "48px",
              padding: "12px 20px",
              borderRadius: "16px",
              border: "none",
              backgroundColor: COLOR.brand,
              color: COLOR.surface,
              fontSize: "14px",
              fontWeight: 700,
              fontFamily: "inherit",
              cursor: "pointer",
            }}
          >
            다시 시도하기
          </button>
          <a
            href="/"
            style={{
              display: "inline-block",
              marginTop: "16px",
              fontSize: "13px",
              fontWeight: 600,
              color: COLOR.brand,
              textDecoration: "none",
            }}
          >
            첫 화면으로 가기
          </a>
        </main>
      </body>
    </html>
  );
}
