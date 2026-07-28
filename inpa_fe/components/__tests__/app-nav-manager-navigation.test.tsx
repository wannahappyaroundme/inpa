import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppNav } from "@/components/app-nav";
import {
  acknowledgeManagerPromotion,
  getProfile,
  getUnreadCount,
} from "@/lib/api";

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
    tokenStore: { get: () => "token" },
    getUnreadCount: vi.fn(),
    getProfile: vi.fn(),
    acknowledgeManagerPromotion: vi.fn(),
  };
});

const profile = vi.mocked(getProfile);
const unread = vi.mocked(getUnreadCount);
const acknowledge = vi.mocked(acknowledgeManagerPromotion);

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

describe("AppNav Manager 프로그램 이동", () => {
  beforeEach(() => {
    navigation.push.mockReset();
    profile.mockReset();
    unread.mockReset();
    acknowledge.mockReset();
    unread.mockResolvedValue({
      unread_count: 0,
      customers: 0,
      schedule: 0,
      board: 0,
      promotion: 0,
      admin: 0,
      recruiting: 0,
    });
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

  it("늦게 열린 승격 안내도 전달받은 blocker로 취소하고 다시 허용한다", async () => {
    const user = userEvent.setup();
    const pendingProfile = deferred<Awaited<ReturnType<typeof getProfile>>>();
    const onBeforeNavigate = vi
      .fn<() => boolean>()
      .mockReturnValueOnce(false)
      .mockReturnValueOnce(true);
    profile.mockReturnValue(pendingProfile.promise);
    render(
      <AppNav
        active="settings"
        onBeforeNavigate={onBeforeNavigate}
      />,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await act(async () => {
      pendingProfile.resolve({
        is_admin: false,
        is_manager: true,
        managed_agents_count: 1,
        recruiting_enabled: true,
        manager_promoted_at: "2026-07-28T00:00:00Z",
        manager_promotion_seen_at: null,
        email: "planner@inpa.test",
        name: "김인파",
        affiliation: "인파",
        title: "팀장",
      } as Awaited<ReturnType<typeof getProfile>>);
    });

    const teamButton = await screen.findByRole("button", {
      name: "팀 현황 보기",
    });
    await user.click(teamButton);
    expect(navigation.push).not.toHaveBeenCalled();
    expect(acknowledge).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    await user.click(teamButton);
    expect(onBeforeNavigate).toHaveBeenCalledTimes(2);
    expect(navigation.push).toHaveBeenCalledWith("/manager");
    expect(acknowledge).toHaveBeenCalledTimes(1);
  });
});
