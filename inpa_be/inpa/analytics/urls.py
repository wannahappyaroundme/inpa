"""북극성 계측 + 공유뷰 라우팅 (dev/13).

base 는 config/urls.py 에서 /api/v1/ 로 마운트.
  GET  /api/v1/s/<token>/                          ShareAnalysisView (AllowAny, 공유뷰)
  POST /api/v1/s/<token>/event/                    ShareEventView (AllowAny, clipboard_copy 등)
  POST /api/v1/customers/<customer_pk>/share/      CustomerShareCreateView (인증, 토큰 발급)
  GET  /api/v1/customers/<customer_pk>/history/     CustomerHistoryView (인증·소유자, 이력 타임라인)
  GET  /api/v1/customers/<customer_pk>/share-snapshots/            CustomerShareSnapshotListView (인증·소유자, 공유 기록 목록)
  GET  /api/v1/customers/<customer_pk>/share-snapshots/<snap_id>/  CustomerShareSnapshotDetailView (인증·소유자, 공유 기록 상세)
"""
from django.urls import path

from .history import CustomerHistoryView
from .views import (
    CustomerShareCreateView, CustomerShareSnapshotDetailView,
    CustomerShareSnapshotListView, CustomerShareSnapshotRevokeView,
    ShareAnalysisView, ShareEventView,
)

app_name = 'analytics'

urlpatterns = [
    path('s/<uuid:token>/', ShareAnalysisView.as_view(), name='share-analysis'),
    path('s/<uuid:token>/event/', ShareEventView.as_view(), name='share-event'),
    path('customers/<int:customer_pk>/share/',
         CustomerShareCreateView.as_view(), name='customer-share-create'),
    path('customers/<int:customer_pk>/history/',
         CustomerHistoryView.as_view(), name='customer-history'),
    path('customers/<int:customer_pk>/share-snapshots/',
         CustomerShareSnapshotListView.as_view(), name='customer-share-snapshot-list'),
    path('customers/<int:customer_pk>/share-snapshots/<int:snap_id>/',
         CustomerShareSnapshotDetailView.as_view(), name='customer-share-snapshot-detail'),
    path('customers/<int:customer_pk>/share-snapshots/<int:snap_id>/revoke/',
         CustomerShareSnapshotRevokeView.as_view(), name='customer-share-snapshot-revoke'),
]
