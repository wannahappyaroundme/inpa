import Link from "next/link";

import { SEARCH_HUBS, type SearchHubContent } from "@/lib/search-content";
import { PUBLIC_RESOURCES } from "@/lib/public-resources";

function hubPath(hub: SearchHubContent): string {
  const segment = hub.kind === "solution" ? "solutions" : "guides";
  return `/${segment}/${hub.slug}`;
}

const SOLUTIONS = SEARCH_HUBS.filter((hub) => hub.kind === "solution");
const GUIDES = SEARCH_HUBS.filter((hub) => hub.kind === "guide");

function DiscoveryCards({ hubs }: { hubs: readonly SearchHubContent[] }) {
  const desktopColumns = hubs.length === 4 ? "lg:grid-cols-2" : "lg:grid-cols-3";
  return (
    <div className={`mt-6 grid gap-4 md:grid-cols-2 ${desktopColumns}`}>
      {hubs.map((hub) => (
        <Link
          key={hub.slug}
          href={hubPath(hub)}
          aria-label={hub.title}
          className="group rounded-2xl border border-[var(--line)] bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:border-[var(--brand)] hover:shadow-card focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--brand)] sm:p-6"
        >
          <h3 className="break-keep text-[17px] font-extrabold leading-snug text-[var(--brand-ink)] group-hover:text-[var(--brand)]">
            {hub.title}
          </h3>
          <p className="mt-3 line-clamp-3 break-keep text-[14px] leading-6 text-[var(--ink-3)]">
            {hub.description}
          </p>
          <span className="mt-5 inline-flex text-[13px] font-bold text-[var(--brand)]">
            자세히 보기
          </span>
        </Link>
      ))}
    </div>
  );
}

export function PublicDiscoverySection() {
  return (
    <section className="bg-[var(--canvas)] py-20 sm:py-24" aria-label="인파 솔루션과 실무 자료">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <div id="solutions" className="scroll-mt-24">
          <p className="text-sm font-extrabold tracking-wide text-[var(--brand)]">업무별로 살펴보기</p>
          <h2 className="mt-3 break-keep text-3xl font-extrabold tracking-tight text-[var(--brand-ink)] sm:text-4xl">
            설계사 업무별 솔루션
          </h2>
          <p className="mt-4 max-w-3xl break-keep text-[15px] leading-7 text-[var(--ink-3)]">
            고객 기록, 증권 정리, 영업 일정을 실제 인파 화면과 함께 확인해보세요.
          </p>
          <DiscoveryCards hubs={SOLUTIONS} />
        </div>

        <div id="guides" className="mt-16 scroll-mt-24 border-t border-[var(--line)] pt-16 sm:mt-20 sm:pt-20">
          <p className="text-sm font-extrabold tracking-wide text-[var(--brand)]">질문부터 바로 찾기</p>
          <h2 className="mt-3 break-keep text-3xl font-extrabold tracking-tight text-[var(--brand-ink)] sm:text-4xl">
            현장에서 바로 쓰는 실무 가이드
          </h2>
          <p className="mt-4 max-w-3xl break-keep text-[15px] leading-7 text-[var(--ink-3)]">
            첫 상담 준비부터 후속 연락, 증권 확인과 여러 증권 비교까지 순서대로 정리했습니다.
          </p>
          <DiscoveryCards hubs={GUIDES} />
        </div>

        <div id="tools" className="mt-16 scroll-mt-24 border-t border-[var(--line)] pt-16 sm:mt-20 sm:pt-20">
          <p className="text-sm font-extrabold tracking-wide text-[var(--brand)]">가입 전에도 활용하기</p>
          <h2 className="mt-3 break-keep text-3xl font-extrabold tracking-tight text-[var(--brand-ink)] sm:text-4xl">
            무료 자료
          </h2>
          <p className="mt-4 max-w-3xl break-keep text-[15px] leading-7 text-[var(--ink-3)]">
            날짜와 체크 상태는 서버로 보내지 않고, 고객 관리표는 빈 양식으로만 제공합니다.
          </p>
          <div className="mt-6 grid gap-4 md:grid-cols-3">
            {PUBLIC_RESOURCES.map((resource) => (
              <Link
                key={resource.path}
                href={resource.path}
                aria-label={resource.title}
                className="group rounded-2xl border border-[var(--line)] bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:border-[var(--brand)] hover:shadow-card focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--brand)] sm:p-6"
              >
                <p className="text-[12px] font-extrabold tracking-wide text-[var(--brand)]">
                  {resource.kind === "tool" ? "계산 도구" : "실무 양식"}
                </p>
                <h3 className="mt-2 break-keep text-[18px] font-extrabold leading-snug text-[var(--brand-ink)] group-hover:text-[var(--brand)]">
                  {resource.title}
                </h3>
                <p className="mt-3 break-keep text-[14px] leading-6 text-[var(--ink-3)]">
                  {resource.description}
                </p>
                <span className="mt-5 inline-flex text-[13px] font-bold text-[var(--brand)]">
                  {resource.actionLabel}
                </span>
              </Link>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

export function PublicDiscoveryLinks() {
  return (
    <nav
      aria-label="솔루션과 실무 자료"
      className="mt-12 rounded-2xl border border-[var(--line)] bg-[var(--surface-2)] p-5 sm:p-6"
    >
      <p className="text-[14px] font-extrabold text-[var(--brand-ink)]">업무에 맞는 설명을 바로 확인해보세요</p>
      <div className="mt-4 grid gap-x-6 gap-y-3 sm:grid-cols-2">
        {SEARCH_HUBS.map((hub) => (
          <Link
            key={`${hub.kind}-${hub.slug}`}
            href={hubPath(hub)}
            className="break-keep text-[13px] font-semibold leading-5 text-[var(--ink-2)] transition hover:text-[var(--brand)]"
          >
            {hub.title}
          </Link>
        ))}
      </div>
      <div className="mt-5 border-t border-[var(--line)] pt-5">
        <p className="text-[13px] font-extrabold text-[var(--brand-ink)]">무료 자료</p>
        <div className="mt-3 grid gap-x-6 gap-y-3 sm:grid-cols-2">
          {PUBLIC_RESOURCES.map((resource) => (
            <Link
              key={resource.path}
              href={resource.path}
              className="break-keep text-[13px] font-semibold leading-5 text-[var(--ink-2)] transition hover:text-[var(--brand)]"
            >
              {resource.title}
            </Link>
          ))}
        </div>
      </div>
    </nav>
  );
}
