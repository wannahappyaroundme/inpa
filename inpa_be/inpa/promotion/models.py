"""판촉물 도메인 모델 (dev/21, dev/02 §11).

모델 4종:
  PromotionSample          — 샘플 카탈로그 (공유 — 읽기, 관리자 쓰기). owner FK 없음.
  PromotionSampleImage     — 샘플 이미지 (공유 — PromotionSample 종속).
  PromotionOrder           — 주문 (소유자 + 관리자). OwnedQuerySetMixin 적용.
  PromotionOrderStatusLog  — 상태 변경 이력 (소유자 본인 주문 로그 + 관리자).

★ 가시성 매트릭스 (dev/02 §0, dev/21 §5):
  PromotionSample/Image  — owner FK 없음. 인증 설계사 전원 읽기, 관리자만 쓰기.
  PromotionOrder         — OwnedQuerySetMixin(owner 필드). 설계사 본인만, 관리자 전체.
  PromotionOrderStatusLog — PromotionOrder 종속. 주문 소유자 + 관리자.

★ 정직성 레드라인 (dev/21 §7.2):
  - 자동발송 없음. 주문 = 예약 접수. 제작·발송은 관리자 수동.
  - 설계사에게 상태 변경 알림은 인앱 Notification(설계사 본인 대상)만.
  - 카카오·SMS 자동발송 경로 물리 부재.
  - admin_note는 설계사에게도 노출 (운영 메모, 광고 내용 아님).

★ form_response PII 레드라인 (dev/21 §7.3):
  - form_response JSON에 설계사 본인 연락처·문구 포함 가능.
  - 소유자(owner) + 관리자만 접근. 타 설계사 API 응답에 절대 노출 금지.
"""
from django.conf import settings
from django.db import models


