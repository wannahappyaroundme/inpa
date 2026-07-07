// 클라이언트(브라우저) Sentry 초기화 — Next 파일 컨벤션(루트 instrumentation-client.ts).
// 리플레이·트레이싱 없음, 오류만 수집 (lib/sentry-shared.ts 원칙 참조).
import * as Sentry from "@sentry/nextjs";

import { SENTRY_BASE_OPTIONS } from "@/lib/sentry-shared";

Sentry.init({ ...SENTRY_BASE_OPTIONS });

// 라우터 전환 계측 훅(SDK 표준 배선 — 트레이싱 0이라 실부하 없음)
export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
