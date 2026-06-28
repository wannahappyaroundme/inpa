"use client";

// 콘텐츠 보호 — 웹은 100% 차단 불가(스크린샷·개발자도구는 항상 가능). '억제 + 추적(워터마크)'이 목적.
// ★ 정당한 복사(화법 복사버튼 등)는 깨지지 않게 — 전역엔 가벼운 가드만, 강한 차단은 외부노출 화면(공유뷰)에만.

import { useEffect, type ReactNode } from "react";

/** 전역 가드(레이아웃 1회 마운트): 콘솔 셀프-XSS 경고 + 이미지 우클릭/드래그 저장 방해.
 *  텍스트·링크 우클릭은 막지 않음(IMG에만) → 일반 UX 영향 최소. */
export function GlobalContentGuard() {
  useEffect(() => {
    try {
      console.log("%c⚠️ 잠깐!", "color:#DC2626;font-size:22px;font-weight:800");
      console.log(
        "%c누군가 여기에 코드를 붙여넣으라고 했다면 사기(셀프-XSS)일 수 있어요. 개발자가 아니면 이 창을 닫아주세요.",
        "font-size:13px;color:#334155"
      );
    } catch {
      /* 무시 */
    }
    const onImg = (e: Event) => {
      const t = e.target as HTMLElement | null;
      if (t && t.tagName === "IMG") e.preventDefault();
    };
    document.addEventListener("contextmenu", onImg);
    document.addEventListener("dragstart", onImg);
    return () => {
      document.removeEventListener("contextmenu", onImg);
      document.removeEventListener("dragstart", onImg);
    };
  }, []);
  return null;
}

/** 반투명 대각선 타일 워터마크 — 유출 스크린샷 추적·재사용 억제. 클릭은 통과(pointer-events-none).
 *  부모에 position:relative 필요. */
export function Watermark({ text }: { text: string }) {
  if (!text) return null;
  const safe = text.replace(/[<>&]/g, "");
  const svg =
    "<svg xmlns='http://www.w3.org/2000/svg' width='270' height='160'>" +
    "<text x='18' y='95' transform='rotate(-24 135 80)' font-size='15' " +
    "font-family='sans-serif' fill='rgba(15,23,42,0.08)'>" +
    safe +
    "</text></svg>";
  const bg = `url("data:image/svg+xml,${encodeURIComponent(svg)}")`;
  return (
    <div
      aria-hidden
      className="pointer-events-none absolute inset-0 z-10 select-none"
      style={{ backgroundImage: bg, backgroundRepeat: "repeat" }}
    />
  );
}

/** 복사·선택·우클릭 차단 래퍼 — 외부 노출 콘텐츠(고객용 공유뷰)에만 사용.
 *  ★ 설계사 내부 화면·화법 복사버튼엔 쓰지 말 것(정당한 복사가 막힘).
 *  programmatic 복사(navigator.clipboard)는 onCopy 이벤트와 무관하므로 '링크 복사' 버튼은 정상. */
export function ContentProtect({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`select-none ${className}`}
      onContextMenu={(e) => e.preventDefault()}
      onCopy={(e) => e.preventDefault()}
      onCut={(e) => e.preventDefault()}
      style={{
        WebkitUserSelect: "none",
        userSelect: "none",
        WebkitTouchCallout: "none",
      }}
    >
      {children}
    </div>
  );
}
