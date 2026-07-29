import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const navigation = vi.hoisted(() => ({
  push: vi.fn(),
}));

const api = vi.hoisted(() => ({
  createConsentRequest: vi.fn(),
  deleteRecordingSource: vi.fn(),
  getRecordingDownloadUrl: vi.fn(),
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

const recorderSession = vi.hoisted(() => ({
  current: null as Record<string, unknown> | null,
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, ...api };
});
vi.mock("next/navigation", () => ({
  useRouter: () => navigation,
}));
vi.mock("@/components/consultation-recorder/recorder-provider", () => ({
  useOptionalRecorderContext: () => recorderSession.current ?? ({
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
import { navigateToRecordingDownload } from "@/components/consultation-recorder/recording-card";
import { ApiError } from "@/lib/api";

function capability(consentReady: boolean) {
  return {
    recording_enabled: true,
    consent_ready: consentReady,
    summary_enabled: true,
    summary_provider: "openai",
    summary_consent_ready: true,
    summary_usage: {
      year_month: "2026-07",
      monthly_success_used: 0,
      monthly_success_limit: 5,
    },
    customer_free_summary_used: false,
    retention_days: 30,
    planner_notice_version: "consultation-notice-v2-2026-07-28",
    planner_notice_text: "본 상담은 상담 내용을 정확히 기록하고, 향후 상담 내용과 보험금 청구 관련 안내를 확인하는 참고자료로 활용하기 위해 녹음합니다. 원본은 인파에 30일 동안 보관된 뒤 자동 삭제됩니다. 녹음에 동의하시나요?",
    max_duration_seconds: 3600,
    max_bytes: 100 * 1024 * 1024,
    part_bytes: 8 * 1024 * 1024,
    max_part_number: 13,
  };
}

function session(overrides: Record<string, unknown> = {}) {
  return {
    customerId: null,
    state: {
      kind: "idle",
      elapsedSeconds: 0,
      uploadedBytes: 0,
      notice: null,
      error: null,
      errorCode: null,
      recording: null,
    },
    isActive: false,
    ...recorder,
    ...overrides,
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

function recording(overrides: Record<string, unknown> = {}) {
  return {
    id: "00000000-0000-4000-8000-000000000032",
    status: "ready",
    mime_type: "audio/webm",
    codec: "opus",
    byte_size: 1024,
    duration_ms: 60_000,
    started_at: "2026-07-26T01:00:00Z",
    ended_at: "2026-07-26T01:01:00Z",
    uploaded_at: "2026-07-26T01:01:00Z",
    expires_at: "2026-08-25T01:01:00Z",
    deleted_at: null,
    delete_reason: "",
    source_available: true,
    summary: null,
    version: 2,
    created_at: "2026-07-26T01:00:00Z",
    updated_at: "2026-07-26T01:01:00Z",
    ...overrides,
  };
}

describe("고객 상담 녹음", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    recorderSession.current = session();
    vi.stubGlobal("crypto", {
      randomUUID: () => "00000000-0000-4000-8000-000000000777",
    });
    recorder.start.mockResolvedValue(undefined);
    api.getRecordingCapability.mockResolvedValue(capability(true));
    api.listConsultationRecordings.mockResolvedValue(recordings());
  });

  it("다운로드 이동은 http·https 주소만 허용한다", () => {
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);

    expect(navigateToRecordingDownload("javascript:alert('recording')")).toBe(false);
    expect(click).not.toHaveBeenCalled();
    expect(navigateToRecordingDownload("https://private.example/signed-recording"))
      .toBe(true);
    expect(click).toHaveBeenCalledOnce();
  });

  it("서버의 30일 보관과 녹음당 1회 요약 규칙을 시작 전에 보여준다", async () => {
    render(<ConsultationRecorder customerId={31} />);
    await userEvent.click(
      await screen.findByRole("button", { name: "상담 녹음" }),
    );

    expect(screen.getByText(/인파에서 최대 30일 보관/)).toBeTruthy();
    expect(screen.getByText(/녹음 파일 하나당 AI 요약은 한 번/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "녹음 시작" })).toBeDisabled();
  });

  it("모달은 첫 요소에 초점을 두고 Tab과 Shift+Tab을 끝에서 순환시킨다", async () => {
    const user = userEvent.setup();
    render(<ConsultationRecorder customerId={31} />);
    await user.click(await screen.findByRole("button", { name: "상담 녹음" }));

    const close = screen.getByRole("button", { name: "상담 녹음 창 닫기" });
    const last = screen.getByRole("button", { name: "상담 메모로 기록하기" });
    await waitFor(() => expect(document.activeElement).toBe(close));

    await user.tab({ shift: true });
    expect(document.activeElement).toBe(last);
    await user.tab();
    expect(document.activeElement).toBe(close);
  });

  it("Escape와 바깥 영역 닫기는 상담 녹음 호출 버튼으로 초점을 돌린다", async () => {
    const user = userEvent.setup();
    render(<ConsultationRecorder customerId={31} />);
    const trigger = await screen.findByRole("button", { name: "상담 녹음" });

    await user.click(trigger);
    expect(document.body.style.overflow).toBe("hidden");
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(trigger));

    await user.click(trigger);
    const dialog = screen.getByRole("dialog");
    fireEvent.mouseDown(dialog.parentElement as HTMLElement);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(trigger));
    expect(document.body.style.overflow).toBe("");
  });

  it("닫기 버튼은 배경 접근성 속성과 body 상태를 기존 값으로 되돌린다", async () => {
    const user = userEvent.setup();
    const background = document.createElement("div");
    background.setAttribute("inert", "legacy");
    background.setAttribute("aria-hidden", "false");
    document.body.appendChild(background);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "clip";

    try {
      render(<ConsultationRecorder customerId={31} />);
      const trigger = await screen.findByRole("button", { name: "상담 녹음" });
      await user.click(trigger);

      expect(background.getAttribute("inert")).toBe("");
      expect(background.getAttribute("aria-hidden")).toBe("true");
      expect(document.body.style.overflow).toBe("hidden");

      await user.click(
        screen.getByRole("button", { name: "상담 녹음 창 닫기" }),
      );
      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
      expect(background.getAttribute("inert")).toBe("legacy");
      expect(background.getAttribute("aria-hidden")).toBe("false");
      expect(document.body.style.overflow).toBe("clip");
      await waitFor(() => expect(document.activeElement).toBe(trigger));
    } finally {
      background.remove();
      document.body.style.overflow = previousOverflow;
    }
  });

  it("고지를 확인한 현재 시도만 시작하고 거절 시 기존 메모 영역으로 이동한다", async () => {
    const user = userEvent.setup();
    render(<ConsultationRecorder customerId={31} />);
    const trigger = await screen.findByRole("button", { name: "상담 녹음" });
    await user.click(trigger);

    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "녹음 시작" }));

    expect(recorder.start).toHaveBeenCalledWith(
      31,
      expect.objectContaining({
        noticeVersion: "consultation-notice-v2-2026-07-28",
        retentionDays: 30,
        signal: expect.any(AbortSignal),
      }),
    );

    await user.click(screen.getByRole("button", { name: "상담 메모로 기록하기" }));
    expect(navigation.push).toHaveBeenCalledWith(
      "/customer/31?tab=history&view=memos#customer-history-panel-memos",
    );
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  it("저장 완료 뒤 기록 확인으로 닫아도 호출 버튼으로 초점을 돌린다", async () => {
    const user = userEvent.setup();
    const view = render(<ConsultationRecorder customerId={31} />);
    const trigger = await screen.findByRole("button", { name: "상담 녹음" });
    await user.click(trigger);

    recorderSession.current = session({
      customerId: 31,
      state: {
        kind: "ready",
        elapsedSeconds: 10,
        uploadedBytes: 100,
        notice: "녹음을 저장했어요.",
        error: null,
        errorCode: null,
        recording: { id: "recording-ready" },
      },
    });
    view.rerender(<ConsultationRecorder customerId={31} />);

    await user.click(screen.getByRole("button", { name: "상담 기록 확인" }));
    expect(recorder.reset).toHaveBeenCalledOnce();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  it("취소, 완료, 고객 변경 뒤에는 고지 확인을 다시 받는다", async () => {
    const user = userEvent.setup();
    const view = render(<ConsultationRecorder customerId={31} />);
    await user.click(await screen.findByRole("button", { name: "상담 녹음" }));
    await user.click(screen.getByRole("checkbox"));

    recorderSession.current = session({
      customerId: 31,
      isActive: true,
      state: {
        kind: "recording",
        elapsedSeconds: 2,
        uploadedBytes: 0,
        notice: "상담 녹음 중이에요.",
        error: null,
        errorCode: null,
        recording: null,
      },
    });
    view.rerender(<ConsultationRecorder customerId={31} />);
    await user.click(screen.getByRole("button", { name: "이번 녹음 지우기" }));
    recorderSession.current = session();
    view.rerender(<ConsultationRecorder customerId={31} />);
    expect(screen.getByRole("checkbox")).not.toBeChecked();

    await user.click(screen.getByRole("checkbox"));
    recorderSession.current = session({
      customerId: 31,
      state: {
        kind: "ready",
        elapsedSeconds: 10,
        uploadedBytes: 100,
        notice: "녹음을 저장했어요.",
        error: null,
        errorCode: null,
        recording: { id: "recording-ready" },
      },
    });
    view.rerender(<ConsultationRecorder customerId={31} />);
    recorderSession.current = session();
    view.rerender(<ConsultationRecorder customerId={31} />);
    expect(screen.getByRole("checkbox")).not.toBeChecked();

    await user.click(screen.getByRole("checkbox"));
    api.getRecordingCapability.mockResolvedValue(capability(true));
    view.rerender(<ConsultationRecorder customerId={32} />);
    expect(await screen.findByRole("checkbox")).not.toBeChecked();
  });

  it("409 고지 변경 뒤 최신 버전을 다시 받고 자동 재시작하지 않는다", async () => {
    const user = userEvent.setup();
    api.getRecordingCapability
      .mockResolvedValueOnce(capability(true))
      .mockResolvedValueOnce({
        ...capability(true),
        planner_notice_version: "consultation-notice-v3",
        planner_notice_text: "최신 녹음 안내 문구입니다.",
      });
    const view = render(<ConsultationRecorder customerId={31} />);
    await user.click(await screen.findByRole("button", { name: "상담 녹음" }));
    await user.click(screen.getByRole("checkbox"));

    recorderSession.current = session({
      customerId: 31,
      state: {
        kind: "error",
        elapsedSeconds: 0,
        uploadedBytes: 0,
        notice: null,
        error: "최신 안내 문구를 확인하면 녹음을 시작할 수 있어요.",
        errorCode: "recording_notice_changed",
        recording: null,
      },
    });
    view.rerender(<ConsultationRecorder customerId={31} />);

    expect(await screen.findByText("최신 녹음 안내 문구입니다.")).toBeInTheDocument();
    const refreshedCheckbox = screen.getByRole("checkbox");
    expect(refreshedCheckbox).not.toBeChecked();
    await waitFor(() => expect(document.activeElement).toBe(refreshedCheckbox));
    expect(recorder.start).not.toHaveBeenCalled();
    expect(api.getRecordingCapability).toHaveBeenCalledTimes(2);
  });

  it("409 뒤 최신 안내 조회가 실패하면 이전 안내를 숨기고 재시도 성공 뒤 새 안내만 확인받는다", async () => {
    const user = userEvent.setup();
    api.getRecordingCapability
      .mockResolvedValueOnce({
        ...capability(true),
        planner_notice_text: "교체 전 녹음 안내입니다.",
      })
      .mockRejectedValueOnce(new Error("latest notice unavailable"))
      .mockResolvedValueOnce({
        ...capability(true),
        planner_notice_version: "consultation-notice-v3",
        planner_notice_text: "다시 받은 최신 녹음 안내입니다.",
        retention_days: 30,
      });
    const view = render(<ConsultationRecorder customerId={31} />);
    await user.click(await screen.findByRole("button", { name: "상담 녹음" }));
    await user.click(screen.getByRole("checkbox"));

    recorderSession.current = session({
      customerId: 31,
      state: {
        kind: "error",
        elapsedSeconds: 0,
        uploadedBytes: 0,
        notice: null,
        error: "최신 안내 문구를 확인하면 녹음을 시작할 수 있어요.",
        errorCode: "recording_notice_changed",
        recording: null,
      },
    });
    view.rerender(<ConsultationRecorder customerId={31} />);

    const retry = await screen.findByRole("button", {
      name: "최신 안내 다시 불러오기",
    });
    expect(screen.queryByText("교체 전 녹음 안내입니다.")).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByRole("button", { name: "녹음 시작" })).toBeNull();
    expect(screen.queryByText(/최대 30일/)).toBeNull();

    await user.click(retry);

    expect(await screen.findByText("다시 받은 최신 녹음 안내입니다."))
      .toBeInTheDocument();
    expect(screen.queryByText("교체 전 녹음 안내입니다.")).toBeNull();
    const refreshedCheckbox = screen.getByRole("checkbox");
    expect(refreshedCheckbox).not.toBeChecked();
    await waitFor(() => expect(document.activeElement).toBe(refreshedCheckbox));
    expect(recorder.start).not.toHaveBeenCalled();
  });

  it("이전 고객의 409 상태와 늦은 재조회가 전환된 고객의 최신 안내를 가리지 않는다", async () => {
    let resolveStaleRefresh:
      | ((value: ReturnType<typeof capability>) => void)
      | undefined;
    api.getRecordingCapability
      .mockResolvedValueOnce(capability(true))
      .mockImplementationOnce(() => new Promise((resolve) => {
        resolveStaleRefresh = resolve;
      }))
      .mockResolvedValueOnce({
        ...capability(true),
        planner_notice_version: "customer-32-v3",
        planner_notice_text: "32번 고객의 현재 녹음 안내입니다.",
      });
    const view = render(<ConsultationRecorder customerId={31} />);
    await userEvent.click(await screen.findByRole("button", { name: "상담 녹음" }));

    recorderSession.current = session({
      customerId: 31,
      state: {
        kind: "error",
        elapsedSeconds: 0,
        uploadedBytes: 0,
        notice: null,
        error: "최신 안내 문구를 확인하면 녹음을 시작할 수 있어요.",
        errorCode: "recording_notice_changed",
        recording: null,
      },
    });
    view.rerender(<ConsultationRecorder customerId={31} />);
    await waitFor(() => expect(api.getRecordingCapability).toHaveBeenCalledTimes(2));

    view.rerender(<ConsultationRecorder customerId={32} />);
    expect(await screen.findByText("32번 고객의 현재 녹음 안내입니다."))
      .toBeInTheDocument();
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    expect(screen.getByRole("button", { name: "녹음 시작" })).toBeDisabled();

    resolveStaleRefresh?.({
      ...capability(true),
      planner_notice_version: "stale-customer-31-v3",
      planner_notice_text: "31번 고객의 늦은 최신 안내입니다.",
    });
    await waitFor(() => {
      expect(screen.queryByText("31번 고객의 늦은 최신 안내입니다.")).toBeNull();
    });
    expect(screen.getByText("32번 고객의 현재 녹음 안내입니다."))
      .toBeInTheDocument();
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    expect(screen.getByRole("button", { name: "녹음 시작" })).toBeDisabled();

    api.getRecordingCapability.mockResolvedValueOnce({
      ...capability(true),
      planner_notice_version: "customer-32-v4",
      planner_notice_text: "32번 고객이 다시 받은 최신 녹음 안내입니다.",
    });
    recorderSession.current = session({
      customerId: 32,
      state: {
        kind: "error",
        elapsedSeconds: 0,
        uploadedBytes: 0,
        notice: null,
        error: "최신 안내 문구를 확인하면 녹음을 시작할 수 있어요.",
        errorCode: "recording_notice_changed",
        recording: null,
      },
    });
    view.rerender(<ConsultationRecorder customerId={32} />);

    expect(await screen.findByText("32번 고객이 다시 받은 최신 녹음 안내입니다."))
      .toBeInTheDocument();
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    expect(screen.getByRole("button", { name: "녹음 시작" })).toBeDisabled();
  });

  it("늦게 도착한 이전 고객 capability가 현재 고객 화면을 덮지 않는다", async () => {
    let resolveFirst: ((value: ReturnType<typeof capability>) => void) | undefined;
    api.getRecordingCapability
      .mockImplementationOnce(() => new Promise((resolve) => {
        resolveFirst = resolve;
      }))
      .mockResolvedValueOnce({
        ...capability(true),
        planner_notice_text: "현재 고객의 녹음 안내입니다.",
      });
    const view = render(<ConsultationRecorder customerId={31} />);
    view.rerender(<ConsultationRecorder customerId={32} />);

    await userEvent.click(await screen.findByRole("button", { name: "상담 녹음" }));
    expect(screen.getByText("현재 고객의 녹음 안내입니다.")).toBeInTheDocument();

    resolveFirst?.({
      ...capability(true),
      planner_notice_text: "이전 고객의 늦은 녹음 안내입니다.",
    });
    await waitFor(() => {
      expect(screen.queryByText("이전 고객의 늦은 녹음 안내입니다.")).toBeNull();
    });
  });

  it("시작 요청 중 화면을 떠나면 해당 시도의 업로드 신호를 취소한다", async () => {
    const user = userEvent.setup();
    let startSignal: AbortSignal | undefined;
    recorder.start.mockImplementation(async (
      _customerId: number,
      options: { signal?: AbortSignal },
    ) => {
      startSignal = options.signal;
      await new Promise(() => undefined);
    });
    const view = render(<ConsultationRecorder customerId={31} />);
    await user.click(await screen.findByRole("button", { name: "상담 녹음" }));
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "녹음 시작" }));
    expect(startSignal?.aborted).toBe(false);

    view.unmount();

    expect(startSignal?.aborted).toBe(true);
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

  it("녹음이 아직 없으면 원본과 상담 메모를 확인할 다음 흐름을 안내한다", async () => {
    api.listConsultationRecordings.mockResolvedValue(recordings());

    render(<ConsultationRecordingList customerId={31} />);

    expect(await screen.findByText(
      "녹음을 마치면 이곳에서 원본과 상담 메모를 함께 확인할 수 있어요.",
    )).toBeInTheDocument();
  });

  it("확인 뒤 녹음별 OpenAI 요약을 정확히 한 번 요청한다", async () => {
    api.listConsultationRecordings.mockResolvedValue(recordings([recording()]));
    api.summarizeConsultationRecording.mockResolvedValue({
      id: "00000000-0000-4000-8000-000000000888",
      status: "queued",
      provider: "openai",
      memo_id: null,
      created_at: "2026-07-26T01:02:00Z",
      completed_at: null,
    });

    render(<ConsultationRecordingList customerId={31} />);
    await userEvent.click(await screen.findByRole("button", {
      name: "OpenAI로 핵심 메모 만들기",
    }));
    expect(screen.getByText(/한 번만 만들 수 있어요/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "OpenAI로 한 번 요약하기" }));

    expect(api.summarizeConsultationRecording).toHaveBeenCalledOnce();
    expect(api.summarizeConsultationRecording).toHaveBeenCalledWith(
      31,
      "00000000-0000-4000-8000-000000000032",
      "00000000-0000-4000-8000-000000000777",
    );
    expect(await screen.findByText("상담 핵심을 정리하고 있어요.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "OpenAI로 핵심 메모 만들기" })).toBeNull();
  });

  it("ready와 completed 원본만 다운로드할 수 있고 그 밖의 상태는 숨긴다", async () => {
    api.listConsultationRecordings.mockResolvedValue(recordings([
      recording({ id: "ready", status: "ready" }),
      recording({ id: "completed", status: "completed" }),
      recording({ id: "processing", status: "processing" }),
      recording({ id: "missing", status: "ready", source_available: false }),
    ]));

    render(<ConsultationRecordingList customerId={31} />);

    expect(await screen.findAllByRole("button", { name: "원본 녹음 다운로드" }))
      .toHaveLength(2);
  });

  it("다운로드는 한 번만 요청하고 서명 URL을 저장하거나 기록하지 않고 안전하게 연다", async () => {
    const user = userEvent.setup();
    let resolveDownload: ((value: { url: string; expires_in_seconds: number }) => void) | undefined;
    api.listConsultationRecordings.mockResolvedValue(recordings([recording()]));
    api.getRecordingDownloadUrl.mockImplementation(() => new Promise((resolve) => {
      resolveDownload = resolve;
    }));
    let openedUrl = "";
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(function capture(this: HTMLAnchorElement) {
        openedUrl = this.href;
      });
    const log = vi.spyOn(console, "log").mockImplementation(() => undefined);
    const store = vi.spyOn(Storage.prototype, "setItem");
    render(<ConsultationRecordingList customerId={31} />);

    const download = await screen.findByRole("button", { name: "원본 녹음 다운로드" });
    await user.click(download);
    await user.click(download);
    expect(api.getRecordingDownloadUrl).toHaveBeenCalledOnce();
    expect(download).toBeDisabled();
    expect(download).toHaveTextContent("다운로드 연결 중");

    const signedUrl = "https://download.example/task9-success-signed-sentinel";
    resolveDownload?.({
      url: signedUrl,
      expires_in_seconds: 300,
    });
    expect(await screen.findByText("다운로드를 시작했어요.")).toBeInTheDocument();
    expect(click).toHaveBeenCalledOnce();
    expect(openedUrl).toBe(signedUrl);
    expect(document.body.querySelector(
      'a[href*="task9-success-signed-sentinel"]',
    )).toBeNull();
    expect(document.body.innerHTML).not.toContain(
      "task9-success-signed-sentinel",
    );
    expect(log).not.toHaveBeenCalled();
    expect(store).not.toHaveBeenCalled();
  });

  it("다운로드 click이 실패해도 서명 URL을 DOM에서 지우고 재시도 행동을 유지한다", async () => {
    const user = userEvent.setup();
    const signedUrl = "https://download.example/task9-throw-signed-sentinel";
    api.listConsultationRecordings.mockResolvedValue(recordings([recording()]));
    api.getRecordingDownloadUrl.mockResolvedValue({
      url: signedUrl,
      expires_in_seconds: 300,
    });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {
        throw new Error("browser download unavailable");
      });
    const log = vi.spyOn(console, "log").mockImplementation(() => undefined);
    const store = vi.spyOn(Storage.prototype, "setItem");
    render(<ConsultationRecordingList customerId={31} />);

    const download = await screen.findByRole("button", {
      name: "원본 녹음 다운로드",
    });
    await user.click(download);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "다운로드 주소를 다시 받으면 원본을 내려받을 수 있어요.",
    );
    expect(download).toBeEnabled();
    expect(click).toHaveBeenCalledOnce();
    expect(document.body.querySelector(
      'a[href*="task9-throw-signed-sentinel"]',
    )).toBeNull();
    expect(document.body.innerHTML).not.toContain(
      "task9-throw-signed-sentinel",
    );
    expect(log).not.toHaveBeenCalled();
    expect(store).not.toHaveBeenCalled();
  });

  it("410은 다운로드를 숨기고 지정된 메모 안내만 보여준다", async () => {
    const user = userEvent.setup();
    api.listConsultationRecordings.mockResolvedValue(recordings([recording()]));
    api.getRecordingDownloadUrl.mockRejectedValue(new ApiError(
      410,
      "recording_download_unavailable",
      "고객 동의를 다시 확인하면 원본을 내려받을 수 있어요.",
    ));
    render(<ConsultationRecordingList customerId={31} />);

    await user.click(await screen.findByRole("button", {
      name: "원본 녹음 다운로드",
    }));

    const unavailable = await screen.findByText(
      "녹음이 정리되어 상담 메모를 확인할 수 있어요",
    );
    expect(unavailable).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "원본 녹음 다운로드" })).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(unavailable));
  });

  it("503은 서버의 다음 행동을 알리고 다운로드 재시도를 유지한다", async () => {
    const user = userEvent.setup();
    api.listConsultationRecordings.mockResolvedValue(recordings([recording()]));
    api.getRecordingDownloadUrl.mockRejectedValue(new ApiError(
      503,
      "recording_download_retry",
      "잠시 후 다시 누르면 원본을 내려받을 수 있어요.",
    ));
    render(<ConsultationRecordingList customerId={31} />);

    const download = await screen.findByRole("button", { name: "원본 녹음 다운로드" });
    await user.click(download);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "잠시 후 다시 누르면 원본을 내려받을 수 있어요.",
    );
    expect(download).toBeEnabled();
    await user.click(download);
    expect(api.getRecordingDownloadUrl).toHaveBeenCalledTimes(2);
  });

  it("재생 컨트롤은 다운로드 차단 속성 없이 계속 사용할 수 있다", async () => {
    const user = userEvent.setup();
    api.listConsultationRecordings.mockResolvedValue(recordings([recording()]));
    api.getRecordingPlayUrl.mockResolvedValue({
      url: "https://play.example/private-signed-value",
      expires_in_seconds: 300,
    });
    const view = render(<ConsultationRecordingList customerId={31} />);

    await user.click(await screen.findByRole("button", { name: "녹음 듣기" }));
    const audio = view.container.querySelector("audio");
    expect(audio).not.toBeNull();
    expect(audio).toHaveAttribute("controls");
    expect(audio).not.toHaveAttribute("controlsList");
  });

  it("목록은 새 원본의 서버 보관기간과 기존 녹음의 개별 만료 시각을 구분한다", async () => {
    api.listConsultationRecordings.mockResolvedValue(recordings([recording()]));
    render(<ConsultationRecordingList customerId={31} />);

    expect(await screen.findByText("새 원본은 최대 30일 보관")).toBeInTheDocument();
    expect(screen.getByText(/2026\. 8\. 25\..*까지 보관 후 자동 삭제/))
      .toBeInTheDocument();
  });

  it("목록 capability를 받지 못하면 보관일을 추정하지 않고 재확인을 제공한다", async () => {
    const user = userEvent.setup();
    api.listConsultationRecordings.mockResolvedValue(recordings([recording()]));
    api.getRecordingCapability
      .mockRejectedValueOnce(new Error("capability unavailable"))
      .mockResolvedValueOnce(capability(true));
    render(<ConsultationRecordingList customerId={31} />);

    const retry = await screen.findByRole("button", {
      name: "새 원본 보관 기간 다시 확인",
    });
    expect(screen.queryByText(/새 원본은 최대 \d+일 보관/)).toBeNull();
    await user.click(retry);
    expect(await screen.findByText("새 원본은 최대 30일 보관")).toBeInTheDocument();
  });
});
