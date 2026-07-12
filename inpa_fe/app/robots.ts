// robots.txt 생성 (Next 파일 컨벤션 — /robots.txt 로 서빙).
// 허용 = 랜딩·legal·data-policy·faq(공개 마케팅/법적 페이지).
// 차단 = 공개 토큰 라우트 5종(고객 개인정보가 오가는 링크) + 어드민 + API.
//   ⚠️ 토큰 라우트는 반드시 트레일링 슬래시(/s/ …)로 — '/s' 는 접두 매칭이라 /schedule, /settings 까지 막힌다.
// 각 토큰 페이지 layout 의 noindex 메타와 이중 방어.
//
// ★ AI 답변 엔진 크롤러(GPTBot·ClaudeBot·PerplexityBot·Google-Extended 등)를 이름으로 명시 허용한다.
//   공개 페이지엔 민감정보가 없고, "AI 답변에 인파가 나오게"가 목표라 인용·학습 봇을 환영한다.
//   봇 종류와 무관하게 토큰·어드민·API 는 동일 차단(공통 ALLOW/DISALLOW 재사용).
import type { MetadataRoute } from "next";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://www.inpa.kr";

const ALLOW = ["/$", "/legal/", "/data-policy", "/faq", "/blog"];
const DISALLOW = ["/s/", "/b/", "/c/", "/d/", "/p/", "/admin", "/api"];

// AI 답변 엔진/검색 크롤러 (공개 페이지 인용·학습 허용).
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
