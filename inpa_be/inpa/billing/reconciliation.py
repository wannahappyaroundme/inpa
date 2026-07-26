"""미확정 결제 조회, 늦은 승인 취소, 결제키 폐기."""

from datetime import timedelta
import hashlib

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from inpa.analytics.events import log_billing_event
from inpa.analytics.models import NorthStarEvent

from .kicc import (
    ChargeResult,
    KiccBillingClient,
    KiccIntegrityError,
    OperationResult,
)
from .models import (
    PaymentAttempt,
    PaymentMethodToken,
    PaymentOrder,
)
from .payment_tokens import decrypt_billing_token
from .recurring import (
    _active_token,
    _queue_token_revocation,
    project_free_entitlement,
    project_subscription,
)


def provider_cleanup_configured():
    return all((
        getattr(settings, 'KICC_MALL_ID', ''),
        getattr(settings, 'KICC_CLIENT_SECRET', ''),
        getattr(settings, 'KICC_API_BASE_URL', ''),
        getattr(settings, 'PAYMENT_TOKEN_ENCRYPTION_KEY', ''),
    ))


def _response_hash(result):
    return hashlib.sha256(
        (
            f'{result.kind}|{result.code}|'
            f'{result.provider_transaction_id}|{result.amount_krw}'
        ).encode(),
    ).hexdigest()


def _age_bucket(age):
    if age < timedelta(minutes=5):
        return 'under_5m'
    if age < timedelta(minutes=30):
        return '5m_to_30m'
    if age < timedelta(hours=24):
        return '30m_to_24h'
    return 'over_24h'


def _query_snapshot(order_id):
    with transaction.atomic():
        order = (
            PaymentOrder.objects.select_for_update()
            .select_related('agreement')
            .get(pk=order_id)
        )
        if order.status != 'unknown':
            return order, None
        attempt = order.attempts.order_by('attempt_no').first()
        if not attempt:
            return order, None
        return order, {
            'request_id': attempt.provider_request_id,
            'transaction_date': timezone.localtime(
                attempt.started_at).strftime('%Y%m%d'),
            'expected_order_id': order.merchant_order_id,
            'expected_amount': order.amount_krw,
        }


def _expire_unknown_access(order, agreement, *, failure_code):
    token = _active_token(agreement, lock=True)
    order.failure_code = failure_code
    order.save(update_fields=['failure_code', 'updated_at'])
    project_free_entitlement(
        agreement,
        reason='payment_unknown',
        event_key=f'payment:{order.pk}:unknown-expired',
    )
    _queue_token_revocation(token)


