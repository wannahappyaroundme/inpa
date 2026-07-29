import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AdminConsultationsPage from "@/app/admin/consultations/page";

const adminApi = vi.hoisted(() => ({
  adminAddConsultationPilot: vi.fn(),
  adminGetConsultationSettings: vi.fn(),
  adminRemoveConsultationPilot: vi.fn(),
  adminUpdateConsultationPilot: vi.fn(),
  adminUpdateConsultationSettings: vi.fn(),
}));

vi.mock("@/lib/useAdminGuard", () => ({
  useAdminGuard: () => true,
}));

vi.mock("@/lib/adminApi", () => adminApi);

const response = {
  environment_gate_open: true,
  ai_environment_gate_open: true,
  retention_days: 30,
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
    active_upload_count: 2,
    ready_source_count: 4,
    deleted_count: 9,
    overdue_source_count: 1,
    delete_failure_count: 0,
    storage_audit_available: true,
    orphan_object_count: 0,
    missing_object_count: 0,
    summary_queued_count: 1,
    summary_processing_count: 2,
    summary_success_count: 3,
    summary_failed_count: 0,
    summary_ambiguous_count: 0,
    summary_cancelled_count: 0,
    summary_processing_minutes: 42,
    summary_estimated_cost_krw: 1200,
    summary_p50_seconds: 18,
    summary_p95_seconds: 55,
    recent_summary_runs: [],
    pilot_recent_summary_runs: [],
  },
  pilot_users: [],
};

describe("상담 녹음 관리자 화면", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    adminApi.adminGetConsultationSettings.mockResolvedValue(response);
    adminApi.adminUpdateConsultationSettings.mockResolvedValue({
      ...response,
      settings: { ...response.settings, recording_enabled: true },
    });
  });

  it("원음이나 고객 정보 없이 운영 수치와 다음 행동을 보여준다", async () => {
    render(<AdminConsultationsPage />);

    expect(await screen.findByText("상담 녹음 운영")).toBeInTheDocument();
    expect(screen.getByText("진행 중 업로드")).toBeInTheDocument();
    expect(screen.getByText("만료 시각 지난 원본")).toBeInTheDocument();
    expect(screen.getAllByText("1").length).toBeGreaterThan(0);
    expect(screen.queryByText(/재생/)).not.toBeInTheDocument();
    expect(screen.queryByText(/고객명/)).not.toBeInTheDocument();
    expect(screen.getByText("30일 이내 자동 삭제 대상")).toBeInTheDocument();
  });

  it("서버 보관기간이 없으면 숫자를 추정하지 않고 운영 상태 재확인을 제공한다", async () => {
    const { retention_days: _missing, ...withoutRetention } = response;
    adminApi.adminGetConsultationSettings.mockResolvedValue(withoutRetention);
    render(<AdminConsultationsPage />);

    const retry = await screen.findByRole("button", {
      name: "보관 기간 다시 불러오기",
    });
    expect(screen.queryByText(/7일 이내|30일 이내/)).toBeNull();
    fireEvent.click(retry);
    await waitFor(() => {
      expect(adminApi.adminGetConsultationSettings).toHaveBeenCalledTimes(2);
    });
  });

  it("운영 스위치를 저장하고 새 상태를 반영한다", async () => {
    render(<AdminConsultationsPage />);
    await screen.findByText("상담 녹음 운영");

    fireEvent.click(screen.getByRole("button", { name: "녹음 기능 켜기" }));

    await waitFor(() => {
      expect(adminApi.adminUpdateConsultationSettings).toHaveBeenCalledWith({
        recording_enabled: true,
      });
    });
    expect(await screen.findByText("녹음 기능을 켰어요.")).toBeInTheDocument();
  });

  it("AI 요약 스위치와 내용 없는 처리 지표를 관리한다", async () => {
    adminApi.adminUpdateConsultationSettings.mockResolvedValue({
      ...response,
      settings: { ...response.settings, ai_summary_enabled: true },
    });
    render(<AdminConsultationsPage />);
    await screen.findByText("상담 녹음 운영");

    expect(screen.getByText("AI 요약 처리 상태")).toBeInTheDocument();
    expect(screen.getByText("메모 생성 완료")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "AI 요약 기능 켜기" }));

    await waitFor(() => {
      expect(adminApi.adminUpdateConsultationSettings).toHaveBeenCalledWith({
        ai_summary_enabled: true,
      });
    });
  });

  it("백엔드가 먼저 교체되는 동안 이전 작업 응답도 안전하게 표시한다", async () => {
    const { pilot_recent_summary_runs: _pilot, ...legacyStatus } = response.status;
    adminApi.adminGetConsultationSettings.mockResolvedValue({
      ...response,
      status: {
        ...legacyStatus,
        recent_summary_runs: [{
          id: "12345678-0000-4000-8000-000000000001",
          status: "succeeded",
          processing_minutes_reserved: 1,
          input_tokens: 10,
          output_tokens: 5,
          estimated_cost_krw: 3,
          outcome: "succeeded",
          error_code: "",
          created_at: "2026-07-29T09:00:00Z",
          completed_at: "2026-07-29T09:00:10Z",
        }],
      },
    });

    render(<AdminConsultationsPage />);

    expect(await screen.findByText("12345678")).toBeInTheDocument();
    expect(screen.getByText("0초")).toBeInTheDocument();
  });
});
