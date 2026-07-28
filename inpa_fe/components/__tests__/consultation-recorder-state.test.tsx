import {
  act,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ConsultationRecorder } from "@/components/consultation-recorder/consultation-recorder";
import { RecorderProvider } from "@/components/consultation-recorder/recorder-provider";
import {
  recordingNotice,
  shouldAutoStop,
  useGlobalRecorderSession,
} from "@/components/consultation-recorder/use-consultation-recorder";

const api = vi.hoisted(() => ({
  completeRecordingUpload: vi.fn(),
  createConsentRequest: vi.fn(),
  createRecordingUpload: vi.fn(),
  deleteRecordingSource: vi.fn(),
  getConsultationRecording: vi.fn(),
  getRecordingCapability: vi.fn(),
  getRecordingDownloadUrl: vi.fn(),
  getRecordingPartUrl: vi.fn(),
  getRecordingPlayUrl: vi.fn(),
  listConsultationRecordings: vi.fn(),
  summarizeConsultationRecording: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    code: string;

    constructor(status: number, code: string, message: string) {
      super(message);
      this.status = status;
      this.code = code;
    }
  },
  ...api,
}));

function recording(overrides: Record<string, unknown> = {}) {
  return {
    id: "00000000-0000-4000-8000-000000000031",
    status: "uploading",
    mime_type: "audio/webm;codecs=opus",
    codec: "",
    byte_size: 0,
    duration_ms: 0,
    started_at: new Date().toISOString(),
    ended_at: null,
    uploaded_at: null,
    expires_at: null,
    deleted_at: null,
    delete_reason: "",
    source_available: false,
    summary: null,
    version: 1,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    part_bytes: 8,
    max_part_number: 13,
    ...overrides,
  };
}

function capability() {
  return {
    recording_enabled: true,
    consent_ready: true,
    summary_enabled: true,
    summary_consent_ready: true,
    summary_usage: {
      year_month: "2026-07",
      monthly_success_used: 0,
      monthly_success_limit: 5,
    },
    customer_free_summary_used: false,
    retention_days: 30,
    planner_notice_version: "consultation-notice-v2-2026-07-28",
    planner_notice_text: "가입 희망자에게 읽을 현재 녹음 안내입니다.",
    max_duration_seconds: 3600,
    max_bytes: 100 * 1024 * 1024,
    part_bytes: 8,
    max_part_number: 13,
  };
}

function mediaStream(track: { stop: ReturnType<typeof vi.fn>; onended: null }) {
  return {
    getTracks: () => [track],
  } as unknown as MediaStream;
}

async function startFromRecorderUi() {
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "상담 녹음" }));
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: "녹음 시작" }));
  return user;
}

class FakeMediaRecorder {
  static isTypeSupported() {
    return true;
  }

  state: RecordingState = "inactive";
  ondataavailable: ((event: BlobEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onstop: ((event: Event) => void) | null = null;

  start() {
    mediaRecorderStart();
    this.state = "recording";
  }

  pause() {
    this.state = "paused";
  }

  resume() {
    this.state = "recording";
  }

  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob([new Uint8Array(3)]) } as BlobEvent);
    this.onstop?.(new Event("stop"));
  }
}

const mediaRecorderStart = vi.fn();

describe("상담 녹음 시간 안내", () => {
  it("45분, 55분, 59분 안내와 60분 자동 종료를 계산한다", () => {
    expect(recordingNotice(45 * 60)).toBe("45분 동안 녹음했어요.");
    expect(recordingNotice(55 * 60)).toBe("5분 뒤 녹음이 마무리돼요.");
    expect(recordingNotice(59 * 60)).toBe("1분 뒤 녹음이 마무리돼요.");
    expect(recordingNotice(44 * 60)).toBeNull();
    expect(shouldAutoStop(60 * 60)).toBe(true);
    expect(shouldAutoStop(60 * 60 - 1)).toBe(false);
  });
});

