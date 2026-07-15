import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { resolveNewHostRoute } from "@/lib/new-host-routing";

// new.inpa.kr = 브랜드 시네마 랜딩 전용 host.
// 공개 랜딩 경로만 내부 페이지로 rewrite(주소창 유지), 그 외 서비스 경로는 본진(www)으로 보낸다.
// www·프리뷰·localhost 트래픽은 어떤 개입도 하지 않는다.
const NEW_HOST = "new.inpa.kr";

export function proxy(request: NextRequest) {
  const host = (request.headers.get("host") ?? "").toLowerCase();
  const isNewHost = host === NEW_HOST || host.startsWith(`${NEW_HOST}:`);
  if (!isNewHost) return;

  const { pathname, search } = request.nextUrl;
  const route = resolveNewHostRoute(pathname, search);
  if (route.kind === "rewrite") return NextResponse.rewrite(new URL(route.target, request.url));
  if (route.kind === "local-redirect") return NextResponse.redirect(new URL(route.target, request.url));
  return NextResponse.redirect(route.target);
}

export const config = {
  // 정적 자산(_next, 확장자 있는 파일)은 통과 — 랜딩 이미지·폰트가 new host에서 그대로 서빙되도록
  matcher: ["/((?!_next|.*\\..*).*)"],
};
