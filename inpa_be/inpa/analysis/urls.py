"""담보 분석 라우팅 — 담보 한눈표/히트맵 (dev/02 §0).

base 는 config/urls.py 에서 /api/v1/ 로 마운트.
  GET /api/v1/customers/<customer_pk>/heatmap/   CustomerHeatmapView (소유자 격리 + neutral 게이트)

담보 분류 트리/정규화 사전 CRUD ViewSet 은 다음 라운드.
"""
from django.urls import path

from .views import CustomerHeatmapView

app_name = 'analysis'

urlpatterns = [
    path('customers/<int:customer_pk>/heatmap/',
         CustomerHeatmapView.as_view(), name='customer-heatmap'),
]
