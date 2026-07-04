"""담보 분류 트리 + 정규화 사전 — 공유 전역 마스터 (dev/02 §5).

포팅 원칙: foliio `weapon/insurances/models.py:12~92`의 4계층 분류 모델
  (AnalysisCategory / AnalysisSubCategory / AnalysisDetail / ChartDetail)을
  **모델 무변경**으로 가져온다. 시드만 30 → 100+ 확장(다음 라운드).

가시성(dev/02 §0):
- AnalysisCategory/SubCategory/Detail · ChartDetail → 공유 (owner FK 없음, 전역 표준 마스터)
- NormalizationDict / UnmatchedLog → 공유 (전역) + 관리자 검수

★ 정규화 사전(NormalizationDict)은 보험사별 담보명 → 표준 담보(AnalysisDetail) 매핑으로,
  foliio `claude_parser._add_coverage` 매칭 단계에 끼우는 데이터 복리 해자다(다음 라운드 배선).
"""
from django.conf import settings
from django.db import models


# ── 보험 종류 choices (foliio 4계층 공통) ──────────────────────────
INSURANCE_TYPE = (
    (0, '공통'),
    (1, '생명보험'),
    (2, '손해보험'),
)
INSURANCE_TYPE_DICT = {v: k for k, v in INSURANCE_TYPE}

CHART_TYPE = (
    (1, 'Cart1'),
    (2, 'Cart2'),
)
CHART_TYPE_DICT = {v: k for k, v in CHART_TYPE}


class AnalysisCategory(models.Model):
    """분석 대분류 (♻ foliio insurances/models.py:12 무변경)."""
    INSURANCE_TYPE = INSURANCE_TYPE
    INSURANCE_TYPE_DICT = INSURANCE_TYPE_DICT

    insurance_type = models.SmallIntegerField(choices=INSURANCE_TYPE, default=0)
    name = models.CharField(max_length=20)
    order = models.SmallIntegerField('순서', default=0, blank=True)

    def __str__(self):
        return f'{self.order}, {self.name}'

    class Meta:
        db_table = 'analysis_category'
        verbose_name = '분석 카테고리'
        verbose_name_plural = '분석 카테고리'


class AnalysisSubCategory(models.Model):
    """분석 중분류 (♻ foliio insurances/models.py:32 무변경)."""
    INSURANCE_TYPE = INSURANCE_TYPE
    INSURANCE_TYPE_DICT = INSURANCE_TYPE_DICT

    insurance_type = models.SmallIntegerField(choices=INSURANCE_TYPE, default=0)
    category = models.ForeignKey(AnalysisCategory, on_delete=models.CASCADE, related_name='sub_categories')
    name = models.CharField(max_length=20)
    order = models.SmallIntegerField('순서', default=0, blank=True)

    def __str__(self):
        return f'{self.category.name} / {self.order}, {self.name}'

    class Meta:
        db_table = 'analysis_sub_category'
        verbose_name = '분석 서브 카테고리'
        verbose_name_plural = '분석 서브 카테고리'


class AnalysisDetail(models.Model):
    """분석 세부담보 leaf (♻ foliio insurances/models.py:53 무변경).

    chart_based_amount = 표준 보장 기준선의 물리 저장 위치(dev/02 §5.1). 단 인파의
    히트맵 판정 상위 권위는 planner_baseline(설계사 소유)이다.
    """
    sub_category = models.ForeignKey(AnalysisSubCategory, on_delete=models.CASCADE, related_name='details')
    name = models.CharField(max_length=20)
    order = models.SmallIntegerField('순서', default=0, blank=True)
    chart_based_amount = models.SmallIntegerField('차트 기준 금액', default=0, blank=True)

    def __str__(self):
        return f'{self.name}'

    class Meta:
        db_table = 'analysis_detail'
        verbose_name = '분석 상세 아이템'
        verbose_name_plural = '분석 상세 아이템'


