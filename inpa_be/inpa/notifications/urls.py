"""알림 도메인 라우팅 (dev/22 §5.1).

base는 config/urls.py에서 /api/v1/로 마운트.

  GET    /api/v1/notifications/                  목록 (페이지네이션, ?is_read 필터)
  GET    /api/v1/notifications/{id}/             상세
  DELETE /api/v1/notifications/{id}/             단일 삭제
  PATCH  /api/v1/notifications/{id}/read/        단일 읽음 처리
  GET    /api/v1/notifications/unread-count/     미읽음 수 (벨 배지)
  POST   /api/v1/notifications/read-all/         전체 읽음 처리

  GET    /api/v1/reminder-rules/                 내 설정 5종 조회
  PATCH  /api/v1/reminder-rules/bulk/            설정 일괄 업데이트
"""
from rest_framework.routers import SimpleRouter

from .views import NotificationViewSet, ReminderRuleViewSet

app_name = 'notifications'

router = SimpleRouter()
router.register('notifications', NotificationViewSet, basename='notification')
router.register('reminder-rules', ReminderRuleViewSet, basename='reminder-rule')

# router가 자동으로 list/detail 라우트 + @action URL 생성:
#   /notifications/              → list
#   /notifications/{pk}/         → retrieve, destroy
#   /notifications/{pk}/read/    → mark_read
#   /notifications/unread-count/ → unread_count
#   /notifications/read-all/     → read_all
#   /reminder-rules/             → list
#   /reminder-rules/bulk/        → bulk_update
urlpatterns = router.urls
