import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getFunnel = vi.fn();

vi.mock("@/lib/useAdminGuard", () => ({ useAdminGuard: () => true }));
vi.mock("@/lib/adminApi", () => ({
  adminGetActivationFunnel: (...args: unknown[]) => getFunnel(...args),
}));
vi.mock("@/components/charts", () => ({ BarChart: () => <div>차트</div> }));

import AdminActivationFunnelPage from "@/app/admin/activation-funnel/page";

const response = {
  days: 30,
  activation_window_days: 7,
  signup_count: 3,
  activated_count: 1,
  activation_rate: 33.3,
  avg_days_to_activation: 2,
  steps: [
    { step: "signup", label: "가입", count: 3, conversion_rate: null },
  ],
  utm_sources: [],
  acquisition_channels: [
    {
      channel: "search",
      label: "검색",
      signups: 2,
      verified: 1,
      first_customers: 1,
      first_analyses: 1,
      first_shares: 1,
      activated: 1,
      activation_rate: 50,
    },
    {
      channel: "ai",
      label: "AI",
      signups: 1,
      verified: 0,
      first_customers: 0,
      first_analyses: 0,
      first_shares: 0,
      activated: 0,
      activation_rate: 0,
    },
  ],
};

describe("AdminActivationFunnelPage", () => {
  beforeEach(() => getFunnel.mockReset());

  it("shows every acquisition step for search and AI channels", async () => {
    getFunnel.mockResolvedValue(response);
    render(<AdminActivationFunnelPage />);

    expect(await screen.findByText("채널별 단계 성과")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "첫 고객" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "첫 분석" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "첫 공유" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "7일 활성화" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "검색" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "AI" })).toBeInTheDocument();
  });

  it("offers a retry action when loading fails", async () => {
    getFunnel.mockRejectedValueOnce(new Error("network"));
    render(<AdminActivationFunnelPage />);

    expect(await screen.findByText("퍼널 데이터를 불러오지 못했어요.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "다시 불러오기" })).toBeInTheDocument();
  });
});
