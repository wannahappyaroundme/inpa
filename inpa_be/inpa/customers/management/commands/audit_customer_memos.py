"""구버전 Customer.memo와 상담 메모 호환 행을 내용 노출 없이 대조한다."""
import hashlib
import json

from django.core.management.base import BaseCommand, CommandError

from inpa.customers.models import Customer, CustomerMemo


def _clean(value):
    return (value or '').strip()


def _digest_add(hasher, customer_id, body):
    hasher.update(str(customer_id).encode())
    hasher.update(b'\0')
    hasher.update(body.encode())
    hasher.update(b'\0')


class Command(BaseCommand):
    help = '기존 메모와 상담 메모 이관 상태를 안전하게 대조합니다.'

    def handle(self, *args, **options):
        old_rows = Customer.objects.order_by('pk').values_list('pk', 'memo').iterator(chunk_size=500)
        mirror_rows = (CustomerMemo.objects
                       .filter(source__in=(CustomerMemo.SOURCE_LEGACY, CustomerMemo.SOURCE_MANUAL))
                       .order_by('customer_id', 'id')
                       .values_list('customer_id', 'source', 'body')
                       .iterator(chunk_size=500))
        current_mirror = next(mirror_rows, None)
        old_hash = hashlib.sha256()
        mirror_hash = hashlib.sha256()
        old_count = mirror_count = missing_count = mismatched_count = duplicate_count = 0
        seen_sources = set()

        for customer_id, old_body in old_rows:
            clean_old = _clean(old_body)
            matching_count = wrong_count = 0
            while current_mirror is not None and current_mirror[0] == customer_id:
                _, source, mirror_body = current_mirror
                clean_mirror = _clean(mirror_body)
                if clean_old:
                    mirror_count += 1
                    seen_sources.add(source)
                    _digest_add(mirror_hash, customer_id, clean_mirror)
                    if clean_mirror == clean_old:
                        matching_count += 1
                    else:
                        wrong_count += 1
                elif source == CustomerMemo.SOURCE_LEGACY:
                    mismatched_count += 1
                    seen_sources.add(source)
                current_mirror = next(mirror_rows, None)

            if not clean_old:
                continue
            old_count += 1
            _digest_add(old_hash, customer_id, clean_old)
            if not matching_count and not wrong_count:
                missing_count += 1
            mismatched_count += wrong_count
            duplicate_count += max(0, matching_count - 1)

        result = {
            'duplicate_count': duplicate_count,
            'mismatched_count': mismatched_count,
            'mirror_count': mirror_count,
            'mirror_hash': mirror_hash.hexdigest(),
            'missing_count': missing_count,
            'old_count': old_count,
            'old_hash': old_hash.hexdigest(),
            'sources': sorted(seen_sources),
        }
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
        if (missing_count or mismatched_count or duplicate_count
                or old_count != mirror_count or old_hash.hexdigest() != mirror_hash.hexdigest()):
            raise CommandError('기존 메모 이관 대조가 일치하지 않습니다.')
