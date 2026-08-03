import Image from "next/image";
import Link from "next/link";

import { PublicSiteShell } from "@/components/public-site-shell";
import { JsonLd, breadcrumbList, faqPage, webPage } from "@/components/structured-data";
import {
  SEARCH_HUBS,
  SEARCH_HUB_CTA_PATH,
  type SearchHubContent,
} from "@/lib/search-content";

const PUBLIC_LABELS: Record<string, string> = {
  "/": "인파 홈",
  "/blog": "설계사 실무 블로그",
  "/faq": "자주 묻는 질문",
  "/data-policy": "데이터 처리 안내",
};

function hubPath(hub: SearchHubContent): string {
  return `/${hub.kind === "solution" ? "solutions" : "guides"}/${hub.slug}`;
}

function relatedLabel(path: string): string {
  return SEARCH_HUBS.find((hub) => hubPath(hub) === path)?.title ?? PUBLIC_LABELS[path] ?? path;
}

export function SearchHubPage({ hub }: { hub: SearchHubContent }) {
  const path = hubPath(hub);
  const kindLabel = hub.kind === "solution" ? "인파 솔루션" : "설계사 실무 가이드";
  const schemas = [
    webPage({
      name: hub.title,
      description: hub.description,
      url: path,
      dateModified: hub.updatedAt,
    }),
    breadcrumbList([
      { name: "홈", url: "/" },
      { name: kindLabel, url: hub.kind === "solution" ? "/#solutions" : "/#guides" },
      { name: hub.title, url: path },
    ]),
    faqPage(hub.faq),
  ];

  return (
    <PublicSiteShell>
      <JsonLd data={schemas} />

      <main>
        <section className="border-b border-line bg-surface">
          <div className="mx-auto max-w-5xl px-4 py-12 sm:px-6 sm:py-16 lg:py-20">
            <nav aria-label="현재 위치" className="flex flex-wrap items-center gap-2 text-[12px] font-semibold text-ink3">
              <Link href="/" className="rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand">홈</Link>
              <span aria-hidden="true">/</span>
              <span>{kindLabel}</span>
            </nav>

            <div className="mt-6 max-w-4xl">
              <p className="text-[13px] font-extrabold tracking-[0.14em] text-brand">{kindLabel}</p>
              <h1 className="mt-3 break-keep text-[34px] font-black leading-[1.18] tracking-tight text-brand-ink sm:text-[48px]">
                {hub.title}
              </h1>
              <p className="mt-6 max-w-3xl break-keep text-[17px] font-medium leading-8 text-ink2 sm:text-[19px] sm:leading-9">
                {hub.answer}
              </p>
              <p className="mt-5 text-[12px] text-muted">
                마지막 확인 <time dateTime={hub.updatedAt}>{hub.updatedAt.replaceAll("-", ".")}</time>
              </p>
            </div>
          </div>
        </section>

        <div className="mx-auto max-w-5xl space-y-20 px-4 py-14 sm:px-6 sm:py-20">
          <section aria-labelledby="fit-title">
            <h2 id="fit-title" className="text-[27px] font-black tracking-tight text-brand-ink sm:text-[32px]">
              이런 분에게 맞아요
            </h2>
            <div className="mt-7 grid gap-3 md:grid-cols-3">
              {hub.fitFor.map((item) => (
                <div key={item} className="rounded-2xl border border-line bg-surface p-5 shadow-card">
                  <div className="flex h-9 w-9 items-center justify-center rounded-full bg-accent-tint text-[16px] font-black text-brand" aria-hidden="true">
                    ✓
                  </div>
                  <p className="mt-4 break-keep text-[15px] font-bold leading-7 text-ink">{item}</p>
                </div>
              ))}
            </div>
          </section>

          <section aria-labelledby="steps-title">
            <div className="max-w-2xl">
              <p className="text-[12px] font-extrabold tracking-[0.14em] text-brand">실행 순서</p>
              <h2 id="steps-title" className="mt-2 text-[27px] font-black tracking-tight text-brand-ink sm:text-[32px]">
                인파에서 하는 순서
              </h2>
            </div>
            <ol className="mt-8 grid gap-5 md:grid-cols-2">
              {hub.steps.map((step, index) => (
                <li key={step.title} className="rounded-3xl border border-line bg-surface p-6 sm:p-7">
                  <div className="flex items-center gap-3">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand text-[13px] font-black text-white">
                      {index + 1}
                    </span>
                    <h3 className="break-keep text-[18px] font-extrabold text-brand-ink">{step.title}</h3>
                  </div>
                  <p className="mt-4 break-keep text-[14px] leading-7 text-ink2 sm:text-[15px]">{step.body}</p>
                </li>
              ))}
            </ol>
          </section>

          <section aria-labelledby="evidence-title">
            <div className="max-w-2xl">
              <p className="text-[12px] font-extrabold tracking-[0.14em] text-brand">제품 근거</p>
              <h2 id="evidence-title" className="mt-2 text-[27px] font-black tracking-tight text-brand-ink sm:text-[32px]">
                실제 화면으로 확인
              </h2>
            </div>
            <div className="mt-8 space-y-8">
              {hub.evidence.map((evidence) => (
                <figure key={evidence.src} className="overflow-hidden rounded-3xl border border-line bg-surface shadow-card">
                  <div className="relative aspect-[16/10] w-full overflow-hidden bg-canvas">
                    <Image
                      src={evidence.src}
                      alt={evidence.alt}
                      fill
                      sizes="(max-width: 1023px) calc(100vw - 32px), 960px"
                      className="object-cover"
                    />
                  </div>
                  <figcaption className="border-t border-line px-5 py-4 text-[13px] leading-6 text-ink3 sm:px-6">
                    {evidence.caption}
                  </figcaption>
                </figure>
              ))}
            </div>
          </section>

          <section className="grid gap-5 lg:grid-cols-5">
            <div className="rounded-3xl border border-line bg-surface p-6 sm:p-8 lg:col-span-3">
              <h2 className="text-[24px] font-black text-brand-ink">직접 확인할 항목</h2>
              <ul className="mt-6 space-y-4">
                {hub.checklist.map((item) => (
                  <li key={item} className="flex gap-3 text-[14px] leading-7 text-ink2 sm:text-[15px]">
                    <span className="mt-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-brand/30 bg-accent-tint text-[12px] font-black text-brand" aria-hidden="true">
                      ✓
                    </span>
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>

            <aside className="rounded-3xl bg-brand-ink p-6 text-white sm:p-8 lg:col-span-2">
              <h2 className="text-[24px] font-black">알아둘 점</h2>
              <ul className="mt-6 space-y-4">
                {hub.limitations.map((item) => (
                  <li key={item} className="flex gap-3 text-[14px] leading-7 text-white/85">
                    <span className="mt-3 h-1.5 w-1.5 shrink-0 rounded-full bg-white/70" aria-hidden="true" />
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </aside>
          </section>

          <section aria-labelledby="faq-title">
            <h2 id="faq-title" className="text-[27px] font-black tracking-tight text-brand-ink sm:text-[32px]">
              자주 묻는 질문
            </h2>
            <div className="mt-7 divide-y divide-line border-y border-line">
              {hub.faq.map((item) => (
                <details key={item.q} className="group py-5">
                  <summary className="cursor-pointer list-none pr-8 text-[16px] font-extrabold leading-7 text-brand-ink marker:hidden focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand">
                    {item.q}
                  </summary>
                  <p className="mt-3 max-w-3xl break-keep text-[14px] leading-7 text-ink2 sm:text-[15px]">{item.a}</p>
                </details>
              ))}
            </div>
          </section>

          <section aria-labelledby="related-title">
            <h2 id="related-title" className="text-[24px] font-black text-brand-ink">관련해서 함께 보기</h2>
            <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {hub.relatedPaths.map((relatedPath) => (
                <Link
                  key={relatedPath}
                  href={relatedPath}
                  className="group flex min-h-[96px] items-center justify-between gap-4 rounded-2xl border border-line bg-surface p-5 text-[14px] font-bold leading-6 text-ink transition hover:border-brand/50 hover:text-brand-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
                >
                  <span>{relatedLabel(relatedPath)}</span>
                  <span aria-hidden="true" className="text-brand transition group-hover:translate-x-1">→</span>
                </Link>
              ))}
            </div>
          </section>

          <section className="overflow-hidden rounded-[32px] bg-brand px-6 py-10 text-center text-white sm:px-10 sm:py-14">
            <p className="text-[13px] font-bold text-white/80">증권 한 장에서 시작해 보세요</p>
            <h2 className="mx-auto mt-3 max-w-2xl break-keep text-[27px] font-black leading-tight sm:text-[36px]">
              고객 기록과 보장 정리를 한 흐름으로 이어 보세요
            </h2>
            <p className="mx-auto mt-4 max-w-xl text-[14px] leading-7 text-white/85 sm:text-[15px]">
              가입한 뒤 첫 고객을 등록하고 실제 증권으로 화면을 직접 확인할 수 있습니다.
            </p>
            <Link
              href={SEARCH_HUB_CTA_PATH}
              className="mt-7 inline-flex min-h-[52px] items-center justify-center rounded-2xl bg-white px-7 py-3 text-[15px] font-black text-brand-ink transition hover:bg-white/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-brand"
            >
              첫 분석 무료로 시작하기
            </Link>
          </section>
        </div>
      </main>
    </PublicSiteShell>
  );
}
