import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AccountSettingsPage from "@/app/settings/account/page";
import { ApiError, getProfile, updateProfile, uploadProfileImage, type ProfileResponse } from "@/lib/api";

const authState = vi.hoisted(() => ({ ready: true }));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/components/app-nav", () => ({ AppNav: () => null }));
vi.mock("@/components/account-security", () => ({ AccountSecurity: () => null }));
vi.mock("@/components/manager-switch-confirm-modal", () => ({ ManagerSwitchConfirmModal: () => null }));
vi.mock("@/lib/useAuthGuard", () => ({ useAuthGuard: () => authState.ready }));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()), getProfile: vi.fn(), updateProfile: vi.fn(), uploadProfileImage: vi.fn(),
}));

const mockedGetProfile = vi.mocked(getProfile);
const mockedUpdateProfile = vi.mocked(updateProfile);
const mockedUploadProfileImage = vi.mocked(uploadProfileImage);
const profile = (overrides: Partial<ProfileResponse> = {}): ProfileResponse => ({
  email: "planner@test.com", name: "황예진", phone: "010-0000-0000", affiliation: "인파", agent_type: null, affiliation_type: null,
  cohort_opt_in: false, manager_share_opt_in: false, manager_share_level: "none", manager_email: null, is_manager: false,
  manager_promoted_at: null, manager_promotion_seen_at: null, managed_agents_count: 0, recruiting_enabled: true,
  license_self_declared: false, license_no: null, career_years: null, booking_msg_template: "", booking_location: "", booking_default_duration: 30,
  booking_buffer_min: 60, title: "FC", intro_text: "", profile_image: null, google_calendar_connected: false,
  google_calendar_mask_name: false, has_usable_password: true, onboarding_completed_at: null, tour_completed_at: null,
  marketing_agreed_at: null, ref_code: null, email_verified_at: null, is_admin: false, is_dormant: false, ...overrides,
});

