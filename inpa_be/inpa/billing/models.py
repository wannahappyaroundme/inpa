"""요금제 도메인 모델 (dev/23, dev/02 §16).

모델 3종:
  Plan         — 요금제 정의 (공개 읽기 / 관리자 쓰기). code별 한도 필드.
  Subscription — 설계사 1:1 구독 상태 (소유자+관리자). MVP = 수동 활성화.
  UsageMeter   — 설계사 × action × 월 카운터 (소유자+관리자). lazy reset 방식.

★ 가시성 매트릭스 (dev/02 §0, dev/23 §7):
  Plan        — 비로그인 GET 허용(AllowAny), 쓰기 IsAdmin.
  Subscription — OwnedQuerySetMixin(user 필드) + IsAdmin bypass.
  UsageMeter  — OwnedQuerySetMixin(user 필드) + IsAdmin bypass.

★ 정직성 레드라인:
  - 한도 초과 = 기능 차단 X, 업그레이드 안내 소프트 블록(402 Payment Required).
  - share_link / customer_add 는 이 모델에서 제한하지 않는다(북극성 계측 차단 금지).
"""
import secrets
import string

from django.conf import settings
from django.db import models
from django.utils import timezone


class Plan(models.Model):
    """요금제 정의. 관리자가 Django Admin에서 직접 수정(코드 배포 없이 한도·가격 변경 가능).

    limit_* = null → 무제한 sentinel (remaining이 아닌 is_unlimited 판별).
    FREE_TIER_UNLIMITED=True(베타) 시 Plan 한도는 무시됨 — credit.py 레이어에서 우회.
    """
    PLAN_CODE = (
        ('free', 'Free'),
        ('plus', 'Plus'),
    )

    code = models.CharField(max_length=20, unique=True, choices=PLAN_CODE)
    display_name = models.CharField('표시 이름', max_length=50)
    price_krw = models.PositiveIntegerField('월 요금(원)', default=0)
    description = models.TextField('설명(관리자 메모)', blank=True)

    # action별 월 한도 (정본 4종 — dev/02 §16, dev/23 §1.2)
    # null = 무제한 sentinel. 이 필드 이름은 UsageMeter.action 코드와 1:1 대응
    limit_ocr = models.PositiveIntegerField(
        'OCR 한도(월)', null=True, blank=True, default=10,
        help_text='null=무제한. Free 기본 10건.'
    )
    limit_ai_compare = models.PositiveIntegerField(
        'AI비교안내서 한도(월)', null=True, blank=True, default=5,
        help_text='null=무제한. Free 기본 5건.'
    )
    limit_analysis = models.PositiveIntegerField(
        'AI분석 한도(월)', null=True, blank=True, default=10,
        help_text='null=무제한. Free 기본 10건.'
    )
    limit_promotion = models.PositiveIntegerField(
        '판촉물 한도(월)', null=True, blank=True, default=5,
        help_text='null=무제한. Free 기본 5건.'
    )
    # share_link / customer_add = 절대 차단 금지 → 필드 없음 (dev/23 §1.2)

    is_active = models.BooleanField('활성', default=True,
                                    help_text='False 시 신규 Subscription 생성 불가.')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'billing_plan'
        verbose_name = '요금제'
        verbose_name_plural = '요금제'

    def __str__(self):
        return f'{self.display_name}({self.code})'

    def get_limit(self, action: str):
        """action 코드로 월 한도 반환. None = 무제한 sentinel."""
        field = f'limit_{action}'
        return getattr(self, field, None)


