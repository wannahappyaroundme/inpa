"""무료 전환 안내를 여러 기기에서 한 번만 표시한다."""

from datetime import timedelta
import hashlib
import hmac

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import BillingNoticeEvent


class NoticeError(RuntimeError):
    pass


_NOTICE_COPY = {
    'reconfirmation_missing': {
        'title': '무료 요금제로 전환됐어요',
        'body': (
            '고객 기록은 그대로 이용할 수 있어요. '
            '결제를 다시 설정하면 Plus 이용을 이어갈 수 있어요.'
        ),
        'action_label': '결제 다시 설정',
    },
    'payment_method_missing': {
        'title': '결제 정보를 다시 확인해 주세요',
        'body': (
            '고객 기록은 그대로 이용할 수 있어요. '
            '카드를 등록하면 Plus 이용을 다시 시작할 수 있어요.'
        ),
        'action_label': '카드 등록하기',
    },
    'payment_declined': {
        'title': '카드 결제를 확인해 주세요',
        'body': (
            '지금은 무료 요금제로 고객 기록을 계속 관리할 수 있어요. '
            '결제 메뉴에서 Plus를 다시 시작할 수 있어요.'
        ),
        'action_label': '결제 확인하기',
    },
    'payment_unknown': {
        'title': '결제 상태 확인이 끝났어요',
        'body': (
            '지금은 무료 요금제로 고객 기록을 계속 관리할 수 있어요. '
            '결제 메뉴에서 Plus를 다시 시작할 수 있어요.'
        ),
        'action_label': '결제 확인하기',
    },
    'late_approval_canceled': {
        'title': '늦게 확인된 결제를 취소했어요',
        'body': (
            '고객 기록은 그대로 이용할 수 있어요. '
            '결제 메뉴에서 Plus를 다시 시작할 수 있어요.'
        ),
        'action_label': '결제 확인하기',
    },
    'cancellation_expired': {
        'title': '예약한 이용 기간이 끝났어요',
        'body': (
            '무료 요금제로 고객 기록을 계속 관리할 수 있어요. '
            '필요할 때 Plus를 다시 시작해 보세요.'
        ),
        'action_label': '요금제 보기',
    },
}


def _device_hash(device_id):
    return hmac.new(
        settings.SECRET_KEY.encode(),
        str(device_id).encode(),
        hashlib.sha256,
    ).hexdigest()


def lease_notice(user, device_id):
    now = timezone.now()
    with transaction.atomic():
        notice = (
            BillingNoticeEvent.objects.select_for_update(skip_locked=True)
            .filter(
                user=user,
                rendered_at__isnull=True,
                dismissed_at__isnull=True,
            )
            .filter(
                Q(lease_until__isnull=True)
                | Q(lease_until__lt=now)
            )
            .order_by('created_at')
            .first()
        )
        if not notice:
            return None
        notice.lease_device_hash = _device_hash(device_id)
        notice.lease_until = now + timedelta(minutes=2)
        notice.save(update_fields=[
            'lease_device_hash',
            'lease_until',
        ])
        return notice


def notice_payload(notice):
    copy = _NOTICE_COPY.get(
        notice.reason,
        {
            'title': '이용 상태가 변경됐어요',
            'body': (
                '고객 기록은 그대로 이용할 수 있어요. '
                '결제 메뉴에서 현재 상태를 확인해 주세요.'
            ),
            'action_label': '현재 상태 보기',
        },
    )
    return {
        'id': notice.pk,
        'type': notice.notice_type,
        **copy,
        'action_path': '/settings/billing',
        'existing_data_available': True,
    }


def mark_notice_rendered(user, notice_id, device_id):
    now = timezone.now()
    with transaction.atomic():
        notice = BillingNoticeEvent.objects.select_for_update().filter(
            pk=notice_id,
            user=user,
        ).first()
        if not notice:
            raise NoticeError('NOTICE_NOT_FOUND')
        if notice.rendered_at:
            return notice
        if (
            notice.lease_device_hash != _device_hash(device_id)
            or not notice.lease_until
            or notice.lease_until < now
        ):
            raise NoticeError('NOTICE_LEASE_NOT_FOUND')
        notice.rendered_at = now
        notice.save(update_fields=['rendered_at'])
        return notice


def dismiss_notice(user, notice_id):
    with transaction.atomic():
        notice = BillingNoticeEvent.objects.select_for_update().filter(
            pk=notice_id,
            user=user,
            rendered_at__isnull=False,
        ).first()
        if not notice:
            raise NoticeError('NOTICE_NOT_FOUND')
        if not notice.dismissed_at:
            notice.dismissed_at = timezone.now()
            notice.save(update_fields=['dismissed_at'])
        return notice
