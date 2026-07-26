"""정기결제 약정·동의·주문·처리 원장.

카드번호와 CVC는 이 모델을 통과하지 않는다. 빌키는 암호문만 저장한다.
"""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class BillingAgreement(models.Model):
    STATUS_CHOICES = [(value, value) for value in (
        'trialing',
        'renewal_processing',
        'active',
        'past_due_unknown',
        'canceled',
        'free',
    )]

    id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='billing_agreement',
    )
    plan = models.ForeignKey(
        'billing.Plan', on_delete=models.PROTECT,
        related_name='billing_agreements')
    coupon_claim = models.OneToOneField(
        'billing.CouponClaim',
        on_delete=models.PROTECT,
        related_name='agreement',
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=24, choices=STATUS_CHOICES, default='trialing')
    billing_anchor_day = models.PositiveSmallIntegerField()
    trial_duration_months = models.PositiveSmallIntegerField(default=1)
    cycle_sequence = models.PositiveIntegerField(default=0)
    current_period_starts_on = models.DateField()
    current_period_ends_on = models.DateField()
    next_charge_date = models.DateField(null=True, blank=True)
    canceled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'billing_agreement'
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    billing_anchor_day__gte=1,
                    billing_anchor_day__lte=31),
                name='billing_anchor_day_1_31'),
            models.CheckConstraint(
                condition=Q(
                    trial_duration_months__gte=1,
                    trial_duration_months__lte=3),
                name='billing_trial_months_1_3'),
        ]


class PaymentMethodToken(models.Model):
    STATUS_CHOICES = [(value, value) for value in (
        'active', 'revocation_pending', 'revoked')]

    agreement = models.ForeignKey(
        BillingAgreement, on_delete=models.CASCADE,
        related_name='payment_tokens')
    encrypted_token = models.TextField()
    key_version = models.CharField(max_length=20)
    card_brand = models.CharField(max_length=40, blank=True, default='')
    card_last4 = models.CharField(max_length=4, blank=True, default='')
    status = models.CharField(
        max_length=24, choices=STATUS_CHOICES, default='active')
    revocation_attempts = models.PositiveSmallIntegerField(default=0)
    last_error_code = models.CharField(
        max_length=40, blank=True, default='')
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'billing_payment_method_token'
        constraints = [
            models.UniqueConstraint(
                fields=['agreement'],
                condition=Q(status='active'),
                name='uniq_billing_active_token'),
        ]

    @property
    def display_label(self):
        brand = self.card_brand.strip() or '카드'
        last4 = self.card_last4 if len(self.card_last4) == 4 else '****'
        return f'{brand} 끝 {last4}'


class RecurringPaymentConsent(models.Model):
    KIND_CHOICES = (
        ('trial_start', 'trial_start'),
        ('first_charge', 'first_charge'),
    )

    agreement = models.ForeignKey(
        BillingAgreement, on_delete=models.PROTECT,
        related_name='payment_consents')
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    consent_version = models.CharField(max_length=40)
    plan_code = models.CharField(max_length=20)
    amount_krw = models.PositiveIntegerField()
    charge_date = models.DateField()
    card_label = models.CharField(max_length=80, blank=True, default='')
    cancel_path = models.CharField(
        max_length=100, default='/settings/billing')
    cancel_effect = models.DateField()
    display_snapshot_hash = models.CharField(max_length=64)
    accepted_at = models.DateTimeField()
    network_hmac = models.CharField(
        max_length=64, blank=True, default='')
    user_agent_hash = models.CharField(
        max_length=64, blank=True, default='')

    class Meta:
        db_table = 'billing_recurring_payment_consent'
        constraints = [
            models.UniqueConstraint(
                fields=[
                    'agreement', 'kind', 'charge_date',
                    'display_snapshot_hash',
                ],
                name='uniq_billing_consent_snapshot'),
        ]


