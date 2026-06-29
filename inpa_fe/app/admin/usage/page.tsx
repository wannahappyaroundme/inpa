"use client";

// 어드민 사용량 트래킹 — 설계사별 기능 사용량(NorthStarEvent 집계). 데모 계정(@inpa.local) 제외.

import { useState, useEffect, useCallback } from "react";
import { useAdminGuard } from "@/lib/useAdminGuard";
import { adminGetUsage, type AdminUsageResponse } from "@/lib/adminApi";
import { Card } from "@/components/ui";

const EVENT_LABEL: Record<string, string> = {
  ocr_upload: "증권 OCR",
  analysis_view: "분석 조회",
  share_created: "공유링크 발급",
  clipboard_copy: "복사",
  share_view: "공유뷰 열람",
  referral_attributed: "인바운드 귀속",
};
const EVENT_ORDER = [
  "ocr_upload",
  "analysis_view",
  "share_created",
  "clipboard_copy",
  "share_view",
  "referral_attributed",
];

export default function AdminUsagePage() {
  const ready = useAdminGuard();
  const [days, setDays] = useState(30);
  const [data, setData] = useState<AdminUsageResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await adminGetUsage(days));
    } catch {
      setError("사용량을 불러오지 못했어요.");
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => {
    if (ready) load();
  }, [ready, load]);

  if (!ready) return null;

  return (
    <div>
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <h1 className="text-[22px] font-extrabold text-ink">사용량 트래킹</h1>
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
        설계사가 어떤 기능을 많이 쓰는지 집계예요. (데모 계정 제외)
      </p>

      {error && <div className="mt-4 text-[13px] text-danger">{error}</div>}
      {loading && <div className="mt-6 h-40 rounded-2xl bg-line animate-pulse" />}

      {data && !loading && (
        <>
          {/* 기능별 총합 */}
          <div className="mt-4 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5">
            {EVENT_ORDER.map((e) => (
              <Card key={e} className="px-3 py-3">
                <div className="text-[11px] text-ink3">{EVENT_LABEL[e]}</div>
                <div className="mt-1 text-[18px] font-extrabold text-ink tnum">
                  {data.feature_totals[e] ?? 0}
                </div>
              </Card>
            ))}
          </div>
          <p className="mt-3 text-[12px] text-ink3">
            활성 설계사 {data.active_users}명 · 최근 {data.days}일
          </p>

          {/* 설계사별 사용량 순위 */}
          <Card className="mt-3 overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="text-ink3 border-b border-line">
                  <th className="text-left font-semibold px-3 py-2.5">설계사</th>
                  <th className="text-right font-semibold px-2 py-2.5">총</th>
                  {EVENT_ORDER.map((e) => (
                    <th key={e} className="text-right font-semibold px-2 py-2.5 whitespace-nowrap">
                      {EVENT_LABEL[e]}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.users.map((u) => (
                  <tr key={u.user_id} className="border-b border-line/60">
                    <td className="px-3 py-2.5">
                      <div className="font-semibold text-ink">{u.name || "(이름 없음)"}</div>
                      <div className="text-[11px] text-ink3 truncate max-w-[180px]">{u.email}</div>
                    </td>
                    <td className="text-right px-2 py-2.5 font-bold text-ink tnum">{u.total}</td>
                    {EVENT_ORDER.map((e) => (
                      <td key={e} className="text-right px-2 py-2.5 tnum text-ink2">
                        {u.events[e] ?? 0}
                      </td>
                    ))}
                  </tr>
                ))}
                {data.users.length === 0 && (
                  <tr>
                    <td
                      colSpan={2 + EVENT_ORDER.length}
                      className="px-3 py-8 text-center text-ink3"
                    >
                      집계된 사용량이 없어요.
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
