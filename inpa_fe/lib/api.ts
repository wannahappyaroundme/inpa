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
    "[인파] NEXT_PUBLIC_API_BASE 미설정 — API가 localhost를 가리킵니다. " +
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
  constructor(status: number, code: string, message: string, creditBody?: CreditExhaustedBody) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.creditBody = creditBody;
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

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  auth = false
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
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
    const detail =
      (data["detail"] as string) ??
      (data["message"] as string) ??
      res.statusText;
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
    throw new ApiError(res.status, code, detail, creditBody);
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
  affiliation: string | null;
  agent_type: number | null;
  /** 1=전속(원수사) 2=GA. null=미신고 */
  affiliation_type: number | null;
  cohort_opt_in: boolean;
  manager_share_opt_in: boolean;
  manager_email: string | null;
  managed_agents_count: number;
  license_self_declared: boolean;
  license_no: string | null;
  career_years: number | null;
  booking_msg_template: string;
  booking_location: string;
  booking_default_duration: number;
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
  affiliation_type?: number | null;
  cohort_opt_in?: boolean;
  manager_share_opt_in?: boolean;
  manager_email?: string;
  booking_msg_template?: string;
  booking_location?: string;
  booking_default_duration?: number;
  google_calendar_mask_name?: boolean;
}
export async function updateProfile(payload: ProfileUpdatePayload): Promise<ProfileResponse> {
  return request<ProfileResponse>("PATCH", "/auth/profile/", payload, true);
}

// ─── Onboarding ───────────────────────────────────────────────────────────────

export interface OnboardingAttestPayload {
  affiliation?: string;
  agent_type?: number | null;
  affiliation_type?: number | null;
  manager_email?: string;
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
  retention_y1: number | null;
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
  totals: { customer_count: number; churn_risk_count: number; share_view_count: number };
  team_funnel: Record<SalesStage, number>;
  team_retention: RetentionYears;
  roi: ManagerTeamRoi;
}
export async function getManagerDashboard(): Promise<ManagerDashboardResponse> {
  return request<ManagerDashboardResponse>("GET", "/manager/dashboard/", undefined, true);
}

// ─── 환수 위험 → 인앱 알림 동기화 (cron 아님, 홈 진입 시 호출) ───────────────────
export async function syncChurnAlerts(): Promise<{ created: number }> {
  return request<{ created: number }>("POST", "/churn-radar/sync-alerts/", {}, true);
}

// ─── 셀프진단 인바운드 (공개, 비로그인) ─────────────────────────────────────────
export interface SelfDiagnosisResult {
  customer: { name_masked: string; gender: number | null; birth_year: number | null };
  mode: string;
  summary: { monthly_premiums: number | null; total_premiums: number | null };
  tree: ShareCategory[];
  disclaimer: string;
  lead_created?: boolean;
}
/** POST /api/v1/d/<refcode>/ — multipart: file, consent_overseas, consent_share, name?, phone? */
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

/** GET /api/v1/customers/{id}/ */
export async function getCustomer(id: number): Promise<CustomerDetail> {
  return request<CustomerDetail>("GET", `/customers/${id}/`, undefined, true);
}