describe("전역 상담 녹음 상태", () => {
  const track = {
    stop: vi.fn(),
    onended: null as (() => void) | null,
  };
  const stream = {
    getTracks: () => [track],
  } as unknown as MediaStream;

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
    vi.stubGlobal("crypto", {
      randomUUID: () => "00000000-0000-4000-8000-000000000099",
    });
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
    });
    api.createRecordingUpload.mockResolvedValue(recording());
    api.getRecordingPartUrl.mockResolvedValue({
      url: "https://upload.example/part-1",
      part_number: 1,
      expires_in_seconds: 600,
    });
    api.completeRecordingUpload.mockResolvedValue(recording({
      status: "ready",
      byte_size: 3,
      duration_ms: 1000,
      source_available: true,
    }));
    api.deleteRecordingSource.mockResolvedValue(recording({ status: "deleted" }));
    api.getRecordingCapability.mockResolvedValue(capability());
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", {
      status: 200,
      headers: { ETag: '"etag-1"' },
    })));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("권한 요청부터 일시정지, 재개, 완료까지 한 녹음기만 사용한다", async () => {
    const { result } = renderHook(() => useGlobalRecorderSession());

    await act(async () => {
      await result.current.start(31, {
        noticeVersion: "consultation-notice-v2-2026-07-28",
        retentionDays: 30,
      });
    });
    expect(result.current.state.kind).toBe("recording");
    expect(api.createRecordingUpload).toHaveBeenCalledWith(
      31,
      "00000000-0000-4000-8000-000000000099",
      "audio/webm;codecs=opus",
      expect.any(String),
      "consultation-notice-v2-2026-07-28",
    );

    act(() => result.current.pause());
    expect(result.current.state.kind).toBe("paused");
    act(() => result.current.resume());
    expect(result.current.state.kind).toBe("recording");
    act(() => result.current.stop());

    await waitFor(() => expect(result.current.state.kind).toBe("ready"));
    expect(result.current.state.notice).toContain("최대 30일");
    expect(api.getRecordingPartUrl).toHaveBeenCalledWith(
      31,
      "00000000-0000-4000-8000-000000000031",
      1,
    );
    expect(api.completeRecordingUpload).toHaveBeenCalledTimes(1);
    expect(track.stop).toHaveBeenCalled();
  });

  it("마이크 동의를 건너뛴 경우 다음 행동을 안내한다", async () => {
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockRejectedValue(
          new DOMException("denied", "NotAllowedError"),
        ),
      },
    });
    const { result } = renderHook(() => useGlobalRecorderSession());

    await act(async () => {
      await result.current.start(31, {
        noticeVersion: "consultation-notice-v2-2026-07-28",
        retentionDays: 30,
      });
    });

    expect(result.current.state.kind).toBe("error");
    expect(result.current.state.error).toContain("마이크 사용을 허용");
    expect(api.createRecordingUpload).not.toHaveBeenCalled();
  });

  it("고객 전환으로 취소된 늦은 업로드 응답은 녹음을 시작하지 않는다", async () => {
    let resolveUpload: ((value: ReturnType<typeof recording>) => void) | undefined;
    api.createRecordingUpload.mockImplementationOnce(() => new Promise((resolve) => {
      resolveUpload = resolve;
    }));
    const controller = new AbortController();
    const { result } = renderHook(() => useGlobalRecorderSession());

    let startPromise: Promise<void>;
    act(() => {
      startPromise = result.current.start(31, {
        noticeVersion: "consultation-notice-v2-2026-07-28",
        retentionDays: 30,
        signal: controller.signal,
      });
    });
    await waitFor(() => expect(api.createRecordingUpload).toHaveBeenCalledOnce());

    controller.abort();
    resolveUpload?.(recording());
    await act(async () => {
      await startPromise;
    });

    expect(mediaRecorderStart).not.toHaveBeenCalled();
    expect(api.deleteRecordingSource).toHaveBeenCalledWith(
      31,
      "00000000-0000-4000-8000-000000000031",
    );
    expect(result.current.customerId).toBeNull();
    expect(result.current.state.kind).toBe("idle");
    expect(track.stop).toHaveBeenCalled();
  });

  it("UI에서 권한 요청 중 지우면 늦은 마이크 응답의 트랙만 멈추고 업로드를 시작하지 않는다", async () => {
    const permissionTrack = { stop: vi.fn(), onended: null };
    const permissionStream = mediaStream(permissionTrack);
    let resolvePermission: ((value: MediaStream) => void) | undefined;
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: vi.fn(() => new Promise<MediaStream>((resolve) => {
          resolvePermission = resolve;
        })),
      },
    });
    render(
      <RecorderProvider>
        <ConsultationRecorder customerId={31} />
      </RecorderProvider>,
    );

    const user = await startFromRecorderUi();
    await user.click(await screen.findByRole("button", {
      name: "이번 녹음 지우기",
    }));
    resolvePermission?.(permissionStream);

    await waitFor(() => expect(permissionTrack.stop).toHaveBeenCalledOnce());
    expect(api.createRecordingUpload).not.toHaveBeenCalled();
    expect(mediaRecorderStart).not.toHaveBeenCalled();
  });

  it("UI에서 업로드 세션 대기 중 지우면 늦게 온 정확한 원본만 지우고 녹음을 시작하지 않는다", async () => {
    let resolveUpload: ((value: ReturnType<typeof recording>) => void) | undefined;
    api.createRecordingUpload.mockImplementationOnce(() => (
      new Promise((resolve) => {
        resolveUpload = resolve;
      })
    ));
    render(
      <RecorderProvider>
        <ConsultationRecorder customerId={31} />
      </RecorderProvider>,
    );

    const user = await startFromRecorderUi();
    await waitFor(() => expect(api.createRecordingUpload).toHaveBeenCalledOnce());
    await user.click(screen.getByRole("button", { name: "이번 녹음 지우기" }));
    resolveUpload?.(recording({ id: "late-recording-31" }));

    await waitFor(() => expect(api.deleteRecordingSource).toHaveBeenCalledWith(
      31,
      "late-recording-31",
    ));
    expect(mediaRecorderStart).not.toHaveBeenCalled();
  });

  it("UI에서 취소한 늦은 원본을 정리한 뒤 시작한 현재 녹음은 그대로 둔다", async () => {
    const oldTrack = { stop: vi.fn(), onended: null };
    const currentTrack = { stop: vi.fn(), onended: null };
    const getUserMedia = vi.fn()
      .mockResolvedValueOnce(mediaStream(oldTrack))
      .mockResolvedValueOnce(mediaStream(currentTrack));
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia },
    });
    let resolveOldUpload: ((value: ReturnType<typeof recording>) => void) | undefined;
    api.createRecordingUpload
      .mockImplementationOnce(() => new Promise((resolve) => {
        resolveOldUpload = resolve;
      }))
      .mockResolvedValueOnce(recording({ id: "current-recording-31" }));
    render(
      <RecorderProvider>
        <ConsultationRecorder customerId={31} />
      </RecorderProvider>,
    );

    const user = await startFromRecorderUi();
    await waitFor(() => expect(api.createRecordingUpload).toHaveBeenCalledOnce());
    await user.click(screen.getByRole("button", { name: "이번 녹음 지우기" }));
    resolveOldUpload?.(recording({ id: "late-recording-31" }));
    await waitFor(() => expect(api.deleteRecordingSource).toHaveBeenCalledWith(
      31,
      "late-recording-31",
    ));

    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "녹음 시작" }));
    await waitFor(() => expect(mediaRecorderStart).toHaveBeenCalledOnce());

    expect(api.deleteRecordingSource).toHaveBeenCalledTimes(1);
    expect(api.deleteRecordingSource).not.toHaveBeenCalledWith(
      31,
      "current-recording-31",
    );
    expect(currentTrack.stop).not.toHaveBeenCalled();
  });
});
