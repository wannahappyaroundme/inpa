from django.db import transaction
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from inpa.customers.models import Customer

from .tasks import delete_exact_sources


@receiver(pre_delete, sender=Customer)
def delete_consultation_sources_with_customer(sender, instance, **kwargs):
    sources = list(
        instance.consultation_recordings.exclude(
            storage_key__isnull=True,
        ).values('storage_key', 'multipart_upload_id')
    )
    if sources:
        transaction.on_commit(
            lambda values=sources: delete_exact_sources.delay(
                values,
                reason='customer_deleted',
            ),
        )

