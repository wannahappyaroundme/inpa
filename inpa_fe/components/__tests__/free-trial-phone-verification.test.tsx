import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/lib/api";
import { FreeTrialPhoneVerification } from "@/components/billing/free-trial-phone-verification";
import {
  adminDecideBenefitReview,
  adminListBenefitReviews,
} from "@/lib/adminApi";

describe("무료 혜택 휴대전화 API 계약", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("휴대전화 인증 요청, 확인, 수동 확인 요청을 단일 API 게이트로 보낸다", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        challenge_id: "challenge-1",
        expires_in_seconds: 300,
        phone_masked: "010-****-5678",
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        verified: true,
        phone_masked: "010-****-5678",
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
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
      }), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);

    await api.requestFreeTrialPhoneVerification("010-1234-5678");
    await api.verifyFreeTrialPhone({
      challenge_id: "challenge-1",
      phone: "010-1234-5678",
      code: "123456",
    });
    const createdReview = await api.submitManualBenefitReview({
      contact_email: "planner@example.com",
      reason: "기존에 사용한 번호일 수 있어요",
    });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      expect.stringContaining("/billing/free-trial/phone/request/"),
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      expect.stringContaining("/billing/free-trial/phone/verify/"),
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      expect.stringContaining("/billing/free-trial/manual-reviews/"),
      expect.objectContaining({ method: "POST" }),
    );
    expect(createdReview.created).toBe(true);
  });

  it("기존 수동 확인 요청의 200 응답은 새 접수가 아님을 보존한다", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      id: 4, phone_masked: "010-****-5678", contact_email: "planner@example.com",
      reason: "기존 요청", status: "pending", decision_reason: "", created_at: "2026-07-28T00:00:00Z", decided_at: null, consumed_at: null,
    }), { status: 200 })));
    const existingReview = await api.submitManualBenefitReview({ contact_email: "planner@example.com", reason: "기존 요청" });
    expect(existingReview.created).toBe(false);
  });

  it("현재 수동 확인 상태는 없으면 null로, 있으면 단일 API 게이트에서 가져온다", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        id: 4, phone_masked: "010-****-5678", contact_email: "planner@example.com",
        reason: "기존 요청", status: "rejected", decision_reason: "확인했어요.",
        created_at: "2026-07-28T00:00:00Z", decided_at: "2026-07-28T01:00:00Z", consumed_at: null,
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        code: "manual_benefit_review_not_found",
      }), { status: 404 }));
    vi.stubGlobal("fetch", fetchMock);

    const review = await api.getCurrentManualBenefitReview();
    const none = await api.getCurrentManualBenefitReview();

    expect(review?.status).toBe("rejected");
    expect(none).toBeNull();
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      expect.stringContaining("/billing/free-trial/manual-reviews/"),
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("관리자 수동 확인 목록과 결정을 관리자 API 게이트로 보낸다", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ results: [] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        id: 4,
        phone_masked: "010-****-5678",
        contact_email: "planner@example.com",
        reason: "기존에 사용한 번호일 수 있어요",
        status: "approved",
        decision_reason: "확인했어요",
        created_at: "2026-07-28T00:00:00Z",
        decided_at: "2026-07-28T00:00:00Z",
        consumed_at: null,
      }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await adminListBenefitReviews("pending");
    await adminDecideBenefitReview(4, { decision: "approved", reason: "확인했어요" });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      expect.stringContaining("/admin/billing/benefit-reviews/?status=pending"),
      expect.objectContaining({ method: "GET" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      expect.stringContaining("/admin/billing/benefit-reviews/4/decision/"),
      expect.objectContaining({ method: "POST" }),
    );
  });
});

