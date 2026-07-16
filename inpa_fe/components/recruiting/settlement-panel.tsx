"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Card } from "@/components/ui";
import {
  ApiError,
  completeRecruitingSettlement,
  getProfile,
  getTeamRecruitingSummary,
  listRecruitingSettlements,
  reopenRecruitingSettlement,
  type RecruitingSettlement,
  type SettlementBlocker,
  type SettlementNextSupport,
  type SettlementState,
  type TeamRecruitingSummary,
} from "@/lib/api";
import { ConfirmationDialog } from "./confirmation-dialog";
import {
  BLOCKER_LABELS,
  SETTLEMENT_STATE_LABELS,
  SUPPORT_LABELS,
  formatDate,
  formatDateTime,
  friendlyRecruitingError,
} from "./recruiting-labels";
import { RecruitingError, RecruitingLoading } from "./recruiting-states";
import { createLatestRequestGate, groupSettlementsByDue } from "./recruiting-view-model";
import { TeamAggregate } from "./team-aggregate";

const BLOCKERS = Object.keys(BLOCKER_LABELS) as SettlementBlocker[];
const SUPPORTS = Object.keys(SUPPORT_LABELS) as SettlementNextSupport[];
const STATES = Object.keys(SETTLEMENT_STATE_LABELS) as SettlementState[];

