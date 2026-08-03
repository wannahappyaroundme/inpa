import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Event } from "@sentry/nextjs";

type TelemetryMockProps = {
  beforeSend: (event: { url: string }) => { url: string } | null;
};

const telemetryComponents = vi.hoisted(() => ({
  analytics: vi.fn((_props: TelemetryMockProps) => null),
  speedInsights: vi.fn((_props: TelemetryMockProps) => null),
}));

vi.mock("@vercel/analytics/next", () => ({
  Analytics: telemetryComponents.analytics,
}));

vi.mock("@vercel/speed-insights/next", () => ({
  SpeedInsights: telemetryComponents.speedInsights,
}));

import { PublicTelemetry } from "@/components/public-telemetry";
import { SENTRY_BASE_OPTIONS } from "@/lib/sentry-shared";
import {
  redactSensitiveText,
  sanitizeAnalyticsEvent,
  sanitizeSentryBreadcrumb,
  sanitizeSentryEvent,
  sanitizeTelemetryUrl,
} from "@/lib/telemetry-privacy";

const TOKEN_CANARY = "TOPSECRET-CUSTOMER-482";
const PHONE_CANARY = "010-9876-5432";
const UUID_CANARY = "123e4567-e89b-12d3-a456-426614174000";
const lowercaseOpaqueIdCanary = ["abcdefgh", "ijklmnop", "1234"].join("");

function setRobotsMeta(content: string) {
  document.head.querySelectorAll('meta[name="robots"]').forEach((node) => node.remove());
  const meta = document.createElement("meta");
  meta.name = "robots";
  meta.content = content;
  document.head.append(meta);
}

function appendCanonical(href: string) {
  const canonical = document.createElement("link");
  canonical.rel = "canonical";
  canonical.href = href;
  document.head.append(canonical);
}

function setCanonical(href: string) {
  document.head
    .querySelectorAll('link[rel~="canonical"]')
    .forEach((node) => node.remove());
  appendCanonical(href);
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.head.querySelectorAll('meta[name="robots"]').forEach((node) => node.remove());
  document.head
    .querySelectorAll('link[rel~="canonical"]')
    .forEach((node) => node.remove());
});

describe("telemetry URL 비식별화", () => {
  it.each([
    [
      `/s/${TOKEN_CANARY}?customer=kim#details`,
      "https://www.inpa.kr/s/[token]",
    ],
    ["/customer/482?tab=analysis", "https://www.inpa.kr/customer/[id]"],
    ["/promotion/orders/93", "https://www.inpa.kr/promotion/orders/[id]"],
    ["/boards/inquiry/71", "https://www.inpa.kr/boards/inquiry/[id]"],
  ])("%s를 안전한 경로 템플릿으로 바꾼다", (raw, expected) => {
    expect(sanitizeTelemetryUrl(raw)).toBe(expected);
  });

  it("외부 origin과 query/hash를 버리고, 해석할 수 없는 값은 고정 경로로 닫는다", () => {
    expect(
      sanitizeTelemetryUrl(
        `https://attacker.example/s/${TOKEN_CANARY}?phone=${PHONE_CANARY}#customer`,
      ),
    ).toBe("https://www.inpa.kr/s/[token]");
    expect(sanitizeTelemetryUrl("http://[")).toBe(
      "https://www.inpa.kr/telemetry-redacted",
    );
    expect(sanitizeTelemetryUrl("javascript:alert(1)")).toBe(
      "https://www.inpa.kr/telemetry-redacted",
    );
  });

  it("문자열 안의 URL, 이메일, 한국 전화번호와 긴 식별자를 비식별화한다", () => {
    const result = redactSensitiveText(
      `오류 ${TOKEN_CANARY}, ${PHONE_CANARY}, kim@example.com, ` +
        `https://old.example/promotion/orders/93?customer=kim#detail`,
    );

    expect(result).not.toContain(TOKEN_CANARY);
    expect(result).not.toContain(PHONE_CANARY);
    expect(result).not.toContain("kim@example.com");
    expect(result).not.toContain("customer=kim");
    expect(result).not.toContain("#detail");
    expect(result).toContain("https://www.inpa.kr/promotion/orders/[id]");
  });

  it("일반 문자열 안의 UUID와 소문자 opaque token도 비식별화한다", () => {
    const result = redactSensitiveText(
      `진단 ${UUID_CANARY}, 외부 식별자 ${lowercaseOpaqueIdCanary}`,
    );

    expect(result).not.toContain(UUID_CANARY);
    expect(result).not.toContain(lowercaseOpaqueIdCanary);
    expect(result).toBe("진단 [token], 외부 식별자 [token]");
  });

  it.each([
    "02-1234-5678",
    "031-123-4567",
    "070-1234-5678",
    "+82-2-1234-5678",
    "+82 31 123 4567",
    "+82-70-1234-5678",
  ])("국내 유선·지역·인터넷 전화번호 %s를 비식별화한다", (phone) => {
    const result = redactSensitiveText(`연락처 ${phone}`);

    expect(result).toBe("연락처 [phone]");
  });
});

