"""고객 도메인 모델 — 소유자 전용 (dev/02 §3·§4·§6, dev/12 §4).

포팅 원칙: foliio `weapon/customers/models.py`의 Customer 재활용 필드를 그대로 가져오고,
인파 신규 자산(owner 스코프 + 국외이전 동의 게이트 + 태그 + planner_baseline)을 얹는다.

가시성(dev/02 §0):
- Customer / CustomerTag / FamilyMember / CustomerMedicalHistory / PlannerBaseline → 소유자 전용
- ConsentLog → 소유자 전용 (customer__owner 경유, append-only 감사 로그)

★ 준법 통제점: PlannerBaseline.baseline_source(=source)가 null이면 분석은 neutral 강제.
  (이번 라운드는 모델만 — 분석/히트맵 판정 로직은 다음 라운드.)
"""
import uuid

from django.conf import settings
from django.db import models


def compute_insurance_age(birth_day, as_of=None):
    """보험나이(보험상령일 규칙): 만나이 기준 + 마지막 생일로부터 6개월 이상 지나면 +1.

    PM 피드백(06.24): "보험나이는 만으로 계산한거 + 6개월". calculate.py의 contract-time
    'years+1' 관습과는 다른 정확한 상령일 규칙이라 별도 헬퍼로 둔다.
    birth_day='YYYY-MM-DD'. 파싱 불가/미래 생일이면 None.
    """
    from datetime import date

    from dateutil.relativedelta import relativedelta

    if not birth_day:
        return None
    try:
        parts = str(birth_day).split('-')
        bd = date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, TypeError, IndexError):
        return None
    rd = relativedelta(as_of or date.today(), bd)
    if rd.years < 0:
        return None
    return rd.years + (1 if rd.months >= 6 else 0)


class Customer(models.Model):
    """고객 — 설계사 자산 (소유자 전용).

    재활용 필드(♻ foliio 무변경): name, mobile_phone_number, birth_day, gender,
      job_code, memo, color, share_token, share_expires_at, user_view_at, is_agree_term.
    신규 필드(✦): owner(CASCADE), consent_overseas_at(detect 412 게이트 키),
      share_sent_at(공유 알림 트리거), tags(M2M).
    """
    GENDER_TYPE = (
        (1, '남'),
        (2, '여'),
    )

    # ── owner 스코프 (멀티테넌시 핵심) ──────────────────────────────
    # foliio는 SET_NULL(유령행)이나 인파는 CASCADE — 탈퇴 시 고객 개인정보 연쇄 삭제 (dev/02 §3.1 결정 8)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name='customers')

    # ── 재활용 필드 (♻ foliio 무변경) ──────────────────────────────
    name = models.CharField('이름', max_length=20)
    mobile_phone_number = models.CharField('연락처', max_length=15, default='', blank=True)
    birth_day = models.CharField('생일', max_length=10, blank=True, default='')  # YYYY-MM-DD (foliio CharField 계승)
    gender = models.SmallIntegerField('성별', choices=GENDER_TYPE, default=None, null=True, blank=True)
    job_code = models.ForeignKey('JobRiskCode', verbose_name='직업 코드(위험등급)',
                                 on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='customers')
    memo = models.TextField('메모', blank=True, default='')
    color = models.CharField('색상 마커', max_length=10, blank=True, default='')  # 7색 팔레트 키워드 또는 ''
    is_agree_term = models.BooleanField('일반 동의 여부', default=False, blank=True)
    share_token = models.UUIDField('공유 토큰', default=uuid.uuid4, unique=True)
    share_expires_at = models.DateTimeField('공유 만료일', default=None, null=True, blank=True)
    user_view_at = models.DateTimeField('고객 열람 시각', default=None, null=True, blank=True)

    # ── 병력 = 민감정보 = AI 분석(detect) 게이트 ────────────────────
    # null = 미동의 → detect API 호출 전 412 게이트. is_agree_term(일반 동의)로 덮지 않는다.
    consent_overseas_at = models.DateTimeField('병력 국외이전 동의 시각', null=True, blank=True, default=None)

    # ── 공유/알림 계측 ─────────────────────────────────────────────
    share_sent_at = models.DateTimeField('공유 발송 시각', null=True, blank=True, default=None)

    # ── 셀프진단 리드(발굴 입구) ───────────────────────────────────
    # 잠재고객이 ?ref 셀프진단으로 유입돼 자동 생성된 리드. null = 설계사가 직접 등록한 고객.
    lead_source = models.CharField('리드 출처', max_length=30, null=True, blank=True, default=None)
    lead_created_at = models.DateTimeField('리드 생성 시각', null=True, blank=True, default=None)

    # ── 영업 단계 (파이프라인 — 칸반/퍼널 공용 데이터) ───────────────
    # 발굴→계약 4단계. 칸반 드래그·단계이동이 이 값만 PATCH한다. 홈 퍼널(011) 카운트도 이 필드.
    STAGE_DB = 'db'              # DB확보
    STAGE_CONTACT = 'contact'   # 전화·메신저 영업
    STAGE_MEETING = 'meeting'   # 대면 상담
    STAGE_CONTRACT = 'contract'  # 계약
    SALES_STAGE_CHOICES = (
        (STAGE_DB, 'DB'),          # 잠재고객 풀(이름·연락처만)
        (STAGE_CONTACT, 'TA'),     # Telephone Approach — 전화·문자 접근
        (STAGE_MEETING, 'FA'),     # Face-to-face Approach — 대면 상담
        (STAGE_CONTRACT, '청약'),  # 보험 계약 청약
    )
    sales_stage = models.CharField('영업 단계', max_length=10,
                                   choices=SALES_STAGE_CHOICES, default=STAGE_DB,
                                   db_index=True)

    # ── 태그 (설계사 자유 분류) ────────────────────────────────────
    tags = models.ManyToManyField('CustomerTag', blank=True, related_name='customers')

    # ── 고객 관리 (최종연락·즐겨찾기·상단고정·명함) — PM 06.24 피드백 ─────
    # last_contacted_at: 방치 색상경보(3일↑ 노랑/7일↑ 빨강)·정렬 기준. 수동 '연락함' 또는 미팅·발송 시 갱신.
    last_contacted_at = models.DateTimeField('최종 연락일', null=True, blank=True, default=None)
    is_favorite = models.BooleanField('즐겨찾기', default=False)
    is_pinned = models.BooleanField('상단 고정', default=False)
    business_card = models.ImageField('명함 이미지', upload_to='business_cards/', null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'customer'
        verbose_name = '고객'
        verbose_name_plural = '고객'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['owner', '-created_at']),
            models.Index(fields=['owner', 'name']),
        ]

    def __str__(self):
        return self.name


