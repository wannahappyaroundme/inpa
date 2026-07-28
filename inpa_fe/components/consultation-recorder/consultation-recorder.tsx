"use client";

import { useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type Ref,
} from "react";

import {
  ApiError,
  createConsentRequest,
  getRecordingCapability,
  listConsultationRecordings,
  type ConsultationRecording,
  type PaginatedResult,
  type RecordingCapability,
} from "@/lib/api";

import { ConsentQr } from "./consent-qr";
import { RecordingCard } from "./recording-card";
import { RecordingNotice } from "./recording-notice";
import { useOptionalRecorderContext } from "./recorder-provider";

function RecordingNoticeWithMemoRoute({
  customerId,
  noticeText,
  checked,
  onCheckedChange,
  onBeforeMemo,
  onStart,
  startBlocked,
  checkboxRef,
}: {
  customerId: number;
  noticeText: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  onBeforeMemo: () => void;
  onStart: () => void;
  startBlocked: boolean;
  checkboxRef: Ref<HTMLInputElement>;
}) {
  const router = useRouter();
  return (
    <RecordingNotice
      noticeText={noticeText}
      checked={checked}
      onCheckedChange={onCheckedChange}
      onDecline={() => {
        onBeforeMemo();
        router.push(
          `/customer/${customerId}?tab=history&view=memos#customer-history-panel-memos`,
        );
      }}
      onStart={onStart}
      startBlocked={startBlocked}
      checkboxRef={checkboxRef}
    />
  );
}

function messageFrom(error: unknown, fallback: string): string {
  return error instanceof ApiError && error.message ? error.message : fallback;
}

function elapsedLabel(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

const DIALOG_FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
  "[contenteditable='true']",
].join(",");

