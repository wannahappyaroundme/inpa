"use client";

// 활성화 퍼널 — 가입→인증→첫 고객→첫 분석→첫 공유→활성화 코호트 계측 (프리런치 리뷰 #16).
// ★ 활성화 = 첫 분석 AND 첫 공유 링크가 모두 가입 후 activation_window_days(기본 7일) 이내.
//   사실 수치만(§6 판정어 금지). 데모 계정(@inpa.local) 제외.

import { useState, useEffect, useCallback } from "react";
import { useAdminGuard } from "@/lib/useAdminGuard";
import { adminGetActivationFunnel, type AdminActivationFunnelResponse } from "@/lib/adminApi";
import { Card } from "@/components/ui";
import { BarChart } from "@/components/charts";

const KO = new Intl.NumberFormat("ko-KR");

function pct(n: number | null) {
  return n === null ? "-" : `${n.toFixed(1)}%`;
}

export default function AdminActivationFunnelPage() {
  const ready = useAdminGuard();
  const [days, setDays] = useState(30);
  const [data, setData] = useState<AdminActivationFunnelResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await adminGetActivationFunnel(days));
    } catch {
      setError("퍼널 데이터를 불러오지 못했어요.");
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => {
    if (ready) load();
  }, [ready, load]);

  if (!ready) return null;

  const funnelBars = data?.steps.map((s) => ({ label: s.label, value: s.count })) ?? [];

  return (
    <div>
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <h1 className="text-[22px] font-extrabold text-ink">활성화 퍼널</h1>
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
        가입 코호트(창 내 신규 가입) 기준 단계별 인원과 전환율이에요. 활성화 = 첫 분석과 첫 공유
        링크가 모두 가입 후{" "}
        <b className="text-ink2">{data ? data.activation_window_days : "-"}일</b> 이내인 경우예요.
        (데모 계정 제외)
      </p>

      {error && <div className="mt-4 text-[13px] text-danger">{error}</div>}
      {loading && <div className="mt-6 h-40 rounded-2xl bg-line animate-pulse" />}

      {data && !loading && (
        <>
          <div className="mt-4 grid grid-cols-1 sm:grid-cols-4 gap-2.5">
            <Card className="px-4 py-3">
              <div className="text-[11px] text-ink3">가입 수</div>
              <div className="mt-1 text-[20px] font-extrabold text-ink tnum">
                {KO.format(data.signup_count)}명
              </div>
            </Card>
            <Card className="px-4 py-3">
              <div className="text-[11px] text-ink3">활성화 수</div>
              <div className="mt-1 text-[20px] font-extrabold text-ink tnum">
                {KO.format(data.activated_count)}명
              </div>
            </Card>
            <Card className="px-4 py-3">
              <div className="text-[11px] text-ink3">활성화율</div>
              <div className="mt-1 text-[20px] font-extrabold text-ink tnum">
                {pct(data.activation_rate)}
              </div>
            </Card>
            <Card className="px-4 py-3">
              <div className="text-[11px] text-ink3">평균 활성화 소요일</div>
              <div className="mt-1 text-[20px] font-extrabold text-ink tnum">
                {data.avg_days_to_activation === null ? "-" : `${data.avg_days_to_activation}일`}
              </div>
            </Card>
          </div>

          <Card className="mt-4 p-4">
            <div className="text-[13px] font-semibold text-ink mb-2">단계별 인원</div>
            <BarChart data={funnelBars} heightClass="h-40" highlightLast={false} />
          </Card>

          <Card className="mt-3 overflow-x-auto">
            <div className="px-3 pt-3 text-[13px] font-semibold text-ink">단계별 전환율</div>
            <p className="px-3 pb-1 text-[11px] text-ink3">직전 단계 대비 전환율(%)이에요.</p>
            <table className="w-full text-[13px] mt-1">
              <thead>
                <tr className="text-ink3 border-b border-line">
                  <th className="text-left font-semibold px-3 py-2">단계</th>
                  <th className="text-right font-semibold px-2 py-2">인원</th>
                  <th className="text-right font-semibold px-3 py-2">전환율</th>
                </tr>
              </thead>
              <tbody>
                {data.steps.map((s) => (
                  <tr key={s.step} className="border-b border-line/60">
                    <td className="px-3 py-2 text-ink">{s.label}</td>
                    <td className="text-right px-2 py-2 tnum text-ink2">{KO.format(s.count)}</td>
                    <td className="text-right px-3 py-2 tnum text-ink font-semibold">
                      {pct(s.conversion_rate)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>

          <Card className="mt-3 mb-6 overflow-x-auto">
            <div className="px-3 pt-3 text-[13px] font-semibold text-ink">유입 소스별 가입·활성화</div>
            <p className="px-3 pb-1 text-[11px] text-ink3">
              utm_source 기준이에요. 값이 없으면 '직접 유입'으로 묶어요.
            </p>
            <table className="w-full text-[13px] mt-1">
              <thead>
                <tr className="text-ink3 border-b border-line">
                  <th className="text-left font-semibold px-3 py-2">유입 소스</th>
                  <th className="text-right font-semibold px-2 py-2">가입</th>
                  <th className="text-right font-semibold px-2 py-2">활성화</th>
                  <th className="text-right font-semibold px-3 py-2">활성화율</th>
                </tr>
              </thead>
              <tbody>
                {data.utm_sources.map((row) => (
                  <tr key={row.source} className="border-b border-line/60">
                    <td className="px-3 py-2 text-ink">
                      {row.source === "direct" ? "직접 유입" : row.source}
                    </td>
                    <td className="text-right px-2 py-2 tnum text-ink2">{KO.format(row.signups)}</td>
                    <td className="text-right px-2 py-2 tnum text-ink2">{KO.format(row.activated)}</td>
                    <td className="text-right px-3 py-2 tnum text-ink font-semibold">
                      {pct(row.activation_rate)}
                    </td>
                  </tr>
                ))}
                {data.utm_sources.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-3 py-8 text-center text-ink3">
                      집계된 가입이 없어요.
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
