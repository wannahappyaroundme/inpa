import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { ServiceLanding } from "@/components/service-landing";

vi.mock("@vercel/analytics", () => ({ track: vi.fn() }));

vi.mock("@/components/landing-product-gallery", () => ({
  LandingProductGallery: () => <div>제품 화면 갤러리</div>,
}));

vi.mock("@/components/brand-story-sections", () => ({
  PricingFourTiers: ({ id, registerHref }: { id?: string; registerHref?: string }) => (
    <section id={id}>
      <h2>공용 4단 요금표</h2>
      <a href={registerHref}>무료로 시작하기</a>
    </section>
  ),
}));

it("메인 랜딩은 베타 안내 대신 공용 4단 요금표를 사용한다", () => {
  render(<ServiceLanding />);

  expect(screen.getByRole("heading", { name: "공용 4단 요금표" })).toBeInTheDocument();
  expect(document.querySelector("#pricing")).toBeInTheDocument();
});

it("메인 랜딩은 헤더, 본문, 푸터를 독립된 접근성 영역으로 제공한다", () => {
  render(<ServiceLanding />);

  expect(screen.getByRole("banner")).toBeInTheDocument();
  expect(screen.getByRole("main")).toBeInTheDocument();
  expect(screen.getByRole("contentinfo")).toBeInTheDocument();
});

it("메인 랜딩은 이야기, 블로그, 문의의 공식 www 링크를 제공한다", () => {
  render(<ServiceLanding />);

  expect(screen.getByRole("link", { name: "인파 이야기 60초 보기" })).toHaveAttribute(
    "href",
    "/story",
  );
  const blogLinks = screen.getAllByRole("link", { name: "인파 노트" });
  expect(blogLinks.length).toBeGreaterThanOrEqual(2);
  blogLinks.forEach((link) => expect(link).toHaveAttribute("href", "/blog"));
  expect(screen.getByRole("link", { name: "문의" })).toHaveAttribute(
    "href",
    "mailto:hello.fingo.official@gmail.com",
  );
});
