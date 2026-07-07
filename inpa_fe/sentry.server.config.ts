// Node 서버 런타임 Sentry 초기화 (instrumentation.ts 가 로드).
import * as Sentry from "@sentry/nextjs";

import { SENTRY_BASE_OPTIONS } from "@/lib/sentry-shared";

Sentry.init({ ...SENTRY_BASE_OPTIONS });
