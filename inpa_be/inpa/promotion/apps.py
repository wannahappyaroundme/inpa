"""판촉물 앱 설정 (dev/21)."""
from django.apps import AppConfig


class PromotionConfig(AppConfig):
    name = 'inpa.promotion'
    label = 'promotion'
    verbose_name = '판촉물'
