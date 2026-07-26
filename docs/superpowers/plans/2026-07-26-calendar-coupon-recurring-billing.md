# 달력 개월 쿠폰·정기결제 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 카드 등록이 필요한 1~3 달력 개월 쿠폰과 첫 결제 재확인형 월 정기결제를 구현하고, 결제 실패·미확정·해지 뒤에도 기존 고객 기록을 보존한다.

**Architecture:** 기존 `Subscription`은 현재 이용 권한의 투영으로 남기고, 결제 약정·결제수단·동의·주문·시도·안내를 별도 원장 모델로 관리한다. KICC 호출은 한 adapter에 격리하고 모든 신규 결제 진입점은 환경변수와 관리자 스위치의 이중 게이트를 통과한다. 달력 계산, 쿠폰 점유, 승인, 대사, 무료 전환을 각각 독립 서비스로 나눠 동시성과 실패 복구를 시험한다.

**Tech Stack:** Django 5.2 LTS, DRF 3.16, PostgreSQL, Celery 5.6, KICC Easypay Billing API, Next.js 16, React 19, TypeScript, Tailwind v4, Vitest.

## Global Constraints

- 새 일반 쿠폰 `duration_months`는 1, 2, 3만 허용한다.
- 쿠폰을 사용하려면 KICC 카드 등록과 무료 시작 동의가 먼저 완료돼야 한다.
- 1개월 쿠폰은 첫 결제 7일 전, 2~3개월 쿠폰은 30일 전부터 결제일 직전 23:59(KST)까지 별도 재확인한다.
- 결제 기준일은 최초 활성화 KST 날짜를 보존하고 해당 월에 날짜가 없을 때만 월말로 보정한다.
- 시간초과·응답 유실은 `unknown`으로 두고 재승인하지 않으며 거래 조회로만 확정한다.
- 사용자가 다음 결제를 멈추면 즉시 빌키를 폐기하고 확보한 이용기간 끝까지 이용권을 유지한다.
- 결제·동의·환불 원장에는 메모·AI 요약·녹음·고객 이름·전화번호를 저장하지 않는다.
- 카드번호·CVC는 인파 서버를 통과하거나 저장하지 않는다. 빌키는 서버에서 암호화한다.
- 유료 만료·해지·승인 실패 뒤에도 기존 고객·메모·AI 요약은 열람·직접 수정할 수 있다.
- 새 녹음·새 AI 요약·기타 비용 발생 기능만 현재 요금제 한도를 적용한다.
- 기능 게이트 기본값은 모두 `False`다. 운영 공개는 KICC·법적 문구·정산 증거가 갖춰진 뒤 별도 스위치로 연다.
- `FREE_TIER_UNLIMITED=True` 동안 정기 승인 게이트를 열 수 없다.
- 화면 문구는 쉬운 한국어와 다음 행동을 사용하고 `—`, `불가`, `안 됩니다`, `준비 중`을 쓰지 않는다.
- 서비스 화면은 light-fixed, 관리자 화면만 기존 admin theme를 사용한다.
- 사용자 요청에 따라 기능 코드의 master 병합·원격 푸시·운영 배포까지 진행하되 신규 결제 게이트는 닫힌 상태로 배포한다.

---

## 파일 구조

### Backend

- `inpa_be/inpa/billing/calendar.py`: KST 달력 개월·기준일 계산만 담당
- `inpa_be/inpa/billing/payment_models.py`: 결제 원장 모델
- `inpa_be/inpa/billing/gates.py`: 환경·런타임 게이트와 의존 규칙
- `inpa_be/inpa/billing/kicc.py`: KICC 요청·응답 검증 adapter
- `inpa_be/inpa/billing/payment_tokens.py`: 빌키 암호화·폐기
- `inpa_be/inpa/billing/agreements.py`: 카드 등록·동의·약정 상태 전이
- `inpa_be/inpa/billing/recurring.py`: 주문 생성·승인·무료 전환
- `inpa_be/inpa/billing/reconciliation.py`: 미확정 거래 조회·늦은 승인 취소
- `inpa_be/inpa/billing/notices.py`: 무료 전환 안내 lease·render ack
- `inpa_be/inpa/billing/coupons.py`: 기존 일수형 호환 + 신규 달력 개월 점유·확정
- `inpa_be/inpa/billing/views.py`, `serializers.py`, `urls.py`: 본인 결제 API
- `inpa_be/inpa/admin_console/*`: 비개발자용 결제 운영 API
- `inpa_be/inpa/billing/tasks.py`: 정기 승인·미확정 재조회·빌키 폐기 재시도

### Frontend

- `inpa_fe/app/settings/billing/page.tsx`: 요금제·쿠폰·카드·결제일·해지
- `inpa_fe/components/billing/card-registration.tsx`: KICC 카드 등록창 흐름
- `inpa_fe/components/billing/first-charge-confirmation.tsx`: 첫 결제 재확인
- `inpa_fe/components/billing/free-transition-notice.tsx`: 사건별 1회 안내
- `inpa_fe/app/admin/billing/page.tsx`: 쿠폰·주문·미확정·폐기 운영
- `inpa_fe/lib/api.ts`, `adminApi.ts`: 단일 API gateway 계약

---

### Task 1: KST 달력 개월 계산과 기준일 보존

**Files:**
- Create: `inpa_be/inpa/billing/calendar.py`
- Test: `inpa_be/inpa/billing/test_calendar.py`

**Interfaces:**
- Produces: `add_calendar_months(start_date: date, months: int, anchor_day: int) -> date`
- Produces: `period_for(start_date: date, months: int, anchor_day: int) -> BillingPeriod`
- Produces: `new_anchor(local_date: date) -> int`

- [ ] **Step 1: Write failing month-end and leap-year tests**

```python
class CalendarBillingTests(SimpleTestCase):
    def test_fifth_to_fifth(self):
        period = period_for(date(2027, 1, 5), 1, anchor_day=5)
        self.assertEqual(period.access_through, date(2027, 2, 4))
        self.assertEqual(period.next_charge_date, date(2027, 2, 5))

    def test_eighth_to_eighth(self):
        period = period_for(date(2027, 2, 8), 1, anchor_day=8)
        self.assertEqual(period.access_through, date(2027, 3, 7))
        self.assertEqual(period.next_charge_date, date(2027, 3, 8))

    def test_month_end_clamps_then_restores_original_anchor(self):
        feb = add_calendar_months(date(2027, 1, 31), 1, anchor_day=31)
        mar = add_calendar_months(feb, 1, anchor_day=31)
        self.assertEqual(feb, date(2027, 2, 28))
        self.assertEqual(mar, date(2027, 3, 31))

    def test_leap_year(self):
        self.assertEqual(
            add_calendar_months(date(2028, 1, 31), 1, anchor_day=31),
            date(2028, 2, 29),
        )
```

- [ ] **Step 2: Run and verify module-not-found failure**

Run: `cd inpa_be && python manage.py test inpa.billing.test_calendar -v 2`

Expected: `inpa.billing.calendar` import failure.

- [ ] **Step 3: Implement pure calendar functions**