class Subscription(models.Model):
    """설계사 1:1 구독 상태.

    MVP: 관리자가 Django Admin에서 status·plan 수동 변경으로 Plus 활성화.
    pg_subscription_id: Phase 2 PG 자동 결제 연동 시 채움 (현재 미사용).

    OneToOneField(user) → OwnedQuerySetMixin은 owner_field='user' 로 사용.
    """
    STATUS = (
        ('active', '활성'),
        ('cancelled', '해지'),
        ('expired', '만료'),
        ('trial', '체험'),
    )

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='subscription',
        verbose_name='설계사',
    )
    plan = models.ForeignKey(
        Plan, on_delete=models.PROTECT,
        verbose_name='요금제',
    )
    status = models.CharField('상태', max_length=20, choices=STATUS, default='active')
    started_at = models.DateTimeField('시작 시각', auto_now_add=True)
    expires_at = models.DateTimeField('만료 시각', null=True, blank=True,
                                      help_text='null = 무기한(Free).')
    cancelled_at = models.DateTimeField('해지 시각', null=True, blank=True)
    # PG 연동 hook (MVP 미사용)
    pg_subscription_id = models.CharField(
        'PG 구독 ID', max_length=100, blank=True, default='',
        help_text='Phase 2 PG 자동 결제 연동 시 채움.'
    )

    class Meta:
        db_table = 'billing_subscription'
        verbose_name = '구독'
        verbose_name_plural = '구독'

    def __str__(self):
        return f'{self.user.email} / {self.plan.code} / {self.status}'

    def is_plus(self) -> bool:
        """Plus 플랜 활성 여부."""
        return self.plan.code == 'plus' and self.status == 'active'


class UsageMeter(models.Model):
    """설계사 × action × 월 사용 카운터.

    lazy reset: year_month가 현재 월과 다르면 get_or_create에서 새 행 = 자동 0 리셋.
    과거 행 보존 (히스토리 분석, dev/23 §8).
    select_for_update: race condition 방지 (AC-B8).

    ForeignKey(user) → OwnedQuerySetMixin은 owner_field='user' 로 사용.
    """
    ACTION_CHOICES = (
        ('ocr', 'OCR 증권 분석'),
        ('ai_compare', 'AI 비교안내서'),
        ('analysis', 'AI 분析·메시지'),
        ('promotion', '판촉물 주문'),
    )

    # action label 한글 매핑 (GET /billing/usage/ 응답용)
    ACTION_LABELS = {
        'ocr': '증권 OCR 분析',
        'ai_compare': 'AI 비교안내서',
        'analysis': 'AI 분析·메시지',
        'promotion': '판촉물 주문',
    }

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='usage_meters',
        verbose_name='설계사',
    )
    action = models.CharField('액션', max_length=30, choices=ACTION_CHOICES)
    year_month = models.CharField('연월(YYYY-MM)', max_length=7,
                                  help_text='예: "2026-06". lazy reset 기준.')
    count = models.PositiveIntegerField('사용 횟수', default=0)
    updated_at = models.DateTimeField('최종 수정', auto_now=True)

    class Meta:
        db_table = 'billing_usage_meter'
        unique_together = ('user', 'action', 'year_month')
        verbose_name = '사용량 미터'
        verbose_name_plural = '사용량 미터'
        indexes = [
            models.Index(fields=['user', 'year_month']),
        ]

    def __str__(self):
        return f'{self.user.email} / {self.action} / {self.year_month} = {self.count}'

    @classmethod
    def current_month(cls) -> str:
        """현재 연월 (YYYY-MM). lazy reset 비교 기준."""
        return timezone.now().strftime('%Y-%m')


class ClaudeApiLog(models.Model):
    """Claude API 호출당 토큰·비용 로깅 (관리자 전용 — dev/02 §14.2).

    ★ owner FK 없음: 운영 로그(설계사 본인 조회 불가, 관리자 전체 조회).
    월 예산 캡 집계·모델별 비용 추적·prompt caching 효율(cache_read 비율) 모니터링용.

    필드:
      - action: 호출 목적 (ocr_parse|compare_guide|message_gen 등). 자유 문자열.
      - model:  실제 호출된 Claude 모델 ID (settings CLAUDE_MODEL_PARSE/BULK 정본).
      - input_tokens / output_tokens: usage 기본 토큰.
      - cache_read_input_tokens:     prompt caching 재사용 토큰(~0.1x 비용).
      - cache_creation_input_tokens: prompt caching 신규 작성 토큰(~1.25x 비용).
    """
    ACTION_CHOICES = (
        ('ocr_parse', '증권 OCR 파싱'),
        ('compare_guide', '비교 분석 안내서'),
        ('message_gen', '고객 메시지 생성'),
    )

    action = models.CharField('호출 목적', max_length=30)
    model = models.CharField('Claude 모델', max_length=60)
    input_tokens = models.PositiveIntegerField('입력 토큰', default=0)
    output_tokens = models.PositiveIntegerField('출력 토큰', default=0)
    cache_read_input_tokens = models.PositiveIntegerField(
        '캐시 읽기 토큰', default=0, help_text='prompt caching 재사용(~0.1x 비용).')
    cache_creation_input_tokens = models.PositiveIntegerField(
        '캐시 작성 토큰', default=0, help_text='prompt caching 신규 작성(~1.25x 비용).')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'billing_claude_api_log'
        verbose_name = 'Claude API 로그'
        verbose_name_plural = 'Claude API 로그'
        indexes = [
            models.Index(fields=['action', 'created_at']),
            models.Index(fields=['model', 'created_at']),
        ]

    def __str__(self):
        return (f'{self.action} / {self.model} / '
                f'in={self.input_tokens} out={self.output_tokens} '
                f'cache_r={self.cache_read_input_tokens} @ {self.created_at:%Y-%m-%d}')


