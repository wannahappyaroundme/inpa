"use client";

// ════════════════════════════════════════════════════════════════════════════
// 유지 회차 타이머 (구 '환수 레이더') — 보유계약의 납입회차(유지율)를 한눈에.
//
// ★ 정직성: 연체·미납·환수금액은 시스템이 알 수 없음(보험사 전산에만 존재) → 표시/판정 안 함.
//   납입회차는 '계약일 기준 자동 계산'(설계사가 직접 입력하면 그 값 우선). 13/25회차 임박만 알림.
//   owner 전용(BE customer__owner 격리). 보유(portfolio_type=1) 계약만.
// ════════════════════════════════════════════════════════════════════════════

import { useState, useEffect, useCallback } from "react";
import { Timer } from "lucide-react";
import { AppNav } from "@/components/app-nav";
import { Card, ReminderCard } from "@/components/ui";
import { useAuthGuard } from "@/lib/useAuthGuard";
import {
  getChurnRadar,
  updateInsuranceChurn,
  ApiError,
  type ChurnRadarResponse,
  type ChurnRadarItem,
  type PersistencyStage,
} from "@/lib/api";

const STAGE_META: Record<PersistencyStage, { label: string; cls: string }> = {
  unknown: { label: "회차 미상", cls: "bg-surface2 text-ink3 border-line" },
  pre_13: { label: "초기 (13회차 전)", cls: "bg-warning-tint text-warning-ink border-short/40" },
  pre_25: { label: "정착 중 (25회차 전)", cls: "bg-accent-tint text-brand border-accent/30" },
  safe: { label: "유지 안정 (25회차+)", cls: "bg-success-tint text-success-ink border-enough/30" },
};

// 입력 드래프트 — 회차(수기 override) + 해지 기록만(나머지 납입상태는 자동 인지 불가라 제거).
type Draft = {
  current_payment_period: string;
  is_cancelled: boolean;
  cancelled_at: string;
};

