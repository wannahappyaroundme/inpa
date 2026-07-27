import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AdminConsultationComparisonPage from "@/app/admin/consultations/compare/page";
import AdminConsultationsPage from "@/app/admin/consultations/page";
import { ApiError, tokenStore } from "@/lib/api";
import * as adminApi from "@/lib/adminApi";

vi.mock("@/lib/useAdminGuard", () => ({
  useAdminGuard: () => true,
}));

const successResponse: adminApi.AdminConsultationComparisonResponse = {
  transcript: {
    segments: [
      {
        speaker: "화자 1",
        text: "가상 상담 내용입니다.",
        start_seconds: null,
        end_seconds: null,
      },
    ],
  },
  results: [
    {
      slot: "A",
      provider: "openai",
      model: "env-openai-summary",
      status: "success",
      summary: {
        consultation_core: ["가입 목적과 현재 상황을 먼저 확인했어요."],
        customer_priorities: ["월 투자 범위를 중요하게 보고 있어요."],
        items_to_confirm: ["기존 계약 내용을 확인해요."],
        next_actions: ["자료를 받은 뒤 다음 상담을 잡아요."],
      },
      latency_ms: 1200,
      input_tokens: 240,
      output_tokens: 80,
      error_code: "",
    },
    {
      slot: "B",
      provider: "anthropic",
      model: "env-anthropic-summary",
      status: "success",
      summary: {
        consultation_core: ["두 번째 상담 핵심"],
        customer_priorities: ["두 번째 고객 우선순위"],
        items_to_confirm: ["두 번째 확인할 내용"],
        next_actions: ["두 번째 다음 할 일"],
      },
      latency_ms: 1500,
      input_tokens: 260,
      output_tokens: 90,
      error_code: "",
    },
  ],
};

const partialFailureResponse: adminApi.AdminConsultationComparisonResponse = {
  ...successResponse,
  results: [
    successResponse.results[0],
    {
      slot: "B",
      provider: "anthropic",
      model: "",
      status: "failed",
      summary: null,
      latency_ms: 0,
      input_tokens: 0,
      output_tokens: 0,
      error_code: "SUMMARY_FAILED",
    },
  ],
};

const allFailureResponse: adminApi.AdminConsultationComparisonResponse = {
  ...successResponse,
  results: [
    {
      slot: "A",
      provider: "openai",
      model: "",
      status: "outcome_unknown",
      summary: null,
      latency_ms: 0,
      input_tokens: 0,
      output_tokens: 0,
      error_code: "SUMMARY_TIMEOUT",
    },
    {
      slot: "B",
      provider: "anthropic",
      model: "",
      status: "failed",
      summary: null,
      latency_ms: 0,
      input_tokens: 0,
      output_tokens: 0,
      error_code: "SUMMARY_FAILED",
    },
  ],
};

const emptySummaryResponse: adminApi.AdminConsultationComparisonResponse = {
  ...successResponse,
  results: [
    {
      ...successResponse.results[0],
      summary: {
        consultation_core: [],
        customer_priorities: [],
        items_to_confirm: [],
        next_actions: [],
      },
    },
    successResponse.results[1],
  ],
};

function selectValidFileAndConfirm(
  file = new File(["audio"], "synthetic.webm", { type: "audio/webm" }),
) {
  fireEvent.change(screen.getByLabelText("가상 상담 음성"), {
    target: { files: [file] },
  });
  fireEvent.click(screen.getByLabelText("가상 녹음 확인"));
}

