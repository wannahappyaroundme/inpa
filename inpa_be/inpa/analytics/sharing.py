import uuid
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import prefetch_related_objects
from django.utils import timezone

from inpa.customers.consent_texts import (
    CONSENT_TEXTS_VERSION, has_current_overseas_consent,
)
from inpa.customers.models import ConsentLog, Customer
from inpa.insurances.models import CustomerInsurance

from .models import NorthStarEvent, ShareSnapshot


PAYLOAD_VERSION_V2 = 'v2-immutable-analysis'
PAYLOAD_VERSION_V1 = 'v1-legacy-actions'
SHARE_LINK_DAYS = 90


class ShareNotReady(Exception):
    pass


def _current_consent_scopes(customer):
    return list(
        ConsentLog.objects.filter(
            customer=customer,
            subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
            revoked_at__isnull=True,
        ).values_list('scope', flat=True).distinct()
    )


def _current_dict_version():
    from inpa.analysis.models import SeedMarker
    live = (SeedMarker.objects.filter(key='seed_normalization')
            .values_list('version', flat=True).first())
    if live:
        return live
    try:
        from inpa.analysis.management.commands.seed_normalization import SEED_VERSION
        return SEED_VERSION
    except Exception:
        return ''


def _retention_deadline(now):
    days = int(getattr(settings, 'SHARE_SNAPSHOT_RETENTION_DAYS', 180) or 0)
    if days <= 0:
        days = 180
    return now + timedelta(days=days)


def assert_shareable(customer):
    review_state = customer.customer_insurance_list.analysis_review_state()
    # Customers without any held policy can still share the empty diagnosis
    # frame. Once a held policy exists, at least one analysis-ready policy is
    # required so drafts/exclusions never become customer-facing material.
    if (not review_state['can_share']
            and (settings.INSURANCE_REVIEW_GATE_ENABLED
                 or review_state['total_insurance_count'] > 0)):
        raise ShareNotReady(review_state['share_block_reason'])
    return review_state


@transaction.atomic
def create_share_snapshot(*, customer_id, owner, payload_builder):
    customer = (Customer.objects.select_for_update(of=('self',)).select_related('owner__profile')
                .get(pk=customer_id, owner=owner))
    list(
        CustomerInsurance.objects.select_for_update()
        .filter(customer=customer)
        .order_by('pk')
    )
    review_state = assert_shareable(customer)
    ready_insurances = list(
        review_state['ready_queryset'].order_by('pk'))
    prefetch_related_objects(
        ready_insurances,
        'case_list__detail__analysis_detail',
        'case_list__analysis_detail_override',
        'case_list__detail__chart_detail',
    )

    payload = payload_builder(
        customer,
        include_live_actions=False,
        insurance_list=ready_insurances,
    )
    now = timezone.now()
    ShareSnapshot.objects.filter(
        customer=customer,
        share_token__isnull=False,
        revoked_at__isnull=True,
    ).update(revoked_at=now, revoked_reason='reissued')

    token = uuid.uuid4()
    link_expires_at = now + timedelta(days=SHARE_LINK_DAYS)
    snapshot = ShareSnapshot.objects.create(
        owner=owner,
        customer=customer,
        share_token=token,
        payload_version=PAYLOAD_VERSION_V2,
        payload=payload,
        consent_overseas=has_current_overseas_consent(customer),
        consent_doc_version=CONSENT_TEXTS_VERSION,
        consent_scopes=_current_consent_scopes(customer),
        dict_version=_current_dict_version(),
        insurance_count=len(ready_insurances),
        link_expires_at=link_expires_at,
        retention_expires_at=_retention_deadline(now),
    )

    profile = getattr(owner, 'profile', None)
    ref_code = getattr(profile, 'ref_code', None)
    NorthStarEvent.objects.create(
        event_type=NorthStarEvent.SHARE_CREATED,
        customer=customer,
        sender=owner,
        share_token=token,
        ref_code=ref_code or None,
        channel='web',
        payload={'customer_id': customer.id, 'ttl_days': SHARE_LINK_DAYS,
                 'snapshot_id': snapshot.id},
    )

    customer.share_token = token
    customer.share_sent_at = now
    customer.share_expires_at = link_expires_at
    customer.save(update_fields=(
        'share_token', 'share_sent_at', 'share_expires_at'))
    return snapshot
