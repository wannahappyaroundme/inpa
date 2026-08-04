import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SearchHubPage } from "@/components/search-hub-page";
import { PublicDiscoveryLinks, PublicDiscoverySection } from "@/components/public-discovery";
import { breadcrumbList, webPage } from "@/components/structured-data";
import * as guideRoute from "@/app/guides/[slug]/page";
import * as solutionRoute from "@/app/solutions/[slug]/page";
import { PUBLIC_INDEX_ROBOTS } from "@/lib/search-policy";
import { SEARCH_HUBS, getSearchHub, getSearchHubPaths } from "@/lib/search-content";
import { PUBLIC_RESOURCES } from "@/lib/public-resources";

const SITE_URL = "https://www.inpa.kr";
const sampleHub = SEARCH_HUBS[0];

describe("검색 근거 페이지 공통 템플릿", () => {
  it("답부터 시작해 대상, 순서, 증거, 확인표, 한계, FAQ와 다음 행동을 모두 렌더한다", () => {
    render(<SearchHubPage hub={sampleHub} />);

    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(sampleHub.title);
    expect(screen.getByText(sampleHub.answer)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "이런 분에게 맞아요" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "인파에서 하는 순서" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "실제 화면으로 확인" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "직접 확인할 항목" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "알아둘 점" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "자주 묻는 질문" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "관련해서 함께 보기" })).toBeInTheDocument();

    for (const item of sampleHub.fitFor) expect(screen.getByText(item)).toBeInTheDocument();
    for (const step of sampleHub.steps) {
      expect(screen.getByRole("heading", { name: step.title })).toBeInTheDocument();
      expect(screen.getByText(step.body)).toBeInTheDocument();
    }
    for (const evidence of sampleHub.evidence) {
      expect(screen.getByRole("img", { name: evidence.alt })).toBeInTheDocument();
      expect(screen.getByText(evidence.caption)).toBeInTheDocument();
    }
    for (const item of sampleHub.limitations) expect(screen.getByText(item)).toBeInTheDocument();
    for (const item of sampleHub.faq) {
      expect(screen.getByText(item.q)).toBeInTheDocument();
      expect(screen.getByText(item.a)).toBeInTheDocument();
    }

    expect(screen.getByRole("link", { name: "첫 분석 무료로 시작하기" })).toHaveAttribute(
      "href",
      "/register",
    );
  });

  it("공개 메뉴에서 홈, 솔루션, 실무 가이드, 블로그와 FAQ로 이동한다", () => {
    render(<SearchHubPage hub={sampleHub} />);

    const nav = screen.getByRole("navigation", { name: "공개 메뉴" });
    expect(nav).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "인파 홈" })).toHaveAttribute("href", "/");
    expect(within(nav).getByRole("link", { name: "솔루션" })).toHaveAttribute("href", "/#solutions");
    expect(within(nav).getByRole("link", { name: "실무 가이드" })).toHaveAttribute("href", "/#guides");
    expect(within(nav).getByRole("link", { name: "블로그" })).toHaveAttribute("href", "/blog");
    expect(within(nav).getByRole("link", { name: "자주 묻는 질문" })).toHaveAttribute("href", "/faq");
  });

  it("현재 canonical과 일치하는 WebPage, Breadcrumb, FAQ 구조화 데이터를 넣는다", () => {
    const { container } = render(<SearchHubPage hub={sampleHub} />);
    const scripts = Array.from(
      container.querySelectorAll<HTMLScriptElement>('script[type="application/ld+json"]'),
    );
    const schemas = scripts.flatMap((script) => {
      const parsed = JSON.parse(script.textContent || "null");
      return Array.isArray(parsed) ? parsed : [parsed];
    });
    const currentUrl = `${SITE_URL}${getSearchHubPaths()[0]}`;
    const pageSchema = schemas.find((schema) => schema["@type"] === "WebPage");
    const crumbsSchema = schemas.find((schema) => schema["@type"] === "BreadcrumbList");
    const faqSchema = schemas.find((schema) => schema["@type"] === "FAQPage");

    expect(pageSchema.url).toBe(currentUrl);
    expect(pageSchema.dateModified).toBe(sampleHub.updatedAt);
    expect(crumbsSchema.itemListElement[0].item).toBe(`${SITE_URL}/`);
    expect(crumbsSchema.itemListElement.at(-1).item).toBe(currentUrl);
    expect(faqSchema.mainEntity).toHaveLength(sampleHub.faq.length);
  });
});