describe("상담 AI 블라인드 비교 화면", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    tokenStore.remove();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("확인 전에는 비교를 시작하지 않고 다음 행동을 안내한다", async () => {
    const compare = vi.spyOn(adminApi, "adminCompareConsultation");
    render(<AdminConsultationComparisonPage />);
    fireEvent.change(screen.getByLabelText("가상 상담 음성"), {
      target: {
        files: [
          new File(["audio"], "synthetic.webm", { type: "audio/webm" }),
        ],
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "비교 시작" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "가상 녹음 확인을 선택해 주세요",
    );
    expect(compare).not.toHaveBeenCalled();
  });

  it("A/B 결과는 평가 전 모델명을 가리고 선택 뒤 공개한다", async () => {
    vi.spyOn(adminApi, "adminCompareConsultation").mockResolvedValue(
      successResponse,
    );
    render(<AdminConsultationComparisonPage />);
    selectValidFileAndConfirm();
    fireEvent.click(screen.getByRole("button", { name: "비교 시작" }));

    expect(await screen.findByText("결과 A")).toBeInTheDocument();
    expect(screen.getByText("결과 B")).toBeInTheDocument();
    expect(screen.queryByText("env-openai-summary")).not.toBeInTheDocument();
    expect(screen.queryByText("openai")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "모델명 보기" })).toBeDisabled();

    fireEvent.click(screen.getByLabelText("A 우세"));
    fireEvent.click(screen.getByRole("button", { name: "모델명 보기" }));

    expect(screen.getByText("env-openai-summary")).toBeInTheDocument();
    expect(screen.getByText("env-anthropic-summary")).toBeInTheDocument();
    expect(screen.getByText("1,200ms")).toBeInTheDocument();
    expect(screen.getByText("240 / 80")).toBeInTheDocument();
  });

  it("한쪽 실패에도 성공 결과와 공통 전사문을 유지한다", async () => {
    vi.spyOn(adminApi, "adminCompareConsultation").mockResolvedValue(
      partialFailureResponse,
    );
    render(<AdminConsultationComparisonPage />);
    selectValidFileAndConfirm();
    fireEvent.click(screen.getByRole("button", { name: "비교 시작" }));

    expect(await screen.findByText("상담 핵심")).toBeInTheDocument();
    expect(
      screen.getByText("한쪽 결과를 다시 확인해 주세요."),
    ).toBeInTheDocument();
    expect(screen.queryByText("SUMMARY_FAILED")).not.toBeInTheDocument();
    const resultA = screen.getByRole("article", { name: "결과 A" });
    const resultB = screen.getByRole("article", { name: "결과 B" });
    expect(within(resultA).getAllByRole("checkbox")).toHaveLength(5);
    expect(within(resultB).queryAllByRole("checkbox")).toHaveLength(0);
    expect(
      within(resultB).getByText(
        "성공한 결과와 공통 전사문을 평가해 주세요.",
      ),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("radio")).toHaveLength(2);
    expect(screen.getByLabelText("A 우세")).toBeInTheDocument();
    expect(screen.getByLabelText("판단 보류")).toBeInTheDocument();
    expect(screen.queryByLabelText("B 우세")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("동률")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("공통 전사문 보기"));
    expect(screen.getByText(/화자 1/)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("A 우세"));
    fireEvent.click(screen.getByRole("button", { name: "모델명 보기" }));
    expect(screen.getByText("env-openai-summary")).toBeInTheDocument();
  });

  it("두 요약이 모두 실패하면 다시 시작 안내만 보여준다", async () => {
    vi.spyOn(adminApi, "adminCompareConsultation").mockResolvedValue(
      allFailureResponse,
    );
    render(<AdminConsultationComparisonPage />);
    selectValidFileAndConfirm();
    fireEvent.click(screen.getByRole("button", { name: "비교 시작" }));

    expect(
      await screen.findByRole("alert", {
        name: "두 결과를 확인하지 못했어요",
      }),
    ).toHaveTextContent(
      "선택한 음성은 그대로 두었어요. 비교 시작을 다시 눌러 주세요.",
    );
    expect(screen.queryAllByRole("article")).toHaveLength(0);
    expect(
      screen.queryByRole("group", { name: "최종 선택" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "모델명 보기" }),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("가상 녹음 확인")).toBeChecked();
    expect(screen.getByRole("button", { name: "비교 시작" })).toBeEnabled();
  });

  it("요약 구역이 비어 있으면 확인된 내용이 없다고 보여준다", async () => {
    vi.spyOn(adminApi, "adminCompareConsultation").mockResolvedValue(
      emptySummaryResponse,
    );
    render(<AdminConsultationComparisonPage />);
    selectValidFileAndConfirm();
    fireEvent.click(screen.getByRole("button", { name: "비교 시작" }));

    expect(
      await screen.findAllByText("확인된 내용 없음"),
    ).toHaveLength(4);
  });

  it("각 결과에 다섯 가지 평가 항목과 네 가지 최종 선택만 제공한다", async () => {
    vi.spyOn(adminApi, "adminCompareConsultation").mockResolvedValue(
      successResponse,
    );
    render(<AdminConsultationComparisonPage />);
    selectValidFileAndConfirm();
    fireEvent.click(screen.getByRole("button", { name: "비교 시작" }));

    const resultA = await screen.findByRole("article", { name: "결과 A" });
    const resultB = screen.getByRole("article", { name: "결과 B" });
    expect(within(resultA).getAllByRole("checkbox")).toHaveLength(5);
    expect(within(resultB).getAllByRole("checkbox")).toHaveLength(5);
    expect(within(resultA).getByLabelText("빠진 내용")).toBeInTheDocument();
    expect(
      within(resultA).getByLabelText("대화에 없는데 만든 내용"),
    ).toBeInTheDocument();
    expect(within(resultA).getByLabelText("금액·날짜 오류")).toBeInTheDocument();
    expect(within(resultA).getByLabelText("화자 구분 오류")).toBeInTheDocument();
    expect(
      within(resultA).getByLabelText("바로 메모로 사용할 수 있음"),
    ).toBeInTheDocument();
    expect(
      within(resultA).getByRole("heading", {
        name: "고객이 중요하게 본 내용",
      }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("radio")).toHaveLength(4);
    expect(screen.getByLabelText("A 우세")).toBeInTheDocument();
    expect(screen.getByLabelText("B 우세")).toBeInTheDocument();
    expect(screen.getByLabelText("동률")).toBeInTheDocument();
    expect(screen.getByLabelText("판단 보류")).toBeInTheDocument();
  });

  it("내부 검토 목적과 저장되지 않는 범위를 분명히 안내한다", () => {
    render(<AdminConsultationComparisonPage />);

    expect(
      screen.getByRole("heading", { name: "상담 AI 비교" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("가상 상담으로 요약 결과를 나란히 확인합니다."),
    ).toBeInTheDocument();
    expect(screen.getByText("내부 검토용")).toBeInTheDocument();
    expect(
      screen.getByText(
        "이 화면의 음성과 결과는 고객 메모에 저장되지 않습니다.",
      ),
    ).toBeInTheDocument();
  });

  it("선택한 파일의 이름과 크기와 지원 여부를 바로 보여준다", () => {
    render(<AdminConsultationComparisonPage />);
    const audio = new File([new Uint8Array(1024)], "synthetic.WAV", {
      type: "audio/wav",
    });

    fireEvent.change(screen.getByLabelText("가상 상담 음성"), {
      target: { files: [audio] },
    });

    expect(screen.getByText("synthetic.WAV")).toBeInTheDocument();
    expect(screen.getByText("1KB")).toBeInTheDocument();
    expect(screen.getByText("사용할 수 있는 음성 파일")).toBeInTheDocument();
  });

  it("지원하지 않는 확장자와 25MB 초과 파일은 요청 전에 안내한다", async () => {
    const compare = vi.spyOn(adminApi, "adminCompareConsultation");
    render(<AdminConsultationComparisonPage />);

    selectValidFileAndConfirm(
      new File(["audio"], "synthetic.txt", { type: "text/plain" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "비교 시작" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "지원하는 음성 파일을 선택해 주세요",
    );

    const oversized = new File(["audio"], "synthetic.wav", {
      type: "audio/wav",
    });
    Object.defineProperty(oversized, "size", { value: 26214401 });
    fireEvent.change(screen.getByLabelText("가상 상담 음성"), {
      target: { files: [oversized] },
    });
    fireEvent.click(screen.getByLabelText("가상 녹음 확인"));
    fireEvent.click(screen.getByRole("button", { name: "비교 시작" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "25MB 이하 음성 파일을 선택해 주세요",
    );
    expect(compare).not.toHaveBeenCalled();
  });

  it("진행 중에는 중복 제출을 막고 세 단계 안내를 시간에 맞춰 바꾼다", async () => {
    vi.useFakeTimers();
    let resolveComparison:
      | ((value: typeof successResponse) => void)
      | undefined;
    const comparison = new Promise<typeof successResponse>((resolve) => {
      resolveComparison = resolve;
    });
    const compare = vi
      .spyOn(adminApi, "adminCompareConsultation")
      .mockReturnValue(comparison);
    render(<AdminConsultationComparisonPage />);
    selectValidFileAndConfirm();
    const submit = screen.getByRole("button", { name: "비교 시작" });

    fireEvent.click(submit);
    fireEvent.click(submit);
    expect(compare).toHaveBeenCalledTimes(1);
    expect(
      screen.getByText("음성을 글로 바꾸고 있어요"),
    ).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(8000);
    });
    expect(
      screen.getByText("두 가지 요약을 만들고 있어요"),
    ).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(17000);
    });
    expect(
      screen.getByText(
        "결과를 정리하고 있어요. 화면을 그대로 두면 이어집니다.",
      ),
    ).toBeInTheDocument();

    await act(async () => {
      resolveComparison?.(successResponse);
      await comparison;
    });
    expect(screen.getByText("결과 A")).toBeInTheDocument();
  });

  it("응답이 일찍 끝나면 남은 진행 안내 타이머를 정리한다", async () => {
    vi.useFakeTimers();
    let resolveComparison:
      | ((value: typeof successResponse) => void)
      | undefined;
    const comparison = new Promise<typeof successResponse>((resolve) => {
      resolveComparison = resolve;
    });
    vi.spyOn(adminApi, "adminCompareConsultation").mockReturnValue(comparison);
    render(<AdminConsultationComparisonPage />);
    selectValidFileAndConfirm();
    const timersBeforeSubmit = vi.getTimerCount();

    fireEvent.click(screen.getByRole("button", { name: "비교 시작" }));
    expect(vi.getTimerCount()).toBe(timersBeforeSubmit + 2);

    await act(async () => {
      resolveComparison?.(successResponse);
      await comparison;
    });

    expect(screen.getByText("결과 A")).toBeInTheDocument();
    expect(vi.getTimerCount()).toBe(timersBeforeSubmit);
  });

  it("화면을 나가면 진행 안내 타이머를 정리한다", () => {
    vi.useFakeTimers();
    vi.spyOn(adminApi, "adminCompareConsultation").mockReturnValue(
      new Promise(() => undefined),
    );
    const { unmount } = render(<AdminConsultationComparisonPage />);
    selectValidFileAndConfirm();
    const timersBeforeSubmit = vi.getTimerCount();

    fireEvent.click(screen.getByRole("button", { name: "비교 시작" }));
    expect(vi.getTimerCount()).toBe(timersBeforeSubmit + 2);

    unmount();

    expect(vi.getTimerCount()).toBe(0);
  });

  it("최종 선택을 바꾸거나 새 파일을 고르면 모델 정보를 다시 가린다", async () => {
    vi.spyOn(adminApi, "adminCompareConsultation").mockResolvedValue(
      successResponse,
    );
    render(<AdminConsultationComparisonPage />);
    selectValidFileAndConfirm();
    fireEvent.click(screen.getByRole("button", { name: "비교 시작" }));
    await screen.findByText("결과 A");

    fireEvent.click(screen.getByLabelText("A 우세"));
    fireEvent.click(screen.getByRole("button", { name: "모델명 보기" }));
    expect(screen.getByText("env-openai-summary")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("B 우세"));
    expect(screen.queryByText("env-openai-summary")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "모델명 보기" }));
    expect(screen.getByText("env-openai-summary")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("가상 상담 음성"), {
      target: {
        files: [
          new File(["new audio"], "synthetic-2.wav", {
            type: "audio/wav",
          }),
        ],
      },
    });

    expect(screen.queryByText("env-openai-summary")).not.toBeInTheDocument();
    expect(screen.queryByText("결과 A")).not.toBeInTheDocument();
  });

  it("전체 요청이 실패해도 선택과 확인을 유지해 다시 시작할 수 있다", async () => {
    const compare = vi
      .spyOn(adminApi, "adminCompareConsultation")
      .mockRejectedValueOnce(new Error("private provider detail"))
      .mockResolvedValueOnce(successResponse);
    render(<AdminConsultationComparisonPage />);
    selectValidFileAndConfirm();

    fireEvent.click(screen.getByRole("button", { name: "비교 시작" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "음성 파일은 그대로 두었어요",
    );
    expect(screen.getByLabelText("가상 녹음 확인")).toBeChecked();
    expect(screen.queryByText("private provider detail")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "비교 시작" }));
    expect(await screen.findByText("결과 A")).toBeInTheDocument();
    expect(compare).toHaveBeenCalledTimes(2);
  });

  it.each([
    [
      403,
      "CONSULTATION_COMPARISON_CLOSED",
      "내부 비교 설정을 켜면 바로 확인할 수 있어요.",
    ],
    [
      503,
      "CONSULTATION_COMPARISON_NOT_READY",
      "두 AI 연결 설정을 마치면 비교를 시작할 수 있어요.",
    ],
    [
      400,
      "SYNTHETIC_CONFIRMATION_REQUIRED",
      "가상 녹음 확인을 선택하면 바로 비교할 수 있어요.",
    ],
    [
      400,
      "AUDIO_EMPTY",
      "내용이 담긴 음성 파일을 선택하면 바로 비교할 수 있어요.",
    ],
    [
      400,
      "AUDIO_FORMAT_UNSUPPORTED",
      "지원하는 음성 파일을 선택하면 바로 비교할 수 있어요.",
    ],
    [
      400,
      "AUDIO_INVALID",
      "재생되는 음성 파일을 선택하면 바로 비교할 수 있어요.",
    ],
    [
      400,
      "AUDIO_ONLY_REQUIRED",
      "영상 없이 음성만 담긴 파일을 선택하면 바로 비교할 수 있어요.",
    ],
    [
      400,
      "AUDIO_TOO_LARGE",
      "25MB 이하 음성 파일을 선택하면 바로 비교할 수 있어요.",
    ],
    [
      400,
      "AUDIO_TOO_LONG",
      "5분 이하 가상 상담 음성을 선택하면 바로 비교할 수 있어요.",
    ],
  ])(
    "%s %s 응답은 서버 문구 대신 정해진 다음 행동을 보여준다",
    async (status, code, expectedMessage) => {
      vi.spyOn(adminApi, "adminCompareConsultation").mockRejectedValue(
        new ApiError(status, code, "private backend detail"),
      );
      render(<AdminConsultationComparisonPage />);
      selectValidFileAndConfirm();

      fireEvent.click(screen.getByRole("button", { name: "비교 시작" }));

      expect(await screen.findByRole("alert")).toHaveTextContent(
        expectedMessage,
      );
      expect(screen.queryByText("private backend detail")).not.toBeInTheDocument();
      expect(screen.queryByText(code)).not.toBeInTheDocument();
      expect(screen.getByLabelText("가상 녹음 확인")).toBeChecked();
    },
  );
});

