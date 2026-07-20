import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    getInsuranceImportConfig: vi.fn(),
    listInsuranceImports: vi.fn(),
  };
});

import { getInsuranceImportConfig, listInsuranceImports } from "@/lib/api";
import { InsuranceImportCards } from "@/components/insurance-import-cards";

const sourceReview = {
  required: false,
  image_only_page_count: 0,
  image_only_pages: [],
  quarantined_line_count: 0,
  quarantined_pages: [],
  analysis_signal_quarantined_line_count: 0,
  analysis_signal_quarantined_pages: [],
  pages_requiring_manual_source_review: [],
  requires_manual_coverage_entry: false,
  guidance: "",
};

function job(customerId: number, status: "queued" | "review_required" | "failed") {
  return {
    job_id: `${status}-job`,
    customer_id: customerId,
    status,
    intent: "add" as const,
    portfolio_type: 1 as const,
    safe_display_name: `${status}.pdf`,
    page_count: 3,
    draft_version: 1,
    error_code: "",
    target_insurance_id: null,
    target_insurance_version: null,
    source_review: sourceReview,
    confirmation_requirements: {
      planner_confirmed_source_match: { required: true as const },
      planner_confirmed_unread_pages: { required: false },
    },
    created_at: "2026-07-16T01:00:00+09:00",
    started_at: null,
    completed_at: null,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((nextResolve) => { resolve = nextResolve; });
  return { promise, resolve };
}

describe("보험 작업 이어보기", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getInsuranceImportConfig).mockResolvedValue({
      review_workflow_enabled: true,
      accepted_input: "digital_pdf",
      max_file_bytes: 50 * 1024 * 1024,
    });
    vi.mocked(listInsuranceImports).mockResolvedValue({
      count: 3,
      next: null,
      previous: null,
      results: [job(31, "review_required"), job(31, "queued"), job(31, "failed")],
    });
  });

  it("새로고침 뒤 서버 작업 상태를 분석보다 먼저 복구한다", async () => {
    render(<InsuranceImportCards customerId={31} />);

    expect(await screen.findByRole("heading", { name: "증권 확인 작업" })).toBeTruthy();
    expect(screen.getByText("직접 확인할 내용이 준비됐어요")).toBeTruthy();
    expect(screen.getByText("분석 순서를 기다리고 있어요")).toBeTruthy();
    expect(screen.getByText("증권 원문을 다시 선택해 주세요")).toBeTruthy();
    expect(listInsuranceImports).toHaveBeenCalledWith(31);
  });

  it("서버 스위치가 꺼져 있으면 기존 화면을 그대로 둔다", async () => {
    vi.mocked(getInsuranceImportConfig).mockResolvedValue({
      review_workflow_enabled: false,
      accepted_input: "digital_pdf",
      max_file_bytes: 50 * 1024 * 1024,
    });
    const { container } = render(<InsuranceImportCards customerId={31} />);

    await waitFor(() => expect(container.innerHTML).toBe(""));
    expect(getInsuranceImportConfig).toHaveBeenCalledOnce();
    expect(listInsuranceImports).not.toHaveBeenCalled();
  });

  it("설정 확인 실패를 기존 화면으로 오인하지 않고 다시 불러온다", async () => {
    vi.mocked(getInsuranceImportConfig)
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce({
        review_workflow_enabled: true,
        accepted_input: "digital_pdf",
        max_file_bytes: 50 * 1024 * 1024,
      });
    const user = userEvent.setup();
    render(<InsuranceImportCards customerId={31} />);

    await user.click(await screen.findByRole("button", { name: "다시 불러오기" }));

    expect(await screen.findByText("직접 확인할 내용이 준비됐어요")).toBeTruthy();
    expect(getInsuranceImportConfig).toHaveBeenCalledTimes(2);
  });

  it("응답 고객이 현재 주소와 다르면 섞인 목록을 숨기고 고객 목록으로 안내한다", async () => {
    vi.mocked(listInsuranceImports).mockResolvedValue({
      count: 1,
      next: null,
      previous: null,
      results: [job(99, "review_required")],
    });
    render(<InsuranceImportCards customerId={31} />);

    const link = await screen.findByRole("link", { name: "고객 목록으로 이동" });
    expect(link.getAttribute("href")).toBe("/customers");
    expect(screen.queryByText("review_required.pdf")).toBeNull();
  });

  it("고객이 바뀌면 이전 고객의 늦은 목록과 오류를 반영하지 않는다", async () => {
    const first = deferred<Awaited<ReturnType<typeof listInsuranceImports>>>();
    vi.mocked(listInsuranceImports)
      .mockReturnValueOnce(first.promise)
      .mockResolvedValueOnce({
        count: 1,
        next: null,
        previous: null,
        results: [{
          ...job(32, "review_required"),
          safe_display_name: "customer-32.pdf",
        }],
      });
    const view = render(<InsuranceImportCards customerId={31} />);

    await waitFor(() => expect(listInsuranceImports).toHaveBeenCalledWith(31));
    view.rerender(<InsuranceImportCards customerId={32} />);
    expect(await screen.findByText("customer-32.pdf")).toBeTruthy();
    expect(listInsuranceImports).toHaveBeenCalledWith(32);

    first.resolve({
      count: 1,
      next: null,
      previous: null,
      results: [{ ...job(31, "failed"), safe_display_name: "customer-31-late.pdf" }],
    });
    await waitFor(() => {
      expect(screen.queryByText("customer-31-late.pdf")).toBeNull();
      expect(screen.queryByText("증권 확인 작업을 불러오지 못했어요.")).toBeNull();
    });
  });
});
