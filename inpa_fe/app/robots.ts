// robots.txt 생성 (Next 파일 컨벤션, /robots.txt 로 서빙).
// 허용 = 중앙 정책에 등록된 공개 페이지.
// 차단 = 공개 토큰 라우트 + 어드민 + API.
// 각 토큰 페이지 layout 의 noindex 메타와 이중 방어.
//
// AI 검색 크롤러에도 같은 공개 허용 및 민감 경로 차단 규칙을 적용한다.
import type { MetadataRoute } from "next";
import { CURRENT_INDEXABLE_PATHS, ROBOTS_DISALLOW_PATHS } from "@/lib/search-policy";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://www.inpa.kr";

const ALLOW = CURRENT_INDEXABLE_PATHS.map((path) => path === "/" ? "/$" : path);
const DISALLOW = [...ROBOTS_DISALLOW_PATHS];

// AI 답변 엔진 및 검색 크롤러.
const AI_BOTS = [
  "GPTBot", "OAI-SearchBot", "ChatGPT-User",   // OpenAI (학습·검색·사용자조회)
  "ClaudeBot", "Claude-User", "Claude-SearchBot", "anthropic-ai",  // Anthropic(학습·사용자조회·검색인용)
  "PerplexityBot", "Perplexity-User",          // Perplexity
  "Google-Extended",                           // 구글 AI(Gemini/Vertex) 학습 제어 토큰
  "Applebot-Extended",                         // Apple 지능
];

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      { userAgent: "*", allow: ALLOW, disallow: DISALLOW },
      ...AI_BOTS.map((userAgent) => ({ userAgent, allow: ALLOW, disallow: DISALLOW })),
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