describe("상담 녹음 운영 화면의 비교 진입점", () => {
  it("상담 AI 비교 화면으로 이동할 수 있다", async () => {
    vi.spyOn(adminApi, "adminGetConsultationSettings").mockResolvedValue({
      environment_gate_open: true,
      ai_environment_gate_open: true,
      settings: {
        recording_enabled: false,
        ai_summary_enabled: false,
        max_duration_seconds: 3600,
        max_bytes: 104857600,
        global_active_limit: 20,
        daily_ai_cost_limit_krw: 50000,
        monthly_ai_cost_limit_krw: 500000,
        updated_at: "2026-07-26T12:00:00Z",
      },
      status: {
        active_upload_count: 0,
        ready_source_count: 0,
        deleted_count: 0,
        overdue_source_count: 0,
        delete_failure_count: 0,
        storage_audit_available: true,
        orphan_object_count: 0,
        missing_object_count: 0,
        summary_queued_count: 0,
        summary_processing_count: 0,
        summary_success_count: 0,
        summary_failed_count: 0,
        summary_ambiguous_count: 0,
        summary_cancelled_count: 0,
        summary_processing_minutes: 0,
        summary_estimated_cost_krw: 0,
        summary_p50_seconds: null,
        summary_p95_seconds: null,
        recent_summary_runs: [],
      },
      pilot_users: [],
    });
    render(<AdminConsultationsPage />);

    const link = await screen.findByRole("link", { name: "상담 AI 비교" });
    expect(link).toHaveAttribute("href", "/admin/consultations/compare");
  });
});

describe("상담 AI 비교 관리자 API", () => {
  beforeEach(() => {
    tokenStore.remove();
  });

  it("multipart 경계를 브라우저에 맡기고 음성과 가상 확인을 보낸다", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(successResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetch);
    tokenStore.set("admin-token");
    const audio = new File(["audio"], "synthetic.webm", {
      type: "audio/webm",
    });

    await adminApi.adminCompareConsultation(audio, true);

    expect(fetch).toHaveBeenCalledTimes(1);
    const [url, init] = fetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      "http://localhost:8000/api/v1/admin/consultations/comparison/",
    );
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    const body = init.body as FormData;
    expect(body.get("audio")).toBe(audio);
    expect(body.get("synthetic_confirmed")).toBe("true");
    expect(init.headers).toEqual({ Authorization: "Token admin-token" });
    expect(
      Object.keys(init.headers as Record<string, string>).some(
        (name) => name.toLowerCase() === "content-type",
      ),
    ).toBe(false);
  });
});
