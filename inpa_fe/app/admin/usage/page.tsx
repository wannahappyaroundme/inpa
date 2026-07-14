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
  callback_request: "연락 요청",
  referral_attributed: "인바운드 귀속",
};

// 설계사가 직접 한 행동 vs 고객이 공유 링크에 반응한 것 (BE AdminUsageView 분류와 동일).
const PLANNER_EVENTS = ["ocr_upload", "analysis_view", "share_created", "clipboard_copy"];
const CUSTOMER_EVENTS = ["share_view", "callback_request", "referral_attributed"];
const EVENT_ORDER = [...PLANNER_EVENTS, ...CUSTOMER_EVENTS];

const RANGES = [
  { v: 7, l: "7일" },
  { v: 30, l: "30일" },
  { v: 90, l: "90일" },
  { v: 0, l: "전체" },
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
      <div className="flex items-start justify-between gap-3 flex-wrap mb-6">
        <div>
          <h1 className="text-[22px] font-extrabold text-ink">사용량 트래킹</h1>
          <p className="mt-1 text-[13px] text-ink3">
            설계사가 직접 한 활동과 고객이 공유 링크에 보인 반응을 나눠서 집계해요. 순위는 설계사
            활동 기준이라, 고객이 링크를 여러 번 열어도 순위가 부풀지 않아요. (데모 계정 제외)
          </p>
        </div>
        <div className="flex gap-1">
          {RANGES.map((r) => (
            <button
              key={r.v}
              onClick={() => setDays(r.v)}
              className={`rounded-lg px-3 py-1.5 text-[13px] font-semibold transition ${
                days === r.v ? "bg-brand-soft text-brand" : "bg-surface2 text-ink2 hover:bg-line"
              }`}
            >
              {r.l}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 rounded-xl bg-danger-tint border border-line text-[13px] text-danger-ink">
          {error}
        </div>
      )}
      {loading && <div className="mt-2 h-40 rounded-2xl bg-line animate-pulse" />}

      {data && !loading && (
        <>
          {/* 기능별 총합 — 설계사 활동 / 고객 반응 두 갈래 */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <div>
              <div className="mb-2 flex items-baseline justify-between">
                <span className="text-[13px] font-bold text-ink">설계사 활동</span>
                <span className="text-[12px] text-ink3 tnum">
                  합 {data.group_totals?.planner_activity ?? 0}
                </span>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                {PLANNER_EVENTS.map((e) => (
                  <Card key={e} className="px-4 py-3.5">
                    <div className="text-[11px] text-ink3">{EVENT_LABEL[e]}</div>
                    <div className="mt-1 text-[18px] font-extrabold text-ink tnum">
                      {data.feature_totals[e] ?? 0}
                    </div>
                  </Card>
                ))}
              </div>
            </div>
            <div>
              <div className="mb-2 flex items-baseline justify-between">
                <span className="text-[13px] font-bold text-ink">고객 반응</span>
                <span className="text-[12px] text-ink3 tnum">
                  합 {data.group_totals?.customer_response ?? 0}
                </span>
              </div>
              <div className="grid grid-cols-3 gap-3">
                {CUSTOMER_EVENTS.map((e) => (
                  <Card key={e} className="px-4 py-3.5">
                    <div className="text-[11px] text-ink3">{EVENT_LABEL[e]}</div>
                    <div className="mt-1 text-[18px] font-extrabold text-ink tnum">
                      {data.feature_totals[e] ?? 0}
                    </div>
                  </Card>
                ))}
              </div>
            </div>
          </div>
          <p className="mt-3 text-[12px] text-ink3">
            활성 설계사 {data.active_users}명 · 최근 {data.days === 0 ? "전체 기간" : `${data.days}일`}
          </p>

          {/* 설계사별 사용량 순위 — 설계사 활동 합 기준 내림차순 */}
          <Card className="mt-3 overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="text-ink3 border-b border-line">
                  <th rowSpan={2} className="text-left font-semibold px-3 py-2.5 align-bottom">설계사</th>
                  <th
                    colSpan={PLANNER_EVENTS.length + 1}
                    className="text-center font-bold px-2 py-1.5 text-ink2 border-l border-line"
                  >
                    설계사 활동
                  </th>
                  <th
                    colSpan={CUSTOMER_EVENTS.length + 1}
                    className="text-center font-bold px-2 py-1.5 text-ink2 border-l border-line"
                  >
                    고객 반응
                  </th>
                </tr>
                <tr className="text-ink3 border-b border-line">
                  <th className="text-right font-bold px-2 py-2 whitespace-nowrap border-l border-line">활동 합</th>
                  {PLANNER_EVENTS.map((e) => (
                    <th key={e} className="text-right font-semibold px-2 py-2 whitespace-nowrap">
                      {EVENT_LABEL[e]}
                    </th>
                  ))}
                  <th className="text-right font-bold px-2 py-2 whitespace-nowrap border-l border-line">반응 합</th>
                  {CUSTOMER_EVENTS.map((e) => (
                    <th key={e} className="text-right font-semibold px-2 py-2 whitespace-nowrap">
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
                    <td className="text-right px-2 py-2.5 font-bold text-ink tnum border-l border-line/60">
                      {u.planner_activity}
                    </td>
                    {PLANNER_EVENTS.map((e) => (
                      <td key={e} className="text-right px-2 py-2.5 tnum text-ink2">
                        {u.events[e] ?? 0}
                      </td>
                    ))}
                    <td className="text-right px-2 py-2.5 font-bold text-ink tnum border-l border-line/60">
                      {u.customer_response}
                    </td>
                    {CUSTOMER_EVENTS.map((e) => (
                      <td key={e} className="text-right px-2 py-2.5 tnum text-ink2">
                        {u.events[e] ?? 0}
                      </td>
                    ))}
                  </tr>
                ))}
                {data.users.length === 0 && (
                  <tr>
                    <td
                      colSpan={3 + EVENT_ORDER.length}
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
