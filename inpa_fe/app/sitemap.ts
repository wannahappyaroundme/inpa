// sitemap.xml 생성 (Next 파일 컨벤션 — /sitemap.xml 로 서빙).
// 검색 노출 대상은 공개 페이지 5개: 랜딩 + FAQ + 이용약관 + 개인정보처리방침 + 데이터 처리 안내.
// 나머지(앱 화면·공개 토큰 라우트)는 로그인/noindex 라 사이트맵에 넣지 않는다.
import type { MetadataRoute } from "next";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://www.inpa.kr";

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    { url: `${SITE_URL}/`, changeFrequency: "weekly", priority: 1 },
    { url: `${SITE_URL}/faq`, changeFrequency: "monthly", priority: 0.6 },
    { url: `${SITE_URL}/legal/terms`, changeFrequency: "monthly", priority: 0.3 },
    { url: `${SITE_URL}/legal/privacy`, changeFrequency: "monthly", priority: 0.3 },
    { url: `${SITE_URL}/data-policy`, changeFrequency: "monthly", priority: 0.3 },
  ];
}
