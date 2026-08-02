"use client";

import { track } from "@vercel/analytics";
import Link from "next/link";
import { useEffect, useRef, type ReactNode } from "react";
import type { BlogCategory } from "@/lib/api";

type BlogAnalyticsProps = { slug: string; category: BlogCategory };

type TrackedBlogCtaProps = BlogAnalyticsProps & {
  href: string;
  children: ReactNode;
  className?: string;
};

type ReferrerClass = "direct" | "search" | "social" | "other";
type CtaDestination = "register" | "other";
type AnalyticsPayload = Record<string, string>;

const UTM_SOURCES = ["naver", "google", "kakao", "instagram", "facebook", "youtube", "newsletter", "partner"] as const;
const UTM_MEDIA = ["organic", "cpc", "social", "email", "referral", "display"] as const;

function safeTrack(event: "blog_view" | "blog_cta_click", payload: AnalyticsPayload) {
  try {
    void Promise.resolve(track(event, payload)).catch(() => undefined);
  } catch {
    // 계측 장애는 글 읽기와 이동을 막지 않는다.
  }
}

export function classifyReferrer(referrer: string): ReferrerClass {
  if (!referrer) return "direct";

  try {
    const hostname = new URL(referrer).hostname.toLowerCase();
    if (/(^|\.)(google|naver|daum|bing|yahoo|duckduckgo)\./.test(hostname)) return "search";
    if (/(^|\.)(facebook|fb|instagram|kakao|linkedin|tiktok|twitter|x|threads)\./.test(hostname)) return "social";
    return "other";
  } catch {
    return "other";
  }
}

function classifyUtmValue(value: string | null, allowed: readonly string[]): string {
  if (!value) return "none";
  const normalized = value.slice(0, 80).toLowerCase();
  return allowed.includes(normalized) ? normalized : "other";
}

export function readAllowedUtm(search: string): Record<"utm_source" | "utm_medium" | "utm_campaign", string> {
  const params = new URLSearchParams(search);
  const campaign = params.get("utm_campaign")?.slice(0, 80).trim();
  return {
    utm_source: classifyUtmValue(params.get("utm_source"), UTM_SOURCES),
    utm_medium: classifyUtmValue(params.get("utm_medium"), UTM_MEDIA),
    utm_campaign: campaign ? "present" : "absent",
  };
}

function trackingContext({ slug, category }: BlogAnalyticsProps): AnalyticsPayload {
  return {
    slug,
    category,
    referrer_class: classifyReferrer(document.referrer),
    ...readAllowedUtm(window.location.search),
  };
}

function destinationFor(href: string): CtaDestination {
  return href === "/register" || href.startsWith("/register?") ? "register" : "other";
}

export function BlogAnalytics({ slug, category }: BlogAnalyticsProps) {
  const viewedRef = useRef(false);

  useEffect(() => {
    if (viewedRef.current) return;
    viewedRef.current = true;
    safeTrack("blog_view", trackingContext({ slug, category }));
  }, [slug, category]);

  return null;
}

export function TrackedBlogCta({ href, slug, category, children, className }: TrackedBlogCtaProps) {
  return (
    <Link
      href={href}
      className={className}
      onClick={() => safeTrack("blog_cta_click", {
        ...trackingContext({ slug, category }),
        destination: destinationFor(href),
      })}
    >
      {children}
    </Link>
  );
}
