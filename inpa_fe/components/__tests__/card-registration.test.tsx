import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  preflightRecurringCoupon: vi.fn(),
  requestFreeTrialPhoneVerification: vi.fn(),
  verifyFreeTrialPhone: vi.fn(),
  submitManualBenefitReview: vi.fn(),
  getCurrentManualBenefitReview: vi.fn(),
  startCardRegistration: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, ...api };
});

import { CardRegistration } from "@/components/billing/card-registration";
import { ApiError } from "@/lib/api";

const preview = {
  claim_id: "claim-1",
  claim_expires_at: "2026-07-28T01:00:00Z",
  plan_code: "plus",
  plan_display_name: "Plus",
  duration_months: 1 as const,
  redeem_by: "2026-08-01T00:00:00Z",
  access_through: "2026-08-28",
  next_charge_date: "2026-08-29",
  amount_krw: 21890,
  initial_consent_version: "v1",
};

describe("무료 쿠폰 카드 등록", () => {
  beforeEach(() => vi.resetAllMocks());

  it("휴대전화 확인 후 같은 쿠폰을 한 번만 다시 확인해 기존 미리보기로 이어간다", async () => {
    const user = userEvent.setup();
    api.preflightRecurringCoupon
      .mockRejectedValueOnce(new ApiError(409, "phone_verification_required", "휴대전화 확인이 필요해요."))
      .mockResolvedValueOnce(preview);
    api.requestFreeTrialPhoneVerification.mockResolvedValue({
      challenge_id: "challenge-1",
      expires_in_seconds: 300,
      phone_masked: "010-****-5678",
    });
    api.verifyFreeTrialPhone.mockResolvedValue({
      verified: true,
      phone_masked: "010-****-5678",
    });

    render(<CardRegistration />);
    const couponInput = screen.getByLabelText("쿠폰 코드");
    await user.type(couponInput, "inpa-free");
    await user.click(screen.getByRole("button", { name: "쿠폰 확인" }));
    expect(await screen.findByLabelText("휴대전화 번호")).toBeInTheDocument();
    expect(couponInput).toHaveValue("INPA-FREE");

    await user.type(screen.getByLabelText("휴대전화 번호"), "010-1234-5678");
    await user.click(screen.getByRole("button", { name: "인증번호 보내기" }));
    await user.type(await screen.findByLabelText("인증번호"), "123456");
    await user.click(screen.getByRole("button", { name: "인증 확인" }));

    expect(await screen.findByText("Plus 1개월 무료")).toBeInTheDocument();
    expect(api.preflightRecurringCoupon).toHaveBeenCalledTimes(2);
    expect(api.preflightRecurringCoupon).toHaveBeenNthCalledWith(2, "INPA-FREE");
  });

  it("중복 번호 확인이 필요하면 쿠폰을 지우지 않고 수동 확인 양식으로 바로 안내한다", async () => {
    const user = userEvent.setup();
    api.preflightRecurringCoupon.mockRejectedValueOnce(
      new ApiError(409, "manual_benefit_review_required", "확인 요청을 남겨 주세요."),
    );

    render(<CardRegistration />);
    const couponInput = screen.getByLabelText("쿠폰 코드");
    await user.type(couponInput, "inpa-free");
    await user.click(screen.getByRole("button", { name: "쿠폰 확인" }));

    expect(await screen.findByText("확인이 필요한 번호예요. 이메일과 간단한 사유를 남기면 확인 후 안내해 드릴게요.")).toBeInTheDocument();
    expect(couponInput).toHaveValue("INPA-FREE");
  });

  it("접수 상태에서 다시 확인하면 새 요청 없이 서버의 승인 결과로 이어간다", async () => {
    const user = userEvent.setup();
    api.preflightRecurringCoupon
      .mockRejectedValueOnce(
        new ApiError(409, "manual_benefit_review_required", "확인 요청을 남겨 주세요."),
      )
      .mockResolvedValueOnce(preview);
    api.submitManualBenefitReview.mockResolvedValue({
      id: 4,
      phone_masked: "010-****-5678",
      contact_email: "planner@example.com",
      reason: "기존에 사용한 번호일 수 있어요",
      status: "pending",
      decision_reason: "",
      created_at: "2026-07-28T00:00:00Z",
      decided_at: null,
      consumed_at: null,
      created: true,
    });

    render(<CardRegistration />);
    const couponInput = screen.getByLabelText("쿠폰 코드");
    await user.type(couponInput, "inpa-free");
    await user.click(screen.getByRole("button", { name: "쿠폰 확인" }));
    await user.type(await screen.findByLabelText("연락 이메일"), "planner@example.com");
    await user.type(screen.getByLabelText("확인 사유"), "기존에 사용한 번호일 수 있어요");
    await user.click(screen.getByRole("button", { name: "확인 요청 보내기" }));
    expect(await screen.findByText("확인 요청을 접수했어요. 처리 결과는 이 화면에서 다시 확인할 수 있어요.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "처리 상태 다시 확인" }));

    expect(await screen.findByText("Plus 1개월 무료")).toBeInTheDocument();
    expect(api.submitManualBenefitReview).toHaveBeenCalledTimes(1);
    expect(api.preflightRecurringCoupon).toHaveBeenCalledTimes(2);
    expect(api.preflightRecurringCoupon).toHaveBeenLastCalledWith("INPA-FREE");
  });

  it("상위 쿠폰 오류를 바로 읽어 준다", async () => {
    const user = userEvent.setup();
    api.preflightRecurringCoupon.mockRejectedValueOnce(
      new ApiError(503, "billing_setup_required", "결제 설정을 확인하고 있어요."),
    );

    render(<CardRegistration />);
    await user.type(screen.getByLabelText("쿠폰 코드"), "inpa-free");
    await user.click(screen.getByRole("button", { name: "쿠폰 확인" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("결제 설정을 확인하고 있어요.");
  });

  it("접수 상태에서 다시 확인하면 새 요청 없이 서버의 반려 상태를 보여준다", async () => {
    const user = userEvent.setup();
    api.preflightRecurringCoupon.mockRejectedValue(
      new ApiError(409, "manual_benefit_review_required", "확인 요청을 남겨 주세요."),
    );
    api.getCurrentManualBenefitReview
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce({
        id: 4,
        phone_masked: "010-****-5678",
        contact_email: "planner@example.com",
        reason: "기존에 사용한 번호일 수 있어요",
        status: "rejected",
        decision_reason: "확인 자료를 다시 남겨 주세요.",
        created_at: "2026-07-28T00:00:00Z",
        decided_at: "2026-07-28T01:00:00Z",
        consumed_at: null,
      });
    api.submitManualBenefitReview.mockResolvedValue({
      id: 4,
      phone_masked: "010-****-5678",
      contact_email: "planner@example.com",
      reason: "기존에 사용한 번호일 수 있어요",
      status: "pending",
      decision_reason: "",
      created_at: "2026-07-28T00:00:00Z",
      decided_at: null,
      consumed_at: null,
      created: true,
    });

    render(<CardRegistration />);
    await user.type(screen.getByLabelText("쿠폰 코드"), "inpa-free");
    await user.click(screen.getByRole("button", { name: "쿠폰 확인" }));
    await user.type(await screen.findByLabelText("연락 이메일"), "planner@example.com");
    await user.type(screen.getByLabelText("확인 사유"), "기존에 사용한 번호일 수 있어요");
    await user.click(screen.getByRole("button", { name: "확인 요청 보내기" }));
    expect(await screen.findByText("현재 상태: 접수")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "처리 상태 다시 확인" }));

    expect(await screen.findByText("현재 상태: 반려")).toBeInTheDocument();
    expect(api.getCurrentManualBenefitReview).toHaveBeenCalledTimes(2);
    expect(api.submitManualBenefitReview).toHaveBeenCalledTimes(1);
  });

  it("접수 상태에서 다시 확인하면 서버의 지급 완료 상태를 보여준다", async () => {
    const user = userEvent.setup();
    api.preflightRecurringCoupon.mockRejectedValue(
      new ApiError(409, "manual_benefit_review_required", "확인 요청을 남겨 주세요."),
    );
    api.getCurrentManualBenefitReview
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce({
        id: 4,
        phone_masked: "010-****-5678",
        contact_email: "planner@example.com",
        reason: "기존에 사용한 번호일 수 있어요",
        status: "consumed",
        decision_reason: "확인했어요.",
        created_at: "2026-07-28T00:00:00Z",
        decided_at: "2026-07-28T01:00:00Z",
        consumed_at: "2026-07-28T02:00:00Z",
      });
    api.submitManualBenefitReview.mockResolvedValue({
      id: 4,
      phone_masked: "010-****-5678",
      contact_email: "planner@example.com",
      reason: "기존에 사용한 번호일 수 있어요",
      status: "pending",
      decision_reason: "",
      created_at: "2026-07-28T00:00:00Z",
      decided_at: null,
      consumed_at: null,
      created: true,
    });

    render(<CardRegistration />);
    await user.type(screen.getByLabelText("쿠폰 코드"), "inpa-free");
    await user.click(screen.getByRole("button", { name: "쿠폰 확인" }));
    await user.type(await screen.findByLabelText("연락 이메일"), "planner@example.com");
    await user.type(screen.getByLabelText("확인 사유"), "기존에 사용한 번호일 수 있어요");
    await user.click(screen.getByRole("button", { name: "확인 요청 보내기" }));
    await user.click(await screen.findByRole("button", { name: "처리 상태 다시 확인" }));

    expect(await screen.findByText("현재 상태: 지급 완료")).toBeInTheDocument();
    expect(api.submitManualBenefitReview).toHaveBeenCalledTimes(1);
  });

  it("인증 뒤 다시 확인한 쿠폰이 중복 번호 확인을 요구하면 수동 확인으로 이어간다", async () => {
    const user = userEvent.setup();
    api.preflightRecurringCoupon
      .mockRejectedValueOnce(new ApiError(409, "phone_verification_required", "휴대전화 확인이 필요해요."))
      .mockRejectedValueOnce(new ApiError(409, "manual_benefit_review_required", "확인 요청을 남겨 주세요."));
    api.requestFreeTrialPhoneVerification.mockResolvedValue({
      challenge_id: "challenge-1",
      expires_in_seconds: 300,
      phone_masked: "010-****-5678",
    });
    api.verifyFreeTrialPhone.mockResolvedValue({ verified: true, phone_masked: "010-****-5678" });

    render(<CardRegistration />);
    await user.type(screen.getByLabelText("쿠폰 코드"), "inpa-free");
    await user.click(screen.getByRole("button", { name: "쿠폰 확인" }));
    await user.type(await screen.findByLabelText("휴대전화 번호"), "010-1234-5678");
    await user.click(screen.getByRole("button", { name: "인증번호 보내기" }));
    await user.type(await screen.findByLabelText("인증번호"), "123456");
    await user.click(screen.getByRole("button", { name: "인증 확인" }));

    expect(await screen.findByLabelText("연락 이메일")).toBeInTheDocument();
    expect(api.preflightRecurringCoupon).toHaveBeenCalledTimes(2);
  });

  it("인증 화면에서 쿠폰을 바꿔도 최초 쿠폰만 한 번 다시 확인한다", async () => {
    const user = userEvent.setup();
    api.preflightRecurringCoupon
      .mockRejectedValueOnce(new ApiError(409, "phone_verification_required", "휴대전화 확인이 필요해요."))
      .mockResolvedValueOnce(preview);
    api.requestFreeTrialPhoneVerification.mockResolvedValue({ challenge_id: "challenge-1", expires_in_seconds: 300, phone_masked: "010-****-5678" });
    api.verifyFreeTrialPhone.mockResolvedValue({ verified: true, phone_masked: "010-****-5678" });

    render(<CardRegistration />);
    const coupon = screen.getByLabelText("쿠폰 코드");
    await user.type(coupon, "first-code");
    await user.click(screen.getByRole("button", { name: "쿠폰 확인" }));
    await user.clear(coupon);
    await user.type(coupon, "other-code");
    await user.type(await screen.findByLabelText("휴대전화 번호"), "010-1234-5678");
    await user.click(screen.getByRole("button", { name: "인증번호 보내기" }));
    await user.type(await screen.findByLabelText("인증번호"), "123456");
    await user.click(screen.getByRole("button", { name: "인증 확인" }));

    expect(await screen.findByText("Plus 1개월 무료")).toBeInTheDocument();
    expect(api.preflightRecurringCoupon).toHaveBeenLastCalledWith("FIRST-CODE");
  });

  it("인증 뒤 재확인 오류는 코드 입력과 쿠폰 입력으로 돌아갈 수 있게 한다", async () => {
    const user = userEvent.setup();
    api.preflightRecurringCoupon
      .mockRejectedValueOnce(new ApiError(409, "phone_verification_required", "휴대전화 확인이 필요해요."))
      .mockRejectedValueOnce(new ApiError(503, "phone_verification_setup_required", "설정을 확인하고 있어요."));
    api.requestFreeTrialPhoneVerification.mockResolvedValue({ challenge_id: "challenge-1", expires_in_seconds: 300, phone_masked: "010-****-5678" });
    api.verifyFreeTrialPhone.mockResolvedValue({ verified: true, phone_masked: "010-****-5678" });

    render(<CardRegistration />);
    const coupon = screen.getByLabelText("쿠폰 코드");
    await user.type(coupon, "inpa-free");
    await user.click(screen.getByRole("button", { name: "쿠폰 확인" }));
    await user.type(await screen.findByLabelText("휴대전화 번호"), "010-1234-5678");
    await user.click(screen.getByRole("button", { name: "인증번호 보내기" }));
    await user.type(await screen.findByLabelText("인증번호"), "123456");
    await user.click(screen.getByRole("button", { name: "인증 확인" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("설정을 확인하고 있어요.");
    await user.click(screen.getByRole("button", { name: "쿠폰 코드 다시 입력" }));
    expect(coupon).toHaveFocus();
  });

  it("첫 쿠폰 확인 중에는 다른 코드로 두 번째 미리보기를 시작하지 않는다", async () => {
    let resolveFirst: ((value: typeof preview) => void) | undefined;
    api.preflightRecurringCoupon.mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }));
    const user = userEvent.setup();

    render(<CardRegistration />);
    const coupon = screen.getByLabelText("쿠폰 코드");
    await user.type(coupon, "old-code");
    await user.click(screen.getByRole("button", { name: "쿠폰 확인" }));
    await user.clear(coupon);
    await user.type(coupon, "current-code");

    expect(api.preflightRecurringCoupon).toHaveBeenNthCalledWith(1, "OLD-CODE");
    expect(screen.getByRole("button", { name: "확인 중..." })).toBeDisabled();
    expect(api.preflightRecurringCoupon).toHaveBeenCalledTimes(1);
    await act(async () => resolveFirst?.(preview));
    expect(await screen.findByText("Plus 1개월 무료")).toBeInTheDocument();
  });
});
