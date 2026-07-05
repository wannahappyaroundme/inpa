"use client";

// 관리자(지점장·팀장) 조직관리 대시보드 — 동의(manager_share_opt_in)한 소속 설계사 KPI '집계만'.
// ★ 개별 고객 이름·병력 등 PII는 절대 표시 안 함(BE가 집계 수치만 반환). 성과 수치는 '추정' 라벨.

import { useState, useEffect, useMemo, useCallback } from "react";
import { Wallet, UserPlus, Users, AlertTriangle, Link2 } from "lucide-react";
import { AppNav } from "@/components/app-nav";
import { Card, StatCard, SectionTitle } from "@/components/ui";
import { BarChart } from "@/components/charts";
import { useAuthGuard } from "@/lib/useAuthGuard";
import {
  getManagerDashboard,
  createTeamInviteLink,
  SALES_STAGES,
  funnelConversion,
  type ManagerDashboardResponse,
  type ManagerAgentKpi,
} from "@/lib/api";

const krw = new Intl.NumberFormat("ko-KR");
function fmtWonShort(v: number): string {
  if (v >= 100_000_000) return `${krw.format(Math.round((v / 100_000_000) * 10) / 10)}억`;
  if (v >= 10_000) return `${krw.format(Math.round(v / 10_000))}만`;
  return krw.format(v);
}
function loginAgo(iso: string | null): string {
  if (!iso) return "기록 없음";
  const d = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  return d <= 0 ? "오늘" : `${d}일 전`;
}
// 단계 분포 미니바 색(고객 보드 단계 계열과 동일 톤)
const STAGE_BAR: Record<string, string> = {
  db: "bg-slate-300",
  contact: "bg-blue-400",
  meeting: "bg-violet-400",
  contract: "bg-emerald-400",
};

function FunnelMini({ funnel }: { funnel: Record<string, number> }) {
  const total = SALES_STAGES.reduce((s, st) => s + (funnel[st.key] ?? 0), 0);
  if (!total) return <span className="text-[11px] text-ink3">-</span>;
  return (
    <div className="flex h-2 w-full min-w-[72px] rounded-full overflow-hidden bg-surface2">
      {SALES_STAGES.map((st) => {
        const v = funnel[st.key] ?? 0;
        return v ? (
          <div key={st.key} className={STAGE_BAR[st.key]} style={{ width: `${(v / total) * 100}%` }} title={`${st.label} ${v}`} />
        ) : null;
      })}
    </div>
  );
}

function Delta({ pct }: { pct: number | null }) {
  if (pct == null || pct === 0) return null;
  return (
    <span className={`block text-[10px] font-semibold tnum ${pct > 0 ? "text-emerald-600" : "text-rose-500"}`}>
      {pct > 0 ? "▲" : "▼"}{Math.abs(pct)}%
    </span>
  );
}

function RankRow({ rank, a }: { rank: number; a: ManagerAgentKpi }) {
  const idle = !a.is_active_month;
  return (
    <div className={`grid grid-cols-[2rem_1.4fr_1fr_0.7fr_0.7fr_1fr_0.8fr_0.9fr] gap-2 px-2 py-2.5 items-center border-b border-line/60 ${idle ? "opacity-55" : ""}`}>
      <span className="text-[12px] font-bold tnum text-ink3">{rank}</span>
      <span className="flex items-center gap-2 min-w-0">
        <span className="w-7 h-7 rounded-full bg-brand-soft text-brand grid place-items-center text-[12px] font-bold shrink-0">{a.name_masked[0]}</span>
        <span className="min-w-0">
          <span className="block text-[13px] font-bold text-ink truncate">{a.name_masked}</span>
          {idle && <span className="block text-[10px] text-ink3">이번 달 활동 없음</span>}
        </span>
      </span>
      <span className="text-right">
        {a.shares_performance ? (
          <>
            <span className="text-[13px] font-extrabold tnum text-ink">{fmtWonShort(a.premium_month ?? 0)}</span>
            <Delta pct={a.premium_delta} />
          </>
        ) : (
          <span className="text-[12px] text-ink3">비공개</span>
        )}
      </span>
      <span className="text-right text-[13px] tnum text-ink2">{a.new_month}</span>
      <span className="text-right text-[13px] tnum text-ink2">{a.meetings_month}</span>
      <span><FunnelMini funnel={a.funnel} /></span>
      <span className="text-right text-[12px] tnum text-ink2">{!a.shares_performance ? "비공개" : a.retention_y1 == null ? "·" : `${a.retention_y1}%`}</span>
      <span className="text-right text-[11px] text-ink3">{loginAgo(a.last_login)}</span>
    </div>
  );
}

