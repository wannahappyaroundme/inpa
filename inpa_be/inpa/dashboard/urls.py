"""대시보드 라우팅 — config/urls.py에서 /api/v1/로 마운트. GET/PATCH /api/v1/dashboard/"""
from django.urls import path

from .views import DashboardView, InsightsView

app_name = 'dashboard'

urlpatterns = [
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('dashboard/insights/', InsightsView.as_view(), name='insights'),
]
