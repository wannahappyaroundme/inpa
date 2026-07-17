"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  CoverageFactFields,
  CoveragePeriodFields,
  StandardCoveragePicker,
  type CoverageFactValue,
  type CoveragePeriodValue,
} from "@/components/insurance-draft-editor";
import {
  ApiError,
  confirmManualInsurance,
  createManualCoverage,
  deleteManualCoverage,
  excludeManualInsurance,
  getManualInsuranceReview,
  patchManualCoverage,
  patchManualInsurance,
  type ManualCoverageCreatePayload,
  type ManualCoverageItem,
  type ManualInsuranceConfirmPayload,
  type ManualInsuranceReviewBundle,
  type StandardCoverageOption,
} from "@/lib/api";

const EMPTY_FACTS: CoverageFactValue = {
  raw_name: "",
  assurance_amount: null,
  premium: null,
};

const EMPTY_PERIODS: CoveragePeriodValue = {
  is_renewal: null,
  renewal_period: null,
  payment_period: null,
  payment_period_unit: null,
  warranty_period: null,
  warranty_period_unit: null,
};

function standardValue(row: ManualCoverageItem): string {
  if (!row.standard_category || !row.standard_subcategory || !row.standard_detail_name) return "";
  return `${row.standard_category}\u0000${row.standard_subcategory}\u0000${row.standard_detail_name}`;
}

function factsFrom(row?: ManualCoverageItem): CoverageFactValue {
  if (!row) return EMPTY_FACTS;
  return {
    raw_name: row.raw_name,
    assurance_amount: row.assurance_amount,
    premium: row.premium,
  };
}

function periodsFrom(row?: ManualCoverageItem): CoveragePeriodValue {
  if (!row) return EMPTY_PERIODS;
  return {
    is_renewal: row.is_renewal,
    renewal_period: row.renewal_period,
    payment_period: row.payment_period,
    payment_period_unit: row.payment_period_unit,
    warranty_period: row.warranty_period,
    warranty_period_unit: row.warranty_period_unit,
  };
}

function coverageValidation(
  facts: CoverageFactValue,
  periods: CoveragePeriodValue,
  standard: string,
  contractDate: string | null
): string[] {
  const errors: string[] = [];
  if (!facts.raw_name?.trim()) errors.push("담보 이름을 입력해 주세요.");
  if (facts.assurance_amount !== null && facts.assurance_amount < 0) {
    errors.push("보장 금액은 0원 이상으로 입력해 주세요.");
  } else if (facts.assurance_amount !== null && !Number.isSafeInteger(facts.assurance_amount)) {
    errors.push("보장 금액은 0 이상의 정수로 입력해 주세요.");
  }
  if (facts.premium !== null && facts.premium < 0) {
    errors.push("담보 보험료는 0원 이상으로 입력해 주세요.");
  } else if (facts.premium !== null && !Number.isSafeInteger(facts.premium)) {
    errors.push("담보 보험료는 0 이상의 정수로 입력해 주세요.");
  }
  if (periods.is_renewal === null) errors.push("갱신 여부를 선택해 주세요.");
  if (periods.is_renewal === true && (
    periods.renewal_period === null ||
    !Number.isSafeInteger(periods.renewal_period) ||
    periods.renewal_period < 1
  )) {
    errors.push("갱신 보험은 갱신 주기를 입력해 주세요.");
  }
  if (periods.is_renewal === true && periods.payment_period_unit === "age") {
    errors.push("갱신 보험의 납입 기간 기준은 년 또는 종신으로 선택해 주세요.");
  }
  if (periods.is_renewal === false && periods.renewal_period !== null) {
    errors.push("비갱신 보험은 갱신 주기를 비워 주세요.");
  }
  for (const [label, period, unit] of [
    ["납입", periods.payment_period, periods.payment_period_unit],
    ["보장", periods.warranty_period, periods.warranty_period_unit],
  ] as const) {
    if (!unit) errors.push(`${label} 기간 기준을 선택해 주세요.`);
    if (unit === "lifetime" && period !== null) errors.push(`${label} 기간을 종신으로 선택하면 숫자는 비워 주세요.`);
    if (unit && unit !== "lifetime" && (period === null || period < 1)) {
      errors.push(`${label} 기간을 1 이상으로 입력해 주세요.`);
    } else if (unit && unit !== "lifetime" && period !== null && !Number.isSafeInteger(period)) {
      errors.push(`${label} 기간은 1 이상의 정수로 입력해 주세요.`);
    }
  }
  if (
    periods.is_renewal === false &&
    facts.premium !== null &&
    periods.payment_period_unit === "age" &&
    !contractDate
  ) {
    errors.push("나이 기준 납입 기간은 계약일을 먼저 입력해 주세요.");
  }
  if (
    periods.payment_period !== null &&
    periods.warranty_period !== null &&
    periods.payment_period_unit === periods.warranty_period_unit &&
    (periods.payment_period_unit === "years" || periods.payment_period_unit === "age") &&
    periods.payment_period > periods.warranty_period
  ) {
    errors.push("납입 기간은 보장 기간보다 길 수 없어요.");
  }
  if (!standard) errors.push("표준 위치를 선택해 주세요.");
  return errors;
}

