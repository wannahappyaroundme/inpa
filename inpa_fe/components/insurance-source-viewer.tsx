"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";

import { ApiError, getInsuranceImportSourceUrl } from "@/lib/api";

type SourceError = "missing" | "network";

export interface InsuranceSourceViewerProps {
  customerId: number;
  jobId: string;
  pageCount: number | null;
  currentPage: number;
  availablePages: number[];
  onPageChange: (page: number) => void;
}

export function sourceUrlForPage(url: string, page: number): string {
  const base = url.split("#", 1)[0];
  return `${base}#page=${page}&zoom=page-width`;
}

function validPage(page: number, pageCount: number | null): number {
  const maximum = pageCount && pageCount > 0 ? pageCount : 1;
  return Number.isSafeInteger(page) && page >= 1 && page <= maximum ? page : 1;
}

export function InsuranceSourceViewer({
  customerId,
  jobId,
  pageCount,
  currentPage,
  availablePages,
  onPageChange,
}: InsuranceSourceViewerProps) {
  const identity = `${customerId}:${jobId}`;
  return (
    <InsuranceSourceViewerIdentity
      key={identity}
      customerId={customerId}
      jobId={jobId}
      pageCount={pageCount}
      currentPage={currentPage}
      availablePages={availablePages}
      onPageChange={onPageChange}
    />
  );
}

