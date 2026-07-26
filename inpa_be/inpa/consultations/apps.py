from django.apps import AppConfig


class ConsultationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'inpa.consultations'
    verbose_name = '상담 녹음'

    def ready(self):
        from . import signals  # noqa: F401
