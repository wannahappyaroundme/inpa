"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  ApiError,
  completeRecordingUpload,
  createRecordingUpload,
  deleteRecordingSource,
  type RecordingUploadSession,
} from "@/lib/api";

import type {
  RecorderSessionContextValue,
  RecorderState,
} from "./recorder-types";
import {
  MultipartBuffer,
  createRecordingPartUploader,
  selectRecordingMimeType,
  withUploadRetry,
} from "./upload-parts";

const MAX_RECORDING_SECONDS = 60 * 60;
const EMPTY_STATE: RecorderState = {
  kind: "idle",
  elapsedSeconds: 0,
  uploadedBytes: 0,
  notice: null,
  error: null,
  recording: null,
};

function messageFrom(error: unknown): string {
  if (error instanceof ApiError && error.message) return error.message;
  if (error instanceof DOMException && error.name === "NotAllowedError") {
    return "마이크 사용을 허용하면 상담 녹음을 시작할 수 있어요.";
  }
  if (error instanceof DOMException && error.name === "NotFoundError") {
    return "사용할 마이크를 연결한 뒤 다시 시작해 주세요.";
  }
  return "녹음 연결을 확인한 뒤 다시 시작해 주세요.";
}
export function recordingNotice(elapsedSeconds: number): string | null {
  if (elapsedSeconds >= 59 * 60) return "1분 뒤 녹음이 마무리돼요.";
  if (elapsedSeconds >= 55 * 60) return "5분 뒤 녹음이 마무리돼요.";
  if (elapsedSeconds >= 45 * 60) return "45분 동안 녹음했어요.";
  return null;
}

export function shouldAutoStop(elapsedSeconds: number): boolean {
  return elapsedSeconds >= MAX_RECORDING_SECONDS;
}

function newClientSessionId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  throw new Error("SECURE_RANDOM_UNAVAILABLE");
}

function stopTracks(stream: MediaStream | null): void {
  stream?.getTracks().forEach((track) => track.stop());
}