class Coupon(models.Model):
    """관리자 발급 무료 쿠폰 — 코드 입력 시 지정 요금제(보통 Plus)를 duration_days만큼 부여.

    관리자가 Django Admin에서 발급(코드·기간·최대 사용 수 지정). 설계사가 설정 화면에서 코드를
    입력해 사용한다. 유료 결제 전, 인터뷰·LOI 대상 등에 '선별 배포'하는 통제형 방식(§98 부당혜택 회피).
    코드 유효기한(expires_at)·최대 사용 수(max_redemptions)로 남용을 제한한다.
    """
    code = models.CharField('쿠폰 코드', max_length=32, unique=True, blank=True,
                            help_text='대문자·숫자. 비워두면 자동 생성(INPA-XXXXXXXX).')
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, verbose_name='부여 요금제',
                             help_text='보통 Plus.')
    duration_days = models.PositiveIntegerField('부여 기간(일)', default=30,
                                                help_text='기본 30일(1개월).')
    max_redemptions = models.PositiveIntegerField('최대 사용 횟수', default=1,
                                                  help_text='이 코드를 총 몇 명이 쓸 수 있는지. 기본 1(1회용).')
    redeemed_count = models.PositiveIntegerField('사용된 횟수', default=0)
    expires_at = models.DateTimeField('코드 유효기한', null=True, blank=True,
                                      help_text='이 시각 이후 사용 불가. null=무기한.')
    is_active = models.BooleanField('활성', default=True)
    note = models.CharField('메모(관리자)', max_length=200, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'billing_coupon'
        verbose_name = '쿠폰'
        verbose_name_plural = '쿠폰'

    def __str__(self):
        return f'{self.code} ({self.plan.code}, {self.duration_days}일)'

    def save(self, *args, **kwargs):
        if self.code:
            self.code = self.code.strip().upper()
        else:
            self.code = self._generate_code()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_code():
        # 헷갈리는 글자(O/0, I/1) 제외한 대문자·숫자.
        alphabet = (string.ascii_uppercase + string.digits).translate(
            str.maketrans('', '', 'O0I1'))
        while True:
            code = 'INPA-' + ''.join(secrets.choice(alphabet) for _ in range(8))
            if not Coupon.objects.filter(code=code).exists():
                return code

    def redeemable_reason(self, now=None):
        """사용 가능하면 None, 불가하면 사유코드(inactive/expired/exhausted) 반환."""
        now = now or timezone.now()
        if not self.is_active:
            return 'inactive'
        if self.expires_at is not None and self.expires_at <= now:
            return 'expired'
        if self.redeemed_count >= self.max_redemptions:
            return 'exhausted'
        return None


class CouponRedemption(models.Model):
    """쿠폰 사용 기록 — (쿠폰, 사용자) 유일. 이중 사용 방지 + 감사 로그."""
    coupon = models.ForeignKey(Coupon, on_delete=models.CASCADE,
                               related_name='redemptions', verbose_name='쿠폰')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name='coupon_redemptions', verbose_name='설계사')
    granted_until = models.DateTimeField('부여 만료 시각')
    redeemed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'billing_coupon_redemption'
        unique_together = ('coupon', 'user')
        verbose_name = '쿠폰 사용'
        verbose_name_plural = '쿠폰 사용'

    def __str__(self):
        return f'{self.user.email} / {self.coupon.code} / ~{self.granted_until:%Y-%m-%d}'
