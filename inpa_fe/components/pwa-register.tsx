"use client";

import { useEffect } from "react";

// 서비스워커 등록(설치형 PWA). 실패는 조용히 무시(앱 동작에 영향 없음).
export function PwaRegister() {
  useEffect(() => {
    if (typeof navigator !== "undefined" && "serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => { /* 무시 */ });
    }
  }, []);
  return null;
}
