import { expect, it, vi } from "vitest";

import sitemap from "@/app/sitemap";
import robots from "@/app/robots";
import { metadata as storyMetadata } from "@/app/story/page";

vi.mock("@/lib/api", () => ({
  getBlogSitemap: vi.fn().mockResolvedValue([]),
}));

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
