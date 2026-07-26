from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from .coupons import (
    CouponError,
    hold_recurring_coupon,
    preflight_recurring_coupon,
    redeem_coupon,
    redeem_held_coupon,
)
from .models import (
    BillingAgreement,
    Coupon,
    CouponClaim,
    CouponRedemption,
    PaymentMethodToken,
    Plan,
    RecurringPaymentConsent,
    Subscription,
)

User = get_user_model()


class RecurringCouponTests(TestCase):
    def setUp(self):
        self.free = Plan.objects.create(
            code='free', display_name='무료', price_krw=0)
        self.plus = Plan.objects.create(
            code='plus', display_name='Plus', price_krw=19900)
        self.user = User.objects.create_user(
            email='coupon@example.com', password='test-password')
        self.sub = Subscription.objects.get(user=self.user)

    def _coupon(self, **overrides):
        values = {
            'code': 'MONTHS-2',
            'plan': self.plus,
            'coupon_kind': 'recurring_trial',
            'duration_months': 2,
            'redeem_by': timezone.now() + timedelta(days=30),
            'max_redemptions': 1,
        }
        values.update(overrides)
        return Coupon.objects.create(**values)

    def _agreement(self, coupon):
        agreement = BillingAgreement.objects.create(
            user=self.user,
            plan=self.plus,
            status='trialing',
            billing_anchor_day=5,
            trial_duration_months=coupon.duration_months,
            current_period_starts_on=date(2027, 1, 5),
            current_period_ends_on=date(2027, 3, 4),
            next_charge_date=date(2027, 3, 5),
        )
        PaymentMethodToken.objects.create(
            agreement=agreement,
            encrypted_token='ciphertext',
            key_version='v1',
            card_brand='신한',
            card_last4='1234',
            status='active',
        )
        RecurringPaymentConsent.objects.create(
            agreement=agreement,
            kind='trial_start',
            consent_version='v1',
            plan_code='plus',
            amount_krw=21890,
            charge_date=date(2027, 3, 5),
            card_label='신한 끝 1234',
            cancel_effect=date(2027, 3, 4),
            display_snapshot_hash='a' * 64,
            accepted_at=timezone.now(),
        )
        return agreement

    def test_recurring_coupon_accepts_only_one_to_three_months(self):
        for months in (1, 2, 3):
            coupon = Coupon(
                coupon_kind='recurring_trial',
                duration_months=months,
                redeem_by=timezone.now() + timedelta(days=1),
                plan=self.plus,
            )
            coupon.full_clean(exclude=['code'])

        for months in (0, 4):
            with self.subTest(months=months):
                with self.assertRaises(ValidationError):
                    Coupon(
                        coupon_kind='recurring_trial',
                        duration_months=months,
                        redeem_by=timezone.now() + timedelta(days=1),
                        plan=self.plus,
                    ).full_clean(exclude=['code'])

    def test_recurring_coupon_requires_redeem_by(self):
        with self.assertRaises(ValidationError):
            Coupon(
                coupon_kind='recurring_trial',
                duration_months=1,
                plan=self.plus,
            ).full_clean(exclude=['code'])

    def test_legacy_coupon_keeps_duration_days_behavior(self):
        legacy = Coupon.objects.create(
            code='LEGACY-14',
            plan=self.plus,
            duration_days=14,
            max_redemptions=1,
        )
        result = redeem_coupon(self.user, legacy.code)
        self.assertEqual(result['duration_days'], 14)
        self.assertEqual(
            CouponRedemption.objects.get(user=self.user).coupon,
            legacy,
        )

    def test_hold_is_idempotent_for_same_user(self):
        coupon = self._coupon()
        first = hold_recurring_coupon(self.user, coupon.code)
        second = hold_recurring_coupon(self.user, coupon.code)
        self.assertEqual(first.id, second.id)
        self.assertEqual(
            CouponClaim.objects.filter(status='held').count(), 1)

    def test_last_seat_is_unavailable_after_hold(self):
        coupon = self._coupon()
        other = User.objects.create_user(
            email='other@example.com', password='test-password')
        hold_recurring_coupon(self.user, coupon.code)
        with self.assertRaisesMessage(
                CouponError, '이미 모두 사용된 쿠폰이에요.'):
            hold_recurring_coupon(other, coupon.code)

    def test_preflight_returns_calendar_preview_without_holding(self):
        coupon = self._coupon()
        preview = preflight_recurring_coupon(self.user, coupon.code)
        self.assertEqual(preview.duration_months, 2)
        self.assertEqual(preview.plan_code, 'plus')
        self.assertEqual(preview.redeem_by, coupon.redeem_by)
        self.assertFalse(CouponClaim.objects.exists())

    def test_finalize_requires_active_card_and_current_consent(self):
        coupon = self._coupon()
        claim = hold_recurring_coupon(self.user, coupon.code)
        agreement = BillingAgreement.objects.create(
            user=self.user,
            plan=self.plus,
            status='trialing',
            billing_anchor_day=5,
            trial_duration_months=2,
            current_period_starts_on=date(2027, 1, 5),
            current_period_ends_on=date(2027, 3, 4),
            next_charge_date=date(2027, 3, 5),
        )
        with self.assertRaisesMessage(CouponError, 'CARD_REQUIRED'):
            redeem_held_coupon(claim, agreement)

    def test_finalize_projects_calendar_period_once(self):
        coupon = self._coupon()
        claim = hold_recurring_coupon(self.user, coupon.code)
        agreement = self._agreement(coupon)
        result = redeem_held_coupon(claim, agreement)

        claim.refresh_from_db()
        self.sub.refresh_from_db()
        coupon.refresh_from_db()
        self.assertEqual(claim.status, 'redeemed')
        self.assertEqual(self.sub.plan, self.plus)
        self.assertEqual(self.sub.status, 'trial')
        self.assertEqual(
            timezone.localtime(self.sub.expires_at).date(),
            date(2027, 3, 5),
        )
        self.assertEqual(coupon.redeemed_count, 1)
        self.assertEqual(result['duration_months'], 2)
