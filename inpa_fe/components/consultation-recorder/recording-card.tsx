"use client";

import { useEffect, useRef, useState } from "react";

import {
  ApiError,
  deleteRecordingSource,
  getConsultationRecording,
  getRecordingPlayUrl,
  summarizeConsultationRecording,
  type ConsultationRecording,
  type ConsultationSummaryStatus,
} from "@/lib/api";

function messageFrom(error: unknown, fallback: string): string {
  return error instanceof ApiError && error.message ? error.message : fallback;
}
const dateTime = new Intl.DateTimeFormat("ko-KR", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "Asia/Seoul",
});

function formatDate(value: string | null): string {
  if (!value) return "-";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "-" : dateTime.format(parsed);
}

function durationLabel(durationMs: number): string {
  const seconds = Math.max(0, Math.round(durationMs / 1000));
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${minutes}분 ${String(remainder).padStart(2, "0")}초`;
}

export function RecordingCard({
  customerId,
  recording,
  onChanged,
  onSummaryReady,
  summaryEnabled,
  summaryConsentReady,
}: {
  customerId: number;
  recording: ConsultationRecording;
  onChanged: (recording: ConsultationRecording) => void;
  onSummaryReady: () => void;
  summaryEnabled: boolean;
  summaryConsentReady: boolean;
}) {
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [loadingAudio, setLoadingAudio] = useState(false);
  const [audioError, setAudioError] = useState<string | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [summaryConfirm, setSummaryConfirm] = useState(false);
  const [summaryBusy, setSummaryBusy] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const summaryBusyRef = useRef(false);
  const onChangedRef = useRef(onChanged);
  const onSummaryReadyRef = useRef(onSummaryReady);

  useEffect(() => {
    onChangedRef.current = onChanged;
    onSummaryReadyRef.current = onSummaryReady;
  }, [onChanged, onSummaryReady]);

  useEffect(() => {
    const active = ["queued", "transcribing", "summarizing"].includes(
      recording.summary?.status ?? "",
    );
    if (!active) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let delay = 5_000;

    const poll = async () => {
      try {
        const refreshed = await getConsultationRecording(customerId, recording.id);
        if (cancelled) return;
        setSummaryError(null);
        onChangedRef.current(refreshed);
        if (refreshed.summary?.status === "succeeded") {
          onSummaryReadyRef.current();
          return;
        }
        if (["queued", "transcribing", "summarizing"].includes(
          refreshed.summary?.status ?? "",
        )) {
          delay = Math.min(30_000, Math.round(delay * 1.5));
          timer = setTimeout(() => void poll(), delay);
        }
      } catch (error) {
        if (cancelled) return;
        setSummaryError(messageFrom(error, "요약 상태를 다시 확인하고 있어요."));
        delay = Math.min(30_000, Math.round(delay * 1.5));
        timer = setTimeout(() => void poll(), delay);
      }
    };

    timer = setTimeout(() => void poll(), delay);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [customerId, recording.id, recording.summary?.status]);

  async function loadAudio() {
    if (loadingAudio) return;
    setLoadingAudio(true);
    setAudioError(null);
    try {
      const result = await getRecordingPlayUrl(customerId, recording.id);
      setAudioUrl(result.url);
    } catch (error) {
      setAudioError(messageFrom(error, "녹음 주소를 다시 받으면 바로 들을 수 있어요."));
    } finally {
      setLoadingAudio(false);
    }
  }

  async function confirmDelete() {
    if (deleting) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      const changed = await deleteRecordingSource(customerId, recording.id);
      onChanged(changed);
      setDeleteConfirm(false);
      setAudioUrl(null);
    } catch (error) {
      setDeleteError(messageFrom(error, "삭제 확인을 다시 요청해 주세요."));
    } finally {
      setDeleting(false);
    }
  }

  async function createSummary() {
    if (summaryBusyRef.current || recording.summary) return;
    summaryBusyRef.current = true;
    setSummaryBusy(true);
    setSummaryError(null);
    try {
      const run = await summarizeConsultationRecording(
        customerId,
        recording.id,
        globalThis.crypto?.randomUUID?.()
          ?? `${recording.id}-${Date.now()}`,
      );
      onChanged({ ...recording, summary: run });
      setSummaryConfirm(false);
    } catch (error) {
      setSummaryError(messageFrom(
        error,
        "요약 요청을 다시 확인하면 상담 내용을 정리할 수 있어요.",
      ));
    } finally {
      summaryBusyRef.current = false;
      setSummaryBusy(false);
    }
  }

  const summaryStatus = recording.summary?.status;
  const summaryMessage = summaryStatusMessage(summaryStatus);
  const summaryActive = ["queued", "transcribing", "summarizing"].includes(
    summaryStatus ?? "",
  );

  return (
    <article className="rounded-2xl border border-line bg-surface p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-[13px] font-bold text-ink">원본 녹음</p>
          <p className="mt-1 text-[12px] text-ink3">
            {formatDate(recording.ended_at)} · {durationLabel(recording.duration_ms)}
          </p>
          <p className="mt-1 text-[12px] text-muted">
            {formatDate(recording.expires_at)}까지 보관 후 자동 삭제
          </p>
        </div>
        {recording.source_available && !audioUrl && (
          <button
            type="button"
            onClick={() => void loadAudio()}
            disabled={loadingAudio}
            className="min-h-11 rounded-xl border border-line px-3 text-[13px] font-bold text-brand disabled:opacity-60"
          >
            {loadingAudio ? "녹음 주소 받는 중" : "녹음 듣기"}
          </button>
        )}
      </div>

      {recording.source_available && audioUrl && (
        <audio
          controls
          controlsList="nodownload"
          preload="none"
          src={audioUrl}
          className="mt-3 w-full"
        >
          녹음을 들을 수 있는 브라우저에서 열어 주세요.
        </audio>
      )}
      {audioError && (
        <p role="alert" className="mt-3 rounded-xl bg-danger-tint px-3 py-2 text-[12px] text-danger-ink">
          {audioError}
        </p>
      )}

      {!recording.source_available && (
        <div className="mt-3 rounded-xl bg-surface2 px-3 py-3">
          <p className="text-[13px] font-bold text-ink">원본 녹음 보관을 마쳤어요.</p>
          <p className="mt-1 text-[12px] leading-5 text-ink3">
            {summaryStatus === "succeeded"
              ? "요약 메모는 아래 상담 메모에서 계속 확인하고 수정할 수 있어요."
              : "메모 작성에서 기억할 내용을 직접 이어서 정리할 수 있어요."}
          </p>
        </div>
      )}

      {summaryMessage && (
        <div
          role={summaryActive ? "status" : undefined}
          aria-live="polite"
          className="mt-3 rounded-xl bg-brand-soft px-3 py-3"
        >
          <p className="text-[13px] font-bold text-ink">{summaryMessage.title}</p>
          <p className="mt-1 text-[12px] leading-5 text-ink2">{summaryMessage.detail}</p>
        </div>
      )}

      {summaryEnabled
        && summaryConsentReady
        && recording.source_available
        && !recording.summary
        && !summaryConfirm && (
        <button
          type="button"
          onClick={() => setSummaryConfirm(true)}
          className="mt-3 min-h-11 rounded-xl bg-brand px-4 text-[13px] font-bold text-white"
        >
          AI로 핵심 메모 만들기
        </button>
      )}

      {summaryConfirm && !recording.summary && (
        <div className="mt-3 rounded-xl bg-brand-soft p-3">
          <p className="text-[13px] font-bold text-ink">이 녹음을 요약할까요?</p>
          <p className="mt-1 text-[12px] leading-5 text-ink2">
            AI 요약은 이 녹음에서 한 번만 만들 수 있어요. 만들어진 메모는 직접 수정할 수 있습니다.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void createSummary()}
              disabled={summaryBusy}
              className="min-h-11 rounded-xl bg-brand px-3 text-[13px] font-bold text-white disabled:opacity-60"
            >
              {summaryBusy ? "핵심 내용 정리 시작 중" : "한 번 요약하기"}
            </button>
            <button
              type="button"
              onClick={() => setSummaryConfirm(false)}
              disabled={summaryBusy}
              className="min-h-11 rounded-xl border border-line bg-surface px-3 text-[13px] font-bold text-ink2"
            >
              더 확인하기
            </button>
          </div>
        </div>
      )}

      {summaryError && (
        <p role="alert" className="mt-3 rounded-xl bg-danger-tint px-3 py-2 text-[12px] leading-5 text-danger-ink">
          {summaryError}
        </p>
      )}

      {recording.source_available && (!deleteConfirm ? (
        <button
          type="button"
          onClick={() => setDeleteConfirm(true)}
          className="mt-3 min-h-11 rounded-xl px-2 text-[12px] font-bold text-danger-ink"
        >
          원본 녹음 지금 삭제
        </button>
      ) : (
        <div className="mt-3 rounded-xl bg-surface2 p-3">
          <p className="text-[12px] leading-5 text-ink2">
            {summaryActive
              ? "원본 녹음과 진행 중인 요약을 마치고, 직접 작성한 메모는 그대로 둡니다."
              : "요약 메모는 남기고 원본 녹음만 지금 삭제합니다."}
          </p>
          {deleteError && (
            <p role="alert" className="mt-2 text-[12px] text-danger-ink">{deleteError}</p>
          )}
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              onClick={() => void confirmDelete()}
              disabled={deleting}
              className="min-h-11 rounded-xl bg-brand px-3 text-[13px] font-bold text-white disabled:opacity-60"
            >
              {deleting ? "삭제 확인 중" : "원본만 삭제"}
            </button>
            <button
              type="button"
              onClick={() => setDeleteConfirm(false)}
              disabled={deleting}
              className="min-h-11 rounded-xl border border-line bg-surface px-3 text-[13px] font-bold text-ink2"
            >
              그대로 보관
            </button>
          </div>
        </div>
      ))}
    </article>
  );
}

function summaryStatusMessage(
  status: ConsultationSummaryStatus | undefined,
): { title: string; detail: string } | null {
  if (!status) return null;
  if (["queued", "transcribing", "summarizing"].includes(status)) {
    return {
      title: "상담 핵심을 정리하고 있어요.",
      detail: "화면을 나가도 계속 진행되며, 완료되면 상담 메모에 추가됩니다.",
    };
  }
  if (status === "succeeded") {
    return {
      title: "요약 메모를 만들었어요.",
      detail: "아래 상담 메모에서 내용을 확인하고 직접 수정할 수 있어요.",
    };
  }
  if (status === "ambiguous") {
    return {
      title: "중복 요약을 막기 위해 처리를 마쳤어요.",
      detail: "메모 작성에서 상담 핵심을 직접 정리해 주세요.",
    };
  }
  if (status === "cancelled") {
    return {
      title: "변경된 동의와 원본 상태를 반영했어요.",
      detail: "메모 작성에서 상담 핵심을 직접 정리할 수 있어요.",
    };
  }
  return {
    title: "직접 메모로 이어서 정리해 주세요.",
    detail: "이 녹음의 AI 요약은 한 번 처리되었으며 다시 만들지 않습니다.",
  };
}
