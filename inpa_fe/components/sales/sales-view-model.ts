import type { RecruitingTab } from "@/components/recruiting/recruiting-view-model";

export type SalesTab = "customers" | "recruiting";

export function normalizeSalesTab(value: string | null): SalesTab {
  return value === "recruiting" ? "recruiting" : "customers";
}

export function resolveSalesTab(
  value: string | null,
  recruitingEnabled: boolean,
): SalesTab {
  const requested = normalizeSalesTab(value);
  return requested === "recruiting" && !recruitingEnabled
    ? "customers"
    : requested;
}

export function buildRecruitingSalesHref(view: RecruitingTab): string {
  return `/sales?tab=recruiting&view=${view}`;
}
