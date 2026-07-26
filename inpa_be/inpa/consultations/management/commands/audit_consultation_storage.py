import json

from django.core.management.base import BaseCommand
from django.utils import timezone

from inpa.consultations.cleanup import SOURCE_PRESENT_STATUSES
from inpa.consultations.models import ConsultationRecording
from inpa.consultations.services import get_recording_storage
from inpa.consultations.storage import recording_id_from_key


class Command(BaseCommand):
    help = 'Compare private recording objects with database references without reading content.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        now = timezone.now()
        rows = list(
            ConsultationRecording.objects.filter(
                storage_key__isnull=False,
                status__in=SOURCE_PRESENT_STATUSES,
            ).values('id', 'storage_key', 'expires_at')
        )
        storage = get_recording_storage()
        object_keys = set(storage.iter_keys())
        db_keys = {row['storage_key'] for row in rows}
        missing = sorted(db_keys - object_keys)
        orphan = sorted(object_keys - db_keys)
        overdue = sorted(
            row['storage_key']
            for row in rows
            if row['expires_at'] is not None
            and row['expires_at'] <= now
            and row['storage_key'] in object_keys
        )
        deleted = 0
        failed = 0
        if options['apply']:
            for key in orphan:
                try:
                    storage.delete(key)
                except Exception:
                    failed += 1
                else:
                    deleted += 1
        result = {
            'missing_db_object_count': len(missing),
            'missing_db_object_ids': [
                str(recording_id_from_key(key)) for key in missing
            ],
            'orphan_object_count': len(orphan),
            'orphan_object_ids': [
                str(recording_id_from_key(key)) for key in orphan
            ],
            'overdue_object_count': len(overdue),
            'overdue_object_ids': [
                str(recording_id_from_key(key)) for key in overdue
            ],
            'applied': bool(options['apply']),
            'deleted': deleted,
            'failed': failed,
        }
        self.stdout.write(json.dumps(result, sort_keys=True))
