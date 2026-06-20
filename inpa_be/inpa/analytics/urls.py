"""북극성 계측 + 공유뷰 라우팅 (dev/13).

base 는 config/urls.py 에서 /api/v1/ 로 마운트.
  GET  /api/v1/s/<token>/                       ShareAnalysisView (AllowAny, 공유뷰)
  POST /api/v1/s/<token>/event/                 ShareEventView (AllowAny, clipboard_copy 등)
  POST /api/v1/customers/<customer_pk>/share/   CustomerShareCreateView (인증, 토큰 발급)
"""
from django.urls import path

from .views import (
    CustomerShareCreateView, ShareAnalysisView, ShareEventView,
)

app_name = 'analytics'

urlpatterns = [
    path('s/<uuid:token>/', ShareAnalysisView.as_view(), name='share-analysis'),
    path('s/<uuid:token>/event/', ShareEventView.as_view(), name='share-event'),
    path('customers/<int:customer_pk>/share/',
         CustomerShareCreateView.as_view(), name='customer-share-create'),
]