```python
@dataclass(frozen=True)
class BillingPeriod:
    starts_on: date
    access_through: date
    next_charge_date: date


def add_calendar_months(start_date: date, months: int, *, anchor_day: int) -> date:
    if months < 1 or anchor_day not in range(1, 32):
        raise ValueError('INVALID_CALENDAR_PERIOD')
    month_index = start_date.year * 12 + start_date.month - 1 + months
    year, zero_month = divmod(month_index, 12)
    month = zero_month + 1
    day = min(anchor_day, monthrange(year, month)[1])
    return date(year, month, day)


def period_for(start_date: date, months: int, *, anchor_day: int) -> BillingPeriod:
    next_date = add_calendar_months(start_date, months, anchor_day=anchor_day)
    return BillingPeriod(start_date, next_date - timedelta(days=1), next_date)


def new_anchor(local_date: date) -> int:
    return local_date.day
```

- [ ] **Step 4: Run calendar tests**

Run: `cd inpa_be && python manage.py test inpa.billing.test_calendar -v 2`

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add inpa_be/inpa/billing/calendar.py inpa_be/inpa/billing/test_calendar.py
git commit -m "feat(결제): 달력 기준 구독 기간 계산"
```

### Task 2: 결제 원장 모델과 닫힌 기능 게이트

**Files:**
- Create: `inpa_be/inpa/billing/payment_models.py`
- Create: `inpa_be/inpa/billing/gates.py`
- Modify: `inpa_be/inpa/billing/models.py`
- Modify: `inpa_be/config/settings/base.py`
- Create migrations with `makemigrations billing`
- Test: `inpa_be/inpa/billing/test_payment_models.py`
- Modify: `inpa_be/.env.example`

**Interfaces:**
- Produces: `BillingAgreement`, `PaymentMethodToken`, `RecurringPaymentConsent`
- Produces: `PaymentOrder`, `PaymentAttempt`, `WebhookInbox`, `BillingNoticeEvent`, `CouponClaim`
- Produces: `card_registration_enabled()`, `recurring_charge_enabled()`, `reconciliation_enabled()`

- [ ] **Step 1: Write failing defaults, constraints, and gate dependency tests**

```python
class PaymentLedgerModelTests(TestCase):
    def test_cycle_is_permanently_unique_inside_agreement(self):
        PaymentOrder.objects.create(
            agreement=self.agreement, cycle_sequence=1,
            merchant_order_id='INPA-1', amount_krw=21890,
            due_date=date(2027, 2, 5), status='created')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PaymentOrder.objects.create(
                    agreement=self.agreement, cycle_sequence=1,
                    merchant_order_id='INPA-2', amount_krw=21890,
                    due_date=date(2027, 2, 5), status='created')

    @override_settings(
        BILLING_CARD_REGISTRATION_ENABLED=True,
        BILLING_RECURRING_CHARGE_ENABLED=True,
        BILLING_WEBHOOK_RECONCILIATION_ENABLED=False,
        FREE_TIER_UNLIMITED=False,
    )
    def test_charge_stays_closed_without_reconciliation(self):
        RuntimeConfig.solo().billing_recurring_charge_enabled = True
        RuntimeConfig.solo().save()
        self.assertFalse(recurring_charge_enabled())
```

- [ ] **Step 2: Add exact environment settings**

```python
BILLING_CARD_REGISTRATION_ENABLED = env.bool(
    'BILLING_CARD_REGISTRATION_ENABLED', default=False)
BILLING_RECURRING_CHARGE_ENABLED = env.bool(
    'BILLING_RECURRING_CHARGE_ENABLED', default=False)
BILLING_WEBHOOK_RECONCILIATION_ENABLED = env.bool(
    'BILLING_WEBHOOK_RECONCILIATION_ENABLED', default=False)
KICC_MALL_ID = env('KICC_MALL_ID', default='')
KICC_CLIENT_SECRET = env('KICC_CLIENT_SECRET', default='')
KICC_API_BASE_URL = env('KICC_API_BASE_URL', default='')
PAYMENT_TOKEN_ENCRYPTION_KEY = env('PAYMENT_TOKEN_ENCRYPTION_KEY', default='')
PAYMENT_TOKEN_KEY_VERSION = env('PAYMENT_TOKEN_KEY_VERSION', default='v1')
```

`.env.example`에는 이름과 안전한 설명만 넣고 실제 값은 넣지 않는다.

- [ ] **Step 3: Add focused ledger models**

```python
class BillingAgreement(models.Model):
    STATUS_CHOICES = [(v, v) for v in (
        'trialing', 'renewal_processing', 'active',
        'past_due_unknown', 'canceled', 'free')]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    plan = models.ForeignKey('billing.Plan', on_delete=models.PROTECT)
    status = models.CharField(max_length=24, choices=STATUS_CHOICES)
    billing_anchor_day = models.PositiveSmallIntegerField()
    cycle_sequence = models.PositiveIntegerField(default=0)
    current_period_starts_on = models.DateField()
    current_period_ends_on = models.DateField()
    next_charge_date = models.DateField(null=True, blank=True)
    canceled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class PaymentMethodToken(models.Model):
    STATUS_CHOICES = [(v, v) for v in (
        'active', 'revocation_pending', 'revoked')]
    agreement = models.ForeignKey(BillingAgreement, on_delete=models.CASCADE)
    encrypted_token = models.TextField()
    key_version = models.CharField(max_length=20)
    card_brand = models.CharField(max_length=40, blank=True, default='')
    card_last4 = models.CharField(max_length=4, blank=True, default='')
    status = models.CharField(max_length=24, choices=STATUS_CHOICES)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['agreement'], condition=models.Q(status='active'),
            name='uniq_billing_active_token')]

    @property
    def display_label(self):
        return f'{self.card_brand} 끝 {self.card_last4}'


class PaymentOrder(models.Model):
    STATUS_CHOICES = [(v, v) for v in (
        'created', 'submitted', 'approved', 'declined',
        'unknown', 'canceled', 'refunded')]
    agreement = models.ForeignKey(BillingAgreement, on_delete=models.PROTECT)
    cycle_sequence = models.PositiveIntegerField()
    merchant_order_id = models.CharField(max_length=80, unique=True)
    amount_krw = models.PositiveIntegerField()
    due_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    failure_code = models.CharField(max_length=40, blank=True, default='')
    unknown_since = models.DateTimeField(null=True, blank=True)
    temporary_access_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['agreement', 'cycle_sequence'],
            name='uniq_billing_agreement_cycle')]


class RecurringPaymentConsent(models.Model):
    KIND_CHOICES = (('trial_start', 'trial_start'), ('first_charge', 'first_charge'))
    agreement = models.ForeignKey(BillingAgreement, on_delete=models.PROTECT)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    consent_version = models.CharField(max_length=40)
    amount_krw = models.PositiveIntegerField()
    charge_date = models.DateField()
    display_snapshot_hash = models.CharField(max_length=64)
    accepted_at = models.DateTimeField()
    network_hmac = models.CharField(max_length=64, blank=True, default='')
    user_agent_hash = models.CharField(max_length=64, blank=True, default='')

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['agreement', 'kind', 'charge_date', 'display_snapshot_hash'],
            name='uniq_billing_consent_snapshot')]


