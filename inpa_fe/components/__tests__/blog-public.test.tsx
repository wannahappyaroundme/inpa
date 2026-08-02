import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const analytics = vi.hoisted(() => ({ track: vi.fn() }));
const api = vi.hoisted(() => ({
  listBlogPosts: vi.fn(),
  getBlogPost: vi.fn(),
}));

vi.mock("@vercel/analytics", () => ({ track: analytics.track }));
vi.mock("@/lib/api", () => ({
  ...api,
  BLOG_CATEGORIES: [
    { code: "sales", label: "고객 늘리기" },
    { code: "coverage", label: "보장분석" },
    { code: "safety", label: "안심 가이드" },
    { code: "story", label: "설계사 이야기" },
  ],
  ApiError: class ApiError extends Error {
    status?: number;
  },
}));

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
import { BlogContentImage } from "@/components/blog-content-image";
import { BlogAnalytics, TrackedBlogCta } from "@/components/blog-analytics";
import { BlogMarkdown } from "@/components/blog-markdown";
import { blogPosting } from "@/components/structured-data";
import { getBlogAsset } from "@/lib/blog-assets";
import BlogListPage from "@/app/blog/page";
import BlogPostPage from "@/app/blog/[slug]/page";

const ownedImagePath = "/blog-assets/보험나이-계산법-6개월-예시/cover.webp";

const publishedAt = "2026-08-01T03:00:00Z";
const updatedAt = "2026-08-02T03:00:00Z";

const listPost = {
  id: 101,
  title: "보험나이, 생일 전후 6개월로 쉽게 계산하기",
  slug: "보험나이-계산법-6개월-예시",
  excerpt: "생일 전후 6개월 기준을 알면 보험나이를 바로 확인할 수 있어요.",
  cover_image: ownedImagePath,
  category: "coverage" as const,
  category_label: "보장분석",
  tags: ["보험나이", "보장분석"],
  author_name: "인파 담당자",
  published_at: publishedAt,
  view_count: 42,
};

const relatedPosts = [
  {
    id: 102,
    title: "보장 내용을 고객에게 쉽게 설명하는 순서",
    slug: "보장-설명-순서",
    excerpt: "고객이 이해하기 쉬운 상담 순서를 정리했어요.",
    cover_image: null,
    category: "sales" as const,
    category_label: "고객 늘리기",
    published_at: publishedAt,
  },
  {
    id: 103,
    title: "갱신형 보험료를 확인하는 방법",
    slug: "갱신형-보험료-확인",
    excerpt: "보험료 변화를 보기 전 확인할 항목이에요.",
    cover_image: null,
    category: "coverage" as const,
    category_label: "보장분석",
    published_at: publishedAt,
  },
  {
    id: 104,
    title: "고객 안내 전에 확인할 약속",
    slug: "고객-안내-약속",
    excerpt: "안내 내용을 차분히 정리하는 방법을 소개합니다.",
    cover_image: null,
    category: "safety" as const,
    category_label: "안심 가이드",
    published_at: publishedAt,
  },
];

const detailPost = {
  ...listPost,
  body: "## 보험나이\n\n생일 전후 6개월을 기준으로 계산합니다.",
  updated_at: updatedAt,
  created_at: "2026-07-31T03:00:00Z",
  seo_title: "보험나이 계산법",
  seo_description: "보험나이를 쉽게 계산하는 방법",
  is_noindex: false,
  related_posts: relatedPosts,
};

beforeEach(() => {
  analytics.track.mockReset();
  api.listBlogPosts.mockReset();
  api.getBlogPost.mockReset();
  Object.defineProperty(document, "referrer", { configurable: true, value: "" });
  window.history.replaceState({}, "", "/blog");
});

afterEach(() => vi.clearAllMocks());

it("Strict Mode 재실행에도 글 조회 분석은 마운트당 한 번만 보낸다", () => {
  render(
    <StrictMode>
      <BlogAnalytics slug="보험나이-계산법-6개월-예시" category="coverage" />
    </StrictMode>
  );

  expect(analytics.track).toHaveBeenCalledTimes(1);
  expect(analytics.track).toHaveBeenCalledWith("blog_view", {
    slug: "보험나이-계산법-6개월-예시",
    category: "coverage",
    referrer_class: "direct",
    utm_source: "none",
    utm_medium: "none",
    utm_campaign: "absent",
  });
});

