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
  type InquiryCategory,
  type FeedbackMeta,
  type NoticeItem,
  type FaqItem,
  type PromotionOrderStatus,
  type PromotionOrderDetail,
  type BlogCategory,
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

// ─── Usage Tracking (사용량 트래킹) ───────────────────────────────────────────

export interface AdminUsageUser {
  user_id: number;
  email: string;
  name: string;
  total: number;
  events: Record<string, number>; // event_type → count
}
export interface AdminUsageResponse {
  days: number;
  active_users: number;
  feature_totals: Record<string, number>; // event_type → 전체 합
  users: AdminUsageUser[]; // 사용량 내림차순(데모 @inpa.local 제외)
}

/** GET /api/v1/admin/usage/?days= — 설계사별 기능 사용량 집계(데모 제외) */
export async function adminGetUsage(days = 30): Promise<AdminUsageResponse> {
  return req<AdminUsageResponse>("GET", `/admin/usage/?days=${days}`);
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

// ─── 설계사별 고객 목록 (admin READ-ONLY, 비민감 필드만) ──────────────────────
export interface AdminCustomerRow {
  id: number;
  name: string;
  mobile_phone_number: string;
  sales_stage: string;
  sales_stage_display: string;
  status: string;
  status_display: string;
  job_name: string | null;
  insurance_count: number;
  created_at: string;
  last_contacted_at: string | null;
}
export interface AdminUserCustomersResponse {
  count: number;
  results: AdminCustomerRow[];
}
/** GET /api/v1/admin/users/{id}/customers/ — 그 설계사가 보유한 고객 목록(사실 필드만) */
export async function adminGetUserCustomers(id: number): Promise<AdminUserCustomersResponse> {
  return req<AdminUserCustomersResponse>("GET", `/admin/users/${id}/customers/`);
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
// ⚠️ admin 직렬화는 답변 작성자를 author_email 로 준다(설계사용 InquiryReply 의
//    author_name 아님). 문의 본문도 owner_email 를 포함한다.

/** 답변 (admin 직렬화 필드 그대로: id/author_email/body/created_at/updated_at). */
export interface AdminInquiryReply {
  id: number;
  author_email: string | null;
  body: string;
  created_at: string;
  updated_at: string;
}

/** 문의 상세 + 답변 목록 (admin). */
export interface AdminInquiryDetail {
  id: number;
  owner_email: string | null;   // null = 비회원(익명) 제출
  category: InquiryCategory;
  title: string;
  body: string;
  status: InquiryStatus;
  rating: number | null;        // 이용 의견 별점(1~5), 그 외 null
  meta: FeedbackMeta | null;    // 불편 신고 화면 정보(경로/브라우저/화면 크기)
  contact_email: string;        // 비회원 답변 이메일(없으면 '')
  created_at: string;
  updated_at: string;
  replies: AdminInquiryReply[];
}

/** GET /api/v1/admin/inquiries/{id}/ — 문의 상세 + 답변 목록 */
export async function adminGetInquiry(id: number): Promise<AdminInquiryDetail> {
  return req<AdminInquiryDetail>("GET", `/admin/inquiries/${id}/`);
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

/**
 * GET /api/v1/admin/notices/ — 임시저장(미게시) 포함 전체 목록.
 * 공개 listNotices()는 게시분만 반환하므로 관리자 콘솔은 이 함수를 써야
 * 방금 저장한 임시저장 공지가 목록에서 사라지지 않는다. 페이지네이션 전체 순회.
 */
export async function adminListNotices(): Promise<NoticeItem[]> {
  const all: NoticeItem[] = [];
  let page = 1;
  for (;;) {
    const res = await req<PaginatedResult<NoticeItem>>("GET", `/admin/notices/?page=${page}`);
    all.push(...res.results);
    if (!res.next) break;
    page += 1;
  }
  return all;
}

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

/**
 * GET /api/v1/admin/faq/ — 비공개(미게시) 포함 전체 목록.
 * 공개 listFaqs()는 게시분만 반환하므로 관리자 콘솔은 이 함수를 써야
 * 방금 저장한 비공개 FAQ가 목록에서 사라지지 않는다. 페이지네이션 전체 순회.
 */
export async function adminListFaqs(): Promise<FaqItem[]> {
  const all: FaqItem[] = [];
  let page = 1;
  for (;;) {
    const res = await req<PaginatedResult<FaqItem>>("GET", `/admin/faq/?page=${page}`);
    all.push(...res.results);
    if (!res.next) break;
    page += 1;
  }
  return all;
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
// ★ BE 계약이 SSOT (admin_console/serializers.py). 2026-07-09 정합 픽스:
//   - UnmatchedLog: company(코드 숫자)/occurrence — 과거 insurer/count 는 드리프트였음.
//   - 매핑 등록 payload: {unmatched_log_id, std_detail_id, confidence} — 과거
//     {unmatched_id, standard_name} 은 BE 400(동작 불능 버그).

export interface UnmatchedLogItem {
  id: number;
  raw_name: string;
  /** 보험사 코드(ocrdata index, -1=미감지) — 라벨 변환은 FE 표시층에서 */
  company: number;
  occurrence: number;
  sample_ctx: string | null;
  resolved: boolean;
  created_at: string;
  updated_at: string;
}

export interface NormalizationDictItem {
  id: number;
  std_detail: number;
  std_detail_name: string;
  raw_name: string;
  company: number;
  source: number;
  source_display: string;
  confidence: number;
  verified_by_email: string | null;
  hit_count: number;
  created_at: string;
  updated_at: string;
}

/** 표준 담보 leaf (관리자 선택기용 — [표준] 스코프만) */
export interface NormalizationLeaf {
  id: number;
  name: string;
  category_name: string;
  sub_category_name: string;
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

/** POST /api/v1/admin/normalization/map/ — 매핑 등록 (BE 계약: unmatched_log_id + std_detail_id) */
export async function adminMapNormalization(payload: {
  unmatched_log_id: number;
  std_detail_id: number;
  confidence?: number;
}): Promise<NormalizationDictItem> {
  return req<NormalizationDictItem>("POST", "/admin/normalization/map/", {
    confidence: 100,
    ...payload,
  });
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

/** GET /api/v1/admin/normalization/leaves/ — 표준 담보 leaf 목록(선택기용) */
export async function adminListNormalizationLeaves(q?: string): Promise<NormalizationLeaf[]> {
  const query = q ? `?q=${encodeURIComponent(q)}` : "";
  return req<NormalizationLeaf[]>("GET", `/admin/normalization/leaves/${query}`);
}

// ─── Coverage Flags (담보 위치 확인 요청 — 설계사 피드백 검수) ────────────────

export type CoverageFlagStatus = "open" | "accepted" | "rejected";

export interface CoverageFlagItem {
  id: number;
  company: number | null;
  raw_name_snapshot: string;
  note: string;
  status: CoverageFlagStatus;
  planner_email: string | null;
  customer_name: string | null;
  /** 신고 당시 매핑돼 있던 표준 담보명(null 가능) */
  current_mapping: string | null;
  analysis_detail_id: number | null;
  case_id: number | null;
  resolution_memo: string;
  created_at: string;
  updated_at: string;
}

export interface CoverageFlagResolveResult {
  flag: CoverageFlagItem;
  /** accept 에서만 의미: 사전 행 신규 생성 여부 */
  dict_created?: boolean;
  dict_id?: number | null;
  /** 교정된 카탈로그 연결 수(0|1) */
  relinked?: number;
  /** 부분 문자열 충돌 경고 + 골든셋 불일치 경고(차단 없음) */
  warnings?: string[];
}

/** GET /api/v1/admin/normalization/flags/?status= — 기본 open, 'all' 로 전체 */
export async function adminListCoverageFlags(
  params: { page?: number; status?: CoverageFlagStatus | "all" } = {}
): Promise<PaginatedResult<CoverageFlagItem>> {
  const qs = new URLSearchParams();
  if (params.page) qs.set("page", String(params.page));
  if (params.status) qs.set("status", params.status);
  const query = qs.toString() ? `?${qs.toString()}` : "";
  return req<PaginatedResult<CoverageFlagItem>>("GET", `/admin/normalization/flags/${query}`);
}

/** POST /api/v1/admin/normalization/flags/{id}/resolve/ — 승인(사전 반영)/반려 */
export async function adminResolveCoverageFlag(
  id: number,
  payload:
    | { action: "accept"; std_detail_id: number; raw_name?: string; memo?: string }
    | { action: "reject"; memo?: string }
): Promise<CoverageFlagResolveResult> {
  return req<CoverageFlagResolveResult>(
    "POST",
    `/admin/normalization/flags/${id}/resolve/`,
    payload
  );
}

// ─── 골든셋 정규화 정확도 기준선 (프리런치 리뷰 #18) ──────────────────────────
// 사전(NormalizationDict)의 유일한 데이터 자산 정확도를 인파 자체 큐레이션 사전
// (NORMALIZATION_V0) + 손으로 옮겨 적은 함정 앵커로 측정한다. 사실 수치만 — 판정어 없음.

export interface NormalizationAccuracyFailure {
  company: number;
  raw_name: string;
  expected: string;
  got: string | null;
}

export interface NormalizationAccuracy {
  accuracy: number;
  total: number;
  passed: number;
  anchor_passed: number;
  anchor_total: number;
  min_accuracy: number;
  /** 최대 20건 — 판정어 없이 기대/실제 표준 담보명만 */
  sample_failures: NormalizationAccuracyFailure[];
}

/** GET /api/v1/admin/normalization/accuracy/ — 정규화 사전 정확도 기준선 */
export async function adminGetNormalizationAccuracy(): Promise<NormalizationAccuracy> {
  return req<NormalizationAccuracy>("GET", "/admin/normalization/accuracy/");
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
  limit_customer: number | null;
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

// ─── Billing Mode (유료화 모드 토글) ──────────────────────────────────────────

export interface BillingMode {
  free_tier_unlimited: boolean;
}

/**
 * GET /api/v1/admin/billing/mode/
 * 현재 유료화 모드 조회. free_tier_unlimited=true → 베타 무제한, false → 유료 한도 적용.
 */
export async function getBillingMode(): Promise<BillingMode> {
  return req<BillingMode>("GET", "/admin/billing/mode/");
}

/**
 * PATCH /api/v1/admin/billing/mode/
 * 유료화 모드 전환. 모든 설계사에게 즉시 적용됨.
 */
export async function setBillingMode(free_tier_unlimited: boolean): Promise<BillingMode> {
  return req<BillingMode>("PATCH", "/admin/billing/mode/", { free_tier_unlimited });
}

// ─── Claude 호출당 비용·파싱 결과 계측 (프리런치 리뷰 #17) ───────────────────
// cost_krw 는 전부 "추정치"(토큰 × 모델 단가 × 환율 추정). 실제 청구서와 다를 수 있음(§6 정직성).

export interface ClaudeCostByAction {
  action: string;
  calls: number;
  cost_krw: number;
}
export interface ClaudeCostDailyPoint {
  date: string | null; // YYYY-MM-DD
  calls: number;
  cost_krw: number;
}
export interface ClaudeCostByCarrier {
  carrier_code: number;
  matched: number;
  unmatched: number;
  /** 미매칭 담보 건수 ÷ (매칭+미매칭) × 100, 소수 1자리 */
  unmatched_rate: number;
}
export interface AdminClaudeCostResponse {
  days: number;
  total_calls: number;
  total_cost_krw: number;
  /** 항상 true — cost_krw 가 추정치임을 FE 가 명시하라는 신호(판정어 아닌 사실 플래그) */
  cost_is_estimate: boolean;
  usd_krw_rate: number;
  /** 0건이면 null (분모 없음) */
  success_rate: number | null;
  outcome_counts: Record<string, number>;
  by_action: ClaudeCostByAction[];
  daily: ClaudeCostDailyPoint[];
  by_carrier: ClaudeCostByCarrier[];
}

/** GET /api/v1/admin/claude-cost/?days= — Claude 호출당 비용(추정)·파싱 결과 집계(데모 제외) */
export async function adminGetClaudeCost(days = 30): Promise<AdminClaudeCostResponse> {
  return req<AdminClaudeCostResponse>("GET", `/admin/claude-cost/?days=${days}`);
}

// ─── 활성화 퍼널 (프리런치 리뷰 #16) ──────────────────────────────────────

export interface ActivationFunnelStep {
  step: string;
  label: string;
  count: number;
  /** 직전 단계 대비 전환율(%), 소수 1자리. 첫 단계(signup)는 null */
  conversion_rate: number | null;
}
export interface ActivationUtmSource {
  /** utm_source 값, 없으면 'direct' */
  source: string;
  signups: number;
  activated: number;
  activation_rate: number | null;
}
export interface AdminActivationFunnelResponse {
  days: number;
  /** 활성화 판정 창(일), env ACTIVATION_WINDOW_DAYS(기본 7) */
  activation_window_days: number;
  signup_count: number;
  activated_count: number;
  activation_rate: number | null;
  steps: ActivationFunnelStep[];
  utm_sources: ActivationUtmSource[];
  /** 활성화 코호트 평균 소요일수(가입→활성화), 활성화 0명이면 null */
  avg_days_to_activation: number | null;
}

/** GET /api/v1/admin/activation-funnel/?days= — 가입→인증→첫고객→첫분석→첫공유→활성화 코호트 퍼널(데모 제외) */
export async function adminGetActivationFunnel(days = 30): Promise<AdminActivationFunnelResponse> {
  return req<AdminActivationFunnelResponse>("GET", `/admin/activation-funnel/?days=${days}`);
}

// ─── 인파 노트 (BlogPost CRUD — IsAdmin) ──────────────────────────────────────
// ⚠️ 공개 직렬화는 tags 를 배열로, 어드민은 RAW 콤마 문자열(tags) + tags_list 배열 둘 다 준다.
// 저장(create/update)은 커버 파일이 있으면 multipart, 없으면 JSON. 응답 = BlogAdmin + warnings[].

export interface BlogAdmin {
  id: number;
  title: string;
  slug: string;
  body: string;
  excerpt: string;
  cover_image: string | null;
  category: BlogCategory;
  category_label: string;
  tags: string;         // RAW 콤마 문자열(입력 편집용)
  tags_list: string[];  // 파싱된 배열(표시용)
  is_published: boolean;
  published_at: string | null;
  seo_title: string;
  seo_description: string;
  is_noindex: boolean;
  view_count: number;
  author_name: string;
  author_email: string | null;
  created_at: string;
  updated_at: string;
}

/** 게시 상태에서 저장할 때만 반환되는 비차단 카피 경고(고객 대면 문구 주의). */
export interface CopyWarning {
  field: "title" | "body" | "excerpt";
  issue: "em_dash" | "advice_word";
  match: string;
}

/** create/update 응답 = BlogAdmin 에 warnings 배열이 얹혀 온다. */
export type BlogAdminSaveResult = BlogAdmin & { warnings: CopyWarning[] };

export interface BlogWritePayload {
  title?: string;
  body?: string;
  slug?: string;
  excerpt?: string;
  category?: BlogCategory;
  tags?: string;              // 콤마 구분 문자열
  is_published?: boolean;
  seo_title?: string;
  seo_description?: string;
  is_noindex?: boolean;
  cover_image?: string | null; // null = 커버 제거(수정 시 명시 전송, JSON 경로). 파일 교체는 coverFile 인자로.
}

/** 오류 본문 → 메시지. detail/message 우선, 없으면 DRF 필드 배열({slug:["..."]})의 첫 메시지(슬러그 중복 등). */
function extractBlogDetail(data: Record<string, unknown>, statusText: string): string {
  const direct = (data["detail"] as string) ?? (data["message"] as string);
  if (direct) return direct;
  for (const v of Object.values(data)) {
    if (Array.isArray(v) && typeof v[0] === "string") return v[0];
  }
  return statusText;
}

/** 저장 요청(create/update) — 커버 파일 유무로 multipart/JSON 분기. 응답에 warnings 포함. */
async function reqBlogWrite(
  method: "POST" | "PATCH",
  path: string,
  payload: BlogWritePayload,
  coverFile?: File | null
): Promise<BlogAdminSaveResult> {
  const headers: Record<string, string> = {};
  const tok = tokenStore.get();
  if (tok) headers["Authorization"] = `Token ${tok}`;

  let body: BodyInit;
  if (coverFile) {
    // multipart — Content-Type 은 브라우저가 boundary 와 함께 설정하므로 지정하지 않는다.
    const form = new FormData();
    for (const [k, v] of Object.entries(payload)) {
      if (v === undefined || v === null) continue;
      form.append(k, typeof v === "boolean" ? String(v) : String(v));
    }
    form.append("cover_image", coverFile);
    body = form;
  } else {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(payload);
  }

  const res = await fetch(`${API_BASE}${path}`, { method, headers, body });
  let data: Record<string, unknown> = {};
  try { data = await res.json(); } catch { /* empty */ }
  if (!res.ok) {
    const code = (data["error"] as string) ?? (data["code"] as string) ?? String(res.status);
    throw new ApiError(res.status, code, extractBlogDetail(data, res.statusText));
  }
  return data as unknown as BlogAdminSaveResult;
}

/** GET /api/v1/admin/blog/?status=&category=&page= — 초안 포함 목록(page_size 20). */
export async function adminListBlogPosts(
  params: { status?: "published" | "draft"; category?: BlogCategory | string; page?: number } = {}
): Promise<PaginatedResult<BlogAdmin>> {
  const qs = new URLSearchParams();
  if (params.status) qs.set("status", params.status);
  if (params.category) qs.set("category", params.category);
  if (params.page) qs.set("page", String(params.page));
  const query = qs.toString() ? `?${qs.toString()}` : "";
  return req<PaginatedResult<BlogAdmin>>("GET", `/admin/blog/${query}`);
}

/** GET /api/v1/admin/blog/<id>/ — 상세(초안 포함). */
export async function adminGetBlogPost(id: number): Promise<BlogAdmin> {
  return req<BlogAdmin>("GET", `/admin/blog/${id}/`);
}

/** POST /api/v1/admin/blog/ — 작성. coverFile 있으면 multipart. */
export async function adminCreateBlogPost(
  payload: BlogWritePayload,
  coverFile?: File | null
): Promise<BlogAdminSaveResult> {
  return reqBlogWrite("POST", "/admin/blog/", payload, coverFile);
}

/** PATCH /api/v1/admin/blog/<id>/ — 수정. coverFile 있으면 multipart. */
export async function adminUpdateBlogPost(
  id: number,
  payload: BlogWritePayload,
  coverFile?: File | null
): Promise<BlogAdminSaveResult> {
  return reqBlogWrite("PATCH", `/admin/blog/${id}/`, payload, coverFile);
}

/** DELETE /api/v1/admin/blog/<id>/ — 소프트 삭제(공개에서만 숨김, DB 보존). */
export async function adminDeleteBlogPost(id: number): Promise<{ deleted: boolean; id: number }> {
  return req<{ deleted: boolean; id: number }>("DELETE", `/admin/blog/${id}/`);
}

/** PATCH /api/v1/admin/blog/<id>/ (커버만 multipart) — 편집 중 즉시 R2 업로드 + 미리보기 URL 확보. */
export async function uploadBlogCover(id: number, file: File): Promise<BlogAdmin> {
  const form = new FormData();
  form.append("cover_image", file);
  const headers: Record<string, string> = {};
  const tok = tokenStore.get();
  if (tok) headers["Authorization"] = `Token ${tok}`;
  const res = await fetch(`${API_BASE}/admin/blog/${id}/`, { method: "PATCH", headers, body: form });
  let data: Record<string, unknown> = {};
  try { data = await res.json(); } catch { /* empty */ }
  if (!res.ok) {
    const code = (data["error"] as string) ?? (data["code"] as string) ?? String(res.status);
    throw new ApiError(res.status, code, extractBlogDetail(data, res.statusText));
  }
  return data as unknown as BlogAdmin;
}
