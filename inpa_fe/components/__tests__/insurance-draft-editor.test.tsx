import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  CoverageFactFields,
  CoveragePeriodFields,
  InsuranceDraftEditor,
} from "@/components/insurance-draft-editor";
import type { InsuranceDraftCoverageRow, InsuranceImportDraft } from "@/lib/api";

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

function row(index: number): InsuranceDraftCoverageRow {
  return {
    row_id: `row-${index}`,
    raw_name: `담보 ${index}`,
    assurance_amount: index * 1000,
    premium: index * 100,
    is_renewal: false,
    renewal_period: null,
    payment_period: 20,
    payment_period_unit: "years",
    warranty_period: 80,
    warranty_period_unit: "age",
    disposition: "assigned",
    standard_category: "상해",
    standard_subcategory: "사망",
    standard_detail_name: "상해사망",
    exclusion_reason: null,
    duplicate_of_row_id: null,
    source_candidate_ids: [`candidate-${index}`],
    evidence_line_ids: [`p${(index % 3) + 1}-l1`],
    state: "review_ready",
    review_reason_codes: [],
  };
}

function makeDraft(rows: InsuranceDraftCoverageRow[], unresolvedIds: string[] = []): InsuranceImportDraft {
  return {
    job_id: "33333333-3333-4333-8333-333333333333",
    customer_id: 31,
    status: "review_required",
    draft_version: 4,
    target_insurance_id: null,
    target_insurance_version: null,
    policy: {
      carrier_name: { value: "한빛보험", state: "review_ready", evidence_line_ids: ["p1-l1"], review_reason_codes: [] },
      company_code: null,
      insurance_type: { value: "life", state: "review_ready", evidence_line_ids: ["p1-l2"], review_reason_codes: [] },
      product_name: { value: "든든보험", state: "review_ready", evidence_line_ids: ["p1-l3"], review_reason_codes: [] },
      contract_date: { value: "2026-01-01", state: "review_ready", evidence_line_ids: ["p1-l4"], review_reason_codes: [] },
      expiry_date: { value: "2046-01-01", state: "review_ready", evidence_line_ids: ["p1-l5"], review_reason_codes: [] },
      monthly_premium: { value: 50000, state: "review_ready", evidence_line_ids: ["p1-l6"], review_reason_codes: [] },
    },
    coverages: rows,
    validation: {
      unresolved_count: unresolvedIds.length,
      issues: unresolvedIds.map((row_id) => ({
        code: "NEEDS_REVIEW",
        state: "needs_review",
        scope: "coverage",
        row_id,
        field: null,
      })),
    },
    source_review: sourceReview,
    confirmation_requirements: {
      planner_confirmed_source_match: { required: true },
      planner_confirmed_unread_pages: { required: false },
    },
    standard_coverages: {
      version: "v1",
      items: [{ category: "질병", subcategory: "진단", detail_name: "암진단" }],
    },
  };
}

function renderEditor(draft: InsuranceImportDraft, overrides = {}) {
  const props = {
    customerId: 31,
    draft,
    isSaving: false,
    hasVersionConflict: false,
    plannerConfirmedSourceMatch: false,
    plannerConfirmedUnreadPages: false,
    onSourceMatchChange: vi.fn(),
    onUnreadPagesChange: vi.fn(),
    onSave: vi.fn().mockResolvedValue(draft),
    onConfirm: vi.fn(),
    onViewEvidence: vi.fn(),
    ...overrides,
  };
  return { ...render(<InsuranceDraftEditor {...props} />), props };
}

function coverageRegion() {
  return within(screen.getByRole("region", { name: "담보" }));
}

