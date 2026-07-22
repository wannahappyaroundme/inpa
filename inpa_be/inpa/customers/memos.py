"""고객 상담 메모의 생성·수정 규칙.

수정·삭제는 접촉 사실이 아니므로 Customer.last_contacted_at을 바꾸지 않는다.
"""
from django.db import transaction
from django.utils import timezone

from .models import Customer, CustomerMemo


MAX_MEMO_BODY_LENGTH = 10_000


def _clean_body(body):
    clean = body.strip()
    if not clean:
        raise ValueError('EMPTY_MEMO')
    if len(clean) > MAX_MEMO_BODY_LENGTH:
        raise ValueError('MEMO_BODY_TOO_LONG')
    return clean


def _schedule_memo_event(event_type, memo):
    """주 트랜잭션이 확정된 뒤에만 개인정보 없는 메모 이벤트를 적재한다."""
    customer_id = memo.customer_id
    sender_id = memo.owner_id
    source = memo.source
    from inpa.analytics.events import log_event

    def record():
        log_event(event_type, customer_id=customer_id, sender_id=sender_id,
                  payload={'source': source})

    transaction.on_commit(record, robust=True)


def bump_last_contacted_at(customer_id, at):
    """기존 시각보다 새 접촉 시각이 늦을 때만 고객의 접촉 시각을 갱신한다."""
    with transaction.atomic():
        customer = Customer.objects.select_for_update().get(pk=customer_id)
        if customer.last_contacted_at is None or customer.last_contacted_at < at:
            customer.last_contacted_at = at
            customer.save(update_fields=['last_contacted_at'])


def create_manual_memo(*, customer, owner, body, is_legacy_mirror=False):
    """직접 작성 메모를 만들고, 성공한 생성만 접촉 시각에 반영한다."""
    clean = _clean_body(body)
    now = timezone.now()
    with transaction.atomic():
        memo = CustomerMemo.objects.create(
            owner=owner,
            customer=customer,
            source=CustomerMemo.SOURCE_MANUAL,
            body=clean,
            is_legacy_mirror=is_legacy_mirror,
            occurred_at=now,
        )
        bump_last_contacted_at(customer.id, now)
        from inpa.analytics.models import NorthStarEvent
        _schedule_memo_event(NorthStarEvent.CONSULTATION_MEMO_CREATED, memo)
    return memo


def update_memo(*, memo, body, expected_revision):
    """낙관적 잠금으로 본문을 수정한다. 같은 본문은 버전을 올리지 않는다."""
    clean = _clean_body(body)
    with transaction.atomic():
        customer = Customer.objects.select_for_update().get(pk=memo.customer_id)
        locked = CustomerMemo.objects.select_for_update().get(
            pk=memo.pk, customer=customer)
        if locked.revision != expected_revision:
            raise ValueError('MEMO_EDIT_CONFLICT')
        if locked.is_legacy_mirror and customer.memo != clean:
            customer.memo = clean
            customer.save(update_fields=['memo', 'updated_at'])
        if locked.body != clean:
            locked.body = clean
            locked.revision += 1
            locked.edited_at = timezone.now()
            locked.save(update_fields=['body', 'revision', 'edited_at', 'updated_at'])
            from inpa.analytics.models import NorthStarEvent
            _schedule_memo_event(NorthStarEvent.CONSULTATION_MEMO_EDITED, locked)
        return locked


def delete_memo(*, memo):
    """메모를 삭제하고, 호환 행이면 구버전 단일 필드도 같은 트랜잭션에서 비운다."""
    with transaction.atomic():
        customer = Customer.objects.select_for_update().get(pk=memo.customer_id)
        locked = CustomerMemo.objects.select_for_update().get(
            pk=memo.pk, customer=customer)
        if locked.is_legacy_mirror and customer.memo:
            customer.memo = ''
            customer.save(update_fields=['memo', 'updated_at'])
        locked.delete()


def sync_legacy_memo(*, customer, owner, body, source):
    """구버전 단일 메모 필드와 대응 상담 메모를 한 트랜잭션으로 맞춘다.

    반환값의 두 번째 값은 실제 메모 행 변경에 따른 계측 종류(`created`/`edited`)다.
    구버전 PATCH는 legacy 행 하나만, 신규 호환 생성은 Task 2의 직접 작성 서비스를 쓴다.
    """
    if source not in (CustomerMemo.SOURCE_LEGACY, CustomerMemo.SOURCE_MANUAL):
        raise ValueError('UNSUPPORTED_MEMO_SOURCE')
    clean = (body or '').strip()

    with transaction.atomic():
        locked = Customer.objects.select_for_update().get(pk=customer.pk)
        if locked.owner_id != owner.id:
            raise ValueError('MEMO_OWNER_MISMATCH')

        if source == CustomerMemo.SOURCE_MANUAL:
            if not clean:
                return None, None
            clean = _clean_body(body)
            if locked.memo != clean:
                locked.memo = clean
                locked.save(update_fields=['memo', 'updated_at'])
            memo = create_manual_memo(
                customer=locked, owner=owner, body=clean, is_legacy_mirror=True)
            return memo, 'created'

        legacy = (CustomerMemo.objects.select_for_update()
                  .filter(customer=locked, is_legacy_mirror=True)
                  .first())
        if not clean:
            if locked.memo:
                locked.memo = ''
                locked.save(update_fields=['memo', 'updated_at'])
            if legacy is not None:
                legacy.delete()
            return None, None

        if len(clean) > MAX_MEMO_BODY_LENGTH:
            old_matches = (locked.memo or '').strip() == clean
            mirror_matches = legacy is not None and (legacy.body or '').strip() == clean
            if old_matches and mirror_matches:
                return legacy, None
            raise ValueError('MEMO_BODY_TOO_LONG')

        if (locked.memo or '').strip() != clean:
            locked.memo = clean
            locked.save(update_fields=['memo', 'updated_at'])
        if legacy is None:
            memo = CustomerMemo.objects.create(
                owner=owner,
                customer=locked,
                source=CustomerMemo.SOURCE_LEGACY,
                body=clean,
                is_legacy_mirror=True,
            )
            from inpa.analytics.models import NorthStarEvent
            _schedule_memo_event(NorthStarEvent.CONSULTATION_MEMO_CREATED, memo)
            return memo, 'created'
        if (legacy.body or '').strip() != clean:
            legacy.body = clean
            legacy.revision += 1
            legacy.edited_at = timezone.now()
            legacy.save(update_fields=['body', 'revision', 'edited_at', 'updated_at'])
            from inpa.analytics.models import NorthStarEvent
            _schedule_memo_event(NorthStarEvent.CONSULTATION_MEMO_EDITED, legacy)
            return legacy, 'edited'
        return legacy, None
