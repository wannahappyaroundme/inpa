"""보험·계산 모델 — 소유자 전용 (dev/02 §7, ♻ foliio 8케이스 엔진 무변경).

포팅 원칙(★ 핵심 자산 보존):
  foliio `weapon/insurances/models.py:194~559`의 CustomerInsurance / CustomerInsuranceDetail /
  CustomerInsuranceRefundSchedule를 가져온다. **8케이스 보험료 엔진(calculate · set_renewal_month ·
  detail.calculate, numpy_financial.fv 포함)은 한 줄도 건드리지 않는다** — 재포팅 위험 회피.

가시성(dev/02 §0):
  CustomerInsurance / CustomerInsuranceDetail → 소유자 전용 (★ customer__owner 경유).
  foliio는 CustomerInsurance.user 직속 owner FK였으나, 인파는 owner 스코프를 customer FK로 일원화한다
  (OwnedQuerySetMixin.owner_field = 'customer__owner'). → user FK 제거, customer 필수.

  Insurance 상품 카탈로그 계층(InsuranceTag/Category/SubCategory/Detail/Insurance)은 **필요한 최소만**
  유지 — CustomerInsuranceDetail.detail FK · CustomerInsurance.insurance/tags FK 무결성용. 전역 공유.

변경점(✦ 인파 적응):
  - CustomerInsurance.user(직속 owner FK) 제거 → customer__owner 경유로 일원화.
  - CustomerInsurance.customer: SET_NULL/nullable → CASCADE/required (owner 도출 경로 보장).
  - Insurance.image: foliio ProcessedImageField(imagekit) → 표준 ImageField (imagekit 의존성 회피).
  - portfolio_type 주석: 1=보유(기존가입)/2=제안 → 갈아타기 비교 좌/우 분기.
"""
import datetime
import uuid

import numpy_financial as npf
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Exists, OuterRef, Q

from inpa.analysis.models import AnalysisDetail, ChartDetail
from inpa.customers.models import Customer

from .date_utils import parse_insurance_date


# ── 보험 종류 choices (카탈로그 공통) ──────────────────────────────
class InsuranceTag(models.Model):
    """보험 태그 (♻ foliio insurances/models.py:95 무변경). 전역 공유."""
    name = models.CharField(max_length=45, primary_key=True)

    class Meta:
        db_table = 'insurance_tag'
        verbose_name = '보험 태그'
        verbose_name_plural = '보험 태그'

    def __str__(self):
        return self.name


class InsuranceCategory(models.Model):
    """보험 상품 카탈로그 대분류 (♻ foliio insurances/models.py:106 무변경). 전역 공유."""
    INSURANCE_TYPE = (
        (0, '공통'),
        (1, '생명보험'),
        (2, '손해보험'),
    )
    INSURANCE_TYPE_DICT = {v: k for k, v in INSURANCE_TYPE}

    insurance_type = models.SmallIntegerField(choices=INSURANCE_TYPE, default=0)
    name = models.CharField(max_length=20)
    order = models.SmallIntegerField('순서', default=0, blank=True)

    def __str__(self):
        return f'{self.order}, {self.name}'

    class Meta:
        db_table = 'insurance_category'
        verbose_name = '보험 카테고리'
        verbose_name_plural = '보험 카테고리'


class InsuranceSubCategory(models.Model):
    """보험 상품 카탈로그 중분류 (♻ foliio insurances/models.py:126 무변경). 전역 공유."""
    INSURANCE_TYPE = (
        (0, '공통'),
        (1, '생명보험'),
        (2, '손해보험'),
    )
    INSURANCE_TYPE_DICT = {v: k for k, v in INSURANCE_TYPE}

    insurance_type = models.SmallIntegerField(choices=INSURANCE_TYPE, default=0)
    category = models.ForeignKey(InsuranceCategory, on_delete=models.CASCADE, related_name='sub_categories')
    name = models.CharField(max_length=20)
    order = models.SmallIntegerField('순서', default=0, blank=True)

    def __str__(self):
        return f'{self.category.name} / {self.insurance_type} / {self.name}'

    class Meta:
        db_table = 'insurance_sub_category'
        verbose_name = '보험 서브 카테고리'
        verbose_name_plural = '보험 서브 카테고리'


class InsuranceDetail(models.Model):
    """보험 상품 카탈로그 세부담보 (♻ foliio insurances/models.py:147 무변경). 전역 공유.

    analysis_detail/chart_detail M2M는 inpa.analysis(표준 담보 트리)로 연결 — 카탈로그 담보를
    표준 분석 담보·차트 단위에 매핑한다.
    """
    CHART_TYPE = (
        (1, 'Cart1'),
        (2, 'Cart2'),
    )
    CHART_TYPE_DICT = {v: k for k, v in CHART_TYPE}

    chart_type = models.SmallIntegerField(choices=CHART_TYPE, default=1)

    sub_category = models.ForeignKey(InsuranceSubCategory, on_delete=models.CASCADE, related_name='details')
    name = models.CharField(max_length=20)
    order = models.SmallIntegerField('순서', default=0, blank=True)
    chart_based_amount = models.SmallIntegerField('차트 기준 금액', default=0, blank=True)
    analysis_detail = models.ManyToManyField(AnalysisDetail, blank=True)
    chart_detail = models.ManyToManyField(ChartDetail, blank=True)

    def __str__(self):
        return f'{self.sub_category.category.name} / {self.sub_category.name} / {self.order}, {self.name}'

    class Meta:
        db_table = 'insurance_detail'
        verbose_name = '보험 상세 아이템'
        verbose_name_plural = '보험 상세 아이템'


