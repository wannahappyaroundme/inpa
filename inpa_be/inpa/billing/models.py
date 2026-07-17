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
        ('manager', 'Manager'),
        ('super', 'Super'),
    )

    code = models.CharField(max_length=20, unique=True, choices=PLAN_CODE)
    display_name = models.CharField('표시 이름', max_length=50)
    price_krw = models.PositiveIntegerField('월 요금(원)', default=0)
    price_annual_krw = models.PositiveIntegerField(
        '연 요금(원)', null=True, blank=True,
        help_text='연 요금(부가세 별도). 미설정 시 월가×10 폴백(연구독=12개월을 10개월가로).'
    )
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
    # ★ 신규 고객 추가 한도(spec 2026-07-09 pricing-limits-align) — 랜딩 요금표 4한도 정합.
    #   설계사가 능동으로 추가하는 고객(단건·일괄 등록)만 집계한다. 셀프진단(/d)·소개카드(/p) 같은
    #   인바운드 자동 리드는 Customer.objects.create()를 직접 호출해 이 한도를 거치지 않는다
    #   (고객이 셀프진단했다고 설계사 한도가 깎이면 불합리하므로 의도적 설계).
    limit_customer = models.PositiveIntegerField(
        '신규 고객 추가 한도(월)', null=True, blank=True, default=5,
        help_text='null=무제한. Free 기본 5명(월). 설계사가 능동으로 추가하는 고객만 집계'
                   '(셀프진단·소개 카드 인바운드 리드는 미집계).'
    )
    # share_link / customer_add(레거시 명칭, 이 필드와 무관) = 절대 차단 금지 → 필드 없음 (dev/23 §1.2)

    # ★ capability 필드(월 액션 한도와 별개) — 활성·미만료 구독의 플랜이 True일 때 팀 기능 허용.
    # seed_billing 신규 기본값은 Plus·legacy Manager·Super=True, Free=False다.
    can_use_team = models.BooleanField(
        '팀 관리 기능 사용 가능', default=False,
        help_text='True면 /manager 대시보드·팀 초대 링크를 사용할 수 있어요. '
                   'settings.MANAGER_PLAN_GATE_ENABLED=True일 때만 실제로 게이트가 적용됩니다(기본 False=미적용).'
    )

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
    BILLING_CYCLE = (
        ('monthly', '월간'),
        ('annual', '연간'),
    )
    billing_cycle = models.CharField(
        '결제 주기', max_length=10, choices=BILLING_CYCLE, default='monthly',
        help_text='monthly=월간 / annual=연간(12개월을 10개월가로).'
    )
    first_paid_bonus_used = models.BooleanField(
        '첫 유료 보너스 소진', default=False,
        help_text='첫 유료 구독 1회에 한해 +1개월 이벤트 보너스가 적용됐는지(사용자당 1회 보장).'
    )
    started_at = models.DateTimeField('시작 시각', auto_now_add=True)
    expires_at = models.DateTimeField('만료 시각', null=True, blank=True,
                                      help_text='null = 무기한(Free).')
    cancelled_at = models.DateTimeField('해지 시각', null=True, blank=True)
    # PG 연동 hook (MVP 미사용)
    pg_subscription_id = models.CharField(
        'PG 구독 ID', max_length=100, blank=True, default='',
        help_text='Phase 2 PG 자동 결제 연동 시 채움.'
    )
    # ── Phase B(자동결제) 토대 — 지금은 필드만, 청구 로직은 후속(spec 2026-07-15) ──
    auto_renew = models.BooleanField(
        '자동 갱신', default=False,
        help_text='Phase B 정기결제 토대. True면 next_billing_at 도래 시 빌링키로 자동 청구(로직 후속).'
    )
    next_billing_at = models.DateTimeField(
        '다음 결제 예정 시각', null=True, blank=True,
        help_text='Phase B 정기결제 토대. auto_renew 청구 잡의 기준 시각(로직 후속).'
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
        ('customer', '고객 추가'),
    )

    # action label 한글 매핑 (GET /billing/usage/ 응답용)
    ACTION_LABELS = {
        'ocr': '증권 OCR 분析',
        'ai_compare': 'AI 비교안내서',
        'analysis': 'AI 분析·메시지',
        'promotion': '판촉물 주문',
        'customer': '고객 추가',
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
        """현재 연월 (YYYY-MM). lazy reset 비교 기준.

        ★ KST 기준(dashboard.MonthlyGoal.current_month 와 동형, §7). UsageMeter 집계·
          '이번 달' 창은 TIME_ZONE(Asia/Seoul) 버킷과 맞춰야 UTC/KST 월 경계일에
          카운트가 어긋나지 않는다. timezone.now()=UTC 를 쓰면 안 된다.
        """
        return timezone.localtime().strftime('%Y-%m')


class ClaudeApiLog(models.Model):
    """Claude API 호출당 토큰·비용·파싱결과 로깅 (관리자 전용 — dev/02 §14.2, 프리런치 #17).

    ★ 운영 로그(설계사 본인 조회 불가, 관리자 전체 조회). 월 예산 캡 집계·모델별 비용 추적·
    prompt caching 효율(cache_read 비율)·파싱 성공률·회사별 미매칭율 모니터링용.

    ★ PII-safe 필드만 — 증권 원문·Claude 응답 본문·상품/고객명은 절대 저장하지 않는다
    (claude_parser.py:29 레드라인과 동일 원칙). user 는 FK(id)만, 이름 아님.

    필드:
      - action: 호출 목적 (ocr_parse|ocr_verify|compare_guide|self_diagnosis 등). 자유 문자열.
      - model:  실제 호출된 Claude 모델 ID (settings CLAUDE_MODEL_PARSE/BULK 정본).
      - input_tokens / output_tokens: usage 기본 토큰.
      - cache_read_input_tokens:     prompt caching 재사용 토큰(~0.1x 비용).
      - cache_creation_input_tokens: prompt caching 신규 작성 토큰(~1.25x 비용).
      - user: 호출을 발생시킨 설계사(SET_NULL, null 허용 — /d 공개 경로는 귀속 없음).
      - cost_krw: ★ 추정 비용(원) — 토큰×단가(billing/pricing.py)×환율. 원천 진실은 토큰수,
        cost 는 파생 추정치(§6 정직성 — 정밀 청구서 아님).
      - parse_outcome: 이 호출의 결과 신호(성공/빈 결과/JSON 오류/API 오류/타임아웃/키 없음/
        패키지 없음). 실패도 1건으로 기록해 '실패율'을 관측 가능하게 한다.
      - carrier_code: 보험사 코드(int, UnmatchedLog 규약과 동일 — 손해=raw index/생명=200+idx).
      - matched_count / unmatched_count: 이 호출에서 표준 담보에 매칭/미매칭된 담보 수(정수만,
        담보명 원문은 저장하지 않는다).
    """
    ACTION_CHOICES = (
        ('ocr_parse', '증권 OCR 파싱'),
        ('insurance_extraction', '증권 검토형 추출'),
        ('ocr_verify', '증권 파싱 다중검사'),
        ('compare_guide', '비교 분석 안내서'),
        ('self_diagnosis', '셀프진단(공개)'),
        ('message_gen', '고객 메시지 생성'),
    )

    OUTCOME_SUCCESS = 'success'
    OUTCOME_EMPTY = 'empty'
    OUTCOME_JSON_INVALID = 'json_invalid'
    OUTCOME_API_ERROR = 'api_error'
    OUTCOME_TIMEOUT = 'timeout'
    OUTCOME_NO_KEY = 'no_key'
    OUTCOME_PACKAGE_MISSING = 'package_missing'
    # Review extraction uses these more precise PII-free ledger details.
    # They deliberately stay outside OUTCOME_CHOICES: changing model choices
    # would create a schema migration even though the DB column is free text.
    EXTRACTION_OUTCOME_SCHEMA_INVALID = 'schema_invalid'
    EXTRACTION_OUTCOME_PRIVACY_REJECTED = 'privacy_rejected'
    EXTRACTION_OUTCOME_TRANSPORT_FAILURE = 'transport_failure'
    EXTRACTION_OUTCOME_CONFIG_FAILURE = 'config_failure'
    EXTRACTION_OUTCOMES = (
        OUTCOME_SUCCESS,
        OUTCOME_EMPTY,
        EXTRACTION_OUTCOME_SCHEMA_INVALID,
        EXTRACTION_OUTCOME_PRIVACY_REJECTED,
        EXTRACTION_OUTCOME_TRANSPORT_FAILURE,
        EXTRACTION_OUTCOME_CONFIG_FAILURE,
    )
    OUTCOME_CHOICES = (
        (OUTCOME_SUCCESS, '성공'),
        (OUTCOME_EMPTY, '결과 없음'),
        (OUTCOME_JSON_INVALID, 'JSON 형식 오류'),
        (OUTCOME_API_ERROR, 'API 오류'),
        (OUTCOME_TIMEOUT, '시간 초과'),
        (OUTCOME_NO_KEY, '키 미설정'),
        (OUTCOME_PACKAGE_MISSING, '패키지 없음'),
    )

    action = models.CharField('호출 목적', max_length=30)
    model = models.CharField('Claude 모델', max_length=60)
    input_tokens = models.PositiveIntegerField('입력 토큰', default=0)
    output_tokens = models.PositiveIntegerField('출력 토큰', default=0)
    cache_read_input_tokens = models.PositiveIntegerField(
        '캐시 읽기 토큰', default=0, help_text='prompt caching 재사용(~0.1x 비용).')
    cache_creation_input_tokens = models.PositiveIntegerField(
        '캐시 작성 토큰', default=0, help_text='prompt caching 신규 작성(~1.25x 비용).')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='claude_api_logs', verbose_name='호출 설계사',
        help_text='공개 경로(/d 셀프진단)는 null.')
    cost_krw = models.DecimalField(
        '추정 비용(원)', max_digits=10, decimal_places=2, default=0,
        help_text='★ 추정치 — 토큰×단가×환율 파생값. 정밀 청구서 아님(§6 정직성).')
    parse_outcome = models.CharField(
        '파싱 결과', max_length=20, choices=OUTCOME_CHOICES, default=OUTCOME_SUCCESS,
        db_index=True)
    carrier_code = models.SmallIntegerField(
        '보험사 코드', null=True, blank=True,
        help_text='손해=raw index / 생명=200+index (UnmatchedLog 규약과 동일). 미상=null.')
    matched_count = models.SmallIntegerField('매칭 담보 수', default=0)
    unmatched_count = models.SmallIntegerField('미매칭 담보 수', default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'billing_claude_api_log'
        verbose_name = 'Claude API 로그'
        verbose_name_plural = 'Claude API 로그'
        indexes = [
            models.Index(fields=['action', 'created_at']),
            models.Index(fields=['model', 'created_at']),
            models.Index(fields=['created_at']),
            models.Index(fields=['parse_outcome']),
        ]

    def __str__(self):
        return (f'{self.action} / {self.model} / {self.parse_outcome} / '
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


class RuntimeConfig(models.Model):
    """관리자 런타임 토글(재배포 없이 변경). 단일 행(pk=1)."""
    free_tier_unlimited = models.BooleanField(
        '무료 무제한(베타)', default=True,
        help_text='True=모든 한도 무시(베타 무차감). False=유료 한도 적용(402 발동).')
    first_paid_bonus_enabled = models.BooleanField(
        '첫 유료 결제 보너스 이벤트', default=False,
        help_text='True=첫 유료 구독 부여 시 +1개월 보너스(사용자당 1회). 기본 OFF.')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'billing_runtime_config'
        verbose_name = '런타임 설정'
        verbose_name_plural = '런타임 설정'

    def __str__(self):
        return (f'free_tier_unlimited={self.free_tier_unlimited} '
                f'first_paid_bonus_enabled={self.first_paid_bonus_enabled}')

    @classmethod
    def solo(cls):
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                'free_tier_unlimited': bool(getattr(settings, 'FREE_TIER_UNLIMITED', True)),
                'first_paid_bonus_enabled': bool(getattr(settings, 'FIRST_PAID_BONUS_ENABLED', False)),
            },
        )
        return obj


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
