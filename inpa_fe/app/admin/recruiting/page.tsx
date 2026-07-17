"use client";

import Link from "next/link";
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { createPortal } from "react-dom";

import { Card } from "@/components/ui";
import { getWrappedFocusIndex } from "@/components/recruiting/recruiting-integration";
import {
  adminCreateRecruitingTemplate,
  adminGetRecruitingSummary,
  adminListRecruitingAudit,
  adminListRecruitingCandidates,
  adminListRecruitingPromotions,
  adminListRecruitingTemplates,
  adminPurgeRecruitingCandidate,
  adminUpdateRecruitingTemplate,
  type AdminRecruitingAuditRow,
  type AdminRecruitingCandidateRow,
  type AdminRecruitingPromotion,
  type AdminRecruitingSummary,
  type AdminRecruitingTemplate,
} from "@/lib/adminApi";
import { ApiError, type PaginatedResult } from "@/lib/api";
import { useAdminGuard } from "@/lib/useAdminGuard";

import {
  PURGE_REASON_LABELS,
  RECRUITING_EVENT_LABELS,
  RECRUITING_STAGE_LABELS,
  RECRUITING_TEMPLATE_KIND_LABELS,
  createLatestRequestGate,
  focusAdminRecruitingTarget,
  getAdminRecruitingFailure,
  getCandidateContactStatusLabel,
  getRecruitingActorLabel,
  getRecruitingRolloutCopy,
  getRecruitingTemplateIssue,
  normalizeAdminRecruitingPage,
  shouldRefreshCandidatesAfterPurge,
  type AdminRecruitingFailure,
  type AdminRecruitingPurgeReason,
  type AdminRecruitingTemplateDraft,
  type AdminRecruitingTemplateKind,
} from "./view-model";

const PRIMARY_BUTTON =
  "min-h-11 rounded-xl bg-brand px-4 py-2.5 text-[13px] font-bold text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-55 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2";
const SECONDARY_BUTTON =
  "min-h-11 rounded-xl border border-line bg-surface px-4 py-2.5 text-[13px] font-semibold text-ink2 transition hover:bg-surface2 disabled:cursor-not-allowed disabled:opacity-55 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2";
const FIELD_CLASS =
  "min-h-11 w-full rounded-xl border border-line bg-surface px-3 py-2.5 text-[14px] text-ink outline-none transition placeholder:text-muted focus:border-brand focus:ring-2 focus:ring-brand/15 disabled:cursor-not-allowed disabled:opacity-60";

const numberFormatter = new Intl.NumberFormat("ko-KR");

function formatDate(value: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(date);
}

function formatDateTime(value: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function toFailure(error: unknown, fallback: string): AdminRecruitingFailure {
  return getAdminRecruitingFailure(
    error instanceof ApiError ? error.status : null,
    error instanceof ApiError ? error.message : "",
    fallback,
  );
}

function useLatestRequestGate() {
  const gateRef = useRef<ReturnType<typeof createLatestRequestGate> | null>(null);
  if (gateRef.current === null) gateRef.current = createLatestRequestGate();
  const gate = gateRef.current;
  useEffect(() => () => gate.invalidate(), [gate]);
  return gate;
}

function ConsoleSkeleton() {
  return (
    <div role="status" aria-live="polite" className="mx-auto max-w-[1440px] space-y-8">
      <span className="sr-only">설계사 영입 운영 정보를 불러오는 중이에요.</span>
      <div aria-hidden="true" className="h-9 w-48 animate-pulse rounded-xl bg-line" />
      <div
        aria-hidden="true"
        className="grid grid-cols-1 gap-3 min-[360px]:grid-cols-2 lg:grid-cols-5"
      >
        {[0, 1, 2, 3, 4].map((item) => (
          <div key={item} className="h-28 animate-pulse rounded-2xl bg-line" />
        ))}
      </div>
      {[0, 1, 2].map((item) => (
        <div
          key={item}
          aria-hidden="true"
          className="h-52 animate-pulse rounded-2xl border border-line bg-surface"
        />
      ))}
    </div>
  );
}

function SectionSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div role="status" aria-live="polite" className="space-y-3">
      <span className="sr-only">운영 정보를 불러오는 중이에요.</span>
      {Array.from({ length: rows }, (_, index) => (
        <div
          key={index}
          aria-hidden="true"
          className="h-20 animate-pulse rounded-2xl border border-line bg-surface"
        />
      ))}
    </div>
  );
}

function SectionHeading({
  id,
  title,
  description,
  action,
}: {
  id: string;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <h2 id={id} className="text-[18px] font-extrabold text-ink sm:text-[20px]">
          {title}
        </h2>
        <p className="mt-1 text-[13px] leading-5 text-ink3">{description}</p>
      </div>
      {action}
    </div>
  );
}

function SectionError({
  failure,
  onRetry,
}: {
  failure: AdminRecruitingFailure;
  onRetry: () => void;
}) {
  return (
    <div
      role="alert"
      className="rounded-2xl border border-line bg-danger-tint px-5 py-6 text-center"
    >
      <p className="text-[14px] font-semibold leading-6 text-danger-ink">
        {failure.message}
      </p>
      {failure.needsAdminLogin ? (
        <Link href="/admin-login" className={`${PRIMARY_BUTTON} mt-4 inline-flex items-center`}>
          관리자 로그인
        </Link>
      ) : (
        <button type="button" onClick={onRetry} className={`${PRIMARY_BUTTON} mt-4`}>
          다시 불러오기
        </button>
      )}
    </div>
  );
}

function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-dashed border-line-2 bg-surface px-5 py-10 text-center">
      <p className="text-[15px] font-bold text-ink">{title}</p>
      <p className="mx-auto mt-2 max-w-lg text-[13px] leading-5 text-ink3">{description}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

function StatusMessage({
  kind,
  children,
}: {
  kind: "success" | "error";
  children: React.ReactNode;
}) {
  return (
    <div
      role={kind === "error" ? "alert" : "status"}
      aria-live="polite"
      className={`rounded-xl border border-line px-4 py-3 text-[13px] font-semibold leading-5 ${
        kind === "success"
          ? "bg-success-tint text-success-ink"
          : "bg-danger-tint text-danger-ink"
      }`}
    >
      {children}
    </div>
  );
}

