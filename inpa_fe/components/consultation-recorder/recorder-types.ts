import type {
  CompletedRecordingPart,
  ConsultationRecording,
} from "@/lib/api";

export type RecorderPhase =
  | "idle"
  | "requesting_permission"
  | "recording"
  | "paused"
  | "stopping"
  | "uploading"
  | "ready"
  | "interrupted"
  | "error";

export interface RecorderState {
  kind: RecorderPhase;
  elapsedSeconds: number;
  uploadedBytes: number;
  notice: string | null;
  error: string | null;
  recording: ConsultationRecording | null;
}
export type UploadPart = (
  partNumber: number,
  blob: Blob,
) => Promise<CompletedRecordingPart>;

export interface RecorderSessionContextValue {
  customerId: number | null;
  state: RecorderState;
  isActive: boolean;
  start: (customerId: number) => Promise<void>;
  pause: () => void;
  resume: () => void;
  stop: () => void;
  discard: () => Promise<void>;
  reset: () => void;
}