class Insurance(models.Model):
    """보험 상품 (♻ foliio insurances/models.py:171). 전역 공유.

    ✦ 변경: foliio ProcessedImageField(imagekit) → 표준 ImageField (의존성 회피, 최소 카탈로그).
    """
    INSURANCE_TYPE = (
        (1, '생명보험'),
        (2, '손해보험'),
    )
    INSURANCE_TYPE_DICT = {v: k for k, v in INSURANCE_TYPE}

    name = models.CharField('보험명', max_length=20)
    order = models.SmallIntegerField('순서', default=0, blank=True)
    image = models.ImageField(upload_to='uploads/insurance/%Y/%m/%d/', blank=True, null=True, default=None)
    insurance_type = models.SmallIntegerField(choices=INSURANCE_TYPE, default=1)

    def __str__(self):
        return f'{self.order}, {self.name}'

    class Meta:
        db_table = 'insurance'
        verbose_name = '보험'
        verbose_name_plural = '보험'


class CustomerInsuranceQuerySet(models.QuerySet):
    """분석·공유·비교에 포함할 수 있는 보험의 단일 서버 권위."""

    def analysis_ready(self):
        queryset = self.filter(is_cancelled=False)
        if settings.INSURANCE_REVIEW_GATE_ENABLED:
            queryset = queryset.filter(
                review_status='confirmed', analysis_included=True)
        else:
            # Gate-off preserves already registered legacy policies while
            # drafts, explicit exclusions, and inconsistent confirmations
            # never leak into analysis or customer shares.
            queryset = queryset.filter(
                Q(review_status='legacy_review_required')
                | Q(review_status='confirmed', analysis_included=True)
            )
        unknown_assurance = CustomerInsuranceDetail.objects.filter(
            insurance_id=OuterRef('pk'), assurance_amount__isnull=True)
        return queryset.annotate(
            _has_unknown_assurance=Exists(unknown_assurance),
        ).filter(_has_unknown_assurance=False)

    def analysis_review_state(self):
        """보유 보험의 분석 포함·확인 대기·공유 가능 상태를 한 번에 계산한다."""
        portfolio = self.filter(portfolio_type=1)
        ready = portfolio.analysis_ready()
        pending = portfolio.filter(
            is_cancelled=False,
            review_status__in=('draft', 'legacy_review_required'),
        )
        included_count = ready.count()
        pending_count = pending.count()
        can_share = included_count > 0
        if settings.INSURANCE_REVIEW_GATE_ENABLED and pending_count > 0:
            can_share = False
            block_reason = '확인할 보험 내용을 마치면 바로 공유할 수 있어요.'
        elif not can_share:
            block_reason = '보험 내용을 확인하고 분석에 포함해 주세요.'
        else:
            block_reason = None
        return {
            'portfolio_queryset': portfolio,
            'ready_queryset': ready,
            'included_insurance_count': included_count,
            'total_insurance_count': portfolio.count(),
            'pending_review_count': pending_count,
            'can_share': can_share,
            'share_block_reason': block_reason,
        }


