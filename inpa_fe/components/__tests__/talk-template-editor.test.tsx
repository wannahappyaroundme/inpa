import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { TalkTemplateEditor } from "@/components/talk-template-editor";
import type { PersonalTalkTemplatePayload } from "@/lib/api";

const initialValue: PersonalTalkTemplatePayload = {
  source_key: "closing-confirm",
  title: "고객 확인",
  body: "앞 문장 뒤 문장",
  category: "closing",
  channel: "message",
  sort_order: 7,
  is_active: true,
};

describe("TalkTemplateEditor", () => {
  it.each([
    ["create", "나만의 화법 추가"],
    ["edit", "나만의 화법 수정"],
    ["duplicate", "나만의 화법 복제"],
    ["copy-default", "기본 화법을 내 템플릿으로 저장"],
  ] as const)("renders the %s mode with the correct accessible title", (mode, title) => {
    render(
      <TalkTemplateEditor
        open
        mode={mode}
        initialValue={mode === "create" ? undefined : initialValue}
        saving={false}
        error={null}
        onSave={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByRole("dialog", { name: title })).toBeInTheDocument();
  });

  it("inserts a variable at the current textarea selection and restores the caret", async () => {
    const user = userEvent.setup();
    render(
      <TalkTemplateEditor
        open
        mode="edit"
        initialValue={initialValue}
        saving={false}
        error={null}
        onSave={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    const body = screen.getByLabelText("본문") as HTMLTextAreaElement;
    body.focus();
    body.setSelectionRange(2, 4);

    await user.click(screen.getByRole("button", { name: "고객명 변수 넣기" }));

    expect(body).toHaveValue("앞 {고객명} 뒤 문장");
    await waitFor(() => expect(body.selectionStart).toBe(7));
    expect(body.selectionEnd).toBe(7);
    expect(body).toHaveFocus();
  });

  it("shows remaining counts and blocks blank or over-limit values", async () => {
    const onSave = vi.fn();
    const user = userEvent.setup();
    render(
      <TalkTemplateEditor
        open
        mode="create"
        saving={false}
        error={null}
        onSave={onSave}
        onClose={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText("제목"), {
      target: { value: "가".repeat(101) },
    });
    await user.selectOptions(screen.getByLabelText("분류"), "__custom__");
    fireEvent.change(screen.getByLabelText("직접 만든 분류"), {
      target: { value: "나".repeat(41) },
    });
    fireEvent.change(screen.getByLabelText("본문"), {
      target: { value: "다".repeat(5001) },
    });
    expect(screen.getByText("제목 0자 남음")).toBeInTheDocument();
    expect(screen.getByText("분류 0자 남음")).toBeInTheDocument();
    expect(screen.getByText("본문 0자 남음")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "저장" }));

    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getAllByRole("alert")).toHaveLength(3);
    expect(screen.getByLabelText("제목")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("본문")).toHaveAttribute("aria-invalid", "true");
  });

  it("preserves source key and raw placeholders in the submitted payload", async () => {
    const onSave = vi.fn();
    const user = userEvent.setup();
    render(
      <TalkTemplateEditor
        open
        mode="copy-default"
        initialValue={initialValue}
        saving={false}
        error={null}
        onSave={onSave}
        onClose={vi.fn()}
      />,
    );

    await user.clear(screen.getByLabelText("제목"));
    await user.type(screen.getByLabelText("제목"), "  내 확인 문구  ");
    await user.click(screen.getByRole("button", { name: "저장" }));

    expect(onSave).toHaveBeenCalledWith({
      ...initialValue,
      title: "내 확인 문구",
    });
  });

  it("shows easy Korean category labels while storing stable keys and supports a clear custom flow", async () => {
    const onSave = vi.fn();
    const user = userEvent.setup();
    render(
      <TalkTemplateEditor
        open
        mode="copy-default"
        initialValue={initialValue}
        saving={false}
        error={null}
        onSave={onSave}
        onClose={vi.fn()}
      />,
    );
    const category = screen.getByRole("combobox", { name: "분류" });

    expect(category).toHaveDisplayValue("신청과 마무리");
    expect(screen.getByRole("option", { name: "신청과 마무리" }))
      .toHaveValue("closing");

    await user.selectOptions(category, "__custom__");
    const customCategory = screen.getByLabelText("직접 만든 분류");
    await user.type(customCategory, "갱신 안내");
    await user.click(screen.getByRole("button", { name: "저장" }));

    expect(onSave).toHaveBeenCalledWith({
      ...initialValue,
      category: "갱신 안내",
    });
  });

  it.each([
    [
      "두 변수가 모두 없을 때",
      "{고객명} 고객님, 안내를 확인할까요?",
      "광고 화법 본문에 {설계사연락처}, {수신거부안내} 변수를 다시 넣어 주세요.",
    ],
    [
      "수신거부 변수만 없을 때",
      "{고객명} 고객님, 문의: {설계사연락처}",
      "광고 화법 본문에 {수신거부안내} 변수를 다시 넣어 주세요.",
    ],
  ])("blocks saving an advertising-source personal template when %s", async (
    _case,
    body,
    guidance,
  ) => {
    const onSave = vi.fn();
    const user = userEvent.setup();
    render(
      <TalkTemplateEditor
        open
        mode="edit"
        initialValue={{
          ...initialValue,
          source_key: "as-event-sms",
          body,
        }}
        saving={false}
        error={null}
        onSave={onSave}
        onClose={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "저장" }));

    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(guidance);
  });

  it("disables all closing and saving actions while a save is pending and shows API errors", () => {
    render(
      <TalkTemplateEditor
        open
        mode="edit"
        initialValue={initialValue}
        saving
        error="저장이 중단됐어요. 입력한 내용은 그대로 두었어요."
        onSave={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "저장 중" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "취소" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "닫기" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "저장이 중단됐어요. 입력한 내용은 그대로 두었어요.",
    );
  });

  it("traps focus, closes with Escape, locks scrolling, and returns focus to the opener", async () => {
    const user = userEvent.setup();
    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            편집 열기
          </button>
          <TalkTemplateEditor
            open={open}
            mode="create"
            saving={false}
            error={null}
            onSave={vi.fn()}
            onClose={() => setOpen(false)}
          />
        </>
      );
    }
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "편집 열기" });
    await user.click(opener);
    const dialog = screen.getByRole("dialog");
    const title = within(dialog).getByLabelText("제목");
    await waitFor(() => expect(title).toHaveFocus());
    expect(document.body.style.overflow).toBe("hidden");

    const close = within(dialog).getByRole("button", { name: "닫기" });
    const save = within(dialog).getByRole("button", { name: "저장" });
    close.focus();
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(save).toHaveFocus();
    save.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(close).toHaveFocus();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(opener).toHaveFocus());
    expect(document.body.style.overflow).toBe("");
  });
});
