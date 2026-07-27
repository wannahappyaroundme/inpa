const SAFE_SIGNED_ROUTE_TOKEN = /^[A-Za-z0-9._:-]+$/;

export function isSafeSignedRouteToken(value: unknown): value is string {
  return (
    typeof value === "string"
    && value.length > 0
    && value !== "."
    && value !== ".."
    && SAFE_SIGNED_ROUTE_TOKEN.test(value)
  );
}

export function normalizeSignedRouteToken(value: unknown): string | null {
  if (typeof value !== "string") return null;
  try {
    const decoded = decodeURIComponent(value);
    return isSafeSignedRouteToken(decoded) ? decoded : null;
  } catch {
    return null;
  }
}
