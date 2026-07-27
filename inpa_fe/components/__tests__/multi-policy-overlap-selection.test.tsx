import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, type CompareResponse, type ManualInsuranceItem } from "@/lib/api";
import { SwitchTab } from "@/app/customer/[id]/page";

const api = vi.hoisted(() => ({
  listAllManualInsurances: vi.fn(),
  compareCustomer: vi.fn(),
}));

const clipboard = vi.hoisted(() => ({ copyText: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...api,
}));

vi.mock("@/components/ocr-upload", () => ({
  useOcrUpload: () => ({ phase: "idle", error: null, clearError: vi.fn(), retryUpload: vi.fn(), duplicateInfo: null, onFileChange: vi.fn() }),
  OcrUploadButton: () => null,
  OcrStatusBanner: () => null,
  ConsentModal: () => null,
  InsuranceDuplicateChoice: () => null,
}));

vi.mock("@/components/insurance-manual-modal", () => ({
  InsuranceManualModal: ({ onChanged }: { onChanged: () => void }) => <button type="button" onClick={onChanged}>보험 저장</button>,
}));

vi.mock("@/components/upgrade-modal", () => ({
  UpgradeModal: ({ open, onClose }: { open: boolean; onClose: () => void }) => open ? <button type="button" onClick={onClose}>한도 안내 닫기</button> : null,
}));

vi.mock("@/components/premium-split", () => ({
  CompareAiGuide: () => null,
  ComparePremiumSplit: () => null,
  PremiumSplitSection: () => null,
}));

vi.mock("@/components/charts", () => ({ CompareBarChart: () => null }));

vi.mock("@/lib/clipboard", () => clipboard);

const insurance = (id: number, name: string, portfolio_type: 1 | 2): ManualInsuranceItem => ({
  id, name, portfolio_type, insurance_type: 2, monthly_premiums: 30_000,
  contract_date: null, expiry_date: null, contractor_name: null, insured_name: null,
  is_same_insured: null, payment_status: null, is_cancelled: false, cancelled_at: null,
  created_at: "2026-07-27T00:00:00Z", review_status: "confirmed", analysis_included: true,
  data_version: 1, confirmation_source: "manual_entry", confirmed_at: "2026-07-27T00:00:00Z", review_exclusion_reason: "",
});

const initialRows = [
  insurance(1, "A1", 1), insurance(2, "A2", 1), insurance(3, "A3", 1), insurance(4, "B1", 2),
];

const comparison: CompareResponse = {
  mode: "neutral",
  current: { monthly_premiums: 30_000, total_premiums: 360_000, monthly_renewal_premium: null, monthly_non_renewal_premium: null, monthly_earned_premium: null, total_renewal_premium: null, total_non_renewal_premium: null, total_earned_premium: null, insurances: [] },
  proposed: { monthly_premiums: 40_000, total_premiums: 480_000, monthly_renewal_premium: null, monthly_non_renewal_premium: null, monthly_earned_premium: null, total_renewal_premium: null, total_non_renewal_premium: null, total_earned_premium: null, insurances: [] },
  rows: [{ coverage: "암 진단비", current_amount: 10, proposed_amount: 20, delta: 10 }], comparison_source: "deterministic", switch_warnings: [], guide_draft: null, guide_enabled: false, guide_source: null, publishable: false, publish_blocked_reason: "", disclaimer: "",
};

const renderSwitchTab = async () => {
  render(<SwitchTab customerId={77} />);
  await screen.findByRole("button", { name: "A1 왼쪽에서 제외" });
};