export function useGlobalRecorderSession(): RecorderSessionContextValue {
  const [customerId, setCustomerId] = useState<number | null>(null);
  const [state, setState] = useState<RecorderState>(EMPTY_STATE);
  const stateRef = useRef(state);
  const customerIdRef = useRef<number | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const uploadRef = useRef<RecordingUploadSession | null>(null);
  const bufferRef = useRef<MultipartBuffer | null>(null);
  const discardRequestedRef = useRef(false);
  const finalizingRef = useRef(false);

  const updateState = useCallback((
    updater: RecorderState | ((current: RecorderState) => RecorderState),
  ) => {
    setState((current) => {
      const next = typeof updater === "function" ? updater(current) : updater;
      stateRef.current = next;
      return next;
    });
  }, []);

  const releaseBrowserMedia = useCallback(() => {
    stopTracks(streamRef.current);
    streamRef.current = null;
    recorderRef.current = null;
    bufferRef.current = null;
  }, []);

  const finishRecording = useCallback(async () => {
    if (finalizingRef.current) return;
    finalizingRef.current = true;
    const activeCustomerId = customerIdRef.current;
    const upload = uploadRef.current;
    const buffer = bufferRef.current;
    try {
      if (activeCustomerId === null || !upload || !buffer) {
        throw new Error("RECORDING_SESSION_MISSING");
      }
      if (discardRequestedRef.current) {
        buffer.clear();
        await deleteRecordingSource(activeCustomerId, upload.id);
        uploadRef.current = null;
        setCustomerId(null);
        customerIdRef.current = null;
        updateState(EMPTY_STATE);
        return;
      }
      updateState((current) => ({
        ...current,
        kind: "uploading",
        notice: "녹음 파일을 안전하게 마무리하고 있어요.",
        error: null,
      }));
      const parts = await buffer.finish();
      if (parts.length === 0) {
        throw new Error("RECORDING_EMPTY");
      }
      const completed = await withUploadRetry(() => completeRecordingUpload(
        activeCustomerId,
        upload.id,
        parts,
        new Date().toISOString(),
      ));
      uploadRef.current = null;
      updateState((current) => ({
        ...current,
        kind: "ready",
        notice: "녹음을 저장했어요. 원본은 최대 7일 뒤 자동 삭제됩니다.",
        error: null,
        recording: completed,
      }));
    } catch (error) {
      updateState((current) => ({
        ...current,
        kind: "error",
        error: messageFrom(error),
        notice: null,
      }));
    } finally {
      releaseBrowserMedia();
      discardRequestedRef.current = false;
      finalizingRef.current = false;
    }
  }, [releaseBrowserMedia, updateState]);

  const start = useCallback(async (nextCustomerId: number) => {
    if (
      recorderRef.current
      || ["requesting_permission", "recording", "paused", "stopping", "uploading"]
        .includes(stateRef.current.kind)
    ) {
      updateState((current) => ({
        ...current,
        notice: (
          customerIdRef.current === nextCustomerId
            ? "진행 중인 녹음을 이어서 마쳐 주세요."
            : "진행 중인 고객 녹음을 마치면 다른 고객 녹음을 시작할 수 있어요."
        ),
      }));
      return;
    }
    const mimeType = selectRecordingMimeType();
    if (!mimeType || typeof MediaRecorder === "undefined") {
      updateState({
        ...EMPTY_STATE,
        kind: "error",
        error: "이 기기의 기본 브라우저에서 녹음 형식을 확인해 주세요.",
      });
      return;
    }

    setCustomerId(nextCustomerId);
    customerIdRef.current = nextCustomerId;
    updateState({
      ...EMPTY_STATE,
      kind: "requesting_permission",
      notice: "마이크 연결을 확인하고 있어요.",
    });

    let stream: MediaStream | null = null;
    let upload: RecordingUploadSession | null = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      streamRef.current = stream;
      const clientSessionId = newClientSessionId();
      const startedAt = new Date().toISOString();
      upload = await withUploadRetry(() => createRecordingUpload(
        nextCustomerId,
        clientSessionId,
        mimeType,
        startedAt,
      ));
      uploadRef.current = upload;
      bufferRef.current = new MultipartBuffer(
        upload.part_bytes,
        createRecordingPartUploader(
          nextCustomerId,
          upload.id,
          (byteSize) => updateState((current) => ({
            ...current,
            uploadedBytes: current.uploadedBytes + byteSize,
          })),
        ),
      );

      const recorder = new MediaRecorder(stream, { mimeType });
      recorderRef.current = recorder;
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) bufferRef.current?.push(event.data);
      };
      recorder.onerror = () => {
        updateState((current) => ({
          ...current,
          kind: "interrupted",
          notice: "녹음을 마무리해 저장하고 있어요.",
        }));
        if (recorder.state !== "inactive") recorder.stop();
      };
      recorder.onstop = () => {
        void finishRecording();
      };
      stream.getTracks().forEach((track) => {
        track.onended = () => {
          if (recorder.state !== "inactive") {
            updateState((current) => ({
              ...current,
              kind: "interrupted",
              notice: "마이크 연결이 바뀌어 녹음을 마무리하고 있어요.",
            }));
            recorder.stop();
          }
        };
      });
      discardRequestedRef.current = false;
      recorder.start(5000);
      updateState({
        ...EMPTY_STATE,
        kind: "recording",
        notice: "상담 녹음 중이에요.",
      });
    } catch (error) {
      stopTracks(stream);
      if (upload) {
        try {
          await deleteRecordingSource(nextCustomerId, upload.id);
        } catch {
          // Server cleanup retains the exact source key and retries deletion.
        }
      }
      releaseBrowserMedia();
      uploadRef.current = null;
      updateState({
        ...EMPTY_STATE,
        kind: "error",
        error: messageFrom(error),
      });
    }
  }, [finishRecording, releaseBrowserMedia, updateState]);

  const pause = useCallback(() => {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state !== "recording") return;
    recorder.pause();
    updateState((current) => ({
      ...current,
      kind: "paused",
      notice: "녹음을 잠시 멈췄어요.",
    }));
  }, [updateState]);

  const resume = useCallback(() => {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state !== "paused") return;
    recorder.resume();
    updateState((current) => ({
      ...current,
      kind: "recording",
      notice: "상담 녹음을 이어가고 있어요.",
    }));
  }, [updateState]);

  const stop = useCallback(() => {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state === "inactive") return;
    updateState((current) => ({
      ...current,
      kind: "stopping",
      notice: "녹음을 마무리하고 있어요.",
    }));
    recorder.stop();
  }, [updateState]);

  const discard = useCallback(async () => {
    discardRequestedRef.current = true;
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      updateState((current) => ({
        ...current,
        kind: "stopping",
        notice: "이번 녹음을 정리하고 있어요.",
      }));
      recorder.stop();
      return;
    }
    const activeCustomerId = customerIdRef.current;
    const upload = uploadRef.current;
    if (activeCustomerId !== null && upload) {
      try {
        await deleteRecordingSource(activeCustomerId, upload.id);
      } finally {
        uploadRef.current = null;
        setCustomerId(null);
        customerIdRef.current = null;
        updateState(EMPTY_STATE);
      }
    }
  }, [updateState]);

  const reset = useCallback(() => {
    if (["ready", "error"].includes(stateRef.current.kind)) {
      setCustomerId(null);
      customerIdRef.current = null;
      updateState(EMPTY_STATE);
    }
  }, [updateState]);

  useEffect(() => {
    if (state.kind !== "recording") return;
    const timer = window.setInterval(() => {
      let autoStop = false;
      updateState((current) => {
        if (current.kind !== "recording") return current;
        const elapsedSeconds = current.elapsedSeconds + 1;
        autoStop = shouldAutoStop(elapsedSeconds);
        return {
          ...current,
          elapsedSeconds,
          notice: recordingNotice(elapsedSeconds) ?? current.notice,
        };
      });
      if (autoStop) stop();
    }, 1000);
    return () => window.clearInterval(timer);
  }, [state.kind, stop, updateState]);

  useEffect(() => {
    const onVisibilityChange = () => {
      if (document.visibilityState !== "hidden") return;
      if (!["recording", "paused"].includes(stateRef.current.kind)) return;
      updateState((current) => ({
        ...current,
        notice: "이 화면을 열어 두면 녹음을 안정적으로 이어갈 수 있어요.",
      }));
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => document.removeEventListener("visibilitychange", onVisibilityChange);
  }, [updateState]);

  useEffect(() => () => {
    stopTracks(streamRef.current);
  }, []);

  const isActive = [
    "requesting_permission",
    "recording",
    "paused",
    "stopping",
    "uploading",
    "interrupted",
  ].includes(state.kind);

  return useMemo(() => ({
    customerId,
    state,
    isActive,
    start,
    pause,
    resume,
    stop,
    discard,
    reset,
  }), [
    customerId,
    discard,
    isActive,
    pause,
    reset,
    resume,
    start,
    state,
    stop,
  ]);
}
