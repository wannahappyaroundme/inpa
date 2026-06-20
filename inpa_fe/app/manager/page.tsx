"use client";

// 지점장 대시보드 — 동의(manager_share_opt_in)한 소속 설계사의 KPI '집계만'.
// ★ 개별 고객 이름·병력 등 PII는 절대 표시하지 않음(BE가 집계 수치만 반환).

import { useState, useEffect } from "react";
import { AppNav } from "@/components/app-nav";
import { Card } from "@/components/ui";
import { useAuthGuard } from "@/lib/useAuthGuard";
import { getManagerDashboard, type ManagerDashboardResponse } from "@/lib/api";

const krw = new Intl.NumberFormat("ko-KR");

export default function ManagerPage() {
  const ready = useAuthGuard();
  const [data, setData] = useState<ManagerDashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready) return;
    getManagerDashboard()
      .then(setData)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "불러오지 못했어요."))
      .finally(() => setLoading(false));
  }, [ready]);

  if (!ready) return null;

  return (
    <div className="min-h-dvh">
      <AppNav active="manager" />
      <main className="mx-auto max-w-3xl px-4 sm:px-6 py-6">
        <h1 className="text-[22px] font-extrabold text-ink">지점 KPI</h1>
        <p className="mt-1 text-[13px] text-ink3 leading-5">
          KPI 공유에 <b>동의한</b> 소속 설계사의 집계 수치예요. 개별 고객 정보는 표시되지 않습니다(프라이버시).
        </p>

        {error && (
          <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-[13px] text-rose-700">
            {error}
          </div>
        )}

        {/* 합계 */}
        {data && (
          <div className="mt-4 grid grid-cols-3 gap-3">
            <Card className="px-4 py-3.5">
              <div className="text-[12px] text-ink3">소속(동의)</div>
              <div className="mt-1 text-[22px] font-extrabold tnum text-ink">{data.agent_count}<span className="text-[12px] text-ink3 ml-1">명</span></div>
            </Card>
            <Card className="px-4 py-3.5">
              <div className="text-[12px] text-ink3">총 고객</div>
              <div className="mt-1 text-[22px] font-extrabold tnum text-ink">{data.totals.customer_count}</div>
            </Card>
            <Card className="px-4 py-3.5">
              <div className="text-[12px] text-ink3">환수 위험</div>
              <div className="mt-1 text-[22px] font-extrabold tnum text-rose-600">{data.totals.churn_risk_count}</div>
            </Card>
          </div>
        )}

        {/* 설계사별 */}
        <div className="mt-5 space-y-2.5">
          {loading ? (
            [1, 2, 3].map((i) => <div key={i} className="h-16 rounded-2xl bg-line animate-pulse" />)
          ) : !data || data.agents.length === 0 ? (
            <Card className="px-4 py-10 text-center">
              <p className="text-[14px] text-ink3">아직 KPI 공유에 동의한 소속 설계사가 없어요.</p>
              <p className="mt-1 text-[12px] text-ink3">
                설계사가 설정에서 “지점장에게 KPI 공유”를 켜고 매니저 이메일을 연결하면 여기에 표시돼요.
              </p>
            </Card>
          ) : (
            data.agents.map((a, i) => (
              <Card key={i} className="px-4 py-3.5 flex items-center gap-3">
                <div className="w-9 h-9 rounded-full bg-accent-tint text-brand flex items-center justify-center text-[14px] font-bold shrink-0">
                  {a.name_masked[0]}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-[14px] font-bold text-ink">{a.name_masked}</div>
                  <div className="text-[12px] text-ink3 mt-0.5">
                    고객 {a.customer_count} · 공유열람 {krw.format(a.share_view_count)}
                  </div>
                </div>
                {a.churn_risk_count > 0 && (
                  <span className="shrink-0 text-[12px] font-semibold rounded-full bg-rose-50 text-rose-700 border border-rose-200 px-2 py-0.5">
                    환수 위험 {a.churn_risk_count}
                  </span>
                )}
              </Card>
            ))
          )}
        </div>
      </main>
    </div>
  );
}