function todayInSeoul(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

interface SettlementCardProps {
  item: RecruitingSettlement;
  today: string;
  onRefresh: () => Promise<void>;
}

function SettlementCard({ item, today, onRefresh }: SettlementCardProps) {
  const [state, setState] = useState<SettlementState>(item.state);
  const [blocker, setBlocker] = useState<SettlementBlocker | "">(item.blocker);
  const [support, setSupport] = useState<SettlementNextSupport | "">(item.next_support);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const completed = Boolean(item.completed_at);
  const canReopen = completed && item.state === "stopped" && item.due_on > today;

  useEffect(() => {
    setState(item.state);
    setBlocker(item.blocker);
    setSupport(item.next_support);
  }, [item]);

  async function submit(selectedState = state) {
    if (selectedState === "support_needed" && (!blocker || blocker === "none" || !support)) {
      setError("도움이 필요한 부분과 다음 지원 방법을 함께 선택해 주세요.");
      return;
    }
    setSaving(true);
    setError(null);
    setStatus(null);
    try {
      await completeRecruitingSettlement(item.id, {
        state: selectedState,
        blocker: selectedState === "support_needed" ? blocker : undefined,
        next_support: selectedState === "support_needed" ? support : undefined,
      });
      setConfirmOpen(false);
      setStatus("정착 확인을 저장했어요.");
      await onRefresh();
    } catch (reason) {
      setError(friendlyRecruitingError(reason, "선택한 내용은 그대로 두었어요. 다시 저장해 주세요."));
    } finally {
      setSaving(false);
    }
  }

  async function reopen() {
    setSaving(true);
    setError(null);
    try {
      await reopenRecruitingSettlement(item.id);
      setStatus("다음 확인 일정으로 다시 열었어요.");
      await onRefresh();
    } catch (reason) {
      setError(friendlyRecruitingError(reason, "정착 일정의 날짜와 상태를 확인하면 다시 열 수 있어요."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card className="p-4 sm:p-5">
      {error && <p role="alert" className="mb-3 rounded-xl bg-danger-tint px-3 py-2 text-[12px] font-semibold text-danger-ink">{error}</p>}
      {status && <p aria-live="polite" className="mb-3 rounded-xl bg-success-tint px-3 py-2 text-[12px] font-semibold text-success-ink">{status}</p>}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-[15px] font-extrabold text-ink">{item.joined_agent_name}</h3>
          <p className="mt-1 text-[12px] text-ink3">합류 {item.week}주 확인 · {formatDate(item.due_on)}</p>
        </div>
        <span className={`rounded-full px-2.5 py-1 text-[11px] font-bold ${completed ? "bg-success-tint text-success-ink" : item.due_on < today ? "bg-warning-tint text-warning-ink" : "bg-brand-soft text-brand"}`}>
          {completed ? SETTLEMENT_STATE_LABELS[item.state] : item.due_on < today ? "지난 확인" : item.due_on === today ? "오늘 확인" : "예정"}
        </span>
      </div>

      {completed ? (
        <div className="mt-4 rounded-2xl bg-surface2 p-4">
          <dl className="grid gap-2 text-[12px] sm:grid-cols-3">
            <div><dt className="text-ink3">상태</dt><dd className="mt-1 font-bold text-ink">{SETTLEMENT_STATE_LABELS[item.state]}</dd></div>
            <div><dt className="text-ink3">도움이 필요한 부분</dt><dd className="mt-1 font-bold text-ink">{item.blocker ? BLOCKER_LABELS[item.blocker] : "-"}</dd></div>
            <div><dt className="text-ink3">다음 지원</dt><dd className="mt-1 font-bold text-ink">{item.next_support ? SUPPORT_LABELS[item.next_support] : "-"}</dd></div>
          </dl>
          <p className="mt-3 text-[11px] text-ink3">확인 완료 {formatDateTime(item.completed_at)}</p>
          {canReopen && <button type="button" disabled={saving} onClick={reopen} className="mt-3 min-h-11 rounded-xl border border-line bg-surface px-4 text-[13px] font-bold text-brand disabled:opacity-60">{saving ? "다시 여는 중..." : "다시 수정"}</button>}
        </div>
      ) : (
        <div className="mt-4 space-y-3">
          <fieldset>
            <legend className="text-[12px] font-bold text-ink2">지금 활동 상태</legend>
            <div className="mt-2 grid gap-2 sm:grid-cols-3">
              {STATES.map((value) => (
                <button key={value} type="button" aria-pressed={state === value} onClick={() => { setState(value); setError(null); }} className={`min-h-11 rounded-xl border px-3 text-[12px] font-bold ${state === value ? "border-brand bg-brand text-white" : "border-line bg-surface text-ink2"}`}>
                  {SETTLEMENT_STATE_LABELS[value]}
                </button>
              ))}
            </div>
          </fieldset>
          {state === "support_needed" && (
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="text-[12px] font-bold text-ink2">도움이 필요한 부분
                <select value={blocker} onChange={(event) => setBlocker(event.target.value as SettlementBlocker)} className="mt-1.5 min-h-11 w-full rounded-xl border border-line bg-surface px-3 text-[13px] text-ink">
                  <option value="">선택해 주세요</option>
                  {BLOCKERS.filter((value) => value !== "none").map((value) => <option key={value} value={value}>{BLOCKER_LABELS[value]}</option>)}
                </select>
              </label>
              <label className="text-[12px] font-bold text-ink2">다음 지원 방법
                <select value={support} onChange={(event) => setSupport(event.target.value as SettlementNextSupport)} className="mt-1.5 min-h-11 w-full rounded-xl border border-line bg-surface px-3 text-[13px] text-ink">
                  <option value="">선택해 주세요</option>
                  {SUPPORTS.filter((value) => value !== "close" && value !== "schedule_only").map((value) => <option key={value} value={value}>{SUPPORT_LABELS[value]}</option>)}
                </select>
              </label>
            </div>
          )}
          <button type="button" disabled={saving} onClick={() => state === "stopped" ? setConfirmOpen(true) : void submit()} className="min-h-11 w-full rounded-xl bg-brand px-4 text-[13px] font-bold text-white disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2">
            {saving ? "저장하는 중..." : "정착 확인 저장"}
          </button>
        </div>
      )}

      <ConfirmationDialog
        open={confirmOpen}
        title="활동 중단으로 기록할까요?"
        description="활동 중단으로 저장하면 앞으로 남은 정착 확인도 함께 마무리돼요."
        confirmLabel="활동 중단으로 저장"
        pendingLabel="저장하는 중..."
        pending={saving}
        onConfirm={() => void submit("stopped")}
        onClose={() => setConfirmOpen(false)}
      />
    </Card>
  );
}

export function SettlementPanel() {
  const [items, setItems] = useState<RecruitingSettlement[]>([]);
  const [team, setTeam] = useState<TeamRecruitingSummary | null>(null);
  const [teamPlanMessage, setTeamPlanMessage] = useState<string | null>(null);
  const [teamError, setTeamError] = useState<string | null>(null);
  const [isManager, setIsManager] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const loadRequestGateRef = useRef(createLatestRequestGate());
  const today = todayInSeoul();

  const load = useCallback(async () => {
    const requestGate = loadRequestGateRef.current;
    const requestGeneration = requestGate.begin();
    setLoading(true);
    setError(null);
    try {
      const [settlements, profile] = await Promise.all([
        listRecruitingSettlements(),
        getProfile(),
      ]);
      let nextTeam: TeamRecruitingSummary | null = null;
      let nextTeamPlanMessage: string | null = null;
      let nextTeamError: string | null = null;
      if (profile.is_manager) {
        try {
          nextTeam = await getTeamRecruitingSummary();
        } catch (reason) {
          if (reason instanceof ApiError && reason.status === 402) {
            nextTeamPlanMessage = reason.message || "Plus를 시작하면 팀 관리 기능을 계속 사용할 수 있어요.";
          } else {
            nextTeamError = "팀 합계를 다시 불러오면 이어서 확인할 수 있어요.";
          }
        }
      }
      if (!requestGate.isCurrent(requestGeneration)) return;
      setItems(settlements);
      setIsManager(profile.is_manager);
      setTeam(nextTeam);
      setTeamPlanMessage(nextTeamPlanMessage);
      setTeamError(nextTeamError);
    } catch (reason) {
      if (!requestGate.isCurrent(requestGeneration)) return;
      setError(friendlyRecruitingError(reason));
    } finally {
      if (requestGate.isCurrent(requestGeneration)) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    return () => {
      loadRequestGateRef.current.invalidate();
    };
  }, [load]);

  const groups = useMemo(() => groupSettlementsByDue(items, today), [items, today]);
  const sections = [
    { key: "past", title: "지난 확인", description: "먼저 안부를 확인하면 흐름을 다시 이어갈 수 있어요.", items: groups.past },
    { key: "today", title: "오늘 확인", description: "오늘 짧게 확인할 합류 설계사예요.", items: groups.today },
    { key: "upcoming", title: "예정", description: "앞으로 다가올 정착 확인 일정이에요.", items: groups.upcoming },
    { key: "completed", title: "완료·중단", description: "저장된 확인 결과를 날짜와 함께 볼 수 있어요.", items: groups.completed },
  ];

  if (loading && items.length === 0) return <RecruitingLoading />;
  if (error && items.length === 0) return <RecruitingError message={error} onRetry={load} />;

  return (
    <div className="min-w-0 space-y-6">
      {error && <p role="alert" className="rounded-2xl bg-danger-tint px-4 py-3 text-[13px] font-semibold text-danger-ink">{error}</p>}
      {items.length === 0 ? (
        <div className="rounded-2xl border border-line bg-surface px-5 py-10 text-center shadow-card">
          <p className="text-[15px] font-bold text-ink">합류 뒤 첫 확인 일정이 여기에 모여요.</p>
          <p className="mt-2 text-[13px] leading-5 text-ink3">팀 합류가 기록되면 1·4·8·13주 확인 일정을 차례로 볼 수 있어요.</p>
        </div>
      ) : sections.map((section) => (
        <section key={section.key} aria-labelledby={`settlement-${section.key}`}>
          <div className="mb-3">
            <h2 id={`settlement-${section.key}`} className="text-[17px] font-extrabold text-ink">{section.title} <span className="text-brand">{section.items.length}</span></h2>
            <p className="mt-1 text-[12px] text-ink3">{section.description}</p>
          </div>
          {section.items.length > 0 ? (
            <div className="grid gap-3 lg:grid-cols-2">
              {section.items.map((item) => <SettlementCard key={item.id} item={item} today={today} onRefresh={load} />)}
            </div>
          ) : <p className="rounded-2xl border border-dashed border-line bg-surface px-4 py-6 text-center text-[12px] text-ink3">이 구간에 확인할 일정이 생기면 여기에 보여요.</p>}
        </section>
      ))}
      {isManager && <TeamAggregate data={team} planMessage={teamPlanMessage} errorMessage={teamError} onRetry={() => void load()} />}
    </div>
  );
}
