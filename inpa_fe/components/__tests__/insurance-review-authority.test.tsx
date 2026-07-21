import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  AnalysisAuthoritySummary,
  AnalysisEmptyState,
  HeatCell,
  HeatmapGrid,
} from "@/components/heatmap";
import {
  AssignInsRow,
  InsuranceCards,
} from "@/components/insurance-review-cards";
import type { HeatmapResponse, ManualInsuranceItem } from "@/lib/api";

const api = vi.hoisted(() => ({
  listAllManualInsurances: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...api,
}));

const insurance = (overrides: Partial<ManualInsuranceItem> = {}): ManualInsuranceItem => ({
  id: 9,
  name: "기존 보험",
  insurance_type: 2,
  portfolio_type: 1,
  monthly_premiums: 30_000,
  contract_date: null,
  expiry_date: null,
  contractor_name: null,
  insured_name: null,
  is_same_insured: null,
  payment_status: null,
  is_cancelled: false,
  cancelled_at: null,
  created_at: "2026-07-17T00:00:00Z",
  review_status: "legacy_review_required",
  analysis_included: false,
  data_version: 1,
  confirmation_source: "",
  confirmed_at: null,
  review_exclusion_reason: "",
  ...overrides,
});

function heatmap(overrides: Partial<HeatmapResponse> = {}): HeatmapResponse {
  return {
    customer_id: 31,
    mode: "neutral",
    baseline_present: false,
    grading_enabled: false,
    baseline_count: 0,
    insurance_count: 0,
    included_insurance_count: 0,
    excluded_insurance_count: 0,
    last_confirmed_at: null,
    pending_review_count: 0,
    can_share: false,
    share_block_reason: null,
    summary: {
      monthly_premiums: 0,
      monthly_renewal_premium: 0,
      monthly_non_renewal_premium: 0,
      monthly_earned_premium: 0,
      total_premiums: 0,
      total_renewal_premium: 0,
      total_non_renewal_premium: 0,
      total_earned_premium: 0,
    },
    chart_list: [],
    tree: [],
    insurances: [],
    ...overrides,
  };
}

describe("insurance review authority UI", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows a legacy insurance loaded from the all-page list with its review action", async () => {
    api.listAllManualInsurances.mockResolvedValue([insurance()]);
    const onReview = vi.fn();

    render(<InsuranceCards customerId={31} portfolioType={1} onReview={onReview} title="보유 보험" />);

    expect(await screen.findByText("기존 자료 확인 필요")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "기존 자료 확인하기" }));
    expect(onReview).toHaveBeenCalledWith(9);
  });

  it("keeps unconfirmed insurance visible but disables A and B selection", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const onReview = vi.fn();
    render(<AssignInsRow it={insurance()} value="none" onChange={onChange} onReview={onReview} />);

    expect((screen.getByRole("button", { name: "증권 A" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "증권 B" }) as HTMLButtonElement).disabled).toBe(true);
    await user.click(screen.getByRole("button", { name: "기존 자료 확인하기" }));
    expect(onReview).toHaveBeenCalledWith(9);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("renders server authority counts and distinct pending, excluded, and truly empty next actions", () => {
    const pending = heatmap({
      excluded_insurance_count: 2,
      pending_review_count: 1,
      last_confirmed_at: "2026-07-16T01:30:00Z",
    });
    const first = render(<>
      <AnalysisAuthoritySummary heatmap={pending} />
      <AnalysisEmptyState heatmap={pending} onReview={() => undefined} onManual={() => undefined} />
    </>);

    expect(screen.getByText("분석 포함").parentElement?.textContent).toContain("0건");
    expect(screen.getByText("분석 미포함").parentElement?.textContent).toContain("2건");
    expect(screen.getByText("마지막 확인").parentElement?.textContent).toContain("2026. 7. 16.");
    expect(screen.getByText("확인 대기").parentElement?.textContent).toContain("1건");
    expect(screen.getByText("확인할 보험이 있어요")).toBeTruthy();
    first.unmount();

    const second = render(<AnalysisEmptyState
      heatmap={heatmap({ excluded_insurance_count: 2 })}
      onReview={() => undefined}
      onManual={() => undefined}
    />);
    expect(screen.getByText("분석에 포함된 보험이 없어요")).toBeTruthy();
    second.unmount();

    render(<AnalysisEmptyState heatmap={heatmap()} onReview={() => undefined} onManual={() => undefined} />);
    expect(screen.getByText("첫 보험을 등록해 주세요")).toBeTruthy();
  });

  it.each(["neutral", "graded"] as const)("expands the server contribution chain in %s mode without joining other client data", async (mode) => {
    const user = userEvent.setup();
    render(<HeatCell
      mode={mode}
      graded
      detail={{
        detail_id: 101,
        name: "일반암진단비",
        held_amount: 50_000_000,
        status: "shortage",
        baseline: null,
        contributions: [
          {
            case_id: 71,
            insurance_id: 9,
            insurance_name: "기존 보험",
            raw_name: "일반암 진단비",
            assurance_amount: 30_000_000,
            source_page: 4,
            mapping_source: "global",
          },
          {
            case_id: 72,
            insurance_id: 9,
            insurance_name: "기존 보험",
            raw_name: "소액암 진단비",
            assurance_amount: 20_000_000,
            source_page: null,
            mapping_source: "manual",
          },
        ],
      }}
    />);

    expect(screen.getByLabelText(
      mode === "neutral"
        ? "일반암진단비: 보유 내역만 표시"
        : "일반암진단비: 부족"
    )).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "일반암진단비 합산 근거 보기" }));
    const detail = screen.getByRole("region", { name: "일반암진단비 합산 근거" });
    expect(within(detail).getByText("기존 보험")).toBeTruthy();
    expect(within(detail).getByText("일반암 진단비").parentElement?.textContent).toContain("3,000만");
    expect(within(detail).getByText("일반암 진단비").parentElement?.textContent).toContain("4쪽");
    expect(within(detail).getByText("소액암 진단비").parentElement?.textContent).toContain("2,000만");
    expect(within(detail).getByText("소액암 진단비").parentElement?.textContent).toContain("직접 입력");
    await waitFor(() => expect(detail.textContent).not.toContain("source_text_masked"));
  });

  it("links stored baselines to their settings without showing grading colors", () => {
    const storedBaseline = heatmap({
      baseline_present: true,
      baseline_count: 1,
      tree: [{
        category_id: 1,
        name: "진단",
        insurance_type: "손해보험",
        sub_categories: [{
          sub_category_id: 11,
          name: "암",
          details: [{
            detail_id: 111,
            name: "일반암진단비",
            held_amount: 50_000_000,
            status: "shortage",
            baseline: null,
            contributions: [],
          }],
        }],
      }],
    });

    render(<HeatmapGrid
      heatmap={storedBaseline}
      graded={false}
      onGradedChange={() => undefined}
      filter="all"
      onFilterChange={() => undefined}
    />);

    const settingsLink = screen.getByText("설정한 기준 확인하기 ›").closest("a");
    expect(settingsLink?.getAttribute("href")).toBe("/settings/baseline");
    expect(screen.queryByText("내 기준 1개 적용 중")).toBeNull();
    const detail = screen.getByLabelText("일반암진단비: 보유 내역만 표시");
    expect(within(detail).queryByText("부족")).toBeNull();
    expect(within(detail).queryByText("적정")).toBeNull();
    expect(within(detail).queryByText("넉넉")).toBeNull();
    expect(detail.className).not.toContain("bg-rose-50");
  });
});
