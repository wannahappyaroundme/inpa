"use client";

import { useState, useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";
import {
  Users, UserPlus, CalendarCheck, Wallet,
  ChevronRight, MessageSquare, Calendar as CalendarIcon, Activity,
  Link2, Gift, X, type LucideIcon,
} from "lucide-react";
import { AppNav } from "@/components/app-nav";
import { Card, StatCard, SectionTitle } from "@/components/ui";
import { BarChart, DonutChart } from "@/components/charts";
import { SelfDiagnosisShare } from "@/components/self-diagnosis-share";
import { useAuthGuard } from "@/lib/useAuthGuard";
import {
  listCustomers, getProfile, listMeetings,
  getDashboard, updateDashboardGoal, listScheduleItems,
  getDashboardInsights, SALES_STAGES, funnelConversion,
  type ProfileResponse, type Meeting, type DashboardSummary,
  type ScheduleItem, type ScheduleCategory, type DashboardInsights,
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

// 대시보드 캘린더 색·라벨 — 일정 탭과 동일한 5분류(고객미팅/생일·기념일/만기·갱신/업무/기타).
type Cat = ScheduleCategory;
const CAT_META: Record<Cat, { dot: string; label: string }> = {
  meeting: { dot: "bg-brand", label: "고객미팅" },
  anniversary: { dot: "bg-pink-400", label: "생일·기념일" },
  renewal: { dot: "bg-amber-400", label: "만기·갱신" },
  task: { dot: "bg-emerald-500", label: "업무" },
  etc: { dot: "bg-muted", label: "기타" },
};

// 영업 단계 컬러 — '우리 4색'의 soft 배경. 01 회색 / 02 빨강(TA) / 03 노랑(FA) / 04 초록(청약).
const STAGE_TONE: Record<string, { bg: string; fg: string }> = {
  db:       { bg: "bg-surface2",  fg: "text-ink3" },
  contact:  { bg: "bg-neg-soft",  fg: "text-neg" },
  meeting:  { bg: "bg-warn-soft", fg: "text-warn-ink" },
  contract: { bg: "bg-pos-soft",  fg: "text-pos-ink" },
};

// 하단 퀵액션 바(레퍼런스 1번 하단) — 인파 동등 기능 바로가기.
const QUICK_ACTIONS: { label: string; href: string; icon: LucideIcon }[] = [
  { label: "고객 목록", href: "/customers", icon: Users },
  { label: "보장 분석", href: "/analysis", icon: Activity },
  { label: "상담 예약", href: "/settings/meetings", icon: CalendarCheck },
  { label: "상담 화법", href: "/scripts", icon: MessageSquare },
  { label: "일정 관리", href: "/schedule", icon: CalendarIcon },
];

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

interface AgendaItem { ymd: string; time: string; title: string; cat: Cat; sort: number }

// 일정/할일/차단 + 미팅 → 날짜별 일정 맵. (캘린더 = 보는 달, 오늘 카드 = 이번 달 전용으로 각각 호출)
function buildAgenda(scheduleItems: ScheduleItem[], meetings: Meeting[], year: number, month: number): Map<string, AgendaItem[]> {
  const map = new Map<string, AgendaItem[]>();
  const add = (it: AgendaItem) => { const a = map.get(it.ymd) ?? []; a.push(it); map.set(it.ymd, a); };
  for (const s of scheduleItems) {
    if (s.kind === "block" && s.recur_weekday !== null) continue; // 반복차단은 /schedule 풀뷰에서만
    // 생일·기념일: anniversary_md(MM-DD)로 매년 반복 — 보는 달이면 그 해 날짜에 표시(/schedule과 동일)
    if (s.category === "anniversary" && s.anniversary_md) {
      const [mm, dd] = s.anniversary_md.split("-");
      if (mm === pad(month)) add({ ymd: `${year}-${mm}-${dd}`, time: "종일", title: `🎂 ${s.title}`, cat: "anniversary", sort: -1 });
      continue;
    }
    if (!s.start_at) continue;
    const t = s.all_day ? "" : kstTime(s.start_at);
    const cat: Cat = s.kind === "block" ? "etc" : s.category;
    add({ ymd: kstYmd(s.start_at), time: t || "종일", title: s.title, cat, sort: t ? hhmmToMin(t) : -1 });
  }
  for (const m of meetings) {
    if (m.status !== "confirmed") continue; // 확정된 미팅만 캘린더에 표시(대기·취소·거절 제외)
    const t = kstTime(m.start_at);
    add({ ymd: kstYmd(m.start_at), time: t || "-", title: `${m.customer_name} · ${m.method_display}`, cat: "meeting", sort: t ? hhmmToMin(t) : 0 });
  }
  for (const [, arr] of map) arr.sort((a, b) => a.sort - b.sort);
  return map;
}

function GoalRow({ label, actual, target, unit, won }: { label: string; actual: number; target: number; unit?: string; won?: boolean }) {
  const p = pct(actual, target);
  const fmt = (v: number) => (won ? fmtWonShort(v) : krw.format(v));
  return (
    <div>
      <div className="flex items-baseline justify-between mb-1">
        <span className="text-[13px] text-ink2">{label}</span>
        <span className="text-[13px] text-ink3 tnum">
          <b className="text-ink text-[15px]">{fmt(actual)}</b> / {target > 0 ? fmt(target) : "-"}{unit ? ` ${unit}` : won ? "원" : ""}
          <span className="ml-1.5 font-bold text-brand">{p}%</span>
        </span>
      </div>
      <div className="h-2 rounded-full bg-surface2 overflow-hidden">
        <div className="h-full bg-brand rounded-full transition-all" style={{ width: `${p}%` }} />
      </div>
    </div>
  );
}

// 설계사 대시보드. KPI(실API) + 목표 + 캘린더(실제 미팅·일정) + 선택일 일정.
export default function HomePage() {
  const router = useRouter();
  const ready = useAuthGuard();
  const [profile, setProfile] = useState<ProfileResponse | null>(null);
  const [customerCount, setCustomerCount] = useState<number | null>(null);
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [scheduleItems, setScheduleItems] = useState<ScheduleItem[]>([]);
  const [todayScheduleItems, setTodayScheduleItems] = useState<ScheduleItem[]>([]); // 보는 달과 무관하게 '오늘 카드'용(이번 달 고정)
  const [dash, setDash] = useState<DashboardSummary | null>(null);
  const [insights, setInsights] = useState<DashboardInsights | null>(null);
  const [trendMonths, setTrendMonths] = useState<3 | 6>(6);
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
  const [dayModalOpen, setDayModalOpen] = useState(false); // 캘린더 날짜 클릭 시 그 날 일정 모달

  // 로더 무음 실패 방지 — 어느 로더든 하나라도 실패하면 상단 배너 1개(카드별 배너 금지, §6 소음 방지).
  // '다시 시도' = reloadKey 증가 → 아래 로더 이펙트 전부 재실행.
  const [loadFailed, setLoadFailed] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  function retryAll() {
    setLoadFailed(false);
    setReloadKey((k) => k + 1);
  }

  useEffect(() => {
    if (!ready) return;
    getProfile()
      .then((p) => {
        if (!p.onboarding_completed_at) { router.replace("/onboarding"); return; }
        setProfile(p);
      })
      .catch(() => setLoadFailed(true)); // 401(토큰 만료)은 api.ts가 로그인으로 이동 → 배너는 그 외 실패용
    listCustomers({ page: 1 })
      .then((res) => setCustomerCount(res.count))
      .catch(() => { setCustomerCount(null); setLoadFailed(true); });
    // 캘린더는 지난·진행 중 미팅도 그려야 하므로 upcoming 필터 없이 전체를 받아 날짜별로 표시.
    listMeetings(false)
      .then((res) => setMeetings(res.results))
      .catch(() => { setMeetings([]); setLoadFailed(true); });
    getDashboard()
      .then((d) => {
        setDash(d);
        setGMeet(d.target_meetings); setGPrem(d.target_premium); setGMult(d.income_multiplier);
      })
      .catch(() => { setDash(null); setLoadFailed(true); });
  }, [ready, router, reloadKey]);

  // 기간 필터 변경 시 insights 재조회 (기간 버튼 포함)
  useEffect(() => {
    if (!ready) return;
    getDashboardInsights({ months: trendMonths })
      .then(setInsights)
      .catch(() => { setInsights(null); setLoadFailed(true); });
  }, [ready, trendMonths, reloadKey]);

  // 보고 있는 달의 내 일정/할일/차단 로드(월 이동 시 갱신) — 캘린더용
  useEffect(() => {
    if (!ready) return;
    listScheduleItems({ month: `${viewY}-${pad(viewM)}` })
      .then((r) => setScheduleItems(r.results))
      .catch(() => { setScheduleItems([]); setLoadFailed(true); });
  }, [ready, viewY, viewM, reloadKey]);

  // 이번 달 일정(오늘 카드용) — 캘린더를 다른 달로 넘겨도 '오늘 일정'은 항상 보이게 별도 로드.
  useEffect(() => {
    if (!ready) return;
    listScheduleItems({ month: `${todayY}-${pad(todayM)}` })
      .then((r) => setTodayScheduleItems(r.results))
      .catch(() => { setTodayScheduleItems([]); setLoadFailed(true); });
  }, [ready, todayY, todayM, reloadKey]);

  // 날짜별 일정 맵 — 캘린더(보는 달) / 오늘 카드(이번 달) 각각. (알림은 우측 상단 종에서만)
  const agenda = useMemo(() => buildAgenda(scheduleItems, meetings, viewY, viewM), [scheduleItems, meetings, viewY, viewM]);
  const todayAgenda = useMemo(() => buildAgenda(todayScheduleItems, meetings, todayY, todayM), [todayScheduleItems, meetings, todayY, todayM]);

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
  const quickActions = QUICK_ACTIONS;

  // 전월 대비 증감률(%) — 백엔드 계산 우선, 없으면 추이의 마지막 두 점에서 파생.
  const trend = insights?.monthly_trend ?? [];
  const tCur = trend[trend.length - 1];
  const tPrev = trend[trend.length - 2];
  const momDelta = (key: "premium" | "new_customers" | "meetings"): number | null => {
    const be = dash?.deltas?.[key];
    if (be && be.pct !== null && be.pct !== undefined) return be.pct;
    if (!tCur || !tPrev) return null;
    const a = tCur[key], b = tPrev[key];
    if (b === 0) return a > 0 ? 100 : null;
    return Math.round(((a - b) / b) * 100);
  };

  // 막대 추이(월별 보험료) · 도넛(보유계약 유지현황)
  const trendBars = trend.map((t) => ({ label: `${Number(t.ym.slice(5, 7))}월`, value: t.premium }));
  const trendTargets = trend.map((t) => t.target_premium).filter((v): v is number => v != null && v > 0);
  const targetLine = trendTargets.length > 0
    ? Math.round(trendTargets.reduce((s, v) => s + v, 0) / trendTargets.length)
    : undefined;
  const trendPremiums = trend.map((t) => t.premium).filter((v) => v > 0);
  const averageLine = trendPremiums.length >= 2
    ? Math.round(trendPremiums.reduce((s, v) => s + v, 0) / trendPremiums.length)
    : undefined;
  const pf = insights?.portfolio;
  const portfolioSegs = pf
    ? [
        { label: "유지 안정 (25회차+)", value: pf.stable, color: "var(--success)" },
        { label: "정착 중 (25회차 전)", value: pf.watch, color: "var(--warning)" },
        { label: "초기 (13회차 전)", value: pf.at_risk, color: "var(--danger)" },
        { label: "회차 미상", value: pf.unknown, color: "var(--muted)" },
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
  const selectedItems = agenda.get(selectedYmd) ?? [];                 // 모달(클릭한 날짜)
  const dayModalTitle = isCurrentMonth && selDay === todayD ? "오늘 일정" : `${viewM}월 ${selDay}일 일정`;
  const todayYmd = `${todayY}-${pad(todayM)}-${pad(todayD)}`;
  const todayItems = todayAgenda.get(todayYmd) ?? [];                  // 우측 레일 카드(항상 오늘)

  // 이번 달 목표 달성률(게이지) — 가입 보험료 기준.
  const goalGaugePct = dash ? pct(dash.actual_premium, dash.target_premium) : 0;

  return (
    <div className="min-h-dvh">
      <AppNav active="home" />
      <main className="mx-auto max-w-[1440px] px-4 sm:px-6 py-6">
        {/* 인사 + 날짜 */}
        <div className="flex items-end justify-between">
          <h1 className="text-[24px] sm:text-[26px] font-extrabold text-ink tracking-tight">
            안녕하세요, {displayName} 설계사님 <span className="font-normal">👋</span>
          </h1>
          <span className="hidden sm:block text-[13px] text-ink3 tnum">
            {todayY}.{pad(todayM)}.{pad(todayD)}
          </span>
        </div>

        {/* 로더 실패 통합 배너 — 하나라도 실패하면 여기 1개만(카드별 배너 없음). 다시 시도 = 전체 재로드 */}
        {loadFailed && (
          <div
            role="alert"
            className="mt-4 flex items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 px-3.5 py-2.5 text-[13px]"
          >
            <span className="text-amber-800">일부 정보를 못 불러왔어요.</span>
            <button
              type="button"
              onClick={retryAll}
              className="shrink-0 rounded-lg bg-surface px-3 py-1.5 text-[12px] font-semibold text-brand border border-line hover:border-brand transition"
            >
              다시 시도
            </button>
          </div>
        )}

        {/* ── 1행: 이번 달 목표(8) + 오늘의 일정(4) — 같은 높이(items-stretch) ── */}
        <div className="mt-4 grid grid-cols-12 gap-4 items-stretch">
          {/* 이번 달 목표 + 달성률 게이지 */}
          <Card className="col-span-12 lg:col-span-8 p-4 sm:p-5 flex flex-col">
            <div className="flex items-center justify-between mb-3">
              <div className="text-[15px] font-bold text-ink">이번 달 목표</div>
              {editGoal ? (
                <div className="flex gap-3">
                  <button
                    onClick={() => { setEditGoal(false); if (dash) { setGMeet(dash.target_meetings); setGPrem(dash.target_premium); setGMult(dash.income_multiplier); } }}
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

            {/* 이번 달 경과 */}
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
                  <input type="number" min={0} step={10000} value={gPrem} onChange={(e) => setGPrem(Math.max(0, Number(e.target.value) || 0))} className="flex-1 max-w-[160px] text-right rounded-lg border border-line px-2 py-1.5 text-[14px] tnum" />
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
              <div className="flex items-center gap-5 flex-1">
                <div className="flex-1 min-w-0 space-y-3.5">
                  <GoalRow label="만날 고객" actual={dash?.actual_meetings ?? 0} target={dash?.target_meetings ?? 0} unit="명" />
                  <GoalRow label="가입 보험료" actual={dash?.actual_premium ?? 0} target={dash?.target_premium ?? 0} won />
                  <div className="flex items-center justify-between">
                    <span className="text-[13px] text-ink2">
                      예상 월급 <span className="text-ink3">(가입보험료 ×{dash?.income_multiplier ?? 10})</span>
                    </span>
                    <span className="text-[15px] font-extrabold tnum text-accent">
                      {dash && dash.expected_income > 0 ? `${fmtWonShort(dash.expected_income)}원` : "-"}
                    </span>
                  </div>
                </div>
                <DonutChart
                  className="hidden sm:block w-28 shrink-0"
                  segments={[
                    { label: "달성", value: goalGaugePct, color: "var(--brand)" },
                    { label: "남음", value: Math.max(0, 100 - goalGaugePct), color: "var(--line)" },
                  ]}
                  centerValue={`${goalGaugePct}%`}
                  centerLabel="달성률"
                />
              </div>
            )}
          </Card>

          {/* 오늘의 일정 · 할 일 — 항상 '금일'만(캘린더 선택과 무관). 목표와 같은 높이 */}
          <Card className="col-span-12 lg:col-span-4 p-4 sm:p-5 flex flex-col">
            <div className="text-[15px] font-bold text-ink mb-3">오늘의 일정 · 할 일</div>
            {todayItems.length > 0 ? (
              <div className="space-y-3.5">
                {todayItems.map((t, i) => (
                  <div key={i} className="flex gap-3">
                    <div className="text-[12px] font-semibold text-ink3 w-11 shrink-0 tnum pt-0.5">{t.time}</div>
                    <div className="flex-1 flex items-start gap-2">
                      <span className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${CAT_META[t.cat].dot}`} />
                      <span className="text-[14px] text-ink leading-5">{t.title}</span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex-1 flex flex-col items-center justify-center py-6 text-center text-[13px] text-ink3">
                예정된 일정이 없어요.
                <div className="text-[12px] mt-1">미팅·일정이 생기면 여기에 표시돼요.</div>
              </div>
            )}
            <button
              onClick={() => router.push("/schedule")}
              className="mt-auto pt-4 w-full rounded-xl border border-line text-[13px] font-semibold text-brand py-2.5 hover:bg-brand-soft transition"
            >
              일정 전체 보기 · 추가 →
            </button>
          </Card>
        </div>

        {/* ── 2행: 좌(통계·파이프라인·차트) 8 + 우 레일(유지현황·예약·판촉) 4 — 같은 높이 ── */}
        <div className="mt-4 grid grid-cols-12 gap-4 items-stretch">
          {/* ───── 왼쪽 8칸 ───── */}
          <div className="col-span-12 lg:col-span-8 space-y-4">
            {/* 통계 카드 4개 */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <StatCard icon={Users} tone="brand" label="내 고객" value={customerCount !== null ? String(customerCount) : "-"} unit="명" />
              <StatCard icon={UserPlus} tone="brand" label="이번 달 신규" value={dash ? String(dash.actual_new_customers) : "-"} unit="명" delta={momDelta("new_customers")} />
              <StatCard icon={CalendarCheck} tone="brand" label="이번 달 미팅" value={dash ? String(dash.actual_meetings) : "-"} unit="건" delta={momDelta("meetings")} />
              <StatCard icon={Wallet} tone="brand" label="이번 달 보험료" value={dash ? fmtWonShort(dash.actual_premium) : "-"} unit="원" delta={momDelta("premium")} />
            </div>

            {/* 영업 4단계 파이프라인 */}
            {insights && (
              <Card className="p-4 sm:p-5">
                <SectionTitle
                  title="영업 단계별 고객"
                  action={
                    <button onClick={() => router.push("/customers")} className="text-[12px] font-semibold text-brand">
                      단계별 보기 →
                    </button>
                  }
                />
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                  {SALES_STAGES.map((s, i) => {
                    const tone = STAGE_TONE[s.key] ?? STAGE_TONE.db;
                    return (
                      <div key={s.key} className="relative">
                        <button
                          type="button"
                          onClick={() => router.push(`/customers?stage=${s.key}`)}
                          className={`w-full text-left rounded-xl p-4 ${tone.bg} hover:shadow-cardhover transition`}
                        >
                          <div className="flex items-center gap-1.5">
                            <span className={`text-[13px] font-extrabold tnum ${tone.fg}`}>{s.short}</span>
                            <span className="text-[13px] font-semibold text-ink">{s.label}</span>
                          </div>
                          <p className="mt-2 flex items-baseline gap-0.5">
                            <span className="text-[26px] font-extrabold text-ink tnum leading-none">{insights.funnel[s.key]}</span>
                            <span className="text-[12px] font-normal text-ink3">{s.key === "contract" ? "건" : "명"}</span>
                          </p>
                        </button>
                        {i < SALES_STAGES.length - 1 && (
                          <ChevronRight className="hidden lg:block absolute -right-3 top-1/2 -translate-y-1/2 w-5 h-5 text-muted z-10 pointer-events-none" strokeWidth={2.5} />
                        )}
                      </div>
                    );
                  })}
                </div>
                {/* 단계 전환율(스냅샷) — 지금까지 각 단계를 넘어간 비율 */}
                <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink3">
                  <span className="font-semibold text-ink2">단계 전환율</span>
                  {funnelConversion(insights.funnel).map((c) => {
                    const fl = SALES_STAGES.find((s) => s.key === c.from)?.label;
                    const tl = SALES_STAGES.find((s) => s.key === c.to)?.label;
                    return (
                      <span key={c.from} className="inline-flex items-center gap-1">
                        {fl}→{tl} <b className="text-ink tnum">{c.rate == null ? "-" : `${c.rate}%`}</b>
                      </span>
                    );
                  })}
                  <span className="text-muted">지금까지 넘어간 비율</span>
                </div>
              </Card>
            )}

          </div>

          {/* 우 4: 월별 보험료 추이 — 좌측(통계+단계) 높이만큼 채움 */}
          {insights && (
            <Card className="col-span-12 lg:col-span-4 p-4 sm:p-5 flex flex-col min-h-[260px] lg:min-h-0">
              <div className="flex items-center justify-between mb-3">
                <div className="text-[15px] font-bold text-ink">월별 보험료 추이</div>
                <div className="flex gap-1">
                  {([3, 6] as const).map((m) => (
                    <button
                      key={m}
                      onClick={() => setTrendMonths(m)}
                      className={`px-2.5 py-1 rounded-lg text-[11px] font-semibold transition-colors ${
                        trendMonths === m ? "bg-brand text-white" : "bg-surface2 text-ink3 hover:text-ink"
                      }`}
                    >
                      {m === 3 ? "3개월" : "6개월"}
                    </button>
                  ))}
                </div>
              </div>
              <BarChart data={trendBars} format={(n) => fmtWonShort(n)} targetLine={targetLine} averageLine={averageLine} heightClass="h-full" className="flex-1 min-h-0" />
            </Card>
          )}
        </div>

        {/* ── 2-B행: 좌(캘린더 + 셀프진단) 8 + 우(유지현황 + 예약/판촉) 4 ── */}
        <div className="mt-4 grid grid-cols-12 gap-4 items-stretch">
          {/* 좌 8: 캘린더 + 무료 보장점검(셀프진단) 링크 */}
          <div className="col-span-12 lg:col-span-8 grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* 캘린더(실제 월·미팅·일정) */}
            <Card className="p-4 sm:p-5">
                <div className="flex items-center justify-between mb-3">
                  <button onClick={() => shiftMonth(-1)} className="w-8 h-8 rounded-lg hover:bg-surface2 text-ink2 text-[18px]">‹</button>
                  <div className="text-[16px] font-bold text-ink">{viewY}년 {viewM}월</div>
                  <button onClick={() => shiftMonth(1)} className="w-8 h-8 rounded-lg hover:bg-surface2 text-ink2 text-[18px]">›</button>
                </div>
                <div className="grid grid-cols-7 text-center text-[12px] mb-1">
                  {WEEK.map((w, i) => (
                    <div key={w} className={i === 0 ? "text-danger" : "text-ink3"}>{w}</div>
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
                    const cats = items ? Array.from(new Set(items.map((it) => it.cat))).slice(0, 3) : [];
                    return (
                      <div key={i} className="flex flex-col items-center pt-1.5 pb-1 min-h-[52px]">
                        <button
                          onClick={() => { setSelDay(d); setDayModalOpen(true); }}
                          aria-label={`${viewM}월 ${d}일${cats.length > 0 ? ` · 일정 ${items?.length ?? 0}건` : ""}`}
                          aria-pressed={d === selDay}
                          className={`w-9 h-9 rounded-full flex items-center justify-center text-[14px] font-medium ${cls}`}
                        >
                          {d}
                        </button>
                        {cats.length > 0 && (
                          <div className="flex gap-0.5 mt-1">
                            {cats.map((c, j) => (
                              <span key={j} className={`w-1.5 h-1.5 rounded-full ${CAT_META[c].dot}`} />
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
                <div className="mt-3 flex flex-wrap gap-3 text-[12px] text-ink3">
                  {(Object.keys(CAT_META) as Cat[]).map((c) => (
                    <span key={c} className="inline-flex items-center gap-1.5">
                      <span className={`w-2 h-2 rounded-full ${CAT_META[c].dot}`} />
                      {CAT_META[c].label}
                    </span>
                  ))}
                </div>
              </Card>

            {/* 무료 보장점검(셀프진단) 링크 — 캘린더 옆 prominent 슬롯(그리드 stretch + fill로 높이 꽉) */}
            <SelfDiagnosisShare fill />
          </div>

          {/* 우 4: 유지현황 + 상담예약/판촉물 */}
          <div className="col-span-12 lg:col-span-4 flex flex-col gap-4">
            {/* 보유계약 유지현황(도넛) → 클릭 시 유지 회차 타이머. flex-1로 레일 잔여 높이 흡수(캘린더 높이 맞춤) */}
            {insights && (
              <button onClick={() => router.push("/churn-radar")} className="block w-full text-left flex-1">
                <Card className="p-4 sm:p-5 hover:shadow-cardhover transition h-full flex flex-col">
                  <div className="flex items-center justify-between mb-3">
                    <div className="text-[15px] font-bold text-ink">보유계약 유지현황</div>
                    <span className="text-[12px] font-semibold text-brand">회차 타이머 →</span>
                  </div>
                {portfolioTotal > 0 ? (
                  <div className="flex items-center gap-4 flex-1">
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
              </button>
            )}

            {/* 상담 예약 링크 + 판촉물 신청 — 가로형 카드(아이콘 · 텍스트 · 버튼) */}
            <div className="space-y-4">
              <Card className="p-4 flex items-center gap-3">
                <span className="shrink-0 w-10 h-10 rounded-xl grid place-items-center bg-brand-soft text-brand" aria-hidden>
                  <Link2 className="w-5 h-5" strokeWidth={2} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-[14px] font-bold text-ink">상담 예약 링크</div>
                  <p className="text-[12px] text-ink3 mt-0.5 leading-5">예약 링크를 설정해 보내세요.</p>
                </div>
                <button onClick={() => router.push("/schedule")} className="shrink-0 rounded-xl border border-line text-[12px] font-semibold text-ink2 px-3 py-2 whitespace-nowrap hover:bg-surface2 transition">
                  링크 설정
                </button>
              </Card>

              <Card className="p-4 flex items-center gap-3">
                <span className="shrink-0 w-10 h-10 rounded-xl grid place-items-center bg-warn-soft text-warn-ink" aria-hidden>
                  <Gift className="w-5 h-5" strokeWidth={2} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-[14px] font-bold text-ink">판촉물 신청</div>
                  <p className="text-[12px] text-ink3 mt-0.5 leading-5">디자인 요청부터 제작까지.</p>
                </div>
                <button onClick={() => router.push("/promotion")} className="shrink-0 rounded-xl border border-line text-[12px] font-semibold text-brand px-3 py-2 whitespace-nowrap hover:bg-brand-soft transition">
                  판촉물 신청 →
                </button>
              </Card>
            </div>
          </div>
        </div>

        {/* 하단 퀵액션 바 — 자주 쓰는 기능 바로가기 */}
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {quickActions.map((q) => (
            <button
              key={q.href}
              onClick={() => router.push(q.href)}
              className="flex items-center gap-3 rounded-2xl bg-surface border border-line shadow-card px-4 py-3.5 text-left hover:shadow-cardhover transition active:scale-[0.99]"
            >
              <span className="shrink-0 w-9 h-9 rounded-xl grid place-items-center bg-brand-soft text-brand" aria-hidden>
                <q.icon className="w-[18px] h-[18px]" strokeWidth={2} />
              </span>
              <span className="flex-1 text-[13px] font-semibold text-ink truncate">{q.label}</span>
              <ChevronRight className="w-4 h-4 text-muted shrink-0" />
            </button>
          ))}
        </div>
      </main>

      {/* 캘린더 날짜 클릭 → 그 날 일정 모달 (배경/✕ 클릭 시 닫힘) */}
      {dayModalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-6"
          onClick={() => setDayModalOpen(false)}
        >
          <div
            className="w-full max-w-sm rounded-2xl bg-surface border border-line shadow-card p-5 max-h-[80dvh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-3">
              <div className="text-[16px] font-bold text-ink">{dayModalTitle}</div>
              <button
                onClick={() => setDayModalOpen(false)}
                aria-label="닫기"
                className="w-8 h-8 rounded-lg grid place-items-center hover:bg-surface2 text-ink2"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            {selectedItems.length > 0 ? (
              <div className="space-y-3.5">
                {selectedItems.map((t, i) => (
                  <div key={i} className="flex gap-3">
                    <div className="text-[12px] font-semibold text-ink3 w-11 shrink-0 tnum pt-0.5">{t.time}</div>
                    <div className="flex-1 flex items-start gap-2">
                      <span className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${CAT_META[t.cat].dot}`} />
                      <span className="text-[14px] text-ink leading-5">{t.title}</span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="py-8 text-center text-[13px] text-ink3">이 날은 예정된 일정이 없어요.</div>
            )}
            <button
              onClick={() => router.push("/schedule")}
              className="mt-4 w-full rounded-xl border border-line text-[13px] font-semibold text-brand py-2.5 hover:bg-brand-soft transition"
            >
              일정 전체 보기 · 추가 →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