it("글 CTA는 허용된 UTM 분류만 보내고 임의 원문은 남기지 않는다", async () => {
  window.history.replaceState(
    {},
    "",
    "/blog/보험나이-계산법-6개월-예시?utm_source=Jane.Doe%40example.com&utm_medium=Secret%20Campaign&utm_campaign=Customer%20Kim&customer=never-send"
  );
  const user = userEvent.setup();
  render(
    <div onClick={(event) => event.preventDefault()}>
      <TrackedBlogCta slug="보험나이-계산법-6개월-예시" category="coverage" href="/register">
        무료로 먼저 확인해보기
      </TrackedBlogCta>
    </div>
  );

  const cta = screen.getByRole("link", { name: "무료로 먼저 확인해보기" });
  expect(cta).toHaveAttribute("href", "/register");
  await user.click(cta);

  expect(analytics.track).toHaveBeenCalledTimes(1);
  expect(analytics.track).toHaveBeenCalledWith("blog_cta_click", {
    slug: "보험나이-계산법-6개월-예시",
    category: "coverage",
    destination: "register",
    referrer_class: "direct",
    utm_source: "other",
    utm_medium: "other",
    utm_campaign: "present",
  });
  expect(JSON.stringify(analytics.track.mock.calls)).not.toContain("Jane.Doe");
  expect(JSON.stringify(analytics.track.mock.calls)).not.toContain("Secret Campaign");
  expect(JSON.stringify(analytics.track.mock.calls)).not.toContain("Customer Kim");
});

it("대소문자가 섞인 허용 UTM은 정규화된 enum으로 전송한다", () => {
  window.history.replaceState({}, "", "/blog?utm_source=GOOGLE&utm_medium=CPC&utm_campaign=August");
  render(<BlogAnalytics slug="보험나이-계산법-6개월-예시" category="coverage" />);

  expect(analytics.track).toHaveBeenCalledWith("blog_view", {
    slug: "보험나이-계산법-6개월-예시",
    category: "coverage",
    referrer_class: "direct",
    utm_source: "google",
    utm_medium: "cpc",
    utm_campaign: "present",
  });
});

it("빈 캠페인은 absent로 전송한다", () => {
  window.history.replaceState({}, "", "/blog?utm_campaign=");
  render(<BlogAnalytics slug="보험나이-계산법-6개월-예시" category="coverage" />);

  expect(analytics.track).toHaveBeenLastCalledWith("blog_view", expect.objectContaining({ utm_campaign: "absent" }));
});

it("공백뿐인 캠페인은 absent로 전송한다", () => {
  window.history.replaceState({}, "", "/blog?utm_campaign=%20%20%20");
  render(<BlogAnalytics slug="보험나이-계산법-6개월-예시" category="coverage" />);

  expect(analytics.track).toHaveBeenLastCalledWith("blog_view", expect.objectContaining({ utm_campaign: "absent" }));
});

it("80자를 넘는 PII 형태 캠페인도 present enum만 전송한다", () => {
  const rawCampaign = `jane.doe+${"x".repeat(90)}@example.com`;
  window.history.replaceState({}, "", `/blog?utm_campaign=${encodeURIComponent(rawCampaign)}`);
  render(<BlogAnalytics slug="보험나이-계산법-6개월-예시" category="coverage" />);

  expect(analytics.track).toHaveBeenCalledWith("blog_view", expect.objectContaining({ utm_campaign: "present" }));
  expect(JSON.stringify(analytics.track.mock.calls)).not.toContain(rawCampaign);
  expect(JSON.stringify(analytics.track.mock.calls)).not.toContain(rawCampaign.slice(0, 80));
});

it("분석 전송 실패도 CTA의 기본 이동을 취소하지 않는다", () => {
  analytics.track.mockImplementation(() => {
    throw new Error("analytics unavailable");
  });
  const defaultPrevented: boolean[] = [];
  render(
    <div onClick={(event) => {
      defaultPrevented.push(event.defaultPrevented);
      event.preventDefault();
    }}>
      <TrackedBlogCta slug="보험나이-계산법-6개월-예시" category="coverage" href="/register">
        무료로 먼저 확인해보기
      </TrackedBlogCta>
    </div>
  );

  fireEvent.click(screen.getByRole("link", { name: "무료로 먼저 확인해보기" }));
  expect(defaultPrevented).toEqual([false]);
});

it("목록 카드는 작성자 반복 없이 제목·요약·날짜만 보여준다", async () => {
  api.listBlogPosts.mockResolvedValue({ count: 1, next: null, previous: null, results: [listPost] });

  render(await BlogListPage({ searchParams: Promise.resolve({}) }));

  expect(screen.getByRole("heading", { name: listPost.title })).toBeInTheDocument();
  expect(screen.getByText(listPost.excerpt)).toBeInTheDocument();
  expect(screen.getByText("2026년 8월 1일")).toBeInTheDocument();
  expect(screen.queryByText("인파 담당자")).not.toBeInTheDocument();
});

