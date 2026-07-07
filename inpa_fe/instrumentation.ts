// 서버측 Sentry 배선 — Next 파일 컨벤션(루트 instrumentation.ts).
// register()가 런타임별 설정을 로드하고, onRequestError 가 서버 렌더 오류를 수집한다.
import * as Sentry from "@sentry/nextjs";

export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    await import("./sentry.server.config");
  }
  if (process.env.NEXT_RUNTIME === "edge") {
    await import("./sentry.edge.config");
  }
}

export const onRequestError = Sentry.captureRequestError;
