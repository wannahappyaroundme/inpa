"""정기결제 비동기 작업."""

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .kicc import KiccBillingClient
from .models import PaymentMethodToken
from .payment_tokens import decrypt_billing_token


@shared_task(
    bind=True,
    autoretry_for=(),
    max_retries=4,
)
def revoke_payment_token_task(self, token_id):
    with transaction.atomic():
        token = PaymentMethodToken.objects.select_for_update().get(
            pk=token_id)
        if token.status == 'revoked':
            return {'status': 'revoked'}
        if token.status not in ('active', 'revocation_pending'):
            return {'status': token.status}
        if token.status == 'active':
            token.status = 'revocation_pending'
            token.save(update_fields=['status', 'updated_at'])
        billing_key = decrypt_billing_token(token)
        request_id = f'INPA-BR-{token.pk}'

    result = KiccBillingClient().revoke_key(
        billing_key, request_id=request_id)
    with transaction.atomic():
        token = PaymentMethodToken.objects.select_for_update().get(
            pk=token_id)
        token.revocation_attempts += 1
        if result.kind == 'approved':
            token.status = 'revoked'
            token.revoked_at = timezone.now()
            token.encrypted_token = ''
            token.last_error_code = ''
            token.save(update_fields=[
                'status',
                'revoked_at',
                'encrypted_token',
                'last_error_code',
                'revocation_attempts',
                'updated_at',
            ])
            return {'status': 'revoked'}
        token.last_error_code = result.code
        token.save(update_fields=[
            'last_error_code',
            'revocation_attempts',
            'updated_at',
        ])
    countdowns = (60, 300, 1800, 21600)
    attempt_index = min(self.request.retries, len(countdowns) - 1)
    raise self.retry(countdown=countdowns[attempt_index])