function OverviewSection() {
  const gate = useLatestRequestGate();
  const [summary, setSummary] = useState<AdminRecruitingSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [failure, setFailure] = useState<AdminRecruitingFailure | null>(null);

  const load = useCallback(async () => {
    const generation = gate.begin();
    setLoading(true);
    setFailure(null);
    try {
      const result = await adminGetRecruitingSummary();
      if (gate.isCurrent(generation)) setSummary(result);
    } catch (error) {
      if (gate.isCurrent(generation)) {
        setFailure(toFailure(error, "이번 달 영입 현황을 다시 불러와주세요."));
      }
    } finally {
      if (gate.isCurrent(generation)) setLoading(false);
    }
  }, [gate]);

  useEffect(() => {
    void load();
  }, [load]);

  const metrics = summary
    ? [
        ["방문", summary.visits],
        ["지원", summary.applications],
        ["팀 합류", summary.joins],
        ["정착 확인 완료", summary.settlements_completed],
        ["관리직 활성화", summary.manager_promotions],
      ]
    : [];
  const rollout = summary ? getRecruitingRolloutCopy(summary.recruiting_enabled) : null;

  return (
    <section id="recruiting-overview" aria-labelledby="overview-heading" className="scroll-mt-6">
      <SectionHeading
        id="overview-heading"
        title="이번 달 영입 현황"
        description="한국 시간 기준으로 방문부터 관리직 활성화까지 한눈에 확인합니다."
      />
      {loading && <SectionSkeleton rows={2} />}
      {!loading && failure && <SectionError failure={failure} onRetry={() => void load()} />}
      {!loading && summary && rollout && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-3 min-[360px]:grid-cols-2 lg:grid-cols-5">
            {metrics.map(([label, value]) => (
              <Card key={label} className="min-w-0 p-4">
                <p className="text-[12px] font-semibold text-ink3">{label}</p>
                <p className="mt-2 text-[28px] font-extrabold tracking-tight text-ink tnum">
                  {numberFormatter.format(value as number)}
                  <span className="ml-1 text-[12px] font-medium text-ink3">건</span>
                </p>
              </Card>
            ))}
          </div>
          <Card className="overflow-hidden">
            <div className="grid grid-cols-1 divide-y divide-line lg:grid-cols-3 lg:divide-x lg:divide-y-0">
              <div className="p-5">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[12px] font-semibold text-ink3">공개 상태</span>
                  <span
                    className={`rounded-full px-2.5 py-1 text-[11px] font-bold ${
                      summary.recruiting_enabled
                        ? "bg-success-tint text-success-ink"
                        : "bg-brand-soft text-brand-ink"
                    }`}
                  >
                    {rollout.label}
                  </span>
                </div>
                <p className="mt-2 text-[13px] leading-5 text-ink2">{rollout.description}</p>
              </div>
              <div className="p-5">
                <p className="text-[12px] font-semibold text-ink3">지원 정보 보관 기준</p>
                <p className="mt-2 text-[22px] font-extrabold text-ink tnum">
                  {numberFormatter.format(summary.retention_days)}일
                </p>
                <p className="mt-1 text-[12px] leading-5 text-ink3">
                  보관 기간이 지난 정보는 아래 목록에서 확인할 수 있어요.
                </p>
              </div>
              <div className="p-5">
                <p className="text-[12px] font-semibold text-ink3">정리 기록 유지 기준</p>
                <p className="mt-2 text-[22px] font-extrabold text-ink tnum">
                  {numberFormatter.format(summary.tombstone_days)}일
                </p>
                <p className="mt-1 text-[12px] leading-5 text-ink3">
                  개인 정보를 가린 뒤 운영 기록을 유지하는 기간입니다.
                </p>
              </div>
            </div>
          </Card>
        </div>
      )}
    </section>
  );
}

