import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SearchHubPage } from "@/components/search-hub-page";
import { breadcrumbList, webPage } from "@/components/structured-data";
import { SEARCH_HUBS, getSearchHubPaths } from "@/lib/search-content";

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
