import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ManagerPromotionModal } from "@/components/recruiting/manager-promotion-modal";
import { acknowledgeManagerPromotion } from "@/lib/api";

const navigation = vi.hoisted(() => ({
  push: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: navigation.push }),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    acknowledgeManagerPromotion: vi.fn(),
  };
});

const acknowledge = vi.mocked(acknowledgeManagerPromotion);

describe("Manager 승격 안내 이동 보호", () => {
  beforeEach(() => {
    navigation.push.mockReset();
    acknowledge.mockReset();
    acknowledge.mockResolvedValue({} as Awaited<
      ReturnType<typeof acknowledgeManagerPromotion>
    >);
    vi.stubGlobal(
      "requestAnimationFrame",
      (callback: FrameRequestCallback) => {
        callback(0);
        return 1;
      },
    );
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("프로그램 이동을 취소하면 모달과 확인 기록을 유지하고 이동하지 않는다", async () => {
    const user = userEvent.setup();
    const onBeforeNavigate = vi.fn(() => false);
    const onAcknowledged = vi.fn();
    render(
      <ManagerPromotionModal
        open
        recruitingEnabled
        onBeforeNavigate={onBeforeNavigate}
        onAcknowledged={onAcknowledged}
      />,
    );

    await user.click(screen.getByRole("button", { name: "팀 현황 보기" }));

    expect(onBeforeNavigate).toHaveBeenCalledTimes(1);
    expect(onAcknowledged).not.toHaveBeenCalled();
    expect(acknowledge).not.toHaveBeenCalled();
    expect(navigation.push).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("프로그램 이동을 허용하면 Enter 활성화에서도 한 번만 확인하고 이동한다", async () => {
    const user = userEvent.setup();
    const onBeforeNavigate = vi.fn(() => true);
    const onAcknowledged = vi.fn();
    render(
      <ManagerPromotionModal
        open
        recruitingEnabled
        onBeforeNavigate={onBeforeNavigate}
        onAcknowledged={onAcknowledged}
      />,
    );
    const button = screen.getByRole("button", { name: "팀 현황 보기" });
    button.focus();

    await user.keyboard("{Enter}");

    expect(onBeforeNavigate).toHaveBeenCalledTimes(1);
    expect(onAcknowledged).toHaveBeenCalledTimes(1);
    expect(acknowledge).toHaveBeenCalledTimes(1);
    expect(navigation.push).toHaveBeenCalledWith("/manager");
  });

  it("이동하지 않는 닫기는 navigation guard와 관계없이 동작한다", async () => {
    const user = userEvent.setup();
    const onBeforeNavigate = vi.fn(() => false);
    const onAcknowledged = vi.fn();
    render(
      <ManagerPromotionModal
        open
        recruitingEnabled
        onBeforeNavigate={onBeforeNavigate}
        onAcknowledged={onAcknowledged}
      />,
    );

    await user.click(screen.getByRole("button", { name: "닫기" }));

    expect(onBeforeNavigate).not.toHaveBeenCalled();
    expect(onAcknowledged).toHaveBeenCalledTimes(1);
    expect(acknowledge).toHaveBeenCalledTimes(1);
    expect(navigation.push).not.toHaveBeenCalled();
  });
});