class PaymentAttempt(models.Model):
    order = models.ForeignKey(PaymentOrder, on_delete=models.PROTECT)
    attempt_no = models.PositiveSmallIntegerField()
    provider_request_id = models.CharField(max_length=80, unique=True)
    result_kind = models.CharField(
        max_length=20, choices=[(v, v) for v in ('approved', 'declined', 'unknown')],
        blank=True, default='')
    provider_transaction_id = models.CharField(
        max_length=120, unique=True, null=True, blank=True)
    provider_code = models.CharField(max_length=40, blank=True, default='')
    response_hash = models.CharField(max_length=64, blank=True, default='')
    started_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['order', 'attempt_no'], name='uniq_billing_order_attempt')]


class WebhookInbox(models.Model):
    STATUS_CHOICES = [(v, v) for v in ('received', 'verified', 'processed', 'rejected')]
    provider_event_id = models.CharField(max_length=120, unique=True)
    payload_hash = models.CharField(max_length=64)
    signature_valid = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)


class BillingNoticeEvent(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    event_key = models.CharField(max_length=120)
    notice_type = models.CharField(max_length=40)
    reason = models.CharField(max_length=40)
    lease_device_hash = models.CharField(max_length=64, blank=True, default='')
    lease_until = models.DateTimeField(null=True, blank=True)
    rendered_at = models.DateTimeField(null=True, blank=True)
    dismissed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['user', 'event_key', 'notice_type'],
            name='uniq_billing_notice_event')]


class CouponClaim(models.Model):
    STATUS_CHOICES = [(v, v) for v in ('held', 'redeemed', 'released', 'expired')]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    coupon = models.ForeignKey('billing.Coupon', on_delete=models.PROTECT)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    expires_at = models.DateTimeField()
    policy_snapshot = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    redeemed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['coupon', 'user'],
            condition=models.Q(status__in=('held', 'redeemed')),
            name='uniq_billing_live_coupon_claim')]
```

`inpa_be/inpa/billing/models.py` 마지막에서 위 모델을 명시적으로 import해 Django app registry와 기존 import 경로에서 찾을 수 있게 한다. 원문이나 원본 IP는 저장하지 않는다.

```python
from .payment_models import (  # noqa: E402,F401
    BillingAgreement, BillingNoticeEvent, CouponClaim, PaymentAttempt,
    PaymentMethodToken, PaymentOrder, RecurringPaymentConsent, WebhookInbox,
)
```

- [ ] **Step 4: Add RuntimeConfig switches and gate helpers**

```python
def recurring_charge_enabled() -> bool:
    cfg = RuntimeConfig.solo()
    return all((
        settings.BILLING_CARD_REGISTRATION_ENABLED,
        settings.BILLING_RECURRING_CHARGE_ENABLED,
        settings.BILLING_WEBHOOK_RECONCILIATION_ENABLED,
        cfg.billing_card_registration_enabled,
        cfg.billing_recurring_charge_enabled,
        cfg.billing_reconciliation_enabled,
        not cfg.free_tier_unlimited,
        bool(settings.KICC_MALL_ID),
        bool(settings.KICC_CLIENT_SECRET),
        bool(settings.PAYMENT_TOKEN_ENCRYPTION_KEY),
    ))
```

- [ ] **Step 5: Generate migration and test**

Run: `cd inpa_be && python manage.py makemigrations billing && python manage.py migrate && python manage.py test inpa.billing.test_payment_models -v 2`

Expected: migration applies, constraints and all default-closed cases PASS.

- [ ] **Step 6: Commit**

```bash
git add inpa_be/inpa/billing inpa_be/config/settings/base.py inpa_be/.env.example
git commit -m "feat(결제): 정기결제 원장과 안전 게이트 추가"
```

### Task 3: 기존 쿠폰 호환과 1~3개월 점유

**Files:**
- Modify: `inpa_be/inpa/billing/models.py`
- Modify: `inpa_be/inpa/billing/coupons.py`
- Modify: `inpa_be/inpa/billing/admin.py`
- Create migration: `billing`
- Test: `inpa_be/inpa/billing/test_recurring_coupon.py`

**Interfaces:**
- Produces: `preflight_recurring_coupon(user, code) -> CouponPreview`
- Produces: `hold_recurring_coupon(user, code) -> CouponClaim`
- Produces: `redeem_held_coupon(claim, agreement) -> Subscription`

- [ ] **Step 1: Write failing legacy and concurrent-last-seat tests**

```python
def test_recurring_coupon_accepts_only_one_to_three_months(self):
    for months in (1, 2, 3):
        coupon = Coupon(coupon_kind='recurring_trial', duration_months=months)
        coupon.full_clean()
    for months in (0, 4):
        with self.assertRaises(ValidationError):
            Coupon(coupon_kind='recurring_trial', duration_months=months).full_clean()

def test_legacy_coupon_keeps_duration_days_behavior(self):
    result = redeem_coupon(self.user, self.legacy.code)
    self.assertEqual(result['duration_days'], self.legacy.duration_days)

def test_last_seat_can_be_held_by_only_one_user(self):
    results = run_two_postgres_threads(
        lambda user: hold_recurring_coupon(user, self.coupon.code),
        self.user_a, self.user_b)
    self.assertEqual(sum(result.ok for result in results), 1)
```

- [ ] **Step 2: Extend Coupon without rewriting legacy benefits**

```python
COUPON_KIND_CHOICES = (
    ('legacy_grant', '기존 일수형'),
    ('recurring_trial', '카드 등록형 무료 체험'),
)
coupon_kind = models.CharField(
    max_length=24, choices=COUPON_KIND_CHOICES, default='legacy_grant')
duration_months = models.PositiveSmallIntegerField(null=True, blank=True)
redeem_by = models.DateTimeField(null=True, blank=True)
```

`CheckConstraint`로 `recurring_trial`일 때 `duration_months`가 1~3이고 `legacy_grant`일 때 기존 `duration_days`가 양수인 것을 보장한다. 데이터 마이그레이션은 모든 기존 행을 `legacy_grant`로 채우고 `redeem_by=expires_at`으로 복사한다. 기존 `CouponRedemption`을 변경하거나 달력 쿠폰으로 바꾸지 않는다.

- [ ] **Step 3: Implement 15-minute hold**

```python
def hold_recurring_coupon(user, raw_code):
    with transaction.atomic():
        coupon = (Coupon.objects.select_for_update()
                  .select_related('plan').get(code=normalize_code(raw_code)))
        release_expired_claims(coupon, timezone.now())
        validate_recurring_coupon(coupon, user)
        active_claims = CouponClaim.objects.filter(
            coupon=coupon, status__in=('held', 'redeemed')).count()
        if active_claims >= coupon.max_redemptions:
            raise CouponError('exhausted', _MESSAGES['exhausted'])
        return CouponClaim.objects.create(
            coupon=coupon, user=user, status='held',
            expires_at=timezone.now() + timedelta(minutes=15),
            policy_snapshot=coupon_policy_snapshot(coupon))
