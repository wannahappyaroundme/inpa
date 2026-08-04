import type { Metadata } from "next";
import Link from "next/link";

import { BlogSectionTabs } from "@/components/blog-section-tabs";
import { InpaMark } from "@/components/inpa-logo";
import { PUBLIC_RESOURCES } from "@/lib/public-resources";
import { PUBLIC_INDEX_ROBOTS } from "@/lib/search-policy";

const PATH = "/blog/resources";
const DESCRIPTION =
  "보험설계사가 가입 전에도 바로 쓸 수 있는 보험나이 계산기, 고객 관리표 빈 양식과 첫 상담 체크리스트를 모았습니다.";

export const metadata: Metadata = {
  title: "무료 자료",
  description: DESCRIPTION,
  alternates: { canonical: PATH },
  robots: PUBLIC_INDEX_ROBOTS,
  openGraph: {
    type: "website",
    locale: "ko_KR",
    siteName: "인파(Inpa)",
    title: "무료 자료 · 인파 블로그",
    description: DESCRIPTION,
    url: PATH,
    images: [{ url: "/opengraph-image.jpg", width: 1200, height: 630 }],
  },
  twitter: {
    card: "summary_large_image",
    title: "무료 자료 · 인파 블로그",
    description: DESCRIPTION,
    images: ["/opengraph-image.jpg"],
  },
};

export default function BlogResourcesPage() {
  return (
    <div className="min-h-screen bg-canvas text-ink">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-4 sm:px-6">
          <Link href="/" className="flex items-center gap-2" aria-label="인파 홈으로">
            <InpaMark size={28} />
            <span className="text-[16px] font-extrabold text-brand-ink">인파 블로그</span>
          </Link>
          <Link
            href="/register"
            className="flex min-h-[44px] items-center rounded-xl bg-brand px-4 py-2 text-[14px] font-semibold text-white transition hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
          >
            무료로 시작하기
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 py-10 sm:px-6 sm:py-14">
        <div className="max-w-2xl">
          <h1 className="text-[30px] font-extrabold tracking-tight text-brand-ink sm:text-[38px]">
            무료 자료
          </h1>
          <p className="mt-3 break-keep text-[15px] leading-relaxed text-ink3 sm:text-[16px]">
            상담 전후에 바로 꺼내 쓰는 계산기와 빈 양식, 체크리스트를 한곳에 모았어요.
          </p>
        </div>

        <BlogSectionTabs activeSection="resources" />

        <section className="mt-8" aria-labelledby="free-resource-list-title">
          <h2 id="free-resource-list-title" className="sr-only">무료 자료 목록</h2>
          <div className="grid grid-cols-1 gap-5 md:grid-cols-2 lg:grid-cols-3">
            {PUBLIC_RESOURCES.map((resource) => (
              <Link
                key={resource.path}
                href={resource.path}
                className="group flex min-h-[250px] flex-col rounded-3xl border border-line bg-surface p-6 shadow-card transition hover:-translate-y-0.5 hover:border-brand/50 hover:shadow-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
              >
                <p className="text-[12px] font-extrabold tracking-[0.12em] text-brand">
                  {resource.kind === "tool" ? "계산기" : "실무 자료"}
                </p>
                <h3 className="mt-3 break-keep text-[21px] font-extrabold leading-snug text-brand-ink group-hover:text-brand">
                  {resource.title}
                </h3>
                <p className="mt-4 break-keep text-[14px] leading-7 text-ink3">
                  {resource.description}
                </p>
                <span className="mt-auto pt-6 text-[14px] font-bold text-brand">
                  {resource.actionLabel} <span aria-hidden="true">→</span>
                </span>
              </Link>
            ))}
          </div>
        </section>

        <aside className="mt-8 rounded-2xl border border-[#ccd8ff] bg-accent-tint p-5 text-[13px] leading-6 text-brand-ink">
          계산에 넣은 날짜와 체크 상태는 서버로 보내지 않아요. 고객 관리표는 내용이 비어 있는 양식으로 내려받습니다.
        </aside>

        <nav className="mt-14 flex flex-wrap justify-center gap-x-5 gap-y-2 text-[13px] text-ink3">
          <Link href="/" className="transition hover:text-ink">홈</Link>
          <Link href="/faq" className="transition hover:text-ink">자주 묻는 질문</Link>
          <Link href="/legal/terms" className="transition hover:text-ink">이용약관</Link>
          <Link href="/legal/privacy" className="transition hover:text-ink">개인정보처리방침</Link>
        </nav>
      </main>
    </div>
  );
}
