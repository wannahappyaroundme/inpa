import type { Breadcrumb, Event } from "@sentry/nextjs";
import { classifySearchPath } from "@/lib/search-policy";

const TELEMETRY_ORIGIN = "https://www.inpa.kr";
const TELEMETRY_REDACTED_URL = `${TELEMETRY_ORIGIN}/telemetry-redacted`;
const REDACTED_VALUE = "[redacted]";
const MAX_TRAVERSAL_DEPTH = 10;

const EMAIL_PATTERN = /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi;
const KOREAN_PHONE_PATTERN =
  /(?<!\d)(?:(?:\+82[-.\s]?0?)|0)(?:1[016789]|2|3[1-3]|4[1-4]|5[1-5]|6[1-4]|70)[-.\s]?\d{3,4}[-.\s]?\d{4}(?!\d)/g;
const URL_IN_TEXT_PATTERN = /https?:\/\/[^\s<>"']+|\/[^\s<>"']+/gi;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const NUMERIC_ID_PATTERN = /^\d+$/;
const TOKENISH_PATTERN = /^[A-Za-z0-9_-]{16,}$/;
const FULL_REDACTION_FIELDS = new Set([
  "querystring",
  "search",
  "query",
  "hash",
  "fragment",
  "httpquery",
  "httpfragment",
]);
const SAFE_DIAGNOSTIC_ID_PATTERNS: Readonly<Record<string, RegExp>> = {
  eventid: /^[0-9a-f]{32}$/i,
  traceid: /^[0-9a-f]{32}$/i,
  spanid: /^[0-9a-f]{16}$/i,
  parentspanid: /^[0-9a-f]{16}$/i,
  profileid: /^(?:[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$/i,
  segmentid: /^[0-9a-f]{16}$/i,
};
const SENSITIVE_IDENTIFIER_PARTS = new Set(["id", "uuid", "token", "pk"]);

const SINGLE_TOKEN_ROUTES = new Set(["s", "b", "c", "d", "p"]);

function parseTelemetryUrl(raw: string, baseUrl = TELEMETRY_ORIGIN): URL | null {
  try {
    if (typeof raw !== "string" || raw.trim() === "") return null;
    const base = new URL(baseUrl);
    if (base.protocol !== "http:" && base.protocol !== "https:") return null;

    const parsed = new URL(raw, base);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
    return parsed;
  } catch {
    return null;
  }
}

function looksLikeSensitiveToken(value: string): boolean {
  return (
    TOKENISH_PATTERN.test(value) &&
    /[A-Za-z]/.test(value) &&
    /\d/.test(value)
  );
}

function sanitizeGenericSegment(segment: string): string {
  const decoded = decodeURIComponent(segment);
  if (
    NUMERIC_ID_PATTERN.test(decoded) ||
    UUID_PATTERN.test(decoded) ||
    EMAIL_PATTERN.test(decoded) ||
    KOREAN_PHONE_PATTERN.test(decoded)
  ) {
    EMAIL_PATTERN.lastIndex = 0;
    KOREAN_PHONE_PATTERN.lastIndex = 0;
    return "[id]";
  }
  EMAIL_PATTERN.lastIndex = 0;
  KOREAN_PHONE_PATTERN.lastIndex = 0;
  return looksLikeSensitiveToken(decoded) ? "[token]" : segment;
}

function sanitizePathname(pathname: string): string {
  const segments = pathname.split("/");
  const first = segments[1];

  if (SINGLE_TOKEN_ROUTES.has(first) && segments[2]) {
    segments[2] = "[token]";
    segments.splice(3);
  } else if (first === "r") {
    if (segments[2] === "manage" && segments[3]) {
      segments[3] = "[token]";
      segments.splice(4);
    } else if (segments[2]) {
      segments[2] = "[token]";
      segments.splice(3);
    }
  } else if (first === "recruiting" && segments[2] === "join" && segments[3]) {
    segments[3] = "[token]";
    segments.splice(4);
  }

  return segments.map((segment) => sanitizeGenericSegment(segment)).join("/") || "/";
}

export function sanitizeTelemetryUrl(raw: string, baseUrl = TELEMETRY_ORIGIN): string {
  const parsed = parseTelemetryUrl(raw, baseUrl);
  if (!parsed) return TELEMETRY_REDACTED_URL;

  try {
    return `${TELEMETRY_ORIGIN}${sanitizePathname(parsed.pathname)}`;
  } catch {
    return TELEMETRY_REDACTED_URL;
  }
}

export function redactSensitiveText(value: string): string {
  try {
    const withoutUrls = value.replace(URL_IN_TEXT_PATTERN, (rawUrl) =>
      sanitizeTelemetryUrl(rawUrl),
    );
    const withoutContacts = withoutUrls
      .replace(EMAIL_PATTERN, "[email]")
      .replace(KOREAN_PHONE_PATTERN, "[phone]");

    return withoutContacts.replace(/[A-Za-z0-9_-]{16,}/g, (candidate) =>
      looksLikeSensitiveToken(candidate) ? "[token]" : candidate,
    );
  } catch {
    return REDACTED_VALUE;
  } finally {
    EMAIL_PATTERN.lastIndex = 0;
    KOREAN_PHONE_PATTERN.lastIndex = 0;
  }
}

function isPlainObject(value: object): value is Record<string, unknown> {
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function normalizedFieldName(key: string): string {
  return key.toLowerCase().replace(/[._-]/g, "");
}

function semanticFieldParts(key: string): string[] {
  return key
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .toLowerCase()
    .split(/[._-]+/)
    .filter(Boolean);
}

function sanitizedIdentifierFieldValue(key: string, value: unknown): unknown {
  const diagnosticPattern = SAFE_DIAGNOSTIC_ID_PATTERNS[normalizedFieldName(key)];
  if (diagnosticPattern) {
    return typeof value === "string" && diagnosticPattern.test(value)
      ? value
      : REDACTED_VALUE;
  }
  if (semanticFieldParts(key).some((part) => SENSITIVE_IDENTIFIER_PARTS.has(part))) {
    return REDACTED_VALUE;
  }
  return undefined;
}

function isUrlField(key: string): boolean {
  const lowerKey = key.toLowerCase();
  return (
    lowerKey === "url" ||
    lowerKey === "href" ||
    /(?:^|[._-])url$/.test(lowerKey)
  );
}

function privacySafeObjectKey(key: string): string {
  return redactSensitiveText(key) === key ? key : "[redacted-key]";
}

function uniqueObjectKey(
  requestedKey: string,
  reservedKeys: ReadonlySet<string>,
  usedKeys: ReadonlySet<string>,
): string {
  if (!reservedKeys.has(requestedKey) && !usedKeys.has(requestedKey)) {
    return requestedKey;
  }

  let suffix = 2;
  while (
    reservedKeys.has(`${requestedKey}-${suffix}`) ||
    usedKeys.has(`${requestedKey}-${suffix}`)
  ) {
    suffix += 1;
  }
  return `${requestedKey}-${suffix}`;
}

function sanitizeFieldValue(
  key: string,
  value: unknown,
  activeObjects: WeakSet<object>,
  depth: number,
): unknown {
  const identifierValue = sanitizedIdentifierFieldValue(key, value);
  if (identifierValue !== undefined) return identifierValue;
  if (FULL_REDACTION_FIELDS.has(normalizedFieldName(key))) {
    return REDACTED_VALUE;
  }
  if (isUrlField(key)) {
    return typeof value === "string" ? sanitizeTelemetryUrl(value) : REDACTED_VALUE;
  }
  return sanitizeJsonValue(value, activeObjects, depth);
}

function isDynamicBlogPath(pathname: string): boolean {
  const segments = pathname.split("/").filter(Boolean);
  return segments[0] === "blog" && segments.length > 1;
}

function dynamicBlogPageIsIndexable(eventPathname: string): boolean {
  try {
    if (typeof document === "undefined") return false;
    const robotsTags = Array.from(
      document.querySelectorAll<HTMLMetaElement>('meta[name="robots"]'),
    );
    if (robotsTags.length === 0) return false;
    const canonicalLinks = Array.from(
      document.querySelectorAll<HTMLLinkElement>('link[rel~="canonical"]'),
    );
    if (canonicalLinks.length !== 1) return false;
    const canonicalHref = canonicalLinks[0].getAttribute("href");
    if (!canonicalHref) return false;
    const canonicalUrl = new URL(canonicalHref);
    if (canonicalUrl.protocol !== "http:" && canonicalUrl.protocol !== "https:") {
      return false;
    }
    if (canonicalUrl.pathname !== eventPathname) return false;

    let hasIndex = false;
    for (const tag of robotsTags) {
      const directives = tag.content
        .toLowerCase()
        .split(/[\s,]+/)
        .filter(Boolean);
      if (directives.includes("noindex")) return false;
      if (directives.includes("index")) hasIndex = true;
    }
    return hasIndex;
  } catch {
    return false;
  }
}

function sanitizeJsonValue(
  value: unknown,
  activeObjects: WeakSet<object>,
  depth: number,
): unknown {
  if (typeof value === "string") return redactSensitiveText(value);
  if (value === null || typeof value === "number" || typeof value === "boolean") {
    return value;
  }
  if (typeof value !== "object" || depth >= MAX_TRAVERSAL_DEPTH) {
    return REDACTED_VALUE;
  }
  if (!Array.isArray(value) && !isPlainObject(value)) return REDACTED_VALUE;
  if (activeObjects.has(value)) return REDACTED_VALUE;

  activeObjects.add(value);
  try {
    if (Array.isArray(value)) {
      return value.map((item) => sanitizeJsonValue(item, activeObjects, depth + 1));
    }

    const sourceKeys = Object.keys(value);
    const reservedKeys = new Set(
      sourceKeys.filter(
        (key) => key !== "__proto__" && privacySafeObjectKey(key) === key,
      ),
    );
    const usedKeys = new Set<string>();
    const sanitized: Record<string, unknown> = {};
    for (const key of sourceKeys) {
      if (key === "__proto__") continue;
      const requestedKey = privacySafeObjectKey(key);
      const safeKey =
        requestedKey === key
          ? key
          : uniqueObjectKey(requestedKey, reservedKeys, usedKeys);
      usedKeys.add(safeKey);
      try {
        sanitized[safeKey] = sanitizeFieldValue(
          key,
          value[key],
          activeObjects,
          depth + 1,
        );
      } catch {
        sanitized[safeKey] = REDACTED_VALUE;
      }
    }
    return sanitized;
  } catch {
    return REDACTED_VALUE;
  } finally {
    activeObjects.delete(value);
  }
}

function sanitizePlainPayload<T extends object>(payload: T): T | null {
  try {
    const sanitized = sanitizeJsonValue(payload, new WeakSet<object>(), 0);
    return sanitized !== null && typeof sanitized === "object" && !Array.isArray(sanitized)
      ? (sanitized as T)
      : null;
  } catch {
    return null;
  }
}

export function sanitizeAnalyticsEvent<T extends { url: string }>(event: T): T | null {
  try {
    const parsed = parseTelemetryUrl(event.url);
    if (!parsed || classifySearchPath(parsed.pathname) !== "indexable") return null;
    if (
      isDynamicBlogPath(parsed.pathname) &&
      !dynamicBlogPageIsIndexable(parsed.pathname)
    ) {
      return null;
    }

    const sanitized = sanitizePlainPayload(event);
    if (!sanitized) return null;
    sanitized.url = sanitizeTelemetryUrl(event.url);
    return sanitized;
  } catch {
    return null;
  }
}

export function sanitizeSentryEvent<T extends Event>(event: T): T | null;
export function sanitizeSentryEvent(event: Event): Event | null;
export function sanitizeSentryEvent(event: Event): Event | null {
  return sanitizePlainPayload(event);
}

export function sanitizeSentryBreadcrumb(breadcrumb: Breadcrumb): Breadcrumb | null {
  return sanitizePlainPayload(breadcrumb);
}
