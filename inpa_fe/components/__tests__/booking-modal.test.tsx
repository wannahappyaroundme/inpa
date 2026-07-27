import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BookingModal } from "@/components/booking-modal";
import { createBookingRequest, type BookingRequestResponse } from "@/lib/api";
import { copyText } from "@/lib/clipboard";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  createBookingRequest: vi.fn(),
}));

vi.mock("@/lib/clipboard", () => ({ copyText: vi.fn() }));

const mockedCreateBookingRequest = vi.mocked(createBookingRequest);
const mockedCopyText = vi.mocked(copyText);

function response(): BookingRequestResponse {
  return {
    token: "signed:token",
    booking_url: "https://www.inpa.kr/b/signed:token",
    message: "실제 고객에게 보낼 예약 안내 문구",
  };
}

beforeEach(() => {
  mockedCreateBookingRequest.mockReset();
  mockedCopyText.mockReset();
  mockedCopyText.mockResolvedValue(true);
});

describe("고객 상세 예약 안내 모달", () => {
  it("고유한 실제 제목으로 dialog를 설명하고 첫 동작인 닫기에 focus한다", async () => {
    const firstRender = render(<BookingModal customerId={31} onClose={vi.fn()} />);
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "닫기" })));
    firstRender.unmount();

    render(<><BookingModal customerId={31} onClose={vi.fn()} /><BookingModal customerId={32} onClose={vi.fn()} /></>);

    const dialogs = screen.getAllByRole("dialog");
    expect(dialogs).toHaveLength(2);
    for (const dialog of dialogs) {
      const titleId = dialog.getAttribute("aria-labelledby");
      expect(titleId).toBeTruthy();
      expect(document.getElementById(titleId!)).toHaveTextContent("미팅 예약 링크");
    }
    expect(dialogs[0].getAttribute("aria-labelledby")).not.toBe(dialogs[1].getAttribute("aria-labelledby"));
  });

  it("Escape는 한 번만 닫고 부모가 unmount한 뒤 opener로 focus를 돌린다", async () => {
    const onClose = vi.fn();
    function Probe() {
      const [open, setOpen] = useState(false);
      return <>
        <button type="button" onClick={() => setOpen(true)}>열기</button>
        {open && <BookingModal customerId={31} onClose={() => { onClose(); setOpen(false); }} />}
      </>;
    }
    render(<Probe />);
    const opener = screen.getByRole("button", { name: "열기" });
    await userEvent.setup().click(opener);
    await screen.findByRole("dialog");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(document.activeElement).toBe(opener));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("Tab과 Shift+Tab을 dialog 안의 실제 조작 요소 사이에서 순환한다", async () => {
    render(<BookingModal customerId={31} onClose={vi.fn()} />);
    const close = screen.getByRole("button", { name: "닫기" });
    const create = screen.getByRole("button", { name: "고객에게 보낼 문구 만들기" });
    await waitFor(() => expect(document.activeElement).toBe(close));

    close.focus();
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(create);
    create.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(close);
  });

  it("공용 Composer로 현재 고객의 문구를 만들고 복사 실패를 같은 안내로 보여 준다", async () => {
    mockedCreateBookingRequest.mockResolvedValue(response());
    mockedCopyText.mockResolvedValue(false);
    const user = userEvent.setup();
    render(<BookingModal customerId={77} onClose={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "고객에게 보낼 문구 만들기" }));
    expect(mockedCreateBookingRequest).toHaveBeenCalledWith(77);
    await screen.findByLabelText("고객에게 보낼 메시지");
    await user.click(screen.getByRole("button", { name: "메시지 전체 복사" }));

    expect(screen.getByRole("alert")).toHaveTextContent("복사하지 못했어요. 문구를 길게 눌러 직접 복사해 주세요.");
    expect(screen.queryByText("메시지를 복사했어요.")).toBeNull();
  });
});