class ChartDetail(models.Model):
    """분석 차트 표시 단위 (♻ foliio insurances/models.py:67 무변경)."""
    CHART_TYPE = CHART_TYPE
    CHART_TYPE_DICT = CHART_TYPE_DICT
    INSURANCE_TYPE = INSURANCE_TYPE
    INSURANCE_TYPE_DICT = INSURANCE_TYPE_DICT

    insurance_type = models.SmallIntegerField(choices=INSURANCE_TYPE, default=0)
    chart_type = models.SmallIntegerField(choices=CHART_TYPE, default=1)
    name = models.CharField(max_length=20)
    order = models.SmallIntegerField('순서', default=0, blank=True)
    chart_based_amount = models.SmallIntegerField('차트 기준 금액', default=0, blank=True)

    def __str__(self):
        return f'{self.name}'

    class Meta:
        db_table = 'chart_detail'
        verbose_name = '분석 차트 아이템'
        verbose_name_plural = '분석 차트 아이템'


class NormalizationDict(models.Model):
    """보험사별 담보명 → 표준 담보(AnalysisDetail) 정규화 사전 (✦ 신규, dev/02 §5.2).

    ★ 데이터 복리 해자 — 전역 공유(owner FK 없음). OCR `raw_name`을 표준 담보로 매핑하고
      매칭마다 hit_count++ 한다. 관리자 검수(source=admin_verified)만 베타 매칭에 사용
      (자동매핑 오류 = 비교안내서 거짓 = §97 위반 리스크, 보수적 기본값).
    """
    SOURCE_SEED = 1
    SOURCE_OCR_LEARNED = 2
    SOURCE_ADMIN_VERIFIED = 3
    SOURCE = (
        (SOURCE_SEED, 'seed'),
        (SOURCE_OCR_LEARNED, 'ocr_learned'),
        (SOURCE_ADMIN_VERIFIED, 'admin_verified'),
    )

    std_detail = models.ForeignKey(AnalysisDetail, on_delete=models.CASCADE, related_name='aliases')
    company = models.SmallIntegerField('보험사 코드')
    raw_name = models.CharField('보험사 담보 원문', max_length=120, db_index=True)
    source = models.SmallIntegerField('출처', choices=SOURCE, default=SOURCE_SEED)
    confidence = models.SmallIntegerField('신뢰도', default=100)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name='verified_normalizations')
    hit_count = models.IntegerField('매칭 누적', default=0)  # ★ 매칭마다 ++ (데이터 복리)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'normalization_dict'
        verbose_name = '정규화 사전'
        verbose_name_plural = '정규화 사전'
        constraints = [
            models.UniqueConstraint(fields=['company', 'raw_name'], name='uniq_norm_company_rawname'),
        ]
        indexes = [models.Index(fields=['raw_name'])]

    def __str__(self):
        return f'[{self.company}] {self.raw_name} → {self.std_detail.name}'


class SeedMarker(models.Model):
    """시드 데이터 버전 마커 (✦ 2026-07-04, LB-1 시드 안전화).

    seed_normalization / seed_jobs 같은 무겁거나 파괴적 이력이 있는 시드 커맨드가
    "데이터 버전이 이미 최신이면 no-op"으로 부팅 경로를 무해화하기 위한 마커.
    커맨드마다 key 1행 (예: 'seed_normalization'), version은 코드의 데이터 버전 상수
    (데이터 변경 시 수동 bump). --force 로 우회 가능.
    """
    key = models.CharField('시드 키', max_length=50, unique=True)
    version = models.CharField('데이터 버전', max_length=20)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'seed_marker'
        verbose_name = '시드 마커'
        verbose_name_plural = '시드 마커'

    def __str__(self):
        return f'{self.key}={self.version}'


class UnmatchedLog(models.Model):
    """미매칭 담보명 학습 플라이휠 (✦ 신규, dev/02 §5.3).

    공유 전역 + 관리자 검수. OCR `raw_name`이 NormalizationDict에 없으면 적재 →
    admin 1탭 매핑 → NormalizationDict 영구 추가(source=admin_verified) →
    다음 OCR부터 자동 매칭(복리).
    """
    company = models.SmallIntegerField('보험사 코드')
    raw_name = models.CharField('미매칭 담보 원문', max_length=120, db_index=True)
    occurrence = models.IntegerField('발생 횟수', default=1)
    sample_ctx = models.CharField('샘플 컨텍스트', max_length=300, default='', blank=True)
    resolved = models.BooleanField('매핑 완료 여부', default=False)  # admin 매핑 완료 여부

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'unmatched_log'
        verbose_name = '미매칭 로그'
        verbose_name_plural = '미매칭 로그'
        indexes = [models.Index(fields=['raw_name'])]

    def __str__(self):
        return f'[{self.company}] {self.raw_name} (x{self.occurrence})'
