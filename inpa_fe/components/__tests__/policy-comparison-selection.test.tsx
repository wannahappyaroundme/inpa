import { describe, expect, it } from "vitest";

import type { ManualInsuranceItem } from "@/lib/api";
import {
  buildPolicySelectionSnapshot,
  isPolicyComparisonSelectable,
  isSamePolicyIdSet,
  isSamePolicySelectionSnapshot,
  reconcilePolicySelection,
} from "@/lib/policy-comparison-selection";

const insurance = (overrides: Partial<ManualInsuranceItem> = {}): ManualInsuranceItem => ({
  id: 9,
  name: "보험",
  insurance_type: 2,
  portfolio_type: 1,
  monthly_premiums: 30_000,
  contract_date: null,
  expiry_date: null,
  contractor_name: null,
  insured_name: null,
  is_same_insured: null,
  payment_status: null,
  is_cancelled: false,
  cancelled_at: null,
  created_at: "2026-07-27T00:00:00Z",
  review_status: "confirmed",
  analysis_included: true,
  data_version: 1,
  confirmation_source: "manual_entry",
  confirmed_at: "2026-07-27T00:00:00Z",
  review_exclusion_reason: "",
  ...overrides,
});

describe("policy comparison selection", () => {
  it("uses the portfolio preset for policies without a prior selection", () => {
    const a1 = insurance({ id: 1, portfolio_type: 1 });
    const a2 = insurance({ id: 2, portfolio_type: 1 });
    const a3 = insurance({ id: 3, portfolio_type: 1 });
    const b1 = insurance({ id: 4, portfolio_type: 2 });

    expect(reconcilePolicySelection([a1, a2, a3, b1], {})).toEqual({
      1: { left: true, right: true },
      2: { left: true, right: true },
      3: { left: true, right: true },
      4: { left: false, right: true },
    });
  });

  it("preserves selectable refresh choices and clears disabled policies", () => {
    const previous = {
      1: { left: true, right: true },
      2: { left: true, right: false },
    };
    const refreshed = [
      insurance({ id: 1, portfolio_type: 1 }),
      insurance({ id: 2, portfolio_type: 1 }),
      insurance({ id: 3, portfolio_type: 2 }),
      insurance({ id: 4, portfolio_type: 1, is_cancelled: true }),
    ];

    expect(reconcilePolicySelection(refreshed, previous)).toEqual({
      1: { left: true, right: true },
      2: { left: true, right: false },
      3: { left: false, right: true },
      4: { left: false, right: false },
    });
    expect(isPolicyComparisonSelectable(insurance({ review_status: "draft" }))).toBe(false);
    expect(isPolicyComparisonSelectable(insurance({ analysis_included: false }))).toBe(false);
    expect(reconcilePolicySelection([
      insurance({ id: 5, review_status: "draft" }),
      insurance({ id: 6, analysis_included: false }),
    ], {
      5: { left: true, right: true },
      6: { left: true, right: true },
    })).toEqual({
      5: { left: false, right: false },
      6: { left: false, right: false },
    });
  });

  it("builds sorted snapshots and compares policy ID sets independent of order", () => {
    const snapshot = buildPolicySelectionSnapshot({
      3: { left: true, right: false },
      1: { left: true, right: true },
      4: { left: false, right: true },
      2: { left: true, right: true },
    });

    expect(snapshot).toEqual({
      leftIds: [1, 2, 3],
      rightIds: [1, 2, 4],
    });
    expect(isSamePolicyIdSet([3, 1, 2], [2, 3, 1])).toBe(true);
    expect(isSamePolicyIdSet([1, 2, 3], [1, 2, 4])).toBe(false);
    expect(isSamePolicySelectionSnapshot(snapshot, {
      leftIds: [3, 2, 1],
      rightIds: [4, 1, 2],
    })).toBe(true);
  });
});
