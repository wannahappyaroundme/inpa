import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  recordingNotice,
  shouldAutoStop,
  useGlobalRecorderSession,
} from "@/components/consultation-recorder/use-consultation-recorder";

const api = vi.hoisted(() => ({
  completeRecordingUpload: vi.fn(),
  createRecordingUpload: vi.fn(),
  deleteRecordingSource: vi.fn(),
  getRecordingPartUrl: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
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

class FakeMediaRecorder {
  static isTypeSupported() {
    return true;
  }

  state: RecordingState = "inactive";
  ondataavailable: ((event: BlobEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onstop: ((event: Event) => void) | null = null;

  start() {
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
      await result.current.start(31);
    });
    expect(result.current.state.kind).toBe("recording");
    expect(api.createRecordingUpload).toHaveBeenCalledWith(
      31,
      "00000000-0000-4000-8000-000000000099",
      "audio/webm;codecs=opus",
      expect.any(String),
    );

    act(() => result.current.pause());
    expect(result.current.state.kind).toBe("paused");
    act(() => result.current.resume());
    expect(result.current.state.kind).toBe("recording");
    act(() => result.current.stop());

    await waitFor(() => expect(result.current.state.kind).toBe("ready"));
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
      await result.current.start(31);
    });

    expect(result.current.state.kind).toBe("error");
    expect(result.current.state.error).toContain("마이크 사용을 허용");
    expect(api.createRecordingUpload).not.toHaveBeenCalled();
  });
});