function ManualCoverageForm({
  row,
  options,
  disabled,
  resetKey,
  onSave,
  onDelete,
  onDirtyChange,
  contractDate,
}: {
  row?: ManualCoverageItem;
  options: StandardCoverageOption[];
  disabled: boolean;
  resetKey?: number;
  onSave: (payload: Omit<ManualCoverageCreatePayload, "data_version">) => Promise<void>;
  onDelete?: () => Promise<void>;
  onDirtyChange?: (dirty: boolean) => void;
  contractDate: string | null;
}) {
  const [expanded, setExpanded] = useState(!row);
  const [facts, setFacts] = useState<CoverageFactValue>(() => factsFrom(row));
  const [periods, setPeriods] = useState<CoveragePeriodValue>(() => periodsFrom(row));
  const [standard, setStandard] = useState(() => row ? standardValue(row) : "");
  const dirtyCallbackRef = useRef(onDirtyChange);

  useEffect(() => {
    dirtyCallbackRef.current = onDirtyChange;
  }, [onDirtyChange]);

  useEffect(() => {
    setFacts(factsFrom(row));
    setPeriods(periodsFrom(row));
    setStandard(row ? standardValue(row) : "");
    if (!row) setExpanded(true);
  }, [resetKey, row]);

  const initialFacts = factsFrom(row);
  const initialPeriods = periodsFrom(row);
  const initialStandard = row ? standardValue(row) : "";
  const dirty =
    JSON.stringify(facts) !== JSON.stringify(initialFacts) ||
    JSON.stringify(periods) !== JSON.stringify(initialPeriods) ||
    standard !== initialStandard;

  useEffect(() => {
    dirtyCallbackRef.current?.(dirty);
  }, [dirty]);

  useEffect(() => () => dirtyCallbackRef.current?.(false), []);

  const validationErrors = coverageValidation(facts, periods, standard, contractDate);
  const complete = validationErrors.length === 0;

  const submit = async () => {
    if (!complete) return;
    const [standard_category, standard_subcategory, standard_detail_name] = standard.split("\u0000");
    await onSave({
      raw_name: facts.raw_name!.trim(),
      assurance_amount: facts.assurance_amount,
      premium: facts.premium,
      is_renewal: periods.is_renewal,
      renewal_period: periods.renewal_period,
      payment_period: periods.payment_period,
      payment_period_unit: periods.payment_period_unit,
      warranty_period: periods.warranty_period,
      warranty_period_unit: periods.warranty_period_unit,
      standard_category,
      standard_subcategory,
      standard_detail_name,
    });
    if (row) setExpanded(false);
  };

  return (
    <div
      data-testid={row ? `manual-coverage-${row.id}` : "manual-coverage-new"}
      className="rounded-xl border border-line bg-surface p-3"
    >
      {row && (
        <div className="flex min-w-0 items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate text-[13px] font-bold text-ink">{row.raw_name || "담보 이름 확인"}</p>
            <p className="mt-0.5 text-[11px] text-ink3">
              {row.standard_detail_name ?? "표준 위치 확인"} · {row.assurance_amount?.toLocaleString("ko-KR") ?? "-"}원
            </p>
          </div>
          <button
            type="button"
            disabled={disabled}
            onClick={() => setExpanded((value) => !value)}
            className="shrink-0 rounded-lg border border-line px-3 py-1.5 text-[12px] font-semibold text-ink2 disabled:opacity-50"
          >
            {expanded ? "수정 닫기" : "담보 수정"}
          </button>
        </div>
      )}

      {expanded && (
        <fieldset disabled={disabled} className="mt-3 min-w-0 space-y-3 border-0 p-0 disabled:opacity-60">
          <CoverageFactFields
            value={facts}
            onChange={(field, value) => setFacts((current) => ({ ...current, [field]: value }))}
          />
          <CoveragePeriodFields
            value={periods}
            onChange={(field, value) => setPeriods((current) => ({ ...current, [field]: value }))}
          />
          <StandardCoveragePicker options={options} value={standard} onChange={setStandard} />
          {validationErrors.length > 0 && (
            <ul className="space-y-1 text-[11px] text-danger" aria-live="polite">
              {validationErrors.map((message) => <li key={message} role="alert">{message}</li>)}
            </ul>
          )}
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={!complete || (row ? !dirty : false)}
              onClick={() => void submit()}
              className="rounded-lg bg-brand px-3 py-2 text-[12px] font-bold text-white disabled:opacity-40"
            >
              {row ? "담보 저장" : "담보 추가"}
            </button>
            {row && onDelete && (
              <button
                type="button"
                onClick={() => void onDelete()}
                className="rounded-lg border border-line px-3 py-2 text-[12px] font-semibold text-ink2"
              >
                담보 삭제
              </button>
            )}
          </div>
        </fieldset>
      )}
    </div>
  );
}