```

- [ ] **Step 4: Finalize only after card registration**

`redeem_held_coupon`은 claim과 coupon을 `select_for_update`하고 `held`, 미만료, 같은 user, 활성 결제수단, 현재버전 무료 시작 동의를 모두 확인한다. 달력 기간을 계산해 `BillingAgreement`, `Subscription`, `CouponRedemption`을 한 트랜잭션에서 확정하고 claim을 `redeemed`로 바꾼다.

- [ ] **Step 5: Run legacy and PostgreSQL concurrency tests**

Run: `cd inpa_be && python manage.py test inpa.billing.test_recurring_coupon inpa.billing.tests -v 1`

Run: `cd inpa_be && DJANGO_SETTINGS_MODULE=config.settings.test_postgres python manage.py test inpa.billing.test_recurring_coupon -v 2`

Expected: legacy tests unchanged, concurrent final seat has exactly one winner.

- [ ] **Step 6: Commit**

```bash
git add inpa_be/inpa/billing
git commit -m "feat(쿠폰): 카드 등록형 1~3개월 점유 추가"
```

### Task 4: 빌키 암호화와 KICC adapter

**Files:**
- Modify: `inpa_be/requirements.txt`
- Create: `inpa_be/inpa/billing/payment_tokens.py`
- Create: `inpa_be/inpa/billing/kicc.py`
- Test: `inpa_be/inpa/billing/test_kicc.py`
- Test: `inpa_be/inpa/billing/test_payment_tokens.py`

**Interfaces:**
- Produces: `encrypt_billing_token(raw: str) -> EncryptedToken`
- Produces: `decrypt_billing_token(token: PaymentMethodToken) -> str`
- Produces: `KiccBillingClient.issue_key(auth_id, order_id)`
- Produces: `KiccBillingClient.charge(order, billing_key)`
- Produces: `KiccBillingClient.query(order)`
- Produces: `KiccBillingClient.revoke_key(billing_key)`
- Produces: `KiccBillingClient.cancel(transaction_id, amount_krw, reason)`

- [ ] **Step 1: Write failing redaction, tamper, and timeout tests**

```python
def test_encrypted_token_does_not_contain_plain_billing_key(self):
    encrypted = encrypt_billing_token('secret-billing-key')
    self.assertNotIn('secret-billing-key', encrypted.ciphertext)
    self.assertEqual(decrypt_billing_token_object(encrypted), 'secret-billing-key')

def test_charge_validates_order_amount_and_merchant(self):
    self.http.post.return_value = fake_response(
        mall_id='wrong', order_no='INPA-1', amount=21890, result='0000')
    with self.assertRaises(KiccIntegrityError):
        self.client.charge(self.order, 'bill-key')

def test_timeout_returns_unknown_and_never_retries_post(self):
    self.http.post.side_effect = TimeoutError()
    result = self.client.charge(self.order, 'bill-key')
    self.assertEqual(result.kind, 'unknown')
    self.assertEqual(self.http.post.call_count, 1)
```

- [ ] **Step 2: Pin the encryption dependency already proven in the project venv**

Add `cryptography==49.0.0` to `inpa_be/requirements.txt`, then run:

Run: `cd inpa_be && pip install -r requirements.txt && python -c "import cryptography; print(cryptography.__version__)"`

Expected: `49.0.0`.

- [ ] **Step 3: Implement token encryption**

```python
@dataclass(frozen=True)
class EncryptedToken:
    ciphertext: str
    key_version: str


def encrypt_billing_token(raw: str) -> EncryptedToken:
    if not raw or not settings.PAYMENT_TOKEN_ENCRYPTION_KEY:
        raise PaymentConfigurationError('PAYMENT_TOKEN_KEY_MISSING')
    fernet = Fernet(settings.PAYMENT_TOKEN_ENCRYPTION_KEY.encode())
    return EncryptedToken(
        ciphertext=fernet.encrypt(raw.encode()).decode(),
        key_version=settings.PAYMENT_TOKEN_KEY_VERSION,
    )
```

- [ ] **Step 4: Implement one non-retrying KICC request gate**

```python
@dataclass(frozen=True)
class ChargeResult:
    kind: Literal['approved', 'declined', 'unknown']
    provider_transaction_id: str = ''
    code: str = ''


class KiccBillingClient:
    def charge(self, order, billing_key) -> ChargeResult:
        try:
            response = self._post_charge_once(order, billing_key)
        except (TimeoutError, OSError):
            return ChargeResult(kind='unknown', code='TRANSPORT_UNKNOWN')
        self._validate_common(response, order)
        return self._parse_charge_result(response)
```

실제 JSON key, 서명·해시 계산, URL은 KICC 운영 계약 문서와 공식 빌링 API 문서를 기준으로 adapter 내부 상수에만 둔다. 테스트 fixture는 카드번호·실제 빌키 없이 공급자 코드와 금액만 사용한다.

- [ ] **Step 5: Run adapter tests and secret scan**

Run: `cd inpa_be && python manage.py test inpa.billing.test_kicc inpa.billing.test_payment_tokens -v 2`

Run: `git diff --check && gitleaks git --no-banner`

Expected: adapter PASS, plaintext token absent, gitleaks 0 findings.

- [ ] **Step 6: Commit**

```bash
git add inpa_be/requirements.txt inpa_be/inpa/billing/kicc.py inpa_be/inpa/billing/payment_tokens.py inpa_be/inpa/billing/test_kicc.py inpa_be/inpa/billing/test_payment_tokens.py
git commit -m "security(결제): 빌키 암호화와 KICC 호출 격리"
```

### Task 5: 카드 등록·무료 시작 동의·쿠폰 확정 API

**Files:**
- Create: `inpa_be/inpa/billing/agreements.py`
- Modify: `inpa_be/inpa/billing/views.py`
- Modify: `inpa_be/inpa/billing/serializers.py`
- Modify: `inpa_be/inpa/billing/urls.py`
- Modify: `inpa_be/inpa/billing/legal_texts.py`
- Test: `inpa_be/inpa/billing/test_card_registration.py`

**Interfaces:**
- Produces endpoints:
  - `POST /api/v1/billing/coupons/preflight/`
  - `POST /api/v1/billing/card-registration/start/`
  - `POST /api/v1/billing/card-registration/complete/`
  - `GET /api/v1/billing/status/`

- [ ] **Step 1: Write failing owner, claim-expiry, and late-callback tests**

```python
def test_card_registration_requires_users_own_live_claim(self):
    response = self.other_client.post('/api/v1/billing/card-registration/start/', {
        'claim_id': str(self.claim.id),
        'initial_consent_version': INITIAL_BILLING_CONSENT_VERSION,
    })
    self.assertEqual(response.status_code, 404)

def test_late_success_revokes_key_without_redeeming_coupon(self):
    self.claim.expires_at = timezone.now() - timedelta(seconds=1)
    self.claim.save()
    response = self.client.post('/api/v1/billing/card-registration/complete/', {
        'state': self.signed_state, 'auth_id': 'late-auth'})
    self.assertEqual(response.status_code, 410)
    self.assertEqual(self.kicc.revoke_key.call_count, 1)
    self.assertFalse(CouponRedemption.objects.exists())
