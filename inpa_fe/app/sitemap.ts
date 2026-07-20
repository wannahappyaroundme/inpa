// sitemap.xml 생성 (Next 파일 컨벤션 — /sitemap.xml 로 서빙).
// 정적 공개 페이지(랜딩·인파 이야기·FAQ·약관·개인정보·데이터 처리) + 인파 노트 목록(/blog) +
// 게시된 인파 노트 글(BE sitemap 엔드포인트로 동적 열거).
//
// ★ force-dynamic: 요청 시점 생성 → (1) 빌드가 BE 를 부르지 않아 BE 다운 시에도 빌드 안전,
//   (2) 새 글이 재배포 없이 즉시 사이트맵에 반영. BE 호출은 try/catch 로 감싸 실패해도
//   정적 목록만으로 항상 유효한 사이트맵을 반환한다(민감정보 로그 없음).
import type { MetadataRoute } from "next";
import { getBlogSitemap } from "@/lib/api";

export const dynamic = "force-dynamic";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://www.inpa.kr";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const staticEntries: MetadataRoute.Sitemap = [
    { url: `${SITE_URL}/`, changeFrequency: "weekly", priority: 1 },
    { url: `${SITE_URL}/story`, changeFrequency: "monthly", priority: 0.6 },
    { url: `${SITE_URL}/blog`, changeFrequency: "weekly", priority: 0.7 },
    { url: `${SITE_URL}/faq`, changeFrequency: "monthly", priority: 0.6 },
    { url: `${SITE_URL}/legal/terms`, changeFrequency: "monthly", priority: 0.3 },
    { url: `${SITE_URL}/legal/privacy`, changeFrequency: "monthly", priority: 0.3 },
    { url: `${SITE_URL}/data-policy`, changeFrequency: "monthly", priority: 0.3 },
  ];

  let postEntries: MetadataRoute.Sitemap = [];
  try {
    const rows = await getBlogSitemap();
    postEntries = rows.map((r) => ({
      url: `${SITE_URL}/blog/${r.slug}`,
      lastModified: r.updated_at ? new Date(r.updated_at) : undefined,
      changeFrequency: "monthly",
      priority: 0.6,
    }));
  } catch {
    // BE 연결 실패(빌드/일시 장애) — 정적 목록만으로 유효한 사이트맵 반환. 조용히 폴백.
  }

  return [...staticEntries, ...postEntries];
}
