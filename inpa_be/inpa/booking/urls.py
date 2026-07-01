"""미팅 예약 라우팅 — config/urls.py에서 /api/v1/로 마운트.

  /api/v1/meetings/                               MeetingViewSet (owner, +cancel)
  /api/v1/customers/<id>/booking-requests/        예약 링크 생성(설계사)
  /api/v1/b/<token>/                              공개 예약(고객, 비로그인)
"""
from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views
from .public_booking import PublicBookingView

app_name = 'booking'

router = SimpleRouter()
router.register('work-hours', views.WorkHourViewSet, basename='work-hour')
router.register('meetings', views.MeetingViewSet, basename='meeting')

urlpatterns = router.urls + [
    path('customers/<int:customer_pk>/booking-requests/',
         views.BookingRequestCreateView.as_view(), name='booking-request-create'),
    path('b/<str:token>/', PublicBookingView.as_view(), name='public-booking'),
]
