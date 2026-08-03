import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { SearchHubPage } from "@/components/search-hub-page";
import { SEARCH_HUBS, getSearchHub } from "@/lib/search-content";
import { PUBLIC_INDEX_ROBOTS } from "@/lib/search-policy";

type Props = { params: Promise<{ slug: string }> };

export const dynamicParams = false;

export function generateStaticParams() {
  return SEARCH_HUBS
    .filter((hub) => hub.kind === "guide")
    .map((hub) => ({ slug: hub.slug }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const hub = getSearchHub("guide", slug);
  if (!hub) notFound();

  const path = `/guides/${hub.slug}`;
  const image = hub.evidence[0];
  return {
    title: hub.title,
    description: hub.description,
    alternates: { canonical: path },
    robots: PUBLIC_INDEX_ROBOTS,
    openGraph: {
      type: "website",
      locale: "ko_KR",
      siteName: "인파(Inpa)",
      title: hub.title,
      description: hub.description,
      url: path,
      images: [{ url: image.src, width: 2880, height: 1800, alt: image.alt }],
    },
    twitter: {
      card: "summary_large_image",
      title: hub.title,
      description: hub.description,
      images: [image.src],
    },
  };
}

export default async function GuidePage({ params }: Props) {
  const { slug } = await params;
  const hub = getSearchHub("guide", slug);
  if (!hub) notFound();
  return <SearchHubPage hub={hub} />;
}
