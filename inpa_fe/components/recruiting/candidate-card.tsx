"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { copyText } from "@/lib/clipboard";
import {
  issueRecruitingTeamInvite,
  transitionRecruitingCandidate,
  updateRecruitingCandidate,
  type RecruitingActiveCandidate,
  type RecruitingCandidate,
  type RecruitingNextAction,
  type RecruitingStage,
} from "@/lib/api";
import {
  CAREER_LABELS,
  CONTACT_LABELS,
  NEXT_ACTION_LABELS,
  STAGE_LABELS,
  formatDateTime,
  friendlyRecruitingError,
  toDateTimeInput,
} from "./recruiting-labels";
import {
  allowedManualStageChoices,
  getCandidateDisplayIdentity,
} from "./recruiting-view-model";

interface CandidateCardProps {
  candidate: RecruitingCandidate;
  compact?: boolean;
  onChanged: (candidate: RecruitingCandidate) => void;
}

const INPUT_CLASS =
  "min-h-11 w-full rounded-xl border border-line bg-surface px-3 text-[13px] text-ink outline-none focus:border-brand focus:ring-2 focus:ring-brand/15";

function candidateDateTimeToIso(value: string): string | null {
  if (!value) return null;
  const date = new Date(`${value}:00+09:00`);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

export function CandidateCard({ candidate, compact = false, onChanged }: CandidateCardProps) {
  const identity = getCandidateDisplayIdentity(candidate);
  const [expanded, setExpanded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [nextAction, setNextAction] = useState<RecruitingNextAction | "">(
    candidate.selection_status === "active" ? candidate.next_action : "",
  );
  const [nextAt, setNextAt] = useState(
    candidate.selection_status === "active" ? toDateTimeInput(candidate.next_action_at) : "",
  );
  const choices = useMemo(() => allowedManualStageChoices(candidate), [candidate]);
  const [targetStage, setTargetStage] = useState<RecruitingStage | "">(choices[0] ?? "");
  const [invite, setInvite] = useState<{ url: string; expiresAt: string } | null>(null);

  useEffect(() => {
    if (candidate.selection_status !== "active") return;
    setNextAction(candidate.next_action);
    setNextAt(toDateTimeInput(candidate.next_action_at));
    const updatedChoices = allowedManualStageChoices(candidate);
    setTargetStage(updatedChoices[0] ?? "");
  }, [candidate]);

  if (identity.kind === "closed") {
    return (
      <article className="rounded-2xl border border-line bg-surface p-4 opacity-80 shadow-card">
        <div className="flex items-center justify-between gap-3">
          <h3 className="text-[14px] font-bold text-ink">{identity.displayName}</h3>
          <span className="rounded-full bg-surface2 px-2.5 py-1 text-[11px] font-semibold text-ink3">
            종료
          </span>
        </div>
        <p className="mt-3 text-[13px] leading-5 text-ink2">{identity.closedMessage}</p>
        <p className="mt-2 text-[11px] text-ink3">기록일 {formatDateTime(identity.closedAt)}</p>
      </article>
    );
  }

  if (identity.kind === "joined") {
    return (
      <article className="rounded-2xl border border-line bg-surface p-4 shadow-card">
        <div className="flex items-center gap-3">
          <div className="grid h-11 w-11 shrink-0 place-items-center overflow-hidden rounded-full bg-brand-soft text-[14px] font-extrabold text-brand">
            {identity.profileImage ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={identity.profileImage} alt="" className="h-full w-full object-cover" />
            ) : (
              identity.displayName.slice(0, 1)
            )}
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-[15px] font-extrabold text-ink">{identity.displayName}</h3>
            <p className="mt-0.5 text-[12px] font-semibold text-success-ink">팀 합류 완료</p>
          </div>
        </div>
        <p className="mt-3 text-[12px] text-ink3">
          정착 지원 탭에서 다음 확인 일정을 이어갈 수 있어요.
        </p>
      </article>
    );
  }

  if (candidate.selection_status !== "active") return null;
  const activeCandidate: RecruitingActiveCandidate = candidate;
  const nextLabel = activeCandidate.next_action
    ? NEXT_ACTION_LABELS[activeCandidate.next_action]
    : "다음 행동 정하기";
  const smsDraft = `안녕하세요, ${identity.displayName}님. 다음 이야기를 나눌 시간을 확인하려고 연락드렸어요.`;

  async function saveNextAction() {
    setSaving(true);
    setError(null);
    setStatus(null);
    try {
      const updated = await updateRecruitingCandidate(activeCandidate.id, {
        next_action: nextAction,
        next_action_at: candidateDateTimeToIso(nextAt),
      });
      onChanged(updated);
      setStatus("다음 행동을 저장했어요.");
    } catch (reason) {
      setError(friendlyRecruitingError(reason, "입력한 내용은 그대로 두었어요. 다시 저장해 주세요."));
    } finally {
      setSaving(false);
    }
  }

  async function changeStage() {
    if (!targetStage) return;
    if (targetStage === "recontact" && (!nextAction || nextAction === "none" || !nextAt)) {
      setError("다시 연락할 방법과 날짜를 정하면 단계를 옮길 수 있어요.");
      return;
    }
    setSaving(true);
    setError(null);
    setStatus(null);
    try {
      const updated = await transitionRecruitingCandidate(activeCandidate.id, {
        stage: targetStage,
        next_action: targetStage === "ended" ? "none" : nextAction,
        next_action_at: targetStage === "ended" ? null : candidateDateTimeToIso(nextAt),
      });
      onChanged(updated);
      setStatus(`${STAGE_LABELS[targetStage]} 단계로 옮겼어요.`);
    } catch (reason) {
      setError(friendlyRecruitingError(reason, "현재 위치는 그대로예요. 단계를 다시 확인해 주세요."));
    } finally {
      setSaving(false);
    }
  }

  async function issueInvite() {
    setSaving(true);
    setError(null);
    try {
      const issued = await issueRecruitingTeamInvite(activeCandidate.id);
      const url = `${window.location.origin}${issued.join_path}`;
      setInvite({ url, expiresAt: issued.expires_at });
      setStatus("합류 링크를 만들었어요.");
    } catch (reason) {
      setError(friendlyRecruitingError(reason, "지원 흐름을 확인하면 합류 링크를 만들 수 있어요."));
    } finally {
      setSaving(false);
    }
  }

  async function copyInvite() {
    if (!invite) return;
    const copied = await copyText(invite.url);
    setStatus(copied ? "합류 링크를 복사했어요." : null);
    if (!copied) setError("링크를 길게 눌러 직접 복사해 주세요.");
  }

  return (
    <article className="rounded-2xl border border-line bg-surface p-4 shadow-card">
      {error && (
        <p role="alert" className="mb-3 rounded-xl bg-danger-tint px-3 py-2 text-[12px] font-semibold text-danger-ink">
          {error}
        </p>
      )}
      {status && <p aria-live="polite" className="mb-3 rounded-xl bg-success-tint px-3 py-2 text-[12px] font-semibold text-success-ink">{status}</p>}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate text-[15px] font-extrabold text-ink">{identity.displayName}</h3>
            {activeCandidate.duplicate_contact && (
              <span className="rounded-full bg-warning-tint px-2 py-0.5 text-[10px] font-bold text-warning-ink">
                같은 연락처 확인
              </span>
            )}
          </div>
          <p className="mt-1 text-[12px] text-ink3">
            {CAREER_LABELS[identity.careerBand]} · {identity.currentAffiliation || "현재 소속 미입력"}
          </p>
          <p className="mt-1 text-[11px] text-ink3">
            들어온 곳 {activeCandidate.campaign?.name || "개인 소개"}
          </p>
        </div>
        <span className="shrink-0 rounded-full bg-brand-soft px-2.5 py-1 text-[11px] font-bold text-brand">
          {STAGE_LABELS[activeCandidate.stage]}
        </span>
      </div>

      <dl className={`mt-3 grid gap-2 text-[12px] ${compact ? "grid-cols-1" : "grid-cols-2"}`}>
        <div className="rounded-xl bg-surface2 px-3 py-2">
          <dt className="text-[10px] font-semibold text-ink3">활동 지역</dt>
          <dd className="mt-0.5 font-semibold text-ink2">{identity.region || "-"}</dd>
        </div>
        <div className="rounded-xl bg-surface2 px-3 py-2">
          <dt className="text-[10px] font-semibold text-ink3">연락하기 좋은 때</dt>
          <dd className="mt-0.5 font-semibold text-ink2">{CONTACT_LABELS[identity.contactWindow]}</dd>
        </div>
      </dl>
      <div className="mt-3 rounded-xl border border-line px-3 py-2.5">
        <p className="text-[10px] font-semibold text-ink3">다음 행동</p>
        <p className="mt-1 text-[12px] font-bold text-ink">
          {nextLabel} · {formatDateTime(activeCandidate.next_action_at)}
        </p>
      </div>

      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
        className="mt-3 min-h-11 w-full rounded-xl border border-line bg-surface text-[13px] font-bold text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
      >
        {expanded ? "상세 접기" : "연락처와 다음 단계 보기"}
      </button>

      {expanded && (
        <div className="mt-4 border-t border-line pt-4">
          <div className="flex flex-wrap gap-2">
            <a
              href={`tel:${identity.phone}`}
              className="inline-flex min-h-11 items-center justify-center rounded-xl bg-brand px-4 text-[13px] font-bold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
            >
              전화하기
            </a>
            <a
              href={`sms:${identity.phone}?body=${encodeURIComponent(smsDraft)}`}
              className="inline-flex min-h-11 items-center justify-center rounded-xl border border-line bg-surface px-4 text-[13px] font-bold text-ink2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
            >
              문자 초안 열기
            </a>
            <Link
              href="/schedule"
              target="_blank"
              rel="noreferrer"
              className="inline-flex min-h-11 items-center justify-center rounded-xl border border-line bg-surface px-4 text-[13px] font-bold text-ink2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
            >
              일정에서 시간 잡기
            </Link>
          </div>
          <p className="mt-2 text-[11px] text-ink3">연락처 {identity.phone}</p>

          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <label className="text-[12px] font-semibold text-ink2">
              다음 행동
              <select
                value={nextAction}
                onChange={(event) => setNextAction(event.target.value as RecruitingNextAction)}
                className={`${INPUT_CLASS} mt-1.5`}
              >
                {Object.entries(NEXT_ACTION_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </label>
            <label className="text-[12px] font-semibold text-ink2">
              확인 날짜와 시간
              <input
                type="datetime-local"
                value={nextAt}
                onChange={(event) => setNextAt(event.target.value)}
                className={`${INPUT_CLASS} mt-1.5`}
              />
            </label>
          </div>
          <button
            type="button"
            disabled={saving}
            onClick={saveNextAction}
            className="mt-3 min-h-11 rounded-xl bg-brand px-4 text-[13px] font-bold text-white disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
          >
            {saving ? "저장하는 중..." : "다음 행동 저장"}
          </button>

          {choices.length > 0 && (
            <div className="mt-5 rounded-2xl bg-surface2 p-3">
              <label className="text-[12px] font-semibold text-ink2">
                다음 단계
                <select
                  value={targetStage}
                  onChange={(event) => setTargetStage(event.target.value as RecruitingStage)}
                  className={`${INPUT_CLASS} mt-1.5`}
                >
                  {choices.map((stage) => (
                    <option key={stage} value={stage}>{STAGE_LABELS[stage]}</option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                disabled={saving || !targetStage}
                onClick={changeStage}
                className="mt-3 min-h-11 w-full rounded-xl border border-brand bg-surface px-4 text-[13px] font-bold text-brand disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
              >
                {saving ? "확인하는 중..." : "선택한 단계로 옮기기"}
              </button>
            </div>
          )}

          {activeCandidate.stage === "preparing" && (
            <div className="mt-5 rounded-2xl border border-line bg-brand-soft p-3">
              <p className="text-[13px] font-bold text-brand">팀 합류 안내</p>
              <p className="mt-1 text-[11px] leading-5 text-ink2">
                본인이 링크를 수락하면 팀 합류 단계가 자동으로 기록돼요.
              </p>
              {invite ? (
                <>
                  <input readOnly value={invite.url} className={`${INPUT_CLASS} mt-3`} onFocus={(event) => event.currentTarget.select()} />
                  <p className="mt-2 text-[11px] text-ink3">유효기간 {formatDateTime(invite.expiresAt)}</p>
                  <button
                    type="button"
                    onClick={copyInvite}
                    className="mt-2 min-h-11 rounded-xl bg-brand px-4 text-[13px] font-bold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
                  >
                    합류 링크 복사
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  disabled={saving}
                  onClick={issueInvite}
                  className="mt-3 min-h-11 rounded-xl bg-brand px-4 text-[13px] font-bold text-white disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
                >
                  {saving ? "만드는 중..." : "합류 링크 만들기"}
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </article>
  );
}
