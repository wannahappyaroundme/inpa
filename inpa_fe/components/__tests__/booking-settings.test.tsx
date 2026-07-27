import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BookingSettings } from "@/components/booking-settings";
import {
  createBookingRequest, deleteWorkHour, getProfile, listCustomers, listWorkHours, updateProfile,
  type CustomerListItem, type ProfileResponse,
} from "@/lib/api";
import {
  bookingSettingsPayload,
  isSameBookingSettings,
  profileToBookingSettings,
  type BookingSettingsDraft,
} from "@/lib/booking-settings-state";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  getProfile: vi.fn(),
  updateProfile: vi.fn(),
  listWorkHours: vi.fn(),
  deleteWorkHour: vi.fn(),
  listCustomers: vi.fn(),
  createBookingRequest: vi.fn(),
}));

const mockedGetProfile = vi.mocked(getProfile);
const mockedUpdateProfile = vi.mocked(updateProfile);
const mockedListWorkHours = vi.mocked(listWorkHours);
const mockedDeleteWorkHour = vi.mocked(deleteWorkHour);
const mockedListCustomers = vi.mocked(listCustomers);
const mockedCreateBookingRequest = vi.mocked(createBookingRequest);

function profile(overrides: Partial<ProfileResponse> = {}): ProfileResponse {
  return {
    email: "planner@inpa.test",
    name: "황예진",
    phone: "010-0000-0000",
    affiliation: "인파 GA",
    agent_type: null,
    affiliation_type: null,
    cohort_opt_in: false,
    manager_share_opt_in: false,
    manager_share_level: "none",
    manager_email: null,
    is_manager: false,
    manager_promoted_at: null,
    manager_promotion_seen_at: null,
    managed_agents_count: 0,
    recruiting_enabled: true,
    license_self_declared: false,
    license_no: null,
    career_years: null,
    booking_msg_template: "",
    booking_location: "부산 서면",
    booking_default_duration: 30,
    booking_buffer_min: 60,
    title: "FC",
    intro_text: "",
    profile_image: null,
    google_calendar_connected: false,
    google_calendar_mask_name: false,
    has_usable_password: true,
    onboarding_completed_at: null,
    tour_completed_at: null,
    marketing_agreed_at: null,
    ref_code: null,
    email_verified_at: null,
    is_admin: false,
    is_dormant: false,
    ...overrides,
  };
}

function customer(overrides: Partial<CustomerListItem> = {}): CustomerListItem {
  return {
    id: 31,
    name: "최고객",
    mobile_phone_number: "01012345678",
    sales_stage: "contact",
    ...overrides,
  } as CustomerListItem;
}

describe("예약 설정 draft 상태", () => {
  it("저장 payload에서 이름·소속·직책·장소만 다듬고 문구와 숫자를 보존한다", () => {
    const draft: BookingSettingsDraft = {
      name: " 황예진 ",
      affiliation: " 부산지점 ",
      title: " FC ",
      template: "{고객명}님\n{링크}",
      location: " 서면 ",
      duration: 30,
      buffer: 60,
    };

    expect(bookingSettingsPayload(draft)).toEqual({
      name: "황예진",
      affiliation: "부산지점",
      title: "FC",
      booking_msg_template: "{고객명}님\n{링크}",
      booking_location: "서면",
      booking_default_duration: 30,
      booking_buffer_min: 60,
    });
  });

  it("예약 설정 일곱 필드가 같을 때만 깨끗한 상태로 판정한다", () => {
    const draft: BookingSettingsDraft = {
      name: "황예진",
      affiliation: "부산지점",
      title: "FC",
      template: "{고객명}님\n{링크}",
      location: "서면",
      duration: 30,
      buffer: 60,
    };

    expect(isSameBookingSettings(draft, { ...draft })).toBe(true);
    expect(isSameBookingSettings(draft, { ...draft, title: "팀장" })).toBe(false);
  });

  it("기존 프로필의 비어 있거나 null인 예약 문자열을 안전한 빈 문자열 draft로 바꾼다", () => {
    const legacyProfile = {
      ...profile(),
      affiliation: null,
      title: null,
      booking_msg_template: null,
      booking_location: null,
    } as unknown as ProfileResponse;

    expect(profileToBookingSettings(legacyProfile)).toEqual({
      name: "황예진",
      affiliation: "",
      title: "",
      template: "",
      location: "",
      duration: 30,
      buffer: 60,
    });
  });
});

