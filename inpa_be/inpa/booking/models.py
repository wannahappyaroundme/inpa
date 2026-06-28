"""미팅 예약 도메인 — 소유자 전용 (Calendly식 내장 예약).

MeetingSlot — 설계사가 열어둔 일회성 가용 슬롯 (open→booked→canceled).
Meeting     — 고객이 공개 링크(/b/<token>)에서 확정한 예약.

★ owner FK 강제(OwnedQuerySetMixin). 공개 예약은 토큰의 customer.owner 슬롯만 본다.
★ 정직성 레드라인: 고객 자동발송 없음(링크 복사·붙여넣기). 공개 GET은 마스킹 이름만.
"""
from django.conf import settings
from django.db import models


class WorkHour(models.Model):
    """설계사 주간 업무시간(반복). 이 시간 안에서 미팅·차단·버퍼를 빼고 빈 슬롯을 자동 노출한다.

    ★ 타임존: start_time/end_time = KST 벽시계 그대로(변환 금지). 반복 차단(ScheduleItem)과 동일 규약.
    """
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='work_hours', verbose_name='설계사(소유자)')
    weekday = models.PositiveSmallIntegerField('요일(0=월..6=일)')
    start_time = models.TimeField('시작')  # KST 벽시계
    end_time = models.TimeField('종료')    # KST 벽시계
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'work_hour'
        verbose_name = '업무시간'
        verbose_name_plural = '업무시간'
        ordering = ['weekday', 'start_time']
        indexes = [models.Index(fields=['owner', 'weekday'])]

    def __str__(self):
        return f'{self.owner_id} wd{self.weekday} {self.start_time}-{self.end_time}'


class MeetingSlot(models.Model):
    """설계사 가용 슬롯 (일회성 datetime). 반복 주간가용은 범위 밖."""
    STATUS_OPEN = 'open'
    STATUS_BOOKED = 'booked'
    STATUS_CANCELED = 'canceled'
    STATUS_CHOICES = (
        (STATUS_OPEN, '열림'),
        (STATUS_BOOKED, '예약됨'),
        (STATUS_CANCELED, '취소됨'),
    )

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='meeting_slots', verbose_name='설계사(소유자)')
    start_at = models.DateTimeField('시작 시각')
    duration_min = models.PositiveSmallIntegerField('소요(분)', default=30)
    status = models.CharField('상태', max_length=10, choices=STATUS_CHOICES, default=STATUS_OPEN)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'meeting_slot'
        verbose_name = '미팅 슬롯'
        verbose_name_plural = '미팅 슬롯'
        ordering = ['start_at']
        indexes = [models.Index(fields=['owner', 'status', 'start_at'])]
        constraints = [
            models.UniqueConstraint(fields=['owner', 'start_at'], name='uniq_slot_owner_start'),
        ]

    def __str__(self):
        return f'{self.owner_id}@{self.start_at:%Y-%m-%d %H:%M} ({self.status})'


class Meeting(models.Model):
    """확정된 미팅 예약. 슬롯/고객 삭제돼도 이력 보존(SET_NULL + 시각 비정규화)."""
    METHOD_IN_PERSON = 'in_person'
    METHOD_PHONE = 'phone'
    METHOD_VIDEO = 'video'
    METHOD_CHOICES = (
        (METHOD_IN_PERSON, '대면'),
        (METHOD_PHONE, '전화'),
        (METHOD_VIDEO, '화상'),
    )
    STATUS_PENDING = 'pending'        # 고객이 신청 → 설계사 수락 대기
    STATUS_CONFIRMED = 'confirmed'    # 설계사 수락(확정)
    STATUS_CANCELED = 'canceled'      # 확정 후 취소
    STATUS_DECLINED = 'declined'      # 설계사 거절(대기 → 거절)
    STATUS_CHOICES = (
        (STATUS_PENDING, '대기'),
        (STATUS_CONFIRMED, '확정'),
        (STATUS_CANCELED, '취소됨'),
        (STATUS_DECLINED, '거절됨'),
    )
    # 시간을 점유(중복 차단)하는 상태 — 빈 슬롯 계산에서 제외 대상.
    ACTIVE_STATUSES = (STATUS_PENDING, STATUS_CONFIRMED)

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='meetings', verbose_name='설계사(소유자)')
    customer = models.ForeignKey(
        'customers.Customer', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='meetings', verbose_name='고객')
    slot = models.ForeignKey(
        MeetingSlot, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='meetings')
    start_at = models.DateTimeField('시작 시각')  # 슬롯 시각 비정규화 복사(이력 보존·정렬)
    duration_min = models.PositiveSmallIntegerField('소요(분)', default=30)
    method = models.CharField('방식', max_length=10, choices=METHOD_CHOICES)
    location_detail = models.CharField('장소', max_length=200, blank=True, default='')  # 확정 시 profile.booking_location 스냅샷
    customer_note = models.TextField('고객 메모', blank=True, default='')
    status = models.CharField('상태', max_length=10, choices=STATUS_CHOICES, default=STATUS_CONFIRMED)
    google_event_id = models.CharField('구글 캘린더 이벤트 ID', max_length=1024, null=True, blank=True, default=None)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'meeting'
        verbose_name = '미팅'
        verbose_name_plural = '미팅'
        ordering = ['start_at']
        indexes = [models.Index(fields=['owner', 'status', 'start_at'])]

    def __str__(self):
        return f'{self.owner_id}/{self.customer_id}@{self.start_at:%Y-%m-%d %H:%M}'
