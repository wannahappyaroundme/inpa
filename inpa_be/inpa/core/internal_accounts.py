"""Internal-only account classification and showcase action guard."""
from django.conf import settings
from django.db import models
from rest_framework.exceptions import APIException


def is_showcase_user(user) -> bool:
    """Return True only for the configured account carrying the showcase marker."""
    showcase_email = getattr(settings, 'SHOWCASE_ACCOUNT_EMAIL', '')
    if not showcase_email or getattr(user, 'email', None) != showcase_email:
        return False
    return bool(getattr(getattr(user, 'profile', None), 'is_showcase', False))


def internal_user_q(relation: str = '') -> models.Q:
    """Match local demo users and the verified showcase account through relation."""
    prefix = f'{relation}__' if relation else ''
    query = models.Q(**{f'{prefix}email__iendswith': '@inpa.local'})
    showcase_email = getattr(settings, 'SHOWCASE_ACCOUNT_EMAIL', '')
    if not showcase_email:
        return query
    return query | models.Q(
        **{
            f'{prefix}email': showcase_email,
            f'{prefix}profile__is_showcase': True,
        }
    )


class ShowcaseActionRestricted(APIException):
    status_code = 403
    default_detail = {
        'code': 'SHOWCASE_ACTION_RESTRICTED',
        'detail': '등록된 자료를 활용해 주요 기능을 확인할 수 있어요.',
    }


def block_showcase_external_action(user) -> None:
    """Prevent the verified showcase account from triggering external actions."""
    if is_showcase_user(user):
        raise ShowcaseActionRestricted()
