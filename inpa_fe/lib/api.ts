// inpa_fe/lib/api.ts
// BE API fetch wrapper — base: /api/v1/auth/
// Token: localStorage('inpa_token')
// Error shape: { code?: string; detail?: string; error?: string; message?: string }

const API_BASE =
  (process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000/api/v1").replace(/\/$/, "");

// ─── Error class ────────────────────────────────────────────────────────────

export class ApiError extends Error {
  code: string;
  status: number;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
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
    throw new ApiError(res.status, code, detail);
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
 * GET /api/v1/auth/verify-email/?uid=...&token=...
 * Passes uid and token as query params.
 */
export async function verifyEmail(uid: string, token: string): Promise<VerifyEmailResponse> {
  return request<VerifyEmailResponse>(
    "GET",
    `/auth/verify-email/?uid=${encodeURIComponent(uid)}&token=${encodeURIComponent(token)}`
  );
}

// ─────────────────────────────────────────────────────────────────────────────

export interface LoginPayload {
  email: string;
  password: string;
}

export interface LoginProfile {
  email: string;
  onboarding_completed_at: string | null;
  agent_type: number | null;
  license_self_declared: boolean;
  membership: { name: string; is_unlimited: boolean };
}

export interface LoginResponse {
  token: string;
  onboarding_required: boolean;
  dormancy_recovered: boolean;
  profile: LoginProfile;
}

/** POST /api/v1/auth/login/ */
export async function login(payload: LoginPayload): Promise<LoginResponse> {
  return request<LoginResponse>("POST", "/auth/login/", payload);
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

export interface ProfileResponse {
  email: string;
  onboarding_completed_at: string | null;
  agent_type: number | null;
  license_self_declared: boolean;
  membership: { name: string; is_unlimited: boolean };
}

/** GET /api/v1/auth/profile/ — requires token */
export async function getProfile(): Promise<ProfileResponse> {
  return request<ProfileResponse>("GET", "/auth/profile/", undefined, true);
}

// ─── Customer types ──────────────────────────────────────────────────────────

export interface CustomerTag {
  id: number;
  label: string;
  color: string;
  created_at: string;
}

/** 목록 카드용 경량 타입 (CustomerListSerializer 대응) */
export interface CustomerListItem {
  id: number;
  name: string;
  gender: string | null;
  birth_day: string | null;          // "YYYY-MM-DD"
  mobile_phone_number: string | null;
  consent_overseas_at: string | null;
  color: string | null;
  tags: CustomerTag[];
  family_count: number;
  share_token: string | null;
  created_at: string;
}

/** 상세 타입 (CustomerSerializer 대응) */
export interface CustomerDetail extends CustomerListItem {
  job_code: string | null;
  memo: string | null;
  is_agree_term: boolean;
  share_expires_at: string | null;
  share_sent_at: string | null;
  user_view_at: string | null;
  updated_at: string;
  family_members: unknown[];
  medical_histories: unknown[];
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
  is_agree_term?: boolean;
  tag_ids?: number[];
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
