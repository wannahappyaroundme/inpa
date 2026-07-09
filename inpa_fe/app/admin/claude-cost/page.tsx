"use client";

// Claude 호출당 비용·파싱 결과 계측 (프리런치 리뷰 #17).
// ★ 비용은 전부 "추정치"(토큰 × 모델 단가 × 환율 추정)입니다. 실제 청구서와 다를 수 있어요.
//   판정어 없이 사실 수치만 표시합니다. 데모 계정(@inpa.local) 제외.

import { useState, useEffect, useCallback } from "react";
import { useAdminGuard } from "@/lib/useAdminGuard";
import { adminGetClaudeCost, type AdminClaudeCostResponse } from "@/lib/adminApi";
import { Card } from "@/components/ui";
import { BarChart, DonutChart } from "@/components/charts";

const KO = new Intl.NumberFormat("ko-KR");

const OUTCOME_LABEL: Record<string, string> = {
  success: "성공",
  empty: "결과 없음",
  json_invalid: "형식 오류",
  api_error: "API 오류",
  timeout: "시간 초과",
  no_key: "키 미설정",
  package_missing: "패키지 없음",
};
const OUTCOME_COLOR: Record<string, string> = {
  success: "var(--brand)",
  empty: "var(--accent)",
  json_invalid: "var(--danger)",
  api_error: "var(--danger)",
  timeout: "var(--danger)",
  no_key: "var(--ink3)",
  package_missing: "var(--ink3)",
};

function won(n: number) {
  return `${KO.format(Math.round(n))}원`;
}

