import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useLayoutEffect, useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BookingMessageComposer } from "@/components/booking-message-composer";
import { copyText } from "@/lib/clipboard";
import { createBookingRequest, type BookingRequestResponse } from "@/lib/api";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  createBookingRequest: vi.fn(),
}));

vi.mock("@/lib/clipboard", () => ({ copyText: vi.fn() }));

const mockedCreateBookingRequest = vi.mocked(createBookingRequest);
const mockedCopyText = vi.mocked(copyText);

function response(token = "signed:token"): BookingRequestResponse {
  const booking_url = `https://www.inpa.kr/b/${token}`;
  return {
    token,
    booking_url,
    message: `김보장 고객님, 황예진 보험설계사입니다.\n${booking_url}`,
  };
}

function deferred<T>() {
  let resolve: (value: T) => void;
  let reject: (reason?: unknown) => void;
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, resolve: resolve!, reject: reject! };
}

beforeEach(() => {
  mockedCreateBookingRequest.mockReset();
  mockedCopyText.mockReset();
  mockedCopyText.mockResolvedValue(true);
});

describe("예약 안내 문구 생성기", () => {
  it("저장 준비가 끝난 뒤에만 선택한 고객의 예약 문구를 만든다", async () => {
    const order: string[] = [];
    const prepare = vi.fn(async () => { order.push("prepare"); });
    mockedCreateBookingRequest.mockImplementation(async () => {
      order.push("create");
      return response();
    });

    render(<BookingMessageComposer customerId={31} prepare={prepare} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "고객에게 보낼 문구 만들기" }));

    await waitFor(() => expect(order).toEqual(["prepare", "create"]));
    expect(mockedCreateBookingRequest).toHaveBeenCalledWith(31);
  });

  it("저장 준비가 실패하면 예약 문구 요청을 보내지 않는다", async () => {
    const prepare = vi.fn().mockRejectedValue(new Error("SAVE_FAILED"));

    render(<BookingMessageComposer customerId={31} prepare={prepare} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "고객에게 보낼 문구 만들기" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("예약 설정을 다시 저장해 주세요.");
    expect(mockedCreateBookingRequest).not.toHaveBeenCalled();
  });

  it("서버가 만든 문구와 주소를 그대로 보여 주고 편집한 문구와 주소를 각각 복사한다", async () => {
    const serverResponse = response();
    mockedCreateBookingRequest.mockResolvedValue(serverResponse);
    const user = userEvent.setup();

    render(<BookingMessageComposer customerId={31} />);
    await user.click(screen.getByRole("button", { name: "고객에게 보낼 문구 만들기" }));

    expect(await screen.findByLabelText("고객에게 보낼 메시지")).toHaveValue(serverResponse.message);
    expect(screen.getByText(serverResponse.booking_url)).toBeTruthy();
    const message = screen.getByLabelText("고객에게 보낼 메시지");
    await user.clear(message);
    await user.type(message, "편집한 실제 메시지");
    await user.click(screen.getByRole("button", { name: "메시지 전체 복사" }));
    expect(mockedCopyText).toHaveBeenLastCalledWith("편집한 실제 메시지");

    await user.click(screen.getByRole("button", { name: "링크만 복사" }));
    expect(mockedCopyText).toHaveBeenLastCalledWith(serverResponse.booking_url);
  });

  it("복사에 실패하면 성공 표시 없이 직접 복사를 안내한다", async () => {
    mockedCreateBookingRequest.mockResolvedValue(response());
    mockedCopyText.mockResolvedValue(false);
    const user = userEvent.setup();

    render(<BookingMessageComposer customerId={31} />);
    await user.click(screen.getByRole("button", { name: "고객에게 보낼 문구 만들기" }));
    await screen.findByLabelText("고객에게 보낼 메시지");
    await user.click(screen.getByRole("button", { name: "메시지 전체 복사" }));

    expect(screen.getByRole("alert")).toHaveTextContent("복사하지 못했어요. 문구를 길게 눌러 직접 복사해 주세요.");
    expect(screen.queryByText("메시지를 복사했어요.")).toBeNull();
  });

  it("고객이 바뀌면 이전 고객의 늦은 응답을 버리고 새 고객을 다시 만들 수 있다", async () => {
    const pending = deferred<BookingRequestResponse>();
    mockedCreateBookingRequest.mockReturnValueOnce(pending.promise);
    const { rerender } = render(<BookingMessageComposer customerId={31} />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "고객에게 보낼 문구 만들기" }));
    rerender(<BookingMessageComposer customerId={32} />);
    await act(async () => pending.resolve(response("customer-31-token")));

    expect(screen.queryByText(/customer-31-token/)).toBeNull();
    expect(screen.getByRole("button", { name: "고객에게 보낼 문구 만들기" })).toBeTruthy();
  });

  it("고객 전환 커밋부터 이전 고객의 문구와 주소를 렌더하지 않는다", async () => {
    const oldResponse = response("customer-31-token");
    mockedCreateBookingRequest.mockResolvedValue(oldResponse);
    const snapshots: string[] = [];

    function Probe() {
      const [customerId, setCustomerId] = useState(31);
      useLayoutEffect(() => {
        if (customerId === 32) {
          snapshots.push(document.querySelector('[aria-label="예약 안내 문구"]')?.textContent ?? "");
        }
      }, [customerId]);
      return <>
        <button type="button" onClick={() => setCustomerId(32)}>고객 바꾸기</button>
        <BookingMessageComposer customerId={customerId} />
      </>;
    }

    render(<Probe />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "고객에게 보낼 문구 만들기" }));
    await screen.findByText(oldResponse.booking_url);
    await user.click(screen.getByRole("button", { name: "고객 바꾸기" }));

    expect(snapshots).toHaveLength(1);
    expect(snapshots[0]).not.toContain(oldResponse.booking_url);
    expect(snapshots[0]).not.toContain(oldResponse.message);
  });

  it("고객 전환 첫 커밋에서 이전 고객의 저장 오류와 다시 만들기 상태를 숨긴다", async () => {
    const snapshots: { text: string; disabled: boolean; alerts: number }[] = [];

    function Probe() {
      const [customerId, setCustomerId] = useState(31);
      useLayoutEffect(() => {
        if (customerId === 32) {
          const composer = document.querySelector('[aria-label="예약 안내 문구"]');
          snapshots.push({
            text: composer?.textContent ?? "",
            disabled: (composer?.querySelector("button") as HTMLButtonElement).disabled,
            alerts: composer?.querySelectorAll('[role="alert"]').length ?? 0,
          });
        }
      }, [customerId]);
      return <>
        <button type="button" onClick={() => setCustomerId(32)}>고객 바꾸기</button>
        <BookingMessageComposer customerId={customerId} prepare={() => Promise.reject(new Error("SAVE_FAILED"))} />
      </>;
    }

    render(<Probe />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "고객에게 보낼 문구 만들기" }));
    await screen.findByRole("alert");
    await user.click(screen.getByRole("button", { name: "고객 바꾸기" }));

    expect(snapshots).toEqual([{ text: "고객에게 보낼 문구 만들기", disabled: false, alerts: 0 }]);
  });

  it("고객 전환 첫 커밋에서 이전 고객의 저장 중 버튼을 기본 활성 CTA로 바꾼다", async () => {
    const pendingPrepare = deferred<void>();
    const snapshots: { text: string; disabled: boolean }[] = [];

    function Probe() {
      const [customerId, setCustomerId] = useState(31);
      useLayoutEffect(() => {
        if (customerId === 32) {
          const composer = document.querySelector('[aria-label="예약 안내 문구"]');
          snapshots.push({
            text: composer?.textContent ?? "",
            disabled: (composer?.querySelector("button") as HTMLButtonElement).disabled,
          });
        }
      }, [customerId]);
      return <>
        <button type="button" onClick={() => setCustomerId(32)}>고객 바꾸기</button>
        <BookingMessageComposer customerId={customerId} prepare={() => pendingPrepare.promise} />
      </>;
    }

    render(<Probe />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "고객에게 보낼 문구 만들기" }));
    await user.click(screen.getByRole("button", { name: "고객 바꾸기" }));

    expect(snapshots).toEqual([{ text: "고객에게 보낼 문구 만들기", disabled: false }]);
    await act(async () => pendingPrepare.resolve());
  });

  it("고객 전환 첫 커밋에서 이전 고객의 복사 완료 안내를 숨긴다", async () => {
    mockedCreateBookingRequest.mockResolvedValue(response());
    const snapshots: string[] = [];

    function Probe() {
      const [customerId, setCustomerId] = useState(31);
      useLayoutEffect(() => {
        if (customerId === 32) {
          snapshots.push(document.querySelector('[aria-label="예약 안내 문구"]')?.textContent ?? "");
        }
      }, [customerId]);
      return <>
        <button type="button" onClick={() => setCustomerId(32)}>고객 바꾸기</button>
        <BookingMessageComposer customerId={customerId} />
      </>;
    }

    render(<Probe />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "고객에게 보낼 문구 만들기" }));
    await screen.findByRole("button", { name: "메시지 전체 복사" });
    await user.click(screen.getByRole("button", { name: "메시지 전체 복사" }));
    await user.click(screen.getByRole("button", { name: "고객 바꾸기" }));

    expect(snapshots).toEqual(["고객에게 보낼 문구 만들기"]);
  });

  it("고객이 바뀌면 늦게 끝난 복사 실패도 새 고객 화면에 보이지 않는다", async () => {
    mockedCreateBookingRequest.mockResolvedValue(response());
    const pendingCopy = deferred<boolean>();
    mockedCopyText.mockReturnValue(pendingCopy.promise);
    const user = userEvent.setup();
    const { rerender } = render(<BookingMessageComposer customerId={31} />);

    await user.click(screen.getByRole("button", { name: "고객에게 보낼 문구 만들기" }));
    await screen.findByLabelText("고객에게 보낼 메시지");
    await user.click(screen.getByRole("button", { name: "메시지 전체 복사" }));
    rerender(<BookingMessageComposer customerId={32} />);
    await act(async () => pendingCopy.resolve(false));

    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("생성 중 중복 요청을 막고 실패 후 같은 고객으로 다시 만들 수 있다", async () => {
    const pending = deferred<BookingRequestResponse>();
    mockedCreateBookingRequest.mockReturnValueOnce(pending.promise).mockResolvedValueOnce(response());
    const user = userEvent.setup();

    render(<BookingMessageComposer customerId={31} />);
    const button = screen.getByRole("button", { name: "고객에게 보낼 문구 만들기" });
    await user.click(button);
    await user.click(button);
    expect(mockedCreateBookingRequest).toHaveBeenCalledTimes(1);
    await act(async () => pending.reject(new Error("REQUEST_FAILED")));

    expect(await screen.findByRole("alert")).toHaveTextContent("문구를 다시 만들 수 있어요.");
    await user.click(screen.getByRole("button", { name: "다시 만들기" }));
    expect(mockedCreateBookingRequest).toHaveBeenCalledTimes(2);
  });

  it("같은 렌더 배치의 두 활성화도 저장 준비와 생성 요청을 한 번만 보낸다", async () => {
    const pendingPrepare = deferred<void>();
    const pendingCreate = deferred<BookingRequestResponse>();
    const prepare = vi.fn(() => pendingPrepare.promise);
    mockedCreateBookingRequest.mockReturnValue(pendingCreate.promise);

    render(<BookingMessageComposer customerId={31} prepare={prepare} />);
    const button = screen.getByRole("button", { name: "고객에게 보낼 문구 만들기" });
    act(() => {
      fireEvent.click(button);
      fireEvent.click(button);
    });
    expect(prepare).toHaveBeenCalledTimes(1);
    expect(mockedCreateBookingRequest).not.toHaveBeenCalled();

    await act(async () => pendingPrepare.resolve());
    expect(mockedCreateBookingRequest).toHaveBeenCalledTimes(1);
    await act(async () => pendingCreate.resolve(response()));
  });

  it("고객을 고르기 전에는 문구 생성을 막고 다음 행동을 안내한다", () => {
    render(<BookingMessageComposer customerId={null} />);

    expect(screen.getByRole("button", { name: "고객에게 보낼 문구 만들기" })).toBeDisabled();
    expect(screen.getByText("고객을 먼저 고르면 바로 예약 안내를 만들 수 있어요.")).toBeTruthy();
  });
});
