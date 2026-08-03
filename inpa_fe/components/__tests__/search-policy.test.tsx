import { beforeEach, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

const api = vi.hoisted(() => ({
  getBlogPost: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  ...api,
  BLOG_CATEGORIES: [],
  ApiError: class ApiError extends Error {
    status?: number;
  },
}));

import { metadata as rootMetadata } from "@/app/layout";
import { metadata as landingMetadata } from "@/app/page";
import { metadata as storyMetadata } from "@/app/story/page";
import { metadata as faqMetadata } from "@/app/faq/page";
import { metadata as blogMetadata } from "@/app/blog/page";
import { generateMetadata as generateBlogMetadata } from "@/app/blog/[slug]/page";
import DataPolicyPage, { metadata as dataPolicyMetadata } from "@/app/data-policy/page";
import robots from "@/app/robots";
import { classifySearchPath } from "@/lib/search-policy";

const blogPost = {
  id: 1,
  title: "공개 글",
  slug: "public-post",
  excerpt: "공개 글 요약",
  body: "공개 글 본문",
  cover_image: null,
  category: "sales",
  category_label: "고객 늘리기",
  tags: [],
  author_name: "인파 담당자",
  published_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-02T00:00:00Z",
  created_at: "2026-08-01T00:00:00Z",
  view_count: 0,
  seo_title: "",
  seo_description: "",
  is_noindex: false,
  legal_review_public: null,
  related_posts: [],
};

beforeEach(() => {
  api.getBlogPost.mockReset();
});

it("루트는 기본 차단하고 현재 공개 정적 페이지만 명시적으로 색인한다", () => {
  expect(rootMetadata.robots).toEqual({ index: false, follow: false });
  expect(landingMetadata.robots).toEqual({ index: true, follow: true });
  expect(storyMetadata.robots).toEqual({ index: true, follow: true });
  expect(faqMetadata.robots).toEqual({ index: true, follow: true });
  expect(blogMetadata.robots).toEqual({ index: true, follow: true });
  expect(dataPolicyMetadata.robots).toEqual({ index: true, follow: true });
  expect(dataPolicyMetadata.alternates).toEqual({ canonical: "/data-policy" });
});

it("공개 블로그 글만 색인하고 noindex 글은 계속 차단한다", async () => {
  api.getBlogPost
    .mockResolvedValueOnce(blogPost)
    .mockResolvedValueOnce({ ...blogPost, slug: "blocked-post", is_noindex: true });

  const publicMetadata = await generateBlogMetadata({
    params: Promise.resolve({ slug: "public-post" }),
  });
  const blockedMetadata = await generateBlogMetadata({
    params: Promise.resolve({ slug: "blocked-post" }),
  });

  expect(publicMetadata.robots).toEqual({ index: true, follow: true });
  expect(blockedMetadata.robots).toEqual({ index: false, follow: false });
});

it("검색 및 AI 봇에도 민감한 공개 링크 차단 규칙을 적용한다", () => {
  const rules = JSON.stringify(robots().rules);

  expect(rules).toContain("/s/");
  expect(rules).toContain("OAI-SearchBot");
});

it("경로를 exact 및 segment boundary로 분류하고 부분 문자열은 허용하지 않는다", () => {
  expect(classifySearchPath("/")).toBe("indexable");
  expect(classifySearchPath("/blog/public-post")).toBe("indexable");
  expect(classifySearchPath("/solutions/customer-management")).toBe("indexable");
  expect(classifySearchPath("/guides/factual-comparison")).toBe("indexable");
  expect(classifySearchPath("/solutions/customer-management/extra")).toBe("private_or_utility");
  expect(classifySearchPath("/guides/not-published")).toBe("private_or_utility");
  expect(classifySearchPath("/customers")).toBe("private_or_utility");
  expect(classifySearchPath("/blogger")).toBe("private_or_utility");
});

it("데이터 처리 안내는 현재 공개 범위와 문의 경로를 정확히 설명한다", () => {
  render(<DataPolicyPage />);

  expect(screen.queryByText(/정식 출시 시 게재/)).not.toBeInTheDocument();
  expect(screen.queryByText(/동의가 없으면 분석 호출 자체가 차단/)).not.toBeInTheDocument();
  expect(screen.queryByText(/병력 등 민감정보가 포함된 분석/)).not.toBeInTheDocument();
  expect(screen.getByText(/검토형 증권 정리는.*기본 설정은 닫혀 있습니다/)).toBeInTheDocument();
  expect(screen.getByText(/먼저 고객 동의를 확인합니다/)).toBeInTheDocument();
  expect(screen.getByText(/외부 AI 서비스로 전송될 수 있습니다/)).toBeInTheDocument();
  expect(screen.getByText(/해당 설계사 계정에서만 확인할 수 있습니다/)).toBeInTheDocument();
  expect(screen.getByText(/원본 파일은 증권 정리 결과를 확정하거나 작업을 취소하면 정리합니다/)).toBeInTheDocument();
  expect(screen.getByText(/설계사가 탈퇴하면/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "계정 설정" })).toHaveAttribute(
    "href",
    "/settings/account",
  );
  expect(screen.getByRole("link", { name: "hello.fingo.official@gmail.com" })).toHaveAttribute(
    "href",
    "mailto:hello.fingo.official@gmail.com",
  );
});

it("민감 base path와 하위 경로만 sensitive로 분류한다", () => {
  const sensitivePaths = [
    ["/s", "/s/secret"],
    ["/b", "/b/secret"],
    ["/c", "/c/secret"],
    ["/d", "/d/secret"],
    ["/p", "/p/secret"],
    ["/r", "/r/secret"],
    ["/recruiting/join", "/recruiting/join/secret"],
  ] as const;

  for (const [basePath, childPath] of sensitivePaths) {
    expect(classifySearchPath(basePath)).toBe("sensitive");
    expect(classifySearchPath(childPath)).toBe("sensitive");
  }

  for (const nearMiss of [
    "/sensitive",
    "/booking",
    "/customers",
    "/dashboard",
    "/pricing",
    "/register",
    "/recruiting/joined",
  ]) {
    expect(classifySearchPath(nearMiss)).toBe("private_or_utility");
  }

  expect(classifySearchPath("/admin")).toBe("private_or_utility");
  expect(classifySearchPath("/api")).toBe("private_or_utility");
});
