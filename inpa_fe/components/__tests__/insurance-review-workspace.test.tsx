import { act, render, screen } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    getInsuranceImport: vi.fn(),
    getInsuranceImportDraft: vi.fn(),
    getInsuranceImportSourceUrl: vi.fn(),
    patchInsuranceImportDraft: vi.fn(),
    confirmInsuranceImport: vi.fn(),
  };
});

import {
  ApiError,
  confirmInsuranceImport,
  getInsuranceImport,
  getInsuranceImportDraft,
  getInsuranceImportSourceUrl,
  patchInsuranceImportDraft,
  type InsuranceImportDraft,
  type InsuranceImportStatus,
} from "@/lib/api";
import {
  InsuranceReviewWorkspace,
  parseInsuranceReviewRouteParams,
} from "@/components/insurance-review-workspace";

const JOB_ID = "33333333-3333-4333-8333-333333333333";
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
const confirmationRequirements = {
  planner_confirmed_source_match: { required: true as const },
  planner_confirmed_unread_pages: { required: false },
};

function job(status: InsuranceImportStatus, customerId = 31) {
  return {
    job_id: JOB_ID,
    customer_id: customerId,
    status,
    intent: "add" as const,
    portfolio_type: 1 as const,
    safe_display_name: "접수한 증권",
    page_count: 3,
    draft_version: 1,
    error_code: "",
    target_insurance_id: null,
    target_insurance_version: null,
    source_review: sourceReview,
    confirmation_requirements: confirmationRequirements,
    created_at: "2026-07-17T00:00:00+09:00",
    started_at: null,
    completed_at: null,
  };
}

function draft(): InsuranceImportDraft {
  return {
    job_id: JOB_ID,
    customer_id: 31,
    status: "review_required" as const,
    draft_version: 1,
    target_insurance_id: null,
    target_insurance_version: null,
    policy: {
      carrier_name: { value: "보험사", state: "review_ready" as const, evidence_line_ids: [], review_reason_codes: [] },
      company_code: null,
      insurance_type: { value: "life" as const, state: "review_ready" as const, evidence_line_ids: [], review_reason_codes: [] },
      product_name: { value: "상품", state: "review_ready" as const, evidence_line_ids: [], review_reason_codes: [] },
      contract_date: { value: "2026-01-01", state: "review_ready" as const, evidence_line_ids: [], review_reason_codes: [] },
      expiry_date: { value: "2036-01-01", state: "review_ready" as const, evidence_line_ids: [], review_reason_codes: [] },
      monthly_premium: { value: 10000, state: "review_ready" as const, evidence_line_ids: [], review_reason_codes: [] },
    },
    coverages: [],
    validation: { unresolved_count: 0, issues: [] },
    source_review: sourceReview,
    confirmation_requirements: confirmationRequirements,
    standard_coverages: { version: "v1", items: [] },
  };
}

async function flush() {
  await act(async () => undefined);
}

describe("증권 검토 주소", () => {
  it("양의 정수 고객 번호와 canonical UUID만 허용한다", () => {
    expect(
      parseInsuranceReviewRouteParams({
        id: "31",
        jobId: "33333333-3333-4333-8333-333333333333",
      })
    ).toEqual({ customerId: 31, jobId: "33333333-3333-4333-8333-333333333333" });

    for (const id of ["0", "01", "1e2", "1.5", " "]) {
      expect(
        parseInsuranceReviewRouteParams({
          id,
          jobId: "33333333-3333-4333-8333-333333333333",
        })
      ).toBeNull();
    }
    expect(parseInsuranceReviewRouteParams({ id: "31", jobId: "not-a-uuid" })).toBeNull();
  });
});