describe("multi-policy overlap selection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.listAllManualInsurances.mockResolvedValue(initialRows);
  });

  it("starts with the 3+1 preset without comparing, then sends overlapping side IDs only on request", async () => {
    const user = userEvent.setup();
    await renderSwitchTab();

    expect(screen.getByText("왼쪽 구성 3개")).toBeTruthy();
    expect(screen.getByText("오른쪽 구성 4개")).toBeTruthy();
    expect(api.compareCustomer).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "A3 오른쪽에서 제외" }));
    api.compareCustomer.mockResolvedValue(comparison);
    await user.click(screen.getByRole("button", { name: "선택한 구성 비교하기" }));

    expect(api.compareCustomer).toHaveBeenCalledWith(77, { sideAIds: [1, 2, 3], sideBIds: [1, 2, 4] });
  });

  it("does not call the API for an empty left side or identical selections", async () => {
    const user = userEvent.setup();
    await renderSwitchTab();
    for (const name of ["A1", "A2", "A3"]) {
      await user.click(screen.getByRole("button", { name: `${name} 왼쪽에서 제외` }));
    }
    expect(screen.getByText("왼쪽 구성에 증권을 골라 주세요.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "선택한 구성 비교하기" }) as HTMLButtonElement).disabled).toBe(true);
    expect(api.compareCustomer).not.toHaveBeenCalled();

    for (const name of ["A1", "A2", "A3"]) {
      await user.click(screen.getByRole("button", { name: `${name} 왼쪽에 포함` }));
    }
    await user.click(screen.getByRole("button", { name: "B1 오른쪽에서 제외" }));
    expect(screen.getByText("오른쪽 구성을 조정하면 차이를 볼 수 있어요.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "선택한 구성 비교하기" }) as HTMLButtonElement).disabled).toBe(true);
    expect(api.compareCustomer).not.toHaveBeenCalled();
  });

  it("keeps the selector usable after a comparison error and 402", async () => {
    const user = userEvent.setup();
    await renderSwitchTab();
    api.compareCustomer.mockRejectedValueOnce(new ApiError(500, "ERROR", "비교 내용을 불러오지 못했어요."));
    await user.click(screen.getByRole("button", { name: "선택한 구성 비교하기" }));
    expect(await screen.findByText("비교 내용을 불러오지 못했어요.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "A1 왼쪽에서 제외" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "선택한 구성 비교하기" })).toBeTruthy();

    api.compareCustomer.mockRejectedValueOnce(new ApiError(402, "LIMIT", "", { kind: "ai_compare" }));
    await user.click(screen.getByRole("button", { name: "선택한 구성 비교하기" }));
    expect(await screen.findByRole("button", { name: "한도 안내 닫기" })).toBeTruthy();
    expect(screen.getByText("왼쪽 구성 3개")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "한도 안내 닫기" }));
    api.compareCustomer.mockResolvedValueOnce(comparison);
    await user.click(screen.getByRole("button", { name: "선택한 구성 비교하기" }));
    expect(api.compareCustomer).toHaveBeenCalledTimes(3);
  });

  it("announces an in-flight comparison through a polite status region", async () => {
    const user = userEvent.setup();
    await renderSwitchTab();
    api.compareCustomer.mockReturnValueOnce(new Promise(() => {}));

    await user.click(screen.getByRole("button", { name: "선택한 구성 비교하기" }));

    const status = await screen.findByRole("status", { name: "비교하고 있어요." });
    expect(status).toHaveTextContent("비교하고 있어요.");
  });

  it("announces stale selection guidance through a polite status region", async () => {
    const user = userEvent.setup();
    await renderSwitchTab();
    api.compareCustomer.mockResolvedValueOnce(comparison);
    await user.click(screen.getByRole("button", { name: "선택한 구성 비교하기" }));
    await screen.findByText("암 진단비");

    await user.click(screen.getByRole("button", { name: "A3 오른쪽에서 제외" }));

    const guidance = "선택이 바뀌었어요. 다시 비교하면 새 구성으로 결과를 볼 수 있어요.";
    expect(screen.getByRole("status", { name: guidance })).toHaveTextContent(guidance);
  });

  it("announces a comparison 500 error through an assertive alert region", async () => {
    const user = userEvent.setup();
    await renderSwitchTab();
    api.compareCustomer.mockRejectedValueOnce(new ApiError(500, "ERROR", "비교 내용을 불러오지 못했어요."));

    await user.click(screen.getByRole("button", { name: "선택한 구성 비교하기" }));

    const error = "비교 내용을 불러오지 못했어요.";
    expect(await screen.findByRole("alert", { name: error })).toHaveTextContent(error);
  });

  it("shows limit guidance instead of a stale-selection message after a current result", async () => {
    const user = userEvent.setup();
    await renderSwitchTab();
    api.compareCustomer.mockResolvedValueOnce(comparison);
    await user.click(screen.getByRole("button", { name: "선택한 구성 비교하기" }));
    expect(await screen.findByText("암 진단비")).toBeTruthy();

    api.compareCustomer.mockRejectedValueOnce(new ApiError(402, "LIMIT", "", { kind: "ai_compare" }));
    await user.click(screen.getByRole("button", { name: "선택한 구성 비교하기" }));

    expect(await screen.findByRole("button", { name: "한도 안내 닫기" })).toBeTruthy();
    expect(screen.getByText("한도 안내에서 다음 이용 방법을 확인해 주세요.")).toBeTruthy();
    expect(screen.queryByText("선택이 바뀌었어요. 다시 비교하면 새 구성으로 결과를 볼 수 있어요.")).toBeNull();
  });

  it("hides obsolete and late comparison results after selection changes", async () => {
    const user = userEvent.setup();
    await renderSwitchTab();
    api.compareCustomer.mockResolvedValueOnce(comparison);
    await user.click(screen.getByRole("button", { name: "선택한 구성 비교하기" }));
    expect(await screen.findByText("암 진단비")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "A3 오른쪽에서 제외" }));
    expect(screen.getByText("선택이 바뀌었어요. 다시 비교하면 새 구성으로 결과를 볼 수 있어요.")).toBeTruthy();
    expect(screen.queryByText("암 진단비")).toBeNull();
    const copyButton = screen.getByRole("button", { name: "증권 비교표 내용 복사" }) as HTMLButtonElement;
    expect(copyButton.disabled).toBe(true);
    await user.click(copyButton);
    expect(clipboard.copyText).not.toHaveBeenCalled();

    let resolve!: (value: CompareResponse) => void;
    api.compareCustomer.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    await user.click(screen.getByRole("button", { name: "선택한 구성 비교하기" }));
    await user.click(screen.getByRole("button", { name: "A2 오른쪽에서 제외" }));
    resolve(comparison);
    await waitFor(() => expect(screen.queryByText("암 진단비")).toBeNull());
  });

  it("keeps the existing copy failure guidance after a current comparison", async () => {
    const user = userEvent.setup();
    clipboard.copyText.mockResolvedValueOnce(false);
    await renderSwitchTab();
    api.compareCustomer.mockResolvedValueOnce(comparison);
    await user.click(screen.getByRole("button", { name: "선택한 구성 비교하기" }));

    const copyButton = await screen.findByRole("button", { name: "증권 비교표 내용 복사" });
    await user.click(copyButton);

    expect(clipboard.copyText).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("복사에 실패했어요. 다시 시도해 주세요.")).toBeTruthy();
  });

  it("requires a new successful CTA run when the selection returns to an earlier snapshot", async () => {
    const user = userEvent.setup();
    await renderSwitchTab();
    api.compareCustomer.mockResolvedValueOnce(comparison);
    await user.click(screen.getByRole("button", { name: "선택한 구성 비교하기" }));
    expect(await screen.findByText("암 진단비")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "A3 오른쪽에서 제외" }));
    await user.click(screen.getByRole("button", { name: "A3 오른쪽에 포함" }));
    expect(screen.queryByText("암 진단비")).toBeNull();
    expect((screen.getByRole("button", { name: "증권 비교표 내용 복사" }) as HTMLButtonElement).disabled).toBe(true);

    api.compareCustomer.mockResolvedValueOnce(comparison);
    await user.click(screen.getByRole("button", { name: "선택한 구성 비교하기" }));
    expect(await screen.findByText("암 진단비")).toBeTruthy();
  });

  it("discards an ABA late response before a fresh explicit run succeeds", async () => {
    const user = userEvent.setup();
    await renderSwitchTab();
    let resolve!: (value: CompareResponse) => void;
    api.compareCustomer.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    await user.click(screen.getByRole("button", { name: "선택한 구성 비교하기" }));
    await user.click(screen.getByRole("button", { name: "A3 오른쪽에서 제외" }));
    await user.click(screen.getByRole("button", { name: "A3 오른쪽에 포함" }));
    resolve(comparison);
    await waitFor(() => expect(screen.queryByText("암 진단비")).toBeNull());
    expect((screen.getByRole("button", { name: "증권 비교표 내용 복사" }) as HTMLButtonElement).disabled).toBe(true);

    api.compareCustomer.mockResolvedValueOnce(comparison);
    await user.click(screen.getByRole("button", { name: "선택한 구성 비교하기" }));
    expect(await screen.findByText("암 진단비")).toBeTruthy();
  });

  it("keeps every selected policy name in the desktop composition summary", async () => {
    await renderSwitchTab();
    const chips = within(screen.getByTestId("selected-policy-chips-desktop"));
    for (const name of ["A1", "A2", "A3", "B1"]) {
      expect(chips.getByText(name)).toBeTruthy();
    }
  });

  it("preserves changed selections and presets only new policies on refresh", async () => {
    const user = userEvent.setup();
    api.listAllManualInsurances.mockResolvedValueOnce(initialRows).mockResolvedValueOnce([...initialRows, insurance(5, "B2", 2)]);
    await renderSwitchTab();
    await user.click(screen.getByRole("button", { name: "A3 오른쪽에서 제외" }));
    await user.click(screen.getByRole("button", { name: "직접 입력" }));
    await user.click(screen.getByRole("button", { name: "보험 저장" }));

    await screen.findByRole("button", { name: "B2 오른쪽에서 제외" });
    expect(screen.getByRole("button", { name: "A3 오른쪽에 포함" })).toBeTruthy();
    expect(screen.getByText("오른쪽 구성 4개")).toBeTruthy();
    expect(api.compareCustomer).not.toHaveBeenCalled();
  });

  it("invalidates a successful result while refresh is pending and stays usable after refresh fails", async () => {
    const user = userEvent.setup();
    let rejectRefresh!: (reason?: unknown) => void;
    api.listAllManualInsurances
      .mockResolvedValueOnce(initialRows)
      .mockReturnValueOnce(new Promise((_, reject) => { rejectRefresh = reject; }));
    await renderSwitchTab();
    await user.click(screen.getByRole("button", { name: "A3 오른쪽에서 제외" }));
    api.compareCustomer.mockResolvedValueOnce(comparison);
    await user.click(screen.getByRole("button", { name: "선택한 구성 비교하기" }));
    expect(await screen.findByText("암 진단비")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "직접 입력" }));
    await user.click(screen.getByRole("button", { name: "보험 저장" }));

    expect(await screen.findByRole("status", { name: "보험 목록을 확인하고 있어요." }))
      .toHaveTextContent("보험 목록을 확인하고 있어요.");
    expect(screen.queryByText("암 진단비")).toBeNull();
    expect((screen.getByRole("button", { name: "증권 비교표 내용 복사" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "선택한 구성 비교하기" }) as HTMLButtonElement).disabled).toBe(true);

    rejectRefresh(new Error("refresh failed"));

    expect(await screen.findByRole("alert", { name: "보험 목록을 다시 불러와 주세요." })).toBeTruthy();
    expect(screen.getByRole("button", { name: "A3 오른쪽에 포함" })).toBeTruthy();
    expect(screen.getByText("왼쪽 구성 3개")).toBeTruthy();
    expect(screen.getByText("오른쪽 구성 3개")).toBeTruthy();
    expect((screen.getByRole("button", { name: "선택한 구성 비교하기" }) as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByRole("button", { name: "증권 비교표 내용 복사" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByText("선택이 바뀌었어요. 다시 비교하면 새 구성으로 결과를 볼 수 있어요.")).toBeNull();
    expect(screen.getByRole("button", { name: "다시 불러오기" })).toBeTruthy();
    expect(clipboard.copyText).not.toHaveBeenCalled();
  });

  it("discards a comparison invalidated by refresh failure and does not leave the CTA loading", async () => {
    const user = userEvent.setup();
    let resolveCompare!: (value: CompareResponse) => void;
    let rejectRefresh!: (reason?: unknown) => void;
    api.listAllManualInsurances
      .mockResolvedValueOnce(initialRows)
      .mockReturnValueOnce(new Promise((_, reject) => { rejectRefresh = reject; }));
    api.compareCustomer.mockReturnValueOnce(new Promise((resolve) => { resolveCompare = resolve; }));
    await renderSwitchTab();

    await user.click(screen.getByRole("button", { name: "선택한 구성 비교하기" }));
    expect(await screen.findByRole("status", { name: "비교하고 있어요." })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "직접 입력" }));
    await user.click(screen.getByRole("button", { name: "보험 저장" }));
    rejectRefresh(new Error("refresh failed"));

    await screen.findByRole("alert", { name: "보험 목록을 다시 불러와 주세요." });
    const compareButton = screen.getByRole("button", { name: "선택한 구성 비교하기" }) as HTMLButtonElement;
    expect(compareButton.disabled).toBe(false);

    resolveCompare(comparison);
    await waitFor(() => expect(screen.queryByText("암 진단비")).toBeNull());
    expect(api.compareCustomer).toHaveBeenCalledTimes(1);
  });
});
