// Sentry 공통 설정 — FE 3개 런타임(client/server/edge) 공유 (H-2/LB#11, 2026-07-07).
//
// ★ 개인정보 레드라인(감사 H-6, BE prod.py send_default_pii=False 와 동일 원칙):
//   - sendDefaultPii=false: 요청 헤더·IP·쿠키를 이벤트에 싣지 않는다.
//   - 세션 리플레이(화면 녹화) 미사용: 고객 증권·보장 화면이 담길 수 있어 금지.
//   - tracesSampleRate=0: 오류 수집만(성능 트레이싱은 무료 쿼터·PII 표면 관리상 보류).
// DSN 은 비밀이 아님(공개 클라이언트 키) — 기본값 하드코드 + env 로 교체 가능.
export const SENTRY_DSN =
  process.env.NEXT_PUBLIC_SENTRY_DSN ||
  "https://275953dddf39f784ebaa4d1f5a88a47b@o4511229073227776.ingest.us.sentry.io/4511691391303680";

export const SENTRY_BASE_OPTIONS = {
  dsn: SENTRY_DSN,
  enabled: process.env.NODE_ENV === "production", // 로컬 개발 소음 방지
  sendDefaultPii: false,
  tracesSampleRate: 0,
} as const;
