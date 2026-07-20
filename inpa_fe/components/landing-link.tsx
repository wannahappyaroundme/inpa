"use client";

import Link from "next/link";
import { createContext, useContext, type ReactNode } from "react";

// 랜딩 공용 링크. 기본은 www 내부 이동이며, 필요할 때만 가입·로그인 주소에
// 유입값을 미리 붙여 Next의 내부 이동에서도 값이 사라지지 않게 한다.

const UTM_KEYS = ["utm_source", "utm_medium", "utm_campaign"] as const;
type UtmKey = (typeof UTM_KEYS)[number];
type UtmValues = Partial<Record<UtmKey, string>>;
type BrandLanding = {
  appBase: string;
  utmSearch: string;
  utmDefaults: UtmValues;
};

const BrandLandingContext = createContext<BrandLanding>({
  appBase: "",
  utmSearch: "",
  utmDefaults: {},
});

export function BrandLandingProvider({
  appBase,
  utmSearch = "",
  utmDefaults = {},
  children,
}: {
  appBase: string;
  utmSearch?: string;
  utmDefaults?: UtmValues;
  children: ReactNode;
}) {
  return (
    <BrandLandingContext.Provider value={{ appBase, utmSearch, utmDefaults }}>
      {children}
    </BrandLandingContext.Provider>
  );
}

/** 현재 랜딩의 링크 기준 주소와 유입값. */
export function useBrandLanding(): BrandLanding {
  return useContext(BrandLandingContext);
}

function withLandingUtm(href: string, search: string, defaults: UtmValues): string {
  const hashIndex = href.indexOf("#");
  const hash = hashIndex >= 0 ? href.slice(hashIndex) : "";
  const withoutHash = hashIndex >= 0 ? href.slice(0, hashIndex) : href;
  const queryIndex = withoutHash.indexOf("?");
  const pathname = queryIndex >= 0 ? withoutHash.slice(0, queryIndex) : withoutHash;
  if (pathname !== "/register" && pathname !== "/login") return href;

  const params = new URLSearchParams(queryIndex >= 0 ? withoutHash.slice(queryIndex + 1) : "");
  const incoming = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  for (const [key, value] of incoming) {
    if (key.startsWith("utm_") && !params.has(key)) params.append(key, value);
  }
  for (const key of UTM_KEYS) {
    if (params.has(key)) continue;
    const value = defaults[key];
    if (value) params.set(key, value);
  }
  const query = params.toString();
  return `${pathname}${query ? `?${query}` : ""}${hash}`;
}

/** 랜딩 전용 링크. 같은 www 주소에서는 내부 이동을 유지한다. */
export function LandingLink({ href, className, children }: {
  href: string;
  className?: string;
  children: ReactNode;
}) {
  const { appBase, utmSearch, utmDefaults } = useBrandLanding();
  const resolvedHref = withLandingUtm(href, utmSearch, utmDefaults);
  if (appBase) {
    return <a href={`${appBase}${resolvedHref}`} className={className}>{children}</a>;
  }
  return <Link href={resolvedHref} className={className}>{children}</Link>;
}