function PurgeDialog({
  candidate,
  onClose,
  onConfirm,
}: {
  candidate: AdminRecruitingCandidateRow;
  onClose: () => void;
  onConfirm: (reason: AdminRecruitingPurgeReason) => Promise<string | null>;
}) {
  const titleId = useId();
  const descriptionId = useId();
  const [step, setStep] = useState<"reason" | "confirm">("reason");
  const [reason, setReason] = useState<AdminRecruitingPurgeReason | "">("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const reasonRef = useRef<HTMLSelectElement>(null);
  const backRef = useRef<HTMLButtonElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const pendingRef = useRef(false);
  const closeRef = useRef(onClose);
  const submitLockRef = useRef(false);

  useEffect(() => {
    pendingRef.current = pending;
    closeRef.current = onClose;
  });

  useEffect(() => {
    restoreFocusRef.current = document.activeElement as HTMLElement | null;

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !pendingRef.current) {
        event.preventDefault();
        closeRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(
        dialogRef.current?.querySelectorAll<HTMLElement>(
          "button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])",
        ) ?? [],
      );
      if (focusable.length === 0) {
        event.preventDefault();
        dialogRef.current?.focus();
        return;
      }
      const activeIndex = focusable.indexOf(document.activeElement as HTMLElement);
      const targetIndex = getWrappedFocusIndex(
        activeIndex,
        focusable.length,
        event.shiftKey,
      );
      if (targetIndex !== null) {
        event.preventDefault();
        focusable[targetIndex].focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      const previous = restoreFocusRef.current;
      if (previous?.isConnected) previous.focus();
    };
  }, []);

  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      if (step === "reason") reasonRef.current?.focus();
      else backRef.current?.focus();
    });
    return () => cancelAnimationFrame(frame);
  }, [step]);

  async function submit() {
    if (!reason || submitLockRef.current) return;
    submitLockRef.current = true;
    setPending(true);
    setError(null);
    try {
      const message = await onConfirm(reason);
      if (message) setError(message);
    } finally {
      submitLockRef.current = false;
      setPending(false);
    }
  }

  if (typeof document === "undefined") return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/45 sm:items-center sm:p-4"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !pending) onClose();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        aria-busy={pending}
        tabIndex={-1}
        className="max-h-[92dvh] w-full overflow-y-auto rounded-t-3xl bg-surface px-5 pb-7 pt-6 shadow-xl sm:max-w-md sm:rounded-3xl sm:px-6"
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-[11px] font-bold text-brand">{step === "reason" ? "1 / 2" : "2 / 2"}</p>
            <h3 id={titleId} className="mt-1 text-[19px] font-extrabold text-ink">
              {step === "reason" ? "정보 정리 사유 선택" : "정리 내용 최종 확인"}
            </h3>
          </div>
          <button
            type="button"
            disabled={pending}
            onClick={onClose}
            aria-label="창 닫기"
            className="grid min-h-11 min-w-11 place-items-center rounded-xl text-[22px] text-ink3 hover:bg-surface2 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
          >
            ×
          </button>
        </div>

        {step === "reason" ? (
          <div className="mt-5">
            <p id={descriptionId} className="text-[13px] leading-6 text-ink2">
              실제 요청에 맞는 사유 하나를 선택해주세요. 정해진 사유만 저장하며, 개인 정보는 모두
              같은 기준으로 정리됩니다.
            </p>
            <label htmlFor="purge-reason" className="mt-4 block text-[12px] font-bold text-ink2">
              정리 사유
            </label>
            <select
              ref={reasonRef}
              id="purge-reason"
              value={reason}
              onChange={(event) => {
                setReason(event.target.value as AdminRecruitingPurgeReason | "");
                setError(null);
              }}
              className={`${FIELD_CLASS} mt-1.5`}
            >
              <option value="">사유를 선택해주세요</option>
              {Object.entries(PURGE_REASON_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
            <button
              type="button"
              disabled={!reason}
              onClick={() => setStep("confirm")}
              className={`${PRIMARY_BUTTON} mt-6 w-full`}
            >
              다음 확인
            </button>
          </div>
        ) : (
          <div className="mt-5">
            <p id={descriptionId} className="text-[13px] leading-6 text-ink2">
              합류 이력이 있으면 서버가 기록을 보호하고 다음 절차를 안내합니다. 아래 가려진 정보와
              사유가 맞는지 한 번 더 확인해주세요.
            </p>
            <dl className="mt-4 divide-y divide-line rounded-2xl border border-line bg-surface2 px-4">
              <div className="flex items-center justify-between gap-4 py-3">
                <dt className="text-[12px] font-semibold text-ink3">지원자</dt>
                <dd className="text-right text-[13px] font-bold text-ink">
                  {candidate.name_masked} · {candidate.phone_masked}
                </dd>
              </div>
              <div className="flex items-center justify-between gap-4 py-3">
                <dt className="text-[12px] font-semibold text-ink3">사유</dt>
                <dd className="text-right text-[13px] font-bold text-ink">
                  {reason ? PURGE_REASON_LABELS[reason] : "-"}
                </dd>
              </div>
              <div className="py-3">
                <dt className="text-[12px] font-semibold text-ink3">지원 확인 번호</dt>
                <dd className="mt-1 break-all font-mono text-[11px] font-bold text-ink">
                  {candidate.support_reference}
                </dd>
              </div>
            </dl>
            {error && (
              <div role="alert" className="mt-4 rounded-xl bg-danger-tint px-4 py-3 text-[13px] leading-5 text-danger-ink">
                {error}
              </div>
            )}
            <div className="mt-6 flex flex-col-reverse gap-2.5 sm:flex-row">
              <button
                ref={backRef}
                type="button"
                disabled={pending}
                onClick={() => {
                  setStep("reason");
                  setError(null);
                }}
                className={`${SECONDARY_BUTTON} flex-1`}
              >
                사유 다시 선택
              </button>
              <button
                type="button"
                disabled={pending}
                onClick={() => void submit()}
                className={`${PRIMARY_BUTTON} flex-1`}
              >
                {pending ? "정보 정리 중..." : "정보 정리하기"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}

function CandidateSection() {
  const gate = useLatestRequestGate();
  const candidateSectionRef = useRef<HTMLElement>(null);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<PaginatedResult<AdminRecruitingCandidateRow> | null>(null);
  const [loading, setLoading] = useState(true);
  const [failure, setFailure] = useState<AdminRecruitingFailure | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [referenceDraft, setReferenceDraft] = useState("");
  const [reference, setReference] = useState("");
  const [purgeTarget, setPurgeTarget] = useState<AdminRecruitingCandidateRow | null>(null);
  const [refreshAfterPurge, setRefreshAfterPurge] = useState(false);

  const load = useCallback(
    async (requestedPage: number) => {
      const safePage = normalizeAdminRecruitingPage(requestedPage);
      const generation = gate.begin();
      setLoading(true);
      setFailure(null);
      try {
        const result = await adminListRecruitingCandidates(safePage, reference);
        if (gate.isCurrent(generation)) {
          setData(result);
          setPage(safePage);
        }
      } catch (error) {
        if (gate.isCurrent(generation)) {
          setFailure(toFailure(error, "지원 정보 목록을 다시 불러와주세요."));
        }
      } finally {
        if (gate.isCurrent(generation)) setLoading(false);
      }
    },
    [gate, reference],
  );

  useEffect(() => {
    void load(page);
  }, [load, page]);

  useEffect(() => {
    if (!shouldRefreshCandidatesAfterPurge(purgeTarget !== null, refreshAfterPurge)) return;
    // 정리된 행이 사라져도 초점이 본문으로 빠지지 않도록 남아 있는 구역으로 먼저 옮긴다.
    const frame = requestAnimationFrame(() => {
      focusAdminRecruitingTarget(candidateSectionRef.current);
      setRefreshAfterPurge(false);
      void load(page);
    });
    return () => cancelAnimationFrame(frame);
  }, [load, page, purgeTarget, refreshAfterPurge]);

  async function purgeCandidate(reason: AdminRecruitingPurgeReason): Promise<string | null> {
    if (!purgeTarget) return "정리할 지원 정보를 다시 선택해주세요.";
    gate.invalidate();
    try {
      await adminPurgeRecruitingCandidate(purgeTarget.id, reason);
      setSuccess(`${purgeTarget.name_masked} 지원 정보를 정리했습니다.`);
      setPurgeTarget(null);
      setRefreshAfterPurge(true);
      return null;
    } catch (error) {
      return toFailure(error, "지원 정보를 다시 확인한 뒤 정리를 이어가주세요.").message;
    }
  }

  const rows = data?.results ?? [];

  return (
    <section
      ref={candidateSectionRef}
      id="recruiting-candidates"
      aria-labelledby="candidates-heading"
      tabIndex={-1}
      className="scroll-mt-6 focus:outline-none"
    >
      <SectionHeading
        id="candidates-heading"
        title="지원 정보 정리"
        description="지원자가 알려준 확인 번호로 정확히 찾고, 가려진 정보로 한 번 더 확인합니다."
      />
      <Card className="mb-4 p-4">
        <form
          className="flex flex-col gap-2 sm:flex-row sm:items-end"
          onSubmit={(event) => {
            event.preventDefault();
            setPage(1);
            setReference(referenceDraft.trim());
          }}
        >
          <label className="min-w-0 flex-1 text-[12px] font-bold text-ink2">
            지원 확인 번호
            <input
              value={referenceDraft}
              onChange={(event) => setReferenceDraft(event.target.value)}
              placeholder="전체 번호를 붙여넣어 주세요"
              autoComplete="off"
              className={`${FIELD_CLASS} mt-1.5 font-mono text-[12px]`}
            />
          </label>
          <button type="submit" className={`${PRIMARY_BUTTON} sm:w-auto`}>
            번호로 찾기
          </button>
          {reference && (
            <button
              type="button"
              onClick={() => {
                setReferenceDraft("");
                setReference("");
                setPage(1);
              }}
              className={`${SECONDARY_BUTTON} sm:w-auto`}
            >
              전체 보기
            </button>
          )}
        </form>
      </Card>
      {success && (
        <div className="mb-4">
          <StatusMessage kind="success">{success}</StatusMessage>
        </div>
      )}
      {loading && <SectionSkeleton />}
      {!loading && failure && <SectionError failure={failure} onRetry={() => void load(page)} />}
      {!loading && !failure && data && rows.length === 0 && (
        <EmptyState
          title={
            reference
              ? "이 확인 번호와 일치하는 지원 정보가 없어요."
              : page > 1
                ? "이 페이지 확인을 마쳤어요."
                : "지원 정보 정리가 모두 끝났어요."
          }
          description={
            reference
              ? "지원자에게 받은 전체 번호를 다시 확인해주세요."
              : page > 1
              ? "이전 페이지에서 남은 정보를 이어서 확인해보세요."
              : "보관 기간이 지난 정보가 생기면 이곳에서 가려진 값으로 확인할 수 있어요."
          }
          action={
            reference ? (
              <button
                type="button"
                onClick={() => {
                  setReferenceDraft("");
                  setReference("");
                }}
                className={SECONDARY_BUTTON}
              >
                전체 지원 정보 보기
              </button>
            ) : page > 1 ? (
              <button type="button" onClick={() => setPage(page - 1)} className={SECONDARY_BUTTON}>
                이전 페이지 보기
              </button>
            ) : (
              <a href="#recruiting-overview" className={`${SECONDARY_BUTTON} inline-flex items-center`}>
                보관 기준 확인
              </a>
            )
          }
        />
      )}
      {!loading && !failure && data && rows.length > 0 && (
        <>
          <div className="mb-2 flex items-center justify-between gap-3 text-[12px] text-ink3">
            <span className="tnum">전체 {numberFormatter.format(data.count)}건</span>
            <span>페이지 {page}</span>
          </div>
          <Card className="hidden overflow-hidden md:block">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[920px] text-[13px]">
                <caption className="sr-only">정리 대상 지원 정보 목록</caption>
                <thead className="bg-surface2 text-ink3">
                  <tr>
                    <th scope="col" className="px-4 py-3 text-left font-semibold">지원자</th>
                    <th scope="col" className="px-4 py-3 text-left font-semibold">전화번호</th>
                    <th scope="col" className="px-4 py-3 text-left font-semibold">확인 번호</th>
                    <th scope="col" className="px-4 py-3 text-left font-semibold">단계</th>
                    <th scope="col" className="px-4 py-3 text-left font-semibold">등록일</th>
                    <th scope="col" className="px-4 py-3 text-left font-semibold">보관 만료일</th>
                    <th scope="col" className="px-4 py-3 text-left font-semibold">연락 상태</th>
                    <th scope="col" className="px-4 py-3 text-right font-semibold">작업</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {rows.map((candidate) => (
                    <tr key={candidate.id} className="hover:bg-surface2/70">
                      <td className="px-4 py-3 font-bold text-ink">{candidate.name_masked}</td>
                      <td className="px-4 py-3 text-ink2 tnum">{candidate.phone_masked}</td>
                      <td className="max-w-[220px] break-all px-4 py-3 font-mono text-[11px] text-ink3">
                        {candidate.support_reference}
                      </td>
                      <td className="px-4 py-3">
                        <span className="rounded-full bg-brand-soft px-2.5 py-1 text-[11px] font-bold text-brand-ink">
                          {RECRUITING_STAGE_LABELS[candidate.stage]}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-ink3 tnum">{formatDate(candidate.created_at)}</td>
                      <td className="px-4 py-3 text-ink3 tnum">{formatDate(candidate.retention_expires_at)}</td>
                      <td className="px-4 py-3">
                        <span className="rounded-full bg-surface2 px-2.5 py-1 text-[11px] font-bold text-ink2">
                          {getCandidateContactStatusLabel(
                            candidate.stage,
                            candidate.contact_opted_out,
                          )}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          type="button"
                          onClick={() => {
                            setSuccess(null);
                            setPurgeTarget(candidate);
                          }}
                          className="min-h-10 rounded-xl border border-line px-3 py-2 text-[12px] font-bold text-danger-ink hover:bg-danger-tint focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
                        >
                          정보 정리
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <div className="space-y-3 md:hidden">
            {rows.map((candidate) => (
              <Card key={candidate.id} className="min-w-0 overflow-hidden p-4">
                <div className="flex min-w-0 items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="break-words text-[15px] font-extrabold text-ink">
                      {candidate.name_masked}
                    </p>
                    <p className="mt-1 break-all text-[13px] text-ink2 tnum">
                      {candidate.phone_masked}
                    </p>
                    <p className="mt-2 break-all font-mono text-[10px] leading-4 text-ink3">
                      확인 번호 {candidate.support_reference}
                    </p>
                  </div>
                  <span className="shrink-0 rounded-full bg-brand-soft px-2.5 py-1 text-[11px] font-bold text-brand-ink">
                    {RECRUITING_STAGE_LABELS[candidate.stage]}
                  </span>
                </div>
                <dl className="mt-4 grid grid-cols-1 gap-3 min-[360px]:grid-cols-2">
                  <div>
                    <dt className="text-[11px] font-semibold text-ink3">등록일</dt>
                    <dd className="mt-0.5 text-[13px] text-ink tnum">{formatDate(candidate.created_at)}</dd>
                  </div>
                  <div>
                    <dt className="text-[11px] font-semibold text-ink3">보관 만료일</dt>
                    <dd className="mt-0.5 text-[13px] text-ink tnum">
                      {formatDate(candidate.retention_expires_at)}
                    </dd>
                  </div>
                </dl>
                <div className="mt-4 flex flex-col gap-3 border-t border-line pt-4 min-[360px]:flex-row min-[360px]:items-center min-[360px]:justify-between">
                  <span className="w-fit rounded-full bg-surface2 px-2.5 py-1 text-[11px] font-bold text-ink2">
                    {getCandidateContactStatusLabel(
                      candidate.stage,
                      candidate.contact_opted_out,
                    )}
                  </span>
                  <button
                    type="button"
                    onClick={() => {
                      setSuccess(null);
                      setPurgeTarget(candidate);
                    }}
                    className={`${SECONDARY_BUTTON} w-full text-danger-ink min-[360px]:w-auto`}
                  >
                    정보 정리
                  </button>
                </div>
              </Card>
            ))}
          </div>

          <div className="mt-4 flex items-center justify-center gap-3">
            <button
              type="button"
              disabled={!data.previous}
              onClick={() => setPage((current) => normalizeAdminRecruitingPage(current - 1))}
              className={SECONDARY_BUTTON}
            >
              이전
            </button>
            <span className="text-[13px] font-semibold text-ink3 tnum">{page}페이지</span>
            <button
              type="button"
              disabled={!data.next}
              onClick={() => setPage((current) => current + 1)}
              className={SECONDARY_BUTTON}
            >
              다음
            </button>
          </div>
        </>
      )}
      {purgeTarget && (
        <PurgeDialog
          candidate={purgeTarget}
          onClose={() => setPurgeTarget(null)}
          onConfirm={purgeCandidate}
        />
      )}
    </section>
  );
}

type TemplateEditor =
  | { mode: "create" }
  | { mode: "edit"; template: AdminRecruitingTemplate };

function emptyTemplateDraft(): AdminRecruitingTemplateDraft {
  return {
    code: "",
    kind: "headline",
    title: "",
    body: "",
    sortOrder: 0,
  };
}

function templateDraft(template: AdminRecruitingTemplate): AdminRecruitingTemplateDraft {
  return {
    code: template.code,
    kind: template.kind,
    title: template.title,
    body: template.body,
    sortOrder: template.sort_order,
  };
}

function TemplateSection() {
  const gate = useLatestRequestGate();
  const [templates, setTemplates] = useState<AdminRecruitingTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [failure, setFailure] = useState<AdminRecruitingFailure | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [editor, setEditor] = useState<TemplateEditor | null>(null);
  const [draft, setDraft] = useState<AdminRecruitingTemplateDraft>(emptyTemplateDraft);
  const [active, setActive] = useState(true);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const submitLockRef = useRef(false);
  const editorPanelRef = useRef<HTMLDivElement>(null);
  const firstEditorFieldRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    const generation = gate.begin();
    setLoading(true);
    setFailure(null);
    try {
      const result = await adminListRecruitingTemplates();
      if (gate.isCurrent(generation)) setTemplates(result);
    } catch (error) {
      if (gate.isCurrent(generation)) {
        setFailure(toFailure(error, "영입 문구를 다시 불러와주세요."));
      }
    } finally {
      if (gate.isCurrent(generation)) setLoading(false);
    }
  }, [gate]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!editor) return;
    const frame = requestAnimationFrame(() => {
      editorPanelRef.current?.scrollIntoView({ block: "start" });
      firstEditorFieldRef.current?.focus();
    });
    return () => cancelAnimationFrame(frame);
  }, [editor]);

  function openCreate() {
    setEditor({ mode: "create" });
    setDraft(emptyTemplateDraft());
    setActive(true);
    setFormError(null);
    setSuccess(null);
  }

  function openEdit(template: AdminRecruitingTemplate) {
    setEditor({ mode: "edit", template });
    setDraft(templateDraft(template));
    setActive(template.is_active);
    setFormError(null);
    setSuccess(null);
  }

  async function saveTemplate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editor || submitLockRef.current) return;
    const issue = getRecruitingTemplateIssue(draft, editor.mode);
    if (issue) {
      setFormError(issue);
      return;
    }

    submitLockRef.current = true;
    setSaving(true);
    setFormError(null);
    gate.invalidate();
    try {
      if (editor.mode === "create") {
        await adminCreateRecruitingTemplate({
          code: draft.code.trim(),
          kind: draft.kind,
          title: draft.title.trim(),
          body: draft.body.trim(),
          is_active: active,
          sort_order: draft.sortOrder,
        });
        setSuccess("새 영입 문구를 저장했습니다.");
      } else {
        await adminUpdateRecruitingTemplate(editor.template.id, {
          title: draft.title.trim(),
          body: draft.body.trim(),
          is_active: active,
          sort_order: draft.sortOrder,
        });
        setSuccess("영입 문구 변경 내용을 저장했습니다.");
      }
      setEditor(null);
      await load();
    } catch (error) {
      setFormError(toFailure(error, "문구 내용을 다시 확인한 뒤 저장해주세요.").message);
    } finally {
      submitLockRef.current = false;
      setSaving(false);
    }
  }

  return (
    <section id="recruiting-copy" aria-labelledby="copy-heading" className="scroll-mt-6">
      <SectionHeading
        id="copy-heading"
        title="영입 문구와 자주 묻는 질문"
        description="제목, 내용, 사용 상태, 정렬 순서를 관리합니다. 처음 저장한 코드와 종류는 그대로 유지됩니다."
        action={
          <button type="button" onClick={openCreate} className={`${PRIMARY_BUTTON} w-full sm:w-auto`}>
            문구 추가
          </button>
        }
      />
      {success && (
        <div className="mb-4">
          <StatusMessage kind="success">{success}</StatusMessage>
        </div>
      )}
      {loading && <SectionSkeleton />}
      {!loading && failure && <SectionError failure={failure} onRetry={() => void load()} />}
      {!loading && !failure && (
        <div className="grid min-w-0 gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(320px,420px)]">
          <div className="min-w-0">
            {templates.length === 0 ? (
              <EmptyState
                title="첫 영입 문구를 만들어보세요."
                description="첫 문장이나 자주 묻는 질문부터 한 개 만들어보세요."
                action={
                  <button type="button" onClick={openCreate} className={PRIMARY_BUTTON}>
                    첫 문구 만들기
                  </button>
                }
              />
            ) : (
              <div className="space-y-3">
                {templates.map((template) => (
                  <Card
                    key={template.id}
                    className={`min-w-0 overflow-hidden p-4 sm:p-5 ${
                      editor?.mode === "edit" && editor.template.id === template.id
                        ? "ring-2 ring-brand/30"
                        : ""
                    }`}
                  >
                    <div className="flex min-w-0 flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="rounded-full bg-brand-soft px-2.5 py-1 text-[11px] font-bold text-brand-ink">
                            {RECRUITING_TEMPLATE_KIND_LABELS[template.kind]}
                          </span>
                          <span
                            className={`rounded-full px-2.5 py-1 text-[11px] font-bold ${
                              template.is_active
                                ? "bg-success-tint text-success-ink"
                                : "bg-surface2 text-ink3"
                            }`}
                          >
                            {template.is_active ? "사용 중" : "보관 중"}
                          </span>
                          <span className="text-[11px] text-ink3 tnum">
                            순서 {template.sort_order}
                          </span>
                        </div>
                        <h3 className="mt-3 break-words text-[15px] font-extrabold text-ink">
                          {template.title}
                        </h3>
                        <p className="mt-1 break-words text-[13px] leading-6 text-ink2">
                          {template.body}
                        </p>
                        <p className="mt-3 break-all text-[11px] text-ink3">
                          코드: {template.code}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => openEdit(template)}
                        className={`${SECONDARY_BUTTON} w-full shrink-0 sm:w-auto`}
                      >
                        수정
                      </button>
                    </div>
                  </Card>
                ))}
              </div>
            )}
          </div>

          {editor && (
            <div
              ref={editorPanelRef}
              className="order-first scroll-mt-4 xl:order-none"
            >
            <Card className="h-fit min-w-0 overflow-hidden p-4 xl:sticky xl:top-4 xl:p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-[11px] font-bold text-brand">
                    {editor.mode === "create" ? "새 문구" : "문구 수정"}
                  </p>
                  <h3 className="mt-1 text-[17px] font-extrabold text-ink">
                    {editor.mode === "create" ? "영입 문구 추가" : editor.template.title}
                  </h3>
                </div>
                <button
                  type="button"
                  disabled={saving}
                  onClick={() => setEditor(null)}
                  aria-label="편집 닫기"
                  className="grid min-h-11 min-w-11 place-items-center rounded-xl text-[22px] text-ink3 hover:bg-surface2 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
                >
                  ×
                </button>
              </div>

              <form onSubmit={saveTemplate} className="mt-5 space-y-4" noValidate>
                {editor.mode === "create" ? (
                  <>
                    <div>
                      <div className="flex items-center justify-between gap-3">
                        <label htmlFor="template-code" className="text-[12px] font-bold text-ink2">
                          코드
                        </label>
                        <span className="text-[11px] text-ink3 tnum">{draft.code.length} / 60</span>
                      </div>
                      <input
                        ref={firstEditorFieldRef}
                        id="template-code"
                        value={draft.code}
                        maxLength={60}
                        autoComplete="off"
                        placeholder="예: welcome-note"
                        disabled={saving}
                        onChange={(event) =>
                          setDraft((current) => ({ ...current, code: event.target.value }))
                        }
                        className={`${FIELD_CLASS} mt-1.5`}
                      />
                      <p className="mt-1.5 text-[11px] leading-5 text-ink3">
                        영문 소문자, 숫자, 하이픈, 밑줄을 사용할 수 있어요.
                      </p>
                    </div>
                    <div>
                      <label htmlFor="template-kind" className="text-[12px] font-bold text-ink2">
                        문구 종류
                      </label>
                      <select
                        id="template-kind"
                        value={draft.kind}
                        disabled={saving}
                        onChange={(event) =>
                          setDraft((current) => ({
                            ...current,
                            kind: event.target.value as AdminRecruitingTemplateKind,
                          }))
                        }
                        className={`${FIELD_CLASS} mt-1.5`}
                      >
                        {(Object.keys(RECRUITING_TEMPLATE_KIND_LABELS) as AdminRecruitingTemplateKind[]).map(
                          (kind) => (
                            <option key={kind} value={kind}>
                              {RECRUITING_TEMPLATE_KIND_LABELS[kind]}
                            </option>
                          ),
                        )}
                      </select>
                    </div>
                  </>
                ) : (
                  <div className="grid grid-cols-1 gap-3 rounded-2xl bg-surface2 p-4 min-[360px]:grid-cols-2">
                    <div className="min-w-0">
                      <p className="text-[11px] font-semibold text-ink3">코드</p>
                      <p className="mt-1 break-all text-[12px] font-bold text-ink">
                        {editor.template.code}
                      </p>
                    </div>
                    <div>
                      <p className="text-[11px] font-semibold text-ink3">문구 종류</p>
                      <p className="mt-1 text-[12px] font-bold text-ink">
                        {RECRUITING_TEMPLATE_KIND_LABELS[editor.template.kind]}
                      </p>
                    </div>
                    <p className="text-[11px] leading-5 text-ink3 min-[360px]:col-span-2">
                      코드와 종류는 처음 저장한 값으로 유지됩니다.
                    </p>
                  </div>
                )}

                <div>
                  <div className="flex items-center justify-between gap-3">
                    <label htmlFor="template-title" className="text-[12px] font-bold text-ink2">
                      제목
                    </label>
                    <span className="text-[11px] text-ink3 tnum">{draft.title.length} / 80</span>
                  </div>
                  <input
                    ref={editor.mode === "edit" ? firstEditorFieldRef : undefined}
                    id="template-title"
                    value={draft.title}
                    maxLength={80}
                    disabled={saving}
                    onChange={(event) =>
                      setDraft((current) => ({ ...current, title: event.target.value }))
                    }
                    className={`${FIELD_CLASS} mt-1.5`}
                  />
                </div>

                <div>
                  <div className="flex items-center justify-between gap-3">
                    <label htmlFor="template-body" className="text-[12px] font-bold text-ink2">
                      내용
                    </label>
                    <span className="text-[11px] text-ink3 tnum">{draft.body.length} / 300</span>
                  </div>
                  <textarea
                    id="template-body"
                    value={draft.body}
                    maxLength={300}
                    rows={6}
                    disabled={saving}
                    onChange={(event) =>
                      setDraft((current) => ({ ...current, body: event.target.value }))
                    }
                    className={`${FIELD_CLASS} mt-1.5 resize-y`}
                  />
                </div>

                <div>
                  <label htmlFor="template-order" className="text-[12px] font-bold text-ink2">
                    정렬 순서
                  </label>
                  <input
                    id="template-order"
                    type="number"
                    min={0}
                    max={32767}
                    step={1}
                    value={Number.isFinite(draft.sortOrder) ? draft.sortOrder : ""}
                    disabled={saving}
                    onChange={(event) =>
                      setDraft((current) => ({
                        ...current,
                        sortOrder: event.target.value === "" ? Number.NaN : Number(event.target.value),
                      }))
                    }
                    className={`${FIELD_CLASS} mt-1.5`}
                  />
                </div>

                <label className="flex min-h-11 cursor-pointer items-center gap-3 rounded-xl border border-line px-3 py-2.5 text-[13px] font-semibold text-ink2">
                  <input
                    type="checkbox"
                    checked={active}
                    disabled={saving}
                    onChange={(event) => setActive(event.target.checked)}
                    className="h-4 w-4 accent-[var(--brand)]"
                  />
                  설계사 화면에서 사용
                </label>

                {formError && <StatusMessage kind="error">{formError}</StatusMessage>}

                <button type="submit" disabled={saving} className={`${PRIMARY_BUTTON} w-full`}>
                  {saving ? "저장 중..." : "변경 내용 저장"}
                </button>
              </form>
            </Card>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function PromotionSection() {
  const gate = useLatestRequestGate();
  const [items, setItems] = useState<AdminRecruitingPromotion[]>([]);
  const [loading, setLoading] = useState(true);
  const [failure, setFailure] = useState<AdminRecruitingFailure | null>(null);

  const load = useCallback(async () => {
    const generation = gate.begin();
    setLoading(true);
    setFailure(null);
    try {
      const result = await adminListRecruitingPromotions();
      if (gate.isCurrent(generation)) setItems(result);
    } catch (error) {
      if (gate.isCurrent(generation)) {
        setFailure(toFailure(error, "관리직 활성화 기록을 다시 불러와주세요."));
      }
    } finally {
      if (gate.isCurrent(generation)) setLoading(false);
    }
  }, [gate]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section id="recruiting-promotions" aria-labelledby="promotions-heading" className="scroll-mt-6">
      <SectionHeading
        id="promotions-heading"
        title="관리직 활성화 기록"
        description="현재 적용 요금제와 저장된 구독 요금제를 사실 그대로 비교합니다. 요금제 변경은 설계사 관리에서 이어가세요."
      />
      {loading && <SectionSkeleton />}
      {!loading && failure && <SectionError failure={failure} onRetry={() => void load()} />}
      {!loading && !failure && items.length === 0 && (
        <EmptyState
          title="첫 관리직 활성화가 이곳에 기록됩니다."
          description="활성화가 발생하면 프로필 이름, 날짜, 팀 인원, 두 요금제 정보를 이곳에서 확인할 수 있어요."
          action={
            <a href="#recruiting-overview" className={`${SECONDARY_BUTTON} inline-flex items-center`}>
              이번 달 현황 보기
            </a>
          }
        />
      )}
      {!loading && !failure && items.length > 0 && (
        <>
          <Card className="hidden overflow-hidden md:block">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] text-[13px]">
                <caption className="sr-only">관리직 활성화 기록</caption>
                <thead className="bg-surface2 text-ink3">
                  <tr>
                    <th scope="col" className="px-4 py-3 text-left font-semibold">프로필 이름</th>
                    <th scope="col" className="px-4 py-3 text-left font-semibold">활성화 날짜</th>
                    <th scope="col" className="px-4 py-3 text-left font-semibold">현재 팀 인원</th>
                    <th scope="col" className="px-4 py-3 text-left font-semibold">관리직 역할</th>
                    <th scope="col" className="px-4 py-3 text-left font-semibold">현재 적용 요금제</th>
                    <th scope="col" className="px-4 py-3 text-left font-semibold">저장된 구독 요금제</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {items.map((item) => (
                    <tr key={item.user_id}>
                      <td className="px-4 py-3 font-bold text-ink">{item.display_name}</td>
                      <td className="px-4 py-3 text-ink3 tnum">{formatDateTime(item.manager_promoted_at)}</td>
                      <td className="px-4 py-3 text-ink tnum">{numberFormatter.format(item.current_team_count)}명</td>
                      <td className="px-4 py-3">
                        <span className="rounded-full bg-success-tint px-2.5 py-1 text-[11px] font-bold text-success-ink">
                          {item.is_manager ? "관리직 활성" : "일반 설계사"}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-semibold text-ink">{item.effective_plan_code ?? "-"}</td>
                      <td className="px-4 py-3 font-semibold text-ink">{item.subscription_plan_code ?? "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <div className="space-y-3 md:hidden">
            {items.map((item) => (
              <Card key={item.user_id} className="min-w-0 overflow-hidden p-4">
                <div className="flex min-w-0 items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="break-words text-[15px] font-extrabold text-ink">{item.display_name}</p>
                    <p className="mt-1 text-[12px] text-ink3 tnum">{formatDateTime(item.manager_promoted_at)}</p>
                  </div>
                  <span className="shrink-0 rounded-full bg-success-tint px-2.5 py-1 text-[11px] font-bold text-success-ink">
                    {item.is_manager ? "관리직 활성" : "일반 설계사"}
                  </span>
                </div>
                <dl className="mt-4 grid grid-cols-1 gap-3 min-[360px]:grid-cols-2">
                  <div>
                    <dt className="text-[11px] font-semibold text-ink3">현재 팀 인원</dt>
                    <dd className="mt-1 text-[13px] font-bold text-ink tnum">
                      {numberFormatter.format(item.current_team_count)}명
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[11px] font-semibold text-ink3">현재 적용 요금제</dt>
                    <dd className="mt-1 break-all text-[13px] font-bold text-ink">
                      {item.effective_plan_code ?? "-"}
                    </dd>
                  </div>
                  <div className="min-[360px]:col-span-2">
                    <dt className="text-[11px] font-semibold text-ink3">저장된 구독 요금제</dt>
                    <dd className="mt-1 break-all text-[13px] font-bold text-ink">
                      {item.subscription_plan_code ?? "-"}
                    </dd>
                  </div>
                </dl>
              </Card>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

function stageLabel(value: AdminRecruitingAuditRow["from_stage"]): string {
  return value ? RECRUITING_STAGE_LABELS[value] : "-";
}

function AuditSection() {
  const gate = useLatestRequestGate();
  const [page, setPage] = useState(1);
  const [data, setData] = useState<PaginatedResult<AdminRecruitingAuditRow> | null>(null);
  const [loading, setLoading] = useState(true);
  const [failure, setFailure] = useState<AdminRecruitingFailure | null>(null);

  const load = useCallback(
    async (requestedPage: number) => {
      const safePage = normalizeAdminRecruitingPage(requestedPage);
      const generation = gate.begin();
      setLoading(true);
      setFailure(null);
      try {
        const result = await adminListRecruitingAudit(safePage);
        if (gate.isCurrent(generation)) {
          setData(result);
          setPage(safePage);
        }
      } catch (error) {
        if (gate.isCurrent(generation)) {
          setFailure(toFailure(error, "영입 운영 기록을 다시 불러와주세요."));
        }
      } finally {
        if (gate.isCurrent(generation)) setLoading(false);
      }
    },
    [gate],
  );

  useEffect(() => {
    void load(page);
  }, [load, page]);

  const rows = data?.results ?? [];

  return (
    <section id="recruiting-audit" aria-labelledby="audit-heading" className="scroll-mt-6">
      <SectionHeading
        id="audit-heading"
        title="개인 정보 없는 운영 기록"
        description="후보 참조값, 기록 종류, 정리 사유, 단계 변화, 처리자 번호, 날짜만 표시합니다."
      />
      {loading && <SectionSkeleton />}
      {!loading && failure && <SectionError failure={failure} onRetry={() => void load(page)} />}
      {!loading && !failure && data && rows.length === 0 && (
        <EmptyState
          title={page > 1 ? "이 페이지 확인을 마쳤어요." : "첫 영입 운영 기록이 이곳에 쌓입니다."}
          description={
            page > 1
              ? "이전 페이지에서 기록을 이어서 확인해보세요."
              : "단계 변경이나 정보 정리가 발생하면 개인 정보 없이 이곳에 남습니다."
          }
          action={
            page > 1 ? (
              <button type="button" onClick={() => setPage(page - 1)} className={SECONDARY_BUTTON}>
                이전 페이지 보기
              </button>
            ) : (
              <a href="#recruiting-candidates" className={`${SECONDARY_BUTTON} inline-flex items-center`}>
                지원 정보 정리 보기
              </a>
            )
          }
        />
      )}
      {!loading && !failure && data && rows.length > 0 && (
        <>
          <div className="mb-2 flex items-center justify-between gap-3 text-[12px] text-ink3">
            <span className="tnum">전체 {numberFormatter.format(data.count)}건</span>
            <span>페이지 {page}</span>
          </div>
          <Card className="hidden overflow-hidden md:block">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[980px] text-[13px]">
                <caption className="sr-only">개인 정보 없는 영입 운영 기록</caption>
                <thead className="bg-surface2 text-ink3">
                  <tr>
                    <th scope="col" className="px-4 py-3 text-left font-semibold">후보 참조값</th>
                    <th scope="col" className="px-4 py-3 text-left font-semibold">기록 종류</th>
                    <th scope="col" className="px-4 py-3 text-left font-semibold">정리 사유</th>
                    <th scope="col" className="px-4 py-3 text-left font-semibold">이전 단계</th>
                    <th scope="col" className="px-4 py-3 text-left font-semibold">다음 단계</th>
                    <th scope="col" className="px-4 py-3 text-left font-semibold">처리자</th>
                    <th scope="col" className="px-4 py-3 text-left font-semibold">기록일</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {rows.map((row, index) => (
                    <tr key={`${row.candidate_ref}-${row.created_at}-${index}`}>
                      <td className="max-w-[260px] break-all px-4 py-3 font-mono text-[11px] text-ink2">
                        {row.candidate_ref}
                      </td>
                      <td className="px-4 py-3 font-semibold text-ink">
                        {RECRUITING_EVENT_LABELS[row.event_type]}
                      </td>
                      <td className="px-4 py-3 text-ink3">
                        {row.reason_code ? PURGE_REASON_LABELS[row.reason_code] : "-"}
                      </td>
                      <td className="px-4 py-3 text-ink3">{stageLabel(row.from_stage)}</td>
                      <td className="px-4 py-3 text-ink3">{stageLabel(row.to_stage)}</td>
                      <td className="px-4 py-3 text-ink3 tnum">
                        {getRecruitingActorLabel(row.event_type, row.actor_id)}
                      </td>
                      <td className="px-4 py-3 text-ink3 tnum">{formatDateTime(row.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <div className="space-y-3 md:hidden">
            {rows.map((row, index) => (
              <Card key={`${row.candidate_ref}-${row.created_at}-${index}`} className="min-w-0 overflow-hidden p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="rounded-full bg-brand-soft px-2.5 py-1 text-[11px] font-bold text-brand-ink">
                    {RECRUITING_EVENT_LABELS[row.event_type]}
                  </span>
                  <span className="text-[11px] text-ink3 tnum">{formatDateTime(row.created_at)}</span>
                </div>
                <dl className="mt-4 space-y-3">
                  <div>
                    <dt className="text-[11px] font-semibold text-ink3">후보 참조값</dt>
                    <dd className="mt-1 break-all font-mono text-[11px] leading-5 text-ink2">
                      {row.candidate_ref}
                    </dd>
                  </div>
                  <div className="grid grid-cols-1 gap-3 min-[360px]:grid-cols-2">
                    <div>
                      <dt className="text-[11px] font-semibold text-ink3">단계 변화</dt>
                      <dd className="mt-1 text-[13px] font-semibold text-ink">
                        {stageLabel(row.from_stage)} → {stageLabel(row.to_stage)}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-[11px] font-semibold text-ink3">처리자</dt>
                      <dd className="mt-1 text-[13px] font-semibold text-ink tnum">
                        {getRecruitingActorLabel(row.event_type, row.actor_id)}
                      </dd>
                    </div>
                    {row.reason_code && (
                      <div className="min-[360px]:col-span-2">
                        <dt className="text-[11px] font-semibold text-ink3">정리 사유</dt>
                        <dd className="mt-1 text-[13px] font-semibold text-ink">
                          {PURGE_REASON_LABELS[row.reason_code]}
                        </dd>
                      </div>
                    )}
                  </div>
                </dl>
              </Card>
            ))}
          </div>
          <div className="mt-4 flex items-center justify-center gap-3">
            <button
              type="button"
              disabled={!data.previous}
              onClick={() => setPage((current) => normalizeAdminRecruitingPage(current - 1))}
              className={SECONDARY_BUTTON}
            >
              이전
            </button>
            <span className="text-[13px] font-semibold text-ink3 tnum">{page}페이지</span>
            <button
              type="button"
              disabled={!data.next}
              onClick={() => setPage((current) => current + 1)}
              className={SECONDARY_BUTTON}
            >
              다음
            </button>
          </div>
        </>
      )}
    </section>
  );
}

export default function AdminRecruitingPage() {
  const ready = useAdminGuard();

  if (!ready) return <ConsoleSkeleton />;

  return (
    <div className="mx-auto min-w-0 max-w-[1440px] overflow-x-hidden">
      <header className="mb-8">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-[24px] font-extrabold tracking-tight text-ink sm:text-[28px]">
            설계사 영입 운영
          </h1>
          <span className="rounded-full bg-surface px-2.5 py-1 text-[11px] font-bold text-ink3 ring-1 ring-line">
            관리자 조회·운영
          </span>
        </div>
        <p className="mt-2 max-w-3xl text-[13px] leading-6 text-ink3 sm:text-[14px]">
          고객 관리와 분리된 영입 운영 공간입니다. 지원 정보는 가려진 값만 사용하며, 문구와 보관
          흐름을 한곳에서 확인합니다.
        </p>
      </header>

      <div className="space-y-12">
        <OverviewSection />
        <CandidateSection />
        <TemplateSection />
        <PromotionSection />
        <AuditSection />
      </div>
    </div>
  );
}