class PaymentOrder(models.Model):
    STATUS_CHOICES = [(value, value) for value in (
        'created',
        'submitted',
        'approved',
        'declined',
        'unknown',
        'canceled',
        'refunded',
    )]

    agreement = models.ForeignKey(
        BillingAgreement, on_delete=models.PROTECT,
        related_name='payment_orders')
    cycle_sequence = models.PositiveIntegerField()
    merchant_order_id = models.CharField(max_length=80, unique=True)
    amount_krw = models.PositiveIntegerField()
    due_date = models.DateField()
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='created')
    failure_code = models.CharField(
        max_length=40, blank=True, default='')
    unknown_since = models.DateTimeField(null=True, blank=True)
    temporary_access_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'billing_payment_order'
        constraints = [
            models.UniqueConstraint(
                fields=['agreement', 'cycle_sequence'],
                name='uniq_billing_agreement_cycle'),
        ]
        indexes = [
            models.Index(fields=['status', 'due_date']),
        ]


class PaymentAttempt(models.Model):
    RESULT_CHOICES = [(value, value) for value in (
        'approved', 'declined', 'unknown')]

    order = models.ForeignKey(
        PaymentOrder, on_delete=models.PROTECT,
        related_name='attempts')
    attempt_no = models.PositiveSmallIntegerField()
    provider_request_id = models.CharField(max_length=80, unique=True)
    result_kind = models.CharField(
        max_length=20, choices=RESULT_CHOICES, blank=True, default='')
    provider_transaction_id = models.CharField(
        max_length=120, unique=True, null=True, blank=True)
    provider_code = models.CharField(
        max_length=40, blank=True, default='')
    response_hash = models.CharField(
        max_length=64, blank=True, default='')
    started_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'billing_payment_attempt'
        constraints = [
            models.UniqueConstraint(
                fields=['order', 'attempt_no'],
                name='uniq_billing_order_attempt'),
        ]


class WebhookInbox(models.Model):
    STATUS_CHOICES = [(value, value) for value in (
        'received', 'verified', 'processed', 'rejected')]

    provider_event_id = models.CharField(max_length=120, unique=True)
    payload_hash = models.CharField(max_length=64)
    signature_valid = models.BooleanField(default=False)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='received')
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'billing_webhook_inbox'


class BillingNoticeEvent(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='billing_notice_events')
    event_key = models.CharField(max_length=120)
    notice_type = models.CharField(max_length=40)
    reason = models.CharField(max_length=40)
    lease_device_hash = models.CharField(
        max_length=64, blank=True, default='')
    lease_until = models.DateTimeField(null=True, blank=True)
    rendered_at = models.DateTimeField(null=True, blank=True)
    dismissed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'billing_notice_event'
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'event_key', 'notice_type'],
                name='uniq_billing_notice_event'),
        ]


class CouponClaim(models.Model):
    STATUS_CHOICES = [(value, value) for value in (
        'held', 'redeemed', 'released', 'expired')]

    id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False)
    coupon = models.ForeignKey(
        'billing.Coupon', on_delete=models.PROTECT,
        related_name='claims')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='coupon_claims')
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='held')
    expires_at = models.DateTimeField()
    policy_snapshot = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    redeemed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'billing_coupon_claim'
        constraints = [
            models.UniqueConstraint(
                fields=['coupon', 'user'],
                condition=Q(status__in=('held', 'redeemed')),
                name='uniq_billing_live_coupon_claim'),
        ]


class BillingAdminAction(models.Model):
    admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='billing_admin_actions',
    )
    action = models.CharField(max_length=40)
    target_type = models.CharField(max_length=30)
    target_id = models.CharField(max_length=80, blank=True, default='')
    request_key = models.CharField(
        max_length=100, blank=True, default='')
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'billing_admin_action'
        constraints = [
            models.UniqueConstraint(
                fields=['request_key'],
                condition=~Q(request_key=''),
                name='uniq_billing_admin_request_key',
            ),
        ]
        indexes = [
            models.Index(fields=['action', '-created_at']),
        ]
