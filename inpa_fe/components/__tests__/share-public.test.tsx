import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SharePage from "@/app/s/[token]/page";
import { ApiError } from "@/lib/api";

const api = vi.hoisted(() => ({
  getShareView: vi.fn(),
  postShareEvent: vi.fn(),
}));
const navigation = vi.hoisted(() => ({ token: "share-token" }));

vi.mock("next/navigation", () => ({ useParams: () => ({ token: navigation.token }) }));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...api,
}));
vi.mock("@/components/content-guard", () => ({
  ContentProtect: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Watermark: () => null,
}));
vi.mock("@/components/ui", () => ({
  Card: ({ children, className = "" }: { children: React.ReactNode; className?: string }) => <div className={className}>{children}</div>,
  DisclaimerFooter: () => null,
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((nextResolve) => { resolve = nextResolve; });
  return { promise, resolve };
}

const callbackSuccess = {
  event_type: "callback_request" as const,
  recorded: true,
  notification: "created" as const,
};

function snapshot(name = "발급 때 담보") {
  return {
    captured_at: "2026-07-21T01:30:00Z",
    customer: { name_masked: "김**", gender: null, birth_year: 1985 },
    mode: "neutral" as const,
    summary: { monthly_premiums: 50_000, total_premiums: 12_000_000 },
    tree: [{
      category_id: 1,
      name: "진단",
      insurance_type: 2,
      sub_categories: [{
        sub_category_id: 2,
        name: "암",
        details: [{ detail_id: 3, name, held_amount: 30_000_000, status: "neutral" }],
      }],
    }],
    disclaimer: "인파가 등록된 보장 정보를 정리한 참고 자료입니다.",
  };
}

describe("public immutable share", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getShareView.mockReset();
    api.postShareEvent.mockReset();
    api.postShareEvent.mockResolvedValue(callbackSuccess);
    navigation.token = "share-token";
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });

  it("separates a terminal 404 from retryable 429, 5xx, and network errors", async () => {
    api.getShareView.mockRejectedValueOnce(new ApiError(404, "SHARE_LINK_EXPIRED", "expired"));
    const terminal = render(<SharePage />);
    expect(await screen.findByText("링크 사용 기간이 끝났어요")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "다시 불러오기" })).toBeNull();
    terminal.unmount();

    for (const error of [
      new ApiError(429, "THROTTLED", "busy"),
      new ApiError(503, "TEMPORARY", "down"),
      new TypeError("network"),
    ]) {
      api.getShareView.mockRejectedValueOnce(error).mockResolvedValueOnce({
        snapshot: snapshot(),
        actions: { booking_url: "/b/retry", planner_contact: null },
      });
      const view = render(<SharePage />);
      expect(await screen.findByText("잠시 연결이 원활하지 않아요")).toBeTruthy();
      await userEvent.setup().click(screen.getByRole("button", { name: "다시 불러오기" }));
      expect(await screen.findByText("발급 때 담보")).toBeTruthy();
      view.unmount();
    }
  });

  it("keeps the stored body across a day-four remount while using the new action", async () => {
    api.getShareView
      .mockResolvedValueOnce({
        snapshot: snapshot(),
        actions: { booking_url: "/b/day-zero", planner_contact: "010-0000-0000" },
      })
      .mockResolvedValueOnce({
        snapshot: snapshot(),
        actions: { booking_url: "/b/day-four", planner_contact: "010-9999-9999" },
      });
    const first = render(<SharePage />);
    expect(await screen.findByText("발급 때 담보")).toBeTruthy();
    expect(screen.getByRole("button", { name: /바로 상담 예약하기/ }).getAttribute("data-booking-url")).toBe("/b/day-zero");
    first.unmount();

    render(<SharePage />);
    expect(await screen.findByText("발급 때 담보")).toBeTruthy();
    expect(screen.getByRole("button", { name: /바로 상담 예약하기/ }).getAttribute("data-booking-url")).toBe("/b/day-four");
    expect(screen.queryByText("010-9999-9999")).toBeNull();
  });

  it("shows the KST capture time and the customer notice once without live-data wording", async () => {
    api.getShareView.mockResolvedValueOnce({
      snapshot: snapshot(),
      actions: { booking_url: null, planner_contact: null },
    });

    render(<SharePage />);

    expect(await screen.findByText("공유 당시 2026. 7. 21. 10:30")).toBeTruthy();
    expect(screen.queryByText("지금 보장 현황이에요")).toBeNull();
    expect(screen.queryByText("지금 보장받는 담보")).toBeNull();
    expect(screen.getAllByText("인파가 등록된 보장 정보를 정리한 참고 자료입니다.")).toHaveLength(1);
  });

  it("ignores an older token response and safely rejects a malformed stored body", async () => {
    const slow = deferred<unknown>();
    api.getShareView
      .mockReturnValueOnce(slow.promise)
      .mockResolvedValueOnce({
        snapshot: snapshot("새 토큰 담보"),
        actions: { booking_url: null, planner_contact: null },
      });
    const view = render(<SharePage />);
    navigation.token = "new-token";
    view.rerender(<SharePage />);
    expect(await screen.findByText("새 토큰 담보")).toBeTruthy();
    await act(async () => slow.resolve({
      snapshot: snapshot("오래된 토큰 담보"),
      actions: { booking_url: null, planner_contact: null },
    }));
    expect(screen.queryByText("오래된 토큰 담보")).toBeNull();
    view.unmount();

    api.getShareView.mockResolvedValueOnce({
      snapshot: { ...snapshot(), tree: [{ sub_categories: null }] },
      actions: {},
    });
    render(<SharePage />);
    expect(await screen.findByText("잠시 연결이 원활하지 않아요")).toBeTruthy();
    expect(screen.getByRole("button", { name: "다시 불러오기" })).toBeTruthy();
  });

  it("keeps only the newest public-copy timer and clears it on token change and unmount", async () => {
    vi.useFakeTimers();
    try {
      api.getShareView
        .mockResolvedValueOnce({
          snapshot: snapshot(),
          actions: { booking_url: null, planner_contact: null },
        })
        .mockResolvedValueOnce({
          snapshot: snapshot("B 토큰 담보"),
          actions: { booking_url: null, planner_contact: null },
        });
      const view = render(<SharePage />);
      await act(async () => Promise.resolve());
      const copy = screen.getByRole("button", { name: "이 링크 복사하기" });
      await act(async () => fireEvent.click(copy));
      expect(screen.getByRole("button", { name: "링크 복사됐어요!" })).toBeTruthy();
      act(() => vi.advanceTimersByTime(1000));
      await act(async () => fireEvent.click(screen.getByRole("button", { name: "링크 복사됐어요!" })));
      expect(vi.getTimerCount()).toBe(1);
      act(() => vi.advanceTimersByTime(1000));
      expect(screen.getByRole("button", { name: "링크 복사됐어요!" })).toBeTruthy();

      navigation.token = "token-b";
      view.rerender(<SharePage />);
      await act(async () => Promise.resolve());
      expect(vi.getTimerCount()).toBe(0);
      expect(screen.getByRole("button", { name: "이 링크 복사하기" })).toBeTruthy();
      view.unmount();
      act(() => vi.runOnlyPendingTimers());
      expect(vi.getTimerCount()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it("resets contact, callback, copied, and stale actions when the token changes", async () => {
    const next = deferred<unknown>();
    api.getShareView
      .mockResolvedValueOnce({
        snapshot: snapshot("A 토큰 담보"),
        actions: { booking_url: null, planner_contact: "010-1111-1111" },
      })
      .mockReturnValueOnce(next.promise);
    const view = render(<SharePage />);
    expect(await screen.findByText("A 토큰 담보")).toBeTruthy();
    await userEvent.setup().click(screen.getByRole("button", { name: "담당 설계사에게 물어보기" }));
    await userEvent.setup().click(screen.getByRole("button", { name: "연락 요청 남기기" }));
    fireEvent.click(screen.getByRole("button", { name: "이 링크 복사하기" }));
    expect(await screen.findByText("요청을 전달했어요. 곧 연락드릴 거예요.")).toBeTruthy();
    expect(await screen.findByRole("button", { name: "링크 복사됐어요!" })).toBeTruthy();

    navigation.token = "token-b";
    view.rerender(<SharePage />);
    await waitFor(() => expect(screen.queryByText("A 토큰 담보")).toBeNull());
    expect(screen.queryByText("요청을 전달했어요. 곧 연락드릴 거예요.")).toBeNull();
    await act(async () => next.resolve({
      snapshot: snapshot("B 토큰 담보"),
      actions: { booking_url: "/b/token-b", planner_contact: "010-2222-2222" },
    }));
    expect(await screen.findByText("B 토큰 담보")).toBeTruthy();
    expect(screen.queryByText("요청을 전달했어요. 곧 연락드릴 거예요.")).toBeNull();
    expect(screen.getByRole("button", { name: "이 링크 복사하기" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /바로 상담 예약하기/ }).getAttribute("data-booking-url")).toBe("/b/token-b");
  });

  it("연락 패널 상태를 알리고 열리면 첫 동작으로 focus를 옮긴다", async () => {
    api.getShareView.mockResolvedValueOnce({
      snapshot: snapshot(),
      actions: { booking_url: null, planner_contact: "010-1111-1111" },
    });
    render(<SharePage />);
    const user = userEvent.setup();
    const opener = await screen.findByRole("button", { name: "담당 설계사에게 물어보기" });

    expect(opener.getAttribute("aria-expanded")).toBe("false");
    await user.click(opener);
    expect(opener.getAttribute("aria-expanded")).toBe("true");
    expect(opener.getAttribute("aria-controls")).toBe("share-contact-panel");
    expect(screen.getByRole("region", { name: "담당 설계사 연락" })).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByRole("link", { name: "전화하기" }));
  });

  it("연락 요청은 서버 성공 뒤에만 완료로 표시하고 실패하면 다시 시도하게 한다", async () => {
    const pending = deferred<typeof callbackSuccess>();
    api.getShareView.mockResolvedValueOnce({
      snapshot: snapshot(),
      actions: { booking_url: null, planner_contact: null },
    });
    api.postShareEvent.mockImplementation((_token: string, eventType: string) =>
      eventType === "callback_request"
        ? pending.promise
        : Promise.resolve({ event_type: eventType, recorded: true })
    );
    const firstView = render(<SharePage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "담당 설계사에게 물어보기" }));

    await user.click(screen.getByRole("button", { name: "연락 요청 남기기" }));
    expect(screen.queryByText("요청을 전달했어요. 곧 연락드릴 거예요.")).toBeNull();
    await act(async () => pending.resolve(callbackSuccess));
    expect(await screen.findByText("요청을 전달했어요. 곧 연락드릴 거예요.")).toBeTruthy();
    firstView.unmount();

    navigation.token = "token-b";
    api.getShareView.mockResolvedValueOnce({
      snapshot: snapshot("B 연락 담보"),
      actions: { booking_url: null, planner_contact: null },
    });
    let callbackAttempt = 0;
    api.postShareEvent.mockImplementation((_token: string, eventType: string) => {
      if (eventType !== "callback_request") {
        return Promise.resolve({ event_type: eventType, recorded: true });
      }
      callbackAttempt += 1;
      return callbackAttempt === 1
        ? Promise.reject(new ApiError(503, "CALLBACK_NOTIFICATION_FAILED", "연락 요청을 다시 남겨 주세요."))
        : Promise.resolve(callbackSuccess);
    });
    const retryView = render(<SharePage />);
    await screen.findByText("B 연락 담보");
    await user.click(screen.getByRole("button", { name: "담당 설계사에게 물어보기" }));
    await user.click(screen.getByRole("button", { name: "연락 요청 남기기" }));
    expect((await screen.findByRole("alert")).textContent).toContain("연결이 잠시 원활하지 않아요");
    expect(screen.queryByText("요청을 전달했어요. 곧 연락드릴 거예요.")).toBeNull();

    await user.click(screen.getByRole("button", { name: "연락 요청 다시 남기기" }));
    expect(await screen.findByText("요청을 전달했어요. 곧 연락드릴 거예요.")).toBeTruthy();
    retryView.unmount();
  });
});