it("상세는 작성자·발행 및 수정일·관련 글 세 편·공식 안내를 한 번만 보여준다", async () => {
  api.getBlogPost.mockResolvedValue(detailPost);

  render(await BlogPostPage({ params: Promise.resolve({ slug: detailPost.slug }) }));

  expect(screen.getByText("인파 담당자")).toBeInTheDocument();
  expect(screen.getByText("발행 2026년 8월 1일")).toBeInTheDocument();
  expect(screen.getByText("수정 2026년 8월 2일")).toBeInTheDocument();
  for (const post of relatedPosts) {
    expect(screen.getByRole("heading", { name: post.title, level: 3 }).closest("a")).toHaveAttribute("href", `/blog/${post.slug}`);
  }
  expect(
    screen.getAllByText("인파는 보험을 중개·권유하지 않는 분석·정리 소프트웨어입니다. 보장 판단과 고객 안내는 설계사님의 업무입니다.")
  ).toHaveLength(1);
});

it("상세 페이지에는 추적되는 가입 CTA 하나만 보여준다", async () => {
  api.getBlogPost.mockResolvedValue(detailPost);
  render(await BlogPostPage({ params: Promise.resolve({ slug: detailPost.slug }) }));

  const registerCtas = screen.getAllByRole("link").filter((link) => link.getAttribute("href") === "/register");
  expect(registerCtas).toHaveLength(1);
  expect(registerCtas[0]).toHaveTextContent("무료로 먼저 확인해보기");

  analytics.track.mockReset();
  registerCtas[0].addEventListener("click", (event) => event.preventDefault(), { once: true });
  fireEvent.click(registerCtas[0]);
  expect(analytics.track).toHaveBeenCalledWith("blog_cta_click", expect.objectContaining({
    slug: detailPost.slug,
    category: detailPost.category,
    destination: "register",
  }));
});

it("안심 가이드도 별도 법률 안내를 더하지 않고 공식 안내만 한 번 보여준다", async () => {
  const safetyPost = {
    ...detailPost,
    slug: "고객-안내-약속",
    category: "safety" as const,
    category_label: "안심 가이드",
  };
  api.getBlogPost.mockResolvedValue(safetyPost);

  render(await BlogPostPage({ params: Promise.resolve({ slug: safetyPost.slug }) }));

  expect(
    screen.queryByText("이 글은 일반적인 정보를 정리한 참고 자료예요. 법률 자문이 아니며, 실제 적용은 소속사 컴플라이언스와 금융감독원 안내를 함께 확인해 주세요.")
  ).not.toBeInTheDocument();
  expect(
    screen.getAllByText("인파는 보험을 중개·권유하지 않는 분석·정리 소프트웨어입니다. 보장 판단과 고객 안내는 설계사님의 업무입니다.")
  ).toHaveLength(1);
});

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

it("서버 호환 본문 이미지 렌더러는 대체 설명과 캡션이 있는 figure를 만든다", () => {
  render(<BlogContentImage src={ownedImagePath} />);

  expect(document.querySelector("figure")).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "달력과 보험 증서를 상징하는 파란색 정물" })).toBeInTheDocument();
  expect(screen.getByText("보험나이 계산의 기준이 되는 생일 전후 6개월")).toBeInTheDocument();
});

it("마크다운의 독립된 소유 이미지는 문단 안에 figure를 넣지 않는다", () => {
  render(<BlogMarkdown body={`![임의 텍스트](${ownedImagePath})`} />);

  const figure = document.querySelector("figure");
  expect(figure).toBeInTheDocument();
  expect(figure?.parentElement?.tagName).not.toBe("P");
});

it("매니페스트에 없는 본문 자산 경로는 이미지를 렌더하지 않는다", () => {
  render(<BlogMarkdown body="![](/blog-assets/없는-자산.webp)" />);

  expect(document.querySelector("figure")).not.toBeInTheDocument();
  expect(document.querySelector("img")).not.toBeInTheDocument();
});

it("외부 본문 이미지 URL은 이미지를 렌더하지 않는다", () => {
  render(<BlogMarkdown body="![](https://example.com/external.webp)" />);

  expect(document.querySelector("figure")).not.toBeInTheDocument();
  expect(document.querySelector("img")).not.toBeInTheDocument();
});
