import logging

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from inpa.insurances.import_storage import delete_source
from inpa.insurances.import_services import _publish_job
from inpa.insurances.models import InsuranceExtractionJob
from inpa.insurances.tasks import (
    MAX_LEASE_ATTEMPTS,
    _delete_terminal_source,
    _fail_queued_job,
    _lock_job_row,
    _lock_owner_row,
    _terminalize_locked_attempt,
)


logger = logging.getLogger(__name__)


def _lock_cleanup_job(job_id, owner_id):
    """Canonical owner -> job locking for retention state changes."""
    try:
        _lock_owner_row(owner_id)
    except get_user_model().DoesNotExist:
        return None
    job = _lock_job_row(job_id)
    if job is None or job.owner_id != owner_id:
        return None
    return job


def _credit_is_pending_refund(job):
    summary = job.validation_summary
    system = summary.get('_system', {}) if isinstance(summary, dict) else {}
    return bool(
        system.get('credit_consumed')
        and not system.get('credit_refunded')
    )


def _source_deleted_count(job_id):
    return int(
        InsuranceExtractionJob.objects.filter(
            pk=job_id,
            source_deleted_at__isnull=False,
        ).exists()
    )


def _recover_expired_leases(now, *, _terminal_barrier=None):
    recovered = 0
    failed = 0
    candidates = list(
        InsuranceExtractionJob.objects.filter(
            status__in=('extracting', 'validating'),
            lease_expires_at__lte=now,
        ).values_list('pk', 'owner_id')
    )
    for job_id, owner_id in candidates:
        terminal_source = None
        with transaction.atomic():
            job = _lock_cleanup_job(job_id, owner_id)
            if (job is None
                    or job.status not in ('extracting', 'validating')
                    or job.lease_expires_at is None
                    or job.lease_expires_at > now):
                continue
            source_is_live = bool(
                job.source_storage_key
                and job.source_deleted_at is None
                and job.source_expires_at is not None
                and job.source_expires_at > now
            )
            if source_is_live and job.attempt_count < MAX_LEASE_ATTEMPTS:
                updated = InsuranceExtractionJob.objects.filter(
                    pk=job.pk,
                    status=job.status,
                    attempt_uuid=job.attempt_uuid,
                    lease_expires_at__lte=now,
                ).update(
                    status='queued',
                    attempt_uuid=None,
                    lease_expires_at=None,
                    lease_expired_count=F('lease_expired_count') + 1,
                    error_code='',
                    error_type='',
                )
                if updated == 1:
                    refund_credit = _credit_is_pending_refund(job)
                    transaction.on_commit(
                        lambda queued_id=str(job.pk),
                        refund=refund_credit: _publish_job(
                            queued_id, refund_credit=refund)
                    )
                    recovered += 1
                continue
            attempt_uuid = job.attempt_uuid
            code = (
                'LEASE_RETRY_EXHAUSTED'
                if job.attempt_count >= MAX_LEASE_ATTEMPTS
                else 'SOURCE_EXPIRED'
            )
            source_key = _terminalize_locked_attempt(
                job,
                attempt_uuid,
                code=code,
                error_type='lease_expired',
                increment_lease_expired=True,
            )
            # Deterministic race seam: the attempt is already invalidated in
            # this first owner->job transaction before a late save can run.
            if _terminal_barrier is not None:
                _terminal_barrier(job.pk, attempt_uuid)
            terminal_source = (job.pk, source_key)
            failed += 1
        if terminal_source is not None:
            _delete_terminal_source(*terminal_source)
    return recovered, failed


def _delete_expired_sources(now):
    deleted = 0
    candidates = list(
        InsuranceExtractionJob.objects.filter(
            source_expires_at__lte=now,
            source_deleted_at__isnull=True,
        ).filter(
            Q(lease_expires_at__isnull=True)
            | Q(lease_expires_at__lte=now)
        ).values_list('pk', 'owner_id', 'status')
    )
    for job_id, owner_id, candidate_status in candidates:
        if candidate_status == 'queued':
            failed = _fail_queued_job(
                job_id,
                code='SOURCE_EXPIRED',
                error_type='source_expired',
            )
            if failed:
                deleted += _source_deleted_count(job_id)
                continue

        queued_after_lock = False
        with transaction.atomic():
            job = _lock_cleanup_job(job_id, owner_id)
            if (job is None
                    or job.source_expires_at is None
                    or job.source_expires_at > now
                    or job.source_deleted_at is not None
                    or (job.lease_expires_at is not None
                        and job.lease_expires_at > now)):
                continue
            if job.status == 'queued':
                queued_after_lock = True
            else:
                source_key = job.source_storage_key
                if not source_key:
                    continue
                try:
                    # Keep the row lock through the exact-key storage
                    # operation so no new worker lease can appear between the
                    # final guard and deletion. Prefix deletion is never used.
                    delete_source(job, key=source_key)
                except Exception as exc:
                    logger.warning(
                        'insurance import retention cleanup failed '
                        'job=%s type=%s',
                        job.pk, type(exc).__name__)
                    continue
                marked = InsuranceExtractionJob.objects.filter(
                    pk=job.pk,
                    source_storage_key=source_key,
                    source_expires_at__lte=now,
                    source_deleted_at__isnull=True,
                ).filter(
                    Q(lease_expires_at__isnull=True)
                    | Q(lease_expires_at__lte=now)
                ).update(source_deleted_at=now)
                deleted += int(marked == 1)
        if queued_after_lock:
            failed = _fail_queued_job(
                job_id,
                code='SOURCE_EXPIRED',
                error_type='source_expired',
            )
            if failed:
                deleted += _source_deleted_count(job_id)
    return deleted


def cleanup_imports(*, now=None, _terminal_barrier=None):
    now = now or timezone.now()
    recovered, failed = _recover_expired_leases(
        now, _terminal_barrier=_terminal_barrier)
    deleted = _delete_expired_sources(now)
    return {'recovered': recovered, 'failed': failed, 'deleted': deleted}


class Command(BaseCommand):
    help = '만료된 증권 작업 lease와 정확한 임시 원본만 정리합니다.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--now',
            help='테스트/운영 복구용 ISO 시각. 생략하면 현재 시각을 사용합니다.',
        )

    def handle(self, *args, **options):
        value = options.get('now')
        now = timezone.now()
        if value:
            now = parse_datetime(value)
            if now is None:
                raise CommandError('--now는 ISO 시각이어야 합니다.')
            if timezone.is_naive(now):
                now = timezone.make_aware(now)
        result = cleanup_imports(now=now)
        self.stdout.write(
            'insurance import cleanup '
            f"recovered={result['recovered']} "
            f"failed={result['failed']} deleted={result['deleted']}"
        )