function operationError(error: unknown): string {
  return error instanceof ApiError
    ? error.message
    : "연결이 잠시 끊겼어요. 같은 요청을 안전하게 다시 보낼 수 있어요.";
}

interface ManualPolicyForm {
  name: string;
  insuranceType: string;
  portfolioType: string;
  contractorName: string;
  insuredName: string;
  isSameInsured: "" | "true" | "false";
  contractDate: string;
  expiryDate: string;
  monthlyPremium: string;
}

function policyFormFrom(insurance: ManualInsuranceReviewBundle["insurance"]): ManualPolicyForm {
  return {
    name: insurance.name ?? "",
    insuranceType: String(insurance.insurance_type),
    portfolioType: String(insurance.portfolio_type),
    contractorName: insurance.contractor_name ?? "",
    insuredName: insurance.insured_name ?? "",
    isSameInsured: insurance.is_same_insured === null ? "" : String(insurance.is_same_insured) as "true" | "false",
    contractDate: insurance.contract_date ?? "",
    expiryDate: insurance.expiry_date ?? "",
    monthlyPremium: insurance.monthly_premiums === null ? "" : String(insurance.monthly_premiums),
  };
}

const EMPTY_POLICY_FORM: ManualPolicyForm = {
  name: "",
  insuranceType: "",
  portfolioType: "",
  contractorName: "",
  insuredName: "",
  isSameInsured: "",
  contractDate: "",
  expiryDate: "",
  monthlyPremium: "",
};

function requiredInsuranceChoice(value: string): 1 | 2 {
  if (value === "1") return 1;
  if (value === "2") return 2;
  throw new Error("보험 종류 또는 구분을 먼저 선택해 주세요.");
}

function validIsoDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

function policyValidation(form: ManualPolicyForm): string[] {
  const errors: string[] = [];
  if (!["1", "2"].includes(form.insuranceType)) errors.push("보험 종류를 선택해 주세요.");
  if (!["1", "2"].includes(form.portfolioType)) errors.push("보유 또는 제안을 선택해 주세요.");
  if (form.contractDate && !validIsoDate(form.contractDate)) errors.push("계약일을 다시 확인해 주세요.");
  if (form.expiryDate && !validIsoDate(form.expiryDate)) errors.push("만기일을 다시 확인해 주세요.");
  if (validIsoDate(form.contractDate) && validIsoDate(form.expiryDate) && form.contractDate > form.expiryDate) {
    errors.push("계약일은 만기일보다 늦을 수 없어요.");
  }
  if (form.monthlyPremium !== "" && Number(form.monthlyPremium) < 0) {
    errors.push("월 보험료는 0원 이상으로 입력해 주세요.");
  } else if (form.monthlyPremium !== "" && !Number.isSafeInteger(Number(form.monthlyPremium))) {
    errors.push("월 보험료는 0 이상의 정수로 입력해 주세요.");
  }
  return errors;
}