export default function AdminClaudeCostPage() {
  const ready = useAdminGuard();
  const [days, setDays] = useState(30);
  const [data, setData] = useState<AdminClaudeCostResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await adminGetClaudeCost(days));
    } catch {
      setError("비용 데이터를 불러오지 못했어요.");
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => {
    if (ready) load();
  }, [ready, load]);

  if (!ready) return null;

  const outcomeSegments = data
    ? Object.entries(data.outcome_counts)
        .filter(([, v]) => v > 0)
        .map(([k, v]) => ({
          label: OUTCOME_LABEL[k] ?? k,
          value: v,
          color: OUTCOME_COLOR[k] ?? "var(--ink3)",
        }))
    : [];

  const dailyBars =
    data?.daily.map((d) => ({ label: (d.date ?? "").slice(5) || "-", value: d.cost_krw })) ?? [];

  return (
    <div>
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <h1 className="text-[22px] font-extrabold text-ink">Claude 비용·결과 계측</h1>
        <div className="flex gap-1">
          {[7, 30, 90].map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`rounded-lg px-3 py-1.5 text-[13px] font-semibold transition ${
                days === d ? "bg-brand-soft text-brand" : "bg-surface2 text-ink2 hover:bg-line"
              }`}
            >
              {d}일
            </button>
          ))}
        </div>
      </div>
      <p className="mt-1 text-[13px] text-ink3">
        비용은 토큰 수 × 모델 단가 × 환율({data ? KO.format(data.usd_krw_rate) : "-"}원/USD
        가정)로 계산한 <b className="text-ink2">추정치</b>예요. 실제 청구서와 다를 수 있어요.
        (데모 계정 제외)
      </p>

      {error && <div className="mt-4 text-[13px] text-danger">{error}</div>}
      {loading && <div className="mt-6 h-40 rounded-2xl bg-line animate-pulse" />}

      {data && !loading && (
        <>
          <div className="mt-4 grid grid-cols-1 sm:grid-cols-3 gap-2.5">
            <Card className="px-4 py-3">
              <div className="text-[11px] text-ink3">총 호출</div>
              <div className="mt-1 text-[20px] font-extrabold text-ink tnum">
                {KO.format(data.total_calls)}건
              </div>
            </Card>
            <Card className="px-4 py-3">
              <div className="text-[11px] text-ink3">총 추정 비용</div>
              <div className="mt-1 text-[20px] font-extrabold text-ink tnum">
                {won(data.total_cost_krw)}
              </div>
            </Card>
            <Card className="px-4 py-3">
              <div className="text-[11px] text-ink3">성공률</div>
              <div className="mt-1 text-[20px] font-extrabold text-ink tnum">
                {data.success_rate === null ? "-" : `${data.success_rate.toFixed(1)}%`}
              </div>
            </Card>
          </div>

          <div className="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-3">
            <Card className="p-4">
              <div className="text-[13px] font-semibold text-ink mb-2">일별 추정 비용 추이</div>
              <BarChart data={dailyBars} format={won} />
            </Card>
            <Card className="p-4">
              <div className="text-[13px] font-semibold text-ink mb-2">파싱 결과 분포</div>
              {outcomeSegments.length === 0 ? (
                <div className="h-24 flex items-center justify-center text-[12px] text-ink3">
                  데이터가 아직 없어요
                </div>
              ) : (
                <div className="flex items-center gap-4">
                  <DonutChart segments={outcomeSegments} className="w-28 shrink-0" />
                  <div className="flex-1 space-y-1.5">
                    {outcomeSegments.map((s) => (
                      <div key={s.label} className="flex items-center justify-between text-[12px]">
                        <span className="flex items-center gap-1.5 text-ink2">
                          <span
                            className="inline-block w-2 h-2 rounded-full"
                            style={{ background: s.color }}
                          />
                          {s.label}
                        </span>
                        <span className="tnum text-ink font-semibold">{s.value}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </Card>
          </div>

          <Card className="mt-3 overflow-x-auto">
            <div className="px-3 pt-3 text-[13px] font-semibold text-ink">기능별 비용</div>
            <table className="w-full text-[13px] mt-2">
              <thead>
                <tr className="text-ink3 border-b border-line">
                  <th className="text-left font-semibold px-3 py-2">기능</th>
                  <th className="text-right font-semibold px-2 py-2">호출수</th>
                  <th className="text-right font-semibold px-3 py-2">추정 비용</th>
                </tr>
              </thead>
              <tbody>
                {data.by_action.map((a) => (
                  <tr key={a.action} className="border-b border-line/60">
                    <td className="px-3 py-2 text-ink">{a.action}</td>
                    <td className="text-right px-2 py-2 tnum text-ink2">{KO.format(a.calls)}</td>
                    <td className="text-right px-3 py-2 tnum text-ink font-semibold">
                      {won(a.cost_krw)}
                    </td>
                  </tr>
                ))}
                {data.by_action.length === 0 && (
                  <tr>
                    <td colSpan={3} className="px-3 py-8 text-center text-ink3">
                      집계된 호출이 없어요.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </Card>

          <Card className="mt-3 mb-6 overflow-x-auto">
            <div className="px-3 pt-3 text-[13px] font-semibold text-ink">회사별 미매칭 담보 비율</div>
            <p className="px-3 pb-1 text-[11px] text-ink3">
              담보 매칭 실패 건수 ÷ (매칭+미매칭), 회사코드 기준 사실 수치예요.
            </p>
            <table className="w-full text-[13px] mt-1">
              <thead>
                <tr className="text-ink3 border-b border-line">
                  <th className="text-left font-semibold px-3 py-2">회사코드</th>
                  <th className="text-right font-semibold px-2 py-2">매칭</th>
                  <th className="text-right font-semibold px-2 py-2">미매칭</th>
                  <th className="text-right font-semibold px-3 py-2">미매칭율</th>
                </tr>
              </thead>
              <tbody>
                {data.by_carrier.map((c) => (
                  <tr key={c.carrier_code} className="border-b border-line/60">
                    <td className="px-3 py-2 text-ink tnum">{c.carrier_code}</td>
                    <td className="text-right px-2 py-2 tnum text-ink2">{KO.format(c.matched)}</td>
                    <td className="text-right px-2 py-2 tnum text-ink2">{KO.format(c.unmatched)}</td>
                    <td className="text-right px-3 py-2 tnum text-ink font-semibold">
                      {c.unmatched_rate}%
                    </td>
                  </tr>
                ))}
                {data.by_carrier.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-3 py-8 text-center text-ink3">
                      집계된 담보 매칭 데이터가 없어요.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </Card>
        </>
      )}
    </div>
  );
}
