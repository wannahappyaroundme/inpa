"use client";

// 구글 소셜 로그인 버튼(병행) — GIS 렌더. 클라이언트 ID 없으면 렌더 안 함.
// credential(ID 토큰) → googleLogin → 토큰 저장 → onboarding 여부로 분기(이메일 로그인과 동일).

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { googleLogin, tokenStore, ApiError } from "@/lib/api";

const CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (cfg: {
            client_id: string;
            callback: (resp: { credential: string }) => void;
          }) => void;
          renderButton: (el: HTMLElement, opts: Record<string, unknown>) => void;
        };
      };
    };
  }
}

export function GoogleSignInButton() {
  const router = useRouter();
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!CLIENT_ID) return;
    let tries = 0;
    const timer = setInterval(() => {
      const gid = window.google?.accounts?.id;
      if (!gid) {
        if (++tries > 50) clearInterval(timer); // ~5s 대기 후 포기
        return;
      }
      clearInterval(timer);
      gid.initialize({
        client_id: CLIENT_ID,
        callback: async (resp) => {
          setError(null);
          try {
            const res = await googleLogin(resp.credential);
            tokenStore.set(res.token);
            router.replace(res.onboarding_completed ? "/home" : "/onboarding");
          } catch (e) {
            if (e instanceof ApiError && e.code === "GOOGLE_ALREADY_LINKED") {
              setError("이미 다른 구글 계정에 연결된 이메일이에요.");
            } else if (e instanceof ApiError) {
              setError("구글 로그인에 실패했어요. 다시 시도해 주세요.");
            } else {
              setError("네트워크 오류가 발생했어요.");
            }
          }
        },
      });
      if (ref.current) {
        gid.renderButton(ref.current, {
          theme: "outline", size: "large", width: 320,
          text: "continue_with", locale: "ko", shape: "pill",
        });
      }
    }, 100);
    return () => clearInterval(timer);
  }, [router]);

  if (!CLIENT_ID) return null;

  return (
    <div className="flex flex-col items-center gap-2">
      <div ref={ref} />
      {error && <p className="text-[13px] text-red-600">{error}</p>}
    </div>
  );
}