```

- [ ] **Step 2: Centralize versioned consent copy**

```python
INITIAL_BILLING_CONSENT_VERSION = 'v1-2026-07-26'
INITIAL_BILLING_CONSENT = {
    'title': '무료 이용과 카드 등록 확인',
    'items': [
        '표시된 날짜까지 무료로 이용합니다.',
        '첫 유료 결제 전 결제일과 금액을 다시 확인합니다.',
        '다시 확인하지 않으면 결제하지 않고 무료 요금제로 전환합니다.',
        '설정 > 결제에서 언제든 다음 결제를 멈출 수 있습니다.',
    ],
}
```

문구의 실질 변경은 버전을 올리고 새 약정에만 적용한다.

- [ ] **Step 3: Implement start and complete services**

```python
def complete_registration(*, user, claim_id, auth_id, signed_state):
    state = verify_registration_state(signed_state, user=user, claim_id=claim_id)
    issue = KiccBillingClient().issue_key(auth_id=auth_id, order_id=state.order_id)
    encrypted = encrypt_billing_token(issue.billing_key)
    try:
        with transaction.atomic():
            claim = lock_live_claim(user=user, claim_id=claim_id)
            consent = create_initial_consent(user, claim)
            agreement = create_trial_agreement(user, claim)
            store_active_token(agreement, encrypted, issue.masked_card)
            redeem_held_coupon(claim, agreement)
            return agreement
    except Exception:
        schedule_key_revocation(issue.billing_key)
        raise
```

- [ ] **Step 4: Add server-authoritative response**

`GET /billing/status/`는 현재 플랜, trial/active/free 상태, 무료 이용 가능일, 첫/다음 결제일, VAT 포함 금액, 마스킹 카드, 재확인 필요 여부, 해지 효과, 미확정 상태, 표시할 안내 사건만 반환한다. 빌키·provider transaction ID는 반환하지 않는다.

- [ ] **Step 5: Run API tests**

Run: `cd inpa_be && python manage.py test inpa.billing.test_card_registration -v 2`

Expected: gate, owner, signed state, claim expiry, late callback cleanup PASS.

- [ ] **Step 6: Commit**

```bash
git add inpa_be/inpa/billing
git commit -m "feat(결제): 카드 등록형 쿠폰 시작 API 추가"
```

### Task 6: 첫 유료 결제 재확인

**Files:**
- Modify: `inpa_be/inpa/billing/legal_texts.py`
- Modify: `inpa_be/inpa/billing/agreements.py`
- Modify: `inpa_be/inpa/billing/views.py`
- Modify: `inpa_be/inpa/billing/urls.py`
- Test: `inpa_be/inpa/billing/test_reconfirmation.py`

**Interfaces:**
- Produces: `reconfirmation_window(agreement) -> DateTimeRange`
- Produces endpoint: `POST /api/v1/billing/reconfirm/`
- Produces: `has_current_reconfirmation(agreement, charge_date, amount_krw) -> bool`

- [ ] **Step 1: Write failing 1-, 2-, 3-month window and snapshot tests**

```python
def test_one_month_window_opens_seven_days_before(self):
    agreement = trial_agreement(months=1, charge_date=date(2027, 2, 5))
    window = reconfirmation_window(agreement)
    self.assertEqual(window.opens_at, kst_midnight(date(2027, 1, 29)))
    self.assertEqual(window.closes_at, kst_midnight(date(2027, 2, 5)))

def test_two_and_three_month_windows_open_thirty_days_before(self):
    for months in (2, 3):
        agreement = trial_agreement(months=months)
        self.assertEqual(
            reconfirmation_window(agreement).opens_at.date(),
            agreement.next_charge_date - timedelta(days=30))

def test_amount_change_invalidates_old_reconfirmation(self):
    consent = confirm_first_charge(self.agreement, amount_krw=21890)
    self.assertFalse(has_current_reconfirmation(
        self.agreement, self.agreement.next_charge_date, amount_krw=43890))
```

- [ ] **Step 2: Add immutable display snapshot**

```python
def reconfirmation_snapshot(agreement):
    amount = vat_inclusive_amount(agreement.plan.price_krw)
    return {
        'plan_code': agreement.plan.code,
        'amount_krw': amount,
        'charge_date': agreement.next_charge_date.isoformat(),
        'card_label': active_token(agreement).display_label,
        'cancel_path': '/settings/billing',
        'cancel_effect': agreement.current_period_ends_on.isoformat(),
        'consent_version': FIRST_CHARGE_CONSENT_VERSION,
    }
```

DB에는 canonical JSON의 SHA-256과 `plan_code`, `amount_krw`, `charge_date`, `card_label`, `cancel_path`, `cancel_effect`, `consent_version`을 구조 필드로 저장한다. 사용자 화면에 보여준 정확한 값은 serializer로 다시 만들 수 있어야 한다.

- [ ] **Step 3: Implement locked confirmation**

`POST /billing/reconfirm/`은 agreement를 user scope로 잠그고 현재 window, 활성 빌키, 현재 가격, 같은 charge date를 검증한다. 같은 스냅샷의 반복 POST는 기존 동의를 반환하고, 가격·날짜·카드가 바뀌면 새 동의를 요구한다.

- [ ] **Step 4: Run tests**

Run: `cd inpa_be && python manage.py test inpa.billing.test_reconfirmation -v 2`

Expected: calendar windows, exact snapshot, idempotency, owner checks PASS.

- [ ] **Step 5: Commit**

```bash
git add inpa_be/inpa/billing
git commit -m "feat(결제): 첫 유료 결제 재확인 추가"
```

### Task 7: 정기 승인과 이용 권한 투영

**Files:**
- Create: `inpa_be/inpa/billing/recurring.py`
- Create: `inpa_be/inpa/billing/tasks.py`
- Modify: `inpa_be/inpa/billing/credit.py`
- Test: `inpa_be/inpa/billing/test_recurring_charge.py`
- Test: `inpa_be/inpa/billing/test_recurring_concurrency.py`

**Interfaces:**
- Produces: `create_due_order(agreement_id, due_date) -> PaymentOrder`
- Produces: `charge_order(order_id) -> PaymentOrder`
- Produces: `project_subscription(agreement) -> Subscription`

- [ ] **Step 1: Write failing duplicate-worker and no-reconfirmation tests**

```python
def test_two_workers_create_and_charge_one_order(self):
    orders = run_two_postgres_threads(
        lambda: create_and_charge_due_agreement(self.agreement.id, self.due_date))
    self.assertEqual(PaymentOrder.objects.count(), 1)
    self.assertEqual(self.kicc.charge.call_count, 1)

def test_missing_reconfirmation_never_calls_provider(self):
    order = create_due_order(self.agreement.id, self.due_date)
    result = charge_order(order.id)
    self.assertEqual(result.status, 'declined')
    self.assertEqual(result.failure_code, 'RECONFIRMATION_MISSING')
    self.assertEqual(self.kicc.charge.call_count, 0)
    self.assertEqual(current_plan(self.user).code, 'free')
```

- [ ] **Step 2: Create a permanent cycle order before external I/O**

```python
def create_due_order(agreement_id, due_date):
    with transaction.atomic():
        agreement = BillingAgreement.objects.select_for_update().get(pk=agreement_id)
        validate_due_date(agreement, due_date)
        sequence = agreement.cycle_sequence + 1
        order, _ = PaymentOrder.objects.get_or_create(
            agreement=agreement, cycle_sequence=sequence,
            defaults={
                'merchant_order_id': make_order_id(agreement, sequence),
                'amount_krw': vat_inclusive_amount(agreement.plan.price_krw),
                'due_date': due_date,
                'status': 'created',
            })
        return order