describe("예약 설정 화면", () => {
  beforeEach(() => {
    mockedGetProfile.mockReset();
    mockedUpdateProfile.mockReset();
    mockedListWorkHours.mockReset();
    mockedDeleteWorkHour.mockReset();
    mockedListCustomers.mockReset();
    mockedCreateBookingRequest.mockReset();
    mockedGetProfile.mockResolvedValue(profile());
    mockedListWorkHours.mockResolvedValue({ count: 0, next: null, previous: null, results: [] });
    mockedListCustomers.mockResolvedValue({ count: 0, next: null, previous: null, results: [] });
  });

  it("프로필을 읽는 동안 저장과 안내 생성을 막고, 실패는 빈 초안 대신 다시 불러오기를 보여 준다", async () => {
    let retry = false;
    mockedGetProfile.mockImplementation(async () => {
      if (!retry) throw new Error("PROFILE_DOWN");
      return profile({ name: "다시 불러온 설계사" });
    });

    render(<BookingSettings />);
    expect(screen.getByTestId("booking-settings-skeleton")).toBeTruthy();
    expect(screen.getByRole("button", { name: "예약 설정 저장" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "고객에게 보낼 문구 만들기" })).toBeDisabled();

    expect(await screen.findByRole("alert")).toHaveTextContent("예약 설정을 불러오지 못했어요.");
    expect(mockedUpdateProfile).not.toHaveBeenCalled();
    expect(mockedCreateBookingRequest).not.toHaveBeenCalled();

    retry = true;
    await userEvent.setup().click(screen.getByRole("button", { name: "다시 불러오기" }));
    expect(await screen.findByDisplayValue("다시 불러온 설계사")).toBeTruthy();
  });

  it("바뀐 설정을 먼저 저장한 뒤 선택 고객의 실제 안내 문구를 만든다", async () => {
    mockedListCustomers.mockResolvedValue({
      count: 1, next: null, previous: null,
      results: [customer()],
    });
    mockedUpdateProfile.mockResolvedValue(profile({ name: "수정한 이름" }));
    mockedCreateBookingRequest.mockResolvedValue({
      token: "signed:31", booking_url: "https://www.inpa.kr/b/signed:31", message: "실제 고객 안내 문구",
    });
    render(<BookingSettings />);
    const user = userEvent.setup();
    await screen.findByDisplayValue("황예진");
    await user.clear(screen.getByDisplayValue("황예진"));
    await user.type(screen.getByLabelText("내 이름"), "수정한 이름");
    await user.type(screen.getByRole("combobox", { name: "고객 선택" }), "최");
    await user.click(await screen.findByRole("option", { name: /최고객/ }));
    await user.click(screen.getByRole("button", { name: "고객에게 보낼 문구 만들기" }));
    await waitFor(() => expect(mockedCreateBookingRequest).toHaveBeenCalledWith(31));
    expect(mockedUpdateProfile.mock.invocationCallOrder[0])
      .toBeLessThan(mockedCreateBookingRequest.mock.invocationCallOrder[0]);
  });

  it("깨끗한 설정은 PATCH 없이 선택한 고객에게 바로 문구를 만든다", async () => {
    mockedListCustomers.mockResolvedValue({
      count: 1, next: null, previous: null,
      results: [customer()],
    });
    mockedCreateBookingRequest.mockResolvedValue({
      token: "signed:31", booking_url: "https://www.inpa.kr/b/signed:31", message: "실제 고객 안내 문구",
    });
    render(<BookingSettings />);
    const user = userEvent.setup();
    await screen.findByDisplayValue("황예진");
    await user.type(screen.getByRole("combobox", { name: "고객 선택" }), "최");
    expect(await screen.findByRole("option", { name: /최고객/ })).toBeTruthy();
    await user.click(screen.getByRole("option", { name: /최고객/ }));
    await user.click(screen.getByRole("button", { name: "고객에게 보낼 문구 만들기" }));

    await waitFor(() => expect(mockedCreateBookingRequest).toHaveBeenCalledWith(31));
    expect(mockedUpdateProfile).not.toHaveBeenCalled();
  });

  it("저장 실패 시 입력을 보존하고 실제 안내 요청을 보내지 않는다", async () => {
    mockedListCustomers.mockResolvedValue({
      count: 1, next: null, previous: null,
      results: [customer()],
    });
    mockedUpdateProfile.mockRejectedValue(new Error("PATCH_FAILED"));
    render(<BookingSettings />);
    const user = userEvent.setup();
    await screen.findByDisplayValue("황예진");
    await user.clear(screen.getByLabelText("내 이름"));
    await user.type(screen.getByLabelText("내 이름"), "수정 중인 이름");
    await user.type(screen.getByRole("combobox", { name: "고객 선택" }), "최");
    await user.click(await screen.findByRole("option", { name: /최고객/ }));
    await user.click(screen.getByRole("button", { name: "고객에게 보낼 문구 만들기" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("예약 설정을 다시 저장해 주세요.");
    expect(screen.getByDisplayValue("수정 중인 이름")).toBeTruthy();
    expect(mockedCreateBookingRequest).not.toHaveBeenCalled();
  });

  it("가짜 고객 미리보기 대신 실제 고객 안내 영역을 표시한다", async () => {
    render(<BookingSettings />);
    await screen.findByDisplayValue("황예진");
    expect(screen.queryByText(/고객이 받는 모습/)).toBeNull();
    expect(screen.queryByText(/김보장/)).toBeNull();
    expect(screen.queryByText(/\/b\/…/)).toBeNull();
    expect(screen.getByText("고객에게 예약 안내 보내기")).toBeTruthy();
  });

  it("업무시간 조회 실패를 숨기지 않고 다시 불러올 수 있다", async () => {
    mockedListWorkHours.mockRejectedValueOnce(new Error("WORK_HOURS_DOWN"));
    render(<BookingSettings />);
    expect(await screen.findByRole("alert")).toHaveTextContent("업무시간을 불러오지 못했어요.");
    await userEvent.setup().click(screen.getByRole("button", { name: "업무시간 다시 불러오기" }));
    await waitFor(() => expect(mockedListWorkHours).toHaveBeenCalledTimes(2));
  });
});
