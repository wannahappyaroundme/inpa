import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getBillingStatus: vi.fn(),
  reconfirmFirstCharge: vi.fn(),
  cancelBilling: vi.fn(),
  preflightRecurringCoupon: vi.fn(),
  startCardRegistration: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, ...api };
});
vi.mock("@/lib/useAuthGuard", () => ({
  useAuthGuard: () => true,
}));
vi.mock("@/components/app-nav", () => ({
  AppNav: () => <nav aria-label="앱 메뉴" />,
}));

import BillingPage from "@/app/settings/billing/page";

describe("결제와 쿠폰 화면", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getBillingStatus.mockResolvedValue({
      state: "trial",
      plan_code: "plus",
      plan_display_name: "Plus",
      access_through: "2027-02-04",
      next_charge_date: "2027-02-05",
      amount_krw: 21890,
      card_label: "신한카드 끝 7890",
      reconfirmation_required: true,
      reconfirmation_opens_on: "2027-01-29",
      existing_data_available: true,
    });
  });

  it("달력 날짜와 첫 결제 금액을 정확히 보여준다", async () => {
    render(<BillingPage />);

    expect(
      await screen.findByText("2027년 2월 4일까지 무료"),
    ).toBeTruthy();
    expect(
      screen.getByText("2027년 2월 5일 21,890원 결제 예정"),
    ).toBeTruthy();
    expect(screen.getByText("신한카드 끝 7890")).toBeTruthy();
  });

  it("첫 결제 내용을 다시 확인한 뒤 상태를 새로 읽는다", async () => {
    api.reconfirmFirstCharge.mockResolvedValue({
      consent_id: 31,
    });
    render(<BillingPage />);

    await userEvent.click(await screen.findByRole("checkbox", {
      name: "첫 결제 내용을 확인했어요",
    }));
    await userEvent.click(screen.getByRole("button", {
      name: "첫 결제 확인하기",
    }));

    expect(api.reconfirmFirstCharge).toHaveBeenCalledOnce();
    expect(api.getBillingStatus).toHaveBeenCalledTimes(2);
  });

  it("다음 결제를 멈춰도 현재 기간과 고객 데이터가 유지됨을 보여준다", async () => {
    api.cancelBilling.mockResolvedValue({
      state: "canceled",
      access_through: "2027-02-04",
      next_charge_date: null,
      existing_data_available: true,
    });
    render(<BillingPage />);

    await userEvent.click(await screen.findByRole("button", {
      name: "다음 결제 멈추기",
    }));
    expect(screen.getByText(
      "다음 결제를 멈춰도 2027년 2월 4일까지 이용해요.",
    )).toBeTruthy();
    expect(screen.getByText(
      "기존 고객과 메모, 상담 요약은 그대로 보관돼요.",
    )).toBeTruthy();
    await userEvent.click(screen.getByRole("button", {
      name: "다음 결제 멈춤 확인",
    }));

    expect(api.cancelBilling).toHaveBeenCalledOnce();
  });
});
