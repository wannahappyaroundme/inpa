"""알림 도메인 모델 — 소유자 전용 (dev/22, dev/02 §0).

모델 2종:
  Notification  — 발화된 알림(읽음/삭제 상태 머신). OwnedQuerySetMixin 소유자 전용.
  ReminderRule  — 설계사별 "며칠 전" 알림 설정(5종 고정 enum). 소유자 전용.

★ 정직성 레드라인 (dev/22 §6.2):
  - Notification.owner = 설계사 본인. 고객(Customer)에게 자동발송하는 경로 물리 부재.
  - customer.mobile_phone_number / 고객 이메일 발송 필드 없음.
  - 이메일 발송 대상은 오직 설계사 본인 가입 이메일(sent_email 플래그만 기록, 실제 인프라 확정 후 전송).

★ 멀티테넌시 (dev/02 §0):
  - 소유자 전용: OwnedQuerySetMixin + IsOwner + IsEmailVerified 3중 강제.
  - 설계사 A의 알림이 B에게 노출되면 코드리뷰 reject.
"""
from django.conf import settings
from django.db import models


class NotifType(models.TextChoices):
    """알림 유형 7종 (dev/22 §2.4 + dev/02 §9.1 게시판 확장).

    스케줄형 5종 (ReminderRule 대상):
      expiry_soon / birthday_soon / consult_reminder / task_due / share_unread
    즉시 이벤트 2종 (ReminderRule 대상 아님 — 게시판 댓글·좋아요):
      board_comment / board_like
    """
    EXPIRY_SOON = 'expiry_soon', '만기 임박'
    BIRTHDAY_SOON = 'birthday_soon', '고객 생일'
    CONSULT_REMINDER = 'consult_reminder', '상담 약속'
    TASK_DUE = 'task_due', '할 일 마감'
    SHARE_UNREAD = 'share_unread', '미열람 공유'
    # ── 환수 레이더(A/S) — /churn-radar/sync-alerts/ on-demand 생성(cron 아님). ──
    UNPAID_D_ALERT = 'unpaid_d_alert', '미납 임박'
    # ── 셀프진단 인바운드 리드(발굴 입구) — 잠재고객 진단 완료 시 설계사에게. ──
    SELF_DIAGNOSIS_LEAD = 'self_diagnosis_lead', '셀프진단 리드'
    # ── 게시판 즉시 이벤트 (dev/02 §9.1 확정, ReminderRule 대상 아님) ──
    BOARD_COMMENT = 'board_comment', '게시글 댓글'
    BOARD_LIKE = 'board_like', '게시글 좋아요'
    # ── 미팅 예약(영업) — 고객이 공개 링크에서 예약 확정 시 설계사에게. 즉시 이벤트. ──
    MEETING_BOOKED = 'meeting_booked', '미팅 예약됨'
    # ── 판촉물/전자자료 (PM 06.24) ──
    PROMOTION_STATUS = 'promotion_status', '판촉물 상태'
    PROMOTION_DIGITAL_REQUESTED = 'promotion_digital_requested', '전자자료 요청'   # → 어드민
    PROMOTION_DIGITAL_READY = 'promotion_digital_ready', '전자자료 준비됨'         # → 설계사


class Notification(models.Model):
    """발화된 알림 — 읽음/삭제 상태 머신 (dev/22 §2.2).

    ★ owner FK 강제: OwnedQuerySetMixin이 모든 조회에 filter(owner=request.user) 적용.
    customer / calendar_event FK는 nullable(고객 없는 시스템 알림 허용).
    알림 클릭 → is_read=True 전환, 삭제 시 실제 삭제(감사 목적 불필요 — dev/22 §5.5).
    """
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
        verbose_name='설계사(소유자)',
    )
    notif_type = models.CharField(
        '알림 유형',
        max_length=30,
        choices=NotifType.choices,
    )
    title = models.CharField('알림 제목', max_length=200)
    body = models.TextField('알림 본문')
    target_date = models.DateField(
        '트리거 기준일',
        null=True, blank=True,
        help_text='만기일/생일/약속일/마감일 — 정렬·그룹화 기준 (dev/22 §4.2)',
    )

    # ── 연관 FK (nullable — 고객 없는 시스템 알림 허용) ────────────
    # ★ on_delete=SET_NULL: 고객/이벤트 삭제 시 알림 이력은 보존
    customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='notifications',
        verbose_name='연관 고객',
    )
    # CalendarEvent 앱이 미생성 상태이므로 string 참조로 느슨하게 연결
    # (추후 calendar 앱 생성 시 'calendar.CalendarEvent' 로 변경)
    # 현재는 Integer FK로만 저장 — 정규 FK 없이 ID만 보관
    calendar_event_id = models.PositiveIntegerField(
        '연관 캘린더 이벤트 ID',
        null=True, blank=True,
        help_text='CalendarEvent(미생성 앱) PK. 앱 생성 후 ForeignKey로 교체.',
    )

    # ── 상태 ────────────────────────────────────────────────────────
    is_read = models.BooleanField('읽음 여부', default=False)
    sent_email = models.BooleanField(
        '이메일 발송 여부',
        default=False,
        help_text='opt-in 설정 기반. 인프라 미결 시 미전환(dev/22 §8 G-2).',
    )

    created_at = models.DateTimeField('생성 시각', auto_now_add=True)

    class Meta:
        db_table = 'notification'
        verbose_name = '알림'
        verbose_name_plural = '알림'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['owner', '-created_at']),
            models.Index(fields=['owner', 'is_read']),
        ]
        # 중복 방지 (dev/22 §3.2): 동일 (owner, notif_type, target_date, customer_id) 당일 1회
        constraints = [
            models.UniqueConstraint(
                fields=['owner', 'notif_type', 'target_date', 'customer'],
                name='uniq_notif_owner_type_date_customer',
                condition=models.Q(target_date__isnull=False, customer__isnull=False),
            ),
        ]

    def __str__(self):
        return f'[{self.get_notif_type_display()}] {self.title}'


