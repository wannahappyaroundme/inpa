"use client";

import { useEffect, useState } from "react";

import { fmtWon } from "@/components/heatmap";
import { listAllManualInsurances, type ManualInsuranceItem } from "@/lib/api";

function insuranceReviewPresentation(it: ManualInsuranceItem): {
  label: string;
  action: string | null;
} {
  if (it.is_cancelled) return { label: "해지 기록", action: null };
  if (it.review_status === "draft") return { label: "직접 입력 확인 필요", action: "입력 이어하기" };
  if (it.review_status === "legacy_review_required") return { label: "기존 자료 확인 필요", action: "기존 자료 확인하기" };
  if (it.review_status === "excluded") return { label: "분석에서 뺀 보험", action: null };
  if (it.review_status === "superseded") return { label: "새 자료로 교체됨", action: null };
  return { label: it.analysis_included ? "분석 포함" : "분석 미포함", action: null };
}

export function InsuranceCard({ it, onReview }: {
  it: ManualInsuranceItem;
  onReview?: (insuranceId: number) => void;
}) {
  const typeLabel = it.insurance_type === 1 ? "생명" : "손해";
  const insured = it.insured_name ?? (it.is_same_insured ? "계약자와 동일" : "-");
  const review = insuranceReviewPresentation(it);
  return (
    <div className="rounded-xl border border-line bg-surface p-3.5">
      <div className="flex items-start justify-between gap-2">
        <div className="truncate text-[14px] font-bold text-ink">{it.name ?? "이름 없는 보험"}</div>
        <span className="shrink-0 rounded-full border border-line bg-surface2 px-2 py-0.5 text-[10px] font-semibold text-ink3">{typeLabel}</span>
      </div>
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12px]">
        <dt className="text-ink3">계약자</dt><dd className="truncate text-right text-ink2">{it.contractor_name ?? "-"}</dd>
        <dt className="text-ink3">피보험자</dt><dd className="truncate text-right text-ink2">{insured}</dd>
        <dt className="text-ink3">월 보험료</dt><dd className="tnum text-right text-ink2">{fmtWon(it.monthly_premiums)}</dd>
        <dt className="text-ink3">기간</dt><dd className="text-right text-ink2">{it.contract_date ?? "-"} ~ {it.expiry_date ?? "-"}</dd>
      </dl>
      {(it.monthly_renewal_premium != null || it.monthly_non_renewal_premium != null) && (
        <div className="mt-1 flex gap-3 text-[12px] text-ink3">
          {it.monthly_renewal_premium != null && <span>갱신 {fmtWon(it.monthly_renewal_premium)}</span>}
          {it.monthly_non_renewal_premium != null && <span>비갱신 {fmtWon(it.monthly_non_renewal_premium)}</span>}
        </div>
      )}
      <div className="mt-2 flex items-center justify-between gap-2 border-t border-line pt-2">
        <span className="text-[11px] font-semibold text-ink3">{review.label}</span>
        {review.action && onReview && (
          <button type="button" onClick={() => onReview(it.id)} className="rounded-lg border border-brand px-2.5 py-1.5 text-[11px] font-semibold text-brand">{review.action}</button>
        )}
      </div>
    </div>
  );
}

