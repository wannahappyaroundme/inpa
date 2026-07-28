import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TalkTemplateShare } from "@/components/talk-template-share";
import { copyText } from "@/lib/clipboard";

vi.mock("@/lib/clipboard", () => ({ copyText: vi.fn() }));

const mockedCopyText = vi.mocked(copyText);
const finalText = "김고객 고객님, 다음 항목을 함께 확인할까요?";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((next, fail) => {
    resolve = next;
    reject = fail;
  });
  return { promise, resolve, reject };
}

function setDeviceShare(
  share: ((data?: ShareData) => Promise<void>) | undefined,
) {
  Object.defineProperty(navigator, "share", {
    configurable: true,
    value: share,
  });
}

beforeEach(() => {
  mockedCopyText.mockReset();
  mockedCopyText.mockResolvedValue(true);
  setDeviceShare(undefined);
});

afterEach(() => {
  setDeviceShare(undefined);
});

describe("TalkTemplateShare", () => {
  it("always shows a read-only final message and copy, without a device action when unsupported", () => {
    render(
      <TalkTemplateShare
        open
        title="첫 연락"
        text={finalText}
        disabledReason={null}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("최종 공유 문구")).toHaveValue(finalText);
    expect(screen.getByLabelText("최종 공유 문구")).toHaveAttribute(
      "readonly",
    );
    expect(screen.getByRole("button", { name: "문구 복사" }))
      .toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "기기에서 공유" }))
      .not.toBeInTheDocument();
  });

  it("announces copy success and failure through a live region", async () => {
    const user = userEvent.setup();
    const first = render(
      <TalkTemplateShare
        open
        title="첫 연락"
        text={finalText}
        disabledReason={null}
        onClose={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "문구 복사" }));
    expect(screen.getByText("문구를 복사했어요.")).toHaveAttribute(
      "aria-live",
      "polite",
    );
    expect(mockedCopyText).toHaveBeenCalledWith(finalText);

    first.unmount();
    mockedCopyText.mockResolvedValue(false);
    render(
      <TalkTemplateShare
        open
        title="첫 연락"
        text={finalText}
        disabledReason={null}
        onClose={vi.fn()}
      />,
    );
    await user.click(screen.getByRole("button", { name: "문구 복사" }));
    expect(
      screen.getByText("복사가 중단됐어요. 문구를 길게 눌러 직접 복사해 주세요."),
    ).toHaveAttribute("aria-live", "polite");
  });

  it("settles copy and announces success after the Strict Mode effect replay", async () => {
    const pendingCopy = deferred<boolean>();
    mockedCopyText.mockReturnValue(pendingCopy.promise);
    const user = userEvent.setup();
    render(
      <StrictMode>
        <TalkTemplateShare
          open
          title="첫 연락"
          text={finalText}
          disabledReason={null}
          onClose={vi.fn()}
        />
      </StrictMode>,
    );

    await user.click(screen.getByRole("button", { name: "문구 복사" }));
    expect(screen.getByRole("button", { name: "복사 중" })).toBeDisabled();

    await act(async () => {
      pendingCopy.resolve(true);
    });

    expect(screen.getByText("문구를 복사했어요.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "문구 복사" })).toBeEnabled();
  });

  it("shows device share only when supported and sends the final text", async () => {
    const share = vi.fn().mockResolvedValue(undefined);
    setDeviceShare(share);
    const user = userEvent.setup();
    render(
      <TalkTemplateShare
        open
        title="첫 연락"
        text={finalText}
        disabledReason={null}
        onClose={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "기기에서 공유" }));

    expect(share).toHaveBeenCalledWith({
      title: "첫 연락",
      text: finalText,
    });
  });

  it("settles device sharing after the Strict Mode effect replay", async () => {
    const pendingShare = deferred<void>();
    setDeviceShare(vi.fn().mockReturnValue(pendingShare.promise));
    const user = userEvent.setup();
    render(
      <StrictMode>
        <TalkTemplateShare
          open
          title="첫 연락"
          text={finalText}
          disabledReason={null}
          onClose={vi.fn()}
        />
      </StrictMode>,
    );

    await user.click(screen.getByRole("button", { name: "기기에서 공유" }));
    expect(
      screen.getByRole("button", { name: "공유창 여는 중" }),
    ).toBeDisabled();

    await act(async () => {
      pendingShare.resolve();
    });

    expect(
      screen.getByRole("button", { name: "기기에서 공유" }),
    ).toBeEnabled();
  });

  it("treats AbortError as a neutral device-share cancellation", async () => {
    setDeviceShare(
      vi.fn().mockRejectedValue(new DOMException("cancel", "AbortError")),
    );
    const user = userEvent.setup();
    render(
      <TalkTemplateShare
        open
        title="첫 연락"
        text={finalText}
        disabledReason={null}
        onClose={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "기기에서 공유" }));

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows other share errors while keeping copy usable", async () => {
    setDeviceShare(vi.fn().mockRejectedValue(new Error("unavailable")));
    const user = userEvent.setup();
    render(
      <TalkTemplateShare
        open
        title="첫 연락"
        text={finalText}
        disabledReason={null}
        onClose={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "기기에서 공유" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "기기 공유 연결이 중단됐어요. 문구 복사를 이용해 주세요.",
    );

    await user.click(screen.getByRole("button", { name: "문구 복사" }));
    expect(mockedCopyText).toHaveBeenCalledWith(finalText);
    expect(screen.getByText("문구를 복사했어요.")).toBeInTheDocument();
  });

  it("ignores an older copy result after the shared title or text changes", async () => {
    const pendingCopy = deferred<boolean>();
    mockedCopyText.mockReturnValue(pendingCopy.promise);
    const user = userEvent.setup();
    const view = render(
      <TalkTemplateShare
        open
        title="이전 문구"
        text="이전 고객 문구"
        disabledReason={null}
        onClose={vi.fn()}
      />,
    );
    await user.click(screen.getByRole("button", { name: "문구 복사" }));

    view.rerender(
      <TalkTemplateShare
        open
        title="새 문구"
        text="새 고객 문구"
        disabledReason={null}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "복사 중" })).toBeDisabled();

    await act(async () => {
      pendingCopy.resolve(true);
    });

    expect(screen.queryByText("문구를 복사했어요.")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "문구 복사" })).toBeEnabled();
  });

  it("ignores an older device-share failure without reopening the action early", async () => {
    const pendingShare = deferred<void>();
    setDeviceShare(vi.fn().mockReturnValue(pendingShare.promise));
    const user = userEvent.setup();
    const view = render(
      <TalkTemplateShare
        open
        title="이전 문구"
        text="이전 고객 문구"
        disabledReason={null}
        onClose={vi.fn()}
      />,
    );
    await user.click(screen.getByRole("button", { name: "기기에서 공유" }));

    view.rerender(
      <TalkTemplateShare
        open
        title="새 문구"
        text="새 고객 문구"
        disabledReason={null}
        onClose={vi.fn()}
      />,
    );
    expect(
      screen.getByRole("button", { name: "공유창 여는 중" }),
    ).toBeDisabled();

    await act(async () => {
      pendingShare.reject(new Error("old failure"));
    });

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "기기에서 공유" }),
    ).toBeEnabled();
  });

  it("disables both advertising share actions and explains the exact next action", () => {
    setDeviceShare(vi.fn());
    render(
      <TalkTemplateShare
        open
        title="광고 안내"
        text={finalText}
        disabledReason="계정 설정에서 내 전화번호를 저장하고, 이 화면에 수신거부 안내를 입력해 주세요."
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "문구 복사" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "기기에서 공유" }))
      .toBeDisabled();
    expect(screen.getByText(/계정 설정에서 내 전화번호를 저장하고/))
      .toBeInTheDocument();
  });

  it("traps focus, locks scrolling, closes on Escape, and restores opener focus", async () => {
    const user = userEvent.setup();
    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            공유 열기
          </button>
          <TalkTemplateShare
            open={open}
            title="첫 연락"
            text={finalText}
            disabledReason={null}
            onClose={() => setOpen(false)}
          />
        </>
      );
    }
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "공유 열기" });
    await user.click(opener);
    const dialog = screen.getByRole("dialog");
    const close = within(dialog).getByRole("button", { name: "닫기" });
    const copy = within(dialog).getByRole("button", { name: "문구 복사" });
    await waitFor(() => expect(close).toHaveFocus());
    expect(document.body.style.overflow).toBe("hidden");

    close.focus();
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(copy).toHaveFocus();
    copy.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(close).toHaveFocus();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(opener).toHaveFocus());
    expect(document.body.style.overflow).toBe("");
  });

  it("closes from the backdrop and returns focus", async () => {
    const onClose = vi.fn();
    render(
      <TalkTemplateShare
        open
        title="첫 연락"
        text={finalText}
        disabledReason={null}
        onClose={onClose}
      />,
    );

    fireEvent.mouseDown(screen.getByTestId("talk-share-backdrop"));

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "공유창 바깥 닫기" }))
      .not.toBeInTheDocument();
  });
});