class PromotionSample(models.Model):
    """판촉물 샘플 카탈로그 — 공유(모든 인증 설계사 읽기) + 관리자만 쓰기.

    form_fields JSON: 관리자가 샘플별 수집 항목을 자유 정의.
    예: [
      {"key":"quantity","label":"수량","type":"number","required":true,"min":50},
      {"key":"color","label":"색상","type":"radio","options":["빨강","파랑"],"required":true}
    ]
    필드 타입: text / number / select / radio / checkbox / textarea / file

    owner FK 없음 — 공유 데이터. OwnedQuerySetMixin 미적용.
    """
    CATEGORY_BUSINESS_CARD = '명함'
    CATEGORY_CALENDAR = '달력'
    CATEGORY_LEAFLET = '리플렛'
    CATEGORY_PAMPHLET = '팜플렛'
    CATEGORY_FILE_HOLDER = '파일보관함'
    CATEGORY_DIARY = '다이어리'
    CATEGORY_LIFE = '생활용품'
    CATEGORY_ETC = '기타'
    # category 는 choices 없는 자유 문자열(관리자가 새 분류 자유 추가) — 위는 표준 분류 상수.

    name = models.CharField('샘플명', max_length=100)
    category = models.CharField(
        '카테고리', max_length=30,
        help_text='달력 / 다이어리 / 생활용품 / 기타',
    )
    description = models.TextField('설명(재질·사이즈·납기 등)', blank=True)
    is_available = models.BooleanField(
        '주문 가능', default=True,
        help_text='False = 품절·단종 → 설계사 목록에 "주문 불가" 배지.',
    )

    # 동적 폼 필드 정의 (관리자가 샘플별 항목 구성)
    form_fields = models.JSONField(
        '폼 필드 정의',
        default=list,
        help_text='[{"key":str,"label":str,"type":str,"required":bool,...}]',
    )

    # ── 전자자료(전자명함·전자팜플렛·전자영업자료) — PM 06.24 ──
    # is_digital=True: 1회 무료 다운로드(digital_file) 후, 2회차+는 어드민 주문 큐로.
    is_digital = models.BooleanField('전자자료', default=False)
    digital_file = models.FileField('전자자료 파일(1회 무료 다운로드)',
                                    upload_to='promotion/digital/', null=True, blank=True)

    sort_order = models.IntegerField('노출 순서', default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'promotion_sample'
        ordering = ['sort_order', '-created_at']
        verbose_name = '판촉물 샘플'
        verbose_name_plural = '판촉물 샘플'

    def __str__(self):
        return f'{self.name} ({self.category})'


class PromotionSampleImage(models.Model):
    """샘플 이미지 — PromotionSample 종속. 공유(읽기)."""

    sample = models.ForeignKey(
        PromotionSample,
        on_delete=models.CASCADE,
        related_name='images',
        verbose_name='샘플',
    )
    image_url = models.URLField('이미지 URL (S3)', max_length=500)
    is_primary = models.BooleanField('대표 이미지', default=False)
    sort_order = models.IntegerField('순서', default=0)

    class Meta:
        db_table = 'promotion_sample_image'
        ordering = ['sort_order', 'id']
        verbose_name = '샘플 이미지'
        verbose_name_plural = '샘플 이미지'

    def __str__(self):
        return f'{self.sample.name} 이미지#{self.pk}'


class PromotionOrder(models.Model):
    """판촉물 주문 — 소유자(설계사) + 관리자.

    상태 머신 (dev/21 §3.3):
      pending    예약 접수  → [reviewing, cancelled]
      reviewing  검토 중    → [producing, cancelled]
      producing  제작 중    → [shipping,  cancelled]
      shipping   발송       → [completed, cancelled]
      completed  완료       (종결)
      cancelled  취소       (종결)

    OwnedQuerySetMixin 적용: 설계사는 본인 주문만, 관리자는 전체.
    owner SET_NULL: 탈퇴 설계사 주문은 owner=null 보존(운영 감사용).
    """
    STATUS_PENDING = 'pending'
    STATUS_REVIEWING = 'reviewing'
    STATUS_PRODUCING = 'producing'
    STATUS_SHIPPING = 'shipping'
    STATUS_COMPLETED = 'completed'
    STATUS_CANCELLED = 'cancelled'

    STATUS_CHOICES = [
        (STATUS_PENDING,   '예약 접수'),
        (STATUS_REVIEWING, '검토 중'),
        (STATUS_PRODUCING, '제작 중'),
        (STATUS_SHIPPING,  '발송'),
        (STATUS_COMPLETED, '완료'),
        (STATUS_CANCELLED, '취소'),
    ]

    VALID_TRANSITIONS = {
        STATUS_PENDING:   [STATUS_REVIEWING, STATUS_CANCELLED],
        STATUS_REVIEWING: [STATUS_PRODUCING, STATUS_CANCELLED],
        STATUS_PRODUCING: [STATUS_SHIPPING,  STATUS_CANCELLED],
        STATUS_SHIPPING:  [STATUS_COMPLETED, STATUS_CANCELLED],
        STATUS_COMPLETED: [],
        STATUS_CANCELLED: [],
    }

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='promotion_orders',
        verbose_name='소유자(설계사)',
    )
    sample = models.ForeignKey(
        PromotionSample,
        on_delete=models.SET_NULL,
        null=True,
        related_name='orders',
        verbose_name='선택 샘플',
    )

    # 설계사가 입력한 폼 필드 응답 (키 = form_fields[].key)
    # 예: {"quantity": 100, "name_text": "홍길동 010-1234", "color": "파랑"}
    form_response = models.JSONField(
        '폼 응답',
        default=dict,
        help_text='★ PII 포함 가능. owner + 관리자만 접근.',
    )

    status = models.CharField(
        '주문 상태', max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )

    # 관리자 메모 — 설계사 주문 상세에도 노출
    admin_note = models.TextField('관리자 메모', blank=True)

    # 발송 정보 (STATUS_SHIPPING 이후)
    tracking_number = models.CharField('운송장 번호', max_length=100, blank=True)
    carrier = models.CharField('택배사', max_length=50, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'promotion_order'
        ordering = ['-created_at']
        verbose_name = '판촉물 주문'
        verbose_name_plural = '판촉물 주문'

    def __str__(self):
        owner_str = self.owner.email if self.owner else '(탈퇴)'
        return f'주문#{self.pk} {owner_str} [{self.get_status_display()}]'

    def transition_to(self, new_status: str, changed_by) -> 'PromotionOrderStatusLog':
        """상태 전이 유효성 검사 후 저장.

        Args:
            new_status: 전이할 상태 코드
            changed_by: 변경 주체 (관리자 User 또는 설계사 본인)

        Returns:
            생성된 PromotionOrderStatusLog

        Raises:
            ValueError: 허용되지 않은 전이 시도
        """
        allowed = self.VALID_TRANSITIONS.get(self.status, [])
        if new_status not in allowed:
            raise ValueError(
                f"'{self.get_status_display()}'('{self.status}') → "
                f"'{new_status}' 전이는 허용되지 않습니다. "
                f"허용: {allowed}"
            )
        self.status = new_status
        self.save(update_fields=['status', 'updated_at'])
        return PromotionOrderStatusLog.objects.create(
            order=self,
            to_status=new_status,
            changed_by=changed_by,
        )


class PromotionDownload(models.Model):
    """전자자료 다운로드/요청 이력 — 소유자 전용 (PM 06.24).

    1회차(is_free=True) = 무료 다운로드. 2회차+ = 어드민 주문(order) 연결 → 운영팀 수동 제작.
    """
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='promotion_downloads', verbose_name='설계사(소유자)')
    sample = models.ForeignKey(
        PromotionSample, on_delete=models.CASCADE,
        related_name='downloads', verbose_name='전자자료 샘플')
    is_free = models.BooleanField('무료(1회차)', default=False)
    order = models.ForeignKey(
        'PromotionOrder', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='downloads', verbose_name='연결 주문(2회차+)')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'promotion_download'
        ordering = ['-created_at']
        verbose_name = '전자자료 다운로드'
        verbose_name_plural = '전자자료 다운로드'

    def __str__(self):
        return f'{self.owner_id}/{self.sample_id} {"free" if self.is_free else "queued"}'


class PromotionOrderStatusLog(models.Model):
    """주문 상태 변경 이력 — 타임라인 + 감사추적.

    설계사 주문 상세의 타임라인 렌더링 및 관리자 감사추적에 사용.
    append-only: UPDATE/DELETE 금지.
    """
    order = models.ForeignKey(
        PromotionOrder,
        on_delete=models.CASCADE,
        related_name='status_logs',
        verbose_name='주문',
    )
    to_status = models.CharField('전이 상태', max_length=20)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name='변경자(관리자/설계사)',
    )
    changed_at = models.DateTimeField('변경 시각', auto_now_add=True)
    note = models.TextField('전이 메모', blank=True)

    class Meta:
        db_table = 'promotion_order_status_log'
        ordering = ['changed_at']
        verbose_name = '주문 상태 이력'
        verbose_name_plural = '주문 상태 이력'

    def __str__(self):
        return f'주문#{self.order_id} → {self.to_status} @ {self.changed_at}'

    def get_to_status_display(self):
        """상태 코드 → 한국어 라벨 (PromotionOrder.STATUS_CHOICES 참조)."""
        return dict(PromotionOrder.STATUS_CHOICES).get(self.to_status, self.to_status)
