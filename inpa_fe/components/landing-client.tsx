"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { tokenStore } from "@/lib/api";
import { useUtmCapture } from "@/lib/useUtmCapture";

// 랜딩의 클라이언트 전용 부수효과만 담는다(화면 렌더 없음 → null 반환).
// 랜딩 page 를 서버 컴포넌트로 두어 metadata(canonical)·JSON-LD 를 서버에서 주입하려고 분리.
export function LandingClient() {
  const router = useRouter();
  useUtmCapture(); // 유입 첫터치 캡처(#16) — 화면 변화 없음
  useEffect(() => {
    if (tokenStore.get()) router.replace("/home");
  }, [router]);
  return null;
}
