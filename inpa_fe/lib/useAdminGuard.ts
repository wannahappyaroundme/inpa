// lib/useAdminGuard.ts
// 관리자 전용 가드 훅. is_admin=True 인 경우만 통과.
// 토큰 없으면 /admin-login, is_admin=false면 /admin-denied.
// 사용법: const ready = useAdminGuard();
//         if (!ready) return null;

"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getProfile, tokenStore } from "@/lib/api";

export function useAdminGuard(): boolean {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const tok = tokenStore.get();
    if (!tok) {
      router.replace("/admin-login");
      return;
    }
    let cancelled = false;
    getProfile()
      .then((p) => {
        if (cancelled) return;
        if (!p.is_admin) {
          router.replace("/admin-login?denied=1");
        } else {
          setReady(true);
        }
      })
      .catch(() => {
        if (!cancelled) router.replace("/admin-login");
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  return ready;
}
