import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import IntroCardPage from "@/app/p/[refcode]/page";
import { ApiError } from "@/lib/api";

const api = vi.hoisted(() => ({
  getIntroductionCard: vi.fn(),
  submitIntroLead: vi.fn(),
}));

vi.mock("next/navigation", () => ({ useParams: () => ({ refcode: "intro-card-token" }) }));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...api,
}));
vi.mock("@/components/ui", () => ({
  Card: ({ children, className = "" }: { children: React.ReactNode; className?: string }) => <div className={className}>{children}</div>,
}));

const card = {
  planner: {
    name: "홍길동",
    affiliation: "인파금융",
    title: "팀장",
    intro_text: "편하게 상담해 보세요.",
  },
  self_diagnosis_url: "/d/intro-card-token",
};

async function fillRequiredFields(phone: string) {
  const user = userEvent.setup();
  await user.type(screen.getByPlaceholderText("이름"), "김상담");
  await user.type(screen.getByLabelText("연락받을 휴대폰 번호"), phone);
  await user.click(screen.getByRole("checkbox"));
  return user;
}

describe("introduction card consultation request", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getIntroductionCard.mockReset();
    api.submitIntroLead.mockReset();
    api.getIntroductionCard.mockResolvedValue(card);
    api.submitIntroLead.mockResolvedValue({ lead_created: true });
  });

  it("shows a tel-friendly required mobile-phone field and blocks an invalid number before the API call", async () => {
    render(<IntroCardPage />);
    const phone = await screen.findByLabelText("연락받을 휴대폰 번호");
    expect(phone).toHaveAttribute("inputmode", "tel");

    const user = await fillRequiredFields("010-1234-56");
    await user.click(screen.getByRole("button", { name: "상담 신청" }));

    expect(await screen.findByText("올바른 휴대폰 번호를 입력해 주세요.")).toBeInTheDocument();
    expect(api.submitIntroLead).not.toHaveBeenCalled();
    expect(screen.queryByText("상담 내용을 확인한 뒤 연락드려요")).toBeNull();
  });

  it("submits a valid mobile phone and confirms the next contact action", async () => {
    render(<IntroCardPage />);
    await screen.findByLabelText("연락받을 휴대폰 번호");
    const user = await fillRequiredFields("010-1234-5678");
    await user.click(screen.getByRole("button", { name: "상담 신청" }));

    await waitFor(() => expect(api.submitIntroLead).toHaveBeenCalledWith("intro-card-token", {
      name: "김상담",
      phone: "010-1234-5678",
      agreed: true,
    }));
    expect(await screen.findByText("상담 내용을 확인한 뒤 연락드려요")).toBeInTheDocument();
  });

  it("keeps a server phone error near the field without entering the success state", async () => {
    api.submitIntroLead.mockRejectedValue(new ApiError(400, "INVALID_PHONE", "올바른 휴대폰 번호를 입력해 주세요."));
    render(<IntroCardPage />);
    await screen.findByLabelText("연락받을 휴대폰 번호");
    const user = await fillRequiredFields("010-1234-5678");
    await user.click(screen.getByRole("button", { name: "상담 신청" }));

    expect(await screen.findByText("올바른 휴대폰 번호를 입력해 주세요.")).toBeInTheDocument();
    expect(screen.queryByText("상담 내용을 확인한 뒤 연락드려요")).toBeNull();
  });

  it("keeps a 404 as an invalid-link state without offering retry", async () => {
    api.getIntroductionCard.mockRejectedValueOnce(new ApiError(404, "NOT_FOUND", "missing"));

    render(<IntroCardPage />);

    expect(await screen.findByText("유효하지 않은 링크예요.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "다시 불러오기" })).toBeNull();
  });

  it.each([
    ["429", new ApiError(429, "THROTTLED", "busy")],
    ["500", new ApiError(500, "SERVER_ERROR", "down")],
    ["network", new TypeError("network")],
  ])("offers one working retry after a %s load error", async (_label, loadError) => {
    api.getIntroductionCard.mockRejectedValueOnce(loadError).mockResolvedValueOnce(card);

    render(<IntroCardPage />);

    expect(await screen.findByText("잠시 연결이 원활하지 않아요")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "다시 불러오기" })).toHaveLength(1);

    await userEvent.setup().click(screen.getByRole("button", { name: "다시 불러오기" }));

    expect(await screen.findByText("홍길동")).toBeInTheDocument();
    expect(api.getIntroductionCard).toHaveBeenCalledTimes(2);
  });
});