function RankCard({ rank, a }: { rank: number; a: ManagerAgentKpi }) {
  const idle = !a.is_active_month;
  return (
    <div className={`rounded-xl border border-line p-3 ${idle ? "opacity-60 bg-surface2" : "bg-surface"}`}>
      <div className="flex items-center gap-2">
        <span className="text-[12px] font-bold tnum text-ink3 w-5">{rank}</span>
        <span className="w-8 h-8 rounded-full bg-brand-soft text-brand grid place-items-center text-[13px] font-bold">{a.name_masked[0]}</span>
        <span className="flex-1 min-w-0">
          <span className="block text-[14px] font-bold text-ink">{a.name_masked}</span>
          {idle && <span className="block text-[10px] text-ink3">이번 달 활동 없음</span>}
        </span>
        <span className="text-right">
          {a.shares_performance ? (
            <>
              <span className="text-[14px] font-extrabold tnum text-ink">{fmtWonShort(a.premium_month ?? 0)}</span>
              <Delta pct={a.premium_delta} />
            </>
          ) : (
            <span className="text-[12px] text-ink3">비공개</span>
          )}
        </span>
      </div>
      <div className="mt-2 flex items-center gap-3 text-[11px] text-ink3">
        <span>신규 <b className="text-ink2">{a.new_month}</b></span>
        <span>미팅 <b className="text-ink2">{a.meetings_month}</b></span>
        <span>1년유지 <b className="text-ink2">{!a.shares_performance ? "비공개" : a.retention_y1 == null ? "·" : `${a.retention_y1}%`}</b></span>
        <span className="ml-auto">{loginAgo(a.last_login)}</span>
      </div>
      <div className="mt-2"><FunnelMini funnel={a.funnel} /></div>
    </div>
  );
}

