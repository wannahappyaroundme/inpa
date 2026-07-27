import { afterEach, describe, expect, it, vi } from "vitest";

import { listBookingCustomers, tokenStore } from "@/lib/api";

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("booking customer API", () => {
  afterEach(() => {
    tokenStore.remove();
    vi.unstubAllGlobals();
  });

  it("uses the dedicated authenticated booking-customer path", async () => {
    const fetch = vi.fn().mockResolvedValue(jsonResponse({
      count: 0,
      next: null,
      previous: null,
      results: [],
    }));
    vi.stubGlobal("fetch", fetch);
    tokenStore.set("booking-token");

    await listBookingCustomers({ page: 2, search: " 김 고객 " });

    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/booking-customers/?page=2&search=%EA%B9%80+%EA%B3%A0%EA%B0%9D",
      expect.objectContaining({
        method: "GET",
        headers: expect.objectContaining({
          Authorization: "Token booking-token",
        }),
      }),
    );
  });
});