describe("Vercel 공개 계측 경계", () => {
  it.each([
    ["/", "https://www.inpa.kr/"],
    ["/faq?from=private#answer", "https://www.inpa.kr/faq"],
  ])("공개 경로 %s만 비식별화한 뒤 유지한다", (url, expected) => {
    expect(sanitizeAnalyticsEvent({ url, marker: "kept" })).toEqual({
      url: expected,
      marker: "kept",
    });
  });

  it.each(["/home", "/customers", `/s/${TOKEN_CANARY}`])(
    "비공개 또는 민감 경로 %s는 전송하지 않는다",
    (url) => {
      expect(sanitizeAnalyticsEvent({ url })).toBeNull();
    },
  );

  it("동적 공개 글은 DOM robots가 명시적으로 index일 때만 유지한다", () => {
    setRobotsMeta("index, follow");
    setCanonical("https://www.inpa.kr/blog/public-slug?canonical=1#ignored");

    expect(
      sanitizeAnalyticsEvent({
        url: "/blog/public-slug?customer=kim#details",
        marker: "kept",
      }),
    ).toEqual({
      url: "https://www.inpa.kr/blog/public-slug",
      marker: "kept",
    });
  });

  it("동적 글의 robots meta가 없거나 noindex면 전송하지 않는다", () => {
    expect(sanitizeAnalyticsEvent({ url: "/blog/missing-meta" })).toBeNull();

    setRobotsMeta("noindex, nofollow");
    setCanonical("https://www.inpa.kr/blog/private-draft");
    expect(sanitizeAnalyticsEvent({ url: "/blog/private-draft" })).toBeNull();
  });

  it("SSR document 부재와 Next 404의 noindex meta에서는 동적 글을 전송하지 않는다", () => {
    vi.stubGlobal("document", undefined);
    expect(sanitizeAnalyticsEvent({ url: "/blog/server-render" })).toBeNull();
    vi.unstubAllGlobals();

    setRobotsMeta("noindex");
    setCanonical("https://www.inpa.kr/blog/not-found");
    expect(sanitizeAnalyticsEvent({ url: "/blog/not-found" })).toBeNull();
  });

  it("이전 공개 글 canonical이 남아 있으면 새 글 event를 차단한다", () => {
    setRobotsMeta("index, follow");
    setCanonical("https://www.inpa.kr/blog/public-a");

    expect(sanitizeAnalyticsEvent({ url: "/blog/private-b?from=a#pending" })).toBeNull();

    setCanonical("https://www.inpa.kr/blog/private-b?canonical=1#ready");
    expect(sanitizeAnalyticsEvent({ url: "/blog/private-b?from=a#ready" })).toEqual({
      url: "https://www.inpa.kr/blog/private-b",
    });
  });

  it("canonical은 정확히 하나의 http/https 절대 URL이며 pathname이 일치해야 한다", () => {
    setRobotsMeta("index, follow");

    expect(sanitizeAnalyticsEvent({ url: "/blog/public-post" })).toBeNull();

    for (const invalidCanonical of [
      "/blog/public-post",
      "javascript:alert(1)",
      "http://[",
      "https://www.inpa.kr/blog/different-post",
    ]) {
      setCanonical(invalidCanonical);
      expect(sanitizeAnalyticsEvent({ url: "/blog/public-post" })).toBeNull();
    }

    setCanonical("https://www.inpa.kr/blog/public-post");
    appendCanonical("https://www.inpa.kr/blog/public-post");
    expect(sanitizeAnalyticsEvent({ url: "/blog/public-post" })).toBeNull();

    setCanonical("http://www.inpa.kr/blog/public-post?canonical=1#ignored");
    expect(sanitizeAnalyticsEvent({ url: "/blog/public-post?event=1#ignored" })).toEqual({
      url: "https://www.inpa.kr/blog/public-post",
    });
  });

  it("URL getter나 파싱이 실패하면 원문 이벤트를 보내지 않는다", () => {
    const unreadable = {} as { url: string };
    Object.defineProperty(unreadable, "url", {
      enumerable: true,
      get() {
        throw new Error("cannot read URL");
      },
    });

    expect(sanitizeAnalyticsEvent(unreadable)).toBeNull();
    expect(sanitizeAnalyticsEvent({ url: "http://[" })).toBeNull();
  });

  it("Analytics와 Speed Insights에 같은 공개 경계 함수를 연결한다", () => {
    telemetryComponents.analytics.mockClear();
    telemetryComponents.speedInsights.mockClear();

    render(<PublicTelemetry />);

    expect(telemetryComponents.analytics).toHaveBeenCalledWith(
      expect.objectContaining({ beforeSend: sanitizeAnalyticsEvent }),
      undefined,
    );
    expect(telemetryComponents.speedInsights).toHaveBeenCalledWith(
      expect.objectContaining({ beforeSend: sanitizeAnalyticsEvent }),
      undefined,
    );

    const analyticsBeforeSend = telemetryComponents.analytics.mock.calls.at(-1)?.[0]
      .beforeSend;
    const speedBeforeSend = telemetryComponents.speedInsights.mock.calls.at(-1)?.[0]
      .beforeSend;

    setRobotsMeta("noindex");
    setCanonical("https://www.inpa.kr/blog/noindex-post");
    expect(analyticsBeforeSend?.({ url: "/blog/noindex-post" })).toBeNull();
    expect(speedBeforeSend?.({ url: "/blog/noindex-post" })).toBeNull();

    setRobotsMeta("index, follow");
    setCanonical("https://www.inpa.kr/blog/public-post");
    expect(analyticsBeforeSend?.({ url: "/blog/public-post" })).toEqual({
      url: "https://www.inpa.kr/blog/public-post",
    });
    expect(speedBeforeSend?.({ url: "/blog/public-post" })).toEqual({
      url: "https://www.inpa.kr/blog/public-post",
    });
  });
});

