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
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import Coupon, CouponRedemption, Subscription


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
}


def redeem_coupon(user, raw_code):
    """user가 raw_code 쿠폰을 사용 → 쿠폰의 요금제를 duration_days만큼 부여.

    반환: {plan_code, plan_display_name, expires_at(iso), duration_days}
    실패: CouponError(code) — not_found/inactive/expired/exhausted/already.
    """
    code = (raw_code or '').strip().upper()
    if not code:
        raise CouponError('not_found', _MESSAGES['not_found'])

    now = timezone.now()
    with transaction.atomic():
        try:
            coupon = Coupon.objects.select_for_update().select_related('plan').get(code=code)
        except Coupon.DoesNotExist:
            raise CouponError('not_found', _MESSAGES['not_found'])

        reason = coupon.redeemable_reason(now)
        if reason:
            raise CouponError(reason, _MESSAGES.get(reason, _MESSAGES['inactive']))

        if CouponRedemption.objects.filter(coupon=coupon, user=user).exists():
            raise CouponError('already', _MESSAGES['already'])

        # 구독 upsert — 같은 플랜 잔여 기간이 있으면 그 위에 이어붙임(stack).
        sub = Subscription.objects.select_for_update().filter(user=user).first()
        base = now
        if (sub and sub.plan_id == coupon.plan_id
                and sub.expires_at and sub.expires_at > now):
            base = sub.expires_at
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
