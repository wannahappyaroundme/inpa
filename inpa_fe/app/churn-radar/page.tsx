"use client";

// ════════════════════════════════════════════════════════════════════════════
// 환수 레이더(A/S) — docs 회의 후속(분석→영업→소개→A/S의 A/S 단계)
//
// ★ 정직성/컴플라이언스:
//  - 납입회차·환수예상액은 설계사 '수기입력' 추정치. 정확액은 보험사/회사 전산 권위 → '추정' 라벨 상시.
//  - owner 전용(BE customer__owner 격리). 보유(portfolio_type=1) 계약만.
//  - 자동발송 없음 — 본 화면은 점검·표시·수기입력까지만.
// ════════════════════════════════════════════════════════════════════════════

import { useState, useEffect, useCallback } from "react";
import { AppNav } from "@/components/app-nav";
import { Card } from "@/components/ui";
import { useAuthGuard } from "@/lib/useAuthGuard";
import {
  getChurnRadar,
  updateInsuranceChurn,
  type ChurnRadarResponse,
  type ChurnRadarItem,
  type PersistencyStage,
} from "@/lib/api";

const STAGE_META: Record<PersistencyStage, { label: string; cls: string }> = {
  unknown: { label: "미입력", cls: "bg-surface2 text-ink3 border-line" },
  pre_13: { label: "13회차 전", cls: "bg-rose-50 text-rose-700 border-rose-200" },
  pre_25: { label: "25회차 전", cls: "bg-amber-50 text-amber-700 border-amber-200" },
  safe: { label: "유지 안정", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
};

const STATUS_OPTIONS = [
  { v: "", label: "미입력" },
  { v: "1", label: "정상" },
  { v: "2", label: "연체" },
  { v: "3", label: "납입중단" },
];

const krw = new Intl.NumberFormat("ko-KR");

// 입력 드래프트(문자열 보관 → 저장 시 number|null 변환)
type Draft = {
  current_payment_period: string;
  payment_status: string;
  next_payment_date: string;
  expected_recovery_amount: string;
};

function toDraft(it: ChurnRadarItem): Draft {
  return {
    current_payment_period: it.current_payment_period?.toString() ?? "",
    payment_status: it.payment_status?.toString() ?? "",
    next_payment_date: it.next_payment_date ?? "",
    expected_recovery_amount: it.expected_recovery_amount?.toString() ?? "",
  };
}

function numOrNull(s: string): number | null {
  if (s.trim() === "") return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

export default function ChurnRadarPage() {
  const ready = useAuthGuard();
  const [data, setData] = useState<ChurnRadarResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<number, Draft>>({});
  const [savingId, setSavingId] = useState<number | null>(null);
  const [savedId, setSavedId] = useState<number | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    getChurnRadar()
      .then((res) => {
        setData(res);
        const d: Record<number, Draft> = {};
        res.items.forEach((it) => (d[it.insurance_id] = toDraft(it)));
        setDrafts(d);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "불러오지 못했어요."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (ready) load();
  }, [ready, load]);

  function setField(id: number, key: keyof Draft, val: string) {
    setDrafts((prev) => ({ ...prev, [id]: { ...prev[id], [key]: val } }));
  }

  async function save(it: ChurnRadarItem) {
    const d = drafts[it.insurance_id];
    if (!d) return;
    setSavingId(it.insurance_id);
    setError(null);
    try {
      await updateInsuranceChurn(it.insurance_id, {
        current_payment_period: numOrNull(d.current_payment_period),
        payment_status: numOrNull(d.payment_status),
        next_payment_date: d.next_payment_date.trim() === "" ? null : d.next_payment_date,
        expected_recovery_amount: numOrNull(d.expected_recovery_amount),
      });
      setSavedId(it.insurance_id);
      setTimeout(() => setSavedId(null), 1800);
      load(); // 위험판정·집계 재계산 반영
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "저장 실패");
    } finally {
      setSavingId(null);
    }
  }

  if (!ready) return null;

  return (
    <div className="min-h-dvh">
      <AppNav active="home" />
      <main className="mx-auto max-w-3xl px-4 sm:px-6 py-6">
        <h1 className="text-[22px] font-extrabold text-ink">환수 레이더</h1>
        <p className="mt-1 text-[13px] text-ink3 leading-5">
          보유 계약의 납입상태와 유지율(13/25회차)을 점검해, 환수(차지백) 위험을 미리 막으세요.
        </p>

        {/* 요약 */}
        {data && (
          <div className="mt-4 grid grid-cols-2 gap-3">
            <Card className="px-4 py-3.5">
              <div className="text-[12px] text-ink3">환수 위험</div>
              <div className="mt-1 text-[24px] font-extrabold tnum text-rose-600">
                {data.risk_count}<span className="text-[13px] text-ink3 ml-1">건</span>
              </div>
            </Card>
            <Card className="px-4 py-3.5">
              <div className="text-[12px] text-ink3">예상 환수액(추정)</div>
              <div className="mt-1 text-[18px] font-extrabold tnum text-ink">
                ₩{krw.format(data.expected_recovery_total)}
              </div>
            </Card>
          </div>
        )}

        {/* 면책 */}
        {data && (
          <div className="mt-3 rounded-xl border border-line bg-surface2 px-4 py-3 text-[12px] text-ink3 leading-5">
            {data.disclaimer}
          </div>
        )}

        {error && (
          <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-[13px] text-rose-700">
            {error}
          </div>
        )}

        {/* 리스트 */}
        <div className="mt-5 space-y-3">
          {loading ? (
            [1, 2, 3].map((i) => (
              <div key={i} className="h-28 rounded-2xl bg-line animate-pulse" />
            ))
          ) : !data || data.items.length === 0 ? (
            <Card className="px-4 py-10 text-center">
              <p className="text-[14px] text-ink3">보유 보험이 아직 없어요.</p>
              <p className="mt-1 text-[12px] text-ink3">
                고객 상세에서 증권을 올려 보험을 먼저 등록하면 여기서 납입·환수를 관리할 수 있어요.
              </p>
            </Card>
          ) : (
            data.items.map((it) => {
              const d = drafts[it.insurance_id];
              const stage = STAGE_META[it.persistency_stage];
              return (
                <Card
                  key={it.insurance_id}
                  className={`px-4 py-3.5 ${it.is_at_risk ? "border-rose-200" : ""}`}
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-[15px] font-bold text-ink">{it.customer_name}</span>
                    <span className="text-[13px] text-ink3">{it.insurance_name ?? "보험"}</span>
                    <span className={`ml-auto text-[11px] font-semibold rounded-full border px-2 py-0.5 ${stage.cls}`}>
                      {stage.label}
                    </span>
                  </div>
                  {it.is_at_risk && it.risk_reason && (
                    <div className="mt-1.5 text-[12px] font-semibold text-rose-700">
                      ⚠️ {it.risk_reason}
                    </div>
                  )}

                  {/* 수기입력 */}
                  <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2.5">
                    <label className="block">
                      <span className="text-[11px] text-ink3">납입회차</span>
                      <input
                        type="number"
                        min={0}
                        value={d?.current_payment_period ?? ""}
                        onChange={(e) => setField(it.insurance_id, "current_payment_period", e.target.value)}
                        className="mt-0.5 w-full rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[14px] text-ink tnum"
                        placeholder="회"
                      />
                    </label>
                    <label className="block">
                      <span className="text-[11px] text-ink3">납입상태</span>
                      <select
                        value={d?.payment_status ?? ""}
                        onChange={(e) => setField(it.insurance_id, "payment_status", e.target.value)}
                        className="mt-0.5 w-full rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[14px] text-ink"
                      >
                        {STATUS_OPTIONS.map((o) => (
                          <option key={o.v} value={o.v}>{o.label}</option>
                        ))}
                      </select>
                    </label>
                    <label className="block">
                      <span className="text-[11px] text-ink3">다음 납입일</span>
                      <input
                        type="date"
                        value={d?.next_payment_date ?? ""}
                        onChange={(e) => setField(it.insurance_id, "next_payment_date", e.target.value)}
                        className="mt-0.5 w-full rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[14px] text-ink"
                      />
                    </label>
                    <label className="block">
                      <span className="text-[11px] text-ink3">예상 환수액(추정)</span>
                      <input
                        type="number"
                        min={0}
                        value={d?.expected_recovery_amount ?? ""}
                        onChange={(e) => setField(it.insurance_id, "expected_recovery_amount", e.target.value)}
                        className="mt-0.5 w-full rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[14px] text-ink tnum"
                        placeholder="원"
                      />
                    </label>
                  </div>

                  <div className="mt-2.5 flex items-center justify-end gap-2">
                    {savedId === it.insurance_id && (
                      <span className="text-[12px] font-semibold text-emerald-600">저장됐어요</span>
                    )}
                    <button
                      onClick={() => save(it)}
                      disabled={savingId === it.insurance_id}
                      className="rounded-xl bg-brand text-white text-[13px] font-bold px-4 py-2 disabled:opacity-60 active:scale-[0.98] transition"
                    >
                      {savingId === it.insurance_id ? "저장 중…" : "저장"}
                    </button>
                  </div>
                </Card>
              );
            })
          )}
        </div>
      </main>
    </div>
  );
}
