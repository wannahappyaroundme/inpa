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
    AdminBillingModeView,
    AdminBillingUsageView,
    AdminSubscriptionPatchView,
    BillingEventView,
    BillingStatusView,
    BillingUsageView,
    CardRegistrationCompleteView,
    CardRegistrationProviderReturnView,
    CardRegistrationStartView,
    CouponRedeemView,
    FirstChargeReconfirmationView,
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

    # 관리자 전용
    path('admin/billing/mode/', AdminBillingModeView.as_view(), name='admin-billing-mode'),
    path('admin/billing/usage/', AdminBillingUsageView.as_view(), name='admin-billing-usage'),
    path(
        'admin/billing/subscription/<int:user_id>/',
        AdminSubscriptionPatchView.as_view(),
        name='admin-subscription-patch',
    ),
]