function InsuranceSourceViewerIdentity({
  customerId,
  jobId,
  pageCount,
  currentPage,
  availablePages,
  onPageChange,
}: InsuranceSourceViewerProps) {
  const generationRef = useRef(0);
  const openerRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const desktopSourceRef = useRef<HTMLElement>(null);
  const dialogCloseTargetRef = useRef<"opener" | "desktop">("opener");
  const [sourceUrl, setSourceUrl] = useState<string | null>(null);
  const [sourceError, setSourceError] = useState<SourceError | null>(null);
  const [loading, setLoading] = useState(true);
  const [reloadNonce, setReloadNonce] = useState(0);
  const [dialogOpen, setDialogOpen] = useState(false);
  const page = validPage(currentPage, pageCount);
  const pages = Array.from(new Set(availablePages))
    .filter((candidate) => validPage(candidate, pageCount) === candidate)
    .sort((left, right) => left - right);

  useEffect(() => {
    const generation = ++generationRef.current;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let refreshAt = 0;
    let inFlight = false;
    let hasSource = false;

    const current = () => generationRef.current === generation;
    const clearTimer = () => {
      if (timer) clearTimeout(timer);
      timer = undefined;
    };
    const schedule = () => {
      clearTimer();
      if (!current() || document.visibilityState === "hidden" || refreshAt <= 0) return;
      timer = setTimeout(() => void load(), Math.max(0, refreshAt - Date.now()));
    };
    const load = async () => {
      if (!current() || inFlight) return;
      inFlight = true;
      clearTimer();
      setLoading(true);
      try {
        const response = await getInsuranceImportSourceUrl(jobId);
        if (!current()) return;
        setSourceUrl(response.url);
        hasSource = true;
        setSourceError(null);
        refreshAt = Date.now() + Math.max(0, response.expires_in * 1_000 - 30_000);
        schedule();
      } catch (error) {
        if (!current()) return;
        setSourceUrl(null);
        hasSource = false;
        setSourceError(error instanceof ApiError && error.status === 404 ? "missing" : "network");
      } finally {
        inFlight = false;
        if (current()) setLoading(false);
      }
    };
    const refreshIfNeeded = () => {
      if (document.visibilityState === "hidden") {
        clearTimer();
        return;
      }
      if (!hasSource || Date.now() >= refreshAt) void load();
      else schedule();
    };

    setSourceUrl(null);
    setSourceError(null);
    void load();
    document.addEventListener("visibilitychange", refreshIfNeeded);
    window.addEventListener("focus", refreshIfNeeded);
    return () => {
      generationRef.current += 1;
      clearTimer();
      document.removeEventListener("visibilitychange", refreshIfNeeded);
      window.removeEventListener("focus", refreshIfNeeded);
    };
  }, [jobId, reloadNonce]);

  useEffect(() => {
    if (!dialogOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        dialogCloseTargetRef.current = "opener";
        setDialogOpen(false);
        return;
      }
      if (event.key !== "Tab") return;
      const dialog = closeRef.current?.closest<HTMLElement>("[role='dialog']");
      if (!dialog) return;
      const focusable = Array.from(
        dialog.querySelectorAll<HTMLElement>(
          "button:not([disabled]), a[href], iframe, [tabindex='0']"
        )
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    const desktopQuery = window.matchMedia?.("(min-width: 1024px)");
    const closeOnDesktop = (event: MediaQueryListEvent) => {
      if (event.matches) {
        dialogCloseTargetRef.current = "desktop";
        setDialogOpen(false);
      }
    };
    desktopQuery?.addEventListener("change", closeOnDesktop);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      desktopQuery?.removeEventListener("change", closeOnDesktop);
      document.body.style.overflow = previousOverflow;
      const focusTarget = dialogCloseTargetRef.current === "desktop"
        ? desktopSourceRef.current
        : openerRef.current;
      if (focusTarget?.isConnected) focusTarget.focus();
    };
  }, [dialogOpen]);

  const reload = () => setReloadNonce((value) => value + 1);
  const framedUrl = sourceUrl ? sourceUrlForPage(sourceUrl, page) : null;

  const toolbar = (mobile = false) => (
    <div className="flex flex-wrap items-center gap-2">
      {pages.map((candidate) => (
        <button key={candidate} type="button" aria-pressed={candidate === page} className="rounded-lg border border-line px-2.5 py-1.5 text-xs font-semibold text-ink2" onClick={() => onPageChange(candidate)}>{candidate}페이지</button>
      ))}
      <button type="button" className="rounded-lg border border-line px-2.5 py-1.5 text-xs font-semibold text-ink2" onClick={reload}>원문 다시 불러오기</button>
      {sourceUrl && <a className="rounded-lg border border-line px-2.5 py-1.5 text-xs font-semibold text-brand" href={sourceUrlForPage(sourceUrl, page)} target="_blank" rel="noopener noreferrer">새 화면에서 보기</a>}
      {mobile && <span className="sr-only">모바일 원문 도구</span>}
    </div>
  );

  const content = (mobile = false) => (
    <div className="flex h-full min-h-0 min-w-0 flex-col gap-3 overflow-x-hidden">
      {toolbar(mobile)}
      {loading && !framedUrl && <div role="status" aria-live="polite" className="flex min-h-72 items-center justify-center rounded-xl bg-surface2 text-sm text-ink3">증권 원문을 불러오고 있어요</div>}
      {sourceError === "missing" && <div role="alert" className="rounded-xl border border-line bg-surface2 p-4 text-sm leading-6 text-ink2"><p>같은 증권 파일을 다시 선택하면 이어서 확인할 수 있어요.</p><Link href={`/customer/${customerId}?tab=analysis`} className="font-semibold text-brand">고객 분석으로 이동</Link></div>}
      {sourceError === "network" && <div role="alert" className="rounded-xl border border-line bg-surface2 p-4 text-sm leading-6 text-ink2">원문 연결을 다시 확인해 주세요. 원문 다시 불러오기를 누르면 이어서 볼 수 있어요.</div>}
      {framedUrl && <iframe title={`증권 원문, ${page}페이지`} src={framedUrl} referrerPolicy="no-referrer" tabIndex={mobile ? 0 : undefined} className="min-h-[50dvh] w-full min-w-0 flex-1 rounded-xl border border-line bg-white sm:min-h-[70dvh]" />}
    </div>
  );

  return (
    <>
      <aside ref={desktopSourceRef} tabIndex={-1} className="sticky top-4 hidden h-[calc(100dvh-2rem)] min-h-0 rounded-2xl border border-line bg-surface p-4 shadow-card focus:outline-none lg:block" aria-label="증권 원문">
        {content()}
      </aside>
      <button ref={openerRef} type="button" className="w-full rounded-xl border border-brand bg-brand-soft px-4 py-3 text-sm font-bold text-brand lg:hidden" onClick={() => { dialogCloseTargetRef.current = "opener"; setDialogOpen(true); }}>원문 보기</button>
      {dialogOpen && (
        <div role="dialog" aria-modal="true" aria-labelledby="mobile-source-title" className="fixed inset-0 z-[100] flex min-w-0 flex-col overflow-hidden bg-surface p-3 sm:p-4 lg:hidden">
          <div className="mb-3 flex shrink-0 flex-wrap items-center justify-between gap-3">
            <h2 id="mobile-source-title" className="text-lg font-bold text-ink">증권 원문</h2>
            <button ref={closeRef} type="button" className="rounded-lg border border-line px-3 py-2 text-sm font-semibold text-ink" onClick={() => { dialogCloseTargetRef.current = "opener"; setDialogOpen(false); }}>원문 닫기</button>
          </div>
          <div className="min-h-0 min-w-0 flex-1 overflow-auto">{content(true)}</div>
        </div>
      )}
    </>
  );
}
