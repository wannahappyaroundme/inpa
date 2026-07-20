export const MAIN_ORIGIN = "https://www.inpa.kr";

export type NewHostRoute = { kind: "main-redirect"; target: string };

export function resolveNewHostRoute(pathname: string, search: string): NewHostRoute {
  if (pathname === "/" || pathname === "/new") {
    return { kind: "main-redirect", target: `${MAIN_ORIGIN}/story${search}` };
  }
  if (pathname === "/test" || pathname === "/new/test") {
    return { kind: "main-redirect", target: `${MAIN_ORIGIN}/${search}` };
  }
  return { kind: "main-redirect", target: `${MAIN_ORIGIN}${pathname}${search}` };
}

export function resolveLegacyMainRoute(pathname: string, search: string): string | null {
  if (pathname === "/new") return `/story${search}`;
  if (pathname === "/new/test") return `/${search}`;
  return null;
}
