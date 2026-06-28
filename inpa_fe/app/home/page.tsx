"use client";

import { useState, useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";
import { AppNav } from "@/components/app-nav";
import { Card, StatCard } from "@/components/ui";
import { BarChart, DonutChart } from "@/components/charts";
import { SelfDiagnosisShare } from "@/components/self-diagnosis-share";
import { useAuthGuard } from "@/lib/useAuthGuard";
import {
  listCustomers, getProfile, getChurnRadar, syncChurnAlerts, listMeetings,
  getDashboard, updateDashboardGoal, listNotifications, listScheduleItems,
  getDashboardInsights, SALES_STAGES,
  type ProfileResponse, type ChurnRadarResponse, type Meeting, type DashboardSummary, type NotificationItem,
  type ScheduleItem, type DashboardInsights,
} from "@/lib/api";

const WEEK = ["일", "월", "화", "수", "목", "금", "토"];
const krw = new Intl.NumberFormat("ko-KR");
function fmtWonShort(v: number): string {
  if (v >= 100_000_000) return `${krw.format(Math.round((v / 100_000_000) * 10) / 10)}억`;
  if (v >= 10_000) return `${krw.format(Math.round(v / 10_000))}만`;
  return krw.format(v);
}
function pct(actual: number, target: number): number {
  return target > 0 ? Math.min(100, Math.round((actual / target) * 100)) : 0;
}
const pad = (n: number) => String(n).padStart(2, "0");

// 일정/알림 종류별 점 색·라벨 (실데이터 = 내 일정/할일/차단 + 미팅 + 리마인더 알림)
type Kind = "schedule" | "todo" | "block" | "meeting" | "expiry" | "birthday" | "consult" | "task" | "other";
const META: Record<Kind, { dot: string; label: string }> = {
  schedule: { dot: "bg-brand", label: "일정" },
  todo: { dot: "bg-over", label: "할일" },
  block: { dot: "bg-muted", label: "차단" },
  meeting: { dot: "bg-enough", label: "미팅" },
  expiry: { dot: "bg-cnone", label: "만기·미납" },
  birthday: { dot: "bg-short", label: "생일" },
  consult: { dot: "bg-existing", label: "상담" },
  task: { dot: "bg-over", label: "리드·알림" },
  other: { dot: "bg-muted", label: "알림" },
};
function notifKind(t: string): Kind {
  switch (t) {
    case "expiry_soon":
    case "unpaid_d_alert": return "expiry";
    case "birthday_soon": return "birthday";
    case "consult_reminder": return "consult";
    case "self_diagnosis_lead":
    case "task_due": return "task";
    default: return "other";
  }
}

// ISO(+09:00) → Asia/Seoul 기준 'YYYY-MM-DD' / 'HH:mm'
function kstYmd(iso: string): string {
  try {
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit",
    }).format(new Date(iso));
  } catch { return iso.slice(0, 10); }
}
function kstTime(iso: string): string {
  try {
    return new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", hour12: false,
    }).format(new Date(iso));
  } catch { return ""; }
}
function hhmmToMin(t: string): number {
  const [h, m] = t.split(":").map(Number);
  return (h || 0) * 60 + (m || 0);
}

interface AgendaItem { ymd: string; time: string; title: string; kind: Kind; sort: number }

function GoalRow({ label, actual, target, unit, won }: { label: string; actual: number; target: number; unit?: string; won?: boolean }) {
  const p = pct(actual, target);
  const fmt = (v: number) => (won ? fmtWonShort(v) : krw.format(v));
  return (
    <div>
      <div className="flex items-baseline justify-between mb-1">
        <span className="text-[13px] text-ink2">{label}</span>
        <span className="text-[13px] text-ink3 tnum">
          <b className="text-ink text-[15px]">{fmt(actual)}</b> / {target > 0 ? fmt(target) : "—"}{unit ? ` ${unit}` : won ? "원" : ""}
          <span className="ml-1.5 font-bold text-brand">{p}%</span>
        </span>
      </div>
      <div className="h-2 rounded-full bg-surface2 overflow-hidden">
        <div className="h-full bg-brand rounded-full transition-all" style={{ width: `${p}%` }} />
      </div>
    </div>
  );
}

