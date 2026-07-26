"""정기결제 안전 작업을 다시 찾아 큐에 넣는다."""

from django.core.management.base import BaseCommand
from django.utils import timezone

from inpa.billing.gates import recurring_charge_enabled
from inpa.billing.models import (
    BillingAgreement,
    PaymentMethodToken,
    PaymentOrder,
)
from inpa.billing.reconciliation import provider_cleanup_configured
from inpa.billing.tasks import (
    charge_due_agreement_task,
    reconcile_unknown_order_task,
    revoke_payment_token_task,
)


class Command(BaseCommand):
    help = '도래 결제, 미확정 거래, 결제키 폐기 작업을 안전하게 재등록합니다.'

    def handle(self, *args, **options):
        counts = {'due': 0, 'unknown': 0, 'revocation': 0}
        if recurring_charge_enabled():
            today = timezone.localdate()
            due_agreements = BillingAgreement.objects.filter(
                status__in=('trialing', 'active'),
                next_charge_date__lte=today,
            ).values_list('pk', 'next_charge_date')
            for agreement_id, due_date in due_agreements.iterator():
                charge_due_agreement_task.delay(
                    str(agreement_id), due_date.isoformat())
                counts['due'] += 1

        if provider_cleanup_configured():
            for order_id in PaymentOrder.objects.filter(
                    status='unknown').values_list('pk', flat=True).iterator():
                reconcile_unknown_order_task.delay(order_id)
                counts['unknown'] += 1
            for token_id in PaymentMethodToken.objects.filter(
                    status='revocation_pending').values_list(
                        'pk', flat=True).iterator():
                revoke_payment_token_task.delay(token_id)
                counts['revocation'] += 1

        self.stdout.write(
            self.style.SUCCESS(
                'billing reconciliation queued '
                f"due={counts['due']} "
                f"unknown={counts['unknown']} "
                f"revocation={counts['revocation']}"
            )
        )
