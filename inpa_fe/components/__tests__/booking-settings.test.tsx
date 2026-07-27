import { describe, expect, it } from "vitest";
import type { ProfileResponse } from "@/lib/api";
import {
  bookingSettingsPayload,
  isSameBookingSettings,
  profileToBookingSettings,
  type BookingSettingsDraft,
} from "@/lib/booking-settings-state";

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