# ── ReminderRule 기본값 (dev/22 §2.3 테이블) ──────────────────────
REMINDER_DEFAULTS = [
    {'rule_type': NotifType.EXPIRY_SOON,      'days_before': 30, 'enabled': True,  'email_enabled': False},
    {'rule_type': NotifType.BIRTHDAY_SOON,    'days_before': 7,  'enabled': True,  'email_enabled': False},
    {'rule_type': NotifType.CONSULT_REMINDER, 'days_before': 1,  'enabled': True,  'email_enabled': False},
    {'rule_type': NotifType.TASK_DUE,         'days_before': 1,  'enabled': True,  'email_enabled': False},
    {'rule_type': NotifType.SHARE_UNREAD,     'days_before': 0,  'enabled': True,  'email_enabled': False},
]


class ReminderRule(models.Model):
    """설계사별 알림 설정 — "며칠 전" 발화 조건 (dev/22 §2.3).

    5종 고정 enum (notif_type 1:1). 설계사 가입 시 REMINDER_DEFAULTS 기준으로 자동 생성
    (accounts Signal 또는 가입 API 완료 시 create_reminder_rules_for_user() 호출).

    ★ share_unread days_before는 0 고정 — UI는 읽기 전용(dev/22 §4.3).
    days_before 유효 범위: 0~90 (이 바깥 입력은 Serializer에서 400 반환).
    """
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reminder_rules',
        verbose_name='설계사(소유자)',
    )
    rule_type = models.CharField(
        '알림 유형',
        max_length=30,
        choices=NotifType.choices,
    )
    days_before = models.PositiveSmallIntegerField(
        '발화 기준(며칠 전)',
        default=1,
        help_text='0~90. share_unread는 0 고정(24h = 0일 전 특별 해석).',
    )
    enabled = models.BooleanField('이 유형 알림 활성', default=True)
    email_enabled = models.BooleanField(
        '이메일 알림 활성',
        default=False,
        help_text='opt-in. 기본 꺼짐. 켜면 발화 시 설계사 본인 가입 이메일로 발송.',
    )

    updated_at = models.DateTimeField('최종 수정', auto_now=True)

    class Meta:
        db_table = 'reminder_rule'
        verbose_name = '알림 설정'
        verbose_name_plural = '알림 설정'
        constraints = [
            models.UniqueConstraint(
                fields=['owner', 'rule_type'],
                name='uniq_reminder_rule_owner_type',
            ),
        ]

    def __str__(self):
        return f'{self.get_rule_type_display()} D-{self.days_before} (enabled={self.enabled})'


def create_reminder_rules_for_user(user):
    """설계사 가입 완료 시 ReminderRule 5종 기본 생성.

    계정 앱 또는 이메일 인증 완료 시그널에서 호출한다.
    이미 존재하는 rule_type은 건너뜀(중복 생성 방지).
    """
    existing = set(
        ReminderRule.objects.filter(owner=user).values_list('rule_type', flat=True)
    )
    to_create = [
        ReminderRule(owner=user, **defaults)
        for defaults in REMINDER_DEFAULTS
        if defaults['rule_type'] not in existing
    ]
    if to_create:
        ReminderRule.objects.bulk_create(to_create)