export function InsuranceCards({
  customerId,
  portfolioType,
  refreshKey,
  emptyHint,
  title,
  onReview,
  onPendingInsurance,
}: {
  customerId: number;
  portfolioType?: number;
  refreshKey?: number;
  emptyHint?: string;
  title?: string;
  onReview?: (insuranceId: number) => void;
  onPendingInsurance?: (insuranceId: number | null) => void;
}) {
  const [items, setItems] = useState<ManualInsuranceItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setLoadError(false);
    listAllManualInsurances(customerId)
      .then((rows) => {
        if (!active) return;
        const filtered = portfolioType == null
          ? rows
          : rows.filter((item) => item.portfolio_type === portfolioType);
        setItems(filtered);
        onPendingInsurance?.(
          filtered.find((item) => item.review_status === "draft" || item.review_status === "legacy_review_required")?.id ?? null
        );
      })
      .catch(() => {
        if (!active) return;
        setItems([]);
        setLoadError(true);
        onPendingInsurance?.(null);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [customerId, onPendingInsurance, portfolioType, refreshKey, retryKey]);

  if (loading) return <div role="status" aria-label="보험 목록을 불러오는 중" className="grid gap-3 sm:grid-cols-2">{[1, 2].map((index) => <div key={index} className="h-24 animate-pulse rounded-xl bg-line" />)}</div>;
  if (loadError) return <div role="alert" className="rounded-xl border border-line bg-surface2 px-4 py-5 text-center text-[13px] text-ink3">보험 목록을 불러오지 못했어요.<button type="button" onClick={() => setRetryKey((value) => value + 1)} className="ml-2 font-semibold text-brand">다시 불러오기</button></div>;
  if (items.length === 0) return emptyHint ? <div role="status" className="rounded-xl border border-dashed border-line px-4 py-5 text-center text-[13px] text-ink3">{emptyHint}</div> : null;
  return (
    <div>
      {title && <div className="mb-2 text-[13px] font-bold text-ink">{title} <span className="tnum text-ink3">{items.length}</span></div>}
      <div className="grid gap-3 sm:grid-cols-2">
        {items.map((item) => <InsuranceCard key={item.id} it={item} onReview={onReview} />)}
      </div>
    </div>
  );
}

export type SideAssign = "A" | "B" | "none";

export function AssignInsRow({ it, value, onChange, onReview }: {
  it: ManualInsuranceItem;
  value: SideAssign;
  onChange: (value: SideAssign) => void;
  onReview?: (insuranceId: number) => void;
}) {
  const sub = [it.contractor_name && `계약 ${it.contractor_name}`, it.insured_name && `피보험 ${it.insured_name}`]
    .filter(Boolean).join(" · ") || (it.insurance_type === 1 ? "생명" : "손해");
  const portfolioTag = it.portfolio_type === 1 ? "보유" : "제안";
  const selectable = it.review_status === "confirmed" && it.analysis_included && !it.is_cancelled;
  const review = insuranceReviewPresentation(it);
  return (
    <div className="flex flex-wrap items-center gap-2.5 rounded-xl border border-line bg-surface px-3 py-2 sm:flex-nowrap">
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5">
          <span className="truncate text-[13px] font-semibold text-ink">{it.name ?? "이름 없는 보험"}</span>
          <span className="shrink-0 rounded-full border border-line bg-surface2 px-1.5 py-0.5 text-[10px] font-semibold text-ink3">{portfolioTag}</span>
        </span>
        <span className="block truncate text-[11px] text-ink3">{sub}</span>
        {!selectable && <span className="block text-[10px] font-semibold text-amber-700">{review.label}</span>}
      </span>
      <span className="tnum shrink-0 text-[11px] text-ink2">{fmtWon(it.monthly_premiums)}</span>
      <div className="inline-flex shrink-0 overflow-hidden rounded-lg border border-line text-[11px] font-semibold">
        <button type="button" disabled={!selectable} onClick={() => onChange("A")} aria-pressed={value === "A"} className={`px-2.5 py-1.5 transition disabled:opacity-40 ${value === "A" ? "bg-brand text-white" : "bg-surface text-ink2 hover:bg-surface2"}`}>A안</button>
        <button type="button" onClick={() => onChange("none")} aria-pressed={value === "none"} className={`border-x border-line px-2.5 py-1.5 transition ${value === "none" ? "bg-surface2 text-ink" : "bg-surface text-ink3 hover:bg-surface2"}`}>미포함</button>
        <button type="button" disabled={!selectable} onClick={() => onChange("B")} aria-pressed={value === "B"} className={`px-2.5 py-1.5 transition disabled:opacity-40 ${value === "B" ? "bg-ink text-white" : "bg-surface text-ink2 hover:bg-surface2"}`}>B안</button>
      </div>
      {!selectable && onReview && review.action && (
        <button type="button" onClick={() => onReview(it.id)} className="shrink-0 rounded-lg border border-brand px-2.5 py-1.5 text-[11px] font-semibold text-brand">{review.action}</button>
      )}
    </div>
  );
}
