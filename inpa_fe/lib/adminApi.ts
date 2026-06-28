// lib/adminApi.ts
// 관리자 콘솔 전용 API 함수.
// lib/api.ts에 이미 선언된 함수(adminListUsers, adminGetStats 등)는 api.ts에서 re-export.
// 이 파일: api.ts에 없는 admin 전용 함수만 추가한다.
// 토큰: localStorage('inpa_token') — 설계사·admin 동일 키 사용 (엔드포인트로 구분).

import {
  ApiError,
  tokenStore,
  type PaginatedResult,
  type InquiryStatus,
  type InquiryDetail,
  type NoticeItem,
  type FaqItem,
  type PromotionOrderStatus,
  type PromotionOrderDetail,
} from "@/lib/api";

// ─── re-export frequently used admin functions from api.ts ──────────────────
export {
  adminListUsers,
  adminGetStats,
  adminCreateNotice,
  adminListInquiries,
  adminReplyInquiry,
  adminListOrders,
  adminUpdateOrderStatus,
  adminListConsentLogs,
  type AdminUserListItem,
  type AdminDashboardStats,
  type AdminInquiryListItem,
  type AdminOrderListItem,
  type AdminConsentLogItem,
} from "@/lib/api";

// ─── Internal fetch (mirrors api.ts request()) ──────────────────────────────

