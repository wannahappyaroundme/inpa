"use client";

import { useState } from "react";

import {
  ApiError,
  deleteRecordingSource,
  getRecordingPlayUrl,
  type ConsultationRecording,
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
}: {
  customerId: number;
  recording: ConsultationRecording;
  onChanged: (recording: ConsultationRecording) => void;
}) {
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [loadingAudio, setLoadingAudio] = useState(false);
  const [audioError, setAudioError] = useState<string | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  if (!recording.source_available) {
    return (
      <article className="rounded-2xl border border-line bg-surface p-4">
        <p className="text-[13px] font-bold text-ink">원본 녹음은 보관을 마치고 삭제됐어요.</p>
        <p className="mt-1 text-[12px] text-ink3">요약 메모는 그대로 남아요.</p>
        <p className="mt-2 text-[12px] text-muted">상담 시각 {formatDate(recording.ended_at)}</p>
      </article>
    );
  }

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
        {!audioUrl && (
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

      {audioUrl && (
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

      {!deleteConfirm ? (
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
            요약 메모는 남기고 원본 녹음만 지금 삭제합니다.
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
      )}
    </article>
  );
}
