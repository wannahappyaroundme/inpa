"""billing 도메인 라우팅 (dev/23 §4).

config/urls.py에서 /api/v1/ 로 마운트.

  GET  /api/v1/billing/plans/                     — 요금제 목록 (AllowAny)
  GET  /api/v1/billing/usage/                     — 내 사용량 (IsAuthenticated)
  GET  /api/v1/admin/billing/usage/               — 관리자 전체 사용량 (IsAdmin)
  PATCH /api/v1/admin/billing/subscription/<uid>/ — 관리자 구독 수동 변경 (IsAdmin)
"""
from django.urls import path

from .views import (
    AdminBillingUsageView,
    AdminSubscriptionPatchView,
    BillingUsageView,
    PlanListView,
)

app_name = 'billing'

urlpatterns = [
    # 설계사 공개 / 본인 조회
    path('billing/plans/', PlanListView.as_view(), name='plan-list'),
    path('billing/usage/', BillingUsageView.as_view(), name='billing-usage'),

    # 관리자 전용
    path('admin/billing/usage/', AdminBillingUsageView.as_view(), name='admin-billing-usage'),
    path(
        'admin/billing/subscription/<int:user_id>/',
        AdminSubscriptionPatchView.as_view(),
        name='admin-subscription-patch',
    ),
]