```

- [ ] **Step 3: Implement one external attempt and atomic settlement**

`charge_order`은 order를 잠가 `created`만 `submitted`로 바꾸고 커밋한 뒤 KICC를 한 번 호출한다. approved이면 새 트랜잭션에서 order·agreement를 다시 잠가 금액과 provider ID를 검증하고 `Subscription`을 같은 날짜 구간으로 투영한다. declined이면 빌키 폐기와 Free 전환을 예약한다. unknown이면 24시간 임시 이용을 주고 조회 task를 예약한다.

- [ ] **Step 4: Preserve customer data on downgrade**

```python
def project_free_entitlement(user, *, reason, event_key):
    free = Plan.objects.get(code='free')
    sub = Subscription.objects.select_for_update().get(user=user)
    sub.plan = free
    sub.status = 'active'
    sub.expires_at = None
    sub.auto_renew = False
    sub.next_billing_at = None
    sub.save(update_fields=[
        'plan', 'status', 'expires_at', 'auto_renew', 'next_billing_at'])
    create_free_transition_notice(user=user, reason=reason, event_key=event_key)
```

`Customer`, `CustomerMemo`, `Meeting`, `ScheduleItem`은 수정하거나 삭제하지 않는다. 회귀 테스트는 무료 전환 뒤 기존 고객 detail, memo GET/PATCH가 200이고 새 비용 기능만 Free 한도를 적용하는지 확인한다.

- [ ] **Step 5: Run SQLite and PostgreSQL concurrency tests**

Run: `cd inpa_be && python manage.py test inpa.billing.test_recurring_charge -v 2`

Run: `cd inpa_be && DJANGO_SETTINGS_MODULE=config.settings.test_postgres python manage.py test inpa.billing.test_recurring_concurrency -v 2`

Expected: provider call one, order one, entitlement projection correct.

- [ ] **Step 6: Commit**

```bash
git add inpa_be/inpa/billing
git commit -m "feat(결제): 중복 없는 월 정기 승인 구현"
```

### Task 8: 미확정 대사·늦은 승인·빌키 폐기

**Files:**
- Create: `inpa_be/inpa/billing/reconciliation.py`
- Modify: `inpa_be/inpa/billing/tasks.py`
- Create: `inpa_be/inpa/billing/management/commands/run_billing_reconciliation.py`
- Modify: `render.yaml`
- Test: `inpa_be/inpa/billing/test_reconciliation.py`

**Interfaces:**
- Produces: `reconcile_unknown_order(order_id) -> PaymentOrder`
- Produces: `revoke_payment_token(token_id) -> PaymentMethodToken`
- Produces command: `python manage.py run_billing_reconciliation`

- [ ] **Step 1: Write failing query-only and late-approval tests**

```python
def test_unknown_reconciliation_never_recharges(self):
    reconcile_unknown_order(self.order.id)
    self.assertEqual(self.kicc.query.call_count, 1)
    self.assertEqual(self.kicc.charge.call_count, 0)

def test_approval_found_after_twenty_four_hours_is_canceled(self):
    self.order.unknown_since = timezone.now() - timedelta(hours=25)
    self.kicc.query.return_value = approved_result(transaction_id='tx-late')
    reconcile_unknown_order(self.order.id)
    self.assertEqual(self.kicc.cancel.call_count, 1)
    self.assertEqual(self.order.refresh_from_db().status, 'canceled')
```

- [ ] **Step 2: Implement finite reconciliation**

5분과 30분 Celery task는 같은 order를 조회한다. 24시간까지 approved이면 정상 확정하고 declined이면 Free로 전환한다. 24시간 뒤 approved이면 전액 취소하고, 계속 unknown이면 임시 이용을 끝내고 운영 대기열에 남긴다. 작업은 order 상태 잠금과 provider transaction ID 유일성으로 반복 실행에 안전해야 한다.

- [ ] **Step 3: Implement token revocation retry**

`PaymentMethodToken`을 `revocation_pending`으로 먼저 커밋하고 provider 삭제 성공 뒤 `revoked`로 바꾼다. 실패 시 비밀값이나 응답 본문 없이 오류 enum과 재시도 횟수만 남기고 1분, 5분, 30분, 6시간 간격으로 재시도한다.

- [ ] **Step 4: Add hourly safety job**

`run_billing_reconciliation`은 due인데 주문이 없는 agreement, unknown order, revocation_pending token, 처리되지 않은 검증 완료 webhook만 찾는다. 새 정기 승인은 `BILLING_RECURRING_CHARGE_ENABLED`가 열렸을 때만 만들고, 정리·취소·대사는 게이트가 닫혀도 계속 수행한다.

- [ ] **Step 5: Run tests**

Run: `cd inpa_be && python manage.py test inpa.billing.test_reconciliation -v 2`

Expected: unknown query-only, late approval cancel, repeated task idempotency PASS.

- [ ] **Step 6: Commit**

```bash
git add inpa_be/inpa/billing render.yaml
git commit -m "feat(결제): 미확정 대사와 결제키 폐기 자동화"
```

### Task 9: 해지와 사건별 1회 무료 전환 안내 API

**Files:**
- Create: `inpa_be/inpa/billing/notices.py`
- Modify: `inpa_be/inpa/billing/views.py`
- Modify: `inpa_be/inpa/billing/urls.py`
- Test: `inpa_be/inpa/billing/test_cancellation_notice.py`

**Interfaces:**
- Produces endpoint: `POST /api/v1/billing/cancel/`
- Produces endpoints:
  - `POST /api/v1/billing/notices/lease/`
  - `POST /api/v1/billing/notices/{id}/rendered/`
  - `POST /api/v1/billing/notices/{id}/dismiss/`

- [ ] **Step 1: Write failing access-through-period and multi-device tests**

```python
def test_cancel_stops_future_charge_but_keeps_current_period(self):
    response = self.client.post('/api/v1/billing/cancel/')
    self.assertEqual(response.status_code, 200)
    self.agreement.refresh_from_db()
    self.assertEqual(self.agreement.status, 'canceled')
    self.assertEqual(
        Subscription.objects.get(user=self.user).expires_at.date(),
        self.agreement.current_period_ends_on)

def test_two_devices_receive_one_render_lease(self):
    first, second = run_two_postgres_threads(
        lambda: lease_notice(self.user, device_id=str(uuid.uuid4())),
        lambda: lease_notice(self.user, device_id=str(uuid.uuid4())))
    self.assertEqual(sum(bool(item) for item in (first, second)), 1)
```

- [ ] **Step 2: Implement cancellation**

약정과 활성 token을 잠그고 agreement를 `canceled`, Subscription을 현재 기간 종료형으로 투영한 뒤 token을 `revocation_pending`으로 바꾼다. 제공사 폐기는 트랜잭션 커밋 뒤 task로 실행한다. 반복 요청은 같은 종료일을 반환한다.

- [ ] **Step 3: Implement lease and render acknowledgement**

```python
def lease_notice(user, device_id):
    with transaction.atomic():
        notice = (BillingNoticeEvent.objects.select_for_update(skip_locked=True)
                  .filter(user=user, rendered_at__isnull=True)
                  .filter(Q(lease_until__isnull=True) | Q(lease_until__lt=timezone.now()))
                  .order_by('created_at').first())
        if not notice:
            return None
        notice.lease_device_hash = hmac_device(device_id)
        notice.lease_until = timezone.now() + timedelta(minutes=2)
        notice.save(update_fields=['lease_device_hash', 'lease_until'])
        return notice
