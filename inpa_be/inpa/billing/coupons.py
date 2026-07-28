"""쿠폰 사용 로직 — 관리자 발급 코드로 Plus를 한시적으로 부여 (item 8).

공개 인터페이스:
  redeem_coupon(user, raw_code) → 성공 dict / CouponError raise
  CouponError                   → 실패 (뷰에서 상태코드·메시지로 변환)

정직성/안전:
  - 코드는 대소문자 무시(대문자 정규화). 존재/활성/유효기한/사용 수 검증.
  - 같은 사용자가 같은 쿠폰을 두 번 쓰지 못함(CouponRedemption unique).
  - 같은 플랜 잔여 기간이 있으면 이어붙여(stack) 만료 시각을 연장.
  - select_for_update로 동시 사용 레이스 차단.
"""
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from .models import (
    BenefitGrantException,
    BenefitGrantLedger,
    BillingAgreement,
    Coupon,
    CouponClaim,
    CouponRedemption,
    ManualBenefitReview,
    PaymentMethodToken,
    RecurringPaymentConsent,
    Subscription,
    VerifiedPhoneIdentity,
)


class CouponError(Exception):
    """쿠폰 사용 실패. code(not_found/inactive/expired/exhausted/already)로 상황 구분."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


_MESSAGES = {
    'not_found': '유효하지 않은 쿠폰 코드예요. 코드를 다시 확인해 주세요.',
    'inactive': '지금은 사용할 수 없는 쿠폰이에요.',
    'expired': '유효기간이 지난 쿠폰이에요.',
    'exhausted': '이미 모두 사용된 쿠폰이에요.',
    'already': '이미 사용한 쿠폰이에요.',
    'active_plan': '이미 이용 중인 요금제가 있어요. 기간이 끝난 뒤에 사용해 주세요.',
    'wrong_kind': '카드 등록형 무료 이용 쿠폰을 확인해 주세요.',
    'card_required': 'CARD_REQUIRED',
    'consent_required': 'CONSENT_REQUIRED',
    'claim_expired': '쿠폰 사용 시간이 지났어요. 쿠폰을 다시 확인해 주세요.',
    'phone_verification_required':
        '휴대전화 인증을 마치면 무료 이용을 시작할 수 있어요.',
    'manual_benefit_review_required':
        '확인이 필요한 번호예요. 이메일과 간단한 사유를 남기면 확인 후 안내해 드릴게요.',
    'phone_identity_key_rotation_required':
        '휴대전화 인증 기준을 확인하고 있어요. 잠시 뒤 다시 시도해 주세요.',
}

_KST = ZoneInfo('Asia/Seoul')


@dataclass(frozen=True)
class CouponPreview:
    code: str
    plan_code: str
    plan_display_name: str
    duration_months: int
    redeem_by: datetime


@dataclass(frozen=True)
class PhoneBenefitContext:
    identity_hmac: str
    key_version: str
    phone_last4: str


def normalize_code(raw_code):
    return (raw_code or '').strip().upper()


def _get_recurring_coupon(raw_code):
    code = normalize_code(raw_code)
    if not code:
        raise CouponError('not_found', _MESSAGES['not_found'])
    try:
        coupon = Coupon.objects.select_related('plan').get(code=code)
    except Coupon.DoesNotExist:
        raise CouponError('not_found', _MESSAGES['not_found'])
    if coupon.coupon_kind != 'recurring_trial':
        raise CouponError('wrong_kind', _MESSAGES['wrong_kind'])
    reason = coupon.redeemable_reason()
    if reason:
        raise CouponError(reason, _MESSAGES.get(reason, _MESSAGES['inactive']))
    return coupon


def _phone_benefit_context(user):
    if not getattr(
        settings,
        'FREE_TRIAL_PHONE_VERIFICATION_ENABLED',
        False,
    ):
        return None
    current_key_version = getattr(
        settings,
        'PHONE_IDENTITY_HMAC_KEY_VERSION',
        'v1',
    )
    benefit_code = BenefitGrantLedger.BENEFIT_PLUS_TRIAL_MONTH
    if BenefitGrantLedger.objects.filter(
        benefit_code=benefit_code,
    ).exclude(key_version=current_key_version).exists():
        # 이전 원장을 무시한 채 새 digest로 지급하면 키 회전만으로 중복 수혜가
        # 가능해진다. 원장 재키잉/previous-key 지원 전까지 전역 fail-closed.
        raise CouponError(
            'phone_identity_key_rotation_required',
            _MESSAGES['phone_identity_key_rotation_required'],
        )
    identity = VerifiedPhoneIdentity.objects.filter(user=user).first()
    if (
        identity is None
        or identity.key_version != current_key_version
    ):
        raise CouponError(
            'phone_verification_required',
            _MESSAGES['phone_verification_required'],
        )
    ledger_exists = BenefitGrantLedger.objects.filter(
        identity_hmac=identity.phone_hmac,
        benefit_code=benefit_code,
    ).exists()
    if ledger_exists and not ManualBenefitReview.objects.filter(
        user=user,
        identity_hmac=identity.phone_hmac,
        key_version=identity.key_version,
        benefit_code=benefit_code,
        status=ManualBenefitReview.STATUS_APPROVED,
    ).exists():
        raise CouponError(
            'manual_benefit_review_required',
            _MESSAGES['manual_benefit_review_required'],
        )
    return PhoneBenefitContext(
        identity_hmac=identity.phone_hmac,
        key_version=identity.key_version,
        phone_last4=identity.phone_last4,
    )


def _validate_user_can_claim(coupon, user):
    if CouponRedemption.objects.filter(coupon=coupon, user=user).exists():
        raise CouponError('already', _MESSAGES['already'])
    sub = (
        Subscription.objects.select_related('plan')
        .filter(user=user)
        .first()
    )
    if (
        sub
        and sub.plan.code != 'free'
        and sub.status in ('active', 'trial')
        and (sub.expires_at is None or sub.expires_at > timezone.now())
    ):
        raise CouponError('active_plan', _MESSAGES['active_plan'])
    return _phone_benefit_context(user)


def preflight_recurring_coupon(user, raw_code):
    coupon = _get_recurring_coupon(raw_code)
    _validate_user_can_claim(coupon, user)
    return CouponPreview(
        code=coupon.code,
        plan_code=coupon.plan.code,
        plan_display_name=coupon.plan.display_name,
        duration_months=coupon.duration_months,
        redeem_by=coupon.redeem_by,
    )


def release_expired_claims(coupon, now=None):
    now = now or timezone.now()
    return CouponClaim.objects.filter(
        coupon=coupon,
        status='held',
        expires_at__lte=now,
    ).update(status='expired')


def hold_recurring_coupon(user, raw_code):
    code = normalize_code(raw_code)
    if not code:
        raise CouponError('not_found', _MESSAGES['not_found'])
    now = timezone.now()
    with transaction.atomic():
        try:
            coupon = (
                Coupon.objects.select_for_update()
                .select_related('plan')
                .get(code=code)
            )
        except Coupon.DoesNotExist:
            raise CouponError('not_found', _MESSAGES['not_found'])
        if coupon.coupon_kind != 'recurring_trial':
            raise CouponError('wrong_kind', _MESSAGES['wrong_kind'])
        release_expired_claims(coupon, now)
        reason = coupon.redeemable_reason(now)
        if reason:
            raise CouponError(
                reason, _MESSAGES.get(reason, _MESSAGES['inactive']))
        phone_context = _validate_user_can_claim(coupon, user)
        existing = CouponClaim.objects.filter(
            coupon=coupon,
            user=user,
            status__in=('held', 'redeemed'),
        ).first()
        if existing:
            if phone_context is None:
                return existing
            snapshot = existing.policy_snapshot or {}
            if (
                snapshot.get('phone_identity_hmac')
                == phone_context.identity_hmac
                and snapshot.get('phone_identity_key_version')
                == phone_context.key_version
            ):
                return existing
            existing.status = 'released'
            existing.save(update_fields=['status'])
        active_claims = CouponClaim.objects.filter(
            coupon=coupon,
            status__in=('held', 'redeemed'),
        ).count()
        if active_claims >= coupon.max_redemptions:
            raise CouponError('exhausted', _MESSAGES['exhausted'])
        try:
            return CouponClaim.objects.create(
                coupon=coupon,
                user=user,
                status='held',
                expires_at=now + timedelta(minutes=15),
                policy_snapshot={
                    'coupon_code': coupon.code,
                    'plan_code': coupon.plan.code,
                    'duration_months': coupon.duration_months,
                    'redeem_by': coupon.redeem_by.isoformat(),
                    **({
                        'phone_identity_hmac':
                            phone_context.identity_hmac,
                        'phone_identity_key_version':
                            phone_context.key_version,
                    } if phone_context is not None else {}),
                },
            )
        except IntegrityError:
            existing = CouponClaim.objects.filter(
                coupon=coupon,
                user=user,
                status__in=('held', 'redeemed'),
            ).first()
            if existing:
                return existing
            raise


def _exclusive_kst_midnight(local_date):
    return timezone.make_aware(
        datetime.combine(local_date, time.min),
        timezone=_KST,
    )


def _create_reviewed_exception(
    *,
    original_ledger,
    user,
    phone_context,
    coupon_snapshot,
    granted_at,
    granted_until,
):
    review = (
        ManualBenefitReview.objects.select_for_update()
        .filter(
            user=user,
            identity_hmac=phone_context.identity_hmac,
            key_version=phone_context.key_version,
            benefit_code=(
                BenefitGrantLedger.BENEFIT_PLUS_TRIAL_MONTH
            ),
            status=ManualBenefitReview.STATUS_APPROVED,
        )
        .order_by('decided_at', 'pk')
        .first()
    )
    if review is None:
        raise CouponError(
            'manual_benefit_review_required',
            _MESSAGES['manual_benefit_review_required'],
        )
    try:
        BenefitGrantException.objects.create(
            original_ledger=original_ledger,
            review=review,
            user=user,
            identity_hmac=phone_context.identity_hmac,
            key_version=phone_context.key_version,
            benefit_code=(
                BenefitGrantLedger.BENEFIT_PLUS_TRIAL_MONTH
            ),
            granted_at=granted_at,
            granted_until=granted_until,
            coupon_snapshot=coupon_snapshot,
        )
    except IntegrityError as exc:
        raise CouponError(
            'manual_benefit_review_required',
            _MESSAGES['manual_benefit_review_required'],
        ) from exc
    review.status = ManualBenefitReview.STATUS_CONSUMED
    review.consumed_at = granted_at
    review.save(update_fields=['status', 'consumed_at'])


def _claim_phone_benefit(
    *,
    user,
    phone_context,
    coupon,
    claim,
    granted_at,
    granted_until,
):
    if phone_context is None:
        return
    snapshot = claim.policy_snapshot or {}
    if (
        snapshot.get('phone_identity_hmac')
        != phone_context.identity_hmac
        or snapshot.get('phone_identity_key_version')
        != phone_context.key_version
    ):
        raise CouponError(
            'phone_verification_required',
            _MESSAGES['phone_verification_required'],
        )
    coupon_snapshot = {
        'coupon_id': coupon.pk,
        'coupon_code': coupon.code,
        'plan_code': coupon.plan.code,
        'duration_months': coupon.duration_months,
        'claim_id': str(claim.pk),
    }
    benefit_code = BenefitGrantLedger.BENEFIT_PLUS_TRIAL_MONTH
    existing = (
        BenefitGrantLedger.objects.select_for_update()
        .filter(
            identity_hmac=phone_context.identity_hmac,
            benefit_code=benefit_code,
        )
        .first()
    )
    if existing is not None:
        _create_reviewed_exception(
            original_ledger=existing,
            user=user,
            phone_context=phone_context,
            coupon_snapshot=coupon_snapshot,
            granted_at=granted_at,
            granted_until=granted_until,
        )
        return
    try:
        with transaction.atomic():
            BenefitGrantLedger.objects.create(
                identity_hmac=phone_context.identity_hmac,
                key_version=phone_context.key_version,
                benefit_code=benefit_code,
                user=user,
                granted_at=granted_at,
                granted_until=granted_until,
                coupon_snapshot=coupon_snapshot,
            )
    except IntegrityError:
        # PostgreSQL에서 동시 insert가 유일 제약에 걸리면 savepoint만
        # 되돌리고, 커밋된 최초 원장을 다시 잠근 뒤 승인 예외를 재검사한다.
        existing = (
            BenefitGrantLedger.objects.select_for_update()
            .get(
                identity_hmac=phone_context.identity_hmac,
                benefit_code=benefit_code,
            )
        )
        _create_reviewed_exception(
            original_ledger=existing,
            user=user,
            phone_context=phone_context,
            coupon_snapshot=coupon_snapshot,
            granted_at=granted_at,
            granted_until=granted_until,
        )


def redeem_held_coupon(claim, agreement):
    claim_id = getattr(claim, 'pk', claim)
    agreement_id = getattr(agreement, 'pk', agreement)
    now = timezone.now()
    with transaction.atomic():
        locked_claim = (
            CouponClaim.objects.select_for_update()
            .select_related('coupon__plan', 'user')
            .get(pk=claim_id)
        )
        locked_agreement = (
            BillingAgreement.objects.select_for_update()
            .select_related('plan', 'user')
            .get(pk=agreement_id)
        )
        if locked_claim.user_id != locked_agreement.user_id:
            raise CouponError('not_found', _MESSAGES['not_found'])
        if (
            locked_claim.status != 'held'
            or locked_claim.expires_at <= now
        ):
            if locked_claim.status == 'held':
                locked_claim.status = 'expired'
                locked_claim.save(update_fields=['status'])
            raise CouponError('claim_expired', _MESSAGES['claim_expired'])

        coupon = locked_claim.coupon
        reason = coupon.redeemable_reason(now)
        if reason:
            raise CouponError(
                reason, _MESSAGES.get(reason, _MESSAGES['inactive']))
        if not PaymentMethodToken.objects.filter(
                agreement=locked_agreement, status='active').exists():
            raise CouponError(
                'card_required', _MESSAGES['card_required'])
        if not RecurringPaymentConsent.objects.filter(
                agreement=locked_agreement,
                kind='trial_start').exists():
            raise CouponError(
                'consent_required', _MESSAGES['consent_required'])
        if (
            locked_agreement.plan_id != coupon.plan_id
            or locked_agreement.trial_duration_months
            != coupon.duration_months
        ):
            raise CouponError('policy_changed', 'POLICY_CHANGED')
        if CouponRedemption.objects.filter(
                coupon=coupon, user=locked_claim.user).exists():
            raise CouponError('already', _MESSAGES['already'])

        phone_context = _phone_benefit_context(locked_claim.user)
        expires_at = _exclusive_kst_midnight(
            locked_agreement.next_charge_date)
        _claim_phone_benefit(
            user=locked_claim.user,
            phone_context=phone_context,
            coupon=coupon,
            claim=locked_claim,
            granted_at=now,
            granted_until=expires_at,
        )
        subscription, _ = Subscription.objects.select_for_update().get_or_create(
            user=locked_claim.user,
            defaults={
                'plan': coupon.plan,
                'status': 'trial',
                'expires_at': expires_at,
            },
        )
        subscription.plan = coupon.plan
        subscription.status = 'trial'
        subscription.expires_at = expires_at
        subscription.cancelled_at = None
        subscription.auto_renew = True
        subscription.next_billing_at = expires_at
        subscription.save(update_fields=[
            'plan',
            'status',
            'expires_at',
            'cancelled_at',
            'auto_renew',
            'next_billing_at',
        ])
        CouponRedemption.objects.create(
            coupon=coupon,
            user=locked_claim.user,
            granted_until=expires_at,
        )
        Coupon.objects.filter(pk=coupon.pk).update(
            redeemed_count=F('redeemed_count') + 1)
        locked_claim.status = 'redeemed'
        locked_claim.redeemed_at = now
        locked_claim.save(update_fields=['status', 'redeemed_at'])

    return {
        'plan_code': coupon.plan.code,
        'plan_display_name': coupon.plan.display_name,
        'expires_at': expires_at.isoformat(),
        'duration_months': coupon.duration_months,
    }


def redeem_coupon(user, raw_code):
    """user가 raw_code 쿠폰을 사용 → 쿠폰의 요금제를 duration_days만큼 부여.

    반환: {plan_code, plan_display_name, expires_at(iso), duration_days}
    실패: CouponError(code) — not_found/inactive/expired/exhausted/already.
    """
    code = normalize_code(raw_code)
    if not code:
        raise CouponError('not_found', _MESSAGES['not_found'])

    now = timezone.now()
    with transaction.atomic():
        try:
            coupon = Coupon.objects.select_for_update().select_related('plan').get(code=code)
        except Coupon.DoesNotExist:
            raise CouponError('not_found', _MESSAGES['not_found'])

        if coupon.coupon_kind != 'legacy_grant':
            raise CouponError('wrong_kind', _MESSAGES['wrong_kind'])

        reason = coupon.redeemable_reason(now)
        if reason:
            raise CouponError(reason, _MESSAGES.get(reason, _MESSAGES['inactive']))

        if CouponRedemption.objects.filter(coupon=coupon, user=user).exists():
            raise CouponError('already', _MESSAGES['already'])

        # 구독 upsert — free/만료/해지/없음일 때만 새로 부여한다. 활성 구독을 조용히
        # 덮어써 기존 혜택을 줄이지 않는다.
        #   · 무기한 동일·상위 플랜 → 유한 쿠폰이 오히려 기간을 깎으므로 적용하지 않음('already').
        #   · 같은 플랜 잔여 기간 → 그 위에 이어붙임(stack).
        #   · 다른 활성 플랜(잔여 기간 있음) → 덮어쓰지 않음('active_plan').
        # ★ Free 구독은 지켜야 할 유료 혜택이 없으므로 '활성 유료 구독'에서 제외한다
        #   (free/만료/해지/없음 = 그대로 새로 부여). paid 활성 구독만 덮어쓰기를 막는다.
        sub = Subscription.objects.select_for_update().filter(user=user).first()
        active = (
            sub is not None
            and sub.status in ('active', 'trial')
            and (sub.expires_at is None or sub.expires_at > now)
            and sub.plan.code != 'free'
        )
        base = now
        if active:
            same_plan = sub.plan_id == coupon.plan_id
            if sub.expires_at is None and (same_plan or sub.plan.price_krw >= coupon.plan.price_krw):
                # 무기한 동일·상위 플랜은 유한 쿠폰으로 단축하지 않는다.
                raise CouponError('already', _MESSAGES['already'])
            if same_plan:
                base = sub.expires_at
            else:
                # 다른 활성 플랜은 조용히 덮어쓰지 않는다.
                raise CouponError('active_plan', _MESSAGES['active_plan'])
        granted_until = base + timedelta(days=coupon.duration_days)

        if sub is None:
            Subscription.objects.create(
                user=user, plan=coupon.plan, status='active', expires_at=granted_until)
        else:
            sub.plan = coupon.plan
            sub.status = 'active'
            sub.expires_at = granted_until
            sub.cancelled_at = None
            sub.save(update_fields=['plan', 'status', 'expires_at', 'cancelled_at'])

        CouponRedemption.objects.create(coupon=coupon, user=user, granted_until=granted_until)
        coupon.redeemed_count += 1
        coupon.save(update_fields=['redeemed_count'])

    return {
        'plan_code': coupon.plan.code,
        'plan_display_name': coupon.plan.display_name,
        'expires_at': granted_until.isoformat(),
        'duration_days': coupon.duration_days,
    }