class CustomerInsurance(models.Model):
    """고객 보유/제안 포트폴리오 — 소유자 전용 (★ customer__owner 경유, dev/02 §7).

    foliio CustomerInsurance(insurances/models.py:194) ♻ — 8케이스 보험료 엔진 무변경.
    ✦ 인파 적응: user 직속 owner FK 제거 / customer CASCADE·required (owner 도출 경로).
    """
    PORTFOLIO_TYPE = (
        (0, '템플릿'),
        (1, '보유'),    # 기존가입 — 갈아타기 비교 좌측
        (2, '제안'),    # 제안 — 갈아타기 비교 우측
    )
    PORTFOLIO_TYPE_DICT = {v: k for k, v in PORTFOLIO_TYPE}

    INSURANCE_TYPE = (
        (1, '생명보험'),
        (2, '손해보험'),
    )
    INSURANCE_TYPE_DICT = {v: k for k, v in INSURANCE_TYPE}
    PAYMENT_PERIOD_TYPE = (
        (1, '년'),
        (2, '년 갱신'),
    )
    PAYMENT_PERIOD_TYPE_DICT = {v: k for k, v in PAYMENT_PERIOD_TYPE}
    WARRANTY_PERIOD_TYPE = (
        (1, '세 만기'),
        (2, '년 만기'),
        (3, '종신'),
    )
    WARRANTY_PERIOD_TYPE_DICT = {v: k for k, v in WARRANTY_PERIOD_TYPE}

    REFUND_TYPE = (
        (1, '종신보험'),
        (2, '만기환급'),
        (3, '50%환급'),
        (4, '순수보장형'),
    )
    REFUND_TYPE_DICT = {v: k for k, v in REFUND_TYPE}

    is_common = models.BooleanField('공통 유무', default=False)  # 어드민용

    # ✦ 담보 사전 피드백(2026-07-09): OCR이 감지한 보험사 코드(ocrdata index, -1=미감지).
    #   NormalizationDict.company 와 같은 코드 공간. 수기 입력/레거시 행은 null.
    company = models.SmallIntegerField('보험사 코드', default=None, null=True, blank=True)

    insurance = models.ForeignKey(Insurance, on_delete=models.SET_NULL, default=None, null=True, blank=True)
    # ✦ owner 스코프 = customer__owner 경유 (foliio user 직속 FK 제거). customer 필수·CASCADE.
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE,
                                 related_name='customer_insurance_list')
    insurance_type = models.SmallIntegerField(choices=INSURANCE_TYPE, default=1)

    name = models.CharField('상품명', max_length=100, default=None, null=True, blank=True)
    contractor_name = models.CharField('계약자 이름', max_length=10, default=None, null=True, blank=True)
    insured_name = models.CharField('피보험자 이름', max_length=10, default=None, null=True, blank=True)
    is_same_insured = models.BooleanField('계/피 동일', default=None, null=True, blank=True)
    portfolio_type = models.SmallIntegerField('포트폴리오 타입', choices=PORTFOLIO_TYPE, default=0)
    payment_period_type = models.SmallIntegerField('납입기간 타입', choices=PAYMENT_PERIOD_TYPE, default=1)
    warranty_period_type = models.SmallIntegerField('보장기간 타입', choices=WARRANTY_PERIOD_TYPE, default=1)
    payment_period = models.IntegerField('납입기간', default=None, null=True, blank=True)
    warranty_period = models.IntegerField('보장기간', default=None, null=True, blank=True)
    contract_date = models.CharField('계약일', max_length=10, default=None, null=True, blank=True)
    expiry_date = models.CharField('만기일', max_length=10, default=None, null=True, blank=True)
    old = models.IntegerField('나이', default=None, null=True, blank=True)  # 자주쓰는

    renewal_month = models.IntegerField('총 갱신 납입 회차', default=None, null=True, blank=True)
    non_renewal_month = models.IntegerField('총 비갱신 납입 회차', default=None, null=True, blank=True)
    monthly_assurance_premium = models.IntegerField('월 보장 보험료', default=None, null=True, blank=True)
    monthly_special_premium = models.IntegerField('월 특약 보험료', default=None, null=True, blank=True)
    monthly_premiums = models.IntegerField('월 납입 보험료', default=None, null=True, blank=True)
    monthly_contract_premium = models.IntegerField('월 주계약 보험료', default=None, null=True, blank=True)
    monthly_earned_premium = models.IntegerField('월 적립 보험료', default=None, null=True, blank=True)

    monthly_non_renewal_premium = models.IntegerField('월 비갱신 보험료', default=None, null=True, blank=True)
    monthly_renewal_premium = models.IntegerField('월 갱신 보험료', default=None, null=True, blank=True)

    # 계산되는 부분
    total_premiums = models.FloatField('총 납입 보험료', default=None, null=True, blank=True)
    total_renewal_premium = models.FloatField('총 갱신 보험료', default=None, null=True, blank=True)
    total_non_renewal_premium = models.FloatField('총 비갱신 보험료', default=None, null=True, blank=True)
    total_earned_premium = models.FloatField('총 적립 보험료', default=None, null=True, blank=True)
    expected_due_year = models.IntegerField('예상 만기 년수', default=None, null=True, blank=True)  # 년만기 보장 기간, 세 만기 나이 - 보장 기간

    cancellation_refund = models.IntegerField('혜약 환급금', default=None, null=True, blank=True)
    refund_type = models.SmallIntegerField('환급타입', choices=REFUND_TYPE, default=1)
    percent_cancellation_refund = models.IntegerField('혜약 환급금 퍼센트', default=None, null=True, blank=True)

    # ── 환수 레이더(A/S) — 수기입력 MVP. OCR 추출 불가 항목이라 설계사가 직접 입력. ──
    # 정확한 환수액은 회사 전산 권위 → 화면·계산 모두 '추정' 라벨 강제. owner 전용.
    PAYMENT_STATUS = ((1, '정상'), (2, '연체'), (3, '납입중단'))
    current_payment_period = models.IntegerField('현재 납입회차', default=None, null=True, blank=True)
    payment_status = models.SmallIntegerField('납입상태', choices=PAYMENT_STATUS, default=None, null=True, blank=True)
    next_payment_date = models.DateField('다음 납입일', default=None, null=True, blank=True)
    expected_recovery_amount = models.IntegerField('예상 환수액(추정)', default=None, null=True, blank=True)

    # ── 계약 유지율(1/2/3년) 추적 — 해지 여부/해지일(수기). retention 집계용(추정 라벨). ──
    is_cancelled = models.BooleanField('해지 여부', default=False)
    cancelled_at = models.CharField('해지일', max_length=10, default=None, null=True, blank=True)  # YYYY-MM-DD

    # ── 파싱 정확도 다중검사 결과(Claude 교차검증) — verify.py 산출. null=미검증. ──
    # {checked, confidence(high|medium|low), issues[], missing[], note} — 설계사 확인용 플래그.
    verification = models.JSONField('파싱 검증 결과', default=None, null=True, blank=True)

    renewal_growth_rate = models.FloatField('갱신 증가율', default=None, null=True, blank=True)
    renewal_special_expiry_date = models.CharField('갱신특약 만기일 날짜', max_length=10, default=None, null=True, blank=True)
    renewal_special_expiry = models.IntegerField('갱신특약 만기일', default=None, null=True, blank=True)
    user_view_at = models.DateTimeField(default=None, null=True, blank=True)
    comment_title = models.CharField(max_length=100, default=None, null=True, blank=True)
    comment = models.TextField(default=None, null=True, blank=True)
    is_template = models.BooleanField(default=False)

    tags = models.ManyToManyField(InsuranceTag, blank=True)

    custom_coverages = models.JSONField('수동 담보', default=list, blank=True)

    share_token = models.UUIDField('공유 토큰', default=None, null=True, blank=True, unique=True)
    share_expires_at = models.DateTimeField('공유 만료일', default=None, null=True, blank=True)

    # 검토형 증권 등록 권위. 기존/직접 입력 행도 설계사가 확인하기 전에는 분석에 포함하지 않는다.
    REVIEW_STATUS_CHOICES = (
        ('draft', '직접 입력 확인 전'),
        ('legacy_review_required', '기존 자료 확인 필요'),
        ('confirmed', '확인 완료'),
        ('excluded', '분석 제외'),
        ('superseded', '교체됨'),
    )
    review_status = models.CharField(
        max_length=32, choices=REVIEW_STATUS_CHOICES,
        default='legacy_review_required')
    source_job = models.OneToOneField(
        'InsuranceExtractionJob', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='confirmed_insurance')
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='confirmed_insurances')
    analysis_included = models.BooleanField(default=False)
    confirmation_source = models.CharField(max_length=24, default='', blank=True)
    review_exclusion_reason = models.CharField(
        max_length=500, default='', blank=True)
    data_version = models.PositiveIntegerField(default=1)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = CustomerInsuranceQuerySet.as_manager()

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'customer_insurance'
        verbose_name = '포트폴리오'
        verbose_name_plural = '포트폴리오'

    def set_renewal_month(self):
        self.non_renewal_month = (self.payment_period or 0) * 12
        contract_date = parse_insurance_date(self.contract_date)
        expiry_date = parse_insurance_date(self.expiry_date)
        self.renewal_month = None

        if (contract_date is not None
                and expiry_date is not None
                and contract_date <= expiry_date):
            period = relativedelta(expiry_date, contract_date)
            self.renewal_month = period.years * 12 + period.months

        self.save()

    COVERAGE_PREMIUM_COMPOSITION_FIELDS = frozenset({
        'monthly_renewal_premium',
        'monthly_non_renewal_premium',
        'total_premiums',
        'total_renewal_premium',
        'total_non_renewal_premium',
    })

    def has_mixed_case_premiums(self):
        """담보 보험료가 알려진 행과 미상 행이 함께 있는지 반환한다."""
        has_known = False
        has_unknown = False
        for case in self.case_list.all():
            if case.premium is None:
                has_unknown = True
            else:
                has_known = True
            if has_known and has_unknown:
                return True
        return False

    def calculate(self):
        monthly_renewal_premium = 0  # 월 비갱신 보험료
        monthly_non_renewal_premium = 0  # 월 비갱신 보험료
        total_premiums = 0  # 총 납입 보험료
        total_renewal_premium = 0  # 총 갱신 보험료
        total_non_renewal_premium = 0  # 총 비갱신 보험료
        total_earned_premium = 0  # 총 적립 보험료
        monthly_earned_premium = 0  # 월 적립 보험료
        if self.monthly_earned_premium:
            monthly_earned_premium = self.monthly_earned_premium
        # 총 적립금 = 월 적립금 * 납입기간 * 12 (납입 타입이 년 인경우, 년 갱신 0)
        if self.payment_period_type == 1:
            total_earned_premium = monthly_earned_premium * (self.non_renewal_month or 0)

        # 총 보험료 계산
        # 담보 보험료 x - 손해 보험 - 년
        # 담보 보험료 x - 손해 보험 - 년 갱신
        # 담보 보험료 x - 생명 보험 - 년
        # 담보 보험료 x - 생명 보험 - 년 갱신

        # 담보 보험료 o - 담보별 년
        # 담보 보험료 o - 담보별 세
        # 담보 보험료 o - 담보별 년 갱신

        # ================= 보험료 케이스 별 계산 ====================================================

        case_list = list(self.case_list.all())
        has_known_case_premium = any(
            case.premium is not None for case in case_list)
        has_unknown_case_premium = any(
            case.premium is None for case in case_list)
        has_mixed_case_premiums = (
            has_known_case_premium and has_unknown_case_premium)
        unknown_renewal_total = False
        unknown_non_renewal_total = False

        # 2026-05-11 fix: case 가 갱신/비갱신 둘 다 보유 (total_renewal_premium > 0 AND
        # total_non_renewal_premium > 0) 시 case.premium 이 양쪽 버킷에 더해져 이중카운트
        # 되던 버그. case.premium 은 단일 월보험료이므로 payment_period_type 으로 한 버킷에만
        # 귀속시킨다 (1/2 = 비갱신, 3 = 갱신). total_X_premium (보장금액 누적) 은 그대로 합산.
        for case in case_list:
            total_renewal_premium = total_renewal_premium + (case.total_renewal_premium or 0)
            total_non_renewal_premium = total_non_renewal_premium + (case.total_non_renewal_premium or 0)
            if case.payment_period_type == 4 and (case.premium or 0) > 0:
                if case.is_renewal_case:
                    unknown_renewal_total = True
                else:
                    unknown_non_renewal_total = True
            if case.is_renewal_case:
                monthly_renewal_premium = monthly_renewal_premium + (case.premium or 0)
            else:
                monthly_non_renewal_premium = monthly_non_renewal_premium + (case.premium or 0)

        if monthly_renewal_premium == 0 and self.monthly_renewal_premium:
            monthly_renewal_premium = self.monthly_renewal_premium

        if (total_renewal_premium > 0 or total_non_renewal_premium > 0
                or unknown_renewal_total or unknown_non_renewal_total):  # 담보별 가격이 있음
            # @ 담보 보험료 o - 담보별 년
            # @ 담보 보험료 o - 담보별 세
            # @ 담보 보험료 o - 담보별 년 갱신
            if self.insurance_type == 1:  # 생명보험
                etc_premium = (self.monthly_premiums or 0) - monthly_non_renewal_premium - monthly_renewal_premium
                total_etc_premium = etc_premium * (self.non_renewal_month or 0)
                total_premiums = total_non_renewal_premium + total_renewal_premium + total_etc_premium
            else:  # 손해 보험
                etc_premium = (self.monthly_premiums or 0) - monthly_non_renewal_premium - monthly_renewal_premium - monthly_earned_premium
                total_etc_premium = etc_premium * (self.non_renewal_month or 0)
                total_premiums = total_non_renewal_premium + total_renewal_premium + total_earned_premium + total_etc_premium

        else:
            if self.insurance_type == 2:  # 손해보험
                # @ 담보 보험료 x - 손해 보험 - 년

                # Rate는 기간당 이자율입니다.  갱신 증가율 * 12
                # Nper는 연금의 총 지급 기간입니다.  갱신 개월수
                # Pmt는 각 기간마다 지급되는 지급액이며, 연금 연수에 따라 변경될 수 없습니다. Pmt는 음수로 입력해야 합니다.
                # Pv는 현재 가치 또는 일련의 미래 지급 가치가 있는 일시불 금액입니다. pv를 생략하면 0으로 가정합니다. PV는 음수로 입력해야 합니다.
                # numpy.fv(Rate, Nper, Pmt, Pv)
                if self.renewal_month and self.renewal_growth_rate is not None and self.monthly_renewal_premium:
                    total_renewal_premium = round(-npf.fv((self.renewal_growth_rate / 100) / 12, self.renewal_month,
                                                          self.monthly_renewal_premium, 0), 0)

                if self.payment_period_type == 1:  # 년
                    # 갱신 총 납입 횟수 = 만기일 - 계약일 개월수
                    pass
                    # 비갱신 총 납입 횟수 = 납입기간 * 12
                    non_renewal_month = self.payment_period * 12
                    # 월 비갱신 보험료 = 월 보장 보험료 - 월 갱신 보험료
                    # max(0): 갱신 > 보장(입력/OCR 오류) 시 음수 방지 — overage 경고가 별도 처리.
                    monthly_non_renewal_premium = max(0, (self.monthly_assurance_premium or 0) - monthly_renewal_premium)

                    # 총 비갱신 = 비갱신 납입 개월 * 월 비갱신 보험료
                    total_non_renewal_premium = non_renewal_month * monthly_non_renewal_premium
                    # 총 보험료 = 총 비갱신 + 총 갱신 + 총 적립
                    total_premiums = total_earned_premium + total_renewal_premium + total_non_renewal_premium

                # @ 담보 보험료 x - 손해 보험 - 년 갱신
                if self.payment_period_type == 2:  # 년 갱신
                    total_premiums = total_renewal_premium
                    # 월 비갱신 = 월 보장 보험료 - 월 갱신 보험료 (년 분기와 동일 규칙).
                    # 안 그러면 보장보험료의 비갱신분이 어느 버킷에도 안 들어가
                    # 분석 도넛에서 '미분류'로 표시됨 (월보험료 = 갱신+비갱신+적립 불변식 유지).
                    # max(0): 갱신 > 보장(입력/OCR 오류) 시 음수 방지 — 이 경우는 별도 overage 경고가 처리.
                    monthly_non_renewal_premium = max(0, (self.monthly_assurance_premium or 0) - monthly_renewal_premium)

            if self.insurance_type == 1:  # 생명보험
                # @ 담보 보험료 x - 생명 보험 - 년
                if self.payment_period_type == 1:  # 년
                    # 총 비용 = 월 보험료 * 납입기간 * 12
                    non_renewal_month = self.payment_period * 12
                    total_premiums = (self.monthly_premiums or 0) * non_renewal_month
                    monthly_non_renewal_premium = (self.monthly_premiums or 0) - (self.monthly_earned_premium or 0)
                    total_non_renewal_premium = non_renewal_month * monthly_non_renewal_premium
                    total_renewal_premium = 0
                    monthly_renewal_premium = 0

                # @ 담보 보험료 x - 생명 보험 - 년 갱신
                if self.payment_period_type == 2:  # 년 갱신
                    monthly_renewal_premium = self.monthly_premiums or 0
                    if self.renewal_growth_rate is not None and self.renewal_month:
                        total_renewal_premium = round(-npf.fv((self.renewal_growth_rate / 100) / 12, self.renewal_month,
                                                              monthly_renewal_premium, 0), 0)
                    else:
                        total_renewal_premium = monthly_renewal_premium * (self.renewal_month or 0)
                    total_premiums = total_renewal_premium
                    monthly_earned_premium = 0
                    monthly_non_renewal_premium = 0
                    total_earned_premium = 0
                    total_non_renewal_premium = 0

        if unknown_renewal_total:
            total_renewal_premium = None
        if unknown_non_renewal_total:
            total_non_renewal_premium = None
        if unknown_renewal_total or unknown_non_renewal_total:
            total_premiums = None

        if has_mixed_case_premiums:
            monthly_renewal_premium = None
            monthly_non_renewal_premium = None
            total_premiums = None
            total_renewal_premium = None
            total_non_renewal_premium = None

        self.total_premiums = total_premiums
        self.monthly_non_renewal_premium = monthly_non_renewal_premium
        self.monthly_renewal_premium = monthly_renewal_premium
        self.total_renewal_premium = total_renewal_premium
        self.total_non_renewal_premium = total_non_renewal_premium
        self.total_earned_premium = total_earned_premium
        self.monthly_earned_premium = monthly_earned_premium


