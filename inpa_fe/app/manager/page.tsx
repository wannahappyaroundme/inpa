"use client";

// 관리직 대시보드 — 동의(manager_share_opt_in)한 소속 설계사의 KPI '집계만'.
// ★ 개별 고객 이름·병력 등 PII는 절대 표시하지 않음(BE가 집계 수치만 반환).

import { useState, useEffect } from "react";
import { AppNav } from "@/components/app-nav";
import { Card } from "@/components/ui";
import { useAuthGuard } from "@/lib/useAuthGuard";
import { getManagerDashboard, SALES_STAGES, type ManagerDashboardResponse } from "@/lib/api";

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
        <h1 className="text-[22px] font-extrabold text-ink">관리직 KPI</h1>
        <p className="mt-1.5 text-[14px] font-semibold text-brand leading-5">
          팀원 한 명 한 명의 인파(人波)를 정리하면 팀 전체의 성과가 보입니다.
        </p>
        <p className="mt-1 text-[13px] text-ink3 leading-5">
          월말 취합 엑셀은 이제 그만. KPI 공유에 <b>동의한</b> 소속 설계사의 집계를 실시간으로 봐요. 개별 고객 정보는 표시되지 않습니다(프라이버시).
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

        {/* 팀 계약 유지율(추정) · 팀 퍼널 · ROI — PM 06.24 */}
        {data && data.agent_count > 0 && (
          <>
            <h2 className="mt-5 text-[15px] font-bold text-ink">
              팀 계약 유지율 <span className="text-[11px] font-normal text-ink3">(추정)</span>
            </h2>
            {data.team_retention.has_cancellation_data ? (
              <div className="mt-2 grid grid-cols-3 gap-3">
                {([["y1", "1년"], ["y2", "2년"], ["y3", "3년"]] as const).map(([k, label]) => {
                  const r = data.team_retention[k];
                  return (
                    <Card key={k} className="px-4 py-3.5">
                      <div className="text-[12px] text-ink3">{label} 유지율</div>
                      <div className="mt-1 text-[22px] font-extrabold tnum text-ink">
                        {r.rate == null ? "·" : `${r.rate}%`}
                      </div>
                      <div className="text-[11px] text-ink3 tnum">{r.survived}/{r.reached}건</div>
                    </Card>
                  );
                })}
              </div>
            ) : (
              <Card className="mt-2 px-4 py-4 text-[12px] text-ink3 leading-5">
                아직 팀의 해지 입력이 없어 유지율을 계산하지 않았어요. 팀원이 환수 레이더에서 해지를 표시하면 집계됩니다.
              </Card>
            )}

            <h2 className="mt-5 text-[15px] font-bold text-ink">팀 영업 퍼널</h2>
            <div className="mt-2 grid grid-cols-4 gap-2">
              {SALES_STAGES.map((s) => (
                <Card key={s.key} className="px-3 py-3 text-center">
                  <div className="text-[11px] text-ink3">{s.label}</div>
                  <div className="mt-1 text-[18px] font-extrabold tnum text-ink">{data.team_funnel[s.key] ?? 0}</div>
                </Card>
              ))}
            </div>

            <Card className="mt-5 p-4 border-accent-tint">
              <h2 className="text-[15px] font-bold text-ink">
                팀 성과 ROI <span className="text-[11px] font-normal text-ink3">(추정)</span>
              </h2>
              <p className="mt-1.5 text-[13px] text-ink2 leading-5">
                팀원 1인당 월 <b>{data.roi.hours_saved_per_agent}시간</b> 절약 × <b>{data.roi.agent_count}명</b>
                {" "}= 팀 전체 <b className="text-brand">{data.roi.team_hours_saved}시간</b> → 상담{" "}
                <b className="text-brand">약 {data.roi.extra_consults}건</b> 환산.
              </p>
              <p className="mt-1 text-[11px] text-ink3">{data.roi.note}</p>
            </Card>
          </>
        )}

        {/* 설계사별 */}
        <div className="mt-5 space-y-2.5">
          {loading ? (
            [1, 2, 3].map((i) => <div key={i} className="h-16 rounded-2xl bg-line animate-pulse" />)
          ) : !data || data.agents.length === 0 ? (
            <Card className="px-4 py-10 text-center">
              <p className="text-[14px] text-ink3">아직 KPI 공유에 동의한 소속 설계사가 없어요.</p>
              <p className="mt-1 text-[12px] text-ink3">
                설계사가 설정에서 “관리직에게 KPI 공유”를 켜고 관리직 이메일을 연결하면 여기에 표시돼요.
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
                    {a.retention_y1 != null && <> · 1년유지 {a.retention_y1}%</>}
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
