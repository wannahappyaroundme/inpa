"""알림 도메인 Django admin 등록."""
from django.contrib import admin

from .models import Notification, ReminderRule


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['id', 'owner', 'notif_type', 'title', 'is_read', 'sent_email', 'created_at']
    list_filter = ['notif_type', 'is_read', 'sent_email']
    search_fields = ['owner__email', 'title']
    readonly_fields = ['owner', 'notif_type', 'title', 'body', 'target_date',
                       'customer', 'calendar_event_id', 'is_read', 'sent_email', 'created_at']

    def has_add_permission(self, request):
        """알림은 cron/signal 자동 생성 전용 — 관리자 수동 생성 금지 (dev/22 §6.1)."""
        return False


@admin.register(ReminderRule)
class ReminderRuleAdmin(admin.ModelAdmin):
    list_display = ['id', 'owner', 'rule_type', 'days_before', 'enabled', 'email_enabled', 'updated_at']
    list_filter = ['rule_type', 'enabled', 'email_enabled']
    search_fields = ['owner__email']
