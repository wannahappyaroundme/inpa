import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs";

const nextConfig: NextConfig = {
  /* config options here */
};

// Sentry 빌드 래핑 — 소스맵 업로드는 SENTRY_AUTH_TOKEN 이 있을 때만 SDK가 수행
// (토큰 미설정 = 업로드 생략, 빌드는 정상). 오류 수집 자체는 토큰과 무관.
export default withSentryConfig(nextConfig, {
  org: "fingo-dm",
  project: "inpa-fe",
  silent: true, // 빌드 로그 소음 방지
});
