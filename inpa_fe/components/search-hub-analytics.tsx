"use client";

import { track } from "@vercel/analytics";
import Link from "next/link";
import { useEffect, type ReactNode } from "react";

const HUB_KINDS = new Set(["solution", "guide"]);
const HUB_SLUGS = new Set([
  "customer-management",
  "policy-analysis",
  "sales-management",
  "first-consultation",
  "customer-follow-up",
  "policy-review",
  "factual-comparison",
]);
const HUB_ACTIONS = new Set(["view", "click"]);

export function trackSearchHubEvent(action: string, kind: string, slug: string) {
  if (!HUB_ACTIONS.has(action) || !HUB_KINDS.has(kind) || !HUB_SLUGS.has(slug)) return;
  const eventName = action === "view" ? "search_hub_view" : "search_hub_cta_click";
  try {
    void Promise.resolve(track(eventName, {
      hub_kind: kind,
      hub_slug: slug,
    })).catch(() => undefined);
  } catch {
    // 계측 오류는 공개 페이지 탐색을 막지 않는다.
  }
}

export function SearchHubViewTracker({ kind, slug }: { kind: string; slug: string }) {
  useEffect(() => {
    trackSearchHubEvent("view", kind, slug);
  }, [kind, slug]);
  return null;
}

export function TrackedSearchHubCta({
  kind,
  slug,
  href,
  className,
  children,
}: {
  kind: string;
  slug: string;
  href: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Link
      href={href}
      className={className}
      onClick={() => trackSearchHubEvent("click", kind, slug)}
    >
      {children}
    </Link>
  );
}
