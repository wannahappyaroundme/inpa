// lib/useAuthGuard.ts
// 토큰 없으면 /login 리다이렉트하는 클라이언트 가드 훅.
// "use client" 컴포넌트에서 최상단에서 호출한다.
// 사용법: const ready = useAuthGuard(); if (!ready) return null;

"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { tokenStore } from "@/lib/api";

/**
 * 토큰이 있으면 true 반환(렌더 허용).
 * 없으면 /login 리다이렉트 후 false 유지(컴포넌트는 null 반환).
 */
export function useAuthGuard(): boolean {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const tok = tokenStore.get();
    if (!tok) {
      router.replace("/login");
    } else {
      setReady(true);
    }
  }, [router]);

  return ready;
}
