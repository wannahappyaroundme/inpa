import type { ManualInsuranceItem } from "@/lib/api";

export type ComparisonSide = "left" | "right";

export interface PolicySideSelection {
  left: boolean;
  right: boolean;
}

export type PolicySelectionMap = Record<number, PolicySideSelection>;

export interface PolicySelectionSnapshot {
  leftIds: number[];
  rightIds: number[];
}

export function isPolicyComparisonSelectable(item: ManualInsuranceItem): boolean {
  return (
    item.review_status === "confirmed"
    && item.analysis_included
    && !item.is_cancelled
  );
}

function initialSelection(item: ManualInsuranceItem): PolicySideSelection {
  if (!isPolicyComparisonSelectable(item)) {
    return { left: false, right: false };
  }
  if (item.portfolio_type === 1) {
    return { left: true, right: true };
  }
  if (item.portfolio_type === 2) {
    return { left: false, right: true };
  }
  return { left: false, right: false };
}

export function reconcilePolicySelection(
  items: ManualInsuranceItem[],
  previous: PolicySelectionMap,
): PolicySelectionMap {
  return Object.fromEntries(items.map((item) => [
    item.id,
    isPolicyComparisonSelectable(item)
      ? (previous[item.id] ?? initialSelection(item))
      : { left: false, right: false },
  ]));
}

export function buildPolicySelectionSnapshot(
  selection: PolicySelectionMap,
): PolicySelectionSnapshot {
  const leftIds: number[] = [];
  const rightIds: number[] = [];

  for (const [id, sides] of Object.entries(selection)) {
    const policyId = Number(id);
    if (sides.left) leftIds.push(policyId);
    if (sides.right) rightIds.push(policyId);
  }

  return {
    leftIds: leftIds.sort((a, b) => a - b),
    rightIds: rightIds.sort((a, b) => a - b),
  };
}

export function isSamePolicyIdSet(left: number[], right: number[]): boolean {
  const leftSet = new Set(left);
  const rightSet = new Set(right);

  return leftSet.size === rightSet.size && [...leftSet].every((id) => rightSet.has(id));
}

export function isSamePolicySelectionSnapshot(
  left: PolicySelectionSnapshot,
  right: PolicySelectionSnapshot,
): boolean {
  return (
    isSamePolicyIdSet(left.leftIds, right.leftIds)
    && isSamePolicyIdSet(left.rightIds, right.rightIds)
  );
}
