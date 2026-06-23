"""개인 일정 라우팅 — config/urls.py 에서 /api/v1/ 로 마운트.

  /api/v1/schedule-items/                       ScheduleItemViewSet (owner)
  /api/v1/schedule-items/<id>/toggle_done/      할일 완료 토글
"""
from rest_framework.routers import SimpleRouter

from . import views

app_name = 'schedule'

router = SimpleRouter()
router.register('schedule-items', views.ScheduleItemViewSet, basename='schedule-item')

urlpatterns = router.urls
