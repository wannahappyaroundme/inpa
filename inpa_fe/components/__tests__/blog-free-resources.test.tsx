import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import BlogResourcesPage, { metadata } from "@/app/blog/resources/page";
import { BlogSectionTabs } from "@/components/blog-section-tabs";
import { PUBLIC_INDEX_ROBOTS } from "@/lib/search-policy";

it("인파 블로그와 무료 자료를 독립 주소의 1차 탭으로 제공한다", () => {
  render(<BlogSectionTabs activeSection="resources" />);

  expect(screen.getByRole("link", { name: "인파 블로그" })).toHaveAttribute("href", "/blog");
  expect(screen.getByRole("link", { name: "무료 자료" })).toHaveAttribute("href", "/blog/resources");
  expect(screen.getByRole("link", { name: "무료 자료" })).toHaveAttribute("aria-current", "page");
});

it("무료 자료 화면에서 기존 자료 세 주소로 이동한다", () => {
  render(<BlogResourcesPage />);

  expect(screen.getByRole("heading", { level: 1, name: "무료 자료" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /보험나이 계산기/ })).toHaveAttribute(
    "href",
    "/tools/insurance-age",
  );
  expect(screen.getByRole("link", { name: /고객 관리표 빈 양식/ })).toHaveAttribute(
    "href",
    "/resources/customer-management-sheet",
  );
  expect(screen.getByRole("link", { name: /첫 상담 체크리스트/ })).toHaveAttribute(
    "href",
    "/resources/consultation-checklist",
  );
});

it("무료 자료 모음은 고유 canonical과 공개 색인 정책을 쓴다", () => {
  expect(metadata.alternates).toEqual({ canonical: "/blog/resources" });
  expect(metadata.robots).toEqual(PUBLIC_INDEX_ROBOTS);
  expect(metadata.openGraph).toMatchObject({ url: "/blog/resources" });
});
