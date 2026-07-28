from django.apps import AppConfig


class TalksConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'inpa.talks'
    label = 'talks'
    verbose_name = '나만의 화법'
