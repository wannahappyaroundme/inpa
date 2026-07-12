"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { tokenStore } from "@/lib/api";

// 랜딩의 클라이언트 전용 부수효과만 담는다(화면 렌더 없음 → null 반환).
// 랜딩 page 를 서버 컴포넌트로 두어 metadata(canonical)·JSON-LD 를 서버에서 주입하려고 분리.
// ★ UTM 첫터치 캡처는 루트 레이아웃의 <UtmCapture />(모든 공개 페이지)로 이동했다(#16 갭 수정).
export function LandingClient() {
  const router = useRouter();
  useEffect(() => {
    if (tokenStore.get()) router.replace("/home");
  }, [router]);
  return null;
}
