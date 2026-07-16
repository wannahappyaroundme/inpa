export const MAIN_ORIGIN = "https://www.inpa.kr";

export type NewHostRoute =
  | { kind: "rewrite"; target: "/new" | "/new/test" }
  | { kind: "local-redirect"; target: "/" | "/test" }
  | { kind: "main-redirect"; target: string };

export function resolveNewHostRoute(pathname: string, search: string): NewHostRoute {
  if (pathname === "/") return { kind: "rewrite", target: "/new" };
  if (pathname === "/test") return { kind: "rewrite", target: "/new/test" };
  if (pathname === "/new") return { kind: "local-redirect", target: "/" };
  if (pathname === "/new/test") return { kind: "local-redirect", target: "/test" };
  return { kind: "main-redirect", target: `${MAIN_ORIGIN}${pathname}${search}` };
}