// 팀 초대 링크 카드(#24) — 링크 생성·복사(공유 위젯 패턴 재사용). 동의 침해 없음:
// 가입 시 팀 연결만 되고, 성과 공유 여부는 가입한 본인이 설정에서 직접 선택한다.
function TeamInviteCard() {
  const [link, setLink] = useState<string | null>(null);
  const [ttlDays, setTtlDays] = useState(7);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const generate = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await createTeamInviteLink();
      setLink(r.url);
      if (r.ttl_days) setTtlDays(r.ttl_days);
    } catch {
      setError("링크를 만들지 못했어요. 잠시 후 다시 시도해 주세요.");
    } finally {
      setBusy(false);
    }
  }, []);

  const copy = useCallback(async () => {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* 미지원 환경 무시 */
    }
  }, [link]);

  return (
    <Card className="mt-4 p-4 sm:p-5">
      <div className="flex items-center gap-2">
        <Link2 size={16} className="text-brand" />
        <span className="text-[15px] font-bold text-ink">팀 초대 링크</span>
      </div>
      <p className="mt-1 text-[12px] text-ink3 leading-5">
        이 링크로 가입한 설계사는 내 팀으로 연결돼요. 성과 공유 여부는 본인이 설정에서 선택해요. (링크는 {ttlDays}일 유효)
      </p>
      {error && <p className="mt-2 text-[12px] text-danger">{error}</p>}
      {link ? (
        <div className="mt-2.5 flex items-center gap-2">
          <input
            readOnly
            value={link}
            onFocus={(e) => e.currentTarget.select()}
            className="flex-1 min-w-0 rounded-xl border border-line bg-surface2 px-3 py-2 text-[12px] text-ink2 truncate"
          />
          <button
            onClick={copy}
            className="shrink-0 rounded-xl bg-brand text-white text-[13px] font-bold px-4 py-2 active:scale-[0.98] transition"
          >
            {copied ? "복사됨" : "링크 복사"}
          </button>
        </div>
      ) : (
        <button
          onClick={generate}
          disabled={busy}
          className="mt-2.5 rounded-xl bg-brand text-white text-[13px] font-bold px-4 py-2 disabled:opacity-60 active:scale-[0.98] transition"
        >
          {busy ? "만드는 중..." : "초대 링크 만들기"}
        </button>
      )}
    </Card>
  );
}

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

  const ranked = useMemo(
    () => (data ? [...data.agents].sort((a, b) => (b.premium_month ?? 0) - (a.premium_month ?? 0)) : []),
    [data]
  );

  if (!ready) return null;

  const trendBars = data?.team_premium_trend.map((p) => ({ label: `${Number(p.ym.slice(5))}월`, value: p.premium })) ?? [];
  const mix = data?.team_product_mix ?? { life: 0, nonlife: 0 };
  const mixTotal = mix.life + mix.nonlife;

  return (
    <div className="min-h-dvh">
      <AppNav active="manager" />
      <main className="mx-auto max-w-[1440px] px-4 sm:px-6 py-6">
        <h1 className="text-[22px] font-extrabold text-ink">팀 현황</h1>
        <p className="mt-1.5 text-[14px] font-semibold text-brand leading-5">팀원이 편해지면 팀장님 숫자가 좋아집니다.</p>
        <p className="mt-1 text-[13px] text-ink3 leading-5">
          월말 취합 엑셀은 그만. 성과 공유에 <b>동의한</b> 소속 설계사의 집계를 실시간으로 봐요. 개별 고객 정보는 표시되지 않아요(프라이버시). 성과 수치는 추정이에요.
        </p>

        {/* 팀 초대 링크 — 팀이 아직 없어도 항상 노출(팀을 만드는 첫 행동) */}
        <TeamInviteCard />

        {error && (
          <div className="mt-4 rounded-xl border border-danger/30 bg-danger-tint px-4 py-2.5 text-[13px] text-danger">{error}</div>
        )}

        {loading ? (
          <div className="mt-4 grid grid-cols-2 lg:grid-cols-4 gap-3">
            {[1, 2, 3, 4].map((i) => <div key={i} className="h-20 rounded-2xl bg-line animate-pulse" />)}
          </div>
        ) : !data || data.agent_count === 0 ? (
          <Card className="mt-4 px-4 py-10 text-center">
            <p className="text-[14px] text-ink3">아직 성과 공유에 동의한 소속 설계사가 없어요.</p>
            <p className="mt-1 text-[12px] text-ink3">팀원이 설정 화면에서 '관리자에게 내 성과 공유'를 켜면 여기에 표시돼요.</p>
          </Card>
        ) : (
          <>
            {/* 상단 합계 바 */}
            <div className="mt-4 grid grid-cols-2 lg:grid-cols-4 gap-3">
              <StatCard icon={Wallet} tone="brand" label="이번 달 팀 보험료" value={fmtWonShort(data.totals.premium_month)} unit="원" hint={`실적까지 공유한 ${data.totals.perf_agent_count}명 기준 (활동만 공유한 팀원 제외)`} />
              <StatCard icon={UserPlus} tone="brand" label="이번 달 신규 유치" value={data.totals.new_month} unit="명" />
              <StatCard icon={Users} tone="pos" label="활동 멤버" value={`${data.totals.active_member_count}/${data.agent_count}`} unit="명" hint="이번 달 신규 등록이나 미팅이 있는 팀원 수" />
              <StatCard icon={AlertTriangle} tone="warn" accent={data.totals.churn_risk_count > 0} label="환수 위험" value={data.totals.churn_risk_count} unit="건" />
            </div>

            <div className="mt-4 grid grid-cols-1 lg:grid-cols-3 gap-4 items-start">
              {/* 좌: 팀 전체 */}
              <div className="lg:col-span-2 space-y-4">
                <Card className="p-4 sm:p-5">
                  <SectionTitle title="팀 영업 단계" />
                  <div className="grid grid-cols-4 gap-3">
                    {SALES_STAGES.map((s) => (
                      <div key={s.key} className="rounded-xl p-3 bg-surface2 text-center">
                        <div className="text-[12px] text-ink3">{s.label}</div>
                        <div className="mt-1 text-[22px] font-extrabold tnum text-ink">{data.team_funnel[s.key] ?? 0}</div>
                      </div>
                    ))}
                  </div>
                  {/* 단계 전환율(스냅샷) — 어디서 막히는지 */}
                  <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink3">
                    <span className="font-semibold text-ink2">전환율</span>
                    {funnelConversion(data.team_funnel).map((c) => {
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

                <Card className="p-4 sm:p-5">
                  <div className="text-[15px] font-bold text-ink mb-3">팀 월별 보험료 추이</div>
                  <BarChart data={trendBars} format={(n) => fmtWonShort(n)} heightClass="h-40" />
                </Card>

                <Card className="p-4 sm:p-5">
                  <div className="text-[15px] font-bold text-ink mb-3">취급 보험 종류</div>
                  {mixTotal ? (
                    <div className="space-y-2.5">
                      {([["생명보험", mix.life, "bg-blue-400"], ["손해보험", mix.nonlife, "bg-emerald-400"]] as const).map(([label, v, c]) => (
                        <div key={label} className="flex items-center gap-3">
                          <span className="w-16 text-[12px] text-ink2 shrink-0">{label}</span>
                          <div className="flex-1 h-3 rounded-full bg-surface2 overflow-hidden">
                            <div className={c} style={{ width: `${(v / mixTotal) * 100}%`, height: "100%" }} />
                          </div>
                          <span className="w-12 text-right text-[12px] font-semibold tnum text-ink">{v}건</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-[12px] text-ink3">아직 등록된 보유 증권이 없어요.</p>
                  )}
                </Card>
              </div>

              {/* 우 레일: 유지율 + ROI */}
              <div className="space-y-4">
                <Card className="p-4 sm:p-5">
                  <div className="text-[15px] font-bold text-ink">팀 유지율 <span className="text-[11px] font-normal text-ink3">(추정)</span></div>
                  {data.team_retention.has_cancellation_data ? (
                    <div className="mt-3 space-y-2">
                      {([["y1", "1년"], ["y2", "2년"], ["y3", "3년"]] as const).map(([k, label]) => {
                        const r = data.team_retention[k];
                        return (
                          <div key={k} className="flex items-center justify-between">
                            <span className="text-[13px] text-ink2">{label}</span>
                            <span className="text-[15px] font-extrabold tnum text-ink">
                              {r.rate == null ? "·" : `${r.rate}%`} <span className="text-[11px] font-normal text-ink3">({r.survived}/{r.reached})</span>
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <p className="mt-2 text-[12px] text-ink3 leading-5">아직 팀의 해지 입력이 없어 유지율을 계산하지 않았어요.</p>
                  )}
                </Card>

                <Card className="p-4 sm:p-5 border-accent-tint">
                  <div className="text-[15px] font-bold text-ink">팀 성과 ROI <span className="text-[11px] font-normal text-ink3">(추정)</span></div>
                  <p className="mt-2 text-[13px] text-ink2 leading-5">
                    팀원 1인당 월 <b>{data.roi.hours_saved_per_agent}시간</b> 절약 × <b>{data.roi.agent_count}명</b> = 팀 <b className="text-brand">{data.roi.team_hours_saved}시간</b> → 상담 <b className="text-brand">약 {data.roi.extra_consults}건</b>.
                  </p>
                  <p className="mt-1 text-[11px] text-ink3">{data.roi.note}</p>
                </Card>
              </div>
            </div>

            {/* 설계사별 순위표 */}
            <Card className="mt-4 p-4 sm:p-5">
              <SectionTitle title="설계사별 성과" action={<span className="text-[12px] text-ink3">이번 달 보험료순</span>} />
              <div className="hidden md:block">
                <div className="grid grid-cols-[2rem_1.4fr_1fr_0.7fr_0.7fr_1fr_0.8fr_0.9fr] gap-2 px-2 py-2 text-[11px] font-semibold text-ink3 border-b border-line">
                  <span>#</span><span>설계사</span><span className="text-right">이번달 보험료</span><span className="text-right">신규</span><span className="text-right">미팅</span><span>단계 분포</span><span className="text-right">1년유지</span><span className="text-right">최근접속</span>
                </div>
                {ranked.map((a, i) => <RankRow key={i} rank={i + 1} a={a} />)}
              </div>
              <div className="md:hidden space-y-2">
                {ranked.map((a, i) => <RankCard key={i} rank={i + 1} a={a} />)}
              </div>
            </Card>
          </>
        )}
      </main>
    </div>
  );
}
