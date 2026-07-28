import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { BoardItemMenu } from "@/components/board-item-menu";

describe("게시판 항목 메뉴", () => {
  it("관리할 수 있는 항목에는 수정과 삭제만 보여 준다", async () => {
    const user = userEvent.setup();
    render(
      <BoardItemMenu
        canManage
        editHref="/boards/1/edit"
        onDelete={() => undefined}
        onReport={() => undefined}
      />,
    );

    await user.click(screen.getByRole("button", { name: "더보기" }));

    expect(screen.getByRole("menuitem", { name: "수정" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "삭제" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "신고" })).not.toBeInTheDocument();
  });

  it("관리할 수 없는 항목은 신고만 보이고 Escape 후 호출 버튼으로 포커스를 돌린다", async () => {
    const user = userEvent.setup();
    const onReport = vi.fn();
    render(
      <BoardItemMenu
        canManage={false}
        onDelete={() => undefined}
        onReport={onReport}
      />,
    );

    const trigger = screen.getByRole("button", { name: "더보기" });
    await user.click(trigger);
    expect(screen.getByRole("menuitem", { name: "신고" })).toBeInTheDocument();

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    expect(onReport).not.toHaveBeenCalled();
  });

  it("열린 메뉴에서 첫 항목부터 화살표·Home·End로 이동하고 Tab으로 닫는다", async () => {
    const user = userEvent.setup();
    render(
      <BoardItemMenu
        canManage
        editHref="/boards/1/edit"
        onDelete={() => undefined}
        onReport={() => undefined}
        menuLabel="댓글 메뉴"
      />,
    );

    const trigger = screen.getByRole("button", { name: "더보기" });
    await user.click(trigger);
    const menu = screen.getByRole("menu", { name: "댓글 메뉴" });
    const edit = screen.getByRole("menuitem", { name: "수정" });
    const remove = screen.getByRole("menuitem", { name: "삭제" });
    expect(edit).toHaveFocus();

    await user.keyboard("{ArrowDown}");
    expect(remove).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(edit).toHaveFocus();
    await user.keyboard("{End}");
    expect(remove).toHaveFocus();
    await user.keyboard("{Home}");
    expect(edit).toHaveFocus();
    expect(menu).toBeInTheDocument();

    await user.keyboard("{Tab}");
    expect(screen.queryByRole("menu", { name: "댓글 메뉴" })).not.toBeInTheDocument();
  });
});
