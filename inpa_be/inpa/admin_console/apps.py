"""admin_console 앱 설정 (dev/19 관리자 콘솔)."""
from django.apps import AppConfig


class AdminConsoleConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'inpa.admin_console'
    label = 'admin_console'
    verbose_name = '관리자 콘솔'