describe("공개 페이지 발견 경로", () => {
  it("랜딩에서 솔루션 3개, 실무 가이드 4개와 무료 자료 3개를 직접 연결한다", () => {
    render(<PublicDiscoverySection />);

    expect(screen.getByRole("heading", { name: "설계사 업무별 솔루션" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "현장에서 바로 쓰는 실무 가이드" })).toBeInTheDocument();
    for (const hub of SEARCH_HUBS) {
      const path = `/${hub.kind === "solution" ? "solutions" : "guides"}/${hub.slug}`;
      expect(screen.getByRole("link", { name: hub.title })).toHaveAttribute("href", path);
    }
    expect(screen.getByRole("heading", { name: "무료 자료" })).toBeInTheDocument();
    for (const resource of PUBLIC_RESOURCES) {
      expect(screen.getByRole("link", { name: resource.title })).toHaveAttribute("href", resource.path);
    }
  });

  it("FAQ와 블로그에서 재사용할 간단한 링크도 허브와 도구 원문으로 직접 이어진다", () => {
    render(<PublicDiscoveryLinks />);

    const nav = screen.getByRole("navigation", { name: "솔루션과 실무 자료" });
    expect(within(nav).getAllByRole("link")).toHaveLength(SEARCH_HUBS.length + PUBLIC_RESOURCES.length);
    for (const path of getSearchHubPaths()) {
      expect(within(nav).getByRole("link", { name: SEARCH_HUBS[getSearchHubPaths().indexOf(path)].title }))
        .toHaveAttribute("href", path);
    }
    for (const resource of PUBLIC_RESOURCES) {
      expect(within(nav).getByRole("link", { name: resource.title })).toHaveAttribute("href", resource.path);
    }
  });
});

describe("검색 근거 구조화 데이터 helper", () => {
  it("상대 경로를 절대 URL로 만들고 정적 사실만 반환한다", () => {
    expect(
      breadcrumbList([
        { name: "홈", url: "/" },
        { name: sampleHub.title, url: getSearchHubPaths()[0] },
      ]),
    ).toMatchObject({
      "@type": "BreadcrumbList",
      itemListElement: [
        { "@type": "ListItem", position: 1, name: "홈", item: `${SITE_URL}/` },
        {
          "@type": "ListItem",
          position: 2,
          name: sampleHub.title,
          item: `${SITE_URL}${getSearchHubPaths()[0]}`,
        },
      ],
    });
    expect(
      webPage({
        name: sampleHub.title,
        description: sampleHub.description,
        url: getSearchHubPaths()[0],
        dateModified: sampleHub.updatedAt,
      }),
    ).toMatchObject({
      "@type": "WebPage",
      name: sampleHub.title,
      description: sampleHub.description,
      url: `${SITE_URL}${getSearchHubPaths()[0]}`,
      dateModified: sampleHub.updatedAt,
      inLanguage: "ko-KR",
    });
  });
});

describe("검색 근거 정적 route", () => {
  it("솔루션 3개와 실무 가이드 4개만 정적으로 생성한다", async () => {
    expect(solutionRoute.dynamicParams).toBe(false);
    expect(guideRoute.dynamicParams).toBe(false);
    expect(await solutionRoute.generateStaticParams()).toEqual([
      { slug: "customer-management" },
      { slug: "policy-analysis" },
      { slug: "sales-management" },
    ]);
    expect(await guideRoute.generateStaticParams()).toEqual([
      { slug: "first-consultation" },
      { slug: "customer-follow-up" },
      { slug: "policy-review" },
      { slug: "factual-comparison" },
    ]);
  });

  it.each([
    ["solution", "customer-management", solutionRoute.generateMetadata],
    ["guide", "first-consultation", guideRoute.generateMetadata],
  ] as const)("%s 샘플 route에 고유 검색 메타데이터를 넣는다", async (kind, slug, generateMetadata) => {
    const hub = getSearchHub(kind, slug)!;
    const path = `/${kind === "solution" ? "solutions" : "guides"}/${slug}`;
    const metadata = await generateMetadata({ params: Promise.resolve({ slug }) });

    expect(metadata.title).toBe(hub.title);
    expect(metadata.description).toBe(hub.description);
    expect(metadata.alternates).toEqual({ canonical: path });
    expect(metadata.robots).toEqual(PUBLIC_INDEX_ROBOTS);
    expect(metadata.openGraph).toMatchObject({
      type: "website",
      title: hub.title,
      description: hub.description,
      url: path,
    });
    expect(metadata.openGraph?.images).toEqual([
      { url: hub.evidence[0].src, width: 2880, height: 1800, alt: hub.evidence[0].alt },
    ]);
  });
});
