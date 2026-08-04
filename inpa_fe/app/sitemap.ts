// sitemap.xml 생성 (Next 파일 컨벤션, /sitemap.xml 로 서빙).
// 정적 공개 페이지(랜딩·검색 허브·무료 자료·인파 이야기·FAQ·데이터 처리) + 인파 블로그 목록(/blog) +
// 게시된 인파 블로그 글(BE sitemap 엔드포인트로 동적 열거).
//
// force-dynamic으로 빌드 중 BE 호출을 피하고, 요청마다 최신 공개 목록을 확인한다.
// 조회가 실패하면 동적 글을 모두 제외하고 정적 목록만 반환한다.
// 오류에는 URL이나 응답 본문을 기록하지 않는다.
import type { MetadataRoute } from "next";
import { getBlogSitemap } from "@/lib/api";
import { staticSitemapEntries } from "@/lib/search-policy";

export const dynamic = "force-dynamic";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://www.inpa.kr";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const staticEntries = staticSitemapEntries(SITE_URL);

  let postEntries: MetadataRoute.Sitemap = [];
  try {
    const rows = await getBlogSitemap();
    const seen = new Set<string>();
    postEntries = rows
      .filter((row) => {
        if (seen.has(row.slug)) return false;
        seen.add(row.slug);
        return true;
      })
      .sort((a, b) => a.slug.localeCompare(b.slug))
      .map((row) => {
        const updatedAt = row.updated_at ? new Date(row.updated_at) : undefined;
        const lastModified = updatedAt && !Number.isNaN(updatedAt.getTime()) ? updatedAt : undefined;
        return {
          url: `${SITE_URL}/blog/${row.slug}`,
          lastModified,
          changeFrequency: "monthly" as const,
          priority: 0.6,
        };
      });
  } catch {
    // BE 연결 실패(빌드/일시 장애) — 정적 목록만으로 유효한 사이트맵 반환. 조용히 폴백.
  }

  return [...staticEntries, ...postEntries];
}
