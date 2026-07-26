import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  createConsentRequest: vi.fn(),
  deleteRecordingSource: vi.fn(),
  getConsultationRecording: vi.fn(),
  getRecordingCapability: vi.fn(),
  getRecordingPlayUrl: vi.fn(),
  listConsultationRecordings: vi.fn(),
  summarizeConsultationRecording: vi.fn(),
}));

const recorder = vi.hoisted(() => ({
  start: vi.fn(),
  pause: vi.fn(),
  resume: vi.fn(),
  stop: vi.fn(),
  discard: vi.fn(),
  reset: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, ...api };
});
vi.mock("@/components/consultation-recorder/recorder-provider", () => ({
  useOptionalRecorderContext: () => ({
    customerId: null,
    state: {
      kind: "idle",
      elapsedSeconds: 0,
      uploadedBytes: 0,
      notice: null,
      error: null,
      recording: null,
    },
    isActive: false,
    ...recorder,
  }),
}));

import {
  ConsultationRecorder,
  ConsultationRecordingList,
} from "@/components/consultation-recorder/consultation-recorder";

function capability(consentReady: boolean) {
  return {
    recording_enabled: true,
    consent_ready: consentReady,
    summary_enabled: true,
    summary_consent_ready: true,
    summary_usage: {
      year_month: "2026-07",
      monthly_success_used: 0,
      monthly_success_limit: 5,
    },
    customer_free_summary_used: false,
    retention_days: 7,
    max_duration_seconds: 3600,
    max_bytes: 100 * 1024 * 1024,
    part_bytes: 8 * 1024 * 1024,
    max_part_number: 13,
  };
}

function recordings(results: Array<Record<string, unknown>> = []) {
  return {
    count: results.length,
    next: null,
    previous: null,
    results,
  };
}

describe("고객 상담 녹음", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("crypto", {
      randomUUID: () => "00000000-0000-4000-8000-000000000777",
    });
    api.getRecordingCapability.mockResolvedValue(capability(true));
    api.listConsultationRecordings.mockResolvedValue(recordings());
  });

  it("7일 보관과 녹음당 1회 요약 규칙을 시작 전에 보여준다", async () => {
    render(<ConsultationRecorder customerId={31} />);
    await userEvent.click(
      await screen.findByRole("button", { name: "상담 녹음" }),
    );

    expect(screen.getByText(/인파에서 최대 7일 보관/)).toBeTruthy();
    expect(screen.getByText(/녹음 파일 하나당 AI 요약은 한 번/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "녹음 시작" })).toBeTruthy();
  });

  it("고객 동의가 없으면 링크, QR 안내, 완료 재확인을 제공한다", async () => {
    api.getRecordingCapability.mockResolvedValue(capability(false));
    render(<ConsultationRecorder customerId={31} />);
    await userEvent.click(
      await screen.findByRole("button", { name: "상담 녹음" }),
    );

    expect(screen.getByRole("button", { name: "동의 링크 복사" })).toBeTruthy();
    expect(screen.getByText(/QR로 열어/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "동의 완료 다시 확인" })).toBeTruthy();
  });

  it("기능 스위치가 닫히면 녹음 버튼을 숨긴다", async () => {
    api.getRecordingCapability.mockResolvedValue({
      ...capability(false),
      recording_enabled: false,
    });
    render(<ConsultationRecorder customerId={31} />);

    await vi.waitFor(() => {
      expect(api.getRecordingCapability).toHaveBeenCalledWith(31);
    });
    expect(screen.queryByRole("button", { name: "상담 녹음" })).toBeNull();
  });

  it("삭제된 원본 상태는 새로고침 뒤에도 고객별 목록에서 복구한다", async () => {
    api.listConsultationRecordings.mockResolvedValue(recordings([{
      id: "00000000-0000-4000-8000-000000000031",
      status: "deleted",
      mime_type: "audio/webm",
      codec: "opus",
      byte_size: 1024,
      duration_ms: 60_000,
      started_at: "2026-07-26T01:00:00Z",
      ended_at: "2026-07-26T01:01:00Z",
      uploaded_at: "2026-07-26T01:01:00Z",
      expires_at: "2026-08-02T00:46:00Z",
      deleted_at: "2026-07-27T01:00:00Z",
      delete_reason: "user_requested",
      source_available: false,
      summary: null,
      version: 3,
      created_at: "2026-07-26T01:00:00Z",
      updated_at: "2026-07-27T01:00:00Z",
    }]));

    render(<ConsultationRecordingList customerId={31} />);

    expect(await screen.findByText("원본 녹음 보관을 마쳤어요.")).toBeTruthy();
    expect(screen.getByText(/메모 작성에서 기억할 내용을 직접/)).toBeTruthy();
  });

  it("확인 뒤 녹음별 AI 요약을 정확히 한 번 요청한다", async () => {
    api.listConsultationRecordings.mockResolvedValue(recordings([{
      id: "00000000-0000-4000-8000-000000000032",
      status: "ready",
      mime_type: "audio/webm",
      codec: "opus",
      byte_size: 1024,
      duration_ms: 60_000,
      started_at: "2026-07-26T01:00:00Z",
      ended_at: "2026-07-26T01:01:00Z",
      uploaded_at: "2026-07-26T01:01:00Z",
      expires_at: "2026-08-02T00:46:00Z",
      deleted_at: null,
      delete_reason: "",
      source_available: true,
      summary: null,
      version: 2,
      created_at: "2026-07-26T01:00:00Z",
      updated_at: "2026-07-26T01:01:00Z",
    }]));
    api.summarizeConsultationRecording.mockResolvedValue({
      id: "00000000-0000-4000-8000-000000000888",
      status: "queued",
      memo_id: null,
      created_at: "2026-07-26T01:02:00Z",
      completed_at: null,
    });

    render(<ConsultationRecordingList customerId={31} />);
    await userEvent.click(await screen.findByRole("button", {
      name: "AI로 핵심 메모 만들기",
    }));
    expect(screen.getByText(/한 번만 만들 수 있어요/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "한 번 요약하기" }));

    expect(api.summarizeConsultationRecording).toHaveBeenCalledOnce();
    expect(api.summarizeConsultationRecording).toHaveBeenCalledWith(
      31,
      "00000000-0000-4000-8000-000000000032",
      "00000000-0000-4000-8000-000000000777",
    );
    expect(await screen.findByText("상담 핵심을 정리하고 있어요.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "AI로 핵심 메모 만들기" })).toBeNull();
  });
});
