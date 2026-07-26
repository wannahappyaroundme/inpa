from celery import shared_task

from .cleanup import delete_recording_source
from .models import ConsultationRecording
from .services import get_recording_storage
from .summary_worker import cancel_summary_run, run_summary_step


@shared_task(
    bind=True,
    name='inpa.consultations.process_summary',
    acks_late=True,
    reject_on_worker_lost=True,
)
def process_consultation_summary(self, run_id):
    result = run_summary_step(run_id)
    if result.retry_after > 0:
        self.apply_async(
            args=[str(run_id)],
            countdown=result.retry_after,
            queue='consultation_summaries',
        )
    return {
        'outcome': result.outcome,
        'retry_after': result.retry_after,
    }


@shared_task(name='inpa.consultations.cancel_customer_summaries')
def cancel_customer_summaries(customer_id, *, reason):
    run_ids = list(
        ConsultationRecording.objects.filter(
            customer_id=customer_id,
            summary_run__status__in=(
                'queued',
                'transcribing',
                'summarizing',
            ),
        ).values_list('summary_run__id', flat=True)
    )
    cancelled = 0
    for run_id in run_ids:
        if cancel_summary_run(run_id, reason=reason) is not None:
            cancelled += 1
    return {'cancelled': cancelled, 'reason': reason}


@shared_task(name='inpa.consultations.delete_exact_sources')
def delete_exact_sources(sources, *, reason):
    """Delete post-cascade sources using exact server-generated keys only."""
    storage = get_recording_storage()
    deleted = 0
    failed = 0
    for source in sources:
        key = source.get('storage_key')
        upload_id = source.get('multipart_upload_id')
        try:
            if upload_id:
                storage.abort(key, upload_id)
            storage.delete(key)
        except Exception:
            failed += 1
        else:
            deleted += 1
    return {'deleted': deleted, 'failed': failed, 'reason': reason}


@shared_task(name='inpa.consultations.delete_customer_sources')
def delete_customer_sources(customer_id, *, reason):
    recording_ids = list(
        ConsultationRecording.objects.filter(
            customer_id=customer_id,
            storage_key__isnull=False,
        ).values_list('id', flat=True)
    )
    deleted = 0
    failed = 0
    for recording_id in recording_ids:
        outcome = delete_recording_source(
            recording_id,
            reason=reason,
        )
        if outcome == 'deleted':
            deleted += 1
        else:
            failed += 1
    return {'deleted': deleted, 'failed': failed, 'reason': reason}
