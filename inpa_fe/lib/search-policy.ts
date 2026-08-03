import type { Metadata, MetadataRoute } from "next";

export const PUBLIC_INDEX_ROBOTS: Metadata["robots"] = {
  index: true,
  follow: true,
};

export const CURRENT_INDEXABLE_PATHS = [
  "/",
  "/story",
  "/blog",
  "/faq",
  "/data-policy",
] as const;

const INDEXABLE_DYNAMIC_PREFIXES = ["/blog/"] as const;

export const SENSITIVE_CRAWL_PREFIXES = [
  "/s",
  "/b",
  "/c",
  "/d",
  "/p",
  "/r",
  "/recruiting/join",
] as const;

export const ROBOTS_DISALLOW_PATHS = [
  ...SENSITIVE_CRAWL_PREFIXES.map((path) => `${path}/`),
  "/admin",
  "/api",
];

export type SearchPathClass = "indexable" | "sensitive" | "private_or_utility";

function isRouteOrChild(pathname: string, route: string): boolean {
  return pathname === route || pathname.startsWith(`${route}/`);
}

export function classifySearchPath(pathname: string): SearchPathClass {
  if (
    CURRENT_INDEXABLE_PATHS.some((path) => pathname === path) ||
    INDEXABLE_DYNAMIC_PREFIXES.some((prefix) => pathname.startsWith(prefix))
  ) {
    return "indexable";
  }
  if (SENSITIVE_CRAWL_PREFIXES.some((route) => isRouteOrChild(pathname, route))) {
    return "sensitive";
  }
  return "private_or_utility";
}

const SITEMAP_META: Record<
  (typeof CURRENT_INDEXABLE_PATHS)[number],
  Pick<MetadataRoute.Sitemap[number], "changeFrequency" | "priority">
> = {
  "/": { changeFrequency: "weekly", priority: 1 },
  "/story": { changeFrequency: "monthly", priority: 0.6 },
  "/blog": { changeFrequency: "weekly", priority: 0.7 },
  "/faq": { changeFrequency: "monthly", priority: 0.6 },
  "/data-policy": { changeFrequency: "monthly", priority: 0.3 },
};

export function staticSitemapEntries(siteUrl: string): MetadataRoute.Sitemap {
  const baseUrl = siteUrl.replace(/\/+$/, "");
  return CURRENT_INDEXABLE_PATHS.map((path) => ({
    url: `${baseUrl}${path === "/" ? "/" : path}`,
    ...SITEMAP_META[path],
  }));
}
