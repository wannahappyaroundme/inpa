import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StatusPanel } from "@/components/recruiting/status-panel";
import { ApiError } from "@/lib/api";

const api = vi.hoisted(() => ({
  getRecruitingSummary: vi.fn(),
  listRecruitingCandidates: vi.fn(),
  getRecruitingPage: vi.fn(),
  getRecruitingCampaign: vi.fn(),
  recordRecruitingCampaignCopied: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...api,
}));

const summary = {
  stage_counts: {
    new: 0,
    contact: 0,
    conversation: 0,
    preparing: 0,
    team_join: 0,
    recontact: 0,
    ended: 0,
  },
  due_today: 0,
  overdue: 0,
  joined_this_month: 0,
  settlement_due: 0,
};

const emptyCandidates = {
  count: 0,
  next: null,
  previous: null,
  results: [],
};

const recruitingPage = {
  planner: {
    display_name: "김인파",
    affiliation: "인파금융",
    title: "팀장",
    profile_image: null,
  },
  headline_template_id: null,
  headline: null,
  templates: [],
  activity_region: "서울",
  is_published: false,
};

const campaign = {
  id: 1,
  name: "개인 소개",
  channel: "relationship" as const,
  is_active: false,
  public_path: "/p/test",
  public_url: "https://www.inpa.kr/p/test",
  visits: 0,
  applications: 0,
  joins: 0,
  created_at: "2026-07-30T00:00:00+09:00",
};

describe("시연 계정 영입 현황", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getRecruitingSummary.mockResolvedValue(summary);
    api.listRecruitingCandidates.mockResolvedValue(emptyCandidates);
    api.getRecruitingPage.mockResolvedValue(recruitingPage);
    api.getRecruitingCampaign.mockResolvedValue(campaign);
  });

  it("외부 공개 기능 제한은 오류 대신 읽기 전용 안내와 영입 현황으로 보여준다", async () => {
    const restriction = new ApiError(
      403,
      "SHOWCASE_ACTION_RESTRICTED",
      "등록된 자료를 활용해 주요 기능을 확인할 수 있어요.",
    );
    api.getRecruitingPage.mockRejectedValue(restriction);
    api.getRecruitingCampaign.mockRejectedValue(restriction);

    render(<StatusPanel />);

    expect(
      await screen.findByText("시연 계정에서는 등록된 자료로 영입 흐름을 확인할 수 있어요."),
    ).toBeInTheDocument();
    expect(screen.getByText("오늘 확인")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "다시 불러오기" })).not.toBeInTheDocument();
    expect(screen.queryByText("잠시 후 다시 확인하면 이어갈 수 있어요.")).not.toBeInTheDocument();
  });

  it("일반 서버 오류는 기존 재시도 안내를 유지한다", async () => {
    api.getRecruitingPage.mockRejectedValue(
      new ApiError(500, "SERVER_ERROR", "서버 오류"),
    );

    render(<StatusPanel />);

    expect(
      await screen.findByText("잠시 후 다시 확인하면 이어갈 수 있어요."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "다시 불러오기" })).toBeInTheDocument();
    expect(
      screen.queryByText("시연 계정에서는 등록된 자료로 영입 흐름을 확인할 수 있어요."),
    ).not.toBeInTheDocument();
  });
});
