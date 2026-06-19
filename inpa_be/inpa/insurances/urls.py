"""보험 라우팅 — 증권 OCR 업로드 (dev/02 §7, dev/12 §5).

base 는 config/urls.py 에서 /api/v1/ 로 마운트.
  POST /api/v1/customers/<customer_pk>/insurances/ocr/   InsuranceOcrViewSet (★동의 게이트)

하위 라우트는 외부 패키지(drf-nested-routers) 없이 ViewSet.as_view 매핑으로 명시
(customers/urls.py 와 동일 패턴 — 외부 의존 최소화).
"""
from django.urls import path

from .views import InsuranceOcrViewSet

app_name = 'insurances'

urlpatterns = [
    path('customers/<int:customer_pk>/insurances/ocr/',
         InsuranceOcrViewSet.as_view({'post': 'create'}),
         name='insurance-ocr-upload'),
]
