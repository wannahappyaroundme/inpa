export interface NormalizedAdminApiError {
  code: string;
  detail: string;
}

export function normalizeAdminApiError(
  data: Record<string, unknown>,
  status: number,
  statusText: string,
): NormalizedAdminApiError {
  const errorCode = data["error"];
  const responseCode = data["code"];
  const code =
    typeof errorCode === "string" && errorCode
      ? errorCode
      : typeof responseCode === "string" && responseCode
        ? responseCode
        : String(status);

  const detail = data["detail"];
  if (typeof detail === "string" && detail) return { code, detail };
  const message = data["message"];
  if (typeof message === "string" && message) return { code, detail: message };
  for (const value of Object.values(data)) {
    if (Array.isArray(value) && typeof value[0] === "string") {
      return { code, detail: value[0] };
    }
  }
  return { code, detail: statusText };
}
