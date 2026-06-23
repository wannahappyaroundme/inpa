from django.apps import AppConfig


class ScheduleConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'inpa.schedule'
    label = 'schedule'
    verbose_name = '개인 일정'