describe("Sentry 전송 직전 비식별화", () => {
  it("업무 ID는 닫고 형식이 올바른 Sentry 진단 ID만 보존한다", () => {
    const safeEventId = "0123456789abcdef0123456789abcdef";
    const safeTraceId = "11111111111111111111111111111111";
    const safeSpanId = "2222222222222222";
    const safeParentSpanId = "3333333333333333";
    const safeProfileId = "44444444444444444444444444444444";
    const sanitized = sanitizeSentryEvent({
      event_id: safeEventId,
      message: `UUID ${UUID_CANARY}, opaque ${lowercaseOpaqueIdCanary}`,
      contexts: {
        trace: {
          trace_id: safeTraceId,
          span_id: safeSpanId,
          parent_span_id: safeParentSpanId,
        },
        profile: { profile_id: safeProfileId },
      },
      extra: {
        customer_id: "482",
        order_id: 93,
        job_uuid: UUID_CANARY,
        opaque_id: lowercaseOpaqueIdCanary,
      },
    });
    const serialized = JSON.stringify(sanitized);

    expect(sanitized?.event_id).toBe(safeEventId);
    expect(sanitized?.contexts?.trace).toMatchObject({
      trace_id: safeTraceId,
      span_id: safeSpanId,
      parent_span_id: safeParentSpanId,
    });
    expect(sanitized?.contexts?.profile).toMatchObject({
      profile_id: safeProfileId,
    });
    expect(sanitized?.extra).toMatchObject({
      customer_id: "[redacted]",
      order_id: "[redacted]",
      job_uuid: "[redacted]",
      opaque_id: "[redacted]",
    });
    expect(serialized).not.toContain(UUID_CANARY);
    expect(serialized).not.toContain(lowercaseOpaqueIdCanary);
  });

  it("query/hash 의미 필드와 민감한 property key를 원문 없이 결정적으로 닫는다", () => {
    const sanitized = sanitizeSentryEvent({
      request: {
        url: `/s/${TOKEN_CANARY}?customer=kim#details`,
        query_string: `customer=kim&token=${TOKEN_CANARY}`,
      },
      extra: {
        search: `?customer=kim&token=${TOKEN_CANARY}`,
        query: `customer=kim&phone=${PHONE_CANARY}`,
        hash: `#${TOKEN_CANARY}`,
        fragment: PHONE_CANARY,
        "http.query": `customer=kim&token=${TOKEN_CANARY}`,
        "http.fragment": `#${PHONE_CANARY}`,
        keyCollision: {
          "[redacted-key]": "safe-value",
          [TOKEN_CANARY]: "first-private-value",
          [`${TOKEN_CANARY}-SECOND`]: "second-private-value",
          "kim@example.com": "email-key-value",
        },
      },
    });
    const serialized = JSON.stringify(sanitized);

    expect(serialized).not.toContain(TOKEN_CANARY);
    expect(serialized).not.toContain(PHONE_CANARY);
    expect(serialized).not.toContain("customer=kim");
    expect(sanitized?.request?.url).toBe("https://www.inpa.kr/s/[token]");
    expect(sanitized?.request?.query_string).toBe("[redacted]");
    expect(sanitized?.extra).toMatchObject({
      search: "[redacted]",
      query: "[redacted]",
      hash: "[redacted]",
      fragment: "[redacted]",
      "http.query": "[redacted]",
      "http.fragment": "[redacted]",
      keyCollision: {
        "[redacted-key]": "safe-value",
        "[redacted-key]-2": "first-private-value",
        "[redacted-key]-3": "second-private-value",
        "[redacted-key]-4": "email-key-value",
      },
    });
  });

  it("request, transaction, exception, breadcrumb, extra와 context에서 원문을 제거한다", () => {
    const event: Event = {
      message: `고객 ${TOKEN_CANARY} ${PHONE_CANARY}`,
      request: {
        url: `https://old.example/s/${TOKEN_CANARY}?customer=kim#details`,
      },
      transaction: `/customer/482?tab=analysis#${TOKEN_CANARY}`,
      exception: {
        values: [
          {
            type: "CustomerLookupError",
            value:
              `연락처 ${PHONE_CANARY}, kim@example.com, ${TOKEN_CANARY}, ` +
              "/promotion/orders/93?customer=kim#details",
          },
        ],
      },
      breadcrumbs: [
        {
          category: "navigation",
          message:
            `/boards/inquiry/71?phone=${PHONE_CANARY}#${TOKEN_CANARY}`,
          data: {
            from: `/s/${TOKEN_CANARY}?customer=kim#details`,
          },
        },
      ],
      extra: {
        nested: {
          url: `/promotion/orders/93?customer=${TOKEN_CANARY}#${PHONE_CANARY}`,
          contact: `kim@example.com ${PHONE_CANARY}`,
        },
      },
      contexts: {
        customer: {
          route: `/customer/482?token=${TOKEN_CANARY}#${PHONE_CANARY}`,
        },
      },
    };

    const sanitized = sanitizeSentryEvent(event);
    const serialized = JSON.stringify(sanitized);

    expect(sanitized).not.toBeNull();
    expect(serialized).not.toContain(TOKEN_CANARY);
    expect(serialized).not.toContain(PHONE_CANARY);
    expect(serialized).not.toContain("kim@example.com");
    expect(serialized).not.toContain("customer=kim");
    expect(serialized).not.toContain("tab=analysis");
    expect(serialized).not.toContain("#details");
    expect(serialized).toContain("/s/[token]");
    expect(serialized).toContain("/customer/[id]");
    expect(serialized).toContain("/promotion/orders/[id]");
    expect(serialized).toContain("/boards/inquiry/[id]");
  });

  it("순환참조, throwing getter, 비평문 객체가 있어도 원문 대신 닫힌 값을 반환한다", () => {
    const circular: Record<string, unknown> = {
      secret: TOKEN_CANARY,
      phone: PHONE_CANARY,
    };
    circular.self = circular;

    const throwingGetter: Record<string, unknown> = {};
    Object.defineProperty(throwingGetter, "secret", {
      enumerable: true,
      get() {
        throw new Error(TOKEN_CANARY);
      },
    });

    class PrivateEnvelope {
      secret = TOKEN_CANARY;
    }

    const sanitized = sanitizeSentryEvent({
      extra: {
        circular,
        throwingGetter,
        classInstance: new PrivateEnvelope(),
      },
    });
    const serialized = JSON.stringify(sanitized);

    expect(serialized).not.toContain(TOKEN_CANARY);
    expect(serialized).not.toContain(PHONE_CANARY);
    expect(serialized).toContain("[redacted]");
  });

  it("개별 breadcrumb도 중첩 URL과 문자열을 같은 규칙으로 닫는다", () => {
    const sanitized = sanitizeSentryBreadcrumb({
      message: `이동 /s/${TOKEN_CANARY}?customer=kim#details ${PHONE_CANARY}`,
      data: {
        destination: "/boards/inquiry/71?customer=kim#details",
      },
    });
    const serialized = JSON.stringify(sanitized);

    expect(serialized).not.toContain(TOKEN_CANARY);
    expect(serialized).not.toContain(PHONE_CANARY);
    expect(serialized).not.toContain("customer=kim");
    expect(serialized).toContain("/s/[token]");
    expect(serialized).toContain("/boards/inquiry/[id]");
  });

  it("Sentry 공통 옵션은 PII, replay, tracing을 차단하고 두 hook을 공유한다", () => {
    expect(SENTRY_BASE_OPTIONS.sendDefaultPii).toBe(false);
    expect(SENTRY_BASE_OPTIONS.tracesSampleRate).toBe(0);
    expect(SENTRY_BASE_OPTIONS).not.toHaveProperty("replaysSessionSampleRate");
    expect(SENTRY_BASE_OPTIONS).not.toHaveProperty("replaysOnErrorSampleRate");
    expect(SENTRY_BASE_OPTIONS).not.toHaveProperty("integrations");
    expect(SENTRY_BASE_OPTIONS.beforeSend).toBe(sanitizeSentryEvent);
    expect(SENTRY_BASE_OPTIONS.beforeBreadcrumb).toBe(sanitizeSentryBreadcrumb);
  });
});
