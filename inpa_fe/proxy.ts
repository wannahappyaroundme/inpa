import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { resolveLegacyMainRoute, resolveNewHostRoute } from "@/lib/new-host-routing";

// new.inpa.kr의 공개 랜딩은 www 공식 주소로 이전했다.
// 이전 주소와 서비스 경로를 모두 www로 영구 이동해 기존 공유 링크를 보호한다.
// www·프리뷰·localhost에서는 과거 내부 랜딩 주소만 같은 공식 경로로 이동한다.
const NEW_HOST = "new.inpa.kr";

export function proxy(request: NextRequest) {
  const host = (request.headers.get("host") ?? "").toLowerCase();
  const isNewHost = host === NEW_HOST || host.startsWith(`${NEW_HOST}:`);
  const { pathname, search } = request.nextUrl;
  if (!isNewHost) {
    const legacyTarget = resolveLegacyMainRoute(pathname, search);
    if (!legacyTarget) return;
    return NextResponse.redirect(new URL(legacyTarget, request.url), 308);
  }

  const route = resolveNewHostRoute(pathname, search);
  return NextResponse.redirect(route.target, 308);
}

export const config = {
  // 정적 자산(_next, 확장자 있는 파일)은 통과 — 랜딩 이미지·폰트가 new host에서 그대로 서빙되도록
  matcher: ["/((?!_next|.*\\..*).*)"],
};