class JobRiskCode(models.Model):
    """직업 위험등급 코드 (foliio ♻ 축약 포팅 — 전역 표준 마스터, 공유).

    foliio 전체 메리츠 분류 체계는 추후 시드 확장. 이번 라운드는 Customer.job_code FK
    무결성을 위한 최소 모델만 둔다. owner FK 없음(전역 마스터).
    """
    RISK_GRADE_CHOICES = (
        (1, '1급'),
        (2, '2급'),
        (3, '3급'),
        (9, '기타'),
    )

    sctg_cd = models.CharField('소분류 코드', max_length=10, db_index=True)
    name = models.CharField('직업명', max_length=120, db_index=True)
    risk_grade = models.PositiveSmallIntegerField('위험등급', choices=RISK_GRADE_CHOICES, default=9)
    source = models.CharField('출처', max_length=20, default='meritz')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'job_risk_code'
        verbose_name = '직업 위험등급 코드'
        verbose_name_plural = '직업 위험등급 코드'
        constraints = [
            models.UniqueConstraint(fields=['sctg_cd', 'name'], name='uniq_jobriskcode_sctg_name'),
        ]

    def __str__(self):
        return f'{self.name} ({self.risk_grade}급)'


class CustomerTag(models.Model):
    """설계사 자유 분류 태그 (소유자 전용). UNIQUE(owner, label)로 설계사별 네임스페이스 분리."""
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name='customer_tags')
    label = models.CharField('태그 이름', max_length=30)
    color = models.CharField('색 칩', max_length=20, blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'customer_tag'
        verbose_name = '고객 태그'
        verbose_name_plural = '고객 태그'
        constraints = [
            models.UniqueConstraint(fields=['owner', 'label'], name='uniq_tag_owner_label'),
        ]

    def __str__(self):
        return self.label


class FamilyMember(models.Model):
    """가족구성원 (소유자 전용 — customer__owner 경유). 공유뷰 노출 0."""
    RELATION_CHOICES = (
        ('self', '본인'),
        ('spouse', '배우자'),
        ('child', '자녀'),
        ('parent', '부모'),
        ('other', '기타'),
    )
    GENDER_TYPE = (
        (1, '남'),
        (2, '여'),
    )

    customer = models.ForeignKey('Customer', on_delete=models.CASCADE, related_name='family_members')
    relation = models.CharField('관계', max_length=20, choices=RELATION_CHOICES, default='other')
    name = models.CharField('이름', max_length=20, null=True, blank=True)
    birth_day = models.CharField('생년월일', max_length=10, null=True, blank=True)  # YYYY-MM-DD
    gender = models.SmallIntegerField('성별', choices=GENDER_TYPE, null=True, blank=True)
    memo = models.CharField('메모', max_length=200, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'family_member'
        verbose_name = '가족구성원'
        verbose_name_plural = '가족구성원'
        ordering = ['id']

    def __str__(self):
        return f'{self.get_relation_display()}:{self.name or "-"}'


class CustomerMedicalHistory(models.Model):
    """고객 병력 (소유자 전용 — customer__owner 경유, foliio ♻ 별도 모델).

    ★ 병력 = 민감정보 = 국외이전 동의 대상. ConsentLog(scope=overseas_medical) +
      Customer.consent_overseas_at 2중 게이트 아래에서만 Claude API detect에 전달.
    등록 게이트: Customer.consent_overseas_at 없으면 ViewSet에서 거부.
    """
    customer = models.ForeignKey('Customer', on_delete=models.CASCADE, related_name='medical_histories')
    disease_name = models.CharField('병명/진단', max_length=100)
    diagnosed_at = models.CharField('진단일', max_length=10, null=True, blank=True)  # YYYY-MM-DD
    is_inpatient = models.BooleanField('입원여부', default=False)
    treatment_content = models.CharField('치료 내용', max_length=100, blank=True, default='')
    hospital_name = models.CharField('병원명', max_length=100, blank=True, default='')
    memo = models.CharField('메모', max_length=200, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'customer_medical_history'
        verbose_name = '고객 병력'
        verbose_name_plural = '고객 병력'
        ordering = ['-created_at']

    def __str__(self):
        return self.disease_name


class ConsentLog(models.Model):
    """동의 감사 로그 (소유자 전용 — customer__owner 경유, ★append-only).

    consent_overseas_at = "지금 동의 상태인가" 스냅샷, ConsentLog = "언제·어떤 버전·누가·어디서"
    불변 감사 로그. 둘 다 필요(dev/02 §4.1). INSERT만 허용, UPDATE/DELETE 금지.
    철회는 삭제가 아니라 revoked_at 기록.

    ★ on_delete=SET_NULL(council 2026-06-21 P0-5): 고객 삭제(파기) 시에도 동의 증거는
      보존한다(처리방침상 동의기록 5년 보관). CASCADE면 고객 삭제로 감사기록이 함께
      소멸해 append-only 원칙과 모순됨. 고객이 null이 된 로그는 owner 쿼리에서 빠지고
      관리자 감사 용도로만 남는다.
    """
    SCOPE_OVERSEAS_MEDICAL = 'overseas_medical'
    SCOPE_MEDICAL_SENSITIVE = 'medical_sensitive'
    SCOPE_MARKETING = 'marketing'
    SCOPE_CHOICES = (
        (SCOPE_OVERSEAS_MEDICAL, '병력 국외이전 (Claude API, 미국)'),
        (SCOPE_MEDICAL_SENSITIVE, '민감정보(병력) 처리'),
        (SCOPE_MARKETING, '마케팅 수신'),
    )

    # ★ 동의 주체(council P3c): 누가 동의했나 = 감사 핵심.
    #   customer_self = 고객 본인이 자기 기기에서 동의(셀프진단 / 동의요청 링크) → 적법.
    #   planner_attested = 설계사가 기록(대리) → 감사용으로만 남고 국외이전 게이트를 열지 못함.
    SUBJECT_CUSTOMER_SELF = 'customer_self'
    SUBJECT_PLANNER_ATTESTED = 'planner_attested'
    SUBJECT_CHOICES = (
        (SUBJECT_CUSTOMER_SELF, '고객 본인'),
        (SUBJECT_PLANNER_ATTESTED, '설계사 기록(대리)'),
    )

    customer = models.ForeignKey('Customer', on_delete=models.SET_NULL, null=True, blank=True, related_name='consent_logs')
    scope = models.CharField('동의 범위', max_length=50, choices=SCOPE_CHOICES)
    subject = models.CharField('동의 주체', max_length=20, choices=SUBJECT_CHOICES,
                               default=SUBJECT_PLANNER_ATTESTED)
    purpose = models.CharField('처리 목적', max_length=200, default='', blank=True)
    doc_version = models.CharField('약관 버전', max_length=30, blank=True, default='')  # PolicyVersion.version 참조
    agreed_at = models.DateTimeField('동의 시각', auto_now_add=True)  # 불변
    ip = models.GenericIPAddressField('동의 IP', null=True, blank=True)
    revoked_at = models.DateTimeField('철회 시각', null=True, blank=True)  # null = 유효, 값 = 철회
    revoke_ip = models.GenericIPAddressField('철회 IP', null=True, blank=True)

    class Meta:
        db_table = 'consent_log'
        verbose_name = '동의 로그'
        verbose_name_plural = '동의 로그'
        ordering = ['-agreed_at']
        indexes = [models.Index(fields=['customer', 'scope'])]

    def __str__(self):
        return f'{self.get_scope_display()}@{self.agreed_at:%Y-%m-%d}'


class PlannerBaseline(models.Model):
    """설계사 기준선 (소유자 전용 — ★ 준법 통제점, dev/02 §6 · dev/10).

    표기상 planner_baseline. 설계사가 소유하는 보장 기준 — 인파는 중개·권유하지 않으며
    "부족/충분" 판정 권위는 설계사에게 있다.

    ★ neutral 강제: 해당 coverage_key의 baseline이 없거나 source가 null이면 분석은 neutral 강제
      (이번 라운드는 모델만 — 판정 로직은 다음 라운드).
    """
    PRODUCT_GROUP_LIFE = 1
    PRODUCT_GROUP_NONLIFE = 2
    PRODUCT_GROUP_INDEMNITY = 3
    PRODUCT_GROUP_ANNUITY = 4
    PRODUCT_GROUP_CHOICES = (
        (PRODUCT_GROUP_LIFE, '생명'),
        (PRODUCT_GROUP_NONLIFE, '손해'),
        (PRODUCT_GROUP_INDEMNITY, '실손'),
        (PRODUCT_GROUP_ANNUITY, '연금저축'),
    )
    GENDER_TYPE = (
        (1, '남'),
        (2, '여'),
    )

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name='planner_baselines')
    coverage_key = models.CharField('표준 담보 키', max_length=120, db_index=True)
    product_group = models.SmallIntegerField('상품군', choices=PRODUCT_GROUP_CHOICES)
    age_band = models.CharField('연령대', max_length=10)  # '20s'|'30s'|'40s'|'50s'|'60s+'
    gender = models.SmallIntegerField('성별', choices=GENDER_TYPE, null=True, blank=True)  # null=공통
    recommend_min = models.DecimalField('권장 하한', max_digits=14, decimal_places=2, null=True, blank=True)
    recommend_max = models.DecimalField('권장 상한', max_digits=14, decimal_places=2, null=True, blank=True)
    unit = models.SmallIntegerField('금액 단위', default=1)  # 1=만원/2=원/3=구좌

    # ★ 준법 통제점 물리 키 — null이면 분석 neutral 강제
    baseline_source = models.CharField('기준 출처', max_length=30, null=True, blank=True,
                                       default=None)  # 'planner' | 'preset:<id>' | null
    preset_origin = models.CharField('프리셋 출처 라벨', max_length=100, null=True, blank=True)
    is_active = models.BooleanField('활성', default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'planner_baseline'
        verbose_name = '설계사 기준선'
        verbose_name_plural = '설계사 기준선'
        constraints = [
            models.UniqueConstraint(
                fields=['owner', 'coverage_key', 'product_group', 'age_band', 'gender'],
                name='uniq_baseline_scope'),
        ]

    def __str__(self):
        return f'{self.coverage_key}/{self.age_band} (src={self.baseline_source})'
