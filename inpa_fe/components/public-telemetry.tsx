"use client";

import { Analytics } from "@vercel/analytics/next";
import { SpeedInsights } from "@vercel/speed-insights/next";
import { sanitizeAnalyticsEvent } from "@/lib/telemetry-privacy";

export function PublicTelemetry() {
  return (
    <>
      <Analytics beforeSend={sanitizeAnalyticsEvent} />
      <SpeedInsights beforeSend={sanitizeAnalyticsEvent} />
    </>
  );
}
