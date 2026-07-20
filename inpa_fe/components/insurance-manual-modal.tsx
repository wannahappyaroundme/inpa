"use client";

// 보험 수기 등록 모달 — OCR 불가(스캔/이미지/키없음) 폴백 + 갈아타기 제안 입력.
// customer-create-modal 시트형 패턴. 담보 상세는 없이 기본정보만 → 환수레이더·요약 반영.

import { useState, useCallback, useEffect, useId, useRef } from "react";
import { createManualInsurance, ApiError } from "@/lib/api";
import { ManualInsuranceReview } from "@/components/insurance-manual-review";

export function InsuranceManualModal({
  customerId,
  onClose,
  onChanged,
  initialInsuranceId,
  defaultPortfolioType = 1,
}: {
  customerId: number;
  onClose: () => void;
  onChanged?: () => void;
  initialInsuranceId?: number | null;
  defaultPortfolioType?: 1 | 2;   // 1=보유 / 2=제안 (호출처에서 지정, 비교분석=2)
}) {
  const [insuranceId, setInsuranceId] = useState<number | null>(initialInsuranceId ?? null);
  const [name, setName] = useState("");
  const [insuranceType, setInsuranceType] = useState<1 | 2>(2); // 손해보험 기본
  const [portfolioType, setPortfolioType] = useState<1 | 2>(defaultPortfolioType);
  const [contractor, setContractor] = useState("");
  const [insured, setInsured] = useState("");
  const [premium, setPremium] = useState("");
  const [contractDate, setContractDate] = useState("");
  const [expiryDate, setExpiryDate] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const openerRef = useRef<HTMLElement | null>(null);
  const identityKey = `${customerId}:${initialInsuranceId ?? "new"}`;
  const lifecycleRef = useRef({ key: identityKey, generation: 1, mounted: false });
  if (lifecycleRef.current.key !== identityKey) {
    lifecycleRef.current.key = identityKey;
    lifecycleRef.current.generation += 1;
  }

  useEffect(() => {
    lifecycleRef.current.mounted = true;
    return () => {
      lifecycleRef.current.mounted = false;
      lifecycleRef.current.generation += 1;
    };
  }, []);

  useEffect(() => {
    setInsuranceId(initialInsuranceId ?? null);
    setSaving(false);
    setError(null);
  }, [identityKey, initialInsuranceId]);

  useEffect(() => {
    openerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const dialog = dialogRef.current;
    const focusable = dialog?.querySelector<HTMLElement>("button, input, select, textarea, [tabindex]:not([tabindex='-1'])");
    focusable?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !dialog) return;
      const controls = Array.from(dialog.querySelectorAll<HTMLElement>("button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex='-1'])"));
      if (controls.length === 0) return;
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      openerRef.current?.focus();
    };
  }, [onClose]);

  const inputCls =
    "w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 text-[14px] text-ink placeholder:text-muted outline-none focus:border-brand transition";

  const submit = useCallback(async () => {
    if (!name.trim()) {
      setError("상품명을 입력해 주세요.");
      return;
    }
    const generation = lifecycleRef.current.generation;
    const isActive = () => lifecycleRef.current.mounted && lifecycleRef.current.generation === generation;
    setSaving(true);
    setError(null);
    try {
      const created = await createManualInsurance(customerId, {
        name: name.trim(),
        insurance_type: insuranceType,
        portfolio_type: portfolioType,
        monthly_premiums: premium ? Number(premium) : undefined,
        contract_date: contractDate || undefined,
        expiry_date: expiryDate || undefined,
        contractor_name: contractor.trim() || undefined,
        insured_name: insured.trim() || undefined,
      });
      if (!isActive()) return;
      setInsuranceId(created.id);
      onChanged?.();
    } catch (e) {
      if (!isActive()) return;
      setError(e instanceof ApiError ? e.message : "저장에 실패했어요. 잠시 후 다시 시도하세요.");
    } finally {
      if (isActive()) setSaving(false);
    }
  }, [name, insuranceType, portfolioType, contractor, insured, premium, contractDate, expiryDate, customerId, onChanged]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 sm:p-4"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="w-full min-w-0 sm:max-w-3xl bg-surface rounded-t-2xl sm:rounded-2xl p-4 sm:p-5 max-h-[95dvh] sm:max-h-[90dvh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 id={titleId} className="text-[17px] font-extrabold text-ink">{insuranceId ? "담보 내용 확인" : "보험 직접 입력"}</h2>
          <button onClick={onClose} aria-label="닫기" className="text-ink3 text-[20px] leading-none px-1">✕</button>
        </div>
        {insuranceId ? (
          <div className="mt-4">
            <ManualInsuranceReview
              customerId={customerId}
              insuranceId={insuranceId}
              onChanged={onChanged}
              onCompleted={onClose}
            />
          </div>
        ) : (
        <>
          <p className="mt-1 text-[12px] text-ink3 leading-5">
            증권 파일이 없을 때 보험 기본정보를 먼저 입력해요. 저장한 뒤 같은 화면에서 담보를 확인하면 분석에 반영돼요.
          </p>

        <div className="mt-4 space-y-3">
          <label className="flex flex-col gap-1">
            <span className="text-[12px] font-semibold text-ink3">상품명</span>
            <input
              aria-label="상품명"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="예: 삼성생명 무배당 종합보험"
              className={inputCls}
            />
          </label>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="flex flex-col gap-1">
              <span className="text-[12px] font-semibold text-ink3">보험 종류</span>
              <select value={insuranceType} onChange={(e) => setInsuranceType(e.target.value === "1" ? 1 : 2)} className={inputCls}>
                <option value={2}>손해보험</option>
                <option value={1}>생명보험</option>
              </select>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[12px] font-semibold text-ink3">구분</span>
              <select value={portfolioType} onChange={(e) => setPortfolioType(e.target.value === "1" ? 1 : 2)} className={inputCls}>
                <option value={1}>비교 묶음 A</option>
                <option value={2}>비교 묶음 B</option>
              </select>
            </label>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="flex flex-col gap-1">
              <span className="text-[12px] font-semibold text-ink3">계약자 (선택)</span>
              <input value={contractor} onChange={(e) => setContractor(e.target.value)} placeholder="예: 김보장" className={inputCls} />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[12px] font-semibold text-ink3">피보험자 (선택)</span>
              <input value={insured} onChange={(e) => setInsured(e.target.value)} placeholder="예: 김보장" className={inputCls} />
            </label>
          </div>

          <label className="flex flex-col gap-1">
            <span className="text-[12px] font-semibold text-ink3">월 보험료 (원, 선택)</span>
            <input
              value={premium}
              onChange={(e) => setPremium(e.target.value.replace(/[^0-9]/g, ""))}
              inputMode="numeric"
              placeholder="예: 85000"
              className={inputCls}
            />
          </label>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="flex flex-col gap-1">
              <span className="text-[12px] font-semibold text-ink3">계약일 (선택)</span>
              <input type="date" value={contractDate} onChange={(e) => setContractDate(e.target.value)} className={inputCls} />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[12px] font-semibold text-ink3">만기일 (선택)</span>
              <input type="date" value={expiryDate} onChange={(e) => setExpiryDate(e.target.value)} className={inputCls} />
            </label>
          </div>
        </div>

        {error && <p className="mt-3 text-[13px] text-danger">{error}</p>}

        <div className="mt-5 flex gap-2">
          <button onClick={onClose} className="flex-1 rounded-xl border border-line text-ink2 text-[14px] font-semibold py-2.5 hover:bg-surface2">취소</button>
          <button onClick={submit} disabled={saving} className="flex-1 rounded-xl bg-brand text-white text-[14px] font-bold py-2.5 disabled:opacity-60">
            {saving ? "저장 중…" : "담보 입력으로 이동"}
          </button>
        </div>
        </>
        )}
      </div>
    </div>
  );
}
