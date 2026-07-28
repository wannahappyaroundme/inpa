import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  adminListBenefitReviews: vi.fn(),
  adminDecideBenefitReview: vi.fn(),
}));

vi.mock("@/lib/adminApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adminApi")>("@/lib/adminApi");
  return { ...actual, ...api };
});
vi.mock("@/lib/useAdminGuard", () => ({
  useAdminGuard: () => true,
}));

import AdminBenefitReviewsPage from "@/app/admin/benefit-reviews/page";
import { ApiError } from "@/lib/api";

const pendingReview = {
  id: 4,
  phone_masked: "010-****-5678",
  contact_email: "planner@example.com",
  reason: "기존에 사용한 번호일 수 있어요",
  status: "pending" as const,
  decision_reason: "",
  created_at: "2026-07-28T00:00:00Z",
  decided_at: null,
  consumed_at: null,
};

describe("관리자 무료 혜택 확인 요청", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    api.adminListBenefitReviews.mockResolvedValue({ results: [pendingReview] });
  });

  it("상태별 목록에서 마스킹된 번호와 필요한 확인 정보만 보여준다", async () => {
    const user = userEvent.setup();
    render(<AdminBenefitReviewsPage />);

    expect(await screen.findByText("010-****-5678")).toBeInTheDocument();
    expect(screen.getByText("planner@example.com")).toBeInTheDocument();
    expect(screen.queryByText(/identity_hmac|provider|otp/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "승인" }));
    expect(api.adminListBenefitReviews).toHaveBeenLastCalledWith("approved");
  });

  it("관리자 응답의 원번호·식별값·인증값·공급자·쿠폰 내부값은 렌더하지 않는다", async () => {
    const forbidden = {
      identity_hmac: "IDENTITY-HMAC-SENTINEL",
      raw_phone: "010-9999-0000",
      otp_hash: "OTP-HASH-SENTINEL",
      otp_code: "991122",
      provider_reference: "PROVIDER-REF-SENTINEL",
      coupon_snapshot: "COUPON-SNAPSHOT-SENTINEL",
    };
    api.adminListBenefitReviews.mockResolvedValueOnce({ results: [{ ...pendingReview, ...forbidden }] });
    render(<AdminBenefitReviewsPage />);

    expect(await screen.findByText(pendingReview.phone_masked)).toBeInTheDocument();
    for (const value of Object.values(forbidden)) {
      expect(document.body.textContent).not.toContain(value);
    }
  });

  it("결정 사유를 확인 대화상자에서 받고, 서버 확인 뒤 목록을 새로 읽는다", async () => {
    const user = userEvent.setup();
    api.adminDecideBenefitReview.mockResolvedValue({
      ...pendingReview,
      status: "approved",
      decision_reason: "번호 사용 이력을 확인했어요",
      decided_at: "2026-07-28T01:00:00Z",
    });
    render(<AdminBenefitReviewsPage />);

    await user.click(await screen.findByRole("button", { name: "승인" }));
    expect(screen.getByRole("dialog", { name: "확인 요청 승인" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("처리 사유"), "번호 사용 이력을 확인했어요");
    expect(screen.getByLabelText("처리 사유")).toHaveValue("번호 사용 이력을 확인했어요");
    await user.click(screen.getByRole("button", { name: "승인 확정" }));

    expect(api.adminDecideBenefitReview).toHaveBeenCalledWith(4, {
      decision: "approved",
      reason: "번호 사용 이력을 확인했어요",
    });
    expect(api.adminListBenefitReviews).toHaveBeenCalledTimes(2);
  });

  it("다른 관리자가 먼저 처리한 충돌은 최신 목록을 읽고 안내한다", async () => {
    const user = userEvent.setup();
    api.adminDecideBenefitReview.mockRejectedValue(
      new ApiError(409, "benefit_review_already_decided", "이미 처리한 확인 요청이에요."),
    );
    render(<AdminBenefitReviewsPage />);

    await user.click(await screen.findByRole("button", { name: "반려" }));
    await user.type(screen.getByLabelText("처리 사유"), "이미 다른 경로에서 처리했어요");
    expect(screen.getByLabelText("처리 사유")).toHaveValue("이미 다른 경로에서 처리했어요");
    await user.click(screen.getByRole("button", { name: "반려 확정" }));

    expect(await screen.findByText("이미 다른 관리자가 처리했어요. 최신 상태를 불러왔어요.")).toBeInTheDocument();
    expect(api.adminListBenefitReviews).toHaveBeenCalledTimes(2);
    expect(screen.getByLabelText("처리 사유")).toHaveValue("이미 다른 경로에서 처리했어요");
  });

  it("409 뒤에는 재확정만 막고 Escape로 닫아 원래 버튼에 초점을 돌린다", async () => {
    const user = userEvent.setup();
    api.adminDecideBenefitReview.mockRejectedValue(new ApiError(409, "benefit_review_already_decided", "이미 처리한 확인 요청이에요."));
    render(<AdminBenefitReviewsPage />);
    const trigger = await screen.findByRole("button", { name: "승인" });
    await user.click(trigger);
    await user.type(screen.getByLabelText("처리 사유"), "이미 처리됐어요");
    await user.click(screen.getByRole("button", { name: "승인 확정" }));

    expect(await screen.findByText("이미 다른 관리자가 처리한 요청이에요. 최신 목록을 확인해 주세요.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "승인 확정" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "승인 확정" }));
    expect(api.adminDecideBenefitReview).toHaveBeenCalledTimes(1);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("409 상태의 대화상자는 Tab을 내부에 가두고 취소와 배경 클릭으로 닫힌다", async () => {
    const user = userEvent.setup();
    api.adminDecideBenefitReview.mockRejectedValue(new ApiError(409, "benefit_review_already_decided", "이미 처리한 확인 요청이에요."));
    render(<AdminBenefitReviewsPage />);
    const trigger = await screen.findByRole("button", { name: "승인" });
    await user.click(trigger);
    const reason = screen.getByLabelText("처리 사유");
    await user.type(reason, "충돌 확인");
    await user.click(screen.getByRole("button", { name: "승인 확정" }));
    await screen.findByText("이미 다른 관리자가 처리한 요청이에요. 최신 목록을 확인해 주세요.");

    reason.focus();
    await user.keyboard("{Shift>}{Tab}{/Shift}");
    expect(screen.getByRole("button", { name: "그대로 둘게요" })).toHaveFocus();
    await user.keyboard("{Tab}");
    expect(reason).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "그대로 둘게요" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();

    await user.click(trigger);
    const backdrop = screen.getByRole("dialog").parentElement as HTMLElement;
    fireEvent.mouseDown(backdrop);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("관리자 결정 사유는 요청 본문 외의 콘솔·저장소·URL·분석 경로로 보내지 않는다", async () => {
    const decisionSecret = "ADMIN-DECISION-SENTINEL";
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const consoleWarn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const consoleLog = vi.spyOn(console, "log").mockImplementation(() => undefined);
    const localWrite = vi.spyOn(Storage.prototype, "setItem");
    const sessionWrite = vi.spyOn(window.sessionStorage.__proto__, "setItem");
    const pushState = vi.spyOn(window.history, "pushState");
    const replaceState = vi.spyOn(window.history, "replaceState");
    const analyticsTrack = vi.fn();
    Object.assign(window, { analytics: { track: analyticsTrack } });
    api.adminDecideBenefitReview.mockResolvedValue({ ...pendingReview, status: "approved", decision_reason: decisionSecret });
    const user = userEvent.setup();

    try {
      render(<AdminBenefitReviewsPage />);
      await user.click(await screen.findByRole("button", { name: "승인" }));
      await user.type(screen.getByLabelText("처리 사유"), decisionSecret);
      await user.click(screen.getByRole("button", { name: "승인 확정" }));
      expect(api.adminDecideBenefitReview).toHaveBeenCalledWith(4, { decision: "approved", reason: decisionSecret });
      const sentinels = JSON.stringify([consoleError.mock.calls, consoleWarn.mock.calls, consoleLog.mock.calls, localWrite.mock.calls, sessionWrite.mock.calls, pushState.mock.calls, replaceState.mock.calls, analyticsTrack.mock.calls]);
      expect(sentinels).not.toContain(decisionSecret);
    } finally {
      delete (window as Window & { analytics?: unknown }).analytics;
    }
  });

  it("빈 처리 사유는 대화상자 안에서 안내하고 입력칸으로 초점을 돌린다", async () => {
    const user = userEvent.setup();
    render(<AdminBenefitReviewsPage />);
    await user.click(await screen.findByRole("button", { name: "승인" }));
    await user.click(screen.getByRole("button", { name: "승인 확정" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("처리 사유를 입력해 주세요.");
    expect(screen.getByLabelText("처리 사유")).toHaveFocus();
    expect(api.adminDecideBenefitReview).not.toHaveBeenCalled();
  });

  it("늦은 이전 필터 응답은 현재 탭 목록을 덮어쓰지 않는다", async () => {
    const user = userEvent.setup();
    let resolvePending: ((value: { results: Array<typeof pendingReview> }) => void) | undefined;
    const latePending = {
      ...pendingReview,
      id: 7,
      phone_masked: "010-****-1111",
      contact_email: "late-pending@example.com",
    };
    const currentApproved = {
      ...pendingReview,
      id: 9,
      phone_masked: "010-****-9999",
      contact_email: "current-approved@example.com",
      status: "approved" as const,
    };
    api.adminListBenefitReviews
      .mockImplementationOnce(() => new Promise((resolve) => { resolvePending = resolve; }))
      .mockResolvedValueOnce({ results: [currentApproved] });
    render(<AdminBenefitReviewsPage />);
    await user.click(screen.getByRole("tab", { name: "승인" }));
    expect(await screen.findByText("current-approved@example.com")).toBeInTheDocument();
    await act(async () => resolvePending?.({ results: [latePending] }));

    expect(screen.getByRole("tab", { name: "승인" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("010-****-9999")).toBeInTheDocument();
    expect(screen.queryByText("late-pending@example.com")).not.toBeInTheDocument();
  });
});