describe("무료 혜택 휴대전화 인증", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("인증번호를 보내면 서버가 준 마스킹 번호와 벽시계 만료 시간을 보여준다", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "requestFreeTrialPhoneVerification").mockResolvedValue({
      challenge_id: "challenge-1",
      expires_in_seconds: 300,
      phone_masked: "010-****-5678",
    });

    render(<FreeTrialPhoneVerification onVerified={vi.fn()} onBack={vi.fn()} />);
    await user.type(screen.getByLabelText("휴대전화 번호"), "010-1234-5678");
    await user.click(screen.getByRole("button", { name: "인증번호 보내기" }));

    expect(await screen.findByText("010-****-5678로 인증번호를 보냈어요.")).toBeInTheDocument();
    expect(screen.getByLabelText("인증번호")).toHaveAttribute("inputmode", "numeric");
    expect(screen.getByText("남은 시간 5:00")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /재전송 1:00/ })).toBeDisabled();
  });

  it("인증 성공 뒤 쿠폰 확인을 한 번만 다시 요청한다", async () => {
    const user = userEvent.setup();
    const onVerified = vi.fn().mockResolvedValue({ state: "complete" });
    vi.spyOn(api, "requestFreeTrialPhoneVerification").mockResolvedValue({
      challenge_id: "challenge-1",
      expires_in_seconds: 300,
      phone_masked: "010-****-5678",
    });
    vi.spyOn(api, "verifyFreeTrialPhone").mockResolvedValue({
      verified: true,
      phone_masked: "010-****-5678",
    });

    render(<FreeTrialPhoneVerification onVerified={onVerified} onBack={vi.fn()} />);
    await user.type(screen.getByLabelText("휴대전화 번호"), "010-1234-5678");
    await user.click(screen.getByRole("button", { name: "인증번호 보내기" }));
    await user.type(await screen.findByLabelText("인증번호"), "123456");
    await user.click(screen.getByRole("button", { name: "인증 확인" }));

    expect(await screen.findByText("쿠폰을 다시 확인하고 있어요.")).toBeInTheDocument();
    expect(onVerified).toHaveBeenCalledTimes(1);
  });

  it("인증 단계를 떠나면 남은 시간 갱신을 멈춘다", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-28T00:00:00Z"));
    const clearInterval = vi.spyOn(window, "clearInterval");
    vi.spyOn(api, "requestFreeTrialPhoneVerification").mockResolvedValue({
      challenge_id: "challenge-1",
      expires_in_seconds: 300,
      phone_masked: "010-****-5678",
    });
    vi.spyOn(api, "verifyFreeTrialPhone").mockResolvedValue({
      verified: true,
      phone_masked: "010-****-5678",
    });

    try {
      render(
        <FreeTrialPhoneVerification
          initialStep="phone"
          onVerified={vi.fn().mockResolvedValue({ state: "manual-review" })}
          onBack={vi.fn()}
        />,
      );
      fireEvent.change(screen.getByLabelText("휴대전화 번호"), { target: { value: "010-1234-5678" } });
      fireEvent.click(screen.getByRole("button", { name: "인증번호 보내기" }));
      await act(async () => {});
      fireEvent.change(screen.getByLabelText("인증번호"), { target: { value: "123456" } });
      fireEvent.click(screen.getByRole("button", { name: "인증 확인" }));
      await act(async () => {});

      expect(screen.getByLabelText("연락 이메일")).toBeInTheDocument();
      expect(clearInterval).toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("인증번호 입력 중 화면을 떠나면 남은 시간 interval을 정리한다", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-28T00:00:00Z"));
    const setInterval = vi.spyOn(window, "setInterval");
    const clearInterval = vi.spyOn(window, "clearInterval");
    vi.spyOn(api, "requestFreeTrialPhoneVerification").mockResolvedValue({
      challenge_id: "challenge-1",
      expires_in_seconds: 300,
      phone_masked: "010-****-5678",
    });

    try {
      const view = render(
        <FreeTrialPhoneVerification
          onVerified={vi.fn()}
          onBack={vi.fn()}
        />,
      );
      fireEvent.change(screen.getByLabelText("휴대전화 번호"), {
        target: { value: "010-1234-5678" },
      });
      fireEvent.click(screen.getByRole("button", { name: "인증번호 보내기" }));
      await act(async () => {});
      expect(screen.getByLabelText("인증번호")).toBeInTheDocument();
      const intervalIndex = setInterval.mock.calls.findIndex(
        ([, delay]) => delay === 1000,
      );
      expect(intervalIndex).toBeGreaterThanOrEqual(0);
      const intervalId = setInterval.mock.results[intervalIndex]?.value;

      view.unmount();

      expect(clearInterval).toHaveBeenCalledWith(intervalId);
    } finally {
      vi.useRealTimers();
    }
  });

  it("인증 실패 뒤에는 코드 입력에 머문다", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "requestFreeTrialPhoneVerification").mockResolvedValue({
      challenge_id: "challenge-1",
      expires_in_seconds: 300,
      phone_masked: "010-****-5678",
    });
    vi.spyOn(api, "verifyFreeTrialPhone").mockRejectedValueOnce(
      new api.ApiError(400, "invalid_code", "인증번호를 다시 확인해 주세요."),
    );
    render(<FreeTrialPhoneVerification onVerified={vi.fn()} onBack={vi.fn()} />);
    await user.type(screen.getByLabelText("휴대전화 번호"), "010-1234-5678");
    await user.click(screen.getByRole("button", { name: "인증번호 보내기" }));
    await user.type(await screen.findByLabelText("인증번호"), "654321");
    await user.click(screen.getByRole("button", { name: "인증 확인" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("인증번호를 다시 확인해 주세요.");
    expect(screen.getByLabelText("인증번호")).toHaveFocus();
  });

  it("기존 번호 확인 요청은 이메일과 사유만 보내고, 접수 상태를 그대로 보여준다", async () => {
    const user = userEvent.setup();
    const submit = vi.spyOn(api, "submitManualBenefitReview").mockResolvedValue({
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

    render(
      <FreeTrialPhoneVerification
        initialStep="manual-review"
        onVerified={vi.fn()}
        onBack={vi.fn()}
      />,
    );
    expect(screen.getByText("확인이 필요한 번호예요. 이메일과 간단한 사유를 남기면 확인 후 안내해 드릴게요.")).toBeInTheDocument();
    await user.type(screen.getByLabelText("연락 이메일"), "planner@example.com");
    await user.type(screen.getByLabelText("확인 사유"), "기존에 사용한 번호일 수 있어요");
    await user.click(screen.getByRole("button", { name: "확인 요청 보내기" }));

    expect(submit).toHaveBeenCalledWith({
      contact_email: "planner@example.com",
      reason: "기존에 사용한 번호일 수 있어요",
    });
    expect(await screen.findByText("확인 요청을 접수했어요. 처리 결과는 이 화면에서 다시 확인할 수 있어요.")).toBeInTheDocument();
    expect(screen.getByText("현재 상태: 접수")).toBeInTheDocument();
  });

  it("이미 처리된 요청 응답이면 새 요청처럼 말하지 않고 서버 상태를 보여준다", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "submitManualBenefitReview").mockResolvedValue({
      id: 4,
      phone_masked: "010-****-5678",
      contact_email: "planner@example.com",
      reason: "기존에 사용한 번호일 수 있어요",
      status: "approved",
      decision_reason: "확인했어요",
      created_at: "2026-07-28T00:00:00Z",
      decided_at: "2026-07-28T01:00:00Z",
      consumed_at: null,
    });

    render(<FreeTrialPhoneVerification initialStep="manual-review" onVerified={vi.fn()} onBack={vi.fn()} />);
    await user.type(screen.getByLabelText("연락 이메일"), "planner@example.com");
    await user.type(screen.getByLabelText("확인 사유"), "기존에 사용한 번호일 수 있어요");
    await user.click(screen.getByRole("button", { name: "확인 요청 보내기" }));

    expect(await screen.findByText("이전에 남긴 확인 요청의 현재 상태예요.")).toBeInTheDocument();
    expect(screen.getByText("현재 상태: 승인")).toBeInTheDocument();
  });

  it("확인 요청을 보내는 동안 같은 요청을 한 번만 보낸다", async () => {
    const user = userEvent.setup();
    let resolveReview: ((value: api.ManualBenefitReview) => void) | undefined;
    const submit = vi.spyOn(api, "submitManualBenefitReview").mockImplementation(() => new Promise((resolve) => {
      resolveReview = resolve;
    }));

    render(<FreeTrialPhoneVerification initialStep="manual-review" onVerified={vi.fn()} onBack={vi.fn()} />);
    await user.type(screen.getByLabelText("연락 이메일"), "planner@example.com");
    await user.type(screen.getByLabelText("확인 사유"), "기존에 사용한 번호일 수 있어요");
    await user.click(screen.getByRole("button", { name: "확인 요청 보내기" }));
    await user.click(screen.getByRole("button", { name: /확인 요청/ }));

    expect(submit).toHaveBeenCalledTimes(1);
    await act(async () => resolveReview?.({
      id: 4,
      phone_masked: "010-****-5678",
      contact_email: "planner@example.com",
      reason: "기존에 사용한 번호일 수 있어요",
      status: "pending",
      decision_reason: "",
      created_at: "2026-07-28T00:00:00Z",
      decided_at: null,
      consumed_at: null,
    }));
  });

  it("화면을 닫은 뒤 늦게 도착한 인증 응답은 쿠폰 확인을 다시 시작하지 않는다", async () => {
    const user = userEvent.setup();
    let resolveVerification: ((value: { verified: true; phone_masked: string }) => void) | undefined;
    vi.spyOn(api, "requestFreeTrialPhoneVerification").mockResolvedValue({
      challenge_id: "challenge-1",
      expires_in_seconds: 300,
      phone_masked: "010-****-5678",
    });
    vi.spyOn(api, "verifyFreeTrialPhone").mockImplementation(() => new Promise((resolve) => {
      resolveVerification = resolve;
    }));
    const onVerified = vi.fn();

    const view = render(<FreeTrialPhoneVerification onVerified={onVerified} onBack={vi.fn()} />);
    await user.type(screen.getByLabelText("휴대전화 번호"), "010-1234-5678");
    await user.click(screen.getByRole("button", { name: "인증번호 보내기" }));
    await user.type(await screen.findByLabelText("인증번호"), "123456");
    await user.click(screen.getByRole("button", { name: "인증 확인" }));
    view.unmount();
    await act(async () => resolveVerification?.({ verified: true, phone_masked: "010-****-5678" }));

    expect(onVerified).not.toHaveBeenCalled();
  });

  it("첫 인증번호 요청이 대기 중이면 빠른 이중 클릭과 번호 변경으로 새 흐름을 시작할 수 없다", async () => {
    let resolveSend: ((value: { challenge_id: string; expires_in_seconds: number; phone_masked: string }) => void) | undefined;
    const request = vi.spyOn(api, "requestFreeTrialPhoneVerification").mockImplementation(() => new Promise((resolve) => {
      resolveSend = resolve;
    }));
    const user = userEvent.setup();

    render(<FreeTrialPhoneVerification onVerified={vi.fn()} onBack={vi.fn()} />);
    const phone = screen.getByLabelText("휴대전화 번호");
    await user.type(phone, "010-1234-5678");
    await user.click(screen.getByRole("button", { name: "인증번호 보내기" }));
    await user.click(screen.getByRole("button", { name: "인증번호 보내는 중..." }));

    expect(request).toHaveBeenCalledTimes(1);
    expect(phone).toBeDisabled();
    expect(screen.getByRole("button", { name: "인증번호 보내는 중..." })).toBeDisabled();
    await act(async () => resolveSend?.({ challenge_id: "challenge-locked", expires_in_seconds: 300, phone_masked: "010-****-5678" }));
  });

  it("전송 화면을 닫은 뒤 늦게 도착한 첫 인증번호 응답은 코드 입력으로 바꾸지 않는다", async () => {
    let resolveSend: ((value: { challenge_id: string; expires_in_seconds: number; phone_masked: string }) => void) | undefined;
    vi.spyOn(api, "requestFreeTrialPhoneVerification").mockImplementation(() => new Promise((resolve) => {
      resolveSend = resolve;
    }));
    const user = userEvent.setup();
    const view = render(<FreeTrialPhoneVerification onVerified={vi.fn()} onBack={vi.fn()} />);
    await user.type(screen.getByLabelText("휴대전화 번호"), "010-1234-5678");
    await user.click(screen.getByRole("button", { name: "인증번호 보내기" }));
    view.unmount();
    await act(async () => resolveSend?.({ challenge_id: "challenge-late", expires_in_seconds: 300, phone_masked: "010-****-9999" }));

    expect(screen.queryByLabelText("인증번호")).not.toBeInTheDocument();
    expect(screen.queryByText("010-****-9999로 인증번호를 보냈어요.")).not.toBeInTheDocument();
  });

  it("재전송이 가능한 시점에는 중복 요청을 막고, 보내는 동안 원번호 입력을 숨긴다", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-28T00:00:00Z"));
    let resolveResend: ((value: { challenge_id: string; expires_in_seconds: number; phone_masked: string }) => void) | undefined;
    const request = vi.spyOn(api, "requestFreeTrialPhoneVerification")
      .mockResolvedValueOnce({ challenge_id: "challenge-1", expires_in_seconds: 300, phone_masked: "010-****-5678" })
      .mockImplementationOnce(() => new Promise((resolve) => { resolveResend = resolve; }));

    try {
      render(<FreeTrialPhoneVerification onVerified={vi.fn()} onBack={vi.fn()} />);
      fireEvent.change(screen.getByLabelText("휴대전화 번호"), { target: { value: "010-1234-5678" } });
      fireEvent.click(screen.getByRole("button", { name: "인증번호 보내기" }));
      await act(async () => {});
      await act(async () => { vi.advanceTimersByTime(60_000); });
      expect(screen.getByRole("button", { name: "인증번호 다시 보내기" })).toBeEnabled();

      const resendButton = screen.getByRole("button", { name: "인증번호 다시 보내기" });
      fireEvent.click(resendButton);
      fireEvent.click(resendButton);

      expect(request).toHaveBeenCalledTimes(2);
      expect(screen.queryByLabelText("휴대전화 번호")).not.toBeInTheDocument();
      expect(screen.getByText("인증번호를 다시 보내고 있어요.")).toBeInTheDocument();
      expect(screen.queryByText("010-1234-5678")).not.toBeInTheDocument();

      await act(async () => resolveResend?.({ challenge_id: "challenge-2", expires_in_seconds: 300, phone_masked: "010-****-5678" }));
    } finally {
      vi.useRealTimers();
    }
  });

  it("새 인증번호 요청은 늦게 끝난 이전 인증 확인이 쿠폰 재확인을 시작하지 못하게 한다", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-28T00:00:00Z"));
    let resolveVerify: ((value: { verified: true; phone_masked: string }) => void) | undefined;
    vi.spyOn(api, "requestFreeTrialPhoneVerification")
      .mockResolvedValueOnce({ challenge_id: "challenge-old", expires_in_seconds: 300, phone_masked: "010-****-1111" })
      .mockResolvedValueOnce({ challenge_id: "challenge-current", expires_in_seconds: 300, phone_masked: "010-****-2222" });
    const verify = vi.spyOn(api, "verifyFreeTrialPhone").mockImplementation(() => new Promise((resolve) => {
      resolveVerify = resolve;
    }));
    const onVerified = vi.fn().mockResolvedValue({ state: "complete" });

    try {
      render(<FreeTrialPhoneVerification onVerified={onVerified} onBack={vi.fn()} />);
      fireEvent.change(screen.getByLabelText("휴대전화 번호"), { target: { value: "010-1234-5678" } });
      fireEvent.click(screen.getByRole("button", { name: "인증번호 보내기" }));
      await act(async () => {});
      fireEvent.change(screen.getByLabelText("인증번호"), { target: { value: "123456" } });
      fireEvent.click(screen.getByRole("button", { name: "인증 확인" }));
      await act(async () => { vi.advanceTimersByTime(60_000); });
      fireEvent.click(screen.getByRole("button", { name: "인증번호 다시 보내기" }));
      await act(async () => {});

      expect(screen.getByText("010-****-2222로 인증번호를 보냈어요.")).toBeInTheDocument();
      await act(async () => resolveVerify?.({ verified: true, phone_masked: "010-****-1111" }));

      expect(onVerified).not.toHaveBeenCalled();
      fireEvent.change(screen.getByLabelText("인증번호"), { target: { value: "654321" } });
      fireEvent.click(screen.getByRole("button", { name: "인증 확인" }));
      expect(verify).toHaveBeenLastCalledWith({ challenge_id: "challenge-current", phone: "010-1234-5678", code: "654321" });
    } finally {
      vi.useRealTimers();
    }
  });

  it("Strict Mode의 setup-cleanup-setup 뒤 현재 인증번호 응답을 정상적으로 반영한다", async () => {
    let resolveSend: ((value: { challenge_id: string; expires_in_seconds: number; phone_masked: string }) => void) | undefined;
    vi.spyOn(api, "requestFreeTrialPhoneVerification").mockImplementation(() => new Promise((resolve) => {
      resolveSend = resolve;
    }));
    const user = userEvent.setup();

    render(
      <React.StrictMode>
        <FreeTrialPhoneVerification onVerified={vi.fn()} onBack={vi.fn()} />
      </React.StrictMode>,
    );
    await user.type(screen.getByLabelText("휴대전화 번호"), "010-1234-5678");
    await user.click(screen.getByRole("button", { name: "인증번호 보내기" }));
    await act(async () => resolveSend?.({ challenge_id: "challenge-strict", expires_in_seconds: 300, phone_masked: "010-****-7777" }));

    expect(await screen.findByText("010-****-7777로 인증번호를 보냈어요.")).toBeInTheDocument();
    expect(screen.getByLabelText("인증번호")).toBeInTheDocument();
  });

  it("휴대전화·인증번호·수동 확인 오류 경로가 비밀값을 화면 밖으로 보내지 않는다", async () => {
    const phoneSecret = "010-9999-1111";
    const otpSecret = "829173";
    const emailSecret = "privacy-sentinel@example.com";
    const reasonSecret = "REASON-SENTINEL-ONLY";
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const consoleWarn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const consoleLog = vi.spyOn(console, "log").mockImplementation(() => undefined);
    const localWrite = vi.spyOn(Storage.prototype, "setItem");
    const sessionWrite = vi.spyOn(window.sessionStorage.__proto__, "setItem");
    const pushState = vi.spyOn(window.history, "pushState");
    const replaceState = vi.spyOn(window.history, "replaceState");
    const analyticsTrack = vi.fn();
    Object.assign(window, { analytics: { track: analyticsTrack } });
    vi.spyOn(api, "requestFreeTrialPhoneVerification").mockResolvedValue({
      challenge_id: "challenge-private", expires_in_seconds: 300, phone_masked: "010-****-1111",
    });
    vi.spyOn(api, "verifyFreeTrialPhone").mockRejectedValue(new api.ApiError(400, "invalid_code", "안전한 인증 안내"));
    vi.spyOn(api, "submitManualBenefitReview").mockRejectedValue(new api.ApiError(400, "review_error", "안전한 확인 안내"));
    const user = userEvent.setup();

    try {
      const view = render(<FreeTrialPhoneVerification onVerified={vi.fn()} onBack={vi.fn()} />);
      await user.type(screen.getByLabelText("휴대전화 번호"), phoneSecret);
      await user.click(screen.getByRole("button", { name: "인증번호 보내기" }));
      await user.type(await screen.findByLabelText("인증번호"), otpSecret);
      await user.click(screen.getByRole("button", { name: "인증 확인" }));
      const otpError = await screen.findByRole("alert");
      expect(otpError).toHaveTextContent("안전한 인증 안내");
      expect(otpError).not.toHaveTextContent(phoneSecret);
      expect(otpError).not.toHaveTextContent(otpSecret);

      view.unmount();
      render(<FreeTrialPhoneVerification initialStep="manual-review" onVerified={vi.fn()} onBack={vi.fn()} />);
      await user.type(screen.getByLabelText("연락 이메일"), emailSecret);
      await user.type(screen.getByLabelText("확인 사유"), reasonSecret);
      await user.click(screen.getByRole("button", { name: "확인 요청 보내기" }));
      const reviewError = await screen.findByRole("alert");
      expect(reviewError).toHaveTextContent("안전한 확인 안내");
      expect(reviewError).not.toHaveTextContent(emailSecret);
      expect(reviewError).not.toHaveTextContent(reasonSecret);

      const renderedUi = document.body.cloneNode(true) as HTMLElement;
      renderedUi.querySelectorAll("input, textarea, select").forEach((field) => field.remove());
      const protectedSurfaces = {
        "인증 오류 UI": otpError.textContent ?? "",
        "수동 확인 오류 UI": reviewError.textContent ?? "",
        "입력칸 밖의 렌더링 UI": renderedUi.textContent ?? "",
        "직렬화된 오류 캡처": JSON.stringify([otpError.textContent, reviewError.textContent]),
        "console.error": JSON.stringify(consoleError.mock.calls),
        "console.warn": JSON.stringify(consoleWarn.mock.calls),
        "console.log": JSON.stringify(consoleLog.mock.calls),
        "localStorage 쓰기": JSON.stringify(localWrite.mock.calls),
        "sessionStorage 쓰기": JSON.stringify(sessionWrite.mock.calls),
        "history.pushState": JSON.stringify(pushState.mock.calls),
        "history.replaceState": JSON.stringify(replaceState.mock.calls),
        "현재 URL": window.location.href,
        "analytics payload": JSON.stringify(analyticsTrack.mock.calls),
      };
      const secrets = {
        휴대전화: phoneSecret,
        인증번호: otpSecret,
        이메일: emailSecret,
        "수동 확인 사유": reasonSecret,
      };
      for (const [secretName, secret] of Object.entries(secrets)) {
        for (const [surfaceName, surface] of Object.entries(protectedSurfaces)) {
          expect(
            surface,
            `${secretName} sentinel이 ${surfaceName}에 노출됨`,
          ).not.toContain(secret);
        }
      }
    } finally {
      delete (window as Window & { analytics?: unknown }).analytics;
    }
  });
});
