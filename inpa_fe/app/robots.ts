// robots.txt 생성 (Next 파일 컨벤션 — /robots.txt 로 서빙).
// 허용 = 랜딩·legal·data-policy(공개 마케팅/법적 페이지).
// 차단 = 공개 토큰 라우트 5종(고객 개인정보가 오가는 링크) + 어드민 + API.
//   ⚠️ 토큰 라우트는 반드시 트레일링 슬래시(/s/ …)로 — '/s' 는 접두 매칭이라 /schedule, /settings 까지 막힌다.
// 각 토큰 페이지 layout 의 noindex 메타와 이중 방어.
import type { MetadataRoute } from "next";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://www.inpa.kr";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: ["/$", "/legal/", "/data-policy"],
      disallow: ["/s/", "/b/", "/c/", "/d/", "/p/", "/admin", "/api"],
    },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
