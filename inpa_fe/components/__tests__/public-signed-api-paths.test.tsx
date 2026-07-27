import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getBookingInfo,
  getConsentDisclosure,
  submitBooking,
  submitConsent,
} from "@/lib/api";

const SIGNED = "eyJwayI6MTI4fQ:1wo9X8:k8naBaeSr-UhWUIbw-0KvWK1c8";
const ENCODED_SIGNED = "eyJwayI6MTI4fQ%3A1wo9X8%3Ak8naBaeSr-UhWUIbw-0KvWK1c8";
const CONSENT_URL = `http://localhost:8000/api/v1/c/${ENCODED_SIGNED}/`;
const BOOKING_URL = `http://localhost:8000/api/v1/b/${ENCODED_SIGNED}/`;

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("public signed API paths", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends the raw consent token to its once-encoded GET and POST paths", async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(jsonResponse({}))
      .mockResolvedValueOnce(jsonResponse({}));
    vi.stubGlobal("fetch", fetch);

    await getConsentDisclosure(SIGNED);
    await submitConsent(SIGNED, ["personal_info"]);

    expect(fetch).toHaveBeenNthCalledWith(1, CONSENT_URL);
    expect(fetch).toHaveBeenNthCalledWith(2, CONSENT_URL, expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ agreed: ["personal_info"] }),
    }));
    expect(fetch.mock.calls.map(([url]) => url)).not.toContain(expect.stringContaining("%253A"));
  });

  it("sends the raw booking token to its once-encoded GET and POST paths", async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(jsonResponse({}))
      .mockResolvedValueOnce(jsonResponse({}));
    vi.stubGlobal("fetch", fetch);

    await getBookingInfo(SIGNED);
    await submitBooking(SIGNED, {
      start_at: "2026-07-28T10:00:00+09:00",
      method: "phone",
    });

    expect(fetch).toHaveBeenNthCalledWith(1, BOOKING_URL);
    expect(fetch).toHaveBeenNthCalledWith(2, BOOKING_URL, expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        start_at: "2026-07-28T10:00:00+09:00",
        method: "phone",
      }),
    }));
    expect(fetch.mock.calls.map(([url]) => url)).not.toContain(expect.stringContaining("%253A"));
  });
});
