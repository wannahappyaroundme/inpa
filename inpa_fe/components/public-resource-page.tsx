import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import { PublicSiteShell } from "@/components/public-site-shell";
import { JsonLd, breadcrumbList, webPage } from "@/components/structured-data";
import { PUBLIC_INDEX_ROBOTS } from "@/lib/search-policy";

type RelatedLink = { href: string; label: string };

type PublicResourcePageProps = {
  kindLabel: string;
  title: string;
  description: string;
  answer: string;
  path: string;
  updatedAt: string;
  privacyNote: string;
  related: readonly RelatedLink[];
  children: ReactNode;
};

export function publicResourceMetadata({
  title,
  description,
  path,
}: Pick<PublicResourcePageProps, "title" | "description" | "path">): Metadata {
  return {
    title,
    description,
    alternates: { canonical: path },
    robots: PUBLIC_INDEX_ROBOTS,
    openGraph: {
      type: "website",
      locale: "ko_KR",
      siteName: "인파(Inpa)",
      title,
      description,
      url: path,
      images: [{ url: "/opengraph-image.jpg", width: 1200, height: 630 }],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: ["/opengraph-image.jpg"],
    },
  };
}

export function PublicResourcePage({
  kindLabel,
  title,
  description,
  answer,
  path,
  updatedAt,
  privacyNote,
  related,
  children,
}: PublicResourcePageProps) {
  return (
    <PublicSiteShell>
      <JsonLd
        data={[
          webPage({ name: title, description, url: path, dateModified: updatedAt }),
          breadcrumbList([
            { name: "홈", url: "/" },
            { name: kindLabel, url: path },
          ]),
        ]}
      />

      <main>
        <section className="border-b border-line bg-surface">
          <div className="mx-auto max-w-4xl px-4 py-12 sm:px-6 sm:py-16">
            <nav aria-label="현재 위치" className="flex items-center gap-2 text-[12px] font-semibold text-ink3">
              <Link href="/" className="rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand">홈</Link>
              <span aria-hidden="true">/</span>
              <span>{kindLabel}</span>
            </nav>
            <p className="mt-6 text-[13px] font-extrabold tracking-[0.14em] text-brand">{kindLabel}</p>
            <h1 className="mt-3 break-keep text-[34px] font-black leading-[1.18] tracking-tight text-brand-ink sm:text-[46px]">
              {title}
            </h1>
            <p className="mt-6 max-w-3xl break-keep text-[17px] font-medium leading-8 text-ink2 sm:text-[19px] sm:leading-9">
              {answer}
            </p>
            <p className="mt-5 text-[12px] text-muted">
              마지막 확인 <time dateTime={updatedAt}>{updatedAt.replaceAll("-", ".")}</time>
            </p>
          </div>
        </section>

        <div className="mx-auto max-w-4xl px-4 py-12 sm:px-6 sm:py-16">
          <aside className="mb-7 flex gap-3 rounded-2xl border border-[#ccd8ff] bg-accent-tint p-4 text-[13px] leading-6 text-brand-ink sm:p-5">
            <span aria-hidden="true" className="font-black">✓</span>
            <p>{privacyNote}</p>
          </aside>

          {children}

          <section className="mt-14 border-t border-line pt-10" aria-labelledby="resource-related-title">
            <h2 id="resource-related-title" className="text-[23px] font-black text-brand-ink">함께 확인하면 좋은 안내</h2>
            <div className="mt-5 grid gap-3 sm:grid-cols-2">
              {related.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="flex min-h-[80px] items-center justify-between gap-4 rounded-2xl border border-line bg-surface p-5 text-[14px] font-bold leading-6 text-ink transition hover:border-brand/50 hover:text-brand-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
                >
                  <span>{item.label}</span>
                  <span aria-hidden="true" className="text-brand">→</span>
                </Link>
              ))}
            </div>
          </section>

          <section className="mt-12 overflow-hidden rounded-[30px] bg-brand px-6 py-9 text-center text-white sm:px-10 sm:py-12">
            <h2 className="break-keep text-[26px] font-black sm:text-[32px]">고객 기록과 상담 준비를 한 흐름으로 이어 보세요</h2>
            <p className="mx-auto mt-4 max-w-xl text-[14px] leading-7 text-white/85">
              인파에 가입하면 고객 관리, 증권 정리, 여러 증권 비교와 일정을 한곳에서 확인할 수 있습니다.
            </p>
            <Link
              href="/register"
              className="mt-7 inline-flex min-h-[52px] items-center justify-center rounded-2xl bg-white px-7 py-3 text-[15px] font-black text-brand-ink transition hover:bg-white/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-brand"
            >
              무료로 먼저 확인해보기
            </Link>
          </section>
        </div>
      </main>
    </PublicSiteShell>
  );
}
