import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  adminGetBillingOverview: vi.fn(),
  adminListBillingCoupons: vi.fn(),
  adminCreateBillingCoupon: vi.fn(),
  adminUpdateBillingCoupon: vi.fn(),
  adminUpdateBillingSettings: vi.fn(),
  adminQueueBillingReconciliation: vi.fn(),
  adminQueueBillingTokenRevocation: vi.fn(),
}));

vi.mock("@/lib/adminApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adminApi")>(
    "@/lib/adminApi",
  );
  return { ...actual, ...api };
});
vi.mock("@/lib/useAdminGuard", () => ({
  useAdminGuard: () => true,
}));

import AdminBillingPage from "@/app/admin/billing/page";

function overview() {
  return {
    status: {
      agreement_count: 3,
      trial_count: 1,
      active_count: 1,
      unknown_order_count: 1,
      revocation_pending_token_count: 1,
      held_coupon_claim_count: 2,
      terminal_event_gap_count: 0,
    },
    environment: {
      card_registration_env: false,
      recurring_charge_env: false,
      reconciliation_env: false,
      provider_credentials_ready: false,
      card_registration_effective: false,
      recurring_charge_effective: false,
      reconciliation_effective: false,
    },
    settings: {
      free_tier_unlimited: true,
      billing_card_registration_enabled: false,
      billing_recurring_charge_enabled: false,
      billing_reconciliation_enabled: false,
    },
    recent_agreements: [],
    recent_orders: [{
      id: 7,
      agreement_id: "agreement-1",
      user_email: "planner@example.com",
      cycle_sequence: 1,
      merchant_order_id: "INPA-ORDER-1",
      amount_krw: 21890,
      due_date: "2026-08-08",
      status: "unknown",
      failure_code: "TRANSPORT_UNKNOWN",
      unknown_since: "2026-08-08T00:00:00Z",
      temporary_access_until: "2026-08-09T00:00:00Z",
      created_at: "2026-08-08T00:00:00Z",
      updated_at: "2026-08-08T00:00:00Z",
    }],
  };
}

describe("관리자 결제 운영", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.adminGetBillingOverview.mockResolvedValue(overview());
    api.adminListBillingCoupons.mockResolvedValue([]);
  });

  it("환경 게이트와 미확정 대기열을 원문 없이 보여준다", async () => {
    render(<AdminBillingPage />);
    expect(await screen.findByText("결제·쿠폰 운영")).toBeTruthy();
    expect(screen.getByText("미확정 결제")).toBeTruthy();
    expect(screen.getByText("planner@example.com")).toBeTruthy();
    expect(screen.getByText(
      /서버 환경 설정을 마치면 운영 스위치를 켤 수 있어요/,
    )).toBeTruthy();
  });

  it("1~3개월 중 선택해 사용 기한이 있는 쿠폰을 발행한다", async () => {
    api.adminCreateBillingCoupon.mockResolvedValue({
      id: 31,
      code: "INPA-ABCD2345",
      plan_code: "plus",
      plan_display_name: "Plus",
      duration_months: 2,
      redeem_by: "2026-10-31T14:59:00Z",
      max_redemptions: 100,
      redeemed_count: 0,
      is_active: true,
      note: "설명회",
      created_at: "2026-07-27T00:00:00Z",
    });
    render(<AdminBillingPage />);

    await userEvent.selectOptions(
      await screen.findByLabelText("무료 이용 개월"),
      "2",
    );
    await userEvent.type(
      screen.getByLabelText("쿠폰 사용 기한"),
      "2026-10-31T23:59",
    );
    await userEvent.clear(screen.getByLabelText("최대 사용 인원"));
    await userEvent.type(screen.getByLabelText("최대 사용 인원"), "100");
    await userEvent.click(screen.getByRole("button", {
      name: "쿠폰 발행",
    }));

    expect(api.adminCreateBillingCoupon).toHaveBeenCalledWith(
      expect.objectContaining({
        duration_months: 2,
        max_redemptions: 100,
      }),
      expect.any(String),
    );
    expect(await screen.findByText("INPA-ABCD2345")).toBeTruthy();
  });
});
