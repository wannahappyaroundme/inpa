"use client";

// 유입 첫터치(UTM) 캡처 — 루트 레이아웃에 마운트해 '모든 공개 페이지'에서 동작한다.
// 이전엔 랜딩(LandingClient)에서만 캡처해 블로그(/blog)로 먼저 들어온 방문자의 유입을 놓쳤다(#16 갭).
// 순수 부수효과(화면 변화 0). sessionStorage 최초 1회만 저장(first-touch) — 훅 내부에서 보장.
import { useUtmCapture } from "@/lib/useUtmCapture";

export function UtmCapture() {
  useUtmCapture();
  return null;
}
