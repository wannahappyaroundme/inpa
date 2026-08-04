import { beforeEach, expect, it, vi } from "vitest";

import sitemap from "@/app/sitemap";
import robots from "@/app/robots";
import { metadata as storyMetadata } from "@/app/story/page";
import { getSearchHubPaths } from "@/lib/search-content";
import { getPublicResourcePaths } from "@/lib/public-resources";
import { CURRENT_INDEXABLE_PATHS } from "@/lib/search-policy";

const api = vi.hoisted(() => ({
  getBlogSitemap: vi.fn(),
}));
const nextCache = vi.hoisted(() => ({
  state: { hasValue: false, value: undefined as unknown },
  unstableCache: vi.fn((callback: () => Promise<unknown>) => async () => {
    try {
      const value = await callback();
      nextCache.state.hasValue = true;
      nextCache.state.value = value;
      return value;
    } catch (error) {
      if (nextCache.state.hasValue) return nextCache.state.value;
      throw error;
    }
  }),
}));

vi.mock("@/lib/api", () => api);
vi.mock("next/cache", () => ({ unstable_cache: nextCache.unstableCache }));

beforeEach(() => {
  api.getBlogSitemap.mockReset();
  api.getBlogSitemap.mockResolvedValue([]);
  nextCache.state.hasValue = false;
  nextCache.state.value = undefined;
});

it("공식 인파 이야기 주소를 사이트맵에 제공한다", async () => {
  const entries = await sitemap();

  expect(entries).toContainEqual(
    expect.objectContaining({
      url: "https://www.inpa.kr/story",
      changeFrequency: "monthly",
    }),
  );
});

it("검색 로봇에 공식 인파 이야기 주소를 공개한다", () => {
  const rules = robots().rules;
  const firstRule = Array.isArray(rules) ? rules[0] : rules;

  expect(firstRule.allow).toContain("/story");
});

it("인파 이야기는 공유 미리보기에도 전용 주소와 문구를 제공한다", () => {
  expect(storyMetadata.openGraph).toMatchObject({
    url: "/story",
    title: "인파(Inpa) · 수많은 인파 속, 흔들림 없는 안내",
  });
  expect(storyMetadata.twitter).toMatchObject({
    card: "summary_large_image",
    title: "인파(Inpa) · 수많은 인파 속, 흔들림 없는 안내",
  });
});

it("사이트맵에는 공개 허용 목록과 근거 페이지 7개를 먼저 제공하고 법무 초안은 제외한다", async () => {
  const paths = (await sitemap()).map((row) => new URL(row.url).pathname);

  expect(paths.slice(0, CURRENT_INDEXABLE_PATHS.length)).toEqual(CURRENT_INDEXABLE_PATHS);
  expect(paths).toEqual(expect.arrayContaining(getSearchHubPaths()));
  expect(paths).toEqual(expect.arrayContaining(getPublicResourcePaths()));
  expect(paths).toContain("/blog/resources");
  expect(new Set(paths).size).toBe(paths.length);
  expect(paths).not.toContain("/legal/terms");
  expect(paths).not.toContain("/legal/privacy");
});

it("게시글은 slug 기준으로 중복 제거하고 잘못된 수정일은 생략한다", async () => {
  api.getBlogSitemap.mockResolvedValue([
    { slug: "b-post", updated_at: "not-a-date" },
    { slug: "a-post", updated_at: "2026-08-02T00:00:00Z" },
    { slug: "b-post", updated_at: "2026-08-03T00:00:00Z" },
  ]);

  const entries = await sitemap();
  const posts = entries.slice(CURRENT_INDEXABLE_PATHS.length);

  expect(posts.map((row) => new URL(row.url).pathname)).toEqual([
    "/blog/a-post",
    "/blog/b-post",
  ]);
  expect(posts[0].lastModified).toEqual(new Date("2026-08-02T00:00:00Z"));
  expect(posts[1].lastModified).toBeUndefined();
});

it("정적 무료 자료 주소와 같은 게시글은 사이트맵에 한 번만 제공한다", async () => {
  api.getBlogSitemap.mockResolvedValue([
    { slug: "resources", updated_at: "2026-08-04T00:00:00Z" },
  ]);

  const paths = (await sitemap()).map((row) => new URL(row.url).pathname);

  expect(paths.filter((path) => path === "/blog/resources")).toHaveLength(1);
});

it("게시글 sitemap은 Next last-good cache를 만들지 않는다", () => {
  expect(nextCache.unstableCache).not.toHaveBeenCalled();
});

it("최초 backend 조회부터 실패하면 정적 sitemap을 반환한다", async () => {
  api.getBlogSitemap.mockRejectedValue(new Error("upstream unavailable"));

  const paths = (await sitemap()).map((row) => new URL(row.url).pathname);

  expect(paths).toEqual(CURRENT_INDEXABLE_PATHS);
});

it("마지막 정상 목록이 있어도 다음 조회 실패 시 동적 글을 즉시 제외한다", async () => {
  api.getBlogSitemap.mockResolvedValueOnce([
    { slug: "now-noindex", updated_at: "2026-08-03T00:00:00Z" },
  ]);
  expect((await sitemap()).map((row) => new URL(row.url).pathname)).toContain(
    "/blog/now-noindex",
  );

  api.getBlogSitemap.mockRejectedValueOnce(new Error("upstream unavailable"));
  const paths = (await sitemap()).map((row) => new URL(row.url).pathname);

  expect(paths).toEqual(CURRENT_INDEXABLE_PATHS);
});
