import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

// 실자산 manifest는 Task 7에서 채워진다. 여기서는 import 경계에 완전한 레코드만 주입해
// 렌더러가 빈 초기 manifest가 아닌 소유 자산을 처리하는 계약을 검증한다.
vi.mock("@/public/blog-assets/manifest.json", () => ({
  default: [
    {
      path: "/blog-assets/보험나이-계산법-6개월-예시/cover.webp",
      role: "cover",
      source_type: "generated-object",
      license: "generated-for-inpa",
      created_at: "2026-08-03",
      used_by: ["보험나이-계산법-6개월-예시"],
      pii_reviewed: true,
      rights_reviewed: true,
      width: 1600,
      height: 900,
      alt: "달력과 보험 증서를 상징하는 파란색 정물",
      caption: "보험나이 계산의 기준이 되는 생일 전후 6개월",
    },
  ],
}));

import { BlogCoverImage } from "@/components/blog-image";
import { BlogMarkdown } from "@/components/blog-markdown";
import { blogPosting } from "@/components/structured-data";
import { getBlogAsset } from "@/lib/blog-assets";

const ownedImagePath = "/blog-assets/보험나이-계산법-6개월-예시/cover.webp";

it("소유 이미지 렌더러는 매니페스트 import에서 자산 정보를 읽는다", () => {
  expect(getBlogAsset(ownedImagePath)).toMatchObject({ width: 1600, height: 900 });
});

it("블로그 구조화 데이터는 작성자를 인파 조직으로 참조한다", () => {
  const post = blogPosting({
    title: "보험나이 계산법",
    slug: "보험나이-계산법-6개월-예시",
    cover_image: ownedImagePath,
  });

  expect(post.author).toEqual({ "@id": "https://www.inpa.kr/#organization" });
});

it("블로그 구조화 데이터는 소유 커버 경로를 절대 URL로 정규화한다", () => {
  const post = blogPosting({
    title: "보험나이 계산법",
    slug: "보험나이-계산법-6개월-예시",
    cover_image: ownedImagePath,
  });

  expect(post.image).toBe("https://www.inpa.kr/blog-assets/보험나이-계산법-6개월-예시/cover.webp");
});

it("소유 커버는 장식 이미지로 크기와 반응형 sizes를 제공한다", () => {
  render(<BlogCoverImage src={ownedImagePath} categoryLabel="보장분석" />);

  const image = document.querySelector("img");
  expect(image).toHaveAttribute("alt", "");
  expect(image?.parentElement).toHaveStyle({ aspectRatio: "1600 / 900" });
  expect(image).toHaveAttribute("sizes");
});

it("마크다운의 소유 이미지는 대체 설명과 캡션이 있는 figure로 렌더한다", () => {
  render(<BlogMarkdown body={`![임의 텍스트](${ownedImagePath})`} />);

  expect(document.querySelector("figure")).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "달력과 보험 증서를 상징하는 파란색 정물" })).toBeInTheDocument();
  expect(screen.getByText("보험나이 계산의 기준이 되는 생일 전후 6개월")).toBeInTheDocument();
});
