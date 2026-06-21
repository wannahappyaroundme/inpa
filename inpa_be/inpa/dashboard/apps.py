from django.apps import AppConfig


class DashboardConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'inpa.dashboard'
    label = 'dashboard'
    verbose_name = '대시보드'