```

`rendered` endpoint는 같은 device lease만 확인하고 실제 렌더 뒤 `rendered_at`을 찍는다. `dismiss`는 닫은 시각만 기록한다. 사건별 유일 제약 때문에 같은 실패 사건의 큰 팝업은 다시 만들지 않는다.

- [ ] **Step 4: Run tests**

Run: `cd inpa_be && python manage.py test inpa.billing.test_cancellation_notice -v 2`

Expected: cancel idempotency, period preservation, cross-device once PASS.

- [ ] **Step 5: Commit**

```bash
git add inpa_be/inpa/billing
git commit -m "feat(결제): 해지와 무료 전환 1회 안내 추가"
```

### Task 10: 사용자 결제 화면과 만료 안내

**Files:**
- Modify: `inpa_fe/lib/api.ts`
- Create: `inpa_fe/app/settings/billing/page.tsx`
- Create: `inpa_fe/components/billing/card-registration.tsx`
- Create: `inpa_fe/components/billing/first-charge-confirmation.tsx`
- Create: `inpa_fe/components/billing/free-transition-notice.tsx`
- Modify: `inpa_fe/app/settings/account/page.tsx`
- Modify: `inpa_fe/components/app-nav.tsx`
- Test: `inpa_fe/components/__tests__/billing-flow.test.tsx`
- Test: `inpa_fe/components/__tests__/billing-expiry-notice.test.tsx`

**Interfaces:**
- Consumes billing status, preflight, card registration, reconfirm, cancel, notice endpoints.
- Produces responsive settings and app-wide one-time notice.

- [ ] **Step 1: Write failing happy, error, unknown, and expiry UI tests**

```tsx
it("shows calendar dates and exact first charge amount", async () => {
  api.getBillingStatus.mockResolvedValue(trialStatus({
    accessThrough: "2027-02-04",
    nextChargeDate: "2027-02-05",
    amountKrw: 21890,
  }));
  render(<BillingPage />);
  expect(await screen.findByText("2027년 2월 4일까지 무료")).toBeInTheDocument();
  expect(screen.getByText("2027년 2월 5일 21,890원 결제 예정")).toBeInTheDocument();
});

it("keeps existing data message after free transition", async () => {
  api.leaseBillingNotice.mockResolvedValue(freeTransitionNotice());
  render(<FreeTransitionNotice />);
  expect(await screen.findByText("기존 고객과 메모는 그대로 보관돼요")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "카드 등록하고 다시 시작" })).toBeEnabled();
});
```

- [ ] **Step 2: Add exact API types in the single gateway**

```ts
export type BillingStatus =
  | { state: "free"; existingDataAvailable: true; notice?: BillingNotice }
  | { state: "trial"; accessThrough: string; nextChargeDate: string;
      amountKrw: number; reconfirmationRequired: boolean; cardLabel: string }
  | { state: "active"; accessThrough: string; nextChargeDate: string;
      amountKrw: number; cardLabel: string }
  | { state: "renewal_processing" | "past_due_unknown";
      temporaryAccessUntil: string; cardLabel: string };
```

- [ ] **Step 3: Implement card registration**

쿠폰 preflight 성공 뒤 서버가 주는 등록 파라미터만 KICC 창에 전달한다. 창 닫기, 사용자 취소, 네트워크 오류, 점유 만료를 각각 안내하고 “다시 카드 등록” 또는 “쿠폰 다시 확인” 행동을 제공한다. 클라이언트는 쿠폰을 사용 처리하지 않는다.

- [ ] **Step 4: Implement reconfirmation and cancellation**

재확인 카드에는 VAT 포함 금액, 결제 날짜, 마스킹 카드, 다음 결제 중단 경로와 종료일을 보여준다. 해지 확인창은 “다음 결제를 멈춰도 YYYY년 M월 D일까지 이용해요”를 보여주고 성공 뒤 상태를 다시 조회한다.

- [ ] **Step 5: Mount one-time notice**

인증된 앱 layout에서 `FreeTransitionNotice`를 한 번 mount한다. lease를 받은 컴포넌트만 팝업을 렌더하고 DOM commit 뒤 `rendered`를 보낸다. 닫은 뒤 `/settings/billing`의 작은 상태 안내는 유지한다.

- [ ] **Step 6: Run UI tests, copy lint, and build**

Run: `cd inpa_fe && npm run test:run -- components/__tests__/billing-flow.test.tsx components/__tests__/billing-expiry-notice.test.tsx`

Run: `cd inpa_fe && npm run lint:copy && npm run build`

Expected: all UI states PASS, 360px layout inspection PASS, copy lint 0, build PASS.

- [ ] **Step 7: Commit**

```bash
git add inpa_fe/lib/api.ts inpa_fe/app/settings inpa_fe/components/billing inpa_fe/components/app-nav.tsx inpa_fe/components/__tests__
git commit -m "feat(결제): 달력 쿠폰과 무료 전환 화면 구현"
```

### Task 11: 관리자 쿠폰·결제 운영 화면

**Files:**
- Modify: `inpa_be/inpa/admin_console/serializers.py`
- Modify: `inpa_be/inpa/admin_console/views.py`
- Modify: `inpa_be/inpa/admin_console/urls.py`
- Modify: `inpa_fe/lib/adminApi.ts`
- Create: `inpa_fe/app/admin/billing/page.tsx`
- Modify: `inpa_fe/app/admin/layout.tsx`
- Test: `inpa_be/inpa/admin_console/tests.py`
- Test: `inpa_fe/app/admin/billing/page.test.tsx`

**Interfaces:**
- Produces coupon CRUD, ledger summary, unknown/revocation/refund queues.
- Never produces billing key, raw provider body, customer memo, AI summary, recording content.

- [ ] **Step 1: Write failing redaction and coupon CRUD tests**

```python
def test_admin_billing_response_contains_ops_fields_without_secrets(self):
    response = self.client.get('/api/v1/admin/billing/overview/')
    encoded = json.dumps(response.data, ensure_ascii=False)
    for forbidden in ('encrypted_token', 'billing_key', 'card_number', 'memo_body'):
        self.assertNotIn(forbidden, encoded)
    self.assertIn('unknown_order_count', response.data['status'])

def test_admin_can_create_one_to_three_month_coupon(self):
    response = self.client.post('/api/v1/admin/billing/coupons/', {
        'plan_code': 'plus', 'duration_months': 2,
        'redeem_by': '2027-01-31T14:59:59Z', 'max_redemptions': 100})
    self.assertEqual(response.status_code, 201)
