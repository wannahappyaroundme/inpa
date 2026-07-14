"""미팅 가용 시간 자동 산출 — 업무시간(WorkHour)에서 미팅·차단·버퍼를 빼고 빈 슬롯을 만든다.

설계사가 주간 업무시간만 정해두면, 고객은 공개 링크에서 '비어 있는 시간'을 바로 고른다.
(수동으로 슬롯을 하나하나 만들 필요 없음 — Calendly식)

★ 타임존 규약(중요 — config TIME_ZONE='Asia/Seoul', USE_TZ=True 전제):
  - WorkHour.start_time/end_time, ScheduleItem.recur_*_time = KST 벽시계 → 그 날짜의 KST aware로 결합.
  - Meeting.start_at, ScheduleItem.start_at/end_at = UTC 저장 → timezone.localtime()으로 KST aware 변환.
  - 모든 겹침 비교는 'KST aware datetime'으로 통일한다(절대 9시간 밀지 않게).
"""
from datetime import datetime, timedelta

from django.utils import timezone

from inpa.schedule.models import ScheduleItem

from .models import Meeting, WorkHour


def _overlaps(a_start, a_end, b_start, b_end):
    """두 [start, end) 구간이 겹치면 True."""
    return a_start < b_end and a_end > b_start


def generate_available_slots(owner, *, days=14, duration_min=30, buffer_min=60, step_min=30):
    """owner의 향후 `days`일 가용 슬롯(시작 시각, KST aware datetime) 리스트를 반환.

    업무시간 ∩ 미래 − (미팅 ± 버퍼) − (반복 차단) − (단건 차단/일정) 으로 계산.
    업무시간(WorkHour)이 하나도 없으면 빈 리스트(설계사가 아직 설정 전).
    """
    duration_min = duration_min or 30
    step_min = step_min or 30
    buffer = timedelta(minutes=buffer_min or 0)
    dur = timedelta(minutes=duration_min)

    workhours = list(WorkHour.objects.filter(owner=owner))
    if not workhours:
        return []

    now = timezone.localtime(timezone.now())  # KST aware
    today = now.date()
    horizon = today + timedelta(days=days)

    # ── 점유(busy) 구간 수집: KST aware (start, end) ──
    busy = []  # 단건 미팅(±버퍼) + 단건 차단/일정
    recur_blocks = []  # (weekday, start_time, end_time) — 반복 차단(KST 벽시계)

    meetings = Meeting.objects.filter(
        owner=owner, status__in=Meeting.ACTIVE_STATUSES,
        start_at__gte=now - timedelta(days=1),
    )
    for m in meetings:
        s = timezone.localtime(m.start_at)
        e = s + timedelta(minutes=m.duration_min or duration_min)
        busy.append((s - buffer, e + buffer))

    items = ScheduleItem.objects.filter(owner=owner)
    for it in items:
        if it.kind == ScheduleItem.KIND_BLOCK and it.recur_weekday is not None:
            if it.recur_start_time and it.recur_end_time:
                recur_blocks.append((it.recur_weekday, it.recur_start_time, it.recur_end_time))
            continue
        # 시각이 있는 단건 일정/차단만 점유로 본다(온종일·시각없는 할일은 제외).
        if it.kind in (ScheduleItem.KIND_BLOCK, ScheduleItem.KIND_EVENT) and it.start_at and not it.all_day:
            s = timezone.localtime(it.start_at)
            e = timezone.localtime(it.end_at) if it.end_at else s + dur
            busy.append((s, e))

    # ── 슬롯 생성 ──
    slots = []
    d = today
    while d < horizon:
        wd = d.weekday()  # Mon=0 .. Sun=6
        for wh in workhours:
            if wh.weekday != wd:
                continue
            day_start = timezone.make_aware(datetime.combine(d, wh.start_time))
            day_end = timezone.make_aware(datetime.combine(d, wh.end_time))
            cur = day_start
            while cur + dur <= day_end:
                slot_end = cur + dur
                if cur <= now:
                    cur += timedelta(minutes=step_min)
                    continue
                blocked = False
                # 반복 차단(같은 요일, KST 벽시계 → 그 날짜의 aware)
                for (bwd, bs, be) in recur_blocks:
                    if bwd != wd:
                        continue
                    rb_start = timezone.make_aware(datetime.combine(d, bs))
                    rb_end = timezone.make_aware(datetime.combine(d, be))
                    if _overlaps(cur, slot_end, rb_start, rb_end):
                        blocked = True
                        break
                # 단건 점유(미팅±버퍼, 차단/일정)
                if not blocked:
                    for (bstart, bend) in busy:
                        if _overlaps(cur, slot_end, bstart, bend):
                            blocked = True
                            break
                if not blocked:
                    slots.append(cur)
                cur += timedelta(minutes=step_min)
        d += timedelta(days=1)

    slots.sort()
    return slots


def is_slot_available(owner, start_at, *, duration_min=30, buffer_min=60):
    """단일 start_at(KST aware 또는 UTC aware)이 지금도 예약 가능한지 재확인(POST 확정 직전 검증).

    start_at 은 반드시 업무시간 안의 슬롯 경계와 정확히 일치해야 한다(임의 시각 차단).
    """
    if timezone.is_naive(start_at):
        start_at = timezone.make_aware(start_at)
    target = timezone.localtime(start_at)  # KST aware
    # ★ POST 재확인 grid = GET 노출 grid 와 동일해야 함(step_min=소요시간).
    # 예전엔 max(15,...) 바닥을 둬서 10~14분 소요 미팅은 GET 슬롯이 POST에서 안 잡혀 409가 났다.
    candidates = generate_available_slots(
        owner, days=60, duration_min=duration_min, buffer_min=buffer_min,
        step_min=duration_min or 30)
    return any(abs((c - target).total_seconds()) < 60 for c in candidates)
