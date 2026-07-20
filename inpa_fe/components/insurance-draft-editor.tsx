"use client";

import { useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";

import type {
  DraftPatchPayload,
  InsuranceDraftCoverageRow,
  InsuranceImportDraft,
  ReviewState,
  StandardCoverageOption,
  ValidationIssue,
} from "@/lib/api";

type CoverageFilter = "unresolved" | "all" | "confirmed" | "excluded";

const FIELD_LABELS: Record<string, string> = {
  carrier_name: "보험사 이름",
  insurance_type: "보험 종류",
  product_name: "상품 이름",
  contract_date: "계약일",
  expiry_date: "만기일",
  monthly_premium: "월 보험료",
  raw_name: "담보 이름",
  assurance_amount: "보장 금액",
  premium: "담보 보험료",
  is_renewal: "갱신 여부",
  renewal_period: "갱신 주기",
  payment_period: "납입 기간",
  payment_period_unit: "납입 기간 기준",
  warranty_period: "보장 기간",
  warranty_period_unit: "보장 기간 기준",
  standard_category: "표준 위치",
  standard_subcategory: "표준 위치",
  standard_detail_name: "표준 위치",
};

const ISSUE_GUIDANCE: Record<string, string> = {
  INVALID_DATE: "날짜 형식을 다시 확인해 주세요",
  CONTRACT_AFTER_EXPIRY: "계약일과 만기일 순서를 확인해 주세요",
  NEGATIVE_AMOUNT: "0원 이상의 금액을 입력해 주세요",
  NEGATIVE_PREMIUM: "0원 이상의 보험료를 입력해 주세요",
  RAW_NAME_REQUIRED: "담보 이름을 입력해 주세요",
  ASSURANCE_AMOUNT_REQUIRED: "보장 금액을 입력해 주세요",
  INSURANCE_TYPE_REQUIRED: "보험 종류를 선택해 주세요",
  RENEWAL_FLAG_REQUIRED: "갱신 여부를 선택해 주세요",
  PERIOD_UNIT_REQUIRED: "기간 기준을 선택해 주세요",
  PERIOD_VALUE_REQUIRED: "기간을 입력해 주세요",
  INVALID_PERIOD: "기간을 다시 확인해 주세요",
  PAYMENT_PERIOD_EXCEEDS_WARRANTY: "납입 기간과 보장 기간을 확인해 주세요",
  AMOUNT_EVIDENCE_MISMATCH: "원문 금액과 같은지 확인해 주세요",
  PREMIUM_EVIDENCE_MISMATCH: "원문 보험료와 같은지 확인해 주세요",
  RAW_NAME_EVIDENCE_MISMATCH: "원문 담보 이름과 같은지 확인해 주세요",
  DATE_EVIDENCE_MISMATCH: "원문 날짜와 같은지 확인해 주세요",
  TEXT_EVIDENCE_MISMATCH: "원문 내용과 같은지 확인해 주세요",
  EVIDENCE_LINE_NOT_FOUND: "원문 위치를 직접 확인해 주세요",
  AMOUNT_ROLE_AMBIGUOUS: "금액의 쓰임을 원문에서 확인해 주세요",
  CARRIER_MANUAL_REVIEW: "보험사 양식을 원문에서 직접 확인해 주세요",
  STANDARD_MAPPING_AMBIGUOUS: "자동으로 고른 위치가 확실하지 않아요. 증권 원문을 보고 직접 선택해 주세요",
  STANDARD_MAPPING_CONTRADICTION: "담보 이름과 자동으로 고른 위치가 달라 보여요. 증권 원문을 보고 직접 선택해 주세요",
};

function reviewFieldTarget(field: string | null): string | null {
  if (
    field === "standard_category" ||
    field === "standard_subcategory" ||
    field === "standard_detail_name"
  ) {
    return "standard_category";
  }
  return field;
}

function issueLabel(issue: ValidationIssue, draft: InsuranceImportDraft): string {
  const rowIndex = issue.row_id
    ? draft.coverages.findIndex((row) => row.row_id === issue.row_id)
    : -1;
  const scope = issue.scope === "coverage" && rowIndex >= 0
    ? `담보 ${rowIndex + 1} `
    : "";
  const field = issue.field ? FIELD_LABELS[issue.field] ?? "해당 항목" : "해당 항목";
  const guidance = ISSUE_GUIDANCE[issue.code]
    ?? (issue.state === "unmatched"
      ? "표준 위치를 선택해 주세요"
      : issue.state === "no_evidence"
        ? "증권 원문과 같은지 확인해 주세요"
        : "입력 내용을 다시 확인해 주세요");
  return `${scope}${field}: ${guidance}`;
}

export interface InsuranceDraftEditorProps {
  customerId: number;
  draft: InsuranceImportDraft;
  isSaving: boolean;
  hasVersionConflict: boolean;
  plannerConfirmedSourceMatch: boolean;
  plannerConfirmedUnreadPages: boolean;
  onSourceMatchChange: (checked: boolean) => void;
  onUnreadPagesChange: (checked: boolean) => void;
  onSave: (payload: DraftPatchPayload) => Promise<InsuranceImportDraft | null>;
  onConfirm: () => Promise<void> | void;
  onViewEvidence: (pages: number[]) => void;
  focusRequest?: { type: "first-unresolved" | "source-match" | "unread-pages"; key: number } | null;
}

function unresolvedRowIds(draft: InsuranceImportDraft): Set<string> {
  const ids = new Set<string>();
  const unresolvedStates = new Set<ReviewState>(["needs_review", "no_evidence", "unmatched", "invalid"]);
  const rowsById = new Map(draft.coverages.map((row) => [row.row_id, row]));
  for (const issue of draft.validation.issues) {
    if (!issue.row_id || !unresolvedStates.has(issue.state)) continue;
    const row = rowsById.get(issue.row_id);
    if (row && row.disposition !== "intentionally_excluded") ids.add(issue.row_id);
  }
  for (const row of draft.coverages) {
    if (row.disposition !== "intentionally_excluded" && unresolvedStates.has(row.state)) ids.add(row.row_id);
  }
  return ids;
}

export function stableUnresolvedFirst(
  rows: InsuranceDraftCoverageRow[],
  unresolvedIds: ReadonlySet<string>
): InsuranceDraftCoverageRow[] {
  return [
    ...rows.filter((row) => unresolvedIds.has(row.row_id)),
    ...rows.filter((row) => !unresolvedIds.has(row.row_id)),
  ];
}

export function evidencePages(lineIds: string[], pageCount: number | null = null): number[] {
  const maximum = pageCount && pageCount > 0 ? pageCount : Number.MAX_SAFE_INTEGER;
  return Array.from(
    new Set(
      lineIds
        .map((lineId) => /^p([1-9]\d*)-l\d+$/.exec(lineId)?.[1])
        .map(Number)
        .filter((page) => Number.isSafeInteger(page) && page >= 1 && page <= maximum)
    )
  );
}

export function StandardCoveragePicker({
  options,
  value,
  onChange,
  ariaLabel = "표준 위치",
}: {
  options: StandardCoverageOption[];
  value: string;
  onChange: (value: string) => void;
  ariaLabel?: string;
}) {
  return (
    <label className="grid gap-1 text-xs font-semibold text-ink2">
      표준 위치
      <select aria-label={ariaLabel} data-review-field="standard_category" className="rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink" value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">위치를 선택해 주세요</option>
        {options.map((option) => {
          const key = `${option.category}\u0000${option.subcategory}\u0000${option.detail_name}`;
          return <option key={key} value={key}>{option.category} / {option.subcategory} / {option.detail_name}</option>;
        })}
      </select>
    </label>
  );
}

function standardCoverageValue(row: InsuranceDraftCoverageRow): string {
  if (!row.standard_category || !row.standard_subcategory || !row.standard_detail_name) {
    return "";
  }
  return `${row.standard_category}\u0000${row.standard_subcategory}\u0000${row.standard_detail_name}`;
}

export interface CoverageFactValue {
  raw_name: string | null;
  assurance_amount: number | null;
  premium: number | null;
}

export interface CoveragePeriodValue {
  is_renewal: boolean | null;
  renewal_period: number | null;
  payment_period: number | null;
  payment_period_unit: "years" | "age" | "lifetime" | null;
  warranty_period: number | null;
  warranty_period_unit: "years" | "age" | "lifetime" | null;
}

type CoverageFactChange = <Field extends keyof CoverageFactValue>(
  field: Field,
  value: CoverageFactValue[Field]
) => void;
type CoveragePeriodChange = <Field extends keyof CoveragePeriodValue>(
  field: Field,
  value: CoveragePeriodValue[Field]
) => void;

export function coverageFactValueFromImport(row: InsuranceDraftCoverageRow): CoverageFactValue {
  return {
    raw_name: row.raw_name,
    assurance_amount: row.assurance_amount,
    premium: row.premium,
  };
}

export function coveragePeriodValueFromImport(row: InsuranceDraftCoverageRow): CoveragePeriodValue {
  return {
    is_renewal: row.is_renewal,
    renewal_period: row.renewal_period,
    payment_period: row.payment_period,
    payment_period_unit: row.payment_period_unit,
    warranty_period: row.warranty_period,
    warranty_period_unit: row.warranty_period_unit,
  };
}

export function CoverageFactFields({
  value,
  onChange,
  ariaLabelPrefix = "",
}: {
  value: CoverageFactValue;
  onChange: CoverageFactChange;
  ariaLabelPrefix?: string;
}) {
  const ariaLabel = (label: string) => ariaLabelPrefix
    ? `${ariaLabelPrefix} ${label.replace(/^담보 /, "")}`
    : label;
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <label className="grid gap-1 text-xs font-semibold text-ink2">담보 이름<input data-review-field="raw_name" aria-label={ariaLabel("담보 이름")} className="rounded-lg border border-line px-3 py-2 text-sm" value={value.raw_name ?? ""} onChange={(event) => onChange("raw_name", event.target.value)} /></label>
      <label className="grid gap-1 text-xs font-semibold text-ink2">보장 금액<input data-review-field="assurance_amount" aria-label={ariaLabel("보장 금액")} type="number" min="0" className="rounded-lg border border-line px-3 py-2 text-sm" value={value.assurance_amount ?? ""} onChange={(event) => onChange("assurance_amount", event.target.value === "" ? null : Number(event.target.value))} /></label>
      <label className="grid gap-1 text-xs font-semibold text-ink2">담보 보험료<input data-review-field="premium" aria-label={ariaLabel("담보 보험료")} type="number" min="0" className="rounded-lg border border-line px-3 py-2 text-sm" value={value.premium ?? ""} onChange={(event) => onChange("premium", event.target.value === "" ? null : Number(event.target.value))} /></label>
    </div>
  );
}