export function ManualInsuranceReview({
  customerId,
  insuranceId,
  onChanged,
  onCompleted,
}: {
  customerId: number;
  insuranceId: number;
  onChanged?: () => void;
  onCompleted?: () => void;
}) {
  const [review, setReview] = useState<ManualInsuranceReviewBundle | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadStatus, setLoadStatus] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [excludeReason, setExcludeReason] = useState("");
  const [pendingConfirm, setPendingConfirm] = useState<{
    payload: ManualInsuranceConfirmPayload;
    key: string;
  } | null>(null);
  const [newCoverageReset, setNewCoverageReset] = useState(0);
  const [dirtyRows, setDirtyRows] = useState<Set<number | "new">>(new Set());
  const [policyForm, setPolicyForm] = useState<ManualPolicyForm>(EMPTY_POLICY_FORM);
  const operationRef = useRef(false);
  const mountedRef = useRef(false);
  const loadSequenceRef = useRef(0);
  const identityKey = `${customerId}:${insuranceId}`;
  const identityRef = useRef({ key: identityKey, generation: 1 });
  if (identityRef.current.key !== identityKey) {
    identityRef.current = {
      key: identityKey,
      generation: identityRef.current.generation + 1,
    };
  }
  const isActive = useCallback((generation: number) => (
    mountedRef.current && identityRef.current.generation === generation
  ), []);

  const load = useCallback(async () => {
    const generation = identityRef.current.generation;
    const sequence = ++loadSequenceRef.current;
    setLoading(true);
    setError(null);
    setLoadStatus(null);
    try {
      const next = await getManualInsuranceReview(customerId, insuranceId);
      if (!isActive(generation) || sequence !== loadSequenceRef.current) return;
      setReview(next);
      setPolicyForm(policyFormFrom(next.insurance));
      setConflict(false);
      setConfirmed(false);
      setPendingConfirm(null);
      setDirtyRows(new Set());
    } catch (nextError) {
      if (!isActive(generation) || sequence !== loadSequenceRef.current) return;
      const status = nextError instanceof ApiError ? nextError.status : 0;
      setLoadStatus(status);
      setError(status === 404
        ? "보험 기록을 찾을 수 없어요."
        : nextError instanceof Error ? nextError.message : "보험 내용을 불러오지 못했어요.");
    } finally {
      if (isActive(generation) && sequence === loadSequenceRef.current) setLoading(false);
    }
  }, [customerId, insuranceId, isActive]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      identityRef.current.generation += 1;
    };
  }, []);

  useEffect(() => {
    operationRef.current = false;
    setSaving(false);
    setReview(null);
    setPolicyForm(EMPTY_POLICY_FORM);
    setPendingConfirm(null);
    setDirtyRows(new Set());
    void load();
  }, [identityKey, load]);

  const run = async (operation: (generation: number) => Promise<void>) => {
    if (operationRef.current) return;
    const generation = identityRef.current.generation;
    operationRef.current = true;
    setSaving(true);
    setError(null);
    try {
      await operation(generation);
    } catch (nextError) {
      if (!isActive(generation)) return;
      if (nextError instanceof ApiError && nextError.code === "INSURANCE_VERSION_CHANGED") {
        setConflict(true);
        setError("다른 화면에서 보험 내용이 바뀌었어요. 최신 내용을 다시 불러와 주세요.");
      } else {
        setError(operationError(nextError));
      }
    } finally {
      if (isActive(generation)) {
        operationRef.current = false;
        setSaving(false);
      }
    }
  };

  const setDirty = useCallback((id: number | "new", dirty: boolean) => {
    setDirtyRows((current) => {
      const next = new Set(current);
      if (dirty) next.add(id);
      else next.delete(id);
      return next;
    });
  }, []);

  if (loading) return <p role="status" className="py-10 text-center text-[13px] text-ink3">보험 내용을 불러오는 중이에요.</p>;
  if (!review) {
    return (
      <div className="py-8 text-center">
        <p role="alert" className="text-[13px] text-danger">{error ?? "보험 내용을 불러오지 못했어요."}</p>
        {loadStatus !== 404 && <button type="button" onClick={() => void load()} className="mt-3 text-[13px] font-semibold text-brand">다시 불러오기</button>}
      </div>
    );
  }

  const terminal = !["draft", "legacy_review_required"].includes(review.review_status);
  const policy = review.insurance;
  const initialPolicyForm = policyFormFrom(policy);
  const policyDirty = JSON.stringify(policyForm) !== JSON.stringify(initialPolicyForm);
  const policyErrors = policyValidation(policyForm);
  const locked = saving || conflict || terminal;
  const updatePolicy = <K extends keyof ManualPolicyForm>(field: K, value: ManualPolicyForm[K]) => {
    setPolicyForm((current) => ({ ...current, [field]: value }));
    setConfirmed(false);
  };

  const savePolicy = () => run(async (generation) => {
    const next = await patchManualInsurance(customerId, insuranceId, {
      data_version: review.data_version,
      name: policyForm.name.trim() || null,
      insurance_type: requiredInsuranceChoice(policyForm.insuranceType),
      portfolio_type: requiredInsuranceChoice(policyForm.portfolioType),
      contractor_name: policyForm.contractorName.trim() || null,
      insured_name: policyForm.insuredName.trim() || null,
      is_same_insured: policyForm.isSameInsured === "" ? null : policyForm.isSameInsured === "true",
      contract_date: policyForm.contractDate || null,
      expiry_date: policyForm.expiryDate || null,
      monthly_premiums: policyForm.monthlyPremium === "" ? null : Number(policyForm.monthlyPremium),
    });
    if (!isActive(generation)) return;
    setReview((current) => current ? {
      ...current,
      data_version: next.data_version,
      insurance: next,
      review_status: next.review_status,
      analysis_included: next.analysis_included,
    } : current);
    setPolicyForm(policyFormFrom(next));
    setConfirmed(false);
  });

  const saveNewCoverage = (payload: Omit<ManualCoverageCreatePayload, "data_version">) => run(async (generation) => {
    const response = await createManualCoverage(customerId, insuranceId, {
      data_version: review.data_version,
      ...payload,
    });
    if (!isActive(generation)) return;
    const { data_version, ...row } = response;
    setReview((current) => current ? {
      ...current,
      data_version,
      insurance: { ...current.insurance, data_version },
      coverages: [...current.coverages, row],
    } : current);
    setNewCoverageReset((value) => value + 1);
    setConfirmed(false);
  });

  const saveCoverage = (row: ManualCoverageItem, payload: Omit<ManualCoverageCreatePayload, "data_version">) => run(async (generation) => {
    const response = await patchManualCoverage(customerId, insuranceId, row.id, {
      data_version: review.data_version,
      ...payload,
    });
    if (!isActive(generation)) return;
    const { data_version, ...nextRow } = response;
    setReview((current) => current ? {
      ...current,
      data_version,
      insurance: { ...current.insurance, data_version },
      coverages: current.coverages.map((item) => item.id === row.id ? nextRow : item),
    } : current);
    setConfirmed(false);
  });

  const removeCoverage = (row: ManualCoverageItem) => run(async (generation) => {
    const response = await deleteManualCoverage(customerId, insuranceId, row.id, review.data_version);
    if (!isActive(generation)) return;
    setReview((current) => current ? {
      ...current,
      data_version: response.data_version,
      insurance: { ...current.insurance, data_version: response.data_version },
      coverages: current.coverages.filter((item) => item.id !== row.id),
    } : current);
    setConfirmed(false);
  });

  const sendConfirmation = (pending?: { payload: ManualInsuranceConfirmPayload; key: string }) => run(async (generation) => {
    const command = pending ?? {
      payload: { data_version: review.data_version, planner_confirmed_contents: true as const },
      key: crypto.randomUUID(),
    };
    try {
      await confirmManualInsurance(customerId, insuranceId, command.payload, command.key);
    } catch (nextError) {
      if (isActive(generation) && !(nextError instanceof ApiError)) setPendingConfirm(command);
      throw nextError;
    }
    if (!isActive(generation)) return;
    setPendingConfirm(null);
    onChanged?.();
    onCompleted?.();
  });

  const exclude = () => run(async (generation) => {
    await excludeManualInsurance(customerId, insuranceId, {
      data_version: review.data_version,
      reason: excludeReason.trim(),
    });
    if (!isActive(generation)) return;
    onChanged?.();
    onCompleted?.();
  });

  return (
    <div className="space-y-4">
      {review.review_status === "legacy_review_required" && (
        <div role="status" className="rounded-xl border border-amber-200 bg-amber-50 px-3.5 py-3 text-[12px] leading-5 text-amber-900">
          <p className="font-semibold">이전에 등록한 자료라 증권 원본은 보관하지 않았어요.</p>
          <p>보험 기본정보와 담보를 직접 확인한 뒤 분석에 반영해 주세요.</p>
        </div>
      )}

      {terminal && (
        <div role="status" className="rounded-xl border border-line bg-surface2 px-3.5 py-3 text-[13px] text-ink2">
          {review.review_status === "confirmed" && "확인한 보험이며 분석에 포함돼요."}
          {review.review_status === "excluded" && "분석에서 뺀 보험이에요. 기록은 그대로 보관돼요."}
          {review.review_status === "superseded" && "새 자료로 교체된 보험이에요."}
        </div>
      )}

      <section className="rounded-xl border border-line bg-surface2 p-3.5">
        <div className="flex items-center justify-between gap-3">
          <h3 className="text-[13px] font-bold text-ink">보험 기본정보</h3>
        </div>
        <fieldset disabled={locked} className="mt-3 grid gap-3 border-0 p-0 sm:grid-cols-2 disabled:opacity-60">
          <label className="grid gap-1 text-[12px] font-semibold text-ink2">
            상품명
            <input aria-label="검토 상품명" maxLength={100} value={policyForm.name} onChange={(event) => updatePolicy("name", event.target.value)} className="rounded-lg border border-line bg-surface px-3 py-2 text-[13px]" />
          </label>
          <label className="grid gap-1 text-[12px] font-semibold text-ink2">
            보험 종류
            <select aria-label="검토 보험 종류" value={policyForm.insuranceType} onChange={(event) => updatePolicy("insuranceType", event.target.value)} className="rounded-lg border border-line bg-surface px-3 py-2 text-[13px]"><option value="">선택해 주세요</option><option value="1">생명보험</option><option value="2">손해보험</option></select>
          </label>
          <label className="grid gap-1 text-[12px] font-semibold text-ink2">
            구분
            <select aria-label="검토 구분" value={policyForm.portfolioType} onChange={(event) => updatePolicy("portfolioType", event.target.value)} className="rounded-lg border border-line bg-surface px-3 py-2 text-[13px]"><option value="1">보유(기존 가입)</option><option value="2">제안(갈아타기)</option></select>
          </label>
          <label className="grid gap-1 text-[12px] font-semibold text-ink2">
            계약자
            <input aria-label="검토 계약자" maxLength={10} value={policyForm.contractorName} onChange={(event) => updatePolicy("contractorName", event.target.value)} className="rounded-lg border border-line bg-surface px-3 py-2 text-[13px]" />
          </label>
          <label className="grid gap-1 text-[12px] font-semibold text-ink2">
            피보험자
            <input aria-label="검토 피보험자" maxLength={10} value={policyForm.insuredName} onChange={(event) => updatePolicy("insuredName", event.target.value)} className="rounded-lg border border-line bg-surface px-3 py-2 text-[13px]" />
          </label>
          <label className="grid gap-1 text-[12px] font-semibold text-ink2">
            계약자와 피보험자 관계
            <select aria-label="계약자와 피보험자 관계" value={policyForm.isSameInsured} onChange={(event) => updatePolicy("isSameInsured", event.target.value as ManualPolicyForm["isSameInsured"])} className="rounded-lg border border-line bg-surface px-3 py-2 text-[13px]"><option value="">확인 필요</option><option value="true">같음</option><option value="false">다름</option></select>
          </label>
          <label className="grid gap-1 text-[12px] font-semibold text-ink2">
            계약일
            <input aria-label="검토 계약일" type="date" value={policyForm.contractDate} onChange={(event) => updatePolicy("contractDate", event.target.value)} className="rounded-lg border border-line bg-surface px-3 py-2 text-[13px]" />
          </label>
          <label className="grid gap-1 text-[12px] font-semibold text-ink2">
            만기일
            <input aria-label="검토 만기일" type="date" value={policyForm.expiryDate} onChange={(event) => updatePolicy("expiryDate", event.target.value)} className="rounded-lg border border-line bg-surface px-3 py-2 text-[13px]" />
          </label>
          <label className="grid gap-1 text-[12px] font-semibold text-ink2">
            월 보험료
            <input aria-label="검토 월 보험료" type="number" min="0" value={policyForm.monthlyPremium} onChange={(event) => updatePolicy("monthlyPremium", event.target.value)} className="rounded-lg border border-line bg-surface px-3 py-2 text-[13px]" />
          </label>
        </fieldset>
        {policyErrors.length > 0 && (
          <ul className="mt-3 space-y-1 text-[11px] text-danger" aria-live="polite">
            {policyErrors.map((message) => <li key={message} role="alert">{message}</li>)}
          </ul>
        )}
        {!terminal && (
          <button type="button" disabled={locked || !policyDirty || policyErrors.length > 0} onClick={() => void savePolicy()} className="mt-3 rounded-lg border border-brand px-3 py-2 text-[12px] font-semibold text-brand disabled:opacity-40">보험 기본정보 저장</button>
        )}
      </section>

      <section>
        <div className="mb-2 flex items-center justify-between gap-3">
          <h3 className="text-[13px] font-bold text-ink">담보 {review.coverages.length}건</h3>
          {!terminal && <span className="text-[11px] text-ink3">마지막으로 저장된 내용을 기준으로 확인해요.</span>}
        </div>
        <div className="max-h-[55dvh] space-y-2 overflow-y-auto pr-1">
          {review.coverages.length === 0 && (
            <p role="status" className="rounded-xl border border-dashed border-line px-3 py-5 text-center text-[12px] text-ink3">담보를 한 개 이상 입력하면 최종 확인할 수 있어요.</p>
          )}
          {review.coverages.map((row) => (
            <ManualCoverageForm
              key={`${row.id}:${row.updated_at}`}
              row={row}
              options={review.standard_coverages.items}
              disabled={locked}
              contractDate={policy.contract_date}
              onDirtyChange={(dirty) => setDirty(row.id, dirty)}
              onSave={(payload) => saveCoverage(row, payload)}
              onDelete={() => removeCoverage(row)}
            />
          ))}
          {!terminal && (
            <ManualCoverageForm
              key={`new:${newCoverageReset}`}
              resetKey={newCoverageReset}
              options={review.standard_coverages.items}
              disabled={locked}
              contractDate={policy.contract_date}
              onDirtyChange={(dirty) => setDirty("new", dirty)}
              onSave={saveNewCoverage}
            />
          )}
        </div>
      </section>

      {error && <p role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-3.5 py-3 text-[12px] text-rose-700">{error}</p>}
      {conflict && (
        <button type="button" onClick={() => void load()} className="rounded-lg border border-brand px-3 py-2 text-[12px] font-semibold text-brand">최신 내용 다시 불러오기</button>
      )}
      {pendingConfirm && !conflict && (
        <button type="button" disabled={saving} onClick={() => void sendConfirmation(pendingConfirm)} className="rounded-lg border border-brand px-3 py-2 text-[12px] font-semibold text-brand disabled:opacity-50">같은 확인 요청 다시 보내기</button>
      )}

      {!terminal && (
        <section className="rounded-xl border border-line bg-surface2 p-3.5">
          <label className="flex items-start gap-2 text-[12px] font-semibold leading-5 text-ink2">
            <input type="checkbox" checked={confirmed} disabled={locked || policyDirty || policyErrors.length > 0} onChange={(event) => setConfirmed(event.target.checked)} className="mt-1" />
            보험 기본정보와 담보 내용을 직접 확인했습니다
          </label>
          <button
            type="button"
            disabled={locked || policyDirty || policyErrors.length > 0 || !confirmed || review.coverages.length === 0 || dirtyRows.size > 0 || Boolean(pendingConfirm)}
            onClick={() => void sendConfirmation()}
            className="mt-3 w-full rounded-xl bg-brand px-4 py-2.5 text-[13px] font-bold text-white disabled:opacity-40"
          >
            {saving ? "저장 중…" : "확인한 내용을 분석에 반영"}
          </button>
          <label className="mt-4 grid gap-1 text-[12px] font-semibold text-ink2">
            분석에서 빼는 이유
            <textarea value={excludeReason} onChange={(event) => setExcludeReason(event.target.value)} maxLength={500} className="min-h-16 rounded-lg border border-line bg-surface px-3 py-2 text-[13px]" />
          </label>
          <button type="button" disabled={locked || policyDirty || policyErrors.length > 0 || !excludeReason.trim() || dirtyRows.size > 0} onClick={() => void exclude()} className="mt-2 rounded-lg border border-line px-3 py-2 text-[12px] font-semibold text-ink2 disabled:opacity-40">이 보험을 분석에서 빼기</button>
        </section>
      )}
    </div>
  );
}