const API_BASE =
  (process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000/api/v1").replace(/\/$/, "");

async function req<T>(
  method: string,
  path: string,
  body?: unknown
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  const tok = tokenStore.get();
  if (tok) headers["Authorization"] = `Token ${tok}`;

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  let data: Record<string, unknown> = {};
  try { data = await res.json(); } catch { /* empty body */ }

  if (!res.ok) {
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

async function reqVoid(method: string, path: string, body?: unknown): Promise<void> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const tok = tokenStore.get();
  if (tok) headers["Authorization"] = `Token ${tok}`;
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let data: Record<string, unknown> = {};
    try { data = await res.json(); } catch { /* empty */ }
    const code = (data["error"] as string) ?? String(res.status);
    const detail = (data["detail"] as string) ?? res.statusText;
    throw new ApiError(res.status, code, detail);
  }
}

// ─── Admin Login ─────────────────────────────────────────────────────────────

export interface AdminLoginPayload { email: string; password: string }
export interface AdminLoginResponse {
  token: string;
  admin: { email: string; name: string };
}

/** POST /api/v1/admin/auth/login/ — is_admin=false면 403 */
export async function adminLogin(payload: AdminLoginPayload): Promise<AdminLoginResponse> {
  return req<AdminLoginResponse>("POST", "/admin/auth/login/", payload);
}

/** POST /api/v1/admin/auth/logout/ */
export async function adminLogout(): Promise<void> {
  await reqVoid("POST", "/admin/auth/logout/");
  tokenStore.remove();
}

// ─── User Detail ─────────────────────────────────────────────────────────────

export interface AdminUserDetail {
  id: number;
  email: string;
  is_active: boolean;
  date_joined: string;
  last_login: string | null;
  affiliation: string | null;
  agent_type: number | null;
  agent_type_display: string | null;
  career_years: number | null;
  license_self_declared: boolean;
  license_no: string | null;
  email_verified_at: string | null;
  onboarding_completed_at: string | null;
  is_dormant: boolean;
  dormant_at: string | null;
  will_delete_at: string | null;
  plan_code: string;
  plan_display: string;
  subscription_status: string | null;
  // 이번 달 사용량 — 4종 (ocr / ai_compare / analysis / promotion)
  usage_this_month: Record<string, number>;
  customer_count: number;
  portfolio_count: number;
  consent_logs: Array<{
    id: number;
    customer_name_masked: string;
    scope: string;
    scope_display: string;
    subject_display: string;
    agreed_at: string;
    revoked_at: string | null;
  }>;
}

/** GET /api/v1/admin/users/{id}/ — 설계사 상세 + 사용량 */
export async function adminGetUser(id: number): Promise<AdminUserDetail> {
  return req<AdminUserDetail>("GET", `/admin/users/${id}/`);
}

/** PATCH /api/v1/admin/users/{id}/subscription/ — 요금제 변경 */
export async function adminUpdateSubscription(
  userId: number,
  plan_code: string
): Promise<{ plan_code: string; plan_display: string }> {
  return req("PATCH", `/admin/users/${userId}/subscription/`, { plan_code });
}

/** POST /api/v1/admin/users/{id}/send_reset_email/ — 비밀번호 재설정 이메일 발송 */
export async function adminSendResetEmail(userId: number): Promise<{ sent: boolean }> {
  return req("POST", `/admin/users/${userId}/send_reset_email/`);
}

// ─── Inquiries ───────────────────────────────────────────────────────────────

/** GET /api/v1/admin/inquiries/{id}/ — 문의 상세 + 답변 목록 */
export async function adminGetInquiry(id: number): Promise<InquiryDetail> {
  return req<InquiryDetail>("GET", `/admin/inquiries/${id}/`);
}

/** PATCH /api/v1/admin/inquiries/{id}/status/ — 문의 상태 변경 */
export async function adminUpdateInquiryStatus(
  id: number,
  status: InquiryStatus
): Promise<{ status: InquiryStatus }> {
  return req("PATCH", `/admin/inquiries/${id}/status/`, { status });
}

// ─── Board / Reports ─────────────────────────────────────────────────────────

export type ReportStatus = "pending" | "resolved" | "dismissed";

export interface AdminReportListItem {
  id: number;
  reporter_email: string | null;
  content_type: string;
  object_id: number;
  reason: string;
  detail: string | null;
  status: ReportStatus;
  created_at: string;
}

/** GET /api/v1/admin/reports/?status= — 신고 목록 */
export async function adminListReports(
  params: { page?: number; status?: ReportStatus } = {}
): Promise<PaginatedResult<AdminReportListItem>> {
  const qs = new URLSearchParams();
  if (params.page) qs.set("page", String(params.page));
  if (params.status) qs.set("status", params.status);
  const query = qs.toString() ? `?${qs.toString()}` : "";
  return req<PaginatedResult<AdminReportListItem>>("GET", `/admin/reports/${query}`);
}

/** PATCH /api/v1/admin/reports/{id}/action/ — 신고 처리 */
export async function adminActionReport(
  id: number,
  payload: { action: "resolved" | "dismissed"; note?: string }
): Promise<AdminReportListItem> {
  return req<AdminReportListItem>("PATCH", `/admin/reports/${id}/action/`, payload);
}

// ─── Notices (admin write) ───────────────────────────────────────────────────

/** PATCH /api/v1/admin/notices/{id}/ — 공지 수정 */
export async function adminUpdateNotice(
  id: number,
  payload: Partial<{
    title: string;
    body: string;
    is_pinned: boolean;
    is_published: boolean;
    published_at: string | null;
  }>
): Promise<NoticeItem> {
  return req<NoticeItem>("PATCH", `/admin/notices/${id}/`, payload);
}

/** DELETE /api/v1/admin/notices/{id}/ — 공지 삭제(소프트) */
export async function adminDeleteNotice(id: number): Promise<void> {
  return reqVoid("DELETE", `/admin/notices/${id}/`);
}

// ─── FAQ (admin write) ────────────────────────────────────────────────────────

export interface FaqWritePayload {
  question: string;
  answer: string;
  category?: string;
  order?: number;
  is_published?: boolean;
}

/** POST /api/v1/admin/faq/ — FAQ 작성 */
export async function adminCreateFaq(payload: FaqWritePayload): Promise<FaqItem> {
  return req<FaqItem>("POST", "/admin/faq/", payload);
}

/** PATCH /api/v1/admin/faq/{id}/ — FAQ 수정 */
export async function adminUpdateFaq(id: number, payload: Partial<FaqWritePayload>): Promise<FaqItem> {
  return req<FaqItem>("PATCH", `/admin/faq/${id}/`, payload);
}

/** DELETE /api/v1/admin/faq/{id}/ */
export async function adminDeleteFaq(id: number): Promise<void> {
  return reqVoid("DELETE", `/admin/faq/${id}/`);
}

// ─── Orders Detail ────────────────────────────────────────────────────────────

/** GET /api/v1/admin/orders/{id}/ — 주문 상세 + 타임라인 */
export async function adminGetOrder(id: number): Promise<PromotionOrderDetail> {
  return req<PromotionOrderDetail>("GET", `/admin/orders/${id}/`);
}

// ─── Normalization ────────────────────────────────────────────────────────────

export interface UnmatchedLogItem {
  id: number;
  raw_name: string;
  insurer: string;
  count: number;
  sample_ctx: string | null;
  resolved: boolean;
}

export interface NormalizationDictItem {
  id: number;
  standard_name: string;
  raw_name: string;
  insurer: string;
  source: string;
  confidence: number;
  hit_count: number;
  created_at: string;
}

/** GET /api/v1/admin/normalization/unmatched/ */
export async function adminListUnmatched(
  params: { page?: number } = {}
): Promise<PaginatedResult<UnmatchedLogItem>> {
  const qs = new URLSearchParams();
  if (params.page) qs.set("page", String(params.page));
  const query = qs.toString() ? `?${qs.toString()}` : "";
  return req<PaginatedResult<UnmatchedLogItem>>("GET", `/admin/normalization/unmatched/${query}`);
}

/** POST /api/v1/admin/normalization/map/ — 매핑 등록 */
export async function adminMapNormalization(payload: {
  unmatched_id: number;
  standard_name: string;
}): Promise<NormalizationDictItem> {
  return req<NormalizationDictItem>("POST", "/admin/normalization/map/", payload);
}

/** GET /api/v1/admin/normalization/dict/ */
export async function adminListNormalizationDict(
  params: { page?: number; q?: string } = {}
): Promise<PaginatedResult<NormalizationDictItem>> {
  const qs = new URLSearchParams();
  if (params.page) qs.set("page", String(params.page));
  if (params.q) qs.set("q", params.q);
  const query = qs.toString() ? `?${qs.toString()}` : "";
  return req<PaginatedResult<NormalizationDictItem>>("GET", `/admin/normalization/dict/${query}`);
}

/** DELETE /api/v1/admin/normalization/dict/{id}/ — 오매핑 삭제 */
export async function adminDeleteNormalizationDict(id: number): Promise<void> {
  return reqVoid("DELETE", `/admin/normalization/dict/${id}/`);
}

// ─── Settings ─────────────────────────────────────────────────────────────────

export interface AdminPlan {
  code: string;
  display_name: string;
  price_krw: number;
  limit_ocr: number | null;
  limit_ai_compare: number | null;
  limit_analysis: number | null;
  limit_promotion: number | null;
  is_active: boolean;
}

/** GET /api/v1/admin/settings/plans/ */
export async function adminListPlans(): Promise<AdminPlan[]> {
  return req<AdminPlan[]>("GET", "/admin/settings/plans/");
}

/** PATCH /api/v1/admin/settings/plans/{code}/ */
export async function adminUpdatePlan(
  code: string,
  payload: Partial<AdminPlan>
): Promise<AdminPlan> {
  return req<AdminPlan>("PATCH", `/admin/settings/plans/${code}/`, payload);
}

export interface PolicyVersion {
  id: number;
  policy_type: "tos" | "pp" | "overseas";
  version: string;
  effective_at: string;
  requires_reconsent: boolean;
  created_at: string;
}

/** GET /api/v1/admin/settings/policy-versions/ */
export async function adminListPolicyVersions(): Promise<PaginatedResult<PolicyVersion>> {
  return req<PaginatedResult<PolicyVersion>>("GET", "/admin/settings/policy-versions/");
}

/** POST /api/v1/admin/settings/policy-versions/ */
export async function adminCreatePolicyVersion(
  payload: Omit<PolicyVersion, "id" | "created_at">
): Promise<PolicyVersion> {
  return req<PolicyVersion>("POST", "/admin/settings/policy-versions/", payload);
}

export interface FeatureFlags {
  FREE_TIER_UNLIMITED: boolean;
  COMPARE_AI_ENABLED: boolean;
  COMPARE_PUBLISH_ENABLED: boolean;
  ANALYZE_MEDICAL_ENABLED: boolean;
  BOOKING_ENABLED: boolean;
  OCR_VERIFY_ENABLED: boolean;
  REQUIRE_CUSTOMER_SELF_CONSENT: boolean;
  GOOGLE_OAUTH_ENABLED: boolean;
  [key: string]: boolean;
}

/**
 * GET /api/v1/admin/settings/flags/
 * 기능 플래그 현재값 읽기 전용 반환 (env 기반, runtime 변경 불가).
 * PATCH는 컴플라이언스 원칙(env 우회 차단)으로 미구현.
 */
export async function adminGetFlags(): Promise<FeatureFlags> {
  return req<FeatureFlags>("GET", "/admin/settings/flags/");
}