export function CoveragePeriodFields({
  value,
  onChange,
  ariaLabelPrefix = "",
}: {
  value: CoveragePeriodValue;
  onChange: CoveragePeriodChange;
  ariaLabelPrefix?: string;
}) {
  const ariaLabel = (label: string) => ariaLabelPrefix ? `${ariaLabelPrefix} ${label}` : label;
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <label className="grid gap-1 text-xs font-semibold text-ink2">갱신 여부<select data-review-field="is_renewal" aria-label={ariaLabel("갱신 여부")} className="rounded-lg border border-line px-3 py-2 text-sm" value={value.is_renewal === null ? "" : String(value.is_renewal)} onChange={(event) => onChange("is_renewal", event.target.value === "" ? null : event.target.value === "true")}><option value="">확인 필요</option><option value="false">비갱신</option><option value="true">갱신</option></select></label>
      <label className="grid gap-1 text-xs font-semibold text-ink2">갱신 주기<input data-review-field="renewal_period" aria-label={ariaLabel("갱신 주기")} type="number" min="1" className="rounded-lg border border-line px-3 py-2 text-sm" value={value.renewal_period ?? ""} onChange={(event) => onChange("renewal_period", event.target.value === "" ? null : Number(event.target.value))} /></label>
      <label className="grid gap-1 text-xs font-semibold text-ink2">납입 기간<input data-review-field="payment_period" aria-label={ariaLabel("납입 기간")} type="number" min="1" disabled={value.payment_period_unit === "lifetime"} className="rounded-lg border border-line px-3 py-2 text-sm disabled:bg-surface2" value={value.payment_period ?? ""} onChange={(event) => onChange("payment_period", event.target.value === "" ? null : Number(event.target.value))} /></label>
      <label className="grid gap-1 text-xs font-semibold text-ink2">납입 기간 기준<select data-review-field="payment_period_unit" aria-label={ariaLabel("납입 기간 기준")} className="rounded-lg border border-line px-3 py-2 text-sm" value={value.payment_period_unit ?? ""} onChange={(event) => { const unit = (event.target.value || null) as CoveragePeriodValue["payment_period_unit"]; if (unit === "lifetime") onChange("payment_period", null); onChange("payment_period_unit", unit); }}><option value="">확인 필요</option><option value="years">년</option><option value="age">나이</option><option value="lifetime">종신</option></select></label>
      <label className="grid gap-1 text-xs font-semibold text-ink2">보장 기간<input data-review-field="warranty_period" aria-label={ariaLabel("보장 기간")} type="number" min="1" disabled={value.warranty_period_unit === "lifetime"} className="rounded-lg border border-line px-3 py-2 text-sm disabled:bg-surface2" value={value.warranty_period ?? ""} onChange={(event) => onChange("warranty_period", event.target.value === "" ? null : Number(event.target.value))} /></label>
      <label className="grid gap-1 text-xs font-semibold text-ink2">보장 기간 기준<select data-review-field="warranty_period_unit" aria-label={ariaLabel("보장 기간 기준")} className="rounded-lg border border-line px-3 py-2 text-sm" value={value.warranty_period_unit ?? ""} onChange={(event) => { const unit = (event.target.value || null) as CoveragePeriodValue["warranty_period_unit"]; if (unit === "lifetime") onChange("warranty_period", null); onChange("warranty_period_unit", unit); }}><option value="">확인 필요</option><option value="years">년</option><option value="age">나이</option><option value="lifetime">종신</option></select></label>
    </div>
  );
}

