"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import {
  ApiError,
  confirmInsuranceImport,
  getInsuranceImport,
  getInsuranceImportDraft,
  patchInsuranceImportDraft,
  type ConfirmPayload,
  type DraftPatchPayload,
  type InsuranceImportDraft,
  type InsuranceImportJob,
} from "@/lib/api";
import { createIdempotencyKey, IMPORT_STATUS_COPY } from "@/lib/insurance-imports";
import { InsuranceDraftEditor } from "@/components/insurance-draft-editor";
import { InsuranceSourceViewer } from "@/components/insurance-source-viewer";

const POSITIVE_INTEGER = /^[1-9]\d*$/;
const CANONICAL_UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function parseInsuranceReviewRouteParams(params: {
  id: string | string[] | undefined;
  jobId: string | string[] | undefined;
}): { customerId: number; jobId: string } | null {
  if (typeof params.id !== "string" || typeof params.jobId !== "string") return null;
  if (!POSITIVE_INTEGER.test(params.id) || !CANONICAL_UUID.test(params.jobId)) return null;
  const customerId = Number(params.id);
  if (!Number.isSafeInteger(customerId) || customerId <= 0) return null;
  return { customerId, jobId: params.jobId };
}

const PROCESSING_STATUSES = new Set(["queued", "extracting", "validating"]);
const NETWORK_RETRY_DELAYS = [8_000, 16_000, 30_000] as const;
const MAX_COMMAND_RETRIES = 3;

type LoadError = "not_found" | "network" | "other";
type OperationContext = { generation: number };

export function InsuranceReviewWorkspace({
  customerId,
  jobId,
}: {
  customerId: number;
  jobId: string;
}) {
  const identity = `${customerId}:${jobId}`;
  return <InsuranceReviewWorkspaceIdentity key={identity} customerId={customerId} jobId={jobId} />;
}

