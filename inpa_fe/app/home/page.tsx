"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { AppNav } from "@/components/app-nav";
import { Card } from "@/components/ui";
import { calendar, calendarEvents, eventMeta, todayTasks, type EventType } from "@/lib/mock";
import { useAuthGuard } from "@/lib/useAuthGuard";
import { listCustomers, getProfile, getChurnRadar, syncChurnAlerts, type ProfileResponse, type ChurnRadarResponse } from "@/lib/api";

const WEEK = ["일", "월", "화", "수", "목", "금", "토"];

// 설계사 대시보드. KPI 한 줄(내 고객 수=실API) + 캘린더(일정/업무) + 오늘 할 일.
export default function HomePage() {
  const router = useRouter();
  const ready = useAuthGuard();
  const [sel, setSel] = useState(calendar.today);
  const [profile, setProfile] = useState<ProfileResponse | null>(null);
  const [customerCount, setCustomerCount] = useState<number | null>(null);
  const [churn, setChurn] = useState<ChurnRadarResponse | null>(null);

  const first = new Date(calendar.year, calendar.month - 1, 1).getDay();
  const days = new Date(calendar.year, calendar.month, 0).getDate();
  const cells: (number | null)[] = [
    ...Array(first).fill(null),
    ...Array.from({ length: days }, (_, i) => i + 1),
  ];

  useEffect(() => {
    if (!ready) return;
    // 프로필 & 고객 수 병렬 로드
    getProfile()
      .then((p) => {
        // 온보딩 미완료면 투어로 보냄 (홈 진입 가드)
        if (!p.onboarding_completed_at) {
          router.replace("/onboarding");
          return;
        }
        setProfile(p);
      })
      .catch(() => { /* 토큰 만료 시 useAuthGuard가 처리 */ });
    listCustomers({ page: 1 })
      .then((res) => setCustomerCount(res.count))
      .catch(() => setCustomerCount(null));
    // 환수 위험을 인앱 알림으로 동기화(조용히, dedup) → 그 다음 레이더 집계 로드.
    syncChurnAlerts().catch(() => { /* 무시 */ }).finally(() => {
      getChurnRadar()
        .then((res) => setChurn(res))
        .catch(() => setChurn(null));
    });
  }, [ready, router]);

  if (!ready) return null;

  // 이름 표시: profile.email 앞부분 fallback
  const displayName = profile
    ? profile.email.split("@")[0]
    : "설계사";

  // KPI — 내 고객 수는 실API, 나머지는 자리표시(mock 대신 대시)
  const kpiRows = [
    {
      label: "내 고객",
      value: customerCount !== null ? String(customerCount) : "—",
      unit: "명",
      accent: false,
    },
    { label: "이번 달 만기", value: "—", unit: "건", accent: true },
    { label: "오늘 할 일",    value: "—", unit: "건", accent: false },
    { label: "이번 달 신규",  value: "—", unit: "명", accent: false },
    { label: "미열람 공유",   value: "—", unit: "건", accent: false },
  ];

  return (
    <div className="min-h-dvh">
      <AppNav active="home" />
      <main className="mx-auto max-w-5xl px-4 sm:px-6 py-6">
        <div className="flex items-end justify-between">
          <h1 className="text-[22px] font-extrabold text-ink">
            안녕하세요, {displayName} 설계사님{" "}
            <span className="font-normal">👋</span>
          </h1>
          <span className="hidden sm:block text-[13px] text-ink3 tnum">
            {calendar.year}.{String(calendar.month).padStart(2, "0")}.
            {String(calendar.today).padStart(2, "0")}
          </span>
        </div>

        {/* KPI 한 줄 */}
        <div className="mt-4 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          {kpiRows.map((k) => (
            <Card key={k.label} className="px-4 py-3.5">
              <div className="text-[12px] text-ink3">{k.label}</div>
              <div className="mt-1 flex items-baseline gap-1">
                <span
                  className={`text-[24px] font-extrabold tnum ${
                    k.accent ? "text-accent" : "text-ink"
                  }`}
                >
                  {k.value}
                </span>
                <span className="text-[13px] text-ink3">{k.unit}</span>
              </div>
            </Card>
          ))}
        </div>

        {/* 환수 레이더(A/S) — 보유계약 납입/유지율 위험. 클릭 시 수기입력·점검 */}
        <button
          onClick={() => router.push("/churn-radar")}
          className={`mt-4 w-full text-left rounded-2xl border px-4 py-3.5 flex items-center gap-3 transition active:scale-[0.997] ${
            churn && churn.risk_count > 0
              ? "border-rose-200 bg-rose-50 hover:bg-rose-100"
              : "border-line bg-surface2 hover:bg-surface"
          }`}
        >
          <span className="text-[22px]">{churn && churn.risk_count > 0 ? "⚠️" : "🛡️"}</span>
          <div className="flex-1 min-w-0">
            <div className="text-[14px] font-bold text-ink">
              환수 레이더
              {churn && churn.risk_count > 0 && (
                <span className="ml-2 text-rose-700">위험 {churn.risk_count}건</span>
              )}
            </div>
            <div className="text-[12px] text-ink3 mt-0.5">
              {churn === null
                ? "보유계약 납입상태·유지율(13/25회차)을 점검하세요"
                : churn.risk_count > 0
                ? `예상 환수액(추정) ₩${new Intl.NumberFormat("ko-KR").format(churn.expected_recovery_total)} · 지금 확인`
                : "현재 환수 위험 없음 · 납입정보 입력·점검"}
            </div>
          </div>
          <span className="text-ink3 text-[18px] shrink-0">›</span>
        </button>

        {/* 캘린더 + 오늘 일정 */}
        <div className="mt-5 lg:grid lg:grid-cols-3 lg:gap-5">
          <Card className="lg:col-span-2 p-4 sm:p-5">
            <div className="flex items-center justify-between mb-3">
              <button className="w-8 h-8 rounded-lg hover:bg-surface2 text-ink2 text-[18px]">
                ‹
              </button>
              <div className="text-[16px] font-bold text-ink">
                {calendar.year}년 {calendar.month}월
              </div>
              <button className="w-8 h-8 rounded-lg hover:bg-surface2 text-ink2 text-[18px]">
                ›
              </button>
            </div>
            <div className="grid grid-cols-7 text-center text-[12px] mb-1">
              {WEEK.map((w, i) => (
                <div key={w} className={i === 0 ? "text-danger" : "text-ink3"}>
                  {w}
                </div>
              ))}
            </div>
            <div className="grid grid-cols-7">
              {cells.map((d, i) => {
                if (!d) return <div key={i} />;
                const isSun = i % 7 === 0;
                const isToday = d === calendar.today;
                const isSel = d === sel;
                let cls = isSun ? "text-danger" : "text-ink2";
                if (isToday && !isSel) cls = "text-brand font-bold";
                if (isSel) cls = "bg-brand text-white font-bold";
                const evs = calendarEvents[d];
                return (
                  <div
                    key={i}
                    className="flex flex-col items-center pt-1.5 pb-1 min-h-[52px]"
                  >
                    <button
                      onClick={() => setSel(d)}
                      className={`w-9 h-9 rounded-full flex items-center justify-center text-[14px] font-medium ${cls}`}
                    >
                      {d}
                    </button>
                    {evs && (
                      <div className="flex gap-0.5 mt-1">
                        {evs.slice(0, 3).map((e, j) => (
                          <span
                            key={j}
                            className={`w-1.5 h-1.5 rounded-full ${eventMeta[e].dot}`}
                          />
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
            <div className="mt-3 flex flex-wrap gap-3 text-[12px] text-ink3">
              {(Object.keys(eventMeta) as EventType[]).map((e) => (
                <span key={e} className="inline-flex items-center gap-1.5">
                  <span className={`w-2 h-2 rounded-full ${eventMeta[e].dot}`} />
                  {eventMeta[e].label}
                </span>
              ))}
            </div>
          </Card>

          <Card className="mt-4 lg:mt-0 p-4 sm:p-5">
            <div className="text-[15px] font-bold text-ink mb-3">
              오늘의 일정 · 할 일
            </div>
            <div className="space-y-3.5">
              {todayTasks.map((t, i) => (
                <div key={i} className="flex gap-3">
                  <div className="text-[12px] font-semibold text-ink3 w-11 shrink-0 tnum pt-0.5">
                    {t.time}
                  </div>
                  <div className="flex-1 flex items-start gap-2">
                    <span
                      className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${eventMeta[t.type].dot}`}
                    />
                    <span className="text-[14px] text-ink leading-5">{t.title}</span>
                  </div>
                </div>
              ))}
            </div>
            <button className="mt-4 w-full rounded-xl border border-line text-[13px] font-semibold text-brand py-2.5 hover:bg-accent-tint transition">
              + 일정 · 업무 추가
            </button>
          </Card>
        </div>
      </main>
    </div>
  );
}
