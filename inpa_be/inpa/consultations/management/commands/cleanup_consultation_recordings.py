import json

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from inpa.consultations.cleanup import cleanup_expired_recordings


class Command(BaseCommand):
    help = 'Delete consultation source recordings whose server expiry has passed.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=500)
        parser.add_argument('--now', default=None, help='ISO datetime for controlled operations/tests')

    def handle(self, *args, **options):
        now = None
        if options['now']:
            now = parse_datetime(options['now'])
            if now is None:
                raise CommandError('--now must be an ISO datetime')
            if timezone.is_naive(now):
                now = timezone.make_aware(now)
        result = cleanup_expired_recordings(
            now=now,
            limit=options['limit'],
        )
        self.stdout.write(json.dumps(result, sort_keys=True))