describe("증권 검토 작업 상태", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.resetAllMocks();
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    vi.mocked(getInsuranceImportSourceUrl).mockResolvedValue({ url: "https://source.example/policy", expires_in: 300 });
  });

  afterEach(() => vi.useRealTimers());

  it("한 요청이 끝난 뒤 8초를 기다려 다음 상태를 읽고 검토 초안을 연다", async () => {
    let resolveFirst!: (value: ReturnType<typeof job>) => void;
    vi.mocked(getInsuranceImport)
      .mockReturnValueOnce(new Promise((resolve) => { resolveFirst = resolve; }))
      .mockResolvedValueOnce(job("extracting"))
      .mockResolvedValueOnce(job("validating"))
      .mockResolvedValueOnce(job("review_required"));
    vi.mocked(getInsuranceImportDraft).mockResolvedValue(draft());

    render(<InsuranceReviewWorkspace customerId={31} jobId={JOB_ID} />);
    await act(async () => vi.advanceTimersByTime(24_000));
    expect(getInsuranceImport).toHaveBeenCalledTimes(1);

    await act(async () => resolveFirst(job("queued")));
    expect(screen.getByRole("status").textContent).toContain("분석 순서를 기다리고 있어요");

    for (const expected of ["증권 내용을 읽고 있어요", "읽은 내용을 확인하고 있어요"]) {
      await act(async () => vi.advanceTimersByTime(8_000));
      await flush();
      expect(screen.getByRole("status").textContent).toContain(expected);
    }
    await act(async () => vi.advanceTimersByTime(8_000));
    await flush();
    await flush();
    expect(getInsuranceImportDraft).toHaveBeenCalledWith(JOB_ID);
    expect(screen.getByRole("heading", { name: "증권 원문과 초안 확인" })).toBeTruthy();
  });

  it("작업 고객이 주소 고객과 다르면 초안 요청 없이 목록으로 안내한다", async () => {
    vi.mocked(getInsuranceImport).mockResolvedValue(job("review_required", 99));
    render(<InsuranceReviewWorkspace customerId={31} jobId={JOB_ID} />);
    await flush();

    expect(screen.getByRole("alert").textContent).toContain("현재 고객의 증권 작업을 다시 선택해 주세요");
    expect(getInsuranceImportDraft).not.toHaveBeenCalled();
  });

  it("숨긴 화면에서는 멈추고 다시 보거나 focus하면 즉시 최신 상태를 읽는다", async () => {
    vi.mocked(getInsuranceImport).mockResolvedValue(job("queued"));
    render(<InsuranceReviewWorkspace customerId={31} jobId={JOB_ID} />);
    await flush();

    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
    await act(async () => vi.advanceTimersByTime(32_000));
    expect(getInsuranceImport).toHaveBeenCalledTimes(1);

    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    document.dispatchEvent(new Event("visibilitychange"));
    await flush();
    expect(getInsuranceImport).toHaveBeenCalledTimes(2);

    window.dispatchEvent(new Event("focus"));
    await flush();
    expect(getInsuranceImport).toHaveBeenCalledTimes(3);
  });

  it("작업이 바뀐 뒤 도착한 이전 응답을 버린다", async () => {
    let resolveOld!: (value: ReturnType<typeof job>) => void;
    vi.mocked(getInsuranceImport)
      .mockReturnValueOnce(new Promise((resolve) => { resolveOld = resolve; }))
      .mockResolvedValueOnce(job("extracting"));
    const { rerender } = render(<InsuranceReviewWorkspace customerId={31} jobId={JOB_ID} />);
    const newJobId = "44444444-4444-4444-8444-444444444444";
    rerender(<InsuranceReviewWorkspace customerId={31} jobId={newJobId} />);
    await flush();
    await act(async () => resolveOld(job("review_required")));

    expect(screen.getByRole("status").textContent).toContain("증권 내용을 읽고 있어요");
    expect(getInsuranceImportDraft).not.toHaveBeenCalled();
  });

  it("고객과 작업 identity가 바뀌는 즉시 이전 초안과 원문, 확인, 재시도 상태를 비운다", async () => {
    const nextJobId = "44444444-4444-4444-8444-444444444444";
    const firstDraft = draft();
    firstDraft.policy.product_name.value = "이전 고객 상품";
    const nextDraft = draft();
    nextDraft.job_id = nextJobId;
    nextDraft.customer_id = 32;
    nextDraft.policy.product_name.value = "새 고객 상품";
    let resolveNextJob!: (value: ReturnType<typeof job>) => void;
    vi.mocked(getInsuranceImport)
      .mockResolvedValueOnce(job("review_required"))
      .mockReturnValueOnce(new Promise((resolve) => { resolveNextJob = resolve; }));
    vi.mocked(getInsuranceImportDraft)
      .mockResolvedValueOnce(firstDraft)
      .mockResolvedValueOnce(nextDraft);
    vi.mocked(patchInsuranceImportDraft).mockRejectedValueOnce(new TypeError("network"));

    const { rerender } = render(<InsuranceReviewWorkspace customerId={31} jobId={JOB_ID} />);
    await flush();
    await flush();
    fireEvent.click(screen.getByLabelText("기본정보와 전체 담보가 증권 원문과 같은지 확인했습니다"));
    fireEvent.change(screen.getByLabelText("상품 이름"), { target: { value: "저장 대기 값" } });
    fireEvent.click(screen.getByRole("button", { name: "기본정보 저장" }));
    await flush();
    expect(screen.getByRole("button", { name: "같은 내용 다시 저장" })).toBeTruthy();
    expect(screen.getByTitle("증권 원문, 1페이지")).toBeTruthy();

    rerender(<InsuranceReviewWorkspace customerId={32} jobId={nextJobId} />);
    expect(screen.queryByDisplayValue("이전 고객 상품")).toBeNull();
    expect(screen.queryByDisplayValue("저장 대기 값")).toBeNull();
    expect(screen.queryByTitle("증권 원문, 1페이지")).toBeNull();
    expect(screen.queryByRole("button", { name: "같은 내용 다시 저장" })).toBeNull();
    expect(screen.queryByLabelText("기본정보와 전체 담보가 증권 원문과 같은지 확인했습니다")).toBeNull();

    await act(async () => resolveNextJob({ ...job("review_required", 32), job_id: nextJobId }));
    await flush();
    await flush();
    expect(screen.getByDisplayValue("새 고객 상품")).toBeTruthy();
    expect((screen.getByLabelText("기본정보와 전체 담보가 증권 원문과 같은지 확인했습니다") as HTMLInputElement).checked).toBe(false);
    expect((screen.getByRole("button", { name: "검토 완료하고 분석에 반영" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it.each([
    ["failed", "증권 원문을 다시 선택해 주세요", "alert"],
    ["canceled", "선택한 증권 작업을 정리했어요", "status"],
    ["confirmed", "확인한 내용이 분석에 반영됐어요", "status"],
    ["superseded", "새로 확인한 자료가 반영됐어요", "status"],
  ] as const)("%s 상태에서 polling을 끝내고 다음 행동을 보여준다", async (status, copy, role) => {
    vi.mocked(getInsuranceImport).mockResolvedValue(job(status));
    render(<InsuranceReviewWorkspace customerId={31} jobId={JOB_ID} />);
    await flush();
    await act(async () => vi.advanceTimersByTime(60_000));

    expect(screen.getByRole(role).textContent).toContain(copy);
    expect(getInsuranceImport).toHaveBeenCalledTimes(1);
    window.dispatchEvent(new Event("focus"));
    await flush();
    expect(getInsuranceImport).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("link", { name: "고객 분석으로 이동" }).getAttribute("href"))
      .toBe("/customer/31?tab=analysis");
  });

  it("404는 자동 재시도하지 않고 고객 목록으로 안내한다", async () => {
    vi.mocked(getInsuranceImport).mockRejectedValue(new ApiError(404, "not_found", "not found"));
    render(<InsuranceReviewWorkspace customerId={31} jobId={JOB_ID} />);
    await flush();
    await act(async () => vi.advanceTimersByTime(60_000));

    expect(screen.getByRole("alert").textContent).toContain("증권 확인 작업을 찾지 못했어요");
    expect(getInsuranceImport).toHaveBeenCalledTimes(1);
  });

  it("일시적인 연결 오류는 8초, 16초, 30초 뒤 재시도한 후 수동 재시도를 연다", async () => {
    vi.mocked(getInsuranceImport).mockRejectedValue(new TypeError("network"));
    render(<InsuranceReviewWorkspace customerId={31} jobId={JOB_ID} />);
    await flush();
    for (const delay of [8_000, 16_000, 30_000]) {
      await act(async () => vi.advanceTimersByTime(delay));
      await flush();
    }

    expect(getInsuranceImport).toHaveBeenCalledTimes(4);
    expect(screen.getByRole("button", { name: "다시 불러오기" })).toBeTruthy();
  });

  it("검토 상태와 초안 요청이 엇갈리면 작업 상태를 즉시 다시 읽는다", async () => {
    vi.mocked(getInsuranceImport)
      .mockResolvedValueOnce(job("review_required"))
      .mockResolvedValueOnce(job("confirmed"));
    vi.mocked(getInsuranceImportDraft).mockRejectedValue(
      new ApiError(409, "DRAFT_NOT_READY", "state changed")
    );
    render(<InsuranceReviewWorkspace customerId={31} jobId={JOB_ID} />);
    await flush();
    await flush();
    await flush();

    expect(getInsuranceImport).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("status").textContent).toContain("확인한 내용이 분석에 반영됐어요");
  });

  it("서버 target/version과 두 원문 확인을 그대로 보내 확정 후 고객 분석으로 이동한다", async () => {
    const reviewDraft = draft();
    reviewDraft.target_insurance_id = 9;
    reviewDraft.target_insurance_version = 7;
    reviewDraft.source_review = { ...sourceReview, required: true, pages_requiring_manual_source_review: [2] };
    reviewDraft.confirmation_requirements = {
      planner_confirmed_source_match: { required: true },
      planner_confirmed_unread_pages: { required: true },
    };
    vi.mocked(getInsuranceImport).mockResolvedValue({
      ...job("review_required"),
      intent: "replace",
      target_insurance_id: 9,
      target_insurance_version: 7,
      source_review: reviewDraft.source_review,
      confirmation_requirements: reviewDraft.confirmation_requirements,
    });
    vi.mocked(getInsuranceImportDraft).mockResolvedValue(reviewDraft);
    vi.mocked(confirmInsuranceImport).mockResolvedValue({
      job_id: JOB_ID,
      status: "confirmed",
      insurance_id: 9,
      insurance_version: 8,
      confirmed_coverage_count: 0,
    });
    render(<InsuranceReviewWorkspace customerId={31} jobId={JOB_ID} />);
    await flush();
    await flush();

    fireEvent.click(screen.getByLabelText("기본정보와 전체 담보가 증권 원문과 같은지 확인했습니다"));
    fireEvent.click(screen.getByLabelText("읽기 어려운 페이지도 원문에서 직접 확인했습니다"));
    fireEvent.click(screen.getByRole("button", { name: "검토 완료하고 분석에 반영" }));
    await flush();

    expect(confirmInsuranceImport).toHaveBeenCalledWith(
      JOB_ID,
      {
        draft_version: 1,
        target_insurance_version: 7,
        planner_confirmed_source_match: true,
        planner_confirmed_unread_pages: true,
      },
      expect.any(String)
    );
    expect(push).toHaveBeenCalledWith("/customer/31?tab=analysis");
  });

  it("같은 tick의 저장과 확정 중복 입력을 각각 한 호출로 막는다", async () => {
    let resolvePatch!: (value: InsuranceImportDraft) => void;
    vi.mocked(getInsuranceImport).mockResolvedValue(job("review_required"));
    vi.mocked(getInsuranceImportDraft).mockResolvedValue(draft());
    vi.mocked(patchInsuranceImportDraft).mockReturnValue(
      new Promise((resolve) => { resolvePatch = resolve; })
    );
    render(<InsuranceReviewWorkspace customerId={31} jobId={JOB_ID} />);
    await flush();
    await flush();

    fireEvent.change(screen.getByLabelText("상품 이름"), { target: { value: "한 번만 저장" } });
    const save = screen.getByRole("button", { name: "기본정보 저장" });
    fireEvent.click(save);
    fireEvent.click(save);
    expect(patchInsuranceImportDraft).toHaveBeenCalledTimes(1);

    await act(async () => resolvePatch({ ...draft(), draft_version: 2 }));
    await flush();

    let resolveConfirm!: (value: {
      job_id: string;
      status: "confirmed";
      insurance_id: number;
      insurance_version: number;
      confirmed_coverage_count: number;
    }) => void;
    vi.mocked(confirmInsuranceImport).mockReturnValue(
      new Promise((resolve) => { resolveConfirm = resolve; })
    );
    fireEvent.click(screen.getByLabelText("기본정보와 전체 담보가 증권 원문과 같은지 확인했습니다"));
    const confirm = screen.getByRole("button", { name: "검토 완료하고 분석에 반영" });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    expect(confirmInsuranceImport).toHaveBeenCalledTimes(1);
    await act(async () => resolveConfirm({
      job_id: JOB_ID,
      status: "confirmed",
      insurance_id: 1,
      insurance_version: 1,
      confirmed_coverage_count: 0,
    }));
  });

  it("COMMAND_IN_PROGRESS를 세 번까지만 자동 재시도하고 같은 key로 수동 재시도한다", async () => {
    vi.mocked(getInsuranceImport).mockResolvedValue(job("review_required"));
    vi.mocked(getInsuranceImportDraft).mockResolvedValue(draft());
    vi.mocked(patchInsuranceImportDraft).mockRejectedValue(
      new ApiError(409, "COMMAND_IN_PROGRESS", "busy")
    );
    render(<InsuranceReviewWorkspace customerId={31} jobId={JOB_ID} />);
    await flush();
    await flush();
    fireEvent.change(screen.getByLabelText("상품 이름"), { target: { value: "재시도 값" } });
    fireEvent.click(screen.getByRole("button", { name: "기본정보 저장" }));
    await flush();
    for (let index = 0; index < 3; index += 1) {
      await act(async () => vi.advanceTimersByTime(1_000));
      await flush();
    }

    expect(patchInsuranceImportDraft).toHaveBeenCalledTimes(4);
    const firstKey = vi.mocked(patchInsuranceImportDraft).mock.calls[0][2];
    expect(vi.mocked(patchInsuranceImportDraft).mock.calls.every((call) => call[2] === firstKey)).toBe(true);
    expect(screen.getByRole("button", { name: "같은 내용 다시 저장" })).toBeTruthy();
    await act(async () => vi.advanceTimersByTime(60_000));
    expect(patchInsuranceImportDraft).toHaveBeenCalledTimes(4);

    vi.mocked(patchInsuranceImportDraft).mockResolvedValueOnce({ ...draft(), draft_version: 2 });
    fireEvent.click(screen.getByRole("button", { name: "같은 내용 다시 저장" }));
    await flush();
    expect(patchInsuranceImportDraft).toHaveBeenCalledTimes(5);
    expect(vi.mocked(patchInsuranceImportDraft).mock.calls[4][2]).toBe(firstKey);
  });

  it("COMMAND_IN_PROGRESS 대기 중 unmount하면 이전 저장을 다시 호출하지 않는다", async () => {
    vi.mocked(getInsuranceImport).mockResolvedValue(job("review_required"));
    vi.mocked(getInsuranceImportDraft).mockResolvedValue(draft());
    vi.mocked(patchInsuranceImportDraft).mockRejectedValue(
      new ApiError(409, "COMMAND_IN_PROGRESS", "busy")
    );
    const { unmount } = render(<InsuranceReviewWorkspace customerId={31} jobId={JOB_ID} />);
    await flush();
    await flush();
    fireEvent.change(screen.getByLabelText("상품 이름"), { target: { value: "종료 전 값" } });
    fireEvent.click(screen.getByRole("button", { name: "기본정보 저장" }));
    await flush();
    expect(patchInsuranceImportDraft).toHaveBeenCalledTimes(1);
    unmount();
    await act(async () => vi.advanceTimersByTime(10_000));
    expect(patchInsuranceImportDraft).toHaveBeenCalledTimes(1);
  });

  it("COMMAND_IN_PROGRESS 대기 중 고객과 작업이 바뀌면 이전 저장을 다시 호출하지 않는다", async () => {
    const nextJobId = "44444444-4444-4444-8444-444444444444";
    const nextDraft = draft();
    nextDraft.job_id = nextJobId;
    nextDraft.customer_id = 32;
    vi.mocked(getInsuranceImport)
      .mockResolvedValueOnce(job("review_required"))
      .mockResolvedValueOnce({ ...job("review_required", 32), job_id: nextJobId });
    vi.mocked(getInsuranceImportDraft)
      .mockResolvedValueOnce(draft())
      .mockResolvedValueOnce(nextDraft);
    vi.mocked(patchInsuranceImportDraft).mockRejectedValue(
      new ApiError(409, "COMMAND_IN_PROGRESS", "busy")
    );
    const { rerender } = render(<InsuranceReviewWorkspace customerId={31} jobId={JOB_ID} />);
    await flush();
    await flush();
    fireEvent.change(screen.getByLabelText("상품 이름"), { target: { value: "이전 작업 값" } });
    fireEvent.click(screen.getByRole("button", { name: "기본정보 저장" }));
    await flush();
    rerender(<InsuranceReviewWorkspace customerId={32} jobId={nextJobId} />);
    await flush();
    await act(async () => vi.advanceTimersByTime(10_000));
    expect(patchInsuranceImportDraft).toHaveBeenCalledTimes(1);
  });

  it("편집 version 충돌은 최신 서버 초안을 읽고 두 원문 확인을 초기화한다", async () => {
    const latest = draft();
    latest.draft_version = 2;
    latest.policy.product_name.value = "최신 상품";
    vi.mocked(getInsuranceImport).mockResolvedValue(job("review_required"));
    vi.mocked(getInsuranceImportDraft)
      .mockResolvedValueOnce(draft())
      .mockResolvedValueOnce(latest);
    vi.mocked(patchInsuranceImportDraft).mockRejectedValue(
      new ApiError(409, "DRAFT_VERSION_CHANGED", "changed")
    );
    render(<InsuranceReviewWorkspace customerId={31} jobId={JOB_ID} />);
    await flush();
    await flush();
    fireEvent.click(screen.getByLabelText("기본정보와 전체 담보가 증권 원문과 같은지 확인했습니다"));
    fireEvent.change(screen.getByLabelText("상품 이름"), { target: { value: "내 수정" } });
    fireEvent.click(screen.getByRole("button", { name: "기본정보 저장" }));
    await flush();
    await flush();

    expect(screen.getByRole("status").textContent).toContain("다른 화면에서 내용이 바뀌었어요. 최신 내용을 불러왔습니다.");
    expect((screen.getByLabelText("상품 이름") as HTMLInputElement).value).toBe("최신 상품");
    expect((screen.getByLabelText("기본정보와 전체 담보가 증권 원문과 같은지 확인했습니다") as HTMLInputElement).checked).toBe(false);
  });

  it("편집 충돌 뒤 최신 초안 연결이 끊겨도 차단 상태와 GET 전용 수동 복구를 제공한다", async () => {
    const latest = draft();
    latest.draft_version = 2;
    latest.policy.product_name.value = "수동 복구 상품";
    vi.mocked(getInsuranceImport).mockResolvedValue(job("review_required"));
    vi.mocked(getInsuranceImportDraft)
      .mockResolvedValueOnce(draft())
      .mockRejectedValueOnce(new TypeError("network"))
      .mockResolvedValueOnce(latest);
    vi.mocked(patchInsuranceImportDraft).mockRejectedValue(
      new ApiError(409, "DRAFT_VERSION_CHANGED", "changed")
    );
    render(<InsuranceReviewWorkspace customerId={31} jobId={JOB_ID} />);
    await flush();
    await flush();
    fireEvent.click(screen.getByLabelText("기본정보와 전체 담보가 증권 원문과 같은지 확인했습니다"));
    fireEvent.change(screen.getByLabelText("상품 이름"), { target: { value: "충돌한 수정" } });
    fireEvent.click(screen.getByRole("button", { name: "기본정보 저장" }));
    await flush();
    await flush();

    expect(screen.getByRole("status").textContent).toContain("최신 내용을 불러오지 못했어요");
    const reload = screen.getByRole("button", { name: "최신 내용 다시 불러오기" });
    expect((screen.getByRole("button", { name: "검토 완료하고 분석에 반영" }) as HTMLButtonElement).disabled).toBe(true);
    expect(patchInsuranceImportDraft).toHaveBeenCalledTimes(1);

    fireEvent.click(reload);
    await flush();
    await flush();
    expect(getInsuranceImportDraft).toHaveBeenCalledTimes(3);
    expect(patchInsuranceImportDraft).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "최신 내용 다시 불러오기" })).toBeNull();
    expect(screen.getByDisplayValue("수동 복구 상품")).toBeTruthy();
    expect((screen.getByLabelText("기본정보와 전체 담보가 증권 원문과 같은지 확인했습니다") as HTMLInputElement).checked).toBe(false);
  });

  it("확정 충돌의 최신 초안 GET 실패도 처리되지 않은 rejection 없이 수동 복구로 전환한다", async () => {
    vi.mocked(getInsuranceImport).mockResolvedValue(job("review_required"));
    vi.mocked(getInsuranceImportDraft)
      .mockResolvedValueOnce(draft())
      .mockRejectedValueOnce(new TypeError("network"));
    vi.mocked(confirmInsuranceImport).mockRejectedValue(
      new ApiError(409, "DRAFT_VERSION_CHANGED", "changed")
    );
    render(<InsuranceReviewWorkspace customerId={31} jobId={JOB_ID} />);
    await flush();
    await flush();
    fireEvent.click(screen.getByLabelText("기본정보와 전체 담보가 증권 원문과 같은지 확인했습니다"));
    fireEvent.click(screen.getByRole("button", { name: "검토 완료하고 분석에 반영" }));
    await flush();
    await flush();

    expect(screen.getByRole("button", { name: "최신 내용 다시 불러오기" })).toBeTruthy();
    expect((screen.getByRole("button", { name: "검토 완료하고 분석에 반영" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("충돌 수동 GET이 대기 중 identity가 바뀌면 이전 최신 초안을 버린다", async () => {
    const nextJobId = "44444444-4444-4444-8444-444444444444";
    const nextDraft = draft();
    nextDraft.job_id = nextJobId;
    nextDraft.customer_id = 32;
    nextDraft.policy.product_name.value = "새 고객 상품";
    const staleLatest = draft();
    staleLatest.draft_version = 9;
    staleLatest.policy.product_name.value = "이전 고객 최신 상품";
    let resolveStale!: (value: InsuranceImportDraft) => void;
    vi.mocked(getInsuranceImport)
      .mockResolvedValueOnce(job("review_required"))
      .mockResolvedValueOnce({ ...job("review_required", 32), job_id: nextJobId });
    vi.mocked(getInsuranceImportDraft)
      .mockResolvedValueOnce(draft())
      .mockRejectedValueOnce(new TypeError("network"))
      .mockReturnValueOnce(new Promise((resolve) => { resolveStale = resolve; }))
      .mockResolvedValueOnce(nextDraft);
    vi.mocked(patchInsuranceImportDraft).mockRejectedValue(
      new ApiError(409, "DRAFT_VERSION_CHANGED", "changed")
    );
    const { rerender } = render(<InsuranceReviewWorkspace customerId={31} jobId={JOB_ID} />);
    await flush();
    await flush();
    fireEvent.change(screen.getByLabelText("상품 이름"), { target: { value: "충돌 값" } });
    fireEvent.click(screen.getByRole("button", { name: "기본정보 저장" }));
    await flush();
    await flush();
    fireEvent.click(screen.getByRole("button", { name: "최신 내용 다시 불러오기" }));

    rerender(<InsuranceReviewWorkspace customerId={32} jobId={nextJobId} />);
    await flush();
    await flush();
    await act(async () => resolveStale(staleLatest));
    await flush();

    expect(screen.getByDisplayValue("새 고객 상품")).toBeTruthy();
    expect(screen.queryByDisplayValue("이전 고객 최신 상품")).toBeNull();
  });

  it("대상 보험이 바뀐 충돌은 특정 보험 query 없이 최신 목록으로 돌아간다", async () => {
    vi.mocked(getInsuranceImport).mockResolvedValue(job("review_required"));
    vi.mocked(getInsuranceImportDraft).mockResolvedValue(draft());
    vi.mocked(confirmInsuranceImport).mockRejectedValue(
      new ApiError(409, "IMPORT_TARGET_CHANGED", "changed")
    );
    render(<InsuranceReviewWorkspace customerId={31} jobId={JOB_ID} />);
    await flush();
    await flush();
    fireEvent.click(screen.getByLabelText("기본정보와 전체 담보가 증권 원문과 같은지 확인했습니다"));
    fireEvent.click(screen.getByRole("button", { name: "검토 완료하고 분석에 반영" }));
    await flush();

    expect(push).toHaveBeenCalledWith("/customer/31?tab=analysis");
  });

  it("작업이 바뀐 뒤 도착한 이전 편집 응답을 새 화면에 적용하지 않는다", async () => {
    const newJobId = "44444444-4444-4444-8444-444444444444";
    const oldDraft = draft();
    const newDraft = draft();
    newDraft.job_id = newJobId;
    newDraft.policy.product_name.value = "새 작업 상품";
    let resolveOldPatch!: (value: InsuranceImportDraft) => void;
    vi.mocked(getInsuranceImport)
      .mockResolvedValueOnce(job("review_required"))
      .mockResolvedValueOnce({ ...job("review_required"), job_id: newJobId });
    vi.mocked(getInsuranceImportDraft)
      .mockResolvedValueOnce(oldDraft)
      .mockResolvedValueOnce(newDraft);
    vi.mocked(patchInsuranceImportDraft).mockReturnValueOnce(
      new Promise((resolve) => { resolveOldPatch = resolve; })
    );
    const { rerender } = render(<InsuranceReviewWorkspace customerId={31} jobId={JOB_ID} />);
    await flush();
    await flush();
    fireEvent.change(screen.getByLabelText("상품 이름"), { target: { value: "이전 작업 수정" } });
    fireEvent.click(screen.getByRole("button", { name: "기본정보 저장" }));

    rerender(<InsuranceReviewWorkspace customerId={31} jobId={newJobId} />);
    await flush();
    await flush();
    resolveOldPatch({ ...oldDraft, draft_version: 2 });
    await flush();

    expect((screen.getByLabelText("상품 이름") as HTMLInputElement).value).toBe("새 작업 상품");
  });
});
