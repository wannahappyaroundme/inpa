// inpa_fe/lib/api.ts
// BE API fetch wrapper — base: /api/v1/auth/
// Token: localStorage('inpa_token')
// Error shape: { code?: string; detail?: string; error?: string; message?: string }

const API_BASE =
  (process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000/api/v1").replace(/\/$/, "");

// 운영(브라우저가 localhost가 아닌데 API가 localhost로 폴백) = NEXT_PUBLIC_API_BASE 미설정.
// 빌드타임 인라인이라 배포 전 Vercel 환경변수 설정 + 재배포 필요. 조용한 전면장애를 콘솔로 경고.
if (typeof window !== "undefined" &&
    API_BASE.includes("localhost") &&
    !window.location.hostname.match(/^(localhost|127\.0\.0\.1)$/)) {
  console.error(
    "[인파] NEXT_PUBLIC_API_BASE 미설정: API가 localhost를 가리킵니다. " +
    "Vercel 환경변수에 백엔드 URL을 넣고 재배포하세요."
  );
}

// ─── Error class ────────────────────────────────────────────────────────────

/** 402 한도초과 응답 추가 필드 (BE: credit_exhausted shape) */
export interface CreditExhaustedBody {
  kind?: string;
  membership?: string;
  limit?: number | null;
  used?: number;
}

export class ApiError extends Error {
  code: string;
  status: number;
  /** 402 credit_exhausted 일 때 BE가 반환하는 추가 필드. 그 외는 undefined. */
  creditBody?: CreditExhaustedBody;
  /** 412 CONSENT_OVERSEAS_REQUIRED 일 때 BE가 주는 사유: "missing"(동의 없음) | "reconsent"(구버전 동의). */
  reason?: string;
  /** 충돌 처리처럼 서버가 제공하는 안전한 추가 선택지. */
  data?: Record<string, unknown>;
  constructor(
    status: number,
    code: string,
    message: string,
    creditBody?: CreditExhaustedBody,
    reason?: string,
    data?: Record<string, unknown>
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.creditBody = creditBody;
    this.reason = reason;
    this.data = data;
  }
}

// ─── Token helpers ──────────────────────────────────────────────────────────

export const tokenStore = {
  get(): string | null {
    if (typeof window === "undefined") return null;
    return localStorage.getItem("inpa_token");
  },
  set(token: string): void {
    if (typeof window === "undefined") return;
    localStorage.setItem("inpa_token", token);
  },
  remove(): void {
    if (typeof window === "undefined") return;
    localStorage.removeItem("inpa_token");
  },
};

// ─── Internal fetch ─────────────────────────────────────────────────────────

/**
 * 401 공통 처리 — 저장된 토큰이 무효/만료된 상태(서버가 인증 거부).
 * 죽은 토큰을 비우고 로그인 화면으로 보낸다(이미 로그인 화면이면 재이동 안 함 → 루프 방지).
 * request()와 멀티파트/DELETE 등 수제 fetch 헬퍼가 전부 이 한 곳을 태운다(우회 금지).
 * 인증 요청에서만 호출할 것 — 로그인/회원가입 등 비인증 요청의 401은 그대로 에러로 전달.
 */
function handleUnauthorized(status: number): void {
  if (status !== 401) return;
  tokenStore.remove();
  if (typeof window !== "undefined" && window.location.pathname !== "/login") {
    window.location.href = "/login?session=expired";
  }
}

/** 오류 본문 → 사용자 메시지. detail/message 우선, 없으면 DRF 필드 검증 오류
 *  ({field: ["메시지", ...]})의 첫 메시지를 그대로 노출한다.
 *  (2026-07-07: 가입 400이 '오류가 발생했습니다'로만 보이던 문제 — 실제 사유
 *   예: '이미 가입된 이메일입니다'가 사용자에게 전달되지 않았음) */
function extractErrorDetail(data: Record<string, unknown>, statusText: string): string {
  const direct = (data["detail"] as string) ?? (data["message"] as string);
  if (direct) return direct;
  for (const v of Object.values(data)) {
    if (Array.isArray(v) && typeof v[0] === "string") return v[0];
  }
  return statusText;
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  auth = false,
  extraHeaders: Record<string, string> = {}
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...extraHeaders,
  };
  if (auth) {
    const tok = tokenStore.get();
    if (tok) headers["Authorization"] = `Token ${tok}`;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  let data: Record<string, unknown> = {};
  try {
    data = await res.json();
  } catch {
    // empty body
  }

  if (!res.ok) {
    // BE returns { error: "CODE" } or { detail: "msg" } or { code: "CODE" }
    const code =
      (data["error"] as string) ??
      (data["code"] as string) ??
      String(res.status);
    const detail = extractErrorDetail(data, res.statusText);
    // 402 credit_exhausted: 추가 필드(kind/limit/used) 추출해 ApiError에 첨부
    const creditBody: CreditExhaustedBody | undefined =
      res.status === 402 && code === "credit_exhausted"
        ? {
            kind: data["kind"] as string | undefined,
            membership: data["membership"] as string | undefined,
            limit: data["limit"] as number | null | undefined,
            used: data["used"] as number | undefined,
          }
        : undefined;
    // 401(인증 요청만): 공통 처리 — 토큰 제거 + 로그인 화면 이동.
    if (auth) handleUnauthorized(res.status);
    throw new ApiError(res.status, code, detail, creditBody, undefined, data);
  }

  return data as T;
}

// ─── Auth endpoints ─────────────────────────────────────────────────────────

export interface RegisterPayload {
  email: string;
  password: string;
  password_confirm: string;
  tos_agreed: boolean;
  pp_agreed: boolean;
  marketing_agreed: boolean;
  affiliation?: string;   // 소속(선택)
  title?: string;         // 직책(선택)
  license_no?: string;    // 설계사 번호(선택, 숫자 14자리)
  invite_token?: string;  // 팀 초대 토큰(선택) — 무효여도 가입은 성공(BE가 토큰만 무시)
  // UTM/유입 캡처(#16, 선택) — sessionStorage 첫터치 또는 현재 URL 쿼리에서 옴. PII 아님.
  utm_source?: string;
  utm_medium?: string;
  utm_campaign?: string;
}

export interface RegisterResponse {
  message: string;
}

/** POST /api/v1/auth/register/ */
export async function register(payload: RegisterPayload): Promise<RegisterResponse> {
  return request<RegisterResponse>("POST", "/auth/register/", payload);
}

// ─────────────────────────────────────────────────────────────────────────────

export interface VerifyEmailResponse {
  message: string;
}

/**
 * 이메일 인증 — BE 토큰은 self-contained(signing.dumps(pk))라 token 1개로 충분.
 * reset-password와 달리 uid 불필요. (이전 버그: FE가 없는 uid를 요구해 인증 전면 차단)
 * POST /api/v1/auth/verify-email/  body: { token }
 */
export async function verifyEmail(token: string): Promise<VerifyEmailResponse> {
  return request<VerifyEmailResponse>("POST", "/auth/verify-email/", { token });
}

/** 인증 메일 재발송 — 미인증 계정이면 재발송(계정 존재 노출 방지로 항상 200). */
export async function resendVerification(email: string): Promise<{ message: string }> {
  return request<{ message: string }>("POST", "/auth/resend-verification/", { email });
}

/** 비밀번호 변경(로그인 상태) — 성공 시 새 토큰이 발급되므로 tokenStore 갱신(세션 유지). */
export async function changePassword(oldPassword: string, newPassword: string): Promise<{ message: string }> {
  const r = await request<{ message: string; token: string }>(
    "POST", "/auth/password/change/", { old_password: oldPassword, new_password: newPassword }, true);
  if (r.token) tokenStore.set(r.token);
  return { message: r.message };
}

/** 회원 탈퇴 — 이메일가입=password / 구글가입=confirm(가입 이메일). 성공 시 토큰 폐기. */
export async function withdrawAccount(payload: { password?: string; confirm?: string }): Promise<{ message: string }> {
  const r = await request<{ message: string }>("POST", "/auth/withdraw/", payload, true);
  tokenStore.remove();
  return r;
}

// ─────────────────────────────────────────────────────────────────────────────

export interface LoginPayload {
  email: string;
  password: string;
}

/**
 * BE 실제 응답: { token, email, onboarding_completed }.
 * (accounts/views.py LoginView 기준 — profile/membership 없음.)
 */
export interface LoginResponse {
  token: string;
  email: string;
  onboarding_completed: boolean;
}

/** POST /api/v1/auth/login/ */
export async function login(payload: LoginPayload): Promise<LoginResponse> {
  return request<LoginResponse>("POST", "/auth/login/", payload);
}

/** POST /api/v1/auth/google/ — 구글 소셜 로그인(병행). 응답은 login과 동일 */
export async function googleLogin(id_token: string): Promise<LoginResponse> {
  return request<LoginResponse>("POST", "/auth/google/", { id_token });
}

/** GET /api/v1/auth/google/calendar/connect/ — 연동 동의 URL(인증) */
export async function getGoogleCalendarConnectUrl(): Promise<{ auth_url: string }> {
  return request<{ auth_url: string }>("GET", "/auth/google/calendar/connect/", undefined, true);
}

/** POST /api/v1/auth/google/calendar/disconnect/ — 연동 해제(인증) */
export async function disconnectGoogleCalendar(): Promise<{ disconnected: boolean }> {
  return request<{ disconnected: boolean }>("POST", "/auth/google/calendar/disconnect/", undefined, true);
}

// ─────────────────────────────────────────────────────────────────────────────

export interface LogoutResponse {
  message: string;
}

/** POST /api/v1/auth/logout/ — requires token */
export async function logout(): Promise<LogoutResponse> {
  const res = await request<LogoutResponse>("POST", "/auth/logout/", undefined, true);
  tokenStore.remove();
  return res;
}

// ─────────────────────────────────────────────────────────────────────────────

export interface PasswordResetPayload {
  email: string;
}

export interface PasswordResetResponse {
  message: string;
}

/** POST /api/v1/auth/password-reset/ */
export async function requestPasswordReset(
  payload: PasswordResetPayload
): Promise<PasswordResetResponse> {
  return request<PasswordResetResponse>("POST", "/auth/password-reset/", payload);
}

// ─────────────────────────────────────────────────────────────────────────────

export interface PasswordResetConfirmPayload {
  uid: string;
  token: string;
  new_password: string;
  new_password_confirm: string;
}

export interface PasswordResetConfirmResponse {
  message: string;
}

/** POST /api/v1/auth/password-reset/confirm/ */
export async function confirmPasswordReset(
  payload: PasswordResetConfirmPayload
): Promise<PasswordResetConfirmResponse> {
  return request<PasswordResetConfirmResponse>(
    "POST",
    "/auth/password-reset/confirm/",
    payload
  );
}

// ─────────────────────────────────────────────────────────────────────────────

/**
 * GET /api/v1/auth/profile/ 응답 (accounts ProfileSerializer 기준).
 * is_admin → 관리자 진입점 노출 게이트. onboarding_completed_at → 온보딩 가드.
 */
export interface ProfileResponse {
  email: string;
  name: string;
  phone: string;                // 설계사 전화번호(/s 전화·문자 버튼 + 판촉물 인쇄 정보 프리필)
  affiliation: string | null;
  agent_type: number | null;
  /** 1=전속(원수사) 2=GA. null=미신고 */
  affiliation_type: number | null;
  cohort_opt_in: boolean;
  manager_share_opt_in: boolean;
  manager_share_level: "none" | "activity" | "full";  // 관리자 공유 단계
  manager_email: string | null;
  is_manager: boolean;
  manager_promoted_at: string | null;
  manager_promotion_seen_at: string | null;
  managed_agents_count: number;
  recruiting_enabled: boolean;
  license_self_declared: boolean;
  license_no: string | null;
  career_years: number | null;
  booking_msg_template: string;
  booking_location: string;
  booking_default_duration: number;
  booking_buffer_min: number;   // 미팅 앞뒤 여유(분)
  title: string;                // 직책({소속직책} 머지필드용)
  intro_text: string;           // 한줄소개(공개 소개 카드 /p)
  profile_image: string | null; // 프로필 사진 URL(없으면 null → 이니셜 아바타)
  google_calendar_connected: boolean;
  google_calendar_mask_name: boolean;
  has_usable_password: boolean;   // false=구글 전용 가입(비번 없음) → 비번변경 숨김·탈퇴는 이메일 확인
  onboarding_completed_at: string | null;
  marketing_agreed_at: string | null;
  ref_code: string | null;
  email_verified_at: string | null;
  is_admin: boolean;
  is_dormant: boolean;
}

/** GET /api/v1/auth/profile/ — requires token */
export async function getProfile(): Promise<ProfileResponse> {
  return request<ProfileResponse>("GET", "/auth/profile/", undefined, true);
}

/** PATCH /api/v1/auth/profile/ — 모드·동의·매니저 연결 변경 */
export interface ProfileUpdatePayload {
  name?: string;
  phone?: string;
  affiliation?: string;
  affiliation_type?: number | null;
  cohort_opt_in?: boolean;
  manager_share_opt_in?: boolean;
  manager_share_level?: "none" | "activity" | "full";
  manager_email?: string;
  confirm_manager_switch?: boolean;
  booking_msg_template?: string;
  booking_location?: string;
  booking_default_duration?: number;
  booking_buffer_min?: number;
  title?: string;
  intro_text?: string;
  google_calendar_mask_name?: boolean;
}
export async function updateProfile(payload: ProfileUpdatePayload): Promise<ProfileResponse> {
  return request<ProfileResponse>("PATCH", "/auth/profile/", payload, true);
}

/** POST /api/v1/auth/manager-promotion/ack/ — 첫 관리자 승격 안내 확인 */
export async function acknowledgeManagerPromotion(): Promise<{
  manager_promotion_seen_at: string | null;
}> {
  return request<{ manager_promotion_seen_at: string | null }>(
    "POST",
    "/auth/manager-promotion/ack/",
    undefined,
    true,
  );
}

/** PATCH /api/v1/auth/profile/ — 프로필 사진 멀티파트 업로드. 저장은 명함과 동일 저장소(프로드=R2). */
export async function uploadProfileImage(file: File): Promise<ProfileResponse> {
  const form = new FormData();
  form.append("profile_image", file);
  const headers: Record<string, string> = {};
  const tok = tokenStore.get();
  if (tok) headers["Authorization"] = `Token ${tok}`;
  const res = await fetch(`${API_BASE}/auth/profile/`, { method: "PATCH", headers, body: form });
  let data: Record<string, unknown> = {};
  try { data = await res.json(); } catch { /* empty */ }
  if (!res.ok) {
    const code = (data["error"] as string) ?? (data["code"] as string) ?? String(res.status);
    const detail = extractErrorDetail(data, res.statusText);
    handleUnauthorized(res.status);
    throw new ApiError(res.status, code, detail);
  }
  return data as unknown as ProfileResponse;
}

// ─── Onboarding ───────────────────────────────────────────────────────────────

export interface OnboardingAttestPayload {
  affiliation?: string;
  agent_type?: number | null;
  affiliation_type?: number | null;
  manager_email?: string;
  confirm_manager_switch?: boolean;
  license_self_declared?: boolean;
  career_years?: number | null;
}

/** POST /api/v1/auth/onboarding/attest/ — 온보딩 완료 기록. ProfileResponse 반환 */
export async function attestOnboarding(
  payload: OnboardingAttestPayload = {}
): Promise<ProfileResponse> {
  return request<ProfileResponse>("POST", "/auth/onboarding/attest/", payload, true);
}

// ─── 지점장 대시보드 (동의한 소속 설계사 KPI 집계만) ───────────────────────────
export interface ManagerAgentKpi {
  name_masked: string;
  customer_count: number;
  churn_risk_count: number;
  share_view_count: number;
  retention_y1: number | null;           // 실적: 미공유(activity)면 null
  premium_month: number | null;          // 실적: 미공유면 null('비공개')
  new_month: number;
  meetings_month: number;
  premium_delta: number | null;          // 전월 대비 % (미공유면 null)
  funnel: Record<SalesStage, number>;    // 단계 분포(미니바)
  product_mix: { life: number; nonlife: number };
  last_login: string | null;
  is_active_month: boolean;              // 이번 달 활동 0 → 회색 강조
  shares_performance: boolean;           // false면 실적(보험료·유지율) '비공개'
}
export interface ManagerTeamRoi {
  agent_count: number;
  hours_saved_per_agent: number;
  team_hours_saved: number;
  extra_consults: number;
  note: string;
}
export interface ManagerDashboardResponse {
  agent_count: number;
  agents: ManagerAgentKpi[];
  totals: {
    customer_count: number; churn_risk_count: number; share_view_count: number;
    premium_month: number; new_month: number; active_member_count: number;
    perf_agent_count: number;   // 실적까지 공유한 팀원 수(팀 보험료 합계 기준)
  };
  team_funnel: Record<SalesStage, number>;
  team_retention: RetentionYears;
  team_product_mix: { life: number; nonlife: number };
  team_premium_trend: { ym: string; premium: number }[];
  roi: ManagerTeamRoi;
}
export async function getManagerDashboard(): Promise<ManagerDashboardResponse> {
  return request<ManagerDashboardResponse>("GET", "/manager/dashboard/", undefined, true);
}

// ─── 팀 초대 링크(#24) — 가입 시 manager 연결만, 성과 공유는 본인이 설정에서 선택 ───
export interface TeamInviteLinkResponse {
  url: string; // FRONTEND_BASE_URL/register?invite=<token>
  ttl_days: number; // 링크 유효일수(서버 TEAM_INVITE_TTL_DAYS)
}
/** POST /api/v1/manager/invite-link/ — 내 팀 초대 링크 생성(인증) */
export async function createTeamInviteLink(): Promise<TeamInviteLinkResponse> {
  return request<TeamInviteLinkResponse>("POST", "/manager/invite-link/", {}, true);
}

export interface InviteInfo {
  manager_name: string;
  affiliation: string | null;
}
/** GET /api/v1/manager/invite-info/?token= — 초대 칩용(무효/만료면 404 → 칩 없이 일반 가입) */
export async function getInviteInfo(token: string): Promise<InviteInfo> {
  return request<InviteInfo>("GET", `/manager/invite-info/?token=${encodeURIComponent(token)}`);
}

// ─── 환수 위험 → 인앱 알림 동기화 (cron 아님, 홈 진입 시 호출) ───────────────────
export async function syncChurnAlerts(): Promise<{ created: number }> {
  return request<{ created: number }>("POST", "/churn-radar/sync-alerts/", {}, true);
}

// ─── 셀프진단 인바운드 (공개, 비로그인) ─────────────────────────────────────────
/** 업로드한 증권 1장 = 카드 1장. failed/skipped 는 message(다음 행동 안내)만 담긴다. */
export interface SelfDiagnosisInsurance {
  name: string;                    // 상품명(파싱) 또는 파일명 폴백
  company_label: string | null;    // 보험사명(미감지면 null)
  monthly_premium: number | null;
  total_premium: number | null;
  coverage_count: number;          // 읽어들인 담보 수
  tree: ShareCategory[];           // 이 보험만의 보유 담보 트리(neutral, held>0만)
  status: "ok" | "failed" | "skipped";
  message?: string;                // failed/skipped 안내 문구(BE 고정 카피)
}
export interface SelfDiagnosisResult {
  customer: { name_masked: string; gender: number | null; birth_year: number | null };
  mode: string;
  summary: { monthly_premiums: number | null; total_premiums: number | null };
  tree: ShareCategory[];
  disclaimer: string;
  lead_created?: boolean;
  analyzed?: boolean;   // PDF 분석 수행 여부. false = 증권 미첨부(리드만 접수, 결과 없음)
  booking_url?: string; // 예약 가능할 때만(설계사 영업시간 존재) — '바로 상담 예약' CTA
  insurances?: SelfDiagnosisInsurance[]; // 업로드한 증권별 카드(업로드 순서 보존)
  notice?: string;      // 5장 초과 업로드 시 안내 문구
}
/** POST /api/v1/d/<refcode>/ — multipart: name·phone·birth·gender 필수, consent_*·files(최대 5장) 선택 */
export async function postSelfDiagnosis(refcode: string, form: FormData): Promise<SelfDiagnosisResult> {
  const res = await fetch(`${API_BASE}/d/${encodeURIComponent(refcode)}/`, {
    method: "POST",
    body: form,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new ApiError(res.status, (data as { code?: string }).code ?? "ERROR",
      (data as { detail?: string }).detail ?? "진단에 실패했어요.");
  }
  return data as SelfDiagnosisResult;
}

// ─── 소개 카드(공개, 비로그인) — /p/<refcode> ────────────────────────────────
export interface IntroCardResponse {
  planner: { name: string; affiliation: string; title: string; intro_text: string };
  self_diagnosis_url: string;  // '/d/<ref>'
}
/** GET /api/v1/p/<refcode>/ — 설계사 소개 카드 데이터 */
export async function getIntroductionCard(refcode: string): Promise<IntroCardResponse> {
  const res = await fetch(`${API_BASE}/p/${encodeURIComponent(refcode)}/`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new ApiError(res.status, (data as { code?: string }).code ?? "ERROR",
      (data as { detail?: string }).detail ?? "불러오지 못했어요.");
  }
  return data as IntroCardResponse;
}
/** POST /api/v1/p/<refcode>/ — 상담 신청(설계사 db 리드 자동 생성) */
export async function submitIntroLead(refcode: string, payload: { name: string; phone?: string; agreed: boolean }): Promise<{ lead_created: boolean }> {
  const res = await fetch(`${API_BASE}/p/${encodeURIComponent(refcode)}/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new ApiError(res.status, (data as { code?: string }).code ?? "ERROR",
      (data as { detail?: string }).detail ?? "신청에 실패했어요.");
  }
  return data as { lead_created: boolean };
}

// ─── Customer types ──────────────────────────────────────────────────────────

export interface CustomerTag {
  id: number;
  label: string;
  color: string;
  created_at: string;
}

/** 목록 카드용 경량 타입 (CustomerListSerializer 대응) */
/** 영업 4단계(파이프라인) — BE Customer.SALES_STAGE_CHOICES 대응. 칸반/퍼널 공용. */
export type SalesStage = "db" | "contact" | "meeting" | "contract";

/** 단계 메타(순서·라벨·? 툴팁 설명) — 칸반 컬럼/퍼널 셀이 이 순서·라벨을 그대로 쓴다. */
export const SALES_STAGES: { key: SalesStage; label: string; short: string; desc: string }[] = [
  { key: "db", label: "DB", short: "01", desc: "아직 상담 전인 예비 고객 명단이에요. 이름·연락처만 확보된 단계." },
  { key: "contact", label: "TA", short: "02", desc: "전화·문자로 처음 연락해 만날 약속을 잡는 단계예요. (TA = Telephone Approach)" },
  { key: "meeting", label: "FA", short: "03", desc: "직접 만나 보장을 분석·상담하는 대면 단계예요. (FA = Face-to-face Approach)" },
  { key: "contract", label: "청약", short: "04", desc: "고객이 보험계약을 신청(청약서 작성)하는 계약 체결 단계." },
];

/** 단계 전환율(스냅샷) — 현재 분포 기준 '지금까지 각 단계를 넘어간 비율'. db→contact→meeting→contract 3개 구간.
 *  누적 도달(해당 단계 이상에 있는 고객 수)로 계산. 단계 기본값이 db라 모두 db에서 출발한다는 가정. */
export function funnelConversion(
  funnel: Record<SalesStage, number>
): { from: SalesStage; to: SalesStage; rate: number | null }[] {
  const order: SalesStage[] = ["db", "contact", "meeting", "contract"];
  const reached = (i: number) => order.slice(i).reduce((s, k) => s + (funnel[k] ?? 0), 0);
  return [0, 1, 2].map((i) => {
    const denom = reached(i);
    const numer = reached(i + 1);
    return { from: order[i], to: order[i + 1], rate: denom > 0 ? Math.round((numer / denom) * 100) : null };
  });
}

/** 고객 상태(설계사 집중 관리) — BE Customer.STATUS_CHOICES 대응. 영업 단계와 별개의 '진행 상태'.
 *  진행중만 방치(무접촉) 경보 대상, 보류·휴면·종료는 흐리게 처리해 집중 고객과 구분한다. */
export type CustomerStatus = "active" | "hold" | "dormant" | "closed";
export const CUSTOMER_STATUSES: { key: CustomerStatus; label: string }[] = [
  { key: "active", label: "진행중" },
  { key: "hold", label: "보류" },
  { key: "dormant", label: "휴면" },
  { key: "closed", label: "종료" },
];

/** 마케팅(개인정보 수집·이용) 동의 상태 — 'none'(기록 없음)도 비동의로 취급해 영업 자동화에서 제외. */
export type MarketingConsent = "agreed" | "revoked" | "none";
export type ConsentStatus = MarketingConsent;
export type ConsentSubject = "customer_self" | "planner_attested" | null;
export interface ConsentState {
  status: ConsentStatus;
  subject: ConsentSubject;
  agreed_at: string | null;
}

/** 유입 경로(측정) — 수기등록 select / self_diagnosis는 자동 */
export const LEAD_SOURCES: { value: string; label: string }[] = [
  { value: "introduction", label: "소개" },
  { value: "business_card", label: "명함" },
  { value: "event", label: "행사" },
  { value: "direct", label: "직접 등록" },
];

export interface CustomerListItem {
  id: number;
  name: string;
  gender: string | null;
  birth_day: string | null;          // "YYYY-MM-DD"
  mobile_phone_number: string | null;
  consent_overseas_at: string | null;
  color: string | null;
  avatar_label: string;              // 아바타 글씨(약자·숫자, 빈값=색만/로고)
  tags: CustomerTag[];
  family_count: number;
  sales_stage: SalesStage;
  status: CustomerStatus;            // 진행 상태(진행중/보류/휴면/종료)
  share_token: string | null;
  created_at: string;
  lead_source: string | null;        // 유입 경로(측정)
  // ── 고객 관리(PM 06.24) ──
  last_contacted_at: string | null;  // 방치 색상경보·정렬 기준
  is_favorite: boolean;
  is_pinned: boolean;
  insurance_age: number | null;      // 보험나이(상령일)
  job_risk_grade: number | null;     // 직업 위험등급 1|2|3|9
  marketing_consent: MarketingConsent;
  personal_info_consent: ConsentStatus;
}

/** 상세 타입 (CustomerSerializer 대응) */
export interface CustomerDetail extends CustomerListItem {
  job_code: string | null;
  job_name: string | null;
  memo: string | null;
  is_agree_term: boolean;
  share_expires_at: string | null;
  share_sent_at: string | null;
  user_view_at: string | null;
  business_card: string | null;      // 명함 이미지 URL
  updated_at: string;
  family_members: unknown[];
  medical_histories: unknown[];
  // 동의 상태(본인/대리 구분) — 상세에서만.
  consents?: { marketing: ConsentState; personal_info: ConsentState };
}

/** DRF 페이지네이션 래퍼 */
export interface PaginatedResult<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

/** 고객 등록/수정 payload */
export interface CustomerWritePayload {
  name: string;
  gender?: string;
  birth_day?: string;
  mobile_phone_number?: string;
  job_code?: string;
  memo?: string;
  color?: string;
  avatar_label?: string;
  lead_source?: string;
  is_agree_term?: boolean;
  tag_ids?: number[];
  sales_stage?: SalesStage;     // 칸반 단계이동 = updateCustomer({sales_stage})
  status?: CustomerStatus;      // 고객 상태 변경(진행중/보류/휴면/종료)
  is_favorite?: boolean;
  is_pinned?: boolean;
  last_contacted_at?: string | null;  // '연락함' = updateCustomer({last_contacted_at: now})
}

// ─── 직업급수(JobRiskCode) 검색 ──────────────────────────────────────────────

/** 직업급수 검색 결과 1건 (전역 마스터). job_code = id 로 고객에 적용. */
export interface JobMatch {
  id: number;
  name: string;
  alt_name: string;
  risk_grade: number;        // 1/2/3/9
  risk_grade_label: string;  // '1급'…'기타'
  kidi_cd: string;
  sctg_cd: string;
  description_short: string;
}

/** GET /api/v1/jobs/search/?q=시의원 — 이름·약명·검색어 매칭, 관련도순 최대 limit(≤50). */
export async function searchJobs(q: string, limit = 30): Promise<JobMatch[]> {
  const query = q.trim();
  if (!query) return [];
  const qs = new URLSearchParams({ q: query, limit: String(limit) });
  const data = await request<{ results: JobMatch[] }>(
    "GET", `/jobs/search/?${qs.toString()}`, undefined, true
  );
  return data.results;
}

// ─── Customer endpoints ──────────────────────────────────────────────────────

/** GET /api/v1/customers/?page=1&search=... */
export async function listCustomers(
  params: { page?: number; search?: string } = {}
): Promise<PaginatedResult<CustomerListItem>> {
  const qs = new URLSearchParams();
  if (params.page) qs.set("page", String(params.page));
  if (params.search) qs.set("search", params.search);
  const query = qs.toString() ? `?${qs.toString()}` : "";
  return request<PaginatedResult<CustomerListItem>>("GET", `/customers/${query}`, undefined, true);
}

/**
 * 모든 고객을 페이지를 따라가며 전부 로드(선택 드롭다운용).
 * page=1만 부르면 21명째부터 못 고르므로, next가 없을 때까지 이어붙인다.
 * 안전 상한(무한루프 방지): 최대 100페이지.
 */
export async function listAllCustomers(): Promise<CustomerListItem[]> {
  const all: CustomerListItem[] = [];
  let page = 1;
  for (let i = 0; i < 100; i++) {
    const res = await listCustomers({ page });
    all.push(...res.results);
    if (!res.next) break;
    page += 1;
  }
  return all;
}

/** GET /api/v1/customers/{id}/ */
export async function getCustomer(id: number): Promise<CustomerDetail> {
  return request<CustomerDetail>("GET", `/customers/${id}/`, undefined, true);
}

// ─── Customer consultation memos ──────────────────────────────────────────

export type CustomerMemoSource = "manual" | "ai_summary" | "legacy_migrated";

export interface CustomerMemo {
  id: number;
  source: CustomerMemoSource;
  source_label: string;
  body: string;
  occurred_at: string | null;
  created_at: string;
  updated_at: string;
  edited_at: string | null;
  revision: number;
}

/** 고객별 상담 메모 목록. 서버의 정렬·페이지 순서를 그대로 사용한다. */
export function listCustomerMemos(
  customerId: number,
  page = 1,
): Promise<PaginatedResult<CustomerMemo>> {
  return request<PaginatedResult<CustomerMemo>>(
    "GET",
    `/customers/${customerId}/memos/?page=${page}`,
    undefined,
    true,
  );
}

/** 새 상담 메모는 서버가 작성 시각과 출처를 정한다. */
export function createCustomerMemo(
  customerId: number,
  body: string,
): Promise<CustomerMemo> {
  return request<CustomerMemo>("POST", `/customers/${customerId}/memos/`, { body }, true);
}

/** 수정에는 서버가 준 revision을 함께 보내 최신 메모 보호를 받는다. */
export function updateCustomerMemo(
  customerId: number,
  memo: CustomerMemo,
  body: string,
): Promise<CustomerMemo> {
  return request<CustomerMemo>(
    "PATCH",
    `/customers/${customerId}/memos/${memo.id}/`,
    { body, revision: memo.revision },
    true,
  );
}

export function deleteCustomerMemo(customerId: number, memoId: number): Promise<void> {
  return requestVoid("DELETE", `/customers/${customerId}/memos/${memoId}/`, true);
}

/** POST /api/v1/customers/ */
export async function createCustomer(payload: CustomerWritePayload): Promise<CustomerDetail> {
  return request<CustomerDetail>("POST", "/customers/", payload, true);
}

/** POST /api/v1/customers/bulk/ — 여러 고객 일괄 등록(이름 필수, 이름+연락처 중복은 건너뜀).
 *  단건 등록과 동일 필드 세트를 행별로 받음(전부 선택, name만 필수). */
export interface BulkCustomerRow {
  name: string;
  mobile_phone_number?: string;
  gender?: string;          // "1"(남) | "2"(여)
  birth_day?: string;       // "YYYY-MM-DD"
  job_code?: string;        // JobRiskCode id
  memo?: string;
  lead_source?: string;     // introduction | business_card | event | direct
  avatar_label?: string;    // 약자·숫자(최대 3)
  color?: string;           // 팔레트 hex 또는 ''
  sales_stage?: SalesStage;
}
export async function createCustomersBulk(rows: BulkCustomerRow[]): Promise<{ created: number; skipped: number }> {
  return request<{ created: number; skipped: number }>("POST", "/customers/bulk/", { customers: rows }, true);
}

/** PATCH /api/v1/customers/{id}/ */
export async function updateCustomer(
  id: number,
  payload: Partial<CustomerWritePayload>
): Promise<CustomerDetail> {
  return request<CustomerDetail>("PATCH", `/customers/${id}/`, payload, true);
}

/** PATCH /api/v1/customers/{id}/ — 명함 이미지 멀티파트 업로드(C8). Content-Type은 브라우저가 boundary 설정. */
export async function uploadBusinessCard(id: number, file: File): Promise<CustomerDetail> {
  const form = new FormData();
  form.append("business_card", file);
  const headers: Record<string, string> = {};
  const tok = tokenStore.get();
  if (tok) headers["Authorization"] = `Token ${tok}`;
  const res = await fetch(`${API_BASE}/customers/${id}/`, { method: "PATCH", headers, body: form });
  let data: Record<string, unknown> = {};
  try { data = await res.json(); } catch { /* empty */ }
  if (!res.ok) {
    const code = (data["error"] as string) ?? (data["code"] as string) ?? String(res.status);
    const detail = extractErrorDetail(data, res.statusText);
    handleUnauthorized(res.status);
    throw new ApiError(res.status, code, detail);
  }
  return data as unknown as CustomerDetail;
}

// ── 계약 설명의무 체크리스트 (PM 06.24) ──
export interface ContractChecklistItem {
  id: number;
  label: string;
  is_done: boolean;
  done_at: string | null;
  order: number;
  created_at: string;
  updated_at: string;
}

/** GET /api/v1/customers/<id>/checklist/ */
export async function listChecklist(customerId: number): Promise<PaginatedResult<ContractChecklistItem>> {
  return request<PaginatedResult<ContractChecklistItem>>("GET", `/customers/${customerId}/checklist/`, undefined, true);
}
/** POST .../checklist/apply-template/ — 기본 설명의무 항목 일괄 생성(멱등) */
export async function applyChecklistTemplate(customerId: number): Promise<{ created: number; detail?: string }> {
  return request("POST", `/customers/${customerId}/checklist/apply-template/`, {}, true);
}
/** POST .../checklist/<itemId>/toggle/ */
export async function toggleChecklistItem(customerId: number, itemId: number): Promise<ContractChecklistItem> {
  return request<ContractChecklistItem>("POST", `/customers/${customerId}/checklist/${itemId}/toggle/`, {}, true);
}
/** POST .../checklist/ — 사용자 정의 항목 추가 */
export async function addChecklistItem(customerId: number, label: string): Promise<ContractChecklistItem> {
  return request<ContractChecklistItem>("POST", `/customers/${customerId}/checklist/`, { label }, true);
}
/** DELETE .../checklist/<itemId>/ */
export async function deleteChecklistItem(customerId: number, itemId: number): Promise<void> {
  await requestVoid("DELETE", `/customers/${customerId}/checklist/${itemId}/`, true);
}

// ─── 접촉 결과 로그 (TA 콜 활동 기록, append-only) ──────────────────────────
export type ContactResult = "no_answer" | "connected" | "appointment" | "rejected" | "hold";
export const CONTACT_RESULTS: { key: ContactResult; label: string }[] = [
  { key: "no_answer", label: "부재중" },
  { key: "connected", label: "연결" },
  { key: "appointment", label: "약속" },
  { key: "rejected", label: "거절" },
  { key: "hold", label: "보류" },
];
export interface ContactLog {
  id: number;
  result: ContactResult;
  result_display: string;
  memo: string;
  created_at: string;
}
/** GET /api/v1/customers/<id>/contact-logs/ — 최근순 */
export async function listContactLogs(customerId: number): Promise<PaginatedResult<ContactLog>> {
  return request<PaginatedResult<ContactLog>>("GET", `/customers/${customerId}/contact-logs/`, undefined, true);
}
/** POST .../contact-logs/ — 접촉 결과 기록(생성 시 last_contacted_at 자동 갱신) */
export async function createContactLog(customerId: number, payload: { result: ContactResult; memo?: string }): Promise<ContactLog> {
  return request<ContactLog>("POST", `/customers/${customerId}/contact-logs/`, payload, true);
}

// ─── 오늘 전화할 고객 (call-list) — pull 방식, 화면 열 때 계산 ────────────────
/** call-list 1행 — reasons 는 그대로 칩으로 렌더 가능한 한글 라벨(연락 우선순위, 판정 아님). */
export interface CallListRow {
  id: number;
  name: string;
  mobile_phone_number: string;
  sales_stage: SalesStage;
  score: number;
  reasons: string[];               // 예: ["생일 D-3", "만기 D-12", "무접촉 21일"]
  last_contacted_at: string | null;
}
export interface CallListResponse {
  results: CallListRow[];          // 점수순, 기본 10명 (limit로 최대 50명)
  total_candidates: number;        // 사유 있는 전체 후보 수
}
/** GET /api/v1/customers/call-list/ — 본인 소유 + 진행중(active)만, 점수순.
 *  limit: 기본 10 · 최대 50(BE 클램프). 전용 화면(/call-list)은 50으로 요청. */
export async function getCallList(limit?: number): Promise<CallListResponse> {
  const qs = limit != null ? `?limit=${limit}` : "";
  return request<CallListResponse>("GET", `/customers/call-list/${qs}`, undefined, true);
}

/** DELETE /api/v1/customers/{id}/ — 204 No Content → void */
export async function deleteCustomer(id: number): Promise<void> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const tok = tokenStore.get();
  if (tok) headers["Authorization"] = `Token ${tok}`;
  const res = await fetch(`${API_BASE}/customers/${id}/`, { method: "DELETE", headers });
  if (!res.ok) {
    let data: Record<string, unknown> = {};
    try { data = await res.json(); } catch { /* empty */ }
    const code = (data["error"] as string) ?? String(res.status);
    const detail = extractErrorDetail(data, res.statusText);
    handleUnauthorized(res.status);
    throw new ApiError(res.status, code, detail);
  }
}

// ─── Heatmap types ───────────────────────────────────────────────────────────

export type HeatmapStatus = "neutral" | "shortage" | "adequate" | "over";

export interface HeatmapBaseline {
  min: number | null;
  max: number | null;
  unit: string | null;
  baseline_source: string | null;
}

export interface HeatmapContribution {
  case_id: number;
  insurance_id: number;
  insurance_name: string | null;
  raw_name: string;
  assurance_amount: number;
  source_page: number | null;
  mapping_source: "global" | "planner_override" | "manual";
}

export interface HeatmapDetail {
  detail_id: number;
  name: string;
  held_amount: number | null;
  status: HeatmapStatus;
  baseline: HeatmapBaseline | null;
  contributions: HeatmapContribution[];
}

export interface HeatmapSubCategory {
  sub_category_id: number;
  name: string;
  details: HeatmapDetail[];
}

export interface HeatmapCategory {
  category_id: number;
  name: string;
  insurance_type: string;
  sub_categories: HeatmapSubCategory[];
}

export interface InsuranceCaseFee {
  detail_name: string;
  premium: number | null;             // 월 보험료(담보)
  payment_period_type: number;        // 1 년/2 세 = 비갱신, 3 년갱신 = 갱신
  is_renewal: boolean;
  assurance_amount: number | null;
  total_renewal_premium: number | null;
  total_non_renewal_premium: number | null;
}

export interface InsuranceFee {
  id: number;
  name: string | null;
  insurance_type: number;
  portfolio_type: number;
  monthly_premiums: number | null;
  monthly_renewal_premium: number | null;
  monthly_non_renewal_premium: number | null;
  monthly_earned_premium: number | null;
  total_premiums: number | null;
  total_renewal_premium: number | null;
  total_non_renewal_premium: number | null;
  total_earned_premium: number | null;
  review_status: "legacy_review_required" | "draft" | "confirmed" | "excluded" | "superseded";
  analysis_included: boolean;
  confirmed_at: string | null;
  case_fees: InsuranceCaseFee[];      // 수기입력 보험은 []
}

export interface HeatmapSummary {
  monthly_premiums: number | null;
  monthly_renewal_premium: number | null;
  monthly_non_renewal_premium: number | null;
  monthly_earned_premium: number | null;
  total_premiums: number | null;
  total_renewal_premium: number | null;
  total_non_renewal_premium: number | null;
  total_earned_premium: number | null;
  [key: string]: unknown;
}

export interface HeatmapResponse {
  customer_id: number;
  mode: "neutral" | "graded";
  baseline_present: boolean;
  baseline_count: number;       // graded 근거(보유한 살아있는 기준 수) — PM 06.24 명확화
  insurance_count: number;
  included_insurance_count: number;
  excluded_insurance_count: number;
  last_confirmed_at: string | null;
  pending_review_count: number;
  can_share: boolean;
  share_block_reason: string | null;
  summary: HeatmapSummary;
  chart_list: unknown[];
  tree: HeatmapCategory[];
  insurances: InsuranceFee[];
}

/** GET /api/v1/customers/<id>/heatmap/ — requires token.
 *  insuranceId 를 주면 그 보험 1건만 집계한 트리/summary (보험별 상세 보기).
 *  남의/없는 보험 id 는 BE 가 404 (owner 격리). */
export async function getHeatmap(customerId: number, insuranceId?: number): Promise<HeatmapResponse> {
  const qs = insuranceId != null ? `?insurance_id=${insuranceId}` : "";
  return request<HeatmapResponse>("GET", `/customers/${customerId}/heatmap/${qs}`, undefined, true);
}

// ─── 담보 사전 피드백 (담보 위치 확인 요청, 2026-07-09) ─────────────────────
// BE: analysis/flags.py — 한눈표에서 잘못 잡힌 담보를 알리면 운영팀이 검수해
// 정규화 사전에 반영(다음 분석부터 자동 적용). 소유자 격리(타인 고객 404).

/** 표준 담보(leaf)에 연결된 고객 담보 케이스 1건 — 플래그 모달의 선택지. */
export interface CoverageCase {
  case_id: number;
  insurance_id: number;
  insurance_title: string | null;
  /** 카탈로그 담보명 */
  name: string;
  /** 증권에서 읽은 원문명 — 빈 값(직접 입력/과거 데이터)이면 name 으로 폴백 표시 */
  raw_name: string;
  assurance_amount: number | null;
}

/** GET /api/v1/customers/<id>/coverage-cases/?detail_id= */
export async function getCoverageCases(
  customerId: number,
  detailId: number
): Promise<CoverageCase[]> {
  return request<CoverageCase[]>(
    "GET",
    `/customers/${customerId}/coverage-cases/?detail_id=${detailId}`,
    undefined,
    true
  );
}

/** POST /api/v1/customers/<id>/coverage-flags/ — 담보 위치 확인 요청 생성.
 *  raw_name/보험사 스냅샷은 서버가 케이스에서 복사(클라이언트 입력 불신). */
export async function createCoverageFlag(
  customerId: number,
  payload: { analysis_detail_id: number; case_id?: number; note?: string }
): Promise<{ id: number; status: string }> {
  return request<{ id: number; status: string }>(
    "POST",
    `/customers/${customerId}/coverage-flags/`,
    payload,
    true
  );
}

// ─── 설계사 기준선 (PlannerBaseline) ─────────────────────────────────────────
// ★ 준법 통제점 (dev/10): baseline_source 가 null 이면 분석은 neutral 강제.
//   기준을 설정하면(source='planner') 부족/적정/넉넉 판정 권위·최종책임은 설계사.
// BE 계약: customers/urls.py → router.register('planner-baselines', ...)
//   → /api/v1/planner-baselines/  (ModelViewSet, IsOwner)
// 필드 출처: customers/serializers.py PlannerBaselineSerializer + models.py PlannerBaseline.

/** 상품군 (PlannerBaseline.PRODUCT_GROUP_CHOICES) */
export type ProductGroup = 1 | 2 | 3 | 4; // 1=생명 2=손해 3=실손 4=연금저축

/** 성별 (PlannerBaseline.GENDER_TYPE) — null=성별 무관 공통 밴드 */
export type BaselineGender = 1 | 2 | null; // 1=남 2=여

/** 금액 단위 (PlannerBaseline.unit) */
export type BaselineUnit = 1 | 2 | 3; // 1=만원 2=원 3=구좌

/**
 * 기준선 1행. DRF DecimalField 는 JSON 직렬화 시 문자열로 내려온다
 * (recommend_min/max). null 가능.
 * baseline_source: 'planner'(직접) | 'preset:<id>'(프리셋 채택) | null(미설정→neutral).
 */
export interface PlannerBaseline {
  id: number;
  coverage_key: string;
  product_group: ProductGroup;
  age_band: string; // '20s'|'30s'|'40s'|'50s'|'60s+'
  gender: BaselineGender;
  recommend_min: string | null;
  recommend_max: string | null;
  unit: BaselineUnit;
  baseline_source: string | null;
  preset_origin: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

/** 생성/수정 payload — read_only(id/created_at/updated_at) 제외 */
export interface PlannerBaselineWritePayload {
  coverage_key: string;
  product_group: ProductGroup;
  age_band: string;
  gender?: BaselineGender;
  recommend_min?: string | number | null;
  recommend_max?: string | number | null;
  unit?: BaselineUnit;
  baseline_source?: string | null;
  preset_origin?: string | null;
  is_active?: boolean;
}

/** GET /api/v1/planner-baselines/?product_group=&age_band=&gender= — {count, next, previous, results} */
export async function listBaselines(
  params: {
    page?: number;
    product_group?: ProductGroup;
    age_band?: string;
    gender?: BaselineGender;
  } = {}
): Promise<PaginatedResult<PlannerBaseline>> {
  const qs = new URLSearchParams();
  if (params.page) qs.set("page", String(params.page));
  if (params.product_group) qs.set("product_group", String(params.product_group));
  if (params.age_band) qs.set("age_band", params.age_band);
  if (params.gender !== undefined && params.gender !== null) {
    qs.set("gender", String(params.gender));
  }
  const query = qs.toString() ? `?${qs.toString()}` : "";
  return request<PaginatedResult<PlannerBaseline>>(
    "GET",
    `/planner-baselines/${query}`,
    undefined,
    true
  );
}

/** POST /api/v1/planner-baselines/ — 직접 입력은 baseline_source='planner' 로 보냄 */
export async function createBaseline(
  payload: PlannerBaselineWritePayload
): Promise<PlannerBaseline> {
  return request<PlannerBaseline>("POST", "/planner-baselines/", payload, true);
}

/** PATCH /api/v1/planner-baselines/{id}/ */
export async function updateBaseline(
  id: number,
  payload: Partial<PlannerBaselineWritePayload>
): Promise<PlannerBaseline> {
  return request<PlannerBaseline>("PATCH", `/planner-baselines/${id}/`, payload, true);
}

/** DELETE /api/v1/planner-baselines/{id}/ — 204 No Content → void */
export async function deleteBaseline(id: number): Promise<void> {
  return requestVoid("DELETE", `/planner-baselines/${id}/`);
}

// ─── DELETE helper (204 No Content → void) ─────────────────────────────────────

async function requestVoid(method: string, path: string, auth = true): Promise<void> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (auth) {
    const tok = tokenStore.get();
    if (tok) headers["Authorization"] = `Token ${tok}`;
  }
  const res = await fetch(`${API_BASE}${path}`, { method, headers });
  if (!res.ok) {
    let data: Record<string, unknown> = {};
    try { data = await res.json(); } catch { /* empty */ }
    const code = (data["error"] as string) ?? (data["code"] as string) ?? String(res.status);
    const detail = extractErrorDetail(data, res.statusText);
    if (auth) handleUnauthorized(res.status);
    throw new ApiError(res.status, code, detail);
  }
}

/** 일부 BE 목록 응답은 {count, results}만 반환(next/previous 없음 — promotion) */
export interface CountResult<T> {
  count: number;
  results: T[];
}

// ════════════════════════════════════════════════════════════════════════════
// 게시판 & 커뮤니티 (boards)  — base: /board/  (urls.py boards 기준)
// ════════════════════════════════════════════════════════════════════════════

export type PostCategory = string | null;

export interface PostAuthor {
  id: number | null;
  display_name: string;
}

/** 피드 목록 항목 (PostFeedSerializer) */
export interface PostFeedItem {
  id: number;
  author: PostAuthor;
  title: string;
  body_preview: string;
  like_count: number;
  comment_count: number;
  view_count: number;
  created_at: string;
  updated_at: string;
  is_pinned: boolean;
  is_edited: boolean;
  category: PostCategory;
  thumbnail_url: string | null;
}

export interface PostAttachment {
  id: number;
  file_url: string;
  file_name: string;
  mime_type: string;
  file_size: number;
}

/** 게시글 상세 (PostDetailSerializer) */
export interface PostDetail {
  id: number;
  author: PostAuthor;
  title: string;
  body: string;
  like_count: number;
  comment_count: number;
  view_count: number;
  created_at: string;
  updated_at: string;
  is_pinned: boolean;
  is_deleted: boolean;
  is_hidden: boolean;
  is_edited: boolean;
  category: PostCategory;
  attachments: PostAttachment[];
}

export interface PostWritePayload {
  body: string;
  title?: string;
  category?: string | null;
}

/** 게시판 피드는 커서 페이지네이션 (PostCursorPagination) */
export interface CursorResult<T> {
  next_cursor: string | null;
  previous_cursor: string | null;
  results: T[];
}

/** GET /api/v1/board/posts/?cursor=&page_size=&ordering= */
export async function listPosts(
  params: { cursor?: string; page_size?: number; ordering?: "latest" | "popular" } = {}
): Promise<CursorResult<PostFeedItem>> {
  const qs = new URLSearchParams();
  if (params.cursor) qs.set("cursor", params.cursor);
  if (params.page_size) qs.set("page_size", String(params.page_size));
  if (params.ordering) qs.set("ordering", params.ordering);
  const query = qs.toString() ? `?${qs.toString()}` : "";
  return request<CursorResult<PostFeedItem>>("GET", `/board/posts/${query}`, undefined, true);
}

/** GET /api/v1/board/posts/{id}/ */
export async function getPost(id: number): Promise<PostDetail> {
  return request<PostDetail>("GET", `/board/posts/${id}/`, undefined, true);
}

/** POST /api/v1/board/posts/ */
export async function createPost(payload: PostWritePayload): Promise<PostDetail> {
  return request<PostDetail>("POST", "/board/posts/", payload, true);
}

/** PATCH /api/v1/board/posts/{id}/ */
export async function updatePost(id: number, payload: Partial<PostWritePayload>): Promise<PostDetail> {
  return request<PostDetail>("PATCH", `/board/posts/${id}/`, payload, true);
}

/** DELETE /api/v1/board/posts/{id}/ — 소프트 삭제 */
export async function deletePost(id: number): Promise<void> {
  return requestVoid("DELETE", `/board/posts/${id}/`);
}

export interface LikeToggleResponse {
  liked: boolean;
  like_count: number;
}

/** POST /api/v1/board/posts/{id}/like/ — 좋아요 토글 */
export async function toggleLike(postId: number): Promise<LikeToggleResponse> {
  return request<LikeToggleResponse>("POST", `/board/posts/${postId}/like/`, undefined, true);
}

/** 댓글 (CommentSerializer — replies 1단계 인라인) */
export interface CommentItem {
  id: number;
  post: number;
  author: PostAuthor;
  parent: number | null;
  body: string;
  is_deleted: boolean;
  is_hidden: boolean;
  created_at: string;
  updated_at: string;
  replies: CommentItem[];
}

/** GET /api/v1/board/posts/{postId}/comments/ — 평면 배열 반환 */
export async function listComments(postId: number): Promise<CommentItem[]> {
  return request<CommentItem[]>("GET", `/board/posts/${postId}/comments/`, undefined, true);
}

/** POST /api/v1/board/posts/{postId}/comments/ */
export async function createComment(
  postId: number,
  payload: { body: string; parent?: number | null }
): Promise<CommentItem> {
  return request<CommentItem>(
    "POST",
    `/board/posts/${postId}/comments/`,
    { post: postId, body: payload.body, parent: payload.parent ?? null },
    true
  );
}

/** PATCH /api/v1/board/comments/{id}/ */
export async function updateComment(id: number, body: string): Promise<CommentItem> {
  return request<CommentItem>("PATCH", `/board/comments/${id}/`, { body }, true);
}

/** DELETE /api/v1/board/comments/{id}/ — 소프트 삭제 */
export async function deleteComment(id: number): Promise<void> {
  return requestVoid("DELETE", `/board/comments/${id}/`);
}

export type ReportContentType = "post" | "comment";
export type ReportReason = "spam" | "hate" | "adult" | "fake" | "other";

export interface ReportPayload {
  content_type: ReportContentType;
  object_id: number;
  reason: ReportReason;
  detail?: string;
}

export interface ReportResponse {
  id: number;
  content_type: ReportContentType;
  object_id: number;
  reason: ReportReason;
  detail: string | null;
  status: string;
  created_at: string;
}

/** POST /api/v1/board/reports/ — 신고 접수 */
export async function reportContent(payload: ReportPayload): Promise<ReportResponse> {
  return request<ReportResponse>("POST", "/board/reports/", payload, true);
}

// ── 공지사항 (Notice — AllowAny GET, 평면 배열) ─────────────────────────────

export interface NoticeItem {
  id: number;
  author: number | null;
  author_name: string;
  title: string;
  body: string;
  is_pinned: boolean;
  is_published: boolean;
  published_at: string | null;
  created_at: string;
  updated_at: string;
}

/** GET /api/v1/board/notices/ — 평면 배열 */
export async function listNotices(): Promise<NoticeItem[]> {
  return request<NoticeItem[]>("GET", "/board/notices/", undefined, false);
}

/** GET /api/v1/board/notices/{id}/ */
export async function getNotice(id: number): Promise<NoticeItem> {
  return request<NoticeItem>("GET", `/board/notices/${id}/`, undefined, false);
}

// ── FAQ (Faq — AllowAny GET, 평면 배열) ─────────────────────────────────────

export interface FaqItem {
  id: number;
  category: string;
  question: string;
  answer: string;
  order: number;
  is_published: boolean;
  created_at: string;
  updated_at: string;
}

/** GET /api/v1/board/faqs/?category=&q= — 평면 배열 */
export async function listFaqs(
  params: { category?: string; q?: string } = {}
): Promise<FaqItem[]> {
  const qs = new URLSearchParams();
  if (params.category) qs.set("category", params.category);
  if (params.q) qs.set("q", params.q);
  const query = qs.toString() ? `?${qs.toString()}` : "";
  return request<FaqItem[]>("GET", `/board/faqs/${query}`, undefined, false);
}

// ── 인파 노트 (BlogPost — AllowAny GET, 읽기 전용) ──────────────────────────
// 공개 직렬화는 tags 를 문자열 배열로 준다(어드민만 RAW 콤마 문자열 + tags_list).
// 서버 컴포넌트(app/blog)에서 그대로 호출한다 — request()는 auth=false 라 토큰 불필요.

/** 카테고리 코드 → 공개 라벨. 라벨은 API(category_label)가 SSOT지만 탭 렌더용 정적 목록으로 재사용. */
export type BlogCategory = "sales" | "coverage" | "safety" | "story";
export const BLOG_CATEGORIES: { code: BlogCategory; label: string }[] = [
  { code: "sales", label: "고객 늘리기" },
  { code: "coverage", label: "보장분석" },
  { code: "safety", label: "안심 가이드" },
  { code: "story", label: "설계사 이야기" },
];

/** 목록 아이템(본문 없음). */
export interface BlogListItem {
  id: number;
  title: string;
  slug: string;
  excerpt: string;
  cover_image: string | null; // 절대 URL(R2) 또는 null
  category: BlogCategory;
  category_label: string;
  tags: string[];
  author_name: string;
  published_at: string | null; // ISO
  view_count: number;
}

/** 상세(본문 마크다운 포함). */
export interface BlogDetail {
  id: number;
  title: string;
  slug: string;
  excerpt: string;
  body: string; // 마크다운
  cover_image: string | null;
  category: BlogCategory;
  category_label: string;
  tags: string[];
  author_name: string;
  published_at: string | null;
  updated_at: string;
  created_at: string;
  view_count: number;
  seo_title: string;
  seo_description: string;
  is_noindex: boolean;
}

/** GET /api/v1/board/blog/?category=&page=&page_size= — 게시글 목록(페이지네이션). */
export async function listBlogPosts(
  params: { category?: BlogCategory | string; page?: number; pageSize?: number } = {}
): Promise<PaginatedResult<BlogListItem>> {
  const qs = new URLSearchParams();
  if (params.category) qs.set("category", params.category);
  if (params.page) qs.set("page", String(params.page));
  if (params.pageSize) qs.set("page_size", String(params.pageSize));
  const query = qs.toString() ? `?${qs.toString()}` : "";
  return request<PaginatedResult<BlogListItem>>("GET", `/board/blog/${query}`, undefined, false);
}

/** GET /api/v1/board/blog/<slug>/ — 상세. 공개 조회 시 BE가 조회수 증가. 초안·미존재 = 404(ApiError). */
export async function getBlogPost(slug: string): Promise<BlogDetail> {
  return request<BlogDetail>("GET", `/board/blog/${encodeURIComponent(slug)}/`, undefined, false);
}

/** GET /api/v1/board/blog/sitemap/ — 게시글 {slug, updated_at} 경량 목록(sitemap.xml 구동용). */
export async function getBlogSitemap(): Promise<{ slug: string; updated_at: string }[]> {
  return request<{ slug: string; updated_at: string }[]>(
    "GET",
    "/board/blog/sitemap/",
    undefined,
    false
  );
}

// ── 1:1 문의 (Inquiry — 비공개) ─────────────────────────────────────────────

export type InquiryCategory = "feedback" | "feature" | "billing" | "bug" | "other";
export type InquiryStatus = "open" | "answered" | "closed";

export interface InquiryListItem {
  id: number;
  category: InquiryCategory;
  title: string;
  status: InquiryStatus;
  created_at: string;
  updated_at: string;
}

export interface InquiryReply {
  id: number;
  inquiry: number;
  author: number | null;
  author_name: string;
  body: string;
  created_at: string;
  updated_at: string;
}

export interface InquiryDetail {
  id: number;
  category: InquiryCategory;
  title: string;
  body: string;
  status: InquiryStatus;
  created_at: string;
  updated_at: string;
  replies: InquiryReply[];
}

export interface InquiryWritePayload {
  category: InquiryCategory;
  title: string;
  body: string;
}

/** GET /api/v1/board/inquiries/ — 내 문의 평면 배열 */
export async function listInquiries(): Promise<InquiryListItem[]> {
  return request<InquiryListItem[]>("GET", "/board/inquiries/", undefined, true);
}

/** GET /api/v1/board/inquiries/{id}/ — 상세 + 답변 */
export async function getInquiry(id: number): Promise<InquiryDetail> {
  return request<InquiryDetail>("GET", `/board/inquiries/${id}/`, undefined, true);
}

/** POST /api/v1/board/inquiries/ */
export async function createInquiry(payload: InquiryWritePayload): Promise<InquiryDetail> {
  return request<InquiryDetail>("POST", "/board/inquiries/", payload, true);
}

// ── 의견 위젯 (Feedback) — 공개 엔드포인트, 로그인 선택 ────────────────────────

/** 불편 신고 시 자동 첨부되는 화면 정보(관리자 전용 노출). PII 아님. */
export interface FeedbackMeta {
  path?: string;
  user_agent?: string;
  viewport?: string;
}

export interface FeedbackPayload {
  category: InquiryCategory;   // feedback | feature | bug | other
  body: string;
  rating?: number;             // 이용 의견(별점 1~5)만
  meta?: FeedbackMeta;         // 불편 신고 화면 정보
  contact_email?: string;      // 비회원 답변 채널(선택)
}

export interface FeedbackResponse {
  id?: number;
  created?: boolean;
}

/**
 * POST /api/v1/feedback/ — 의견 위젯 제출.
 * 공개 엔드포인트(AllowAny). 로그인 상태면 토큰을 실어 보내 owner 에 귀속되고,
 * 비로그인이면 토큰 없이 전송한다(contact_email 로 답장). 401 리다이렉트 처리는 하지 않는다.
 */
export async function submitFeedback(payload: FeedbackPayload): Promise<FeedbackResponse> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const tok = tokenStore.get();
  if (tok) headers["Authorization"] = `Token ${tok}`;
  const res = await fetch(`${API_BASE}/feedback/`, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new ApiError(
      res.status,
      (data as { code?: string }).code ?? "ERROR",
      (data as { detail?: string }).detail ?? "보내지 못했어요. 잠시 후 다시 시도해 주세요.",
    );
  }
  return data as FeedbackResponse;
}

// ════════════════════════════════════════════════════════════════════════════
// 판촉물 (promotion)  — base: /promotion/
// ════════════════════════════════════════════════════════════════════════════

export type PromotionCategory = string;

export interface PromotionSampleListItem {
  id: number;
  name: string;
  category: PromotionCategory;
  description: string;
  is_available: boolean;
  is_digital: boolean;            // 전자자료(1회 무료 다운로드)
  primary_image: string | null;
  sort_order: number;
}

export interface PromotionSampleImage {
  id: number;
  url: string;
  is_primary: boolean;
  sort_order: number;
}

/** 주문 폼 필드 정의 (sample.form_fields) */
export interface PromotionFormField {
  key: string;
  label: string;
  type?: string;
  required?: boolean;
  options?: string[];
  [k: string]: unknown;
}

export interface PromotionSampleDetail {
  id: number;
  name: string;
  category: PromotionCategory;
  description: string;
  is_available: boolean;
  is_digital: boolean;            // 전자자료(1회 무료 다운로드 후 어드민 큐)
  images: PromotionSampleImage[];
  form_fields: PromotionFormField[];
  sort_order: number;
}

/** 전자자료 요청 결과 — free(무료 다운로드) | queued(어드민 큐) */
export interface DigitalRequestResult {
  mode: "free" | "queued";
  file_url?: string | null;
  order_id?: number;
  detail: string;
}
/** POST /promotion/samples/<id>/request/ — 1회 무료 / 2회차+ 어드민 큐 */
export async function requestDigitalSample(sampleId: number): Promise<DigitalRequestResult> {
  return request<DigitalRequestResult>("POST", `/promotion/samples/${sampleId}/request/`, {}, true);
}

export type PromotionOrderStatus =
  | "pending"
  | "reviewing"
  | "producing"
  | "shipping"
  | "completed"
  | "cancelled";

export interface PromotionOrderStatusLog {
  to_status: PromotionOrderStatus;
  status_display: string;
  changed_at: string;
  note: string;
}

export interface PromotionOrderSampleRef {
  id: number;
  name: string | null;
}

export interface PromotionOrderListItem {
  id: number;
  status: PromotionOrderStatus;
  status_display: string;
  sample: PromotionOrderSampleRef | null;
  admin_note: string;
  tracking_number: string;
  created_at: string;
  updated_at: string;
}

export interface PromotionOrderDetail extends PromotionOrderListItem {
  form_response: Record<string, unknown>;
  carrier: string;
  status_logs: PromotionOrderStatusLog[];
}

/** GET /api/v1/promotion/samples/ — {count, results} */
export async function listSamples(): Promise<CountResult<PromotionSampleListItem>> {
  return request<CountResult<PromotionSampleListItem>>(
    "GET",
    "/promotion/samples/",
    undefined,
    true
  );
}

/** GET /api/v1/promotion/samples/{id}/ — form_fields 포함 */
export async function getSample(id: number): Promise<PromotionSampleDetail> {
  return request<PromotionSampleDetail>("GET", `/promotion/samples/${id}/`, undefined, true);
}

/** POST /api/v1/promotion/orders/ — 주문 생성 */
export async function createOrder(payload: {
  sample: number;
  form_response: Record<string, unknown>;
}): Promise<PromotionOrderDetail> {
  return request<PromotionOrderDetail>("POST", "/promotion/orders/", payload, true);
}

/** GET /api/v1/promotion/orders/ — 내 주문 목록 {count, results} */
export async function listMyOrders(): Promise<CountResult<PromotionOrderListItem>> {
  return request<CountResult<PromotionOrderListItem>>(
    "GET",
    "/promotion/orders/",
    undefined,
    true
  );
}

/** GET /api/v1/promotion/orders/{id}/ — 상세 + 타임라인 */
export async function getMyOrder(id: number): Promise<PromotionOrderDetail> {
  return request<PromotionOrderDetail>("GET", `/promotion/orders/${id}/`, undefined, true);
}

/** DELETE /api/v1/promotion/orders/{id}/ — 주문 취소 (pending만) */
export async function cancelOrder(id: number): Promise<void> {
  return requestVoid("DELETE", `/promotion/orders/${id}/`);
}

// ════════════════════════════════════════════════════════════════════════════
// 알림 (notifications)  — base: /notifications/, /reminder-rules/
// ════════════════════════════════════════════════════════════════════════════

export type NotifType =
  | "expiry_soon"
  | "birthday_soon"
  | "consult_reminder"
  | "task_due"
  | "share_unread"
  | "unpaid_d_alert"
  | "self_diagnosis_lead"
  | "board_comment"
  | "board_like"
  | "meeting_booked";

// 받은함(알림 센터)에 뜰 수 있는 전체 유형 = 리마인더용 NotifType + 판촉물/담보/문의/데드맨 등.
// (리마인더 규칙은 NotifType 부분집합만 다루므로 ReminderRule 은 NotifType 유지.)
export type NotificationType =
  | NotifType
  | "promotion_status"
  | "promotion_digital_ready"
  | "promotion_digital_requested"
  | "coverage_flag_requested"
  | "signup_verify_flatline"
  | "inquiry_answered"
  | "inquiry_received"
  | "recruiting_application"
  | "recruiting_followup"
  | "recruiting_settlement"
  | "manager_promoted";

export interface NotificationItem {
  id: number;
  notif_type: NotificationType;
  title: string;
  body: string;
  target_date: string | null;
  customer: number | null;
  customer_name: string | null;
  calendar_event_id: number | null;
  meeting: number | null;              // 미팅 예약 알림의 수락/거절 대상
  meeting_status: MeetingStatus | null; // 'pending'이면 수락/거절 버튼 노출
  is_read: boolean;
  created_at: string;
}

/** GET /api/v1/notifications/?is_read=&page= — {count, next, previous, results} */
export async function listNotifications(
  params: { page?: number; is_read?: boolean } = {}
): Promise<PaginatedResult<NotificationItem>> {
  const qs = new URLSearchParams();
  if (params.page) qs.set("page", String(params.page));
  if (params.is_read !== undefined) qs.set("is_read", String(params.is_read));
  const query = qs.toString() ? `?${qs.toString()}` : "";
  return request<PaginatedResult<NotificationItem>>(
    "GET",
    `/notifications/${query}`,
    undefined,
    true
  );
}

/** GET /api/v1/notifications/unread-count/ — 벨 배지 */
// unread_count = 전체(받은함·벨). 나머지 = 그 부분집합(네비 메뉴별 배지). 각 유형은 한 카테고리에만 포함.
export interface UnreadCount {
  unread_count: number;
  customers: number;
  schedule: number;
  board: number;
  promotion: number;
  admin: number;
  recruiting: number;
}
export async function getUnreadCount(): Promise<UnreadCount> {
  return request<UnreadCount>("GET", "/notifications/unread-count/", undefined, true);
}

/** PATCH /api/v1/notifications/{id}/read/ — 단일 읽음 */
export async function markNotificationRead(id: number): Promise<NotificationItem> {
  return request<NotificationItem>("PATCH", `/notifications/${id}/read/`, {}, true);
}

/** POST /api/v1/notifications/read-all/ — 전체 읽음 */
export async function markAllNotificationsRead(): Promise<{ updated: number }> {
  return request<{ updated: number }>(
    "POST",
    "/notifications/read-all/",
    undefined,
    true
  );
}

/** DELETE /api/v1/notifications/{id}/ — 단일 삭제 */
export async function deleteNotification(id: number): Promise<void> {
  return requestVoid("DELETE", `/notifications/${id}/`);
}

export interface ReminderRule {
  id: number;
  rule_type: NotifType;
  days_before: number;
  enabled: boolean;
  email_enabled: boolean;
  updated_at: string;
}

export interface ReminderRuleBulkItem {
  rule_type: NotifType;
  days_before?: number;
  enabled?: boolean;
  email_enabled?: boolean;
}

/** GET /api/v1/reminder-rules/ — 내 설정 5종 (평면 배열) */
export async function listReminderRules(): Promise<ReminderRule[]> {
  return request<ReminderRule[]>("GET", "/reminder-rules/", undefined, true);
}

/** PATCH /api/v1/reminder-rules/bulk/ — 일괄 업데이트 (배열 전송, 전체 반환) */
export async function updateReminderRules(
  items: ReminderRuleBulkItem[]
): Promise<ReminderRule[]> {
  return request<ReminderRule[]>("PATCH", "/reminder-rules/bulk/", items, true);
}

// ════════════════════════════════════════════════════════════════════════════
// 요금제 / 사용량 (billing)  — base: /billing/
// ════════════════════════════════════════════════════════════════════════════

export interface Plan {
  code: string;
  display_name: string;
  price_krw: number;
  /** 연 결제 금액(VAT 별도). null이면 price_krw*10 폴백(2개월 무료). */
  price_annual_krw: number | null;
  description: string;
  limit_ocr: number | null;
  limit_ai_compare: number | null;
  limit_analysis: number | null;
  limit_promotion: number | null;
  limit_customer: number | null;
  is_active: boolean;
}

export interface UsageItem {
  action: string;
  label: string;
  count: number;
  limit: number | null;
  remaining: number | null;
}

export interface BillingUsage {
  plan: { code: string; display_name: string; price_krw: number };
  subscription: { status: string; expires_at: string | null };
  year_month: string;
  usage: UsageItem[];
}

/** GET /api/v1/billing/plans/ — 요금제 목록 (AllowAny, 평면 배열) */
export async function listPlans(): Promise<Plan[]> {
  return request<Plan[]>("GET", "/billing/plans/", undefined, false);
}

export interface BillingEvent {
  /** 첫 유료 결제 +1개월 보너스 이벤트가 실제로 켜져 있는지(RuntimeConfig). */
  first_paid_bonus_enabled: boolean;
}

/** GET /api/v1/billing/event/ — 진행 중 결제 이벤트 플래그 (AllowAny, 토큰 불필요).
 *  랜딩·업그레이드 모달의 이벤트 문구를 이 값이 true일 때만 노출한다(§6 정직성).
 *  연 결제 할인(실제 가격)은 이 플래그와 무관하게 항상 표시. */
export async function getBillingEvent(): Promise<BillingEvent> {
  return request<BillingEvent>("GET", "/billing/event/", undefined, false);
}

/** GET /api/v1/billing/usage/ — 내 사용량 + 구독 */
export async function getMyUsage(): Promise<BillingUsage> {
  return request<BillingUsage>("GET", "/billing/usage/", undefined, true);
}

/**
 * 내 요금제 요약 — billing/usage 응답의 plan+subscription을 발췌.
 * (별도 /myPlan 엔드포인트 없음 → usage에서 파생)
 */
export async function getMyPlan(): Promise<BillingUsage["plan"] & { status: string; expires_at: string | null }> {
  const u = await getMyUsage();
  return { ...u.plan, status: u.subscription.status, expires_at: u.subscription.expires_at };
}

export interface CouponRedeemResult {
  plan_code: string;
  plan_display_name: string;
  expires_at: string;   // ISO — 부여 만료 시각
  duration_days: number;
}

/** POST /api/v1/billing/coupons/redeem/ — 무료 쿠폰 코드 사용(인증).
 *  실패 시 ApiError(.code = not_found/already/expired/exhausted/inactive, .message = 안내문). */
export async function redeemCoupon(code: string): Promise<CouponRedeemResult> {
  return request<CouponRedeemResult>("POST", "/billing/coupons/redeem/", { code }, true);
}

// ════════════════════════════════════════════════════════════════════════════
// 관리자 콘솔 (admin)  — base: /admin/   (is_admin 권한 필요)
// ════════════════════════════════════════════════════════════════════════════

export interface AdminUserListItem {
  id: number;
  email: string;
  date_joined: string;
  last_login: string | null;
  affiliation: string | null;
  plan_code: string;
  plan_display: string;
  subscription_status: string | null;
  is_dormant: boolean;
  will_delete_at: string | null;
}

/** GET /api/v1/admin/users/?q=&plan=&is_dormant= — {count, next, previous, results} */
export async function adminListUsers(
  params: { page?: number; q?: string; plan?: string; is_dormant?: boolean } = {}
): Promise<PaginatedResult<AdminUserListItem>> {
  const qs = new URLSearchParams();
  if (params.page) qs.set("page", String(params.page));
  if (params.q) qs.set("q", params.q);
  if (params.plan) qs.set("plan", params.plan);
  if (params.is_dormant !== undefined) qs.set("is_dormant", String(params.is_dormant));
  const query = qs.toString() ? `?${qs.toString()}` : "";
  return request<PaginatedResult<AdminUserListItem>>(
    "GET",
    `/admin/users/${query}`,
    undefined,
    true
  );
}

export interface AdminDashboardStats {
  today_new_users: number;
  today_new_orders: number;
  open_inquiries: number;
  pending_reports: number;
  total_users: number;
  total_customers: number;
  plan_distribution: Record<string, number>;
  pending_orders: number;
  unresolved_unmatched: number;
  /** 담보 위치 확인 요청(설계사 피드백) 대기 건수 */
  open_flags: number;
}

/** GET /api/v1/admin/dashboard/ — 운영 지표 (사실 카운트만) */
export async function adminGetStats(): Promise<AdminDashboardStats> {
  return request<AdminDashboardStats>("GET", "/admin/dashboard/", undefined, true);
}

/** POST /api/v1/admin/notices/ — 공지 작성 (관리자) */
export async function adminCreateNotice(payload: {
  title: string;
  body: string;
  is_pinned?: boolean;
  is_published?: boolean;
  published_at?: string | null;
}): Promise<NoticeItem> {
  return request<NoticeItem>("POST", "/admin/notices/", payload, true);
}

export interface AdminInquiryListItem {
  id: number;
  owner_email: string | null;   // null = 비회원(익명) 제출
  category: InquiryCategory;
  title: string;
  status: InquiryStatus;
  rating: number | null;        // 이용 의견 별점(1~5), 그 외 null
  contact_email: string;        // 비회원 답변 이메일(없으면 '')
  created_at: string;
  updated_at: string;
}

/** GET /api/v1/admin/inquiries/?status=&category= — {count, next, previous, results} */
export async function adminListInquiries(
  params: { page?: number; status?: InquiryStatus; category?: InquiryCategory } = {}
): Promise<PaginatedResult<AdminInquiryListItem>> {
  const qs = new URLSearchParams();
  if (params.page) qs.set("page", String(params.page));
  if (params.status) qs.set("status", params.status);
  if (params.category) qs.set("category", params.category);
  const query = qs.toString() ? `?${qs.toString()}` : "";
  return request<PaginatedResult<AdminInquiryListItem>>(
    "GET",
    `/admin/inquiries/${query}`,
    undefined,
    true
  );
}

/** POST /api/v1/admin/inquiries/{id}/reply/ — 관리자 답변 작성 */
export async function adminReplyInquiry(inquiryId: number, body: string): Promise<InquiryReply> {
  return request<InquiryReply>(
    "POST",
    `/admin/inquiries/${inquiryId}/reply/`,
    { body },
    true
  );
}

export interface AdminOrderListItem {
  id: number;
  owner_email: string;
  sample_name: string | null;
  status: PromotionOrderStatus;
  status_display: string;
  admin_note: string;
  created_at: string;
  updated_at: string;
}

/** GET /api/v1/admin/orders/?status= — {count, next, previous, results} */
export async function adminListOrders(
  params: { page?: number; status?: PromotionOrderStatus } = {}
): Promise<PaginatedResult<AdminOrderListItem>> {
  const qs = new URLSearchParams();
  if (params.page) qs.set("page", String(params.page));
  if (params.status) qs.set("status", params.status);
  const query = qs.toString() ? `?${qs.toString()}` : "";
  return request<PaginatedResult<AdminOrderListItem>>(
    "GET",
    `/admin/orders/${query}`,
    undefined,
    true
  );
}

/** PATCH /api/v1/admin/orders/{id}/status/ — 주문 상태 변경 + 메모 */
export async function adminUpdateOrderStatus(
  orderId: number,
  payload: {
    status: PromotionOrderStatus;
    admin_note?: string;
    tracking_number?: string;
    carrier?: string;
    note?: string;
  }
): Promise<unknown> {
  return request<unknown>("PATCH", `/admin/orders/${orderId}/status/`, payload, true);
}

export interface AdminConsentLogItem {
  id: number;
  customer_name_masked: string;
  owner_email: string | null;
  scope: string;
  subject: string; // 'customer_self' | 'planner_attested'
  subject_display: string;
  purpose: string;
  doc_version: string;
  agreed_at: string;
  ip: string | null;
  revoked_at: string | null;
  revoke_ip: string | null;
}

/** GET /api/v1/admin/consent-logs/ — 동의 로그 (READ-ONLY, PII 마스킹) */
export async function adminListConsentLogs(
  params: { page?: number } = {}
): Promise<PaginatedResult<AdminConsentLogItem>> {
  const qs = new URLSearchParams();
  if (params.page) qs.set("page", String(params.page));
  const query = qs.toString() ? `?${qs.toString()}` : "";
  return request<PaginatedResult<AdminConsentLogItem>>(
    "GET",
    `/admin/consent-logs/${query}`,
    undefined,
    true
  );
}

// ════════════════════════════════════════════════════════════════════════════
// 증권 검토 작업 — 전자 PDF 접수 → 초안 확인 → 확정
// ════════════════════════════════════════════════════════════════════════════

export type InsuranceImportStatus =
  | "queued"
  | "extracting"
  | "validating"
  | "review_required"
  | "confirmed"
  | "failed"
  | "canceled"
  | "superseded";

export type ReviewState =
  | "review_ready"
  | "needs_review"
  | "no_evidence"
  | "unmatched"
  | "invalid"
  | "manual";

export type CoverageResolution = "assigned" | "unmatched" | "intentionally_excluded";

export interface InsuranceImportConfig {
  review_workflow_enabled: boolean;
  accepted_input: "digital_pdf";
  max_file_bytes: number;
}

export interface SourceReview {
  required: boolean;
  image_only_page_count: number;
  image_only_pages: number[];
  quarantined_line_count: number;
  quarantined_pages: number[];
  analysis_signal_quarantined_line_count: number;
  analysis_signal_quarantined_pages: number[];
  pages_requiring_manual_source_review: number[];
  requires_manual_coverage_entry: boolean;
  guidance: string;
}

export interface InsuranceImportConfirmationRequirements {
  planner_confirmed_source_match: { required: true };
  planner_confirmed_unread_pages: { required: boolean };
}

export interface InsuranceImportListItem {
  job_id: string;
  customer_id: number;
  status: InsuranceImportStatus;
  intent: "add" | "replace";
  portfolio_type: 1 | 2;
  safe_display_name: string;
  page_count: number | null;
  draft_version: number;
  error_code: string;
  target_insurance_id: number | null;
  target_insurance_version: number | null;
  source_review: SourceReview;
  confirmation_requirements: InsuranceImportConfirmationRequirements;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export type InsuranceImportJob = InsuranceImportListItem;

export interface DraftEvidence<T> {
  value: T | null;
  state: ReviewState;
  evidence_line_ids: string[];
  review_reason_codes: string[];
}

export interface InsuranceDraftPolicy {
  carrier_name: DraftEvidence<string>;
  company_code: number | null;
  insurance_type: DraftEvidence<"life" | "loss">;
  product_name: DraftEvidence<string>;
  contract_date: DraftEvidence<string>;
  expiry_date: DraftEvidence<string>;
  monthly_premium: DraftEvidence<number>;
}

export interface InsuranceDraftCoverageRow {
  row_id: string;
  raw_name: string | null;
  assurance_amount: number | null;
  premium: number | null;
  is_renewal: boolean | null;
  renewal_period: number | null;
  payment_period: number | null;
  payment_period_unit: "years" | "age" | "lifetime" | null;
  warranty_period: number | null;
  warranty_period_unit: "years" | "age" | "lifetime" | null;
  disposition: CoverageResolution;
  standard_category: string | null;
  standard_subcategory: string | null;
  standard_detail_name: string | null;
  exclusion_reason: string | null;
  duplicate_of_row_id: string | null;
  source_candidate_ids: string[];
  evidence_line_ids: string[];
  state: ReviewState;
  review_reason_codes: string[];
}

export interface StandardCoverageOption {
  category: string;
  subcategory: string;
  detail_name: string;
}

export interface ValidationIssue {
  code: string;
  state: ReviewState;
  scope: "policy" | "coverage" | "document";
  row_id: string | null;
  field: string | null;
}

export interface InsuranceImportDraft {
  job_id: string;
  customer_id: number;
  status: InsuranceImportStatus;
  draft_version: number;
  target_insurance_id: number | null;
  target_insurance_version: number | null;
  policy: InsuranceDraftPolicy;
  coverages: InsuranceDraftCoverageRow[];
  validation: { unresolved_count: number; issues: ValidationIssue[] };
  source_review: SourceReview;
  confirmation_requirements: InsuranceImportConfirmationRequirements;
  standard_coverages: { version: string; items: StandardCoverageOption[] };
}

export interface DraftCoverageAddAction {
  action: "add";
  raw_name: string;
  assurance_amount: number;
  premium: number | null;
  is_renewal: boolean;
  renewal_period?: number | null;
  payment_period?: number | null;
  payment_period_unit?: "years" | "age" | "lifetime" | null;
  warranty_period?: number | null;
  warranty_period_unit?: "years" | "age" | "lifetime" | null;
  standard_category: string;
  standard_subcategory: string;
  standard_detail_name: string;
}

export interface DraftCoverageExistingRowAction {
  row_id: string;
  action: "edit" | "assign" | "exclude" | "duplicate" | "undo_exclude" | "confirm";
  field?: string;
  value?: unknown;
  standard_category?: string;
  standard_subcategory?: string;
  standard_detail_name?: string;
  reason?: string;
  target_row_id?: string;
}

export interface DraftPatchPayload {
  draft_version: number;
  policy_changes?: Array<{ field: string; value: unknown }>;
  coverage_actions?: Array<DraftCoverageAddAction | DraftCoverageExistingRowAction>;
}

export interface ConfirmPayload {
  draft_version: number;
  target_insurance_version?: number | null;
  planner_confirmed_source_match: true;
  planner_confirmed_unread_pages?: boolean;
}

export interface SourceUrlResponse {
  url: string;
  expires_in: number;
}

export interface InsuranceImportCreateResponse {
  job_id: string;
  status: InsuranceImportStatus;
}

export interface InsuranceImportConfirmResponse {
  job_id: string;
  status: "confirmed";
  insurance_id: number;
  insurance_version: number;
  confirmed_coverage_count: number;
}

export interface InsuranceImportCancelResponse {
  job_id: string;
  status: "canceled";
}

export interface CreateInsuranceImportOptions {
  intent?: "add" | "replace";
  portfolioType?: 1 | 2;
  targetInsuranceId?: number;
  duplicateResolutionToken?: string;
  idempotencyKey: string;
}

async function parseResponseData(res: Response): Promise<Record<string, unknown>> {
  try {
    return (await res.json()) as Record<string, unknown>;
  } catch {
    return {};
  }
}

function responseError(res: Response, data: Record<string, unknown>): ApiError {
  const code = (data.code as string) ?? (data.error as string) ?? String(res.status);
  const creditBody: CreditExhaustedBody | undefined =
    res.status === 402 && code === "credit_exhausted"
      ? {
          kind: data.kind as string | undefined,
          membership: data.membership as string | undefined,
          limit: data.limit as number | null | undefined,
          used: data.used as number | undefined,
        }
      : undefined;
  handleUnauthorized(res.status);
  return new ApiError(
    res.status,
    code,
    extractErrorDetail(data, res.statusText),
    creditBody,
    data.reason as string | undefined,
    data
  );
}

export async function createInsuranceImport(
  customerId: number,
  file: File,
  options: CreateInsuranceImportOptions
): Promise<InsuranceImportCreateResponse> {
  const headers: Record<string, string> = { "Idempotency-Key": options.idempotencyKey };
  const tok = tokenStore.get();
  if (tok) headers.Authorization = `Token ${tok}`;
  const body = new FormData();
  body.append("file", file);
  body.append("intent", options.intent ?? "add");
  body.append("portfolio_type", String(options.portfolioType ?? 1));
  if (options.targetInsuranceId !== undefined) {
    body.append("target_insurance_id", String(options.targetInsuranceId));
  }
  if (options.duplicateResolutionToken) {
    body.append("duplicate_resolution_token", options.duplicateResolutionToken);
  }
  const res = await fetch(`${API_BASE}/customers/${customerId}/insurance-imports/`, {
    method: "POST",
    headers,
    body,
  });
  const data = await parseResponseData(res);
  if (!res.ok) throw responseError(res, data);
  return data as unknown as InsuranceImportCreateResponse;
}

let insuranceImportConfigCache:
  | { expiresAt: number; promise: Promise<InsuranceImportConfig> }
  | undefined;

export function getInsuranceImportConfig(): Promise<InsuranceImportConfig> {
  const now = Date.now();
  if (insuranceImportConfigCache && insuranceImportConfigCache.expiresAt > now) {
    return insuranceImportConfigCache.promise;
  }
  const promise = request<InsuranceImportConfig>(
    "GET",
    "/insurance-imports/config/",
    undefined,
    true
  ).catch((error) => {
    insuranceImportConfigCache = undefined;
    throw error;
  });
  insuranceImportConfigCache = { expiresAt: now + 60_000, promise };
  return promise;
}

export function listInsuranceImports(customerId: number): Promise<PaginatedResult<InsuranceImportListItem>> {
  return request("GET", `/customers/${customerId}/insurance-imports/`, undefined, true);
}

export function getInsuranceImport(jobId: string): Promise<InsuranceImportJob> {
  return request("GET", `/insurance-imports/${jobId}/`, undefined, true);
}

export function getInsuranceImportDraft(jobId: string): Promise<InsuranceImportDraft> {
  return request("GET", `/insurance-imports/${jobId}/draft/`, undefined, true);
}

export function patchInsuranceImportDraft(
  jobId: string,
  payload: DraftPatchPayload,
  idempotencyKey: string
): Promise<InsuranceImportDraft> {
  return request("PATCH", `/insurance-imports/${jobId}/draft/`, payload, true, {
    "Idempotency-Key": idempotencyKey,
  });
}

export function confirmInsuranceImport(
  jobId: string,
  payload: ConfirmPayload,
  idempotencyKey: string
): Promise<InsuranceImportConfirmResponse> {
  return request("POST", `/insurance-imports/${jobId}/confirm/`, payload, true, {
    "Idempotency-Key": idempotencyKey,
  });
}

export function cancelInsuranceImport(
  jobId: string,
  idempotencyKey: string
): Promise<InsuranceImportCancelResponse> {
  return request("POST", `/insurance-imports/${jobId}/cancel/`, {}, true, {
    "Idempotency-Key": idempotencyKey,
  });
}

export function getInsuranceImportSourceUrl(jobId: string): Promise<SourceUrlResponse> {
  return request("GET", `/insurance-imports/${jobId}/source-url/`, undefined, true);
}

// ════════════════════════════════════════════════════════════════════════════
// 과거 즉시 등록 경로 — 서버 스위치가 꺼져 있을 때만 사용
// ════════════════════════════════════════════════════════════════════════════

export interface OcrUploadResponse {
  code: string;
  parsing_method: string;
  created_cases: number;
  insurance: unknown;
}

/**
 * POST /api/v1/customers/<customerId>/insurances/ocr/
 * multipart/form-data: file=PDF
 * 412 CONSENT_OVERSEAS_REQUIRED → 국외이전 동의 필요
 */
export async function uploadInsuranceOcr(
  customerId: number,
  file: File,
  portfolioType: number = 1
): Promise<OcrUploadResponse> {
  const tok = tokenStore.get();
  const headers: Record<string, string> = {};
  if (tok) headers["Authorization"] = `Token ${tok}`;

  const formData = new FormData();
  formData.append("file", file);
  if (portfolioType !== 1) formData.append("portfolio_type", String(portfolioType));

  const res = await fetch(
    `${API_BASE}/customers/${customerId}/insurances/ocr/`,
    { method: "POST", headers, body: formData }
  );

  let data: Record<string, unknown> = {};
  try {
    data = await res.json();
  } catch {
    // empty body
  }

  if (!res.ok) {
    const code =
      (data["code"] as string) ??
      (data["error"] as string) ??
      String(res.status);
    const detail = extractErrorDetail(data, res.statusText);
    handleUnauthorized(res.status);
    throw new ApiError(res.status, code, detail, undefined, data["reason"] as string | undefined);
  }

  return data as unknown as OcrUploadResponse;
}

// ════════════════════════════════════════════════════════════════════════════
// 동의 고지문 단일 소스 — GET /api/v1/consent-texts/ (공개, 화면 렌더용)
// ════════════════════════════════════════════════════════════════════════════

export interface ConsentText {
  title: string;
  body: string[];
  retention: string;
}

export interface ConsentTextsResponse {
  version: string;
  texts: Record<string, ConsentText>;
}

/** 최신 동의 고지문. 실패 시 화면은 로컬 v2 폴백으로 렌더한다(옛 문구는 절대 안 씀). */
export async function getConsentTexts(): Promise<ConsentTextsResponse> {
  return request<ConsentTextsResponse>("GET", "/consent-texts/");
}

// ════════════════════════════════════════════════════════════════════════════
// 동의 로그 생성 — 국외이전 동의 (customers.ConsentLogViewSet)
// ════════════════════════════════════════════════════════════════════════════

export interface ConsentLogCreatePayload {
  scope: string;
  purpose?: string;
  doc_version?: string;
}

export interface ConsentLogCreateResponse {
  id: number;
  scope: string;
  agreed_at: string;
}

/**
 * POST /api/v1/customers/<customerId>/consents/
 * 설계사가 기록한 동의 메모(subject=planner_attested, 서버강제). consent_overseas_at 동기화 없음.
 */
export async function createConsentLog(
  customerId: number,
  payload: ConsentLogCreatePayload
): Promise<ConsentLogCreateResponse> {
  return request<ConsentLogCreateResponse>(
    "POST",
    `/customers/${customerId}/consents/`,
    payload,
    true
  );
}

// ════════════════════════════════════════════════════════════════════════════
// P3c — 고객 본인 국외이전 동의 (설계사가 링크 생성 → 고객 본인이 /c/<token>에서 동의)
// ════════════════════════════════════════════════════════════════════════════

export interface ConsentRequestResponse {
  token: string;
  consent_url: string;
  already_consented: boolean;
}

/** POST /api/v1/customers/<id>/consent-requests/ — 설계사가 동의 요청 링크 생성(인증).
 *  scopes 미지정 시 BE 기본=국외이전(OCR 동선 호환). */
export async function createConsentRequest(
  customerId: number,
  scopes?: string[]
): Promise<ConsentRequestResponse> {
  return request<ConsentRequestResponse>(
    "POST",
    `/customers/${customerId}/consent-requests/`,
    scopes ? { scopes } : undefined,
    true
  );
}

export interface ConsentItem {
  scope: string;
  title: string;
  required: boolean;
  already: boolean;
  revocable: boolean; // 살아있는 동의가 있어 철회 가능한 항목
  lines: string[];
  notice: string;
}

export interface ConsentDisclosure {
  customer: { name_masked: string };
  planner: { affiliation: string };
  items: ConsentItem[];
  all_required_done: boolean;
  disclaimer: string;
}

/** GET /api/v1/c/<token>/ — 고객 본인이 보는 동의 고지(공개, 비인증) */
export async function getConsentDisclosure(token: string): Promise<ConsentDisclosure> {
  const res = await fetch(`${API_BASE}/c/${encodeURIComponent(token)}/`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new ApiError(res.status, (data as { code?: string }).code ?? "ERROR",
      (data as { detail?: string }).detail ?? "링크를 열 수 없어요.");
  }
  return data as ConsentDisclosure;
}

/** POST /api/v1/c/<token>/ — 동의 scope 배열 제출 + 철회 scope 배열(공개, 비인증) */
export async function submitConsent(
  token: string,
  agreed: string[],
  revoked: string[] = []
): Promise<{ results: { scope: string; consented: boolean }[]; all_required_done: boolean }> {
  const res = await fetch(`${API_BASE}/c/${encodeURIComponent(token)}/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(revoked.length ? { agreed, revoked } : { agreed }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new ApiError(res.status, (data as { code?: string }).code ?? "ERROR",
      (data as { detail?: string }).detail ?? "동의 처리에 실패했어요.");
  }
  return data as { results: { scope: string; consented: boolean }[]; all_required_done: boolean };
}

// ════════════════════════════════════════════════════════════════════════════
// 미팅 예약(Calendly식) — 미팅/예약링크 + 공개 예약 페이지(영업 시간 기반 자동 슬롯)
// ════════════════════════════════════════════════════════════════════════════

export type MeetingMethod = "in_person" | "phone" | "video";

export type MeetingStatus = "pending" | "confirmed" | "canceled" | "declined";

export interface Meeting {
  id: number;
  customer: number | null;
  customer_name: string;
  slot: number | null;
  start_at: string;
  duration_min: number;
  method: MeetingMethod;
  method_display: string;
  location_detail: string;
  customer_note: string;
  status: MeetingStatus;
  status_display: string;
  created_at: string;
}

// 설계사 주간 업무시간(반복). 이 시간 안에서 빈 시간을 고객에게 자동 노출.
export interface WorkHour {
  id: number;
  weekday: number;      // 0=월 … 6=일
  start_time: string;   // "HH:MM[:SS]" (KST 벽시계)
  end_time: string;
  created_at: string;
}

export interface BookingRequestResponse {
  token: string;
  booking_url: string;
  message: string;
}

export interface PublicBookingInfo {
  customer: { name_masked: string };
  planner: { affiliation: string; name: string };
  methods: { key: MeetingMethod; label: string }[];
  duration_min: number;
  slots: { start_at: string; duration_min: number }[];
  disclaimer: string;
}

/** GET /api/v1/meetings/ — 내 미팅 목록(인증) */
export async function listMeetings(upcoming = false): Promise<PaginatedResult<Meeting>> {
  const q = upcoming ? "?upcoming=true" : "";
  return request<PaginatedResult<Meeting>>("GET", `/meetings/${q}`, undefined, true);
}

/** POST /api/v1/meetings/<id>/cancel/ — 미팅 취소(인증) */
export async function cancelMeeting(id: number): Promise<Meeting> {
  return request<Meeting>("POST", `/meetings/${id}/cancel/`, undefined, true);
}

/** GET /api/v1/meetings/?status=pending — 수락 대기 중인 예약 신청(인증) */
export async function listPendingMeetings(): Promise<PaginatedResult<Meeting>> {
  return request<PaginatedResult<Meeting>>("GET", "/meetings/?status=pending", undefined, true);
}

/** POST /api/v1/meetings/<id>/accept/ — 예약 신청 수락(확정 + 캘린더 등록) */
export async function acceptMeeting(id: number): Promise<Meeting> {
  return request<Meeting>("POST", `/meetings/${id}/accept/`, undefined, true);
}

/** POST /api/v1/meetings/<id>/decline/ — 예약 신청 거절(그 시간 다시 비움) */
export async function declineMeeting(id: number): Promise<Meeting> {
  return request<Meeting>("POST", `/meetings/${id}/decline/`, undefined, true);
}

// ── 업무시간(WorkHour) — 빈 시간 자동 노출의 기준 ──────────────────────────
/** GET /api/v1/work-hours/ — 내 주간 업무시간(인증) */
export async function listWorkHours(): Promise<PaginatedResult<WorkHour>> {
  return request<PaginatedResult<WorkHour>>("GET", "/work-hours/", undefined, true);
}

/** POST /api/v1/work-hours/ — 업무시간 추가(인증). start/end는 "HH:mm" 벽시계 */
export async function createWorkHour(payload: {
  weekday: number;
  start_time: string;
  end_time: string;
}): Promise<WorkHour> {
  return request<WorkHour>("POST", "/work-hours/", payload, true);
}

/** DELETE /api/v1/work-hours/<id>/ — 업무시간 삭제(인증) */
export async function deleteWorkHour(id: number): Promise<void> {
  await requestVoid("DELETE", `/work-hours/${id}/`, true);
}

// ── 개인 일정(schedule) — 일정/할일/고정 차단 ──────────────────────────────
export type ScheduleKind = "event" | "todo" | "block";
/** 사용자 5분류(색/범례) — kind(동작)와 직교 (PM 06.24) */
export type ScheduleCategory = "meeting" | "anniversary" | "renewal" | "task" | "etc";

export interface ScheduleItem {
  id: number;
  kind: ScheduleKind;
  category: ScheduleCategory;
  anniversary_md: string;             // "MM-DD" — 생일·기념일 매년 반복(빈값=미사용)
  title: string;
  memo: string;
  customer: number | null;
  customer_name: string | null;
  start_at: string | null;   // event/todo/단건 block (ISO, UTC 저장 → KST 표시)
  end_at: string | null;
  all_day: boolean;
  is_done: boolean;          // todo 완료
  done_at: string | null;
  recur_weekday: number | null;       // 0=월 … 6=일 (반복 차단)
  recur_start_time: string | null;    // "HH:MM:SS" — ★ new Date()에 넣지 말 것(slice(0,5))
  recur_end_time: string | null;
  created_at: string;
  updated_at: string;
}

export interface ScheduleItemPayload {
  kind: ScheduleKind;
  category?: ScheduleCategory;
  anniversary_md?: string;
  title: string;
  memo?: string;
  customer?: number | null;
  start_at?: string | null;
  end_at?: string | null;
  all_day?: boolean;
  recur_weekday?: number | null;
  recur_start_time?: string | null;   // "HH:mm" 전송(벽시계 — 변환 금지)
  recur_end_time?: string | null;
}

/** GET /api/v1/schedule-items/?month=YYYY-MM&kind= — 내 일정(인증). 반복차단은 항상 포함 */
export async function listScheduleItems(
  params?: { month?: string; kind?: ScheduleKind }
): Promise<PaginatedResult<ScheduleItem>> {
  const q = new URLSearchParams();
  if (params?.month) q.set("month", params.month);
  if (params?.kind) q.set("kind", params.kind);
  const qs = q.toString() ? `?${q.toString()}` : "";
  return request<PaginatedResult<ScheduleItem>>("GET", `/schedule-items/${qs}`, undefined, true);
}

/** POST /api/v1/schedule-items/ — 일정/할일/차단 추가(인증) */
export async function createScheduleItem(payload: ScheduleItemPayload): Promise<ScheduleItem> {
  return request<ScheduleItem>("POST", "/schedule-items/", payload, true);
}

/** PATCH /api/v1/schedule-items/<id>/ — 수정(인증) */
export async function updateScheduleItem(
  id: number, payload: Partial<ScheduleItemPayload>
): Promise<ScheduleItem> {
  return request<ScheduleItem>("PATCH", `/schedule-items/${id}/`, payload, true);
}

/** DELETE /api/v1/schedule-items/<id>/ — 삭제(인증) */
export async function deleteScheduleItem(id: number): Promise<void> {
  await requestVoid("DELETE", `/schedule-items/${id}/`, true);
}

/** POST /api/v1/schedule-items/<id>/toggle_done/ — 할일 완료 토글(인증) */
export async function toggleScheduleDone(id: number): Promise<ScheduleItem> {
  return request<ScheduleItem>("POST", `/schedule-items/${id}/toggle_done/`, undefined, true);
}

/** POST /api/v1/customers/<id>/booking-requests/ — 예약 링크 생성(인증) */
export async function createBookingRequest(customerId: number): Promise<BookingRequestResponse> {
  return request<BookingRequestResponse>(
    "POST", `/customers/${customerId}/booking-requests/`, undefined, true);
}

/** GET /api/v1/b/<token>/ — 고객이 보는 예약 페이지(공개, 비인증) */
export async function getBookingInfo(token: string): Promise<PublicBookingInfo> {
  const res = await fetch(`${API_BASE}/b/${encodeURIComponent(token)}/`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new ApiError(res.status, (data as { code?: string }).code ?? "ERROR",
      (data as { detail?: string }).detail ?? "예약 페이지를 열 수 없어요.");
  }
  return data as PublicBookingInfo;
}

/** POST /api/v1/b/<token>/ — 고객이 시간 신청(공개, 비인증). 409=그 시간이 마감/충돌 */
export async function submitBooking(
  token: string,
  payload: { start_at: string; method: MeetingMethod; note?: string }
): Promise<{ requested: boolean; status: MeetingStatus; start_at: string; method: MeetingMethod }> {
  const res = await fetch(`${API_BASE}/b/${encodeURIComponent(token)}/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new ApiError(res.status, (data as { code?: string }).code ?? "ERROR",
      (data as { detail?: string }).detail ?? "신청에 실패했어요.");
  }
  return data as { requested: boolean; status: MeetingStatus; start_at: string; method: MeetingMethod };
}

// ════════════════════════════════════════════════════════════════════════════
// 대시보드 월별 목표 — 수동 설정(목표) + 실적(계산). GET/PATCH /api/v1/dashboard/
// ════════════════════════════════════════════════════════════════════════════

/** 전월 대비 증감 — 백엔드 계산(스펙 §5). pct=null이면 비교 불가(전월 0). */
export interface DeltaInfo {
  pct: number | null;
  dir: "up" | "down" | "flat";
}

export interface DashboardSummary {
  year_month: string;
  target_meetings: number;
  target_premium: number;
  income_multiplier: number;   // 예상 월급 배율(기본 10)
  expected_income: number;     // = actual_premium × income_multiplier (계산값)
  actual_meetings: number;
  actual_premium: number;
  actual_new_customers: number;
  // 전월 대비 증감(%) — KPI 카드 배지용. 구 백엔드 호환 위해 옵셔널.
  deltas?: {
    new_customers: DeltaInfo;
    meetings: DeltaInfo;
    premium: DeltaInfo;
  };
}

/** GET /api/v1/dashboard/?month=YYYY-MM (기본 현재월) — 목표+실적(인증) */
export async function getDashboard(month?: string): Promise<DashboardSummary> {
  const q = month ? `?month=${encodeURIComponent(month)}` : "";
  return request<DashboardSummary>("GET", `/dashboard/${q}`, undefined, true);
}

/** PATCH /api/v1/dashboard/ — 목표 갱신(인증). 음수는 400 */
export async function updateDashboardGoal(
  payload: { target_meetings?: number; target_premium?: number; income_multiplier?: number },
  month?: string
): Promise<DashboardSummary> {
  const q = month ? `?month=${encodeURIComponent(month)}` : "";
  return request<DashboardSummary>("PATCH", `/dashboard/${q}`, payload, true);
}

// ─── Dashboard insights (홈 차트 — 막대추이·퍼널·유지현황 도넛) ──────────────

export interface MonthlyTrendPoint {
  ym: string;            // "YYYY-MM"
  premium: number;
  new_customers: number;
  meetings: number;
  target_premium?: number | null;  // 해당 월 MonthlyGoal.target_premium; 미설정이면 null
}

/** 보유계약 유지현황(도넛) — churn 판정 재사용 버킷. */
export interface PortfolioBreakdown {
  at_risk: number;       // 환수 위험
  watch: number;         // 주의(13/25회차 전, 위험 아님)
  stable: number;        // 유지 안정(25회차+)
  unknown: number;       // 회차 미입력
}

/** 계약 유지율(추정) — rate=null 이면 평가 모수 부족 */
export interface RetentionStat {
  rate: number | null;   // %
  reached: number;       // N년 평가 가능 모수
  survived: number;      // N년 유지
}
export interface RetentionYears {
  y1: RetentionStat;
  y2: RetentionStat;
  y3: RetentionStat;
  has_cancellation_data: boolean;   // false면 유지율 미계산(해지 입력 전 — 100% 오해 방지)
}

export interface DashboardInsights {
  monthly_trend: MonthlyTrendPoint[];           // 최근 N개월(기본 12)
  funnel: Record<SalesStage, number>;           // 영업 4단계 카운트
  portfolio: PortfolioBreakdown;
  retention: RetentionYears;                    // 1/2/3년 유지율(추정)
}

/** GET /api/v1/dashboard/insights/ — 홈 차트 집계(인증, owner 전용)
 *  opts.months: 3 | 6 | 12 | 24 (기본 12 = BE 기본값)
 */
export async function getDashboardInsights(opts?: { months?: number }): Promise<DashboardInsights> {
  const qs = opts?.months ? `?months=${opts.months}` : "";
  return request<DashboardInsights>("GET", `/dashboard/insights/${qs}`, undefined, true);
}

// ════════════════════════════════════════════════════════════════════════════
// 공유뷰 — 고객 공개 링크 (NoAuth, GET /api/v1/s/<token>/)
// ════════════════════════════════════════════════════════════════════════════

/** 공유뷰 담보 한 칸 (사실만 — 공개 공유는 neutral, 판정 라벨 없음) */
export interface ShareCoverageDetail {
  detail_id: number;
  name: string;
  held_amount: number | null;
  status: string;
  baseline?: unknown | null;
}
export interface ShareSubCategory {
  sub_category_id: number;
  name: string;
  details: ShareCoverageDetail[];
}
export interface ShareCategory {
  category_id: number;
  name: string;
  insurance_type: number;
  sub_categories: ShareSubCategory[];
}

/** 마스킹된 고객 (PII 최소) */
export interface ShareCustomer {
  name_masked: string;
  gender: number | null;
  birth_year: number | null;
}

/** 납입/보험료 합계 (사실) */
export interface ShareSummary {
  monthly_premiums: number | null;
  total_premiums: number | null;
  [key: string]: number | null;
}

export interface ShareSnapshotPayload {
  customer: ShareCustomer;
  mode: "neutral" | "graded";
  summary: ShareSummary;
  tree: ShareCategory[];
  disclaimer: string;
}

export interface ShareLiveActions {
  booking_url?: string;
  planner_contact: string | null;
}

/** Gate OFF에서 과거 Customer 토큰에만 반환되는 평면 응답. */
export interface LegacyShareViewResponse extends ShareSnapshotPayload {
  booking_url?: string;
  planner_contact: string | null;
}

/** Gate ON과 v2 스냅샷 토큰에 반환되는 불변 본문 + 실시간 행동 응답. */
export interface ShareViewV2Response {
  snapshot: ShareSnapshotPayload;
  actions: ShareLiveActions;
}

/** GET /api/v1/s/<token>/ 원본 응답. 전환 기간에는 두 형태가 모두 유효하다. */
export type ShareViewResponse = LegacyShareViewResponse | ShareViewV2Response;

/** 화면은 호환 처리를 마친 이 한 형태만 사용한다. */
export interface NormalizedShareViewResponse {
  snapshot: ShareSnapshotPayload;
  actions: {
    booking_url: string | null;
    planner_contact: string | null;
  };
}

function isRecordValue(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNullableNumber(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isFinite(value));
}

function isShareCoverageDetail(value: unknown): value is ShareCoverageDetail {
  if (!isRecordValue(value)) return false;
  return (
    Number.isInteger(value.detail_id) &&
    typeof value.name === "string" &&
    isNullableNumber(value.held_amount) &&
    typeof value.status === "string"
  );
}

function isShareSubCategory(value: unknown): value is ShareSubCategory {
  if (!isRecordValue(value)) return false;
  return (
    Number.isInteger(value.sub_category_id) &&
    typeof value.name === "string" &&
    Array.isArray(value.details) &&
    value.details.every(isShareCoverageDetail)
  );
}

function isShareCategory(value: unknown): value is ShareCategory {
  if (!isRecordValue(value)) return false;
  return (
    Number.isInteger(value.category_id) &&
    typeof value.name === "string" &&
    Number.isInteger(value.insurance_type) &&
    Array.isArray(value.sub_categories) &&
    value.sub_categories.every(isShareSubCategory)
  );
}

/** 저장된 공개 본문을 렌더하기 전에 모든 사용 필드를 확인한다. */
export function isShareSnapshotPayload(value: unknown): value is ShareSnapshotPayload {
  if (!isRecordValue(value)) return false;
  const customer = value.customer;
  const summary = value.summary;
  if (!isRecordValue(customer) || !isRecordValue(summary)) return false;
  return (
    typeof customer.name_masked === "string" &&
    isNullableNumber(customer.gender) &&
    isNullableNumber(customer.birth_year) &&
    (value.mode === "neutral" || value.mode === "graded") &&
    Object.values(summary).every(isNullableNumber) &&
    "monthly_premiums" in summary &&
    "total_premiums" in summary &&
    Array.isArray(value.tree) &&
    value.tree.every(isShareCategory) &&
    typeof value.disclaimer === "string"
  );
}

function normalizedLiveValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

/**
 * Gate 전환 중인 공개 공유 응답을 한 번만 정규화한다.
 * v2 snapshot은 그대로 유지하고 live action을 섞거나 변경하지 않는다.
 */
export function normalizeShareViewResponse(
  response: ShareViewResponse
): NormalizedShareViewResponse {
  if (!isRecordValue(response)) {
    throw new ApiError(502, "INVALID_SHARE_RESPONSE", "공유 내용을 다시 불러와 주세요.");
  }

  if ("snapshot" in response) {
    if (!isShareSnapshotPayload(response.snapshot)) {
      throw new ApiError(502, "INVALID_SHARE_RESPONSE", "공유 내용을 다시 불러와 주세요.");
    }
    const actions = isRecordValue(response.actions) ? response.actions : {};
    return {
      snapshot: response.snapshot,
      actions: {
        booking_url: normalizedLiveValue(actions.booking_url),
        planner_contact: normalizedLiveValue(actions.planner_contact),
      },
    };
  }

  const { booking_url, planner_contact, ...snapshot } = response;
  if (!isShareSnapshotPayload(snapshot)) {
    throw new ApiError(502, "INVALID_SHARE_RESPONSE", "공유 내용을 다시 불러와 주세요.");
  }
  return {
    snapshot,
    actions: {
      booking_url: normalizedLiveValue(booking_url),
      planner_contact: normalizedLiveValue(planner_contact),
    },
  };
}

/**
 * GET /api/v1/s/<token>/
 * 인증 불필요 — 고객이 공유 링크로 접근.
 * BE가 share_view 이벤트를 적재(별도 호출 불필요).
 * 만료/존재 없음 → 404
 */
export async function getShareView(token: string): Promise<ShareViewResponse> {
  const res = await fetch(`${API_BASE}/s/${token}/`, {
    method: "GET",
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
  });

  let data: Record<string, unknown> = {};
  try {
    data = await res.json();
  } catch {
    // empty body
  }

  if (!res.ok) {
    const code =
      (data["code"] as string) ??
      (data["error"] as string) ??
      String(res.status);
    const detail = extractErrorDetail(data, res.statusText);
    throw new ApiError(res.status, code, detail);
  }

  return data as unknown as ShareViewResponse;
}

// ════════════════════════════════════════════════════════════════════════════
// 비교 분석(나란히 정리) — GET/POST /api/v1/customers/<id>/compare/
// 2026-07-09 재정의: 인파는 KEEP/SWITCH 판정을 산출하지 않는다(응답에 verdict 키 없음).
// 정직성 레드라인:
//  - publishable 은 BE 권위. FE 는 절대 true 로 위조하지 않는다.
//  - guide_enabled=false 면 guide_draft 를 표시하지 않는다(가짜 데이터 금지).
//  - disclaimer 는 응답 값 그대로 노출(면책 생략 불가).
// ════════════════════════════════════════════════════════════════════════════

export interface CompareRow {
  coverage: string;
  current_amount: number | null;
  proposed_amount: number | null;
  delta: number | null;
}

export interface CompareSide {
  monthly_premiums: number | null;
  total_premiums: number | null;
  monthly_renewal_premium: number | null;
  monthly_non_renewal_premium: number | null;
  monthly_earned_premium: number | null;
  total_renewal_premium: number | null;
  total_non_renewal_premium: number | null;
  total_earned_premium: number | null;
  insurances: InsuranceFee[];
}

/** 확인해야 할 사항(중립 사실, 설계사 내부면 전용) — 판정 아님. amount=null 이면 정성 항목. */
export interface SwitchWarning {
  type: "cancellation_loss" | "exemption_reset" | "rate_change" | string;
  label: string;
  detail: string;
  amount: number | null;
}

export interface CompareResponse {
  mode: "neutral" | "graded";
  /** A안(왼쪽) 집계 — side_a_ids 로 고른 세트, 미지정 시 보유(하위호환) */
  current: CompareSide;
  /** B안(오른쪽) 집계 — side_b_ids 로 고른 세트, 미지정 시 제안(하위호환) */
  proposed: CompareSide;
  rows: CompareRow[];
  /**
   * 확인해야 할 사항(중립 사실 — 해지환급 손실 추정·면책 리셋·이율 변동). ★ 판정 아님.
   * 2026-07-09: 인파는 KEEP/SWITCH 판정을 만들지 않는다(BE 응답에 verdict 키 자체가 없음).
   * 설계사 내부 전용 — 고객 공유뷰에는 BE가 절대 전송하지 않음(누수 회귀 테스트로 강제).
   */
  switch_warnings: SwitchWarning[];
  guide_draft: string | null;
  guide_enabled: boolean;
  /** 항상 false — BE 권위. FE 절대 override 불가 */
  publishable: false;
  publish_blocked_reason: string;
  disclaimer: string;
}

/**
 * GET/POST /api/v1/customers/<id>/compare/ — A/B 두 세트를 나란히 정리(중립 시각화, 판정 없음).
 * sideAIds/sideBIds(신규): 고객 소유 보험 임의 두 집합(제안 vs 제안·증권 vs 증권도 가능).
 * currentIds/proposedIds(하위호환): sideAIds/sideBIds 없을 때만 적용(보유/제안 분리 유지).
 */
export async function compareCustomer(
  id: number,
  opts?: {
    currentIds?: number[];
    proposedIds?: number[];
    sideAIds?: number[];
    sideBIds?: number[];
  }
): Promise<CompareResponse> {
  if (
    !opts ||
    (opts.currentIds === undefined &&
      opts.proposedIds === undefined &&
      opts.sideAIds === undefined &&
      opts.sideBIds === undefined)
  ) {
    return request<CompareResponse>("GET", `/customers/${id}/compare/`, undefined, true);
  }
  const body: Record<string, number[]> = {};
  if (opts.sideAIds !== undefined) body.side_a_ids = opts.sideAIds;
  if (opts.sideBIds !== undefined) body.side_b_ids = opts.sideBIds;
  if (opts.currentIds !== undefined) body.current_ids = opts.currentIds;
  if (opts.proposedIds !== undefined) body.proposed_ids = opts.proposedIds;
  return request<CompareResponse>("POST", `/customers/${id}/compare/`, body, true);
}

/** POST /api/v1/customers/<id>/compare/ — 발행 요청(publishable=false 라 항상 차단됨) */
export async function publishCompare(id: number): Promise<CompareResponse> {
  return request<CompareResponse>("POST", `/customers/${id}/compare/`, undefined, true);
}

// ════════════════════════════════════════════════════════════════════════════
// 수기 보험 등록(보유/제안) — OCR 폴백 + 제안 입력. /customers/<id>/insurances/manual/
// ════════════════════════════════════════════════════════════════════════════

export type ManualInsuranceReviewStatus =
  | "legacy_review_required"
  | "draft"
  | "confirmed"
  | "excluded"
  | "superseded";

export interface ManualInsuranceItem {
  id: number;
  name: string | null;
  insurance_type: number;        // 1 생명 / 2 손해
  portfolio_type: number;        // 1 보유 / 2 제안
  monthly_premiums: number | null;
  contract_date: string | null;
  expiry_date: string | null;
  contractor_name: string | null;   // 계약자
  insured_name: string | null;      // 피보험자
  is_same_insured: boolean | null;  // 계약자=피보험자
  payment_status: number | null;
  is_cancelled: boolean;
  cancelled_at: string | null;
  created_at: string;
  monthly_renewal_premium?: number | null;
  monthly_non_renewal_premium?: number | null;
  monthly_earned_premium?: number | null;
  payment_period_type?: number | null;
  payment_period?: number | null;
  warranty_period_type?: number | null;
  warranty_period?: number | null;
  review_status: ManualInsuranceReviewStatus;
  analysis_included: boolean;
  data_version: number;
  confirmation_source: "manual_entry" | "legacy_review" | "import" | "" | string;
  confirmed_at: string | null;
  review_exclusion_reason: string;
}

export interface ManualInsuranceWritePayload {
  name?: string;
  insurance_type: 1 | 2;
  portfolio_type: 1 | 2;        // 1 보유 / 2 제안 (필수)
  monthly_premiums?: number;
  contract_date?: string;        // YYYY-MM-DD
  expiry_date?: string;
  contractor_name?: string;
  insured_name?: string;
}

export interface ManualInsurancePatchPayload {
  data_version: number;
  name?: string | null;
  insurance_type?: 1 | 2;
  portfolio_type?: 1 | 2;
  monthly_premiums?: number | null;
  contract_date?: string | null;
  expiry_date?: string | null;
  contractor_name?: string | null;
  insured_name?: string | null;
  is_same_insured?: boolean | null;
}

export type ManualCoveragePeriodUnit = "years" | "age" | "lifetime";

export interface ManualCoverageItem {
  id: number;
  raw_name: string;
  assurance_amount: number | null;
  premium: number | null;
  is_renewal: boolean | null;
  renewal_period: number | null;
  payment_period: number | null;
  payment_period_unit: ManualCoveragePeriodUnit | null;
  warranty_period: number | null;
  warranty_period_unit: ManualCoveragePeriodUnit | null;
  standard_category: string | null;
  standard_subcategory: string | null;
  standard_detail_name: string | null;
  standard_detail_id: number | null;
  mapping_source: "global" | "planner_override" | "manual" | string;
  review_status: "needs_review" | "confirmed";
  source_page: number | null;
  source_line_start: number | null;
  source_line_end: number | null;
  source_candidate_ids: string[];
  evidence_line_ids: string[];
  review_reason: string[];
  confirmed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ManualInsuranceReviewBundle {
  insurance_id: number;
  insurance: ManualInsuranceItem;
  data_version: number;
  review_status: ManualInsuranceReviewStatus;
  analysis_included: boolean;
  confirmation_source: ManualInsuranceItem["confirmation_source"];
  confirmation_requirements: {
    planner_confirmed_contents: { required: true };
  };
  standard_coverages: { version: string; items: StandardCoverageOption[] };
  coverages: ManualCoverageItem[];
}

export interface ManualCoverageCreatePayload {
  data_version: number;
  raw_name: string;
  assurance_amount: number | null;
  premium: number | null;
  is_renewal: boolean | null;
  renewal_period?: number | null;
  payment_period?: number | null;
  payment_period_unit?: ManualCoveragePeriodUnit | null;
  warranty_period?: number | null;
  warranty_period_unit?: ManualCoveragePeriodUnit | null;
  standard_category: string;
  standard_subcategory: string;
  standard_detail_name: string;
}

export type ManualCoveragePatchPayload =
  Partial<Omit<ManualCoverageCreatePayload, "data_version">> & { data_version: number };

export type ManualCoverageMutationResponse = ManualCoverageItem & { data_version: number };

export interface ManualCoverageDeleteResponse {
  insurance_id: number;
  deleted_coverage_id: number;
  data_version: number;
}

export interface ManualInsuranceConfirmPayload {
  data_version: number;
  planner_confirmed_contents: true;
}

export interface ManualInsuranceConfirmResponse {
  insurance_id: number;
  review_status: "confirmed";
  analysis_included: true;
  data_version: number;
  confirmation_source: "manual_entry" | "legacy_review";
  confirmed_at: string;
}

export interface ManualInsuranceExcludePayload {
  data_version: number;
  reason: string;
}

export interface ManualInsuranceExcludeResponse {
  insurance_id: number;
  review_status: "excluded";
  analysis_included: false;
  data_version: number;
  exclusion_reason: string;
}

/** GET /api/v1/customers/<id>/insurances/manual/ — 고객의 보험 목록(보유+제안, 카드용) */
export async function listManualInsurances(
  customerId: number,
  page?: number
): Promise<PaginatedResult<ManualInsuranceItem>> {
  const query = page === undefined ? "" : `?page=${page}`;
  return request<PaginatedResult<ManualInsuranceItem>>(
    "GET", `/customers/${customerId}/insurances/manual/${query}`, undefined, true);
}

/** 모든 보험 페이지를 최대 100페이지까지 읽는다. */
export async function listAllManualInsurances(customerId: number): Promise<ManualInsuranceItem[]> {
  const all: ManualInsuranceItem[] = [];
  let page = 1;
  for (let index = 0; index < 100; index += 1) {
    const result = await listManualInsurances(customerId, page === 1 ? undefined : page);
    all.push(...result.results);
    if (!result.next) break;
    if (index === 99) {
      throw new Error("보험 목록 100페이지를 모두 불러왔어요. 목록 범위를 확인해 주세요.");
    }
    page += 1;
  }
  return all;
}

/** 수기 보험 등록 — OCR 불가(스캔/이미지/키없음) 폴백 + 갈아타기 제안 입력. */
export async function createManualInsurance(
  customerId: number,
  payload: ManualInsuranceWritePayload
): Promise<ManualInsuranceItem> {
  return request<ManualInsuranceItem>(
    "POST", `/customers/${customerId}/insurances/manual/`, payload, true);
}

export function getManualInsuranceReview(
  customerId: number,
  insuranceId: number
): Promise<ManualInsuranceReviewBundle> {
  return request(
    "GET",
    `/customers/${customerId}/insurances/manual/${insuranceId}/coverages/`,
    undefined,
    true
  );
}

export function patchManualInsurance(
  customerId: number,
  insuranceId: number,
  payload: ManualInsurancePatchPayload
): Promise<ManualInsuranceItem> {
  return request(
    "PATCH",
    `/customers/${customerId}/insurances/manual/${insuranceId}/`,
    payload,
    true
  );
}

export function createManualCoverage(
  customerId: number,
  insuranceId: number,
  payload: ManualCoverageCreatePayload
): Promise<ManualCoverageMutationResponse> {
  return request(
    "POST",
    `/customers/${customerId}/insurances/manual/${insuranceId}/coverages/`,
    payload,
    true
  );
}

export function patchManualCoverage(
  customerId: number,
  insuranceId: number,
  coverageId: number,
  payload: ManualCoveragePatchPayload
): Promise<ManualCoverageMutationResponse> {
  return request(
    "PATCH",
    `/customers/${customerId}/insurances/manual/${insuranceId}/coverages/${coverageId}/`,
    payload,
    true
  );
}

export function deleteManualCoverage(
  customerId: number,
  insuranceId: number,
  coverageId: number,
  dataVersion: number
): Promise<ManualCoverageDeleteResponse> {
  return request(
    "DELETE",
    `/customers/${customerId}/insurances/manual/${insuranceId}/coverages/${coverageId}/`,
    { data_version: dataVersion },
    true
  );
}

export function confirmManualInsurance(
  customerId: number,
  insuranceId: number,
  payload: ManualInsuranceConfirmPayload,
  idempotencyKey: string
): Promise<ManualInsuranceConfirmResponse> {
  return request(
    "POST",
    `/customers/${customerId}/insurances/manual/${insuranceId}/confirm/`,
    payload,
    true,
    { "Idempotency-Key": idempotencyKey }
  );
}

export function excludeManualInsurance(
  customerId: number,
  insuranceId: number,
  payload: ManualInsuranceExcludePayload
): Promise<ManualInsuranceExcludeResponse> {
  return request(
    "POST",
    `/customers/${customerId}/insurances/manual/${insuranceId}/exclude/`,
    payload,
    true
  );
}

// ════════════════════════════════════════════════════════════════════════════
// 고객 공유 링크 발급 — POST /api/v1/customers/<id>/share/ (북극성 분석→공유 동선)
// ════════════════════════════════════════════════════════════════════════════

export interface ShareLinkResponse {
  customer_id: number;
  snapshot_id: number;
  share_token: string;
  share_expires_at: string;
  share_url: string; // "/s/<token>" — origin 붙여 완성
}

/** 공유 토큰 발급(rotate) — 보장 한눈표 공유뷰(/s/<token>) 링크. §97 비교안내서 아님. */
export async function createShareLink(customerId: number): Promise<ShareLinkResponse> {
  const token = tokenStore.get();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Token ${token}`;
  const res = await fetch(`${API_BASE}/customers/${customerId}/share/`, {
    method: "POST",
    headers,
  });
  let data: Record<string, unknown> = {};
  try {
    data = await res.json();
  } catch {
    // empty body
  }
  if (res.status !== 201) {
    if (res.ok) {
      throw new ApiError(
        502,
        "INVALID_SHARE_CREATE_RESPONSE",
        "공유 내용을 다시 만들어 주세요."
      );
    }
    const code =
      (data.error as string) ?? (data.code as string) ?? String(res.status);
    if (res.status === 401) handleUnauthorized(res.status);
    throw new ApiError(
      res.status,
      code,
      extractErrorDetail(data, res.statusText),
      undefined,
      undefined,
      data
    );
  }
  if (
    data.customer_id !== customerId ||
    !Number.isInteger(data.snapshot_id) ||
    (data.snapshot_id as number) < 1 ||
    typeof data.share_token !== "string" ||
    !data.share_token ||
    typeof data.share_expires_at !== "string" ||
    !data.share_expires_at ||
    Number.isNaN(Date.parse(data.share_expires_at)) ||
    typeof data.share_url !== "string" ||
    data.share_url !== `/s/${data.share_token}`
  ) {
    throw new ApiError(
      502,
      "INVALID_SHARE_CREATE_RESPONSE",
      "공유 내용을 다시 만들어 주세요."
    );
  }
  return data as unknown as ShareLinkResponse;
}

// ════════════════════════════════════════════════════════════════════════════
// 공유 기록 — GET /api/v1/customers/<id>/share-snapshots/[/<snap_id>/]
// 공유 링크를 만든 순간 고객에게 보여준 화면을 그대로 남긴 기록(설계사 내부 전용).
// 목록은 경량(payload 없음), 상세는 그때 그 화면(payload)을 포함한다.
// ════════════════════════════════════════════════════════════════════════════

export interface ShareSnapshotListItem {
  id: number;
  link_status: ShareSnapshotLifecycle;
  captured_at: string;
  payload_version: string;
  link_expires_at: string | null;
  revoked_at: string | null;
  revoked_reason: string;
  first_viewed_at: string | null;
  retention_expires_at: string;
  insurance_count: number;
  consent_overseas: boolean;
  consent_doc_version: string;
  dict_version: string;
}

export type ShareSnapshotLifecycle =
  | "active"
  | "revoked"
  | "expired"
  | "history_only";

export interface ShareSnapshotDetail extends ShareSnapshotListItem {
  consent_scopes: string[];
  payload: unknown;
}

/** GET /api/v1/customers/<id>/share-snapshots/ — 공유 기록 목록(최신순, 경량). */
export async function listShareSnapshots(
  customerId: number
): Promise<ShareSnapshotListItem[]> {
  return request<ShareSnapshotListItem[]>(
    "GET", `/customers/${customerId}/share-snapshots/`, undefined, true);
}

/** GET /api/v1/customers/<id>/share-snapshots/<snap_id>/ — 그때 보여드린 화면(상세). */
export async function getShareSnapshot(
  customerId: number,
  snapId: number
): Promise<ShareSnapshotDetail> {
  return request<ShareSnapshotDetail>(
    "GET", `/customers/${customerId}/share-snapshots/${snapId}/`, undefined, true);
}

export interface ShareSnapshotRevokeResponse {
  id: number;
  status: "revoked";
}

/** 사용 중인 v2 공유 링크를 회수한다. 기록 자체는 보존된다. */
export async function revokeShareSnapshot(
  customerId: number,
  snapId: number
): Promise<ShareSnapshotRevokeResponse> {
  return request<ShareSnapshotRevokeResponse>(
    "POST",
    `/customers/${customerId}/share-snapshots/${snapId}/revoke/`,
    undefined,
    true
  );
}

// ════════════════════════════════════════════════════════════════════════════
// 환수 레이더(A/S) — GET /api/v1/churn-radar/  ·  PATCH /api/v1/insurances/<id>/churn/
// ★ 보유 정책만 / owner 전용 / 수기입력 추정. 정확액은 보험사·회사 전산 권위.
// ════════════════════════════════════════════════════════════════════════════

export type PersistencyStage = "unknown" | "pre_13" | "pre_25" | "safe";

export interface ChurnRadarItem {
  insurance_id: number;
  data_version: number;
  customer_id: number;
  customer_name: string;
  insurance_name: string | null;
  current_payment_period: number | null;
  /** 1=정상 2=연체 3=납입중단 */
  payment_status: number | null;
  next_payment_date: string | null; // YYYY-MM-DD
  expected_recovery_amount: number | null;
  persistency_stage: PersistencyStage;
  is_at_risk: boolean;
  risk_reason: string;
  is_cancelled: boolean;
  cancelled_at: string | null;       // YYYY-MM-DD — 유지율 계산용
}

export interface ChurnRadarResponse {
  risk_count: number;
  expected_recovery_total: number;
  items: ChurnRadarItem[];
  disclaimer: string;
}

export interface ChurnInputPayload {
  data_version: number;
  current_payment_period?: number | null;
  payment_status?: number | null;
  next_payment_date?: string | null; // YYYY-MM-DD
  expected_recovery_amount?: number | null;
  is_cancelled?: boolean;
  cancelled_at?: string | null;      // YYYY-MM-DD
}

/** GET /api/v1/churn-radar/ — 환수 위험 집계 + 보유정책 리스트 */
export async function getChurnRadar(): Promise<ChurnRadarResponse> {
  return request<ChurnRadarResponse>("GET", "/churn-radar/", undefined, true);
}

/** PATCH /api/v1/insurances/<id>/churn/ — 환수 4개 필드 수기 저장 */
export async function updateInsuranceChurn(
  insuranceId: number,
  payload: ChurnInputPayload,
): Promise<ChurnRadarItem> {
  return request<ChurnRadarItem>("PATCH", `/insurances/${insuranceId}/churn/`, payload, true);
}

// ════════════════════════════════════════════════════════════════════════════
// 고객 이력 — GET /api/v1/customers/<id>/history/
// ════════════════════════════════════════════════════════════════════════════

export interface HistoryEvent {
  type: string;
  label: string;
  at: string; // ISO 8601
  meta: Record<string, unknown>;
}

export interface CustomerHistoryResponse {
  events: HistoryEvent[];
}

/** GET /api/v1/customers/<id>/history/ */
export async function getCustomerHistory(id: number): Promise<CustomerHistoryResponse> {
  return request<CustomerHistoryResponse>("GET", `/customers/${id}/history/`, undefined, true);
}

// ════════════════════════════════════════════════════════════════════════════
// 기준선 프리셋 적용 — POST /api/v1/planner-baselines/apply-preset/
// 준법 통제: preset_origin='v0_starter' 는 출처 미확정 → 경고 모달 확인 후만 적용
// ════════════════════════════════════════════════════════════════════════════

export interface ApplyPresetPayload {
  product_group: number;
}

export interface ApplyPresetResponse {
  created: number;
  preset_origin: "v0_starter";
  note: string;
}

/** POST /api/v1/planner-baselines/apply-preset/ */
export async function applyBaselinePreset(
  product_group: number
): Promise<ApplyPresetResponse> {
  return request<ApplyPresetResponse>(
    "POST",
    "/planner-baselines/apply-preset/",
    { product_group } satisfies ApplyPresetPayload,
    true
  );
}

/** 공유뷰 이벤트 종류 */
export type ShareEventType =
  | "clipboard_copy"
  | "cta_click"
  | "share_view"
  | "callback_request";

export interface ShareEventResponse {
  event_type: ShareEventType;
  recorded: boolean;
  notification?: "created" | "already_notified";
}

/**
 * POST /api/v1/s/<token>/event/
 * 인증 불필요. 클립보드 복사 등 이벤트 적재.
 */
export async function postShareEvent(
  token: string,
  event_type: ShareEventType
): Promise<ShareEventResponse> {
  const response = await fetch(`${API_BASE}/s/${token}/event/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event_type }),
  });
  let data: Record<string, unknown> = {};
  try {
    data = await response.json();
  } catch {
    // 응답 본문이 비어 있어도 상태 코드를 최종 권위로 사용한다.
  }
  if (!response.ok) {
    const code = (data["code"] as string | undefined) ?? String(response.status);
    const detail = extractErrorDetail(data, response.statusText);
    throw new ApiError(response.status, code, detail, undefined, undefined, data);
  }
  return data as unknown as ShareEventResponse;
}

// ════════════════════════════════════════════════════════════════════════════
// 설계사 영입 · 정착 관리
// ════════════════════════════════════════════════════════════════════════════

export type RecruitingStage =
  | "new"
  | "contact"
  | "conversation"
  | "preparing"
  | "team_join"
  | "recontact"
  | "ended";

export type RecruitingCareerBand =
  | "under_1"
  | "1_3"
  | "3_5"
  | "5_10"
  | "10_plus";

export type RecruitingContactWindow =
  | "morning"
  | "afternoon"
  | "evening"
  | "anytime";

export type RecruitingNextAction =
  | "call"
  | "message"
  | "meeting"
  | "follow_up"
  | "none";

export type RecruitingSelectionStatus = "active" | "replaced";
export type SettlementState = "active" | "support_needed" | "stopped";

export type SettlementBlocker =
  | "customer_prospecting"
  | "consultation_prep"
  | "product_understanding"
  | "work_tools"
  | "time_management"
  | "organization_adjustment"
  | "personal"
  | "none";

export type SettlementNextSupport =
  | "consultation_prep"
  | "training"
  | "activity_plan"
  | "tool_help"
  | "leader_meeting"
  | "schedule_only"
  | "close";

export interface RecruitingTemplate {
  id: number;
  code: string;
  kind: "headline" | "support" | "faq" | "share";
  title: string;
  body: string;
  sort_order: number;
}

export interface RecruitingPlanner {
  display_name: string;
  affiliation: string;
  title: string;
  profile_image: string | null;
}

export interface RecruitingCandidateCampaign {
  id: number;
  name: string;
  channel: "relationship";
}

export interface RecruitingJoinedAgent {
  id: number;
  display_name: string;
  profile_image: string | null;
}

export interface RecruitingActiveCandidate {
  id: number;
  campaign_id: number | null;
  campaign: RecruitingCandidateCampaign | null;
  name: string;
  phone: string;
  career_band: RecruitingCareerBand;
  current_affiliation: string;
  region: string;
  contact_window: RecruitingContactWindow;
  stage: RecruitingStage;
  selection_status: "active";
  next_action: RecruitingNextAction | "";
  next_action_at: string | null;
  last_contacted_at: string | null;
  ended_at: string | null;
  joined_at: string | null;
  joined_agent: RecruitingJoinedAgent | null;
  created_at: string;
  updated_at: string;
  duplicate_contact: boolean;
  closed_message: string;
}

export interface RecruitingReplacedCandidate {
  id: number;
  stage: "ended";
  selection_status: "replaced";
  closed_message: string;
  created_at: string;
  updated_at: string;
}

export type RecruitingCandidate =
  | RecruitingActiveCandidate
  | RecruitingReplacedCandidate;

export interface RecruitingSummary {
  stage_counts: Record<RecruitingStage, number>;
  due_today: number;
  overdue: number;
  joined_this_month: number;
  settlement_due: number;
}

export interface RecruitingCandidateQuery {
  page?: number;
  q?: string;
  stage?: RecruitingStage;
  campaign?: number;
  source?: RecruitingCandidateCampaign["channel"];
  career_band?: RecruitingCareerBand;
  due?: boolean | "overdue";
}

export interface RecruitingCandidatePatch {
  next_action?: RecruitingNextAction | "";
  next_action_at?: string | null;
}

export interface RecruitingCandidateTransition {
  stage: RecruitingStage;
  next_action?: RecruitingNextAction | "";
  next_action_at?: string | null;
}

export interface RecruitingTeamInvite {
  join_path: string;
  expires_at: string;
}

export interface RecruitingPage {
  planner: RecruitingPlanner;
  headline_template_id: number | null;
  headline: RecruitingTemplate | null;
  templates: RecruitingTemplate[];
  activity_region: string;
  is_published: boolean;
}

export interface RecruitingPagePatch {
  headline_template_id?: number | null;
  template_ids?: number[];
  activity_region?: string;
  is_published?: boolean;
}

export interface RecruitingCampaign {
  id: number;
  name: string;
  channel: "relationship";
  is_active: boolean;
  public_path: string;
  public_url: string;
  visits: number;
  applications: number;
  joins: number;
  created_at: string;
}

export interface RecruitingSettlement {
  id: number;
  candidate_id: number;
  joined_agent_name: string;
  week: 1 | 4 | 8 | 13;
  due_on: string;
  state: SettlementState;
  blocker: SettlementBlocker | "";
  next_support: SettlementNextSupport | "";
  completed_at: string | null;
}

export interface RecruitingSettlementUpdate {
  id: number;
  week: 1 | 4 | 8 | 13;
  state: SettlementState;
  blocker: SettlementBlocker | "";
  next_support: SettlementNextSupport | "";
  completed_at: string | null;
}

export interface RecruitingSettlementComplete {
  state: SettlementState;
  blocker?: SettlementBlocker | "";
  next_support?: SettlementNextSupport | "";
}

export interface TeamRecruitingMember {
  user_id: number;
  display_name: string;
  active_recruiting: number;
  joined_this_month: number;
  settlement_due: number;
}

export interface TeamRecruitingSummary {
  members: TeamRecruitingMember[];
  not_shared_count: number;
  team_totals: {
    active_recruiting: number;
    joined_this_month: number;
    settlement_due: number;
  };
}

export interface PublicRecruitingPage {
  planner: RecruitingPlanner;
  headline: RecruitingTemplate | null;
  support: RecruitingTemplate[];
  faq: RecruitingTemplate[];
  activity_region: string;
  consent_version: string;
  consent_text: string;
}

export interface PublicRecruitingApplication {
  name: string;
  phone: string;
  career_band: RecruitingCareerBand;
  current_affiliation?: string;
  region: string;
  contact_window: RecruitingContactWindow;
  submission_key: string;
  prior_manage_token?: string | null;
  consent_version: string;
  agreed: boolean;
}

export interface PublicRecruitingSubmitted {
  submitted: true;
  message: string;
  manage_url: string;
}

export interface PublicRecruitingChoiceRequired {
  submitted: false;
  choice_required: true;
  current_leader: Pick<RecruitingPlanner, "display_name" | "affiliation">;
  new_leader: Pick<RecruitingPlanner, "display_name" | "affiliation">;
  choice_token: string;
}

export interface PublicRecruitingVerificationRequired {
  submitted: false;
  verification_required: true;
  message: string;
}

export type PublicRecruitingApplicationResult =
  | PublicRecruitingSubmitted
  | PublicRecruitingChoiceRequired
  | PublicRecruitingVerificationRequired;

export type PublicRecruitingManage =
  | {
      contact_stopped: true;
      submitted_at: string;
      support_reference: string;
      message: string;
    }
  | {
      contact_stopped: false;
      stage: RecruitingStage;
      submitted_at: string;
      support_reference: string;
      leader: RecruitingPlanner;
    };

export interface RecruitingJoinInfo {
  display_name: string;
  affiliation: string;
  title: string;
  profile_image: string | null;
  headline: string;
}

export interface RecruitingJoinAcceptResult {
  stage: RecruitingStage;
  joined_now: boolean;
  manager_promoted_now: boolean;
}

export async function getRecruitingSummary(): Promise<RecruitingSummary> {
  return request<RecruitingSummary>("GET", "/recruiting/summary/", undefined, true);
}

export async function listRecruitingCandidates(
  filters: RecruitingCandidateQuery = {},
): Promise<PaginatedResult<RecruitingCandidate>> {
  const query = new URLSearchParams();
  if (filters.page && Number.isInteger(filters.page) && filters.page > 0) {
    query.set("page", String(filters.page));
  }
  if (filters.q?.trim()) query.set("q", filters.q.trim());
  if (filters.stage) query.set("stage", filters.stage);
  if (filters.campaign !== undefined) query.set("campaign", String(filters.campaign));
  if (filters.source) query.set("source", filters.source);
  if (filters.career_band) query.set("career_band", filters.career_band);
  if (filters.due === true) query.set("due", "true");
  if (filters.due === "overdue") query.set("due", "overdue");
  const suffix = query.size ? `?${query.toString()}` : "";
  return request<PaginatedResult<RecruitingCandidate>>(
    "GET",
    `/recruiting/candidates/${suffix}`,
    undefined,
    true,
  );
}

export async function getRecruitingCandidate(id: number): Promise<RecruitingCandidate> {
  return request<RecruitingCandidate>(
    "GET",
    `/recruiting/candidates/${id}/`,
    undefined,
    true,
  );
}

export async function updateRecruitingCandidate(
  id: number,
  payload: RecruitingCandidatePatch,
): Promise<RecruitingActiveCandidate> {
  return request<RecruitingActiveCandidate>(
    "PATCH",
    `/recruiting/candidates/${id}/`,
    payload,
    true,
  );
}

export async function transitionRecruitingCandidate(
  id: number,
  payload: RecruitingCandidateTransition,
): Promise<RecruitingCandidate> {
  return request<RecruitingCandidate>(
    "POST",
    `/recruiting/candidates/${id}/transition/`,
    payload,
    true,
  );
}

export async function issueRecruitingTeamInvite(id: number): Promise<RecruitingTeamInvite> {
  return request<RecruitingTeamInvite>(
    "POST",
    `/recruiting/candidates/${id}/team-invite/`,
    undefined,
    true,
  );
}

export async function listRecruitingSettlements(): Promise<RecruitingSettlement[]> {
  return request<RecruitingSettlement[]>("GET", "/recruiting/settlements/", undefined, true);
}

export async function completeRecruitingSettlement(
  id: number,
  payload: RecruitingSettlementComplete,
): Promise<RecruitingSettlementUpdate> {
  return request<RecruitingSettlementUpdate>(
    "POST",
    `/recruiting/settlement-checks/${id}/complete/`,
    payload,
    true,
  );
}

export async function reopenRecruitingSettlement(
  id: number,
): Promise<RecruitingSettlementUpdate> {
  return request<RecruitingSettlementUpdate>(
    "POST",
    `/recruiting/settlement-checks/${id}/reopen/`,
    undefined,
    true,
  );
}

export async function getRecruitingPage(): Promise<RecruitingPage> {
  return request<RecruitingPage>("GET", "/recruiting/page/", undefined, true);
}

export async function updateRecruitingPage(
  payload: RecruitingPagePatch,
): Promise<RecruitingPage> {
  return request<RecruitingPage>("PATCH", "/recruiting/page/", payload, true);
}

export async function listRecruitingTemplates(): Promise<RecruitingTemplate[]> {
  return request<RecruitingTemplate[]>("GET", "/recruiting/templates/", undefined, true);
}

export async function getRecruitingCampaign(): Promise<RecruitingCampaign> {
  return request<RecruitingCampaign>("GET", "/recruiting/campaign/", undefined, true);
}

export async function setRecruitingCampaignActive(
  isActive: boolean,
): Promise<RecruitingCampaign> {
  return request<RecruitingCampaign>(
    "PATCH",
    "/recruiting/campaign/",
    { is_active: isActive },
    true,
  );
}

export async function reissueRecruitingCampaign(): Promise<RecruitingCampaign> {
  return request<RecruitingCampaign>(
    "PATCH",
    "/recruiting/campaign/",
    { reissue: true },
    true,
  );
}

export async function recordRecruitingCampaignCopied(): Promise<{ recorded: boolean }> {
  return request<{ recorded: boolean }>(
    "POST",
    "/recruiting/campaign/copied/",
    undefined,
    true,
  );
}

export async function getTeamRecruitingSummary(): Promise<TeamRecruitingSummary> {
  return request<TeamRecruitingSummary>("GET", "/recruiting/team-summary/", undefined, true);
}

export async function getPublicRecruitingPage(token: string): Promise<PublicRecruitingPage> {
  return request<PublicRecruitingPage>(
    "GET",
    `/r/${encodeURIComponent(token)}/`,
  );
}

export async function applyPublicRecruitingCampaign(
  token: string,
  payload: PublicRecruitingApplication,
): Promise<PublicRecruitingApplicationResult> {
  return request<PublicRecruitingApplicationResult>(
    "POST",
    `/r/${encodeURIComponent(token)}/`,
    payload,
  );
}

export async function submitPublicRecruitingLeaderChoice(
  token: string,
  choice: "keep_current" | "switch_to_new",
): Promise<PublicRecruitingSubmitted> {
  return request<PublicRecruitingSubmitted>(
    "POST",
    `/r/choice/${encodeURIComponent(token)}/`,
    { choice },
  );
}

export async function getPublicRecruitingManage(token: string): Promise<PublicRecruitingManage> {
  return request<PublicRecruitingManage>(
    "GET",
    `/r/manage/${encodeURIComponent(token)}/`,
  );
}

export async function stopPublicRecruitingManage(
  token: string,
): Promise<{ contact_stopped: true; message: string }> {
  return request<{ contact_stopped: true; message: string }>(
    "POST",
    `/r/manage/${encodeURIComponent(token)}/`,
    { action: "stop_contact" },
  );
}

export async function getRecruitingJoinInfo(token: string): Promise<RecruitingJoinInfo> {
  return request<RecruitingJoinInfo>(
    "GET",
    `/recruiting/join/${encodeURIComponent(token)}/`,
  );
}

export async function acceptRecruitingJoin(
  token: string,
  manageToken: string,
  confirmSwitch = false,
): Promise<RecruitingJoinAcceptResult> {
  return request<RecruitingJoinAcceptResult>(
    "POST",
    `/recruiting/join/${encodeURIComponent(token)}/`,
    { confirm_switch: confirmSwitch, manage_token: manageToken },
    true,
  );
}
