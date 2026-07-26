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
  settings: {
    recording_enabled: false,
    ai_summary_enabled: false,
    max_duration_seconds: 3600,
    max_bytes: 104857600,
    global_active_limit: 20,
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
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.queryByText(/재생/)).not.toBeInTheDocument();
    expect(screen.queryByText(/고객명/)).not.toBeInTheDocument();
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
});
