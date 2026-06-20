"""담보 분석 라우팅 — 담보 한눈표/히트맵 + 갈아타기 비교 (dev/02 §0).

base 는 config/urls.py 에서 /api/v1/ 로 마운트.
  GET  /api/v1/customers/<customer_pk>/heatmap/          CustomerHeatmapView (소유자 격리 + neutral 게이트)
  GET/POST /api/v1/customers/<customer_pk>/compare/      CustomerCompareView (보유 vs 제안 담보별 비교 + §97 게이트)
  POST /api/v1/customers/<customer_pk>/compare/publish/  CustomerComparePublishView (★ 발행 하드블록)

담보 분류 트리/정규화 사전 CRUD ViewSet 은 다음 라운드.
"""
from django.urls import path

from .compare import CustomerCompareView, CustomerComparePublishView
from .views import CustomerHeatmapView

app_name = 'analysis'

urlpatterns = [
    path('customers/<int:customer_pk>/heatmap/',
         CustomerHeatmapView.as_view(), name='customer-heatmap'),
    path('customers/<int:customer_pk>/compare/',
         CustomerCompareView.as_view(), name='customer-compare'),
    path('customers/<int:customer_pk>/compare/publish/',
         CustomerComparePublishView.as_view(), name='customer-compare-publish'),
]
