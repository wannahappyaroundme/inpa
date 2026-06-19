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
