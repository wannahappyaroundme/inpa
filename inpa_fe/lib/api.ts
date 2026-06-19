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
  affiliation: string | null;
  agent_type: number | null;
  license_self_declared: boolean;
  license_no: string | null;
  career_years: number | null;
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

// ─── Onboarding ───────────────────────────────────────────────────────────────

export interface OnboardingAttestPayload {
  affiliation?: string;
  agent_type?: number | null;
  license_self_declared?: boolean;
  career_years?: number | null;
}

/** POST /api/v1/auth/onboarding/attest/ — 온보딩 완료 기록. ProfileResponse 반환 */
export async function attestOnboarding(
  payload: OnboardingAttestPayload = {}
): Promise<ProfileResponse> {
  return request<ProfileResponse>("POST", "/auth/onboarding/attest/", payload, true);
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
  insurance_count: number;
  summary: HeatmapSummary;
  chart_list: unknown[];
  tree: HeatmapCategory[];
}

/** GET /api/v1/customers/<id>/heatmap/ — requires token */
export async function getHeatmap(customerId: number): Promise<HeatmapResponse> {
  return request<HeatmapResponse>("GET", `/customers/${customerId}/heatmap/`, undefined, true);
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
  images: PromotionSampleImage[];
  form_fields: PromotionFormField[];
  sort_order: number;
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