const EMPTY_COVERAGE_FACTS: CoverageFactValue = {
  raw_name: "",
  assurance_amount: null,
  premium: null,
};

const EMPTY_COVERAGE_PERIODS: CoveragePeriodValue = {
  is_renewal: null,
  renewal_period: null,
  payment_period: null,
  payment_period_unit: null,
  warranty_period: null,
  warranty_period_unit: null,
};

function manualCoverageErrors(
  facts: CoverageFactValue,
  periods: CoveragePeriodValue,
  standardValue: string
): string[] {
  const errors: string[] = [];
  if (!facts.raw_name?.trim()) errors.push("담보 이름을 입력해 주세요.");
  if (facts.assurance_amount === null) {
    errors.push("보장 금액을 입력해 주세요.");
  } else if (!Number.isSafeInteger(facts.assurance_amount) || facts.assurance_amount < 0) {
    errors.push("보장 금액은 0원 이상의 정수로 입력해 주세요.");
  }
  if (facts.premium !== null && (!Number.isSafeInteger(facts.premium) || facts.premium < 0)) {
    errors.push("담보 보험료는 0원 이상의 정수로 입력해 주세요.");
  }
  if (periods.is_renewal === null) errors.push("갱신 여부를 선택해 주세요.");
  if (periods.is_renewal === true && periods.renewal_period === null) {
    errors.push("갱신 주기를 입력해 주세요.");
  }
  if (periods.renewal_period !== null && (!Number.isSafeInteger(periods.renewal_period) || periods.renewal_period < 1)) {
    errors.push("갱신 주기는 1 이상의 정수로 입력해 주세요.");
  }
  if (periods.is_renewal === false && periods.renewal_period !== null) {
    errors.push("비갱신 담보는 갱신 주기를 비워 주세요.");
  }
  for (const [label, period, unit] of [
    ["납입", periods.payment_period, periods.payment_period_unit],
    ["보장", periods.warranty_period, periods.warranty_period_unit],
  ] as const) {
    if (!unit) errors.push(`${label} 기간 기준을 선택해 주세요.`);
    if (unit && unit !== "lifetime" && period === null) errors.push(`${label} 기간을 입력해 주세요.`);
    if (period !== null && (!Number.isSafeInteger(period) || period < 1)) {
      errors.push(`${label} 기간은 1 이상의 정수로 입력해 주세요.`);
    }
  }
  if (!standardValue) errors.push("표준 위치를 선택해 주세요.");
  return errors;
}

