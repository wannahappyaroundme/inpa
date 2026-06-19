// lib/useAuthGuard.ts
// 토큰 없으면 /login 리다이렉트하는 클라이언트 가드 훅.
// "use client" 컴포넌트에서 최상단에서 호출한다.
// 사용법: const ready = useAuthGuard();           // 토큰만 확인
//        const ready = useAuthGuard({ requireOnboarding: true }); // 온보딩 미완료면 /onboarding
//        if (!ready) return null;

"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getProfile, tokenStore } from "@/lib/api";

interface GuardOptions {
  /** true면 온보딩 미완료 사용자를 /onboarding 으로 보냄 (홈 등 진입점에서 사용) */
  requireOnboarding?: boolean;
}

/**
 * 토큰이 있으면 true 반환(렌더 허용).
 * 없으면 /login 리다이렉트 후 false 유지(컴포넌트는 null 반환).
 * requireOnboarding=true 인 경우, 프로필 onboarding_completed_at 가 null 이면
 * /onboarding 으로 보내고 false 유지.
 */
export function useAuthGuard(options: GuardOptions = {}): boolean {
  const { requireOnboarding = false } = options;
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const tok = tokenStore.get();
    if (!tok) {
      router.replace("/login");
      return;
    }
    if (!requireOnboarding) {
      setReady(true);
      return;
    }
    // 온보딩 게이트: 프로필 조회 후 미완료면 리다이렉트
    let cancelled = false;
    getProfile()
      .then((p) => {
        if (cancelled) return;
        if (!p.onboarding_completed_at) {
          router.replace("/onboarding");
        } else {
          setReady(true);
        }
      })
      .catch(() => {
        // 프로필 조회 실패(토큰 만료 등) → 로그인으로
        if (!cancelled) router.replace("/login");
      });
    return () => {
      cancelled = true;
    };
  }, [router, requireOnboarding]);

  return ready;
}
