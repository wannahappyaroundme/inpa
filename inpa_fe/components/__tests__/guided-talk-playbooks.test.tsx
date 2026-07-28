import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GuidedTalkPlaybooks } from "@/components/guided-talk-playbooks";
import { copyText } from "@/lib/clipboard";

const analytics = vi.hoisted(() => ({ track: vi.fn() }));

vi.mock("@/lib/clipboard", () => ({ copyText: vi.fn() }));
vi.mock("@vercel/analytics", () => ({ track: analytics.track }));

const mockedCopyText = vi.mocked(copyText);
const variables = {
  customer: "김인파",
  planner: "황예진",
  affiliation: "인파지점",
  title: "팀장",
  referrer: "이인파",
};

beforeEach(() => {
  mockedCopyText.mockReset();
  mockedCopyText.mockResolvedValue(true);
  analytics.track.mockReset();
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

describe("GuidedTalkPlaybooks", () => {
  it("selects a scene and keeps exactly one current step", async () => {
    const user = userEvent.setup();
    render(
      <GuidedTalkPlaybooks
        variables={variables}
        customerId={17}
        onOpenQuick={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("button", { name: /소개받은 고객 첫 통화/ }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("현재 1/6")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /신분과 연락 목적 밝히기/ }),
    ).toHaveAttribute("aria-current", "step");

    await user.click(screen.getByRole("button", { name: "다음 단계" }));
    expect(screen.getByText("현재 2/6")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /소개 경위 설명하기/ }),
    ).toHaveAttribute("aria-current", "step");

    await user.click(
      screen.getByRole("button", { name: /첫 대면 보장 점검/ }),
    );
    expect(screen.getByText("현재 1/8")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /신분과 상담 목적 다시 밝히기/ }),
    ).toHaveAttribute("aria-current", "step");
  });

  it("tracks each playbook transition exactly once when the parent echoes the selection", async () => {
    const user = userEvent.setup();
    const onPlaybookChange = vi.fn();
    const { rerender } = render(
      <GuidedTalkPlaybooks
        variables={variables}
        customerId={17}
        onOpenQuick={vi.fn()}
        onPlaybookChange={onPlaybookChange}
        initialPlaybookKey="referred-customer-first-call"
      />,
    );

    await user.click(
      screen.getByRole("button", { name: /첫 대면 보장 점검/ }),
    );
    rerender(
      <GuidedTalkPlaybooks
        variables={variables}
        customerId={17}
        onOpenQuick={vi.fn()}
        onPlaybookChange={onPlaybookChange}
        initialPlaybookKey="first-coverage-review"
      />,
    );

    expect(onPlaybookChange).toHaveBeenCalledOnce();
    expect(
      analytics.track.mock.calls.filter(
        ([eventName, properties]) =>
          eventName === "talk_playbook_open" &&
          properties.playbook_key === "first-coverage-review",
      ),
    ).toHaveLength(1);
    expect(
      analytics.track.mock.calls.filter(
        ([eventName, properties]) =>
          eventName === "talk_stage_view" &&
          properties.playbook_key === "first-coverage-review" &&
          properties.step_key === "meeting-disclosure",
      ),
    ).toHaveLength(1);
  });

  it("supports free step jumping and previous navigation", async () => {
    const user = userEvent.setup();
    render(
      <GuidedTalkPlaybooks
        variables={variables}
        customerId={null}
        onOpenQuick={vi.fn()}
      />,
    );

    await user.click(
      screen.getByRole("button", { name: /6단계 약속 확인하고 마치기/ }),
    );
    expect(screen.getByText("현재 6/6")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "다음 단계" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "이전 단계" }));
    expect(screen.getByText("현재 5/6")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "상담 방식과 일정 정하기" }),
    ).toHaveFocus();
  });

  it("keeps the mobile reading order as card, objections, then navigation", () => {
    render(
      <GuidedTalkPlaybooks
        variables={variables}
        customerId={null}
        onOpenQuick={vi.fn()}
      />,
    );

    const article = screen
      .getByRole("heading", { name: "신분과 연락 목적 밝히기" })
      .closest("article");
    const objections = screen.getByRole("complementary", {
      name: "고객 반응에 맞춰 말하기",
    });
    const previous = screen.getByRole("button", { name: "이전 단계" });
    expect(article).not.toBeNull();
    expect(
      article!.compareDocumentPosition(objections) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      objections.compareDocumentPosition(previous) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("opens an objection branch, moves focus, and returns focus when closed", async () => {
    const user = userEvent.setup();
    render(
      <GuidedTalkPlaybooks
        variables={variables}
        customerId={null}
        onOpenQuick={vi.fn()}
      />,
    );
    const busy = screen.getByRole("button", {
      name: "지금 시간이 없어요",
    });

    await user.click(busy);
    expect(busy).toHaveAttribute("aria-expanded", "true");
    const branch = screen.getByRole("region", {
      name: "지금 시간이 없어요 대응",
    });
    expect(within(branch).getByText("한 번 더 거절하면")).toBeInTheDocument();
    await waitFor(() =>
      expect(
        within(branch).getByRole("heading", {
          name: "지금 시간이 없어요 대응",
        }),
      ).toHaveFocus(),
    );

    await user.click(
      within(branch).getByRole("button", { name: "대응 닫기" }),
    );
    expect(busy).toHaveAttribute("aria-expanded", "false");
    expect(busy).toHaveFocus();
  });

  it("treats a contact opt-out as an immediate close, not another proposal", async () => {
    const user = userEvent.setup();
    render(
      <GuidedTalkPlaybooks
        variables={variables}
        customerId={null}
        onOpenQuick={vi.fn()}
      />,
    );

    await user.click(
      screen.getByRole("button", { name: "다음 연락을 원치 않아요" }),
    );
    const branch = screen.getByRole("region", {
      name: "다음 연락을 원치 않아요 대응",
    });
    expect(within(branch).getByText("연락을 마칠 때")).toBeInTheDocument();
    expect(
      within(branch).queryByText("한 번 더 거절하면"),
    ).not.toBeInTheDocument();
  });

  it("copies only the rendered spoken text", async () => {
    const user = userEvent.setup();
    render(
      <GuidedTalkPlaybooks
        variables={variables}
        customerId={null}
        onOpenQuick={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "말할 문장 복사" }));

    expect(mockedCopyText).toHaveBeenCalledTimes(1);
    const copied = mockedCopyText.mock.calls[0][0];
    expect(copied).toContain("김인파 고객님");
    expect(copied).toContain("인파지점 팀장 황예진");
    expect(copied).not.toContain("누가 왜 연락했는지");
    expect(copied).not.toContain("통화가 어렵다면");
    expect(copied).not.toContain("성명·소속");
    expect(screen.getByRole("status")).toHaveTextContent(
      "말할 문장을 복사했어요.",
    );
  });

  it("does not show an older copy result after moving to another step", async () => {
    const user = userEvent.setup();
    const copyRequest = deferred<boolean>();
    mockedCopyText.mockReturnValue(copyRequest.promise);
    render(
      <GuidedTalkPlaybooks
        variables={variables}
        customerId={null}
        onOpenQuick={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "말할 문장 복사" }));
    await user.click(screen.getByRole("button", { name: "다음 단계" }));
    copyRequest.resolve(true);

    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(""),
    );
  });

  it("requires the planner name and affiliation before copying spoken text", () => {
    render(
      <GuidedTalkPlaybooks
        variables={{ customer: "김인파" }}
        customerId={null}
        onOpenQuick={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("button", { name: "말할 문장 복사" }),
    ).toBeDisabled();
    expect(
      screen.getByText(/내 이름과 소속을 채우면/),
    ).toBeInTheDocument();
  });

  it("opens quick copy callbacks and customer-safe next links at the final step", async () => {
    const user = userEvent.setup();
    const onOpenQuick = vi.fn();
    render(
      <GuidedTalkPlaybooks
        variables={variables}
        customerId={17}
        onOpenQuick={onOpenQuick}
      />,
    );
    await user.click(
      screen.getByRole("button", { name: /6단계 약속 확인하고 마치기/ }),
    );

    expect(screen.getByRole("link", { name: "일정 열기" })).toHaveAttribute(
      "href",
      "/schedule",
    );
    await user.click(
      screen.getByRole("button", { name: "예약 안내 문구 열기" }),
    );
    expect(onOpenQuick).toHaveBeenCalledWith("appointment");
    expect(
      screen.getByRole("link", { name: "연락 종료" }),
    ).toHaveAttribute(
      "href",
      "/customer/17",
    );

    await user.click(
      screen.getByRole("button", { name: /첫 대면 보장 점검/ }),
    );
    await user.click(
      screen.getByRole("button", {
        name: /8단계 확인한 내용과 다음 일정 정하기/,
      }),
    );
    expect(
      screen.getByRole("link", { name: "고객 분석 열기" }),
    ).toHaveAttribute("href", "/customer/17?tab=analysis");
  });

  it("tracks enums only and never sends customer, referrer, or spoken text", async () => {
    const user = userEvent.setup();
    render(
      <GuidedTalkPlaybooks
        variables={variables}
        customerId={17}
        onOpenQuick={vi.fn()}
      />,
    );
    await user.click(screen.getByRole("button", { name: "다음 단계" }));
    await user.click(
      screen.getByRole("button", { name: "연락 경로가 궁금해요" }),
    );

    const serialized = JSON.stringify(analytics.track.mock.calls);
    expect(serialized).toContain("referred-customer-first-call");
    expect(serialized).toContain("source-and-privacy");
    expect(serialized).not.toContain("김인파");
    expect(serialized).not.toContain("이인파");
    expect(serialized).not.toContain("황예진");
    expect(serialized).not.toContain("17");
    expect(serialized).not.toContain("가입하신 보험");
  });
});
