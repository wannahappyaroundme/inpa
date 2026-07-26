"""환경과 운영 스위치가 함께 여는 결제 기능 게이트."""

from django.conf import settings

from .models import RuntimeConfig


def _configured(name):
    return bool(getattr(settings, name, ''))


def card_registration_enabled() -> bool:
    config = RuntimeConfig.solo()
    return all((
        getattr(settings, 'BILLING_CARD_REGISTRATION_ENABLED', False),
        config.billing_card_registration_enabled,
        _configured('KICC_MALL_ID'),
        _configured('KICC_CLIENT_SECRET'),
        _configured('KICC_API_BASE_URL'),
        _configured('PAYMENT_TOKEN_ENCRYPTION_KEY'),
    ))


def reconciliation_enabled() -> bool:
    config = RuntimeConfig.solo()
    return all((
        getattr(
            settings,
            'BILLING_WEBHOOK_RECONCILIATION_ENABLED',
            False,
        ),
        config.billing_reconciliation_enabled,
        _configured('KICC_MALL_ID'),
        _configured('KICC_CLIENT_SECRET'),
        _configured('KICC_API_BASE_URL'),
    ))


def recurring_charge_enabled() -> bool:
    config = RuntimeConfig.solo()
    return all((
        card_registration_enabled(),
        reconciliation_enabled(),
        getattr(settings, 'BILLING_RECURRING_CHARGE_ENABLED', False),
        config.billing_recurring_charge_enabled,
        not config.free_tier_unlimited,
        not getattr(settings, 'FREE_TIER_UNLIMITED', True),
    ))