class CustomerInsuranceDetail(models.Model):
    """고객 보험 담보별 케이스 (♻ foliio insurances/models.py:462 무변경).

    insurance.case_list 역참조로 CustomerInsurance.calculate()가 케이스별 미래가치를 합산.
    """
    insurance = models.ForeignKey(CustomerInsurance, on_delete=models.CASCADE, related_name="case_list")
    detail = models.ForeignKey(InsuranceDetail, on_delete=models.CASCADE)

    # ✦ 담보 사전 피드백(2026-07-09): 증권에서 읽은 담보 원문명. 오매핑 신고 → 정규화
    #   사전 별칭 등록의 원료. 직접 입력/레거시 행은 빈 값(FE는 detail.name 폴백).
    raw_name = models.CharField('담보 원문명', max_length=200, default='', blank=True)

    source_page = models.PositiveSmallIntegerField(null=True, blank=True)
    source_line_start = models.PositiveIntegerField(null=True, blank=True)
    source_line_end = models.PositiveIntegerField(null=True, blank=True)
    source_text_masked = models.TextField(default='', blank=True)
    source_candidate_ids = models.JSONField(default=list, blank=True)
    evidence_line_ids = models.JSONField(default=list, blank=True)
    review_reason = models.JSONField(default=list, blank=True)
    MAPPING_SOURCE_CHOICES = (
        ('global', '전역 사전'),
        ('planner_override', '설계사 수정'),
        ('manual', '직접 입력'),
    )
    mapping_source = models.CharField(
        max_length=24, choices=MAPPING_SOURCE_CHOICES, default='global')
    analysis_detail_override = models.ManyToManyField(
        AnalysisDetail, blank=True, related_name='insurance_case_overrides')
    confirmed_at = models.DateTimeField(null=True, blank=True)

    PAYMENT_PERIOD_TYPE = (
        (1, '년'),
        (2, '세'),
        (3, '년 갱신'),
        (4, '종신'),
    )
    PAYMENT_PERIOD_TYPE_DICT = {v: k for k, v in PAYMENT_PERIOD_TYPE}
    WARRANTY_PERIOD_TYPE = (
        (1, '세'),
        (2, '년'),
        (3, '날짜'),
        (4, '종신'),
    )
    WARRANTY_PERIOD_TYPE_DICT = {v: k for k, v in WARRANTY_PERIOD_TYPE}

    assurance_amount = models.IntegerField('보장 금액', default=None, null=True, blank=True)
    premium = models.IntegerField('보험료', default=None, null=True, blank=True)
    renewal_period = models.PositiveIntegerField(
        '갱신 주기', default=None, null=True, blank=True)
    payment_period_type = models.SmallIntegerField('납입기간 타입', choices=PAYMENT_PERIOD_TYPE, default=1)
    payment_period = models.IntegerField('납입기간', default=None, null=True, blank=True)
    warranty_period_type = models.SmallIntegerField('보증기간 타입', choices=WARRANTY_PERIOD_TYPE, default=1)
    warranty_period = models.CharField('보증기간', max_length=20, default=None, null=True, blank=True)  # 날짜도 가능해야 하기때문에

    total_renewal_premium = models.FloatField('총 갱신 보험료', default=None, null=True, blank=True)
    total_non_renewal_premium = models.FloatField('총 비갱신 보험료', default=None, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.detail.name

    class Meta:
        db_table = 'customer_insurance_detail'
        verbose_name = '고객 보험 상세'
        verbose_name_plural = '고객 보험 상세'

    def effective_analysis_details(self):
        if self.mapping_source in {'planner_override', 'manual'}:
            return self.analysis_detail_override.all()
        return self.detail.analysis_detail.all()

    @property
    def is_renewal_case(self):
        return (
            self.payment_period_type == 3
            or (self.payment_period_type == 4
                and self.renewal_period is not None)
        )

    def calculate(self, insurance):
        self.total_renewal_premium = 0
        self.total_non_renewal_premium = 0

        if self.premium:
            if self.payment_period_type == 4:
                self.total_renewal_premium = None
                self.total_non_renewal_premium = None
                return
            if self.payment_period_type == 1:
                # 납입기간 타입 이 '년' 인경우
                self.total_non_renewal_premium = self.payment_period * 12 * self.premium
            if self.payment_period_type == 2:
                # 나이 계산
                # 납입기간 타입 이 '세' 인경우
                # 납입기간 = 보장기간 - 나이
                # case.비갱신합계 = 납입기간 * 12 * 보험료

                if insurance.customer:
                    birth_day = parse_insurance_date(
                        insurance.customer.birth_day)
                    contract_date = parse_insurance_date(
                        insurance.contract_date)
                    if birth_day is None or contract_date is None:
                        self.total_non_renewal_premium = None
                        return
                    now = datetime.date.today()
                    old = relativedelta(now, birth_day).years + 1
                    contract_old = old - (now.year - contract_date.year)
                    old = contract_old
                else:
                    old = insurance.old

                if old is None or self.payment_period is None:
                    self.total_non_renewal_premium = None
                    return

                period = self.payment_period - old
                self.total_non_renewal_premium = period * 12 * self.premium

            if self.payment_period_type == 3:
                # 납입기간 타입 이 '년 갱신' 인경우
                # 보험 총 납입 개월 수
                if insurance.renewal_month is None:
                    self.total_renewal_premium = None
                    return
                if insurance.renewal_growth_rate is not None and insurance.renewal_month:
                    total_renewal_premium = round(-npf.fv((insurance.renewal_growth_rate / 100) / 12, insurance.renewal_month,
                                                          self.premium, 0), 0)
                else:
                    total_renewal_premium = self.premium * insurance.renewal_month
                self.total_renewal_premium = total_renewal_premium


class CustomerInsuranceRefundSchedule(models.Model):
    """년차별 해약환급금 스케줄 (♻ foliio insurances/models.py:540 무변경)."""
    insurance = models.ForeignKey(
        CustomerInsurance, on_delete=models.CASCADE,
        related_name='refund_schedule'
    )
    year = models.SmallIntegerField('경과년수')
    refund_amount = models.IntegerField('해약환급금', default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'customer_insurance_refund_schedule'
        verbose_name = '해약환급금 스케줄'
        verbose_name_plural = '해약환급금 스케줄'
        ordering = ['year']
        unique_together = ['insurance', 'year']

    def __str__(self):
        return f'{self.insurance.name} - {self.year}년차: {self.refund_amount}원'


class InsuranceExtractionJob(models.Model):
    """설계사·고객·파일 단위 증권 추출 작업의 상태 정본."""

    ACTIVE_STATUSES = ('queued', 'extracting', 'validating', 'review_required')
    STATUS_CHOICES = (
        ('queued', '대기'),
        ('extracting', '추출'),
        ('validating', '검사'),
        ('review_required', '검토 필요'),
        ('confirmed', '확인 완료'),
        ('failed', '실패'),
        ('canceled', '취소'),
        ('superseded', '교체됨'),
    )
    INTENT_CHOICES = (('add', '추가'), ('replace', '교체'))

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='insurance_extraction_jobs')
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE,
        related_name='insurance_extraction_jobs')
    target_insurance = models.ForeignKey(
        CustomerInsurance, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='replacement_jobs')
    intent = models.CharField(max_length=12, choices=INTENT_CHOICES)
    portfolio_type = models.SmallIntegerField()
    status = models.CharField(
        max_length=24, choices=STATUS_CHOICES, default='queued', db_index=True)
    file_sha256 = models.CharField(max_length=64)
    file_size = models.PositiveBigIntegerField()
    page_count = models.PositiveSmallIntegerField(null=True, blank=True)
    safe_display_name = models.CharField(max_length=120)
    source_storage_key = models.CharField(max_length=500, default='', blank=True)
    source_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    source_deleted_at = models.DateTimeField(null=True, blank=True)
    masked_lines = models.JSONField(default=list, blank=True)
    draft_payload = models.JSONField(default=dict, blank=True)
    validation_summary = models.JSONField(default=dict, blank=True)
    schema_version = models.CharField(max_length=40, default='', blank=True)
    prompt_version = models.CharField(max_length=40, default='', blank=True)
    normalization_version = models.CharField(max_length=40, default='', blank=True)
    attempt_uuid = models.UUIDField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    lease_expired_count = models.PositiveSmallIntegerField(default=0)
    planner_edit_count = models.PositiveIntegerField(default=0)
    confirmed_coverage_count = models.PositiveIntegerField(default=0)
    draft_version = models.PositiveIntegerField(default=1)
    target_insurance_version = models.PositiveIntegerField(null=True, blank=True)
    create_idempotency_key = models.UUIDField(null=True, blank=True)
    error_code = models.CharField(max_length=40, default='', blank=True)
    error_type = models.CharField(max_length=40, default='', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    canceled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'insurance_extraction_job'
        verbose_name = '증권 검토 작업'
        verbose_name_plural = '증권 검토 작업'
        constraints = [
            models.UniqueConstraint(
                fields=['owner', 'customer', 'file_sha256', 'portfolio_type'],
                condition=Q(status__in=(
                    'queued', 'extracting', 'validating', 'review_required')),
                name='uniq_active_ins_import_hash'),
            models.UniqueConstraint(
                fields=['owner', 'create_idempotency_key'],
                condition=Q(create_idempotency_key__isnull=False),
                name='uniq_ins_import_create_key'),
            models.UniqueConstraint(
                fields=['owner', 'customer', 'file_sha256', 'portfolio_type'],
                condition=Q(status='confirmed'),
                name='uniq_confirmed_ins_import_hash'),
        ]
        indexes = [
            models.Index(
                fields=['owner', 'customer', 'status'],
                name='ins_import_owner_cust_st'),
            models.Index(
                fields=['status', 'lease_expires_at'],
                name='ins_import_status_lease'),
        ]

    def __str__(self):
        return f'{self.id} / {self.status}'


class InsuranceExtractionResult(models.Model):
    """작업별 구조화 결과와 개인정보 없는 호출 메트릭."""

    PROVIDER_CHOICES = (('claude', 'Claude'), ('local_regex', '로컬 규칙'))

    job = models.ForeignKey(
        InsuranceExtractionJob, on_delete=models.CASCADE,
        related_name='results')
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES)
    model_id = models.CharField(max_length=100, default='', blank=True)
    outcome = models.CharField(max_length=40, default='', blank=True)
    structured_payload = models.JSONField(default=dict, blank=True)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    estimated_cost_krw = models.DecimalField(
        max_digits=12, decimal_places=4, default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'insurance_extraction_result'
        verbose_name = '증권 추출 결과'
        verbose_name_plural = '증권 추출 결과'
        constraints = [
            models.UniqueConstraint(
                fields=['job', 'provider'], name='uniq_ins_result_job_provider'),
        ]


class InsuranceImportCommand(models.Model):
    """검토 수정·확정 명령의 멱등 재생 기록."""

    OPERATION_CHOICES = (
        ('patch', '수정'), ('confirm', '확정'), ('cancel', '취소'))

    job = models.ForeignKey(
        InsuranceExtractionJob, on_delete=models.CASCADE,
        related_name='commands')
    operation = models.CharField(max_length=16, choices=OPERATION_CHOICES)
    idempotency_key = models.UUIDField()
    request_sha256 = models.CharField(max_length=64)
    response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    response_body = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'insurance_import_command'
        verbose_name = '증권 검토 멱등 명령'
        verbose_name_plural = '증권 검토 멱등 명령'
        constraints = [
            models.UniqueConstraint(
                fields=['job', 'operation', 'idempotency_key'],
                name='uniq_ins_command_key'),
        ]


class ManualInsuranceCommand(models.Model):
    """직접 입력·기존 보험 확인 명령의 멱등 재생 기록."""

    OPERATION_CHOICES = (('confirm', '확정'),)

    insurance = models.ForeignKey(
        CustomerInsurance, on_delete=models.CASCADE,
        related_name='manual_review_commands')
    operation = models.CharField(
        max_length=16, choices=OPERATION_CHOICES, default='confirm')
    idempotency_key = models.UUIDField()
    request_sha256 = models.CharField(max_length=64)
    response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    response_body = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'manual_insurance_command'
        verbose_name = '직접 입력 보험 멱등 명령'
        verbose_name_plural = '직접 입력 보험 멱등 명령'
        constraints = [
            models.UniqueConstraint(
                fields=['insurance', 'operation', 'idempotency_key'],
                name='uniq_manual_ins_command_key'),
        ]


class InsuranceImportCreateRequest(models.Model):
    """Owner-scoped immutable replay record for an import create request."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='insurance_import_create_requests')
    job = models.ForeignKey(
        InsuranceExtractionJob, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='create_requests')
    resolution_job = models.ForeignKey(
        InsuranceExtractionJob, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='duplicate_resolution_requests')
    idempotency_key = models.UUIDField()
    request_sha256 = models.CharField(max_length=64)
    response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    response_body = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'insurance_import_create_request'
        verbose_name = '증권 접수 멱등 요청'
        verbose_name_plural = '증권 접수 멱등 요청'
        constraints = [
            models.UniqueConstraint(
                fields=['owner', 'idempotency_key'],
                name='uniq_ins_import_create_request_key'),
        ]

    def __str__(self):
        return f'create-request/{self.pk}'


class InsuranceImportRuntimeConfig(models.Model):
    """증권 작업 동시 실행 상한. 단일 행(pk=1), 관리자 수정값 우선."""

    id = models.PositiveSmallIntegerField(
        primary_key=True, default=1, editable=False)
    per_owner_concurrency = models.PositiveSmallIntegerField(default=2)
    global_concurrency = models.PositiveSmallIntegerField(default=4)
    force_manual_carrier_codes = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'insurance_import_runtime_config'
        verbose_name = '증권 검토 실행 설정'
        verbose_name_plural = '증권 검토 실행 설정'
        constraints = [
            models.CheckConstraint(
                check=Q(pk=1), name='insurance_import_config_pk_one'),
        ]

    def clean(self):
        from .import_validation import sanitize_force_manual_carrier_codes

        errors = {}
        for field in ('per_owner_concurrency', 'global_concurrency'):
            value = getattr(self, field)
            if type(value) is not int or not 1 <= value <= 100:
                errors[field] = '1부터 100 사이의 정수를 입력하세요.'
        if (not errors.get('per_owner_concurrency')
                and not errors.get('global_concurrency')
                and self.per_owner_concurrency > self.global_concurrency):
            errors['per_owner_concurrency'] = (
                '설계사별 상한은 전체 상한보다 클 수 없습니다.')
        canonical_codes = sanitize_force_manual_carrier_codes(
            self.force_manual_carrier_codes)
        if self.force_manual_carrier_codes != canonical_codes:
            errors['force_manual_carrier_codes'] = (
                '지원하는 보험사 코드의 정렬된 중복 없는 목록을 입력하세요.')
        if errors:
            raise ValidationError(errors)

        super().clean()

    @classmethod
    def solo(cls):
        config, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                'per_owner_concurrency': getattr(
                    settings, 'INSURANCE_IMPORT_PER_OWNER_LIMIT', 2),
                'global_concurrency': getattr(
                    settings, 'INSURANCE_IMPORT_GLOBAL_LIMIT', 4),
            },
        )
        return config

    def __str__(self):
        return (
            f'per_owner={self.per_owner_concurrency} '
            f'global={self.global_concurrency}'
        )
