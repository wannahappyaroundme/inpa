import { describe, expect, it } from "vitest";

import {
  classifyAcquisitionSource,
  inferSafeAcquisition,
} from "@/lib/acquisition";

describe("inferSafeAcquisition", () => {
  it("keeps sanitized explicit UTM values ahead of the referrer", () => {
    expect(
      inferSafeAcquisition(
        "?utm_source=Partner%20Launch&utm_medium=Paid%2FSocial&utm_campaign=August%20Pilot",
        "https://www.google.com/search?q=insurance+planner",
      ),
    ).toEqual({
      utm_source: "PartnerLaunch",
      utm_medium: "PaidSocial",
      utm_campaign: "AugustPilot",
    });
  });

  it.each([
    ["https://www.google.com/search?q=private-query", "google_organic", "search"],
    ["https://m.search.naver.com/search.naver?query=private-query", "naver_organic", "search"],
    ["https://www.bing.com/search?q=private-query", "bing_organic", "search"],
    ["https://search.daum.net/search?q=private-query", "daum_organic", "search"],
    ["https://chatgpt.com/c/secret-conversation", "chatgpt", "ai"],
    ["https://www.perplexity.ai/search/secret", "perplexity", "ai"],
    ["https://gemini.google.com/app/secret", "gemini", "ai"],
    ["https://claude.ai/chat/secret", "claude", "ai"],
    ["https://copilot.microsoft.com/chats/secret", "copilot", "ai"],
  ])("maps %s without retaining its path or query", (referrer, source, medium) => {
    const result = inferSafeAcquisition("", referrer);

    expect(result).toEqual({ utm_source: source, utm_medium: medium });
    expect(JSON.stringify(result)).not.toContain("private-query");
    expect(JSON.stringify(result)).not.toContain("secret");
  });

  it("does not mistake a lookalike hostname for Google", () => {
    expect(inferSafeAcquisition("", "https://notgoogle.com/search?q=secret")).toEqual({
      utm_source: "other_referral",
      utm_medium: "referral",
    });
  });

  it("returns no inferred values for direct or malformed referrers", () => {
    expect(inferSafeAcquisition("", "")).toEqual({});
    expect(inferSafeAcquisition("", "not a valid url")).toEqual({});
  });

  it("limits explicit values to safe characters and 60 characters", () => {
    const result = inferSafeAcquisition(
      `?utm_source=${encodeURIComponent("a".repeat(80))}&utm_medium=paid%20social%3Fsecret`,
      "",
    );

    expect(result.utm_source).toHaveLength(60);
    expect(result.utm_medium).toBe("paidsocialsecret");
  });
});

describe("classifyAcquisitionSource", () => {
  it.each([
    ["google_organic", "search"],
    ["NAVER", "search"],
    ["chatgpt", "ai"],
    ["perplexity", "ai"],
    ["", "direct"],
    ["direct", "direct"],
    ["partner_newsletter", "other"],
  ])("classifies %s as %s", (source, channel) => {
    expect(classifyAcquisitionSource(source)).toBe(channel);
  });
});
