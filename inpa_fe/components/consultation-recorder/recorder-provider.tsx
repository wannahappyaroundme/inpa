"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
} from "react";

import type { RecorderSessionContextValue } from "./recorder-types";
import { useGlobalRecorderSession } from "./use-consultation-recorder";

const RecorderContext = createContext<RecorderSessionContextValue | null>(null);

function elapsedLabel(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

export function RecordingMiniBar({
  session,
}: {
  session: RecorderSessionContextValue;
}) {
  const { state } = session;
  return (
    <aside
      aria-label="진행 중인 상담 녹음"
      className="fixed inset-x-3 bottom-20 z-[80] mx-auto max-w-xl rounded-2xl border border-brand/25 bg-surface px-4 py-3 shadow-xl sm:bottom-5"
    >
      <div className="flex flex-wrap items-center gap-3">
        <span
          aria-hidden="true"
          className={`h-2.5 w-2.5 rounded-full ${
            state.kind === "paused" ? "bg-warning" : "animate-pulse bg-danger"
          }`}
        />
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-extrabold text-ink">
            {state.kind === "paused" ? "상담 녹음 잠시 멈춤" : "상담 녹음 중"}
          </p>
          <p className="mt-0.5 truncate text-[12px] text-ink3" aria-live="polite">
            {elapsedLabel(state.elapsedSeconds)}
            {state.notice ? ` · ${state.notice}` : ""}
          </p>
        </div>
        <div className="flex gap-2">
          {state.kind === "recording" && (
            <button
              type="button"
              onClick={session.pause}
              className="min-h-11 rounded-xl border border-line px-3 text-[13px] font-bold text-ink2"
            >
              잠시 멈춤
            </button>
          )}
          {state.kind === "paused" && (
            <button
              type="button"
              onClick={session.resume}
              className="min-h-11 rounded-xl border border-line px-3 text-[13px] font-bold text-brand"
            >
              이어서 녹음
            </button>
          )}
          {["recording", "paused", "interrupted"].includes(state.kind) && (
            <button
              type="button"
              onClick={session.stop}
              className="min-h-11 rounded-xl bg-brand px-3 text-[13px] font-bold text-white"
            >
              녹음 마치기
            </button>
          )}
        </div>
      </div>
    </aside>
  );
}

export function RecorderProvider({ children }: { children: React.ReactNode }) {
  const session = useGlobalRecorderSession();

  useEffect(() => {
    if (!session.isActive) return;
    const beforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [session.isActive]);

  return (
    <RecorderContext value={session}>
      {children}
      {session.isActive && <RecordingMiniBar session={session} />}
    </RecorderContext>
  );
}

export function useRecorderContext(): RecorderSessionContextValue {
  const session = useContext(RecorderContext);
  if (!session) {
    throw new Error("RecorderProvider is missing");
  }
  return session;
}

export function useOptionalRecorderContext(): RecorderSessionContextValue | null {
  return useContext(RecorderContext);
}

export function useConsultationRecorder(customerId: number) {
  const session = useRecorderContext();
  return useMemo(() => ({
    ...session,
    start: (options: Parameters<RecorderSessionContextValue["start"]>[1]) => (
      session.start(customerId, options)
    ),
    belongsToCustomer: session.customerId === customerId,
  }), [customerId, session]);
}
