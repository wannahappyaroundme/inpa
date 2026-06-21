from django.apps import AppConfig


class BookingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'inpa.booking'
    label = 'booking'
    verbose_name = '미팅 예약'
