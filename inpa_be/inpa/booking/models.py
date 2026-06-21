"""미팅 예약 도메인 — 소유자 전용 (Calendly식 내장 예약).

MeetingSlot — 설계사가 열어둔 일회성 가용 슬롯 (open→booked→canceled).
Meeting     — 고객이 공개 링크(/b/<token>)에서 확정한 예약.

★ owner FK 강제(OwnedQuerySetMixin). 공개 예약은 토큰의 customer.owner 슬롯만 본다.
★ 정직성 레드라인: 고객 자동발송 없음(링크 복사·붙여넣기). 공개 GET은 마스킹 이름만.
"""
from django.conf import settings
from django.db import models


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
    STATUS_CONFIRMED = 'confirmed'
    STATUS_CANCELED = 'canceled'
    STATUS_CHOICES = (
        (STATUS_CONFIRMED, '확정'),
        (STATUS_CANCELED, '취소됨'),
    )

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
