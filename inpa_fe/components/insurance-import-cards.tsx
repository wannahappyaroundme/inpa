"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  getInsuranceImportConfig,
  listInsuranceImports,
  type InsuranceImportListItem,
} from "@/lib/api";
import { IMPORT_STATUS_COPY } from "@/lib/insurance-imports";

export function InsuranceImportCards({ customerId }: { customerId: number }) {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [items, setItems] = useState<InsuranceImportListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(false);
  const currentCustomerId = useRef(customerId);
  const requestGeneration = useRef(0);
  currentCustomerId.current = customerId;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      requestGeneration.current += 1;
    };
  }, []);

  const load = useCallback(async () => {
    const request = ++requestGeneration.current;
    const isCurrentRequest = () =>
      mounted.current &&
      requestGeneration.current === request &&
      currentCustomerId.current === customerId;
    setLoading(true);
    setError(null);
    try {
      const config = await getInsuranceImportConfig();
      if (!isCurrentRequest()) return;
      setEnabled(config.review_workflow_enabled);
      if (!config.review_workflow_enabled) {
        setItems([]);
        return;
      }
      const response = await listInsuranceImports(customerId);
      if (!isCurrentRequest()) return;
      setItems(response.results);
    } catch {
      if (!isCurrentRequest()) return;
      setEnabled(null);
      setItems([]);
      setError("증권 확인 작업을 불러오지 못했어요.");
    } finally {
      if (isCurrentRequest()) setLoading(false);
    }
  }, [customerId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return (
      <section className="mt-4 rounded-xl border border-line bg-surface p-4" aria-label="증권 확인 작업 불러오는 중">
        <div className="h-4 w-28 rounded bg-line animate-pulse" />
        <div className="mt-3 h-14 rounded-xl bg-surface2 animate-pulse" />
      </section>
    );
  }

  if (error) {
    return (
      <section className="mt-4 rounded-xl border border-line bg-surface2 px-4 py-4">
        <p className="text-[13px] text-ink2">{error} 다시 불러오면 이어서 확인할 수 있어요.</p>
        <button type="button" onClick={() => void load()} className="mt-2 text-[13px] font-semibold text-brand">
          다시 불러오기
        </button>
      </section>
    );
  }

  if (!enabled || items.length === 0) return null;

  if (items.some((item) => item.customer_id !== customerId)) {
    return (
      <section className="mt-4 rounded-xl border border-line bg-surface2 px-4 py-4">
        <p className="text-[13px] text-ink2">현재 고객의 증권 작업을 다시 선택해 주세요.</p>
        <Link href="/customers" className="mt-2 inline-block text-[13px] font-semibold text-brand">
          고객 목록으로 이동
        </Link>
      </section>
    );
  }

  return (
    <section className="mt-4" aria-labelledby="insurance-import-heading">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h3 id="insurance-import-heading" className="text-[13px] font-bold text-ink">증권 확인 작업</h3>
        <span className="text-[11px] text-ink3 tnum">{items.length}건</span>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {items.map((item) => (
          <Link
            key={item.job_id}
            href={`/customer/${customerId}/insurance-imports/${item.job_id}`}
            className="rounded-xl border border-line bg-surface px-3.5 py-3 transition hover:bg-surface2"
          >
            <div className="flex items-start justify-between gap-2">
              <span className="truncate text-[13px] font-semibold text-ink">{item.safe_display_name}</span>
              <span className="shrink-0 rounded-full border border-line bg-surface2 px-2 py-0.5 text-[10px] font-semibold text-ink3">
                {item.portfolio_type === 1 ? "비교 묶음 A" : "비교 묶음 B"}
              </span>
            </div>
            <p className="mt-1 text-[12px] leading-5 text-ink3">{IMPORT_STATUS_COPY[item.status]}</p>
          </Link>
        ))}
      </div>
    </section>
  );
}