function fmtMeeting(iso: string): string {
  try {
    return new Intl.DateTimeFormat("ko-KR", {
      month: "numeric", day: "numeric", weekday: "short",
      hour: "numeric", minute: "2-digit", timeZone: "Asia/Seoul",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

// 설계사 대시보드. KPI(실API) + 목표 + 환수레이더 + 캘린더(실제 미팅·리마인더) + 선택일 일정.
export default function HomePage() {
  const router = useRouter();
  const ready = useAuthGuard();
  const [profile, setProfile] = useState<ProfileResponse | null>(null);
  const [customerCount, setCustomerCount] = useState<number | null>(null);
  const [churn, setChurn] = useState<ChurnRadarResponse | null>(null);
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [notifs, setNotifs] = useState<NotificationItem[]>([]);
  const [scheduleItems, setScheduleItems] = useState<ScheduleItem[]>([]);
  const [dash, setDash] = useState<DashboardSummary | null>(null);
  const [insights, setInsights] = useState<DashboardInsights | null>(null);
  const [trendMonths, setTrendMonths] = useState<3 | 6 | 12 | 24>(12);
  const [editGoal, setEditGoal] = useState(false);
  const [gMeet, setGMeet] = useState(0);
  const [gPrem, setGPrem] = useState(0);
  const [gMult, setGMult] = useState(10);
  const [goalSaving, setGoalSaving] = useState(false);

  // 캘린더가 보는 연·월 (실제 오늘 기준) + 선택일
  const now = new Date();
  const todayY = now.getFullYear();
  const todayM = now.getMonth() + 1;
  const todayD = now.getDate();
  const [viewY, setViewY] = useState(todayY);
  const [viewM, setViewM] = useState(todayM);
  const [selDay, setSelDay] = useState(todayD);

  useEffect(() => {
    if (!ready) return;
    getProfile()
      .then((p) => {
        if (!p.onboarding_completed_at) { router.replace("/onboarding"); return; }
        setProfile(p);
      })
      .catch(() => { /* 토큰 만료 시 useAuthGuard가 처리 */ });
    listCustomers({ page: 1 })
      .then((res) => setCustomerCount(res.count))
      .catch(() => setCustomerCount(null));
    listMeetings(true)
      .then((res) => setMeetings(res.results))
      .catch(() => setMeetings([]));
    listNotifications({ page: 1 })
      .then((res) => setNotifs(res.results))
      .catch(() => setNotifs([]));
    getDashboard()
      .then((d) => {
        setDash(d);
        setGMeet(d.target_meetings); setGPrem(d.target_premium); setGMult(d.income_multiplier);
      })
      .catch(() => setDash(null));
    syncChurnAlerts().catch(() => { /* 무시 */ }).finally(() => {
      getChurnRadar().then((res) => setChurn(res)).catch(() => setChurn(null));
    });
  }, [ready, router]);

  // 기간 필터 변경 시 insights 재조회 (기간 버튼 포함)
  useEffect(() => {
    if (!ready) return;
    getDashboardInsights({ months: trendMonths }).then(setInsights).catch(() => setInsights(null));
  }, [ready, trendMonths]);

  // 보고 있는 달의 내 일정/할일/차단 로드(월 이동 시 갱신)
  useEffect(() => {
    if (!ready) return;
    listScheduleItems({ month: `${viewY}-${pad(viewM)}` })
      .then((r) => setScheduleItems(r.results))
      .catch(() => setScheduleItems([]));
  }, [ready, viewY, viewM]);

  // 내 일정/할일/차단 + 미팅 + 리마인더 알림 → 날짜별 일정 맵
  const agenda = useMemo(() => {
    const map = new Map<string, AgendaItem[]>();
    const add = (it: AgendaItem) => { const a = map.get(it.ymd) ?? []; a.push(it); map.set(it.ymd, a); };
    for (const s of scheduleItems) {
      if (s.kind === "block" && s.recur_weekday !== null) continue; // 반복차단은 /schedule 풀뷰에서만
      if (!s.start_at) continue;
      const t = s.all_day ? "" : kstTime(s.start_at);
      const k: Kind = s.kind === "event" ? "schedule" : s.kind === "todo" ? "todo" : "block";
      add({ ymd: kstYmd(s.start_at), time: t || "종일", title: s.title, kind: k, sort: t ? hhmmToMin(t) : -1 });
    }
    for (const m of meetings) {
      const t = kstTime(m.start_at);
      add({ ymd: kstYmd(m.start_at), time: t || "—", title: `${m.customer_name} · ${m.method_display}`, kind: "meeting", sort: t ? hhmmToMin(t) : 0 });
    }
    for (const n of notifs) {
      if (!n.target_date) continue;
      add({ ymd: n.target_date, time: "온종일", title: n.title, kind: notifKind(n.notif_type), sort: -1 });
    }
    for (const [, arr] of map) arr.sort((a, b) => a.sort - b.sort);
    return map;
  }, [scheduleItems, meetings, notifs]);

  async function saveGoal() {
    setGoalSaving(true);
    try {
      const d = await updateDashboardGoal({ target_meetings: gMeet, target_premium: gPrem, income_multiplier: gMult });
      setDash(d);
      setEditGoal(false);
    } catch {
      /* 무시 — 재시도 가능 */
    } finally {
      setGoalSaving(false);
    }
  }

  function shiftMonth(delta: number) {
    let y = viewY, m = viewM + delta;
    if (m < 1) { m = 12; y--; }
    if (m > 12) { m = 1; y++; }
    setViewY(y); setViewM(m);
  }

  if (!ready) return null;

  // 이번 달 경과 — 남은 일수 · 경과 %
  const _dim = new Date(todayY, todayM, 0).getDate();
  const monthDaysLeft = _dim - todayD;
  const monthPct = Math.round((todayD / _dim) * 100);

  const displayName = profile ? (profile.name?.trim() || profile.email.split("@")[0]) : "설계사";

  // 전월 대비 증감률(%) — 최근 6개월 추이의 마지막 두 점에서 파생. 데이터 부족 시 null(배지 숨김).
  const trend = insights?.monthly_trend ?? [];
  const tCur = trend[trend.length - 1];
  const tPrev = trend[trend.length - 2];
  const momDelta = (key: "premium" | "new_customers" | "meetings"): number | null => {
    if (!tCur || !tPrev) return null;
    const a = tCur[key], b = tPrev[key];
    if (b === 0) return a > 0 ? 100 : null;
    return Math.round(((a - b) / b) * 100);
  };

  // 막대 추이(월별 보험료) · 도넛(보유계약 유지현황)
  const trendBars = trend.map((t) => ({ label: `${Number(t.ym.slice(5, 7))}월`, value: t.premium }));
  // 목표선: 기간 내 MonthlyGoal이 있는 달의 target_premium 평균 (0 제외, 없으면 undefined)
  const trendTargets = trend.map((t) => t.target_premium).filter((v): v is number => v != null && v > 0);
  const targetLine = trendTargets.length > 0
    ? Math.round(trendTargets.reduce((s, v) => s + v, 0) / trendTargets.length)
    : undefined;
  // 평균선: 보험료 평균 (0 제외, 데이터가 2개 이상일 때만)
  const trendPremiums = trend.map((t) => t.premium).filter((v) => v > 0);
  const averageLine = trendPremiums.length >= 2
    ? Math.round(trendPremiums.reduce((s, v) => s + v, 0) / trendPremiums.length)
    : undefined;
  const pf = insights?.portfolio;
  const portfolioSegs = pf
    ? [
        { label: "유지 안정", value: pf.stable, color: "var(--success)" },
        { label: "주의(13/25회차)", value: pf.watch, color: "var(--warning)" },
        { label: "환수 위험", value: pf.at_risk, color: "var(--danger)" },
        { label: "회차 미입력", value: pf.unknown, color: "var(--muted)" },
      ]
    : [];
  const portfolioTotal = portfolioSegs.reduce((s, x) => s + x.value, 0);

  // 캘린더 셀
  const first = new Date(viewY, viewM - 1, 1).getDay();
  const days = new Date(viewY, viewM, 0).getDate();
  const cells: (number | null)[] = [
    ...Array(first).fill(null),
    ...Array.from({ length: days }, (_, i) => i + 1),
  ];
  const isCurrentMonth = viewY === todayY && viewM === todayM;

  const selectedYmd = `${viewY}-${pad(viewM)}-${pad(selDay)}`;
  const selectedItems = agenda.get(selectedYmd) ?? [];
  const agendaTitle = isCurrentMonth && selDay === todayD ? "오늘의 일정 · 할 일" : `${viewM}월 ${selDay}일 일정`;

  return (
    <div className="min-h-dvh">
      <AppNav active="home" />
      <main className="mx-auto max-w-5xl px-4 sm:px-6 py-6">
        <div className="flex items-end justify-between">
          <h1 className="text-[22px] font-extrabold text-ink">
            안녕하세요, {displayName} 설계사님 <span className="font-normal">👋</span>
          </h1>
          <span className="hidden sm:block text-[13px] text-ink3 tnum">
            {todayY}.{pad(todayM)}.{pad(todayD)}
          </span>
        </div>

        {/* 발굴 입구 — 셀프진단 링크로 새 고객(인바운드) 받기. refCode 없으면 위젯이 null 반환 */}
        <div className="mt-4">
          <SelfDiagnosisShare />
        </div>

        {/* KPI 한 줄 — 전부 실데이터(+ 전월 대비 증감률) */}
        <div className="mt-4 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          <StatCard label="내 고객" value={customerCount !== null ? String(customerCount) : "—"} unit="명" />
          <StatCard label="이번 달 신규" value={dash ? String(dash.actual_new_customers) : "—"} unit="명" delta={momDelta("new_customers")} />
          <StatCard label="이번 달 미팅" value={dash ? String(dash.actual_meetings) : "—"} unit="건" delta={momDelta("meetings")} />
          <StatCard label="이번 달 보험료" value={dash ? fmtWonShort(dash.actual_premium) : "—"} unit="원" delta={momDelta("premium")} />
          <StatCard label="환수 위험" value={churn ? String(churn.risk_count) : "—"} unit="건" accent={!!churn && churn.risk_count > 0}
            hint="고객이 계약을 해지하면 이미 받은 수수료가 환수(반환)될 수 있어요. 최근 해지·연락 두절 등 위험 신호가 있는 고객 수예요." />
        </div>

        {/* 영업 4단계 퍼널 — 단계별 고객(클릭 시 칸반) */}
        {insights && (
          <button onClick={() => router.push("/customers")} className="mt-4 block w-full text-left">
            <Card className="p-4 sm:p-5 hover:bg-surface2 transition">
              <div className="flex items-center justify-between mb-3">
                <div className="text-[15px] font-bold text-ink">영업 단계별 고객</div>
                <span className="text-[12px] font-semibold text-brand">칸반 보기 →</span>
              </div>
              <div className="grid grid-cols-4 gap-2">
                {SALES_STAGES.map((s) => (
                  <div key={s.key}>
                    <div className="text-[11px] text-ink3 tnum">{s.short}</div>
                    <div className="text-[12px] text-ink2 truncate">{s.label}</div>
                    <div className="mt-0.5 text-[20px] font-extrabold text-ink tnum">
                      {insights.funnel[s.key]}
                      <span className="ml-0.5 text-[12px] font-normal text-ink3">{s.key === "contract" ? "건" : "명"}</span>
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          </button>
        )}

        {/* 월별 보험료 추이(막대) + 보유계약 유지현황(도넛) */}
        {insights && (
          <div className="mt-4 lg:grid lg:grid-cols-3 lg:gap-4">
            <Card className="lg:col-span-2 p-4 sm:p-5">
              <div className="flex items-center justify-between mb-3">
                <div className="text-[15px] font-bold text-ink">월별 보험료 추이</div>
                <div className="flex gap-1">
                  {([3, 6, 12, 24] as const).map((m) => (
                    <button
                      key={m}
                      onClick={() => setTrendMonths(m)}
                      className={`px-2 py-0.5 rounded text-[11px] font-medium transition-colors ${
                        trendMonths === m
                          ? "bg-brand text-white"
                          : "bg-surface2 text-ink3 hover:text-ink"
                      }`}
                    >
                      {m === 3 ? "3개월" : m === 6 ? "6개월" : m === 12 ? "1년" : "2년"}
                    </button>
                  ))}
                </div>
              </div>
              <BarChart
                data={trendBars}
                format={(n) => fmtWonShort(n)}
                targetLine={targetLine}
                averageLine={averageLine}
              />
            </Card>
            <Card className="mt-4 lg:mt-0 p-4 sm:p-5">
              <div className="text-[15px] font-bold text-ink mb-3">보유계약 유지현황</div>
              {portfolioTotal > 0 ? (
                <div className="flex items-center gap-4">
                  <DonutChart className="w-24 shrink-0" segments={portfolioSegs} centerValue={String(portfolioTotal)} centerLabel="보유계약" />
                  <ul className="flex-1 space-y-1.5">
                    {portfolioSegs.map((s) => (
                      <li key={s.label} className="flex items-center justify-between text-[12px]">
                        <span className="inline-flex items-center gap-1.5 text-ink2">
                          <span className="w-2 h-2 rounded-full" style={{ background: s.color }} />
                          {s.label}
                        </span>
                        <span className="tnum font-semibold text-ink">{s.value}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : (
                <div className="py-6 text-center text-[13px] text-ink3">
                  보유계약이 아직 없어요.
                  <div className="text-[12px] mt-1">증권을 등록하면 유지현황이 표시돼요.</div>
                </div>
              )}
            </Card>
          </div>
        )}

        {/* 계약 유지율(추정) 1/2/3년 — PM 06.24 */}
        {insights && (
          <Card className="mt-4 p-4 sm:p-5">
            <div className="text-[15px] font-bold text-ink mb-3">
              계약 유지율 <span className="text-[11px] font-normal text-ink3">(추정)</span>
            </div>
            {insights.retention.has_cancellation_data ? (
              <>
                <div className="grid grid-cols-3 gap-3">
                  {([["y1", "1년"], ["y2", "2년"], ["y3", "3년"]] as const).map(([k, label]) => {
                    const r = insights.retention[k];
                    return (
                      <div key={k} className="rounded-xl bg-surface2 px-3 py-3 text-center">
                        <div className="text-[11px] text-ink3">{label}</div>
                        <div className="mt-1 text-[20px] font-extrabold tnum text-ink">{r.rate == null ? "—" : `${Math.round(r.rate)}%`}</div>
                        <div className="text-[11px] text-ink3 tnum">{r.survived}/{r.reached}건</div>
                      </div>
                    );
                  })}
                </div>
                <p className="mt-2 text-[11px] text-ink3">해지 입력 기준 추정치예요.</p>
              </>
            ) : (
              <div className="rounded-xl bg-surface2 px-4 py-5 text-center text-[13px] text-ink3 leading-6">
                아직 해지 입력이 없어 유지율을 계산하지 않았어요.
                <div className="text-[12px] mt-0.5">환수 레이더에서 해지된 계약을 표시하면 1·2·3년 유지율이 나와요.</div>
              </div>
            )}
          </Card>
        )}

        {/* 이번 달 목표 — 수동 설정 + 실적 진행률 */}
        {dash && (
          <Card className="mt-4 p-4 sm:p-5">
            <div className="flex items-center justify-between mb-3">
              <div className="text-[15px] font-bold text-ink">이번 달 목표</div>
              {editGoal ? (
                <div className="flex gap-3">
                  <button
                    onClick={() => { setEditGoal(false); setGMeet(dash.target_meetings); setGPrem(dash.target_premium); setGMult(dash.income_multiplier); }}
                    className="text-[13px] text-ink3"
                  >
                    취소
                  </button>
                  <button onClick={saveGoal} disabled={goalSaving} className="text-[13px] font-bold text-brand disabled:opacity-60">저장</button>
                </div>
              ) : (
                <button onClick={() => setEditGoal(true)} className="text-[13px] font-semibold text-brand">목표 수정</button>
              )}
            </div>

            {/* 이번 달 경과 — 남은 일수 · 경과 % */}
            <div className="mb-4">
              <div className="flex items-baseline justify-between text-[12px]">
                <span className="text-ink3">이번 달 경과</span>
                <span className="text-ink2 tnum"><b className="text-ink">D-{monthDaysLeft}</b> · {monthPct}% 지남</span>
              </div>
              <div className="mt-1 h-1.5 rounded-full bg-surface2 overflow-hidden">
                <div className="h-full bg-muted rounded-full" style={{ width: `${monthPct}%` }} />
              </div>
            </div>

            {editGoal ? (
              <div className="space-y-3">
                <label className="flex items-center justify-between gap-3">
                  <span className="text-[13px] text-ink2">만날 고객 (명)</span>
                  <div className="flex items-center gap-1.5">
                    <button onClick={() => setGMeet((v) => Math.max(0, v - 1))} className="w-7 h-7 rounded-lg border border-line text-ink2">−</button>
                    <input type="number" min={0} value={gMeet} onChange={(e) => setGMeet(Math.max(0, Number(e.target.value) || 0))} className="w-16 text-center rounded-lg border border-line py-1.5 text-[14px] tnum" />
                    <button onClick={() => setGMeet((v) => v + 1)} className="w-7 h-7 rounded-lg border border-line text-ink2">+</button>
                  </div>
                </label>
                <label className="flex items-center justify-between gap-3">
                  <span className="text-[13px] text-ink2">가입 보험료 (원)</span>
                  <input type="number" min={0} step={10000} value={gPrem} onChange={(e) => setGPrem(Math.max(0, Number(e.target.value) || 0))} className="w-40 text-right rounded-lg border border-line px-2 py-1.5 text-[14px] tnum" />
                </label>
                <label className="flex items-center justify-between gap-3">
                  <span className="text-[13px] text-ink2">예상 월급 배율 (×가입보험료)</span>
                  <div className="flex items-center gap-1.5">
                    <button onClick={() => setGMult((v) => Math.max(0, v - 1))} className="w-7 h-7 rounded-lg border border-line text-ink2">−</button>
                    <input type="number" min={0} step={1} value={gMult} onChange={(e) => setGMult(Math.max(0, Number(e.target.value) || 0))} className="w-16 text-center rounded-lg border border-line py-1.5 text-[14px] tnum" />
                    <button onClick={() => setGMult((v) => v + 1)} className="w-7 h-7 rounded-lg border border-line text-ink2">+</button>
                  </div>
                </label>
                <p className="text-[11px] text-ink3 leading-4">예상 월급 = <b>가입 보험료(실적) × 배율</b>(기본 10배, 직접 수정). 만날 고객·가입 보험료 실적은 자동 반영돼요.</p>
              </div>
            ) : (
              <div className="space-y-3.5">
                <GoalRow label="만날 고객" actual={dash.actual_meetings} target={dash.target_meetings} unit="명" />
                <GoalRow label="가입 보험료" actual={dash.actual_premium} target={dash.target_premium} won />
                <div className="flex items-center justify-between">
                  <span className="text-[13px] text-ink2">
                    예상 월급 <span className="text-ink3">(가입보험료 ×{dash.income_multiplier})</span>
                  </span>
                  <span className="text-[15px] font-extrabold tnum text-accent">
                    {dash.expected_income > 0 ? `${fmtWonShort(dash.expected_income)}원` : "—"}
                  </span>
                </div>
              </div>
            )}
          </Card>
        )}

        {/* 환수 레이더(A/S) — 보유계약 납입/유지율 위험. 클릭 시 수기입력·점검 */}
        <button
          onClick={() => router.push("/churn-radar")}
          className={`mt-4 w-full text-left rounded-2xl border px-4 py-3.5 flex items-center gap-3 transition active:scale-[0.997] ${
            churn && churn.risk_count > 0
              ? "border-cnone/30 bg-danger-tint hover:bg-danger-tint/70"
              : "border-line bg-surface2 hover:bg-surface"
          }`}
        >
          <span className="text-[22px]">{churn && churn.risk_count > 0 ? "⚠️" : "🛡️"}</span>
          <div className="flex-1 min-w-0">
            <div className="text-[14px] font-bold text-ink">
              환수 레이더
              {churn && churn.risk_count > 0 && (
                <span className="ml-2 text-danger-ink">위험 {churn.risk_count}건</span>
              )}
            </div>
            <div className="text-[12px] text-ink3 mt-0.5">
              {churn === null
                ? "보유계약 납입상태·유지율(13/25회차)을 점검하세요"
                : churn.risk_count > 0
                ? `예상 환수액(추정) ${fmtWonShort(churn.expected_recovery_total)}원 · 지금 확인`
                : "현재 환수 위험 없음 · 납입정보 입력·점검"}
            </div>
          </div>
          <span className="text-ink3 text-[18px] shrink-0">›</span>
        </button>

        {/* 다가오는 미팅(예약 확정) — 실데이터 */}
        {meetings.length > 0 && (
          <Card className="mt-4 p-4 sm:p-5">
            <div className="flex items-center justify-between mb-2">
              <div className="text-[14px] font-bold text-ink">다가오는 미팅</div>
              <button onClick={() => router.push("/settings/meetings")} className="text-[12px] font-semibold text-brand">
                관리 →
              </button>
            </div>
            <div className="divide-y divide-line">
              {meetings.slice(0, 4).map((m) => (
                <div key={m.id} className="py-2">
                  <div className="text-[13px] font-semibold text-ink">
                    {fmtMeeting(m.start_at)} · {m.customer_name}
                  </div>
                  <div className="text-[12px] text-ink3">
                    {m.method_display}{m.location_detail ? ` · ${m.location_detail}` : ""}
                  </div>
                </div>
              ))}
            </div>
          </Card>
        )}

        {/* 캘린더(실제 월·미팅·리마인더) + 선택일 일정 */}
        <div className="mt-5 lg:grid lg:grid-cols-3 lg:gap-5">
          <Card className="lg:col-span-2 p-4 sm:p-5">
            <div className="flex items-center justify-between mb-3">
              <button onClick={() => shiftMonth(-1)} className="w-8 h-8 rounded-lg hover:bg-surface2 text-ink2 text-[18px]">
                ‹
              </button>
              <div className="text-[16px] font-bold text-ink">
                {viewY}년 {viewM}월
              </div>
              <button onClick={() => shiftMonth(1)} className="w-8 h-8 rounded-lg hover:bg-surface2 text-ink2 text-[18px]">
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
                const isToday = isCurrentMonth && d === todayD;
                const isSel = d === selDay;
                let cls = isSun ? "text-danger" : "text-ink2";
                if (isToday && !isSel) cls = "text-brand font-bold";
                if (isSel) cls = "bg-brand text-white font-bold";
                const ymd = `${viewY}-${pad(viewM)}-${pad(d)}`;
                const items = agenda.get(ymd);
                const kinds = items ? Array.from(new Set(items.map((it) => it.kind))).slice(0, 3) : [];
                return (
                  <div key={i} className="flex flex-col items-center pt-1.5 pb-1 min-h-[52px]">
                    <button
                      onClick={() => setSelDay(d)}
                      aria-label={`${viewM}월 ${d}일${kinds.length > 0 ? ` · 일정 ${items?.length ?? 0}건` : ""}`}
                      aria-pressed={d === selDay}
                      className={`w-9 h-9 rounded-full flex items-center justify-center text-[14px] font-medium ${cls}`}
                    >
                      {d}
                    </button>
                    {kinds.length > 0 && (
                      <div className="flex gap-0.5 mt-1">
                        {kinds.map((k, j) => (
                          <span key={j} className={`w-1.5 h-1.5 rounded-full ${META[k].dot}`} />
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
            <div className="mt-3 flex flex-wrap gap-3 text-[12px] text-ink3">
              {(Object.keys(META) as Kind[]).map((k) => (
                <span key={k} className="inline-flex items-center gap-1.5">
                  <span className={`w-2 h-2 rounded-full ${META[k].dot}`} />
                  {META[k].label}
                </span>
              ))}
            </div>
          </Card>

          <Card className="mt-4 lg:mt-0 p-4 sm:p-5">
            <div className="text-[15px] font-bold text-ink mb-3">{agendaTitle}</div>
            {selectedItems.length > 0 ? (
              <div className="space-y-3.5">
                {selectedItems.map((t, i) => (
                  <div key={i} className="flex gap-3">
                    <div className="text-[12px] font-semibold text-ink3 w-11 shrink-0 tnum pt-0.5">
                      {t.time}
                    </div>
                    <div className="flex-1 flex items-start gap-2">
                      <span className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${META[t.kind].dot}`} />
                      <span className="text-[14px] text-ink leading-5">{t.title}</span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="py-6 text-center text-[13px] text-ink3">
                예정된 일정이 없어요.
                <div className="text-[12px] mt-1">미팅·리마인더가 생기면 여기에 표시돼요.</div>
              </div>
            )}
            <button
              onClick={() => router.push("/schedule")}
              className="mt-4 w-full rounded-xl border border-line text-[13px] font-semibold text-brand py-2.5 hover:bg-accent-tint transition"
            >
              일정 전체 보기 · 추가 →
            </button>
          </Card>
        </div>
      </main>
    </div>
  );
}
