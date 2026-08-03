import { track } from "@vercel/analytics";

export type PublicResource = "insurance_age" | "customer_sheet" | "consultation_checklist";
export type PublicResourceAction = "calculate" | "download" | "print";
export type PublicResourcePageKind = "tool" | "resource";

export function trackPublicResourceUse(
  resource: PublicResource,
  action: PublicResourceAction,
  pageKind: PublicResourcePageKind,
) {
  try {
    void Promise.resolve(track("public_resource_use", {
      resource,
      action,
      page_kind: pageKind,
    })).catch(() => undefined);
  } catch {
    // 계측 오류는 공개 도구 사용을 막지 않는다.
  }
}