def reconcile_unknown_order(order_id, *, client=None):
    order, query = _query_snapshot(order_id)
    if not query:
        return order
    provider = client or KiccBillingClient()
    try:
        result = provider.query(**query)
    except (KiccIntegrityError, OSError):
        result = ChargeResult(
            kind='unknown',
            code='QUERY_INTEGRITY_UNKNOWN',
        )

    age = timezone.now() - order.unknown_since
    late_approval = result.kind == 'approved' and age >= timedelta(hours=24)
    cancel_result = None
    if late_approval:
        try:
            cancel_result = provider.cancel(
                result.provider_transaction_id,
                order.amount_krw,
                '미확정 이용 시간 경과 후 승인 취소',
                request_id=f'INPA-PC-{order.pk}',
            )
        except (KiccIntegrityError, OSError):
            cancel_result = OperationResult(
                kind='unknown',
                code='CANCEL_INTEGRITY_UNKNOWN',
            )

    with transaction.atomic():
        order = (
            PaymentOrder.objects.select_for_update()
            .select_related('agreement__plan', 'agreement__user')
            .get(pk=order_id)
        )
        if order.status != 'unknown':
            return order
        agreement = order.agreement
        attempt = order.attempts.select_for_update().order_by(
            'attempt_no').first()
        now = timezone.now()

        valid_approval = (
            result.kind == 'approved'
            and result.amount_krw == order.amount_krw
            and bool(result.provider_transaction_id)
        )
        if valid_approval and age < timedelta(hours=24):
            attempt.result_kind = 'approved'
            attempt.provider_code = result.code
            attempt.provider_transaction_id = (
                result.provider_transaction_id)
            attempt.response_hash = _response_hash(result)
            attempt.completed_at = now
            attempt.save(update_fields=[
                'result_kind',
                'provider_code',
                'provider_transaction_id',
                'response_hash',
                'completed_at',
            ])
            order.status = 'approved'
            order.failure_code = ''
            order.save(update_fields=[
                'status', 'failure_code', 'updated_at'])
            project_subscription(agreement)
            transaction.on_commit(
                lambda user=agreement.user,
                plan_code=agreement.plan.code,
                sequence=order.cycle_sequence:
                    log_billing_event(
                        NorthStarEvent.BILLING_CHARGE_SUCCEEDED,
                        sender=user,
                        payload={
                            'plan_code': plan_code,
                            'cycle_sequence': sequence,
                        },
                    )
            )
            return order

        if valid_approval and cancel_result.kind == 'approved':
            attempt.provider_transaction_id = (
                result.provider_transaction_id)
            attempt.provider_code = result.code
            attempt.response_hash = _response_hash(result)
            attempt.completed_at = now
            attempt.save(update_fields=[
                'provider_transaction_id',
                'provider_code',
                'response_hash',
                'completed_at',
            ])
            order.status = 'canceled'
            order.failure_code = 'LATE_APPROVAL_CANCELED'
            order.save(update_fields=[
                'status', 'failure_code', 'updated_at'])
            token = _active_token(agreement, lock=True)
            project_free_entitlement(
                agreement,
                reason='late_approval_canceled',
                event_key=f'payment:{order.pk}:late-canceled',
            )
            transaction.on_commit(
                lambda user=agreement.user,
                sequence=order.cycle_sequence:
                    log_billing_event(
                        NorthStarEvent.BILLING_CHARGE_DECLINED,
                        sender=user,
                        payload={
                            'provider_code_enum':
                                'LATE_APPROVAL_CANCELED',
                            'cycle_sequence': sequence,
                        },
                    )
            )
            _queue_token_revocation(token)
            return order

        if result.kind == 'declined':
            attempt.result_kind = 'declined'
            attempt.provider_code = result.code
            attempt.response_hash = _response_hash(result)
            attempt.completed_at = now
            attempt.save(update_fields=[
                'result_kind',
                'provider_code',
                'response_hash',
                'completed_at',
            ])
            order.status = 'declined'
            order.failure_code = result.code
            order.save(update_fields=[
                'status', 'failure_code', 'updated_at'])
            token = _active_token(agreement, lock=True)
            project_free_entitlement(
                agreement,
                reason='payment_declined',
                event_key=f'payment:{order.pk}:declined',
            )
            transaction.on_commit(
                lambda user=agreement.user,
                code=result.code,
                sequence=order.cycle_sequence:
                    log_billing_event(
                        NorthStarEvent.BILLING_CHARGE_DECLINED,
                        sender=user,
                        payload={
                            'provider_code_enum': code,
                            'cycle_sequence': sequence,
                        },
                    )
            )
            _queue_token_revocation(token)
            return order

        if age >= timedelta(hours=24):
            failure_code = (
                'LATE_CANCEL_PENDING'
                if valid_approval else 'RECONCILIATION_EXPIRED'
            )
            _expire_unknown_access(
                order, agreement, failure_code=failure_code)
        else:
            order.failure_code = result.code or 'PAYMENT_UNKNOWN'
            order.save(update_fields=[
                'failure_code', 'updated_at'])
        transaction.on_commit(
            lambda user=agreement.user,
            bucket=_age_bucket(age):
                log_billing_event(
                    NorthStarEvent.BILLING_CHARGE_UNKNOWN,
                    sender=user,
                    payload={'age_bucket': bucket},
                    dedupe_hours=4,
                )
        )
        return order


def revoke_payment_token(token_id, *, client=None):
    with transaction.atomic():
        token = PaymentMethodToken.objects.select_for_update().get(
            pk=token_id)
        if token.status == 'revoked':
            return token
        if token.status not in ('active', 'revocation_pending'):
            return token
        if token.status == 'active':
            token.status = 'revocation_pending'
            token.save(update_fields=['status', 'updated_at'])
        billing_key = decrypt_billing_token(token)
        request_id = f'INPA-BR-{token.pk}'

    provider = client or KiccBillingClient()
    try:
        result = provider.revoke_key(
            billing_key, request_id=request_id)
    except (KiccIntegrityError, OSError):
        result = OperationResult(
            kind='unknown',
            code='REVOKE_INTEGRITY_UNKNOWN',
        )

    with transaction.atomic():
        token = PaymentMethodToken.objects.select_for_update().get(
            pk=token_id)
        if token.status == 'revoked':
            return token
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
            return token
        token.last_error_code = result.code
        token.save(update_fields=[
            'last_error_code',
            'revocation_attempts',
            'updated_at',
        ])
        return token