function InsuranceReviewWorkspaceIdentity({
  customerId,
  jobId,
}: {
  customerId: number;
  jobId: string;
}) {
  const router = useRouter();
  const generationRef = useRef(0);
  const operationGenerationRef = useRef(0);
  const operationLockRef = useRef(false);
  const draftReloadGenerationRef = useRef(0);
  const draftReloadLockRef = useRef(false);
  const mountedRef = useRef(false);
  const operationDelayRef = useRef<{
    timer: ReturnType<typeof setTimeout>;
    resolve: (active: boolean) => void;
  } | null>(null);
  const [job, setJob] = useState<InsuranceImportJob | null>(null);
  const [draft, setDraft] = useState<InsuranceImportDraft | null>(null);
  const [customerMismatch, setCustomerMismatch] = useState(false);
  const [loadError, setLoadError] = useState<LoadError | null>(null);
  const [retryNonce, setRetryNonce] = useState(0);
  const [plannerConfirmedSourceMatch, setPlannerConfirmedSourceMatch] = useState(false);
  const [plannerConfirmedUnreadPages, setPlannerConfirmedUnreadPages] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isReloadingLatest, setIsReloadingLatest] = useState(false);
  const [hasVersionConflict, setHasVersionConflict] = useState(false);
  const [pendingConflictReload, setPendingConflictReload] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [availablePages, setAvailablePages] = useState<number[]>([1]);
  const [focusRequest, setFocusRequest] = useState<{
    type: "first-unresolved" | "source-match" | "unread-pages";
    key: number;
  } | null>(null);
  const [pendingMutation, setPendingMutation] = useState<
    | { kind: "patch"; payload: DraftPatchPayload; key: string }
    | { kind: "confirm"; payload: ConfirmPayload; key: string }
    | null
  >(null);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      operationGenerationRef.current += 1;
      operationLockRef.current = false;
      draftReloadGenerationRef.current += 1;
      draftReloadLockRef.current = false;
      const pendingDelay = operationDelayRef.current;
      if (pendingDelay) {
        clearTimeout(pendingDelay.timer);
        operationDelayRef.current = null;
        pendingDelay.resolve(false);
      }
    };
  }, []);

  useEffect(() => {
    const generation = ++generationRef.current;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let inFlight = false;
    let retryCount = 0;
    let rerunImmediately = false;
    let refreshAllowed = true;

    const current = () => generationRef.current === generation;
    const clearTimer = () => {
      if (timer) clearTimeout(timer);
      timer = undefined;
    };
    const schedule = (delay: number) => {
      if (!current() || document.visibilityState === "hidden") return;
      clearTimer();
      timer = setTimeout(() => void load(), delay);
    };
    const load = async () => {
      if (!current()) return;
      if (inFlight) {
        rerunImmediately = true;
        return;
      }
      inFlight = true;
      clearTimer();
      try {
        const nextJob = await getInsuranceImport(jobId);
        if (!current()) return;
        if (nextJob.customer_id !== customerId) {
          refreshAllowed = false;
          setCustomerMismatch(true);
          return;
        }
        retryCount = 0;
        setLoadError(null);
        setJob(nextJob);
        if (nextJob.status === "review_required") {
          refreshAllowed = false;
          try {
            const nextDraft = await getInsuranceImportDraft(jobId);
            if (!current()) return;
            if (nextDraft.customer_id !== customerId || nextDraft.job_id !== jobId) {
              setCustomerMismatch(true);
              return;
            }
            setDraft(nextDraft);
          } catch (error) {
            if (!current()) return;
            if (error instanceof ApiError && error.status === 409 && error.code === "DRAFT_NOT_READY") {
              rerunImmediately = true;
              return;
            }
            throw error;
          }
          return;
        }
        setDraft(null);
        refreshAllowed = PROCESSING_STATUSES.has(nextJob.status);
        if (refreshAllowed) schedule(8_000);
      } catch (error) {
        if (!current()) return;
        if (error instanceof ApiError && error.status === 404) {
          refreshAllowed = false;
          setLoadError("not_found");
          return;
        }
        if (error instanceof ApiError && error.status < 500 && error.status !== 429) {
          refreshAllowed = false;
          setLoadError("other");
          return;
        }
        if (retryCount < NETWORK_RETRY_DELAYS.length) {
          schedule(NETWORK_RETRY_DELAYS[retryCount]);
          retryCount += 1;
        } else {
          setLoadError("network");
        }
      } finally {
        inFlight = false;
        if (current() && rerunImmediately) {
          rerunImmediately = false;
          void load();
        }
      }
    };

    const refreshNow = () => {
      if (!refreshAllowed) return;
      if (document.visibilityState === "hidden") {
        clearTimer();
        return;
      }
      clearTimer();
      void load();
    };
    const onVisibilityChange = () => refreshNow();

    void load();
    document.addEventListener("visibilitychange", onVisibilityChange);
    window.addEventListener("focus", refreshNow);
    return () => {
      generationRef.current += 1;
      clearTimer();
      document.removeEventListener("visibilitychange", onVisibilityChange);
      window.removeEventListener("focus", refreshNow);
    };
  }, [customerId, jobId, retryNonce]);

  const resetSourceConfirmations = () => {
    setPlannerConfirmedSourceMatch(false);
    setPlannerConfirmedUnreadPages(false);
  };

  const loadLatestDraft = async (
    message?: string,
    options: { conflictRecovery?: boolean } = {}
  ): Promise<boolean> => {
    const reloadGeneration = ++draftReloadGenerationRef.current;
    const current = () =>
      mountedRef.current && draftReloadGenerationRef.current === reloadGeneration;
    try {
      const latest = await getInsuranceImportDraft(jobId);
      if (!current()) return false;
      if (latest.customer_id !== customerId || latest.job_id !== jobId) {
        setCustomerMismatch(true);
        return false;
      }
      setDraft(latest);
      resetSourceConfirmations();
      setHasVersionConflict(false);
      setPendingConflictReload(false);
      setPendingMutation(null);
      if (message) setNotice(message);
      return true;
    } catch {
      if (!current()) return false;
      if (options.conflictRecovery) {
        setHasVersionConflict(true);
        setPendingConflictReload(true);
      }
      setNotice("최신 내용을 불러오지 못했어요. 다시 불러오면 이어서 확인할 수 있어요.");
      return false;
    }
  };

  const reloadLatestAfterConflict = async () => {
    if (draftReloadLockRef.current) return;
    draftReloadLockRef.current = true;
    setIsReloadingLatest(true);
    try {
      await loadLatestDraft(
        "다른 화면에서 바뀐 최신 내용을 불러왔어요.",
        { conflictRecovery: true }
      );
    } finally {
      if (mountedRef.current) {
        draftReloadLockRef.current = false;
        setIsReloadingLatest(false);
      }
    }
  };

  const requestFocus = (type: "first-unresolved" | "source-match" | "unread-pages") => {
    setFocusRequest({ type, key: Date.now() + Math.random() });
  };

  const operationIsCurrent = (context: OperationContext) =>
    mountedRef.current && operationGenerationRef.current === context.generation;

  const beginOperation = (): OperationContext | null => {
    if (operationLockRef.current) return null;
    operationLockRef.current = true;
    const context = { generation: ++operationGenerationRef.current };
    setIsSaving(true);
    setNotice(null);
    return context;
  };

  const finishOperation = (context: OperationContext) => {
    if (!operationIsCurrent(context)) return;
    operationLockRef.current = false;
    setIsSaving(false);
  };

  const waitForOperationRetry = (context: OperationContext) =>
    new Promise<boolean>((resolve) => {
      if (!operationIsCurrent(context)) {
        resolve(false);
        return;
      }
      const timer = setTimeout(() => {
        if (operationDelayRef.current?.timer === timer) operationDelayRef.current = null;
        resolve(operationIsCurrent(context));
      }, 1_000);
      operationDelayRef.current = { timer, resolve };
    });

  const handleOperationError = async (
    error: unknown,
    fallbackMessage: string
  ) => {
    if (!(error instanceof ApiError) || error.status !== 409) {
      setNotice(fallbackMessage);
      return;
    }
    if (error.code === "DRAFT_VERSION_CHANGED") {
      setHasVersionConflict(true);
      setPendingConflictReload(true);
      setPendingMutation(null);
      await loadLatestDraft(
        "다른 화면에서 내용이 바뀌었어요. 최신 내용을 불러왔습니다.",
        { conflictRecovery: true }
      );
      return;
    }
    if (error.code === "DRAFT_UNRESOLVED") {
      const unresolved = error.data?.unresolved_count;
      const suffix = typeof unresolved === "number" ? ` 현재 ${unresolved}개예요.` : "";
      const loaded = await loadLatestDraft(`확인이 필요한 항목을 다시 불러왔어요.${suffix}`);
      if (loaded) requestFocus("first-unresolved");
      return;
    }
    if (error.code === "SOURCE_CONFIRMATION_REQUIRED") {
      setNotice("증권 원문과 같은지 확인해 주세요.");
      requestFocus("source-match");
      return;
    }
    if (error.code === "UNREAD_SOURCE_PAGES_CONFIRMATION_REQUIRED") {
      setNotice("읽기 어려운 페이지를 원문에서 확인해 주세요.");
      requestFocus("unread-pages");
      return;
    }
    if (error.code === "DRAFT_NOT_READY" || error.code === "IMPORT_STATE_CHANGED") {
      setRetryNonce((value) => value + 1);
      return;
    }
    if (error.code === "IMPORT_TARGET_CHANGED") {
      router.push(`/customer/${customerId}?tab=analysis`);
      return;
    }
    if (error.code === "NORMALIZATION_VERSION_UNAVAILABLE") {
      setNotice("새 증권으로 다시 등록하면 최신 기준으로 확인할 수 있어요.");
      return;
    }
    if (error.code === "IDEMPOTENCY_KEY_REUSED") {
      await loadLatestDraft("최신 내용을 다시 불러왔어요. 저장할 내용을 다시 확인해 주세요.");
      return;
    }
    setNotice(fallbackMessage);
  };

  const runPatch = async (
    payload: DraftPatchPayload,
    key: string,
    context: OperationContext,
    commandRetryCount = 0
  ): Promise<InsuranceImportDraft | null> => {
    if (!operationIsCurrent(context)) return null;
    try {
      const nextDraft = await patchInsuranceImportDraft(jobId, payload, key);
      if (!operationIsCurrent(context)) return null;
      if (nextDraft.customer_id !== customerId || nextDraft.job_id !== jobId) {
        setCustomerMismatch(true);
        return null;
      }
      setDraft(nextDraft);
      resetSourceConfirmations();
      setHasVersionConflict(false);
      setPendingConflictReload(false);
      setPendingMutation(null);
      setNotice("저장한 내용을 반영했어요.");
      return nextDraft;
    } catch (error) {
      if (!operationIsCurrent(context)) return null;
      if (error instanceof ApiError && error.status === 409 && error.code === "COMMAND_IN_PROGRESS") {
        if (commandRetryCount < MAX_COMMAND_RETRIES) {
          const active = await waitForOperationRetry(context);
          if (!active) return null;
          return runPatch(payload, key, context, commandRetryCount + 1);
        }
        setPendingMutation({ kind: "patch", payload, key });
        setNotice("같은 내용을 처리하고 있어요. 잠시 후 다시 저장해 주세요.");
        return null;
      }
      if (!(error instanceof ApiError) || error.status === 429 || error.status >= 500) {
        setPendingMutation({ kind: "patch", payload, key });
      }
      await handleOperationError(error, "수정 내용을 저장하지 못했어요. 다시 저장하면 이어서 확인할 수 있어요.");
      return null;
    }
  };

  const handleSave = async (payload: DraftPatchPayload): Promise<InsuranceImportDraft | null> => {
    const context = beginOperation();
    if (!context) return null;
    try {
      return await runPatch(payload, createIdempotencyKey(), context);
    } finally {
      finishOperation(context);
    }
  };

  const runConfirm = async (
    payload: ConfirmPayload,
    key: string,
    context: OperationContext,
    commandRetryCount = 0
  ): Promise<boolean> => {
    if (!operationIsCurrent(context)) return false;
    try {
      const response = await confirmInsuranceImport(jobId, payload, key);
      if (!operationIsCurrent(context)) return false;
      if (response.status !== "confirmed") throw new Error("unexpected confirmation state");
      setPendingMutation(null);
      router.push(`/customer/${customerId}?tab=analysis`);
      return true;
    } catch (error) {
      if (!operationIsCurrent(context)) return false;
      if (error instanceof ApiError && error.status === 409 && error.code === "COMMAND_IN_PROGRESS") {
        if (commandRetryCount < MAX_COMMAND_RETRIES) {
          const active = await waitForOperationRetry(context);
          if (!active) return false;
          return runConfirm(payload, key, context, commandRetryCount + 1);
        }
        setPendingMutation({ kind: "confirm", payload, key });
        setNotice("같은 내용을 처리하고 있어요. 잠시 후 다시 시도해 주세요.");
        return false;
      }
      if (!(error instanceof ApiError) || error.status === 429 || error.status >= 500) {
        setPendingMutation({ kind: "confirm", payload, key });
      }
      await handleOperationError(error, "검토 내용을 반영하지 못했어요. 다시 시도하면 이어서 확인할 수 있어요.");
      return false;
    }
  };

  const handleConfirm = async () => {
    if (!draft) return;
    const context = beginOperation();
    if (!context) return;
    const payload: ConfirmPayload = {
      draft_version: draft.draft_version,
      planner_confirmed_source_match: true,
    };
    if (draft.target_insurance_id !== null) payload.target_insurance_version = draft.target_insurance_version;
    if (draft.confirmation_requirements.planner_confirmed_unread_pages.required) {
      payload.planner_confirmed_unread_pages = true;
    }
    try {
      await runConfirm(payload, createIdempotencyKey(), context);
    } finally {
      finishOperation(context);
    }
  };

  const retryPendingMutation = async () => {
    if (!pendingMutation) return;
    const context = beginOperation();
    if (!context) return;
    const mutation = pendingMutation;
    try {
      if (mutation.kind === "patch") await runPatch(mutation.payload, mutation.key, context);
      else await runConfirm(mutation.payload, mutation.key, context);
    } finally {
      finishOperation(context);
    }
  };

  if (customerMismatch) {
    return (
      <div role="alert">
        <p>현재 고객의 증권 작업을 다시 선택해 주세요.</p>
        <Link href="/customers">고객 목록으로 이동</Link>
      </div>
    );
  }
  if (loadError) {
    const notFound = loadError === "not_found";
    return (
      <div role="alert">
        <p>{notFound ? "증권 확인 작업을 찾지 못했어요." : "증권 확인 작업을 불러오지 못했어요."}</p>
        {notFound ? (
          <Link href="/customers">고객 목록으로 이동</Link>
        ) : (
          <button type="button" onClick={() => setRetryNonce((value) => value + 1)}>다시 불러오기</button>
        )}
      </div>
    );
  }
  if (draft) {
    return (
      <section aria-labelledby="insurance-review-heading">
        <div className="mb-5">
          <h1 id="insurance-review-heading" className="text-2xl font-black text-ink">증권 원문과 초안 확인</h1>
          <p className="mt-2 text-sm leading-6 text-ink2">원문을 보며 정리된 내용을 하나씩 확인해 주세요.</p>
        </div>
        {notice && <div role="status" aria-live="polite" className="mb-4 rounded-xl border border-line bg-surface2 px-4 py-3 text-sm text-ink2">{notice}</div>}
        {pendingConflictReload && <button type="button" disabled={isSaving || isReloadingLatest} className="mb-4 rounded-lg border border-brand px-3 py-2 text-sm font-semibold text-brand disabled:opacity-40" onClick={() => void reloadLatestAfterConflict()}>최신 내용 다시 불러오기</button>}
        {pendingMutation && <button type="button" disabled={isSaving} className="mb-4 rounded-lg border border-brand px-3 py-2 text-sm font-semibold text-brand" onClick={() => void retryPendingMutation()}>같은 내용 다시 저장</button>}
        <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(440px,1fr)]">
          <InsuranceSourceViewer customerId={customerId} jobId={jobId} pageCount={job?.page_count ?? null} currentPage={currentPage} availablePages={availablePages} onPageChange={setCurrentPage} />
          <InsuranceDraftEditor
            customerId={customerId}
            draft={draft}
            isSaving={isSaving}
            hasVersionConflict={hasVersionConflict}
            plannerConfirmedSourceMatch={plannerConfirmedSourceMatch}
            plannerConfirmedUnreadPages={plannerConfirmedUnreadPages}
            onSourceMatchChange={setPlannerConfirmedSourceMatch}
            onUnreadPagesChange={setPlannerConfirmedUnreadPages}
            onSave={handleSave}
            onConfirm={handleConfirm}
            onViewEvidence={(pages) => {
              const valid = pages.filter((page) => page >= 1 && (job?.page_count === null || job?.page_count === undefined || page <= job.page_count));
              const nextPages = valid.length > 0 ? Array.from(new Set(valid)) : [1];
              setAvailablePages(nextPages);
              setCurrentPage(nextPages[0]);
            }}
            focusRequest={focusRequest}
          />
        </div>
      </section>
    );
  }
  if (job && ["failed", "canceled", "confirmed", "superseded"].includes(job.status)) {
    const role = job.status === "failed" ? "alert" : "status";
    return (
      <div role={role} aria-live={role === "status" ? "polite" : undefined}>
        <p>{IMPORT_STATUS_COPY[job.status]}</p>
        <Link href={`/customer/${customerId}?tab=analysis`}>고객 분석으로 이동</Link>
      </div>
    );
  }
  return (
    <div role="status" aria-live="polite">
      {job ? IMPORT_STATUS_COPY[job.status] : "증권 확인 작업을 불러오고 있어요"}
    </div>
  );
}
