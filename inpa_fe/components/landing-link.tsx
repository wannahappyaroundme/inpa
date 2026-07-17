"use client";

import Link from "next/link";
import { createContext, useContext, type ReactNode } from "react";

// 랜딩 섹션(landing-sections·brand-story-sections)은 www와 new.inpa.kr이 공용으로 쓴다.
// 서비스 경로(/register·/login·/blog·/faq·/legal/*·/data-policy)는 실제로 www에만 존재하므로,
// new.inpa.kr에서는 www 절대주소를 가리키는 '바깥 링크'로 렌더해야 한다.
//  - www(기본, appBase=""): 내부 <Link> — 프리페치·소프트 내비 그대로(렌더 결과 불변)
//  - new(appBase="https://www.inpa.kr"): <a href="https://www.inpa.kr/..."> — 프리페치 없음, 하드 내비
// 이렇게 하면 교차도메인 RSC 프리페치가 애초에 생기지 않아 CORS/503 잡음이 사라진다.
// ★ www 통합 시: appBase만 ""로 두면 전부 내부 링크로 자동 복귀 → 별도 정리 불필요.

type BrandLanding = { appBase: string };

const BrandLandingContext = createContext<BrandLanding>({ appBase: "" });

export function BrandLandingProvider({ appBase, children }: { appBase: string; children: ReactNode }) {
  return <BrandLandingContext.Provider value={{ appBase }}>{children}</BrandLandingContext.Provider>;
}

/** 현재 랜딩이 브랜드 도메인(new.inpa.kr)에서 렌더되는지 여부(appBase 비어 있으면 www 본진). */
export function useBrandLanding(): BrandLanding {
  return useContext(BrandLandingContext);
}

/** 랜딩 전용 링크. www에선 내부 <Link>, new.inpa.kr에선 www 절대주소 <a>. */
export function LandingLink({ href, className, children }: {
  href: string;
  className?: string;
  children: ReactNode;
}) {
  const { appBase } = useBrandLanding();
  if (appBase) {
    return <a href={`${appBase}${href}`} className={className}>{children}</a>;
  }
  return <Link href={href} className={className}>{children}</Link>;
}
