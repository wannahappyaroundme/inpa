"""판촉물 도메인 URL 라우팅 (dev/21 §4).

config/urls.py에서 /api/v1/ 로 마운트.

설계사 공개:
  GET    /api/v1/promotion/samples/                 샘플 목록
  GET    /api/v1/promotion/samples/:id/             샘플 상세 (form_fields 포함)
  POST   /api/v1/promotion/orders/                  주문 생성
  GET    /api/v1/promotion/orders/                  내 주문 목록
  GET    /api/v1/promotion/orders/:id/              내 주문 상세 + 타임라인
  DELETE /api/v1/promotion/orders/:id/              주문 취소 (pending 상태만)

관리자 전용:
  GET    /api/v1/admin/promotion/samples/                    샘플 목록
  POST   /api/v1/admin/promotion/samples/                    샘플 등록
  GET    /api/v1/admin/promotion/samples/:id/                샘플 상세
  PATCH  /api/v1/admin/promotion/samples/:id/                샘플 수정
  DELETE /api/v1/admin/promotion/samples/:id/                샘플 삭제
  POST   /api/v1/admin/promotion/samples/:id/images/         이미지 추가
  DELETE /api/v1/admin/promotion/samples/:id/images/:img_id/ 이미지 삭제
  GET    /api/v1/admin/promotion/orders/                     전체 주문 목록 + 필터
  PATCH  /api/v1/admin/promotion/orders/:id/status/          상태 변경 + 메모
"""
from django.urls import path

from .views import (
    AdminOrderListView,
    AdminOrderStatusPatchView,
    AdminSampleDetailView,
    AdminSampleImageCreateView,
    AdminSampleImageDeleteView,
    AdminSampleListCreateView,
    PromotionDigitalRequestView,
    PromotionOrderDetailView,
    PromotionOrderListCreateView,
    PromotionSampleDetailView,
    PromotionSampleListView,
)

app_name = 'promotion'

urlpatterns = [
    # ── 설계사 공개 — 샘플 ────────────────────────────────────────
    path('promotion/samples/', PromotionSampleListView.as_view(), name='sample-list'),
    path('promotion/samples/<int:pk>/', PromotionSampleDetailView.as_view(), name='sample-detail'),
    # 전자자료 1회 무료 / 2회차+ 어드민 큐 (PM 06.24)
    path('promotion/samples/<int:sample_id>/request/', PromotionDigitalRequestView.as_view(), name='sample-digital-request'),

    # ── 설계사 공개 — 주문 ────────────────────────────────────────
    path('promotion/orders/', PromotionOrderListCreateView.as_view(), name='order-list-create'),
    path('promotion/orders/<int:pk>/', PromotionOrderDetailView.as_view(), name='order-detail'),

    # ── 관리자 전용 — 샘플 ────────────────────────────────────────
    path('admin/promotion/samples/', AdminSampleListCreateView.as_view(), name='admin-sample-list'),
    path('admin/promotion/samples/<int:pk>/', AdminSampleDetailView.as_view(), name='admin-sample-detail'),
    path('admin/promotion/samples/<int:pk>/images/', AdminSampleImageCreateView.as_view(), name='admin-sample-image-create'),
    path('admin/promotion/samples/<int:pk>/images/<int:img_id>/', AdminSampleImageDeleteView.as_view(), name='admin-sample-image-delete'),

    # ── 관리자 전용 — 주문 ────────────────────────────────────────
    path('admin/promotion/orders/', AdminOrderListView.as_view(), name='admin-order-list'),
    path('admin/promotion/orders/<int:pk>/status/', AdminOrderStatusPatchView.as_view(), name='admin-order-status'),
]
