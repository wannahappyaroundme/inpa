"""개인 일정 도메인 — 소유자 전용. 일정(event)/할일(todo)/고정 차단(block) 통합 1모델.

★ owner FK 강제(OwnedQuerySetMixin). 예약(booking.MeetingSlot/Meeting)과는 별도 —
  캘린더가 읽어서 같이 그리기만 한다(공개예약·이중예약락 비파괴).
★ 타임존 규약(중요):
  - 단건(start_at/end_at): UTC 저장(datetime). 표시는 KST(Intl timeZone).
  - 반복 차단 TimeField(recur_*_time): KST 벽시계 그대로 저장(변환 금지 — 변환하면 9시간 밀림).
  - all_day / 시각 없는 todo: start_at 을 KST 정오(12:00)로 저장 → 양끝 타임존에서도 날짜 불변.
"""
from django.conf import settings
from django.db import models


class ScheduleItem(models.Model):
    KIND_EVENT = 'event'   # 일정(이벤트)
    KIND_TODO = 'todo'     # 할일(To-do)
    KIND_BLOCK = 'block'   # 고정으로 안 되는 시간(차단)
    KIND_CHOICES = (
        (KIND_EVENT, '일정'),
        (KIND_TODO, '할일'),
        (KIND_BLOCK, '차단'),
    )

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='schedule_items', verbose_name='설계사(소유자)')
    kind = models.CharField('종류', max_length=10, choices=KIND_CHOICES, default=KIND_EVENT)
    title = models.CharField('제목', max_length=120)
    memo = models.TextField('메모', blank=True, default='')
    customer = models.ForeignKey(
        'customers.Customer', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='schedule_items', verbose_name='연결 고객')

    # 단건(event / todo 마감 / 단건 block) — UTC 저장
    start_at = models.DateTimeField('시작/마감', null=True, blank=True)
    end_at = models.DateTimeField('종료', null=True, blank=True)
    all_day = models.BooleanField('온종일', default=False)

    # todo 전용 완료
    is_done = models.BooleanField('완료', default=False)
    done_at = models.DateTimeField('완료 시각', null=True, blank=True)

    # 반복 차단 전용(kind=block) — TimeField 는 KST 벽시계 저장(변환 금지)
    recur_weekday = models.PositiveSmallIntegerField('반복 요일(0=월..6=일)', null=True, blank=True)
    recur_start_time = models.TimeField('반복 차단 시작', null=True, blank=True)
    recur_end_time = models.TimeField('반복 차단 종료', null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'schedule_item'
        verbose_name = '일정 항목'
        verbose_name_plural = '일정 항목'
        ordering = ['start_at']
        indexes = [
            models.Index(fields=['owner', 'kind', 'start_at']),
            models.Index(fields=['owner', 'kind', 'recur_weekday']),
        ]

    def __str__(self):
        return f'{self.owner_id}/{self.kind}:{self.title}'
