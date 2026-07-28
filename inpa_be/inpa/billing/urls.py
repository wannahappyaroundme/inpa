"""billing 도메인 라우팅 (dev/23 §4).

config/urls.py에서 /api/v1/ 로 마운트.

  GET  /api/v1/billing/plans/                     — 요금제 목록 (AllowAny)
  GET  /api/v1/billing/event/                      — 진행 중 이벤트 플래그 (AllowAny)
  GET  /api/v1/billing/usage/                     — 내 사용량 (IsAuthenticated)
  GET  /api/v1/admin/billing/usage/               — 관리자 전체 사용량 (IsAdmin)
  PATCH /api/v1/admin/billing/subscription/<uid>/ — 관리자 구독 수동 변경 (IsAdmin)
"""
from django.urls import path

from .views import (
    AdminBenefitReviewDecisionView,
    AdminBenefitReviewDetailView,
    AdminBenefitReviewListView,
    AdminBillingModeView,
    AdminBillingUsageView,
    AdminSubscriptionPatchView,
    BillingEventView,
    BillingCancellationView,
    BillingNoticeDismissView,
    BillingNoticeLeaseView,
    BillingNoticeRenderedView,
    BillingStatusView,
    BillingUsageView,
    CardRegistrationCompleteView,
    CardRegistrationProviderReturnView,
    CardRegistrationStartView,
    CouponRedeemView,
    FirstChargeReconfirmationView,
    FreeTrialPhoneRequestView,
    FreeTrialPhoneVerifyView,
    ManualBenefitReviewRequestView,
    PlanListView,
    RecurringCouponPreflightView,
)

app_name = 'billing'

urlpatterns = [
    # 설계사 공개 / 본인 조회
    path('billing/plans/', PlanListView.as_view(), name='plan-list'),
    path('billing/event/', BillingEventView.as_view(), name='billing-event'),
    path('billing/usage/', BillingUsageView.as_view(), name='billing-usage'),
    path('billing/coupons/redeem/', CouponRedeemView.as_view(), name='coupon-redeem'),
    path(
        'billing/free-trial/phone/request/',
        FreeTrialPhoneRequestView.as_view(),
        name='free-trial-phone-request',
    ),
    path(
        'billing/free-trial/phone/verify/',
        FreeTrialPhoneVerifyView.as_view(),
        name='free-trial-phone-verify',
    ),
    path(
        'billing/free-trial/manual-reviews/',
        ManualBenefitReviewRequestView.as_view(),
        name='free-trial-manual-review',
    ),
    path(
        'billing/coupons/preflight/',
        RecurringCouponPreflightView.as_view(),
        name='recurring-coupon-preflight',
    ),
    path(
        'billing/card-registration/start/',
        CardRegistrationStartView.as_view(),
        name='card-registration-start',
    ),
    path(
        'billing/card-registration/complete/',
        CardRegistrationCompleteView.as_view(),
        name='card-registration-complete',
    ),
    path(
        'billing/card-registration/provider-return/',
        CardRegistrationProviderReturnView.as_view(),
        name='card-registration-provider-return',
    ),
    path('billing/status/', BillingStatusView.as_view(), name='billing-status'),
    path(
        'billing/reconfirm/',
        FirstChargeReconfirmationView.as_view(),
        name='billing-reconfirm',
    ),
    path(
        'billing/cancel/',
        BillingCancellationView.as_view(),
        name='billing-cancel',
    ),
    path(
        'billing/notices/lease/',
        BillingNoticeLeaseView.as_view(),
        name='billing-notice-lease',
    ),
    path(
        'billing/notices/<int:notice_id>/rendered/',
        BillingNoticeRenderedView.as_view(),
        name='billing-notice-rendered',
    ),
    path(
        'billing/notices/<int:notice_id>/dismiss/',
        BillingNoticeDismissView.as_view(),
        name='billing-notice-dismiss',
    ),

    # 관리자 전용
    path('admin/billing/mode/', AdminBillingModeView.as_view(), name='admin-billing-mode'),
    path(
        'admin/billing/benefit-reviews/',
        AdminBenefitReviewListView.as_view(),
        name='admin-benefit-review-list',
    ),
    path(
        'admin/billing/benefit-reviews/<int:review_id>/',
        AdminBenefitReviewDetailView.as_view(),
        name='admin-benefit-review-detail',
    ),
    path(
        'admin/billing/benefit-reviews/<int:review_id>/decision/',
        AdminBenefitReviewDecisionView.as_view(),
        name='admin-benefit-review-decision',
    ),
    path('admin/billing/usage/', AdminBillingUsageView.as_view(), name='admin-billing-usage'),
    path(
        'admin/billing/subscription/<int:user_id>/',
        AdminSubscriptionPatchView.as_view(),
        name='admin-subscription-patch',
    ),
]
