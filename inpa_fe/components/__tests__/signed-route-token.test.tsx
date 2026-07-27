import { describe, expect, it } from "vitest";
import {
  isSafeSignedRouteToken,
  normalizeSignedRouteToken,
} from "@/lib/signed-route-token";

const SIGNED = "eyJwayI6MTI4fQ:1wo9X8:k8naBaeSr-UhWUIbw-0KvWK1c8";

describe("signed route token", () => {
  it("accepts raw and one encoded token as the same raw token", () => {
    expect(normalizeSignedRouteToken(SIGNED)).toBe(SIGNED);
    expect(normalizeSignedRouteToken(encodeURIComponent(SIGNED))).toBe(SIGNED);
  });

  it.each([
    encodeURIComponent(encodeURIComponent(SIGNED)),
    "broken%2",
    "has/slash",
    "has%2Fslash",
    "has space",
    "%00control",
    ".",
    "..",
    "",
  ])("rejects unsafe input %s", (value) => {
    expect(normalizeSignedRouteToken(value)).toBeNull();
  });

  it("rejects non strings", () => {
    expect(normalizeSignedRouteToken(undefined)).toBeNull();
    expect(normalizeSignedRouteToken(["signed"])).toBeNull();
  });

  it("uses the same predicate for already decoded values", () => {
    expect(isSafeSignedRouteToken(SIGNED)).toBe(true);
    expect(isSafeSignedRouteToken("has%3Aescape")).toBe(false);
  });
});
