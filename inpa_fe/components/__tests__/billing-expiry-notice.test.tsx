import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  leaseBillingNotice: vi.fn(),
  markBillingNoticeRendered: vi.fn(),
  dismissBillingNotice: vi.fn(),
  tokenStore: { get: vi.fn(() => "token") },
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, ...api };
});

import { FreeTransitionNotice } from "@/components/billing/free-transition-notice";

describe("무료 전환 1회 안내", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    vi.stubGlobal("crypto", {
      randomUUID: () => "00000000-0000-4000-8000-000000000031",
    });
    api.tokenStore.get.mockReturnValue("token");
    api.leaseBillingNotice.mockResolvedValue({
      notice: {
        id: 11,
        type: "free_transition",
        title: "무료 요금제로 전환됐어요",
        body: "결제 메뉴에서 Plus를 다시 시작할 수 있어요.",
        action_label: "카드 등록하고 다시 시작",
        action_path: "/settings/billing",
        existing_data_available: true,
      },
    });
    api.markBillingNoticeRendered.mockResolvedValue({
      notice_id: 11,
      rendered: true,
    });
    api.dismissBillingNotice.mockResolvedValue({
      notice_id: 11,
      dismissed: true,
    });
  });

  it("기존 데이터 보존과 다음 행동을 최초 한 번 안내한다", async () => {
    render(<FreeTransitionNotice />);

    expect(
      await screen.findByText("무료 요금제로 전환됐어요"),
    ).toBeTruthy();
    expect(screen.getByText(
      "기존 고객과 메모, 상담 요약은 그대로 보관돼요.",
    )).toBeTruthy();
    expect(screen.getByRole("link", {
      name: "카드 등록하고 다시 시작",
    })).toBeTruthy();
    await vi.waitFor(() => {
      expect(api.markBillingNoticeRendered).toHaveBeenCalledWith(
        11,
        "00000000-0000-4000-8000-000000000031",
      );
    });

    await userEvent.click(screen.getByRole("button", {
      name: "안내 닫기",
    }));
    expect(api.dismissBillingNotice).toHaveBeenCalledWith(11);
  });

  it("표시할 사건이 없으면 화면을 열지 않는다", async () => {
    api.leaseBillingNotice.mockResolvedValue({ notice: null });
    render(<FreeTransitionNotice />);
    await vi.waitFor(() => {
      expect(api.leaseBillingNotice).toHaveBeenCalledOnce();
    });
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