describe("기본 프로필 저장 결과", () => {
  beforeEach(() => {
    authState.ready = true;
    mockedGetProfile.mockReset();
    mockedGetProfile.mockResolvedValue(profile());
    mockedUpdateProfile.mockReset();
    mockedUploadProfileImage.mockReset();
  });
  afterEach(() => vi.restoreAllMocks());

  async function save() {
    const user = userEvent.setup(); render(<AccountSettingsPage />);
    await screen.findByDisplayValue("황예진");
    await user.click(screen.getAllByRole("button", { name: "저장" })[0]);
  }

  it("프로필을 불러오는 동안 현재 상태를 알린다", () => {
    mockedGetProfile.mockImplementation(() => new Promise(() => undefined));

    render(<AccountSettingsPage />);

    expect(screen.getByRole("status")).toHaveTextContent("계정 설정을 불러오는 중");
  });

  it("첫 조회가 실패해도 다시 불러와 같은 화면에서 복구한다", async () => {
    const user = userEvent.setup();
    mockedGetProfile
      .mockRejectedValueOnce(new Error("temporary"))
      .mockResolvedValueOnce(profile({ name: "다시 불러온 설계사" }));

    render(<AccountSettingsPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "계정 설정을 다시 불러오면 이어서 입력할 수 있어요.",
    );
    await user.click(screen.getByRole("button", { name: "다시 불러오기" }));
    expect(await screen.findByDisplayValue("다시 불러온 설계사")).toBeInTheDocument();
    expect(mockedGetProfile).toHaveBeenCalledTimes(2);
  });

  it("인증 상태가 바뀐 뒤 늦게 도착한 이전 프로필은 최신 화면을 덮지 않는다", async () => {
    let resolveFirst: ((value: ProfileResponse) => void) | undefined;
    const firstRequest = new Promise<ProfileResponse>((resolve) => {
      resolveFirst = resolve;
    });
    mockedGetProfile
      .mockReturnValueOnce(firstRequest)
      .mockResolvedValueOnce(profile({ name: "최신 프로필" }));
    const view = render(<AccountSettingsPage />);
    await waitFor(() => expect(mockedGetProfile).toHaveBeenCalledTimes(1));

    authState.ready = false;
    view.rerender(<AccountSettingsPage />);
    expect(await screen.findByText("로그인 정보를 확인하는 중이에요.")).toBeInTheDocument();

    authState.ready = true;
    view.rerender(<AccountSettingsPage />);
    expect(await screen.findByDisplayValue("최신 프로필")).toBeInTheDocument();

    await act(async () => resolveFirst?.(profile({ name: "이전 프로필" })));
    expect(screen.getByDisplayValue("최신 프로필")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("이전 프로필")).not.toBeInTheDocument();
  });

  it("화면을 떠난 뒤 도착한 프로필 응답은 처리하지 않는다", async () => {
    let resolveProfile: ((value: ProfileResponse) => void) | undefined;
    const pendingRequest = new Promise<ProfileResponse>((resolve) => {
      resolveProfile = resolve;
    });
    const staleProfile = profile();
    const managerEmailRead = vi.fn(() => null);
    Object.defineProperty(staleProfile, "manager_email", {
      configurable: true,
      get: managerEmailRead,
    });
    mockedGetProfile.mockReturnValueOnce(pendingRequest);
    const view = render(<AccountSettingsPage />);
    await waitFor(() => expect(mockedGetProfile).toHaveBeenCalledTimes(1));

    view.unmount();
    await act(async () => resolveProfile?.(staleProfile));

    expect(managerEmailRead).not.toHaveBeenCalled();
  });

  it("성공 응답은 status로 알리고 서버가 정리한 값을 다시 입력한다", async () => {
    mockedUpdateProfile.mockResolvedValue(profile({ name: "황 예진", affiliation: "인파 GA", title: "선임 FC" }));
    await save();
    expect(await screen.findByRole("status")).toHaveTextContent("기본 프로필을 저장했어요");
    expect(screen.getByDisplayValue("황 예진")).toBeInTheDocument();
  });
  it("400 검증 실패는 error alert로 알린다", async () => {
    mockedUpdateProfile.mockRejectedValue(new ApiError(400, "invalid", "입력 내용을 확인해 주세요."));
    await save();
    expect(await screen.findByRole("alert")).toHaveTextContent("입력 내용을 확인해 주세요.");
  });
  it("네트워크 실패는 error alert로 다음 행동을 알린다", async () => {
    mockedUpdateProfile.mockRejectedValue(new Error("offline"));
    await save();
    expect(await screen.findByRole("alert")).toHaveTextContent("저장에 실패했어요. 다시 시도해 주세요.");
  });
  it("새 화면의 사진 업로드 실패는 error alert로 알린다", async () => {
    mockedUploadProfileImage.mockRejectedValue(new Error("offline"));
    render(<AccountSettingsPage />);
    const input = await screen.findByLabelText("사진 등록");
    fireEvent.change(input, { target: { files: [new File(["x"], "photo.png", { type: "image/png" })] } });
    expect(await screen.findByRole("alert")).toHaveTextContent("사진 업로드에 실패했어요. 다시 시도해 주세요.");
  });
  it("오류 뒤 사진 저장 성공은 status로 바꾼다", async () => {
    mockedUpdateProfile.mockRejectedValueOnce(new Error("offline"));
    mockedUploadProfileImage.mockResolvedValue(profile({ profile_image: "https://img.test/photo.png" }));
    await save();
    await screen.findByRole("alert");
    const input = screen.getByLabelText("사진 등록");
    fireEvent.change(input, { target: { files: [new File(["x"], "photo.png", { type: "image/png" })] } });
    expect(await screen.findByRole("status")).toHaveTextContent("프로필 사진을 저장했어요");
  });

  it("이전 성공 안내의 timer가 새 저장 오류를 지우지 않는다", async () => {
    const user = userEvent.setup();
    const nativeSetTimeout = window.setTimeout.bind(window);
    let staleCallback: (() => void) | null = null;
    const timerSpy = vi.spyOn(window, "setTimeout").mockImplementation(
      ((handler: TimerHandler, timeout?: number, ...args: unknown[]) => {
        if (timeout === 1800 && typeof handler === "function" && !staleCallback) {
          staleCallback = () => handler(...args);
          return nativeSetTimeout(() => undefined, 60_000);
        }
        return nativeSetTimeout(handler, timeout, ...args);
      }) as typeof window.setTimeout,
    );
    mockedUpdateProfile
      .mockResolvedValueOnce(profile())
      .mockRejectedValueOnce(new Error("offline"));
    render(<AccountSettingsPage />);
    await screen.findByDisplayValue("황예진");
    const saveButton = screen.getAllByRole("button", { name: "저장" })[0];

    await user.click(saveButton);
    await screen.findByRole("status");
    await user.click(saveButton);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "저장에 실패했어요. 다시 시도해 주세요.",
    );

    timerSpy.mockRestore();
    act(() => staleCallback?.());
    expect(screen.getByRole("alert")).toHaveTextContent(
      "저장에 실패했어요. 다시 시도해 주세요.",
    );
  });

  it("화면을 떠나면 성공 안내 timer를 정리한다", async () => {
    const user = userEvent.setup();
    const timerSpy = vi.spyOn(window, "setTimeout");
    const clearTimerSpy = vi.spyOn(window, "clearTimeout");
    mockedUpdateProfile.mockResolvedValue(profile());
    const view = render(<AccountSettingsPage />);
    await screen.findByDisplayValue("황예진");

    await user.click(screen.getAllByRole("button", { name: "저장" })[0]);
    await screen.findByRole("status");
    const timerIndex = timerSpy.mock.calls.findIndex(([, delay]) => delay === 1800);
    expect(timerIndex).toBeGreaterThanOrEqual(0);
    const timerId = timerSpy.mock.results[timerIndex]?.value;

    view.unmount();

    expect(clearTimerSpy).toHaveBeenCalledWith(timerId);
  });
});
