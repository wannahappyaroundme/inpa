import type { ProfileResponse, ProfileUpdatePayload } from "@/lib/api";

export interface BookingSettingsDraft {
  name: string;
  affiliation: string;
  title: string;
  template: string;
  location: string;
  duration: number;
  buffer: number;
}

export function profileToBookingSettings(profile: ProfileResponse): BookingSettingsDraft {
  return {
    name: profile.name ?? "",
    affiliation: profile.affiliation ?? "",
    title: profile.title ?? "",
    template: profile.booking_msg_template ?? "",
    location: profile.booking_location ?? "",
    duration: profile.booking_default_duration,
    buffer: profile.booking_buffer_min,
  };
}

export function bookingSettingsPayload(draft: BookingSettingsDraft): ProfileUpdatePayload {
  return {
    name: draft.name.trim(),
    affiliation: draft.affiliation.trim(),
    title: draft.title.trim(),
    booking_msg_template: draft.template,
    booking_location: draft.location.trim(),
    booking_default_duration: draft.duration,
    booking_buffer_min: draft.buffer,
  };
}

export function isSameBookingSettings(
  left: BookingSettingsDraft,
  right: BookingSettingsDraft,
): boolean {
  const leftPayload = bookingSettingsPayload(left);
  const rightPayload = bookingSettingsPayload(right);

  return leftPayload.name === rightPayload.name
    && leftPayload.affiliation === rightPayload.affiliation
    && leftPayload.title === rightPayload.title
    && leftPayload.booking_msg_template === rightPayload.booking_msg_template
    && leftPayload.booking_location === rightPayload.booking_location
    && leftPayload.booking_default_duration === rightPayload.booking_default_duration
    && leftPayload.booking_buffer_min === rightPayload.booking_buffer_min;
}