describe("증권 초안 편집", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: vi.fn(),
    });
  });

  it("100개 행을 가상 목록 없이 유지하고 미해결 행을 안정적으로 먼저 둔다", async () => {
    const rows = Array.from({ length: 100 }, (_, index) => row(index + 1));
    renderEditor(makeDraft(rows, ["row-70", "row-20"]));
    const user = userEvent.setup();

    expect(screen.getByText("확인이 필요한 항목 2개")).toBeTruthy();
    const summaries = coverageRegion().getAllByRole("button", { name: /담보 \d+/ });
    expect(summaries).toHaveLength(100);
    expect(summaries[0].textContent).toContain("담보 20");
    expect(summaries[1].textContent).toContain("담보 70");
    expect(document.querySelector("[tabindex]:not([tabindex='0']):not([tabindex='-1'])")).toBeNull();
    expect(screen.queryByLabelText("담보 이름")).toBeNull();
  });

  it("첫 확인 항목으로 focus와 scroll을 옮긴다", async () => {
    renderEditor(makeDraft([row(1), row(2)], ["row-2"]));
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "첫 확인 항목으로 이동" }));

    const summary = coverageRegion().getByRole("button", { name: /담보 2/ });
    expect(document.activeElement).toBe(summary);
    expect(summary.scrollIntoView).toHaveBeenCalledWith({ block: "center" });
  });

  it("validation issue가 없어도 행 상태가 확인 필요면 미해결로 먼저 보여준다", () => {
    const stateRow = { ...row(2), state: "needs_review" as const };
    const reviewDraft = makeDraft([row(1), stateRow]);
    reviewDraft.validation.unresolved_count = 1;
    renderEditor(reviewDraft);

    expect(coverageRegion().getByRole("button", { name: /담보 2/ })).toBeTruthy();
    expect(coverageRegion().getByRole("button", { name: /담보 1/ })).toBeTruthy();
  });

  it("manual과 분석 제외 행은 서버 미해결 수, 필터, 행 표시에서 모두 해결된 상태로 맞춘다", async () => {
    const manual = { ...row(1), state: "manual" as const };
    const excluded = {
      ...row(2),
      state: "needs_review" as const,
      disposition: "intentionally_excluded" as const,
      exclusion_reason: "원문 확인",
    };
    const reviewDraft = makeDraft([manual, excluded]);
    reviewDraft.validation = {
      unresolved_count: 0,
      issues: [
        { code: "MANUAL", state: "manual", scope: "coverage", row_id: "row-1", field: null },
        { code: "OLD", state: "needs_review", scope: "coverage", row_id: "row-2", field: null },
      ],
    };
    renderEditor(reviewDraft);
    const user = userEvent.setup();

    expect(screen.getByText("확인이 필요한 항목 0개")).toBeTruthy();
    expect(coverageRegion().getByRole("button", { name: /담보 1.*확인 완료/ })).toBeTruthy();
    expect(coverageRegion().getByRole("button", { name: /담보 2.*분석 제외/ })).toBeTruthy();
  });

  it("기본정보 변경은 명시적으로 저장하고 미저장 중에는 최종 확인을 막는다", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const onSourceMatchChange = vi.fn();
    renderEditor(makeDraft([]), { onSave, onSourceMatchChange });
    const user = userEvent.setup();

    expect(screen.getByText("자동으로 정리한 내용이에요. 증권 원문과 같은지 직접 확인해 주세요.")).toBeTruthy();
    await user.clear(screen.getByLabelText("상품 이름"));
    await user.type(screen.getByLabelText("상품 이름"), "새 상품");
    expect((screen.getByRole("button", { name: "검토 완료하고 분석에 반영" }) as HTMLButtonElement).disabled).toBe(true);
    await user.click(screen.getByRole("button", { name: "기본정보 저장" }));

    expect(onSave).toHaveBeenCalledWith({
      draft_version: 4,
      policy_changes: [{ field: "product_name", value: "새 상품" }],
    });
  });

  it("선택한 기본정보 field의 원문 페이지를 연다", async () => {
    const onViewEvidence = vi.fn();
    renderEditor(makeDraft([]), { onViewEvidence });
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "상품 이름 원문에서 보기" }));
    expect(onViewEvidence).toHaveBeenCalledWith([1]);
  });

  it("정책과 담보의 확인 이유를 쉬운 말로 보여주고 해당 입력칸으로 이동한다", async () => {
    const reviewDraft = makeDraft([row(1)], ["row-1"]);
    reviewDraft.validation.issues = [
      {
        code: "INVALID_DATE",
        state: "invalid",
        scope: "policy",
        row_id: null,
        field: "contract_date",
      },
      {
        code: "AMOUNT_EVIDENCE_MISMATCH",
        state: "no_evidence",
        scope: "coverage",
        row_id: "row-1",
        field: "assurance_amount",
      },
    ];
    renderEditor(reviewDraft);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", {
      name: "계약일: 날짜 형식을 다시 확인해 주세요",
    }));
    expect(document.activeElement).toBe(screen.getByLabelText("계약일"));

    await user.click(screen.getByRole("button", {
      name: "담보 1 보장 금액: 원문 금액과 같은지 확인해 주세요",
    }));
    expect(document.activeElement).toBe(screen.getByLabelText("보장 금액"));
  });

  it.each([
    ["STANDARD_MAPPING_REQUIRED", "standard_category"],
    ["STANDARD_MAPPING_REQUIRED", "standard_subcategory"],
    ["STANDARD_MAPPING_REQUIRED", "standard_detail_name"],
    ["STANDARD_MAPPING_INVALID", "standard_detail_name"],
  ])("%s의 %s 확인은 같은 표준 위치 선택기로 이동한다", async (code, field) => {
    const mappingRow = {
      ...row(1),
      disposition: "unmatched" as const,
      standard_category: null,
      standard_subcategory: null,
      standard_detail_name: null,
      state: "unmatched" as const,
    };
    const reviewDraft = makeDraft([mappingRow], ["row-1"]);
    reviewDraft.validation.issues = [{
      code,
      state: "unmatched",
      scope: "coverage",
      row_id: "row-1",
      field,
    }];
    renderEditor(reviewDraft);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /담보 1 표준 위치:/ }));

    expect(document.activeElement).toBe(screen.getByLabelText("표준 위치"));
  });

  it.each([
    [
      "STANDARD_MAPPING_AMBIGUOUS",
      "자동으로 고른 위치가 확실하지 않아요. 증권 원문을 보고 직접 선택해 주세요",
    ],
    [
      "STANDARD_MAPPING_CONTRADICTION",
      "담보 이름과 자동으로 고른 위치가 달라 보여요. 증권 원문을 보고 직접 선택해 주세요",
    ],
  ])("%s는 쉬운 안내와 표준 위치 선택으로 이끌고 직접 해결 전 확정을 막는다", async (code, guidance) => {
    const mappingRow = {
      ...row(1),
      state: "needs_review" as const,
      review_reason_codes: [code],
    };
    const reviewDraft = makeDraft([mappingRow], ["row-1"]);
    reviewDraft.validation.issues = [{
      code,
      state: "needs_review",
      scope: "coverage",
      row_id: "row-1",
      field: "standard_detail_name",
    }];
    const resolvedDraft = makeDraft([{
      ...mappingRow,
      state: "manual" as const,
      standard_category: "질병",
      standard_subcategory: "진단",
      standard_detail_name: "암진단",
      review_reason_codes: [],
    }]);
    resolvedDraft.draft_version = 5;
    const onSave = vi.fn().mockResolvedValue(resolvedDraft);
    const { rerender, props } = renderEditor(reviewDraft, {
      plannerConfirmedSourceMatch: true,
      onSave,
    });
    const user = userEvent.setup();

    const confirm = screen.getByRole("button", { name: "검토 완료하고 분석에 반영" });
    expect((confirm as HTMLButtonElement).disabled).toBe(true);

    await user.click(screen.getByRole("button", {
      name: `담보 1 표준 위치: ${guidance}`,
    }));

    expect(document.activeElement).toBe(screen.getByLabelText("표준 위치"));
    expect((confirm as HTMLButtonElement).disabled).toBe(true);

    await user.selectOptions(screen.getByLabelText("표준 위치"), "질병\u0000진단\u0000암진단");
    await user.click(screen.getByRole("button", { name: "표준 위치 저장" }));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith({
      draft_version: 4,
      coverage_actions: [{
        row_id: "row-1",
        action: "assign",
        standard_category: "질병",
        standard_subcategory: "진단",
        standard_detail_name: "암진단",
      }],
    }));

    rerender(<InsuranceDraftEditor {...props} draft={resolvedDraft} />);
    await waitFor(() => expect((
      screen.getByRole("button", { name: "검토 완료하고 분석에 반영" }) as HTMLButtonElement
    ).disabled).toBe(false));
  });

  it("최종 반영 확인은 기본정보와 전체 담보를 확인했다는 범위를 분명히 한다", () => {
    renderEditor(makeDraft([row(1)]));

    expect(screen.getByLabelText(
      "기본정보와 전체 담보가 증권 원문과 같은지 확인했습니다"
    )).toBeTruthy();
  });

  it("담보 사실과 기간을 한 행의 명시적 저장으로 보낸다", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderEditor(makeDraft([row(1)], ["row-1"]), { onSave });
    const user = userEvent.setup();
    await user.click(coverageRegion().getByRole("button", { name: /담보 1/ }));
    await user.clear(screen.getByLabelText("보장 금액"));
    await user.type(screen.getByLabelText("보장 금액"), "9000");
    await user.clear(screen.getByLabelText("납입 기간"));
    await user.type(screen.getByLabelText("납입 기간"), "15");
    await user.click(screen.getByRole("button", { name: "담보 내용 저장" }));

    expect(onSave).toHaveBeenCalledWith({
      draft_version: 4,
      coverage_actions: expect.arrayContaining([
        { row_id: "row-1", action: "edit", field: "assurance_amount", value: 9000 },
        { row_id: "row-1", action: "edit", field: "payment_period", value: 15 },
      ]),
    });
  });

  it("표준 위치 지정과 분석 제외를 서버 action 그대로 저장한다", async () => {
    const assignRow = { ...row(1), disposition: "unmatched" as const, standard_category: null, standard_subcategory: null, standard_detail_name: null };
    const onSave = vi.fn().mockResolvedValue(undefined);
    const { rerender, props } = renderEditor(makeDraft([assignRow], ["row-1"]), { onSave });
    const user = userEvent.setup();
    await user.click(coverageRegion().getByRole("button", { name: /담보 1/ }));
    await user.selectOptions(screen.getByLabelText("표준 위치"), "질병\u0000진단\u0000암진단");
    await user.click(screen.getByRole("button", { name: "표준 위치 저장" }));
    expect(onSave).toHaveBeenLastCalledWith({
      draft_version: 4,
      coverage_actions: [{
        row_id: "row-1",
        action: "assign",
        standard_category: "질병",
        standard_subcategory: "진단",
        standard_detail_name: "암진단",
      }],
    });

    rerender(<InsuranceDraftEditor {...props} />);
    await user.type(screen.getByLabelText("분석 제외 이유"), "원문에서 중복으로 확인");
    await user.click(screen.getByRole("button", { name: "분석에서 제외" }));
    expect(onSave).toHaveBeenLastCalledWith({
      draft_version: 4,
      coverage_actions: [{ row_id: "row-1", action: "exclude", reason: "원문에서 중복으로 확인" }],
    });
  });

  it("저장된 표준 위치를 다시 열어도 선택값을 유지하고 변경 전 재저장을 막는다", async () => {
    const mappedDraft = makeDraft([row(1)]);
    mappedDraft.standard_coverages.items = [{
      category: "상해",
      subcategory: "사망",
      detail_name: "상해사망",
    }];
    renderEditor(mappedDraft);
    const user = userEvent.setup();

    await user.click(coverageRegion().getByRole("button", { name: /담보 1/ }));

    expect((screen.getByLabelText("표준 위치") as HTMLSelectElement).value).toBe(
      "상해\u0000사망\u0000상해사망"
    );
    expect(screen.getByRole("button", { name: "표준 위치 저장" }).matches(":disabled")).toBe(true);
  });

  it("확인 필요 행은 제안된 표준 위치가 맞으면 같은 값으로 확인 완료할 수 있다", async () => {
    const suggested = row(1);
    const reviewDraft = makeDraft([suggested], ["row-1"]);
    reviewDraft.standard_coverages.items = [{
      category: "상해",
      subcategory: "사망",
      detail_name: "상해사망",
    }];
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderEditor(reviewDraft, { onSave });
    const user = userEvent.setup();

    await user.click(coverageRegion().getByRole("button", { name: /담보 1/ }));
    const confirmSuggestion = screen.getByRole("button", { name: "제안 위치 확인 완료" });
    expect(confirmSuggestion.matches(":disabled")).toBe(false);

    await user.click(confirmSuggestion);
    expect(onSave).toHaveBeenLastCalledWith({
      draft_version: 4,
      coverage_actions: [{
        row_id: "row-1",
        action: "assign",
        standard_category: "상해",
        standard_subcategory: "사망",
        standard_detail_name: "상해사망",
      }],
    });
  });

  it("같은 원본 후보 집합의 행만 중복 대상으로 고르고 제외 취소와 직접 확인을 지원한다", async () => {
    const first = { ...row(1), source_candidate_ids: ["a", "b"], review_reason_codes: ["CARRIER_MANUAL_REVIEW"] };
    const matching = { ...row(2), source_candidate_ids: ["b", "a"] };
    const different = { ...row(3), source_candidate_ids: ["a"] };
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderEditor(makeDraft([first, matching, different], ["row-1"]), { onSave });
    const user = userEvent.setup();
    await user.click(coverageRegion().getByRole("button", { name: /담보 1/ }));

    const target = screen.getByLabelText("중복된 원본 항목") as HTMLSelectElement;
    expect(Array.from(target.options).map((option) => option.value)).toEqual(["", "row-2"]);
    await user.selectOptions(target, "row-2");
    await user.type(screen.getByLabelText("중복 지정 이유"), "같은 줄에서 두 번 나뉨");
    await user.click(screen.getByRole("button", { name: "중복으로 묶기" }));
    expect(onSave).toHaveBeenLastCalledWith({
      draft_version: 4,
      coverage_actions: [{ row_id: "row-1", action: "duplicate", target_row_id: "row-2", reason: "같은 줄에서 두 번 나뉨" }],
    });

    await user.click(screen.getByRole("button", { name: "직접 확인 완료" }));
    expect(onSave).toHaveBeenLastCalledWith({
      draft_version: 4,
      coverage_actions: [{ row_id: "row-1", action: "confirm" }],
    });
  });

  it("원본 후보가 비었거나 제외·중복 처리된 행은 중복 대상으로 보여주지 않는다", async () => {
    const empty = { ...row(1), source_candidate_ids: [] };
    const otherEmpty = { ...row(2), source_candidate_ids: [] };
    const source = { ...row(3), source_candidate_ids: ["a", "b"] };
    const excluded = {
      ...row(4),
      source_candidate_ids: ["b", "a"],
      disposition: "intentionally_excluded" as const,
    };
    const duplicate = {
      ...row(5),
      source_candidate_ids: ["a", "b"],
      duplicate_of_row_id: "row-9",
    };
    renderEditor(makeDraft([empty, otherEmpty, source, excluded, duplicate], ["row-1", "row-3"]));
    const user = userEvent.setup();

    await user.click(coverageRegion().getByRole("button", { name: /담보 1/ }));
    expect(screen.queryByLabelText("중복된 원본 항목")).toBeNull();
    await user.click(coverageRegion().getByRole("button", { name: /담보 3/ }));
    expect(screen.queryByLabelText("중복된 원본 항목")).toBeNull();
  });

  it("원문 근거 페이지를 모두 전달하고 필요한 두 확인이 끝나야 최종 확인한다", async () => {
    const onConfirm = vi.fn();
    const onViewEvidence = vi.fn();
    const reviewDraft = makeDraft([{ ...row(1), evidence_line_ids: ["p3-l2", "p2-l1", "bad", "p3-l7"] }]);
    reviewDraft.confirmation_requirements.planner_confirmed_unread_pages.required = true;
    renderEditor(reviewDraft, {
      plannerConfirmedSourceMatch: true,
      plannerConfirmedUnreadPages: true,
      onConfirm,
      onViewEvidence,
    });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "전체" }));
    await user.click(coverageRegion().getByRole("button", { name: /담보 1/ }));
    await user.click(screen.getByRole("button", { name: "원문에서 보기" }));
    expect(onViewEvidence).toHaveBeenCalledWith([3, 2]);
    expect((screen.getByRole("button", { name: "검토 완료하고 분석에 반영" }) as HTMLButtonElement).disabled).toBe(false);
    await user.click(screen.getByRole("button", { name: "검토 완료하고 분석에 반영" }));
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it("행 action의 미저장 값도 최종 확인을 막고 해결 전 다음 확인 항목으로 focus한다", async () => {
    const initial = makeDraft([row(1), row(2)], ["row-1", "row-2"]);
    const afterSave = makeDraft([row(1), row(2)], ["row-2"]);
    let resolveSave!: (value: InsuranceImportDraft | null) => void;
    const onSave = vi.fn().mockReturnValue(new Promise((resolve) => { resolveSave = resolve; }));
    renderEditor(initial, {
      plannerConfirmedSourceMatch: true,
      onSave,
    });
    const user = userEvent.setup();
    await user.click(coverageRegion().getByRole("button", { name: /담보 1/ }));
    await user.type(screen.getByLabelText("분석 제외 이유"), "원문에서 제외 확인");
    expect((screen.getByRole("button", { name: "검토 완료하고 분석에 반영" }) as HTMLButtonElement).disabled).toBe(true);
    await user.click(screen.getByRole("button", { name: "분석에서 제외" }));

    expect(document.activeElement).not.toBe(coverageRegion().getByRole("button", { name: /담보 2/ }));
    await act(async () => resolveSave(afterSave));

    expect(document.activeElement).toBe(coverageRegion().getByRole("button", { name: /담보 2/ }));
  });

  it("행 저장이 끝나지 않으면 현재 항목을 유지하고 마지막 해결 뒤에는 검토 상단으로 이동한다", async () => {
    const initial = makeDraft([row(1)], ["row-1"]);
    let resolveSave!: (value: InsuranceImportDraft | null) => void;
    const onSave = vi.fn().mockReturnValue(new Promise((resolve) => { resolveSave = resolve; }));
    const { rerender, props } = renderEditor(initial, { onSave });
    const user = userEvent.setup();
    await user.click(coverageRegion().getByRole("button", { name: /담보 1/ }));
    await user.type(screen.getByLabelText("분석 제외 이유"), "마지막 확인");
    const action = screen.getByRole("button", { name: "분석에서 제외" });
    await user.click(action);
    expect(document.activeElement).toBe(action);

    await act(async () => resolveSave(null));
    expect(document.activeElement).toBe(action);

    const completed = makeDraft([{ ...row(1), disposition: "intentionally_excluded" }]);
    const successfulSave = vi.fn().mockResolvedValue(completed);
    rerender(<InsuranceDraftEditor {...props} onSave={successfulSave} />);
    await user.click(screen.getByRole("button", { name: "분석에서 제외" }));
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "증권 초안 확인" }));
  });

  it("마지막 위치의 행을 해결해도 앞쪽 미해결 행이 남으면 첫 미해결로 순환한다", async () => {
    const initial = makeDraft([row(1), row(2), row(3)], ["row-1", "row-3"]);
    const afterSave = makeDraft([row(1), row(2), row(3)], ["row-1"]);
    const onSave = vi.fn().mockResolvedValue(afterSave);
    renderEditor(initial, { onSave });
    const user = userEvent.setup();
    await user.click(coverageRegion().getByRole("button", { name: /담보 3/ }));
    await user.type(screen.getByLabelText("분석 제외 이유"), "뒤 항목 해결");
    await user.click(screen.getByRole("button", { name: "분석에서 제외" }));

    expect(document.activeElement).toBe(coverageRegion().getByRole("button", { name: /담보 1/ }));
  });

  it("저장 중에는 기본정보, 모든 담보 action, 원문 확인과 확정을 함께 잠근다", async () => {
    const reviewDraft = makeDraft([row(1)], ["row-1"]);
    const { rerender, props } = renderEditor(reviewDraft);
    const user = userEvent.setup();
    await user.click(coverageRegion().getByRole("button", { name: /담보 1/ }));
    rerender(<InsuranceDraftEditor {...props} isSaving />);

    for (const control of [
      screen.getByLabelText("상품 이름"),
      screen.getByLabelText("담보 이름"),
      screen.getByLabelText("표준 위치"),
      screen.getByLabelText("분석 제외 이유"),
      screen.getByRole("button", { name: "담보 내용 저장" }),
      screen.getByRole("button", { name: "제안 위치 확인 완료" }),
      screen.getByRole("button", { name: "분석에서 제외" }),
      screen.getByLabelText("기본정보와 전체 담보가 증권 원문과 같은지 확인했습니다"),
      screen.getByRole("button", { name: "검토 완료하고 분석에 반영" }),
    ]) {
      expect(control.matches(":disabled")).toBe(true);
    }
  });

  it("공통 담보 field는 전체 row 없이 필요한 값과 typed 변경 callback만 받는다", async () => {
    const onFactChange = vi.fn();
    const onPeriodChange = vi.fn();
    render(
      <>
        <CoverageFactFields
          value={{ raw_name: "암진단", assurance_amount: 1000, premium: 100 }}
          onChange={onFactChange}
        />
        <CoveragePeriodFields
          value={{
            is_renewal: false,
            renewal_period: null,
            payment_period: 20,
            payment_period_unit: "years",
            warranty_period: 80,
            warranty_period_unit: "age",
          }}
          onChange={onPeriodChange}
        />
      </>
    );
    const user = userEvent.setup();
    fireEvent.change(screen.getByLabelText("보장 금액"), { target: { value: "2000" } });
    await user.selectOptions(screen.getByLabelText("갱신 여부"), "true");
    expect(onFactChange).toHaveBeenLastCalledWith("assurance_amount", 2000);
    expect(onPeriodChange).toHaveBeenLastCalledWith("is_renewal", true);
  });

  it("분석 제외 행을 원래 상태로 되돌리는 action을 보낸다", async () => {
    const excluded = { ...row(1), disposition: "intentionally_excluded" as const, exclusion_reason: "중복" };
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderEditor(makeDraft([excluded]), { onSave });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "분석 제외" }));
    await user.click(coverageRegion().getByRole("button", { name: /담보 1/ }));
    await user.click(screen.getByRole("button", { name: "분석 제외 취소" }));

    expect(onSave).toHaveBeenCalledWith({
      draft_version: 4,
      coverage_actions: [{ row_id: "row-1", action: "undo_exclude" }],
    });
  });
});