export function ConsultationRecorder({ customerId }: { customerId: number }) {
  const session = useOptionalRecorderContext();
  const hasSession = Boolean(session);
  const [capability, setCapability] = useState<RecordingCapability | null>(null);
  const [loading, setLoading] = useState(hasSession);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [consentUrl, setConsentUrl] = useState<string | null>(null);
  const [consentBusy, setConsentBusy] = useState(false);
  const [consentMessage, setConsentMessage] = useState<string | null>(null);
  const [noticeAttested, setNoticeAttested] = useState(false);
  const [noticeRefreshState, setNoticeRefreshState] = useState<
    "idle" | "loading" | "error" | "ready"
  >("idle");
  const triggerButtonRef = useRef<HTMLButtonElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const noticeCheckboxRef = useRef<HTMLInputElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const capabilityRequestRef = useRef(0);
  const capabilityIdentityRef = useRef<string | null>(null);
  const startAbortRef = useRef<AbortController | null>(null);
  const noticeRefreshHandledRef = useRef(false);

  const loadCapability = useCallback(async (resetAttestation = false) => {
    if (!hasSession) return null;
    const requestId = ++capabilityRequestRef.current;
    if (resetAttestation) setNoticeAttested(false);
    setLoading(true);
    setLoadError(null);
    try {
      const result = await getRecordingCapability(customerId);
      if (requestId !== capabilityRequestRef.current) return null;
      const identity = `${customerId}:${result.planner_notice_version}`;
      if (capabilityIdentityRef.current !== identity) {
        setNoticeAttested(false);
      }
      capabilityIdentityRef.current = identity;
      setCapability(result);
      return true;
    } catch (error) {
      if (requestId !== capabilityRequestRef.current) return null;
      setLoadError(messageFrom(error, "녹음 연결을 다시 확인해 주세요."));
      return false;
    } finally {
      if (requestId === capabilityRequestRef.current) {
        setLoading(false);
      }
    }
  }, [customerId, hasSession]);

  const refreshLatestNotice = useCallback(async () => {
    setNoticeRefreshState("loading");
    setCapability(null);
    capabilityIdentityRef.current = null;
    setNoticeAttested(false);
    const success = await loadCapability(true);
    if (success === null) return false;
    setNoticeRefreshState(success ? "ready" : "error");
    return success;
  }, [loadCapability]);

  useEffect(() => {
    noticeRefreshHandledRef.current = false;
    setCapability(null);
    setNoticeRefreshState("idle");
    setNoticeAttested(false);
    setConsentUrl(null);
    setConsentMessage(null);
    startAbortRef.current?.abort();
    startAbortRef.current = null;
    void loadCapability();
    return () => {
      capabilityRequestRef.current += 1;
      startAbortRef.current?.abort();
      startAbortRef.current = null;
    };
  }, [loadCapability]);

  const closeDialog = useCallback(() => {
    const focusTarget = restoreFocusRef.current ?? triggerButtonRef.current;
    startAbortRef.current?.abort();
    startAbortRef.current = null;
    setNoticeAttested(false);
    setOpen(false);
    requestAnimationFrame(() => {
      focusTarget?.focus();
      restoreFocusRef.current = null;
    });
  }, []);

  useEffect(() => {
    if (!open) return;
    const dialog = dialogRef.current;
    const overlay = overlayRef.current;
    if (!dialog || !overlay) return;
    const previousBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const backgroundState = new Map<
      HTMLElement,
      { inert: string | null; ariaHidden: string | null }
    >();
    let current: HTMLElement | null = overlay;
    while (current && current !== document.body) {
      const parent: HTMLElement | null = current.parentElement;
      if (!parent) break;
      for (const sibling of Array.from(parent.children)) {
        if (sibling === current || !(sibling instanceof HTMLElement)) continue;
        if (!backgroundState.has(sibling)) {
          backgroundState.set(sibling, {
            inert: sibling.getAttribute("inert"),
            ariaHidden: sibling.getAttribute("aria-hidden"),
          });
        }
        sibling.setAttribute("inert", "");
        sibling.setAttribute("aria-hidden", "true");
      }
      current = parent;
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeDialog();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(
        dialog.querySelectorAll<HTMLElement>(DIALOG_FOCUSABLE_SELECTOR),
      );
      const first = focusable[0];
      const last = focusable.at(-1);
      if (!first || !last) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const active = document.activeElement;
      if (event.shiftKey && (active === first || !dialog.contains(active))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (active === last || !dialog.contains(active))) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown, true);
    const focusFrame = requestAnimationFrame(() => closeButtonRef.current?.focus());
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      cancelAnimationFrame(focusFrame);
      document.body.style.overflow = previousBodyOverflow;
      for (const [element, state] of backgroundState) {
        if (state.inert === null) element.removeAttribute("inert");
        else element.setAttribute("inert", state.inert);
        if (state.ariaHidden === null) element.removeAttribute("aria-hidden");
        else element.setAttribute("aria-hidden", state.ariaHidden);
      }
    };
  }, [closeDialog, open]);

  useEffect(() => {
    if (session?.state.kind === "ready") {
      setNoticeAttested(false);
    }
  }, [session?.state.kind]);

  useEffect(() => {
    const noticeChangedForCustomer = (
      session?.customerId === customerId
      && session.state.errorCode === "recording_notice_changed"
    );
    if (!noticeChangedForCustomer) {
      noticeRefreshHandledRef.current = false;
      setNoticeRefreshState("idle");
      return;
    }
    if (noticeRefreshHandledRef.current) return;
    noticeRefreshHandledRef.current = true;
    startAbortRef.current?.abort();
    startAbortRef.current = null;
    void refreshLatestNotice();
  }, [
    customerId,
    refreshLatestNotice,
    session?.customerId,
    session?.state.errorCode,
  ]);

  useEffect(() => {
    if (
      noticeRefreshState !== "ready"
      || !capability
      || capabilityIdentityRef.current
        !== `${customerId}:${capability.planner_notice_version}`
    ) {
      return;
    }
    const frame = requestAnimationFrame(() => noticeCheckboxRef.current?.focus());
    return () => cancelAnimationFrame(frame);
  }, [capability, customerId, noticeRefreshState]);

  if (!session) return null;
  const recorderSession = session;
  const noticeChanged = (
    session.customerId === customerId
    && session.state.errorCode === "recording_notice_changed"
  );
  const visibleCapability = (
    noticeChanged && noticeRefreshState !== "ready"
      ? null
      : capability
  );
  const latestNoticeLoading = noticeChanged
    && ["idle", "loading"].includes(noticeRefreshState);
  if ((loading || latestNoticeLoading) && !visibleCapability) {
    return (
      <span
        aria-label={noticeChanged
          ? "최신 녹음 안내 확인 중"
          : "상담 녹음 연결 확인 중"}
        className="h-11 w-24 animate-pulse rounded-xl bg-surface2"
      />
    );
  }
  if (
    !visibleCapability
    && (loadError || (noticeChanged && noticeRefreshState === "error"))
  ) {
    return (
      <button
        type="button"
        onClick={() => {
          if (noticeChanged) {
            void refreshLatestNotice();
          } else {
            void loadCapability();
          }
        }}
        className="min-h-11 rounded-xl border border-line bg-surface px-3 text-[13px] font-bold text-brand"
      >
        {noticeChanged ? "최신 안내 다시 불러오기" : "녹음 연결 다시 확인"}
      </button>
    );
  }
  if (!visibleCapability?.recording_enabled) return null;
  const currentCapability = visibleCapability;

  async function copyConsentLink() {
    if (consentBusy) return;
    setConsentBusy(true);
    setConsentMessage(null);
    try {
      const result = consentUrl
        ? { consent_url: consentUrl }
        : await createConsentRequest(customerId, [
          "consultation_recording",
          "consultation_sensitive",
        ]);
      setConsentUrl(result.consent_url);
      await navigator.clipboard.writeText(result.consent_url);
      setConsentMessage("동의 링크를 복사했어요. 고객에게 전달해 주세요.");
    } catch (error) {
      setConsentMessage(messageFrom(error, "링크를 다시 만들면 바로 전달할 수 있어요."));
    } finally {
      setConsentBusy(false);
    }
  }

  const belongsToCustomer = session.customerId === customerId;
  const activeForAnotherCustomer = session.isActive && !belongsToCustomer;

  function startRecording() {
    if (
      !currentCapability
      || !noticeAttested
      || !currentCapability.recording_enabled
      || !currentCapability.consent_ready
      || activeForAnotherCustomer
      || capabilityIdentityRef.current
        !== `${customerId}:${currentCapability.planner_notice_version}`
    ) {
      return;
    }
    startAbortRef.current?.abort();
    const controller = new AbortController();
    startAbortRef.current = controller;
    void recorderSession.start(customerId, {
      noticeVersion: currentCapability.planner_notice_version,
      retentionDays: currentCapability.retention_days,
      signal: controller.signal,
    }).finally(() => {
      if (startAbortRef.current === controller) {
        startAbortRef.current = null;
      }
    });
  }

  function prepareMemoNavigation() {
    closeDialog();
  }

  return (
    <>
      <button
        ref={triggerButtonRef}
        type="button"
        onClick={(event) => {
          restoreFocusRef.current = event.currentTarget;
          setOpen(true);
        }}
        className="min-h-11 rounded-xl bg-brand px-4 text-[14px] font-bold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
      >
        상담 녹음
      </button>

      {open && (
        <div
          ref={overlayRef}
          className="fixed inset-0 z-[90] grid place-items-end bg-black/35 p-0 sm:place-items-center sm:p-5"
          onMouseDown={(event) => {
            if (event.currentTarget === event.target) closeDialog();
          }}
        >
          <section
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="consultation-recording-title"
            tabIndex={-1}
            className="max-h-[92dvh] w-full overflow-y-auto rounded-t-3xl bg-surface p-5 shadow-2xl sm:max-w-lg sm:rounded-3xl sm:p-6"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 id="consultation-recording-title" className="text-[20px] font-extrabold text-ink">
                  상담 녹음
                </h2>
                <p className="mt-1 text-[13px] text-ink3">
                  상담 내용을 놓치지 않고 메모로 이어가세요.
                </p>
              </div>
              <button
                ref={closeButtonRef}
                type="button"
                aria-label="상담 녹음 창 닫기"
                onClick={closeDialog}
                className="min-h-11 min-w-11 rounded-xl text-[20px] text-ink3"
              >
                ×
              </button>
            </div>

            <div className="mt-5 rounded-2xl bg-brand-soft p-4">
              <p className="text-[13px] font-bold text-ink">원본은 짧게, 메모는 계속</p>
              <p className="mt-2 text-[13px] leading-6 text-ink2">
                원본 녹음은 인파에서 최대 {currentCapability.retention_days}일 보관한 뒤 자동 삭제됩니다.
              </p>
              <p className="mt-1 text-[13px] leading-6 text-ink2">
                녹음 파일 하나당 AI 요약은 한 번만 만들 수 있고, 이후에는 메모를 직접 수정할 수 있어요.
              </p>
            </div>

            {!currentCapability.consent_ready ? (
              <div className="mt-5">
                <h3 className="text-[15px] font-extrabold text-ink">고객 동의를 먼저 받아주세요</h3>
                <p className="mt-2 text-[13px] leading-6 text-ink3">
                  링크를 보내거나 QR로 열어 고객이 직접 동의하면 바로 녹음을 시작할 수 있어요.
                </p>
                <div className="mt-4 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => void copyConsentLink()}
                    disabled={consentBusy}
                    className="min-h-11 rounded-xl bg-brand px-4 text-[13px] font-bold text-white disabled:opacity-60"
                  >
                    {consentBusy ? "동의 링크 만드는 중" : "동의 링크 복사"}
                  </button>
                  <button
                    type="button"
                    onClick={() => void loadCapability()}
                    disabled={loading}
                    className="min-h-11 rounded-xl border border-line px-4 text-[13px] font-bold text-brand disabled:opacity-60"
                  >
                    {loading ? "동의 확인 중" : "동의 완료 다시 확인"}
                  </button>
                </div>
                {consentMessage && (
                  <p aria-live="polite" className="mt-3 text-[12px] text-ink2">{consentMessage}</p>
                )}
                {consentUrl && (
                  <div className="mt-4 flex flex-col gap-3 rounded-2xl bg-surface2 p-4 sm:flex-row sm:items-center">
                    <ConsentQr url={consentUrl} />
                    <p className="break-all text-[12px] leading-5 text-ink3">{consentUrl}</p>
                  </div>
                )}
              </div>
            ) : (
              <div className="mt-5">
                {activeForAnotherCustomer ? (
                  <p className="rounded-2xl bg-surface2 p-4 text-[13px] leading-6 text-ink2">
                    진행 중인 고객 녹음을 마치면 이 고객의 녹음을 시작할 수 있어요.
                  </p>
                ) : (
                  <>
                    {belongsToCustomer && session.isActive ? (
                      <div className="mt-4 rounded-2xl bg-surface2 p-4">
                        <p className="text-[15px] font-extrabold text-ink">
                          {elapsedLabel(session.state.elapsedSeconds)}
                        </p>
                        <p aria-live="polite" className="mt-1 text-[13px] text-ink3">
                          {session.state.notice}
                        </p>
                        <div className="mt-4 flex flex-wrap gap-2">
                          {session.state.kind === "recording" && (
                            <button type="button" onClick={session.pause} className="min-h-11 rounded-xl border border-line px-4 text-[13px] font-bold text-ink2">
                              잠시 멈춤
                            </button>
                          )}
                          {session.state.kind === "paused" && (
                            <button type="button" onClick={session.resume} className="min-h-11 rounded-xl border border-line px-4 text-[13px] font-bold text-brand">
                              이어서 녹음
                            </button>
                          )}
                          {["recording", "paused", "interrupted"].includes(session.state.kind) && (
                            <button type="button" onClick={session.stop} className="min-h-11 rounded-xl bg-brand px-4 text-[13px] font-bold text-white">
                              녹음 마치기
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={() => {
                              startAbortRef.current?.abort();
                              startAbortRef.current = null;
                              setNoticeAttested(false);
                              void session.discard();
                            }}
                            className="min-h-11 rounded-xl px-3 text-[13px] font-bold text-danger-ink"
                          >
                            이번 녹음 지우기
                          </button>
                        </div>
                      </div>
                    ) : belongsToCustomer && session.state.kind === "ready" ? (
                      <div className="rounded-2xl bg-success-tint p-4">
                        <p className="text-[13px] font-bold text-ink">녹음을 저장했어요.</p>
                        <button
                          type="button"
                          onClick={() => {
                            session.reset();
                            closeDialog();
                          }}
                          className="mt-3 min-h-11 rounded-xl bg-brand px-4 text-[13px] font-bold text-white"
                        >
                          상담 기록 확인
                        </button>
                      </div>
                    ) : (
                      <>
                        <p className="mb-4 text-[13px] leading-6 text-ink3">
                          고지를 확인한 뒤 마이크 사용을 연결합니다. 한 번에 최대 60분까지 녹음돼요.
                        </p>
                        <RecordingNoticeWithMemoRoute
                          customerId={customerId}
                          noticeText={currentCapability.planner_notice_text}
                          checked={noticeAttested}
                          onCheckedChange={setNoticeAttested}
                          onBeforeMemo={prepareMemoNavigation}
                          onStart={startRecording}
                          checkboxRef={noticeCheckboxRef}
                          startBlocked={
                            loading
                            || !currentCapability.recording_enabled
                            || !currentCapability.consent_ready
                          }
                        />
                      </>
                    )}
                  </>
                )}
                {belongsToCustomer && session.state.error && (
                  <p role="alert" className="mt-3 rounded-xl bg-danger-tint px-3 py-2 text-[13px] text-danger-ink">
                    {session.state.error}
                  </p>
                )}
              </div>
            )}
          </section>
        </div>
      )}
    </>
  );
}

export function ConsultationRecordingList({
  customerId,
  onSummaryReady = () => undefined,
}: {
  customerId: number;
  onSummaryReady?: () => void;
}) {
  const session = useOptionalRecorderContext();
  const hasSession = Boolean(session);
  const [data, setData] = useState<PaginatedResult<ConsultationRecording> | null>(null);
  const [capability, setCapability] = useState<RecordingCapability | null>(null);
  const [capabilityLoading, setCapabilityLoading] = useState(hasSession);
  const [capabilityError, setCapabilityError] = useState(false);
  const [loading, setLoading] = useState(hasSession);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summaryConsentBusy, setSummaryConsentBusy] = useState(false);
  const [summaryConsentMessage, setSummaryConsentMessage] = useState<string | null>(null);
  const generationRef = useRef(0);
  const capabilityGenerationRef = useRef(0);

  const load = useCallback(async (page: number, append = false) => {
    if (!hasSession) return;
    const generation = ++generationRef.current;
    if (append) setLoadingMore(true);
    else setLoading(true);
    setError(null);
    try {
      const result = await listConsultationRecordings(customerId, page);
      if (generation !== generationRef.current) return;
      setData((current) => (
        append && current
          ? {
            ...result,
            results: [
              ...current.results,
              ...result.results.filter((row) => (
                !current.results.some((known) => known.id === row.id)
              )),
            ],
          }
          : result
      ));
    } catch (loadError) {
      if (generation !== generationRef.current) return;
      setError(messageFrom(loadError, "녹음 목록을 다시 불러와 주세요."));
    } finally {
      if (generation === generationRef.current) {
        setLoading(false);
        setLoadingMore(false);
      }
    }
  }, [customerId, hasSession]);

  useEffect(() => {
    void load(1);
    return () => {
      generationRef.current += 1;
    };
  }, [load]);

  const loadSummaryCapability = useCallback(async () => {
    if (!hasSession) return;
    const generation = ++capabilityGenerationRef.current;
    setCapabilityLoading(true);
    setCapabilityError(false);
    try {
      const result = await getRecordingCapability(customerId);
      if (generation !== capabilityGenerationRef.current) return;
      setCapability(result);
    } catch {
      if (generation !== capabilityGenerationRef.current) return;
      setCapability(null);
      setCapabilityError(true);
    } finally {
      if (generation === capabilityGenerationRef.current) {
        setCapabilityLoading(false);
      }
    }
  }, [customerId, hasSession]);

  useEffect(() => {
    void loadSummaryCapability();
    return () => {
      capabilityGenerationRef.current += 1;
    };
  }, [loadSummaryCapability]);

  useEffect(() => {
    if (
      session?.customerId === customerId
      && session.state.kind === "ready"
      && session.state.recording
    ) {
      setData((current) => current ? {
        ...current,
        count: current.results.some((row) => row.id === session.state.recording?.id)
          ? current.count
          : current.count + 1,
        results: [
          session.state.recording as ConsultationRecording,
          ...current.results.filter((row) => row.id !== session.state.recording?.id),
        ],
      } : current);
    }
  }, [customerId, session?.customerId, session?.state.kind, session?.state.recording]);

  if (!session) return null;
  if (loading && !data) {
    return (
      <div className="mt-5 space-y-2" aria-label="상담 녹음 목록을 불러오는 중">
        <div className="h-24 animate-pulse rounded-2xl bg-surface2" />
      </div>
    );
  }
  if (!data && error) {
    return (
      <div className="mt-5 rounded-2xl bg-surface2 p-4">
        <p role="alert" className="text-[13px] text-ink2">{error}</p>
        <button type="button" onClick={() => void load(1)} className="mt-3 min-h-11 rounded-xl border border-line bg-surface px-3 text-[13px] font-bold text-brand">
          녹음 목록 다시 불러오기
        </button>
      </div>
    );
  }
  if (!data || data.count === 0) {
    return (
      <p className="mt-5 rounded-2xl bg-surface2 px-4 py-3 text-[13px] leading-6 text-ink3">
        녹음을 마치면 이곳에서 원본과 상담 메모를 함께 확인할 수 있어요.
      </p>
    );
  }

  async function copySummaryConsentLink() {
    if (summaryConsentBusy) return;
    setSummaryConsentBusy(true);
    setSummaryConsentMessage(null);
    try {
      const result = await createConsentRequest(customerId, [
        "consultation_recording",
        "consultation_sensitive",
        "consultation_overseas_summary",
      ]);
      await navigator.clipboard.writeText(result.consent_url);
      setSummaryConsentMessage("요약 동의 링크를 복사했어요. 고객에게 전달해 주세요.");
    } catch (copyError) {
      setSummaryConsentMessage(messageFrom(
        copyError,
        "동의 링크를 다시 만들면 바로 전달할 수 있어요.",
      ));
    } finally {
      setSummaryConsentBusy(false);
    }
  }

  return (
    <section className="mt-5 border-t border-line pt-5" aria-label="상담 녹음 목록">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-[15px] font-extrabold text-ink">
          상담 녹음 {data.count.toLocaleString("ko-KR")}개
        </h3>
        {capability ? (
          <span className="text-[12px] text-ink3">
            새 원본은 최대 {capability.retention_days}일 보관
          </span>
        ) : capabilityLoading ? (
          <span role="status" className="text-[12px] text-ink3">
            새 원본 보관 기간 확인 중
          </span>
        ) : capabilityError ? (
          <button
            type="button"
            onClick={() => void loadSummaryCapability()}
            className="min-h-11 rounded-xl border border-line px-3 text-[12px] font-bold text-brand"
          >
            새 원본 보관 기간 다시 확인
          </button>
        ) : (
          <span className="text-[12px] text-ink3">
            새 원본 보관 기간을 확인해 주세요
          </span>
        )}
      </div>
      {capability?.summary_enabled && !capability.summary_consent_ready && (
        <div className="mt-3 rounded-2xl bg-brand-soft p-4">
          <p className="text-[13px] font-bold text-ink">요약 동의를 받으면 핵심 메모를 만들 수 있어요.</p>
          <p className="mt-1 text-[12px] leading-5 text-ink2">
            고객이 링크에서 녹음과 AI 요약 항목을 직접 확인하고 동의합니다.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void copySummaryConsentLink()}
              disabled={summaryConsentBusy}
              className="min-h-11 rounded-xl bg-brand px-3 text-[13px] font-bold text-white disabled:opacity-60"
            >
              {summaryConsentBusy ? "동의 링크 만드는 중" : "요약 동의 링크 복사"}
            </button>
            <button
              type="button"
              onClick={() => void loadSummaryCapability()}
              className="min-h-11 rounded-xl border border-line bg-surface px-3 text-[13px] font-bold text-brand"
            >
              동의 완료 다시 확인
            </button>
          </div>
          {summaryConsentMessage && (
            <p aria-live="polite" className="mt-2 text-[12px] text-ink2">
              {summaryConsentMessage}
            </p>
          )}
        </div>
      )}
      {error && <p role="alert" className="mt-3 text-[12px] text-danger-ink">{error}</p>}
      <div className="mt-3 space-y-3">
        {data.results.map((recording) => (
          <RecordingCard
            key={recording.id}
            customerId={customerId}
            recording={recording}
            summaryEnabled={Boolean(capability?.summary_enabled)}
            summaryConsentReady={Boolean(capability?.summary_consent_ready)}
            onSummaryReady={onSummaryReady}
            onChanged={(changed) => setData((current) => current ? {
              ...current,
              results: current.results.map((row) => (
                row.id === changed.id ? changed : row
              )),
            } : current)}
          />
        ))}
      </div>
      {data.next && (
        <button
          type="button"
          disabled={loadingMore}
          onClick={() => {
            const page = Number(new URL(data.next ?? "", "https://inpa.local").searchParams.get("page") ?? 2);
            void load(page, true);
          }}
          className="mt-3 min-h-11 w-full rounded-xl border border-line text-[13px] font-bold text-brand disabled:opacity-60"
        >
          {loadingMore ? "이전 녹음을 불러오는 중" : "이전 녹음 더 보기"}
        </button>
      )}
    </section>
  );
}
