export type AcquisitionChannel = "search" | "ai" | "direct" | "other";

export interface SafeAcquisition {
  utm_source?: string;
  utm_medium?: string;
  utm_campaign?: string;
}

const UTM_KEYS = ["utm_source", "utm_medium", "utm_campaign"] as const;
const SEARCH_SOURCES = new Set([
  "google",
  "google.com",
  "google.co.kr",
  "google_organic",
  "naver",
  "naver.com",
  "naver_organic",
  "bing",
  "bing.com",
  "bing_organic",
  "daum",
  "daum.net",
  "daum_organic",
]);
const AI_SOURCES = new Set([
  "chatgpt",
  "chatgpt.com",
  "openai",
  "openai.com",
  "perplexity",
  "perplexity.ai",
  "gemini",
  "gemini.google.com",
  "bard",
  "claude",
  "claude.ai",
  "anthropic",
  "anthropic.com",
  "copilot",
  "copilot.microsoft.com",
]);

const REFERRER_RULES: ReadonlyArray<{
  domains: readonly string[];
  source: string;
  medium: "search" | "ai";
}> = [
  // More-specific AI subdomains must precede their parent search domains.
  { domains: ["gemini.google.com", "bard.google.com"], source: "gemini", medium: "ai" },
  { domains: ["google.com", "google.co.kr"], source: "google_organic", medium: "search" },
  { domains: ["naver.com"], source: "naver_organic", medium: "search" },
  { domains: ["bing.com"], source: "bing_organic", medium: "search" },
  { domains: ["daum.net"], source: "daum_organic", medium: "search" },
  { domains: ["chatgpt.com", "openai.com"], source: "chatgpt", medium: "ai" },
  { domains: ["perplexity.ai"], source: "perplexity", medium: "ai" },
  { domains: ["claude.ai", "anthropic.com"], source: "claude", medium: "ai" },
  { domains: ["copilot.microsoft.com"], source: "copilot", medium: "ai" },
];

function sanitizeUtmValue(value: string | null): string | undefined {
  if (!value) return undefined;
  const safe = value.replace(/[^A-Za-z0-9._-]/g, "").slice(0, 60);
  return safe || undefined;
}

function hostnameMatches(hostname: string, domain: string): boolean {
  return hostname === domain || hostname.endsWith(`.${domain}`);
}

/**
 * Returns only short, allowlisted acquisition labels. Referrer paths, queries,
 * fragments, and search terms never leave this function.
 */
export function inferSafeAcquisition(search: string, referrer: string): SafeAcquisition {
  const params = new URLSearchParams(search);
  const explicit: SafeAcquisition = {};
  let hasExplicitUtm = false;

  for (const key of UTM_KEYS) {
    if (!params.has(key)) continue;
    hasExplicitUtm = true;
    const value = sanitizeUtmValue(params.get(key));
    if (value) explicit[key] = value;
  }
  if (hasExplicitUtm) return explicit;

  if (!referrer) return {};
  let hostname: string;
  try {
    hostname = new URL(referrer).hostname.toLowerCase().replace(/\.$/, "");
  } catch {
    return {};
  }
  if (!hostname) return {};

  const matched = REFERRER_RULES.find((rule) =>
    rule.domains.some((domain) => hostnameMatches(hostname, domain)),
  );
  if (matched) {
    return { utm_source: matched.source, utm_medium: matched.medium };
  }
  return { utm_source: "other_referral", utm_medium: "referral" };
}

export function classifyAcquisitionSource(source: string | null | undefined): AcquisitionChannel {
  const normalized = (source || "").trim().toLowerCase();
  if (!normalized || normalized === "direct") return "direct";
  if (SEARCH_SOURCES.has(normalized)) return "search";
  if (AI_SOURCES.has(normalized)) return "ai";
  return "other";
}
