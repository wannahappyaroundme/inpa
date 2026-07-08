"""admin_console URL 라우팅 (dev/19 §5 API 계약).

base path: /api/v1/admin/  (config/urls.py에서 include)
"""
from django.urls import path

from .views import (
    AdminConsentLogListView,
    AdminCoverageFlagListView,
    AdminCoverageFlagResolveView,
    AdminDashboardView,
    AdminFaqDetailView,
    AdminFaqListView,
    AdminFeatureFlagsView,
    AdminInquiryDetailView,
    AdminInquiryListView,
    AdminInquiryReplyView,
    AdminInquiryStatusView,
    AdminLoginView,
    AdminLogoutView,
    AdminNormalizationDictDetailView,
    AdminNormalizationDictListView,
    AdminNormalizationLeavesView,
    AdminNormalizationMapView,
    AdminNoticeDetailView,
    AdminNoticeListView,
    AdminOrderDetailView,
    AdminOrderListView,
    AdminOrderStatusView,
    AdminPlanDetailView,
    AdminPlanListView,
    AdminPolicyVersionListView,
    AdminReportActionView,
    AdminReportListView,
    AdminUnmatchedListView,
    AdminUsageView,
    AdminUserCustomersView,
    AdminUserDetailView,
    AdminUserListView,
    AdminUserSendResetEmailView,
    AdminUserSubscriptionView,
)

urlpatterns = [
    # ── 인증 ──────────────────────────────────────────────────────────
    path('admin/auth/login/', AdminLoginView.as_view(), name='admin-login'),
    path('admin/auth/logout/', AdminLogoutView.as_view(), name='admin-logout'),

    # ── 대시보드 ──────────────────────────────────────────────────────
    path('admin/dashboard/', AdminDashboardView.as_view(), name='admin-dashboard'),
    path('admin/usage/', AdminUsageView.as_view(), name='admin-usage'),

    # ── 설계사 관리 ───────────────────────────────────────────────────
    path('admin/users/', AdminUserListView.as_view(), name='admin-user-list'),
    path('admin/users/<int:user_id>/', AdminUserDetailView.as_view(), name='admin-user-detail'),
    path('admin/users/<int:user_id>/customers/', AdminUserCustomersView.as_view(),
         name='admin-user-customers'),
    path('admin/users/<int:user_id>/subscription/', AdminUserSubscriptionView.as_view(),
         name='admin-user-subscription'),
    path('admin/users/<int:user_id>/send_reset_email/', AdminUserSendResetEmailView.as_view(),
         name='admin-user-send-reset-email'),

    # ── 1:1 문의 ──────────────────────────────────────────────────────
    path('admin/inquiries/', AdminInquiryListView.as_view(), name='admin-inquiry-list'),
    path('admin/inquiries/<int:inquiry_id>/', AdminInquiryDetailView.as_view(),
         name='admin-inquiry-detail'),
    path('admin/inquiries/<int:inquiry_id>/reply/', AdminInquiryReplyView.as_view(),
         name='admin-inquiry-reply'),
    path('admin/inquiries/<int:inquiry_id>/status/', AdminInquiryStatusView.as_view(),
         name='admin-inquiry-status'),

    # ── 신고 모더레이션 ────────────────────────────────────────────────
    path('admin/reports/', AdminReportListView.as_view(), name='admin-report-list'),
    path('admin/reports/<int:report_id>/action/', AdminReportActionView.as_view(),
         name='admin-report-action'),

    # ── 판촉물 주문 ───────────────────────────────────────────────────
    path('admin/orders/', AdminOrderListView.as_view(), name='admin-order-list'),
    path('admin/orders/<int:order_id>/', AdminOrderDetailView.as_view(), name='admin-order-detail'),
    path('admin/orders/<int:order_id>/status/', AdminOrderStatusView.as_view(),
         name='admin-order-status'),

    # ── 동의 로그 (READ-ONLY — DELETE 미구현, 감사 무결성) ─────────────
    path('admin/consent-logs/', AdminConsentLogListView.as_view(), name='admin-consent-log-list'),

    # ── 정규화 매핑 큐 ─────────────────────────────────────────────────
    path('admin/normalization/unmatched/', AdminUnmatchedListView.as_view(),
         name='admin-unmatched-list'),
    path('admin/normalization/map/', AdminNormalizationMapView.as_view(),
         name='admin-normalization-map'),
    path('admin/normalization/dict/', AdminNormalizationDictListView.as_view(),
         name='admin-normalization-dict-list'),
    path('admin/normalization/dict/<int:dict_id>/', AdminNormalizationDictDetailView.as_view(),
         name='admin-normalization-dict-detail'),
    path('admin/normalization/leaves/', AdminNormalizationLeavesView.as_view(),
         name='admin-normalization-leaves'),
    path('admin/normalization/flags/', AdminCoverageFlagListView.as_view(),
         name='admin-coverage-flag-list'),
    path('admin/normalization/flags/<int:flag_id>/resolve/', AdminCoverageFlagResolveView.as_view(),
         name='admin-coverage-flag-resolve'),

    # ── 공지사항 (admin 쓰기 — 읽기는 /api/v1/board/notices/ AllowAny) ──
    path('admin/notices/', AdminNoticeListView.as_view(), name='admin-notice-list'),
    path('admin/notices/<int:notice_id>/', AdminNoticeDetailView.as_view(), name='admin-notice-detail'),

    # ── FAQ (admin 쓰기 — 읽기는 /api/v1/board/faqs/ AllowAny) ─────────
    path('admin/faq/', AdminFaqListView.as_view(), name='admin-faq-list'),
    path('admin/faq/<int:faq_id>/', AdminFaqDetailView.as_view(), name='admin-faq-detail'),

    # ── 운영 설정 — 요금제 한도 ────────────────────────────────────────
    path('admin/settings/plans/', AdminPlanListView.as_view(), name='admin-plan-list'),
    path('admin/settings/plans/<str:plan_code>/', AdminPlanDetailView.as_view(),
         name='admin-plan-detail'),

    # ── 운영 설정 — 약관 버전 ────────────────────────────────────────
    path('admin/settings/policy-versions/', AdminPolicyVersionListView.as_view(),
         name='admin-policy-version-list'),

    # ── 운영 설정 — 기능 플래그 (읽기 전용 — env 우회 차단) ─────────
    path('admin/settings/flags/', AdminFeatureFlagsView.as_view(), name='admin-feature-flags'),
]