```

- [ ] **Step 2: Add admin endpoints**

```text
GET/POST /api/v1/admin/billing/coupons/
PATCH /api/v1/admin/billing/coupons/{id}/
GET /api/v1/admin/billing/agreements/
GET /api/v1/admin/billing/orders/
GET /api/v1/admin/billing/operations/
POST /api/v1/admin/billing/orders/{id}/reconcile/
POST /api/v1/admin/billing/orders/{id}/cancel/
POST /api/v1/admin/billing/tokens/{id}/revoke/
GET/PATCH /api/v1/admin/billing/settings/
```

모든 POST/PATCH는 `IsAdmin`, 입력 serializer, 감사 이벤트, idempotency key를 적용한다.

- [ ] **Step 3: Implement operator-focused UI**

쿠폰 CRUD, 환경 게이트, 운영 스위치, 약정, 결제 시도, `unknown`, 빌키 폐기 실패, 취소·환불을 탭으로 나눈다. 목록에는 사용자 ID·이메일, 상태, 금액, 날짜, 마스킹 카드만 표시한다. 빈 상태와 오류 상태에는 새로고침 또는 처리 행동을 둔다.

- [ ] **Step 4: Run admin tests**

Run: `cd inpa_be && python manage.py test inpa.admin_console inpa.billing -v 1`

Run: `cd inpa_fe && npm run test:run -- app/admin/billing/page.test.tsx && npm run build`

Expected: permission, redaction, CRUD, responsive admin page PASS.

- [ ] **Step 5: Commit**

```bash
git add inpa_be/inpa/admin_console inpa_fe/lib/adminApi.ts inpa_fe/app/admin
git commit -m "feat(관리자): 쿠폰과 정기결제 운영 화면 추가"
```

### Task 12: 보존·감사·관측과 전체 회귀

**Files:**
- Modify: `inpa_be/inpa/analytics/models.py`
- Modify: `inpa_be/inpa/analytics/history.py`
- Modify: `inpa_be/inpa/analytics/tests.py`
- Create: `docs/dev/29-recurring-billing-operations.md`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `.github/workflows/ci.yml` if PostgreSQL billing concurrency is not already covered

**Interfaces:**
- Produces content-free billing funnel and operations runbook.
- Produces deploy and rollback checklist.

- [ ] **Step 1: Add stable content-free events**

```text
billing_coupon_preflighted: duration_months, plan_code
billing_card_registration_started: plan_code
billing_trial_started: duration_months, plan_code
billing_reconfirmation_viewed: days_before
billing_reconfirmation_accepted: days_before
billing_charge_succeeded: plan_code, cycle_sequence
billing_charge_declined: provider_code_enum
billing_charge_unknown: age_bucket
billing_free_transitioned: reason_enum
billing_restart_started: source=notice|settings
```

사용자 ID FK와 enum·숫자만 저장하고 이메일, 카드 표시값, 고객 정보, 메모 원문은 payload에 넣지 않는다.

- [ ] **Step 2: Write data-retention and expected-event tests**

유료 → Free 전환 뒤 고객·메모 행 수와 본문 해시가 동일한지 검증한다. 결제 작업이 실행됐는데 10분 안에 성공·거절·unknown 이벤트가 하나도 없으면 운영 경고를 만드는 flatline 테스트를 추가한다.

- [ ] **Step 3: Write the exact operations runbook**

Runbook에는 KICC 샌드박스·운영 URL, Render/Vercel 환경변수 이름, 세 게이트 의존 순서, 카드 등록·승인·조회·취소·빌키 폐기 성공 신호, unknown 처리, 전액 취소, 롤백, 관리자 경로를 번호로 적는다. 실제 비밀값은 넣지 않는다.

- [ ] **Step 4: Run complete verification**

Run: `cd inpa_be && python manage.py check && python manage.py test inpa`

Run: `cd inpa_be && DJANGO_SETTINGS_MODULE=config.settings.test_postgres python manage.py test inpa.billing.test_recurring_concurrency inpa.billing.test_recurring_coupon`

Run: `cd inpa_fe && npm run test:run && npm run lint:copy && npm run build`

Run: `gitleaks git --no-banner`

Expected: all PASS, copy lint 0, gitleaks 0.

- [ ] **Step 5: KICC sandbox E2E**

기본 닫힘 게이트를 preview에서만 열고 아래를 실제 API로 확인한다.

```text
카드 등록 → 1개월 쿠폰 활성화 → 날짜 조회
첫 결제 재확인 → 승인 1건 → 이용권 연장
시간초과 모의 → 거래 조회로 복구, 재승인 0건
해지 → 빌키 폐기 → 기간 끝 Free
승인 1건 → 전체 취소 → KICC와 인파 원장 일치
```

- [ ] **Step 6: Commit docs and verification changes**

```bash
git add inpa_be/inpa/analytics docs/dev/29-recurring-billing-operations.md README.md AGENTS.md .github/workflows/ci.yml
git commit -m "docs(결제): 정기결제 운영과 검증 기준 반영"
```

### Task 13: master 통합·배포·운영 확인

**Files:**
- No new feature files; integration and deployment only.

**Interfaces:**
- Consumes all prior verified commits.
- Produces a default-closed production deployment and rollback point.

- [ ] **Step 1: Refresh remote state before integration**

Run: `git fetch origin`

Run: `git log --oneline origin/master..HEAD && git log --oneline HEAD..origin/master`

Expected: owned commits identified, unrelated remote commits reviewed.

- [ ] **Step 2: Rebase or merge latest master without touching user files**

Use the isolated worktree only. Resolve conflicts by preserving latest master behavior and rerun the complete Task 12 verification.

- [ ] **Step 3: Push feature branch and confirm CI**

Run: `git push -u origin codex/recurring-billing`

Expected: GitHub Actions backend, frontend, gitleaks jobs all success.

- [ ] **Step 4: Merge to master**

Create and merge the reviewed PR. Do not force-push master. Confirm the merge commit is present on `origin/master`.

- [ ] **Step 5: Verify production with gates closed**

Confirm:

```text
GET https://inpa-be.onrender.com/healthz/ → 200
GET https://www.inpa.kr/settings/billing → 200 after authentication
DB migrations applied
BILLING_CARD_REGISTRATION_ENABLED=False
BILLING_RECURRING_CHARGE_ENABLED=False
BILLING_WEBHOOK_RECONCILIATION_ENABLED=False
existing customer and memo API → 200
admin billing page loads without exposing secrets
```

- [ ] **Step 6: Monitor and document**

Watch Render/Vercel/Sentry for at least 5 minutes, confirm no migration, 5xx, latency, or expected-event flatline alert. Update `README.md` and `AGENTS.md` with the actual merge, CI run, deploy IDs, production checks, and remaining external activation conditions.

---

## 운영 결제 개방 게이트

코드 배포와 별개로 아래가 모두 충족돼야 카드 등록·정기 승인 스위치를 연다.

1. KICC 상점 심사와 운영 빌링 권한
2. KICC 샌드박스 등록·승인·조회·삭제·전체 취소
3. 최신 전자상거래 관련 문구 검토
4. PostgreSQL 중복 작업 시험
5. 실제 소액 승인·전체 취소·정산 확인
6. 관리자·CS 운영 지침
7. `FREE_TIER_UNLIMITED=False` 전환과 화면·API 한도 일치

조건이 부족하면 운영에는 코드를 배포하되 모든 신규 결제 게이트를 닫아 기존 계좌이체·쿠폰 흐름을 그대로 유지한다.
