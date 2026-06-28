"use client";

// 보험 수기 등록 모달 — OCR 불가(스캔/이미지/키없음) 폴백 + 갈아타기 제안 입력.
// customer-create-modal 시트형 패턴. 담보 상세는 없이 기본정보만 → 환수레이더·요약 반영.

import { useState, useCallback } from "react";
import { createManualInsurance, ApiError } from "@/lib/api";

export function InsuranceManualModal({
  customerId,
  onClose,
  onCreated,
}: {
  customerId: number;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [name, setName] = useState("");
  const [insuranceType, setInsuranceType] = useState(2); // 손해보험 기본
  const [portfolioType, setPortfolioType] = useState(1); // 보유 기본
  const [premium, setPremium] = useState("");
  const [contractDate, setContractDate] = useState("");
  const [expiryDate, setExpiryDate] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const inputCls =
    "w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 text-[14px] text-ink placeholder:text-muted outline-none focus:border-brand transition";

  const submit = useCallback(async () => {
    if (!name.trim()) {
      setError("상품명을 입력해 주세요.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await createManualInsurance(customerId, {
        name: name.trim(),
        insurance_type: insuranceType,
        portfolio_type: portfolioType,
        monthly_premiums: premium ? Number(premium) : undefined,
        contract_date: contractDate || undefined,
        expiry_date: expiryDate || undefined,
      });
      onCreated();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "저장에 실패했어요. 잠시 후 다시 시도하세요.");
    } finally {
      setSaving(false);
    }
  }, [name, insuranceType, portfolioType, premium, contractDate, expiryDate, customerId, onCreated]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 sm:p-4"
      onClick={onClose}
    >
      <div
        className="w-full sm:max-w-md bg-surface rounded-t-2xl sm:rounded-2xl p-5 max-h-[90dvh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-[17px] font-extrabold text-ink">보험 직접 입력</h2>
          <button onClick={onClose} aria-label="닫기" className="text-ink3 text-[20px] leading-none px-1">✕</button>
        </div>
        <p className="mt-1 text-[12px] text-ink3 leading-5">
          증권 파일이 없을 때 보험을 직접 입력해요. 회사명은 상품명에 함께 적어 주세요(예: 삼성생명 무배당…). 담보 상세 없이 보험료·계약 유지 점검에 반영돼요.
        </p>

        <div className="mt-4 space-y-3">
          <label className="flex flex-col gap-1">
            <span className="text-[12px] font-semibold text-ink3">상품명</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="예: 삼성생명 무배당 종합보험"
              className={inputCls}
            />
          </label>

          <div className="grid grid-cols-2 gap-3">
            <label className="flex flex-col gap-1">
              <span className="text-[12px] font-semibold text-ink3">보험 종류</span>
              <select value={insuranceType} onChange={(e) => setInsuranceType(Number(e.target.value))} className={inputCls}>
                <option value={2}>손해보험</option>
                <option value={1}>생명보험</option>
              </select>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[12px] font-semibold text-ink3">구분</span>
              <select value={portfolioType} onChange={(e) => setPortfolioType(Number(e.target.value))} className={inputCls}>
                <option value={1}>보유(기존 가입)</option>
                <option value={2}>제안(갈아타기)</option>
              </select>
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

          <div className="grid grid-cols-2 gap-3">
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
            {saving ? "저장 중…" : "등록"}
          </button>
        </div>
      </div>
    </div>
  );
}
