"""카드 등록, 무료 시작 동의, 약정 상태 전이."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.db import transaction
from django.utils import timezone

from inpa.analytics.events import log_billing_event
from inpa.analytics.models import NorthStarEvent

from .calendar import new_anchor, period_for
from .coupons import CouponError, redeem_held_coupon
from .kicc import (
    KiccBillingClient,
    KiccIntegrityError,
    KiccProviderDeclined,
)
from .legal_texts import (
    FIRST_CHARGE_CONSENT,
    FIRST_CHARGE_CONSENT_VERSION,
    INITIAL_BILLING_CONSENT,
    INITIAL_BILLING_CONSENT_VERSION,
)
from .models import (
    BillingAgreement,
    CouponClaim,
    PaymentMethodToken,
    RecurringPaymentConsent,
)
from .payment_tokens import encrypt_billing_token

User = get_user_model()
_KST = ZoneInfo('Asia/Seoul')
_STATE_SALT = 'inpa.billing.card-registration.v1'
_STATE_MAX_AGE_SECONDS = 20 * 60


class BillingFlowError(RuntimeError):
    def __init__(self, code, detail, *, status_code=400):
        self.code = code
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


@dataclass(frozen=True)
class DateTimeRange:
    opens_at: datetime
    closes_at: datetime


def vat_inclusive_amount(base_amount):
    return int(
        (Decimal(int(base_amount)) * Decimal('1.1'))
        .quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    )


def _snapshot_hash(payload):
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _live_claim(user, claim_id, *, lock=False):
    queryset = CouponClaim.objects.select_related('coupon__plan')
    if lock:
        queryset = queryset.select_for_update()
    try:
        claim = queryset.get(pk=claim_id, user=user)
    except (CouponClaim.DoesNotExist, ValueError):
        raise BillingFlowError(
            'claim_not_found',
            '쿠폰을 다시 확인해 주세요.',
            status_code=404,
        )
    if claim.status == 'redeemed':
        return claim
    if claim.status != 'held' or claim.expires_at <= timezone.now():
        if claim.status == 'held':
            claim.status = 'expired'
            claim.save(update_fields=['status'])
        raise BillingFlowError(
            'claim_expired',
            '쿠폰을 다시 확인하면 카드 등록을 이어갈 수 있어요.',
            status_code=410,
        )
    return claim


def _local_midnight(local_date):
    return timezone.make_aware(
        datetime.combine(local_date, time.min),
        timezone=_KST,
    )


def reconfirmation_window(agreement):
    if not agreement.next_charge_date:
        raise BillingFlowError(
            'charge_date_missing',
            '결제 날짜를 다시 확인해 주세요.',
            status_code=409,
        )
    lead_days = 7 if agreement.trial_duration_months == 1 else 30
    return DateTimeRange(
        opens_at=_local_midnight(
            agreement.next_charge_date - timedelta(days=lead_days)),
        closes_at=_local_midnight(agreement.next_charge_date),
    )


def _active_token(agreement, *, lock=False):
    queryset = PaymentMethodToken.objects.filter(
        agreement=agreement,
        status='active',
    )
    if lock:
        queryset = queryset.select_for_update()
    token = queryset.first()
    if not token:
        raise BillingFlowError(
            'card_required',
            '카드를 등록하면 첫 결제 내용을 확인할 수 있어요.',
            status_code=409,
        )
    return token


def reconfirmation_snapshot(agreement, *, amount_krw=None):
    token = _active_token(agreement)
    return {
        'consent_version': FIRST_CHARGE_CONSENT_VERSION,
        'title': FIRST_CHARGE_CONSENT['title'],
        'items': FIRST_CHARGE_CONSENT['items'],
        'plan_code': agreement.plan.code,
        'amount_krw': (
            vat_inclusive_amount(agreement.plan.price_krw)
            if amount_krw is None else int(amount_krw)
        ),
        'charge_date': agreement.next_charge_date.isoformat(),
        'card_label': token.display_label,
        'cancel_path': '/settings/billing',
        'cancel_effect': agreement.current_period_ends_on.isoformat(),
    }


def has_current_reconfirmation(
    agreement,
    charge_date,
    amount_krw,
):
    if not charge_date or agreement.next_charge_date != charge_date:
        return False
    try:
        snapshot = reconfirmation_snapshot(
            agreement, amount_krw=amount_krw)
    except BillingFlowError:
        return False
    return RecurringPaymentConsent.objects.filter(
        agreement=agreement,
        kind='first_charge',
        consent_version=FIRST_CHARGE_CONSENT_VERSION,
        plan_code=snapshot['plan_code'],
        amount_krw=snapshot['amount_krw'],
        charge_date=charge_date,
        card_label=snapshot['card_label'],
        cancel_path=snapshot['cancel_path'],
        cancel_effect=agreement.current_period_ends_on,
        display_snapshot_hash=_snapshot_hash(snapshot),
    ).exists()


def confirm_first_charge(
    *,
    user,
    consent_version,
    network_hmac='',
    user_agent_hash='',
):
    if consent_version != FIRST_CHARGE_CONSENT_VERSION:
        raise BillingFlowError(
            'consent_version_changed',
            '최신 결제 내용을 확인해 주세요.',
            status_code=409,
        )
    with transaction.atomic():
        agreement = (
            BillingAgreement.objects.select_for_update()
            .select_related('plan')
            .filter(user=user)
            .first()
        )
        if not agreement:
            raise BillingFlowError(
                'agreement_not_found',
                '결제 정보를 다시 확인해 주세요.',
                status_code=404,
            )
        if agreement.status != 'trialing':
            raise BillingFlowError(
                'reconfirmation_not_required',
                '현재 이용 중인 결제 정보를 확인해 주세요.',
                status_code=409,
            )
        token = _active_token(agreement, lock=True)
        window = reconfirmation_window(agreement)
        now = timezone.now()
        if now < window.opens_at:
            raise BillingFlowError(
                'reconfirmation_not_open',
                '확인 시작일이 되면 결제 내용을 확인할 수 있어요.',
                status_code=409,
            )
        if now >= window.closes_at:
            raise BillingFlowError(
                'reconfirmation_closed',
                '현재 이용 상태를 확인한 뒤 결제를 다시 설정해 주세요.',
                status_code=410,
            )
        snapshot = {
            **reconfirmation_snapshot(agreement),
            'card_label': token.display_label,
        }
        consent, created = RecurringPaymentConsent.objects.get_or_create(
            agreement=agreement,
            kind='first_charge',
            charge_date=agreement.next_charge_date,
            display_snapshot_hash=_snapshot_hash(snapshot),
            defaults={
                'consent_version': FIRST_CHARGE_CONSENT_VERSION,
                'plan_code': snapshot['plan_code'],
                'amount_krw': snapshot['amount_krw'],
                'card_label': snapshot['card_label'],
                'cancel_path': snapshot['cancel_path'],
                'cancel_effect': agreement.current_period_ends_on,
                'accepted_at': now,
                'network_hmac': network_hmac,
                'user_agent_hash': user_agent_hash,
            },
        )
        if created:
            days_before = max(
                (agreement.next_charge_date - timezone.localdate()).days,
                0,
            )
            transaction.on_commit(
                lambda user=agreement.user, days=days_before:
                    log_billing_event(
                        NorthStarEvent.BILLING_RECONFIRMATION_ACCEPTED,
                        sender=user,
                        payload={'days_before': days},
                    )
            )
        return consent, snapshot


def _state_payload(agreement, claim, order_id, consent_version):
    return {
        'user_id': claim.user_id,
        'claim_id': str(claim.id),
        'agreement_id': str(agreement.id),
        'shop_order_no': order_id,
        'consent_version': consent_version,
    }


def _sign_state(payload):
    return signing.dumps(payload, salt=_STATE_SALT, compress=True)


def _read_state(raw_state):
    try:
        return signing.loads(
            raw_state,
            salt=_STATE_SALT,
            max_age=_STATE_MAX_AGE_SECONDS,
        )
    except signing.SignatureExpired as exc:
        raise BillingFlowError(
            'registration_expired',
            '쿠폰을 다시 확인하면 카드 등록을 이어갈 수 있어요.',
            status_code=410,
        ) from exc
    except signing.BadSignature as exc:
        raise BillingFlowError(
            'registration_invalid',
            '카드 등록을 다시 시작해 주세요.',
            status_code=400,
        ) from exc


def start_card_registration(
    *,
    user,
    claim_id,
    consent_version,
    device_type='mobile',
    client=None,
):
    if consent_version != INITIAL_BILLING_CONSENT_VERSION:
        raise BillingFlowError(
            'consent_version_changed',
            '최신 내용을 확인하면 카드 등록을 이어갈 수 있어요.',
            status_code=409,
        )
    today = timezone.localdate()
    with transaction.atomic():
        claim = _live_claim(user, claim_id, lock=True)
        if claim.status == 'redeemed':
            agreement = BillingAgreement.objects.filter(
                user=user, coupon_claim=claim).first()
            if agreement:
                return {
                    'already_complete': True,
                    'agreement': agreement,
                }
        coupon = claim.coupon
        period = period_for(
            today,
            coupon.duration_months,
            anchor_day=new_anchor(today),
        )
        agreement, _ = BillingAgreement.objects.select_for_update().get_or_create(
            user=user,
            defaults={
                'plan': coupon.plan,
                'coupon_claim': claim,
                'status': 'trialing',
                'billing_anchor_day': new_anchor(today),
                'trial_duration_months': coupon.duration_months,
                'current_period_starts_on': period.starts_on,
                'current_period_ends_on': period.access_through,
                'next_charge_date': period.next_charge_date,
            },
        )
        agreement.plan = coupon.plan
        agreement.coupon_claim = claim
        agreement.status = 'trialing'
        agreement.billing_anchor_day = new_anchor(today)
        agreement.trial_duration_months = coupon.duration_months
        agreement.current_period_starts_on = period.starts_on
        agreement.current_period_ends_on = period.access_through
        agreement.next_charge_date = period.next_charge_date
        agreement.canceled_at = None
        agreement.save(update_fields=[
            'plan',
            'coupon_claim',
            'status',
            'billing_anchor_day',
            'trial_duration_months',
            'current_period_starts_on',
            'current_period_ends_on',
            'next_charge_date',
            'canceled_at',
            'updated_at',
        ])
        order_id = f'INPA-BK-{claim.id.hex}'
        state = _sign_state(_state_payload(
            agreement, claim, order_id, consent_version))

    query = urlencode({'state': state})
    return_url = (
        f"{settings.BACKEND_BASE_URL.rstrip('/')}"
        f'/api/v1/billing/card-registration/provider-return/?{query}'
    )
    registration = (client or KiccBillingClient()).start_registration(
        order_id=order_id,
        return_url=return_url,
        device_type=device_type,
    )
    log_billing_event(
        NorthStarEvent.BILLING_CARD_REGISTRATION_STARTED,
        sender=user,
        payload={'plan_code': agreement.plan.code},
        dedupe_hours=1,
    )
    return {
        'already_complete': False,
        'auth_page_url': registration.auth_page_url,
        'state': state,
        'shop_order_no': order_id,
        'claim_expires_at': claim.expires_at,
        'access_through': agreement.current_period_ends_on,
        'next_charge_date': agreement.next_charge_date,
        'amount_krw': vat_inclusive_amount(agreement.plan.price_krw),
    }


def _provider_request_id(order_id, authorization_id):
    digest = hashlib.sha256(
        f'{order_id}|{authorization_id}'.encode()).hexdigest()[:32]
    return f'INPA-BK-{digest}'


def _trial_consent_payload(agreement, card_label):
    return {
        'version': INITIAL_BILLING_CONSENT_VERSION,
        'title': INITIAL_BILLING_CONSENT['title'],
        'items': INITIAL_BILLING_CONSENT['items'],
        'plan_code': agreement.plan.code,
        'amount_krw': vat_inclusive_amount(agreement.plan.price_krw),
        'charge_date': agreement.next_charge_date.isoformat(),
        'access_through': agreement.current_period_ends_on.isoformat(),
        'card_label': card_label,
        'cancel_path': '/settings/billing',
    }


def enqueue_token_revocation(token_id):
    from .tasks import revoke_payment_token_task
    revoke_payment_token_task.delay(token_id)


def _record_pending_revocation(agreement_id, issue):
    encrypted = encrypt_billing_token(issue.billing_key)
    token = PaymentMethodToken.objects.create(
        agreement_id=agreement_id,
        encrypted_token=encrypted.ciphertext,
        key_version=encrypted.key_version,
        card_brand=issue.card_brand,
        card_last4=issue.card_last4,
        status='revocation_pending',
    )
    transaction.on_commit(
        lambda: enqueue_token_revocation(token.pk))
    return token


def complete_card_registration(
    *,
    raw_state,
    authorization_id,
    shop_order_no,
    user=None,
    client=None,
):
    payload = _read_state(raw_state)
    if shop_order_no != payload.get('shop_order_no'):
        raise BillingFlowError(
            'registration_order_mismatch',
            '카드 등록을 다시 시작해 주세요.',
            status_code=400,
        )
    state_user = User.objects.filter(pk=payload.get('user_id')).first()
    if not state_user or (user is not None and state_user.pk != user.pk):
        raise BillingFlowError(
            'registration_not_found',
            '카드 등록을 다시 시작해 주세요.',
            status_code=404,
        )
    claim_id = payload.get('claim_id')
    agreement_id = payload.get('agreement_id')

    with transaction.atomic():
        claim = _live_claim(state_user, claim_id, lock=True)
        agreement = BillingAgreement.objects.select_for_update().filter(
            pk=agreement_id,
            user=state_user,
            coupon_claim=claim,
        ).first()
        if not agreement:
            raise BillingFlowError(
                'registration_not_found',
                '카드 등록을 다시 시작해 주세요.',
                status_code=404,
            )
        existing_token = PaymentMethodToken.objects.filter(
            agreement=agreement,
            status='active',
        ).first()
        if claim.status == 'redeemed' and existing_token:
            return agreement

    request_id = _provider_request_id(
        shop_order_no, authorization_id)
    provider = client or KiccBillingClient()
    try:
        issue = provider.issue_key(
            auth_id=authorization_id,
            order_id=shop_order_no,
            request_id=request_id,
        )
    except KiccProviderDeclined as exc:
        raise BillingFlowError(
            'card_registration_declined',
            '카드 정보를 확인하고 다시 등록해 주세요.',
            status_code=422,
        ) from exc
    except (KiccIntegrityError, OSError) as exc:
        raise BillingFlowError(
            'card_registration_unknown',
            '결제 상태를 확인하고 있어요. 잠시 뒤 다시 확인해 주세요.',
            status_code=503,
        ) from exc

    try:
        with transaction.atomic():
            claim = _live_claim(state_user, claim_id, lock=True)
            agreement = (
                BillingAgreement.objects.select_for_update()
                .select_related('plan')
                .get(
                    pk=agreement_id,
                    user=state_user,
                    coupon_claim=claim,
                )
            )
            if PaymentMethodToken.objects.filter(
                    agreement=agreement, status='active').exists():
                raise BillingFlowError(
                    'registration_already_complete',
                    '카드 등록이 완료됐어요.',
                    status_code=409,
                )
            encrypted = encrypt_billing_token(issue.billing_key)
            token = PaymentMethodToken.objects.create(
                agreement=agreement,
                encrypted_token=encrypted.ciphertext,
                key_version=encrypted.key_version,
                card_brand=issue.card_brand,
                card_last4=issue.card_last4,
                status='active',
            )
            consent_payload = _trial_consent_payload(
                agreement, token.display_label)
            RecurringPaymentConsent.objects.get_or_create(
                agreement=agreement,
                kind='trial_start',
                charge_date=agreement.next_charge_date,
                display_snapshot_hash=_snapshot_hash(consent_payload),
                defaults={
                    'consent_version':
                        INITIAL_BILLING_CONSENT_VERSION,
                    'plan_code': agreement.plan.code,
                    'amount_krw': consent_payload['amount_krw'],
                    'card_label': token.display_label,
                    'cancel_path': '/settings/billing',
                    'cancel_effect':
                        agreement.current_period_ends_on,
                    'accepted_at': timezone.now(),
                },
            )
            redeem_held_coupon(claim, agreement)
            agreement.status = 'trialing'
            agreement.save(update_fields=['status', 'updated_at'])
            return agreement
    except Exception:
        _record_pending_revocation(agreement_id, issue)
        raise


def billing_status(user):
    agreement = (
        BillingAgreement.objects
        .select_related('plan')
        .filter(user=user)
        .first()
    )
    if not agreement:
        return {
            'state': 'free',
            'existing_data_available': True,
        }
    token = (
        PaymentMethodToken.objects.filter(
            agreement=agreement,
            status__in=('active', 'revocation_pending'),
        )
        .order_by('status', '-created_at')
        .first()
    )
    if agreement.status == 'free':
        return {
            'state': 'free',
            'existing_data_available': True,
        }
    state_map = {
        'trialing': 'trial',
        'active': 'active',
        'renewal_processing': 'renewal_processing',
        'past_due_unknown': 'past_due_unknown',
        'canceled': 'canceled',
    }
    response = {
        'state': state_map.get(agreement.status, 'free'),
        'plan_code': agreement.plan.code,
        'plan_display_name': agreement.plan.display_name,
        'access_through':
            agreement.current_period_ends_on.isoformat(),
        'next_charge_date': (
            agreement.next_charge_date.isoformat()
            if agreement.next_charge_date else None
        ),
        'amount_krw': vat_inclusive_amount(
            agreement.plan.price_krw),
        'card_label': token.display_label if token else None,
        'reconfirmation_required': False,
        'existing_data_available': True,
    }
    if agreement.status == 'trialing' and token:
        window = reconfirmation_window(agreement)
        amount_krw = response['amount_krw']
        now = timezone.now()
        response['reconfirmation_opens_on'] = (
            timezone.localdate(window.opens_at).isoformat())
        response['reconfirmation_required'] = (
            window.opens_at <= now < window.closes_at
            and not has_current_reconfirmation(
                agreement,
                agreement.next_charge_date,
                amount_krw,
            )
        )
    return response