function ManualCoverageAddForm({
  draft,
  disabled,
  onSave,
  onDirtyChange,
}: {
  draft: InsuranceImportDraft;
  disabled: boolean;
  onSave: InsuranceDraftEditorProps["onSave"];
  onDirtyChange: (dirty: boolean) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [facts, setFacts] = useState<CoverageFactValue>(EMPTY_COVERAGE_FACTS);
  const [periods, setPeriods] = useState<CoveragePeriodValue>(EMPTY_COVERAGE_PERIODS);
  const [standardValue, setStandardValue] = useState("");
  const [showErrors, setShowErrors] = useState(false);
  const fieldsetRef = useRef<HTMLFieldSetElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const returnFocusAfterSaveRef = useRef(false);

  useEffect(() => {
    onDirtyChange(expanded);
    return () => onDirtyChange(false);
  }, [expanded, onDirtyChange]);

  useEffect(() => {
    if (!expanded && returnFocusAfterSaveRef.current) {
      returnFocusAfterSaveRef.current = false;
      toggleRef.current?.focus();
    }
  }, [expanded]);

  const errors = manualCoverageErrors(facts, periods, standardValue);
  const updateFact: CoverageFactChange = (field, value) => {
    setFacts((current) => ({ ...current, [field]: value }));
  };
  const updatePeriod: CoveragePeriodChange = (field, value) => {
    setPeriods((current) => ({
      ...current,
      [field]: value,
      ...(field === "is_renewal" && value === false ? { renewal_period: null } : {}),
    }));
  };
  const reset = () => {
    setFacts(EMPTY_COVERAGE_FACTS);
    setPeriods(EMPTY_COVERAGE_PERIODS);
    setStandardValue("");
    setShowErrors(false);
    setExpanded(false);
  };
  const submit = async () => {
    setShowErrors(true);
    if (errors.length > 0) {
      fieldsetRef.current?.querySelector<HTMLInputElement>('[aria-label="새 담보 이름"]')?.focus();
      return;
    }
    const [standard_category, standard_subcategory, standard_detail_name] = standardValue.split("\u0000");
    const nextDraft = await onSave({
      draft_version: draft.draft_version,
      coverage_actions: [{
        action: "add",
        raw_name: facts.raw_name!.trim(),
        assurance_amount: facts.assurance_amount!,
        premium: facts.premium,
        is_renewal: periods.is_renewal!,
        renewal_period: periods.renewal_period,
        payment_period: periods.payment_period,
        payment_period_unit: periods.payment_period_unit,
        warranty_period: periods.warranty_period,
        warranty_period_unit: periods.warranty_period_unit,
        standard_category,
        standard_subcategory,
        standard_detail_name,
      }],
    });
    if (nextDraft) {
      returnFocusAfterSaveRef.current = true;
      reset();
    }
  };

  return (
    <div className="mt-4 rounded-xl border border-line bg-surface2 p-4">
      <p className="text-sm leading-6 text-ink2">자동 정리에서 빠진 담보를 증권 원문대로 추가할 수 있어요.</p>
      <button
        ref={toggleRef}
        type="button"
        disabled={disabled}
        aria-expanded={expanded}
        aria-controls="manual-coverage-add-form"
        className="mt-3 rounded-lg border border-brand px-3 py-2 text-sm font-semibold text-brand disabled:opacity-40"
        onClick={() => {
          if (expanded) reset();
          else setExpanded(true);
        }}
      >
        {expanded ? "담보 추가 닫기" : "담보 직접 추가"}
      </button>
      {expanded && (
        <fieldset ref={fieldsetRef} id="manual-coverage-add-form" disabled={disabled} className="mt-4 min-w-0 space-y-3 border-0 p-0">
          <legend className="sr-only">새 담보 입력</legend>
          <CoverageFactFields value={facts} onChange={updateFact} ariaLabelPrefix="새 담보" />
          <CoveragePeriodFields value={periods} onChange={updatePeriod} ariaLabelPrefix="새 담보" />
          <StandardCoveragePicker
            options={draft.standard_coverages.items}
            value={standardValue}
            onChange={setStandardValue}
            ariaLabel="새 담보 표준 위치"
          />
          {showErrors && errors.length > 0 && (
            <ul role="alert" className="space-y-1 rounded-lg bg-warn-soft p-3 text-sm font-semibold text-warn-ink">
              {errors.map((error) => <li key={error}>{error}</li>)}
            </ul>
          )}
          <button type="button" className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-40" onClick={() => void submit()}>담보 추가 저장</button>
        </fieldset>
      )}
    </div>
  );
}

export function CoverageRowSummary({ row, unresolved }: { row: InsuranceDraftCoverageRow; unresolved: boolean }) {
  return (
    <span className="flex w-full items-center justify-between gap-3 text-left">
      <span className="font-semibold text-ink">{row.raw_name || "이름 확인 필요"}</span>
      <span className="shrink-0 text-xs text-ink3">{unresolved ? "확인 필요" : row.disposition === "intentionally_excluded" ? "분석 제외" : "확인 완료"}</span>
    </span>
  );
}

function policyInitial(draft: InsuranceImportDraft) {
  return {
    carrier_name: draft.policy.carrier_name.value ?? "",
    insurance_type: draft.policy.insurance_type.value ?? "",
    product_name: draft.policy.product_name.value ?? "",
    contract_date: draft.policy.contract_date.value ?? "",
    expiry_date: draft.policy.expiry_date.value ?? "",
    monthly_premium: draft.policy.monthly_premium.value === null ? "" : String(draft.policy.monthly_premium.value),
  };
}

const COVERAGE_EDIT_FIELDS = [
  "raw_name",
  "assurance_amount",
  "premium",
  "is_renewal",
  "renewal_period",
  "payment_period",
  "payment_period_unit",
  "warranty_period",
  "warranty_period_unit",
] as const;

const SOURCE_CONFIRM_FIELD_BY_CODE = {
  RAW_NAME_EVIDENCE_MISMATCH: "raw_name",
  AMOUNT_EVIDENCE_MISMATCH: "assurance_amount",
  AMOUNT_ROLE_AMBIGUOUS: "assurance_amount",
  PREMIUM_EVIDENCE_MISMATCH: "premium",
} as const;

function sameCandidates(left: string[], right: string[]): boolean {
  const leftSet = new Set(left);
  const rightSet = new Set(right);
  if (leftSet.size === 0 || rightSet.size === 0 || leftSet.size !== rightSet.size) return false;
  return Array.from(leftSet).every((value) => rightSet.has(value));
}

function CoverageRowDetails({
  draft,
  row,
  unresolved,
  onSave,
  onViewEvidence,
  onDirtyChange,
  onDidResolve,
  isSaving,
}: {
  draft: InsuranceImportDraft;
  row: InsuranceDraftCoverageRow;
  unresolved: boolean;
  onSave: InsuranceDraftEditorProps["onSave"];
  onViewEvidence: InsuranceDraftEditorProps["onViewEvidence"];
  onDirtyChange: (dirty: boolean) => void;
  onDidResolve: (rowId: string, nextDraft: InsuranceImportDraft) => void;
  isSaving: boolean;
}) {
  const [edited, setEdited] = useState(row);
  const [standardValue, setStandardValue] = useState(() => standardCoverageValue(row));
  const [excludeReason, setExcludeReason] = useState("");
  const [duplicateReason, setDuplicateReason] = useState("");
  const [duplicateTarget, setDuplicateTarget] = useState("");

  useEffect(() => {
    setEdited(row);
    setStandardValue(standardCoverageValue(row));
    setExcludeReason("");
    setDuplicateReason("");
    setDuplicateTarget("");
  }, [draft.draft_version, row]);

  const editActions = COVERAGE_EDIT_FIELDS.flatMap((field) =>
    edited[field] === row[field]
      ? []
      : [{ row_id: row.row_id, action: "edit" as const, field, value: edited[field] }]
  );
  const hasDirtyValues = editActions.length > 0;
  const initialStandardValue = standardCoverageValue(row);
  const hasDirtyAction = Boolean(
    standardValue !== initialStandardValue || excludeReason || duplicateReason || duplicateTarget
  );
  useEffect(() => onDirtyChange(hasDirtyValues || hasDirtyAction), [hasDirtyAction, hasDirtyValues, onDirtyChange]);

  const duplicateTargets = draft.coverages.filter((candidate) =>
    candidate.row_id !== row.row_id &&
    candidate.disposition !== "intentionally_excluded" &&
    candidate.duplicate_of_row_id === null &&
    sameCandidates(candidate.source_candidate_ids, row.source_candidate_ids)
  );
  const pages = evidencePages(row.evidence_line_ids);
  const sourceConfirmFields = Array.from(new Set(
    row.review_reason_codes.flatMap((code) => {
      const field = SOURCE_CONFIRM_FIELD_BY_CODE[
        code as keyof typeof SOURCE_CONFIRM_FIELD_BY_CODE
      ];
      return field && row[field] !== null ? [field] : [];
    })
  ));
  const sourceConfirmActions = sourceConfirmFields.map((field) => ({
    row_id: row.row_id,
    action: "edit" as const,
    field,
    value: row[field],
  }));

  const updateFact: CoverageFactChange = (field, value) => {
    setEdited((current) => ({ ...current, [field]: value }));
  };
  const updatePeriod: CoveragePeriodChange = (field, value) => {
    setEdited((current) => ({ ...current, [field]: value }));
  };
  const saveActions = async (
    actions: NonNullable<DraftPatchPayload["coverage_actions"]>
  ) => {
    const nextDraft = await onSave({ draft_version: draft.draft_version, coverage_actions: actions });
    if (nextDraft && !unresolvedRowIds(nextDraft).has(row.row_id)) {
      onDidResolve(row.row_id, nextDraft);
    }
  };
  const saveAction = (action: NonNullable<DraftPatchPayload["coverage_actions"]>[number]) => {
    return saveActions([action]);
  };

  return (
    <fieldset disabled={isSaving} className="min-w-0 border-0 p-0">
    <div className="space-y-4 border-t border-line px-4 py-4">
      <CoverageFactFields value={coverageFactValueFromImport(edited)} onChange={updateFact} />
      <CoveragePeriodFields value={coveragePeriodValueFromImport(edited)} onChange={updatePeriod} />
      <button type="button" disabled={!hasDirtyValues} className="rounded-lg bg-brand px-3 py-2 text-xs font-semibold text-white disabled:opacity-40" onClick={() => void saveActions(editActions)}>담보 내용 저장</button>

      {sourceConfirmActions.length > 0 && <button type="button" disabled={hasDirtyValues || hasDirtyAction} className="ml-2 rounded-lg border border-brand px-3 py-2 text-xs font-semibold text-brand disabled:opacity-40" onClick={() => void saveActions(sourceConfirmActions)}>현재 내용을 원문대로 확인</button>}

      {pages.length > 0 && <button type="button" className="ml-2 rounded-lg border border-line px-3 py-2 text-xs font-semibold text-brand" onClick={() => onViewEvidence(pages)}>원문에서 보기</button>}

      <div className="grid gap-3 border-t border-line pt-4 sm:grid-cols-2">
        <div className="space-y-2">
          <StandardCoveragePicker options={draft.standard_coverages.items} value={standardValue} onChange={setStandardValue} />
          <button type="button" disabled={!standardValue || (!unresolved && standardValue === initialStandardValue)} className="rounded-lg border border-brand px-3 py-2 text-xs font-semibold text-brand disabled:opacity-40" onClick={() => {
            const [standard_category, standard_subcategory, standard_detail_name] = standardValue.split("\u0000");
            void saveAction({ row_id: row.row_id, action: "assign", standard_category, standard_subcategory, standard_detail_name });
          }}>{unresolved && standardValue === initialStandardValue ? "제안 위치 확인 완료" : "표준 위치 저장"}</button>
        </div>
        <div className="space-y-2">
          <label className="grid gap-1 text-xs font-semibold text-ink2">분석 제외 이유<textarea aria-label="분석 제외 이유" maxLength={300} className="min-h-20 rounded-lg border border-line px-3 py-2 text-sm" value={excludeReason} onChange={(event) => setExcludeReason(event.target.value)} /></label>
          <button type="button" disabled={!excludeReason.trim()} className="rounded-lg border border-line px-3 py-2 text-xs font-semibold text-ink2 disabled:opacity-40" onClick={() => void saveAction({ row_id: row.row_id, action: "exclude", reason: excludeReason.trim() })}>분석에서 제외</button>
        </div>
      </div>

      {row.disposition === "intentionally_excluded" && <button type="button" className="rounded-lg border border-line px-3 py-2 text-xs font-semibold text-ink2" onClick={() => void saveAction({ row_id: row.row_id, action: "undo_exclude" })}>분석 제외 취소</button>}

      {duplicateTargets.length > 0 && (
        <div className="grid gap-2 border-t border-line pt-4 sm:grid-cols-2">
          <label className="grid gap-1 text-xs font-semibold text-ink2">중복된 원본 항목<select aria-label="중복된 원본 항목" className="rounded-lg border border-line px-3 py-2 text-sm" value={duplicateTarget} onChange={(event) => setDuplicateTarget(event.target.value)}><option value="">항목을 선택해 주세요</option>{duplicateTargets.map((target) => <option key={target.row_id} value={target.row_id}>{target.raw_name || target.row_id}</option>)}</select></label>
          <label className="grid gap-1 text-xs font-semibold text-ink2">중복 지정 이유<input aria-label="중복 지정 이유" maxLength={300} className="rounded-lg border border-line px-3 py-2 text-sm" value={duplicateReason} onChange={(event) => setDuplicateReason(event.target.value)} /></label>
          <button type="button" disabled={!duplicateTarget || !duplicateReason.trim()} className="rounded-lg border border-line px-3 py-2 text-xs font-semibold text-ink2 disabled:opacity-40" onClick={() => void saveAction({ row_id: row.row_id, action: "duplicate", target_row_id: duplicateTarget, reason: duplicateReason.trim() })}>중복으로 묶기</button>
        </div>
      )}

      {row.review_reason_codes.includes("CARRIER_MANUAL_REVIEW") && <button type="button" className="rounded-lg border border-brand px-3 py-2 text-xs font-semibold text-brand" onClick={() => void saveAction({ row_id: row.row_id, action: "confirm" })}>직접 확인 완료</button>}
    </div>
    </fieldset>
  );
}

export function InsuranceDraftEditor(props: InsuranceDraftEditorProps) {
  const { draft } = props;
  const unresolvedIds = useMemo(() => unresolvedRowIds(draft), [draft]);
  const sortedRows = useMemo(() => stableUnresolvedFirst(draft.coverages, unresolvedIds), [draft.coverages, unresolvedIds]);
  const [filter, setFilter] = useState<CoverageFilter>("all");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [pendingIssueFocus, setPendingIssueFocus] = useState<{ rowId: string; field: string | null } | null>(null);
  const [dirtyRows, setDirtyRows] = useState<Set<string>>(new Set());
  const [addingCoverage, setAddingCoverage] = useState(false);
  const [policyValues, setPolicyValues] = useState(() => policyInitial(draft));
  const summaryRefs = useRef(new Map<string, HTMLButtonElement>());
  const coverageRefs = useRef(new Map<string, HTMLElement>());
  const policyFieldRefs = useRef(new Map<string, HTMLInputElement | HTMLSelectElement>());
  const reviewHeadingRef = useRef<HTMLHeadingElement>(null);
  const sourceMatchRef = useRef<HTMLInputElement>(null);
  const unreadPagesRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setPolicyValues(policyInitial(draft));
    setDirtyRows(new Set());
  }, [draft]);

  useEffect(() => {
    if (!pendingIssueFocus) return;
    const container = coverageRefs.current.get(pendingIssueFocus.rowId);
    if (!container) return;
    const fields = Array.from(
      container.querySelectorAll<HTMLElement>("[data-review-field]")
    );
    const target = pendingIssueFocus.field
      ? fields.find((field) => field.dataset.reviewField === pendingIssueFocus.field)
      : null;
    const fallback = summaryRefs.current.get(pendingIssueFocus.rowId);
    const focusTarget = target ?? fallback;
    focusTarget?.focus();
    focusTarget?.scrollIntoView({ block: "center" });
    setPendingIssueFocus(null);
  }, [expanded, filter, pendingIssueFocus]);

  const initialPolicy = policyInitial(draft);
  const policyChanges = Object.entries(policyValues).flatMap(([field, value]) => {
    if (value === initialPolicy[field as keyof typeof initialPolicy]) return [];
    const normalized = field === "monthly_premium" ? (value === "" ? null : Number(value)) : value || null;
    return [{ field, value: normalized }];
  });
  const hasUnsavedChanges = policyChanges.length > 0;
  const monthlyPremiumNeedsSourceConfirmation =
    draft.policy.monthly_premium.value !== null &&
    draft.policy.monthly_premium.review_reason_codes.some((code) =>
      code === "PREMIUM_SUM_MISMATCH" || code === "PREMIUM_SUM_INCOMPLETE"
    );

  const visibleRows = sortedRows.filter((row) => {
    if (filter === "all") return true;
    if (filter === "unresolved") return unresolvedIds.has(row.row_id);
    if (filter === "excluded") return row.disposition === "intentionally_excluded";
    return !unresolvedIds.has(row.row_id) && row.disposition !== "intentionally_excluded";
  });

  const focusFirstUnresolved = () => {
    const first = sortedRows.find((row) => unresolvedIds.has(row.row_id));
    if (!first) return;
    const summary = summaryRefs.current.get(first.row_id);
    summary?.focus();
    summary?.scrollIntoView({ block: "center" });
  };
  const focusIssue = (issue: ValidationIssue) => {
    if (issue.scope === "policy" && issue.field) {
      const target = policyFieldRefs.current.get(issue.field);
      target?.focus();
      target?.scrollIntoView({ block: "center" });
      return;
    }
    if (!issue.row_id) {
      reviewHeadingRef.current?.focus();
      return;
    }
    const rowId = issue.row_id;
    setFilter("all");
    setExpanded((current) => new Set(current).add(rowId));
    setPendingIssueFocus({ rowId, field: reviewFieldTarget(issue.field) });
  };
  const focusAfterResolution = (currentRowId: string, nextDraft: InsuranceImportDraft) => {
    const nextUnresolvedIds = unresolvedRowIds(nextDraft);
    const currentIndex = sortedRows.findIndex((row) => row.row_id === currentRowId);
    const nextAfterCurrent = sortedRows
      .slice(Math.max(0, currentIndex + 1))
      .find((row) => nextUnresolvedIds.has(row.row_id));
    const next = nextAfterCurrent ?? sortedRows.find((row) => nextUnresolvedIds.has(row.row_id));
    if (next) {
      const summary = summaryRefs.current.get(next.row_id);
      summary?.focus();
      summary?.scrollIntoView({ block: "center" });
      return;
    }
    reviewHeadingRef.current?.focus();
    reviewHeadingRef.current?.scrollIntoView({ block: "start" });
  };

  useEffect(() => {
    if (!props.focusRequest) return;
    if (props.focusRequest.type === "first-unresolved") focusFirstUnresolved();
    if (props.focusRequest.type === "source-match") sourceMatchRef.current?.focus();
    if (props.focusRequest.type === "unread-pages") unreadPagesRef.current?.focus();
  }, [props.focusRequest]);

  const canConfirm =
    props.plannerConfirmedSourceMatch &&
    (!draft.confirmation_requirements.planner_confirmed_unread_pages.required || props.plannerConfirmedUnreadPages) &&
    draft.validation.unresolved_count === 0 &&
    !props.isSaving &&
    !props.hasVersionConflict &&
    !hasUnsavedChanges &&
    !addingCoverage &&
    dirtyRows.size === 0 &&
    (draft.target_insurance_id === null || draft.target_insurance_version !== null);

  const updatePolicy = (field: keyof typeof policyValues) => (event: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    setPolicyValues((current) => ({ ...current, [field]: event.target.value }));
  };

  return (
    <section className="min-w-0 space-y-5" aria-labelledby="draft-editor-heading">
      <div className="rounded-2xl border border-line bg-surface p-5 shadow-card">
        <h2 ref={reviewHeadingRef} tabIndex={-1} id="draft-editor-heading" className="text-lg font-bold text-ink">증권 초안 확인</h2>
        <p className="mt-2 text-sm leading-6 text-ink2">자동으로 정리한 내용이에요. 증권 원문과 같은지 직접 확인해 주세요.</p>
        <p className="mt-3 text-sm font-semibold text-warn-ink">확인이 필요한 항목 {draft.validation.unresolved_count}개</p>
        {draft.validation.unresolved_count > 0 && <button type="button" className="mt-2 text-sm font-semibold text-brand" onClick={focusFirstUnresolved}>첫 확인 항목으로 이동</button>}
        {draft.validation.issues.length > 0 && (
          <ul className="mt-3 space-y-2" aria-label="확인할 내용">
            {draft.validation.issues.map((issue, index) => (
              <li key={`${issue.code}-${issue.row_id ?? "document"}-${issue.field ?? "all"}-${index}`}>
                <button type="button" disabled={props.isSaving} className="w-full rounded-lg border border-line bg-surface2 px-3 py-2 text-left text-sm font-semibold text-ink2 hover:border-brand hover:text-brand disabled:opacity-40" onClick={() => focusIssue(issue)}>
                  {issueLabel(issue, draft)}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <fieldset disabled={props.isSaving} className="rounded-2xl border border-line bg-surface p-5 shadow-card">
        <legend className="px-1 text-base font-bold text-ink">기본정보</legend>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <label className="grid gap-1 text-xs font-semibold text-ink2">보험사 이름<input ref={(node) => { if (node) policyFieldRefs.current.set("carrier_name", node); }} aria-label="보험사 이름" className="rounded-lg border border-line px-3 py-2 text-sm" value={policyValues.carrier_name} onChange={updatePolicy("carrier_name")} /></label>
          <label className="grid gap-1 text-xs font-semibold text-ink2">보험 종류<select ref={(node) => { if (node) policyFieldRefs.current.set("insurance_type", node); }} aria-label="보험 종류" className="rounded-lg border border-line px-3 py-2 text-sm" value={policyValues.insurance_type} onChange={updatePolicy("insurance_type")}><option value="">선택해 주세요</option><option value="life">생명보험</option><option value="loss">손해보험</option></select></label>
          <label className="grid gap-1 text-xs font-semibold text-ink2">상품 이름<input ref={(node) => { if (node) policyFieldRefs.current.set("product_name", node); }} aria-label="상품 이름" className="rounded-lg border border-line px-3 py-2 text-sm" value={policyValues.product_name} onChange={updatePolicy("product_name")} /></label>
          <label className="grid gap-1 text-xs font-semibold text-ink2">계약일<input ref={(node) => { if (node) policyFieldRefs.current.set("contract_date", node); }} aria-label="계약일" type="date" className="rounded-lg border border-line px-3 py-2 text-sm" value={policyValues.contract_date} onChange={updatePolicy("contract_date")} /></label>
          <label className="grid gap-1 text-xs font-semibold text-ink2">만기일<input ref={(node) => { if (node) policyFieldRefs.current.set("expiry_date", node); }} aria-label="만기일" type="date" className="rounded-lg border border-line px-3 py-2 text-sm" value={policyValues.expiry_date} onChange={updatePolicy("expiry_date")} /></label>
          <label className="grid gap-1 text-xs font-semibold text-ink2">월 보험료<input ref={(node) => { if (node) policyFieldRefs.current.set("monthly_premium", node); }} aria-label="월 보험료" type="number" min="0" className="rounded-lg border border-line px-3 py-2 text-sm" value={policyValues.monthly_premium} onChange={updatePolicy("monthly_premium")} /></label>
        </div>
        <div className="mt-3 flex flex-wrap gap-2" aria-label="기본정보 원문 위치">
          {([
            ["보험사 이름", draft.policy.carrier_name.evidence_line_ids],
            ["보험 종류", draft.policy.insurance_type.evidence_line_ids],
            ["상품 이름", draft.policy.product_name.evidence_line_ids],
            ["계약일", draft.policy.contract_date.evidence_line_ids],
            ["만기일", draft.policy.expiry_date.evidence_line_ids],
            ["월 보험료", draft.policy.monthly_premium.evidence_line_ids],
          ] as const).map(([label, lineIds]) => {
            const pages = evidencePages([...lineIds]);
            return pages.length > 0 ? <button key={label} type="button" className="rounded-lg border border-line px-2.5 py-1.5 text-xs font-semibold text-brand" onClick={() => props.onViewEvidence(pages)}>{label} 원문에서 보기</button> : null;
          })}
        </div>
        <button type="button" disabled={!hasUnsavedChanges || props.isSaving} className="mt-4 rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-40" onClick={() => void props.onSave({ draft_version: draft.draft_version, policy_changes: policyChanges })}>기본정보 저장</button>
        {monthlyPremiumNeedsSourceConfirmation && <button type="button" disabled={hasUnsavedChanges || props.isSaving} className="ml-2 mt-4 rounded-lg border border-brand px-4 py-2 text-sm font-semibold text-brand disabled:opacity-40" onClick={() => void props.onSave({ draft_version: draft.draft_version, policy_changes: [{ field: "monthly_premium", value: draft.policy.monthly_premium.value }] })}>월 보험료 원문 확인 완료</button>}
      </fieldset>

      <section className="rounded-2xl border border-line bg-surface p-5 shadow-card" aria-labelledby="coverage-heading">
        <h3 id="coverage-heading" className="text-base font-bold text-ink">담보</h3>
        <div className="mt-3 flex flex-wrap gap-2" aria-label="담보 보기 선택">
          {([ ["unresolved", "확인 필요"], ["all", "전체"], ["confirmed", "확인 완료"], ["excluded", "분석 제외"] ] as const).map(([value, label]) => <button key={value} type="button" disabled={props.isSaving} aria-pressed={filter === value} className="rounded-full border border-line px-3 py-1.5 text-xs font-semibold text-ink2 disabled:opacity-40" onClick={() => setFilter(value)}>{label}</button>)}
        </div>
        <div className="mt-4 space-y-2">
          {visibleRows.map((row) => {
            const open = expanded.has(row.row_id);
            return (
              <article ref={(node) => { if (node) coverageRefs.current.set(row.row_id, node); else coverageRefs.current.delete(row.row_id); }} key={row.row_id} className="rounded-xl border border-line bg-surface2">
                <button ref={(node) => { if (node) summaryRefs.current.set(row.row_id, node); else summaryRefs.current.delete(row.row_id); }} type="button" disabled={props.isSaving} aria-expanded={open} className="flex w-full px-4 py-3 disabled:opacity-60" onClick={() => setExpanded((current) => { const next = new Set(current); if (next.has(row.row_id)) next.delete(row.row_id); else next.add(row.row_id); return next; })}>
                  <CoverageRowSummary row={row} unresolved={unresolvedIds.has(row.row_id)} />
                </button>
                {open && <CoverageRowDetails draft={draft} row={row} unresolved={unresolvedIds.has(row.row_id)} isSaving={props.isSaving} onSave={props.onSave} onViewEvidence={props.onViewEvidence} onDidResolve={focusAfterResolution} onDirtyChange={(dirty) => setDirtyRows((current) => { if (current.has(row.row_id) === dirty) return current; const next = new Set(current); if (dirty) next.add(row.row_id); else next.delete(row.row_id); return next; })} />}
              </article>
            );
          })}
        </div>
        <ManualCoverageAddForm
          draft={draft}
          disabled={props.isSaving}
          onSave={props.onSave}
          onDirtyChange={setAddingCoverage}
        />
      </section>

      <div className="sticky bottom-4 rounded-2xl border border-line bg-surface p-5 shadow-card">
        <label className="flex items-start gap-2 text-sm font-semibold text-ink"><input ref={sourceMatchRef} type="checkbox" disabled={props.isSaving} checked={props.plannerConfirmedSourceMatch} onChange={(event) => props.onSourceMatchChange(event.target.checked)} />기본정보와 전체 담보가 증권 원문과 같은지 확인했습니다</label>
        {draft.confirmation_requirements.planner_confirmed_unread_pages.required && <label className="mt-3 flex items-start gap-2 text-sm font-semibold text-ink"><input ref={unreadPagesRef} type="checkbox" disabled={props.isSaving} checked={props.plannerConfirmedUnreadPages} onChange={(event) => props.onUnreadPagesChange(event.target.checked)} />읽기 어려운 페이지도 원문에서 직접 확인했습니다</label>}
        <button type="button" disabled={!canConfirm} className="mt-4 w-full rounded-xl bg-brand px-4 py-3 text-sm font-bold text-white disabled:opacity-40" onClick={() => void props.onConfirm()}>검토 완료하고 분석에 반영</button>
      </div>
    </section>
  );
}
