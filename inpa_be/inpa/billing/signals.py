"""billing 앱 시그널.

User post_save → Free Plan Subscription 자동 생성 (dev/23 §2.3).
설계사가 가입한 순간 Subscription 레코드가 없으면 안 된다.

시그널 수신 조건:
  created=True (신규 생성만). 기존 User 업데이트 시 무시.
  Free Plan이 DB에 없으면 에러 대신 경고만 남기고 넘어감(초기 마이그레이션 순서 보호).
"""
import logging

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)

_AUTH_USER_MODEL = settings.AUTH_USER_MODEL


@receiver(post_save, sender=_AUTH_USER_MODEL)
def create_free_subscription(sender, instance, created, **kwargs):
    """User 생성 시 Free Plan Subscription 자동 생성."""
    if not created:
        return

    # 순환 import 방지 — ready() 이후에 import
    from .models import Plan, Subscription

    try:
        free_plan = Plan.objects.get(code='free')
    except Plan.DoesNotExist:
        # 초기 마이그레이션 순서상 Plan 시드 전에 User가 생성될 수 있음
        logger.warning(
            'billing.Plan(code="free")가 없어 Subscription 자동 생성을 건너뜀. '
            'User pk=%s. 시드 후 수동으로 생성 필요.',
            instance.pk,
        )
        return

    Subscription.objects.get_or_create(
        user=instance,
        defaults={'plan': free_plan, 'status': 'active'},
    )