function toDraft(it: ChurnRadarItem): Draft {
  return {
    current_payment_period: it.current_payment_period?.toString() ?? "",
    is_cancelled: it.is_cancelled,
    cancelled_at: it.cancelled_at ?? "",
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

  const load = useCallback(async (keepError = false) => {
    setLoading(true);
    if (!keepError) setError(null);
    try {
      const res = await getChurnRadar();
      setData(res);
      const d: Record<number, Draft> = {};
      res.items.forEach((it) => (d[it.insurance_id] = toDraft(it)));
      setDrafts(d);
    } catch (e: unknown) {
      setError(keepError
        ? "최신 보험 내용을 다시 불러와 주세요."
        : e instanceof Error ? e.message : "연결이 잠시 원활하지 않아요. 다시 불러와 주세요.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (ready) void load();
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
        data_version: it.data_version,
        current_payment_period: numOrNull(d.current_payment_period),
        is_cancelled: d.is_cancelled,
        cancelled_at: d.is_cancelled && d.cancelled_at.trim() !== "" ? d.cancelled_at : null,
      });
      setSavedId(it.insurance_id);
      setTimeout(() => setSavedId(null), 1800);
      void load(); // 회차·임박 재계산 반영
    } catch (e: unknown) {
      if (e instanceof ApiError && e.status === 409 && e.code === "INSURANCE_VERSION_CHANGED") {
        setError("다른 화면에서 보험 내용이 먼저 변경됐어요. 최신 내용을 불러왔습니다.");
        await load(true);
      } else {
        setError(e instanceof Error ? e.message : "저장 연결이 잠시 원활하지 않아요. 다시 시도해 주세요.");
      }
    } finally {
      setSavingId(null);
    }
  }

  if (!ready) return null;

  // 4색 리마인드 버킷 — 회차 단계(계약일 자동계산)에 정직하게 매핑.
  // 임박(빨강) → 초기 13회차 전(주황) → 정착 25회차 전(파랑) → 유지 안정(초록).
  const items = data?.items ?? [];
  const reminderCards = [
    { tone: "var(--danger)", icon: "⏰", label: "회차 임박", count: items.filter((i) => i.is_at_risk).length },
    { tone: "var(--warning)", icon: "①", label: "초기(13회차 전)", count: items.filter((i) => i.persistency_stage === "pre_13").length },
    { tone: "var(--accent-blue)", icon: "②", label: "정착(25회차 전)", count: items.filter((i) => i.persistency_stage === "pre_25").length },
    { tone: "var(--success)", icon: "✓", label: "유지 안정", count: items.filter((i) => i.persistency_stage === "safe").length },
  ];

  return (
    <div className="min-h-dvh">
      <AppNav active="home" />
      <main className="mx-auto max-w-3xl px-4 sm:px-6 py-6">
        <h1 className="text-[22px] font-extrabold text-ink">유지 회차 타이머</h1>
        <p className="mt-1 text-[13px] text-ink3 leading-5">
          보유 계약의 납입회차(유지율)를 계약일 기준으로 자동 계산해, 13/25회차(환수 구간) 전 유지 관리를 도와드려요.
        </p>

        {/* 요약 — 4색 회차 단계 리마인드 카드 */}
        {data && (
          <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-3">
            {reminderCards.map((c) => (
              <ReminderCard key={c.label} tone={c.tone} icon={c.icon} label={c.label} count={c.count} unit="건" />
            ))}
          </div>
        )}

        {/* 면책 */}
        {data && (
          <div className="mt-3 rounded-xl border border-line bg-surface2 px-4 py-3 text-[12px] text-ink3 leading-5">
            {data.disclaimer}
          </div>
        )}

        {error && (
          <div className="mt-3 rounded-xl border border-cnone/30 bg-danger-tint px-4 py-2.5 text-[13px] text-danger-ink">
            {error}
          </div>
        )}

        {/* 리스트 */}
        <div className="mt-5 space-y-3">
          {loading ? (
            [1, 2, 3].map((i) => (
              <div key={i} className="h-24 rounded-2xl bg-line animate-pulse" />
            ))
          ) : !data || data.items.length === 0 ? (
            <Card className="px-4 py-10 text-center">
              <Timer className="mx-auto w-8 h-8 text-ink3" />
              <p className="mt-3 text-[14px] text-ink3">보유 보험이 아직 없어요.</p>
              <p className="mt-1 text-[12px] text-ink3">
                고객 상세에서 증권을 올려 보험을 먼저 등록하면 여기서 유지 회차를 관리할 수 있어요.
              </p>
            </Card>
          ) : (
            data.items.map((it) => {
              const d = drafts[it.insurance_id];
              const stage = STAGE_META[it.persistency_stage];
              return (
                <Card
                  key={it.insurance_id}
                  className={`px-4 py-3.5 ${it.is_at_risk ? "border-cnone/50" : ""}`}
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-[15px] font-bold text-ink">{it.customer_name}</span>
                    <span className="text-[13px] text-ink3">{it.insurance_name ?? "보험"}</span>
                    <span className="text-[12px] text-ink2 tnum">
                      {it.current_payment_period != null ? `${it.current_payment_period}회차` : "회차 미상"}
                    </span>
                    <span className={`ml-auto text-[11px] font-semibold rounded-full border px-2 py-0.5 ${stage.cls}`}>
                      {stage.label}
                    </span>
                  </div>
                  {it.is_at_risk && it.risk_reason && (
                    <div className="mt-1.5 text-[12px] font-semibold text-warning-ink">
                      ⏰ {it.risk_reason} 남았어요. 유지 관리하세요.
                    </div>
                  )}

                  {/* 수기 보정 — 회차만(계약일 자동 계산이 부정확할 때) + 해지 기록 */}
                  <div className="mt-3 flex flex-wrap items-end gap-3">
                    <label className="block">
                      <span className="text-[11px] text-ink3">납입회차 (비우면 자동)</span>
                      <input
                        type="number"
                        min={0}
                        value={d?.current_payment_period ?? ""}
                        onChange={(e) => setField(it.insurance_id, "current_payment_period", e.target.value)}
                        className="mt-0.5 w-28 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[14px] text-ink tnum"
                        placeholder="회"
                      />
                    </label>
                    <label className="flex items-center gap-2 text-[13px] text-ink2 pb-1.5">
                      <input
                        type="checkbox"
                        checked={d?.is_cancelled ?? false}
                        onChange={(e) =>
                          setDrafts((prev) => ({
                            ...prev,
                            [it.insurance_id]: { ...prev[it.insurance_id], is_cancelled: e.target.checked },
                          }))
                        }
                        className="w-4 h-4 accent-cnone"
                      />
                      해지된 계약
                      {d?.is_cancelled && (
                        <input
                          type="date"
                          value={d?.cancelled_at ?? ""}
                          onChange={(e) => setField(it.insurance_id, "cancelled_at", e.target.value)}
                          className="ml-1 rounded-lg border border-line bg-surface px-2 py-1 text-[13px] text-ink"
                          aria-label="해지일"
                        />
                      )}
                    </label>
                    <div className="ml-auto flex items-center gap-2 pb-0.5">
                      {savedId === it.insurance_id && (
                        <span className="text-[12px] font-semibold text-success-ink">저장됐어요</span>
                      )}
                      <button
                        onClick={() => save(it)}
                        disabled={savingId === it.insurance_id}
                        className="rounded-xl bg-brand text-white text-[13px] font-bold px-4 py-2 disabled:opacity-60 active:scale-[0.98] transition"
                      >
                        {savingId === it.insurance_id ? "저장 중…" : "저장"}
                      </button>
                    </div>
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
