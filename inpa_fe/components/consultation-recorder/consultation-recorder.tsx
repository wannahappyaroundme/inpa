"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
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
import { useOptionalRecorderContext } from "./recorder-provider";

function messageFrom(error: unknown, fallback: string): string {
  return error instanceof ApiError && error.message ? error.message : fallback;
}

function elapsedLabel(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

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
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  const loadCapability = useCallback(async () => {
    if (!hasSession) return;
    setLoading(true);
    setLoadError(null);
    try {
      setCapability(await getRecordingCapability(customerId));
    } catch (error) {
      setLoadError(messageFrom(error, "녹음 연결을 다시 확인해 주세요."));
    } finally {
      setLoading(false);
    }
  }, [customerId, hasSession]);

  useEffect(() => {
    void loadCapability();
  }, [loadCapability]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", onKeyDown);
    requestAnimationFrame(() => closeButtonRef.current?.focus());
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open]);

  if (!session) return null;
  if (loading && !capability) {
    return (
      <span
        aria-label="상담 녹음 연결 확인 중"
        className="h-11 w-24 animate-pulse rounded-xl bg-surface2"
      />
    );
  }
  if (loadError && !capability) {
    return (
      <button
        type="button"
        onClick={() => void loadCapability()}
        className="min-h-11 rounded-xl border border-line bg-surface px-3 text-[13px] font-bold text-brand"
      >
        녹음 연결 다시 확인
      </button>
    );
  }
  if (!capability?.recording_enabled) return null;

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

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="min-h-11 rounded-xl bg-brand px-4 text-[14px] font-bold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
      >
        상담 녹음
      </button>

      {open && (
        <div
          className="fixed inset-0 z-[90] grid place-items-end bg-black/35 p-0 sm:place-items-center sm:p-5"
          onMouseDown={(event) => {
            if (event.currentTarget === event.target) setOpen(false);
          }}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="consultation-recording-title"
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
                onClick={() => setOpen(false)}
                className="min-h-11 min-w-11 rounded-xl text-[20px] text-ink3"
              >
                ×
              </button>
            </div>

            <div className="mt-5 rounded-2xl bg-brand-soft p-4">
              <p className="text-[13px] font-bold text-ink">원본은 짧게, 메모는 계속</p>
              <p className="mt-2 text-[13px] leading-6 text-ink2">
                원본 녹음은 인파에서 최대 7일 보관한 뒤 자동 삭제됩니다.
              </p>
              <p className="mt-1 text-[13px] leading-6 text-ink2">
                녹음 파일 하나당 AI 요약은 한 번만 만들 수 있고, 이후에는 메모를 직접 수정할 수 있어요.
              </p>
            </div>

            {!capability.consent_ready ? (
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
                    <p className="text-[13px] leading-6 text-ink3">
                      시작 버튼을 누르면 마이크 사용을 확인합니다. 한 번에 최대 60분까지 녹음돼요.
                    </p>
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
                          <button type="button" onClick={() => void session.discard()} className="min-h-11 rounded-xl px-3 text-[13px] font-bold text-danger-ink">
                            이번 녹음 지우기
                          </button>
                        </div>
                      </div>
                    ) : (
                      <button
                        type="button"
                        onClick={() => void session.start(customerId)}
                        className="mt-4 min-h-12 w-full rounded-2xl bg-brand px-4 text-[15px] font-extrabold text-white"
                      >
                        녹음 시작
                      </button>
                    )}
                  </>
                )}
                {belongsToCustomer && session.state.error && (
                  <p role="alert" className="mt-3 rounded-xl bg-danger-tint px-3 py-2 text-[13px] text-danger-ink">
                    {session.state.error}
                  </p>
                )}
                {belongsToCustomer && session.state.kind === "ready" && (
                  <div className="mt-4 rounded-2xl bg-success-tint p-4">
                    <p className="text-[13px] font-bold text-ink">녹음을 저장했어요.</p>
                    <button type="button" onClick={() => { session.reset(); setOpen(false); }} className="mt-3 min-h-11 rounded-xl bg-brand px-4 text-[13px] font-bold text-white">
                      상담 기록 확인
                    </button>
                  </div>
                )}
              </div>
            )}
          </section>
        </div>
      )}
    </>
  );
}

export function ConsultationRecordingList({ customerId }: { customerId: number }) {
  const session = useOptionalRecorderContext();
  const hasSession = Boolean(session);
  const [data, setData] = useState<PaginatedResult<ConsultationRecording> | null>(null);
  const [loading, setLoading] = useState(hasSession);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generationRef = useRef(0);

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
  if (!data || data.count === 0) return null;

  return (
    <section className="mt-5 border-t border-line pt-5" aria-label="상담 녹음 목록">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-[15px] font-extrabold text-ink">
          상담 녹음 {data.count.toLocaleString("ko-KR")}개
        </h3>
        <span className="text-[12px] text-ink3">원본은 최대 7일 보관</span>
      </div>
      {error && <p role="alert" className="mt-3 text-[12px] text-danger-ink">{error}</p>}
      <div className="mt-3 space-y-3">
        {data.results.map((recording) => (
          <RecordingCard
            key={recording.id}
            customerId={customerId}
            recording={recording}
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