/** POST /api/v1/customers/ */
export async function createCustomer(payload: CustomerWritePayload): Promise<CustomerDetail> {
  return request<CustomerDetail>("POST", "/customers/", payload, true);
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
    const detail = (data["detail"] as string) ?? (data["message"] as string) ?? res.statusText;
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
    const detail = (data["detail"] as string) ?? res.statusText;
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

export interface HeatmapDetail {
  detail_id: number;
  name: string;
  held_amount: number | null;
  status: HeatmapStatus;
  baseline: HeatmapBaseline | null;
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

export interface HeatmapSummary {
  monthly_premiums: number | null;
  total_premiums: number | null;
  [key: string]: unknown;
}

export interface HeatmapResponse {
  customer_id: number;
  mode: "neutral" | "graded";
  baseline_present: boolean;
  baseline_count: number;       // graded 근거(보유한 살아있는 기준 수) — PM 06.24 명확화
  insurance_count: number;
  summary: HeatmapSummary;
  chart_list: unknown[];
  tree: HeatmapCategory[];
}

/** GET /api/v1/customers/<id>/heatmap/ — requires token */
export async function getHeatmap(customerId: number): Promise<HeatmapResponse> {
  return request<HeatmapResponse>("GET", `/customers/${customerId}/heatmap/`, undefined, true);
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
    const detail = (data["detail"] as string) ?? res.statusText;
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

// ── 1:1 문의 (Inquiry — 비공개) ─────────────────────────────────────────────

export type InquiryCategory = "feature" | "billing" | "bug" | "other";
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
  | "board_like";

export interface NotificationItem {
  id: number;
  notif_type: NotifType;
  title: string;
  body: string;
  target_date: string | null;
  customer: number | null;
  customer_name: string | null;
  calendar_event_id: number | null;
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
export async function getUnreadCount(): Promise<{ unread_count: number }> {
  return request<{ unread_count: number }>(
    "GET",
    "/notifications/unread-count/",
    undefined,
    true
  );
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
  description: string;
  limit_ocr: number | null;
  limit_ai_compare: number | null;
  limit_analysis: number | null;
  limit_promotion: number | null;
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
  owner_email: string;
  category: InquiryCategory;
  title: string;
  status: InquiryStatus;
  created_at: string;
  updated_at: string;
}

/** GET /api/v1/admin/inquiries/?status= — {count, next, previous, results} */
export async function adminListInquiries(
  params: { page?: number; status?: InquiryStatus } = {}
): Promise<PaginatedResult<AdminInquiryListItem>> {
  const qs = new URLSearchParams();
  if (params.page) qs.set("page", String(params.page));
  if (params.status) qs.set("status", params.status);
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
// 증권 OCR 업로드 — multipart POST (auth required)
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
  file: File
): Promise<OcrUploadResponse> {
  const tok = tokenStore.get();
  const headers: Record<string, string> = {};
  if (tok) headers["Authorization"] = `Token ${tok}`;

  const formData = new FormData();
  formData.append("file", file);

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
    const detail =
      (data["detail"] as string) ??
      (data["message"] as string) ??
      res.statusText;
    throw new ApiError(res.status, code, detail);
  }

  return data as unknown as OcrUploadResponse;
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

/** POST /api/v1/c/<token>/ — 동의 scope 배열 제출(공개, 비인증) */
export async function submitConsent(
  token: string,
  agreed: string[]
): Promise<{ results: { scope: string; consented: boolean }[]; all_required_done: boolean }> {
  const res = await fetch(`${API_BASE}/c/${encodeURIComponent(token)}/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agreed }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new ApiError(res.status, (data as { code?: string }).code ?? "ERROR",
      (data as { detail?: string }).detail ?? "동의 처리에 실패했어요.");
  }
  return data as { results: { scope: string; consented: boolean }[]; all_required_done: boolean };
}

// ════════════════════════════════════════════════════════════════════════════
// 미팅 예약(Calendly식) — 슬롯(설계사)/미팅/예약링크 + 공개 예약 페이지
// ════════════════════════════════════════════════════════════════════════════

export type MeetingMethod = "in_person" | "phone" | "video";
export type MeetingSlotStatus = "open" | "booked" | "canceled";

export interface MeetingSlot {
  id: number;
  start_at: string;
  duration_min: number;
  status: MeetingSlotStatus;
  created_at: string;
}

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
  status: "confirmed" | "canceled";
  created_at: string;
}

export interface BookingRequestResponse {
  token: string;
  booking_url: string;
  message: string;
}

export interface PublicBookingInfo {
  customer: { name_masked: string };
  planner: { affiliation: string; location: string };
  methods: { key: MeetingMethod; label: string }[];
  slots: { id: number; start_at: string; duration_min: number }[];
  disclaimer: string;
}

/** GET /api/v1/meeting-slots/ — 내 슬롯 목록(인증) */
export async function listMeetingSlots(
  upcoming = false
): Promise<PaginatedResult<MeetingSlot>> {
  const q = upcoming ? "?upcoming=true" : "";
  return request<PaginatedResult<MeetingSlot>>("GET", `/meeting-slots/${q}`, undefined, true);
}

/** POST /api/v1/meeting-slots/ — 슬롯 추가(인증). start_at은 ISO(+09:00) */
export async function createMeetingSlot(payload: {
  start_at: string;
  duration_min?: number;
}): Promise<MeetingSlot> {
  return request<MeetingSlot>("POST", "/meeting-slots/", payload, true);
}

/** DELETE /api/v1/meeting-slots/<id>/ — 슬롯 삭제(인증, booked면 403) */
export async function deleteMeetingSlot(id: number): Promise<void> {
  await requestVoid("DELETE", `/meeting-slots/${id}/`, true);
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

/** POST /api/v1/b/<token>/ — 고객이 슬롯 예약 제출(공개, 비인증). 409=이미 예약됨 */
export async function submitBooking(
  token: string,
  payload: { slot_id: number; method: MeetingMethod; note?: string }
): Promise<{ confirmed: boolean; start_at: string; method: MeetingMethod; location_detail: string }> {
  const res = await fetch(`${API_BASE}/b/${encodeURIComponent(token)}/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new ApiError(res.status, (data as { code?: string }).code ?? "ERROR",
      (data as { detail?: string }).detail ?? "예약에 실패했어요.");
  }
  return data as { confirmed: boolean; start_at: string; method: MeetingMethod; location_detail: string };
}

// ════════════════════════════════════════════════════════════════════════════
// 대시보드 월별 목표 — 수동 설정(목표) + 실적(계산). GET/PATCH /api/v1/dashboard/
// ════════════════════════════════════════════════════════════════════════════

export interface DashboardSummary {
  year_month: string;
  target_meetings: number;
  target_premium: number;
  income_multiplier: number;   // 예상 월급 배율(기본 10)
  expected_income: number;     // = actual_premium × income_multiplier (계산값)
  actual_meetings: number;
  actual_premium: number;
  actual_new_customers: number;
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
  baseline: unknown | null;
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

/** GET /api/v1/s/<token>/ 응답 전체 (BE 실제 형태) */
export interface ShareViewResponse {
  customer: ShareCustomer;
  mode: "neutral" | "graded";
  summary: ShareSummary;
  tree: ShareCategory[];
  disclaimer: string;
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
    const detail =
      (data["detail"] as string) ??
      (data["message"] as string) ??
      res.statusText;
    throw new ApiError(res.status, code, detail);
  }

  return data as unknown as ShareViewResponse;
}

// ════════════════════════════════════════════════════════════════════════════
// 갈아타기(비교) — GET/POST /api/v1/customers/<id>/compare/
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
}

/** 갈아타기 유의사항(설계사 내부면 전용). amount=null 이면 정성 경고. */
export interface SwitchWarning {
  type: "cancellation_loss" | "exemption_reset" | "rate_change" | string;
  label: string;
  detail: string;
  amount: number | null;
}

/** KEEP/SWITCH/NEUTRAL 판정 — ★ 설계사 내부 의사결정 근거. 고객에게 노출 금지(§97). */
export interface SwitchVerdict {
  decision: "KEEP" | "SWITCH" | "NEUTRAL";
  reason: string;
  /** 1년 기준 추정 순손익(원). 양수=이득, 음수=손해, null=계산 불가 */
  customer_net_benefit_estimate: number | null;
  disclaimer: string;
}

export interface CompareResponse {
  mode: "neutral" | "graded";
  current: CompareSide;
  proposed: CompareSide;
  rows: CompareRow[];
  /** ★ 설계사 내부 전용 — 고객 공유뷰에는 BE가 절대 전송하지 않음(누수 회귀 테스트로 강제) */
  verdict: SwitchVerdict;
  switch_warnings: SwitchWarning[];
  guide_draft: string | null;
  guide_enabled: boolean;
  /** 항상 false — BE 권위. FE 절대 override 불가 */
  publishable: false;
  publish_blocked_reason: string;
  disclaimer: string;
}

/** GET /api/v1/customers/<id>/compare/ */
export async function compareCustomer(id: number): Promise<CompareResponse> {
  return request<CompareResponse>("GET", `/customers/${id}/compare/`, undefined, true);
}

/** POST /api/v1/customers/<id>/compare/ — 발행 요청(publishable=false 라 항상 차단됨) */
export async function publishCompare(id: number): Promise<CompareResponse> {
  return request<CompareResponse>("POST", `/customers/${id}/compare/`, undefined, true);
}

// ════════════════════════════════════════════════════════════════════════════
// 수기 보험 등록(보유/제안) — OCR 폴백 + 제안 입력. /customers/<id>/insurances/manual/
// ════════════════════════════════════════════════════════════════════════════

export interface ManualInsuranceItem {
  id: number;
  name: string | null;
  insurance_type: number;        // 1 생명 / 2 손해
  portfolio_type: number;        // 1 보유 / 2 제안
  monthly_premiums: number | null;
  contract_date: string | null;
  expiry_date: string | null;
  payment_status: number | null;
  is_cancelled: boolean;
  cancelled_at: string | null;
  created_at: string;
}

export interface ManualInsuranceWritePayload {
  name?: string;
  insurance_type?: number;
  portfolio_type: number;        // 1 보유 / 2 제안 (필수)
  monthly_premiums?: number;
  contract_date?: string;        // YYYY-MM-DD
  expiry_date?: string;
}

/** 수기 보험 등록 — OCR 불가(스캔/이미지/키없음) 폴백 + 갈아타기 제안 입력. */
export async function createManualInsurance(
  customerId: number,
  payload: ManualInsuranceWritePayload
): Promise<ManualInsuranceItem> {
  return request<ManualInsuranceItem>(
    "POST", `/customers/${customerId}/insurances/manual/`, payload, true);
}

// ════════════════════════════════════════════════════════════════════════════
// 고객 공유 링크 발급 — POST /api/v1/customers/<id>/share/ (북극성 분석→공유 동선)
// ════════════════════════════════════════════════════════════════════════════

export interface ShareLinkResponse {
  customer_id: number;
  share_token: string;
  share_expires_at: string;
  share_url: string; // "/s/<token>" — origin 붙여 완성
}

/** 공유 토큰 발급(rotate) — 보장 한눈표 공유뷰(/s/<token>) 링크. §97 비교안내서 아님. */
export async function createShareLink(customerId: number): Promise<ShareLinkResponse> {
  return request<ShareLinkResponse>("POST", `/customers/${customerId}/share/`, undefined, true);
}

// ════════════════════════════════════════════════════════════════════════════
// 환수 레이더(A/S) — GET /api/v1/churn-radar/  ·  PATCH /api/v1/insurances/<id>/churn/
// ★ 보유 정책만 / owner 전용 / 수기입력 추정. 정확액은 보험사·회사 전산 권위.
// ════════════════════════════════════════════════════════════════════════════

export type PersistencyStage = "unknown" | "pre_13" | "pre_25" | "safe";

export interface ChurnRadarItem {
  insurance_id: number;
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
export type ShareEventType = "clipboard_copy" | "cta_click" | "share_view";

/**
 * POST /api/v1/s/<token>/event/
 * 인증 불필요. 클립보드 복사 등 이벤트 적재.
 */
export async function postShareEvent(
  token: string,
  event_type: ShareEventType
): Promise<void> {
  await fetch(`${API_BASE}/s/${token}/event/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event_type }),
  });
  // 이벤트 적재 실패는 무시 (non-critical)
}
