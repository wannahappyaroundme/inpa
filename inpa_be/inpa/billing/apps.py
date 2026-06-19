from django.apps import AppConfig


class BillingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'inpa.billing'
    label = 'billing'

    def ready(self):
        import inpa.billing.signals  # noqa: F401 — post_save 시그널 등록
