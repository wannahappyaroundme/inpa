"""정기결제 비동기 작업."""

from datetime import date

from celery import shared_task

from .reconciliation import (
    reconcile_unknown_order,
    revoke_payment_token,
)
from .recurring import create_and_charge_due_agreement


@shared_task(
    bind=True,
    autoretry_for=(),
    max_retries=4,
)
def revoke_payment_token_task(self, token_id):
    token = revoke_payment_token(token_id)
    if token.status == 'revoked':
        return {'status': 'revoked'}
    countdowns = (60, 300, 1800, 21600)
    attempt_index = min(self.request.retries, len(countdowns) - 1)
    raise self.retry(countdown=countdowns[attempt_index])


@shared_task
def charge_due_agreement_task(agreement_id, due_date):
    return {
        'order_id': create_and_charge_due_agreement(
            agreement_id,
            date.fromisoformat(due_date),
        ).pk,
    }


@shared_task
def reconcile_unknown_order_task(order_id):
    return {
        'order_id': reconcile_unknown_order(order_id).pk,
    }


def schedule_unknown_reconciliation(order_id):
    for countdown in (300, 1800, 86400):
        reconcile_unknown_order_task.apply_async(
            args=[order_id],
            countdown=countdown,
        )
