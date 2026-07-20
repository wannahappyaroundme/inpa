from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from inpa.analytics.models import ShareSnapshot
from inpa.customers.models import Customer


class Command(BaseCommand):
    help = '과거 공유 링크를 변경하지 않고 유형별 수량을 점검합니다.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--revoke-legacy', action='store_true',
            help='별도 운영 승인 후 과거 링크를 닫습니다.')

    def handle(self, *args, **options):
        now = timezone.now()
        issued_customers = Customer.objects.filter(
            share_sent_at__isnull=False,
        ).filter(Q(share_expires_at__isnull=True) | Q(share_expires_at__gt=now))
        backed_tokens = ShareSnapshot.objects.filter(
            share_token__isnull=False,
        ).values('share_token')
        unbacked = issued_customers.exclude(share_token__in=backed_tokens)
        v1_history = ShareSnapshot.objects.filter(
            payload_version='v1-legacy-actions',
            share_token__isnull=False,
        )
        v1 = (v1_history
              .filter(revoked_at__isnull=True)
              .filter(Q(link_expires_at__isnull=True)
                      | Q(link_expires_at__gt=now))
              .filter(customer__share_token=F('share_token'))
              .filter(Q(customer__share_expires_at__isnull=True)
                      | Q(customer__share_expires_at__gt=now)))
        frozen_booking = sum(
            1 for payload in v1.values_list('payload', flat=True).iterator()
            if isinstance(payload, dict) and payload.get('booking_url')
        )
        v1_history_count = v1_history.count()
        v1_active_count = v1.count()

        revoke = bool(options['revoke_legacy'])
        self.stdout.write(f'unbacked_legacy_links={unbacked.count()}')
        self.stdout.write(f'v1_legacy_snapshots={v1_active_count}')
        self.stdout.write(f'v1_frozen_booking_actions={frozen_booking}')
        self.stdout.write(f'v1_history_snapshots={v1_history_count}')
        self.stdout.write(
            f'v1_inactive_snapshots={v1_history_count - v1_active_count}')
        self.stdout.write(f'dry_run={str(not revoke).lower()}')

        if not revoke:
            return

        with transaction.atomic():
            unbacked.update(share_expires_at=now)
            legacy_ids = list(v1.values_list('pk', flat=True))
            legacy_tokens = list(v1.values_list('share_token', flat=True))
            Customer.objects.filter(share_token__in=legacy_tokens).update(
                share_expires_at=now)
            v1_history.filter(pk__in=legacy_ids).update(
                revoked_at=now, revoked_reason='legacy_revoke')
        self.stdout.write('legacy_links_revoked=true')
